# -*- coding: utf-8 -*-
"""شخصی‌سازی فروشگاه وب (تب «شخصی‌سازی وب» در پنل ادمین).

این ماژول عمداً هیچ وابستگی سنگینی (FastAPI و ...) ندارد تا هم در routes.py و server.py
استفاده شود و هم مستقل تست شود. همه‌ی مقادیر از تنظیمات خوانده و پاک‌سازی می‌شوند؛
مقدار نامعتبر = نادیده گرفته می‌شود و هرگز صفحه را خراب نمی‌کند.
"""
import re
from typing import Callable, Dict, List, Tuple

NOTICE_STYLES = ("info", "success", "warning", "danger")
SORT_MODES = ("value", "low", "high")

MAX_NOTICE = 300
MAX_MAINTENANCE = 400
MAX_FOOTER = 200
MAX_FAQ_ITEMS = 30
MAX_FAQ_Q = 200
MAX_FAQ_A = 1500
MAX_TERMS_SECTIONS = 20
MAX_TERMS_TITLE = 120
MAX_TERMS_LINES = 30
MAX_TERMS_LINE = 500

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_TG_ID_RE = re.compile(r"^@([A-Za-z0-9_]{4,32})$")
_IG_ID_RE = re.compile(r"^@([A-Za-z0-9_.]{1,30})$")

# مسیرهای POST که در حالت تعمیرات بسته می‌شوند (ساخت سفارش جدید، فاکتور پرداخت و تمدید کامل).
# بارگذاری رسید برای سفارش‌های قبلاً ساخته‌شده و مسیرهای خواندنی عمداً باز می‌مانند.
_BLOCKED_PREFIXES = ("/api/orders", "/api/custom-configs/")


def _clean(value, limit: int) -> str:
    text = (value or "")
    if not isinstance(text, str):
        text = str(text)
    # حذف نویسه‌های کنترلی (به‌جز خط جدید و تب)، سپس برش طول.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()[:limit]


def safe_link(value: str) -> str:
    """لینک مجاز: https://، http://، t.me/...، یا @آیدی تلگرام؛ غیر از این خالی."""
    v = _clean(value, 500)
    if not v or any(ch.isspace() for ch in v):
        return ""
    m = _TG_ID_RE.match(v)
    if m:
        return "https://t.me/" + m.group(1)
    if re.match(r"^(t\.me|telegram\.me)/", v, re.I):
        v = "https://" + v
    return v if re.match(r"^https?://[^\s]+$", v, re.I) else ""


def safe_https_url(value: str) -> str:
    """فقط HTTPS (برای تصویر/آیکون)."""
    v = _clean(value, 500)
    if not v or any(ch.isspace() for ch in v) or '"' in v or "<" in v or ">" in v:
        return ""
    return v if re.match(r"^https://[^\s]+$", v, re.I) else ""


def safe_instagram(value: str) -> str:
    v = _clean(value, 300)
    if not v or any(ch.isspace() for ch in v):
        return ""
    m = _IG_ID_RE.match(v)
    if m:
        return "https://instagram.com/" + m.group(1)
    if re.match(r"^(www\.)?instagram\.com/", v, re.I):
        v = "https://" + v
    return v if re.match(r"^https://(www\.)?instagram\.com/[^\s]*$", v, re.I) else ""


def safe_email(value: str) -> str:
    v = _clean(value, 200)
    return v if _EMAIL_RE.match(v) else ""


def parse_blocks(text: str, max_blocks: int, max_title: int, max_body_line: int,
                 max_lines: int) -> List[Tuple[str, List[str]]]:
    """متن را به بلوک‌هایی تبدیل می‌کند که با یک خط خالی از هم جدا شده‌اند.

    خط اول هر بلوک = عنوان (سؤال/سرفصل)، بقیه‌ی خطوط = متن (پاسخ/موارد).
    بلوکی که فقط عنوان دارد و متن ندارد نادیده گرفته می‌شود.
    """
    out: List[Tuple[str, List[str]]] = []
    raw = _clean(text, 60000)
    if not raw:
        return out
    for block in re.split(r"\n\s*\n", raw):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        title = lines[0][:max_title]
        body = [ln[:max_body_line] for ln in lines[1:max_lines + 1]]
        out.append((title, body))
        if len(out) >= max_blocks:
            break
    return out


def parse_faq(text: str) -> List[List[str]]:
    blocks = parse_blocks(text, MAX_FAQ_ITEMS, MAX_FAQ_Q, MAX_FAQ_A, 12)
    return [[q, "\n".join(a)[:MAX_FAQ_A]] for q, a in blocks]


def parse_terms(text: str) -> List[list]:
    blocks = parse_blocks(text, MAX_TERMS_SECTIONS, MAX_TERMS_TITLE, MAX_TERMS_LINE, MAX_TERMS_LINES)
    return [[title, body] for title, body in blocks]


def _flag(get: Callable[[str, str], str], key: str, default: str = "0") -> bool:
    return str(get(key, default) or default).strip() == "1"


def maintenance_message(get: Callable[[str, str], str]) -> str:
    """متن حالت تعمیرات (رشته‌ی خالی = حالت تعمیرات خاموش است)."""
    if not _flag(get, "web_store_maintenance"):
        return ""
    custom = _clean(get("web_store_maintenance_text", ""), MAX_MAINTENANCE)
    return custom or "__default__"


def is_blocked_in_maintenance(method: str, path: str) -> bool:
    """آیا این درخواست در حالت تعمیرات باید رد شود؟ فقط ثبت سفارش/فاکتور/تمدید."""
    if method.upper() != "POST":
        return False
    if path == "/api/orders":
        return True
    if path.startswith("/api/orders/") and ("invoice" in path):
        return True
    if path.startswith("/api/custom-configs/") and path.endswith("/renew-full"):
        return True
    return False


def build_custom_payload(get: Callable[[str, str], str]) -> Dict[str, object]:
    """همه‌ی مقادیر شخصی‌سازی که کاتالوگ عمومی به فرانت می‌دهد (فقط کلیدهای معتبر)."""
    out: Dict[str, object] = {}

    # --- اعلان بالای صفحه
    if _flag(get, "web_store_notice_enabled"):
        text = _clean(get("web_store_notice_text", ""), MAX_NOTICE)
        if text:
            style = _clean(get("web_store_notice_style", "info"), 20).lower()
            out["notice"] = {
                "text": text,
                "link": safe_link(get("web_store_notice_link", "")),
                "style": style if style in NOTICE_STYLES else "info",
            }

    # --- حالت تعمیرات
    maint = maintenance_message(get)
    if maint:
        out["maintenance"] = {"text": "" if maint == "__default__" else maint}

    # --- فوتر و راه‌های تماس
    footer = {
        "text": _clean(get("web_store_footer_text", ""), MAX_FOOTER),
        "channel": safe_link(get("web_store_channel_url", "")),
        "instagram": safe_instagram(get("web_store_instagram_url", "")),
        "email": safe_email(get("web_store_email", "")),
    }
    if any(footer.values()):
        out["footer"] = footer

    # --- نمایش پلن‌ها
    sort = _clean(get("web_store_default_sort", "value"), 10).lower()
    out["default_sort"] = sort if sort in SORT_MODES else "value"

    # --- محتوای سفارشی (فقط صفحه‌ی فارسی؛ در فرانت اعمال می‌شود)
    faq = parse_faq(get("web_store_faq_custom", ""))
    if faq:
        out["faq_custom"] = faq
    terms = parse_terms(get("web_store_terms_custom", ""))
    if terms:
        out["terms_custom"] = terms
    return out


def hide_soldout(get: Callable[[str, str], str]) -> bool:
    return _flag(get, "web_store_hide_soldout")


def head_assets(get: Callable[[str, str], str]) -> Dict[str, str]:
    """فاوآیکون و تصویر اشتراک‌گذاری سفارشی؛ مقدار خالی = پیش‌فرض."""
    return {
        "favicon": safe_https_url(get("web_store_favicon", "")),
        "og_image": safe_https_url(get("web_store_og_image", "")),
    }
