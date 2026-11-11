# -*- coding: utf-8 -*-
"""سرویس مستقل فروشگاه وب ShopVPN.

اجرا: uvicorn web_store.server:app --host 127.0.0.1 --port 8005
این سرویس دامنه، پورت و فرانت خودش را دارد و مینی‌اپ را باز نمی‌کند؛ فقط مسیرهای
لازم فروشگاه (ورود، سفارش، پرداخت، سرویس‌ها، تیکت) را از منطق مشترک سفارش بالا می‌آورد.
"""
import html as html_lib
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from asset_versioning import ApiNoStoreMiddleware, static_version
from i18n import normalize_language, reset_language, set_language
from miniapp import server as core
from web_store.routes import router as web_router

log = logging.getLogger("web_store")

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

ALLOWED_CORE_ROUTES = {
    ("/api/me", "GET"),
    ("/api/gateways", "GET"),
    ("/api/tier-quote", "GET"),
    ("/api/orders", "GET"),
    ("/api/orders", "POST"),
    ("/api/orders/{order_id}/crypto-invoice", "POST"),
    ("/api/orders/{order_id}/abangateway-invoice", "POST"),
    ("/api/orders/{order_id}/blupal-invoice", "POST"),
    ("/api/orders/{order_id}/noapay-invoice", "POST"),
    ("/api/orders/{order_id}/extra-invoice/{gateway}", "POST"),
    ("/api/orders/{order_id}/custom-invoice/{gateway_key}", "POST"),
    ("/api/orders/{order_id}/card-auto-invoice", "POST"),
    ("/api/orders/{order_id}/receipt", "POST"),
    ("/api/card-auto-invoice/{invoice_id}/status", "GET"),
    ("/api/tickets", "GET"),
    ("/api/tickets", "POST"),
    ("/api/tickets/{ticket_id}/messages", "GET"),
    ("/api/tickets/{ticket_id}/messages", "POST"),
    ("/api/tickets/{ticket_id}/close", "POST"),
    ("/api/sub-info", "GET"),
    ("/api/terms/accept", "POST"),
    ("/api/custom-configs/{custom_config_id}/renewal-full-plans", "GET"),
    ("/api/custom-configs/{custom_config_id}/renew-full", "POST"),
}

PAGE_META = {
    "fa": {
        "lang": "fa",
        "dir": "rtl",
        "title": "ShopVPN | خرید سریع سرویس VPN",
        "desc": "پلن را انتخاب کن، پرداخت کن و لینک اشتراک را همان لحظه بگیر. بدون نیاز به نصب برنامه‌ی تلگرام برای خرید.",
    },
    "en": {
        "lang": "en",
        "dir": "ltr",
        "title": "ShopVPN | Buy a VPN plan in a minute",
        "desc": "Pick a plan, pay, and get your subscription link right away. No Telegram app needed to buy.",
    },
}

# حالت‌های سه‌بعدی صفحه‌ی اصلی و فایل‌هایی که هر حالت لازم دارد (حالت خاموش هیچ اسکریپتی نمی‌گیرد).
SCENE_MODES = {
    "off": ([], []),
    "cinema": (["cinema.css"], ["hero-scene.js", "cinema.js"]),
    "particles": ([], ["hero-scene.js"]),
    "globe": ([], ["scene-extra.js"]),
    "network": ([], ["scene-extra.js"]),
    "tunnel": ([], ["scene-extra.js"]),
    "waves": ([], ["scene-extra.js"]),
}
DEFAULT_SCENE_MODE = "cinema"


def _scene_settings(request: Request) -> dict:
    db = core.main_db
    mode = (db.get_setting("web_3d_mode", DEFAULT_SCENE_MODE) or DEFAULT_SCENE_MODE).strip().lower()
    # پیش‌نمایش ادمین: ?preview=1&scene=globe فقط برای دیدن، چیزی ذخیره نمی‌کند.
    if request.query_params.get("preview") == "1":
        mode = (request.query_params.get("scene") or mode).strip().lower()
    if mode not in SCENE_MODES:
        mode = DEFAULT_SCENE_MODE
    return {
        "mode": mode,
        "mobile": "0" if db.get_setting("web_3d_mobile", "1") == "0" else "1",
        "lite": "0" if db.get_setting("web_3d_auto_lite", "1") == "0" else "1",
    }


LEGACY_HASH = {
    "faq.html": "#/faq",
    "connection-guide.html": "#/guide",
    "terms.html": "#/terms",
}


def _mount_core_routes(target: FastAPI) -> None:
    found = set()
    for route in core.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        hit = {(path, m) for m in methods} & ALLOWED_CORE_ROUTES
        if hit:
            target.router.routes.append(route)
            found |= hit
    missing = ALLOWED_CORE_ROUTES - found
    if missing:
        log.error("مسیرهای زیر در مینی‌اپ پیدا نشدند و در فروشگاه وب فعال نیستند: %s", sorted(missing))


app = FastAPI(title="ShopVPN Web Store", docs_url=None, redoc_url=None, openapi_url=None)


def _preview_ancestors() -> list:
    """Origins allowed to embed the preview: the admin panel and any extras from the env."""
    raw = [os.getenv("ADMIN_PANEL_URL", "")] + os.getenv("SHOPVPN_PREVIEW_ORIGINS", "").split(",")
    out = []
    for item in raw:
        parsed = urlparse((item or "").strip())
        if parsed.scheme in ("http", "https") and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in out:
                out.append(origin)
    return out


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    preview = request.url.path in ("/", "/en", "/en/") and request.query_params.get("preview") == "1"
    ancestors = "'none'"
    if preview:
        ancestors = " ".join(["'self'"] + _preview_ancestors())
    if not preview:
        response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://challenges.cloudflare.com; "
        "style-src 'self'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://challenges.cloudflare.com; "
        "frame-src https://challenges.cloudflare.com; "
        f"frame-ancestors {ancestors}; object-src 'none'; base-uri 'self'; form-action 'self'",
    )
    if request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip() == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.middleware("http")
async def _request_language(request: Request, call_next):
    language = normalize_language(request.headers.get("x-language") or request.headers.get("accept-language"))
    token = set_language(language)
    try:
        response = await call_next(request)
        response.headers["Content-Language"] = language
        return response
    finally:
        reset_language(token)


app.add_middleware(ApiNoStoreMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(web_router)
_mount_core_routes(app)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


def _render_index(lang: str, request: Request) -> HTMLResponse:
    meta = PAGE_META[lang]
    base = os.getenv("SHOPVPN_SEO_SITE_URL", "").strip().rstrip("/")
    if not base:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme
        host = request.headers.get("x-forwarded-host", "").split(",")[0].strip() or request.headers.get("host", "")
        base = f"{proto}://{host}".rstrip("/")
    canonical = base + ("/" if lang == "fa" else "/en/")
    page = INDEX_FILE.read_text(encoding="utf-8")
    asset_ver = static_version(str(STATIC_DIR / "assets"))
    values = {
        "LANG": meta["lang"],
        "DIR": meta["dir"],
        "TITLE": html_lib.escape(meta["title"]),
        "DESC": html_lib.escape(meta["desc"], quote=True),
        "CANON": html_lib.escape(canonical),
        "ALT_FA": html_lib.escape(base + "/"),
        "ALT_EN": html_lib.escape(base + "/en/"),
        "OG_IMAGE": html_lib.escape(base + "/assets/og-image.png"),
        "ASSET_VERSION": html_lib.escape(asset_ver),
    }
    try:
        scene = _scene_settings(request)
    except Exception:
        log.exception("خواندن تنظیم سه‌بعدی ناموفق بود؛ حالت پیش‌فرض")
        scene = {"mode": DEFAULT_SCENE_MODE, "mobile": "1", "lite": "1"}
    css_files, js_files = SCENE_MODES[scene["mode"]]
    ver = values["ASSET_VERSION"]
    values["SCENE_MODE"] = scene["mode"]
    values["SCENE_MOBILE"] = scene["mobile"]
    values["SCENE_LITE"] = scene["lite"]
    values["SCENE_STYLES"] = "\n".join(f'<link rel="stylesheet" href="/assets/{f}?v={ver}">' for f in css_files)
    values["SCENE_SCRIPTS"] = "\n".join(f'<script src="/assets/{f}?v={ver}" defer></script>' for f in js_files)
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index_fa(request: Request):
    return _render_index("fa", request)


@app.get("/en", include_in_schema=False)
def index_en_noslash(request: Request):
    return RedirectResponse("/en/" + ("?" + request.url.query if request.url.query else ""), status_code=308)


@app.get("/en/", include_in_schema=False)
def index_en(request: Request):
    return _render_index("en", request)


@app.get("/store", include_in_schema=False)
@app.get("/store/", include_in_schema=False)
@app.get("/store/{path:path}", include_in_schema=False)
def legacy_store(request: Request, path: str = ""):
    english = path == "en" or path.startswith("en/")
    leaf = path.split("/")[-1] if path else ""
    target = "/en/" if english else "/"
    query = urlencode({k: v for k, v in request.query_params.items() if k == "preview"})
    return RedirectResponse(target + (("?" + query) if query else "") + LEGACY_HASH.get(leaf, ""), status_code=301)


app.mount("/assets", core.NoCacheStaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")
