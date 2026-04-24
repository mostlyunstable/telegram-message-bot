"""
main.py — Production entry point.

FIXES:
  - BUG: load_targets() called but result passed nowhere (AccountManager
    now reads targets from config; load_targets() result was unused).
    Removed the dead code path.
  - BUG: dispatcher.enqueue() signature changed to (from_chat_id, message_id)
    but main.py was calling it with a dict in MOCK_MODE. Fixed.
  - BUG: monitor_client.idle() swallows KeyboardInterrupt before finally
    block can run, leaving workers dangling. Fixed with explicit shutdown event.
  - BUG: Signal handlers registered AFTER dispatcher.run() task created,
    meaning a SIGTERM in the initialization window is unhandled. Fixed.
  - IMPROVEMENT: shutdown_event drives clean teardown instead of relying on
    exception propagation.
"""

import asyncio
import os
import signal
import traceback

from config import ACCOUNTS, TARGETS_FILE, SOURCE_CHANNEL, MOCK_MODE
from account_manager import AccountManager
from dispatcher import Dispatcher
from monitor import Monitor
from logger import logger


async def main():
    logger.info("=" * 55)
    logger.info("   TELEGRAM BULK MESSENGER — Worker Architecture")
    logger.info("=" * 55)

    # ── 1. Init account manager ──
    mgr = AccountManager()
    try:
        await mgr.initialize()
    except RuntimeError as e:
        logger.error(str(e))
        return

    if not mgr.workers:
        logger.error("No authenticated workers available. "
                     "Log in via the Web Panel first.")
        return

    # ── 2. Start independent worker loops ──
    mgr.start_all()

    # ── 3. Create dispatcher ──
    dispatcher = Dispatcher(mgr)

    # ── 4. Shutdown event — driven by signals OR clean exit ──
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("🛑 Shutdown signal received.")
        shutdown_event.set()
        dispatcher.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, OSError):
            # Windows doesn't support add_signal_handler
            pass

    # ── 5. Run ──
    if MOCK_MODE:
        logger.info("🛠️  MOCK MODE — injecting test messages.")
        dispatcher_task = asyncio.create_task(dispatcher.run())
        # Simulate burst: 3 messages arriving quickly
        for i in range(1, 4):
            await dispatcher.enqueue(123456789, i)
            await asyncio.sleep(0.2)
        # Let it run for a moment then stop
        await asyncio.sleep(5)
        dispatcher.stop()
        try:
            await asyncio.wait_for(dispatcher_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    else:
        # Use first authenticated worker's client to monitor the source channel
        monitor_client = mgr.workers[0].client
        monitor = Monitor(monitor_client, dispatcher)
        logger.info(f"👁️  Monitoring channel: {SOURCE_CHANNEL}")

        dispatcher_task = asyncio.create_task(dispatcher.run())

        try:
            # Run until shutdown signal or keyboard interrupt
            idle_task = asyncio.create_task(monitor_client.idle())
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, pending = await asyncio.wait(
                [idle_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        finally:
            dispatcher.stop()
            try:
                await asyncio.wait_for(dispatcher_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    # ── 6. Graceful shutdown ──
    await mgr.stop_all()
    logger.info("✅ Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception:
        traceback.print_exc()
