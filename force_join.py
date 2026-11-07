#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from i18n import tr
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

import asyncio
import logging

from aiogram import BaseMiddleware
from force_join_channels import parse_channels, join_link
from aiogram.types import TelegramObject, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

CHECK_CALLBACK = "check_force_join"
TERMS_ACCEPT_CALLBACK = "accept_terms"


def terms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr("✅ می‌پذیرم و ادامه می‌دهم"), callback_data=TERMS_ACCEPT_CALLBACK)],
        ]
    )


def _join_keyboard(channels) -> InlineKeyboardMarkup:
    channels = parse_channels(channels)
    rows = []
    for index, channel in enumerate(channels, 1):
        link = join_link(channel)
        if not link:
            continue
        label = tr("📢 عضویت در کانال")
        if len(channels) > 1:
            label = f"{label} {index}"
        rows.append([InlineKeyboardButton(text=label, url=link)])
    rows.append([InlineKeyboardButton(text=tr("✅ بررسی مجدد عضویت"), callback_data=CHECK_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_text(count: int) -> str:
    if count > 1:
        return "برای استفاده از بات، ابتدا باید در کانال‌های زیر عضو شوید؛ سپس دکمه‌ی «بررسی مجدد عضویت» را بزنید:"
    return "برای استفاده از بات، ابتدا باید در کانال زیر عضو شوید؛ سپس دکمه‌ی «بررسی مجدد عضویت» را بزنید:"


async def is_channel_member(bot, channel: str, user_id: int) -> bool:
    """اگر بات دسترسی نداشته باشد یا خطایی رخ دهد، True برمی‌گرداند (fail-open)."""
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.warning("بررسی عضویت کانال %s برای کاربر %s ناموفق بود: %s", channel, user_id, e)
        return True


async def missing_channels(bot, channels, user_id: int) -> list:
    """کانال‌هایی از فهرست که کاربر عضو آن‌ها نیست (چک موازی؛ خطا = fail-open)."""
    channels = parse_channels(channels)
    if not channels:
        return []
    results = await asyncio.gather(*(is_channel_member(bot, c, user_id) for c in channels))
    return [c for c, ok in zip(channels, results) if not ok]


class ForceJoinMiddleware(BaseMiddleware):
    def __init__(self, db):
        super().__init__()
        self.db = db

    async def __call__(self, handler, event: TelegramObject, data: dict):
        settings = self.db.get_force_join_settings()
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        if isinstance(event, Message) and event.successful_payment:
            return await handler(event, data)

        # ادمین‌های بات از محدودیت عضویت/قوانین معاف هستند.
        if self.db.is_admin(user.id):
            return await handler(event, data)

        # دکمه‌ی «بررسی مجدد عضویت» و دکمه‌ی پذیرش قوانین باید خودشان اجرا شوند.
        if isinstance(event, CallbackQuery) and event.data in (CHECK_CALLBACK, TERMS_ACCEPT_CALLBACK):
            return await handler(event, data)

        # کاربری که هنوز زبان را انتخاب نکرده، اول باید زبان را انتخاب کند (قبل از‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
        # پیام عضویت/قوانین)؛ cmd_start و cb_language خودشان بعدش عضویت را چک می‌کنند.
        if (
            (isinstance(event, Message) and (event.text or "").startswith("/start"))
            or (isinstance(event, CallbackQuery) and (event.data or "").startswith("language:"))
        ) and not await asyncio.to_thread(self.db.is_user_language_selected, user.id):
            return await handler(event, data)

        exempt = await asyncio.to_thread(self.db.is_force_join_exempt, user.id)
        missing = []
        if settings["enabled"] and settings["channels"] and not exempt:
            bot = data.get("bot")
            missing = await missing_channels(bot, settings["channels"], user.id)

        if missing:
            text = join_text(len(missing))
            markup = _join_keyboard(missing)
            if isinstance(event, CallbackQuery):
                await event.answer(tr("هنوز عضو کانال نشده‌اید."), show_alert=True)
                try:
                    await event.message.answer(text, reply_markup=markup)
                except Exception:
                    pass
            elif isinstance(event, Message):
                await event.answer(text, reply_markup=markup)
            return

        # /start بعد از عبور از مرحله‌ی عضویت باید اجرا شود تا دیپ‌لینک‌ها و‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
        # رفرال‌ها ثبت شوند؛ خود cmd_start قوانین را بلافاصله بعد از آن نشان می‌دهد.
        if isinstance(event, Message) and (event.text or "").startswith("/start"):
            return await handler(event, data)

        terms = self.db.get_terms_settings()
        if terms["enabled"] and not await asyncio.to_thread(self.db.is_terms_accepted, user.id):
            await self._show_terms(event, terms["text"])
            return

        return await handler(event, data)

    async def _show_terms(self, event: TelegramObject, text: str):
        markup = terms_keyboard()
        if isinstance(event, CallbackQuery):
            await event.answer(tr("ابتدا قوانین و مقررات را تأیید کنید."), show_alert=True)
            try:
                await event.message.answer(text, reply_markup=markup)
            except Exception:
                pass
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=markup)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
