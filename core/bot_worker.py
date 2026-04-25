import asyncio
import time
from enum import Enum
from typing import Optional, List
from pyrogram import Client, filters, handlers
from pyrogram.types import Message
from pyrogram.errors import (
    FloodWait, PeerFlood, UserPrivacyRestricted,
    ChatWriteForbidden, UserBannedInChannel, AuthKeyUnregistered
)
from utils.logger import logger

class WorkerState(str, Enum):
    IDLE      = "idle"
    SENDING   = "sending"
    COOLDOWN  = "cooldown"
    STOPPED   = "stopped"
    UNAUTH    = "unauth"

class BotWorker:
    def __init__(self, client: Client, phone: str, clean_phone: str, 
                 targets: List[str], source_channel: str, loop_interval: int,
                 global_semaphore: asyncio.Semaphore):
        self.client = client
        self.phone = phone
        self.clean_phone = clean_phone
        self.targets = [t.strip() for t in targets if t.strip()]
        self.source_channel = str(source_channel).strip()
        self.loop_interval = max(1, int(loop_interval))
        self.global_semaphore = global_semaphore
        
        self.state = WorkerState.IDLE
        self.sent = 0
        self.errors = 0
        self.last_action = "Ready"
        self.last_dispatch_time = 0.0
        self.cooldown_until = 0.0
        
        self.is_loop_active = False
        self.queue = asyncio.Queue()
        self._dispatch_lock = asyncio.Lock() # Prevent race conditions on dispatch trigger
        
        self._worker_task: Optional[asyncio.Task] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._handler_group = 1 
        
        self.current_msg_id = None
        self.current_from_chat = None
        self._new_msg_event = asyncio.Event()

    def start(self):
        if self._worker_task and not self._worker_task.done(): return
        self._worker_task = asyncio.create_task(self._process_queue())
        self._setup_monitor()
        self.is_loop_active = True
        if self.current_msg_id: self._start_scheduler()
        logger.info(f"[{self.phone}] Worker activated.")

    def stop(self):
        self.is_loop_active = False
        if self._worker_task: self._worker_task.cancel()
        if self._loop_task: self._loop_task.cancel()
        self._remove_monitor()
        self.state = WorkerState.STOPPED

    def update_settings(self, source: str, interval: int, targets: List[str]):
        self.source_channel = str(source).strip()
        self.loop_interval = max(1, int(interval))
        self.targets = [t.strip() for t in targets if t.strip()]
        self._remove_monitor()
        self._setup_monitor()
        if self.is_loop_active: self._start_scheduler()

    def _start_scheduler(self):
        if self._loop_task: self._loop_task.cancel()
        self._loop_task = asyncio.create_task(self._reforward_scheduler())

    def _setup_monitor(self):
        if not self.client.is_connected: return
        async def dynamic_filter(_, __, m: Message):
            if not m.chat or not self.source_channel: return False
            target = self.source_channel.lower().replace("@", "")
            return str(m.chat.id) == self.source_channel or (m.chat.username or "").lower() == target
        async def on_new_message(client, message: Message):
            await self.trigger_dispatch(message.chat.id, message.id)
        self.client.add_handler(handlers.MessageHandler(on_new_message, filters.create(dynamic_filter)), group=self._handler_group)

    def _remove_monitor(self):
        if self.client.is_connected:
            try: self.client.remove_handler(None, group=self._handler_group)
            except: pass

    async def trigger_dispatch(self, from_chat_id: int, message_id: int):
        """Atomic dispatch trigger to prevent duplicate queues from spam-clicks or rapid events."""
        async with self._dispatch_lock:
            self.current_msg_id = message_id
            self.current_from_chat = from_chat_id
            while not self.queue.empty():
                try: self.queue.get_nowait()
                except asyncio.QueueEmpty: break
            for target in self.targets:
                await self.queue.put(target)
            self.last_dispatch_time = time.time()
            self._new_msg_event.set()
            if self.is_loop_active and (not self._loop_task or self._loop_task.done()):
                self._start_scheduler()

    async def _reforward_scheduler(self):
        try:
            while self.is_loop_active:
                self._new_msg_event.clear()
                try:
                    await asyncio.wait_for(self._new_msg_event.wait(), timeout=self.loop_interval * 60)
                    continue 
                except asyncio.TimeoutError:
                    if self.current_msg_id:
                        for target in self.targets: await self.queue.put(target)
                        self.last_dispatch_time = time.time()
        except asyncio.CancelledError: pass

    async def _process_queue(self):
        while True:
            try:
                while self.cooldown_until > time.monotonic():
                    self.state = WorkerState.COOLDOWN
                    await asyncio.sleep(1)
                
                target = await self.queue.get()
                self.state = WorkerState.SENDING
                
                # Global Throttle: Respect the system-wide limit
                async with self.global_semaphore:
                    success = await self._send_msg(target)
                
                if success: self.sent += 1
                else: self.errors += 1
                
                if self.state != WorkerState.UNAUTH:
                    self.state = WorkerState.IDLE
                self.queue.task_done()
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"[{self.phone}] Critical loop error: {e}")
                await asyncio.sleep(5)

    async def _send_msg(self, target: str):
        for attempt in range(1, 4):
            try:
                self.last_action = f"Forwarding: {target}"
                await self.client.forward_messages(chat_id=target, from_chat_id=self.current_from_chat, message_ids=self.current_msg_id)
                logger.info(f"[{self.phone}] ✅ Delivered to {target}")
                return True
            except AuthKeyUnregistered:
                self.state = WorkerState.UNAUTH
                self.last_action = "Session Revoked"
                self.stop()
                return False
            except FloodWait as e:
                wait = e.value + 5
                self.cooldown_until = time.monotonic() + wait
                self.last_action = f"FloodWait ({wait}s)"
                await self.queue.put(target)
                return False
            except (PeerFlood, UserPrivacyRestricted, ChatWriteForbidden, UserBannedInChannel):
                self.last_action = f"Blocked by {target}"
                return False
            except Exception as e:
                if attempt < 3: await asyncio.sleep(2 ** attempt)
                else: 
                    self.last_action = f"Error: {type(e).__name__}"
                    return False
        return False

    def to_dict(self):
        cd_rem = max(0, int(self.cooldown_until - time.monotonic()))
        return {
            "phone": self.phone, "clean_phone": self.clean_phone,
            "state": self.state.value, "sent": self.sent, "errors": self.errors,
            "last_action": self.last_action, "last_dispatch_time": self.last_dispatch_time,
            "targets_count": len(self.targets), "source_channel": self.source_channel,
            "loop_interval": self.loop_interval, "is_loop_active": self.is_loop_active,
            "cooldown_remaining": cd_rem
        }
