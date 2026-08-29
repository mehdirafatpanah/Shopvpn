# -*- coding: utf-8 -*-
"""
پنل مدیریت وب کاملاً مستقل ShopVPN - خارج از تلگرام.

لاگین با یوزرنیم/پسورد (نه initData). روی دیتابیس بات اصلی کار می‌کند.
اجرا: uvicorn admin_panel.server:app --host 127.0.0.1 --port 8002
اولین حساب (owner) را با دستور زیر بساز:
    python -m admin_panel.create_admin <username> <password>
"""

import asyncio
import contextvars
import hmac
import json
import logging
import os
import sqlite3
import time
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Response, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import DB_PATH, BOT_TOKEN, OWNER_ID, ADMIN_PANEL_SECRET, VAPID_PUBLIC_KEY, resolve_db_path, API_BASE_URL
from database import Database, WEB_ADMIN_PERMISSIONS, MENU_BUTTON_META
from admin_panel.security import hash_password, verify_password, create_session_token, verify_session_token
from admin_panel.telegram_notify import send_message as tg_send, send_document as tg_send_document, fetch_telegram_file
from admin_panel.config_delivery_web import deliver_config_to_user_web
from admin_panel.webpush import PUSH_ENABLED, send_push
from reseller_auto_provision import provision_auto_config, ProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from stock_alerts import check_and_notify_low_stock
from panel_providers import (
    get_provider, PanelError, PanelUsernameTakenError, PANEL_TYPE_LABELS,
    PROVIDERS, SUB_BASE_URL_PANEL_TYPES, INBOUND_SELECT_PANEL_TYPES, TEMPLATE_BASED_PANEL_TYPES,
)
from renewal_reminders import STATUS_KEY_LAST_RUN, STATUS_KEY_LAST_DATE_SENT, STATUS_KEY_LAST_VOLUME_SENT
from backup import create_backup, restore_backup, is_valid_sqlite_db
import exchange_rate
import geo_scan
import world_map
import payment_engine

logger = logging.getLogger("admin_panel.server")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_NAME = "panel_session"
NOTIFY_POLL_SECONDS = 15

app = FastAPI(title="ShopVPN Admin Panel")
main_db = Database(DB_PATH)
main_db.init_db(owner_id=OWNER_ID)

# --------------------------------------------------------- multi-tenancy --
# پنل وب یک instance واحد است که هم بات اصلی و هم نماینده‌های «کامل» را سرو
# می‌کند. تننت جاری (دیتابیس + توکن بات + مسیر بکاپ) از payload توکن نشستِ
# لاگین‌شده استخراج و در یک contextvar برای طول همان درخواست نگه داشته می‌شود؛
# متغیرهای ماژول‌سطح db/BOT_TOKEN/BACKUP_DIR که کدِ قبلاً تک‌تننتی همه‌جا با
# آن‌ها کار می‌کند، بدون تغییر باقی می‌مانند ولی حالا به این contextvar وصل‌اند
# تا نیازی به بازنویسی تک‌تک endpointها نباشد.


@dataclass
class Tenant:
    slug: str          # "" یعنی بات اصلی
    bot_id: Optional[int]
    db: Database
    db_path: str
    bot_token: str
    backup_dir: str


MAIN_TENANT = Tenant(
    slug="", bot_id=None, db=main_db, db_path=DB_PATH, bot_token=BOT_TOKEN,
    backup_dir=os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups"),
)

_current_tenant: contextvars.ContextVar[Tenant] = contextvars.ContextVar("current_tenant", default=MAIN_TENANT)


class _TenantDBProxy:
    """پروکسی شفاف که `db.xxx()` را به دیتابیسِ تننتِ جاریِ درخواست هدایت می‌کند."""

    def __getattr__(self, name):
        return getattr(_current_tenant.get().db, name)


db = _TenantDBProxy()


def _bot_token() -> str:
    return _current_tenant.get().bot_token


def _backup_dir() -> str:
    return _current_tenant.get().backup_dir


def _lookup_reseller_bot_row(b: str):
    b = (b or "").strip()
    if not b:
        return None
    return main_db.get_reseller_bot(int(b)) if b.isdigit() else main_db.get_reseller_bot_by_slug(b)


def resolve_tenant_by_slug(slug: str) -> Optional[Tenant]:
    """فقط نماینده‌های «سطح ۱ (کامل)» که پنل وبشان صریحاً فعال شده اجازه‌ی
    ورود دارند؛ نماینده‌ی سطح ۲ یا غیرفعال، حتی با اسلاگ درست هم رد می‌شود.
    مثل مینی‌اپ، هم اسلاگ دلخواه و هم آیدی عددی بات (وقتی هنوز اسلاگ ست نشده) قبول می‌شود."""
    slug = (slug or "").strip()
    if not slug:
        return MAIN_TENANT
    row = _lookup_reseller_bot_row(slug)
    if not row:
        return None
    if not row["is_active"] or not row["web_panel_enabled"]:
        return None
    level = row["reseller_level"] if "reseller_level" in row.keys() else 2
    if level != 1:
        return None
    resolved_path = resolve_db_path(row["db_path"])
    if not os.path.exists(resolved_path):
        return None
    return Tenant(
        slug=slug, bot_id=row["id"], db=Database(resolved_path), db_path=resolved_path,
        bot_token=row["bot_token"], backup_dir=os.path.join(os.path.dirname(resolved_path), "backups"),
    )

# ---------------------------------------------------- live push notifier --
# یک تسک پس‌زمینه‌ی سبک که هر چند ثانیه دیتابیس را برای سفارش/شارژ/تیکت جدید
# چک می‌کند و برای ادمین‌های مربوطه Push می‌فرستد؛ چون پنل وب مستقل است و
# instance ای از بات در اختیار ندارد، این ساده‌ترین راه برای تشخیص «جدید بودن»
# یک رکورد بدون دست‌کاری کد بات اصلی است. اگر کلیدهای VAPID تنظیم نشده باشند
# (PUSH_ENABLED=False) این تسک اصلاً استارت نمی‌شود.


async def _notify_admins(permission: str, payload: dict):
    subs = (await asyncio.to_thread(db.list_push_subscriptions_for_permission, permission))
    if not subs:
        return
    gone = []
    for s in subs:
        result = await send_push(s, payload)
        if result == "gone":
            gone.append(s["endpoint"])
    if gone:
        (await asyncio.to_thread(db.delete_push_subscriptions_by_endpoints, gone))


async def _notifier_loop():
    init_orders = (await asyncio.to_thread(db.get_pending_orders))
    init_topups = (await asyncio.to_thread(db.get_pending_topups))
    init_tickets = (await asyncio.to_thread(db.get_all_tickets, "open"))
    last_order_id = max((o["id"] for o in init_orders), default=0)
    last_topup_id = max((t["id"] for t in init_topups), default=0)
    last_ticket_id = max((t["id"] for t in init_tickets), default=0)
    last_support_id = (await asyncio.to_thread(db.get_latest_user_support_message_id))
    while True:
        try:
            all_pending_orders = (await asyncio.to_thread(db.get_pending_orders))
            orders = [o for o in all_pending_orders if o["id"] > last_order_id]
            for o in orders:
                user = (await asyncio.to_thread(db.get_user, o["user_id"]))
                uname = (user["username"] if user else None) or o["user_id"]
                await _notify_admins("orders", {
                    "title": "🛒 سفارش جدید",
                    "body": f"سفارش #{o['id']} از {uname} در انتظار بررسی است.",
                    "tag": "orders",
                })
            if orders:
                last_order_id = max(o["id"] for o in orders)

            all_pending_topups = (await asyncio.to_thread(db.get_pending_topups))
            topups = [t for t in all_pending_topups if t["id"] > last_topup_id]
            for t in topups:
                user = (await asyncio.to_thread(db.get_user, t["user_id"]))
                uname = (user["username"] if user else None) or t["user_id"]
                await _notify_admins("orders", {
                    "title": "💳 درخواست شارژ جدید",
                    "body": f"شارژ #{t['id']} از {uname} به مبلغ {t['amount']:,} تومان.",
                    "tag": "topups",
                })
            if topups:
                last_topup_id = max(t["id"] for t in topups)

            all_open_tickets = (await asyncio.to_thread(db.get_all_tickets, "open"))
            tickets = [tk for tk in all_open_tickets if tk["id"] > last_ticket_id]
            for tk in tickets:
                await _notify_admins("tickets", {
                    "title": "🎫 تیکت جدید",
                    "body": f"تیکت #{tk['id']}: {tk['subject']}",
                    "tag": "tickets",
                })
            if tickets:
                last_ticket_id = max(tk["id"] for tk in tickets)

            latest_support_id = (await asyncio.to_thread(db.get_latest_user_support_message_id))
            if latest_support_id > last_support_id:
                new_msgs = (await asyncio.to_thread(db.get_new_support_messages_since, last_support_id))
                for m in new_msgs:
                    user = (await asyncio.to_thread(db.get_user, m["user_id"]))
                    uname = (user["username"] if user else None) or (user["first_name"] if user else None) or m["user_id"]
                    preview = (m["message"] or "")[:120]
                    await _notify_admins("tickets", {
                        "title": "💬 پیام جدید در چت زنده",
                        "body": f"{uname}: {preview}",
                        "tag": "support",
                    })
                last_support_id = latest_support_id
        except Exception:
            logger.exception("خطا در حلقه‌ی اعلان زنده‌ی پنل وب")
        await asyncio.sleep(NOTIFY_POLL_SECONDS)


# ------------------------------------------------------ server status watch --
# هر چند دقیقه (قابل‌تنظیم از پنل، کلید تنظیمات server_check_interval_min)
# کانفیگ‌های «لینک ساب مادر» را دوباره اسکن می‌کند (همان منطق دکمه‌ی «اسکن
# مجدد» نقشه‌ی جهانی سرورها) و اگر کانفیگی که قبلاً آنلاین/نامشخص بوده حالا
# آفلاین شده، یک Push می‌فرستد. برای جلوگیری از اسپم، هر کانفیگ فقط یک‌بار
# در لحظه‌ی *تغییر* وضعیت به آفلاین اعلان می‌گیرد، نه هر بار که هنوز آفلاین
# است؛ وقتی دوباره آنلاین شود هم یک اعلان بازیابی می‌فرستد.

# مقادیر پیش‌فرض وقتی هنوز از پنل چیزی تنظیم نشده باشد، و بازه‌ی مجاز برای
# جلوگیری از مقادیر بی‌معنی (مثلاً صفر یا خیلی بزرگ) وارد شده از پنل.
DEFAULT_SERVER_CHECK_INTERVAL_MIN = 3
DEFAULT_SERVER_OFFLINE_STREAK = 2
_MIN_CHECK_INTERVAL_MIN = 1
_MAX_CHECK_INTERVAL_MIN = 120
_MIN_OFFLINE_STREAK = 1
_MAX_OFFLINE_STREAK = 10


def _get_server_check_interval_seconds() -> int:
    try:
        minutes = int(db.get_setting("server_check_interval_min", str(DEFAULT_SERVER_CHECK_INTERVAL_MIN)))
    except (TypeError, ValueError):
        minutes = DEFAULT_SERVER_CHECK_INTERVAL_MIN
    minutes = max(_MIN_CHECK_INTERVAL_MIN, min(_MAX_CHECK_INTERVAL_MIN, minutes))
    return minutes * 60


def _get_server_offline_streak_threshold() -> int:
    try:
        streak = int(db.get_setting("server_offline_streak", str(DEFAULT_SERVER_OFFLINE_STREAK)))
    except (TypeError, ValueError):
        streak = DEFAULT_SERVER_OFFLINE_STREAK
    return max(_MIN_OFFLINE_STREAK, min(_MAX_OFFLINE_STREAK, streak))


async def _server_status_loop():
    # یک بار آفلاین دیدن TCP لزوماً یعنی سرور واقعاً قطعه؛ ممکنه جیتر لحظه‌ای
    # شبکه باشه. پس فقط وقتی یه کانفیگ چند دور متوالی (تعدادش از پنل قابل‌تنظیم
    # است) پشت‌سرهم آفلاین دیده بشه پوش قطعی می‌فرستیم؛ به‌محضی که یه دور
    # آنلاین ببینیم استریک ریست می‌شه. هر دو تنظیم (بازه‌ی هر دور اسکن و تعداد
    # دور لازم) در هر iteration از دیتابیس خوانده می‌شوند تا بدون ری‌استارت
    # سرویس قابل تغییر باشند.
    offline_streak: dict[str, int] = {}
    notified_offline: set[str] = set()
    while True:
        interval_seconds = _get_server_check_interval_seconds()
        try:
            streak_needed = _get_server_offline_streak_threshold()
            link = (await asyncio.to_thread(db.get_setting, "master_sub_link", "")).strip()
            if link:
                result = await geo_scan.scan_subscription(
                    link,
                    force_refresh=True,
                    check_status=True,
                    tcp_timeout=geo_scan.TCP_TIMEOUT_BACKGROUND,
                )
                if result.get("ok"):
                    current: dict[str, str] = {}
                    for s in result.get("servers", []):
                        key = s.get("remark") or s.get("ip") or ""
                        if not key:
                            continue
                        current[key] = s.get("status", "unknown")

                    for key, status in current.items():
                        if status == "offline":
                            offline_streak[key] = offline_streak.get(key, 0) + 1
                            if offline_streak[key] >= streak_needed and key not in notified_offline:
                                await _notify_admins("panels", {
                                    "title": "🔴 قطعی کانفیگ",
                                    "body": f"کانفیگ «{key}» آفلاین شده است.",
                                    "tag": f"server-status-{key}",
                                })
                                notified_offline.add(key)
                        else:
                            offline_streak[key] = 0
                            if status == "online" and key in notified_offline:
                                await _notify_admins("panels", {
                                    "title": "🟢 اتصال مجدد کانفیگ",
                                    "body": f"کانفیگ «{key}» دوباره آنلاین شد.",
                                    "tag": f"server-status-{key}",
                                })
                                notified_offline.discard(key)
        except Exception:
            logger.exception("خطا در حلقه‌ی بررسی وضعیت سرورها")
        await asyncio.sleep(interval_seconds)


@app.on_event("startup")
async def _start_notifier():
    if PUSH_ENABLED:
        asyncio.create_task(_notifier_loop())
        asyncio.create_task(_notifier_supervisor())
        asyncio.create_task(_server_status_loop())


# --------------------------------- اعلان زنده برای پنل نماینده‌های کامل --
# چون پنل وب یک پروسه‌ی جدا (systemd سرویس دیگر) است، فعال/غیرفعال شدن پنل
# یک نماینده از داخل بات بلافاصله به این پروسه اطلاع داده نمی‌شود؛ به‌جایش
# این supervisor هر ۲ دقیقه لیست نماینده‌های «کامل و فعال با پنل وب روشن» را
# از main_db می‌خواند و برای هرکدام یک تسک _notifier_loop مستقل (روی
# دیتابیس خودشان) نگه می‌دارد؛ با غیرفعال‌شدن پنل، تسک مربوطه هم کنسل می‌شود.

_tenant_notifier_tasks: dict[str, asyncio.Task] = {}


async def _run_tenant_notifier_loop(tenant: "Tenant"):
    _current_tenant.set(tenant)
    await asyncio.gather(_notifier_loop(), _server_status_loop())


async def _notifier_supervisor():
    while True:
        try:
            active_slugs = set()
            for row in (await asyncio.to_thread(main_db.list_reseller_bots, active_only=True)):
                level = row["reseller_level"] if "reseller_level" in row.keys() else 2
                enabled = bool(row["web_panel_enabled"]) if "web_panel_enabled" in row.keys() else False
                if level != 1 or not enabled:
                    continue
                resolved_path = resolve_db_path(row["db_path"])
                if not os.path.exists(resolved_path):
                    continue
                slug = row["link_slug"] or str(row["id"])
                active_slugs.add(slug)
                if slug in _tenant_notifier_tasks:
                    continue
                tenant = Tenant(
                    slug=slug, bot_id=row["id"], db=Database(resolved_path), db_path=resolved_path,
                    bot_token=row["bot_token"], backup_dir=os.path.join(os.path.dirname(resolved_path), "backups"),
                )
                _tenant_notifier_tasks[slug] = asyncio.create_task(_run_tenant_notifier_loop(tenant))
                logger.info("اعلان زنده‌ی پنل وب برای نماینده‌ی %s فعال شد.", slug)

            for slug in list(_tenant_notifier_tasks.keys()):
                if slug not in active_slugs:
                    _tenant_notifier_tasks.pop(slug).cancel()
                    logger.info("اعلان زنده‌ی پنل وب برای نماینده‌ی %s متوقف شد.", slug)
        except Exception:
            logger.exception("خطا در supervisor اعلان زنده‌ی نماینده‌ها")
        await asyncio.sleep(120)


# ------------------------------------------------------------------ auth --


class LoginBody(BaseModel):
    username: str
    password: str
    b: Optional[str] = None  # اسلاگ نماینده؛ خالی/غایب یعنی بات اصلی


async def get_current_admin(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    payload = verify_session_token(ADMIN_PANEL_SECRET, token) if token else None
    if not payload:
        raise HTTPException(401, "نشست منقضی شده یا نامعتبر است.")

    # تننت همیشه از خودِ توکن امضاشده خوانده می‌شود، نه از کوئری URL؛ وگرنه
    # کسی با یک session کوکی معتبر می‌توانست با عوض‌کردن ?b= به دیتابیس تننت
    # دیگری دسترسی بگیرد.
    tenant = resolve_tenant_by_slug(payload.get("b", ""))
    if not tenant:
        raise HTTPException(401, "پنل وب این نماینده دیگر فعال نیست.")
    _current_tenant.set(tenant)

    admin = (await asyncio.to_thread(tenant.db.get_web_admin, payload["id"]))
    if not admin or not admin["is_active"]:
        raise HTTPException(401, "حساب کاربری غیرفعال یا حذف شده است.")
    return {
        "id": admin["id"],
        "username": admin["username"],
        "role": admin["role"],
        "permissions": (await asyncio.to_thread(tenant.db.get_web_admin_permissions, admin)),
        "tenant": tenant.slug,
    }


# مجوزهایی که حتی برای owner پنل یک نماینده هم معنی ندارند (مثلاً «نمایندگی‌ها»:
# پنل وب نماینده‌ی سطح ۱ نباید بتواند نماینده‌های خودش را مدیریت کند).
MAIN_TENANT_ONLY_PERMISSIONS = {"resellers"}


def require_permission(permission: str):
    def _dep(admin=Depends(get_current_admin)):
        if permission in MAIN_TENANT_ONLY_PERMISSIONS and admin["tenant"]:
            raise HTTPException(403, "این بخش فقط در پنل بات اصلی در دسترس است.")
        if admin["role"] != "owner" and permission not in admin["permissions"]:
            raise HTTPException(403, "دسترسی کافی نیست.")
        return admin
    return _dep


def require_owner(admin=Depends(get_current_admin)):
    if admin["role"] != "owner":
        raise HTTPException(403, "این بخش فقط برای مالک است.")
    return admin


def require_main_tenant(admin=Depends(get_current_admin)):
    """برای بخش‌هایی که حتی برای owner پنل نماینده هم معنی ندارند (مثلاً منابع سخت‌افزاری سرور)."""
    if admin["tenant"]:
        raise HTTPException(403, "این بخش فقط در پنل بات اصلی در دسترس است.")
    return admin


@app.post("/api/login")
def api_login(body: LoginBody, response: Response):
    tenant = resolve_tenant_by_slug(body.b or "")
    if not tenant:
        raise HTTPException(401, "این پنل در دسترس نیست.")
    admin = tenant.db.get_web_admin_by_username(body.username)
    if not admin or not admin["is_active"] or not verify_password(body.password, admin["password_hash"]):
        raise HTTPException(401, "یوزرنیم یا پسورد اشتباه است.")
    token = create_session_token(
        ADMIN_PANEL_SECRET, admin["id"], admin["username"], admin["role"], tenant=tenant.slug,
    )
    tenant.db.touch_web_admin_login(admin["id"])
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", max_age=12 * 3600, path="/",
    )
    return {"id": admin["id"], "username": admin["username"], "role": admin["role"], "tenant": tenant.slug}


@app.post("/api/logout")
def api_logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


# ------------------------------------------------------- reseller web panel setup --
# مسیرِ یک‌بارمصرفی که نماینده‌ی «کامل» بعد از این‌که مدیر اصلی از داخل بات
# «فعالسازی پنل وب» را زد، برای اولین‌بار یوزرنیم/پسورد خودش را ست می‌کند.
# بعد از اولین حساب owner در دیتابیس همان نماینده، توکن باطل می‌شود.


class SetupBody(BaseModel):
    b: str
    t: str
    username: str
    password: str


@app.get("/api/setup/info")
def api_setup_info(b: str, t: str):
    row = _lookup_reseller_bot_row(b)
    if not row or not row["web_panel_enabled"] or not row["web_panel_setup_token"]:
        raise HTTPException(404, "لینک راه‌اندازی نامعتبر یا منقضی‌شده است.")
    if not hmac.compare_digest(row["web_panel_setup_token"], t):
        raise HTTPException(404, "لینک راه‌اندازی نامعتبر یا منقضی‌شده است.")
    tenant_db = Database(resolve_db_path(row["db_path"]))
    if tenant_db.count_web_admins() > 0:
        raise HTTPException(400, "پنل این نماینده قبلاً راه‌اندازی شده؛ از صفحه‌ی ورود استفاده کن.")
    return {"bot_username": row["bot_username"] or "", "owner_name": row["owner_name"] or ""}


@app.post("/api/setup")
def api_setup_submit(body: SetupBody, response: Response):
    row = _lookup_reseller_bot_row(body.b)
    if not row or not row["web_panel_enabled"] or not row["web_panel_setup_token"]:
        raise HTTPException(404, "لینک راه‌اندازی نامعتبر یا منقضی‌شده است.")
    if not hmac.compare_digest(row["web_panel_setup_token"], body.t):
        raise HTTPException(404, "لینک راه‌اندازی نامعتبر یا منقضی‌شده است.")

    username = (body.username or "").strip().lower()
    if len(username) < 3:
        raise HTTPException(400, "یوزرنیم باید حداقل ۳ کاراکتر باشد.")
    if len(body.password or "") < 8:
        raise HTTPException(400, "پسورد باید حداقل ۸ کاراکتر باشد.")

    tenant_db = Database(resolve_db_path(row["db_path"]))
    if tenant_db.count_web_admins() > 0:
        raise HTTPException(400, "پنل این نماینده قبلاً راه‌اندازی شده؛ از صفحه‌ی ورود استفاده کن.")
    if tenant_db.get_web_admin_by_username(username):
        raise HTTPException(400, "این یوزرنیم قبلاً استفاده شده.")

    admin_id = tenant_db.create_web_admin(username, hash_password(body.password), role="owner")
    main_db.consume_reseller_web_panel_setup_token(row["id"])

    tenant_slug = row["link_slug"] or str(row["id"])
    token = create_session_token(ADMIN_PANEL_SECRET, admin_id, username, "owner", tenant=tenant_slug)
    tenant_db.touch_web_admin_login(admin_id)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=12 * 3600, path="/")
    return {"id": admin_id, "username": username, "role": "owner", "tenant": tenant_slug}


@app.get("/api/me")
def api_me(admin=Depends(get_current_admin)):
    return admin


@app.get("/api/notifications/summary")
def api_notifications_summary(admin=Depends(get_current_admin)):
    """شمارش موارد در انتظار برای بج‌های زنده‌ی منو (سفارش/شارژ/تیکت/چت زنده).
    چت زنده مثل تب خودش (role: 'any' در NAV) برای هر ادمین لاگین‌کرده‌ای نمایش
    داده می‌شود، چون خودِ endpointهای /api/support هم به مجوز خاصی گیر نخورده‌اند."""
    out = {}
    if admin["role"] == "owner" or "orders" in admin["permissions"]:
        out["orders"] = len(db.get_pending_orders())
        out["topups"] = len(db.get_pending_topups())
    if admin["role"] == "owner" or "tickets" in admin["permissions"]:
        out["tickets"] = len(db.get_all_tickets("open"))
    out["support"] = db.count_unread_support_conversations()
    return out


# -------------------------------------------------------------- web push --


class PushSubscribeBody(BaseModel):
    endpoint: str
    keys: dict
    user_agent: Optional[str] = None


class PushUnsubscribeBody(BaseModel):
    endpoint: str


@app.get("/api/push/vapid-public-key")
def api_push_vapid_key(admin=Depends(get_current_admin)):
    return {"publicKey": VAPID_PUBLIC_KEY, "enabled": PUSH_ENABLED}


@app.get("/api/push/status")
def api_push_status(endpoint: str, admin=Depends(get_current_admin)):
    """بررسی می‌کند آیا این endpoint واقعاً برای همین ادمین در دیتابیس ذخیره شده یا نه
    (برای تشخیص حالتی که subscription محلی مرورگر با دیتابیس سرور ناهماهنگ شده)."""
    subs = db.list_push_subscriptions_for_admin(admin["id"])
    registered = any(s["endpoint"] == endpoint for s in subs)
    return {"registered": registered}


@app.post("/api/push/subscribe")
def api_push_subscribe(body: PushSubscribeBody, admin=Depends(get_current_admin)):
    if not PUSH_ENABLED:
        raise HTTPException(400, "اعلان Push روی سرور تنظیم نشده است.")
    p256dh = (body.keys or {}).get("p256dh")
    auth = (body.keys or {}).get("auth")
    if not p256dh or not auth:
        raise HTTPException(400, "اطلاعات subscription ناقص است.")
    db.save_push_subscription(admin["id"], body.endpoint, p256dh, auth, body.user_agent)
    return {"ok": True}


@app.post("/api/push/unsubscribe")
def api_push_unsubscribe(body: PushUnsubscribeBody, admin=Depends(get_current_admin)):
    db.delete_push_subscription_by_endpoint(body.endpoint)
    return {"ok": True}


@app.post("/api/push/test")
async def api_push_test(admin=Depends(get_current_admin)):
    if not PUSH_ENABLED:
        raise HTTPException(400, "اعلان Push روی سرور تنظیم نشده است.")
    subs = (await asyncio.to_thread(db.list_push_subscriptions_for_admin, admin["id"]))
    if not subs:
        raise HTTPException(400, "هنوز روی این دستگاه اعلان را فعال نکرده‌ای.")
    sent, gone = 0, []
    for s in subs:
        result = await send_push(s, {
            "title": "🔔 اعلان تست",
            "body": "این یک پیام آزمایشی از پنل مدیریت ShopVPN است.",
            "tag": "test",
        })
        if result == "ok":
            sent += 1
        elif result == "gone":
            gone.append(s["endpoint"])
    if gone:
        (await asyncio.to_thread(db.delete_push_subscriptions_by_endpoints, gone))
    if not sent:
        raise HTTPException(502, "ارسال اعلان تست ناموفق بود.")
    return {"ok": True, "sent": sent}


# --------------------------------------------------------------- helpers --


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


async def notify_user(chat_id: int, text: str):
    asyncio.create_task(tg_send(_bot_token(), chat_id, text))


# --------------------------------------------------------------- dashboard --


@app.get("/api/dashboard")
def api_dashboard(start: Optional[str] = None, end: Optional[str] = None, admin=Depends(get_current_admin)):
    return db.get_full_stats(start, end)


# ------------------------------------------------------------- servers map --
# نقشه‌ی جهان در داشبورد: بر اساس یک «لینک ساب مادر» که ادمین وارد می‌کند،
# کانفیگ‌های داخلش پارس و آدرس هرکدام جئولوکیت می‌شود.

class MasterSubBody(BaseModel):
    link: str


@app.get("/api/settings/master-sub")
def api_get_master_sub(admin=Depends(get_current_admin)):
    return {"link": db.get_setting("master_sub_link", "")}


@app.post("/api/settings/master-sub")
def api_set_master_sub(body: MasterSubBody, admin=Depends(require_permission("settings"))):
    link = (body.link or "").strip()
    if link and not (link.startswith("http://") or link.startswith("https://")):
        raise HTTPException(400, "لینک ساب باید با http:// یا https:// شروع شود.")
    db.set_setting("master_sub_link", link)
    return {"ok": True}


class ServerCheckSettingsBody(BaseModel):
    interval_min: int
    offline_streak: int


@app.get("/api/settings/server-check")
def api_get_server_check_settings(admin=Depends(get_current_admin)):
    return {
        "interval_min": int(db.get_setting("server_check_interval_min", str(DEFAULT_SERVER_CHECK_INTERVAL_MIN))),
        "offline_streak": int(db.get_setting("server_offline_streak", str(DEFAULT_SERVER_OFFLINE_STREAK))),
        "min_interval_min": _MIN_CHECK_INTERVAL_MIN,
        "max_interval_min": _MAX_CHECK_INTERVAL_MIN,
        "min_offline_streak": _MIN_OFFLINE_STREAK,
        "max_offline_streak": _MAX_OFFLINE_STREAK,
    }


@app.post("/api/settings/server-check")
def api_set_server_check_settings(body: ServerCheckSettingsBody, admin=Depends(require_permission("settings"))):
    if not (_MIN_CHECK_INTERVAL_MIN <= body.interval_min <= _MAX_CHECK_INTERVAL_MIN):
        raise HTTPException(400, f"بازه‌ی هر دور اسکن باید بین {_MIN_CHECK_INTERVAL_MIN} تا {_MAX_CHECK_INTERVAL_MIN} دقیقه باشد.")
    if not (_MIN_OFFLINE_STREAK <= body.offline_streak <= _MAX_OFFLINE_STREAK):
        raise HTTPException(400, f"تعداد دور متوالی باید بین {_MIN_OFFLINE_STREAK} تا {_MAX_OFFLINE_STREAK} باشد.")
    db.set_setting("server_check_interval_min", str(body.interval_min))
    db.set_setting("server_offline_streak", str(body.offline_streak))
    db.log_admin_action(
        admin["id"], "setting_change",
        f"server_check_interval_min={body.interval_min}, server_offline_streak={body.offline_streak} (پنل وب - {admin['username']})",
        "setting", "server_check",
    )
    return {"ok": True}


@app.get("/api/dashboard/servers-map")
async def api_dashboard_servers_map(refresh: bool = False, admin=Depends(get_current_admin)):
    link = (await asyncio.to_thread(db.get_setting, "master_sub_link", "")).strip()
    if not link:
        return {"ok": False, "error": "no_link"}
    return await geo_scan.scan_subscription(link, force_refresh=refresh)


@app.get("/api/dashboard/world-map")
async def api_dashboard_world_map(refresh: bool = False, admin=Depends(get_current_admin)):
    """خطوط ساحلی زمین برای پس‌زمینه‌ی نقشه — از خودِ سرور پنل serve می‌شود
    تا مرورگر ادمین دیگر لازم نباشد مستقیماً به CDNهای خارجی وصل شود."""
    return await world_map.get_world_map(force_refresh=refresh)


# ------------------------------------------------------------------ system --


@app.get("/api/system/stats")
def api_system_stats(admin=Depends(require_main_tenant)):
    """وضعیت لحظه‌ای منابع سرور (CPU / RAM / دیسک) - چون این منابع بین همه‌ی
    بات‌های میزبانی‌شده روی این سرور مشترک است، فقط در پنل بات اصلی نشان
    داده می‌شود (نه به نماینده‌ها)."""
    try:
        import psutil
    except ImportError:
        raise HTTPException(500, "psutil نصب نیست. دستور: pip install psutil")

    cpu_percent = psutil.cpu_percent(interval=0.3)
    cpu_count = psutil.cpu_count(logical=True) or 1

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    try:
        load1, load5, load15 = os.getloadavg()
    except (OSError, AttributeError):
        load1 = load5 = load15 = None

    return {
        "cpu": {
            "percent": round(cpu_percent, 1),
            "cores": cpu_count,
            "load1": load1, "load5": load5, "load15": load15,
        },
        "ram": {
            "percent": round(mem.percent, 1),
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "total_gb": round(mem.total / (1024 ** 3), 1),
        },
        "disk": {
            "percent": round(disk.percent, 1),
            "used_gb": round(disk.used / (1024 ** 3), 1),
            "total_gb": round(disk.total / (1024 ** 3), 1),
        },
    }


@app.get("/api/system/jobs")
def api_system_jobs(admin=Depends(require_permission("system"))):
    """وضعیت فقط‌خواندنیِ آخرین اجرای یادآوری‌های تمدید/حجم + وضعیت لحظه‌ای موجودی محصولات.
    زمان‌بندی این‌ها هاردکد است (renewal_reminder_loop در پردازش بات) و از اینجا قابل تغییر نیست."""
    return {
        "renewal": {
            "last_run": db.get_setting(STATUS_KEY_LAST_RUN, "") or None,
            "last_date_sent": int(db.get_setting(STATUS_KEY_LAST_DATE_SENT, "0") or 0),
            "last_volume_sent": int(db.get_setting(STATUS_KEY_LAST_VOLUME_SENT, "0") or 0),
        },
        "stock": db.get_low_stock_overview(),
    }


# ------------------------------------------------------------------ backup --

@app.get("/api/system/backup/status")
def api_backup_status(admin=Depends(require_permission("system"))):
    """آخرین وضعیت بکاپ‌ها؛ فقط‌خواندنی، برای نمایش در پنل."""
    backup_dir = _backup_dir()
    if not os.path.isdir(backup_dir):
        return {"last_backup_at": None, "last_backup_size_mb": None, "count": 0}
    files = sorted(
        (f for f in os.listdir(backup_dir) if f.endswith(".db") and not f.startswith("pre_restore_")),
    )
    if not files:
        return {"last_backup_at": None, "last_backup_size_mb": None, "count": 0}
    last_path = os.path.join(backup_dir, files[-1])
    return {
        "last_backup_at": db.get_setting("_job_backup_last_at", "") or None,
        "last_backup_size_mb": round(os.path.getsize(last_path) / (1024 * 1024), 1),
        "count": len(files),
    }


@app.post("/api/system/backup/create")
async def api_backup_create(admin=Depends(require_permission("backup"))):
    """یک بکاپ فوری می‌سازد و به همه‌ی ادمین‌های تلگرامی همین بات ارسال می‌کند."""
    tenant = _current_tenant.get()
    backup_path = await asyncio.to_thread(create_backup, tenant.db_path, _backup_dir(), 14)
    if not backup_path:
        raise HTTPException(404, "فایل دیتابیس پیدا نشد.")

    size_mb = round(os.path.getsize(backup_path) / (1024 * 1024), 1)
    caption = f"🗄 بکاپ فوری دیتابیس (پنل وب - {admin['username']})"

    sent, failed = 0, 0
    for admin_tg_id in (await asyncio.to_thread(db.list_admins)):
        ok = await tg_send_document(_bot_token(), admin_tg_id, backup_path, caption)
        sent += 1 if ok else 0
        failed += 0 if ok else 1

    (await asyncio.to_thread(db.set_setting, "_job_backup_last_at", datetime.now().isoformat()))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "backup_create",
        f"بکاپ فوری ساخته شد ({os.path.basename(backup_path)}, {size_mb} مگابایت) — ارسال به {sent} ادمین "
        f"(پنل وب - {admin['username']})",
    ))
    return {"ok": True, "filename": os.path.basename(backup_path), "size_mb": size_mb, "sent": sent, "failed": failed}


@app.post("/api/system/backup/restore")
async def api_backup_restore(
    file: UploadFile = File(...), confirm_phrase: str = Form(""), admin=Depends(require_owner)
):
    """جایگزینی کامل دیتابیس با فایل بکاپ آپلودشده. چون این کار overwrite کامل و
    غیرقابل‌برگشت (به‌جز با بکاپ دیگر) است، علاوه بر تاییدیه‌ی دوگانه‌ی فرانت‌اند،
    سمت سرور هم عبارت تاییدی «RESTORE» را الزامی می‌کند."""
    if confirm_phrase.strip().upper() != "RESTORE":
        raise HTTPException(400, "برای تایید بازیابی، عبارت RESTORE را دقیقاً وارد کن.")
    if not file.filename or not file.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(400, "فایل باید پسوند .db یا .sqlite داشته باشد.")

    tmp_dir = tempfile.mkdtemp(prefix="restore_")
    tmp_path = os.path.join(tmp_dir, "uploaded.db")
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    if not is_valid_sqlite_db(tmp_path):
        os.remove(tmp_path)
        os.rmdir(tmp_dir)
        raise HTTPException(400, "این فایل یک دیتابیس sqlite معتبر نیست.")

    try:
        pre_restore_path = await asyncio.to_thread(restore_backup, db, _current_tenant.get().db_path, tmp_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"بازیابی ناموفق بود: {e}")
    finally:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass

    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "backup_restore",
        f"دیتابیس از فایل آپلودی بازیابی شد؛ نسخه‌ی قبلی: {os.path.basename(pre_restore_path)} "
        f"(پنل وب - {admin['username']})",
    ))
    return {"ok": True, "pre_restore_backup": os.path.basename(pre_restore_path)}


# ------------------------------------------------------------------ orders --


@app.get("/api/orders")
def api_orders(status: str = "pending", admin=Depends(get_current_admin)):
    rows = db.get_pending_orders() if status == "pending" else db.get_orders_by_status(status)
    out = []
    for o in rows:
        o = dict(o)
        product = row_to_dict(db.get_product(o["product_id"])) if o["product_id"] else None
        user = row_to_dict(db.get_user(o["user_id"]))
        o["product_name"] = product["name"] if product else ("ساخت کانفیگ شخصی" if o.get("is_custom_config") else "-")
        o["username"] = user["username"] if user else None
        out.append(o)
    return out


@app.get("/api/orders/{order_id}/receipt")
async def api_order_receipt(order_id: int, admin=Depends(get_current_admin)):
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or not order["receipt_file_id"]:
        raise HTTPException(404, "رسیدی برای این سفارش ثبت نشده است.")
    result = await fetch_telegram_file(_bot_token(), order["receipt_file_id"])
    if not result:
        raise HTTPException(502, "دریافت رسید از تلگرام ناموفق بود.")
    content, content_type = result
    return Response(content=content, media_type=content_type)


@app.post("/api/orders/{order_id}/approve")
async def api_approve_order(order_id: int, admin=Depends(require_permission("orders"))):
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or order["status"] != "pending":
        raise HTTPException(400, "سفارش یافت نشد یا قبلاً بررسی شده.")

    if order["is_custom_config"]:
        server = (await asyncio.to_thread(db.get_panel_server, order["custom_panel_server_id"]))
        if not server or not server["is_active"]:
            raise HTTPException(400, "سرور پنل مربوطه یافت نشد یا غیرفعال است.")

        try:
            provider = get_provider(server)
            result = await provider.create_user(
                username=order["custom_username"],
                volume_gb=order["custom_volume_gb"],
                duration_days=(await asyncio.to_thread(db.get_custom_config_settings))["duration_days"],
            )
        except PanelUsernameTakenError:
            raise HTTPException(400, "این نام کاربری روی پنل تکراری است؛ از کاربر بخواه نام دیگری انتخاب کند.")
        except PanelError as e:
            raise HTTPException(400, f"خطا در ارتباط با پنل: {e}")

        (await asyncio.to_thread(db.approve_custom_config_order, order_id))
        (await asyncio.to_thread(db.add_custom_config, 
            user_id=order["user_id"],
            panel_server_id=server["id"],
            username=result.username,
            volume_gb=order["custom_volume_gb"],
            duration_days=db.get_custom_config_settings()["duration_days"],
            subscription_url=result.subscription_url,
            order_id=order_id,
        ))
        (await asyncio.to_thread(db.log_admin_action, 
            admin["id"], "order_approve",
            f"سفارش شخصی #{order_id} | کاربر {order['user_id']} | یوزرنیم «{result.username}» | "
            f"{order['custom_volume_gb']} گیگ | مبلغ: {order['final_price']:,} (پنل وب - {admin['username']})",
            "order", order_id,
        ))
        await notify_user(order["user_id"], "✅ کانفیگ شخصی شما ساخته شد!")
        asyncio.create_task(deliver_config_to_user_web(
            order["user_id"], "کانفیگ شخصی", result.subscription_url,
            final_price=order["final_price"], order_id=order_id, db=db, bot_token=_bot_token(),
        ))
        return {"ok": True}

    product = (await asyncio.to_thread(db.get_product, order["product_id"]))
    quantity = order["quantity"] or 1

    if product and product["is_auto_provision"]:
        try:
            if product["provision_server_id"]:
                results = await provision_direct(db, product, quantity)
            else:
                results = await provision_auto_config(db, product, quantity)
        except (ProvisionError, DirectProvisionError) as e:
            raise HTTPException(400, str(e))
        (await asyncio.to_thread(db.approve_order_auto, order_id))
        (await asyncio.to_thread(db.log_admin_action, 
            admin["id"], "order_approve",
            f"سفارش #{order_id} (خودکار) | کاربر {order['user_id']} | محصول «{product['name']}» (پنل وب - {admin['username']})",
            "order", order_id,
        ))
        links = [r["subscription_url"] for r in results]
        await notify_user(order["user_id"], "✅ خرید شما تایید شد!")
        asyncio.create_task(deliver_config_to_user_web(
            order["user_id"], product["name"], links,
            final_price=order["final_price"], order_id=order_id, db=db, bot_token=_bot_token(),
        ))
        return {"ok": True}

    results = (await asyncio.to_thread(db.take_unused_configs, order["product_id"], order["user_id"], quantity))
    if not results:
        raise HTTPException(400, "موجودی این محصول تمام شده است.")
    (await asyncio.to_thread(db.approve_order, order_id, [r["id"] for r in results]))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "order_approve",
        f"سفارش #{order_id} | کاربر {order['user_id']} | محصول «{product['name'] if product else '---'}» (پنل وب - {admin['username']})",
        "order", order_id,
    ))
    await check_and_notify_low_stock(lambda aid, text: tg_send(_bot_token(), aid, text), db, order["product_id"])
    (await asyncio.to_thread(db.reward_referrer_if_first_purchase, order["user_id"], order["final_price"] or (product["price"] if product else 0)))
    links = [r["link"] for r in results]
    await notify_user(order["user_id"], "✅ خرید شما تایید شد!")
    asyncio.create_task(deliver_config_to_user_web(
        order["user_id"], product["name"] if product else "", links,
        final_price=order["final_price"], order_id=order_id, db=db, bot_token=_bot_token(),
    ))
    return {"ok": True}


@app.post("/api/orders/{order_id}/reject")
async def api_reject_order(order_id: int, admin=Depends(require_permission("orders"))):
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or order["status"] != "pending":
        raise HTTPException(400, "سفارش یافت نشد یا قبلاً بررسی شده.")
    (await asyncio.to_thread(db.reject_order, order_id))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "order_reject", f"سفارش #{order_id} رد شد (پنل وب - {admin['username']})", "order", order_id))
    await notify_user(order["user_id"], "⛔️ سفارش شما رد شد. در صورت کسر از کیف پول، مبلغ برگشت داده شد.")
    return {"ok": True}


# ------------------------------------------------------------------ topups --


@app.get("/api/topups")
def api_topups(status: str = "pending", admin=Depends(get_current_admin)):
    rows = db.get_pending_topups() if status == "pending" else db.get_topups_by_status(status)
    out = []
    for t in rows:
        t = dict(t)
        user = row_to_dict(db.get_user(t["user_id"]))
        t["username"] = user["username"] if user else None
        out.append(t)
    return out


@app.get("/api/topups/{topup_id}/receipt")
async def api_topup_receipt(topup_id: int, admin=Depends(get_current_admin)):
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup or not topup["receipt_file_id"]:
        raise HTTPException(404, "رسیدی برای این شارژ ثبت نشده است.")
    result = await fetch_telegram_file(_bot_token(), topup["receipt_file_id"])
    if not result:
        raise HTTPException(502, "دریافت رسید از تلگرام ناموفق بود.")
    content, content_type = result
    return Response(content=content, media_type=content_type)


@app.post("/api/topups/{topup_id}/approve")
async def api_approve_topup(topup_id: int, admin=Depends(require_permission("orders"))):
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup:
        raise HTTPException(404, "یافت نشد.")
    if not (await asyncio.to_thread(db.approve_topup, topup_id)):
        raise HTTPException(400, "قبلاً بررسی شده است.")
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "topup_approve", f"شارژ #{topup_id} تایید شد (پنل وب - {admin['username']})", "topup", topup_id))
    await notify_user(topup["user_id"], f"✅ شارژ کیف پول شما به مبلغ {topup['amount']:,} تومان تایید شد.")
    return {"ok": True}


@app.post("/api/topups/{topup_id}/reject")
async def api_reject_topup(topup_id: int, admin=Depends(require_permission("orders"))):
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup or topup["status"] != "pending":
        raise HTTPException(400, "یافت نشد یا قبلاً بررسی شده.")
    (await asyncio.to_thread(db.reject_topup, topup_id))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "topup_reject", f"شارژ #{topup_id} رد شد (پنل وب - {admin['username']})", "topup", topup_id))
    await notify_user(topup["user_id"], "⛔️ درخواست شارژ کیف پول شما رد شد.")
    return {"ok": True}


# ------------------------------------------------------------------- users --


@app.get("/api/users")
def api_users(q: str = "", status: str = "all", page: int = 1, admin=Depends(get_current_admin)):
    limit = 25
    rows, total = db.search_users(q, status, limit=limit, offset=(page - 1) * limit)
    return {"items": rows_to_list(rows), "total": total, "page": page, "limit": limit}


@app.get("/api/users/{tg_id}")
def api_user_detail(tg_id: int, admin=Depends(get_current_admin)):
    user = db.get_user(tg_id)
    if not user:
        raise HTTPException(404, "کاربر یافت نشد.")
    history = db.get_user_full_history(tg_id)
    return {
        "user": dict(user),
        "orders": rows_to_list(history["orders"]),
        "topups": rows_to_list(history["topups"]),
        "referral": db.get_referral_stats(tg_id),
        "is_reseller": db.is_reseller(tg_id),
        "reseller_credit": db.get_reseller_credit(tg_id),
    }


@app.post("/api/users/{tg_id}/block")
def api_block_user(tg_id: int, admin=Depends(require_permission("users"))):
    db.set_user_blocked(tg_id, True)
    db.log_admin_action(admin["id"], "user_block", f"کاربر {tg_id} مسدود شد (پنل وب - {admin['username']})", "user", tg_id)
    return {"ok": True}


@app.post("/api/users/{tg_id}/unblock")
def api_unblock_user(tg_id: int, admin=Depends(require_permission("users"))):
    db.set_user_blocked(tg_id, False)
    db.log_admin_action(admin["id"], "user_unblock", f"کاربر {tg_id} رفع مسدودیت شد (پنل وب - {admin['username']})", "user", tg_id)
    return {"ok": True}


class WalletAdjustBody(BaseModel):
    delta: int


@app.post("/api/users/{tg_id}/wallet")
async def api_adjust_wallet(tg_id: int, body: WalletAdjustBody, admin=Depends(require_permission("users"))):
    (await asyncio.to_thread(db.add_wallet_credit, tg_id, body.delta))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "wallet_adjust", f"کیف پول کاربر {tg_id} به میزان {body.delta:,} تغییر کرد (پنل وب - {admin['username']})",
        "user", tg_id,
    ))
    if body.delta:
        sign = "افزایش" if body.delta > 0 else "کاهش"
        await notify_user(tg_id, f"💰 موجودی کیف پول شما {sign} یافت: {abs(body.delta):,} تومان")
    return {"ok": True}


# ------------------------------------------------------- categories/products --


class CategoryBody(BaseModel):
    name: str


@app.get("/api/categories")
def api_categories(admin=Depends(get_current_admin)):
    return rows_to_list(db.get_categories(active_only=False))


@app.post("/api/categories")
def api_add_category(body: CategoryBody, admin=Depends(require_permission("catalog"))):
    cat_id = db.add_category(body.name)
    db.log_admin_action(admin["id"], "category_add", body.name, "category", cat_id)
    return {"id": cat_id}


@app.put("/api/categories/{cat_id}")
def api_edit_category(cat_id: int, body: CategoryBody, admin=Depends(require_permission("catalog"))):
    db.edit_category(cat_id, body.name)
    db.log_admin_action(admin["id"], "category_edit", body.name, "category", cat_id)
    return {"ok": True}


@app.post("/api/categories/{cat_id}/toggle")
def api_toggle_category(cat_id: int, admin=Depends(require_permission("catalog"))):
    db.toggle_category(cat_id)
    db.log_admin_action(admin["id"], "category_toggle", str(cat_id), "category", cat_id)
    return {"ok": True}


@app.delete("/api/categories/{cat_id}")
def api_delete_category(cat_id: int, admin=Depends(require_permission("catalog"))):
    db.delete_category(cat_id)
    db.log_admin_action(admin["id"], "category_delete", str(cat_id), "category", cat_id)
    return {"ok": True}


class ProductBody(BaseModel):
    category_id: int
    name: str
    price: int
    description: str = ""
    duration_days: int = 30
    is_auto_provision: bool = False
    auto_provision_volume_gb: Optional[int] = None
    provision_server_id: Optional[int] = None


@app.get("/api/products")
def api_products(admin=Depends(get_current_admin)):
    products = rows_to_list(db.get_all_products())
    for p in products:
        p["stock"] = db.count_available_configs(p["id"])
    return products


@app.get("/api/panel-servers-lite")
def api_panel_servers_lite(admin=Depends(require_permission("catalog"))):
    """لیست سبک پنل‌ها (فقط id/name) برای انتخاب پنل موقع ساخت محصول اتصال مستقیم."""
    return [{"id": s["id"], "name": s["name"]} for s in db.get_panel_servers(active_only=True)]


@app.post("/api/products")
def api_add_product(body: ProductBody, admin=Depends(require_permission("catalog"))):
    if body.provision_server_id and not body.auto_provision_volume_gb:
        raise HTTPException(400, "برای اتصال مستقیم به پنل باید حجم (گیگابایت) را مشخص کنید.")
    pid = db.add_product(
        body.category_id, body.name, body.price, body.description, body.duration_days,
        body.is_auto_provision or bool(body.provision_server_id), body.auto_provision_volume_gb,
        body.provision_server_id,
    )
    db.log_admin_action(admin["id"], "product_add", f"{body.name} (پنل وب - {admin['username']})", "product", pid)
    return {"id": pid}


class ProductEditBody(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    description: Optional[str] = None
    duration_days: Optional[int] = None


@app.put("/api/products/{product_id}")
def api_edit_product(product_id: int, body: ProductEditBody, admin=Depends(require_permission("catalog"))):
    db.edit_product(product_id, body.name, body.price, body.description, body.duration_days)
    db.log_admin_action(admin["id"], "product_edit", f"#{product_id} (پنل وب - {admin['username']})", "product", product_id)
    return {"ok": True}


@app.post("/api/products/{product_id}/toggle")
def api_toggle_product(product_id: int, admin=Depends(require_permission("catalog"))):
    db.toggle_product(product_id)
    db.log_admin_action(admin["id"], "product_toggle", str(product_id), "product", product_id)
    return {"ok": True}


@app.delete("/api/products/{product_id}")
def api_delete_product(product_id: int, admin=Depends(require_permission("catalog"))):
    db.delete_product(product_id)
    db.log_admin_action(admin["id"], "product_delete", str(product_id), "product", product_id)
    return {"ok": True}


# ------------------------------------------------------------- config bank --


class ConfigsAddBody(BaseModel):
    links: str  # هر خط یک لینک


@app.get("/api/products/{product_id}/configs")
def api_product_configs(product_id: int, admin=Depends(require_permission("catalog"))):
    stats = db.get_config_stats(product_id)
    return {"items": rows_to_list(db.get_unused_configs(product_id)), "used_count": stats["used"]}


@app.post("/api/products/{product_id}/configs")
def api_add_configs(product_id: int, body: ConfigsAddBody, admin=Depends(require_permission("catalog"))):
    links = [l.strip() for l in body.links.splitlines() if l.strip()]
    added, duplicates = db.add_configs(product_id, links)
    db.log_admin_action(admin["id"], "configs_add", f"{added} لینک به محصول #{product_id} (پنل وب - {admin['username']})", "product", product_id)
    return {"added": added, "duplicates": duplicates}


@app.delete("/api/configs/{config_id}")
def api_delete_config(config_id: int, admin=Depends(require_permission("catalog"))):
    db.delete_config(config_id)
    db.log_admin_action(admin["id"], "config_delete", str(config_id), "config", config_id)
    return {"ok": True}


# --------------------------------------------------------------- discounts --


class DiscountBody(BaseModel):
    code: str
    percent: Optional[int] = None
    fixed_amount: Optional[int] = None
    max_uses: int = 0
    expires_at: Optional[str] = None


@app.get("/api/discounts")
def api_discounts(admin=Depends(require_permission("discounts"))):
    return rows_to_list(db.list_discount_codes())


@app.post("/api/discounts")
def api_add_discount(body: DiscountBody, admin=Depends(require_permission("discounts"))):
    code_id = db.create_discount_code(body.code, body.percent, body.fixed_amount, body.max_uses, body.expires_at)
    db.log_admin_action(admin["id"], "discount_add", body.code, "discount", code_id)
    return {"id": code_id}


@app.post("/api/discounts/{code_id}/toggle")
def api_toggle_discount(code_id: int, admin=Depends(require_permission("discounts"))):
    db.toggle_discount_code(code_id)
    db.log_admin_action(admin["id"], "discount_toggle", str(code_id), "discount", code_id)
    return {"ok": True}


@app.delete("/api/discounts/{code_id}")
def api_delete_discount(code_id: int, admin=Depends(require_permission("discounts"))):
    db.delete_discount_code(code_id)
    db.log_admin_action(admin["id"], "discount_delete", str(code_id), "discount", code_id)
    return {"ok": True}


# ------------------------------------------------------------------ tickets --


@app.get("/api/tickets")
def api_tickets(status: Optional[str] = None, admin=Depends(get_current_admin)):
    tickets = rows_to_list(db.get_all_tickets(status))
    for t in tickets:
        user = row_to_dict(db.get_user(t["user_id"]))
        t["username"] = user["username"] if user else None
    return tickets


@app.get("/api/tickets/{ticket_id}/messages")
def api_ticket_messages(ticket_id: int, admin=Depends(get_current_admin)):
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "یافت نشد.")
    return {"ticket": dict(ticket), "messages": rows_to_list(db.get_ticket_messages(ticket_id))}


class TicketReplyBody(BaseModel):
    message: str


@app.post("/api/tickets/{ticket_id}/reply")
async def api_ticket_reply(ticket_id: int, body: TicketReplyBody, admin=Depends(require_permission("tickets"))):
    ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
    if not ticket:
        raise HTTPException(404, "یافت نشد.")
    (await asyncio.to_thread(db.claim_ticket_if_open, ticket_id, admin["id"]))
    (await asyncio.to_thread(db.add_ticket_message, ticket_id, "admin", body.message))
    await notify_user(ticket["user_id"], f"📩 پاسخ پشتیبانی برای تیکت «{ticket['subject']}»:\n\n{body.message}")
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "ticket_reply", f"تیکت #{ticket_id} (پنل وب - {admin['username']})", "ticket", ticket_id))
    return {"ok": True}


@app.post("/api/tickets/{ticket_id}/close")
def api_ticket_close(ticket_id: int, admin=Depends(require_permission("tickets"))):
    db.close_ticket(ticket_id)
    db.log_admin_action(admin["id"], "ticket_close", f"تیکت #{ticket_id} (پنل وب - {admin['username']})", "ticket", ticket_id)
    return {"ok": True}


# -------------------------------------------------------------- broadcast --


class BroadcastBody(BaseModel):
    message: str


@app.post("/api/broadcast")
async def api_broadcast(body: BroadcastBody, admin=Depends(require_permission("broadcast"))):
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(400, "متن پیام نمی‌تواند خالی باشد.")
    if len(text) > 4000:
        raise HTTPException(400, "متن پیام بیش از حد طولانی است.")

    user_ids = (await asyncio.to_thread(db.get_all_user_ids))
    sem = asyncio.Semaphore(20)
    counters = {"success": 0, "failed": 0}

    async def _send(uid):
        async with sem:
            ok = await tg_send(_bot_token(), uid, text)
            counters["success" if ok else "failed"] += 1

    await asyncio.gather(*[_send(uid) for uid in user_ids])
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "broadcast",
        f"ارسال به {len(user_ids)} کاربر | موفق: {counters['success']} | ناموفق: {counters['failed']} "
        f"(پنل وب - {admin['username']})",
    ))
    return {"total": len(user_ids), "success": counters["success"], "failed": counters["failed"]}


# --------------------------------------------------------- live support chat --


def _support_lock_label(assigned_admin_id):
    """assigned_admin_id مثبت یعنی قفل روی ادمین تلگرام (بات/میان‌اپ)، منفی یعنی
    قفل روی ادمین وب (چون ادمین‌های وب آیدی تلگرام ندارند، با -admin_id ذخیره می‌شوند)."""
    if not assigned_admin_id:
        return None
    if assigned_admin_id < 0:
        wa = db.get_web_admin(-assigned_admin_id)
        return f"{wa['username']} (پنل وب)" if wa else "ادمین وب"
    return f"ادمین تلگرام #{assigned_admin_id}"


@app.get("/api/support/conversations")
def api_support_conversations(admin=Depends(get_current_admin)):
    my_lock_id = -admin["id"]
    is_owner = admin["role"] == "owner"
    convs = rows_to_list(db.list_support_conversations())
    for c in convs:
        user = row_to_dict(db.get_user(c["user_id"]))
        c["user_name"] = (user["first_name"] if user else "") or ""
        c["user_username"] = (user["username"] if user else "") or ""
        assigned = c.get("assigned_admin_id")
        c["locked_by"] = _support_lock_label(assigned)
        c["locked_for_me"] = bool(assigned) and assigned != my_lock_id and not is_owner
    return convs


@app.get("/api/support/{user_id}/messages")
def api_support_messages(user_id: int, since_id: int = 0, admin=Depends(get_current_admin)):
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "کاربر یافت نشد.")
    db.mark_support_read_by_admin(user_id)
    rows = rows_to_list(db.get_support_messages(user_id, since_id=since_id))
    conv = db.get_support_conversation(user_id)
    assigned = conv["assigned_admin_id"] if conv else None
    my_lock_id = -admin["id"]
    is_owner = admin["role"] == "owner"
    return {
        "user": {
            "user_id": user_id,
            "user_name": (user["first_name"] if user else "") or "",
            "user_username": (user["username"] if user else "") or "",
            "locked_by": _support_lock_label(assigned),
            "locked_for_me": bool(assigned) and assigned != my_lock_id and not is_owner,
        },
        "messages": [
            {"id": m["id"], "sender": m["sender"], "message": m["message"], "created_at": m["created_at"]}
            for m in rows
        ],
    }


class SupportReplyBody(BaseModel):
    message: str


@app.post("/api/support/{user_id}/messages")
async def api_support_send(user_id: int, body: SupportReplyBody, admin=Depends(get_current_admin)):
    user = (await asyncio.to_thread(db.get_user, user_id))
    if not user:
        raise HTTPException(404, "کاربر یافت نشد.")
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(400, "پیام نمی‌تواند خالی باشد.")
    if len(text) > 2000:
        raise HTTPException(400, "پیام بیش از حد طولانی است.")

    # قفل مکالمه: چون ادمین‌های وب آیدی تلگرام ندارند، با -admin_id در همان
    # ستون assigned_admin_id ذخیره می‌شود (که با آیدی‌های واقعی تلگرام تداخل ندارد).
    my_lock_id = -admin["id"]
    is_owner = admin["role"] == "owner"
    conv = (await asyncio.to_thread(db.get_support_conversation, user_id))
    assigned = conv["assigned_admin_id"] if conv else None
    if assigned and assigned != my_lock_id and not is_owner:
        raise HTTPException(
            403,
            f"این گفتگو در حال حاضر توسط {_support_lock_label(assigned)} در حال پاسخ‌دهی است.",
        )
    if not is_owner:
        (await asyncio.to_thread(db.set_support_conversation_admin, user_id, my_lock_id))

    msg_id = (await asyncio.to_thread(db.add_support_message, user_id, "admin", text))
    await notify_user(user_id, f"💬 پشتیبانی:\n\n{text}")
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "support_reply", f"پاسخ چت زنده به کاربر {user_id} (پنل وب - {admin['username']})", "user", user_id))
    return {"ok": True, "id": msg_id}


# -------------------------------------------------------------- resellers --


def _resolved_admin_panel_url(request: Request) -> str:
    saved = (db.get_setting("admin_panel_url", "") or "").strip().rstrip("/")
    if saved:
        return saved
    return f"{request.url.scheme}://{request.url.netloc}"


async def _deliver_reseller_webpanel_link(bot_id: int, request: Request) -> bool:
    reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
    if not reseller_bot or not reseller_bot["web_panel_setup_token"]:
        return False
    panel_url = _resolved_admin_panel_url(request)
    b_value = reseller_bot["link_slug"] or str(bot_id)
    link = f"{panel_url}/setup?b={b_value}&t={reseller_bot['web_panel_setup_token']}"
    text = (
        "🌐 لینک راه‌اندازی پنل وب نمایندگی شما:\n\n"
        f"{link}\n\n"
        "این لینک یک‌بارمصرف است؛ با باز کردنش یک یوزرنیم/پسورد دلخواه برای پنل وب "
        "خودت (مستقل از پنل بات اصلی) تنظیم می‌کنی."
    )
    return await tg_send(reseller_bot["bot_token"], reseller_bot["owner_telegram_id"], text)


def _set_main_bot_fsm_state(chat_id: int, state: Optional[str], data: Optional[dict] = None) -> bool:
    """مستقیم روی فایل SQLite استوریج FSM بات اصلی می‌نویسد - چون این پروسه‌ی پنل وب
    مستقل است و به Dispatcher زنده‌ی بات اصلی دسترسی ندارد. دقیقاً همان اسکیمای
    fsm_storage.SQLiteStorage را می‌سازد/به‌روزرسانی می‌کند (bot_manager.reconcile
    هم دقیقاً به همین شکل با پروسه‌های جدا هماهنگ می‌شود)."""
    try:
        bot_id = int(BOT_TOKEN.split(":")[0])
        conn = sqlite3.connect(f"{DB_PATH}.fsm.sqlite3", timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=4000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fsm_storage (
                    bot_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    business_connection_id TEXT,
                    destiny TEXT NOT NULL DEFAULT 'default',
                    state TEXT,
                    data TEXT,
                    PRIMARY KEY (bot_id, chat_id, user_id, thread_id, business_connection_id, destiny)
                )
                """
            )
            conn.execute(
                "INSERT INTO fsm_storage "
                "(bot_id, chat_id, user_id, thread_id, business_connection_id, destiny, state, data) "
                "VALUES (?, ?, ?, 0, '', 'default', ?, ?) "
                "ON CONFLICT (bot_id, chat_id, user_id, thread_id, business_connection_id, destiny) "
                "DO UPDATE SET state=excluded.state, data=excluded.data",
                (bot_id, chat_id, chat_id, state, json.dumps(data or {}, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        logger.exception("تنظیم FSM state بات اصلی برای %s ناموفق بود.", chat_id)
        return False


@app.get("/api/reseller-panels-lite")
def api_reseller_panels_lite(admin=Depends(require_permission("resellers"))):
    """لیست سبک پنل‌ها (فقط id/name) برای انتخاب‌گرها؛ بدون نیاز به مجوز «panels»."""
    return [{"id": s["id"], "name": s["name"]} for s in db.get_panel_servers(active_only=True)]


# ------------------------------------------------- reseller bots (سطح ۱/کامل) --


@app.get("/api/reseller-bots")
def api_reseller_bots(admin=Depends(require_permission("resellers"))):
    bots = rows_to_list(db.list_reseller_bots())
    for b in bots:
        try:
            rdb = Database(resolve_db_path(b["db_path"]))
            b.update(rdb.get_bot_revenue_summary())
        except Exception:
            b["revenue_toman"] = 0
            b["paid_orders"] = 0
        b.pop("bot_token", None)
        b.pop("web_panel_setup_token", None)
    return bots


@app.post("/api/reseller-bots/{bot_id}/toggle")
def api_toggle_reseller_bot(bot_id: int, admin=Depends(require_permission("resellers"))):
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    db.toggle_reseller_bot(bot_id)
    db.log_admin_action(
        admin["id"], "reseller_bot_toggle", f"نماینده #{bot_id} (پنل وب - {admin['username']})", "reseller_bot", bot_id
    )
    return {"ok": True}


class ResellerBotLevelBody(BaseModel):
    level: int


@app.post("/api/reseller-bots/{bot_id}/level")
def api_set_reseller_bot_level(bot_id: int, body: ResellerBotLevelBody, admin=Depends(require_permission("resellers"))):
    if body.level not in (1, 2):
        raise HTTPException(400, "سطح نامعتبر است.")
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    db.set_reseller_level(bot_id, body.level)
    try:
        reseller_db = Database(resolve_db_path(reseller_bot["db_path"]))
        reseller_db.set_setting("reseller_level", str(body.level))
        if body.level == 2:
            reseller_db.set_setting("custom_config_enabled", "0")
    except Exception:
        logger.exception("همگام‌سازی سطح نمایندگی روی دیتابیس نماینده #%s ناموفق بود.", bot_id)
    db.log_admin_action(
        admin["id"], "reseller_bot_level", f"نماینده #{bot_id} -> سطح {body.level} (پنل وب - {admin['username']})",
        "reseller_bot", bot_id,
    )
    return {"ok": True}


class ResellerBotEditBody(BaseModel):
    owner_name: Optional[str] = None
    owner_telegram_id: Optional[int] = None


@app.put("/api/reseller-bots/{bot_id}")
def api_edit_reseller_bot(bot_id: int, body: ResellerBotEditBody, admin=Depends(require_permission("resellers"))):
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    db.edit_reseller_bot(bot_id, owner_telegram_id=body.owner_telegram_id, owner_name=body.owner_name)
    db.log_admin_action(
        admin["id"], "reseller_bot_edit", f"نماینده #{bot_id} (پنل وب - {admin['username']})", "reseller_bot", bot_id
    )
    return {"ok": True}


@app.delete("/api/reseller-bots/{bot_id}")
def api_delete_reseller_bot(bot_id: int, purge_db: bool = False, admin=Depends(require_permission("resellers"))):
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    db.delete_reseller_bot(bot_id)
    db.purge_reseller_leftovers(reseller_bot["owner_telegram_id"])
    if purge_db:
        db.queue_db_purge(reseller_bot["bot_token"], resolve_db_path(reseller_bot["db_path"]))
    db.log_admin_action(
        admin["id"], "reseller_bot_delete",
        f"نماینده #{bot_id} (@{reseller_bot['bot_username'] or ''}) (پنل وب - {admin['username']})",
        "reseller_bot", bot_id,
    )
    return {"ok": True}


@app.post("/api/reseller-bots/{bot_id}/web-panel/enable")
async def api_enable_reseller_webpanel(bot_id: int, request: Request, admin=Depends(require_permission("resellers"))):
    reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    level = reseller_bot["reseller_level"] if "reseller_level" in reseller_bot.keys() else 2
    if level != 1:
        raise HTTPException(400, "پنل وب فقط برای نمایندگی «کامل» قابل فعال‌سازی است.")
    if reseller_bot["web_panel_enabled"]:
        raise HTTPException(400, "قبلاً فعال است؛ برای لینک جدید از «ساخت لینک جدید» استفاده کنید.")
    (await asyncio.to_thread(db.enable_reseller_web_panel, bot_id))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_webpanel_enable", f"نماینده #{bot_id} (پنل وب - {admin['username']})",
        "reseller_bot", bot_id,
    ))
    sent = await _deliver_reseller_webpanel_link(bot_id, request)
    return {"ok": True, "sent_to_owner": sent}


@app.post("/api/reseller-bots/{bot_id}/web-panel/regenerate")
async def api_regen_reseller_webpanel(bot_id: int, request: Request, admin=Depends(require_permission("resellers"))):
    reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    (await asyncio.to_thread(db.regenerate_reseller_web_panel_token, bot_id))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_webpanel_regen", f"نماینده #{bot_id} (پنل وب - {admin['username']})",
        "reseller_bot", bot_id,
    ))
    sent = await _deliver_reseller_webpanel_link(bot_id, request)
    return {"ok": True, "sent_to_owner": sent}


@app.post("/api/reseller-bots/{bot_id}/web-panel/disable")
def api_disable_reseller_webpanel(bot_id: int, admin=Depends(require_permission("resellers"))):
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    db.disable_reseller_web_panel(bot_id)
    db.log_admin_action(
        admin["id"], "reseller_webpanel_disable", f"نماینده #{bot_id} (پنل وب - {admin['username']})",
        "reseller_bot", bot_id,
    )
    return {"ok": True}


@app.get("/api/reseller-bots/{bot_id}/web-panel/login-link")
def api_reseller_webpanel_login_link(bot_id: int, request: Request, admin=Depends(require_permission("resellers"))):
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, "یافت نشد.")
    panel_url = _resolved_admin_panel_url(request)
    b_value = reseller_bot["link_slug"] or str(bot_id)
    return {"login_link": f"{panel_url}/?b={b_value}"}


# --------------------------------------------- resellers (سطح ۲ / اعتبار حجمی) --


@app.get("/api/resellers")
def api_resellers(admin=Depends(require_permission("resellers"))):
    rows = rows_to_list(db.get_resellers())
    sales = db.get_reseller_sales_map()
    for r in rows:
        s = sales.get(r["telegram_id"], {"configs": 0, "volume_gb": 0})
        r["sold_configs"] = s["configs"]
        r["sold_volume_gb"] = s["volume_gb"]
    return rows


class ResellerCreditBody(BaseModel):
    delta_gb: int
    reason: Optional[str] = None


@app.post("/api/resellers/{tg_id}/credit")
async def api_adjust_reseller_credit(tg_id: int, body: ResellerCreditBody, admin=Depends(require_permission("resellers"))):
    (await asyncio.to_thread(db.adjust_reseller_credit, tg_id, body.delta_gb, admin_id=admin["id"], reason=body.reason or "تنظیم از پنل وب"))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_credit_adjust",
        f"نماینده {tg_id} به میزان {body.delta_gb:,} گیگ (پنل وب - {admin['username']})",
        "reseller", tg_id,
    ))
    await notify_user(tg_id, f"📦 اعتبار حجمی نمایندگی شما تغییر کرد: {body.delta_gb:+,} گیگابایت")
    return {"ok": True}


@app.get("/api/resellers/{tg_id}/log")
def api_reseller_log(tg_id: int, admin=Depends(require_permission("resellers"))):
    return rows_to_list(db.get_reseller_credit_log(tg_id, limit=50))


class ResellerToggleBody(BaseModel):
    enabled: bool


@app.post("/api/resellers/{tg_id}/status")
def api_reseller_status(tg_id: int, body: ResellerToggleBody, admin=Depends(require_permission("resellers"))):
    db.set_reseller_status(tg_id, body.enabled)
    db.log_admin_action(admin["id"], "reseller_status_toggle", f"نماینده {tg_id} -> {body.enabled}", "reseller", tg_id)
    return {"ok": True}


class ResellerPanelBody(BaseModel):
    panel_server_id: Optional[int] = None


@app.post("/api/resellers/{tg_id}/panel")
def api_set_reseller_panel(tg_id: int, body: ResellerPanelBody, admin=Depends(require_permission("resellers"))):
    db.set_reseller_panel(tg_id, body.panel_server_id)
    db.log_admin_action(
        admin["id"], "reseller_panel_set",
        f"نماینده {tg_id} -> پنل {body.panel_server_id or 'پیش‌فرض خودکار'} (پنل وب - {admin['username']})",
        "reseller", tg_id,
    )
    return {"ok": True}


@app.get("/api/resellers/analytics/cohort")
def api_reseller_cohort(days: int = 30, months: int = 6, admin=Depends(require_permission("resellers"))):
    """تحلیل کوهورت (نگهداشت ماهانه) و ریزش (churn) نمایندگی‌ها."""
    days = max(1, min(days, 365))
    months = max(1, min(months, 12))
    return db.get_reseller_cohort_churn(inactivity_days=days, months=months)


@app.get("/api/resellers/orphans")
def api_reseller_orphans(admin=Depends(require_permission("resellers"))):
    return rows_to_list(db.list_orphaned_reseller_users())


@app.post("/api/resellers/{tg_id}/purge")
def api_purge_reseller_leftovers(tg_id: int, admin=Depends(require_permission("resellers"))):
    db.purge_reseller_leftovers(tg_id)
    db.log_admin_action(
        admin["id"], "reseller_orphan_purge", f"کاربر {tg_id} (پنل وب - {admin['username']})", "reseller", tg_id
    )
    return {"ok": True}


# ------------------------------------------------------------ reseller requests --


@app.get("/api/reseller-requests")
def api_reseller_requests(status: Optional[str] = None, admin=Depends(require_permission("resellers"))):
    rows = db.list_reseller_requests(status)
    out = []
    for r in rows:
        r = dict(r)
        user = row_to_dict(db.get_user(r["user_id"]))
        r["username"] = user["username"] if user else None
        out.append(r)
    return out


@app.get("/api/reseller-requests/{request_id}/receipt")
async def api_reseller_request_receipt(request_id: int, admin=Depends(require_permission("resellers"))):
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or not req["receipt_file_id"]:
        raise HTTPException(404, "رسیدی برای این درخواست ثبت نشده است.")
    result = await fetch_telegram_file(_bot_token(), req["receipt_file_id"])
    if not result:
        raise HTTPException(502, "دریافت رسید از تلگرام ناموفق بود.")
    content, content_type = result
    return Response(content=content, media_type=content_type)


class ResellerRequestQuoteBody(BaseModel):
    price_toman: int
    panel_server_id: Optional[int] = None


@app.post("/api/reseller-requests/{request_id}/quote")
async def api_quote_reseller_request(request_id: int, body: ResellerRequestQuoteBody, admin=Depends(require_permission("resellers"))):
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or req["status"] != "pending_review":
        raise HTTPException(400, "این درخواست دیگر معتبر نیست.")
    if body.price_toman <= 0:
        raise HTTPException(400, "هزینه باید عددی مثبت باشد.")
    (await asyncio.to_thread(db.quote_reseller_request, request_id, body.price_toman, body.panel_server_id, admin["id"]))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_request_quote",
        f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {body.price_toman:,} (پنل وب - {admin['username']})",
    ))
    await tg_send(
        _bot_token(), req["user_id"],
        f"🏪 درخواست نمایندگی #{request_id} شما تایید شد!\n\n"
        f"💰 هزینه‌ی نمایندگی: {body.price_toman:,} تومان\n"
        f"📦 حجم: {req['volume_gb']:,} گیگ\n\n"
        f"در صورت موافقت روی «پرداخت می‌کنم» بزنید:",
        reply_markup={"inline_keyboard": [[{"text": "✅ پرداخت می‌کنم", "callback_data": f"resreq_pay:{request_id}"}]]},
    )
    return {"ok": True}


@app.post("/api/reseller-requests/{request_id}/approve-payment")
async def api_approve_reseller_request_payment(request_id: int, admin=Depends(require_permission("resellers"))):
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or req["status"] != "awaiting_payment_review":
        raise HTTPException(400, "این درخواست دیگر معتبر نیست.")
    (await asyncio.to_thread(db.approve_reseller_request_payment, request_id, admin["id"]))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_request_payment_approve",
        f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {(req['price_toman'] or 0):,} (پنل وب - {admin['username']})",
    ))
    _set_main_bot_fsm_state(req["user_id"], "ResellerRequestFlow:waiting_bot_token", {"resreq_request_id": request_id})
    await notify_user(
        req["user_id"],
        "✅ پرداخت شما تایید شد!\n\nحالا توکن بات نماینده‌ی خودتان را ارسال کنید (همانی که از @BotFather گرفته‌اید):",
    )
    return {"ok": True}


class ResellerRequestRejectBody(BaseModel):
    reason: str
    kind: str = "rejected"


@app.post("/api/reseller-requests/{request_id}/reject")
async def api_reject_reseller_request(request_id: int, body: ResellerRequestRejectBody, admin=Depends(require_permission("resellers"))):
    if body.kind not in ("rejected", "payment_rejected"):
        raise HTTPException(400, "نوع رد نامعتبر است.")
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or not (await asyncio.to_thread(db.is_reseller_request_open, req["status"])):
        raise HTTPException(400, "این درخواست دیگر باز نیست.")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "دلیل رد الزامی است.")
    (await asyncio.to_thread(db.reject_reseller_request, request_id, body.kind, admin["id"], reason))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_request_reject",
        f"درخواست #{request_id} | کاربر {req['user_id']} | وضعیت: {body.kind} | دلیل: {reason} (پنل وب - {admin['username']})",
    ))
    label = "درخواست نمایندگی" if body.kind == "rejected" else "پرداخت درخواست نمایندگی"
    await notify_user(req["user_id"], f"❌ متاسفانه {label} شما (#{request_id}) رد شد.\n\nدلیل: {reason}")
    return {"ok": True}


@app.post("/api/reseller-requests/{request_id}/cancel")
async def api_cancel_reseller_request(request_id: int, admin=Depends(require_permission("resellers"))):
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or not (await asyncio.to_thread(db.is_reseller_request_open, req["status"])):
        raise HTTPException(400, "این درخواست دیگر باز نیست.")
    (await asyncio.to_thread(db.admin_cancel_reseller_request, request_id, admin["id"]))
    if req["status"] == "awaiting_bot_info":
        _set_main_bot_fsm_state(req["user_id"], None, {})
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_request_admin_cancel", f"درخواست #{request_id} | کاربر {req['user_id']} (پنل وب - {admin['username']})",
    ))
    await notify_user(req["user_id"], f"⚪️ درخواست نمایندگی شما (#{request_id}) توسط مدیریت کنسل شد.")
    return {"ok": True}


# ---------------------------------------------------------------- panels --


class PanelServerBody(BaseModel):
    name: str
    panel_type: str
    api_url: str
    api_username: str = ""
    api_password: str
    default_group: Optional[str] = None
    template_username: Optional[str] = None  # لازم برای PasarGuard/Marzban/Marzneshin


class PanelServerUpdateBody(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    api_username: Optional[str] = None
    api_password: Optional[str] = None
    xui_inbound_id: Optional[int] = None
    xui_sub_base_url: Optional[str] = None


class PanelServerTemplateBody(BaseModel):
    template_username: str


class PanelServerXuiConfigBody(BaseModel):
    inbound_id: Optional[int] = None
    sub_base_url: str


def _panel_server_public(s) -> dict:
    is_sub_base_type = s["panel_type"] in SUB_BASE_URL_PANEL_TYPES
    if is_sub_base_type:
        needs_inbound = s["panel_type"] in INBOUND_SELECT_PANEL_TYPES
        configured = bool(s["xui_sub_base_url"]) and (bool(s["xui_inbound_id"]) if needs_inbound else True)
    else:
        configured = bool(s["group_ids"] and s["proxy_settings"])
    return {
        "id": s["id"], "name": s["name"], "panel_type": s["panel_type"],
        "type_label": PANEL_TYPE_LABELS.get(s["panel_type"], s["panel_type"]),
        "api_url": s["api_url"], "template_username": s["template_username"],
        "has_template": bool(s["group_ids"] and s["proxy_settings"]),
        "xui_inbound_id": s["xui_inbound_id"], "xui_sub_base_url": s["xui_sub_base_url"],
        "is_configured": configured,
        "used_for_custom_config": bool(s["used_for_custom_config"]),
        "used_for_test_config": bool(s["used_for_test_config"]),
        "default_group": s["default_group"], "is_active": bool(s["is_active"]),
    }


@app.get("/api/panel-servers")
def api_panel_servers(admin=Depends(require_permission("panels"))):
    return [_panel_server_public(s) for s in db.get_panel_servers()]


@app.get("/api/panel-servers/panel-types")
def api_panel_server_types(admin=Depends(require_permission("panels"))):
    """لیست انواع پنل پشتیبانی‌شده - برای ساخت فرم افزودن سرور در فرانت."""
    return [
        {
            "type": k, "label": v,
            "needs_template": k in TEMPLATE_BASED_PANEL_TYPES,
            "needs_sub_base_url": k in SUB_BASE_URL_PANEL_TYPES,
            "needs_inbound_select": k in INBOUND_SELECT_PANEL_TYPES,
        }
        for k, v in PANEL_TYPE_LABELS.items()
    ]


@app.post("/api/panel-servers")
async def api_add_panel_server(body: PanelServerBody, admin=Depends(require_permission("panels"))):
    if not body.name.strip() or not body.api_url.strip() or not body.api_password.strip():
        raise HTTPException(400, "نام، آدرس و پسورد/توکن الزامی هستند.")
    if body.panel_type not in PROVIDERS:
        raise HTTPException(400, "نوع پنل پشتیبانی نمی‌شود.")

    username = body.api_username.strip()
    if body.panel_type == "3xui":
        # 3X-UI جدید فقط با API Token (فیلد پسورد) کار می‌کند؛ یوزرنیم استفاده نمی‌شود.
        username = username or "3xui"

    if body.panel_type in INBOUND_SELECT_PANEL_TYPES:
        server_id = db.add_panel_server(body.name.strip(), body.panel_type, body.api_url.strip(), username, body.api_password, body.default_group)
        server = db.get_panel_server(server_id)
        try:
            provider = get_provider(server)
            inbounds = await provider.list_inbounds()
        except PanelError as e:
            db.delete_panel_server(server_id)
            raise HTTPException(400, str(e))
        if not inbounds:
            db.delete_panel_server(server_id)
            raise HTTPException(400, "این پنل هیچ inbound ای ندارد. اول از داخل پنل یک inbound بساز.")
        db.log_admin_action(admin["id"], "panel_add", f"سرور «{body.name}» (3X-UI، #{server_id}) از پنل وب")
        return {"id": server_id, "inbounds": inbounds, "needs_inbound_select": True}

    if body.panel_type in SUB_BASE_URL_PANEL_TYPES:
        # مثل Hiddify: inbound لازم نیست؛ باید بعداً با /xui-config تکمیل شود.
        server_id = db.add_panel_server(body.name.strip(), body.panel_type, body.api_url.strip(), username, body.api_password, body.default_group)
        db.log_admin_action(admin["id"], "panel_add", f"سرور «{body.name}» (#{server_id}) از پنل وب")
        return {"id": server_id, "needs_sub_base_url": True}

    # خانواده‌ی PasarGuard/Marzban/Marzneshin: با «کاربر نمونه» قالب گرفته می‌شود
    if not body.template_username or not body.template_username.strip():
        raise HTTPException(400, "نام کاربری نمونه (برای دریافت قالب) الزامی است.")
    server_id = db.add_panel_server(body.name.strip(), body.panel_type, body.api_url.strip(), username, body.api_password, body.default_group)
    server = db.get_panel_server(server_id)
    try:
        provider = get_provider(server)
        template = await provider.fetch_template_from_user(body.template_username.strip())
    except PanelError as e:
        db.delete_panel_server(server_id)
        raise HTTPException(400, str(e))
    db.update_panel_server(
        server_id, group_ids=json.dumps(template["group_ids"]),
        proxy_settings=json.dumps(template["proxy_settings"]), template_username=body.template_username.strip(),
    )
    db.log_admin_action(admin["id"], "panel_add", f"سرور «{body.name}» (#{server_id}) از پنل وب")
    return {"id": server_id}


@app.get("/api/panel-servers/{server_id}/inbounds")
async def api_panel_server_inbounds(server_id: int, admin=Depends(require_permission("panels"))):
    server = (await asyncio.to_thread(db.get_panel_server, server_id))
    if not server:
        raise HTTPException(404, "یافت نشد.")
    try:
        provider = get_provider(server)
        inbounds = await provider.list_inbounds()
    except PanelError as e:
        raise HTTPException(400, str(e))
    return inbounds


@app.post("/api/panel-servers/{server_id}/xui-config")
async def api_set_panel_server_xui_config(server_id: int, body: PanelServerXuiConfigBody, admin=Depends(require_permission("panels"))):
    """تکمیل ساخت سرور برای پنل‌های نیازمند «آدرس پایه‌ی Subscription» (3X-UI/Hiddify)."""
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, "یافت نشد.")
    if server["panel_type"] not in SUB_BASE_URL_PANEL_TYPES:
        raise HTTPException(400, "این سرور به این تنظیمات نیاز ندارد.")
    if server["panel_type"] in INBOUND_SELECT_PANEL_TYPES and not body.inbound_id:
        raise HTTPException(400, "انتخاب inbound برای این نوع پنل الزامی است.")
    url = body.sub_base_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(400, "آدرس Subscription باید با http:// یا https:// شروع شود.")
    db.update_panel_server(server_id, xui_inbound_id=body.inbound_id, xui_sub_base_url=url)
    db.log_admin_action(admin["id"], "panel_update", f"xui-config سرور #{server_id} (پنل وب)", "panel", server_id)
    return {"ok": True}


@app.post("/api/panel-servers/{server_id}/template")
async def api_set_panel_server_template(server_id: int, body: PanelServerTemplateBody, admin=Depends(require_permission("panels"))):
    """گرفتن/به‌روزرسانی قالب (group_ids/proxy_settings) از روی یک کاربر نمونه‌ی
    دیگر روی پنل - برای پنل‌های خانواده‌ی PasarGuard/Marzban/Marzneshin."""
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, "یافت نشد.")
    try:
        provider = get_provider(server)
        template = await provider.fetch_template_from_user(body.template_username.strip())
    except PanelError as e:
        raise HTTPException(400, str(e))
    db.update_panel_server(
        server_id, group_ids=json.dumps(template["group_ids"]),
        proxy_settings=json.dumps(template["proxy_settings"]), template_username=body.template_username.strip(),
    )
    db.log_admin_action(admin["id"], "panel_update", f"template سرور #{server_id} (پنل وب)", "panel", server_id)
    return {"ok": True}


@app.post("/api/panel-servers/{server_id}/toggle")
def api_toggle_panel_server(server_id: int, admin=Depends(require_permission("panels"))):
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, "یافت نشد.")
    db.update_panel_server(server_id, is_active=0 if server["is_active"] else 1)
    db.log_admin_action(admin["id"], "panel_toggle", f"سرور #{server_id} (پنل وب)", "panel", server_id)
    return {"ok": True}


@app.post("/api/panel-servers/{server_id}/usage/{kind}")
def api_toggle_panel_server_usage(server_id: int, kind: str, admin=Depends(require_permission("panels"))):
    """مشخص‌کردن این‌که این سرور برای «کانفیگ شخصی» و/یا «کانفیگ تست» استفاده شود؛
    قبلاً این کلیدها فقط از داخل ربات/مینی‌اپ قابل تنظیم بودند."""
    if kind not in ("custom", "test"):
        raise HTTPException(400, "نوع مصرف نامعتبر است.")
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, "یافت نشد.")
    field = "used_for_custom_config" if kind == "custom" else "used_for_test_config"
    db.update_panel_server(server_id, **{field: 0 if server[field] else 1})
    db.log_admin_action(admin["id"], "panel_usage_toggle", f"سرور #{server_id} | {field} (پنل وب)", "panel", server_id)
    return {"ok": True}


@app.put("/api/panel-servers/{server_id}")
def api_update_panel_server(server_id: int, body: PanelServerUpdateBody, admin=Depends(require_permission("panels"))):
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, "یافت نشد.")
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if fields:
        db.update_panel_server(server_id, **fields)
    db.log_admin_action(admin["id"], "panel_update", str(server_id), "panel", server_id)
    return {"ok": True}


@app.delete("/api/panel-servers/{server_id}")
def api_delete_panel_server(server_id: int, force: bool = False, admin=Depends(require_permission("panels"))):
    try:
        removed = db.delete_panel_server(server_id, force=force)
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.log_admin_action(
        admin["id"], "panel_delete",
        str(server_id) + (f" + {removed} کانفیگ شخصی مرتبط" if removed else ""),
        "panel", server_id,
    )
    return {"ok": True, "removed_custom_configs": removed}


@app.post("/api/panel-servers/{server_id}/test")
async def api_test_panel_server(server_id: int, admin=Depends(require_permission("panels"))):
    server = (await asyncio.to_thread(db.get_panel_server, server_id))
    if not server:
        raise HTTPException(404, "یافت نشد.")
    try:
        provider = get_provider(server)
        ok = await provider.test_connection()
    except PanelError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": ok}


# ----------------------------------------------------------- exchange rate --


def _rate_response(ok: bool, status: dict, error: Optional[str] = None) -> dict:
    ts = status.get("ts") or 0
    return {
        "ok": ok,
        "rate": status.get("rate"),
        "source": status.get("source"),
        "updated_at": datetime.fromtimestamp(ts).isoformat(sep=" ") if ts else None,
        "cache_ttl_seconds": exchange_rate.CACHE_TTL_SECONDS,
        "error": error,
    }


def _manual_fallback_rate() -> Optional[float]:
    try:
        value = float(db.get_setting("manual_usd_rate_toman", "0") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


@app.get("/api/exchange-rate")
async def api_exchange_rate(admin=Depends(require_permission("panels"))):
    """نرخ فعلی دلار به تومان (از کش یا در صورت انقضا، از منابع خارجی) + نام منبع."""
    try:
        await exchange_rate.get_usd_to_toman_rate(manual_fallback=_manual_fallback_rate())
        return _rate_response(True, exchange_rate.get_cache_status())
    except Exception as e:
        # حتی اگر دریافت زنده شکست بخورد، هر مقدار کش‌شده‌ی قدیمی را نشان بده
        return _rate_response(False, exchange_rate.get_cache_status(), str(e))


@app.post("/api/exchange-rate/refresh")
async def api_exchange_rate_refresh(admin=Depends(require_permission("panels"))):
    """کش نرخ را باطل و دوباره از منابع خارجی (tgju/نوبیتکس/والکس/coingecko) دریافت می‌کند."""
    try:
        status = await exchange_rate.refresh_rate(manual_fallback=_manual_fallback_rate())
    except Exception as e:
        raise HTTPException(502, str(e))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "exchange_rate_refresh",
        f"نرخ دلار به {status['rate']:,} تومان (منبع: {status['source']}) رفرش شد (پنل وب - {admin['username']})",
    ))
    return _rate_response(True, status)


# --------------------------------------------------------------- settings --


@app.get("/api/settings")
def api_settings(admin=Depends(require_permission("settings"))):
    return db.get_all_settings()


class SettingBody(BaseModel):
    key: str
    value: str


@app.post("/api/settings")
def api_set_setting(body: SettingBody, admin=Depends(require_permission("settings"))):
    db.set_setting(body.key, body.value)
    db.log_admin_action(admin["id"], "setting_change", f"{body.key}={body.value} (پنل وب - {admin['username']})", "setting", body.key)
    return {"ok": True}


# --------------------------------------------------- درگاه‌های پرداخت سفارشی/پویا -----
# هر API پرداختی که ادمین بخواهد (بدون نوشتن کد) از همین‌جا وصل می‌شود؛ خودِ
# فاکتور/چک‌اوت مشتری از داخل مینی‌اپ تلگرام انجام می‌شود (این پنل فقط تنظیمات
# را می‌سازد که هر دو سرویس، روی همان دیتابیس تننت، به‌اشتراک می‌گذارند).

def _gw_load(gateway_id: int = None, gateway_key: str = None):
    row = db.get_custom_gateway(gateway_id) if gateway_id else db.get_custom_gateway_by_key(gateway_key)
    if not row:
        raise HTTPException(status_code=404, detail="این درگاه پیدا نشد.")
    try:
        config = json.loads(row["config_json"])
    except Exception:
        config = {}
    return row, config


def _gw_mask(row, config: dict) -> dict:
    creds = dict(config.get("credentials") or {})
    masked_creds = {}
    field_meta = {f.get("name"): f for f in (config.get("credential_fields") or [])}
    for k, v in creds.items():
        is_secret = field_meta.get(k, {}).get("secret", True)
        if is_secret and v:
            v = f"...{str(v)[-4:]}" if len(str(v)) > 4 else "•••"
        masked_creds[k] = v
    out_config = dict(config)
    out_config["credentials"] = masked_creds
    return {
        "id": row["id"], "key": row["gateway_key"], "name": row["name"],
        "enabled": bool(row["enabled"]), "config": out_config,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


class CustomGatewayIn(BaseModel):
    key: str
    name: str
    enabled: bool = False
    config: dict


@app.get("/api/gateways")
def api_list_gateways(admin=Depends(require_permission("settings"))):
    rows = db.list_custom_gateways()
    out = []
    for row in rows:
        try:
            config = json.loads(row["config_json"])
        except Exception:
            config = {}
        out.append(_gw_mask(row, config))
    return out


@app.get("/api/gateways/{gateway_id}")
def api_get_gateway(gateway_id: int, admin=Depends(require_permission("settings"))):
    row, config = _gw_load(gateway_id=gateway_id)
    return _gw_mask(row, config)


@app.post("/api/gateways")
def api_create_gateway(body: CustomGatewayIn, admin=Depends(require_permission("settings"))):
    key = "".join(ch for ch in body.key.strip().lower() if ch.isalnum() or ch in ("-", "_"))
    if not key:
        raise HTTPException(status_code=400, detail="کلید درگاه نامعتبر است (فقط حروف/عدد انگلیسی، - و _).")
    if db.get_custom_gateway_by_key(key):
        raise HTTPException(status_code=400, detail="درگاهی با همین کلید قبلاً ثبت شده.")
    gateway_id = db.create_custom_gateway(key, body.name.strip() or key, body.config, body.enabled)
    db.log_admin_action(admin["id"], "custom_gateway_create", f"درگاه سفارشی «{body.name}» ({key}) اضافه شد (پنل وب - {admin['username']}).")
    row, config = _gw_load(gateway_id=gateway_id)
    return _gw_mask(row, config)


@app.put("/api/gateways/{gateway_id}")
def api_update_gateway(gateway_id: int, body: CustomGatewayIn, admin=Depends(require_permission("settings"))):
    row, existing_config = _gw_load(gateway_id=gateway_id)

    # مقادیر محرمانه‌ای که ادمین در فرم دست‌نخورده گذاشته (ماسک‌شده نمایش داده شده بودند)
    # با «...abcd» شروع می‌شوند؛ با مقدار واقعی قبلی جایگزین می‌شوند تا رمز از بین نرود.
    new_creds = dict((body.config or {}).get("credentials") or {})
    old_creds = dict(existing_config.get("credentials") or {})
    for k, v in list(new_creds.items()):
        if isinstance(v, str) and (v.startswith("...") or v == "•••") and k in old_creds:
            new_creds[k] = old_creds[k]
    body.config["credentials"] = new_creds

    db.update_custom_gateway(gateway_id, name=body.name.strip() or row["name"], config=body.config, enabled=body.enabled)
    db.log_admin_action(admin["id"], "custom_gateway_update", f"درگاه سفارشی «{row['name']}» ویرایش شد (پنل وب - {admin['username']}).")
    row, config = _gw_load(gateway_id=gateway_id)
    return _gw_mask(row, config)


@app.delete("/api/gateways/{gateway_id}")
def api_delete_gateway(gateway_id: int, admin=Depends(require_permission("settings"))):
    row, _ = _gw_load(gateway_id=gateway_id)
    db.delete_custom_gateway(gateway_id)
    db.log_admin_action(admin["id"], "custom_gateway_delete", f"درگاه سفارشی «{row['name']}» حذف شد (پنل وب - {admin['username']}).")
    return {"ok": True}


class CustomGatewayTestRequest(BaseModel):
    amount_toman: int = 1000


@app.post("/api/gateways/{gateway_id}/test")
async def api_test_gateway(gateway_id: int, body: CustomGatewayTestRequest, admin=Depends(require_permission("settings"))):
    """یک فاکتور واقعی آزمایشی می‌سازد تا قبل از فعال‌کردن درگاه برای مشتری‌ها، مطمئن
    شوی URL/هدر/بدنه و مسیرهای پاسخ درست تنظیم شده‌اند. توجه: چون این یک درخواست واقعی
    به API درگاه است، ممکن است یک فاکتور واقعی نزد آن درگاه بسازد."""
    row, config = _gw_load(gateway_id=gateway_id)
    if not API_BASE_URL:
        return {"success": False, "error": "آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است."}
    gw = payment_engine.GenericGateway(config)
    tenant = _current_tenant.get()
    our_ref = f"test-{gateway_id}-{int(time.time())}"
    try:
        result = await gw.create_invoice(
            amount=body.amount_toman, amount_toman=body.amount_toman,
            order_id=our_ref, currency="IRT", description="تست اتصال درگاه",
            tenant_id=tenant.slug or "main",
            callback_url=f"{API_BASE_URL}/api/pay/custom/{row['gateway_key']}/return?b={tenant.slug}&txn={our_ref}",
            webhook_url=f"{API_BASE_URL}/api/webhooks/custom/{row['gateway_key']}?b={tenant.slug}",
        )
    except payment_engine.PaymentEngineError as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "invoice_url": result.get("invoice_url"), "txn_id": result.get("txn_id")}


# ------------------------------------------------------------- تنظیمات کامل فروش -----
# این بخش‌ها قبلاً فقط از داخل ربات یا مینی‌اپ قابل تنظیم بودند و در پنل وب
# مستقل اصلاً وجود نداشتند (رفرال، گردونه‌شانس، کریپتو، یادآوری تمدید/حجم،
# کانفیگ تست، عضویت اجباری کانال، هشدار موجودی، بنرها). این‌جا برای هماهنگی
# کامل با ربات و مینی‌اپ اضافه شده‌اند.


class ReferralSettingsBody(BaseModel):
    enabled: bool
    percent: int
    commission_max_count: int = 0
    free_config_enabled: bool = False
    free_config_threshold: int = 10
    free_config_product_id: Optional[int] = None
    invite_bonus_enabled: bool = False
    invite_bonus_amount: int = 0
    invite_bonus_max_count: int = 0


@app.get("/api/settings/referral")
def api_get_referral_settings(admin=Depends(require_permission("settings"))):
    fc_product_id = db.get_setting("referral_free_config_product_id", "") or ""
    return {
        "enabled": db.get_setting("referral_enabled", "1") == "1",
        "percent": int(db.get_setting("referral_percent", "10") or 0),
        "commission_max_count": int(db.get_setting("referral_commission_max_count", "0") or 0),
        "free_config_enabled": db.get_setting("referral_free_config_enabled", "0") == "1",
        "free_config_threshold": int(db.get_setting("referral_free_config_threshold", "10") or 0),
        "free_config_product_id": int(fc_product_id) if fc_product_id else None,
        "invite_bonus_enabled": db.get_setting("referral_invite_bonus_enabled", "0") == "1",
        "invite_bonus_amount": int(db.get_setting("referral_invite_bonus_amount", "0") or 0),
        "invite_bonus_max_count": int(db.get_setting("referral_invite_bonus_max_count", "0") or 0),
    }


@app.post("/api/settings/referral")
def api_set_referral_settings(body: ReferralSettingsBody, admin=Depends(require_permission("settings"))):
    if body.percent < 0 or body.percent > 100:
        raise HTTPException(400, "درصد باید بین ۰ تا ۱۰۰ باشد.")
    if body.commission_max_count < 0:
        raise HTTPException(400, "سقف تعداد نفرات نمی‌تواند منفی باشد.")
    if body.free_config_threshold < 0 or body.invite_bonus_amount < 0 or body.invite_bonus_max_count < 0:
        raise HTTPException(400, "مقادیر عددی نمی‌توانند منفی باشند.")

    product = None
    if body.free_config_product_id:
        product = db.get_product(body.free_config_product_id)
        if not product:
            raise HTTPException(400, "محصول جایزه یافت نشد.")
        if not product["is_auto_provision"] or not product["provision_server_id"]:
            raise HTTPException(400, "محصول جایزه باید «تحویل خودکار» داشته باشد و به یک پنل وصل باشد.")
    if body.free_config_enabled and (not body.free_config_product_id or body.free_config_threshold < 1):
        raise HTTPException(400, "برای فعال‌سازی کانفیگ رایگان، محصول جایزه و آستانه‌ی معتبر (حداقل ۱) لازم است.")
    if body.invite_bonus_enabled and body.invite_bonus_amount <= 0:
        raise HTTPException(400, "برای فعال‌سازی شارژ به‌ازای دعوت، مبلغ باید بزرگ‌تر از صفر باشد.")

    db.set_setting("referral_enabled", "1" if body.enabled else "0")
    db.set_setting("referral_percent", str(body.percent))
    db.set_setting("referral_commission_max_count", str(body.commission_max_count))
    db.set_setting("referral_free_config_enabled", "1" if body.free_config_enabled else "0")
    db.set_setting("referral_free_config_threshold", str(body.free_config_threshold))
    db.set_setting("referral_free_config_product_id", str(body.free_config_product_id) if body.free_config_product_id else "")
    db.set_setting("referral_invite_bonus_enabled", "1" if body.invite_bonus_enabled else "0")
    db.set_setting("referral_invite_bonus_amount", str(body.invite_bonus_amount))
    db.set_setting("referral_invite_bonus_max_count", str(body.invite_bonus_max_count))
    db.log_admin_action(admin["id"], "setting_change", f"referral settings (پنل وب - {admin['username']})", "setting", "referral")
    return {"ok": True}


class WheelSettingsBody(BaseModel):
    enabled: bool
    win_percent: int
    prizes: list[int]
    expiry_hours: int
    cooldown_hours: int


@app.get("/api/settings/wheel")
def api_get_wheel_settings(admin=Depends(require_permission("settings"))):
    return db.get_wheel_settings()


@app.post("/api/settings/wheel")
def api_set_wheel_settings(body: WheelSettingsBody, admin=Depends(require_permission("settings"))):
    if body.win_percent < 0 or body.win_percent > 100:
        raise HTTPException(400, "درصد برد باید بین ۰ تا ۱۰۰ باشد.")
    if not body.prizes or any(p <= 0 for p in body.prizes):
        raise HTTPException(400, "حداقل یک جایزه‌ی معتبر (بزرگ‌تر از صفر) لازم است.")
    if body.expiry_hours <= 0 or body.cooldown_hours <= 0:
        raise HTTPException(400, "مقادیر ساعت باید بزرگ‌تر از صفر باشند.")
    db.set_setting("wheel_enabled", "1" if body.enabled else "0")
    db.set_setting("wheel_win_percent", str(body.win_percent))
    db.set_wheel_prizes(body.prizes)
    db.set_setting("wheel_code_expiry_hours", str(body.expiry_hours))
    db.set_setting("wheel_cooldown_hours", str(body.cooldown_hours))
    db.log_admin_action(admin["id"], "setting_change", f"wheel updated (پنل وب - {admin['username']})", "setting", "wheel")
    return {"ok": True}





class RenewalSettingsBody(BaseModel):
    enabled: bool
    days_before: int
    discount_percent: int
    discount_expiry_hours: int


@app.get("/api/settings/renewal")
def api_get_renewal_settings(admin=Depends(require_permission("settings"))):
    return db.get_renewal_settings()


@app.post("/api/settings/renewal")
def api_set_renewal_settings(body: RenewalSettingsBody, admin=Depends(require_permission("settings"))):
    if body.discount_percent < 0 or body.discount_percent > 100:
        raise HTTPException(400, "درصد تخفیف باید بین ۰ تا ۱۰۰ باشد.")
    if body.days_before <= 0 or body.discount_expiry_hours <= 0:
        raise HTTPException(400, "مقادیر روز/ساعت باید بزرگ‌تر از صفر باشند.")
    db.set_setting("renewal_reminder_enabled", "1" if body.enabled else "0")
    db.set_setting("renewal_reminder_days_before", str(body.days_before))
    db.set_setting("renewal_discount_percent", str(body.discount_percent))
    db.set_setting("renewal_discount_expiry_hours", str(body.discount_expiry_hours))
    db.log_admin_action(admin["id"], "setting_change", "renewal settings updated (پنل وب)", "setting", "renewal")
    return {"ok": True}


class VolumeReminderSettingsBody(BaseModel):
    enabled: bool
    mode: str
    percent: int
    gb_left: int
    discount_percent: int
    discount_expiry_hours: int


@app.get("/api/settings/volume-reminder")
def api_get_volume_reminder_settings(admin=Depends(require_permission("settings"))):
    return db.get_volume_reminder_settings()


@app.post("/api/settings/volume-reminder")
def api_set_volume_reminder_settings(body: VolumeReminderSettingsBody, admin=Depends(require_permission("settings"))):
    if body.mode not in ("percent", "gb"):
        raise HTTPException(400, "مبنای آستانه باید percent یا gb باشد.")
    if body.discount_percent < 0 or body.discount_percent > 100:
        raise HTTPException(400, "درصد تخفیف باید بین ۰ تا ۱۰۰ باشد.")
    if not (0 < body.percent < 100):
        raise HTTPException(400, "درصد آستانه باید بین ۱ تا ۹۹ باشد.")
    if body.gb_left <= 0:
        raise HTTPException(400, "آستانه‌ی گیگابایت باید بزرگ‌تر از صفر باشد.")
    if body.discount_expiry_hours <= 0:
        raise HTTPException(400, "اعتبار کد تخفیف باید بزرگ‌تر از صفر باشد.")
    db.set_setting("volume_reminder_enabled", "1" if body.enabled else "0")
    db.set_setting("volume_reminder_mode", body.mode)
    db.set_setting("volume_reminder_percent", str(body.percent))
    db.set_setting("volume_reminder_gb_left", str(body.gb_left))
    db.set_setting("volume_discount_percent", str(body.discount_percent))
    db.set_setting("volume_discount_expiry_hours", str(body.discount_expiry_hours))
    db.log_admin_action(admin["id"], "setting_change", "volume reminder settings updated (پنل وب)", "setting", "volume_reminder")
    return {"ok": True}


class TestConfigSettingsBody(BaseModel):
    enabled: bool
    panel_volume_gb: int
    panel_duration_days: int


@app.get("/api/settings/test-config")
def api_get_test_config_settings(admin=Depends(require_permission("settings"))):
    return {
        "enabled": db.get_setting("test_enabled", "1") == "1",
        "panel_volume_gb": int(db.get_setting("test_config_panel_volume_gb", "1") or 1),
        "panel_duration_days": int(db.get_setting("test_config_panel_duration_days", "1") or 1),
        "bank_stock": db.count_available_test_configs(),
        "panel_server": (lambda s: {"id": s["id"], "name": s["name"]} if s else None)(db.get_panel_server_for_usage("test_config")),
    }


@app.post("/api/settings/test-config")
def api_set_test_config_settings(body: TestConfigSettingsBody, admin=Depends(require_permission("settings"))):
    if body.panel_volume_gb <= 0 or body.panel_duration_days <= 0:
        raise HTTPException(400, "حجم و مدت باید بزرگ‌تر از صفر باشند.")
    db.set_setting("test_enabled", "1" if body.enabled else "0")
    db.set_setting("test_config_panel_volume_gb", str(body.panel_volume_gb))
    db.set_setting("test_config_panel_duration_days", str(body.panel_duration_days))
    db.log_admin_action(admin["id"], "setting_change", "test config settings updated (پنل وب)", "setting", "test_config")
    return {"ok": True}


@app.post("/api/settings/test-config/reset-all")
def api_reset_all_test_configs(admin=Depends(require_permission("settings"))):
    """معادل «بازنشانی کانفیگ تست برای همه» در ربات: امکان دریافت مجدد کانفیگ تست برای همه‌ی کاربران."""
    count = db.reset_all_test_usage()
    db.log_admin_action(admin["id"], "test_config_reset_all", f"{count} کاربر (پنل وب - {admin['username']})", "setting", "test_config")
    return {"ok": True, "count": count}


class ForceJoinSettingsBody(BaseModel):
    enabled: bool
    channel: str = ""


@app.get("/api/settings/force-join")
def api_get_force_join_settings(admin=Depends(require_permission("settings"))):
    return db.get_force_join_settings()


@app.post("/api/settings/force-join")
def api_set_force_join_settings(body: ForceJoinSettingsBody, admin=Depends(require_permission("settings"))):
    channel = (body.channel or "").strip()
    if body.enabled and not channel:
        raise HTTPException(400, "برای فعال‌سازی، آیدی کانال الزامی است.")
    db.set_setting("force_join_enabled", "1" if body.enabled else "0")
    db.set_setting("force_join_channel", channel)
    db.log_admin_action(admin["id"], "setting_change", f"force_join_channel={channel} (پنل وب - {admin['username']})", "setting", "force_join")
    return {"ok": True}


class StockAlertSettingsBody(BaseModel):
    threshold: int


@app.get("/api/settings/stock-alert")
def api_get_stock_alert_settings(admin=Depends(require_permission("settings"))):
    return {"threshold": int(db.get_setting("stock_alert_threshold", "5") or 5)}


@app.post("/api/settings/stock-alert")
def api_set_stock_alert_settings(body: StockAlertSettingsBody, admin=Depends(require_permission("settings"))):
    if body.threshold < 0:
        raise HTTPException(400, "آستانه نمی‌تواند منفی باشد.")
    db.set_setting("stock_alert_threshold", str(body.threshold))
    db.log_admin_action(admin["id"], "setting_change", f"stock_alert_threshold={body.threshold} (پنل وب - {admin['username']})", "setting", "stock_alert")
    return {"ok": True}


# ------------------------------------------------------------------ بنرها --


class BannerItemBody(BaseModel):
    text: str
    image_url: Optional[str] = None
    enabled: bool = True


class BannersUpdateBody(BaseModel):
    banners: list[BannerItemBody]


@app.get("/api/banners")
def api_get_banners(admin=Depends(require_permission("settings"))):
    return db.get_banners()


@app.post("/api/banners/upload-image")
async def api_upload_banner_image(photo: UploadFile = File(...), admin=Depends(require_permission("settings"))):
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(400, "فقط فایل تصویری مجاز است.")
    content = await photo.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(400, "حجم تصویر نباید بیشتر از ۲ مگابایت باشد.")
    ext = os.path.splitext(photo.filename or "")[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    fname = f"banner_{int(time.time()*1000)}{ext}"
    dest_dir = os.path.join(BASE_DIR, "static", "uploads", "banners")
    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, fname), "wb") as f:
        f.write(content)
    return {"url": f"/static/uploads/banners/{fname}"}


@app.post("/api/banners")
def api_save_banners(body: BannersUpdateBody, admin=Depends(require_permission("settings"))):
    if len(body.banners) > 20:
        raise HTTPException(400, "حداکثر ۲۰ بنر مجاز است.")
    clean = []
    for b in body.banners:
        text = (b.text or "").strip()
        if not text:
            continue
        clean.append({"text": text, "image_url": b.image_url, "enabled": bool(b.enabled)})
    db.set_banners(clean)
    db.log_admin_action(admin["id"], "setting_change", f"{len(clean)} بنر ذخیره شد (پنل وب - {admin['username']})", "setting", "banners")
    return {"ok": True, "banners": clean}


# --------------------------------------------- نمایندگان اعتباری (Credit) --
# توجه: این قابلیت از قبل در همین پنل زیر مسیر /api/resellers پیاده‌سازی شده
# بود (adjust credit/status/panel/log/cohort/orphans) - همان‌جا کامل‌تر هم
# هست (شامل آمار فروش و purge). چیزی این‌جا اضافه نشد تا دو سیستم موازی
# ساخته نشود؛ گپ واقعی فقط در مینی‌اپ بود که در miniapp/server.py اضافه شد.


# ------------------------------------------------------------- منوی قیمت‌گذاری بازه‌ای و تنظیمات کانفیگ شخصی --
# معادل adm_pricing_tiers / تنظیمات custom_config در ربات و مینی‌اپ؛ در پنل
# وب مستقل اصلاً وجود نداشت.


class CustomConfigSettingsBody(BaseModel):
    enabled: bool
    min_gb: int
    max_gb: int
    duration_days: int


@app.get("/api/custom-config/settings")
def api_get_custom_config_settings(admin=Depends(require_permission("panels"))):
    return db.get_custom_config_settings()


@app.post("/api/custom-config/settings")
def api_set_custom_config_settings(body: CustomConfigSettingsBody, admin=Depends(require_permission("panels"))):
    if body.min_gb <= 0 or body.max_gb <= 0 or body.min_gb > body.max_gb:
        raise HTTPException(400, "بازه‌ی حجم نامعتبر است.")
    if body.duration_days <= 0:
        raise HTTPException(400, "مدت باید بزرگ‌تر از صفر باشد.")
    db.set_setting("custom_config_enabled", "1" if body.enabled else "0")
    db.set_setting("custom_config_min_gb", str(body.min_gb))
    db.set_setting("custom_config_max_gb", str(body.max_gb))
    db.set_setting("custom_config_duration_days", str(body.duration_days))
    db.log_admin_action(admin["id"], "setting_change", "custom config settings updated (پنل وب)", "setting", "custom_config")
    return {"ok": True}


@app.get("/api/custom-config/pricing-tiers")
def api_get_pricing_tiers(admin=Depends(require_permission("panels"))):
    return rows_to_list(db.get_pricing_tiers())


class PricingTierBody(BaseModel):
    from_gb: int
    to_gb: Optional[int] = None
    price_per_gb: int


@app.post("/api/custom-config/pricing-tiers")
def api_add_pricing_tier(body: PricingTierBody, admin=Depends(require_permission("panels"))):
    if body.from_gb < 0 or body.price_per_gb <= 0:
        raise HTTPException(400, "مقادیر نامعتبر است.")
    if body.to_gb is not None and body.to_gb <= body.from_gb:
        raise HTTPException(400, "سقف بازه باید بزرگ‌تر از کف بازه باشد.")
    tier_id = db.add_pricing_tier(body.from_gb, body.to_gb, body.price_per_gb)
    db.log_admin_action(admin["id"], "pricing_tier_add", f"{body.from_gb}-{body.to_gb} = {body.price_per_gb} (پنل وب)")
    return {"id": tier_id}


@app.delete("/api/custom-config/pricing-tiers/{tier_id}")
def api_delete_pricing_tier(tier_id: int, admin=Depends(require_permission("panels"))):
    db.delete_pricing_tier(tier_id)
    db.log_admin_action(admin["id"], "pricing_tier_delete", str(tier_id), "setting", "pricing_tier")
    return {"ok": True}


# ------------------------------------------------------------- menu order --


@app.get("/api/settings/menu-order")
def api_menu_order_get(admin=Depends(require_permission("settings"))):
    settings = db.get_all_settings()
    order = db.get_menu_order()
    row_breaks = db.get_menu_row_breaks()
    break_set = set(row_breaks) if row_breaks is not None else None
    result = []
    for key in order:
        meta = MENU_BUTTON_META.get(key)
        if not meta:
            continue
        item = {
            "key": key, "label": meta["label"], "admin_only": meta["admin_only"],
            "togglable": meta["toggle_key"] is not None,
        }
        if meta["toggle_key"]:
            item["enabled"] = settings.get(meta["toggle_key"], "1") == "1"
        # break_before یعنی این دکمه یک ردیف تازه در منو شروع می‌کند (کنار دکمه‌ی
        # قبلی‌اش قرار نمی‌گیرد). اگر کاربر هنوز چیدمان سفارشی نساخته باشد
        # (break_set is None)، null برمی‌گردد تا فرانت‌اند بداند هنوز از حالت
        # قدیمی «تعداد ستون ثابت» استفاده می‌شود.
        item["break_before"] = (key in break_set) if break_set is not None else None
        result.append(item)
    return result


class MenuButtonToggle(BaseModel):
    key: str
    enabled: bool


def _apply_menu_button_toggles(buttons: Optional[list[MenuButtonToggle]]):
    for btn in buttons or []:
        meta = MENU_BUTTON_META.get(btn.key)
        if meta and meta["toggle_key"]:
            db.set_setting(meta["toggle_key"], "1" if btn.enabled else "0")


class MenuOrderBody(BaseModel):
    order: list[str]
    buttons: Optional[list[MenuButtonToggle]] = None


@app.post("/api/settings/menu-order")
def api_menu_order_set(body: MenuOrderBody, admin=Depends(require_permission("settings"))):
    db.set_menu_order(body.order)
    _apply_menu_button_toggles(body.buttons)
    db.log_admin_action(admin["id"], "menu_order_change", f"ترتیب منوی ربات تغییر کرد (پنل وب - {admin['username']})", "setting", "menu_order")
    return {"ok": True}


class MenuLayoutBody(BaseModel):
    order: list[str]
    breaks: list[str]
    buttons: Optional[list[MenuButtonToggle]] = None


@app.post("/api/settings/menu-layout")
def api_menu_layout_set(body: MenuLayoutBody, admin=Depends(require_permission("settings"))):
    """مثل /settings/menu-order ولی علاوه بر ترتیب، چیدمان ردیف‌ها (کدام دکمه‌ها
    کنار هم و کدام‌ها در ردیف جدا قرار بگیرند) را هم ذخیره می‌کند - یعنی چیدمان
    آزاد (نه فقط بالا/پایین با تعداد ستون ثابت)."""
    db.set_menu_order(body.order)
    db.set_menu_row_breaks(body.breaks)
    _apply_menu_button_toggles(body.buttons)
    db.log_admin_action(admin["id"], "menu_order_change", f"چیدمان منوی ربات تغییر کرد (پنل وب - {admin['username']})", "setting", "menu_order")
    return {"ok": True}


# ----------------------------------------------------------------- logs ---


@app.get("/api/admin-logs")
def api_admin_logs(
    page: int = 1, action: Optional[str] = None, record_type: Optional[str] = None,
    record_id: Optional[str] = None, admin=Depends(require_permission("system")),
):
    limit = 40
    rows, total = db.get_admin_logs(
        limit=limit, offset=(page - 1) * limit,
        action=action or None, record_type=record_type or None, record_id=record_id or None,
    )
    return {"items": rows_to_list(rows), "total": total, "page": page, "limit": limit}


@app.get("/api/admin-logs/actions")
def api_admin_log_actions(admin=Depends(require_permission("system"))):
    return {"actions": db.list_admin_log_actions()}


# ----------------------------------------------------------- web admins ---


class WebAdminCreateBody(BaseModel):
    username: str
    password: str
    role: str = "admin"
    permissions: Optional[list] = None


@app.get("/api/web-admins")
def api_web_admins(admin=Depends(require_owner)):
    rows = rows_to_list(db.list_web_admins())
    for r in rows:
        r["permissions"] = db.get_web_admin_permissions(r)
    return rows


@app.get("/api/web-admins/permissions")
def api_web_admin_permission_keys(admin=Depends(require_owner)):
    perms = [p for p in WEB_ADMIN_PERMISSIONS if p not in MAIN_TENANT_ONLY_PERMISSIONS or not admin["tenant"]]
    return {"permissions": perms}


@app.post("/api/web-admins")
def api_create_web_admin(body: WebAdminCreateBody, admin=Depends(require_owner)):
    if db.get_web_admin_by_username(body.username):
        raise HTTPException(400, "این یوزرنیم قبلاً استفاده شده.")
    if len(body.password) < 8:
        raise HTTPException(400, "پسورد باید حداقل ۸ کاراکتر باشد.")
    new_id = db.create_web_admin(body.username, hash_password(body.password), body.role, body.permissions)
    db.log_admin_action(admin["id"], "web_admin_add", f"{body.username} ({body.role})", "webadmin", new_id)
    return {"id": new_id}


class WebAdminRoleBody(BaseModel):
    role: str


@app.post("/api/web-admins/{admin_id}/role")
def api_set_web_admin_role(admin_id: int, body: WebAdminRoleBody, admin=Depends(require_owner)):
    if not db.set_web_admin_role(admin_id, body.role):
        raise HTTPException(400, "امکان تغییر نقش این حساب نیست.")
    return {"ok": True}


class WebAdminPermissionsBody(BaseModel):
    permissions: list


@app.post("/api/web-admins/{admin_id}/permissions")
def api_set_web_admin_permissions(admin_id: int, body: WebAdminPermissionsBody, admin=Depends(require_owner)):
    if not db.set_web_admin_permissions(admin_id, body.permissions):
        raise HTTPException(400, "امکان تغییر مجوزهای این حساب نیست.")
    db.log_admin_action(admin["id"], "web_admin_permissions", f"admin#{admin_id} -> {body.permissions}", "webadmin", admin_id)
    return {"ok": True}


class WebAdminActiveBody(BaseModel):
    active: bool


@app.post("/api/web-admins/{admin_id}/active")
def api_set_web_admin_active(admin_id: int, body: WebAdminActiveBody, admin=Depends(require_owner)):
    if not db.set_web_admin_active(admin_id, body.active):
        raise HTTPException(400, "امکان تغییر وضعیت این حساب نیست.")
    db.log_admin_action(admin["id"], "web_admin_active", f"admin#{admin_id} -> {body.active}", "webadmin", admin_id)
    return {"ok": True}


@app.delete("/api/web-admins/{admin_id}")
def api_delete_web_admin(admin_id: int, admin=Depends(require_owner)):
    if not db.delete_web_admin(admin_id):
        raise HTTPException(400, "امکان حذف این حساب نیست.")
    db.log_admin_action(admin["id"], "web_admin_delete", f"admin#{admin_id}", "webadmin", admin_id)
    return {"ok": True}


class MyPasswordBody(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/me/password")
def api_change_my_password(body: MyPasswordBody, admin=Depends(get_current_admin)):
    row = db.get_web_admin(admin["id"])
    if not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(400, "پسورد فعلی اشتباه است.")
    if len(body.new_password) < 8:
        raise HTTPException(400, "پسورد جدید باید حداقل ۸ کاراکتر باشد.")
    db.set_web_admin_password(admin["id"], hash_password(body.new_password))
    return {"ok": True}


# ------------------------------------------------------------------ static --

STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/sw.js")
def serve_service_worker():
    # عمداً روی ریشه‌ی دامنه سرو می‌شود (نه زیر /assets) تا scope پیش‌فرض
    # Service Worker کل پنل را بگیرد و بتواند برای هر صفحه‌ای اعلان Push نشان دهد.
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"), media_type="application/javascript")


@app.get("/manifest.json")
def serve_manifest(request: Request):
    """Web App Manifest برای قابلیت نصب (Add to Home Screen / PWA) روی اندروید
    و آیفون. چون پنل چندمستاجری است و هر نماینده با کوئری‌استرینگ ?b=... از
    بقیه جدا می‌شود، start_url باید همان b را نگه دارد وگرنه بعد از نصب،
    آیکون روی هوم‌اسکرین به پنل درست باز نمی‌شود. index.html این مسیر را با
    همان query string صفحه‌ی جاری صدا می‌زند (مثلا /manifest.json?b=xyz)."""
    b_value = request.query_params.get("b", "").strip()
    start_url = f"/?b={b_value}&source=pwa" if b_value else "/?source=pwa"
    manifest = {
        "name": "پنل مدیریت ShopVPN",
        "short_name": "ShopVPN",
        "description": "پنل مدیریت وب ShopVPN",
        "start_url": start_url,
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#0B0C14",
        "theme_color": "#0B0C14",
        "dir": "rtl",
        "lang": "fa",
        "icons": [
            {"src": "/assets/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/assets/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/assets/icons/icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/assets/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return JSONResponse(manifest, media_type="application/manifest+json")


def _asset_version(filename: str) -> int:
    try:
        return int(os.path.getmtime(os.path.join(STATIC_DIR, filename)))
    except OSError:
        return int(time.time())


def _bust_asset_cache(html: str) -> str:
    # کش‌شکن خودکار: هر بار app.js یا style.css عوض شود mtime‌شان هم عوض
    # می‌شود، پس مرورگر دیگر نسخه‌ی قدیمیِ کش‌شده را اجرا نمی‌کند — بدون
    # نیاز به دستی زیاد کردن شماره‌ی ورژن در هر دیپلوی.
    html = html.replace('src="/assets/app.js"', f'src="/assets/app.js?v={_asset_version("app.js")}"')
    html = html.replace('href="/assets/style.css"', f'href="/assets/style.css?v={_asset_version("style.css")}"')
    return html


@app.get("/", response_class=HTMLResponse)
def serve_index():
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    # کش‌شکن خودکار: هر بار app.js عوض شود mtime آن هم عوض می‌شود، پس
    # مرورگر دیگر نسخه‌ی قدیمیِ کش‌شده را اجرا نمی‌کند و مجبور به دانلود
    # مجدد است — بدون نیاز به دستی زیاد کردن شماره‌ی ورژن در هر دیپلوی.
    return _bust_asset_cache(html)


@app.get("/setup", response_class=HTMLResponse)
def serve_setup_page():
    """همان SPA سرو می‌شود؛ خود فرانت مسیر /setup را تشخیص داده و فرم راه‌اندازی
    اولیه‌ی پنل نماینده را نشان می‌دهد."""
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    return _bust_asset_cache(html)

