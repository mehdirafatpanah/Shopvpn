# -*- coding: utf-8 -*-
"""
هندلرهای مربوط به کاربر عادی

این فایل یک تابع کارخانه‌ای (factory) دارد: create_user_router(db).
چون هر بات (اصلی یا نمایندگی) دیتابیس مستقل خودش را دارد، این تابع یک
Router تازه می‌سازد که به همان یک db گره خورده؛ یعنی دقیقاً همان کد،
برای بات اصلی و هر بات نمایندگی، مستقل و کامل اجرا می‌شود.
"""

import os
import random
import re
import asyncio
import logging
from service_alerts import send_service_alert
import math
from datetime import datetime, timezone, timedelta

from aiogram import Router, F, Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError

from md_utils import escape_md, escape_html
import keyboards as kb
from states import BuyFlow, ContactFlow, TicketFlow, TicketReplyFlow, AIChatFlow, DiscountEntry, RenewalDiscountEntry, WalletTopup, WalletGiftCode, WalletTransfer, CoinConvert, CustomConfigFlow, RenewalFlow, ResellerFlow, ResellerRequestFlow, ServiceRenameFlow, ServiceTransferFlow, CommissionResellerRequestFlow
import ai_support
from service_refund import (
    quote_service_refund, refund_quote_text, wallet_refund_amount, grant_service_refund_credit, refund_result_text,
)
from config import MAX_TEST_PER_USER, RESELLER_DBS_DIR, resolve_db_path, DB_PATH, ADMIN_PANEL_URL
from database import Database, DuplicateBotTokenError
from config_delivery import deliver_config_to_user, send_individual_configs, build_qr_bytes
from renewal_engine import execute_renewal, RenewalError
import renewal_log
from temp_messages import schedule_message_autodelete
from force_join import is_channel_member, CHECK_CALLBACK
from sub_info import fetch_sub_info, format_sub_info_fa, fetch_individual_links
from jalali import to_jalali_str
from stock_alerts import check_and_notify_low_stock
from referral_fraud_alerts import check_and_notify_referral_fraud
import user_limit as ul
import crypto_payment
import abangateway_payment
import blupal_payment
import noapay_payment
import extra_gateway_payment
import extra_gateway_registry
import extra_gateway_user
import custom_gateway_payment
import card_to_card_payment
import report_router
import tutorial
import tutorial_hub
from panel_providers import get_provider, PanelError, PanelUsernameTakenError
from reseller_auto_provision import provision_auto_config, provision_test_config, provision_reseller_fixed_product, ProvisionError
from direct_panel_provision import provision_direct, planned_usernames, ProvisionError as DirectProvisionError
from test_config_provision import provision_test_plan, format_plan_amount, ProvisionError as TestPlanProvisionError
from i18n import set_language, reset_language, language_label, normalize_language, is_language_enabled, tr


async def _send_admin_notification(bot, admin_id, send_coro_factory, context_label: str, ref_id: int):
    """ارسال اعلان به یک ادمین با تلاش مجدد در برابر flood-limit و خطای شبکه.
    دلیل عدم دریافت نوتیف توسط ادمین (بلاک بودن ربات، فایل نامعتبر و ...) به‌صورت
    شفاف در logs/bot.log ثبت می‌شود تا قابل بررسی باشد."""
    log = logging.getLogger("handlers_user")
    for attempt in range(2):
        try:
            return await send_coro_factory()
        except TelegramRetryAfter as e:
            log.warning(
                "محدودیت ارسال تلگرام (flood) هنگام اطلاع %s #%s به ادمین %s؛ %s ثانیه صبر و تلاش مجدد.",
                context_label, ref_id, admin_id, e.retry_after,
            )
            await asyncio.sleep(e.retry_after + 1)
            continue
        except TelegramForbiddenError:
            log.warning(
                "ادمین %s ربات را بلاک/استارت نکرده - اطلاع %s #%s ارسال نشد.",
                admin_id, context_label, ref_id,
            )
            return None
        except TelegramBadRequest:
            log.exception(
                "درخواست نامعتبر هنگام ارسال اطلاع %s #%s به ادمین %s (احتمالاً عکس رسید/file_id نامعتبر است).",
                context_label, ref_id, admin_id,
            )
            return None
        except TelegramNetworkError:
            log.warning(
                "خطای شبکه هنگام ارسال اطلاع %s #%s به ادمین %s؛ تلاش مجدد.",
                context_label, ref_id, admin_id,
            )
            await asyncio.sleep(2)
            continue
        except Exception:
            log.exception(
                "ارسال اطلاع %s #%s به ادمین %s ناموفق بود.",
                context_label, ref_id, admin_id,
            )
            return None
    log.error(
        "ارسال اطلاع %s #%s به ادمین %s پس از تلاش مجدد هم ناموفق بود.",
        context_label, ref_id, admin_id,
    )
    return None


class _MessageCall:
    """Adapter that lets callback-style handlers run from a text message."""

    def __init__(self, from_user, message):
        self.from_user = from_user
        self.message = message
        self.data = ""

    async def answer(self, text=None, *args, **kwargs):
        if text:
            await self.message.answer(text)


def create_user_router(db, is_main_bot: bool = True, bot_manager=None) -> Router:
    # نمایندگی کامل دیتابیس مستقل خودش را دارد و باید تقریباً همان رفتار بات اصلی
    # را داشته باشد. نمایندگی‌های سطح محدود همچنان backend اصلیِ اعتبار را می‌گیرند.
    full_access_bot = db.is_full_access_bot(is_main_bot)
    reseller_backend = db if full_access_bot else Database(DB_PATH)

    # امنیت/هزینه: جلوگیری از اسپم پیام به دستیار هوش مصنوعی. هر بات (اصلی یا
    # نمایندگی) نمونه‌ی مستقل خودش از این دیکشنری را دارد (بسته به closure)،
    # پس رفتار بین بات‌های مختلف قاطی نمی‌شود. فقط حافظه‌ی درون‌پروسه‌ای است -
    # با ری‌استارت پاک می‌شود که برای یک محدودیتِ ثانیه‌ای کاملاً کافی است.
    _ai_last_call_at = {}
    _AI_COOLDOWN_SECONDS = 3.0

    async def _send_receipt_to_admin(bot: Bot, admin_id: int, file_id: str, receipt_type: str, caption: str, reply_markup=None):
        if receipt_type == "document":
            return await bot.send_document(admin_id, file_id, caption=caption, reply_markup=reply_markup)
        return await bot.send_photo(admin_id, file_id, caption=caption, reply_markup=reply_markup)

    def _receipt_payload(message: Message):
        if message.photo:
            return message.photo[-1].file_id, "photo"
        if message.document:
            return message.document.file_id, "document"
        return None, None

    async def _order_payment_method_error(order, method_key: str) -> str:
        """اگر برای این سفارش (به‌خاطر محدودیت روش پرداخت محصول یا حداقل مبلغ
        این درگاه) روش پرداخت انتخاب‌شده مجاز نباشد، متن خطا را برمی‌گرداند؛
        در غیر این صورت None (یعنی مجاز است). این یک لایه‌ی دفاعی اضافه روی
        فیلترشدن دکمه‌ها در payment_choice_kb است."""
        product_id = order["product_id"] if "product_id" in order.keys() else None
        if "is_custom_config" in order.keys() and order["is_custom_config"]:
            if not (await asyncio.to_thread(db.custom_config_allows_payment_method, order["custom_product_id"], method_key)):
                return "⛔️ این روش پرداخت برای ساخت کانفیگ شخصی مجاز نیست."
        elif product_id and not (await asyncio.to_thread(db.product_allows_payment_method, product_id, method_key)):
            return "⛔️ این روش پرداخت برای این محصول مجاز نیست."
        min_amt = await asyncio.to_thread(db.get_payment_method_min_amount, method_key)
        if min_amt and order["final_price"] < min_amt:
            return f"⛔️ حداقل مبلغ قابل پرداخت با این روش {min_amt:,} تومان است."
        return None

    async def _wallet_topup_method_error(amount: int, method_key: str) -> str:
        """معادل _order_payment_method_error برای شارژ کیف پول: اگر این روش
        برای شارژ کیف پول محدود شده باشد یا مبلغ کمتر از حداقل مبلغ این روش
        باشد، متن خطا را برمی‌گرداند؛ در غیر این صورت None."""
        if not (await asyncio.to_thread(db.wallet_topup_allows_payment_method, method_key)):
            return "⛔️ این روش پرداخت برای شارژ کیف پول در حال حاضر مجاز نیست."
        min_amt = await asyncio.to_thread(db.get_payment_method_min_amount, method_key)
        if min_amt and amount < min_amt:
            return f"⛔️ حداقل مبلغ قابل پرداخت با این روش {min_amt:,} تومان است."
        return None

    async def _wallet_topup_cap_line(user_tg_id: int) -> str:
        """اگر سقف موجودی کیف پول فعال باشد، سطر توضیح باقی‌مانده‌ی مجاز شارژ را برمی‌گرداند؛ وگرنه رشته‌ی خالی."""
        max_balance = int((await asyncio.to_thread(db.get_setting, "max_wallet_balance", "0")) or "0")
        if max_balance <= 0:
            return ""
        current_balance = await asyncio.to_thread(db.get_wallet_credit, user_tg_id)
        remaining = max(max_balance - current_balance, 0)
        return f"\nسقف موجودی کیف پول: {max_balance:,} تومان (حداکثر مبلغ قابل شارژ فعلی: {remaining:,} تومان)"

    router = Router()


    @router.message(Command("language"))
    async def language_command(message: Message):
        await message.answer(
            db.get_text("handlers_user.language.choose", "لطفاً زبان موردنظر را انتخاب کنید:"),
            reply_markup=kb.language_kb(db),
        )

    @router.callback_query(F.data.startswith("language:"))
    async def cb_language(call: CallbackQuery, state: FSMContext):
        lang = normalize_language(call.data.split(":", 1)[1])
        if not await asyncio.to_thread(is_language_enabled, db, lang):
            await call.answer(tr("زبان در حال حاضر فعال نیست."), show_alert=True)
            return
        user_id = call.from_user.id
        await asyncio.to_thread(db.set_user_language, user_id, lang)
        # The current update still has the previous ContextVar value; switch it
        # immediately so the confirmation and menu are rendered in the new language.
        catalog = await asyncio.to_thread(db.translation_catalog, lang) if lang not in {"fa", "en"} else None
        token = set_language(lang, catalog)
        try:
            await call.answer(language_label(lang))
            data = await state.get_data()
            if data.get("pending_welcome"):
                # اولین انتخاب زبان بعد از /start: به‌جای پیام تغییر زبان، مستقیم
                # پیام خوش‌آمد و منوی اصلی فرستاده می‌شود.
                await state.update_data(pending_welcome=False)
                welcome = (await asyncio.to_thread(db.get_setting, "welcome_text"))
                reply_enabled = (await asyncio.to_thread(db.get_setting, "main_menu_reply_enabled", "1")) == "1"
                if reply_enabled:
                    await call.message.answer(welcome, reply_markup=kb.menu_for_user(db, user_id, is_main_bot))
                    await _send_inline_main_menu(call.message, user_id)
                else:
                    inline_kb = (await asyncio.to_thread(kb.inline_menu_for_user, db, user_id, is_main_bot))
                    await call.message.answer(
                        welcome,
                        reply_markup=inline_kb if inline_kb is not None else kb.menu_for_user(db, user_id, is_main_bot),
                    )
            else:
                await call.message.answer(
                    db.get_text("handlers_user.language.changed", "زبان با موفقیت تغییر کرد.")
                )
                await call.message.answer(
                    db.get_text("handlers_user.language.choose", "لطفاً زبان موردنظر را انتخاب کنید:"),
                    reply_markup=kb.menu_for_user(db, user_id, is_main_bot),
                )
        finally:
            reset_language(token)

    extra_gateway_user.register_early(router, db, is_main_bot)

    async def _safe_edit(message: Message, text: str, reply_markup=None, parse_mode=None) -> None:
        """ویرایش امن یک پیام (برای منوهای «بازگشت»/«لغو» و مشابه).

        قبلاً همه‌جا مستقیم message.edit_text صدا زده می‌شد؛ اگر تلگرام به هر
        دلیلی (محتوای پیام دقیقاً همان قبلی بود، پیام قبلی عکس/رسید بود که
        متن ندارد، پیام خیلی قدیمی شده و...) خطای TelegramBadRequest برمی‌گرداند،
        کل هندلر کرش می‌کرد و چون بعد از آن call.answer() اجرا نمی‌شد، دکمه از
        دید کاربر هیچ واکنشی نشان نمی‌داد (دقیقاً حس «منو برنمی‌گرده»). این تابع
        چنین خطاهایی را می‌گیرد و در بدترین حالت، به‌جای ویرایش، پیام قدیمی را
        حذف و یک پیام تازه می‌فرستد تا منو همیشه به کاربر برگردد.
        """
        kwargs = {"reply_markup": reply_markup}
        try:
            if parse_mode is not None:
                await message.edit_text(text, parse_mode=parse_mode, **kwargs)
            else:
                await message.edit_text(text, **kwargs)
            return
        except TelegramBadRequest as exc:
            error = str(exc).lower()
            if "message is not modified" in error:
                return
            if parse_mode is not None:
                # شاید خطا مربوط به فرمت Markdown بود؛ یک‌بار بدون آن امتحان کن
                try:
                    await message.edit_text(text, **kwargs)
                    return
                except TelegramBadRequest as exc2:
                    if "message is not modified" in str(exc2).lower():
                        return
        except Exception:
            pass
        # Fallback نهایی: ویرایش به هیچ روشی ممکن نشد؛ پیام قدیمی را حذف
        # (در صورت امکان) و یک پیام تازه با همان محتوا بفرست.
        try:
            await message.delete()
        except Exception:
            pass
        try:
            if parse_mode is not None:
                await message.answer(text, parse_mode=parse_mode, **kwargs)
            else:
                await message.answer(text, **kwargs)
        except TelegramBadRequest:
            await message.answer(text, **kwargs)

    async def _send_inline_main_menu(target, user_tg_id: int):
        """اگر منوی شیشه‌ای بالا از تنظیمات فعال باشد، آن را به‌عنوان یک پیام
        جدا (کنار/بعد از منوی پایین) ارسال می‌کند. target هر شیء‌ای است که
        متد answer async دارد (Message یا call.message)."""
        inline_kb = (await asyncio.to_thread(kb.inline_menu_for_user, db, user_tg_id, is_main_bot))
        if inline_kb is not None:
            await target.answer(db.get_text('handlers_user.auto_f368dac9', '📋 منو:'), reply_markup=inline_kb)

    async def _schedule_card_msg_autodelete(chat_id: int, message_id: int):
        """اگر ادمین از تنظیمات، حذف خودکار پیام‌های شماره کارت را فعال کرده باشد،
        حذف همین پیام (که الان شماره کارت را داخلش داره) را زمان‌بندی می‌کند."""
        seconds = int((await asyncio.to_thread(db.get_setting, "card_msg_autodelete_seconds", "0")) or 0)
        if seconds > 0:
            await schedule_message_autodelete(db, chat_id, message_id, seconds)

    async def _send_card2card_details(target, intro_lines: list, final_price: int):
        """بعد از اینکه کاربر از لیست روش‌های پرداخت گزینه‌ی «کارت‌به‌کارت» را انتخاب کرد،
        شماره کارت را نشان می‌دهد و از او می‌خواهد رسید را ارسال کند. target هر شیء‌ای
        است که متد answer async دارد (معمولاً call.message). مبلغ هم به تومان هم به ریال،
        به‌صورت جدا از عدد ویرگول‌دار، در قالب کد (قابل کپی با یک لمس) نمایش داده می‌شود."""
        card_number = (await asyncio.to_thread(db.get_setting, "card_number"))
        card_holder = (await asyncio.to_thread(db.get_setting, "card_holder"))
        text = "\n".join(intro_lines) + "\n" if intro_lines else ""
        text += f"💳 شماره کارت: `{card_number}`\n"
        text += f"👤 به نام: {escape_md(card_holder)}\n"
        text += f"💰 مبلغ (تومان): `{final_price}` ({final_price:,} تومان)\n"
        text += f"💰 مبلغ (ریال): `{final_price * 10}` ({final_price * 10:,} ریال)\n\n"
        text += "لطفاً عدد بالا رو لمس کن تا کپی بشه، مبلغ رو واریز کن و عکس رسید رو همینجا ارسال کن."
        sent = await target.answer(text, parse_mode="Markdown")
        await _schedule_card_msg_autodelete(sent.chat.id, sent.message_id)

    async def _send_card_auto_details(target, intro_lines: list, kind: str, ref_id: int,
                                       user_id: int, base_amount: int):
        """نسخه‌ی خودکار کارت‌به‌کارت: یک مبلغ یکتا (با چند رقم آخر تصادفی) رزرو
        می‌کند و از کاربر می‌خواهد دقیقاً همان مبلغ را واریز کند؛ به‌محض رسیدن
        پیامک بانک (از اپ BankSmsForwarder) به وب‌هوک سرور، بدون دخالت ادمین
        تایید و تحویل داده می‌شود. مبلغ هم به تومان هم به ریال به‌صورت کد
        (قابل کپی با یک لمس، بدون ویرگول) نمایش داده می‌شود."""
        try:
            invoice = await asyncio.to_thread(
                card_to_card_payment.create_invoice, db, kind, ref_id, user_id, base_amount,
            )
        except card_to_card_payment.CardToCardError as e:
            await target.answer(f"⚠️ {e}")
            return
        timeout_minutes = int((await asyncio.to_thread(
            db.get_setting, "card_to_card_auto_timeout_minutes", "15")) or 15)
        amount_rial = invoice.get("amount_rial") or invoice["amount_toman"] * 10
        text = "\n".join(intro_lines) + "\n" if intro_lines else ""
        text += f"💳 شماره کارت: `{invoice['card_number']}`\n"
        text += f"👤 به نام: {escape_md(invoice['card_holder'] or '')}\n"
        if invoice.get("bank_name"):
            text += f"🏦 بانک: {escape_md(invoice['bank_name'])}\n"
        text += f"\n⚠️ لطفاً دقیقاً یکی از این دو مبلغ رو (بسته به واحد اپ بانکت) واریز کن:\n"
        text += f"💰 تومان: `{invoice['amount_toman']}` ({invoice['amount_toman']:,} تومان)\n"
        text += f"💰 ریال: `{amount_rial}` ({amount_rial:,} ریال)\n\n"
        text += (
            f"✅ به‌محض دریافت پیامک بانک، پرداخت به‌صورت خودکار تایید و تحویل داده "
            f"می‌شود (بدون نیاز به ارسال رسید).\n"
            f"⏳ اعتبار این مبلغ فقط {timeout_minutes} دقیقه است؛ بعد از آن باید دوباره اقدام کنید."
        )
        sent = await target.answer(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_c2c:{invoice['invoice_id']}"),
            ]]),
        )
        await _schedule_card_msg_autodelete(sent.chat.id, sent.message_id)

    async def _start_customgw_payment(target_message, state: FSMContext, phone_state,
                                       gw_row, prompt_prefix: str) -> bool:
        """اگر درگاه سفارشی gw_row به شماره موبایل مشتری نیاز داشته باشد (تنظیم
        require_customer_phone در پنل ادمین)، مرحله‌ی «اشتراک‌گذاری شماره» را
        شروع می‌کند (کیبورد پایین با دکمه‌ی request_contact) و True برمی‌گرداند
        (یعنی: فعلاً فاکتور نساز، منتظر شماره بمان). اگر نیازی نبود False
        برمی‌گرداند (یعنی: همین الان فاکتور بساز). آیدی عددی تلگرام کاربر همیشه
        و خودکار در create_invoice_for پاس داده می‌شود و نیازی به پرسیدن ندارد."""
        if not custom_gateway_payment.gateway_requires_phone(db, gw_row["gateway_key"]):
            return False
        await state.update_data(customgw_gateway_id=gw_row["id"])
        await state.set_state(phone_state)
        await target_message.answer(
            tr(f"{prompt_prefix}\n\n📱 درگاه «{gw_row['name']}» به شماره موبایلت نیاز داره. "
            "با زدن دکمه‌ی زیر شماره‌ات رو به اشتراک بذار:"),
            reply_markup=kb.share_phone_kb(),
        )
        return True

    async def _send_customgw_invoice(target_message, gw_row, kind: str, ref_id: int, tg_id: int,
                                      amount: int, order_name: str, customer_phone: str,
                                      noun: str, verb: str) -> None:
        """فاکتور درگاه سفارشی را می‌سازد و پیام نتیجه را ارسال می‌کند (مشترک بین
        فلوی سفارش/تمدید/شارژ کیف پول). noun/verb برای متن پیام نهایی است، مثلاً
        noun='سفارش' verb='تحویل داده می‌شود'، یا noun='کیف پول' verb='شارژ می‌شود'."""
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await custom_gateway_payment.create_invoice_for(
                db, tenant_id, tg_id, gw_row["gateway_key"], kind, ref_id, amount,
                order_name=order_name, customer_phone=customer_phone,
            )
        except custom_gateway_payment.CustomGatewayPaymentError as e:
            await target_message.answer(f"⚠️ {e}", reply_markup=ReplyKeyboardRemove())
            return
        if not result.get("invoice_url"):
            await target_message.answer(
                f"{tr('💠 فاکتور')} «{gw_row['name']}» {tr('ساخته شد ولی این درگاه لینک پرداخت برنگرداند.')}\n"
                f"پس از انجام پرداخت، {noun} به‌محض تایید درگاه به‌صورت خودکار {verb}.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        await target_message.answer(
            f"{tr('💠 فاکتور پرداخت')} «{gw_row['name']}» {tr('ساخته شد. روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن.')}\n"
            f"به‌محض تایید پرداخت توسط درگاه، {noun} شما به‌صورت خودکار {verb}.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data.startswith("check_c2c:"))
    async def cb_check_card_auto(call: CallbackQuery):
        try:
            invoice_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await call.answer(db.get_text("handlers_user.payment.invalid_data", "داده نامعتبر."), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_card_to_card_invoice, invoice_id))
        if not invoice or invoice["user_id"] != call.from_user.id:
            await call.answer(db.get_text("handlers_user.payment.invoice_not_found", "فاکتور یافت نشد."), show_alert=True)
            return
        await asyncio.to_thread(db.expire_stale_card_to_card_invoices)
        invoice = (await asyncio.to_thread(db.get_card_to_card_invoice, invoice_id))
        if invoice["status"] == "completed":
            await call.answer(db.get_text("handlers_user.payment.already_confirmed", "✅ این پرداخت قبلاً تایید و تحویل داده شده است."), show_alert=True)
        elif invoice["status"] == "manual_review":
            await call.answer(
                db.get_text('handlers_user.auto_4de8d1d5', '⏳ مهلت این مبلغ تمام شده و برای بررسی دستی به ادمین ارسال شد.'), show_alert=True,
            )
        else:
            await call.answer(db.get_text('handlers_user.auto_709cacef', '⏳ هنوز پیامک بانک برای این مبلغ دریافت نشده. کمی صبر کن.'), show_alert=True)

    @router.callback_query(F.data.startswith("svy:"))
    async def cb_order_survey(call: CallbackQuery):
        try:
            _, survey_id, rating = call.data.split(":")
            survey_id, rating = int(survey_id), int(rating)
        except ValueError:
            await call.answer(db.get_text("handlers_user.payment.invalid_data", "داده نامعتبر."), show_alert=True)
            return
        result = await asyncio.to_thread(db.record_survey_rating, survey_id, call.from_user.id, rating)
        if result == "ok":
            await call.answer(db.get_text('handlers_user.auto_549daa0f', '🙏 ممنون از نظرت!'), show_alert=True)
            try:
                await call.message.edit_text(tr(f"🗳 نظر شما ثبت شد: {rating} از ۵ ⭐\nممنون که وقت گذاشتی."))
            except Exception:
                logging.getLogger("handlers_user").debug("ویرایش پیام نظرسنجی ناموفق بود", exc_info=True)
        elif result == "already":
            await call.answer(db.get_text('handlers_user.auto_37687743', 'قبلاً به این نظرسنجی پاسخ داده\u200cای.'), show_alert=True)
        else:
            await call.answer(db.get_text('handlers_user.auto_c1e947e8', 'این نظرسنجی معتبر نیست.'), show_alert=True)

    # -----------------------------------------------------------------------
    # عضویت اجباری در کانال
    # -----------------------------------------------------------------------

    @router.callback_query(F.data == CHECK_CALLBACK)
    async def cb_check_force_join(call: CallbackQuery, bot: Bot):
        settings = (await asyncio.to_thread(db.get_force_join_settings))
        if not settings["enabled"] or not settings["channel"]:
            await call.answer("✅")
            try:
                await call.message.delete()
            except Exception:
                pass
            return
        member = await is_channel_member(bot, settings["channel"], call.from_user.id)
        if member:
            await call.answer(db.get_text('handlers_user.auto_e5b5b280', '✅ عضویت شما تایید شد.'), show_alert=True)
            try:
                await call.message.delete()
            except Exception:
                pass
            welcome = (await asyncio.to_thread(db.get_setting, "welcome_text"))
            await call.message.answer(welcome, reply_markup=kb.menu_for_user(db, call.from_user.id, is_main_bot))
            await _send_inline_main_menu(call.message, call.from_user.id)
        else:
            await call.answer(db.get_text('handlers_user.auto_34eb72c8', '❌ هنوز عضو کانال نشده\u200cاید.'), show_alert=True)

    @router.message(Command("transfer_wallet"))
    async def transfer_wallet_cmd(message: Message):
        if (await asyncio.to_thread(db.get_setting, "wallet_show_transfer", "1")) != "1":
            await message.answer(db.get_text('handlers_user.wallet_transfer_disabled', '⛔️ انتقال موجودی کیف پول در حال حاضر غیرفعال است.'))
            return
        parts=(message.text or "").split()
        if len(parts)!=3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
            await message.answer(db.get_text('handlers_user.auto_ee215b96', 'فرمت: /transfer_wallet USER_ID AMOUNT'))
            return
        receiver=int(parts[1]); amount=int(parts[2])
        ok=await asyncio.to_thread(db.transfer_wallet, message.from_user.id, receiver, amount)
        if ok:
            await _notify_admins_wallet_transfer(message.bot, message.from_user.id, receiver, amount)
        await message.answer("✅ انتقال کیف پول انجام شد." if ok else "⛔️ انتقال ناموفق بود؛ موجودی یا کاربر مقصد را بررسی کنید.")

    @router.message(Command("buy"))
    async def buy_cmd(message: Message, state: FSMContext):
        await show_categories(message, state)

    @router.message(Command("charge"))
    async def charge_cmd(message: Message, state: FSMContext):
        min_topup = int((await asyncio.to_thread(db.get_setting, "min_amount_wallet_topup", "1000")) or "1000")
        cap_line = await _wallet_topup_cap_line(message.from_user.id)
        await state.set_state(WalletTopup.waiting_amount)
        await message.answer(
            tr(f"💰 چه مبلغی (به تومان) می‌خواهید به کیف پول خود شارژ کنید؟ فقط عدد ارسال کنید (مثال: 100000):\n"
            f"حداقل مبلغ شارژ: {min_topup:,} تومان{cap_line}"),
            reply_markup=kb.cancel_kb(),
        )

    @router.message(Command("help"))
    async def help_cmd(message: Message):
        await tutorial_menu_entry(message)

    @router.message(Command("smartsub"))
    async def smartsub_cmd(message: Message):
        if db.get_setting("smart_subscription_enabled","1")!="1":
            await message.answer(db.get_text('handlers_user.auto_cc8afc71', '⛔️ اشتراک هوشمند غیرفعال است.')); return
        rows=await asyncio.to_thread(db.get_user_custom_configs, message.from_user.id) if hasattr(db,"get_user_custom_configs") else []
        urls=[]
        for r in rows or []:
            if r["subscription_url"] and r["status"]=="active": urls.append(r["subscription_url"])
        if len(urls)<2:
            await message.answer(db.get_text('handlers_user.auto_95fbba11', 'ℹ️ برای ساخت اشتراک هوشمند حداقل دو اشتراک فعال لازم است.')); return
        token=await asyncio.to_thread(db.create_smart_subscription,message.from_user.id,urls)
        from config import API_BASE_URL
        base=(db.get_setting("smart_subscription_base_url","") or API_BASE_URL).rstrip("/")
        if not base:
            await message.answer(db.get_text('handlers_user.auto_c76802fa', '⛔️ آدرس عمومی API تنظیم نشده است.')); return
        await message.answer(tr(f"🔗 لینک اشتراک هوشمند شما:\n{base}/sub/smart/{token}"))

    # -----------------------------------------------------------------------
    # شروع
    # -----------------------------------------------------------------------

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext, bot: Bot):
        await state.clear()
        existing_user = await asyncio.to_thread(db.get_user, message.from_user.id)
        (await asyncio.to_thread(db.add_or_update_user,
            message.from_user.id, message.from_user.username or "", message.from_user.first_name or ""
        ))

        # پردازش پارامتر دیپ‌لینک: /start <param>
        # چند بخش با "-" قابل ترکیب هستند، مثلاً: nofj-disc_SUMMER10
        #   ref<id>     زیرمجموعه‌گیری (منطق قبلی، بدون تغییر)
        #   resref_<id> مشتریِ نماینده با «لینک اختصاصی داخل بات اصلی» (بند ۳.۱ اسپک)
        #   disc_CODE   اعمال خودکار کد تخفیف در اولین خرید
        #   test        باز کردن مستقیم فلوی کانفیگ تست
        #   wheel       باز کردن مستقیم گردونه شانس
        #   buy         باز کردن مستقیم منوی خرید (دسته‌بندی‌ها)
        #   nofj        معافیت دائمی این کاربر از عضویت اجباری در کانال
        # هر پیشوند ناشناخته دیگر (مثلاً یک اسم کمپین دلخواه) صرفاً به‌عنوان
        # منبع ورود کاربر (acquisition_source) برای آمار تبلیغات ثبت می‌شود.
        parts = (message.text or "").split(maxsplit=1)
        start_param = parts[1].strip() if len(parts) > 1 else ""
        post_start_actions = []

        # طبق تصمیم صریح: ورود با هر دیپ‌لینکی (نه فقط nofj) یعنی معافیت دائمی
        # از عضویت اجباری برای همین کاربر.
        if start_param:
            (await asyncio.to_thread(db.set_force_join_exempt, message.from_user.id))

        for token in filter(None, start_param.split("-")):
            if token.startswith("resref_"):
                # نماینده با «لینک اختصاصی داخل بات اصلی» (بند ۳.۱ اسپک) —
                # کاملاً مستقل از سیستم زیرمجموعه‌گیری ref<id> زیر.
                owner_part = token[len("resref_"):]
                if owner_part.isdigit() and int(owner_part) != message.from_user.id:
                    (await asyncio.to_thread(db.set_owner_reseller_id, message.from_user.id, int(owner_part)))
            elif token.startswith("ref"):
                ref_part = token[3:]
                if ref_part.isdigit() and int(ref_part) != message.from_user.id:
                    referrer_id = int(ref_part)
                    already_referred = (await asyncio.to_thread(db.get_user, message.from_user.id))
                    already_referred = bool(already_referred and already_referred["referred_by"])
                    if not already_referred:
                        (await asyncio.to_thread(db.set_referred_by, message.from_user.id, referrer_id))
                        reward_info = (await asyncio.to_thread(
                            db.apply_referral_invite_rewards, message.from_user.id, referrer_id
                        ))
                        await _handle_referral_invite_rewards(bot, referrer_id, reward_info)
                        await check_and_notify_referral_fraud(bot.send_message, db, referrer_id, bot_token=bot.token)
            elif token.startswith("disc_"):
                code = token[len("disc_"):]
                code_row = (await asyncio.to_thread(db.get_discount_code, code))
                if (await asyncio.to_thread(db.is_discount_code_valid, code_row, user_id=message.from_user.id)):
                    await state.update_data(
                        pending_discount_code_id=code_row["id"],
                        pending_discount_code_label=code_row["code"],
                    )
                    post_start_actions.append(
                        db.get_text(
                            "handlers_user.start.discount_activated",
                            "🎟 کد تخفیف «{code}» فعال شد؛ در اولین خرید به‌صورت خودکار اعمال می‌شود.",
                        ).format(code=code_row["code"])
                    )
            elif token == "test":
                post_start_actions.append("__open_test__")
            elif token == "wheel":
                post_start_actions.append("__open_wheel__")
            elif token == "buy":
                post_start_actions.append("__open_buy__")
            elif token.startswith("prod_"):
                prod_part = token[len("prod_"):]
                if prod_part.isdigit():
                    post_start_actions.append(f"__open_product__:{int(prod_part)}")
            elif token == "nofj":
                pass  # دیگر نیازی نیست؛ ورود با هر دیپ‌لینکی خودش معافیت می‌دهد (بالاتر انجام شد)
            elif token:
                (await asyncio.to_thread(db.set_acquisition_source, message.from_user.id, token))

        welcome = (await asyncio.to_thread(db.get_setting, "welcome_text"))
        reply_enabled = (await asyncio.to_thread(db.get_setting, "main_menu_reply_enabled", "1")) == "1"
        if not existing_user:
            # کاربر تازه: به‌جای تنظیم خودکار زبان بر اساس لوکیل تلگرام، از او سوال می‌شود.
            # پیام خوش‌آمد/منو بلافاصله بعد از انتخاب زبان (در cb_language) فرستاده می‌شود.
            await state.update_data(pending_welcome=True)
            await message.answer(
                db.get_text("handlers_user.language.choose", "لطفاً زبان موردنظر را انتخاب کنید:"),
                reply_markup=kb.language_kb(db),
            )
        elif reply_enabled:
            # منوی پایین فعال است: طبق روال قبلی، پیام خوش‌آمد با منوی پایین
            # ارسال می‌شود و منوی شیشه‌ای (در صورت فعال بودن) در پیام جدا می‌آید،
            # چون یک پیام نمی‌تواند هم‌زمان هر دو نوع کیبورد را داشته باشد.
            await message.answer(welcome, reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot))
            await _send_inline_main_menu(message, message.from_user.id)
        else:
            # منوی پایین غیرفعال است: اگر منوی شیشه‌ای فعال باشد، دکمه‌ها مستقیم
            # زیر همین پیام خوش‌آمد می‌آیند و پیام جدای «📋 منو:» حذف می‌شود.
            inline_kb = (await asyncio.to_thread(kb.inline_menu_for_user, db, message.from_user.id, is_main_bot))
            await message.answer(
                welcome,
                reply_markup=inline_kb if inline_kb is not None else kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )

        for action in post_start_actions:
            if action == "__open_test__":
                await get_test_config(message)
            elif action == "__open_wheel__":
                await wheel_of_fortune(message, bot)
            elif action == "__open_buy__":
                await show_categories(message, state)
            elif action.startswith("__open_product__:"):
                product_id = int(action.split(":", 1)[1])
                await _open_product_from_deeplink(message, state, product_id)
            else:
                await message.answer(action)

    async def _open_product_from_deeplink(message: Message, state: FSMContext, product_id: int):
        """معادلِ کلیک روی یک محصول از منو، ولی به‌صورت پیام جدید (برای بازکردن
        مستقیم صفحه‌ی یک محصول خاص از طریق دیپ‌لینک ?start=prod_<id>)."""
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product or not product["is_active"]:
            await message.answer(db.get_text(
                "handlers_user.product.not_found_or_inactive", "⛔️ محصول موردنظر یافت نشد یا دیگر فعال نیست."
            ))
            return
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, message.from_user.id))
        if stock <= 0:
            text = _product_confirm_text(product, 1, stock, wallet_credit)
            text += "\n" + db.get_text(
                "handlers_user.product.out_of_stock_suffix", "⛔️ در حال حاضر موجودی این محصول تمام شده است."
            )
            await message.answer(text)
            return
        tier_info = await _tier_info(message.from_user.id, product["price"], 1)
        discount_amount, discount_label = await _apply_pending_discount(
            state, tier_info["total_after"], product_id, user_id=message.from_user.id
        )
        text = _product_confirm_text(product, 1, stock, wallet_credit, discount_amount, discount_label, tier_info)
        await message.answer(text, reply_markup=kb.product_confirm_kb(db, product_id, 1, stock, 10 if tier_info["title"] else 0))

    async def _handle_referral_invite_rewards(bot: Bot, referrer_id: int, reward_info: dict):
        """پیام و تحویل جوایز حالت‌های ۲ و ۳ زیرمجموعه‌گیری (که با صرفِ دعوت، بدون
        نیاز به خرید زیرمجموعه، فعال می‌شوند) را برای دعوت‌کننده انجام می‌دهد."""
        if not reward_info:
            return

        invite_bonus = reward_info.get("invite_bonus")
        if invite_bonus:
            try:
                await bot.send_message(
                    referrer_id,
                    db.get_text(
                        "handlers_user.referral.invite_bonus_credited",
                        "🤝 یک نفر با لینک دعوت شما به بات آمد!\n💰 {amount} تومان به کیف پول شما اضافه شد.",
                    ).format(amount=f"{invite_bonus:,}"),
                )
            except Exception:
                pass

        free_product_id = reward_info.get("free_config_product_id")
        if free_product_id:
            product = (await asyncio.to_thread(db.get_product, free_product_id))
            if not product or not product["is_auto_provision"] or not product["provision_server_id"]:
                try:
                    await bot.send_message(
                        referrer_id,
                        db.get_text(
                            "handlers_user.referral.free_config_manual_contact",
                            "🎁 شما با تعداد دعوت‌های خود، یک کانفیگ رایگان برنده شدید! "
                            "برای دریافت آن با پشتیبانی تماس بگیرید.",
                        ),
                    )
                except Exception:
                    pass
                return
            try:
                prov_results = await provision_direct(db, product, 1, user_id=referrer_id)
            except (ProvisionError, DirectProvisionError):
                try:
                    await bot.send_message(
                        referrer_id,
                        db.get_text(
                            "handlers_user.referral.free_config_provision_failed",
                            "🎁 شما با تعداد دعوت‌های خود، یک کانفیگ رایگان برنده شدید؛ اما در ساخت "
                            "خودکار آن مشکلی پیش آمد. لطفاً با پشتیبانی تماس بگیرید.",
                        ),
                    )
                except Exception:
                    pass
                return
            try:
                links_text = "\n".join(f"🔗 {r['subscription_url']}" for r in prov_results)
                await bot.send_message(
                    referrer_id,
                    db.get_text(
                        "handlers_user.referral.free_config_delivered",
                        "🎉 تبریک! با دعوت موفق دوستانتان، محصول «{product_name}» به‌صورت رایگان برای شما "
                        "ساخته شد:\n\n{links}",
                    ).format(product_name=product["name"], links=links_text),
                )
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # مینی‌اپ (دکمه‌ی متنی -> پیام با دکمه‌ی inline واقعی وب‌اپ)
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t in (kb.MINIAPP_BTN_TEXT, tr(kb.MINIAPP_BTN_TEXT, "en"))))
    async def open_miniapp(message: Message):
        miniapp_url = kb._miniapp_url(db, db.get_user_language(message.from_user.id))
        if not miniapp_url:
            return
        await message.answer(
            db.get_text("handlers_user.miniapp.open_prompt", "برای ورود به مینی‌اپ فروشگاه، روی دکمه‌ی زیر بزن:"),
            reply_markup=kb.miniapp_inline_kb(miniapp_url),
        )

    # -----------------------------------------------------------------------
    # خرید کانفیگ
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_buy"), tr(db.get_setting("btn_buy")))))
    async def show_categories(message: Message, state: FSMContext):
        await state.clear()
        categories = (await asyncio.to_thread(db.get_categories, active_only=True))
        custom_enabled = full_access_bot and (
            (await asyncio.to_thread(db.get_setting, "custom_config_enabled", "0")) == "1"
            or (await asyncio.to_thread(db.count_active_custom_config_products)) > 0
        )
        if not categories and not custom_enabled:
            await message.answer(db.get_text("handlers_user.category.none_active", "در حال حاضر دسته‌بندی فعالی وجود ندارد."))
            return
        await message.answer(
            db.get_text("handlers_user.category.choose_option", "یک گزینه را انتخاب کنید:"),
            reply_markup=kb.categories_kb(db, categories, full_access_bot),
        )

    @router.callback_query(F.data == "custom_config_start")
    async def cb_custom_config_start(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if not full_access_bot:
            return
        try:
            await call.message.delete()
        except Exception:
            pass
        await custom_config_start(call.message, state)

    @router.callback_query(F.data == "back_main")
    async def cb_back_main(call: CallbackQuery, state: FSMContext):
        await state.clear()
        try:
            await call.message.delete()
        except Exception:
            # پیام قدیمی‌تر از ۴۸ ساعت یا از قبل حذف‌شده باشد، تلگرام حذف را رد
            # می‌کند؛ در این حالت به‌جای کرش، فقط دکمه‌ها را از زیر پیام برمی‌داریم.
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await call.answer()

    @router.callback_query(F.data == "back_categories")
    async def cb_back_categories(call: CallbackQuery):
        categories = (await asyncio.to_thread(db.get_categories, active_only=True))
        await _safe_edit(
            call.message,
            db.get_text("handlers_user.category.choose_category", "یک دسته‌بندی را انتخاب کنید:"),
            reply_markup=kb.categories_kb(db, categories, is_main_bot),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("cat:"))
    async def cb_category(call: CallbackQuery):
        cat_id = int(call.data.split(":")[1])
        products = (await asyncio.to_thread(db.get_products, cat_id, active_only=True))
        if not products:
            await call.answer(
                db.get_text("handlers_user.category.empty", "محصولی در این دسته‌بندی موجود نیست."), show_alert=True
            )
            return
        await _safe_edit(
            call.message,
            db.get_text("handlers_user.category.choose_product", "یک محصول را انتخاب کنید:"),
            reply_markup=kb.products_kb(db, products, cat_id),
        )
        await call.answer()

    async def _tier_info(user_id: int, unit_price: int, quantity: int) -> dict:
        return await asyncio.to_thread(db.get_tier_price_info, user_id, unit_price, quantity)

    async def _users_option(product) -> int:
        return await asyncio.to_thread(ul.selectable_max_users, db, product)

    def _chosen_users(data: dict, product) -> int:
        if data.get("buy_users_pid") != product["id"]:
            return 0
        return int(data.get("buy_users") or 0)

    def _product_confirm_text(product, quantity: int, stock: int, wallet_credit: int, discount_amount: int = 0, discount_label: str = "", tier_info: dict = None, users: int = 0, included_users: int = 0) -> str:
        unit_price = ul.price_for_users(product, users)
        stock_line = (
            db.get_text(
                "handlers_user.product.stock_line_auto",
                "⚡️ این محصول خودکار و لحظه‌ای ساخته می‌شود (محدودیت موجودی ندارد)\n",
            ) if product["is_auto_provision"] else
            db.get_text("handlers_user.product.stock_line_count", "📊 موجودی: {stock} عدد\n").format(stock=stock)
        )
        text = db.get_text(
            "handlers_user.product.confirm_header",
            "📦 {name}\n💰 قیمت واحد: {price} تومان\n📝 توضیحات: {description}\n",
        ).format(name=product["name"], price=f"{unit_price:,}", description=product["description"] or "---")
        text += stock_line
        if product["is_auto_provision"] and (product["auto_provision_volume_gb"] or product["duration_days"]):
            volume_gb = product["auto_provision_volume_gb"]
            duration_days = product["duration_days"]
            spec_parts = []
            if volume_gb:
                spec_parts.append(db.get_text("handlers_user.product.spec_volume", "📦 حجم: {volume} گیگ").format(volume=volume_gb))
            if duration_days:
                spec_parts.append(db.get_text("handlers_user.product.spec_duration", "⏳ مدت: {duration} روز").format(duration=duration_days))
            text += " | ".join(spec_parts) + "\n"
        if users or included_users:
            text += db.get_text("handlers_user.product.users_line", "👥 تعداد کاربر همزمان: {users}\n").format(users=users or included_users)
        total_price = unit_price * quantity
        if quantity > 1:
            text += db.get_text(
                "handlers_user.product.quantity_total_line",
                "\n🔢 تعداد انتخابی: {quantity} عدد\n💵 جمع کل: {total} تومان\n",
            ).format(quantity=quantity, total=f"{total_price:,}")
        if tier_info and tier_info["amount"] > 0:
            text += db.get_text(
                "handlers_user.product.tier_discount_line",
                "\n{icon} تخفیف سطح {title} ({percent}٪): -{amount} تومان\n",
            ).format(icon=tier_info["icon"], title=tier_info["title"], percent=tier_info["percent"], amount=f"{tier_info['amount']:,}")
            text += db.get_text(
                "handlers_user.product.tier_total_after_line", "💵 مبلغ پس از تخفیف سطح: {total} تومان\n"
            ).format(total=f"{tier_info['total_after']:,}")
            total_price = tier_info["total_after"]
        if discount_amount > 0:
            text += db.get_text(
                "handlers_user.product.discount_code_line",
                "\n🎟 کد تخفیف «{label}» به‌صورت خودکار اعمال شد: -{amount} تومان\n",
            ).format(label=discount_label, amount=f"{discount_amount:,}")
            text += db.get_text(
                "handlers_user.product.discount_total_after_line", "💵 مبلغ پس از تخفیف: {total} تومان\n"
            ).format(total=f"{total_price - discount_amount:,}")
        if wallet_credit > 0:
            text += db.get_text(
                "handlers_user.product.wallet_credit_line",
                "\n👛 موجودی کیف پول شما: {amount} تومان (به‌صورت خودکار در پرداخت اعمال می‌شود)\n",
            ).format(amount=f"{wallet_credit:,}")
        elif wallet_credit < 0:
            text += db.get_text(
                "handlers_user.product.wallet_debt_line", "\n📉 بدهی فعلی کیف پول شما: {amount} تومان\n"
            ).format(amount=f"{-wallet_credit:,}")
        return text

    async def _apply_pending_discount(state: FSMContext, total_price: int, product_id: int = None, user_id: int = None):
        """اگر از دیپ‌لینک کد تخفیف پندینگ داریم و هنوز روی این خرید اعمال نشده،
        همین‌جا اعمالش می‌کند و مبلغ تخفیف/برچسب را برمی‌گرداند. اگر کد به این
        محصول/مبلغ نخورد (مثلاً مخصوص محصول دیگری یا زیر حداقل خرید است)، ساکت
        نادیده گرفته می‌شود (کاربر می‌تواند دستی هم امتحان کند)."""
        data = await state.get_data()
        pending_id = data.get("pending_discount_code_id")
        if not pending_id:
            return data.get("discount_amount", 0) or 0, ""
        code_row = (await asyncio.to_thread(db.get_discount_code_by_id, pending_id))
        if not (await asyncio.to_thread(db.is_discount_code_valid, code_row, total_price, product_id, user_id=user_id)):
            await state.update_data(pending_discount_code_id=None, pending_discount_code_label=None)
            return 0, ""
        discount_amount = (await asyncio.to_thread(db.compute_discount_amount, code_row, total_price))
        await state.update_data(discount_code_id=code_row["id"], discount_amount=discount_amount)
        return discount_amount, code_row["code"]

    @router.callback_query(F.data.startswith("prod:"))
    async def cb_product(call: CallbackQuery, state: FSMContext):
        product_id = int(call.data.split(":")[1])
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product:
            await call.answer(db.get_text("handlers_user.product.not_found_short", "محصول یافت نشد."), show_alert=True)
            return
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, call.from_user.id))
        if stock <= 0:
            text = _product_confirm_text(product, 1, stock, wallet_credit)
            text += "\n⛔️ در حال حاضر موجودی این محصول تمام شده است."
            await _safe_edit(call.message, text)
            await call.answer()
            return
        max_users = await _users_option(product)
        await state.update_data(buy_users_pid=None, buy_users=None)
        if max_users:
            await _show_users_picker(call, product, max_users)
            await call.answer()
            return
        await _show_product_confirm(call, state, product, 1, stock)
        await call.answer()

    async def _show_users_picker(call: CallbackQuery, product, max_users: int):
        text = (
            f"📦 {product['name']}\n"
            f"📝 توضیحات: {product['description'] or '---'}\n\n"
            "👥 تعداد کاربر همزمان را انتخاب کنید (قیمت پایه شامل ۱ کاربر است):"
        )
        await _safe_edit(
            call.message, text,
            reply_markup=kb.user_count_picker_kb(product, max_users, f"buy_users:{product['id']}", "back_categories"),
        )

    async def _show_product_confirm(call: CallbackQuery, state: FSMContext, product, quantity: int, stock: int):
        data = await state.get_data()
        users = _chosen_users(data, product)
        included = 0 if users else await asyncio.to_thread(ul.included_users, db, product)
        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, call.from_user.id))
        tier_info = await _tier_info(call.from_user.id, ul.price_for_users(product, users), quantity)
        discount_amount, discount_label = await _apply_pending_discount(
            state, tier_info["total_after"], product["id"], user_id=call.from_user.id
        )
        text = _product_confirm_text(product, quantity, stock, wallet_credit, discount_amount, discount_label, tier_info, users, included)
        await _safe_edit(call.message, text, reply_markup=kb.product_confirm_kb(
            db, product["id"], quantity, stock, 10 if tier_info["title"] else 0, users_change=bool(users),
        ))

    @router.callback_query(F.data.startswith("buy_users_pick:"))
    async def cb_buy_users_pick(call: CallbackQuery, state: FSMContext):
        product = (await asyncio.to_thread(db.get_product, int(call.data.split(":")[1])))
        max_users = (await _users_option(product)) if product else 0
        if not max_users:
            await call.answer(db.get_text('handlers_user.auto_f4122f85', 'این گزینه در دسترس نیست.'), show_alert=True)
            return
        await _show_users_picker(call, product, max_users)
        await call.answer()

    @router.callback_query(F.data.startswith("buy_users:"))
    async def cb_buy_users(call: CallbackQuery, state: FSMContext):
        try:
            _, product_id_s, users_s = call.data.split(":")
            product_id, users = int(product_id_s), int(users_s)
        except ValueError:
            await call.answer(db.get_text('handlers_user.auto_ec3a51ff', 'درخواست نامعتبر است.'), show_alert=True)
            return
        product = (await asyncio.to_thread(db.get_product, product_id))
        max_users = (await _users_option(product)) if product else 0
        if not max_users or not 1 <= users <= max_users:
            await call.answer(db.get_text('handlers_user.auto_f4122f85', 'این گزینه در دسترس نیست.'), show_alert=True)
            return
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        if stock <= 0:
            await call.answer(db.get_text("handlers_user.product.currently_unavailable", "این محصول در حال حاضر موجود نیست."), show_alert=True)
            return
        await state.update_data(buy_users_pid=product_id, buy_users=users)
        await _show_product_confirm(call, state, product, 1, stock)
        await call.answer()

    async def _cb_qty_change(call: CallbackQuery, state: FSMContext, delta: int):
        parts = call.data.split(":")
        product_id, quantity = int(parts[1]), int(parts[2])
        step = int(parts[3]) if len(parts) > 3 else 1
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product:
            await call.answer(db.get_text("handlers_user.product.not_found_short", "محصول یافت نشد."), show_alert=True)
            return
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        if stock <= 0:
            await call.answer(db.get_text("handlers_user.product.currently_unavailable", "این محصول در حال حاضر موجود نیست."), show_alert=True)
            return
        quantity = max(1, min(quantity + delta * step, stock))
        await _show_product_confirm(call, state, product, quantity, stock)
        await call.answer()

    @router.callback_query(F.data.startswith("qty_inc:"))
    async def cb_qty_inc(call: CallbackQuery, state: FSMContext):
        await _cb_qty_change(call, state, 1)

    @router.callback_query(F.data.startswith("qty_dec:"))
    async def cb_qty_dec(call: CallbackQuery, state: FSMContext):
        await _cb_qty_change(call, state, -1)

    @router.callback_query(F.data == "noop")
    async def cb_noop(call: CallbackQuery):
        await call.answer()

    @router.callback_query(F.data.startswith("enter_code:"))
    async def cb_enter_code(call: CallbackQuery, state: FSMContext):
        _, product_id, quantity = call.data.split(":")
        await state.update_data(discount_product_id=int(product_id), discount_quantity=int(quantity))
        await state.set_state(DiscountEntry.waiting_code)
        await _safe_edit(call.message, db.get_text('handlers_user.auto_506f789e', '🎟 کد تخفیف را ارسال کنید:'), reply_markup=kb.cancel_kb())
        await call.answer()

    @router.message(DiscountEntry.waiting_code)
    async def process_discount_code(message: Message, state: FSMContext):
        data = await state.get_data()
        product_id = data.get("discount_product_id")
        quantity = data.get("discount_quantity", 1)
        product = (await asyncio.to_thread(db.get_product, product_id)) if product_id else None
        if not product:
            await message.answer(db.get_text('handlers_user.auto_dd59b9be', 'محصول معتبر نیست. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return

        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        quantity = max(1, min(quantity, stock)) if stock > 0 else quantity

        users = _chosen_users(data, product)
        tier_info = await _tier_info(message.from_user.id, ul.price_for_users(product, users), quantity)
        total_price = tier_info["total_after"]
        code_row = (await asyncio.to_thread(db.get_discount_code, message.text.strip()))
        invalid_reason = (await asyncio.to_thread(
            db.get_discount_invalid_reason, code_row, total_price, product_id, user_id=message.from_user.id
        ))
        if invalid_reason:
            await message.answer(
                tr(f"❌ {invalid_reason}\nدوباره تلاش کنید یا بدون کد ادامه دهید."),
                reply_markup=kb.cancel_kb(),
            )
            return
        discount_amount = (await asyncio.to_thread(db.compute_discount_amount, code_row, total_price))
        # کد وارد شده دستی جایگزین کد پندینگِ احتمالی دیپ‌لینک می‌شود
        await state.update_data(
            discount_code_id=code_row["id"], discount_amount=discount_amount,
            pending_discount_code_id=None, pending_discount_code_label=None,
        )
        await state.set_state(None)

        price_after_code = total_price - discount_amount
        wallet_used_preview = (await asyncio.to_thread(db.plan_wallet_spend, message.from_user.id, price_after_code))["wallet_used"]
        final_preview = price_after_code - wallet_used_preview

        text = (
            f"✅ کد تخفیف اعمال شد!\n\n"
            f"📦 {product['name']}\n"
            f"🔢 تعداد: {quantity} عدد\n"
            f"💰 قیمت کل: {tier_info['total']:,} تومان\n"
        )
        if tier_info["amount"] > 0:
            text += f"{tier_info['icon']} تخفیف سطح {tier_info['title']}: {tier_info['amount']:,} تومان\n"
        text += f"🎟 تخفیف کد: {discount_amount:,} تومان\n"
        if wallet_used_preview > 0:
            text += f"👛 اعمال کیف پول: {wallet_used_preview:,} تومان\n"
        text += f"💵 مبلغ نهایی قابل پرداخت: {final_preview:,} تومان\n"
        text += f"📊 موجودی: {stock} عدد"

        await message.answer(text, reply_markup=kb.product_confirm_kb(
            db, product_id, quantity, max(stock, quantity), 10 if tier_info["title"] else 0, users_change=bool(users),
        ))

    async def _report_order_to_group(bot: Bot, order_id: int, caption: str, reply_markup, receipt_file_id: str = None, receipt_type: str = "photo") -> bool:
        if receipt_file_id:
            sent = await report_router.send_media(bot, db, "purchase", receipt_file_id, receipt_type, caption, reply_markup)
        else:
            sent = await report_router.send_text(bot, db, "purchase", caption, reply_markup)
        if not sent:
            return False
        await asyncio.to_thread(db.set_order_admin_message, order_id, sent.chat.id, sent.message_id)
        return True

    async def _report_topup_to_group(bot: Bot, topup_id: int, file_id: str, receipt_type: str, caption: str, reply_markup) -> bool:
        sent = await report_router.send_media(bot, db, "finance", file_id, receipt_type, caption, reply_markup)
        if not sent:
            return False
        await asyncio.to_thread(db.set_topup_admin_message, topup_id, sent.chat.id, sent.message_id)
        return True

    def _user_purchase_info_line(user_row) -> str:
        """خط شماره تلفن و موجودی کیف پول کاربر، برای نمایش به مدیر هنگام سفارش."""
        if not user_row:
            return ""
        phone = user_row["phone_number"] or "ثبت نشده"
        balance = int(user_row["referral_credit"] or 0)
        return f"📱 شماره: {phone}\n👛 موجودی کیف پول: {balance:,} تومان\n"

    async def _admin_card_hint_line() -> str:
        """قابلیت ۸۵: وقتی سفارش با رسید کارت‌به‌کارت به مدیر گزارش می‌شود، شماره
        کارتی که به خریدار نشان داده شده هم اضافه می‌شود - چون شماره کارت ممکن
        است بین زمان خرید و زمان بررسی مدیر عوض شده باشد و مدیر برای تطبیق با
        صورتحساب بانکی باید دقیقاً بداند پول به کدام کارت واریز شده."""
        card_number = (await asyncio.to_thread(db.get_setting, "card_number"))
        if not card_number:
            return ""
        card_holder = (await asyncio.to_thread(db.get_setting, "card_holder")) or ""
        holder_line = f"👤 به نام: {escape_html(card_holder)}\n" if card_holder else ""
        return f"💳 شماره کارت واریزی: `{card_number}`\n{holder_line}"

    async def _notify_admins_of_order(bot: Bot, order_id: int, receipt_file_id: str = None, receipt_type: str = "photo"):
        order = (await asyncio.to_thread(db.get_order, order_id))

        if order["is_custom_config"]:
            user_row = (await asyncio.to_thread(db.get_user, order["user_id"]))
            username = user_row["username"] if user_row else ""
            first_name = user_row["first_name"] if user_row else ""
            caption = (
                f"🧾 سفارش کانفیگ شخصی #{order_id}\n"
                f"👤 کاربر: {escape_html(first_name)} (@{escape_html(username) or '---'})\n"
                f"🆔 آیدی عددی: {order['user_id']}\n"
                f"{_user_purchase_info_line(user_row)}"
                f"🛠 نام کاربری: {order['custom_username']}\n"
                f"📶 حجم: {order['custom_volume_gb']} گیگابایت\n"
                f"💰 قیمت پایه: {order['base_price']:,} تومان\n"
            )
            if order["wallet_used"]:
                caption += f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان\n"
            caption += f"💵 مبلغ قابل پرداخت: {order['final_price']:,} تومان"
            already_approved = order["status"] != "pending"
            reply_markup = None if already_approved else kb.order_review_kb(order_id)
            if already_approved:
                caption += "\n\n✅ این سفارش به‌طور خودکار تایید و کانفیگ ساخته شد (پرداخت کامل از کیف پول)."
            if not receipt_file_id and not already_approved:
                caption += "\n\n(بدون نیاز به رسید - مبلغ کاملاً از کیف پول پوشش داده شده)"
            elif receipt_file_id and not already_approved:
                caption += "\n\n" + (await _admin_card_hint_line())
            if await _report_order_to_group(bot, order_id, caption, reply_markup, receipt_file_id, receipt_type):
                return
            for admin_id in (await asyncio.to_thread(db.list_admins)):
                if receipt_file_id:
                    factory = lambda aid=admin_id: _send_receipt_to_admin(
                        bot, aid, receipt_file_id, receipt_type, caption, reply_markup
                    )
                else:
                    factory = lambda aid=admin_id: bot.send_message(
                        aid, caption, reply_markup=reply_markup,
                    )
                sent = await _send_admin_notification(bot, admin_id, factory, "سفارش کانفیگ شخصی", order_id)
                if sent:
                    (await asyncio.to_thread(db.set_order_admin_message, order_id, admin_id, sent.message_id))
            return

        if order["is_renewal"]:
            # سفارش «تمدید سرویس» از حساب کاربری - product_id این سفارش سنتینل ۰
            # است (نه یک محصول واقعی)، پس caption از فیلدهای renewal_* خود سفارش
            # ساخته می‌شود، نه از جدول products.
            user_row = (await asyncio.to_thread(db.get_user, order["user_id"]))
            username = user_row["username"] if user_row else ""
            first_name = user_row["first_name"] if user_row else ""
            mode_label = _RENEW_MODE_LABEL.get(order["renewal_mode"], order["renewal_mode"] or "")
            target_label = "کانفیگ شخصی" if order["renewal_target_kind"] == "custom" else "کانفیگ بانک (استخر)"
            caption = (
                f"🧾 سفارش تمدید سرویس #{order_id}\n"
                f"👤 کاربر: {escape_html(first_name)} (@{escape_html(username) or '---'})\n"
                f"🆔 آیدی عددی: {order['user_id']}\n"
                f"{_user_purchase_info_line(user_row)}"
                f"🔄 نوع: {mode_label}\n"
                f"🎯 هدف: {target_label} #{order['renewal_target_id']}\n"
            )
            if order["renewal_add_volume_gb"]:
                caption += f"🔋 افزایش حجم: {order['renewal_add_volume_gb']} گیگابایت\n"
            if order["renewal_add_days"]:
                caption += f"⏱ افزایش زمان: {order['renewal_add_days']} روز\n"
            if order["renewal_user_limit"]:
                caption += f"👥 تعداد کاربر همزمان: {order['renewal_user_limit']}\n"
            caption += f"💰 قیمت پایه: {order['base_price']:,} تومان\n"
            if order["wallet_used"]:
                caption += f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان\n"
            caption += f"💵 مبلغ قابل پرداخت: {order['final_price']:,} تومان"
            already_approved = order["status"] != "pending"
            reply_markup = None if already_approved else kb.order_review_kb(order_id)
            if already_approved:
                caption += "\n\n✅ این سفارش به‌طور خودکار تایید و سرویس تمدید شد (پرداخت کامل از کیف پول)."
            if not receipt_file_id and not already_approved:
                caption += "\n\n(بدون نیاز به رسید - مبلغ کاملاً از کیف پول پوشش داده شده)"
            elif receipt_file_id and not already_approved:
                caption += "\n\n" + (await _admin_card_hint_line())
            if await _report_order_to_group(bot, order_id, caption, reply_markup, receipt_file_id, receipt_type):
                return
            for admin_id in (await asyncio.to_thread(db.list_admins)):
                if receipt_file_id:
                    factory = lambda aid=admin_id: _send_receipt_to_admin(
                        bot, aid, receipt_file_id, receipt_type, caption, reply_markup
                    )
                else:
                    factory = lambda aid=admin_id: bot.send_message(
                        aid, caption, reply_markup=reply_markup,
                    )
                sent = await _send_admin_notification(bot, admin_id, factory, "سفارش تمدید سرویس", order_id)
                if sent:
                    (await asyncio.to_thread(db.set_order_admin_message, order_id, admin_id, sent.message_id))
            return

        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        user_row = (await asyncio.to_thread(db.get_user, order["user_id"]))
        username = user_row["username"] if user_row else ""
        first_name = user_row["first_name"] if user_row else ""

        quantity = order["quantity"] or 1
        caption = (
            f"🧾 سفارش #{order_id}\n"
            f"👤 کاربر: {escape_html(first_name)} (@{escape_html(username) or '---'})\n"
            f"🆔 آیدی عددی: {order['user_id']}\n"
            f"{_user_purchase_info_line(user_row)}"
            f"📦 محصول: {product['name']}"
            + (f" × {quantity}\n" if quantity > 1 else "\n")
            + f"💰 قیمت پایه: {order['base_price']:,} تومان\n"
        )
        if order["user_limit"]:
            caption += f"👥 تعداد کاربر همزمان: {order['user_limit']}\n"
        if order["discount_amount"]:
            caption += f"🎟 تخفیف کد: {order['discount_amount']:,} تومان\n"
        if order["wallet_used"]:
            caption += f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان\n"
        caption += f"💵 مبلغ قابل پرداخت: {order['final_price']:,} تومان"

        # اگر سفارش از قبل به‌صورت خودکار تایید شده (کاملاً از کیف پول/کد تخفیف پوشش داده شده بود)،
        # این پیام فقط جهت اطلاع ادمین است و نیازی به دکمه تایید/رد ندارد.
        already_approved = order["status"] != "pending"
        reply_markup = None if already_approved else kb.order_review_kb(order_id)
        if already_approved:
            caption += "\n\n✅ این سفارش به‌طور خودکار تایید و کانفیگ برای کاربر ارسال شد (پرداخت کامل از کیف پول/کد تخفیف)."

        if not receipt_file_id and not already_approved:
            caption += "\n\n(بدون نیاز به رسید - مبلغ کاملاً از کیف پول/تخفیف پوشش داده شده)"
        elif receipt_file_id and not already_approved:
            caption += "\n\n" + (await _admin_card_hint_line())

        if await _report_order_to_group(bot, order_id, caption, reply_markup, receipt_file_id, receipt_type):
            return
        for admin_id in (await asyncio.to_thread(db.list_admins)):
            if receipt_file_id:
                factory = lambda aid=admin_id: _send_receipt_to_admin(
                    bot, aid, receipt_file_id, receipt_type, caption, reply_markup
                )
            else:
                factory = lambda aid=admin_id: bot.send_message(
                    aid, caption, reply_markup=reply_markup,
                )
            sent = await _send_admin_notification(bot, admin_id, factory, "سفارش", order_id)
            if sent:
                (await asyncio.to_thread(db.set_order_admin_message, order_id, admin_id, sent.message_id))

    async def _notify_admins_wallet_transfer(bot: Bot, sender_id: int, receiver_id: int, amount: int):
        """گزارش به ادمین‌ها هنگام انتقال موجودی کیف پول بین دو کاربر (رصد تراکنش‌های مشکوک)؛
        اگر گروه گزارش تنظیم باشد به تاپیک «مالی» می‌رود، وگرنه پیام خصوصی به همه‌ی ادمین‌ها."""
        sender_row = (await asyncio.to_thread(db.get_user, sender_id))
        receiver_row = (await asyncio.to_thread(db.get_user, receiver_id))
        sender_label = f"{sender_row['first_name'] or ''} (@{sender_row['username'] or '---'}) [{sender_id}]" if sender_row else str(sender_id)
        receiver_label = f"{receiver_row['first_name'] or ''} (@{receiver_row['username'] or '---'}) [{receiver_id}]" if receiver_row else str(receiver_id)
        sender_balance = (await asyncio.to_thread(db.get_wallet_credit, sender_id))
        receiver_balance = (await asyncio.to_thread(db.get_wallet_credit, receiver_id))
        text = (
            f"💸 انتقال موجودی کیف پول\n"
            f"از: {sender_label}\n"
            f"به: {receiver_label}\n"
            f"مبلغ: {amount:,} تومان\n"
            f"موجودی فعلی فرستنده: {sender_balance:,} تومان\n"
            f"موجودی فعلی گیرنده: {receiver_balance:,} تومان"
        )
        await report_router.report(bot, db, "finance", text)

    async def _notify_admins_service_transfer(bot: Bot, cc: dict, sender_id: int, receiver_id: int):
        """گزارش به ادمین‌ها هنگام انتقال مالکیت یک سرویس/کانفیگ بین دو کاربر."""
        sender_row = (await asyncio.to_thread(db.get_user, sender_id))
        receiver_row = (await asyncio.to_thread(db.get_user, receiver_id))
        sender_label = f"{sender_row['first_name'] or ''} (@{sender_row['username'] or '---'}) [{sender_id}]" if sender_row else str(sender_id)
        receiver_label = f"{receiver_row['first_name'] or ''} (@{receiver_row['username'] or '---'}) [{receiver_id}]" if receiver_row else str(receiver_id)
        text = (
            f"👤 انتقال سرویس\n"
            f"سرویس: {cc.get('display_name') or cc.get('username')}\n"
            f"از: {sender_label}\n"
            f"به: {receiver_label}"
        )
        await report_router.report(bot, db, "service", text)

    extra_gateway_user.register(
        router, db, is_main_bot, _order_payment_method_error, _wallet_topup_method_error, _notify_admins_of_order,
    )

    @router.callback_query(F.data.startswith("check_aban:"))
    async def cb_check_abangateway(call: CallbackQuery, bot: Bot):
        try:
            invoice_db_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await call.answer(db.get_text("handlers_user.payment.invalid_data", "داده نامعتبر."), show_alert=True)
            return
        invoice_row = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_db_id))
        if not invoice_row or invoice_row["user_id"] != call.from_user.id:
            await call.answer(db.get_text("handlers_user.payment.invoice_not_found", "فاکتور یافت نشد."), show_alert=True)
            return

        await call.answer(db.get_text("handlers_user.payment.checking_status", "در حال بررسی وضعیت پرداخت..."))
        result = await abangateway_payment.try_verify_and_finalize(db, invoice_row)

        if result == "not_paid_yet":
            await call.message.answer(db.get_text("handlers_user.payment.not_confirmed_yet", "⏳ هنوز واریزی برای این فاکتور تایید نشده. کمی صبر کن و دوباره بررسی کن."))
            return
        if result in ("expired", "cancelled"):
            await call.message.answer(db.get_text("handlers_user.payment.invoice_expired_cancelled", "❌ اعتبار این فاکتور تمام شده یا لغو شده. لطفاً دوباره از منو اقدام کن."))
            return
        if result == "already_delivered":
            await call.message.answer(db.get_text("handlers_user.payment.already_confirmed", "✅ این پرداخت قبلاً تایید و تحویل داده شده است."))
            return
        if result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))
            return

        # result == "verified_now"
        if invoice_row["kind"] == "wallet_topup":
            text = await abangateway_payment.finalize_paid_topup(db, invoice_row["ref_id"])
        else:
            text = await abangateway_payment.finalize_paid_order(
                db, bot, invoice_row["ref_id"], notify_admins_fn=_notify_admins_of_order
            )
        await call.message.answer(text)

    @router.callback_query(F.data.startswith("check_blupal:"))
    async def cb_check_blupal(call: CallbackQuery, bot: Bot):
        try:
            invoice_db_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await call.answer(db.get_text("handlers_user.payment.invalid_data", "داده نامعتبر."), show_alert=True)
            return
        invoice_row = (await asyncio.to_thread(db.get_blupal_invoice, invoice_db_id))
        if not invoice_row or invoice_row["user_id"] != call.from_user.id:
            await call.answer(db.get_text("handlers_user.payment.invoice_not_found", "فاکتور یافت نشد."), show_alert=True)
            return

        await call.answer(db.get_text("handlers_user.payment.checking_status", "در حال بررسی وضعیت پرداخت..."))
        result = await blupal_payment.try_verify_and_finalize(db, invoice_row)

        if result == "not_paid_yet":
            await call.message.answer(db.get_text("handlers_user.payment.not_confirmed_yet", "⏳ هنوز واریزی برای این فاکتور تایید نشده. کمی صبر کن و دوباره بررسی کن."))
            return
        if result in ("expired", "cancelled"):
            await call.message.answer(db.get_text("handlers_user.payment.invoice_expired_cancelled", "❌ اعتبار این فاکتور تمام شده یا لغو شده. لطفاً دوباره از منو اقدام کن."))
            return
        if result == "already_delivered":
            await call.message.answer(db.get_text("handlers_user.payment.already_confirmed", "✅ این پرداخت قبلاً تایید و تحویل داده شده است."))
            return
        if result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))
            return

        # result == "verified_now"
        if invoice_row["kind"] == "wallet_topup":
            text = await blupal_payment.finalize_paid_topup(db, invoice_row["ref_id"])
        else:
            text = await blupal_payment.finalize_paid_order(
                db, bot, invoice_row["ref_id"], notify_admins_fn=_notify_admins_of_order
            )
        await call.message.answer(text)

    @router.callback_query(F.data.startswith("check_noapay:"))
    async def cb_check_noapay(call: CallbackQuery, bot: Bot):
        try:
            invoice_db_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await call.answer(db.get_text("handlers_user.payment.invalid_data", "داده نامعتبر."), show_alert=True)
            return
        invoice_row = (await asyncio.to_thread(db.get_noapay_invoice, invoice_db_id))
        if not invoice_row or invoice_row["user_id"] != call.from_user.id:
            await call.answer(db.get_text("handlers_user.payment.invoice_not_found", "فاکتور یافت نشد."), show_alert=True)
            return

        await call.answer(db.get_text("handlers_user.payment.checking_status", "در حال بررسی وضعیت پرداخت..."))
        result = await noapay_payment.try_verify_and_finalize(db, invoice_row)

        if result == "not_paid_yet":
            await call.message.answer(db.get_text("handlers_user.payment.not_confirmed_yet", "⏳ هنوز واریزی برای این فاکتور تایید نشده. کمی صبر کن و دوباره بررسی کن."))
            return
        if result in ("expired", "rejected"):
            await call.message.answer(db.get_text("handlers_user.payment.invoice_expired_rejected", "❌ اعتبار این فاکتور تمام شده یا رد شده. لطفاً دوباره از منو اقدام کن."))
            return
        if result == "already_delivered":
            await call.message.answer(db.get_text("handlers_user.payment.already_confirmed", "✅ این پرداخت قبلاً تایید و تحویل داده شده است."))
            return
        if result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))
            return

        # result == "verified_now"
        if invoice_row["kind"] == "wallet_topup":
            text = await noapay_payment.finalize_paid_topup(db, invoice_row["ref_id"])
        else:
            text = await noapay_payment.finalize_paid_order(
                db, bot, invoice_row["ref_id"], notify_admins_fn=_notify_admins_of_order
            )
        await call.message.answer(text)

    @router.callback_query(F.data.startswith("buy_start:"))
    async def cb_buy_start(call: CallbackQuery, state: FSMContext, bot: Bot):
        _, product_id, quantity = call.data.split(":")
        await _buy_start(call, state, bot, int(product_id), int(quantity))

    async def _buy_start(call, state: FSMContext, bot: Bot, product_id: int, quantity: int, config_name: str = None):
        product = (await asyncio.to_thread(db.get_product, product_id))
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        if not product or stock <= 0:
            await call.answer(db.get_text("handlers_user.product.currently_unavailable", "این محصول در حال حاضر موجود نیست."), show_alert=True)
            return
        if quantity < 1:
            quantity = 1
        if quantity > stock:
            await call.answer(tr(f"موجودی کافی نیست. فقط {stock} عدد موجود است."), show_alert=True)
            return

        if config_name is None and product["is_auto_provision"] and product["provision_server_id"]:
            await state.update_data(buy_name_product_id=product_id, buy_name_quantity=quantity)
            await state.set_state(BuyFlow.waiting_config_name)
            prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
            max_len = 20 if quantity == 1 else 16
            text = "🛠 نام کانفیگ\n\n"
            if prefix:
                text += f"نام با پیش‌وند ثابت «{prefix}-» شروع می‌شود. فقط ادامه‌ی نام (بعد از خط تیره) را ارسال کنید"
            else:
                text += "یک نام دلخواه برای کانفیگ ارسال کنید"
            text += "، یا از دکمه‌ی زیر نام خودکار بگیرید.\n"
            if quantity > 1:
                text += "نام هر کانفیگ با شماره‌ی ترتیبی (_1، _2، ...) ادامه پیدا می‌کند.\n"
            text += f"فقط حروف انگلیسی، عدد و آندرلاین مجاز است (بین ۳ تا {max_len} کاراکتر)."
            await _safe_edit(call.message, text, reply_markup=kb.custom_config_username_kb())
            await call.answer()
            return

        data = await state.get_data()
        discount_code_id = data.get("discount_code_id")
        discount_amount = data.get("discount_amount", 0) or 0

        users = _chosen_users(data, product)
        if users:
            max_users = await _users_option(product)
            users = min(users, max_users) if max_users else 0
        else:
            # محصول با تعداد کاربر ثابت (base_users): همان عدد روی سفارش و سرویس اعمال می‌شود
            users = await asyncio.to_thread(ul.included_users, db, product)

        allowed_methods = (await asyncio.to_thread(db.get_product_payment_methods, product_id))
        wallet_allowed = allowed_methods is None or "wallet" in allowed_methods

        tier_info = await _tier_info(call.from_user.id, ul.price_for_users(product, users), quantity)
        total_price = tier_info["total_after"]
        price_after_code = max(total_price - discount_amount, 0)
        plan = await asyncio.to_thread(db.plan_wallet_spend, call.from_user.id, price_after_code, wallet_allowed)
        if plan["blocked"]:
            await call.message.answer(plan["message"])
            await call.answer()
            return
        wallet_used = plan["wallet_used"]

        if discount_code_id:
            claimed = await asyncio.to_thread(db.claim_discount_use, discount_code_id, call.from_user.id)
            if not claimed:
                await state.update_data(
                    discount_code_id=None, discount_amount=0, discount_product_id=None,
                    pending_discount_code_id=None, pending_discount_code_label=None,
                )
                await call.answer(db.get_text('handlers_user.auto_ca864ddb', 'این کد تخفیف دیگر برای شما قابل استفاده نیست. دوباره تلاش کنید.'), show_alert=True)
                return
        if wallet_used > 0:
            wallet_used = await asyncio.to_thread(db.deduct_wallet_credit, call.from_user.id, wallet_used)

        order_id = (await asyncio.to_thread(db.create_order, 
            call.from_user.id,
            product_id,
            base_price=total_price,
            wallet_used=wallet_used,
            discount_code_id=discount_code_id,
            discount_amount=discount_amount,
            quantity=quantity,
            config_name=config_name or None,
            tier_discount_amount=tier_info["amount"],
            user_limit=users or None,
        ))
        order = (await asyncio.to_thread(db.get_order, order_id))
        await state.update_data(order_id=order_id)
        await state.update_data(
            discount_code_id=None, discount_amount=0, discount_product_id=None,
            pending_discount_code_id=None, pending_discount_code_label=None,
            buy_users_pid=None, buy_users=None,
        )

        # نکته‌ی مهم: از این‌جا به بعد کیف پول کاربر (در صورت استفاده) از قبل کسر
        # شده (خط بالاتر) و سفارش با status='pending' ساخته شده. اگر هر خطای
        # غیرمنتظره‌ای (نه فقط ProvisionError/موجودی تمام‌شده که خودشان مدیریت
        # شده‌اند، بلکه هر Exception دیگری - مثلاً خطای پارس Markdown، قطعی موقت
        # دیتابیس، خطای شبکه‌ی تلگرام و...) در ادامه‌ی این تابع رخ بدهد و کل
        # هندلر کرش کند، بدون این try/except مبلغ کسرشده برای همیشه در سفارش
        # pending گیر می‌کرد و هیچ‌جا برنمی‌گشت. reject_order فقط روی سفارش‌های
        # هنوز pending اثر می‌کند (اگر سفارش already approved/rejected شده باشد
        # بی‌اثر است)، پس فراخوانی آن در حالت خطا همیشه امن است.
        try:
            if order["final_price"] <= 0:
                await state.clear()

                if product["is_auto_provision"]:
                    try:
                        if product["provision_server_id"]:
                            prov_results = await provision_direct(db, product, quantity, user_id=call.from_user.id, order_id=order_id)
                        else:
                            prov_results = await provision_auto_config(db, product, quantity, user_id=call.from_user.id, order_id=order_id)
                    except (ProvisionError, DirectProvisionError) as e:
                        (await asyncio.to_thread(db.reject_order, order_id))
                        await _notify_admins_of_order(bot, order_id)
                        await _safe_edit(
                            call.message,
                            f"⛔️ {e}\nمبلغ کسرشده از کیف پول شما به‌طور کامل بازگردانده شد."
                        )
                        await call.answer()
                        return
                    (await asyncio.to_thread(db.approve_order_auto, order_id))
                    links = [r["subscription_url"] for r in prov_results]
                else:
                    results = (await asyncio.to_thread(db.take_unused_configs, product_id, call.from_user.id, quantity))
                    if not results:
                        # موجودی تمام شده: مبلغ کسرشده از کیف پول/کد تخفیف را برگردان و به ادمین اطلاع بده
                        (await asyncio.to_thread(db.reject_order, order_id))
                        await _notify_admins_of_order(bot, order_id)
                        await _safe_edit(
                            call.message,
                            db.get_text('handlers_user.auto_30519740', '⛔️ موجودی این محصول در حال حاضر تمام شده است.\nمبلغ کسرشده از کیف پول شما به\u200cطور کامل بازگردانده شد. لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی در تماس باشید.')
                        )
                        await call.answer()
                        return
                    (await asyncio.to_thread(db.approve_order, order_id, [r["id"] for r in results]))
                    links = [r["link"] for r in results]
                    await check_and_notify_low_stock(bot.send_message, db, product_id, bot_token=bot.token)
                reward_info = (await asyncio.to_thread(db.reward_referrer_if_first_purchase, call.from_user.id, order["base_price"]))
                if reward_info:
                    reward_amount, referrer_id = reward_info
                    try:
                        await bot.send_message(
                            referrer_id,
                            tr(f"🤝 تبریک! یکی از زیرمجموعه‌های شما اولین خرید خود را انجام داد.\n"
                            f"💰 {reward_amount:,} تومان به کیف پول شما اضافه شد."),
                        )
                    except Exception:
                        pass

                # اطلاع‌رسانی به ادمین‌ها فقط جهت آگاهی (نیازی به تایید دستی نیست)
                try:
                    await _notify_admins_of_order(bot, order_id)
                except Exception:
                    pass

                await _safe_edit(
                    call.message,
                    db.get_text('handlers_user.auto_d8da31b4', '✅ مبلغ سفارش شما به\u200cطور کامل از کیف پول/تخفیف پوشش داده شد.\nکانفیگ شما در پیام بعدی ارسال می\u200cشود 👇')
                )
                await deliver_config_to_user(
                    bot,
                    call.from_user.id,
                    product["name"],
                    links,
                    final_price=0,
                    order_id=order_id,
                    db=db,
                )
                await call.answer()
                return

            remaining_amount = order["final_price"]

            if remaining_amount > 0 and not (await asyncio.to_thread(
                db.has_any_payable_method, remaining_amount, allowed_methods
            )):
                # توجه: قبلاً این‌جا یک‌بار دستی add_wallet_credit(+wallet_used) هم زده
                # می‌شد؛ چون reject_order خودش مبلغ order["wallet_used"] را برمی‌گرداند،
                # آن فراخوانی اضافه باعث می‌شد مبلغ کیف پول کاربر دوبار برگردانده شود
                # (کاربر اعتبار اضافه می‌گرفت). حذف شد.
                (await asyncio.to_thread(db.reject_order, order_id))
                await state.clear()
                msg = "⛔️ در حال حاضر هیچ روش پرداخت فعالی برای این مبلغ در دسترس نیست."
                if allowed_methods == ["wallet"]:
                    msg = "⛔️ این محصول فقط با کیف پول قابل خرید است و موجودی کیف پول شما کافی نیست."
                if wallet_used > 0:
                    msg += "\nمبلغ کسرشده از کیف پول شما بازگردانده شد."
                await _safe_edit(call.message, msg)
                await call.answer()
                return

            await state.set_state(BuyFlow.waiting_receipt)

            after_buy_text = (await asyncio.to_thread(db.get_setting, "after_buy_text"))

            text = f"{after_buy_text}\n\n"
            if quantity > 1:
                text += f"🔢 تعداد: {quantity} عدد\n"
            if users:
                text += f"👥 تعداد کاربر همزمان: {users}\n"
            if discount_amount:
                text += f"🎟 تخفیف کد: {discount_amount:,} تومان\n"
            if wallet_used:
                text += f"👛 استفاده از کیف پول: {wallet_used:,} تومان\n"
            text += f"💰 مبلغ نهایی قابل پرداخت: {order['final_price']:,} تومان\n\n"
            text += "لطفاً روش پرداخت را انتخاب کنید:"

            await _safe_edit(
                call.message,
                text, parse_mode="Markdown",
                reply_markup=kb.payment_choice_kb(
                    crypto_payment.crypto_payment_available(db),
                    abangateway_payment.abangateway_payment_available(db),
                    custom_gateway_payment.list_enabled_gateways(db),
                    (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) == "1",
                    card_auto_enabled=(await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) == "1",
                    amount=remaining_amount,
                    db=db,
                    allowed_methods=allowed_methods,
                    noapay_enabled=noapay_payment.noapay_payment_available(db),
                    blupal_enabled=blupal_payment.blupal_payment_available(db),
                    extra_gateways=extra_gateway_payment.available_keys(db, is_main_bot),
                ),
            )
            await call.answer()
        except Exception:
            logging.getLogger("handlers_user").exception(
                "خطای غیرمنتظره در فرآیند خرید سفارش #%s برای کاربر %s؛ سفارش رد و مبلغ کیف پول (در صورت وجود) بازگردانده شد.",
                order_id, call.from_user.id,
            )
            (await asyncio.to_thread(db.reject_order, order_id))
            await state.clear()
            await _safe_edit(
                call.message,
                db.get_text('handlers_user.auto_7c0e859b', '⛔️ خطای غیرمنتظره\u200cای در پردازش سفارش رخ داد.\nاگر مبلغی از کیف پول شما کسر شده بود، به\u200cطور کامل بازگردانده شد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.')
            )
            try:
                await call.answer()
            except Exception:
                pass

    @router.callback_query(F.data == "custom_config_random_username", BuyFlow.waiting_config_name)
    async def cb_buy_random_config_name(call: CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        product_id = data.get("buy_name_product_id")
        if not product_id:
            await state.clear()
            await call.answer(db.get_text("handlers_user.flow.step_expired", "این مرحله منقضی شده؛ دوباره از منو اقدام کنید."), show_alert=True)
            return
        await _buy_start(call, state, bot, int(product_id), int(data.get("buy_name_quantity") or 1), config_name="")

    @router.message(BuyFlow.waiting_config_name)
    async def buy_receive_config_name(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        product_id = data.get("buy_name_product_id")
        if not product_id:
            await state.clear()
            await message.answer(db.get_text("handlers_user.flow.step_expired", "این مرحله منقضی شده؛ دوباره از منو اقدام کنید."))
            return
        quantity = int(data.get("buy_name_quantity") or 1)
        max_len = 20 if quantity == 1 else 16
        suffix = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,%d}" % max_len, suffix):
            await message.answer(tr(f"❌ نام نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا {max_len} کاراکتر."))
            return
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        base = f"{prefix}-{suffix}" if prefix else suffix
        for candidate in planned_usernames(base, quantity):
            if (await asyncio.to_thread(db.is_custom_username_taken, candidate)):
                await message.answer(db.get_text('handlers_user.auto_aab267fe', '❌ این نام قبلاً استفاده شده. لطفاً نام دیگری ارسال کنید.'))
                return
        progress = await message.answer(db.get_text('handlers_user.auto_86206ade', '⏳ در حال ثبت سفارش...'))
        await _buy_start(_MessageCall(message.from_user, progress), state, bot, int(product_id), quantity, config_name=base)

    @router.callback_query(F.data == "pay_card2card", BuyFlow.waiting_receipt)
    async def cb_pay_card2card_order(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "card")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        intro_lines = []
        if order["quantity"] and order["quantity"] > 1:
            intro_lines.append(f"🔢 تعداد: {order['quantity']} عدد")
        if order["discount_amount"]:
            intro_lines.append(f"🎟 تخفیف کد: {order['discount_amount']:,} تومان")
        if order["wallet_used"]:
            intro_lines.append(f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان")
        await _send_card2card_details(call.message, intro_lines, order["final_price"])

    @router.callback_query(F.data == "pay_card_auto", BuyFlow.waiting_receipt)
    async def cb_pay_card_auto_order(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "card_auto")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        intro_lines = []
        if order["quantity"] and order["quantity"] > 1:
            intro_lines.append(f"🔢 تعداد: {order['quantity']} عدد")
        if order["discount_amount"]:
            intro_lines.append(f"🎟 تخفیف کد: {order['discount_amount']:,} تومان")
        if order["wallet_used"]:
            intro_lines.append(f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان")
        await _send_card_auto_details(
            call.message, intro_lines, "order", order_id, call.from_user.id, order["final_price"],
        )
    @router.callback_query(F.data == "cancel_flow")
    async def cb_cancel_flow(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        if order_id:
            order = (await asyncio.to_thread(db.get_order, order_id))
            if order and order["status"] == "pending":
                (await asyncio.to_thread(db.reject_order, order_id))
        await state.clear()
        await _safe_edit(call.message, db.get_text('handlers_user.auto_570dedda', 'عملیات لغو شد.'))
        await call.answer()

    @router.callback_query(F.data == "pay_crypto", BuyFlow.waiting_receipt)
    async def cb_pay_crypto_order(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "crypto")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await crypto_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"سفارش #{order_id} - {product['name'] if product else ''}",
            )
        except crypto_payment.CryptoPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        await call.message.answer(
            db.get_text('handlers_user.auto_bed9e374', '🪙 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.\n⏳ اعتبار این فاکتور فقط ۸۰ دقیقه است.\nبه\u200cمحض تایید تراکنش روی بلاک\u200cچین، سفارش شما به\u200cصورت خودکار تحویل داده می\u200cشود.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data == "pay_abangateway", BuyFlow.waiting_receipt)
    async def cb_pay_abangateway_order(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "abangateway")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await abangateway_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"سفارش #{order_id} - {product['name'] if product else ''}",
            )
        except abangateway_payment.AbanGatewayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_abangateway_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_12ea9cde', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\n⏳ اعتبار این فاکتور محدود است.\nمعمولاً به\u200cمحض واریز، سفارش خودکار تحویل داده می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_aban:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_blupal", BuyFlow.waiting_receipt)
    async def cb_pay_blupal_order(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "blupal")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await blupal_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"سفارش #{order_id} - {product['name'] if product else ''}",
            )
        except blupal_payment.BluPalPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_blupal_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_64b8f84a', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\n⏳ اعتبار این فاکتور حدود ۳۰ دقیقه است.\nمعمولاً به\u200cمحض واریز، سفارش خودکار تحویل داده می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_blupal:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_noapay", BuyFlow.waiting_receipt)
    async def cb_pay_noapay_order(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "noapay")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await noapay_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"سفارش #{order_id} - {product['name'] if product else ''}",
            )
        except noapay_payment.NoapayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_noapay_invoice_by_token, result["invoice_token"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_2fae0081', '⭐ فاکتور پرداخت (NoapayBot) ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\n⏳ اعتبار این فاکتور محدود است.\nمعمولاً به\u200cمحض واریز، سفارش خودکار تحویل داده می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_noapay:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data.startswith("pay_customgw:"), BuyFlow.waiting_receipt)
    async def cb_pay_customgw_order(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        gw_row = (await asyncio.to_thread(db.get_custom_gateway, int(call.data.split(":", 1)[1])))
        if not gw_row or not gw_row["enabled"]:
            await call.answer(db.get_text('handlers_user.auto_e29914cb', 'این درگاه در دسترس نیست.'), show_alert=True)
            return
        err = await _order_payment_method_error(order, f"custom:{gw_row['gateway_key']}")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        if await _start_customgw_payment(
            call.message, state, BuyFlow.waiting_customgw_phone, gw_row,
            prompt_prefix="⏳ در حال آماده‌سازی فاکتور...",
        ):
            return
        await call.message.answer(db.get_text('handlers_user.auto_9bbc7040', '⏳ در حال ساخت فاکتور...'))
        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        await _send_customgw_invoice(
            call.message, gw_row, "order", order_id, call.from_user.id, order["final_price"],
            order_name=f"سفارش #{order_id} - {product['name'] if product else ''}",
            customer_phone=None, noun="سفارش", verb="تحویل داده می‌شود",
        )

    @router.message(BuyFlow.waiting_customgw_phone, F.contact)
    async def receive_customgw_phone_order(message: Message, state: FSMContext):
        if not message.contact or message.contact.user_id != message.from_user.id:
            await message.answer(db.get_text('handlers_user.auto_78cc91ac', '❌ لطفاً با زدن همون دکمه\u200cی «اشتراک\u200cگذاری شماره موبایل» شماره\u200cی خودت رو بفرست.'))
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        gw_id = data.get("customgw_gateway_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        gw_row = (await asyncio.to_thread(db.get_custom_gateway, gw_id)) if gw_id else None
        if not order or order["status"] != "pending" or not gw_row or not gw_row["enabled"]:
            await message.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return
        await state.set_state(BuyFlow.waiting_receipt)
        await message.answer(db.get_text('handlers_user.auto_9bbc7040', '⏳ در حال ساخت فاکتور...'), reply_markup=ReplyKeyboardRemove())
        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        await _send_customgw_invoice(
            message, gw_row, "order", order_id, message.from_user.id, order["final_price"],
            order_name=f"سفارش #{order_id} - {product['name'] if product else ''}",
            customer_phone=message.contact.phone_number, noun="سفارش", verb="تحویل داده می‌شود",
        )

    @router.message(BuyFlow.waiting_customgw_phone, F.text == "❌ انصراف")
    async def cancel_customgw_phone_order(message: Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        if order_id:
            order = (await asyncio.to_thread(db.get_order, order_id))
            if order and order["status"] == "pending":
                (await asyncio.to_thread(db.reject_order, order_id))
        await state.clear()
        await message.answer(db.get_text('handlers_user.auto_570dedda', 'عملیات لغو شد.'), reply_markup=ReplyKeyboardRemove())

    @router.message(BuyFlow.waiting_customgw_phone)
    async def receive_customgw_phone_invalid_order(message: Message):
        await message.answer(
            db.get_text('handlers_user.auto_3cb5d7ba', '📱 لطفاً با زدن دکمه\u200cی «اشتراک\u200cگذاری شماره موبایل» ادامه بده، یا انصراف بده.'),
            reply_markup=kb.share_phone_kb(),
        )

    @router.message(BuyFlow.waiting_receipt, F.photo | F.document)
    async def receive_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order or order["status"] != "pending":
            await message.answer(db.get_text('handlers_user.auto_32ccba24', 'سفارش معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return

        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_order_receipt, order_id, file_id, receipt_type))

        await _notify_admins_of_order(
            bot, order_id, receipt_file_id=file_id, receipt_type=receipt_type
        )

        await message.answer(
            db.get_text('handlers_user.auto_9cef8cad', '✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، کانفیگ برای شما ارسال خواهد شد.'),
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        await state.clear()

    @router.message(BuyFlow.waiting_receipt)
    async def receipt_wrong_type(message: Message):
        await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))

    # -----------------------------------------------------------------------
    # ساخت کانفیگ شخصی (اتصال مستقیم به پنل VPN)
    # -----------------------------------------------------------------------

    def _format_pricing_table(tiers) -> str:
        lines = ["💰 جدول قیمت‌گذاری (بر اساس بازه‌ی حجم):", ""]
        for t in tiers:
            to_label = f"{t['to_gb']} گیگ" if t["to_gb"] is not None else "به بالا"
            from_label = f"{t['from_gb']}" if t["to_gb"] is not None else f"{t['from_gb']} گیگ"
            lines.append(f"▫️ {from_label} تا {to_label} ← {t['price_per_gb']:,} تومان/گیگ")
        lines.append("")
        lines.append("قیمت نهایی = کل حجم انتخابی × نرخ همان بازه‌ای که حجم داخلش قرار می‌گیرد.")
        return "\n".join(lines)

    async def custom_config_start(message: Message, state: FSMContext):
        if not full_access_bot:
            await message.answer(db.get_text('handlers_user.auto_1be04045', 'این بخش در حال حاضر غیرفعال است.'))
            return
        products = (await asyncio.to_thread(db.get_custom_config_products, True))
        if not products:
            # نصب‌های بسیار قدیمی که هنوز مهاجرت به مدل محصولی برایشان اجرا
            # نشده (یا اصلاً هرگز فعال نبوده‌اند): همان مسیر سراسری قدیمی.
            settings = (await asyncio.to_thread(db.get_custom_config_settings))
            if not settings["enabled"]:
                await message.answer(db.get_text('handlers_user.auto_1be04045', 'این بخش در حال حاضر غیرفعال است.'))
                return
            server = (await asyncio.to_thread(db.get_panel_server_for_usage, "custom_config"))
            if not server:
                await message.answer(db.get_text('handlers_user.auto_ebb74adf', 'در حال حاضر سروری برای ساخت کانفیگ شخصی فعال نیست. لطفاً بعداً تلاش کنید.'))
                return
            tiers = (await asyncio.to_thread(db.get_pricing_tiers))
            if not tiers:
                await message.answer(db.get_text('handlers_user.auto_bc026085', 'قیمت\u200cگذاری این بخش هنوز توسط ادمین تنظیم نشده است.'))
                return
            await state.update_data(product_id=None, panel_server_id=server["id"])
            await _custom_config_ask_username(message, state)
            return

        if len(products) == 1:
            await _custom_config_select_product(message, state, products[0])
            return

        await state.set_state(CustomConfigFlow.waiting_product_select)
        lines = ["🛠 ساخت کانفیگ شخصی\n", "لطفاً یکی از پلن‌های زیر را انتخاب کن:"]
        for p in products:
            if p["description"]:
                lines.append(f"\n{p['icon'] or '🛠'} <b>{p['name']}</b>\n{p['description']}")
            else:
                lines.append(f"\n{p['icon'] or '🛠'} <b>{p['name']}</b>")
        await message.answer(
            "\n".join(lines), parse_mode="HTML",
            reply_markup=kb.custom_config_product_select_kb(products),
        )

    @router.callback_query(F.data.startswith("ccf_pick_product:"), CustomConfigFlow.waiting_product_select)
    async def cb_custom_config_pick_product(call: CallbackQuery, state: FSMContext):
        product_id = int(call.data.split(":", 1)[1])
        product = (await asyncio.to_thread(db.get_custom_config_product, product_id))
        if not product or not product["is_active"]:
            await call.answer(db.get_text('handlers_user.auto_c6a86863', 'این پلن دیگر در دسترس نیست.'), show_alert=True)
            return
        await call.answer()
        try:
            await call.message.delete()
        except Exception:
            pass
        await _custom_config_select_product(call.message, state, product)

    async def _custom_config_select_product(message: Message, state: FSMContext, product):
        server = (await asyncio.to_thread(db.get_panel_server, product["panel_server_id"]))
        if not server or not server["is_active"]:
            await message.answer(db.get_text('handlers_user.auto_e8464426', '⛔️ سرور این پلن در حال حاضر در دسترس نیست. لطفاً بعداً تلاش کنید.'))
            return
        if product["pricing_mode"] == "tiered" and not (await asyncio.to_thread(db.get_custom_config_product_tiers, product["id"])):
            await message.answer(db.get_text('handlers_user.auto_881dcc0e', '⚠️ قیمت\u200cگذاری این پلن هنوز توسط ادمین تنظیم نشده. لطفاً با پشتیبانی تماس بگیر.'))
            return
        await state.update_data(product_id=product["id"], panel_server_id=server["id"])
        await _custom_config_ask_username(message, state)

    async def _custom_config_ask_username(message: Message, state: FSMContext):
        await state.set_state(CustomConfigFlow.waiting_username)
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        if prefix:
            await message.answer(
                tr("🛠 ساخت کانفیگ شخصی\n\n"
                f"نام هر کانفیگ با پیش‌وند ثابت «{prefix}-» شروع می‌شود. لطفاً فقط ادامه‌ی نام "
                "(بعد از خط تیره) را ارسال کنید، یا از دکمه‌ی زیر یک نام تصادفی بگیر.\n"
                "فقط حروف انگلیسی، عدد و آندرلاین مجاز است (بین ۳ تا ۲۰ کاراکتر)."),
                reply_markup=kb.custom_config_username_kb(),
            )
        else:
            await message.answer(
                db.get_text('handlers_user.auto_1abaf690', '🛠 ساخت کانفیگ شخصی\n\nلطفاً یک نام کاربری دلخواه برای کانفیگ خود ارسال کنید، یا از دکمه\u200cی زیر یک نام تصادفی بگیر.\nفقط حروف انگلیسی، عدد و آندرلاین مجاز است (بین ۳ تا ۲۰ کاراکتر).'),
                reply_markup=kb.custom_config_username_kb(),
            )

    @router.callback_query(F.data == "custom_config_random_username", CustomConfigFlow.waiting_username)
    async def cb_custom_config_random_username(call: CallbackQuery, state: FSMContext):
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        for _ in range(10):
            suffix = "u" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
            candidate = f"{prefix}-{suffix}" if prefix else suffix
            if not (await asyncio.to_thread(db.is_custom_username_taken, candidate)):
                break
        await call.answer()
        await _custom_config_apply_username(call.message, state, candidate)

    @router.message(CustomConfigFlow.waiting_username)
    async def custom_config_receive_username(message: Message, state: FSMContext):
        suffix = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", suffix):
            await message.answer(db.get_text('handlers_user.auto_b8c82218', '❌ نام کاربری نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.'))
            return
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        username = f"{prefix}-{suffix}" if prefix else suffix
        if (await asyncio.to_thread(db.is_custom_username_taken, username)):
            await message.answer(db.get_text('handlers_user.auto_3fa427ee', '❌ این نام کاربری قبلاً استفاده شده. لطفاً نام دیگری انتخاب کنید.'))
            return
        await _custom_config_apply_username(message, state, username)

    async def _custom_config_apply_username(message: Message, state: FSMContext, username: str):
        data = await state.get_data()
        product_id = data.get("product_id")
        await state.update_data(custom_username=username)
        await state.set_state(CustomConfigFlow.waiting_volume)
        if product_id:
            product = (await asyncio.to_thread(db.get_custom_config_product, product_id))
            duration_note = (
                f"⏳ مدت اعتبار: {product['duration_days']} روز (ثابت)"
                if product["duration_mode"] == "fixed"
                else f"⏳ مدت اعتبار: بعد از انتخاب حجم، بین {product['min_days'] or 1} تا {product['max_days'] or 90} روز خودت انتخاب می‌کنی"
            )
            pricing_note = (
                f"💰 قیمت: {product['flat_price_per_gb']:,} تومان/گیگ"
                if product["pricing_mode"] == "flat"
                else _format_pricing_table((await asyncio.to_thread(db.get_custom_config_product_tiers, product_id)))
            )
            await message.answer(
                tr(f"✅ نام کاربری: {username}\n\n"
                f"{pricing_note}\n\n"
                f"📶 حالا حجم مورد نظر خود را به گیگابایت وارد کنید.\n"
                f"حداقل: {product['min_gb']} گیگ — حداکثر: {product['max_gb']} گیگ\n"
                f"{duration_note}"),
                reply_markup=kb.cancel_kb(),
            )
        else:
            settings = (await asyncio.to_thread(db.get_custom_config_settings))
            tiers = (await asyncio.to_thread(db.get_pricing_tiers))
            await message.answer(
                tr(f"✅ نام کاربری: {username}\n\n"
                f"{_format_pricing_table(tiers)}\n\n"
                f"📶 حالا حجم مورد نظر خود را به گیگابایت وارد کنید.\n"
                f"حداقل: {settings['min_gb']} گیگ — حداکثر: {settings['max_gb']} گیگ\n"
                f"⏳ مدت اعتبار: {settings['duration_days']} روز (ثابت)"),
                reply_markup=kb.cancel_kb(),
            )

    @router.message(CustomConfigFlow.waiting_duration)
    async def custom_config_receive_duration(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        data = await state.get_data()
        product = (await asyncio.to_thread(db.get_custom_config_product, data.get("product_id")))
        if not product:
            await message.answer(db.get_text('handlers_user.auto_917a82c0', '⛔️ این پلن دیگر در دسترس نیست. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return
        min_days, max_days = product["min_days"] or 1, product["max_days"] or 90
        if not text.isdigit() or int(text) < min_days or int(text) > max_days:
            await message.answer(tr(f"❌ مدت باید بین {min_days} تا {max_days} روز باشد."))
            return
        await _custom_config_finalize_order(message, state, int(text))


    @router.message(CustomConfigFlow.waiting_volume)
    async def custom_config_receive_volume(message: Message, state: FSMContext):
        data = await state.get_data()
        product_id = data.get("product_id")
        product = (await asyncio.to_thread(db.get_custom_config_product, product_id)) if product_id else None
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_user.auto_5272e718', '❌ لطفاً فقط عدد صحیح وارد کنید (به گیگابایت).'))
            return
        volume_gb = int(text)

        if product:
            if volume_gb < product["min_gb"] or volume_gb > product["max_gb"]:
                await message.answer(tr(f"❌ حجم باید بین {product['min_gb']} تا {product['max_gb']} گیگابایت باشد."))
                return
            price = (await asyncio.to_thread(db.calc_custom_config_product_price, product_id, volume_gb))
        else:
            settings = (await asyncio.to_thread(db.get_custom_config_settings))
            if volume_gb < settings["min_gb"] or volume_gb > settings["max_gb"]:
                await message.answer(tr(f"❌ حجم باید بین {settings['min_gb']} تا {settings['max_gb']} گیگابایت باشد."))
                return
            price = (await asyncio.to_thread(db.calc_custom_config_price, volume_gb))

        if price <= 0:
            await message.answer(db.get_text('handlers_user.auto_9aee5aa0', '⚠️ قیمت\u200cگذاری برای این بخش هنوز تنظیم نشده. لطفاً با پشتیبانی تماس بگیرید.'))
            await state.clear()
            return

        await state.update_data(custom_volume_gb=volume_gb, custom_price=price)

        if product and product["duration_mode"] == "user_choice":
            await state.set_state(CustomConfigFlow.waiting_duration)
            min_days, max_days = product["min_days"] or 1, product["max_days"] or 90
            await message.answer(tr(f"⏳ مدت اعتبار را به روز وارد کن (بین {min_days} تا {max_days} روز):"))
            return

        duration_days = product["duration_days"] if product else (await asyncio.to_thread(db.get_custom_config_settings))["duration_days"]
        await _custom_config_finalize_order(message, state, duration_days)

    async def _custom_config_finalize_order(message: Message, state: FSMContext, duration_days: int):
        data = await state.get_data()
        volume_gb = data.get("custom_volume_gb")
        price = data.get("custom_price")
        username = data.get("custom_username")
        product_id = data.get("product_id")
        server = (await asyncio.to_thread(db.get_panel_server, data.get("panel_server_id")))
        if not server or not server["is_active"]:
            await message.answer(db.get_text('handlers_user.auto_0feb94f0', '⛔️ سرور این بخش دیگر در دسترس نیست. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return

        tier_info = await _tier_info(message.from_user.id, price, 1)
        price = tier_info["total_after"]
        allowed_methods = await asyncio.to_thread(db.get_effective_custom_config_payment_methods, product_id)
        wallet_allowed = allowed_methods is None or "wallet" in allowed_methods
        plan = await asyncio.to_thread(db.plan_wallet_spend, message.from_user.id, price, wallet_allowed)
        if plan["blocked"]:
            await message.answer(plan["message"])
            await state.clear()
            return
        wallet_used = plan["wallet_used"]

        capacity_ok = await asyncio.to_thread(db.panel_has_capacity, server["id"], 1)
        if not capacity_ok:
            cap = await asyncio.to_thread(db.get_panel_capacity_info, server["id"])
            await message.answer(tr(f"⛔️ ظرفیت پنل تکمیل است ({cap['active_services']}/{cap['max_services']} سرویس فعال)."))
            await state.clear()
            return

        if wallet_used > 0:
            wallet_used = await asyncio.to_thread(db.deduct_wallet_credit, message.from_user.id, wallet_used)

        order_id = (await asyncio.to_thread(db.create_custom_config_order, 
            message.from_user.id, volume_gb, username, server["id"],
            base_price=price, wallet_used=wallet_used,
            custom_product_id=product_id, custom_duration_days=duration_days,
            tier_discount_amount=tier_info["amount"],
        ))
        order = (await asyncio.to_thread(db.get_order, order_id))
        await state.update_data(order_id=order_id, custom_volume_gb=volume_gb)

        try:
            if order["final_price"] <= 0:
                await state.clear()
                server_row = (await asyncio.to_thread(db.get_panel_server, server["id"]))
                try:
                    if not db.panel_has_capacity(server_row["id"], 1):
                        raise RuntimeError("ظرفیت پنل در همین لحظه تکمیل شد.")
                    provider = get_provider(server_row)
                    result = await provider.create_user(username, volume_gb, duration_days)
                except PanelUsernameTakenError:
                    (await asyncio.to_thread(db.reject_order, order_id))
                    await message.answer(db.get_text('handlers_user.auto_2bb7a76d', '❌ این نام کاربری تکراری است، یک نام دیگر انتخاب کنید.\nمبلغ به کیف پول بازگردانده شد.'))
                    return
                except Exception as e:
                    (await asyncio.to_thread(db.reject_order, order_id))
                    await message.answer(tr(f"⛔️ خطا در ساخت کانفیگ روی پنل: {e}\nمبلغ به کیف پول بازگردانده شد."))
                    return
                (await asyncio.to_thread(db.approve_custom_config_order, order_id))
                (await asyncio.to_thread(db.add_custom_config, 
                    message.from_user.id, server["id"], result.username, volume_gb,
                    duration_days, result.subscription_url, order_id=order_id, product_id=product_id,
                ))
                await message.answer(
                    db.get_text('handlers_user.auto_5f36061a', '✅ مبلغ سفارش شما به\u200cطور کامل از کیف پول پوشش داده شد.\nکانفیگ شما در پیام بعدی ارسال می\u200cشود 👇'),
                    reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
                )
                await _send_inline_main_menu(message, message.from_user.id)
                await deliver_config_to_user(
                    message.bot, message.from_user.id, "کانفیگ شخصی",
                    [result.subscription_url], final_price=0, order_id=order_id, db=db,
                )
                try:
                    await _notify_admins_of_order(message.bot, order_id)
                except Exception:
                    pass
                return

            remaining_amount = order["final_price"]
            if not (await asyncio.to_thread(db.has_any_payable_method, remaining_amount, allowed_methods)):
                # reject_order خودش مبلغ order["wallet_used"] را برمی‌گرداند؛ برگرداندن
                # دستی اضافه‌ی قبلی این‌جا حذف شد چون باعث بازگشت دوبرابری می‌شد.
                (await asyncio.to_thread(db.reject_order, order_id))
                await state.clear()
                await message.answer(
                    "⛔️ در حال حاضر هیچ روش پرداخت فعالی برای این مبلغ در دسترس نیست."
                    + ("\nمبلغ کسرشده از کیف پول شما بازگردانده شد." if wallet_used > 0 else "")
                )
                return

            await state.set_state(CustomConfigFlow.waiting_receipt)
            text = (
                f"🛠 نام کاربری: {escape_md(username)}\n"
                f"📶 حجم: {volume_gb} گیگابایت\n"
                f"⏳ مدت: {duration_days} روز\n\n"
            )
            if tier_info["amount"] > 0:
                text += (
                    f"{tier_info['icon']} تخفیف سطح {escape_md(tier_info['title'])} "
                    f"({tier_info['percent']}٪): {tier_info['amount']:,} تومان\n"
                )
            if wallet_used:
                text += f"👛 استفاده از کیف پول: {wallet_used:,} تومان\n"
            text += f"💰 مبلغ نهایی قابل پرداخت: {order['final_price']:,} تومان\n\n"
            text += "لطفاً روش پرداخت را انتخاب کنید:"
            await message.answer(
                text, parse_mode="Markdown",
                reply_markup=kb.payment_choice_kb(
                    crypto_payment.crypto_payment_available(db),
                    abangateway_payment.abangateway_payment_available(db),
                    custom_gateway_payment.list_enabled_gateways(db),
                    (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) == "1",
                    card_auto_enabled=(await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) == "1",
                    amount=remaining_amount,
                    db=db,
                    allowed_methods=allowed_methods,
                    noapay_enabled=noapay_payment.noapay_payment_available(db),
                    blupal_enabled=blupal_payment.blupal_payment_available(db),
                    extra_gateways=extra_gateway_payment.available_keys(db, is_main_bot),
                ),
            )
        except Exception:
            logging.getLogger("handlers_user").exception(
                "خطای غیرمنتظره در فرآیند ساخت کانفیگ شخصی (سفارش #%s) برای کاربر %s؛ سفارش رد و مبلغ کیف پول (در صورت وجود) بازگردانده شد.",
                order_id, message.from_user.id,
            )
            (await asyncio.to_thread(db.reject_order, order_id))
            await state.clear()
            await message.answer(
                db.get_text('handlers_user.auto_7c0e859b', '⛔️ خطای غیرمنتظره\u200cای در پردازش سفارش رخ داد.\nاگر مبلغی از کیف پول شما کسر شده بود، به\u200cطور کامل بازگردانده شد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.')
            )

    @router.callback_query(F.data == "pay_card2card", CustomConfigFlow.waiting_receipt)
    async def cb_pay_card2card_custom_config(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "card")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        duration_days = order["custom_duration_days"]
        if duration_days is None:
            duration_days = (await asyncio.to_thread(db.get_custom_config_settings))["duration_days"]
        intro_lines = [
            f"🛠 نام کاربری: {escape_md(order['custom_username'])}",
            f"📶 حجم: {order['custom_volume_gb']} گیگابایت",
            f"⏳ مدت: {duration_days} روز",
        ]
        if order["wallet_used"]:
            intro_lines.append(f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان")
        await _send_card2card_details(call.message, intro_lines, order["final_price"])

    @router.callback_query(F.data == "pay_card_auto", CustomConfigFlow.waiting_receipt)
    async def cb_pay_card_auto_custom_config(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "card_auto")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        duration_days = order["custom_duration_days"]
        if duration_days is None:
            duration_days = (await asyncio.to_thread(db.get_custom_config_settings))["duration_days"]
        intro_lines = [
            f"🛠 نام کاربری: {escape_md(order['custom_username'])}",
            f"📶 حجم: {order['custom_volume_gb']} گیگابایت",
            f"⏳ مدت: {duration_days} روز",
        ]
        if order["wallet_used"]:
            intro_lines.append(f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان")
        await _send_card_auto_details(
            call.message, intro_lines, "order", order_id, call.from_user.id, order["final_price"],
        )

    @router.callback_query(F.data == "pay_crypto", CustomConfigFlow.waiting_receipt)
    async def cb_pay_crypto_custom_config(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "crypto")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await crypto_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"کانفیگ شخصی #{order_id} - {order['custom_username']}",
            )
        except crypto_payment.CryptoPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        await call.message.answer(
            db.get_text('handlers_user.auto_c7ac1436', '🪙 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.\n⏳ اعتبار این فاکتور فقط ۸۰ دقیقه است.\nبه\u200cمحض تایید تراکنش روی بلاک\u200cچین، کانفیگ شما به\u200cصورت خودکار ساخته می\u200cشود.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data == "pay_abangateway", CustomConfigFlow.waiting_receipt)
    async def cb_pay_abangateway_custom_config(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "abangateway")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await abangateway_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"کانفیگ شخصی #{order_id} - {order['custom_username']}",
            )
        except abangateway_payment.AbanGatewayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_abangateway_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_117e923b', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، کانفیگ خودکار ساخته می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_aban:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_blupal", CustomConfigFlow.waiting_receipt)
    async def cb_pay_blupal_custom_config(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "blupal")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await blupal_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"کانفیگ شخصی #{order_id} - {order['custom_username']}",
            )
        except blupal_payment.BluPalPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_blupal_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_117e923b', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، کانفیگ خودکار ساخته می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_blupal:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_noapay", CustomConfigFlow.waiting_receipt)
    async def cb_pay_noapay_custom_config(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        err = await _order_payment_method_error(order, "noapay")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await noapay_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"کانفیگ شخصی #{order_id} - {order['custom_username']}",
            )
        except noapay_payment.NoapayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_noapay_invoice_by_token, result["invoice_token"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_2f92e15c', '⭐ فاکتور پرداخت (NoapayBot) ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، کانفیگ خودکار ساخته می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_noapay:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data.startswith("pay_customgw:"), CustomConfigFlow.waiting_receipt)
    async def cb_pay_customgw_custom_config(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        gw_row = (await asyncio.to_thread(db.get_custom_gateway, int(call.data.split(":", 1)[1])))
        if not gw_row or not gw_row["enabled"]:
            await call.answer(db.get_text('handlers_user.auto_e29914cb', 'این درگاه در دسترس نیست.'), show_alert=True)
            return
        err = await _order_payment_method_error(order, f"custom:{gw_row['gateway_key']}")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await custom_gateway_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, gw_row["gateway_key"], "order", order_id, order["final_price"],
                order_name=f"کانفیگ شخصی #{order_id} - {order['custom_username']}",
            )
        except custom_gateway_payment.CustomGatewayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        if not result.get("invoice_url"):
            await call.message.answer(
                f"{tr('💠 فاکتور')} «{gw_row['name']}» {tr('ساخته شد ولی این درگاه لینک پرداخت برنگرداند.')}\n"
                "پس از انجام پرداخت، کانفیگ به‌محض تایید درگاه به‌صورت خودکار ساخته می‌شود.")
            return
        await call.message.answer(
            f"{tr('💠 فاکتور پرداخت')} «{gw_row['name']}» {tr('ساخته شد. روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن.')}\n"
            "به‌محض تایید پرداخت توسط درگاه، کانفیگ شما به‌صورت خودکار ساخته می‌شود.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["invoice_url"]),
            ]]),
        )

    @router.message(CustomConfigFlow.waiting_receipt, F.photo | F.document)
    async def receive_custom_config_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order or order["status"] != "pending":
            await message.answer(db.get_text('handlers_user.auto_32ccba24', 'سفارش معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return

        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_order_receipt, order_id, file_id, receipt_type))
        await _notify_admins_of_order(
            bot, order_id, receipt_file_id=file_id, receipt_type=receipt_type
        )
        await message.answer(
            db.get_text('handlers_user.auto_3c5b40fb', '✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، کانفیگ شخصی شما ساخته و ارسال خواهد شد.'),
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        await state.clear()

    @router.message(CustomConfigFlow.waiting_receipt)
    async def custom_config_receipt_wrong_type(message: Message):
        await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))

    # -----------------------------------------------------------------------
    # کانفیگ تست
    # -----------------------------------------------------------------------

    async def _send_test_success_message(message: Message, plan_name: str = "", amount: str = "", username: str = "") -> None:
        template = (await asyncio.to_thread(db.get_setting, "test_success_message", "")) or ""
        if not template.strip():
            return
        try:
            text = template.format(plan_name=plan_name or "", amount=amount or "", username=username or "")
        except (KeyError, ValueError):
            text = template
        try:
            await message.answer(text)
        except Exception:
            # پیام سفارشی نباید باعث شکست تحویل کانفیگ تست شود.
            pass

    async def _send_test_config_link(message: Message, link: str, prefix: str) -> None:
        """ارسال لینک اشتراک کانفیگ تست و کانفیگ‌های تکی داخلش، هرکدام طبق تنظیمات
        deliver_sub_link_enabled / deliver_individual_configs_enabled فعال/غیرفعال می‌شود."""
        sub_link_on = (await asyncio.to_thread(db.get_setting, "deliver_sub_link_enabled", "1")) != "0"
        if sub_link_on:
            await message.answer(f"{prefix}\n\n`{link}`", parse_mode="Markdown")

        individual_on = (await asyncio.to_thread(db.get_setting, "deliver_individual_configs_enabled", "1")) != "0"
        if individual_on and link.startswith(("http://", "https://")):
            try:
                individual_links = await fetch_individual_links(link)
            except Exception:
                individual_links = []
            if individual_links:
                await send_individual_configs(message.bot, message.from_user.id, individual_links)

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_test"), tr(db.get_setting("btn_test")))))
    async def get_test_config(message: Message):
        if (await asyncio.to_thread(db.get_setting, "test_enabled", "1")) != "1":
            await message.answer(db.get_text('handlers_user.auto_e61183a5', 'در حال حاضر امکان دریافت کانفیگ تست غیرفعال است.'))
            return

        user = (await asyncio.to_thread(db.get_user, message.from_user.id))
        if user and user["test_used"] >= MAX_TEST_PER_USER:
            await message.answer(db.get_text('handlers_user.auto_6aacb1a2', 'شما قبلاً کانفیگ تست خود را دریافت کرده\u200cاید. هر کاربر فقط یک بار مجاز به دریافت کانفیگ تست است.'))
            return

        plans = (await asyncio.to_thread(db.get_test_config_plans, True))
        if plans:
            if len(plans) == 1:
                await _deliver_test_plan(message, plans[0])
            else:
                await message.answer(
                    db.get_text('handlers_user.auto_c158894a', '🧪 کدام مدل کانفیگ تست را می\u200cخواهید؟'), reply_markup=kb.test_plan_pick_kb(plans)
                )
            return

        if not full_access_bot:
            await message.answer(db.get_text('handlers_user.auto_ef5b3624', 'در حال حاضر هیچ پلن کانفیگ تستی تعریف نشده است؛ با پشتیبانی تماس بگیرید.'))
            return

        # هیچ پلنی تعریف نشده: سازگاری با نصب‌های خیلی قدیمی که هنوز فقط بانک لینک دستی دارند
        # رفع باگ ریس‌کاندیشن: قبلاً اینجا اول take_unused_test_config صدا زده می‌شد
        # و بعد mark_test_used - بین این دو هیچ قفلی نبود، پس چند کلیک/ریکوئست
        # همزمان از یک کاربر می‌توانستند همگی از چک بالای تابع (test_used هنوز
        # صفر) رد شوند و هرکدام یک کانفیگ از بانک لینک بگیرند. حالا سهمیه *قبل*
        # از برداشتن کانفیگ با یک UPDATE اتمیک رزرو می‌شود.
        if not (await asyncio.to_thread(db.try_reserve_test_slot, message.from_user.id, MAX_TEST_PER_USER)):
            await message.answer(db.get_text('handlers_user.auto_6aacb1a2', 'شما قبلاً کانفیگ تست خود را دریافت کرده\u200cاید. هر کاربر فقط یک بار مجاز به دریافت کانفیگ تست است.'))
            return

        result = (await asyncio.to_thread(db.take_unused_test_config, message.from_user.id))
        if not result:
            # موجودی بانک لینک تمام شده - سهمیه‌ی رزروشده باید برگردد چون کانفیگی
            # تحویل داده نشد، وگرنه کاربر بدون گرفتن هیچ کانفیگی «مصرف‌شده» می‌ماند.
            (await asyncio.to_thread(db.release_test_slot, message.from_user.id))
            await message.answer(db.get_text('handlers_user.auto_5511df87', 'متاسفانه موجودی کانفیگ تست تمام شده است. لطفاً بعداً مراجعه کنید.'))
            return

        await _send_test_config_link(message, result['link'], "🧪 کانفیگ تست شما:")
        await _send_test_success_message(message, username=result.get("username", ""))
        await report_router.notify_test_config(
            message.bot, db, message.from_user.id, message.from_user.full_name, message.from_user.username,
            "📦 از بانک لینک دستی",
        )

    async def _deliver_test_plan(message: Message, plan) -> None:
        # رفع باگ ریس‌کاندیشن: قبلاً اینجا فقط یک SELECT ساده (get_user) چک
        # می‌شد و mark_test_used فقط *بعد* از ساخت واقعی کانفیگ روی پنل صدا زده
        # می‌شد - یعنی بین چک و مصرف، کل زمانِ تماس با پنل (که می‌تواند طول
        # بکشد) بدون قفل بود. چند درخواست همزمان از همین دکمه (دبل‌تپ، یا چند
        # ریکوئست موازی از مینی‌اپ) همه از همان چک اولیه رد می‌شدند و هرکدام
        # واقعاً یک کانفیگ تست می‌ساختند (و در بات‌های نمایندگی، هرکدام واقعاً
        # از اعتبار حجمی نماینده کم می‌کردند). حالا سهمیه با یک UPDATE اتمیک
        # *قبل* از تماس با پنل رزرو می‌شود؛ اگر ساخت کانفیگ شکست بخورد، سهمیه
        # با release_test_slot برمی‌گردد تا کاربر واقعاً بتواند دوباره تلاش کند.
        if not (await asyncio.to_thread(db.try_reserve_test_slot, message.from_user.id, MAX_TEST_PER_USER)):
            await message.answer(db.get_text('handlers_user.auto_6aacb1a2', 'شما قبلاً کانفیگ تست خود را دریافت کرده\u200cاید. هر کاربر فقط یک بار مجاز به دریافت کانفیگ تست است.'))
            return

        if not full_access_bot:
            # نمایندگی سطح محدود: همیشه از پنل اعتباری خودش و اعتبار حجمی‌اش ساخته می‌شود
            try:
                result = await provision_test_config(db, plan, user_id=message.from_user.id)
            except ProvisionError as e:
                (await asyncio.to_thread(db.release_test_slot, message.from_user.id))
                await message.answer(f"⛔️ {e}")
                return
        else:
            try:
                result = await provision_test_plan(db, plan, user_id=message.from_user.id)
            except TestPlanProvisionError as e:
                (await asyncio.to_thread(db.release_test_slot, message.from_user.id))
                await message.answer(f"⛔️ {e}")
                return

        await _send_test_config_link(
            message, result['subscription_url'],
            f"🧪 کانفیگ تست شما ({plan['name']} - {format_plan_amount(plan)}):",
        )
        await _send_test_success_message(
            message,
            plan_name=plan.get("name", ""),
            amount=format_plan_amount(plan),
            username=result.get("username", ""),
        )
        await report_router.notify_test_config(
            message.bot, db, message.from_user.id, message.from_user.full_name, message.from_user.username,
            f"📦 {escape_html(plan['name'])} - {escape_html(format_plan_amount(plan))}\n"
            f"🔑 <code>{escape_html(result.get('username') or '')}</code>",
        )

    @router.callback_query(F.data.startswith("user_test_plan:"))
    async def cb_user_test_plan_pick(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "test_enabled", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_e61183a5', 'در حال حاضر امکان دریافت کانفیگ تست غیرفعال است.'), show_alert=True)
            return
        plan_id = int(call.data.split(":", 1)[1])
        plan = (await asyncio.to_thread(db.get_test_config_plan, plan_id))
        if not plan or not plan["is_active"]:
            await call.answer(db.get_text('handlers_user.auto_c6a86863', 'این پلن دیگر در دسترس نیست.'), show_alert=True)
            return
        await call.message.delete()
        await _deliver_test_plan(call.message.model_copy(update={"from_user": call.from_user}), plan)
        await call.answer()

    # -----------------------------------------------------------------------
    # پنل نمایندگی (ساخت کانفیگ از استخر حجم بدون پرداخت جداگانه)
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_reseller_panel", "🧑‍💼 پنل نمایندگی"), tr(db.get_setting("btn_reseller_panel", "🧑‍💼 پنل نمایندگی")))))
    async def reseller_panel_open(message: Message, state: FSMContext):
        if not (await asyncio.to_thread(db.is_reseller, message.from_user.id)):
            return
        await state.clear()
        credit = (await asyncio.to_thread(reseller_backend.get_reseller_credit, message.from_user.id))
        supply = await asyncio.to_thread(reseller_backend.get_reseller_supply, message.from_user.id)
        inventory = await asyncio.to_thread(reseller_backend.get_reseller_product_inventory, message.from_user.id)
        fixed = [dict(x) for x in inventory if int(x["qty_remaining"]) > 0]
        if supply["model"] == "fixed_product" or fixed:
            lines = ["🧑‍💼 پنل نمایندگی", "", "📦 موجودی محصولات شما:"]
            if fixed:
                lines += [f"• {x['name']} — {x['qty_remaining']:,} عدد" for x in fixed]
            else:
                lines.append("• موجودی محصولی ندارید.")
            lines += ["", "برای ساخت کانفیگ، روی محصول موردنظر بزن."]
            await message.answer("\n".join(lines), reply_markup=kb.reseller_panel_kb(fixed))
        else:
            await message.answer(
                tr(f"🧑‍💼 پنل نمایندگی\n\n📦 اعتبار باقی‌مانده: {credit:,} گیگابایت\n\n"
                f"می‌تونی از این اعتبار مستقیم کانفیگ بسازی."),
                reply_markup=kb.reseller_panel_kb(),
            )

    @router.callback_query(F.data == "reseller_stats")
    async def cb_reseller_stats(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_reseller, call.from_user.id)):
            await call.answer(tr("دسترسی نداری."), show_alert=True)
            return
        stats = await asyncio.to_thread(db.get_reseller_overview_stats)
        await call.message.answer(
            tr("📊 آمار کلی نمایندگی\n\n"
            f"👥 کاربران: {stats['users']:,}\n"
            f"🛒 خریداران: {stats['buyers']:,}\n"
            f"🧪 اکانت تست: {stats['test_accounts']:,}\n"
            f"📦 تعداد فروش: {stats['sales']:,}\n"
            f"💰 جمع فروش: {stats['revenue']:,} تومان")
        )
        await call.answer()

    @router.callback_query(F.data.startswith("reseller_fixed:"))
    async def cb_reseller_fixed_product(call: CallbackQuery, state: FSMContext):
        if not (await asyncio.to_thread(db.is_reseller, call.from_user.id)):
            await call.answer(db.get_text('handlers_user.auto_c5ac93f4', 'دسترسی نداری.'), show_alert=True); return
        try:
            product_id = int(call.data.split(":", 1)[1])
        except Exception:
            await call.answer(db.get_text('handlers_user.auto_2a726be6', 'محصول نامعتبر است.'), show_alert=True); return
        inventory = await asyncio.to_thread(reseller_backend.get_reseller_product_inventory, call.from_user.id)
        item = next((dict(x) for x in inventory if int(x["product_id"]) == product_id), None)
        if not item or int(item["qty_remaining"]) < 1:
            await call.answer(db.get_text('handlers_user.auto_ed50928c', 'موجودی این محصول تمام شده است.'), show_alert=True); return
        # برای محصول آماده، خودِ محصول می‌تواند پنل ساخت کانفیگ داشته باشد؛
        # بنابراین نبودن reseller_panel_id نباید جلوی ساخت کانفیگ را بگیرد.
        # انتخاب نهایی پنل داخل provision_reseller_fixed_product انجام می‌شود
        # تا همان منطق fallback در همه مسیرها یکسان باشد.
        server = await asyncio.to_thread(reseller_backend.get_reseller_panel, call.from_user.id)
        if not server or not server["is_active"]:
            product_server_id = item.get("provision_server_id")
            if product_server_id:
                candidate = await asyncio.to_thread(reseller_backend.get_panel_server, product_server_id)
                if candidate and candidate["is_active"]:
                    server = candidate
        if not server or not server["is_active"]:
            await call.answer(db.get_text('handlers_user.auto_40732a42', 'برای این محصول هیچ پنل فعالی برای ساخت کانفیگ پیدا نشد.'), show_alert=True); return
        await state.clear(); await state.set_state(ResellerFlow.waiting_fixed_product_username)
        await state.update_data(fixed_product_id=product_id, panel_server_id=server["id"])
        await call.answer()
        await call.message.answer(
            f"{tr('📦 محصول:')} {item['name']}\n"
            f"موجودی: {item['qty_remaining']:,} عدد\n\n"
            "یک نام کاربری برای کانفیگ وارد کن یا از دکمه نام تصادفی استفاده کن.",
            reply_markup=kb.custom_config_username_kb(),
        )

    @router.callback_query(F.data == "custom_config_random_username", ResellerFlow.waiting_fixed_product_username)
    async def cb_reseller_fixed_random_username(call: CallbackQuery, state: FSMContext):
        prefix = await asyncio.to_thread(db.get_custom_config_prefix)
        for _ in range(10):
            suffix = "r" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
            candidate = f"{prefix}-{suffix}" if prefix else suffix
            if not (await asyncio.to_thread(db.is_custom_username_taken, candidate)):
                break
        data = await state.get_data()
        product_id = int(data["fixed_product_id"])
        # همان پنلی که هنگام انتخاب محصول تعیین شد (ممکن است fallback محصول باشد)
        server = None
        panel_server_id = data.get("panel_server_id")
        if panel_server_id:
            server = await asyncio.to_thread(reseller_backend.get_panel_server, int(panel_server_id))
        if not server or not server["is_active"]:
            server = await asyncio.to_thread(reseller_backend.get_reseller_panel, call.from_user.id)
        try:
            result = (await provision_reseller_fixed_product(reseller_backend, call.from_user.id, product_id, 1, username_prefix=prefix or "r", username=candidate))[0]
        except ProvisionError as e:
            await state.clear(); await call.answer(str(e), show_alert=True); return
        try:
            local_panel_id = await asyncio.to_thread(db.get_or_create_mirror_panel_server, server)
            await asyncio.to_thread(db.add_custom_config, call.from_user.id, local_panel_id, result["username"], result["volume_gb"], result["duration_days"], result["subscription_url"], source="reseller", reseller_product_id=product_id)
        except Exception:
            try:
                server=await asyncio.to_thread(reseller_backend.get_panel_server, data["panel_server_id"])
                if server:
                    provider=get_provider(server); await provider.delete_user(result["username"])
            except Exception: pass
            await asyncio.to_thread(reseller_backend.grant_reseller_product_credit, call.from_user.id, product_id, 1, reason="بازگشت موجودی به‌دلیل خطای ثبت کانفیگ")
            await state.clear(); await call.answer(db.get_text('handlers_user.auto_545dc373', 'ثبت کانفیگ ناموفق بود.'), show_alert=True); return
        remaining=await asyncio.to_thread(reseller_backend.get_reseller_product_credit, call.from_user.id, product_id)
        await state.clear(); await call.answer(db.get_text('handlers_user.auto_d056c989', 'کانفیگ ساخته شد.'))
        await call.message.answer(tr(f"✅ کانفیگ ساخته شد!\n\n🛠 نام کاربری: {escape_md(result['username'])}\n📦 محصول: {escape_md(result['product_name'])}\n📶 حجم: {result['volume_gb']} گیگ | ⏳ مدت: {result['duration_days']} روز\n\n`{result['subscription_url']}`\n\n📦 موجودی باقی‌مانده: {remaining:,} عدد"), parse_mode="Markdown", reply_markup=kb.menu_for_user(db, call.from_user.id, is_main_bot))

    @router.message(ResellerFlow.waiting_fixed_product_username)
    async def reseller_fixed_product_username(message: Message, state: FSMContext):
        suffix=(message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", suffix):
            await message.answer(db.get_text('handlers_user.auto_b8c82218', '❌ نام کاربری نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.')); return
        prefix=await asyncio.to_thread(db.get_custom_config_prefix)
        username=f"{prefix}-{suffix}" if prefix else suffix
        if await asyncio.to_thread(db.is_custom_username_taken, username):
            await message.answer(db.get_text('handlers_user.auto_d4197028', '❌ این نام کاربری قبلاً استفاده شده است.')); return
        data=await state.get_data()
        product_id=int(data["fixed_product_id"])
        # پنل واقعی انتخاب‌شده در مرحله قبل را نگه می‌داریم؛ اگر پنل نماینده
        # نداشتیم، این مقدار همان provision_server_id محصول است.
        server=None
        panel_server_id=data.get("panel_server_id")
        if panel_server_id:
            server=await asyncio.to_thread(reseller_backend.get_panel_server, int(panel_server_id))
        if not server or not server["is_active"]:
            server=await asyncio.to_thread(reseller_backend.get_reseller_panel, message.from_user.id)
        try:
            result=(await provision_reseller_fixed_product(reseller_backend, message.from_user.id, product_id, 1, username_prefix=prefix or "r", username=username))[0]
        except ProvisionError as e:
            await state.clear(); await message.answer(f"⛔️ {e}"); return
        try:
            local_panel_id = await asyncio.to_thread(db.get_or_create_mirror_panel_server, server)
            await asyncio.to_thread(db.add_custom_config, message.from_user.id, local_panel_id, result["username"], result["volume_gb"], result["duration_days"], result["subscription_url"], source="reseller", reseller_product_id=product_id)
        except Exception:
            # در صورت شکست ثبت رکورد، موجودی برگردانده و اکانت پنل حذف می‌شود.
            try:
                server=await asyncio.to_thread(reseller_backend.get_panel_server, data["panel_server_id"])
                if server:
                    provider=get_provider(server); await provider.delete_user(result["username"])
            except Exception: pass
            await asyncio.to_thread(reseller_backend.grant_reseller_product_credit, message.from_user.id, product_id, 1, reason="بازگشت موجودی به‌دلیل خطای ثبت کانفیگ")
            await state.clear(); await message.answer(db.get_text('handlers_user.auto_b176a624', '⛔️ ثبت کانفیگ ناموفق بود؛ موجودی شما برگشت داده شد.')); return
        remaining=await asyncio.to_thread(reseller_backend.get_reseller_product_credit, message.from_user.id, product_id)
        await state.clear()
        await message.answer(
            tr(f"✅ کانفیگ محصول آماده ساخته شد!\n\n🛠 نام کاربری: {escape_md(result['username'])}\n"
            f"📦 محصول: {escape_md(result['product_name'])}\n"
            f"📶 حجم: {result['volume_gb']} گیگ | ⏳ مدت: {result['duration_days']} روز\n\n`{result['subscription_url']}`\n\n"
            f"📦 موجودی باقی‌مانده: {remaining:,} عدد"), parse_mode="Markdown",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )

    @router.callback_query(F.data == "reseller_new_config")
    async def cb_reseller_new_config(call: CallbackQuery, state: FSMContext):
        if not (await asyncio.to_thread(db.is_reseller, call.from_user.id)):
            await call.answer(db.get_text('handlers_user.auto_c5ac93f4', 'دسترسی نداری.'), show_alert=True)
            return
        credit = (await asyncio.to_thread(reseller_backend.get_reseller_credit, call.from_user.id))
        if credit <= 0:
            await call.answer(db.get_text('handlers_user.auto_566e9dd5', 'اعتبار شما کافی نیست. با ادمین تماس بگیر.'), show_alert=True)
            return
        server = (await asyncio.to_thread(reseller_backend.get_reseller_panel, call.from_user.id))
        if not server:
            await call.answer(db.get_text('handlers_user.auto_7ddb367e', 'هنوز سروری برای نمایندگی توسط ادمین تنظیم نشده.'), show_alert=True)
            return
        await state.set_state(ResellerFlow.waiting_username)
        await state.update_data(panel_server_id=server["id"])
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        await call.answer()
        if prefix:
            await call.message.answer(
                tr(f"نام هر کانفیگ با پیش‌وند ثابت «{prefix}-» شروع می‌شود. فقط ادامه‌ی نام (بعد از خط تیره) را "
                "وارد کن، یا از دکمه‌ی زیر یک نام تصادفی بگیر.\n"
                "فقط حروف انگلیسی، عدد و آندرلاین (بین ۳ تا ۲۰ کاراکتر)."),
                reply_markup=kb.custom_config_username_kb(),
            )
        else:
            await call.message.answer(
                db.get_text('handlers_user.auto_90ab8c88', 'یک نام کاربری برای این کانفیگ وارد کن، یا از دکمه\u200cی زیر یک نام تصادفی بگیر.\nفقط حروف انگلیسی، عدد و آندرلاین (بین ۳ تا ۲۰ کاراکتر).'),
                reply_markup=kb.custom_config_username_kb(),
            )

    @router.callback_query(F.data == "custom_config_random_username", ResellerFlow.waiting_username)
    async def cb_reseller_random_username(call: CallbackQuery, state: FSMContext):
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        for _ in range(10):
            suffix = "r" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
            candidate = f"{prefix}-{suffix}" if prefix else suffix
            if not (await asyncio.to_thread(db.is_custom_username_taken, candidate)):
                break
        await call.answer()
        await _reseller_apply_username(call.message, state, candidate)

    @router.message(ResellerFlow.waiting_username)
    async def reseller_receive_username(message: Message, state: FSMContext):
        suffix = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", suffix):
            await message.answer(db.get_text('handlers_user.auto_b8c82218', '❌ نام کاربری نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.'))
            return
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        username = f"{prefix}-{suffix}" if prefix else suffix
        if (await asyncio.to_thread(db.is_custom_username_taken, username)):
            await message.answer(db.get_text('handlers_user.auto_3fa427ee', '❌ این نام کاربری قبلاً استفاده شده. لطفاً نام دیگری انتخاب کنید.'))
            return
        await _reseller_apply_username(message, state, username)

    async def _reseller_apply_username(message: Message, state: FSMContext, username: str):
        credit = (await asyncio.to_thread(db.get_reseller_credit, message.from_user.id))
        await state.update_data(reseller_username=username)
        await state.set_state(ResellerFlow.waiting_volume)
        await message.answer(
            tr(f"✅ نام کاربری: {username}\n\n"
            f"📦 اعتبار باقی‌مانده: {credit:,} گیگابایت\n"
            f"حالا حجم مورد نظر برای این کانفیگ را به گیگابایت وارد کن:"),
            reply_markup=kb.cancel_kb(),
        )

    @router.message(ResellerFlow.waiting_volume)
    async def reseller_receive_volume(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_user.auto_607c61b7', '❌ لطفاً فقط عدد صحیح مثبت وارد کنید.'))
            return
        volume_gb = int(text)
        credit = (await asyncio.to_thread(reseller_backend.get_reseller_credit, message.from_user.id))
        if volume_gb > credit:
            await message.answer(tr(f"❌ اعتبار شما کافی نیست. اعتبار باقی‌مانده: {credit:,} گیگ."))
            return

        data = await state.get_data()
        server = (await asyncio.to_thread(db.get_panel_server, data.get("panel_server_id")))
        if not server or not server["is_active"]:
            await message.answer(db.get_text('handlers_user.auto_b8da1165', '⛔️ سرور نمایندگی دیگر در دسترس نیست.'))
            await state.clear()
            return

        duration_days = (await asyncio.to_thread(db.get_custom_config_settings))["duration_days"]
        provider = get_provider(server)
        try:
            result = await provider.create_user(data["reseller_username"], volume_gb, duration_days)
        except PanelUsernameTakenError:
            await message.answer(db.get_text('handlers_user.auto_69d7d6ca', '❌ این نام کاربری روی پنل تکراری است. دوباره از ابتدا با نام دیگری امتحان کن.'))
            return
        except PanelError as e:
            await message.answer(tr(f"⛔️ خطا در ساخت کانفیگ: {e}"))
            return

        # کسر اتمیک، نه فقط یک UPDATE بدون قید: اگر بین چک بالا و همین لحظه یک
        # مصرف هم‌زمان دیگر (مثلاً یک خرید اتوماتیک از همین نماینده) دقیقاً همین
        # اعتبار را برده باشد، اینجا واقعاً رد می‌شود و اکانت تازه‌ساخته روی پنل هم
        # پاک می‌شود تا یتیم نماند.
        credit_ok = (await asyncio.to_thread(
            reseller_backend.consume_reseller_credit, message.from_user.id, volume_gb,
            reason=f"ساخت کانفیگ «{result.username}»",
        ))
        if not credit_ok:
            try:
                await provider.delete_user(result.username)
            except Exception:
                pass
            await message.answer(db.get_text('handlers_user.auto_7046adde', '❌ اعتبار شما هم\u200cزمان توسط یک ساخت دیگر مصرف شد. دوباره از ابتدا امتحان کن.'))
            return

        try:
            local_panel_id = await asyncio.to_thread(db.get_or_create_mirror_panel_server, server)
            (await asyncio.to_thread(db.add_custom_config,
                message.from_user.id, local_panel_id, result.username, volume_gb, duration_days, result.subscription_url,
                source="reseller",
            ))
        except Exception:
            # اگر ثبت رکورد محلی شکست بخورد، هم اعتبار برگردانده می‌شود هم اکانتِ
            # روی پنل پاک می‌شود؛ وگرنه اعتبار نماینده بی‌دلیل کم شده بود بدون این‌که
            # خودش هیچ رکورد/کانفیگی از آن داشته باشد (اکانت یتیم روی پنل).
            logging.getLogger("handlers_user").exception(
                "ثبت کانفیگ دستی نماینده %s ناموفق بود", message.from_user.id
            )
            (await asyncio.to_thread(
                reseller_backend.adjust_reseller_credit, message.from_user.id, volume_gb,
                reason="بازگشت اعتبار به‌دلیل خطای ثبت کانفیگ",
            ))
            try:
                await provider.delete_user(result.username)
            except Exception:
                pass
            await message.answer(db.get_text('handlers_user.auto_39531c9f', '⛔️ خطایی در ثبت کانفیگ رخ داد؛ اعتبار شما بازگردانده شد. دوباره تلاش کن.'))
            return

        new_credit = (await asyncio.to_thread(reseller_backend.get_reseller_credit, message.from_user.id))
        await state.clear()
        await message.answer(
            tr(f"✅ کانفیگ ساخته شد!\n\n"
            f"🛠 نام کاربری: {escape_md(result.username)}\n"
            f"📶 حجم: {volume_gb} گیگ | ⏳ مدت: {duration_days} روز\n\n"
            f"`{result.subscription_url}`\n\n"
            f"📦 اعتبار باقی‌مانده: {new_credit:,} گیگابایت"),
            parse_mode="Markdown",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)

    async def _account_hub_text(user_tg_id: int) -> str:
        user = (await asyncio.to_thread(db.get_user, user_tg_id))
        username = f"@{escape_md(user['username'])}" if (user and user["username"]) else "—"
        orders = (await asyncio.to_thread(db.get_user_orders, user_tg_id))
        st = await asyncio.to_thread(db.get_wallet_status, user_tg_id)
        credit_line = (
            f"💳 سقف اعتبار: {st['limit']:,} تومان | بدهی: {st['debt']:,} تومان\n"
            if (st["limit"] > 0 or st["debt"] > 0) else ""
        )
        credit_line = tr(credit_line.rstrip("\n")) + "\n" if credit_line else ""
        return (
            tr("🧾 حساب کاربری من") + "\n\n"
            + tr(f"🆔 شناسه کاربری: `{user_tg_id}`") + "\n"
            + tr(f"👤 نام کاربری: {username}") + "\n"
            + tr(f"👛 موجودی کیف پول: {st['balance']:,} تومان") + "\n"
            + credit_line
            + tr(f"📦 تعداد سفارش‌ها: {len(orders)}")
        )

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_my_orders"), tr(db.get_setting("btn_my_orders")))))
    async def my_orders(message: Message):
        text = await _account_hub_text(message.from_user.id)
        await message.answer(text, parse_mode="Markdown", reply_markup=kb.account_hub_kb(db))

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_tutorial"), tr(db.get_setting("btn_tutorial")))))
    async def tutorial_menu_entry(message: Message):
        tutorials = await asyncio.to_thread(db.get_tutorials_for_target, tutorial_hub.GENERAL)
        if not tutorials:
            await message.answer(db.get_text('handlers_user.auto_tut_none', 'فعلاً آموزشی ثبت نشده.'))
            return
        await message.answer(
            tr("📚 یک آموزش را انتخاب کنید:"),
            reply_markup=kb.tutorial_devices_user_kb(tutorials),
        )

    @router.callback_query(F.data == "acct:hub")
    async def cb_account_hub(call: CallbackQuery):
        text = await _account_hub_text(call.from_user.id)
        await _safe_edit(call.message, text, parse_mode="Markdown", reply_markup=kb.account_hub_kb(db))
        await call.answer()

    @router.callback_query(F.data == "acct:language")
    async def cb_account_language(call: CallbackQuery):
        await _safe_edit(
            call.message,
            db.get_text("handlers_user.language.choose", "لطفاً زبان موردنظر را انتخاب کنید:"),
            reply_markup=kb.language_kb(db, back_callback="acct:hub"),
        )
        await call.answer()

    @router.callback_query(F.data == "acct:orders")
    async def cb_account_orders(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "acct_show_orders", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_877cd65e', 'این بخش غیرفعال است.'), show_alert=True)
            return
        await _show_my_orders_list(call.message, call.from_user.id, edit=True)
        await call.answer()

    @router.callback_query(F.data == "acct:referral")
    async def cb_account_referral(call: CallbackQuery, bot: Bot):
        if (await asyncio.to_thread(db.get_setting, "acct_show_referral", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_877cd65e', 'این بخش غیرفعال است.'), show_alert=True)
            return
        await call.answer()
        fake_message = call.message.model_copy(update={"from_user": call.from_user})
        await referral_menu(fake_message, bot)

    @router.callback_query(F.data == "acct:wallet")
    async def cb_account_wallet(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "acct_show_wallet", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_877cd65e', 'این بخش غیرفعال است.'), show_alert=True)
            return
        await call.answer()
        fake_message = call.message.model_copy(update={"from_user": call.from_user})
        await wallet_menu(fake_message)

    @router.callback_query(F.data == "acct:main_menu")
    async def cb_account_back_to_main(call: CallbackQuery):
        await call.answer()
        try:
            await call.message.delete()
        except Exception:
            pass
        await _send_inline_main_menu(call.message, call.from_user.id)

    # -----------------------------------------------------------------------
    # سفارش‌های من (منوی کانفیگ‌ها + امکان حذف کامل هر کانفیگ)
    # -----------------------------------------------------------------------

    _MO_STATUS_MAP = {"pending": "⏳ در انتظار بررسی", "approved": "✅ تایید شده", "rejected": "❌ رد شده"}
    _MO_STATUS_ICON = {"pending": "⏳", "approved": "✅", "rejected": "❌"}

    _PANEL_STATUS_MAP = {
        "active": "🟢 فعال",
        "disabled": "🔴 غیرفعال",
        "limited": "🟡 محدود شده (اتمام حجم)",
        "expired": "🔴 منقضی شده",
        "on_hold": "⏸ در حال انتظار",
    }

    def _fmt_bytes(n: int) -> str:
        n = n or 0
        gb = n / (1024 ** 3)
        if gb >= 1:
            return f"{gb:.2f} گیگابایت"
        return f"{n / (1024 ** 2):.2f} مگابایت"

    def _my_orders_items(user_tg_id: int):
        """هر آیتم یک ردیف/دکمه‌ی جدا در منوست: یک کانفیگ محصول، یک کانفیگ شخصی،
        یا (فقط برای سفارش‌های در انتظار بررسی که هنوز کانفیگی ندارند) خود
        سفارش. سفارش‌های رد‌شده اصلاً نمایش داده نمی‌شوند (کانفیگی برایشان
        ساخته نشده، پس چیزی برای کاربر ندارند).
        در پایان بر اساس تاریخ ثبت (created_at سفارش/کانفیگ شخصی) از جدید به
        قدیم مرتب می‌شود - مستقل از این‌که آیتم از کدام منبع (سفارش عادی یا
        کانفیگ شخصی) آمده باشد.
        نکته‌ی مهم درباره‌ی محصولات is_auto_provision (اعتبار حجمی نماینده/تحویل
        آنی): این‌ها به‌جای بانک کانفیگ، مستقیماً یک ردیف در custom_configs
        می‌سازند (تا حجم/انقضا قابل پیگیری باشد) - یعنی سفارششان هیچ‌وقت
        configs مرتبط ندارد. بدون این استثنا، همان یک خرید هم به‌صورت آیتم
        «سفارش» ناقص (بدون لینک/حجم، چون configs خالی است) و هم به‌صورت آیتم
        «کانفیگ شخصی» کامل (از حلقه‌ی custom_configs پایین‌تر) دوبار نمایش داده
        می‌شد."""
        custom_order_ids = {cc["order_id"] for cc in db.get_custom_configs_for_user(user_tg_id) if cc["order_id"]}
        items = []
        for o in db.get_user_orders(user_tg_id):
            if o["status"] == "rejected":
                continue
            if o["is_renewal"]:
                # سفارش‌های «تمدید سرویس» فقط یک رکورد داخلی برای پرداخت‌اند
                # (product_id=0 سنتینل، بدون کانفیگ/محصول واقعی مال خودشان)؛
                # نتیجه‌ی تمدید همین حالا روی خودِ سرویس هدف (renewal_target_*)
                # اعمال شده و همان‌جا با حجم/انقضای به‌روزشده دیده می‌شود، پس
                # اینجا دوباره به‌عنوان یک آیتم جدا و ناقص («نامشخص») نشان داده
                # نمی‌شود.
                continue
            order_ts = o["created_at"] or ""
            if o["is_custom_config"]:
                # نسخه‌ی تاییدشده‌ی کانفیگ شخصی از جدول custom_configs (پایین‌تر)
                # با جزئیات کامل نمایش داده می‌شود؛ اینجا فقط سفارش‌های در
                # انتظار (که هنوز کانفیگی ندارند) را نشان می‌دهیم.
                if o["status"] != "approved":
                    label = (
                        f"{_MO_STATUS_ICON.get(o['status'], '')} #{o['id']} "
                        f"کانفیگ شخصی «{o['custom_username']}» ({o['custom_volume_gb']} گیگ)"
                    )
                    items.append({"cb_id": f"o{o['id']}", "kind": "order", "label": label, "order": o, "_ts": order_ts})
                continue
            product = db.get_product(o["product_id"])
            pname = product["name"] if product else "نامشخص"
            qty = o["quantity"] or 1
            base_label = f"{_MO_STATUS_ICON.get(o['status'], '')} #{o['id']} {pname}" + (f" ×{qty}" if qty > 1 else "")
            if o["status"] == "approved":
                configs = db.get_order_configs(o["id"])
                if not configs and o["config_id"]:
                    cfg = db.get_config_by_id(o["config_id"])
                    configs = [cfg] if cfg else []
                had_configs = bool(configs)
                # کانفیگ‌هایی که ادمین غیرفعال کرده در «سفارش‌های من» نشان داده
                # نمی‌شوند (لینک دیگر متعلق به کاربر شناخته نمی‌شود).
                configs = [c for c in configs if not (("is_disabled" in c.keys()) and c["is_disabled"])]
                if had_configs and not configs:
                    continue
                if configs:
                    for i, cfg in enumerate(configs, start=1):
                        label = base_label + (f" ({i}/{len(configs)})" if len(configs) > 1 else "")
                        items.append({
                            "cb_id": f"c{cfg['id']}", "kind": "config", "label": label,
                            "order": o, "product_name": pname, "config": cfg, "_ts": order_ts,
                        })
                    continue
            if o["status"] == "approved" and o["id"] in custom_order_ids:
                # این سفارش (محصول is_auto_provision) از قبل با یک ردیف کامل در
                # custom_configs (پایین‌تر) نمایش داده می‌شود؛ آیتم ناقصِ سفارش
                # را دوباره اضافه نکن.
                continue
            items.append({
                "cb_id": f"o{o['id']}", "kind": "order", "label": base_label, "order": o,
                "product_name": pname, "_ts": order_ts,
            })

        for cc in db.get_custom_configs_for_user(user_tg_id):
            label_name = cc["display_name"] or cc["username"]
            if cc["source"] == "test":
                label = f"🧪 «{label_name}» (تست، {cc['volume_gb']:g} گیگ / {cc['duration_days']:g} روز)"
            else:
                label = f"🛠 «{label_name}» ({cc['volume_gb']} گیگ / {cc['duration_days']} روز)"
            items.append({"cb_id": f"x{cc['id']}", "kind": "custom", "label": label, "custom": cc, "_ts": cc["created_at"] or ""})

        items.sort(key=lambda it: it["_ts"], reverse=True)
        return items

    def _find_my_orders_item(user_tg_id: int, cb_id: str):
        for it in _my_orders_items(user_tg_id):
            if it["cb_id"] == cb_id:
                return it
        return None

    def _svc_kb_kwargs(item) -> dict:
        if item["kind"] != "custom":
            return {}
        cc = item["custom"]
        return {
            "enabled": (cc["enabled"] if "enabled" in cc.keys() else 1) == 1,
            "auto_renew": (cc["auto_renew"] if "auto_renew" in cc.keys() else 0) == 1,
            "is_test": cc["source"] == "test",
            "can_add_users": ul.service_upgrade_info(db, cc) is not None,
        }

    def _is_test_item(item) -> bool:
        return item["kind"] == "custom" and item["custom"]["source"] == "test"

    def _item_sub_link(item) -> str:
        """لینک ساب یک آیتم (برای QR/بروزرسانی/کانفیگ‌های تکی) - یا رشته‌ی
        خالی اگر آیتم اصلاً لینکی نداشته باشد."""
        if item["kind"] == "config":
            return item["config"]["link"] or ""
        if item["kind"] == "custom":
            return item["custom"]["subscription_url"] or ""
        return ""

    def _item_has_individual_links(item) -> bool:
        link = _item_sub_link(item)
        return str(link).startswith(("http://", "https://"))

    async def _my_orders_item_text(item) -> str:
        kind = item["kind"]
        if kind == "config":
            cfg, o, pname = item["config"], item["order"], item["product_name"]
            text = f"📦 محصول: {escape_md(pname)} (سفارش #{o['id']})\n"
            text += f"🗓 تاریخ خرید: {to_jalali_str(o['created_at'], with_time=True)}\n"
            if cfg["expires_at"]:
                text += f"⏳ انقضا: {to_jalali_str(cfg['expires_at'], with_time=True)}\n"
            text += f"🔗 `{cfg['link']}`\n"
            info = await fetch_sub_info(cfg["link"])
            text += f"\n{format_sub_info_fa(info)}"
            if str(cfg["link"]).startswith(("http://", "https://")):
                text += "\n\n📋 برای دیدن کانفیگ‌های تکی این لینک، دکمه‌ی «کانفیگ‌های تکی» پایین را بزنید."
            return text
        if kind == "custom":
            cc = item["custom"]
            sub_url = cc["subscription_url"]
            server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
            if server and server["is_active"]:
                try:
                    provider = get_provider(server)
                    fresh = await provider.get_user(cc["username"])
                    if fresh.subscription_url:
                        if fresh.subscription_url != sub_url:
                            (await asyncio.to_thread(
                                db.update_custom_config_subscription_url, cc["id"], fresh.subscription_url,
                            ))
                        sub_url = fresh.subscription_url
                except Exception:
                    # پنل در دسترس نبود، تایم‌اوت داد یا کاربر پیدا نشد؛ به‌جای کرش‌کردن
                    # کل صفحه (که باعث می‌شود چیزی برای کاربر نمایش داده نشود)،
                    # همان لینک ذخیره‌شده (احتمالاً قدیمی) نشان داده می‌شود.
                    logging.getLogger("handlers_user").exception(
                        "خواندن اطلاعات تازه از پنل برای «%s» ناموفق بود؛ لینک ذخیره‌شده نمایش داده می‌شود.",
                        cc["username"],
                    )
            text = (
                f"🛠 کانفیگ شخصی «{escape_md(cc['display_name'] or cc['username'])}»\n"
                f"📶 حجم: {cc['volume_gb']} گیگ | ⏳ مدت: {cc['duration_days']} روز\n"
                f"وضعیت: {'🟢 فعال' if (cc['enabled'] if 'enabled' in cc.keys() else 1) == 1 else '🔴 غیرفعال'} | "
                f"تمدید خودکار: {'🟢 فعال' if (cc['auto_renew'] if 'auto_renew' in cc.keys() else 0) == 1 else '🔴 غیرفعال'}\n"
                f"🗓 تاریخ خرید: {to_jalali_str(cc['created_at'], with_time=True)}\n"
            )
            if cc["user_limit"]:
                text += f"👥 کاربر همزمان: {cc['user_limit']}\n"
            if cc["start_on_first_use"] and not cc["expires_at"]:
                text += "⏳ انقضا: شروع از اولین اتصال\n"
            elif cc["expires_at"]:
                text += f"📅 انقضا: {to_jalali_str(cc['expires_at'], with_time=True)}\n"
            if sub_url:
                text += f"🔗 `{sub_url}`\n"
                info = await fetch_sub_info(sub_url)
                text += f"\n{format_sub_info_fa(info)}"
                if str(sub_url).startswith(("http://", "https://")):
                    text += "\n\n📋 برای دیدن کانفیگ‌های تکی این لینک، دکمه‌ی «کانفیگ‌های تکی» پایین را بزنید."
            return text
        # kind == "order": سفارشی بدون کانفیگ فعلی (در انتظار بررسی/رد‌شده)
        o = item["order"]
        pname = item.get("product_name") or f"کانفیگ شخصی «{o['custom_username']}» ({o['custom_volume_gb']} گیگ)"
        return f"📦 سفارش #{o['id']} | {escape_md(pname)}\nوضعیت: {_MO_STATUS_MAP.get(o['status'], o['status'])}"

    async def _show_my_orders_list(target, user_tg_id: int, edit: bool):
        items = _my_orders_items(user_tg_id)
        if not items:
            text = "شما تاکنون سفارشی ثبت نکرده‌اید."
            if edit:
                await _safe_edit(target, text)
            else:
                await target.answer(text)
            return
        text = "📦 سفارش‌ها و کانفیگ‌های شما\n\nیکی از موارد زیر را برای مشاهده‌ی جزئیات انتخاب کنید:"
        markup = kb.my_orders_menu_kb(items)
        if edit:
            await _safe_edit(target, text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "mo_back")
    async def cb_my_orders_back(call: CallbackQuery):
        await _show_my_orders_list(call.message, call.from_user.id, edit=True)
        await call.answer()

    @router.callback_query(F.data.startswith("mo_v:"))
    async def cb_my_orders_view(call: CallbackQuery):
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item:
            await call.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            await _show_my_orders_list(call.message, call.from_user.id, edit=True)
            return
        await call.answer()
        try:
            text = await _my_orders_item_text(item)
        except Exception:
            logging.getLogger("handlers_user").exception(
                "ساخت متن جزئیات سرویس (cb_id=%s) برای کاربر %s ناموفق بود.", cb_id, call.from_user.id,
            )
            await _safe_edit(
                call.message,
                db.get_text('handlers_user.auto_1fb3c0b2', '⚠️ در دریافت اطلاعات این سرویس خطایی رخ داد (احتمالاً پنل موقتاً در دسترس نیست).\nلطفاً چند لحظه دیگر دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.'),
                reply_markup=kb.my_order_error_back_kb(),
            )
            return
        deletable = item["kind"] in ("config", "custom")
        show_links = _item_has_individual_links(item)
        markup = kb.service_detail_kb(db, cb_id, item["kind"], deletable, show_links, **_svc_kb_kwargs(item))
        if len(text) > 4000:
            text = text[:3950] + "\n\n… (فهرست کوتاه شد؛ تعداد کانفیگ‌ها زیاد است)"
        await _safe_edit(call.message, text, parse_mode="Markdown", reply_markup=markup)

    @router.callback_query(F.data.startswith("mo_refresh:"))
    async def cb_my_orders_refresh(call: CallbackQuery):
        """دکمه‌ی «بروزرسانی کانفیگ». چون خودِ صفحه‌ی جزئیات هر بار با اطلاعات
        زنده (fetch_sub_info) ساخته می‌شود، ممکن است متن با قبل فرقی نکند و
        ویرایش پیام در تلگرام بی‌اثر به‌نظر برسد؛ برای همین همیشه یک پیام
        تاییدیه‌ی جدا (toast) هم نشان می‌دهیم تا کاربر مطمئن شود کاری انجام شد."""
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item:
            await call.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            await _show_my_orders_list(call.message, call.from_user.id, edit=True)
            return
        try:
            text = await _my_orders_item_text(item)
        except Exception:
            logging.getLogger("handlers_user").exception(
                "بروزرسانی اطلاعات سرویس (cb_id=%s) برای کاربر %s ناموفق بود.", cb_id, call.from_user.id,
            )
            await call.answer(db.get_text('handlers_user.auto_c4d5d37d', '⚠️ بروزرسانی ناموفق بود؛ کمی بعد دوباره تلاش کنید.'), show_alert=True)
            return
        deletable = item["kind"] in ("config", "custom")
        show_links = _item_has_individual_links(item)
        markup = kb.service_detail_kb(db, cb_id, item["kind"], deletable, show_links, **_svc_kb_kwargs(item))
        if len(text) > 4000:
            text = text[:3950] + "\n\n… (فهرست کوتاه شد؛ تعداد کانفیگ‌ها زیاد است)"
        await _safe_edit(call.message, text, parse_mode="Markdown", reply_markup=markup)
        await call.answer(db.get_text('handlers_user.auto_dcd3a0df', '✅ اطلاعات بروزرسانی شد.'))

    @router.callback_query(F.data.startswith("svc_inquiry:"))
    async def cb_service_inquiry(call: CallbackQuery):
        """دکمه‌ی «🔍 استعلام»: فقط برای سرویس‌های kind='custom' (متصل به یک پنل
        VPN واقعی) نمایش داده می‌شود. برخلاف متن پیش‌فرض صفحه‌ی جزئیات که فقط
        یک خلاصه‌ی ترکیبی از fetch_sub_info نشان می‌دهد، این صفحه هر فیلد
        (وضعیت/آپلود/دانلود/حجم کل/حجم باقی‌مانده/تاریخ اتمام/روز باقی‌مانده)
        را جدا و مطابق کارتی که ادمین در پنل‌های دیگر (مثلاً مینی‌اپ) می‌بیند
        نمایش می‌دهد."""
        if (await asyncio.to_thread(db.get_setting, "svc_show_inquiry", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            await _show_my_orders_list(call.message, call.from_user.id, edit=True)
            return
        cc = item["custom"]
        if not cc["panel_server_id"] or not cc["subscription_url"]:
            await call.answer(db.get_text('handlers_user.auto_304a0c67', 'این سرویس به پنل VPN متصل نیست.'), show_alert=True)
            return
        await call.answer()

        config_name = cc["display_name"] or cc["username"]
        status_line = "❔ نامشخص"
        online_line = "❔ نامشخص"
        server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
        if server and server["is_active"]:
            provider = get_provider(server)
            try:
                usage = await provider.get_user_usage(cc["username"])
                status_line = _PANEL_STATUS_MAP.get(usage.get("status"), usage.get("status") or "❔ نامشخص")
            except Exception:
                logging.getLogger("handlers_user").exception(
                    "استعلام وضعیت سرویس «%s» از پنل ناموفق بود.", cc["username"],
                )
            if getattr(provider, "supports_online_status", False):
                try:
                    online_line = "🟢 آنلاین (همین الان متصل است)" if await provider.is_client_online(cc["username"]) else "⚪️ آفلاین (الان متصل نیست)"
                except Exception:
                    logging.getLogger("handlers_user").exception(
                        "استعلام وضعیت آنلاین سرویس «%s» از پنل ناموفق بود.", cc["username"],
                    )

        info = await fetch_sub_info(cc["subscription_url"])
        if not info.get("ok"):
            text = (
                f"🎫 نام کانفیگ: {config_name}\n"
                f"⚡️ وضعیت: {status_line}\n"
                f"📡 اتصال لحظه‌ای: {online_line}\n\n"
                "⚠️ دریافت اطلاعات مصرف از سرور امکان‌پذیر نبود."
            )
        else:
            upload, download, total = info["upload"], info["download"], info["total"]
            used = upload + download
            if total > 0:
                remaining_line = _fmt_bytes(max(0, total - used))
                total_line = _fmt_bytes(total)
            else:
                remaining_line = "نامحدود"
                total_line = "نامحدود"

            if info["expire"]:
                exp_dt = datetime.fromtimestamp(info["expire"], tz=timezone.utc)
                expire_line = to_jalali_str(exp_dt, with_time=True)
                days_left = max(0, (exp_dt - datetime.now(timezone.utc)).days)
                days_left_line = str(days_left)
            else:
                expire_line = "نامحدود"
                days_left_line = "نامحدود"

            purchase_line = to_jalali_str(cc["created_at"], with_time=True) if cc["created_at"] else "نامشخص"
            text = "📋 مشخصات این لحظه سرویس:"
            fields = [
                ("⚡️ وضعیت", status_line),
                ("📡 اتصال لحظه‌ای", online_line),
                ("🎫 نام کانفیگ", config_name),
                ("⬆️ آپلود", _fmt_bytes(upload)),
                ("⬇️ دانلود", _fmt_bytes(download)),
                ("🔋 حجم کل", total_line),
                ("🪫 حجم باقی‌مانده", remaining_line),
                ("🗓 تاریخ خرید", purchase_line),
                ("📅 تاریخ اتمام", expire_line),
                ("⏳ روز باقی‌مانده", days_left_line),
            ]
            await _safe_edit(call.message, text, reply_markup=kb.service_inquiry_card_kb(cb_id, fields))
            return
        await _safe_edit(call.message, text, reply_markup=kb.service_inquiry_kb(cb_id))

    @router.callback_query(F.data == "svc_tutorial")
    async def cb_service_tutorial(call: CallbackQuery):
        tutorials = await asyncio.to_thread(db.get_tutorials_for_target, tutorial_hub.GENERAL)
        if not tutorials:
            await call.answer(db.get_text('handlers_user.auto_tut_none', 'فعلاً آموزشی ثبت نشده.'), show_alert=True)
            return
        await call.answer()
        await call.message.answer(
            tr("📚 یک آموزش را انتخاب کنید:"),
            reply_markup=kb.tutorial_devices_user_kb(tutorials),
        )

    @router.callback_query(F.data.startswith(tutorial_hub.BUTTON_PREFIX))
    async def cb_tutorial_target_button(call: CallbackQuery):
        target_key = call.data[len(tutorial_hub.BUTTON_PREFIX):]
        tutorials = await asyncio.to_thread(db.get_tutorials_for_target, target_key)
        if not tutorials:
            await call.answer(tr('فعلاً آموزشی برای این بخش ثبت نشده.'), show_alert=True)
            return
        await call.answer()
        if len(tutorials) == 1:
            await tutorial.send_device_steps(call.bot, call.from_user.id, db, tutorials[0]["id"])
            return
        await call.message.answer(
            tr("📚 یک آموزش را انتخاب کنید:"),
            reply_markup=kb.tutorial_devices_user_kb(tutorials),
        )

    @router.callback_query(F.data.startswith("tut_pick:"))
    async def cb_tutorial_pick(call: CallbackQuery):
        try:
            device_id = int(call.data.split(":", 1)[1])
        except ValueError:
            await call.answer(db.get_text('handlers_user.auto_ec3a51ff', 'درخواست نامعتبر است.'), show_alert=True)
            return
        await call.answer()
        sent = await tutorial.send_device_steps(call.bot, call.from_user.id, db, device_id)
        if not sent:
            await call.message.answer(db.get_text('handlers_user.auto_tut_empty', 'برای این آموزش هنوز مرحله‌ای ثبت نشده.'))

    @router.callback_query(F.data.startswith("mo_links:"))
    async def cb_my_orders_links(call: CallbackQuery):
        """دکمه‌ی واحد «کانفیگ‌های تکی»: فقط با زدن همین دکمه، تمام لینک‌های
        تکیِ این سرویس (نه از همان ابتدا) به‌صورت یک پیام جدا ارسال می‌شوند."""
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item:
            await call.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            return
        link = _item_sub_link(item)
        if not link.startswith(("http://", "https://")):
            await call.answer(db.get_text('handlers_user.auto_fc8d34f5', 'کانفیگ تکی\u200cای برای این لینک موجود نیست.'), show_alert=True)
            return
        await call.answer()
        try:
            links = await fetch_individual_links(link)
        except Exception:
            links = []
        if not links:
            await call.answer(db.get_text('handlers_user.auto_096cc2af', 'در حال حاضر کانفیگ تکی\u200cای یافت نشد.'), show_alert=True)
            return
        text = f"📋 کانفیگ‌های تکی این سرویس ({len(links)} عدد):\n\n" + "\n".join(f"`{c}`" for c in links)
        if len(text) > 4000:
            text = text[:3950] + "\n\n… (فهرست کوتاه شد؛ تعداد کانفیگ‌ها زیاد است)"
        await call.message.answer(text, parse_mode="Markdown")

    @router.callback_query(F.data.startswith("mo_del:"))
    async def cb_my_orders_delete_ask(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_delete", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] not in ("config", "custom"):
            await call.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            await _show_my_orders_list(call.message, call.from_user.id, edit=True)
            return
        await call.answer()
        refund_text = ""
        if item["kind"] == "custom":
            refund_text = refund_quote_text(await quote_service_refund(db, item["custom"], call.from_user.id, reseller_backend))
        await _safe_edit(
            call.message,
            "⚠️ آیا مطمئن هستید؟\n\n"
            "با حذف این کانفیگ، اطلاعات و لینک آن برای همیشه از سیستم پاک می‌شود و "
            "این عملیات **غیرقابل بازگشت** است."
            + (f"\n\n{refund_text}" if refund_text else ""),
            parse_mode="Markdown",
            reply_markup=kb.my_order_delete_confirm_kb(cb_id),
        )

    @router.callback_query(F.data.startswith("mo_delok:"))
    async def cb_my_orders_delete_confirm(call: CallbackQuery):
        cb_id = call.data.split(":", 1)[1]
        user_tg_id = call.from_user.id
        kind = cb_id[0]
        try:
            item_id = int(cb_id[1:])
        except ValueError:
            await call.answer(db.get_text('handlers_user.auto_dc46e7ed', 'درخواست نامعتبر.'), show_alert=True)
            return

        if kind == "c":
            removed = (await asyncio.to_thread(db.delete_owned_config, item_id, user_tg_id))
            if not removed:
                await call.answer(db.get_text('handlers_user.auto_dd15f4d3', 'این کانفیگ یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            else:
                await send_service_alert(
                    bot, db,
                    f"🗑 حذف کانفیگ\n\n👤 کاربر: {user_tg_id}\n🔗 کانفیگ #{item_id}\n📌 نوع: کانفیگ بانکی"
                )
                await call.answer(db.get_text('handlers_user.auto_67b7397c', '✅ کانفیگ برای همیشه حذف شد.'), show_alert=True)
        elif kind == "x":
            cc = (await asyncio.to_thread(db.get_custom_configs_for_user, user_tg_id))
            cc_row = next((c for c in cc if c["id"] == item_id), None)
            if not cc_row:
                await call.answer(db.get_text('handlers_user.auto_dd15f4d3', 'این کانفیگ یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            else:
                quote = await quote_service_refund(db, cc_row, user_tg_id, reseller_backend)
                panel_deleted = False
                if cc_row["panel_server_id"]:
                    server = (await asyncio.to_thread(db.get_panel_server, cc_row["panel_server_id"]))
                    if server:
                        try:
                            provider = get_provider(server)
                            panel_deleted = bool(await provider.delete_user(cc_row["username"]))
                        except Exception:
                            logging.getLogger("handlers_user").exception(
                                "حذف کاربر «%s» از پنل سرور #%s ناموفق بود؛ در هر صورت از لیست کاربر حذف می‌شود.",
                                cc_row["username"], cc_row["panel_server_id"],
                            )
                removed = (await asyncio.to_thread(
                    db.delete_owned_custom_config, item_id, user_tg_id, wallet_refund_amount(quote, panel_deleted),
                ))
                refunded = 0
                if removed:
                    refunded = wallet_refund_amount(quote, panel_deleted) or await grant_service_refund_credit(
                        reseller_backend, user_tg_id, quote, panel_deleted, cc_row["username"],
                    )
                if removed:
                    await send_service_alert(
                        bot, db,
                        f"🗑 حذف کانفیگ\n\n👤 کاربر: {user_tg_id}\n🔗 سرویس #{item_id}\n📌 نام کاربری پنل: {cc_row['username']}\n📌 نوع: کانفیگ پنلی"
                    )
                if refunded > 0:
                    await call.answer(tr(f"✅ کانفیگ برای همیشه حذف شد و {refund_result_text(quote, refunded)}"), show_alert=True)
                else:
                    await call.answer(db.get_text('handlers_user.auto_67b7397c', '✅ کانفیگ برای همیشه حذف شد.'), show_alert=True)
        else:
            await call.answer(db.get_text('handlers_user.auto_dc46e7ed', 'درخواست نامعتبر.'), show_alert=True)

        await _show_my_orders_list(call.message, user_tg_id, edit=True)

    # -----------------------------------------------------------------------
    # تمدید سرویس / کیوآر / قطع دسترسی (دکمه‌های صفحه‌ی جزئیات یک سرویس)
    # -----------------------------------------------------------------------

    _RENEW_MODE_LABEL = {
        "full": "تمدید کامل سرویس", "volume": "تمدید حجم سرویس", "time": "تمدید زمان سرویس",
        "users": "افزایش کاربر سرویس",
    }

    @router.callback_query(F.data.startswith("svc_qr:"))
    async def cb_service_qr(call: CallbackQuery, bot: Bot):
        if (await asyncio.to_thread(db.get_setting, "svc_show_qr", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item:
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        link = None
        if item["kind"] == "config":
            link = item["config"]["link"]
        elif item["kind"] == "custom":
            link = item["custom"]["subscription_url"]
        if not link:
            await call.answer(db.get_text('handlers_user.auto_4e32a60a', 'لینکی برای ساخت کیوآر پیدا نشد.'), show_alert=True)
            return
        await call.answer()
        photo = BufferedInputFile(build_qr_bytes(link, db=db), filename="config_qr.png")
        await bot.send_photo(call.from_user.id, photo, caption=tr("⬜ کیوآر کانفیگ شما"))

    @router.callback_query(F.data.startswith("svc_cut:"))
    async def cb_service_cut_ask(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_cut_access", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        await call.answer()
        await _safe_edit(
            call.message,
            db.get_text('handlers_user.auto_7715b64e', '⚠️ آیا مطمئن هستید؟\n\nبا این کار، لینک/کانفیگ فعلی شما از کار می\u200cافتد و بلافاصله یک لینک جدید با **دقیقاً همان حجم و زمان باقی\u200cمانده\u200cی فعلی** صادر می\u200cشود (نه یک سرویس تازه). این عملیات **غیرقابل بازگشت** است.'),
            parse_mode="Markdown",
            reply_markup=kb.service_cut_confirm_kb(cb_id),
        )

    @router.callback_query(F.data.startswith("svc_cutok:"))
    async def cb_service_cut_confirm(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_cut_access", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        user_tg_id = call.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            await _show_my_orders_list(call.message, user_tg_id, edit=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        cc = item["custom"]
        server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
        if not server or not server["is_active"]:
            await call.answer(db.get_text('handlers_user.auto_55aad2d4', 'سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است.'), show_alert=True)
            return
        await call.answer()
        try:
            provider = get_provider(server)
            result = await provider.revoke_credentials(cc["username"])
        except PanelError as e:
            await _safe_edit(
                call.message, f"⛔️ قطع دسترسی ناموفق بود: {e}",
                reply_markup=kb.my_order_error_back_kb(),
            )
            return
        if result.subscription_url:
            (await asyncio.to_thread(db.update_custom_config_subscription_url, cc["id"], result.subscription_url))
        (await asyncio.to_thread(db.add_custom_config_history, cc["id"], "cut_access", "دسترسی قطع و لینک جدید صادر شد"))
        item2 = _find_my_orders_item(user_tg_id, cb_id)
        if item2:
            text = await _my_orders_item_text(item2)
            await _safe_edit(
                call.message, "✅ دسترسی قبلی قطع شد و لینک جدید صادر شد.\n\n" + text,
                parse_mode="Markdown",
                reply_markup=kb.service_detail_kb(db, cb_id, item2["kind"], True, **_svc_kb_kwargs(item2)),
            )
        else:
            await _safe_edit(call.message, db.get_text('handlers_user.auto_1061be58', '✅ دسترسی قبلی قطع شد و لینک جدید صادر شد.'))

    # -----------------------------------------------------------------------
    # فعال/غیرفعال، تغییر نام، تمدید خودکار، انتقال و تاریخچه‌ی کانفیگ‌های
    # مستقیم-پنل (دکمه‌های اضافه‌ی صفحه‌ی جزئیات یک سرویس)
    # -----------------------------------------------------------------------

    async def _refresh_service_card(target, user_tg_id: int, cb_id: str, prefix_text: str = None):
        item2 = _find_my_orders_item(user_tg_id, cb_id)
        if not item2:
            await target.answer(db.get_text('handlers_user.auto_91b523c7', 'این مورد دیگر یافت نشد.'))
            return
        text = await _my_orders_item_text(item2)
        if prefix_text:
            text = prefix_text + "\n\n" + text
        deletable = item2["kind"] in ("config", "custom")
        show_links = _item_has_individual_links(item2)
        markup = kb.service_detail_kb(db, cb_id, item2["kind"], deletable, show_links, **_svc_kb_kwargs(item2))
        if isinstance(target, Message):
            await target.answer(text, parse_mode="Markdown", reply_markup=markup)
        else:
            await _safe_edit(target, text, parse_mode="Markdown", reply_markup=markup)

    @router.callback_query(F.data.startswith("svc_toggle:"))
    async def cb_service_toggle(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_toggle", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        user_tg_id = call.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        cc = item["custom"]
        new_enabled = not ((cc["enabled"] if "enabled" in cc.keys() else 1) == 1)
        server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
        if not server or not server["is_active"]:
            await call.answer(db.get_text('handlers_user.auto_55aad2d4', 'سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است.'), show_alert=True)
            return
        try:
            provider = get_provider(server)
            await provider.set_enabled(cc["username"], new_enabled)
        except PanelError as e:
            await call.answer(tr(f"⛔️ ناموفق بود: {e}"), show_alert=True)
            return
        (await asyncio.to_thread(db.set_custom_config_enabled, cc["id"], user_tg_id, new_enabled))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc["id"], "toggle", "فعال شد" if new_enabled else "غیرفعال شد",
        ))
        await _refresh_service_card(call.message, user_tg_id, cb_id)
        await call.answer(db.get_text('handlers_user.auto_9b232770', '✅ وضعیت بروزرسانی شد.'))

    @router.callback_query(F.data.startswith("svc_rename:"))
    async def cb_service_rename_ask(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "svc_show_rename", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        cc = item["custom"]
        await state.set_state(ServiceRenameFlow.waiting_suffix)
        await state.update_data(cb_id=cb_id)
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        current_label = cc["display_name"] or cc["username"]
        if prefix and current_label.startswith(prefix + "-"):
            current_suffix = current_label[len(prefix) + 1:]
            prompt = (
                f"✏️ نام فعلی: «{current_label}»\n\n"
                f"ادامه‌ی نام جدید (بعد از «{prefix}-») را ارسال کنید.\n"
                "فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر."
            )
        else:
            prompt = (
                f"✏️ نام فعلی: «{current_label}»\n\n"
                "نام جدید کانفیگ را ارسال کنید. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر."
            )
        await call.answer()
        await call.message.answer(prompt, reply_markup=kb.service_rename_cancel_kb(cb_id))

    @router.message(ServiceRenameFlow.waiting_suffix)
    async def service_rename_receive(message: Message, state: FSMContext):
        data = await state.get_data()
        cb_id = data.get("cb_id")
        suffix = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", suffix):
            await message.answer(db.get_text('handlers_user.auto_4b7b8e98', '❌ نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.'))
            return
        user_tg_id = message.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] != "custom":
            await state.clear()
            await message.answer(db.get_text('handlers_user.auto_91b523c7', 'این مورد دیگر یافت نشد.'))
            return
        cc = item["custom"]
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        current_label = cc["display_name"] or cc["username"]
        new_label = f"{prefix}-{suffix}" if (prefix and current_label.startswith(prefix + "-")) else suffix
        if new_label == current_label:
            await message.answer(db.get_text('handlers_user.auto_23695416', 'این نام همان نام فعلی است.'))
            return
        if (await asyncio.to_thread(db.is_custom_username_taken, new_label)):
            await message.answer(db.get_text('handlers_user.auto_141334c4', '❌ این نام قبلاً استفاده شده. نام دیگری بفرست.'))
            return
        server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
        panel_username = None
        note = "(فقط نام نمایشی داخل بات تغییر کرد؛ لینک/کانفیگ فعلی روی پنل بدون تغییر کار می‌کند)"
        if server and server["is_active"]:
            try:
                provider = get_provider(server)
                await provider.rename_user(cc["username"], new_label)
                panel_username = new_label
                note = "(روی خودِ پنل هم اعمال شد)"
            except PanelError:
                pass
        old_label = current_label
        (await asyncio.to_thread(db.rename_custom_config, cc["id"], user_tg_id, new_label, panel_username))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc["id"], "rename", f"{old_label} ← {new_label} {note}",
        ))
        await state.clear()
        await _refresh_service_card(message, user_tg_id, cb_id, f"✅ نام کانفیگ به «{new_label}» تغییر کرد. {note}")

    @router.callback_query(F.data.startswith("svc_autorenew:"))
    async def cb_service_autorenew_toggle(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_auto_renew", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        user_tg_id = call.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        cc = item["custom"]
        if (cc["duration_days"] or 0) <= 0:
            await call.answer(db.get_text('handlers_user.auto_1b293231', 'این کانفیگ نامحدود است و نیازی به تمدید خودکار ندارد.'), show_alert=True)
            return
        new_val = not ((cc["auto_renew"] if "auto_renew" in cc.keys() else 0) == 1)
        (await asyncio.to_thread(db.set_custom_config_auto_renew, cc["id"], user_tg_id, new_val))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc["id"], "auto_renew_toggle", "فعال شد" if new_val else "غیرفعال شد",
        ))
        await _refresh_service_card(call.message, user_tg_id, cb_id)
        if new_val:
            await call.answer(db.get_text('handlers_user.auto_893ac1bb', '✅ تمدید خودکار فعال شد. هر بار نزدیک انقضا، از کیف پول کسر و تمدید می\u200cشود.'))
        else:
            await call.answer(db.get_text('handlers_user.auto_a983081d', '✅ تمدید خودکار غیرفعال شد.'))

    # -----------------------------------------------------------------------
    # تغییر لوکیشن سرویس: ساخت روی مقصد، سپس حذف مبدا، با rollback
    # -----------------------------------------------------------------------

    def _location_remaining_days(cc):
        if not cc["expires_at"]:
            return 0
        try:
            dt = datetime.fromisoformat(cc["expires_at"])
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            seconds = (dt - datetime.utcnow()).total_seconds()
            return max(1, int(math.ceil(seconds / 86400))) if seconds > 0 else 0
        except Exception:
            return 0

    @router.callback_query(F.data.startswith("svc_location:"))
    async def cb_service_location_ask(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_location_transfer", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_d9b5ca16', 'تغییر لوکیشن برای کانفیگ تست مجاز نیست.'), show_alert=True)
            return
        cc = item["custom"]
        if int(cc["start_on_first_use"] or 0) and not cc["expires_at"]:
            await call.answer(db.get_text('handlers_user.auto_8b141043', '⛔️ این سرویس هنوز استفاده نشده و در حالت On-hold است؛ تغییر لوکیشن مجاز نیست.'), show_alert=True)
            return
        current_server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
        if not current_server or not current_server["is_active"]:
            await call.answer(db.get_text('handlers_user.auto_1b163050', 'پنل فعلی سرویس در دسترس نیست.'), show_alert=True)
            return
        targets = await asyncio.to_thread(db.get_location_transfer_targets, cc["panel_server_id"])
        targets = [x for x in targets if int(x["id"]) != int(cc["panel_server_id"])]
        if not targets:
            await call.answer(db.get_text('handlers_user.auto_6c062495', 'هیچ لوکیشن مقصد فعالی برای انتقال تعریف نشده است.'), show_alert=True)
            return
        policies = {}
        for target in targets:
            policy = await asyncio.to_thread(db.get_location_transfer_policy, call.from_user.id, target["id"])
            policies[target["id"]] = policy
        if all(not p.get("ok") for p in policies.values()):
            first = next(iter(policies.values()))
            if first.get("reason") == "user_limit":
                await call.answer(tr(f"⛔️ سقف انتقال شما تکمیل شده است ({first.get('count',0)}/{first.get('limit')})."), show_alert=True)
            else:
                await call.answer(db.get_text('handlers_user.auto_82c337fc', 'هیچ مقصد مجازی برای انتقال وجود ندارد.'), show_alert=True)
            return
        await call.answer()
        await _safe_edit(
            call.message,
            db.get_text('handlers_user.auto_5b405570', '📍 تغییر لوکیشن سرویس\n\nلوکیشن مقصد را انتخاب کنید.\nدر انتقال، حجم باقی\u200cمانده و زمان باقی\u200cمانده حفظ می\u200cشود؛ لینک اشتراک قبلی پس از موفقیت از کار می\u200cافتد.'),
            reply_markup=kb.service_location_targets_kb(cb_id, targets, policies),
        )

    @router.callback_query(F.data.startswith("svc_location_pick:"))
    async def cb_service_location_pick(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_location_transfer", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        _, cb_id, target_id_s = call.data.split(":", 2)
        target_id = int(target_id_s)
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom" or _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ad118aee', 'این سرویس قابل انتقال نیست.'), show_alert=True)
            return
        cc = item["custom"]
        target = await asyncio.to_thread(db.get_panel_server, target_id)
        if not target or not target["is_active"] or not target["allow_transfer_target"]:
            await call.answer(db.get_text('handlers_user.auto_2b56d8ea', 'لوکیشن مقصد دیگر قابل انتقال نیست.'), show_alert=True)
            return
        policy = await asyncio.to_thread(db.get_location_transfer_policy, call.from_user.id, target_id)
        if not policy.get("ok"):
            if policy.get("reason") == "user_limit":
                await call.answer(tr(f"⛔️ سقف انتقال شما تکمیل شده است ({policy.get('count',0)}/{policy.get('limit')})."), show_alert=True)
            else:
                await call.answer(db.get_text('handlers_user.auto_7fef7f50', 'امکان انتقال به این مقصد وجود ندارد.'), show_alert=True)
            return
        price = int(policy.get("price", 0))
        fee_text = "رایگان" if price <= 0 else f"{price:,} تومان"
        await call.answer()
        await _safe_edit(
            call.message,
            f"⚠️ انتقال «{cc['display_name'] or cc['username']}» به «{target['name']}»\n\n"
            f"هزینه انتقال: **{fee_text}**\n"
            "حجم باقی‌مانده و زمان باقی‌مانده منتقل می‌شود.\n"
            "پس از موفقیت، لینک قدیمی از کار خواهد افتاد.\n\nآیا ادامه می‌دهید؟",
            parse_mode="Markdown",
            reply_markup=kb.service_location_confirm_kb(cb_id, target_id),
        )

    @router.callback_query(F.data.startswith("svc_location_ok:"))
    async def cb_service_location_confirm(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_location_transfer", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        _, cb_id, target_id_s = call.data.split(":", 2)
        target_id = int(target_id_s)
        user_tg_id = call.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] != "custom" or _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ad118aee', 'این سرویس قابل انتقال نیست.'), show_alert=True)
            return
        cc = item["custom"]
        old_server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
        target = await asyncio.to_thread(db.get_panel_server, target_id)
        if not old_server or not target or not old_server["is_active"] or not target["is_active"] or not target["allow_transfer_target"]:
            await call.answer(db.get_text('handlers_user.auto_2d68684b', 'مبدا یا مقصد دیگر قابل استفاده نیست.'), show_alert=True)
            return
        if int(cc["start_on_first_use"] or 0) and not cc["expires_at"]:
            await call.answer(db.get_text('handlers_user.auto_a88e988e', '⛔️ سرویس هنوز استفاده نشده و قابل انتقال نیست.'), show_alert=True)
            return
        cap = await asyncio.to_thread(db.get_panel_capacity_info, target_id)
        if cap and cap.get("max_services") is not None and cap['active_services'] + 1 > cap['max_services']:
            await call.answer(db.get_text('handlers_user.auto_3ca149dd', '⛔️ ظرفیت لوکیشن مقصد تکمیل است.'), show_alert=True)
            return
        remaining_days = _location_remaining_days(cc)
        if cc["expires_at"] and remaining_days <= 0:
            await call.answer(db.get_text('handlers_user.auto_e2d73bd6', '⛔️ این سرویس منقضی شده است.'), show_alert=True)
            return
        await call.answer(db.get_text('handlers_user.auto_e2b896a2', '⏳ در حال انتقال سرویس...'))
        old_provider = get_provider(old_server)
        target_provider = get_provider(target)
        try:
            usage = await old_provider.get_user_usage(cc["username"])
            used_bytes = max(0, int(usage.get("used_bytes", 0) or 0))
            limit_bytes = int(usage.get("data_limit_bytes", 0) or 0)
            if limit_bytes > 0:
                remaining_bytes = max(limit_bytes - used_bytes, 0)
                remaining_volume = int(math.ceil(remaining_bytes / (1024 ** 3)))
            else:
                remaining_volume = int(cc["volume_gb"] or 0)
            if remaining_volume <= 0:
                await call.answer(db.get_text('handlers_user.auto_e047ffcb', '⛔️ حجم باقی\u200cمانده برای انتقال وجود ندارد.'), show_alert=True)
                return
            status = str(usage.get("status") or "").lower()
            if status in {"on_hold", "on-hold", "onhold", "pending"}:
                await call.answer(db.get_text('handlers_user.auto_61132908', '⛔️ این سرویس هنوز استفاده نشده است و قابل انتقال نیست.'), show_alert=True)
                return
            try:
                transfer_kwargs = ul.provider_kwargs(target_provider, cc["user_limit"])
                result = await target_provider.create_user(
                    cc["username"], remaining_volume, remaining_days,
                    start_on_first_use=False, **transfer_kwargs,
                )
            except TypeError as te:
                if "start_on_first_use" not in str(te):
                    raise
                result = await target_provider.create_user(
                    cc["username"], remaining_volume, remaining_days, **transfer_kwargs,
                )
        except PanelUsernameTakenError:
            await call.message.answer(db.get_text('handlers_user.auto_ca2aa6c8', '⛔️ نام کاربری این سرویس روی لوکیشن مقصد از قبل وجود دارد؛ سرویس قدیمی دست\u200cنخورده باقی ماند.'))
            return
        except PanelError as e:
            await call.message.answer(tr(f"⛔️ ساخت سرویس روی لوکیشن مقصد ناموفق بود؛ سرویس قدیمی دست‌نخورده باقی ماند.\n{e}"))
            return
        except Exception:
            logging.getLogger("handlers_user").exception("location transfer create failed")
            await call.message.answer(db.get_text('handlers_user.auto_6c79e631', '⛔️ هنگام ساخت سرویس روی مقصد خطایی رخ داد؛ سرویس قدیمی دست\u200cنخورده باقی ماند.'))
            return

        reserve = await asyncio.to_thread(
            db.reserve_location_transfer, cc["id"], user_tg_id, cc["panel_server_id"], target_id,
            int(target["transfer_price"] or 0), cc["username"], cc["volume_gb"], cc["expires_at"], cc["subscription_url"],
        )
        if not reserve.get("ok"):
            try:
                await target_provider.delete_user(result.username)
            except Exception:
                logging.getLogger("handlers_user").exception("location transfer rollback delete failed")
            reason = reserve.get("reason")
            if reason == "insufficient_balance":
                await call.message.answer(db.get_text('handlers_user.auto_d0283e26', '⛔️ موجودی کیف پول برای هزینه انتقال کافی نیست؛ سرویس قدیمی دست\u200cنخورده باقی ماند.'))
            elif reason == "user_limit":
                await call.message.answer(db.get_text('handlers_user.auto_f77894b2', '⛔️ سقف تعداد انتقال شما تکمیل شده است؛ سرویس قدیمی دست\u200cنخورده باقی ماند.'))
            else:
                await call.message.answer(db.get_text('handlers_user.auto_9cd5b2cf', '⛔️ امکان رزرو انتقال وجود نداشت؛ سرویس قدیمی دست\u200cنخورده باقی ماند.'))
            return

        log_id = reserve["log_id"]
        new_expiry = cc["expires_at"]
        try:
            if not await asyncio.to_thread(
                db.update_location_transfer_local_pending, log_id, cc["id"], result.username,
                result.subscription_url, remaining_volume, new_expiry,
            ):
                raise RuntimeError("local update failed")
            if not await asyncio.to_thread(
                db.complete_location_transfer, log_id, cc["id"], result.username,
                remaining_volume, new_expiry, f"{old_server['name']} → {target['name']} | هزینه {reserve['fee']:,} تومان",
                result.subscription_url,
            ):
                raise RuntimeError("local finalize failed")
            try:
                await old_provider.delete_user(cc["username"])
            except Exception as old_delete_error:
                raise RuntimeError(f"old panel delete failed: {old_delete_error}")
        except Exception as e:
            logging.getLogger("handlers_user").exception("location transfer finalize failed")
            try:
                await target_provider.delete_user(result.username)
            except Exception:
                logging.getLogger("handlers_user").exception("location transfer target rollback failed")
            await asyncio.to_thread(db.rollback_location_transfer, log_id, str(e))
            await call.message.answer(db.get_text('handlers_user.auto_3af738f8', '⛔️ انتقال کامل نشد؛ تلاش شد سرویس و هزینه به وضعیت قبلی برگردد. سرویس قدیمی در صورت موفقیت rollback حفظ شده است.'))
            return

        try:
            await asyncio.to_thread(
                db.add_custom_config_history, cc["id"], "location_change",
                f"انتقال لوکیشن: {old_server['name']} → {target['name']} | {remaining_volume}GB | {remaining_days} روز | هزینه {reserve['fee']:,} تومان",
            )
        except Exception:
            logging.getLogger("handlers_user").exception("location transfer history log failed")

        item2 = _find_my_orders_item(user_tg_id, cb_id)
        if item2:
            text = await _my_orders_item_text(item2)
            await _safe_edit(
                call.message,
                "✅ لوکیشن سرویس با موفقیت تغییر کرد.\n\n" + text,
                parse_mode="Markdown",
                reply_markup=kb.service_detail_kb(db, cb_id, item2["kind"], True, **_svc_kb_kwargs(item2)),
            )
        else:
            await call.message.answer(db.get_text('handlers_user.auto_e6014d75', '✅ لوکیشن سرویس با موفقیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("svc_transfer:"))
    async def cb_service_transfer_ask(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "svc_show_transfer", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        await state.set_state(ServiceTransferFlow.waiting_target_id)
        await state.update_data(cb_id=cb_id)
        await call.answer()
        await call.message.answer(
            db.get_text('handlers_user.auto_312bac76', '👤 آی\u200cدی عددی تلگرام کاربری که می\u200cخواهید این کانفیگ به او منتقل شود را ارسال کنید.\nتوجه: آن کاربر باید قبلاً بات را استارت کرده باشد.'),
            reply_markup=kb.service_rename_cancel_kb(cb_id),
        )

    @router.message(ServiceTransferFlow.waiting_target_id)
    async def service_transfer_receive(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_user.auto_7bd119ef', '❌ فقط آی\u200cدی عددی تلگرام را ارسال کنید.'))
            return
        target_id = int(text)
        data = await state.get_data()
        cb_id = data.get("cb_id")
        user_tg_id = message.from_user.id
        if target_id == user_tg_id:
            await message.answer(db.get_text('handlers_user.auto_099fb6a8', 'این کانفیگ همین الان مال شماست.'))
            return
        target_user = (await asyncio.to_thread(db.get_user, target_id))
        if not target_user:
            await message.answer(db.get_text('handlers_user.auto_d037e5c6', '❌ این کاربر بات را استارت نکرده یا آی\u200cدی نادرست است.'))
            return
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] != "custom":
            await state.clear()
            await message.answer(db.get_text('handlers_user.auto_91b523c7', 'این مورد دیگر یافت نشد.'))
            return
        await state.clear()
        await message.answer(
            tr(f"⚠️ آیا مطمئن هستید که این کانفیگ به کاربر با آی‌دی {target_id} منتقل شود؟\n"
            "این عملیات **غیرقابل بازگشت** است."),
            parse_mode="Markdown",
            reply_markup=kb.service_transfer_confirm_kb(cb_id, target_id),
        )

    @router.callback_query(F.data.startswith("svc_transok:"))
    async def cb_service_transfer_confirm(call: CallbackQuery, bot: Bot):
        if (await asyncio.to_thread(db.get_setting, "svc_show_transfer", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        _, cb_id, target_id_s = call.data.split(":", 2)
        target_id = int(target_id_s)
        user_tg_id = call.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_7e65dc98', 'این مورد یافت نشد (شاید قبلاً حذف/منتقل شده).'), show_alert=True)
            await _show_my_orders_list(call.message, user_tg_id, edit=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        cc = item["custom"]
        ok = (await asyncio.to_thread(db.transfer_custom_config, cc["id"], user_tg_id, target_id))
        if not ok:
            await call.answer(db.get_text('handlers_user.auto_79b3425b', 'انتقال ناموفق بود.'), show_alert=True)
            return
        (await asyncio.to_thread(
            db.add_custom_config_history, cc["id"], "transfer", f"از {user_tg_id} به {target_id}",
        ))
        await call.answer(db.get_text('handlers_user.auto_70c5a109', '✅ کانفیگ منتقل شد.'), show_alert=True)
        try:
            await call.bot.send_message(
                target_id,
                tr(f"📦 یک کانفیگ («{cc['display_name'] or cc['username']}») از طرف کاربر دیگری به حساب شما منتقل شد.\n"
                "برای مشاهده، حساب کاربری ← سرویس‌ها و سفارش‌های من را ببینید."),
            )
        except Exception:
            pass
        try:
            await _notify_admins_service_transfer(bot, cc, user_tg_id, target_id)
        except Exception:
            logging.getLogger("handlers_user").exception("service transfer admin notify failed")
        await _show_my_orders_list(call.message, user_tg_id, edit=True)

    @router.callback_query(F.data.startswith("svc_hist:"))
    async def cb_service_history(call: CallbackQuery):
        if (await asyncio.to_thread(db.get_setting, "svc_show_history", "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        cc = item["custom"]
        rows = (await asyncio.to_thread(db.get_custom_config_history, cc["id"]))
        _EVENT_LABEL = {
            "purchase": "🛒 خرید", "renewal": "🔄 تمدید", "toggle": "🟢 فعال/غیرفعال",
            "users": "👥 کاربر همزمان", "auto_renew_toggle": "🔁 تمدید خودکار", "rename": "✏️ تغییر نام", "transfer": "👤 انتقال",
            "cut_access": "🚫 قطع دسترسی", "auto_renew": "🔄 تمدید خودکار (خودکار انجام‌شده)",
        }
        if not rows:
            text = "📜 تاریخچه‌ای برای این سرویس ثبت نشده است."
        else:
            lines = [f"📜 تاریخچه‌ی سرویس «{cc['display_name'] or cc['username']}»\n"]
            for r in rows:
                label = _EVENT_LABEL.get(r["event_type"], r["event_type"])
                when = to_jalali_str(r["created_at"], with_time=True)
                detail = f" — {r['detail']}" if r["detail"] else ""
                lines.append(f"{label}{detail}\n🗓 {when}\n")
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:3950] + "\n\n… (فهرست کوتاه شد)"
        await call.answer()
        await _safe_edit(call.message, text, reply_markup=kb.service_history_back_kb(cb_id))

    async def _process_renewal_order(
        user_tg_id: int, cb_id: str, mode: str, target_kind: str, target_id: int,
        add_volume: int, add_days: int, price: int, summary_label: str,
        state: FSMContext, edit_fn, send_fn, bot: Bot, user_limit: int = None,
        discount_code_id: int = None, discount_amount: int = 0,
    ) -> None:
        """ساخت سفارش تمدید + مسیر پرداخت مشترک، هم برای «تمدید کامل» (بر اساس
        قیمت پلن انتخابی) و هم برای «تمدید حجم/زمان» (بر اساس نرخ ثابت هر واحد).
        discount_code_id/discount_amount (قابلیت ۵۱) فقط از مسیر «تمدید کامل»
        با کد تخفیف از قبل claim‌شده پر می‌شوند؛ price همان قیمت نهایی بعد از
        کسر تخفیف است.
        edit_fn(text, **kw) پیام اصلی (وضعیت/انتخاب پرداخت) را نشان می‌دهد؛
        send_fn(text, **kw) همیشه یک پیام تازه می‌فرستد (کارت جزئیات سرویس پس از موفقیت)."""
        price_after_code = max(price - discount_amount, 0)
        plan = await asyncio.to_thread(db.plan_wallet_spend, user_tg_id, price_after_code)
        if plan["blocked"]:
            await edit_fn(plan["message"])
            return
        wallet_used = plan["wallet_used"]
        if wallet_used > 0:
            wallet_used = await asyncio.to_thread(db.deduct_wallet_credit, user_tg_id, wallet_used)

        order_id = (await asyncio.to_thread(
            db.create_renewal_order, user_tg_id, target_kind, target_id, mode,
            add_volume, add_days, price, wallet_used, user_limit, discount_code_id, discount_amount,
        ))
        order = (await asyncio.to_thread(db.get_order, order_id))

        try:
            if order["final_price"] <= 0:
                try:
                    result_text = await execute_renewal(db, order)
                except RenewalError as e:
                    (await asyncio.to_thread(db.reject_order, order_id))
                    await edit_fn(f"⛔️ تمدید ناموفق بود: {e}\nمبلغ کسرشده از کیف پول شما بازگردانده شد.")
                    return
                (await asyncio.to_thread(db.approve_renewal_order, order_id))
                renewal_reward_info = (await asyncio.to_thread(
                    db.reward_referrer_on_renewal, user_tg_id, order["base_price"] or order["final_price"] or 0
                ))
                if renewal_reward_info:
                    renewal_reward_amount, renewal_referrer_id = renewal_reward_info
                    try:
                        await bot.send_message(
                            renewal_referrer_id,
                            tr(f"🤝 تبریک! یکی از زیرمجموعه‌های شما سرویسش را تمدید کرد.\n"
                            f"💰 {renewal_reward_amount:,} تومان پورسانت به کیف پول شما اضافه شد."),
                        )
                    except Exception:
                        pass
                await edit_fn(result_text)
                item2 = _find_my_orders_item(user_tg_id, cb_id)
                if item2:
                    text = await _my_orders_item_text(item2)
                    deletable = item2["kind"] in ("config", "custom")
                    await send_fn(text, parse_mode="Markdown", reply_markup=kb.service_detail_kb(db, cb_id, item2["kind"], deletable, **_svc_kb_kwargs(item2)))
                return

            remaining_amount = order["final_price"]
            if not (await asyncio.to_thread(db.has_any_payable_method, remaining_amount, None)):
                (await asyncio.to_thread(db.reject_order, order_id))
                await edit_fn(
                    "⛔️ در حال حاضر هیچ روش پرداخت فعالی برای این مبلغ در دسترس نیست."
                    + ("\nمبلغ کسرشده از کیف پول شما بازگردانده شد." if wallet_used > 0 else ""),
                )
                return

            await state.set_state(RenewalFlow.waiting_receipt)
            await state.update_data(order_id=order_id, renew_cb_id=cb_id)

            text = f"🔄 {_RENEW_MODE_LABEL[mode]} - {summary_label}\n\n"
            if discount_amount > 0:
                text += db.get_text(
                    "handlers_user.renewal.discount_applied_line", "🎟 تخفیف کد: {amount} تومان\n"
                ).format(amount=f"{discount_amount:,}")
            if wallet_used:
                text += f"👛 استفاده از کیف پول: {wallet_used:,} تومان\n"
            text += f"💰 مبلغ نهایی قابل پرداخت: {order['final_price']:,} تومان\n\n"
            text += "لطفاً روش پرداخت را انتخاب کنید:"
            await edit_fn(
                text, parse_mode="Markdown",
                reply_markup=kb.payment_choice_kb(
                    crypto_payment.crypto_payment_available(db),
                    abangateway_payment.abangateway_payment_available(db),
                    custom_gateway_payment.list_enabled_gateways(db),
                    (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) == "1",
                    card_auto_enabled=(await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) == "1",
                    amount=remaining_amount,
                    db=db,
                    noapay_enabled=noapay_payment.noapay_payment_available(db),
                    blupal_enabled=blupal_payment.blupal_payment_available(db),
                    extra_gateways=extra_gateway_payment.available_keys(db, is_main_bot),
                ),
            )
        except Exception:
            logging.getLogger("handlers_user").exception(
                "خطای غیرمنتظره در فرآیند تمدید سرویس (سفارش #%s) برای کاربر %s؛ سفارش رد و مبلغ کیف پول (در صورت وجود) بازگردانده شد.",
                order_id, user_tg_id,
            )
            (await asyncio.to_thread(db.reject_order, order_id))
            await state.clear()
            await edit_fn(
                "⛔️ خطای غیرمنتظره‌ای در پردازش تمدید رخ داد.\n"
                "اگر مبلغی از کیف پول شما کسر شده بود، به‌طور کامل بازگردانده شد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
            )

    @router.callback_query(F.data.startswith("svc_renew:"))
    async def cb_service_renew_start(call: CallbackQuery, state: FSMContext):
        _, mode, cb_id = call.data.split(":", 2)
        toggle_key = {"full": "svc_show_renew_full", "volume": "svc_show_renew_volume", "time": "svc_show_renew_time"}[mode]
        if (await asyncio.to_thread(db.get_setting, toggle_key, "1")) != "1":
            await call.answer(db.get_text('handlers_user.auto_b151f395', 'این قابلیت غیرفعال است.'), show_alert=True)
            return
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] not in ("config", "custom"):
            await call.answer(db.get_text('handlers_user.auto_6bf10f8b', 'این مورد یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_ac955106', 'این قابلیت برای کانفیگ تست در دسترس نیست.'), show_alert=True)
            return
        if item["kind"] == "config" and mode != "time":
            await call.answer(db.get_text('handlers_user.auto_09ec17e1', 'برای این کانفیگ فقط «تمدید زمان» ممکن است.'), show_alert=True)
            return

        if mode == "full":
            current_panel_id = item["custom"]["panel_server_id"]
            all_products = [p for p in (await asyncio.to_thread(db.get_all_products)) if p["is_auto_provision"] and p["is_active"]]
            # فقط پلن‌هایی که روی همان پنل VPN این سرویس ساخته شده‌اند نشان داده
            # می‌شوند - نه پلن‌هایی با همان حجم اولیه؛ چون بعد از هر تمدید حجم/زمان
            # سرویس تغییر می‌کند و دیگر با هیچ محصولی برابر نمی‌ماند، ولی پنل آن
            # ثابت است.
            products = [p for p in all_products if p["provision_server_id"] == current_panel_id]
            if not products:
                await call.answer(db.get_text('handlers_user.auto_4559ece1', 'در حال حاضر پلن تمدیدی روی همین پنل VPN تعریف نشده.'), show_alert=True)
                return
            await call.answer()
            await _safe_edit(
                call.message,
                f"🔄 {_RENEW_MODE_LABEL[mode]}\n\nیکی از پلن‌های زیر را برای اعمال روی همین سرویس انتخاب کنید:",
                reply_markup=kb.renewal_plans_kb(products, mode, cb_id),
            )
            return

        # حالت «تمدید حجم» یا «تمدید زمان»: بر اساس نرخ ثابت هر گیگ/روز که ادمین
        # تنظیم کرده (نه قیمت کامل یک پلن)، از کاربر مقدار مورد نظر پرسیده می‌شود.
        rate_key = "renewal_price_per_gb" if mode == "volume" else "renewal_price_per_day"
        rate = int((await asyncio.to_thread(db.get_setting, rate_key, "0")) or "0")
        if rate <= 0:
            await call.answer(db.get_text('handlers_user.auto_bc026085', 'قیمت\u200cگذاری این بخش هنوز توسط ادمین تنظیم نشده است.'), show_alert=True)
            return

        target_id = item["custom"]["id"] if item["kind"] == "custom" else item["config"]["id"]
        await call.answer()
        await state.set_state(RenewalFlow.waiting_amount)
        await state.update_data(
            renew_mode=mode, renew_cb_id=cb_id,
            renew_target_kind=item["kind"], renew_target_id=target_id, renew_rate=rate,
        )
        unit_label = "گیگابایت" if mode == "volume" else "روز"
        await _safe_edit(
            call.message,
            f"🔄 {_RENEW_MODE_LABEL[mode]}\n\n"
            f"نرخ: {rate:,} تومان به ازای هر {unit_label}\n\n"
            f"لطفاً مقداری که می‌خواهید اضافه شود را به {unit_label} وارد کنید (فقط عدد صحیح):",
            reply_markup=kb.cancel_kb(),
        )

    @router.message(RenewalFlow.waiting_amount)
    async def receive_renewal_amount(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_user.auto_3f57e9bc', '❌ لطفاً یک عدد صحیح مثبت وارد کنید.'))
            return
        amount = int(text)

        data = await state.get_data()
        mode = data.get("renew_mode")
        cb_id = data.get("renew_cb_id")
        target_kind = data.get("renew_target_kind")
        target_id = data.get("renew_target_id")
        rate = data.get("renew_rate", 0)
        if not mode or not cb_id or not rate:
            await message.answer(db.get_text('handlers_user.auto_32ccba24', 'سفارش معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return

        item = _find_my_orders_item(message.from_user.id, cb_id)
        if not item or item["kind"] not in ("config", "custom"):
            await message.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'))
            await state.clear()
            return

        add_volume = amount if mode == "volume" else 0
        add_days = amount if mode == "time" else 0
        price = amount * rate
        unit_label = "گیگابایت" if mode == "volume" else "روز"
        summary_label = f"{amount:,} {unit_label}"

        async def edit_fn(t, **kw):
            await message.answer(t, **kw)

        async def send_fn(t, **kw):
            await message.answer(t, **kw)

        await _process_renewal_order(
            message.from_user.id, cb_id, mode, target_kind, target_id,
            add_volume, add_days, price, summary_label, state, edit_fn, send_fn, message.bot,
        )

    @router.callback_query(F.data.startswith("svc_users:"))
    async def cb_service_users(call: CallbackQuery, state: FSMContext):
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        info = ul.service_upgrade_info(db, item["custom"]) if item and item["kind"] == "custom" else None
        if not info:
            await call.answer(db.get_text('handlers_user.auto_66ddb16b', 'افزایش کاربر برای این سرویس در دسترس نیست.'), show_alert=True)
            return
        await call.answer()
        await _safe_edit(
            call.message,
            f"👥 افزایش تعداد کاربر همزمان\n\nتعداد فعلی: {info['current']} کاربر\n"
            "تعداد جدید را انتخاب کنید (فقط مابه‌التفاوت پرداخت می‌شود):",
            reply_markup=kb.user_count_picker_kb(
                info["product"], info["max_users"], f"svc_users_pick:{cb_id}", f"mo_v:{cb_id}",
                current_users=info["current"],
            ),
        )

    @router.callback_query(F.data.startswith("svc_users_pick:"))
    async def cb_service_users_pick(call: CallbackQuery, state: FSMContext):
        try:
            _, cb_id, users_s = call.data.split(":")
            users = int(users_s)
        except ValueError:
            await call.answer(db.get_text('handlers_user.auto_ec3a51ff', 'درخواست نامعتبر است.'), show_alert=True)
            return
        user_tg_id = call.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        info = ul.service_upgrade_info(db, item["custom"]) if item and item["kind"] == "custom" else None
        if not info or not info["current"] < users <= info["max_users"]:
            await call.answer(db.get_text('handlers_user.auto_f4122f85', 'این گزینه در دسترس نیست.'), show_alert=True)
            return
        price = ul.upgrade_price(info["product"], info["current"], users)
        await call.answer()

        async def edit_fn(t, **kw):
            await _safe_edit(call.message, t, **kw)

        async def send_fn(t, **kw):
            await call.message.answer(t, **kw)

        await _process_renewal_order(
            user_tg_id, cb_id, "users", "custom", item["custom"]["id"], 0, 0, price,
            f"{info['current']} به {users} کاربر", state, edit_fn, send_fn, call.bot, user_limit=users,
        )

    @router.callback_query(F.data.startswith("svc_renew_pick:"))
    async def cb_service_renew_pick(call: CallbackQuery, state: FSMContext):
        parts = call.data.split(":")
        _, mode, cb_id, product_id = parts[:4]
        users = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        user_tg_id = call.from_user.id
        item = _find_my_orders_item(user_tg_id, cb_id)
        if not item or item["kind"] not in ("config", "custom"):
            await call.answer(db.get_text('handlers_user.auto_848eae5d', 'این مورد یافت نشد (شاید قبلاً حذف شده).'), show_alert=True)
            return
        if item["kind"] == "config" and mode != "time":
            await call.answer(db.get_text('handlers_user.auto_09ec17e1', 'برای این کانفیگ فقط «تمدید زمان» ممکن است.'), show_alert=True)
            return
        product = (await asyncio.to_thread(db.get_product, int(product_id)))
        if not product:
            await call.answer(db.get_text('handlers_user.auto_6ecda637', 'این پلن یافت نشد.'), show_alert=True)
            return

        add_volume = product["auto_provision_volume_gb"] if mode in ("full", "volume") else 0
        add_days = product["duration_days"] if mode in ("full", "time") else 0
        target_kind = item["kind"]
        target_id = item["custom"]["id"] if target_kind == "custom" else item["config"]["id"]
        price = product["price"]
        product_label = product["name"]

        if mode == "full" and target_kind == "custom":
            max_users = await _users_option(product)
            if max_users and not users:
                await call.answer()
                await _safe_edit(
                    call.message,
                    f"🔄 {_RENEW_MODE_LABEL[mode]} - {product['name']}\n\n"
                    "👥 تعداد کاربر همزمان را انتخاب کنید (قیمت پایه شامل ۱ کاربر است):",
                    reply_markup=kb.user_count_picker_kb(
                        product, max_users, f"svc_renew_pick:{mode}:{cb_id}:{product['id']}", f"svc_renew:{mode}:{cb_id}",
                    ),
                )
                return
            if not max_users or users > max_users:
                users = 0
            if not max_users:
                # محصول با تعداد کاربر ثابت: تعداد فعلی سرویس (بعد از ارتقاهای قبلی) حفظ و قیمت‌گذاری می‌شود
                users = await asyncio.to_thread(ul.renewal_users, db, product, item["custom"])
            if users:
                price = ul.price_for_users(product, users)
                product_label = f"{product['name']} - {users} کاربر"
        else:
            users = 0

        # تخفیف تمدید کامل زودهنگام: اگر ادمین فعال کرده باشد و تا انقضای
        # واقعی این سرویس حداکثر N روز مانده باشد، به‌صورت خودکار و بدون
        # نیاز به کد تخفیف روی قیمت پلن انتخاب‌شده اعمال می‌شود.
        if mode == "full" and target_kind == "custom":
            discount_settings = await asyncio.to_thread(db.get_early_full_renewal_discount_settings)
            if discount_settings["enabled"]:
                expires_at_raw = item["custom"]["expires_at"]
                if expires_at_raw:
                    try:
                        exp_dt = datetime.fromisoformat(expires_at_raw)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        days_left = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 86400
                        if 0 <= days_left <= discount_settings["days_before"]:
                            percent = discount_settings["percent"]
                            price = round(price * (100 - percent) / 100)
                            product_label = f"{product_label} (تخفیف تمدید زودهنگام {percent}٪)"
                    except (ValueError, TypeError):
                        pass

        await call.answer()

        # قابلیت ۵۱: فقط «تمدید کامل سرویس» یک صفحه‌ی تایید با امکان کد تخفیف
        # دارد (تمدید حجم/زمان بر اساس نرخ ثابت است، نه قیمت یک محصول واقعی،
        # پس معنای «کد تخفیف روی محصول» را ندارد).
        if mode == "full":
            renew_warning = ""
            if target_kind == "custom":
                renew_warning = renewal_log.warning_text(await renewal_log.service_snapshot(db, item["custom"]))
            await state.update_data(
                renew_full_ctx={
                    "cb_id": cb_id, "target_kind": target_kind, "target_id": target_id,
                    "add_volume": add_volume, "add_days": add_days, "price": price,
                    "product_label": product_label, "product_id": product["id"], "user_limit": users or None,
                    "warning": renew_warning,
                },
                renew_full_discount_code_id=None, renew_full_discount_amount=0, renew_full_discount_label=None,
            )
            await _safe_edit(
                call.message,
                _renewal_full_confirm_text(product_label, price, warning=renew_warning),
                reply_markup=kb.renewal_full_confirm_kb(db, cb_id),
            )
            return

        async def edit_fn(t, **kw):
            await _safe_edit(call.message, t, **kw)

        async def send_fn(t, **kw):
            await call.message.answer(t, **kw)

        await _process_renewal_order(
            user_tg_id, cb_id, mode, target_kind, target_id,
            add_volume, add_days, price, product_label, state, edit_fn, send_fn, call.bot, user_limit=users or None,
        )

    def _renewal_full_confirm_text(product_label: str, base_price: int, discount_amount: int = 0, discount_label: str = "", warning: str = "") -> str:
        text = db.get_text(
            "handlers_user.renewal.full_confirm_header",
            "🔄 تمدید کامل سرویس - {product_label}\n💰 مبلغ قابل پرداخت: {price} تومان\n",
        ).format(product_label=product_label, price=f"{base_price:,}")
        if warning:
            text += "\n" + warning
        if discount_amount > 0:
            text += db.get_text(
                "handlers_user.product.discount_code_line",
                "\n🎟 کد تخفیف «{label}» به‌صورت خودکار اعمال شد: -{amount} تومان\n",
            ).format(label=discount_label, amount=f"{discount_amount:,}")
            total = max(base_price - discount_amount, 0)
            text += db.get_text(
                "handlers_user.product.discount_total_after_line", "💵 مبلغ پس از تخفیف: {total} تومان\n"
            ).format(total=f"{total:,}")
        return text

    @router.callback_query(F.data.startswith("renew_enter_code:"))
    async def cb_renew_enter_code(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        ctx = data.get("renew_full_ctx")
        cb_id = call.data.split(":", 1)[1]
        if not ctx or ctx.get("cb_id") != cb_id:
            await call.answer(db.get_text(
                "handlers_user.renewal.step_expired", "این مرحله منقضی شده؛ دوباره از منو اقدام کنید."
            ), show_alert=True)
            return
        await state.set_state(RenewalDiscountEntry.waiting_code)
        await _safe_edit(
            call.message,
            db.get_text("handlers_user.auto_506f789e", "🎟 کد تخفیف را ارسال کنید:"),
            reply_markup=kb.cancel_kb(),
        )
        await call.answer()

    @router.message(RenewalDiscountEntry.waiting_code)
    async def process_renewal_discount_code(message: Message, state: FSMContext):
        data = await state.get_data()
        ctx = data.get("renew_full_ctx")
        if not ctx:
            await message.answer(db.get_text(
                "handlers_user.renewal.step_expired", "این مرحله منقضی شده؛ دوباره از منو اقدام کنید."
            ))
            await state.set_state(None)
            return
        base_price = ctx["price"]
        code_row = (await asyncio.to_thread(db.get_discount_code, message.text.strip()))
        invalid_reason = (await asyncio.to_thread(
            db.get_discount_invalid_reason, code_row, base_price, ctx["product_id"], user_id=message.from_user.id
        ))
        if invalid_reason:
            await message.answer(
                db.get_text(
                    "handlers_user.discount.invalid_reason_retry", "❌ {reason}\nدوباره تلاش کنید یا بدون کد ادامه دهید."
                ).format(reason=invalid_reason),
                reply_markup=kb.cancel_kb(),
            )
            return
        discount_amount = (await asyncio.to_thread(db.compute_discount_amount, code_row, base_price))
        await state.update_data(
            renew_full_discount_code_id=code_row["id"], renew_full_discount_amount=discount_amount,
            renew_full_discount_label=code_row["code"],
        )
        await state.set_state(None)
        await message.answer(
            db.get_text("handlers_user.discount.applied_title", "✅ کد تخفیف اعمال شد!") + "\n\n" +
            _renewal_full_confirm_text(ctx["product_label"], base_price, discount_amount, code_row["code"], ctx.get("warning", "")),
            reply_markup=kb.renewal_full_confirm_kb(db, ctx["cb_id"]),
        )

    @router.callback_query(F.data.startswith("renew_confirm_pay:"))
    async def cb_renew_confirm_pay(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        ctx = data.get("renew_full_ctx")
        cb_id = call.data.split(":", 1)[1]
        if not ctx or ctx.get("cb_id") != cb_id:
            await call.answer(db.get_text(
                "handlers_user.renewal.step_expired", "این مرحله منقضی شده؛ دوباره از منو اقدام کنید."
            ), show_alert=True)
            return
        discount_code_id = data.get("renew_full_discount_code_id")
        discount_amount = data.get("renew_full_discount_amount", 0) or 0
        if discount_code_id:
            claimed = await asyncio.to_thread(db.claim_discount_use, discount_code_id, call.from_user.id)
            if not claimed:
                await state.update_data(
                    renew_full_discount_code_id=None, renew_full_discount_amount=0, renew_full_discount_label=None,
                )
                await call.answer(db.get_text(
                    "handlers_user.auto_ca864ddb", "این کد تخفیف دیگر برای شما قابل استفاده نیست. دوباره تلاش کنید."
                ), show_alert=True)
                return
        await call.answer()
        await state.update_data(
            renew_full_ctx=None, renew_full_discount_code_id=None, renew_full_discount_amount=0,
            renew_full_discount_label=None,
        )

        async def edit_fn(t, **kw):
            await _safe_edit(call.message, t, **kw)

        async def send_fn(t, **kw):
            await call.message.answer(t, **kw)

        await _process_renewal_order(
            call.from_user.id, cb_id, "full", ctx["target_kind"], ctx["target_id"],
            ctx["add_volume"], ctx["add_days"], ctx["price"], ctx["product_label"], state, edit_fn, send_fn, call.bot,
            user_limit=ctx["user_limit"], discount_code_id=discount_code_id, discount_amount=discount_amount,
        )

    @router.callback_query(F.data == "pay_card2card", RenewalFlow.waiting_receipt)
    async def cb_pay_card2card_renewal(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        await call.answer()
        intro_lines = [f"🔄 {_RENEW_MODE_LABEL[order['renewal_mode']]}"]
        if order["wallet_used"]:
            intro_lines.append(f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان")
        await _send_card2card_details(call.message, intro_lines, order["final_price"])

    @router.callback_query(F.data == "pay_card_auto", RenewalFlow.waiting_receipt)
    async def cb_pay_card_auto_renewal(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        await call.answer()
        intro_lines = [f"🔄 {_RENEW_MODE_LABEL[order['renewal_mode']]}"]
        if order["wallet_used"]:
            intro_lines.append(f"👛 استفاده از کیف پول: {order['wallet_used']:,} تومان")
        await _send_card_auto_details(
            call.message, intro_lines, "order", order_id, call.from_user.id, order["final_price"],
        )

    @router.callback_query(F.data == "pay_crypto", RenewalFlow.waiting_receipt)
    async def cb_pay_crypto_renewal(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await crypto_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"تمدید سرویس #{order_id}",
            )
        except crypto_payment.CryptoPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        await call.message.answer(
            db.get_text('handlers_user.auto_d456f435', '🪙 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.\n⏳ اعتبار این فاکتور فقط ۸۰ دقیقه است.\nبه\u200cمحض تایید تراکنش روی بلاک\u200cچین، سرویس شما به\u200cصورت خودکار تمدید می\u200cشود.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data == "pay_abangateway", RenewalFlow.waiting_receipt)
    async def cb_pay_abangateway_renewal(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await abangateway_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"تمدید سرویس #{order_id}",
            )
        except abangateway_payment.AbanGatewayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_abangateway_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_c5283e58', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، سرویس خودکار تمدید می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_aban:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_blupal", RenewalFlow.waiting_receipt)
    async def cb_pay_blupal_renewal(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await blupal_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"تمدید سرویس #{order_id}",
            )
        except blupal_payment.BluPalPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_blupal_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_c5283e58', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، سرویس خودکار تمدید می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_blupal:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_noapay", RenewalFlow.waiting_receipt)
    async def cb_pay_noapay_renewal(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await noapay_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "order", order_id, order["final_price"],
                order_name=f"تمدید سرویس #{order_id}",
            )
        except noapay_payment.NoapayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_noapay_invoice_by_token, result["invoice_token"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_3090acc2', '⭐ فاکتور پرداخت (NoapayBot) ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، سرویس خودکار تمدید می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_noapay:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data.startswith("pay_customgw:"), RenewalFlow.waiting_receipt)
    async def cb_pay_customgw_renewal(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), show_alert=True)
            return
        gw_row = (await asyncio.to_thread(db.get_custom_gateway, int(call.data.split(":", 1)[1])))
        if not gw_row or not gw_row["enabled"]:
            await call.answer(db.get_text('handlers_user.auto_e29914cb', 'این درگاه در دسترس نیست.'), show_alert=True)
            return
        await call.answer()
        if await _start_customgw_payment(
            call.message, state, RenewalFlow.waiting_customgw_phone, gw_row,
            prompt_prefix="⏳ در حال آماده‌سازی فاکتور...",
        ):
            return
        await call.message.answer(db.get_text('handlers_user.auto_9bbc7040', '⏳ در حال ساخت فاکتور...'))
        await _send_customgw_invoice(
            call.message, gw_row, "order", order_id, call.from_user.id, order["final_price"],
            order_name=f"تمدید سرویس #{order_id}",
            customer_phone=None, noun="سرویس", verb="تمدید می‌شود",
        )

    @router.message(RenewalFlow.waiting_customgw_phone, F.contact)
    async def receive_customgw_phone_renewal(message: Message, state: FSMContext):
        if not message.contact or message.contact.user_id != message.from_user.id:
            await message.answer(db.get_text('handlers_user.auto_78cc91ac', '❌ لطفاً با زدن همون دکمه\u200cی «اشتراک\u200cگذاری شماره موبایل» شماره\u200cی خودت رو بفرست.'))
            return
        data = await state.get_data()
        order_id = data.get("order_id")
        gw_id = data.get("customgw_gateway_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        gw_row = (await asyncio.to_thread(db.get_custom_gateway, gw_id)) if gw_id else None
        if not order or order["status"] != "pending" or not gw_row or not gw_row["enabled"]:
            await message.answer(db.get_text("handlers_user.order.not_found", "سفارش معتبر یافت نشد."), reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return
        await state.set_state(RenewalFlow.waiting_receipt)
        await message.answer(db.get_text('handlers_user.auto_9bbc7040', '⏳ در حال ساخت فاکتور...'), reply_markup=ReplyKeyboardRemove())
        await _send_customgw_invoice(
            message, gw_row, "order", order_id, message.from_user.id, order["final_price"],
            order_name=f"تمدید سرویس #{order_id}",
            customer_phone=message.contact.phone_number, noun="سرویس", verb="تمدید می‌شود",
        )

    @router.message(RenewalFlow.waiting_customgw_phone, F.text == "❌ انصراف")
    async def cancel_customgw_phone_renewal(message: Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        if order_id:
            order = (await asyncio.to_thread(db.get_order, order_id))
            if order and order["status"] == "pending":
                (await asyncio.to_thread(db.reject_order, order_id))
        await state.clear()
        await message.answer(db.get_text('handlers_user.auto_570dedda', 'عملیات لغو شد.'), reply_markup=ReplyKeyboardRemove())

    @router.message(RenewalFlow.waiting_customgw_phone)
    async def receive_customgw_phone_invalid_renewal(message: Message):
        await message.answer(
            db.get_text('handlers_user.auto_3cb5d7ba', '📱 لطفاً با زدن دکمه\u200cی «اشتراک\u200cگذاری شماره موبایل» ادامه بده، یا انصراف بده.'),
            reply_markup=kb.share_phone_kb(),
        )

    @router.message(RenewalFlow.waiting_receipt, F.photo | F.document)
    async def receive_renewal_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order or order["status"] != "pending":
            await message.answer(db.get_text('handlers_user.auto_32ccba24', 'سفارش معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return
        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_order_receipt, order_id, file_id, receipt_type))
        await _notify_admins_of_order(bot, order_id, receipt_file_id=file_id, receipt_type=receipt_type)
        await message.answer(
            db.get_text('handlers_user.auto_925daaf0', '✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، سرویس شما تمدید خواهد شد.'),
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        await state.clear()

    @router.message(RenewalFlow.waiting_receipt)
    async def renewal_receipt_wrong_type(message: Message):
        await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))

    # -----------------------------------------------------------------------
    # زیرمجموعه‌گیری (رفرال)
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_referral"), tr(db.get_setting("btn_referral")))))
    async def referral_menu(message: Message, bot: Bot):
        settings = (await asyncio.to_thread(db.get_all_settings))
        if settings.get("referral_button_enabled", "1") != "1":
            await message.answer(db.get_text('handlers_user.auto_623932c0', 'در حال حاضر سیستم زیرمجموعه\u200cگیری غیرفعال است.'))
            return
        commission_on = settings.get("referral_enabled", "1") == "1"
        freeconfig_on = settings.get("referral_free_config_enabled", "0") == "1"
        invitebonus_on = settings.get("referral_invite_bonus_enabled", "0") == "1"

        if not (commission_on or freeconfig_on or invitebonus_on):
            await message.answer(db.get_text('handlers_user.auto_623932c0', 'در حال حاضر سیستم زیرمجموعه\u200cگیری غیرفعال است.'))
            return

        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=ref{message.from_user.id}"
        stats = (await asyncio.to_thread(db.get_referral_stats, message.from_user.id))

        lines = ["🤝 سیستم زیرمجموعه‌گیری", "", f"لینک اختصاصی دعوت شما:\n{link}", ""]
        if commission_on:
            percent = settings.get("referral_percent", "10")
            max_count = int(settings.get("referral_commission_max_count", "0") or 0)
            cap_text = f" (فقط برای {max_count} نفر اول از زیرمجموعه‌هایی که خرید می‌کنند)" if max_count > 0 else ""
            lines.append(
                f"💳 هر کاربری که با این لینک وارد بات شود و اولین خریدش تایید شود، {percent}٪ از مبلغ "
                f"پرداختی او به‌صورت اعتبار کیف پول به شما تعلق می‌گیرد{cap_text}."
            )
        if freeconfig_on:
            threshold = settings.get("referral_free_config_threshold", "10")
            lines.append(f"🎁 با دعوت {threshold} نفر (حتی بدون خرید آن‌ها)، یک کانفیگ رایگان دریافت می‌کنید.")
        if invitebonus_on:
            amount = settings.get("referral_invite_bonus_amount", "0")
            ib_max = int(settings.get("referral_invite_bonus_max_count", "0") or 0)
            cap_text = f" (فقط برای {ib_max} دعوت اول)" if ib_max > 0 else ""
            lines.append(f"💰 با دعوت هر نفر (حتی بدون خرید)، {int(amount):,} تومان به کیف پول شما اضافه می‌شود{cap_text}.")

        lines.append("")
        lines.append(f"👥 تعداد زیرمجموعه‌های شما: {stats['count']}")
        lines.append(f"👛 موجودی کیف پول شما: {stats['credit']:,} تومان")

        await message.answer(
            "\n".join(lines),
            reply_markup=kb.referral_share_kb(link),
        )

    # -----------------------------------------------------------------------
    # لینک نمایندگی - «لینک اختصاصی داخل بات اصلی» (بند ۳.۱ اسپک)
    # -----------------------------------------------------------------------

    @router.message(Command("reseller_link"))
    async def inline_reseller_link(message: Message, bot: Bot):
        if not (await asyncio.to_thread(db.is_inline_reseller, message.from_user.id)):
            return
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=resref_{message.from_user.id}"
        stats = (await asyncio.to_thread(db.get_inline_reseller_stats, message.from_user.id))
        percent = stats["percent"]
        await message.answer(
            tr("🔗 نمایندگی کمیسیونی شما (لینک اختصاصی داخل بات)\n\n"
            f"لینک فروش شما:\n{link}\n\n"
            f"روی هر خرید مشتریانی که با این لینک وارد شده‌اند، {percent}٪ کارمزد به کیف پول شما اضافه می‌شود.\n\n"
            f"👥 تعداد مشتریان شما: {stats['customers']}\n"
            f"🧾 تعداد خریدهای تسویه‌شده: {stats['paid_orders']}\n"
            f"👛 مجموع کارمزد دریافتی: {stats['total_commission']:,} تومان")
        )

    # -----------------------------------------------------------------------
    # درخواست نمایندگی کمیسیونی (مستقل کامل از نمایندگی حجمی؛ بدون حجم،
    # بدون محصول آماده - فقط یک درصد کمیسیون که ادمین تایید/رد می‌کند و در
    # صورت تایید، تا وقتی ادمین غیرفعالش نکند روی همه‌ی خریدهای بعدی می‌ماند)
    # -----------------------------------------------------------------------

    async def commission_reseller_request_start(message: Message, state: FSMContext):
        if not is_main_bot:
            return
        if (await asyncio.to_thread(db.is_inline_reseller, message.from_user.id)):
            await message.answer(
                db.get_text('handlers_user.auto_16eed31a', 'شما همین الان هم نماینده\u200cی کمیسیونی هستید. برای دیدن لینک و آمار خودتان، دستور /reseller_link را بفرستید.')
            )
            return
        pending = (await asyncio.to_thread(db.get_pending_commission_reseller_request_for_user, message.from_user.id))
        if pending:
            await message.answer(
                tr(f"شما همین الان یک درخواست نمایندگی کمیسیونی باز دارید (درصد پیشنهادی: {pending['proposed_percent']}٪)؛ "
                "منتظر بررسی ادمین بمانید.")
            )
            return
        await state.set_state(CommissionResellerRequestFlow.waiting_percent)
        await message.answer(
            db.get_text('handlers_user.auto_4cf1fe86', '💼 درخواست نمایندگی کمیسیونی\n\nاین نوع نمایندگی بدون حجم و بدون محصول آماده است؛ فقط یک لینک اختصاصی فروش می\u200cگیرید و روی هر خرید مشتریانی که از طریق آن لینک وارد شوند، درصدی کمیسیون به کیف پول شما اضافه می\u200cشود — تا زمانی که ادمین نمایندگی\u200cتان را غیرفعال کند.\n\nچند درصد کمیسیون پیشنهاد می\u200cدهید؟ فقط عدد بین ۱ تا ۱۰۰ ارسال کنید (مثلاً 10):'),
            reply_markup=kb.cancel_kb(),
        )

    @router.message(CommissionResellerRequestFlow.waiting_percent)
    async def commission_reseller_request_percent(message: Message, state: FSMContext, bot: Bot):
        text = (message.text or "").strip()
        if not text.isdigit() or not (1 <= int(text) <= 100):
            await message.answer(db.get_text('handlers_user.auto_15bcc016', 'لطفاً یک عدد صحیح بین ۱ تا ۱۰۰ ارسال کنید.'))
            return
        percent = int(text)
        await state.clear()
        user_id = message.from_user.id

        request_id = (await asyncio.to_thread(db.create_commission_reseller_request, user_id, percent))
        if not request_id:
            await message.answer(
                db.get_text('handlers_user.auto_808723f4', '⚠️ ثبت درخواست ممکن نشد؛ شاید همین الان نماینده\u200cی کمیسیونی هستید یا یک درخواست باز دیگر دارید.'),
                reply_markup=kb.menu_for_user(db, user_id, is_main_bot),
            )
            await _send_inline_main_menu(message, user_id)
            return

        user_row = (await asyncio.to_thread(db.get_user, user_id))
        first_name = (user_row["first_name"] if user_row else "") or ""
        username = (user_row["username"] if user_row else "") or "---"
        caption = (
            f"💼 درخواست نمایندگی کمیسیونی #{request_id}\n"
            f"👤 کاربر: {first_name} (@{username})\n"
            f"🆔 آیدی عددی: {user_id}\n"
            f"📊 درصد پیشنهادی: {percent}٪"
            f"{await _switch_warning_line(user_id, 'bronze')}\n\n"
            "این نمایندگی بدون حجم و بدون محصول آماده است؛ فقط کمیسیون دائمی روی خریدهای زیرمجموعه."
        )
        for admin_id in _senior_admin_ids():
            try:
                await bot.send_message(admin_id, caption, reply_markup=kb.commission_reseller_request_review_kb(request_id))
            except Exception:
                pass

        await message.answer(
            db.get_text('handlers_user.auto_b97f74bf', '✅ درخواست نمایندگی کمیسیونی شما ثبت شد. پس از بررسی ادمین، نتیجه (تایید یا رد به همراه علت) برایتان ارسال می\u200cشود.'),
            reply_markup=kb.menu_for_user(db, user_id, is_main_bot),
        )
        await _send_inline_main_menu(message, user_id)

    # -----------------------------------------------------------------------
    # کیف پول (جدا از زیرمجموعه‌گیری)
    # -----------------------------------------------------------------------

    async def _wallet_text(user_id: int) -> str:
        st = await asyncio.to_thread(db.get_wallet_status, user_id)
        text = (
            "👛 کیف پول شما\n\n"
            f"موجودی فعلی: {st['balance']:,} تومان\n"
        )
        if st["limit"] > 0 or st["debt"] > 0:
            text += (
                f"💳 سقف اعتبار پس‌پرداخت: {st['limit']:,} تومان\n"
                f"📉 بدهی فعلی: {st['debt']:,} تومان\n"
                f"✅ اعتبار قابل استفاده: {max(st['spendable'], 0):,} تومان\n"
            )
        text += "\nاین موجودی (چه از شارژ دستی، چه از پورسانت زیرمجموعه‌گیری) به‌صورت خودکار در خرید بعدی شما کسر می‌شود."
        expiring = await asyncio.to_thread(db.get_wallet_credit_expiry_lines, user_id)
        for day, amount in expiring:
            text += f"\n⏳ {amount:,} تومان از موجودی شما (حاصل از تبدیل سکه) تا {to_jalali_str(day)} معتبر است."
        return text

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_wallet"), tr(db.get_setting("btn_wallet")))))
    async def wallet_menu(message: Message):
        await message.answer(await _wallet_text(message.from_user.id), reply_markup=kb.wallet_menu_kb(db))

    async def _coins_view(user_id: int):
        s = await asyncio.to_thread(db.get_coin_settings)
        coins = await asyncio.to_thread(db.get_user_score, user_id)
        mode = await asyncio.to_thread(db.get_user_coin_mode, user_id)
        lines = ["🪙 سکه‌های شما", "", f"موجودی سکه: {coins:,}"]
        for day, amount in await asyncio.to_thread(db.get_coin_expiry_lines, user_id):
            lines.append(f"⏳ {amount:,} سکه تا {to_jalali_str(day)} معتبر است.")
        if s["value"] > 0:
            lines.append(f"ارزش هر سکه: {s['value']:,} تومان (جمعاً {coins * s['value']:,} تومان)")
        lines.append("")
        if mode == "lottery":
            lines += [
                "حالت فعلی: 🎟 شرکت در قرعه‌کشی شبانه",
                f"اگر حداقل {s['lottery_min']:,} سکه داشته باشید، در قرعه‌کشی ساعت ۰۰:۰۰ شرکت داده می‌شوید. "
                "سکه‌ی شرکت‌کنندگان بعد از هر قرعه‌کشی صفر می‌شود.",
            ]
        else:
            lines.append("حالت فعلی: 💰 تبدیل به موجودی کیف پول")
            if s["value"] > 0:
                limit = f"{s['convert_max']:,}" if s["convert_max"] else "بدون سقف"
                lines.append(f"در هر تبدیل حداقل {s['convert_min']:,} و حداکثر {limit} سکه می‌توانید تبدیل کنید.")
            else:
                lines.append("تبدیل سکه به موجودی هنوز توسط ادمین فعال نشده است.")
        can_convert = s["value"] > 0 and coins >= s["convert_min"]
        return "\n".join(lines), kb.coins_menu_kb(mode, can_convert)

    @router.callback_query(F.data == "coins_menu")
    async def cb_coins_menu(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "score_enabled", "1")) != "1":
            await call.answer(tr("سیستم سکه در حال حاضر غیرفعال است."), show_alert=True)
            return
        await state.clear()
        text, markup = await _coins_view(call.from_user.id)
        await _safe_edit(call.message, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "coins_back")
    async def cb_coins_back(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await _safe_edit(call.message, await _wallet_text(call.from_user.id), reply_markup=kb.wallet_menu_kb(db))
        await call.answer()

    @router.callback_query(F.data.startswith("coins_mode:"))
    async def cb_coins_mode(call: CallbackQuery):
        await asyncio.to_thread(db.set_user_coin_mode, call.from_user.id, call.data.split(":", 1)[1])
        text, markup = await _coins_view(call.from_user.id)
        await _safe_edit(call.message, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    @router.callback_query(F.data == "coins_convert")
    async def cb_coins_convert(call: CallbackQuery, state: FSMContext):
        s = await asyncio.to_thread(db.get_coin_settings)
        coins = await asyncio.to_thread(db.get_user_score, call.from_user.id)
        mode = await asyncio.to_thread(db.get_user_coin_mode, call.from_user.id)
        if not s["enabled"] or s["value"] <= 0 or mode != "wallet" or coins < s["convert_min"]:
            await call.answer(tr("در حال حاضر امکان تبدیل سکه وجود ندارد."), show_alert=True)
            return
        limit = f"{s['convert_max']:,}" if s["convert_max"] else "بدون سقف"
        await state.set_state(CoinConvert.waiting_amount)
        await _safe_edit(
            call.message,
            f"💰 چند سکه را می‌خواهید تبدیل کنید؟ فقط عدد ارسال کنید.\n"
            f"موجودی سکه: {coins:,}\n"
            f"حداقل: {s['convert_min']:,} | حداکثر: {limit}\n"
            f"ارزش هر سکه: {s['value']:,} تومان",
            reply_markup=kb.cancel_kb(),
        )
        await call.answer()

    @router.message(CoinConvert.waiting_amount)
    async def process_coin_convert(message: Message, state: FSMContext):
        text = (message.text or "").strip().replace(",", "").replace("٬", "")
        if not text.isdigit() or int(text) <= 0:
            await message.answer(tr("⚠️ یک عدد صحیح مثبت ارسال کنید."), reply_markup=kb.cancel_kb())
            return
        try:
            result = await asyncio.to_thread(db.convert_coins_to_wallet, message.from_user.id, int(text))
        except ValueError as e:
            await message.answer(tr(f"❌ {e}\nدوباره تلاش کنید یا انصراف بدهید."), reply_markup=kb.cancel_kb())
            return
        await state.clear()
        balance = await asyncio.to_thread(db.get_wallet_credit, message.from_user.id)
        await message.answer(
            f"✅ {result['coins']:,} سکه به {result['amount']:,} تومان تبدیل و به کیف پول شما اضافه شد.\n"
            f"سکه‌ی باقی‌مانده: {result['coins_left']:,}\n"
            f"موجودی کیف پول: {balance:,} تومان"
            + (f"\n⏳ این مبلغ تا {to_jalali_str(result['expires_at'])} معتبر است." if result.get("expires_at") else ""),
            reply_markup=kb.wallet_menu_kb(db),
        )

    # -----------------------------------------------------------------------
    # گردونه شانس
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_wheel"), tr(db.get_setting("btn_wheel")))))
    async def wheel_of_fortune(message: Message, bot: Bot):
        if (await asyncio.to_thread(db.get_setting, "wheel_enabled", "1")) != "1":
            await message.answer(db.get_text('handlers_user.auto_ea150277', 'در حال حاضر گردونه شانس غیرفعال است.'))
            return

        can_spin, remaining_hours = (await asyncio.to_thread(db.can_spin_wheel, message.from_user.id))
        if not can_spin:
            hours = int(remaining_hours) + 1
            await message.answer(tr(f"⏳ فردا دوباره امتحان کن! حدود {hours} ساعت دیگر می‌توانی دوباره گردونه را بچرخانی."))
            return

        # افکت چرخش: انیمیشن اسلات‌ماشین بومی تلگرام
        try:
            await bot.send_dice(message.chat.id, emoji="🎰")
        except Exception:
            await message.answer(db.get_text('handlers_user.auto_63102316', '🎡 در حال چرخش گردونه...'))
        await asyncio.sleep(2.5)

        (await asyncio.to_thread(db.record_wheel_spin, message.from_user.id))

        settings = (await asyncio.to_thread(db.get_wheel_settings))
        won = random.randint(1, 100) <= settings["win_percent"]

        if won and settings["prizes"]:
            percent = random.choice(settings["prizes"])
            code, expires_at = (await asyncio.to_thread(db.generate_wheel_prize_code, message.from_user.id, percent))
            await message.answer(
                tr(f"🎉 تبریک! برنده شدی!\n\n"
                f"🎟 کد تخفیف {percent}٪ شما:\n`{code}`\n\n"
                f"⏳ اعتبار: تا {settings['expiry_hours']} ساعت آینده\n"
                f"این کد یکبارمصرف است و در خرید بعدی‌ات قابل استفاده است."),
                parse_mode="Markdown",
            )
        else:
            await message.answer(db.get_text('handlers_user.auto_93ef7080', '😔 امروز شانس با تو نبود! فردا دوباره امتحان کن.'))

    @router.callback_query(F.data == "wallet_history")
    async def cb_wallet_history(call: CallbackQuery):
        rows = await asyncio.to_thread(db.get_wallet_transactions, call.from_user.id, 10)
        text = await asyncio.to_thread(db.wallet_transactions_text, rows)
        await call.message.answer("📜 ۱۰ تراکنش آخر کیف پول:\n\n" + text, reply_markup=kb.wallet_menu_kb(db))
        await call.answer()

    @router.callback_query(F.data == "wallet_gift_code")
    async def cb_wallet_gift_code(call: CallbackQuery, state: FSMContext):
        await state.set_state(WalletGiftCode.waiting_code)
        await _safe_edit(call.message, db.get_text('handlers_user.auto_4ccdd5c4', '🎁 کد هدیه را ارسال کنید:'), reply_markup=kb.cancel_kb())
        await call.answer()

    @router.message(WalletGiftCode.waiting_code)
    async def process_wallet_gift_code(message: Message, state: FSMContext):
        code = message.text.strip()
        try:
            result = await asyncio.to_thread(db.redeem_wallet_gift_code, message.from_user.id, code)
        except ValueError as e:
            await message.answer(tr(f"❌ {e}\nدوباره تلاش کنید یا انصراف بدهید."), reply_markup=kb.cancel_kb())
            return
        await state.clear()
        await message.answer(
            tr(f"✅ {result['amount']:,} تومان به کیف پول شما اضافه شد.\n"
            f"موجودی فعلی: {result['new_balance']:,} تومان"),
            reply_markup=kb.wallet_menu_kb(db),
        )

    @router.callback_query(F.data == "wallet_transfer")
    async def cb_wallet_transfer(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "wallet_show_transfer", "1")) != "1":
            await call.answer(db.get_text('handlers_user.wallet_transfer_disabled', '⛔️ انتقال موجودی کیف پول در حال حاضر غیرفعال است.'), show_alert=True)
            return
        await state.set_state(WalletTransfer.waiting_receiver)
        await _safe_edit(call.message, db.get_text('handlers_user.auto_26ac40ee', '💸 آیدی عددی تلگرام کاربر مقصد را ارسال کنید:'), reply_markup=kb.cancel_kb())
        await call.answer()

    @router.message(WalletTransfer.waiting_receiver)
    async def process_wallet_transfer_receiver(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) == message.from_user.id:
            await message.answer(db.get_text('handlers_user.auto_280674ab', '⚠️ یک آیدی عددی معتبر (غیر از خودتان) ارسال کنید.'), reply_markup=kb.cancel_kb())
            return
        await state.update_data(transfer_receiver=int(text))
        await state.set_state(WalletTransfer.waiting_amount)
        balance = await asyncio.to_thread(db.get_wallet_credit, message.from_user.id)
        await message.answer(tr(f"مبلغ انتقال (تومان) را ارسال کنید.\nموجودی شما: {balance:,} تومان"), reply_markup=kb.cancel_kb())

    @router.message(WalletTransfer.waiting_amount)
    async def process_wallet_transfer_amount(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_user.auto_b867d968', '⚠️ یک عدد صحیح مثبت ارسال کنید.'), reply_markup=kb.cancel_kb())
            return
        data = await state.get_data()
        receiver = data.get("transfer_receiver")
        amount = int(text)
        await state.clear()
        ok = await asyncio.to_thread(db.transfer_wallet, message.from_user.id, receiver, amount)
        if not ok:
            await message.answer(db.get_text('handlers_user.auto_3c6c92ee', '⛔️ انتقال ناموفق بود؛ موجودی یا کاربر مقصد را بررسی کنید.'), reply_markup=kb.wallet_menu_kb(db))
            return
        balance = await asyncio.to_thread(db.get_wallet_credit, message.from_user.id)
        await message.answer(tr(f"✅ {amount:,} تومان منتقل شد.\nموجودی فعلی: {balance:,} تومان"), reply_markup=kb.wallet_menu_kb(db))
        await _notify_admins_wallet_transfer(message.bot, message.from_user.id, receiver, amount)
        try:
            await message.bot.send_message(receiver, tr(f"💸 {amount:,} تومان از طرف یک کاربر به کیف پول شما منتقل شد."))
        except Exception:
            pass

    @router.callback_query(F.data == "start_topup")
    async def cb_start_topup(call: CallbackQuery, state: FSMContext):
        min_topup = int((await asyncio.to_thread(db.get_setting, "min_amount_wallet_topup", "1000")) or "1000")
        cap_line = await _wallet_topup_cap_line(call.from_user.id)
        await state.set_state(WalletTopup.waiting_amount)
        await _safe_edit(
            call.message,
            f"💰 چه مبلغی (به تومان) می‌خواهید به کیف پول خود شارژ کنید؟ فقط عدد ارسال کنید (مثال: 100000):\n"
            f"حداقل مبلغ شارژ: {min_topup:,} تومان{cap_line}",
            reply_markup=kb.cancel_kb(),
        )
        await call.answer()

    @router.message(WalletTopup.waiting_amount)
    async def process_topup_amount(message: Message, state: FSMContext):
        min_topup = int((await asyncio.to_thread(db.get_setting, "min_amount_wallet_topup", "1000")) or "1000")
        text = message.text.strip().replace(",", "")
        if not text.isdigit() or int(text) < min_topup:
            await message.answer(tr(f"لطفاً یک عدد معتبر و حداقل {min_topup:,} تومان ارسال کنید."))
            return

        amount = int(text)

        max_balance = int((await asyncio.to_thread(db.get_setting, "max_wallet_balance", "0")) or "0")
        if max_balance > 0:
            current_balance = await asyncio.to_thread(db.get_wallet_credit, message.from_user.id)
            if current_balance + amount > max_balance:
                remaining = max(max_balance - current_balance, 0)
                await message.answer(
                    tr(f"⛔️ با این شارژ، موجودی کیف پول شما از سقف مجاز ({max_balance:,} تومان) بیشتر می‌شود.\n"
                    f"حداکثر مبلغ قابل شارژ فعلی: {remaining:,} تومان.")
                )
                return

        wallet_allowed_methods = (await asyncio.to_thread(db.get_wallet_topup_payment_methods))

        if not (await asyncio.to_thread(db.has_any_payable_method, amount, wallet_allowed_methods)):
            await message.answer(
                db.get_text('handlers_user.auto_b6a66c09', '⛔️ در حال حاضر هیچ روش پرداخت فعالی برای این مبلغ در دسترس نیست. لطفاً مبلغ دیگری وارد کنید یا بعداً تلاش کنید.')
            )
            return

        await state.update_data(topup_amount=amount)
        await state.set_state(WalletTopup.waiting_receipt)

        text = f"💰 مبلغ شارژ: {amount:,} تومان\n\nلطفاً روش پرداخت را انتخاب کنید:"
        await message.answer(
            text, parse_mode="Markdown",
            reply_markup=kb.payment_choice_kb(
                crypto_payment.crypto_payment_available(db),
                abangateway_payment.abangateway_payment_available(db),
                custom_gateway_payment.list_enabled_gateways(db),
                (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) == "1",
                card_auto_enabled=(await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) == "1",
                amount=amount,
                db=db,
                allowed_methods=wallet_allowed_methods,
                noapay_enabled=noapay_payment.noapay_payment_available(db),
                blupal_enabled=blupal_payment.blupal_payment_available(db),
                extra_gateways=extra_gateway_payment.available_keys(db, is_main_bot),
            ),
        )

    @router.callback_query(F.data == "pay_card2card", WalletTopup.waiting_receipt)
    async def cb_pay_card2card_topup(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer(db.get_text('handlers_user.auto_7b34cb6f', 'درخواست شارژ معتبر یافت نشد.'), show_alert=True)
            return
        err = await _wallet_topup_method_error(amount, "card")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        await _send_card2card_details(call.message, [], amount)

    @router.callback_query(F.data == "pay_card_auto", WalletTopup.waiting_receipt)
    async def cb_pay_card_auto_topup(call: CallbackQuery, state: FSMContext):
        if (await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0")) != "1":
            await call.answer(db.get_text("handlers_user.payment.method_disabled", "این روش پرداخت در حال حاضر غیرفعال است."), show_alert=True)
            return
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer(db.get_text('handlers_user.auto_7b34cb6f', 'درخواست شارژ معتبر یافت نشد.'), show_alert=True)
            return
        err = await _wallet_topup_method_error(amount, "card_auto")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        topup_id = (await asyncio.to_thread(db.create_topup, call.from_user.id, amount))
        await _send_card_auto_details(call.message, [], "wallet_topup", topup_id, call.from_user.id, amount)

    @router.callback_query(F.data == "pay_crypto", WalletTopup.waiting_receipt)
    async def cb_pay_crypto_topup(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer(db.get_text('handlers_user.auto_70b436a3', 'درخواست معتبر یافت نشد.'), show_alert=True)
            return
        err = await _wallet_topup_method_error(amount, "crypto")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        topup_id = (await asyncio.to_thread(db.create_topup, call.from_user.id, amount))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await crypto_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "wallet_topup", topup_id, amount,
                order_name=f"شارژ کیف پول #{topup_id}",
            )
        except crypto_payment.CryptoPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        await call.message.answer(
            db.get_text('handlers_user.auto_18b31b92', '🪙 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.\n⏳ اعتبار این فاکتور فقط ۸۰ دقیقه است.\nبه\u200cمحض تایید تراکنش روی بلاک\u200cچین، کیف پول شما به\u200cصورت خودکار شارژ می\u200cشود.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data == "pay_abangateway", WalletTopup.waiting_receipt)
    async def cb_pay_abangateway_topup(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer(db.get_text('handlers_user.auto_70b436a3', 'درخواست معتبر یافت نشد.'), show_alert=True)
            return
        err = await _wallet_topup_method_error(amount, "abangateway")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        topup_id = (await asyncio.to_thread(db.create_topup, call.from_user.id, amount))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await abangateway_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "wallet_topup", topup_id, amount,
                order_name=f"شارژ کیف پول #{topup_id}",
            )
        except abangateway_payment.AbanGatewayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_abangateway_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_463bed92', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، کیف پول خودکار شارژ می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_aban:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_blupal", WalletTopup.waiting_receipt)
    async def cb_pay_blupal_topup(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer(db.get_text('handlers_user.auto_70b436a3', 'درخواست معتبر یافت نشد.'), show_alert=True)
            return
        err = await _wallet_topup_method_error(amount, "blupal")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        topup_id = (await asyncio.to_thread(db.create_topup, call.from_user.id, amount))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await blupal_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "wallet_topup", topup_id, amount,
                order_name=f"شارژ کیف پول #{topup_id}",
            )
        except blupal_payment.BluPalPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_blupal_invoice_by_invoice_id, result["invoice_id"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_463bed92', '💳 فاکتور پرداخت ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، کیف پول خودکار شارژ می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_blupal:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data == "pay_noapay", WalletTopup.waiting_receipt)
    async def cb_pay_noapay_topup(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer(db.get_text('handlers_user.auto_70b436a3', 'درخواست معتبر یافت نشد.'), show_alert=True)
            return
        err = await _wallet_topup_method_error(amount, "noapay")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer(db.get_text("handlers_user.payment.creating_invoice", "در حال ساخت فاکتور..."))
        topup_id = (await asyncio.to_thread(db.create_topup, call.from_user.id, amount))
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        try:
            result = await noapay_payment.create_invoice_for(
                db, tenant_id, call.from_user.id, "wallet_topup", topup_id, amount,
                order_name=f"شارژ کیف پول #{topup_id}",
            )
        except noapay_payment.NoapayPaymentError as e:
            await call.message.answer(f"⚠️ {e}")
            return
        invoice_row = (await asyncio.to_thread(db.get_noapay_invoice_by_token, result["invoice_token"]))
        await call.message.answer(
            db.get_text('handlers_user.auto_205c37e7', '⭐ فاکتور پرداخت (NoapayBot) ساخته شد. روی دکمه\u200cی زیر بزن و پرداخت رو تکمیل کن.\nمعمولاً به\u200cمحض واریز، کیف پول خودکار شارژ می\u200cشود؛ اگر چند دقیقه طول کشید، دکمه\u200cی «بررسی وضعیت پرداخت» را بزن.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("🔗 رفتن به صفحه‌ی پرداخت"), url=result["payment_url"])],
                [InlineKeyboardButton(text=tr("🔄 بررسی وضعیت پرداخت"), callback_data=f"check_noapay:{invoice_row['id']}")],
            ]),
        )

    @router.callback_query(F.data.startswith("pay_customgw:"), WalletTopup.waiting_receipt)
    async def cb_pay_customgw_topup(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer(db.get_text('handlers_user.auto_70b436a3', 'درخواست معتبر یافت نشد.'), show_alert=True)
            return
        gw_row = (await asyncio.to_thread(db.get_custom_gateway, int(call.data.split(":", 1)[1])))
        if not gw_row or not gw_row["enabled"]:
            await call.answer(db.get_text('handlers_user.auto_e29914cb', 'این درگاه در دسترس نیست.'), show_alert=True)
            return
        err = await _wallet_topup_method_error(amount, f"custom:{gw_row['key']}")
        if err:
            await call.answer(err, show_alert=True)
            return
        await call.answer()
        if await _start_customgw_payment(
            call.message, state, WalletTopup.waiting_customgw_phone, gw_row,
            prompt_prefix="⏳ در حال آماده‌سازی فاکتور...",
        ):
            return
        await call.message.answer(db.get_text('handlers_user.auto_9bbc7040', '⏳ در حال ساخت فاکتور...'))
        topup_id = (await asyncio.to_thread(db.create_topup, call.from_user.id, amount))
        await _send_customgw_invoice(
            call.message, gw_row, "wallet_topup", topup_id, call.from_user.id, amount,
            order_name=f"شارژ کیف پول #{topup_id}",
            customer_phone=None, noun="کیف پول", verb="شارژ می‌شود",
        )

    @router.message(WalletTopup.waiting_customgw_phone, F.contact)
    async def receive_customgw_phone_topup(message: Message, state: FSMContext):
        if not message.contact or message.contact.user_id != message.from_user.id:
            await message.answer(db.get_text('handlers_user.auto_78cc91ac', '❌ لطفاً با زدن همون دکمه\u200cی «اشتراک\u200cگذاری شماره موبایل» شماره\u200cی خودت رو بفرست.'))
            return
        data = await state.get_data()
        amount = data.get("topup_amount")
        gw_id = data.get("customgw_gateway_id")
        gw_row = (await asyncio.to_thread(db.get_custom_gateway, gw_id)) if gw_id else None
        if not amount or not gw_row or not gw_row["enabled"]:
            await message.answer(db.get_text('handlers_user.auto_70b436a3', 'درخواست معتبر یافت نشد.'), reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return
        await state.set_state(WalletTopup.waiting_receipt)
        await message.answer(db.get_text('handlers_user.auto_9bbc7040', '⏳ در حال ساخت فاکتور...'), reply_markup=ReplyKeyboardRemove())
        topup_id = (await asyncio.to_thread(db.create_topup, message.from_user.id, amount))
        await _send_customgw_invoice(
            message, gw_row, "wallet_topup", topup_id, message.from_user.id, amount,
            order_name=f"شارژ کیف پول #{topup_id}",
            customer_phone=message.contact.phone_number, noun="کیف پول", verb="شارژ می‌شود",
        )

    @router.message(WalletTopup.waiting_customgw_phone, F.text == "❌ انصراف")
    async def cancel_customgw_phone_topup(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(db.get_text('handlers_user.auto_570dedda', 'عملیات لغو شد.'), reply_markup=ReplyKeyboardRemove())

    @router.message(WalletTopup.waiting_customgw_phone)
    async def receive_customgw_phone_invalid_topup(message: Message):
        await message.answer(
            db.get_text('handlers_user.auto_3cb5d7ba', '📱 لطفاً با زدن دکمه\u200cی «اشتراک\u200cگذاری شماره موبایل» ادامه بده، یا انصراف بده.'),
            reply_markup=kb.share_phone_kb(),
        )

    @router.message(WalletTopup.waiting_receipt, F.photo | F.document)
    async def receive_topup_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await message.answer(db.get_text('handlers_user.auto_dae8bf95', 'درخواست معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.'))
            await state.clear()
            return

        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))
            return
        topup_id = (await asyncio.to_thread(db.create_topup, message.from_user.id, amount))
        (await asyncio.to_thread(db.set_topup_receipt, topup_id, file_id, receipt_type))

        user_row = (await asyncio.to_thread(db.get_user, message.from_user.id))
        caption = (
            f"👛 درخواست شارژ کیف پول #{topup_id}\n"
            f"👤 کاربر: {user_row['first_name'] or ''} (@{user_row['username'] or '---'})\n"
            f"🆔 آیدی عددی: {message.from_user.id}\n"
            f"💰 مبلغ: {amount:,} تومان"
        )
        # قابلیت ۸۵: شماره کارتی که هنگام واریز به کاربر نشان داده شده بود، برای
        # تطبیق مدیر با صورتحساب بانکی، به گزارش اضافه می‌شود.
        caption += "\n\n" + (await _admin_card_hint_line())
        if not await _report_topup_to_group(bot, topup_id, file_id, receipt_type, caption, kb.topup_review_kb(topup_id)):
            for admin_id in (await asyncio.to_thread(db.list_admins)):
                factory = lambda aid=admin_id: _send_receipt_to_admin(
                    bot, aid, file_id, receipt_type, caption, kb.topup_review_kb(topup_id)
                )
                sent = await _send_admin_notification(bot, admin_id, factory, "شارژ کیف پول", topup_id)
                if sent:
                    (await asyncio.to_thread(db.set_topup_admin_message, topup_id, admin_id, sent.message_id))

        await message.answer(
            db.get_text('handlers_user.auto_202cc8d3', '✅ درخواست شارژ کیف پول شما برای بررسی ارسال شد. پس از تایید ادمین، مبلغ به کیف پول شما اضافه می\u200cشود.'),
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        await state.clear()

    @router.message(WalletTopup.waiting_receipt)
    async def topup_receipt_wrong_type(message: Message):
        await message.answer(db.get_text('handlers_user.auto_deee023d', 'لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.'))

    # -----------------------------------------------------------------------
    # منوی واحد انتخاب سطح نمایندگی
    # -----------------------------------------------------------------------

    def _tiers_menu_text(tiers) -> str:
        lines = ["🤝 <b>نمایندگی</b>", "سطح مورد نظرتان را انتخاب کنید:", ""]
        for t in tiers:
            lines.append(f"{t['icon']} <b>{escape_html(t['title'])}</b>: {escape_html(t['summary'])}")
        return "\n".join(lines)

    def _tier_detail_text(t) -> str:
        lines = [f"{t['icon']} <b>{escape_html(t['title'])}</b>", "", escape_html(t["description"]), ""]
        if t["commission_min"] is not None or t["commission_max"] is not None:
            low = t["commission_min"] if t["commission_min"] is not None else 0
            high = t["commission_max"] if t["commission_max"] is not None else 100
            lines.append(f"📈 درصد کمیسیون: {low} تا {high}٪")
        if t["permanent_discount_percent"] is not None:
            lines.append(f"🏷 تخفیف دائمی: {t['permanent_discount_percent']}٪")
        if t["min_qty"] is not None:
            lines.append(f"📦 حداقل خرید: {t['min_qty']} عدد")
        if t["min_volume_gb"] is not None:
            lines.append(f"📦 حداقل خرید: {t['min_volume_gb']} گیگ")
        features = [
            label for flag, label in (
                ("has_miniapp", "مینی‌اپ اختصاصی"),
                ("has_web_panel", "پنل وب"),
                ("has_dedicated_bot", "بات مستقل"),
            ) if t[flag]
        ]
        if features:
            lines.append("✅ " + "، ".join(features))
        return "\n".join(lines).strip()

    async def _show_tiers_menu(message: Message, edit: bool = False):
        tiers = await asyncio.to_thread(db.list_reseller_tiers, True)
        if not tiers:
            await message.answer(db.get_text('handlers_user.auto_605e9816', 'در حال حاضر سطحی برای نمایندگی فعال نیست.'))
            return
        text = _tiers_menu_text(tiers)
        markup = kb.reseller_tiers_kb(tiers)
        if edit:
            await _safe_edit(message, text, reply_markup=markup, parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=markup)

    async def _switch_warning_line(user_id: int, new_code: str) -> str:
        current = await asyncio.to_thread(db.get_agent_tier, user_id)
        if not current or current == new_code:
            return ""
        return f"\n⚠️ سطح فعلی کاربر: {current}؛ با تایید، نمایندگی قبلی او کامل حذف می‌شود."

    async def _start_discount_tier_request(message: Message, tier):
        user_id = message.from_user.id
        if (await asyncio.to_thread(db.get_agent_tier, user_id)) == tier["code"]:
            await message.answer(tr(f"شما همین الان در سطح {tier['icon']} {tier['title']} هستید."))
            return
        if (await asyncio.to_thread(db.get_pending_tier_request, user_id, tier["code"])):
            await message.answer(db.get_text('handlers_user.auto_25035b09', 'درخواست شما برای این سطح در انتظار بررسی است.'))
            return
        request_id = await asyncio.to_thread(db.create_tier_request, user_id, tier["code"])
        if tier["auto_approve"]:
            await asyncio.to_thread(db.approve_tier_request, request_id, 0)
            await message.answer(
                tr(f"✅ سطح {tier['icon']} {tier['title']} برای شما فعال شد. تخفیف‌ها هنگام «خرید کانفیگ» خودکار اعمال می‌شود.")
            )
            return
        user_row = await asyncio.to_thread(db.get_user, user_id)
        first_name = (user_row["first_name"] if user_row else "") or ""
        username = (user_row["username"] if user_row else "") or "---"
        caption = (
            f"🏅 درخواست سطح نمایندگی #{request_id}\n"
            f"سطح: {tier['icon']} {tier['title']}\n"
            f"👤 کاربر: {first_name} (@{username})\n"
            f"🆔 آیدی عددی: {user_id}"
            f"{await _switch_warning_line(user_id, tier['code'])}"
        )
        for admin_id in _senior_admin_ids():
            try:
                await message.bot.send_message(admin_id, caption, reply_markup=kb.tier_request_review_kb(request_id))
            except Exception:
                pass
        await message.answer(db.get_text('handlers_user.auto_9d720db5', '✅ درخواست شما ثبت شد. بعد از تایید ادمین، نتیجه به شما اطلاع داده می\u200cشود.'))

    async def _start_tier_request(message: Message, state: FSMContext, tier):
        if tier["model"] in ("commission", "discount", "fixed_product", "volume_credit"):
            await reseller_request_start(message, state, tier)
        else:
            await message.answer(db.get_text('handlers_user.auto_63037d6b', 'ثبت درخواست برای این سطح هنوز فعال نشده است.'))

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_reseller_tiers", "🤝 نمایندگی"), tr(db.get_setting("btn_reseller_tiers", "🤝 نمایندگی")))))
    async def reseller_tiers_menu(message: Message):
        if not is_main_bot:
            return
        if (await asyncio.to_thread(db.get_setting, "reseller_request_enabled", "1")) != "1":
            await message.answer(db.get_text('handlers_user.auto_8f789b56', 'در حال حاضر امکان درخواست نمایندگی غیرفعال است.'))
            return
        await _show_tiers_menu(message)

    @router.callback_query(F.data.startswith("rt:"))
    async def cb_reseller_tiers(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if not is_main_bot:
            return
        if (await asyncio.to_thread(db.get_setting, "reseller_request_enabled", "1")) != "1":
            return
        parts = call.data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if action == "close":
            try:
                await call.message.delete()
            except TelegramBadRequest:
                pass
            return
        if action == "menu":
            await _show_tiers_menu(call.message, edit=True)
            return
        if action not in ("pick", "go", "goc") or len(parts) < 3:
            return
        tier = await asyncio.to_thread(db.get_reseller_tier, parts[2])
        if not tier or not tier["is_enabled"]:
            await call.message.answer(db.get_text('handlers_user.auto_ac0165cd', 'این سطح در حال حاضر فعال نیست.'))
            return
        if action == "pick":
            await _safe_edit(
                call.message, _tier_detail_text(tier),
                reply_markup=kb.reseller_tier_detail_kb(tier["code"]), parse_mode="HTML",
            )
            return
        if action == "go":
            current_code = await asyncio.to_thread(db.get_agent_tier, call.from_user.id)
            if current_code and current_code != tier["code"]:
                current_tier = await asyncio.to_thread(db.get_reseller_tier, current_code)
                current_label = f"{current_tier['icon']} {current_tier['title']}" if current_tier else current_code
                await _safe_edit(
                    call.message,
                    f"⚠️ <b>تغییر سطح نمایندگی</b>\n\n"
                    f"شما الان در سطح {current_label} هستید. بعد از تایید سطح {tier['icon']} {escape_html(tier['title'])}، "
                    "نمایندگی فعلی شما (بات و دیتابیس اختصاصی، اعتبار حجمی/محصولی، پنل، لینک و کمیسیون و مشتری‌های وصل‌شده) "
                    "کامل حذف می‌شود و قابل بازگشت نیست. کیف پول شما دست‌نخورده می‌ماند.\n\nادامه می‌دهید؟",
                    reply_markup=kb.reseller_tier_switch_confirm_kb(tier["code"]), parse_mode="HTML",
                )
                return
        fake_message = call.message.model_copy(update={"from_user": call.from_user})
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await _start_tier_request(fake_message, state, tier)

    # -----------------------------------------------------------------------
    # درخواست خودکار نمایندگی
    # -----------------------------------------------------------------------

    def _senior_admin_ids():
        return [a["telegram_id"] for a in db.list_admins_with_roles() if a["role"] in ("owner", "admin")]

    async def _reseller_payment_methods(req):
        allowed = await asyncio.to_thread(db.get_effective_reseller_payment_methods, req)
        catalog = [x for x in (await asyncio.to_thread(db.get_payment_methods_catalog, True)) if x["key"] != "wallet"]
        enabled = {x["key"]: x for x in catalog}
        methods = [m for m in (allowed or [x["key"] for x in catalog]) if m in enabled]
        return [m for m in methods if not enabled[m].get("min_amount") or enabled[m]["min_amount"] <= 10**18]

    async def _send_reseller_payment_menu(target, req):
        methods = await _reseller_payment_methods(req)
        if not methods:
            await target.answer(db.get_text('handlers_user.auto_1ad235b4', '⚠️ هیچ روش پرداخت فعالی برای هزینه نمایندگی تنظیم نشده است. با مدیریت تماس بگیرید.'))
            return
        tier = await asyncio.to_thread(db.get_reseller_tier, req["tier_code"]) if req["tier_code"] else None
        label = f"{tier['icon']} {tier['title']}" if tier else "نمایندگی"
        await target.answer(
            tr(f"💳 <b>پرداخت هزینه {escape_html(label)}</b>\n\n"
            f"💰 مبلغ: <b>{req['price_toman']:,} تومان</b>\n\n"
            "روش پرداخت را انتخاب کنید:"),
            reply_markup=kb.reseller_payment_choice_kb(db, methods), parse_mode="HTML",
        )

    async def reseller_request_start(message: Message, state: FSMContext, tier=None):
        if not is_main_bot:
            return
        if (await asyncio.to_thread(db.get_setting, "reseller_request_enabled", "1")) != "1":
            await message.answer(db.get_text('handlers_user.auto_8f789b56', 'در حال حاضر امکان درخواست نمایندگی غیرفعال است.'))
            return
        current_tier = await asyncio.to_thread(db.get_agent_tier, message.from_user.id)
        if current_tier:
            if tier is None or current_tier == tier["code"]:
                await message.answer(db.get_text('handlers_user.auto_42d388d9', 'شما همین الان هم در این سطح نمایندگی فعال هستید.'))
                return
        if (await asyncio.to_thread(db.get_open_reseller_request, message.from_user.id)):
            await message.answer(db.get_text('handlers_user.auto_6637dd81', 'شما همین الان یک درخواست نمایندگی باز دارید؛ منتظر بررسی آن بمانید.'))
            return
        await state.update_data(resreq_tier=tier["code"] if tier else None)
        if tier is not None and tier["model"] in ("commission", "discount"):
            await state.update_data(resreq_volume=0, resreq_text=_RESREQ_DEFAULT_TEXT)
            low, high = _resreq_percent_bounds(tier)
            await state.set_state(ResellerRequestFlow.waiting_percent)
            if tier["model"] == "commission":
                question = f"چند درصد کمیسیون از خرید مشتری‌ها پیشنهاد می‌کنید؟ (بین {low} تا {high})"
            else:
                question = f"چند درصد تخفیف دائمی برای خرید خودتان پیشنهاد می‌کنید؟ (بین {low} تا {high})"
            await message.answer(
                tr(f"{tier['icon']} درخواست نمایندگی {tier['title']}\n\n"
                f"پیشنهاد خودتان را ارسال کنید؛ مدیر بررسی می‌کند و نتیجه را اعلام می‌کند.\n"
                f"{question}\nفقط عدد ارسال کنید:"),
                reply_markup=kb.cancel_kb(),
            )
            return
        if tier is not None and tier["model"] == "fixed_product":
            await state.update_data(resreq_volume=0, resreq_text=_RESREQ_DEFAULT_TEXT)
            await _resreq_after_basics(message, state)
            return
        await state.set_state(ResellerRequestFlow.waiting_volume)
        title = f"{tier['icon']} درخواست نمایندگی {tier['title']}" if tier else "🏪 درخواست نمایندگی"
        min_hint = f"\nحداقل خرید این سطح: {tier['min_volume_gb']:,} گیگ" if tier and tier["min_volume_gb"] else ""
        await message.answer(
            tr(f"{title}\n\n"
            f"چند گیگ حجم برای شروع نیاز دارید؟ فقط عدد ارسال کنید (مثلاً 500):{min_hint}"),
            reply_markup=kb.cancel_kb(),
        )

    def _resreq_percent_bounds(tier):
        if tier["model"] == "commission":
            return int(tier["commission_min"] or 1), int(tier["commission_max"] or 100)
        return 1, 100

    @router.message(ResellerRequestFlow.waiting_percent)
    async def reseller_request_percent(message: Message, state: FSMContext):
        tier = await _resreq_tier(state)
        if tier is None:
            await state.clear()
            await message.answer(db.get_text('handlers_user.auto_da6a370f', '⚠️ این درخواست منقضی شده. لطفاً دوباره روی «درخواست نمایندگی» بزنید.'))
            return
        low, high = _resreq_percent_bounds(tier)
        text = (message.text or "").strip().replace("%", "").replace("٪", "")
        if not text.isdigit() or not (low <= int(text) <= high):
            await message.answer(tr(f"لطفاً یک عدد صحیح بین {low} تا {high} ارسال کنید."))
            return
        await state.update_data(resreq_proposed_percent=int(text))
        await _resreq_after_basics(message, state)

    @router.message(ResellerRequestFlow.waiting_volume)
    async def reseller_request_volume(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_user.auto_fb9e0845', 'لطفاً یک عدد صحیح و مثبت ارسال کنید.'))
            return
        tier = await _resreq_tier(state)
        if tier is not None and tier["min_volume_gb"] and int(text) < tier["min_volume_gb"]:
            await message.answer(f"{tr('حداقل خرید سطح')} {tier['title']} {tr('برابر')} {tier['min_volume_gb']:,} {tr('گیگ است.')}")
            return
        await state.update_data(resreq_volume=int(text))
        if tier is not None:
            await state.update_data(resreq_text=_RESREQ_DEFAULT_TEXT)
            await _resreq_after_basics(message, state)
            return
        await state.set_state(ResellerRequestFlow.waiting_text)
        await message.answer(
            db.get_text('handlers_user.auto_42eb2ece', 'اگه توضیحی دارید (چرا نمایندگی می\u200cخوای و قراره چطور بفروشی) ارسال کنید، در غیر این صورت «ندارم» را ارسال کنید:'),
            reply_markup=kb.cancel_kb(),
        )

    _RESREQ_DEFAULT_TEXT = "توضیحی ارائه نشده."

    async def _resreq_tier(state: FSMContext):
        code = (await state.get_data()).get("resreq_tier")
        if not code:
            return None
        return await asyncio.to_thread(db.get_reseller_tier, code)

    async def _resreq_after_basics(event, state: FSMContext):
        tier = await _resreq_tier(state)
        if tier is None:
            await _resreq_step_bot_choice(event, state)
            return
        if tier["model"] == "fixed_product" and not (await asyncio.to_thread(db.get_reseller_fixed_products)):
            await state.clear()
            await _resreq_notify(event, "⚠️ فعلاً محصولی برای خرید عمده تعریف نشده است. لطفاً بعداً دوباره تلاش کنید.")
            return
        await state.update_data(
            resreq_bot_choice="dedicated" if tier["has_dedicated_bot"] else "none",
            resreq_wants_web_panel=tier["has_web_panel"],
            resreq_wants_miniapp=tier["has_miniapp"],
            resreq_supply_model=tier["model"],
        )
        if tier["model"] == "fixed_product":
            await _resreq_ask_supply_product(event, state, prefix=f"{tier['icon']} درخواست نمایندگی {tier['title']}\n\n")
        else:
            await _resreq_finalize(event, state)

    _RESREQ_AXIS_KEYS = (
        "reseller_axis_bot_dedicated_enabled", "reseller_axis_bot_inline_link_enabled",
        "reseller_axis_bot_none_enabled", "reseller_axis_webpanel_enabled", "reseller_axis_miniapp_enabled",
        "reseller_axis_supply_volume_enabled", "reseller_axis_supply_fixed_product_enabled",
    )

    async def _resreq_axes(state: FSMContext) -> dict:
        """کش وضعیت روشن/خاموش ۴ محور فرم (بند ۶ اسپک) داخل state، تا هر مرحله
        دوباره از دیتابیس نخواند."""
        data = await state.get_data()
        axes = data.get("resreq_axes")
        if axes is None:
            axes = {k: (await asyncio.to_thread(db.get_setting, k, "1")) == "1" for k in _RESREQ_AXIS_KEYS}
            await state.update_data(resreq_axes=axes)
        return axes

    async def _resreq_notify(event, text: str, reply_markup=None):
        """ارسال/ادیت پیام صرف‌نظر از اینکه event پیام است یا کال‌بک."""
        if isinstance(event, CallbackQuery):
            await event.answer()
            await _safe_edit(event.message, text, reply_markup=reply_markup)
        else:
            await event.answer(text, reply_markup=reply_markup)

    async def _resreq_step_bot_choice(event, state: FSMContext):
        axes = await _resreq_axes(state)
        # گزینه‌ی «inline_link» عمداً از این لیست حذف شد: نمایندگی کمیسیونیِ
        # «لینک اختصاصی داخل بات اصلی» حالا یک مسیر کاملاً مستقل و جدا شده است
        # (دکمه‌ی «💼 درخواست نمایندگی کمیسیونی» + CommissionResellerRequestFlow)،
        # بدون حجم/محصول آماده و با تایید/رد درصد کمیسیون توسط ادمین. این محور
        # فقط برای سازگاری با درخواست‌های قدیمیِ ثبت‌شده با این گزینه نگه داشته
        # شده (_finalize_no_bot_reseller_request هنوز bot_choice=='inline_link' را
        # می‌شناسد)، ولی دیگر به کاربر پیشنهاد نمی‌شود.
        options = [o for o, key in (
            ("dedicated", "reseller_axis_bot_dedicated_enabled"),
            ("none", "reseller_axis_bot_none_enabled"),
        ) if axes.get(key, True)] or ["dedicated"]
        if len(options) == 1:
            await state.update_data(resreq_bot_choice=options[0])
            await _resreq_step_web_panel(event, state)
            return
        await state.set_state(ResellerRequestFlow.waiting_bot_choice)
        await _resreq_notify(event, "بات این نمایندگی چطور باشد؟", kb.reseller_request_bot_choice_kb(options))

    async def _resreq_step_web_panel(event, state: FSMContext):
        axes = await _resreq_axes(state)
        if not axes.get("reseller_axis_webpanel_enabled", True):
            await state.update_data(resreq_wants_web_panel=0)
            await _resreq_step_miniapp(event, state)
            return
        await state.set_state(ResellerRequestFlow.waiting_web_panel)
        await _resreq_notify(event, "آیا پنل وب اختصاصی (فقط دسترسی به داده‌های خودش) می‌خواهد؟", kb.reseller_request_web_panel_kb())

    async def _resreq_step_miniapp(event, state: FSMContext):
        axes = await _resreq_axes(state)
        if not axes.get("reseller_axis_miniapp_enabled", True):
            await state.update_data(resreq_wants_miniapp=0)
            await _resreq_step_supply_model(event, state)
            return
        await state.set_state(ResellerRequestFlow.waiting_miniapp)
        await _resreq_notify(event, "آیا مینی‌اپ فروشگاه می‌خواهد؟", kb.reseller_request_miniapp_kb())

    async def _resreq_step_supply_model(event, state: FSMContext):
        axes = await _resreq_axes(state)
        options = [o for o, key in (
            ("volume_credit", "reseller_axis_supply_volume_enabled"),
            ("fixed_product", "reseller_axis_supply_fixed_product_enabled"),
        ) if axes.get(key, True)] or ["volume_credit"]
        if len(options) == 1:
            await state.update_data(resreq_supply_model=options[0])
            if options[0] == "fixed_product":
                await _resreq_ask_supply_product(event, state)
            else:
                await _resreq_finalize(event, state)
            return
        await state.set_state(ResellerRequestFlow.waiting_supply_model)
        await _resreq_notify(event, "مدل تامین این نمایندگی چه باشد؟", kb.reseller_request_supply_model_kb(options))

    async def _resreq_ask_supply_product(event, state: FSMContext, prefix: str = ""):
        products = (await asyncio.to_thread(db.get_reseller_fixed_products))
        if not products:
            await state.update_data(resreq_supply_model="volume_credit")
            await _resreq_notify(event, "⚠️ فعلاً محصولی برای این مدل مجاز نشده؛ به «اعتبار حجمی» تغییر یافت.")
            await _resreq_finalize(event, state)
            return
        await state.set_state(ResellerRequestFlow.waiting_supply_product)
        await _resreq_notify(event, f"{prefix}کدام محصول؟", kb.reseller_request_supply_product_kb(products))

    # توجه: سوال «کاستوم‌سازی کانفیگ» عمداً از فرم حذف شد. این قابلیت (ساخت کانفیگ شخصی
    # مشتری) روی طرف بات فقط از یک پنل VPN «شخصیِ» خودِ همان بات تامین می‌شود
    # (panel_servers محلی با used_for_custom_config=1) و is_full_access_bot هم آن را
    # قفل می‌کند؛ نمایندگی نه پنل شخصی دارد و نه اجازه‌ی ساختش را (طبق ممیزی
    # امنیتی بند ۳.۲). یعنی حتی با روشن‌کردن این تاگل، فیچر عملاً کار نمی‌کرد. برای
    # اینکه یک گزینه‌ی ظاهراً فعال ولی درعمل بی‌اثر به نماینده نشان داده نشود، این مرحله
    # حذف و wants_custom_config همیشه ۰ ثبت می‌شود.

    async def _resreq_finalize(event, state: FSMContext):
        data = await state.get_data()
        volume_gb = data.get("resreq_volume")
        request_text = data.get("resreq_text")
        bot_choice = data.get("resreq_bot_choice", "dedicated")
        wants_web_panel = data.get("resreq_wants_web_panel", 0)
        wants_miniapp = data.get("resreq_wants_miniapp", 0)
        supply_model = data.get("resreq_supply_model", "volume_credit")
        supply_product_id = data.get("resreq_supply_product_id")
        supply_product_name = data.get("resreq_supply_product_name")
        supply_qty = data.get("resreq_supply_qty")
        wants_custom_config = 0  # همیشه غیرفعال؛ دلیل را در کامنت بالای این تابع ببینید.
        tier_code = data.get("resreq_tier")
        proposed_percent = data.get("resreq_proposed_percent")
        tier = await asyncio.to_thread(db.get_reseller_tier, tier_code) if tier_code else None
        await state.clear()
        user_id = event.from_user.id
        bot_obj = event.bot

        volume_missing = volume_gb is None or (supply_model not in ("fixed_product", "commission", "discount") and not volume_gb)
        if volume_missing or request_text is None:
            await _resreq_notify(event, "⚠️ این درخواست منقضی شده. لطفاً دوباره روی «درخواست نمایندگی» بزنید.")
            return

        try:
            request_id = (await asyncio.to_thread(
                db.create_reseller_request, user_id, volume_gb, request_text, wants_custom_config,
                supply_model, supply_product_id, supply_qty, bot_choice, wants_web_panel, wants_miniapp,
                tier_code, proposed_percent,
            ))
            user_row = (await asyncio.to_thread(db.get_user, user_id))
            first_name = (user_row["first_name"] if user_row else "") or ""
            username = (user_row["username"] if user_row else "") or "---"
            if supply_model == "fixed_product":
                supply_label = f"محصول آماده — {supply_product_name} × {supply_qty:,}"
            elif supply_model == "commission":
                supply_label = "کمیسیونی"
            elif supply_model == "discount":
                supply_label = "تخفیف دائمی"
            else:
                supply_label = "اعتبار حجمی"
            bot_choice_label = {
                "dedicated": "بات مستقل با توکن", "inline_link": "لینک اختصاصی داخل بات اصلی", "none": "ندارد",
            }.get(bot_choice, bot_choice)
            tier_line = f"🏅 سطح: {tier['icon']} {tier['title']}\n" if tier else ""
            if tier:
                warning = await _switch_warning_line(user_id, tier["code"])
                if warning:
                    tier_line += warning.lstrip("\n") + "\n"
            volume_line = "" if not volume_gb else f"📦 حجم درخواستی: {volume_gb:,} گیگ\n"
            if proposed_percent is not None:
                kind = "کمیسیون" if supply_model == "commission" else "تخفیف"
                volume_line += f"💡 پیشنهاد کاربر: {kind} {proposed_percent}٪\n"
            caption = (
                f"🏪 درخواست نمایندگی #{request_id}\n"
                f"{tier_line}"
                f"👤 کاربر: {first_name} (@{username})\n"
                f"🆔 آیدی عددی: {user_id}\n"
                f"{volume_line}"
                f"🤖 بات: {bot_choice_label}\n"
                f"🌐 پنل وب: {'بله' if wants_web_panel else 'خیر'}\n"
                f"📱 مینی‌اپ: {'بله' if wants_miniapp else 'خیر'}\n"
                f"🧩 مدل تامین: {supply_label}\n\n"
                f"📝 متن درخواست:\n{request_text}"
            )
            for admin_id in _senior_admin_ids():
                try:
                    await bot_obj.send_message(admin_id, caption, reply_markup=kb.reseller_request_review_kb(request_id))
                except Exception:
                    pass

            await _resreq_notify(event, "✅ درخواست نمایندگی شما ثبت شد. بعد از بررسی ادمین، هزینه‌ی نمایندگی برایتان اعلام می‌شود.")
            target_msg = event.message if isinstance(event, CallbackQuery) else event
            await _send_inline_main_menu(target_msg, user_id)
        except Exception:
            logging.getLogger(__name__).exception("خطا در ثبت درخواست نمایندگی کاربر %s", user_id)
            await _resreq_notify(event, "⚠️ در ثبت درخواست خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.")

    @router.message(ResellerRequestFlow.waiting_text)
    async def reseller_request_text(message: Message, state: FSMContext, bot: Bot):
        request_text = (message.text or "").strip()
        if not request_text:
            await message.answer(db.get_text('handlers_user.auto_72132055', 'لطفاً متن درخواست را ارسال کنید یا «ندارم» را بفرستید.'))
            return
        if request_text in ("ندارم", "ندارم.", "-", "_"):
            request_text = "توضیحی ارائه نشده."
        data = await state.get_data()
        volume_gb = data.get("resreq_volume")

        if not volume_gb:
            # اگر به هر دلیلی (مثلاً ری‌استارت بات بین دو مرحله) داده‌ی حجم گم شده باشد،
            # به‌جای کرش‌کردن روی فرمت عدد، از کاربر می‌خواهیم دوباره از ابتدا شروع کند
            # تا هرگز بدون پاسخ نماند.
            await state.clear()
            await message.answer(
                db.get_text('handlers_user.auto_712a8de3', '⚠️ مشکلی در ثبت درخواست پیش آمد (احتمالاً به\u200cدلیل گذشت زمان زیاد). لطفاً دوباره روی «درخواست نمایندگی» بزنید.'),
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)
            return

        await state.update_data(resreq_text=request_text)
        await _resreq_step_bot_choice(message, state)

    @router.callback_query(ResellerRequestFlow.waiting_bot_choice, F.data.startswith("resreq_bot:"))
    async def reseller_request_bot_choice(call: CallbackQuery, state: FSMContext):
        bot_choice = call.data.split(":")[1]
        await state.update_data(resreq_bot_choice=bot_choice)
        await _resreq_step_web_panel(call, state)

    @router.callback_query(ResellerRequestFlow.waiting_web_panel, F.data.startswith("resreq_webpanel:"))
    async def reseller_request_web_panel(call: CallbackQuery, state: FSMContext):
        wants_web_panel = int(call.data.split(":")[1])
        await state.update_data(resreq_wants_web_panel=wants_web_panel)
        await _resreq_step_miniapp(call, state)

    @router.callback_query(ResellerRequestFlow.waiting_miniapp, F.data.startswith("resreq_miniapp:"))
    async def reseller_request_miniapp(call: CallbackQuery, state: FSMContext):
        wants_miniapp = int(call.data.split(":")[1])
        await state.update_data(resreq_wants_miniapp=wants_miniapp)
        await _resreq_step_supply_model(call, state)

    @router.callback_query(ResellerRequestFlow.waiting_supply_model, F.data.startswith("resreq_supply:"))
    async def reseller_request_supply_model(call: CallbackQuery, state: FSMContext):
        supply_model = call.data.split(":")[1]
        await state.update_data(resreq_supply_model=supply_model)
        if supply_model == "fixed_product":
            await _resreq_ask_supply_product(call, state)
        else:
            await _resreq_finalize(call, state)

    @router.callback_query(ResellerRequestFlow.waiting_supply_product, F.data.startswith("resreq_supplyprod:"))
    async def reseller_request_supply_product(call: CallbackQuery, state: FSMContext):
        product_id = int(call.data.split(":")[1])
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product:
            await call.answer(db.get_text('handlers_user.auto_b887c4b0', 'این محصول دیگر در دسترس نیست.'), show_alert=True)
            return
        await state.update_data(resreq_supply_product_id=product_id, resreq_supply_product_name=product["name"])
        await state.set_state(ResellerRequestFlow.waiting_supply_qty)
        await call.answer()
        await _safe_edit(call.message, f"چند عدد «{product['name']}» نیاز دارید؟ فقط عدد ارسال کنید:")

    @router.message(ResellerRequestFlow.waiting_supply_qty)
    async def reseller_request_supply_qty(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_user.auto_fb9e0845', 'لطفاً یک عدد صحیح و مثبت ارسال کنید.'))
            return
        tier = await _resreq_tier(state)
        if tier is not None and tier["min_qty"] and int(text) < tier["min_qty"]:
            await message.answer(f"{tr('حداقل خرید سطح')} {tier['title']} {tr('برابر')} {tier['min_qty']:,} {tr('عدد است.')}")
            return
        await state.update_data(resreq_supply_qty=int(text))
        await _resreq_finalize(message, state)


    @router.callback_query(F.data.startswith("resreq_pay:"))
    async def reseller_request_pay(call: CallbackQuery):
        request_id = int(call.data.split(":")[1])
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        if not req or req["user_id"] != call.from_user.id or req["status"] != "awaiting_payment":
            await call.answer(db.get_text('handlers_user.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
            return
        await call.answer()
        await _send_reseller_payment_menu(call.message, req)

    @router.callback_query(F.data == "resreq_cancel_payment")
    async def reseller_request_cancel_payment(call: CallbackQuery):
        await call.answer(db.get_text('handlers_user.auto_e2feed12', 'درخواست همچنان منتظر پرداخت شماست.'))

    @router.callback_query(F.data.startswith("respay:"))
    async def reseller_request_choose_payment(call: CallbackQuery, state: FSMContext, bot: Bot):
        method = call.data.split(":", 1)[1]
        req = await asyncio.to_thread(db.get_open_reseller_request, call.from_user.id)
        if not req or req["status"] != "awaiting_payment":
            await call.answer(db.get_text('handlers_user.auto_0c585844', 'این درخواست دیگر در مرحله پرداخت نیست.'), show_alert=True)
            return
        allowed = await asyncio.to_thread(db.get_effective_reseller_payment_methods, req)
        catalog = [x for x in (await asyncio.to_thread(db.get_payment_methods_catalog, True)) if x["key"] != "wallet"]
        enabled = {x["key"]: x for x in catalog}
        if allowed is not None and method not in allowed:
            await call.answer(db.get_text('handlers_user.auto_cbc0fded', 'این روش برای این سطح مجاز نیست.'), show_alert=True); return
        item = enabled.get(method)
        if not item:
            await call.answer(db.get_text('handlers_user.auto_e29914cb', 'این درگاه در دسترس نیست.'), show_alert=True); return
        if item.get("min_amount") and int(req["price_toman"] or 0) < int(item["min_amount"]):
            await call.answer(db.get_text('handlers_user.auto_8e61f65e', 'مبلغ این درخواست از حداقل مبلغ درگاه کمتر است.'), show_alert=True); return
        await asyncio.to_thread(db.set_reseller_request_status, req["id"], "awaiting_payment", payment_method=method)
        amount = int(req["price_toman"] or 0)
        try:
            tenant_id = await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", "")
            label = f"هزینه نمایندگی #{req['id']}"
            if method == "card":
                card_number = await asyncio.to_thread(db.get_setting, "card_number")
                card_holder = await asyncio.to_thread(db.get_setting, "card_holder")
                text = f"💳 مبلغ {amount:,} تومان را واریز کنید و سپس عکس/فایل رسید را همین‌جا ارسال کنید:\n\n💳 شماره کارت: `{card_number}`\n👤 به نام: {escape_md(card_holder)}"
                await call.message.answer(text, parse_mode="Markdown")
            elif method == "card_auto":
                inv = card_to_card_payment.create_invoice(db, "reseller_request", req["id"], call.from_user.id, amount)
                await call.message.answer(
                    tr(f"💳 مبلغ دقیق برای واریز: `{inv['amount_toman']:,}` تومان\n"
                    f"💳 کارت: `{inv['card_number']}`\n👤 به نام: {escape_md(inv['card_holder'] or '')}\n\n"
                    "بعد از واریز، پرداخت به‌صورت خودکار بررسی می‌شود."), parse_mode="Markdown")
            elif method == "abangateway":
                inv = await abangateway_payment.create_invoice_for(db, tenant_id, call.from_user.id, "reseller_request", req["id"], amount, label)
                await call.message.answer(db.get_text('handlers_user.auto_e2a9ed99', '💳 فاکتور آبان\u200cگیت\u200cوی ساخته شد.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("🔗 پرداخت"), url=inv["payment_url"])]]))
            elif method == "blupal":
                inv = await blupal_payment.create_invoice_for(db, tenant_id, call.from_user.id, "reseller_request", req["id"], amount, label)
                await call.message.answer(db.get_text('handlers_user.auto_135a2053', '💳 فاکتور بلوپال ساخته شد.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("🔗 پرداخت"), url=inv["payment_url"])]]))
            elif method == "noapay":
                inv = await noapay_payment.create_invoice_for(db, tenant_id, call.from_user.id, "reseller_request", req["id"], amount, label)
                await call.message.answer(db.get_text('handlers_user.auto_89c1ac87', '⭐ فاکتور NoapayBot ساخته شد.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("🔗 پرداخت"), url=inv["payment_url"])]]))
            elif method == "crypto":
                inv = await crypto_payment.create_invoice_for(db, tenant_id, call.from_user.id, "reseller_request", req["id"], amount, label)
                await call.message.answer(db.get_text('handlers_user.auto_96a35ab8', '🪙 فاکتور کریپتو ساخته شد.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("🔗 پرداخت"), url=inv["invoice_url"])]]))
            elif method.startswith("custom:"):
                key = method.split(":", 1)[1]
                if custom_gateway_payment.gateway_requires_phone(db, key):
                    await state.update_data(resreq_payment_id=req["id"], resreq_payment_method=method)
                    await state.set_state(ResellerRequestFlow.waiting_payment_phone)
                    await call.message.answer(db.get_text('handlers_user.auto_355c0932', '📱 این درگاه برای ساخت فاکتور شماره موبایل می\u200cخواهد. شماره موبایل را ارسال کنید:'))
                    return
                inv = await custom_gateway_payment.create_invoice_for(db, tenant_id, call.from_user.id, key, "reseller_request", req["id"], amount, label)
                await call.message.answer(db.get_text('handlers_user.auto_8815c25a', '💠 فاکتور درگاه سفارشی ساخته شد.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("🔗 پرداخت"), url=inv["invoice_url"])]]))
            elif method in extra_gateway_registry.GATEWAYS:
                inv = await extra_gateway_payment.create_invoice_for(db, tenant_id, call.from_user.id, method, "reseller_request", req["id"], amount, label)
                await extra_gateway_user.present_invoice(call.message, bot, method, inv, "reseller_request", label, amount)
            else:
                raise ValueError("روش پرداخت پشتیبانی نمی‌شود")
            await call.answer(db.get_text('handlers_user.auto_2b4bbfde', 'روش پرداخت انتخاب شد.'))
        except Exception as e:
            logging.getLogger("handlers_user").exception("reseller payment invoice failed")
            await call.answer(str(e)[:180], show_alert=True)

    @router.message(ResellerRequestFlow.waiting_payment_phone)
    async def reseller_request_payment_phone(message: Message, state: FSMContext):
        phone = (message.text or "").strip()
        if len(phone) < 7:
            await message.answer(db.get_text('handlers_user.auto_4a0426db', 'لطفاً شماره موبایل معتبر ارسال کنید.'))
            return
        data = await state.get_data()
        request_id = data.get("resreq_payment_id")
        req = await asyncio.to_thread(db.get_reseller_request, request_id) if request_id else None
        method = data.get("resreq_payment_method") or ""
        if not req or req["user_id"] != message.from_user.id or req["status"] != "awaiting_payment" or not method.startswith("custom:"):
            await state.clear(); await message.answer(db.get_text('handlers_user.auto_0c585844', 'این درخواست دیگر در مرحله پرداخت نیست.')); return
        key = method.split(":", 1)[1]
        try:
            tenant_id = await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", "")
            tier = await asyncio.to_thread(db.get_reseller_tier, req["tier_code"]) if req["tier_code"] else None
            label = f"هزینه نمایندگی #{req['id']}"
            inv = await custom_gateway_payment.create_invoice_for(db, tenant_id, message.from_user.id, key, "reseller_request", req["id"], int(req["price_toman"]), label, customer_phone=phone)
            await state.clear()
            await message.answer(db.get_text('handlers_user.auto_8815c25a', '💠 فاکتور درگاه سفارشی ساخته شد.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("🔗 پرداخت"), url=inv["invoice_url"])]]))
        except Exception as e:
            logging.getLogger("handlers_user").exception("reseller custom gateway phone invoice failed")
            await message.answer(str(e)[:180])

    @router.callback_query(F.data.startswith("resreq_cancel:"))
    async def reseller_request_cancel(call: CallbackQuery):
        request_id = int(call.data.split(":")[1])
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        if not req or req["user_id"] != call.from_user.id:
            await call.answer(db.get_text('handlers_user.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
            return
        # رفع باگ: قبلاً فقط مرحله‌ی «در انتظار پرداخت» قابل انصراف بود. مرحله‌ی
        # «awaiting_bot_info» (ارسال توکن / منتظرِ تاییدِ مالک) می‌تواند به‌خاطر آیدی
        # مالکی که هیچ‌وقت تایید نمی‌کند برای همیشه باز بماند و قبلاً هیچ راهی برای
        # خودِ درخواست‌دهنده برای بستنش نبود (فقط ادمین می‌توانست دستی کنسل کند).
        if req["status"] not in ("awaiting_payment", "awaiting_bot_info"):
            await call.answer(db.get_text('handlers_user.auto_35611d2f', 'این درخواست دیگر قابل انصراف نیست.'), show_alert=True)
            return
        (await asyncio.to_thread(db.set_reseller_request_status, request_id, "cancelled"))
        await _safe_edit(call.message, (call.message.text or "") + "\n\n❌ انصراف داده شد.")
        await call.answer()

    @router.message(F.photo | F.document)
    async def reseller_request_receipt_catch(message: Message, state: FSMContext, bot: Bot):
        # این کاربر عکس رسید نمایندگی را می‌فرستد؛ چون مبلغ برای هر نماینده متفاوت
        # است (برخلاف کیف‌پول/سفارش که state دارند)، به‌جای state از یک درخواست
        # «awaiting_payment» باز برای همین کاربر استفاده می‌کنیم.
        current_state = await state.get_state()
        if current_state:
            return  # یک state دیگر (سفارش/شارژ/...) در حال پردازش این عکس است

        log = logging.getLogger("handlers_user")

        req = (await asyncio.to_thread(db.get_open_reseller_request, message.from_user.id))
        if req and req["status"] == "awaiting_payment" and (req["payment_method"] or "card") == "card":
            file_id, receipt_type = _receipt_payload(message)
            if not file_id:
                return
            (await asyncio.to_thread(db.set_reseller_request_receipt, req["id"], file_id, receipt_type))
            caption = (
                f"💳 رسید پرداخت درخواست نمایندگی #{req['id']}\n"
                f"👤 کاربر: {message.from_user.id}\n"
                f"💰 مبلغ: {req['price_toman']:,} تومان"
            )
            caption += "\n\n" + (await _admin_card_hint_line())
            for admin_id in _senior_admin_ids():
                try:
                    await _send_receipt_to_admin(
                        bot, admin_id, file_id, receipt_type, caption,
                        kb.reseller_request_payment_review_kb(req["id"])
                    )
                except Exception:
                    pass
            await message.answer(db.get_text('handlers_user.auto_0c4dec8f', '✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، مرحله\u200cی بعدی اعلام می\u200cشود.'))
            return

        # -------------------------------------------------------------------
        # Fallback: کاربر state خودش را ندارد (معمولاً چون بین ارسال رسید و
        # رسیدن پیام، پروسه‌ی بات ری‌استارت شده و MemoryStorage پاک شده است -
        # این با ری‌استارت کل سرویس، یا استارت/استاپ بات نمایندگی توسط
        # reconcile_resellers_loop اتفاق می‌افتد). بدون این بخش، عکس رسید
        # کاملاً بی‌سروصدا نادیده گرفته می‌شد: نه در دیتابیس ذخیره می‌شد، نه
        # به ادمین می‌رسید، نه کاربر می‌فهمید. اینجا با پیدا کردن آخرین
        # سفارش pending این کاربر که هنوز رسید ندارد، رسید را به همان سفارش
        # می‌چسبانیم - دقیقاً همان مسیر عادی receive_receipt.
        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            return

        try:
            order = (await asyncio.to_thread(db.get_latest_pending_order_awaiting_receipt, message.from_user.id))
        except Exception:
            log.exception("خطا در جست‌وجوی سفارش pending برای fallback رسید کاربر %s", message.from_user.id)
            order = None

        if order:
            try:
                (await asyncio.to_thread(db.set_order_receipt, order["id"], file_id, receipt_type))
                await _notify_admins_of_order(
                    bot, order["id"], receipt_file_id=file_id, receipt_type=receipt_type
                )
            except Exception:
                log.exception(
                    "پردازش fallback رسید سفارش #%s کاربر %s ناموفق بود.",
                    order["id"], message.from_user.id,
                )
                await message.answer(
                    db.get_text('handlers_user.auto_4e513e64', '⚠️ در ثبت رسید شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.')
                )
                return
            log.warning(
                "رسید سفارش #%s کاربر %s با fallback (بدون FSM state) پردازش شد.",
                order["id"], message.from_user.id,
            )
            await message.answer(
                db.get_text('handlers_user.auto_9cef8cad', '✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، کانفیگ برای شما ارسال خواهد شد.'),
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)
            return

        # هیچ سفارش/درخواست pending‌ای برای این کاربر پیدا نشد. برای شارژ کیف‌پول
        # نمی‌توان بازیابی کرد چون مبلغ فقط داخل state نگه داشته می‌شود، نه دیتابیس؛
        # پس حداقل کاربر را از سکوت کامل نجات می‌دهیم و راهنمایی می‌کنیم.
        try:
            topup = (await asyncio.to_thread(db.get_latest_pending_topup_awaiting_receipt, message.from_user.id))
        except Exception:
            log.exception("خطا در جست‌وجوی شارژ کیف‌پول pending برای fallback رسید کاربر %s", message.from_user.id)
            topup = None

        if topup:
            try:
                (await asyncio.to_thread(db.set_topup_receipt, topup["id"], file_id, receipt_type))
                user_row = (await asyncio.to_thread(db.get_user, message.from_user.id))
                caption = (
                    f"👛 درخواست شارژ کیف پول #{topup['id']}\n"
                    f"👤 کاربر: {user_row['first_name'] or ''} (@{user_row['username'] or '---'})\n"
                    f"🆔 آیدی عددی: {message.from_user.id}\n"
                    f"💰 مبلغ: {topup['amount']:,} تومان"
                )
                caption += "\n\n" + (await _admin_card_hint_line())
                if not await _report_topup_to_group(bot, topup["id"], file_id, receipt_type, caption, kb.topup_review_kb(topup["id"])):
                    for admin_id in (await asyncio.to_thread(db.list_admins)):
                        factory = lambda aid=admin_id: _send_receipt_to_admin(
                            bot, aid, file_id, receipt_type, caption, kb.topup_review_kb(topup["id"])
                        )
                        sent = await _send_admin_notification(bot, admin_id, factory, "شارژ کیف پول", topup["id"])
                        if sent:
                            (await asyncio.to_thread(db.set_topup_admin_message, topup["id"], admin_id, sent.message_id))
            except Exception:
                log.exception(
                    "پردازش fallback رسید شارژ کیف‌پول #%s کاربر %s ناموفق بود.",
                    topup["id"], message.from_user.id,
                )
                await message.answer(
                    db.get_text('handlers_user.auto_4e513e64', '⚠️ در ثبت رسید شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.')
                )
                return
            log.warning(
                "رسید شارژ کیف‌پول #%s کاربر %s با fallback (بدون FSM state) پردازش شد.",
                topup["id"], message.from_user.id,
            )
            await message.answer(
                db.get_text('handlers_user.auto_202cc8d3', '✅ درخواست شارژ کیف پول شما برای بررسی ارسال شد. پس از تایید ادمین، مبلغ به کیف پول شما اضافه می\u200cشود.'),
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)
            return

        log.warning(
            "عکس/فایل بدون state و بدون هیچ سفارش/درخواست pending‌ای از کاربر %s دریافت شد.",
            message.from_user.id,
        )
        await message.answer(
            db.get_text('handlers_user.auto_129febcc', '❌ رسید شما ثبت نشد.\nدلیل: هیچ سفارش یا درخواست شارژ در انتظار رسیدی برای شما پیدا نشد (احتمالاً ارتباط قطع شده بود یا قبلاً بررسی شده است).\n\nلطفاً دوباره از منوی اصلی همان مسیر خرید یا شارژ کیف پول را طی کنید و رسید را مجدداً ارسال کنید.'),
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)

    @router.callback_query(F.data.startswith("resreq_continue:"))
    async def reseller_request_continue(call: CallbackQuery, state: FSMContext):
        request_id = int(call.data.split(":", 1)[1])
        req = await asyncio.to_thread(db.get_reseller_request, request_id)
        if not req or req["user_id"] != call.from_user.id or req["status"] != "awaiting_bot_info":
            await call.answer(db.get_text('handlers_user.auto_5be38894', 'این مرحله دیگر معتبر نیست.'), show_alert=True)
            return
        await state.set_state(ResellerRequestFlow.waiting_bot_token)
        await state.update_data(resreq_request_id=request_id)
        await call.answer()
        await call.message.answer(db.get_text('handlers_user.auto_a5d1e288', '🤖 توکن بات نمایندگی خودتان را از @BotFather ارسال کنید:'))

    @router.message(ResellerRequestFlow.waiting_bot_token)
    async def reseller_request_bot_token(message: Message, state: FSMContext):
        token = (message.text or "").strip()
        temp_bot = Bot(token=token)
        try:
            me = await temp_bot.get_me()
        except Exception:
            await message.answer(db.get_text('handlers_user.auto_1e1d79ba', '❌ این توکن معتبر نیست. توکن بات را دوباره از @BotFather بگیرید و ارسال کنید:'))
            await temp_bot.session.close()
            return
        await temp_bot.session.close()
        if (await asyncio.to_thread(db.get_reseller_bot_by_token, token)):
            await message.answer(db.get_text('handlers_user.auto_27230770', '⛔️ این توکن قبلاً برای یک بات نمایندگی دیگر ثبت شده است.'))
            return
        data = await state.get_data()
        request_id = data.get("resreq_request_id")
        # رفع باگ: توکن/یوزرنیم قبلاً فقط داخل FSM state خودِ درخواست‌دهنده نگه
        # داشته می‌شد. مسیر تایید مالکیت «بیرونی» (وقتی آیدی مالک با آیدی
        # درخواست‌دهنده فرق دارد - ر.ک. reseller_request_owner_id) باید بتواند
        # همین مقادیر را از خودِ ردیف درخواست بخواند، چون آن تایید در چتِ شخص
        # دیگری اتفاق می‌افتد که به state این چت اصلاً دسترسی ندارد.
        if request_id:
            (await asyncio.to_thread(db.set_reseller_request_bot, request_id, token, me.username))
        await state.update_data(resreq_bot_token=token, resreq_bot_username=me.username)
        await state.set_state(ResellerRequestFlow.waiting_owner_id)
        await message.answer(
            tr(f"✅ توکن معتبر است: @{me.username}\n\n"
            f"حالا آیدی عددی تلگرام خودتان (که مالک این بات خواهد بود) را ارسال کنید:")
        )

    @router.message(ResellerRequestFlow.waiting_owner_id)
    async def reseller_request_owner_id(message: Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer(db.get_text('handlers_user.auto_0cd98de6', 'لطفاً فقط آیدی عددی ارسال کنید.'))
            return
        owner_id = int(raw)
        data = await state.get_data()
        request_id = data.get("resreq_request_id")
        req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
        if not req or req["status"] != "awaiting_bot_info":
            await state.clear()
            await message.answer(db.get_text('handlers_user.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'))
            return

        (await asyncio.to_thread(
            db.set_reseller_request_status, request_id, "awaiting_bot_info", owner_telegram_id=owner_id
        ))

        if owner_id == message.from_user.id:
            await state.update_data(resreq_owner_id=owner_id)
            await state.set_state(ResellerRequestFlow.waiting_owner_id_confirm)
            await message.answer(
                tr(f"آیدی عددی وارد‌شده: `{owner_id}`\n\n"
                "این عدد از این به بعد مالکِ بات نمایندگی و صاحبِ اعتبار/موجودی آن خواهد بود. "
                "آیا تایید می‌کنید؟"),
                parse_mode="Markdown",
                reply_markup=kb.reseller_owner_id_confirm_kb(),
            )
            return

        # رفع باگ امنیتی: قبلاً هر آیدی دلخواهی که درخواست‌دهنده تایپ می‌کرد، فقط
        # با تاییدِ خودِ درخواست‌دهنده (نه صاحبِ واقعیِ آن آیدی) به‌عنوان مالکِ
        # نمایندگی و صاحبِ اعتبار/موجودی ثبت می‌شد - یعنی می‌شد بدون اطلاع یا
        # رضایتِ کسی، نمایندگی و مسئولیتِ آن را به آیدی یک شخص ثالث چسباند. حالا
        # وقتی آیدیِ واردشده با درخواست‌دهنده فرق دارد، تاییدِ نهایی فقط با کلیکِ
        # خودِ آن آیدی (در چتِ خودش با همین بات) ممکن است.
        await state.clear()
        sent_ok = False
        try:
            await message.bot.send_message(
                owner_id,
                tr(f"🏪 کاربری با آیدی عددی {message.from_user.id} درخواست کرده که شما مالکِ یک بات "
                f"نمایندگی (@{req['bot_username']}) با {req['volume_gb']:,} گیگ اعتبار حجمی اولیه باشید.\n\n"
                "با تایید، این بات و کلِ اعتبار/موجودیِ آن از این پس متعلق به آیدی شما (همین چت) "
                "خواهد بود. آیا تایید می‌کنید؟"),
                reply_markup=kb.reseller_owner_external_confirm_kb(request_id),
            )
            sent_ok = True
        except Exception:
            sent_ok = False

        if sent_ok:
            await message.answer(
                tr(f"✅ درخواست تاییدِ مالکیت برای آیدی {owner_id} ارسال شد. تا وقتی خودشان تایید نکنند، "
                "نمایندگی نهایی نمی‌شود."),
                reply_markup=kb.reseller_request_owner_wait_kb(request_id),
            )
        else:
            (await asyncio.to_thread(
                db.set_reseller_request_status, request_id, "awaiting_bot_info", owner_telegram_id=None
            ))
            await state.set_state(ResellerRequestFlow.waiting_owner_id)
            await message.answer(
                db.get_text('handlers_user.auto_12614756', '⚠️ نتوانستم به این آیدی پیام بدهم (احتمالاً هنوز با این بات شروع نکرده\u200cاند).\n\nیا از خودشان بخواهید ابتدا با /start وارد بات شوند و دوباره همین آیدی را بفرستید، یا آیدی عددی خودتان را به\u200cعنوان مالک ارسال کنید:')
            )

    @router.callback_query(ResellerRequestFlow.waiting_owner_id_confirm, F.data == "resreq_ownerretry")
    async def reseller_request_owner_id_retry(call: CallbackQuery, state: FSMContext):
        await state.set_state(ResellerRequestFlow.waiting_owner_id)
        await call.answer()
        await _safe_edit(call.message, db.get_text('handlers_user.auto_75c14770', 'باشه، دوباره آیدی عددی مالک بات را ارسال کنید:'))

    async def _finalize_dedicated_bot_reseller(req, bot: Bot, dispatcher: Dispatcher):
        """ثبت نهایی بات نمایندگیِ «مستقل با توکن» - نقطه‌ی مرکزیِ مشترک بین مسیر
        خودتاییدی (مالک = درخواست‌دهنده) و تاییدِ بیرونی (مالک شخص دیگری است که خودش
        دکمه‌ی تایید را زده). عمداً همه‌چیز (توکن/یوزرنیم/آیدی مالک) را از خودِ ردیف
        دیتابیسِ درخواست می‌خواند، نه از FSM state، چون در مسیر بیرونی این تابع از
        چتِ مالک صدا زده می‌شود که اصلاً به state چتِ درخواست‌دهنده دسترسی ندارد."""
        if not (await asyncio.to_thread(db.claim_reseller_request_finalization, req["id"])):
            return
        req = await asyncio.to_thread(db.get_reseller_request, req["id"])
        owner_id = req["owner_telegram_id"]
        token = req["bot_token"]
        username = req["bot_username"]
        requester_id = req["user_id"]

        os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
        db_path = os.path.join(RESELLER_DBS_DIR, f"{username}.db")
        # رفع باگ: مسیر فایل دیتابیس فقط از روی یوزرنیم بات ساخته می‌شود. اگر یک
        # نماینده‌ی قبلی با همین یوزرنیم بات قبلاً حذف شده باشد ولی ادمین موقع حذف
        # گزینه‌ی «پاک نشود» را زده باشد، این فایل قدیمی همچنان روی دیسک هست و چون
        # init_db همه‌جا از CREATE TABLE IF NOT EXISTS استفاده می‌کند، بدون این پاکسازی
        # کل کاربران/کیف‌پول/سفارش‌های نماینده‌ی قبلی عیناً به این نماینده‌ی *تازه* هم
        # دیده می‌شد (و طبق باگ init_db، حتی مالکیت ممکن بود به‌اشتباه به نماینده‌ی
        # قبلی برگردد). چون این یک ثبت‌نام کاملاً تازه است، هر فایل قدیمی روی این
        # مسیر باید قبل از init_db حذف شود تا نماینده‌ی جدید همیشه از صفر شروع کند.
        if os.path.exists(db_path):
            logging.getLogger("handlers_user").warning(
                "فایل دیتابیس قدیمی روی مسیر نماینده‌ی تازه پیدا شد و قبل از ثبت‌نام پاک می‌شود: %s", db_path,
            )
            try:
                os.remove(db_path)
            except OSError:
                logging.getLogger("handlers_user").exception("پاک‌کردن فایل دیتابیس قدیمی نماینده ناموفق بود: %s", db_path)
            for suffix in (".fsm.sqlite3", ".fsm.sqlite3-wal", ".fsm.sqlite3-shm"):
                stale_fsm = db_path + suffix
                if os.path.exists(stale_fsm):
                    try:
                        os.remove(stale_fsm)
                    except OSError:
                        pass
        # قبلاً اینجا req["request_text"] (متن آزادِ توضیحِ درخواست) به‌جای اسم
        # صاحب بات ذخیره می‌شد که باعث می‌شد لیست ادمین به‌جای اسم، توضیحات درخواست
        # را نشان دهد. get_reseller_owner_display_name اسم/یوزرنیم واقعی را برمی‌گرداند.
        owner_name = (await asyncio.to_thread(db.get_reseller_owner_display_name, owner_id))
        try:
            reseller_bot_id = (await asyncio.to_thread(
                db.register_reseller_bot, token, username, owner_id, owner_name, db_path
            ))
        except DuplicateBotTokenError:
            # رفع باگ: قبلاً این استثنا کنترل‌نشده تا بیرونِ هندلر بالا می‌رفت. این
            # فقط در یک شرایط بسیار نادر (دقیقاً همان توکن هم‌زمان توسط یک ثبت‌نام
            # دیگر مصرف شود) رخ می‌دهد؛ درخواست به مرحله‌ی «ارسال توکن» برمی‌گردد تا
            # درخواست‌دهنده بتواند توکن تازه‌ای بگیرد و دوباره تلاش کند.
            (await asyncio.to_thread(
                db.set_reseller_request_status, req["id"], "awaiting_bot_info",
                owner_telegram_id=None, bot_token=None, bot_username=None,
            ))
            try:
                requester_state = FSMContext(
                    storage=dispatcher.storage,
                    key=StorageKey(bot_id=bot.id, chat_id=requester_id, user_id=requester_id),
                )
                await requester_state.set_state(ResellerRequestFlow.waiting_bot_token)
            except Exception:
                pass
            try:
                await bot.send_message(
                    requester_id,
                    tr("⛔️ این توکن همین الان توسط یک ثبت‌نام دیگر مصرف شد؛ لطفاً یک توکن جدید از @BotFather "
                    "بگیرید و دوباره ارسال کنید."),
                )
            except Exception:
                pass
            return

        (await asyncio.to_thread(db.set_reseller_miniapp_enabled, reseller_bot_id, bool(req["wants_miniapp"])))
        if req["wants_web_panel"]:
            (await asyncio.to_thread(db.enable_reseller_web_panel, reseller_bot_id))

        started = False
        if bot_manager:
            started = await bot_manager.start_bot(token, db_path, owner_id, is_main_bot=False)

        reseller_db = Database(db_path)
        (await asyncio.to_thread(reseller_db.init_db, owner_id=owner_id))
        if req["wants_miniapp"]:
            (await asyncio.to_thread(reseller_db.set_setting, "miniapp_tenant_id", str(reseller_bot_id)))
        wants_custom_config = "1" if req["wants_custom_config"] else "0"
        (await asyncio.to_thread(reseller_db.set_setting, "custom_config_enabled", wants_custom_config))

        (await asyncio.to_thread(db.set_reseller_status, owner_id, True))
        (await asyncio.to_thread(db.set_reseller_supply_model, owner_id, req["supply_model"], req["supply_product_id"]))
        if req["supply_model"] == "fixed_product":
            # درخواست‌های جدید ادمین می‌توانند چند محصول داشته باشند؛ درخواست‌های
            # قدیمی همچنان با supply_product_id/supply_qty کار می‌کنند.
            import json as _json
            items = []
            marker = "[[RESSELLER_SUPPLY_ITEMS:"
            text = req["request_text"] or ""
            if marker in text:
                try:
                    start = text.index(marker) + len(marker)
                    end = text.index("]]", start)
                    raw = _json.loads(text[start:end])
                    if isinstance(raw, list):
                        for item in raw:
                            pid = int(item.get("product_id") or 0)
                            qty = int(item.get("quantity") or 0)
                            if pid > 0 and qty > 0:
                                items.append((pid, qty))
                except Exception:
                    items = []
            if not items and req["supply_product_id"] and req["supply_qty"]:
                items = [(int(req["supply_product_id"]), int(req["supply_qty"]))]
            for product_id, quantity in items:
                (await asyncio.to_thread(
                    db.set_reseller_product_credit, owner_id, product_id, quantity,
                    admin_id=req["reviewed_by"],
                    reason=f"تخصیص خودکار پس از تایید درخواست نمایندگی #{req['id']}",
                ))
        else:
            (await asyncio.to_thread(db.adjust_reseller_credit,
                owner_id, req["volume_gb"], admin_id=req["reviewed_by"],
                reason=f"تخصیص خودکار پس از تایید درخواست نمایندگی #{req['id']}",
            ))
        if req["panel_server_id"]:
            (await asyncio.to_thread(db.set_reseller_panel, owner_id, req["panel_server_id"]))
        (await asyncio.to_thread(db.complete_reseller_request, req["id"], owner_id))

        status_text = "✅ بات نمایندگی راه‌اندازی و همین الان روشن شد." if started else \
            "⚠️ بات ثبت شد ولی راه‌اندازی زنده انجام نشد؛ با ری‌استارت سرویس اصلی خودکار روشن می‌شود."
        web_panel_note = ""
        if req["wants_web_panel"]:
            panel_url = (await asyncio.to_thread(db.get_setting, "admin_panel_url", "")) or ADMIN_PANEL_URL or ""
            panel_url = panel_url.rstrip("/")
            if panel_url:
                b_value = reseller_bot_id
                reseller_bot_row = await asyncio.to_thread(db.get_reseller_bot, reseller_bot_id)
                setup_token = reseller_bot_row["web_panel_setup_token"] if reseller_bot_row else None
                # اگر به هر دلیل توکن در زمان فعال‌سازی ذخیره نشده/مصرف شده بود،
                # همین‌جا یک توکن تازه بساز تا نماینده هیچ‌وقت بدون لینک setup نماند.
                if not setup_token:
                    try:
                        setup_token = await asyncio.to_thread(db.regenerate_reseller_web_panel_token, reseller_bot_id)
                    except Exception:
                        setup_token = None
                if setup_token:
                    web_panel_note = (
                        f"\n\n🌐 لینک راه‌اندازی پنل وب نمایندگی:\n"
                        f"{panel_url}/setup?b={b_value}&t={setup_token}\n\n"
                        "این لینک یک‌بارمصرف است؛ با باز کردن آن، یوزرنیم و رمز پنل را خودت تعیین می‌کنی."
                    )
            elif req["wants_web_panel"]:
                web_panel_note = (
                    "\n\n⚠️ پنل وب فعال شده، اما آدرس پنل وب در تنظیمات بات ثبت نشده است. "
                    "ابتدا ADMIN_PANEL_URL / آدرس پنل وب را تنظیم کنید تا لینک راه‌اندازی ارسال شود."
                )
        try:
            await bot.send_message(
                owner_id,
                tr(f"{status_text}\n\n"
                f"🤖 بات: @{username}\n"
                f"📦 اعتبار حجمی تخصیص‌یافته: {req['volume_gb']:,} گیگ\n\n"
                f"برای شروع، با /start به بات خودتان (@{username}) وارد شوید."
                f"{web_panel_note}"),
                reply_markup=kb.menu_for_user(db, owner_id, is_main_bot),
            )
        except Exception:
            pass
        if requester_id != owner_id:
            try:
                await bot.send_message(
                    requester_id,
                    tr(f"✅ آیدی {owner_id} مالکیت نمایندگی #{req['id']} شما را تایید کرد و راه‌اندازی تکمیل شد.\n"
                    f"🤖 بات: @{username}"),
                )
            except Exception:
                pass
        try:
            for admin_id in _senior_admin_ids():
                await bot.send_message(
                    admin_id,
                    tr(f"✅ نمایندگی #{req['id']} تکمیل شد.\n🤖 بات: @{username}\n👤 مالک: {owner_id}"),
                )
        except Exception:
            pass

    @router.callback_query(ResellerRequestFlow.waiting_owner_id_confirm, F.data == "resreq_ownerok")
    async def reseller_request_owner_id_confirmed(call: CallbackQuery, state: FSMContext, bot: Bot, dispatcher: Dispatcher):
        data = await state.get_data()
        request_id = data.get("resreq_request_id")
        req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
        if not req or req["status"] != "awaiting_bot_info" or not req["owner_telegram_id"] or not req["bot_token"]:
            await state.clear()
            await call.answer(db.get_text('handlers_user.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
            return
        await call.answer()
        await state.clear()
        await _finalize_dedicated_bot_reseller(req, bot, dispatcher)

    @router.callback_query(F.data.startswith("resreq_ownerx_ok:"))
    async def reseller_request_owner_confirm_external(call: CallbackQuery, bot: Bot, dispatcher: Dispatcher):
        """تاییدِ مالکیت توسط خودِ آیدیِ نامزدشده (نه درخواست‌دهنده) - رفع باگ امنیتیِ
        امکان ثبتِ نمایندگی روی آیدیِ شخص ثالث بدون رضایت او."""
        request_id = int(call.data.split(":")[1])
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        if not req or req["status"] != "awaiting_bot_info" or not req["owner_telegram_id"] or not req["bot_token"]:
            await call.answer(db.get_text('handlers_user.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
            return
        if req["owner_telegram_id"] != call.from_user.id:
            # فقط خودِ همان آیدیِ نامزدشده اجازه‌ی تایید دارد، نه هرکسی که این پیام را
            # (مثلاً با فوروارد) دیده باشد.
            await call.answer(db.get_text('handlers_user.auto_afd23713', 'این تاییدیه برای شما نیست.'), show_alert=True)
            return
        await call.answer()
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _finalize_dedicated_bot_reseller(req, bot, dispatcher)

    @router.callback_query(F.data.startswith("resreq_ownerx_no:"))
    async def reseller_request_owner_reject_external(call: CallbackQuery, bot: Bot, dispatcher: Dispatcher):
        request_id = int(call.data.split(":")[1])
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        if not req or req["status"] != "awaiting_bot_info" or not req["owner_telegram_id"]:
            await call.answer(db.get_text('handlers_user.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
            return
        if req["owner_telegram_id"] != call.from_user.id:
            await call.answer(db.get_text('handlers_user.auto_afd23713', 'این تاییدیه برای شما نیست.'), show_alert=True)
            return
        await call.answer()
        rejected_owner_id = req["owner_telegram_id"]
        (await asyncio.to_thread(
            db.set_reseller_request_status, request_id, "awaiting_bot_info", owner_telegram_id=None
        ))
        await _safe_edit(call.message, db.get_text('handlers_user.auto_6e0a51d4', '❌ درخواست مالکیت این نمایندگی را رد کردید.'))
        try:
            user_state = FSMContext(
                storage=dispatcher.storage,
                key=StorageKey(bot_id=bot.id, chat_id=req["user_id"], user_id=req["user_id"]),
            )
            await user_state.set_state(ResellerRequestFlow.waiting_owner_id)
            await bot.send_message(
                req["user_id"],
                tr(f"❌ آیدی {rejected_owner_id} مالکیت نمایندگی #{request_id} شما را نپذیرفت.\n\n"
                "لطفاً یک آیدی عددی دیگر (یا آیدی عددی خودتان) را ارسال کنید:"),
            )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # ارتباط با پشتیبانی
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_contact"), tr(db.get_setting("btn_contact")))))
    async def contact_start(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(db.get_text('handlers_user.auto_1071350a', 'چطور می\u200cخواهید با پشتیبانی در ارتباط باشید؟'), reply_markup=kb.contact_menu_kb(db))

    @router.callback_query(F.data == "contact_menu")
    async def cb_contact_menu(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await _safe_edit(call.message, db.get_text('handlers_user.auto_1071350a', 'چطور می\u200cخواهید با پشتیبانی در ارتباط باشید؟'), reply_markup=kb.contact_menu_kb(db))
        await call.answer()

    @router.callback_query(F.data == "contact_direct")
    async def cb_contact_direct(call: CallbackQuery, state: FSMContext):
        if not kb.support_method_enabled(db, "support_direct_enabled"):
            await call.answer(db.get_text('handlers_user.support_method_disabled', 'این روش ارتباطی در حال حاضر غیرفعال است.'), show_alert=True)
            return
        await state.set_state(ContactFlow.waiting_message)
        await _safe_edit(
            call.message, (await asyncio.to_thread(db.get_setting, "contact_text")), reply_markup=kb.cancel_kb()
        )
        await call.answer()

    @router.message(ContactFlow.waiting_message)
    async def contact_receive(message: Message, state: FSMContext, bot: Bot):
        user = message.from_user
        if message.text:
            (await asyncio.to_thread(db.add_support_message, user.id, "user", message.text))
        text = (
            f"📩 پیام جدید از کاربر\n"
            f"👤 {user.first_name or ''} (@{user.username or '---'})\n"
            f"🆔 {user.id}\n\n"
            f"✉️ {message.text or '(بدون متن / رسانه)'}"
        )
        # فقط به اولین ادمین/مالک آنلاین اطلاع بده تا مکالمه به او اختصاص یابد؛
        # اگر هیچ‌کس آنلاین نبود، طبق روال قدیم به همه‌ی ادمین‌ها اطلاع بده.
        target_admin = (await asyncio.to_thread(db.resolve_support_admin_for_message, user.id))
        admin_ids = [target_admin] if target_admin else (await asyncio.to_thread(db.list_admins))
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text, reply_markup=kb.contact_reply_kb(user.id))
            except Exception:
                logging.getLogger("handlers_user").exception(
                    "ارسال پیام پشتیبانی کاربر %s به ادمین %s ناموفق بود.", user.id, admin_id
                )
        await message.answer(
            db.get_text('handlers_user.auto_76185689', 'پیام شما برای پشتیبانی ارسال شد. به زودی پاسخ داده می\u200cشود.'),
            reply_markup=kb.menu_for_user(db, user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, user.id)
        await state.clear()

    # --- دستیار پشتیبانی هوش مصنوعی ---

    async def _forward_ai_transcript_to_admin(bot: Bot, user, reason: str):
        """کل مکالمه‌ی کاربر با دستیار هوشمند را برای ادمین (طبق همان منطق
        مسیریابی چت مستقیم) می‌فرستد تا وقتی وارد می‌شود از صفر شروع نکند."""
        history = await asyncio.to_thread(db.get_ai_conversation, user.id)
        lines = [
            f"🤖 ارجاع از دستیار هوشمند\n👤 {user.first_name or ''} (@{user.username or '---'})\n🆔 {user.id}",
        ]
        if reason:
            lines.append(f"📌 دلیل: {reason}")
        if history:
            lines.append("\n--- تاریخچه‌ی گفتگو با دستیار ---")
            for row in history:
                who = "👤 کاربر" if row["role"] == "user" else "🤖 دستیار"
                lines.append(f"{who}: {row['message']}")
        text = "\n".join(lines)
        target_admin = (await asyncio.to_thread(db.resolve_support_admin_for_message, user.id))
        admin_ids = [target_admin] if target_admin else (await asyncio.to_thread(db.list_admins))
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text, reply_markup=kb.contact_reply_kb(user.id))
            except Exception:
                logging.getLogger("handlers_user").exception(
                    "ارسال ارجاع دستیار هوشمند کاربر %s به ادمین %s ناموفق بود.", user.id, admin_id
                )
        await asyncio.to_thread(db.clear_ai_conversation, user.id)

    @router.callback_query(F.data == "contact_ai")
    async def cb_contact_ai(call: CallbackQuery, state: FSMContext):
        if db.get_setting("ai_support_enabled", "1") != "1" or not ai_support.is_configured(db):
            await call.answer(db.get_text('handlers_user.auto_2e83e1d6', 'دستیار هوشمند در حال حاضر فعال نیست.'), show_alert=True)
            return
        await asyncio.to_thread(db.clear_ai_conversation, call.from_user.id)
        await state.set_state(AIChatFlow.chatting)
        await _safe_edit(
            call.message,
            (await asyncio.to_thread(db.get_setting, "ai_support_intro_text")),
            reply_markup=kb.ai_chat_kb(),
        )
        await call.answer()

    @router.callback_query(F.data == "ai_escalate")
    async def cb_ai_escalate(call: CallbackQuery, state: FSMContext, bot: Bot):
        user = call.from_user
        await _forward_ai_transcript_to_admin(bot, user, "کاربر درخواست صحبت با پشتیبانی انسانی کرد.")
        await state.set_state(ContactFlow.waiting_message)
        await _safe_edit(
            call.message,
            db.get_text('handlers_user.auto_4dc71f40', 'گفتگوی شما برای پشتیبانی انسانی ارسال شد. اگر پیام دیگری داری همین\u200cجا بنویس:'),
            reply_markup=kb.cancel_kb(),
        )
        await call.answer()

    @router.callback_query(F.data == "ai_end")
    async def cb_ai_end(call: CallbackQuery, state: FSMContext):
        await asyncio.to_thread(db.clear_ai_conversation, call.from_user.id)
        await state.clear()
        await _safe_edit(call.message, db.get_text('handlers_user.auto_c05276f0', 'گفتگو با دستیار هوشمند پایان یافت.'))
        await call.answer()

    @router.message(AIChatFlow.chatting)
    async def ai_chat_receive(message: Message, state: FSMContext, bot: Bot):
        user = message.from_user
        if not message.text:
            await message.answer(db.get_text('handlers_user.auto_56d5e115', 'فعلاً فقط پیام متنی رو می\u200cفهمم؛ لطفاً سوالت رو بنویس.'))
            return

        now = asyncio.get_event_loop().time()
        last_at = _ai_last_call_at.get(user.id, 0.0)
        if now - last_at < _AI_COOLDOWN_SECONDS:
            await message.answer(db.get_text('handlers_user.auto_927bceb6', 'لطفاً چند لحظه صبر کن و دوباره بفرست. ⏳'))
            return
        _ai_last_call_at[user.id] = now

        history = await asyncio.to_thread(db.get_ai_conversation, user.id)
        thinking_msg = await message.answer(db.get_text('handlers_user.auto_ba4923c8', 'در حال بررسی... ⏳'))
        try:
            result = await ai_support.get_reply(db, user.id, history, message.text)
        except Exception:
            logging.getLogger("handlers_user").exception(
                "خطای غیرمنتظره در دستیار هوشمند برای کاربر %s.", user.id
            )
            result = {
                "reply": "یه مشکلی پیش اومد؛ پیامت رو برای پشتیبانی انسانی می‌فرستم.",
                "escalate": True,
            }

        await asyncio.to_thread(db.add_ai_message, user.id, "user", message.text)
        await asyncio.to_thread(db.add_ai_message, user.id, "model", result["reply"])

        try:
            await thinking_msg.delete()
        except Exception:
            pass

        if result.get("escalate"):
            await message.answer(result["reply"])
            await _forward_ai_transcript_to_admin(bot, user, "دستیار هوشمند مکالمه را ارجاع داد.")
            await state.set_state(ContactFlow.waiting_message)
            await message.answer(
                db.get_text('handlers_user.auto_3fb129f1', 'مکالمه برای پشتیبانی انسانی ارسال شد. اگر پیام دیگری داری همین\u200cجا بنویس:'),
                reply_markup=kb.cancel_kb(),
            )
            return

        await message.answer(result["reply"], reply_markup=kb.ai_chat_kb())

        # اگر دستیار تشخیص داد کاربر می‌خواهد محصولی بخرد، همان کارت خرید
        # واقعی (قیمت زنده + اعمال خودکار کیف پول + دکمه‌های واقعی پرداخت) را
        # درست مثل مسیر عادی «خرید» نشانش بده. هیچ مبلغی اینجا کسر نمی‌شود؛
        # تسویه فقط با زدن خودِ کاربر روی دکمه‌های زیر همین کارت انجام می‌شود.
        ui_action = result.get("ui_action")
        if ui_action and ui_action.get("type") == "show_product":
            product_id = ui_action.get("product_id")
            product = await asyncio.to_thread(db.get_product, product_id)
            if product:
                stock = await asyncio.to_thread(db.count_available_configs, product_id)
                wallet_credit = await asyncio.to_thread(db.get_wallet_credit, user.id)
                if product["is_auto_provision"] or stock > 0:
                    text = _product_confirm_text(product, 1, stock, wallet_credit)
                    await message.answer(
                        text, reply_markup=kb.product_confirm_kb(db, product_id, 1, max(stock, 1))
                    )
                else:
                    await message.answer(db.get_text('handlers_user.auto_46d880df', '⛔️ موجودی این محصول در حال حاضر تمام شده.'))
        elif ui_action and ui_action.get("type") == "deliver_test_config":
            # دستیار هوشمند فقط تشخیص داد کاربر واجد شرایط کانفیگ تست است؛
            # ساخت/تحویل واقعی همیشه از دقیقاً همان تابعِ دکمه‌ی «کانفیگ تست»
            # انجام می‌شود تا همان محدودیت یک‌بار-در-عمر-حساب و همان بررسی‌های
            # فعال/غیرفعال بودن دوباره (و این‌بار قطعی) اعمال شوند.
            await get_test_config(message)
        elif ui_action and ui_action.get("type") == "show_referral_info":
            # همان پیامِ واقعیِ زیرمجموعه‌گیری (لینک واقعی + آمار زنده) - دقیقاً
            # همان تابعی که دکمه‌ی «زیرمجموعه‌گیری» هم صدا می‌زند.
            await referral_menu(message, bot)
        elif ui_action and ui_action.get("type") == "finalize_wallet_purchase":
            # فقط وقتی به این‌جا می‌رسیم که مدل از کاربر تاییدِ صریح گرفته و
            # ابزار request_purchase_with_wallet هم موجودی کافی کیف پول را
            # تایید کرده؛ اینجا (دفاع در عمق) دوباره از صفر بررسی و نهایی
            # می‌کنیم - دقیقاً با همان توابع دیتابیس/تحویلی که دکمه‌ی واقعیِ
            # «ادامه و ارسال رسید» برای حالتِ «کاملاً با کیف‌پول پوشش داده شده»
            # استفاده می‌کند.
            await _ai_finalize_wallet_purchase(
                message, bot, ui_action.get("product_id"), ui_action.get("quantity", 1)
            )
        elif ui_action and ui_action.get("type") == "finalize_wallet_renewal":
            # مثل finalize_wallet_purchase بالا: فقط وقتی به این‌جا می‌رسیم که
            # مدل از کاربر تاییدِ صریح گرفته و ابزار renew_service_with_wallet
            # هم موجودی کافی کیف پول را تایید کرده؛ اجرای واقعی با همان تابع
            # _process_renewal_order پایین‌تر (همان مسیر دکمه‌های تمدید در
            # «سرویس‌های من») انجام می‌شود - دفاع در عمق، دوباره از صفر بررسی.
            await _ai_finalize_wallet_renewal(
                message, bot, state, ui_action.get("service_id"), ui_action.get("mode"),
                ui_action.get("amount"), ui_action.get("product_id"),
            )
        elif ui_action and ui_action.get("type") == "toggle_auto_renew":
            await _ai_toggle_auto_renew(message, ui_action.get("service_id"), ui_action.get("enabled"))
        elif ui_action and ui_action.get("type") == "send_service_qr":
            await _ai_send_service_qr(message, bot, ui_action.get("service_id"))
        elif ui_action and ui_action.get("type") == "send_individual_configs":
            await _ai_send_individual_configs(message, bot, ui_action.get("service_id"))
        elif ui_action and ui_action.get("type") == "toggle_service_enabled":
            await _ai_toggle_service_enabled(message, ui_action.get("service_id"), ui_action.get("enabled"))
        elif ui_action and ui_action.get("type") == "rename_service":
            await _ai_rename_service(message, ui_action.get("service_id"), ui_action.get("new_name"))
        elif ui_action and ui_action.get("type") == "regenerate_service_access":
            await _ai_regenerate_service_access(message, ui_action.get("service_id"))
        elif ui_action and ui_action.get("type") == "transfer_service":
            await _ai_transfer_service(message, bot, ui_action.get("service_id"), ui_action.get("target_telegram_id"))
        elif ui_action and ui_action.get("type") == "delete_service":
            await _ai_delete_service(message, ui_action.get("service_id"))

    async def _ai_finalize_wallet_purchase(message: Message, bot: Bot, product_id, quantity: int) -> None:
        user_id = message.from_user.id
        quantity = max(1, int(quantity or 1))
        product = await asyncio.to_thread(db.get_product, product_id)
        if not product or not product["is_active"]:
            await message.answer(db.get_text('handlers_user.auto_28235c65', '⛔️ این محصول دیگر موجود نیست.'))
            return
        stock = None if product["is_auto_provision"] else await asyncio.to_thread(db.count_available_configs, product_id)
        if stock is not None and stock < quantity:
            await message.answer(db.get_text('handlers_user.auto_4f213ab0', '⛔️ موجودی این محصول در حال حاضر کافی نیست.'))
            return

        allowed_methods = await asyncio.to_thread(db.get_product_payment_methods, product_id)
        wallet_allowed = allowed_methods is None or "wallet" in allowed_methods
        tier_info = await _tier_info(user_id, product["price"], quantity)
        total_price = tier_info["total_after"]
        wallet_credit = await asyncio.to_thread(db.get_wallet_credit, user_id)
        plan = await asyncio.to_thread(db.plan_wallet_spend, user_id, total_price, wallet_allowed)
        if plan["blocked"]:
            await message.answer(plan["message"])
            return

        if not wallet_allowed or plan["wallet_used"] < total_price:
            # موجودی کافی نبود یا از این نظر تغییر کرده (مثلاً هم‌زمان جای دیگر
            # خرج شده)؛ به‌جای خرید خودکار، همان کارت خرید واقعی را نشان بده تا
            # کاربر خودش با روش دیگری تکمیل کند - هیچ کسری اینجا اتفاق نمی‌افتد.
            stock_display = stock if stock is not None else quantity
            text = _product_confirm_text(product, quantity, stock_display, wallet_credit, tier_info=tier_info)
            await message.answer(
                db.get_text('handlers_user.auto_5eeb79de', '👛 موجودی کیف پول برای تکمیل خودکار کافی نیست؛ کارت خرید رو برات باز می\u200cکنم:')
            )
            await message.answer(
                text,
                reply_markup=kb.product_confirm_kb(
                    db, product_id, quantity, max(stock_display, quantity), 10 if tier_info["title"] else 0
                ),
            )
            return

        deducted = await asyncio.to_thread(db.deduct_wallet_credit, user_id, total_price, True)
        if not deducted:
            await message.answer(db.get_text('handlers_user.auto_6e766fa2', '⛔️ موجودی کیف پول برای این خرید کافی نیست.'))
            return
        try:
            order_id = await asyncio.to_thread(
                db.create_order, user_id, product_id,
                base_price=total_price, wallet_used=total_price,
                discount_code_id=None, discount_amount=0, quantity=quantity,
                tier_discount_amount=tier_info["amount"],
            )
        except Exception:
            await asyncio.to_thread(db.add_wallet_credit, user_id, total_price, "order_refund", "بازگشت وجه خرید ناموفق")
            raise
        order = await asyncio.to_thread(db.get_order, order_id)

        try:
            if product["is_auto_provision"]:
                try:
                    if product["provision_server_id"]:
                        prov_results = await provision_direct(db, product, quantity, user_id=user_id, order_id=order_id)
                    else:
                        prov_results = await provision_auto_config(db, product, quantity, user_id=user_id, order_id=order_id)
                except (ProvisionError, DirectProvisionError) as e:
                    await asyncio.to_thread(db.reject_order, order_id)
                    await _notify_admins_of_order(bot, order_id)
                    await message.answer(tr(f"⛔️ {e}\nمبلغ کسرشده از کیف پول شما به‌طور کامل بازگردانده شد."))
                    return
                await asyncio.to_thread(db.approve_order_auto, order_id)
                links = [r["subscription_url"] for r in prov_results]
            else:
                results = await asyncio.to_thread(db.take_unused_configs, product_id, user_id, quantity)
                if not results:
                    await asyncio.to_thread(db.reject_order, order_id)
                    await _notify_admins_of_order(bot, order_id)
                    await message.answer(
                        db.get_text('handlers_user.auto_99dcfd8b', '⛔️ موجودی این محصول در حال حاضر تمام شده است.\nمبلغ کسرشده از کیف پول شما به\u200cطور کامل بازگردانده شد.')
                    )
                    return
                await asyncio.to_thread(db.approve_order, order_id, [r["id"] for r in results])
                links = [r["link"] for r in results]
                await check_and_notify_low_stock(bot.send_message, db, product_id, bot_token=bot.token)

            reward_info = await asyncio.to_thread(db.reward_referrer_if_first_purchase, user_id, order["base_price"])
            if reward_info:
                reward_amount, referrer_id = reward_info
                try:
                    await bot.send_message(
                        referrer_id,
                        tr(f"🤝 تبریک! یکی از زیرمجموعه‌های شما اولین خرید خود را انجام داد.\n"
                        f"💰 {reward_amount:,} تومان به کیف پول شما اضافه شد."),
                    )
                except Exception:
                    pass
            try:
                await _notify_admins_of_order(bot, order_id)
            except Exception:
                pass

            await message.answer(
                db.get_text('handlers_user.auto_56b713c7', '✅ خرید شما به\u200cطور کامل از کیف پول پرداخت شد.\nکانفیگ شما در پیام بعدی ارسال می\u200cشود 👇')
            )
            await deliver_config_to_user(bot, user_id, product["name"], links, final_price=0, order_id=order_id, db=db)
        except Exception:
            logging.getLogger("handlers_user").exception(
                "خطای غیرمنتظره در خرید خودکارِ دستیار هوشمند برای سفارش #%s کاربر %s؛ سفارش رد و کیف پول بازگردانده شد.",
                order_id, user_id,
            )
            await asyncio.to_thread(db.reject_order, order_id)
            await message.answer(
                db.get_text('handlers_user.auto_1389b2c2', '⛔️ یه خطای غیرمنتظره پیش اومد؛ مبلغ کسرشده به کیف پولت به\u200cطور کامل برگشت. لطفاً دوباره امتحان کن یا با پشتیبانی تماس بگیر.')
            )

    async def _ai_finalize_wallet_renewal(
        message: Message, bot: Bot, state: FSMContext, service_id, mode: str, amount, product_id,
    ) -> None:
        """اجرای واقعیِ «تمدید سرویس با کیف پول» که دستیار هوشمند پیشنهاد داده.
        همه‌چیز از صفر دوباره بررسی می‌شود (دفاع در عمق) و اجرای نهایی دقیقاً با
        همان تابع _process_renewal_order بالا انجام می‌شود - همان تابعی که
        دکمه‌های واقعیِ تمدید در «سرویس‌های من» هم استفاده می‌کنند."""
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item or item["kind"] not in ("config", "custom"):
            await message.answer(db.get_text('handlers_user.auto_5e9e4b97', '⛔️ این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).'))
            return
        if _is_test_item(item):
            await message.answer(db.get_text('handlers_user.auto_f925feb7', '⛔️ این قابلیت برای کانفیگ تست در دسترس نیست.'))
            return
        if item["kind"] == "config" and mode != "time":
            await message.answer(db.get_text('handlers_user.auto_397a4acd', '⛔️ برای این کانفیگ فقط «تمدید زمان» ممکن است.'))
            return

        target_id = item["custom"]["id"] if item["kind"] == "custom" else item["config"]["id"]

        if mode == "full":
            product = await asyncio.to_thread(db.get_product, product_id)
            if not product or not product["is_active"] or not product["is_auto_provision"]:
                await message.answer(db.get_text('handlers_user.auto_5754b3d9', '⛔️ این پلن دیگر برای تمدید در دسترس نیست.'))
                return
            add_volume = product["auto_provision_volume_gb"] or 0
            add_days = product["duration_days"] or 0
            price = product["price"]
            summary_label = product["name"]
        else:
            rate_key = "renewal_price_per_gb" if mode == "volume" else "renewal_price_per_day"
            rate = int((await asyncio.to_thread(db.get_setting, rate_key, "0")) or "0")
            try:
                amount = max(1, int(amount or 0))
            except (TypeError, ValueError):
                amount = 0
            if rate <= 0 or amount <= 0:
                await message.answer(db.get_text('handlers_user.auto_f40bb3a4', '⛔️ قیمت\u200cگذاری این بخش هنوز توسط ادمین تنظیم نشده یا مقدار نامعتبر است.'))
                return
            add_volume = amount if mode == "volume" else 0
            add_days = amount if mode == "time" else 0
            price = amount * rate
            unit_label = "گیگابایت" if mode == "volume" else "روز"
            summary_label = f"{amount:,} {unit_label}"

        plan = await asyncio.to_thread(db.plan_wallet_spend, user_id, price)
        if plan["wallet_used"] < price:
            await message.answer(
                plan["message"] or
                "👛 موجودی کیف پول برای تکمیل خودکار این تمدید کافی نیست؛ "
                "از منوی «سرویس‌های من» می‌تونی با روش دیگری تکمیلش کنی."
            )
            return

        async def edit_fn(t, **kw):
            await message.answer(t, **kw)

        async def send_fn(t, **kw):
            await message.answer(t, **kw)

        await _process_renewal_order(
            user_id, service_id, mode, item["kind"], target_id,
            add_volume, add_days, price, summary_label, state, edit_fn, send_fn, message.bot,
        )

    async def _ai_toggle_auto_renew(message: Message, service_id, enabled) -> None:
        """اجرای واقعیِ روشن/خاموش‌کردنِ تمدید خودکار - دفاع در عمق: دوباره از
        صفر بررسی می‌شود، دقیقاً مثل دکمه‌ی واقعیِ svc_autorenew."""
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item or item["kind"] != "custom":
            await message.answer(db.get_text('handlers_user.auto_5e9e4b97', '⛔️ این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).'))
            return
        if _is_test_item(item):
            await message.answer(db.get_text('handlers_user.auto_f925feb7', '⛔️ این قابلیت برای کانفیگ تست در دسترس نیست.'))
            return
        cc = item["custom"]
        if (cc["duration_days"] or 0) <= 0:
            await message.answer(db.get_text('handlers_user.auto_1b293231', 'این کانفیگ نامحدود است و نیازی به تمدید خودکار ندارد.'))
            return
        enabled = bool(enabled)
        (await asyncio.to_thread(db.set_custom_config_auto_renew, cc["id"], user_id, enabled))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc["id"], "auto_renew_toggle", "فعال شد" if enabled else "غیرفعال شد",
        ))
        await message.answer("✅ تمدید خودکار فعال شد." if enabled else "✅ تمدید خودکار غیرفعال شد.")
        await _refresh_service_card(message, user_id, service_id)

    async def _ai_send_service_qr(message: Message, bot: Bot, service_id) -> None:
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item:
            await message.answer(db.get_text('handlers_user.auto_e6ba8f93', '⛔️ این سرویس دیگر یافت نشد.'))
            return
        link = _item_sub_link(item)
        if not link:
            await message.answer(db.get_text('handlers_user.auto_1e7d994f', '⛔️ لینکی برای ساخت کیوآر پیدا نشد.'))
            return
        photo = BufferedInputFile(build_qr_bytes(link, db=db), filename="config_qr.png")
        await bot.send_photo(user_id, photo, caption=tr("⬜ کیوآر کانفیگ شما"))

    async def _ai_send_individual_configs(message: Message, bot: Bot, service_id) -> None:
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item:
            await message.answer(db.get_text('handlers_user.auto_e6ba8f93', '⛔️ این سرویس دیگر یافت نشد.'))
            return
        link = _item_sub_link(item)
        if not link.startswith(("http://", "https://")):
            await message.answer(db.get_text('handlers_user.auto_fd563df7', '⛔️ کانفیگ تکی\u200cای برای این سرویس موجود نیست.'))
            return
        try:
            links = await fetch_individual_links(link)
        except Exception:
            links = []
        if not links:
            await message.answer(db.get_text('handlers_user.auto_b9f34761', '⛔️ در حال حاضر کانفیگ تکی\u200cای یافت نشد.'))
            return
        text = f"📋 کانفیگ‌های تکی این سرویس ({len(links)} عدد):\n\n" + "\n".join(f"`{c}`" for c in links)
        if len(text) > 4000:
            text = text[:3950] + "\n\n… (فهرست کوتاه شد؛ تعداد کانفیگ‌ها زیاد است)"
        await message.answer(text, parse_mode="Markdown")

    async def _ai_toggle_service_enabled(message: Message, service_id, enabled) -> None:
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item or item["kind"] != "custom":
            await message.answer(db.get_text('handlers_user.auto_5e9e4b97', '⛔️ این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).'))
            return
        if _is_test_item(item):
            await message.answer(db.get_text('handlers_user.auto_f925feb7', '⛔️ این قابلیت برای کانفیگ تست در دسترس نیست.'))
            return
        cc = item["custom"]
        new_enabled = bool(enabled)
        server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
        if not server or not server["is_active"]:
            await message.answer(db.get_text('handlers_user.auto_bced6392', '⛔️ سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است.'))
            return
        try:
            provider = get_provider(server)
            await provider.set_enabled(cc["username"], new_enabled)
        except PanelError as e:
            await message.answer(tr(f"⛔️ ناموفق بود: {e}"))
            return
        (await asyncio.to_thread(db.set_custom_config_enabled, cc["id"], user_id, new_enabled))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc["id"], "toggle", "فعال شد" if new_enabled else "غیرفعال شد",
        ))
        await message.answer(db.get_text('handlers_user.auto_9b232770', '✅ وضعیت بروزرسانی شد.'))
        await _refresh_service_card(message, user_id, service_id)

    async def _ai_rename_service(message: Message, service_id, new_suffix) -> None:
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item or item["kind"] != "custom":
            await message.answer(db.get_text('handlers_user.auto_5e9e4b97', '⛔️ این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).'))
            return
        if _is_test_item(item):
            await message.answer(db.get_text('handlers_user.auto_f925feb7', '⛔️ این قابلیت برای کانفیگ تست در دسترس نیست.'))
            return
        suffix = (new_suffix or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", suffix):
            await message.answer(db.get_text('handlers_user.auto_f720bd29', '❌ نام نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.'))
            return
        cc = item["custom"]
        prefix = (await asyncio.to_thread(db.get_custom_config_prefix))
        current_label = cc["display_name"] or cc["username"]
        new_label = f"{prefix}-{suffix}" if (prefix and current_label.startswith(prefix + "-")) else suffix
        if new_label == current_label:
            await message.answer(db.get_text('handlers_user.auto_23695416', 'این نام همان نام فعلی است.'))
            return
        if (await asyncio.to_thread(db.is_custom_username_taken, new_label)):
            await message.answer(db.get_text('handlers_user.auto_141334c4', '❌ این نام قبلاً استفاده شده. نام دیگری بفرست.'))
            return
        server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
        panel_username = None
        note = "(فقط نام نمایشی داخل بات تغییر کرد؛ لینک/کانفیگ فعلی روی پنل بدون تغییر کار می‌کند)"
        if server and server["is_active"]:
            try:
                provider = get_provider(server)
                await provider.rename_user(cc["username"], new_label)
                panel_username = new_label
                note = "(روی خودِ پنل هم اعمال شد)"
            except PanelError:
                pass
        (await asyncio.to_thread(db.rename_custom_config, cc["id"], user_id, new_label, panel_username))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc["id"], "rename", f"{current_label} ← {new_label} {note}",
        ))
        await _refresh_service_card(message, user_id, service_id, f"✅ نام کانفیگ به «{new_label}» تغییر کرد. {note}")

    # امنیت: عملیات‌های غیرقابل‌بازگشت (قطع دسترسی/انتقال/حذف) دیگر مستقیماً
    # توسط تصمیم مدل اجرا نمی‌شوند - چون تنها سدِ راه در آن حالت، دستورالعمل
    # متنیِ system prompt بود که با اشتباه مدل یا prompt injection قابل دور
    # زدن است. این سه تابع حالا فقط اعتبارسنجی می‌کنند و همان کیبورد تاییدِ
    # واقعی/تست‌شده‌ی مسیر دستی «سرویس‌های من» (mo_delok / svc_cutok /
    # svc_transok) را نشان می‌دهند؛ اجرای واقعی فقط با تپ خودِ کاربر روی آن
    # دکمه، توسط همان هندلرهای callback موجود، انجام می‌شود - نه اینجا.
    async def _ai_regenerate_service_access(message: Message, service_id) -> None:
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item or item["kind"] != "custom":
            await message.answer(db.get_text('handlers_user.auto_5e9e4b97', '⛔️ این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).'))
            return
        if _is_test_item(item):
            await message.answer(db.get_text('handlers_user.auto_f925feb7', '⛔️ این قابلیت برای کانفیگ تست در دسترس نیست.'))
            return
        cc = item["custom"]
        server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
        if not server or not server["is_active"]:
            await message.answer(db.get_text('handlers_user.auto_bced6392', '⛔️ سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است.'))
            return
        await message.answer(
            db.get_text('handlers_user.auto_a0f85a3c', '⚠️ این عملیات غیرقابل\u200cبازگشت است: لینک فعلی از کار می\u200cافتد و لینک جدیدی (با همان حجم/زمان باقی\u200cمانده) صادر می\u200cشود.\nبرای تایید نهایی روی دکمه\u200cی زیر بزن:'),
            reply_markup=kb.service_cut_confirm_kb(str(service_id)),
        )

    async def _ai_transfer_service(message: Message, bot: Bot, service_id, target_telegram_id) -> None:
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item or item["kind"] != "custom":
            await message.answer(db.get_text('handlers_user.auto_16536ad9', '⛔️ این سرویس دیگر یافت نشد (شاید قبلاً حذف/منتقل شده).'))
            return
        if _is_test_item(item):
            await message.answer(db.get_text('handlers_user.auto_f925feb7', '⛔️ این قابلیت برای کانفیگ تست در دسترس نیست.'))
            return
        try:
            target_telegram_id = int(target_telegram_id)
        except (TypeError, ValueError):
            await message.answer(db.get_text('handlers_user.auto_46369b03', '⛔️ آی\u200cدی مقصد نامعتبر است.'))
            return
        if target_telegram_id == user_id:
            await message.answer(db.get_text('handlers_user.auto_474c54ea', '⛔️ نمی\u200cتوانی سرویس را به خودت منتقل کنی.'))
            return
        target_user = await asyncio.to_thread(db.get_user, target_telegram_id)
        if not target_user:
            await message.answer(db.get_text('handlers_user.auto_600977af', '⛔️ آن کاربر بات را استارت نکرده یا آی\u200cدی نادرست است.'))
            return
        await message.answer(
            tr(f"⚠️ این عملیات غیرقابل‌بازگشت است: سرویس برای همیشه به کاربر با آی‌دی "
            f"{target_telegram_id} منتقل می‌شود.\nبرای تایید نهایی روی دکمه‌ی زیر بزن:"),
            reply_markup=kb.service_transfer_confirm_kb(str(service_id), target_telegram_id),
        )

    async def _ai_delete_service(message: Message, service_id) -> None:
        user_id = message.from_user.id
        item = _find_my_orders_item(user_id, service_id)
        if not item:
            await message.answer(db.get_text('handlers_user.auto_e6ba8f93', '⛔️ این سرویس دیگر یافت نشد.'))
            return
        await message.answer(
            db.get_text('handlers_user.auto_1d3b6726', '⚠️ این عملیات غیرقابل\u200cبازگشت است: سرویس برای همیشه حذف می\u200cشود.\nبرای تایید نهایی روی دکمه\u200cی زیر بزن:'),
            reply_markup=kb.my_order_delete_confirm_kb(str(service_id)),
        )

    @router.callback_query(F.data.startswith("svc_disruption:"))
    async def cb_service_disruption(call: CallbackQuery, bot: Bot):
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_d52e4662', 'سرویس یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_c1b68f41', 'گزارش اختلال برای سرویس تستی فعال نیست.'), show_alert=True)
            return
        cc = item["custom"]
        deps = await asyncio.to_thread(db.list_ticket_departments, True)
        dep = next((d for d in deps if d["name"] == "فنی"), deps[0] if deps else None)
        subject = f"گزارش اختلال سرویس «{cc['display_name'] or cc['username']}»"
        ticket_text = (f"کاربر گزارش اختلال سرویس را ثبت کرد.\n\nنام کاربری پنل: {cc['username']}\n"
                       f"شناسه سرویس: {cc['id']}\nپنل: {cc['panel_server_id'] or '-'}")
        ticket_id = await asyncio.to_thread(db.create_ticket, call.from_user.id, subject, ticket_text, dep["id"] if dep else None)
        await call.message.answer(tr(f"✅ گزارش اختلال ثبت شد. شماره تیکت: #{ticket_id}\nبخش فنی در حال بررسی است."))
        for admin_id in await asyncio.to_thread(db.list_ticket_admin_ids_for_department, dep["id"] if dep else None):
            try:
                await bot.send_message(admin_id, tr(f"⚠️ گزارش اختلال جدید #{ticket_id}\n👤 {call.from_user.id}\n📌 {subject}\n\n{ticket_text}"), reply_markup=kb.ticket_admin_notify_kb(ticket_id))
            except Exception:
                logging.getLogger("handlers_user").exception("اعلان اختلال #%s به ادمین %s ناموفق بود", ticket_id, admin_id)
        await call.answer(db.get_text('handlers_user.auto_82dd141f', 'گزارش ثبت شد'))

    @router.callback_query(F.data.startswith("svc_rate:"))
    async def cb_service_rate(call: CallbackQuery):
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom":
            await call.answer(db.get_text('handlers_user.auto_d52e4662', 'سرویس یافت نشد.'), show_alert=True)
            return
        if _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_d1366877', 'امتیازدهی برای سرویس تستی فعال نیست.'), show_alert=True)
            return
        cc = item["custom"]
        current = await asyncio.to_thread(db.get_service_rating, call.from_user.id, cc["id"])
        text = f"⭐ کیفیت سرویس «{cc['display_name'] or cc['username']}» را چند ستاره می‌دهید؟"
        if current:
            text += f"\n\nامتیاز فعلی شما: {current}/۵"
        await call.answer()
        await _safe_edit(call.message, text, reply_markup=kb.service_rating_kb(cb_id, current))

    @router.callback_query(F.data.startswith("svc_rate_set:"))
    async def cb_service_rate_set(call: CallbackQuery):
        _, cb_id, value_s = call.data.split(":", 2)
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] != "custom" or _is_test_item(item):
            await call.answer(db.get_text('handlers_user.auto_d52e4662', 'سرویس یافت نشد.'), show_alert=True)
            return
        cc = item["custom"]
        rating = int(value_s)
        await asyncio.to_thread(db.rate_service, call.from_user.id, cc["id"], cc["panel_server_id"], rating)
        await call.answer(tr(f"⭐ امتیاز {rating}/۵ ثبت شد. ممنون از بازخوردت!"), show_alert=True)
        await _safe_edit(
            call.message,
            f"⭐ امتیاز شما برای «{cc['display_name'] or cc['username']}»: {rating}/۵ ثبت شد.",
            reply_markup=kb.service_rating_kb(cb_id, rating),
        )

    # --- سیستم تیکت (موضوع مشخص + پیام، مستقل از چت مستقیم بالا) ---

    @router.callback_query(F.data == "tickets_new")
    async def cb_tickets_new(call: CallbackQuery, state: FSMContext):
        if not kb.support_method_enabled(db, "support_ticket_new_enabled"):
            await call.answer(db.get_text('handlers_user.support_method_disabled', 'این روش ارتباطی در حال حاضر غیرفعال است.'), show_alert=True)
            return
        departments = await asyncio.to_thread(db.list_ticket_departments, True)
        await state.set_state(TicketFlow.waiting_department)
        await _safe_edit(call.message, db.get_text('handlers_user.auto_4a8dbe38', '🧩 لطفاً بخش مرتبط با درخواست خود را انتخاب کنید:'), reply_markup=kb.ticket_departments_kb(departments))
        await call.answer()

    @router.callback_query(F.data == "ticket_cancel")
    async def cb_ticket_cancel(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await _safe_edit(call.message, db.get_text('handlers_user.auto_c3f30694', '❌ ثبت تیکت لغو شد.'), reply_markup=kb.contact_menu_kb(db))
        await call.answer()

    @router.callback_query(F.data.startswith("ticket_dept:"))
    async def cb_ticket_department(call: CallbackQuery, state: FSMContext):
        raw = call.data.split(":", 1)[1]
        if not raw.isdigit():
            await call.answer(db.get_text('handlers_user.auto_2aa5d7e8', '❌ دپارتمان نامعتبر است.'), show_alert=True)
            return
        department = await asyncio.to_thread(db.get_ticket_department, int(raw))
        if not department or not department["is_active"]:
            await call.answer(db.get_text('handlers_user.auto_cede281d', '❌ این دپارتمان در دسترس نیست.'), show_alert=True)
            return
        await state.update_data(ticket_department_id=int(raw))
        await state.set_state(TicketFlow.waiting_subject)
        await _safe_edit(call.message, f"🧩 بخش انتخاب‌شده: {department['name']}\n\nموضوع تیکت را ارسال کنید:", reply_markup=kb.cancel_kb())
        await call.answer()

    @router.message(TicketFlow.waiting_subject)
    async def ticket_receive_subject(message: Message, state: FSMContext):
        subject = (message.text or "").strip()
        if not subject:
            await message.answer(db.get_text('handlers_user.auto_31aac992', 'لطفاً موضوع تیکت را به\u200cصورت متن ارسال کنید:'))
            return
        await state.update_data(ticket_subject=subject[:150])
        await state.set_state(TicketFlow.waiting_message)
        await message.answer(db.get_text('handlers_user.auto_d9b50287', 'متن کامل پیام خود را ارسال کنید:'), reply_markup=kb.cancel_kb())

    @router.message(TicketFlow.waiting_message)
    async def ticket_receive_message(message: Message, state: FSMContext, bot: Bot):
        if not message.text:
            await message.answer(db.get_text('handlers_user.auto_7b96f3b5', 'لطفاً متن پیام را به\u200cصورت نوشتاری ارسال کنید:'))
            return
        data = await state.get_data()
        subject = data.get("ticket_subject") or "بدون موضوع"
        department_id = data.get("ticket_department_id")
        department = await asyncio.to_thread(db.get_ticket_department, department_id) if department_id else None
        user = message.from_user
        ticket_id = (await asyncio.to_thread(db.create_ticket, user.id, subject, message.text, department_id))
        text = (
            f"🎫 تیکت جدید #{ticket_id}\n"
            f"👤 {user.first_name or ''} (@{user.username or '---'})\n"
            f"🆔 {user.id}\n"
            f"📌 موضوع: {subject}\n"
            f"🧩 بخش: {(department['name'] if department else 'عمومی')}\n\n"
            f"✉️ {message.text}"
        )
        for admin_id in (await asyncio.to_thread(db.list_ticket_admin_ids_for_department, department_id)):
            try:
                await bot.send_message(admin_id, text, reply_markup=kb.ticket_admin_notify_kb(ticket_id))
            except Exception:
                logging.getLogger("handlers_user").exception(
                    "ارسال اطلاع تیکت #%s کاربر %s به ادمین %s ناموفق بود.", ticket_id, user.id, admin_id
                )
        await message.answer(
            tr(f"✅ تیکت شما با شماره #{ticket_id} ثبت شد. به زودی پاسخ داده می‌شود."),
            reply_markup=kb.menu_for_user(db, user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, user.id)
        await state.clear()

    @router.callback_query(F.data == "tickets_mine")
    async def cb_tickets_mine(call: CallbackQuery, state: FSMContext):
        if not kb.support_method_enabled(db, "support_ticket_mine_enabled"):
            await call.answer(db.get_text('handlers_user.support_method_disabled', 'این روش ارتباطی در حال حاضر غیرفعال است.'), show_alert=True)
            return
        await state.clear()
        tickets = (await asyncio.to_thread(db.get_user_tickets, call.from_user.id))
        await _safe_edit(call.message, db.get_text('handlers_user.auto_362322f8', '📂 تیکت\u200cهای شما:'), reply_markup=kb.tickets_list_kb(tickets))
        await call.answer()

    @router.callback_query(F.data.startswith("ticket_view:"))
    async def cb_ticket_view(call: CallbackQuery):
        ticket_id_str = call.data.split(":", 1)[1]
        if not ticket_id_str.isdigit():
            await call.answer(db.get_text('handlers_user.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        ticket_id = int(ticket_id_str)
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket or ticket["user_id"] != call.from_user.id:
            await call.answer(db.get_text('handlers_user.auto_01aac3cf', 'تیکت یافت نشد.'), show_alert=True)
            return
        (await asyncio.to_thread(db.mark_ticket_read_by_user, ticket_id))
        messages = (await asyncio.to_thread(db.get_ticket_messages, ticket_id))
        lines = [
            f"🎫 تیکت #{ticket['id']} — {kb.TICKET_STATUS_LABELS.get(ticket['status'], ticket['status'])}",
            f"📌 موضوع: {ticket['subject']}",
            "",
        ]
        for m in messages:
            sender_label = "👤 شما" if m["sender"] == "user" else "🛠 پشتیبانی"
            lines.append(f"{sender_label}: {m['message']}")
        await _safe_edit(
            call.message, "\n".join(lines), reply_markup=kb.ticket_thread_kb(ticket_id, ticket["status"] == "closed")
        )
        await call.answer()

    @router.callback_query(F.data.startswith("ticket_reply:"))
    async def cb_ticket_reply(call: CallbackQuery, state: FSMContext):
        ticket_id_str = call.data.split(":", 1)[1]
        if not ticket_id_str.isdigit():
            await call.answer(db.get_text('handlers_user.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        ticket_id = int(ticket_id_str)
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket or ticket["user_id"] != call.from_user.id:
            await call.answer(db.get_text('handlers_user.auto_01aac3cf', 'تیکت یافت نشد.'), show_alert=True)
            return
        if ticket["status"] == "closed":
            await call.answer(db.get_text('handlers_user.auto_4ad3a3fa', '⛔️ این تیکت بسته شده و امکان ارسال پیام جدید در آن نیست.'), show_alert=True)
            return
        await state.update_data(reply_ticket_id=ticket_id)
        await state.set_state(TicketReplyFlow.waiting_message)
        await _safe_edit(
            call.message, f"متن پیام خود را برای تیکت #{ticket_id} ارسال کنید:", reply_markup=kb.cancel_kb()
        )
        await call.answer()

    @router.message(TicketReplyFlow.waiting_message)
    async def ticket_reply_receive(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        ticket_id = data.get("reply_ticket_id")
        if not ticket_id:
            await state.clear()
            return
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket or ticket["user_id"] != message.from_user.id:
            await state.clear()
            return
        if ticket["status"] == "closed":
            await message.answer(
                db.get_text('handlers_user.auto_4ad3a3fa', '⛔️ این تیکت بسته شده و امکان ارسال پیام جدید در آن نیست.'),
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await state.clear()
            return
        if not message.text:
            await message.answer(db.get_text('handlers_user.auto_7b96f3b5', 'لطفاً متن پیام را به\u200cصورت نوشتاری ارسال کنید:'))
            return
        (await asyncio.to_thread(db.add_ticket_message, ticket_id, "user", message.text))
        user = message.from_user
        text = (
            f"🎫 پیام جدید در تیکت #{ticket_id} ({ticket['subject']})\n"
            f"👤 {user.first_name or ''} (@{user.username or '---'})\n"
            f"🆔 {user.id}\n\n"
            f"✉️ {message.text}"
        )
        admin_ids = [ticket["claimed_by"]] if ticket["claimed_by"] else (await asyncio.to_thread(db.list_ticket_admin_ids_for_department, ticket["department_id"]))
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text, reply_markup=kb.ticket_admin_notify_kb(ticket_id))
            except Exception:
                logging.getLogger("handlers_user").exception(
                    "ارسال پیام جدید تیکت #%s به ادمین %s ناموفق بود.", ticket_id, admin_id
                )
        await message.answer(db.get_text('handlers_user.auto_49c8bedb', '✅ پیام شما ثبت شد.'), reply_markup=kb.menu_for_user(db, user.id, is_main_bot))
        await _send_inline_main_menu(message, user.id)
        await state.clear()

    @router.callback_query(F.data.startswith("ticket_close:"))
    async def cb_ticket_close(call: CallbackQuery):
        ticket_id_str = call.data.split(":", 1)[1]
        if not ticket_id_str.isdigit():
            await call.answer(db.get_text('handlers_user.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        ticket_id = int(ticket_id_str)
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket or ticket["user_id"] != call.from_user.id:
            await call.answer(db.get_text('handlers_user.auto_01aac3cf', 'تیکت یافت نشد.'), show_alert=True)
            return
        (await asyncio.to_thread(db.close_ticket, ticket_id))
        tickets = (await asyncio.to_thread(db.get_user_tickets, call.from_user.id))
        await _safe_edit(call.message, f"✅ تیکت #{ticket_id} بسته شد.", reply_markup=kb.tickets_list_kb(tickets))
        await call.answer()

    # -----------------------------------------------------------------------
    # پل بین منوی شیشه‌ای بالا (Inline) و همان هندلرهای منوی پایین (Reply)
    # چون هر دکمه‌ی پایین از قبل یک هندلر مستقل دارد، به‌جای تکرار منطق هرکدام،
    # کلیک روی دکمه‌ی شیشه‌ای معادل، مستقیماً همان تابع را با کاربرِ واقعیِ
    # کلیک‌کننده (call.from_user) صدا می‌زند تا رفتار دقیقاً یکسان بماند.
    # -----------------------------------------------------------------------

    @router.callback_query(F.data.startswith("mm:"))
    async def cb_main_menu_inline(call: CallbackQuery, state: FSMContext, bot: Bot):
        await call.answer()
        key = call.data.split(":", 1)[1]
        # پیام جعلی: همان پیام بات ولی از_user واقعیِ کلیک‌کننده، تا هندلرهای
        # زیر که message.from_user.id می‌خوانند درست کار کنند
        fake_message = call.message.model_copy(update={"from_user": call.from_user})

        if key == "language":
            await fake_message.answer(
                db.get_text("handlers_user.language.choose", "لطفاً زبان موردنظر را انتخاب کنید:"),
                reply_markup=kb.language_kb(db),
            )
        elif key == "btn_buy":
            await show_categories(fake_message, state)
        elif key == "btn_test":
            await get_test_config(fake_message)
        elif key == "btn_my_orders":
            await my_orders(fake_message)
        elif key == "btn_tutorial":
            await tutorial_menu_entry(fake_message)
        elif key == "btn_wallet":
            await wallet_menu(fake_message)
        elif key == "btn_referral":
            await referral_menu(fake_message, bot)
        elif key == "btn_wheel":
            await wheel_of_fortune(fake_message, bot)
        elif key == "btn_contact":
            await contact_start(fake_message, state)
        elif key == "btn_reseller_panel":
            await reseller_panel_open(fake_message, state)
        elif key == "btn_reseller_tiers":
            await reseller_tiers_menu(fake_message)
        # کلید "btn_admin_panel" در handlers_admin.py مدیریت می‌شود چون هندلر
        # اصلی آن (open_admin_panel) در همان روتر تعریف شده است.

    return router
