# -*- coding: utf-8 -*-
"""
منطق مشترک ساخت فاکتور «درگاه‌های پرداخت سفارشی/پویا» (payment_engine.GenericGateway)
که هم از سرور مینی‌اپ (miniapp/server.py، برای مدیریت و دریافت وب‌هوک) و هم
مستقیم از داخل بات اصلی (handlers_user.py، برای ساخت فاکتور از همان لحظه‌ی
خرید) قابل استفاده است.

نکته: وب‌هوک/بازگشت این درگاه‌ها (تکمیل نهایی سفارش/شارژ کیف‌پول) کاملاً در
سمت miniapp/server.py و بر اساس رکورد دیتابیس مدیریت می‌شود؛ برای آن مهم
نیست فاکتور از داخل بات ساخته شده یا از مینی‌اپ، پس این‌جا فقط «ساخت فاکتور»
پیاده‌سازی شده است.
"""

import json
import logging
from datetime import datetime, timezone

from config import API_BASE_URL
import payment_engine

logger = logging.getLogger("custom_gateway_payment")


class CustomGatewayPaymentError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین در فلوی یک درگاه سفارشی."""
    pass


def list_enabled_gateways(db):
    """لیست درگاه‌های سفارشی فعال، برای نمایش به‌عنوان دکمه‌ی روش پرداخت در بات."""
    if not API_BASE_URL:
        return []
    rows = db.list_custom_gateways(only_enabled=True)
    return [{"id": r["id"], "key": r["gateway_key"], "name": r["name"]} for r in rows]


def custom_gateway_payment_available(db) -> bool:
    return bool(list_enabled_gateways(db))


def _load_gateway(db, gateway_key: str):
    row = db.get_custom_gateway_by_key(gateway_key)
    if not row:
        raise CustomGatewayPaymentError("این درگاه پیدا نشد.")
    if not row["enabled"]:
        raise CustomGatewayPaymentError("این درگاه فعال نیست.")
    try:
        config = json.loads(row["config_json"])
    except Exception:
        config = {}
    return row, config


async def create_invoice_for(db, tenant_id: str, tg_id: int, gateway_key: str, kind: str,
                              ref_id: int, amount_toman: int, order_name: str) -> dict:
    """یک فاکتور برای سفارش (kind='order') یا شارژ کیف پول (kind='wallet_topup') با
    درگاه سفارشی gateway_key می‌سازد و آن را در جدول custom_gateway_invoices ثبت می‌کند.
    خروجی: {"invoice_url": ..., "txn_id": ...}
    در صورت خطا CustomGatewayPaymentError صادر می‌شود."""
    if not API_BASE_URL:
        raise CustomGatewayPaymentError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")

    row, config = _load_gateway(db, gateway_key)

    existing = db.get_pending_custom_gateway_invoice_for_ref(row["id"], kind, ref_id)
    if existing:
        return {"invoice_url": existing["invoice_url"], "txn_id": existing["txn_id"]}

    tenant_slug = tenant_id or "main"
    our_ref = f"{kind}-{tenant_slug}-{ref_id}-{int(datetime.now(timezone.utc).timestamp())}"
    # برخی درگاه‌ها (مثل TonPays) سقف طول کاراکتر برای order_id دارند (مثلاً حداکثر
    # ۲۰ کاراکتر)؛ چون ردیابی واقعی سفارش از طریق gateway_ref (شناسه‌ای که خودِ
    # درگاه در پاسخ create_invoice برمی‌گرداند) انجام می‌شود نه با پارس order_id،
    # اینجا یک نسخه‌ی کوتاه‌شده و یکتا فقط برای ارسال به درگاه می‌سازیم؛ our_ref
    # کامل همچنان برای callback_url/webhook_url و ذخیره‌ی txn_id داخلی حفظ می‌شود.
    short_order_id = f"{ref_id}-{int(datetime.now(timezone.utc).timestamp())}"[:20]
    gw = payment_engine.GenericGateway(config)
    try:
        result = await gw.create_invoice(
            amount=amount_toman, amount_toman=amount_toman, order_id=short_order_id,
            currency="IRT", description=order_name, tenant_id=tenant_slug,
            callback_url=f"{API_BASE_URL}/api/pay/custom/{gateway_key}/return?b={tenant_id or ''}&txn={our_ref}",
            webhook_url=f"{API_BASE_URL}/api/webhooks/custom/{gateway_key}?b={tenant_id or ''}",
        )
    except payment_engine.PaymentEngineError as e:
        raise CustomGatewayPaymentError(str(e))

    invoice_id = db.create_custom_gateway_invoice(
        row["id"], our_ref, kind, ref_id, tg_id, amount_toman, invoice_url=result.get("invoice_url"),
    )
    if result.get("txn_id") and result.get("txn_id") != our_ref:
        db.set_custom_gateway_invoice_gateway_ref(invoice_id, result.get("txn_id"))
    return {"invoice_url": result.get("invoice_url"), "txn_id": our_ref}
