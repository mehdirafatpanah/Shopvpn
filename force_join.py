# -*- coding: utf-8 -*-
"""
Middleware عضویت اجباری در کانال.

قبل از اجرای هر هندلر (پیام یا دکمه‌ی شیشه‌ای)، عضویت کاربر در کانال تنظیم‌شده
را چک می‌کند. اگر کاربر عضو نباشد، هندلر اصلی اجرا نمی‌شود و به‌جایش پیام
دعوت به عضویت + دکمه‌ی «بررسی مجدد» نمایش داده می‌شود.

طراحی محافظه‌کارانه: اگر بات دسترسی لازم به کانال را نداشته باشد (مثلاً ادمین
نیست یا آیدی اشتباه تنظیم شده)، به‌جای قفل‌کردن کل بات برای همه، عبور می‌دهد
(fail-open) تا یک تنظیم اشتباه، بات را کاملاً از کار نیندازد.
"""

import logging

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

CHECK_CALLBACK = "check_force_join"


def _join_keyboard(channel: str) -> InlineKeyboardMarkup:
    channel_display = channel.lstrip("@")
    link = f"https://t.me/{channel_display}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 عضویت در کانال", url=link)],
            [InlineKeyboardButton(text="✅ بررسی مجدد عضویت", callback_data=CHECK_CALLBACK)],
        ]
    )


async def is_channel_member(bot, channel: str, user_id: int) -> bool:
    """اگر بات دسترسی نداشته باشد یا خطایی رخ دهد، True برمی‌گرداند (fail-open)."""
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.warning("بررسی عضویت کانال %s برای کاربر %s ناموفق بود: %s", channel, user_id, e)
        return True


class ForceJoinMiddleware(BaseMiddleware):
    def __init__(self, db):
        super().__init__()
        self.db = db

    async def __call__(self, handler, event: TelegramObject, data: dict):
        settings = self.db.get_force_join_settings()
        if not settings["enabled"] or not settings["channel"]:
            return await handler(event, data)

        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # ادمین‌های بات از این محدودیت معاف هستند
        if self.db.is_admin(user.id):
            return await handler(event, data)

        # کاربرانی که با دیپ‌لینک تبلیغاتی nofj وارد شده‌اند، برای همیشه معاف‌اند
        if self.db.is_force_join_exempt(user.id):
            return await handler(event, data)

        # دکمه‌ی «بررسی مجدد» باید همیشه خودش اجرا شود (نه اینکه دوباره بلاک شود)
        if isinstance(event, CallbackQuery) and event.data == CHECK_CALLBACK:
            return await handler(event, data)

        # پیام /start با هر دیپ‌لینکی (هر پارامتری) باید خودش رد شود تا cmd_start
        # معافیت دائمی را ثبت کند؛ وگرنه این میدلور همان اولین پیامی که قرار است
        # معافیت را فعال کند را بلاک می‌کرد. توجه: یعنی هر کسی با پارامتر دلخواه
        # هم می‌تواند وارد شود و برای همیشه معاف بماند (طبق درخواست صریح کارفرما).
        if isinstance(event, Message) and (event.text or "").startswith("/start"):
            parts = event.text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                return await handler(event, data)

        bot = data.get("bot")
        member = await is_channel_member(bot, settings["channel"], user.id)
        if member:
            return await handler(event, data)

        text = "برای استفاده از بات، ابتدا باید در کانال زیر عضو شوید؛ سپس دکمه‌ی «بررسی مجدد عضویت» را بزنید:"
        markup = _join_keyboard(settings["channel"])
        if isinstance(event, CallbackQuery):
            await event.answer("هنوز عضو کانال نشده‌اید.", show_alert=True)
            try:
                await event.message.answer(text, reply_markup=markup)
            except Exception:
                pass
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=markup)
        return  # هندلر اصلی اجرا نمی‌شود
