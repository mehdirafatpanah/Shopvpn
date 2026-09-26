from i18n import tr
# -*- coding: utf-8 -*-
"""منطق مشترک ساخت، بررسی و تحویل فاکتور درگاه‌های زرین‌پال، آقای پرداخت، تترا۹۸، کیوب‌پی، NowPayments و استارز داخلی تلگرام (فقط بات اصلی)."""

import asyncio
import json
import logging
import math
import secrets

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import abangateway_payment
import crypto_payment
import exchange_rate
import extra_gateway_clients as clients
import extra_gateway_registry as registry
import report_router
from config import API_BASE_URL

logger = logging.getLogger("extra_gateway_payment")

_order_notifiers = {}


class ExtraGatewayError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین در فلوی درگاه‌های افزوده‌شده."""


def register_order_notifier(db, fn):
    _order_notifiers[id(db)] = fn


def spec(key: str) -> dict:
    if key not in registry.GATEWAYS:
        raise ExtraGatewayError("درگاه نامعتبر است.")
    return registry.GATEWAYS[key]


def _field_value(db, field: dict) -> str:
    return (db.get_setting(field["setting"], "") or "").strip()


def missing_fields(db, key: str) -> list:
    out = []
    for field in spec(key)["fields"]:
        if not field["required"]:
            continue
        value = _field_value(db, field)
        if not value or (field["numeric"] and _to_float(value) <= 0):
            out.append(field["label"])
    return out


def _to_float(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("،", ""))
    except (TypeError, ValueError):
        return 0.0


def is_configured(db, key: str) -> bool:
    if missing_fields(db, key):
        return False
    return bool(API_BASE_URL) or not spec(key)["needs_base_url"]


def is_available(db, key: str, is_main_bot: bool = True) -> bool:
    return (
        is_main_bot
        and db.get_setting(registry.enable_setting(key), "0") == "1"
        and is_configured(db, key)
    )


def available_keys(db, is_main_bot: bool = True) -> list:
    return [k for k in registry.GATEWAY_ORDER if is_available(db, k, is_main_bot)]


def callback_url(tenant_id: str, key: str) -> str:
    if not API_BASE_URL:
        raise ExtraGatewayError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")
    return f"{API_BASE_URL}/api/pay-return/{key}?b={tenant_id or ''}"


def ipn_url(tenant_id: str) -> str:
    if not API_BASE_URL:
        raise ExtraGatewayError("آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده است.")
    return f"{API_BASE_URL}/api/webhooks/nowpayments?b={tenant_id or ''}"


def _order_number(kind: str, ref_id: int) -> str:
    code = {"order": "o", "wallet_topup": "w", "reseller_request": "r"}.get(kind, "x")
    return f"{code}{ref_id}x{secrets.token_hex(4)}"


STAR_USD_DEFAULT = 0.013  # مبلغی که توسعه‌دهنده بابت هر استارز دریافت می‌کند (دلار)


async def resolve_star_rate(db) -> float:
    """نرخ هر ۱ استارز به تومان.
    ۱) اگر «نرخ دستی» (tgstars_rate_toman_per_star) بزرگ‌تر از صفر باشد همان ثابت استفاده می‌شود.
    ۲) وگرنه: نرخ لحظه‌ای دلار × ارزش هر استارز به دلار × (۱ + حاشیه سود٪).
    ۳) اگر دریافت نرخ دلار کاملاً شکست بخورد، آخرین نرخ خودکار موفق استفاده می‌شود."""
    manual = _to_float(db.get_setting("tgstars_rate_toman_per_star", "0"))
    if manual > 0:
        return manual
    usd_per_star = _to_float(db.get_setting("tgstars_usd_per_star", str(STAR_USD_DEFAULT))) or STAR_USD_DEFAULT
    margin = max(0.0, _to_float(db.get_setting("tgstars_margin_percent", "0")))
    fallback = (
        _to_float(db.get_setting("manual_usd_rate_toman", "0"))
        or _to_float(db.get_setting("usd_to_toman_rate", "0"))
    )
    try:
        usd_rate = await exchange_rate.get_usd_to_toman_rate(manual_fallback=fallback or None)
    except Exception as e:
        last = _to_float(db.get_setting("tgstars_last_auto_rate", "0"))
        if last > 0:
            logger.warning("دریافت نرخ دلار برای استارز ناموفق بود؛ استفاده از آخرین نرخ ذخیره‌شده (%s): %s", last, e)
            return last
        logger.error("دریافت نرخ دلار برای استارز ناموفق بود: %s", e)
        raise ExtraGatewayError(
            "دریافت خودکار نرخ استارز ناموفق بود. ادمین می‌تواند «نرخ دستی هر استارز» را در تنظیمات همین درگاه وارد کند."
        )
    rate = usd_rate * usd_per_star * (1 + margin / 100)
    if rate <= 0:
        raise ExtraGatewayError("نرخ استارز نامعتبر است.")
    rate = round(rate, 2)
    if abs(rate - _to_float(db.get_setting("tgstars_last_auto_rate", "0"))) >= 0.01:
        await asyncio.to_thread(db.set_setting, "tgstars_last_auto_rate", str(rate))
    return rate


async def stars_for_amount(db, amount_toman: int) -> int:
    rate = await resolve_star_rate(db)
    return max(1, math.ceil(int(amount_toman) / rate))


def cubepay_payable(db, amount_toman: int) -> int:
    return clients.cubepay_payable_toman(amount_toman, _to_float(db.get_setting("cubepay_fee", "0")))


async def create_invoice_for(db, tenant_id: str, tg_id: int, gateway: str, kind: str, ref_id: int,
                              amount_toman: int, order_name: str) -> dict:
    """فاکتور درگاه را می‌سازد یا فاکتور فعال قبلی را برمی‌گرداند؛ خروجی: {invoice_id, payment_url, meta, payable_amount}."""
    spec(gateway)
    if not is_available(db, gateway):
        raise ExtraGatewayError("این درگاه در حال حاضر فعال یا کامل تنظیم نشده است.")

    existing = await asyncio.to_thread(db.get_pending_extra_invoice_for_ref, gateway, kind, ref_id)
    if existing:
        return _result(existing)

    order_number = _order_number(kind, ref_id)
    amount_toman = int(amount_toman)
    payable = amount_toman
    try:
        if gateway == "tgstars":
            payable = await stars_for_amount(db, amount_toman)
            created = {"remote_id": None, "payment_url": None, "meta": {}}
        elif gateway == "zarinpal":
            created = await clients.zarinpal_create(
                db.get_setting("zarinpal_merchant_id", "").strip(), amount_toman,
                callback_url(tenant_id, gateway), order_name, order_number,
            )
        elif gateway == "aqayepardakht":
            created = await clients.aqayepardakht_create(
                db.get_setting("aqayepardakht_pin", "").strip(), amount_toman,
                callback_url(tenant_id, gateway), order_name, order_number,
            )
        elif gateway == "tetra98":
            created = await clients.tetra98_create(
                db.get_setting("tetra98_api_key", "").strip(), amount_toman,
                callback_url(tenant_id, gateway), order_name, order_number,
            )
        elif gateway == "cubepay":
            payable = cubepay_payable(db, amount_toman)
            created = await clients.cubepay_create(
                db.get_setting("cubepay_token", "").strip(), payable,
                callback_url(tenant_id, gateway), order_name, order_number, tg_id,
            )
        else:
            try:
                price_usd = await crypto_payment.toman_to_usd(db, amount_toman)
            except crypto_payment.CryptoPaymentError as e:
                raise ExtraGatewayError(str(e))
            created = await clients.nowpayments_create_invoice(
                db.get_setting("nowpayments_api_key", "").strip(), price_usd, order_number, order_name,
                ipn_url(tenant_id),
            )
    except clients.GatewayError as e:
        raise ExtraGatewayError(str(e))

    invoice_id = await asyncio.to_thread(
        db.create_extra_invoice, gateway, kind, ref_id, tg_id, amount_toman, payable,
        created["remote_id"], order_number, created["payment_url"], created["meta"],
    )
    row = await asyncio.to_thread(db.get_extra_invoice, invoice_id)
    return _result(row)


def _result(row) -> dict:
    try:
        meta = json.loads(row["meta"] or "{}")
    except (TypeError, ValueError):
        meta = {}
    return {
        "invoice_id": row["id"], "payment_url": row["payment_url"], "meta": meta,
        "payable_amount": row["payable_amount"], "gateway": row["gateway"],
    }


def _meta(row) -> dict:
    try:
        return json.loads(row["meta"] or "{}")
    except (TypeError, ValueError):
        return {}


async def _remote_state(db, invoice) -> str:
    gateway = invoice["gateway"]
    remote_id = invoice["remote_id"]
    amount = int(invoice["amount_toman"])
    if gateway == "zarinpal":
        return await clients.zarinpal_verify(db.get_setting("zarinpal_merchant_id", "").strip(), amount, remote_id)
    if gateway == "aqayepardakht":
        return await clients.aqayepardakht_verify(db.get_setting("aqayepardakht_pin", "").strip(), amount, remote_id)
    if gateway == "tetra98":
        return await clients.tetra98_verify(db.get_setting("tetra98_api_key", "").strip(), remote_id)
    if gateway == "cubepay":
        payable = int(invoice["payable_amount"] or amount)
        return await clients.cubepay_verify(
            db.get_setting("cubepay_token", "").strip(), remote_id, invoice["order_number"], payable * 10,
        )
    if gateway == "nowpayments":
        meta = _meta(invoice)
        payment_id = meta.get("payment_id")
        if not payment_id:
            return clients.PENDING
        payment = await clients.nowpayments_payment_status(db.get_setting("nowpayments_api_key", "").strip(), payment_id)
        return clients.nowpayments_classify(payment, remote_id, invoice["order_number"], meta.get("price_usd") or 0)
    return clients.PENDING


async def check_invoice(db, invoice) -> str:
    """خروجی: already_delivered | verified_now | not_paid_yet | expired | error:<متن>."""
    if invoice["status"] == "completed":
        return "already_delivered"
    if invoice["status"] in ("expired", "cancelled"):
        return "expired"
    if invoice["gateway"] == "tgstars":
        return "not_paid_yet"
    try:
        state = await _remote_state(db, invoice)
    except clients.GatewayError as e:
        return f"error:{e}"
    if state == clients.FAILED:
        await asyncio.to_thread(db.update_extra_invoice_status, invoice["id"], "expired")
        return "expired"
    if state != clients.PAID:
        return "not_paid_yet"
    claimed = await asyncio.to_thread(db.claim_extra_invoice, invoice["id"])
    return "verified_now" if claimed else "already_delivered"


async def _notify_admins(db, bot, text: str):
    await report_router.report(bot, db, "error", text)


async def _finalize_reseller(db, bot, invoice) -> str:
    request_id = int(invoice["ref_id"])
    if not await asyncio.to_thread(db.complete_reseller_request_gateway_payment, request_id):
        return "✅ این پرداخت قبلاً ثبت شده است."
    req = await asyncio.to_thread(db.get_reseller_request, request_id)
    if not req:
        return "⚠️ درخواست نمایندگی یافت نشد."
    tier = await asyncio.to_thread(db.get_reseller_tier, req["tier_code"]) if req["tier_code"] else None
    label = f"{tier['icon']} {tier['title']}" if tier else "نمایندگی"
    if req["status"] == "completed":
        extra = ""
        if tier and tier["model"] == "commission":
            extra = f"\n📈 درصد کمیسیون: {req['commission_percent'] or tier['commission_min'] or 10}٪"
        return f"✅ پرداخت هزینه {label} تایید شد و نمایندگی شما فعال شد.{extra}"
    markup = None
    if req["status"] == "awaiting_bot_info":
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr("🚀 ادامه فعال‌سازی نمایندگی"), callback_data=f"resreq_continue:{request_id}"),
        ]])
    try:
        await bot.send_message(
            req["user_id"],
            tr(f"✅ پرداخت هزینه {label} تایید شد!\n\nحالا توکن بات نمایندگی خودتان را از @BotFather ارسال کنید تا فعال‌سازی ادامه پیدا کند:"),
            reply_markup=markup,
        )
    except Exception:
        pass
    return ""


async def deliver(db, bot, invoice, notify_admins_fn=None) -> str:
    """پس از claim شدن فاکتور، سفارش/شارژ/هزینه‌ی نمایندگی را تحویل می‌دهد و متن کوتاه نتیجه را برمی‌گرداند."""
    kind = invoice["kind"]
    ref_id = int(invoice["ref_id"])
    title = registry.GATEWAYS[invoice["gateway"]]["title"]
    if kind == "wallet_topup":
        return await abangateway_payment.finalize_paid_topup(db, ref_id)
    if kind == "reseller_request":
        return await _finalize_reseller(db, bot, invoice)
    order = await asyncio.to_thread(db.get_order, ref_id)
    if not order:
        await _notify_admins(db, bot, f"⚠️ پرداخت {title} برای سفارش #{ref_id} دریافت شد ولی سفارش پیدا نشد.")
        return "⚠️ پرداخت شما دریافت شد ولی سفارش یافت نشد. با پشتیبانی تماس بگیرید."
    if order["status"] not in ("pending", "approved"):
        await _notify_admins(
            db, bot,
            f"⚠️ پرداخت {title} برای سفارش #{ref_id} (کاربر {invoice['user_id']}) دریافت شد "
            f"ولی وضعیت سفارش «{order['status']}» است. لطفاً دستی رسیدگی کنید.",
        )
        return "⚠️ پرداخت شما دریافت شد ولی این سفارش دیگر فعال نیست. با پشتیبانی تماس بگیرید."
    notifier = notify_admins_fn or _order_notifiers.get(id(db))
    text = await abangateway_payment.finalize_paid_order(db, bot, ref_id, notify_admins_fn=notifier)
    if text.startswith(("⛔️", "⚠️")):
        await _notify_admins(
            db, bot,
            f"⚠️ پرداخت {title} برای سفارش #{ref_id} (کاربر {invoice['user_id']}) تایید شد ولی تحویل خودکار ناموفق بود:\n{text}",
        )
    return text


async def process_invoice(db, bot, invoice, notify_admins_fn=None):
    """بررسی وضعیت و در صورت پرداخت، تحویل. خروجی: (result, text)."""
    result = await check_invoice(db, invoice)
    if result != "verified_now":
        return result, ""
    try:
        text = await deliver(db, bot, invoice, notify_admins_fn)
    except Exception:
        logger.exception("خطای غیرمنتظره در تحویل فاکتور %s", invoice["id"])
        await asyncio.to_thread(db.release_extra_invoice, invoice["id"])
        return "error:خطای غیرمنتظره در تحویل؛ دوباره بررسی می‌شود.", ""
    return result, text


def stars_payload(invoice_id: int) -> str:
    return f"xg:{invoice_id}"


def parse_stars_payload(payload: str):
    if not payload or not payload.startswith("xg:"):
        return None
    try:
        return int(payload.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


async def ref_still_payable(db, invoice) -> bool:
    kind = invoice["kind"]
    ref_id = int(invoice["ref_id"])
    if kind == "order":
        order = await asyncio.to_thread(db.get_order, ref_id)
        return bool(order and order["status"] == "pending")
    if kind == "wallet_topup":
        topup = await asyncio.to_thread(db.get_topup, ref_id)
        return bool(topup and topup["status"] == "pending")
    return True


async def process_stars_payment(db, bot, invoice_id: int, user_id: int, total_amount: int, currency: str,
                                charge_id: str, notify_admins_fn=None) -> str:
    invoice = await asyncio.to_thread(db.get_extra_invoice, invoice_id)
    if not invoice or invoice["gateway"] != "tgstars" or int(invoice["user_id"]) != int(user_id):
        await _notify_admins(db, bot, f"⚠️ پرداخت استارز با payload نامعتبر از کاربر {user_id} (شارژ {charge_id}). دستی بررسی کن.")
        return "⚠️ پرداخت دریافت شد ولی فاکتور یافت نشد. با پشتیبانی تماس بگیرید."
    if currency != "XTR" or int(total_amount) != int(invoice["payable_amount"] or 0):
        await _notify_admins(db, bot, f"⚠️ مبلغ استارز فاکتور #{invoice_id} با مقدار پرداخت‌شده نمی‌خواند (شارژ {charge_id}).")
        return "⚠️ مبلغ پرداخت‌شده با فاکتور نمی‌خواند. با پشتیبانی تماس بگیرید."
    await asyncio.to_thread(db.merge_extra_invoice_meta, invoice_id, {"charge_id": charge_id})
    if not await asyncio.to_thread(db.claim_extra_invoice, invoice_id):
        return "✅ این پرداخت قبلاً ثبت و تحویل داده شده است."
    invoice = await asyncio.to_thread(db.get_extra_invoice, invoice_id)
    try:
        return await deliver(db, bot, invoice, notify_admins_fn)
    except Exception:
        logger.exception("خطای غیرمنتظره در تحویل فاکتور استارز %s", invoice_id)
        await _notify_admins(db, bot, f"⚠️ خطای غیرمنتظره در تحویل فاکتور استارز #{invoice_id} (شارژ {charge_id}). دستی بررسی کن.")
        return "⚠️ پرداخت شما دریافت شد ولی تحویل با خطا مواجه شد. ادمین به‌زودی رسیدگی می‌کند."


async def poll_loop(bot, db, interval: int = 15):
    """حلقه‌ی پس‌زمینه‌ی بات اصلی: فاکتورهای باز را بررسی و در صورت پرداخت تحویل می‌دهد."""
    tick = 0
    last_checked = {}
    while True:
        try:
            tick += 1
            if tick % 8 == 1:
                await asyncio.to_thread(db.expire_stale_extra_invoices)
                await asyncio.to_thread(db.purge_old_extra_invoices, 7)
            now = asyncio.get_running_loop().time()
            for invoice in await asyncio.to_thread(db.list_open_extra_invoices, 100):
                seen = last_checked.get(invoice["id"], 0)
                if now - seen < 12:
                    continue
                last_checked[invoice["id"]] = now
                result, text = await process_invoice(db, bot, invoice)
                if result == "verified_now" and text:
                    try:
                        await bot.send_message(invoice["user_id"], text)
                    except Exception:
                        pass
            if len(last_checked) > 2000:
                last_checked.clear()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در حلقه‌ی بررسی فاکتورهای درگاه‌های افزوده‌شده")
        await asyncio.sleep(interval)
