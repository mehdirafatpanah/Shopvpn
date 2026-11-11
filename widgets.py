"""Telegram widgets: custom-plan sliders, admin stats chart and feature toggles inside bot messages."""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import TelegramMethod
from aiogram import F
from aiogram.types import CallbackQuery, Message, User

import widget_html

logger = logging.getLogger(__name__)

EXTRA_UPDATES = ["widget_query", "shared_widget_query"]
ENABLED = os.environ.get("SHOPVPN_WIDGETS", "1") != "0"

FEATURES = [
    ("global_bot_enabled", "وضعیت ربات", "1"),
    ("terms_enabled", "قوانین", "0"),
    ("phone_auth_enabled", "احراز هویت با شماره", "1"),
    ("smart_subscription_enabled", "اشتراک هوشمند", "1"),
]
STATS_KEYS = ("1", "7", "30", "0")

_HOOKS: dict = {}
_TASKS: set = set()


class SendWidget(TelegramMethod[Message]):
    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int
    html: str
    caption: Optional[str] = None
    allow_queries: Optional[bool] = None
    public_data: Optional[str] = None
    chat_data: Optional[str] = None


class EditMessageWidgetData(TelegramMethod[Any]):
    __returning__ = Any
    __api_method__ = "editMessageWidgetData"

    chat_id: int
    message_id: int
    chat_data: Optional[str] = None
    public_data: Optional[str] = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: Optional[str] = None


def _dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def register_custom_hook(db, fn) -> None:
    """fn(bot, user, chat_id, state, volume_gb, days) -> (error_text | result_text, runner | None)."""
    _HOOKS[id(db)] = fn


def allowed_updates(dp: Dispatcher) -> list:
    updates = list(dp.resolve_used_update_types())
    if ENABLED:
        updates += [u for u in EXTRA_UPDATES if u not in updates]
    return updates


def plan_params(db, product_id) -> Optional[dict]:
    """Slider limits and price tiers of the custom-config flow, or None when not priceable."""
    if product_id:
        product = db.get_custom_config_product(product_id)
        if not product:
            return None
        lo, hi = int(product["min_gb"]), int(product["max_gb"])
        if product["duration_mode"] == "user_choice":
            dmin, dmax = int(product["min_days"] or 1), int(product["max_days"] or 90)
        else:
            dmin = dmax = int(product["duration_days"])
        if product["pricing_mode"] == "flat":
            tiers = [[lo, 0, int(product["flat_price_per_gb"] or 0)]]
        else:
            tiers = [
                [int(t["from_gb"]), int(t["to_gb"] or 0), int(t["price_per_gb"])]
                for t in db.get_custom_config_product_tiers(product_id)
            ]
    else:
        settings = db.get_custom_config_settings()
        lo, hi = settings["min_gb"], settings["max_gb"]
        dmin = dmax = settings["duration_days"]
        tiers = [
            [int(t["from_gb"]), int(t["to_gb"] or 0), int(t["price_per_gb"])]
            for t in db.get_pricing_tiers()
        ]
    if not tiers or lo >= hi or tiers[0][2] <= 0:
        return None
    params = {"a": lo, "b": hi, "c": dmin, "d": dmax, "t": tiers, "u": "تومان"}
    return params if len(_dumps(params).encode()) <= 1000 else None


async def send_custom_plan(bot, db, chat_id: int, product_id) -> bool:
    """Send the slider widget under the volume prompt; False when unavailable (text flow stays as fallback)."""
    if not ENABLED:
        return False
    try:
        if (await asyncio.to_thread(db.get_setting, "widgets_enabled", "1")) == "0":
            return False
        params = await asyncio.to_thread(plan_params, db, product_id)
        if params is None:
            return False
        await bot(SendWidget(
            chat_id=chat_id,
            html=widget_html.custom_plan_html(),
            caption="🛠 حجم و مدت را با اسلایدر انتخاب کنید (یا حجم را تایپ کنید)",
            allow_queries=True,
            public_data=_dumps(params),
        ))
        return True
    except Exception:
        logger.warning("ارسال ویجت سرویس سفارشی ناموفق بود", exc_info=True)
        return False


def stats_payload(db, key: str) -> dict:
    key = key if key in STATS_KEYS else "30"
    today = datetime.now(timezone.utc).date()
    base = db.get_sales_stats()
    series = [int(x["revenue"] or 0) for x in base["daily_series"]][-14:]
    if key == "0":
        total = db.get_stats()
        rev, orders, users = int(total["revenue"] or 0), int(total["approved"] or 0), int(total["users"] or 0)
        aov = rev // orders if orders else 0
    else:
        days = int(key)
        start = (today - timedelta(days=days - 1)).isoformat()
        cur = db.get_sales_stats(start, today.isoformat())
        rev, orders, users, aov = (
            int(cur["revenue"] or 0), int(cur["approved"] or 0),
            int(cur["new_users"] or 0), int(cur["aov"] or 0),
        )
    return {"k": key, "r": rev, "o": orders, "u": users, "a": aov, "s": series}


def features_state(db) -> list:
    out = []
    for key, _label, default in FEATURES:
        value = str(db.get_setting(key, default)).strip()
        out.append(1 if (value == "1" if default == "0" else value != "0") else 0)
    return out


def _toggle(db, index: int) -> Optional[str]:
    key, _label, default = FEATURES[index]
    state = features_state(db)
    new_on = not state[index]
    if key == "terms_enabled" and new_on and not (db.get_setting("terms_text", "") or "").strip():
        return "⚠️ ابتدا متن قوانین را در تنظیمات وارد کنید."
    db.set_setting(key, "1" if new_on else "0")
    return None


class WidgetHub:
    """Handles widget_query updates for one bot."""

    def __init__(self, db):
        self.db = db

    async def handle(self, dp, bot, query: dict) -> None:
        after = None
        try:
            result, after = await self._route(dp, bot, query)
        except Exception:
            logger.exception("خطا در پردازش widget_query")
            result = "⚠️ خطا؛ دوباره تلاش کنید."
        if result is not None and len(result.encode()) > 1000:
            result = "⚠️ خطا؛ دوباره تلاش کنید."
        try:
            await bot(AnswerWidgetQuery(widget_query_id=str(query["id"]), data=result or None))
        except Exception:
            logger.warning("پاسخ به widget_query ناموفق بود", exc_info=True)
        if after is not None:
            try:
                await after()
            except Exception:
                logger.exception("خطا در ادامه‌ی پردازش widget_query")

    async def _route(self, dp, bot, query: dict):
        db = self.db
        uid = int(query["from"]["id"])
        kind, _, rest = (query.get("data") or "").partition(":")
        if kind == "c":
            return await self._custom(dp, bot, query, uid, rest)
        if not await asyncio.to_thread(db.is_admin, uid):
            return "⛔️ دسترسی ندارید.", None
        if kind == "s":
            payload = await asyncio.to_thread(stats_payload, db, rest)
            return _dumps(payload), self._persist(bot, query, payload)
        if kind == "f":
            return await self._features(bot, query, uid, rest)
        return None, None

    async def _custom(self, dp, bot, query, uid, rest):
        hook = _HOOKS.get(id(self.db))
        if hook is None:
            return "این بخش فعال نیست.", None
        try:
            gb, days = (int(x) for x in rest.split(":"))
        except ValueError:
            return "❌ مقدار نامعتبر.", None
        state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
        user = User.model_validate(query["from"])
        return await hook(bot, user, uid, state, gb, days)

    async def _features(self, bot, query, uid, rest):
        db = self.db
        if rest != "r":
            if not await asyncio.to_thread(db.is_senior_admin, uid):
                return "⛔️ فقط مالک و مدیر کامل.", None
            try:
                index = int(rest)
                error = await asyncio.to_thread(_toggle, db, index)
            except (ValueError, IndexError):
                return "❌ مقدار نامعتبر.", None
            if error:
                return error, None
        state = await asyncio.to_thread(features_state, db)
        return _dumps(state), (None if rest == "r" else self._persist(bot, query, state))

    def _persist(self, bot, query, payload):
        chat = query.get("chat") or {}
        message_id = query.get("message_id")
        if not chat.get("id") or not message_id:
            return None

        async def run():
            try:
                await bot(EditMessageWidgetData(
                    chat_id=chat["id"], message_id=message_id, chat_data=_dumps(payload),
                ))
            except Exception:
                logger.debug("ذخیره‌ی state ویجت ناموفق بود", exc_info=True)

        return run


class WidgetDispatcher(Dispatcher):
    """Dispatcher that routes widget_query updates (unknown to the base event system) to WidgetHub."""

    async def feed_update(self, bot, update, **kwargs):
        hub = getattr(self, "widget_hub", None)
        extra = getattr(update, "model_extra", None) or {}
        query = extra.get("widget_query")
        if hub is not None and isinstance(query, dict):
            task = asyncio.create_task(hub.handle(self, bot, query))
            _TASKS.add(task)
            task.add_done_callback(_TASKS.discard)
            return True
        return await super().feed_update(bot, update, **kwargs)


def create_router(db) -> Router:
    router = Router()

    async def _send(message: Message, html: str, caption: str, chat_data=None) -> None:
        try:
            await message.bot(SendWidget(
                chat_id=message.chat.id, html=html, caption=caption,
                allow_queries=True, chat_data=chat_data,
            ))
        except Exception:
            logger.warning("sendWidget ناموفق بود", exc_info=True)
            await message.answer("⚠️ ویجت در این سرور تلگرام پشتیبانی نمی‌شود.")

    async def _stats(message: Message):
        payload = await asyncio.to_thread(stats_payload, db, "30")
        caption = f"📊 آمار ربات (۳۰ روز): {payload['r']:,} تومان فروش، {payload['o']:,} سفارش، {payload['u']:,} کاربر جدید"
        await _send(message, widget_html.stats_html(), caption, _dumps(payload))

    async def _features(message: Message):
        state = await asyncio.to_thread(features_state, db)
        html = widget_html.features_html([label for _k, label, _d in FEATURES])
        await _send(message, html, "⚙️ مدیریت قابلیت‌ها", _dumps(state))

    @router.message(Command("wstats"))
    async def cmd_wstats(message: Message):
        if await asyncio.to_thread(db.is_admin, message.from_user.id):
            await _stats(message)

    @router.message(Command("wfeatures"))
    async def cmd_wfeatures(message: Message):
        if await asyncio.to_thread(db.is_admin, message.from_user.id):
            await _features(message)

    @router.callback_query(F.data == "adm_wstats")
    async def cb_wstats(call: CallbackQuery):
        if not await asyncio.to_thread(db.is_admin, call.from_user.id):
            return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)
        await call.answer()
        await _stats(call.message)

    @router.callback_query(F.data == "adm_wfeat")
    async def cb_wfeat(call: CallbackQuery):
        if not await asyncio.to_thread(db.is_admin, call.from_user.id):
            return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)
        await call.answer()
        await _features(call.message)

    return router
