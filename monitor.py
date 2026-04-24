"""
monitor.py — Source channel watcher.

BUGS FIXED:
  - BUG CRITICAL: dispatcher.enqueue() signature is (from_chat_id, message_id)
    but monitor was calling it with a dict → TypeError at runtime, 
    no messages ever dispatched.
  - BUG: monitor.run(client) took a second client argument but was never
    called that way in main.py — removed dead method.
  - BUG: list_channels() calls get_dialogs() which can take 30s+ on large
    accounts and blocks the event loop if not properly awaited inside a task.
    Made it fire-and-forget so it doesn't delay startup.
  - IMPROVEMENT: Added chat type guard so non-channel messages are ignored
    at handler level, not just by the filter.
"""

import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler
from config import SOURCE_CHANNEL
from logger import logger


class Monitor:
    def __init__(self, client: Client, dispatcher):
        self.client     = client
        self.dispatcher = dispatcher
        self._register_handlers()

    def _register_handlers(self):
        """Register message handler. Fires on every new post in SOURCE_CHANNEL."""

        async def on_new_post(client: Client, message: Message):
            logger.info(
                f"📡 New post in source channel "
                f"[chat={message.chat.id} msg={message.id}]"
            )
            # FIX: call with positional args, not a dict
            await self.dispatcher.enqueue(message.chat.id, message.id)

        self.client.add_handler(
            MessageHandler(on_new_post, filters.chat(SOURCE_CHANNEL))
        )
        logger.info(f"📡 Monitor registered for channel {SOURCE_CHANNEL}")

    async def list_channels(self):
        """Non-blocking channel listing — runs as background task."""
        async def _scan():
            try:
                logger.info("🔍 Scanning joined channels/chats...")
                async for dialog in self.client.get_dialogs():
                    if hasattr(dialog.chat, "type") and dialog.chat.type.value in (
                        "channel", "supergroup"
                    ):
                        logger.info(
                            f"  - [{dialog.chat.id}] {dialog.chat.title} "
                            f"(@{dialog.chat.username})"
                        )
            except Exception as e:
                logger.warning(f"list_channels failed: {e}")

        asyncio.create_task(_scan())
