from i18n import tr
# -*- coding: utf-8 -*-
"""هندلرهای کاربر برای درگاه‌های افزوده‌شده (فقط بات اصلی): انتخاب روش، ساخت فاکتور، بررسی وضعیت و استارز داخلی."""

import asyncio
import logging

from aiogram import F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery,
)

import extra_gateway_payment as egp
import extra_gateway_registry as registry
from states import BuyFlow, CustomConfigFlow, RenewalFlow, WalletTopup

logger = logging.getLogger("extra_gateway_user")

_DONE_TEXT = {
    "order": "معمولاً به‌محض پرداخت، سفارش خودکار تحویل داده می‌شود",
    "wallet_topup": "معمولاً به‌محض پرداخت، کیف پول خودکار شارژ می‌شود",
    "reseller_request": "معمولاً به‌محض پرداخت، درخواست نمایندگی شما ادامه پیدا می‌کند",
}


async def present_invoice(target: Message, bot: Bot, gateway: str, result: dict, kind: str, label: str,
                          amount_toman: int):
    """فاکتور ساخته‌شده را به کاربر نشان می‌دهد؛ برای استارز داخلی فاکتور تلگرامی می‌فرستد."""
    meta = registry.GATEWAYS[gateway]
    if gateway == "tgstars":
        stars = int(result["payable_amount"])
        try:
            await bot.send_invoice(
                chat_id=target.chat.id,
                title="پرداخت با استارز تلگرام",
                description=f"{label} - {amount_toman:,} تومان معادل {stars} استارز"[:255],
                payload=egp.stars_payload(result["invoice_id"]),
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=label[:60] or "پرداخت", amount=stars)],
            )
        except TelegramBadRequest as e:
            await target.answer(tr(f"⚠️ ساخت فاکتور استارز ناموفق بود: {e.message}"))
        return

    lines = [f"{meta['icon']} فاکتور پرداخت ({meta['title']}) ساخته شد. روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن."]
    if gateway == "cubepay":
        exact = result["meta"].get("pay_amount_toman") or result["payable_amount"]
        lines.append(f"💰 مبلغ دقیق قابل پرداخت: {int(exact):,} تومان")
    lines.append("⏳ اعتبار این فاکتور محدود است.")
    lines.append(
        f"{_DONE_TEXT.get(kind, _DONE_TEXT['order'])}؛ اگر چند دقیقه طول کشید، دکمه‌ی «بررسی وضعیت پرداخت» را بزن."
    )
    rows = [[InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])]]
    bot_url = result["meta"].get("bot_url")
    if gateway == "tetra98" and bot_url:
        rows.append([InlineKeyboardButton(text=tr("🤖 پرداخت از داخل ربات تترا۹۸"), url=bot_url)])
    rows.append([InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"xgw_check:{result['invoice_id']}")])
    await target.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


def register_early(router, db, is_main_bot: bool):
    """هندلرهایی که باید قبل از هندلرهای عمومی FSM ثبت شوند (استارز و دکمه‌ی بررسی وضعیت)."""
    if not is_main_bot:
        return

    @router.pre_checkout_query(F.invoice_payload.startswith("xg:"))
    async def stars_pre_checkout(query: PreCheckoutQuery):
        invoice_id = egp.parse_stars_payload(query.invoice_payload)
        invoice = await asyncio.to_thread(db.get_extra_invoice, invoice_id) if invoice_id else None
        ok = bool(
            invoice
            and invoice["gateway"] == "tgstars"
            and invoice["status"] in ("new", "pending")
            and int(invoice["user_id"]) == query.from_user.id
            and query.currency == "XTR"
            and int(query.total_amount) == int(invoice["payable_amount"] or 0)
            and await egp.ref_still_payable(db, invoice)
        )
        if ok:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message=tr("این فاکتور دیگر معتبر نیست. لطفاً دوباره از منو اقدام کن."))

    @router.message(F.successful_payment)
    async def stars_successful_payment(message: Message, bot: Bot):
        payment = message.successful_payment
        invoice_id = egp.parse_stars_payload(payment.invoice_payload)
        if invoice_id is None:
            return
        notifier = egp._order_notifiers.get(id(db))
        text = await egp.process_stars_payment(
            db, bot, invoice_id, message.from_user.id, payment.total_amount, payment.currency,
            payment.telegram_payment_charge_id, notifier,
        )
        if text:
            await message.answer(text)

    @router.callback_query(F.data.startswith("xgw_check:"))
    async def cb_check_extra_gateway(call: CallbackQuery, bot: Bot):
        try:
            invoice_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await call.answer(tr("داده نامعتبر."), show_alert=True)
            return
        invoice = await asyncio.to_thread(db.get_extra_invoice, invoice_id)
        if not invoice or invoice["user_id"] != call.from_user.id:
            await call.answer(tr("فاکتور یافت نشد."), show_alert=True)
            return
        await call.answer(tr("در حال بررسی وضعیت پرداخت..."))
        result, text = await egp.process_invoice(db, bot, invoice, egp._order_notifiers.get(id(db)))
        if result == "not_paid_yet":
            await call.message.answer(tr("⏳ هنوز پرداختی برای این فاکتور تایید نشده. کمی صبر کن و دوباره بررسی کن."))
        elif result == "expired":
            await call.message.answer(tr("❌ اعتبار این فاکتور تمام شده یا لغو شده. لطفاً دوباره از منو اقدام کن."))
        elif result == "already_delivered":
            await call.message.answer(tr("✅ این پرداخت قبلاً تایید و تحویل داده شده است."))
        elif result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))
        elif text:
            await call.message.answer(text)


def register(router, db, is_main_bot: bool, order_error, topup_error, notify_admins_of_order):
    """هندلرهای انتخاب روش پرداخت در چهار مسیر خرید، کانفیگ شخصی، تمدید و شارژ کیف پول."""
    if not is_main_bot:
        return
    egp.register_order_notifier(db, notify_admins_of_order)

    async def _order_label(order, order_id: int) -> str:
        keys = order.keys()
        if "is_renewal" in keys and order["is_renewal"]:
            return f"تمدید سرویس #{order_id}"
        if "is_custom_config" in keys and order["is_custom_config"]:
            return f"کانفیگ شخصی #{order_id} - {order['custom_username']}"
        product = await asyncio.to_thread(db.get_product, order["product_id"])
        return f"سفارش #{order_id} - {product['name'] if product else ''}"

    def make_order_handler(key: str):
        async def handler(call: CallbackQuery, state: FSMContext, bot: Bot):
            data = await state.get_data()
            order_id = data.get("order_id")
            order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
            if not order or order["status"] != "pending":
                await call.answer(tr("سفارش معتبر یافت نشد."), show_alert=True)
                return
            if not egp.is_available(db, key, is_main_bot):
                await call.answer(tr("این روش پرداخت در حال حاضر در دسترس نیست."), show_alert=True)
                return
            err = await order_error(order, key)
            if err:
                await call.answer(err, show_alert=True)
                return
            await call.answer(tr("در حال ساخت فاکتور..."))
            tenant_id = await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", "")
            label = await _order_label(order, order_id)
            try:
                result = await egp.create_invoice_for(
                    db, tenant_id, call.from_user.id, key, "order", order_id, order["final_price"], label,
                )
            except egp.ExtraGatewayError as e:
                await call.message.answer(f"⚠️ {e}")
                return
            await present_invoice(call.message, bot, key, result, "order", label, order["final_price"])
        return handler

    def make_topup_handler(key: str):
        async def handler(call: CallbackQuery, state: FSMContext, bot: Bot):
            data = await state.get_data()
            amount = data.get("topup_amount")
            if not amount:
                await call.answer(tr("درخواست معتبر یافت نشد."), show_alert=True)
                return
            if not egp.is_available(db, key, is_main_bot):
                await call.answer(tr("این روش پرداخت در حال حاضر در دسترس نیست."), show_alert=True)
                return
            err = await topup_error(amount, key)
            if err:
                await call.answer(err, show_alert=True)
                return
            await call.answer(tr("در حال ساخت فاکتور..."))
            topup_id = await asyncio.to_thread(db.create_topup, call.from_user.id, amount)
            tenant_id = await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", "")
            label = f"شارژ کیف پول #{topup_id}"
            try:
                result = await egp.create_invoice_for(
                    db, tenant_id, call.from_user.id, key, "wallet_topup", topup_id, amount, label,
                )
            except egp.ExtraGatewayError as e:
                await asyncio.to_thread(db.reject_topup, topup_id)
                await call.message.answer(f"⚠️ {e}")
                return
            await present_invoice(call.message, bot, key, result, "wallet_topup", label, amount)
        return handler

    for gateway_key in registry.GATEWAY_ORDER:
        callback = f"pay_{gateway_key}"
        order_handler = make_order_handler(gateway_key)
        for flow_state in (BuyFlow.waiting_receipt, CustomConfigFlow.waiting_receipt, RenewalFlow.waiting_receipt):
            router.callback_query.register(order_handler, F.data == callback, flow_state)
        router.callback_query.register(make_topup_handler(gateway_key), F.data == callback, WalletTopup.waiting_receipt)
