# -*- coding: utf-8 -*-
"""
کلاینت سبک برای درگاه پرداخت کارت‌به‌کارت آبان گیت وی (https://abangateway.ir)
ساخت فاکتور، استعلام وضعیت، تأیید یک‌بارمصرف و لغو.
مستندات: https://abangateway.ir/docs/api

نکته‌ی مهم درباره‌ی مبلغ: API آبان گیت وی مبلغ را فقط به ریال (عدد صحیح) قبول می‌کند،
اما بقیه‌ی این پروژه مبالغ را به تومان نگه می‌دارد. تبدیل (ضرب/تقسیم بر ۱۰) وظیفه‌ی
ماژول abangateway_payment.py است، نه این فایل؛ این فایل فقط با ریال کار می‌کند.
"""

import logging

import aiohttp

ABANGATEWAY_BASE_URL = "https://abangateway.ir/api/v1"
logger = logging.getLogger("abangateway")


class AbanGatewayError(Exception):
    """خطای عمومی از سمت آبان گیت وی. code همان کد ماشین‌خوان مستندات است (ممکن است None باشد)."""

    def __init__(self, message: str, code: str = None, http_status: int = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class AbanGatewayAlreadyVerified(AbanGatewayError):
    """۴۰۹ already_verified: یعنی این فاکتور قبلاً تأیید و تحویل داده شده — نباید دوباره تحویل داد."""
    pass


class AbanGatewayNotYetPaid(AbanGatewayError):
    """۴۰۲ not_yet_paid: هنوز واریزی برای این فاکتور تشخیص داده نشده."""
    pass


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def _request(method: str, api_key: str, path: str, json_body: dict = None) -> dict:
    if not api_key:
        raise AbanGatewayError("کلید API آبان گیت وی تنظیم نشده است.")

    url = f"{ABANGATEWAY_BASE_URL}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=_headers(api_key), json=json_body, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                status = resp.status
    except aiohttp.ClientError as e:
        logger.warning("خطای شبکه در ارتباط با آبان گیت وی: %s", e)
        raise AbanGatewayError(f"خطای شبکه در ارتباط با درگاه پرداخت: {e}")

    if status >= 400:
        err = (data or {}).get("error") or {}
        code = err.get("code")
        message = err.get("message") or "خطای نامشخص از آبان گیت وی"
        logger.warning("خطای آبان گیت وی (%s): %s - %s", status, code, message)
        if code == "already_verified":
            raise AbanGatewayAlreadyVerified(message, code=code, http_status=status)
        if code == "not_yet_paid":
            raise AbanGatewayNotYetPaid(message, code=code, http_status=status)
        raise AbanGatewayError(message, code=code, http_status=status)

    return data


async def create_invoice(
    api_key: str,
    amount_rial: int,
    order_id: str = None,
    callback_url: str = None,
    description: str = None,
    metadata: dict = None,
    expiry_minutes: int = None,
) -> dict:
    """یک فاکتور می‌سازد و دیکشنری کامل پاسخ (شامل invoice_id، payment_url، payable_rial و ...) را برمی‌گرداند."""
    body = {"amount_rial": int(amount_rial)}
    if order_id is not None:
        body["order_id"] = str(order_id)[:128]
    if callback_url is not None:
        body["callback_url"] = callback_url
    if description is not None:
        body["description"] = str(description)[:1000]
    if metadata is not None:
        body["metadata"] = metadata
    if expiry_minutes is not None:
        body["expiry_minutes"] = int(expiry_minutes)

    return await _request("POST", api_key, "/invoices", json_body=body)


async def get_invoice(api_key: str, invoice_id: str) -> dict:
    """وضعیت فعلی فاکتور را برمی‌گرداند (pending/partially_paid/paid/expired/cancelled)."""
    return await _request("GET", api_key, f"/invoices/{invoice_id}")


async def verify_invoice(api_key: str, invoice_id: str) -> dict:
    """تأیید یک‌بارمصرف. فراخوانی دوم AbanGatewayAlreadyVerified می‌دهد — نباید دوباره تحویل داد."""
    return await _request("POST", api_key, f"/invoices/{invoice_id}/verify")


async def cancel_invoice(api_key: str, invoice_id: str) -> dict:
    """فاکتور پرداخت‌نشده را لغو می‌کند. روی فاکتور پرداخت‌شده ۴۰۹ می‌گیرد."""
    return await _request("POST", api_key, f"/invoices/{invoice_id}/cancel")


async def simulate_payment(api_key: str, invoice_id: str) -> dict:
    """فقط برای توکن‌های test_؛ پرداخت را در محیط آزمایش شبیه‌سازی می‌کند."""
    return await _request("POST", api_key, f"/invoices/{invoice_id}/simulate-payment")
