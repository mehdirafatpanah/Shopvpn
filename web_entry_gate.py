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


def base_path() -> str:
    """مسیر پایه‌ی پنل در مرورگر: «/<مسیر>/» وقتی گیت روشن است، وگرنه «/»."""
    enabled, slug = get_config()
    return f"/{slug}/" if enabled and slug else "/"


def is_document_navigation(headers) -> bool:
    """true یعنی مرورگر دارد یک صفحه (نه fetch/تصویر/اسکریپت) باز می‌کند."""
    mode = (headers.get("sec-fetch-mode") or "").lower()
    if mode:
        return mode == "navigate"
    return "text/html" in (headers.get("accept") or "").lower()


from gear_svg import gear_path as _gp

_GEARS = (
    f'<svg class="gears" viewBox="0 0 220 150" aria-hidden="true">'
    f'<defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6366f1"/><stop offset="1" stop-color="#06b6d4"/></linearGradient></defs>'
    f'<path class="gear g-a" fill="url(#g1)" fill-rule="evenodd" d="{_gp(78, 80, 56, 45, 12, 16)}"/>'
    f'<path class="gear g-b" fill="url(#g1)" fill-rule="evenodd" opacity=".85" d="{_gp(160, 46, 34, 27, 9, 10)}"/>'
    f'<path class="gear g-c" fill="url(#g1)" fill-rule="evenodd" opacity=".65" d="{_gp(168, 112, 22, 17, 8, 6)}"/>'
    f'</svg>'
)

ERROR_PAGE_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>به زودی</title>
<style>
  :root{--bg:#f4f6fb;--fg:#0f172a;--mut:#64748b;--card:#ffffffcc;--line:#e2e8f0;--a:#6366f1;--b:#06b6d4;--glow:#6366f133}
  @media (prefers-color-scheme:dark){:root{--bg:#0a0d18;--fg:#e8ecf8;--mut:#8b95b0;--card:#121830cc;--line:#232b48;--a:#818cf8;--b:#22d3ee;--glow:#818cf826}}
  *{box-sizing:border-box;margin:0}
  html,body{height:100%}
  body{font-family:Vazirmatn,Tahoma,"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--fg);
    display:grid;place-items:center;padding:20px}
  .bg{position:fixed;inset:0;overflow:hidden;z-index:0;pointer-events:none}
  .bg::before,.bg::after{content:"";position:absolute;width:46vmax;height:46vmax;border-radius:50%;filter:blur(90px);opacity:.55}
  .bg::before{background:var(--glow);top:-18vmax;right:-14vmax}
  .bg::after{background:#06b6d422;bottom:-20vmax;left:-14vmax}
  .grid{position:absolute;inset:0;opacity:.5;
    background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
    background-size:44px 44px;-webkit-mask-image:radial-gradient(circle at 50% 45%,#000 0,transparent 68%);mask-image:radial-gradient(circle at 50% 45%,#000 0,transparent 68%)}
  main{position:relative;z-index:1;width:min(460px,100%);text-align:center;background:var(--card);border:1px solid var(--line);
    border-radius:28px;padding:34px 28px 30px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    box-shadow:0 30px 80px -30px var(--glow);animation:in .6s cubic-bezier(.2,.8,.2,1) both}
  @keyframes in{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}
  .gears{width:min(260px,70%);height:auto;overflow:visible}
  .gear{transform-box:fill-box;transform-origin:center}
  .g-a{animation:cw 12s linear infinite}
  .g-b{animation:ccw 9s linear infinite}
  .g-c{animation:cw 6.5s linear infinite}
  @keyframes cw{to{transform:rotate(360deg)}}
  @keyframes ccw{to{transform:rotate(-360deg)}}
  h1{font-size:26px;font-weight:800;margin:8px 0 8px;background:linear-gradient(135deg,var(--a),var(--b));-webkit-background-clip:text;background-clip:text;color:transparent}
  p{color:var(--mut);font-size:14px;line-height:1.9}
  .tag{display:inline-flex;align-items:center;gap:8px;margin-top:20px;padding:8px 14px;border-radius:999px;
    border:1px dashed var(--line);color:var(--mut);font-size:12.5px}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--b);animation:pulse 2s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 #06b6d466}70%,100%{box-shadow:0 0 0 8px #06b6d400}}
  .en{margin-top:16px;font-size:12px;color:var(--mut);opacity:.8;direction:ltr}
  @media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style>
</head>
<body>
<div class="bg"><div class="grid"></div></div>
<main role="main">
  __GEARS__
  <h1>به زودی</h1>
  <p>در حال آماده‌سازی هستیم.<br>خیلی زود با امکانات تازه برمی‌گردیم.</p>
  <div class="tag"><span class="dot"></span>در حال راه‌اندازی</div>
  <div class="en">Coming soon</div>
</main>
</body>
</html>""".replace("__GEARS__", _GEARS)
