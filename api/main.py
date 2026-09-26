# -*- coding: utf-8 -*-
"""API توکنی مستند ShopVPN - F20.

اجرا:
    uvicorn api.main:app --host 127.0.0.1 --port 8003 --workers 1

احراز هویت با هدر Token انجام می‌شود. API عمداً read-only است مگر اینکه
توکن scope صریح orders:write داشته باشد؛ /token2 چنین scopeای صادر نمی‌کند.
"""
import os
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from config import DB_PATH as PROJECT_DB_PATH
from database import Database
from .utils import RateLimiter, hash_token, has_scope, pagination, safe_row
from i18n import tr, set_language, reset_language, normalize_language

DB_PATH = os.getenv("DB_PATH", PROJECT_DB_PATH)
app = FastAPI(
    title="ShopVPN Integration API",
    version="1.0.0",
    description="API توکنی read-only برای یکپارچه‌سازی ShopVPN. احراز هویت با هدر Token.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

db = Database(DB_PATH)

RATE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "60"))
limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)


@app.middleware("http")
async def language_middleware(request: Request, call_next):
    language = normalize_language(request.headers.get("x-language") or request.headers.get("accept-language"))
    catalog = db.translation_catalog(language) if language not in {"fa", "en"} and db.get_language(language) and db.get_language(language)["enabled"] else None
    token = set_language(language, catalog)
    try:
        return await call_next(request)
    finally:
        reset_language(token)


def api_message(text: str) -> str:
    return tr(text)

access_logger = logging.getLogger("shopvpn.api.access")
if not access_logger.handlers:
    os.makedirs("logs", exist_ok=True)
    _handler = RotatingFileHandler("logs/api_access.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    access_logger.addHandler(_handler)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

SAFE_SETTINGS = {
    "welcome_text", "btn_buy", "btn_test", "btn_contact", "btn_my_orders", "btn_referral",
    "btn_wallet", "test_enabled", "force_join_enabled", "force_join_channel",
    "card_to_card_enabled", "currency_rate", "brand_name", "shop_name",
}


def _auth(request: Request, token: Optional[str], required_scope: str = "read") -> dict:
    if not token:
        raise HTTPException(401, api_message("توکن در هدر الزامی است."))
    row = db.get_mobile_token_by_hash(hash_token(token))
    if not row:
        raise HTTPException(401, api_message("توکن نامعتبر است یا لغو شده است."))
    request.state.token_id = row["id"]
    request.state.admin_id = row["admin_id"]
    retry_after = limiter.check(row["id"])
    if retry_after:
        raise HTTPException(429, api_message("محدودیت درخواست رد شده است."), headers={"Retry-After": str(retry_after)})
    scope = row["scope"] if "scope" in row.keys() else "read"
    if not has_scope(scope, required_scope):
        raise HTTPException(403, api_message(f"مجوز لازم وجود ندارد: {required_scope}"))
    db.touch_mobile_token(row["id"])
    return {"id": row["id"], "admin_id": row["admin_id"], "scope": scope}


def _require(auth: dict, scope: str) -> None:
    if not has_scope(auth["scope"], scope):
        raise HTTPException(403, api_message(f"مجوز لازم وجود ندارد: {scope}"))


@app.middleware("http")
async def access_log(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.rstrip("/") == "/api":
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        ip = forwarded or (request.client.host if request.client else "-")
        state = request.state
        access_logger.info(
            "%s %s ip=%s token=%s admin=%s action=%s status=%s",
            request.method, request.url.path, ip,
            getattr(state, "token_id", "-"), getattr(state, "admin_id", "-"),
            getattr(state, "action", "-"), response.status_code,
        )
    return response


def _response(obj=None, msg="ok", status=True, **extra):
    return {"status": status, "msg": msg, "obj": obj, **extra}


@app.get("/api", tags=["meta"])
async def api_meta(request: Request, Token: Optional[str] = Header(default=None)):
    _auth(request, Token)
    return _response({"version": app.version, "docs": "/api/docs", "actions": [
        "users", "orders", "payments", "products", "panels", "categories", "discounts", "settings"
    ]})


@app.get("/api/index.html", response_class=HTMLResponse, include_in_schema=False)
async def api_docs_page():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.post("/api", tags=["actions"])
async def actions(request: Request, payload: Dict[str, Any], Token: Optional[str] = Header(default=None)):
    action = str(payload.get("action") or payload.get("actions") or "").strip().lower()
    limit, offset = pagination(payload.get("limit", 50), payload.get("offset", 0))
    auth = _auth(request, Token, "read")
    request.state.action = action

    # /token2 فقط توکن read/users/orders می‌دهد. این مسیر عمداً guarded است تا
    # یک read-only token هرگز نتواند سفارش را تایید یا تغییر دهد.
    if action in {"order_confirm", "order_approve", "order_reject"}:
        if not has_scope(auth["scope"], "orders:write"):
            raise HTTPException(403, api_message("توکن فقط خواندنی نمی‌تواند سفارش‌ها را تغییر دهد."))
        raise HTTPException(501, api_message("عملیات نوشتن سفارش در API عمومی غیرفعال است."))

    if action in {"users", "user_get", "user_list"}:
        _require(auth, "users")
        uid = payload.get("id") or payload.get("telegram_id")
        if action == "user_get" or uid:
            row = await asyncio.to_thread(db.get_user, int(uid))
            return _response(safe_row(row, ["id", "telegram_id", "username", "first_name", "is_blocked", "test_used", "joined_at"]))
        rows, total = await asyncio.to_thread(db.search_users, payload.get("q", ""), "all", limit, offset)
        return _response([safe_row(r, ["id", "telegram_id", "username", "first_name", "is_blocked", "joined_at"]) for r in rows], total=total, limit=limit, offset=offset)

    if action in {"orders", "order_list"}:
        _require(auth, "orders")
        user_id = payload.get("user_id")
        if user_id:
            rows = await asyncio.to_thread(db.get_user_orders, int(user_id))
            rows = rows[offset:offset + limit]
        else:
            with db._get_conn() as conn:
                rows = conn.execute(
                    "SELECT o.id,o.user_id,o.product_id,o.status,o.base_price,o.final_price,o.discount_amount,o.quantity,o.created_at "
                    "FROM orders o ORDER BY o.id DESC LIMIT ? OFFSET ?", (limit, offset)
                ).fetchall()
        return _response([safe_row(r) for r in rows], limit=limit, offset=offset)

    if action in {"payments", "payment_list"}:
        _require(auth, "orders")
        user_id = payload.get("user_id")
        with db._get_conn() as conn:
            if user_id:
                rows = conn.execute("SELECT id,user_id,amount,status,receipt_type,created_at FROM wallet_topups WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (int(user_id), limit, offset)).fetchall()
            else:
                rows = conn.execute("SELECT id,user_id,amount,status,receipt_type,created_at FROM wallet_topups ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return _response([safe_row(r) for r in rows], limit=limit, offset=offset)

    if action in {"products", "product_list"}:
        rows = await asyncio.to_thread(db.get_all_products)
        rows = rows[offset:offset + limit]
        return _response([safe_row(r, ["id", "name", "category_id", "category_name", "price", "duration_days", "description", "is_active", "is_auto_provision", "provision_server_id"]) for r in rows], limit=limit, offset=offset)

    if action in {"panels", "panel_list"}:
        rows = await asyncio.to_thread(db.get_panel_servers, True, False)
        return _response([safe_row(r, ["id", "name", "panel_type", "is_active", "capacity", "used_for_test_config", "used_for_custom_config"]) for r in rows[offset:offset + limit]], limit=limit, offset=offset)

    if action in {"categories", "category_list"}:
        rows = await asyncio.to_thread(db.get_categories, True)
        return _response([safe_row(r) for r in rows[offset:offset + limit]], limit=limit, offset=offset)

    if action in {"discounts", "discount_list"}:
        rows = await asyncio.to_thread(db.list_discount_codes)
        return _response([safe_row(r, ["id", "code", "percent", "amount", "expires_at", "min_purchase", "max_purchase", "product_id", "category_id", "per_user_limit", "first_purchase_only", "audience"]) for r in rows[offset:offset + limit]], limit=limit, offset=offset)

    if action in {"settings", "setting_get"}:
        key = payload.get("key")
        if key:
            if key not in SAFE_SETTINGS:
                raise HTTPException(403, api_message("این تنظیم از طریق API عمومی قابل دسترسی نیست."))
            return _response({key: await asyncio.to_thread(db.get_setting, key, "")})
        result = {k: await asyncio.to_thread(db.get_setting, k, "") for k in SAFE_SETTINGS}
        return _response(result)

    raise HTTPException(400, api_message("عملیات ناشناخته است."))
