from i18n import tr
from notification_i18n import send_telegram
# -*- coding: utf-8 -*-
"""هدیه‌ی عضویت (بند ۴۶ اسپک).

به‌صورت دوره‌ای بررسی می‌کند کدام کاربران از «signup_gift_delay_days» روز قبل
عضو شده‌اند و تا الان هیچ خریدی نکرده‌اند؛ به هر کدام دقیقاً یک‌بار مبلغ ثابت
«signup_gift_amount» به کیف پول اضافه می‌شود (منطق واقعی در
Database.grant_pending_signup_gifts) و پیام اطلاع‌رسانی برایش ارسال می‌شود.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _notify(bot, db, user_id: int, amount: int):
    try:
        await send_telegram(
            bot, db, user_id,
            tr(f"🎁 هدیه‌ی عضویت شما فعال شد!\n{amount:,} تومان به کیف پولت اضافه شد، همین حالا سرویس بگیر."),
        )
    except Exception as exc:
        logger.info("ارسال پیام هدیه‌ی عضویت به کاربر %s ناموفق بود: %s", user_id, exc)


async def signup_gift_once(bot, db) -> list:
    granted = await asyncio.to_thread(db.grant_pending_signup_gifts)
    for item in granted:
        await _notify(bot, db, item["user_id"], item["amount"])
    return granted


async def signup_gift_loop(bot, db, interval: int = 3600):
    """حلقه‌ی ساعتی؛ تنظیمات هر دور دوباره از دیتابیس خوانده می‌شوند."""
    while True:
        try:
            await signup_gift_once(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در حلقه‌ی هدیه‌ی عضویت")
        await asyncio.sleep(max(300, int(interval)))
