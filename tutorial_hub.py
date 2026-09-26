# -*- coding: utf-8 -*-
"""اتصال آموزش‌ها به بخش‌ها و دکمه‌های بات.

هر «مقصد» (target) یک دکمه/بخش از بات است که کاربر با آن کار می‌کند. وقتی
کاربر آن دکمه را می‌زند و برای مقصدش آموزشی متصل شده باشد، زیر همان صفحه‌ی
جواب دکمه «📚 آموزش» اضافه می‌شود. تزریق دکمه به‌صورت مرکزی و بدون دست‌زدن به
تک‌تک هندلرها انجام می‌شود:
  - TutorialTargetMiddleware مقصدِ آپدیت جاری را تشخیص می‌دهد.
  - TutorialRequestMiddleware دکمه را به اولین پیام خروجی همان چت اضافه می‌کند.
برای مقصد جدید فقط یک ورودی به GROUPS اضافه کن.
"""

import contextvars
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import extra_gateway_registry
from i18n import tr

log = logging.getLogger("tutorial_hub")

GENERAL = "general"
POST_PURCHASE = "post_purchase"

BUTTON_PREFIX = "tutb:"
BUTTON_TEXT_SETTING = "btn_tutorial_here"
DEFAULT_BUTTON_TEXT = "📚 آموزش"
COMPANION_TEXT = "📚 برای راهنمایی این بخش، دکمه‌ی زیر را بزنید:"
CONTEXT_TTL = 30.0

SPECIAL_TARGETS = (
    (GENERAL, "📚 منوی «آموزش» (آموزش‌های کلی)"),
    (POST_PURCHASE, "🎁 پیشنهاد بعد از خرید موفق"),
)


def _t(key, label, menu=None, exact=(), prefix=(), cmd=()):
    return {
        "key": key, "label": label, "menu": menu,
        "exact": tuple(exact), "prefix": tuple(prefix), "cmd": tuple(cmd),
    }


def _extra_gateway_targets():
    items = []
    for gw_key in extra_gateway_registry.GATEWAY_ORDER:
        gw = extra_gateway_registry.GATEWAYS[gw_key]
        items.append(_t(f"pay_{gw_key}", f"{gw['icon']} {gw['title']}", exact=(f"pay_{gw_key}",)))
    return items


GROUPS = [
    ("main", "🏠 دکمه‌های منوی اصلی", [
        _t("buy", "🛒 خرید کانفیگ (لیست دسته‌بندی)", menu="btn_buy", exact=("back_categories",), cmd=("/buy",)),
        _t("test", "🧪 کانفیگ تست رایگان", menu="btn_test", prefix=("user_test_plan:",)),
        _t("wheel", "🎡 گردونه شانس", menu="btn_wheel"),
        _t("tiers", "🤝 نمایندگی (درخواست نمایندگی)", menu="btn_reseller_tiers", prefix=("rt:",)),
        _t("reseller_panel", "🧑‍💼 پنل نمایندگی", menu="btn_reseller_panel"),
    ]),
    ("buy", "🛍 مسیر خرید", [
        _t("category", "انتخاب دسته‌بندی (لیست محصولات)", prefix=("cat:",)),
        _t("product", "انتخاب محصول (صفحه تأیید خرید)", prefix=("prod:",)),
        _t("buy_users", "انتخاب تعداد کاربر", prefix=("buy_users:", "buy_users_pick:")),
        _t("discount", "🎟 وارد کردن کد تخفیف", prefix=("enter_code:", "renew_enter_code:")),
        _t("buy_start", "ادامه خرید (انتخاب روش پرداخت)", prefix=("buy_start:",)),
        _t("custom_config", "🛠 ساخت کانفیگ شخصی", exact=("custom_config_start",)),
        _t("custom_product", "انتخاب محصول کانفیگ شخصی", prefix=("ccf_pick_product:",)),
        _t("check_payment", "بررسی پرداخت (بعد از پرداخت)",
           prefix=("check_c2c:", "check_aban:", "check_blupal:", "check_noapay:")),
    ]),
    ("pay", "💳 روش‌های پرداخت", [
        _t("pay_card", "💳 کارت‌به‌کارت (ارسال رسید)", exact=("pay_card2card",)),
        _t("pay_card_auto", "💳 کارت‌به‌کارت خودکار", exact=("pay_card_auto",)),
        _t("pay_crypto", "🪙 ارز دیجیتال", exact=("pay_crypto",)),
        _t("pay_abangateway", "آبان‌گیت‌وی", exact=("pay_abangateway",)),
        _t("pay_blupal", "بلوپال", exact=("pay_blupal",)),
        _t("pay_noapay", "⭐ استارز تلگرام (NoapayBot)", exact=("pay_noapay",)),
        _t("pay_customgw", "💠 درگاه‌های سفارشی", prefix=("pay_customgw:",)),
    ] + _extra_gateway_targets()),
    ("account", "🧾 حساب کاربری و کیف پول", [
        _t("acct_hub", "🧾 صفحه‌ی حساب کاربری من", menu="btn_my_orders", exact=("acct:hub",)),
        _t("acct_orders", "📦 سرویس‌ها و سفارش‌های من", exact=("acct:orders", "mo_back")),
        _t("referral", "🤝 زیرمجموعه‌گیری", menu="btn_referral", exact=("acct:referral",)),
        _t("wallet", "👛 کیف پول من", menu="btn_wallet", exact=("acct:wallet",)),
        _t("wallet_topup", "➕ شارژ کیف پول", exact=("start_topup",), cmd=("/charge",)),
        _t("wallet_gift", "🎁 استفاده از گیفت‌کد", exact=("wallet_gift_code",)),
        _t("wallet_transfer", "💸 انتقال موجودی", exact=("wallet_transfer",)),
        _t("wallet_history", "📜 تاریخچه تراکنش‌ها", exact=("wallet_history",)),
        _t("coins", "🪙 سکه‌های من", exact=("coins_menu",), prefix=("coins_mode:",)),
    ]),
    ("service", "📦 صفحه و دکمه‌های هر سرویس", [
        _t("svc_detail", "صفحه‌ی جزئیات سرویس", prefix=("mo_v:",)),
        _t("svc_refresh", "♻️ بروزرسانی کانفیگ", prefix=("mo_refresh:",)),
        _t("svc_qr", "⬜ کیوآر کانفیگ", prefix=("svc_qr:",)),
        _t("svc_links", "📋 کانفیگ‌های تکی", prefix=("mo_links:",)),
        _t("svc_renew", "🛠 تمدید سرویس (انتخاب نوع/پلن)", prefix=("svc_renew:", "svc_users:", "svc_users_pick:")),
        _t("svc_renew_pay", "تأیید و پرداخت تمدید", prefix=("svc_renew_pick:", "renew_confirm_pay:")),
        _t("svc_cut", "🚫 قطع دسترسی و لینک جدید", prefix=("svc_cut:", "svc_cutok:")),
        _t("svc_toggle", "🟢 فعال/غیرفعال کردن کانفیگ", prefix=("svc_toggle:",)),
        _t("svc_rename", "✏️ تغییر نام کانفیگ", prefix=("svc_rename:",)),
        _t("svc_autorenew", "🔄 تمدید خودکار", prefix=("svc_autorenew:",)),
        _t("svc_transfer", "👤 انتقال کانفیگ", prefix=("svc_transfer:", "svc_transok:")),
        _t("svc_location", "📍 تغییر لوکیشن", prefix=("svc_location:", "svc_location_pick:", "svc_location_ok:")),
        _t("svc_history", "📜 تاریخچه سرویس", prefix=("svc_hist:",)),
        _t("svc_inquiry", "🔍 استعلام", prefix=("svc_inquiry:",)),
        _t("svc_rate", "⭐ امتیازدهی به سرویس", prefix=("svc_rate:", "svc_rate_set:")),
        _t("svc_delete", "🗑 حذف کامل سرویس", prefix=("mo_del:", "mo_delok:")),
    ]),
    ("reseller", "🧑‍💼 نمایندگی", [
        _t("resreq", "مراحل ثبت درخواست نمایندگی", prefix=("resreq_", "respay:")),
        _t("reseller_stats", "📊 آمار نماینده", exact=("reseller_stats",)),
        _t("reseller_new", "ساخت کانفیگ توسط نماینده", exact=("reseller_new_config",), prefix=("reseller_fixed:",)),
    ]),
    ("support", "📞 پشتیبانی", [
        _t("contact", "📞 ارتباط با پشتیبانی", menu="btn_contact", exact=("contact_menu",)),
        _t("contact_direct", "پشتیبانی مستقیم", exact=("contact_direct",)),
        _t("contact_ai", "🤖 دستیار هوشمند", exact=("contact_ai",)),
        _t("ticket_new", "🎫 ثبت تیکت جدید", exact=("tickets_new",)),
        _t("ticket_list", "🎫 تیکت‌های من", exact=("tickets_mine",), prefix=("ticket_view:",)),
    ]),
]


def _build_indexes():
    exact, prefixes, menus, cmds, labels, flat = {}, [], {}, {}, {}, []
    for key, label in SPECIAL_TARGETS:
        labels[key] = label
        flat.append(key)
    for _gk, _title, items in GROUPS:
        for t in items:
            key = t["key"]
            if key in labels:
                raise ValueError(f"tutorial target تکراری: {key}")
            if len(BUTTON_PREFIX + key) > 64:
                raise ValueError(f"tutorial target خیلی بلند: {key}")
            labels[key] = t["label"]
            flat.append(key)
            if t["menu"]:
                menus[t["menu"]] = key
            for e in t["exact"]:
                exact[e] = key
            for p in t["prefix"]:
                prefixes.append((p, key))
            for c in t["cmd"]:
                cmds[c] = key
    prefixes.sort(key=lambda x: -len(x[0]))
    return exact, prefixes, menus, cmds, labels, flat


_EXACT, _PREFIXES, MENU_TARGETS, _COMMANDS, TARGET_LABELS, FLAT_KEYS = _build_indexes()


def target_label(key: str) -> str:
    return TARGET_LABELS.get(key, key)


def describe_targets(keys, limit: int = 8) -> str:
    """لیست خوانای مقصدهای متصل (به‌ترتیب ثابت)، با خلاصه‌سازی اگر زیاد بود."""
    ordered = [k for k in FLAT_KEYS if k in keys]
    names = [target_label(k) for k in ordered[:limit]]
    text = "، ".join(names)
    if len(ordered) > limit:
        text += f" و {len(ordered) - limit} مورد دیگر"
    return text


def resolve_target(db, event):
    """کلید مقصد آپدیت جاری را برمی‌گرداند (یا None)."""
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        if data.startswith("mm:"):
            return MENU_TARGETS.get(data[3:])
        key = _EXACT.get(data)
        if key:
            return key
        for prefix, key in _PREFIXES:
            if data.startswith(prefix):
                return key
        return None
    if isinstance(event, Message):
        text = (event.text or "").strip()
        if not text:
            return None
        if text.startswith("/"):
            return _COMMANDS.get(text.split()[0].split("@")[0].lower())
        for menu_key, target in MENU_TARGETS.items():
            if text == db.get_setting(menu_key):
                return target
    return None


def _event_chat_id(event):
    if isinstance(event, CallbackQuery):
        if event.message is not None:
            return event.message.chat.id
        return event.from_user.id
    if isinstance(event, Message):
        return event.chat.id
    return None


_CTX = contextvars.ContextVar("tutorial_ctx", default=None)


class TutorialTargetMiddleware(BaseMiddleware):
    """مقصد آپدیت جاری را (فقط اگر آموزشی برایش ثبت شده) در contextvar می‌گذارد."""

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def __call__(self, handler, event, data):
        token = None
        try:
            key = resolve_target(self.db, event)
            if key and key in self.db.get_tutorial_bound_targets():
                chat_id = _event_chat_id(event)
                if chat_id is not None:
                    token = _CTX.set({"key": key, "chat_id": chat_id, "t": time.monotonic(), "done": False})
        except Exception:
            log.exception("تشخیص مقصد آموزش ناموفق بود.")
        try:
            return await handler(event, data)
        finally:
            if token is not None:
                try:
                    _CTX.reset(token)
                except ValueError:
                    _CTX.set(None)


_SEND_METHODS = {"SendMessage", "SendPhoto", "SendVideo", "SendDocument", "SendAnimation"}
_EDIT_METHODS = {"EditMessageText", "EditMessageCaption"}


def _is_back_row(row) -> bool:
    if len(row) != 1:
        return False
    text = row[0].text or ""
    return "بازگشت" in text or "انصراف" in text or text.startswith(("⬅", "🔙", "↩", "❌"))


class TutorialRequestMiddleware:
    """middleware درخواست‌های خروجی بات: دکمه‌ی «📚 آموزش» را به پیام صفحه اضافه می‌کند."""

    def __init__(self, db):
        self.db = db

    def _button(self, key: str) -> InlineKeyboardButton:
        text = tr(self.db.get_setting(BUTTON_TEXT_SETTING, DEFAULT_BUTTON_TEXT) or DEFAULT_BUTTON_TEXT)
        return InlineKeyboardButton(text=text, callback_data=f"{BUTTON_PREFIX}{key}")

    def prepare(self, ctx, method):
        """(method جدید، markup پیام همراه یا None) را برمی‌گرداند."""
        name = type(method).__name__
        is_send = name in _SEND_METHODS
        is_edit = name in _EDIT_METHODS
        if not (is_send or is_edit):
            return method, None
        if time.monotonic() - ctx["t"] > CONTEXT_TTL:
            return method, None
        if str(getattr(method, "chat_id", None)) != str(ctx["chat_id"]):
            return method, None
        if is_send and ctx["done"]:
            return method, None
        markup = getattr(method, "reply_markup", None)
        button = self._button(ctx["key"])
        if isinstance(markup, InlineKeyboardMarkup):
            rows = [list(r) for r in markup.inline_keyboard]
            if any((b.callback_data or "").startswith(BUTTON_PREFIX) for r in rows for b in r):
                return method, None
            at = len(rows) - 1 if rows and _is_back_row(rows[-1]) else len(rows)
            rows.insert(at, [button])
            ctx["done"] = True
            return method.model_copy(update={"reply_markup": InlineKeyboardMarkup(inline_keyboard=rows)}), None
        if markup is None:
            if is_edit:
                return method, None
            ctx["done"] = True
            new_markup = InlineKeyboardMarkup(inline_keyboard=[[button]])
            return method.model_copy(update={"reply_markup": new_markup}), None
        if is_send:
            ctx["done"] = True
            return method, InlineKeyboardMarkup(inline_keyboard=[[button]])
        return method, None

    async def __call__(self, make_request, bot, method):
        ctx = _CTX.get()
        companion = None
        if ctx is not None:
            try:
                method, companion = self.prepare(ctx, method)
            except Exception:
                log.exception("افزودن دکمه‌ی آموزش ناموفق بود.")
        result = await make_request(bot, method)
        if companion is not None:
            try:
                await bot.send_message(ctx["chat_id"], tr(COMPANION_TEXT), reply_markup=companion)
            except Exception:
                log.exception("ارسال پیام همراه دکمه‌ی آموزش ناموفق بود.")
        return result


def install(bot, dp, db) -> None:
    """middlewareهای آموزش را روی یک بات و dispatcher آن نصب می‌کند."""
    bot.session.middleware(TutorialRequestMiddleware(db))
    target_mw = TutorialTargetMiddleware(db)
    dp.message.outer_middleware(target_mw)
    dp.callback_query.outer_middleware(target_mw)
