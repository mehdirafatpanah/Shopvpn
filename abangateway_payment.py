# -*- coding: utf-8 -*-
"""
منطق مشترک ساخت/تأیید فاکتور پرداخت کارت‌به‌کارت خودکار آبان گیت وی که هم از سرور
مینی‌اپ (miniapp/server.py، برای دریافت وب‌هوک) و هم مستقیم از داخل بات
(handlers_user.py، برای ساخت فاکتور و بررسی دستی وضعیت) قابل استفاده است.

نکته درباره‌ی مبلغ: بقیه‌ی پروژه مبالغ را به «تومان» نگه می‌دارد؛ API آبان گیت وی
مبلغ را به «ریال» می‌خواهد (۱ تومان = ۱۰ ریال). تبدیل این‌جا انجام می‌شود.

نکته درباره‌ی وب‌هوک: مستندات رسمی آبان گیت وی قالب دقیق بدنه‌ی وب‌هوک (و مکانیزم
امضای آن) را مشخص نکرده است. به همین دلیل، این ماژول به بدنه‌ی وب‌هوک اعتماد نمی‌کند؛
فقط از آن برای پیدا کردن invoice_id استفاده می‌کند و سپس با فراخوانی مستقیم API
(با کلید API خودمان که بدنه‌ی وب‌هوک نمی‌تواند جعل کند) وضعیت واقعی فاکتور را
استعلام و سپس verify می‌کند. تابع try_verify_and_finalize منبع حقیقت است و هم از
مسیر وب‌هوک و هم از مسیر «بررسی دستی وضعیت» در بات صدا زده می‌شود.
"""

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


def abangateway_payment_available(db) -> bool:
    return (
        db.get_setting("abangateway_payment_enabled", "0") == "1"
        and bool(resolve_api_key(db))
        and bool(API_BASE_URL)
    )


def toman_to_rial(amount_toman: int) -> int:
    return int(amount_toman) * 10


def rial_to_toman(amount_rial: int) -> int:
    return int(amount_rial) // 10


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


async def finalize_paid_order(db, bot, order_id: int, notify_admins_fn=None) -> str:
    """پس از تأیید پرداخت آبان گیت وی برای یک سفارش (کانفیگ شخصی یا خرید از کاتالوگ)،
    کانفیگ را می‌سازد/برمی‌دارد، سفارش را تایید و به کاربر تحویل می‌دهد.
    notify_admins_fn (اختیاری) یک async callable(bot, order_id) برای اطلاع‌رسانی به ادمین‌هاست
    (در فلوی بات با _notify_admins_of_order پر می‌شود؛ در پنل ادمین لازم نیست چون ادمین
    خودش همان‌جا در حال بررسی است).
    خروجی متن کوتاهی برای نمایش است."""
    order = db.get_order(order_id)
    if not order:
        return "⚠️ سفارش یافت نشد."
    if order["status"] != "pending":
        return "✅ این سفارش قبلاً بررسی و تحویل داده شده است."

    if order["is_renewal"]:
        try:
            result_text = await execute_renewal(db, order)
        except RenewalError as e:
            return f"⛔️ تمدید ناموفق بود: {e}\nبا پشتیبانی تماس بگیرید."
        db.approve_renewal_order(order_id)
        try:
            await bot.send_message(order["user_id"], result_text)
        except Exception:
            pass
        if notify_admins_fn:
            try:
                await notify_admins_fn(bot, order_id)
            except Exception:
                pass
        return result_text

    if order["is_custom_config"]:
        server = db.get_panel_server(order["custom_panel_server_id"])
        if not server:
            return "⛔️ سرور مربوط به کانفیگ شخصی یافت نشد؛ با پشتیبانی تماس بگیرید."
        duration_days = db.get_custom_config_settings()["duration_days"]
        try:
            provider = get_provider(server)
            result = await provider.create_user(order["custom_username"], order["custom_volume_gb"], duration_days)
        except Exception as e:
            return f"⛔️ خطا در ساخت کانفیگ روی پنل: {e}\nبا پشتیبانی تماس بگیرید."
        db.add_custom_config(
            order["user_id"], server["id"], result.username, order["custom_volume_gb"],
            duration_days, result.subscription_url, order_id=order_id,
        )
        db.approve_custom_config_order(order_id)
        await deliver_config_to_user(
            bot, order["user_id"], "کانفیگ شخصی",
            [result.subscription_url], final_price=order["final_price"], order_id=order_id, db=db,
        )
    else:
        product = db.get_product(order["product_id"])
        quantity = order["quantity"] or 1
        if product and product["is_auto_provision"]:
            try:
                if product["provision_server_id"]:
                    prov_results = await provision_direct(db, product, quantity, user_id=order["user_id"], order_id=order_id)
                else:
                    prov_results = await provision_auto_config(db, product, quantity, user_id=order["user_id"], order_id=order_id)
            except (ProvisionError, DirectProvisionError) as e:
                return f"⚠️ پرداخت تایید شد ولی ساخت خودکار کانفیگ ناموفق بود: {e}\nبا پشتیبانی تماس بگیرید."
            db.approve_order_auto(order_id)
            links = [r["subscription_url"] for r in prov_results]
        else:
            results = db.take_unused_configs(order["product_id"], order["user_id"], quantity)
            if not results:
                return "⚠️ پرداخت تایید شد ولی موجودی هم‌زمان تمام شده؛ ادمین به‌زودی دستی رسیدگی می‌کند."
            db.approve_order(order_id, [r["id"] for r in results])
            links = [r["link"] for r in results]
            await check_and_notify_low_stock(bot.send_message, db, order["product_id"])
        await deliver_config_to_user(
            bot, order["user_id"], product["name"] if product else "",
            links, final_price=order["final_price"], order_id=order_id, db=db,
        )

    reward_info = db.reward_referrer_if_first_purchase(order["user_id"], order["base_price"])
    if reward_info:
        reward_amount, referrer_id = reward_info
        try:
            await bot.send_message(
                referrer_id,
                f"🤝 تبریک! یکی از زیرمجموعه‌های شما اولین خرید خود را انجام داد.\n"
                f"💰 {reward_amount:,} تومان به کیف پول شما اضافه شد.",
            )
        except Exception:
            pass
    if notify_admins_fn:
        try:
            await notify_admins_fn(bot, order_id)
        except Exception:
            pass
    return "✅ پرداخت تایید شد و کانفیگ تحویل داده شد."


async def finalize_paid_topup(db, topup_id: int) -> str:
    topup = db.get_topup(topup_id)
    if not topup:
        return "⚠️ درخواست شارژ یافت نشد."
    if topup["status"] != "pending":
        return "✅ این درخواست شارژ قبلاً بررسی شده است."
    db.approve_topup(topup_id)
    return f"✅ پرداخت تایید شد و {topup['amount']:,} تومان به کیف پول کاربر اضافه شد."


def extract_invoice_id_from_webhook(body: dict) -> str:
    """چون قالب دقیق بدنه‌ی وب‌هوک آبان گیت وی در مستندات مشخص نشده، چند نام فیلد
    محتمل را امتحان می‌کنیم. خودِ محتوای بدنه هرگز به‌عنوان منبع حقیقتِ وضعیت پرداخت
    استفاده نمی‌شود (نگاه کن به try_verify_and_finalize) - فقط برای پیدا کردن شناسه است."""
    for key in ("invoice_id", "id", "invoiceId", "invoice"):
        val = body.get(key)
        if val:
            return str(val)
    return None
