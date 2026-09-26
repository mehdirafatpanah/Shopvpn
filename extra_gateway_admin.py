from i18n import tr
# -*- coding: utf-8 -*-
"""پنل ادمین بات اصلی برای درگاه‌های افزوده‌شده: تنظیمات، فهرست فاکتورها، بررسی و لغو."""

import asyncio

from aiogram import F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import extra_gateway_payment as egp
import extra_gateway_registry as registry
from config import API_BASE_URL
from states import AdminSetExtraGateway

_STATUS_TEXT = {
    "new": "🟡 جدید", "pending": "🟠 در انتظار", "completed": "🟢 تکمیل‌شده",
    "expired": "🔴 منقضی‌شده", "cancelled": "🔴 لغوشده",
}
_KIND_TEXT = {"order": "🧾 سفارش", "wallet_topup": "👛 شارژ کیف پول", "reseller_request": "🏪 هزینه نمایندگی"}


def _mask(value: str) -> str:
    return f"...{value[-4:]}" if value and len(value) > 4 else ("•••" if value else "")


def gateway_settings_kb(db, key: str) -> InlineKeyboardMarkup:
    meta = registry.GATEWAYS[key]
    enabled = db.get_setting(registry.enable_setting(key), "0") == "1"
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(
            text="🔴 غیرفعال کردن" if enabled else "🟢 فعال کردن", callback_data=f"adm_xgw_toggle:{key}",
        )],
    ]
    for idx, field in enumerate(meta["fields"]):
        value = (db.get_setting(field["setting"], "") or "").strip()
        if field["secret"]:
            shown = "✅ تنظیم شده" if value else "❌ تنظیم نشده"
        elif field["numeric"]:
            shown = f"{value or '0'}"
        else:
            shown = value or "❌ تنظیم نشده"
        label = field["label"] if len(field["label"]) <= 28 else field["label"][:26] + "…"
        rows.append([InlineKeyboardButton(text=tr(f"{label}: {shown} (تغییر)"), callback_data=f"adm_xgw_set:{key}:{idx}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gateway_settings_text(db, key: str) -> str:
    meta = registry.GATEWAYS[key]
    lines = [f"{meta['icon']} تنظیم درگاه {meta['title']}", "", meta["help"]]
    tenant_id = db.get_setting("miniapp_tenant_id", "")
    if meta["needs_base_url"]:
        if not API_BASE_URL:
            lines += ["", "⚠️ MINIAPP_URL روی سرور تنظیم نشده؛ بدون آن این درگاه فعال نمی‌شود."]
        elif key == "nowpayments":
            lines += ["", f"🔗 آدرس IPN:\n{egp.ipn_url(tenant_id)}"]
        else:
            lines += ["", f"🔗 آدرس برگشت (باید با دامنه‌ی ثبت‌شده در درگاه یکی باشد):\n{egp.callback_url(tenant_id, key)}"]
    lines += ["", "حداقل مبلغ این درگاه را از «حداقل مبلغ پرداخت‌ها» در همین بخش مالی تنظیم کن."]
    return "\n".join(lines)


def invoices_kb(invoices, gateway: str) -> InlineKeyboardMarkup:
    rows = []
    for inv in invoices:
        meta = registry.GATEWAYS.get(inv["gateway"], {"icon": "💠", "title": inv["gateway"]})
        st = _STATUS_TEXT.get(inv["status"], inv["status"] or "---")
        kind = _KIND_TEXT.get(inv["kind"], inv["kind"])
        row = [InlineKeyboardButton(
            text=f"{st} | {meta['icon']} {meta['title']} | {kind} #{inv['ref_id']} | {inv['amount_toman']:,}",
            callback_data=f"view_xgw_invoice:{inv['id']}",
        )]
        if inv["status"] in ("new", "pending"):
            if inv["gateway"] != "tgstars":
                row.append(InlineKeyboardButton(text="🔄", callback_data=f"check_xgw_invoice:{inv['id']}"))
            row.append(InlineKeyboardButton(text="❌", callback_data=f"cancel_xgw_invoice:{inv['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text=tr("🔄 بروزرسانی"), callback_data=f"adm_xgw_payments:{gateway}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def register(router, db, is_main_bot: bool, admin_only, full_admin_only, deny_support, replace_admin_view,
             safe_edit, callback_id):
    if not is_main_bot:
        return

    async def _load_invoices(gateway: str):
        await asyncio.to_thread(db.expire_stale_extra_invoices)
        await asyncio.to_thread(db.purge_old_extra_invoices, 7)
        return await asyncio.to_thread(db.list_extra_invoices, 50, gateway)

    async def _show_invoices(call: CallbackQuery, key: str):
        meta = registry.GATEWAYS[key]
        invoices = await _load_invoices(key)
        if not invoices:
            await replace_admin_view(
                call, f"{meta['icon']} پرداخت‌های {meta['title']}\n\nهیچ پرداختی ثبت نشده است.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=tr("🔄 بروزرسانی"), callback_data=f"adm_xgw_payments:{key}")],
                    [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")],
                ]),
            )
            return
        await replace_admin_view(
            call,
            f"{meta['icon']} پرداخت‌های {meta['title']}\n\n"
            "این پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=invoices_kb(invoices, key),
        )

    async def _show_gateway(call: CallbackQuery, key: str):
        await replace_admin_view(
            call, gateway_settings_text(db, key), reply_markup=gateway_settings_kb(db, key),
        )

    @router.callback_query(F.data.startswith("adm_xgw:"))
    async def cb_xgw_open(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        key = call.data.split(":", 1)[1]
        if key not in registry.GATEWAYS:
            await call.answer(tr("درگاه نامعتبر."), show_alert=True)
            return
        await _show_gateway(call, key)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_xgw_toggle:"))
    async def cb_xgw_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        key = call.data.split(":", 1)[1]
        if key not in registry.GATEWAYS:
            await call.answer(tr("درگاه نامعتبر."), show_alert=True)
            return
        setting = registry.enable_setting(key)
        enabled = (await asyncio.to_thread(db.get_setting, setting, "0")) == "1"
        if not enabled:
            missing = await asyncio.to_thread(egp.missing_fields, db, key)
            if missing:
                await call.answer("⚠️ اول این موارد را تنظیم کن: " + "، ".join(missing), show_alert=True)
                return
            if not egp.is_configured(db, key):
                await call.answer(tr("⚠️ MINIAPP_URL روی سرور تنظیم نشده است."), show_alert=True)
                return
        new_value = "0" if enabled else "1"
        await asyncio.to_thread(db.set_setting, setting, new_value)
        await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, f"xgw_toggle_{key}", f"وضعیت درگاه {key}: {new_value}",
        )
        await safe_edit(call, call.message.text, reply_markup=gateway_settings_kb(db, key))
        await call.answer(tr("✅ به‌روزرسانی شد."))

    @router.callback_query(F.data.startswith("adm_xgw_set:"))
    async def cb_xgw_set(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        try:
            _, key, idx_text = call.data.split(":")
            field = registry.GATEWAYS[key]["fields"][int(idx_text)]
        except (ValueError, KeyError, IndexError):
            await call.answer(tr("درخواست نامعتبر."), show_alert=True)
            return
        current = (await asyncio.to_thread(db.get_setting, field["setting"], "")).strip()
        if field["secret"]:
            shown = _mask(current) or "❌ تنظیم نشده"
        else:
            shown = current or "❌ تنظیم نشده"
        await state.set_state(AdminSetExtraGateway.waiting_value)
        await state.update_data(xgw_key=key, xgw_idx=int(idx_text))
        await safe_edit(
            call,
            f"✏️ {field['label']}\n\nمقدار جدید را ارسال کن.\nوضعیت فعلی: {shown}\n\n"
            "برای پاک‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"adm_xgw:{key}"),
            ]]),
        )
        await call.answer()

    @router.message(AdminSetExtraGateway.waiting_value)
    async def process_xgw_value(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            await state.clear()
            return
        data = await state.get_data()
        await state.clear()
        key = data.get("xgw_key")
        try:
            field = registry.GATEWAYS[key]["fields"][int(data.get("xgw_idx"))]
        except (KeyError, IndexError, TypeError, ValueError):
            await message.answer(tr("❌ درخواست منقضی شد؛ دوباره از منو اقدام کن."))
            return
        text = (message.text or "").strip()
        if field["secret"]:
            try:
                await message.delete()
            except Exception:
                pass
        clear = text in ("حذف", "/حذف", "-")
        if not clear and field["numeric"]:
            number = egp._to_float(text)
            if number < 0 or (field["required"] and number <= 0):
                await message.answer(tr("❌ یک عدد معتبر (بزرگ‌تر از صفر) بفرست."), reply_markup=gateway_settings_kb(db, key))
                return
            text = str(int(number)) if number == int(number) else str(number)
        if not clear and not text:
            await message.answer(tr("❌ مقدار خالی است."), reply_markup=gateway_settings_kb(db, key))
            return
        value = ("0" if field["numeric"] else "") if clear else text
        await asyncio.to_thread(db.set_setting, field["setting"], value)
        if clear and field["required"]:
            await asyncio.to_thread(db.set_setting, registry.enable_setting(key), "0")
        await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, f"xgw_setting_{key}",
            f"{field['setting']} {'حذف شد' if clear else 'تغییر کرد'}.",
        )
        await message.answer(
            "✅ ذخیره شد." if not clear else "✅ حذف شد" + (" و درگاه غیرفعال شد." if field["required"] else "."),
            reply_markup=gateway_settings_kb(db, key),
        )

    @router.callback_query(F.data.startswith("adm_xgw_payments:"))
    async def cb_xgw_payments(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        key = call.data.split(":", 1)[1]
        if key not in registry.GATEWAYS:
            await call.answer(tr("درگاه نامعتبر."), show_alert=True)
            return
        await _show_invoices(call, key)
        await call.answer()

    @router.callback_query(F.data.startswith("view_xgw_invoice:"))
    async def cb_view_xgw_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "view_xgw_invoice")
        invoice = await asyncio.to_thread(db.get_extra_invoice, invoice_id) if invoice_id else None
        if not invoice:
            await call.answer(tr("فاکتور یافت نشد."), show_alert=True)
            return
        meta = registry.GATEWAYS.get(invoice["gateway"], {"icon": "💠", "title": invoice["gateway"]})
        text = (
            f"{meta['icon']} فاکتور {meta['title']} #{invoice['id']}\n"
            f"{_KIND_TEXT.get(invoice['kind'], invoice['kind'])}: #{invoice['ref_id']}\n"
            f"👤 کاربر: {invoice['user_id']}\n"
            f"💰 مبلغ: {invoice['amount_toman']:,} تومان\n"
        )
        if invoice["gateway"] == "tgstars":
            text += f"⭐ تعداد استارز: {invoice['payable_amount']}\n"
        elif invoice["payable_amount"] and int(invoice["payable_amount"]) != int(invoice["amount_toman"]):
            text += f"💳 مبلغ قابل پرداخت: {int(invoice['payable_amount']):,} تومان\n"
        if invoice["remote_id"]:
            text += f"🔖 شناسه درگاه: {invoice['remote_id']}\n"
        text += (
            f"📌 وضعیت: {_STATUS_TEXT.get(invoice['status'], invoice['status'] or '---')}\n"
            f"🕐 ایجاد: {invoice['created_at'] or '---'}"
        )
        rows = []
        active = invoice["status"] in ("new", "pending")
        if invoice["payment_url"] and active:
            rows.append([InlineKeyboardButton(text=tr("🔗 باز کردن فاکتور"), url=invoice["payment_url"])])
        if active:
            if invoice["gateway"] != "tgstars":
                rows.append([InlineKeyboardButton(text=tr("🔄 بررسی وضعیت"), callback_data=f"check_xgw_invoice:{invoice['id']}")])
            rows.append([InlineKeyboardButton(text=tr("❌ لغو و حذف فاکتور"), callback_data=f"cancel_xgw_invoice:{invoice['id']}")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_xgw_payments:{invoice['gateway']}")])
        await replace_admin_view(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("check_xgw_invoice:"))
    async def cb_check_xgw_invoice(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "check_xgw_invoice")
        invoice = await asyncio.to_thread(db.get_extra_invoice, invoice_id) if invoice_id else None
        if not invoice:
            await call.answer(tr("فاکتور یافت نشد."), show_alert=True)
            return
        await call.answer(tr("در حال بررسی..."))
        result, text = await egp.process_invoice(db, bot, invoice)
        if result == "verified_now":
            await call.message.answer(text or "✅ پرداخت تایید و تحویل داده شد.")
        elif result == "not_paid_yet":
            await call.message.answer(tr("⏳ هنوز پرداختی برای این فاکتور تایید نشده."))
        elif result == "already_delivered":
            await call.message.answer(tr("✅ این پرداخت قبلاً تایید و تحویل داده شده است."))
        elif result == "expired":
            await call.message.answer(tr("❌ اعتبار این فاکتور تمام شده یا لغو شده است."))
        elif result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))

    @router.callback_query(F.data.startswith("cancel_xgw_invoice:"))
    async def cb_cancel_xgw_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "cancel_xgw_invoice")
        invoice = await asyncio.to_thread(db.get_extra_invoice, invoice_id) if invoice_id else None
        if not invoice:
            await call.answer(tr("فاکتور یافت نشد یا قبلاً حذف شده."), show_alert=True)
            return
        await asyncio.to_thread(db.cancel_and_delete_extra_invoice, invoice_id)
        await call.answer(tr("✅ فاکتور لغو و حذف شد."))
        await _show_invoices(call, invoice["gateway"])
