# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
منطق مشترک ساخت/تأیید فاکتور پرداخت کارت‌به‌کارت خودکار آبان گیت وی که هم از سرور
مینی‌اپ (miniapp/server.py، برای دریافت وب‌هوک) و هم مستقیم از داخل بات
(handlers_user.py، برای ساخت فاکتور و بررسی دستی وضعیت) قابل استفاده است.

نکته درباره‌ی مبلغ: بقیه‌ی پروژه مبالغ را به «تومان» نگه می‌دارد؛ API آبان گیت وی
مبلغ را به «ریال» می‌خواهد (۱ تومان = ۱۰ ریال). تبدیل این‌جا انجام می‌شود.

نکته درباره‌ی وب‌هوک: اگر کلید مخفی وب‌هوک تنظیم شده باشد، هدر X-Signature
(HMAC-SHA256 روی بایت‌های خام بدنه) چک می‌شود. با این حال این ماژول به محتوای بدنه
اعتماد نمی‌کند؛ فقط از آن برای پیدا کردن invoice_id استفاده می‌کند و سپس با
فراخوانی مستقیم API (با کلید API خودمان) وضعیت واقعی فاکتور را استعلام و سپس
verify می‌کند. تابع try_verify_and_finalize منبع حقیقت است و هم از
مسیر وب‌هوک و هم از مسیر «بررسی دستی وضعیت» در بات صدا زده می‌شود.
"""

import hashlib
import hmac
import logging

from config import ABANGATEWAY_API_KEY, API_BASE_URL
import abangateway_client
from config_delivery import deliver_config_to_user
from panel_providers import get_provider
from reseller_auto_provision import provision_auto_config, ProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from stock_alerts import check_and_notify_low_stock
from renewal_engine import execute_renewal, RenewalError

logger = logging.getLogger("abangateway_payment")
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


class AbanGatewayPaymentError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین در فلوی پرداخت آبان گیت وی."""
    pass


def resolve_api_key(db) -> str:
    """کلید API را برمی‌گرداند: اولویت با کلیدی است که ادمین از داخل بات برای همین
    فروشگاه (تننت) تنظیم کرده؛ در غیر این صورت کلید سراسری .env."""
    return db.get_setting("abangateway_api_key", "") or ABANGATEWAY_API_KEY


def resolve_api_key_source(db) -> str:
    """برای دیباگ/نمایش در پنل ادمین: کلید از کجا آمده؟"""
    if db.get_setting("abangateway_api_key", ""):
        return "db"
    if ABANGATEWAY_API_KEY:
        return "env"
    return "none"


def verify_webhook_signature(raw_body: bytes, sent_signature: str, secret: str) -> bool:
    """امضای HMAC-SHA256 وب‌هوک آبان گیت وی را روی بایت‌های خام بدنه بررسی می‌کند."""
    if not secret or not sent_signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sent_signature.strip())


def abangateway_payment_available(db) -> bool:
    return (
        db.get_setting("abangateway_payment_enabled", "0") == "1"
        and bool(resolve_api_key(db))
        and bool(API_BASE_URL)
    )


def availability_problems(db) -> list:
    """دلایلی که باعث می‌شوند دکمه‌ی پرداخت آبان گیت وی به کاربر نمایش داده نشود.
    لیست خالی یعنی درگاه کاملاً آماده است. برای نمایش هشدار به ادمین استفاده می‌شود
    (قبلاً در این حالت دکمه بی‌صدا پنهان می‌شد و ادمین دلیلش را نمی‌فهمید)."""
    problems = []
    if db.get_setting("abangateway_payment_enabled", "0") != "1":
        problems.append("درگاه در تنظیمات غیرفعال است.")
    if not resolve_api_key(db):
        problems.append("کلید API آبان گیت وی تنظیم نشده است.")
    if not API_BASE_URL:
        problems.append(
            "آدرس مینی‌اپ تنظیم نشده است: در فایل .env مقدار MINIAPP_URL (یا API_BASE_URL) را "
            "با آدرس HTTPS عمومی سرور مینی‌اپ پر کنید و بات و مینی‌اپ را ری‌استارت کنید. "
            "این آدرس برای دریافت وب‌هوک تأیید پرداخت لازم است."
        )
    return problems


from payment_base import toman_to_rial, rial_to_toman  # noqa: F401


def callback_url(tenant_id: str) -> str:
    if not API_BASE_URL:
        raise AbanGatewayPaymentError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")
    base = API_BASE_URL
    return f"{base}/api/webhooks/abangateway?b={tenant_id or ''}"


async def create_invoice_for(db, tenant_id: str, tg_id: int, kind: str, ref_id: int,
                              amount_toman: int, order_name: str) -> dict:
    """یک فاکتور آبان گیت وی برای سفارش (kind='order') یا شارژ کیف پول (kind='wallet_topup')
    می‌سازد و آن را در جدول abangateway_invoices ثبت می‌کند.
    خروجی: {"payment_url": ..., "invoice_id": ...}
    در صورت خطا AbanGatewayPaymentError صادر می‌شود."""
    api_key = resolve_api_key(db)
    if not api_key:
        raise AbanGatewayPaymentError(
            "درگاه آبان گیت وی هنوز تنظیم نشده. از پنل مدیریت، «تنظیم درگاه آبان گیت وی» را بزن."
        )
    if not API_BASE_URL:
        raise AbanGatewayPaymentError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است؛ بدون آن این پرداخت ممکن نیست.")
    if db.get_setting("abangateway_payment_enabled", "0") != "1":
        raise AbanGatewayPaymentError("پرداخت آبان گیت وی برای این فروشگاه فعال نیست.")

    existing = db.get_pending_abangateway_invoice_for_ref(kind, ref_id)
    if existing:
        return {"payment_url": existing["payment_url"], "invoice_id": existing["invoice_id"]}

    amount_rial = toman_to_rial(amount_toman)
    order_number = f"{kind}-{tenant_id or 'main'}-{ref_id}"
    cb_url = callback_url(tenant_id)
    try:
        data = await abangateway_client.create_invoice(
            api_key=api_key,
            amount_rial=amount_rial,
            order_id=order_number,
            callback_url=cb_url,
            description=order_name,
            expiry_minutes=60,
        )
    except abangateway_client.AbanGatewayError as e:
        raise AbanGatewayPaymentError(f"خطا از درگاه پرداخت: {e}")

    invoice_id = data.get("invoice_id") or data.get("id")
    if not invoice_id:
        raise AbanGatewayPaymentError("پاسخ درگاه پرداخت ناقص بود (بدون شناسه‌ی فاکتور).")

    db.create_abangateway_invoice(
        invoice_id=invoice_id, kind=kind, ref_id=ref_id, user_id=tg_id,
        amount_toman=amount_toman, amount_rial=amount_rial,
        payable_rial=data.get("payable_rial"),
        payment_url=data.get("payment_url"),
        expiry_minutes=60,
    )
    return {"payment_url": data.get("payment_url"), "invoice_id": invoice_id}


async def try_verify_and_finalize(db, invoice_row) -> str:
    """منبع حقیقت برای تأیید یک فاکتور آبان گیت وی. بدون توجه به این‌که از کجا صدا زده
    شده (وب‌هوک یا دکمه‌ی «بررسی وضعیت» در بات)، وضعیت واقعی را از خودِ API استعلام
    می‌کند و فقط در صورت paid بودن، verify را صدا می‌زند (یک‌بارمصرف).

    خروجی یکی از این مقادیر است:
      'already_delivered' - قبلاً تحویل داده شده؛ کاری نکن
      'verified_now'      - همین الان تأیید شد؛ باید سفارش/شارژ را تحویل بدهی
      'not_paid_yet'       - هنوز واریزی تشخیص داده نشده
      'expired' / 'cancelled' - فاکتور دیگر معتبر نیست
      شروع‌شونده با 'error:' - خطای ارتباط با درگاه
    """
    invoice_id = invoice_row["invoice_id"]
    if invoice_row["status"] == "completed":
        return "already_delivered"

    api_key = resolve_api_key(db)
    if not api_key:
        return "error:کلید API آبان گیت وی تنظیم نشده است."

    try:
        remote = await abangateway_client.get_invoice(api_key, invoice_id)
    except abangateway_client.AbanGatewayError as e:
        return f"error:{e}"

    remote_status = remote.get("status")

    if remote_status in ("expired", "cancelled"):
        db.update_abangateway_invoice_status(invoice_id, remote_status)
        return remote_status

    if remote_status != "paid":
        db.update_abangateway_invoice_status(invoice_id, "pending" if remote_status == "partially_paid" else invoice_row["status"])
        return "not_paid_yet"

    try:
        await abangateway_client.verify_invoice(api_key, invoice_id)
    except abangateway_client.AbanGatewayAlreadyVerified:
        db.update_abangateway_invoice_status(invoice_id, "completed")
        return "already_delivered"
    except abangateway_client.AbanGatewayError as e:
        return f"error:{e}"

    db.update_abangateway_invoice_status(invoice_id, "completed")
    return "verified_now"


from payment_delivery import finalize_paid_order, finalize_paid_topup  # noqa: F401



def extract_invoice_id_from_webhook(body: dict) -> str:
    """شناسه‌ی فاکتور را از بدنه‌ی وب‌هوک درمی‌آورد. بدنه هرگز منبع حقیقتِ وضعیت
    پرداخت نیست (نگاه کن به try_verify_and_finalize)."""
    for key in ("invoice_id", "id", "invoiceId", "invoice"):
        val = body.get(key)
        if val:
            return str(val)
    return None
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
