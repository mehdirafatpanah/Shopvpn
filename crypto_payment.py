# -*- coding: utf-8 -*-
"""
منطق مشترک ساخت فاکتور پرداخت کریپتو (Plisio) که هم از سرور مینی‌اپ (server.py)
و هم مستقیم از داخل بات (handlers_user.py) قابل استفاده است، تا رفتار و
اعتبارسنجی‌ها بین این دو مسیر یکسان بماند.
"""

import logging
from datetime import datetime

from config import PLISIO_API_KEY, API_BASE_URL
import plisio_client
import exchange_rate

logger = logging.getLogger("crypto_payment")


class CryptoPaymentError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین در فلوی پرداخت کریپتو."""
    pass


def resolve_plisio_key(db) -> str:
    """کلید API Plisio را برمی‌گرداند: اولویت با کلیدی است که ادمین از داخل بات
    برای همین فروشگاه (تننت) تنظیم کرده؛ در غیر این صورت کلید سراسری .env."""
    return db.get_setting("plisio_api_key", "") or PLISIO_API_KEY


def resolve_plisio_key_source(db) -> str:
    """برای دیباگ/نمایش در پنل ادمین: کلید از کجا آمده؟
    'db' یعنی از داخل پنل بات ثبت شده (پیشنهادی، فوری و بدون نیاز به ری‌استارت).
    'env' یعنی فقط از .env این پروسه خوانده شده (اگر بات و مینی‌اپ را جدا
    ری‌استارت نکنی ممکن است این دو با هم ناهماهنگ شوند).
    'none' یعنی هیچ‌کدام تنظیم نشده."""
    if db.get_setting("plisio_api_key", ""):
        return "db"
    if PLISIO_API_KEY:
        return "env"
    return "none"


def crypto_payment_available(db) -> bool:
    return (
        db.get_setting("crypto_payment_enabled", "0") == "1"
        and bool(resolve_plisio_key(db))
        and bool(API_BASE_URL)
    )


async def toman_to_usd(db, amount_toman: int) -> float:
    rate = float(db.get_setting("usd_to_toman_rate", "0") or 0)
    if rate <= 0:
        try:
            rate = await exchange_rate.get_usd_to_toman_rate()
        except Exception as e:
            logger.warning("دریافت نرخ خودکار دلار ناموفق بود: %s", e)
            raise CryptoPaymentError(
                "دریافت نرخ لحظه‌ای دلار ناموفق بود (احتمالاً سرور به منابع نرخ دسترسی ندارد). "
                "می‌تونی از مینی‌اپ → مدیریت → تنظیمات کریپتو، یک نرخ دلار به تومان دستی ثبت کنی "
                "تا دیگر نیازی به دریافت خودکار نباشد."
            )
    usd = amount_toman / rate
    if usd < 1:
        raise CryptoPaymentError("مبلغ برای پرداخت کریپتو خیلی کم است (حداقل حدود ۱ دلار).")
    return round(usd, 2)


def resolve_expire_min(db) -> int:
    try:
        val = int(db.get_setting("crypto_expire_min", "80") or 80)
    except ValueError:
        val = 80
    return val if val > 0 else 80


def resolve_allowed_currencies(db) -> str:
    """رشته‌ی CSV ارزهای مجاز که ادمین از پنل تنظیم کرده (مثل 'BTC,ETH,USDT_TRX').
    خالی یعنی همه‌ی ارزهای فعال Plisio مجازند."""
    return (db.get_setting("crypto_allowed_currencies", "") or "").strip()


def callback_url(tenant_id: str) -> str:
    if not API_BASE_URL:
        raise CryptoPaymentError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")
    base = API_BASE_URL
    return f"{base}/api/webhooks/plisio?b={tenant_id}&json=true"


async def create_invoice_for(db, tenant_id: str, tg_id: int, kind: str, ref_id: int,
                              amount_toman: int, order_name: str) -> dict:
    """یک فاکتور Plisio برای سفارش (kind='order') یا شارژ کیف پول (kind='wallet_topup')
    می‌سازد و آن را در جدول crypto_invoices ثبت می‌کند.
    خروجی: {"invoice_url": ..., "txn_id": ...}
    در صورت خطا CryptoPaymentError صادر می‌شود."""
    api_key = resolve_plisio_key(db)
    if not api_key:
        raise CryptoPaymentError("درگاه پرداخت کریپتو هنوز تنظیم نشده. از پنل مدیریت، «تنظیم درگاه کریپتو» را بزن.")
    if not API_BASE_URL:
        raise CryptoPaymentError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است؛ بدون آن پرداخت کریپتو ممکن نیست.")
    if db.get_setting("crypto_payment_enabled", "0") != "1":
        raise CryptoPaymentError("پرداخت کریپتو برای این فروشگاه فعال نیست.")

    existing = db.get_pending_crypto_invoice_for_ref(kind, ref_id)
    if existing:
        return {"invoice_url": existing["invoice_url"], "txn_id": existing["txn_id"]}

    source_amount_usd = await toman_to_usd(db, amount_toman)
    order_number = f"{kind}-{tenant_id or 'main'}-{ref_id}-{int(datetime.utcnow().timestamp())}"
    cb_url = callback_url(tenant_id)
    try:
        data = await plisio_client.create_invoice(
            api_key=api_key,
            order_number=order_number,
            order_name=order_name,
            source_amount_usd=source_amount_usd,
            callback_url=cb_url,
            expire_min=resolve_expire_min(db),
            allowed_psys_cids=resolve_allowed_currencies(db),
        )
    except plisio_client.PlisioError as e:
        raise CryptoPaymentError(f"خطا از درگاه پرداخت: {e}")

    db.create_crypto_invoice(
        txn_id=data["txn_id"], kind=kind, ref_id=ref_id, user_id=tg_id,
        amount_toman=amount_toman, source_amount_usd=source_amount_usd,
        invoice_url=data.get("invoice_url"),
    )
    return {"invoice_url": data.get("invoice_url"), "txn_id": data["txn_id"]}
