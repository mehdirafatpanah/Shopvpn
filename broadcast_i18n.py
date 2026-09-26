# -*- coding: utf-8 -*-
"""Language policy for admin broadcasts.

Broadcast content written by an administrator is user-authored/custom content.
It MUST be delivered verbatim and must never pass through the UI translation
catalog. System messages around the broadcast (confirmation, errors, counters,
etc.) are localized separately by the caller.
"""
from __future__ import annotations

from typing import Any


def custom_broadcast_text(text: str) -> str:
    """Return admin-authored broadcast text unchanged.

    Keeping this as an explicit helper makes the no-translation contract easy
    to audit and test. It intentionally does not call ``tr``/``localized``.
    """
    return text if isinstance(text, str) else str(text or "")


async def send_scheduled_broadcast(bot: Any, chat_id: int, text: str, **kwargs):
    """Deliver a scheduled custom broadcast verbatim.

    The recipient's language affects system notifications, not text authored
    by an administrator. This function is the single delivery path used by the
    scheduled-broadcast worker.
    """
    return await bot.send_message(chat_id, custom_broadcast_text(text), **kwargs)
