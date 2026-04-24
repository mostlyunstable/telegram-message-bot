"""
dispatcher.py — Smart Message Forwarding Engine

BEHAVIOR:
  1. New message arrives → dispatch immediately → start 15-min timer
  2. New message arrives DURING timer → cancel timer → dispatch → restart timer
  3. Timer expires with no new message → re-forward last message → restart timer
  4. Rapid burst (10 messages in 1s) → only LAST message survives
  5. Dispatch failure → timer continues unaffected

DESIGN:
  - asyncio.Event for instant wake-up (no polling)
  - asyncio.Task cancellation for instant timer kill
  - Single shared mutable state protected by asyncio.Lock
  - No threading, fully async-safe
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
from logger import logger

REFORWARD_INTERVAL = 15 * 60   # 15 minutes


# ──────────────────────────────────────────────────────────────
# DATA
# ──────────────────────────────────────────────────────────────
@dataclass
class MessageState:
    """Single source of truth for the latest message."""
    from_chat_id: Optional[int] = None
    message_id:   Optional[int] = None
    received_at:  float         = 0.0
    dispatch_count: int         = 0

    def update(self, from_chat_id: int, message_id: int):
        self.from_chat_id  = from_chat_id
        self.message_id    = message_id
        self.received_at   = time.time()
        self.dispatch_count = 0

    @property
    def is_valid(self) -> bool:
        return self.from_chat_id is not None and self.message_id is not None


# ──────────────────────────────────────────────────────────────
# DISPATCHER
# ──────────────────────────────────────────────────────────────
class Dispatcher:
    """
    Smart message forwarding engine.

    Usage:
        dispatcher = Dispatcher(account_manager)
        asyncio.create_task(dispatcher.run())       # start the loop
        await dispatcher.enqueue(from_id, msg_id)  # call on new message
    """

    def __init__(self, account_manager):
        self.account_manager = account_manager

        # Latest message state — shared, protected by lock
        self._state   = MessageState()
        self._lock    = asyncio.Lock()

        # asyncio.Event: set() when a new message arrives, cleared after consumption
        self._new_msg_event = asyncio.Event()

        # The currently running 15-minute re-forward task
        self._reforward_task: Optional[asyncio.Task] = None

        self._running = False

    # ──────────────────────────────────────────────────────────
    # PUBLIC API — called by the Telegram client handler
    # ──────────────────────────────────────────────────────────
    async def enqueue(self, from_chat_id: int, message_id: int):
        """
        Called when a new Telegram message is received.
        Thread-safe, non-blocking, instant.

        EDGE CASE: Rapid burst → only the LAST call wins because
        each call overwrites _state before the event is consumed.
        """
        async with self._lock:
            self._state.update(from_chat_id, message_id)

        # Wake up the main loop immediately
        self._new_msg_event.set()
        logger.info(f"📥 Enqueued message {message_id} from {from_chat_id}")

    # ──────────────────────────────────────────────────────────
    # MAIN LOOP — runs forever
    # ──────────────────────────────────────────────────────────
    async def run(self):
        """
        Main event loop. Waits for new messages and manages
        the 15-minute re-forward cycle.
        """
        self._running = True
        logger.info("🚀 Dispatcher running — Smart Forwarding mode active")

        while self._running:
            # ── STEP 1: Wait for a new message to arrive ──
            await self._new_msg_event.wait()
            self._new_msg_event.clear()

            if not self._running:
                break

            # ── STEP 2: Cancel the existing re-forward cycle ──
            # This kills the 15-min sleep instantly if it's running
            await self._cancel_reforward()

            # ── STEP 3: Read the latest message (snapshot) ──
            async with self._lock:
                from_chat_id = self._state.from_chat_id
                message_id   = self._state.message_id

            if from_chat_id is None or message_id is None:
                continue

            logger.info(f"📨 Processing message {message_id} — dispatching NOW")

            # ── STEP 4: Dispatch immediately (non-blocking) ──
            # Fire-and-forget dispatch so it never blocks the loop
            asyncio.create_task(self._safe_dispatch(from_chat_id, message_id))

            # ── STEP 5: Start the 15-min re-forward cycle ──
            self._reforward_task = asyncio.create_task(
                self._reforward_loop(from_chat_id, message_id)
            )

        logger.info("🛑 Dispatcher stopped.")

    # ──────────────────────────────────────────────────────────
    # RE-FORWARD LOOP — cancellable 15-min cycle
    # ──────────────────────────────────────────────────────────
    async def _reforward_loop(self, from_chat_id: int, message_id: int):
        """
        Runs indefinitely for a given message, re-forwarding every 15 minutes.
        Gets cancelled the moment a new message arrives in enqueue().

        EDGE CASE: CancelledError during asyncio.sleep() is caught cleanly.
        EDGE CASE: Dispatch failure doesn't break the loop — it logs and continues.
        """
        try:
            while True:
                logger.info(
                    f"⏳ Re-forward timer started — {REFORWARD_INTERVAL // 60}min "
                    f"until next forward of message {message_id}"
                )

                # ── CANCELLABLE SLEEP ──
                # asyncio.sleep() suspends without blocking the event loop.
                # .cancel() on this task wakes it up with CancelledError immediately.
                await asyncio.sleep(REFORWARD_INTERVAL)

                # ── Check the latest message BEFORE re-forwarding ──
                # A new message may have arrived while we slept but we weren't cancelled
                # (this is an extra safety check, cancellation should handle it)
                async with self._lock:
                    current_msg_id = self._state.message_id

                if current_msg_id != message_id:
                    # A new message took over — stop this loop
                    logger.info(
                        f"🔄 Message {message_id} superseded by {current_msg_id} "
                        f"— stopping old re-forward loop"
                    )
                    return

                # ── RE-FORWARD ──
                logger.info(
                    f"🔁 15min elapsed — re-forwarding message {message_id}"
                )
                await self._safe_dispatch(from_chat_id, message_id)

                # Loop back → sleep another 15 min

        except asyncio.CancelledError:
            # Clean cancellation — a new message arrived
            logger.info(
                f"✋ Re-forward loop for message {message_id} cancelled "
                f"(new message arrived)"
            )

    # ──────────────────────────────────────────────────────────
    # DISPATCH — sends to all accounts/targets
    # ──────────────────────────────────────────────────────────
    async def _safe_dispatch(self, from_chat_id: int, message_id: int):
        """
        Dispatches the message to all account workers.
        Failures are logged but never propagate — timer logic is unaffected.
        """
        try:
            await self.account_manager.distribute(from_chat_id, message_id)
            async with self._lock:
                self._state.dispatch_count += 1
        except Exception as e:
            # EDGE CASE: Dispatch failure → log and continue, do NOT crash the loop
            logger.error(f"❌ Dispatch error for message {message_id}: {e}")

    # ──────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────
    async def _cancel_reforward(self):
        """Cancel the running re-forward task and wait for it to finish."""
        if self._reforward_task and not self._reforward_task.done():
            self._reforward_task.cancel()
            try:
                await self._reforward_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reforward_task = None

    def stop(self):
        """Gracefully stop the dispatcher."""
        self._running = False
        # Wake the main loop so it can exit
        self._new_msg_event.set()
        if self._reforward_task and not self._reforward_task.done():
            self._reforward_task.cancel()

    @property
    def state_snapshot(self) -> dict:
        """Return a safe read-only snapshot of current state for monitoring."""
        return {
            "message_id":     self._state.message_id,
            "from_chat_id":   self._state.from_chat_id,
            "received_at":    self._state.received_at,
            "dispatch_count": self._state.dispatch_count,
            "timer_active":   (
                self._reforward_task is not None
                and not self._reforward_task.done()
            ),
        }
