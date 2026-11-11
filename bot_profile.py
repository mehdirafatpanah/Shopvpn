# -*- coding: utf-8 -*-
"""
پروفایل ربات: «توضیحات» و «توضیح کوتاه» که تلگرام قبل از زدن Start نشان می‌دهد.

  • description        → متن زیر «What can this bot do?»   (حداکثر ۵۱۲ کاراکتر)
  • short_description  → متن کوتاه صفحه‌ی پروفایل ربات      (حداکثر ۱۲۰ کاراکتر)

هر دو برای زبان fa و en جدا تنظیم می‌شوند. زبان «پیش‌فرض» تلگرام (برای کاربرانی که
زبانشان fa/en نیست) از متن فارسی پر می‌شود و اگر خالی بود از انگلیسی.

عکس/گیف توضیحات (Description Picture) API ندارد و فقط از BotFather قابل تنظیم است.

این ماژول فقط به aiohttp وابسته است تا هر سه پروسه (بات، پنل وب، مینی‌اپ) بتوانند با
توکن همان مستأجر (بات اصلی یا نماینده) آن را صدا بزنند. فقط تفاوت نسبت به آخرین
مقدارِ اعمال‌شده به تلگرام ارسال می‌شود تا محدودیت نرخ تلگرام فعال نشود.
"""

import asyncio
import json
import logging

import aiohttp

logger = logging.getLogger("bot_profile")

DESC_MAX = 512
SHORT_MAX = 120
LANGS = ("fa", "en")

KEY_DESC = {"fa": "bot_desc_fa", "en": "bot_desc_en"}
KEY_SHORT = {"fa": "bot_short_desc_fa", "en": "bot_short_desc_en"}
PROFILE_KEYS = frozenset(list(KEY_DESC.values()) + list(KEY_SHORT.values()))
APPLIED_KEY = "bot_profile_applied"  # JSON: آخرین مقدار اعمال‌شده برای هر (نوع، زبان)

_METHODS = {
    "desc": ("setMyDescription", "description"),
    "short": ("setMyShortDescription", "short_description"),
}


def _get(db, key: str) -> str:
    v = db.get_setting(key, "")
    return "" if v is None else str(v).strip()


def desired(db) -> dict:
    """مقدار مطلوب برای هر «نوع:زبان». زبان خالی = پیش‌فرض تلگرام."""
    out = {}
    for kind, keys in (("desc", KEY_DESC), ("short", KEY_SHORT)):
        for lang in LANGS:
            out[f"{kind}:{lang}"] = _get(db, keys[lang])
        out[f"{kind}:"] = out[f"{kind}:fa"] or out[f"{kind}:en"]
    return out


def has_profile_keys(changed) -> bool:
    return bool(PROFILE_KEYS.intersection(changed or ()))


def _load_applied(db) -> dict:
    try:
        data = json.loads(db.get_setting(APPLIED_KEY, "") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _call(session, token: str, method: str, payload: dict):
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        data = await resp.json(content_type=None)
    return data


async def apply_profile(token: str, db, force: bool = False) -> dict:
    """
    تفاوت تنظیمات با آخرین مقدار اعمال‌شده را روی تلگرام می‌گذارد.
    خروجی: {"ok": bool, "applied": [..], "errors": {کلید: پیام}}
    هرگز استثنا نمی‌اندازد (ذخیره‌ی تنظیمات نباید به خاطر خطای تلگرام شکست بخورد).
    """
    result = {"ok": True, "applied": [], "errors": {}}
    if not token:
        result.update(ok=False, errors={"token": "no token"})
        return result
    try:
        wanted = desired(db)
        applied = _load_applied(db)
        todo = [k for k, v in wanted.items() if force or applied.get(k, "") != v]
        if not todo:
            return result
        async with aiohttp.ClientSession() as session:
            for k in todo:
                kind, lang = k.split(":", 1)
                method, field = _METHODS[kind]
                text = wanted[k]
                limit = DESC_MAX if kind == "desc" else SHORT_MAX
                if len(text) > limit:
                    result["errors"][k] = f"too long ({len(text)}>{limit})"
                    continue
                payload = {field: text}
                if lang:
                    payload["language_code"] = lang
                try:
                    data = await _call(session, token, method, payload)
                except Exception as e:  # شبکه/زمان‌بندی
                    result["errors"][k] = str(e)[:200]
                    continue
                if data.get("ok"):
                    applied[k] = text
                    result["applied"].append(k)
                else:
                    result["errors"][k] = str(data.get("description", "unknown error"))[:200]
                    retry = (data.get("parameters") or {}).get("retry_after")
                    if retry:  # flood control: بقیه را در تلاش بعدی می‌فرستیم
                        break
                await asyncio.sleep(0.4)
        db.set_setting(APPLIED_KEY, json.dumps(applied, ensure_ascii=False))
    except Exception:
        logger.exception("اعمال پروفایل ربات ناموفق بود.")
        result["errors"]["internal"] = "unexpected error"
    result["ok"] = not result["errors"]
    return result


def apply_profile_sync(token: str, db, force: bool = False) -> dict:
    """برای endpointهای sync فست‌ای‌پی‌آی (که در threadpool و بدون event loop اجرا می‌شوند)."""
    return asyncio.run(apply_profile(token, db, force=force))
