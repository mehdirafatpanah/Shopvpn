# -*- coding: utf-8 -*-
"""
Middleware ضداسپم: محدودیت نرخ رویداد هر کاربر با هشدار و سپس مسدودسازی.

چرا RAM-only (عمدی):
- ThrottleMiddleware قبل از هر IO باید ارزان باشد؛ persist کردن هر پیام در
  SQLite همان قفل WAL را تشدید می‌کند که دلیل وجود cache_autorefresh_loop است.
- جدول admins بسیار کم‌تغییر است ولی هر پیام نرخ را می‌سنجد؛ خواندن/نوشتن
  دائمی روی دیسک برای این hot path منطقی نیست.
- PRUNE تنبل (سقف 5000 کاربر + هرس دوره‌ای) برای حافظه کافی است؛ در صورت
  ری‌استارت، state از بین می‌رود که برای rate-limit قابل قبول است.
- اگر در آینده persist لازم شد، فقط strikes را opt-in در settings نگه دارید،
  نه events.
"""

import asyncio
import html
import logging
import time
from collections import deque

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from blocked_user import BLOCKED_MESSAGE
from i18n import tr

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 35
DEFAULT_WINDOW = 60
MUTE_SECONDS = 60
MUTE_TOLERANCE = 10
STRIKE_RESET_SECONDS = 600
PRUNE_THRESHOLD = 5000
EXEMPT_CALLBACK_PREFIXES = ("qty_inc:", "qty_dec:")

WARN_MESSAGE = (
    "تعداد درخواست‌های شما بیش از حد مجاز است. تا یک دقیقه‌ی آینده درخواست‌های شما "
    "نادیده گرفته می‌شود. در صورت ادامه، حساب شما مسدود خواهد شد."
)


class _UserState:
    __slots__ = ("events", "muted_until", "dropped", "strikes", "last_strike")

    def __init__(self):
        self.events = deque()
        self.muted_until = 0.0
        self.dropped = 0
        self.strikes = 0
        self.last_strike = 0.0


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self._states = {}

    def _read_int(self, key: str, default: int) -> int:
        try:
            return max(1, int(self.db.get_setting(key, str(default)) or default))
        except (TypeError, ValueError):
            return default

    def _enabled(self) -> bool:
        return self.db.get_setting("spam_guard_enabled", "1") == "1"

    @staticmethod
    def _is_exempt(event) -> bool:
        if isinstance(event, Message):
            return event.successful_payment is not None
        if isinstance(event, CallbackQuery):
            return (event.data or "").startswith(EXEMPT_CALLBACK_PREFIXES)
        return True

    def _prune(self, now: float, window: int):
        if len(self._states) < PRUNE_THRESHOLD:
            return
        stale = [
            uid for uid, st in self._states.items()
            if st.muted_until < now
            and now - st.last_strike > STRIKE_RESET_SECONDS
            and (not st.events or now - st.events[-1] > window)
        ]
        for uid in stale:
            del self._states[uid]
        if len(self._states) >= PRUNE_THRESHOLD and not stale:
            oldest = sorted(self._states.items(), key=lambda kv: kv[1].last_strike)[: max(1, PRUNE_THRESHOLD // 10)]
            for uid, _ in oldest:
                self._states.pop(uid, None)

    async def __call__(self, handler, event, data: dict):
        user = data.get("event_from_user")
        if user is None or self._is_exempt(event) or not self._enabled() or self.db.is_admin(user.id):
            return await handler(event, data)

        now = time.monotonic()
        limit = self._read_int("spam_limit", DEFAULT_LIMIT)
        window = self._read_int("spam_window", DEFAULT_WINDOW)

        state = self._states.get(user.id)
        if state is None:
            if len(self._states) >= PRUNE_THRESHOLD:
                self._prune(now, window)
            state = self._states[user.id] = _UserState()

        if now < state.muted_until:
            state.dropped += 1
            if state.dropped > MUTE_TOLERANCE:
                await self._block(event, data, user)
            elif isinstance(event, CallbackQuery):
                await self._safe(event.answer())
            return

        events = state.events
        events.append(now)
        while events and events[0] < now - window:
            events.popleft()
        if len(events) < limit:
            return await handler(event, data)

        events.clear()
        if now - state.last_strike > STRIKE_RESET_SECONDS:
            state.strikes = 0
        state.strikes += 1
        state.last_strike = now
        if state.strikes >= 2:
            await self._block(event, data, user)
            return

        state.muted_until = now + MUTE_SECONDS
        state.dropped = 0
        await self._reply(event, WARN_MESSAGE)

    async def _block(self, event, data: dict, user):
        self._states.pop(user.id, None)
        try:
            await asyncio.to_thread(self.db.set_user_blocked, user.id, True)
        except Exception:
            logger.exception("مسدودسازی کاربر اسپمر %s ناموفق بود.", user.id)
            return
        await self._reply(event, tr(BLOCKED_MESSAGE))
        await self._notify_admins(data.get("bot") or event.bot, user)

    async def _reply(self, event, text: str):
        if isinstance(event, CallbackQuery):
            await self._safe(event.answer(text, show_alert=True))
        elif isinstance(event, Message):
            await self._safe(event.answer(text))

    async def _notify_admins(self, bot, user):
        name = html.escape(user.first_name or "")
        username = f"@{html.escape(user.username)}" if user.username else "-"
        text = (
            "کاربر زیر به دلیل ارسال بیش از حد درخواست (اسپم) به‌صورت خودکار مسدود شد.\n\n"
            f"نام: {name}\n"
            f"آیدی عددی: <code>{user.id}</code>\n"
            f"یوزرنیم: {username}\n\n"
            "برای رفع مسدودیت از پنل وب یا مینی‌اپ (بخش کاربران) اقدام کنید."
        )
        try:
            admin_ids = await asyncio.to_thread(self.db.list_admins)
        except Exception:
            logger.exception("خواندن لیست ادمین‌ها برای گزارش اسپم ناموفق بود.")
            return
        for admin_id in admin_ids:
            await self._safe(bot.send_message(admin_id, text))

    @staticmethod
    async def _safe(coro):
        try:
            await coro
        except Exception:
            logger.warning("ارسال پاسخ ضداسپم ناموفق بود.", exc_info=True)
