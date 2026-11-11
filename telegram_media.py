# -*- coding: utf-8 -*-
"""Helpers for copying Telegram messages and media groups without downloading files."""
import asyncio
from collections import defaultdict

_GROUPS = {}

async def collect_media_group(message, window: float = 1.25):
    """Collect one Telegram album. Exactly one update receives the completed list."""
    group_id = getattr(message, "media_group_id", None)
    if not group_id:
        return [message]
    key = (int(message.chat.id), str(group_id))
    item = _GROUPS.setdefault(key, {"messages": {}, "lock": asyncio.Lock(), "done": False})
    item["messages"][int(message.message_id)] = message
    await asyncio.sleep(window)
    async with item["lock"]:
        if item["done"]:
            return None
        item["done"] = True
        result = [item["messages"][mid] for mid in sorted(item["messages"])]
        _GROUPS.pop(key, None)
        return result

async def copy_messages(bot, chat_id: int, from_chat_id: int, message_ids):
    """Copy one message or an album; supports every copyable Telegram media type."""
    ids = [int(x) for x in (message_ids or []) if str(x).lstrip("-").isdigit()]
    if not ids:
        return []
    if len(ids) == 1:
        result = await bot.copy_message(chat_id, from_chat_id=from_chat_id, message_id=ids[0])
        return [result]
    return await bot.copy_messages(chat_id, from_chat_id=from_chat_id, message_ids=ids)
