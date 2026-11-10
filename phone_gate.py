# -*- coding: utf-8 -*-
"""محدودیت خرید بر اساس پیش‌شماره‌ی شماره‌ی موبایل تاییدشده با دکمه‌ی اشتراک‌گذاری تلگرام."""

import asyncio
import json
import logging
import re

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

from i18n import tr

logger = logging.getLogger(__name__)

SETTING_ENABLED = "phone_verify_enabled"
SETTING_COUNTRIES = "phone_verify_countries"

DEFAULT_COUNTRIES = (
    ("98", "🇮🇷 ایران", True),
    ("93", "🇦🇫 افغانستان", False),
    ("964", "🇮🇶 عراق", False),
    ("90", "🇹🇷 ترکیه", False),
    ("971", "🇦🇪 امارات", False),
    ("966", "🇸🇦 عربستان", False),
    ("965", "🇰🇼 کویت", False),
    ("974", "🇶🇦 قطر", False),
    ("973", "🇧🇭 بحرین", False),
    ("968", "🇴🇲 عمان", False),
    ("92", "🇵🇰 پاکستان", False),
    ("91", "🇮🇳 هند", False),
    ("994", "🇦🇿 آذربایجان", False),
    ("374", "🇦🇲 ارمنستان", False),
    ("993", "🇹🇲 ترکمنستان", False),
    ("992", "🇹🇯 تاجیکستان", False),
    ("998", "🇺🇿 ازبکستان", False),
    ("7", "🇷🇺 روسیه / قزاقستان", False),
    ("49", "🇩🇪 آلمان", False),
    ("44", "🇬🇧 انگلیس", False),
    ("1", "🇺🇸 آمریکا / کانادا", False),
    ("33", "🇫🇷 فرانسه", False),
    ("31", "🇳🇱 هلند", False),
    ("46", "🇸🇪 سوئد", False),
)

GATED_EXACT = ("custom_config_start", "start_topup")
GATED_PREFIXES = (
    "prod:", "buy_start:", "buy_users:", "buy_users_pick:", "ccf_pick_product:",
    "svc_renew:", "svc_renew_pick:", "renew_confirm_pay:", "pay_",
)


def normalize_phone(raw) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[2:] if digits.startswith("00") else digits


def default_countries() -> list:
    return [{"p": p, "n": n, "a": a} for p, n, a in DEFAULT_COUNTRIES]


def load_countries(db) -> list:
    raw = (db.get_setting(SETTING_COUNTRIES, "") or "").strip()
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        data = []
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        prefix = re.sub(r"\D", "", str(item.get("p", "")))
        if not prefix:
            continue
        out.append({"p": prefix, "n": str(item.get("n", "")).strip() or f"+{prefix}", "a": bool(item.get("a"))})
    return out or default_countries()


def is_enabled(db) -> bool:
    return (db.get_setting(SETTING_ENABLED, "0") or "0") == "1"


def match_country(db, phone):
    digits = normalize_phone(phone)
    best = None
    for country in load_countries(db):
        if country["a"] and digits.startswith(country["p"]) and (best is None or len(country["p"]) > len(best["p"])):
            best = country
    return best


def user_ok(db, tg_id: int) -> bool:
    phone, verified = db.get_user_phone_info(tg_id)
    return bool(verified and phone and match_country(db, phone))


def describe_allowed(db) -> str:
    return "، ".join(f"{c['n']} (+{c['p']})" for c in load_countries(db) if c["a"])


def is_blocked(db, tg_id: int) -> bool:
    return is_enabled(db) and not db.is_admin(tg_id) and not user_ok(db, tg_id)


def prompt_text(db) -> str:
    return tr(
        "📱 برای خرید، شماره موبایل خود را فقط با دکمه‌ی «اشتراک‌گذاری شماره موبایل» پایین ارسال کنید.\n\n"
        f"شماره‌های مجاز: {describe_allowed(db) or '—'}\n\n"
        "⚠️ شماره‌ی تایپ‌شده یا شماره‌ی افراد دیگر پذیرفته نمی‌شود."
    )


class PhoneGateMiddleware(BaseMiddleware):
    """دکمه‌های مسیر خرید/تمدید/شارژ را برای کاربر بدون شماره‌ی مجاز مسدود می‌کند."""

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def __call__(self, handler, event, data: dict):
        if not isinstance(event, CallbackQuery) or event.from_user is None:
            return await handler(event, data)
        cb = event.data or ""
        if cb not in GATED_EXACT and not cb.startswith(GATED_PREFIXES):
            return await handler(event, data)
        try:
            blocked = await asyncio.to_thread(is_blocked, self.db, event.from_user.id)
        except Exception:
            logger.warning("بررسی تایید شماره ناموفق بود؛ عبور داده شد.", exc_info=True)
            return await handler(event, data)
        if not blocked:
            return await handler(event, data)
        await event.answer(tr("برای خرید ابتدا باید شماره موبایل خود را تایید کنید."), show_alert=True)
        try:
            import keyboards as kb
            await event.message.answer(await asyncio.to_thread(prompt_text, self.db), reply_markup=kb.share_phone_kb())
        except Exception:
            logger.warning("ارسال درخواست شماره ناموفق بود.", exc_info=True)
        return None
