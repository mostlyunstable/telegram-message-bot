import os
import asyncio
from typing import List, Optional
from pyrogram import Client
from pyrogram.errors import AuthKeyUnregistered
from core.bot_worker import BotWorker
from utils.logger import logger
from utils.config_loader import load_config

class BotManager:
    """
    Orchestrates multiple BotWorkers. Handles initialization,
    session persistence, and global rate limiting.
    """
    def __init__(self):
        self.workers: List[BotWorker] = []
        self._lock = asyncio.Lock()
        # Global Concurrency Limit: Max 3 simultaneous forward operations
        # across ALL accounts to stay under Telegram's IP-based rate limits.
        self.global_semaphore = asyncio.Semaphore(3)
        
    async def initialize(self):
        """Discovers and starts all authorized sessions."""
        async with self._lock:
            config = load_config()
            phones = [p.strip() for p in config.get("phones", "").split("\n") if p.strip()]
            
            for phone in phones:
                p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
                if any(w.phone == phone for w in self.workers):
                    continue
                    
                session_file = f"sessions/session_{p_clean}"
                if os.path.exists(f"{session_file}.session"):
                    await self._start_worker(phone, p_clean, config)

    async def _start_worker(self, phone: str, p_clean: str, config: dict):
        try:
            settings = config.get("account_settings", {}).get(p_clean, {})
            source = settings.get("source_channel") or config.get("source_channel", "")
            interval = settings.get("loop_interval") or config.get("loop_interval", 15)
            targets = settings.get("targets")
            if not targets:
                targets = [t.strip() for t in config.get("targets", "").split("\n") if t.strip()]

            client = Client(
                f"sessions/session_{p_clean}",
                api_id=int(config["api_id"]),
                api_hash=config["api_hash"],
                workdir=".",
                device_model="iPhone 15 Pro Max",
                system_version="iOS 17.5.1",
                app_version="10.14.1",
                lang_code="en"
            )
            await client.start()
            
            # Pass the global semaphore to the worker
            worker = BotWorker(client, phone, p_clean, targets, source, interval, self.global_semaphore)
            self.workers.append(worker)
            
            if settings.get("is_loop_active"):
                worker.start()
                
            logger.info(f"[{phone}] Connected and ready.")
        except AuthKeyUnregistered:
            logger.error(f"[{phone}] Session expired. Manual re-auth required.")
        except Exception as e:
            logger.error(f"[{phone}] Start failed: {e}")

    def get_worker(self, identifier: str) -> Optional[BotWorker]:
        for w in self.workers:
            if identifier in [w.phone, w.clean_phone]:
                return w
        return None

    def get_all_status(self) -> List[dict]:
        return [w.to_dict() for w in self.workers]

    async def shutdown(self):
        """Cleanup all workers and clients."""
        for w in self.workers:
            w.stop()
            try: await w.client.stop()
            except: pass
        self.workers = []
