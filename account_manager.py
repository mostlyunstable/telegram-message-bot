"""
AccountManager — Orchestrates all AccountWorkers.

Updated for TARGET MAPPING:
Instead of distributing all targets round-robin, it passes the 
specific targets to each AccountWorker on initialization.
When a new message arrives, it commands every available worker 
to dispatch to its own targets.
"""

import asyncio
import os
from pyrogram import Client
from pyrogram.errors import AuthKeyUnregistered, SessionRevoked
from logger import logger
from config import MOCK_MODE, ACCOUNTS, TARGETS_FILE
from account_worker import AccountWorker, WorkerState


class AccountManager:
    def __init__(self):
        self.account_configs = ACCOUNTS
        self.workers: list[AccountWorker] = []
        
        # Load global targets for fallback mapping
        self.global_targets = self._load_global_targets()

    def _load_global_targets(self) -> list:
        if not os.path.exists(TARGETS_FILE):
            return []
        targets = []
        with open(TARGETS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    targets.append(int(line) if line.lstrip("-").isdigit() else line)
        return targets

    async def initialize(self):
        os.makedirs("sessions", exist_ok=True)

        for i, cfg in enumerate(self.account_configs):
            # FEATURE 1: Account -> Target Mapping
            # If account has specific targets, use them. 
            # Otherwise, partition global targets or give them a copy.
            # For simplicity if config doesn't have per-account targets yet,
            # we just give them a partition of the global targets.
            targets = cfg.get("targets", [])
            if not targets and self.global_targets:
                # Divide global targets equally among accounts
                num_accounts = len(self.account_configs)
                chunk_size = max(1, len(self.global_targets) // num_accounts)
                start_idx = i * chunk_size
                # Give last account the remainder
                end_idx = start_idx + chunk_size if i < num_accounts - 1 else len(self.global_targets)
                targets = self.global_targets[start_idx:end_idx]

            if MOCK_MODE:
                worker = await self._create_mock_worker(cfg, i, targets)
                if worker:
                    self.workers.append(worker)
                continue

            worker = await self._create_real_worker(cfg, i, targets)
            if worker:
                self.workers.append(worker)
            await asyncio.sleep(3)

        if not self.workers:
            raise RuntimeError("No accounts initialized. Authenticate in the Web Panel.")
        logger.info(f"✅ {len(self.workers)} worker(s) ready.")

    async def _create_real_worker(self, cfg: dict, index: int, targets: list) -> AccountWorker | None:
        name = cfg["name"]
        clean_phone = cfg["phone"].replace(" ", "").replace("-", "")
        client = Client(
            name=cfg["session_name"],
            api_id=cfg["api_id"],
            api_hash=cfg["api_hash"],
            phone_number=clean_phone,
            device_model="iPhone 15 Pro Max",
            system_version="iOS 17.5.1",
            app_version="10.14.1",
            lang_code="en",
        )
        try:
            await client.connect()
            me = await client.get_me()
            await client.disconnect()
            await client.start()
            logger.info(f"  ✅ [{name}] Logged in as {me.first_name} ({me.id})")
            return AccountWorker(client, name, index, targets)
        except (AuthKeyUnregistered, SessionRevoked) as e:
            logger.error(f"  ❌ [{name}] Session invalid: {type(e).__name__}. Deleting corrupted session.")
            await self._safe_disconnect(client)
            # Delete the invalid session file so the dashboard resets to Auth Required
            session_file = f"{cfg['session_name']}.session"
            if os.path.exists(session_file):
                try:
                    os.remove(session_file)
                except Exception:
                    pass
            return None
        except Exception as e:
            logger.error(f"  ❌ [{name}] Init failed: {type(e).__name__}: {e}")
            await self._safe_disconnect(client)
            return None

    async def _create_mock_worker(self, cfg: dict, index: int, targets: list) -> AccountWorker | None:
        class MockClient:
            name = cfg["session_name"]
            async def forward_messages(self, **kw):
                import random
                from pyrogram.errors import FloodWait, PeerFlood
                r = random.random()
                if r < 0.15: raise FloodWait(10)
                if r < 0.25: raise PeerFlood()
                await asyncio.sleep(0.05)
            async def start(self): pass
            async def stop(self): pass

        logger.info(f"  ✅ [MOCK] {cfg['name']}")
        return AccountWorker(MockClient(), cfg["name"], index, targets)

    def start_all(self):
        for w in self.workers:
            w.start()
        logger.info(f"🚀 {len(self.workers)} workers started.")

    async def stop_all(self):
        for w in self.workers:
            w.stop()
        await asyncio.gather(*(w.wait_stopped() for w in self.workers), return_exceptions=True)
        for w in self.workers:
            try: await w.client.stop()
            except Exception: pass
        logger.info("All workers stopped.")

    async def distribute(self, from_chat_id: int, message_id: int):
        """
        FEATURE 2: Tell EVERY worker to dispatch this message to its OWN targets.
        If a worker is offline or in error state, it skips.
        """
        active_workers = [w for w in self.workers if w.state != WorkerState.STOPPED and w.state != WorkerState.ERROR]
        
        logger.info(f"📤 Notifying {len(active_workers)} workers to dispatch message ID {message_id}")
        
        for worker in active_workers:
            await worker.enqueue_dispatch(from_chat_id, message_id)

    def get_all_status(self) -> list[dict]:
        return [w.to_dict() for w in self.workers]

    def get_totals(self) -> dict:
        return {
            "total_workers": len(self.workers),
            "active": sum(1 for w in self.workers if w.state == WorkerState.SENDING),
            "idle": sum(1 for w in self.workers if w.state == WorkerState.IDLE),
            "cooldown": sum(1 for w in self.workers if w.state == WorkerState.COOLDOWN),
            "error": sum(1 for w in self.workers if w.state == WorkerState.ERROR),
            "total_sent": sum(w.sent for w in self.workers),
            "total_errors": sum(w.errors for w in self.workers),
        }

    @staticmethod
    async def _safe_disconnect(client):
        try: await client.disconnect()
        except Exception: pass
