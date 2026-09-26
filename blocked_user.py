# -*- coding: utf-8 -*-
"""
Middleware مسدودسازی کاربر.

قبل از اجرای هر هندلر (پیام یا دکمه‌ی شیشه‌ای)، اگر کاربر توسط ادمین بلاک شده
باشد، هندلر اصلی اجرا نمی‌شود و پیام «حساب شما مسدود شده» نمایش داده می‌شود.
ادمین‌های بات از این محدودیت معاف هستند (تا خودشون هیچ‌وقت قفل نشن).
"""

import asyncio
import logging

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from i18n import tr

logger = logging.getLogger(__name__)

BLOCKED_MESSAGE = "⛔️ حساب شما توسط مدیریت مسدود شده است. برای پیگیری با پشتیبانی تماس بگیرید."


class BlockedUserMiddleware(BaseMiddleware):
    def __init__(self, db):
        super().__init__()
        self.db = db

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # ثبت/به‌روزرسانی کاربر باید همینجا (اولین میدلور، قبل از هر بلاک‌کننده‌ای
        # مثل ForceJoinMiddleware) انجام شود، نه فقط داخل cmd_start. قبلاً فقط
        # cmd_start این کار را می‌کرد؛ یعنی وقتی عضویت اجباری فعال بود و کاربر
        # جدید هنوز عضو کانال نبود، /start او اصلاً به cmd_start نمی‌رسید و ردیف
        # کاربر هرگز در دیتابیس ساخته نمی‌شد - حتی بعد از عضویت و زدن «بررسی
        # مجدد» هم (چون آن کال‌بک هم add_or_update_user را صدا نمی‌زد) - نتیجه:
        # کاربر برای همیشه در پنل وب و مینی‌اپ قابل جستجو نبود.
        # این دو تماس هر دو sqlite3 synchronous هستند (SELECT/UPDATE-INSERT
        # واقعی روی دیسک) و قبلاً مستقیم روی event loop مشترکِ همه‌ی بات‌ها
        # اجرا می‌شدند - یعنی هر پیام هر کاربر (نه فقط ادمین‌ها) می‌توانست با
        # برخورد به قفل نوشتن (مثلاً هم‌زمانی با Mini App/پنل ادمین) کل
        # پردازش را تا busy_timeout فریز کند. با to_thread این دو کوئری روی
        # یک ترد جدا اجرا می‌شوند و فقط همین یک آپدیت را منتظر نگه می‌دارند،
        # نه بقیه‌ی بات‌ها/کاربران را.
        try:
            await asyncio.to_thread(
                self.db.add_or_update_user, user.id, user.username or "", user.first_name or ""
            )
        except Exception:
            logger.exception("ثبت/به‌روزرسانی کاربر %s ناموفق بود.", user.id)

        # ادمین‌های بات از این محدودیت معاف هستند (is_admin از کش در حافظه
        # می‌خواند، عملاً بلوکه‌کننده نیست - رجوع کنید به database.py)
        if self.db.is_admin(user.id):
            return await handler(event, data)

        db_user = await asyncio.to_thread(self.db.get_user, user.id)
        if not db_user or not db_user["is_blocked"]:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(tr(BLOCKED_MESSAGE), show_alert=True)
        elif isinstance(event, Message):
            await event.answer(tr(BLOCKED_MESSAGE))
        return  # هندلر اصلی اجرا نمی‌شود
