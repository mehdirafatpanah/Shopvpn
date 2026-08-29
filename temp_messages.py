# -*- coding: utf-8 -*-
"""پیام موقت: ارسال پیام + زمان‌بندی حذف خودکارش بعد از مدت مشخص.

send_temp_message از هر جای دیگر کد (هندلر ادمین، تحویل کانفیگ، شماره کارت و ...)
قابل استفاده است. temp_message_cleanup_loop باید به ازای هر بات (اصلی/نمایندگی)
یک‌بار در bot_manager.py استارت شود، دقیقاً مثل renewal_reminder_loop/backup_loop.
"""

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def send_temp_message(bot, db, chat_id: int, text: str, expire_seconds: int, **kwargs):
    """پیام را می‌فرستد و حذف خودکارش را بعد از expire_seconds ثانیه زمان‌بندی می‌کند."""
    msg = await bot.send_message(chat_id, text, **kwargs)
    delete_at = (datetime.utcnow() + timedelta(seconds=expire_seconds)).isoformat()
    await asyncio.to_thread(db.schedule_temp_message, chat_id, msg.message_id, delete_at)
    return msg


async def temp_message_cleanup_loop(bot, db, interval: float = 30.0):
    while True:
        try:
            due = await asyncio.to_thread(db.pop_due_temp_messages)
            for row in due:
                try:
                    await bot.delete_message(row["chat_id"], row["message_id"])
                except Exception:
                    pass
        except Exception:
            logger.exception("temp_message_cleanup_loop ناموفق بود (db_path=%s).", db.db_path)
        await asyncio.sleep(interval)
