import asyncio
import itertools
from pyrogram import Client
from pyrogram.errors import (
    FloodWait, PeerFlood, UserPrivacyRestricted,
    InputUserDeactivated, UserIsBlocked
)
from config import ACCOUNTS, MOCK_MODE
from logger import logger

class AccountManager:
    """
    Manages a pool of Telegram user accounts.
    Distributes sending load in a round-robin fashion.
    """

    def __init__(self):
        self.clients = []
        self._cycle = None

    async def initialize(self):
        """Login and initialize all configured accounts."""
        if MOCK_MODE:
            logger.info("🛠️  RUNNING IN MOCK MODE (Simulation Only)")
            async def mock_stop(): pass
            for acc in ACCOUNTS:
                # Create a mock object that mimics a client
                mock_client = type('MockClient', (), {
                    'name': acc['session_name'], 
                    'is_mock': True,
                    'stop': mock_stop
                })()
                self.clients.append(mock_client)
            self._cycle = itertools.cycle(self.clients)
            return

        import os
        os.makedirs("sessions", exist_ok=True)

        for acc in ACCOUNTS:
            logger.info(f"Initializing account: {acc['name']} ({acc['phone']})")
            client = Client(
                name=acc["session_name"],
                api_id=acc["api_id"],
                api_hash=acc["api_hash"],
                phone_number=acc["phone"],
            )
            try:
                await client.start()
                me = await client.get_me()
                logger.info(f"  ✅ Logged in as: {me.first_name} (@{me.username})")
                self.clients.append(client)
            except Exception as e:
                logger.error(f"  ❌ Failed to start {acc['name']}: {e}")

        if not self.clients:
            raise RuntimeError("No accounts could be initialized. Check config.py.")

        self._cycle = itertools.cycle(self.clients)
        logger.info(f"Account pool ready with {len(self.clients)} account(s).")

    def next_client(self) -> Client:
        return next(self._cycle)

    async def send_message(self, target: str, from_chat_id: int, message_id: int) -> bool:
        client = self.next_client()
        acc_name = client.name.split("/")[-1]

        if MOCK_MODE:
            await asyncio.sleep(0.5) 
            logger.info(f"  [{acc_name}] 📱 (MOCK) Forwarded message to {target}")
            return True

        try:
            # Using forward_messages ENSURES the "Forwarded from..." bar is visible
            await client.forward_messages(
                chat_id=target,
                from_chat_id=from_chat_id,
                message_ids=message_id
            )

            logger.info(f"  [{acc_name}] ✅ Forwarded to {target}")
            return True
        except FloodWait as e:
            logger.warning(f"  [{acc_name}] ⚠️ FloodWait: sleeping {e.value}s before retrying.")
            await asyncio.sleep(e.value)
            return await self.send_message(target, message_text, from_chat_id, message_id)
        except (PeerFlood, UserPrivacyRestricted, InputUserDeactivated, UserIsBlocked) as e:
            logger.warning(f"  [{acc_name}] ⚠️ Skipping {target}: {type(e).__name__}")
            return False
        except Exception as e:
            logger.error(f"  [{acc_name}] ❌ Error sending to {target}: {e}")
            return False

    async def stop_all(self):
        for client in self.clients:
            if hasattr(client, 'stop'):
                if asyncio.iscoroutine(client.stop):
                    await client.stop()
                else:
                    client.stop()
        logger.info("All accounts disconnected.")
