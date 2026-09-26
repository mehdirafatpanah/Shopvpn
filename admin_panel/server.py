# -*- coding: utf-8 -*-
"""
پنل مدیریت وب کاملاً مستقل ShopVPN - خارج از تلگرام.

لاگین با یوزرنیم/پسورد (نه initData). روی دیتابیس بات اصلی کار می‌کند.
اجرا: uvicorn admin_panel.server:app --host 127.0.0.1 --port 8002
اولین حساب (owner) را با دستور زیر بساز:
    python -m admin_panel.create_admin <username> <password>
"""

import asyncio
import base64
import contextvars
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

from i18n import tr, set_language, reset_language, normalize_language, LANGUAGE_CATALOG
from notification_i18n import localized_payload
from fastapi import FastAPI, Request, Response, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles که به مرورگر می‌گه هر بار فایل رو revalidate کنه (ETag/
    Last-Modified) و بدون سوال‌کردن از سرور کش نکنه. جواب سرور معمولاً با
    304 برمی‌گرده، پس ترافیک زیاد نمی‌شه، ولی هیچ نسخه‌ی قدیمی هم کش نمی‌مونه."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
from pydantic import BaseModel

from config import DB_PATH, BOT_TOKEN, OWNER_ID, ADMIN_PANEL_SECRET, VAPID_PUBLIC_KEY, resolve_db_path, API_BASE_URL, RESELLER_DBS_DIR
from database import Database, WEB_ADMIN_PERMISSIONS, MENU_BUTTON_META
import button_registry
import extra_gateway_registry
from admin_panel.security import hash_password, verify_password, create_session_token, verify_session_token
from admin_panel import mobile_auth
from asset_versioning import file_digest, static_version, ApiNoStoreMiddleware
from admin_panel.telegram_notify import send_message as tg_send, send_document as tg_send_document, fetch_telegram_file, get_me as tg_get_me
from admin_panel.config_delivery_web import deliver_config_to_user_web
from admin_panel.webpush import PUSH_ENABLED, send_push
import fcm_client
import report_router
from reseller_auto_provision import provision_auto_config, ProvisionError
from service_refund import quote_service_refund, refund_quote_text, grant_service_refund_credit, refund_result_text
from service_alerts import send_service_alert_sync
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from stock_alerts import check_and_notify_low_stock
import ai_support
from renewal_engine import execute_renewal, RenewalError
from panel_providers import (
    get_provider, PanelError, PanelUsernameTakenError, PANEL_TYPE_LABELS,
    PROVIDERS, SUB_BASE_URL_PANEL_TYPES, INBOUND_SELECT_PANEL_TYPES, TEMPLATE_BASED_PANEL_TYPES,
    SINGLE_INBOUND_PANEL_TYPES, TOKEN_ONLY_PANEL_TYPES, TEMPLATE_PROMPTS,
    parse_xui_inbound_ids,
)
from renewal_reminders import STATUS_KEY_LAST_RUN, STATUS_KEY_LAST_DATE_SENT, STATUS_KEY_LAST_VOLUME_SENT
from backup import create_backup, restore_backup, is_valid_sqlite_db
import exchange_rate
import geo_scan
import world_map
import payment_engine
import custom_gateway_payment

logger = logging.getLogger("admin_panel.server")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_NAME = "panel_session"
NOTIFY_POLL_SECONDS = 15

app = FastAPI(title="ShopVPN Admin Panel")

# Backend i18n: every API request gets a language context from the frontend header.
# The frontend sends X-Language based on its persisted sv-lang setting.
@app.middleware("http")
async def _i18n_request_language(request: Request, call_next):
    language = normalize_language(request.headers.get("x-language") or request.headers.get("accept-language"))
    token = set_language(language)
    try:
        response = await call_next(request)
        response.headers["Content-Language"] = language
        return response
    finally:
        reset_language(token)

app.add_middleware(ApiNoStoreMiddleware)
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
    """نماینده‌های سطح ۱ (کامل) یا سطح ۲ که پنل وبشان صریحاً فعال شده (web_panel_enabled=1)
    اجازه‌ی ورود دارند؛ نماینده‌ی غیرفعال یا بدون پنل وب فعال، حتی با اسلاگ درست هم رد می‌شود.
    برای سطح ۲، فعال‌بودن web_panel_enabled یعنی خودِ نماینده هنگام درخواست نمایندگی
    گزینه‌ی «پنل وب» را انتخاب کرده (ر.ک. wants_web_panel در reseller_requests).
    مثل مینی‌اپ، هم اسلاگ دلخواه و هم آیدی عددی بات (وقتی هنوز اسلاگ ست نشده) قبول می‌شود."""
    slug = (slug or "").strip()
    if not slug:
        return MAIN_TENANT
    row = _lookup_reseller_bot_row(slug)
    if not row:
        return None
    if not row["is_active"] or not row["web_panel_enabled"]:
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


async def _notify_admins(permission: str, payload: dict, category: str | None = None):
    subs = (await asyncio.to_thread(db.list_push_subscriptions_for_permission, permission))
    if subs:
        gone = []
        for s in subs:
            localized = localized_payload(db, int(s["admin_id"]), payload)
            result = await send_push(s, localized)
            if result == "gone":
                gone.append(s["endpoint"])
        if gone:
            (await asyncio.to_thread(db.delete_push_subscriptions_by_endpoints, gone))

    # پوش اپ موبایل (FCM) — مستقل از وب‌پوش. تنظیم‌بودنش هر بار زنده از
    # دیتابیس همین تننت چک می‌شود (نه یک پرچم ثابت زمان استارت)، تا وصل‌کردنش
    # از پنل وب فوری اثر کند و بدون ری‌استارت هم کار کند.
    # "category" باید دقیقاً با id همون تب در اپ اندروید یکی باشه؛ اپ از رویش
    # تشخیص می‌ده کاربر نوتیف همون بخش رو از تنظیمات خودش خاموش کرده یا نه
    # (نگاه کن به PushService.onMessageReceived در پروژه‌ی اندروید).
    # توجه: category با permission (پارامتر اول - برای فیلترکردن اینکه کدوم
    # ادمین‌ها اجازه‌ی دیدن این پوش رو دارن) یکی نیست؛ مثلاً شارژ کیف‌پول زیر
    # permission="orders" می‌ره (چون همون مجوز رو لازم داره) ولی توی اپ تب
    # جدا با id="topups" داره - قبلاً چون category رو مساوی permission
    # می‌ذاشتیم، خاموش‌کردن سوییچ "شارژ کیف‌پول" هیچ اثری نداشت.
    fcm_tokens = (await asyncio.to_thread(db.list_fcm_tokens_with_admins))
    if fcm_tokens:
        invalid = await fcm_client.send_to_admins(
            db, fcm_tokens, payload,
            data={"tag": payload.get("tag", ""), "category": category or permission},
        )
        for t in invalid:
            await asyncio.to_thread(db.delete_fcm_token, t)


# برچسب نوع تمدید، برای ساخت متن پوش سفارش‌های تمدید سرویس - همان مقادیر
# _RENEW_MODE_LABEL در handlers_user.py (اینجا هم لازم است چون آن دیکشنری
# private ماژول بات است و این پردازه‌ی جدا نمی‌تواند مستقیم به آن دسترسی
# داشته باشد).
_RENEW_MODE_LABEL = {"full": "تمدید کامل سرویس", "volume": "تمدید حجم سرویس", "time": "تمدید زمان سرویس", "users": "افزایش کاربر سرویس"}


def _describe_order(o) -> tuple[str, str]:
    """عنوان و توضیح نوعِ یک سفارش را برای متن پوش برمی‌گرداند - قبلاً پوش
    موبایل برای هر سفارشی (تمدید سرویس، کانفیگ شخصی، یا خرید عادی) همیشه یک
    متن یکسان و کلی می‌فرستاد («سفارش #N از فلانی») و هیچ نشانه‌ای نداشت که
    مثلاً سفارش تمدید است یا برای کدام پلن - دقیقاً همان چیزی که پیام تلگرامی
    ادمین (در handlers_user.py) از قبل نشان می‌دهد، اما پوش اپ اندروید نه."""
    if o["is_renewal"]:
        mode_label = _RENEW_MODE_LABEL.get(o["renewal_mode"], o["renewal_mode"] or "تمدید سرویس")
        target_label = "کانفیگ شخصی" if o["renewal_target_kind"] == "custom" else "کانفیگ بانک (استخر)"
        return (
            "🔄 سفارش تمدید سرویس",
            f"{mode_label} - {target_label} #{o['renewal_target_id']}",
        )
    if o["product_id"] == 0:
        return ("🛠 سفارش کانفیگ شخصی", "کانفیگ شخصی")
    product = None
    try:
        product = db.get_product(o["product_id"])
    except Exception:
        product = None
    return ("🛒 سفارش جدید", (product["name"] if product else "") or "")


_STUCK_METHOD_LABELS = {
    "abangateway": "آبان‌گیت‌وی",
    "blupal": "بلوپال",
    "noapay": "NoapayBot",
    "card_auto": "کارت‌به‌کارت خودکار",
}

# شناسه‌های (روش/جدول، id فاکتور) که یک بار پوش «معطل‌مانده» برایشان رفته -
# تا هر دور دوباره اسپم نشوند. وقتی فاکتور از حالت new/pending خارج شود
# (تایید یا گیرافتاده/ناموفق)، دیگر توسط کوئری stuck برگردانده نمی‌شود و
# خودش از این‌جا هرس می‌شود.
_stuck_notified_ids = set()


async def _check_stuck_gateway_payments():
    still_stuck_ids = set()
    for method_key in _STUCK_METHOD_LABELS:
        minutes = (await asyncio.to_thread(db.get_payment_method_notify_timeout, method_key))
        if minutes <= 0:
            continue
        if not (await asyncio.to_thread(db.is_payment_method_push_enabled, method_key)):
            continue
        stuck = (await asyncio.to_thread(db.list_stuck_gateway_invoices, method_key, minutes))
        for inv in stuck:
            uid = (method_key, inv["id"])
            still_stuck_ids.add(uid)
            if uid in _stuck_notified_ids:
                continue
            _stuck_notified_ids.add(uid)
            is_topup = inv["kind"] == "wallet_topup"
            kind_label = "شارژ کیف پول" if is_topup else "سفارش"
            await _notify_admins("orders", {
                "title": "⏱ پرداخت معطل‌مانده",
                "body": f"{kind_label} #{inv['ref_id']} با {_STUCK_METHOD_LABELS[method_key]} "
                        f"بیش از {minutes} دقیقه تایید نشده - بررسی کن.",
                "tag": "stuck_payment",
            }, category="topups" if is_topup else "orders")

    for gw in (await asyncio.to_thread(db.list_custom_gateways)):
        method_key = f"custom:{gw['gateway_key']}"
        minutes = (await asyncio.to_thread(db.get_payment_method_notify_timeout, method_key))
        if minutes <= 0:
            continue
        if not (await asyncio.to_thread(db.is_payment_method_push_enabled, method_key)):
            continue
        stuck = (await asyncio.to_thread(db.list_stuck_custom_gateway_invoices, gw["id"], minutes))
        for inv in stuck:
            uid = ("custom", inv["id"])
            still_stuck_ids.add(uid)
            if uid in _stuck_notified_ids:
                continue
            _stuck_notified_ids.add(uid)
            is_topup = inv["kind"] == "wallet_topup"
            kind_label = "شارژ کیف پول" if is_topup else "سفارش"
            await _notify_admins("orders", {
                "title": "⏱ پرداخت معطل‌مانده",
                "body": f"{kind_label} #{inv['ref_id']} با درگاه «{gw['name']}» "
                        f"بیش از {minutes} دقیقه تایید نشده - بررسی کن.",
                "tag": "stuck_payment",
            }, category="topups" if is_topup else "orders")

    _stuck_notified_ids.intersection_update(still_stuck_ids)


async def _notifier_loop():
    init_orders = (await asyncio.to_thread(db.get_pending_orders))
    init_topups = (await asyncio.to_thread(db.get_pending_topups))
    init_tickets = (await asyncio.to_thread(db.get_all_tickets, "open"))
    last_order_id = max((o["id"] for o in init_orders), default=0)
    last_topup_id = max((t["id"] for t in init_topups), default=0)
    last_ticket_id = max((t["id"] for t in init_tickets), default=0)
    last_support_id = (await asyncio.to_thread(db.get_latest_user_support_message_id))
    last_panel_event_id = (await asyncio.to_thread(db.get_latest_panel_health_event_id))
    # سفارش/شارژهایی که دیده شده‌اند ولی هنوز روش پرداختشان مشخص نیست (نه
    # فاکتور درگاهی برایشان ساخته شده، نه رسیدی ارسال شده) - هر دور دوباره
    # چک می‌شوند تا همین که روش مشخص شد (و اگر پوش آن روش فعال بود) پوش برود.
    pending_order_methods = set()
    pending_topup_methods = set()
    while True:
        try:
            all_pending_orders = (await asyncio.to_thread(db.get_pending_orders))
            pending_order_methods &= {o["id"] for o in all_pending_orders}
            new_orders = [o for o in all_pending_orders if o["id"] > last_order_id]
            for o in [o for o in all_pending_orders if o["id"] in pending_order_methods] + new_orders:
                method = (await asyncio.to_thread(db.resolve_payment_method, "order", o["id"]))
                if method is None:
                    pending_order_methods.add(o["id"])
                    continue
                pending_order_methods.discard(o["id"])
                if not (await asyncio.to_thread(db.is_payment_method_push_enabled, method)):
                    continue
                user = (await asyncio.to_thread(db.get_user, o["user_id"]))
                uname = (user["username"] if user else None) or o["user_id"]
                title, kind_detail = await asyncio.to_thread(_describe_order, o)
                body = f"سفارش #{o['id']} از {uname}"
                if kind_detail:
                    body += f" ({kind_detail})"
                body += " - در انتظار بررسی است."
                await _notify_admins("orders", {
                    "title": title,
                    "body": body,
                    "tag": "orders",
                })
            if new_orders:
                last_order_id = max(o["id"] for o in new_orders)

            all_pending_topups = (await asyncio.to_thread(db.get_pending_topups))
            pending_topup_methods &= {t["id"] for t in all_pending_topups}
            new_topups = [t for t in all_pending_topups if t["id"] > last_topup_id]
            for t in [t for t in all_pending_topups if t["id"] in pending_topup_methods] + new_topups:
                method = (await asyncio.to_thread(db.resolve_payment_method, "wallet_topup", t["id"]))
                if method is None:
                    pending_topup_methods.add(t["id"])
                    continue
                pending_topup_methods.discard(t["id"])
                if not (await asyncio.to_thread(db.is_payment_method_push_enabled, method)):
                    continue
                user = (await asyncio.to_thread(db.get_user, t["user_id"]))
                uname = (user["username"] if user else None) or t["user_id"]
                await _notify_admins("orders", {
                    "title": "💳 درخواست شارژ جدید",
                    "body": f"شارژ #{t['id']} از {uname} به مبلغ {t['amount']:,} تومان.",
                    "tag": "topups",
                }, category="topups")
            if new_topups:
                last_topup_id = max(t["id"] for t in new_topups)

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
                    # توجه: این با permission="tickets" می‌ره (همون مجوزی که چت زنده
                    # لازم داره) ولی تب اپ اندروید برای چت زنده id="support" داره، نه
                    # "tickets" (نگاه کن به تعریف تب‌ها در api_app_config) - قبلاً چون
                    # category صریح نمی‌دادیم، این پیام‌ها هم مثل تیکت واقعی زیر دسته‌ی
                    # "tickets" می‌رفتن و خاموش‌کردن سوییچ "چت زنده" روشون اثر نداشت
                    # (همون باگی که در _notify_admins برای شارژ کیف‌پول مستند شده).
                    await _notify_admins("tickets", {
                        "title": "💬 پیام جدید در چت زنده",
                        "body": f"{uname}: {preview}",
                        "tag": "support",
                    }, category="support")
                last_support_id = latest_support_id

            panel_events = (await asyncio.to_thread(db.get_panel_health_events_since, last_panel_event_id))
            for ev in panel_events:
                is_down = ev["kind"] == "down"
                server_name = ev["server_name"] or f"#{ev['server_id']}"
                await _notify_admins("panels", {
                    "title": "🔴 قطعی پنل" if is_down else "🟢 پنل دوباره وصل شد",
                    "body": f"پنل «{server_name}» " + ("در دسترس نیست." if is_down else "دوباره در دسترس است."),
                    "tag": "panel_health",
                })
                last_panel_event_id = ev["id"]

            await _check_stuck_gateway_payments()
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
                                # قبلاً این هشدار فقط Web Push بود و به تلگرام نمی‌رسید؛
                                # این پروسه (پنل وب مستقل) شیء Bot از aiogram ندارد، پس
                                # با HTTP خام (توکن بات) به تاپیک «سرویس» ارسال می‌شود.
                                try:
                                    await report_router.send_raw_to_group(
                                        _bot_token(), db, "service",
                                        f"🔴 قطعی کانفیگ\n\nکانفیگ «{key}» آفلاین شده است.",
                                    )
                                except Exception:
                                    logger.warning("ارسال هشدار قطعی کانفیگ به تلگرام ناموفق بود.", exc_info=True)
                                notified_offline.add(key)
                        else:
                            offline_streak[key] = 0
                            if status == "online" and key in notified_offline:
                                await _notify_admins("panels", {
                                    "title": "🟢 اتصال مجدد کانفیگ",
                                    "body": f"کانفیگ «{key}» دوباره آنلاین شد.",
                                    "tag": f"server-status-{key}",
                                })
                                try:
                                    await report_router.send_raw_to_group(
                                        _bot_token(), db, "service",
                                        f"🟢 اتصال مجدد کانفیگ\n\nکانفیگ «{key}» دوباره آنلاین شد.",
                                    )
                                except Exception:
                                    logger.warning("ارسال اعلان بازیابی کانفیگ به تلگرام ناموفق بود.", exc_info=True)
                                notified_offline.discard(key)
        except Exception:
            logger.exception("خطا در حلقه‌ی بررسی وضعیت سرورها")
        await asyncio.sleep(interval_seconds)


async def _translation_sync_loop():
    """Keep enabled language catalogs current without admin intervention."""
    from translation_engine import prewarm_enabled_languages
    while True:
        try:
            await asyncio.to_thread(prewarm_enabled_languages, main_db)
            for row in await asyncio.to_thread(main_db.list_reseller_bots, active_only=True):
                try:
                    resolved_path = resolve_db_path(row["db_path"])
                    if not os.path.exists(resolved_path):
                        continue
                    tenant_db = Database(resolved_path)
                    tenant_db.init_db(owner_id=row["owner_telegram_id"])
                    await asyncio.to_thread(prewarm_enabled_languages, tenant_db)
                except Exception:
                    logger.exception("Automatic translation sync failed for reseller %s", row.get("id"))
        except Exception:
            logger.exception("Automatic translation sync loop failed")
        await asyncio.sleep(900)


@app.on_event("startup")
async def _start_notifier():
    # همیشه استارت می‌شود: این تسک هم پوش وب (VAPID) و هم پوش موبایل (FCM) را
    # می‌فرستد، و تنظیم‌بودن هرکدام حالا به‌صورت زنده (نه یک پرچم ثابت زمان
    # استارت پردازش) از تنظیمات همان تننت خوانده می‌شود؛ در نتیجه یک پرچم
    # سراسری واحد نمی‌تواند تشخیص بدهد که آیا لازم است این تسک اجرا شود یا نه
    # (هر تننت/نماینده می‌تواند مستقل از بقیه، فقط FCM یا فقط وب‌پوش را روشن
    # داشته باشد). هزینه‌ی این حلقه هم ناچیز است: فقط دیتابیس را برای سفارش/
    # شارژ/تیکت جدید پول می‌کند و اگر چیزی برای فرستادن نباشد کاری نمی‌کند.
    asyncio.create_task(_notifier_loop())
    asyncio.create_task(_notifier_supervisor())
    asyncio.create_task(_translation_sync_loop())
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
                # رفع باگ: شرط قبلی (`level != 1`) اعلان زنده‌ی پنل وب (سفارش/تیکت
                # جدید و ...) را فقط برای نماینده‌ی سطح ۱ (کامل) روشن می‌کرد، درحالی‌که
                # resolve_tenant_by_slug (بالاتر در همین فایل) صراحتاً به نماینده‌ی
                # سطح ۲ای هم که هنگام درخواست نمایندگی گزینه‌ی «پنل وب» را انتخاب کرده
                # (web_panel_enabled=1) اجازه‌ی ورود به پنل وب می‌دهد. نتیجه: چنین
                # نماینده‌ای وارد پنلش می‌شد ولی هیچ‌وقت پوش سفارش/تیکت جدید نمی‌گرفت.
                # معیار درست همان چیزی است که resolve_tenant_by_slug برای اجازه‌ی ورود
                # چک می‌کند: is_active (که همین حلقه با active_only=True تضمین کرده) و
                # web_panel_enabled - مستقل از سطح نمایندگی.
                enabled = bool(row["web_panel_enabled"]) if "web_panel_enabled" in row.keys() else False
                if not enabled:
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


async def _authenticate_via_mobile_token(bearer_token: str):
    """اعتبارسنجی توکن دسترسی طولانی‌مدت اپ موبایل (Authorization: Bearer ...).
    برمی‌گرداند: dict ادمین در همان قالب get_current_admin، یا None اگر معتبر نبود."""
    tenant_slug = mobile_auth.extract_tenant_slug(bearer_token)
    if tenant_slug is None:
        return None
    tenant = resolve_tenant_by_slug(tenant_slug)
    if not tenant:
        return None
    token_hash = mobile_auth.hash_token(bearer_token)
    row = await asyncio.to_thread(tenant.db.get_mobile_token_by_hash, token_hash)
    if not row:
        return None
    admin = await asyncio.to_thread(tenant.db.get_web_admin, row["admin_id"])
    if not admin or not admin["is_active"]:
        return None
    _current_tenant.set(tenant)
    admin_language = admin["language_code"] if "language_code" in admin.keys() and admin["language_code"] else "fa"
    catalog = await asyncio.to_thread(tenant.db.translation_catalog, admin_language) if admin_language not in {"fa", "en"} else None
    set_language(admin_language, catalog)
    await asyncio.to_thread(tenant.db.touch_mobile_token, row["id"])
    return {
        "id": admin["id"],
        "username": admin["username"],
        "role": admin["role"],
        "permissions": (await asyncio.to_thread(tenant.db.get_web_admin_permissions, admin)),
        "tenant": tenant.slug,
        "mobile_token_id": row["id"],
    }


async def get_current_admin(request: Request):
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        admin = await _authenticate_via_mobile_token(auth_header[7:].strip())
        if admin:
            return admin
        raise HTTPException(401, tr("توکن دسترسی نامعتبر یا باطل‌شده است."))

    token = request.cookies.get(COOKIE_NAME)
    payload = verify_session_token(ADMIN_PANEL_SECRET, token) if token else None
    if not payload:
        raise HTTPException(401, tr("نشست منقضی شده یا نامعتبر است."))

    # تننت همیشه از خودِ توکن امضاشده خوانده می‌شود، نه از کوئری URL؛ وگرنه
    # کسی با یک session کوکی معتبر می‌توانست با عوض‌کردن ?b= به دیتابیس تننت
    # دیگری دسترسی بگیرد.
    tenant = resolve_tenant_by_slug(payload.get("b", ""))
    if not tenant:
        raise HTTPException(401, tr("پنل وب این نماینده دیگر فعال نیست."))
    _current_tenant.set(tenant)

    admin = (await asyncio.to_thread(tenant.db.get_web_admin, payload["id"]))
    if not admin or not admin["is_active"]:
        raise HTTPException(401, tr("حساب کاربری غیرفعال یا حذف شده است."))
    admin_language = admin["language_code"] if "language_code" in admin.keys() and admin["language_code"] else "fa"
    catalog = await asyncio.to_thread(tenant.db.translation_catalog, admin_language) if admin_language not in {"fa", "en"} else None
    set_language(admin_language, catalog)
    reseller_profile = None
    if tenant.slug and tenant.bot_id:
        rb = await asyncio.to_thread(main_db.get_reseller_bot, tenant.bot_id)
        if rb:
            owner_tg_id = int(rb["owner_telegram_id"])
            supply = await asyncio.to_thread(main_db.get_reseller_supply, owner_tg_id)
            tier_code = await asyncio.to_thread(main_db.get_agent_tier, owner_tg_id)
            tier = await asyncio.to_thread(main_db.get_reseller_tier, tier_code) if tier_code else None
            local_configs = await asyncio.to_thread(tenant.db.get_custom_configs_for_user, owner_tg_id)
            sales = {"configs": len(local_configs), "volume_gb": sum(int(x["volume_gb"] or 0) for x in local_configs)}
            revenue_summary = await asyncio.to_thread(tenant.db.get_bot_revenue_summary)
            reseller_profile = {
                "enabled": True,
                "has_live_bot": bool(rb["has_live_bot"]) if "has_live_bot" in rb.keys() else True,
                "inline_link_enabled": await asyncio.to_thread(main_db.is_inline_reseller, owner_tg_id),
                "web_panel_enabled": bool(rb["web_panel_enabled"]) if "web_panel_enabled" in rb.keys() else False,
                "miniapp_enabled": bool(rb["miniapp_enabled"]) if "miniapp_enabled" in rb.keys() else False,
                "owner_telegram_id": owner_tg_id,
                "supply_model": supply["model"],
                "fixed_product_id": supply["product_id"],
                "tier_code": tier_code or "gold",
                "tier_title": tier["title"] if tier else ("طلایی" if supply["model"] == "fixed_product" else "VIP"),
                "tier_icon": tier["icon"] if tier else ("🥇" if supply["model"] == "fixed_product" else "💎"),
                "tier_model": tier["model"] if tier else supply["model"],
                "revenue_toman": int(revenue_summary.get("revenue_toman", 0) or 0),
                "paid_orders": int(revenue_summary.get("paid_orders", 0) or 0),
                "configs_created": int(sales.get("configs", 0) or 0),
                "volume_sold_gb": int(sales.get("volume_gb", 0) or 0),
            }
    return {
        "id": admin["id"],
        "username": admin["username"],
        "role": admin["role"],
        "permissions": (await asyncio.to_thread(tenant.db.get_web_admin_permissions, admin)),
        "tenant": tenant.slug,
        "language": await asyncio.to_thread(tenant.db.get_web_admin_language, admin["id"]),
        "reseller_profile": reseller_profile,
    }


# مجوزهایی که حتی برای owner پنل یک نماینده هم معنی ندارند (مثلاً «نمایندگی‌ها»:
# پنل وب نماینده‌ی سطح ۱ نباید بتواند نماینده‌های خودش را مدیریت کند).
MAIN_TENANT_ONLY_PERMISSIONS = {"resellers"}
# مالک پنل یک نماینده owner است، اما owner بودن نباید او را به ادمین
# دیتابیس اصلی تبدیل کند. این مجوزها فقط در tenant اصلی معنی دارند؛ برای
# نماینده مسیرهای self-service پایین‌تر استفاده می‌شوند.
TENANT_BLOCKED_PERMISSIONS = {
    # A dedicated reseller is a near-complete copy of the main bot.  The one
    # intentional tenant restriction is managing/creating other resellers.
    "resellers",
}


def require_permission(permission: str):
    def _dep(admin=Depends(get_current_admin)):
        if admin.get("tenant") and permission in TENANT_BLOCKED_PERMISSIONS:
            raise HTTPException(403, tr("این قابلیت برای نمایندگی در دسترس نیست."))
        if permission in MAIN_TENANT_ONLY_PERMISSIONS and admin["tenant"]:
            raise HTTPException(403, tr("این بخش فقط در پنل بات اصلی در دسترس است."))
        if admin["role"] != "owner" and permission not in admin["permissions"]:
            raise HTTPException(403, tr("دسترسی کافی نیست."))
        return admin
    return _dep


def require_any_permission(*permissions: str):
    """مانند require_permission ولی کافی است ادمین یکی از این دسترسی‌ها را داشته باشد
    (مثلاً /api/payment-methods هم برای مدیریت کاتالوگ لازم است هم برای تنظیمات مالی)."""
    def _dep(admin=Depends(get_current_admin)):
        if admin["role"] == "owner":
            return admin
        if not any(p in admin["permissions"] for p in permissions):
            raise HTTPException(403, tr("دسترسی کافی نیست."))
        return admin
    return _dep


def require_owner(admin=Depends(get_current_admin)):
    if admin["role"] != "owner":
        raise HTTPException(403, tr("این بخش فقط برای مالک است."))
    return admin


def require_main_tenant(admin=Depends(get_current_admin)):
    """برای بخش‌هایی که حتی برای owner پنل نماینده هم معنی ندارند (مثلاً منابع سخت‌افزاری سرور)."""
    if admin["tenant"]:
        raise HTTPException(403, tr("این بخش فقط در پنل بات اصلی در دسترس است."))
    return admin


def require_full_access_tenant(admin=Depends(get_current_admin)):
    """بند ۳.۲ اسپک (ممیزی امنیتی): پنل‌های VPN شخصی، ساخت کانفیگ دستی و بانک لینک/قیمت‌گذاری
    آن، امکاناتی هستند که طرف بات فقط با is_full_access_bot (بات اصلی) در
    دسترس‌اند. تا قبل از این‌که پنل وب برای نماینده باز شود، همین که کاربر به این پنل وارد
    می‌شد یعنی حتماً سطح ۱ بود؛ حالا که سطح ۲ هم می‌تواند پنل وب داشته باشد، owner پنل او از چک
    require_permission معمولی عبور می‌کند (owner همیشه مجاز است) و باید همین‌جا صریحاً مسدود شود."""
    # Dedicated reseller tenants are full-access tenants; the separate
    # ``resellers`` permission remains main-tenant-only via require_permission.
    return admin


@app.post("/api/login")
def api_login(body: LoginBody, response: Response):
    tenant = resolve_tenant_by_slug(body.b or "")
    if not tenant:
        raise HTTPException(401, tr("این پنل در دسترس نیست."))
    admin = tenant.db.get_web_admin_by_username(body.username)
    if not admin or not admin["is_active"] or not verify_password(body.password, admin["password_hash"]):
        raise HTTPException(401, tr("یوزرنیم یا پسورد اشتباه است."))
    token = create_session_token(
        ADMIN_PANEL_SECRET, admin["id"], admin["username"], admin["role"], tenant=tenant.slug,
    )
    tenant.db.touch_web_admin_login(admin["id"])
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", max_age=12 * 3600, path="/",
    )
    return {"id": admin["id"], "username": admin["username"], "role": admin["role"], "tenant": tenant.slug, "language": tenant.db.get_web_admin_language(admin["id"])}


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
        raise HTTPException(404, tr("لینک راه‌اندازی نامعتبر یا منقضی‌شده است."))
    if not hmac.compare_digest(row["web_panel_setup_token"], t):
        raise HTTPException(404, tr("لینک راه‌اندازی نامعتبر یا منقضی‌شده است."))
    tenant_db = Database(resolve_db_path(row["db_path"]))
    if tenant_db.count_web_admins() > 0:
        raise HTTPException(400, tr("پنل این نماینده قبلاً راه‌اندازی شده؛ از صفحه‌ی ورود استفاده کن."))
    return {"bot_username": row["bot_username"] or "", "owner_name": row["owner_name"] or ""}


@app.post("/api/setup")
def api_setup_submit(body: SetupBody, response: Response):
    row = _lookup_reseller_bot_row(body.b)
    if not row or not row["web_panel_enabled"] or not row["web_panel_setup_token"]:
        raise HTTPException(404, tr("لینک راه‌اندازی نامعتبر یا منقضی‌شده است."))
    if not hmac.compare_digest(row["web_panel_setup_token"], body.t):
        raise HTTPException(404, tr("لینک راه‌اندازی نامعتبر یا منقضی‌شده است."))

    username = (body.username or "").strip().lower()
    if len(username) < 3:
        raise HTTPException(400, tr("یوزرنیم باید حداقل ۳ کاراکتر باشد."))
    if len(body.password or "") < 8:
        raise HTTPException(400, tr("پسورد باید حداقل ۸ کاراکتر باشد."))

    tenant_db = Database(resolve_db_path(row["db_path"]))
    if tenant_db.count_web_admins() > 0:
        raise HTTPException(400, tr("پنل این نماینده قبلاً راه‌اندازی شده؛ از صفحه‌ی ورود استفاده کن."))
    if tenant_db.get_web_admin_by_username(username):
        raise HTTPException(400, tr("این یوزرنیم قبلاً استفاده شده."))

    admin_id = tenant_db.create_web_admin(username, hash_password(body.password), role="owner")
    main_db.consume_reseller_web_panel_setup_token(row["id"])

    tenant_slug = row["link_slug"] or str(row["id"])
    token = create_session_token(ADMIN_PANEL_SECRET, admin_id, username, "owner", tenant=tenant_slug)
    tenant_db.touch_web_admin_login(admin_id)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=12 * 3600, path="/")
    return {"id": admin_id, "username": username, "role": "owner", "tenant": tenant_slug}


class LanguageBody(BaseModel):
    language: str


@app.post("/api/language")
async def api_language(body: LanguageBody, admin=Depends(get_current_admin)):
    lang = normalize_language(body.language)
    tenant = _current_tenant.get()
    if not await asyncio.to_thread(tenant.db.get_language, lang):
        raise HTTPException(400, tr("زبان در حال حاضر در این پنل تعریف نشده است."))
    row = await asyncio.to_thread(tenant.db.get_language, lang)
    if not row["enabled"]:
        raise HTTPException(400, tr("این زبان در حال حاضر فعال نیست."))
    await asyncio.to_thread(tenant.db.set_web_admin_language, admin["id"], lang)
    return {"language": lang, "admin_id": admin["id"]}


@app.get("/api/languages")
async def api_languages(admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    rows = await asyncio.to_thread(tenant.db.list_languages)
    return [{"code": r["code"], "name": r["name"], "native_name": r["native_name"], "flag": r["flag"], "rtl": bool(r["rtl"]), "enabled": bool(r["enabled"]), "generated": bool(r["generated"])} for r in rows]


@app.get("/api/i18n/catalog")
async def api_i18n_catalog(language: str = Query("en"), admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    code = normalize_language(language)
    row = await asyncio.to_thread(tenant.db.get_language, code)
    if not row or not row["enabled"]:
        raise HTTPException(400, tr("این زبان در حال حاضر فعال نیست."))
    return {"language": code, "catalog": await asyncio.to_thread(tenant.db.translation_catalog, code) if code not in {"fa", "en"} else {}}


@app.post("/api/languages/{language}/enable")
async def api_enable_language(language: str, admin=Depends(require_permission("settings"))):
    tenant = _current_tenant.get()
    code = normalize_language(language)
    if code not in LANGUAGE_CATALOG or code in {"fa", "en"}:
        if code in {"fa", "en"}:
            await asyncio.to_thread(tenant.db.enable_language, code, True)
            return {"code": code, "enabled": True, "generated": True, "translated": 0}
        raise HTTPException(400, tr("این زبان در فهرست زبان‌های قابل پشتیبانی نیست."))
    from translation_engine import generate_language
    try:
        translated = await asyncio.to_thread(generate_language, tenant.db, code)
        status = await asyncio.to_thread(__import__("translation_engine", fromlist=["inspect_language"]).inspect_language, tenant.db, code)
        if status.get("missing_count"):
            raise RuntimeError(f"{status['missing_count']} translation(s) are still missing")
        await asyncio.to_thread(tenant.db.enable_language, code, True)
    except Exception as exc:
        await asyncio.to_thread(tenant.db.disable_language, code, automatic=True, error=str(exc)[:500])
        raise HTTPException(502, tr("ترجمه خودکار این زبان کامل نشد؛ زبان فعال نشد.")) from exc
    return {"code": code, "enabled": True, "generated": True, "translated": translated}


@app.post("/api/languages/{language}/disable")
async def api_disable_language(language: str, admin=Depends(require_permission("settings"))):
    tenant = _current_tenant.get()
    code = normalize_language(language)
    if code in {"fa", "en"}:
        raise HTTPException(400, tr("زبان فارسی و انگلیسی قابل غیرفعال‌سازی نیستند."))
    await asyncio.to_thread(tenant.db.disable_language, code)
    return {"code": code, "enabled": False}


@app.get("/api/i18n/status/{language}")
async def api_i18n_status(language: str, admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    from translation_engine import inspect_language
    return await asyncio.to_thread(inspect_language, tenant.db, normalize_language(language))


@app.get("/api/i18n/health")
async def api_i18n_health(admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    from translation_engine import translation_health
    return await asyncio.to_thread(translation_health, tenant.db)


@app.get("/api/i18n/health/{language}")
async def api_i18n_health_language(language: str, admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    from translation_engine import translation_health
    return await asyncio.to_thread(translation_health, tenant.db, normalize_language(language))


@app.get("/api/i18n/providers")
def api_i18n_providers(admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    from translation_engine import provider_status
    return {"providers": provider_status(tenant.db)}

@app.get("/api/i18n/dashboard")
async def api_i18n_dashboard(admin=Depends(get_current_admin)):
    """Compact translation operations dashboard for administrators.

    This is observational only: it never changes language state or translations.
    """
    tenant = _current_tenant.get()
    from translation_engine import translation_health, provider_status, catalog_version, source_catalog
    health = await asyncio.to_thread(translation_health, tenant.db)
    languages = await asyncio.to_thread(tenant.db.list_languages, False)
    manifests = {}
    histories = {}
    for row in languages:
        code = row["code"]
        manifest = await asyncio.to_thread(tenant.db.get_translation_manifest, code)
        manifests[code] = dict(manifest) if manifest else None
        if code not in {"fa", "en"}:
            histories[code] = [dict(x) for x in await asyncio.to_thread(tenant.db.list_translation_history, code, 5)]
    enabled_dynamic = [r for r in languages if r["code"] not in {"fa", "en"} and bool(r["enabled"])]
    warm = sum(1 for h in health if h["healthy"] and h["enabled"])
    quarantined = sum(1 for h in health if h["auto_quarantined"])
    pending = sum(1 for h in health if h["enabled"] and not h["healthy"])
    return {
        "catalog_version": catalog_version(source_catalog()),
        "source_count": len(source_catalog()),
        "providers": provider_status(tenant.db),
        "summary": {
            "total_languages": len(languages),
            "enabled_languages": sum(1 for r in languages if bool(r["enabled"])),
            "enabled_dynamic": len(enabled_dynamic),
            "warm_languages": warm,
            "pending_languages": pending,
            "quarantined_languages": quarantined,
        },
        "languages": health,
        "manifests": manifests,
        "history": histories,
    }


@app.get("/api/i18n/history/{language}")
async def api_i18n_history(language: str, limit: int = Query(20), admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    rows = await asyncio.to_thread(tenant.db.list_translation_history, normalize_language(language), limit)
    return [dict(r) for r in rows]


@app.post("/api/i18n/sync/{language}")
async def api_i18n_sync(language: str, admin=Depends(require_permission("settings"))):
    tenant = _current_tenant.get()
    from translation_engine import sync_language
    code = normalize_language(language)
    if code in {"fa", "en"}:
        result = await asyncio.to_thread(sync_language, tenant.db, code, allow_network=False)
        return result
    try:
        result = await asyncio.to_thread(sync_language, tenant.db, code, allow_network=True)
    except Exception as exc:
        raise HTTPException(502, tr("ترجمه خودکار این زبان کامل نشد؛ زبان فعال نشد.")) from exc
    if result.get("missing_count"):
        await asyncio.to_thread(tenant.db.disable_language, code)
    return result


@app.post("/api/i18n/sync-all")
async def api_i18n_sync_all(admin=Depends(require_permission("settings"))):
    tenant = _current_tenant.get()
    from translation_engine import sync_enabled_languages
    return await asyncio.to_thread(sync_enabled_languages, tenant.db, allow_network=True)


@app.post("/api/i18n/translate-batch")
def api_i18n_translate_batch(payload: Dict[str, Any], auth=Depends(get_current_admin)):
    from translation_engine import translate_many
    admin = auth
    tenant = _current_tenant.get()
    db = tenant.db
    language = normalize_language(payload.get("language"))
    if not is_language_enabled(db, language):
        raise HTTPException(400, tr("این زبان در حال حاضر فعال نیست."))
    texts = [str(x) for x in (payload.get("texts") or [])][:50]
    if not texts:
        return {"language": language, "catalog": {}, "verbatim": []}
    if language in {"fa", "en"}:
        return {"language": language, "catalog": {x: x for x in texts}, "verbatim": []}
    from translation_engine import split_translatable, runtime_limiter
    texts, verbatim = split_translatable(texts)
    catalog = db.translation_catalog(language)
    missing = [x for x in texts if x not in catalog]
    if missing:
        if not runtime_limiter.allow((db.db_path, admin["id"])):
            raise HTTPException(429, tr("درخواست‌های ترجمه بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید."))
        try:
            generated = translate_many(missing, language, cached=catalog, db=db)
        except Exception as exc:
            raise HTTPException(503, tr("ترجمه این زبان در دسترس نیست؛ لطفاً کمی بعد دوباره تلاش کنید.")) from exc
        unresolved = [x for x in missing if not generated.get(x)]
        if unresolved:
            raise HTTPException(503, tr("ترجمه این زبان کامل نیست؛ لطفاً کمی بعد دوباره تلاش کنید."))
        catalog.update(generated)
        db.upsert_translations(language, {x: catalog[x] for x in missing}, source="machine-runtime")
    unresolved = [x for x in texts if not catalog.get(x)]
    if unresolved:
        raise HTTPException(503, tr("ترجمه این زبان کامل نیست؛ لطفاً کمی بعد دوباره تلاش کنید."))
    return {"language": language, "catalog": {x: catalog[x] for x in texts}, "verbatim": verbatim}


@app.get("/api/me")
def api_me(admin=Depends(get_current_admin)):
    return admin


# ============================================================================
#  اپ موبایل مدیریت (Native Android) — توکن دسترسی، پیکربندی SDUI، Push (FCM)
# ============================================================================

class MobileTokenCreateBody(BaseModel):
    name: str = "دستگاه من"


@app.post("/api/app/tokens")
async def api_app_create_token(body: MobileTokenCreateBody, request: Request, admin=Depends(get_current_admin)):
    """یک توکن دسترسی طولانی‌مدت جدید برای اپ موبایل می‌سازد.
    رشته‌ی خام توکن فقط همین یک‌بار در پاسخ برمی‌گردد و هیچ‌جا ذخیره نمی‌شود."""
    tenant = _current_tenant.get()
    full_token, token_hash, prefix = mobile_auth.generate_token(tenant.slug)
    token_id = await asyncio.to_thread(
        tenant.db.create_mobile_token, admin["id"], body.name, token_hash, prefix
    )
    return {
        "id": token_id,
        "token": full_token,  # فقط همین یک بار نمایش داده می‌شود
        "name": body.name,
        # نکته: قبلاً اینجا از API_BASE_URL (تنظیمات config.py) استفاده می‌شد که
        # در واقع آدرس دامنه‌ی مینی‌اپ/سرور FastAPI اصلی است (از MINIAPP_URL
        # مشتق می‌شود)، نه آدرس همین پنل مدیریت وب که ممکن است روی دامنه/ساب‌دامنه‌ی
        # جداگانه‌ای اجرا شود (مثلاً apanel.celenor.ir در برابر botmini.celenor.ir).
        # چون اپ موبایل ادمین باید دقیقاً همین پنل ادمین را صدا بزند نه مینی‌اپ را،
        # آدرس را از خودِ درخواست HTTP فعلی می‌گیریم که همیشه درست است.
        "server_url": str(request.base_url).rstrip("/"),
    }


@app.get("/api/app/tokens")
async def api_app_list_tokens(admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    rows = await asyncio.to_thread(tenant.db.list_mobile_tokens, admin["id"])
    return [dict(r) for r in rows]


@app.delete("/api/app/tokens/{token_id}")
async def api_app_revoke_token(token_id: int, admin=Depends(get_current_admin)):
    """اگر توکن هنوز فعال است باطلش می‌کند؛ اگر قبلاً باطل شده، برای همیشه از لیست حذف می‌کند."""
    tenant = _current_tenant.get()
    ok = await asyncio.to_thread(tenant.db.revoke_mobile_token, token_id, admin["id"])
    if ok:
        return {"ok": True, "deleted": False}
    ok = await asyncio.to_thread(tenant.db.delete_mobile_token, token_id, admin["id"])
    if not ok:
        raise HTTPException(404, tr("توکن پیدا نشد."))
    return {"ok": True, "deleted": True}


class FcmTokenBody(BaseModel):
    fcm_token: str
    device_label: str = ""


@app.post("/api/app/fcm-token")
async def api_app_register_fcm(body: FcmTokenBody, admin=Depends(get_current_admin)):
    """اپ موبایل بعد از دریافت توکن Firebase، آن را اینجا ثبت می‌کند تا بات
    بتواند برای این ادمین نوتیفیکیشن پوش (سفارش جدید، تیکت جدید و ...) بفرستد."""
    tenant = _current_tenant.get()
    await asyncio.to_thread(
        tenant.db.save_fcm_token, admin["id"], admin.get("mobile_token_id"),
        body.fcm_token, body.device_label,
    )
    return {"ok": True}


@app.delete("/api/app/fcm-token")
async def api_app_unregister_fcm(body: FcmTokenBody, admin=Depends(get_current_admin)):
    tenant = _current_tenant.get()
    await asyncio.to_thread(tenant.db.delete_fcm_token, body.fcm_token)
    return {"ok": True}


@app.post("/api/app/push-test")
async def api_app_push_test(admin=Depends(get_current_admin)):
    """یک پوش واقعی به آخرین دستگاه ثبت‌شده‌ی همین ادمین می‌فرستد و خطای واقعی
    گوگل را برمی‌گرداند - تا مشخص شود مشکل سمت سرور/تنظیمات فایربیس است یا
    سمت گوشی (مجوز نوتیف/بهینه‌سازی باتری)، به‌جای حدس‌زدن از روی سکوت."""
    tenant = _current_tenant.get()
    tokens = await asyncio.to_thread(tenant.db.list_fcm_tokens, admin["id"])
    if not tokens:
        raise HTTPException(
            400,
            tr("هیچ دستگاهی برای این حساب ادمین ثبت نشده. یک‌بار از اپ اندروید خارج و دوباره وارد شو."),
        )
    result = await fcm_client.send_test(tenant.db, tokens[-1], admin_id=admin["id"])
    if result.get("reason") == "not_configured":
        raise HTTPException(400, tr("سرویس‌اکانت فایربیس روی سرور تنظیم نشده (تنظیمات > اپ موبایل)."))
    if not result.get("ok"):
        raise HTTPException(502, tr(f"ارسال ناموفق بود: {result.get('detail') or result.get('reason')}"))
    return {"ok": True}


@app.get("/app/webview-bridge")
async def app_webview_bridge(token: str, next: str = "/"):
    """پل بین PAT اپ موبایل و پنل وب کامل (که هنوز کوکی‌محور است): توکن را مثل
    get_current_admin معتبرسنجی می‌کند، یک کوکی سشن عادی برای همان تننت/ادمین
    می‌سازد و کاربر را به پنل وب (SPA تک‌صفحه‌ای، پیش‌فرض داشبورد که شامل
    نقشه‌ی سرورهاست) ریدایرکت می‌کند. توجه: پنل وب مسیر URL جدا برای هر تب
    ندارد (فقط "/" و "/setup")، پس اینجا همیشه "/" یا "/setup" معتبر است."""
    admin = await _authenticate_via_mobile_token(token)
    if not admin:
        raise HTTPException(401, tr("توکن نامعتبر است."))
    tenant = _current_tenant.get()
    session_token = create_session_token(
        ADMIN_PANEL_SECRET, admin["id"], admin["username"], admin["role"], tenant=tenant.slug,
    )
    response = RedirectResponse(url=next)
    response.set_cookie(COOKIE_NAME, session_token, httponly=True, samesite="lax", max_age=3600, path="/")
    return response


MINIAPP_THEME_OPTIONS = {
    "clean-light": "🌿 مینیمال روشن (پیش‌فرض)",
    "synthwave": "🌅 سینت‌ویو",
    "neon-mint": "🟢 نئون مینت",
    "royal-violet": "👑 بنفش سلطنتی",
    "blood-moon": "🔴 ماه خونین",
    "aurora-ice": "🧊 یخ شمالی",
}


@app.get("/api/app/config")
def api_app_config(admin=Depends(get_current_admin)):
    """پیکربندی Server-Driven UI برای اپ اندروید: تب‌های ناوبری پایین و نوع هر
    صفحه. اپ این JSON را می‌خواند و کامپوننت‌های Native متناظر را می‌سازد —
    اضافه/حذف/تغییر یک تب اینجا، بدون هیچ آپدیت اپ، همان لحظه در اپ اثر می‌کند."""
    perms = admin["permissions"]
    is_owner = admin["role"] == "owner"

    def allowed(perm: str) -> bool:
        return is_owner or perm in perms

    tabs = [
        {
            "id": "dashboard", "title": "داشبورد", "icon": "dashboard", "screen": "dashboard",
            "source": "/api/dashboard",
        }
    ]

    # ------------------------------------------------------------ عملیات مالی
    if allowed("orders"):
        tabs.append({
            "id": "orders", "title": "سفارش‌ها", "icon": "receipt", "screen": "list",
            "section": "عملیات مالی",
            "source": "/api/orders", "item_id_field": "id",
            "search": True,
            "detail_source": "/api/orders/{id}/full",
            "receipt_source": "/api/orders/{id}/receipt-base64",
            "filters": [{"key": "status", "label": "وضعیت", "options":
                         ["pending", "approved", "rejected", "expired"]}],
            "fields": [
                {"key": "id", "label": "#", "type": "text"},
                {"key": "product_name", "label": "محصول", "type": "title"},
                {"key": "amount", "label": "مبلغ", "type": "currency"},
                {"key": "status", "label": "وضعیت", "type": "badge"},
                {"key": "created_at", "label": "تاریخ", "type": "date"},
            ],
            "actions": [
                {"id": "approve", "label": "تایید", "method": "POST",
                 "endpoint": "/api/orders/{id}/approve", "style": "success", "confirm": True},
                {"id": "reject", "label": "رد", "method": "POST",
                 "endpoint": "/api/orders/{id}/reject", "style": "danger", "confirm": True},
                {"id": "fake_receipt", "label": "فیش فیک + بلاک", "method": "POST",
                 "endpoint": "/api/orders/{id}/fake-receipt", "style": "danger", "confirm": True},
            ],
        })
        # شارژ کیف‌پول هم زیر همان مجوز "orders" است (طبق تعریف WEB_ADMIN_PERMISSIONS)
        tabs.append({
            "id": "topups", "title": "شارژ کیف‌پول", "icon": "wallet", "screen": "list",
            "section": "عملیات مالی",
            "source": "/api/topups", "item_id_field": "id",
            "detail_source": "/api/topups/{id}/full",
            "receipt_source": "/api/topups/{id}/receipt-base64",
            "fields": [
                {"key": "id", "label": "#", "type": "text"},
                {"key": "amount", "label": "مبلغ", "type": "currency"},
                {"key": "status", "label": "وضعیت", "type": "badge"},
                {"key": "created_at", "label": "تاریخ", "type": "date"},
            ],
            "actions": [
                {"id": "approve", "label": "تایید", "method": "POST",
                 "endpoint": "/api/topups/{id}/approve", "style": "success", "confirm": True},
                {"id": "reject", "label": "رد", "method": "POST",
                 "endpoint": "/api/topups/{id}/reject", "style": "danger", "confirm": True},
            ],
        })

    # ------------------------------------------------------- کاربران و پشتیبانی
    if allowed("users"):
        tabs.append({
            "id": "users", "title": "کاربران", "icon": "people", "screen": "list",
            "section": "کاربران و پشتیبانی",
            "source": "/api/users", "item_id_field": "tg_id", "search": True,
            # معادل تب‌های وضعیت («همه/فعال/منقضی/مسدود») در دایرکتوری کاربران
            # پنل وب؛ چون این‌ها فیلترهای واقعی سمت سرور هستند (نه فقط جستجوی
            # محلی روی همان صفحه)، به همان endpoint با پارامتر status ارسال می‌شوند.
            "filters": [{"key": "status", "label": "وضعیت", "options":
                         ["active", "expired", "blocked"]}],
            "fields": [
                {"key": "tg_id", "label": "شناسه", "type": "text"},
                {"key": "full_name", "label": "نام", "type": "title"},
                {"key": "wallet_balance", "label": "کیف‌پول", "type": "currency"},
            ],
            "detail_source": "/api/users/{tg_id}",
            "detail_type": "user",
            "services_source": "/api/users/{tg_id}/custom-configs",
            # کانفیگ‌های «بانک محصول» (لینک‌های ساده‌ی اختصاص‌یافته به کاربر) که
            # قبلاً فقط در پنل وب دیده می‌شدند؛ حالا در جزئیات کاربر اپ هم هستند.
            "bank_configs_source": "/api/users/{tg_id}/configs",
            "wallet_endpoint": "/api/users/{tg_id}/wallet",
            # پیام مستقیم به همین کاربر (نه پیام همگانی)؛ معادل دکمه‌ی «ارسال
            # پیام» در جزئیات کاربر پنل وب.
            "message_endpoint": "/api/users/{tg_id}/message",
            "actions": [
                {"id": "block", "label": "مسدود", "method": "POST",
                 "endpoint": "/api/users/{tg_id}/block", "style": "danger", "confirm": True,
                 "visible_if_field": "is_blocked", "visible_if_value": "false"},
                {"id": "unblock", "label": "رفع مسدودی", "method": "POST",
                 "endpoint": "/api/users/{tg_id}/unblock", "style": "success", "confirm": True,
                 "visible_if_field": "is_blocked", "visible_if_value": "true"},
            ],
        })
    # تیکت‌ها صفحه‌ی اختصاصی native دارند تا جزئیات، پیام‌ها، پاسخ و بستن تیکت
    # در اپ هم دقیقاً مثل پنل وب کار کند.
    tabs.append({
        "id": "tickets", "title": "تیکت‌ها", "icon": "ticket", "screen": "tickets",
        "section": "کاربران و پشتیبانی",
        "source": "/api/tickets", "item_id_field": "id", "search": True,
        "filters": [{"key": "status", "label": "وضعیت", "options": ["open", "answered", "closed"]}],
    })
    # چت زنده هم مثل تب خودش در پنل وب برای هر ادمینی باز است؛ چون ماهیتش
    # زنده/رفت‌وبرگشتی است همان صفحه‌ی وب را در یک وب‌ویوی داخل اپ نشان می‌دهیم
    tabs.append({
        "id": "support", "title": "چت زنده", "icon": "chat", "screen": "support",
        "section": "کاربران و پشتیبانی", "source": "/api/support/conversations",
    })

    # ------------------------------------------------------- محصولات و بازاریابی
    if allowed("catalog"):
        tabs.append({
            "id": "products", "title": "محصولات", "icon": "box", "screen": "list",
            "section": "محصولات و بازاریابی",
            "source": "/api/products", "item_id_field": "id",
            "config_bank_source": "/api/products/{id}/configs",
            "fields": [
                {"key": "name", "label": "نام", "type": "title"},
                {"key": "price", "label": "قیمت", "type": "currency"},
                {"key": "is_active", "label": "فعال", "type": "toggle",
                 "toggle_endpoint": "/api/products/{id}/toggle"},
            ],
            "create_form": {
                "title": "افزودن محصول",
                "submit_url": "/api/products",
                "method": "POST",
                "fields": [
                    {"key": "category_id", "label": "دسته‌بندی", "type": "select_remote",
                     "options_source": "/api/categories", "option_value_key": "id", "option_label_key": "name"},
                    {"key": "name", "label": "نام محصول", "type": "text"},
                    {"key": "price", "label": "قیمت (تومان)", "type": "number"},
                    {"key": "description", "label": "توضیحات", "type": "textarea"},
                    {"key": "duration_days", "label": "مدت اعتبار (روز، ۰=نامحدود فقط با اتصال مستقیم)", "type": "number"},
                    {"key": "is_auto_provision", "label": "اتصال مستقیم به پنل (ساخت خودکار)", "type": "bool"},
                    {"key": "provision_server_id", "label": "پنل VPN", "type": "select_remote",
                     "options_source": "/api/panel-servers-lite", "option_value_key": "id", "option_label_key": "name",
                     "nullable": True, "depends_on": "is_auto_provision"},
                    {"key": "auto_provision_volume_gb", "label": "حجم (گیگ، ۰=نامحدود)", "type": "number",
                     "depends_on": "is_auto_provision"},
                ],
            },
            "edit_form": {
                "title": "ویرایش محصول",
                "submit_url": "/api/products/{id}",
                "method": "PUT",
                "fields": [
                    {"key": "name", "label": "نام محصول", "type": "text"},
                    {"key": "price", "label": "قیمت (تومان)", "type": "number"},
                    {"key": "description", "label": "توضیحات", "type": "textarea"},
                    {"key": "duration_days", "label": "مدت اعتبار (روز)", "type": "number"},
                    {"key": "provision_server_id", "label": "پنل VPN (فقط اتصال مستقیم)", "type": "select_remote",
                     "options_source": "/api/panel-servers-lite", "option_value_key": "id", "option_label_key": "name",
                     "nullable": True},
                    {"key": "auto_provision_volume_gb", "label": "حجم (گیگ، فقط اتصال مستقیم)", "type": "number"},
                ],
            },
        })
    if allowed("discounts"):
        tabs.append({
            "id": "discounts", "title": "کدهای تخفیف", "icon": "discount", "screen": "list",
            "section": "محصولات و بازاریابی",
            "source": "/api/discounts", "item_id_field": "id",
            "fields": [
                {"key": "code", "label": "کد", "type": "title"},
                {"key": "percent", "label": "درصد", "type": "text"},
                {"key": "used_count", "label": "استفاده‌شده", "type": "text"},
                {"key": "is_active", "label": "فعال", "type": "toggle",
                 "toggle_endpoint": "/api/discounts/{id}/toggle"},
            ],
            "actions": [
                {"id": "delete", "label": "حذف", "method": "DELETE",
                 "endpoint": "/api/discounts/{id}", "style": "danger", "confirm": True},
            ],
            "create_form": {
                "title": "افزودن کد تخفیف",
                "submit_url": "/api/discounts",
                "method": "POST",
                "fields": [
                    {"key": "code", "label": "کد تخفیف", "type": "text"},
                    {"key": "percent", "label": "درصد تخفیف (خالی=استفاده از مبلغ ثابت)", "type": "number", "nullable": True},
                    {"key": "fixed_amount", "label": "مبلغ ثابت تخفیف (تومان، خالی=استفاده از درصد)", "type": "number", "nullable": True},
                    {"key": "max_discount_amount", "label": "سقف مبلغ تخفیف (تومان، فقط برای تخفیف درصدی، خالی=بدون سقف)",
                     "type": "number", "nullable": True},
                    {"key": "max_uses", "label": "حداکثر تعداد استفاده (۰=نامحدود)", "type": "number"},
                    {"key": "expires_at", "label": "تاریخ انقضا (خالی=بدون انقضا، فرمت: 2026-12-31T23:59:00)", "type": "text"},
                    {"key": "min_purchase", "label": "حداقل مبلغ خرید (تومان)", "type": "number", "nullable": True},
                    {"key": "max_purchase", "label": "حداکثر مبلغ خرید (تومان)", "type": "number", "nullable": True},
                    {"key": "product_id", "label": "محدود به یک محصول خاص (خالی=همه)", "type": "select_remote",
                     "options_source": "/api/products", "option_value_key": "id", "option_label_key": "name", "nullable": True},
                    {"key": "category_id", "label": "محدود به دسته‌بندی (خالی=همه)", "type": "select_remote",
                     "options_source": "/api/categories", "option_value_key": "id", "option_label_key": "name", "nullable": True},
                    {"key": "product_ids", "label": "محدود به چند محصول خاص (خالی=بدون محدودیت)", "type": "select_remote_multi",
                     "options_source": "/api/products", "option_value_key": "id", "option_label_key": "name", "nullable": True},
                ],
            },
        })
    if allowed("broadcast"):
        # فرم پیام همگانی (انتخاب مخاطب، ضمیمه و ...) در پنل وب پیاده شده؛
        # چون ذاتاً یک فرم غنی است همان صفحه را این‌جا هم نشان می‌دهیم
        tabs.append({
            "id": "broadcast", "title": "پیام همگانی", "icon": "campaign", "screen": "broadcast",
            "section": "محصولات و بازاریابی", "submit_url": "/api/broadcast",
        })
    if allowed("settings"):
        # آپلود تصویر بنر (multipart) در فرم وب پیاده شده؛ همان‌جا نگه می‌داریم
        tabs.append({
            "id": "banners", "title": "بنرها", "icon": "image", "screen": "banners",
            "section": "محصولات و بازاریابی", "source": "/api/banners", "submit_url": "/api/banners",
        })

    # ------------------------------------------------------------ شبکه و همکاران
    if allowed("resellers"):
        tabs.append({
            "id": "resellers", "title": "نمایندگی‌ها", "icon": "groups", "screen": "resellers",
            "section": "شبکه و همکاران", "source": "/api/resellers", "search": True,
        })
    if allowed("resellers"):
        tabs.append({
            "id": "reseller_tiers", "title": "سطوح نمایندگی", "icon": "groups", "screen": "list",
            "section": "شبکه و همکاران",
            "source": "/api/reseller-tiers", "item_id_field": "id",
            "fields": [
                {"key": "title", "label": "سطح", "type": "title"},
                {"key": "model_label", "label": "مدل", "type": "badge"},
                {"key": "members_count", "label": "اعضا", "type": "text"},
                {"key": "is_enabled", "label": "فعال", "type": "toggle",
                 "toggle_endpoint": "/api/reseller-tiers/{id}/toggle"},
            ],
            "edit_form": {
                "title": "ویرایش سطح نمایندگی",
                "submit_url": "/api/reseller-tiers/{id}",
                "method": "PUT",
                "fields": [
                    {"key": "title", "label": "عنوان سطح", "type": "text"},
                    {"key": "icon", "label": "ایموجی", "type": "text"},
                    {"key": "summary", "label": "توضیح کوتاه (داخل لیست سطح‌ها)", "type": "text"},
                    {"key": "description", "label": "توضیح کامل (کارت جزئیات)", "type": "text"},
                    {"key": "sort_order", "label": "ترتیب نمایش", "type": "number"},
                    {"key": "commission_min", "label": "حداقل درصد کمیسیون (خالی=بدون محدودیت)", "type": "number", "nullable": True},
                    {"key": "commission_max", "label": "حداکثر درصد کمیسیون (خالی=بدون محدودیت)", "type": "number", "nullable": True},
                    {"key": "permanent_discount_percent", "label": "تخفیف دائمی٪ (سطح تخفیفی)", "type": "number", "nullable": True},
                    {"key": "min_qty", "label": "حداقل تعداد خرید (خرید عمده محصول)", "type": "number", "nullable": True},
                    {"key": "min_volume_gb", "label": "حداقل حجم خرید به گیگ (اعتبار حجمی)", "type": "number", "nullable": True},
                    {"key": "credit_limit_toman", "label": "سقف اعتبار پس‌پرداخت به تومان (۰=بدون اعتبار)", "type": "number"},
                    {"key": "has_miniapp", "label": "مینی‌اپ اختصاصی", "type": "bool"},
                    {"key": "has_web_panel", "label": "پنل وب", "type": "bool"},
                    {"key": "has_dedicated_bot", "label": "بات مستقل", "type": "bool"},
                    {"key": "auto_approve", "label": "تایید خودکار (سطح تخفیفی)", "type": "bool"},
                ],
            },
        })
        tabs.append({
            "id": "reseller_tier_qty", "title": "پلکان تخفیف نقره‌ای", "icon": "discount", "screen": "list",
            "section": "شبکه و همکاران",
            "source": "/api/reseller-tiers/silver/qty-discounts", "item_id_field": "id",
            "fields": [
                {"key": "min_qty", "label": "از تعداد", "type": "title"},
                {"key": "discount_percent", "label": "درصد تخفیف", "type": "text"},
            ],
            "actions": [
                {"id": "delete", "label": "حذف", "method": "DELETE",
                 "endpoint": "/api/reseller-tiers/qty-discounts/{id}", "style": "danger", "confirm": True},
            ],
            "create_form": {
                "title": "افزودن پله‌ی تخفیف",
                "submit_url": "/api/reseller-tiers/silver/qty-discounts",
                "method": "POST",
                "fields": [
                    {"key": "min_qty", "label": "حداقل تعداد خرید یک‌جا", "type": "number"},
                    {"key": "discount_percent", "label": "درصد تخفیف", "type": "number"},
                ],
            },
        })
    if allowed("panels"):
        tabs.append({
            "id": "panels", "title": "پنل‌های VPN", "icon": "dns", "screen": "list",
            "section": "شبکه و همکاران",
            "source": "/api/panel-servers", "item_id_field": "id",
            "fields": [
                {"key": "name", "label": "نام", "type": "title"},
                {"key": "type_label", "label": "نوع", "type": "badge"},
                {"key": "is_active", "label": "فعال", "type": "toggle",
                 "toggle_endpoint": "/api/panel-servers/{id}/toggle"},
            ],
            # فقط پنل‌های خانواده‌ی PasarGuard/Marzban/Marzneshin (ساخت تک‌مرحله‌ای
            # با «کاربر نمونه»). افزودن 3X-UI/Hiddify از اپ پشتیبانی نمی‌شود چون
            # نیاز به انتخاب inbound یا تکمیل بعدی دارند - فعلاً فقط از پنل وب.
            "create_form": {
                "title": "افزودن پنل (PasarGuard/Marzban/Marzneshin)",
                "submit_url": "/api/panel-servers",
                "method": "POST",
                "fields": [
                    {"key": "name", "label": "نام سرور", "type": "text"},
                    {"key": "panel_type", "label": "نوع پنل", "type": "select", "options": [
                        ["pasarguard", "PasarGuard"], ["marzban", "Marzban"], ["marzneshin", "Marzneshin"],
                    ]},
                    {"key": "api_url", "label": "آدرس پنل (API URL)", "type": "text"},
                    {"key": "api_username", "label": "نام کاربری ادمین پنل", "type": "text"},
                    {"key": "api_password", "label": "پسورد ادمین پنل", "type": "password"},
                    {"key": "template_username", "label": "نام کاربری نمونه (برای دریافت قالب)", "type": "text"},
                    {"key": "default_group", "label": "گروه پیش‌فرض (اختیاری)", "type": "text", "nullable": True},
                ],
            },
            # ویرایش نام/آدرس/اطلاعات ورود پنل موجود؛ تغییر نوع پنل یا
            # inbound/آدرس Subscription (3X-UI/Hiddify) هنوز فقط از پنل وب است.
            "edit_form": {
                "title": "ویرایش پنل",
                "submit_url": "/api/panel-servers/{id}",
                "method": "PUT",
                "fields": [
                    {"key": "name", "label": "نام سرور", "type": "text", "nullable": True},
                    {"key": "api_url", "label": "آدرس پنل (API URL)", "type": "text", "nullable": True},
                    {"key": "api_username", "label": "نام کاربری ادمین پنل", "type": "text", "nullable": True},
                    {"key": "api_password", "label": "پسورد/توکن جدید (خالی=بدون تغییر)", "type": "password", "nullable": True},
                ],
            },
            "actions": [
                {"id": "test", "label": "تست اتصال", "method": "POST",
                 "endpoint": "/api/panel-servers/{id}/test", "style": "default", "confirm": True},
                {"id": "delete", "label": "حذف", "method": "DELETE",
                 "endpoint": "/api/panel-servers/{id}", "style": "danger", "confirm": True},
            ],
        })
    tabs.append({
        "id": "map", "title": "نقشه سرورها", "icon": "map", "screen": "server_map",
        "section": "شبکه و همکاران", "source": "/api/dashboard/servers-map",
        "map_source": "/api/dashboard/world-map",
    })
    if allowed("settings"):
        # لینک ساب مادر و فاصله/آستانه‌ی چک آنلاین‌بودن سرورها؛ قبلاً فقط از
        # پنل وب قابل تنظیم بود، هیچ فرمی برایشان در تب نقشه‌ی اپ نبود.
        tabs.append({
            "id": "map_settings", "title": "تنظیمات نقشه و مانیتورینگ", "icon": "map",
            "screen": "settings_group", "section": "شبکه و همکاران",
            "cards": [
                {"title": "لینک ساب مادر", "load_url": "/api/settings/master-sub",
                 "submit_url": "/api/settings/master-sub", "fields": [
                    {"key": "link", "label": "لینک ساب (http/https)", "type": "text"},
                ]},
                {"title": "بررسی آنلاین‌بودن سرورها", "load_url": "/api/settings/server-check",
                 "submit_url": "/api/settings/server-check", "fields": [
                    {"key": "interval_min", "label": "هر چند دقیقه چک شود", "type": "number"},
                    {"key": "offline_streak", "label": "تعداد شکست پیاپی برای آفلاین اعلام‌کردن", "type": "number"},
                ]},
            ],
        })

    # -------------------------------------------------------------- تنظیمات و سیستم
    if allowed("settings"):
        # نسخه‌ی native تنظیمات پایه؛ قبلاً این تب WebView بود و روی بعضی نسخه‌های
        # Android WebView به صفحه‌ی کاملاً خالی/سیاه می‌رسید.
        tabs.append({
            "id": "branding", "title": "تنظیمات و برندینگ", "icon": "brush", "screen": "form",
            "section": "تنظیمات و سیستم", "load_url": "/api/settings", "submit_url": "/api/settings",
            "form_sections": [
                {"title": "محتوا و برندینگ", "groups": [{"title": "متن‌های پایه", "fields": [
                    {"key": "store_name", "label": "نام فروشگاه", "type": "text"},
                    {"key": "welcome_text", "label": "متن خوش‌آمدگویی", "type": "textarea"},
                    {"key": "contact_text", "label": "متن ارتباط با پشتیبانی", "type": "textarea"},
                    {"key": "after_buy_text", "label": "متن راهنمای پرداخت", "type": "textarea"},
                ]}, {"title": "متن‌ها و ظاهر مینی‌اپ", "fields": [
                    {"key": "miniapp_banner_text", "label": "متن بنر مینی‌اپ (زیر نام کاربر)", "type": "text"},
                    {"key": "miniapp_theme", "label": "تم رنگی مینی‌اپ", "type": "select",
                     "options": [[k, v] for k, v in MINIAPP_THEME_OPTIONS.items()]},
                ]}]}
                # نکته: رنگ دکمه‌های مسیر خرید (انتخاب دسته/محصول/ادامه/کد تخفیف/بازگشت)
                # دیگر اینجا نیست؛ برای یکپارچه‌سازی به تب «دکمه‌های ربات» منتقل شد.
            ],
        })
        # نسخه‌ی native تنظیمات پرداخت و مالی؛ همان کلیدهایی که در پنل وب زیر
        # زیرتب «پرداخت» تنظیمات هستند (همه روی /api/settings ذخیره می‌شوند)،
        # اینجا هم با فرم native نمایش داده می‌شوند - بدون نیاز به آپدیت اپ.
        tabs.append({
            "id": "paymentsettings", "title": "پرداخت و مالی", "icon": "wallet", "screen": "form",
            "section": "تنظیمات و سیستم", "load_url": "/api/settings", "submit_url": "/api/settings",
            "form_sections": [
                {"title": "پرداخت و مالی", "groups": [{"title": "کارت بانکی", "fields": [
                    {"key": "card_number", "label": "شماره کارت", "type": "text"},
                    {"key": "card_holder", "label": "نام صاحب کارت", "type": "text"},
                ]}, {"title": "قابلیت ۸۶: انقضای سفارش‌های رهاشده با کد تخفیف", "fields": [
                    {"key": "discount_order_expiry_minutes",
                     "label": "مهلت لغو خودکار سفارش (دقیقه) اگر رسید کارت‌به‌کارت فرستاده نشود؛ ۰ = غیرفعال",
                     "type": "number"},
                ]}, {"title": "نرخ ارز پشتیبان (عمومی فروشگاه)", "fields": [
                    {"key": "manual_usd_rate_toman", "label": "نرخ دلار دستی (فقط اگر منابع زنده شکست بخورند)", "type": "number"},
                ]}, {"title": "🪙 پرداخت کریپتو (Plisio)", "fields": [
                    {"key": "crypto_payment_enabled", "label": "فعال بودن پرداخت کریپتو", "type": "bool"},
                    {"key": "plisio_api_key", "label": "کلید API درگاه Plisio", "type": "password"},
                ]}, {"title": "💳 آبان گیت‌وی (کارت به کارت خودکار)", "fields": [
                    {"key": "abangateway_payment_enabled", "label": "فعال بودن درگاه آبان گیت‌وی", "type": "bool"},
                    {"key": "abangateway_api_key", "label": "کلید API آبان گیت‌وی", "type": "password"},
                    {"key": "abangateway_webhook_secret", "label": "کلید مخفی وب‌هوک آبان گیت‌وی", "type": "password"},
                ]}, {"title": "💳 بلوپال (کارت به کارت خودکار)", "fields": [
                    {"key": "blupal_payment_enabled", "label": "فعال بودن درگاه بلوپال", "type": "bool"},
                    {"key": "blupal_api_key", "label": "کلید API بلوپال", "type": "password"},
                ]}, {"title": "⭐ NoapayBot - استارز تلگرام (تایید آنی)", "fields": [
                    {"key": "noapay_payment_enabled", "label": "فعال بودن درگاه NoapayBot", "type": "bool"},
                    {"key": "noapay_api_key", "label": "کلید API NoapayBot", "type": "password"},
                    {"key": "noapay_webhook_secret", "label": "رمز HMAC وب‌هوک (X-Starbot-Signature)", "type": "password"},
                    {"key": "noapay_rate_toman_per_star", "label": "نرخ تومان به‌ازای هر استارز", "type": "number"},
                ]}, *extra_gateway_registry.settings_groups(), {"title": "📡 کارت‌به‌کارت با تایید خودکار (پیامک بانک)", "fields": [
                    {"key": "card_to_card_auto_enabled", "label": "فعال بودن (نیازمند حداقل یک کارت فعال)", "type": "bool"},
                    {"key": "card_to_card_auto_timeout_minutes", "label": "مهلت هر مبلغ (دقیقه)", "type": "number"},
                    {"key": "card_to_card_auto_amount_digits", "label": "تعداد رقم آخر برای یکتاسازی مبلغ", "type": "number"},
                    {"key": "card_to_card_sms_amount_unit", "label": "واحد مبلغ داخل پیامک بانک", "type": "select",
                     "options": [["rial", "ریال (اکثر بانک‌ها)"], ["toman", "تومان"]]},
                ]}]}
            ],
        })
        # نسخه‌ی native مدیریت درگاه‌های سفارشی: فعال/غیرفعال، تست اتصال، حذف
        # و ساخت/ویرایش. چون config یک JSON DSL دلخواه است (credential_fields،
        # body با placeholder، verify/webhook mapping)، فیلد "config" با نوع
        # "json" نمایش داده می‌شود: یک ادیتور متنی چندخطی که کل شیء JSON را
        # خام می‌گیرد/نشان می‌دهد - همان چیزی که پنل وب هم برای ساخت اولیه
        # پیشنهاد می‌کند، فقط بدون UI مرحله‌به‌مرحله. مقادیر محرمانه‌ی
        # ماسک‌شده (که با "..." شروع می‌شوند) اگر دست‌نخورده بمانند توسط خودِ
        # /api/gateways سمت سرور با مقدار واقعی قبلی جایگزین می‌شوند.
        tabs.append({
            "id": "custom_gateways", "title": "درگاه‌های سفارشی", "icon": "dns", "screen": "list",
            "section": "تنظیمات و سیستم",
            "source": "/api/gateways", "item_id_field": "id",
            "fields": [
                {"key": "name", "label": "نام", "type": "title"},
                {"key": "key", "label": "کلید", "type": "text"},
                {"key": "enabled", "label": "فعال", "type": "toggle",
                 "toggle_endpoint": "/api/gateways/{id}/toggle"},
            ],
            "actions": [
                {"id": "test", "label": "تست اتصال", "method": "POST",
                 "endpoint": "/api/gateways/{id}/test", "style": "default", "confirm": True},
                {"id": "delete", "label": "حذف", "method": "DELETE",
                 "endpoint": "/api/gateways/{id}", "style": "danger", "confirm": True},
            ],
            "create_form": {
                "title": "افزودن درگاه سفارشی",
                "submit_url": "/api/gateways",
                "method": "POST",
                "fields": [
                    {"key": "key", "label": "کلید (فقط حروف/عدد انگلیسی، - و _)", "type": "text"},
                    {"key": "name", "label": "نام", "type": "text"},
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "min_amount", "label": "حداقل مبلغ واریز (تومان، ۰=بدون محدودیت)", "type": "number"},
                    {"key": "config", "label": "تنظیمات (JSON)", "type": "json"},
                ],
            },
            "edit_form": {
                "title": "ویرایش درگاه سفارشی",
                "submit_url": "/api/gateways/{id}",
                "method": "PUT",
                "fields": [
                    {"key": "key", "label": "کلید", "type": "text"},
                    {"key": "name", "label": "نام", "type": "text"},
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "min_amount", "label": "حداقل مبلغ واریز (تومان، ۰=بدون محدودیت)", "type": "number"},
                    {"key": "config", "label": "تنظیمات (JSON)", "type": "json"},
                ],
            },
        })
        # تنظیمات دستیار هوشمند (AI Support) قبلاً فقط از منوی ربات تلگرام
        # قابل تنظیم بود؛ نه در پنل وب، نه در اپ. اینجا معادل native آن اضافه
        # می‌شود: فعال/غیرفعال، انتخاب مسیر/مدل هر Provider، کلیدهای API
        # (چندخطی، هر خط یک کلید) و سوالات متداول.
        tabs.append({
            "id": "aisupport", "title": "دستیار هوشمند", "icon": "chat", "screen": "settings_group",
            "section": "تنظیمات و سیستم", "cards": [
                {"title": "عمومی", "load_url": "/api/settings/ai-support", "submit_url": "/api/settings/ai-support", "fields": [
                    {"key": "enabled", "label": "فعال بودن دستیار هوشمند", "type": "bool"},
                    {"key": "provider", "label": "مسیر انتخاب مدل", "type": "select", "options": [
                        ["auto", "خودکار (Gemini → Groq → OpenRouter)"], ["gemini", "فقط Gemini"],
                        ["groq", "فقط Groq"], ["openrouter", "فقط OpenRouter"],
                    ]},
                ]},
                {"title": "🔷 Gemini", "load_url": "/api/settings/ai-support", "submit_url": "/api/settings/ai-support", "fields": [
                    {"key": "gemini_model", "label": "مدل", "type": "select", "options": [
                        [m, label] for prov, m, label in ai_support.MODEL_CHOICES if prov == "gemini"
                    ]},
                    {"key": "gemini_api_key", "label": "کلید(های) API (هر خط یک کلید؛ خالی=بدون تغییر)", "type": "textarea"},
                ]},
                {"title": "🚀 Groq", "load_url": "/api/settings/ai-support", "submit_url": "/api/settings/ai-support", "fields": [
                    {"key": "groq_model", "label": "مدل", "type": "select", "options": [
                        [m, label] for prov, m, label in ai_support.MODEL_CHOICES if prov == "groq"
                    ]},
                    {"key": "groq_api_key", "label": "کلید(های) API (هر خط یک کلید؛ خالی=بدون تغییر)", "type": "textarea"},
                ]},
                {"title": "🌐 OpenRouter", "load_url": "/api/settings/ai-support", "submit_url": "/api/settings/ai-support", "fields": [
                    {"key": "openrouter_model", "label": "مدل", "type": "select", "options": [
                        [m, label] for prov, m, label in ai_support.MODEL_CHOICES if prov == "openrouter"
                    ]},
                    {"key": "openrouter_api_key", "label": "کلید(های) API (هر خط یک کلید؛ خالی=بدون تغییر)", "type": "textarea"},
                ]},
            ],
        })
        tabs.append({
            "id": "aifaq", "title": "سوالات متداول دستیار", "icon": "chat", "screen": "list",
            "section": "تنظیمات و سیستم",
            "source": "/api/ai-faq", "item_id_field": "id",
            "fields": [
                {"key": "question", "label": "سوال", "type": "title"},
                {"key": "answer", "label": "جواب", "type": "text"},
            ],
            "actions": [
                {"id": "delete", "label": "حذف", "method": "DELETE",
                 "endpoint": "/api/ai-faq/{id}", "style": "danger", "confirm": True},
            ],
            "create_form": {
                "title": "افزودن سوال متداول",
                "submit_url": "/api/ai-faq",
                "method": "POST",
                "fields": [
                    {"key": "question", "label": "سوال", "type": "text"},
                    {"key": "answer", "label": "جواب", "type": "textarea"},
                ],
            },
        })
        tabs.append({
            "id": "buttons", "title": "دکمه‌های ربات", "icon": "tune", "screen": "buttons",
            "section": "تنظیمات و سیستم", "source": "/api/buttons",
        })
        tabs.append({
            "id": "salessettings", "title": "تنظیمات فروش", "icon": "sell", "screen": "settings_group",
            "section": "تنظیمات و سیستم", "cards": [
                {"title": "رفرال", "load_url": "/api/settings/referral", "submit_url": "/api/settings/referral", "fields": [
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "percent", "label": "درصد پورسانت", "type": "number"},
                    {"key": "commission_max_count", "label": "سقف افراد پورسانت‌دار (۰=نامحدود)", "type": "number"},
                    {"key": "free_config_enabled", "label": "کانفیگ رایگان فعال", "type": "bool"},
                    {"key": "free_config_threshold", "label": "تعداد دعوت لازم", "type": "number"},
                    {"key": "free_config_product_id", "label": "شناسه محصول جایزه (خالی=بدون محصول)", "type": "select_int_nullable"},
                    {"key": "invite_bonus_enabled", "label": "شارژ ثابت برای دعوت فعال", "type": "bool"},
                    {"key": "invite_bonus_amount", "label": "مبلغ شارژ هر دعوت", "type": "number"},
                    {"key": "invite_bonus_max_count", "label": "سقف دعوت مشمول (۰=نامحدود)", "type": "number"},
                ]},
                {"title": "هشدار زیرمجموعه‌گیری فیک", "load_url": "/api/settings/referral-fraud", "submit_url": "/api/settings/referral-fraud", "fields": [
                    {"key": "detection_enabled", "label": "فعال", "type": "bool"},
                    {"key": "burst_count", "label": "تعداد دعوت که یعنی انبوه", "type": "number"},
                    {"key": "burst_minutes", "label": "بازه‌ی دعوت انبوه (دقیقه)", "type": "number"},
                    {"key": "min_invites", "label": "حداقل دعوت برای بررسی نرخ بی‌خریدی", "type": "number"},
                    {"key": "zero_purchase_ratio", "label": "درصد بی‌خریدی مشکوک", "type": "number"},
                    {"key": "auto_suspend", "label": "توقف خودکار پاداش تا بررسی دستی", "type": "bool"},
                ]},
                {"title": "گردونه شانس", "load_url": "/api/settings/wheel", "submit_url": "/api/settings/wheel", "fields": [
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "win_percent", "label": "درصد برد", "type": "number"},
                    {"key": "prizes", "label": "جوایز (با کاما جدا شود)", "type": "number_list"},
                    {"key": "expiry_hours", "label": "اعتبار کد (ساعت)", "type": "number"},
                    {"key": "cooldown_hours", "label": "فاصله چرخش (ساعت)", "type": "number"},
                ]},
                {"title": "یادآوری تمدید", "load_url": "/api/settings/renewal", "submit_url": "/api/settings/renewal", "fields": [
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "days_before", "label": "چند روز قبل از انقضا", "type": "number"},
                    {"key": "discount_percent", "label": "درصد تخفیف", "type": "number"},
                    {"key": "discount_expiry_hours", "label": "اعتبار کد (ساعت)", "type": "number"},
                ]},
                {"title": "یادآوری حجم", "load_url": "/api/settings/volume-reminder", "submit_url": "/api/settings/volume-reminder", "fields": [
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "mode", "label": "مبنا: percent یا gb", "type": "text"},
                    {"key": "percent", "label": "درصد آستانه", "type": "number"},
                    {"key": "gb_left", "label": "گیگ باقی‌مانده", "type": "number"},
                    {"key": "discount_percent", "label": "درصد تخفیف", "type": "number"},
                    {"key": "discount_expiry_hours", "label": "اعتبار کد (ساعت)", "type": "number"},
                ]},
                {"title": "هشدار اتصال به کانفیگ", "load_url": "/api/settings/connect-alert", "submit_url": "/api/settings/connect-alert", "fields": [
                    {"key": "connect_enabled", "label": "فعال", "type": "bool"},
                    {"key": "connect_threshold_mb", "label": "آستانه‌ی مصرف (مگابایت)", "type": "number"},
                    {"key": "connect_text", "label": "متن پیام (از {used_gb} می‌توانید استفاده کنید)", "type": "textarea"},
                ]},
                {"title": "هشدار عدم‌اتصال به کانفیگ", "load_url": "/api/settings/connect-alert", "submit_url": "/api/settings/connect-alert", "fields": [
                    {"key": "no_connect_enabled", "label": "فعال", "type": "bool"},
                    {"key": "no_connect_hours", "label": "مهلت بعد از فعال‌سازی (ساعت)", "type": "number"},
                    {"key": "no_connect_threshold_mb", "label": "آستانه‌ی مصرف (مگابایت)", "type": "number"},
                    {"key": "no_connect_text", "label": "متن پیام (از {used_gb} می‌توانید استفاده کنید)", "type": "textarea"},
                ]},
                {"title": "تخفیف تمدید کامل زودهنگام", "load_url": "/api/settings/early-renewal-discount", "submit_url": "/api/settings/early-renewal-discount", "fields": [
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "days_before", "label": "حداکثر روز مانده به انقضا", "type": "number"},
                    {"key": "percent", "label": "درصد تخفیف", "type": "number"},
                ]},
                {"title": "عضویت اجباری", "load_url": "/api/settings/force-join", "submit_url": "/api/settings/force-join", "fields": [
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                    {"key": "channel", "label": "آیدی کانال", "type": "text"},
                ]},
                {"title": "هشدار موجودی", "load_url": "/api/settings/stock-alert", "submit_url": "/api/settings/stock-alert", "fields": [
                    {"key": "threshold", "label": "آستانه هشدار", "type": "number"},
                ]},
                {"title": "کانفیگ تست", "load_url": "/api/settings/test-config", "submit_url": "/api/settings/test-config", "fields": [
                    {"key": "enabled", "label": "فعال", "type": "bool"},
                ], "danger_action": {"label": "بازنشانی برای همه کاربران", "endpoint": "/api/settings/test-config/reset-all", "method": "POST", "confirm_text": "امکان دریافت کانفیگ تست برای همه کاربران دوباره فعال شود؟"}},
            ],
        })
    if is_owner:
        _perm_labels = {
            "orders": "سفارش‌ها و شارژ کیف‌پول", "users": "کاربران", "catalog": "محصولات و بانک کانفیگ",
            "discounts": "کدهای تخفیف", "tickets": "تیکت و پشتیبانی", "broadcast": "پیام همگانی",
            "resellers": "نمایندگی‌ها", "panels": "پنل‌های VPN", "system": "سیستم و لاگ‌ها",
            "settings": "تنظیمات و برندینگ", "backup": "بکاپ فوری",
        }
        _assignable_perms = [p for p in WEB_ADMIN_PERMISSIONS if p not in MAIN_TENANT_ONLY_PERMISSIONS or not admin["tenant"]]
        tabs.append({
            "id": "webadmins", "title": "کاربران پنل", "icon": "admin", "screen": "list",
            "section": "تنظیمات و سیستم",
            "source": "/api/web-admins", "item_id_field": "id",
            "fields": [
                {"key": "username", "label": "نام کاربری", "type": "title"},
                {"key": "role", "label": "نقش", "type": "badge"},
            ],
            "create_form": {
                "title": "افزودن ادمین پنل",
                "submit_url": "/api/web-admins",
                "method": "POST",
                "fields": [
                    {"key": "username", "label": "نام کاربری", "type": "text"},
                    {"key": "password", "label": "پسورد (حداقل ۸ کاراکتر)", "type": "password"},
                    {"key": "role", "label": "نقش", "type": "select", "options": [
                        ["admin", "ادمین کامل"], ["mid", "ادمین میانی"], ["support", "پشتیبان"],
                    ]},
                    {"key": "permissions", "label": "مجوزها", "type": "multiselect",
                     "options": [[p, _perm_labels.get(p, p)] for p in _assignable_perms]},
                ],
            },
        })
        tabs.append({
            "id": "tgadmins", "title": "ادمین‌های ربات", "icon": "shield", "screen": "list",
            "section": "تنظیمات و سیستم",
            "source": "/api/telegram-admins", "item_id_field": "telegram_id",
            "fields": [
                {"key": "telegram_id", "label": "شناسه", "type": "title"},
                {"key": "role", "label": "نقش", "type": "badge"},
            ],
        })
    if allowed("system"):
        tabs.append({
            "id": "system", "title": "سیستم و نگهداری", "icon": "memory", "screen": "system_status",
            "section": "تنظیمات و سیستم", "source": "/api/system/stats",
            "jobs_source": "/api/system/jobs",
            "backup_status_source": "/api/system/backup/status",
            "backup_create_endpoint": "/api/system/backup/create",
            # بازیابی بکاپ و بازنشانی کارخانه‌ای هر دو مخرب/غیرقابل‌برگشت‌اند و
            # سمت سرور هم require_owner هستند؛ برای همین فقط برای owner در
            # پیکربندی اپ فرستاده می‌شوند (مثل خودِ پنل وب).
            **({
                "backup_restore_endpoint": "/api/system/backup/restore",
                "factory_reset_endpoint": "/api/system/factory-reset",
            } if is_owner else {}),
        })
        tabs.append({
            "id": "logs", "title": "لاگ فعالیت ادمین‌ها", "icon": "history", "screen": "list",
            "section": "تنظیمات و سیستم",
            "source": "/api/admin-logs", "item_id_field": "id",
            "fields": [
                {"key": "action", "label": "عملیات", "type": "title"},
                {"key": "record_type", "label": "نوع", "type": "badge"},
                {"key": "created_at", "label": "تاریخ", "type": "date"},
            ],
        })

    # ------------------------------------------------------------------ حساب کاربری
    tabs.append({
        "id": "account", "title": "حساب من", "icon": "account", "screen": "account",
        "section": "حساب کاربری", "submit_url": "/api/me/password",
    })
    tabs.append({
        "id": "device_settings", "title": "تنظیمات دستگاه", "icon": "settings", "screen": "settings",
        "section": "حساب کاربری",
    })

    return {
        "app_min_supported_version": 1,
        "server_name": "ShopVPN Admin",
        "tenant": admin["tenant"] or "main",
        "tabs": tabs,
        # مقادیر عمومی (غیرمحرمانه) پروژه‌ی فایربیس همین سرور -- از تنظیمات >
        # اپ موبایل در پنل وب. اپ اندروید این‌ها را در زمان اجرا به FirebaseOptions
        # می‌دهد؛ اگر خالی باشند، اپ فقط برای همین سرور پوش را غیرفعال می‌کند.
        "firebase_api_key": db.get_setting("firebase_api_key") or None,
        "firebase_app_id": db.get_setting("firebase_app_id") or None,
        "firebase_project_id": db.get_setting("firebase_project_id") or None,
        "firebase_sender_id": db.get_setting("firebase_sender_id") or None,
    }


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
        raise HTTPException(400, tr("اعلان Push روی سرور تنظیم نشده است."))
    p256dh = (body.keys or {}).get("p256dh")
    auth = (body.keys or {}).get("auth")
    if not p256dh or not auth:
        raise HTTPException(400, tr("اطلاعات subscription ناقص است."))
    db.save_push_subscription(admin["id"], body.endpoint, p256dh, auth, body.user_agent)
    return {"ok": True}


@app.post("/api/push/unsubscribe")
def api_push_unsubscribe(body: PushUnsubscribeBody, admin=Depends(get_current_admin)):
    db.delete_push_subscription_by_endpoint(body.endpoint)
    return {"ok": True}


@app.post("/api/push/test")
async def api_push_test(admin=Depends(get_current_admin)):
    if not PUSH_ENABLED:
        raise HTTPException(400, tr("اعلان Push روی سرور تنظیم نشده است."))
    subs = (await asyncio.to_thread(db.list_push_subscriptions_for_admin, admin["id"]))
    if not subs:
        raise HTTPException(400, tr("هنوز روی این دستگاه اعلان را فعال نکرده‌ای."))
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
        raise HTTPException(502, tr("ارسال اعلان تست ناموفق بود."))
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


@app.get("/api/dashboard/advanced")
def api_dashboard_advanced(
    start: Optional[str] = None,
    end: Optional[str] = None,
    granularity: str = "day",
    admin=Depends(get_current_admin),
):
    """روند فروش با تفکیک بازه، عملکرد و نرخ موفقیت درگاه‌های پرداخت، عملکرد
    کمپین‌ها/نمایندگان داخلی، قیف تبدیل و نقشه‌ی ساعتی فعالیت. مکمل /api/dashboard -
    منبع همین db.get_advanced_stats است که بات و مینی‌اپ هم از آن استفاده می‌کنند."""
    if granularity not in ("day", "week", "month"):
        raise HTTPException(400, tr("granularity باید یکی از day/week/month باشد."))
    return db.get_advanced_stats(start, end, granularity=granularity)


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
        raise HTTPException(400, tr("لینک ساب باید با http:// یا https:// شروع شود."))
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
        raise HTTPException(400, tr(f"بازه‌ی هر دور اسکن باید بین {_MIN_CHECK_INTERVAL_MIN} تا {_MAX_CHECK_INTERVAL_MIN} دقیقه باشد."))
    if not (_MIN_OFFLINE_STREAK <= body.offline_streak <= _MAX_OFFLINE_STREAK):
        raise HTTPException(400, tr(f"تعداد دور متوالی باید بین {_MIN_OFFLINE_STREAK} تا {_MAX_OFFLINE_STREAK} باشد."))
    db.set_setting("server_check_interval_min", str(body.interval_min))
    db.set_setting("server_offline_streak", str(body.offline_streak))
    db.log_admin_action(
        admin["id"], "setting_change",
        f"server_check_interval_min={body.interval_min}, server_offline_streak={body.offline_streak} (پنل وب - {admin['username']})",
        "setting", "server_check",
    )
    return {"ok": True}


# ------------------------------------------------------------- AI support --
# قبلاً این تنظیمات فقط از منوی ادمین ربات تلگرام قابل تغییر بودند؛ اینجا
# معادل REST آن‌ها برای پنل وب و اپ اندروید اضافه می‌شود.


def _mask_key_lines(raw: str) -> str:
    keys = ai_support._split_keys(raw or "")
    return "\n".join((f"...{k[-4:]}" if len(k) > 4 else "•••") for k in keys)


class AiSupportSettingsBody(BaseModel):
    # Optional: این تنظیمات از ۴ کارت جدا (عمومی/Gemini/Groq/OpenRouter) روی
    # همین یک endpoint ذخیره می‌شوند؛ هر کارت فقط فیلدهای خودش را می‌فرستد.
    # با مقدار پیش‌فرض غیر-None، ذخیره‌ی مثلاً کارت Gemini به‌غلط enabled/provider
    # را به پیش‌فرض برمی‌گرداند.
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    gemini_model: str = ""
    groq_model: str = ""
    openrouter_model: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""


@app.get("/api/settings/ai-support")
def api_get_ai_support_settings(admin=Depends(require_permission("settings"))):
    return {
        "enabled": db.get_setting("ai_support_enabled", "1") == "1",
        "provider": ai_support.resolve_provider_mode(db),
        "gemini_model": ai_support.resolve_gemini_model(db),
        "groq_model": ai_support.resolve_groq_model(db),
        "openrouter_model": ai_support.resolve_openrouter_model(db),
        # کلیدها هیچ‌وقت خام برنمی‌گردند، فقط ماسک‌شده - برای این‌که فرم نشان
        # بدهد کلیدی تنظیم شده یا نه. اگر ادمین این متن ماسک‌شده را دست‌نخورده
        # بگذارد، ذخیره تغییری در کلید نمی‌دهد.
        "gemini_api_key": _mask_key_lines(db.get_setting("gemini_api_key", "")),
        "groq_api_key": _mask_key_lines(db.get_setting("groq_api_key", "")),
        "openrouter_api_key": _mask_key_lines(db.get_setting("openrouter_api_key", "")),
    }


@app.post("/api/settings/ai-support")
def api_set_ai_support_settings(body: AiSupportSettingsBody, admin=Depends(require_permission("settings"))):
    if body.provider is not None and body.provider not in ai_support.PROVIDER_LABELS:
        raise HTTPException(400, tr("مسیر انتخاب مدل نامعتبر است."))
    if body.enabled is not None:
        db.set_setting("ai_support_enabled", "1" if body.enabled else "0")
    if body.provider is not None:
        db.set_setting("ai_provider", body.provider)
    if body.gemini_model:
        db.set_setting("gemini_model", body.gemini_model)
    if body.groq_model:
        db.set_setting("groq_model", body.groq_model)
    if body.openrouter_model:
        db.set_setting("openrouter_model", body.openrouter_model)
    for field, setting_key in (
        ("gemini_api_key", "gemini_api_key"),
        ("groq_api_key", "groq_api_key"),
        ("openrouter_api_key", "openrouter_api_key"),
    ):
        raw = getattr(body, field)
        current_masked = _mask_key_lines(db.get_setting(setting_key, ""))
        if raw.strip() == current_masked.strip():
            continue  # دست‌نخورده مانده؛ کلید تغییر نکند
        db.set_setting(setting_key, "\n".join(ai_support._split_keys(raw)))
    db.log_admin_action(admin["id"], "ai_support_settings_change", f"تنظیمات دستیار هوشمند تغییر کرد (پنل وب - {admin['username']}).")
    return {"ok": True}


class AiFaqItemBody(BaseModel):
    question: str
    answer: str


@app.get("/api/ai-faq")
def api_list_ai_faq(admin=Depends(require_permission("settings"))):
    return [dict(row) for row in db.get_ai_faq_items()]


@app.post("/api/ai-faq")
def api_add_ai_faq(body: AiFaqItemBody, admin=Depends(require_permission("settings"))):
    question, answer = body.question.strip(), body.answer.strip()
    if not question or not answer:
        raise HTTPException(400, tr("سوال و جواب نمی‌توانند خالی باشند."))
    item_id = db.add_ai_faq_item(question, answer)
    db.log_admin_action(admin["id"], "ai_faq_add", f"سوال متداول دستیار اضافه شد (پنل وب - {admin['username']}).")
    return {"id": item_id, "ok": True}


@app.delete("/api/ai-faq/{item_id}")
def api_delete_ai_faq(item_id: int, admin=Depends(require_permission("settings"))):
    if not db.get_ai_faq_item(item_id):
        raise HTTPException(404, tr("یافت نشد."))
    db.delete_ai_faq_item(item_id)
    db.log_admin_action(admin["id"], "ai_faq_delete", f"سوال متداول دستیار حذف شد (پنل وب - {admin['username']}).")
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
        raise HTTPException(500, tr("psutil نصب نیست. دستور: pip install psutil"))

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
        raise HTTPException(404, tr("فایل دیتابیس پیدا نشد."))

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
        raise HTTPException(400, tr("برای تایید بازیابی، عبارت RESTORE را دقیقاً وارد کن."))
    if not file.filename or not file.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(400, tr("فایل باید پسوند .db یا .sqlite داشته باشد."))

    tmp_dir = tempfile.mkdtemp(prefix="restore_")
    tmp_path = os.path.join(tmp_dir, "uploaded.db")
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    if not is_valid_sqlite_db(tmp_path):
        os.remove(tmp_path)
        os.rmdir(tmp_dir)
        raise HTTPException(400, tr("این فایل یک دیتابیس sqlite معتبر نیست."))

    try:
        pre_restore_path = await asyncio.to_thread(restore_backup, db, _current_tenant.get().db_path, tmp_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, tr(f"بازیابی ناموفق بود: {e}"))
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


@app.post("/api/system/factory-reset")
async def api_factory_reset(confirm_phrase: str = Form(""), admin=Depends(require_owner)):
    """بازگشت این بات (اصلی یا نمایندگی) به وضعیت روز اول نصب: همه‌ی داده‌ی
    فروشگاه پاک می‌شود، فقط خودِ owner باقی می‌ماند. غیرقابل‌بازگشت به‌جز از
    روی بکاپ؛ به همین دلیل یک بکاپ ایمنی خودکار قبل از پاک‌سازی گرفته می‌شود
    و سمت سرور هم عبارت تاییدی الزامی است."""
    if confirm_phrase.strip().upper() != "RESET":
        raise HTTPException(400, tr("برای تایید بازگشت به حالت کارخانه، عبارت RESET را دقیقاً وارد کن."))

    tenant = _current_tenant.get()
    safety_backup = await asyncio.to_thread(create_backup, tenant.db_path, _backup_dir(), 14)

    await asyncio.to_thread(db.factory_reset)

    (await asyncio.to_thread(db.log_admin_action,
        admin["id"], "factory_reset",
        f"بازگشت کامل به حالت کارخانه (روز اول نصب)؛ بکاپ ایمنی قبل از پاک‌سازی: "
        f"{os.path.basename(safety_backup) if safety_backup else 'ناموفق'} (پنل وب - {admin['username']})",
    ))
    return {
        "ok": True,
        "safety_backup": os.path.basename(safety_backup) if safety_backup else None,
    }


# ------------------------------------------------------------------ orders --


@app.get("/api/orders")
def api_orders(status: str = "pending", q: str = "", product_id: Optional[int] = None, date_from: str = "", date_to: str = "", admin=Depends(get_current_admin)):
    if any((q.strip(), product_id is not None, date_from.strip(), date_to.strip())):
        rows = db.search_orders(status=status, query=q, product_id=product_id, date_from=date_from, date_to=date_to)
    else:
        rows = db.get_pending_orders() if status == "pending" else db.get_orders_by_status(status)
    out = []
    for o in rows:
        o = dict(o)
        product = row_to_dict(db.get_product(o["product_id"])) if o["product_id"] else None
        user = row_to_dict(db.get_user(o["user_id"]))
        o["product_name"] = product["name"] if product else ("ساخت کانفیگ شخصی" if o.get("is_custom_config") else "-")
        o["username"] = user["username"] if user else None
        survey = db.get_order_survey_by_order(o["id"]) if o.get("status") == "approved" else None
        o["survey_sent"] = bool(survey)
        o["survey_rating"] = survey["rating"] if survey else None
        out.append(o)
    return out


@app.get("/api/orders/{order_id}/receipt")
async def api_order_receipt(order_id: int, admin=Depends(get_current_admin)):
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or not order["receipt_file_id"]:
        raise HTTPException(404, tr("رسیدی برای این سفارش ثبت نشده است."))
    result = await fetch_telegram_file(_bot_token(), order["receipt_file_id"])
    if not result:
        raise HTTPException(502, tr("دریافت رسید از تلگرام ناموفق بود."))
    content, content_type = result
    return Response(content=content, media_type=content_type)


@app.get("/api/orders/{order_id}/full")
async def api_order_full(order_id: int, admin=Depends(get_current_admin)):
    """جزئیات یک سفارش برای صفحه‌ی جزئیات اپ موبایل (detail_source).

    عمداً کل سطر خام دیتابیس برگردانده نمی‌شود: صفحه‌ی جزئیات اپ (DetailScreen)
    هر فیلد primitive که این endpoint برگرداند را (به‌جز چندتای معدود در
    HIDDEN_DETAIL_KEYS سمت اپ) مستقیم به‌صورت یک ردیف نشان می‌دهد؛ سطر خام
    سفارش پر از فیلدهای داخلی/فنی (توکن بات نمایندگی، جزئیات تمدید، فلگ‌های
    ساخت کانفیگ شخصی/نمایندگی و...) بود که هیچ‌کدام برای بررسی و تایید/رد یک
    سفارش به کار ادمین نمی‌آید و فقط صفحه را شلوغ می‌کرد. اینجا فقط همان
    فیلدهایی که واقعاً برای این کار لازم است ساخته و برگردانده می‌شود."""
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order:
        raise HTTPException(404, tr("سفارش یافت نشد."))
    o = dict(order)
    product = row_to_dict(db.get_product(o["product_id"])) if o.get("product_id") else None
    user = row_to_dict(db.get_user(o["user_id"])) if o.get("user_id") else None
    result = {
        "status": o.get("status"),
        "quantity": o.get("quantity"),
        "amount": o.get("final_price"),
        "username": (user or {}).get("username"),
        "full_name": (user or {}).get("full_name"),
        "created_at": o.get("created_at"),
        "has_receipt": bool(o.get("receipt_file_id")),
    }
    # سفارش تمدید سرویس با سفارش خرید عادی/کانفیگ شخصی فرق دارد: product_id
    # آن سنتینل ۰ است (محصول واقعی ندارد)، پس جزئیاتش باید از ستون‌های
    # renewal_* خودِ سفارش ساخته شود - وگرنه (باگ قبلی) اینجا فقط "-" نشان
    # داده می‌شد و معلوم نبود اصلاً سفارش تمدید است یا برای کدام سرویس.
    if o.get("is_renewal"):
        mode_label = _RENEW_MODE_LABEL.get(o.get("renewal_mode"), o.get("renewal_mode") or "-")
        target_label = "کانفیگ شخصی" if o.get("renewal_target_kind") == "custom" else "کانفیگ بانک (استخر)"
        result["product_name"] = f"🔄 {mode_label}"
        result["renewal_target"] = f"{target_label} #{o.get('renewal_target_id')}"
        if o.get("renewal_add_volume_gb"):
            result["renewal_add_volume_gb"] = f"{o['renewal_add_volume_gb']} گیگابایت"
        if o.get("renewal_add_days"):
            result["renewal_add_days"] = f"{o['renewal_add_days']} روز"
    else:
        result["product_name"] = product["name"] if product else ("ساخت کانفیگ شخصی" if o.get("is_custom_config") else "-")
    return result


SURVEY_ERRORS = {
    "not_found": "سفارش یافت نشد.",
    "not_approved": "نظرسنجی فقط برای سفارش‌های تایید‌شده ارسال می‌شود.",
    "answered": "کاربر قبلاً به نظرسنجی این سفارش پاسخ داده است.",
}


@app.post("/api/orders/{order_id}/survey")
async def api_send_order_survey(order_id: int, admin=Depends(require_permission("orders"))):
    result = await asyncio.to_thread(db.create_order_survey, order_id, admin["id"])
    if not result["ok"]:
        raise HTTPException(400, SURVEY_ERRORS.get(result["reason"], tr("ارسال نظرسنجی ممکن نیست.")))
    survey_id = result["survey_id"]
    markup = {"inline_keyboard": [[{"text": f"{n}⭐", "callback_data": f"svy:{survey_id}:{n}"} for n in range(1, 6)]]}
    text = f"🗳 نظرسنجی\n\nکیفیت سرویس سفارش #{order_id} را چطور ارزیابی می‌کنی؟\n(۱ = ضعیف تا ۵ = عالی)"
    if not await tg_send(_bot_token(), result["user_id"], text, reply_markup=markup):
        raise HTTPException(502, tr("ارسال پیام به کاربر ناموفق بود (شاید بات را بلاک کرده)."))
    (await asyncio.to_thread(db.log_admin_action,
        admin["id"], "order_survey_send", f"سفارش #{order_id} | کاربر {result['user_id']} (پنل وب - {admin['username']})",
        "order", order_id,
    ))
    return {"ok": True}


@app.get("/api/order-surveys/summary")
def api_order_survey_summary(admin=Depends(get_current_admin)):
    return db.get_survey_summary()


@app.get("/api/orders/{order_id}/receipt-base64")
async def api_order_receipt_base64(order_id: int, admin=Depends(get_current_admin)):
    """نسخه‌ی JSON/base64 رسید، مخصوص اپ موبایل (که به‌جای کوکی از Bearer
    توکن استفاده می‌کند و نمی‌تواند مستقیماً از یک <img src> با هدر سفارشی
    عکس بارگذاری کند)."""
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or not order["receipt_file_id"]:
        raise HTTPException(404, tr("رسیدی برای این سفارش ثبت نشده است."))
    result = await fetch_telegram_file(_bot_token(), order["receipt_file_id"])
    if not result:
        raise HTTPException(502, tr("دریافت رسید از تلگرام ناموفق بود."))
    content, content_type = result
    return {"content_type": content_type, "data_base64": base64.b64encode(content).decode("ascii")}


@app.post("/api/orders/{order_id}/approve")
async def api_approve_order(order_id: int, admin=Depends(require_permission("orders"))):
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or order["status"] != "pending":
        raise HTTPException(400, tr("سفارش یافت نشد یا قبلاً بررسی شده."))
    if not (await asyncio.to_thread(db.claim_order, order_id)):
        raise HTTPException(400, tr("سفارش یافت نشد یا قبلاً بررسی شده."))

    if order["is_renewal"]:
        try:
            result_text = await execute_renewal(db, order)
        except RenewalError as e:
            await asyncio.to_thread(db.release_order_claim, order_id)
            raise HTTPException(400, tr(f"تمدید ناموفق بود: {e}"))
        except Exception:
            logger.exception("خطای غیرمنتظره در execute_renewal برای سفارش تمدید #%s (پنل وب)", order_id)
            await asyncio.to_thread(db.release_order_claim, order_id)
            raise HTTPException(400, tr("خطای غیرمنتظره‌ای در تمدید رخ داد. سفارش برای بررسی دوباره آزاد شد؛ لاگ سرور را بررسی کن."))
        (await asyncio.to_thread(db.approve_renewal_order, order_id))
        (await asyncio.to_thread(db.log_admin_action,
            admin["id"], "renewal_approve",
            f"سفارش تمدید #{order_id} | کاربر {order['user_id']} | مبلغ: {order['final_price']:,} (پنل وب - {admin['username']})",
            "order", order_id,
        ))
        await notify_user(order["user_id"], result_text)
        return {"ok": True}

    if order["is_custom_config"]:
        server = (await asyncio.to_thread(db.get_panel_server, order["custom_panel_server_id"]))
        if not server or not server["is_active"]:
            await asyncio.to_thread(db.release_order_claim, order_id)
            raise HTTPException(400, tr("سرور پنل مربوطه یافت نشد یا غیرفعال است."))

        try:
            provider = get_provider(server)
            result = await provider.create_user(
                username=order["custom_username"],
                volume_gb=order["custom_volume_gb"],
                duration_days=(await asyncio.to_thread(db.get_custom_config_settings))["duration_days"],
            )
        except PanelUsernameTakenError:
            await asyncio.to_thread(db.release_order_claim, order_id)
            raise HTTPException(400, tr("این نام کاربری روی پنل تکراری است؛ از کاربر بخواه نام دیگری انتخاب کند."))
        except PanelError as e:
            await asyncio.to_thread(db.release_order_claim, order_id)
            raise HTTPException(400, tr(f"خطا در ارتباط با پنل: {e}"))

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
            await asyncio.to_thread(db.release_order_claim, order_id)
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
        await asyncio.to_thread(db.release_order_claim, order_id)
        raise HTTPException(400, tr("موجودی این محصول تمام شده است."))
    (await asyncio.to_thread(db.approve_order, order_id, [r["id"] for r in results]))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "order_approve",
        f"سفارش #{order_id} | کاربر {order['user_id']} | محصول «{product['name'] if product else '---'}» (پنل وب - {admin['username']})",
        "order", order_id,
    ))
    await check_and_notify_low_stock(
        lambda aid, text: tg_send(_bot_token(), aid, text), db, order["product_id"], bot_token=_bot_token(),
    )
    (await asyncio.to_thread(db.reward_referrer_if_first_purchase, order["user_id"], order["final_price"] or (product["price"] if product else 0)))
    links = [r["link"] for r in results]
    await notify_user(order["user_id"], "✅ خرید شما تایید شد!")
    asyncio.create_task(deliver_config_to_user_web(
        order["user_id"], product["name"] if product else "", links,
        final_price=order["final_price"], order_id=order_id, db=db, bot_token=_bot_token(),
    ))
    return {"ok": True}


@app.post("/api/orders/{order_id}/fake-receipt")
async def api_fake_receipt_order(order_id: int, admin=Depends(require_permission("orders"))):
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or order["status"] != "pending":
        raise HTTPException(400, tr("سفارش یافت نشد یا قبلاً بررسی شده."))
    result = await asyncio.to_thread(db.fake_receipt_order, order_id)
    if not result:
        raise HTTPException(400, tr("سفارش یافت نشد یا قبلاً بررسی شده."))
    await asyncio.to_thread(
        db.log_admin_action,
        admin["id"],
        "order_fake_receipt",
        f"فیش فیک سفارش #{order_id} | کاربر {order['user_id']} | {result['deleted_configs']} کانفیگ حذف شد و کاربر بلاک شد (پنل وب - {admin['username']})",
        "order", order_id,
    )
    await notify_user(
        order["user_id"],
        "🚫 فیش فیک تشخیص داده شد.\n\n"
        "⛔️ سفارش شما رد شد و حساب کاربری‌تان بلاک شد.\n"
        "در صورت اشتباه، برای بررسی موضوع با پشتیبانی تماس بگیرید.",
    )
    return {"ok": True, "deleted_configs": result["deleted_configs"], "blocked": True}


@app.post("/api/orders/{order_id}/reject")
async def api_reject_order(order_id: int, admin=Depends(require_permission("orders"))):
    order = (await asyncio.to_thread(db.get_order, order_id))
    if not order or order["status"] != "pending":
        raise HTTPException(400, tr("سفارش یافت نشد یا قبلاً بررسی شده."))
    if not (await asyncio.to_thread(db.reject_order, order_id)):
        raise HTTPException(400, tr("سفارش یافت نشد یا قبلاً بررسی شده."))
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
        t["has_receipt"] = bool(t.get("receipt_file_id"))
        out.append(t)
    return out


@app.get("/api/topups/{topup_id}/receipt")
async def api_topup_receipt(topup_id: int, admin=Depends(get_current_admin)):
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup or not topup["receipt_file_id"]:
        raise HTTPException(404, tr("رسیدی برای این شارژ ثبت نشده است."))
    result = await fetch_telegram_file(_bot_token(), topup["receipt_file_id"])
    if not result:
        raise HTTPException(502, tr("دریافت رسید از تلگرام ناموفق بود."))
    content, content_type = result
    return Response(content=content, media_type=content_type)


@app.get("/api/topups/{topup_id}/full")
async def api_topup_full(topup_id: int, admin=Depends(get_current_admin)):
    """جزئیات یک درخواست شارژ کیف‌پول برای صفحه‌ی جزئیات اپ موبایل (detail_source)،
    مشابه /api/orders/{id}/full."""
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup:
        raise HTTPException(404, tr("درخواست شارژ یافت نشد."))
    t = dict(topup)
    user = row_to_dict(db.get_user(t["user_id"])) if t.get("user_id") else None
    return {
        "status": t.get("status"),
        "amount": t.get("amount"),
        "username": (user or {}).get("username"),
        "full_name": (user or {}).get("full_name"),
        "created_at": t.get("created_at"),
        "has_receipt": bool(t.get("receipt_file_id")),
    }


@app.get("/api/topups/{topup_id}/receipt-base64")
async def api_topup_receipt_base64(topup_id: int, admin=Depends(get_current_admin)):
    """نسخه‌ی JSON/base64 رسید، مخصوص اپ موبایل (مشابه /api/orders/{id}/receipt-base64)."""
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup or not topup["receipt_file_id"]:
        raise HTTPException(404, tr("رسیدی برای این شارژ ثبت نشده است."))
    result = await fetch_telegram_file(_bot_token(), topup["receipt_file_id"])
    if not result:
        raise HTTPException(502, tr("دریافت رسید از تلگرام ناموفق بود."))
    content, content_type = result
    return {"content_type": content_type, "data_base64": base64.b64encode(content).decode("ascii")}


@app.post("/api/topups/{topup_id}/approve")
async def api_approve_topup(topup_id: int, admin=Depends(require_permission("orders"))):
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup:
        raise HTTPException(404, tr("یافت نشد."))
    if not (await asyncio.to_thread(db.approve_topup, topup_id)):
        raise HTTPException(400, tr("قبلاً بررسی شده است."))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "topup_approve", f"شارژ #{topup_id} تایید شد (پنل وب - {admin['username']})", "topup", topup_id))
    await notify_user(topup["user_id"], f"✅ شارژ کیف پول شما به مبلغ {topup['amount']:,} تومان تایید شد.")
    return {"ok": True}


@app.post("/api/topups/{topup_id}/reject")
async def api_reject_topup(topup_id: int, admin=Depends(require_permission("orders"))):
    topup = (await asyncio.to_thread(db.get_topup, topup_id))
    if not topup or topup["status"] != "pending":
        raise HTTPException(400, tr("یافت نشد یا قبلاً بررسی شده."))
    if not (await asyncio.to_thread(db.reject_topup, topup_id)):
        raise HTTPException(400, tr("یافت نشد یا قبلاً بررسی شده."))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "topup_reject", f"شارژ #{topup_id} رد شد (پنل وب - {admin['username']})", "topup", topup_id))
    await notify_user(topup["user_id"], "⛔️ درخواست شارژ کیف پول شما رد شد.")
    return {"ok": True}


# ------------------------------------------------------------------- users --


@app.get("/api/users")
def api_users(q: str = "", status: str = "all", page: int = 1, sort: str = "newest", admin=Depends(get_current_admin)):
    limit = 25
    rows, total = db.search_users(q, status, limit=limit, offset=(page - 1) * limit, sort=sort)
    items = []
    for r in rows:
        row = dict(r)
        # alias‌های زیر فقط برای فرمت لیست ساده‌ی اپ اندروید (tg_id/full_name/wallet_balance)
        # هستند؛ ستون واقعی جدول users به همان شکل هم برای صفحه‌ی جزئیات کاربر باقی می‌ماند.
        row["tg_id"] = row["telegram_id"]
        row["full_name"] = row.get("first_name") or (f"@{row['username']}" if row.get("username") else str(row["telegram_id"]))
        row["wallet_balance"] = row.get("referral_credit", 0)
        # برای اینکه چیپ‌های فیلتر وضعیت در اپ اندروید (که بعد از فچ سرور یک
        # بارِ دیگر هم لوکال چک می‌کنند) با پاسخ سرور ناسازگار نشوند.
        row["status"] = db.get_user_status(row["telegram_id"])
        # is_blocked در دیتابیس INTEGER (0/1) است؛ اینجا به bool واقعی تبدیل
        # می‌شود تا هم در JSON به‌صورت true/false برسد (نه 0/1) و هم دکمه‌ی
        # نمایش‌شرطی «مسدود/رفع مسدودی» در اپ اندروید درست کار کند.
        row["is_blocked"] = bool(row.get("is_blocked"))
        items.append(row)
    return {"items": items, "total": total, "page": page, "limit": limit}


@app.get("/api/users/{tg_id}")
def api_user_detail(tg_id: int, admin=Depends(get_current_admin)):
    user = db.get_user(tg_id)
    if not user:
        raise HTTPException(404, tr("کاربر یافت نشد."))
    history = db.get_user_full_history(tg_id)
    user_dict = dict(user)
    # همان تبدیل is_blocked به bool واقعی که در /api/users انجام می‌شود، اینجا
    # هم لازم است تا صفحه‌ی جزئیات کاربر (وب و اندروید) وضعیت را درست بخواند.
    user_dict["is_blocked"] = bool(user_dict.get("is_blocked"))
    return {
        "user": user_dict,
        "orders": rows_to_list(history["orders"]),
        "topups": rows_to_list(history["topups"]),
        "wallet_transactions": db.get_wallet_transaction_entries(tg_id, 50),
        "referral": db.get_referral_stats(tg_id),
        "is_reseller": db.is_reseller(tg_id),
        "agent_tier": db.get_agent_tier(tg_id),
        "reseller_credit": db.get_reseller_credit(tg_id),
        "wallet_status": db.get_wallet_status(tg_id),
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


class UserMessageBody(BaseModel):
    text: str


@app.post("/api/users/{tg_id}/message")
async def api_message_user(tg_id: int, body: UserMessageBody, admin=Depends(require_permission("users"))):
    """پیام مستقیم به یک کاربر خاص (نه پیام همگانی) - معادل همین قابلیت در مینی‌اپ."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, tr("متن پیام نمی‌تواند خالی باشد."))
    if len(text) > 4000:
        raise HTTPException(400, tr("متن پیام بیش از حد طولانی است."))
    user = row_to_dict(db.get_user(tg_id))
    if not user:
        raise HTTPException(404, tr("کاربری با این آیدی عددی پیدا نشد."))
    ok = await tg_send(_bot_token(), tg_id, f"📩 پیام از پشتیبانی:\n\n{text}")
    if not ok:
        raise HTTPException(502, tr("ارسال پیام به کاربر ناموفق بود (شاید بات را بلاک کرده)."))
    (await asyncio.to_thread(db.log_admin_action,
        admin["id"], "user_message", f"پیام مستقیم به کاربر {tg_id} ارسال شد (پنل وب - {admin['username']})",
        "user", tg_id,
    ))
    return {"ok": True}


class WalletAdjustBody(BaseModel):
    delta: int


@app.post("/api/users/{tg_id}/wallet")
async def api_adjust_wallet(tg_id: int, body: WalletAdjustBody, admin=Depends(require_permission("users"))):
    (await asyncio.to_thread(db.add_wallet_credit, tg_id, body.delta, "admin_adjust", f"تنظیم دستی توسط ادمین ({admin['username']})"))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "wallet_adjust", f"کیف پول کاربر {tg_id} به میزان {body.delta:,} تغییر کرد (پنل وب - {admin['username']})",
        "user", tg_id,
    ))
    if body.delta:
        sign = "افزایش" if body.delta > 0 else "کاهش"
        await notify_user(tg_id, f"💰 موجودی کیف پول شما {sign} یافت: {abs(body.delta):,} تومان")
    return {"ok": True}


MAX_CREDIT_LIMIT_TOMAN = 10_000_000_000


class CreditLimitBody(BaseModel):
    amount: int


@app.put("/api/users/{tg_id}/credit-limit")
async def api_set_user_credit_limit(tg_id: int, body: CreditLimitBody, admin=Depends(require_permission("resellers"))):
    if not 0 <= body.amount <= MAX_CREDIT_LIMIT_TOMAN:
        raise HTTPException(400, tr("سقف اعتبار باید بین ۰ تا ۱۰ میلیارد تومان باشد."))
    if not await asyncio.to_thread(db.set_credit_limit, tg_id, body.amount):
        raise HTTPException(404, tr("کاربر یافت نشد."))
    (await asyncio.to_thread(db.log_admin_action,
        admin["id"], "reseller_credit_limit", f"کاربر {tg_id} | سقف اعتبار پس‌پرداخت {body.amount:,} تومان (پنل وب - {admin['username']})",
        "user", tg_id,
    ))
    return {"ok": True, "wallet_status": await asyncio.to_thread(db.get_wallet_status, tg_id)}


# ---------------------------------------------------------------- user services --
# مدیریت سرویس‌های مستقیم-پنل یک کاربر خاص از سمت ادمین؛ معادل دکمه‌های
# «سرویس‌های من» در ربات (svc_toggle/svc_rename/svc_autorenew/svc_transfer/
# svc_hist/svc_cut در handlers_user.py) که تا امروز فقط خودِ کاربر در ربات
# به آن‌ها دسترسی داشت. همان توابع دیتابیس/پروایدر اینجا هم استفاده می‌شوند.

def _admin_get_custom_config_or_404(custom_config_id: int):
    row = db.get_custom_config_by_id(custom_config_id)
    if not row:
        raise HTTPException(404, tr("کانفیگ یافت نشد."))
    return row


@app.get("/api/users/{tg_id}/custom-configs")
def api_user_custom_configs(tg_id: int, admin=Depends(get_current_admin)):
    configs = db.get_custom_configs_for_user(tg_id)
    return [
        {
            "id": c["id"],
            "username": c["username"],
            "display_name": c["display_name"] or c["username"],
            "volume_gb": c["volume_gb"],
            "duration_days": c["duration_days"],
            "subscription_url": c["subscription_url"],
            "created_at": c["created_at"],
            "expires_at": c["expires_at"],
            "is_test": c["source"] == "test",
            "enabled": (c["enabled"] if "enabled" in c.keys() else 1) == 1,
            "auto_renew": (c["auto_renew"] if "auto_renew" in c.keys() else 0) == 1,
        }
        for c in configs
    ]


# کانفیگ‌های «بانک محصول» (لینک‌های ساده‌ی از پیش‌آماده که به کاربر اختصاص
# یافته‌اند - نه سرویس‌های مستقیم-پنل بالا) که پیش‌تر فقط از پنل ادمین داخل
# مینی‌اپ قابل مشاهده/غیرفعال‌سازی/حذف بودند؛ همان توابع دیتابیس اینجا هم
# استفاده می‌شوند تا رفتار دقیقاً یکسان باشد.

@app.get("/api/users/{tg_id}/configs")
def api_user_bank_configs(tg_id: int, admin=Depends(get_current_admin)):
    rows = db.get_bank_configs_for_user(tg_id)
    return [
        {
            "id": c["id"],
            "product_name": c["product_name"] or "نامشخص",
            "order_id": c["order_display_id"],
            "link": c["link"],
            "assigned_at": c["assigned_at"],
            "expires_at": c["expires_at"] if "expires_at" in c.keys() else None,
            "is_used": bool(c["is_used"]),
            "is_disabled": bool(c["is_disabled"]) if "is_disabled" in c.keys() else False,
            "last_activity": (lambda a: {"action": a["action"], "details": a["details"], "created_at": a["created_at"]} if a else None)(db.get_last_config_activity(c["id"])),
        }
        for c in rows
    ]


@app.get("/api/user-configs/{config_id}/activity")
def api_user_config_activity(config_id: int, admin=Depends(get_current_admin)):
    row = db.get_config_by_id(config_id)
    if not row:
        raise HTTPException(404, tr("کانفیگ یافت نشد."))
    return [dict(a) for a in db.get_config_activity(config_id)]


class ConfigDisableBody(BaseModel):
    disabled: bool


@app.post("/api/user-configs/{config_id}/disable")
def api_user_config_disable(config_id: int, body: ConfigDisableBody, admin=Depends(require_permission("users"))):
    row = db.get_config_by_id(config_id)
    if not row:
        raise HTTPException(404, tr("کانفیگ یافت نشد."))
    db.set_config_disabled(config_id, body.disabled)
    db.log_admin_action(
        admin["id"], "config_disable" if body.disabled else "config_enable",
        f"کانفیگ #{config_id} کاربر {row['assigned_user_id']} {'غیرفعال' if body.disabled else 'فعال'} شد (پنل وب - {admin['username']})",
        "user", row["assigned_user_id"],
    )
    return {"status": "ok", "is_disabled": body.disabled}


@app.delete("/api/user-configs/{config_id}")
def api_user_config_delete(config_id: int, admin=Depends(require_permission("users"))):
    row = db.admin_delete_bank_config(config_id)
    if not row:
        raise HTTPException(404, tr("کانفیگ یافت نشد."))
    db.log_admin_action(
        admin["id"], "config_delete_admin",
        f"کانفیگ #{config_id} کاربر {row['assigned_user_id']} حذف شد (پنل وب - {admin['username']})",
        "user", row["assigned_user_id"],
    )
    return {"status": "ok"}


@app.post("/api/custom-configs/{custom_config_id}/toggle")
async def api_admin_custom_config_toggle(custom_config_id: int, admin=Depends(require_permission("users"))):
    cc = _admin_get_custom_config_or_404(custom_config_id)
    if cc["source"] == "test":
        raise HTTPException(403, tr("این قابلیت برای کانفیگ تست در دسترس نیست."))
    new_enabled = not ((cc["enabled"] if "enabled" in cc.keys() else 1) == 1)
    server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
    if not server or not server["is_active"]:
        raise HTTPException(409, tr("سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است."))
    try:
        provider = get_provider(server)
        await provider.set_enabled(cc["username"], new_enabled)
    except PanelError as e:
        raise HTTPException(502, tr(f"ناموفق بود: {e}"))
    (await asyncio.to_thread(db.set_custom_config_enabled, cc["id"], cc["user_id"], new_enabled))
    (await asyncio.to_thread(db.add_custom_config_history, cc["id"], "toggle",
        f"{'فعال' if new_enabled else 'غیرفعال'} شد (پنل وب - {admin['username']})"))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "custom_config_toggle",
        f"سرویس «{cc['username']}» کاربر {cc['user_id']} {'فعال' if new_enabled else 'غیرفعال'} شد (پنل وب)",
        "user", cc["user_id"]))
    return {"status": "ok", "enabled": new_enabled}


class AdminSvcRenameBody(BaseModel):
    new_name: str


@app.post("/api/custom-configs/{custom_config_id}/rename")
async def api_admin_custom_config_rename(custom_config_id: int, body: AdminSvcRenameBody,
                                          admin=Depends(require_permission("users"))):
    cc = _admin_get_custom_config_or_404(custom_config_id)
    if cc["source"] == "test":
        raise HTTPException(403, tr("این قابلیت برای کانفیگ تست در دسترس نیست."))
    new_label = (body.new_name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", new_label):
        raise HTTPException(400, tr("نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر."))
    current_label = cc["display_name"] or cc["username"]
    if new_label == current_label:
        raise HTTPException(400, tr("این نام همان نام فعلی است."))
    if (await asyncio.to_thread(db.is_custom_username_taken, new_label)):
        raise HTTPException(409, tr("این نام قبلاً استفاده شده. نام دیگری انتخاب کنید."))
    server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
    panel_username = None
    note = "فقط نام نمایشی داخل بات تغییر کرد؛ لینک/کانفیگ فعلی روی پنل بدون تغییر کار می‌کند."
    if server and server["is_active"]:
        try:
            provider = get_provider(server)
            await provider.rename_user(cc["username"], new_label)
            panel_username = new_label
            note = "روی خودِ پنل هم اعمال شد."
        except PanelError:
            pass
    (await asyncio.to_thread(db.rename_custom_config, cc["id"], cc["user_id"], new_label, panel_username))
    (await asyncio.to_thread(db.add_custom_config_history, cc["id"], "rename",
        f"{current_label} ← {new_label} ({note}) (پنل وب - {admin['username']})"))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "custom_config_rename",
        f"سرویس «{current_label}» کاربر {cc['user_id']} به «{new_label}» تغییر نام کرد (پنل وب)",
        "user", cc["user_id"]))
    return {"status": "ok", "display_name": new_label, "note": note}


class AdminSvcAutoRenewBody(BaseModel):
    enabled: bool


@app.post("/api/custom-configs/{custom_config_id}/auto-renew")
async def api_admin_custom_config_auto_renew(custom_config_id: int, body: AdminSvcAutoRenewBody,
                                              admin=Depends(require_permission("users"))):
    cc = _admin_get_custom_config_or_404(custom_config_id)
    if cc["source"] == "test":
        raise HTTPException(403, tr("این قابلیت برای کانفیگ تست در دسترس نیست."))
    if (cc["duration_days"] or 0) <= 0:
        raise HTTPException(400, tr("این کانفیگ نامحدود است و نیازی به تمدید خودکار ندارد."))
    (await asyncio.to_thread(db.set_custom_config_auto_renew, cc["id"], cc["user_id"], body.enabled))
    (await asyncio.to_thread(db.add_custom_config_history, cc["id"], "auto_renew_toggle",
        f"{'فعال' if body.enabled else 'غیرفعال'} شد (پنل وب - {admin['username']})"))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "custom_config_auto_renew",
        f"تمدید خودکار سرویس «{cc['username']}» کاربر {cc['user_id']} {'فعال' if body.enabled else 'غیرفعال'} شد (پنل وب)",
        "user", cc["user_id"]))
    return {"status": "ok", "auto_renew": body.enabled}


class AdminSvcTransferBody(BaseModel):
    target_telegram_id: int


@app.post("/api/custom-configs/{custom_config_id}/transfer")
async def api_admin_custom_config_transfer(custom_config_id: int, body: AdminSvcTransferBody,
                                            admin=Depends(require_permission("users"))):
    cc = _admin_get_custom_config_or_404(custom_config_id)
    if cc["source"] == "test":
        raise HTTPException(403, tr("این قابلیت برای کانفیگ تست در دسترس نیست."))
    target_id = body.target_telegram_id
    if target_id == cc["user_id"]:
        raise HTTPException(400, tr("این کانفیگ همین الان مال همین کاربر است."))
    target_user = (await asyncio.to_thread(db.get_user, target_id))
    if not target_user:
        raise HTTPException(404, tr("این کاربر بات را استارت نکرده یا آی‌دی نادرست است."))
    from_user_id = cc["user_id"]
    ok = (await asyncio.to_thread(db.transfer_custom_config, cc["id"], from_user_id, target_id))
    if not ok:
        raise HTTPException(409, tr("انتقال ناموفق بود."))
    label = cc["display_name"] or cc["username"]
    (await asyncio.to_thread(db.add_custom_config_history, cc["id"], "transfer",
        f"از {from_user_id} به {target_id} (پنل وب - {admin['username']})"))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "custom_config_transfer",
        f"سرویس «{label}» از کاربر {from_user_id} به {target_id} منتقل شد (پنل وب)",
        "user", from_user_id))
    await notify_user(target_id, f"📦 یک کانفیگ («{label}») از طرف مدیریت به حساب شما منتقل شد.\n"
                                  "برای مشاهده، حساب کاربری ← سرویس‌ها و سفارش‌های من را ببینید.")
    return {"status": "ok"}


@app.get("/api/custom-configs/{custom_config_id}/history")
def api_admin_custom_config_history(custom_config_id: int, admin=Depends(get_current_admin)):
    cc = _admin_get_custom_config_or_404(custom_config_id)
    rows = db.get_custom_config_history(cc["id"])
    return [
        {"event_type": r["event_type"], "detail": r["detail"], "created_at": r["created_at"]}
        for r in rows
    ]


@app.post("/api/custom-configs/{custom_config_id}/cut-access")
async def api_admin_custom_config_cut_access(custom_config_id: int, admin=Depends(require_permission("users"))):
    cc = _admin_get_custom_config_or_404(custom_config_id)
    if cc["source"] == "test":
        raise HTTPException(403, tr("این قابلیت برای کانفیگ تست در دسترس نیست."))
    server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
    if not server or not server["is_active"]:
        raise HTTPException(409, tr("سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است."))
    try:
        provider = get_provider(server)
        result = await provider.revoke_credentials(cc["username"])
    except PanelError as e:
        raise HTTPException(502, tr(f"قطع دسترسی ناموفق بود: {e}"))
    if result.subscription_url:
        (await asyncio.to_thread(db.update_custom_config_subscription_url, cc["id"], result.subscription_url))
    (await asyncio.to_thread(db.add_custom_config_history, cc["id"], "cut_access",
        f"دسترسی قطع و لینک جدید صادر شد (پنل وب - {admin['username']})"))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "custom_config_cut_access",
        f"دسترسی سرویس «{cc['username']}» کاربر {cc['user_id']} قطع و لینک جدید صادر شد (پنل وب)",
        "user", cc["user_id"]))
    return {"status": "ok", "subscription_url": result.subscription_url}


@app.delete("/api/custom-configs/{custom_config_id}")
async def api_admin_custom_config_delete(custom_config_id: int, admin=Depends(require_permission("users"))):
    """حذف کامل یک سرویس مستقیم-پنل: هم از روی خودِ پنل VPN (best-effort) و هم
    از دیتابیس. برخلاف «قطع دسترسی» که فقط لینک را عوض می‌کند، این عملیات
    برگشت‌ناپذیر است و کاربر را کاملاً از این سرویس محروم می‌کند."""
    cc = _admin_get_custom_config_or_404(custom_config_id)
    if cc["source"] == "test":
        raise HTTPException(403, tr("این قابلیت برای کانفیگ تست در دسترس نیست."))
    if cc["panel_server_id"]:
        server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
        if server:
            try:
                provider = get_provider(server)
                await provider.delete_user(cc["username"])
            except Exception:
                logging.getLogger("admin_panel").exception(
                    "حذف کاربر «%s» از پنل سرور #%s ناموفق بود؛ در هر صورت از دیتابیس حذف می‌شود.",
                    cc["username"], cc["panel_server_id"],
                )
    (await asyncio.to_thread(db.delete_owned_custom_config, custom_config_id, cc["user_id"]))
    (await asyncio.to_thread(db.log_admin_action, admin["id"], "custom_config_delete_admin",
        f"سرویس «{cc['username']}» کاربر {cc['user_id']} حذف شد (پنل وب - {admin['username']})",
        "user", cc["user_id"]))
    return {"status": "ok"}


# ------------------------------------------------------- reseller self-service --
# پنل وب نماینده «مدیریت کاتالوگ» نیست؛ یک فضای عملیاتی شخصی است.
# نماینده فقط موجودی‌ای را که مدیر به او داده مصرف می‌کند و هرگز به محصولات/پنل‌های
# اصلی برای ویرایش، حذف یا ساخت دسترسی پیدا نمی‌کند.


def _require_reseller_admin(admin):
    if not admin.get("tenant"):
        raise HTTPException(403, tr("این بخش فقط از پنل نمایندگی در دسترس است."))
    return admin.get("reseller_profile") or {}


def _reseller_owner_id_or_404():
    tenant = _current_tenant.get()
    if not tenant.bot_id:
        raise HTTPException(403, tr("نمایندگی معتبر نیست."))
    row = main_db.get_reseller_bot(tenant.bot_id)
    if not row or not row["is_active"]:
        raise HTTPException(403, tr("نمایندگی غیرفعال است."))
    return int(row["owner_telegram_id"]), row


def _reseller_product_view(p, qty=0):
    return {
        "id": int(p["id"]), "name": p["name"], "description": p["description"] or "",
        "price": int(p["price"] or 0), "duration_days": int(p["duration_days"] or 0),
        "volume_gb": int(p["auto_provision_volume_gb"] or 0),
        "provision_server_id": p["provision_server_id"], "qty": int(qty or 0),
        "is_active": bool(p["is_active"]),
    }


@app.get("/api/reseller/dashboard-chart")
async def api_reseller_dashboard_chart(admin=Depends(get_current_admin)):
    """چارت فروش (روند ۱۴ روز اخیر) و موجودی/اعتبار نمایندگی برای داشبورد پنل نمایندگی وب (تیر گلد/VIP)."""
    _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    advanced = await asyncio.to_thread(db.get_advanced_stats)
    supply = await asyncio.to_thread(main_db.get_reseller_supply, owner_id)
    balance = {"model": supply["model"]}
    if supply["model"] == "fixed_product":
        inventory = await asyncio.to_thread(main_db.get_reseller_product_inventory, owner_id)
        balance["products"] = [
            {"name": row["name"], "qty_remaining": int(row["qty_remaining"] or 0)}
            for row in inventory if row["is_active"]
        ]
    else:
        credit = await asyncio.to_thread(main_db.get_reseller_credit, owner_id)
        balance["credit_gb"] = int(credit or 0)
    return {"sales_trend": advanced["revenue_trend"], "balance": balance}


@app.get("/api/reseller/self-service")
async def api_reseller_self_service(admin=Depends(get_current_admin)):
    profile = _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    supply = await asyncio.to_thread(main_db.get_reseller_supply, owner_id)
    credit = await asyncio.to_thread(main_db.get_reseller_credit, owner_id)
    inventory = await asyncio.to_thread(main_db.get_reseller_product_inventory, owner_id)
    tenant_db = _current_tenant.get().db
    services = await asyncio.to_thread(tenant_db_get_custom_configs, tenant_db, owner_id)
    fixed = []
    for row in inventory:
        if int(row["qty_remaining"] or 0) > 0 and row["is_active"] and row["is_auto_provision"]:
            fixed.append(_reseller_product_view(row, row["qty_remaining"]))
    settings = await asyncio.to_thread(main_db.get_custom_config_settings)
    return {
        "profile": profile,
        "supply": {"model": supply["model"], "fixed_product_id": supply["product_id"], "credit_gb": int(credit or 0)},
        "inventory": fixed,
        "custom_limits": {"min_gb": int(settings["min_gb"]), "max_gb": int(settings["max_gb"])},
        "services": services,
    }


def tenant_db_get_custom_configs(tenant_db: Database, owner_id: int):
    # برای نماینده بدون بات، owner دیتابیس محلی همان کاربر اصلی است.
    rows = tenant_db.get_custom_configs_for_user(owner_id)
    return [
        {"id": c["id"], "username": c["username"], "display_name": c["display_name"] or c["username"],
         "volume_gb": c["volume_gb"], "duration_days": c["duration_days"],
         "subscription_url": c["subscription_url"], "created_at": c["created_at"], "expires_at": c["expires_at"],
         "enabled": (c["enabled"] if "enabled" in c.keys() else 1) == 1,
         "auto_renew": (c["auto_renew"] if "auto_renew" in c.keys() else 0) == 1}
        for c in rows
    ]


class ResellerSelfBuildBody(BaseModel):
    volume_gb: int
    duration_days: int = 30
    username: Optional[str] = None


class ResellerSelfFixedBody(BaseModel):
    product_id: int
    quantity: int = 1


async def _build_reseller_self_config(owner_id: int, product, volume_gb: int, duration_days: int,
                                      username: Optional[str], consume_fixed: bool, quantity: int = 1):
    if volume_gb < 0:
        raise HTTPException(400, tr("حجم نامعتبر است."))
    if duration_days < 0 or duration_days > 3650:
        raise HTTPException(400, tr("مدت باید بین ۰ تا ۳۶۵۰ روز باشد؛ ۰ یعنی نامحدود."))
    if not username:
        prefix = (await asyncio.to_thread(main_db.get_custom_config_prefix)) or "r"
        username = f"{prefix}-r{secrets.token_hex(4)}" if prefix else f"r{secrets.token_hex(4)}"
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", username):
        raise HTTPException(400, tr("نام کاربری فقط می‌تواند شامل حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط باشد (۳ تا ۶۴ کاراکتر)."))

    server = None
    if product is not None and product["provision_server_id"]:
        server = await asyncio.to_thread(main_db.get_panel_server, product["provision_server_id"])
    if not server or not server["is_active"]:
        server = await asyncio.to_thread(main_db.get_reseller_panel, owner_id)
    if not server or not server["is_active"]:
        raise HTTPException(400, tr("هیچ پنل فعالی برای ساخت کانفیگ نمایندگی تنظیم نشده است."))

    provider = get_provider(server)
    try:
        result = await provider.create_user(username, volume_gb, duration_days)
    except PanelUsernameTakenError:
        raise HTTPException(400, tr("این نام کاربری روی پنل وجود دارد؛ نام دیگری انتخاب کنید."))
    except PanelError as e:
        raise HTTPException(400, tr(f"ساخت کانفیگ روی پنل ناموفق بود: {e}"))

    # مصرف اعتبار فقط بعد از ساخت موفق؛ اگر مصرف هم‌زمان شکست خورد، اکانت واقعی را rollback کن.
    if consume_fixed:
        if not await asyncio.to_thread(main_db.consume_reseller_product_credit, owner_id, int(product["id"]), quantity):
            try: await provider.delete_user(result.username)
            except Exception: logger.exception("rollback fixed reseller config failed: %s", result.username)
            raise HTTPException(409, tr("موجودی محصول هم‌زمان مصرف شد؛ دوباره تلاش کنید."))
    else:
        if not await asyncio.to_thread(main_db.consume_reseller_credit, owner_id, volume_gb * quantity,
                                       f"ساخت کانفیگ شخصی از پنل وب نماینده"):
            try: await provider.delete_user(result.username)
            except Exception: logger.exception("rollback volume reseller config failed: %s", result.username)
            raise HTTPException(409, tr("اعتبار حجمی هم‌زمان مصرف شد؛ دوباره تلاش کنید."))

    tenant_db = _current_tenant.get().db
    try:
        local_panel_id = await asyncio.to_thread(tenant_db.get_or_create_mirror_panel_server, server)
        await asyncio.to_thread(tenant_db.add_custom_config, owner_id, local_panel_id, result.username,
                                volume_gb, duration_days, result.subscription_url,
                                source="reseller", reseller_product_id=int(product["id"]) if consume_fixed else None)
    except Exception:
        # اگر ثبت محلی شکست خورد، اکانت و اعتبار را rollback می‌کنیم تا نماینده سرویس گمشده نداشته باشد.
        try: await provider.delete_user(result.username)
        except Exception: logger.exception("rollback after local reseller record failure: %s", result.username)
        if consume_fixed:
            await asyncio.to_thread(main_db.adjust_reseller_product_credit, owner_id, int(product["id"]), quantity,
                                    reason="rollback ساخت کانفیگ نماینده")
        else:
            await asyncio.to_thread(main_db.adjust_reseller_credit, owner_id, volume_gb * quantity,
                                    reason="rollback ساخت کانفیگ نماینده")
        raise HTTPException(500, tr("ثبت سرویس در پنل نماینده ناموفق بود؛ عملیات برگشت داده شد."))
    return {"username": result.username, "subscription_url": result.subscription_url,
            "volume_gb": volume_gb, "duration_days": duration_days}


@app.post("/api/reseller/self-service/fixed")
async def api_reseller_self_fixed(body: ResellerSelfFixedBody, admin=Depends(get_current_admin)):
    _require_reseller_admin(admin)
    if body.quantity != 1:
        raise HTTPException(400, tr("در حال حاضر هر بار فقط یک محصول برای استفاده شخصی دریافت می‌شود."))
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    supply = await asyncio.to_thread(main_db.get_reseller_supply, owner_id)
    if supply["model"] != "fixed_product":
        raise HTTPException(403, tr("این محصول به موجودی نمایندگی شما اختصاص داده نشده است."))
    product = await asyncio.to_thread(main_db.get_product, body.product_id)
    if not product or not product["is_active"] or not product["is_auto_provision"]:
        raise HTTPException(400, tr("محصول در دسترس نیست."))
    qty = await asyncio.to_thread(main_db.get_reseller_product_credit, owner_id, body.product_id)
    if qty < 1:
        raise HTTPException(400, tr("موجودی این محصول تمام شده است."))
    result = await _build_reseller_self_config(owner_id, product, int(product["auto_provision_volume_gb"] or 0),
                                               int(product["duration_days"] if product["duration_days"] is not None else 30),
                                               None, True, 1)
    await asyncio.to_thread(main_db.log_admin_action, admin["id"], "reseller_self_fixed",
                            f"نماینده {owner_id} محصول #{body.product_id} را برای خود مصرف کرد (پنل وب)", "reseller", owner_id)
    return result


@app.post("/api/reseller/self-service/custom")
async def api_reseller_self_custom(body: ResellerSelfBuildBody, admin=Depends(get_current_admin)):
    profile = _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    if profile.get("supply_model") != "volume_credit":
        raise HTTPException(403, tr("ساخت آزاد کانفیگ فقط برای نمایندگی دارای اعتبار حجمی فعال است."))
    settings = await asyncio.to_thread(main_db.get_custom_config_settings)
    if body.volume_gb < int(settings["min_gb"]) or body.volume_gb > int(settings["max_gb"]):
        raise HTTPException(400, tr(f"حجم باید بین {settings['min_gb']} تا {settings['max_gb']} گیگابایت باشد."))
    credit = await asyncio.to_thread(main_db.get_reseller_credit, owner_id)
    if credit < body.volume_gb:
        raise HTTPException(400, tr(f"اعتبار کافی نیست؛ موجودی فعلی {credit:,} گیگ است."))
    result = await _build_reseller_self_config(owner_id, None, body.volume_gb, body.duration_days, body.username, False, 1)
    await asyncio.to_thread(main_db.log_admin_action, admin["id"], "reseller_self_custom",
                            f"نماینده {owner_id} کانفیگ شخصی {body.volume_gb}GB/{body.duration_days}d ساخت (پنل وب)", "reseller", owner_id)
    return result


@app.get("/api/reseller/self-service/services")
async def api_reseller_self_services(admin=Depends(get_current_admin)):
    _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    return await asyncio.to_thread(tenant_db_get_custom_configs, _current_tenant.get().db, owner_id)


@app.post("/api/reseller/self-service/services/{config_id}/toggle")
async def api_reseller_self_toggle(config_id: int, admin=Depends(get_current_admin)):
    _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    cc = db.get_custom_config_owned(config_id, owner_id)
    if not cc or cc["source"] != "reseller": raise HTTPException(404, tr("سرویس یافت نشد."))
    enabled = not ((cc["enabled"] if "enabled" in cc.keys() else 1) == 1)
    if not db.set_custom_config_enabled(config_id, owner_id, enabled): raise HTTPException(400, tr("تغییر وضعیت ناموفق بود."))
    return {"ok": True, "enabled": enabled}


@app.post("/api/reseller/self-service/services/{config_id}/rename")
async def api_reseller_self_rename(config_id: int, body: dict, admin=Depends(get_current_admin)):
    _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    cc = db.get_custom_config_owned(config_id, owner_id)
    if not cc or cc["source"] != "reseller": raise HTTPException(404, tr("سرویس یافت نشد."))
    name = str(body.get("name") or "").strip()
    if not name or len(name) > 80: raise HTTPException(400, tr("نام نامعتبر است."))
    if not db.rename_custom_config(config_id, owner_id, name): raise HTTPException(400, tr("تغییر نام ناموفق بود."))
    return {"ok": True}


def _reseller_service_or_404(config_id: int, owner_id: int):
    cc = db.get_custom_config_owned(config_id, owner_id)
    if not cc or cc["source"] != "reseller":
        raise HTTPException(404, tr("سرویس یافت نشد."))
    return cc


@app.get("/api/reseller/self-service/services/{config_id}/delete-quote")
async def api_reseller_self_delete_quote(config_id: int, admin=Depends(get_current_admin)):
    """مقدار اعتبار/موجودی برگشتی احتمالی قبل از حذف سرویس نماینده."""
    _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    cc = await asyncio.to_thread(_reseller_service_or_404, config_id, owner_id)
    quote = await quote_service_refund(db, cc, owner_id, main_db)
    return {**quote, "text": refund_quote_text(quote)}


@app.delete("/api/reseller/self-service/services/{config_id}")
async def api_reseller_self_delete(config_id: int, admin=Depends(get_current_admin)):
    """حذف سرویس نماینده از پنل VPN و دیتابیس و برگرداندن اعتبار/موجودی در صورت واجد شرایط بودن."""
    _require_reseller_admin(admin)
    owner_id, _ = await asyncio.to_thread(_reseller_owner_id_or_404)
    cc = await asyncio.to_thread(_reseller_service_or_404, config_id, owner_id)
    quote = await quote_service_refund(db, cc, owner_id, main_db)
    panel_deleted = False
    if cc["panel_server_id"]:
        server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
        if server:
            try:
                panel_deleted = bool(await get_provider(server).delete_user(cc["username"]))
            except Exception:
                logger.exception("حذف کاربر «%s» از پنل سرور #%s ناموفق بود؛ در هر صورت از لیست نماینده حذف می‌شود.",
                                 cc["username"], cc["panel_server_id"])
    removed = await asyncio.to_thread(db.delete_owned_custom_config, config_id, owner_id)
    if not removed:
        raise HTTPException(404, tr("سرویس یافت نشد."))
    refunded = await grant_service_refund_credit(main_db, owner_id, quote, panel_deleted, cc["username"])
    await asyncio.to_thread(main_db.log_admin_action, admin["id"], "reseller_self_delete",
                            f"نماینده {owner_id} سرویس «{cc['username']}» را حذف کرد؛ برگشتی: {refunded} (پنل وب)",
                            "reseller", owner_id)
    return {"ok": True, "refunded": refunded, "refund_text": refund_result_text(quote, refunded)}


# ------------------------------------------------------- categories/products --


class CategoryBody(BaseModel):
    name: str


@app.get("/api/categories")
def api_categories(admin=Depends(require_permission("catalog"))):
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
    payment_methods: Optional[List[str]] = None


@app.get("/api/products")
def api_products(admin=Depends(require_permission("catalog"))):
    products = rows_to_list(db.get_all_products())
    for p in products:
        p["stock"] = db.count_available_configs(p["id"])
    return products


@app.get("/api/panel-servers-lite")
def api_panel_servers_lite(admin=Depends(require_permission("catalog"))):
    """لیست سبک پنل‌ها (فقط id/name) برای انتخاب پنل موقع ساخت محصول اتصال مستقیم."""
    return [{"id": s["id"], "name": s["name"]} for s in db.get_panel_servers(active_only=True)]


class ProductReorderBody(BaseModel):
    category_id: int
    product_ids: List[int]


@app.post("/api/products/reorder")
def api_reorder_products(body: ProductReorderBody, admin=Depends(require_permission("catalog"))):
    try:
        db.reorder_products(body.category_id, body.product_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log_admin_action(admin["id"], "product_reorder", ",".join(map(str, body.product_ids)), "product")
    return {"ok": True}


@app.post("/api/products")
def api_add_product(body: ProductBody, admin=Depends(require_permission("catalog"))):
    if body.duration_days < 0:
        raise HTTPException(400, tr("مدت اعتبار نامعتبر است."))
    if body.duration_days == 0 and not body.provision_server_id:
        raise HTTPException(400, tr("مدت نامحدود فقط برای محصولات با اتصال مستقیم به پنل ممکن است."))
    if body.provision_server_id:
        if body.auto_provision_volume_gb is None or body.auto_provision_volume_gb < 0:
            raise HTTPException(400, tr("برای اتصال مستقیم به پنل باید حجم (گیگابایت) را مشخص کنید."))
    if admin["tenant"]:
        # نمایندگی (بند ۳.۲ اسپک): نه پنل شخصی دارد، نه بانک کانفیگ دستی؛ فقط
        # محصول خودکار از اعتبار حجمی/موجودی خودش مجاز است (مطابق منطق طرف بات).
        if body.provision_server_id:
            raise HTTPException(403, tr("اتصال مستقیم به پنل فقط برای بات اصلی مجاز است."))
        if not body.is_auto_provision:
            raise HTTPException(403, tr("این نمایندگی فقط می‌تواند محصول خودکار (از اعتبار حجمی) بسازد؛ نه بانک کانفیگ دستی."))
    pid = db.add_product(
        body.category_id, body.name, body.price, body.description, body.duration_days,
        body.is_auto_provision or bool(body.provision_server_id), body.auto_provision_volume_gb,
        body.provision_server_id, payment_methods=body.payment_methods,
    )
    pm_log = "همه" if not body.payment_methods else "، ".join(body.payment_methods)
    db.log_admin_action(admin["id"], "product_add", f"{body.name} | پرداخت: {pm_log} (پنل وب - {admin['username']})", "product", pid)
    return {"id": pid}


class ProductEditBody(BaseModel):
    category_id: Optional[int] = None
    name: Optional[str] = None
    price: Optional[int] = None
    description: Optional[str] = None
    duration_days: Optional[int] = None
    # اگر ارسال شود ("bank" یا "direct")، منبع تأمین محصول تغییر می‌کند (امکانی که
    # قبلاً فقط موقع «ساخت» محصول بود و بعد از آن دیگر قابل تغییر نبود).
    source: Optional[str] = None
    provision_server_id: Optional[int] = None
    auto_provision_volume_gb: Optional[int] = None


@app.put("/api/products/{product_id}")
def api_edit_product(product_id: int, body: ProductEditBody, admin=Depends(require_permission("catalog"))):
    old_product = db.get_product(product_id)
    if not old_product:
        raise HTTPException(status_code=404, detail=tr("محصول یافت نشد."))

    if body.category_id is not None and not db.get_category(body.category_id):
        raise HTTPException(status_code=404, detail=tr("دسته‌بندی یافت نشد."))

    if body.source is not None and body.source not in ("bank", "direct"):
        raise HTTPException(status_code=400, detail=tr("منبع تأمین نامعتبر است."))

    # سنتینل Ellipsis یعنی «بدون تغییر» (به db.edit_product پاس داده می‌شود).
    is_auto_provision = ...
    provision_server_id = ...
    auto_provision_volume_gb = ...

    if body.source == "direct":
        if admin["tenant"]:
            raise HTTPException(status_code=403, detail=tr("اتصال مستقیم به پنل فقط برای بات اصلی مجاز است."))
        if not body.provision_server_id or not db.get_panel_server(body.provision_server_id):
            raise HTTPException(status_code=404, detail=tr("سرور پنل یافت نشد."))
        if body.auto_provision_volume_gb is None or body.auto_provision_volume_gb < 0:
            raise HTTPException(status_code=400, detail=tr("برای اتصال مستقیم به پنل باید حجم (گیگابایت) را مشخص کنید."))
        is_auto_provision = True
        provision_server_id = body.provision_server_id
        auto_provision_volume_gb = body.auto_provision_volume_gb
    elif body.source == "bank":
        if body.duration_days is None and old_product["duration_days"] == 0:
            raise HTTPException(status_code=400, detail=tr("برای برگرداندن به «بانک کانفیگ» باید مدت اعتبار (روز) را هم مشخص کنید."))
        is_auto_provision = False
        provision_server_id = None
        auto_provision_volume_gb = None
    elif body.provision_server_id is not None or body.auto_provision_volume_gb is not None:
        # سازگاری با نسخه‌ی قبلی: ویرایش تک‌فیلدیِ سرور/حجم روی محصولی که از قبل
        # «اتصال مستقیم به پنل» بوده (بدون تغییر صریح source).
        if not old_product["is_auto_provision"]:
            raise HTTPException(status_code=400, detail=tr("این محصول به‌صورت خودکار ساخته نمی‌شود."))
        if body.provision_server_id is not None:
            if admin["tenant"]:
                raise HTTPException(status_code=403, detail=tr("اتصال مستقیم به پنل فقط برای بات اصلی مجاز است."))
            if not db.get_panel_server(body.provision_server_id):
                raise HTTPException(status_code=404, detail=tr("سرور پنل یافت نشد."))
            provision_server_id = body.provision_server_id
        if body.auto_provision_volume_gb is not None:
            if body.auto_provision_volume_gb < 0:
                raise HTTPException(status_code=400, detail=tr("حجم نامعتبر است."))
            auto_provision_volume_gb = body.auto_provision_volume_gb

    effective_server_id = (
        provision_server_id if provision_server_id is not ... else old_product["provision_server_id"]
    )

    if body.duration_days is not None:
        if body.duration_days < 0:
            raise HTTPException(status_code=400, detail=tr("مدت اعتبار نامعتبر است."))
        if body.duration_days == 0 and not effective_server_id:
            raise HTTPException(status_code=400, detail=tr("مدت نامحدود فقط برای محصولات با اتصال مستقیم به پنل ممکن است."))

    db.edit_product(
        product_id, body.name, body.price, body.description, body.duration_days,
        is_auto_provision=is_auto_provision, provision_server_id=provision_server_id,
        auto_provision_volume_gb=auto_provision_volume_gb, category_id=body.category_id,
    )
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


@app.get("/api/products/{product_id}/payment-methods")
def api_get_product_payment_methods(product_id: int, admin=Depends(require_permission("catalog"))):
    """None/[] یعنی «همه‌ی روش‌ها مجازند» (بدون محدودیت)."""
    return {"allowed": db.get_product_payment_methods(product_id)}


class ProductPaymentMethodsBody(BaseModel):
    methods: Optional[List[str]] = None


@app.post("/api/products/{product_id}/payment-methods")
def api_set_product_payment_methods(product_id: int, body: ProductPaymentMethodsBody,
                                     admin=Depends(require_permission("catalog"))):
    """محدودسازی این‌که این محصول با کدام روش‌های پرداخت (کیف پول/کارت/آبان‌گیت‌وی/
    کریپتو/درگاه سفارشی) قابل خرید باشد. methods=null یا [] یعنی حذف محدودیت
    (همه‌ی روش‌های فعال مجازند) - دقیقاً همان چیزی که بات از منوی خودش می‌سازد."""
    db.set_product_payment_methods(product_id, body.methods or None)
    db.log_admin_action(admin["id"], "product_payment_methods",
                         f"#{product_id} -> {body.methods or 'همه'} (پنل وب - {admin['username']})",
                         "product", product_id)
    return {"ok": True}


# ------------------------------------------------------------- config bank --


class ConfigsAddBody(BaseModel):
    links: str  # هر خط یک لینک


@app.get("/api/products/{product_id}/configs")
def api_product_configs(product_id: int, admin=Depends(require_permission("catalog")), _fa=Depends(require_full_access_tenant)):
    stats = db.get_config_stats(product_id)
    return {"items": rows_to_list(db.get_unused_configs(product_id)), "used_count": stats["used"]}


@app.get("/api/products/{product_id}/configs/used")
def api_product_used_configs(product_id: int, admin=Depends(require_permission("catalog")), _fa=Depends(require_full_access_tenant)):
    return {"items": rows_to_list(db.get_used_configs(product_id))}


@app.delete("/api/products/{product_id}/configs/{config_id}/used")
def api_delete_used_config(product_id: int, config_id: int, admin=Depends(require_permission("catalog")), _fa=Depends(require_full_access_tenant)):
    row = db.admin_delete_bank_config(config_id)
    if not row or row["product_id"] != product_id:
        raise HTTPException(404, tr("کانفیگ یافت نشد."))
    db.log_admin_action(
        admin["id"], "config_delete_admin",
        f"کانفیگ ناموجود #{config_id} از بانک محصول #{product_id} حذف شد (پنل وب - {admin['username']})",
        "product", product_id,
    )
    return {"ok": True}


@app.post("/api/products/{product_id}/configs")
def api_add_configs(product_id: int, body: ConfigsAddBody, admin=Depends(require_permission("catalog")), _fa=Depends(require_full_access_tenant)):
    links = [l.strip() for l in body.links.splitlines() if l.strip()]
    added, duplicates = db.add_configs(product_id, links)
    db.log_admin_action(admin["id"], "configs_add", f"{added} لینک به محصول #{product_id} (پنل وب - {admin['username']})", "product", product_id)
    return {"added": added, "duplicates": duplicates}


@app.delete("/api/configs/{config_id}")
def api_delete_config(config_id: int, admin=Depends(require_permission("catalog")), _fa=Depends(require_full_access_tenant)):
    row = db.get_config_by_id(config_id) if hasattr(db, "get_config_by_id") else None
    db.delete_config(config_id)
    if row:
        send_service_alert_sync(BOT_TOKEN, db, f"🗑 حذف کانفیگ توسط ادمین\n\n🔗 کانفیگ #{config_id}\n📦 محصول: {row['product_id']}")
    db.log_admin_action(admin["id"], "config_delete", str(config_id), "config", config_id)
    return {"ok": True}


# --------------------------------------------------------------- discounts --


class DiscountBody(BaseModel):
    code: str
    percent: Optional[int] = None
    fixed_amount: Optional[int] = None
    max_discount_amount: Optional[int] = None
    max_uses: int = 0
    expires_at: Optional[str] = None
    min_purchase: Optional[int] = None
    max_purchase: Optional[int] = None
    product_id: Optional[int] = None
    category_id: Optional[int] = None
    product_ids: Optional[List[int]] = None
    per_user_limit: Optional[int] = None
    first_purchase_only: bool = False
    audience: str = "all"


@app.get("/api/discounts")
def api_discounts(admin=Depends(require_permission("discounts"))):
    rows = rows_to_list(db.list_discount_codes())
    for r in rows:
        raw = r.get("product_ids")
        try:
            r["product_ids"] = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            r["product_ids"] = []
    return rows


@app.post("/api/discounts")
def api_add_discount(body: DiscountBody, admin=Depends(require_permission("discounts"))):
    code_id = db.create_discount_code(
        body.code, body.percent, body.fixed_amount, body.max_uses, body.expires_at,
        min_purchase=body.min_purchase, max_purchase=body.max_purchase,
        product_id=body.product_id, category_id=body.category_id,
        per_user_limit=body.per_user_limit, first_purchase_only=body.first_purchase_only,
        audience=body.audience, max_discount_amount=body.max_discount_amount,
        product_ids=body.product_ids,
    )
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
        raise HTTPException(404, tr("یافت نشد."))
    return {"ticket": dict(ticket), "messages": rows_to_list(db.get_ticket_messages(ticket_id))}


class TicketReplyBody(BaseModel):
    message: str


@app.post("/api/tickets/{ticket_id}/reply")
async def api_ticket_reply(ticket_id: int, body: TicketReplyBody, admin=Depends(require_permission("tickets"))):
    ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
    if not ticket:
        raise HTTPException(404, tr("یافت نشد."))
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
        raise HTTPException(400, tr("متن پیام نمی‌تواند خالی باشد."))
    if len(text) > 4000:
        raise HTTPException(400, tr("متن پیام بیش از حد طولانی است."))

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
        raise HTTPException(404, tr("کاربر یافت نشد."))
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
        raise HTTPException(404, tr("کاربر یافت نشد."))
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(400, tr("پیام نمی‌تواند خالی باشد."))
    if len(text) > 2000:
        raise HTTPException(400, tr("پیام بیش از حد طولانی است."))

    # قفل مکالمه: چون ادمین‌های وب آیدی تلگرام ندارند، با -admin_id در همان
    # ستون assigned_admin_id ذخیره می‌شود (که با آیدی‌های واقعی تلگرام تداخل ندارد).
    my_lock_id = -admin["id"]
    is_owner = admin["role"] == "owner"
    conv = (await asyncio.to_thread(db.get_support_conversation, user_id))
    assigned = conv["assigned_admin_id"] if conv else None
    if assigned and assigned != my_lock_id and not is_owner:
        raise HTTPException(
            403,
            tr(f"این گفتگو در حال حاضر توسط {_support_lock_label(assigned)} در حال پاسخ‌دهی است."),
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
    reseller_bot = (await asyncio.to_thread(main_db.get_reseller_bot, bot_id))
    if not reseller_bot or not reseller_bot["web_panel_setup_token"]:
        return False
    panel_url = _resolved_admin_panel_url(request)
    b_value = reseller_bot["link_slug"] or str(bot_id)
    link = f"{panel_url}/setup?b={b_value}&t={reseller_bot['web_panel_setup_token']}"
    text = (
        "🌐 لینک راه‌اندازی پنل وب نمایندگی شما:\n\n"
        f"{link}\n\n"
        "این لینک یک‌بارمصرف است؛ با باز کردنش یک یوزرنیم/پسورد دلخواه برای پنل وب "
        "خودت تنظیم می‌کنی."
    )
    # نماینده‌ی بدون بات توکن واقعی تلگرام ندارد و با no-bot:* ذخیره می‌شود؛
    # لینک چنین نماینده‌ای باید با بات اصلی ارسال شود.
    send_token = reseller_bot["bot_token"]
    if str(send_token or "").startswith("no-bot:"):
        send_token = BOT_TOKEN
    return await tg_send(send_token, reseller_bot["owner_telegram_id"], text)


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
    return [{"id": s["id"], "name": s["name"]} for s in db.get_panel_servers(active_only=True) if s["used_for_reseller"]]


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
        raise HTTPException(404, tr("یافت نشد."))
    db.toggle_reseller_bot(bot_id)
    db.log_admin_action(
        admin["id"], "reseller_bot_toggle", f"نماینده #{bot_id} (پنل وب - {admin['username']})", "reseller_bot", bot_id
    )
    return {"ok": True}


class ResellerBotEditBody(BaseModel):
    owner_name: Optional[str] = None
    owner_telegram_id: Optional[int] = None


@app.put("/api/reseller-bots/{bot_id}")
def api_edit_reseller_bot(bot_id: int, body: ResellerBotEditBody, admin=Depends(require_permission("resellers"))):
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, tr("یافت نشد."))
    # رفع باگ: قبلاً اینجا فقط edit_reseller_bot صدا زده می‌شد که صرفاً ستون‌های
    # reseller_bots را عوض می‌کرد - یعنی تغییر owner_telegram_id از این مسیر کاملاً
    # ظاهری بود (مالکیت واقعی/اعتبار حجمی همچنان مال مالک قبلی می‌ماند؛ جزئیات در
    # database.transfer_reseller_ownership). حالا وقتی owner_telegram_id واقعاً عوض
    # شده باشد، از تابعی استفاده می‌شود که مالکیت را کامل (فلگ‌های نمایندگی در
    # دیتابیس اصلی + role='owner' در دیتابیس محلی بات) منتقل می‌کند.
    if body.owner_telegram_id is not None and body.owner_telegram_id != reseller_bot["owner_telegram_id"]:
        db.transfer_reseller_ownership(bot_id, body.owner_telegram_id, new_owner_name=body.owner_name)
    elif body.owner_name is not None:
        db.edit_reseller_bot(bot_id, owner_name=body.owner_name)
    db.log_admin_action(
        admin["id"], "reseller_bot_edit", f"نماینده #{bot_id} (پنل وب - {admin['username']})", "reseller_bot", bot_id
    )
    return {"ok": True}


@app.delete("/api/reseller-bots/{bot_id}")
def api_delete_reseller_bot(bot_id: int, purge_db: bool = False, admin=Depends(require_permission("resellers"))):
    reseller_bot = db.get_reseller_bot(bot_id)
    if not reseller_bot:
        raise HTTPException(404, tr("یافت نشد."))
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


@app.get("/api/resellers/inline-commissions")
def api_list_inline_resellers(admin=Depends(require_permission("resellers"))):
    """دید ادمین به نماینده‌های «لینک اختصاصی داخل بات اصلی» و کارمزدشان
    (بند ۴ از موارد باقی‌مانده - چون خودِ نماینده فقط /reseller_link دارد و
    پنل مدیریتی جدا برایش ساخته نشده)."""
    rows = rows_to_list(db.list_inline_resellers())
    return {"items": rows}


class CommissionResellerDirectBody(BaseModel):
    owner_telegram_id: int
    percent: int


class CommissionResellerPercentBody(BaseModel):
    percent: int


class CommissionResellerRejectBody(BaseModel):
    reason: str


@app.post("/api/resellers/inline-commissions")
def api_create_inline_reseller(body: CommissionResellerDirectBody, admin=Depends(require_permission("resellers"))):
    """ساخت مستقیم یک نماینده‌ی کمیسیونی توسط ادمین (بدون نیاز به درخواست
    قبلی از سمت کاربر) - نمایندگی کمیسیونی نه حجم دارد نه محصول آماده،
    فقط یک درصد کمیسیون دائمی تا زمان غیرفعال‌سازی."""
    if not (1 <= body.percent <= 100):
        raise HTTPException(400, tr("درصد باید بین ۱ تا ۱۰۰ باشد."))
    user_row = db.get_user(body.owner_telegram_id)
    if not user_row:
        raise HTTPException(404, tr("این کاربر هنوز با بات /start نزده است."))
    if db.is_inline_reseller(body.owner_telegram_id):
        raise HTTPException(400, tr("این کاربر همین الان هم نماینده‌ی کمیسیونی فعال است."))
    db.enable_inline_reseller(body.owner_telegram_id, body.percent)
    db.log_admin_action(
        admin["id"], "commission_reseller_direct_create",
        f"کاربر {body.owner_telegram_id} | {body.percent}٪ (پنل وب - {admin['username']})",
    )
    asyncio.create_task(tg_send(
        _bot_token(), body.owner_telegram_id,
        "🎉 شما توسط ادمین به‌عنوان نماینده‌ی کمیسیونی تعیین شدید!\n\n"
        f"روی هر خرید مشتریانی که با لینک اختصاصی‌تان وارد شوند، {body.percent}٪ کارمزد به کیف پول شما اضافه "
        "می‌شود - تا وقتی ادمین نمایندگی‌تان را غیرفعال کند.\n"
        "برای دیدن لینک و آمار، دستور /reseller_link را در بات بفرستید.",
    ))
    return {"ok": True}


@app.put("/api/resellers/inline-commissions/{telegram_id}")
def api_edit_inline_reseller_percent(telegram_id: int, body: CommissionResellerPercentBody, admin=Depends(require_permission("resellers"))):
    if not (1 <= body.percent <= 100):
        raise HTTPException(400, tr("درصد باید بین ۱ تا ۱۰۰ باشد."))
    if not db.is_inline_reseller(telegram_id):
        raise HTTPException(404, tr("این کاربر نماینده‌ی کمیسیونی فعال نیست."))
    db.set_inline_reseller_commission_percent(telegram_id, body.percent)
    db.log_admin_action(
        admin["id"], "commission_reseller_edit_percent",
        f"کاربر {telegram_id} → {body.percent}٪ (پنل وب - {admin['username']})",
    )
    asyncio.create_task(tg_send(_bot_token(), telegram_id, f"📊 درصد کمیسیون نمایندگی شما به {body.percent}٪ تغییر کرد."))
    return {"ok": True}


@app.delete("/api/resellers/inline-commissions/{telegram_id}")
def api_disable_inline_reseller(telegram_id: int, admin=Depends(require_permission("resellers"))):
    if not db.is_inline_reseller(telegram_id):
        raise HTTPException(404, tr("این کاربر نماینده‌ی کمیسیونی فعال نیست."))
    db.disable_inline_reseller(telegram_id)
    db.log_admin_action(
        admin["id"], "commission_reseller_disable", f"کاربر {telegram_id} (پنل وب - {admin['username']})",
    )
    asyncio.create_task(tg_send(_bot_token(), telegram_id, "⛔️ نمایندگی کمیسیونی شما توسط ادمین غیرفعال شد."))
    return {"ok": True}


@app.get("/api/resellers/commission-requests")
def api_list_commission_reseller_requests(status: str = "pending", admin=Depends(require_permission("resellers"))):
    rows = rows_to_list(db.list_commission_reseller_requests(status or None))
    for r in rows:
        u = db.get_user(r["user_id"])
        r["username"] = u["username"] if u else None
        r["first_name"] = u["first_name"] if u else None
    return {"items": rows}


@app.post("/api/resellers/commission-requests/{request_id}/approve")
def api_approve_commission_reseller_request(request_id: int, admin=Depends(require_permission("resellers"))):
    req = db.get_commission_reseller_request(request_id)
    if not req or req["status"] != "pending":
        raise HTTPException(404, tr("این درخواست دیگر معتبر نیست."))
    approved = db.approve_commission_reseller_request(request_id, req["proposed_percent"], admin["id"])
    if not approved:
        raise HTTPException(409, tr("این درخواست همین الان بررسی شد."))
    db.log_admin_action(
        admin["id"], "commission_reseller_approve",
        f"درخواست #{request_id} | کاربر {req['user_id']} | {req['proposed_percent']}٪ (پنل وب - {admin['username']})",
    )
    asyncio.create_task(tg_send(
        _bot_token(), req["user_id"],
        "✅ درخواست نمایندگی کمیسیونی شما تایید شد!\n\n"
        f"روی هر خرید مشتریانی که با لینک اختصاصی‌تان وارد شوند، {req['proposed_percent']}٪ کارمزد به کیف پول شما "
        "اضافه می‌شود - تا وقتی ادمین نمایندگی‌تان را غیرفعال کند.\n"
        "برای دیدن لینک و آمار، دستور /reseller_link را در بات بفرستید.",
    ))
    return {"ok": True}


@app.post("/api/resellers/commission-requests/{request_id}/reject")
def api_reject_commission_reseller_request(request_id: int, body: CommissionResellerRejectBody, admin=Depends(require_permission("resellers"))):
    req = db.get_commission_reseller_request(request_id)
    if not req or req["status"] != "pending":
        raise HTTPException(404, tr("این درخواست دیگر معتبر نیست."))
    rejected = db.reject_commission_reseller_request(request_id, body.reason, admin["id"])
    if not rejected:
        raise HTTPException(409, tr("این درخواست همین الان بررسی شد."))
    db.log_admin_action(
        admin["id"], "commission_reseller_reject",
        f"درخواست #{request_id} | کاربر {req['user_id']} | دلیل: {body.reason} (پنل وب - {admin['username']})",
    )
    asyncio.create_task(tg_send(
        _bot_token(), req["user_id"],
        f"❌ متاسفانه درخواست نمایندگی کمیسیونی شما (#{request_id}) رد شد.\n\nدلیل: {body.reason}",
    ))
    return {"ok": True}


_RESELLER_AXIS_SETTING_KEYS = (
    "reseller_axis_bot_dedicated_enabled", "reseller_axis_bot_inline_link_enabled",
    "reseller_axis_bot_none_enabled", "reseller_axis_webpanel_enabled", "reseller_axis_miniapp_enabled",
    "reseller_axis_supply_volume_enabled", "reseller_axis_supply_fixed_product_enabled",
)


@app.get("/api/resellers/axis-settings")
async def api_get_reseller_axis_settings(admin=Depends(require_permission("resellers"))):
    """وضعیت روشن/خاموش سراسری ۴ محور فرم درخواست نمایندگی + لیست محصولات
    مجاز برای مدل تامین «محصول آماده» (بند ۶ اسپک)."""
    settings = {k: (await asyncio.to_thread(db.get_setting, k, "1")) == "1" for k in _RESELLER_AXIS_SETTING_KEYS}
    raw_ids = (await asyncio.to_thread(db.get_setting, "reseller_fixed_product_ids", "")) or ""
    allowed_ids = {int(x) for x in raw_ids.split(",") if x.strip().isdigit()}
    products = (await asyncio.to_thread(db.get_all_products))
    return {
        "ok": True,
        "axes": settings,
        "products": [
            {"id": p["id"], "name": p["name"], "category_name": p["category_name"],
             "is_active": bool(p["is_active"]), "allowed_for_fixed_product": p["id"] in allowed_ids}
            for p in products
        ],
    }


class ResellerAxisSettingsBody(BaseModel):
    axes: dict = {}
    fixed_product_ids: Optional[list] = None


@app.post("/api/resellers/axis-settings")
async def api_set_reseller_axis_settings(body: ResellerAxisSettingsBody, admin=Depends(require_permission("resellers"))):
    for key, value in (body.axes or {}).items():
        if key not in _RESELLER_AXIS_SETTING_KEYS:
            continue
        (await asyncio.to_thread(db.set_setting, key, "1" if value else "0"))
    if body.fixed_product_ids is not None:
        clean_ids = ",".join(str(int(x)) for x in body.fixed_product_ids)
        (await asyncio.to_thread(db.set_setting, "reseller_fixed_product_ids", clean_ids))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_axis_settings_update", f"تنظیمات محورهای نمایندگی (پنل وب - {admin['username']})",
    ))
    return {"ok": True}


@app.post("/api/reseller-bots/{bot_id}/web-panel/enable")
async def api_enable_reseller_webpanel(bot_id: int, request: Request, admin=Depends(require_permission("resellers"))):
    reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
    if not reseller_bot:
        raise HTTPException(404, tr("یافت نشد."))
    if reseller_bot["web_panel_enabled"]:
        raise HTTPException(400, tr("قبلاً فعال است؛ برای لینک جدید از «ساخت لینک جدید» استفاده کنید."))
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
        raise HTTPException(404, tr("یافت نشد."))
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
        raise HTTPException(404, tr("یافت نشد."))
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
        raise HTTPException(404, tr("یافت نشد."))
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


TIER_MODEL_LABELS = {
    "commission": "کمیسیون",
    "discount": "تخفیف دائمی و خرید عمده",
    "fixed_product": "خرید عمده محصول",
    "volume_credit": "خرید عمده حجم",
}
TIER_FLAG_KEYS = ("is_enabled", "has_miniapp", "has_web_panel", "has_dedicated_bot", "auto_approve")


class TierBody(BaseModel):
    title: Optional[str] = None
    icon: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    sort_order: Optional[int] = None
    commission_min: Optional[int] = None
    commission_max: Optional[int] = None
    permanent_discount_percent: Optional[int] = None
    min_qty: Optional[int] = None
    min_volume_gb: Optional[int] = None
    has_miniapp: Optional[bool] = None
    has_web_panel: Optional[bool] = None
    has_dedicated_bot: Optional[bool] = None
    auto_approve: Optional[bool] = None
    credit_limit_toman: Optional[int] = None


class TierQtyDiscountBody(BaseModel):
    min_qty: int
    discount_percent: int


def _tier_view(row):
    d = row_to_dict(row)
    d["id"] = d["code"]
    d["model_label"] = TIER_MODEL_LABELS.get(d["model"], d["model"])
    for key in TIER_FLAG_KEYS:
        d[key] = bool(d[key])
    return d


def _tier_or_404(code: str):
    row = db.get_reseller_tier(code)
    if not row:
        raise HTTPException(status_code=404, detail=tr("سطح پیدا نشد."))
    return row


@app.get("/api/reseller-tiers")
def api_reseller_tiers(admin=Depends(require_permission("resellers"))):
    out = []
    for row in db.list_reseller_tiers():
        d = _tier_view(row)
        d["qty_discounts"] = rows_to_list(db.list_tier_qty_discounts(row["code"]))
        d["members_count"] = len(db.list_tier_members(row["code"]))
        out.append(d)
    return out


@app.put("/api/reseller-tiers/{code}")
def api_update_reseller_tier(code: str, body: TierBody, admin=Depends(require_permission("resellers"))):
    _tier_or_404(code)
    nullable = set(Database.RESELLER_TIER_NULLABLE_FIELDS)
    fields = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None or k in nullable}
    if "title" in fields and not str(fields["title"]).strip():
        raise HTTPException(status_code=400, detail=tr("عنوان سطح نمی‌تواند خالی باشد."))
    if "credit_limit_toman" in fields and not 0 <= int(fields["credit_limit_toman"]) <= MAX_CREDIT_LIMIT_TOMAN:
        raise HTTPException(status_code=400, detail=tr("سقف اعتبار باید بین ۰ تا ۱۰ میلیارد تومان باشد."))
    try:
        db.update_reseller_tier(code, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.log_admin_action(admin["id"], "reseller_tier_update", code, "reseller_tier", None)
    return {"ok": True}


@app.post("/api/reseller-tiers/{code}/toggle")
def api_toggle_reseller_tier(code: str, admin=Depends(require_permission("resellers"))):
    row = _tier_or_404(code)
    db.update_reseller_tier(code, is_enabled=0 if row["is_enabled"] else 1)
    db.log_admin_action(admin["id"], "reseller_tier_toggle", code, "reseller_tier", None)
    return {"ok": True}


@app.get("/api/reseller-tiers/{code}/qty-discounts")
def api_tier_qty_discounts(code: str, admin=Depends(require_permission("resellers"))):
    _tier_or_404(code)
    return rows_to_list(db.list_tier_qty_discounts(code))


@app.post("/api/reseller-tiers/{code}/qty-discounts")
def api_add_tier_qty_discount(code: str, body: TierQtyDiscountBody, admin=Depends(require_permission("resellers"))):
    _tier_or_404(code)
    try:
        discount_id = db.set_tier_qty_discount(code, body.min_qty, body.discount_percent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.log_admin_action(admin["id"], "reseller_tier_qty_discount", f"{code}: {body.min_qty}+ = {body.discount_percent}%", "reseller_tier", None)
    return {"id": discount_id}


@app.delete("/api/reseller-tiers/qty-discounts/{discount_id}")
def api_delete_tier_qty_discount(discount_id: int, admin=Depends(require_permission("resellers"))):
    if not db.delete_tier_qty_discount(discount_id):
        raise HTTPException(status_code=404, detail=tr("ردیف پیدا نشد."))
    db.log_admin_action(admin["id"], "reseller_tier_qty_discount_delete", str(discount_id), "reseller_tier", None)
    return {"ok": True}


@app.get("/api/reseller-tiers/{code}/members")
def api_tier_members(code: str, admin=Depends(require_permission("resellers"))):
    _tier_or_404(code)
    return rows_to_list(db.list_tier_members(code))


class TierMemberBody(BaseModel):
    telegram_id: int
    discount_percent: Optional[int] = None


@app.post("/api/reseller-tiers/{code}/members")
async def api_add_tier_member(code: str, body: TierMemberBody, admin=Depends(require_permission("resellers"))):
    tier = _tier_or_404(code)
    if tier["model"] != "discount":
        raise HTTPException(status_code=400, detail=tr("افزودن مستقیم عضو فقط برای سطح‌های تخفیفی ممکن است."))
    tg_id = body.telegram_id
    if not (await asyncio.to_thread(db.get_user, tg_id)):
        raise HTTPException(status_code=404, detail=tr("کاربر یافت نشد."))
    current = await asyncio.to_thread(db.get_agent_tier, tg_id)
    if current == code:
        raise HTTPException(status_code=400, detail=tr("این کاربر همین الان عضو این سطح است."))
    if current:
        raise HTTPException(status_code=400, detail=tr("این کاربر همین الان نماینده‌ی سطح دیگری است."))
    discount_percent = body.discount_percent
    if code == "silver":
        if discount_percent is None:
            raise HTTPException(status_code=400, detail=tr("برای نمایندگی نقره‌ای درصد تخفیف را مشخص کنید."))
        if not 1 <= int(discount_percent) <= 100:
            raise HTTPException(status_code=400, detail=tr("درصد تخفیف باید بین ۱ تا ۱۰۰ باشد."))
    elif discount_percent is not None:
        raise HTTPException(status_code=400, detail=tr("درصد تخفیف فقط برای سطح نقره‌ای قابل تنظیم است."))
    await asyncio.to_thread(db.set_user_reseller_tier, tg_id, code, discount_percent)
    await asyncio.to_thread(db.log_admin_action, admin["id"], "reseller_tier_member_add", f"{code}: {tg_id}", "user", tg_id)
    await notify_user(
        tg_id,
        f"✅ شما توسط مدیریت در سطح {tier['icon']} {tier['title']} قرار گرفتید. "
        "تخفیف‌ها هنگام «خرید کانفیگ» خودکار اعمال می‌شود.",
    )
    return {"ok": True}


@app.delete("/api/reseller-tiers/{code}/members/{user_id}")
def api_remove_tier_member(code: str, user_id: int, admin=Depends(require_permission("resellers"))):
    _tier_or_404(code)
    if db.get_user_reseller_tier(user_id) != code:
        raise HTTPException(status_code=404, detail=tr("این کاربر عضو این سطح نیست."))
    db.set_user_reseller_tier(user_id, None)
    db.log_admin_action(admin["id"], "reseller_tier_member_remove", f"{code}: {user_id}", "user", user_id)
    return {"ok": True}


@app.get("/api/reseller-tier-requests")
def api_tier_requests(status: Optional[str] = "pending", admin=Depends(require_permission("resellers"))):
    out = []
    for req in rows_to_list(db.list_tier_requests(status or None)):
        user = row_to_dict(db.get_user(req["user_id"])) or {}
        tier = db.get_reseller_tier(req["tier_code"])
        req["tier_title"] = tier["title"] if tier else req["tier_code"]
        req["username"] = user.get("username")
        req["first_name"] = user.get("first_name")
        out.append(req)
    return out


async def _decide_tier_request_web(request_id: int, admin, approve: bool):
    req = db.get_tier_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=tr("درخواست پیدا نشد."))
    done = db.approve_tier_request(request_id, 0) if approve else db.reject_tier_request(request_id, 0)
    if not done:
        raise HTTPException(status_code=409, detail=tr("این درخواست دیگر در انتظار بررسی نیست."))
    tier = db.get_reseller_tier(req["tier_code"])
    label = f"{tier['icon']} {tier['title']}" if tier else req["tier_code"]
    db.log_admin_action(
        admin["id"], "tier_request_approve" if approve else "tier_request_reject",
        f"درخواست #{request_id} | کاربر {req['user_id']} | سطح {req['tier_code']}", "user", req["user_id"],
    )
    text = (
        f"✅ درخواست شما برای سطح {label} تایید شد. تخفیف‌ها هنگام «خرید کانفیگ» خودکار اعمال می‌شود."
        if approve else f"❌ متاسفانه درخواست شما برای سطح {label} رد شد."
    )
    await tg_send(_bot_token(), req["user_id"], text)
    return {"ok": True}


@app.post("/api/reseller-tier-requests/{request_id}/approve")
async def api_approve_tier_request(request_id: int, admin=Depends(require_permission("resellers"))):
    return await _decide_tier_request_web(request_id, admin, True)


@app.post("/api/reseller-tier-requests/{request_id}/reject")
async def api_reject_tier_request(request_id: int, admin=Depends(require_permission("resellers"))):
    return await _decide_tier_request_web(request_id, admin, False)


class ResellerCreditBody(BaseModel):
    delta_gb: int
    reason: Optional[str] = None


@app.post("/api/resellers/{tg_id}/credit")
async def api_adjust_reseller_credit(tg_id: int, body: ResellerCreditBody, admin=Depends(require_permission("resellers"))):
    if body.delta_gb == 0:
        raise HTTPException(400, tr("مقدار اعتبار نمی‌تواند صفر باشد."))
    if not db.is_reseller(tg_id):
        raise HTTPException(400, tr("این کاربر نماینده فعال نیست."))
    try:
        await asyncio.to_thread(
            db.adjust_reseller_credit, tg_id, body.delta_gb,
            admin_id=admin["id"], reason=body.reason or "تنظیم از پنل وب",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
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


class ResellerManageBody(BaseModel):
    owner_name: Optional[str] = None
    enabled: Optional[bool] = None
    supply_model: Optional[str] = None
    supply_product_id: Optional[int] = None
    supply_products: Optional[list] = None
    panel_server_id: Optional[int] = None


@app.get("/api/resellers/{tg_id}/manage")
def api_reseller_manage(tg_id: int, admin=Depends(require_permission("resellers"))):
    user = row_to_dict(db.get_user(tg_id))
    if not user:
        raise HTTPException(404, tr("کاربر یافت نشد."))
    supply = db.get_reseller_supply(tg_id)
    inventory = rows_to_list(db.get_reseller_product_inventory(tg_id))
    bot_rows = [dict(x) for x in db.list_reseller_bots() if x["owner_telegram_id"] == tg_id]
    for b in bot_rows:
        b.pop("bot_token", None); b.pop("web_panel_setup_token", None)
    return {"user": user, "supply": supply, "inventory": inventory, "bots": bot_rows}


@app.patch("/api/resellers/{tg_id}")
def api_edit_reseller(tg_id: int, body: ResellerManageBody, admin=Depends(require_permission("resellers"))):
    user = db.get_user(tg_id)
    if not user:
        raise HTTPException(404, tr("کاربر یافت نشد."))
    if body.supply_model is not None and body.supply_model not in ("volume_credit", "fixed_product"):
        raise HTTPException(400, tr("مدل تامین نامعتبر است."))
    if body.supply_model == "fixed_product":
        items = body.supply_products or []
        if not items and body.supply_product_id:
            items = [{"product_id": body.supply_product_id, "qty": 1}]
        normalized = []; seen = set()
        for item in items:
            try: pid, qty = int(item.get("product_id")), int(item.get("qty"))
            except Exception: raise HTTPException(400, tr("فهرست محصولات نامعتبر است."))
            if pid in seen or qty < 0: raise HTTPException(400, tr("محصول تکراری یا تعداد نامعتبر است."))
            product = db.get_product(pid)
            if not product or not product["is_active"] or not product["is_auto_provision"]:
                raise HTTPException(400, tr(f"محصول #{pid} فعال یا خودکار-ساز نیست."))
            seen.add(pid); normalized.append((pid, qty))
        if not normalized: raise HTTPException(400, tr("حداقل یک محصول را انتخاب کنید."))
    panel_was_sent = "panel_server_id" in getattr(body, "model_fields_set", set())
    if panel_was_sent and body.panel_server_id is not None:
        panel = db.get_panel_server(body.panel_server_id)
        if not panel or not panel["is_active"] or not panel["used_for_reseller"]:
            raise HTTPException(400, tr("پنل انتخاب‌شده فعال نیست یا برای نمایندگی مجاز نشده است."))
    if body.owner_name is not None:
        db.update_user_profile(tg_id, first_name=body.owner_name)
    if body.enabled is not None:
        db.set_reseller_status(tg_id, body.enabled)
    if body.supply_model is not None:
        normalized = normalized if body.supply_model == "fixed_product" else []
        db.set_reseller_supply_model(tg_id, body.supply_model, normalized[0][0] if normalized else None)
        if body.supply_model == "fixed_product" and "supply_products" in getattr(body, "model_fields_set", set()):
            # تنظیم مستقیم موجودی چندمحصولی؛ هر محصول مقدار دقیقاً انتخاب‌شده را می‌گیرد.
            existing = {int(x["product_id"]): int(x["qty_remaining"] or 0) for x in db.get_reseller_product_inventory(tg_id)}
            wanted = {pid: qty for pid, qty in normalized}
            for pid in set(existing) | set(wanted):
                target = wanted.get(pid, 0)
                current = existing.get(pid, 0)
                if target != current:
                    db.adjust_reseller_product_credit(tg_id, pid, target - current, admin_id=admin["id"], reason="تنظیم چندمحصولی نمایندگی از پنل مدیریت")
    if panel_was_sent:
        db.set_reseller_panel(tg_id, body.panel_server_id)
    elif body.supply_model is not None:
        # تغییر مدل تامین بدون ارسال پنل، پنل فعلی را دست‌نخورده نگه می‌دارد.
        pass
    db.log_admin_action(admin["id"], "reseller_level2_edit", f"ویرایش نماینده {tg_id} (پنل وب - {admin['username']})", "reseller", tg_id)
    return {"ok": True}


class ResellerProductInventoryBody(BaseModel):
    delta: int
    reason: Optional[str] = None


@app.post("/api/resellers/{tg_id}/products/{product_id}/inventory")
def api_adjust_reseller_product_inventory(tg_id: int, product_id: int, body: ResellerProductInventoryBody, admin=Depends(require_permission("resellers"))):
    if not db.is_reseller(tg_id):
        raise HTTPException(400, tr("این کاربر نماینده فعال نیست."))
    product = db.get_product(product_id)
    if not product or not product["is_active"] or not product["is_auto_provision"]:
        raise HTTPException(400, tr("محصول معتبر یا خودکار-ساز نیست."))
    try:
        qty = db.adjust_reseller_product_credit(tg_id, product_id, body.delta, admin_id=admin["id"], reason=body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log_admin_action(admin["id"], "reseller_product_inventory", f"نماینده {tg_id} | محصول {product_id} | {body.delta:+d}", "reseller", tg_id)
    return {"ok": True, "qty_remaining": qty}


@app.delete("/api/resellers/{tg_id}")
def api_delete_reseller(tg_id: int, admin=Depends(require_permission("resellers"))):
    if not db.get_user(tg_id):
        raise HTTPException(404, tr("کاربر یافت نشد."))
    # حذف کامل باید دقیقاً از همان موتور مرکزی حذف نمایندگی استفاده کند تا
    # فایل DB اختصاصی، اعتبار، پنل، بات و لینک/کمیسیون همگی پاک شوند.
    db.wipe_agent_state(tg_id)
    db.log_admin_action(admin["id"], "reseller_level2_delete", f"حذف نماینده {tg_id} (پنل وب - {admin['username']})", "reseller", tg_id)
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


# ------------------------------------------------------ reseller payment config --

@app.get("/api/reseller-tiers/{code}/payment-methods")
def api_reseller_payment_methods(code: str, admin=Depends(require_permission("resellers"))):
    tier = db.get_reseller_tier(code)
    if not tier:
        raise HTTPException(404, tr("سطح نمایندگی پیدا نشد."))
    allowed = db.get_reseller_payment_methods(code)
    catalog = [x for x in db.get_payment_methods_catalog() if x["key"] != "wallet"]
    keys = {x["key"] for x in catalog}
    selected = [k for k in (allowed if allowed is not None else keys) if k in keys]
    return {"methods": catalog, "selected": selected, "all_enabled_by_default": allowed is None}

class ResellerPaymentMethodsBody(BaseModel):
    methods: List[str]

@app.put("/api/reseller-tiers/{code}/payment-methods")
def api_set_reseller_payment_methods(code: str, body: ResellerPaymentMethodsBody, admin=Depends(require_permission("resellers"))):
    tier = db.get_reseller_tier(code)
    if not tier:
        raise HTTPException(404, tr("سطح نمایندگی پیدا نشد."))
    catalog = [x for x in db.get_payment_methods_catalog() if x["key"] != "wallet"]
    valid = {x["key"] for x in catalog}
    methods = [m for m in body.methods if m in valid]
    if not methods:
        raise HTTPException(400, tr("حداقل یک روش پرداخت انتخاب کنید."))
    db.set_reseller_payment_methods(code, methods)
    db.log_admin_action(admin["id"], "reseller_payment_methods_update", f"سطح {code}: {', '.join(methods)}")
    return {"ok": True, "selected": methods}

# ------------------------------------------------------------ reseller requests --


@app.get("/api/reseller-requests")
def api_reseller_requests(status: Optional[str] = None, admin=Depends(require_permission("resellers"))):
    rows = db.list_reseller_requests(status)
    out = []
    for r in rows:
        r = dict(r)
        user = row_to_dict(db.get_user(r["user_id"]))
        r["username"] = user["username"] if user else None
        r["first_name"] = user["first_name"] if user else None
        tier = db.get_reseller_tier(r.get("tier_code")) if r.get("tier_code") else None
        r["tier_title"] = f"{tier['icon']} {tier['title']}" if tier else r.get("tier_code")
        out.append(r)
    return out


@app.get("/api/reseller-requests/{request_id}/receipt")
async def api_reseller_request_receipt(request_id: int, admin=Depends(require_permission("resellers"))):
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or not req["receipt_file_id"]:
        raise HTTPException(404, tr("رسیدی برای این درخواست ثبت نشده است."))
    result = await fetch_telegram_file(_bot_token(), req["receipt_file_id"])
    if not result:
        raise HTTPException(502, tr("دریافت رسید از تلگرام ناموفق بود."))
    content, content_type = result
    return Response(content=content, media_type=content_type)


@app.get("/api/reseller-requests/{request_id}/receipt-base64")
async def api_reseller_request_receipt_base64(request_id: int, admin=Depends(require_permission("resellers"))):
    """نسخه‌ی JSON/base64 رسید، مخصوص اپ موبایل (مشابه /api/orders/{id}/receipt-base64)."""
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or not req["receipt_file_id"]:
        raise HTTPException(404, tr("رسیدی برای این درخواست ثبت نشده است."))
    result = await fetch_telegram_file(_bot_token(), req["receipt_file_id"])
    if not result:
        raise HTTPException(502, tr("دریافت رسید از تلگرام ناموفق بود."))
    content, content_type = result
    return {"content_type": content_type, "data_base64": base64.b64encode(content).decode("ascii")}


class ResellerRequestQuoteBody(BaseModel):
    price_toman: int
    panel_server_id: Optional[int] = None
    commission_percent: Optional[int] = None
    discount_percent: Optional[int] = None
    payment_methods: Optional[List[str]] = None


@app.post("/api/reseller-requests/{request_id}/quote")
async def api_quote_reseller_request(request_id: int, body: ResellerRequestQuoteBody, admin=Depends(require_permission("resellers"))):
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or req["status"] != "pending_review":
        raise HTTPException(400, tr("این درخواست دیگر معتبر نیست."))
    if body.price_toman <= 0:
        raise HTTPException(400, tr("هزینه باید عددی مثبت باشد."))
    tier = (await asyncio.to_thread(db.get_reseller_tier, req["tier_code"])) if req["tier_code"] else None
    if tier and tier["model"] == "commission":
        low = int(tier["commission_min"] or 1)
        high = int(tier["commission_max"] or 100)
        if body.commission_percent is None:
            raise HTTPException(400, tr("برای نمایندگی برنزی درصد کمیسیون را مشخص کنید."))
        if not (low <= body.commission_percent <= high):
            raise HTTPException(400, tr(f"درصد کمیسیون باید بین {low} تا {high} باشد."))
    if tier and tier["model"] == "discount":
        if body.discount_percent is None:
            raise HTTPException(400, tr("برای نمایندگی نقره‌ای درصد تخفیف را مشخص کنید."))
        if not (1 <= body.discount_percent <= 100):
            raise HTTPException(400, tr("درصد تخفیف باید بین ۱ تا ۱۰۰ باشد."))
    payment_methods = None
    if body.payment_methods is not None:
        valid = {x["key"] for x in (await asyncio.to_thread(db.get_payment_methods_catalog)) if x["key"] != "wallet"}
        payment_methods = [m for m in body.payment_methods if m in valid]
        if not payment_methods:
            raise HTTPException(400, tr("حداقل یک روش پرداخت انتخاب کنید."))
    try:
        await asyncio.to_thread(db.quote_reseller_request, request_id, body.price_toman, body.panel_server_id, admin["id"], body.commission_percent, body.discount_percent, payment_methods)
    except ValueError as e:
        raise HTTPException(400, str(e))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_request_quote",
        f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {body.price_toman:,} (پنل وب - {admin['username']})",
    ))
    tier_title = f"{tier['icon']} {tier['title']}" if tier else "نمایندگی"
    commission_note = f"\n📈 کمیسیون: {body.commission_percent}٪" if body.commission_percent is not None else ""
    discount_note = f"\n🏷 تخفیف نماینده: {body.discount_percent}٪" if body.discount_percent is not None else ""
    await tg_send(
        _bot_token(), req["user_id"],
        f"🏪 درخواست نمایندگی #{request_id} شما تایید شد!\n\n"
        f"🏅 سطح: {tier_title}\n"
        f"💰 هزینه‌ی نمایندگی: {body.price_toman:,} تومان{commission_note}{discount_note}\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup={"inline_keyboard": [[{"text": "💳 انتخاب روش پرداخت", "callback_data": f"resreq_pay:{request_id}"}]]},
    )
    return {"ok": True}


@app.post("/api/reseller-requests/{request_id}/approve-payment")
async def api_approve_reseller_request_payment(request_id: int, request: Request, admin=Depends(require_permission("resellers"))):
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or req["status"] != "awaiting_payment_review":
        raise HTTPException(400, tr("این درخواست دیگر معتبر نیست."))
    # رفع باگ ریس‌کاندیشن: approve_reseller_request_payment حالا اتمیک است؛ اگر
    # هم‌زمان از یک سطح دیگر (بات/مینی‌اپ) همین درخواست تایید شده باشد، False
    # برمی‌گردد و اینجا متوقف می‌شویم تا اعتبار/بات نماینده دوبار ساخته نشود.
    if not (await asyncio.to_thread(db.approve_reseller_request_payment, request_id, admin["id"])):
        raise HTTPException(400, tr("این درخواست همین الان از جای دیگری تایید شد."))
    (await asyncio.to_thread(db.log_admin_action, 
        admin["id"], "reseller_request_payment_approve",
        f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {(req['price_toman'] or 0):,} (پنل وب - {admin['username']})",
    ))

    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if req and req["status"] == "completed":
        tier = await asyncio.to_thread(db.get_reseller_tier, req["tier_code"]) if req["tier_code"] else None
        label = f"{tier['icon']} {tier['title']}" if tier else "نمایندگی"
        await tg_send(_bot_token(), req["user_id"], f"✅ پرداخت هزینه {label} تایید شد و نمایندگی شما فعال شد.")
        return {"ok": True}
    bot_choice = req["bot_choice"] if "bot_choice" in req.keys() else "dedicated"
    if bot_choice == "dedicated":
        _set_main_bot_fsm_state(req["user_id"], "ResellerRequestFlow:waiting_bot_token", {"resreq_request_id": request_id})
        await notify_user(
            req["user_id"],
            "✅ پرداخت شما تایید شد!\n\nحالا توکن بات نماینده‌ی خودتان را ارسال کنید (همانی که از @BotFather گرفته‌اید):",
        )
    else:
        # «لینک اختصاصی داخل بات اصلی» یا «بدون بات»: نیازی به توکن/آیدی مالک نیست،
        # نمایندگی همین‌جا تکمیل می‌شود (معادل _finalize_no_bot_reseller_request
        # در handlers_admin.py، ولی با HTTP خام چون این پروسه aiogram Bot ندارد).
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        await _finalize_no_bot_reseller_request_web(req, request)
    return {"ok": True}


async def _finalize_no_bot_reseller_request_web(req, request: Request = None):
    """معادل _finalize_no_bot_reseller_request در handlers_admin.py، برای وقتی که
    تایید پرداخت از پنل وب مستقل انجام می‌شود (نه از تلگرام). هر تغییری در منطق
    تکمیل درخواست باید در هر دو جا اعمال شود."""
    owner_id = req["user_id"]
    bot_token = _bot_token()
    if req["wants_web_panel"] or req["wants_miniapp"]:
        os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
        fake_slug = f"noBot_{req['id']}_{owner_id}"
        fake_token = f"no-bot:{req['id']}:{owner_id}"
        db_path = os.path.join(RESELLER_DBS_DIR, f"{fake_slug}.db")
        # قبلاً اینجا req["request_text"] (متن آزادِ توضیحِ درخواست) به‌جای اسم
        # صاحب بات ذخیره می‌شد؛ get_reseller_owner_display_name اسم/یوزرنیم واقعی را برمی‌گرداند.
        owner_name = (await asyncio.to_thread(db.get_reseller_owner_display_name, owner_id))
        reseller_bot_id = (await asyncio.to_thread(
            db.register_reseller_bot, fake_token, fake_slug, owner_id,
            owner_name, db_path, has_live_bot=0,
        ))
        if req["wants_web_panel"]:
            (await asyncio.to_thread(db.enable_reseller_web_panel, reseller_bot_id))
        (await asyncio.to_thread(db.set_reseller_miniapp_enabled, reseller_bot_id, bool(req["wants_miniapp"])))
        reseller_db = Database(db_path)
        (await asyncio.to_thread(reseller_db.init_db, owner_id=owner_id))
        if req["wants_miniapp"]:
            (await asyncio.to_thread(reseller_db.set_setting, "miniapp_tenant_id", str(reseller_bot_id)))
        (await asyncio.to_thread(reseller_db.set_setting, "custom_config_enabled", "0"))

    (await asyncio.to_thread(db.set_reseller_status, owner_id, True))
    (await asyncio.to_thread(db.set_reseller_supply_model, owner_id, req["supply_model"], req["supply_product_id"]))
    if req["supply_model"] == "fixed_product":
        items = _decode_reseller_supply_items(req.get("request_text") if hasattr(req, "get") else req["request_text"])
        if not items and req["supply_product_id"] and req["supply_qty"]:
            items = [{"product_id": int(req["supply_product_id"]), "quantity": int(req["supply_qty"])}]
        for item in items:
            (await asyncio.to_thread(
                db.set_reseller_product_credit, owner_id, item["product_id"], item["quantity"],
                admin_id=req["reviewed_by"],
                reason=f"تخصیص خودکار پس از تایید درخواست نمایندگی #{req['id']} (پنل وب)",
            ))
    else:
        (await asyncio.to_thread(db.adjust_reseller_credit, 
            owner_id, req["volume_gb"], admin_id=req["reviewed_by"],
            reason=f"تخصیص خودکار پس از تایید درخواست نمایندگی #{req['id']} (پنل وب)",
        ))
    if req["panel_server_id"]:
        (await asyncio.to_thread(db.set_reseller_panel, owner_id, req["panel_server_id"]))
    (await asyncio.to_thread(db.complete_reseller_request, req["id"], owner_id))

    # در مسیر تایید از پنل وب، لینک setup باید در همان پیام نهایی به مالک برسد.
    # ارسال جداگانه‌ی لینک قبلاً ممکن بود بی‌صدا شکست بخورد و مالک فقط «رابط: پنل وب» را ببیند.
    web_panel_note = ""
    if req["wants_web_panel"] and reseller_bot_id:
        try:
            row = await asyncio.to_thread(db.get_reseller_bot, reseller_bot_id)
            if row:
                setup_token = row["web_panel_setup_token"]
                if not setup_token:
                    setup_token = await asyncio.to_thread(
                        db.regenerate_reseller_web_panel_token, reseller_bot_id
                    )
                panel_url = _resolved_admin_panel_url(request) if request is not None else ""
                if setup_token and panel_url:
                    b_value = row["link_slug"] or str(reseller_bot_id)
                    setup_link = f"{panel_url}/setup?b={b_value}&t={setup_token}"
                    login_link = f"{panel_url}/?b={b_value}"
                    web_panel_note = (
                        "\n\n🌐 لینک اولیه فعال‌سازی پنل وب نمایندگی:\n"
                        f"{setup_link}\n\n"
                        "این لینک یک‌بارمصرف است؛ با باز کردن آن یوزرنیم و رمز پنل را خودت تعیین می‌کنی.\n"
                        f"🔗 لینک ورود بعدی: {login_link}"
                    )
                else:
                    web_panel_note = (
                        "\n\n⚠️ پنل وب فعال شد، اما لینک فعال‌سازی ساخته نشد. "
                        "از مدیریت نماینده‌ها گزینه «تولید مجدد لینک راه‌اندازی» را بزنید."
                    )
        except Exception:
            logger.exception("ساخت لینک اولیه پنل وب نماینده #%s ناموفق بود", reseller_bot_id)
            web_panel_note = (
                "\n\n⚠️ پنل وب فعال شد، اما ساخت لینک فعال‌سازی با خطا مواجه شد. "
                "از مدیریت نماینده‌ها لینک راه‌اندازی را مجدداً تولید کنید."
            )

    interface_bits = []
    if req["wants_web_panel"]:
        interface_bits.append("پنل وب")
    if req["wants_miniapp"]:
        interface_bits.append("مینی‌اپ")
    interface_label = " و ".join(interface_bits) if interface_bits else "بدون رابط (فقط اعتبار/موجودی)"
    note = ""
    if req["bot_choice"] == "inline_link":
        (await asyncio.to_thread(db.enable_inline_reseller, owner_id))
        me = await tg_get_me(bot_token)
        username = (me or {}).get("username")
        if username:
            ref_link = f"https://t.me/{username}?start=resref_{owner_id}"
            percent = (await asyncio.to_thread(db.get_setting, "reseller_inline_commission_percent", "10"))
            note = (
                f"\n\n🔗 لینک اختصاصی فروش شما داخل همین بات:\n{ref_link}\n\n"
                f"هر مشتری که با این لینک وارد شود و از شما خرید کند، {percent}٪ از مبلغ هر خرید "
                f"به‌صورت اعتبار کیف پول به شما تعلق می‌گیرد. برای دیدن آمار، دستور /reseller_link را بفرستید."
            )
    await notify_user(owner_id, f"✅ نمایندگی شما تکمیل شد.\n🧩 رابط: {interface_label}{note}{web_panel_note}")
    try:
        for a in (await asyncio.to_thread(db.list_admins_with_roles)):
            if a["role"] in ("owner", "admin"):
                await notify_user(a["telegram_id"], f"✅ نمایندگی #{req['id']} (بدون بات مستقل) تکمیل شد.\n👤 مالک: {owner_id}")
    except Exception:
        pass


@app.get("/api/reseller-fixed-products")
def api_reseller_fixed_products(admin=Depends(require_permission("resellers"))):
    """محصولات مجاز برای مدل تامین «محصول آماده»، همان لیستی که در فرم درخواست
    نمایندگی کاربر هم استفاده می‌شود."""
    return [{"id": p["id"], "name": p["name"]} for p in db.get_reseller_fixed_products()]


def _decode_reseller_supply_items(request_text):
    """Read optional multi-product allocation metadata embedded by the admin make-reseller flow.
    Older requests have no marker and continue using supply_product_id/supply_qty.
    """
    import json as _json
    text = request_text or ""
    marker = "[[RESSELLER_SUPPLY_ITEMS:"
    if marker not in text:
        return []
    try:
        start = text.index(marker) + len(marker)
        end = text.index("]]", start)
        raw = text[start:end]
        items = _json.loads(raw)
        if not isinstance(items, list):
            return []
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = int(item.get("product_id") or 0)
            qty = int(item.get("quantity") or 0)
            if pid > 0 and qty > 0:
                out.append({"product_id": pid, "quantity": qty})
        return out
    except Exception:
        return []


class MakeResellerBody(BaseModel):
    tier_code: str
    percent: Optional[int] = None
    discount_percent: Optional[int] = None
    volume_gb: int = 0
    bot_choice: str = "none"
    wants_web_panel: bool = False
    wants_miniapp: bool = False
    supply_model: str = "volume_credit"
    supply_product_id: Optional[int] = None
    supply_qty: Optional[int] = None
    supply_products: Optional[list] = None
    supply_items: Optional[list[dict]] = None
    panel_server_id: Optional[int] = None
    note: Optional[str] = None


async def _provision_reseller_tier(tg_id: int, tier, body: "MakeResellerBody", request: Request, admin, *, is_change: bool = False):
    """منطق مشترک اعمال یک سطح نمایندگی روی کاربر - هم برای «نماینده کردن»ِ
    کاربر تازه و هم برای «تغییر سطح» یک نماینده‌ی موجود (که پیش از فراخوانیِ
    این تابع باید وضعیت نمایندگیِ قبلی‌اش پاک‌سازی شده باشد) استفاده می‌شود تا
    هر دو مسیر دقیقاً یک رفتار داشته باشند."""
    tier_label = f"{tier['icon']} {tier['title']}"
    if tier["model"] == "commission":
        percent = body.percent or 0
        low = tier["commission_min"] or 1
        high = tier["commission_max"] or 100
        if not (low <= percent <= high):
            raise HTTPException(400, tr(f"درصد کمیسیون باید بین {low} تا {high} باشد."))
        (await asyncio.to_thread(db.enable_inline_reseller, tg_id, percent))
        (await asyncio.to_thread(db.set_user_reseller_tier, tg_id, tier["code"]))
        (await asyncio.to_thread(db.log_admin_action,
            admin["id"], "reseller_change_tier" if is_change else "reseller_make_direct",
            f"کاربر {tg_id} {'به سطح جدید' if is_change else 'مستقیم در سطح'} {tier['code']} نماینده شد ({percent}٪) (پنل وب - {admin['username']})",
            "user", tg_id,
        ))
        await notify_user(
            tg_id,
            (f"✅ سطح نمایندگی شما توسط مدیریت به {tier_label} تغییر کرد!\n\n" if is_change
             else f"✅ شما توسط مدیریت به‌عنوان نماینده‌ی سطح {tier_label} انتخاب شدید!\n\n")
            + f"روی هر خرید مشتریانی که با لینک اختصاصی‌تان وارد شوند، {percent}٪ کارمزد به کیف پول شما اضافه می‌شود.\n"
            "برای دیدن لینک و آمار، دستور /reseller_link را در بات بفرستید.",
        )
        return {"ok": True}
    if tier["model"] == "discount":
        discount_percent = body.discount_percent
        if tier["code"] == "silver":
            if discount_percent is None:
                raise HTTPException(400, tr("برای نمایندگی نقره‌ای درصد تخفیف را مشخص کنید."))
            if not 1 <= int(discount_percent) <= 100:
                raise HTTPException(400, tr("درصد تخفیف نقره‌ای باید بین ۱ تا ۱۰۰ باشد."))
        elif discount_percent is not None:
            raise HTTPException(400, tr("درصد تخفیف فقط برای سطح نقره‌ای قابل تنظیم است."))
        (await asyncio.to_thread(db.set_user_reseller_tier, tg_id, tier["code"], discount_percent))
        (await asyncio.to_thread(db.log_admin_action,
            admin["id"], "reseller_change_tier" if is_change else "reseller_make_direct",
            f"کاربر {tg_id} {'به سطح جدید' if is_change else 'مستقیم در سطح'} {tier['code']} نماینده شد | تخفیف: {discount_percent}% (پنل وب - {admin['username']})",
            "user", tg_id,
        ))
        await notify_user(
            tg_id,
            (f"✅ سطح نمایندگی شما توسط مدیریت به {tier_label} تغییر کرد.\n" if is_change else f"✅ شما توسط مدیریت در سطح {tier_label} قرار گرفتید.\n")
            + f"🏷 تخفیف اختصاصی نمایندگی: {discount_percent}٪\nتخفیف خرید عمده نیز در صورت رسیدن به پلکان مربوطه اعمال می‌شود.",
        )
        return {"ok": True}
    if tier["model"] not in ("volume_credit", "fixed_product"):
        raise HTTPException(400, tr("مدل این سطح پشتیبانی نمی‌شود."))

    body.supply_model = tier["model"]
    body.bot_choice = "dedicated" if tier["has_dedicated_bot"] else "none"
    body.wants_web_panel = bool(tier["has_web_panel"])
    body.wants_miniapp = bool(tier["has_miniapp"])

    fixed_items = []
    if body.supply_model == "fixed_product":
        # چند محصول مجاز است؛ برای سازگاری با درخواست‌های قدیمی، فیلد تکی هم پذیرفته می‌شود.
        if body.supply_items:
            for raw in body.supply_items:
                try:
                    pid = int(raw.get("product_id") or 0)
                    qty = int(raw.get("quantity") or 0)
                except Exception:
                    continue
                if pid > 0 and qty > 0:
                    fixed_items.append({"product_id": pid, "quantity": qty})
            # یک محصول تکراری را تجمیع کن.
            merged = {}
            for item in fixed_items:
                merged[item["product_id"]] = merged.get(item["product_id"], 0) + item["quantity"]
            fixed_items = [{"product_id": pid, "quantity": qty} for pid, qty in merged.items()]
        elif body.supply_product_id and body.supply_qty and body.supply_qty > 0:
            fixed_items = [{"product_id": int(body.supply_product_id), "quantity": int(body.supply_qty)}]
        if not fixed_items:
            raise HTTPException(400, tr("حداقل یک محصول و تعداد آن را انتخاب کنید."))
        for item in fixed_items:
            product = db.get_product(item["product_id"])
            if not product or not product["is_active"] or not product["is_auto_provision"]:
                raise HTTPException(400, tr(f"محصول #{item['product_id']} فعال یا خودکار-ساز نیست."))
        # ستون‌های فعلی درخواست فقط یک محصول را نگه می‌دارند؛ اولین محصول primary است
        # و لیست کامل در marker متنی برای ادامه‌ی flow ذخیره می‌شود.
        body.supply_product_id = fixed_items[0]["product_id"]
        body.supply_qty = fixed_items[0]["quantity"]
        volume_gb = 0
    else:
        if body.volume_gb <= 0:
            raise HTTPException(400, tr("حجم اعتبار اولیه باید عددی مثبت باشد."))
        volume_gb = body.volume_gb

    if body.panel_server_id is not None:
        panel = db.get_panel_server(body.panel_server_id)
        if not panel or not panel["is_active"] or not panel["used_for_reseller"]:
            raise HTTPException(400, tr("پنل انتخاب‌شده فعال نیست یا برای نمایندگی مجاز نشده است."))

    request_text = (body.note or "").strip() or "ثبت مستقیم توسط ادمین از پنل وب"
    if fixed_items:
        # متادیتای داخلی برای اینکه اگر بات مستقل بعداً توکن را فرستاد، تمام اقلام هم تخصیص یابند.
        import json as _json
        request_text = f"{request_text} [[RESSELLER_SUPPLY_ITEMS:{_json.dumps(fixed_items, separators=(',', ':'))}]]"
    request_id = (await asyncio.to_thread(
        db.create_reseller_request, tg_id, volume_gb, request_text, 0,
        body.supply_model, body.supply_product_id, body.supply_qty, body.bot_choice,
        int(body.wants_web_panel), int(body.wants_miniapp), tier["code"],
    ))
    (await asyncio.to_thread(db.log_admin_action,
        admin["id"], "reseller_change_tier" if is_change else "reseller_make_direct",
        f"کاربر {tg_id} {'به سطح جدید نماینده شد' if is_change else 'مستقیم نماینده شد'} (درخواست #{request_id}) (پنل وب - {admin['username']})",
        "user", tg_id,
    ))

    if body.bot_choice == "dedicated":
        (await asyncio.to_thread(
            db.set_reseller_request_status, request_id, "awaiting_bot_info",
            reviewed_by=admin["id"], panel_server_id=body.panel_server_id,
        ))
        _set_main_bot_fsm_state(tg_id, "ResellerRequestFlow:waiting_bot_token", {"resreq_request_id": request_id})
        await notify_user(
            tg_id,
            (f"✅ سطح نمایندگی شما توسط مدیریت به {tier_label} تغییر کرد!\n\n" if is_change
             else f"✅ شما توسط مدیریت به‌عنوان نماینده‌ی سطح {tier_label} انتخاب شدید!\n\n")
            + "برای تکمیل، توکن بات نماینده‌ی خودتان را ارسال کنید (همانی که از @BotFather گرفته‌اید):",
        )
    else:
        (await asyncio.to_thread(
            db.set_reseller_request_status, request_id, "awaiting_payment_review",
            reviewed_by=admin["id"], panel_server_id=body.panel_server_id,
        ))
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        await _finalize_no_bot_reseller_request_web(req, request)

    return {"ok": True, "request_id": request_id}


@app.post("/api/users/{tg_id}/make-reseller")
async def api_make_user_reseller(tg_id: int, body: MakeResellerBody, request: Request, admin=Depends(require_permission("resellers"))):
    """نماینده‌کردن مستقیم یک کاربر از پنل ادمین، با همان گزینه‌های چندسطحیِ فرم
    درخواست نمایندگی کاربر (بند ۶ اسپک) - بدون نیاز به این‌که خودِ کاربر
    درخواست بدهد. برای هر گزینه یک reseller_request با reviewed_by این ادمین ثبت
    می‌شود تا هم در تاریخچه‌ی «درخواست‌های نمایندگی» دیده شود و هم منطق تکمیل
    (اعتبار/موجودی، پنل وب، مینی‌اپ، لینک اینلاین) دقیقاً همان مسیر تاییدشده‌ی
    فعلی را طی کند - نه یک کپیِ جدا که ممکن است رفتارش با گذر زمان از مسیر اصلی
    جدا بیفتد."""
    tier = (await asyncio.to_thread(db.get_reseller_tier, body.tier_code))
    if not tier or not tier["is_enabled"]:
        raise HTTPException(400, tr("سطح نمایندگی نامعتبر یا غیرفعال است."))
    user = (await asyncio.to_thread(db.get_user, tg_id))
    if not user:
        raise HTTPException(404, tr("کاربر یافت نشد."))
    if (
        (await asyncio.to_thread(db.is_reseller, tg_id))
        or (await asyncio.to_thread(db.is_inline_reseller, tg_id))
        or (await asyncio.to_thread(db.get_agent_tier, tg_id))
    ):
        raise HTTPException(400, tr("این کاربر همین الان هم نماینده است."))
    if (await asyncio.to_thread(db.get_open_reseller_request, tg_id)):
        raise HTTPException(400, tr("این کاربر یک درخواست نمایندگی باز دارد؛ ابتدا از تب «درخواست‌های نمایندگی» آن را ببندید."))
    return await _provision_reseller_tier(tg_id, tier, body, request, admin, is_change=False)


@app.post("/api/users/{tg_id}/change-reseller-tier")
async def api_change_user_reseller_tier(tg_id: int, body: MakeResellerBody, request: Request, admin=Depends(require_permission("resellers"))):
    """تغییر سطح نمایندگیِ یک نماینده‌ی موجود (مثلاً برنزی -> طلایی)، بدون این‌که
    ادمین مجبور باشد اول کاملاً حذفش کند و بعد از نو بسازد: وضعیت نمایندگیِ
    قبلی (بات اختصاصی، اعتبار/موجودی، کمیسیون، سطح تخفیف) کامل با همان موتور
    مرکزیِ حذف نمایندگی (wipe_agent_state) پاک می‌شود و سپس سطح جدید درست مثل
    «نماینده کردن» از ابتدا برایش تنظیم می‌شود. کیف پول و سابقه‌ی مالی کاربر
    دست‌نخورده باقی می‌مانند."""
    tier = (await asyncio.to_thread(db.get_reseller_tier, body.tier_code))
    if not tier or not tier["is_enabled"]:
        raise HTTPException(400, tr("سطح نمایندگی نامعتبر یا غیرفعال است."))
    user = (await asyncio.to_thread(db.get_user, tg_id))
    if not user:
        raise HTTPException(404, tr("کاربر یافت نشد."))
    current_tier = await asyncio.to_thread(db.get_agent_tier, tg_id)
    if not current_tier:
        raise HTTPException(400, tr("این کاربر در حال حاضر نماینده‌ی هیچ سطحی نیست؛ از گزینه‌ی «نماینده کردن» استفاده کنید."))
    if current_tier == tier["code"]:
        raise HTTPException(400, tr("این کاربر همین الان هم در همین سطح است."))
    if (await asyncio.to_thread(db.get_open_reseller_request, tg_id)):
        raise HTTPException(400, tr("این کاربر یک درخواست نمایندگی باز دارد؛ ابتدا از تب «درخواست‌های نمایندگی» آن را ببندید."))
    await asyncio.to_thread(db.wipe_agent_state, tg_id)
    return await _provision_reseller_tier(tg_id, tier, body, request, admin, is_change=True)


class ResellerRequestRejectBody(BaseModel):
    reason: str
    kind: str = "rejected"


@app.post("/api/reseller-requests/{request_id}/reject")
async def api_reject_reseller_request(request_id: int, body: ResellerRequestRejectBody, admin=Depends(require_permission("resellers"))):
    if body.kind not in ("rejected", "payment_rejected"):
        raise HTTPException(400, tr("نوع رد نامعتبر است."))
    req = (await asyncio.to_thread(db.get_reseller_request, request_id))
    if not req or not (await asyncio.to_thread(db.is_reseller_request_open, req["status"])):
        raise HTTPException(400, tr("این درخواست دیگر باز نیست."))
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, tr("دلیل رد الزامی است."))
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
        raise HTTPException(400, tr("این درخواست دیگر باز نیست."))
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


class PanelServerReorderBody(BaseModel):
    server_ids: List[int]


class PanelServerUpdateBody(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    api_username: Optional[str] = None
    api_password: Optional[str] = None
    xui_inbound_ids: Optional[List[int]] = None
    xui_sub_base_url: Optional[str] = None


class PanelServerTemplateBody(BaseModel):
    template_username: str


class PanelServerXuiConfigBody(BaseModel):
    inbound_ids: Optional[List[int]] = None
    sub_base_url: str


def _panel_server_public(s, health=None) -> dict:
    h = (health or {}).get(s["id"])
    is_sub_base_type = s["panel_type"] in SUB_BASE_URL_PANEL_TYPES
    xui_inbound_ids = parse_xui_inbound_ids(s) if s["panel_type"] in INBOUND_SELECT_PANEL_TYPES else []
    if is_sub_base_type:
        needs_inbound = s["panel_type"] in INBOUND_SELECT_PANEL_TYPES
        configured = bool(s["xui_sub_base_url"]) and (bool(xui_inbound_ids) if needs_inbound else True)
    else:
        configured = bool(s["group_ids"] and s["proxy_settings"])
    return {
        "id": s["id"], "name": s["name"], "panel_type": s["panel_type"],
        "type_label": PANEL_TYPE_LABELS.get(s["panel_type"], s["panel_type"]),
        "api_url": s["api_url"], "template_username": s["template_username"],
        "has_template": bool(s["group_ids"] and s["proxy_settings"]),
        "xui_inbound_ids": xui_inbound_ids, "xui_sub_base_url": s["xui_sub_base_url"],
        "is_configured": configured,
        "used_for_custom_config": bool(s["used_for_custom_config"]),
        "used_for_test_config": bool(s["used_for_test_config"]),
        "default_group": s["default_group"], "is_active": bool(s["is_active"]),
        "health_status": h["status"] if h else None,
        "health_last_check": h["last_check"] if h else None,
        "health_last_change": h["last_change"] if h else None,
        "health_error": (h["last_error"] or None) if h else None,
        "sort_order": int(s["sort_order"] or 0),
    }


@app.get("/api/panel-servers")
def api_panel_servers(admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    health = db.list_panel_health()
    return [_panel_server_public(s, health) for s in db.get_panel_servers()]


@app.post("/api/panel-servers/reorder")
def api_reorder_panel_servers(body: PanelServerReorderBody, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    try:
        db.reorder_panel_servers(body.server_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log_admin_action(admin["id"], "panel_reorder", ",".join(map(str, body.server_ids)), "panel")
    return {"ok": True}


@app.get("/api/panel-servers/panel-types")
def api_panel_server_types(admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    """لیست انواع پنل پشتیبانی‌شده - برای ساخت فرم افزودن سرور در فرانت."""
    return [
        {
            "type": k, "label": v,
            "needs_template": k in TEMPLATE_BASED_PANEL_TYPES,
            "needs_sub_base_url": k in SUB_BASE_URL_PANEL_TYPES,
            "needs_inbound_select": k in INBOUND_SELECT_PANEL_TYPES,
            "single_inbound": k in SINGLE_INBOUND_PANEL_TYPES,
            "token_only": k in TOKEN_ONLY_PANEL_TYPES,
            "template_prompt": TEMPLATE_PROMPTS.get(k),
        }
        for k, v in PANEL_TYPE_LABELS.items()
    ]


@app.post("/api/panel-servers")
async def api_add_panel_server(body: PanelServerBody, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    if not body.name.strip() or not body.api_url.strip() or not body.api_password.strip():
        raise HTTPException(400, tr("نام، آدرس و پسورد/توکن الزامی هستند."))
    if body.panel_type not in PROVIDERS:
        raise HTTPException(400, tr("نوع پنل پشتیبانی نمی‌شود."))

    username = body.api_username.strip()
    if body.panel_type in TOKEN_ONLY_PANEL_TYPES:
        username = username or TOKEN_ONLY_PANEL_TYPES[body.panel_type]

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
            raise HTTPException(400, tr("این پنل هیچ inbound ای ندارد. اول از داخل پنل یک inbound بساز."))
        db.log_admin_action(admin["id"], "panel_add", f"سرور «{body.name}» (3X-UI، #{server_id}) از پنل وب")
        return {"id": server_id, "inbounds": inbounds, "needs_inbound_select": True}

    if body.panel_type in SUB_BASE_URL_PANEL_TYPES:
        # مثل Hiddify: inbound لازم نیست؛ باید بعداً با /xui-config تکمیل شود.
        server_id = db.add_panel_server(body.name.strip(), body.panel_type, body.api_url.strip(), username, body.api_password, body.default_group)
        db.log_admin_action(admin["id"], "panel_add", f"سرور «{body.name}» (#{server_id}) از پنل وب")
        return {"id": server_id, "needs_sub_base_url": True}

    # خانواده‌ی PasarGuard/Marzban/Marzneshin: با «کاربر نمونه» قالب گرفته می‌شود
    if not body.template_username or not body.template_username.strip():
        raise HTTPException(400, tr("نام کاربری نمونه (برای دریافت قالب) الزامی است."))
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
async def api_panel_server_inbounds(server_id: int, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    server = (await asyncio.to_thread(db.get_panel_server, server_id))
    if not server:
        raise HTTPException(404, tr("یافت نشد."))
    try:
        provider = get_provider(server)
        inbounds = await provider.list_inbounds()
    except PanelError as e:
        raise HTTPException(400, str(e))
    return inbounds


@app.post("/api/panel-servers/{server_id}/xui-config")
async def api_set_panel_server_xui_config(server_id: int, body: PanelServerXuiConfigBody, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    """تکمیل ساخت سرور برای پنل‌های نیازمند «آدرس پایه‌ی Subscription» (3X-UI/Hiddify)."""
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, tr("یافت نشد."))
    if server["panel_type"] not in SUB_BASE_URL_PANEL_TYPES:
        raise HTTPException(400, tr("این سرور به این تنظیمات نیاز ندارد."))
    if server["panel_type"] in INBOUND_SELECT_PANEL_TYPES and not body.inbound_ids:
        raise HTTPException(400, tr("انتخاب حداقل یک inbound برای این نوع پنل الزامی است."))
    if server["panel_type"] in SINGLE_INBOUND_PANEL_TYPES and len(body.inbound_ids or []) > 1:
        raise HTTPException(400, tr("برای این نوع پنل فقط یک inbound قابل انتخاب است."))
    url = body.sub_base_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(400, tr("آدرس Subscription باید با http:// یا https:// شروع شود."))
    update_kwargs = {"xui_sub_base_url": url}
    if body.inbound_ids:
        update_kwargs["xui_inbound_ids"] = json.dumps(body.inbound_ids)
    db.update_panel_server(server_id, **update_kwargs)
    db.log_admin_action(admin["id"], "panel_update", f"xui-config سرور #{server_id} (پنل وب)", "panel", server_id)
    return {"ok": True}


@app.post("/api/panel-servers/{server_id}/template")
async def api_set_panel_server_template(server_id: int, body: PanelServerTemplateBody, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    """گرفتن/به‌روزرسانی قالب (group_ids/proxy_settings) از روی یک کاربر نمونه‌ی
    دیگر روی پنل - برای پنل‌های خانواده‌ی PasarGuard/Marzban/Marzneshin."""
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, tr("یافت نشد."))
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
def api_toggle_panel_server(server_id: int, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, tr("یافت نشد."))
    db.update_panel_server(server_id, is_active=0 if server["is_active"] else 1)
    db.log_admin_action(admin["id"], "panel_toggle", f"سرور #{server_id} (پنل وب)", "panel", server_id)
    return {"ok": True}


@app.post("/api/panel-servers/{server_id}/usage/{kind}")
def api_toggle_panel_server_usage(server_id: int, kind: str, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    """مشخص‌کردن این‌که این سرور برای «کانفیگ شخصی» و/یا «کانفیگ تست» استفاده شود؛
    قبلاً این کلیدها فقط از داخل ربات/مینی‌اپ قابل تنظیم بودند."""
    if kind not in ("custom", "test"):
        raise HTTPException(400, tr("نوع مصرف نامعتبر است."))
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, tr("یافت نشد."))
    field = "used_for_custom_config" if kind == "custom" else "used_for_test_config"
    db.update_panel_server(server_id, **{field: 0 if server[field] else 1})
    db.log_admin_action(admin["id"], "panel_usage_toggle", f"سرور #{server_id} | {field} (پنل وب)", "panel", server_id)
    return {"ok": True}


@app.put("/api/panel-servers/{server_id}")
def api_update_panel_server(server_id: int, body: PanelServerUpdateBody, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(404, tr("یافت نشد."))
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if server["panel_type"] in SINGLE_INBOUND_PANEL_TYPES and len(fields.get("xui_inbound_ids") or []) > 1:
        raise HTTPException(400, tr("برای این نوع پنل فقط یک inbound قابل انتخاب است."))
    if "xui_inbound_ids" in fields:
        fields["xui_inbound_ids"] = json.dumps(fields["xui_inbound_ids"])
    if fields:
        db.update_panel_server(server_id, **fields)
    db.log_admin_action(admin["id"], "panel_update", str(server_id), "panel", server_id)
    return {"ok": True}


@app.delete("/api/panel-servers/{server_id}")
def api_delete_panel_server(server_id: int, force: bool = False, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
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
async def api_test_panel_server(server_id: int, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    server = (await asyncio.to_thread(db.get_panel_server, server_id))
    if not server:
        raise HTTPException(404, tr("یافت نشد."))
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


# قابلیت ۵۰: «متن‌های ربات» - رجیستری کامل (کاربر + ادمین) که با اسکن خودکار
# کد ساخته می‌شود (نگاه کن: text_scanner.py، Database.list_text_registry).
@app.get("/api/texts")
def api_list_texts(search: str = "", admin=Depends(require_permission("settings"))):
    return {"items": db.list_text_registry(search)}


class TextSetBody(BaseModel):
    key: str
    value: str


@app.post("/api/texts")
def api_set_text(body: TextSetBody, admin=Depends(require_permission("settings"))):
    db.set_text(body.key, body.value)
    db.log_admin_action(
        admin["id"], "setting_change", f"ویرایش متن ربات: {body.key} (پنل وب - {admin['username']})",
        "bot_text", body.key,
    )
    return {"ok": True}


class TextResetBody(BaseModel):
    key: str


@app.post("/api/texts/reset")
def api_reset_text(body: TextResetBody, admin=Depends(require_permission("settings"))):
    db.reset_text(body.key)
    db.log_admin_action(
        admin["id"], "setting_change", f"بازگردانی متن ربات به پیش‌فرض: {body.key} (پنل وب - {admin['username']})",
        "bot_text", body.key,
    )
    return {"ok": True}


# --------------------------------------------------- درگاه‌های پرداخت سفارشی/پویا -----
# هر API پرداختی که ادمین بخواهد (بدون نوشتن کد) از همین‌جا وصل می‌شود؛ خودِ
# فاکتور/چک‌اوت مشتری از داخل مینی‌اپ تلگرام انجام می‌شود (این پنل فقط تنظیمات
# را می‌سازد که هر دو سرویس، روی همان دیتابیس تننت، به‌اشتراک می‌گذارند).

def _gw_load(gateway_id: int = None, gateway_key: str = None):
    row = db.get_custom_gateway(gateway_id) if gateway_id else db.get_custom_gateway_by_key(gateway_key)
    if not row:
        raise HTTPException(status_code=404, detail=tr("این درگاه پیدا نشد."))
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
        # حداقل مبلغ مجاز واریز با این درگاه (تومان). 0 یعنی بدون محدودیت؛
        # همان چیزی که بات و مینی‌اپ هر دو موقع چک‌اوت اعمالش می‌کنند.
        "min_amount": int(row["min_amount"] or 0) if "min_amount" in row.keys() else 0,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


class CustomGatewayIn(BaseModel):
    key: str
    name: str
    enabled: bool = False
    config: dict
    min_amount: int = 0


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
        raise HTTPException(status_code=400, detail=tr("کلید درگاه نامعتبر است (فقط حروف/عدد انگلیسی، - و _)."))
    if db.get_custom_gateway_by_key(key):
        raise HTTPException(status_code=400, detail=tr("درگاهی با همین کلید قبلاً ثبت شده."))
    gateway_id = db.create_custom_gateway(key, body.name.strip() or key, body.config, body.enabled, max(0, body.min_amount or 0))
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

    db.update_custom_gateway(gateway_id, name=body.name.strip() or row["name"], config=body.config,
                              enabled=body.enabled, min_amount=max(0, body.min_amount or 0))
    db.log_admin_action(admin["id"], "custom_gateway_update", f"درگاه سفارشی «{row['name']}» ویرایش شد (پنل وب - {admin['username']}).")
    row, config = _gw_load(gateway_id=gateway_id)
    return _gw_mask(row, config)


@app.delete("/api/gateways/{gateway_id}")
def api_delete_gateway(gateway_id: int, admin=Depends(require_permission("settings"))):
    row, _ = _gw_load(gateway_id=gateway_id)
    db.delete_custom_gateway(gateway_id)
    db.log_admin_action(admin["id"], "custom_gateway_delete", f"درگاه سفارشی «{row['name']}» حذف شد (پنل وب - {admin['username']}).")
    return {"ok": True}


@app.post("/api/gateways/{gateway_id}/toggle")
def api_toggle_gateway(gateway_id: int, admin=Depends(require_permission("settings"))):
    """فعال/غیرفعال‌کردن سریع یک درگاه سفارشی بدون نیاز به ارسال کل config
    (برای اپ موبایل - جایی که فقط کلید enabled باید عوض شود)."""
    row, _ = _gw_load(gateway_id=gateway_id)
    db.update_custom_gateway(gateway_id, enabled=not bool(row["enabled"]))
    db.log_admin_action(admin["id"], "custom_gateway_toggle",
                         f"درگاه سفارشی «{row['name']}» {'فعال' if not row['enabled'] else 'غیرفعال'} شد (پنل وب - {admin['username']}).",
                         "gateway", gateway_id)
    return {"ok": True}


@app.get("/api/payment-methods")
def api_payment_methods(admin=Depends(require_any_permission("settings", "catalog"))):
    """کاتالوگ کامل روش‌های پرداخت (داخلی + درگاه‌های سفارشی) به‌همراه حداقل
    مبلغ هرکدام؛ منبع همان db.get_payment_methods_catalog است که بات و
    مینی‌اپ هم موقع چک‌اوت از آن می‌خوانند - برای نمایش/ویرایش یک‌جا در پنل."""
    return db.get_payment_methods_catalog()


@app.get("/api/wallet/payment-methods")
def api_get_wallet_payment_methods(admin=Depends(require_any_permission("settings", "catalog"))):
    """None/[] یعنی «همه‌ی روش‌ها مجازند» (بدون محدودیت). دقیقاً معادل
    /api/products/{id}/payment-methods اما مستقل از محصول - فقط روی
    شارژ کیف پول اثر دارد."""
    return {"allowed": db.get_wallet_topup_payment_methods()}


class WalletPaymentMethodsBody(BaseModel):
    methods: Optional[List[str]] = None


@app.post("/api/wallet/payment-methods")
def api_set_wallet_payment_methods(body: WalletPaymentMethodsBody,
                                    admin=Depends(require_permission("settings"))):
    """محدودسازی این‌که شارژ کیف پول با کدام روش‌های پرداخت (کارت/آبان‌گیت‌وی/
    کریپتو/بلوپال/نوآپی/درگاه سفارشی) ممکن باشد. methods=null یا [] یعنی حذف
    محدودیت (همه‌ی روش‌های فعال مجازند) - دقیقاً همان چیزی که بات از منوی
    خودش می‌سازد."""
    db.set_wallet_topup_payment_methods(body.methods or None)
    db.log_admin_action(admin["id"], "wallet_payment_methods",
                         f"{body.methods or 'همه'} (پنل وب - {admin['username']})",
                         "setting", "wallet_topup_payment_methods")
    return {"ok": True}


class PaymentMethodMinAmountBody(BaseModel):
    min_amount: int = 0


@app.post("/api/payment-methods/{method_key}/min-amount")
def api_set_payment_method_min_amount(method_key: str, body: PaymentMethodMinAmountBody,
                                       admin=Depends(require_permission("settings"))):
    """تعیین حداقل مبلغ مجاز برای یک روش پرداخت داخلی (card/abangateway/crypto)
    یا یک درگاه سفارشی (کلید 'custom:<key>'). همان تنظیمی که بات از داخل
    منوی خودش می‌سازد؛ اینجا معادل وب آن است."""
    value = max(0, body.min_amount or 0)
    if method_key.startswith("custom:"):
        gw = db.get_custom_gateway_by_key(method_key.split(":", 1)[1])
        if not gw:
            raise HTTPException(status_code=404, detail=tr("این درگاه پیدا نشد."))
        db.update_custom_gateway(gw["id"], min_amount=value)
    else:
        db.set_setting(f"min_amount_{method_key}", str(value))
    db.log_admin_action(admin["id"], "payment_method_min_amount",
                         f"{method_key}={value} (پنل وب - {admin['username']})", "setting", method_key)
    return {"ok": True}


class PaymentMethodPushBody(BaseModel):
    enabled: bool


@app.post("/api/payment-methods/{method_key}/push")
def api_set_payment_method_push(method_key: str, body: PaymentMethodPushBody,
                                 admin=Depends(require_permission("settings"))):
    """روشن/خاموش‌کردن پوش نوتیف ادمین برای یک روش پرداخت (داخلی یا
    درگاه سفارشی با کلید 'custom:<key>') - مستقل از بقیه‌ی روش‌ها."""
    if method_key.startswith("custom:") and not db.get_custom_gateway_by_key(method_key.split(":", 1)[1]):
        raise HTTPException(status_code=404, detail=tr("این درگاه پیدا نشد."))
    db.set_payment_method_push_enabled(method_key, body.enabled)
    db.log_admin_action(admin["id"], "payment_method_push",
                         f"{method_key} push={'on' if body.enabled else 'off'} (پنل وب - {admin['username']})",
                         "setting", method_key)
    return {"ok": True}


class PaymentMethodNotifyTimeoutBody(BaseModel):
    minutes: int = 0


@app.post("/api/payment-methods/{method_key}/notify-timeout")
def api_set_payment_method_notify_timeout(method_key: str, body: PaymentMethodNotifyTimeoutBody,
                                           admin=Depends(require_permission("settings"))):
    """مهلت (دقیقه) برای درگاه‌های «تایید آنی»: اگر فاکتور بیش از این مدت هنوز
    تایید نشده باشد، یک پوش «معطل‌مانده» جدا برای ادمین می‌رود. صفر یعنی خاموش."""
    if method_key.startswith("custom:") and not db.get_custom_gateway_by_key(method_key.split(":", 1)[1]):
        raise HTTPException(status_code=404, detail=tr("این درگاه پیدا نشد."))
    minutes = max(0, int(body.minutes or 0))
    db.set_payment_method_notify_timeout(method_key, minutes)
    db.log_admin_action(admin["id"], "payment_method_notify_timeout",
                         f"{method_key} timeout={minutes}m (پنل وب - {admin['username']})",
                         "setting", method_key)
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
        return {"success": False, "error": tr("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")}
    try:
        computed = await custom_gateway_payment.compute_send_amount(db, config, body.amount_toman)
    except custom_gateway_payment.CustomGatewayPaymentError as e:
        return {"success": False, "error": str(e)}
    gw = payment_engine.GenericGateway(config)
    tenant = _current_tenant.get()
    our_ref = f"test-{gateway_id}-{int(time.time())}"
    try:
        result = await gw.create_invoice(
            amount=computed["amount"], amount_toman=body.amount_toman,
            order_id=our_ref, currency=computed["currency"], description="تست اتصال درگاه",
            tenant_id=tenant.slug or "main",
            callback_url=f"{API_BASE_URL}/api/pay/custom/{row['gateway_key']}/return?b={tenant.slug}&txn={our_ref}",
            webhook_url=f"{API_BASE_URL}/api/webhooks/custom/{row['gateway_key']}?b={tenant.slug}",
        )
    except payment_engine.PaymentEngineError as e:
        return {"success": False, "error": str(e)}
    return {
        "success": True, "invoice_url": result.get("invoice_url"), "txn_id": result.get("txn_id"),
        "sent_amount": computed["amount"], "sent_currency": computed["currency"],
    }


# ------------------------------------- کارت‌به‌کارت با تایید خودکار (پیامک بانک) -----
# اپ اندروید BankSmsForwarder پیامک بانک را می‌خواند و به وب‌هوک زیر می‌فرستد؛
# چون مبلغ هر فاکتور یکتاست (مبلغ اصلی + چند رقم آخر تصادفی)، حتی با هزاران
# پرداخت هم‌زمان هم تشخیص فاکتورِ مربوطه بدون ابهام است.

class CardToCardCardIn(BaseModel):
    card_number: str
    holder_name: str = ""
    bank_name: str = ""
    sort_order: int = 0


def _clean_card_number(raw: str) -> str:
    number = re.sub(r"\D", "", raw or "")
    if len(number) != 16:
        raise HTTPException(status_code=400, detail=tr("شماره کارت باید ۱۶ رقم باشد."))
    return number


@app.get("/api/card-to-card/cards")
def api_list_c2c_cards(admin=Depends(require_permission("settings"))):
    return [dict(r) for r in db.list_card_to_card_cards()]


@app.post("/api/card-to-card/cards")
def api_create_c2c_card(body: CardToCardCardIn, admin=Depends(require_permission("settings"))):
    number = _clean_card_number(body.card_number)
    card_id = db.create_card_to_card_card(number, body.holder_name.strip(), body.bank_name.strip(), body.sort_order)
    db.log_admin_action(admin["id"], "card_to_card_card_create",
                         f"کارت با ۴ رقم آخر {number[-4:]} اضافه شد (پنل وب - {admin['username']}).")
    return dict(db.get_card_to_card_card(card_id))


@app.put("/api/card-to-card/cards/{card_id}")
def api_update_c2c_card(card_id: int, body: CardToCardCardIn, admin=Depends(require_permission("settings"))):
    if not db.get_card_to_card_card(card_id):
        raise HTTPException(status_code=404, detail=tr("این کارت پیدا نشد."))
    number = _clean_card_number(body.card_number)
    db.update_card_to_card_card(card_id, card_number=number, holder_name=body.holder_name.strip(),
                                 bank_name=body.bank_name.strip(), sort_order=body.sort_order)
    db.log_admin_action(admin["id"], "card_to_card_card_update",
                         f"کارت #{card_id} ویرایش شد (پنل وب - {admin['username']}).")
    return dict(db.get_card_to_card_card(card_id))


@app.post("/api/card-to-card/cards/{card_id}/toggle")
def api_toggle_c2c_card(card_id: int, admin=Depends(require_permission("settings"))):
    if not db.get_card_to_card_card(card_id):
        raise HTTPException(status_code=404, detail=tr("این کارت پیدا نشد."))
    db.toggle_card_to_card_card(card_id)
    return {"ok": True}


@app.delete("/api/card-to-card/cards/{card_id}")
def api_delete_c2c_card(card_id: int, admin=Depends(require_permission("settings"))):
    if not db.get_card_to_card_card(card_id):
        raise HTTPException(status_code=404, detail=tr("این کارت پیدا نشد."))
    db.delete_card_to_card_card(card_id)
    db.log_admin_action(admin["id"], "card_to_card_card_delete",
                         f"کارت #{card_id} حذف شد (پنل وب - {admin['username']}).")
    return {"ok": True}


@app.get("/api/settings/card-to-card")
def api_get_c2c_webhook_info(admin=Depends(require_permission("settings"))):
    """فقط اطلاعات وب‌هوک (که فیلد ساده‌ی تنظیمات نیست) را برمی‌گرداند؛ فعال‌بودن/مهلت/
    تعداد رقم/واحد مبلغ/حداقل مبلغ مثل بقیه‌ی تنظیمات پرداخت از همان اندپوینت عمومی
    /api/settings ذخیره و خوانده می‌شوند (تا همه‌ی روش‌های پرداخت یک‌جا مدیریت شوند)."""
    tenant = _current_tenant.get()
    token = db.get_setting("card_to_card_sms_webhook_token", "")
    return {
        "webhook_token_set": bool(token),
        "webhook_url": (f"{API_BASE_URL}/api/webhooks/sms-forwarder?b={tenant.slug}"
                        if API_BASE_URL else None),
    }


@app.post("/api/settings/card-to-card/regenerate-token")
def api_regen_c2c_token(admin=Depends(require_permission("settings"))):
    token = secrets.token_hex(24)
    db.set_setting("card_to_card_sms_webhook_token", token)
    db.log_admin_action(admin["id"], "card_to_card_token_regen",
                         f"توکن وب‌هوک کارت‌به‌کارت بازتولید شد (پنل وب - {admin['username']}).")
    return {"webhook_token": token}


@app.get("/api/card-to-card/invoices")
def api_list_c2c_invoices(status: Optional[str] = None, admin=Depends(require_permission("orders"))):
    return [dict(r) for r in db.list_card_to_card_invoices(status=status)]


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
        raise HTTPException(400, tr("درصد باید بین ۰ تا ۱۰۰ باشد."))
    if body.commission_max_count < 0:
        raise HTTPException(400, tr("سقف تعداد نفرات نمی‌تواند منفی باشد."))
    if body.free_config_threshold < 0 or body.invite_bonus_amount < 0 or body.invite_bonus_max_count < 0:
        raise HTTPException(400, tr("مقادیر عددی نمی‌توانند منفی باشند."))

    product = None
    if body.free_config_product_id:
        product = db.get_product(body.free_config_product_id)
        if not product:
            raise HTTPException(400, tr("محصول جایزه یافت نشد."))
        if not product["is_auto_provision"] or not product["provision_server_id"]:
            raise HTTPException(400, tr("محصول جایزه باید «تحویل خودکار» داشته باشد و به یک پنل وصل باشد."))
    if body.free_config_enabled and (not body.free_config_product_id or body.free_config_threshold < 1):
        raise HTTPException(400, tr("برای فعال‌سازی کانفیگ رایگان، محصول جایزه و آستانه‌ی معتبر (حداقل ۱) لازم است."))
    if body.invite_bonus_enabled and body.invite_bonus_amount <= 0:
        raise HTTPException(400, tr("برای فعال‌سازی شارژ به‌ازای دعوت، مبلغ باید بزرگ‌تر از صفر باشد."))

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


# ------------------------------------------------------- هشدار زیرمجموعه‌گیری فیک -----
# تشخیص صرفاً بر رفتار حساب‌ها (نه IP/دستگاه که تلگرام نمی‌دهد) - دعوت انبوه در
# یک بازه‌ی کوتاه یا نرخ بالای زیرمجموعه‌های بی‌خرید. بررسی خودِ پیام هر دعوت تازه
# در handlers_user.cmd_start انجام می‌شود؛ این بخش فقط تنظیمات و لیست/رفع فلگ‌ها را
# در پنل وب در اختیار ادمین می‌گذارد.

class ReferralFraudSettingsBody(BaseModel):
    detection_enabled: bool
    burst_count: int
    burst_minutes: int
    min_invites: int
    zero_purchase_ratio: int
    auto_suspend: bool


@app.get("/api/settings/referral-fraud")
def api_get_referral_fraud_settings(admin=Depends(require_permission("settings"))):
    return {
        "detection_enabled": db.get_setting("referral_fraud_detection_enabled", "1") == "1",
        "burst_count": int(db.get_setting("referral_fraud_burst_count", "5") or 0),
        "burst_minutes": int(db.get_setting("referral_fraud_burst_minutes", "60") or 0),
        "min_invites": int(db.get_setting("referral_fraud_min_invites", "5") or 0),
        "zero_purchase_ratio": int(db.get_setting("referral_fraud_zero_purchase_ratio", "80") or 0),
        "auto_suspend": db.get_setting("referral_fraud_auto_suspend", "1") == "1",
    }


@app.post("/api/settings/referral-fraud")
def api_set_referral_fraud_settings(body: ReferralFraudSettingsBody, admin=Depends(require_permission("settings"))):
    if body.burst_count < 1 or body.min_invites < 1:
        raise HTTPException(400, tr("تعداد دعوت انبوه و حداقل تعداد دعوت باید حداقل ۱ باشند."))
    if body.burst_minutes < 1:
        raise HTTPException(400, tr("بازه‌ی زمانی دعوت انبوه باید حداقل ۱ دقیقه باشد."))
    if body.zero_purchase_ratio < 1 or body.zero_purchase_ratio > 100:
        raise HTTPException(400, tr("درصد نرخ بی‌خریدی باید بین ۱ تا ۱۰۰ باشد."))

    db.set_setting("referral_fraud_detection_enabled", "1" if body.detection_enabled else "0")
    db.set_setting("referral_fraud_burst_count", str(body.burst_count))
    db.set_setting("referral_fraud_burst_minutes", str(body.burst_minutes))
    db.set_setting("referral_fraud_min_invites", str(body.min_invites))
    db.set_setting("referral_fraud_zero_purchase_ratio", str(body.zero_purchase_ratio))
    db.set_setting("referral_fraud_auto_suspend", "1" if body.auto_suspend else "0")
    db.log_admin_action(admin["id"], "setting_change", f"referral fraud settings (پنل وب - {admin['username']})", "setting", "referral_fraud")
    return {"ok": True}


@app.get("/api/referral-fraud/flags")
def api_list_referral_fraud_flags(resolved: bool = False, admin=Depends(require_permission("users"))):
    rows = rows_to_list(db.list_referral_fraud_flags(resolved=resolved))
    return {"items": rows}


@app.post("/api/referral-fraud/flags/{flag_id}/resolve")
def api_resolve_referral_fraud_flag(flag_id: int, admin=Depends(require_permission("users"))):
    resolved = db.resolve_referral_fraud_flag(flag_id, admin["id"])
    if not resolved:
        raise HTTPException(404, tr("این هشدار یافت نشد یا قبلاً رفع شده است."))
    db.log_admin_action(
        admin["id"], "referral_fraud_resolve",
        f"فلگ #{flag_id} | دعوت‌کننده {resolved['referrer_id']} (پنل وب - {admin['username']})",
    )
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
        raise HTTPException(400, tr("درصد برد باید بین ۰ تا ۱۰۰ باشد."))
    if not body.prizes or any(p <= 0 for p in body.prizes):
        raise HTTPException(400, tr("حداقل یک جایزه‌ی معتبر (بزرگ‌تر از صفر) لازم است."))
    if body.expiry_hours <= 0 or body.cooldown_hours <= 0:
        raise HTTPException(400, tr("مقادیر ساعت باید بزرگ‌تر از صفر باشند."))
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
        raise HTTPException(400, tr("درصد تخفیف باید بین ۰ تا ۱۰۰ باشد."))
    if body.days_before <= 0 or body.discount_expiry_hours <= 0:
        raise HTTPException(400, tr("مقادیر روز/ساعت باید بزرگ‌تر از صفر باشند."))
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
        raise HTTPException(400, tr("مبنای آستانه باید percent یا gb باشد."))
    if body.discount_percent < 0 or body.discount_percent > 100:
        raise HTTPException(400, tr("درصد تخفیف باید بین ۰ تا ۱۰۰ باشد."))
    if not (0 < body.percent < 100):
        raise HTTPException(400, tr("درصد آستانه باید بین ۱ تا ۹۹ باشد."))
    if body.gb_left <= 0:
        raise HTTPException(400, tr("آستانه‌ی گیگابایت باید بزرگ‌تر از صفر باشد."))
    if body.discount_expiry_hours <= 0:
        raise HTTPException(400, tr("اعتبار کد تخفیف باید بزرگ‌تر از صفر باشد."))
    db.set_setting("volume_reminder_enabled", "1" if body.enabled else "0")
    db.set_setting("volume_reminder_mode", body.mode)
    db.set_setting("volume_reminder_percent", str(body.percent))
    db.set_setting("volume_reminder_gb_left", str(body.gb_left))
    db.set_setting("volume_discount_percent", str(body.discount_percent))
    db.set_setting("volume_discount_expiry_hours", str(body.discount_expiry_hours))
    db.log_admin_action(admin["id"], "setting_change", "volume reminder settings updated (پنل وب)", "setting", "volume_reminder")
    return {"ok": True}


class ConnectAlertSettingsBody(BaseModel):
    # همه‌ی فیلدها Optional هستند چون این تنظیمات از دو کارت جدا (اپ native:
    # «هشدار اتصال» و «هشدار عدم‌اتصال») روی همین یک endpoint ذخیره می‌شوند؛
    # هر کارت فقط فیلدهای خودش را می‌فرستد. اگر این‌ها مقدار پیش‌فرض غیر-None
    # داشته باشند، ذخیره‌ی یک کارت مقدار واقعی کارت دیگر را با پیش‌فرض/خالی
    # رونویسی می‌کند (و حتی می‌تواند به‌غلط خطای «متن خالی» بدهد).
    connect_enabled: Optional[bool] = None
    connect_threshold_mb: Optional[float] = None
    connect_text: Optional[str] = None
    no_connect_enabled: Optional[bool] = None
    no_connect_hours: Optional[int] = None
    no_connect_threshold_mb: Optional[float] = None
    no_connect_text: Optional[str] = None


@app.get("/api/settings/connect-alert")
def api_get_connect_alert_settings(admin=Depends(require_permission("settings"))):
    return db.get_connect_alert_settings()


@app.post("/api/settings/connect-alert")
def api_set_connect_alert_settings(body: ConnectAlertSettingsBody, admin=Depends(require_permission("settings"))):
    if body.connect_threshold_mb is not None and body.connect_threshold_mb <= 0:
        raise HTTPException(400, tr("آستانه‌ی مصرف باید بزرگ‌تر از صفر باشد."))
    if body.no_connect_threshold_mb is not None and body.no_connect_threshold_mb <= 0:
        raise HTTPException(400, tr("آستانه‌ی مصرف باید بزرگ‌تر از صفر باشد."))
    if body.no_connect_hours is not None and body.no_connect_hours <= 0:
        raise HTTPException(400, tr("مهلت هشدار عدم‌اتصال باید بزرگ‌تر از صفر باشد."))
    if body.connect_text is not None and not body.connect_text.strip():
        raise HTTPException(400, tr("متن پیام نمی‌تواند خالی باشد."))
    if body.no_connect_text is not None and not body.no_connect_text.strip():
        raise HTTPException(400, tr("متن پیام نمی‌تواند خالی باشد."))
    db.set_connect_alert_settings(**body.dict(exclude_none=True))
    db.log_admin_action(admin["id"], "setting_change", "connect alert settings updated (پنل وب)", "setting", "connect_alert")
    return {"ok": True}


class EarlyRenewalDiscountBody(BaseModel):
    enabled: bool = False
    days_before: int = 5
    percent: int = 10


@app.get("/api/settings/early-renewal-discount")
def api_get_early_renewal_discount_settings(admin=Depends(require_permission("settings"))):
    return db.get_early_full_renewal_discount_settings()


@app.post("/api/settings/early-renewal-discount")
def api_set_early_renewal_discount_settings(body: EarlyRenewalDiscountBody, admin=Depends(require_permission("settings"))):
    if body.days_before <= 0:
        raise HTTPException(400, tr("تعداد روز باید بزرگ‌تر از صفر باشد."))
    if not (0 < body.percent <= 100):
        raise HTTPException(400, tr("درصد تخفیف باید بین ۱ تا ۱۰۰ باشد."))
    db.set_early_full_renewal_discount_settings(body.enabled, body.days_before, body.percent)
    db.log_admin_action(admin["id"], "setting_change", "early renewal discount settings updated (پنل وب)", "setting", "early_renewal_discount")
    return {"ok": True}


class TestConfigToggleBody(BaseModel):
    enabled: bool


class TestPlanBody(BaseModel):
    name: str
    name_prefix: str
    panel_server_id: int
    volume_mb: int
    duration_hours: int


@app.get("/api/settings/test-config")
def api_get_test_config_settings(admin=Depends(require_permission("settings"))):
    return {
        "enabled": db.get_setting("test_enabled", "1") == "1",
        "bank_stock": db.count_available_test_configs(),
    }


@app.post("/api/settings/test-config")
def api_set_test_config_settings(body: TestConfigToggleBody, admin=Depends(require_permission("settings"))):
    db.set_setting("test_enabled", "1" if body.enabled else "0")
    db.log_admin_action(admin["id"], "setting_change", "test config enabled/disabled (پنل وب)", "setting", "test_config")
    return {"ok": True}


@app.post("/api/settings/test-config/reset-all")
def api_reset_all_test_configs(admin=Depends(require_permission("settings"))):
    """معادل «بازنشانی کانفیگ تست برای همه» در ربات: امکان دریافت مجدد کانفیگ تست برای همه‌ی کاربران."""
    count = db.reset_all_test_usage()
    db.log_admin_action(admin["id"], "test_config_reset_all", f"{count} کاربر (پنل وب - {admin['username']})", "setting", "test_config")
    return {"ok": True, "count": count}


# --- پلن‌های کانفیگ تست (چندمدلی، مثل محصولات) ---

def _serialize_test_plan(p) -> dict:
    server = db.get_panel_server(p["panel_server_id"])
    return {
        "id": p["id"],
        "name": p["name"],
        "name_prefix": p["name_prefix"],
        "panel_server_id": p["panel_server_id"],
        "panel_server_name": server["name"] if server else None,
        "volume_mb": p["volume_mb"],
        "duration_hours": p["duration_hours"],
        "is_active": bool(p["is_active"]),
        "sort_order": p["sort_order"],
    }


@app.get("/api/test-config/panel-servers-lite")
def api_test_config_panel_servers_lite(admin=Depends(require_permission("settings"))):
    """نسخه‌ی مخصوص تنظیمات کانفیگ تست از لیست سبک پنل‌ها، تا نیازی به
    دسترسی «کاتالوگ» برای مدیریت پلن‌های تست نباشد."""
    return [{"id": s["id"], "name": s["name"]} for s in db.get_panel_servers(active_only=True)]


@app.get("/api/test-config/plans")
def api_list_test_plans(admin=Depends(require_permission("settings"))):
    return [_serialize_test_plan(p) for p in db.get_test_config_plans()]


@app.post("/api/test-config/plans")
def api_create_test_plan(body: TestPlanBody, admin=Depends(require_permission("settings"))):
    if not body.name.strip():
        raise HTTPException(400, tr("نام پلن الزامی است."))
    if not re.fullmatch(r"[A-Za-z0-9_]+", body.name_prefix.strip()):
        raise HTTPException(400, tr("پیشوند نام کاربری فقط باید شامل حروف/عدد انگلیسی و آندرلاین باشد."))
    if body.volume_mb <= 0 or body.duration_hours <= 0:
        raise HTTPException(400, tr("حجم و مدت باید بزرگ‌تر از صفر باشند."))
    server = db.get_panel_server(body.panel_server_id)
    if not server or not server["is_active"]:
        raise HTTPException(400, tr("پنل انتخاب‌شده یافت نشد یا غیرفعال است."))
    plan_id = db.create_test_config_plan(
        body.name.strip(), body.name_prefix.strip(), body.panel_server_id, body.volume_mb, body.duration_hours,
    )
    db.log_admin_action(admin["id"], "test_plan_create", f"پلن «{body.name}» (پنل وب)", "test_config_plan", str(plan_id))
    return _serialize_test_plan(db.get_test_config_plan(plan_id))


@app.put("/api/test-config/plans/{plan_id}")
def api_update_test_plan(plan_id: int, body: TestPlanBody, admin=Depends(require_permission("settings"))):
    if not db.get_test_config_plan(plan_id):
        raise HTTPException(404, tr("این پلن یافت نشد."))
    if not body.name.strip():
        raise HTTPException(400, tr("نام پلن الزامی است."))
    if not re.fullmatch(r"[A-Za-z0-9_]+", body.name_prefix.strip()):
        raise HTTPException(400, tr("پیشوند نام کاربری فقط باید شامل حروف/عدد انگلیسی و آندرلاین باشد."))
    if body.volume_mb <= 0 or body.duration_hours <= 0:
        raise HTTPException(400, tr("حجم و مدت باید بزرگ‌تر از صفر باشند."))
    server = db.get_panel_server(body.panel_server_id)
    if not server or not server["is_active"]:
        raise HTTPException(400, tr("پنل انتخاب‌شده یافت نشد یا غیرفعال است."))
    db.update_test_config_plan(
        plan_id, name=body.name.strip(), name_prefix=body.name_prefix.strip(),
        panel_server_id=body.panel_server_id, volume_mb=body.volume_mb, duration_hours=body.duration_hours,
    )
    db.log_admin_action(admin["id"], "test_plan_update", f"پلن #{plan_id} (پنل وب)", "test_config_plan", str(plan_id))
    return _serialize_test_plan(db.get_test_config_plan(plan_id))


@app.post("/api/test-config/plans/{plan_id}/toggle")
def api_toggle_test_plan(plan_id: int, admin=Depends(require_permission("settings"))):
    if not db.get_test_config_plan(plan_id):
        raise HTTPException(404, tr("این پلن یافت نشد."))
    db.toggle_test_config_plan(plan_id)
    db.log_admin_action(admin["id"], "test_plan_toggle", f"پلن #{plan_id} (پنل وب)", "test_config_plan", str(plan_id))
    return _serialize_test_plan(db.get_test_config_plan(plan_id))


@app.delete("/api/test-config/plans/{plan_id}")
def api_delete_test_plan(plan_id: int, admin=Depends(require_permission("settings"))):
    if not db.get_test_config_plan(plan_id):
        raise HTTPException(404, tr("این پلن یافت نشد."))
    db.delete_test_config_plan(plan_id)
    db.log_admin_action(admin["id"], "test_plan_delete", f"پلن #{plan_id} (پنل وب)", "test_config_plan", str(plan_id))
    return {"ok": True}




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
        raise HTTPException(400, tr("برای فعال‌سازی، آیدی کانال الزامی است."))
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
        raise HTTPException(400, tr("آستانه نمی‌تواند منفی باشد."))
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
        raise HTTPException(400, tr("فقط فایل تصویری مجاز است."))
    content = await photo.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(400, tr("حجم تصویر نباید بیشتر از ۲ مگابایت باشد."))
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
        raise HTTPException(400, tr("حداکثر ۲۰ بنر مجاز است."))
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
def api_get_custom_config_settings(admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    return db.get_custom_config_settings()


@app.post("/api/custom-config/settings")
def api_set_custom_config_settings(body: CustomConfigSettingsBody, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    if body.min_gb <= 0 or body.max_gb <= 0 or body.min_gb > body.max_gb:
        raise HTTPException(400, tr("بازه‌ی حجم نامعتبر است."))
    if body.duration_days <= 0:
        raise HTTPException(400, tr("مدت باید بزرگ‌تر از صفر باشد."))
    db.set_setting("custom_config_enabled", "1" if body.enabled else "0")
    db.set_setting("custom_config_min_gb", str(body.min_gb))
    db.set_setting("custom_config_max_gb", str(body.max_gb))
    db.set_setting("custom_config_duration_days", str(body.duration_days))
    db.log_admin_action(admin["id"], "setting_change", "custom config settings updated (پنل وب)", "setting", "custom_config")
    return {"ok": True}


@app.get("/api/custom-config/pricing-tiers")
def api_get_pricing_tiers(admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    return rows_to_list(db.get_pricing_tiers())


class PricingTierBody(BaseModel):
    from_gb: int
    to_gb: Optional[int] = None
    price_per_gb: int


@app.post("/api/custom-config/pricing-tiers")
def api_add_pricing_tier(body: PricingTierBody, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
    if body.from_gb < 0 or body.price_per_gb <= 0:
        raise HTTPException(400, tr("مقادیر نامعتبر است."))
    if body.to_gb is not None and body.to_gb <= body.from_gb:
        raise HTTPException(400, tr("سقف بازه باید بزرگ‌تر از کف بازه باشد."))
    tier_id = db.add_pricing_tier(body.from_gb, body.to_gb, body.price_per_gb)
    db.log_admin_action(admin["id"], "pricing_tier_add", f"{body.from_gb}-{body.to_gb} = {body.price_per_gb} (پنل وب)")
    return {"id": tier_id}


@app.get("/api/custom-config/payment-methods")
def api_get_custom_config_payment_methods(admin=Depends(require_any_permission("settings", "panels")), _fa=Depends(require_full_access_tenant)):
    return {"allowed": db.get_custom_config_payment_methods()}


class CustomConfigPaymentMethodsBody(BaseModel):
    methods: Optional[List[str]] = None


@app.post("/api/custom-config/payment-methods")
def api_set_custom_config_payment_methods(body: CustomConfigPaymentMethodsBody, admin=Depends(require_any_permission("settings", "panels")), _fa=Depends(require_full_access_tenant)):
    valid = {x["key"] for x in db.get_payment_methods_catalog()}
    methods = [m for m in (body.methods or []) if m in valid]
    if body.methods and not methods:
        raise HTTPException(400, tr("روش پرداخت نامعتبر است."))
    db.set_custom_config_payment_methods(methods or None)
    db.log_admin_action(admin["id"], "custom_config_payment_methods",
                        f"{methods or 'همه'} (پنل وب - {admin['username']})",
                        "setting", "custom_config_payment_methods")
    return {"ok": True}


@app.delete("/api/custom-config/pricing-tiers/{tier_id}")
def api_delete_pricing_tier(tier_id: int, admin=Depends(require_permission("panels")), _fa=Depends(require_full_access_tenant)):
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
            # این دو فیلد برای این‌است که تب «دکمه‌های ربات» بتواند متن/رنگ این
            # دکمه‌ها را هم از همین‌جا (کنار ترتیب/فعال‌سازی) نمایش و ویرایش کند.
            "has_text": bool(meta.get("has_text")),
            "has_style": bool(meta.get("has_style")),
        }
        if meta["toggle_key"]:
            item["enabled"] = settings.get(meta["toggle_key"], "1") == "1"
        if meta.get("has_text"):
            item["text"] = settings.get(key, meta.get("default_text") or "")
        if meta.get("has_style"):
            item["style"] = settings.get(f"{key}_style", "")
        # break_before یعنی این دکمه یک ردیف تازه در منو شروع می‌کند (کنار دکمه‌ی
        # قبلی‌اش قرار نمی‌گیرد). اگر کاربر هنوز چیدمان سفارشی نساخته باشد
        # (break_set is None)، null برمی‌گردد تا فرانت‌اند بداند هنوز از حالت
        # قدیمی «تعداد ستون ثابت» استفاده می‌شود.
        item["break_before"] = (key in break_set) if break_set is not None else None
        result.append(item)
    return result


class MenuButtonToggle(BaseModel):
    key: str
    enabled: Optional[bool] = None
    text: Optional[str] = None
    style: Optional[str] = None


def _apply_menu_button_toggles(buttons: Optional[list[MenuButtonToggle]]):
    for btn in buttons or []:
        meta = MENU_BUTTON_META.get(btn.key)
        if not meta:
            continue
        if meta["toggle_key"] and btn.enabled is not None:
            db.set_setting(meta["toggle_key"], "1" if btn.enabled else "0")
        if btn.text is not None and meta.get("has_text"):
            text = btn.text.strip()
            if text:
                db.set_setting(btn.key, text)
        if btn.style is not None and meta.get("has_style") and btn.style in button_registry.STYLE_CHOICES:
            db.set_setting(f"{btn.key}_style", btn.style)


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


# --------------------------------------------------- تب مستقل «دکمه‌های ربات» --
# رجیستری عمومی کاستوم‌سازی دکمه‌ها (button_registry.py): پنل مدیریت، مسیر
# خرید، حساب کاربری، روش‌های پرداخت + درگاه‌های سفارشی. منوی اصلی بات از قبل
# ویرایشگر مخصوص خودش را دارد (بالاتر: /api/settings/menu-order|menu-layout)
# و عمداً اینجا تکرار نشده.


@app.get("/api/buttons")
def api_buttons_registry(admin=Depends(require_permission("settings"))):
    return button_registry.build_registry(db)


class ButtonItemUpdateBody(BaseModel):
    group: str
    key: str
    text: Optional[str] = None
    style: Optional[str] = None


@app.post("/api/buttons/item")
def api_buttons_update_item(body: ButtonItemUpdateBody, admin=Depends(require_permission("settings"))):
    try:
        button_registry.update_item(db, body.group, body.key, text=body.text, style=body.style)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log_admin_action(
        admin["id"], "button_customize",
        f"دکمه‌ی «{body.key}» در گروه «{body.group}» ویرایش شد (پنل وب - {admin['username']})",
        "setting", f"{body.group}:{body.key}",
    )
    return {"ok": True}


class ButtonOrderUpdateBody(BaseModel):
    group: str
    order: list[str]


@app.post("/api/buttons/order")
def api_buttons_update_order(body: ButtonOrderUpdateBody, admin=Depends(require_permission("settings"))):
    try:
        button_registry.update_order(db, body.group, body.order)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log_admin_action(
        admin["id"], "button_reorder",
        f"ترتیب گروه «{body.group}» تغییر کرد (پنل وب - {admin['username']})",
        "setting", body.group,
    )
    return {"ok": True}


# ------------------------------------------------------- main menu display --
# این سه تنظیم با «ترتیب منو»/«چیدمان منو» بالا فرق دارند: آن‌ها ترتیب و
# گروه‌بندی آیتم‌های منو را کنترل می‌کنند، این‌ها نوع نمایش منو (Reply در
# مقابل Inline) و چیدمان فیزیکی دکمه‌ها (تعداد دکمه در هر ردیف) را کنترل
# می‌کنند - معادل adm_main_menu_settings در ربات.


@app.get("/api/settings/main-menu-display")
def api_main_menu_display_get(admin=Depends(require_permission("settings"))):
    return {
        "reply_enabled": db.get_setting("main_menu_reply_enabled", "1") == "1",
        "inline_enabled": db.get_setting("main_menu_inline_enabled", "0") == "1",
        "columns": int(db.get_setting("main_menu_columns", "1") or "1"),
    }


class MainMenuDisplayBody(BaseModel):
    reply_enabled: bool
    inline_enabled: bool
    columns: int


@app.post("/api/settings/main-menu-display")
def api_main_menu_display_set(body: MainMenuDisplayBody, admin=Depends(require_permission("settings"))):
    # قانون محافظتی: هردو منو همزمان نباید خاموش باشند وگرنه کاربر هیچ راهی
    # برای پیمایش منو نخواهد داشت (همان چکی که در ربات هم هست).
    if not body.reply_enabled and not body.inline_enabled:
        raise HTTPException(400, tr("حداقل یکی از منوی پایین یا منوی شیشه‌ای بالا باید فعال باشد."))
    if body.columns not in (1, 2):
        raise HTTPException(400, tr("چیدمان باید ۱ یا ۲ ستون باشد."))

    db.set_setting("main_menu_reply_enabled", "1" if body.reply_enabled else "0")
    db.set_setting("main_menu_inline_enabled", "1" if body.inline_enabled else "0")
    db.set_setting("main_menu_columns", str(body.columns))
    db.log_admin_action(
        admin["id"], "main_menu_display_change",
        f"نمایش منوی اصلی تغییر کرد: Reply={'روشن' if body.reply_enabled else 'خاموش'}, "
        f"Inline={'روشن' if body.inline_enabled else 'خاموش'}, ستون={body.columns} (پنل وب - {admin['username']})",
        "setting", "main_menu_display",
    )
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
        raise HTTPException(400, tr("این یوزرنیم قبلاً استفاده شده."))
    if len(body.password) < 8:
        raise HTTPException(400, tr("پسورد باید حداقل ۸ کاراکتر باشد."))
    new_id = db.create_web_admin(body.username, hash_password(body.password), body.role, body.permissions)
    db.log_admin_action(admin["id"], "web_admin_add", f"{body.username} ({body.role})", "webadmin", new_id)
    return {"id": new_id}


class WebAdminRoleBody(BaseModel):
    role: str


@app.post("/api/web-admins/{admin_id}/role")
def api_set_web_admin_role(admin_id: int, body: WebAdminRoleBody, admin=Depends(require_owner)):
    if not db.set_web_admin_role(admin_id, body.role):
        raise HTTPException(400, tr("امکان تغییر نقش این حساب نیست."))
    return {"ok": True}


class WebAdminPermissionsBody(BaseModel):
    permissions: list


@app.post("/api/web-admins/{admin_id}/permissions")
def api_set_web_admin_permissions(admin_id: int, body: WebAdminPermissionsBody, admin=Depends(require_owner)):
    if not db.set_web_admin_permissions(admin_id, body.permissions):
        raise HTTPException(400, tr("امکان تغییر مجوزهای این حساب نیست."))
    db.log_admin_action(admin["id"], "web_admin_permissions", f"admin#{admin_id} -> {body.permissions}", "webadmin", admin_id)
    return {"ok": True}


class WebAdminActiveBody(BaseModel):
    active: bool


@app.post("/api/web-admins/{admin_id}/active")
def api_set_web_admin_active(admin_id: int, body: WebAdminActiveBody, admin=Depends(require_owner)):
    if not db.set_web_admin_active(admin_id, body.active):
        raise HTTPException(400, tr("امکان تغییر وضعیت این حساب نیست."))
    db.log_admin_action(admin["id"], "web_admin_active", f"admin#{admin_id} -> {body.active}", "webadmin", admin_id)
    return {"ok": True}


@app.delete("/api/web-admins/{admin_id}")
def api_delete_web_admin(admin_id: int, admin=Depends(require_owner)):
    if not db.delete_web_admin(admin_id):
        raise HTTPException(400, tr("امکان حذف این حساب نیست."))
    db.log_admin_action(admin["id"], "web_admin_delete", f"admin#{admin_id}", "webadmin", admin_id)
    return {"ok": True}


# ------------------------------------------------------- telegram admins ---
# ادمین‌های تلگرامی ربات (جدول admins، بر اساس آیدی عددی) - جدا از وب‌ادمین‌ها
# که برای لاگین به همین پنل وب هستند.

TG_ADMIN_ROLES = ("admin", "mid", "support")


@app.get("/api/telegram-admins")
def api_telegram_admins(admin=Depends(require_owner)):
    return db.list_admins_with_roles()


class TelegramAdminAddBody(BaseModel):
    telegram_id: int
    role: str = "admin"


@app.post("/api/telegram-admins")
def api_add_telegram_admin(body: TelegramAdminAddBody, admin=Depends(require_owner)):
    if body.role not in TG_ADMIN_ROLES:
        raise HTTPException(400, tr("نقش نامعتبر است."))
    if db.get_admin_role(body.telegram_id):
        raise HTTPException(400, tr("این کاربر از قبل ادمین است."))
    db.add_admin(body.telegram_id, body.role)
    db.log_admin_action(admin["id"], "tg_admin_add", f"{body.telegram_id} ({body.role})", "tg_admin", str(body.telegram_id))
    return {"ok": True}


class TelegramAdminRoleBody(BaseModel):
    role: str


@app.post("/api/telegram-admins/{telegram_id}/role")
def api_set_telegram_admin_role(telegram_id: int, body: TelegramAdminRoleBody, admin=Depends(require_owner)):
    if body.role not in TG_ADMIN_ROLES:
        raise HTTPException(400, tr("نقش نامعتبر است."))
    if not db.set_admin_role(telegram_id, body.role):
        raise HTTPException(400, tr("امکان تغییر نقش این کاربر نیست (شاید مالک اصلی باشد یا اصلاً ادمین نباشد)."))
    db.log_admin_action(admin["id"], "tg_admin_role", f"{telegram_id} -> {body.role}", "tg_admin", str(telegram_id))
    return {"ok": True}


@app.delete("/api/telegram-admins/{telegram_id}")
def api_remove_telegram_admin(telegram_id: int, admin=Depends(require_owner)):
    if not db.remove_admin(telegram_id, protected_owner_id=OWNER_ID):
        raise HTTPException(400, tr("امکان حذف این کاربر نیست (شاید مالک اصلی باشد یا اصلاً ادمین نباشد)."))
    db.log_admin_action(admin["id"], "tg_admin_remove", str(telegram_id), "tg_admin", str(telegram_id))
    return {"ok": True}


# ---------------------------------------------------------- orphan db files --
# فایل‌های .db داخل پوشه‌ی reseller_dbs که هیچ رکورد نماینده‌ای (حتی حذف‌شده)
# در جدول reseller_bots به مسیرشان اشاره نمی‌کند.

def _find_orphan_reseller_db_files():
    if not os.path.isdir(RESELLER_DBS_DIR):
        return []
    referenced = set()
    for r in db.list_reseller_bots():
        try:
            referenced.add(os.path.normcase(os.path.abspath(resolve_db_path(r["db_path"]))))
        except Exception:
            continue
    orphans = []
    try:
        disk_files = sorted(os.listdir(RESELLER_DBS_DIR))
    except OSError:
        return []
    for fname in disk_files:
        if not fname.endswith(".db"):
            continue
        full_path = os.path.normcase(os.path.abspath(os.path.join(RESELLER_DBS_DIR, fname)))
        if full_path not in referenced:
            size = 0
            try:
                size = os.path.getsize(os.path.join(RESELLER_DBS_DIR, fname))
            except OSError:
                pass
            orphans.append({"filename": fname, "size": size})
    return orphans


@app.get("/api/orphan-db-files")
def api_orphan_db_files(admin=Depends(require_permission("system"))):
    return _find_orphan_reseller_db_files()


@app.delete("/api/orphan-db-files/{filename}")
def api_delete_orphan_db_file(filename: str, admin=Depends(require_permission("system"))):
    # ضدضربه: فقط اجازه‌ی حذف فایل مستقیماً داخل پوشه‌ی reseller_dbs را بده،
    # نه هر مسیر دلخواهی (جلوگیری از path traversal).
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(400, tr("نام فایل نامعتبر است."))
    orphan_names = {o["filename"] for o in _find_orphan_reseller_db_files()}
    if filename not in orphan_names:
        raise HTTPException(400, tr("این فایل یتیم نیست یا وجود ندارد."))
    full_path = os.path.join(RESELLER_DBS_DIR, filename)
    try:
        os.remove(full_path)
    except OSError as e:
        raise HTTPException(500, tr(f"حذف فایل ناموفق بود: {e}"))
    db.log_admin_action(admin["id"], "orphan_db_delete", filename, "orphan_db", filename)
    return {"ok": True}


class MyPasswordBody(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/me/password")
def api_change_my_password(body: MyPasswordBody, admin=Depends(get_current_admin)):
    row = db.get_web_admin(admin["id"])
    if not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(400, tr("پسورد فعلی اشتباه است."))
    if len(body.new_password) < 8:
        raise HTTPException(400, tr("پسورد جدید باید حداقل ۸ کاراکتر باشد."))
    db.set_web_admin_password(admin["id"], hash_password(body.new_password))
    return {"ok": True}


# ------------------------------------------------------------------ static --

STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/assets", NoCacheStaticFiles(directory=STATIC_DIR), name="assets")


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

    # رنگ اسپلش‌اسکرین/نوار وضعیت باید با تم و حالت روشن/تیره‌ی فعلی کاربر
    # هماهنگ باشد؛ index.html این دو را به‌صورت کوئری‌استرینگ می‌فرستد.
    # فقط تم اندروید حالت روشن پیش‌فرض دارد، بقیه‌ی تم‌ها تیره‌اند.
    theme = request.query_params.get("theme", "").strip()
    mode = request.query_params.get("mode", "").strip()
    android_colors = {"light": "#FEF7FF", "dark": "#141218"}
    pwa_color = android_colors.get(mode, "#141218") if theme == "android" else "#0B0C14"

    manifest = {
        "name": "پنل مدیریت ShopVPN",
        "short_name": "ShopVPN",
        "description": "پنل مدیریت وب ShopVPN",
        "start_url": start_url,
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": pwa_color,
        "theme_color": pwa_color,
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


def _asset_version(filename: str) -> str:
    return file_digest(os.path.join(STATIC_DIR, filename))


def _bust_asset_cache(html: str) -> str:
    html = html.replace('src="/assets/app.js"', f'src="/assets/app.js?v={_asset_version("app.js")}"')
    html = html.replace('href="/assets/style.css"', f'href="/assets/style.css?v={_asset_version("style.css")}"')
    html = html.replace("{{ASSET_VERSION}}", static_version(STATIC_DIR))
    return html


@app.get("/api/app-version")
def app_version():
    return {"v": static_version(STATIC_DIR)}


@app.get("/", response_class=HTMLResponse)
def serve_index():
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    # کش‌شکن خودکار: هر بار app.js عوض شود mtime آن هم عوض می‌شود، پس
    # مرورگر دیگر نسخه‌ی قدیمیِ کش‌شده را اجرا نمی‌کند و مجبور به دانلود
    # مجدد است — بدون نیاز به دستی زیاد کردن شماره‌ی ورژن در هر دیپلوی.
    html = _bust_asset_cache(html)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/setup", response_class=HTMLResponse)
def serve_setup_page():
    """همان SPA سرو می‌شود؛ خود فرانت مسیر /setup را تشخیص داده و فرم راه‌اندازی
    اولیه‌ی پنل نماینده را نشان می‌دهد."""
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    html = _bust_asset_cache(html)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})

