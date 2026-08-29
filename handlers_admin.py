# -*- coding: utf-8 -*-
"""
هندلرهای پنل مدیریت

این فایل هم مثل handlers_user.py یک تابع کارخانه‌ای دارد: create_admin_router(db, ...).
هر بات (اصلی یا نمایندگی) پنل مدیریت کامل و مستقل خودش را از همین یک کد می‌سازد.
"""

import os
import re
import asyncio
from datetime import date, timedelta
import tempfile
import logging

from aiogram import Router, F, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

import keyboards as kb
from database import Database, MENU_BUTTON_META
from config import RESELLER_DBS_DIR, resolve_db_path, ADMIN_PANEL_URL
from config_delivery import deliver_config_to_user
from jalali import to_jalali_str
from stock_alerts import check_and_notify_low_stock
from backup import create_backup, restore_backup, is_valid_sqlite_db
import crypto_payment
import abangateway_payment
from panel_providers import (
    get_provider, PanelError, PanelUsernameTakenError, PANEL_TYPE_LABELS,
    SUB_BASE_URL_PANEL_TYPES, INBOUND_SELECT_PANEL_TYPES,
)
from reseller_auto_provision import provision_auto_config, ProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from states import (
    AdminAddCategory,
    AdminAddProduct,
    AdminAddConfigs,
    AdminAddTestConfigs,
    AdminTestConfigSettings,
    AdminForceJoin,
    AdminEditButton,
    AdminSetCard,
    AdminSetPlisio,
    AdminSetAbanGateway,
    AdminBroadcast,
    AdminDeepLinkTools,
    AdminChannelButton,
    AdminAddAdmin,
    AdminRemoveAdmin,
    AdminChangeRole,
    AdminEditWelcome,
    AdminReplyFlow,
    AdminCreateDiscount,
    AdminReferralPercent,
    AdminReferralCommissionMax,
    AdminReferralFreeConfigThreshold,
    AdminReferralInviteBonusAmount,
    AdminReferralInviteBonusMax,
    AdminAddResellerBot,
    AdminSetPanelDomain,
    AdminResellerCredit,
    AdminWheelSettings,
    AdminRenewalSettings,
    AdminVolumeReminderSettings,
    AdminStockAlertSettings,
    AdminRestoreBackup,
    AdminAddPanelServer,
    AdminSetPanelTemplate,
    AdminSetPanelSubUrl,
    AdminAddPricingTier,
    AdminCustomConfigSettings,
    AdminResetTestConfig,
    ResellerRequestFlow,
    AdminResellerRequestFlow,
    AdminTempMessage,
)
from temp_messages import send_temp_message, schedule_message_autodelete

logger = logging.getLogger(__name__)


async def _send_via_reseller_bot(bot_token: str, chat_id: int, text: str) -> bool:
    """پیام را از طریق خودِ بات نماینده می‌فرستد، نه بات اصلی.
    چون نماینده معمولاً هیچ‌وقت به بات اصلی /start نزده، بات اصلی اصلاً اجازه‌ی
    شروع مکالمه با او را ندارد (محدودیت خودِ تلگرام)؛ فقط بات خودش می‌تواند
    برایش پیام بفرستد، چون او با همان بات کار می‌کند."""
    temp_bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await temp_bot.send_message(chat_id, text)
        return True
    except Exception:
        logger.warning("ارسال پیام از طریق بات نماینده به %s ناموفق بود.", chat_id, exc_info=True)
        return False
    finally:
        await temp_bot.session.close()


def _get_admin_panel_url(db) -> str:
    """آدرس دامنه‌ی پنل مدیریت وب مستقل - اول از تنظیمات داخل دیتابیس (که خودِ
    ادمین از داخل بات وارد کرده)، اگر نبود از ADMIN_PANEL_URL توی .env (برای
    سازگاری با نصب‌های قدیمی‌تر)."""
    saved = db.get_setting("admin_panel_url", "")
    return (saved or ADMIN_PANEL_URL or "").strip().rstrip("/")


async def _deliver_webpanel_link(db, answerable, admin_id: int, bot_id: int) -> None:
    """توکن راه‌اندازی از قبل روی ردیف نماینده ذخیره است (enable/regenerate قبلاً
    صداش زده)؛ این تابع فقط لینک نهایی رو می‌سازه، به ادمین نشون می‌ده و از
    طریق بات خودِ نماینده براش می‌فرسته. answerable هر چیزی با متد async
    answer(text, reply_markup=None) است (call.message یا یک Message)."""
    reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
    if not reseller_bot or not reseller_bot["web_panel_setup_token"]:
        await answerable.answer("این نماینده یا توکن راه‌اندازی‌اش دیگر پیدا نشد؛ دوباره از منوی نمایندگی امتحان کن.")
        return
    panel_url = _get_admin_panel_url(db)
    if not panel_url:
        await answerable.answer("هنوز آدرس پنل مدیریت تنظیم نشده.")
        return

    b_value = reseller_bot["link_slug"] or str(bot_id)
    link = f"{panel_url}/setup?b={b_value}&t={reseller_bot['web_panel_setup_token']}"
    login_link = f"{panel_url}/?b={b_value}"

    await answerable.answer(
        "🌐 لینک راه‌اندازی پنل وب این نماینده:\n\n"
        f"{link}\n\n"
        "این لینک یک‌بارمصرف است؛ نماینده با باز کردنش یک یوزرنیم/پسورد دلخواه برای پنل وب "
        "خودش تنظیم می‌کند (مستقل از پنل بات اصلی، فقط روی دیتابیس خودش).\n\n"
        "این لینک همین الان از طریق بات خودِ نماینده براش ارسال شد.",
        reply_markup=kb.resbot_webpanel_kb(bot_id),
    )
    (await asyncio.to_thread(db.log_admin_action, 
        admin_id, "reseller_webpanel_enable", f"نماینده #{bot_id} (@{reseller_bot['bot_username'] or ''})",
    ))

    sent = await _send_via_reseller_bot(
        reseller_bot["bot_token"],
        reseller_bot["owner_telegram_id"],
        "🌐 پنل مدیریت وب برای نمایندگی شما آماده است!\n\n"
        "با باز کردن لینک زیر، یک‌بار یوزرنیم و پسورد دلخواه برای پنل وب خودتان تنظیم کنید "
        "(این لینک فقط یک‌بار کار می‌کند):\n\n"
        f"{link}\n\n"
        "🔗 لینک ثابت ورود پنل وب (برای دفعات بعد، بعد از تنظیم یوزرنیم/پسورد این را بوکمارک کنید):\n"
        f"{login_link}",
    )
    if not sent:
        await answerable.answer(
            "⚠️ ارسال خودکار لینک به نماینده (از طریق بات خودش) ناموفق بود؛ لینک بالا را خودت برایش بفرست."
        )


def create_admin_router(db, is_main_bot: bool = True, bot_manager=None) -> Router:
    router = Router()

    def admin_only(user_id: int) -> bool:
        return db.is_admin(user_id)

    def full_admin_only(user_id: int) -> bool:
        """دسترسی کامل: مالک، مدیر یا ادمین میانی. ادمین با نقش «پشتیبان» اجازه‌ی این اقدامات
        (تنظیمات، مالی، مدیریت محصولات/موجودی) را ندارد."""
        return db.is_full_admin(user_id)

    def panel_server_readiness_text(server) -> str:
        if server["panel_type"] in SUB_BASE_URL_PANEL_TYPES:
            if server["panel_type"] in INBOUND_SELECT_PANEL_TYPES:
                if server["xui_inbound_id"] and server["xui_sub_base_url"]:
                    return f"inbound #{server['xui_inbound_id']} تنظیم شده"
                return "⚠️ inbound/آدرس Subscription هنوز تنظیم نشده"
            if server["xui_sub_base_url"]:
                return "✅ آدرس Subscription تنظیم شده"
            return "⚠️ آدرس Subscription هنوز تنظیم نشده"
        return f"قالب از کاربر «{server['template_username']}»" if server["template_username"] else "⚠️ قالب هنوز تنظیم نشده"

    def senior_admin_only(user_id: int) -> bool:
        """فقط مالک یا مدیر کامل؛ ادمین میانی و پشتیبان اجازه‌ی این بخش‌های حساس
        (آمار فروش، تنظیمات کمپین‌ها/تخفیف، نمایندگی‌ها، برندینگ، مدیریت محصولات/
        دسته‌بندی‌ها/کانفیگ‌بانک) را ندارند."""
        return db.is_senior_admin(user_id)

    async def _notify_user_inline_menu(bot: Bot, user_tg_id: int):
        """بعد از این‌که مدیر یک اقدام را روی سفارش/شارژ/درخواست کاربر انجام می‌دهد
        (تایید، رد و ...) و پیامی برای کاربر ارسال می‌شود، اگر منوی شیشه‌ای بالا از
        تنظیمات فعال باشد، دوباره برایش ارسال می‌شود؛ وگرنه بعد از این پیام‌های جدید
        از دسترس کاربر خارج می‌ماند (چون به پیام قبلی‌اش چسبیده بود، نه به چت)."""
        try:
            inline_kb = (await asyncio.to_thread(kb.inline_menu_for_user, db, user_tg_id, is_main_bot))
            if inline_kb is not None:
                await bot.send_message(user_tg_id, "📋 منو:", reply_markup=inline_kb)
        except Exception:
            pass

    async def _notify_admin_panel_menu(bot: Bot, admin_tg_id: int):
        """بعد از تایید/رد یک رسید یا درخواست، پنل مدیریت (منوی شیشه‌ای) دوباره
        برای همان مدیر ارسال می‌شود؛ چون آن منو به پیام رسید چسبیده بود، نه به چت."""
        try:
            await bot.send_message(admin_tg_id, "🔧 پنل مدیریت:", reply_markup=kb.admin_panel_kb(db, is_main_bot))
        except Exception:
            pass

    async def _send_receipt(bot: Bot, chat_id: int, file_id: str, receipt_type: str, caption: str, reply_markup=None):
        """ارسال رسید ذخیره‌شده؛ رسیدهای قدیمی photo فرض می‌شوند."""
        if (receipt_type or "photo") == "document":
            return await bot.send_document(chat_id, file_id, caption=caption, reply_markup=reply_markup)
        return await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=reply_markup)

    def owner_only(user_id: int) -> bool:
        """فقط مالک اصلی بات (تعیین‌شده در env)؛ برای مدیریت خود ادمین‌ها."""
        return db.is_owner(user_id)

    async def deny_support(call: CallbackQuery):
        await call.answer("⛔️ این بخش فقط برای مدیران کامل در دسترس است.", show_alert=True)

    async def deny_mid(call: CallbackQuery):
        await call.answer("⛔️ این بخش فقط برای مالک و مدیر کامل در دسترس است.", show_alert=True)

    async def safe_edit(call: CallbackQuery, text: str, reply_markup=None, parse_mode=None) -> bool:
        """ویرایش امن پیام؛ خطای message is not modified نباید کل callback را خراب کند."""
        try:
            kwargs = {"reply_markup": reply_markup}
            if parse_mode is not None:
                kwargs["parse_mode"] = parse_mode
            await call.message.edit_text(text, **kwargs)
            return True
        except TelegramBadRequest as exc:
            error = str(exc).lower()
            if any(phrase in error for phrase in (
                "message is not modified",
                "message can't be edited",
                "message to edit not found",
            )):
                return False
            raise

    async def replace_admin_view(call: CallbackQuery, text: str, reply_markup=None, parse_mode=None) -> bool:
        """تغییر منوی ادمین روی همان پیام؛ بدون حذف/ارسال مجدد پیام."""
        if call.message is None:
            return False

        kwargs = {"reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode

        try:
            await call.message.edit_text(text, **kwargs)
            return True
        except TelegramBadRequest as exc:
            error = str(exc).lower()
            if any(phrase in error for phrase in (
                "message is not modified",
                "message can't be edited",
                "message to edit not found",
            )):
                return False
            raise

    def callback_id(data: str, prefix: str):
        """استخراج امن ID از callback_data و بررسی پیشوند."""
        try:
            parts = (data or "").split(":", 1)
            if len(parts) != 2 or parts[0] != prefix:
                return None
            value = parts[1]
            if not value.isdigit():
                return None
            return int(value)
        except (IndexError, AttributeError, ValueError):
            return None

    def _find_orphan_reseller_db_files():
        """فایل‌های .db داخل پوشه‌ی reseller_dbs که هیچ رکورد نماینده‌ای (حتی حذف‌شده)
        در جدول reseller_bots به مسیرشان اشاره نمی‌کند؛ باقیمانده‌ی نماینده‌های قدیمی."""
        if not os.path.isdir(RESELLER_DBS_DIR):
            return []
        referenced = set()
        for r in db.list_reseller_bots():
            try:
                referenced.add(os.path.normcase(os.path.abspath(resolve_db_path(r["db_path"]))))
            except Exception:
                continue
        orphans = []
        try:
            disk_files = sorted(os.listdir(RESELLER_DBS_DIR))
        except OSError:
            return []
        for fname in disk_files:
            if not fname.endswith(".db"):
                continue
            full_path = os.path.normcase(os.path.abspath(os.path.join(RESELLER_DBS_DIR, fname)))
            if full_path not in referenced:
                orphans.append(fname)
        return orphans

    # -------------------------------------------------------------------
    # ورود به پنل
    # -------------------------------------------------------------------

    @router.message(F.text.func(lambda t: t == db.get_setting("btn_admin_panel")))
    async def open_admin_panel(message: Message, state: FSMContext):
        if not admin_only(message.from_user.id):
            return
        await state.clear()
        await message.answer("🔧 پنل مدیریت:", reply_markup=kb.admin_panel_kb(db, is_main_bot))

    @router.callback_query(F.data == "adm_back_panel")
    async def cb_back_panel(call: CallbackQuery, state: FSMContext):
        if not admin_only(call.from_user.id):
            return await call.answer()
        await state.clear()
        await replace_admin_view(call, "🔧 پنل مدیریت:", reply_markup=kb.admin_panel_kb(db, is_main_bot))
        await call.answer()

    @router.callback_query(F.data == "noop")
    async def cb_noop(call: CallbackQuery):
        await call.answer()

    @router.callback_query(F.data.startswith("adm_cat:"))
    async def cb_admin_category(call: CallbackQuery, state: FSMContext):
        if not admin_only(call.from_user.id):
            return await call.answer()
        await state.clear()
        cat_key = call.data.split(":", 1)[1]
        title = kb.admin_category_label(cat_key)
        await replace_admin_view(call, f"{title}:", reply_markup=kb.admin_category_kb(db, is_main_bot, cat_key))
        await call.answer()

    # -------------------------------------------------------------------
    # مدیریت دسته‌بندی‌ها
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_categories")
    async def cb_admin_categories(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            categories = (await asyncio.to_thread(db.get_categories, active_only=False))
            await replace_admin_view(call, "📂 مدیریت دسته‌بندی‌ها:", kb.admin_categories_kb(categories))
            await call.answer()
        except Exception:
            await call.answer("⚠️ بارگذاری دسته‌بندی‌ها ناموفق بود. دوباره تلاش کنید.", show_alert=True)

    @router.callback_query(F.data.startswith("adm_cat_toggle:"))
    async def cb_admin_cat_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cat_id = callback_id(call.data, "adm_cat_toggle")
        if cat_id is None:
            return await call.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
        try:
            if (await asyncio.to_thread(db.get_category, cat_id)) is None:
                return await call.answer("⚠️ این دسته‌بندی دیگر وجود ندارد.", show_alert=True)
            (await asyncio.to_thread(db.toggle_category, cat_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "category_toggle", f"دسته‌بندی #{cat_id}"))
            categories = (await asyncio.to_thread(db.get_categories, active_only=False))
            await safe_edit(call, "📂 مدیریت دسته‌بندی‌ها:", kb.admin_categories_kb(categories))
            await call.answer("وضعیت تغییر کرد.")
        except Exception:
            await call.answer("⚠️ تغییر وضعیت دسته‌بندی ناموفق بود. دوباره تلاش کنید.", show_alert=True)

    @router.callback_query(F.data.startswith("adm_cat_del:"))
    async def cb_admin_cat_del(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cat_id = callback_id(call.data, "adm_cat_del")
        if cat_id is None:
            return await call.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
        try:
            if (await asyncio.to_thread(db.get_category, cat_id)) is None:
                return await call.answer("⚠️ این دسته‌بندی قبلاً حذف شده است.", show_alert=True)
            (await asyncio.to_thread(db.delete_category, cat_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "category_delete", f"دسته‌بندی #{cat_id}"))
            categories = (await asyncio.to_thread(db.get_categories, active_only=False))
            await safe_edit(call, "📂 مدیریت دسته‌بندی‌ها:", kb.admin_categories_kb(categories))
            await call.answer("دسته‌بندی حذف شد.")
        except Exception:
            await call.answer("⚠️ حذف دسته‌بندی ناموفق بود. دوباره تلاش کنید.", show_alert=True)

    @router.callback_query(F.data == "adm_cat_add")
    async def cb_admin_cat_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminAddCategory.waiting_name)
        await safe_edit(call, "نام دسته‌بندی جدید را ارسال کنید:", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminAddCategory.waiting_name)
    async def process_add_category(message: Message, state: FSMContext):
        if not admin_only(message.from_user.id):
            return
        name = (message.text or "").strip()
        if not name:
            await message.answer("لطفاً نام دسته‌بندی را وارد کنید.")
            return
        if len(name) > 100:
            await message.answer("نام دسته‌بندی نباید بیشتر از ۱۰۰ کاراکتر باشد.")
            return
        try:
            (await asyncio.to_thread(db.add_category, name))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "category_add", f"دسته‌بندی «{name}»"))
            await state.clear()
            await message.answer("✅ دسته‌بندی اضافه شد.", reply_markup=kb.admin_category_kb(db, is_main_bot, "products"))
        except Exception:
            await message.answer("⚠️ افزودن دسته‌بندی ناموفق بود. دوباره تلاش کنید.")

    # -------------------------------------------------------------------
    # مدیریت محصولات
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_products")
    async def cb_admin_products(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        categories = (await asyncio.to_thread(db.get_categories, active_only=False))
        await replace_admin_view(call, 
            "📦 مدیریت محصولات - ابتدا دسته‌بندی را انتخاب کنید:",
            reply_markup=kb.admin_products_categories_kb(categories),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_prod_cat:"))
    async def cb_admin_prod_cat(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cat_id = callback_id(call.data, "adm_prod_cat")
        if cat_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        products = (await asyncio.to_thread(db.get_products, cat_id, active_only=False))
        if not products:
            await call.answer("محصولی در این دسته وجود ندارد.", show_alert=True)
            return
        await safe_edit(call, "لیست محصولات این دسته‌بندی:", reply_markup=kb.admin_products_list_kb(db, products))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_prod_toggle:"))
    async def cb_admin_prod_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_toggle")
        if product_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        (await asyncio.to_thread(db.toggle_product, product_id))
        product = (await asyncio.to_thread(db.get_product, product_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "product_toggle", f"محصول «{product['name'] if product else product_id}»"))
        products = (await asyncio.to_thread(db.get_products, product["category_id"], active_only=False))
        await safe_edit(call, "لیست محصولات این دسته‌بندی:", reply_markup=kb.admin_products_list_kb(db, products))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data.startswith("adm_prod_del:"))
    async def cb_admin_prod_del(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_del")
        if product_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        product = (await asyncio.to_thread(db.get_product, product_id))
        cat_id = product["category_id"] if product else None
        (await asyncio.to_thread(db.delete_product, product_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "product_delete", f"محصول «{product['name'] if product else product_id}»"))
        if cat_id:
            products = (await asyncio.to_thread(db.get_products, cat_id, active_only=False))
            await safe_edit(call, "لیست محصولات این دسته‌بندی:", reply_markup=kb.admin_products_list_kb(db, products))
        await call.answer("محصول حذف شد.")

    @router.callback_query(F.data == "adm_prod_add")
    async def cb_admin_prod_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        categories = (await asyncio.to_thread(db.get_categories, active_only=True))
        if not categories:
            await call.answer("ابتدا باید حداقل یک دسته‌بندی فعال بسازید.", show_alert=True)
            return
        await state.set_state(AdminAddProduct.waiting_category)
        await safe_edit(call, 
            "محصول جدید در کدام دسته‌بندی اضافه شود؟",
            reply_markup=kb.admin_pick_category_kb(categories, "adm_newprod_cat"),
        )
        await call.answer()

    @router.callback_query(AdminAddProduct.waiting_category, F.data.startswith("adm_newprod_cat:"))
    async def cb_pick_category_for_new_product(call: CallbackQuery, state: FSMContext):
        cat_id = callback_id(call.data, "adm_newprod_cat")
        if cat_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        await state.update_data(category_id=cat_id)
        await state.set_state(AdminAddProduct.waiting_name)
        await safe_edit(call, "نام محصول را ارسال کنید:", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminAddProduct.waiting_name)
    async def process_product_name(message: Message, state: FSMContext):
        await state.update_data(name=message.text.strip())
        await state.set_state(AdminAddProduct.waiting_price)
        await message.answer("قیمت محصول را به تومان و فقط عدد وارد کنید (مثال: 150000):")

    @router.message(AdminAddProduct.waiting_price)
    async def process_product_price(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", "")
        if not text.isdigit():
            await message.answer("لطفاً فقط عدد وارد کنید. مثال: 150000")
            return
        await state.update_data(price=int(text))
        await state.set_state(AdminAddProduct.waiting_desc)
        await message.answer("توضیحات محصول را وارد کنید (یا برای رد شدن بنویسید: -)")

    @router.message(AdminAddProduct.waiting_desc)
    async def process_product_desc(message: Message, state: FSMContext):
        desc = "" if message.text.strip() == "-" else message.text.strip()
        await state.update_data(description=desc)
        await state.set_state(AdminAddProduct.waiting_duration)
        await message.answer(
            "مدت اعتبار این سرویس چند روز است؟ فقط عدد وارد کنید (مثال: 30).\n"
            "این عدد برای محاسبه‌ی تاریخ یادآوری اتمام سرویس به کاربر استفاده می‌شود."
        )

    @router.message(AdminAddProduct.waiting_duration)
    async def process_product_duration(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً فقط عدد صحیح و بزرگ‌تر از صفر وارد کنید. مثال: 30")
            return
        await state.update_data(duration_days=int(text))

        if (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            await state.set_state(AdminAddProduct.waiting_provision_choice)
            await message.answer(
                "منبع کانفیگ این محصول چیست؟\n\n"
                "📦 بانک کانفیگ: از لینک‌های از پیش آماده‌شده تحویل داده می‌شود.\n"
                "🔌 اتصال مستقیم به پنل: هر بار خرید، همان لحظه یک کاربر واقعی روی پنل انتخابی ساخته می‌شود "
                "(نیازی به پر کردن بانک کانفیگ نیست).",
                reply_markup=kb.admin_new_product_source_kb(),
            )
            return

        # نمایندگی سطح ۲: به پنل/بانک لینک دسترسی ندارد، همیشه خودکار از اعتبار حجمی است - سوالی پرسیده نمی‌شود
        await state.set_state(AdminAddProduct.waiting_auto_provision_volume)
        await message.answer("این محصول چند گیگابایت باشد؟ فقط عدد وارد کنید (مثال: 30):")

    @router.callback_query(AdminAddProduct.waiting_provision_choice, F.data.startswith("adm_newprod_src:"))
    async def cb_pick_product_source(call: CallbackQuery, state: FSMContext):
        source = call.data.split(":", 1)[1]
        if source == "bank":
            data = await state.get_data()
            (await asyncio.to_thread(db.add_product, data["category_id"], data["name"], data["price"], data["description"], data["duration_days"]))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "product_add", f"محصول «{data['name']}» | قیمت: {data['price']:,}"))
            await state.clear()
            await safe_edit(call, "✅ محصول با موفقیت اضافه شد.\nحالا از «بانک کانفیگ» می‌تونی لینک‌ها رو براش اضافه کنی.")
            await call.answer()
            return

        # اتصال مستقیم به پنل
        servers = (await asyncio.to_thread(db.get_panel_servers, active_only=True))
        if not servers:
            await call.answer("ابتدا باید حداقل یک پنل فعال در بخش «مدیریت پنل‌ها» تعریف کنید.", show_alert=True)
            return
        await state.set_state(AdminAddProduct.waiting_provision_server)
        await safe_edit(call, "این محصول به کدام پنل وصل شود؟", reply_markup=kb.admin_pick_provision_server_kb(servers))
        await call.answer()

    @router.callback_query(AdminAddProduct.waiting_provision_server, F.data.startswith("adm_newprod_srv:"))
    async def cb_pick_provision_server(call: CallbackQuery, state: FSMContext):
        server_id = callback_id(call.data, "adm_newprod_srv")
        if server_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        await state.update_data(provision_server_id=server_id)
        await state.set_state(AdminAddProduct.waiting_auto_provision_volume)
        await safe_edit(call, "این محصول چند گیگابایت باشد؟ فقط عدد وارد کنید (مثال: 30):", reply_markup=None)
        await call.answer()

    @router.message(AdminAddProduct.waiting_auto_provision_volume)
    async def process_product_auto_provision_volume(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً فقط عدد صحیح و بزرگ‌تر از صفر وارد کنید. مثال: 30")
            return
        data = await state.get_data()
        provision_server_id = data.get("provision_server_id")
        (await asyncio.to_thread(db.add_product, 
            data["category_id"], data["name"], data["price"], data["description"], data["duration_days"],
            is_auto_provision=True, auto_provision_volume_gb=int(text),
            provision_server_id=provision_server_id,
        ))
        (await asyncio.to_thread(db.log_admin_action, 
            message.from_user.id, "product_add",
            f"محصول «{data['name']}» (خودکار"
            + (" - اتصال مستقیم به پنل" if provision_server_id else "")
            + f"، {text} گیگ) | قیمت: {data['price']:,}",
        ))
        await state.clear()
        if provision_server_id:
            await message.answer(
                "✅ محصول با موفقیت اضافه شد.\n"
                "هر بار خرید این محصول، خودکار روی پنل انتخابی یک کاربر واقعی ساخته می‌شود؛ "
                "نیازی به اضافه کردن لینک به بانک کانفیگ نیست.",
                reply_markup=kb.admin_category_kb(db, is_main_bot, "products"),
            )
        else:
            await message.answer(
                "✅ محصول با موفقیت اضافه شد.\n"
                "⚠️ برای این‌که این محصول واقعاً کار کند، باید توسط ادمین بات اصلی برایت «نماینده» فعال شده و "
                "اعتبار حجمی و پنل نمایندگی برایت تنظیم شده باشد.",
                reply_markup=kb.admin_category_kb(db, is_main_bot, "products"),
            )

    # -------------------------------------------------------------------
    # افزودن کانفیگ (بانک لینک) به محصول
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_add_configs")
    async def cb_admin_add_configs(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            await call.answer("این بخش برای نمایندگی سطح ۲ فعال نیست.", show_alert=True)
            return
        products = (await asyncio.to_thread(db.get_all_products))
        if not products:
            await call.answer("ابتدا باید یک محصول بسازید.", show_alert=True)
            return
        await state.set_state(AdminAddConfigs.waiting_product)
        await replace_admin_view(call, 
            "افزودن کانفیگ به کدام محصول؟", reply_markup=kb.admin_pick_product_kb(products, "adm_addcfg_prod")
        )
        await call.answer()

    @router.callback_query(AdminAddConfigs.waiting_product, F.data.startswith("adm_addcfg_prod:"))
    async def cb_pick_product_for_configs(call: CallbackQuery, state: FSMContext):
        product_id = callback_id(call.data, "adm_addcfg_prod")
        if product_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        await state.update_data(product_id=product_id)
        await state.set_state(AdminAddConfigs.waiting_links)
        await safe_edit(call, 
            "لینک‌های کانفیگ را ارسال کنید (هر لینک در یک خط جداگانه). می‌توانید چند لینک را با هم در یک پیام بفرستید:",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminAddConfigs.waiting_links)
    async def process_add_configs(message: Message, state: FSMContext):
        data = await state.get_data()
        product_id = data["product_id"]
        links = [line for line in (message.text or "").splitlines() if line.strip()]
        added_count, duplicate_count = (await asyncio.to_thread(db.add_configs, product_id, links))
        await state.clear()
        stock = (await asyncio.to_thread(db.count_available_configs, product_id))
        text = f"✅ {added_count} لینک با موفقیت اضافه شد."
        if duplicate_count:
            text += f"\n⚠️ تعداد {duplicate_count} کانفیگ تکراری بود و اضافه نشد."
        if not added_count and not duplicate_count:
            text = "⚠️ هیچ لینک معتبری دریافت نشد."
        text += f"\n📊 موجودی فعلی این محصول: {stock} عدد"
        await message.answer(text, reply_markup=kb.admin_category_kb(db, is_main_bot, "products"))

    # -------------------------------------------------------------------
    # دریافت یک کانفیگ رندوم آزاد (خارج از فرآیند سفارش، برای فروش دستی)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_random_cfg")
    async def cb_admin_random_cfg(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        products = (await asyncio.to_thread(db.get_all_products))
        if not products:
            await call.answer("ابتدا باید یک محصول بسازید.", show_alert=True)
            return
        await replace_admin_view(call, 
            "دریافت یک کانفیگ رندوم آزاد از کدام محصول؟",
            reply_markup=kb.admin_pick_product_kb(products, "adm_randomcfg_prod"),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_randomcfg_prod:"))
    async def cb_admin_random_cfg_pick(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_randomcfg_prod")
        if product_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        product = (await asyncio.to_thread(db.get_product, product_id))
        if product and product["provision_server_id"]:
            try:
                built = await provision_direct(db, product, quantity=1, user_id=call.from_user.id)
            except DirectProvisionError as e:
                await call.answer(f"⛔️ {e}", show_alert=True)
                return
            item = built[0]
            text = (
                f"🎲 یک کانفیگ از پنل متصل به «{product['name']}» ساخته شد:\n\n"
                f"`{item['subscription_url']}`\n\n"
                f"📦 حجم: {item['volume_gb']} گیگ | ⏳ مدت: {item['duration_days']} روز"
            )
            await safe_edit(call, text, parse_mode="Markdown", reply_markup=kb.admin_back_kb())
            await call.answer("کانفیگ دریافت شد ✅")
            return

        result = (await asyncio.to_thread(db.admin_take_random_config, product_id, call.from_user.id))
        if not result:
            await call.answer("کانفیگ آزادی برای این محصول موجود نیست.", show_alert=True)
            return
        expires_display = to_jalali_str(result.get("expires_at"))
        text = (
            f"🎲 یک کانفیگ رندوم از انبار «{product['name'] if product else 'محصول'}» برداشته و از انبار کم شد:\n\n"
            f"`{result['link']}`\n\n"
            f"⏳ تاریخ انقضا: {expires_display}"
        )
        await safe_edit(call, text, parse_mode="Markdown", reply_markup=kb.admin_back_kb())
        await call.answer("کانفیگ دریافت شد ✅")

    # -------------------------------------------------------------------
    # مدیریت کانفیگ تست
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_test_menu")
    async def cb_admin_test_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "🧪 مدیریت کانفیگ تست:", reply_markup=kb.admin_test_menu_kb(db, is_main_bot))
        await call.answer()

    @router.callback_query(F.data == "adm_test_toggle")
    async def cb_admin_test_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "test_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "test_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, "🧪 مدیریت کانفیگ تست:", reply_markup=kb.admin_test_menu_kb(db, is_main_bot))
        await call.answer("وضعیت کانفیگ تست تغییر کرد.")

    @router.callback_query(F.data == "adm_test_add")
    async def cb_admin_test_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            await call.answer("این بخش برای نمایندگی سطح ۲ فعال نیست.", show_alert=True)
            return
        await state.set_state(AdminAddTestConfigs.waiting_links)
        await safe_edit(call, 
            "لینک‌های کانفیگ تست را ارسال کنید (هر لینک در یک خط):", reply_markup=kb.admin_back_kb()
        )
        await call.answer()

    @router.message(AdminAddTestConfigs.waiting_links)
    async def process_add_test_configs(message: Message, state: FSMContext):
        links = [line for line in message.text.splitlines() if line.strip()]
        (await asyncio.to_thread(db.add_test_configs, links))
        await state.clear()
        await message.answer(f"✅ {len(links)} لینک تست اضافه شد.", reply_markup=kb.admin_test_menu_kb(db, is_main_bot))

    @router.callback_query(F.data == "adm_test_set_volume")
    async def cb_admin_test_set_volume(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)) and not (
            await asyncio.to_thread(db.get_panel_server_for_usage, "test_config")
        ):
            await call.answer("این بخش فقط وقتی یک پنل برای کانفیگ تست فعال باشد در دسترس است.", show_alert=True)
            return
        await state.set_state(AdminTestConfigSettings.waiting_volume)
        await safe_edit(call, "کانفیگ تست چند گیگابایت باشد؟ فقط عدد وارد کنید (مثال: 1):", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminTestConfigSettings.waiting_volume)
    async def process_test_volume(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً فقط عدد صحیح و بزرگ‌تر از صفر وارد کنید. مثال: 1")
            return
        await state.update_data(volume_gb=int(text))
        await state.set_state(AdminTestConfigSettings.waiting_duration)
        await message.answer("کانفیگ تست چند روز اعتبار داشته باشد؟ فقط عدد وارد کنید (مثال: 1):")

    @router.message(AdminTestConfigSettings.waiting_duration)
    async def process_test_duration(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً فقط عدد صحیح و بزرگ‌تر از صفر وارد کنید. مثال: 1")
            return
        data = await state.get_data()
        (await asyncio.to_thread(db.set_setting, "test_config_panel_volume_gb", str(data["volume_gb"])))
        (await asyncio.to_thread(db.set_setting, "test_config_panel_duration_days", text))
        await state.clear()
        await message.answer(
            f"✅ کانفیگ تست تنظیم شد: {data['volume_gb']} گیگ / {text} روز.",
            reply_markup=kb.admin_test_menu_kb(db, is_main_bot),
        )

    # -------------------------------------------------------------------
    # عضویت اجباری در کانال
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_forcejoin_menu")
    async def cb_admin_forcejoin_menu(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, 
            "📢 عضویت اجباری در کانال:\n\n"
            "کاربران قبل از استفاده از بات باید عضو کانال شما باشند. "
            "دقت کن که ربات باید از قبل ادمین کانال شده باشد تا بتواند عضویت را بررسی کند.",
            reply_markup=kb.admin_forcejoin_menu_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_forcejoin_toggle")
    async def cb_admin_forcejoin_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        settings = (await asyncio.to_thread(db.get_force_join_settings))
        if not settings["enabled"] and not settings["channel"]:
            await call.answer("اول باید آیدی کانال را تنظیم کنی.", show_alert=True)
            return
        current = (await asyncio.to_thread(db.get_setting, "force_join_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "force_join_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, "📢 عضویت اجباری در کانال:", reply_markup=kb.admin_forcejoin_menu_kb(db))
        await call.answer("وضعیت عضویت اجباری تغییر کرد.")

    @router.callback_query(F.data == "adm_forcejoin_set_channel")
    async def cb_admin_forcejoin_set_channel(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminForceJoin.waiting_channel)
        await safe_edit(call, 
            "آیدی عددی یا یوزرنیم کانال را ارسال کن.\n\n"
            "مثال: `@mychannel`\n\n"
            "⚠️ حتماً ربات باید از قبل به‌عنوان ادمین به کانال اضافه شده باشد؛ در غیر این صورت نمی‌تواند عضویت را بررسی کند.",
            reply_markup=kb.admin_back_kb("adm_forcejoin_menu"),
        )
        await call.answer()

    @router.message(AdminForceJoin.waiting_channel)
    async def process_forcejoin_channel(message: Message, state: FSMContext, bot: Bot):
        channel = (message.text or "").strip()
        if not channel:
            await message.answer("ورودی نامعتبر است. دوباره تلاش کن.")
            return
        if not channel.startswith("@") and not channel.startswith("-"):
            channel = "@" + channel

        try:
            chat = await bot.get_chat(channel)
            member = await bot.get_chat_member(channel, bot.id)
            if member.status not in ("administrator", "creator"):
                raise ValueError("bot is not admin")
        except Exception:
            await message.answer(
                "⛔️ نتوانستم به این کانال دسترسی پیدا کنم.\n"
                "مطمئن شو آیدی درست است و ربات از قبل به‌عنوان *ادمین* به کانال اضافه شده باشد.",
                reply_markup=kb.admin_back_kb("adm_forcejoin_menu"),
            )
            return

        (await asyncio.to_thread(db.set_setting, "force_join_channel", channel))
        await state.clear()
        await message.answer(
            f"✅ کانال «{chat.title}» ثبت شد. حالا می‌تونی از منوی قبلی عضویت اجباری رو فعال کنی.",
            reply_markup=kb.admin_forcejoin_menu_kb(db),
        )

    # -------------------------------------------------------------------
    # سفارش‌های در انتظار
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_pending_orders")
    async def cb_admin_pending_orders(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        orders = (await asyncio.to_thread(db.get_pending_orders))
        if not orders:
            await call.answer("سفارش در انتظاری وجود ندارد.", show_alert=True)
            return
        await replace_admin_view(call, "🧾 سفارش‌های در انتظار بررسی:", reply_markup=kb.pending_orders_kb(orders))
        await call.answer()

    @router.callback_query(F.data.startswith("view_order:"))
    async def cb_view_order(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        order_id = callback_id(call.data, "view_order")
        if order_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order:
            await call.answer("سفارش یافت نشد.", show_alert=True)
            return
        product = (await asyncio.to_thread(db.get_product, order["product_id"]))
        qty = order["quantity"] or 1
        caption = f"سفارش #{order_id}\nکاربر: {order['user_id']}\nمحصول: {product['name'] if product else '---'}"
        if qty > 1:
            caption += f" × {qty}"
        if order["receipt_file_id"]:
            await _send_receipt(
                bot, call.from_user.id, order["receipt_file_id"], (order["receipt_type"] if "receipt_type" in order.keys() else "photo"),
                caption, kb.order_review_kb(order_id)
            )
        else:
            await call.message.answer(caption, reply_markup=kb.order_review_kb(order_id))
        await call.answer()

    @router.callback_query(F.data.startswith("order_approve:"))
    async def cb_order_approve(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()

        order_id = callback_id(call.data, "order_approve")
        if order_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order:
            await call.answer("سفارش یافت نشد.", show_alert=True)
            return
        if order["status"] != "pending":
            await call.answer("این سفارش قبلاً بررسی شده است.", show_alert=True)
            return

        # ===== سفارش کانفیگ شخصی: به‌جای برداشتن از انبار، کاربر روی پنل ساخته می‌شود =====
        if order["is_custom_config"]:
            server = (await asyncio.to_thread(db.get_panel_server, order["custom_panel_server_id"]))
            if not server or not server["is_active"]:
                await call.answer("⛔️ سرور پنل مربوطه یافت نشد یا غیرفعال است.", show_alert=True)
                return
            try:
                provider = get_provider(server)
                result = await provider.create_user(
                    username=order["custom_username"],
                    volume_gb=order["custom_volume_gb"],
                    duration_days=(await asyncio.to_thread(db.get_custom_config_settings))["duration_days"],
                )
            except PanelUsernameTakenError:
                await call.answer("⛔️ این نام کاربری روی پنل تکراری است؛ از کاربر بخواه نام دیگری انتخاب کند.", show_alert=True)
                return
            except PanelError as e:
                await call.answer(f"⛔️ خطا در ارتباط با پنل: {e}", show_alert=True)
                return

            (await asyncio.to_thread(db.approve_custom_config_order, order_id))
            (await asyncio.to_thread(db.add_custom_config, 
                user_id=order["user_id"],
                panel_server_id=server["id"],
                username=result.username,
                volume_gb=order["custom_volume_gb"],
                duration_days=db.get_custom_config_settings()["duration_days"],
                subscription_url=result.subscription_url,
                order_id=order_id,
            ))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "custom_config_approve",
                f"سفارش کانفیگ شخصی #{order_id} | کاربر {order['user_id']} | یوزرنیم «{result.username}» | "
                f"{order['custom_volume_gb']} گیگ | مبلغ: {order['final_price']:,}",
            ))
            try:
                await bot.send_message(order["user_id"], "✅ کانفیگ شخصی شما ساخته شد!")
                await deliver_config_to_user(
                    bot, order["user_id"], "کانفیگ شخصی",
                    [result.subscription_url], final_price=order["final_price"], order_id=order_id,
                )
                await _notify_user_inline_menu(bot, order["user_id"])
            except Exception:
                pass
            try:
                await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ تایید شد و کانفیگ ساخته شد.")
            except Exception:
                try:
                    await safe_edit(call, (call.message.text or "") + "\n\n✅ تایید شد و کانفیگ ساخته شد.")
                except Exception:
                    pass
            await call.answer("سفارش تایید و کانفیگ شخصی روی پنل ساخته شد.")
            await _notify_admin_panel_menu(bot, call.from_user.id)
            return

        product = (await asyncio.to_thread(db.get_product, order["product_id"]))

        if product and product["is_auto_provision"]:
            quantity = order["quantity"] or 1
            try:
                if product["provision_server_id"]:
                    prov_results = await provision_direct(db, product, quantity, user_id=order["user_id"], order_id=order_id)
                else:
                    prov_results = await provision_auto_config(db, product, quantity, user_id=order["user_id"], order_id=order_id)
            except (ProvisionError, DirectProvisionError) as e:
                await call.answer(f"⛔️ {e}", show_alert=True)
                return
            (await asyncio.to_thread(db.approve_order_auto, order_id))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "order_approve",
                f"سفارش #{order_id} (خودکار) | کاربر {order['user_id']} | محصول «{product['name']}» | "
                f"مبلغ: {(order['final_price'] or product['price']):,}",
            ))
            try:
                await bot.send_message(order["user_id"], f"✅ خرید شما تایید شد!\n📦 محصول: {product['name']}")
                await deliver_config_to_user(
                    bot, order["user_id"], product["name"],
                    [r["subscription_url"] for r in prov_results], final_price=order["final_price"], order_id=order_id,
                )
                await _notify_user_inline_menu(bot, order["user_id"])
            except Exception:
                pass
            try:
                await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ تایید شد و کانفیگ ساخته شد.")
            except Exception:
                try:
                    await safe_edit(call, (call.message.text or "") + "\n\n✅ تایید شد و کانفیگ ساخته شد.")
                except Exception:
                    pass
            await call.answer("سفارش تایید و کانفیگ به‌صورت خودکار ساخته شد.")
            await _notify_admin_panel_menu(bot, call.from_user.id)
            return

        quantity = order["quantity"] or 1
        results = (await asyncio.to_thread(db.take_unused_configs, order["product_id"], order["user_id"], quantity))
        if not results:
            await call.answer("⛔️ موجودی این محصول تمام شده! ابتدا لینک جدید اضافه کنید.", show_alert=True)
            return

        (await asyncio.to_thread(db.approve_order, order_id, [r["id"] for r in results]))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "order_approve",
            f"سفارش #{order_id} | کاربر {order['user_id']} | محصول «{product['name'] if product else '---'}» | مبلغ: {(order['final_price'] or (product['price'] if product else 0)):,}",
        ))
        await check_and_notify_low_stock(bot.send_message, db, order["product_id"])

        reward_info = (await asyncio.to_thread(db.reward_referrer_if_first_purchase, order["user_id"], order["final_price"] or product["price"]))
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

        try:
            await bot.send_message(order["user_id"], f"✅ خرید شما تایید شد!\n📦 محصول: {product['name']}")
            await deliver_config_to_user(
                bot,
                order["user_id"],
                product["name"],
                [r["link"] for r in results],
                final_price=order["final_price"],
                order_id=order_id,
            )
            await _notify_user_inline_menu(bot, order["user_id"])
        except Exception:
            pass

        try:
            await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ تایید شد و کانفیگ ارسال شد.")
        except Exception:
            try:
                await safe_edit(call, (call.message.text or "") + "\n\n✅ تایید شد و کانفیگ ارسال شد.")
            except Exception:
                pass
        await call.answer("سفارش تایید و کانفیگ برای کاربر ارسال شد.")
        await _notify_admin_panel_menu(bot, call.from_user.id)

    @router.callback_query(F.data.startswith("order_reject:"))
    async def cb_order_reject(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()

        order_id = callback_id(call.data, "order_reject")
        if order_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order:
            await call.answer("سفارش یافت نشد.", show_alert=True)
            return
        if order["status"] != "pending":
            await call.answer("این سفارش قبلاً بررسی شده است.", show_alert=True)
            return

        (await asyncio.to_thread(db.reject_order, order_id))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "order_reject",
            f"سفارش #{order_id} | کاربر {order['user_id']}",
        ))
        try:
            await bot.send_message(
                order["user_id"],
                "❌ متاسفانه رسید ارسالی شما تایید نشد. در صورت اشتباه لطفاً با پشتیبانی در ارتباط باشید.",
            )
            await _notify_user_inline_menu(bot, order["user_id"])
        except Exception:
            pass

        try:
            await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ رد شد.")
        except Exception:
            try:
                await safe_edit(call, (call.message.text or "") + "\n\n❌ رد شد.")
            except Exception:
                pass
        await call.answer("سفارش رد شد.")
        await _notify_admin_panel_menu(bot, call.from_user.id)

    # -------------------------------------------------------------------
    # درخواست‌های شارژ کیف پول
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_pending_topups")
    async def cb_admin_pending_topups(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        topups = (await asyncio.to_thread(db.get_pending_topups))
        if not topups:
            await call.answer("درخواست شارژ در انتظاری وجود ندارد.", show_alert=True)
            return
        await replace_admin_view(call, "👛 درخواست‌های شارژ کیف پول در انتظار:", reply_markup=kb.pending_topups_kb(topups))
        await call.answer()

    # -------------------------------------------------------------------
    # پرداخت‌های کریپتو (تایید خودکار)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_crypto_payments")
    async def cb_admin_crypto_payments(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        (await asyncio.to_thread(db.expire_stale_crypto_invoices))
        (await asyncio.to_thread(db.purge_old_crypto_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_crypto_invoices, 50))
        if not invoices:
            await call.answer("هیچ پرداخت کریپتویی ثبت نشده است.", show_alert=True)
            return
        await replace_admin_view(
            call,
            "🪙 پرداخت‌های کریپتو\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.crypto_invoices_kb(invoices),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("view_crypto_invoice:"))
    async def cb_view_crypto_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "view_crypto_invoice")
        if invoice_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_crypto_invoice, invoice_id))
        if not invoice:
            await call.answer("فاکتور یافت نشد.", show_alert=True)
            return

        status_text = {
            "new": "🟡 جدید",
            "pending": "🟠 در انتظار تایید شبکه",
            "completed": "🟢 تکمیل‌شده",
            "expired": "🔴 منقضی‌شده",
            "cancelled": "⚪️ لغوشده",
            "error": "🔴 خطا",
            "mismatch": "🟣 مغایرت",
        }.get(invoice["status"], invoice["status"] or "---")
        kind_text = {"order": "🧾 سفارش", "wallet_topup": "👛 شارژ کیف پول"}.get(invoice["kind"], invoice["kind"])

        text = (
            f"🪙 فاکتور کریپتو #{invoice['id']}\n"
            f"{kind_text}: #{invoice['ref_id']}\n"
            f"👤 کاربر: {invoice['user_id']}\n"
            f"💰 مبلغ: {invoice['amount_toman']:,} تومان\n"
            f"💵 معادل: {invoice['source_amount_usd']:.2f} USD\n"
            f"🪙 ارز: {invoice['currency'] or 'انتخاب نشده'}\n"
            f"📌 وضعیت: {status_text}\n"
            f"⏳ اعتبار فاکتور: ۸۰ دقیقه\n"
            f"🕐 ایجاد: {invoice['created_at'] or '---'}\n"
            f"⌛ انقضا: {invoice['expires_at'] or '---'}"
        )
        rows = []
        if invoice["invoice_url"] and invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text="🔗 باز کردن فاکتور", url=invoice["invoice_url"])])
        if invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text="❌ لغو و حذف فاکتور", callback_data=f"cancel_crypto_invoice:{invoice['id']}")])
        rows.append([InlineKeyboardButton(text="⬅️ بازگشت به پرداخت‌های کریپتو", callback_data="adm_crypto_payments")])
        await replace_admin_view(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("cancel_crypto_invoice:"))
    async def cb_cancel_crypto_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "cancel_crypto_invoice")
        if invoice_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_crypto_invoice, invoice_id))
        if not invoice:
            await call.answer("فاکتور یافت نشد یا قبلاً حذف شده.", show_alert=True)
        else:
            (await asyncio.to_thread(db.cancel_and_delete_crypto_invoice, invoice_id))
            await call.answer("✅ فاکتور لغو و حذف شد.")

        (await asyncio.to_thread(db.expire_stale_crypto_invoices))
        (await asyncio.to_thread(db.purge_old_crypto_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_crypto_invoices, 50))
        if not invoices:
            await replace_admin_view(call, "🪙 پرداخت‌های کریپتو\n\nهیچ پرداخت کریپتویی ثبت نشده است.",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:daily")]
                                      ]))
            return
        await replace_admin_view(
            call,
            "🪙 پرداخت‌های کریپتو\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.crypto_invoices_kb(invoices),
        )

    # -------------------------------------------------------------------
    # پرداخت‌های آبان گیت وی (تایید خودکار کارت‌به‌کارت)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_abangateway_payments")
    async def cb_admin_abangateway_payments(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        (await asyncio.to_thread(db.expire_stale_abangateway_invoices))
        (await asyncio.to_thread(db.purge_old_abangateway_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_abangateway_invoices, 50))
        if not invoices:
            await call.answer("هیچ پرداخت آبان گیت‌وی‌ای ثبت نشده است.", show_alert=True)
            return
        await replace_admin_view(
            call,
            "💳 پرداخت‌های آبان گیت وی\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.abangateway_invoices_kb(invoices),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("view_abangateway_invoice:"))
    async def cb_view_abangateway_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "view_abangateway_invoice")
        if invoice_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_id))
        if not invoice:
            await call.answer("فاکتور یافت نشد.", show_alert=True)
            return

        status_text = {
            "new": "🟡 جدید",
            "pending": "🟠 در انتظار پرداخت",
            "completed": "🟢 تکمیل‌شده",
            "expired": "🔴 منقضی‌شده",
            "cancelled": "⚪️ لغوشده",
            "error": "🔴 خطا",
        }.get(invoice["status"], invoice["status"] or "---")
        kind_text = {"order": "🧾 سفارش", "wallet_topup": "👛 شارژ کیف پول"}.get(invoice["kind"], invoice["kind"])

        text = (
            f"💳 فاکتور آبان گیت وی #{invoice['id']}\n"
            f"{kind_text}: #{invoice['ref_id']}\n"
            f"👤 کاربر: {invoice['user_id']}\n"
            f"💰 مبلغ: {invoice['amount_toman']:,} تومان\n"
            f"📌 وضعیت: {status_text}\n"
            f"🕐 ایجاد: {invoice['created_at'] or '---'}\n"
            f"⌛ انقضا: {invoice['expires_at'] or '---'}"
        )
        rows = []
        if invoice["payment_url"] and invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text="🔗 باز کردن فاکتور", url=invoice["payment_url"])])
        if invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text="🔄 بررسی وضعیت", callback_data=f"check_abangateway_invoice:{invoice['id']}")])
            rows.append([InlineKeyboardButton(text="❌ لغو و حذف فاکتور", callback_data=f"cancel_abangateway_invoice:{invoice['id']}")])
        rows.append([InlineKeyboardButton(text="⬅️ بازگشت به پرداخت‌های آبان گیت وی", callback_data="adm_abangateway_payments")])
        await replace_admin_view(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("check_abangateway_invoice:"))
    async def cb_check_abangateway_invoice(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "check_abangateway_invoice")
        if invoice_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_id))
        if not invoice:
            await call.answer("فاکتور یافت نشد.", show_alert=True)
            return
        await call.answer("در حال بررسی...")
        result = await abangateway_payment.try_verify_and_finalize(db, invoice)
        if result == "verified_now":
            if invoice["kind"] == "wallet_topup":
                text = await abangateway_payment.finalize_paid_topup(db, invoice["ref_id"])
            else:
                text = await abangateway_payment.finalize_paid_order(db, bot, invoice["ref_id"])
            await call.message.answer(text)
        elif result == "not_paid_yet":
            await call.message.answer("⏳ هنوز واریزی برای این فاکتور تایید نشده.")
        elif result == "already_delivered":
            await call.message.answer("✅ این پرداخت قبلاً تایید و تحویل داده شده است.")
        elif result in ("expired", "cancelled"):
            await call.message.answer("❌ اعتبار این فاکتور تمام شده یا لغو شده است.")
        elif result.startswith("error:"):
            await call.message.answer(f"⚠️ خطا در بررسی وضعیت: {result[6:]}")

    @router.callback_query(F.data.startswith("cancel_abangateway_invoice:"))
    async def cb_cancel_abangateway_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "cancel_abangateway_invoice")
        if invoice_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_id))
        if not invoice:
            await call.answer("فاکتور یافت نشد یا قبلاً حذف شده.", show_alert=True)
        else:
            (await asyncio.to_thread(db.cancel_and_delete_abangateway_invoice, invoice_id))
            await call.answer("✅ فاکتور لغو و حذف شد.")

        (await asyncio.to_thread(db.expire_stale_abangateway_invoices))
        (await asyncio.to_thread(db.purge_old_abangateway_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_abangateway_invoices, 50))
        if not invoices:
            await replace_admin_view(call, "💳 پرداخت‌های آبان گیت وی\n\nهیچ پرداخت آبان گیت‌وی‌ای ثبت نشده است.",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:daily")]
                                      ]))
            return
        await replace_admin_view(
            call,
            "💳 پرداخت‌های آبان گیت وی\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.abangateway_invoices_kb(invoices),
        )

    # -------------------------------------------------------------------
    # تنظیم درگاه پرداخت آبان گیت وی
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_set_abangateway")
    async def cb_admin_set_abangateway(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "abangateway_api_key", ""))
        masked = f"...{current[-4:]}" if current else "❌ تنظیم نشده"
        source = abangateway_payment.resolve_api_key_source(db)
        source_note = {
            "db": "✅ از همین پنل بات خوانده می‌شود (بات و مینی‌اپ هر دو همین را می‌بینند، بدون نیاز به ری‌استارت).",
            "env": "⚠️ فقط از فایل .env این پروسه خوانده می‌شود. اگر بات و مینی‌اپ را جدا ری‌استارت نکرده باشی ممکن است این دو با هم ناهماهنگ باشند. پیشنهاد: همینجا دوباره ثبتش کن تا مطمئن بشی.",
            "none": "❌ هیچ کلیدی (نه در دیتابیس، نه در .env) تنظیم نشده.",
        }[source]
        await state.set_state(AdminSetAbanGateway.waiting_key)
        await safe_edit(
            call,
            f"💳 API Key حساب آبان گیت وی را ارسال کن (از abangateway.ir → تنظیمات API).\n"
            f"وضعیت فعلی: {masked}\n"
            f"منبع کلید: {source_note}\n\n"
            f"برای غیرفعال‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminSetAbanGateway.waiting_key)
    async def process_set_abangateway_key(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "abangateway_api_key", ""))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "abangateway_key_change", "API Key آبان گیت وی حذف شد."))
            await message.answer("✅ API Key آبان گیت وی حذف شد و درگاه غیرفعال شد.", reply_markup=kb.admin_panel_kb(db, is_main_bot))
            return
        (await asyncio.to_thread(db.set_setting, "abangateway_api_key", text))
        (await asyncio.to_thread(db.set_setting, "abangateway_payment_enabled", "1"))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "abangateway_key_change", "API Key آبان گیت وی تغییر کرد."))
        await message.answer(
            "✅ API Key آبان گیت وی ذخیره شد و درگاه فعال شد.\n"
            "برای غیرفعال‌کردن، دوباره وارد همین بخش شو و «حذف» را بفرست.",
            reply_markup=kb.admin_panel_kb(db, is_main_bot),
        )

    @router.callback_query(F.data.startswith("view_topup:"))
    async def cb_view_topup(call: CallbackQuery, bot: Bot):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        topup_id = callback_id(call.data, "view_topup")
        if topup_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        topup = (await asyncio.to_thread(db.get_topup, topup_id))
        if not topup:
            await call.answer("درخواست یافت نشد.", show_alert=True)
            return
        caption = f"شارژ کیف پول #{topup_id}\nکاربر: {topup['user_id']}\nمبلغ: {topup['amount']:,} تومان"
        if topup["receipt_file_id"]:
            await _send_receipt(
                bot, call.from_user.id, topup["receipt_file_id"], (topup["receipt_type"] if "receipt_type" in topup.keys() else "photo"),
                caption, kb.topup_review_kb(topup_id)
            )
        else:
            await call.message.answer(caption, reply_markup=kb.topup_review_kb(topup_id))
        await call.answer()

    @router.callback_query(F.data.startswith("topup_approve:"))
    async def cb_topup_approve(call: CallbackQuery, bot: Bot):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)

        topup_id = callback_id(call.data, "topup_approve")
        if topup_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        topup = (await asyncio.to_thread(db.get_topup, topup_id))
        if not topup:
            await call.answer("درخواست یافت نشد.", show_alert=True)
            return
        if topup["status"] != "pending":
            await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
            return

        (await asyncio.to_thread(db.approve_topup, topup_id))
        new_balance = (await asyncio.to_thread(db.get_wallet_credit, topup["user_id"]))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "topup_approve",
            f"شارژ #{topup_id} | کاربر {topup['user_id']} | مبلغ: {topup['amount']:,} | موجودی جدید: {new_balance:,}",
        ))

        try:
            await bot.send_message(
                topup["user_id"],
                f"✅ شارژ کیف پول شما تایید شد!\n💰 مبلغ {topup['amount']:,} تومان اضافه شد.\n"
                f"👛 موجودی فعلی کیف پول شما: {new_balance:,} تومان",
            )
            await _notify_user_inline_menu(bot, topup["user_id"])
        except Exception:
            pass

        try:
            await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ تایید و شارژ شد.")
        except Exception:
            try:
                await safe_edit(call, (call.message.text or "") + "\n\n✅ تایید و شارژ شد.")
            except Exception:
                pass
        await call.answer("شارژ کیف پول تایید شد.")
        await _notify_admin_panel_menu(bot, call.from_user.id)

    @router.callback_query(F.data.startswith("topup_reject:"))
    async def cb_topup_reject(call: CallbackQuery, bot: Bot):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)

        topup_id = callback_id(call.data, "topup_reject")
        if topup_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        topup = (await asyncio.to_thread(db.get_topup, topup_id))
        if not topup:
            await call.answer("درخواست یافت نشد.", show_alert=True)
            return
        if topup["status"] != "pending":
            await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
            return

        (await asyncio.to_thread(db.reject_topup, topup_id))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "topup_reject",
            f"شارژ #{topup_id} | کاربر {topup['user_id']} | مبلغ: {topup['amount']:,}",
        ))
        try:
            await bot.send_message(
                topup["user_id"],
                "❌ متاسفانه درخواست شارژ کیف پول شما تایید نشد. در صورت اشتباه با پشتیبانی تماس بگیرید.",
            )
            await _notify_user_inline_menu(bot, topup["user_id"])
        except Exception:
            pass

        try:
            await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ رد شد.")
        except Exception:
            try:
                await safe_edit(call, (call.message.text or "") + "\n\n❌ رد شد.")
            except Exception:
                pass
        await call.answer("درخواست رد شد.")
        await _notify_admin_panel_menu(bot, call.from_user.id)

    # -------------------------------------------------------------------
    # مدیریت کدهای تخفیف
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_discounts_menu")
    async def cb_admin_discounts_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        codes = (await asyncio.to_thread(db.list_discount_codes))
        await replace_admin_view(call, "🎟 مدیریت کدهای تخفیف:", reply_markup=kb.discount_codes_kb(codes))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_disc_toggle:"))
    async def cb_admin_disc_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code_id = callback_id(call.data, "adm_disc_toggle")
        if code_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        (await asyncio.to_thread(db.toggle_discount_code, code_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "discount_toggle", f"کد تخفیف #{code_id}"))
        codes = (await asyncio.to_thread(db.list_discount_codes))
        await safe_edit(call, "🎟 مدیریت کدهای تخفیف:", reply_markup=kb.discount_codes_kb(codes))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data.startswith("adm_disc_del:"))
    async def cb_admin_disc_del(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code_id = callback_id(call.data, "adm_disc_del")
        if code_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        (await asyncio.to_thread(db.delete_discount_code, code_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "discount_delete", f"کد تخفیف #{code_id}"))
        codes = (await asyncio.to_thread(db.list_discount_codes))
        await safe_edit(call, "🎟 مدیریت کدهای تخفیف:", reply_markup=kb.discount_codes_kb(codes))
        await call.answer("کد حذف شد.")

    @router.callback_query(F.data == "adm_disc_add")
    async def cb_admin_disc_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCreateDiscount.waiting_code)
        await safe_edit(call, 
            "نام کد تخفیف را ارسال کنید (مثلاً WELCOME20، بدون فاصله):", reply_markup=kb.admin_back_kb()
        )
        await call.answer()

    @router.message(AdminCreateDiscount.waiting_code)
    async def process_disc_code(message: Message, state: FSMContext):
        code = message.text.strip()
        if (await asyncio.to_thread(db.get_discount_code, code)):
            await message.answer("⛔️ این کد از قبل وجود دارد. یک نام دیگر ارسال کنید:")
            return
        await state.update_data(disc_code=code)
        await state.set_state(AdminCreateDiscount.waiting_type_value)
        await message.answer(
            "نوع و مقدار تخفیف را به یکی از این دو شکل ارسال کنید:\n\n"
            "برای تخفیف درصدی: `percent 20`\n"
            "برای تخفیف مبلغ ثابت: `fixed 50000`",
            parse_mode="Markdown",
        )

    @router.message(AdminCreateDiscount.waiting_type_value)
    async def process_disc_type_value(message: Message, state: FSMContext):
        parts = message.text.strip().split()
        if len(parts) != 2 or parts[0].lower() not in ("percent", "fixed") or not parts[1].isdigit():
            await message.answer("فرمت اشتباه است. مثال درست: `percent 20` یا `fixed 50000`", parse_mode="Markdown")
            return

        kind, value = parts[0].lower(), int(parts[1])
        if kind == "percent":
            await state.update_data(disc_percent=value, disc_fixed=None)
        else:
            await state.update_data(disc_percent=None, disc_fixed=value)

        await state.set_state(AdminCreateDiscount.waiting_maxuses)
        await message.answer("سقف تعداد استفاده از این کد چند بار باشد؟ (برای نامحدود عدد 0 را بفرست)")

    @router.message(AdminCreateDiscount.waiting_maxuses)
    async def process_disc_maxuses(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer("لطفاً فقط عدد ارسال کنید (0 برای نامحدود).")
            return
        max_uses = int(message.text.strip())
        data = await state.get_data()
        (await asyncio.to_thread(db.create_discount_code, 
            data["disc_code"], percent=data.get("disc_percent"), fixed_amount=data.get("disc_fixed"), max_uses=max_uses
        ))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "discount_add", f"کد «{data['disc_code']}»"))
        await state.clear()
        codes = (await asyncio.to_thread(db.list_discount_codes))
        await message.answer(f"✅ کد تخفیف «{data['disc_code']}» ساخته شد.", reply_markup=kb.discount_codes_kb(codes))

    # -------------------------------------------------------------------
    # تنظیمات زیرمجموعه‌گیری
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_referral_settings")
    async def cb_admin_referral_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "🤝 تنظیمات زیرمجموعه‌گیری:", reply_markup=kb.referral_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_referral_toggle")
    async def cb_admin_referral_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "referral_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "referral_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, "🤝 تنظیمات زیرمجموعه‌گیری:", reply_markup=kb.referral_settings_kb(db))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data == "adm_referral_percent_edit")
    async def cb_admin_referral_percent_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralPercent.waiting_value)
        await safe_edit(call, 
            "درصد پورسانت جدید را وارد کنید (عددی بین 0 تا 100):", reply_markup=kb.admin_back_kb()
        )
        await call.answer()

    @router.message(AdminReferralPercent.waiting_value)
    async def process_referral_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 <= int(text) <= 100):
            await message.answer("لطفاً یک عدد بین 0 تا 100 ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "referral_percent", text))
        await state.clear()
        await message.answer(f"✅ درصد پورسانت زیرمجموعه‌گیری روی {text}٪ تنظیم شد.", reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_commission_max_edit")
    async def cb_admin_referral_commission_max_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralCommissionMax.waiting_value)
        await safe_edit(call,
            "حداکثر تعداد زیرمجموعه‌هایی که پورسانت خریدشان تعلق می‌گیرد را وارد کنید "
            "(برای نامحدود، عدد 0 را ارسال کنید):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminReferralCommissionMax.waiting_value)
    async def process_referral_commission_max(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit():
            await message.answer("لطفاً یک عدد صحیح (0 یا بیشتر) ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "referral_commission_max_count", text))
        await state.clear()
        label = "نامحدود" if text == "0" else f"{text} نفر"
        await message.answer(f"✅ سقف تعداد نفرات پورسانت‌دار روی «{label}» تنظیم شد.", reply_markup=kb.referral_settings_kb(db))

    # --- حالت ۲: کانفیگ رایگان با تعداد دعوت مشخص ---

    @router.callback_query(F.data == "adm_referral_freeconfig_toggle")
    async def cb_admin_referral_freeconfig_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "referral_free_config_enabled", "0"))
        new_value = "0" if current == "1" else "1"
        if new_value == "1" and not (await asyncio.to_thread(db.get_setting, "referral_free_config_product_id", "")):
            await call.answer("ابتدا از «انتخاب محصول جایزه» یک محصول انتخاب کنید.", show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "referral_free_config_enabled", new_value))
        await safe_edit(call, "🤝 تنظیمات زیرمجموعه‌گیری:", reply_markup=kb.referral_settings_kb(db))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data == "adm_referral_freeconfig_threshold_edit")
    async def cb_admin_referral_freeconfig_threshold_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralFreeConfigThreshold.waiting_value)
        await safe_edit(call,
            "با دعوت چند نفر، یک کانفیگ رایگان تعلق بگیرد؟ عدد را وارد کنید:",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminReferralFreeConfigThreshold.waiting_value)
    async def process_referral_freeconfig_threshold(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer("لطفاً یک عدد صحیح بزرگ‌تر از صفر ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "referral_free_config_threshold", text))
        await state.clear()
        await message.answer(f"✅ با دعوت {text} نفر، کانفیگ رایگان تعلق می‌گیرد.", reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_freeconfig_product")
    async def cb_admin_referral_freeconfig_product(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "📦 محصولی که به‌عنوان جایزه رایگان تحویل داده شود را انتخاب کنید:", reply_markup=kb.referral_freeconfig_product_kb(db))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_referral_freeconfig_setprod:"))
    async def cb_admin_referral_freeconfig_setprod(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = call.data.split(":")[1]
        product = (await asyncio.to_thread(db.get_product, int(product_id)))
        if not product:
            await call.answer("این محصول یافت نشد.", show_alert=True)
            return
        if not product["is_auto_provision"] or not product["provision_server_id"]:
            await call.answer(
                "این محصول تحویل خودکار ندارد؛ فقط محصولاتی که به یک پنل وصل و «تحویل خودکار» هستند قابل انتخاب‌اند.",
                show_alert=True,
            )
            return
        (await asyncio.to_thread(db.set_setting, "referral_free_config_product_id", product_id))
        await safe_edit(call, "🤝 تنظیمات زیرمجموعه‌گیری:", reply_markup=kb.referral_settings_kb(db))
        await call.answer(f"✅ محصول «{product['name']}» به‌عنوان جایزه انتخاب شد.")

    # --- حالت ۳: شارژ ثابت کیف پول به‌ازای هر دعوت ---

    @router.callback_query(F.data == "adm_referral_invitebonus_toggle")
    async def cb_admin_referral_invitebonus_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "referral_invite_bonus_enabled", "0"))
        new_value = "0" if current == "1" else "1"
        if new_value == "1" and int((await asyncio.to_thread(db.get_setting, "referral_invite_bonus_amount", "0")) or 0) <= 0:
            await call.answer("ابتدا مبلغ شارژ را از «تغییر مبلغ شارژ» تنظیم کنید.", show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "referral_invite_bonus_enabled", new_value))
        await safe_edit(call, "🤝 تنظیمات زیرمجموعه‌گیری:", reply_markup=kb.referral_settings_kb(db))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data == "adm_referral_invitebonus_amount_edit")
    async def cb_admin_referral_invitebonus_amount_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralInviteBonusAmount.waiting_value)
        await safe_edit(call,
            "مبلغ ثابتی که برای هر دعوت به کیف پول دعوت‌کننده اضافه شود را به تومان وارد کنید:",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminReferralInviteBonusAmount.waiting_value)
    async def process_referral_invitebonus_amount(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 0:
            await message.answer("لطفاً یک عدد صحیح ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "referral_invite_bonus_amount", text))
        await state.clear()
        await message.answer(f"✅ مبلغ شارژ به‌ازای هر دعوت روی {int(text):,} تومان تنظیم شد.", reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_invitebonus_max_edit")
    async def cb_admin_referral_invitebonus_max_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralInviteBonusMax.waiting_value)
        await safe_edit(call,
            "این شارژ فقط برای چند نفر اول دعوت‌شده اعمال شود؟ عدد را وارد کنید "
            "(برای نامحدود، عدد 0 را ارسال کنید):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminReferralInviteBonusMax.waiting_value)
    async def process_referral_invitebonus_max(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit():
            await message.answer("لطفاً یک عدد صحیح (0 یا بیشتر) ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "referral_invite_bonus_max_count", text))
        await state.clear()
        label = "نامحدود" if text == "0" else f"{text} نفر"
        await message.answer(f"✅ سقف تعداد نفرات شارژ به‌ازای دعوت روی «{label}» تنظیم شد.", reply_markup=kb.referral_settings_kb(db))

    # -------------------------------------------------------------------
    # مدیریت گردونه شانس
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_wheel_settings")
    async def cb_admin_wheel_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "🎡 مدیریت گردونه شانس:", reply_markup=kb.wheel_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_wheel_toggle")
    async def cb_admin_wheel_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "wheel_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "wheel_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, "🎡 مدیریت گردونه شانس:", reply_markup=kb.wheel_settings_kb(db))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data == "adm_wheel_edit_percent")
    async def cb_admin_wheel_edit_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_win_percent)
        await safe_edit(call, 
            "درصد احتمال برد را وارد کنید (عددی بین 0 تا 100، مثلاً 10):", reply_markup=kb.admin_back_kb()
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_win_percent)
    async def process_wheel_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 <= int(text) <= 100):
            await message.answer("لطفاً یک عدد بین 0 تا 100 ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "wheel_win_percent", text))
        await state.clear()
        await message.answer(f"✅ احتمال برد گردونه روی {text}٪ تنظیم شد.", reply_markup=kb.wheel_settings_kb(db))

    @router.callback_query(F.data == "adm_wheel_edit_prizes")
    async def cb_admin_wheel_edit_prizes(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_prizes)
        await safe_edit(call, 
            "درصدهای تخفیف ممکن را با کاما جدا کرده و ارسال کنید (مثلاً: 10,20,30,50):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_prizes)
    async def process_wheel_prizes(message: Message, state: FSMContext):
        parts = [p.strip() for p in message.text.split(",")]
        if not all(p.isdigit() and 0 < int(p) <= 100 for p in parts) or not parts:
            await message.answer("فرمت اشتباه است. مثال درست: 10,20,30,50")
            return
        (await asyncio.to_thread(db.set_wheel_prizes, [int(p) for p in parts]))
        await state.clear()
        await message.answer("✅ لیست جوایز گردونه به‌روزرسانی شد.", reply_markup=kb.wheel_settings_kb(db))

    @router.callback_query(F.data == "adm_wheel_edit_expiry")
    async def cb_admin_wheel_edit_expiry(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_expiry)
        await safe_edit(call, 
            "کد جایزه چند ساعت اعتبار داشته باشد؟ (فقط عدد، مثلاً 24):", reply_markup=kb.admin_back_kb()
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_expiry)
    async def process_wheel_expiry(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "wheel_code_expiry_hours", text))
        await state.clear()
        await message.answer(f"✅ اعتبار کد جایزه روی {text} ساعت تنظیم شد.", reply_markup=kb.wheel_settings_kb(db))

    @router.callback_query(F.data == "adm_wheel_edit_cooldown")
    async def cb_admin_wheel_edit_cooldown(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_cooldown)
        await safe_edit(call, 
            "فاصله مجاز بین دو چرخش هر کاربر چند ساعت باشد؟ (فقط عدد، مثلاً 24):", reply_markup=kb.admin_back_kb()
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_cooldown)
    async def process_wheel_cooldown(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "wheel_cooldown_hours", text))
        await state.clear()
        await message.answer(f"✅ فاصله بین دو چرخش روی {text} ساعت تنظیم شد.", reply_markup=kb.wheel_settings_kb(db))

    # -------------------------------------------------------------------
    # یادآوری اتمام سرویس + کد تخفیف تشویقی تمدید
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_renewal_settings")
    async def cb_admin_renewal_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "🔔 یادآوری تمدید سرویس:", reply_markup=kb.renewal_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_stock_alert_settings")
    async def cb_admin_stock_alert_settings(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, 
            "📦 آستانه‌ی هشدار موجودی:\n\nوقتی موجودی یک محصول به این عدد یا کمتر برسد، همه‌ی ادمین‌ها یک‌بار پیام هشدار می‌گیرند.",
            reply_markup=kb.stock_alert_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_stock_alert_edit")
    async def cb_admin_stock_alert_edit(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminStockAlertSettings.waiting_threshold)
        await safe_edit(call, 
            "آستانه‌ی هشدار موجودی چند کانفیگ باشد؟ (فقط عدد، مثلاً 3):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminStockAlertSettings.waiting_threshold)
    async def process_stock_alert_threshold(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 0:
            await message.answer("لطفاً یک عدد صحیح غیرمنفی ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "low_stock_threshold", text))
        await state.clear()
        await message.answer(
            f"✅ آستانه‌ی هشدار موجودی روی {text} کانفیگ تنظیم شد.", reply_markup=kb.stock_alert_settings_kb(db)
        )

    # -------------------------------------------------------------------
    # ساخت کانفیگ شخصی: تنظیمات کلی + سرورهای پنل + قیمت‌گذاری بر اساس بازه
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_custom_config_settings")
    async def cb_admin_custom_config_settings(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call,
            "🛠 ساخت کانفیگ شخصی\n\n"
            "کاربران می‌توانند با تعیین نام، حجم و پرداخت متناسب، کاربر خودشان را مستقیماً "
            "روی یکی از سرورهای پنل زیر بسازند.",
            reply_markup=kb.custom_config_menu_kb(db, is_main_bot),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_custom_config_toggle")
    async def cb_admin_custom_config_toggle(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "custom_config_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "custom_config_enabled", "0" if current == "1" else "1"))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "custom_config_toggle", f"وضعیت جدید: {'0' if current == '1' else '1'}"))
        await safe_edit(call, "🛠 ساخت کانفیگ شخصی:", reply_markup=kb.custom_config_menu_kb(db, is_main_bot))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data == "adm_custom_config_edit_range")
    async def cb_admin_custom_config_edit_range(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCustomConfigSettings.waiting_min_gb)
        await safe_edit(call, "حداقل حجم مجاز چند گیگابایت باشد؟ (فقط عدد):", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminCustomConfigSettings.waiting_min_gb)
    async def process_custom_config_min_gb(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        await state.update_data(min_gb=text)
        await state.set_state(AdminCustomConfigSettings.waiting_max_gb)
        await message.answer("حداکثر حجم مجاز چند گیگابایت باشد؟ (فقط عدد):")

    @router.message(AdminCustomConfigSettings.waiting_max_gb)
    async def process_custom_config_max_gb(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        min_gb = int(data.get("min_gb", "0"))
        if not text.isdigit() or int(text) <= min_gb:
            await message.answer(f"لطفاً عددی بزرگ‌تر از حداقل ({min_gb}) ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "custom_config_min_gb", data["min_gb"]))
        (await asyncio.to_thread(db.set_setting, "custom_config_max_gb", text))
        await state.clear()
        await message.answer(
            f"✅ بازه‌ی حجم مجاز روی {data['min_gb']} تا {text} گیگابایت تنظیم شد.",
            reply_markup=kb.custom_config_menu_kb(db, is_main_bot),
        )

    async def deny_reseller_panel_access(call: CallbackQuery):
        await call.answer("⛔️ اتصال پنل VPN فقط از طریق بات اصلی مدیریت می‌شود.", show_alert=True)

    @router.callback_query(F.data == "adm_panel_servers")
    async def cb_admin_panel_servers(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "🖥 سرورهای پنل VPN متصل:", reply_markup=kb.panel_servers_list_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_panel_server_add")
    async def cb_admin_panel_server_add(call: CallbackQuery, state: FSMContext):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminAddPanelServer.waiting_name)
        await safe_edit(call, "یک نام دلخواه برای این سرور بفرست (مثلاً «سرور آلمان»):", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminAddPanelServer.waiting_name)
    async def process_panel_server_name(message: Message, state: FSMContext):
        await state.update_data(name=message.text.strip())
        await state.set_state(AdminAddPanelServer.waiting_type)
        await message.answer("نوع پنل را انتخاب کن:", reply_markup=kb.panel_type_select_kb())

    @router.callback_query(F.data.startswith("adm_panel_type:"), AdminAddPanelServer.waiting_type)
    async def cb_panel_server_type_selected(call: CallbackQuery, state: FSMContext):
        panel_type = call.data.split(":")[1]
        await state.update_data(panel_type=panel_type)
        await state.set_state(AdminAddPanelServer.waiting_url)
        await call.answer()
        await call.message.answer("آدرس API پنل را بفرست (مثلاً https://panel.example.com یا با پورت/مسیر مخصوص):")

    @router.message(AdminAddPanelServer.waiting_url)
    async def process_panel_server_url(message: Message, state: FSMContext):
        url = message.text.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            await message.answer("آدرس باید با http:// یا https:// شروع شود.")
            return
        await state.update_data(url=url)
        data = await state.get_data()
        if data.get("panel_type") == "3xui":
            # 3X-UI فقط با API Token احراز هویت می‌شود و اصلاً یوزرنیم ندارد؛
            # پس دیگر لازم نیست از ادمین یک مقدار الکی برای «نام کاربری» بپرسیم -
            # همینجا یک مقدار ثابت داخلی ذخیره می‌شود و مستقیم سراغ API Token می‌رویم.
            await state.update_data(username="3xui")
            await state.set_state(AdminAddPanelServer.waiting_password)
            await message.answer(
                "API Token پنل را بفرست (نه پسورد ادمین!):\n"
                "از داخل پنل 3X-UI برو به Settings ← Security ← API Token، یکی بساز و همان را اینجا بفرست.\n"
                "(نسخه‌های جدید 3X-UI لاگین با یوزر/پس را برای بات‌ها قبول نمی‌کنند و فقط با API Token کار می‌کنند.)"
            )
            return
        await state.set_state(AdminAddPanelServer.waiting_username)
        if data.get("panel_type") == "hiddify":
            await message.answer(
                "هیدیفای یوزر/پس ندارد؛ این فیلد استفاده نمی‌شود - فقط هر متنی (مثلاً «hiddify») بفرست:"
            )
        else:
            await message.answer("نام کاربری ادمین پنل را بفرست:")

    @router.message(AdminAddPanelServer.waiting_username)
    async def process_panel_server_username(message: Message, state: FSMContext):
        await state.update_data(username=message.text.strip())
        await state.set_state(AdminAddPanelServer.waiting_password)
        data = await state.get_data()
        if data.get("panel_type") == "hiddify":
            await message.answer("Hiddify-API-Key (همان UUID ادمین از داخل پنل: تنظیمات ← API) را بفرست:")
        else:
            await message.answer("رمز عبور ادمین پنل را بفرست:")

    @router.message(AdminAddPanelServer.waiting_password)
    async def process_panel_server_password(message: Message, state: FSMContext):
        await state.update_data(password=message.text.strip())
        try:
            await message.delete()
        except Exception:
            pass
        data = await state.get_data()

        if data["panel_type"] in INBOUND_SELECT_PANEL_TYPES:
            await message.answer("⏳ در حال دریافت لیست inbound از پنل...")
            server_id = (await asyncio.to_thread(db.add_panel_server, 
                name=data["name"], panel_type=data["panel_type"], api_url=data["url"],
                api_username=data["username"], api_password=data["password"],
            ))
            server = (await asyncio.to_thread(db.get_panel_server, server_id))
            try:
                provider = get_provider(server)
                inbounds = await provider.list_inbounds()
            except PanelError as e:
                (await asyncio.to_thread(db.delete_panel_server, server_id))
                await state.clear()
                await message.answer(f"⛔️ {e}\nسرور ذخیره نشد؛ دوباره از ابتدا تلاش کن.")
                return
            if not inbounds:
                (await asyncio.to_thread(db.delete_panel_server, server_id))
                await state.clear()
                await message.answer("⛔️ این پنل هیچ inbound ای ندارد. اول از داخل پنل یک inbound بساز.")
                return
            await state.update_data(server_id=server_id)
            await state.set_state(AdminAddPanelServer.waiting_inbound_select)
            await message.answer("کدام inbound برای ساخت کاربرهای جدید استفاده شود؟", reply_markup=kb.inbound_select_kb(inbounds))
            return

        if data["panel_type"] in SUB_BASE_URL_PANEL_TYPES:
            # مثل Hiddify: inbound لازم نیست، فقط یک آدرس Subscription جدا از آدرس ادمین
            server_id = (await asyncio.to_thread(db.add_panel_server, 
                name=data["name"], panel_type=data["panel_type"], api_url=data["url"],
                api_username=data["username"], api_password=data["password"],
            ))
            await state.update_data(server_id=server_id)
            await state.set_state(AdminAddPanelServer.waiting_sub_base_url)
            await message.answer(
                "آدرس عمومی Subscription پنل را بفرست (چون معمولاً با آدرس API ادمین فرق دارد؛ "
                "همان دامنه/مسیری که پنل برای لینک اشتراک کاربر نشان می‌دهد - بدون / انتهایی):"
            )
            return

        # پنل‌های خانواده‌ی PasarGuard/Marzban/Marzneshin: قالب از کاربر نمونه
        await state.set_state(AdminAddPanelServer.waiting_template_user)
        await message.answer(
            "یک نام کاربری که از قبل روی این پنل وجود دارد بفرست.\n"
            "تنظیمات پروتکل/گروه (یا سرویس) همین کاربر به‌عنوان قالب پیش‌فرض برای همه‌ی "
            "کانفیگ‌های شخصی جدید استفاده می‌شود."
        )

    @router.callback_query(F.data.startswith("adm_xui_inbound:"), AdminAddPanelServer.waiting_inbound_select)
    async def cb_panel_server_inbound_selected(call: CallbackQuery, state: FSMContext):
        inbound_id = int(call.data.split(":")[1])
        await state.update_data(inbound_id=inbound_id)
        await state.set_state(AdminAddPanelServer.waiting_sub_base_url)
        await call.answer()
        await call.message.answer(
            "آدرس پایه‌ی Subscription پنل را بفرست (همان چیزی که پنل موقع ساخت کاربر دستی نشانت می‌دهد، "
            "مثلاً https://domain:2096/sub یا https://domain/sub - بدون / انتهایی):"
        )

    @router.message(AdminAddPanelServer.waiting_sub_base_url)
    async def process_xui_sub_base_url(message: Message, state: FSMContext):
        url = message.text.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            await message.answer("آدرس باید با http:// یا https:// شروع شود.")
            return
        data = await state.get_data()
        if "inbound_id" in data:
            (await asyncio.to_thread(db.update_panel_server, data["server_id"], xui_inbound_id=data["inbound_id"], xui_sub_base_url=url))
        else:
            (await asyncio.to_thread(db.update_panel_server, data["server_id"], xui_sub_base_url=url))
        await state.clear()
        label = PANEL_TYPE_LABELS.get(data["panel_type"], data["panel_type"])
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_add", f"سرور «{data['name']}» ({label}, #{data['server_id']})"))
        await message.answer(
            f"✅ سرور «{data['name']}» ({label}) با موفقیت اضافه شد.",
            reply_markup=kb.panel_servers_list_kb(db),
        )

    @router.message(AdminAddPanelServer.waiting_template_user)
    async def process_panel_server_template_user(message: Message, state: FSMContext):
        data = await state.get_data()
        server_id = (await asyncio.to_thread(db.add_panel_server, 
            name=data["name"], panel_type=data["panel_type"], api_url=data["url"],
            api_username=data["username"], api_password=data["password"],
        ))
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        await message.answer("⏳ در حال دریافت قالب از پنل...")
        try:
            provider = get_provider(server)
            template = await provider.fetch_template_from_user(message.text.strip())
        except PanelError as e:
            (await asyncio.to_thread(db.delete_panel_server, server_id))
            await state.clear()
            await message.answer(f"⛔️ {e}\nسرور ذخیره نشد؛ دوباره از ابتدا تلاش کن.")
            return

        import json as _json
        (await asyncio.to_thread(db.update_panel_server, 
            server_id,
            group_ids=_json.dumps(template["group_ids"]),
            proxy_settings=_json.dumps(template["proxy_settings"]),
            template_username=message.text.strip(),
        ))
        await state.clear()
        label = PANEL_TYPE_LABELS.get(data["panel_type"], data["panel_type"])
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_add", f"سرور «{data['name']}» ({label}, #{server_id})"))
        await message.answer(
            f"✅ سرور «{data['name']}» ({label}) با قالب گرفته‌شده از «{message.text.strip()}» اضافه شد.",
            reply_markup=kb.panel_servers_list_kb(db),
        )

    @router.callback_query(F.data.startswith("adm_panel_server_view:"))
    async def cb_admin_panel_server_view(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_view")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        status = "🟢 فعال" if server["is_active"] else "🔴 غیرفعال"
        template_status = panel_server_readiness_text(server)
        usage_status = (
            f"مصرف: {'✅ خرید شخصی' if server['used_for_custom_config'] else '◻️ خرید شخصی'} | "
            f"{'✅ کانفیگ تست' if server['used_for_test_config'] else '◻️ کانفیگ تست'}"
        )
        text = (
            f"🖥 {server['name']}\n"
            f"نوع: {PANEL_TYPE_LABELS.get(server['panel_type'], server['panel_type'])}\n"
            f"آدرس: {server['api_url']}\n"
            f"وضعیت: {status}\n"
            f"{usage_status}\n"
            f"{template_status}"
        )
        await replace_admin_view(call, text, reply_markup=kb.panel_server_view_kb(server))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_panel_server_template:"))
    async def cb_admin_panel_server_template(call: CallbackQuery, state: FSMContext):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_template")
        if not (await asyncio.to_thread(db.get_panel_server, server_id)):
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminSetPanelTemplate.waiting_username)
        await safe_edit(call, "نام کاربری نمونه‌ی جدید (که روی پنل موجود است) را بفرست:", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminSetPanelTemplate.waiting_username)
    async def process_panel_server_template_update(message: Message, state: FSMContext):
        data = await state.get_data()
        server = (await asyncio.to_thread(db.get_panel_server, data["panel_server_id"]))
        if not server:
            await state.clear()
            await message.answer("سرور یافت نشد.")
            return
        await message.answer("⏳ در حال دریافت قالب از پنل...")
        try:
            provider = get_provider(server)
            template = await provider.fetch_template_from_user(message.text.strip())
        except PanelError as e:
            await message.answer(f"⛔️ {e}")
            return
        import json as _json
        (await asyncio.to_thread(db.update_panel_server, 
            server["id"],
            group_ids=_json.dumps(template["group_ids"]),
            proxy_settings=_json.dumps(template["proxy_settings"]),
            template_username=message.text.strip(),
        ))
        await state.clear()
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_template_update", f"سرور #{server['id']} ← «{message.text.strip()}»"))
        server = (await asyncio.to_thread(db.get_panel_server, server["id"]))
        await message.answer("✅ قالب جدید ذخیره شد.", reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_panel_server_suburl:"))
    async def cb_admin_panel_server_suburl(call: CallbackQuery, state: FSMContext):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_suburl")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminSetPanelSubUrl.waiting_url)
        current = server["xui_sub_base_url"] or "—"
        await safe_edit(
            call,
            f"آدرس فعلی Subscription:\n{current}\n\n"
            "آدرس جدید Subscription پنل را بفرست (همان چیزی که پنل موقع ساخت کاربر دستی نشانت می‌دهد، "
            "مثلاً https://domain:2096/sub یا https://domain/sub - بدون / انتهایی):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminSetPanelSubUrl.waiting_url)
    async def process_panel_server_suburl_update(message: Message, state: FSMContext):
        url = message.text.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            await message.answer("آدرس باید با http:// یا https:// شروع شود.")
            return
        data = await state.get_data()
        server = (await asyncio.to_thread(db.get_panel_server, data["panel_server_id"]))
        if not server:
            await state.clear()
            await message.answer("سرور یافت نشد.")
            return
        (await asyncio.to_thread(db.update_panel_server, server["id"], xui_sub_base_url=url))
        await state.clear()
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_suburl_update", f"سرور #{server['id']} ← {url}"))
        server = (await asyncio.to_thread(db.get_panel_server, server["id"]))
        await message.answer("✅ آدرس Subscription جدید ذخیره شد.", reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_panel_server_test:"))
    async def cb_admin_panel_server_test(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_test")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        await call.answer("در حال تست اتصال...")
        try:
            provider = get_provider(server)
            ok = await provider.test_connection()
        except PanelError:
            ok = False
        await call.message.answer("✅ اتصال به پنل موفق بود." if ok else "❌ اتصال به پنل ناموفق بود. اطلاعات را بررسی کن.")

    @router.callback_query(F.data.startswith("adm_panel_server_usage:"))
    async def cb_admin_panel_server_usage_toggle(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, kind, server_id_str = call.data.split(":")
        server_id = int(server_id_str)
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        field = {"custom": "used_for_custom_config", "test": "used_for_test_config", "reseller": "used_for_reseller"}.get(kind)
        if not field:
            await call.answer("نوع نامعتبر.", show_alert=True)
            return
        (await asyncio.to_thread(db.update_panel_server, server_id, **{field: 0 if server[field] else 1}))
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "panel_server_usage_toggle",
            f"سرور #{server_id} | {field} ← {server[field]}",
        ))
        status = "🟢 فعال" if server["is_active"] else "🔴 غیرفعال"
        template_status = panel_server_readiness_text(server)
        usage_status = (
            f"مصرف: {'✅ خرید شخصی' if server['used_for_custom_config'] else '◻️ خرید شخصی'} | "
            f"{'✅ کانفیگ تست' if server['used_for_test_config'] else '◻️ کانفیگ تست'} | "
            f"{'✅ نمایندگی' if server['used_for_reseller'] else '◻️ نمایندگی'}"
        )
        await safe_edit(call,
            f"🖥 {server['name']}\nنوع: {PANEL_TYPE_LABELS.get(server['panel_type'], server['panel_type'])}\nآدرس: {server['api_url']}\n"
            f"وضعیت: {status}\n{usage_status}\n{template_status}",
            reply_markup=kb.panel_server_view_kb(server),
        )
        await call.answer("تغییر کرد.")

    @router.callback_query(F.data.startswith("adm_panel_server_toggle:"))
    async def cb_admin_panel_server_toggle(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_toggle")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        (await asyncio.to_thread(db.update_panel_server, server_id, is_active=0 if server["is_active"] else 1))
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        await safe_edit(call,
            f"🖥 {server['name']}\nنوع: {PANEL_TYPE_LABELS.get(server['panel_type'], server['panel_type'])}\nآدرس: {server['api_url']}\n"
            f"وضعیت: {'🟢 فعال' if server['is_active'] else '🔴 غیرفعال'}",
            reply_markup=kb.panel_server_view_kb(server),
        )
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data.startswith("adm_panel_server_delete:"))
    async def cb_admin_panel_server_delete(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_delete")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        dependent = (await asyncio.to_thread(db.count_custom_configs_by_panel, server_id))
        if dependent:
            await safe_edit(
                call,
                f"⚠️ پنل «{server['name']}» {dependent} کانفیگ شخصی ثبت‌شده دارد.\n"
                "حذف کامل، رکورد این کانفیگ‌ها را هم برای همیشه پاک می‌کند و دیگر در "
                "لیست کانفیگ‌های کاربران و یادآوری‌های تمدید/حجم دیده نمی‌شوند "
                "(اتصال واقعی روی خود پنل VPN جداگانه است و با این کار قطع نمی‌شود).\n\n"
                "مطمئنید؟",
                reply_markup=kb.panel_server_delete_confirm_kb(server_id),
            )
            await call.answer()
            return
        (await asyncio.to_thread(db.delete_panel_server, server_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "panel_server_delete", f"سرور #{server_id}"))
        await replace_admin_view(call, "🖥 سرورهای پنل VPN متصل:", reply_markup=kb.panel_servers_list_kb(db))
        await call.answer("سرور حذف شد.")

    @router.callback_query(F.data.startswith("adm_panel_server_delete_force:"))
    async def cb_admin_panel_server_delete_force(call: CallbackQuery):
        if not (await asyncio.to_thread(db.is_full_access_bot, is_main_bot)):
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_delete_force")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer("سرور یافت نشد.", show_alert=True)
            return
        removed = (await asyncio.to_thread(db.delete_panel_server, server_id, force=True))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "panel_server_delete",
            f"سرور #{server_id} ({server['name']}) + {removed} کانفیگ شخصی مرتبط",
        ))
        await replace_admin_view(call, "🖥 سرورهای پنل VPN متصل:", reply_markup=kb.panel_servers_list_kb(db))
        await call.answer("سرور و کانفیگ‌های مرتبط حذف شدند.")

    @router.callback_query(F.data == "adm_pricing_tiers")
    async def cb_admin_pricing_tiers(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call,
            "💰 قیمت‌گذاری بر اساس بازه‌ی حجم:\n\n"
            "قیمت نهایی = کل حجم انتخابی کاربر × نرخ همان بازه‌ای که حجم داخلش قرار می‌گیرد "
            "(نه پلکانی/تصاعدی؛ یک نرخ ثابت برای کل حجم).",
            reply_markup=kb.pricing_tiers_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_pricing_tier_add")
    async def cb_admin_pricing_tier_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminAddPricingTier.waiting_from_gb)
        await safe_edit(call, "ابتدای این بازه چند گیگابایت باشد؟ (فقط عدد):", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminAddPricingTier.waiting_from_gb)
    async def process_pricing_tier_from(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        await state.update_data(from_gb=int(text))
        await state.set_state(AdminAddPricingTier.waiting_to_gb)
        await message.answer(
            "انتهای این بازه چند گیگابایت باشد؟ (فقط عدد)\n"
            "اگر می‌خواهی این آخرین بازه باشد (بدون سقف/تا بی‌نهایت)، عدد 0 بفرست."
        )

    @router.message(AdminAddPricingTier.waiting_to_gb)
    async def process_pricing_tier_to(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        if not text.isdigit():
            await message.answer("لطفاً فقط عدد صحیح ارسال کن (یا 0 برای بی‌نهایت).")
            return
        to_gb = None if int(text) == 0 else int(text)
        if to_gb is not None and to_gb <= data["from_gb"]:
            await message.answer(f"انتهای بازه باید بزرگ‌تر از ابتدای آن ({data['from_gb']}) باشد.")
            return
        await state.update_data(to_gb=to_gb)
        await state.set_state(AdminAddPricingTier.waiting_price)
        await message.answer("قیمت هر گیگابایت در این بازه چند تومان باشد؟ (فقط عدد):")

    @router.message(AdminAddPricingTier.waiting_price)
    async def process_pricing_tier_price(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        data = await state.get_data()
        (await asyncio.to_thread(db.add_pricing_tier, data["from_gb"], data.get("to_gb"), int(text)))
        await state.clear()
        to_label = data.get("to_gb") or "∞"
        (await asyncio.to_thread(db.log_admin_action, 
            message.from_user.id, "pricing_tier_add",
            f"بازه {data['from_gb']} تا {to_label} گیگ ← {int(text):,} تومان/گیگ",
        ))
        await message.answer(
            f"✅ بازه‌ی قیمت اضافه شد: {data['from_gb']} تا {to_label} گیگ ← {int(text):,} تومان/گیگ",
            reply_markup=kb.pricing_tiers_kb(db),
        )

    @router.callback_query(F.data.startswith("adm_pricing_tier_delete:"))
    async def cb_admin_pricing_tier_delete(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tier_id = callback_id(call.data, "adm_pricing_tier_delete")
        (await asyncio.to_thread(db.delete_pricing_tier, tier_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "pricing_tier_delete", f"بازه #{tier_id}"))
        await replace_admin_view(call, "💰 قیمت‌گذاری بر اساس بازه‌ی حجم:", reply_markup=kb.pricing_tiers_kb(db))
        await call.answer("بازه حذف شد.")

    @router.callback_query(F.data == "adm_reset_test_configs")
    async def cb_admin_reset_test_configs(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminResetTestConfig.waiting_message)
        await safe_edit(call,
            "پیامی که می‌خوای به کاربرانی که قبلاً کانفیگ تست گرفته‌اند ارسال بشه رو بفرست.\n"
            "(مثلاً: «🎉 کانفیگ تست دوباره برای شما فعال شد، از منوی اصلی دریافت کنید.»)\n\n"
            "بعد از این پیام، بازنشانی و ارسال شروع می‌شود.",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminResetTestConfig.waiting_message)
    async def process_reset_test_configs_message(message: Message, state: FSMContext, bot: Bot):
        text = message.text.strip()
        if not text:
            await message.answer("لطفاً یک متن معتبر ارسال کنید.")
            return
        await state.clear()
        user_ids = (await asyncio.to_thread(db.reset_all_test_usage))
        (await asyncio.to_thread(db.log_admin_action, 
            message.from_user.id, "reset_test_configs",
            f"بازنشانی کانفیگ تست برای {len(user_ids)} کاربر",
        ))
        status_msg = await message.answer(f"⏳ در حال ارسال پیام به {len(user_ids)} کاربر...")
        sent = 0
        for uid in user_ids:
            try:
                await bot.send_message(uid, text)
                sent += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"✅ کانفیگ تست برای {len(user_ids)} کاربر بازنشانی شد و پیام به {sent} نفر ارسال شد.",
            reply_markup=kb.admin_test_menu_kb(db, is_main_bot),
        )

    @router.callback_query(F.data == "adm_renewal_toggle")
    async def cb_admin_renewal_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "renewal_reminder_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "renewal_reminder_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, "🔔 یادآوری تمدید سرویس:", reply_markup=kb.renewal_settings_kb(db))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data == "adm_renewal_edit_days")
    async def cb_admin_renewal_edit_days(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalSettings.waiting_days_before)
        await safe_edit(call, 
            "چند روز قبل از اتمام سرویس، یادآوری ارسال شود؟ (فقط عدد، مثلاً 5):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminRenewalSettings.waiting_days_before)
    async def process_renewal_days(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "renewal_reminder_days_before", text))
        await state.clear()
        await message.answer(
            f"✅ یادآوری روی {text} روز قبل از اتمام سرویس تنظیم شد.", reply_markup=kb.renewal_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_renewal_edit_percent")
    async def cb_admin_renewal_edit_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalSettings.waiting_percent)
        await safe_edit(call, 
            "درصد تخفیف کد تشویقی تمدید چقدر باشد؟ (عددی بین 1 تا 100، مثلاً 20):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminRenewalSettings.waiting_percent)
    async def process_renewal_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 < int(text) <= 100):
            await message.answer("لطفاً یک عدد بین 1 تا 100 ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "renewal_discount_percent", text))
        await state.clear()
        await message.answer(f"✅ درصد تخفیف کد تشویقی روی {text}٪ تنظیم شد.", reply_markup=kb.renewal_settings_kb(db))

    @router.callback_query(F.data == "adm_renewal_edit_hours")
    async def cb_admin_renewal_edit_hours(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalSettings.waiting_expiry_hours)
        await safe_edit(call, 
            "کد تخفیف تشویقی چند ساعت اعتبار داشته باشد؟ (فقط عدد، مثلاً 24):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminRenewalSettings.waiting_expiry_hours)
    async def process_renewal_hours(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "renewal_discount_expiry_hours", text))
        await state.clear()
        await message.answer(
            f"✅ اعتبار کد تخفیف تشویقی روی {text} ساعت تنظیم شد.", reply_markup=kb.renewal_settings_kb(db)
        )

    # -------------------------------------------------------------------
    # یادآوری اتمام حجم + کد تخفیف تشویقی تمدید (مستقل از یادآوری تاریخ انقضا)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_volume_reminder_settings")
    async def cb_admin_volume_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "📉 یادآوری اتمام حجم:", reply_markup=kb.volume_reminder_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_volume_toggle")
    async def cb_admin_volume_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "volume_reminder_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "volume_reminder_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, "📉 یادآوری اتمام حجم:", reply_markup=kb.volume_reminder_settings_kb(db))
        await call.answer("وضعیت تغییر کرد.")

    @router.callback_query(F.data == "adm_volume_toggle_mode")
    async def cb_admin_volume_toggle_mode(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "volume_reminder_mode", "percent"))
        (await asyncio.to_thread(db.set_setting, "volume_reminder_mode", "gb" if current == "percent" else "percent"))
        await safe_edit(call, "📉 یادآوری اتمام حجم:", reply_markup=kb.volume_reminder_settings_kb(db))
        await call.answer("مبنای آستانه تغییر کرد.")

    @router.callback_query(F.data == "adm_volume_edit_percent")
    async def cb_admin_volume_edit_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_percent)
        await safe_edit(call,
            "وقتی چند درصد از حجم مصرف شد، یادآوری ارسال شود؟ (عددی بین 1 تا 99، مثلاً 80):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminVolumeReminderSettings.waiting_percent)
    async def process_volume_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 < int(text) < 100):
            await message.answer("لطفاً یک عدد بین 1 تا 99 ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "volume_reminder_percent", text))
        await state.clear()
        await message.answer(
            f"✅ آستانه‌ی یادآوری حجم روی {text}٪ مصرف تنظیم شد.", reply_markup=kb.volume_reminder_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_volume_edit_gb")
    async def cb_admin_volume_edit_gb(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_gb_left)
        await safe_edit(call,
            "وقتی چند گیگابایت حجم باقی‌مانده شد، یادآوری ارسال شود؟ (عدد، مثلاً 2 یا 1.5):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminVolumeReminderSettings.waiting_gb_left)
    async def process_volume_gb(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", ".")
        try:
            value = float(text)
            if value <= 0:
                raise ValueError
        except ValueError:
            await message.answer("لطفاً یک عدد مثبت ارسال کنید (مثلاً 2 یا 1.5).")
            return
        (await asyncio.to_thread(db.set_setting, "volume_reminder_gb_left", str(value)))
        await state.clear()
        await message.answer(
            f"✅ آستانه‌ی یادآوری حجم روی {value} گیگ باقی‌مانده تنظیم شد.", reply_markup=kb.volume_reminder_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_volume_edit_discount_percent")
    async def cb_admin_volume_edit_discount_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_discount_percent)
        await safe_edit(call,
            "درصد تخفیف کد تشویقی اتمام حجم چقدر باشد؟ (عددی بین 1 تا 100، مثلاً 20):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminVolumeReminderSettings.waiting_discount_percent)
    async def process_volume_discount_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 < int(text) <= 100):
            await message.answer("لطفاً یک عدد بین 1 تا 100 ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "volume_discount_percent", text))
        await state.clear()
        await message.answer(f"✅ درصد تخفیف کد تشویقی روی {text}٪ تنظیم شد.", reply_markup=kb.volume_reminder_settings_kb(db))

    @router.callback_query(F.data == "adm_volume_edit_discount_hours")
    async def cb_admin_volume_edit_discount_hours(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_discount_hours)
        await safe_edit(call,
            "کد تخفیف تشویقی اتمام حجم چند ساعت اعتبار داشته باشد؟ (فقط عدد، مثلاً 24):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminVolumeReminderSettings.waiting_discount_hours)
    async def process_volume_discount_hours(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("لطفاً یک عدد صحیح مثبت ارسال کنید.")
            return
        (await asyncio.to_thread(db.set_setting, "volume_discount_expiry_hours", text))
        await state.clear()
        await message.answer(
            f"✅ اعتبار کد تخفیف تشویقی روی {text} ساعت تنظیم شد.", reply_markup=kb.volume_reminder_settings_kb(db)
        )

    # -------------------------------------------------------------------
    # مدیریت بات‌های نمایندگی (فقط در بات اصلی)
    # هر نماینده توکن بات خودش را می‌دهد؛ سیستم یک بات کاملاً مستقل با
    # دیتابیس جدا (شامل تمام امکانات: تست، تخفیف، زیرمجموعه‌گیری، کیف پول)
    # برایش راه‌اندازی می‌کند.
    # -------------------------------------------------------------------

    if is_main_bot:

        @router.callback_query(F.data == "adm_resellers_menu")
        async def cb_admin_resellers_menu(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bots = (await asyncio.to_thread(db.list_reseller_bots))
            await replace_admin_view(call, "🏪 مدیریت بات‌های نمایندگی:", reply_markup=kb.resellers_kb(bots))
            await call.answer()

        @router.callback_query(F.data.startswith("adm_resbot_toggle:"))
        async def cb_admin_resbot_toggle(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_toggle")
            if bot_id is None:
                await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
                return
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
            if not reseller_bot:
                return await call.answer("یافت نشد.", show_alert=True)

            (await asyncio.to_thread(db.toggle_reseller_bot, bot_id))
            updated = (await asyncio.to_thread(db.get_reseller_bot, bot_id))

            if bot_manager:
                if updated["is_active"]:
                    await bot_manager.start_bot(
                        updated["bot_token"], resolve_db_path(updated["db_path"]), updated["owner_telegram_id"],
                        is_main_bot=False,
                    )
                else:
                    await bot_manager.stop_bot(updated["bot_token"])

            bots = (await asyncio.to_thread(db.list_reseller_bots))
            await safe_edit(call, "🏪 مدیریت بات‌های نمایندگی:", reply_markup=kb.resellers_kb(bots))
            await call.answer("وضعیت تغییر کرد و اعمال شد.")

        @router.callback_query(F.data.startswith("adm_resbot_level:"))
        async def cb_admin_resbot_level(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_level")
            if bot_id is None:
                await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
                return
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
            if not reseller_bot:
                return await call.answer("یافت نشد.", show_alert=True)

            current_level = reseller_bot["reseller_level"] if "reseller_level" in reseller_bot.keys() else 2
            new_level = 2 if current_level == 1 else 1
            (await asyncio.to_thread(db.set_reseller_level, bot_id, new_level))

            try:
                reseller_db = Database(resolve_db_path(reseller_bot["db_path"]))
                (await asyncio.to_thread(reseller_db.set_setting, "reseller_level", str(new_level)))
                if new_level == 2:
                    (await asyncio.to_thread(reseller_db.set_setting, "custom_config_enabled", "0"))
            except Exception:
                pass

            bots = (await asyncio.to_thread(db.list_reseller_bots))
            level_label = "کامل" if new_level == 1 else "سطح ۲ (محدود)"
            await safe_edit(call, f"🏪 مدیریت بات‌های نمایندگی:", reply_markup=kb.resellers_kb(bots))
            await call.answer(f"سطح این نمایندگی به «{level_label}» تغییر کرد.")

        @router.callback_query(F.data.startswith("adm_resbot_webpanel:"))
        async def cb_admin_resbot_webpanel(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_webpanel")
            if bot_id is None:
                await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
                return
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
            if not reseller_bot:
                return await call.answer("یافت نشد.", show_alert=True)

            level = reseller_bot["reseller_level"] if "reseller_level" in reseller_bot.keys() else 2
            if level != 1:
                return await call.answer("پنل وب فقط برای نمایندگی «کامل» قابل فعال‌سازی است.", show_alert=True)

            already_enabled = bool(reseller_bot["web_panel_enabled"]) if "web_panel_enabled" in reseller_bot.keys() else False
            if already_enabled:
                await replace_admin_view(
                    call,
                    "🌐 پنل وب این نماینده فعال است.\n\n"
                    "اگر لینک راه‌اندازی را گم کرده یا نیاز به لینک جدید دارید، از دکمه‌ی زیر استفاده کنید.",
                    reply_markup=kb.resbot_webpanel_kb(bot_id),
                )
                return await call.answer()

            (await asyncio.to_thread(db.enable_reseller_web_panel, bot_id))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "reseller_webpanel_enable", f"نماینده #{bot_id} (@{reseller_bot['bot_username'] or ''})",
            ))
            await call.answer("پنل وب فعال شد.")

            if not _get_admin_panel_url(db):
                await state.set_state(AdminSetPanelDomain.waiting_url)
                await state.update_data(pending_webpanel_bot_id=bot_id)
                await call.message.answer(
                    "🌐 پنل وب این نماینده فعال شد، ولی هنوز آدرس پنل مدیریت وب رو بهم نگفتی.\n\n"
                    "فقط همین یک‌بار، آدرس دامنه‌ی پنل مدیریتت رو بفرست (با https://)، مثلاً:\n"
                    "https://panel.example.com\n\n"
                    "بعدش خودم لینک راه‌اندازی رو می‌سازم و مستقیم برای نماینده می‌فرستم؛ "
                    "دیگه لازم نیست هیچ‌جا دستی چیزی تنظیم کنی."
                )
                return

            await _deliver_webpanel_link(db, call.message, call.from_user.id, bot_id)

        @router.callback_query(F.data.startswith("adm_resbot_webpanel_loginlink:"))
        async def cb_admin_resbot_webpanel_loginlink(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_webpanel_loginlink")
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id)) if bot_id is not None else None
            if not reseller_bot:
                return await call.answer("یافت نشد.", show_alert=True)

            panel_url = _get_admin_panel_url(db)
            if not panel_url:
                return await call.answer("هنوز آدرس پنل مدیریت وب تنظیم نشده.", show_alert=True)

            b_value = reseller_bot["link_slug"] or str(bot_id)
            login_link = f"{panel_url}/?b={b_value}"

            await call.message.answer(
                "🔗 لینک ثابت ورود پنل وب این نماینده:\n\n"
                f"{login_link}\n\n"
                "این لینک (بر خلاف لینک راه‌اندازی) چندبارمصرف است؛ نماینده هر بار با همین لینک "
                "و یوزرنیم/پسوردی که خودش موقع راه‌اندازی ساخته وارد پنلش می‌شود. بهتر است "
                "نماینده این لینک را بوکمارک کند.",
                reply_markup=kb.resbot_webpanel_kb(bot_id),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("adm_resbot_webpanel_regen:"))
        async def cb_admin_resbot_webpanel_regen(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_webpanel_regen")
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id)) if bot_id is not None else None
            if not reseller_bot:
                return await call.answer("یافت نشد.", show_alert=True)

            (await asyncio.to_thread(db.regenerate_reseller_web_panel_token, bot_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "reseller_webpanel_regen", f"نماینده #{bot_id}"))
            await call.answer("توکن جدید ساخته شد.")

            if not _get_admin_panel_url(db):
                await state.set_state(AdminSetPanelDomain.waiting_url)
                await state.update_data(pending_webpanel_bot_id=bot_id)
                await call.message.answer(
                    "🔁 توکن راه‌اندازی جدید ساخته شد، ولی هنوز آدرس پنل مدیریت وب رو بهم نگفتی.\n\n"
                    "آدرس دامنه‌ی پنل مدیریتت رو بفرست (با https://)، بعدش خودم لینک رو می‌سازم و می‌فرستم:"
                )
                return

            await _deliver_webpanel_link(db, call.message, call.from_user.id, bot_id)

        @router.callback_query(F.data.startswith("adm_resbot_webpanel_off:"))
        async def cb_admin_resbot_webpanel_off(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_webpanel_off")
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id)) if bot_id is not None else None
            if not reseller_bot:
                return await call.answer("یافت نشد.", show_alert=True)

            (await asyncio.to_thread(db.disable_reseller_web_panel, bot_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "reseller_webpanel_disable", f"نماینده #{bot_id}"))
            bots = (await asyncio.to_thread(db.list_reseller_bots))
            await safe_edit(call, "⛔️ پنل وب این نماینده غیرفعال شد (نشست‌های فعلی هم دیگر کار نمی‌کنند).\n\n🏪 مدیریت بات‌های نمایندگی:", reply_markup=kb.resellers_kb(bots))
            await call.answer("غیرفعال شد.")

        @router.callback_query(F.data == "adm_set_panel_domain")
        async def cb_admin_set_panel_domain(call: CallbackQuery, state: FSMContext):
            """تنظیم/تغییر آدرس پنل مدیریت وب، مستقل از فعالسازی یک نماینده‌ی خاص -
            هر وقت خودت بخوای می‌تونی از همین دکمه دامنه رو عوض کنی."""
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            await state.set_state(AdminSetPanelDomain.waiting_url)
            await state.update_data(pending_webpanel_bot_id=None)
            current = _get_admin_panel_url(db)
            hint = f"\n\nآدرس فعلی: {current}" if current else "\n\nهنوز چیزی تنظیم نشده."
            await call.answer()
            await call.message.answer(
                "آدرس دامنه‌ی پنل مدیریت وب رو بفرست (با https://)، مثلاً:\nhttps://panel.example.com" + hint
            )

        @router.message(AdminSetPanelDomain.waiting_url)
        async def process_admin_panel_domain(message: Message, state: FSMContext):
            url = (message.text or "").strip().rstrip("/")
            if not url.startswith("http://") and not url.startswith("https://"):
                await message.answer("آدرس باید با http:// یا https:// شروع بشه. دوباره بفرست:")
                return

            (await asyncio.to_thread(db.set_setting, "admin_panel_url", url))
            data = await state.get_data()
            pending_bot_id = data.get("pending_webpanel_bot_id")
            await state.clear()
            await message.answer(f"✅ آدرس پنل مدیریت ذخیره شد: {url}\nهر وقت بخوای می‌تونی از همین‌جا («⚙️ آدرس پنل مدیریت») عوضش کنی.")

            if pending_bot_id:
                await _deliver_webpanel_link(db, message, message.from_user.id, pending_bot_id)

        @router.callback_query(F.data.startswith("adm_resbot_del:"))
        async def cb_admin_resbot_del(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_del")
            if bot_id is None:
                await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
                return
            await safe_edit(call,
                "⚠️ آیا از حذف این بات نمایندگی مطمئنی؟\n\nدیتابیس آن (شامل کاربران، کیف پول، کانفیگ‌ها) پاک شود یا فقط برای احتیاط نگه داشته شود؟",
                reply_markup=kb.resbot_del_confirm_kb(bot_id),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("adm_resbot_delc:"))
        async def cb_admin_resbot_del_confirm(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            parts = call.data.split(":")
            if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("0", "1"):
                await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
                return
            bot_id, purge = int(parts[1]), parts[2] == "1"
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
            if reseller_bot and bot_manager:
                await bot_manager.stop_bot(reseller_bot["bot_token"])
            (await asyncio.to_thread(db.delete_reseller_bot, bot_id))
            if reseller_bot:
                # پرچم نماینده/اعتبار/پنل کاربر مالک در دیتابیس اصلی هم پاک شود؛
                # وگرنه او همچنان «نماینده» شناخته می‌شود و نمی‌تواند دوباره
                # درخواست نمایندگی بدهد.
                (await asyncio.to_thread(db.purge_reseller_leftovers, reseller_bot["owner_telegram_id"]))

            db_purged = False
            if purge and reseller_bot:
                resolved_path = resolve_db_path(reseller_bot["db_path"])
                try:
                    if os.path.exists(resolved_path):
                        os.remove(resolved_path)
                        db_purged = True
                except OSError:
                    logger.exception("پاک‌کردن فایل دیتابیس نماینده ناموفق بود: %s", resolved_path)

            bots = (await asyncio.to_thread(db.list_reseller_bots))
            note = "⚠️ بات متوقف و حذف شد. وضعیت نمایندگی مالک هم در بات اصلی پاک شد."
            note += " دیتابیسش هم پاک شد." if db_purged else " فایل دیتابیسش برای احتیاط پاک نشد."
            await safe_edit(call,
                f"🏪 مدیریت بات‌های نمایندگی:\n\n{note}",
                reply_markup=kb.resellers_kb(bots),
            )
            await call.answer("بات نمایندگی حذف شد.")

        @router.callback_query(F.data == "adm_reseller_orphans")
        async def cb_admin_reseller_orphans(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            orphans = (await asyncio.to_thread(db.list_orphaned_reseller_users))
            if not orphans:
                await call.answer("موردی پیدا نشد؛ هیچ داده‌ی باقی‌مانده‌ای وجود ندارد.", show_alert=True)
                return
            text = (
                "🧹 داده‌های باقی‌مانده‌ی نمایندگی\n\n"
                "این کاربرها پرچم/اعتبار/پنل نمایندگی روی حسابشان مانده، "
                "درحالی‌که هیچ بات نمایندگی‌ای (حتی غیرفعال) برایشان ثبت نیست؛ "
                "معمولاً یعنی قبلاً نماینده بوده‌اند و بات‌شان حذف شده اما رد پایش پاک نشده. "
                "پاکسازی یعنی پرچم نماینده، اعتبار حجمی و پنل اختصاصی‌شان صفر می‌شود تا بتوانند "
                "دوباره درخواست نمایندگی بدهند."
            )
            await replace_admin_view(call, text, reply_markup=kb.reseller_orphans_kb(orphans))
            await call.answer()

        @router.callback_query(F.data.startswith("adm_reseller_orphan_purge:"))
        async def cb_admin_reseller_orphan_purge(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = callback_id(call.data, "adm_reseller_orphan_purge")
            if target_id is None:
                await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
                return
            (await asyncio.to_thread(db.purge_reseller_leftovers, target_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "reseller_orphan_purge", f"کاربر {target_id}"))
            orphans = (await asyncio.to_thread(db.list_orphaned_reseller_users))
            if orphans:
                await safe_edit(
                    call,
                    "🧹 داده‌های باقی‌مانده‌ی نمایندگی\n\n✅ کاربر پاکسازی شد.",
                    reply_markup=kb.reseller_orphans_kb(orphans),
                )
            else:
                await safe_edit(
                    call,
                    "🧹 داده‌های باقی‌مانده‌ی نمایندگی\n\n✅ کاربر پاکسازی شد. دیگر موردی باقی نمانده.",
                    reply_markup=kb.admin_back_kb("adm_resellers_menu"),
                )
            await call.answer("پاکسازی شد.")

        @router.callback_query(F.data == "adm_orphan_db_files")
        async def cb_admin_orphan_db_files(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            orphan_files = _find_orphan_reseller_db_files()
            if not orphan_files:
                await call.answer("فایل دیتابیس یتیمی روی دیسک پیدا نشد.", show_alert=True)
                return
            text = (
                "🗃 فایل‌های دیتابیس یتیم\n\n"
                "این فایل‌های .db داخل پوشه‌ی reseller_dbs روی دیسک هستند ولی هیچ بات "
                "نمایندگی‌ای (حتی حذف‌شده) در جدول reseller_bots به آن‌ها اشاره نمی‌کند؛ "
                "معمولاً یعنی وقتی نماینده حذف شده، گزینه‌ی «فقط حذف (دیتابیس نگه داشته شود)» "
                "زده شده. حذف این فایل‌ها غیرقابل بازگشت است."
            )
            await replace_admin_view(call, text, reply_markup=kb.orphan_db_files_kb(orphan_files))
            await call.answer()

        @router.callback_query(F.data.startswith("adm_orphan_db_del:"))
        async def cb_admin_orphan_db_del(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            import urllib.parse
            raw = call.data.split(":", 1)[1] if ":" in call.data else ""
            fname = urllib.parse.unquote(raw)

            # ضدضربه: فقط اجازه‌ی حذف فایل مستقیماً داخل پوشه‌ی reseller_dbs را بده،
            # نه هیچ مسیر دیگری (جلوگیری از path traversal روی callback_data دستکاری‌شده)
            if not fname or os.sep in fname or "/" in fname or ".." in fname or not fname.endswith(".db"):
                await call.answer("❌ نام فایل نامعتبر است.", show_alert=True)
                return

            target_path = os.path.join(RESELLER_DBS_DIR, fname)
            still_orphan = fname in _find_orphan_reseller_db_files()
            if not still_orphan or not os.path.exists(target_path):
                await call.answer("این فایل دیگر یتیم نیست یا وجود ندارد.", show_alert=True)
            else:
                try:
                    os.remove(target_path)
                    (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "orphan_db_file_delete", fname))
                except OSError:
                    logger.exception("پاک‌کردن فایل دیتابیس یتیم ناموفق بود: %s", target_path)
                    await call.answer("❌ حذف فایل با خطا مواجه شد.", show_alert=True)
                    return

            orphan_files = _find_orphan_reseller_db_files()
            if orphan_files:
                await safe_edit(
                    call,
                    f"🗃 فایل‌های دیتابیس یتیم\n\n✅ فایل «{fname}» پاک شد.",
                    reply_markup=kb.orphan_db_files_kb(orphan_files),
                )
            else:
                await safe_edit(
                    call,
                    f"🗃 فایل‌های دیتابیس یتیم\n\n✅ فایل «{fname}» پاک شد. دیگر فایل یتیمی باقی نمانده.",
                    reply_markup=kb.admin_back_kb("adm_resellers_menu"),
                )
            await call.answer("فایل حذف شد.")

        @router.callback_query(F.data == "adm_resbot_add")
        async def cb_admin_resbot_add(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            await state.set_state(AdminAddResellerBot.waiting_token)
            await safe_edit(call, 
                "توکن بات نماینده را ارسال کنید (همانی که از @BotFather گرفته):",
                reply_markup=kb.admin_back_kb(),
            )
            await call.answer()

        @router.message(AdminAddResellerBot.waiting_token)
        async def process_resbot_token(message: Message, state: FSMContext):
            token = message.text.strip()

            existing = None
            with_conn_check = None
            for b in (await asyncio.to_thread(db.list_reseller_bots)):
                if b["bot_token"] == token:
                    existing = b
                    break
            if existing:
                await message.answer("⛔️ این توکن قبلاً ثبت شده است.")
                return

            await message.answer("⏳ در حال بررسی اعتبار توکن...")
            temp_bot = Bot(token=token)
            try:
                me = await temp_bot.get_me()
            except Exception:
                await message.answer("❌ این توکن معتبر نیست. دوباره بررسی و ارسال کنید:")
                await temp_bot.session.close()
                return
            await temp_bot.session.close()

            await state.update_data(resbot_token=token, resbot_username=me.username)
            await state.set_state(AdminAddResellerBot.waiting_owner_id)
            await message.answer(
                f"✅ توکن معتبر است: @{me.username}\n\n"
                f"حالا آیدی عددی نماینده (مالک این بات) را ارسال کنید:"
            )

        @router.message(AdminAddResellerBot.waiting_owner_id)
        async def process_resbot_owner_id(message: Message, state: FSMContext):
            if not message.text.strip().isdigit():
                await message.answer("لطفاً فقط آیدی عددی ارسال کنید.")
                return
            await state.update_data(resbot_owner_id=int(message.text.strip()))
            await state.set_state(AdminAddResellerBot.waiting_owner_name)
            await message.answer("یک نام برای این نماینده وارد کنید (فقط برای نمایش در پنل مدیریت):")

        @router.message(AdminAddResellerBot.waiting_owner_name)
        async def process_resbot_owner_name(message: Message, state: FSMContext):
            await state.update_data(resbot_owner_name=message.text.strip())
            await state.set_state(AdminAddResellerBot.waiting_level)
            await message.answer(
                "سطح این نمایندگی چیست؟\n\n"
                "1️⃣ نمایندگی کامل: به همه‌ی امکانات (پنل VPN شخصی، ساخت کانفیگ دستی، بانک لینک) دسترسی کامل دارد.\n"
                "2️⃣ نمایندگی سطح ۲: فقط می‌تواند از اعتبار حجمی خودش محصول خودکار بفروشد؛ به پنل و ساخت کانفیگ دستی دسترسی ندارد.\n\n"
                "فقط عدد 1 یا 2 را ارسال کنید:"
            )

        @router.message(AdminAddResellerBot.waiting_level)
        async def process_resbot_level(message: Message, state: FSMContext):
            text = message.text.strip()
            if text not in ("1", "2"):
                await message.answer("لطفاً فقط عدد 1 یا 2 را ارسال کنید.")
                return
            level = int(text)
            data = await state.get_data()
            token = data["resbot_token"]
            username = data["resbot_username"]
            owner_id = data["resbot_owner_id"]
            owner_name = data["resbot_owner_name"]

            os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
            db_path = os.path.join(RESELLER_DBS_DIR, f"{username}.db")

            reseller_id = (await asyncio.to_thread(db.register_reseller_bot, token, username, owner_id, owner_name, db_path, reseller_level=level))

            started = False
            if bot_manager:
                started = await bot_manager.start_bot(token, db_path, owner_id, is_main_bot=False)

            # دیتابیس همین نماینده باید بداند شناسه‌ی خودش در جدول reseller_bots (بات اصلی) چیست
            # تا بتواند لینک مینی‌اپ اختصاصی خودش را بسازد (?b=<reseller_id>)، و سطح دسترسی‌اش چیست
            reseller_db = Database(db_path)
            (await asyncio.to_thread(reseller_db.init_db, owner_id=owner_id))
            (await asyncio.to_thread(reseller_db.set_setting, "miniapp_tenant_id", str(reseller_id)))
            (await asyncio.to_thread(reseller_db.set_setting, "reseller_level", str(level)))
            if level == 2:
                # نمایندگی سطح ۲ نباید هرگز حالت کانفیگ دستی/شخصی روشن داشته باشد
                (await asyncio.to_thread(reseller_db.set_setting, "custom_config_enabled", "0"))

            await state.clear()
            status_text = "✅ بات نمایندگی راه‌اندازی و همین الان روشن شد." if started else \
                "⚠️ بات ثبت شد ولی راه‌اندازی زنده انجام نشد؛ با ری‌استارت سرویس اصلی خودکار روشن می‌شود."
            level_label = "کامل" if level == 1 else "سطح ۲ (محدود)"
            await message.answer(
                f"{status_text}\n\n"
                f"🤖 بات: @{username}\n"
                f"🏷 سطح نمایندگی: {level_label}\n"
                f"👤 نماینده: {owner_name} ({owner_id})\n\n"
                f"این بات کاملاً مستقل است و تمام امکانات (کد تخفیف، زیرمجموعه‌گیری، کیف پول، کانفیگ تست) را "
                f"از صفر و جدا از بات اصلی دارد. نماینده باید با /start به بات خودش (@{username}) وارد شود.",
                reply_markup=kb.resellers_kb((await asyncio.to_thread(db.list_reseller_bots))),
            )

        # ---------------------------------------------------------------
        # درخواست خودکار نمایندگی سطح ۲ (بررسی، تعیین هزینه، تایید پرداخت)
        # ---------------------------------------------------------------

        @router.callback_query(F.data.startswith("resreq_approve:"))
        async def cb_resreq_approve(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or req["status"] != "pending_review":
                await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
                return
            panels = (await asyncio.to_thread(db.get_panel_servers, active_only=True))
            await call.message.answer(
                "🔗 این نماینده روی کدام پنل کانفیگ بسازد؟\n(نماینده هیچ‌وقت آدرس/مشخصات این پنل را نمی‌بیند.)",
                reply_markup=kb.reseller_request_panel_pick_kb(request_id, panels),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("resreq_panel:"))
        async def cb_resreq_panel(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            _, request_id_str, panel_id_str = call.data.split(":")
            request_id, panel_id = int(request_id_str), int(panel_id_str)
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or req["status"] != "pending_review":
                await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
                return
            await state.update_data(resreq_request_id=request_id, resreq_panel_id=panel_id or None)
            await state.set_state(AdminResellerRequestFlow.waiting_price)
            await call.message.answer(f"💰 هزینه‌ی این نمایندگی (به تومان) چقدر باشد؟ فقط عدد ارسال کنید:")
            await call.answer()

        @router.message(AdminResellerRequestFlow.waiting_price)
        async def process_resreq_price(message: Message, state: FSMContext, bot: Bot):
            text = (message.text or "").strip().replace(",", "")
            if not text.isdigit() or int(text) <= 0:
                await message.answer("لطفاً یک عدد صحیح و مثبت ارسال کنید.")
                return
            price = int(text)
            data = await state.get_data()
            request_id, panel_id = data.get("resreq_request_id"), data.get("resreq_panel_id")
            req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
            await state.clear()
            if not req or req["status"] != "pending_review":
                await message.answer("این درخواست دیگر معتبر نیست.")
                return

            (await asyncio.to_thread(db.quote_reseller_request, request_id, price, panel_id, message.from_user.id))
            (await asyncio.to_thread(db.log_admin_action, 
                message.from_user.id, "reseller_request_quote",
                f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {price:,}",
            ))
            await message.answer(f"✅ هزینه برای کاربر ارسال شد ({price:,} تومان).")
            try:
                await bot.send_message(
                    req["user_id"],
                    f"🏪 درخواست نمایندگی #{request_id} شما تایید شد!\n\n"
                    f"💰 هزینه‌ی نمایندگی: {price:,} تومان\n"
                    f"📦 حجم: {req['volume_gb']:,} گیگ\n\n"
                    f"در صورت موافقت روی «پرداخت می‌کنم» بزنید:",
                    reply_markup=kb.reseller_request_pay_kb(request_id),
                )
            except Exception:
                pass

        @router.callback_query(F.data.startswith("resreq_reject:"))
        async def cb_resreq_reject(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or req["status"] != "pending_review":
                await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
                return
            await state.update_data(resreq_reject_id=request_id, resreq_reject_status="rejected")
            await state.set_state(AdminResellerRequestFlow.waiting_reject_reason)
            await call.message.answer("دلیل رد درخواست را بنویسید (برای کاربر ارسال می‌شود):")
            await call.answer()

        @router.callback_query(F.data.startswith("resreq_payreject:"))
        async def cb_resreq_payreject(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or req["status"] != "awaiting_payment_review":
                await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
                return
            await state.update_data(resreq_reject_id=request_id, resreq_reject_status="payment_rejected")
            await state.set_state(AdminResellerRequestFlow.waiting_reject_reason)
            await call.message.answer("دلیل رد پرداخت را بنویسید (برای کاربر ارسال می‌شود):")
            await call.answer()

        @router.message(AdminResellerRequestFlow.waiting_reject_reason)
        async def process_resreq_reject_reason(message: Message, state: FSMContext, bot: Bot):
            reason = (message.text or "").strip()
            data = await state.get_data()
            request_id = data.get("resreq_reject_id")
            status = data.get("resreq_reject_status", "rejected")
            req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
            await state.clear()
            if not req:
                await message.answer("این درخواست دیگر معتبر نیست.")
                return

            (await asyncio.to_thread(db.reject_reseller_request, request_id, status, message.from_user.id, reason))
            (await asyncio.to_thread(db.log_admin_action, 
                message.from_user.id, "reseller_request_reject",
                f"درخواست #{request_id} | کاربر {req['user_id']} | وضعیت: {status} | دلیل: {reason}",
            ))
            await message.answer("✅ ثبت شد و به کاربر اطلاع داده شد.")
            label = "درخواست نمایندگی" if status == "rejected" else "پرداخت درخواست نمایندگی"
            try:
                await bot.send_message(
                    req["user_id"],
                    f"❌ متاسفانه {label} شما (#{request_id}) رد شد.\n\nدلیل: {reason}",
                )
                await _notify_user_inline_menu(bot, req["user_id"])
            except Exception:
                pass

        @router.callback_query(F.data.startswith("resreq_payok:"))
        async def cb_resreq_payok(call: CallbackQuery, bot: Bot, dispatcher: Dispatcher):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or req["status"] != "awaiting_payment_review":
                await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
                return

            (await asyncio.to_thread(db.approve_reseller_request_payment, request_id, call.from_user.id))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "reseller_request_payment_approve",
                f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {req['price_toman']:,}",
            ))

            user_state = FSMContext(
                storage=dispatcher.storage,
                key=StorageKey(bot_id=bot.id, chat_id=req["user_id"], user_id=req["user_id"]),
            )
            await user_state.set_state(ResellerRequestFlow.waiting_bot_token)
            await user_state.update_data(resreq_request_id=request_id)

            try:
                await bot.send_message(
                    req["user_id"],
                    "✅ پرداخت شما تایید شد!\n\n"
                    "حالا توکن بات نماینده‌ی خودتان را ارسال کنید (همانی که از @BotFather گرفته‌اید):",
                )
            except Exception:
                pass

            try:
                await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ پرداخت تایید شد.")
            except Exception:
                try:
                    await safe_edit(call, (call.message.text or "") + "\n\n✅ پرداخت تایید شد.")
                except Exception:
                    pass
            await call.answer("پرداخت تایید شد.")

        # ---------------------------------------------------------------
        # درخواست‌های نمایندگی (لیست کامل درخواست‌های باز + کنسل دستی)
        # ---------------------------------------------------------------

        @router.callback_query(F.data == "adm_reseller_requests_menu")
        async def cb_admin_reseller_requests_menu(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            requests = (await asyncio.to_thread(db.list_open_reseller_requests))
            if not requests:
                await call.answer("درخواست باز برای نمایندگی وجود ندارد.", show_alert=True)
                return
            await replace_admin_view(
                call,
                f"📋 درخواست‌های باز نمایندگی ({len(requests)} مورد):\n\n"
                "با «کنسل دستی» می‌توانید یک درخواست را در هر مرحله‌ای که هست "
                "(بدون توضیح یا اطلاع‌رسانی رد رسمی) لغو کنید.",
                reply_markup=kb.reseller_requests_open_kb(requests),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("resreq_admin_cancel:"))
        async def cb_resreq_admin_cancel(call: CallbackQuery, bot: Bot, dispatcher: Dispatcher):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = callback_id(call.data, "resreq_admin_cancel")
            if request_id is None:
                await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
                return
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or not (await asyncio.to_thread(db.is_reseller_request_open, req["status"])):
                await call.answer("این درخواست دیگر باز نیست.", show_alert=True)
                return

            (await asyncio.to_thread(db.admin_cancel_reseller_request, request_id, call.from_user.id))
            if req["status"] == "awaiting_bot_info":
                # کاربر منتظر ارسال توکن بات بوده؛ چون کنسل شد، نباید در این state گیر بماند
                try:
                    user_state = FSMContext(
                        storage=dispatcher.storage,
                        key=StorageKey(bot_id=bot.id, chat_id=req["user_id"], user_id=req["user_id"]),
                    )
                    await user_state.clear()
                except Exception:
                    pass
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "reseller_request_admin_cancel",
                f"درخواست #{request_id} | کاربر {req['user_id']}",
            ))
            try:
                await bot.send_message(
                    req["user_id"],
                    f"⚪️ درخواست نمایندگی شما (#{request_id}) توسط مدیریت کنسل شد.",
                )
                await _notify_user_inline_menu(bot, req["user_id"])
            except Exception:
                pass

            requests = (await asyncio.to_thread(db.list_open_reseller_requests))
            if requests:
                await safe_edit(
                    call,
                    f"📋 درخواست‌های باز نمایندگی ({len(requests)} مورد):\n\n✅ درخواست #{request_id} کنسل شد.",
                    reply_markup=kb.reseller_requests_open_kb(requests),
                )
            else:
                await safe_edit(
                    call,
                    f"📋 درخواست‌های باز نمایندگی\n\n✅ درخواست #{request_id} کنسل شد. دیگر درخواست باز دیگری باقی نمانده.",
                    reply_markup=kb.admin_back_kb(),
                )
            await call.answer("درخواست کنسل شد.")

        # ---------------------------------------------------------------
        # نمایندگی حجمی (استخر اعتبار داخل همین بات اصلی، بدون نمایش پنل)
        # ---------------------------------------------------------------

        @router.callback_query(F.data == "adm_credit_resellers_menu")
        async def cb_admin_credit_resellers_menu(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            resellers = (await asyncio.to_thread(db.get_resellers))
            await replace_admin_view(
                call,
                "💳 نمایندگی حجمی:\n\n"
                "کاربرانی که اعتبار (گیگ) خریده‌اند و می‌توانند از داخل همین بات، بدون دیدن پنل واقعی، "
                "برای مشتری‌های خودشان کانفیگ بسازند.",
                reply_markup=kb.credit_resellers_menu_kb(resellers),
            )
            await call.answer()

        @router.callback_query(F.data == "adm_cres_find")
        async def cb_admin_cres_find(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            await state.set_state(AdminResellerCredit.waiting_user_id)
            await safe_edit(
                call,
                "آیدی عددی کاربری که می‌خواهید نماینده‌اش کنید (یا مدیریت کنید) را ارسال کنید:",
                reply_markup=kb.admin_back_kb("adm_credit_resellers_menu"),
            )
            await call.answer()

        @router.message(AdminResellerCredit.waiting_user_id)
        async def process_cres_find(message: Message, state: FSMContext):
            raw = (message.text or "").strip()
            if not raw.isdigit():
                await message.answer("لطفاً فقط آیدی عددی ارسال کنید.")
                return
            target_id = int(raw)
            if not (await asyncio.to_thread(db.get_user, target_id)):
                await state.clear()
                await message.answer(
                    "این کاربر هنوز با بات /start نزده. اول باید کاربر یک‌بار بات را استارت کند.",
                    reply_markup=kb.credit_resellers_menu_kb((await asyncio.to_thread(db.get_resellers))),
                )
                return
            await state.clear()
            credit = (await asyncio.to_thread(db.get_reseller_credit, target_id))
            is_res = (await asyncio.to_thread(db.is_reseller, target_id))
            await message.answer(
                f"👤 کاربر {target_id}\n"
                f"وضعیت نمایندگی: {'✅ فعال' if is_res else '◻️ غیرفعال'}\n"
                f"📦 اعتبار فعلی: {credit:,} گیگ",
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )

        @router.callback_query(F.data.startswith("adm_cres_view:"))
        async def cb_admin_cres_view(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            credit = (await asyncio.to_thread(db.get_reseller_credit, target_id))
            is_res = (await asyncio.to_thread(db.is_reseller, target_id))
            await replace_admin_view(
                call,
                f"👤 کاربر {target_id}\n"
                f"وضعیت نمایندگی: {'✅ فعال' if is_res else '◻️ غیرفعال'}\n"
                f"📦 اعتبار فعلی: {credit:,} گیگ",
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("adm_cres_toggle:"))
        async def cb_admin_cres_toggle(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            (await asyncio.to_thread(db.set_reseller_status, target_id, not db.is_reseller(target_id)))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "reseller_credit_toggle", f"کاربر {target_id}"))
            is_res = (await asyncio.to_thread(db.is_reseller, target_id))
            credit = (await asyncio.to_thread(db.get_reseller_credit, target_id))
            await safe_edit(
                call,
                f"👤 کاربر {target_id}\n"
                f"وضعیت نمایندگی: {'✅ فعال' if is_res else '◻️ غیرفعال'}\n"
                f"📦 اعتبار فعلی: {credit:,} گیگ",
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )
            await call.answer("وضعیت تغییر کرد.")

        @router.callback_query(F.data.startswith("adm_cres_credit:"))
        async def cb_admin_cres_credit(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            await state.update_data(cres_target_id=target_id)
            await state.set_state(AdminResellerCredit.waiting_delta)
            await safe_edit(
                call,
                "چند گیگ اضافه/کم شود؟ عدد مثبت برای شارژ، عدد منفی برای کسر (مثلاً 1000 یا 1000-):",
                reply_markup=kb.admin_back_kb(f"adm_cres_view:{target_id}"),
            )
            await call.answer()

        @router.message(AdminResellerCredit.waiting_delta)
        async def process_cres_credit(message: Message, state: FSMContext):
            raw = (message.text or "").strip().replace(" ", "")
            data = await state.get_data()
            target_id = data.get("cres_target_id")
            sign = -1 if raw.endswith("-") else 1
            digits = raw.rstrip("-").lstrip("+")
            if not digits.isdigit() or int(digits) == 0:
                await message.answer("لطفاً یک عدد صحیح غیرصفر ارسال کنید (مثلاً 1000 یا 1000-).")
                return
            delta = sign * int(digits)
            (await asyncio.to_thread(db.adjust_reseller_credit, target_id, delta, admin_id=message.from_user.id, reason="تنظیم دستی توسط ادمین"))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "reseller_credit_adjust", f"کاربر {target_id} | {delta:+} گیگ"))
            await state.clear()
            credit = (await asyncio.to_thread(db.get_reseller_credit, target_id))
            is_res = (await asyncio.to_thread(db.is_reseller, target_id))
            await message.answer(
                f"✅ اعتبار به‌روزرسانی شد.\n\n"
                f"👤 کاربر {target_id}\n"
                f"📦 اعتبار فعلی: {credit:,} گیگ",
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )

        @router.callback_query(F.data.startswith("adm_cres_panel:"))
        async def cb_admin_cres_panel(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            panels = (await asyncio.to_thread(db.get_panel_servers, active_only=True))
            await replace_admin_view(
                call,
                "🔗 این نماینده روی کدام پنل کانفیگ بسازد؟\n"
                "(نماینده هیچ‌وقت آدرس/مشخصات این پنل را نمی‌بیند.)",
                reply_markup=kb.credit_reseller_panel_pick_kb(target_id, panels),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("adm_cres_panel_set:"))
        async def cb_admin_cres_panel_set(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            _, target_id_str, panel_id_str = call.data.split(":")
            target_id, panel_id = int(target_id_str), int(panel_id_str)
            (await asyncio.to_thread(db.set_reseller_panel, target_id, panel_id or None))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "reseller_panel_set",
                f"کاربر {target_id} ← پنل {panel_id or 'خودکار'}",
            ))
            is_res = (await asyncio.to_thread(db.is_reseller, target_id))
            credit = (await asyncio.to_thread(db.get_reseller_credit, target_id))
            await safe_edit(
                call,
                f"✅ پنل این نماینده تنظیم شد.\n\n"
                f"👤 کاربر {target_id}\n"
                f"وضعیت نمایندگی: {'✅ فعال' if is_res else '◻️ غیرفعال'}\n"
                f"📦 اعتبار فعلی: {credit:,} گیگ",
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )
            await call.answer("تنظیم شد.")

    # -------------------------------------------------------------------
    # ویرایش متن دکمه‌ها
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_edit_buttons")
    async def cb_admin_edit_buttons(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, "کدام دکمه ویرایش شود؟", reply_markup=kb.admin_edit_buttons_kb(db))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_btn_edit:"))
    async def cb_admin_btn_edit(call: CallbackQuery, state: FSMContext):
        key = call.data.split(":")[1]
        await state.update_data(setting_key=key)
        await state.set_state(AdminEditButton.waiting_text)
        current = (await asyncio.to_thread(db.get_setting, key))
        await safe_edit(call, 
            f"متن فعلی: {current}\n\nمتن جدید را ارسال کنید (می‌توانید ایموجی هم اضافه کنید):",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminEditButton.waiting_text)
    async def process_edit_button(message: Message, state: FSMContext):
        data = await state.get_data()
        key = data["setting_key"]
        (await asyncio.to_thread(db.set_setting, key, message.text.strip()))
        await state.clear()
        await message.answer("✅ متن دکمه به‌روزرسانی شد.", reply_markup=kb.admin_edit_buttons_kb(db))

    @router.callback_query(F.data.startswith("adm_btn_toggle:"))
    async def cb_admin_btn_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        key = call.data.split(":")[1]
        meta = MENU_BUTTON_META.get(key)
        if not meta or not meta["toggle_key"]:
            await call.answer("❌ این دکمه قابل فعال/غیرفعال کردن نیست.", show_alert=True)
            return
        toggle_key = meta["toggle_key"]
        current = (await asyncio.to_thread(db.get_setting, toggle_key, "1"))
        (await asyncio.to_thread(db.set_setting, toggle_key, "0" if current == "1" else "1"))
        await safe_edit(call, "کدام دکمه ویرایش شود؟", reply_markup=kb.admin_edit_buttons_kb(db))
        await call.answer("✅ وضعیت دکمه به‌روزرسانی شد.")

    # -------------------------------------------------------------------
    # چیدمان/نمایش منوی اصلی: منوی پایین (Reply) و منوی شیشه‌ای بالا (Inline)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_main_menu_settings")
    async def cb_admin_main_menu_settings(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, "🧩 تنظیمات منوی اصلی:", reply_markup=kb.main_menu_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_mm_toggle_reply")
    async def cb_admin_mm_toggle_reply(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "main_menu_reply_enabled", "1")) == "1"
        if current and (await asyncio.to_thread(db.get_setting, "main_menu_inline_enabled", "0")) != "1":
            await call.answer("⚠️ چون منوی شیشه‌ای بالا غیرفعال است، منوی پایین را نمی‌توان خاموش کرد.", show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "main_menu_reply_enabled", "0" if current else "1"))
        await safe_edit(call, "🧩 تنظیمات منوی اصلی:", reply_markup=kb.main_menu_settings_kb(db))
        await call.answer("✅ اعمال شد.")

    @router.callback_query(F.data == "adm_mm_toggle_inline")
    async def cb_admin_mm_toggle_inline(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "main_menu_inline_enabled", "0")) == "1"
        if current and (await asyncio.to_thread(db.get_setting, "main_menu_reply_enabled", "1")) != "1":
            await call.answer("⚠️ چون منوی پایین غیرفعال است، منوی شیشه‌ای بالا را نمی‌توان خاموش کرد.", show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "main_menu_inline_enabled", "0" if current else "1"))
        await safe_edit(call, "🧩 تنظیمات منوی اصلی:", reply_markup=kb.main_menu_settings_kb(db))
        await call.answer("✅ اعمال شد.")

    @router.callback_query(F.data == "adm_mm_toggle_columns")
    async def cb_admin_mm_toggle_columns(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "main_menu_columns", "1"))
        new_val = "2" if current != "2" else "1"
        (await asyncio.to_thread(db.set_setting, "main_menu_columns", new_val))
        await safe_edit(call, "🧩 تنظیمات منوی اصلی:", reply_markup=kb.main_menu_settings_kb(db))
        await call.answer("✅ اعمال شد.")

    # کلیک روی دکمه‌ی «پنل مدیریت» وقتی از منوی شیشه‌ای بالا (نه منوی پایین) زده شود
    @router.callback_query(F.data == "mm:btn_admin_panel")
    async def cb_mm_admin_panel(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if not admin_only(call.from_user.id):
            return
        await state.clear()
        await call.message.answer("🔧 پنل مدیریت:", reply_markup=kb.admin_panel_kb(db, is_main_bot))

    def _lookup_button_label(key: str) -> str:
        if key in kb.BUTTON_LABELS:
            return kb.BUTTON_LABELS[key]
        for item_key, label, _ in kb.ADMIN_PANEL_ITEMS:
            if item_key == key:
                return label
        for item_key, label in kb.BUY_FLOW_COLOR_ITEMS:
            if item_key == key:
                return label
        if key in kb._EXTRA_PANEL_ITEM_LABELS:
            return kb._EXTRA_PANEL_ITEM_LABELS[key]
        return key

    def _is_panel_item_key(key: str) -> bool:
        return any(item_key == key for item_key, _, _ in kb.ADMIN_PANEL_ITEMS)

    def _is_buyflow_key(key: str) -> bool:
        return any(item_key == key for item_key, _ in kb.BUY_FLOW_COLOR_ITEMS)

    @router.callback_query(F.data.startswith("adm_btn_color_menu:"))
    async def cb_admin_btn_color_menu(call: CallbackQuery):
        key = call.data.split(":")[1]
        label = _lookup_button_label(key)
        if _is_panel_item_key(key):
            back_callback = "adm_panel_colors_menu"
        elif _is_buyflow_key(key):
            back_callback = "adm_buyflow_colors_menu"
        else:
            back_callback = "adm_edit_buttons"
        await safe_edit(call, 
            f"رنگ «{label}» را انتخاب کنید:", reply_markup=kb.admin_color_picker_kb(key, back_callback)
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_btn_color_set:"))
    async def cb_admin_btn_color_set(call: CallbackQuery):
        parts = (call.data or "").split(":")
        if len(parts) != 3 or parts[0] != "adm_btn_color_set":
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        _, key, style = parts
        if not key or style not in {"primary", "success", "danger", "none"}:
            await call.answer("❌ رنگ انتخاب‌شده نامعتبر است.", show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, f"{key}_style", "" if style == "none" else style))
        if _is_panel_item_key(key):
            await safe_edit(call, "🎨 رنگ‌آمیزی دکمه‌های پنل مدیریت:", reply_markup=kb.admin_panel_colors_kb(db, is_main_bot))
        elif _is_buyflow_key(key):
            await safe_edit(call, "🎨 رنگ‌آمیزی دکمه‌های خرید:", reply_markup=kb.buy_flow_colors_kb(db))
        else:
            await safe_edit(call, "کدام دکمه ویرایش شود؟", reply_markup=kb.admin_edit_buttons_kb(db))
        await call.answer("✅ رنگ دکمه به‌روزرسانی شد.")

    @router.callback_query(F.data == "adm_panel_colors_menu")
    async def cb_admin_panel_colors_menu(call: CallbackQuery):
        await replace_admin_view(call, "🎨 رنگ‌آمیزی دکمه‌های پنل مدیریت:", reply_markup=kb.admin_panel_colors_kb(db, is_main_bot))
        await call.answer()

    @router.callback_query(F.data == "adm_buyflow_colors_menu")
    async def cb_admin_buyflow_colors_menu(call: CallbackQuery):
        await replace_admin_view(call, "🎨 رنگ‌آمیزی دکمه‌های خرید:", reply_markup=kb.buy_flow_colors_kb(db))
        await call.answer()

    # -------------------------------------------------------------------
    # تنظیم شماره کارت
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_set_card")
    async def cb_admin_set_card(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminSetCard.waiting_number)
        await safe_edit(call, "شماره کارت جدید را ارسال کنید:", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminSetCard.waiting_number)
    async def process_set_card_number(message: Message, state: FSMContext):
        await state.update_data(card_number=message.text.strip())
        await state.set_state(AdminSetCard.waiting_holder)
        await message.answer("نام صاحب حساب را ارسال کنید:")

    @router.message(AdminSetCard.waiting_holder)
    async def process_set_card_holder(message: Message, state: FSMContext):
        data = await state.get_data()
        (await asyncio.to_thread(db.set_setting, "card_number", data["card_number"]))
        (await asyncio.to_thread(db.set_setting, "card_holder", message.text.strip()))
        await state.clear()
        (await asyncio.to_thread(db.log_admin_action, 
            message.from_user.id, "card_change",
            f"شماره کارت جدید: {data['card_number']} | به نام: {message.text.strip()}",
        ))
        await message.answer("✅ اطلاعات کارت به‌روزرسانی شد.", reply_markup=kb.admin_category_kb(db, is_main_bot, "finance"))

    # -------------------------------------------------------------------
    # حذف خودکار پیام‌های حاوی شماره کارت
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_card_autodelete")
    async def cb_admin_card_autodelete(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        current = int((await asyncio.to_thread(db.get_setting, "card_msg_autodelete_seconds", "0")) or 0)
        await safe_edit(
            call,
            "⏱ پیام‌هایی که شماره کارت داخلشونه (خرید، شارژ کیف پول، خرید نمایندگی و ...) "
            "بعد از مدت انتخابی، خودشون از چت حذف می‌شوند.\n\n"
            "مدت مورد نظر را انتخاب کن:",
            reply_markup=kb.admin_card_autodelete_kb(current),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_card_autodel:"))
    async def cb_card_autodelete_pick(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        value = call.data.split(":", 1)[1]
        if value == "custom":
            await state.set_state(AdminSetCard.waiting_autodelete_custom)
            await safe_edit(
                call, "مدت دلخواه را به دقیقه ارسال کن (مثلاً 45):",
                reply_markup=kb.admin_back_kb("adm_card_autodelete"),
            )
            await call.answer()
            return
        seconds = int(value)
        (await asyncio.to_thread(db.set_setting, "card_msg_autodelete_seconds", str(seconds)))
        (await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "card_autodelete_change",
            f"حذف خودکار پیام شماره کارت روی {seconds} ثانیه تنظیم شد.",
        ))
        await safe_edit(
            call,
            ("✅ حذف خودکار غیرفعال شد؛ پیام‌های شماره کارت از این پس برای همیشه می‌مانند."
             if seconds == 0 else
             f"✅ پیام‌های شماره کارت از این پس {_duration_label_fa(seconds)} بعد از ارسال خودکار حذف می‌شوند."),
            reply_markup=kb.admin_card_autodelete_kb(seconds),
        )
        await call.answer()

    @router.message(AdminSetCard.waiting_autodelete_custom)
    async def process_card_autodelete_custom(message: Message, state: FSMContext):
        if not (message.text or "").strip().isdigit() or int(message.text.strip()) <= 0:
            await message.answer("⚠️ فقط یک عدد صحیح مثبت (به دقیقه) ارسال کن.")
            return
        seconds = int(message.text.strip()) * 60
        await state.clear()
        (await asyncio.to_thread(db.set_setting, "card_msg_autodelete_seconds", str(seconds)))
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "card_autodelete_change",
            f"حذف خودکار پیام شماره کارت روی {seconds} ثانیه تنظیم شد.",
        ))
        await message.answer(
            f"✅ پیام‌های شماره کارت از این پس {_duration_label_fa(seconds)} بعد از ارسال خودکار حذف می‌شوند.",
            reply_markup=kb.admin_category_kb(db, is_main_bot, "finance"),
        )

    # -------------------------------------------------------------------
    # تنظیم درگاه پرداخت کریپتو (Plisio)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_set_plisio")
    async def cb_admin_set_plisio(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "plisio_api_key", ""))
        masked = f"...{current[-4:]}" if current else "❌ تنظیم نشده"
        source = crypto_payment.resolve_plisio_key_source(db)
        source_note = {
            "db": "✅ از همین پنل بات خوانده می‌شود (بات و مینی‌اپ هر دو همین را می‌بینند، بدون نیاز به ری‌استارت).",
            "env": "⚠️ فقط از فایل .env این پروسه خوانده می‌شود. اگر بات و مینی‌اپ را جدا ری‌استارت نکرده باشی ممکن است این دو با هم ناهماهنگ باشند. پیشنهاد: همینجا دوباره ثبتش کن تا مطمئن بشی.",
            "none": "❌ هیچ کلیدی (نه در دیتابیس، نه در .env) تنظیم نشده.",
        }[source]
        await state.set_state(AdminSetPlisio.waiting_key)
        await safe_edit(
            call,
            f"🪙 API Key حساب Plisio را ارسال کن (از plisio.net → API Settings).\n"
            f"وضعیت فعلی: {masked}\n"
            f"منبع کلید: {source_note}\n\n"
            f"برای غیرفعال‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb(),
        )
        await call.answer()

    @router.message(AdminSetPlisio.waiting_key)
    async def process_set_plisio_key(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "plisio_api_key", ""))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "plisio_key_change", "API Key کریپتو حذف شد."))
            await message.answer("✅ API Key کریپتو حذف شد و درگاه غیرفعال شد.", reply_markup=kb.admin_category_kb(db, is_main_bot, "finance"))
            return
        (await asyncio.to_thread(db.set_setting, "plisio_api_key", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "plisio_key_change", "API Key کریپتو تغییر کرد."))
        await message.answer(
            "✅ API Key کریپتو ذخیره شد.\n"
            "الان از مینی‌اپ → مدیریت → فروش → «پرداخت کریپتو» فعالش کن.",
            reply_markup=kb.admin_category_kb(db, is_main_bot, "finance"),
        )

    # -------------------------------------------------------------------
    # ویرایش پیام خوش‌آمد
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_edit_welcome")
    async def cb_admin_edit_welcome(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminEditWelcome.waiting_text)
        current = (await asyncio.to_thread(db.get_setting, "welcome_text"))
        await safe_edit(call, f"متن فعلی:\n{current}\n\nمتن جدید را ارسال کنید:", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminEditWelcome.waiting_text)
    async def process_edit_welcome(message: Message, state: FSMContext):
        (await asyncio.to_thread(db.set_setting, "welcome_text", message.text))
        await state.clear()
        await message.answer("✅ پیام خوش‌آمد به‌روزرسانی شد.", reply_markup=kb.admin_category_kb(db, is_main_bot, "appearance"))

    # -------------------------------------------------------------------
    # مدیریت ادمین‌ها
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_admins_menu")
    async def cb_admin_admins_menu(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer("⛔️ مدیریت ادمین‌ها فقط برای مالک اصلی در دسترس است.", show_alert=True)
        try:
            await replace_admin_view(call, "👤 مدیریت ادمین‌ها:", kb.admin_admins_menu_kb())
            await call.answer()
        except Exception:
            await call.answer("⚠️ باز کردن مدیریت ادمین‌ها ناموفق بود.", show_alert=True)

    @router.callback_query(F.data == "adm_admins_list")
    async def cb_admin_admins_list(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer("⛔️ فقط مالک اصلی می‌تواند لیست ادمین‌ها را ببیند.", show_alert=True)
        try:
            admins = (await asyncio.to_thread(db.list_admins_with_roles))
            if not admins:
                text = "📃 هیچ ادمینی ثبت نشده است."
            else:
                # برای جلوگیری از خطاهای Markdown، لیست را بدون parse_mode ارسال می‌کنیم.
                lines = [f"• {a['telegram_id']} — {kb.ADMIN_ROLE_LABELS.get(a['role'], a['role'])}" for a in admins]
                text = "📃 لیست ادمین‌ها و نقش‌ها:\n\n" + "\n".join(lines)
            await replace_admin_view(call, text, kb.admin_back_kb("adm_admins_menu"))
            await call.answer()
        except Exception:
            await call.answer("⚠️ دریافت لیست ادمین‌ها ناموفق بود. دوباره تلاش کنید.", show_alert=True)

    @router.callback_query(F.data == "adm_admin_add")
    async def cb_admin_admin_add(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await call.answer("⛔️ فقط مالک اصلی می‌تواند ادمین اضافه کند.", show_alert=True)
        await state.set_state(AdminAddAdmin.waiting_id)
        await replace_admin_view(call, 
            "آیدی عددی کاربر جدید برای افزودن به ادمین‌ها را ارسال کنید:", reply_markup=kb.admin_back_kb("adm_admins_menu")
        )
        await call.answer()

    @router.message(AdminAddAdmin.waiting_id)
    async def process_add_admin(message: Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("لطفاً فقط آیدی عددی ارسال کنید.")
            return
        target_id = int(raw)
        if (await asyncio.to_thread(db.is_admin, target_id)):
            await state.clear()
            await message.answer(
                "این کاربر از قبل ادمین است. برای تغییر نقشش از «🔄 تغییر نقش ادمین» استفاده کن.",
                reply_markup=kb.admin_admins_menu_kb(),
            )
            return
        await state.clear()
        await message.answer(
            f"نقش کاربر {target_id} چه باشد?",
            reply_markup=kb.admin_role_pick_kb(target_id, "add"),
        )

    @router.callback_query(F.data.startswith("adm_add_admin_role:"))
    async def cb_admin_add_admin_role(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer("⛔️ فقط مالک اصلی می‌تواند ادمین اضافه کند.", show_alert=True)
        try:
            parts = (call.data or "").split(":")
            if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("admin", "mid", "support"):
                return await call.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
            target_id, role = int(parts[1]), parts[2]
            (await asyncio.to_thread(db.add_admin, target_id, role=role))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "admin_add",
                f"کاربر {target_id} | نقش: {kb.ADMIN_ROLE_LABELS.get(role, role)}",
            ))
            await safe_edit(
                call,
                f"✅ کاربر {target_id} با نقش «{kb.ADMIN_ROLE_LABELS.get(role, role)}» اضافه شد.",
                kb.admin_back_kb("adm_admins_menu"),
            )
            await call.answer("ادمین اضافه شد.")
        except Exception:
            await call.answer("⚠️ افزودن ادمین ناموفق بود. دوباره تلاش کنید.", show_alert=True)

    @router.callback_query(F.data == "adm_admin_role_change")
    async def cb_admin_role_change_start(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await call.answer("⛔️ فقط مالک اصلی می‌تواند نقش ادمین‌ها را تغییر دهد.", show_alert=True)
        await state.set_state(AdminChangeRole.waiting_id)
        await replace_admin_view(call, 
            "آیدی عددی ادمینی که می‌خواهی نقشش را تغییر دهی را ارسال کن:",
            reply_markup=kb.admin_back_kb("adm_admins_menu"),
        )
        await call.answer()

    @router.message(AdminChangeRole.waiting_id)
    async def process_change_role_id(message: Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("لطفاً فقط آیدی عددی ارسال کنید.")
            return
        target_id = int(raw)
        await state.clear()
        role = (await asyncio.to_thread(db.get_admin_role, target_id))
        if role is None:
            await message.answer("این کاربر ادمین نیست.", reply_markup=kb.admin_admins_menu_kb())
            return
        if role == "owner":
            await message.answer("نقش مالک اصلی قابل تغییر نیست.", reply_markup=kb.admin_admins_menu_kb())
            return
        await message.answer(
            f"نقش جدید کاربر {target_id} (نقش فعلی: {kb.ADMIN_ROLE_LABELS.get(role, role)}) چه باشد؟",
            reply_markup=kb.admin_role_pick_kb(target_id, "setrole"),
        )

    @router.callback_query(F.data.startswith("adm_change_role_set:"))
    async def cb_admin_change_role_set(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer("⛔️ فقط مالک اصلی می‌تواند نقش ادمین‌ها را تغییر دهد.", show_alert=True)
        try:
            parts = (call.data or "").split(":")
            if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("admin", "mid", "support"):
                return await call.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
            target_id, role = int(parts[1]), parts[2]
            ok = (await asyncio.to_thread(db.set_admin_role, target_id, role))
            if not ok:
                return await call.answer("⛔️ تغییر نقش ناموفق بود.", show_alert=True)
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "admin_role_change",
                f"کاربر {target_id} | نقش جدید: {kb.ADMIN_ROLE_LABELS.get(role, role)}",
            ))
            await safe_edit(
                call,
                f"✅ نقش کاربر {target_id} به «{kb.ADMIN_ROLE_LABELS.get(role, role)}» تغییر کرد.",
                kb.admin_back_kb("adm_admins_menu"),
            )
            await call.answer("نقش تغییر کرد.")
        except Exception:
            await call.answer("⚠️ تغییر نقش ناموفق بود. دوباره تلاش کنید.", show_alert=True)

    @router.callback_query(F.data == "adm_admin_remove")
    async def cb_admin_admin_remove(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await call.answer("⛔️ فقط مالک اصلی می‌تواند ادمین حذف کند.", show_alert=True)
        await state.set_state(AdminRemoveAdmin.waiting_id)
        await replace_admin_view(call, 
            "آیدی عددی ادمینی که باید حذف شود را ارسال کنید:", reply_markup=kb.admin_back_kb("adm_admins_menu")
        )
        await call.answer()

    @router.message(AdminRemoveAdmin.waiting_id)
    async def process_remove_admin(message: Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("لطفاً فقط آیدی عددی ارسال کنید.")
            return
        target_id = int(raw)
        try:
            if not (await asyncio.to_thread(db.is_admin, target_id)):
                await state.clear()
                await message.answer("⛔️ این کاربر ادمین نیست.", reply_markup=kb.admin_admins_menu_kb())
                return
            if (await asyncio.to_thread(db.get_admin_role, target_id)) == "owner":
                await state.clear()
                await message.answer("⛔️ مالک اصلی قابل حذف نیست.", reply_markup=kb.admin_admins_menu_kb())
                return
            ok = (await asyncio.to_thread(db.remove_admin, target_id))
            await state.clear()
            if ok:
                (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "admin_remove", f"کاربر {target_id}"))
                await message.answer("✅ ادمین حذف شد.", reply_markup=kb.admin_admins_menu_kb())
            else:
                await message.answer("⛔️ حذف ادمین ناموفق بود.", reply_markup=kb.admin_admins_menu_kb())
        except Exception:
            await state.clear()
            await message.answer("⚠️ حذف ادمین ناموفق بود. دوباره تلاش کنید.")

    # -------------------------------------------------------------------
    # پیام همگانی
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_broadcast")
    async def cb_admin_broadcast(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminBroadcast.waiting_message)
        await replace_admin_view(call, "متن پیام همگانی را ارسال کنید (برای همه کاربران ارسال می‌شود):", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminBroadcast.waiting_message)
    async def process_broadcast(message: Message, state: FSMContext):
        await state.update_data(broadcast_chat_id=message.chat.id, broadcast_message_id=message.message_id)
        await state.set_state(AdminBroadcast.waiting_duration)
        await message.answer(
            "⏱ این پیام همگانی بعد از چه مدت خودش حذف شود؟ (برای ماندن همیشگی، گزینه‌ی «بدون حذف خودکار» را بزن)",
            reply_markup=kb.admin_broadcast_duration_kb(),
        )

    async def _finalize_broadcast(state: FSMContext, bot: Bot, admin_id: int, seconds: int, answer_fn):
        data = await state.get_data()
        chat_id = data.get("broadcast_chat_id")
        message_id = data.get("broadcast_message_id")
        await state.clear()
        if not chat_id or not message_id:
            await answer_fn("⚠️ اطلاعات پیام همگانی ناقص بود؛ دوباره از اول شروع کن.")
            return
        user_ids = (await asyncio.to_thread(db.get_all_user_ids))
        success, failed = 0, 0
        sent_targets = []
        for uid in user_ids:
            try:
                sent = await bot.copy_message(uid, from_chat_id=chat_id, message_id=message_id)
                success += 1
                if seconds > 0:
                    sent_targets.append((uid, sent.message_id))
            except Exception:
                failed += 1
        for uid, mid in sent_targets:
            await schedule_message_autodelete(db, uid, mid, seconds)
        label = _duration_label_fa(seconds) if seconds > 0 else "بدون حذف خودکار"
        (await asyncio.to_thread(db.log_admin_action, admin_id, "broadcast", f"ارسال به {len(user_ids)} کاربر | موفق: {success} | ناموفق: {failed} | حذف خودکار: {label}"))
        await answer_fn(
            f"📢 پیام همگانی ارسال شد.\n✅ موفق: {success}\n❌ ناموفق: {failed}\n⏱ حذف خودکار: {label}",
            reply_markup=kb.admin_category_kb(db, is_main_bot, "marketing"),
        )

    @router.callback_query(F.data.startswith("adm_broadcast_dur:"))
    async def cb_broadcast_duration(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        value = call.data.split(":", 1)[1]
        if value == "custom":
            await state.set_state(AdminBroadcast.waiting_custom_minutes)
            await replace_admin_view(call, "مدت دلخواه را به دقیقه ارسال کن (مثلاً 45):", reply_markup=kb.admin_back_kb())
            await call.answer()
            return
        await call.answer("در حال ارسال...")
        await _finalize_broadcast(state, call.bot, call.from_user.id, int(value), call.message.answer)

    @router.message(AdminBroadcast.waiting_custom_minutes)
    async def process_broadcast_custom_minutes(message: Message, state: FSMContext, bot: Bot):
        if not (message.text or "").strip().isdigit() or int(message.text.strip()) <= 0:
            await message.answer("⚠️ فقط یک عدد صحیح مثبت (به دقیقه) ارسال کن.")
            return
        minutes = int(message.text.strip())
        await _finalize_broadcast(state, bot, message.from_user.id, minutes * 60, message.answer)

    # -------------------------------------------------------------------
    # پیام موقت (خودحذف‌شونده بعد از مدت مشخص)
    # -------------------------------------------------------------------

    def _duration_label_fa(seconds: int) -> str:
        if seconds % 86400 == 0:
            return f"{seconds // 86400} روز"
        if seconds % 3600 == 0:
            return f"{seconds // 3600} ساعت"
        return f"{seconds // 60} دقیقه"

    async def _finalize_temp_message(state: FSMContext, bot: Bot, seconds: int, answer_fn):
        data = await state.get_data()
        target_id = data.get("temp_target_id")
        text = data.get("temp_text")
        await state.clear()
        if not target_id or not text:
            await answer_fn("⚠️ اطلاعات پیام موقت ناقص بود؛ دوباره از اول شروع کن.")
            return
        try:
            await send_temp_message(bot, db, target_id, text, seconds)
            await answer_fn(f"✅ پیام ارسال شد و بعد از {_duration_label_fa(seconds)} خودش حذف می‌شود.")
        except Exception:
            logger.exception("ارسال پیام موقت ناموفق بود.")
            await answer_fn("⚠️ ارسال پیام ناموفق بود؛ آیدی مقصد را بررسی کن.")

    @router.callback_query(F.data == "adm_temp_message")
    async def cb_admin_temp_message(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await replace_admin_view(
            call,
            "⏳ پیام موقت: پیامی که بعد از مدت مشخص خودش حذف می‌شود (مثلاً یادداشت یا شماره کارت).\n\nمقصد را انتخاب کن:",
            reply_markup=kb.admin_temp_message_target_kb(),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tempmsg_target:"))
    async def cb_tempmsg_target(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        choice = call.data.split(":", 1)[1]
        if choice == "self":
            await state.update_data(temp_target_id=call.from_user.id)
            await state.set_state(AdminTempMessage.waiting_text)
            await replace_admin_view(call, "متن پیام موقت را ارسال کن:", reply_markup=kb.admin_back_kb("adm_temp_message"))
        else:
            await state.set_state(AdminTempMessage.waiting_target_id)
            await replace_admin_view(call, "آیدی عددی (Telegram ID) کاربر مقصد را ارسال کن:", reply_markup=kb.admin_back_kb("adm_temp_message"))
        await call.answer()

    @router.message(AdminTempMessage.waiting_target_id)
    async def process_tempmsg_target_id(message: Message, state: FSMContext):
        if not (message.text or "").strip().isdigit():
            await message.answer("⚠️ آیدی نامعتبر است؛ فقط عدد ارسال کن.")
            return
        await state.update_data(temp_target_id=int(message.text.strip()))
        await state.set_state(AdminTempMessage.waiting_text)
        await message.answer("متن پیام موقت را ارسال کن:", reply_markup=kb.admin_back_kb("adm_temp_message"))

    @router.message(AdminTempMessage.waiting_text)
    async def process_tempmsg_text(message: Message, state: FSMContext):
        if not (message.text or "").strip():
            await message.answer("⚠️ فقط متن پشتیبانی می‌شود؛ یک پیام متنی ارسال کن.")
            return
        await state.update_data(temp_text=message.text)
        await message.answer("⏱ بعد از چه مدت خودش حذف شود؟", reply_markup=kb.admin_temp_message_duration_kb())

    @router.callback_query(F.data.startswith("adm_tempmsg_dur:"))
    async def cb_tempmsg_duration(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        value = call.data.split(":", 1)[1]
        if value == "custom":
            await state.set_state(AdminTempMessage.waiting_custom_minutes)
            await replace_admin_view(call, "مدت دلخواه را به دقیقه ارسال کن (مثلاً 45):", reply_markup=kb.admin_back_kb("adm_temp_message"))
            await call.answer()
            return
        await call.answer("در حال ارسال...")
        await _finalize_temp_message(state, call.bot, int(value), call.message.answer)

    @router.message(AdminTempMessage.waiting_custom_minutes)
    async def process_tempmsg_custom_minutes(message: Message, state: FSMContext, bot: Bot):
        if not (message.text or "").strip().isdigit() or int(message.text.strip()) <= 0:
            await message.answer("⚠️ فقط یک عدد صحیح مثبت (به دقیقه) ارسال کن.")
            return
        minutes = int(message.text.strip())
        await _finalize_temp_message(state, bot, minutes * 60, message.answer)

    # -------------------------------------------------------------------
    # ابزار دیپ‌لینک تبلیغاتی + افزودن دکمه به پست کانال
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_deeplink_tools")
    async def cb_deeplink_tools(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await replace_admin_view(call, "🔗 ابزار دیپ‌لینک و پست کانال:", reply_markup=kb.deeplink_tools_menu_kb())
        await call.answer()

    @router.callback_query(F.data == "adm_dl_params_list")
    async def cb_dl_params_list(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        me = await call.bot.get_me()
        base = f"https://t.me/{me.username}?start="
        text = (
            "📋 <b>پارامترهای اصلی دیپ‌لینک (مربوط به منوی کاربر)</b>\n\n"
            "این‌ها کلیدهایی هستند که به‌صورت خودکار توسط بات شناخته می‌شوند و "
            "با ورود کاربر، همان بخش از منو مستقیم برایش باز می‌شود:\n\n"
            f"🛒 <b>خرید</b> — <code>{base}buy</code>\n"
            "باز شدن مستقیم منوی خرید (دسته‌بندی محصولات)\n\n"
            f"🧪 <b>کانفیگ تست</b> — <code>{base}test</code>\n"
            "باز شدن مستقیم فلوی دریافت کانفیگ تست رایگان\n\n"
            f"🎡 <b>گردونه شانس</b> — <code>{base}wheel</code>\n"
            "باز شدن مستقیم گردونه شانس\n\n"
            f"🎟 <b>کد تخفیف</b> — <code>{base}disc_CODE</code>\n"
            "اعمال خودکار کد تخفیف مشخص‌شده در اولین خرید کاربر\n\n"
            f"🤝 <b>رفرال / زیرمجموعه‌گیری</b> — <code>{base}ref&lt;آیدی دعوت‌کننده&gt;</code>\n"
            "ثبت کاربر جدید به‌عنوان زیرمجموعه‌ی همان آیدی\n\n"
            "🏷 <b>پارامتر دلخواه</b> — هر متن دیگری که شناخته نشود، فقط "
            "به‌عنوان «منبع ورود کاربر» (برای آمار کمپین) ثبت می‌شود و اکشنی "
            "در منو باز نمی‌کند.\n\n"
            "ℹ️ می‌توانید چند کلید را با «-» ترکیب کنید، مثلاً:\n"
            f"<code>{base}buy-disc_SUMMER10</code>"
        )
        await safe_edit(
            call, text, reply_markup=kb.admin_back_kb("adm_deeplink_tools"), parse_mode="HTML",
        )
        await call.answer()

    @router.callback_query(F.data == "adm_dl_build")
    async def cb_dl_build(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.update_data(channel_chat_id=None, channel_message_id=None)
        await safe_edit(
            call, "چه نوع دیپ‌لینکی می‌خوای بسازی؟",
            reply_markup=kb.deeplink_type_picker_kb("adm_deeplink_tools"),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_dl_addbtn")
    async def cb_dl_addbtn(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminChannelButton.waiting_forward)
        await replace_admin_view(
            call,
            "همون پستی که قبلاً تو کانال گذاشتی رو از کانال به اینجا فوروارد کن.\n"
            "(بات باید تو کانال ادمین باشه و دسترسی «ویرایش پیام‌های دیگران» داشته باشه)",
            reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
        )
        await call.answer()

    @router.message(AdminChannelButton.waiting_forward)
    async def process_channel_forward(message: Message, state: FSMContext):
        origin = getattr(message, "forward_origin", None)
        chat_id, msg_id = None, None
        if origin is not None and getattr(origin, "chat", None) is not None:
            chat_id = origin.chat.id
            msg_id = origin.message_id
        elif getattr(message, "forward_from_chat", None) is not None:
            chat_id = message.forward_from_chat.id
            msg_id = message.forward_from_message_id

        if not chat_id or not msg_id:
            await message.answer(
                "❌ این یک پیامِ فوروارد شده از کانال نبود. لطفاً خودِ پست کانال را فوروارد کن.",
                reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
            )
            return

        await state.update_data(channel_chat_id=chat_id, channel_message_id=msg_id)
        await state.set_state(AdminChannelButton.waiting_button_text)
        await message.answer("متن دکمه رو بفرست (مثلاً: 🎁 خرید با ۳۰٪ تخفیف)")

    @router.message(AdminChannelButton.waiting_button_text)
    async def process_channel_button_text(message: Message, state: FSMContext):
        button_text = (message.text or "").strip()
        if not button_text:
            await message.answer("متن دکمه نمی‌تواند خالی باشد. دوباره بفرست:")
            return
        await state.update_data(channel_button_text=button_text)
        await message.answer(
            "چه نوع دیپ‌لینکی به این دکمه وصل بشه؟",
            reply_markup=kb.deeplink_type_picker_kb("adm_deeplink_tools"),
        )

    @router.callback_query(F.data.startswith("adm_dlp_type:"))
    async def cb_dlp_type(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        dl_type = call.data.split(":", 1)[1]

        if dl_type == "disc":
            codes = (await asyncio.to_thread(db.list_discount_codes))
            active_codes = [c for c in codes if c["is_active"]]
            if not active_codes:
                await safe_edit(
                    call, "❌ هیچ کد تخفیف فعالی نداری. اول از «کدهای تخفیف» یکی بساز.",
                    reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
                )
                await call.answer()
                return
            await safe_edit(
                call, "کدوم کد تخفیف؟",
                reply_markup=kb.deeplink_discount_picker_kb(active_codes, "adm_dl_build"),
            )
            await call.answer()
            return

        if dl_type == "custom":
            data = await state.get_data()
            in_channel_flow = bool(data.get("channel_chat_id"))
            await state.set_state(
                AdminChannelButton.waiting_custom_param if in_channel_flow else AdminDeepLinkTools.waiting_custom_param
            )
            await safe_edit(call, "پارامتر دلخواه رو بفرست (فقط حروف/عدد/زیرخط، بدون فاصله):")
            await call.answer()
            return

        await _finalize_deeplink(call, state, dl_type, call.bot)

    @router.callback_query(F.data.startswith("adm_dlp_code:"))
    async def cb_dlp_code(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code_id = int(call.data.split(":", 1)[1])
        code_row = (await asyncio.to_thread(db.get_discount_code_by_id, code_id))
        if not code_row:
            await call.answer("کد پیدا نشد.", show_alert=True)
            return
        await _finalize_deeplink(call, state, f"disc_{code_row['code']}", call.bot)

    @router.message(AdminDeepLinkTools.waiting_custom_param)
    async def process_dl_custom_param(message: Message, state: FSMContext, bot: Bot):
        token = re.sub(r"[^A-Za-z0-9_]", "", (message.text or "").strip())
        if not token:
            await message.answer("پارامتر نامعتبر بود. فقط حروف/عدد/زیرخط بفرست:")
            return
        await state.clear()
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={token}"
        await message.answer(
            f"🔗 دیپ‌لینک ساخته شد:\n\n`{link}`",
            parse_mode="Markdown",
            reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
        )

    @router.message(AdminChannelButton.waiting_custom_param)
    async def process_channel_custom_param(message: Message, state: FSMContext, bot: Bot):
        token = re.sub(r"[^A-Za-z0-9_]", "", (message.text or "").strip())
        if not token:
            await message.answer("پارامتر نامعتبر بود. فقط حروف/عدد/زیرخط بفرست:")
            return
        await _finalize_channel_button(message, state, token, bot)

    async def _finalize_deeplink(call: CallbackQuery, state: FSMContext, start_param: str, bot: Bot):
        data = await state.get_data()
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={start_param}"

        if data.get("channel_chat_id"):
            await _finalize_channel_button(call.message, state, start_param, bot, admin_id=call.from_user.id, edit_call=call)
            return

        await state.clear()
        await call.message.answer(
            f"🔗 دیپ‌لینک ساخته شد:\n\n`{link}`",
            parse_mode="Markdown",
            reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
        )
        await call.answer()

    async def _finalize_channel_button(message: Message, state: FSMContext, start_param: str, bot: Bot, admin_id: int = None, edit_call: CallbackQuery = None):
        data = await state.get_data()
        chat_id = data.get("channel_chat_id")
        msg_id = data.get("channel_message_id")
        button_text = data.get("channel_button_text", "🎁 مشاهده")
        admin_id = admin_id if admin_id is not None else message.from_user.id
        await state.clear()

        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={start_param}"
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=link)]])

        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg_id, reply_markup=markup)
            (await asyncio.to_thread(
                db.log_admin_action, admin_id, "channel_button_add", f"دکمه به پست کانال اضافه شد | لینک: {link}"
            ))
            result_text = f"✅ دکمه به پست کانال اضافه شد.\n🔗 {link}"
        except Exception as e:
            result_text = f"❌ خطا در افزودن دکمه: {e}\n(احتمالاً بات ادمین کانال نیست یا دسترسی ویرایش پیام‌های دیگران را ندارد)"

        if edit_call is not None:
            await edit_call.message.answer(result_text, reply_markup=kb.admin_back_kb("adm_deeplink_tools"))
            await edit_call.answer()
        else:
            await message.answer(result_text, reply_markup=kb.admin_back_kb("adm_deeplink_tools"))

    # -------------------------------------------------------------------
    # پاسخ به پیام پشتیبانی کاربر
    # -------------------------------------------------------------------

    @router.callback_query(F.data.startswith("reply_user:"))
    async def cb_reply_user(call: CallbackQuery, state: FSMContext):
        user_id = callback_id(call.data, "reply_user")
        if user_id is None:
            await call.answer("❌ درخواست نامعتبر است.", show_alert=True)
            return
        conv = (await asyncio.to_thread(db.get_support_conversation, user_id))
        assigned_admin_id = conv["assigned_admin_id"] if conv else None
        if assigned_admin_id and assigned_admin_id != call.from_user.id and not owner_only(call.from_user.id):
            await call.answer(
                "⛔️ این گفتگو در حال حاضر توسط ادمین دیگری پاسخ داده می‌شود.", show_alert=True
            )
            return
        await state.update_data(reply_to_user=user_id)
        await state.set_state(AdminReplyFlow.waiting_reply)
        await call.message.answer(f"متن پاسخ برای کاربر {user_id} را ارسال کنید:")
        await call.answer()

    @router.message(AdminReplyFlow.waiting_reply)
    async def process_reply_to_user(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        user_id = data.get("reply_to_user")
        if not user_id:
            await state.clear()
            return
        conv = (await asyncio.to_thread(db.get_support_conversation, user_id))
        assigned_admin_id = conv["assigned_admin_id"] if conv else None
        if assigned_admin_id and assigned_admin_id != message.from_user.id and not owner_only(message.from_user.id):
            await message.answer(
                "⛔️ این گفتگو در حال حاضر توسط ادمین دیگری پاسخ داده می‌شود.",
                reply_markup=kb.admin_panel_kb(db, is_main_bot),
            )
            await state.clear()
            return
        try:
            await bot.send_message(user_id, f"📩 پاسخ پشتیبانی:\n\n{message.text}")
            if message.text:
                if not owner_only(message.from_user.id):
                    (await asyncio.to_thread(db.set_support_conversation_admin, user_id, message.from_user.id))
                (await asyncio.to_thread(db.add_support_message, user_id, "admin", message.text))
            await _notify_user_inline_menu(bot, user_id)
            await message.answer("✅ پاسخ ارسال شد.", reply_markup=kb.admin_panel_kb(db, is_main_bot))
        except Exception:
            await message.answer("⛔️ ارسال پیام به کاربر با خطا مواجه شد.", reply_markup=kb.admin_panel_kb(db, is_main_bot))
        await state.clear()

    # -------------------------------------------------------------------
    # آمار فروش
    # -------------------------------------------------------------------

    def _fmt_stats_report(stats: dict) -> str:
        def _pct(v):
            if v is None:
                return "—"
            sign = "+" if v > 0 else ""
            return f"{sign}{v}٪"

        lines = [
            f"📊 آمار فروشگاه ({to_jalali_str(stats['start_date'])} تا {to_jalali_str(stats['end_date'])})\n",
            f"👥 کاربران کل: {stats['total_users']:,} | 🆕 جدید در بازه: {stats['new_users']:,}",
            f"✅ سفارش تایید شده: {stats['approved']:,} ({_pct(stats['orders_change_pct'])} نسبت به بازه‌ی قبل)",
            f"⏳ در انتظار: {stats['pending']:,} | ❌ رد شده: {stats['rejected']:,}",
            f"💰 درآمد: {stats['revenue']:,} تومان ({_pct(stats['revenue_change_pct'])})",
            f"📈 نرخ تبدیل: {stats['conversion_rate']}٪ | 🧾 میانگین سبد خرید: {stats['aov']:,} تومان",
            f"🔁 مشتری تکراری: {stats['repeat_customers']:,} از {stats['total_customers']:,} ({stats['repeat_customer_rate']}٪)",
            f"🤝 درآمد رفرال: {stats['referral_revenue']:,} | مستقیم: {stats['direct_revenue']:,} تومان",
            f"🎫 تیکت: {stats['tickets_created']:,} ثبت‌شده، {stats['tickets_open']:,} باز",
        ]
        if stats["avg_ticket_response_minutes"] is not None:
            lines.append(f"⏱ میانگین زمان پاسخ اول: {stats['avg_ticket_response_minutes']} دقیقه")
        if stats["top_products"]:
            lines.append("\n🏆 پرفروش‌ترین محصولات:")
            for i, p in enumerate(stats["top_products"][:5], 1):
                lines.append(f"{i}. {p['name']} — {p['orders']:,} فروش، {p['revenue']:,} تومان")
        if stats["low_stock_products"]:
            lines.append("\n⚠️ موجودی کم:")
            for p in stats["low_stock_products"][:8]:
                lines.append(f"• {p['name']}: {p['unused']} کانفیگ باقی‌مانده")
        return "\n".join(lines)

    @router.callback_query(F.data == "adm_stats")
    async def cb_admin_stats(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        stats = await asyncio.to_thread(db.get_full_stats, None, None)
        await replace_admin_view(call, _fmt_stats_report(stats), reply_markup=kb.admin_stats_period_kb(7))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_stats_p:"))
    async def cb_admin_stats_period(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        days = int(call.data.split(":", 1)[1])
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=days - 1)).isoformat()
        stats = await asyncio.to_thread(db.get_full_stats, start_date, end_date)
        await replace_admin_view(call, _fmt_stats_report(stats), reply_markup=kb.admin_stats_period_kb(days))
        await call.answer()

    # -------------------------------------------------------------------
    # بکاپ و بازیابی
    # -------------------------------------------------------------------
    # فقط مالک اصلی بات (owner_only) به این بخش دسترسی دارد، چون بازیابی
    # یعنی جایگزینی کامل دیتابیس فعلی و برگشت‌ناپذیر است.

    @router.callback_query(F.data == "adm_backup_menu")
    async def cb_backup_menu(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await replace_admin_view(call, 
            "🗄 بکاپ و بازیابی دیتابیس\n\n"
            "• «دریافت بکاپ فوری» یک نسخه از دیتابیس فعلی را همین الان برایت می‌فرستد.\n"
            "• «بازیابی از فایل بکاپ» دیتابیس فعلی را با فایلی که آپلود می‌کنی جایگزین می‌کند "
            "(این کار قابل بازگشت نیست مگر با بکاپ دیگری).",
            reply_markup=kb.admin_backup_menu_kb(),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_backup_now")
    async def cb_backup_now(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await call.answer("⏳ در حال گرفتن بکاپ...")
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(db.db_path)), "backups")
        try:
            backup_path = await asyncio.to_thread(create_backup, db.db_path, backup_dir, 14)
        except Exception:
            return await call.message.answer("❌ گرفتن بکاپ ناموفق بود.")
        if not backup_path:
            return await call.message.answer("❌ فایل دیتابیس پیدا نشد.")
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "backup_create", "دریافت بکاپ فوری از طریق بات"))
        await call.message.answer_document(
            FSInputFile(backup_path), caption="🗄 بکاپ فوری دیتابیس"
        )

    @router.callback_query(F.data == "adm_restore_start")
    async def cb_restore_start(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminRestoreBackup.waiting_file)
        await safe_edit(call, 
            "♻️ فایل بکاپ (.db) را همین‌جا به‌صورت Document ارسال کن.\n\n"
            "⚠️ توجه: بعد از تایید، کل دیتابیس فعلی با این فایل جایگزین می‌شود.",
            reply_markup=kb.admin_restore_waiting_kb(),
        )
        await call.answer()

    @router.callback_query(AdminRestoreBackup.waiting_file, F.data == "adm_restore_cancel_wait")
    async def cb_restore_cancel_wait(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await safe_edit(call, "❌ بازیابی لغو شد.", reply_markup=kb.admin_back_kb())
        await call.answer()

    @router.message(AdminRestoreBackup.waiting_file, F.document)
    async def on_restore_file(message: Message, state: FSMContext):
        if not owner_only(message.from_user.id):
            return
        doc = message.document
        if not doc.file_name.lower().endswith((".db", ".sqlite", ".sqlite3")):
            return await message.answer("❌ فایل باید پسوند .db یا .sqlite داشته باشد. دوباره ارسال کن.")

        tmp_dir = tempfile.mkdtemp(prefix="restore_")
        tmp_path = os.path.join(tmp_dir, "uploaded.db")
        file = await message.bot.get_file(doc.file_id)
        await message.bot.download_file(file.file_path, destination=tmp_path)

        if not is_valid_sqlite_db(tmp_path):
            return await message.answer("❌ این فایل یک دیتابیس sqlite معتبر نیست. عملیات لغو شد.")

        await state.update_data(restore_tmp_path=tmp_path)
        await state.set_state(AdminRestoreBackup.waiting_confirm)
        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        await message.answer(
            f"📦 فایل دریافت شد ({size_mb:.1f} مگابایت).\n\n"
            "⚠️ با تایید، دیتابیس فعلی جایگزین می‌شود (یک نسخه از وضعیت فعلی هم قبلش ذخیره می‌شود). "
            "مطمئنی؟",
            reply_markup=kb.admin_restore_confirm_kb(),
        )

    @router.message(AdminRestoreBackup.waiting_file)
    async def on_restore_file_wrong_type(message: Message):
        if not owner_only(message.from_user.id):
            return
        await message.answer("❌ باید فایل بکاپ را به‌صورت Document ارسال کنی، نه متن یا عکس.")

    @router.callback_query(AdminRestoreBackup.waiting_confirm, F.data == "adm_restore_confirm")
    async def cb_restore_confirm(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        tmp_path = data.get("restore_tmp_path")
        await state.clear()
        if not tmp_path or not os.path.exists(tmp_path):
            return await safe_edit(call, "❌ فایل موقت پیدا نشد، دوباره تلاش کن.")

        await safe_edit(call, "⏳ در حال بازیابی...")
        try:
            await asyncio.to_thread(restore_backup, db, db.db_path, tmp_path)
        except Exception as e:
            return await safe_edit(call, f"❌ بازیابی ناموفق بود: {e}")
        else:
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "backup_restore", "بازیابی دیتابیس از فایل بکاپ آپلودی"))
        finally:
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass

        await safe_edit(call, 
            "✅ دیتابیس با موفقیت بازیابی شد.\n"
            "از نسخه‌ی قبلی هم یک بکاپ ایمن (pre_restore) کنار دیتابیس ذخیره شد."
        )
        await call.answer()

    @router.callback_query(AdminRestoreBackup.waiting_confirm, F.data == "adm_restore_cancel")
    async def cb_restore_cancel(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        tmp_path = data.get("restore_tmp_path")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass
        await state.clear()
        await safe_edit(call, "❌ بازیابی لغو شد.", reply_markup=kb.admin_back_kb())
        await call.answer()

    # -------------------------------------------------------------------
    # دستور متنی برای دسترسی سریع
    # -------------------------------------------------------------------

    @router.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        if not admin_only(message.from_user.id):
            return
        await state.clear()
        await message.answer("🔧 پنل مدیریت:", reply_markup=kb.admin_panel_kb(db, is_main_bot))

    return router
