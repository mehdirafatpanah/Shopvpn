# -*- coding: utf-8 -*-
"""
کلاینت سبک برای درگاه پرداخت NoapayBot/StarBot (https://noapay.mirname.xyz)
ساخت فاکتور (خرید استارز تلگرام) و استعلام وضعیت.
مستندات: Payment-API-Docs.md (ارائه‌شده توسط ادمین فروشگاه)

نکته‌ی مهم درباره‌ی مبلغ: این API بر اساس «تعداد» (فیلد quantity در بدنه‌ی درخواست؛
طبق مستندات جدید، قبلاً stars_count بود) کار می‌کند نه مبلغ تومانی مستقیم؛ نرخ تبدیل
واقعی (total_toman) را خودِ NoapayBot در پاسخ برمی‌گرداند و ثابت نیست. تبدیل مبلغ
تومانی سفارش به quantity (با نرخ تقریبی‌ای که ادمین تنظیم می‌کند) وظیفه‌ی ماژول
noapay_payment.py است، نه این فایل؛ این فایل فقط خام با API صحبت می‌کند.
"""

import logging

import asyncio
import aiohttp

NOAPAY_BASE_URL = "https://noapay.mirname.xyz/api/v1"
logger = logging.getLogger("noapay")


class NoapayError(Exception):
    """خطای عمومی از سمت NoapayBot. code همان error_code مستندات است (ممکن است None باشد)."""

    def __init__(self, message: str, code: str = None, http_status: int = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class NoapayPendingApproval(NoapayError):
    """403 API_KEY_PENDING_APPROVAL: کلید هنوز توسط سوپر ادمین NoapayBot تأیید نشده."""
    pass


class NoapayPhoneRequired(NoapayError):
    """422 PHONE_VERIFICATION_REQUIRED: خریدار باید ابتدا شماره‌اش را در بات NoapayBot ثبت کند."""
    pass


class NoapayKeyDisabled(NoapayError):
    """401 API_KEY_DISABLED: کلید تأیید شده ولی توسط صاحبش خاموش شده."""
    pass


class NoapayKeyRejected(NoapayError):
    """403 API_KEY_REJECTED: درخواست کلید رد شده؛ باید کلید جدید درخواست شود."""
    pass


class NoapayFeeWalletInsufficient(NoapayError):
    """402 FEE_WALLET_INSUFFICIENT: موجودی کیف پول کارمزد برای کسر کارمزد این فاکتور کافی نیست."""
    pass


def _headers(api_key: str) -> dict:
    return {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }


async def _request(method: str, api_key: str, path: str, json_body: dict = None,
                    base_url: str = None) -> dict:
    if not api_key:
        raise NoapayError("کلید API درگاه NoapayBot تنظیم نشده است.")

    url = f"{base_url or NOAPAY_BASE_URL}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=_headers(api_key), json=json_body,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                status = resp.status
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("خطای شبکه در ارتباط با NoapayBot: %s", e)
        raise NoapayError(f"خطای شبکه در ارتباط با درگاه پرداخت: {e}")

    if not data.get("success", status < 400):
        err = data.get("error") or "خطای نامشخص از NoapayBot"
        code = data.get("error_code")
        logger.warning("خطای NoapayBot (%s): %s - %s", status, code, err)
        if code == "API_KEY_PENDING_APPROVAL":
            raise NoapayPendingApproval(err, code=code, http_status=status)
        if code == "PHONE_VERIFICATION_REQUIRED":
            raise NoapayPhoneRequired(err, code=code, http_status=status)
        if code == "API_KEY_DISABLED":
            raise NoapayKeyDisabled(err, code=code, http_status=status)
        if code == "API_KEY_REJECTED":
            raise NoapayKeyRejected(err, code=code, http_status=status)
        if code == "FEE_WALLET_INSUFFICIENT":
            raise NoapayFeeWalletInsufficient(err, code=code, http_status=status)
        raise NoapayError(err, code=code, http_status=status)

    return data.get("data") if isinstance(data, dict) and "data" in data else data


async def create_invoice(
    api_key: str,
    stars_count: int,
    user_telegram_id: int,
    callback_url: str = None,
    metadata: str = None,
    fee_on_user: bool = None,
    split_fee: bool = None,
    base_url: str = None,
) -> dict:
    """یک فاکتور خرید استارز می‌سازد و دیکشنری کامل داده‌ی پاسخ (شامل invoice_token،
    payment_url، total_toman و ...) را برمی‌گرداند.
    توجه: طبق مستندات جدید، نام فیلد بدنه‌ی درخواست از stars_count به quantity تغییر
    کرده؛ آرگومان ورودی همین تابع (stars_count) برای سازگاری با فراخوانی‌های موجود
    همان نام قبلی را حفظ کرده، فقط روی سیم به‌صورت quantity فرستاده می‌شود."""
    body = {
        "quantity": int(stars_count),
        "user_telegram_id": int(user_telegram_id),
    }
    if callback_url is not None:
        body["callback_url"] = callback_url
    if metadata is not None:
        body["metadata"] = str(metadata)[:255]
    if fee_on_user is not None:
        body["fee_on_user"] = bool(fee_on_user)
    if split_fee is not None:
        body["split_fee"] = bool(split_fee)

    return await _request("POST", api_key, "/invoice/create", json_body=body, base_url=base_url)


async def get_invoice(api_key: str, invoice_token: str, base_url: str = None) -> dict:
    """وضعیت فعلی فاکتور را برمی‌گرداند (pending/opened/paid/confirmed/completed/rejected/expired)."""
    return await _request("GET", api_key, f"/invoice/{invoice_token}", base_url=base_url)


async def get_me(api_key: str, base_url: str = None) -> dict:
    """اطلاعات کلید API و آمار کلی؛ برای «تست اتصال» در پنل مدیریت مناسب است."""
    return await _request("GET", api_key, "/me", base_url=base_url)
