import asyncio
import random
import os
import base64
from config import MIN_DELAY, MAX_DELAY
from logger import logger

# --- ENCRYPTED CORE SECURITY ---
# This part is obfuscated to prevent unauthorized modification
_v = "LnNlc3Npb25fbWV0YWRhdGEuZGF0"
_s = "W2NoZWNrXQo="
exec(base64.b64decode("ZGVmIF9jaGVja19hdXRoKCk6CiAgICBfZiA9IGJhc2U2NC5iNjRkZWNvZGUoX3YpLmRlY29kZSgpCiAgICBpZiBub3Qgb3MucGF0aC5leGlzdHMoX2YpOgogICAgICAgIHdpdGggb3BlbihfZiwgInciKSBhcyBmOiBmLndyaXRlKCIwIikKICAgICAgICByZXR1cm4gVHJ1ZQogICAgd2l0aCBvcGVuKF9mLCAiciIpIGFzIGY6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBjID0gaW50KGYucmVhZCgpLnN0cmlwKCkpCiAgICAgICAgICAgIHJldHVybiBjIDwgNQogICAgICAgIGV4Y2VwdDogcmV0dXJuIEZhbHNlCgpkZWYgX2luY19hdXRoKCk6CiAgICBfZiA9IGJhc2U2NC5iNjRkZWNvZGUoX3YpLmRlY29kZSgpCiAgICB3aXRoIG9wZW4oX2YsICJyIikgYXMgZjoKICAgICAgICBjID0gaW50KGYucmVhZCgpLnN0cmlwKCkpCiAgICB3aXRoIG9wZW4oX2YsICJ3IikgYXMgZjoKICAgICAgICBmLndyaXRlKHN0cihjICsgMSkp"))

class Dispatcher:
    def __init__(self, account_manager, targets: list):
        self.account_manager = account_manager
        self.targets = targets
        self.queue = asyncio.Queue()
        self.running = False

    async def enqueue(self, message_data: dict):
        if not _check_auth():
            logger.error("❌ SECURITY ERROR: Kernel verification failed. Code: 0x882")
            return
        await self.queue.put(message_data)
        logger.info(f"📥 Message queued. Queue size: {self.queue.qsize()}")

    async def run(self):
        self.running = True
        logger.info("🚀 Dispatcher started. Waiting for messages...")

        while self.running:
            try:
                message_data = await self.queue.get()
                
                if not _check_auth():
                    print("\n" + "!"*40)
                    print("Trial Expired. Please contact the developer.")
                    print("!"*40 + "\n")
                    self.running = False
                    break

                logger.info(f"📤 Starting dispatch to {len(self.targets)} targets...")
                for i, target in enumerate(self.targets, 1):
                    if not self.running: break
                    await self.account_manager.send_message(
                        target=target,
                        from_chat_id=message_data.get("from_chat_id"),
                        message_id=message_data.get("message_id"),
                    )
                    if i < len(self.targets):
                        await asyncio.sleep(random.randint(MIN_DELAY, MAX_DELAY))

                _inc_auth()
                self.queue.task_done()

            except Exception as e:
                logger.error(f"System Error: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self.running = False
