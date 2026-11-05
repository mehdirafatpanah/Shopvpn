# -*- coding: utf-8 -*-
"""
سرور «ساب اختصاصی» ShopVPN.

اجرا (manage.sh این را به‌صورت سرویس systemd می‌سازد):
    uvicorn sub_server.server:app --host 127.0.0.1 --port 8004

مسیرها:
    GET /s/{token}              اپ VPN → ساب (با هدرها/کانفیگ نمایشی/خط اول)؛ مرورگر → صفحه‌ی وب
    GET /s/{token}/qr.png       کیوآر لینک ساب (یا ?i=N برای کانفیگ شماره‌ی N)
    GET /s/{token}/ovpn/{n}     دانلود فایل OpenVPN شماره‌ی n (.ovpn) برای سرویس‌های دارای OpenVPN
    GET /s/{token}/wg/{n}       دانلود فایل WireGuard شماره‌ی n (.conf) برای سرویس‌های دارای WireGuard
    GET /sub/smart/{token}      اشتراک هوشمند (ادغام چند سرویس/پنل در یک لینک)
    GET /healthz                سلامت سرویس

همه‌ی تنظیمات (روشن/خاموش، ظاهر صفحه، هدرها، برنامه‌ها و...) از داخل ادمین بات در جدول settings
ذخیره می‌شوند و همین‌جا با کش کوتاه (۸ ثانیه) خوانده می‌شوند، پس نیازی به ری‌استارت نیست.

وقتی قابلیت «خاموش» باشد، لینک‌هایی که قبلاً به کاربران داده شده کار می‌کنند ولی سرور فقط
پاسخ پنل را بدون هیچ تغییری عبور می‌دهد (بدون صفحه‌ی وب و بدون دستکاری) تا کسی قطع نشود.
"""

import asyncio
import json
import logging
import os
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

import dedicated_sub as ds
import panel_resync
from panel_providers import get_provider
from config import DB_PATH, OWNER_ID
from database import Database

log = logging.getLogger("sub_server")

db = Database(DB_PATH)

PAGE_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sub_page.html")
PAGE_UA = "v2rayNG/1.8.29"          # برای گرفتن فرمت لینک‌های تکی که صفحه‌ی وب نشان می‌دهد
MAX_BODY = 5 * 1024 * 1024
STALE_MAX_AGE = 3600                # اگر پنل قطع بود، تا یک ساعت آخرین پاسخ سالم داده می‌شود
VERIFY_TLS = os.getenv("DEDICATED_SUB_VERIFY_TLS", "1") != "0"

_session = None  # aiohttp.ClientSession (در lifespan ساخته می‌شود)


# ---------------------------------------------------------------------------
# محدودکننده‌ی نرخ (حافظه‌ای، به‌ازای IP)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self._hits: Dict[str, deque] = {}

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self._hits) > 20000:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] <= window}
        return True


limiter = RateLimiter()
RATE_OK = 90        # درخواست معتبر در دقیقه برای هر IP
RATE_MISS = 12      # توکن نامعتبر در دقیقه برای هر IP (جلوگیری از حدس زدن توکن)


def client_ip(request: Request) -> str:
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1"):  # پشت nginx
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return fwd or request.headers.get("x-real-ip", "") or host
    return host


# ---------------------------------------------------------------------------
# دریافت ساب از پنل (با کش کوتاه، هم‌زمانی یکتا و پاسخ قدیمی در زمان قطعی)
# ---------------------------------------------------------------------------
class Upstream:
    __slots__ = ("status", "headers", "body", "fresh", "stale")

    def __init__(self, status, headers, body, fresh=True, stale=False):
        self.status, self.headers, self.body, self.fresh, self.stale = status, headers, body, fresh, stale


async def _http_get(url: str, ua: str) -> Tuple[int, Dict[str, str], bytes]:
    async with _session.get(url, headers={"User-Agent": ua[:200] or PAGE_UA, "Accept": "*/*"}) as resp:
        body = await resp.content.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError("upstream response too large")
        return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body


class UpstreamCache:
    def __init__(self, max_items: int = 1500):
        self._data: Dict[tuple, tuple] = {}
        self._locks: Dict[tuple, asyncio.Lock] = {}
        self._max = max_items

    @staticmethod
    def _ua_key(ua: str) -> str:
        return (ua or "").split("/")[0].strip().lower()[:40]

    async def get(self, url: str, ua: str, ttl: float, force: bool = False,
                  fetcher=None) -> Upstream:
        fetcher = fetcher or _http_get
        key = (url, self._ua_key(ua))
        now = time.monotonic()
        ent = self._data.get(key)
        if ent and not force and now - ent[0] < ttl:
            return Upstream(*ent[1], fresh=False)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            ent = self._data.get(key)
            if ent and not force and time.monotonic() - ent[0] < ttl:
                return Upstream(*ent[1], fresh=False)
            try:
                status, headers, body = await fetcher(url, ua)
            except Exception as exc:
                name = type(exc).__name__
                if "Certificate" in name or "SSL" in name:
                    log.warning("upstream TLS verification failed (%s); set DEDICATED_SUB_VERIFY_TLS=0 in .env for self-signed panels", name)
                else:
                    log.warning("upstream fetch failed: %s", name)
                if ent and time.monotonic() - ent[0] < STALE_MAX_AGE:
                    return Upstream(*ent[1], fresh=False, stale=True)
                raise
            if status == 200 and body:
                if len(self._data) >= self._max:
                    for old in sorted(self._data, key=lambda k: self._data[k][0])[: self._max // 4]:
                        self._data.pop(old, None)
                        self._locks.pop(old, None)
                self._data[key] = (time.monotonic(), (status, headers, body))
            elif status >= 500 and ent and time.monotonic() - ent[0] < STALE_MAX_AGE:
                return Upstream(*ent[1], fresh=False, stale=True)
            return Upstream(status, headers, body, fresh=True)


cache = UpstreamCache()


# ---------------------------------------------------------------------------
# پاسخ‌ها
# ---------------------------------------------------------------------------
def _clean_headers(headers: Dict[str, str]) -> Dict[str, str]:
    out = {}
    for k, v in headers.items():
        v = str(v).replace("\r", " ").replace("\n", " ")
        out[k] = v.encode("latin-1", "ignore").decode("latin-1")
    return out


def _raw(status: int, headers: Dict[str, str], ctype: str, body: bytes) -> Response:
    resp = Response(content=body, status_code=status, headers=headers)
    resp.headers["content-type"] = ctype
    resp.headers["x-content-type-options"] = "nosniff"
    resp.headers["x-robots-tag"] = "noindex, nofollow"
    return resp


def _not_found() -> Response:
    return PlainTextResponse("Not found", status_code=404, headers={"cache-control": "no-store"})


_page_template: Optional[str] = None


def _load_template() -> str:
    global _page_template
    if _page_template is None:
        with open(PAGE_TEMPLATE_PATH, "r", encoding="utf-8") as fh:
            _page_template = fh.read()
    return _page_template


def render_page(data: dict, title: str, settings: Optional[Dict[str, str]] = None) -> Response:
    nonce = secrets.token_urlsafe(12)
    html = None
    custom = ds.pick_template(settings or {})
    if custom:
        try:
            html = ds.render_page_html(custom, data, title, nonce)
        except Exception:
            log.exception("custom sub page template failed; falling back to default")
    if html is None:
        html = ds.render_page_html(_load_template(), data, title, nonce)
    csp = ("default-src 'none'; script-src 'nonce-%s'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
           "font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; "
           "frame-ancestors 'none'; base-uri 'none'; form-action 'none'" % nonce)
    return HTMLResponse(html, headers={
        "content-security-policy": csp, "cache-control": "no-store", "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff", "x-robots-tag": "noindex, nofollow",
    })


def _brand(settings: Dict[str, str]) -> str:
    return (settings.get("dsub_brand") or db.get_setting("brand_name", "") or db.get_setting("shop_name", "")
            or "ShopVPN").strip()


def _query(request: Request) -> Dict[str, str]:
    return {k: v for k, v in request.query_params.items()}


def _forward_query(url: str, query: Dict[str, str]) -> str:
    extra = {k: v for k, v in query.items() if k not in ("raw", "view")}
    if not extra:
        return url
    from urllib.parse import urlencode
    return url + ("&" if "?" in url else "?") + urlencode(extra)


async def _linked_panel_uris(cc, query: Dict[str, str], ua: str, ttl: int) -> List[str]:
    """کانفیگ‌های پنل‌های اضافه‌ی همین سرویس (محصول چندپنلی)؛ فقط وقتی ساب اختصاصی روشن است."""
    try:
        links = await asyncio.to_thread(db.panel_links_for_config, cc["id"])
    except Exception:
        return []
    if not links:
        return []

    async def one(link):
        try:
            up = await cache.get(_forward_query(link["subscription_url"], query), ua, ttl)
        except Exception:
            return []
        return ds.extract_uris(up.body) if up.status == 200 and up.body else []

    out, seen = [], set()
    for part in await asyncio.gather(*[one(l) for l in links]):
        for uri in part:
            if uri not in seen:
                seen.add(uri)
                out.append(uri)
    return out


_WUI_LABELS = {"wireguard": "WireGuard", "amneziawg": "AmneziaWG", "openvpn": "OpenVPN"}
_WUI_TTL = 30
_wui_cache: Dict[int, tuple] = {}


async def _wui_server(cc):
    """ردیف پنل این سرویس اگر W-UI باشد، وگرنه None."""
    try:
        server = await asyncio.to_thread(panel_resync._server_for, db, cc)
    except Exception:
        return None
    if server and str(server["panel_type"] or "").lower() == "wui":
        return server
    return None


def _merge_files(base: List[dict], extra: List[dict]) -> List[dict]:
    offset = max([f["index"] for f in base], default=0)
    return list(base) + [dict(f, index=offset + f["index"]) for f in extra]


async def _wui_bundle(cc, ttl: float = _WUI_TTL) -> Optional[dict]:
    """فایل‌های WireGuard/AmneziaWG/OpenVPN و مصرف یک سرویس W-UI؛ None یعنی سرویس W-UI نیست."""
    server = await _wui_server(cc)
    if server is None:
        return None
    cid = int(cc["id"])
    hit = _wui_cache.get(cid)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    async def _logins(provider):
        # ورودی‌های OpenConnect/L2TP/PPTP/IKEv2؛ خطا نباید فایل‌های WireGuard/OpenVPN و صفحه را خراب کند
        try:
            return await provider.get_login_profiles(cc["username"])
        except Exception as exc:
            log.warning("wui login profiles failed cc=%s: %s", cid, type(exc).__name__)
            return list(hit[1].get("vpn") or []) if hit else []

    try:
        provider = get_provider(server)
        files, info, vpn = await asyncio.gather(
            provider.get_config_files(cc["username"]), provider.get_sub_info(cc["username"]), _logins(provider))
    except Exception as exc:
        log.warning("wui bundle failed cc=%s: %s", cid, type(exc).__name__)
        if hit and now - hit[0] < STALE_MAX_AGE:
            return hit[1]
        return {"wg": [], "ovpn": [], "vpn": [], "info": {}, "live": False}
    wg, ovpn = [], []
    for item in files:
        label = _WUI_LABELS.get(item["kind"])
        if not label:
            continue
        target = ovpn if item["kind"] == "openvpn" else wg
        target.append({"index": len(target) + 1, "remark": f"{item['filename'].rsplit('.', 1)[0]} ({label})",
                       "filename": item["filename"], "profile": item["text"]})
    bundle = {"wg": wg, "ovpn": ovpn, "vpn": vpn, "info": info, "live": True}
    if len(_wui_cache) > 2000:
        _wui_cache.clear()
    _wui_cache[cid] = (now, bundle)
    return bundle


async def _wg_files(cc) -> List[dict]:
    base = await asyncio.to_thread(ds.wg_files_for_config, db, cc["id"], cc)
    wui = await _wui_bundle(cc)
    return _merge_files(base, wui["wg"]) if wui else base


async def _ovpn_files(cc) -> List[dict]:
    base = await asyncio.to_thread(ds.ovpn_files_for_config, db, cc["id"], cc)
    wui = await _wui_bundle(cc)
    return _merge_files(base, wui["ovpn"]) if wui else base


async def _wui_page(request: Request, cc, wui: dict, settings, brand: str, page_url: str, ttl: float) -> Response:
    pool_info = await asyncio.to_thread(ds.quota_info_for_config, db, cc["id"])
    info = pool_info or wui["info"]
    if wui.get("live") and info:
        try:
            await asyncio.to_thread(db.ds_record_usage, cc["id"], (info.get("upload") or 0) + (info.get("download") or 0))
        except Exception:
            log.exception("usage snapshot failed")
    wg = _merge_files(await asyncio.to_thread(ds.wg_files_for_config, db, cc["id"], cc), wui["wg"])
    ovpn = _merge_files(await asyncio.to_thread(ds.ovpn_files_for_config, db, cc["id"], cc), wui["ovpn"])
    uris = list(await asyncio.to_thread(ds.ssh_uris_for_config, db, cc["id"], cc))
    uris.extend(await _linked_panel_uris(cc, {}, PAGE_UA, ttl))
    series = None
    if settings["dsub_show_chart"] == "1":
        now = int(time.time())
        points = await asyncio.to_thread(db.ds_usage_points, cc["id"], now - 31 * 86400)
        series = ds.build_series(points, now)
    data = ds.build_page_data(cc, info, uris, settings, brand, page_url or str(request.url).split("?")[0],
                              series, ovpn=ovpn, wg=wg, vpn=wui.get("vpn"))
    data["live"] = bool(wui.get("live"))
    await _log(cc["id"], request, "page", 200, settings)
    return render_page(data, f"{brand} · اشتراک {ds.service_name(cc)}".strip(" ·"), settings)


async def _log(config_id, request: Request, kind: str, status: int, settings: Dict[str, str]):
    if settings.get("dsub_log_enabled") != "1":
        return
    try:
        await asyncio.to_thread(db.ds_log_access, config_id, client_ip(request),
                                request.headers.get("user-agent", ""), kind, status)
    except Exception:
        log.exception("access log failed")


async def _snapshot_usage(cc, headers: Dict[str, str]):
    info = ds.parse_userinfo({k.lower(): v for k, v in headers.items()}.get("subscription-userinfo"))
    if info:
        try:
            await asyncio.to_thread(db.ds_record_usage, cc["id"],
                                    (info.get("upload") or 0) + (info.get("download") or 0))
        except Exception:
            log.exception("usage snapshot failed")


# ---------------------------------------------------------------------------
# /s/{token}
# ---------------------------------------------------------------------------
async def sub_endpoint(request: Request) -> Response:
    ip = client_ip(request)
    if not limiter.allow("ok:" + ip, RATE_OK):
        return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
    token = request.path_params["token"]
    cc = await asyncio.to_thread(db.ds_get_config_by_token, token)
    if cc is None or str(cc["status"] or "").lower() == "deleted" or \
            not str(cc["subscription_url"] or "").startswith(("http://", "https://")):
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
        return _not_found()

    settings = await asyncio.to_thread(ds.all_settings, db)
    enabled = ds.is_enabled(db)
    query = _query(request)
    ua = request.headers.get("user-agent", "")
    try:
        ttl = max(0, min(600, int(settings["dsub_cache_ttl"] or 30)))
    except ValueError:
        ttl = 30
    upstream_url = _forward_query(cc["subscription_url"], query)

    # --- حالت خاموش: عبور خام بدون هیچ تغییری (لینک‌های قبلی کاربران قطع نمی‌شوند)
    if not enabled:
        try:
            up = await cache.get(upstream_url, ua, ttl)
        except Exception:
            up = None
        extra_uris = await asyncio.to_thread(ds.ssh_uris_for_config, db, cc["id"], cc)
        extra_uris = list(extra_uris) + await _linked_panel_uris(cc, query, ua, ttl)
        if extra_uris:
            primary_ok = up is not None and up.status == 200 and bool(up.body)
            merged = ds.merge_extra_uris(up.body if primary_ok else b"", extra_uris)
            if merged is not None:
                headers = _clean_headers(
                    {k: v for k, v in up.headers.items() if k in ds._PASS_HEADERS} if primary_ok else {})
                headers["cache-control"] = "no-store"
                await _log(cc["id"], request, "sub", 200, settings)
                return _raw(200, headers, "text/plain; charset=utf-8", merged)
        if up is None:
            return PlainTextResponse("Upstream unavailable", status_code=502)
        headers = _clean_headers({k: v for k, v in up.headers.items() if k in ds._PASS_HEADERS or k == "content-type"})
        ctype = headers.pop("content-type", "text/plain; charset=utf-8")
        headers["cache-control"] = "no-store"
        await _log(cc["id"], request, "sub", up.status, settings)
        return _raw(up.status, headers, ctype, up.body)

    brand = _brand(settings)
    page_url = ds.link_for_token(db, token) if ds.base_url(db) else ""

    # --- صفحه‌ی وب برای مرورگر
    if settings["dsub_web_page"] == "1" and ds.wants_page(ua, request.headers.get("accept", ""), query):
        wui = await _wui_bundle(cc, ttl)
        if wui is not None:
            return await _wui_page(request, cc, wui, settings, brand, page_url, ttl)
        try:
            up = await cache.get(_forward_query(cc["subscription_url"], {}), PAGE_UA, ttl)
        except Exception:
            up = Upstream(0, {}, b"", fresh=False)
        ok = up.status == 200 and bool(up.body)
        info = ds.parse_userinfo(up.headers.get("subscription-userinfo")) if ok else {}
        # For combined VPN+SSH products, the shared quota pool is authoritative;
        # panel headers can otherwise incorrectly show unlimited usage/expiry.
        pool_info = await asyncio.to_thread(ds.quota_info_for_config, db, cc["id"])
        if pool_info:
            info = pool_info
        uris = ds.extract_uris(up.body) if ok else []
        if not uris and up.status == 200 and await panel_resync.heal_config(db, cc):
            try:
                up = await cache.get(_forward_query(cc["subscription_url"], {}), PAGE_UA, ttl, force=True)
            except Exception:
                pass
            ok = up.status == 200 and bool(up.body)
            if ok and not pool_info:
                info = ds.parse_userinfo(up.headers.get("subscription-userinfo"))
            uris = ds.extract_uris(up.body) if ok else []
        if not uris:
            # تشخیص: چرا هیچ کانفیگی از پنل استخراج نشد؟ (وضعیت، نوع پاسخ و ابتدای بدنه)
            log.warning("sub-diag: no uris cc=%s url=%s status=%s ok=%s fresh=%s stale=%s ctype=%s len=%s head=%r",
                        cc["id"], str(cc["subscription_url"])[:80], up.status, ok, up.fresh, up.stale,
                        (up.headers or {}).get("content-type"), len(up.body or b""),
                        (up.body or b"")[:160])
        ovpn_files = await asyncio.to_thread(ds.ovpn_files_for_config, db, cc["id"], cc)
        wg_files = await asyncio.to_thread(ds.wg_files_for_config, db, cc["id"], cc)
        uris.extend(await asyncio.to_thread(ds.ssh_uris_for_config, db, cc["id"], cc))
        uris.extend(await _linked_panel_uris(cc, {}, PAGE_UA, ttl))
        if ok and up.fresh:
            await _snapshot_usage(cc, up.headers)
        series = None
        if settings["dsub_show_chart"] == "1":
            now = int(time.time())
            points = await asyncio.to_thread(db.ds_usage_points, cc["id"], now - 31 * 86400)
            series = ds.build_series(points, now)
        data = ds.build_page_data(cc, info, uris, settings, brand, page_url or str(request.url).split("?")[0],
                                  series, ovpn=ovpn_files, wg=wg_files)
        data["live"] = ok
        await _log(cc["id"], request, "page", 200, settings)
        return render_page(data, f"{brand} · اشتراک {ds.service_name(cc)}".strip(" ·"), settings)

    # --- اپ VPN
    try:
        up = await cache.get(upstream_url, ua, ttl)
    except Exception:
        up = Upstream(0, {}, b"", fresh=False)
    if up.status == 200 and not ds.extract_uris(up.body or b"") and await panel_resync.heal_config(db, cc):
        try:
            up = await cache.get(upstream_url, ua, ttl, force=True)
        except Exception:
            pass
    if up.status == 200 and up.fresh:
        await _snapshot_usage(cc, up.headers)
    # Keep the VPN client subscription headers consistent with the shared quota
    # displayed on the web page and in the bot (including the SSH side's usage).
    pool_info = await asyncio.to_thread(ds.quota_info_for_config, db, cc["id"])
    if pool_info:
        up.headers = dict(up.headers)
        up.headers["subscription-userinfo"] = "; ".join(
            f"{key}={int(pool_info.get(key) or 0)}"
            for key in ("upload", "download", "total", "expire") if key in pool_info
        )
    extra_uris = await asyncio.to_thread(ds.ssh_uris_for_config, db, cc["id"], cc)
    extra_uris = list(extra_uris) + await _linked_panel_uris(cc, query, ua, ttl)
    reply = ds.compose_client_reply(up.status, up.headers, up.body, cc, settings, brand, page_url,
                                    extra_uris=extra_uris)
    if reply is None:
        status = 404 if up.status == 404 else 502
        await _log(cc["id"], request, "sub", status, settings)
        return PlainTextResponse("Upstream unavailable" if status == 502 else "Not found", status_code=status,
                                 headers={"cache-control": "no-store"})
    await _log(cc["id"], request, "sub", 200, settings)
    headers = _clean_headers(reply.headers)
    ctype = headers.pop("content-type", "text/plain; charset=utf-8")
    return _raw(200, headers, ctype, reply.body)


# ---------------------------------------------------------------------------
# /s/{token}/qr.png
# ---------------------------------------------------------------------------
def _qr_png(text: str) -> bytes:
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


async def qr_endpoint(request: Request) -> Response:
    ip = client_ip(request)
    if not limiter.allow("ok:" + ip, RATE_OK):
        return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
    token = request.path_params["token"]
    cc = await asyncio.to_thread(db.ds_get_config_by_token, token)
    settings = await asyncio.to_thread(ds.all_settings, db)
    if cc is None or not ds.is_enabled(db) or settings["dsub_show_qr"] != "1":
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    idx = request.query_params.get("i")
    if idx is None:
        text = ds.link_for_token(db, token)
    else:
        try:
            n = int(idx)
        except ValueError:
            return _not_found()
        try:
            up = await cache.get(cc["subscription_url"], PAGE_UA, 30)
        except Exception:
            return PlainTextResponse("Upstream unavailable", status_code=502)
        uris = ds.extract_uris(up.body) if up.status == 200 else []
        if up.status == 200:
            uris.extend(await asyncio.to_thread(ds.ssh_uris_for_config, db, cc["id"], cc))
        if not 0 <= n < min(len(uris), 60):
            return _not_found()
        text = uris[n]
    try:
        png = await asyncio.to_thread(_qr_png, text)
    except Exception:
        log.exception("qr generation failed")
        return PlainTextResponse("QR unavailable", status_code=503)
    return Response(png, media_type="image/png", headers={"cache-control": "private, max-age=300"})


# ---------------------------------------------------------------------------
# /s/{token}/ovpn/{n}
# ---------------------------------------------------------------------------
async def ovpn_endpoint(request: Request) -> Response:
    ip = client_ip(request)
    if not limiter.allow("ok:" + ip, RATE_OK):
        return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
    token = request.path_params["token"]
    cc = await asyncio.to_thread(db.ds_get_config_by_token, token)
    if cc is None or str(cc["status"] or "").lower() == "deleted" or not ds.is_enabled(db):
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    files = await _ovpn_files(cc)
    item = next((f for f in files if f["index"] == request.path_params["n"]), None)
    if item is None:
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    settings = await asyncio.to_thread(ds.all_settings, db)
    await _log(cc["id"], request, "ovpn", 200, settings)
    headers = {"cache-control": "no-store", "content-disposition": f'attachment; filename="{item["filename"]}"'}
    return _raw(200, headers, "application/x-openvpn-profile", item["profile"].encode("utf-8"))


# ---------------------------------------------------------------------------
# /s/{token}/wg/{n}
# ---------------------------------------------------------------------------
async def wg_endpoint(request: Request) -> Response:
    ip = client_ip(request)
    if not limiter.allow("ok:" + ip, RATE_OK):
        return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
    token = request.path_params["token"]
    cc = await asyncio.to_thread(db.ds_get_config_by_token, token)
    if cc is None or str(cc["status"] or "").lower() == "deleted" or not ds.is_enabled(db):
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    files = await _wg_files(cc)
    item = next((f for f in files if f["index"] == request.path_params["n"]), None)
    if item is None:
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    settings = await asyncio.to_thread(ds.all_settings, db)
    await _log(cc["id"], request, "wg", 200, settings)
    headers = {"cache-control": "no-store", "content-disposition": f'attachment; filename="{item["filename"]}"'}
    return _raw(200, headers, "application/x-wireguard-profile", item["profile"].encode("utf-8"))


# ---------------------------------------------------------------------------
# /s/{token}/reveal  (POST)  — مقدار نام‌کاربری/رمز/PSK یک ورودی OpenConnect/L2TP/PPTP/IKEv2
# ---------------------------------------------------------------------------
REVEAL_PER_TOKEN = 30   # در دقیقه برای هر لینک
REVEAL_PER_IP = 60      # در دقیقه برای هر IP


def _same_origin(request: Request) -> bool:
    """فقط درخواست خودِ صفحه: سایت دیگر نمی‌تواند این را بزند (Sec-Fetch-Site/Origin + هدر سفارشی که preflight می‌خواهد)."""
    if request.headers.get("x-sub-reveal") != "1":
        return False
    site = request.headers.get("sec-fetch-site", "")
    if site:
        # مرورگرهای جدید: خودِ مرورگر می‌گوید درخواست از کجاست (پشت پروکسی هم جواب می‌دهد)
        return site in ("same-origin", "none")
    origin = request.headers.get("origin", "")
    if origin:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if origin.split("://", 1)[-1].rstrip("/") != host.split(",")[0].strip():
            return False
    return True


async def vpn_reveal_endpoint(request: Request) -> Response:
    ip = client_ip(request)
    token = request.path_params["token"]
    if not limiter.allow("ok:" + ip, RATE_OK) or not limiter.allow("rv-ip:" + ip, REVEAL_PER_IP) \
            or not limiter.allow("rv-tok:" + token, REVEAL_PER_TOKEN):
        return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
    if not _same_origin(request):
        return PlainTextResponse("Forbidden", status_code=403, headers={"cache-control": "no-store"})
    cc = await asyncio.to_thread(db.ds_get_config_by_token, token)
    if cc is None or str(cc["status"] or "").lower() == "deleted" or not ds.is_enabled(db):
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    try:
        body = await request.json()
        index, what = int(body.get("i")), str(body.get("w"))
    except Exception:
        return PlainTextResponse("Bad request", status_code=400, headers={"cache-control": "no-store"})
    wui = await _wui_bundle(cc)
    value = ds.vpn_secret((wui or {}).get("vpn"), index, what)
    if value is None:
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    settings = await asyncio.to_thread(ds.all_settings, db)
    await _log(cc["id"], request, "reveal", 200, settings)
    return JSONResponse({"v": value}, headers={"cache-control": "no-store", "x-robots-tag": "noindex, nofollow"})


# ---------------------------------------------------------------------------
# /s/{token}/vpn/{n}/ca  (گواهی CA تونل IKEv2؛ عمومی است)
# ---------------------------------------------------------------------------
async def vpn_ca_endpoint(request: Request) -> Response:
    ip = client_ip(request)
    if not limiter.allow("ok:" + ip, RATE_OK):
        return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
    token = request.path_params["token"]
    cc = await asyncio.to_thread(db.ds_get_config_by_token, token)
    if cc is None or str(cc["status"] or "").lower() == "deleted" or not ds.is_enabled(db):
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    wui = await _wui_bundle(cc)
    item = ds.vpn_ca_file((wui or {}).get("vpn"), request.path_params["n"])
    if item is None:
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    settings = await asyncio.to_thread(ds.all_settings, db)
    await _log(cc["id"], request, "vpnca", 200, settings)
    headers = {"cache-control": "no-store", "content-disposition": f'attachment; filename="{item["filename"]}"'}
    return _raw(200, headers, "application/x-x509-ca-cert", item["pem"].encode("utf-8"))



# ---------------------------------------------------------------------------
# /sub/smart/{token}  (ادغام چند سرویس در یک لینک)
# ---------------------------------------------------------------------------
async def smart_endpoint(request: Request) -> Response:
    ip = client_ip(request)
    if not limiter.allow("ok:" + ip, RATE_OK):
        return PlainTextResponse("Too many requests", status_code=429, headers={"retry-after": "60"})
    row = await asyncio.to_thread(db.get_smart_subscription, request.path_params["token"])
    if row is None or db.get_setting("smart_subscription_enabled", "1") != "1":
        if not limiter.allow("miss:" + ip, RATE_MISS):
            return PlainTextResponse("Too many requests", status_code=429)
        return _not_found()
    try:
        urls = [u for u in json.loads(row["source_urls_json"]) if str(u).startswith(("http://", "https://"))]
    except ValueError:
        urls = []
    settings = await asyncio.to_thread(ds.all_settings, db)
    ua = request.headers.get("user-agent", "")
    ttl = 30

    async def one(url):
        try:
            up = await cache.get(url, ua, ttl)
            return up.status, up.headers, up.body
        except Exception:
            return 0, {}, b""

    parts = await asyncio.gather(*[one(u) for u in urls[:20]])
    body, userinfo, count = ds.merge_smart(list(parts))
    await _log(None, request, "smart", 200 if count else 502, settings)
    if not count:
        return PlainTextResponse("Upstream unavailable", status_code=502)
    headers = {"cache-control": "no-store"}
    if userinfo:
        headers["subscription-userinfo"] = userinfo
    title = _brand(settings)
    headers["profile-title"] = ds.b64_header(title[:80])
    try:
        interval = int(settings["dsub_update_interval"] or 0)
    except ValueError:
        interval = 0
    if interval > 0:
        headers["profile-update-interval"] = str(interval)
    return _raw(200, headers, "text/plain; charset=utf-8", body)


async def healthz(request: Request) -> Response:
    return JSONResponse({"ok": True})


async def robots(request: Request) -> Response:
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


# ---------------------------------------------------------------------------
# نمونه‌بردار مصرف (برای نمودار صفحه‌ی وب) و پاک‌سازی لاگ‌ها
# ---------------------------------------------------------------------------
async def _sampler_round():
    settings = await asyncio.to_thread(ds.all_settings, db)
    if ds.is_enabled(db) and settings["dsub_usage_sampling"] == "1":
        ids = await asyncio.to_thread(db.ds_recent_config_ids, int(time.time()) - 21 * 86400)
        sem = asyncio.Semaphore(4)

        async def one(cid):
            async with sem:
                cc = await asyncio.to_thread(db.ds_get_config, cid)
                if cc is None or str(cc["status"] or "") != "active" or \
                        not str(cc["subscription_url"] or "").startswith(("http://", "https://")):
                    return
                wui_server = await _wui_server(cc)
                if wui_server is not None:
                    try:
                        info = await get_provider(wui_server).get_sub_info(cc["username"])
                        await asyncio.to_thread(db.ds_record_usage, cc["id"],
                                                (info.get("upload") or 0) + (info.get("download") or 0))
                    except Exception:
                        log.warning("wui usage sample failed cc=%s", cid)
                    return
                try:
                    up = await cache.get(cc["subscription_url"], PAGE_UA, 0, force=True)
                except Exception:
                    return
                if up.status == 200:
                    await _snapshot_usage(cc, up.headers)

        await asyncio.gather(*[one(c) for c in ids])
    await asyncio.to_thread(db.ds_prune)


async def _sampler_loop():
    await asyncio.sleep(60)
    while True:
        try:
            await _sampler_round()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("usage sampler failed")
        await asyncio.sleep(1800)


@asynccontextmanager
async def lifespan(app):
    global _session
    import aiohttp
    try:
        await asyncio.to_thread(db.init_db, OWNER_ID)  # مطمئن می‌شود ستون/جدول‌های ساب اختصاصی وجود دارند
    except Exception:
        log.exception("init_db failed")
    _session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=None if VERIFY_TLS else False, limit=64),
        timeout=aiohttp.ClientTimeout(total=15),
    )
    task = asyncio.create_task(_sampler_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await _session.close()


app = Starlette(
    routes=[
        Route("/s/{token}", sub_endpoint, methods=["GET", "HEAD"]),
        Route("/s/{token}/qr.png", qr_endpoint, methods=["GET"]),
        Route("/s/{token}/ovpn/{n:int}", ovpn_endpoint, methods=["GET"]),
        Route("/s/{token}/wg/{n:int}", wg_endpoint, methods=["GET"]),
        Route("/s/{token}/vpn/{n:int}/ca", vpn_ca_endpoint, methods=["GET"]),
        Route("/s/{token}/reveal", vpn_reveal_endpoint, methods=["POST"]),
        Route("/sub/smart/{token}", smart_endpoint, methods=["GET", "HEAD"]),
        Route("/healthz", healthz, methods=["GET"]),
        Route("/robots.txt", robots, methods=["GET"]),
    ],
    lifespan=lifespan,
)
