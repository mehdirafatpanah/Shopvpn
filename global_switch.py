from i18n import tr
# -*- coding: utf-8 -*-
"""
سوئیچ سراسری خاموش/روشن ربات.

وقتی تنظیم ``global_bot_enabled`` روی "0" باشد، تمام پیام‌ها و دکمه‌های کاربران
عادی قبل از رسیدن به هندلرها متوقف می‌شوند و فقط پیام «ربات موقتاً غیرفعال است»
نمایش داده می‌شود. ادمین‌ها از این محدودیت معاف هستند تا بتوانند ربات را دوباره
روشن کنند.

خاموش/روشن کردن (مالک و مدیر کامل؛ از «پنل مدیریت ← گزارش و سیستم ← سوئیچ سراسری» هم می‌شود):
    /bot_off      خاموش کردن ربات برای همه‌ی کاربران عادی
    /bot_on       روشن کردن ربات
    /bot_status   نمایش وضعیت فعلی

متن پیام خاموشی با تنظیم ``global_bot_off_text`` قابل تغییر است.
هر ربات (اصلی یا نمایندگی) دیتابیس و تنظیم مستقل خودش را دارد، پس سوئیچ هر ربات
جداگانه عمل می‌کند.
"""

import asyncio
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

logger = logging.getLogger(__name__)

SETTING_KEY = "global_bot_enabled"
TEXT_KEY = "global_bot_off_text"
DEFAULT_OFF_TEXT = "🔧 ربات موقتاً غیرفعال است. لطفاً بعداً دوباره تلاش کنید."

# حداقل فاصله (ثانیه) بین دو پیام «ربات خاموش است» به یک کاربر، برای جلوگیری از اسپم
NOTICE_INTERVAL = 30


def _command_of(message: Message) -> str:
    """نام دستور (بدون / و بدون @botname) یا رشته‌ی خالی."""
    text = (message.text or "").strip()
    if not text.startswith("/"):
        return ""
    return text.split()[0][1:].split("@")[0].lower()


class GlobalBotSwitchMiddleware(BaseMiddleware):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self._last_notice = {}  # user_id -> time.monotonic()

    def _is_enabled(self) -> bool:
        # get_setting از کش حافظه می‌خواند و روی event loop بلوکه نمی‌کند
        try:
            return str(self.db.get_setting(SETTING_KEY, "1")).strip() != "0"
        except Exception:
            logger.exception("خواندن %s ناموفق بود؛ ربات روشن فرض شد.", SETTING_KEY)
            return True

    async def _handle_admin_command(self, event: Message, user_id: int) -> bool:
        """اگر پیام یکی از دستورهای سوئیچ بود پردازش می‌کند و True برمی‌گرداند."""
        cmd = _command_of(event)
        if cmd not in ("bot_off", "bot_on", "bot_status"):
            return False

        if cmd == "bot_status":
            state = "🟢 روشن" if self._is_enabled() else "🔴 خاموش"
            await event.answer(tr(f"وضعیت ربات: {state}"))
            return True

        try:
            allowed = await asyncio.to_thread(self.db.is_senior_admin, user_id)
        except Exception:
            allowed = False
        if not allowed:
            await event.answer(tr("⛔️ فقط مالک و مدیر کامل می‌توانند ربات را خاموش/روشن کنند."))
            return True

        new_value = "0" if cmd == "bot_off" else "1"
        await asyncio.to_thread(self.db.set_setting, SETTING_KEY, new_value)
        if new_value == "0":
            await event.answer(
                tr("🔴 ربات برای کاربران عادی خاموش شد.\n"
                "ادمین‌ها همچنان دسترسی دارند. برای روشن کردن: /bot_on")
            )
        else:
            await event.answer(tr("🟢 ربات دوباره روشن شد."))
        return True

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")

        # ادمین‌ها همیشه عبور می‌کنند (و می‌توانند سوئیچ را کنترل کنند)
        if user is not None and self.db.is_admin(user.id):
            if isinstance(event, Message) and await self._handle_admin_command(event, user.id):
                return
            return await handler(event, data)

        if self._is_enabled():
            return await handler(event, data)

        # --- ربات خاموش است و کاربر عادی است ---
        off_text = (self.db.get_setting(TEXT_KEY, "") or "").strip() or tr(DEFAULT_OFF_TEXT)

        if isinstance(event, CallbackQuery):
            try:
                await event.answer(off_text, show_alert=True)
            except Exception:
                pass
        elif isinstance(event, Message):
            # در گروه‌ها/کانال‌ها بی‌صدا نادیده گرفته می‌شود تا پیام اسپم نشود
            if event.chat.type == "private" and user is not None:
                now = time.monotonic()
                if now - self._last_notice.get(user.id, 0.0) >= NOTICE_INTERVAL:
                    self._last_notice[user.id] = now
                    if len(self._last_notice) > 5000:
                        cutoff = now - NOTICE_INTERVAL
                        self._last_notice = {
                            k: v for k, v in self._last_notice.items() if v > cutoff
                        }
                    try:
                        await event.answer(off_text)
                    except Exception:
                        pass
        return  # هندلر اصلی اجرا نمی‌شود
