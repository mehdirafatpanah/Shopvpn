# -*- coding: utf-8 -*-
"""مسیر ورود مخفی پنل وب (اختیاری، پیش‌فرض خاموش).

وقتی روشن باشد، پنل وب فقط برای مرورگری که یک‌بار آدرس https://دامنه/<مسیر> را باز کرده
(و کوکی گیت گرفته) پاسخ می‌دهد؛ بقیه‌ی درخواست‌ها شبیه یک سرور خالی 404 می‌گیرند.
تنظیمات در دیتابیس اصلی نگه‌داری می‌شود و هم پنل وب و هم بات (برای ساخت لینک) از همین ماژول می‌خوانند.
"""

import hashlib
import hmac
import re
import sqlite3
import time

KEY_ENABLED = "web_entry_path_enabled"
KEY_PATH = "web_entry_path"
COOKIE_NAME = "sv_gate"
COOKIE_MAX_AGE = 90 * 24 * 3600
SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
RESERVED = {
    "api", "assets", "app", "setup", "_chunk", "sw.js", "manifest.json",
    "docs", "redoc", "openapi.json", "static", "favicon.ico", "robots.txt",
}
_TTL = 3.0
_cache = {"at": 0.0, "val": (False, "")}


def validate_slug(slug: str) -> str:
    """برمی‌گرداند پیام خطا؛ رشته‌ی خالی یعنی معتبر."""
    slug = (slug or "").strip()
    if not SLUG_RE.match(slug):
        return "مسیر باید ۶ تا ۶۴ کاراکتر و فقط حروف انگلیسی، عدد، خط تیره و آندرلاین باشد."
    if slug.lower() in RESERVED:
        return "این مسیر رزرو شده است؛ یک مسیر دیگر انتخاب کن."
    return ""


def _read_raw() -> tuple:
    try:
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH, timeout=2)
        try:
            rows = dict(conn.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?)", (KEY_ENABLED, KEY_PATH)
            ).fetchall())
        finally:
            conn.close()
    except Exception:
        return _cache["val"]
    slug = (rows.get(KEY_PATH) or "").strip()
    enabled = str(rows.get(KEY_ENABLED) or "0").strip() == "1" and not validate_slug(slug)
    return (enabled, slug)


def get_config(force: bool = False) -> tuple:
    """(enabled, slug)؛ با کش کوتاه‌مدت تا هر درخواست به دیتابیس نخورد."""
    now = time.monotonic()
    if force or now - _cache["at"] > _TTL:
        _cache["val"] = _read_raw()
        _cache["at"] = now
    return _cache["val"]


def invalidate() -> None:
    _cache["at"] = 0.0


def cookie_value(secret: str, slug: str) -> str:
    return hmac.new((secret or "").encode(), f"gate:{slug}".encode(), hashlib.sha256).hexdigest()[:40]


def cookie_valid(secret: str, slug: str, value: str) -> bool:
    return bool(value) and hmac.compare_digest(cookie_value(secret, slug), value)


def with_entry_path(url: str) -> str:
    """اگر مسیر مخفی روشن است، آن را به آدرس پایه‌ی پنل اضافه می‌کند تا لینک‌های ساخته‌شده کار کنند."""
    url = (url or "").rstrip("/")
    if not url:
        return url
    enabled, slug = get_config()
    if enabled and slug and not url.endswith("/" + slug):
        return f"{url}/{slug}"
    return url
