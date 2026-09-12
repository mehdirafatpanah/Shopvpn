# -*- coding: utf-8 -*-
"""
کلاینت Firebase Cloud Messaging (FCM HTTP v1) برای ارسال نوتیفیکیشن پوش به
اپ اندروید مدیریت.

راه‌اندازی (از پنل وب، بدون نیاز به SSH یا فایل روی سرور):
    1. یک پروژه‌ی رایگان در https://console.firebase.google.com بساز.
    2. از Project Settings → Service Accounts → Generate new private key یک
       فایل JSON بگیر.
    3. کل محتوای همان فایل JSON را در پنل وب > تنظیمات و سیستم > اپ موبایل،
       فیلد «Firebase Service Account JSON» پیست کن و ذخیره بزن.

project_id مستقیم از همان JSON خوانده می‌شود.

نکته‌ی مهم (چندمستأجری/reseller): این تنظیم مثل بقیه‌ی تنظیمات پنل، per-tenant
است — هر بات (بات اصلی یا هر نماینده‌ی سطح ۱ با پنل وب مستقل) پروژه‌ی فایربیس
و سرویس‌اکانت خودش را جدا در دیتابیس خودش ذخیره می‌کند، و هر بار قبل از ارسال
دوباره از دیتابیس همان تننت خوانده می‌شود (نه یک بار در زمان استارت پردازش) تا
تنظیم‌کردن یا تغییردادنش نیازی به ری‌استارت سرویس نداشته باشد.

برای سازگاری با نصب‌های قدیمی‌تر، اگر این تنظیم خالی باشد، از فایل
firebase-service-account.json (یا مسیر FIREBASE_SERVICE_ACCOUNT_PATH) هم به‌عنوان
جایگزین سراسری خوانده می‌شود.

اگر هیچ‌کدام تنظیم نشده باشند، send_to_tokens() چیزی نمی‌فرستد و به‌جای خطا
دادن سکوت می‌کند (دقیقاً مثل رفتار PUSH_ENABLED برای وب‌پوش) تا نصب‌های بدون
Firebase از کار نیفتند.
"""

import json
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)

_SETTING_KEY = "firebase_service_account_json"
_SA_PATH = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "")

# کش توکن OAuth2، کلید‌شده بر اساس client_email سرویس‌اکانت (چون هر تننت
# می‌تواند سرویس‌اکانت/پروژه‌ی متفاوتی داشته باشد و یک کش سراسری تک‌مقداری
# باعث می‌شد پوش تننت‌های دیگر با توکن اشتباه (پروژه‌ی عوضی) رد شود).
_access_token_cache: dict = {}


def _load_service_account_from_file():
    path = _SA_PATH or "firebase-service-account.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("خواندن فایل سرویس‌اکانت Firebase ناموفق بود")
        return None


def _load_service_account(db):
    """اول از تنظیمات همین تننت (دیتابیس) می‌خواند؛ اگر خالی بود، به فایل/env
    سراسری برمی‌گردد (سازگاری با نصب‌های قدیمی)."""
    raw = ""
    try:
        raw = (db.get_setting(_SETTING_KEY) or "").strip()
    except Exception:
        logger.exception("خواندن تنظیم %s از دیتابیس ناموفق بود", _SETTING_KEY)
    if raw:
        try:
            sa = json.loads(raw)
            if sa.get("client_email") and sa.get("private_key") and sa.get("project_id"):
                return sa
            logger.warning("مقدار %s در تنظیمات JSON معتبر سرویس‌اکانت فایربیس نیست", _SETTING_KEY)
        except Exception:
            logger.exception("پارس JSON سرویس‌اکانت فایربیس از تنظیمات ناموفق بود")
    return _load_service_account_from_file()


def is_configured(db) -> bool:
    """آیا برای این تننت (یا سراسری، به‌صورت fallback) سرویس‌اکانت فایربیس
    معتبری در دسترس است؟ برخلاف نسخه‌ی قبلی این تابع، هر بار زنده چک می‌کند،
    نه یک‌بار در زمان بالا آمدن پردازش — پس بعد از ثبت تنظیمات از پنل وب،
    نیازی به ری‌استارت سرویس نیست."""
    return _load_service_account(db) is not None


async def _get_access_token(sa: dict) -> str:
    """توکن OAuth2 کوتاه‌مدت گوگل را با jwt امضاشده با کلید سرویس‌اکانت می‌گیرد.
    کش می‌شود (به ازای هر client_email) تا هر ارسال، یک درخواست جدید به گوگل نزند."""
    cache_key = sa.get("client_email", "")
    now = time.time()
    cached = _access_token_cache.get(cache_key)
    if cached and cached["exp"] > now + 60:
        return cached["token"]

    import jwt  # PyJWT - در requirements.txt اضافه شده

    iat = int(now)
    exp = iat + 3600
    payload = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/firebase.messaging",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat,
        "exp": exp,
    }
    assertion = jwt.encode(payload, sa["private_key"], algorithm="RS256")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        ) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"دریافت access token گوگل ناموفق بود: {data}")
            _access_token_cache[cache_key] = {
                "token": data["access_token"],
                "exp": iat + int(data.get("expires_in", 3600)),
            }
            return data["access_token"]


async def send_to_tokens(db, tokens: list, title: str, body: str, data: dict = None) -> list:
    """برای هر توکن FCM یک نوتیف می‌فرستد (سرویس‌اکانت مخصوص همین تننت/db).
    برمی‌گرداند: لیست توکن‌هایی که گوگل گفته دیگر معتبر نیستند (باید از
    دیتابیس حذف شوند)."""
    sa = _load_service_account(db)
    if not sa or not tokens:
        return []

    try:
        access_token = await _get_access_token(sa)
    except Exception:
        logger.exception("گرفتن access token برای FCM ناموفق بود")
        return []

    project_id = sa["project_id"]
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; UTF-8",
    }
    invalid_tokens = []

    async with aiohttp.ClientSession() as session:
        for token in tokens:
            message = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": {k: str(v) for k, v in (data or {}).items()},
                    "android": {"priority": "high"},
                }
            }
            try:
                async with session.post(url, headers=headers, data=json.dumps(message)) as resp:
                    if resp.status == 404 or resp.status == 400:
                        resp_data = await resp.json()
                        status = (resp_data.get("error", {}).get("status", ""))
                        if status in ("NOT_FOUND", "INVALID_ARGUMENT", "UNREGISTERED"):
                            invalid_tokens.append(token)
                        else:
                            logger.warning(
                                "ارسال FCM رد شد (status=%s, error=%s) - احتمالا project_id/سرویس‌اکانت "
                                "با پروژه‌ی فایربیسی که اپ اندروید با آن مقداردهی شده یکی نیست",
                                resp.status, status,
                            )
                    elif resp.status >= 400:
                        logger.warning("ارسال FCM ناموفق (status=%s) برای یک توکن", resp.status)
            except Exception:
                logger.exception("خطا در ارسال پوش FCM")

    return invalid_tokens


async def send_test(db, token: str) -> dict:
    """یک پوش تک‌توکنی می‌فرستد و به‌جای فقط لاگ‌کردن، جزئیات خام پاسخ گوگل را
    برمی‌گرداند - برای دکمه‌ی «تست پوش» در پنل. بدون این، وقتی پوشی نمی‌رسد
    راهی برای تشخیص علت (سرویس‌اکانت نامعتبر؟ توکن مال پروژه‌ی دیگری‌ست؟ خودِ
    گوشی مسدودش کرده؟) جز کندوکاو در لاگ سرور نیست."""
    sa = _load_service_account(db)
    if not sa:
        return {"ok": False, "reason": "not_configured"}
    try:
        access_token = await _get_access_token(sa)
    except Exception as e:
        return {"ok": False, "reason": "auth_failed", "detail": str(e)}

    project_id = sa["project_id"]
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; UTF-8",
    }
    message = {
        "message": {
            "token": token,
            "notification": {
                "title": "🔔 اعلان تست",
                "body": "این یک پیام آزمایشی از پنل مدیریت ShopVPN است.",
            },
            "android": {"priority": "high"},
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=json.dumps(message)) as resp:
                body = await resp.json()
                if resp.status == 200:
                    return {"ok": True}
                error = body.get("error", {}) if isinstance(body, dict) else {}
                return {
                    "ok": False,
                    "reason": "rejected",
                    "http_status": resp.status,
                    "detail": error.get("message") or error.get("status") or str(body),
                }
    except Exception as e:
        return {"ok": False, "reason": "request_failed", "detail": str(e)}
