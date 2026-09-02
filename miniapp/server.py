# -*- coding: utf-8 -*-
"""
بک‌اند مینی‌اپ - چندمستأجر (Multi-tenant)

یک سرور واحد، هم برای بات اصلی و هم برای همه‌ی بات‌های نمایندگی.
شناسه‌ی نماینده از طریق کوئری‌پارامتر ?b=<reseller_id> در URL مینی‌اپ مشخص
می‌شود (که هنگام ساخت دکمه‌ی مینی‌اپ در keyboards.py به‌صورت خودکار اضافه می‌شود).
اگر ?b وجود نداشته باشد یا خالی/۰ باشد، یعنی بات اصلی.

هر درخواست بر اساس همین شناسه، دیتابیس و توکن بات درست را resolve می‌کند؛
یعنی هر نماینده کاملاً مستقل و ایزوله (دیتابیس خودش) از مینی‌اپ استفاده می‌کند.

اجرا (جدا از پروسه‌ی اصلی بات): uvicorn miniapp.server:app --host 127.0.0.1 --port 8001
سپس nginx مسیر / را به این پورت proxy می‌کند.
"""

import sys
import os
import json
import hmac
import hashlib
import random
import re
import secrets
import base64
import html as html_lib
import asyncio
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form, Depends, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import logging
import sqlite3

logging.basicConfig(level=logging.INFO)

from config import BOT_TOKEN, DB_PATH, OWNER_ID, MAX_TEST_PER_USER, resolve_db_path, RESELLER_DBS_DIR, MINIAPP_URL, API_BASE_URL, PLISIO_API_KEY
import plisio_client
import exchange_rate
import crypto_payment
import abangateway_client
import abangateway_payment
import payment_engine
import card_to_card_payment
from database import Database, MENU_BUTTON_META, DEFAULT_MENU_ORDER
from admin_panel.config_delivery_web import deliver_config_to_user_web
from miniapp.auth import validate_init_data
from sub_info import fetch_sub_info
from backup import create_backup, restore_backup, is_valid_sqlite_db
from jalali import to_jalali_str
from stock_alerts import check_and_notify_low_stock
from panel_providers import (
    get_provider, PanelError, PanelUsernameTakenError, PROVIDERS,
    SUB_BASE_URL_PANEL_TYPES, INBOUND_SELECT_PANEL_TYPES, parse_xui_inbound_ids,
)
from reseller_auto_provision import provision_auto_config, provision_test_config, ProvisionError
from test_config_provision import provision_test_plan, format_plan_amount, ProvisionError as TestPlanProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from renewal_engine import execute_renewal, RenewalError
from admin_panel.telegram_notify import send_message as _tg_notify, fetch_telegram_file as _tg_fetch_file

app = FastAPI(title="V2Ray Shop Mini App API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# تم‌های قابل انتخاب برای مینی‌اپ (هر تننت/نماینده جدا انتخاب می‌کند)
MINIAPP_THEMES = {
    "clean-light": "🌿 مینیمال روشن (پیش‌فرض)",
    "synthwave": "🌅 سینت‌ویو",
    "neon-mint": "🟢 نئون مینت",
    "royal-violet": "👑 بنفش سلطنتی",
    "blood-moon": "🔴 ماه خونین",
    "aurora-ice": "🧊 یخ شمالی",
}
MAX_HEADER_IMAGE_BYTES = 2 * 1024 * 1024  # 2 مگابایت

# دیتابیس بات اصلی - هم برای سرویس‌دهی مستقیم به بات اصلی، هم برای پیدا کردن
# دیتابیس/توکن بات‌های نمایندگی از روی جدول reseller_bots استفاده می‌شود.
main_db = Database(DB_PATH)
try:
    # اگر این پروسه (uvicorn مینی‌اپ) قبل از بات اصلی اجرا شده و فایل دیتابیس
    # هنوز جدول ندارد، این‌جا هم می‌سازیمش تا هیچ درخواستی با خطای ۵۰۰ مواجه نشود.
    main_db.init_db(owner_id=OWNER_ID)
except Exception:
    logging.getLogger("miniapp.tenant").exception("مقداردهی اولیه دیتابیس اصلی ناموفق بود.")

_bot_username_cache: dict[str, str] = {}  # bot_token -> username


# ---------------------------------------------------------------------------
# تشخیص مستأجر (بات اصلی یا یک نماینده‌ی مشخص)
# ---------------------------------------------------------------------------

@dataclass
class Tenant:
    db: Database
    bot_token: str
    tenant_id: str  # "" برای بات اصلی، در غیر این صورت id عددی نماینده به‌صورت رشته


_tenant_logger = logging.getLogger("miniapp.tenant")


def get_tenant(b: str = Query("", description="شناسه یا اسلاگ لینک نماینده؛ خالی یعنی بات اصلی")) -> Tenant:
    b = (b or "").strip()
    if not b or b == "0":
        return Tenant(db=main_db, bot_token=BOT_TOKEN, tenant_id="")

    try:
        if b.isdigit():
            row = main_db.get_reseller_bot(int(b))
        else:
            row = main_db.get_reseller_bot_by_slug(b)
    except sqlite3.OperationalError:
        _tenant_logger.exception(
            "خطای دیتابیس اصلی هنگام خواندن reseller_bots (b=%s). db_path=%s - احتمالاً جدول‌ها هنوز ساخته نشده‌اند.",
            b, DB_PATH,
        )
        raise HTTPException(status_code=503, detail="سرور موقتاً در دسترس نیست، دوباره تلاش کنید.")

    if not row or not row["is_active"]:
        _tenant_logger.warning(
            "تننت b=%s پیدا نشد یا غیرفعال است. row=%s", b, dict(row) if row else None
        )
        raise HTTPException(status_code=404, detail="این فروشگاه در دسترس نیست.")

    resolved_path = resolve_db_path(row["db_path"])
    if not os.path.exists(resolved_path):
        _tenant_logger.error(
            "تننت b=%s معتبر است ولی فایل دیتابیسش پیدا نشد. stored_path=%s resolved_path=%s",
            b, row["db_path"], resolved_path,
        )
        raise HTTPException(status_code=503, detail="دیتابیس این فروشگاه در دسترس نیست.")

    tenant_db = Database(resolved_path)
    try:
        tenant_db.get_all_settings()
    except sqlite3.OperationalError:
        _tenant_logger.exception(
            "تننت b=%s: خواندن settings از %s ناموفق بود (جدول‌ها ساخته نشده؟).", b, resolved_path
        )
        raise HTTPException(status_code=503, detail="دیتابیس این فروشگاه هنوز آماده نیست.")

    _tenant_logger.info(
        "تننت b=%s resolve شد -> bot_username=%s token=...%s db_path=%s",
        b, row["bot_username"], row["bot_token"][-6:], resolved_path,
    )
    return Tenant(db=tenant_db, bot_token=row["bot_token"], tenant_id=b)


def get_verified_user(x_init_data: str = Header(...), tenant: Tenant = Depends(get_tenant)):
    """initData را با توکن همان مستأجر تایید می‌کند. خروجی: (tg_id, db, tenant)

    نکته: کاربر را همین‌جا هم در جدول users ثبت/به‌روز می‌کنیم (نه فقط داخل
    هندلر /start بات)، چون کاربر می‌تواند مستقیماً وارد مینی‌اپ شود بدون آن‌که
    قبلاً /start را در بات زده باشد. بدون این کار، پیام‌های چت زنده/تیکت چنین
    کاربری در دیتابیس ثبت می‌شد ولی چون ردیفی در users نداشت، سمت ادمین
    (هم مینی‌اپ و هم پنل وب) با خطای «کاربر یافت نشد» مواجه می‌شد."""
    result = validate_init_data(x_init_data, tenant.bot_token)
    if not result or "user" not in result:
        raise HTTPException(status_code=401, detail="initData نامعتبر است.")
    tg_user = result["user"]
    try:
        tenant.db.add_or_update_user(tg_user["id"], tg_user.get("username"), tg_user.get("first_name"))
    except Exception:
        logging.getLogger("miniapp.auth").exception("ثبت/به‌روزرسانی کاربر %s ناموفق بود.", tg_user.get("id"))
    return tg_user["id"], tenant.db, tenant


def require_admin(auth=Depends(get_verified_user)):
    """مثل get_verified_user، ولی فقط اگر کاربر ادمین همان مستأجر باشد اجازه می‌دهد.
    همچنین حضور آنلاین ادمین را ثبت می‌کند (برای مسیریابی چت زنده به اولین ادمین آنلاین)."""
    tg_id, db, tenant = auth
    if not db.is_admin(tg_id):
        raise HTTPException(status_code=403, detail="دسترسی ادمین لازم است.")
    db.touch_admin_presence(tg_id)
    return auth


def require_full_admin(auth=Depends(get_verified_user)):
    """مثل require_admin، ولی نقش «پشتیبان» را رد می‌کند؛ مالک، مدیر کامل یا ادمین میانی."""
    tg_id, db, tenant = auth
    if not db.is_full_admin(tg_id):
        raise HTTPException(status_code=403, detail="این بخش فقط برای مدیران کامل در دسترس است.")
    db.touch_admin_presence(tg_id)
    return auth


def require_senior_admin(auth=Depends(get_verified_user)):
    """مثل require_full_admin، ولی نقش «ادمین میانی» را هم رد می‌کند؛ فقط مالک یا مدیر کامل
    (برای بخش‌های حساس: آمار فروش، چیدمان منو، تنظیمات کمپین‌ها/تخفیف، لاگ ادمین، نمایندگی‌ها)."""
    tg_id, db, tenant = auth
    if not db.is_senior_admin(tg_id):
        raise HTTPException(status_code=403, detail="این بخش فقط برای مالک و مدیر کامل در دسترس است.")
    return auth


def require_full_access_admin(auth=Depends(get_verified_user)):
    """مثل require_senior_admin، ولی علاوه بر آن بات‌های نمایندگیِ سطح ۲ (محدود) را هم رد می‌کند؛
    اتصال پنل VPN و ساخت کانفیگ دستی فقط برای بات اصلی و نمایندگی سطح کامل مجاز است."""
    tg_id, db, tenant = auth
    if not db.is_senior_admin(tg_id):
        raise HTTPException(status_code=403, detail="این بخش فقط برای مالک و مدیر کامل در دسترس است.")
    if not db.is_full_access_bot(not tenant.tenant_id):
        raise HTTPException(status_code=403, detail="⛔️ اتصال پنل VPN و ساخت کانفیگ دستی فقط از طریق بات اصلی یا نمایندگی کامل مدیریت می‌شود.")
    return auth


def require_main_admin(auth=Depends(get_verified_user)):
    """مدیریت بات‌های نمایندگی: فقط مالک یا مدیر کامل بات اصلی (نه ادمین میانی/پشتیبان،
    نه بات‌های نمایندگی)."""
    tg_id, db, tenant = auth
    if tenant.tenant_id:
        raise HTTPException(status_code=403, detail="این بخش فقط در بات اصلی در دسترس است.")
    if not db.is_senior_admin(tg_id):
        raise HTTPException(status_code=403, detail="این بخش فقط برای مالک و مدیر کامل در دسترس است.")
    return auth


def require_owner(auth=Depends(get_verified_user)):
    """فقط مالک اصلی همان مستأجر (بات اصلی یا همان نماینده)؛ برای عملیات حساس
    مثل بازیابی کامل دیتابیس."""
    tg_id, db, tenant = auth
    if not db.is_owner(tg_id):
        raise HTTPException(status_code=403, detail="این بخش فقط برای مالک بات در دسترس است.")
    return auth


# ---------------------------------------------------------------------------
# عضویت اجباری در کانال - هماهنگ با force_join.py که در ربات اصلی اجرا می‌شود.
# در ربات این چک قبل از هر هندلر (میدل‌ور) اجرا می‌شود؛ این‌جا هم باید همان
# منطق قبل از هر اکشن نوشتنی (خرید/تاپ‌آپ/کانفیگ تست/گردونه) اجرا شود تا
# کاربر نتواند صرفاً با استفاده از مینی‌اپ این محدودیت را دور بزند.
async def _is_channel_member_http(bot_token: str, channel: str, tg_id: int) -> bool:
    """مثل force_join.is_channel_member ولی بدون وابستگی به شیء Bot آیوگرم
    (چون این پروسه‌ی fastapi جدا از پروسه‌ی بات است)؛ fail-open در صورت خطا."""
    if not bot_token:
        return True
    url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params={"chat_id": channel, "user_id": tg_id},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                data = await resp.json()
    except Exception:
        logging.getLogger("miniapp.forcejoin").exception("بررسی عضویت کانال ناموفق بود.")
        return True
    if not data.get("ok"):
        return True
    status = (data.get("result") or {}).get("status")
    return status not in ("left", "kicked")


async def _force_join_check(tg_id: int, db: Database, tenant: "Tenant"):
    """اگر عضویت لازم باشد و کاربر عضو نباشد، خطای ۴۰۳ با جزئیات کانال می‌دهد."""
    settings = db.get_force_join_settings()
    if not settings.get("enabled") or not settings.get("channel"):
        return
    if db.is_admin(tg_id):
        return
    member = await _is_channel_member_http(tenant.bot_token, settings["channel"], tg_id)
    if member:
        return
    channel_display = str(settings["channel"]).lstrip("@")
    raise HTTPException(
        status_code=403,
        detail={
            "code": "force_join",
            "message": "برای ادامه، ابتدا باید در کانال زیر عضو شوید.",
            "channel": settings["channel"],
            "join_link": f"https://t.me/{channel_display}",
        },
    )


async def require_joined(auth=Depends(get_verified_user)):
    """مثل get_verified_user، به‌علاوه‌ی چک عضویت اجباری کانال - برای همه‌ی
    اکشن‌های نوشتنی/خرید (سفارش، تاپ‌آپ، کانفیگ تست، گردونه، کانفیگ شخصی)."""
    tg_id, db, tenant = auth
    await _force_join_check(tg_id, db, tenant)
    return auth


@app.get("/api/force-join-status")
async def api_force_join_status(auth=Depends(get_verified_user)):
    """فرانت قبل از نمایش دکمه‌های خرید، این را چک می‌کند تا در صورت لزوم
    بنر عضویت در کانال را نشان دهد (هم‌تراز با رفتار ربات اصلی)."""
    tg_id, db, tenant = auth
    settings = db.get_force_join_settings()
    if not settings.get("enabled") or not settings.get("channel") or db.is_admin(tg_id):
        return {"required": False, "member": True}
    member = await _is_channel_member_http(tenant.bot_token, settings["channel"], tg_id)
    channel_display = str(settings["channel"]).lstrip("@")
    return {
        "required": True, "member": member,
        "channel": settings["channel"], "join_link": f"https://t.me/{channel_display}",
    }


async def get_bot_username(tenant: Tenant) -> str:
    """یوزرنیم همان بات (برای ساخت لینک دعوت زیرمجموعه‌گیری) را می‌گیرد و کش می‌کند."""
    cached = _bot_username_cache.get(tenant.bot_token)
    if cached:
        return cached
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{tenant.bot_token}/getMe") as resp:
                data = await resp.json()
                if data.get("ok"):
                    _bot_username_cache[tenant.bot_token] = data["result"]["username"]
    except Exception:
        pass
    return _bot_username_cache.get(tenant.bot_token, "")


# ---------------------------------------------------------------------------
# فایل‌های استاتیک
# ---------------------------------------------------------------------------

def get_asset_version() -> str:
    """نسخه‌ی خودکار برای cache-busting، بر اساس آخرین زمان تغییر فایل‌های استاتیک."""
    try:
        mtimes = [
            os.path.getmtime(os.path.join(STATIC_DIR, "style.css")),
            os.path.getmtime(os.path.join(STATIC_DIR, "app.js")),
        ]
        return str(int(max(mtimes)))
    except OSError:
        return "1"


@app.get("/", response_class=HTMLResponse)
def serve_index(tenant: Tenant = Depends(get_tenant)):
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    version = get_asset_version()
    html = html.replace("{{VERSION}}", version)

    store_name = tenant.db.get_setting("store_name", "⚡ SHOP VPN")
    banner_text = tenant.db.get_setting("miniapp_banner_text", "اتصال امن و پایدار برقرار است")
    html = html.replace("{{STORE_NAME}}", html_lib.escape(store_name))
    html = html.replace("{{BANNER_TEXT}}", html_lib.escape(banner_text))

    theme = tenant.db.get_setting("miniapp_theme", "clean-light")
    if theme not in MINIAPP_THEMES:
        theme = "clean-light"
    html = html.replace("{{THEME}}", theme)

    header_image = tenant.db.get_setting("header_image_data", "")
    if header_image:
        html = html.replace("{{HEADER_LOGO_CLASS}}", "has-logo")
        html = html.replace("{{HEADER_LOGO_HTML}}", f'<img class="brand-logo" src="{header_image}" alt="" />')
    else:
        html = html.replace("{{HEADER_LOGO_CLASS}}", "")
        html = html.replace("{{HEADER_LOGO_HTML}}", "")

    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# حساب کاربری
# ---------------------------------------------------------------------------

@app.get("/api/me")
def api_me(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    user = db.get_user(tg_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد. ابتدا /start را در بات بزنید.")
    wallet = db.get_wallet_credit(tg_id)
    referral = db.get_referral_stats(tg_id)
    orders = db.get_user_orders(tg_id)
    return {
        "telegram_id": tg_id,
        "first_name": user["first_name"],
        "username": user["username"] if "username" in user.keys() else None,
        "joined_at": user["joined_at"] if "joined_at" in user.keys() else None,
        "wallet_credit": wallet,
        "referral_count": referral["count"],
        "orders_count": len(orders),
        "is_admin": db.is_admin(tg_id),
        "admin_role": db.get_admin_role(tg_id),
    }


@app.get("/api/orders")
def api_orders(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    orders = db.get_user_orders(tg_id)
    result = []
    for o in orders:
        if o["is_custom_config"]:
            result.append({
                "id": o["id"],
                "product_name": f"کانفیگ شخصی «{o['custom_username']}» ({o['custom_volume_gb']} گیگ)",
                "quantity": 1,
                "status": o["status"],
                "final_price": o["final_price"],
                "expires_at": None,
                "link": None,
                "links": [],
                "is_custom_config": True,
            })
            continue
        product = db.get_product(o["product_id"])
        cfg = db.get_config_by_id(o["config_id"]) if o["config_id"] else None
        configs = db.get_order_configs(o["id"]) if o["status"] == "approved" else []
        links = [c["link"] for c in configs] if configs else ([cfg["link"]] if cfg else [])
        config_ids = [c["id"] for c in configs] if configs else ([cfg["id"]] if cfg else [])
        result.append({
            "id": o["id"],
            "product_name": product["name"] if product else "نامشخص",
            "quantity": o["quantity"] or 1,
            "status": o["status"],
            "final_price": o["final_price"],
            "expires_at": cfg["expires_at"] if cfg else None,
            "link": cfg["link"] if cfg else None,
            "links": links,
            "config_ids": config_ids,
            "is_custom_config": False,
        })
    return result


@app.delete("/api/orders/configs/{config_id}")
def api_delete_order_config(config_id: int, auth=Depends(get_verified_user)):
    """حذف کامل و برگشت‌ناپذیر یک کانفیگ محصول متعلق به خود کاربر. اگر با این
    حذف، سفارش دیگر هیچ کانفیگی نداشته باشد، آن سفارش هم از لیست کاربر مخفی
    می‌شود (این حذف در بات اصلی هم همزمان اعمال می‌شود چون هر دو از یک
    دیتابیس می‌خوانند)."""
    tg_id, db, _ = auth
    removed = db.delete_owned_config(config_id, tg_id)
    if not removed:
        raise HTTPException(status_code=404, detail="کانفیگ یافت نشد یا متعلق به شما نیست.")
    return {"status": "ok"}


@app.get("/api/custom-configs")
def api_custom_configs(auth=Depends(get_verified_user)):
    """کانفیگ‌های ساخته‌شده مستقیم روی پنل VPN (خرید شخصی/کانفیگ تست پنلی).
    کانفیگ‌های تست هم اینجا برمی‌گردند (is_test=True) تا در «سرویس‌های من» دیده
    شوند، ولی فرانت باید برایشان اکشن‌های سرویس خریداری‌شده (تمدید و مشابه) را
    نمایش ندهد."""
    tg_id, db, _ = auth
    configs = db.get_custom_configs_for_user(tg_id)
    return [
        {
            "id": c["id"],
            "username": c["username"],
            "volume_gb": c["volume_gb"],
            "duration_days": c["duration_days"],
            "subscription_url": c["subscription_url"],
            "created_at": c["created_at"],
            "expires_at": c["expires_at"],
            "is_test": c["source"] == "test",
        }
        for c in configs
    ]


@app.delete("/api/custom-configs/{custom_config_id}")
async def api_delete_custom_config(custom_config_id: int, auth=Depends(get_verified_user)):
    """حذف کامل و برگشت‌ناپذیر یک کانفیگ شخصی متعلق به خود کاربر؛ قبل از حذف از
    دیتابیس، تلاش می‌شود کاربر از روی پنل VPN هم حذف شود (best-effort - در
    صورت خطا در ارتباط با پنل، رکورد همچنان از لیست کاربر حذف می‌شود)."""
    tg_id, db, _ = auth
    rows = db.get_custom_configs_for_user(tg_id)
    cc_row = next((c for c in rows if c["id"] == custom_config_id), None)
    if not cc_row:
        raise HTTPException(status_code=404, detail="کانفیگ یافت نشد یا متعلق به شما نیست.")
    if cc_row["panel_server_id"]:
        server = db.get_panel_server(cc_row["panel_server_id"])
        if server:
            try:
                provider = get_provider(server)
                await provider.delete_user(cc_row["username"])
            except Exception:
                logging.getLogger("miniapp").exception(
                    "حذف کاربر «%s» از پنل سرور #%s ناموفق بود؛ در هر صورت از لیست کاربر حذف می‌شود.",
                    cc_row["username"], cc_row["panel_server_id"],
                )
    db.delete_owned_custom_config(custom_config_id, tg_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# ساخت کانفیگ شخصی (اتصال مستقیم به پنل VPN) - معادل CustomConfigFlow ربات؛
# قبلاً این‌جا فقط GET/DELETE بود (کاربر فقط می‌توانست کانفیگ‌های ساخته‌شده در
# ربات را ببیند/حذف کند). این endpoint ساخت واقعی کانفیگ جدید را هم اضافه
# می‌کند تا کاربر برای این کار مجبور به رفتن سراغ ربات نباشد.
# همچنین «پنل نمایندگی اعتباری» (ساخت رایگان از استخر گیگ نماینده) را هم
# اگر کاربر reseller باشد پشتیبانی می‌کند (use_credit=True).
# ---------------------------------------------------------------------------

@app.get("/api/custom-config/info")
def api_custom_config_info(auth=Depends(get_verified_user)):
    tg_id, db, tenant = auth
    settings = db.get_custom_config_settings()
    tiers = db.get_pricing_tiers()
    server = db.get_panel_server_for_usage("custom_config")
    is_reseller = db.is_reseller(tg_id)
    reseller_credit = db.get_reseller_credit(tg_id) if is_reseller else 0
    reseller_server = db.get_reseller_panel(tg_id) if is_reseller else None
    return {
        "enabled": settings["enabled"] and bool(server) and bool(tiers)
        and bool(db.is_full_access_bot(not tenant.tenant_id)),
        "min_gb": settings["min_gb"], "max_gb": settings["max_gb"],
        "duration_days": settings["duration_days"],
        "tiers": [
            {"from_gb": t["from_gb"], "to_gb": t["to_gb"], "price_per_gb": t["price_per_gb"]}
            for t in tiers
        ],
        "wallet_credit": db.get_wallet_credit(tg_id),
        "is_reseller": is_reseller,
        "reseller_credit_gb": reseller_credit,
        "reseller_available": is_reseller and reseller_credit > 0 and bool(reseller_server),
        "crypto_enabled": db.get_setting("crypto_payment_enabled", "0") == "1"
        and bool(_resolve_plisio_key(db)) and bool(API_BASE_URL),
        "abangateway_enabled": db.get_setting("abangateway_payment_enabled", "0") == "1"
        and bool(_resolve_abangateway_key(db)) and bool(API_BASE_URL),
        "card_to_card_enabled": db.get_setting("card_to_card_enabled", "1") == "1",
        "card_number": db.get_setting("card_number"), "card_holder": db.get_setting("card_holder"),
    }


class CustomConfigPurchase(BaseModel):
    username: str
    volume_gb: int
    use_credit: bool = False  # True یعنی از اعتبار گیگ نمایندگی (رایگان) ساخته شود


def _valid_custom_username(username: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]{3,20}", username or ""))


@app.post("/api/custom-configs")
async def api_create_custom_config(body: CustomConfigPurchase, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    username = (body.username or "").strip()
    if not _valid_custom_username(username):
        raise HTTPException(status_code=400, detail="نام کاربری نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.")
    if db.is_custom_username_taken(username):
        raise HTTPException(status_code=400, detail="این نام کاربری قبلاً استفاده شده است.")

    # --- مسیر نمایندگی اعتباری: رایگان از استخر حجم خودِ نماینده ---
    if body.use_credit:
        if not db.is_reseller(tg_id):
            raise HTTPException(status_code=403, detail="شما نماینده نیستید.")
        credit = db.get_reseller_credit(tg_id)
        if body.volume_gb <= 0 or body.volume_gb > credit:
            raise HTTPException(status_code=400, detail=f"اعتبار شما کافی نیست. اعتبار باقی‌مانده: {credit:,} گیگ.")
        server = db.get_reseller_panel(tg_id)
        if not server or not server["is_active"]:
            raise HTTPException(status_code=400, detail="سرور نمایندگی در دسترس نیست.")
        duration_days = db.get_custom_config_settings()["duration_days"]
        try:
            provider = get_provider(server)
            result = await provider.create_user(username, body.volume_gb, duration_days)
        except PanelUsernameTakenError:
            raise HTTPException(status_code=409, detail="این نام کاربری روی پنل تکراری است.")
        except PanelError as e:
            raise HTTPException(status_code=502, detail=f"خطا در ساخت کانفیگ: {e}")
        db.adjust_reseller_credit(tg_id, -body.volume_gb, reason=f"ساخت کانفیگ «{result.username}» (مینی‌اپ)")
        db.add_custom_config(
            tg_id, server["id"], result.username, body.volume_gb, duration_days,
            result.subscription_url, source="reseller",
        )
        return {
            "status": "approved", "link": result.subscription_url,
            "reseller_credit_left": db.get_reseller_credit(tg_id),
        }

    # --- مسیر خرید عادی (پرداخت از کیف‌پول/کارت/کریپتو) ---
    settings = db.get_custom_config_settings()
    if not settings["enabled"] or not db.is_full_access_bot(not tenant.tenant_id):
        raise HTTPException(status_code=400, detail="این بخش در حال حاضر غیرفعال است.")
    if body.volume_gb < settings["min_gb"] or body.volume_gb > settings["max_gb"]:
        raise HTTPException(status_code=400, detail=f"حجم باید بین {settings['min_gb']} تا {settings['max_gb']} گیگابایت باشد.")
    price = db.calc_custom_config_price(body.volume_gb)
    if price <= 0:
        raise HTTPException(status_code=400, detail="قیمت‌گذاری این بخش هنوز تنظیم نشده است.")
    server = db.get_panel_server_for_usage("custom_config")
    if not server or not server["is_active"]:
        raise HTTPException(status_code=400, detail="در حال حاضر سروری برای ساخت کانفیگ شخصی فعال نیست.")

    user_row = db.get_user(tg_id)
    if user_row and user_row["is_blocked"]:
        raise HTTPException(status_code=403, detail="حساب شما مسدود شده است.")

    wallet_credit = db.get_wallet_credit(tg_id)
    wallet_used = min(wallet_credit, price)
    if wallet_used > 0:
        db.add_wallet_credit(tg_id, -wallet_used)

    order_id = db.create_custom_config_order(
        tg_id, body.volume_gb, username, server["id"], base_price=price, wallet_used=wallet_used,
    )
    order = db.get_order(order_id)

    if order["final_price"] <= 0:
        try:
            provider = get_provider(server)
            result = await provider.create_user(username, body.volume_gb, settings["duration_days"])
        except Exception as e:
            db.reject_order(order_id)
            if wallet_used:
                db.add_wallet_credit(tg_id, wallet_used)
            raise HTTPException(status_code=502, detail=f"خطا در ساخت کانفیگ روی پنل: {e}")
        db.approve_custom_config_order(order_id)
        db.add_custom_config(
            tg_id, server["id"], result.username, body.volume_gb, settings["duration_days"],
            result.subscription_url, order_id=order_id, source="custom_config",
        )
        try:
            db.reward_referrer_if_first_purchase(tg_id, price)
        except Exception:
            pass
        return {"status": "approved", "order_id": order_id, "link": result.subscription_url}

    return {
        "status": "pending_payment", "order_id": order_id, "final_price": order["final_price"],
        "card_number": db.get_setting("card_number"), "card_holder": db.get_setting("card_holder"),
        **_payment_flags(db, order["final_price"], None),
    }


@app.get("/api/catalog")
def api_catalog(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    categories = db.get_categories(active_only=True)
    result = []
    for c in categories:
        products = db.get_products(c["id"], active_only=True)
        result.append({
            "id": c["id"],
            "name": c["name"],
            "products": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "price": p["price"],
                    "description": p["description"],
                    "stock": db.count_available_configs(p["id"]),
                    "is_auto_provision": bool(p["is_auto_provision"]),
                }
                for p in products
            ],
        })
    return result


# ---------------------------------------------------------------------------
# کانفیگ تست
# ---------------------------------------------------------------------------

class TestConfigClaim(BaseModel):
    plan_id: Optional[int] = None


@app.get("/api/test-config")
def api_test_config_status(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    user = db.get_user(tg_id)
    used = bool(user and user["test_used"] >= MAX_TEST_PER_USER)
    link = None
    if used:
        row = db.get_test_custom_config_for_user(tg_id)
        if row:
            link = row["subscription_url"]
        else:
            legacy = db.get_assigned_test_config(tg_id)
            link = legacy["link"] if legacy else None

    plans = db.get_test_config_plans(active_only=True)
    return {
        "enabled": db.get_setting("test_enabled", "1") == "1",
        "used": used,
        "available": db.count_available_test_configs(),
        "link": link,
        "plans": [
            {
                "id": p["id"],
                "name": p["name"],
                "volume_mb": p["volume_mb"],
                "duration_hours": p["duration_hours"],
                "amount_label": format_plan_amount(p),
            }
            for p in plans
        ],
    }


@app.post("/api/test-config/claim")
async def api_test_config_claim(payload: TestConfigClaim, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    if db.get_setting("test_enabled", "1") != "1":
        raise HTTPException(status_code=400, detail="در حال حاضر امکان دریافت کانفیگ تست غیرفعال است.")
    user = db.get_user(tg_id)
    if user and user["test_used"] >= MAX_TEST_PER_USER:
        raise HTTPException(status_code=400, detail="شما قبلاً کانفیگ تست خود را دریافت کرده‌اید.")

    is_full_access = db.is_full_access_bot(not tenant.tenant_id)
    plans = db.get_test_config_plans(active_only=True)
    if plans:
        plan = None
        if payload.plan_id is not None:
            plan = next((p for p in plans if p["id"] == payload.plan_id), None)
            if not plan:
                raise HTTPException(status_code=400, detail="این پلن دیگر در دسترس نیست.")
        elif len(plans) == 1:
            plan = plans[0]
        else:
            raise HTTPException(status_code=400, detail="لطفاً یک مدل کانفیگ تست انتخاب کنید.")

        if is_full_access:
            try:
                result = await provision_test_plan(db, plan, user_id=tg_id)
            except TestPlanProvisionError as e:
                raise HTTPException(status_code=409, detail=str(e))
        else:
            try:
                result = await provision_test_config(db, plan, user_id=tg_id)
            except ProvisionError as e:
                raise HTTPException(status_code=409, detail=str(e))
        db.mark_test_used(tg_id)
        return {"link": result["subscription_url"]}

    if not is_full_access:
        raise HTTPException(status_code=400, detail="در حال حاضر هیچ پلن کانفیگ تستی تعریف نشده است.")

    result = db.take_unused_test_config(tg_id)
    if not result:
        raise HTTPException(status_code=400, detail="متاسفانه موجودی کانفیگ تست تمام شده است.")
    db.mark_test_used(tg_id)
    return {"link": result["link"]}


# ---------------------------------------------------------------------------
# زیرمجموعه‌گیری
# ---------------------------------------------------------------------------

@app.get("/api/referral")
async def api_referral(auth=Depends(get_verified_user)):
    tg_id, db, tenant = auth
    if db.get_setting("referral_button_enabled", "1") != "1":
        return {"enabled": False}
    commission_on = db.get_setting("referral_enabled", "1") == "1"
    fc_on = db.get_setting("referral_free_config_enabled", "0") == "1"
    ib_on = db.get_setting("referral_invite_bonus_enabled", "0") == "1"
    if not (commission_on or fc_on or ib_on):
        return {"enabled": False}
    username = await get_bot_username(tenant)
    ref_start = f"ref{tg_id}"
    link = f"https://t.me/{username}?start={ref_start}" if username else None
    stats = db.get_referral_stats(tg_id)
    return {
        "enabled": True,
        "link": link,
        "count": stats["count"],
        "credit": stats["credit"],
        "commission_enabled": commission_on,
        "percent": db.get_setting("referral_percent", "10"),
        "commission_max_count": int(db.get_setting("referral_commission_max_count", "0") or 0),
        "free_config_enabled": fc_on,
        "free_config_threshold": int(db.get_setting("referral_free_config_threshold", "10") or 0),
        "invite_bonus_enabled": ib_on,
        "invite_bonus_amount": int(db.get_setting("referral_invite_bonus_amount", "0") or 0),
        "invite_bonus_max_count": int(db.get_setting("referral_invite_bonus_max_count", "0") or 0),
    }


# ---------------------------------------------------------------------------
# هشدار انقضا
# ---------------------------------------------------------------------------

@app.get("/api/sub-info")
async def api_sub_info(link: str = Query(...), auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    orders = db.get_user_orders(tg_id)
    owns_link = False
    for o in orders:
        configs = db.get_order_configs(o["id"]) if o["status"] == "approved" else []
        if configs:
            if any(c["link"] == link for c in configs):
                owns_link = True
                break
        else:
            cfg = db.get_config_by_id(o["config_id"]) if o["config_id"] else None
            if cfg and cfg["link"] == link:
                owns_link = True
                break
    if not owns_link:
        custom_configs = db.get_custom_configs_for_user(tg_id)
        owns_link = any(c["subscription_url"] == link for c in custom_configs)
    if not owns_link:
        raise HTTPException(status_code=403, detail="forbidden")

    info = await fetch_sub_info(link)
    return info


@app.get("/api/expiring")
async def api_expiring(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    rows = db.get_expiring_configs_for_user(tg_id)
    if not rows:
        return []

    threshold_days = int(db.get_setting("renewal_reminder_days_before", "5") or 5)
    infos = await asyncio.gather(*[fetch_sub_info(r["link"]) for r in rows])

    result = []
    for r, info in zip(rows, infos):
        expires_at = r["expires_at"]
        if info.get("ok") and info.get("expire"):
            exp_dt = datetime.fromtimestamp(info["expire"], tz=timezone.utc)
            real_days_left = (exp_dt - datetime.now(timezone.utc)).days
            if real_days_left > threshold_days:
                # طبق داده‌ی واقعی پنل هنوز واقعاً نزدیک انقضا نیست
                continue
            expires_at = exp_dt.isoformat()

        product = db.get_product(r["product_id"]) if r["product_id"] else None
        if product:
            product_name = product["name"]
        elif "custom_username" in r.keys() and r["custom_username"]:
            product_name = f"🛠 کانفیگ شخصی «{r['custom_username']}»"
        else:
            product_name = "نامشخص"
        result.append({
            "product_name": product_name,
            "expires_at": expires_at,
            "link": r["link"],
        })
    return result


# ---------------------------------------------------------------------------
# چت پشتیبانی
# ---------------------------------------------------------------------------

@app.get("/api/support/messages")
def api_support_messages(since_id: int = 0, auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    db.mark_support_read_by_user(tg_id)
    rows = db.get_support_messages(tg_id, since_id=since_id)
    return [
        {"id": m["id"], "sender": m["sender"], "message": m["message"], "created_at": m["created_at"]}
        for m in rows
    ]


class SupportMessageCreate(BaseModel):
    message: str


@app.post("/api/support/messages")
async def api_support_send(body: SupportMessageCreate, auth=Depends(get_verified_user)):
    tg_id, db, tenant = auth
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="پیام نمی‌تواند خالی باشد.")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="پیام بیش از حد طولانی است.")

    msg_id = db.add_support_message(tg_id, "user", text)

    user = db.get_user(tg_id)
    caption = (
        f"📩 پیام جدید از کاربر (مینی‌اپ)\n"
        f"👤 {(user['first_name'] if user else '') or ''} (@{(user['username'] if user else '') or '---'})\n"
        f"🆔 `{tg_id}`\n\n"
        f"✉️ {text}"
    )
    reply_markup = {
        "inline_keyboard": [[{"text": "↩️ پاسخ", "callback_data": f"reply_user:{tg_id}"}]]
    }
    # فقط به اولین ادمین/مالک آنلاین اطلاع بده تا مکالمه به او اختصاص یابد؛
    # اگر هیچ‌کس آنلاین نبود، طبق روال قدیم به همه‌ی ادمین‌ها اطلاع بده.
    target_admin = db.resolve_support_admin_for_message(tg_id)
    admin_ids = [target_admin] if target_admin else db.list_admins()
    async with aiohttp.ClientSession() as session:
        for admin_id in admin_ids:
            try:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={
                        "chat_id": admin_id, "text": caption,
                        "parse_mode": "Markdown", "reply_markup": reply_markup,
                    },
                )
            except Exception:
                pass

    return {"id": msg_id, "sender": "user", "message": text}


# ---------------------------------------------------------------------------
# سیستم تیکت (جدا از چت مستقیم بالا)
# ---------------------------------------------------------------------------

class TicketCreate(BaseModel):
    subject: str
    message: str


class TicketMessageCreate(BaseModel):
    message: str


def _ticket_to_dict(t):
    return {
        "id": t["id"], "subject": t["subject"], "status": t["status"],
        "claimed_by": t["claimed_by"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
    }


@app.get("/api/tickets")
def api_list_my_tickets(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    return [_ticket_to_dict(t) for t in db.get_user_tickets(tg_id)]


@app.post("/api/tickets")
async def api_create_ticket(body: TicketCreate, auth=Depends(get_verified_user)):
    tg_id, db, tenant = auth
    subject = (body.subject or "").strip()
    message = (body.message or "").strip()
    if not subject or not message:
        raise HTTPException(status_code=400, detail="موضوع و متن پیام نمی‌تواند خالی باشد.")
    if len(subject) > 150 or len(message) > 2000:
        raise HTTPException(status_code=400, detail="متن وارد شده بیش از حد طولانی است.")

    ticket_id = db.create_ticket(tg_id, subject, message)

    user = db.get_user(tg_id)
    caption = (
        f"🎫 تیکت جدید #{ticket_id}\n"
        f"👤 {(user['first_name'] if user else '') or ''} (@{(user['username'] if user else '') or '---'})\n"
        f"🆔 `{tg_id}`\n\n"
        f"📌 {subject}\n✉️ {message}"
    )
    admin_ids = db.list_admins()
    async with aiohttp.ClientSession() as session:
        for admin_id in admin_ids:
            try:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={"chat_id": admin_id, "text": caption, "parse_mode": "Markdown"},
                )
            except Exception:
                pass

    return _ticket_to_dict(db.get_ticket(ticket_id))


@app.get("/api/tickets/{ticket_id}/messages")
def api_get_my_ticket_messages(ticket_id: int, since_id: int = 0, auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    ticket = db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="تیکت یافت نشد.")
    db.mark_ticket_read_by_user(ticket_id)
    rows = db.get_ticket_messages(ticket_id, since_id=since_id)
    return {
        "ticket": _ticket_to_dict(ticket),
        "messages": [
            {"id": m["id"], "sender": m["sender"], "message": m["message"], "created_at": m["created_at"]}
            for m in rows
        ],
    }


@app.post("/api/tickets/{ticket_id}/messages")
async def api_send_my_ticket_message(ticket_id: int, body: TicketMessageCreate, auth=Depends(get_verified_user)):
    tg_id, db, tenant = auth
    ticket = db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="تیکت یافت نشد.")
    if ticket["status"] == "closed":
        raise HTTPException(status_code=400, detail="این تیکت بسته شده است.")
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="پیام نمی‌تواند خالی باشد.")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="پیام بیش از حد طولانی است.")

    msg_id = db.add_ticket_message(ticket_id, "user", text)

    user = db.get_user(tg_id)
    caption = (
        f"🎫 پیام جدید در تیکت #{ticket_id} ({ticket['subject']})\n"
        f"👤 {(user['first_name'] if user else '') or ''} (@{(user['username'] if user else '') or '---'})\n\n"
        f"✉️ {text}"
    )
    admin_ids = db.list_admins()
    async with aiohttp.ClientSession() as session:
        for admin_id in admin_ids:
            try:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={"chat_id": admin_id, "text": caption, "parse_mode": "Markdown"},
                )
            except Exception:
                pass

    return {"id": msg_id, "sender": "user", "message": text}


@app.post("/api/tickets/{ticket_id}/close")
def api_close_my_ticket(ticket_id: int, auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    ticket = db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="تیکت یافت نشد.")
    db.close_ticket(ticket_id)
    return {"status": "ok"}


async def send_photo_to_admins(db: Database, bot_token: str, caption: str, reply_markup: str,
                                photo_bytes: bytes, filename: str, content_type: str):
    """رسید را برای همه‌ی ادمین‌های همین مستأجر ارسال می‌کند. (file_id, تعداد تحویل موفق، نتایج) را برمی‌گرداند."""
    admin_ids = db.list_admins()
    sent_file_id = None
    delivered = 0
    results = []
    async with aiohttp.ClientSession() as session:
        for admin_id in admin_ids:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(admin_id))
            form.add_field("caption", caption)
            form.add_field("reply_markup", reply_markup)
            form.add_field("photo", photo_bytes, filename=filename, content_type=content_type)
            try:
                async with session.post(
                    f"https://api.telegram.org/bot{bot_token}/sendPhoto", data=form
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        delivered += 1
                        msg = data["result"]
                        results.append((admin_id, msg["message_id"]))
                        if not sent_file_id:
                            sent_file_id = msg["photo"][-1]["file_id"]
            except Exception:
                pass
    return sent_file_id, delivered, results


# ---------------------------------------------------------------------------
# اِعمال محدودیت‌های روش پرداخت (حداقل مبلغ هر روش + محدودیت مجاز هر محصول)
# ---------------------------------------------------------------------------
# منبع حقیقت همان database.py است (product_allows_payment_method /
# get_payment_method_min_amount) که از داخل ربات هم استفاده می‌شود؛ این توابع
# فقط همان چک را این‌جا (مینی‌اپ) هم اعمال می‌کنند تا هرجا خرید انجام شود
# (بات یا مینی‌اپ)، یک قانون یکسان حاکم باشد.

def _payment_method_error(db: Database, amount: int, method_key: str, product_id: int = None) -> Optional[str]:
    """اگر روش پرداخت method_key برای این مبلغ/محصول مجاز نباشد، پیام خطا را
    برمی‌گرداند؛ در غیر این صورت None (یعنی مجاز است). معادل _order_payment_method_error
    در handlers_user.py ربات - به‌عنوان یک لایه‌ی دفاعی سمت سرور (علاوه بر فیلترشدن
    گزینه‌ها در پاسخ API)."""
    if product_id and not db.product_allows_payment_method(product_id, method_key):
        return "این روش پرداخت برای این محصول مجاز نیست."
    min_amt = db.get_payment_method_min_amount(method_key)
    if min_amt and amount < min_amt:
        return f"حداقل مبلغ قابل پرداخت با این روش {min_amt:,} تومان است."
    return None


def _require_payment_method_allowed(db: Database, amount: int, method_key: str, product_id: int = None) -> None:
    err = _payment_method_error(db, amount, method_key, product_id)
    if err:
        raise HTTPException(status_code=400, detail=err)


def _payment_flags(db: Database, amount: int, product_id: int = None) -> dict:
    """فلگ‌های فعال/مجازبودن روش‌های پرداخت داخلی برای مبلغ/محصولِ سفارش جاری؛
    هم تنظیم فعال/غیرفعال کلی و هم محدودیت محصول/حداقل‌مبلغ را لحاظ می‌کند تا
    فرانت‌اند مینی‌اپ فقط دکمه‌های واقعاً قابل‌استفاده را نشان دهد."""
    def _ok(method_key: str) -> bool:
        return _payment_method_error(db, amount, method_key, product_id) is None
    return {
        "card_to_card_enabled": db.get_setting("card_to_card_enabled", "1") == "1" and _ok("card"),
        "crypto_enabled": db.get_setting("crypto_payment_enabled", "0") == "1"
        and bool(_resolve_plisio_key(db)) and bool(API_BASE_URL) and _ok("crypto"),
        "abangateway_enabled": db.get_setting("abangateway_payment_enabled", "0") == "1"
        and bool(_resolve_abangateway_key(db)) and bool(API_BASE_URL) and _ok("abangateway"),
        "card_to_card_auto_enabled": db.get_setting("card_to_card_auto_enabled", "0") == "1"
        and bool(db.list_card_to_card_cards(only_active=True)) and _ok("card_auto"),
    }


# ---------------------------------------------------------------------------
# سفارش‌ها
# ---------------------------------------------------------------------------

class OrderCreate(BaseModel):
    product_id: int
    quantity: int = 1
    discount_code: Optional[str] = None


class TopupCreate(BaseModel):
    amount: int


@app.post("/api/orders")
async def api_create_order(body: OrderCreate, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    user_row = db.get_user(tg_id)
    if user_row and user_row["is_blocked"]:
        raise HTTPException(status_code=403, detail="حساب شما مسدود شده است.")
    quantity = max(1, body.quantity)
    product = db.get_product(body.product_id)
    if not product:
        raise HTTPException(status_code=400, detail="این محصول موجود نیست.")
    if product["is_auto_provision"]:
        pass  # سقفی برای تعداد نیست؛ کافی بودن اعتبار حجمی لحظه‌ی ساخت واقعی چک می‌شود
    else:
        stock = db.count_available_configs(body.product_id)
        if stock <= 0:
            raise HTTPException(status_code=400, detail="این محصول موجود نیست.")
        if quantity > stock:
            raise HTTPException(status_code=400, detail=f"موجودی کافی نیست. فقط {stock} عدد موجود است.")

    total_price = product["price"] * quantity
    discount_code_id = None
    discount_amount = 0
    if body.discount_code:
        code_row = db.get_discount_code(body.discount_code)
        if not db.is_discount_code_valid(code_row):
            raise HTTPException(status_code=400, detail="کد تخفیف نامعتبر است.")
        discount_amount = db.compute_discount_amount(code_row, total_price)
        discount_code_id = code_row["id"]

    wallet_credit = db.get_wallet_credit(tg_id)
    price_after_code = max(total_price - discount_amount, 0)
    wallet_used = min(wallet_credit, price_after_code)

    if wallet_used > 0:
        db.add_wallet_credit(tg_id, -wallet_used)
    if discount_code_id:
        db.increment_discount_usage(discount_code_id)

    order_id = db.create_order(
        tg_id, body.product_id, base_price=total_price,
        wallet_used=wallet_used, discount_code_id=discount_code_id, discount_amount=discount_amount,
        quantity=quantity,
    )
    order = db.get_order(order_id)

    if order["final_price"] <= 0:
        if product["is_auto_provision"]:
            try:
                if product["provision_server_id"]:
                    prov_results = await provision_direct(db, product, quantity, user_id=tg_id, order_id=order_id)
                else:
                    prov_results = await provision_auto_config(db, product, quantity, user_id=tg_id, order_id=order_id)
            except (ProvisionError, DirectProvisionError) as e:
                db.reject_order(order_id)
                raise HTTPException(status_code=409, detail=str(e))
            db.approve_order_auto(order_id)
            db.reward_referrer_if_first_purchase(tg_id, order["final_price"] or total_price)
            links = [r["subscription_url"] for r in prov_results]
            return {
                "status": "approved", "order_id": order_id,
                "link": links[0], "links": links,
                "expires_at": None,
            }

        results = db.take_unused_configs(body.product_id, tg_id, quantity)
        if not results:
            db.reject_order(order_id)
            raise HTTPException(status_code=409, detail="موجودی هم‌زمان تمام شد؛ مبلغ بازگردانده شد.")
        db.approve_order(order_id, [r["id"] for r in results])

        async def _send_admin_msg(admin_id, text):
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={"chat_id": admin_id, "text": text},
                )

        await check_and_notify_low_stock(_send_admin_msg, db, body.product_id)

        db.reward_referrer_if_first_purchase(tg_id, order["final_price"] or total_price)
        order = db.get_order(order_id)
        configs = db.get_order_configs(order_id)
        links = [c["link"] for c in configs] if configs else [db.get_config_by_id(order["config_id"])["link"]]
        return {
            "status": "approved", "order_id": order_id,
            "link": links[0], "links": links,
            "expires_at": configs[0]["expires_at"] if configs else None,
        }

    # مبلغی باقی مانده - کاربر باید مثل قبل از طریق بات رسید کارت‌به‌کارت بفرستد
    flags = _payment_flags(db, order["final_price"], body.product_id)
    return {
        "status": "pending_payment", "order_id": order_id, "final_price": order["final_price"],
        "quantity": quantity,
        "card_number": db.get_setting("card_number"), "card_holder": db.get_setting("card_holder"),
        **flags,
    }


# ---------------------------------------------------------------------------
# پرداخت کریپتو (Plisio)
# ---------------------------------------------------------------------------

def _resolve_plisio_key(db: Database) -> str:
    return crypto_payment.resolve_plisio_key(db)


async def _toman_to_usd(db: Database, amount_toman: int) -> float:
    try:
        return await crypto_payment.toman_to_usd(db, amount_toman)
    except crypto_payment.CryptoPaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _crypto_callback_url(tenant_id: str) -> str:
    try:
        return crypto_payment.callback_url(tenant_id)
    except crypto_payment.CryptoPaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _create_crypto_invoice_for(
    db: Database, tenant, tg_id: int, kind: str, ref_id: int, amount_toman: int,
    order_name: str,
):
    try:
        return await crypto_payment.create_invoice_for(
            db, tenant.tenant_id, tg_id, kind, ref_id, amount_toman, order_name,
        )
    except crypto_payment.CryptoPaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/orders/{order_id}/crypto-invoice")
async def api_order_crypto_invoice(order_id: int, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    order = db.get_order(order_id)
    if not order or order["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")
    if order["status"] != "pending":
        raise HTTPException(status_code=400, detail="این سفارش قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, order["final_price"], "crypto", order["product_id"])
    if order["is_custom_config"]:
        order_label = f"کانفیگ شخصی #{order_id} - {order['custom_username']}"
    else:
        product = db.get_product(order["product_id"])
        order_label = f"سفارش #{order_id} - {product['name'] if product else ''}"
    result = await _create_crypto_invoice_for(
        db, tenant, tg_id, "order", order_id, order["final_price"],
        order_name=order_label,
    )
    return result


class CryptoWalletInvoiceRequest(BaseModel):
    topup_id: int


@app.post("/api/wallet/crypto-invoice")
async def api_wallet_crypto_invoice(body: CryptoWalletInvoiceRequest, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    topup = db.get_topup(body.topup_id)
    if not topup or topup["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="درخواست شارژ یافت نشد.")
    if topup["status"] != "pending":
        raise HTTPException(status_code=400, detail="این درخواست شارژ قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, topup["amount"], "crypto")
    result = await _create_crypto_invoice_for(
        db, tenant, tg_id, "wallet_topup", body.topup_id, topup["amount"],
        order_name=f"شارژ کیف پول #{body.topup_id}",
    )
    result["topup_id"] = body.topup_id
    return result


# ---------------------------------------------------------------------------
# پرداخت کارت‌به‌کارت خودکار (آبان گیت وی)
# ---------------------------------------------------------------------------

def _resolve_abangateway_key(db: Database) -> str:
    return abangateway_payment.resolve_api_key(db)


async def _create_abangateway_invoice_for(
    db: Database, tenant, tg_id: int, kind: str, ref_id: int, amount_toman: int,
    order_name: str,
):
    try:
        return await abangateway_payment.create_invoice_for(
            db, tenant.tenant_id, tg_id, kind, ref_id, amount_toman, order_name,
        )
    except abangateway_payment.AbanGatewayPaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/orders/{order_id}/abangateway-invoice")
async def api_order_abangateway_invoice(order_id: int, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    order = db.get_order(order_id)
    if not order or order["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")
    if order["status"] != "pending":
        raise HTTPException(status_code=400, detail="این سفارش قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, order["final_price"], "abangateway", order["product_id"])
    if order["is_custom_config"]:
        order_label = f"کانفیگ شخصی #{order_id} - {order['custom_username']}"
    else:
        product = db.get_product(order["product_id"])
        order_label = f"سفارش #{order_id} - {product['name'] if product else ''}"
    result = await _create_abangateway_invoice_for(
        db, tenant, tg_id, "order", order_id, order["final_price"],
        order_name=order_label,
    )
    return result


class AbanGatewayWalletInvoiceRequest(BaseModel):
    topup_id: int


@app.post("/api/wallet/abangateway-invoice")
async def api_wallet_abangateway_invoice(body: AbanGatewayWalletInvoiceRequest, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    topup = db.get_topup(body.topup_id)
    if not topup or topup["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="درخواست شارژ یافت نشد.")
    if topup["status"] != "pending":
        raise HTTPException(status_code=400, detail="این درخواست شارژ قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, topup["amount"], "abangateway")
    result = await _create_abangateway_invoice_for(
        db, tenant, tg_id, "wallet_topup", body.topup_id, topup["amount"],
        order_name=f"شارژ کیف پول #{body.topup_id}",
    )
    result["topup_id"] = body.topup_id
    return result


@app.post("/api/webhooks/abangateway")
async def api_abangateway_webhook(request: Request, tenant: Tenant = Depends(get_tenant)):
    """
    توجه مهم: مستندات رسمی آبان گیت وی قالب دقیق بدنه‌ی وب‌هوک (و امضای آن) را مشخص
    نکرده است. بنابراین این هندلر به هیچ فیلدی از بدنه (مثل status) اعتماد نمی‌کند؛
    فقط از آن برای پیدا کردن invoice_id استفاده می‌شود و سپس با کلید API خودمان
    (که در بدنه‌ی وب‌هوک قابل جعل نیست) وضعیت واقعی از سمت آبان گیت وی استعلام و
    verify می‌شود. abangateway_payment.try_verify_and_finalize منبع حقیقت است.
    """
    try:
        body = await request.json()
    except Exception:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}

    invoice_id = abangateway_payment.extract_invoice_id_from_webhook(body or {})
    if not invoice_id:
        # اگر شناسه در بدنه پیدا نشد، شاید در کوئری‌استرینگ آمده باشد
        invoice_id = request.query_params.get("invoice_id")
    if not invoice_id:
        raise HTTPException(status_code=400, detail="شناسه‌ی فاکتور در وب‌هوک پیدا نشد.")

    db = tenant.db
    invoice = db.get_abangateway_invoice_by_invoice_id(invoice_id)
    if not invoice:
        db.log_webhook_event(gateway="abangateway", txn_id=invoice_id, verified=False,
                              status="ignored", error="فاکتور در دیتابیس پیدا نشد.",
                              raw_body=json.dumps(body, ensure_ascii=False))
        return {"status": "ignored"}

    result = await abangateway_payment.try_verify_and_finalize(db, invoice)
    db.log_webhook_event(gateway="abangateway", txn_id=invoice_id, verified=(result == "verified_now"),
                          status=result, raw_body=json.dumps(body, ensure_ascii=False))
    if result != "verified_now":
        # already_delivered / not_paid_yet / expired / cancelled / error:...
        return {"status": result}

    if invoice["kind"] == "wallet_topup":
        db.approve_topup(invoice["ref_id"])
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={
                        "chat_id": invoice["user_id"],
                        "text": f"✅ پرداخت تایید شد و {invoice['amount_toman']:,} تومان به کیف پول شما اضافه شد.",
                    },
                )
        except Exception:
            pass
        return {"status": "ok"}

    # invoice["kind"] == "order"
    order_id = invoice["ref_id"]
    order = db.get_order(order_id)
    if not order or order["status"] != "pending":
        return {"status": "ok"}

    if order["is_renewal"]:
        if not db.claim_order(order_id):
            return {"status": "ok"}
        try:
            result_text = await execute_renewal(db, order)
        except RenewalError as e:
            db.release_order_claim(order_id)
            for admin_id in db.list_admins():
                try:
                    async with aiohttp.ClientSession() as session:
                        await session.post(
                            f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                            json={"chat_id": admin_id, "text": f"⚠️ سفارش تمدید #{order_id} با آبان گیت وی پرداخت شد ولی تمدید ناموفق بود: {e}\nلطفاً دستی رسیدگی کنید."},
                        )
                except Exception:
                    pass
            return {"status": "ok"}
        db.approve_renewal_order(order_id)
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={"chat_id": order["user_id"], "text": result_text},
                )
        except Exception:
            pass
        return {"status": "ok"}

    if order["is_custom_config"]:
        # ساخت کانفیگ شخصی نیازمند panel provider است که در این سرور مستقل هم در
        # دسترس است؛ برای سادگی و یکسان بودن با مسیر «بررسی دستی» در بات، همان
        # منطق مشترک abangateway_payment.finalize_paid_order استفاده می‌شود، اما
        # چون این سرور به آبجکت aiogram Bot دسترسی ندارد، فقط سفارش را به کاربر
        # اطلاع می‌دهیم که از داخل بات دکمه‌ی «بررسی وضعیت پرداخت» را بزند.
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={
                        "chat_id": order["user_id"],
                        "text": "✅ پرداخت شما تایید شد!\nبرای دریافت کانفیگ شخصی، به بات برگرد و روی دکمه‌ی "
                                "«🔄 بررسی وضعیت پرداخت» زیر همان پیام فاکتور بزن.",
                    },
                )
        except Exception:
            pass
        return {"status": "ok"}

    product = db.get_product(order["product_id"])
    if product and product["is_auto_provision"]:
        if not db.claim_order(order_id):
            return {"status": "ok"}
        quantity = order["quantity"] or 1
        try:
            if product["provision_server_id"]:
                prov_results = await provision_direct(db, product, quantity, user_id=order["user_id"], order_id=order_id)
            else:
                prov_results = await provision_auto_config(db, product, quantity, user_id=order["user_id"], order_id=order_id)
        except (ProvisionError, DirectProvisionError) as e:
            db.release_order_claim(order_id)
            admin_ids = db.list_admins()
            async with aiohttp.ClientSession() as session:
                for admin_id in admin_ids:
                    try:
                        await session.post(
                            f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                            json={
                                "chat_id": admin_id,
                                "text": f"⚠️ سفارش #{order_id} با آبان گیت وی پرداخت شد ولی ساخت خودکار کانفیگ ناموفق بود: {e}\nلطفاً دستی رسیدگی کنید.",
                            },
                        )
                    except Exception:
                        pass
            return {"status": "ok"}

        db.approve_order_auto(order_id)
        db.reward_referrer_if_first_purchase(order["user_id"], order["final_price"] or product["price"])
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={
                        "chat_id": order["user_id"],
                        "text": f"✅ پرداخت تایید شد!\n📦 محصول: {product['name']}",
                    },
                )
        except Exception:
            pass
        asyncio.create_task(deliver_config_to_user_web(
            order["user_id"], product["name"], [r["subscription_url"] for r in prov_results],
            final_price=order["final_price"], order_id=order_id, db=db, bot_token=tenant.bot_token,
        ))
        return {"status": "ok"}

    if not db.claim_order(order_id):
        return {"status": "ok"}
    quantity = order["quantity"] or 1
    results = db.take_unused_configs(order["product_id"], order["user_id"], quantity)
    if results:
        db.approve_order(order_id, [r["id"] for r in results])
        db.reward_referrer_if_first_purchase(order["user_id"], order["final_price"] or (product["price"] if product else 0))
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={
                        "chat_id": order["user_id"],
                        "text": f"✅ پرداخت تایید شد!\n📦 محصول: {product['name'] if product else ''}",
                    },
                )
        except Exception:
            pass
        asyncio.create_task(deliver_config_to_user_web(
            order["user_id"], product["name"] if product else "", [r["link"] for r in results],
            final_price=order["final_price"], order_id=order_id, db=db, bot_token=tenant.bot_token,
        ))
    else:
        db.release_order_claim(order_id)
        admin_ids = db.list_admins()
        async with aiohttp.ClientSession() as session:
            for admin_id in admin_ids:
                try:
                    await session.post(
                        f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                        json={
                            "chat_id": admin_id,
                            "text": f"⚠️ سفارش #{order_id} با آبان گیت وی پرداخت شد ولی موجودی هم‌زمان تمام شده. لطفاً دستی رسیدگی کنید.",
                        },
                    )
                except Exception:
                    pass
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# درگاه‌های پرداخت سفارشی/پویا — ادمین از پنل هر API‌ای را (بدون کد) وصل می‌کند
# ---------------------------------------------------------------------------

def _load_gateway(db: Database, gateway_id: int = None, gateway_key: str = None):
    row = db.get_custom_gateway(gateway_id) if gateway_id else db.get_custom_gateway_by_key(gateway_key)
    if not row:
        raise HTTPException(status_code=404, detail="این درگاه پیدا نشد.")
    try:
        config = json.loads(row["config_json"])
    except Exception:
        config = {}
    return row, config


def _gateway_amount_ok(config: dict, invoice, paid_amount) -> bool:
    """اگر amount_path تنظیم شده و مبلغ برگشتی از درگاه به‌اندازه‌ی کافی کمتر
    از مبلغ واقعی فاکتور باشد => False (یعنی نباید تکمیل شود). اگر amount_path
    خالی باشد یا مقدار قابل‌تشخیص نباشد => True (سازگار با درگاه‌هایی که مبلغ
    را در پاسخ برنمی‌گردانند، تا اتصال هر نوع درگاهی همچنان ممکن بماند)."""
    tolerance = config.get("amount_tolerance_percent")
    try:
        tolerance = float(tolerance) if tolerance is not None else 1.0
    except (TypeError, ValueError):
        tolerance = 1.0
    return payment_engine.amounts_match(paid_amount, invoice["amount_toman"], tolerance)


def _mask_gateway_row(row, config: dict) -> dict:
    """برای پاسخ به ادمین: مقادیر محرمانه (credentials با secret=true) ماسک می‌شوند."""
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
        "id": row["id"],
        "key": row["gateway_key"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "config": out_config,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class CustomGatewayIn(BaseModel):
    key: str
    name: str
    enabled: bool = False
    config: dict


@app.get("/api/admin/gateways")
def api_admin_list_gateways(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    rows = db.list_custom_gateways()
    out = []
    for row in rows:
        try:
            config = json.loads(row["config_json"])
        except Exception:
            config = {}
        out.append(_mask_gateway_row(row, config))
    return out


@app.get("/api/admin/gateways/{gateway_id}")
def api_admin_get_gateway(gateway_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    row, config = _load_gateway(db, gateway_id=gateway_id)
    return _mask_gateway_row(row, config)


@app.post("/api/admin/gateways")
def api_admin_create_gateway(body: CustomGatewayIn, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    key = "".join(ch for ch in body.key.strip().lower() if ch.isalnum() or ch in ("-", "_"))
    if not key:
        raise HTTPException(status_code=400, detail="کلید درگاه نامعتبر است (فقط حروف/عدد انگلیسی، - و _).")
    if db.get_custom_gateway_by_key(key):
        raise HTTPException(status_code=400, detail="درگاهی با همین کلید قبلاً ثبت شده.")
    gateway_id = db.create_custom_gateway(key, body.name.strip() or key, body.config, body.enabled)
    db.log_admin_action(admin_id, "custom_gateway_create", f"درگاه سفارشی «{body.name}» ({key}) اضافه شد.")
    row, config = _load_gateway(db, gateway_id=gateway_id)
    return _mask_gateway_row(row, config)


@app.put("/api/admin/gateways/{gateway_id}")
def api_admin_update_gateway(gateway_id: int, body: CustomGatewayIn, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    row, existing_config = _load_gateway(db, gateway_id=gateway_id)

    # مقادیر محرمانه‌ای که ادمین در فرم دست‌نخورده گذاشته (چون ماسک‌شده نمایش داده شده بودند)
    # با «...abcd» شروع می‌شوند؛ این‌ها را با مقدار واقعی قبلی جایگزین می‌کن تا رمز از بین نرود.
    new_creds = dict((body.config or {}).get("credentials") or {})
    old_creds = dict(existing_config.get("credentials") or {})
    for k, v in list(new_creds.items()):
        if isinstance(v, str) and (v.startswith("...") or v == "•••") and k in old_creds:
            new_creds[k] = old_creds[k]
    body.config["credentials"] = new_creds

    db.update_custom_gateway(gateway_id, name=body.name.strip() or row["name"],
                              config=body.config, enabled=body.enabled)
    db.log_admin_action(admin_id, "custom_gateway_update", f"درگاه سفارشی «{row['name']}» ویرایش شد.")
    row, config = _load_gateway(db, gateway_id=gateway_id)
    return _mask_gateway_row(row, config)


@app.delete("/api/admin/gateways/{gateway_id}")
def api_admin_delete_gateway(gateway_id: int, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    row, _ = _load_gateway(db, gateway_id=gateway_id)
    db.delete_custom_gateway(gateway_id)
    db.log_admin_action(admin_id, "custom_gateway_delete", f"درگاه سفارشی «{row['name']}» حذف شد.")
    return {"status": "ok"}


class CustomGatewayTestRequest(BaseModel):
    amount_toman: int = 1000


@app.post("/api/admin/gateways/{gateway_id}/test")
async def api_admin_test_gateway(gateway_id: int, body: CustomGatewayTestRequest,
                                  auth=Depends(require_senior_admin)):
    """یک فاکتور واقعی آزمایشی (با مبلغ دلخواه، پیش‌فرض ۱۰۰۰ تومان) می‌سازد تا ادمین قبل از
    فعال‌کردن درگاه برای کاربران، مطمئن شود URL/هدر/بدنه و مسیرهای پاسخ درست تنظیم شده‌اند.
    توجه: چون این یک درخواست واقعی به API درگاه است، ممکن است یک فاکتور واقعی نزد آن درگاه بسازد."""
    _, db, tenant = auth
    row, config = _load_gateway(db, gateway_id=gateway_id)
    gw = payment_engine.GenericGateway(config)
    our_ref = f"test-{gateway_id}-{int(datetime.now(timezone.utc).timestamp())}"
    try:
        result = await gw.create_invoice(
            amount=body.amount_toman, amount_toman=body.amount_toman,
            order_id=our_ref, currency="IRT", description="تست اتصال درگاه",
            tenant_id=tenant.tenant_id or "main",
            callback_url=f"{API_BASE_URL}/api/pay/custom/{row['gateway_key']}/return?b={tenant.tenant_id}&txn={our_ref}",
            webhook_url=f"{API_BASE_URL}/api/webhooks/custom/{row['gateway_key']}?b={tenant.tenant_id}",
        )
    except payment_engine.PaymentEngineError as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "invoice_url": result.get("invoice_url"), "txn_id": result.get("txn_id")}


@app.get("/api/gateways")
def api_list_public_gateways(auth=Depends(require_joined), amount: int = None, product_id: int = None):
    """لیست درگاه‌های فعال، برای نمایش به‌عنوان یک روش پرداخت در مینی‌اپ.
    اگر amount/product_id داده شود، همان محدودیت «حداقل مبلغ درگاه» و
    «روش‌های مجاز این محصول» که در چک‌اوت اعمال می‌شود، این‌جا هم برای فیلترکردن
    لیست (پیش از نمایش به کاربر) اعمال می‌شود - دقیقاً مثل payment_choice_kb ربات."""
    _, db, _ = auth
    rows = db.list_custom_gateways(only_enabled=True)
    out = []
    for r in rows:
        key = f"custom:{r['gateway_key']}"
        if amount is not None or product_id is not None:
            if _payment_method_error(db, amount if amount is not None else 0, key, product_id) is not None:
                continue
        out.append({"key": r["gateway_key"], "name": r["name"]})
    return out


async def _complete_custom_gateway_payment(db: Database, tenant: "Tenant", invoice) -> None:
    """بعد از تایید قطعی پرداخت یک درگاه سفارشی (چه از طریق webhook چه از طریق verify)،
    سفارش/شارژ کیف پول را همان‌طور که برای Plisio/آبان‌گیت‌وی انجام می‌شود تکمیل و تحویل می‌دهد."""
    if invoice["status"] == "completed":
        return
    db.update_custom_gateway_invoice_status(invoice["id"], "completed")
    await _complete_generic_gateway_payment(db, tenant, invoice)


async def _complete_generic_gateway_payment(db: Database, tenant: "Tenant", invoice) -> None:
    """اثر مشترکِ «پرداخت تایید شد» (تکمیل سفارش یا شارژ کیف‌پول) که همه‌ی
    درگاه‌های خودکار (درگاه سفارشی، کارت‌به‌کارت خودکار و ...) بعد از این‌که
    خودشان وضعیت invoice را در جدول مخصوص خودشان 'completed' کردند، صدا می‌زنند.
    invoice فقط باید کلیدهای kind/ref_id/user_id/amount_toman را داشته باشد."""

    async def _notify(chat_id: int, text: str):
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                )
        except Exception:
            pass

    if invoice["kind"] == "wallet_topup":
        db.approve_topup(invoice["ref_id"])
        await _notify(
            invoice["user_id"],
            f"✅ پرداخت تایید شد و {invoice['amount_toman']:,} تومان به کیف پول شما اضافه شد.",
        )
        return

    order_id = invoice["ref_id"]
    order = db.get_order(order_id)
    if not order or order["status"] != "pending":
        return

    if order["is_renewal"]:
        if not db.claim_order(order_id):
            return
        try:
            result_text = await execute_renewal(db, order)
        except RenewalError as e:
            db.release_order_claim(order_id)
            for admin_id in db.list_admins():
                await _notify(
                    admin_id,
                    f"⚠️ سفارش تمدید #{order_id} با درگاه سفارشی پرداخت شد ولی تمدید ناموفق بود: {e}\nلطفاً دستی رسیدگی کنید.",
                )
            return
        db.approve_renewal_order(order_id)
        await _notify(order["user_id"], result_text)
        return

    if order["is_custom_config"]:
        await _notify(
            order["user_id"],
            "✅ پرداخت شما تایید شد!\nبرای دریافت کانفیگ شخصی، به بات برگرد و روی دکمه‌ی "
            "«🔄 بررسی وضعیت پرداخت» زیر همان پیام فاکتور بزن.",
        )
        return

    product = db.get_product(order["product_id"])
    quantity = order["quantity"] or 1
    if product and product["is_auto_provision"]:
        if not db.claim_order(order_id):
            return
        try:
            if product["provision_server_id"]:
                prov_results = await provision_direct(db, product, quantity, user_id=order["user_id"], order_id=order_id)
            else:
                prov_results = await provision_auto_config(db, product, quantity, user_id=order["user_id"], order_id=order_id)
        except (ProvisionError, DirectProvisionError) as e:
            db.release_order_claim(order_id)
            for admin_id in db.list_admins():
                await _notify(
                    admin_id,
                    f"⚠️ سفارش #{order_id} با درگاه سفارشی پرداخت شد ولی ساخت خودکار کانفیگ ناموفق بود: {e}\n"
                    f"لطفاً دستی رسیدگی کنید.",
                )
            return
        db.approve_order_auto(order_id)
        db.reward_referrer_if_first_purchase(order["user_id"], order["final_price"] or product["price"])
        await _notify(order["user_id"], f"✅ پرداخت تایید شد!\n📦 محصول: {product['name']}")
        asyncio.create_task(deliver_config_to_user_web(
            order["user_id"], product["name"], [r["subscription_url"] for r in prov_results],
            final_price=order["final_price"], order_id=order_id, db=db, bot_token=tenant.bot_token,
        ))
        return

    if not db.claim_order(order_id):
        return
    results = db.take_unused_configs(order["product_id"], order["user_id"], quantity)
    if results:
        db.approve_order(order_id, [r["id"] for r in results])
        db.reward_referrer_if_first_purchase(order["user_id"], order["final_price"] or (product["price"] if product else 0))
        await _notify(order["user_id"], f"✅ پرداخت تایید شد!\n📦 محصول: {product['name'] if product else ''}")
        asyncio.create_task(deliver_config_to_user_web(
            order["user_id"], product["name"] if product else "", [r["link"] for r in results],
            final_price=order["final_price"], order_id=order_id, db=db, bot_token=tenant.bot_token,
        ))
        await check_and_notify_low_stock(_notify, db, order["product_id"])
    else:
        db.release_order_claim(order_id)
        for admin_id in db.list_admins():
            await _notify(
                admin_id,
                f"⚠️ سفارش #{order_id} با درگاه سفارشی پرداخت شد ولی موجودی هم‌زمان تمام شده. لطفاً دستی رسیدگی کنید.",
            )


async def _create_custom_gateway_invoice_for(db: Database, tenant: "Tenant", tg_id: int,
                                              gateway_key: str, kind: str, ref_id: int,
                                              amount_toman: int, order_name: str) -> dict:
    row, config = _load_gateway(db, gateway_key=gateway_key)
    if not row["enabled"]:
        raise HTTPException(status_code=400, detail="این درگاه فعال نیست.")
    if not API_BASE_URL:
        raise HTTPException(status_code=400, detail="آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")

    existing = db.get_pending_custom_gateway_invoice_for_ref(row["id"], kind, ref_id)
    if existing:
        return {"invoice_url": existing["invoice_url"], "txn_id": existing["txn_id"]}

    tenant_slug = tenant.tenant_id or "main"
    # نکته‌ی امنیتی: یک قطعه‌ی تصادفی به txn_id داخلی اضافه می‌شود تا وقتی
    # webhook_auth یک درگاه روی "none" تنظیم شده، کاربر نتواند با حدس‌زدن txn
    # خودش (که ref_id و زمان تقریبی ساختش را می‌داند) وب‌هوک را دستی صدا بزند.
    our_ref = f"{kind}-{tenant_slug}-{ref_id}-{int(datetime.now(timezone.utc).timestamp())}-{secrets.token_hex(6)}"
    # برخی درگاه‌ها (مثل TonPays) سقف طول کاراکتر برای order_id دارند (مثلاً حداکثر
    # ۲۰ کاراکتر). ردیابی واقعی از طریق gateway_ref/our_ref داخلی انجام می‌شود، پس
    # اینجا هم - مثل custom_gateway_payment.create_invoice_for در بات اصلی - یک
    # نسخه‌ی کوتاه‌شده فقط برای ارسال به درگاه می‌سازیم.
    short_order_id = f"{ref_id}-{int(datetime.now(timezone.utc).timestamp())}"[:20]
    gw = payment_engine.GenericGateway(config)
    try:
        result = await gw.create_invoice(
            amount=amount_toman, amount_toman=amount_toman, order_id=short_order_id,
            currency="IRT", description=order_name, tenant_id=tenant_slug,
            callback_url=f"{API_BASE_URL}/api/pay/custom/{gateway_key}/return?b={tenant.tenant_id}&txn={our_ref}",
            webhook_url=f"{API_BASE_URL}/api/webhooks/custom/{gateway_key}?b={tenant.tenant_id}",
        )
    except payment_engine.PaymentEngineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    invoice_id = db.create_custom_gateway_invoice(
        row["id"], our_ref, kind, ref_id, tg_id, amount_toman, invoice_url=result.get("invoice_url"),
    )
    if result.get("txn_id") and result.get("txn_id") != our_ref:
        db.set_custom_gateway_invoice_gateway_ref(invoice_id, result.get("txn_id"))
    return {"invoice_url": result.get("invoice_url"), "txn_id": our_ref}


@app.post("/api/orders/{order_id}/custom-invoice/{gateway_key}")
async def api_order_custom_gateway_invoice(order_id: int, gateway_key: str, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    order = db.get_order(order_id)
    if not order or order["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")
    if order["status"] != "pending":
        raise HTTPException(status_code=400, detail="این سفارش قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, order["final_price"], f"custom:{gateway_key}", order["product_id"])
    if order["is_custom_config"]:
        order_label = f"کانفیگ شخصی #{order_id} - {order['custom_username']}"
    else:
        product = db.get_product(order["product_id"])
        order_label = f"سفارش #{order_id} - {product['name'] if product else ''}"
    return await _create_custom_gateway_invoice_for(
        db, tenant, tg_id, gateway_key, "order", order_id, order["final_price"], order_label,
    )


class CustomGatewayWalletInvoiceRequest(BaseModel):
    topup_id: int


@app.post("/api/wallet/custom-invoice/{gateway_key}")
async def api_wallet_custom_gateway_invoice(gateway_key: str, body: CustomGatewayWalletInvoiceRequest,
                                             auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    topup = db.get_topup(body.topup_id)
    if not topup or topup["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="درخواست شارژ یافت نشد.")
    if topup["status"] != "pending":
        raise HTTPException(status_code=400, detail="این درخواست شارژ قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, topup["amount"], f"custom:{gateway_key}")
    result = await _create_custom_gateway_invoice_for(
        db, tenant, tg_id, gateway_key, "wallet_topup", body.topup_id, topup["amount"],
        order_name=f"شارژ کیف پول #{body.topup_id}",
    )
    result["topup_id"] = body.topup_id
    return result


@app.post("/api/webhooks/custom/{gateway_key}")
async def api_custom_gateway_webhook(gateway_key: str, request: Request, tenant: Tenant = Depends(get_tenant)):
    db = tenant.db
    row, config = _load_gateway(db, gateway_key=gateway_key)
    gw = payment_engine.GenericGateway(config)

    raw_body = await request.body()
    try:
        body = json.loads(raw_body) if raw_body else {}
    except Exception:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}
    query = dict(request.query_params)
    headers = dict(request.headers)

    gw_log_name = f"custom:{gateway_key}"
    if not gw.check_webhook_auth(headers, query, raw_body):
        db.log_webhook_event(gateway=gw_log_name, verified=False, status=None,
                              error="احراز هویت وب‌هوک نامعتبر است.",
                              raw_body=json.dumps(body, ensure_ascii=False))
        raise HTTPException(status_code=401, detail="احراز هویت وب‌هوک نامعتبر است.")

    parsed = gw.parse_webhook(body, query)
    ref_val = parsed.get("txn_id")
    invoice = None
    if ref_val:
        invoice = db.get_custom_gateway_invoice_by_txn(row["id"], ref_val)
        if not invoice:
            invoice = db.get_custom_gateway_invoice_by_gateway_ref(row["id"], ref_val)
    if not invoice and query.get("txn"):
        invoice = db.get_custom_gateway_invoice_by_txn(row["id"], query.get("txn"))
    if not invoice:
        db.log_webhook_event(gateway=gw_log_name, txn_id=ref_val, verified=True, status="ignored",
                              error="فاکتور پیدا نشد.", raw_body=json.dumps(body, ensure_ascii=False))
        return {"status": "ignored"}

    db.log_webhook_event(gateway=gw_log_name, txn_id=ref_val, verified=True,
                          status=str(parsed.get("success")), raw_body=json.dumps(body, ensure_ascii=False))

    if parsed.get("success") is False:
        db.update_custom_gateway_invoice_status(invoice["id"], "failed")
        return {"status": "ok"}
    if parsed.get("success") is None:
        # نگاشت success_values تنظیم نشده؛ فقط وضعیت خام را ثبت کن، تصمیم نهایی
        # را با endpoint استعلام (verify) یا برگشت کاربر بگیر.
        db.update_custom_gateway_invoice_status(invoice["id"], "pending")
        return {"status": "ok"}

    if not _gateway_amount_ok(config, invoice, parsed.get("amount")):
        db.log_webhook_event(gateway=gw_log_name, txn_id=ref_val, verified=True, status="amount_mismatch",
                              error=f"مبلغ پرداختی ({parsed.get('amount')}) با مبلغ فاکتور "
                                    f"({invoice['amount_toman']}) هم‌خوانی ندارد.",
                              raw_body=json.dumps(body, ensure_ascii=False))
        db.update_custom_gateway_invoice_status(invoice["id"], "failed")
        for admin_id in db.list_admins():
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post(
                        f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                        json={"chat_id": admin_id,
                              "text": f"⚠️ درگاه «{row['name']}»: مبلغ پرداختی وب‌هوک با مبلغ فاکتور "
                                      f"#{invoice['id']} هم‌خوانی نداشت و سفارش تکمیل نشد. لطفاً بررسی کنید."},
                    )
            except Exception:
                pass
        return {"status": "ok"}

    await _complete_custom_gateway_payment(db, tenant, invoice)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# کارت‌به‌کارت با تایید خودکار (پیامک بانک از اپ BankSmsForwarder)
# ---------------------------------------------------------------------------

def _create_card_to_card_invoice_for(db: Database, kind: str, ref_id: int, user_id: int,
                                      amount_toman: int) -> dict:
    try:
        return card_to_card_payment.create_invoice(db, kind, ref_id, user_id, amount_toman)
    except card_to_card_payment.CardToCardError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/orders/{order_id}/card-auto-invoice")
async def api_order_card_auto_invoice(order_id: int, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    order = db.get_order(order_id)
    if not order or order["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")
    if order["status"] != "pending":
        raise HTTPException(status_code=400, detail="این سفارش قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, order["final_price"], "card_auto", order["product_id"])
    return _create_card_to_card_invoice_for(db, "order", order_id, tg_id, order["final_price"])


class CardAutoWalletInvoiceRequest(BaseModel):
    topup_id: int


@app.post("/api/wallet/card-auto-invoice")
async def api_wallet_card_auto_invoice(body: CardAutoWalletInvoiceRequest, auth=Depends(require_joined)):
    tg_id, db, tenant = auth
    topup = db.get_topup(body.topup_id)
    if not topup or topup["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="درخواست شارژ یافت نشد.")
    if topup["status"] != "pending":
        raise HTTPException(status_code=400, detail="این درخواست شارژ قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, topup["amount"], "card_auto")
    result = _create_card_to_card_invoice_for(db, "wallet_topup", body.topup_id, tg_id, topup["amount"])
    result["topup_id"] = body.topup_id
    return result


@app.get("/api/card-auto-invoice/{invoice_id}/status")
def api_card_auto_invoice_status(invoice_id: int, auth=Depends(get_verified_user)):
    tg_id, db, tenant = auth
    invoice = db.get_card_to_card_invoice(invoice_id)
    if not invoice or invoice["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="فاکتور یافت نشد.")
    db.expire_stale_card_to_card_invoices()
    invoice = db.get_card_to_card_invoice(invoice_id)
    return {"status": invoice["status"], "amount_toman": invoice["amount_toman"]}


@app.post("/api/webhooks/sms-forwarder")
async def api_sms_forwarder_webhook(request: Request, tenant: Tenant = Depends(get_tenant),
                                     x_webhook_token: str = Header(None)):
    """اندپوینتی که اپ اندروید BankSmsForwarder بعد از رسیدن هر پیامک بانکِ
    منطبق با یکی از قالب‌ها، با متد POST و هدر X-Webhook-Token صدا می‌زند."""
    db = tenant.db
    raw_body = await request.body()
    try:
        body = json.loads(raw_body) if raw_body else {}
    except Exception:
        body = {}

    expected_token = db.get_setting("card_to_card_sms_webhook_token", "")
    if not expected_token or not x_webhook_token or not hmac.compare_digest(x_webhook_token, expected_token):
        db.log_webhook_event(gateway="card_to_card_sms", verified=False,
                              error="توکن وب‌هوک نامعتبر یا خالی است.",
                              raw_body=json.dumps(body, ensure_ascii=False))
        raise HTTPException(status_code=401, detail="توکن نامعتبر است.")

    raw_amount = body.get("matched_amount")
    amount_toman = None
    parsed_amount = card_to_card_payment.normalize_amount(raw_amount)
    if parsed_amount is not None:
        unit = db.get_setting("card_to_card_sms_amount_unit", "rial")
        amount_toman = card_to_card_payment.rial_to_toman(parsed_amount, unit)

    if amount_toman is None:
        db.log_webhook_event(gateway="card_to_card_sms", verified=True, status="no_amount",
                              raw_body=json.dumps(body, ensure_ascii=False))
        return {"status": "ignored"}

    invoice = card_to_card_payment.match_and_complete(
        db, amount_toman, sender=body.get("sender"), body=body.get("body"),
        device_id=body.get("device_id"),
    )
    if not invoice:
        db.log_webhook_event(gateway="card_to_card_sms", verified=True, status="no_match",
                              raw_body=json.dumps(body, ensure_ascii=False))
        return {"status": "ignored"}

    db.log_webhook_event(gateway="card_to_card_sms", txn_id=str(invoice["id"]), verified=True,
                          status="matched", raw_body=json.dumps(body, ensure_ascii=False))
    await _complete_generic_gateway_payment(db, tenant, invoice)
    return {"status": "ok"}


@app.get("/api/pay/custom/{gateway_key}/return")
async def api_custom_gateway_return(gateway_key: str, request: Request, txn: str = "",
                                     tenant: Tenant = Depends(get_tenant)):
    """کاربر پس از پرداخت، مرورگرش به این آدرس برمی‌گردد (برای درگاه‌هایی که بر پایه‌ی
    verify API کار می‌کنند، نه webhook). یک صفحه‌ی HTML ساده نمایش می‌دهد و کاربر را
    به مینی‌اپ برمی‌گرداند."""
    db = tenant.db
    row, config = _load_gateway(db, gateway_key=gateway_key)
    invoice = db.get_custom_gateway_invoice_by_txn(row["id"], txn) if txn else None
    if not invoice:
        return HTMLResponse("<h3>فاکتور پیدا نشد.</h3>", status_code=404)

    gw = payment_engine.GenericGateway(config)
    query = dict(request.query_params)
    success_text = "پرداخت شما تایید شد ✅"
    ok = False
    try:
        if config.get("verify_enabled"):
            result = await gw.verify(
                amount=invoice["amount_toman"], amount_toman=invoice["amount_toman"],
                order_id=invoice["txn_id"], gateway_ref=invoice["gateway_ref"] or "",
                query=query, tenant_id=tenant.tenant_id or "main",
            )
            ok = bool(result.get("success"))
            if ok and not _gateway_amount_ok(config, invoice, result.get("amount")):
                ok = False
                success_text = "مبلغ پرداختی با مبلغ فاکتور هم‌خوانی ندارد ❌ (اگر مبلغ از حساب شما کسر شده، با پشتیبانی تماس بگیرید)"
                for admin_id in db.list_admins():
                    try:
                        async with aiohttp.ClientSession() as session:
                            await session.post(
                                f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                                json={"chat_id": admin_id,
                                      "text": f"⚠️ درگاه «{row['name']}»: مبلغ پرداختی استعلام‌شده با مبلغ فاکتور "
                                              f"#{invoice['id']} هم‌خوانی نداشت و سفارش تکمیل نشد. لطفاً بررسی کنید."},
                            )
                    except Exception:
                        pass
        else:
            # بدون verify_request: صرفاً به وب‌هوکی که قبلاً رسیده (اگر رسیده) تکیه می‌کنیم
            ok = invoice["status"] == "completed"
    except payment_engine.PaymentEngineError as e:
        ok = False
        success_text = f"خطا در استعلام پرداخت: {e}"

    if ok:
        await _complete_custom_gateway_payment(db, tenant, invoice)
    else:
        db.update_custom_gateway_invoice_status(invoice["id"], "failed")
        if success_text == "پرداخت شما تایید شد ✅":
            success_text = "پرداخت تایید نشد ❌ (اگر مبلغ از حساب شما کسر شده، با پشتیبانی تماس بگیرید)"

    return HTMLResponse(
        f"<html dir='rtl'><body style='font-family:sans-serif;text-align:center;padding:40px'>"
        f"<h2>{success_text}</h2>"
        f"<p>این صفحه را می‌توانید ببندید و به بات برگردید.</p>"
        f"</body></html>"
    )


@app.post("/api/webhooks/plisio")
async def api_plisio_webhook(request: Request, tenant: Tenant = Depends(get_tenant)):
    try:
        body = await request.json()
    except Exception:
        form = await request.form()
        body = dict(form)

    body_txn_id = body.get("txn_id")
    body_status = body.get("status")

    if not plisio_client.verify_callback(_resolve_plisio_key(tenant.db), body):
        tenant.db.log_webhook_event(
            gateway="plisio", txn_id=body_txn_id, verified=False, status=body_status,
            error="امضای کال‌بک نامعتبر است (verify_hash mismatch).",
            raw_body=json.dumps(body, ensure_ascii=False),
        )
        raise HTTPException(status_code=401, detail="امضای کال‌بک نامعتبر است.")

    txn_id = body.get("txn_id")
    status = body.get("status")
    currency = body.get("currency")
    if not txn_id or not status:
        tenant.db.log_webhook_event(
            gateway="plisio", txn_id=txn_id, verified=True, status=status,
            error="داده‌ی کال‌بک ناقص است (txn_id/status خالی).",
            raw_body=json.dumps(body, ensure_ascii=False),
        )
        raise HTTPException(status_code=400, detail="داده‌ی کال‌بک ناقص است.")

    db = tenant.db
    db.log_webhook_event(gateway="plisio", txn_id=txn_id, verified=True, status=status,
                          raw_body=json.dumps(body, ensure_ascii=False))
    invoice = db.get_crypto_invoice_by_txn(txn_id)
    if not invoice:
        return {"status": "ignored"}

    if invoice["status"] == "completed":
        return {"status": "already_completed"}

    if status in ("new", "pending", "pending internal"):
        db.update_crypto_invoice_status(txn_id, "pending", currency=currency)
        return {"status": "ok"}

    if status not in ("completed",):
        db.update_crypto_invoice_status(txn_id, status, currency=currency)
        return {"status": "ok"}

    # status == completed
    db.update_crypto_invoice_status(txn_id, "completed", currency=currency)

    if invoice["kind"] == "wallet_topup":
        db.approve_topup(invoice["ref_id"])
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={
                        "chat_id": invoice["user_id"],
                        "text": f"✅ پرداخت کریپتو تایید شد و {invoice['amount_toman']:,} تومان به کیف پول شما اضافه شد.",
                    },
                )
        except Exception:
            pass

    elif invoice["kind"] == "order":
        order_id = invoice["ref_id"]
        order = db.get_order(order_id)
        if order and order["status"] == "pending":
            if order["is_renewal"]:
                if not db.claim_order(order_id):
                    return {"status": "ok"}
                try:
                    result_text = await execute_renewal(db, order)
                except RenewalError as e:
                    db.release_order_claim(order_id)
                    admin_ids = db.list_admins()
                    async with aiohttp.ClientSession() as session:
                        for admin_id in admin_ids:
                            try:
                                await session.post(
                                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                                    json={"chat_id": admin_id, "text": f"⚠️ سفارش تمدید #{order_id} با کریپتو پرداخت شد ولی تمدید ناموفق بود: {e}\nلطفاً دستی رسیدگی کنید."},
                                )
                            except Exception:
                                pass
                    return {"status": "ok"}
                db.approve_renewal_order(order_id)
                try:
                    async with aiohttp.ClientSession() as session:
                        await session.post(
                            f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                            json={"chat_id": order["user_id"], "text": result_text},
                        )
                except Exception:
                    pass
                return {"status": "ok"}

            product = db.get_product(order["product_id"])

            if product and product["is_auto_provision"]:
                if not db.claim_order(order_id):
                    return {"status": "ok"}
                quantity = order["quantity"] or 1
                try:
                    if product["provision_server_id"]:
                        prov_results = await provision_direct(db, product, quantity, user_id=order["user_id"], order_id=order_id)
                    else:
                        prov_results = await provision_auto_config(db, product, quantity, user_id=order["user_id"], order_id=order_id)
                except (ProvisionError, DirectProvisionError) as e:
                    db.release_order_claim(order_id)
                    admin_ids = db.list_admins()
                    async with aiohttp.ClientSession() as session:
                        for admin_id in admin_ids:
                            try:
                                await session.post(
                                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                                    json={
                                        "chat_id": admin_id,
                                        "text": f"⚠️ سفارش #{order_id} با کریپتو پرداخت شد ولی ساخت خودکار کانفیگ ناموفق بود: {e}\nلطفاً دستی رسیدگی کنید.",
                                    },
                                )
                            except Exception:
                                pass
                    return {"status": "ok"}

                db.approve_order_auto(order_id)
                db.reward_referrer_if_first_purchase(order["user_id"], order["final_price"] or product["price"])
                try:
                    async with aiohttp.ClientSession() as session:
                        await session.post(
                            f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                            json={
                                "chat_id": order["user_id"],
                                "text": f"✅ پرداخت کریپتو تایید شد!\n📦 محصول: {product['name']}",
                            },
                        )
                except Exception:
                    pass
                asyncio.create_task(deliver_config_to_user_web(
                    order["user_id"], product["name"], [r["subscription_url"] for r in prov_results],
                    final_price=order["final_price"], order_id=order_id, db=db, bot_token=tenant.bot_token,
                ))
                return {"status": "ok"}

            if not db.claim_order(order_id):
                return {"status": "ok"}
            quantity = order["quantity"] or 1
            results = db.take_unused_configs(order["product_id"], order["user_id"], quantity)
            if results:
                db.approve_order(order_id, [r["id"] for r in results])
                db.reward_referrer_if_first_purchase(order["user_id"], order["final_price"] or (product["price"] if product else 0))
                try:
                    async with aiohttp.ClientSession() as session:
                        await session.post(
                            f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                            json={
                                "chat_id": order["user_id"],
                                "text": f"✅ پرداخت کریپتو تایید شد!\n📦 محصول: {product['name'] if product else ''}",
                            },
                        )
                except Exception:
                    pass
                asyncio.create_task(deliver_config_to_user_web(
                    order["user_id"], product["name"] if product else "", [r["link"] for r in results],
                    final_price=order["final_price"], order_id=order_id, db=db, bot_token=tenant.bot_token,
                ))
            else:
                db.release_order_claim(order_id)
                # موجودی هم‌زمان تمام شده - به ادمین اطلاع بده تا دستی رسیدگی کند
                admin_ids = db.list_admins()
                async with aiohttp.ClientSession() as session:
                    for admin_id in admin_ids:
                        try:
                            await session.post(
                                f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                                json={
                                    "chat_id": admin_id,
                                    "text": f"⚠️ سفارش #{order_id} با کریپتو پرداخت شد ولی موجودی محصول تمام شده! لطفاً دستی رسیدگی کنید.",
                                },
                            )
                        except Exception:
                            pass

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# گردونه‌ی شانس
# ---------------------------------------------------------------------------

@app.get("/api/wheel")
def api_wheel_status(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    settings = db.get_wheel_settings()
    can_spin, remaining_hours = db.can_spin_wheel(tg_id)
    return {
        "enabled": settings["enabled"], "can_spin": can_spin,
        "remaining_hours": round(remaining_hours, 1) if remaining_hours else 0,
        "prizes": settings["prizes"],
    }


@app.post("/api/wheel/spin")
def api_wheel_spin(auth=Depends(require_joined)):
    tg_id, db, _ = auth
    settings = db.get_wheel_settings()
    if not settings["enabled"]:
        raise HTTPException(status_code=400, detail="گردونه غیرفعال است.")
    can_spin, remaining_hours = db.can_spin_wheel(tg_id)
    if not can_spin:
        raise HTTPException(status_code=429, detail=f"حدود {int(remaining_hours)+1} ساعت دیگر دوباره امتحان کن.")

    db.record_wheel_spin(tg_id)
    won = random.randint(1, 100) <= settings["win_percent"]
    if won and settings["prizes"]:
        percent = random.choice(settings["prizes"])
        code, expires_at = db.generate_wheel_prize_code(tg_id, percent)
        return {"won": True, "percent": percent, "code": code, "expires_at": expires_at}
    return {"won": False}


# ---------------------------------------------------------------------------
# کیف پول
# ---------------------------------------------------------------------------

@app.post("/api/wallet/topup-request")
def api_topup_request(body: TopupCreate, auth=Depends(require_joined)):
    tg_id, db, _ = auth
    user_row = db.get_user(tg_id)
    if user_row and user_row["is_blocked"]:
        raise HTTPException(status_code=403, detail="حساب شما مسدود شده است.")
    min_topup = int(db.get_setting("min_amount_wallet_topup", "1000") or "1000")
    if body.amount < min_topup:
        raise HTTPException(status_code=400, detail=f"حداقل مبلغ {min_topup:,} تومان است.")
    topup_id = db.create_topup(tg_id, body.amount)
    return {
        "topup_id": topup_id,
        "card_number": db.get_setting("card_number"),
        "card_holder": db.get_setting("card_holder"),
        "note": "مبلغ را واریز کرده و عکس رسید را همینجا ارسال کنید.",
        **_payment_flags(db, body.amount, None),
    }


@app.post("/api/wallet/topup-receipt")
async def api_topup_receipt(
    topup_id: int = Form(...),
    photo: UploadFile = File(...),
    x_init_data: str = Header(...),
    tenant: Tenant = Depends(get_tenant),
):
    tg_id, db, tenant = get_verified_user(x_init_data, tenant)
    topup = db.get_topup(topup_id)
    if not topup or topup["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="درخواست شارژ یافت نشد.")
    if topup["status"] != "pending":
        raise HTTPException(status_code=400, detail="این درخواست قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, topup["amount"], "card")
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="فقط عکس رسید پذیرفته می‌شود.")

    photo_bytes = await photo.read()
    if len(photo_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="حجم عکس بیش از حد مجاز است.")

    user = db.get_user(tg_id)
    caption = (
        f"👛 درخواست شارژ کیف پول #{topup_id}\n"
        f"👤 کاربر: {(user['first_name'] if user else '') or ''} (@{(user['username'] if user else '') or '---'})\n"
        f"🆔 آیدی عددی: {tg_id}\n"
        f"💰 مبلغ: {topup['amount']:,} تومان"
    )
    reply_markup = json.dumps({
        "inline_keyboard": [[
            {"text": "✅ تایید و شارژ کیف پول", "callback_data": f"topup_approve:{topup_id}"},
            {"text": "❌ رد کردن", "callback_data": f"topup_reject:{topup_id}"},
        ]]
    })

    admin_ids = db.list_admins()
    if not admin_ids:
        raise HTTPException(status_code=500, detail="هیچ ادمینی برای بررسی رسید ثبت نشده است.")

    sent_file_id, delivered, results = await send_photo_to_admins(
        db, tenant.bot_token, caption, reply_markup, photo_bytes, photo.filename or "receipt.jpg", photo.content_type
    )
    if delivered == 0:
        raise HTTPException(status_code=502, detail="ارسال رسید به ادمین ناموفق بود. دوباره تلاش کنید.")

    for admin_id, message_id in results:
        db.set_topup_admin_message(topup_id, admin_id, message_id)
    if sent_file_id:
        db.set_topup_receipt(topup_id, sent_file_id)

    return {"status": "sent"}


@app.post("/api/orders/{order_id}/receipt")
async def api_order_receipt(
    order_id: int,
    photo: UploadFile = File(...),
    x_init_data: str = Header(...),
    tenant: Tenant = Depends(get_tenant),
):
    tg_id, db, tenant = get_verified_user(x_init_data, tenant)
    order = db.get_order(order_id)
    if not order or order["user_id"] != tg_id:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")
    if order["status"] != "pending":
        raise HTTPException(status_code=400, detail="این سفارش قبلاً بررسی شده است.")
    _require_payment_method_allowed(db, order["final_price"], "card", order["product_id"])
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="فقط عکس رسید پذیرفته می‌شود.")

    photo_bytes = await photo.read()
    if len(photo_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="حجم عکس بیش از حد مجاز است.")

    user = db.get_user(tg_id)
    qty = order["quantity"] or 1
    if order["is_custom_config"]:
        product_line = f"🛠 کانفیگ شخصی «{order['custom_username']}» ({order['custom_volume_gb']} گیگ)\n"
    else:
        product = db.get_product(order["product_id"])
        product_line = f"📦 محصول: {product['name'] if product else '---'}" + (f" × {qty}\n" if qty > 1 else "\n")
    caption = (
        f"🧾 سفارش #{order_id}\n"
        f"👤 کاربر: {(user['first_name'] if user else '') or ''} (@{(user['username'] if user else '') or '---'})\n"
        f"🆔 آیدی عددی: {tg_id}\n"
        f"{product_line}"
        f"💰 قیمت پایه: {order['base_price']:,} تومان\n"
    )
    if order["discount_amount"]:
        caption += f"🎟 تخفیف کد: {order['discount_amount']:,} تومان\n"
    if order["wallet_used"]:
        caption += f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان\n"
    caption += f"💵 مبلغ قابل پرداخت: {order['final_price']:,} تومان"

    reply_markup = json.dumps({
        "inline_keyboard": [[
            {"text": "✅ تایید و ارسال کانفیگ", "callback_data": f"order_approve:{order_id}"},
            {"text": "❌ رد کردن", "callback_data": f"order_reject:{order_id}"},
        ]]
    })

    admin_ids = db.list_admins()
    if not admin_ids:
        raise HTTPException(status_code=500, detail="هیچ ادمینی برای بررسی رسید ثبت نشده است.")

    sent_file_id, delivered, results = await send_photo_to_admins(
        db, tenant.bot_token, caption, reply_markup, photo_bytes, photo.filename or "receipt.jpg", photo.content_type
    )
    if delivered == 0:
        raise HTTPException(status_code=502, detail="ارسال رسید به ادمین ناموفق بود. دوباره تلاش کنید.")

    for admin_id, message_id in results:
        db.set_order_admin_message(order_id, admin_id, message_id)
    if sent_file_id:
        db.set_order_receipt(order_id, sent_file_id)

    return {"status": "sent"}


# ---------------------------------------------------------------------------
# مدیریت (فقط ادمین) - چیدمان دکمه‌های منوی اصلی
# ---------------------------------------------------------------------------

class MenuButtonUpdate(BaseModel):
    key: str
    text: Optional[str] = None
    style: Optional[str] = None
    enabled: Optional[bool] = None


class MenuLayoutUpdate(BaseModel):
    order: list[str]
    buttons: list[MenuButtonUpdate]
    # کلیدهایی که باید قبل‌شان یک ردیف جدید در منو شروع شود؛ اگر ارسال نشود
    # (None) یعنی فرانت‌اند هنوز چیدمان آزاد را ویرایش نکرده و تنظیم قبلی
    # (تعداد ستون ثابت یا چیدمان سفارشی قبلی) دست‌نخورده باقی می‌ماند.
    row_breaks: Optional[list[str]] = None


@app.get("/api/admin/check")
def api_admin_check(auth=Depends(get_verified_user)):
    tg_id, db, _ = auth
    is_admin = db.is_admin(tg_id)
    if is_admin:
        # این اندپوینت هنگام باز شدن پنل ادمین و به‌صورت دوره‌ای (heartbeat) از
        # سمت مینی‌اپ صدا زده می‌شود؛ همین‌جا حضور آنلاین ادمین را هم ثبت می‌کنیم.
        db.touch_admin_presence(tg_id)
    return {"is_admin": is_admin, "admin_role": db.get_admin_role(tg_id)}


@app.get("/api/admin/menu")
def api_admin_get_menu(auth=Depends(require_senior_admin)):
    _, db, _ = auth
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
            "key": key,
            "label": meta["label"],
            "admin_only": meta["admin_only"],
            "has_text": meta["has_text"],
            "has_style": meta["has_style"],
            "togglable": meta["toggle_key"] is not None,
        }
        if meta["has_text"]:
            item["text"] = settings.get(key, "")
        if meta["has_style"]:
            item["style"] = settings.get(f"{key}_style", "")
        if meta["toggle_key"]:
            item["enabled"] = settings.get(meta["toggle_key"], "1") == "1"
        # break_before یعنی این دکمه یک ردیف جدید شروع می‌کند (نه کنار دکمه‌ی
        # قبلی). None یعنی هنوز چیدمان آزاد سفارشی نشده (حالت قدیمی ستون ثابت).
        item["break_before"] = (key in break_set) if break_set is not None else None
        result.append(item)
    return result


@app.post("/api/admin/menu")
def api_admin_save_menu(body: MenuLayoutUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    for btn in body.buttons:
        meta = MENU_BUTTON_META.get(btn.key)
        if not meta:
            continue
        if meta["has_text"] and btn.text is not None and btn.text.strip():
            db.set_setting(btn.key, btn.text.strip())
        if meta["has_style"] and btn.style is not None:
            style = btn.style if btn.style in ("primary", "success", "danger") else ""
            db.set_setting(f"{btn.key}_style", style)
        if meta["toggle_key"] and btn.enabled is not None:
            db.set_setting(meta["toggle_key"], "1" if btn.enabled else "0")
    db.set_menu_order(body.order)
    if body.row_breaks is not None:
        db.set_menu_row_breaks(body.row_breaks)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# بنرهای کاروسل بالای صفحه‌ی خانه‌ی مینی‌اپ
# ---------------------------------------------------------------------------

# مقصدهای مجاز برای ضربه‌زدن روی یک بنر؛ باید دقیقاً با کلیدهای شیء `tabs`
# در app.js (سوییچ تب‌های مینی‌اپ) یکی باشد.
BANNER_NAV_TARGETS = {
    "home", "store", "services", "profile", "wallet", "support", "referral", "test", "wheel", "admin",
}


class BannerItem(BaseModel):
    id: Optional[str] = None
    icon: str = ""
    title: str
    sub: str = ""
    cta: str = ""
    nav: str
    bg: str = ""
    image: Optional[str] = ""
    image_only: bool = False
    enabled: bool = True


class BannersUpdate(BaseModel):
    banners: list[BannerItem]


@app.get("/api/banners")
def api_banners(auth=Depends(get_verified_user)):
    """لیست بنرهای فعال کاروسل خانه (برای نمایش به همه‌ی کاربران)."""
    _, db, _ = auth
    banners = db.get_banners()
    return [b for b in banners if b.get("enabled", True)]


@app.get("/api/admin/banners")
def api_admin_get_banners(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    return db.get_banners()


@app.post("/api/admin/banners/upload-image")
async def api_admin_upload_banner_image(photo: UploadFile = File(...), auth=Depends(require_senior_admin)):
    """آپلود عکس آماده برای یک بنر؛ به‌صورت data URI برمی‌گردد تا در فرم بنر
    ذخیره و همراه بقیه‌ی بنرها با POST /api/admin/banners ثبت شود."""
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="فقط فایل عکس پذیرفته می‌شود.")
    photo_bytes = await photo.read()
    if len(photo_bytes) > MAX_HEADER_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="حجم عکس نباید بیشتر از ۲ مگابایت باشد.")
    data_uri = f"data:{photo.content_type};base64,{base64.b64encode(photo_bytes).decode('ascii')}"
    return {"status": "ok", "image": data_uri}


@app.post("/api/admin/banners")
def api_admin_save_banners(body: BannersUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if len(body.banners) > 20:
        raise HTTPException(status_code=400, detail="حداکثر ۲۰ بنر مجاز است.")
    clean = []
    for idx, b in enumerate(body.banners):
        title = b.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail=f"عنوان بنر شماره {idx + 1} نمی‌تواند خالی باشد.")
        if len(title) > 40:
            raise HTTPException(status_code=400, detail=f"عنوان بنر شماره {idx + 1} بیش از حد طولانی است.")
        sub = b.sub.strip()
        if len(sub) > 120:
            raise HTTPException(status_code=400, detail=f"توضیح بنر شماره {idx + 1} بیش از حد طولانی است.")
        cta = b.cta.strip() or "مشاهده"
        if len(cta) > 30:
            raise HTTPException(status_code=400, detail=f"متن دکمه‌ی بنر شماره {idx + 1} بیش از حد طولانی است.")
        if b.nav not in BANNER_NAV_TARGETS:
            raise HTTPException(status_code=400, detail=f"مقصد بنر شماره {idx + 1} نامعتبر است.")
        image = (b.image or "").strip()
        if image and not image.startswith("data:image/"):
            raise HTTPException(status_code=400, detail=f"تصویر بنر شماره {idx + 1} نامعتبر است.")
        if len(image) > 2_900_000:  # ~2MB فایل اصلی بعد از base64 حدوداً همین اندازه می‌شود
            raise HTTPException(status_code=400, detail=f"حجم تصویر بنر شماره {idx + 1} بیش از حد مجاز است.")
        bg = b.bg.strip() or "linear-gradient(120deg, #0d1420, #142845 55%, #1c3f6e)"
        clean.append({
            "id": b.id or f"b_{secrets.token_hex(4)}",
            "icon": (b.icon or "✨").strip()[:8],
            "title": title,
            "sub": sub,
            "cta": cta,
            "nav": b.nav,
            "bg": bg,
            "image": image,
            "image_only": bool(b.image_only) and bool(image),
            "enabled": bool(b.enabled),
        })
    db.set_banners(clean)
    return {"status": "ok", "banners": clean}


# ---------------------------------------------------------------------------
# مدیریت (فقط ادمین) - دسته‌بندی‌ها و محصولات
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    name: str


class CategoryUpdate(BaseModel):
    name: str


class ProductCreate(BaseModel):
    category_id: int
    name: str
    price: int
    description: str = ""
    duration_days: int = 30
    is_auto_provision: bool = False
    auto_provision_volume_gb: Optional[int] = None
    provision_server_id: Optional[int] = None
    payment_methods: Optional[List[str]] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None
    description: Optional[str] = None
    duration_days: Optional[int] = None


class ConfigsAdd(BaseModel):
    links: list[str]


@app.get("/api/admin/categories")
def api_admin_list_categories(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    cats = db.get_categories(active_only=False)
    result = []
    for c in cats:
        products = db.get_products(c["id"], active_only=False)
        result.append({
            "id": c["id"], "name": c["name"], "is_active": bool(c["is_active"]),
            "product_count": len(products),
        })
    return result


@app.post("/api/admin/categories")
def api_admin_create_category(body: CategoryCreate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="نام دسته‌بندی نمی‌تواند خالی باشد.")
    cat_id = db.add_category(body.name.strip())
    return {"id": cat_id}


@app.patch("/api/admin/categories/{cat_id}")
def api_admin_edit_category(cat_id: int, body: CategoryUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not db.get_category(cat_id):
        raise HTTPException(status_code=404, detail="دسته‌بندی یافت نشد.")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="نام دسته‌بندی نمی‌تواند خالی باشد.")
    db.edit_category(cat_id, body.name.strip())
    return {"status": "ok"}


@app.post("/api/admin/categories/{cat_id}/toggle")
def api_admin_toggle_category(cat_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not db.get_category(cat_id):
        raise HTTPException(status_code=404, detail="دسته‌بندی یافت نشد.")
    db.toggle_category(cat_id)
    return {"status": "ok"}


@app.delete("/api/admin/categories/{cat_id}")
def api_admin_delete_category(cat_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not db.get_category(cat_id):
        raise HTTPException(status_code=404, detail="دسته‌بندی یافت نشد.")
    db.delete_category(cat_id)
    return {"status": "ok"}


class PanelServerCreate(BaseModel):
    name: str
    panel_type: str = "pasarguard"
    api_url: str
    api_username: str
    api_password: str
    template_username: Optional[str] = None


class PanelServerUpdate(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    api_username: Optional[str] = None
    api_password: Optional[str] = None


class PanelServerSetTemplate(BaseModel):
    template_username: str


class PanelServerXuiConfig(BaseModel):
    inbound_ids: Optional[List[int]] = None
    sub_base_url: str


class PricingTierCreate(BaseModel):
    from_gb: int
    to_gb: Optional[int] = None  # None یعنی تا بی‌نهایت
    price_per_gb: int


class CustomConfigSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    min_gb: Optional[int] = None
    max_gb: Optional[int] = None


def _panel_server_public(s) -> dict:
    is_sub_base_type = s["panel_type"] in SUB_BASE_URL_PANEL_TYPES
    xui_inbound_ids = parse_xui_inbound_ids(s) if s["panel_type"] in INBOUND_SELECT_PANEL_TYPES else []
    if is_sub_base_type:
        needs_inbound = s["panel_type"] in INBOUND_SELECT_PANEL_TYPES
        configured = bool(s["xui_sub_base_url"]) and (bool(xui_inbound_ids) if needs_inbound else True)
    else:
        configured = bool(s["group_ids"] and s["proxy_settings"])
    return {
        "id": s["id"], "name": s["name"], "panel_type": s["panel_type"],
        "api_url": s["api_url"], "template_username": s["template_username"],
        "has_template": bool(s["group_ids"] and s["proxy_settings"]),
        "xui_inbound_ids": xui_inbound_ids, "xui_sub_base_url": s["xui_sub_base_url"],
        "is_configured": configured,
        "used_for_custom_config": bool(s["used_for_custom_config"]),
        "used_for_test_config": bool(s["used_for_test_config"]),
        "default_group": s["default_group"], "is_active": bool(s["is_active"]),
    }


@app.get("/api/admin/panel-servers")
def api_admin_list_panel_servers(auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    return [_panel_server_public(s) for s in db.get_panel_servers()]


@app.post("/api/admin/panel-servers")
async def api_admin_add_panel_server(body: PanelServerCreate, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    admin_id, _, _ = auth
    if not body.name.strip() or not body.api_url.strip() or not body.api_username.strip() or not body.api_password.strip():
        raise HTTPException(status_code=400, detail="نام، آدرس، یوزرنیم و پسورد الزامی هستند.")
    if body.panel_type not in PROVIDERS:
        raise HTTPException(status_code=400, detail="نوع پنل پشتیبانی نمی‌شود.")

    if body.panel_type in INBOUND_SELECT_PANEL_TYPES:
        server_id = db.add_panel_server(
            body.name.strip(), body.panel_type, body.api_url.strip(),
            body.api_username.strip(), body.api_password,
        )
        server = db.get_panel_server(server_id)
        try:
            provider = get_provider(server)
            inbounds = await provider.list_inbounds()
        except PanelError as e:
            db.delete_panel_server(server_id)
            raise HTTPException(status_code=400, detail=str(e))
        if not inbounds:
            db.delete_panel_server(server_id)
            raise HTTPException(status_code=400, detail="این پنل هیچ inbound ای ندارد. اول از داخل پنل یک inbound بساز.")
        db.log_admin_action(admin_id, "panel_server_add", f"سرور «{body.name}» (3X-UI, #{server_id}) از مینی‌اپ")
        return {"id": server_id, "inbounds": inbounds}

    if body.panel_type in SUB_BASE_URL_PANEL_TYPES:
        # مثل Hiddify: inbound لازم نیست؛ سرور همین‌جا ساخته می‌شود و بعد باید
        # با فراخوانی /xui-config (فقط با sub_base_url، بدون inbound_id) تکمیل شود.
        server_id = db.add_panel_server(
            body.name.strip(), body.panel_type, body.api_url.strip(),
            body.api_username.strip(), body.api_password,
        )
        db.log_admin_action(admin_id, "panel_server_add", f"سرور «{body.name}» (#{server_id}) از مینی‌اپ")
        return {"id": server_id, "needs_sub_base_url": True}

    # پنل‌های خانواده‌ی PasarGuard/Marzban/Marzneshin
    if not body.template_username or not body.template_username.strip():
        raise HTTPException(status_code=400, detail="نام کاربری نمونه الزامی است.")
    server_id = db.add_panel_server(
        body.name.strip(), body.panel_type, body.api_url.strip(),
        body.api_username.strip(), body.api_password,
    )
    server = db.get_panel_server(server_id)
    try:
        provider = get_provider(server)
        template = await provider.fetch_template_from_user(body.template_username.strip())
    except PanelError as e:
        db.delete_panel_server(server_id)
        raise HTTPException(status_code=400, detail=str(e))
    db.update_panel_server(
        server_id, group_ids=json.dumps(template["group_ids"]),
        proxy_settings=json.dumps(template["proxy_settings"]),
        template_username=body.template_username.strip(),
    )
    db.log_admin_action(admin_id, "panel_server_add", f"سرور «{body.name}» (#{server_id}) از مینی‌اپ")
    return {"id": server_id}


@app.get("/api/admin/panel-servers/{server_id}/xui-inbounds")
async def api_admin_list_xui_inbounds(server_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    if server["panel_type"] != "3xui":
        raise HTTPException(status_code=400, detail="این سرور از نوع 3X-UI نیست.")
    try:
        provider = get_provider(server)
        inbounds = await provider.list_inbounds()
    except PanelError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return inbounds


@app.post("/api/admin/panel-servers/{server_id}/xui-config")
async def api_admin_set_xui_config(server_id: int, body: PanelServerXuiConfig, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    if server["panel_type"] not in SUB_BASE_URL_PANEL_TYPES:
        raise HTTPException(status_code=400, detail="این سرور به این تنظیمات نیاز ندارد.")
    if server["panel_type"] in INBOUND_SELECT_PANEL_TYPES and not body.inbound_ids:
        raise HTTPException(status_code=400, detail="انتخاب حداقل یک inbound برای این نوع پنل الزامی است.")
    url = body.sub_base_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="آدرس Subscription باید با http:// یا https:// شروع شود.")
    update_kwargs = {"xui_sub_base_url": url}
    if body.inbound_ids:
        update_kwargs["xui_inbound_ids"] = json.dumps(body.inbound_ids)
    db.update_panel_server(server_id, **update_kwargs)
    return {"status": "ok"}


@app.patch("/api/admin/panel-servers/{server_id}")
def api_admin_edit_panel_server(server_id: int, body: PanelServerUpdate, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if not db.get_panel_server(server_id):
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    db.update_panel_server(
        server_id, name=body.name, api_url=body.api_url,
        api_username=body.api_username, api_password=body.api_password,
    )
    return {"status": "ok"}


@app.post("/api/admin/panel-servers/{server_id}/template")
async def api_admin_set_panel_server_template(server_id: int, body: PanelServerSetTemplate, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    try:
        provider = get_provider(server)
        template = await provider.fetch_template_from_user(body.template_username.strip())
    except PanelError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.update_panel_server(
        server_id, group_ids=json.dumps(template["group_ids"]),
        proxy_settings=json.dumps(template["proxy_settings"]),
        template_username=body.template_username.strip(),
    )
    return {"status": "ok"}


@app.post("/api/admin/panel-servers/{server_id}/toggle")
def api_admin_toggle_panel_server(server_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    db.update_panel_server(server_id, is_active=0 if server["is_active"] else 1)
    return {"status": "ok"}


@app.post("/api/admin/panel-servers/{server_id}/usage/{kind}")
def api_admin_toggle_panel_server_usage(server_id: int, kind: str, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if kind not in ("custom", "test"):
        raise HTTPException(status_code=400, detail="نوع مصرف نامعتبر است.")
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    field = "used_for_custom_config" if kind == "custom" else "used_for_test_config"
    db.update_panel_server(server_id, **{field: 0 if server[field] else 1})
    return {"status": "ok"}


@app.post("/api/admin/panel-servers/{server_id}/test")
async def api_admin_test_panel_server(server_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    server = db.get_panel_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    try:
        provider = get_provider(server)
        ok = await provider.test_connection()
    except PanelError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": ok}


@app.delete("/api/admin/panel-servers/{server_id}")
def api_admin_delete_panel_server(server_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    admin_id, _, _ = auth
    if not db.get_panel_server(server_id):
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    db.delete_panel_server(server_id)
    db.log_admin_action(admin_id, "panel_server_delete", f"سرور #{server_id} از مینی‌اپ")
    return {"status": "ok"}


@app.get("/api/admin/custom-config/settings")
def api_admin_get_custom_config_settings(auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    return db.get_custom_config_settings()


@app.post("/api/admin/custom-config/settings")
def api_admin_update_custom_config_settings(body: CustomConfigSettingsUpdate, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if body.enabled is not None:
        db.set_setting("custom_config_enabled", "1" if body.enabled else "0")
    if body.min_gb is not None:
        if body.min_gb <= 0:
            raise HTTPException(status_code=400, detail="حداقل حجم باید بزرگ‌تر از صفر باشد.")
        db.set_setting("custom_config_min_gb", str(body.min_gb))
    if body.max_gb is not None:
        min_gb = body.min_gb if body.min_gb is not None else db.get_custom_config_settings()["min_gb"]
        if body.max_gb <= min_gb:
            raise HTTPException(status_code=400, detail="حداکثر حجم باید بزرگ‌تر از حداقل باشد.")
        db.set_setting("custom_config_max_gb", str(body.max_gb))
    return {"status": "ok"}


def _serialize_test_plan(db, p) -> dict:
    server = db.get_panel_server(p["panel_server_id"])
    return {
        "id": p["id"], "name": p["name"], "name_prefix": p["name_prefix"],
        "panel_server_id": p["panel_server_id"], "panel_server_name": server["name"] if server else None,
        "volume_mb": p["volume_mb"], "duration_hours": p["duration_hours"],
        "is_active": bool(p["is_active"]), "sort_order": p["sort_order"],
    }


class TestPlanBody(BaseModel):
    name: str
    name_prefix: str
    panel_server_id: int
    volume_mb: int
    duration_hours: int


@app.get("/api/admin/test-config/plans")
def api_admin_list_test_plans(auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    return [_serialize_test_plan(db, p) for p in db.get_test_config_plans()]


@app.post("/api/admin/test-config/plans")
def api_admin_create_test_plan(body: TestPlanBody, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="نام پلن الزامی است.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", body.name_prefix.strip()):
        raise HTTPException(status_code=400, detail="پیشوند نام کاربری فقط باید شامل حروف/عدد انگلیسی و آندرلاین باشد.")
    if body.volume_mb <= 0 or body.duration_hours <= 0:
        raise HTTPException(status_code=400, detail="حجم و مدت باید بزرگ‌تر از صفر باشند.")
    server = db.get_panel_server(body.panel_server_id)
    if not server or not server["is_active"]:
        raise HTTPException(status_code=400, detail="پنل انتخاب‌شده یافت نشد یا غیرفعال است.")
    plan_id = db.create_test_config_plan(
        body.name.strip(), body.name_prefix.strip(), body.panel_server_id, body.volume_mb, body.duration_hours,
    )
    return _serialize_test_plan(db, db.get_test_config_plan(plan_id))


@app.put("/api/admin/test-config/plans/{plan_id}")
def api_admin_update_test_plan(plan_id: int, body: TestPlanBody, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if not db.get_test_config_plan(plan_id):
        raise HTTPException(status_code=404, detail="این پلن یافت نشد.")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="نام پلن الزامی است.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", body.name_prefix.strip()):
        raise HTTPException(status_code=400, detail="پیشوند نام کاربری فقط باید شامل حروف/عدد انگلیسی و آندرلاین باشد.")
    if body.volume_mb <= 0 or body.duration_hours <= 0:
        raise HTTPException(status_code=400, detail="حجم و مدت باید بزرگ‌تر از صفر باشند.")
    server = db.get_panel_server(body.panel_server_id)
    if not server or not server["is_active"]:
        raise HTTPException(status_code=400, detail="پنل انتخاب‌شده یافت نشد یا غیرفعال است.")
    db.update_test_config_plan(
        plan_id, name=body.name.strip(), name_prefix=body.name_prefix.strip(),
        panel_server_id=body.panel_server_id, volume_mb=body.volume_mb, duration_hours=body.duration_hours,
    )
    return _serialize_test_plan(db, db.get_test_config_plan(plan_id))


@app.post("/api/admin/test-config/plans/{plan_id}/toggle")
def api_admin_toggle_test_plan(plan_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if not db.get_test_config_plan(plan_id):
        raise HTTPException(status_code=404, detail="این پلن یافت نشد.")
    db.toggle_test_config_plan(plan_id)
    return _serialize_test_plan(db, db.get_test_config_plan(plan_id))


@app.delete("/api/admin/test-config/plans/{plan_id}")
def api_admin_delete_test_plan(plan_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if not db.get_test_config_plan(plan_id):
        raise HTTPException(status_code=404, detail="این پلن یافت نشد.")
    db.delete_test_config_plan(plan_id)
    return {"status": "ok"}


@app.get("/api/admin/custom-config/pricing-tiers")
def api_admin_list_pricing_tiers(auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    tiers = db.get_pricing_tiers()
    return [
        {"id": t["id"], "from_gb": t["from_gb"], "to_gb": t["to_gb"], "price_per_gb": t["price_per_gb"]}
        for t in tiers
    ]


@app.post("/api/admin/custom-config/pricing-tiers")
def api_admin_add_pricing_tier(body: PricingTierCreate, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if body.from_gb <= 0 or body.price_per_gb <= 0:
        raise HTTPException(status_code=400, detail="مقادیر باید مثبت باشند.")
    if body.to_gb is not None and body.to_gb <= body.from_gb:
        raise HTTPException(status_code=400, detail="انتهای بازه باید بزرگ‌تر از ابتدای آن باشد.")
    tier_id = db.add_pricing_tier(body.from_gb, body.to_gb, body.price_per_gb)
    return {"id": tier_id}


@app.delete("/api/admin/custom-config/pricing-tiers/{tier_id}")
def api_admin_delete_pricing_tier(tier_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    db.delete_pricing_tier(tier_id)
    return {"status": "ok"}


@app.get("/api/admin/panel-servers-lite")
def api_admin_panel_servers_lite(auth=Depends(require_senior_admin)):
    """لیست سبک پنل‌ها (فقط id/name) برای انتخاب پنل موقع ساخت محصول اتصال مستقیم.
    مثل بات و پنل وب مستقل، این گزینه فقط برای بات اصلی یا نمایندگی سطح کامل است."""
    _, db, tenant = auth
    if not db.is_full_access_bot(not tenant.tenant_id):
        raise HTTPException(status_code=403, detail="این بخش فقط برای بات اصلی یا نمایندگی کامل در دسترس است.")
    return [{"id": s["id"], "name": s["name"]} for s in db.get_panel_servers(active_only=True)]


@app.get("/api/admin/categories/{cat_id}/products")
def api_admin_list_products(cat_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    products = db.get_products(cat_id, active_only=False)
    return [
        {
            "id": p["id"], "name": p["name"], "price": p["price"],
            "description": p["description"], "duration_days": p["duration_days"],
            "is_active": bool(p["is_active"]),
            "is_auto_provision": bool(p["is_auto_provision"]),
            "provision_server_id": p["provision_server_id"],
            "auto_provision_volume_gb": p["auto_provision_volume_gb"],
            "stock": None if p["is_auto_provision"] else db.count_available_configs(p["id"]),
        }
        for p in products
    ]


@app.get("/api/admin/products/all")
def api_admin_list_all_products(auth=Depends(require_senior_admin)):
    """لیست همه‌ی محصولات (از همه‌ی دسته‌بندی‌ها، فعال و غیرفعال) - برای مصارفی مثل
    انتخاب «محصول جایزه» در تنظیمات زیرمجموعه‌گیری."""
    _, db, _ = auth
    products = db.get_all_products()
    return [
        {
            "id": p["id"], "name": p["name"], "category_name": p["category_name"],
            "is_active": bool(p["is_active"]),
            "is_auto_provision": bool(p["is_auto_provision"]),
            "provision_server_id": p["provision_server_id"],
        }
        for p in products
    ]


@app.post("/api/admin/products")
def api_admin_create_product(body: ProductCreate, auth=Depends(require_senior_admin)):
    _, db, tenant = auth
    if not db.get_category(body.category_id):
        raise HTTPException(status_code=404, detail="دسته‌بندی یافت نشد.")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="نام محصول نمی‌تواند خالی باشد.")
    if body.price < 0:
        raise HTTPException(status_code=400, detail="قیمت نامعتبر است.")

    is_full_access = db.is_full_access_bot(not tenant.tenant_id)
    provision_server_id = body.provision_server_id if is_full_access else None
    is_auto_provision = bool(body.is_auto_provision or provision_server_id)
    if is_auto_provision and not body.auto_provision_volume_gb:
        raise HTTPException(status_code=400, detail="برای اتصال مستقیم به پنل باید حجم (گیگابایت) را مشخص کنید.")

    product_id = db.add_product(
        body.category_id, body.name.strip(), body.price, body.description, body.duration_days,
        is_auto_provision=is_auto_provision, auto_provision_volume_gb=body.auto_provision_volume_gb,
        provision_server_id=provision_server_id, payment_methods=body.payment_methods,
    )
    return {"id": product_id}


@app.get("/api/admin/payment-methods")
def api_admin_payment_methods(auth=Depends(require_senior_admin)):
    """لیست کامل روش‌های پرداخت (داخلی + درگاه‌های سفارشی) برای انتخاب حین ساخت محصول."""
    _, db, _ = auth
    return db.get_payment_methods_catalog()


@app.patch("/api/admin/products/{product_id}")
def api_admin_edit_product(product_id: int, body: ProductUpdate, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    old_product = db.get_product(product_id)
    if not old_product:
        raise HTTPException(status_code=404, detail="محصول یافت نشد.")
    if body.price is not None and body.price < 0:
        raise HTTPException(status_code=400, detail="قیمت نامعتبر است.")
    db.edit_product(
        product_id,
        name=body.name.strip() if body.name else None,
        price=body.price,
        description=body.description,
        duration_days=body.duration_days,
    )
    if body.price is not None and body.price != old_product["price"]:
        db.log_admin_action(
            admin_id, "product_price_edit",
            f"محصول «{old_product['name']}» (#{product_id}) | قیمت قبلی: {old_product['price']:,} | قیمت جدید: {body.price:,}",
        )
    return {"status": "ok"}


@app.post("/api/admin/products/{product_id}/toggle")
def api_admin_toggle_product(product_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not db.get_product(product_id):
        raise HTTPException(status_code=404, detail="محصول یافت نشد.")
    db.toggle_product(product_id)
    return {"status": "ok"}


@app.delete("/api/admin/products/{product_id}")
def api_admin_delete_product(product_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not db.get_product(product_id):
        raise HTTPException(status_code=404, detail="محصول یافت نشد.")
    db.delete_product(product_id)
    return {"status": "ok"}


@app.get("/api/admin/products/{product_id}/configs")
def api_admin_list_configs(product_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if not db.get_product(product_id):
        raise HTTPException(status_code=404, detail="محصول یافت نشد.")
    rows = db.get_unused_configs(product_id)
    return [{"id": r["id"], "link": r["link"]} for r in rows]


@app.post("/api/admin/products/{product_id}/configs")
def api_admin_add_configs(product_id: int, body: ConfigsAdd, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    if not db.get_product(product_id):
        raise HTTPException(status_code=404, detail="محصول یافت نشد.")
    links = [l.strip() for l in body.links if l.strip()]
    if not links:
        raise HTTPException(status_code=400, detail="هیچ لینک معتبری وارد نشده است.")
    db.add_configs(product_id, links)
    return {"added": len(links)}


@app.delete("/api/admin/configs/{config_id}")
def api_admin_delete_config(config_id: int, auth=Depends(require_full_access_admin)):
    _, db, _ = auth
    db.delete_config(config_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# مدیریت نمایندگی‌ها (فقط بات اصلی)
# ---------------------------------------------------------------------------

class ResellerTokenCheck(BaseModel):
    token: str


class ResellerCreate(BaseModel):
    token: str
    username: str
    owner_telegram_id: int
    owner_name: str = ""


class ResellerUpdate(BaseModel):
    owner_telegram_id: Optional[int] = None
    owner_name: Optional[str] = None


class ResellerTokenUpdate(BaseModel):
    token: str


def _reseller_miniapp_link(reseller_row) -> Optional[str]:
    """لینک اختصاصی مینی‌اپ همین نماینده (همان که در دکمه‌ی منوی بات نماینده استفاده می‌شود)."""
    if not MINIAPP_URL:
        return None
    b_value = reseller_row["link_slug"] or str(reseller_row["id"])
    sep = "&" if "?" in MINIAPP_URL else "?"
    return f"{MINIAPP_URL}{sep}b={b_value}"


# ---------------------------------------------------------------------------
# نمایندگان اعتباری (Credit Resellers) - معادل adm_credit_resellers_menu/
# adm_cres_* در ربات؛ قبلاً این بخش فقط داخل ربات در دسترس بود.
# متمایز از بخش «resellers» زیر که مربوط به بات‌های نمایندگی زیرمجموعه (white-label) است.
# ---------------------------------------------------------------------------

def _credit_reseller_to_dict(user_id: int, db: Database) -> dict:
    user = db.get_user(user_id)
    return {
        "telegram_id": user_id,
        "first_name": user["first_name"] if user else None,
        "username": user["username"] if user else None,
        "is_reseller": db.is_reseller(user_id),
        "credit_gb": db.get_reseller_credit(user_id),
        "panel_server_id": user["reseller_panel_id"] if user else None,
    }


@app.get("/api/admin/credit-resellers")
def api_admin_list_credit_resellers(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    rows = db.get_resellers()
    return [
        {
            "telegram_id": r["telegram_id"], "first_name": r["first_name"],
            "username": r["username"], "credit_gb": r["reseller_credit_gb"],
            "panel_server_id": r["reseller_panel_id"], "is_reseller": True,
        }
        for r in rows
    ]


@app.get("/api/admin/credit-resellers/{telegram_id}")
def api_admin_get_credit_reseller(telegram_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    user = db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="این کاربر هنوز با /start بات را استارت نکرده است.")
    info = _credit_reseller_to_dict(telegram_id, db)
    info["credit_log"] = [
        {"delta_gb": l["delta_gb"], "reason": l["reason"], "created_at": l["created_at"]}
        for l in db.get_reseller_credit_log(telegram_id)
    ]
    return info


@app.post("/api/admin/credit-resellers/{telegram_id}/toggle")
def api_admin_toggle_credit_reseller(telegram_id: int, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    if not db.get_user(telegram_id):
        raise HTTPException(status_code=404, detail="این کاربر هنوز با /start بات را استارت نکرده است.")
    db.set_reseller_status(telegram_id, not db.is_reseller(telegram_id))
    db.log_admin_action(admin_id, "reseller_credit_toggle", f"کاربر {telegram_id} (مینی‌اپ)")
    return _credit_reseller_to_dict(telegram_id, db)


class CreditAdjust(BaseModel):
    delta_gb: int
    reason: Optional[str] = None


@app.post("/api/admin/credit-resellers/{telegram_id}/credit")
def api_admin_adjust_credit_reseller(telegram_id: int, body: CreditAdjust, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    if not db.get_user(telegram_id):
        raise HTTPException(status_code=404, detail="این کاربر هنوز با /start بات را استارت نکرده است.")
    if body.delta_gb == 0:
        raise HTTPException(status_code=400, detail="مقدار تغییر نمی‌تواند صفر باشد.")
    db.adjust_reseller_credit(
        telegram_id, body.delta_gb, admin_id=admin_id,
        reason=body.reason or "تنظیم دستی توسط ادمین (مینی‌اپ)",
    )
    db.log_admin_action(admin_id, "reseller_credit_adjust", f"کاربر {telegram_id} | {body.delta_gb:+} گیگ (مینی‌اپ)")
    return _credit_reseller_to_dict(telegram_id, db)


class CreditResellerPanelSet(BaseModel):
    panel_server_id: Optional[int] = None


@app.post("/api/admin/credit-resellers/{telegram_id}/panel")
def api_admin_set_credit_reseller_panel(telegram_id: int, body: CreditResellerPanelSet, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    if not db.get_user(telegram_id):
        raise HTTPException(status_code=404, detail="این کاربر هنوز با /start بات را استارت نکرده است.")
    if body.panel_server_id and not db.get_panel_server(body.panel_server_id):
        raise HTTPException(status_code=404, detail="سرور یافت نشد.")
    db.set_reseller_panel(telegram_id, body.panel_server_id)
    db.log_admin_action(admin_id, "reseller_credit_panel_set", f"کاربر {telegram_id} (مینی‌اپ)")
    return _credit_reseller_to_dict(telegram_id, db)


# ---------------------------------------------------------------------------
# درخواست‌های نمایندگی (Reseller Requests) - معادل resreq_* در ربات و
# /api/reseller-requests در پنل وب مستقل؛ قبلاً در مینی‌اپ اصلاً وجود نداشت.
# فقط در بات اصلی معنا دارد (کاربر با آن صاحب یک بات نمایندگی زیرمجموعه‌ی
# جدید می‌شود)، بنابراین require_main_admin.
# ---------------------------------------------------------------------------

def _set_bot_fsm_state(chat_id: int, state: Optional[str], data: Optional[dict] = None) -> bool:
    """مستقیم روی فایل SQLite استوریج FSM بات اصلی می‌نویسد؛ همان تکنیکی که
    admin_panel/server.py برای هدایت کاربر به مرحله‌ی بعدی فلوی نمایندگی
    استفاده می‌کند (چون این پروسه هم Dispatcher زنده‌ی بات را در اختیار ندارد)."""
    try:
        bot_id = int(BOT_TOKEN.split(":")[0])
        conn = sqlite3.connect(f"{DB_PATH}.fsm.sqlite3", timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=4000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fsm_storage (
                    bot_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                    thread_id INTEGER, business_connection_id TEXT, destiny TEXT NOT NULL DEFAULT 'default',
                    state TEXT, data TEXT,
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
        logging.getLogger("miniapp.fsm").exception("تنظیم FSM state بات اصلی برای %s ناموفق بود.", chat_id)
        return False


@app.get("/api/admin/reseller-requests")
def api_admin_reseller_requests(status: Optional[str] = None, auth=Depends(require_main_admin)):
    _, db, _ = auth
    out = []
    for r in db.list_reseller_requests(status):
        r = dict(r)
        user = db.get_user(r["user_id"])
        r["username"] = user["username"] if user else None
        out.append(r)
    return out


@app.get("/api/admin/reseller-requests/{request_id}/receipt")
async def api_admin_reseller_request_receipt(request_id: int, auth=Depends(require_main_admin)):
    _, db, tenant = auth
    req = db.get_reseller_request(request_id)
    if not req or not req["receipt_file_id"]:
        raise HTTPException(status_code=404, detail="رسیدی برای این درخواست ثبت نشده است.")
    result = await _tg_fetch_file(tenant.bot_token, req["receipt_file_id"])
    if not result:
        raise HTTPException(status_code=502, detail="دریافت رسید از تلگرام ناموفق بود.")
    content, content_type = result
    return Response(content=content, media_type=content_type)


class ResellerRequestQuote(BaseModel):
    price_toman: int
    panel_server_id: Optional[int] = None


@app.post("/api/admin/reseller-requests/{request_id}/quote")
async def api_admin_quote_reseller_request(request_id: int, body: ResellerRequestQuote, auth=Depends(require_main_admin)):
    admin_id, db, tenant = auth
    req = db.get_reseller_request(request_id)
    if not req or req["status"] != "pending_review":
        raise HTTPException(status_code=400, detail="این درخواست دیگر معتبر نیست.")
    if body.price_toman <= 0:
        raise HTTPException(status_code=400, detail="هزینه باید عددی مثبت باشد.")
    db.quote_reseller_request(request_id, body.price_toman, body.panel_server_id, admin_id)
    db.log_admin_action(admin_id, "reseller_request_quote", f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {body.price_toman:,} (مینی‌اپ)")
    await _tg_notify(
        tenant.bot_token, req["user_id"],
        f"🏪 درخواست نمایندگی #{request_id} شما تایید شد!\n\n"
        f"💰 هزینه‌ی نمایندگی: {body.price_toman:,} تومان\n"
        f"📦 حجم: {req['volume_gb']:,} گیگ\n\nدر صورت موافقت از داخل بات روی «پرداخت می‌کنم» بزنید.",
    )
    return {"ok": True}


@app.post("/api/admin/reseller-requests/{request_id}/approve-payment")
async def api_admin_approve_reseller_request_payment(request_id: int, auth=Depends(require_main_admin)):
    admin_id, db, tenant = auth
    req = db.get_reseller_request(request_id)
    if not req or req["status"] != "awaiting_payment_review":
        raise HTTPException(status_code=400, detail="این درخواست دیگر معتبر نیست.")
    db.approve_reseller_request_payment(request_id, admin_id)
    db.log_admin_action(admin_id, "reseller_request_payment_approve", f"درخواست #{request_id} | کاربر {req['user_id']} (مینی‌اپ)")
    _set_bot_fsm_state(req["user_id"], "ResellerRequestFlow:waiting_bot_token", {"resreq_request_id": request_id})
    await _tg_notify(
        tenant.bot_token, req["user_id"],
        "✅ پرداخت شما تایید شد!\n\nحالا از داخل بات، توکن بات نماینده‌ی خودتان را ارسال کنید (همانی که از @BotFather گرفته‌اید):",
    )
    return {"ok": True}


class ResellerRequestReject(BaseModel):
    reason: str
    kind: str = "rejected"


@app.post("/api/admin/reseller-requests/{request_id}/reject")
async def api_admin_reject_reseller_request(request_id: int, body: ResellerRequestReject, auth=Depends(require_main_admin)):
    admin_id, db, tenant = auth
    if body.kind not in ("rejected", "payment_rejected"):
        raise HTTPException(status_code=400, detail="نوع رد نامعتبر است.")
    req = db.get_reseller_request(request_id)
    if not req or not db.is_reseller_request_open(req["status"]):
        raise HTTPException(status_code=400, detail="این درخواست دیگر باز نیست.")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="دلیل رد الزامی است.")
    db.reject_reseller_request(request_id, body.kind, admin_id, reason)
    db.log_admin_action(admin_id, "reseller_request_reject", f"درخواست #{request_id} | کاربر {req['user_id']} | {body.kind}: {reason} (مینی‌اپ)")
    label = "درخواست نمایندگی" if body.kind == "rejected" else "پرداخت درخواست نمایندگی"
    await _tg_notify(tenant.bot_token, req["user_id"], f"❌ متاسفانه {label} شما (#{request_id}) رد شد.\n\nدلیل: {reason}")
    return {"ok": True}


@app.post("/api/admin/reseller-requests/{request_id}/cancel")
async def api_admin_cancel_reseller_request(request_id: int, auth=Depends(require_main_admin)):
    admin_id, db, tenant = auth
    req = db.get_reseller_request(request_id)
    if not req or not db.is_reseller_request_open(req["status"]):
        raise HTTPException(status_code=400, detail="این درخواست دیگر باز نیست.")
    db.admin_cancel_reseller_request(request_id, admin_id)
    if req["status"] == "awaiting_bot_info":
        _set_bot_fsm_state(req["user_id"], None, {})
    db.log_admin_action(admin_id, "reseller_request_admin_cancel", f"درخواست #{request_id} | کاربر {req['user_id']} (مینی‌اپ)")
    await _tg_notify(tenant.bot_token, req["user_id"], f"⚪️ درخواست نمایندگی شما (#{request_id}) توسط مدیریت کنسل شد.")
    return {"ok": True}


@app.get("/api/admin/resellers")
def api_admin_list_resellers(auth=Depends(require_main_admin)):
    _, db, _ = auth
    rows = db.list_reseller_bots()
    return [
        {
            "id": r["id"], "bot_username": r["bot_username"], "owner_telegram_id": r["owner_telegram_id"],
            "owner_name": r["owner_name"], "is_active": bool(r["is_active"]), "created_at": r["created_at"],
            "miniapp_link": _reseller_miniapp_link(r),
            "bot_link": f"https://t.me/{r['bot_username']}",
        }
        for r in rows
    ]


@app.post("/api/admin/resellers/validate")
async def api_admin_validate_reseller_token(body: ResellerTokenCheck, auth=Depends(require_main_admin)):
    _, db, _ = auth
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="توکن نمی‌تواند خالی باشد.")
    for r in db.list_reseller_bots():
        if r["bot_token"] == token:
            raise HTTPException(status_code=400, detail="این توکن قبلاً ثبت شده است.")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    raise HTTPException(status_code=400, detail="این توکن معتبر نیست.")
                username = data["result"]["username"]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="این توکن معتبر نیست یا تلگرام در دسترس نیست.")
    return {"username": username}


@app.post("/api/admin/resellers")
def api_admin_create_reseller(body: ResellerCreate, auth=Depends(require_main_admin)):
    _, db, _ = auth
    for r in db.list_reseller_bots():
        if r["bot_token"] == body.token:
            raise HTTPException(status_code=400, detail="این توکن قبلاً ثبت شده است.")
    os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
    db_path = os.path.join(RESELLER_DBS_DIR, f"{body.username}.db")
    reseller_id = db.register_reseller_bot(body.token, body.username, body.owner_telegram_id, body.owner_name, db_path)

    # دیتابیس همین نماینده باید بداند شناسه‌ی خودش را تا لینک مینی‌اپ اختصاصی بسازد
    try:
        reseller_db = Database(db_path)
        reseller_db.init_db(owner_id=body.owner_telegram_id)
        reseller_db.set_setting("miniapp_tenant_id", str(reseller_id))
    except Exception:
        logging.getLogger("miniapp.resellers").exception("مقداردهی اولیه دیتابیس نماینده‌ی جدید ناموفق بود.")

    return {
        "id": reseller_id,
        "note": "بات نمایندگی ثبت شد. حداکثر تا ۱۰ ثانیه دیگر توسط بات اصلی خودکار روشن می‌شود.",
    }


@app.patch("/api/admin/resellers/{reseller_id}")
def api_admin_edit_reseller(reseller_id: int, body: ResellerUpdate, auth=Depends(require_main_admin)):
    _, db, _ = auth
    if not db.get_reseller_bot(reseller_id):
        raise HTTPException(status_code=404, detail="نماینده یافت نشد.")
    db.edit_reseller_bot(
        reseller_id,
        owner_telegram_id=body.owner_telegram_id,
        owner_name=body.owner_name.strip() if body.owner_name else None,
    )
    return {"status": "ok"}


@app.patch("/api/admin/resellers/{reseller_id}/token")
async def api_admin_change_reseller_token(reseller_id: int, body: ResellerTokenUpdate, auth=Depends(require_main_admin)):
    _, db, _ = auth
    reseller_bot = db.get_reseller_bot(reseller_id)
    if not reseller_bot:
        raise HTTPException(status_code=404, detail="نماینده یافت نشد.")
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="توکن نمی‌تواند خالی باشد.")
    for r in db.list_reseller_bots():
        if r["id"] != reseller_id and r["bot_token"] == token:
            raise HTTPException(status_code=400, detail="این توکن قبلاً برای نماینده‌ی دیگری ثبت شده است.")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    raise HTTPException(status_code=400, detail="این توکن معتبر نیست.")
                username = data["result"]["username"]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="این توکن معتبر نیست یا تلگرام در دسترس نیست.")
    db.edit_reseller_bot(reseller_id, bot_token=token, bot_username=username)
    return {
        "status": "ok",
        "username": username,
        "note": "توکن بات نماینده تغییر کرد. حداکثر تا ۱۰ ثانیه دیگر بات قدیمی متوقف و بات جدید روشن می‌شود.",
    }


@app.post("/api/admin/resellers/{reseller_id}/regenerate-link")
def api_admin_regenerate_reseller_link(reseller_id: int, auth=Depends(require_main_admin)):
    _, db, _ = auth
    reseller_bot = db.get_reseller_bot(reseller_id)
    if not reseller_bot:
        raise HTTPException(status_code=404, detail="نماینده یافت نشد.")
    if not MINIAPP_URL:
        raise HTTPException(status_code=400, detail="آدرس MINIAPP_URL روی سرور تنظیم نشده است.")
    for _ in range(5):
        slug = secrets.token_urlsafe(8)
        if not db.get_reseller_bot_by_slug(slug):
            break
    else:
        raise HTTPException(status_code=500, detail="ساخت لینک یکتا ممکن نشد، دوباره تلاش کن.")
    db.set_reseller_link_slug(reseller_id, slug)
    reseller_bot = db.get_reseller_bot(reseller_id)
    return {
        "status": "ok",
        "miniapp_link": _reseller_miniapp_link(reseller_bot),
        "note": "لینک قبلی مینی‌اپ این نماینده دیگر کار نمی‌کند؛ فقط لینک جدید معتبر است.",
    }


@app.post("/api/admin/resellers/{reseller_id}/toggle")
def api_admin_toggle_reseller(reseller_id: int, auth=Depends(require_main_admin)):
    _, db, _ = auth
    if not db.get_reseller_bot(reseller_id):
        raise HTTPException(status_code=404, detail="نماینده یافت نشد.")
    db.toggle_reseller_bot(reseller_id)
    return {"status": "ok", "note": "تغییر وضعیت حداکثر تا ۱۰ ثانیه دیگر روی بات اعمال می‌شود."}


@app.delete("/api/admin/resellers/{reseller_id}")
def api_admin_delete_reseller(reseller_id: int, purge_db: bool = Query(False), auth=Depends(require_main_admin)):
    _, db, _ = auth
    reseller_bot = db.get_reseller_bot(reseller_id)
    if not reseller_bot:
        raise HTTPException(status_code=404, detail="نماینده یافت نشد.")
    db.delete_reseller_bot(reseller_id)

    if purge_db:
        resolved_path = resolve_db_path(reseller_bot["db_path"])
        db.queue_db_purge(reseller_bot["bot_token"], resolved_path)

    return {
        "status": "ok",
        "db_purged": False,
        "note": "بات نماینده حداکثر تا ۱۰ ثانیه دیگر متوقف می‌شود"
        + (" و بلافاصله بعد از توقف، فایل دیتابیسش پاک خواهد شد." if purge_db else "."),
    }


# ---------------------------------------------------------------------------
# مدیریت تنظیمات - رفرال / گردونه شانس / یادآوری تمدید (ادمین)
# ---------------------------------------------------------------------------

class ReferralSettingsUpdate(BaseModel):
    enabled: bool
    percent: int
    commission_max_count: int = 0
    free_config_enabled: bool = False
    free_config_threshold: int = 10
    free_config_product_id: Optional[int] = None
    invite_bonus_enabled: bool = False
    invite_bonus_amount: int = 0
    invite_bonus_max_count: int = 0


class WheelSettingsUpdate(BaseModel):
    enabled: bool
    win_percent: int
    prizes: list[int]
    expiry_hours: int
    cooldown_hours: int


class RenewalSettingsUpdate(BaseModel):
    enabled: bool
    days_before: int
    discount_percent: int
    discount_expiry_hours: int


class VolumeReminderSettingsUpdate(BaseModel):
    enabled: bool
    mode: str
    percent: int
    gb_left: float
    discount_percent: int
    discount_expiry_hours: int


class CryptoSettingsUpdate(BaseModel):
    enabled: bool
    usd_to_toman_rate: int
    api_key: Optional[str] = None
    expire_min: Optional[int] = None
    allowed_currencies: Optional[str] = None


class CardSettingsUpdate(BaseModel):
    card_number: str
    card_holder: str


@app.get("/api/admin/settings/referral")
def api_admin_get_referral_settings(auth=Depends(require_senior_admin)):
    _, db, _ = auth
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


@app.post("/api/admin/settings/referral")
def api_admin_set_referral_settings(body: ReferralSettingsUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if body.percent < 0 or body.percent > 100:
        raise HTTPException(status_code=400, detail="درصد باید بین ۰ تا ۱۰۰ باشد.")
    if body.commission_max_count < 0:
        raise HTTPException(status_code=400, detail="سقف تعداد نفرات نمی‌تواند منفی باشد.")
    if body.free_config_threshold < 0 or body.invite_bonus_amount < 0 or body.invite_bonus_max_count < 0:
        raise HTTPException(status_code=400, detail="مقادیر عددی نمی‌توانند منفی باشند.")

    if body.free_config_product_id:
        product = db.get_product(body.free_config_product_id)
        if not product:
            raise HTTPException(status_code=400, detail="محصول جایزه یافت نشد.")
        if not product["is_auto_provision"] or not product["provision_server_id"]:
            raise HTTPException(status_code=400, detail="محصول جایزه باید «تحویل خودکار» داشته باشد و به یک پنل وصل باشد.")
    if body.free_config_enabled and (not body.free_config_product_id or body.free_config_threshold < 1):
        raise HTTPException(status_code=400, detail="برای فعال‌سازی کانفیگ رایگان، محصول جایزه و آستانه‌ی معتبر (حداقل ۱) لازم است.")
    if body.invite_bonus_enabled and body.invite_bonus_amount <= 0:
        raise HTTPException(status_code=400, detail="برای فعال‌سازی شارژ به‌ازای دعوت، مبلغ باید بزرگ‌تر از صفر باشد.")

    db.set_setting("referral_enabled", "1" if body.enabled else "0")
    db.set_setting("referral_percent", str(body.percent))
    db.set_setting("referral_commission_max_count", str(body.commission_max_count))
    db.set_setting("referral_free_config_enabled", "1" if body.free_config_enabled else "0")
    db.set_setting("referral_free_config_threshold", str(body.free_config_threshold))
    db.set_setting("referral_free_config_product_id", str(body.free_config_product_id) if body.free_config_product_id else "")
    db.set_setting("referral_invite_bonus_enabled", "1" if body.invite_bonus_enabled else "0")
    db.set_setting("referral_invite_bonus_amount", str(body.invite_bonus_amount))
    db.set_setting("referral_invite_bonus_max_count", str(body.invite_bonus_max_count))
    return {"status": "ok"}


@app.get("/api/admin/settings/wheel")
def api_admin_get_wheel_settings(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    return db.get_wheel_settings()


@app.post("/api/admin/settings/wheel")
def api_admin_set_wheel_settings(body: WheelSettingsUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if body.win_percent < 0 or body.win_percent > 100:
        raise HTTPException(status_code=400, detail="درصد برد باید بین ۰ تا ۱۰۰ باشد.")
    if not body.prizes or any(p <= 0 for p in body.prizes):
        raise HTTPException(status_code=400, detail="حداقل یک جایزه‌ی معتبر (بزرگ‌تر از صفر) لازم است.")
    if body.expiry_hours <= 0 or body.cooldown_hours <= 0:
        raise HTTPException(status_code=400, detail="مقادیر ساعت باید بزرگ‌تر از صفر باشند.")
    db.set_setting("wheel_enabled", "1" if body.enabled else "0")
    db.set_setting("wheel_win_percent", str(body.win_percent))
    db.set_wheel_prizes(body.prizes)
    db.set_setting("wheel_code_expiry_hours", str(body.expiry_hours))
    db.set_setting("wheel_cooldown_hours", str(body.cooldown_hours))
    return {"status": "ok"}


@app.get("/api/admin/settings/crypto")
def api_admin_get_crypto_settings(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    api_key = _resolve_plisio_key(db)
    return {
        "enabled": db.get_setting("crypto_payment_enabled", "0") == "1",
        "usd_to_toman_rate": int(float(db.get_setting("usd_to_toman_rate", "0") or 0)),
        "has_own_key": bool(db.get_setting("plisio_api_key", "")),
        "masked_key": (f"...{api_key[-4:]}" if api_key else ""),
        "gateway_configured": bool(api_key) and bool(API_BASE_URL),
        "key_source": crypto_payment.resolve_plisio_key_source(db),
        "expire_min": crypto_payment.resolve_expire_min(db),
        "allowed_currencies": crypto_payment.resolve_allowed_currencies(db),
    }


@app.post("/api/admin/settings/crypto")
def api_admin_set_crypto_settings(body: CryptoSettingsUpdate, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    if body.usd_to_toman_rate < 0:
        raise HTTPException(status_code=400, detail="نرخ تبدیل نمی‌تواند منفی باشد.")
    if body.expire_min is not None and body.expire_min <= 0:
        raise HTTPException(status_code=400, detail="مهلت انقضا باید عددی بزرگ‌تر از صفر باشد.")
    if body.api_key is not None:
        new_key = body.api_key.strip()
        db.set_setting("plisio_api_key", new_key)
        db.log_admin_action(admin_id, "plisio_key_change", "API Key کریپتو از مینی‌اپ تغییر کرد." if new_key else "API Key کریپتو از مینی‌اپ حذف شد.")
    api_key = _resolve_plisio_key(db)
    if body.enabled and (not api_key or not API_BASE_URL):
        raise HTTPException(status_code=400, detail="ابتدا کلید API درگاه کریپتو را تنظیم کن. (اگر بازم فعال نمی‌شه، یعنی MINIAPP_URL روی سرور تنظیم نشده.)")
    db.set_setting("crypto_payment_enabled", "1" if body.enabled else "0")
    db.set_setting("usd_to_toman_rate", str(body.usd_to_toman_rate))
    if body.expire_min is not None:
        db.set_setting("crypto_expire_min", str(body.expire_min))
    if body.allowed_currencies is not None:
        cleaned = ",".join(p.strip().upper() for p in body.allowed_currencies.split(",") if p.strip())
        db.set_setting("crypto_allowed_currencies", cleaned)
    return {"status": "ok"}


@app.get("/api/admin/payment-webhook-logs")
def api_admin_payment_webhook_logs(gateway: str = "", limit: int = 50, auth=Depends(require_senior_admin)):
    """لاگ آخرین کال‌بک‌های دریافتی از درگاه‌ها؛ برای دیباگ سریع مشکلاتی مثل
    رد شدن امضا یا برنگشتن تایید پرداخت به بات."""
    _, db, _ = auth
    rows = db.get_recent_webhook_logs(limit=limit, gateway=(gateway or None))
    return {"logs": [dict(r) for r in rows]}


@app.get("/api/admin/reports/gateway-revenue")
def api_admin_gateway_revenue_report(auth=Depends(require_senior_admin)):
    """جمع تراکنش‌های تکمیل‌شده به تفکیک درگاه پرداخت (کریپتو/آبان/سفارشی).
    کارت‌به‌کارت دستی چون invoice مجزا ندارد در این گزارش نیست."""
    _, db, _ = auth
    return {"gateways": db.get_gateway_revenue_report()}


@app.post("/api/admin/settings/crypto/self-test")
def api_admin_crypto_self_test(auth=Depends(require_senior_admin)):
    """بدون نیاز به تراکنش واقعی، بررسی می‌کند که الگوریتم محاسبه‌ی verify_hash با
    یک بدنه‌ی نمونه‌ی حاوی متن فارسی (دقیقاً مثل order_name واقعی) درست کار می‌کند.
    اگر این false برگرداند یعنی هنوز مشکل escape یونیکد وجود دارد."""
    _, db, _ = auth
    api_key = _resolve_plisio_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="ابتدا کلید API کریپتو را تنظیم کن.")
    sample = {
        "txn_id": "self-test-000",
        "order_number": "self-test-000",
        "order_name": "سفارش #۰ - تست خودکار امضا",
        "status": "completed",
    }
    payload = json.dumps(sample, separators=(",", ":"), ensure_ascii=False)
    verify_hash = hmac.new(api_key.encode(), payload.encode("utf-8"), hashlib.sha1).hexdigest()
    sample_with_hash = dict(sample)
    sample_with_hash["verify_hash"] = verify_hash
    ok = plisio_client.verify_callback(api_key, sample_with_hash)
    return {"ok": ok, "message": "امضا با متن فارسی درست تایید شد ✅" if ok else "امضا رد شد ❌ (این خودش یعنی مشکل باقی مانده)"}


@app.get("/api/admin/settings/card")
def api_admin_get_card_settings(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    return {
        "card_number": db.get_setting("card_number", "") or "",
        "card_holder": db.get_setting("card_holder", "") or "",
    }


@app.post("/api/admin/settings/card")
def api_admin_set_card_settings(body: CardSettingsUpdate, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    card_number = body.card_number.strip()
    card_holder = body.card_holder.strip()
    if not card_number or not card_holder:
        raise HTTPException(status_code=400, detail="شماره کارت و نام صاحب کارت نمی‌توانند خالی باشند.")
    db.set_setting("card_number", card_number)
    db.set_setting("card_holder", card_holder)
    db.log_admin_action(admin_id, "card_change", f"شماره کارت جدید: {card_number} | به نام: {card_holder} (مینی‌اپ)")
    return {"status": "ok"}


class AbanGatewaySettingsUpdate(BaseModel):
    enabled: bool
    api_key: Optional[str] = None


@app.get("/api/admin/settings/abangateway")
def api_admin_get_abangateway_settings(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    api_key = _resolve_abangateway_key(db)
    return {
        "enabled": db.get_setting("abangateway_payment_enabled", "0") == "1",
        "has_own_key": bool(db.get_setting("abangateway_api_key", "")),
        "masked_key": (f"...{api_key[-4:]}" if api_key else ""),
        "gateway_configured": bool(api_key) and bool(API_BASE_URL),
        "key_source": abangateway_payment.resolve_api_key_source(db),
    }


@app.post("/api/admin/settings/abangateway")
def api_admin_set_abangateway_settings(body: AbanGatewaySettingsUpdate, auth=Depends(require_senior_admin)):
    admin_id, db, _ = auth
    if body.api_key is not None:
        new_key = body.api_key.strip()
        db.set_setting("abangateway_api_key", new_key)
        db.log_admin_action(admin_id, "abangateway_key_change", "API Key آبان گیت وی از مینی‌اپ تغییر کرد." if new_key else "API Key آبان گیت وی از مینی‌اپ حذف شد.")
    api_key = _resolve_abangateway_key(db)
    if body.enabled and (not api_key or not API_BASE_URL):
        raise HTTPException(status_code=400, detail="ابتدا کلید API آبان گیت وی را تنظیم کن. (اگر بازم فعال نمی‌شه، یعنی MINIAPP_URL روی سرور تنظیم نشده.)")
    db.set_setting("abangateway_payment_enabled", "1" if body.enabled else "0")
    return {"status": "ok"}


@app.get("/api/admin/settings/renewal")
def api_admin_get_renewal_settings(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    return db.get_renewal_settings()


@app.post("/api/admin/settings/renewal")
def api_admin_set_renewal_settings(body: RenewalSettingsUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if body.discount_percent < 0 or body.discount_percent > 100:
        raise HTTPException(status_code=400, detail="درصد تخفیف باید بین ۰ تا ۱۰۰ باشد.")
    if body.days_before <= 0 or body.discount_expiry_hours <= 0:
        raise HTTPException(status_code=400, detail="مقادیر روز/ساعت باید بزرگ‌تر از صفر باشند.")
    db.set_setting("renewal_reminder_enabled", "1" if body.enabled else "0")
    db.set_setting("renewal_reminder_days_before", str(body.days_before))
    db.set_setting("renewal_discount_percent", str(body.discount_percent))
    db.set_setting("renewal_discount_expiry_hours", str(body.discount_expiry_hours))
    return {"status": "ok"}


@app.get("/api/admin/settings/volume-reminder")
def api_admin_get_volume_reminder_settings(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    return db.get_volume_reminder_settings()


@app.post("/api/admin/settings/volume-reminder")
def api_admin_set_volume_reminder_settings(body: VolumeReminderSettingsUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if body.mode not in ("percent", "gb"):
        raise HTTPException(status_code=400, detail="مبنای آستانه باید percent یا gb باشد.")
    if body.discount_percent < 0 or body.discount_percent > 100:
        raise HTTPException(status_code=400, detail="درصد تخفیف باید بین ۰ تا ۱۰۰ باشد.")
    if not (0 < body.percent < 100):
        raise HTTPException(status_code=400, detail="درصد آستانه باید بین ۱ تا ۹۹ باشد.")
    if body.gb_left <= 0:
        raise HTTPException(status_code=400, detail="آستانه‌ی گیگابایت باید بزرگ‌تر از صفر باشد.")
    if body.discount_expiry_hours <= 0:
        raise HTTPException(status_code=400, detail="اعتبار کد تخفیف باید بزرگ‌تر از صفر باشد.")
    db.set_setting("volume_reminder_enabled", "1" if body.enabled else "0")
    db.set_setting("volume_reminder_mode", body.mode)
    db.set_setting("volume_reminder_percent", str(body.percent))
    db.set_setting("volume_reminder_gb_left", str(body.gb_left))
    db.set_setting("volume_discount_percent", str(body.discount_percent))
    db.set_setting("volume_discount_expiry_hours", str(body.discount_expiry_hours))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# مدیریت کدهای تخفیف (ادمین)
# ---------------------------------------------------------------------------

class DiscountCreate(BaseModel):
    code: str
    percent: Optional[int] = None
    fixed_amount: Optional[int] = None
    max_uses: int = 0
    expires_at: Optional[str] = None


def _discount_to_dict(d):
    return {
        "id": d["id"], "code": d["code"], "percent": d["percent"], "fixed_amount": d["fixed_amount"],
        "max_uses": d["max_uses"], "used_count": d["used_count"], "is_active": bool(d["is_active"]),
        "created_at": d["created_at"],
    }


@app.get("/api/admin/discounts")
def api_admin_list_discounts(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    return [_discount_to_dict(d) for d in db.list_discount_codes()]


@app.post("/api/admin/discounts")
def api_admin_create_discount(body: DiscountCreate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    code = (body.code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="کد تخفیف نمی‌تواند خالی باشد.")
    if db.get_discount_code(code):
        raise HTTPException(status_code=400, detail="این کد قبلاً ثبت شده است.")
    if body.percent is None and body.fixed_amount is None:
        raise HTTPException(status_code=400, detail="باید درصد یا مبلغ ثابت تخفیف را مشخص کنی.")
    if body.percent is not None and (body.percent <= 0 or body.percent > 100):
        raise HTTPException(status_code=400, detail="درصد باید بین ۱ تا ۱۰۰ باشد.")
    discount_id = db.create_discount_code(
        code, percent=body.percent, fixed_amount=body.fixed_amount,
        max_uses=body.max_uses, expires_at=body.expires_at, source="admin",
    )
    return _discount_to_dict(db.get_discount_code_by_id(discount_id))


@app.post("/api/admin/discounts/{discount_id}/toggle")
def api_admin_toggle_discount(discount_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not db.get_discount_code_by_id(discount_id):
        raise HTTPException(status_code=404, detail="کد تخفیف یافت نشد.")
    db.toggle_discount_code(discount_id)
    return {"status": "ok"}


@app.delete("/api/admin/discounts/{discount_id}")
def api_admin_delete_discount(discount_id: int, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not db.get_discount_code_by_id(discount_id):
        raise HTTPException(status_code=404, detail="کد تخفیف یافت نشد.")
    db.delete_discount_code(discount_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# داشبورد آماری (ادمین)
# ---------------------------------------------------------------------------

@app.get("/api/admin/dashboard")
def api_admin_dashboard(
    start_date: str = Query(None), end_date: str = Query(None), auth=Depends(require_senior_admin)
):
    _, db, _ = auth
    return db.get_full_stats(start_date=start_date, end_date=end_date)


@app.get("/api/admin/orders/export")
def api_admin_orders_export(
    start_date: str = Query(None), end_date: str = Query(None), auth=Depends(require_senior_admin)
):
    _, db, _ = auth
    rows = db.get_orders_for_export(start_date=start_date, end_date=end_date)

    status_fa = {"approved": "تاییدشده", "pending": "در انتظار", "rejected": "ردشده"}
    lines = [
        "\ufeff" + ",".join([
            "شناسه سفارش", "تاریخ ثبت (شمسی)", "وضعیت", "آیدی کاربر", "یوزرنیم", "نام",
            "محصول", "تعداد", "مبلغ نهایی", "مبلغ از کیف‌پول", "تخفیف",
        ])
    ]
    for r in rows:
        row = [
            str(r["id"]),
            to_jalali_str(r["created_at"], with_time=True),
            status_fa.get(r["status"], r["status"]),
            str(r["user_id"]),
            (r["username"] or ""),
            (r["first_name"] or ""),
            (r["product_name"] or ""),
            str(r["quantity"] or 1),
            str(r["amount"] or 0),
            str(r["wallet_used"] or 0),
            str(r["discount_amount"] or 0),
        ]

        def _csv_cell(v):
            v = v.replace('"', '""')
            return f'"{v}"' if ("," in v or '"' in v) else v

        lines.append(",".join(_csv_cell(c) for c in row))

    csv_content = "\n".join(lines)
    filename = f"orders_{rows[0]['created_at'][:10] if rows else 'export'}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# مدیریت تیکت‌ها (ادمین)
# ---------------------------------------------------------------------------

class AdminTicketMessageCreate(BaseModel):
    message: str


@app.get("/api/admin/tickets")
def api_admin_list_tickets(status: Optional[str] = None, auth=Depends(require_admin)):
    tg_id, db, _ = auth
    is_owner = db.is_owner(tg_id)
    rows = db.get_all_tickets(status=status)
    result = []
    for t in rows:
        user = db.get_user(t["user_id"])
        result.append({
            **_ticket_to_dict(t),
            "user_id": t["user_id"],
            "user_name": (user["first_name"] if user else "") or "",
            "user_username": (user["username"] if user else "") or "",
            "claimed_by_me": t["claimed_by"] == tg_id,
            "locked_for_me": bool(t["claimed_by"]) and t["claimed_by"] != tg_id and not is_owner,
        })
    return result


@app.get("/api/admin/tickets/{ticket_id}/messages")
def api_admin_get_ticket_messages(ticket_id: int, since_id: int = 0, auth=Depends(require_admin)):
    tg_id, db, _ = auth
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="تیکت یافت نشد.")
    db.mark_ticket_read_by_admin(ticket_id)
    rows = db.get_ticket_messages(ticket_id, since_id=since_id)
    user = db.get_user(ticket["user_id"])
    is_owner = db.is_owner(tg_id)
    return {
        "ticket": {
            **_ticket_to_dict(ticket),
            "user_id": ticket["user_id"],
            "user_name": (user["first_name"] if user else "") or "",
            "user_username": (user["username"] if user else "") or "",
            "claimed_by_me": ticket["claimed_by"] == tg_id,
            "locked_for_me": bool(ticket["claimed_by"]) and ticket["claimed_by"] != tg_id and not is_owner,
        },
        "messages": [
            {"id": m["id"], "sender": m["sender"], "message": m["message"], "created_at": m["created_at"]}
            for m in rows
        ],
    }


@app.post("/api/admin/tickets/{ticket_id}/messages")
async def api_admin_send_ticket_message(ticket_id: int, body: AdminTicketMessageCreate, auth=Depends(require_admin)):
    tg_id, db, tenant = auth
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="تیکت یافت نشد.")
    if ticket["claimed_by"] and ticket["claimed_by"] != tg_id and not db.is_owner(tg_id):
        raise HTTPException(status_code=403, detail="این تیکت قبلاً توسط ادمین دیگری پاسخ داده شده و فقط برای او (و مالک) فعال است.")
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="پیام نمی‌تواند خالی باشد.")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="پیام بیش از حد طولانی است.")

    db.claim_ticket_if_open(ticket_id, tg_id)
    msg_id = db.add_ticket_message(ticket_id, "admin", text)

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                json={
                    "chat_id": ticket["user_id"],
                    "text": f"🎫 پاسخ پشتیبانی به تیکت «{ticket['subject']}»:\n\n{text}",
                },
            )
    except Exception:
        pass

    return {"id": msg_id, "sender": "admin", "message": text}


@app.post("/api/admin/tickets/{ticket_id}/close")
def api_admin_close_ticket(ticket_id: int, auth=Depends(require_admin)):
    _, db, _ = auth
    if not db.get_ticket(ticket_id):
        raise HTTPException(status_code=404, detail="تیکت یافت نشد.")
    db.close_ticket(ticket_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# چت زنده پشتیبانی - سمت ادمین (پاسخ‌دادن از داخل مینی‌اپ)
# ---------------------------------------------------------------------------

class AdminSupportMessageCreate(BaseModel):
    message: str


@app.get("/api/admin/support/conversations")
def api_admin_list_support_conversations(auth=Depends(require_admin)):
    tg_id, db, _ = auth
    is_owner = db.is_owner(tg_id)
    convs = db.list_support_conversations()
    result = []
    for c in convs:
        user = db.get_user(c["user_id"])
        result.append({
            **c,
            "user_name": (user["first_name"] if user else "") or "",
            "user_username": (user["username"] if user else "") or "",
            "assigned_to_me": c["assigned_admin_id"] == tg_id,
            "locked_for_me": bool(c["assigned_admin_id"]) and c["assigned_admin_id"] != tg_id and not is_owner,
        })
    return result


@app.get("/api/admin/support/{user_id}/messages")
def api_admin_get_support_messages(user_id: int, since_id: int = 0, auth=Depends(require_admin)):
    tg_id, db, _ = auth
    is_owner = db.is_owner(tg_id)
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    db.mark_support_read_by_admin(user_id)
    rows = db.get_support_messages(user_id, since_id=since_id)
    conv = db.get_support_conversation(user_id)
    assigned_admin_id = conv["assigned_admin_id"] if conv else None
    return {
        "user": {
            "user_id": user_id,
            "user_name": (user["first_name"] if user else "") or "",
            "user_username": (user["username"] if user else "") or "",
            "assigned_admin_id": assigned_admin_id,
            "assigned_to_me": assigned_admin_id == tg_id,
            "locked_for_me": bool(assigned_admin_id) and assigned_admin_id != tg_id and not is_owner,
        },
        "messages": [
            {"id": m["id"], "sender": m["sender"], "message": m["message"], "created_at": m["created_at"]}
            for m in rows
        ],
    }


@app.post("/api/admin/support/{user_id}/messages")
async def api_admin_send_support_message(user_id: int, body: AdminSupportMessageCreate, auth=Depends(require_admin)):
    tg_id, db, tenant = auth
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    conv = db.get_support_conversation(user_id)
    assigned_admin_id = conv["assigned_admin_id"] if conv else None
    if assigned_admin_id and assigned_admin_id != tg_id and not db.is_owner(tg_id):
        raise HTTPException(
            status_code=403,
            detail="این گفتگو در حال حاضر توسط ادمین دیگری پاسخ داده می‌شود و فقط برای او (و مالک) فعال است.",
        )
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="پیام نمی‌تواند خالی باشد.")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="پیام بیش از حد طولانی است.")

    # پاسخ‌دادن یعنی از این پس این مکالمه مال همین ادمین است (مگر مالک باشد که
    # همیشه بدون قفل‌شدن مکالمه اجازه‌ی پاسخ دارد).
    if not db.is_owner(tg_id):
        db.set_support_conversation_admin(user_id, tg_id)

    msg_id = db.add_support_message(user_id, "admin", text)

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                json={"chat_id": user_id, "text": f"📩 پاسخ پشتیبانی:\n\n{text}"},
            )
    except Exception:
        pass

    return {"id": msg_id, "sender": "admin", "message": text}


# ---------------------------------------------------------------------------
# مدیریت برندینگ Mini App (نام فروشگاه / متن بنر) - ادمین
# ---------------------------------------------------------------------------

class BrandingUpdate(BaseModel):
    store_name: str
    banner_text: str


@app.get("/api/admin/settings/branding")
def api_admin_get_branding(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    theme = db.get_setting("miniapp_theme", "clean-light")
    if theme not in MINIAPP_THEMES:
        theme = "clean-light"
    return {
        "store_name": db.get_setting("store_name", "⚡ SHOP VPN"),
        "banner_text": db.get_setting("miniapp_banner_text", "اتصال امن و پایدار برقرار است"),
        "theme": theme,
        "themes": [{"id": k, "label": v} for k, v in MINIAPP_THEMES.items()],
        "header_image": db.get_setting("header_image_data", "") or None,
    }


@app.post("/api/admin/settings/branding")
def api_admin_set_branding(body: BrandingUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    store_name = body.store_name.strip()
    banner_text = body.banner_text.strip()
    if not store_name:
        raise HTTPException(status_code=400, detail="نام فروشگاه نمی‌تواند خالی باشد.")
    if not banner_text:
        raise HTTPException(status_code=400, detail="متن بنر نمی‌تواند خالی باشد.")
    if len(store_name) > 40:
        raise HTTPException(status_code=400, detail="نام فروشگاه بیش از حد طولانی است.")
    if len(banner_text) > 80:
        raise HTTPException(status_code=400, detail="متن بنر بیش از حد طولانی است.")
    db.set_setting("store_name", store_name)
    db.set_setting("miniapp_banner_text", banner_text)
    return {"status": "ok"}


class ThemeUpdate(BaseModel):
    theme: str


@app.post("/api/admin/settings/theme")
def api_admin_set_theme(body: ThemeUpdate, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if body.theme not in MINIAPP_THEMES:
        raise HTTPException(status_code=400, detail="این تم معتبر نیست.")
    db.set_setting("miniapp_theme", body.theme)
    return {"status": "ok", "theme": body.theme}


@app.post("/api/admin/settings/header-image")
async def api_admin_set_header_image(photo: UploadFile = File(...), auth=Depends(require_senior_admin)):
    _, db, _ = auth
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="فقط فایل عکس پذیرفته می‌شود.")
    photo_bytes = await photo.read()
    if len(photo_bytes) > MAX_HEADER_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="حجم عکس نباید بیشتر از ۲ مگابایت باشد.")
    data_uri = f"data:{photo.content_type};base64,{base64.b64encode(photo_bytes).decode('ascii')}"
    db.set_setting("header_image_data", data_uri)
    return {"status": "ok", "header_image": data_uri}


@app.delete("/api/admin/settings/header-image")
def api_admin_delete_header_image(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    db.set_setting("header_image_data", "")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# مدیریت کاربران (جستجو/فیلتر/بلاک/تاریخچه/پیام) — ادمین
# ---------------------------------------------------------------------------

@app.get("/api/admin/users")
def api_admin_list_users(
    query: str = "", status: str = "all", limit: int = 30, offset: int = 0,
    auth=Depends(require_full_admin),
):
    _, db, _ = auth
    if status not in ("all", "active", "expired", "blocked"):
        status = "all"
    limit = max(1, min(limit, 100))
    rows, total = db.search_users(query=query.strip(), status_filter=status, limit=limit, offset=offset)
    users = []
    for u in rows:
        users.append({
            "telegram_id": u["telegram_id"],
            "username": u["username"] or "",
            "first_name": u["first_name"] or "",
            "is_blocked": bool(u["is_blocked"]),
            "joined_at": u["joined_at"],
            "wallet_credit": db.get_wallet_credit(u["telegram_id"]),
            "status": db.get_user_status(u["telegram_id"]),
        })
    return {"users": users, "total": total, "limit": limit, "offset": offset}


@app.get("/api/admin/users/{telegram_id}")
def api_admin_get_user(telegram_id: int, auth=Depends(require_full_admin)):
    _, db, _ = auth
    user = db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربری با این آیدی عددی پیدا نشد.")
    history = db.get_user_full_history(telegram_id)
    return {
        "telegram_id": user["telegram_id"],
        "username": user["username"] or "",
        "first_name": user["first_name"] or "",
        "is_blocked": bool(user["is_blocked"]),
        "joined_at": user["joined_at"],
        "wallet_credit": db.get_wallet_credit(telegram_id),
        "status": db.get_user_status(telegram_id),
        "orders": [dict(o) for o in history["orders"]],
        "topups": [dict(t) for t in history["topups"]],
    }


class UserBlockUpdate(BaseModel):
    blocked: bool


@app.post("/api/admin/users/{telegram_id}/block")
def api_admin_set_user_blocked(telegram_id: int, body: UserBlockUpdate, auth=Depends(require_full_admin)):
    _, db, _ = auth
    user = db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربری با این آیدی عددی پیدا نشد.")
    db.set_user_blocked(telegram_id, body.blocked)
    return {"status": "ok", "is_blocked": body.blocked}


class UserMessageSend(BaseModel):
    text: str


@app.post("/api/admin/users/{telegram_id}/message")
async def api_admin_message_user(telegram_id: int, body: UserMessageSend, tenant: Tenant = Depends(get_tenant), auth=Depends(require_admin)):
    _, db, _ = auth
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="متن پیام خالی است.")
    user = db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربری با این آیدی عددی پیدا نشد.")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
            json={"chat_id": telegram_id, "text": f"📩 پیام از پشتیبانی:\n\n{text}"},
        ) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=502, detail="ارسال پیام به کاربر ناموفق بود (شاید بات را بلاک کرده).")
    return {"status": "ok"}


class BroadcastExpiredSend(BaseModel):
    text: str


@app.post("/api/admin/users/broadcast-expired")
async def api_admin_broadcast_expired(body: BroadcastExpiredSend, tenant: Tenant = Depends(get_tenant), auth=Depends(require_full_admin)):
    _, db, _ = auth
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="متن پیام خالی است.")
    user_ids = db.get_expired_user_ids()
    success, failed = 0, 0
    async with aiohttp.ClientSession() as session:
        for uid in user_ids:
            try:
                async with session.post(
                    f"https://api.telegram.org/bot{tenant.bot_token}/sendMessage",
                    json={"chat_id": uid, "text": text},
                ) as resp:
                    if resp.status == 200:
                        success += 1
                    else:
                        failed += 1
            except Exception:
                failed += 1
    return {"status": "ok", "total": len(user_ids), "success": success, "failed": failed}


# ---------------------------------------------------------------------------
# لاگ فعالیت ادمین (audit log)
# ---------------------------------------------------------------------------

@app.get("/api/admin/logs")
def api_admin_logs(limit: int = 50, offset: int = 0, admin_id: int = None, auth=Depends(require_senior_admin)):
    _, db, _ = auth
    limit = max(1, min(limit, 100))
    rows, total = db.get_admin_logs(limit=limit, offset=offset, admin_id=admin_id)
    logs = []
    for r in rows:
        admin_user = db.get_user(r["admin_id"])
        logs.append({
            "id": r["id"],
            "admin_id": r["admin_id"],
            "admin_name": (admin_user["first_name"] if admin_user else "") or str(r["admin_id"]),
            "action": r["action"],
            "details": r["details"],
            "created_at": r["created_at"],
        })
    return {"logs": logs, "total": total, "limit": limit, "offset": offset}


@app.get("/api/admin/logs/admins")
def api_admin_logs_admin_list(auth=Depends(require_senior_admin)):
    _, db, _ = auth
    admins = db.list_admins_with_roles()
    out = []
    for a in admins:
        u = db.get_user(a["telegram_id"])
        out.append({
            "telegram_id": a["telegram_id"],
            "role": a["role"],
            "name": (u["first_name"] if u else "") or "",
        })
    return {"admins": out}



@app.get("/api/admin/wallet/lookup")
def api_admin_wallet_lookup(telegram_id: int, auth=Depends(require_full_admin)):
    _, db, _ = auth
    user = db.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربری با این آیدی عددی پیدا نشد.")
    return {
        "user_name": user["first_name"] or "",
        "username": user["username"] or "",
        "wallet_credit": db.get_wallet_credit(telegram_id),
    }


class WalletAdjust(BaseModel):
    telegram_id: int
    amount: int  # مثبت = افزایش، منفی = کاهش


@app.post("/api/admin/wallet/adjust")
def api_admin_adjust_wallet(body: WalletAdjust, auth=Depends(require_full_admin)):
    admin_id, db, _ = auth
    if body.amount == 0:
        raise HTTPException(status_code=400, detail="مقدار تغییر نمی‌تواند صفر باشد.")
    user = db.get_user(body.telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربری با این آیدی عددی پیدا نشد.")
    db.add_wallet_credit(body.telegram_id, body.amount)
    new_balance = db.get_wallet_credit(body.telegram_id)
    db.log_admin_action(
        admin_id, "wallet_adjust",
        f"کاربر {body.telegram_id} ({user['first_name'] or ''}) | تغییر: {body.amount:+} | موجودی جدید: {new_balance}",
    )
    return {
        "status": "ok",
        "user_name": user["first_name"] or "",
        "new_balance": new_balance,
    }


# ---------------------------------------------------------------------------
# دریافت یک کانفیگ رندوم آزاد (ادمین)
# ---------------------------------------------------------------------------

@app.post("/api/admin/products/{product_id}/take-random-config")
def api_admin_take_random_config(product_id: int, auth=Depends(require_senior_admin)):
    tg_id, db, _ = auth
    if not db.get_product(product_id):
        raise HTTPException(status_code=404, detail="محصول یافت نشد.")
    result = db.admin_take_random_config(product_id, tg_id)
    if not result:
        raise HTTPException(status_code=400, detail="کانفیگ آزادی برای این محصول موجود نیست.")
    return result


# ---------------------------------------------------------------------------
# بکاپ و بازیابی دیتابیس (فقط مالک اصلی همین مستأجر)
# ---------------------------------------------------------------------------

@app.post("/api/admin/backup/create")
async def api_admin_backup_create(auth=Depends(require_owner)):
    tg_id, db, tenant = auth
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(db.db_path)), "backups")
    backup_path = create_backup(db.db_path, backup_dir, keep=14)
    if not backup_path:
        raise HTTPException(status_code=404, detail="فایل دیتابیس پیدا نشد.")

    filename = os.path.basename(backup_path)
    with open(backup_path, "rb") as f:
        file_bytes = f.read()

    form = aiohttp.FormData()
    form.add_field("chat_id", str(tg_id))
    form.add_field("caption", "🗄 بکاپ فوری دیتابیس")
    form.add_field("document", file_bytes, filename=filename, content_type="application/octet-stream")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{tenant.bot_token}/sendDocument", data=form
            ) as resp:
                data = await resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="ارسال فایل بکاپ به تلگرام ناموفق بود. دوباره تلاش کن.")

    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=f"ارسال فایل بکاپ ناموفق بود: {data.get('description', '')}")

    db.log_admin_action(tg_id, "backup_create", "دریافت بکاپ فوری از طریق میان‌اپ")
    return {"status": "ok", "filename": filename}


@app.post("/api/admin/backup/restore")
async def api_admin_backup_restore(file: UploadFile = File(...), auth=Depends(require_owner)):
    _, db, _ = auth
    if not file.filename or not file.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(status_code=400, detail="فایل باید پسوند .db یا .sqlite داشته باشد.")

    tmp_dir = tempfile.mkdtemp(prefix="restore_")
    tmp_path = os.path.join(tmp_dir, "uploaded.db")
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    if not is_valid_sqlite_db(tmp_path):
        os.remove(tmp_path)
        os.rmdir(tmp_dir)
        raise HTTPException(status_code=400, detail="این فایل یک دیتابیس sqlite معتبر نیست.")

    try:
        pre_restore_path = await asyncio.to_thread(restore_backup, db, db.db_path, tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"بازیابی ناموفق بود: {e}")
    finally:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass

    return {"status": "ok", "pre_restore_backup": os.path.basename(pre_restore_path)}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
