# -*- coding: utf-8 -*-
"""
منطق مشترک ساخت/تأیید فاکتور پرداخت NoapayBot (خرید استارز تلگرام، به‌عنوان یک
روش پرداخت کارت‌به‌کارت با تایید آنی) که هم از سرور مینی‌اپ (miniapp/server.py،
برای دریافت وب‌هوک) و هم مستقیم از داخل بات (handlers_user.py، برای ساخت فاکتور و
بررسی دستی وضعیت) قابل استفاده است.

نکته درباره‌ی مبلغ: API این‌جا مبلغ تومانی نمی‌گیرد؛ به‌جایش «تعداد استارز»
(فیلد quantity در بدنه‌ی درخواست؛ طبق مستندات جدید، قبلاً stars_count بود) می‌گیرد
و مبلغ واقعی (total_toman) را خودش بر اساس نرخ لحظه‌ای
تعیین و در پاسخ برمی‌گرداند. چون نرخ لحظه‌ای از بیرون در دسترس نیست، ادمین یک
نرخ تقریبی (تومان به‌ازای هر استارز) در تنظیمات ثبت می‌کند و از روی آن
stars_count محاسبه می‌شود. amount_toman ثبت‌شده در دیتابیس همیشه همان مبلغ
واقعیِ سفارش/شارژ کیف‌پول است (منبع حقیقت برای تحویل) - دقیقاً مثل رفتار
crypto_payment.py با نرخ دلار؛ مبلغ واقعیِ اعلام‌شده توسط NoapayBot (که ممکن
است کمی با نرخ تقریبی فرق داشته باشد) فقط اطلاعاتی ذخیره می‌شود.

نکته درباره‌ی وب‌هوک: بر خلاف آبان‌گیت‌وی، NoapayBot امضای وب‌هوک را با
HMAC-SHA256 مستند کرده (X-Starbot-Signature). با این‌حال، طبق همان الگوی
دفاعی‌ای که در abangateway_payment.py استفاده شده، حتی بعد از تایید امضا،
وضعیت واقعی از طریق GET /invoice/:token (با کلید API خودمان) استعلام می‌شود
تا منبع حقیقت همیشه خودِ API باشد، نه بدنه‌ی وب‌هوک.
"""

import hashlib
import hmac
import logging
import math

from config import NOAPAY_API_KEY, NOAPAY_WEBHOOK_SECRET, API_BASE_URL
import noapay_client
from config_delivery import deliver_config_to_user
from panel_providers import get_provider
from reseller_auto_provision import provision_auto_config, ProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from stock_alerts import check_and_notify_low_stock
from renewal_engine import execute_renewal, RenewalError

logger = logging.getLogger("noapay_payment")


class NoapayPaymentError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین در فلوی پرداخت NoapayBot."""
    pass


def resolve_api_key(db) -> str:
    """کلید API را برمی‌گرداند: اولویت با کلیدی است که ادمین از داخل بات برای همین
    فروشگاه (تننت) تنظیم کرده؛ در غیر این صورت کلید سراسری .env."""
    return db.get_setting("noapay_api_key", "") or NOAPAY_API_KEY


def resolve_api_key_source(db) -> str:
    """برای دیباگ/نمایش در پنل ادمین: کلید از کجا آمده؟"""
    if db.get_setting("noapay_api_key", ""):
        return "db"
    if NOAPAY_API_KEY:
        return "env"
    return "none"


def resolve_webhook_secret(db) -> str:
    return db.get_setting("noapay_webhook_secret", "") or NOAPAY_WEBHOOK_SECRET


def resolve_rate(db) -> int:
    """نرخ تقریبی تومان به‌ازای هر استارز که ادمین دستی تنظیم کرده. ۰ یعنی هنوز
    تنظیم نشده (درگاه در دسترس نیست)."""
    try:
        return int(db.get_setting("noapay_rate_toman_per_star", "0") or 0)
    except ValueError:
        return 0


def noapay_payment_available(db) -> bool:
    return (
        db.get_setting("noapay_payment_enabled", "0") == "1"
        and bool(resolve_api_key(db))
        and bool(API_BASE_URL)
        and resolve_rate(db) > 0
    )


def amount_to_stars(db, amount_toman: int) -> int:
    """مبلغ تومانی سفارش/شارژ را با نرخ تنظیم‌شده به «تعداد استارز» تبدیل می‌کند
    (گرد به بالا، تا مبلغ واقعی هیچ‌وقت از مبلغ درخواستی کمتر نشود)."""
    rate = resolve_rate(db)
    if rate <= 0:
        raise NoapayPaymentError(
            "نرخ تبدیل استارز به تومان برای درگاه NoapayBot تنظیم نشده. از پنل مدیریت، "
            "«تنظیم درگاه NoapayBot» را بزن."
        )
    stars = max(1, math.ceil(amount_toman / rate))
    return stars


def callback_url(tenant_id: str) -> str:
    """آدرسی که NoapayBot برای این فاکتور، وب‌هوک تغییر وضعیت را به آن POST می‌کند."""
    if not API_BASE_URL:
        raise NoapayPaymentError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")
    return f"{API_BASE_URL}/api/webhooks/noapay?b={tenant_id or ''}"


async def create_invoice_for(db, tenant_id: str, tg_id: int, kind: str, ref_id: int,
                              amount_toman: int, order_name: str) -> dict:
    """یک فاکتور NoapayBot برای سفارش (kind='order') یا شارژ کیف پول (kind='wallet_topup')
    می‌سازد و آن را در جدول noapay_invoices ثبت می‌کند.
    خروجی: {"payment_url": ..., "invoice_token": ...}
    در صورت خطا NoapayPaymentError صادر می‌شود."""
    api_key = resolve_api_key(db)
    if not api_key:
        raise NoapayPaymentError(
            "درگاه NoapayBot هنوز تنظیم نشده. از پنل مدیریت، «تنظیم درگاه NoapayBot» را بزن."
        )
    if not API_BASE_URL:
        raise NoapayPaymentError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است؛ بدون آن این پرداخت ممکن نیست.")
    if db.get_setting("noapay_payment_enabled", "0") != "1":
        raise NoapayPaymentError("پرداخت NoapayBot برای این فروشگاه فعال نیست.")

    existing = db.get_pending_noapay_invoice_for_ref(kind, ref_id)
    if existing:
        return {"payment_url": existing["payment_url"], "invoice_token": existing["invoice_token"]}

    stars_count = amount_to_stars(db, amount_toman)
    metadata = f"{kind}:{tenant_id or 'main'}:{ref_id}"
    cb_url = callback_url(tenant_id)
    try:
        data = await noapay_client.create_invoice(
            api_key=api_key,
            stars_count=stars_count,
            user_telegram_id=tg_id,
            callback_url=cb_url,
            metadata=metadata,
            fee_on_user=True,
        )
    except noapay_client.NoapayError as e:
        raise NoapayPaymentError(f"خطا از درگاه پرداخت: {e}")

    invoice_token = data.get("invoice_token")
    if not invoice_token:
        raise NoapayPaymentError("پاسخ درگاه پرداخت ناقص بود (بدون شناسه‌ی فاکتور).")

    db.create_noapay_invoice(
        invoice_token=invoice_token, kind=kind, ref_id=ref_id, user_id=tg_id,
        amount_toman=amount_toman, stars_count=stars_count,
        quoted_total_toman=data.get("total_toman"),
        payment_url=data.get("payment_url"),
    )
    return {"payment_url": data.get("payment_url"), "invoice_token": invoice_token}


async def try_verify_and_finalize(db, invoice_row) -> str:
    """منبع حقیقت برای تأیید یک فاکتور NoapayBot. بدون توجه به این‌که از کجا صدا زده
    شده (وب‌هوک یا دکمه‌ی «بررسی وضعیت» در بات)، وضعیت واقعی را از خودِ API استعلام
    می‌کند و فقط اگر completed باشد، فاکتور را نهایی می‌کند.

    خروجی یکی از این مقادیر است:
      'already_delivered' - قبلاً تحویل داده شده؛ کاری نکن
      'verified_now'      - همین الان تأیید شد؛ باید سفارش/شارژ را تحویل بدهی
      'not_paid_yet'       - هنوز پرداخت/تاییدی ثبت نشده
      'expired' / 'rejected' - فاکتور دیگر معتبر نیست
      شروع‌شونده با 'error:' - خطای ارتباط با درگاه
    """
    invoice_token = invoice_row["invoice_token"]
    if invoice_row["status"] == "completed":
        return "already_delivered"

    api_key = resolve_api_key(db)
    if not api_key:
        return "error:کلید API درگاه NoapayBot تنظیم نشده است."

    try:
        remote = await noapay_client.get_invoice(api_key, invoice_token)
    except noapay_client.NoapayError as e:
        return f"error:{e}"

    remote_status = remote.get("status")

    if remote_status in ("expired", "rejected"):
        db.update_noapay_invoice_status(invoice_token, remote_status)
        return remote_status

    if remote_status != "completed":
        db.update_noapay_invoice_status(invoice_token, remote_status or invoice_row["status"])
        return "not_paid_yet"

    db.update_noapay_invoice_status(invoice_token, "completed")
    return "verified_now"


def verify_webhook_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    """امضای HMAC-SHA256 هدر X-Starbot-Signature را با webhook_secret تأیید می‌کند."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip().lower())


def extract_invoice_token_from_webhook(body: dict) -> str:
    val = (body or {}).get("invoice_token")
    return str(val) if val else None


from payment_delivery import finalize_paid_order, finalize_paid_topup  # noqa: F401

