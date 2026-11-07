# -*- coding: utf-8 -*-
"""مسیرهای API مخصوص سایت فروش وب: ورود، کاتالوگ، سرویس‌ها، QR و ادغام حساب."""
from fastapi import APIRouter

import dedicated_sub as ds

from miniapp.server import (
    BaseModel,
    Database,
    Depends,
    Field,
    HTTPException,
    Header,
    Optional,
    Query,
    Request,
    Response,
    Tenant,
    _client_ip,
    _verify_web_turnstile,
    asyncio,
    compare_price_for,
    get_bot_username,
    get_tenant,
    get_verified_user,
    html_lib,
    logging,
    os,
    render_stored_setting,
    tr,
    web_auth,
)

router = APIRouter()


def _web_main_only(tenant: Tenant):
    if tenant.tenant_id:
        raise HTTPException(status_code=404, detail=tr("این فروشگاه در دسترس نیست."))


def _web_catalog_payload(db: Database) -> list:
    categories = []
    paths = db.get_category_path_names()
    for c in db.get_categories(active_only=True):
        products = []
        for p in db.get_products(c["id"], active_only=True):
            in_stock = bool(p["is_auto_provision"]) or db.count_available_configs(p["id"]) > 0
            products.append({
                "id": p["id"],
                "name": p["name"],
                "price": p["price"],
                "original_price": compare_price_for(p) or None,
                "description": p["description"],
                "duration_days": p.get("duration_days") if hasattr(p, "get") else p["duration_days"],
                "volume_gb": p.get("auto_provision_volume_gb") if hasattr(p, "get") else p["auto_provision_volume_gb"],
                "in_stock": in_stock,
            })
        if products:
            categories.append({"id": c["id"], "name": paths.get(c["id"], c["name"]), "products": products})
    return categories


@router.get("/api/web/catalog")
async def api_web_catalog(tenant: Tenant = Depends(get_tenant)):
    """کاتالوگ عمومی سایت (بدون ورود)."""
    _web_main_only(tenant)
    categories = await asyncio.to_thread(_web_catalog_payload, tenant.db)
    username = await get_bot_username(tenant)
    store_name = render_stored_setting("store_name", tenant.db.get_setting("store_name", "⚡ SHOP VPN"))
    return {
        "store_name": store_name,
        "logo": "",
        "tagline": "",
        "primary_color": "",
        "support_url": "",
        "bot_url": f"https://t.me/{username}" if username else "",
        "categories": categories,
    }


@router.get("/api/web/apps")
def api_web_apps(tenant: Tenant = Depends(get_tenant)):
    """برنامه‌های اتصال (همان فهرست صفحه‌ی ساب اختصاصی، با تنظیمات ادمین)."""
    _web_main_only(tenant)
    return {"platforms": ds.PLATFORM_LABELS, "apps": ds.resolve_apps(ds.all_settings(tenant.db))}


@router.post("/api/web/login/start")
async def api_web_login_start(request: Request, tenant: Tenant = Depends(get_tenant)):
    _web_main_only(tenant)
    username = await get_bot_username(tenant)
    if not username:
        raise HTTPException(status_code=503, detail=tr("سرور موقتاً در دسترس نیست، دوباره تلاش کنید."))
    if not await asyncio.to_thread(web_auth.enforce_rate_limit, tenant.db, "web-login-ip:" + _client_ip(request), 30, 3600):
        raise HTTPException(status_code=429, detail=tr("تعداد درخواست‌ها زیاد است؛ چند دقیقه بعد دوباره تلاش کنید."))
    try:
        code, poll = await asyncio.to_thread(web_auth.start_login, tenant.db, _client_ip(request))
    except ValueError:
        raise HTTPException(status_code=429, detail=tr("تعداد درخواست‌ها زیاد است؛ چند دقیقه بعد دوباره تلاش کنید."))
    return {
        "link": f"https://t.me/{username}?start=weblogin_{code}",
        "poll": poll,
        "expires_in": web_auth.LOGIN_TTL,
    }


class WebLoginPoll(BaseModel):
    poll: str


@router.get("/api/web/security-config")
def api_web_security_config(tenant: Tenant = Depends(get_tenant)):
    _web_main_only(tenant)
    email_ready = web_auth.email_configured()
    return {
        "turnstile_site_key": os.getenv("SHOPVPN_TURNSTILE_SITE_KEY", "").strip(),
        "email_enabled": email_ready,
    }


class WebMergeCode(BaseModel):
    code: str = Field(default="", max_length=16)


def _merge_http_error(exc: ValueError):
    return HTTPException(status_code=400, detail=tr(web_auth.merge_reason_text(str(exc))))


@router.post("/api/web/merge/code")
async def api_web_merge_code(auth=Depends(get_verified_user)):
    """کد ادغام از سمت سایت: در ربات با /merge CODE وارد می‌شود."""
    tg_id, db, tenant = auth
    _web_main_only(tenant)
    if not web_auth.is_email_account(db, tg_id):
        raise HTTPException(status_code=400, detail=tr("این گزینه فقط برای حساب ایمیلی است."))
    try:
        code = await asyncio.to_thread(web_auth.create_merge_code, db, "web", tg_id)
    except ValueError as exc:
        raise _merge_http_error(exc)
    return {"code": code, "expires_in": web_auth.MERGE_CODE_TTL}


@router.post("/api/web/merge/preview")
async def api_web_merge_preview(body: WebMergeCode, request: Request, auth=Depends(get_verified_user)):
    """کدی را که در ربات ساخته شده بررسی می‌کند و اطلاعات تأیید را برمی‌گرداند (بدون تغییر)."""
    tg_id, db, tenant = auth
    _web_main_only(tenant)
    if not await asyncio.to_thread(web_auth.enforce_rate_limit, db, "merge-try:" + str(tg_id), web_auth.MERGE_TRIES_PER_HOUR, 3600):
        raise HTTPException(status_code=429, detail=tr("تلاش‌های زیاد؛ بعداً دوباره امتحان کنید."))
    try:
        info = await asyncio.to_thread(web_auth.preview_merge, db, body.code, tg_id, "web")
    except ValueError as exc:
        raise _merge_http_error(exc)
    return {"email": info["email"], "telegram": info["telegram"]}


@router.post("/api/web/merge/confirm")
async def api_web_merge_confirm(body: WebMergeCode, auth=Depends(get_verified_user)):
    """ادغام نهایی حساب ایمیلی در حساب تلگرامِ کد. نشست فعلی باطل می‌شود."""
    tg_id, db, tenant = auth
    _web_main_only(tenant)
    if not await asyncio.to_thread(web_auth.enforce_rate_limit, db, "merge-try:" + str(tg_id), web_auth.MERGE_TRIES_PER_HOUR, 3600):
        raise HTTPException(status_code=429, detail=tr("تلاش‌های زیاد؛ بعداً دوباره امتحان کنید."))
    try:
        await asyncio.to_thread(web_auth.complete_merge, db, body.code, tg_id, "web")
    except ValueError as exc:
        raise _merge_http_error(exc)
    return {"status": "ok"}


class WebEmailStart(BaseModel):
    email: str


class WebEmailVerify(BaseModel):
    email: str
    code: str


@router.post("/api/web/email/start")
async def api_web_email_start(body: WebEmailStart, request: Request, tenant: Tenant = Depends(get_tenant)):
    _web_main_only(tenant)
    email = (body.email or "").strip().lower()
    await asyncio.to_thread(_verify_web_turnstile, request)
    ip = _client_ip(request)
    if not await asyncio.to_thread(web_auth.enforce_rate_limit, tenant.db, "email-start-ip:" + ip, 5, 3600):
        raise HTTPException(status_code=429, detail=tr("تعداد درخواست‌ها زیاد است؛ یک ساعت دیگر دوباره تلاش کنید."))
    try:
        code = await asyncio.to_thread(web_auth.start_email_login, tenant.db, email, ip)
        await asyncio.to_thread(web_auth.send_email_code, email, code)
    except ValueError as exc:
        if str(exc) == "rate_limited":
            raise HTTPException(status_code=429, detail=tr("برای این ایمیل کمی صبر کنید و دوباره تلاش کنید."))
        raise HTTPException(status_code=400, detail=tr("ایمیل واردشده معتبر نیست."))
    except RuntimeError:
        raise HTTPException(status_code=503, detail=tr("ورود ایمیلی هنوز پیکربندی نشده است."))
    except Exception:
        logging.getLogger("web_auth").exception("Could not send web email verification")
        raise HTTPException(status_code=502, detail=tr("ارسال ایمیل ناموفق بود؛ چند دقیقه دیگر دوباره تلاش کنید."))
    return {"status": "sent", "expires_in": web_auth.LOGIN_TTL}


@router.post("/api/web/email/verify")
async def api_web_email_verify(body: WebEmailVerify, request: Request, tenant: Tenant = Depends(get_tenant)):
    _web_main_only(tenant)
    await asyncio.to_thread(_verify_web_turnstile, request)
    ip = _client_ip(request)
    if not await asyncio.to_thread(web_auth.enforce_rate_limit, tenant.db, "email-verify-ip:" + ip, 15, 900):
        raise HTTPException(status_code=429, detail=tr("تلاش‌های زیادی انجام شده؛ ۱۵ دقیقه دیگر دوباره تلاش کنید."))
    token, tg_id = await asyncio.to_thread(web_auth.verify_email_code, tenant.db, body.email, body.code, ip)
    if not token:
        raise HTTPException(status_code=400, detail=tr("کد نامعتبر یا منقضی شده است."))
    email = body.email.strip().lower()
    if await asyncio.to_thread(web_auth.is_email_account, tenant.db, tg_id):
        await asyncio.to_thread(tenant.db.add_or_update_user, tg_id, "", email)
    user = await asyncio.to_thread(tenant.db.get_user, tg_id)
    return {"status": "ok", "token": token, "user": {"first_name": (user["first_name"] if user else email), "username": (user["username"] if user else ""), "is_email_account": await asyncio.to_thread(web_auth.is_email_account, tenant.db, tg_id)}}


@router.post("/api/web/login/poll")
async def api_web_login_poll(body: WebLoginPoll, request: Request, tenant: Tenant = Depends(get_tenant)):
    _web_main_only(tenant)
    status, token, tg_id = await asyncio.to_thread(web_auth.poll_login, tenant.db, body.poll, _client_ip(request))
    if status != "ok":
        return {"status": status}
    user = tenant.db.get_user(tg_id)
    return {
        "status": "ok",
        "token": token,
        "user": {"first_name": user["first_name"] if user else "", "username": user["username"] if user else ""},
    }


@router.get("/api/web/session")
def api_web_session(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    user = db.get_user(tg_id)
    return {"first_name": user["first_name"] if user else "", "username": user["username"] if user else "", "is_email_account": web_auth.is_email_account(db, tg_id)}


@router.post("/api/web/logout")
def api_web_logout(x_web_token: Optional[str] = Header(None), tenant: Tenant = Depends(get_tenant)):
    _web_main_only(tenant)
    if x_web_token:
        web_auth.logout(tenant.db, x_web_token)
    return {"status": "ok"}


def _web_services(db: Database, tg_id: int) -> list:
    """سرویس‌های فعال کاربر برای داشبورد: کانفیگ‌های ساخته‌شده روی پنل + کانفیگ‌های بانک."""
    out, panel_order_ids = [], set()
    for c in db.get_custom_configs_for_user(tg_id):
        if c["order_id"]:
            panel_order_ids.add(c["order_id"])
        if not c["subscription_url"]:
            continue
        is_test = c["source"] == "test"
        out.append({
            "key": f"c{c['id']}", "kind": "custom", "id": c["id"],
            "name": c["display_name"] or c["username"],
            "volume_gb": c["volume_gb"], "duration_days": c["duration_days"],
            "link": ds.display_link(db, c["id"], c["subscription_url"]), "expires_at": c["expires_at"],
            "is_test": is_test,
            "enabled": (c["enabled"] if "enabled" in c.keys() else 1) == 1,
            "can_renew": not is_test,
        })
    for o in db.get_user_orders(tg_id):
        if o["status"] != "approved" or o["is_renewal"] or o["is_custom_config"] or o["id"] in panel_order_ids:
            continue
        product = db.get_product(o["product_id"]) if o["product_id"] else None
        cfgs = list(db.get_order_configs(o["id"]) or [])
        if not cfgs and o["config_id"]:
            cfg = db.get_config_by_id(o["config_id"])
            cfgs = [cfg] if cfg else []
        for c in cfgs:
            if (("is_disabled" in c.keys()) and c["is_disabled"]) or not c["link"]:
                continue
            out.append({
                "key": f"b{c['id']}", "kind": "bank", "id": c["id"],
                "name": product["name"] if product else "",
                "volume_gb": None, "duration_days": None,
                "link": c["link"], "expires_at": c["expires_at"],
                "is_test": False, "enabled": True, "can_renew": False,
            })
    return out


@router.get("/api/web/services")
def api_web_services(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    return {
        "renew_enabled": db.get_setting("svc_show_renew_full", "1") == "1",
        "services": _web_services(db, tg_id),
    }


@router.get("/api/web/qr")
def api_web_qr(link: str = Query(..., max_length=2000), auth=Depends(get_verified_user)):
    """QR لینک یکی از سرویس‌های خود کاربر (برای لینک دیگران ساخته نمی‌شود)."""
    tg_id, db, _ = auth
    if not any(s["link"] == link for s in _web_services(db, tg_id)):
        raise HTTPException(status_code=404, detail=tr("کانفیگ یافت نشد یا متعلق به شما نیست."))
    return _qr_svg_response(link)


def _qr_svg_response(data: str):
    try:
        import io
        import qrcode
        import qrcode.image.svg
    except ImportError:
        raise HTTPException(status_code=501, detail=tr("سرور موقتاً در دسترس نیست، دوباره تلاش کنید."))
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "private, no-store"})


def _web_order_view(db: Database, tg_id: int, order_id: int):
    """وضعیت یک سفارش و لینک‌های تحویل آن (هم بانک کانفیگ، هم محصول ساخت خودکار روی پنل)."""
    order = db.get_order(order_id)
    if not order or order["user_id"] != tg_id:
        return None
    product = db.get_product(order["product_id"]) if order["product_id"] else None
    links, expires_at = [], None
    if order["status"] == "approved":
        customs = [c for c in db.get_custom_configs_for_user(tg_id) if c["order_id"] == order_id]
        if customs:
            links = [ds.display_link(db, c["id"], c["subscription_url"]) for c in customs if c["subscription_url"]]
            expires_at = customs[0]["expires_at"]
        else:
            cfgs = list(db.get_order_configs(order_id) or [])
            if not cfgs and order["config_id"]:
                cfg = db.get_config_by_id(order["config_id"])
                cfgs = [cfg] if cfg else []
            cfgs = [c for c in cfgs if not (("is_disabled" in c.keys()) and c["is_disabled"])]
            links = [c["link"] for c in cfgs if c["link"]]
            expires_at = cfgs[0]["expires_at"] if cfgs else None
    return {
        "order_id": order_id,
        "status": order["status"],
        "product_name": product["name"] if product else "",
        "quantity": order["quantity"] or 1,
        "final_price": order["final_price"],
        "links": links,
        "expires_at": expires_at,
    }


@router.get("/api/web/orders/{order_id}")
def api_web_order(order_id: int, auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    view = _web_order_view(db, tg_id, order_id)
    if not view:
        raise HTTPException(status_code=404, detail=tr("سفارش یافت نشد."))
    return view


@router.get("/api/web/orders/{order_id}/qr/{index}")
def api_web_order_qr(order_id: int, index: int, auth=Depends(get_verified_user)):
    """QR لینک تحویل (ساخت روی سرور خودت؛ لینک اشتراک به هیچ سرویس بیرونی نمی‌رود)."""
    tg_id, db, _ = auth
    view = _web_order_view(db, tg_id, order_id)
    if not view or not (0 <= index < len(view["links"])):
        raise HTTPException(status_code=404, detail=tr("سفارش یافت نشد."))
    return _qr_svg_response(view["links"][index])


def _seo_base(request: Request) -> str:
    configured = os.getenv("SHOPVPN_SEO_SITE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme
    host = request.headers.get("x-forwarded-host", "").split(",")[0].strip() or request.headers.get("host", "")
    return f"{proto}://{host}".rstrip("/")


@router.get("/api/web/world-map")
async def web_world_map():
    """مسیر SVG خطوط ساحلی برای «نقشه زنده شبکه» صفحه اول (همان کش world_map.py پنل ادمین؛
    مرورگر مشتری هیچ‌وقت مستقیم به CDN وصل نمی‌شود چون CSP اجازه‌اش را نمی‌دهد)."""
    import world_map
    return await world_map.get_world_map()


@router.get("/api/web/world-countries")
async def web_world_countries():
    """مرز کشورها (برای رنگ‌کردن کشورهای دارای سرور روی «نقشه زنده شبکه»)؛ کش روی دیسک سرور."""
    import world_map
    return await world_map.get_countries()


_NETMAP_TTL = 20
_netmap_cache: dict = {"at": 0.0, "data": None}
_NETMAP_HIST_STEP = 60      # حداقل فاصله‌ی دو نمونه‌ی تاریخچه (ثانیه)
_NETMAP_HIST_MAX = 48       # تعداد نمونه‌ی نگه‌داری‌شده برای هر لوکیشن
_netmap_hist: dict = {}     # id -> {"at": float, "pts": [ms|None, ...]}  (در حافظه؛ با ری‌استارت ریست می‌شود)


def _netmap_overrides(db: Database) -> list:
    """تنظیم اختیاری `netmap_locations` (JSON) برای اصلاح دستی مکان وقتی تشخیص خودکار
    (مثلاً کانفیگ پشت CDN) غلط است. نمونه:
    [{"product_ids":[3,4], "match":"آلمان", "cc":"de", "city":"Frankfurt", "city_fa":"فرانکفورت", "lat":50.11, "lon":8.68}]
    هر محصولی که با product_ids یا match (زیررشته‌ی نام) بخورد فقط در همین مکان نمایش داده می‌شود."""
    import json
    try:
        raw = db.get_setting("netmap_locations", "") or ""
        data = json.loads(raw) if raw.strip() else []
    except Exception:
        return []
    out = []
    for o in data if isinstance(data, list) else []:
        try:
            out.append({
                "ids": {int(x) for x in (o.get("product_ids") or [])},
                "match": str(o.get("match") or "").strip().lower(),
                "cc": str(o.get("cc") or "").lower()[:2],
                "city": str(o.get("city") or ""),
                "city_fa": str(o.get("city_fa") or ""),
                "lat": float(o["lat"]), "lon": float(o["lon"]),
            })
        except Exception:
            continue
    return out


def _apply_netmap_overrides(products: list, located: dict, overrides: list) -> None:
    for p in products:
        name = str(p.get("name") or "").lower()
        for o in overrides:
            if p["id"] in o["ids"] or (o["match"] and o["match"] in name):
                key = (round(o["lat"], 1), round(o["lon"], 1))
                located[p["id"]] = {key: {"cc": o["cc"], "city": o["city"], "city_fa": o["city_fa"],
                                          "lat": o["lat"], "lon": o["lon"], "targets": []}}
                break


def _netmap_history(node_id: str, ms, now: float) -> list:
    h = _netmap_hist.setdefault(node_id, {"at": 0.0, "pts": []})
    if now - h["at"] >= _NETMAP_HIST_STEP or not h["pts"]:
        h["at"] = now
        h["pts"].append(ms)
        del h["pts"][:-_NETMAP_HIST_MAX]
    return list(h["pts"])


def _network_map_products(db: Database) -> list:
    items = []
    for c in db.get_categories(active_only=True):
        for p in db.get_products(c["id"], active_only=True):
            items.append({
                "id": p["id"],
                "name": p["name"],
                "price": p["price"],
                "in_stock": bool(p["is_auto_provision"]) or db.count_available_configs(p["id"]) > 0,
                "duration_days": p["duration_days"],
                "volume_gb": p["auto_provision_volume_gb"],
            })
    return items


async def _network_map_build(db: Database) -> dict:
    import config_geo
    from datetime import datetime, timezone
    products = await asyncio.to_thread(_network_map_products, db)
    located = await config_geo.locate_products(db, products)
    _apply_netmap_overrides(products, located, await asyncio.to_thread(_netmap_overrides, db))
    groups: dict = {}
    for p in products:
        for key, loc in located.get(p["id"], {}).items():
            g = groups.setdefault(key, {
                "id": "l%d_%d" % (round(loc["lat"] * 10), round(loc["lon"] * 10)),
                "cc": loc["cc"], "city": loc["city"], "city_fa": loc.get("city_fa", ""), "lat": loc["lat"], "lon": loc["lon"],
                "targets": [], "products": [],
            })
            for t in loc["targets"]:
                if t not in g["targets"] and len(g["targets"]) < config_geo.TARGETS_PER_LOCATION:
                    g["targets"].append(t)
            g["products"].append({k: v for k, v in p.items()})
    nodes = []
    checked = datetime.now(timezone.utc).isoformat()
    ordered = list(groups.values())
    import time as _t
    probes = await asyncio.gather(*(config_geo.location_probe(g["targets"]) for g in ordered))
    mono = _t.monotonic()
    for g, probe in zip(ordered, probes):
        g.pop("targets")
        g["status"] = probe["status"]
        g["latency_ms"] = probe["latency_ms"]
        g["history"] = _netmap_history(g["id"], probe["latency_ms"] if probe["status"] == "up" else None, mono)
        g["last_check"] = checked
        g["products_total"] = len(g["products"])
        g["products_in_stock"] = sum(1 for x in g["products"] if x["in_stock"])
        nodes.append(g)
    nodes.sort(key=lambda n: (-n["products_in_stock"], n["city"]))
    return {"nodes": nodes}


@router.get("/api/web/network-map")
async def web_network_map(request: Request, tenant: Tenant = Depends(get_tenant)):
    """Store locations derived from the config links of each product, with per-location products."""
    _web_main_only(tenant)
    import time
    from datetime import datetime, timezone
    now = time.monotonic()
    if _netmap_cache["data"] is not None and now - _netmap_cache["at"] < _NETMAP_TTL:
        data = _netmap_cache["data"]
    else:
        data = await _network_map_build(tenant.db)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _netmap_cache["at"], _netmap_cache["data"] = now, data
    # مبدأ مسیرها: کشور بازدیدکننده از هدر CDN (کلودفلر و مشابه)؛ بدون هدر = تهران (پیش‌فرض کلاینت)
    cc = (request.headers.get("cf-ipcountry") or request.headers.get("x-vercel-ip-country") or "").strip().upper()
    origin = None
    if len(cc) == 2 and cc.isalpha() and cc not in ("XX", "T1"):
        try:
            import geo_scan
            info = geo_scan.COUNTRY_INFO.get(cc)
            if info:
                origin = {"cc": cc.lower(), "lat": info[1], "lon": info[2]}
        except Exception:
            origin = None
    return {**data, "origin": origin}


@router.get("/robots.txt", include_in_schema=False)
def seo_robots(request: Request):
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        f"Sitemap: {_seo_base(request)}/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sitemap.xml", include_in_schema=False)
def seo_sitemap(request: Request):
    base = _seo_base(request)
    pages = [("/", "weekly", "1.0"), ("/en/", "weekly", "0.9")]
    alternates = (
        '<xhtml:link rel="alternate" hreflang="fa" href="' + html_lib.escape(base + "/") + '"/>'
        '<xhtml:link rel="alternate" hreflang="en" href="' + html_lib.escape(base + "/en/") + '"/>'
    )
    urls = "".join(
        "<url><loc>" + html_lib.escape(base + path) + "</loc>" + alternates
        + "<changefreq>" + freq + "</changefreq><priority>" + priority + "</priority></url>"
        for path, freq, priority in pages
    )
    xml = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + urls + '</urlset>')
    return Response(content=xml, media_type="application/xml; charset=utf-8", headers={"Cache-Control": "public, max-age=3600"})



