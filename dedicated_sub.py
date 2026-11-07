# -*- coding: utf-8 -*-
"""
هسته‌ی «ساب اختصاصی» ShopVPN.

این ماژول فقط منطق خالص (بدون شبکه و بدون وابستگی به aiogram/FastAPI) را نگه می‌دارد تا هم بات
(برای ساخت لینک اختصاصی) و هم سرور ساب (sub_server/server.py) از آن استفاده کنند و راحت تست شود:

  • کلیدهای تنظیمات و مقادیر پیش‌فرض (همه از داخل بات قابل تغییرند)
  • ساخت لینک اختصاصی از روی توکن سرویس
  • فهرست برنامه‌ها برای همه‌ی سیستم‌عامل‌ها (با لینک «افزودن به برنامه» و دانلود) + شخصی‌سازی ادمین
  • تحلیل خروجی ساب پنل، محاسبه‌ی وضعیت سرویس، ساخت هدرها، «خط اول ساب» و کانفیگ نمایشی
  • ساخت داده‌ی صفحه‌ی وب (همان طرح فایل نمونه) و نمودار مصرف

اجرای خط فرمان (برای manage.sh):
    python -m dedicated_sub enable | disable | status
"""

import base64
import binascii
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, List, Optional

GB = 1024 ** 3

# ---------------------------------------------------------------------------
# تنظیمات (همه با پیشوند dsub_ در جدول settings؛ از منوی ادمین بات تغییر می‌کنند)
# ---------------------------------------------------------------------------
DSUB_DEFAULTS: Dict[str, str] = {
    "dsub_enabled": "0",                # کلید اصلی: روشن/خاموش
    "dsub_base_url": "",                # اگر پر باشد، جای DEDICATED_SUB_URL داخل .env را می‌گیرد
    "dsub_web_page": "1",               # نمایش صفحه‌ی وب به مرورگرها
    "dsub_brand": "",                   # نام برند در صفحه (خالی = نام فروشگاه)
    "dsub_logo_url": "",                # لوگوی صفحه (آدرس https)
    "dsub_notice": "",                  # اطلاعیه‌ی بالای صفحه + هدر announce داخل اپ‌ها
    "dsub_support_url": "",             # لینک پشتیبانی (t.me/... یا https://...)
    "dsub_footer_text": "",             # متن پایین صفحه
    "dsub_theme": "auto",               # auto / light / dark
    "dsub_style": "minimal",             # minimal / modern / glass / cyberpunk / classic
    "dsub_accent_color": "#6366F1",
    "dsub_secondary_color": "#06B6D4",
    "dsub_card_style": "rounded",
    "dsub_density": "comfortable",
    "dsub_show_configs": "1",           # بخش «کانفیگ‌ها» در صفحه
    "dsub_show_chart": "1",             # نمودار مصرف
    "dsub_show_qr": "1",                # دکمه‌های QR
    "dsub_show_apps": "1",              # بخش «برنامه‌ها»
    "dsub_show_faq": "1",               # بخش «اگر وصل نشد»
    "dsub_profile_title": "{name}",     # عنوان پروفایل داخل اپ؛ متغیرها: {name} {user} {brand}
    "dsub_update_interval": "12",       # ساعت؛ هدر profile-update-interval (۰ = از پنل)
    "dsub_info_line": "0",              # «خط اول ساب»: حجم و روز باقی‌مانده
    "dsub_info_line_text": "📊 {volume} | ⏳ {days}",
    "dsub_expired_placeholder": "1",    # کانفیگ نمایشی برای سرویس منقضی/تمام‌شده
    "dsub_expired_text": "⛔ سرویس شما به پایان رسیده؛ برای تمدید به ربات مراجعه کنید",
    "dsub_limited_text": "⛔ حجم سرویس شما تمام شده؛ برای تمدید به ربات مراجعه کنید",
    "dsub_cache_ttl": "30",            # ثانیه؛ کش پاسخ پنل
    "dsub_usage_sampling": "1",         # نمونه‌برداری ساعتی مصرف برای نمودار
    "dsub_log_enabled": "1",            # لاگ دسترسی
    "dsub_faq": "",                     # هر خط: «سوال | جواب» (خالی = پیش‌فرض)
    "dsub_apps_hidden": "",             # «ios:Streisand,android:v2rayNG»
    "dsub_apps_rec": "",                # برنامه‌ی پیشنهادی هر سیستم‌عامل: «ios:Hiddify,android:v2rayNG»
    "dsub_custom_apps": "",             # هر خط: platform|name|توضیح|پیشوند-افزودن|لینک-دانلود
    "dsub_custom_template_enabled": "0",  # استفاده از قالب HTML اختصاصی به‌جای قالب پیش‌فرض صفحه
    "dsub_custom_template": "",         # کد کامل HTML قالب اختصاصی (باید شامل __DATA__ باشد)
}

PLATFORMS = ("ios", "android", "windows", "mac", "linux")
PLATFORM_LABELS = {"ios": "iOS", "android": "اندروید", "windows": "ویندوز", "mac": "مک", "linux": "لینوکس"}

THEMES = ("auto", "light", "dark")


def _gh(repo: str) -> str:
    return f"https://github.com/{repo}/releases"


def _as(name: str, app_id: int) -> str:
    return f"https://apps.apple.com/app/{name}/id{app_id}"


_D = {
    "streisand": "کلاینت پراکسی انعطاف‌پذیر با پشتیبانی از Reality، VMess، Trojan و Shadowsocks.",
    "hiddify": "متن‌باز و چندپروتکلی، با تنظیم خودکار.",
    "singbox": "کلاینت رسمی Sing-box برای مسیریابی امن ترافیک.",
    "happ": "رابط ساده با افزودن سریع اشتراک.",
    "karing": "کلاینت چندسکویی با قوانین مسیریابی آماده.",
    "v2box": "کلاینت ساده و سبک V2Ray.",
    "foxray": "کلاینت Xray با پشتیبانی کامل از Reality.",
    "npv": "کلاینت تانل با پشتیبانی از چند پروتکل.",
    "flclash": "رابط گرافیکی چندسکویی برای Clash core.",
    "verge": "رابط مدرن Clash با قوانین مسیریابی قابل تنظیم.",
    "nekoray": "کلاینت Qt با پشتیبانی از Xray و sing-box.",
}

# «add» پیشوند deep-link افزودن اشتراک است (آدرس ساب به‌صورت URL-encode به انتهایش می‌چسبد)؛
# «fmt»: روش ساخت لینک — پیش‌فرض plain، و "sr" برای Shadowrocket (آدرس base64).
BUILTIN_APPS: Dict[str, List[dict]] = {
    "ios": [
        {"n": "Streisand", "rec": 1, "d": _D["streisand"], "add": "streisand://import/", "dl": _as("streisand", 6450534064)},
        {"n": "V2Box", "d": "کلاینت ساده و سبک V2Ray برای iOS و مک.", "add": "v2box://install-sub?url=", "dl": _as("v2box-v2ray-client", 6446814690)},
        {"n": "Hiddify", "d": _D["hiddify"], "add": "hiddify://import/", "dl": _as("hiddify-proxy-vpn", 6596777532)},
        {"n": "SingBox", "d": _D["singbox"], "add": "sing-box://import-remote-profile?url=", "dl": "https://sing-box.sagernet.org/clients/ios/"},
        {"n": "Happ", "d": _D["happ"], "add": "happ://add/", "dl": "https://www.happ.su/main"},
        {"n": "Karing", "d": _D["karing"], "add": "karing://install-config?url=", "dl": _as("karing", 6472431552)},
        {"n": "FoXray", "d": _D["foxray"], "dl": _as("foxray", 6448898396)},
        {"n": "NPV Tunnel", "d": _D["npv"], "dl": _as("npv-tunnel", 1629465476)},
        {"n": "Shadowrocket", "d": "ابزار پراکسی قانون‌محور برای iOS (پولی).", "add": "shadowrocket://add/sub://", "fmt": "sr", "dl": _as("shadowrocket", 932747118)},
    ],
    "android": [
        {"n": "v2rayNG", "rec": 1, "d": "کلاینت V2Ray برای دستگاه‌های اندرویدی.", "add": "v2rayng://install-sub?url=", "dl": _gh("2dust/v2rayNG")},
        {"n": "Hiddify", "d": _D["hiddify"], "add": "hiddify://import/", "dl": _gh("hiddify/hiddify-app")},
        {"n": "SingBox", "d": _D["singbox"], "add": "sing-box://import-remote-profile?url=", "dl": "https://sing-box.sagernet.org/clients/android/"},
        {"n": "V2Box", "d": _D["v2box"], "add": "v2box://install-sub?url=", "dl": "https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box"},
        {"n": "NPV Tunnel", "d": _D["npv"], "dl": "https://play.google.com/store/apps/details?id=com.napsternetlabs.napsternetv"},
        {"n": "NekoBox", "d": "کلاینت قدرتمند با پشتیبانی از پروتکل‌های متعدد.", "add": "sn://subscription?url=", "dl": _gh("MatsuriDayo/NekoBoxForAndroid")},
        {"n": "Karing", "d": _D["karing"], "add": "karing://install-config?url=", "dl": _gh("KaringX/karing")},
        {"n": "Happ", "d": _D["happ"], "add": "happ://add/", "dl": "https://www.happ.su/main"},
        {"n": "FlClash", "d": _D["flclash"], "add": "clash://install-config?url=", "dl": _gh("chen08209/FlClash")},
    ],
    "windows": [
        {"n": "v2rayN", "rec": 1, "d": "کلاینت V2Ray برای ویندوز با پشتیبانی از رابط کاربری.", "dl": _gh("2dust/v2rayN")},
        {"n": "Hiddify", "d": _D["hiddify"], "add": "hiddify://import/", "dl": _gh("hiddify/hiddify-app")},
        {"n": "FlClash", "d": _D["flclash"], "add": "clash://install-config?url=", "dl": _gh("chen08209/FlClash")},
        {"n": "Clash Verge Rev", "d": _D["verge"], "add": "clash://install-config?url=", "dl": _gh("clash-verge-rev/clash-verge-rev")},
        {"n": "Nekoray", "d": _D["nekoray"], "dl": _gh("MatsuriDayo/nekoray")},
        {"n": "Karing", "d": _D["karing"], "add": "karing://install-config?url=", "dl": _gh("KaringX/karing")},
    ],
    "mac": [
        {"n": "Streisand", "rec": 1, "d": "کلاینت پراکسی انعطاف‌پذیر با پشتیبانی از Reality، VMess و Trojan.", "add": "streisand://import/", "dl": _as("streisand", 6450534064)},
        {"n": "Hiddify", "d": _D["hiddify"], "add": "hiddify://import/", "dl": _gh("hiddify/hiddify-app")},
        {"n": "FlClash", "d": _D["flclash"], "add": "clash://install-config?url=", "dl": _gh("chen08209/FlClash")},
        {"n": "Clash Verge Rev", "d": _D["verge"], "add": "clash://install-config?url=", "dl": _gh("clash-verge-rev/clash-verge-rev")},
        {"n": "SingBox", "d": "کلاینت رسمی Sing-box برای مک.", "add": "sing-box://import-remote-profile?url=", "dl": "https://sing-box.sagernet.org/clients/apple/"},
        {"n": "V2Box", "d": _D["v2box"], "add": "v2box://install-sub?url=", "dl": _as("v2box-v2ray-client", 6446814690)},
    ],
    "linux": [
        {"n": "FlClash", "rec": 1, "d": _D["flclash"], "add": "clash://install-config?url=", "dl": _gh("chen08209/FlClash")},
        {"n": "Hiddify", "d": _D["hiddify"], "add": "hiddify://import/", "dl": _gh("hiddify/hiddify-app")},
        {"n": "SingBox", "d": "کلاینت Sing-box برای مسیریابی امن ترافیک.", "dl": _gh("SagerNet/sing-box")},
        {"n": "Nekoray", "d": _D["nekoray"], "dl": _gh("MatsuriDayo/nekoray")},
        {"n": "Clash Verge Rev", "d": _D["verge"], "add": "clash://install-config?url=", "dl": _gh("clash-verge-rev/clash-verge-rev")},
    ],
}

DEFAULT_FAQ = [
    ("وصل شدم ولی اینترنت ندارم", "اشتراک را در برنامه آپدیت کن، بعد یک کانفیگ دیگر را امتحان کن."),
    ("فقط یک کانفیگ کار نمی‌کند", "کانفیگ‌ها را تکی وارد نکن. لینک اشتراک را اضافه کن تا همه با هم به‌روز شوند."),
    ("بعد از آپدیت هم وصل نمی‌شود", "تاریخ و ساعت گوشی باید روی حالت خودکار باشد."),
    ("هنوز مشکل دارم", "نام کاربری‌ات را برای پشتیبانی بفرست و بگو کدام مرحله خطا می‌دهد."),
]

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]{1,30}://", re.I)
_BAD_SCHEMES = ("http://", "https://", "javascript:", "data:", "vbscript:", "file:")


# ---------------------------------------------------------------------------
# خواندن تنظیمات و ساخت لینک
# ---------------------------------------------------------------------------
def get(db, key: str) -> str:
    return str(db.get_setting(key, DSUB_DEFAULTS.get(key, "")) or "")


def flag(db, key: str) -> bool:
    return get(db, key).strip() == "1"


def all_settings(db) -> Dict[str, str]:
    return {k: get(db, k) for k in DSUB_DEFAULTS}


def env_base_url() -> str:
    try:
        import config  # بارگذاری تنبل: config بدون .env خطا می‌دهد
        return (getattr(config, "DEDICATED_SUB_URL", "") or "").rstrip("/")
    except Exception:
        return (os.getenv("DEDICATED_SUB_URL", "") or "").rstrip("/")


def base_url(db) -> str:
    """آدرس پایه‌ی سرور ساب (بدون اسلش پایانی)؛ اول تنظیم داخل بات، بعد .env."""
    custom = get(db, "dsub_base_url").strip().rstrip("/")
    if custom.startswith(("http://", "https://")):
        return custom
    return env_base_url()


def is_enabled(db) -> bool:
    return flag(db, "dsub_enabled") and bool(base_url(db))


WUI_DSUB_WARNING = ("⚠️ برای پنل W-UI ساب اختصاصی باید روشن باشد: دانلود فایل‌های WireGuard/OpenVPN و بخش "
                    "OpenConnect/L2TP/PPTP/IKEv2 فقط با ساب اختصاصی روشن (و آدرس پایه‌ی تنظیم‌شده) کار می‌کند. "
                    "ساب اختصاصی را از تنظیمات روشن کن.")


def wui_dsub_warning(db, panel_type: str) -> str:
    """متن هشدار اگر پنل W-UI است و ساب اختصاصی خاموش است؛ وگرنه رشته‌ی خالی."""
    return WUI_DSUB_WARNING if panel_type == "wui" and not is_enabled(db) else ""


def link_for_token(db, token: str) -> str:
    return f"{base_url(db)}/s/{token}"


def link_for_config(db, config_id: int) -> Optional[str]:
    if not is_enabled(db):
        return None
    token = db.ds_get_or_create_token(config_id)
    return link_for_token(db, token) if token else None


def dedicated_link_for_upstream(db, upstream_url: str) -> str:
    """لینک اختصاصی معادل یک لینک ساب پنل؛ اگر قابلیت خاموش است یا سرویسی پیدا نشد،
    همان لینک اصلی را برمی‌گرداند (هرگز خطا نمی‌دهد: روی مسیر تحویل کانفیگ به کاربر قرار دارد)."""
    try:
        if not upstream_url or not str(upstream_url).startswith(("http://", "https://")):
            return upstream_url
        if not is_enabled(db):
            return upstream_url
        row = db.ds_find_config_by_sub_url(upstream_url)
        if row is None:
            return upstream_url
        return link_for_config(db, row["id"]) or upstream_url
    except Exception:
        return upstream_url


def display_link(db, config_id, upstream_url: str) -> str:
    """لینک نمایشی سرویس با شناسه‌ی مشخص؛ در هر خطا یا خاموش بودن همان لینک پنل."""
    try:
        if config_id and is_enabled(db):
            return link_for_config(db, config_id) or upstream_url
    except Exception:
        pass
    return upstream_url


def upstream_for_link(db, link: str) -> str:
    """اگر لینک ورودی اختصاصی باشد معادل لینک پنل را برمی‌گرداند، وگرنه خود لینک."""
    try:
        base = base_url(db)
        prefix = f"{base}/s/" if base else ""
        if not prefix or not str(link).startswith(prefix):
            return link
        token = str(link)[len(prefix):].split("?", 1)[0].split("#", 1)[0].strip("/")
        row = db.ds_get_config_by_token(token)
        if row is not None and row["subscription_url"]:
            return row["subscription_url"]
    except Exception:
        pass
    return link


# ---------------------------------------------------------------------------
# برنامه‌ها: ادغام فهرست پیش‌فرض + شخصی‌سازی ادمین
# ---------------------------------------------------------------------------
def _pairs(raw: str) -> set:
    out = set()
    for part in (raw or "").replace("\n", ",").split(","):
        part = part.strip()
        if ":" in part:
            plat, name = part.split(":", 1)
            out.add((plat.strip().lower(), name.strip().lower()))
    return out


def parse_custom_apps(raw: str):
    """هر خط: platform|name|description|add_prefix|download_url — خروجی (apps, errors)."""
    apps, errors = [], []
    for i, line in enumerate((raw or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            errors.append(f"خط {i}: باید ۵ بخش با | جدا شده باشد")
            continue
        plat, name, desc, add, dl = parts[0].lower(), parts[1], parts[2], parts[3], parts[4]
        if plat not in PLATFORMS:
            errors.append(f"خط {i}: سیستم‌عامل نامعتبر ({plat})")
            continue
        if not name or len(name) > 40:
            errors.append(f"خط {i}: نام برنامه خالی یا طولانی است")
            continue
        if add in ("", "-"):
            add = ""
        elif not _SCHEME_RE.match(add) or add.lower().startswith(_BAD_SCHEMES):
            errors.append(f"خط {i}: پیشوند افزودن باید یک scheme اختصاصی مثل myapp://add?url= باشد")
            continue
        if dl in ("", "-"):
            dl = ""
        elif not dl.lower().startswith(("http://", "https://")):
            errors.append(f"خط {i}: لینک دانلود باید با http یا https شروع شود")
            continue
        if not add and not dl:
            errors.append(f"خط {i}: حداقل یکی از لینک افزودن یا دانلود لازم است")
            continue
        app = {"n": name, "d": desc[:160], "custom": 1}
        if add:
            app["add"] = add
        if dl:
            app["dl"] = dl
        apps.append((plat, app))
    return apps, errors


def resolve_apps(settings: Dict[str, str]) -> Dict[str, List[dict]]:
    hidden = _pairs(settings.get("dsub_apps_hidden", ""))
    rec = {}
    for plat, name in _pairs(settings.get("dsub_apps_rec", "")):
        rec[plat] = name
    custom, _ = parse_custom_apps(settings.get("dsub_custom_apps", ""))
    out: Dict[str, List[dict]] = {}
    for plat in PLATFORMS:
        items = [dict(a) for a in BUILTIN_APPS[plat]]
        items += [dict(a) for p, a in custom if p == plat]
        items = [a for a in items if (plat, a["n"].lower()) not in hidden]
        if plat in rec and any(a["n"].lower() == rec[plat] for a in items):
            for a in items:
                a["rec"] = 1 if a["n"].lower() == rec[plat] else 0
        items.sort(key=lambda a: 0 if a.get("rec") else 1)  # پایدار: ترتیب بقیه حفظ می‌شود
        out[plat] = items
    return out


def all_app_names(settings: Dict[str, str], platform: str) -> List[str]:
    """نام همه‌ی برنامه‌های یک سیستم‌عامل (مخفی‌شده‌ها هم) — برای صفحه‌ی مدیریت در بات."""
    custom, _ = parse_custom_apps(settings.get("dsub_custom_apps", ""))
    names = [a["n"] for a in BUILTIN_APPS[platform]] + [a["n"] for p, a in custom if p == platform]
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def parse_faq(raw: str) -> List[tuple]:
    items = []
    for line in (raw or "").splitlines():
        if "|" in line:
            q, a = line.split("|", 1)
            q, a = q.strip(), a.strip()
            if q and a:
                items.append((q[:120], a[:500]))
    return items


def resolve_faq(settings: Dict[str, str]) -> List[tuple]:
    return parse_faq(settings.get("dsub_faq", "")) or list(DEFAULT_FAQ)


# ---------------------------------------------------------------------------
# تحلیل پاسخ پنل
# ---------------------------------------------------------------------------
CONFIG_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "ssr://", "hysteria://", "hysteria2://", "hy2://", "tuic://", "ssh://")
_CONFIG_URI_RE = re.compile(r"(?:vmess|vless|trojan|hysteria2|hy2|hysteria|tuic|ssr|ss)://[^\s\"'<>]+")


def parse_userinfo(value: Optional[str]) -> dict:
    """هدر subscription-userinfo → {upload, download, total, expire}؛ مقدارهای نامعتبر نادیده گرفته می‌شوند."""
    out: dict = {}
    for part in (value or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip().lower(), v.strip()
        if k in ("upload", "download", "total", "expire"):
            try:
                out[k] = int(float(v))
            except ValueError:
                pass
    return out


def format_userinfo(info: dict) -> str:
    return "; ".join(f"{k}={int(info.get(k) or 0)}" for k in ("upload", "download", "total", "expire") if k in info)


def _b64_decode_text(value: str) -> str:
    try:
        padded = value.strip().replace("-", "+").replace("_", "/")
        padded += "=" * (-len(padded) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return value
    return decoded if decoded and "://" in decoded else value


class Body:
    """محتوای ساب پنل: kind='uris' (لیست لینک، ساده یا base64) یا 'other' (Clash/JSON/...)."""

    __slots__ = ("kind", "was_b64", "text", "uris")

    def __init__(self, kind: str, was_b64: bool, text: str, uris: List[str]):
        self.kind, self.was_b64, self.text, self.uris = kind, was_b64, text, uris


def parse_body(raw: bytes) -> Body:
    text = raw.decode("utf-8", errors="ignore").strip()
    if not text:
        return Body("other", False, "", [])
    head = text.lstrip()[:1]
    if head in ("{", "[") or "proxies:" in text[:4000]:
        return Body("other", False, text, [])
    decoded = _b64_decode_text(text)
    was_b64 = decoded != text
    lines = [ln.strip() for ln in decoded.splitlines() if ln.strip()]
    uris = [ln for ln in lines if ln.lower().startswith(CONFIG_SCHEMES)]
    if uris:
        return Body("uris", was_b64, decoded, uris)
    uris = [m.group(0) for m in _CONFIG_URI_RE.finditer(decoded)]
    return Body("other", was_b64, decoded, uris)


def extract_uris(raw: bytes) -> List[str]:
    """کانفیگ‌های تکی داخل ساب؛ برای کانفیگ کامل Xray-JSON از ماژول sub_info استفاده می‌شود."""
    body = parse_body(raw)
    if body.uris:
        return body.uris
    try:  # فرمت JSON کامل Xray فقط وقتی لازم است و ماژول در دسترس است
        from sub_info import _full_json_configs_to_uris
        return _full_json_configs_to_uris(body.text) or []
    except Exception:
        return []


def quota_info_for_config(db, config_id: int, any_status: bool = False) -> Optional[dict]:
    """Return subscription-userinfo compatible values from the shared VPN+SSH pool.

    A panel may report unlimited quota for the VPN half while the product is sold
    with a shared quota. The pool is authoritative for both the web page and client
    subscription headers, so the bot and subscription link show the same limits.
    """
    try:
        pool = db.quota_pool_for_custom_config(int(config_id))
        if not pool or (not any_status and str(pool.get("status") or "active") != "active"):
            return None
        usage = db.get_quota_usage(int(pool["id"]))
        if not usage:
            return None
        expire = 0
        raw_expire = pool.get("expires_at")
        if raw_expire:
            try:
                parsed = datetime.fromisoformat(str(raw_expire).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                expire = int(parsed.timestamp())
            except (TypeError, ValueError, OverflowError):
                expire = 0
        info = {
            "upload": int(usage.get("used_bytes") or 0),
            "download": 0,
            "total": int(usage.get("limit_bytes") or 0),
        }
        if expire:
            info["expire"] = expire
        return info
    except Exception:
        return None


def ssh_uris_for_config(db, config_id, cc=None) -> List[str]:
    """لینک‌های ssh:// حساب‌های فعالِ متصل به این سرویس؛ برای افزودن داخل ساب اختصاصی."""
    try:
        rows = db.ssh_accounts_for_config(int(config_id))
    except Exception:
        return []
    if not rows:
        return []
    from ssh_credentials import decrypt_credential
    out = []
    for n, row in enumerate(rows, start=1):
        try:
            password = decrypt_credential(row.get("credential_enc"))
        except Exception:
            continue
        remark = str(row.get("node_name") or "").strip() or "SSH " + str(row.get("username") or "")
        # مثل بقیه کانفیگ‌ها: نام نود + نام کاربری سرویس
        svc = str(_row(cc, "username") or _row(cc, "display_name") or "").strip() if cc is not None else ""
        if svc and svc not in remark:
            remark += " " + svc
        if len(rows) > 1:
            remark += f" {n}"
        import ssh_hosts
        for ep in ssh_hosts.endpoints(row, "ssh", row.get("host"), int(row.get("port") or 22)):
            try:
                from ssh_uri import build_ssh_uri
                out.append(build_ssh_uri(row.get("username"), password, ep["address"], ep["port"],
                                         remark + (f" {ep['remark']}" if ep["remark"] else "")))
            except (TypeError, ValueError):
                continue
    return out


def ovpn_files_for_config(db, config_id, cc=None) -> List[dict]:
    """فایل‌های .ovpn حساب‌های فعالِ OpenVPN متصل به این سرویس؛ برای دانلود از لینک ساب اختصاصی."""
    try:
        rows = db.ssh_accounts_for_config(int(config_id), protocol="openvpn")
    except Exception:
        return []
    if not rows:
        return []
    from ssh_credentials import decrypt_credential
    svc = str(_row(cc, "username") or _row(cc, "display_name") or "").strip() if cc is not None else ""
    out = []
    for row in rows:
        try:
            profile = decrypt_credential(row.get("credential_enc"))
        except Exception:
            continue
        if "<ca>" not in profile or "<key>" not in profile:
            continue
        username = re.sub(r"[^A-Za-z0-9_.-]", "", str(row.get("username") or "")) or "openvpn"
        remark = str(row.get("node_name") or "").strip() or "OpenVPN"
        if svc and svc not in remark:
            remark += " " + svc
        import ssh_hosts
        eps = ssh_hosts.endpoints(row, "openvpn", row.get("host"), int(row.get("port") or 1194))
        for pos, ep in enumerate(eps, start=1):
            tag = f" {ep['remark']}" if ep["remark"] else (f" {pos}" if len(eps) > 1 else "")
            out.append({"index": len(out) + 1, "remark": remark + tag + " (OpenVPN)",
                        "filename": f"{username}{'-' + str(pos) if len(eps) > 1 else ''}.ovpn",
                        "profile": ssh_hosts.rewrite_ovpn_profile(profile, ep["address"], ep["port"])})
    return out


def wg_files_for_config(db, config_id, cc=None) -> List[dict]:
    """فایل‌های .conf حساب‌های فعالِ WireGuard متصل به این سرویس؛ برای دانلود از لینک ساب اختصاصی."""
    try:
        rows = db.ssh_accounts_for_config(int(config_id), protocol="wireguard")
    except Exception:
        return []
    if not rows:
        return []
    from ssh_credentials import decrypt_credential
    svc = str(_row(cc, "username") or _row(cc, "display_name") or "").strip() if cc is not None else ""
    out = []
    for row in rows:
        try:
            profile = decrypt_credential(row.get("credential_enc"))
        except Exception:
            continue
        if "[Interface]" not in profile or "PrivateKey" not in profile:
            continue
        username = re.sub(r"[^A-Za-z0-9_.-]", "", str(row.get("username") or "")) or "wireguard"
        remark = str(row.get("node_name") or "").strip() or "WireGuard"
        if svc and svc not in remark:
            remark += " " + svc
        import ssh_hosts
        eps = ssh_hosts.endpoints(row, "wireguard", row.get("host"), int(row.get("port") or 51820))
        for pos, ep in enumerate(eps, start=1):
            tag = f" {ep['remark']}" if ep["remark"] else (f" {pos}" if len(eps) > 1 else "")
            out.append({"index": len(out) + 1, "remark": remark + tag + " (WireGuard)",
                        "filename": f"{username}{'-' + str(pos) if len(eps) > 1 else ''}.conf",
                        "profile": ssh_hosts.rewrite_wg_profile(profile, ep["address"], ep["port"])})
    return out


def encode_uris(uris_text: str, was_b64: bool) -> bytes:
    data = uris_text.encode("utf-8")
    return base64.b64encode(data) if was_b64 else data


def merge_extra_uris(up_body: bytes, extra_uris: List[str]) -> Optional[bytes]:
    """لینک‌های پنل‌های اضافه/SSH را به بدنه‌ی ساب اصلی اضافه می‌کند؛ اگر فرمت قابل ادغام نباشد None."""
    raw = up_body or b""
    if not raw.strip():
        return encode_uris("\n".join(extra_uris), True)
    body = parse_body(raw)
    if body.kind == "uris":
        return encode_uris(body.text.rstrip("\n") + "\n" + "\n".join(extra_uris), body.was_b64)
    primary = extract_uris(raw)
    if not primary:
        return None
    return encode_uris("\n".join(list(primary) + list(extra_uris)), True)


def uri_remark(uri: str) -> str:
    try:
        if uri.lower().startswith("vmess://"):
            payload = uri[8:].split("#", 1)[0]
            padded = payload + "=" * (-len(payload) % 4)
            obj = json.loads(base64.b64decode(padded.replace("-", "+").replace("_", "/")).decode("utf-8", "ignore"))
            return str(obj.get("ps") or "")
        if "#" in uri:
            return urllib.parse.unquote(uri.split("#", 1)[1])
    except Exception:
        pass
    return ""


_FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def uri_flag(remark: str) -> str:
    m = _FLAG_RE.search(remark or "")
    return m.group(0) if m else "🌐"


def uri_protocol(uri: str) -> str:
    scheme = uri.split("://", 1)[0].lower()
    return {"hysteria2": "HY2", "hy2": "HY2", "ss": "SS", "ssr": "SSR"}.get(scheme, scheme.upper())


def info_uri(remark: str) -> str:
    """کانفیگ نمایشی بی‌اثر: فقط برای نشان دادن یک پیام داخل لیست کانفیگ‌های اپ."""
    return ("vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1"
            "?encryption=none&security=none&type=tcp#" + urllib.parse.quote(remark, safe=""))


# ---------------------------------------------------------------------------
# زمان، وضعیت سرویس و قالب‌ها
# ---------------------------------------------------------------------------
def parse_dt(value) -> Optional[int]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _row(cc, key, default=None):
    try:
        return cc[key] if key in cc.keys() else default
    except AttributeError:
        return cc.get(key, default)


def service_name(cc) -> str:
    return str(_row(cc, "display_name") or _row(cc, "username") or "")


def compute_state(cc, info: dict, now: Optional[int] = None) -> str:
    """'active' | 'expired' | 'limited' | 'disabled'"""
    now = now or int(time.time())
    if int(_row(cc, "enabled", 1) or 0) == 0:
        return "disabled"
    status = str(_row(cc, "status", "active") or "active").lower()
    if status in ("cancelled", "disabled", "deleted"):
        return "disabled"
    if status == "expired":
        return "expired"
    expire = info.get("expire") or parse_dt(_row(cc, "expires_at"))
    if expire and expire < now:
        return "expired"
    total = info.get("total") or 0
    used = (info.get("upload") or 0) + (info.get("download") or 0)
    if total > 0 and used >= total:
        return "limited"
    return "active"


def fmt_gb(value_bytes: float) -> str:
    gb = value_bytes / GB
    if gb >= 100:
        return f"{gb:.0f} GB"
    if gb >= 1:
        return f"{gb:.2f}".rstrip("0").rstrip(".") + " GB"
    return f"{value_bytes / 1024 ** 2:.0f} MB"


def days_left(info: dict, cc, now: Optional[int] = None) -> Optional[int]:
    now = now or int(time.time())
    expire = info.get("expire") or parse_dt(_row(cc, "expires_at"))
    if not expire:
        return None
    return max(0, -(-(expire - now) // 86400))


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_template(tpl: str, **values) -> str:
    try:
        return tpl.format_map(_Safe(**{k: str(v) for k, v in values.items()}))
    except (ValueError, IndexError, KeyError):
        return tpl


def info_line_text(settings: Dict[str, str], info: dict, cc, now: Optional[int] = None) -> str:
    total = info.get("total") or 0
    used = (info.get("upload") or 0) + (info.get("download") or 0)
    left = days_left(info, cc, now)
    return render_template(
        settings.get("dsub_info_line_text") or DSUB_DEFAULTS["dsub_info_line_text"],
        volume=fmt_gb(max(total - used, 0)) if total else "نامحدود",
        used=fmt_gb(used), total=fmt_gb(total) if total else "نامحدود",
        days=f"{left} روز" if left is not None else "نامحدود",
    )[:120]


def b64_header(text: str) -> str:
    return "base64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# ساخت پاسخ برای اپ‌ها (کلاینت‌های VPN)
# ---------------------------------------------------------------------------
class ClientReply:
    __slots__ = ("status", "headers", "body", "state")

    def __init__(self, status, headers, body, state):
        self.status, self.headers, self.body, self.state = status, headers, body, state


_HTML_HEAD_RE = re.compile(rb"^\s*(<!doctype\s+html|<html|<head|<body|<\?xml)", re.I)


def looks_like_html(headers: Dict[str, str], body: bytes) -> bool:
    """پاسخ HTML/صفحه‌ی خطا (کلودفلر، صفحه‌ی وب پنل، ...) به‌جای کانفیگ؛ اپ‌ها این را «Unknown content type» می‌گیرند."""
    ctype = ((headers or {}).get("content-type") or "").lower()
    if "text/html" in ctype or "application/xhtml" in ctype:
        return True
    return bool(_HTML_HEAD_RE.match((body or b"")[:512]))


_PASS_HEADERS = ("subscription-userinfo", "content-disposition", "routing", "profile-web-page-url",
                 "support-url", "announce", "profile-title", "profile-update-interval")


def compose_client_reply(up_status: Optional[int], up_headers: Dict[str, str], up_body: bytes,
                         cc, settings: Dict[str, str], brand: str, page_url: str,
                         now: Optional[int] = None, extra_uris: Optional[List[str]] = None) -> Optional[ClientReply]:
    """پاسخ نهایی به اپ. None یعنی «پنل پاسخ معتبر نداد و جایگزینی هم مجاز نیست» (فراخوان خطا می‌دهد)."""
    now = now or int(time.time())
    up_headers = {k.lower(): v for k, v in (up_headers or {}).items()}
    ok = up_status == 200 and bool(up_body)
    if ok and looks_like_html(up_headers, up_body):
        ok = False  # پنل مبدأ HTML داده، نه کانفیگ → مثل «پنل جواب نداد» رفتار می‌کنیم
    info = parse_userinfo(up_headers.get("subscription-userinfo")) if ok else {}
    state = compute_state(cc, info, now)
    body = parse_body(up_body) if ok else None

    placeholder_on = settings.get("dsub_expired_placeholder") == "1"
    headers: Dict[str, str] = {"cache-control": "no-store"}
    if ok:
        for k in _PASS_HEADERS:
            if up_headers.get(k):
                headers[k] = up_headers[k]

    def finish(payload: bytes, ctype: str) -> ClientReply:
        headers["content-type"] = ctype
        title = render_template(
            settings.get("dsub_profile_title") or "", name=service_name(cc), user=_row(cc, "username", ""), brand=brand
        ).strip()
        if title:
            headers["profile-title"] = b64_header(title[:80])
        try:
            interval = int(settings.get("dsub_update_interval") or 0)
        except ValueError:
            interval = 0
        if interval > 0:
            headers["profile-update-interval"] = str(interval)
        if (settings.get("dsub_support_url") or "").strip():
            headers["support-url"] = urllib.parse.quote(settings["dsub_support_url"].strip(), safe=":/?#[]@!$&'()*+,;=%-._~")
        if page_url and settings.get("dsub_web_page") == "1":
            headers["profile-web-page-url"] = page_url
        if (settings.get("dsub_notice") or "").strip():
            headers["announce"] = b64_header(settings["dsub_notice"].strip()[:200])
        return ClientReply(200, headers, payload, state)

    # سرویس تمام‌شده/غیرفعال: کانفیگ نمایشی (فقط وقتی اپ فرمت لینک می‌فهمد یا پنل اصلاً جواب نداده)
    if state != "active" and placeholder_on and (body is None or body.kind == "uris"):
        text = settings.get("dsub_limited_text") if state == "limited" else settings.get("dsub_expired_text")
        text = (text or DSUB_DEFAULTS["dsub_expired_text"]).strip()
        raw = info_uri(text)
        return finish(base64.b64encode(raw.encode("utf-8")), "text/plain; charset=utf-8")

    if body is None:
        if extra_uris:
            return finish(merge_extra_uris(b"", extra_uris), "text/plain; charset=utf-8")
        return None

    if body.kind != "uris" and extra_uris:
        merged = merge_extra_uris(up_body, extra_uris)
        if merged is not None:
            return finish(merged, "text/plain; charset=utf-8")

    if body.kind == "uris":
        out_text = body.text
        if extra_uris:
            out_text = out_text.rstrip("\n") + "\n" + "\n".join(extra_uris)
        if settings.get("dsub_info_line") == "1" and state == "active":
            out_text = info_uri(info_line_text(settings, info, cc, now)) + "\n" + out_text
        return finish(encode_uris(out_text, body.was_b64), "text/plain; charset=utf-8")

    ctype = up_headers.get("content-type") or "text/plain; charset=utf-8"
    if "html" in ctype.lower():
        ctype = "text/plain; charset=utf-8"
    return finish(up_body, ctype)


def merge_smart(parts: List[tuple]) -> tuple:
    """parts: [(status, headers, body)] پاسخ چند پنل → (body_bytes, userinfo_header|None, تعداد کانفیگ)؛
    لینک‌های تکراری حذف می‌شوند و مصرف/حجم همه‌ی پنل‌ها جمع می‌شود."""
    seen, merged = set(), []
    up = down = total = 0
    unlimited, expire = False, None
    any_info = False
    for status, headers, raw in parts:
        if status != 200 or not raw:
            continue
        for u in parse_body(raw).uris:
            if u not in seen:
                seen.add(u)
                merged.append(u)
        info = parse_userinfo({k.lower(): v for k, v in (headers or {}).items()}.get("subscription-userinfo"))
        if info:
            any_info = True
            up += info.get("upload", 0)
            down += info.get("download", 0)
            if info.get("total"):
                total += info["total"]
            else:
                unlimited = True
            if info.get("expire"):
                expire = info["expire"] if expire is None else min(expire, info["expire"])
    body = base64.b64encode("\n".join(merged).encode("utf-8"))
    header = None
    if any_info:
        data = {"upload": up, "download": down, "total": 0 if unlimited else total}
        if expire:
            data["expire"] = expire
        header = format_userinfo(data)
    return body, header, len(merged)


# ---------------------------------------------------------------------------
# تشخیص مرورگر از اپ
# ---------------------------------------------------------------------------
_CLIENT_UA = re.compile(
    r"v2ray|xray|clash|mihomo|stash|sing-?box|hiddify|streisand|happ|v2box|shadowrocket|karing|neko|flclash|foxray|"
    r"npv|quantumult|surge|loon|hysteria|tuic|cfnetwork|okhttp|dart|curl|wget|python|go-http|axios|libcurl|"
    r"exclave|husi|matsuri|kitsunebi|sagernet|v2rayu|v2rayx|verge|pharos|potatso|rocket|fair|anx|oneclick|"
    r"v2raytun|incy|nekobox|nekoray|v2rayn|v2raya|koala|liberty|napsternet|mahsa|prizrak|sfa/|sfi/|sfm/|"
    r"clientapp|vpn|proxy|subscription|sub-?client",
    re.I,
)
# مرورگر واقعی: Mozilla + موتور رندر (WebView/اپ‌های مبتنی بر HTTP کتابخانه‌ای معمولاً اینها را ندارند)
_BROWSER_UA = re.compile(r"Mozilla/\d.*(AppleWebKit|Gecko/|Trident/)", re.I)


def wants_page(user_agent: str, accept: str, query: dict) -> bool:
    if query.get("raw") == "1":
        return False
    if query.get("view") == "1":
        return True
    ua = user_agent or ""
    if _CLIENT_UA.search(ua):
        return False
    # مرورگر همیشه Accept را با text/html شروع می‌کند؛ اپ‌ها */* یا application/* می‌فرستند
    if not (accept or "").strip().lower().startswith("text/html"):
        return False
    return bool(_BROWSER_UA.search(ua))


# ---------------------------------------------------------------------------
# نمودار مصرف
# ---------------------------------------------------------------------------
def build_series(points: List[tuple], now: Optional[int] = None) -> Optional[dict]:
    """points: [(ts, used_bytes)] مرتب. خروجی {'d':[12], 'w':[7], 'm':[30]} به GB (None = داده‌ای ثبت نشده)،
    یا None اگر هیچ بازه‌ای قابل محاسبه نباشد."""
    now = now or int(time.time())
    if len(points) < 2:
        return None

    def used_at(t):
        best = None
        for ts, used in points:
            if ts <= t:
                best = used
            else:
                break
        return best

    def buckets(n, step):
        out = []
        for i in range(n):
            end = now - (n - 1 - i) * step
            a, b = used_at(end - step), used_at(end)
            if a is None or b is None:
                out.append(None)
            else:
                out.append(round((b if b < a else b - a) / GB, 3))  # b<a: شمارنده ریست شده (تمدید)
        return out

    series = {"d": buckets(12, 7200), "w": buckets(7, 86400), "m": buckets(30, 86400)}
    if all(v is None for arr in series.values() for v in arr):
        return None
    return series


# ---------------------------------------------------------------------------
# داده‌ی صفحه‌ی وب
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ورودی‌های نام‌کاربری/رمز: OpenConnect / L2TP / PPTP / IKEv2 (پنل W-UI)
# ---------------------------------------------------------------------------
VPN_KIND_LABELS = {"openconnect": "OpenConnect", "l2tp": "L2TP/IPsec", "pptp": "PPTP", "ikev2": "IKEv2"}
# فقط حالت‌هایی که با نام‌کاربری/رمز کار می‌کنند؛ حالت‌های گواهی فایل .p12 می‌خواهند که این صفحه نمی‌دهد
VPN_IKEV2_MODE_LABELS = {"mschapv2": "نام‌کاربری و رمز", "psk": "کلید (PSK)؛ همان رمز عبور"}
VPN_SECRETS = {"user": "username", "pass": "password", "psk": "psk"}
VPN_ITEMS_MAX = 20


def vpn_items_for_page(entries: Optional[List[dict]]) -> List[dict]:
    """نسخه‌ی بدون راز برای داخل صفحه: نام‌کاربری/رمز/PSK هرگز داخل HTML نمی‌آیند و با دکمه‌ی کپی جداگانه گرفته می‌شوند."""
    out = []
    for pos, e in enumerate((entries or [])[:VPN_ITEMS_MAX], start=1):
        kind = str(e.get("kind") or "")
        if kind not in VPN_KIND_LABELS:
            continue
        if kind == "ikev2" and not [m for m in e.get("modes") or [] if m in VPN_IKEV2_MODE_LABELS]:
            continue
        item = {
            "i": pos, "k": kind, "l": VPN_KIND_LABELS[kind],
            "n": " · ".join(x for x in (str(e.get("tunnel") or ""), str(e.get("device") or "")) if x) or VPN_KIND_LABELS[kind],
            "srv": str(e.get("address") or e.get("server") or ""),
            "port": int(e.get("own_port") or 0),
            "has": {"user": bool(e.get("username")), "pass": bool(e.get("password")), "psk": bool(e.get("psk"))},
            "weak": kind == "pptp" or bool(e.get("allow_plain")),
        }
        if kind == "l2tp":
            item["plain"] = bool(e.get("allow_plain"))
        elif kind == "ikev2":
            item["sid"] = str(e.get("server_id") or "")
            item["modes"] = [{"m": m, "t": VPN_IKEV2_MODE_LABELS[m]} for m in e.get("modes") or [] if m in VPN_IKEV2_MODE_LABELS]
            item["ca"] = bool(e.get("ca_cert"))
        elif kind == "openconnect":
            item["dtls"] = bool(e.get("dtls"))
        out.append(item)
    return out


def vpn_secret(entries: Optional[List[dict]], index: int, what: str) -> Optional[str]:
    """مقدار یک راز (user/pass/psk) برای ردیف شماره‌ی index (۱-پایه)؛ None اگر نبود."""
    key = VPN_SECRETS.get(what)
    items = (entries or [])[:VPN_ITEMS_MAX]
    if not key or not 1 <= int(index) <= len(items):
        return None
    value = items[int(index) - 1].get(key)
    return str(value) if value else None


def vpn_ca_file(entries: Optional[List[dict]], index: int) -> Optional[dict]:
    """فایل گواهی CA یک تونل IKEv2 (عمومی است؛ دستگاه برای اعتماد به سرور نصبش می‌کند)."""
    items = (entries or [])[:VPN_ITEMS_MAX]
    if not 1 <= int(index) <= len(items):
        return None
    e = items[int(index) - 1]
    pem = str(e.get("ca_cert") or "").strip()
    if e.get("kind") != "ikev2" or "BEGIN CERTIFICATE" not in pem:
        return None
    name = re.sub(r"[^A-Za-z0-9_.-]", "", str(e.get("tunnel") or "")) or "ikev2"
    return {"filename": f"{name}-ca.crt", "pem": pem + "\n"}


def build_page_data(cc, info: dict, uris: List[str], settings: Dict[str, str], brand: str,
                    sub_link: str, series: Optional[dict], now: Optional[int] = None,
                    ovpn: Optional[List[dict]] = None, wg: Optional[List[dict]] = None,
                    vpn: Optional[List[dict]] = None) -> dict:
    now = now or int(time.time())
    state = compute_state(cc, info, now)
    total = info.get("total") or 0
    used = (info.get("upload") or 0) + (info.get("download") or 0)
    expire = info.get("expire") or parse_dt(_row(cc, "expires_at"))
    left = days_left(info, cc, now)
    plan_days = int(_row(cc, "duration_days", 0) or 0) or None
    created = parse_dt(_row(cc, "created_at"))
    configs = []
    for uri in uris[:60]:
        remark = uri_remark(uri)
        configs.append({"n": remark or "config", "f": uri_flag(remark), "p": uri_protocol(uri), "u": uri})
    support = (settings.get("dsub_support_url") or "").strip()
    if support and not support.lower().startswith(("http://", "https://", "tg://")):
        support = ""
    logo = (settings.get("dsub_logo_url") or "").strip()
    if not logo.lower().startswith("https://"):
        logo = ""
    theme = settings.get("dsub_theme") or "auto"
    ovpn_items = [{"n": f["remark"], "f": f["filename"], "i": f["index"]} for f in (ovpn or [])[:20]]
    wg_items = [{"n": f["remark"], "f": f["filename"], "i": f["index"]} for f in (wg or [])[:20]]
    vpn_items = vpn_items_for_page(vpn)
    return {
        "user": service_name(cc), "brand": brand, "logo": logo,
        "state": state, "online": False,
        "used": round(used / GB, 2), "total": round(total / GB, 2) if total else None,
        "expire": expire, "daysLeft": left if expire else None, "planDays": plan_days,
        "created": created, "now": now,
        "notice": (settings.get("dsub_notice") or "").strip(),
        "support": support, "footer": (settings.get("dsub_footer_text") or "").strip(),
        "theme": theme if theme in THEMES else "auto",
        "style": settings.get("dsub_style", "minimal") if settings.get("dsub_style") in ("minimal", "modern", "glass", "cyberpunk", "classic") else "minimal",
        "accent": settings.get("dsub_accent_color", "#6366F1") if re.fullmatch(r"#[0-9a-fA-F]{6}", settings.get("dsub_accent_color", "")) else "#6366F1",
        "secondary": settings.get("dsub_secondary_color", "#06B6D4") if re.fullmatch(r"#[0-9a-fA-F]{6}", settings.get("dsub_secondary_color", "")) else "#06B6D4",
        "cardStyle": settings.get("dsub_card_style", "rounded") if settings.get("dsub_card_style") in ("rounded", "soft", "sharp") else "rounded",
        "density": settings.get("dsub_density", "comfortable") if settings.get("dsub_density") in ("comfortable", "compact") else "comfortable",
        "sub": sub_link,
        "show": {
            "configs": settings.get("dsub_show_configs") == "1" and bool(configs),
            "chart": settings.get("dsub_show_chart") == "1",
            "qr": settings.get("dsub_show_qr") == "1",
            "apps": settings.get("dsub_show_apps") == "1",
            "faq": settings.get("dsub_show_faq") == "1",
            "ovpn": bool(ovpn_items),
            "wg": bool(wg_items),
            "vpn": bool(vpn_items),
        },
        "configs": configs,
        "ovpn": ovpn_items,
        "wg": wg_items,
        "vpn": vpn_items,
        "apps": resolve_apps(settings),
        "faq": [list(x) for x in resolve_faq(settings)],
        "series": series,
    }


# ---------------------------------------------------------------------------
# قالب اختصاصی صفحه‌ی ساب
# ---------------------------------------------------------------------------
CUSTOM_TEMPLATE_MAX = 400_000  # بایت
_TPL_TOKEN_RE = re.compile(r"__(NONCE|TITLE|THEME|DATA)__")
_SCRIPT_NO_NONCE_RE = re.compile(r"<script\b(?![^>]*\bnonce\s*=)", re.I)


def validate_custom_template(text: str) -> Optional[str]:
    """None یعنی معتبر (یا خالی)؛ در غیر این‌صورت پیام خطا به فارسی."""
    text = text or ""
    if not text.strip():
        return None
    if len(text.encode("utf-8")) > CUSTOM_TEMPLATE_MAX:
        return "حجم قالب بیش از حد مجاز است (حداکثر ۴۰۰ کیلوبایت)."
    if "__DATA__" not in text:
        return "قالب باید شامل __DATA__ باشد؛ مثلاً const D=__DATA__; داخل تگ script."
    return None


def pick_template(settings: Dict[str, str]) -> Optional[str]:
    """اگر قالب اختصاصی روشن و معتبر بود متنش را می‌دهد، وگرنه None (= قالب پیش‌فرض)."""
    if (settings.get("dsub_custom_template_enabled") or "").strip() != "1":
        return None
    text = settings.get("dsub_custom_template") or ""
    if not text.strip() or validate_custom_template(text):
        return None
    return text


def render_page_html(template: str, data: dict, title: str, nonce: str) -> str:
    """جایگذاری __NONCE__ / __TITLE__ / __THEME__ / __DATA__ در یک گذر (مقادیر جایگزین‌شده دوباره اسکن نمی‌شوند).

    به هر تگ <script> که nonce ندارد خودکار nonce اضافه می‌شود تا سازنده‌ی قالب لازم نباشد حواسش به CSP باشد.
    """
    import html as html_lib
    theme = data.get("theme") if data.get("theme") in THEMES else "auto"
    values = {"NONCE": nonce, "TITLE": html_lib.escape(title), "THEME": theme, "DATA": json_for_script(data)}
    template = _SCRIPT_NO_NONCE_RE.sub('<script nonce="__NONCE__"', template)
    return _TPL_TOKEN_RE.sub(lambda m: values[m.group(1)], template)


def json_for_script(data) -> str:
    """JSON امن برای قرار دادن داخل تگ <script> (جلوگیری از بستن تگ/تزریق HTML)."""
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


# ---------------------------------------------------------------------------
# خط فرمان (manage.sh)
# ---------------------------------------------------------------------------
def _cli(argv: List[str]) -> int:
    if not argv or argv[0] not in ("enable", "disable", "status"):
        print("usage: python -m dedicated_sub enable|disable|status")
        return 2
    from config import DB_PATH, OWNER_ID
    from database import Database
    db = Database(DB_PATH)
    db.init_db(owner_id=OWNER_ID)
    if argv[0] == "enable":
        if not base_url(db):
            print("disabled")
            print("(no-domain)")
            return 1
        db.set_setting("dsub_enabled", "1")
    elif argv[0] == "disable":
        db.set_setting("dsub_enabled", "0")
    print("enabled" if flag(db, "dsub_enabled") else "disabled")
    print(base_url(db) or "(no-domain)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
