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

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError

import keyboards as kb
from states import BuyFlow, ContactFlow, DiscountEntry, WalletTopup, CustomConfigFlow, ResellerFlow, ResellerRequestFlow
from config import MAX_TEST_PER_USER, RESELLER_DBS_DIR, resolve_db_path
from database import Database
from config_delivery import deliver_config_to_user
from force_join import is_channel_member, CHECK_CALLBACK
from sub_info import fetch_sub_info, format_sub_info_fa, fetch_individual_links
from stock_alerts import check_and_notify_low_stock
import crypto_payment
import abangateway_payment
from panel_providers import get_provider, PanelError, PanelUsernameTakenError
from reseller_auto_provision import provision_auto_config, provision_test_config, ProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError


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


def create_user_router(db, is_main_bot: bool = True, bot_manager=None) -> Router:
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
    router = Router()

    async def _send_inline_main_menu(target, user_tg_id: int):
        """اگر منوی شیشه‌ای بالا از تنظیمات فعال باشد، آن را به‌عنوان یک پیام
        جدا (کنار/بعد از منوی پایین) ارسال می‌کند. target هر شیء‌ای است که
        متد answer async دارد (Message یا call.message)."""
        inline_kb = (await asyncio.to_thread(kb.inline_menu_for_user, db, user_tg_id, is_main_bot))
        if inline_kb is not None:
            await target.answer("📋 منو:", reply_markup=inline_kb)

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
            await call.answer("✅ عضویت شما تایید شد.", show_alert=True)
            try:
                await call.message.delete()
            except Exception:
                pass
            welcome = (await asyncio.to_thread(db.get_setting, "welcome_text"))
            await call.message.answer(welcome, reply_markup=kb.menu_for_user(db, call.from_user.id, is_main_bot))
            await _send_inline_main_menu(call.message, call.from_user.id)
        else:
            await call.answer("❌ هنوز عضو کانال نشده‌اید.", show_alert=True)

    # -----------------------------------------------------------------------
    # شروع
    # -----------------------------------------------------------------------

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext, bot: Bot):
        await state.clear()
        (await asyncio.to_thread(db.add_or_update_user, 
            message.from_user.id, message.from_user.username or "", message.from_user.first_name or ""
        ))

        # پردازش لینک دعوت زیرمجموعه‌گیری: /start ref123456789
        # (نیازی به «کاربر جدید بودن» نیست؛ خود set_referred_by فقط وقتی کاربر
        # هنوز referred_by ندارد آن را ثبت می‌کند - همین‌جا هم برای جلوگیری از
        # اعمال چندباره‌ی پاداش‌های حالت ۲/۳، دقیقاً همان شرط را چک می‌کنیم)
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("ref"):
            ref_part = parts[1][3:]
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

        welcome = (await asyncio.to_thread(db.get_setting, "welcome_text"))
        await message.answer(welcome, reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot))
        await _send_inline_main_menu(message, message.from_user.id)

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
                    f"🤝 یک نفر با لینک دعوت شما به بات آمد!\n"
                    f"💰 {invite_bonus:,} تومان به کیف پول شما اضافه شد.",
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
                        "🎁 شما با تعداد دعوت‌های خود، یک کانفیگ رایگان برنده شدید! "
                        "برای دریافت آن با پشتیبانی تماس بگیرید.",
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
                        "🎁 شما با تعداد دعوت‌های خود، یک کانفیگ رایگان برنده شدید؛ اما در ساخت "
                        "خودکار آن مشکلی پیش آمد. لطفاً با پشتیبانی تماس بگیرید.",
                    )
                except Exception:
                    pass
                return
            try:
                links_text = "\n".join(f"🔗 {r['subscription_url']}" for r in prov_results)
                await bot.send_message(
                    referrer_id,
                    f"🎉 تبریک! با دعوت موفق دوستانتان، محصول «{product['name']}» به‌صورت رایگان برای شما "
                    f"ساخته شد:\n\n{links_text}",
                )
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # مینی‌اپ (دکمه‌ی متنی -> پیام با دکمه‌ی inline واقعی وب‌اپ)
    # -----------------------------------------------------------------------

    @router.message(F.text == kb.MINIAPP_BTN_TEXT)
    async def open_miniapp(message: Message):
        miniapp_url = kb._miniapp_url(db)
        if not miniapp_url:
            return
        await message.answer(
            "برای ورود به مینی‌اپ فروشگاه، روی دکمه‌ی زیر بزن:",
            reply_markup=kb.miniapp_inline_kb(miniapp_url),
        )

    # -----------------------------------------------------------------------
    # خرید کانفیگ
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_buy")))
    async def show_categories(message: Message, state: FSMContext):
        await state.clear()
        categories = (await asyncio.to_thread(db.get_categories, active_only=True))
        custom_enabled = is_main_bot and (await asyncio.to_thread(db.get_setting, "custom_config_enabled", "0")) == "1"
        if not categories and not custom_enabled:
            await message.answer("در حال حاضر دسته‌بندی فعالی وجود ندارد.")
            return
        await message.answer("یک گزینه را انتخاب کنید:", reply_markup=kb.categories_kb(db, categories, is_main_bot))

    @router.callback_query(F.data == "custom_config_start")
    async def cb_custom_config_start(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
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
        await call.message.edit_text("یک دسته‌بندی را انتخاب کنید:", reply_markup=kb.categories_kb(db, categories, is_main_bot))
        await call.answer()

    @router.callback_query(F.data.startswith("cat:"))
    async def cb_category(call: CallbackQuery):
        cat_id = int(call.data.split(":")[1])
        products = (await asyncio.to_thread(db.get_products, cat_id, active_only=True))
        if not products:
            await call.answer("محصولی در این دسته‌بندی موجود نیست.", show_alert=True)
            return
        await call.message.edit_text("یک محصول را انتخاب کنید:", reply_markup=kb.products_kb(db, products, cat_id))
        await call.answer()

    def _product_confirm_text(product, quantity: int, stock: int, wallet_credit: int) -> str:
        stock_line = (
            "⚡️ این محصول خودکار و لحظه‌ای ساخته می‌شود (محدودیت موجودی ندارد)\n"
            if product["is_auto_provision"] else
            f"📊 موجودی: {stock} عدد\n"
        )
        text = (
            f"📦 {product['name']}\n"
            f"💰 قیمت واحد: {product['price']:,} تومان\n"
            f"📝 توضیحات: {product['description'] or '---'}\n"
            f"{stock_line}"
        )
        if quantity > 1:
            text += f"\n🔢 تعداد انتخابی: {quantity} عدد\n💵 جمع کل: {product['price'] * quantity:,} تومان\n"
        if wallet_credit > 0:
            text += f"\n👛 موجودی کیف پول شما: {wallet_credit:,} تومان (به‌صورت خودکار در پرداخت اعمال می‌شود)\n"
        return text

    @router.callback_query(F.data.startswith("prod:"))
    async def cb_product(call: CallbackQuery):
        product_id = int(call.data.split(":")[1])
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product:
            await call.answer("محصول یافت نشد.", show_alert=True)
            return
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, call.from_user.id))
        if stock <= 0:
            text = _product_confirm_text(product, 1, stock, wallet_credit)
            text += "\n⛔️ در حال حاضر موجودی این محصول تمام شده است."
            await call.message.edit_text(text)
            await call.answer()
            return
        text = _product_confirm_text(product, 1, stock, wallet_credit)
        await call.message.edit_text(text, reply_markup=kb.product_confirm_kb(db, product_id, 1, stock))
        await call.answer()

    async def _cb_qty_change(call: CallbackQuery, delta: int):
        _, product_id, quantity = call.data.split(":")
        product_id, quantity = int(product_id), int(quantity)
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product:
            await call.answer("محصول یافت نشد.", show_alert=True)
            return
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        if stock <= 0:
            await call.answer("این محصول در حال حاضر موجود نیست.", show_alert=True)
            return
        quantity = max(1, min(quantity + delta, stock))
        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, call.from_user.id))
        text = _product_confirm_text(product, quantity, stock, wallet_credit)
        await call.message.edit_text(text, reply_markup=kb.product_confirm_kb(db, product_id, quantity, stock))
        await call.answer()

    @router.callback_query(F.data.startswith("qty_inc:"))
    async def cb_qty_inc(call: CallbackQuery):
        await _cb_qty_change(call, 1)

    @router.callback_query(F.data.startswith("qty_dec:"))
    async def cb_qty_dec(call: CallbackQuery):
        await _cb_qty_change(call, -1)

    @router.callback_query(F.data == "noop")
    async def cb_noop(call: CallbackQuery):
        await call.answer()

    @router.callback_query(F.data.startswith("enter_code:"))
    async def cb_enter_code(call: CallbackQuery, state: FSMContext):
        _, product_id, quantity = call.data.split(":")
        await state.update_data(discount_product_id=int(product_id), discount_quantity=int(quantity))
        await state.set_state(DiscountEntry.waiting_code)
        await call.message.edit_text("🎟 کد تخفیف را ارسال کنید:", reply_markup=kb.cancel_kb())
        await call.answer()

    @router.message(DiscountEntry.waiting_code)
    async def process_discount_code(message: Message, state: FSMContext):
        data = await state.get_data()
        product_id = data.get("discount_product_id")
        quantity = data.get("discount_quantity", 1)
        product = (await asyncio.to_thread(db.get_product, product_id)) if product_id else None
        if not product:
            await message.answer("محصول معتبر نیست. لطفاً دوباره از منو شروع کنید.")
            await state.clear()
            return

        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        quantity = max(1, min(quantity, stock)) if stock > 0 else quantity

        code_row = (await asyncio.to_thread(db.get_discount_code, message.text.strip()))
        if not (await asyncio.to_thread(db.is_discount_code_valid, code_row)):
            await message.answer(
                "❌ این کد تخفیف نامعتبر، غیرفعال یا به سقف استفاده رسیده است. دوباره تلاش کنید یا بدون کد ادامه دهید.",
                reply_markup=kb.cancel_kb(),
            )
            return

        total_price = product["price"] * quantity
        discount_amount = (await asyncio.to_thread(db.compute_discount_amount, code_row, total_price))
        await state.update_data(discount_code_id=code_row["id"], discount_amount=discount_amount)
        await state.set_state(None)

        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, message.from_user.id))
        price_after_code = total_price - discount_amount
        wallet_used_preview = min(wallet_credit, price_after_code)
        final_preview = price_after_code - wallet_used_preview

        text = (
            f"✅ کد تخفیف اعمال شد!\n\n"
            f"📦 {product['name']}\n"
            f"🔢 تعداد: {quantity} عدد\n"
            f"💰 قیمت کل: {total_price:,} تومان\n"
            f"🎟 تخفیف کد: {discount_amount:,} تومان\n"
        )
        if wallet_used_preview > 0:
            text += f"👛 اعمال کیف پول: {wallet_used_preview:,} تومان\n"
        text += f"💵 مبلغ نهایی قابل پرداخت: {final_preview:,} تومان\n"
        text += f"📊 موجودی: {stock} عدد"

        await message.answer(text, reply_markup=kb.product_confirm_kb(db, product_id, quantity, max(stock, quantity)))

    async def _notify_admins_of_order(bot: Bot, order_id: int, receipt_file_id: str = None, receipt_type: str = "photo"):
        order = (await asyncio.to_thread(db.get_order, order_id))

        if order["is_custom_config"]:
            user_row = (await asyncio.to_thread(db.get_user, order["user_id"]))
            username = user_row["username"] if user_row else ""
            first_name = user_row["first_name"] if user_row else ""
            caption = (
                f"🧾 سفارش کانفیگ شخصی #{order_id}\n"
                f"👤 کاربر: {first_name or ''} (@{username or '---'})\n"
                f"🆔 آیدی عددی: {order['user_id']}\n"
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

        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        user_row = (await asyncio.to_thread(db.get_user, order["user_id"]))
        username = user_row["username"] if user_row else ""
        first_name = user_row["first_name"] if user_row else ""

        quantity = order["quantity"] or 1
        caption = (
            f"🧾 سفارش #{order_id}\n"
            f"👤 کاربر: {first_name or ''} (@{username or '---'})\n"
            f"🆔 آیدی عددی: {order['user_id']}\n"
            f"📦 محصول: {product['name']}"
            + (f" × {quantity}\n" if quantity > 1 else "\n")
            + f"💰 قیمت پایه: {order['base_price']:,} تومان\n"
        )
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

    @router.callback_query(F.data.startswith("check_aban:"))
    async def cb_check_abangateway(call: CallbackQuery, bot: Bot):
        try:
            invoice_db_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            await call.answer("داده نامعتبر.", show_alert=True)
            return
        invoice_row = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_db_id))
        if not invoice_row or invoice_row["user_id"] != call.from_user.id:
            await call.answer("فاکتور یافت نشد.", show_alert=True)
            return

        await call.answer("در حال بررسی وضعیت پرداخت...")
        result = await abangateway_payment.try_verify_and_finalize(db, invoice_row)

        if result == "not_paid_yet":
            await call.message.answer("⏳ هنوز واریزی برای این فاکتور تایید نشده. کمی صبر کن و دوباره بررسی کن.")
            return
        if result in ("expired", "cancelled"):
            await call.message.answer("❌ اعتبار این فاکتور تمام شده یا لغو شده. لطفاً دوباره از منو اقدام کن.")
            return
        if result == "already_delivered":
            await call.message.answer("✅ این پرداخت قبلاً تایید و تحویل داده شده است.")
            return
        if result.startswith("error:"):
            await call.message.answer(f"⚠️ خطا در بررسی وضعیت: {result[6:]}")
            return

        # result == "verified_now"
        if invoice_row["kind"] == "wallet_topup":
            text = await abangateway_payment.finalize_paid_topup(db, invoice_row["ref_id"])
        else:
            text = await abangateway_payment.finalize_paid_order(
                db, bot, invoice_row["ref_id"], notify_admins_fn=_notify_admins_of_order
            )
        await call.message.answer(text)

    @router.callback_query(F.data.startswith("buy_start:"))
    async def cb_buy_start(call: CallbackQuery, state: FSMContext, bot: Bot):
        _, product_id, quantity = call.data.split(":")
        product_id, quantity = int(product_id), int(quantity)
        product = (await asyncio.to_thread(db.get_product, product_id))
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        if not product or stock <= 0:
            await call.answer("این محصول در حال حاضر موجود نیست.", show_alert=True)
            return
        if quantity < 1:
            quantity = 1
        if quantity > stock:
            await call.answer(f"موجودی کافی نیست. فقط {stock} عدد موجود است.", show_alert=True)
            return

        data = await state.get_data()
        discount_code_id = data.get("discount_code_id")
        discount_amount = data.get("discount_amount", 0) or 0

        total_price = product["price"] * quantity
        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, call.from_user.id))
        price_after_code = max(total_price - discount_amount, 0)
        wallet_used = min(wallet_credit, price_after_code)

        if wallet_used > 0:
            (await asyncio.to_thread(db.add_wallet_credit, call.from_user.id, -wallet_used))
        if discount_code_id:
            (await asyncio.to_thread(db.increment_discount_usage, discount_code_id))

        order_id = (await asyncio.to_thread(db.create_order, 
            call.from_user.id,
            product_id,
            base_price=total_price,
            wallet_used=wallet_used,
            discount_code_id=discount_code_id,
            discount_amount=discount_amount,
            quantity=quantity,
        ))
        order = (await asyncio.to_thread(db.get_order, order_id))
        await state.update_data(order_id=order_id)
        await state.update_data(discount_code_id=None, discount_amount=0, discount_product_id=None)

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
                    await call.message.edit_text(
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
                    await call.message.edit_text(
                        "⛔️ موجودی این محصول در حال حاضر تمام شده است.\n"
                        "مبلغ کسرشده از کیف پول شما به‌طور کامل بازگردانده شد. لطفاً بعداً دوباره تلاش کنید "
                        "یا با پشتیبانی در تماس باشید."
                    )
                    await call.answer()
                    return
                (await asyncio.to_thread(db.approve_order, order_id, [r["id"] for r in results]))
                links = [r["link"] for r in results]
                await check_and_notify_low_stock(bot.send_message, db, product_id)
            reward_info = (await asyncio.to_thread(db.reward_referrer_if_first_purchase, call.from_user.id, order["base_price"]))
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

            # اطلاع‌رسانی به ادمین‌ها فقط جهت آگاهی (نیازی به تایید دستی نیست)
            try:
                await _notify_admins_of_order(bot, order_id)
            except Exception:
                pass

            await call.message.edit_text(
                "✅ مبلغ سفارش شما به‌طور کامل از کیف پول/تخفیف پوشش داده شد.\n"
                "کانفیگ شما در پیام بعدی ارسال می‌شود 👇"
            )
            await deliver_config_to_user(
                bot,
                call.from_user.id,
                product["name"],
                links,
                final_price=0,
                order_id=order_id,
            )
            await call.answer()
            return

        await state.set_state(BuyFlow.waiting_receipt)

        card_number = (await asyncio.to_thread(db.get_setting, "card_number"))
        card_holder = (await asyncio.to_thread(db.get_setting, "card_holder"))
        after_buy_text = (await asyncio.to_thread(db.get_setting, "after_buy_text"))

        text = f"{after_buy_text}\n\n"
        if quantity > 1:
            text += f"🔢 تعداد: {quantity} عدد\n"
        text += f"💳 شماره کارت: `{card_number}`\n"
        text += f"👤 به نام: {card_holder}\n"
        if discount_amount:
            text += f"🎟 تخفیف کد: {discount_amount:,} تومان\n"
        if wallet_used:
            text += f"👛 استفاده از کیف پول: {wallet_used:,} تومان\n"
        text += f"💰 مبلغ نهایی قابل پرداخت: {order['final_price']:,} تومان\n\n"
        text += "لطفاً عکس رسید پرداخت را همینجا ارسال کنید، یا از دکمه‌ی زیر با ارز دیجیتال پرداخت کنید."

        await call.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=kb.payment_choice_kb(
                crypto_payment.crypto_payment_available(db),
                abangateway_payment.abangateway_payment_available(db),
            ),
        )
        await call.answer()

    @router.callback_query(F.data == "cancel_flow")
    async def cb_cancel_flow(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        if order_id:
            order = (await asyncio.to_thread(db.get_order, order_id))
            if order and order["status"] == "pending":
                (await asyncio.to_thread(db.reject_order, order_id))
        await state.clear()
        await call.message.edit_text("عملیات لغو شد.")
        await call.answer()

    @router.callback_query(F.data == "pay_crypto", BuyFlow.waiting_receipt)
    async def cb_pay_crypto_order(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer("سفارش معتبر یافت نشد.", show_alert=True)
            return
        await call.answer("در حال ساخت فاکتور...")
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
            "🪙 فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.\n"
            "⏳ اعتبار این فاکتور فقط ۸۰ دقیقه است.\n"
            "به‌محض تایید تراکنش روی بلاک‌چین، سفارش شما به‌صورت خودکار تحویل داده می‌شود.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔗 رفتن به صفحه‌ی پرداخت", url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data == "pay_abangateway", BuyFlow.waiting_receipt)
    async def cb_pay_abangateway_order(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer("سفارش معتبر یافت نشد.", show_alert=True)
            return
        await call.answer("در حال ساخت فاکتور...")
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
            "💳 فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن.\n"
            "⏳ اعتبار این فاکتور محدود است.\n"
            "معمولاً به‌محض واریز، سفارش خودکار تحویل داده می‌شود؛ اگر چند دقیقه طول کشید، "
            "دکمه‌ی «بررسی وضعیت پرداخت» را بزن.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 رفتن به صفحه‌ی پرداخت", url=result["payment_url"])],
                [InlineKeyboardButton(text="🔄 بررسی وضعیت پرداخت", callback_data=f"check_aban:{invoice_row['id']}")],
            ]),
        )

    @router.message(BuyFlow.waiting_receipt, F.photo | F.document)
    async def receive_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order or order["status"] != "pending":
            await message.answer("سفارش معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.")
            await state.clear()
            return

        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            await message.answer("لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_order_receipt, order_id, file_id, receipt_type))

        await _notify_admins_of_order(
            bot, order_id, receipt_file_id=file_id, receipt_type=receipt_type
        )

        await message.answer(
            "✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، کانفیگ برای شما ارسال خواهد شد.",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        await state.clear()

    @router.message(BuyFlow.waiting_receipt)
    async def receipt_wrong_type(message: Message):
        await message.answer("لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.")

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
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            await message.answer("این بخش در حال حاضر غیرفعال است.")
            return
        settings = (await asyncio.to_thread(db.get_custom_config_settings))
        if not settings["enabled"]:
            await message.answer("این بخش در حال حاضر غیرفعال است.")
            return
        server = (await asyncio.to_thread(db.get_panel_server_for_usage, "custom_config"))
        if not server:
            await message.answer("در حال حاضر سروری برای ساخت کانفیگ شخصی فعال نیست. لطفاً بعداً تلاش کنید.")
            return
        tiers = (await asyncio.to_thread(db.get_pricing_tiers))
        if not tiers:
            await message.answer("قیمت‌گذاری این بخش هنوز توسط ادمین تنظیم نشده است.")
            return
        await state.set_state(CustomConfigFlow.waiting_username)
        await state.update_data(panel_server_id=server["id"])
        await message.answer(
            "🛠 ساخت کانفیگ شخصی\n\n"
            "لطفاً یک نام کاربری دلخواه برای کانفیگ خود ارسال کنید، یا از دکمه‌ی زیر یک نام تصادفی بگیر.\n"
            "فقط حروف انگلیسی، عدد و آندرلاین مجاز است (بین ۳ تا ۲۰ کاراکتر).",
            reply_markup=kb.custom_config_username_kb(),
        )

    @router.callback_query(F.data == "custom_config_random_username", CustomConfigFlow.waiting_username)
    async def cb_custom_config_random_username(call: CallbackQuery, state: FSMContext):
        for _ in range(10):
            candidate = "u" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
            if not (await asyncio.to_thread(db.is_custom_username_taken, candidate)):
                break
        await call.answer()
        await _custom_config_apply_username(call.message, state, candidate)

    @router.message(CustomConfigFlow.waiting_username)
    async def custom_config_receive_username(message: Message, state: FSMContext):
        username = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            await message.answer("❌ نام کاربری نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.")
            return
        if (await asyncio.to_thread(db.is_custom_username_taken, username)):
            await message.answer("❌ این نام کاربری قبلاً استفاده شده. لطفاً نام دیگری انتخاب کنید.")
            return
        await _custom_config_apply_username(message, state, username)

    async def _custom_config_apply_username(message: Message, state: FSMContext, username: str):
        settings = (await asyncio.to_thread(db.get_custom_config_settings))
        tiers = (await asyncio.to_thread(db.get_pricing_tiers))
        await state.update_data(custom_username=username)
        await state.set_state(CustomConfigFlow.waiting_volume)
        await message.answer(
            f"✅ نام کاربری: {username}\n\n"
            f"{_format_pricing_table(tiers)}\n\n"
            f"📶 حالا حجم مورد نظر خود را به گیگابایت وارد کنید.\n"
            f"حداقل: {settings['min_gb']} گیگ — حداکثر: {settings['max_gb']} گیگ\n"
            f"⏳ مدت اعتبار: {settings['duration_days']} روز (ثابت)",
            reply_markup=kb.cancel_kb(),
        )

    @router.message(CustomConfigFlow.waiting_volume)
    async def custom_config_receive_volume(message: Message, state: FSMContext):
        settings = (await asyncio.to_thread(db.get_custom_config_settings))
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer("❌ لطفاً فقط عدد صحیح وارد کنید (به گیگابایت).")
            return
        volume_gb = int(text)
        if volume_gb < settings["min_gb"] or volume_gb > settings["max_gb"]:
            await message.answer(
                f"❌ حجم باید بین {settings['min_gb']} تا {settings['max_gb']} گیگابایت باشد."
            )
            return

        price = (await asyncio.to_thread(db.calc_custom_config_price, volume_gb))
        if price <= 0:
            await message.answer("⚠️ قیمت‌گذاری برای این بخش هنوز تنظیم نشده. لطفاً با پشتیبانی تماس بگیرید.")
            await state.clear()
            return

        data = await state.get_data()
        username = data.get("custom_username")
        server = (await asyncio.to_thread(db.get_panel_server, data.get("panel_server_id")))
        if not server or not server["is_active"]:
            await message.answer("⛔️ سرور این بخش دیگر در دسترس نیست. لطفاً دوباره از منو شروع کنید.")
            await state.clear()
            return

        wallet_credit = (await asyncio.to_thread(db.get_wallet_credit, message.from_user.id))
        wallet_used = min(wallet_credit, price)

        if wallet_used > 0:
            (await asyncio.to_thread(db.add_wallet_credit, message.from_user.id, -wallet_used))

        order_id = (await asyncio.to_thread(db.create_custom_config_order, 
            message.from_user.id, volume_gb, username, server["id"],
            base_price=price, wallet_used=wallet_used,
        ))
        order = (await asyncio.to_thread(db.get_order, order_id))
        await state.update_data(order_id=order_id, custom_volume_gb=volume_gb)

        if order["final_price"] <= 0:
            await state.clear()
            (await asyncio.to_thread(db.approve_custom_config_order, order_id))
            server_row = (await asyncio.to_thread(db.get_panel_server, server["id"]))
            try:
                provider = get_provider(server_row)
                result = await provider.create_user(username, volume_gb, settings["duration_days"])
            except Exception as e:
                (await asyncio.to_thread(db.reject_order, order_id))
                await message.answer(f"⛔️ خطا در ساخت کانفیگ روی پنل: {e}\nمبلغ به کیف پول بازگردانده شد.")
                return
            (await asyncio.to_thread(db.add_custom_config, 
                message.from_user.id, server["id"], result.username, volume_gb,
                settings["duration_days"], result.subscription_url, order_id=order_id,
            ))
            await message.answer(
                "✅ مبلغ سفارش شما به‌طور کامل از کیف پول پوشش داده شد.\n"
                "کانفیگ شما در پیام بعدی ارسال می‌شود 👇",
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)
            await deliver_config_to_user(
                message.bot, message.from_user.id, "کانفیگ شخصی",
                [result.subscription_url], final_price=0, order_id=order_id,
            )
            try:
                await _notify_admins_of_order(message.bot, order_id)
            except Exception:
                pass
            return

        await state.set_state(CustomConfigFlow.waiting_receipt)
        card_number = (await asyncio.to_thread(db.get_setting, "card_number"))
        card_holder = (await asyncio.to_thread(db.get_setting, "card_holder"))
        text = (
            f"🛠 نام کاربری: {username}\n"
            f"📶 حجم: {volume_gb} گیگابایت\n"
            f"⏳ مدت: {settings['duration_days']} روز\n\n"
            f"💳 شماره کارت: `{card_number}`\n"
            f"👤 به نام: {card_holder}\n"
        )
        if wallet_used:
            text += f"👛 استفاده از کیف پول: {wallet_used:,} تومان\n"
        text += f"💰 مبلغ نهایی قابل پرداخت: {order['final_price']:,} تومان\n\n"
        text += "لطفاً عکس رسید پرداخت را همینجا ارسال کنید، یا از دکمه‌ی زیر با ارز دیجیتال پرداخت کنید."
        await message.answer(
            text, parse_mode="Markdown",
            reply_markup=kb.payment_choice_kb(
                crypto_payment.crypto_payment_available(db),
                abangateway_payment.abangateway_payment_available(db),
            ),
        )

    @router.callback_query(F.data == "pay_crypto", CustomConfigFlow.waiting_receipt)
    async def cb_pay_crypto_custom_config(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer("سفارش معتبر یافت نشد.", show_alert=True)
            return
        await call.answer("در حال ساخت فاکتور...")
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
            "🪙 فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.\n"
            "⏳ اعتبار این فاکتور فقط ۸۰ دقیقه است.\n"
            "به‌محض تایید تراکنش روی بلاک‌چین، کانفیگ شما به‌صورت خودکار ساخته می‌شود.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔗 رفتن به صفحه‌ی پرداخت", url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data == "pay_abangateway", CustomConfigFlow.waiting_receipt)
    async def cb_pay_abangateway_custom_config(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id)) if order_id else None
        if not order or order["status"] != "pending":
            await call.answer("سفارش معتبر یافت نشد.", show_alert=True)
            return
        await call.answer("در حال ساخت فاکتور...")
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
            "💳 فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن.\n"
            "معمولاً به‌محض واریز، کانفیگ خودکار ساخته می‌شود؛ اگر چند دقیقه طول کشید، "
            "دکمه‌ی «بررسی وضعیت پرداخت» را بزن.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 رفتن به صفحه‌ی پرداخت", url=result["payment_url"])],
                [InlineKeyboardButton(text="🔄 بررسی وضعیت پرداخت", callback_data=f"check_aban:{invoice_row['id']}")],
            ]),
        )

    @router.message(CustomConfigFlow.waiting_receipt, F.photo | F.document)
    async def receive_custom_config_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        order_id = data.get("order_id")
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order or order["status"] != "pending":
            await message.answer("سفارش معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.")
            await state.clear()
            return

        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            await message.answer("لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_order_receipt, order_id, file_id, receipt_type))
        await _notify_admins_of_order(
            bot, order_id, receipt_file_id=file_id, receipt_type=receipt_type
        )
        await message.answer(
            "✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، کانفیگ شخصی شما ساخته و ارسال خواهد شد.",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        await state.clear()

    @router.message(CustomConfigFlow.waiting_receipt)
    async def custom_config_receipt_wrong_type(message: Message):
        await message.answer("لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.")

    # -----------------------------------------------------------------------
    # کانفیگ تست
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_test")))
    async def get_test_config(message: Message):
        if (await asyncio.to_thread(db.get_setting, "test_enabled", "1")) != "1":
            await message.answer("در حال حاضر امکان دریافت کانفیگ تست غیرفعال است.")
            return

        user = (await asyncio.to_thread(db.get_user, message.from_user.id))
        if user and user["test_used"] >= MAX_TEST_PER_USER:
            await message.answer("شما قبلاً کانفیگ تست خود را دریافت کرده‌اید. هر کاربر فقط یک بار مجاز به دریافت کانفیگ تست است.")
            return

        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            # نماینده سطح ۲: کانفیگ تست هم خودکار و از اعتبار حجمی نماینده ساخته می‌شود
            try:
                result = await provision_test_config(db, user_id=message.from_user.id)
            except ProvisionError as e:
                await message.answer(f"⛔️ {e}")
                return
            (await asyncio.to_thread(db.mark_test_used, message.from_user.id))
            await message.answer(
                f"🧪 کانفیگ تست شما ({result['volume_gb']} گیگ، {result['duration_days']} روز):\n\n`{result['subscription_url']}`",
                parse_mode="Markdown",
            )
            return

        panel_server = (await asyncio.to_thread(db.get_panel_server_for_usage, "test_config"))
        if panel_server:
            volume_gb = int((await asyncio.to_thread(db.get_setting, "test_config_panel_volume_gb", "1")) or 1)
            duration_days = int((await asyncio.to_thread(db.get_setting, "test_config_panel_duration_days", "1")) or 1)
            for _ in range(10):
                username = "test" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
                if not (await asyncio.to_thread(db.is_custom_username_taken, username)):
                    break
            try:
                provider = get_provider(panel_server)
                result = await provider.create_user(username, volume_gb, duration_days)
            except PanelError as e:
                await message.answer(f"⛔️ خطا در ساخت کانفیگ تست: {e}\nلطفاً بعداً تلاش کنید.")
                return
            (await asyncio.to_thread(db.add_custom_config, 
                message.from_user.id, panel_server["id"], result.username,
                volume_gb, duration_days, result.subscription_url, source="test",
            ))
            (await asyncio.to_thread(db.mark_test_used, message.from_user.id))
            await message.answer(
                f"🧪 کانفیگ تست شما ({volume_gb} گیگ، {duration_days} روز):\n\n`{result.subscription_url}`",
                parse_mode="Markdown",
            )
            return

        result = (await asyncio.to_thread(db.take_unused_test_config, message.from_user.id))
        if not result:
            await message.answer("متاسفانه موجودی کانفیگ تست تمام شده است. لطفاً بعداً مراجعه کنید.")
            return

        (await asyncio.to_thread(db.mark_test_used, message.from_user.id))
        await message.answer(f"🧪 کانفیگ تست شما:\n\n`{result['link']}`", parse_mode="Markdown")

    # -----------------------------------------------------------------------
    # پنل نمایندگی (ساخت کانفیگ از استخر حجم بدون پرداخت جداگانه)
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_reseller_panel", "🧑‍💼 پنل نمایندگی")))
    async def reseller_panel_open(message: Message, state: FSMContext):
        if not (await asyncio.to_thread(db.is_reseller, message.from_user.id)):
            return
        await state.clear()
        credit = (await asyncio.to_thread(db.get_reseller_credit, message.from_user.id))
        await message.answer(
            f"🧑‍💼 پنل نمایندگی\n\n"
            f"📦 اعتبار باقی‌مانده: {credit:,} گیگابایت\n\n"
            f"می‌تونی از این اعتبار مستقیم کانفیگ بسازی، بدون پرداخت جداگانه. "
            f"با هر قیمتی که خودت بخوای می‌تونی به مشتری‌هات بفروشیش.",
            reply_markup=kb.reseller_panel_kb(),
        )

    @router.callback_query(F.data == "reseller_new_config")
    async def cb_reseller_new_config(call: CallbackQuery, state: FSMContext):
        if not (await asyncio.to_thread(db.is_reseller, call.from_user.id)):
            await call.answer("دسترسی نداری.", show_alert=True)
            return
        credit = (await asyncio.to_thread(db.get_reseller_credit, call.from_user.id))
        if credit <= 0:
            await call.answer("اعتبار شما کافی نیست. با ادمین تماس بگیر.", show_alert=True)
            return
        server = (await asyncio.to_thread(db.get_reseller_panel, call.from_user.id))
        if not server:
            await call.answer("هنوز سروری برای نمایندگی توسط ادمین تنظیم نشده.", show_alert=True)
            return
        await state.set_state(ResellerFlow.waiting_username)
        await state.update_data(panel_server_id=server["id"])
        await call.answer()
        await call.message.answer(
            "یک نام کاربری برای این کانفیگ وارد کن، یا از دکمه‌ی زیر یک نام تصادفی بگیر.\n"
            "فقط حروف انگلیسی، عدد و آندرلاین (بین ۳ تا ۲۰ کاراکتر).",
            reply_markup=kb.custom_config_username_kb(),
        )

    @router.callback_query(F.data == "custom_config_random_username", ResellerFlow.waiting_username)
    async def cb_reseller_random_username(call: CallbackQuery, state: FSMContext):
        for _ in range(10):
            candidate = "r" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
            if not (await asyncio.to_thread(db.is_custom_username_taken, candidate)):
                break
        await call.answer()
        await _reseller_apply_username(call.message, state, candidate)

    @router.message(ResellerFlow.waiting_username)
    async def reseller_receive_username(message: Message, state: FSMContext):
        username = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            await message.answer("❌ نام کاربری نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.")
            return
        if (await asyncio.to_thread(db.is_custom_username_taken, username)):
            await message.answer("❌ این نام کاربری قبلاً استفاده شده. لطفاً نام دیگری انتخاب کنید.")
            return
        await _reseller_apply_username(message, state, username)

    async def _reseller_apply_username(message: Message, state: FSMContext, username: str):
        credit = (await asyncio.to_thread(db.get_reseller_credit, message.from_user.id))
        await state.update_data(reseller_username=username)
        await state.set_state(ResellerFlow.waiting_volume)
        await message.answer(
            f"✅ نام کاربری: {username}\n\n"
            f"📦 اعتبار باقی‌مانده: {credit:,} گیگابایت\n"
            f"حالا حجم مورد نظر برای این کانفیگ را به گیگابایت وارد کن:",
            reply_markup=kb.cancel_kb(),
        )

    @router.message(ResellerFlow.waiting_volume)
    async def reseller_receive_volume(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("❌ لطفاً فقط عدد صحیح مثبت وارد کنید.")
            return
        volume_gb = int(text)
        credit = (await asyncio.to_thread(db.get_reseller_credit, message.from_user.id))
        if volume_gb > credit:
            await message.answer(f"❌ اعتبار شما کافی نیست. اعتبار باقی‌مانده: {credit:,} گیگ.")
            return

        data = await state.get_data()
        server = (await asyncio.to_thread(db.get_panel_server, data.get("panel_server_id")))
        if not server or not server["is_active"]:
            await message.answer("⛔️ سرور نمایندگی دیگر در دسترس نیست.")
            await state.clear()
            return

        duration_days = (await asyncio.to_thread(db.get_custom_config_settings))["duration_days"]
        try:
            provider = get_provider(server)
            result = await provider.create_user(data["reseller_username"], volume_gb, duration_days)
        except PanelUsernameTakenError:
            await message.answer("❌ این نام کاربری روی پنل تکراری است. دوباره از ابتدا با نام دیگری امتحان کن.")
            return
        except PanelError as e:
            await message.answer(f"⛔️ خطا در ساخت کانفیگ: {e}")
            return

        (await asyncio.to_thread(db.adjust_reseller_credit, message.from_user.id, -volume_gb, reason=f"ساخت کانفیگ «{result.username}»"))
        (await asyncio.to_thread(db.add_custom_config, 
            message.from_user.id, server["id"], result.username, volume_gb, duration_days, result.subscription_url,
            source="reseller",
        ))
        new_credit = (await asyncio.to_thread(db.get_reseller_credit, message.from_user.id))
        await state.clear()
        await message.answer(
            f"✅ کانفیگ ساخته شد!\n\n"
            f"🛠 نام کاربری: {result.username}\n"
            f"📶 حجم: {volume_gb} گیگ | ⏳ مدت: {duration_days} روز\n\n"
            f"`{result.subscription_url}`\n\n"
            f"📦 اعتبار باقی‌مانده: {new_credit:,} گیگابایت",
            parse_mode="Markdown",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)

    # -----------------------------------------------------------------------
    # سفارش‌های من (منوی کانفیگ‌ها + امکان حذف کامل هر کانفیگ)
    # -----------------------------------------------------------------------

    _MO_STATUS_MAP = {"pending": "⏳ در انتظار بررسی", "approved": "✅ تایید شده", "rejected": "❌ رد شده"}
    _MO_STATUS_ICON = {"pending": "⏳", "approved": "✅", "rejected": "❌"}

    def _my_orders_items(user_tg_id: int):
        """هر آیتم یک ردیف/دکمه‌ی جدا در منوست: یک کانفیگ محصول، یک کانفیگ شخصی،
        یا (فقط برای سفارش‌های در انتظار بررسی که هنوز کانفیگی ندارند) خود
        سفارش. سفارش‌های رد‌شده اصلاً نمایش داده نمی‌شوند (کانفیگی برایشان
        ساخته نشده، پس چیزی برای کاربر ندارند)."""
        items = []
        for o in db.get_user_orders(user_tg_id):
            if o["status"] == "rejected":
                continue
            if o["is_custom_config"]:
                # نسخه‌ی تاییدشده‌ی کانفیگ شخصی از جدول custom_configs (پایین‌تر)
                # با جزئیات کامل نمایش داده می‌شود؛ اینجا فقط سفارش‌های در
                # انتظار (که هنوز کانفیگی ندارند) را نشان می‌دهیم.
                if o["status"] != "approved":
                    label = (
                        f"{_MO_STATUS_ICON.get(o['status'], '')} #{o['id']} "
                        f"کانفیگ شخصی «{o['custom_username']}» ({o['custom_volume_gb']} گیگ)"
                    )
                    items.append({"cb_id": f"o{o['id']}", "kind": "order", "label": label, "order": o})
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
                if configs:
                    for i, cfg in enumerate(configs, start=1):
                        label = base_label + (f" ({i}/{len(configs)})" if len(configs) > 1 else "")
                        items.append({
                            "cb_id": f"c{cfg['id']}", "kind": "config", "label": label,
                            "order": o, "product_name": pname, "config": cfg,
                        })
                    continue
            items.append({"cb_id": f"o{o['id']}", "kind": "order", "label": base_label, "order": o, "product_name": pname})

        for cc in db.get_custom_configs_for_user(user_tg_id):
            if cc["source"] == "test":
                continue
            label = f"🛠 «{cc['username']}» ({cc['volume_gb']} گیگ / {cc['duration_days']} روز)"
            items.append({"cb_id": f"x{cc['id']}", "kind": "custom", "label": label, "custom": cc})
        return items

    def _find_my_orders_item(user_tg_id: int, cb_id: str):
        for it in _my_orders_items(user_tg_id):
            if it["cb_id"] == cb_id:
                return it
        return None

    async def _my_orders_item_text(item) -> str:
        kind = item["kind"]
        if kind == "config":
            cfg, o, pname = item["config"], item["order"], item["product_name"]
            text = f"📦 سفارش #{o['id']} | {pname}\n🔗 `{cfg['link']}`\n"
            if cfg["expires_at"]:
                text += f"⏳ انقضا: {cfg['expires_at']}\n"
            info = await fetch_sub_info(cfg["link"])
            text += f"\n{format_sub_info_fa(info)}"
            if str(cfg["link"]).startswith(("http://", "https://")):
                try:
                    individual_links = await fetch_individual_links(cfg["link"])
                except Exception:
                    individual_links = []
                if individual_links:
                    text += "\n\n📋 کانفیگ‌های تکی:\n" + "\n".join(f"`{c}`" for c in individual_links)
            return text
        if kind == "custom":
            cc = item["custom"]
            text = (
                f"🛠 کانفیگ شخصی «{cc['username']}»\n"
                f"📶 حجم: {cc['volume_gb']} گیگ | ⏳ مدت: {cc['duration_days']} روز\n"
            )
            if cc["expires_at"]:
                text += f"📅 انقضا: {cc['expires_at']}\n"
            if cc["subscription_url"]:
                text += f"🔗 `{cc['subscription_url']}`\n"
                info = await fetch_sub_info(cc["subscription_url"])
                text += f"\n{format_sub_info_fa(info)}"
                try:
                    individual_links = await fetch_individual_links(cc["subscription_url"])
                except Exception:
                    individual_links = []
                if individual_links:
                    text += "\n\n📋 کانفیگ‌های تکی:\n" + "\n".join(f"`{c}`" for c in individual_links)
            return text
        # kind == "order": سفارشی بدون کانفیگ فعلی (در انتظار بررسی/رد‌شده)
        o = item["order"]
        pname = item.get("product_name") or f"کانفیگ شخصی «{o['custom_username']}» ({o['custom_volume_gb']} گیگ)"
        return f"📦 سفارش #{o['id']} | {pname}\nوضعیت: {_MO_STATUS_MAP.get(o['status'], o['status'])}"

    async def _show_my_orders_list(target, user_tg_id: int, edit: bool):
        items = _my_orders_items(user_tg_id)
        if not items:
            text = "شما تاکنون سفارشی ثبت نکرده‌اید."
            if edit:
                await target.edit_text(text)
            else:
                await target.answer(text)
            return
        text = "📦 سفارش‌ها و کانفیگ‌های شما\n\nیکی از موارد زیر را برای مشاهده‌ی جزئیات انتخاب کنید:"
        markup = kb.my_orders_menu_kb(items)
        if edit:
            await target.edit_text(text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_my_orders")))
    async def my_orders(message: Message):
        await _show_my_orders_list(message, message.from_user.id, edit=False)

    @router.callback_query(F.data == "mo_back")
    async def cb_my_orders_back(call: CallbackQuery):
        await _show_my_orders_list(call.message, call.from_user.id, edit=True)
        await call.answer()

    @router.callback_query(F.data.startswith("mo_v:"))
    async def cb_my_orders_view(call: CallbackQuery):
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item:
            await call.answer("این مورد یافت نشد (شاید قبلاً حذف شده).", show_alert=True)
            await _show_my_orders_list(call.message, call.from_user.id, edit=True)
            return
        await call.answer()
        text = await _my_orders_item_text(item)
        deletable = item["kind"] in ("config", "custom")
        markup = kb.my_order_item_kb(cb_id, deletable)
        if len(text) > 4000:
            text = text[:3950] + "\n\n… (فهرست کوتاه شد؛ تعداد کانفیگ‌ها زیاد است)"
        try:
            await call.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        except TelegramBadRequest:
            await call.message.edit_text(text, reply_markup=markup)

    @router.callback_query(F.data.startswith("mo_del:"))
    async def cb_my_orders_delete_ask(call: CallbackQuery):
        cb_id = call.data.split(":", 1)[1]
        item = _find_my_orders_item(call.from_user.id, cb_id)
        if not item or item["kind"] not in ("config", "custom"):
            await call.answer("این مورد یافت نشد (شاید قبلاً حذف شده).", show_alert=True)
            await _show_my_orders_list(call.message, call.from_user.id, edit=True)
            return
        await call.answer()
        await call.message.edit_text(
            "⚠️ آیا مطمئن هستید؟\n\n"
            "با حذف این کانفیگ، اطلاعات و لینک آن برای همیشه از سیستم پاک می‌شود و "
            "این عملیات **غیرقابل بازگشت** است.",
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
            await call.answer("درخواست نامعتبر.", show_alert=True)
            return

        if kind == "c":
            removed = (await asyncio.to_thread(db.delete_owned_config, item_id, user_tg_id))
            if not removed:
                await call.answer("این کانفیگ یافت نشد (شاید قبلاً حذف شده).", show_alert=True)
            else:
                await call.answer("✅ کانفیگ برای همیشه حذف شد.", show_alert=True)
        elif kind == "x":
            cc = (await asyncio.to_thread(db.get_custom_configs_for_user, user_tg_id))
            cc_row = next((c for c in cc if c["id"] == item_id), None)
            if not cc_row:
                await call.answer("این کانفیگ یافت نشد (شاید قبلاً حذف شده).", show_alert=True)
            else:
                if cc_row["panel_server_id"]:
                    server = (await asyncio.to_thread(db.get_panel_server, cc_row["panel_server_id"]))
                    if server:
                        try:
                            provider = get_provider(server)
                            await provider.delete_user(cc_row["username"])
                        except Exception:
                            logging.getLogger("handlers_user").exception(
                                "حذف کاربر «%s» از پنل سرور #%s ناموفق بود؛ در هر صورت از لیست کاربر حذف می‌شود.",
                                cc_row["username"], cc_row["panel_server_id"],
                            )
                (await asyncio.to_thread(db.delete_owned_custom_config, item_id, user_tg_id))
                await call.answer("✅ کانفیگ برای همیشه حذف شد.", show_alert=True)
        else:
            await call.answer("درخواست نامعتبر.", show_alert=True)

        await _show_my_orders_list(call.message, user_tg_id, edit=True)

    # -----------------------------------------------------------------------
    # زیرمجموعه‌گیری (رفرال)
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_referral")))
    async def referral_menu(message: Message, bot: Bot):
        settings = (await asyncio.to_thread(db.get_all_settings))
        if settings.get("referral_button_enabled", "1") != "1":
            await message.answer("در حال حاضر سیستم زیرمجموعه‌گیری غیرفعال است.")
            return
        commission_on = settings.get("referral_enabled", "1") == "1"
        freeconfig_on = settings.get("referral_free_config_enabled", "0") == "1"
        invitebonus_on = settings.get("referral_invite_bonus_enabled", "0") == "1"

        if not (commission_on or freeconfig_on or invitebonus_on):
            await message.answer("در حال حاضر سیستم زیرمجموعه‌گیری غیرفعال است.")
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

        await message.answer("\n".join(lines))

    # -----------------------------------------------------------------------
    # کیف پول (جدا از زیرمجموعه‌گیری)
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_wallet")))
    async def wallet_menu(message: Message):
        balance = (await asyncio.to_thread(db.get_wallet_credit, message.from_user.id))
        text = (
            "👛 کیف پول شما\n\n"
            f"موجودی فعلی: {balance:,} تومان\n\n"
            "این موجودی (چه از شارژ دستی، چه از پورسانت زیرمجموعه‌گیری) به‌صورت خودکار در خرید بعدی شما کسر می‌شود."
        )
        await message.answer(text, reply_markup=kb.wallet_menu_kb())

    # -----------------------------------------------------------------------
    # گردونه شانس
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_wheel")))
    async def wheel_of_fortune(message: Message, bot: Bot):
        if (await asyncio.to_thread(db.get_setting, "wheel_enabled", "1")) != "1":
            await message.answer("در حال حاضر گردونه شانس غیرفعال است.")
            return

        can_spin, remaining_hours = (await asyncio.to_thread(db.can_spin_wheel, message.from_user.id))
        if not can_spin:
            hours = int(remaining_hours) + 1
            await message.answer(f"⏳ فردا دوباره امتحان کن! حدود {hours} ساعت دیگر می‌توانی دوباره گردونه را بچرخانی.")
            return

        # افکت چرخش: انیمیشن اسلات‌ماشین بومی تلگرام
        try:
            await bot.send_dice(message.chat.id, emoji="🎰")
        except Exception:
            await message.answer("🎡 در حال چرخش گردونه...")
        await asyncio.sleep(2.5)

        (await asyncio.to_thread(db.record_wheel_spin, message.from_user.id))

        settings = (await asyncio.to_thread(db.get_wheel_settings))
        won = random.randint(1, 100) <= settings["win_percent"]

        if won and settings["prizes"]:
            percent = random.choice(settings["prizes"])
            code, expires_at = (await asyncio.to_thread(db.generate_wheel_prize_code, message.from_user.id, percent))
            await message.answer(
                f"🎉 تبریک! برنده شدی!\n\n"
                f"🎟 کد تخفیف {percent}٪ شما:\n`{code}`\n\n"
                f"⏳ اعتبار: تا {settings['expiry_hours']} ساعت آینده\n"
                f"این کد یکبارمصرف است و در خرید بعدی‌ات قابل استفاده است.",
                parse_mode="Markdown",
            )
        else:
            await message.answer("😔 امروز شانس با تو نبود! فردا دوباره امتحان کن.")

    @router.callback_query(F.data == "start_topup")
    async def cb_start_topup(call: CallbackQuery, state: FSMContext):
        await state.set_state(WalletTopup.waiting_amount)
        await call.message.edit_text(
            "💰 چه مبلغی (به تومان) می‌خواهید به کیف پول خود شارژ کنید؟ فقط عدد ارسال کنید (مثال: 100000):",
            reply_markup=kb.cancel_kb(),
        )
        await call.answer()

    @router.message(WalletTopup.waiting_amount)
    async def process_topup_amount(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", "")
        if not text.isdigit() or int(text) < 1000:
            await message.answer("لطفاً یک عدد معتبر و حداقل 1000 تومان ارسال کنید.")
            return

        amount = int(text)
        await state.update_data(topup_amount=amount)
        await state.set_state(WalletTopup.waiting_receipt)

        card_number = (await asyncio.to_thread(db.get_setting, "card_number"))
        card_holder = (await asyncio.to_thread(db.get_setting, "card_holder"))

        text = (
            f"مبلغ {amount:,} تومان را به شماره کارت زیر واریز کرده و سپس عکس رسید را ارسال کنید:\n\n"
            f"💳 شماره کارت: `{card_number}`\n"
            f"👤 به نام: {card_holder}\n"
        )
        await message.answer(
            text, parse_mode="Markdown",
            reply_markup=kb.payment_choice_kb(
                crypto_payment.crypto_payment_available(db),
                abangateway_payment.abangateway_payment_available(db),
            ),
        )

    @router.callback_query(F.data == "pay_crypto", WalletTopup.waiting_receipt)
    async def cb_pay_crypto_topup(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer("درخواست معتبر یافت نشد.", show_alert=True)
            return
        await call.answer("در حال ساخت فاکتور...")
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
            "🪙 فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.\n"
            "⏳ اعتبار این فاکتور فقط ۸۰ دقیقه است.\n"
            "به‌محض تایید تراکنش روی بلاک‌چین، کیف پول شما به‌صورت خودکار شارژ می‌شود.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔗 رفتن به صفحه‌ی پرداخت", url=result["invoice_url"]),
            ]]),
        )

    @router.callback_query(F.data == "pay_abangateway", WalletTopup.waiting_receipt)
    async def cb_pay_abangateway_topup(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await call.answer("درخواست معتبر یافت نشد.", show_alert=True)
            return
        await call.answer("در حال ساخت فاکتور...")
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
            "💳 فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن.\n"
            "معمولاً به‌محض واریز، کیف پول خودکار شارژ می‌شود؛ اگر چند دقیقه طول کشید، "
            "دکمه‌ی «بررسی وضعیت پرداخت» را بزن.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 رفتن به صفحه‌ی پرداخت", url=result["payment_url"])],
                [InlineKeyboardButton(text="🔄 بررسی وضعیت پرداخت", callback_data=f"check_aban:{invoice_row['id']}")],
            ]),
        )

    @router.message(WalletTopup.waiting_receipt, F.photo | F.document)
    async def receive_topup_receipt(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        amount = data.get("topup_amount")
        if not amount:
            await message.answer("درخواست معتبر یافت نشد. لطفاً دوباره از منو شروع کنید.")
            await state.clear()
            return

        file_id, receipt_type = _receipt_payload(message)
        if not file_id:
            await message.answer("لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.")
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
        for admin_id in (await asyncio.to_thread(db.list_admins)):
            factory = lambda aid=admin_id: _send_receipt_to_admin(
                bot, aid, file_id, receipt_type, caption, kb.topup_review_kb(topup_id)
            )
            sent = await _send_admin_notification(bot, admin_id, factory, "شارژ کیف پول", topup_id)
            if sent:
                (await asyncio.to_thread(db.set_topup_admin_message, topup_id, admin_id, sent.message_id))

        await message.answer(
            "✅ درخواست شارژ کیف پول شما برای بررسی ارسال شد. پس از تایید ادمین، مبلغ به کیف پول شما اضافه می‌شود.",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        await state.clear()

    @router.message(WalletTopup.waiting_receipt)
    async def topup_receipt_wrong_type(message: Message):
        await message.answer("لطفاً عکس یا فایل رسید پرداخت را ارسال کنید.")

    # -----------------------------------------------------------------------
    # درخواست خودکار نمایندگی سطح ۲
    # -----------------------------------------------------------------------

    def _senior_admin_ids():
        return [a["telegram_id"] for a in db.list_admins_with_roles() if a["role"] in ("owner", "admin")]

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_reseller_request", "🏪 درخواست نمایندگی سطح ۲")))
    async def reseller_request_start(message: Message, state: FSMContext):
        if not is_main_bot:
            return
        if (await asyncio.to_thread(db.get_setting, "reseller_request_enabled", "1")) != "1":
            await message.answer("در حال حاضر امکان درخواست نمایندگی سطح ۲ غیرفعال است.")
            return
        if (await asyncio.to_thread(db.is_reseller, message.from_user.id)):
            await message.answer("شما همین الان هم نماینده هستید.")
            return
        if (await asyncio.to_thread(db.get_open_reseller_request, message.from_user.id)):
            await message.answer("شما همین الان یک درخواست نمایندگی باز دارید؛ منتظر بررسی آن بمانید.")
            return
        await state.set_state(ResellerRequestFlow.waiting_volume)
        await message.answer(
            "🏪 درخواست نمایندگی سطح ۲\n\n"
            "چند گیگ حجم برای شروع نیاز دارید؟ فقط عدد ارسال کنید (مثلاً 500):",
            reply_markup=kb.cancel_kb(),
        )

    @router.message(ResellerRequestFlow.waiting_volume)
    async def reseller_request_volume(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح و مثبت ارسال کنید.")
            return
        await state.update_data(resreq_volume=int(text))
        await state.set_state(ResellerRequestFlow.waiting_text)
        await message.answer(
            "اگه توضیحی دارید (چرا نمایندگی می‌خوای و قراره چطور بفروشی) ارسال کنید، "
            "در غیر این صورت «ندارم» را ارسال کنید:",
            reply_markup=kb.cancel_kb(),
        )

    @router.message(ResellerRequestFlow.waiting_text)
    async def reseller_request_text(message: Message, state: FSMContext, bot: Bot):
        request_text = (message.text or "").strip()
        if not request_text:
            await message.answer("لطفاً متن درخواست را ارسال کنید یا «ندارم» را بفرستید.")
            return
        if request_text in ("ندارم", "ندارم.", "-", "_"):
            request_text = "توضیحی ارائه نشده."
        data = await state.get_data()
        volume_gb = data.get("resreq_volume")
        await state.clear()

        if not volume_gb:
            # اگر به هر دلیلی (مثلاً ری‌استارت بات بین دو مرحله) داده‌ی حجم گم شده باشد،
            # به‌جای کرش‌کردن روی فرمت عدد، از کاربر می‌خواهیم دوباره از ابتدا شروع کند
            # تا هرگز بدون پاسخ نماند.
            await message.answer(
                "⚠️ مشکلی در ثبت درخواست پیش آمد (احتمالاً به‌دلیل گذشت زمان زیاد). "
                "لطفاً دوباره روی «درخواست نمایندگی سطح ۲» بزنید.",
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)
            return

        try:
            request_id = (await asyncio.to_thread(db.create_reseller_request, message.from_user.id, volume_gb, request_text))
            user_row = (await asyncio.to_thread(db.get_user, message.from_user.id))
            first_name = (user_row["first_name"] if user_row else "") or ""
            username = (user_row["username"] if user_row else "") or "---"
            caption = (
                f"🏪 درخواست نمایندگی سطح ۲ #{request_id}\n"
                f"👤 کاربر: {first_name} (@{username})\n"
                f"🆔 آیدی عددی: {message.from_user.id}\n"
                f"📦 حجم درخواستی: {volume_gb:,} گیگ\n\n"
                f"📝 متن درخواست:\n{request_text}"
            )
            for admin_id in _senior_admin_ids():
                try:
                    await bot.send_message(admin_id, caption, reply_markup=kb.reseller_request_review_kb(request_id))
                except Exception:
                    pass

            await message.answer(
                "✅ درخواست نمایندگی شما ثبت شد. بعد از بررسی ادمین، هزینه‌ی نمایندگی برایتان اعلام می‌شود.",
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)
        except Exception:
            logging.getLogger(__name__).exception("خطا در ثبت درخواست نمایندگی سطح ۲ کاربر %s", message.from_user.id)
            await message.answer(
                "⚠️ در ثبت درخواست خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.",
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)

    @router.callback_query(F.data.startswith("resreq_pay:"))
    async def reseller_request_pay(call: CallbackQuery):
        request_id = int(call.data.split(":")[1])
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        if not req or req["user_id"] != call.from_user.id or req["status"] != "awaiting_payment":
            await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
            return
        card_number = (await asyncio.to_thread(db.get_setting, "card_number"))
        card_holder = (await asyncio.to_thread(db.get_setting, "card_holder"))
        text = (
            f"مبلغ {req['price_toman']:,} تومان را به شماره کارت زیر واریز کرده و سپس عکس رسید را ارسال کنید:\n\n"
            f"💳 شماره کارت: `{card_number}`\n"
            f"👤 به نام: {card_holder}\n"
        )
        await call.message.answer(text, parse_mode="Markdown")
        await call.answer()

    @router.callback_query(F.data.startswith("resreq_cancel:"))
    async def reseller_request_cancel(call: CallbackQuery):
        request_id = int(call.data.split(":")[1])
        req = (await asyncio.to_thread(db.get_reseller_request, request_id))
        if not req or req["user_id"] != call.from_user.id:
            await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
            return
        if req["status"] not in ("awaiting_payment",):
            await call.answer("این درخواست دیگر قابل انصراف نیست.", show_alert=True)
            return
        (await asyncio.to_thread(db.set_reseller_request_status, request_id, "cancelled"))
        await call.message.edit_text((call.message.text or "") + "\n\n❌ انصراف داده شد.")
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
        if req and req["status"] == "awaiting_payment":
            file_id, receipt_type = _receipt_payload(message)
            if not file_id:
                return
            (await asyncio.to_thread(db.set_reseller_request_receipt, req["id"], file_id, receipt_type))
            caption = (
                f"💳 رسید پرداخت درخواست نمایندگی #{req['id']}\n"
                f"👤 کاربر: {message.from_user.id}\n"
                f"💰 مبلغ: {req['price_toman']:,} تومان"
            )
            for admin_id in _senior_admin_ids():
                try:
                    await _send_receipt_to_admin(
                        bot, admin_id, file_id, receipt_type, caption,
                        kb.reseller_request_payment_review_kb(req["id"])
                    )
                except Exception:
                    pass
            await message.answer("✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، مرحله‌ی بعدی اعلام می‌شود.")
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
                    "⚠️ در ثبت رسید شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
                )
                return
            log.warning(
                "رسید سفارش #%s کاربر %s با fallback (بدون FSM state) پردازش شد.",
                order["id"], message.from_user.id,
            )
            await message.answer(
                "✅ رسید شما برای بررسی ارسال شد. پس از تایید ادمین، کانفیگ برای شما ارسال خواهد شد.",
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
                    "⚠️ در ثبت رسید شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
                )
                return
            log.warning(
                "رسید شارژ کیف‌پول #%s کاربر %s با fallback (بدون FSM state) پردازش شد.",
                topup["id"], message.from_user.id,
            )
            await message.answer(
                "✅ درخواست شارژ کیف پول شما برای بررسی ارسال شد. پس از تایید ادمین، مبلغ به کیف پول شما اضافه می‌شود.",
                reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
            )
            await _send_inline_main_menu(message, message.from_user.id)
            return

        log.warning(
            "عکس/فایل بدون state و بدون هیچ سفارش/درخواست pending‌ای از کاربر %s دریافت شد.",
            message.from_user.id,
        )
        await message.answer(
            "❌ رسید شما ثبت نشد.\n"
            "دلیل: هیچ سفارش یا درخواست شارژ در انتظار رسیدی برای شما پیدا نشد "
            "(احتمالاً ارتباط قطع شده بود یا قبلاً بررسی شده است).\n\n"
            "لطفاً دوباره از منوی اصلی همان مسیر خرید یا شارژ کیف پول را طی کنید و رسید را مجدداً ارسال کنید.",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)

    @router.message(ResellerRequestFlow.waiting_bot_token)
    async def reseller_request_bot_token(message: Message, state: FSMContext):
        token = (message.text or "").strip()
        temp_bot = Bot(token=token)
        try:
            me = await temp_bot.get_me()
        except Exception:
            await message.answer("❌ این توکن معتبر نیست. توکن بات را دوباره از @BotFather بگیرید و ارسال کنید:")
            await temp_bot.session.close()
            return
        await temp_bot.session.close()
        if (await asyncio.to_thread(db.get_reseller_bot_by_token, token)):
            await message.answer("⛔️ این توکن قبلاً برای یک بات نمایندگی دیگر ثبت شده است.")
            return
        await state.update_data(resreq_bot_token=token, resreq_bot_username=me.username)
        await state.set_state(ResellerRequestFlow.waiting_owner_id)
        await message.answer(
            f"✅ توکن معتبر است: @{me.username}\n\n"
            f"حالا آیدی عددی تلگرام خودتان (که مالک این بات خواهد بود) را ارسال کنید:"
        )

    @router.message(ResellerRequestFlow.waiting_owner_id)
    async def reseller_request_owner_id(message: Message, state: FSMContext, bot: Bot):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("لطفاً فقط آیدی عددی ارسال کنید.")
            return
        owner_id = int(raw)
        data = await state.get_data()
        request_id = data.get("resreq_request_id")
        token = data.get("resreq_bot_token")
        username = data.get("resreq_bot_username")
        req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
        if not req or req["status"] != "awaiting_bot_info":
            await state.clear()
            await message.answer("این درخواست دیگر معتبر نیست.")
            return

        os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
        db_path = os.path.join(RESELLER_DBS_DIR, f"{username}.db")
        reseller_bot_id = (await asyncio.to_thread(db.register_reseller_bot, token, username, owner_id, req["request_text"] or "", db_path, reseller_level=2))

        started = False
        if bot_manager:
            started = await bot_manager.start_bot(token, db_path, owner_id, is_main_bot=False)

        reseller_db = Database(db_path)
        (await asyncio.to_thread(reseller_db.init_db, owner_id=owner_id))
        (await asyncio.to_thread(reseller_db.set_setting, "miniapp_tenant_id", str(reseller_bot_id)))
        (await asyncio.to_thread(reseller_db.set_setting, "reseller_level", "2"))
        (await asyncio.to_thread(reseller_db.set_setting, "custom_config_enabled", "0"))

        (await asyncio.to_thread(db.set_reseller_status, owner_id, True))
        (await asyncio.to_thread(db.adjust_reseller_credit, 
            owner_id, req["volume_gb"], admin_id=req["reviewed_by"],
            reason=f"تخصیص خودکار پس از تایید درخواست نمایندگی #{req['id']}",
        ))
        if req["panel_server_id"]:
            (await asyncio.to_thread(db.set_reseller_panel, owner_id, req["panel_server_id"]))
        (await asyncio.to_thread(db.complete_reseller_request, req["id"], owner_id))

        await state.clear()
        status_text = "✅ بات نمایندگی راه‌اندازی و همین الان روشن شد." if started else \
            "⚠️ بات ثبت شد ولی راه‌اندازی زنده انجام نشد؛ با ری‌استارت سرویس اصلی خودکار روشن می‌شود."
        await message.answer(
            f"{status_text}\n\n"
            f"🤖 بات: @{username}\n"
            f"📦 اعتبار حجمی تخصیص‌یافته: {req['volume_gb']:,} گیگ\n\n"
            f"برای شروع، با /start به بات خودتان (@{username}) وارد شوید.",
            reply_markup=kb.menu_for_user(db, message.from_user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, message.from_user.id)
        try:
            for admin_id in _senior_admin_ids():
                await bot.send_message(
                    admin_id,
                    f"✅ نمایندگی سطح ۲ #{req['id']} تکمیل شد.\n🤖 بات: @{username}\n👤 مالک: {owner_id}",
                )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # ارتباط با پشتیبانی
    # -----------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_contact")))
    async def contact_start(message: Message, state: FSMContext):
        await state.set_state(ContactFlow.waiting_message)
        await message.answer((await asyncio.to_thread(db.get_setting, "contact_text")), reply_markup=kb.cancel_kb())

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
            "پیام شما برای پشتیبانی ارسال شد. به زودی پاسخ داده می‌شود.",
            reply_markup=kb.menu_for_user(db, user.id, is_main_bot),
        )
        await _send_inline_main_menu(message, user.id)
        await state.clear()

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

        if key == "btn_buy":
            await show_categories(fake_message, state)
        elif key == "btn_test":
            await get_test_config(fake_message)
        elif key == "btn_my_orders":
            await my_orders(fake_message)
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
        elif key == "btn_reseller_request":
            await reseller_request_start(fake_message, state)
        # کلید "btn_admin_panel" در handlers_admin.py مدیریت می‌شود چون هندلر
        # اصلی آن (open_admin_panel) در همان روتر تعریف شده است.

    return router
