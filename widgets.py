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
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram import F
from aiogram.types import CallbackQuery, Message, Update, User

import widget_html
import widget_html_pro
import widgets_pro

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
_SYNTHETIC = "wgt-"
_PATCHED_BOTS: set = set()
_MEMBER_TABS = {"n": "all", "b": "blocked", "w": "all"}
_CHARGE_STEPS = (10000, 50000, 100000)
_TOPUP_PRESETS = (50000, 100000, 200000, 500000)


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


def register_hook(db, name: str, fn) -> None:
    _HOOKS[(id(db), name)] = fn


def register_custom_hook(db, fn) -> None:
    """fn(bot, user, chat_id, state, volume_gb, days) -> (error_text | result_text, runner | None)."""
    register_hook(db, "custom", fn)


def _hook(db, name: str):
    return _HOOKS.get((id(db), name))


class _SyntheticAnswerMiddleware:
    """Swallows answerCallbackQuery for callbacks fed from widget buttons (no real query id exists)."""

    async def __call__(self, make_request, bot, method):
        if isinstance(method, AnswerCallbackQuery) and str(method.callback_query_id).startswith(_SYNTHETIC):
            return True
        return await make_request(bot, method)


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


def queue_payload(db) -> dict:
    rows = [o for o in db.get_pending_orders() if not o["lootbox_type_id"]]
    topups = db.get_pending_topups()
    out = []

    def who(user_id):
        user = db.get_user(user_id)
        label = (user["first_name"] or user["username"]) if user else ""
        return str(label or user_id)[:12]

    for o in rows[:3]:
        if o["is_custom_config"]:
            name = f"{o['custom_volume_gb']} گیگ"
        else:
            product = db.get_product(o["product_id"])
            name = product["name"] if product else "؟"
        price = o["final_price"] if o["final_price"] is not None else o["base_price"]
        out.append(["o", o["id"], who(o["user_id"]), name[:14], int(price or 0)])
    for t in topups[:2]:
        out.append(["t", t["id"], who(t["user_id"]), "شارژ کیف پول", int(t["amount"] or 0)])
    return {"n": len(rows) + len(topups), "q": out}


async def health_payload(db, live: bool = False) -> dict:
    servers = list(await asyncio.to_thread(db.get_panel_servers, True))[:6]

    def stored():
        try:
            with db._get_conn() as conn:
                return {r["server_id"]: r["status"] for r in conn.execute("SELECT server_id, status FROM panel_health")}
        except Exception:
            return {}

    status = await asyncio.to_thread(stored)
    latency = {}
    if live:
        import panel_health

        sem = asyncio.Semaphore(panel_health.PROBE_CONCURRENCY)

        async def probe(server):
            started = asyncio.get_running_loop().time()
            try:
                ok, _err = await asyncio.wait_for(panel_health._probe(server, sem), 10)
            except asyncio.TimeoutError:
                return server["id"], None, 0
            return server["id"], ok, int((asyncio.get_running_loop().time() - started) * 1000)

        for sid, ok, ms in await asyncio.gather(*(probe(s) for s in servers)):
            status[sid] = "up" if ok else ("down" if ok is not None else "slow")
            latency[sid] = ms
    out = []
    for server in servers:
        info = await asyncio.to_thread(db.get_panel_capacity_info, server["id"])
        active = int(info["active_services"]) if info else 0
        cap = int(info["max_services"] or 0) if info else 0
        state = status.get(server["id"], "up")
        light = 0 if state == "down" else (2 if state == "slow" or (cap and active * 10 >= cap * 9) else 1)
        out.append([(server["name"] or "")[:14], light, active, cap, latency.get(server["id"], 0)])
    return {"p": out, "l": 1 if live else 0}


def members_payload(db, tab: str, offset: int) -> dict:
    tab = tab if tab in _MEMBER_TABS else "n"
    rows, total = db.search_users(
        "", _MEMBER_TABS[tab], limit=5, offset=offset, sort="balance" if tab == "w" else "newest",
    )
    users = [
        [r["telegram_id"], str(r["first_name"] or r["username"] or r["telegram_id"])[:12],
         int(r["referral_credit"] or 0), 1 if r["is_blocked"] else 0]
        for r in rows
    ]
    return {"t": tab, "o": offset, "n": int(total), "u": users}


def _toggle_block(db, admin_id: int, target: int) -> Optional[str]:
    user = db.get_user(target)
    if not user:
        return "کاربر یافت نشد."
    if db.is_admin(target):
        return "⛔️ ادمین‌ها را نمی‌توان مسدود کرد."
    blocked = not bool(user["is_blocked"])
    db.set_user_blocked(target, blocked)
    db.log_admin_action(admin_id, "widget_user_block", f"کاربر {target} | {'مسدود' if blocked else 'آزاد'}")
    return None


def _charge_user(db, admin_id: int, target: int, amount: int) -> Optional[str]:
    if db.admin_adjust_wallet(target, amount, "widget") is None:
        return "کاربر یافت نشد."
    db.log_admin_action(admin_id, "widget_wallet_adjust", f"کاربر {target} | {amount:,} تومان")
    return None


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
        if kind in ("v", "w"):
            return await self._user(dp, bot, query, uid, kind, rest)
        if not await asyncio.to_thread(db.is_admin, uid):
            return "⛔️ دسترسی ندارید.", None
        if kind == "s":
            payload = await asyncio.to_thread(stats_payload, db, rest)
            return _dumps(payload), self._persist(bot, query, payload)
        if kind == "f":
            return await self._features(bot, query, uid, rest)
        if kind == "q":
            return await self._queue(dp, bot, query, uid, rest)
        if kind == "h":
            return await self._health(bot, query, rest)
        if kind == "m":
            return await self._members(bot, query, uid, rest)
        if kind in ("p", "t", "a", "k"):
            return await self._pro(dp, bot, query, uid, kind, rest)
        return None, None

    async def _pro(self, dp, bot, query, uid, kind, rest):
        db = self.db
        if kind == "p":
            payload = await asyncio.to_thread(widgets_pro.pulse_payload, db, 1 if rest == "1" else 0)
        elif kind == "t":
            tab, _, period = rest.partition(":")
            payload = await asyncio.to_thread(widgets_pro.top_payload, db, tab or "p", period or "30")
        elif kind == "a":
            if rest.startswith("go:"):
                _go, _, idx = rest.partition(":")
                target = widgets_pro.ALERT_TARGETS.get(int(idx)) if idx.isdigit() else None
                if target:
                    await self._press(dp, bot, query, uid, target)
            payload = await asyncio.to_thread(widgets_pro.alerts_payload, db)
        else:
            payload = await asyncio.to_thread(widgets_pro.analysis_payload, db, "h" if rest == "r" else rest)
        return _dumps(payload), (None if rest in ("r", "") or rest.startswith("go:") else self._persist(bot, query, payload))

    async def _user(self, dp, bot, query, uid, kind, rest):
        hook = _hook(self.db, "user")
        if hook is None:
            return "این بخش فعال نیست.", None
        state = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
        user = User.model_validate(query["from"])
        error, payload = await hook(bot, user, state, kind, rest)
        if payload is None:
            return error, None
        return _dumps(payload), self._persist(bot, query, payload)

    async def _press(self, dp, bot, query, uid, data: str) -> None:
        if id(bot) not in _PATCHED_BOTS:
            bot.session.middleware(_SyntheticAnswerMiddleware())
            _PATCHED_BOTS.add(id(bot))
        sent = await bot.send_message(uid, "⏳")
        call = CallbackQuery(
            id=f"{_SYNTHETIC}{uid}-{sent.message_id}",
            from_user=User.model_validate(query["from"]),
            chat_instance="widget",
            message=sent,
            data=data,
        ).as_(bot)
        await dp.feed_update(bot, Update(update_id=0, callback_query=call))

    async def _queue(self, dp, bot, query, uid, rest):
        db = self.db
        act, _, ident = rest.partition(":")
        if act in ("a", "x", "ta", "tx"):
            if not ident.isdigit():
                return "❌ مقدار نامعتبر.", None
            data = {"a": "order_approve", "x": "order_reject", "ta": "topup_approve", "tx": "topup_reject"}[act]
            await self._press(dp, bot, query, uid, f"{data}:{int(ident)}")
        payload = await asyncio.to_thread(queue_payload, db)
        return _dumps(payload), (None if act == "r" else self._persist(bot, query, payload))

    async def _health(self, bot, query, rest):
        payload = await health_payload(self.db, live=(rest == "p"))
        return _dumps(payload), self._persist(bot, query, payload)

    async def _members(self, bot, query, uid, rest):
        db = self.db
        parts = rest.split(":")
        act = parts[0]
        try:
            if act in ("b", "c"):
                tab, offset, target = parts[1], int(parts[2]), int(parts[3])
                if not await asyncio.to_thread(db.is_senior_admin, uid):
                    return "⛔️ فقط مالک و مدیر کامل.", None
                if act == "b":
                    error = await asyncio.to_thread(_toggle_block, db, uid, target)
                else:
                    step = int(parts[4])
                    error = await asyncio.to_thread(_charge_user, db, uid, target, step) if step in _CHARGE_STEPS else "❌ مقدار نامعتبر."
                if error:
                    return error, None
            else:
                tab, offset = parts[1], int(parts[2])
        except (ValueError, IndexError):
            return "❌ مقدار نامعتبر.", None
        payload = await asyncio.to_thread(members_payload, db, tab, max(offset, 0))
        return _dumps(payload), (None if act == "r" else self._persist(bot, query, payload))

    async def _custom(self, dp, bot, query, uid, rest):
        hook = _hook(self.db, "custom")
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

    async def _admin_widget(message: Message, html: str, caption: str, payload) -> None:
        await _send(message, html, caption, _dumps(payload))

    @router.message(Command("wqueue"))
    async def cmd_wqueue(message: Message):
        if await asyncio.to_thread(db.is_admin, message.from_user.id):
            await _admin_widget(message, widget_html.queue_html(), "🧾 صف تایید", await asyncio.to_thread(queue_payload, db))

    @router.message(Command("whealth"))
    async def cmd_whealth(message: Message):
        if await asyncio.to_thread(db.is_admin, message.from_user.id):
            await _admin_widget(message, widget_html.health_html(), "🩺 سلامت پنل‌ها", await health_payload(db))

    @router.message(Command("wusers"))
    async def cmd_wusers(message: Message):
        if await asyncio.to_thread(db.is_admin, message.from_user.id):
            await _admin_widget(message, widget_html.members_html(), "👥 مدیریت سریع کاربران", await asyncio.to_thread(members_payload, db, "n", 0))

    @router.message(Command("wservices"))
    async def cmd_wservices(message: Message, state: FSMContext):
        await _user_widget(message, state, "v", widget_html.services_html(), "📶 سرویس‌های من")

    @router.message(Command("wwallet"))
    async def cmd_wwallet(message: Message, state: FSMContext):
        await _user_widget(message, state, "w", widget_html.wallet_html(), "💰 کیف پول و دعوت")

    async def _user_widget(message: Message, state: FSMContext, kind: str, html: str, caption: str, user=None) -> None:
        hook = _hook(db, "user")
        if hook is None or not ENABLED:
            return
        _error, payload = await hook(message.bot, user or message.from_user, state, kind, "r")
        if payload is None:
            await message.answer(_error or "⚠️ در دسترس نیست.")
            return
        await _send(message, html, caption, _dumps(payload))

    @router.callback_query(F.data.in_({"u_wsvc", "u_wwal"}))
    async def cb_user_widget(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if (await asyncio.to_thread(db.get_setting, "widgets_enabled", "1")) == "0":
            return
        if call.data == "u_wsvc":
            await _user_widget(call.message, state, "v", widget_html.services_html(), "📶 سرویس‌های من", call.from_user)
        else:
            await _user_widget(call.message, state, "w", widget_html.wallet_html(), "💰 کیف پول و دعوت", call.from_user)

    async def _show_menu(call: CallbackQuery, text: str, markup) -> None:
        try:
            await call.message.edit_text(text, reply_markup=markup)
        except Exception:
            await call.message.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_widgets")
    async def cb_admin_widgets_menu(call: CallbackQuery):
        if not await asyncio.to_thread(db.is_admin, call.from_user.id):
            return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)
        await call.answer()
        import keyboards as kb
        await _show_menu(call, "🧩 ویجت‌های مدیریت:", kb.admin_widgets_menu_kb())

    @router.callback_query(F.data == "u_widgets")
    async def cb_user_widgets_menu(call: CallbackQuery):
        await call.answer()
        if not ENABLED or (await asyncio.to_thread(db.get_setting, "widgets_enabled", "1")) == "0":
            return
        import keyboards as kb
        await _show_menu(call, "🧩 ویجت‌ها:", kb.user_widgets_menu_kb())

    def _register_pro(cmd: str, cb: str, html_fn, caption: str, payload_fn) -> None:
        async def send(message: Message) -> None:
            payload = await asyncio.to_thread(payload_fn, db)
            await _admin_widget(message, html_fn(), caption, payload)

        @router.message(Command(cmd))
        async def _cmd(message: Message):
            if await asyncio.to_thread(db.is_admin, message.from_user.id):
                await send(message)

        @router.callback_query(F.data == cb)
        async def _cb(call: CallbackQuery):
            if not await asyncio.to_thread(db.is_admin, call.from_user.id):
                return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)
            await call.answer()
            await send(call.message)

    _register_pro("wpulse", "adm_wpulse", widget_html_pro.pulse_html, "🔴 نبض زنده فروشگاه",
                  lambda d: widgets_pro.pulse_payload(d, 0))
    _register_pro("walerts", "adm_walerts", widget_html_pro.alerts_html, "🚨 مرکز هشدار", widgets_pro.alerts_payload)
    _register_pro("wtop", "adm_wtop", widget_html_pro.top_html, "🏆 برترین‌ها",
                  lambda d: widgets_pro.top_payload(d, "p", "30"))
    _register_pro("wanalysis", "adm_wanalysis", widget_html_pro.analysis_html, "📊 تحلیل فروش",
                  lambda d: widgets_pro.analysis_payload(d, "h"))

    @router.callback_query(F.data == "adm_wqueue")
    async def cb_wqueue(call: CallbackQuery):
        if not await asyncio.to_thread(db.is_admin, call.from_user.id):
            return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)
        await call.answer()
        await _admin_widget(call.message, widget_html.queue_html(), "🧾 صف تایید", await asyncio.to_thread(queue_payload, db))

    @router.callback_query(F.data == "adm_whealth")
    async def cb_whealth(call: CallbackQuery):
        if not await asyncio.to_thread(db.is_admin, call.from_user.id):
            return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)
        await call.answer()
        await _admin_widget(call.message, widget_html.health_html(), "🩺 سلامت پنل‌ها", await health_payload(db))

    @router.callback_query(F.data == "adm_wusers")
    async def cb_wusers(call: CallbackQuery):
        if not await asyncio.to_thread(db.is_admin, call.from_user.id):
            return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)
        await call.answer()
        await _admin_widget(call.message, widget_html.members_html(), "👥 مدیریت سریع کاربران", await asyncio.to_thread(members_payload, db, "n", 0))

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
