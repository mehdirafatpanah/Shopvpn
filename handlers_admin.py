from i18n import tr
# -*- coding: utf-8 -*-
"""
هندلرهای پنل مدیریت

این فایل هم مثل handlers_user.py یک تابع کارخانه‌ای دارد: create_admin_router(db, ...).
هر بات (اصلی یا نمایندگی) پنل مدیریت کامل و مستقل خودش را از همین یک کد می‌سازد.
"""

import os
import re
import secrets
import hashlib
import html
import asyncio
from datetime import date, datetime, timedelta
import tempfile
import logging
import zipfile

from aiogram import Router, F, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, FSInputFile, BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.filters import Command, StateFilter
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from force_join import is_channel_member

import keyboards as kb
from database import Database, MENU_BUTTON_META
from config import RESELLER_DBS_DIR, resolve_db_path, ADMIN_PANEL_URL, BOT_TOKEN
from config_delivery import (
    deliver_config_to_user, build_qr_bytes, has_qr_background, qr_background_enabled,
    save_qr_background, remove_qr_background,
)
from jalali import to_jalali_str
from stock_alerts import check_and_notify_low_stock
from backup import (
    create_backup, restore_backup, is_valid_sqlite_db, push_backup_sftp,
    test_sftp_connection, backup_and_notify, create_full_backup, restore_full_backup,
)
import crypto_payment
import abangateway_payment
import blupal_payment
import noapay_payment
import extra_gateway_admin
import ai_support
import admin_tools
import bulk_gifts
import report_router
import tutorial_hub
from service_alerts import normalize_channel
from notification_i18n import send_telegram
from panel_providers import (
    get_provider, PanelError, PanelUsernameTakenError, PANEL_TYPE_LABELS,
    SUB_BASE_URL_PANEL_TYPES, INBOUND_SELECT_PANEL_TYPES, parse_xui_inbound_ids,
    SINGLE_INBOUND_PANEL_TYPES, TOKEN_ONLY_PANEL_TYPES, SECRET_PROMPTS, TEMPLATE_PROMPTS, TEMPLATE_VALUE_LABELS,
)
from reseller_auto_provision import provision_auto_config, ProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from renewal_engine import execute_renewal, RenewalError
from states import (
    AdminCreateDiscount,
    AdminBulkDiscount,
    AdminUserManage,
    AdminConfigManage,
    AdminCreateWalletGift,
    AdminAddCategory,
    AdminAddProduct,
    AdminEditProduct,
    AdminAddConfigs,
    AdminAddTestConfigs,
    AdminAddTestPlan,
    AdminEditTestPlan, AdminCleanupSettings,
    AdminForceJoin,
    AdminServiceAlertChannel,
    AdminEditButton,
    AdminSetCard,
    AdminSetPlisio,
    AdminSetAbanGateway,
    AdminSetBlupal,
    AdminSetNoapay,
    AdminC2CCard,
    AdminC2CSettings,
    AdminBroadcast,
    AdminXuiInbound,
    AdminXuiRestore,
    AdminBulkGift,
    AdminBulkPrice,
    AdminBulkWalletDeduct,
    AdminBulkWalletCredit,
    AdminDeepLinkTools,
    AdminChannelButton,
    AdminAddAdmin,
    AdminRemoveAdmin,
    AdminChangeRole,
    AdminEditWelcome,
    AdminEditPostDeliveryText,
    AdminSetQrBackground,
    AdminReplyFlow,
    AdminTicketReplyFlow,
    AdminCommissionResellerFlow,
    AdminResellerMembership,
    AdminSetPanelCapacity,
    AdminSetSupportContact,
    AdminAIFaqAdd,
    AdminTutorialDeviceAdd,
    AdminTutorialRename,
    AdminTutorialStepAdd,
    AdminSetGeminiKey,
    AdminSetGroqKey,
    AdminSetOpenRouterKey,
    AdminSetTranslationGeminiKey,
    AdminSetTranslationOpenRouterKey,
    AdminReferralPercent,
    AdminReferralMultilevel,
    AdminReferralCommissionMax,
    AdminReferralRenewalPercent,
    AdminReferralRenewalMax,
    AdminReferralMinPurchase,
    AdminReferralFreeConfigThreshold,
    AdminReferralInviteBonusAmount,
    AdminReferralInviteBonusMax,
    AdminSignupGiftAmount,
    AdminSignupGiftDelay,
    AdminAddResellerBot,
    AdminSetPanelDomain,
    AdminResellerCredit,
    AdminWheelSettings,
    AdminRenewalSettings,
    AdminVolumeReminderSettings,
    AdminConnectAlertSettings,
    AdminEarlyRenewalDiscount,
    AdminStockAlertSettings,
    AdminMinAmountSettings,
    AdminCustomGatewayMinAmount,
    AdminRestoreBackup,
    AdminRestoreFullBackup,
    AdminBackupInterval,
    AdminBackupSecondaryChat,
    AdminReportGroup,
    AdminBackupSftp,
    AdminFactoryReset,
    AdminAddPanelServer,
    AdminSetPanelTemplate,
    AdminPanelServerTransfer,
    AdminLocationTransferSettings,
    AdminSetPanelSubUrl,
    AdminSetPanelSocksProxy,
    AdminAddPricingTier,
    AdminCustomConfigSettings,
    AdminCustomConfigProduct,
    AdminAddCustomConfigProductTier,
    AdminRenewalPricing,
    AdminResetTestConfig,
    ResellerRequestFlow,
    AdminResellerRequestFlow,
    AdminTempMessage,
    AdminUserFullStats,
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
        await answerable.answer(db.get_text('handlers_admin.auto_c59a91f9', 'این نماینده یا توکن راه\u200cاندازی\u200cاش دیگر پیدا نشد؛ دوباره از منوی نمایندگی امتحان کن.'))
        return
    panel_url = _get_admin_panel_url(db)
    if not panel_url:
        await answerable.answer(db.get_text('handlers_admin.auto_bbc6442b', 'هنوز آدرس پنل مدیریت تنظیم نشده.'))
        return

    b_value = reseller_bot["link_slug"] or str(bot_id)
    link = f"{panel_url}/setup?b={b_value}&t={reseller_bot['web_panel_setup_token']}"
    login_link = f"{panel_url}/?b={b_value}"

    is_no_bot = str(reseller_bot["bot_token"] or "").startswith("no-bot:")
    await answerable.answer(
        tr("🌐 لینک راه‌اندازی پنل وب این نماینده:\n\n"
        f"{link}\n\n"
        "این لینک یک‌بارمصرف است؛ نماینده با باز کردنش یک یوزرنیم/پسورد دلخواه برای پنل وب "
        "خودش تنظیم می‌کند (مستقل از پنل بات اصلی، فقط روی دیتابیس خودش).\n\n"
        f"این لینک از طریق {'بات اصلی' if is_no_bot else 'بات خودِ نماینده'} برای نماینده ارسال می‌شود."),
        reply_markup=kb.resbot_webpanel_kb(bot_id),
    )
    (await asyncio.to_thread(db.log_admin_action, 
        admin_id, "reseller_webpanel_enable", f"نماینده #{bot_id} (@{reseller_bot['bot_username'] or ''})",
    ))

    text = (
        "🌐 پنل مدیریت وب برای نمایندگی شما آماده است!\n\n"
        "با باز کردن لینک زیر، یک‌بار یوزرنیم و پسورد دلخواه برای پنل وب خودتان تنظیم کنید "
        "(این لینک فقط یک‌بار کار می‌کند):\n\n"
        f"{link}\n\n"
        "🔗 لینک ثابت ورود پنل وب (برای دفعات بعد، بعد از تنظیم یوزرنیم/پسورد این را بوکمارک کنید):\n"
        f"{login_link}"
    )
    if is_no_bot:
        try:
            temp_bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            try:
                await temp_bot.send_message(reseller_bot["owner_telegram_id"], text)
                sent = True
            finally:
                await temp_bot.session.close()
        except Exception:
            logger.warning("ارسال لینک پنل وب نماینده no-bot از بات اصلی ناموفق بود.", exc_info=True)
            sent = False
    else:
        sent = await _send_via_reseller_bot(reseller_bot["bot_token"], reseller_bot["owner_telegram_id"], text)
    if not sent:
        await answerable.answer(
            db.get_text('handlers_admin.auto_7ab068d6', '⚠️ ارسال خودکار لینک به نماینده ناموفق بود؛ لینک بالا را خودت برایش بفرست.')
        )


def create_admin_router(db, is_main_bot: bool = True, bot_manager=None) -> Router:
    # A dedicated reseller is a near-complete copy of the main bot.  Keep
    # ``is_main_bot`` for genuinely main-only operations (especially reseller
    # management), while ``full_access_bot`` unlocks the normal store/VPN
    # administration features for a dedicated reseller.
    full_access_bot = db.is_full_access_bot(is_main_bot)
    router = Router()
    _bg_lang_tasks: set[str] = set()

    def admin_only(user_id: int) -> bool:
        return db.is_admin(user_id)

    def full_admin_only(user_id: int) -> bool:
        """دسترسی کامل: مالک، مدیر یا ادمین میانی. ادمین با نقش «پشتیبان» اجازه‌ی این اقدامات
        (تنظیمات، مالی، مدیریت محصولات/موجودی) را ندارد."""
        return db.is_full_admin(user_id)

    def panel_server_readiness_text(server) -> str:
        if server["panel_type"] in SUB_BASE_URL_PANEL_TYPES:
            if server["panel_type"] in INBOUND_SELECT_PANEL_TYPES:
                ids = parse_xui_inbound_ids(server)
                if ids and server["xui_sub_base_url"]:
                    ids_text = "، ".join(f"#{i}" for i in ids)
                    return f"{len(ids)} inbound تنظیم شده ({ids_text})"
                return "⚠️ inbound/آدرس Subscription هنوز تنظیم نشده"
            if server["xui_sub_base_url"]:
                return "✅ آدرس Subscription تنظیم شده"
            return "⚠️ آدرس Subscription هنوز تنظیم نشده"
        if server["template_username"]:
            label = TEMPLATE_VALUE_LABELS.get(server["panel_type"])
            if label:
                return f"{label}: «{server['template_username']}»"
            return f"قالب از کاربر «{server['template_username']}»"
        return "⚠️ قالب هنوز تنظیم نشده"

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
                await bot.send_message(user_tg_id, tr("📋 منو:"), reply_markup=inline_kb)
        except Exception:
            pass

    async def _notify_admin_panel_menu(bot: Bot, admin_tg_id: int):
        """بعد از تایید/رد یک رسید یا درخواست، پنل مدیریت (منوی شیشه‌ای) دوباره
        برای همان مدیر ارسال می‌شود؛ چون آن منو به پیام رسید چسبیده بود، نه به چت."""
        try:
            await bot.send_message(admin_tg_id, tr("🔧 پنل مدیریت:"), reply_markup=kb.admin_panel_kb(db, is_main_bot))
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
        await call.answer(db.get_text('handlers_admin.auto_dd587914', '⛔️ این بخش فقط برای مدیران کامل در دسترس است.'), show_alert=True)

    async def deny_mid(call: CallbackQuery):
        await call.answer(db.get_text('handlers_admin.auto_382a28e5', '⛔️ این بخش فقط برای مالک و مدیر کامل در دسترس است.'), show_alert=True)

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
            if "message is not modified" in error:
                return False
            raise

    async def replace_admin_view(call: CallbackQuery, text: str, reply_markup=None, parse_mode=None) -> bool:
        """تغییر منوی ادمین روی همان پیام؛ ترجیحاً بدون حذف/ارسال مجدد پیام.

        قبلاً فقط سه پیام خطای خاص («message is not modified»، «message can't
        be edited»، «message to edit not found») مدیریت می‌شدند و بقیه‌ی
        خطاهای TelegramBadRequest (مثل ویرایش یک پیام عکس/رسید که متن ندارد،
        یا پیامی که خیلی قدیمی شده) کل هندلر را کرش می‌کرد؛ چون بعد از آن
        call.answer() اجرا نمی‌شد، دکمه از دید ادمین هیچ واکنشی نشان نمی‌داد
        («منو برنمی‌گرده»). حالا برای هر خطای غیرمنتظره‌ای، به‌جای کرش، پیام
        قبلی حذف و منوی جدید به‌صورت پیام تازه ارسال می‌شود تا ناوبری همیشه کار
        کند."""
        if call.message is None:
            return False

        kwargs = {"reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode

        try:
            await call.message.edit_text(text, **kwargs)
            return True
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return False
        except Exception:
            pass

        # Fallback: ویرایش به هر دلیلی ممکن نشد؛ پیام قبلی را حذف (در صورت
        # امکان) و همان منو را به‌عنوان پیام تازه بفرست تا ادمین همیشه منو
        # را ببیند.
        try:
            await call.message.delete()
        except Exception:
            pass
        try:
            await call.message.answer(text, **kwargs)
        except Exception:
            return False
        return True

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
        await message.answer(db.get_text('handlers_admin.auto_4741add8', '🔧 پنل مدیریت:'), reply_markup=kb.admin_panel_kb(db, is_main_bot))

    @router.callback_query(F.data == "adm_back_panel")
    async def cb_back_panel(call: CallbackQuery, state: FSMContext):
        if not admin_only(call.from_user.id):
            return await call.answer()
        await state.clear()
        await replace_admin_view(call, "🔧 پنل مدیریت:", reply_markup=kb.admin_panel_kb(db, is_main_bot))
        await call.answer()

    @router.callback_query(F.data == "adm_exit_panel")
    async def cb_exit_admin_panel(call: CallbackQuery, state: FSMContext):
        """خروج کامل از پنل مدیریت (دکمه‌ی «بازگشت» صفحه‌ی اول پنل): برخلاف
        «adm_back_panel» که به داخل خود پنل برمی‌گردد، این دکمه باید کاربر را
        به منوی اصلی بات ببرد. قبلاً از کال‌بک مشترک «back_main» (مخصوص مسیر
        خرید) استفاده می‌شد که فقط پیام را حذف می‌کرد و چیزی جایگزینش نمی‌کرد؛
        چون پنل مدیریت پیام مستقلی است (نه ادامه‌ی یک ری‌پلای-کیبورد تازه باز
        شده)، نتیجه‌اش این بود که بعد از حذف پیام، هیچ منویی برای کاربر باقی
        نمی‌ماند."""
        if not admin_only(call.from_user.id):
            return await call.answer()
        await state.clear()
        try:
            await call.message.delete()
        except Exception:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        welcome = (await asyncio.to_thread(db.get_setting, "welcome_text"))
        await call.message.answer(welcome, reply_markup=kb.menu_for_user(db, call.from_user.id, is_main_bot))
        await _notify_user_inline_menu(call.bot, call.from_user.id)
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
            await call.answer(db.get_text('handlers_admin.auto_9a43de7a', '⚠️ بارگذاری دسته\u200cبندی\u200cها ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data.startswith("adm_cat_toggle:"))
    async def cb_admin_cat_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cat_id = callback_id(call.data, "adm_cat_toggle")
        if cat_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        try:
            if (await asyncio.to_thread(db.get_category, cat_id)) is None:
                return await call.answer(db.get_text('handlers_admin.auto_1da46abb', '⚠️ این دسته\u200cبندی دیگر وجود ندارد.'), show_alert=True)
            (await asyncio.to_thread(db.toggle_category, cat_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "category_toggle", f"دسته‌بندی #{cat_id}"))
            categories = (await asyncio.to_thread(db.get_categories, active_only=False))
            await safe_edit(call, db.get_text('handlers_admin.auto_e7f6733a', '📂 مدیریت دسته\u200cبندی\u200cها:'), kb.admin_categories_kb(categories))
            await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))
        except Exception:
            await call.answer(db.get_text('handlers_admin.auto_0040e660', '⚠️ تغییر وضعیت دسته\u200cبندی ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data.startswith("adm_cat_del:"))
    async def cb_admin_cat_del(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cat_id = callback_id(call.data, "adm_cat_del")
        if cat_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        try:
            if (await asyncio.to_thread(db.get_category, cat_id)) is None:
                return await call.answer(db.get_text('handlers_admin.auto_3c406624', '⚠️ این دسته\u200cبندی قبلاً حذف شده است.'), show_alert=True)
            (await asyncio.to_thread(db.delete_category, cat_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "category_delete", f"دسته‌بندی #{cat_id}"))
            categories = (await asyncio.to_thread(db.get_categories, active_only=False))
            await safe_edit(call, db.get_text('handlers_admin.auto_e7f6733a', '📂 مدیریت دسته\u200cبندی\u200cها:'), kb.admin_categories_kb(categories))
            await call.answer(db.get_text('handlers_admin.auto_333cfcc1', 'دسته\u200cبندی حذف شد.'))
        except Exception:
            await call.answer(db.get_text('handlers_admin.auto_f0a51b8a', '⚠️ حذف دسته\u200cبندی ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data == "adm_cat_add")
    async def cb_admin_cat_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminAddCategory.waiting_name)
        await safe_edit(call, db.get_text('handlers_admin.auto_1935fbea', 'نام دسته\u200cبندی جدید را ارسال کنید:'), reply_markup=kb.admin_back_kb("adm_categories"))
        await call.answer()

    @router.message(AdminAddCategory.waiting_name)
    async def process_add_category(message: Message, state: FSMContext):
        if not admin_only(message.from_user.id):
            return
        name = (message.text or "").strip()
        if not name:
            await message.answer(db.get_text('handlers_admin.auto_b1eeb37b', 'لطفاً نام دسته\u200cبندی را وارد کنید.'))
            return
        if len(name) > 100:
            await message.answer(db.get_text('handlers_admin.auto_72f54ac8', 'نام دسته\u200cبندی نباید بیشتر از ۱۰۰ کاراکتر باشد.'))
            return
        try:
            (await asyncio.to_thread(db.add_category, name))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "category_add", f"دسته‌بندی «{name}»"))
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_83f1db24', '✅ دسته\u200cبندی اضافه شد.'), reply_markup=kb.admin_category_kb(db, is_main_bot, "products"))
        except Exception:
            await message.answer(db.get_text('handlers_admin.auto_0b5d6142', '⚠️ افزودن دسته\u200cبندی ناموفق بود. دوباره تلاش کنید.'))

    # -------------------------------------------------------------------
    # درگاه‌های پرداخت سفارشی — فقط فعال/غیرفعال کردن (ساخت/ویرایش فقط از مینی‌اپ)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_custom_gateways")
    async def cb_admin_custom_gateways(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            gateways = (await asyncio.to_thread(db.list_custom_gateways))
            await replace_admin_view(call, "💠 درگاه‌های پرداخت سفارشی:", kb.admin_custom_gateways_kb(gateways))
            await call.answer()
        except Exception:
            await call.answer(db.get_text('handlers_admin.auto_404586fb', '⚠️ بارگذاری درگاه\u200cها ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data.startswith("adm_customgw_toggle:"))
    async def cb_admin_customgw_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        gw_id = callback_id(call.data, "adm_customgw_toggle")
        if gw_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        try:
            row = (await asyncio.to_thread(db.get_custom_gateway, gw_id))
            if row is None:
                return await call.answer(db.get_text('handlers_admin.auto_ec30fce4', '⚠️ این درگاه دیگر وجود ندارد.'), show_alert=True)
            new_enabled = not bool(row["enabled"])
            (await asyncio.to_thread(db.update_custom_gateway, gw_id, enabled=new_enabled))
            (await asyncio.to_thread(
                db.log_admin_action, call.from_user.id, "custom_gateway_toggle",
                f"درگاه سفارشی «{row['name']}» {'فعال' if new_enabled else 'غیرفعال'} شد.",
            ))
            gateways = (await asyncio.to_thread(db.list_custom_gateways))
            await safe_edit(call, db.get_text('handlers_admin.auto_fe3d10d1', '💠 درگاه\u200cهای پرداخت سفارشی:'), kb.admin_custom_gateways_kb(gateways))
            await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))
        except Exception:
            await call.answer(db.get_text('handlers_admin.auto_78598de2', '⚠️ تغییر وضعیت درگاه ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data.startswith("adm_customgw_minamt:"))
    async def cb_admin_customgw_minamt(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        gw_id = callback_id(call.data, "adm_customgw_minamt")
        if gw_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        row = (await asyncio.to_thread(db.get_custom_gateway, gw_id))
        if row is None:
            return await call.answer(db.get_text('handlers_admin.auto_ec30fce4', '⚠️ این درگاه دیگر وجود ندارد.'), show_alert=True)
        await state.update_data(customgw_minamt_id=gw_id)
        await state.set_state(AdminCustomGatewayMinAmount.waiting_value)
        current = int(row["min_amount"] or 0) if "min_amount" in row.keys() else 0
        await safe_edit(call, 
            f"🧮 حداقل مبلغ واریزی برای درگاه «{row['name']}» چند تومان باشد؟\n"
            f"مقدار فعلی: {current:,} تومان\n"
            "برای بدون‌محدودیت، عدد 0 بفرست. فقط عدد ارسال کن:",
            reply_markup=kb.admin_back_kb("adm_custom_gateways"),
        )
        await call.answer()

    @router.message(AdminCustomGatewayMinAmount.waiting_value)
    async def process_customgw_minamt(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", "")
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_27a6c10b', 'لطفاً فقط عدد ارسال کنید.'))
            return
        data = await state.get_data()
        gw_id = data.get("customgw_minamt_id")
        row = (await asyncio.to_thread(db.get_custom_gateway, gw_id)) if gw_id else None
        if not row:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_ec30fce4', '⚠️ این درگاه دیگر وجود ندارد.'))
            return
        (await asyncio.to_thread(db.update_custom_gateway, gw_id, min_amount=int(text)))
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "custom_gateway_min_amount",
            f"حداقل مبلغ درگاه «{row['name']}» روی {int(text):,} تومان تنظیم شد.",
        ))
        await state.clear()
        gateways = (await asyncio.to_thread(db.list_custom_gateways))
        await message.answer(
            f"{tr('✅ حداقل مبلغ درگاه')} «{row['name']}» {tr('روی')} {int(text):,} {tr('تومان')} {tr('تنظیم شد.')}",
            reply_markup=kb.admin_custom_gateways_kb(gateways),
        )

    # -------------------------------------------------------------------
    # حداقل مبلغ پرداخت‌ها (شارژ کیف پول + روش‌های داخلی)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_min_amount_settings")
    async def cb_admin_min_amount_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, 
            "🧮 حداقل مبلغ پرداخت‌ها و سقف کیف پول:\n\n"
            "برای هر روش، پایین‌تر از این مبلغ اجازه‌ی پرداخت داده نمی‌شود (0 یعنی بدون محدودیت).\n"
            "سقف موجودی کیف پول: اگر موجودی فعلی کاربر به‌علاوه‌ی مبلغ شارژ از این عدد بیشتر شود، شارژ رد می‌شود (0 یعنی بدون محدودیت).\n"
            "حداقل مبلغ هر درگاه سفارشی از داخل «درگاه‌های پرداخت سفارشی» قابل تنظیم است.",
            reply_markup=kb.min_amount_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_minamt_edit:"))
    async def cb_admin_minamt_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        key = call.data.split(":", 1)[1]
        valid_keys = {k for k, _ in kb.MIN_AMOUNT_SETTINGS_ITEMS}
        if key not in valid_keys:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        await state.update_data(min_amount_key=key)
        await state.set_state(AdminMinAmountSettings.waiting_value)
        current = db.get_setting(key, "0")
        await safe_edit(call, 
            f"مقدار فعلی: {int(current or 0):,} تومان\nمبلغ جدید را فقط به‌صورت عدد ارسال کن (0 یعنی بدون محدودیت):",
            reply_markup=kb.admin_back_kb("adm_min_amount_settings"),
        )
        await call.answer()

    @router.message(AdminMinAmountSettings.waiting_value)
    async def process_minamt_value(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", "")
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_27a6c10b', 'لطفاً فقط عدد ارسال کنید.'))
            return
        data = await state.get_data()
        key = data.get("min_amount_key")
        if not key:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_0e29be08', '⚠️ خطایی رخ داد، دوباره تلاش کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, key, text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "min_amount_setting", f"{key} = {text}"))
        await state.clear()
        await message.answer(
            tr(f"✅ مقدار روی {int(text):,} تومان تنظیم شد."), reply_markup=kb.min_amount_settings_kb(db)
        )

    # -------------------------------------------------------------------
    # F12 — ویرایش گروهی قیمت محصولات
    # -------------------------------------------------------------------
    @router.callback_query(F.data == "adm_bulk_price")
    async def cb_bulk_price(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id): return await deny_mid(call)
        cats=await asyncio.to_thread(db.get_categories, active_only=False)
        await state.clear(); await state.set_state(AdminBulkPrice.waiting_category)
        await safe_edit(call, db.get_text('handlers_admin.auto_4a791679', '💰 ویرایش گروهی قیمت\n\nابتدا محدوده\u200cی دسته\u200cبندی را انتخاب کنید:'), reply_markup=kb.admin_bulk_price_scope_kb(cats, []))
        await call.answer()

    @router.callback_query(AdminBulkPrice.waiting_category, F.data.startswith("adm_bprice_cat:"))
    async def cb_bulk_price_category(call: CallbackQuery, state: FSMContext):
        val=call.data.split(":",1)[1]
        await state.update_data(category_id=None if val=="all" else int(val))
        panels=await asyncio.to_thread(db.get_panel_servers, active_only=True)
        await state.set_state(AdminBulkPrice.waiting_panel)
        await safe_edit(call,db.get_text('handlers_admin.auto_0910c18d', '🖥 محدوده\u200cی پنل را انتخاب کنید:'),reply_markup=kb.admin_bulk_price_panel_kb(panels)); await call.answer()

    @router.callback_query(AdminBulkPrice.waiting_panel, F.data.startswith("adm_bprice_panel:"))
    async def cb_bulk_price_panel(call: CallbackQuery, state: FSMContext):
        val=call.data.split(":",1)[1]
        await state.update_data(panel_server_id=None if val=="all" else int(val))
        await state.set_state(AdminBulkPrice.waiting_mode)
        await safe_edit(call,db.get_text('handlers_admin.auto_dfe71107', 'نوع تغییر قیمت را انتخاب کنید:'),reply_markup=kb.admin_bulk_price_mode_kb()); await call.answer()

    @router.callback_query(AdminBulkPrice.waiting_mode, F.data.startswith("adm_bprice_mode:"))
    async def cb_bulk_price_mode(call: CallbackQuery, state: FSMContext):
        mode=call.data.split(":",1)[1]
        await state.update_data(mode=mode); await state.set_state(AdminBulkPrice.waiting_value)
        prompt="درصد تغییر را وارد کنید. برای کاهش، عدد منفی بفرستید؛ مثال: 10 یا -10" if mode=="percent" else "مبلغ تغییر را به تومان وارد کنید. برای کاهش، عدد منفی بفرستید؛ مثال: 50000 یا -50000"
        await safe_edit(call,prompt,reply_markup=kb.admin_back_kb("adm_bulk_price")); await call.answer()

    @router.message(AdminBulkPrice.waiting_value)
    async def msg_bulk_price_value(message: Message, state: FSMContext):
        raw=(message.text or "").replace(",","").replace("٬","").strip()
        try: value=float(raw)
        except ValueError:
            return await message.answer(db.get_text('handlers_admin.auto_2f123b37', '❌ مقدار نامعتبر است.'))
        data=await state.get_data()
        if data.get("mode")=="percent" and (value <= -100 or value > 1000):
            return await message.answer(db.get_text('handlers_admin.auto_dbd31c71', '❌ درصد باید بیشتر از ۱۰۰- و حداکثر ۱۰۰۰ باشد.'))
        if data.get("mode")=="fixed" and abs(value)>10_000_000_000:
            return await message.answer(db.get_text('handlers_admin.auto_b40a09fe', '❌ مبلغ تغییر بیش از حد مجاز است.'))
        await state.update_data(value=value); await state.set_state(AdminBulkPrice.waiting_rounding)
        await message.answer(db.get_text('handlers_admin.auto_0dc2fa54', 'گرد کردن قیمت نهایی را انتخاب کنید:'),reply_markup=kb.admin_bulk_price_rounding_kb())

    @router.callback_query(AdminBulkPrice.waiting_rounding, F.data.startswith("adm_bprice_round:"))
    async def cb_bulk_price_round(call: CallbackQuery, state: FSMContext):
        rounding=int(call.data.split(":",1)[1]); data=await state.get_data(); data["rounding"]=rounding
        changes=await asyncio.to_thread(db.preview_bulk_price_change,data.get("category_id"),data.get("panel_server_id"),data.get("mode"),data.get("value"),rounding)
        if not changes:
            await state.clear(); return await call.answer(db.get_text('handlers_admin.auto_81d4fce5', 'محصولی با این فیلترها پیدا نشد.'),show_alert=True)
        invalid=[c for c in changes if int(c["new_price"]) <= 0]
        if invalid:
            await state.clear()
            return await call.answer(tr(f"❌ تغییر باعث قیمت صفر/منفی برای {len(invalid)} محصول می‌شود؛ عملیات انجام نشد."),show_alert=True)
        # جلوگیری از قیمت‌های صفر/منفی در اجرای نهایی.
        preview=changes[:20]
        lines=[f"💰 پیش‌نمایش تغییر قیمت — {len(changes)} محصول",""]
        for c in preview: lines.append(f"• {c['name']}: {c['old_price']:,} ← {c['new_price']:,} تومان")
        if len(changes)>20: lines.append(f"… و {len(changes)-20} محصول دیگر")
        lines.append("\nبا تأیید، تغییرات در یک تراکنش اعمال و snapshot قبلی برای Undo ذخیره می‌شود.")
        await state.update_data(changes=changes); await state.set_state(AdminBulkPrice.waiting_confirm)
        await safe_edit(call,"\n".join(lines),reply_markup=kb.admin_bulk_price_confirm_kb()); await call.answer()

    @router.callback_query(AdminBulkPrice.waiting_confirm, F.data == "adm_bprice_confirm")
    async def cb_bulk_price_confirm(call: CallbackQuery, state: FSMContext):
        data=await state.get_data(); changes=data.get("changes") or []
        log_id=await asyncio.to_thread(db.apply_bulk_price_change,changes,"products")
        await asyncio.to_thread(db.log_admin_action,call.from_user.id,"bulk_price_change",f"F12 | {len(changes)} محصول | log={log_id}")
        await state.clear(); await safe_edit(call,f"✅ قیمت {len(changes)} محصول با موفقیت تغییر کرد.\nشناسه تغییر: #{log_id}\nبرای بازگردانی از «Undo قیمت‌ها» استفاده کن.",reply_markup=kb.admin_back_kb("adm_products")); await call.answer()

    @router.callback_query(AdminBulkPrice.waiting_confirm, F.data == "adm_bprice_cancel")
    async def cb_bulk_price_cancel(call: CallbackQuery, state: FSMContext):
        await state.clear(); await safe_edit(call,db.get_text('handlers_admin.auto_e071e360', '❌ تغییر قیمت لغو شد.'),reply_markup=kb.admin_back_kb("adm_products")); await call.answer()

    @router.callback_query(F.data == "adm_bulk_price_undo")
    async def cb_bulk_price_undo_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id): return await deny_mid(call)
        logs=await asyncio.to_thread(db.list_price_change_logs,10)
        await safe_edit(call,db.get_text('handlers_admin.auto_8ec0ba14', '↩️ بازگردانی تغییرات قیمت:'),reply_markup=kb.admin_bulk_price_undo_kb(logs)); await call.answer()

    @router.callback_query(F.data.startswith("adm_bprice_undo:"))
    async def cb_bulk_price_undo(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id): return await deny_mid(call)
        log_id=int(call.data.split(":",1)[1]); ok=await asyncio.to_thread(db.undo_bulk_price_change,log_id)
        if not ok: return await call.answer(db.get_text('handlers_admin.auto_d5493a1d', 'این تغییر قبلاً بازگردانی شده یا وجود ندارد.'),show_alert=True)
        await asyncio.to_thread(db.log_admin_action,call.from_user.id,"bulk_price_undo",f"F12 | log={log_id}")
        await call.answer(db.get_text('handlers_admin.auto_ee8d4678', '✅ قیمت\u200cها بازگردانی شدند.'),show_alert=True)
        logs=await asyncio.to_thread(db.list_price_change_logs,10)
        await safe_edit(call,db.get_text('handlers_admin.auto_8ec0ba14', '↩️ بازگردانی تغییرات قیمت:'),reply_markup=kb.admin_bulk_price_undo_kb(logs))

    # -------------------------------------------------------------------
    # کاهش گروهی موجودی کیف پول
    # -------------------------------------------------------------------
    @router.callback_query(F.data == "adm_bulk_wallet_deduct")
    async def cb_bulk_wallet_deduct(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await state.set_state(AdminBulkWalletDeduct.waiting_status)
        await safe_edit(
            call,
            "➖ کاهش گروهی موجودی کیف پول\n\nابتدا وضعیت کاربران هدف را انتخاب کنید:",
            reply_markup=kb.admin_bulk_wallet_status_kb(),
        )
        await call.answer()

    @router.callback_query(AdminBulkWalletDeduct.waiting_status, F.data.startswith("adm_bwd_status:"))
    async def cb_bulk_wallet_status(call: CallbackQuery, state: FSMContext):
        status = call.data.split(":", 1)[1]
        await state.update_data(status_filter=status)
        await state.set_state(AdminBulkWalletDeduct.waiting_usertype)
        await safe_edit(call, "نوع کاربران هدف را انتخاب کنید:", reply_markup=kb.admin_bulk_wallet_usertype_kb())
        await call.answer()

    @router.callback_query(AdminBulkWalletDeduct.waiting_usertype, F.data.startswith("adm_bwd_utype:"))
    async def cb_bulk_wallet_usertype(call: CallbackQuery, state: FSMContext):
        utype = call.data.split(":", 1)[1]
        await state.update_data(user_type_filter=utype)
        await state.set_state(AdminBulkWalletDeduct.waiting_amount)
        await safe_edit(
            call,
            "مبلغ ثابتی که از کیف پول هر کاربر کم می‌شود را به تومان ارسال کنید (فقط عدد مثبت):",
            reply_markup=kb.admin_back_kb("adm_bulk_wallet_deduct"),
        )
        await call.answer()

    @router.message(AdminBulkWalletDeduct.waiting_amount)
    async def msg_bulk_wallet_amount(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        raw = (message.text or "").replace(",", "").replace("٬", "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            return await message.answer(tr("❌ مبلغ نامعتبر است؛ فقط عدد مثبت ارسال کنید."))
        amount = int(raw)
        if amount > 10_000_000_000:
            return await message.answer(tr("❌ مبلغ بیش از حد مجاز است."))
        data = await state.get_data()
        rows = await asyncio.to_thread(
            db.preview_bulk_wallet_deduct,
            data.get("status_filter", "all"), data.get("user_type_filter", "all"), amount,
        )
        if not rows:
            await state.clear()
            return await message.answer(tr("کاربری با این فیلترها پیدا نشد."), reply_markup=kb.admin_back_kb("adm_cat:finance"))
        await state.update_data(amount=amount, user_ids=[r["telegram_id"] for r in rows])
        await state.set_state(AdminBulkWalletDeduct.waiting_confirm)
        total = amount * len(rows)
        preview = rows[:20]
        lines = [
            f"➖ پیش‌نمایش کاهش موجودی — {len(rows)} کاربر",
            f"💰 مبلغ هر کاربر: {amount:,} تومان",
            f"💵 مجموع کسر: {total:,} تومان", "",
        ]
        for r in preview:
            label = f"@{r['username']}" if r["username"] else (r["first_name"] or str(r["telegram_id"]))
            lines.append(f"• {label}: {r['balance_before']:,} ← {r['balance_after']:,} تومان")
        if len(rows) > 20:
            lines.append(f"… و {len(rows)-20} کاربر دیگر")
        debt_count = sum(1 for r in rows if r["balance_after"] < 0)
        if debt_count:
            lines.append(f"\n⚠️ {debt_count} کاربر پس از این کاهش بدهکار می‌شوند.")
        lines.append("\nبا تأیید، این مبلغ بلافاصله از موجودی همه‌ی کاربران بالا کسر می‌شود.")
        await message.answer("\n".join(lines), reply_markup=kb.admin_bulk_wallet_confirm_kb())

    @router.callback_query(AdminBulkWalletDeduct.waiting_confirm, F.data == "adm_bwd_confirm")
    async def cb_bulk_wallet_confirm(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        data = await state.get_data()
        user_ids = data.get("user_ids") or []
        amount = data.get("amount") or 0
        updated = await asyncio.to_thread(
            db.apply_bulk_wallet_deduct, user_ids, amount, f"کاهش گروهی توسط ادمین ({call.from_user.id})",
        )
        await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "bulk_wallet_deduct",
            f"{updated} کاربر | {amount:,} تومان هرکدام | فیلتر: {data.get('status_filter')}/{data.get('user_type_filter')}",
        )
        await state.clear()
        await safe_edit(
            call, f"✅ موجودی {updated} کاربر هرکدام {amount:,} تومان کاهش یافت.",
            reply_markup=kb.admin_back_kb("adm_cat:finance"),
        )
        await call.answer()

    @router.callback_query(AdminBulkWalletDeduct.waiting_confirm, F.data == "adm_bwd_cancel")
    async def cb_bulk_wallet_cancel(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await safe_edit(call, "❌ کاهش گروهی موجودی لغو شد.", reply_markup=kb.admin_back_kb("adm_cat:finance"))
        await call.answer()

    # -------------------------------------------------------------------
    # افزایش گروهی موجودی کیف پول + اعلان به کاربران
    # -------------------------------------------------------------------
    @router.callback_query(F.data == "adm_bulk_wallet_credit")
    async def cb_bulk_wallet_credit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await state.set_state(AdminBulkWalletCredit.waiting_status)
        await safe_edit(
            call,
            "➕ افزایش گروهی موجودی کیف پول\n\nابتدا وضعیت کاربران هدف را انتخاب کنید:",
            reply_markup=kb.admin_bulk_wallet_status_kb(),
        )
        await call.answer()

    @router.callback_query(AdminBulkWalletCredit.waiting_status, F.data.startswith("adm_bwd_status:"))
    async def cb_bulk_wallet_credit_status(call: CallbackQuery, state: FSMContext):
        status = call.data.split(":", 1)[1]
        await state.update_data(status_filter=status)
        await state.set_state(AdminBulkWalletCredit.waiting_usertype)
        await safe_edit(call, "نوع کاربران هدف را انتخاب کنید:", reply_markup=kb.admin_bulk_wallet_usertype_kb())
        await call.answer()

    @router.callback_query(AdminBulkWalletCredit.waiting_usertype, F.data.startswith("adm_bwd_utype:"))
    async def cb_bulk_wallet_credit_usertype(call: CallbackQuery, state: FSMContext):
        utype = call.data.split(":", 1)[1]
        await state.update_data(user_type_filter=utype)
        await state.set_state(AdminBulkWalletCredit.waiting_amount)
        await safe_edit(
            call,
            "مبلغ ثابتی که به کیف پول هر کاربر اضافه می‌شود را به تومان ارسال کنید (فقط عدد مثبت):",
            reply_markup=kb.admin_back_kb("adm_bulk_wallet_credit"),
        )
        await call.answer()

    @router.message(AdminBulkWalletCredit.waiting_amount)
    async def msg_bulk_wallet_credit_amount(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        raw = (message.text or "").replace(",", "").replace("٬", "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            return await message.answer(tr("❌ مبلغ نامعتبر است؛ فقط عدد مثبت ارسال کنید."))
        amount = int(raw)
        if amount > 10_000_000_000:
            return await message.answer(tr("❌ مبلغ بیش از حد مجاز است."))
        data = await state.get_data()
        rows = await asyncio.to_thread(
            db.preview_bulk_wallet_credit,
            data.get("status_filter", "all"), data.get("user_type_filter", "all"), amount,
        )
        if not rows:
            await state.clear()
            return await message.answer(tr("کاربری با این فیلترها پیدا نشد."), reply_markup=kb.admin_back_kb("adm_cat:finance"))
        await state.update_data(amount=amount, user_ids=[r["telegram_id"] for r in rows])
        await state.set_state(AdminBulkWalletCredit.waiting_message)
        lines = [
            f"➕ پیشنمایش افزایش موجودی — {len(rows)} کاربر",
            f"💰 مبلغ هر کاربر: {amount:,} تومان",
            f"💵 مجموع افزایش: {amount * len(rows):,} تومان", "",
        ]
        for r in rows[:20]:
            label = f"@{r['username']}" if r["username"] else (r["first_name"] or str(r["telegram_id"]))
            lines.append(f"• {label}: {r['balance_before']:,} ← {r['balance_after']:,} تومان")
        if len(rows) > 20:
            lines.append(f"… و {len(rows)-20} کاربر دیگر")
        lines.append("\nحالا متن اعلان را ارسال کنید. برای اعلان پیشفرض فقط «پیشفرض» بنویسید.")
        await message.answer("\n".join(lines))

    @router.message(AdminBulkWalletCredit.waiting_message)
    async def msg_bulk_wallet_credit_message(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        msg = (message.text or "").strip()
        if not msg:
            return await message.answer(tr("❌ متن اعلان خالی است."))
        data = await state.get_data()
        amount = int(data.get("amount") or 0)
        count = len(data.get("user_ids") or [])
        if msg in {"پیشفرض", "پیشفرض", "default"}:
            msg = f"💰 مبلغ {amount:,} تومان به کیف پول شما اضافه شد.\nموجودی جدید خود را می‌توانید از بخش کیف پول مشاهده کنید."
        elif len(msg) > 1000:
            return await message.answer(tr("❌ متن اعلان نباید بیشتر از ۱۰۰۰ کاراکتر باشد."))
        await state.update_data(notification=msg)
        await state.set_state(AdminBulkWalletCredit.waiting_confirm)
        await message.answer(
            tr(f"⚠️ تأیید نهایی\n\nتعداد کاربران: {count:,}\nمبلغ هر کاربر: {amount:,} تومان\nمجموع: {amount * count:,} تومان\n\n📢 متن اعلان:\n{msg}\n\nبا تأیید، موجودی کاربران افزایش پیدا می‌کند و اعلان برای آن‌ها ارسال می‌شود."),
            reply_markup=kb.admin_bulk_wallet_credit_confirm_kb(),
        )

    @router.callback_query(AdminBulkWalletCredit.waiting_confirm, F.data == "adm_bwc_confirm")
    async def cb_bulk_wallet_credit_confirm(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        data = await state.get_data()
        user_ids = data.get("user_ids") or []
        amount = int(data.get("amount") or 0)
        notification = data.get("notification") or ""
        note = f"افزایش گروهی توسط ادمین ({call.from_user.id})"
        updated = await asyncio.to_thread(db.apply_bulk_wallet_credit, user_ids, amount, note)
        await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "bulk_wallet_credit",
            f"{updated} کاربر | {amount:,} تومان هرکدام | فیلتر: {data.get('status_filter')}/{data.get('user_type_filter')}",
        )
        sent = 0
        failed = 0
        for uid in user_ids:
            try:
                await bot.send_message(uid, notification)
                sent += 1
            except Exception:
                failed += 1
        await state.clear()
        await safe_edit(
            call,
            f"✅ موجودی {updated} کاربر هرکدام {amount:,} تومان افزایش یافت.\n📢 اعلان: {sent} ارسال شد، {failed} ناموفق بود.",
            reply_markup=kb.admin_back_kb("adm_cat:finance"),
        )
        await call.answer()

    @router.callback_query(AdminBulkWalletCredit.waiting_confirm, F.data == "adm_bwc_cancel")
    async def cb_bulk_wallet_credit_cancel(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await safe_edit(call, "❌ افزایش گروهی موجودی لغو شد.", reply_markup=kb.admin_back_kb("adm_cat:finance"))
        await call.answer()

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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        products = (await asyncio.to_thread(db.get_products, cat_id, active_only=False))
        if not products:
            await call.answer(db.get_text('handlers_admin.auto_aa02e69e', 'محصولی در این دسته وجود ندارد.'), show_alert=True)
            return
        await safe_edit(call, db.get_text('handlers_admin.auto_c8caee2c', 'لیست محصولات این دسته\u200cبندی:'), reply_markup=kb.admin_products_list_kb(db, products))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_prod_toggle:"))
    async def cb_admin_prod_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_toggle")
        if product_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        (await asyncio.to_thread(db.toggle_product, product_id))
        product = (await asyncio.to_thread(db.get_product, product_id))
        if product is None:
            await call.answer(db.get_text('handlers_admin.auto_fa9715cb', '⚠️ این محصول دیگر وجود ندارد.'), show_alert=True)
            return
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "product_toggle", f"محصول «{product['name']}»"))
        products = (await asyncio.to_thread(db.get_products, product["category_id"], active_only=False))
        await safe_edit(call, db.get_text('handlers_admin.auto_c8caee2c', 'لیست محصولات این دسته\u200cبندی:'), reply_markup=kb.admin_products_list_kb(db, products))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_prod_del:"))
    async def cb_admin_prod_del(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_del")
        if product_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        product = (await asyncio.to_thread(db.get_product, product_id))
        cat_id = product["category_id"] if product else None
        (await asyncio.to_thread(db.delete_product, product_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "product_delete", f"محصول «{product['name'] if product else product_id}»"))
        if cat_id:
            products = (await asyncio.to_thread(db.get_products, cat_id, active_only=False))
            await safe_edit(call, db.get_text('handlers_admin.auto_c8caee2c', 'لیست محصولات این دسته\u200cبندی:'), reply_markup=kb.admin_products_list_kb(db, products))
        await call.answer(db.get_text('handlers_admin.auto_1002ca8f', 'محصول حذف شد.'))

    @router.callback_query(F.data.startswith("adm_prod_srv:"))
    async def cb_admin_prod_srv(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_srv")
        if product_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product or not product["provision_server_id"]:
            return await call.answer(db.get_text('handlers_admin.auto_d6cec4a7', '⚠️ این محصول اتصال مستقیم به پنل ندارد.'), show_alert=True)
        if not full_access_bot:
            return await call.answer(db.get_text('handlers_admin.auto_27d04dd7', '⛔️ این بخش فقط برای بات اصلی یا نمایندگی کامل در دسترس است.'), show_alert=True)
        await safe_edit(call, 
            f"🔌 پنل/اینباند جدید برای «{product['name']}» را انتخاب کنید:\n\n"
            "ساخت‌های بعدیِ همین محصول از پنل/اینباند جدید انجام می‌شود؛ سرویس‌های قبلاً ساخته‌شده تغییر نمی‌کنند.",
            reply_markup=kb.admin_edit_product_provision_kb(db, product_id),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_prod_set_srv:"))
    async def cb_admin_prod_set_srv(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, product_id_s, server_id_s = call.data.split(":")
            product_id, server_id = int(product_id_s), int(server_id_s)
        except (ValueError, IndexError):
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        if not full_access_bot:
            return await call.answer(db.get_text('handlers_admin.auto_27d04dd7', '⛔️ این بخش فقط برای بات اصلی یا نمایندگی کامل در دسترس است.'), show_alert=True)
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product or not product["provision_server_id"]:
            return await call.answer(db.get_text('handlers_admin.auto_3ba0d977', '⚠️ این محصول دیگر وجود ندارد یا اتصال مستقیم به پنل ندارد.'), show_alert=True)
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            return await call.answer(db.get_text('handlers_admin.auto_bbdc5d08', '⚠️ این پنل دیگر وجود ندارد.'), show_alert=True)
        (await asyncio.to_thread(db.edit_product, product_id, provision_server_id=server_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "product_server_edit",
                                  f"محصول «{product['name']}» → پنل «{server['name']}»"))
        products = (await asyncio.to_thread(db.get_products, product["category_id"], active_only=False))
        await safe_edit(call, db.get_text('handlers_admin.auto_c8caee2c', 'لیست محصولات این دسته\u200cبندی:'), reply_markup=kb.admin_products_list_kb(db, products))
        await call.answer(db.get_text('handlers_admin.auto_7736dbee', '✅ پنل/اینباند به\u200cروزرسانی شد.'))

    @router.callback_query(F.data.startswith("adm_prod_vol:"))
    async def cb_admin_prod_vol(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_vol")
        if product_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product or not product["is_auto_provision"]:
            return await call.answer(db.get_text('handlers_admin.auto_d0d88ea3', '⚠️ این محصول خودکار نیست.'), show_alert=True)
        await state.update_data(editing_product_id=product_id)
        await state.set_state(AdminEditProduct.waiting_volume)
        hint = " (یا 0 برای نامحدود)" if product["provision_server_id"] else ""
        back_cb = f"adm_prod_cat:{product['category_id']}" if product["category_id"] is not None else "adm_products"
        await safe_edit(call, f"حجم جدید «{product['name']}» چند گیگابایت باشد؟ فقط عدد صحیح{hint}:",
                         reply_markup=kb.admin_back_kb(back_cb))
        await call.answer()

    @router.message(AdminEditProduct.waiting_volume)
    async def process_prod_edit_volume(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        product_id = data.get("editing_product_id")
        product = (await asyncio.to_thread(db.get_product, product_id))
        is_unlimited_ok = bool(product and product["provision_server_id"])
        if not text.isdigit() or (int(text) <= 0 and not is_unlimited_ok):
            hint = " (یا 0 برای نامحدود)" if is_unlimited_ok else ""
            await message.answer(tr(f"لطفاً فقط عدد صحیح و بزرگ‌تر از صفر وارد کنید{hint}. مثال: 30"))
            return
        (await asyncio.to_thread(db.edit_product, product_id, auto_provision_volume_gb=int(text)))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "product_volume_edit",
                                  f"محصول «{product['name'] if product else product_id}» → {text} گیگ"))
        await state.clear()
        if product:
            products = (await asyncio.to_thread(db.get_products, product["category_id"], active_only=False))
            await message.answer(db.get_text('handlers_admin.auto_2f18448b', '✅ حجم به\u200cروزرسانی شد.'), reply_markup=kb.admin_products_list_kb(db, products))
        else:
            await message.answer(db.get_text('handlers_admin.auto_2f18448b', '✅ حجم به\u200cروزرسانی شد.'))

    @router.callback_query(F.data.startswith("adm_prod_users:"))
    async def cb_admin_prod_users(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_users")
        if product_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product or not product["is_auto_provision"]:
            return await call.answer(db.get_text('handlers_admin.auto_d0d88ea3', '⚠️ این محصول خودکار نیست.'), show_alert=True)
        if product["provision_server_id"]:
            from user_limit import server_supports
            server = await asyncio.to_thread(db.get_panel_server, product["provision_server_id"])
            if server and not server_supports(server):
                return await call.answer(tr("⚠️ پنل این محصول از محدودیت کاربر همزمان پشتیبانی نمی‌کند (فقط 3X-UI و علیرضا)."), show_alert=True)
        await state.update_data(editing_product_id=product_id)
        await state.set_state(AdminEditProduct.waiting_user_base)
        back_cb = f"adm_prod_cat:{product['category_id']}" if product["category_id"] is not None else "adm_products"
        await safe_edit(
            call,
            f"👥 کاربر همزمان «{product['name']}»\n\n"
            "چند کاربر همزمان در قیمت این محصول گنجانده شده؟ (عدد بین ۱ تا ۲۰)\n"
            "این تعداد روی هر سرویسِ ساخته‌شده از این محصول اعمال می‌شود.\n"
            "عدد 0 یعنی بدون محدودیت (فقط پنل‌های 3X-UI و علیرضا پشتیبانی می‌شوند):",
            reply_markup=kb.admin_back_kb(back_cb),
        )
        await call.answer()

    async def _finish_prod_user_limit(message: Message, state: FSMContext, product, base: int, extra_price: int, max_users: int):
        await asyncio.to_thread(db.set_product_user_limit, product["id"], extra_price, max_users, base)
        if not base:
            summary, done = "بدون محدودیت", "✅ محدودیت کاربر غیرفعال شد."
        elif extra_price > 0 and max_users > base:
            summary = f"{base} کاربر، امکان افزایش تا {max_users} (هر کاربر اضافه {extra_price:,} تومان)"
            done = "✅ محدودیت کاربر ذخیره شد."
        else:
            summary, done = f"{base} کاربر ثابت (بدون امکان افزایش)", "✅ محدودیت کاربر ذخیره شد."
        await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "product_user_limit_edit",
            f"محصول «{product['name']}» → {summary}",
        )
        await state.clear()
        products = (await asyncio.to_thread(db.get_products, product["category_id"], active_only=False))
        await message.answer(done, reply_markup=kb.admin_products_list_kb(db, products))

    @router.message(AdminEditProduct.waiting_user_base)
    async def process_prod_user_base(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) > 20:
            await message.answer(tr("لطفاً یک عدد صحیح بین ۰ تا ۲۰ وارد کنید. (0 = بدون محدودیت)"))
            return
        data = await state.get_data()
        product = (await asyncio.to_thread(db.get_product, data.get("editing_product_id")))
        if not product:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_fa9715cb', '⚠️ این محصول دیگر وجود ندارد.'))
            return
        base = int(text)
        if base == 0:
            await _finish_prod_user_limit(message, state, product, 0, 0, 0)
            return
        await state.update_data(user_base=base)
        await state.set_state(AdminEditProduct.waiting_user_extra_price)
        await message.answer(tr(
            "قیمت هر کاربر اضافه چند تومان باشد؟\n"
            "مشتری بعداً می‌تواند از «سرویس‌های من» تعداد کاربر را افزایش دهد و فقط مابه‌التفاوت را بپردازد.\n"
            "عدد 0 یعنی افزایش ممکن نباشد:"
        ))

    @router.message(AdminEditProduct.waiting_user_extra_price)
    async def process_prod_user_extra_price(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_5be2f405', 'لطفاً فقط عدد صحیح (تومان) وارد کنید. مثال: 20000 یا 0 برای غیرفعال'))
            return
        data = await state.get_data()
        product = (await asyncio.to_thread(db.get_product, data.get("editing_product_id")))
        base = int(data.get("user_base") or 0)
        if not product or base < 1:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_0a091587', '⚠️ درخواست منقضی شد. دوباره از لیست محصولات شروع کنید.'))
            return
        if int(text) == 0:
            await _finish_prod_user_limit(message, state, product, base, 0, 0)
            return
        if base >= 20:
            await _finish_prod_user_limit(message, state, product, base, 0, 0)
            return
        await state.update_data(user_extra_price=int(text))
        await state.set_state(AdminEditProduct.waiting_user_max)
        await message.answer(tr(f"حداکثر تعداد کاربر همزمانی که مشتری می‌تواند داشته باشد چند باشد؟ (عدد بین {base + 1} تا ۲۰)"))

    @router.message(AdminEditProduct.waiting_user_max)
    async def process_prod_user_max(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        data = await state.get_data()
        base = int(data.get("user_base") or 0)
        if not text.isdigit() or not base < int(text) <= 20:
            await message.answer(tr(f"لطفاً یک عدد صحیح بین {base + 1} تا ۲۰ وارد کنید."))
            return
        extra_price = int(data.get("user_extra_price") or 0)
        product = (await asyncio.to_thread(db.get_product, data.get("editing_product_id")))
        if not product or base < 1 or extra_price <= 0:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_0a091587', '⚠️ درخواست منقضی شد. دوباره از لیست محصولات شروع کنید.'))
            return
        await _finish_prod_user_limit(message, state, product, base, extra_price, int(text))

    @router.callback_query(F.data.startswith("adm_prod_paymethods:"))
    async def cb_admin_prod_paymethods(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prod_paymethods")
        if product_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        product = (await asyncio.to_thread(db.get_product, product_id))
        if not product:
            return await call.answer(db.get_text('handlers_admin.auto_fa9715cb', '⚠️ این محصول دیگر وجود ندارد.'), show_alert=True)
        await safe_edit(call, 
            f"💳 روش‌های پرداخت مجاز برای «{product['name']}»:\n\n"
            "با لمس هر گزینه، فعال/غیرفعال می‌شود. اگر «همه‌ی روش‌ها» تیک بخورد، این محصول از هر روش پرداخت فعالی قابل خرید است "
            "(با اضافه‌شدن هر درگاه جدید در آینده هم خودکار برایش فعال می‌شود).",
            reply_markup=kb.admin_product_payment_methods_kb(db, product_id),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_prodpm_all:"))
    async def cb_admin_prodpm_all(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_prodpm_all")
        if product_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        (await asyncio.to_thread(db.set_product_payment_methods, product_id, None))
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_4694af5b', '💳 روش\u200cهای پرداخت مجاز:'),
            reply_markup=kb.admin_product_payment_methods_kb(db, product_id),
        )
        await call.answer(db.get_text('handlers_admin.auto_d074ae83', 'همه\u200cی روش\u200cها فعال شدند.'))

    @router.callback_query(F.data.startswith("adm_prodpm_tgl:"))
    async def cb_admin_prodpm_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, product_id_s, method_key = call.data.split(":", 2)
            product_id = int(product_id_s)
        except (ValueError, IndexError):
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)

        catalog_keys = [item["key"] for item in (await asyncio.to_thread(db.get_payment_methods_catalog))]
        allowed = (await asyncio.to_thread(db.get_product_payment_methods, product_id))
        current = set(catalog_keys) if allowed is None else set(allowed)

        if method_key in current:
            current.discard(method_key)
        else:
            current.add(method_key)

        if not current:
            return await call.answer(db.get_text('handlers_admin.auto_be79c4fa', '⚠️ حداقل یک روش پرداخت باید برای این محصول فعال بماند.'), show_alert=True)

        if current == set(catalog_keys):
            (await asyncio.to_thread(db.set_product_payment_methods, product_id, None))
        else:
            (await asyncio.to_thread(db.set_product_payment_methods, product_id, sorted(current)))

        await safe_edit(call, 
            db.get_text('handlers_admin.auto_4694af5b', '💳 روش\u200cهای پرداخت مجاز:'),
            reply_markup=kb.admin_product_payment_methods_kb(db, product_id),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_paymethods:"))
    async def cb_admin_ccp_paymethods(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_paymethods")
        if product_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        product = (await asyncio.to_thread(db.get_custom_config_product, product_id))
        if not product:
            return await call.answer(db.get_text('handlers_admin.auto_fa9715cb', '⚠️ این محصول دیگر وجود ندارد.'), show_alert=True)
        await safe_edit(call, 
            f"💳 روش‌های پرداخت مجاز برای «{product['name']}»:\n\n"
            "با لمس هر گزینه، فعال/غیرفعال می‌شود. اگر «همه‌ی روش‌ها» تیک بخورد، این پلن (چه فلت چه پله‌ای/پلکانی) "
            "از هر روش پرداخت فعالی قابل خرید است.",
            reply_markup=kb.admin_custom_config_product_payment_methods_kb(db, product_id),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccppm_all:"))
    async def cb_admin_ccppm_all(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccppm_all")
        if product_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
        (await asyncio.to_thread(db.set_custom_config_product_payment_methods, product_id, None))
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_4694af5b', '💳 روش\u200cهای پرداخت مجاز:'),
            reply_markup=kb.admin_custom_config_product_payment_methods_kb(db, product_id),
        )
        await call.answer(db.get_text('handlers_admin.auto_d074ae83', 'همه\u200cی روش\u200cها فعال شدند.'))

    @router.callback_query(F.data.startswith("adm_ccppm_tgl:"))
    async def cb_admin_ccppm_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, product_id_s, method_key = call.data.split(":", 2)
            product_id = int(product_id_s)
        except (ValueError, IndexError):
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)

        catalog_keys = [item["key"] for item in (await asyncio.to_thread(db.get_payment_methods_catalog))]
        allowed = (await asyncio.to_thread(db.get_custom_config_product_payment_methods, product_id))
        current = set(catalog_keys) if allowed is None else set(allowed)

        if method_key in current:
            current.discard(method_key)
        else:
            current.add(method_key)

        if not current:
            return await call.answer(db.get_text('handlers_admin.auto_180456bb', '⚠️ حداقل یک روش پرداخت باید برای این پلن فعال بماند.'), show_alert=True)

        if current == set(catalog_keys):
            (await asyncio.to_thread(db.set_custom_config_product_payment_methods, product_id, None))
        else:
            (await asyncio.to_thread(db.set_custom_config_product_payment_methods, product_id, sorted(current)))

        await safe_edit(call, 
            db.get_text('handlers_admin.auto_4694af5b', '💳 روش\u200cهای پرداخت مجاز:'),
            reply_markup=kb.admin_custom_config_product_payment_methods_kb(db, product_id),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_wallet_paymethods")
    async def cb_admin_wallet_paymethods(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, 
            "👛 روش‌های پرداخت مجاز برای «شارژ کیف پول»:\n\n"
            "با لمس هر گزینه، فعال/غیرفعال می‌شود. اگر «همه‌ی روش‌ها» تیک بخورد، شارژ کیف پول از هر روش پرداخت "
            "فعالی ممکن است (با اضافه‌شدن هر درگاه جدید در آینده هم خودکار برایش فعال می‌شود). این تنظیم فقط "
            "روی شارژ کیف پول اثر دارد و مستقل از محدودیت روش پرداخت هر محصول است.",
            reply_markup=kb.admin_wallet_payment_methods_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_walletpm_all")
    async def cb_admin_walletpm_all(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        (await asyncio.to_thread(db.set_wallet_topup_payment_methods, None))
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_0f1da972', '👛 روش\u200cهای پرداخت مجاز برای شارژ کیف پول:'),
            reply_markup=kb.admin_wallet_payment_methods_kb(db),
        )
        await call.answer(db.get_text('handlers_admin.auto_d074ae83', 'همه\u200cی روش\u200cها فعال شدند.'))

    @router.callback_query(F.data.startswith("adm_walletpm_tgl:"))
    async def cb_admin_walletpm_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            method_key = call.data.split(":", 1)[1]
        except IndexError:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)

        catalog_keys = [item["key"] for item in (await asyncio.to_thread(db.get_payment_methods_catalog))]
        allowed = (await asyncio.to_thread(db.get_wallet_topup_payment_methods))
        current = set(catalog_keys) if allowed is None else set(allowed)

        if method_key in current:
            current.discard(method_key)
        else:
            current.add(method_key)

        if not current:
            return await call.answer(db.get_text('handlers_admin.auto_a0556fd3', '⚠️ حداقل یک روش پرداخت باید برای شارژ کیف پول فعال بماند.'), show_alert=True)

        if current == set(catalog_keys):
            (await asyncio.to_thread(db.set_wallet_topup_payment_methods, None))
        else:
            (await asyncio.to_thread(db.set_wallet_topup_payment_methods, sorted(current)))

        await safe_edit(call, 
            db.get_text('handlers_admin.auto_0f1da972', '👛 روش\u200cهای پرداخت مجاز برای شارژ کیف پول:'),
            reply_markup=kb.admin_wallet_payment_methods_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_cc_paymethods")
    async def cb_admin_cc_paymethods(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, 
            "🛠 روش‌های پرداخت مجاز برای «ساخت کانفیگ شخصی»:\n\n"
            "با لمس هر گزینه، فعال/غیرفعال می‌شود. اگر «همه‌ی روش‌ها» تیک بخورد، ساخت کانفیگ شخصی از هر روش "
            "پرداخت فعالی ممکن است. پلنی که محدودیت خودش را دارد بر این تنظیم اولویت دارد.",
            reply_markup=kb.admin_custom_config_payment_methods_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_ccpm_all")
    async def cb_admin_ccpm_all(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        (await asyncio.to_thread(db.set_custom_config_payment_methods, None))
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_2f456a3f', '🛠 روش\u200cهای پرداخت مجاز برای ساخت کانفیگ شخصی:'),
            reply_markup=kb.admin_custom_config_payment_methods_kb(db),
        )
        await call.answer(db.get_text('handlers_admin.auto_d074ae83', 'همه\u200cی روش\u200cها فعال شدند.'))

    @router.callback_query(F.data.startswith("adm_ccpm_tgl:"))
    async def cb_admin_ccpm_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            method_key = call.data.split(":", 1)[1]
        except IndexError:
            return await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)

        catalog_keys = [item["key"] for item in (await asyncio.to_thread(db.get_payment_methods_catalog))]
        allowed = (await asyncio.to_thread(db.get_custom_config_payment_methods))
        current = set(catalog_keys) if allowed is None else set(allowed)

        if method_key in current:
            current.discard(method_key)
        else:
            current.add(method_key)

        if not current:
            return await call.answer(db.get_text('handlers_admin.auto_9797a6e4', '⚠️ حداقل یک روش پرداخت باید برای ساخت کانفیگ شخصی فعال بماند.'), show_alert=True)

        if current == set(catalog_keys):
            (await asyncio.to_thread(db.set_custom_config_payment_methods, None))
        else:
            (await asyncio.to_thread(db.set_custom_config_payment_methods, sorted(current)))

        await safe_edit(call, 
            db.get_text('handlers_admin.auto_2f456a3f', '🛠 روش\u200cهای پرداخت مجاز برای ساخت کانفیگ شخصی:'),
            reply_markup=kb.admin_custom_config_payment_methods_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_prod_add")
    async def cb_admin_prod_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        categories = (await asyncio.to_thread(db.get_categories, active_only=True))
        if not categories:
            await call.answer(db.get_text('handlers_admin.auto_44099dc8', 'ابتدا باید حداقل یک دسته\u200cبندی فعال بسازید.'), show_alert=True)
            return
        await state.set_state(AdminAddProduct.waiting_category)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_f07f2021', 'محصول جدید در کدام دسته\u200cبندی اضافه شود؟'),
            reply_markup=kb.admin_pick_category_kb(categories, "adm_newprod_cat"),
        )
        await call.answer()

    @router.callback_query(AdminAddProduct.waiting_category, F.data.startswith("adm_newprod_cat:"))
    async def cb_pick_category_for_new_product(call: CallbackQuery, state: FSMContext):
        cat_id = callback_id(call.data, "adm_newprod_cat")
        if cat_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        await state.update_data(category_id=cat_id)
        await state.set_state(AdminAddProduct.waiting_name)
        await safe_edit(call, db.get_text('handlers_admin.auto_c30cb647', 'نام محصول را ارسال کنید:'), reply_markup=kb.admin_back_kb("adm_cat:products"))
        await call.answer()

    @router.message(AdminAddProduct.waiting_name)
    async def process_product_name(message: Message, state: FSMContext):
        await state.update_data(name=message.text.strip())
        await state.set_state(AdminAddProduct.waiting_price)
        await message.answer(db.get_text('handlers_admin.auto_5b64c2fe', 'قیمت محصول را به تومان و فقط عدد وارد کنید (مثال: 150000):'))

    @router.message(AdminAddProduct.waiting_price)
    async def process_product_price(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", "")
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_8b2d6a4d', 'لطفاً فقط عدد وارد کنید. مثال: 150000'))
            return
        await state.update_data(price=int(text))
        await state.set_state(AdminAddProduct.waiting_desc)
        await message.answer(db.get_text('handlers_admin.auto_4967620a', 'توضیحات محصول را وارد کنید (یا برای رد شدن بنویسید: -)'))

    @router.message(AdminAddProduct.waiting_desc)
    async def process_product_desc(message: Message, state: FSMContext):
        desc = "" if message.text.strip() == "-" else message.text.strip()
        await state.update_data(description=desc)
        await state.set_state(AdminAddProduct.waiting_duration)
        await message.answer(
            db.get_text('handlers_admin.auto_0d1c2cc3', 'مدت اعتبار این سرویس چند روز است؟ فقط عدد وارد کنید (مثال: 30).\nاین عدد برای محاسبه\u200cی تاریخ یادآوری اتمام سرویس به کاربر استفاده می\u200cشود.')
        )

    @router.message(AdminAddProduct.waiting_duration)
    async def process_product_duration(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_0199a788', 'لطفاً فقط عدد صحیح و بزرگ\u200cتر از صفر وارد کنید. مثال: 30'))
            return
        await state.update_data(duration_days=int(text))

        if full_access_bot:
            await state.set_state(AdminAddProduct.waiting_provision_choice)
            await message.answer(
                db.get_text('handlers_admin.auto_3da796e7', 'منبع کانفیگ این محصول چیست؟\n\n📦 بانک کانفیگ: از لینک\u200cهای از پیش آماده\u200cشده تحویل داده می\u200cشود.\n🔌 اتصال مستقیم به پنل: هر بار خرید، همان لحظه یک کاربر واقعی روی پنل انتخابی ساخته می\u200cشود (نیازی به پر کردن بانک کانفیگ نیست).'),
                reply_markup=kb.admin_new_product_source_kb(),
            )
            return

        # نمایندگی سطح محدود: به پنل/بانک لینک دسترسی ندارد. نمایندگی کامل مانند بات اصلی مسیر منبع کانفیگ را می‌بیند.
        await state.set_state(AdminAddProduct.waiting_auto_provision_volume)
        await message.answer(db.get_text('handlers_admin.auto_d8ef9615', 'این محصول چند گیگابایت باشد؟ فقط عدد وارد کنید (مثال: 30):'))

    @router.callback_query(AdminAddProduct.waiting_provision_choice, F.data.startswith("adm_newprod_src:"))
    async def cb_pick_product_source(call: CallbackQuery, state: FSMContext):
        source = call.data.split(":", 1)[1]
        if source == "bank":
            await state.update_data(payment_methods=None)
            await state.set_state(AdminAddProduct.waiting_payment_methods)
            await safe_edit(call, 
                db.get_text('handlers_admin.auto_0677173c', '💳 این محصول با کدام روش(های) پرداخت قابل خرید باشد؟\n\nبا لمس هر گزینه، فعال/غیرفعال می\u200cشود. اگر «همه\u200cی روش\u200cها» تیک بخورد، این محصول از هر روش پرداخت فعالی قابل خرید است (با اضافه\u200cشدن هر درگاه جدید در آینده هم خودکار برایش فعال می\u200cشود).'),
                reply_markup=kb.admin_new_product_payment_methods_kb(db, None),
            )
            await call.answer()
            return

        # اتصال مستقیم به پنل
        servers = (await asyncio.to_thread(db.get_panel_servers, active_only=True))
        if not servers:
            await call.answer(db.get_text('handlers_admin.auto_80677e1c', 'ابتدا باید حداقل یک پنل فعال در بخش «مدیریت پنل\u200cها» تعریف کنید.'), show_alert=True)
            return
        await state.set_state(AdminAddProduct.waiting_provision_server)
        await safe_edit(call, db.get_text('handlers_admin.auto_4b39bcbb', 'این محصول به کدام پنل وصل شود؟'), reply_markup=kb.admin_pick_provision_server_kb(servers))
        await call.answer()

    @router.callback_query(AdminAddProduct.waiting_provision_server, F.data.startswith("adm_newprod_srv:"))
    async def cb_pick_provision_server(call: CallbackQuery, state: FSMContext):
        server_id = callback_id(call.data, "adm_newprod_srv")
        if server_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        await state.update_data(provision_server_id=server_id)
        data = await state.get_data()
        await state.set_state(AdminAddProduct.waiting_provision_duration_mode)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_41f1c921', '⏳ مدت اعتبار این محصول چطور باشد؟\n\n«محدود» یعنی همان مدتی که قبلاً وارد کردید؛ «نامحدود» یعنی این سرویس هیچ\u200cوقت روی پنل منقضی نمی\u200cشود.'),
            reply_markup=kb.admin_newprod_duration_mode_kb(data.get("duration_days", 30)),
        )
        await call.answer()

    @router.callback_query(AdminAddProduct.waiting_provision_duration_mode, F.data.startswith("adm_newprod_durmode:"))
    async def cb_pick_provision_duration_mode(call: CallbackQuery, state: FSMContext):
        mode = call.data.split(":", 1)[1]
        if mode == "unlimited":
            await state.update_data(duration_days=0)
        await state.set_state(AdminAddProduct.waiting_auto_provision_volume_mode)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_11190e90', '📦 حجم این محصول چطور باشد؟\n\n«مقدار مشخص» یعنی یک عدد گیگابایت مشخص می\u200cکنید؛ «نامحدود» یعنی این سرویس هیچ محدودیت حجمی ندارد.'),
            reply_markup=kb.admin_newprod_volume_mode_kb(),
        )
        await call.answer()

    @router.callback_query(AdminAddProduct.waiting_auto_provision_volume_mode, F.data.startswith("adm_newprod_volmode:"))
    async def cb_pick_provision_volume_mode(call: CallbackQuery, state: FSMContext):
        mode = call.data.split(":", 1)[1]
        if mode == "unlimited":
            await state.update_data(auto_provision_volume_gb=0, payment_methods=None)
            text_next, markup_next = await _newprod_after_volume(state)
            await safe_edit(call, text_next, reply_markup=markup_next)
            await call.answer()
            return

        await state.set_state(AdminAddProduct.waiting_auto_provision_volume)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_d8ef9615', 'این محصول چند گیگابایت باشد؟ فقط عدد وارد کنید (مثال: 30):'),
            reply_markup=None,
        )
        await call.answer()

    @router.message(AdminAddProduct.waiting_auto_provision_volume)
    async def process_product_auto_provision_volume(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        is_direct_panel = bool(data.get("provision_server_id"))
        if not text.isdigit() or (int(text) <= 0 and not is_direct_panel):
            hint = " (یا 0 برای نامحدود)" if is_direct_panel else ""
            await message.answer(tr(f"لطفاً فقط عدد صحیح و بزرگ‌تر از صفر وارد کنید{hint}. مثال: 30"))
            return
        await state.update_data(auto_provision_volume_gb=int(text), payment_methods=None)
        text_next, markup_next = await _newprod_after_volume(state)
        await message.answer(text_next, reply_markup=markup_next)

    # -------------------------------------------------------------------
    # تعداد کاربر همزمان حین ساخت محصول خودکار (بعد از حجم، قبل از روش‌های پرداخت)
    # -------------------------------------------------------------------

    def _newprod_payment_prompt():
        return (
            db.get_text('handlers_admin.auto_0677173c', '💳 این محصول با کدام روش(های) پرداخت قابل خرید باشد؟\n\nبا لمس هر گزینه، فعال/غیرفعال می\u200cشود. اگر «همه\u200cی روش\u200cها» تیک بخورد، این محصول از هر روش پرداخت فعالی قابل خرید است (با اضافه\u200cشدن هر درگاه جدید در آینده هم خودکار برایش فعال می\u200cشود).'),
            kb.admin_new_product_payment_methods_kb(db, None),
        )

    async def _newprod_after_volume(state: FSMContext):
        """اگر پنل انتخاب‌شده از limitIp پشتیبانی کند، اول تعداد کاربر همزمان را می‌پرسد؛ وگرنه مستقیم روش‌های پرداخت."""
        data = await state.get_data()
        ask_users = True
        server_id = data.get("provision_server_id")
        if server_id:
            from user_limit import server_supports
            server = await asyncio.to_thread(db.get_panel_server, server_id)
            ask_users = bool(server and server_supports(server))
        await state.update_data(base_users=0, user_extra_price=0, user_max=0)
        if ask_users:
            await state.set_state(AdminAddProduct.waiting_base_users)
            return (
                tr(
                    "👥 چند کاربر همزمان (اتصال هم‌زمان) در قیمت این محصول گنجانده شود؟\n"
                    "عدد بین ۱ تا ۲۰ بفرستید؛ این تعداد روی هر سرویسِ ساخته‌شده اعمال می‌شود.\n"
                    "عدد 0 یعنی بدون محدودیت (فقط پنل‌های 3X-UI و علیرضا پشتیبانی می‌شوند)."
                ),
                None,
            )
        await state.set_state(AdminAddProduct.waiting_payment_methods)
        return _newprod_payment_prompt()

    async def _newprod_to_payment_methods(message: Message, state: FSMContext):
        await state.set_state(AdminAddProduct.waiting_payment_methods)
        text_pm, markup_pm = _newprod_payment_prompt()
        await message.answer(text_pm, reply_markup=markup_pm)

    @router.message(AdminAddProduct.waiting_base_users)
    async def process_newprod_base_users(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) > 20:
            await message.answer(tr("لطفاً یک عدد صحیح بین ۰ تا ۲۰ وارد کنید. (0 = بدون محدودیت)"))
            return
        base = int(text)
        await state.update_data(base_users=base, user_extra_price=0, user_max=0)
        if base == 0 or base >= 20:
            await _newprod_to_payment_methods(message, state)
            return
        await state.set_state(AdminAddProduct.waiting_user_extra_price)
        await message.answer(tr(
            "قیمت هر کاربر اضافه چند تومان باشد؟\n"
            "مشتری بعداً می‌تواند از «سرویس‌های من» تعداد کاربر را افزایش دهد و فقط مابه‌التفاوت را بپردازد.\n"
            "عدد 0 یعنی افزایش ممکن نباشد:"
        ))

    @router.message(AdminAddProduct.waiting_user_extra_price)
    async def process_newprod_user_extra_price(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(tr("لطفاً فقط عدد صحیح (تومان) وارد کنید. مثال: 20000 یا 0 برای غیرفعال"))
            return
        if int(text) == 0:
            await state.update_data(user_extra_price=0, user_max=0)
            await _newprod_to_payment_methods(message, state)
            return
        data = await state.get_data()
        base = int(data.get("base_users") or 1)
        await state.update_data(user_extra_price=int(text))
        await state.set_state(AdminAddProduct.waiting_user_max)
        await message.answer(tr(f"حداکثر تعداد کاربر همزمانی که مشتری می‌تواند داشته باشد چند باشد؟ (عدد بین {base + 1} تا ۲۰)"))

    @router.message(AdminAddProduct.waiting_user_max)
    async def process_newprod_user_max(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        data = await state.get_data()
        base = int(data.get("base_users") or 1)
        if not text.isdigit() or not base < int(text) <= 20:
            await message.answer(tr(f"لطفاً یک عدد صحیح بین {base + 1} تا ۲۰ وارد کنید."))
            return
        await state.update_data(user_max=int(text))
        await _newprod_to_payment_methods(message, state)

    # -------------------------------------------------------------------
    # انتخاب روش‌های پرداخت مجاز حین ساخت محصول (بعد از تکمیل فیلدهای پایه)
    # -------------------------------------------------------------------

    @router.callback_query(AdminAddProduct.waiting_payment_methods, F.data == "newprodpm_all")
    async def cb_newprod_pm_all(call: CallbackQuery, state: FSMContext):
        await state.update_data(payment_methods=None)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_dd40c8d8', '💳 این محصول با کدام روش(های) پرداخت قابل خرید باشد؟'),
            reply_markup=kb.admin_new_product_payment_methods_kb(db, None),
        )
        await call.answer(db.get_text('handlers_admin.auto_d074ae83', 'همه\u200cی روش\u200cها فعال شدند.'))

    @router.callback_query(AdminAddProduct.waiting_payment_methods, F.data.startswith("newprodpm_tgl:"))
    async def cb_newprod_pm_toggle(call: CallbackQuery, state: FSMContext):
        method_key = call.data.split(":", 1)[1]
        catalog_keys = [item["key"] for item in (await asyncio.to_thread(db.get_payment_methods_catalog))]
        data = await state.get_data()
        selected = data.get("payment_methods")
        current = set(catalog_keys) if selected is None else set(selected)

        if method_key in current:
            current.discard(method_key)
        else:
            current.add(method_key)

        if not current:
            return await call.answer(db.get_text('handlers_admin.auto_29d53d44', '⚠️ حداقل یک روش پرداخت باید فعال بماند.'), show_alert=True)

        new_selected = None if current == set(catalog_keys) else sorted(current)
        await state.update_data(payment_methods=new_selected)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_dd40c8d8', '💳 این محصول با کدام روش(های) پرداخت قابل خرید باشد؟'),
            reply_markup=kb.admin_new_product_payment_methods_kb(db, new_selected),
        )
        await call.answer()

    @router.callback_query(AdminAddProduct.waiting_payment_methods, F.data == "newprodpm_done")
    async def cb_newprod_pm_done(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        provision_server_id = data.get("provision_server_id")
        auto_provision_volume_gb = data.get("auto_provision_volume_gb")
        payment_methods = data.get("payment_methods")

        (await asyncio.to_thread(db.add_product, 
            data["category_id"], data["name"], data["price"], data["description"], data["duration_days"],
            is_auto_provision=(auto_provision_volume_gb is not None), auto_provision_volume_gb=auto_provision_volume_gb,
            provision_server_id=provision_server_id, payment_methods=payment_methods,
            base_users=int(data.get("base_users") or 0),
            extra_user_price=int(data.get("user_extra_price") or 0),
            max_users=int(data.get("user_max") or 0),
        ))
        pm_log = "همه" if payment_methods is None else "، ".join(payment_methods)
        if auto_provision_volume_gb is not None:
            volume_log = "نامحدود" if auto_provision_volume_gb == 0 else f"{auto_provision_volume_gb} گیگ"
            duration_log = "نامحدود" if data["duration_days"] == 0 else f"{data['duration_days']} روز"
            log_text = (
                f"محصول «{data['name']}» (خودکار"
                + (" - اتصال مستقیم به پنل" if provision_server_id else "")
                + f"، {volume_log} / {duration_log}) | قیمت: {data['price']:,} | پرداخت: {pm_log}"
            )
            if data.get("base_users"):
                log_text += f" | {int(data['base_users'])} کاربر همزمان"
                if data.get("user_extra_price") and data.get("user_max"):
                    log_text += f" (ارتقا تا {int(data['user_max'])}، +{int(data['user_extra_price']):,} تومان)"
        else:
            log_text = f"محصول «{data['name']}» | قیمت: {data['price']:,} | پرداخت: {pm_log}"
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "product_add", log_text))
        await state.clear()

        if not auto_provision_volume_gb:
            await safe_edit(call, db.get_text('handlers_admin.auto_3e4422b8', '✅ محصول با موفقیت اضافه شد.\nحالا از «بانک کانفیگ» می\u200cتونی لینک\u200cها رو براش اضافه کنی.'))
        elif provision_server_id:
            await safe_edit(call, 
                db.get_text('handlers_admin.auto_5a48dfa0', '✅ محصول با موفقیت اضافه شد.\nهر بار خرید این محصول، خودکار روی پنل انتخابی یک کاربر واقعی ساخته می\u200cشود؛ نیازی به اضافه کردن لینک به بانک کانفیگ نیست.'),
                reply_markup=kb.admin_category_kb(db, is_main_bot, "products"),
            )
        else:
            await safe_edit(call, 
                db.get_text('handlers_admin.auto_ac926166', '✅ محصول با موفقیت اضافه شد.\n⚠️ برای این\u200cکه این محصول واقعاً کار کند، باید توسط ادمین بات اصلی برایت «نماینده» فعال شده و اعتبار حجمی و پنل نمایندگی برایت تنظیم شده باشد.'),
                reply_markup=kb.admin_category_kb(db, is_main_bot, "products"),
            )
        await call.answer()

    # -------------------------------------------------------------------
    # افزودن کانفیگ (بانک لینک) به محصول
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_add_configs")
    async def cb_admin_add_configs(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not full_access_bot:
            await call.answer(db.get_text('handlers_admin.auto_53aa104e', 'این بخش برای نمایندگی سطح محدود فعال نیست.'), show_alert=True)
            return
        products = (await asyncio.to_thread(db.get_all_products))
        if not products:
            await call.answer(db.get_text('handlers_admin.auto_0d101458', 'ابتدا باید یک محصول بسازید.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        await state.update_data(product_id=product_id)
        await state.set_state(AdminAddConfigs.waiting_links)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_1346987b', 'لینک\u200cهای کانفیگ را ارسال کنید (هر لینک در یک خط جداگانه). می\u200cتوانید چند لینک را با هم در یک پیام بفرستید:'),
            reply_markup=kb.admin_back_kb("adm_add_configs"),
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
            await call.answer(db.get_text('handlers_admin.auto_0d101458', 'ابتدا باید یک محصول بسازید.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        product = (await asyncio.to_thread(db.get_product, product_id))
        if product and product["provision_server_id"]:
            try:
                built = await provision_direct(db, product, quantity=1, user_id=call.from_user.id)
            except DirectProvisionError as e:
                await call.answer(f"⛔️ {e}", show_alert=True)
                return
            item = built[0]
            vol_label = "نامحدود" if item["volume_gb"] == 0 else f"{item['volume_gb']} گیگ"
            dur_label = "نامحدود" if item["duration_days"] == 0 else f"{item['duration_days']} روز"
            text = (
                f"🎲 یک کانفیگ از پنل متصل به «{product['name']}» ساخته شد:\n\n"
                f"`{item['subscription_url']}`\n\n"
                f"📦 حجم: {vol_label} | ⏳ مدت: {dur_label}"
            )
            await safe_edit(call, text, parse_mode="Markdown", reply_markup=kb.admin_back_kb("adm_random_cfg"))
            await call.answer(db.get_text('handlers_admin.auto_ce3f553f', 'کانفیگ دریافت شد ✅'))
            return

        result = (await asyncio.to_thread(db.admin_take_random_config, product_id, call.from_user.id))
        if not result:
            await call.answer(db.get_text('handlers_admin.auto_651a47bb', 'کانفیگ آزادی برای این محصول موجود نیست.'), show_alert=True)
            return
        expires_display = to_jalali_str(result.get("expires_at"))
        text = (
            f"🎲 یک کانفیگ رندوم از انبار «{product['name'] if product else 'محصول'}» برداشته و از انبار کم شد:\n\n"
            f"`{result['link']}`\n\n"
            f"⏳ تاریخ انقضا: {expires_display}"
        )
        await safe_edit(call, text, parse_mode="Markdown", reply_markup=kb.admin_back_kb("adm_random_cfg"))
        await call.answer(db.get_text('handlers_admin.auto_ce3f553f', 'کانفیگ دریافت شد ✅'))

    # -------------------------------------------------------------------
    # مدیریت کانفیگ تست: چندمدلی، مثل محصولات (هر پلن پنل/حجم/مدت/پیشوند
    # نام کاربری خودش را دارد). editing_plan_id در FSM data افزودن و ویرایش
    # را از همان state ها رد می‌کند، مثل الگوی محصولات کانفیگ‌ساز (ccp).
    # -------------------------------------------------------------------

    async def _tp_show_view(target, plan_id: int, extra_note: str = ""):
        plan = (await asyncio.to_thread(db.get_test_config_plan, plan_id))
        if not plan:
            return
        text = f"🧪 پلن کانفیگ تست: {plan['name']}" + (f"\n\n{extra_note}" if extra_note else "")
        markup = kb.test_plan_view_kb(db, plan)
        if isinstance(target, CallbackQuery):
            await replace_admin_view(target, text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_test_menu")
    async def cb_admin_test_menu(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await replace_admin_view(call, "🧪 مدیریت کانفیگ تست:", reply_markup=kb.admin_test_menu_kb(db, is_main_bot))
        await call.answer()

    @router.callback_query(F.data == "adm_service_alert_channel")
    async def cb_admin_service_alert_channel(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        channel = (await asyncio.to_thread(db.get_setting, "service_alert_channel", "")) or ""
        text = (
            "📣 کانال اعلان حذف/اتمام کانفیگ\n\n"
            "در این کانال، هنگام اتمام سرویس و حذف کانفیگ پیام اطلاع‌رسانی ارسال می‌شود.\n"
            "ربات باید در کانال ادمین باشد.\n\n"
            f"کانال فعلی: {channel or 'ثبت نشده'}"
        )
        await replace_admin_view(call, text, reply_markup=kb.admin_service_alert_channel_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_service_alert_set_channel")
    async def cb_admin_service_alert_set_channel(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminServiceAlertChannel.waiting_channel)
        await safe_edit(call, "آیدی عددی یا یوزرنیم کانال را بفرستید.\nمثال: `@mychannel`\n\n⚠️ ربات باید از قبل ادمین کانال باشد.", parse_mode="Markdown", reply_markup=kb.admin_back_kb("adm_service_alert_channel"))
        await call.answer()

    @router.message(AdminServiceAlertChannel.waiting_channel)
    async def process_service_alert_channel(message: Message, state: FSMContext, bot: Bot):
        if not senior_admin_only(message.from_user.id):
            return
        channel = normalize_channel(message.text)
        if not channel:
            return await message.answer(tr("❌ آیدی کانال معتبر نیست."))
        try:
            chat = await bot.get_chat(channel)
            member = await bot.get_chat_member(channel, bot.id)
            if member.status not in {"administrator", "creator"}:
                raise ValueError("bot_not_admin")
        except Exception:
            return await message.answer(tr("❌ دسترسی به کانال ممکن نشد. آیدی را بررسی کنید و مطمئن شوید ربات ادمین کانال است."))
        await asyncio.to_thread(db.set_setting, "service_alert_channel", channel)
        await state.clear()
        await message.answer(tr(f"✅ کانال «{chat.title}» برای اعلان‌ها ثبت شد."), reply_markup=kb.admin_service_alert_channel_kb(db))

    @router.callback_query(F.data == "adm_service_alert_clear_channel")
    async def cb_admin_service_alert_clear_channel(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await asyncio.to_thread(db.set_setting, "service_alert_channel", "")
        await safe_edit(call, "📣 کانال اعلان حذف/اتمام کانفیگ\n\nکانال اعلان غیرفعال شد.", reply_markup=kb.admin_service_alert_channel_kb(db))
        await call.answer(tr("کانال حذف شد."))

    @router.callback_query(F.data == "adm_cleanup_settings")
    async def cb_admin_cleanup_settings(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        text = (
            "🧹 پاکسازی خودکار سرویس‌های منقضی\n\n"
            "۰ یعنی خاموش. در حالت dry-run هیچ سرویس روی پنل تغییر یا حذف نمی‌شود و فقط نامزدها به ادمین گزارش می‌شوند.\n\n"
            f"📦 مهلت سرویس: {await asyncio.to_thread(db.get_setting, 'expired_delete_days', '0')} روز\n"
            f"🧪 مهلت تست: {await asyncio.to_thread(db.get_setting, 'test_delete_days', '0')} روز\n"
            f"⚠️ هشدار: {await asyncio.to_thread(db.get_setting, 'expired_cleanup_warning_days', '3')} روز"
        )
        await replace_admin_view(call, text, reply_markup=kb.admin_cleanup_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_cleanup_dryrun")
    async def cb_admin_cleanup_dryrun(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cur = await asyncio.to_thread(db.get_setting, "expired_cleanup_dry_run", "1")
        await asyncio.to_thread(db.set_setting, "expired_cleanup_dry_run", "0" if cur == "1" else "1")
        await safe_edit(call, db.get_text('handlers_admin.auto_5bd71298', '🧹 پاکسازی خودکار سرویس\u200cهای منقضی:'), reply_markup=kb.admin_cleanup_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_bfbbe2fc', 'حالت dry-run تغییر کرد.'))

    @router.callback_query(F.data == "adm_cleanup_expired")
    async def cb_admin_cleanup_expired(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCleanupSettings.waiting_expired_days)
        await safe_edit(call, db.get_text('handlers_admin.auto_d495904f', '📦 تعداد روز مهلت حذف سرویس پس از انقضا را بفرستید. ۰ یعنی خاموش.'), reply_markup=kb.admin_back_kb("adm_cleanup_settings"))
        await call.answer()

    @router.message(AdminCleanupSettings.waiting_expired_days)
    async def msg_admin_cleanup_expired(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        try:
            value = int(message.text.strip())
            if value < 0 or value > 3650:
                raise ValueError
        except Exception:
            return await message.answer(db.get_text('handlers_admin.auto_d54a2ce0', '❌ عددی بین ۰ تا ۳۶۵۰ بفرستید.'))
        await asyncio.to_thread(db.set_setting, "expired_delete_days", str(value))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_5f626d0f', '✅ مهلت حذف سرویس ذخیره شد.'), reply_markup=kb.admin_cleanup_settings_kb(db))

    @router.callback_query(F.data == "adm_cleanup_test")
    async def cb_admin_cleanup_test(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCleanupSettings.waiting_test_days)
        await safe_edit(call, db.get_text('handlers_admin.auto_ec7e1ad7', '🧪 تعداد روز مهلت حذف تست پس از انقضا را بفرستید. ۰ یعنی خاموش.'), reply_markup=kb.admin_back_kb("adm_cleanup_settings"))
        await call.answer()

    @router.message(AdminCleanupSettings.waiting_test_days)
    async def msg_admin_cleanup_test(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        try:
            value = int(message.text.strip())
            if value < 0 or value > 3650:
                raise ValueError
        except Exception:
            return await message.answer(db.get_text('handlers_admin.auto_d54a2ce0', '❌ عددی بین ۰ تا ۳۶۵۰ بفرستید.'))
        await asyncio.to_thread(db.set_setting, "test_delete_days", str(value))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_72f23af4', '✅ مهلت حذف تست ذخیره شد.'), reply_markup=kb.admin_cleanup_settings_kb(db))

    @router.callback_query(F.data == "adm_cleanup_warning")
    async def cb_admin_cleanup_warning(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCleanupSettings.waiting_warning_days)
        await safe_edit(call, db.get_text('handlers_admin.auto_b7fd74e0', '⚠️ چند روز قبل از انقضا هشدار ارسال شود؟ عدد ۰ یعنی بدون هشدار.'), reply_markup=kb.admin_back_kb("adm_cleanup_settings"))
        await call.answer()

    @router.message(AdminCleanupSettings.waiting_warning_days)
    async def msg_admin_cleanup_warning(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        try:
            value = int(message.text.strip())
            if value < 0 or value > 365:
                raise ValueError
        except Exception:
            return await message.answer(db.get_text('handlers_admin.auto_bb562393', '❌ عددی بین ۰ تا ۳۶۵ بفرستید.'))
        await asyncio.to_thread(db.set_setting, "expired_cleanup_warning_days", str(value))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_5c9177fb', '✅ مدت هشدار ذخیره شد.'), reply_markup=kb.admin_cleanup_settings_kb(db))

    @router.callback_query(F.data == "adm_cleanup_orphans")
    async def cb_admin_cleanup_orphans(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        stats = await asyncio.to_thread(db.get_orphan_config_stats)
        total = sum(stats.values()) - stats["custom_active_review"]
        if total <= 0:
            text = (
                "🗑 F147 — پاکسازی کانفیگ‌های یتیم\n\n"
                "مورد امنی برای حذف پیدا نشد.\n\n"
                f"⚠️ سرویس فعالِ بدون کاربر برای بررسی دستی: {stats['custom_active_review']}"
            )
        else:
            deleted = await asyncio.to_thread(db.delete_orphan_configs)
            text = (
                "🗑 F147 — پاکسازی کانفیگ‌های یتیم انجام شد.\n\n"
                f"🔗 بانک کانفیگ: {deleted['configs']}\n"
                f"🧪 بانک تست: {deleted['test_configs']}\n"
                f"🛠 کانفیگ شخصی غیرفعال: {deleted['custom_configs']}\n\n"
                f"⚠️ سرویس فعالِ بدون کاربر که حذف نشد: {stats['custom_active_review']}"
            )
        await safe_edit(call, text, reply_markup=kb.admin_cleanup_settings_kb(db))
        await call.answer(tr("پاکسازی F147 انجام شد."))

    @router.callback_query(F.data == "adm_cleanup_inactive_time")
    async def cb_admin_cleanup_inactive_time(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCleanupSettings.waiting_inactive_time)
        current = await asyncio.to_thread(db.get_setting, "inactive_config_delete_time", "")
        current = current or "خاموش"
        await safe_edit(
            call,
            f"🕐 ساعت حذف خودکار کانفیگ‌های غیرفعال را به فرمت HH:MM به وقت تهران بفرستید.\n"
            f"برای خاموش‌کردن، ۰ بفرستید.\n\nمقدار فعلی: {current}",
            reply_markup=kb.admin_back_kb("adm_cleanup_settings"),
        )
        await call.answer()

    @router.message(AdminCleanupSettings.waiting_inactive_time)
    async def msg_admin_cleanup_inactive_time(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        raw = (message.text or "").strip()
        if raw == "۰" or raw == "0":
            value = ""
        else:
            import re as _re
            if not _re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
                return await message.answer(tr("❌ ساعت نامعتبر است. مثل 23:30 بفرستید یا ۰ برای خاموش‌کردن."))
            value = raw
        await asyncio.to_thread(db.set_setting, "inactive_config_delete_time", value)
        await asyncio.to_thread(db.set_setting, "inactive_config_delete_last_run", "")
        await state.clear()
        await message.answer(tr("✅ ساعت حذف کانفیگ‌های غیرفعال ذخیره شد."), reply_markup=kb.admin_cleanup_settings_kb(db))

    @router.callback_query(F.data == "adm_test_toggle")
    async def cb_admin_test_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "test_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "test_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_c8b98d12', '🧪 مدیریت کانفیگ تست:'), reply_markup=kb.admin_test_menu_kb(db, is_main_bot))
        await call.answer(db.get_text('handlers_admin.auto_fb8498d4', 'وضعیت کانفیگ تست تغییر کرد.'))

    @router.callback_query(F.data == "adm_test_add")
    async def cb_admin_test_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not full_access_bot:
            await call.answer(db.get_text('handlers_admin.auto_53aa104e', 'این بخش برای نمایندگی سطح محدود فعال نیست.'), show_alert=True)
            return
        await state.set_state(AdminAddTestConfigs.waiting_links)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_0e8d8d0e', 'لینک\u200cهای بانک تست دستی (قدیمی) را ارسال کنید (هر لینک در یک خط):'), reply_markup=kb.admin_back_kb("adm_test_menu")
        )
        await call.answer()

    @router.message(AdminAddTestConfigs.waiting_links)
    async def process_add_test_configs(message: Message, state: FSMContext):
        links = [line for line in message.text.splitlines() if line.strip()]
        (await asyncio.to_thread(db.add_test_configs, links))
        await state.clear()
        await message.answer(tr(f"✅ {len(links)} لینک تست اضافه شد."), reply_markup=kb.admin_test_menu_kb(db, is_main_bot))

    # ---- افزودن پلن جدید ----

    @router.callback_query(F.data == "adm_tp_add")
    async def cb_tp_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not (await asyncio.to_thread(db.get_panel_servers, True)):
            await call.answer(db.get_text('handlers_admin.auto_b0d25597', '⛔️ اول باید حداقل یک سرور پنل فعال ثبت کنی.'), show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminAddTestPlan.waiting_name)
        await safe_edit(call, db.get_text('handlers_admin.auto_9214dd60', 'نام این پلن کانفیگ تست چیست؟ (مثلاً «تست یک\u200cساعته»):'), reply_markup=kb.admin_back_kb("adm_test_menu"))
        await call.answer()

    @router.message(AdminAddTestPlan.waiting_name)
    async def process_tp_name(message: Message, state: FSMContext):
        name = (message.text or "").strip()
        if not name:
            await message.answer(db.get_text('handlers_admin.auto_457ac65a', 'لطفاً یک نام معتبر ارسال کن.'))
            return
        await state.update_data(name=name)
        await state.set_state(AdminAddTestPlan.waiting_prefix)
        await message.answer(db.get_text('handlers_admin.auto_48cb4b7a', 'پیشوند نام کاربری کانفیگ\u200cهای این پلن چه باشد؟ (مثلاً «test»؛ فقط حروف/عدد انگلیسی):'))

    @router.message(AdminAddTestPlan.waiting_prefix)
    async def process_tp_prefix(message: Message, state: FSMContext):
        prefix = (message.text or "").strip()
        if not prefix or not prefix.isascii() or not prefix.replace("_", "").isalnum():
            await message.answer(db.get_text('handlers_admin.auto_e47a254d', 'پیشوند باید فقط شامل حروف/عدد انگلیسی باشد. دوباره ارسال کن:'))
            return
        await state.update_data(name_prefix=prefix)
        servers = (await asyncio.to_thread(db.get_panel_servers, True))
        rows = [
            [InlineKeyboardButton(
                text=f"{s['name']} ({kb.PANEL_TYPE_LABELS.get(s['panel_type'], s['panel_type'])})",
                callback_data=f"adm_tp_new_panel:{s['id']}",
            )]
            for s in servers
        ]
        rows.append([InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_test_menu")])
        await state.set_state(AdminAddTestPlan.waiting_panel)
        await message.answer(db.get_text('handlers_admin.auto_c931e1e9', 'این پلن روی کدام سرور پنل ساخته شود؟'), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("adm_tp_new_panel:"), AdminAddTestPlan.waiting_panel)
    async def cb_tp_new_panel_pick(call: CallbackQuery, state: FSMContext):
        server_id = int(call.data.split(":", 1)[1])
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminAddTestPlan.waiting_volume_mb)
        await safe_edit(call, db.get_text('handlers_admin.auto_b6abf359', 'حجم این پلن چند مگابایت باشد؟ فقط عدد صحیح (مثال: 100 برای ۱۰۰ مگ، یا 1024 برای ۱ گیگ):'),
                         reply_markup=kb.admin_back_kb("adm_test_menu"))
        await call.answer()

    @router.message(AdminAddTestPlan.waiting_volume_mb)
    async def process_tp_volume_mb(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_10434b34', 'لطفاً یک عدد صحیح مثبت (به مگابایت) ارسال کن.'))
            return
        await state.update_data(volume_mb=int(text))
        await state.set_state(AdminAddTestPlan.waiting_duration_hours)
        await message.answer(db.get_text('handlers_admin.auto_7c85c581', 'مدت اعتبار این پلن چند ساعت باشد؟ فقط عدد صحیح (مثال: 1 برای ۱ ساعت، یا 24 برای ۱ روز):'))

    @router.message(AdminAddTestPlan.waiting_duration_hours)
    async def process_tp_duration_hours(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_ec60db82', 'لطفاً یک عدد صحیح مثبت (به ساعت) ارسال کن.'))
            return
        data = await state.get_data()
        plan_id = (await asyncio.to_thread(
            db.create_test_config_plan, data["name"], data["name_prefix"],
            data["panel_server_id"], data["volume_mb"], int(text),
        ))
        await state.clear()
        await _tp_show_view(message, plan_id, "✅ پلن ساخته شد.")

    # ---- ویرایش/حذف پلن ----

    @router.callback_query(F.data.startswith("adm_tp_view:"))
    async def cb_tp_view(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await _tp_show_view(call, callback_id(call.data, "adm_tp_view"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tp_edit_name:"))
    async def cb_tp_edit_name(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_edit_name")
        await state.update_data(editing_plan_id=plan_id)
        await state.set_state(AdminEditTestPlan.waiting_name)
        await safe_edit(call, db.get_text('handlers_admin.auto_812e3f0e', 'نام جدید پلن را ارسال کن:'), reply_markup=kb.admin_back_kb(f"adm_tp_view:{plan_id}"))
        await call.answer()

    @router.message(AdminEditTestPlan.waiting_name)
    async def process_tp_edit_name(message: Message, state: FSMContext):
        name = (message.text or "").strip()
        if not name:
            await message.answer(db.get_text('handlers_admin.auto_457ac65a', 'لطفاً یک نام معتبر ارسال کن.'))
            return
        data = await state.get_data()
        plan_id = data.get("editing_plan_id")
        (await asyncio.to_thread(db.update_test_config_plan, plan_id, name=name))
        await state.clear()
        await _tp_show_view(message, plan_id, "✅ نام به‌روزرسانی شد.")

    @router.callback_query(F.data.startswith("adm_tp_edit_prefix:"))
    async def cb_tp_edit_prefix(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_edit_prefix")
        await state.update_data(editing_plan_id=plan_id)
        await state.set_state(AdminEditTestPlan.waiting_prefix)
        await safe_edit(call, db.get_text('handlers_admin.auto_c1af25db', 'پیشوند جدید نام کاربری را ارسال کن (فقط حروف/عدد انگلیسی):'), reply_markup=kb.admin_back_kb(f"adm_tp_view:{plan_id}"))
        await call.answer()

    @router.message(AdminEditTestPlan.waiting_prefix)
    async def process_tp_edit_prefix(message: Message, state: FSMContext):
        prefix = (message.text or "").strip()
        if not prefix or not prefix.isascii() or not prefix.replace("_", "").isalnum():
            await message.answer(db.get_text('handlers_admin.auto_e47a254d', 'پیشوند باید فقط شامل حروف/عدد انگلیسی باشد. دوباره ارسال کن:'))
            return
        data = await state.get_data()
        plan_id = data.get("editing_plan_id")
        (await asyncio.to_thread(db.update_test_config_plan, plan_id, name_prefix=prefix))
        await state.clear()
        await _tp_show_view(message, plan_id, "✅ پیشوند به‌روزرسانی شد.")

    @router.callback_query(F.data.startswith("adm_tp_edit_panel:"))
    async def cb_tp_edit_panel(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_edit_panel")
        await safe_edit(call, db.get_text('handlers_admin.auto_2f4fa6cc', 'پنل جدید این پلن را انتخاب کن:'),
                         reply_markup=kb.test_plan_panel_select_kb(db, plan_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tp_set_panel:"))
    async def cb_tp_set_panel(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, plan_id, server_id = call.data.split(":")
        (await asyncio.to_thread(db.update_test_config_plan, int(plan_id), panel_server_id=int(server_id)))
        await _tp_show_view(call, int(plan_id), "✅ پنل پلن به‌روزرسانی شد.")
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tp_edit_volume:"))
    async def cb_tp_edit_volume(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_edit_volume")
        await state.update_data(editing_plan_id=plan_id)
        await state.set_state(AdminEditTestPlan.waiting_volume_mb)
        await safe_edit(call, db.get_text('handlers_admin.auto_46e5b947', 'حجم جدید این پلن چند مگابایت باشد؟ فقط عدد صحیح:'), reply_markup=kb.admin_back_kb(f"adm_tp_view:{plan_id}"))
        await call.answer()

    @router.message(AdminEditTestPlan.waiting_volume_mb)
    async def process_tp_edit_volume(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_10434b34', 'لطفاً یک عدد صحیح مثبت (به مگابایت) ارسال کن.'))
            return
        data = await state.get_data()
        plan_id = data.get("editing_plan_id")
        (await asyncio.to_thread(db.update_test_config_plan, plan_id, volume_mb=int(text)))
        await state.clear()
        await _tp_show_view(message, plan_id, "✅ حجم به‌روزرسانی شد.")

    @router.callback_query(F.data.startswith("adm_tp_edit_duration:"))
    async def cb_tp_edit_duration(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_edit_duration")
        await state.update_data(editing_plan_id=plan_id)
        await state.set_state(AdminEditTestPlan.waiting_duration_hours)
        await safe_edit(call, db.get_text('handlers_admin.auto_4d7e0395', 'مدت جدید این پلن چند ساعت باشد؟ فقط عدد صحیح:'), reply_markup=kb.admin_back_kb(f"adm_tp_view:{plan_id}"))
        await call.answer()

    @router.message(AdminEditTestPlan.waiting_duration_hours)
    async def process_tp_edit_duration(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_ec60db82', 'لطفاً یک عدد صحیح مثبت (به ساعت) ارسال کن.'))
            return
        data = await state.get_data()
        plan_id = data.get("editing_plan_id")
        (await asyncio.to_thread(db.update_test_config_plan, plan_id, duration_hours=int(text)))
        await state.clear()
        await _tp_show_view(message, plan_id, "✅ مدت به‌روزرسانی شد.")

    @router.callback_query(F.data.startswith("adm_tp_toggle:"))
    async def cb_tp_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_toggle")
        (await asyncio.to_thread(db.toggle_test_config_plan, plan_id))
        await _tp_show_view(call, plan_id)
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_tp_delete:"))
    async def cb_tp_delete_confirm(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_delete")
        await safe_edit(call, db.get_text('handlers_admin.auto_e1a56971', '⚠️ با حذف این پلن، کانفیگ\u200cهای تست ساخته\u200cشده قبلی دست\u200cنخورده می\u200cمانند ولی دیگر قابل انتخاب نیست. مطمئنی؟'),
                         reply_markup=kb.test_plan_delete_confirm_kb(plan_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tp_delete_force:"))
    async def cb_tp_delete_force(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plan_id = callback_id(call.data, "adm_tp_delete_force")
        (await asyncio.to_thread(db.delete_test_config_plan, plan_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "test_plan_delete", f"پلن #{plan_id}"))
        await replace_admin_view(call, "🧪 مدیریت کانفیگ تست:", reply_markup=kb.admin_test_menu_kb(db, is_main_bot))
        await call.answer(db.get_text('handlers_admin.auto_48c23ce2', 'پلن حذف شد.'))

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
            await call.answer(db.get_text('handlers_admin.auto_8c434446', 'اول باید آیدی کانال را تنظیم کنی.'), show_alert=True)
            return
        current = (await asyncio.to_thread(db.get_setting, "force_join_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "force_join_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_00bfae4b', '📢 عضویت اجباری در کانال:'), reply_markup=kb.admin_forcejoin_menu_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_8e44867a', 'وضعیت عضویت اجباری تغییر کرد.'))

    @router.callback_query(F.data == "adm_forcejoin_set_channel")
    async def cb_admin_forcejoin_set_channel(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminForceJoin.waiting_channel)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_34cf694f', 'آیدی عددی یا یوزرنیم کانال را ارسال کن.\n\nمثال: `@mychannel`\n\n⚠️ حتماً ربات باید از قبل به\u200cعنوان ادمین به کانال اضافه شده باشد؛ در غیر این صورت نمی\u200cتواند عضویت را بررسی کند.'),
            reply_markup=kb.admin_back_kb("adm_forcejoin_menu"),
        )
        await call.answer()

    @router.message(AdminForceJoin.waiting_channel)
    async def process_forcejoin_channel(message: Message, state: FSMContext, bot: Bot):
        channel = (message.text or "").strip()
        if not channel:
            await message.answer(db.get_text('handlers_admin.auto_67823205', 'ورودی نامعتبر است. دوباره تلاش کن.'))
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
                db.get_text('handlers_admin.auto_9d459b35', '⛔️ نتوانستم به این کانال دسترسی پیدا کنم.\nمطمئن شو آیدی درست است و ربات از قبل به\u200cعنوان *ادمین* به کانال اضافه شده باشد.'),
                reply_markup=kb.admin_back_kb("adm_forcejoin_menu"),
            )
            return

        (await asyncio.to_thread(db.set_setting, "force_join_channel", channel))
        await state.clear()
        await message.answer(
            tr(f"✅ کانال «{chat.title}» ثبت شد. حالا می‌تونی از منوی قبلی عضویت اجباری رو فعال کنی."),
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
            await call.answer(db.get_text('handlers_admin.auto_8045a61a', 'سفارش در انتظاری وجود ندارد.'), show_alert=True)
            return
        await replace_admin_view(call, "🧾 سفارش‌های در انتظار بررسی:", reply_markup=kb.pending_orders_kb(orders))
        await call.answer()

    async def _show_order_surveys(call: CallbackQuery, notice: str = None):
        orders = await asyncio.to_thread(db.get_orders_by_status, "approved", 20)
        if not orders:
            await call.answer(db.get_text('handlers_admin.auto_dbdb2831', 'سفارش تایید\u200cشده\u200cای وجود ندارد.'), show_alert=True)
            return
        surveys = {}
        for o in orders:
            survey = await asyncio.to_thread(db.get_order_survey_by_order, o["id"])
            if survey:
                surveys[o["id"]] = survey
        await replace_admin_view(
            call,
            "🗳 نظرسنجی سفارش‌ها\n\nروی یک سفارش تایید‌شده بزن تا نظرسنجی برای خریدار ارسال شود (۲۰ سفارش اخیر):",
            reply_markup=kb.order_surveys_list_kb(orders, surveys),
        )
        await call.answer(notice)

    @router.callback_query(F.data == "adm_order_surveys")
    async def cb_admin_order_surveys(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        await _show_order_surveys(call)

    @router.callback_query(F.data.startswith("adm_svy_send:"))
    async def cb_admin_order_survey_send(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        order_id = callback_id(call.data, "adm_svy_send")
        if order_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        result = await asyncio.to_thread(db.create_order_survey, order_id, call.from_user.id)
        if not result["ok"]:
            messages = {
                "not_found": "سفارش یافت نشد.",
                "not_approved": "نظرسنجی فقط برای سفارش‌های تایید‌شده ارسال می‌شود.",
                "answered": "کاربر قبلاً به نظرسنجی این سفارش پاسخ داده است.",
            }
            await call.answer(messages.get(result["reason"], "ارسال نظرسنجی ممکن نیست."), show_alert=True)
            return
        text = f"🗳 نظرسنجی\n\nکیفیت سرویس سفارش #{order_id} را چطور ارزیابی می‌کنی؟\n(۱ = ضعیف تا ۵ = عالی)"
        try:
            await bot.send_message(result["user_id"], text, reply_markup=kb.order_survey_kb(result["survey_id"]))
        except Exception as e:
            await call.answer(tr(f"❌ ارسال به کاربر ناموفق بود: {str(e)[:150]}"), show_alert=True)
            return
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "order_survey_send", f"سفارش #{order_id} | کاربر {result['user_id']}")
        await _show_order_surveys(call, "✅ نظرسنجی برای کاربر ارسال شد.")

    @router.callback_query(F.data == "adm_svy_results")
    async def cb_admin_order_survey_results(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        rows = await asyncio.to_thread(db.get_survey_summary)
        if not rows:
            await call.answer(db.get_text('handlers_admin.auto_f1c7c407', 'هنوز نظرسنجی\u200cای ارسال نشده است.'), show_alert=True)
            return
        lines = ["📊 نتایج نظرسنجی به تفکیک پنل (ضعیف‌ترین‌ها اول)\n"]
        for r in rows:
            avg = f"⭐ {r['avg_rating']:.2f} از ۵" if r["avg_rating"] is not None else "بدون پاسخ"
            lines.append(f"• {html.escape(r['panel_name'])}: {avg} ({r['answered']} پاسخ از {r['sent']} ارسال)")
        await replace_admin_view(call, "\n".join(lines), reply_markup=kb.admin_back_kb("adm_order_surveys"))
        await call.answer()

    @router.callback_query(F.data.startswith("view_order:"))
    async def cb_view_order(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        order_id = callback_id(call.data, "view_order")
        if order_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order:
            await call.answer(db.get_text('handlers_admin.auto_fcb40791', 'سفارش یافت نشد.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order:
            await call.answer(db.get_text('handlers_admin.auto_fcb40791', 'سفارش یافت نشد.'), show_alert=True)
            return
        if order["status"] != "pending":
            await call.answer(db.get_text('handlers_admin.auto_30ff7b82', 'این سفارش قبلاً بررسی شده است.'), show_alert=True)
            return
        if not (await asyncio.to_thread(db.claim_order, order_id)):
            await call.answer(db.get_text('handlers_admin.auto_30ff7b82', 'این سفارش قبلاً بررسی شده است.'), show_alert=True)
            return

        # ===== سفارش تمدید سرویس از حساب کاربری =====
        if order["is_renewal"]:
            try:
                result_text = await execute_renewal(db, order)
            except RenewalError as e:
                await asyncio.to_thread(db.release_order_claim, order_id)
                await call.answer(tr(f"⛔️ تمدید ناموفق بود: {e}"), show_alert=True)
                return
            (await asyncio.to_thread(db.approve_renewal_order, order_id))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "renewal_approve",
                f"سفارش تمدید #{order_id} | کاربر {order['user_id']} | مبلغ: {order['final_price']:,}",
            ))
            renewal_reward_info = (await asyncio.to_thread(
                db.reward_referrer_on_renewal, order["user_id"], order["base_price"] or order["final_price"] or 0
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
            try:
                await bot.send_message(order["user_id"], result_text)
                await _notify_user_inline_menu(bot, order["user_id"])
            except Exception:
                pass
            try:
                await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ تایید شد و سرویس تمدید شد.")
            except Exception:
                try:
                    await safe_edit(call, (call.message.text or "") + "\n\n✅ تایید شد و سرویس تمدید شد.")
                except Exception:
                    pass
            await call.answer(db.get_text('handlers_admin.auto_a501e91f', 'سفارش تایید و سرویس تمدید شد.'))
            await _notify_admin_panel_menu(bot, call.from_user.id)
            return

        # ===== سفارش کانفیگ شخصی: به‌جای برداشتن از انبار، کاربر روی پنل ساخته می‌شود =====
        if order["is_custom_config"]:
            server = (await asyncio.to_thread(db.get_panel_server, order["custom_panel_server_id"]))
            if not server or not server["is_active"]:
                await call.answer(db.get_text('handlers_admin.auto_49653618', '⛔️ سرور پنل مربوطه یافت نشد یا غیرفعال است.'), show_alert=True)
                return
            duration_days = order["custom_duration_days"]
            if duration_days is None:
                duration_days = (await asyncio.to_thread(db.get_custom_config_settings))["duration_days"]
            if not await asyncio.to_thread(db.panel_has_capacity, server["id"], 1):
                await asyncio.to_thread(db.release_order_claim, order_id)
                cap = await asyncio.to_thread(db.get_panel_capacity_info, server["id"])
                await call.answer(tr(f"⛔️ ظرفیت پنل تکمیل است ({cap['active_services']}/{cap['max_services']})."), show_alert=True)
                return
            try:
                provider = get_provider(server)
                result = await provider.create_user(
                    username=order["custom_username"],
                    volume_gb=order["custom_volume_gb"],
                    duration_days=duration_days,
                )
            except PanelUsernameTakenError:
                await asyncio.to_thread(db.release_order_claim, order_id)
                await call.answer(db.get_text('handlers_admin.auto_14118989', '⛔️ این نام کاربری روی پنل تکراری است؛ از کاربر بخواه نام دیگری انتخاب کند.'), show_alert=True)
                return
            except PanelError as e:
                await asyncio.to_thread(db.release_order_claim, order_id)
                await call.answer(tr(f"⛔️ خطا در ارتباط با پنل: {e}"), show_alert=True)
                return

            (await asyncio.to_thread(db.approve_custom_config_order, order_id))
            (await asyncio.to_thread(db.add_custom_config, 
                user_id=order["user_id"],
                panel_server_id=server["id"],
                username=result.username,
                volume_gb=order["custom_volume_gb"],
                duration_days=duration_days,
                subscription_url=result.subscription_url,
                order_id=order_id,
                product_id=order["custom_product_id"],
            ))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "custom_config_approve",
                f"سفارش کانفیگ شخصی #{order_id} | کاربر {order['user_id']} | یوزرنیم «{result.username}» | "
                f"{order['custom_volume_gb']} گیگ | مبلغ: {order['final_price']:,}",
            ))
            try:
                await bot.send_message(order["user_id"], tr("✅ کانفیگ شخصی شما ساخته شد!"))
                await deliver_config_to_user(
                    bot, order["user_id"], "کانفیگ شخصی",
                    [result.subscription_url], final_price=order["final_price"], order_id=order_id, db=db,
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
            await call.answer(db.get_text('handlers_admin.auto_2dfda996', 'سفارش تایید و کانفیگ شخصی روی پنل ساخته شد.'))
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
                await asyncio.to_thread(db.release_order_claim, order_id)
                await call.answer(f"⛔️ {e}", show_alert=True)
                return
            (await asyncio.to_thread(db.approve_order_auto, order_id))
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "order_approve",
                f"سفارش #{order_id} (خودکار) | کاربر {order['user_id']} | محصول «{product['name']}» | "
                f"مبلغ: {(order['final_price'] or product['price']):,}",
            ))
            try:
                await bot.send_message(order["user_id"], tr(f"✅ خرید شما تایید شد!\n📦 محصول: {product['name']}"))
                await deliver_config_to_user(
                    bot, order["user_id"], product["name"],
                    [r["subscription_url"] for r in prov_results], final_price=order["final_price"], order_id=order_id, db=db,
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
            await call.answer(db.get_text('handlers_admin.auto_c1fd6d87', 'سفارش تایید و کانفیگ به\u200cصورت خودکار ساخته شد.'))
            await _notify_admin_panel_menu(bot, call.from_user.id)
            return

        quantity = order["quantity"] or 1
        results = (await asyncio.to_thread(db.take_unused_configs, order["product_id"], order["user_id"], quantity))
        if not results:
            await asyncio.to_thread(db.release_order_claim, order_id)
            await call.answer(db.get_text('handlers_admin.auto_a4785dd8', '⛔️ موجودی این محصول تمام شده! ابتدا لینک جدید اضافه کنید.'), show_alert=True)
            return

        (await asyncio.to_thread(db.approve_order, order_id, [r["id"] for r in results]))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "order_approve",
            f"سفارش #{order_id} | کاربر {order['user_id']} | محصول «{product['name'] if product else '---'}» | مبلغ: {(order['final_price'] or (product['price'] if product else 0)):,}",
        ))
        await check_and_notify_low_stock(bot.send_message, db, order["product_id"], bot_token=bot.token)

        reward_info = (await asyncio.to_thread(db.reward_referrer_if_first_purchase, order["user_id"], order["final_price"] or product["price"]))
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
            await bot.send_message(order["user_id"], tr(f"✅ خرید شما تایید شد!\n📦 محصول: {product['name']}"))
            await deliver_config_to_user(
                bot,
                order["user_id"],
                product["name"],
                [r["link"] for r in results],
                final_price=order["final_price"],
                order_id=order_id,
                db=db,
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
        await call.answer(db.get_text('handlers_admin.auto_bcd7b5a4', 'سفارش تایید و کانفیگ برای کاربر ارسال شد.'))
        await _notify_admin_panel_menu(bot, call.from_user.id)

    @router.callback_query(F.data.startswith("order_fake_receipt:"))
    async def cb_order_fake_receipt(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()

        order_id = callback_id(call.data, "order_fake_receipt")
        if order_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order:
            await call.answer(db.get_text('handlers_admin.auto_fcb40791', 'سفارش یافت نشد.'), show_alert=True)
            return
        if order["status"] != "pending":
            await call.answer(db.get_text('handlers_admin.auto_30ff7b82', 'این سفارش قبلاً بررسی شده است.'), show_alert=True)
            return

        result = await asyncio.to_thread(db.fake_receipt_order, order_id)
        if not result:
            await call.answer(db.get_text('handlers_admin.auto_30ff7b82', 'این سفارش قبلاً بررسی شده است.'), show_alert=True)
            return

        await asyncio.to_thread(
            db.log_admin_action,
            call.from_user.id,
            "order_fake_receipt",
            f"فیش فیک سفارش #{order_id} | کاربر {order['user_id']} | {result['deleted_configs']} کانفیگ حذف شد و کاربر بلاک شد",
        )

        try:
            await bot.send_message(
                order["user_id"],
                tr("🚫 فیش فیک تشخیص داده شد.\n\n"
                "⛔️ سفارش شما رد شد و حساب کاربری‌تان بلاک شد.\n"
                "در صورت اشتباه، برای بررسی موضوع با پشتیبانی تماس بگیرید."),
            )
        except Exception:
            pass

        try:
            await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n🚫 فیش فیک؛ سفارش رد و کاربر بلاک شد.")
        except Exception:
            try:
                await safe_edit(call, (call.message.text or "") + "\n\n🚫 فیش فیک؛ سفارش رد و کاربر بلاک شد.")
            except Exception:
                pass
        await call.answer(tr("فیش فیک ثبت شد؛ کاربر بلاک و کانفیگ مرتبط حذف شد."))
        await _notify_admin_panel_menu(bot, call.from_user.id)

    @router.callback_query(F.data.startswith("order_reject:"))
    async def cb_order_reject(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()

        order_id = callback_id(call.data, "order_reject")
        if order_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        order = (await asyncio.to_thread(db.get_order, order_id))
        if not order:
            await call.answer(db.get_text('handlers_admin.auto_fcb40791', 'سفارش یافت نشد.'), show_alert=True)
            return
        if order["status"] != "pending":
            await call.answer(db.get_text('handlers_admin.auto_30ff7b82', 'این سفارش قبلاً بررسی شده است.'), show_alert=True)
            return

        if not (await asyncio.to_thread(db.reject_order, order_id)):
            await call.answer(db.get_text('handlers_admin.auto_30ff7b82', 'این سفارش قبلاً بررسی شده است.'), show_alert=True)
            return
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "order_reject",
            f"سفارش #{order_id} | کاربر {order['user_id']}",
        ))
        try:
            await bot.send_message(
                order["user_id"],
                tr("❌ متاسفانه رسید ارسالی شما تایید نشد. در صورت اشتباه لطفاً با پشتیبانی در ارتباط باشید."),
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
        await call.answer(db.get_text('handlers_admin.auto_94afef67', 'سفارش رد شد.'))
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
            await call.answer(db.get_text('handlers_admin.auto_0b515b9c', 'درخواست شارژ در انتظاری وجود ندارد.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_6f6e17f1', 'هیچ پرداخت کریپتویی ثبت نشده است.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_crypto_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_fcc2106e', 'فاکتور یافت نشد.'), show_alert=True)
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
            rows.append([InlineKeyboardButton(text=tr("🔗 باز کردن فاکتور"), url=invoice["invoice_url"])])
        if invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text=tr("❌ لغو و حذف فاکتور"), callback_data=f"cancel_crypto_invoice:{invoice['id']}")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به پرداخت‌های کریپتو"), callback_data="adm_crypto_payments")])
        await replace_admin_view(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("cancel_crypto_invoice:"))
    async def cb_cancel_crypto_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "cancel_crypto_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_crypto_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_4c01ab16', 'فاکتور یافت نشد یا قبلاً حذف شده.'), show_alert=True)
        else:
            (await asyncio.to_thread(db.cancel_and_delete_crypto_invoice, invoice_id))
            await call.answer(db.get_text('handlers_admin.auto_74c6ae8f', '✅ فاکتور لغو و حذف شد.'))

        (await asyncio.to_thread(db.expire_stale_crypto_invoices))
        (await asyncio.to_thread(db.purge_old_crypto_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_crypto_invoices, 50))
        if not invoices:
            await replace_admin_view(call, "🪙 پرداخت‌های کریپتو\n\nهیچ پرداخت کریپتویی ثبت نشده است.",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")]
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
            await call.answer(db.get_text('handlers_admin.auto_55f6a337', 'هیچ پرداخت آبان گیت\u200cوی\u200cای ثبت نشده است.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_fcc2106e', 'فاکتور یافت نشد.'), show_alert=True)
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
            rows.append([InlineKeyboardButton(text=tr("🔗 باز کردن فاکتور"), url=invoice["payment_url"])])
        if invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text=tr("🔄 بررسی وضعیت"), callback_data=f"check_abangateway_invoice:{invoice['id']}")])
            rows.append([InlineKeyboardButton(text=tr("❌ لغو و حذف فاکتور"), callback_data=f"cancel_abangateway_invoice:{invoice['id']}")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به پرداخت‌های آبان گیت وی"), callback_data="adm_abangateway_payments")])
        await replace_admin_view(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("check_abangateway_invoice:"))
    async def cb_check_abangateway_invoice(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "check_abangateway_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_fcc2106e', 'فاکتور یافت نشد.'), show_alert=True)
            return
        await call.answer(db.get_text('handlers_admin.auto_0b238115', 'در حال بررسی...'))
        result = await abangateway_payment.try_verify_and_finalize(db, invoice)
        if result == "verified_now":
            if invoice["kind"] == "wallet_topup":
                text = await abangateway_payment.finalize_paid_topup(db, invoice["ref_id"])
            else:
                text = await abangateway_payment.finalize_paid_order(db, bot, invoice["ref_id"])
            await call.message.answer(text)
        elif result == "not_paid_yet":
            await call.message.answer(db.get_text('handlers_admin.auto_100d9937', '⏳ هنوز واریزی برای این فاکتور تایید نشده.'))
        elif result == "already_delivered":
            await call.message.answer(db.get_text('handlers_admin.auto_16b47321', '✅ این پرداخت قبلاً تایید و تحویل داده شده است.'))
        elif result in ("expired", "cancelled"):
            await call.message.answer(db.get_text('handlers_admin.auto_42a7d8a4', '❌ اعتبار این فاکتور تمام شده یا لغو شده است.'))
        elif result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))

    @router.callback_query(F.data.startswith("cancel_abangateway_invoice:"))
    async def cb_cancel_abangateway_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "cancel_abangateway_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_abangateway_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_4c01ab16', 'فاکتور یافت نشد یا قبلاً حذف شده.'), show_alert=True)
        else:
            (await asyncio.to_thread(db.cancel_and_delete_abangateway_invoice, invoice_id))
            await call.answer(db.get_text('handlers_admin.auto_74c6ae8f', '✅ فاکتور لغو و حذف شد.'))

        (await asyncio.to_thread(db.expire_stale_abangateway_invoices))
        (await asyncio.to_thread(db.purge_old_abangateway_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_abangateway_invoices, 50))
        if not invoices:
            await replace_admin_view(call, "💳 پرداخت‌های آبان گیت وی\n\nهیچ پرداخت آبان گیت‌وی‌ای ثبت نشده است.",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")]
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
    async def cb_admin_set_abangateway(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        source = abangateway_payment.resolve_api_key_source(db)
        source_note = {
            "db": "✅ از همین پنل بات خوانده می‌شود (بات و مینی‌اپ هر دو همین را می‌بینند، بدون نیاز به ری‌استارت).",
            "env": "⚠️ فقط از فایل .env این پروسه خوانده می‌شود. اگر بات و مینی‌اپ را جدا ری‌استارت نکرده باشی ممکن است این دو با هم ناهماهنگ باشند. پیشنهاد: همینجا دوباره ثبتش کن تا مطمئن بشی.",
            "none": "❌ هیچ کلیدی (نه در دیتابیس، نه در .env) تنظیم نشده.",
        }[source]
        await replace_admin_view(
            call,
            "💳 تنظیم درگاه آبان گیت وی (پرداخت کارتی/آنلاین)\n\n"
            f"منبع کلید: {source_note}",
            reply_markup=kb.abangateway_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_abangateway_set_key")
    async def cb_admin_abangateway_set_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "abangateway_api_key", ""))
        masked = f"...{current[-4:]}" if current else "❌ تنظیم نشده"
        await state.set_state(AdminSetAbanGateway.waiting_key)
        await safe_edit(
            call,
            f"💳 API Key حساب آبان گیت وی را ارسال کن (از abangateway.ir → تنظیمات API).\n"
            f"وضعیت فعلی: {masked}\n\n"
            f"برای غیرفعال‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb("adm_set_abangateway"),
        )
        await call.answer()

    @router.message(AdminSetAbanGateway.waiting_key)
    async def process_set_abangateway_key(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "abangateway_api_key", ""))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "abangateway_key_change", "API Key آبان گیت وی حذف شد."))
            await message.answer(db.get_text('handlers_admin.auto_6c3aed6a', '✅ API Key آبان گیت وی حذف شد و درگاه غیرفعال شد.'), reply_markup=kb.abangateway_settings_kb(db))
            return
        (await asyncio.to_thread(db.set_setting, "abangateway_api_key", text))
        (await asyncio.to_thread(db.set_setting, "abangateway_payment_enabled", "1"))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "abangateway_key_change", "API Key آبان گیت وی تغییر کرد."))
        await message.answer(
            db.get_text('handlers_admin.auto_e89e288a', '✅ API Key آبان گیت وی ذخیره شد و درگاه فعال شد.'),
            reply_markup=kb.abangateway_settings_kb(db),
        )

    # -------------------------------------------------------------------
    # پرداخت‌های بلوپال (تایید خودکار کارت‌به‌کارت)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_blupal_payments")
    async def cb_admin_blupal_payments(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        (await asyncio.to_thread(db.expire_stale_blupal_invoices))
        (await asyncio.to_thread(db.purge_old_blupal_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_blupal_invoices, 50))
        if not invoices:
            await call.answer(db.get_text('handlers_admin.auto_1ff5b16d', 'هیچ پرداخت بلوپالی ثبت نشده است.'), show_alert=True)
            return
        await replace_admin_view(
            call,
            "💳 پرداخت‌های بلوپال\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.blupal_invoices_kb(invoices),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("view_blupal_invoice:"))
    async def cb_view_blupal_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "view_blupal_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_blupal_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_fcc2106e', 'فاکتور یافت نشد.'), show_alert=True)
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
            f"💳 فاکتور بلوپال #{invoice['id']}\n"
            f"{kind_text}: #{invoice['ref_id']}\n"
            f"👤 کاربر: {invoice['user_id']}\n"
            f"💰 مبلغ: {invoice['amount_toman']:,} تومان\n"
            f"📌 وضعیت: {status_text}\n"
            f"🕐 ایجاد: {invoice['created_at'] or '---'}"
        )
        rows = []
        if invoice["payment_url"] and invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text=tr("🔗 باز کردن فاکتور"), url=invoice["payment_url"])])
        if invoice["status"] in ("new", "pending"):
            rows.append([InlineKeyboardButton(text=tr("🔄 بررسی وضعیت"), callback_data=f"check_blupal_invoice:{invoice['id']}")])
            rows.append([InlineKeyboardButton(text=tr("❌ لغو و حذف فاکتور"), callback_data=f"cancel_blupal_invoice:{invoice['id']}")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به پرداخت‌های بلوپال"), callback_data="adm_blupal_payments")])
        await replace_admin_view(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("check_blupal_invoice:"))
    async def cb_check_blupal_invoice(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "check_blupal_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_blupal_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_fcc2106e', 'فاکتور یافت نشد.'), show_alert=True)
            return
        await call.answer(db.get_text('handlers_admin.auto_0b238115', 'در حال بررسی...'))
        result = await blupal_payment.try_verify_and_finalize(db, invoice)
        if result == "verified_now":
            if invoice["kind"] == "wallet_topup":
                text = await blupal_payment.finalize_paid_topup(db, invoice["ref_id"])
            else:
                text = await blupal_payment.finalize_paid_order(db, bot, invoice["ref_id"])
            await call.message.answer(text)
        elif result == "not_paid_yet":
            await call.message.answer(db.get_text('handlers_admin.auto_100d9937', '⏳ هنوز واریزی برای این فاکتور تایید نشده.'))
        elif result == "already_delivered":
            await call.message.answer(db.get_text('handlers_admin.auto_16b47321', '✅ این پرداخت قبلاً تایید و تحویل داده شده است.'))
        elif result in ("expired", "cancelled"):
            await call.message.answer(db.get_text('handlers_admin.auto_42a7d8a4', '❌ اعتبار این فاکتور تمام شده یا لغو شده است.'))
        elif result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))

    @router.callback_query(F.data.startswith("cancel_blupal_invoice:"))
    async def cb_cancel_blupal_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "cancel_blupal_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_blupal_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_4c01ab16', 'فاکتور یافت نشد یا قبلاً حذف شده.'), show_alert=True)
        else:
            (await asyncio.to_thread(db.cancel_and_delete_blupal_invoice, invoice_id))
            await call.answer(db.get_text('handlers_admin.auto_74c6ae8f', '✅ فاکتور لغو و حذف شد.'))

        (await asyncio.to_thread(db.expire_stale_blupal_invoices))
        (await asyncio.to_thread(db.purge_old_blupal_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_blupal_invoices, 50))
        if not invoices:
            await replace_admin_view(call, "💳 پرداخت‌های بلوپال\n\nهیچ پرداخت بلوپالی ثبت نشده است.",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")]
                                      ]))
            return
        await replace_admin_view(
            call,
            "💳 پرداخت‌های بلوپال\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.blupal_invoices_kb(invoices),
        )

    # -------------------------------------------------------------------
    # تنظیم درگاه پرداخت بلوپال
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_set_blupal")
    async def cb_admin_set_blupal(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        source = blupal_payment.resolve_api_key_source(db)
        source_note = {
            "db": "✅ از همین پنل بات خوانده می‌شود (بات و مینی‌اپ هر دو همین را می‌بینند، بدون نیاز به ری‌استارت).",
            "env": "⚠️ فقط از فایل .env این پروسه خوانده می‌شود. اگر بات و مینی‌اپ را جدا ری‌استارت نکرده باشی ممکن است این دو با هم ناهماهنگ باشند. پیشنهاد: همینجا دوباره ثبتش کن تا مطمئن بشی.",
            "none": "❌ هیچ کلیدی (نه در دیتابیس، نه در .env) تنظیم نشده.",
        }[source]
        tenant_id = (await asyncio.to_thread(db.get_setting, "miniapp_tenant_id", ""))
        webhook_hint = blupal_payment.webhook_url_hint(tenant_id)
        webhook_note = (
            f"\n\n🔗 پس از تنظیم کلید، این آدرس را در داشبورد بلوپال (تنظیمات API Key → Webhook URL) وارد کن تا تاییدها آنی شوند:\n{webhook_hint}"
            if webhook_hint else
            "\n\n⚠️ آدرس مینی‌اپ (MINIAPP_URL) روی سرور تنظیم نشده؛ بدون آن نمی‌توانی آدرس وب‌هوک بسازی (بررسی دستی وضعیت هنوز کار می‌کند)."
        )
        await replace_admin_view(
            call,
            "💳 تنظیم درگاه بلوپال (پرداخت کارتی/آنلاین)\n\n"
            f"منبع کلید: {source_note}"
            f"{webhook_note}",
            reply_markup=kb.blupal_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_blupal_set_key")
    async def cb_admin_blupal_set_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "blupal_api_key", ""))
        masked = f"...{current[-4:]}" if current else "❌ تنظیم نشده"
        await state.set_state(AdminSetBlupal.waiting_key)
        await safe_edit(
            call,
            f"💳 API Key حساب بلوپال را ارسال کن (از blupal.net → مدیریت API Key).\n"
            f"وضعیت فعلی: {masked}\n\n"
            f"برای غیرفعال‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb("adm_set_blupal"),
        )
        await call.answer()

    @router.message(AdminSetBlupal.waiting_key)
    async def process_set_blupal_key(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "blupal_api_key", ""))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "blupal_key_change", "API Key بلوپال حذف شد."))
            await message.answer(db.get_text('handlers_admin.auto_d1a6314d', '✅ API Key بلوپال حذف شد و درگاه غیرفعال شد.'), reply_markup=kb.blupal_settings_kb(db))
            return
        (await asyncio.to_thread(db.set_setting, "blupal_api_key", text))
        (await asyncio.to_thread(db.set_setting, "blupal_payment_enabled", "1"))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "blupal_key_change", "API Key بلوپال تغییر کرد."))
        await message.answer(
            db.get_text('handlers_admin.auto_91daff57', '✅ API Key بلوپال ذخیره شد و درگاه فعال شد.\nیادت نره آدرس وب\u200cهوک را هم در داشبورد بلوپال ثبت کنی (در همین صفحه نمایش داده شد).'),
            reply_markup=kb.blupal_settings_kb(db),
        )


    # -------------------------------------------------------------------
    # کارت‌به‌کارت با تایید خودکار (پیامک بانک) — همان چیزی که در پنل وب
    # مستقل و مینی‌اپ هست، این‌جا هم برای مدیریت از داخل بات در دسترس است.
    # -------------------------------------------------------------------

    # -------------------------------------------------------------------
    # پرداخت‌های NoapayBot (خرید استارز تلگرام، تایید خودکار)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_noapay_payments")
    async def cb_admin_noapay_payments(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        (await asyncio.to_thread(db.expire_stale_noapay_invoices))
        (await asyncio.to_thread(db.purge_old_noapay_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_noapay_invoices, 50))
        if not invoices:
            await call.answer(db.get_text('handlers_admin.auto_5d936fb9', 'هیچ پرداخت NoapayBot ای ثبت نشده است.'), show_alert=True)
            return
        await replace_admin_view(
            call,
            "⭐ پرداخت‌های NoapayBot (استارز تلگرام)\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.noapay_invoices_kb(invoices),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("view_noapay_invoice:"))
    async def cb_view_noapay_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "view_noapay_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_noapay_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_fcc2106e', 'فاکتور یافت نشد.'), show_alert=True)
            return

        status_text = {
            "new": "🟡 جدید", "pending": "🟠 در انتظار", "opened": "🟠 باز شده",
            "paid": "🟠 رسید ارسال‌شده", "confirmed": "🟢 تاییدشده", "completed": "🟢 تکمیل‌شده",
            "expired": "🔴 منقضی‌شده", "rejected": "🔴 ردشده",
        }.get(invoice["status"], invoice["status"] or "---")
        kind_text = {"order": "🧾 سفارش", "wallet_topup": "👛 شارژ کیف پول"}.get(invoice["kind"], invoice["kind"])

        text = (
            f"⭐ فاکتور NoapayBot #{invoice['id']}\n"
            f"{kind_text}: #{invoice['ref_id']}\n"
            f"👤 کاربر: {invoice['user_id']}\n"
            f"💰 مبلغ سفارش: {invoice['amount_toman']:,} تومان\n"
            f"⭐ تعداد استارز: {invoice['stars_count']}\n"
        )
        if invoice["quoted_total_toman"]:
            text += f"💱 مبلغ اعلام‌شده توسط NoapayBot: {invoice['quoted_total_toman']:,} تومان\n"
        text += (
            f"📌 وضعیت: {status_text}\n"
            f"🕐 ایجاد: {invoice['created_at'] or '---'}"
        )
        rows = []
        if invoice["payment_url"] and invoice["status"] not in ("completed", "expired", "rejected"):
            rows.append([InlineKeyboardButton(text=tr("🔗 باز کردن فاکتور"), url=invoice["payment_url"])])
        if invoice["status"] not in ("completed", "expired", "rejected"):
            rows.append([InlineKeyboardButton(text=tr("🔄 بررسی وضعیت"), callback_data=f"check_noapay_invoice:{invoice['id']}")])
            rows.append([InlineKeyboardButton(text=tr("❌ لغو و حذف فاکتور"), callback_data=f"cancel_noapay_invoice:{invoice['id']}")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به پرداخت‌های NoapayBot"), callback_data="adm_noapay_payments")])
        await replace_admin_view(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("check_noapay_invoice:"))
    async def cb_check_noapay_invoice(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "check_noapay_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_noapay_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_fcc2106e', 'فاکتور یافت نشد.'), show_alert=True)
            return
        await call.answer(db.get_text('handlers_admin.auto_0b238115', 'در حال بررسی...'))
        result = await noapay_payment.try_verify_and_finalize(db, invoice)
        if result == "verified_now":
            if invoice["kind"] == "wallet_topup":
                text = await noapay_payment.finalize_paid_topup(db, invoice["ref_id"])
            else:
                text = await noapay_payment.finalize_paid_order(db, bot, invoice["ref_id"])
            await call.message.answer(text)
        elif result == "not_paid_yet":
            await call.message.answer(db.get_text('handlers_admin.auto_100d9937', '⏳ هنوز واریزی برای این فاکتور تایید نشده.'))
        elif result == "already_delivered":
            await call.message.answer(db.get_text('handlers_admin.auto_16b47321', '✅ این پرداخت قبلاً تایید و تحویل داده شده است.'))
        elif result in ("expired", "rejected"):
            await call.message.answer(db.get_text('handlers_admin.auto_907eb4b6', '❌ اعتبار این فاکتور تمام شده یا رد شده است.'))
        elif result.startswith("error:"):
            await call.message.answer(tr(f"⚠️ خطا در بررسی وضعیت: {result[6:]}"))

    @router.callback_query(F.data.startswith("cancel_noapay_invoice:"))
    async def cb_cancel_noapay_invoice(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        invoice_id = callback_id(call.data, "cancel_noapay_invoice")
        if invoice_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        invoice = (await asyncio.to_thread(db.get_noapay_invoice, invoice_id))
        if not invoice:
            await call.answer(db.get_text('handlers_admin.auto_4c01ab16', 'فاکتور یافت نشد یا قبلاً حذف شده.'), show_alert=True)
        else:
            (await asyncio.to_thread(db.cancel_and_delete_noapay_invoice, invoice_id))
            await call.answer(db.get_text('handlers_admin.auto_74c6ae8f', '✅ فاکتور لغو و حذف شد.'))

        (await asyncio.to_thread(db.expire_stale_noapay_invoices))
        (await asyncio.to_thread(db.purge_old_noapay_invoices, days=7))
        invoices = (await asyncio.to_thread(db.get_noapay_invoices, 50))
        if not invoices:
            await replace_admin_view(call, "⭐ پرداخت‌های NoapayBot\n\nهیچ پرداخت NoapayBot ای ثبت نشده است.",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")]
                                      ]))
            return
        await replace_admin_view(
            call,
            "⭐ پرداخت‌های NoapayBot (استارز تلگرام)\n\nاین پرداخت‌ها به‌صورت خودکار تایید می‌شوند و در بخش سفارش‌ها/شارژهای دستی نمایش داده نمی‌شوند.",
            reply_markup=kb.noapay_invoices_kb(invoices),
        )

    # -------------------------------------------------------------------
    # تنظیم درگاه پرداخت NoapayBot (خرید استارز تلگرام)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_set_noapay")
    async def cb_admin_set_noapay(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(
            call,
            "⭐ تنظیم درگاه NoapayBot (خرید استارز تلگرام به‌عنوان روش پرداخت)\n\n"
            "کلید API و رمز وب‌هوک را از دستور /apikey داخل ربات NoapayBot بگیر.\n"
            "این درگاه بر اساس «تعداد استارز» کار می‌کند، نه مبلغ تومانی مستقیم؛ "
            "چون نرخ لحظه‌ای ثابت نیست، باید یک نرخ تقریبی (تومان به‌ازای هر استارز) هم تنظیم کنی "
            "تا مبلغ سفارش/شارژ به تعداد استارز تبدیل شود.",
            reply_markup=kb.noapay_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_noapay_toggle")
    async def cb_admin_noapay_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        enabled = (await asyncio.to_thread(db.get_setting, "noapay_payment_enabled", "0")) == "1"
        if not enabled and not noapay_payment.noapay_payment_available(db):
            await call.answer(
                db.get_text('handlers_admin.auto_5f24ff52', '⚠️ برای فعال\u200cکردن، اول باید کلید API و نرخ تبدیل را تنظیم کنی.'), show_alert=True
            )
            return
        new_value = "0" if enabled else "1"
        (await asyncio.to_thread(db.set_setting, "noapay_payment_enabled", new_value))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "noapay_toggle", f"وضعیت درگاه NoapayBot: {new_value}"))
        await safe_edit(call, call.message.text, reply_markup=kb.noapay_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_8f856fdc', '✅ به\u200cروزرسانی شد.'))

    @router.callback_query(F.data == "adm_noapay_set_key")
    async def cb_admin_noapay_set_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "noapay_api_key", ""))
        masked = f"...{current[-4:]}" if current else "❌ تنظیم نشده"
        await state.set_state(AdminSetNoapay.waiting_key)
        await safe_edit(
            call,
            f"🔑 کلید API را ارسال کن (از دستور /apikey داخل ربات NoapayBot).\n"
            f"وضعیت فعلی: {masked}\n\n"
            f"برای پاک‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb("adm_set_noapay"),
        )
        await call.answer()

    @router.message(AdminSetNoapay.waiting_key)
    async def process_set_noapay_key(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "noapay_api_key", ""))
            (await asyncio.to_thread(db.set_setting, "noapay_payment_enabled", "0"))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "noapay_key_change", "کلید API NoapayBot حذف شد."))
            await message.answer(db.get_text('handlers_admin.auto_58f03207', '✅ کلید API NoapayBot حذف شد و درگاه غیرفعال شد.'), reply_markup=kb.noapay_settings_kb(db))
            return
        (await asyncio.to_thread(db.set_setting, "noapay_api_key", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "noapay_key_change", "کلید API NoapayBot تغییر کرد."))
        await message.answer(
            db.get_text('handlers_admin.auto_bfdfc13e', '✅ کلید API NoapayBot ذخیره شد.\nحالا رمز وب\u200cهوک و نرخ تبدیل استارز را هم تنظیم کن تا درگاه فعال شود.'),
            reply_markup=kb.noapay_settings_kb(db),
        )

    @router.callback_query(F.data == "adm_noapay_set_secret")
    async def cb_admin_noapay_set_secret(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "noapay_webhook_secret", ""))
        masked = f"...{current[-4:]}" if current else "❌ تنظیم نشده"
        await state.set_state(AdminSetNoapay.waiting_secret)
        await safe_edit(
            call,
            f"🔏 رمز وب‌هوک (webhook secret) را ارسال کن؛ همراه کلید API از دستور /apikey داخل ربات NoapayBot می‌گیری.\n"
            f"این رمز برای تایید امضای HMAC وب‌هوک‌های ورودی استفاده می‌شود و بدونش پرداخت‌ها آنی تایید نمی‌شوند.\n"
            f"وضعیت فعلی: {masked}\n\n"
            f"برای پاک‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb("adm_set_noapay"),
        )
        await call.answer()

    @router.message(AdminSetNoapay.waiting_secret)
    async def process_set_noapay_secret(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "noapay_webhook_secret", ""))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "noapay_key_change", "رمز وب‌هوک NoapayBot حذف شد."))
            await message.answer(db.get_text('handlers_admin.auto_f908e09d', '✅ رمز وب\u200cهوک حذف شد.'), reply_markup=kb.noapay_settings_kb(db))
            return
        (await asyncio.to_thread(db.set_setting, "noapay_webhook_secret", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "noapay_key_change", "رمز وب‌هوک NoapayBot تغییر کرد."))
        await message.answer(db.get_text('handlers_admin.auto_8b9af661', '✅ رمز وب\u200cهوک ذخیره شد.'), reply_markup=kb.noapay_settings_kb(db))

    @router.callback_query(F.data == "adm_noapay_set_rate")
    async def cb_admin_noapay_set_rate(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "noapay_rate_toman_per_star", "0"))
        await state.set_state(AdminSetNoapay.waiting_rate)
        await safe_edit(
            call,
            f"💱 نرخ تقریبی «تومان به‌ازای هر استارز» را به‌صورت عدد بفرست (مثلاً 5000).\n"
            f"از روی این نرخ، مبلغ سفارش/شارژ کیف‌پول کاربر به تعداد استارز تبدیل می‌شود؛ "
            f"مبلغی که خودِ NoapayBot در لحظه اعلام می‌کند ممکن است کمی با این نرخ فرق داشته باشد، "
            f"ولی مبلغی که از کیف‌پول/سفارش کاربر کم می‌شود همیشه دقیقاً همان مبلغ اصلی خواهد بود.\n"
            f"نرخ فعلی: {int(current or 0):,} تومان",
            reply_markup=kb.admin_back_kb("adm_set_noapay"),
        )
        await call.answer()

    @router.message(AdminSetNoapay.waiting_rate)
    async def process_set_noapay_rate(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", "")
        await state.clear()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_0b8c683d', '❌ یک عدد بزرگ\u200cتر از صفر بفرست.'), reply_markup=kb.noapay_settings_kb(db))
            return
        (await asyncio.to_thread(db.set_setting, "noapay_rate_toman_per_star", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "noapay_key_change", f"نرخ استارز NoapayBot: {text} تومان"))
        await message.answer(tr(f"✅ نرخ روی {int(text):,} تومان برای هر استارز تنظیم شد."), reply_markup=kb.noapay_settings_kb(db))

    # -------------------------------------------------------------------
    # کارت‌به‌کارت با تایید خودکار (پیامک بانک) — همان چیزی که در پنل وب
    # مستقل و مینی‌اپ هست، این‌جا هم برای مدیریت از داخل بات در دسترس است.
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_card_auto")
    async def cb_admin_card_auto(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, "📶 کارت‌به‌کارت با تایید خودکار (پیامک بانک):",
                                  reply_markup=kb.card_auto_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_card_auto_toggle")
    async def cb_admin_card_auto_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "card_to_card_auto_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "card_to_card_auto_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_01efff47', '📶 کارت\u200cبه\u200cکارت با تایید خودکار (پیامک بانک):'),
                         reply_markup=kb.card_auto_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_card_auto_timeout")
    async def cb_admin_card_auto_timeout(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminC2CSettings.waiting_timeout)
        current = (await asyncio.to_thread(db.get_setting, "card_to_card_auto_timeout_minutes", "15"))
        await safe_edit(call, 
            f"⏱ مهلت فعلی: {current} دقیقه\n"
            "بعد از این مهلت، اگر پیامک بانک نرسیده باشد، فاکتور به صف بررسی دستی می‌رود.\n"
            "مهلت جدید را به دقیقه (فقط عدد) ارسال کن:",
            reply_markup=kb.admin_back_kb("adm_card_auto"),
        )
        await call.answer()

    @router.message(AdminC2CSettings.waiting_timeout)
    async def process_card_auto_timeout(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer(db.get_text('handlers_admin.auto_e874b5f5', 'لطفاً یک عدد صحیح حداقل ۱ ارسال کنید.'))
            return
        await state.clear()
        (await asyncio.to_thread(db.set_setting, "card_to_card_auto_timeout_minutes", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "card_to_card_auto_timeout_change",
                                  f"مهلت کارت‌به‌کارت خودکار: {text} دقیقه"))
        await message.answer(db.get_text('handlers_admin.auto_28a66b8a', '✅ مهلت به\u200cروزرسانی شد.'), reply_markup=kb.card_auto_settings_kb(db))

    @router.callback_query(F.data == "adm_card_auto_digits")
    async def cb_admin_card_auto_digits(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminC2CSettings.waiting_digits)
        current = (await asyncio.to_thread(db.get_setting, "card_to_card_auto_amount_digits", "3"))
        await safe_edit(call, 
            f"🔢 تعداد رقم فعلی: {current}\n"
            "این تعداد رقم آخر مبلغ به‌صورت تصادفی اضافه می‌شود تا مبلغ هر فاکتور یکتا شود.\n"
            "عددی بین ۱ تا ۵ ارسال کن (پیشنهاد: ۳):",
            reply_markup=kb.admin_back_kb("adm_card_auto"),
        )
        await call.answer()

    @router.message(AdminC2CSettings.waiting_digits)
    async def process_card_auto_digits(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or not (1 <= int(text) <= 5):
            await message.answer(db.get_text('handlers_admin.auto_13080f15', 'لطفاً عددی بین ۱ تا ۵ ارسال کنید.'))
            return
        await state.clear()
        (await asyncio.to_thread(db.set_setting, "card_to_card_auto_amount_digits", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "card_to_card_auto_digits_change",
                                  f"رقم یکتاساز کارت‌به‌کارت خودکار: {text}"))
        await message.answer(db.get_text('handlers_admin.auto_0e3cad69', '✅ تعداد رقم به\u200cروزرسانی شد.'), reply_markup=kb.card_auto_settings_kb(db))

    @router.callback_query(F.data == "adm_card_auto_unit_toggle")
    async def cb_admin_card_auto_unit_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "card_to_card_sms_amount_unit", "rial"))
        (await asyncio.to_thread(db.set_setting, "card_to_card_sms_amount_unit",
                                  "toman" if current == "rial" else "rial"))
        await safe_edit(call, db.get_text('handlers_admin.auto_01efff47', '📶 کارت\u200cبه\u200cکارت با تایید خودکار (پیامک بانک):'),
                         reply_markup=kb.card_auto_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_c5c68d5d', 'واحد مبلغ تغییر کرد.'))

    @router.callback_query(F.data == "adm_card_auto_webhook")
    async def cb_admin_card_auto_webhook(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        token = (await asyncio.to_thread(db.get_setting, "card_to_card_sms_webhook_token", ""))
        base_url = os.environ.get("MINIAPP_URL") or os.environ.get("API_BASE_URL") or ""
        webhook_url = f"{base_url}/api/webhooks/sms-forwarder" if base_url else None
        text = (
            "📡 اتصال اپ BankSmsForwarder:\n\n"
            f"آدرس وب‌هوک: {webhook_url or '⚠️ آدرس مینی‌اپ روی سرور تنظیم نشده.'}\n"
            f"توکن: {'✅ تنظیم شده (برای دیدن مجدد، بازتولید کن)' if token else '❌ هنوز ساخته نشده'}\n\n"
            "آدرس و توکن را داخل تنظیمات اپ اندروید BankSmsForwarder وارد کن."
        )
        rows = [
            [InlineKeyboardButton(text=tr("🔁 ساخت/بازتولید توکن"), callback_data="adm_card_auto_webhook_regen")],
            [InlineKeyboardButton(text=tr("📖 راهنمای کامل نصب و دانلود"), callback_data="adm_card_auto_webhook_guide")],
            [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_card_auto")],
        ]
        await safe_edit(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data == "adm_card_auto_webhook_guide")
    async def cb_admin_card_auto_webhook_guide(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        text = (
            "📖 *راهنمای کامل اپ فوروارد پیامک (BankSmsForwarder)*\n\n"
            "این اپ اندروید روی گوشی/سیم‌کارتی نصب می‌شود که پیامک واریزی بانک بهش می‌رسد؛ هر پیامک "
            "بانکی را می‌خواند و به آدرس وب‌هوک (همراه توکن) می‌فرستد تا فاکتور کارت‌به‌کارت مربوطه "
            "بدون دخالت دستی تایید شود.\n\n"
            "*نصب و اتصال:*\n"
            "۱. APK را از دکمه پایین دانلود و نصب کن.\n"
            "۲. دسترسی «خواندن پیامک‌ها (SMS)» را داخل اپ تایید کن.\n"
            "۳. آدرس وب‌هوک و توکن (از دکمه قبلی) را داخل تنظیمات اپ وارد کن.\n"
            "۴. اپ را از «بهینه‌سازی باتری» گوشی مستثنی کن تا در پس‌زمینه بسته نشود.\n\n"
            "⚠️ *چرا موقع نصب اخطار امنیتی می‌دهد؟*\n"
            "چون این اپ از گوگل‌پلی نصب نمی‌شود، اندروید هر APK خارج از پلی‌استور را خودکار «ناشناس» "
            "علامت می‌زند و هشدار عمومی «ممکن است مضر باشد» نشان می‌دهد - این هشدار برای همه‌ی اپ‌های "
            "خارج از پلی‌استور است و ربطی به خطرناک‌بودن واقعی کد ندارد. سورس‌کد این اپ کاملاً اوپن‌سورس "
            "و عمومی است و هیچ داده‌ای جز پیامک بانک به سرور خودت فرستاده نمی‌شود."
        )
        rows = [
            [InlineKeyboardButton(text=tr("⬇️ دانلود اپ فوروارد پیامک"),
                                   url="https://github.com/mehdirafatpanah/sms-forwarder/archive/refs/heads/main.zip")],
            [InlineKeyboardButton(text=tr("مشاهده سورس در گیت‌هاب"),
                                   url="https://github.com/mehdirafatpanah/sms-forwarder")],
            [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_card_auto_webhook")],
        ]
        await safe_edit(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="Markdown")
        await call.answer()

    @router.callback_query(F.data == "adm_card_auto_webhook_regen")
    async def cb_admin_card_auto_webhook_regen(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        token = secrets.token_hex(24)
        (await asyncio.to_thread(db.set_setting, "card_to_card_sms_webhook_token", token))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "card_to_card_token_regen",
                                  "توکن وب‌هوک کارت‌به‌کارت بازتولید شد (بات)."))
        rows = [[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_card_auto")]]
        await safe_edit(call, 
            "✅ توکن جدید (فقط همین یک‌بار کامل نشان داده می‌شود، کپی کن و توی اپ BankSmsForwarder وارد کن):\n\n"
            f"`{token}`",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="Markdown",
        )
        await call.answer(db.get_text('handlers_admin.auto_ac8048cd', 'توکن بازتولید شد.'))

    @router.callback_query(F.data == "adm_card_auto_cards")
    async def cb_admin_card_auto_cards(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        cards = (await asyncio.to_thread(db.list_card_to_card_cards))
        await safe_edit(call, db.get_text('handlers_admin.auto_edb07b78', '💳 کارت\u200cهای کارت\u200cبه\u200cکارت خودکار:'), kb.card_auto_cards_kb(cards))
        await call.answer()

    @router.callback_query(F.data == "adm_card_auto_card_add")
    async def cb_admin_card_auto_card_add(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.update_data(c2c_edit_id=None)
        await state.set_state(AdminC2CCard.waiting_number)
        await safe_edit(call, db.get_text('handlers_admin.auto_fcb95c00', 'شماره کارت جدید (۱۶ رقم) را ارسال کن:'), reply_markup=kb.admin_back_kb("adm_card_auto_cards"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_card_auto_card_edit:"))
    async def cb_admin_card_auto_card_edit(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        card_id = callback_id(call.data, "adm_card_auto_card_edit")
        if card_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        card = (await asyncio.to_thread(db.get_card_to_card_card, card_id))
        if card is None:
            return await call.answer(db.get_text('handlers_admin.auto_1d3b8f1e', '⚠️ این کارت دیگر وجود ندارد.'), show_alert=True)
        await state.update_data(c2c_edit_id=card_id)
        await state.set_state(AdminC2CCard.waiting_number)
        await safe_edit(call, 
            f"شماره کارت فعلی: {card['card_number']}\n"
            "شماره کارت جدید (۱۶ رقم) را ارسال کن:",
            reply_markup=kb.admin_back_kb("adm_card_auto_cards"),
        )
        await call.answer()

    @router.message(AdminC2CCard.waiting_number)
    async def process_c2c_card_number(message: Message, state: FSMContext):
        number = re.sub(r"\D", "", message.text or "")
        if len(number) != 16:
            await message.answer(db.get_text('handlers_admin.auto_fd32d5ca', 'شماره کارت باید دقیقاً ۱۶ رقم باشد. دوباره ارسال کن:'))
            return
        await state.update_data(c2c_number=number)
        await state.set_state(AdminC2CCard.waiting_holder)
        await message.answer(db.get_text('handlers_admin.auto_ca2f6832', 'نام صاحب حساب را ارسال کن (برای رد شدن، «-» بفرست):'))

    @router.message(AdminC2CCard.waiting_holder)
    async def process_c2c_card_holder(message: Message, state: FSMContext):
        holder = (message.text or "").strip()
        await state.update_data(c2c_holder="" if holder == "-" else holder)
        await state.set_state(AdminC2CCard.waiting_bank)
        await message.answer(db.get_text('handlers_admin.auto_ba7d1658', 'نام بانک را ارسال کن (اختیاری، برای رد شدن «-» بفرست):'))

    @router.message(AdminC2CCard.waiting_bank)
    async def process_c2c_card_bank(message: Message, state: FSMContext):
        bank = (message.text or "").strip()
        bank = "" if bank == "-" else bank
        data = await state.get_data()
        await state.clear()
        number = data.get("c2c_number", "")
        holder = data.get("c2c_holder", "")
        edit_id = data.get("c2c_edit_id")
        if edit_id:
            if not (await asyncio.to_thread(db.get_card_to_card_card, edit_id)):
                await message.answer(db.get_text('handlers_admin.auto_1d3b8f1e', '⚠️ این کارت دیگر وجود ندارد.'), reply_markup=kb.card_auto_settings_kb(db))
                return
            (await asyncio.to_thread(db.update_card_to_card_card, edit_id,
                                      card_number=number, holder_name=holder, bank_name=bank))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "card_to_card_card_update",
                                      f"کارت #{edit_id} ویرایش شد (بات)."))
            await message.answer(db.get_text('handlers_admin.auto_a6828b4a', '✅ کارت به\u200cروزرسانی شد.'))
        else:
            card_id = (await asyncio.to_thread(db.create_card_to_card_card, number, holder, bank, 0))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "card_to_card_card_create",
                                      f"کارت با ۴ رقم آخر {number[-4:]} اضافه شد (بات)."))
            await message.answer(db.get_text('handlers_admin.auto_d5a3c801', '✅ کارت اضافه شد.'))
        cards = (await asyncio.to_thread(db.list_card_to_card_cards))
        await message.answer(db.get_text('handlers_admin.auto_edb07b78', '💳 کارت\u200cهای کارت\u200cبه\u200cکارت خودکار:'), reply_markup=kb.card_auto_cards_kb(cards))

    @router.callback_query(F.data.startswith("adm_card_auto_card:"))
    async def cb_admin_card_auto_card_detail(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        card_id = callback_id(call.data, "adm_card_auto_card")
        if card_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        card = (await asyncio.to_thread(db.get_card_to_card_card, card_id))
        if card is None:
            return await call.answer(db.get_text('handlers_admin.auto_1d3b8f1e', '⚠️ این کارت دیگر وجود ندارد.'), show_alert=True)
        text = (
            f"💳 شماره: {card['card_number']}\n"
            f"👤 به نام: {card['holder_name'] or '-'}\n"
            f"🏦 بانک: {card['bank_name'] or '-'}\n"
            f"وضعیت: {'🟢 فعال' if card['is_active'] else '🔴 غیرفعال'}"
        )
        await safe_edit(call, text, kb.card_auto_card_detail_kb(card))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_card_auto_card_toggle:"))
    async def cb_admin_card_auto_card_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        card_id = callback_id(call.data, "adm_card_auto_card_toggle")
        if card_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        card = (await asyncio.to_thread(db.get_card_to_card_card, card_id))
        if card is None:
            return await call.answer(db.get_text('handlers_admin.auto_1d3b8f1e', '⚠️ این کارت دیگر وجود ندارد.'), show_alert=True)
        (await asyncio.to_thread(db.toggle_card_to_card_card, card_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "card_to_card_card_toggle",
                                  f"کارت #{card_id} (بات)."))
        card = (await asyncio.to_thread(db.get_card_to_card_card, card_id))
        await safe_edit(call, 
            f"💳 شماره: {card['card_number']}\n"
            f"👤 به نام: {card['holder_name'] or '-'}\n"
            f"🏦 بانک: {card['bank_name'] or '-'}\n"
            f"وضعیت: {'🟢 فعال' if card['is_active'] else '🔴 غیرفعال'}",
            kb.card_auto_card_detail_kb(card),
        )
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_card_auto_card_del:"))
    async def cb_admin_card_auto_card_del(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        card_id = callback_id(call.data, "adm_card_auto_card_del")
        if card_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        if not (await asyncio.to_thread(db.get_card_to_card_card, card_id)):
            return await call.answer(db.get_text('handlers_admin.auto_e8228c59', '⚠️ این کارت قبلاً حذف شده است.'), show_alert=True)
        (await asyncio.to_thread(db.delete_card_to_card_card, card_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "card_to_card_card_delete",
                                  f"کارت #{card_id} حذف شد (بات)."))
        cards = (await asyncio.to_thread(db.list_card_to_card_cards))
        await safe_edit(call, db.get_text('handlers_admin.auto_edb07b78', '💳 کارت\u200cهای کارت\u200cبه\u200cکارت خودکار:'), kb.card_auto_cards_kb(cards))
        await call.answer(db.get_text('handlers_admin.auto_079ac35d', 'کارت حذف شد.'))

    @router.callback_query(F.data.startswith("view_topup:"))
    async def cb_view_topup(call: CallbackQuery, bot: Bot):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        topup_id = callback_id(call.data, "view_topup")
        if topup_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        topup = (await asyncio.to_thread(db.get_topup, topup_id))
        if not topup:
            await call.answer(db.get_text('handlers_admin.auto_55ad46cd', 'درخواست یافت نشد.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        topup = (await asyncio.to_thread(db.get_topup, topup_id))
        if not topup:
            await call.answer(db.get_text('handlers_admin.auto_55ad46cd', 'درخواست یافت نشد.'), show_alert=True)
            return
        if topup["status"] != "pending":
            await call.answer(db.get_text('handlers_admin.auto_eef1da1e', 'این درخواست قبلاً بررسی شده است.'), show_alert=True)
            return

        if not (await asyncio.to_thread(db.approve_topup, topup_id)):
            await call.answer(db.get_text('handlers_admin.auto_eef1da1e', 'این درخواست قبلاً بررسی شده است.'), show_alert=True)
            return
        new_balance = (await asyncio.to_thread(db.get_wallet_credit, topup["user_id"]))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "topup_approve",
            f"شارژ #{topup_id} | کاربر {topup['user_id']} | مبلغ: {topup['amount']:,} | موجودی جدید: {new_balance:,}",
        ))

        try:
            cashback_amount = await asyncio.to_thread(db.get_topup_cashback, topup_id)
            cashback_line = f"🎁 کش‌بک شارژ: {cashback_amount:,} تومان\n" if cashback_amount else ""
            await bot.send_message(
                topup["user_id"],
                tr(f"✅ شارژ کیف پول شما تایید شد!\n💰 مبلغ {topup['amount']:,} تومان اضافه شد.\n"
                f"{cashback_line}👛 موجودی فعلی کیف پول شما: {new_balance:,} تومان"),
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
        await call.answer(db.get_text('handlers_admin.auto_da8aa62a', 'شارژ کیف پول تایید شد.'))
        await _notify_admin_panel_menu(bot, call.from_user.id)

    @router.callback_query(F.data.startswith("topup_reject:"))
    async def cb_topup_reject(call: CallbackQuery, bot: Bot):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)

        topup_id = callback_id(call.data, "topup_reject")
        if topup_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        topup = (await asyncio.to_thread(db.get_topup, topup_id))
        if not topup:
            await call.answer(db.get_text('handlers_admin.auto_55ad46cd', 'درخواست یافت نشد.'), show_alert=True)
            return
        if topup["status"] != "pending":
            await call.answer(db.get_text('handlers_admin.auto_eef1da1e', 'این درخواست قبلاً بررسی شده است.'), show_alert=True)
            return

        if not (await asyncio.to_thread(db.reject_topup, topup_id)):
            await call.answer(db.get_text('handlers_admin.auto_eef1da1e', 'این درخواست قبلاً بررسی شده است.'), show_alert=True)
            return
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "topup_reject",
            f"شارژ #{topup_id} | کاربر {topup['user_id']} | مبلغ: {topup['amount']:,}",
        ))
        try:
            await bot.send_message(
                topup["user_id"],
                tr("❌ متاسفانه درخواست شارژ کیف پول شما تایید نشد. در صورت اشتباه با پشتیبانی تماس بگیرید."),
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
        await call.answer(db.get_text('handlers_admin.auto_cde89184', 'درخواست رد شد.'))
        await _notify_admin_panel_menu(bot, call.from_user.id)

    # -------------------------------------------------------------------
    # مدیریت کدهای تخفیف
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_discounts_menu")
    async def cb_admin_discounts_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
        await replace_admin_view(call, "🎟 مدیریت کدهای تخفیف:", reply_markup=kb.discount_codes_kb(codes, db))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_disc_toggle:"))
    async def cb_admin_disc_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code_id = callback_id(call.data, "adm_disc_toggle")
        if code_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        (await asyncio.to_thread(db.toggle_discount_code, code_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "discount_toggle", f"کد تخفیف #{code_id}"))
        codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
        await safe_edit(call, db.get_text('handlers_admin.auto_e7be342a', '🎟 مدیریت کدهای تخفیف:'), reply_markup=kb.discount_codes_kb(codes, db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_disc_del:"))
    async def cb_admin_disc_del(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code_id = callback_id(call.data, "adm_disc_del")
        if code_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        (await asyncio.to_thread(db.delete_discount_code, code_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "discount_delete", f"کد تخفیف #{code_id}"))
        codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
        await safe_edit(call, db.get_text('handlers_admin.auto_e7be342a', '🎟 مدیریت کدهای تخفیف:'), reply_markup=kb.discount_codes_kb(codes, db))
        await call.answer(db.get_text('handlers_admin.auto_dd808d7a', 'کد حذف شد.'))

    @router.callback_query(F.data == "adm_disc_add")
    async def cb_admin_disc_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCreateDiscount.waiting_code)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_812a945f', 'نام کد تخفیف را ارسال کنید (مثلاً WELCOME20، بدون فاصله):'), reply_markup=kb.admin_back_kb("adm_discounts_menu")
        )
        await call.answer()

    @router.message(AdminCreateDiscount.waiting_code)
    async def process_disc_code(message: Message, state: FSMContext):
        code = message.text.strip()
        if (await asyncio.to_thread(db.get_discount_code, code)):
            await message.answer(db.get_text('handlers_admin.auto_bb7f1228', '⛔️ این کد از قبل وجود دارد. یک نام دیگر ارسال کنید:'))
            return
        await state.update_data(disc_code=code)
        await state.set_state(AdminCreateDiscount.waiting_type_value)
        await message.answer(
            db.get_text('handlers_admin.auto_6636a04d', 'نوع و مقدار تخفیف را به یکی از این دو شکل ارسال کنید:\n\nبرای تخفیف درصدی: `percent 20`\nبرای تخفیف مبلغ ثابت: `fixed 50000`'),
            parse_mode="Markdown",
        )

    @router.message(AdminCreateDiscount.waiting_type_value)
    async def process_disc_type_value(message: Message, state: FSMContext):
        parts = message.text.strip().split()
        if len(parts) != 2 or parts[0].lower() not in ("percent", "fixed") or not parts[1].isdigit():
            await message.answer(db.get_text('handlers_admin.auto_e00547f9', 'فرمت اشتباه است. مثال درست: `percent 20` یا `fixed 50000`'), parse_mode="Markdown")
            return

        kind, value = parts[0].lower(), int(parts[1])
        if kind == "percent":
            await state.update_data(disc_percent=value, disc_fixed=None)
            await state.set_state(AdminCreateDiscount.waiting_max_discount_amount)
            await message.answer(tr(
                "حداکثر مبلغ تخفیف (سقف تخفیف) به تومان چقدر باشد؟ مثلاً برای «۲۰٪ تا سقف ۴۰ هزار تومان» عدد 40000 را بفرست.\n"
                "برای بدون سقف عدد 0 را بفرست."
            ))
            return
        else:
            await state.update_data(disc_percent=None, disc_fixed=value, disc_max_discount_amount=None)

        await state.set_state(AdminCreateDiscount.waiting_maxuses)
        await message.answer(db.get_text('handlers_admin.auto_316028eb', 'سقف تعداد استفاده از این کد چند بار باشد؟ (برای نامحدود عدد 0 را بفرست)'))

    @router.message(AdminCreateDiscount.waiting_max_discount_amount)
    async def process_disc_max_discount_amount(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer(db.get_text('handlers_admin.auto_607a0779', 'لطفاً فقط عدد ارسال کنید (0 برای بدون محدودیت).'))
            return
        await state.update_data(disc_max_discount_amount=int(message.text.strip()) or None)
        await state.set_state(AdminCreateDiscount.waiting_maxuses)
        await message.answer(db.get_text('handlers_admin.auto_316028eb', 'سقف تعداد استفاده از این کد چند بار باشد؟ (برای نامحدود عدد 0 را بفرست)'))

    @router.message(AdminCreateDiscount.waiting_maxuses)
    async def process_disc_maxuses(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer(db.get_text('handlers_admin.auto_9f7dd44c', 'لطفاً فقط عدد ارسال کنید (0 برای نامحدود).'))
            return
        max_uses = int(message.text.strip())
        await state.update_data(disc_maxuses=max_uses)
        await state.set_state(AdminCreateDiscount.waiting_min_purchase)
        await message.answer(db.get_text('handlers_admin.auto_a57dba1d', 'حداقل مبلغ سبد خرید برای اعمال این کد چقدر باشد؟ (تومان — برای بدون محدودیت عدد 0 را بفرست)'))

    @router.message(AdminCreateDiscount.waiting_min_purchase)
    async def process_disc_min_purchase(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer(db.get_text('handlers_admin.auto_607a0779', 'لطفاً فقط عدد ارسال کنید (0 برای بدون محدودیت).'))
            return
        await state.update_data(disc_min_purchase=int(message.text.strip()) or None)
        await state.set_state(AdminCreateDiscount.waiting_max_purchase)
        await message.answer(db.get_text('handlers_admin.auto_bbdcec92', 'حداکثر مبلغ سبد خرید برای اعمال این کد چقدر باشد؟ (تومان — برای بدون محدودیت عدد 0 را بفرست)'))

    @router.message(AdminCreateDiscount.waiting_max_purchase)
    async def process_disc_max_purchase(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer(db.get_text('handlers_admin.auto_607a0779', 'لطفاً فقط عدد ارسال کنید (0 برای بدون محدودیت).'))
            return
        await state.update_data(disc_max_purchase=int(message.text.strip()) or None)
        await state.set_state(AdminCreateDiscount.waiting_scope)
        await message.answer(
            db.get_text('handlers_admin.auto_055c2c20', 'این کد تخفیف روی چه چیزی قابل استفاده باشد؟'),
            reply_markup=kb.discount_scope_picker_kb(),
        )

    @router.callback_query(AdminCreateDiscount.waiting_scope, F.data.startswith("adm_disc_scope:"))
    async def process_disc_scope_pick(call: CallbackQuery, state: FSMContext):
        scope = call.data.split(":", 1)[1]
        if scope == "all":
            await state.update_data(disc_product_id=None, disc_category_id=None)
            await state.set_state(AdminCreateDiscount.waiting_expiry)
            await safe_edit(call, db.get_text('handlers_admin.auto_9c226230', 'چند روز دیگر این کد تخفیف منقضی شود؟ (برای بدون انقضا عدد 0 را بفرست)'))
            await call.answer()
            return
        if scope == "cat":
            categories = (await asyncio.to_thread(db.get_categories, active_only=True))
            if not categories:
                await call.answer(db.get_text('handlers_admin.auto_ec246ead', 'هیچ دسته\u200cبندی\u200cای وجود ندارد.'), show_alert=True)
                return
            await state.set_state(AdminCreateDiscount.waiting_scope_category)
            await safe_edit(call, db.get_text('handlers_admin.auto_1c8f675a', 'کدام دسته\u200cبندی؟'), reply_markup=kb.discount_scope_categories_kb(categories))
            await call.answer()
            return
        if scope == "prod":
            categories = (await asyncio.to_thread(db.get_categories, active_only=True))
            if not categories:
                await call.answer(db.get_text('handlers_admin.auto_ec246ead', 'هیچ دسته\u200cبندی\u200cای وجود ندارد.'), show_alert=True)
                return
            await state.set_state(AdminCreateDiscount.waiting_scope_product)
            await safe_edit(
                call, db.get_text('handlers_admin.auto_d24ad63a', 'محصول موردنظر در کدام دسته\u200cبندی است؟'),
                reply_markup=kb.discount_scope_categories_kb(categories),
            )
            await call.answer()
            return
        if scope == "mprod":
            products = (await asyncio.to_thread(db.get_all_products))
            if not products:
                await call.answer(tr("هیچ محصولی وجود ندارد."), show_alert=True)
                return
            await state.update_data(disc_selected_products=[])
            await state.set_state(AdminCreateDiscount.waiting_scope_products_multi)
            await safe_edit(
                call, tr("محصولات موردنظر را انتخاب کن (چند مورد ممکن است)، سپس روی «تایید» بزن:"),
                reply_markup=kb.discount_scope_products_multi_kb(products, []),
            )
            await call.answer()
            return

    @router.callback_query(AdminCreateDiscount.waiting_scope_products_multi, F.data.startswith("adm_disc_scope_mprod_toggle:"))
    async def process_disc_scope_mprod_toggle(call: CallbackQuery, state: FSMContext):
        product_id = int(call.data.split(":", 1)[1])
        data = await state.get_data()
        selected = list(data.get("disc_selected_products") or [])
        if product_id in selected:
            selected.remove(product_id)
        else:
            selected.append(product_id)
        await state.update_data(disc_selected_products=selected)
        products = (await asyncio.to_thread(db.get_all_products))
        await safe_edit(
            call, tr("محصولات موردنظر را انتخاب کن (چند مورد ممکن است)، سپس روی «تایید» بزن:"),
            reply_markup=kb.discount_scope_products_multi_kb(products, selected),
        )
        await call.answer()

    @router.callback_query(AdminCreateDiscount.waiting_scope_products_multi, F.data == "adm_disc_scope_mprod_done")
    async def process_disc_scope_mprod_done(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        selected = data.get("disc_selected_products") or []
        if not selected:
            await call.answer(tr("حداقل یک محصول را انتخاب کن."), show_alert=True)
            return
        await state.update_data(disc_product_id=None, disc_category_id=None, disc_product_ids=selected)
        await state.set_state(AdminCreateDiscount.waiting_expiry)
        await safe_edit(call, db.get_text('handlers_admin.auto_9c226230', 'چند روز دیگر این کد تخفیف منقضی شود؟ (برای بدون انقضا عدد 0 را بفرست)'))
        await call.answer()

    @router.callback_query(AdminCreateDiscount.waiting_scope_category, F.data.startswith("adm_disc_scope_cat:"))
    async def process_disc_scope_category(call: CallbackQuery, state: FSMContext):
        cat_id = int(call.data.split(":", 1)[1])
        await state.update_data(disc_product_id=None, disc_category_id=cat_id)
        await state.set_state(AdminCreateDiscount.waiting_expiry)
        await safe_edit(call, db.get_text('handlers_admin.auto_9c226230', 'چند روز دیگر این کد تخفیف منقضی شود؟ (برای بدون انقضا عدد 0 را بفرست)'))
        await call.answer()

    @router.callback_query(AdminCreateDiscount.waiting_scope_product, F.data.startswith("adm_disc_scope_cat:"))
    async def process_disc_scope_product_category(call: CallbackQuery, state: FSMContext):
        cat_id = int(call.data.split(":", 1)[1])
        products = (await asyncio.to_thread(db.get_products, cat_id, active_only=True))
        if not products:
            await call.answer(db.get_text('handlers_admin.auto_f7277c1c', 'محصولی در این دسته\u200cبندی نیست.'), show_alert=True)
            return
        await safe_edit(call, db.get_text('handlers_admin.auto_aca04f3e', 'کدام محصول؟'), reply_markup=kb.discount_scope_products_kb(products))
        await call.answer()

    @router.callback_query(AdminCreateDiscount.waiting_scope_product, F.data.startswith("adm_disc_scope_prod:"))
    async def process_disc_scope_product(call: CallbackQuery, state: FSMContext):
        product_id = int(call.data.split(":", 1)[1])
        await state.update_data(disc_product_id=product_id, disc_category_id=None)
        await state.set_state(AdminCreateDiscount.waiting_expiry)
        await safe_edit(call, db.get_text('handlers_admin.auto_9c226230', 'چند روز دیگر این کد تخفیف منقضی شود؟ (برای بدون انقضا عدد 0 را بفرست)'))
        await call.answer()

    @router.callback_query(
        StateFilter(
            AdminCreateDiscount.waiting_scope, AdminCreateDiscount.waiting_scope_category,
            AdminCreateDiscount.waiting_scope_product, AdminCreateDiscount.waiting_scope_products_multi,
        ),
        F.data == "adm_disc_scope_back",
    )
    async def process_disc_scope_back(call: CallbackQuery, state: FSMContext):
        await state.set_state(AdminCreateDiscount.waiting_scope)
        await safe_edit(call, db.get_text('handlers_admin.auto_055c2c20', 'این کد تخفیف روی چه چیزی قابل استفاده باشد؟'), reply_markup=kb.discount_scope_picker_kb())
        await call.answer()

    @router.message(AdminCreateDiscount.waiting_expiry)
    async def process_disc_expiry(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer(db.get_text('handlers_admin.auto_6327865a', 'لطفاً فقط عدد روز ارسال کنید (0 برای بدون انقضا).'))
            return
        days = int(message.text.strip())
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat() if days > 0 else None
        await state.update_data(disc_expires_at=expires_at)
        await state.set_state(AdminCreateDiscount.waiting_per_user)
        await message.answer(db.get_text('handlers_admin.auto_31b96609', 'هر کاربر حداکثر چند بار می\u200cتواند از این کد استفاده کند؟ (برای نامحدود عدد 0 را بفرست)'))

    @router.message(AdminCreateDiscount.waiting_per_user)
    async def process_disc_per_user(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer(db.get_text('handlers_admin.auto_9f7dd44c', 'لطفاً فقط عدد ارسال کنید (0 برای نامحدود).'))
            return
        await state.update_data(disc_per_user_limit=int(message.text.strip()) or None)
        await state.set_state(AdminCreateDiscount.waiting_first_only)
        await message.answer(db.get_text('handlers_admin.auto_9de92f73', 'این کد برای چه خریدهایی معتبر باشد؟'), reply_markup=kb.discount_first_purchase_kb())

    @router.callback_query(AdminCreateDiscount.waiting_first_only, F.data.startswith("adm_disc_first:"))
    async def process_disc_first_only(call: CallbackQuery, state: FSMContext):
        await state.update_data(disc_first_only=call.data.split(":", 1)[1] == "1")
        await state.set_state(AdminCreateDiscount.waiting_audience)
        await safe_edit(call, db.get_text('handlers_admin.auto_c4638145', 'این کد برای چه کاربرانی قابل استفاده باشد؟'), reply_markup=kb.discount_audience_kb())
        await call.answer()

    @router.callback_query(AdminCreateDiscount.waiting_audience, F.data.startswith("adm_disc_aud:"))
    async def process_disc_audience(call: CallbackQuery, state: FSMContext):
        audience = call.data.split(":", 1)[1]
        if audience not in ("all", "normal", "reseller"):
            audience = "all"
        data = await state.get_data()
        (await asyncio.to_thread(db.create_discount_code,
            data["disc_code"], percent=data.get("disc_percent"), fixed_amount=data.get("disc_fixed"),
            max_uses=data.get("disc_maxuses", 0), expires_at=data.get("disc_expires_at"),
            min_purchase=data.get("disc_min_purchase"), max_purchase=data.get("disc_max_purchase"),
            product_id=data.get("disc_product_id"), category_id=data.get("disc_category_id"),
            per_user_limit=data.get("disc_per_user_limit"),
            first_purchase_only=bool(data.get("disc_first_only")), audience=audience,
            max_discount_amount=data.get("disc_max_discount_amount"),
            product_ids=data.get("disc_product_ids"),
        ))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "discount_add", f"کد «{data['disc_code']}»"))
        await state.clear()
        codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
        await call.message.answer(tr(f"✅ کد تخفیف «{data['disc_code']}» ساخته شد."), reply_markup=kb.discount_codes_kb(codes, db))
        await call.answer()

    # -------------------------------------------------------------------
    # کد تخفیف گروهی بر اساس فیلتر کاربران
    # -------------------------------------------------------------------

    BULK_DISC_FILTER_KEYS = {"no_config", "inactive_config", "no_purchase"}

    async def _bulk_disc_user_ids(filters: list, no_purchase_days: int) -> list:
        """آیدی کاربرانی که در هر یک از فیلترهای انتخاب‌شده صدق می‌کنند را
        برمی‌گرداند (union، بدون تکراری) - اگر کاربری در چند فیلتر باشد فقط
        یک‌بار در خروجی می‌آید و در نتیجه فقط یک کد می‌گیرد."""
        merged = set()
        if "no_config" in filters:
            merged.update(await asyncio.to_thread(db.get_user_ids_without_config))
        if "inactive_config" in filters:
            merged.update(await asyncio.to_thread(db.get_user_ids_with_inactive_config))
        if "no_purchase" in filters:
            merged.update(await asyncio.to_thread(db.get_user_ids_without_recent_purchase, no_purchase_days))
        return list(merged)

    def _bulk_disc_filters_label(filters: list, no_purchase_days: int) -> str:
        labels = {
            "no_config": "بدون سرویس",
            "inactive_config": "سرویس منقضی/غیرفعال",
            "no_purchase": f"بدون خرید در {no_purchase_days} روز اخیر",
        }
        return " + ".join(labels[f] for f in filters if f in labels)

    @router.callback_query(F.data == "adm_bulk_disc")
    async def cb_admin_bulk_disc(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await state.update_data(bulk_disc_filters=[])
        await state.set_state(AdminBulkDiscount.picking_filters)
        await replace_admin_view(
            call,
            "🎯 کد تخفیف گروهی — کدام کاربران هدف باشند؟ (می‌توانید چند فیلتر را با هم انتخاب کنید؛ اگر کاربری در چند فیلتر باشد فقط یک کد می‌گیرد)",
            reply_markup=kb.bulk_discount_filters_kb([]),
        )
        await call.answer()

    @router.callback_query(AdminBulkDiscount.picking_filters, F.data.startswith("adm_bulk_disc_filter:"))
    async def cb_admin_bulk_disc_filter(call: CallbackQuery, state: FSMContext):
        key = call.data.split(":", 1)[1]
        if key not in BULK_DISC_FILTER_KEYS:
            await call.answer()
            return
        data = await state.get_data()
        filters = list(data.get("bulk_disc_filters") or [])
        if key in filters:
            filters.remove(key)
        else:
            filters.append(key)
        await state.update_data(bulk_disc_filters=filters)
        await safe_edit(call, call.message.text, reply_markup=kb.bulk_discount_filters_kb(filters))
        await call.answer()

    @router.callback_query(AdminBulkDiscount.picking_filters, F.data == "adm_bulk_disc_next")
    async def cb_admin_bulk_disc_next(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        filters = list(data.get("bulk_disc_filters") or [])
        if not filters:
            await call.answer(tr("⚠️ حداقل یک فیلتر را انتخاب کن."), show_alert=True)
            return
        if "no_purchase" in filters:
            await state.set_state(AdminBulkDiscount.waiting_no_purchase_days)
            await replace_admin_view(
                call,
                "چند روز؟ (کاربرانی که حداقل یک خرید تاییدشده دارند ولی در این تعداد روز اخیر خرید تاییدشده‌ی جدیدی نداشته‌اند هدف قرار می‌گیرند)",
                reply_markup=kb.admin_back_kb("adm_bulk_disc_cancel"),
            )
            await call.answer()
            return
        await state.set_state(AdminBulkDiscount.waiting_type_value)
        await replace_admin_view(
            call,
            "نوع و مقدار تخفیف را به یکی از این دو شکل ارسال کنید:\n\nبرای تخفیف درصدی: `percent 20`\nبرای تخفیف مبلغ ثابت: `fixed 50000`\n\n(همین یک تخفیف برای همه‌ی کاربران این دسته اعمال می‌شود؛ کد هر کاربر یکتا خواهد بود)",
            reply_markup=kb.admin_back_kb("adm_bulk_disc_cancel"),
        )
        await call.answer()

    @router.message(AdminBulkDiscount.waiting_no_purchase_days)
    async def process_bulk_disc_no_purchase_days(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer(tr("⚠️ فقط یک عدد صحیح مثبت وارد کن (مثلاً 30)."))
            return
        await state.update_data(bulk_disc_no_purchase_days=int(text))
        await state.set_state(AdminBulkDiscount.waiting_type_value)
        await message.answer(
            tr("نوع و مقدار تخفیف را به یکی از این دو شکل ارسال کنید:\n\nبرای تخفیف درصدی: `percent 20`\nبرای تخفیف مبلغ ثابت: `fixed 50000`\n\n(همین یک تخفیف برای همه‌ی کاربران این دسته اعمال می‌شود؛ کد هر کاربر یکتا خواهد بود)"),
            parse_mode="Markdown",
            reply_markup=kb.admin_back_kb("adm_bulk_disc_cancel"),
        )

    @router.message(AdminBulkDiscount.waiting_type_value)
    async def process_bulk_disc_type_value(message: Message, state: FSMContext):
        parts = message.text.strip().split()
        if len(parts) != 2 or parts[0].lower() not in ("percent", "fixed") or not parts[1].isdigit():
            await message.answer(tr("فرمت اشتباه است. مثال درست: `percent 20` یا `fixed 50000`"), parse_mode="Markdown")
            return
        kind, value = parts[0].lower(), int(parts[1])
        if kind == "percent":
            await state.update_data(bulk_disc_percent=value, bulk_disc_fixed=None)
        else:
            await state.update_data(bulk_disc_percent=None, bulk_disc_fixed=value)
        await state.set_state(AdminBulkDiscount.waiting_expiry)
        await message.answer(
            tr("چند روز دیگر این کدها منقضی شوند؟ (برای بدون انقضا عدد 0 را بفرست)"),
            reply_markup=kb.admin_back_kb("adm_bulk_disc_cancel"),
        )

    @router.message(AdminBulkDiscount.waiting_expiry)
    async def process_bulk_disc_expiry(message: Message, state: FSMContext):
        if not message.text.strip().isdigit():
            await message.answer(tr("لطفاً فقط عدد روز ارسال کنید (0 برای بدون انقضا)."))
            return
        days = int(message.text.strip())
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat() if days > 0 else None
        data = await state.get_data()
        filters = list(data.get("bulk_disc_filters") or [])
        no_purchase_days = int(data.get("bulk_disc_no_purchase_days") or 30)
        user_ids = await _bulk_disc_user_ids(filters, no_purchase_days)
        if not user_ids:
            await state.clear()
            await message.answer(
                tr("⚠️ هیچ کاربری با این فیلتر(ها) پیدا نشد؛ کدی ساخته نشد."),
                reply_markup=kb.discount_codes_kb((await asyncio.to_thread(db.list_discount_codes, "bulk_admin")), db),
            )
            return
        await state.update_data(bulk_disc_expires_at=expires_at, bulk_disc_user_ids=user_ids)
        value_txt = f"{data.get('bulk_disc_percent')}%" if data.get("bulk_disc_percent") else f"{data.get('bulk_disc_fixed'):,} تومان"
        expiry_txt = f"{days} روز دیگر" if days > 0 else "بدون انقضا"
        filters_label = _bulk_disc_filters_label(filters, no_purchase_days)
        await message.answer(
            tr(
                f"📋 خلاصه:\n👥 فیلتر: {filters_label}\n🔢 تعداد کاربر هدف: {len(user_ids)}\n"
                f"🎟 تخفیف هر کاربر: {value_txt} (کد یکتا و یک‌بارمصرف)\n⏳ انقضا: {expiry_txt}\n\n"
                "با تایید، برای هر کاربر یک کد اختصاصی ساخته و مستقیم در بات برایش ارسال می‌شود."
            ),
            reply_markup=kb.bulk_discount_confirm_kb(),
        )

    @router.callback_query(F.data == "adm_bulk_disc_confirm")
    async def cb_admin_bulk_disc_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        data = await state.get_data()
        user_ids = list(data.get("bulk_disc_user_ids") or [])
        percent = data.get("bulk_disc_percent")
        fixed_amount = data.get("bulk_disc_fixed")
        expires_at = data.get("bulk_disc_expires_at")
        filters = list(data.get("bulk_disc_filters") or [])
        no_purchase_days = int(data.get("bulk_disc_no_purchase_days") or 30)
        await state.clear()
        if not user_ids:
            await call.answer(tr("⚠️ اطلاعات ناقص بود؛ دوباره از اول شروع کن."), show_alert=True)
            return
        await call.answer(tr("⏳ در حال ساخت و ارسال کدها..."))
        pairs = await asyncio.to_thread(
            db.generate_bulk_discount_codes, user_ids, percent, fixed_amount, expires_at
        )
        value_txt = f"{percent}%" if percent else f"{fixed_amount:,} تومان"
        expiry_txt = f"تا {to_jalali_str(datetime.fromisoformat(expires_at))} معتبر است" if expires_at else "بدون تاریخ انقضا"
        success, failed = 0, 0
        for uid, code in pairs:
            text = (
                "🎁 یک کد تخفیف اختصاصی برای شما صادر شد!\n\n"
                f"🎟 کد: `{code}`\n"
                f"💰 تخفیف: {value_txt}\n"
                f"⏳ {expiry_txt}\n\n"
                "این کد فقط یک‌بار و فقط برای شما قابل استفاده است."
            )
            for _attempt in range(3):
                try:
                    await send_telegram(bot, db, uid, text, parse_mode="Markdown")
                    success += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    continue
                except Exception:
                    failed += 1
                    break
            await asyncio.sleep(0.05)
        filters_label = _bulk_disc_filters_label(filters, no_purchase_days)
        (await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "bulk_discount",
            f"کد تخفیف گروهی ({filters_label}) برای {len(pairs)} کاربر ساخته شد | تخفیف: {value_txt} | ارسال موفق: {success} | ناموفق: {failed}",
        ))
        codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
        await call.message.answer(
            tr(f"✅ {len(pairs)} کد تخفیف ساخته شد.\n📤 ارسال موفق: {success}\n❌ ارسال ناموفق: {failed}"),
            reply_markup=kb.discount_codes_kb(codes, db),
        )

    @router.callback_query(F.data == "adm_bulk_disc_cancel")
    async def cb_admin_bulk_disc_cancel(call: CallbackQuery, state: FSMContext):
        await state.clear()
        codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
        await replace_admin_view(call, "🎟 مدیریت کدهای تخفیف:", reply_markup=kb.discount_codes_kb(codes, db))
        await call.answer()

    @router.callback_query(F.data == "adm_gift_menu")
    async def cb_admin_gift_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        codes = await asyncio.to_thread(db.list_wallet_gift_codes)
        await safe_edit(call, db.get_text('handlers_admin.auto_fb0fb9f9', '🎁 مدیریت گیفت\u200cکدهای شارژ کیف پول:'), reply_markup=kb.wallet_gift_codes_kb(codes))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_gift_toggle:"))
    async def cb_admin_gift_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code_id = callback_id(call.data, "adm_gift_toggle")
        if code_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True); return
        await asyncio.to_thread(db.toggle_wallet_gift_code, code_id)
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "wallet_gift_toggle", f"گیفت‌کد #{code_id}")
        await safe_edit(call, db.get_text('handlers_admin.auto_fb0fb9f9', '🎁 مدیریت گیفت\u200cکدهای شارژ کیف پول:'), reply_markup=kb.wallet_gift_codes_kb(await asyncio.to_thread(db.list_wallet_gift_codes)))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_gift_del:"))
    async def cb_admin_gift_del(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code_id = callback_id(call.data, "adm_gift_del")
        if code_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True); return
        await asyncio.to_thread(db.delete_wallet_gift_code, code_id)
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "wallet_gift_delete", f"گیفت‌کد #{code_id}")
        await safe_edit(call, db.get_text('handlers_admin.auto_fb0fb9f9', '🎁 مدیریت گیفت\u200cکدهای شارژ کیف پول:'), reply_markup=kb.wallet_gift_codes_kb(await asyncio.to_thread(db.list_wallet_gift_codes)))
        await call.answer(db.get_text('handlers_admin.auto_c34ce319', 'گیفت\u200cکد حذف شد.'))

    @router.callback_query(F.data == "adm_gift_add")
    async def cb_admin_gift_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCreateWalletGift.waiting_amount)
        await safe_edit(call, db.get_text('handlers_admin.auto_f21eff20', 'مبلغ هر گیفت\u200cکد چقدر باشد؟ (تومان، فقط عدد)'), reply_markup=kb.admin_back_kb("adm_gift_menu"))
        await call.answer()

    @router.message(AdminCreateWalletGift.waiting_amount)
    async def process_gift_amount(message: Message, state: FSMContext):
        text = (message.text or "").strip().replace(",", "")
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_0c4dc1a8', '❌ مبلغ باید یک عدد بزرگ\u200cتر از صفر باشد.')); return
        await state.update_data(gift_amount=int(text))
        await state.set_state(AdminCreateWalletGift.waiting_maxuses)
        await message.answer(db.get_text('handlers_admin.auto_0c231f94', 'این گیفت\u200cکد چند بار قابل استفاده باشد؟ (حداقل 1)'))

    @router.message(AdminCreateWalletGift.waiting_maxuses)
    async def process_gift_maxuses(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer(db.get_text('handlers_admin.auto_9818e9bd', '❌ تعداد استفاده باید حداقل 1 باشد.')); return
        await state.update_data(gift_maxuses=int(text))
        await state.set_state(AdminCreateWalletGift.waiting_expiry)
        await message.answer(db.get_text('handlers_admin.auto_39a091de', 'چند ساعت اعتبار داشته باشد؟ (0 یعنی بدون انقضا)'))

    @router.message(AdminCreateWalletGift.waiting_expiry)
    async def process_gift_expiry(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_b010c7d2', '❌ فقط عدد ارسال کن. 0 یعنی بدون انقضا.')); return
        hours = int(text); data = await state.get_data()
        import secrets
        from datetime import datetime, timezone, timedelta
        code = "GIFT-" + secrets.token_urlsafe(18).replace("-", "").replace("_", "").upper()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat() if hours > 0 else None
        try:
            await asyncio.to_thread(db.create_wallet_gift_code, code, data["gift_amount"], data["gift_maxuses"], expires_at, message.from_user.id)
        except Exception:
            await state.clear(); logging.getLogger("handlers_admin").exception("خطا در ساخت گیفت‌کد توسط ادمین %s", message.from_user.id)
            await message.answer(db.get_text('handlers_admin.auto_d8ded656', '❌ ساخت گیفت\u200cکد ناموفق بود. دوباره تلاش کن.')); return
        await state.clear()
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "wallet_gift_add", f"گیفت‌کد شارژ {data['gift_amount']} تومان")
        expiry_text = f"{hours} ساعت" if hours else "بدون انقضا"
        await message.answer(tr("✅ گیفت‌کد ساخته شد.\n\n" f"🎁 کد: <code>{code}</code>\n" f"💰 مبلغ: {data['gift_amount']:,} تومان\n" f"🔢 تعداد استفاده: {data['gift_maxuses']}\n" f"⏳ اعتبار: {expiry_text}\n\n⚠️ کد خام فقط همین‌جا نمایش داده می‌شود؛ آن را امن نگه دار."), parse_mode="HTML", reply_markup=kb.wallet_gift_codes_kb(await asyncio.to_thread(db.list_wallet_gift_codes)))

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
        await safe_edit(call, db.get_text('handlers_admin.auto_d33a70fe', '🤝 تنظیمات زیرمجموعه\u200cگیری:'), reply_markup=kb.referral_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_referral_multilevel_toggle")
    async def cb_admin_referral_multilevel_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id): return await deny_mid(call)
        cur = await asyncio.to_thread(db.get_setting, "referral_multilevel_enabled", "0")
        await asyncio.to_thread(db.set_setting, "referral_multilevel_enabled", "0" if cur == "1" else "1")
        await safe_edit(call, db.get_text('handlers_admin.auto_d33a70fe', '🤝 تنظیمات زیرمجموعه\u200cگیری:'), reply_markup=kb.referral_settings_kb(db)); await call.answer(db.get_text('handlers_admin.auto_909cb90f', 'وضعیت رفرال چندمرحله\u200cای تغییر کرد.'))

    @router.callback_query(F.data == "adm_referral_multilevel_info")
    async def cb_admin_referral_multilevel_info(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id): return await deny_mid(call)
        en = await asyncio.to_thread(db.get_setting, "referral_multilevel_enabled", "0"); l2 = await asyncio.to_thread(db.get_setting, "referral_level2_percent", "3"); l3 = await asyncio.to_thread(db.get_setting, "referral_level3_percent", "1")
        await call.answer(tr(f"سطح ۲: {l2}% | سطح ۳: {l3}% | {'فعال' if en == '1' else 'غیرفعال'}"), show_alert=True)

    @router.callback_query(F.data == "adm_referral_multilevel_edit")
    async def cb_admin_referral_multilevel_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id): return await deny_mid(call)
        await state.set_state(AdminReferralMultilevel.waiting_value)
        await safe_edit(call, db.get_text('handlers_admin.auto_b596584f', 'درصدها را به شکل «سطح۲،سطح۳» وارد کنید؛ مثال: 3,1'), reply_markup=kb.admin_back_kb("adm_referral_settings")); await call.answer()

    @router.message(AdminReferralMultilevel.waiting_value)
    async def process_referral_multilevel(message: Message, state: FSMContext):
        parts=[x.strip() for x in (message.text or "").replace("٪", "").split(",")]
        if len(parts)!=2 or any(not x.isdigit() or not (0<=int(x)<=100) for x in parts):
            await message.answer(db.get_text('handlers_admin.auto_257b2747', 'فرمت صحیح: 3,1 و هر درصد باید بین ۰ تا ۱۰۰ باشد.')); return
        await asyncio.to_thread(db.set_setting,"referral_level2_percent",parts[0]); await asyncio.to_thread(db.set_setting,"referral_level3_percent",parts[1]); await state.clear()
        await message.answer(tr(f"✅ سطح ۲ = {parts[0]}٪، سطح ۳ = {parts[1]}٪"), reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_percent_edit")
    async def cb_admin_referral_percent_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralPercent.waiting_value)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_40405fbe', 'درصد پورسانت جدید را وارد کنید (عددی بین 0 تا 100):'), reply_markup=kb.admin_back_kb("adm_referral_settings")
        )
        await call.answer()

    @router.message(AdminReferralPercent.waiting_value)
    async def process_referral_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 <= int(text) <= 100):
            await message.answer(db.get_text('handlers_admin.auto_35bf4e65', 'لطفاً یک عدد بین 0 تا 100 ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "referral_percent", text))
        await state.clear()
        await message.answer(tr(f"✅ درصد پورسانت زیرمجموعه‌گیری روی {text}٪ تنظیم شد."), reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_commission_max_edit")
    async def cb_admin_referral_commission_max_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralCommissionMax.waiting_value)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_7f59fc07', 'حداکثر تعداد زیرمجموعه\u200cهایی که پورسانت خریدشان تعلق می\u200cگیرد را وارد کنید (برای نامحدود، عدد 0 را ارسال کنید):'),
            reply_markup=kb.admin_back_kb("adm_referral_settings"),
        )
        await call.answer()

    @router.message(AdminReferralCommissionMax.waiting_value)
    async def process_referral_commission_max(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_48dbdd1b', 'لطفاً یک عدد صحیح (0 یا بیشتر) ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "referral_commission_max_count", text))
        await state.clear()
        label = "نامحدود" if text == "0" else f"{text} نفر"
        await message.answer(tr(f"✅ سقف تعداد نفرات پورسانت‌دار روی «{label}» تنظیم شد."), reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_renewal_percent_edit")
    async def cb_admin_referral_renewal_percent_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralRenewalPercent.waiting_value)
        await safe_edit(
            call,
            "درصد پورسانت تمدید سرویس زیرمجموعه را وارد کنید (عددی بین 0 تا 100؛ 0 = غیرفعال):",
            reply_markup=kb.admin_back_kb("adm_referral_settings"),
        )
        await call.answer()

    @router.message(AdminReferralRenewalPercent.waiting_value)
    async def process_referral_renewal_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 <= int(text) <= 100):
            await message.answer(tr("لطفاً یک عدد بین 0 تا 100 ارسال کنید."))
            return
        (await asyncio.to_thread(db.set_setting, "referral_renewal_percent", text))
        await state.clear()
        await message.answer(tr(f"✅ درصد پورسانت تمدید سرویس روی {text}٪ تنظیم شد."), reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_renewal_max_edit")
    async def cb_admin_referral_renewal_max_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralRenewalMax.waiting_value)
        await safe_edit(
            call,
            "حداکثر تعداد تمدیدهایی که به‌ازای هر زیرمجموعه پورسانت تعلق می‌گیرد را وارد کنید (برای نامحدود، عدد 0 را ارسال کنید):",
            reply_markup=kb.admin_back_kb("adm_referral_settings"),
        )
        await call.answer()

    @router.message(AdminReferralRenewalMax.waiting_value)
    async def process_referral_renewal_max(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit():
            await message.answer(tr("لطفاً یک عدد صحیح (0 یا بیشتر) ارسال کنید."))
            return
        (await asyncio.to_thread(db.set_setting, "referral_renewal_max_count", text))
        await state.clear()
        label = "نامحدود" if text == "0" else f"{text} تمدید"
        await message.answer(tr(f"✅ سقف تعداد تمدیدهای پورسانت‌دار روی «{label}» تنظیم شد."), reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_min_purchase_edit")
    async def cb_admin_referral_min_purchase_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralMinPurchase.waiting_value)
        await safe_edit(call,
            "حداقل مبلغ خرید (تومان) برای تعلق پورسانت اولین خرید را وارد کنید (برای غیرفعال کردن حداقل، عدد 0 را ارسال کنید):",
            reply_markup=kb.admin_back_kb("adm_referral_settings"),
        )
        await call.answer()

    @router.message(AdminReferralMinPurchase.waiting_value)
    async def process_referral_min_purchase(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit():
            await message.answer(tr("لطفاً یک عدد صحیح (0 یا بیشتر) ارسال کنید."))
            return
        (await asyncio.to_thread(db.set_setting, "referral_min_purchase_amount", text))
        await state.clear()
        label = "بدون حداقل" if text == "0" else f"{int(text):,} تومان"
        await message.answer(tr(f"✅ حداقل مبلغ خرید برای پورسانت روی «{label}» تنظیم شد."), reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_min_purchase_strict_toggle")
    async def cb_admin_referral_min_purchase_strict_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "referral_min_purchase_strict", "0"))
        (await asyncio.to_thread(db.set_setting, "referral_min_purchase_strict", "0" if current == "1" else "1"))
        await safe_edit(call, "🤝 تنظیمات زیرمجموعه‌گیری:", reply_markup=kb.referral_settings_kb(db))
        await call.answer(tr("حالت خرید کمتر از حداقل تغییر کرد."))

    # --- حالت ۲: کانفیگ رایگان با تعداد دعوت مشخص ---

    @router.callback_query(F.data == "adm_referral_freeconfig_toggle")
    async def cb_admin_referral_freeconfig_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "referral_free_config_enabled", "0"))
        new_value = "0" if current == "1" else "1"
        if new_value == "1" and not (await asyncio.to_thread(db.get_setting, "referral_free_config_product_id", "")):
            await call.answer(db.get_text('handlers_admin.auto_72fcacb3', 'ابتدا از «انتخاب محصول جایزه» یک محصول انتخاب کنید.'), show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "referral_free_config_enabled", new_value))
        await safe_edit(call, db.get_text('handlers_admin.auto_d33a70fe', '🤝 تنظیمات زیرمجموعه\u200cگیری:'), reply_markup=kb.referral_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_referral_freeconfig_threshold_edit")
    async def cb_admin_referral_freeconfig_threshold_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralFreeConfigThreshold.waiting_value)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_d777df1c', 'با دعوت چند نفر، یک کانفیگ رایگان تعلق بگیرد؟ عدد را وارد کنید:'),
            reply_markup=kb.admin_back_kb("adm_referral_settings"),
        )
        await call.answer()

    @router.message(AdminReferralFreeConfigThreshold.waiting_value)
    async def process_referral_freeconfig_threshold(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer(db.get_text('handlers_admin.auto_3a225594', 'لطفاً یک عدد صحیح بزرگ\u200cتر از صفر ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "referral_free_config_threshold", text))
        await state.clear()
        await message.answer(tr(f"✅ با دعوت {text} نفر، کانفیگ رایگان تعلق می‌گیرد."), reply_markup=kb.referral_settings_kb(db))

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
            await call.answer(db.get_text('handlers_admin.auto_2c51bb96', 'این محصول یافت نشد.'), show_alert=True)
            return
        if not product["is_auto_provision"] or not product["provision_server_id"]:
            await call.answer(
                db.get_text('handlers_admin.auto_f93b0f1d', 'این محصول تحویل خودکار ندارد؛ فقط محصولاتی که به یک پنل وصل و «تحویل خودکار» هستند قابل انتخاب\u200cاند.'),
                show_alert=True,
            )
            return
        (await asyncio.to_thread(db.set_setting, "referral_free_config_product_id", product_id))
        await safe_edit(call, db.get_text('handlers_admin.auto_d33a70fe', '🤝 تنظیمات زیرمجموعه\u200cگیری:'), reply_markup=kb.referral_settings_kb(db))
        await call.answer(f"{tr('✅ محصول')} «{product['name']}» {tr('به‌عنوان جایزه انتخاب شد.')}")

    # --- حالت ۳: شارژ ثابت کیف پول به‌ازای هر دعوت ---

    @router.callback_query(F.data == "adm_referral_invitebonus_toggle")
    async def cb_admin_referral_invitebonus_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "referral_invite_bonus_enabled", "0"))
        new_value = "0" if current == "1" else "1"
        if new_value == "1" and int((await asyncio.to_thread(db.get_setting, "referral_invite_bonus_amount", "0")) or 0) <= 0:
            await call.answer(db.get_text('handlers_admin.auto_932ef487', 'ابتدا مبلغ شارژ را از «تغییر مبلغ شارژ» تنظیم کنید.'), show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "referral_invite_bonus_enabled", new_value))
        await safe_edit(call, db.get_text('handlers_admin.auto_d33a70fe', '🤝 تنظیمات زیرمجموعه\u200cگیری:'), reply_markup=kb.referral_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_referral_invitebonus_amount_edit")
    async def cb_admin_referral_invitebonus_amount_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralInviteBonusAmount.waiting_value)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_afd8abcd', 'مبلغ ثابتی که برای هر دعوت به کیف پول دعوت\u200cکننده اضافه شود را به تومان وارد کنید:'),
            reply_markup=kb.admin_back_kb("adm_referral_settings"),
        )
        await call.answer()

    @router.message(AdminReferralInviteBonusAmount.waiting_value)
    async def process_referral_invitebonus_amount(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 0:
            await message.answer(db.get_text('handlers_admin.auto_e130c470', 'لطفاً یک عدد صحیح ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "referral_invite_bonus_amount", text))
        await state.clear()
        await message.answer(tr(f"✅ مبلغ شارژ به‌ازای هر دعوت روی {int(text):,} تومان تنظیم شد."), reply_markup=kb.referral_settings_kb(db))

    @router.callback_query(F.data == "adm_referral_invitebonus_max_edit")
    async def cb_admin_referral_invitebonus_max_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminReferralInviteBonusMax.waiting_value)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_7b25ffc9', 'این شارژ فقط برای چند نفر اول دعوت\u200cشده اعمال شود؟ عدد را وارد کنید (برای نامحدود، عدد 0 را ارسال کنید):'),
            reply_markup=kb.admin_back_kb("adm_referral_settings"),
        )
        await call.answer()

    @router.message(AdminReferralInviteBonusMax.waiting_value)
    async def process_referral_invitebonus_max(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_48dbdd1b', 'لطفاً یک عدد صحیح (0 یا بیشتر) ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "referral_invite_bonus_max_count", text))
        await state.clear()
        label = "نامحدود" if text == "0" else f"{text} نفر"
        await message.answer(tr(f"✅ سقف تعداد نفرات شارژ به‌ازای دعوت روی «{label}» تنظیم شد."), reply_markup=kb.referral_settings_kb(db))

    # -------------------------------------------------------------------
    # هدیه‌ی عضویت (بند ۴۶ اسپک)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_signup_gift_settings")
    async def cb_admin_signup_gift_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "🎁 تنظیمات هدیه‌ی عضویت:", reply_markup=kb.signup_gift_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_signup_gift_toggle")
    async def cb_admin_signup_gift_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "signup_gift_enabled", "0"))
        new_value = "0" if current == "1" else "1"
        if new_value == "1" and int((await asyncio.to_thread(db.get_setting, "signup_gift_amount", "0")) or 0) <= 0:
            await call.answer(db.get_text('handlers_admin.auto_3d57afb7', 'ابتدا مبلغ هدیه را از «تغییر مبلغ هدیه» تنظیم کنید.'), show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "signup_gift_enabled", new_value))
        await safe_edit(call, db.get_text('handlers_admin.auto_27aab1f3', '🎁 تنظیمات هدیه\u200cی عضویت:'), reply_markup=kb.signup_gift_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_signup_gift_amount_edit")
    async def cb_admin_signup_gift_amount_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminSignupGiftAmount.waiting_value)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_fade0f58', 'مبلغ ثابتی که به کیف پول کاربر تازه\u200cوارد اضافه شود را به تومان وارد کنید:'),
            reply_markup=kb.admin_back_kb("adm_signup_gift_settings"),
        )
        await call.answer()

    @router.message(AdminSignupGiftAmount.waiting_value)
    async def process_signup_gift_amount(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 0:
            await message.answer(db.get_text('handlers_admin.auto_e130c470', 'لطفاً یک عدد صحیح ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "signup_gift_amount", text))
        await state.clear()
        await message.answer(tr(f"✅ مبلغ هدیه‌ی عضویت روی {int(text):,} تومان تنظیم شد."), reply_markup=kb.signup_gift_settings_kb(db))

    @router.callback_query(F.data == "adm_signup_gift_delay_edit")
    async def cb_admin_signup_gift_delay_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminSignupGiftDelay.waiting_value)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_34aaec89', 'چند روز بعد از عضویت (بدون خرید)، هدیه اعطا شود؟ عدد را وارد کنید:'),
            reply_markup=kb.admin_back_kb("adm_signup_gift_settings"),
        )
        await call.answer()

    @router.message(AdminSignupGiftDelay.waiting_value)
    async def process_signup_gift_delay(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer(db.get_text('handlers_admin.auto_3a225594', 'لطفاً یک عدد صحیح بزرگ\u200cتر از صفر ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "signup_gift_delay_days", text))
        await state.clear()
        await message.answer(tr(f"✅ هدیه‌ی عضویت {text} روز بعد از عضویت (بدون خرید) اعطا می‌شود."), reply_markup=kb.signup_gift_settings_kb(db))

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
        await safe_edit(call, db.get_text('handlers_admin.auto_f2b47804', '🎡 مدیریت گردونه شانس:'), reply_markup=kb.wheel_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_wheel_edit_percent")
    async def cb_admin_wheel_edit_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_win_percent)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_c698345a', 'درصد احتمال برد را وارد کنید (عددی بین 0 تا 100، مثلاً 10):'), reply_markup=kb.admin_back_kb("adm_wheel_settings")
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_win_percent)
    async def process_wheel_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 <= int(text) <= 100):
            await message.answer(db.get_text('handlers_admin.auto_35bf4e65', 'لطفاً یک عدد بین 0 تا 100 ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "wheel_win_percent", text))
        await state.clear()
        await message.answer(tr(f"✅ احتمال برد گردونه روی {text}٪ تنظیم شد."), reply_markup=kb.wheel_settings_kb(db))

    @router.callback_query(F.data == "adm_wheel_edit_prizes")
    async def cb_admin_wheel_edit_prizes(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_prizes)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_708d6cf4', 'درصدهای تخفیف ممکن را با کاما جدا کرده و ارسال کنید (مثلاً: 10,20,30,50):'),
            reply_markup=kb.admin_back_kb("adm_wheel_settings"),
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_prizes)
    async def process_wheel_prizes(message: Message, state: FSMContext):
        parts = [p.strip() for p in message.text.split(",")]
        if not all(p.isdigit() and 0 < int(p) <= 100 for p in parts) or not parts:
            await message.answer(db.get_text('handlers_admin.auto_402f4148', 'فرمت اشتباه است. مثال درست: 10,20,30,50'))
            return
        (await asyncio.to_thread(db.set_wheel_prizes, [int(p) for p in parts]))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_f75190ec', '✅ لیست جوایز گردونه به\u200cروزرسانی شد.'), reply_markup=kb.wheel_settings_kb(db))

    @router.callback_query(F.data == "adm_wheel_edit_expiry")
    async def cb_admin_wheel_edit_expiry(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_expiry)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_d80e0cbe', 'کد جایزه چند ساعت اعتبار داشته باشد؟ (فقط عدد، مثلاً 24):'), reply_markup=kb.admin_back_kb("adm_wheel_settings")
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_expiry)
    async def process_wheel_expiry(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "wheel_code_expiry_hours", text))
        await state.clear()
        await message.answer(tr(f"✅ اعتبار کد جایزه روی {text} ساعت تنظیم شد."), reply_markup=kb.wheel_settings_kb(db))

    @router.callback_query(F.data == "adm_wheel_edit_cooldown")
    async def cb_admin_wheel_edit_cooldown(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminWheelSettings.waiting_cooldown)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_a843ff2a', 'فاصله مجاز بین دو چرخش هر کاربر چند ساعت باشد؟ (فقط عدد، مثلاً 24):'), reply_markup=kb.admin_back_kb("adm_wheel_settings")
        )
        await call.answer()

    @router.message(AdminWheelSettings.waiting_cooldown)
    async def process_wheel_cooldown(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "wheel_cooldown_hours", text))
        await state.clear()
        await message.answer(tr(f"✅ فاصله بین دو چرخش روی {text} ساعت تنظیم شد."), reply_markup=kb.wheel_settings_kb(db))

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
            db.get_text('handlers_admin.auto_2daca9a2', 'آستانه\u200cی هشدار موجودی چند کانفیگ باشد؟ (فقط عدد، مثلاً 3):'),
            reply_markup=kb.admin_back_kb("adm_stock_alert_settings"),
        )
        await call.answer()

    @router.message(AdminStockAlertSettings.waiting_threshold)
    async def process_stock_alert_threshold(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) < 0:
            await message.answer(db.get_text('handlers_admin.auto_77c6bf60', 'لطفاً یک عدد صحیح غیرمنفی ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "low_stock_threshold", text))
        await state.clear()
        await message.answer(
            tr(f"✅ آستانه‌ی هشدار موجودی روی {text} کانفیگ تنظیم شد."), reply_markup=kb.stock_alert_settings_kb(db)
        )

    # -------------------------------------------------------------------
    # ساخت کانفیگ شخصی: تنظیمات کلی + سرورهای پنل + قیمت‌گذاری بر اساس بازه
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_location_transfer_settings")
    async def cb_admin_location_transfer_settings(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        limit = await asyncio.to_thread(db.get_setting, "location_change_user_limit", "0")
        free = await asyncio.to_thread(db.get_setting, "location_change_free_quota", "0")
        await replace_admin_view(
            call,
            "📍 تنظیمات تغییر لوکیشن\n\n"
            f"سقف انتقال هر کاربر: {'نامحدود' if limit == '0' else limit}\n"
            f"سهمیه رایگان کلی: {'خاموش' if free == '0' else free + ' انتقال'}",
            reply_markup=kb.location_transfer_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_location_transfer_user_limit")
    async def cb_admin_location_transfer_user_limit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminLocationTransferSettings.waiting_user_limit)
        await safe_edit(call, db.get_text('handlers_admin.auto_de090a8a', 'سقف تعداد انتقال برای هر کاربر را بفرست. ۰ = نامحدود.'), reply_markup=kb.admin_back_kb("adm_location_transfer_settings"))
        await call.answer()

    @router.message(AdminLocationTransferSettings.waiting_user_limit)
    async def process_admin_location_transfer_user_limit(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_979c0b34', 'فقط عدد نامنفی بفرست.'))
            return
        value = int(text)
        await asyncio.to_thread(db.set_setting, "location_change_user_limit", str(value))
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "location_transfer_user_limit", str(value))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_1338f46d', '✅ سقف انتقال هر کاربر ذخیره شد.'), reply_markup=kb.location_transfer_settings_kb(db))

    @router.callback_query(F.data == "adm_location_transfer_free_quota")
    async def cb_admin_location_transfer_free_quota(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminLocationTransferSettings.waiting_free_quota)
        await safe_edit(call, db.get_text('handlers_admin.auto_e5cd22ae', 'سهمیه رایگان کلی چند انتقال باشد؟ ۰ = بدون سهمیه رایگان.'), reply_markup=kb.admin_back_kb("adm_location_transfer_settings"))
        await call.answer()

    @router.message(AdminLocationTransferSettings.waiting_free_quota)
    async def process_admin_location_transfer_free_quota(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_979c0b34', 'فقط عدد نامنفی بفرست.'))
            return
        value = int(text)
        await asyncio.to_thread(db.set_setting, "location_change_free_quota", str(value))
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "location_transfer_free_quota", str(value))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_54dbff97', '✅ سهمیه رایگان کلی ذخیره شد.'), reply_markup=kb.location_transfer_settings_kb(db))

    @router.callback_query(F.data == "adm_custom_config_settings")
    async def cb_admin_custom_config_settings(call: CallbackQuery):
        if not full_access_bot:
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
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "custom_config_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "custom_config_enabled", "0" if current == "1" else "1"))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "custom_config_toggle", f"وضعیت جدید: {'0' if current == '1' else '1'}"))
        await safe_edit(call, db.get_text('handlers_admin.auto_300551ea', '🛠 ساخت کانفیگ شخصی:'), reply_markup=kb.custom_config_menu_kb(db, is_main_bot))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    # -------------------------------------------------------------------
    # تنظیمات ارسال کانفیگ: فعال/غیرفعال بودن ارسال لینک اشتراک و
    # ارسال جداگانه‌ی کانفیگ‌های تکی استخراج‌شده از آن (مستقل از هم)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_delivery_settings")
    async def cb_admin_delivery_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(
            call,
            "📤 تنظیمات ارسال کانفیگ\n\n"
            "این دو مورد مستقل از هم قابل فعال/غیرفعال کردن هستند و روی همه‌ی مسیرهای "
            "تحویل کانفیگ اثر می‌گذارند (بانک کانفیگ، محصول متصل به پنل، ساخت کانفیگ شخصی، کانفیگ تست):",
            reply_markup=kb.delivery_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_deliver_sublink_toggle")
    async def cb_admin_deliver_sublink_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "deliver_sub_link_enabled", "1"))
        new_value = "0" if current != "0" else "1"
        (await asyncio.to_thread(db.set_setting, "deliver_sub_link_enabled", new_value))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "deliver_sublink_toggle", f"وضعیت جدید: {new_value}"))
        await safe_edit(call, db.get_text('handlers_admin.auto_8ec9e02c', '📤 تنظیمات ارسال کانفیگ:'), reply_markup=kb.delivery_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_deliver_individual_toggle")
    async def cb_admin_deliver_individual_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "deliver_individual_configs_enabled", "1"))
        new_value = "0" if current != "0" else "1"
        (await asyncio.to_thread(db.set_setting, "deliver_individual_configs_enabled", new_value))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "deliver_individual_toggle", f"وضعیت جدید: {new_value}"))
        await safe_edit(call, db.get_text('handlers_admin.auto_8ec9e02c', '📤 تنظیمات ارسال کانفیگ:'), reply_markup=kb.delivery_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_edit_post_delivery_text")
    async def cb_admin_edit_post_delivery_text(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminEditPostDeliveryText.waiting_text)
        current = (await asyncio.to_thread(db.get_setting, "post_delivery_custom_text", ""))
        status = f"متن فعلی:\n{current}" if current else "فعلاً چیزی تنظیم نشده."
        await safe_edit(
            call,
            f"📝 متنی که بعد از تحویل کامل هر کانفیگ (بعد از خلاصه‌ی مبلغ) برای کاربر ارسال شود را بفرست.\n\n"
            f"{status}\n\n"
            f"برای غیرفعال‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb("adm_delivery_settings"),
        )
        await call.answer()

    @router.message(AdminEditPostDeliveryText.waiting_text)
    async def process_edit_post_delivery_text(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "post_delivery_custom_text", ""))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "post_delivery_text_change", "متن بعد از تحویل کانفیگ حذف شد."))
            await message.answer(tr("✅ متن بعد از تحویل کانفیگ حذف شد."), reply_markup=kb.delivery_settings_kb(db))
            return
        (await asyncio.to_thread(db.set_setting, "post_delivery_custom_text", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "post_delivery_text_change", "متن بعد از تحویل کانفیگ تغییر کرد."))
        await message.answer(tr("✅ متن بعد از تحویل کانفیگ ذخیره شد."), reply_markup=kb.delivery_settings_kb(db))

    # -------------------------------------------------------------------
    # تصویر پس‌زمینه‌ی کد QR کانفیگ (فعلاً فقط از داخل خودِ بات اصلی قابل
    # تنظیم است، نه از پنل وب مستقل). خودِ کد QR همیشه داخل یک کادر سفید
    # در وسط تصویر قرار می‌گیرد تا قابل‌اسکن‌بودنش تضمین بماند.
    # -------------------------------------------------------------------

    QR_BG_GUIDE = (
        "🖼 تصویر پس‌زمینه کد QR\n\n"
        "می‌تونی یک تصویر برای پس‌زمینه‌ی کیوآرکدی که بعد از خرید برای کاربر ارسال می‌شود انتخاب کنی. "
        "خودِ کد QR روی یک کادر کاملاً سفید در مرکز تصویر قرار می‌گیرد تا همیشه قابل اسکن باشد؛ "
        "تصویر انتخابی فقط دور و اطراف همان کادر را تزئین می‌کند.\n\n"
        "📐 راهنمای کامل سایز:\n"
        "┣ فرمت: JPG یا PNG\n"
        "┣ نسبت تصویر: مربعی (۱:۱) پیشنهاد می‌شود؛ غیرمربعی هم مشکلی ندارد، ربات وسط آن را برش می‌زند و مربع می‌کند\n"
        "┣ سایز پیشنهادی: حداقل ۱۰۰۰×۱۰۰۰ پیکسل (برای کیفیت بهتر، حتی بزرگ‌تر هم مشکلی ندارد)\n"
        "┣ حداقل قابل قبول: ۵۰۰×۵۰۰ پیکسل\n"
        "┣ حجم فایل: حداکثر ۱۰ مگابایت\n"
        "┗ نکته مهم: چون کد QR داخل یک کادر سفید در همان مرکز تصویر (حدود ۶۰٪ عرض) جا می‌گیرد، بهتر است "
        "جزئیات مهم عکس (چهره، متن، لوگو) وسط تصویر نباشد چون زیر آن کادر سفید پنهان می‌شود؛ حاشیه‌های "
        "تصویر بهترین جا برای طرح تزئینی هستند.\n\n"
        "برای آپلود یا تعویض، از دکمه‌ی زیر استفاده کن."
    )

    @router.callback_query(F.data == "adm_qr_background_menu")
    async def cb_admin_qr_background_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, QR_BG_GUIDE, reply_markup=kb.qr_background_menu_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_qr_background_upload")
    async def cb_admin_qr_background_upload(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminSetQrBackground.waiting_photo)
        await safe_edit(
            call,
            QR_BG_GUIDE + "\n\n📎 حالا تصویر مورد نظر را همین‌جا (به‌صورت عکس یا فایل تصویری) بفرست.\n"
            "برای انصراف، «لغو» را بفرست.",
            reply_markup=kb.admin_back_kb("adm_qr_background_menu"),
        )
        await call.answer()

    @router.message(AdminSetQrBackground.waiting_photo, F.text)
    async def on_qr_background_cancel(message: Message, state: FSMContext):
        if message.text.strip() in ("لغو", "/لغو", "-", "cancel"):
            await state.clear()
            await message.answer(tr("❌ لغو شد."), reply_markup=kb.qr_background_menu_kb(db))
            return
        await message.answer(tr("📎 لطفاً یک تصویر (عکس یا فایل تصویری) بفرست، یا برای انصراف «لغو» را بفرست."))

    @router.message(AdminSetQrBackground.waiting_photo, F.photo | F.document)
    async def on_qr_background_photo(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            await state.clear()
            return

        if message.document:
            mime = (message.document.mime_type or "")
            if not mime.startswith("image/"):
                await message.answer(tr("❌ فایل ارسالی تصویر نیست. یک عکس یا فایل تصویری (JPG/PNG) بفرست."))
                return
            file_id = message.document.file_id
            orig_name = message.document.file_name or "bg.jpg"
        else:
            file_id = message.photo[-1].file_id
            orig_name = "bg.jpg"

        tmp_dir = tempfile.mkdtemp(prefix="qr_bg_")
        ext = os.path.splitext(orig_name)[1] or ".jpg"
        tmp_path = os.path.join(tmp_dir, f"uploaded{ext}")
        try:
            file = await message.bot.get_file(file_id)
            await message.bot.download_file(file.file_path, destination=tmp_path)

            from PIL import Image
            with Image.open(tmp_path) as probe:
                probe.verify()
            with Image.open(tmp_path) as probe:
                width, height = probe.size
            if width < 300 or height < 300:
                await message.answer(
                    tr("❌ ابعاد تصویر خیلی کوچک است (حداقل ۵۰۰×۵۰۰ پیشنهاد می‌شود). یک تصویر بزرگ‌تر بفرست، یا «لغو» را بفرست.")
                )
                return

            await asyncio.to_thread(save_qr_background, tmp_path)
        except Exception:
            await message.answer(tr("❌ پردازش تصویر ناموفق بود. لطفاً یک فایل تصویری سالم (JPG/PNG) بفرست."))
            return
        finally:
            try:
                os.remove(tmp_path)
                os.rmdir(tmp_dir)
            except OSError:
                pass

        await asyncio.to_thread(db.set_setting, "qr_background_enabled", "1")
        await state.clear()
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "qr_background_change", "تصویر پس‌زمینه‌ی QR تغییر کرد."
        ))

        try:
            sample = BufferedInputFile(
                build_qr_bytes("https://t.me/", db=db), filename="qr_preview.png"
            )
            await message.answer_photo(
                sample,
                caption=tr("✅ تصویر پس‌زمینه ذخیره و فعال شد. این یک پیش‌نمایش با یک لینک نمونه است:"),
            )
        except Exception:
            await message.answer(tr("✅ تصویر پس‌زمینه ذخیره و فعال شد."))
        await message.answer(tr("منوی پس‌زمینه QR:"), reply_markup=kb.qr_background_menu_kb(db))

    @router.callback_query(F.data == "adm_qr_background_toggle")
    async def cb_admin_qr_background_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not has_qr_background():
            return await call.answer(tr("هنوز تصویری آپلود نشده."), show_alert=True)
        current = (await asyncio.to_thread(db.get_setting, "qr_background_enabled", "1"))
        new_value = "0" if current != "0" else "1"
        (await asyncio.to_thread(db.set_setting, "qr_background_enabled", new_value))
        (await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "qr_background_toggle", f"وضعیت جدید: {new_value}"
        ))
        await safe_edit(call, QR_BG_GUIDE, reply_markup=kb.qr_background_menu_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_qr_background_remove")
    async def cb_admin_qr_background_remove(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        removed = (await asyncio.to_thread(remove_qr_background))
        if removed:
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "qr_background_remove", "تصویر پس‌زمینه‌ی QR حذف شد."))
            await safe_edit(call, "🗑 تصویر پس‌زمینه حذف شد؛ از این پس کد QR ساده‌ی سیاه/سفید ارسال می‌شود.\n\n" + QR_BG_GUIDE, reply_markup=kb.qr_background_menu_kb(db))
            await call.answer(tr("حذف شد."))
        else:
            await call.answer(tr("چیزی برای حذف وجود نداشت."), show_alert=True)

    @router.callback_query(F.data == "adm_qr_background_preview")
    async def cb_admin_qr_background_preview(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not has_qr_background():
            return await call.answer(tr("هنوز تصویری آپلود نشده."), show_alert=True)
        try:
            sample = BufferedInputFile(
                build_qr_bytes("https://t.me/", db=db), filename="qr_preview.png"
            )
            await call.message.answer_photo(sample, caption=tr("👁 پیش‌نمایش پس‌زمینه‌ی QR (با یک لینک نمونه)"))
        except Exception:
            await call.answer(tr("ساخت پیش‌نمایش ناموفق بود."), show_alert=True)
            return
        await call.answer()

    @router.callback_query(F.data == "adm_custom_config_edit_range")
    async def cb_admin_custom_config_edit_range(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminCustomConfigSettings.waiting_min_gb)
        await safe_edit(call, db.get_text('handlers_admin.auto_aa053203', 'حداقل حجم مجاز چند گیگابایت باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb("adm_custom_config_settings"))
        await call.answer()

    @router.message(AdminCustomConfigSettings.waiting_min_gb)
    async def process_custom_config_min_gb(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        await state.update_data(min_gb=text)
        await state.set_state(AdminCustomConfigSettings.waiting_max_gb)
        await message.answer(db.get_text('handlers_admin.auto_8668a967', 'حداکثر حجم مجاز چند گیگابایت باشد؟ (فقط عدد):'))

    @router.message(AdminCustomConfigSettings.waiting_max_gb)
    async def process_custom_config_max_gb(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        min_gb = int(data.get("min_gb", "0"))
        if not text.isdigit() or int(text) <= min_gb:
            await message.answer(tr(f"لطفاً عددی بزرگ‌تر از حداقل ({min_gb}) ارسال کنید."))
            return
        (await asyncio.to_thread(db.set_setting, "custom_config_min_gb", data["min_gb"]))
        (await asyncio.to_thread(db.set_setting, "custom_config_max_gb", text))
        await state.clear()
        await message.answer(
            tr(f"✅ بازه‌ی حجم مجاز روی {data['min_gb']} تا {text} گیگابایت تنظیم شد."),
            reply_markup=kb.custom_config_menu_kb(db, is_main_bot),
        )

    @router.callback_query(F.data == "adm_custom_config_prefix")
    async def cb_admin_custom_config_prefix(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_custom_config_prefix))
        await state.set_state(AdminCustomConfigSettings.waiting_prefix)
        await safe_edit(
            call,
            "🏷 پیش‌وند ثابت نام کانفیگ‌ها را وارد کنید (فقط حروف انگلیسی، عدد و آندرلاین، ۲ تا ۱۵ کاراکتر؛ "
            "بدون خط تیره - خودِ خط تیره خودکار اضافه می‌شود).\n"
            f"وضعیت فعلی: {('«' + current + '-»') if current else 'خاموش'}\n\n"
            "برای خاموش‌کردن پیش‌وند، کلمه‌ی «خاموش» را ارسال کنید.",
            reply_markup=kb.admin_back_kb("adm_custom_config_settings"),
        )
        await call.answer()

    @router.message(AdminCustomConfigSettings.waiting_prefix)
    async def process_custom_config_prefix(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if text in ("خاموش", "-", "off", "none"):
            (await asyncio.to_thread(db.set_custom_config_prefix, ""))
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_f712b8db', '✅ پیش\u200cوند غیرفعال شد.'), reply_markup=kb.custom_config_menu_kb(db, is_main_bot))
            return
        if not re.fullmatch(r"[A-Za-z0-9_]{2,15}", text):
            await message.answer(db.get_text('handlers_admin.auto_d25e397a', '❌ نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۲ تا ۱۵ کاراکتر (بدون خط تیره).'))
            return
        (await asyncio.to_thread(db.set_custom_config_prefix, text))
        await state.clear()
        await message.answer(
            tr(f"✅ پیش‌وند روی «{text}-» تنظیم شد."), reply_markup=kb.custom_config_menu_kb(db, is_main_bot),
        )

    # -------------------------------------------------------------------
    # محصولات کانفیگ‌ساز (چندمحصولی): هرکدوم پنل/اینباند، بازه‌ی حجم/مدت
    # و قیمت‌گذاری خودشو داره. ویزارد افزودن و صفحات ویرایش زیر همه از
    # editing_product_id در FSM data استفاده می‌کنن تا مسیر «افزودن» و
    # «ویرایش» بتونن از همون state ها و همون پیام‌ها به‌صورت مشترک رد بشن.
    # -------------------------------------------------------------------

    async def _ccp_show_view(target, product_id: int, extra_note: str = ""):
        product = (await asyncio.to_thread(db.get_custom_config_product, product_id))
        if not product:
            return
        text = f"🧩 محصول: {product['name']}" + (f"\n\n{extra_note}" if extra_note else "")
        markup = kb.custom_config_product_view_kb(db, product)
        if isinstance(target, CallbackQuery):
            await replace_admin_view(target, text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_ccp_list")
    async def cb_ccp_list(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await replace_admin_view(call,
            "🧩 محصولات کانفیگ‌ساز\n\n"
            "هر محصول می‌تواند پنل/اینباند، بازه‌ی حجم، مدت و قیمت‌گذاری مستقل خودش را داشته باشد. "
            "اگر بیش از یک محصول فعال باشد، کاربر قبل از ساخت کانفیگ اول محصول را انتخاب می‌کند.",
            reply_markup=kb.custom_config_products_list_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_view:"))
    async def cb_ccp_view(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_view")
        await state.clear()
        await _ccp_show_view(call, product_id)
        await call.answer()

    @router.callback_query(F.data == "adm_ccp_add")
    async def cb_ccp_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not (await asyncio.to_thread(db.get_panel_servers, True)):
            await call.answer(db.get_text('handlers_admin.auto_b0d25597', '⛔️ اول باید حداقل یک سرور پنل فعال ثبت کنی.'), show_alert=True)
            return
        await state.clear()
        await state.set_state(AdminCustomConfigProduct.waiting_name)
        await safe_edit(call, db.get_text('handlers_admin.auto_982109f2', 'نام این محصول چیست؟ (مثلاً «پلن آلمان»):'), reply_markup=kb.admin_back_kb("adm_ccp_list"))
        await call.answer()

    @router.message(AdminCustomConfigProduct.waiting_name)
    async def process_ccp_name(message: Message, state: FSMContext):
        name = (message.text or "").strip()
        if not name:
            await message.answer(db.get_text('handlers_admin.auto_457ac65a', 'لطفاً یک نام معتبر ارسال کن.'))
            return
        data = await state.get_data()
        product_id = data.get("editing_product_id")
        if product_id:
            (await asyncio.to_thread(db.update_custom_config_product, product_id, name=name))
            await state.clear()
            await _ccp_show_view(message, product_id, "✅ نام به‌روزرسانی شد.")
            return
        await state.update_data(name=name)
        servers = (await asyncio.to_thread(db.get_panel_servers, True))
        rows = [
            [InlineKeyboardButton(
                text=f"{s['name']} ({kb.PANEL_TYPE_LABELS.get(s['panel_type'], s['panel_type'])})",
                callback_data=f"adm_ccp_new_panel:{s['id']}",
            )]
            for s in servers
        ]
        rows.append([InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_ccp_list")])
        await state.set_state(AdminCustomConfigProduct.waiting_panel_pick)
        await message.answer(
            db.get_text('handlers_admin.auto_0bada540', 'این محصول روی کدام سرور پنل (و اینباند متصل به آن) ساخته شود؟'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @router.callback_query(F.data.startswith("adm_ccp_new_panel:"), AdminCustomConfigProduct.waiting_panel_pick)
    async def cb_ccp_new_panel_pick(call: CallbackQuery, state: FSMContext):
        server_id = int(call.data.split(":", 1)[1])
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminCustomConfigProduct.waiting_volume_min)
        await safe_edit(call, db.get_text('handlers_admin.auto_6c796814', 'حداقل حجم مجاز این محصول چند گیگابایت باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb("adm_ccp_list"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_edit_panel:"))
    async def cb_ccp_edit_panel(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_edit_panel")
        await safe_edit(call, db.get_text('handlers_admin.auto_cb59311a', 'پنل جدید این محصول را انتخاب کن:'),
                         reply_markup=kb.custom_config_product_panel_select_kb(db, product_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_set_panel:"))
    async def cb_ccp_set_panel(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, product_id, server_id = call.data.split(":")
        (await asyncio.to_thread(db.update_custom_config_product, int(product_id), panel_server_id=int(server_id)))
        await _ccp_show_view(call, int(product_id), "✅ پنل محصول به‌روزرسانی شد.")
        await call.answer()

    @router.message(AdminCustomConfigProduct.waiting_volume_min)
    async def process_ccp_volume_min(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_e75b8b41', 'لطفاً یک عدد صحیح مثبت ارسال کن.'))
            return
        await state.update_data(min_gb=int(text))
        await state.set_state(AdminCustomConfigProduct.waiting_volume_max)
        await message.answer(db.get_text('handlers_admin.auto_8668a967', 'حداکثر حجم مجاز چند گیگابایت باشد؟ (فقط عدد):'))

    @router.message(AdminCustomConfigProduct.waiting_volume_max)
    async def process_ccp_volume_max(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        min_gb = data.get("min_gb", 0)
        if not text.isdigit() or int(text) <= min_gb:
            await message.answer(tr(f"لطفاً عددی بزرگ‌تر از حداقل ({min_gb}) ارسال کن."))
            return
        max_gb = int(text)
        product_id = data.get("editing_product_id")
        if product_id:
            (await asyncio.to_thread(db.update_custom_config_product, product_id, min_gb=min_gb, max_gb=max_gb))
            await state.clear()
            await _ccp_show_view(message, product_id, "✅ بازه‌ی حجم به‌روزرسانی شد.")
            return
        await state.update_data(max_gb=max_gb)
        await state.set_state(AdminCustomConfigProduct.waiting_duration_mode_pick)
        await message.answer(
            db.get_text('handlers_admin.auto_096b772b', 'مدت اعتبار این محصول چطور تعیین شود؟'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("⏳ مدت ثابت (ادمین تعیین می‌کند)"), callback_data="adm_ccp_new_duration:fixed")],
                [InlineKeyboardButton(text=tr("🧑‍💻 مدت قابل‌انتخاب توسط مشتری"), callback_data="adm_ccp_new_duration:user_choice")],
                [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_ccp_list")],
            ]),
        )

    @router.callback_query(F.data.startswith("adm_ccp_edit_volume:"))
    async def cb_ccp_edit_volume(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_edit_volume")
        await state.set_state(AdminCustomConfigProduct.waiting_volume_min)
        await state.update_data(editing_product_id=product_id)
        await safe_edit(call, db.get_text('handlers_admin.auto_febd4766', 'حداقل حجم مجاز جدید چند گیگابایت باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb(f"adm_ccp_view:{product_id}"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_new_duration:"), AdminCustomConfigProduct.waiting_duration_mode_pick)
    async def cb_ccp_new_duration_mode(call: CallbackQuery, state: FSMContext):
        mode = call.data.split(":", 1)[1]
        if mode == "fixed":
            await state.set_state(AdminCustomConfigProduct.waiting_duration_value)
            await safe_edit(call, db.get_text('handlers_admin.auto_db946576', 'مدت اعتبار (روز) چند روز باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb("adm_ccp_list"))
        else:
            await state.set_state(AdminCustomConfigProduct.waiting_duration_min)
            await safe_edit(call, db.get_text('handlers_admin.auto_c9f22c18', 'حداقل مدت قابل\u200cانتخاب (روز) چند روز باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb("adm_ccp_list"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_duration_mode:"))
    async def cb_ccp_duration_mode_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_duration_mode")
        await safe_edit(call, db.get_text('handlers_admin.auto_096b772b', 'مدت اعتبار این محصول چطور تعیین شود؟'),
                         reply_markup=kb.custom_config_product_duration_mode_kb(product_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_set_duration_mode:"))
    async def cb_ccp_set_duration_mode(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, product_id, mode = call.data.split(":")
        product_id = int(product_id)
        await state.update_data(editing_product_id=product_id)
        if mode == "fixed":
            await state.set_state(AdminCustomConfigProduct.waiting_duration_value)
            await safe_edit(call, db.get_text('handlers_admin.auto_75b6bf4f', 'مدت اعتبار جدید (روز) چند روز باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb(f"adm_ccp_view:{product_id}"))
        else:
            await state.set_state(AdminCustomConfigProduct.waiting_duration_min)
            await safe_edit(call, db.get_text('handlers_admin.auto_c9f22c18', 'حداقل مدت قابل\u200cانتخاب (روز) چند روز باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb(f"adm_ccp_view:{product_id}"))
        await call.answer()

    @router.message(AdminCustomConfigProduct.waiting_duration_value)
    async def process_ccp_duration_value(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_e75b8b41', 'لطفاً یک عدد صحیح مثبت ارسال کن.'))
            return
        data = await state.get_data()
        product_id = data.get("editing_product_id")
        if product_id:
            (await asyncio.to_thread(db.update_custom_config_product, product_id,
                                      duration_mode="fixed", duration_days=int(text)))
            await state.clear()
            await _ccp_show_view(message, product_id, "✅ مدت اعتبار به‌روزرسانی شد.")
            return
        await state.update_data(duration_mode="fixed", duration_days=int(text))
        await _ccp_ask_pricing_mode(message, state)

    @router.message(AdminCustomConfigProduct.waiting_duration_min)
    async def process_ccp_duration_min(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_e75b8b41', 'لطفاً یک عدد صحیح مثبت ارسال کن.'))
            return
        await state.update_data(min_days=int(text))
        await state.set_state(AdminCustomConfigProduct.waiting_duration_max)
        await message.answer(db.get_text('handlers_admin.auto_e54d6753', 'حداکثر مدت قابل\u200cانتخاب (روز) چند روز باشد؟ (فقط عدد):'))

    @router.message(AdminCustomConfigProduct.waiting_duration_max)
    async def process_ccp_duration_max(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        min_days = data.get("min_days", 0)
        if not text.isdigit() or int(text) <= min_days:
            await message.answer(tr(f"لطفاً عددی بزرگ‌تر از حداقل ({min_days}) ارسال کن."))
            return
        max_days = int(text)
        product_id = data.get("editing_product_id")
        if product_id:
            (await asyncio.to_thread(db.update_custom_config_product, product_id,
                                      duration_mode="user_choice", min_days=min_days, max_days=max_days))
            await state.clear()
            await _ccp_show_view(message, product_id, "✅ مدت اعتبار به‌روزرسانی شد.")
            return
        await state.update_data(duration_mode="user_choice", min_days=min_days, max_days=max_days)
        await _ccp_ask_pricing_mode(message, state)

    async def _ccp_ask_pricing_mode(message: Message, state: FSMContext):
        await state.set_state(AdminCustomConfigProduct.waiting_pricing_mode_pick)
        await message.answer(
            db.get_text('handlers_admin.auto_36c9c444', 'قیمت\u200cگذاری این محصول چطور باشد؟'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr("💵 قیمت فلت (یک نرخ ثابت هر گیگ)"), callback_data="adm_ccp_new_pricing:flat")],
                [InlineKeyboardButton(text=tr("📊 قیمت پله‌ای (بر اساس بازه‌ی حجم)"), callback_data="adm_ccp_new_pricing:tiered")],
                [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_ccp_list")],
            ]),
        )

    async def _ccp_finalize_creation(target, state: FSMContext, flat_price_per_gb=None, pricing_mode="flat"):
        data = await state.get_data()
        product_id = (await asyncio.to_thread(db.create_custom_config_product,
            name=data["name"], panel_server_id=data["panel_server_id"], min_gb=data["min_gb"],
            max_gb=data["max_gb"], duration_mode=data["duration_mode"],
            duration_days=data.get("duration_days", 30), min_days=data.get("min_days"),
            max_days=data.get("max_days"), pricing_mode=pricing_mode, flat_price_per_gb=flat_price_per_gb,
        ))
        (await asyncio.to_thread(db.log_admin_action, target.from_user.id, "ccp_add", f"محصول کانفیگ‌ساز «{data['name']}» (#{product_id})"))
        await state.clear()
        note = "✅ محصول ساخته شد." if pricing_mode == "flat" else "✅ محصول ساخته شد. حالا تعرفه‌های پله‌ای را اضافه کن."
        await _ccp_show_view(target, product_id, note)

    @router.callback_query(F.data.startswith("adm_ccp_new_pricing:"), AdminCustomConfigProduct.waiting_pricing_mode_pick)
    async def cb_ccp_new_pricing_mode(call: CallbackQuery, state: FSMContext):
        mode = call.data.split(":", 1)[1]
        if mode == "flat":
            await state.set_state(AdminCustomConfigProduct.waiting_flat_price)
            await safe_edit(call, db.get_text('handlers_admin.auto_0b98c431', 'قیمت هر گیگابایت چند تومان باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb("adm_ccp_list"))
            await call.answer()
        else:
            await call.answer()
            await _ccp_finalize_creation(call, state, pricing_mode="tiered")

    @router.callback_query(F.data.startswith("adm_ccp_pricing_mode:"))
    async def cb_ccp_pricing_mode_menu(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_pricing_mode")
        await safe_edit(call, db.get_text('handlers_admin.auto_36c9c444', 'قیمت\u200cگذاری این محصول چطور باشد؟'),
                         reply_markup=kb.custom_config_product_pricing_mode_kb(product_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_set_pricing_mode:"))
    async def cb_ccp_set_pricing_mode(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, product_id, mode = call.data.split(":")
        product_id = int(product_id)
        if mode == "flat":
            await state.update_data(editing_product_id=product_id)
            await state.set_state(AdminCustomConfigProduct.waiting_flat_price)
            await safe_edit(call, db.get_text('handlers_admin.auto_eed6e162', 'قیمت جدید هر گیگابایت چند تومان باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb(f"adm_ccp_view:{product_id}"))
        else:
            (await asyncio.to_thread(db.update_custom_config_product, product_id, pricing_mode="tiered"))
            await _ccp_show_view(call, product_id, "✅ حالت قیمت‌گذاری روی «پله‌ای» تنظیم شد؛ تعرفه‌ها را از همین صفحه اضافه کن.")
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_edit_flat_price:"))
    async def cb_ccp_edit_flat_price(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_edit_flat_price")
        await state.update_data(editing_product_id=product_id)
        await state.set_state(AdminCustomConfigProduct.waiting_flat_price)
        await safe_edit(call, db.get_text('handlers_admin.auto_eed6e162', 'قیمت جدید هر گیگابایت چند تومان باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb(f"adm_ccp_view:{product_id}"))
        await call.answer()

    @router.message(AdminCustomConfigProduct.waiting_flat_price)
    async def process_ccp_flat_price(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_e75b8b41', 'لطفاً یک عدد صحیح مثبت ارسال کن.'))
            return
        data = await state.get_data()
        product_id = data.get("editing_product_id")
        if product_id:
            (await asyncio.to_thread(db.update_custom_config_product, product_id,
                                      pricing_mode="flat", flat_price_per_gb=int(text)))
            await state.clear()
            await _ccp_show_view(message, product_id, "✅ قیمت به‌روزرسانی شد.")
            return
        await _ccp_finalize_creation(message, state, flat_price_per_gb=int(text), pricing_mode="flat")

    @router.callback_query(F.data.startswith("adm_ccp_edit_name:"))
    async def cb_ccp_edit_name(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_edit_name")
        await state.update_data(editing_product_id=product_id)
        await state.set_state(AdminCustomConfigProduct.waiting_name)
        await safe_edit(call, db.get_text('handlers_admin.auto_8d14c6bb', 'نام جدید محصول را ارسال کن:'), reply_markup=kb.admin_back_kb(f"adm_ccp_view:{product_id}"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_edit_desc:"))
    async def cb_ccp_edit_desc(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_edit_desc")
        await state.update_data(editing_product_id=product_id)
        await state.set_state(AdminCustomConfigProduct.waiting_description)
        await safe_edit(call, db.get_text('handlers_admin.auto_1a254e2b', 'توضیح جدید این محصول را ارسال کن (برای کاربر نمایش داده می\u200cشود):'), reply_markup=kb.admin_back_kb(f"adm_ccp_view:{product_id}"))
        await call.answer()

    @router.message(AdminCustomConfigProduct.waiting_description)
    async def process_ccp_description(message: Message, state: FSMContext):
        data = await state.get_data()
        product_id = data.get("editing_product_id")
        (await asyncio.to_thread(db.update_custom_config_product, product_id, description=(message.text or "").strip()))
        await state.clear()
        await _ccp_show_view(message, product_id, "✅ توضیح به‌روزرسانی شد.")

    @router.callback_query(F.data.startswith("adm_ccp_toggle:"))
    async def cb_ccp_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_toggle")
        product = (await asyncio.to_thread(db.get_custom_config_product, product_id))
        if not product:
            return await call.answer(db.get_text('handlers_admin.auto_edca6d43', 'یافت نشد.'), show_alert=True)
        (await asyncio.to_thread(db.update_custom_config_product, product_id, is_active=0 if product["is_active"] else 1))
        await _ccp_show_view(call, product_id)
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_ccp_delete:"))
    async def cb_ccp_delete_confirm(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_delete")
        await safe_edit(call, db.get_text('handlers_admin.auto_dfeddcbc', '⚠️ با حذف این محصول، کانفیگ\u200cهای ساخته\u200cشده قبلی دست\u200cنخورده می\u200cمانند ولی دیگر قابل خرید نیست. مطمئنی؟'),
                         reply_markup=kb.custom_config_product_delete_confirm_kb(product_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_delete_force:"))
    async def cb_ccp_delete_force(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_delete_force")
        (await asyncio.to_thread(db.delete_custom_config_product, product_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "ccp_delete", f"محصول #{product_id}"))
        await replace_admin_view(call, "🧩 محصولات کانفیگ‌ساز:", reply_markup=kb.custom_config_products_list_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_1002ca8f', 'محصول حذف شد.'))

    @router.callback_query(F.data.startswith("adm_ccp_tiers:"))
    async def cb_ccp_tiers(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_tiers")
        await replace_admin_view(call,
            "💰 تعرفه‌های پله‌ای این محصول:\n\n"
            "قیمت نهایی = کل حجم انتخابی کاربر × نرخ همان بازه‌ای که حجم داخلش قرار می‌گیرد.",
            reply_markup=kb.custom_config_product_tiers_kb(db, product_id),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ccp_tier_add:"))
    async def cb_ccp_tier_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = callback_id(call.data, "adm_ccp_tier_add")
        await state.update_data(ccp_tier_product_id=product_id)
        await state.set_state(AdminAddCustomConfigProductTier.waiting_from_gb)
        await safe_edit(call, db.get_text('handlers_admin.auto_97dae02d', 'ابتدای این بازه چند گیگابایت باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb(f"adm_ccp_tiers:{product_id}"))
        await call.answer()

    @router.message(AdminAddCustomConfigProductTier.waiting_from_gb)
    async def process_ccp_tier_from(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_e75b8b41', 'لطفاً یک عدد صحیح مثبت ارسال کن.'))
            return
        await state.update_data(from_gb=int(text))
        await state.set_state(AdminAddCustomConfigProductTier.waiting_to_gb)
        await message.answer(
            db.get_text('handlers_admin.auto_1edcab73', 'انتهای این بازه چند گیگابایت باشد؟ (فقط عدد)\nبرای بی\u200cسقف/آخرین بازه، عدد 0 بفرست.')
        )

    @router.message(AdminAddCustomConfigProductTier.waiting_to_gb)
    async def process_ccp_tier_to(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_321920b0', 'لطفاً فقط عدد صحیح ارسال کن (یا 0 برای بی\u200cنهایت).'))
            return
        to_gb = None if int(text) == 0 else int(text)
        if to_gb is not None and to_gb <= data["from_gb"]:
            await message.answer(tr(f"انتهای بازه باید بزرگ‌تر از ابتدای آن ({data['from_gb']}) باشد."))
            return
        await state.update_data(to_gb=to_gb)
        await state.set_state(AdminAddCustomConfigProductTier.waiting_price)
        await message.answer(db.get_text('handlers_admin.auto_5d369599', 'قیمت هر گیگابایت در این بازه چند تومان باشد؟ (فقط عدد):'))

    @router.message(AdminAddCustomConfigProductTier.waiting_price)
    async def process_ccp_tier_price(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_e75b8b41', 'لطفاً یک عدد صحیح مثبت ارسال کن.'))
            return
        data = await state.get_data()
        product_id = data["ccp_tier_product_id"]
        (await asyncio.to_thread(db.add_custom_config_product_tier, product_id, data["from_gb"], data.get("to_gb"), int(text)))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "ccp_tier_add", f"محصول #{product_id}"))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_4faab443', '💰 تعرفه\u200cهای پله\u200cای این محصول:'),
                              reply_markup=kb.custom_config_product_tiers_kb(db, product_id))

    @router.callback_query(F.data.startswith("adm_ccp_tier_delete:"))
    async def cb_ccp_tier_delete(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, product_id, tier_id = call.data.split(":")
        (await asyncio.to_thread(db.delete_custom_config_product_tier, int(tier_id)))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "ccp_tier_delete", f"بازه #{tier_id}"))
        await replace_admin_view(call, "💰 تعرفه‌های پله‌ای این محصول:",
                                  reply_markup=kb.custom_config_product_tiers_kb(db, int(product_id)))
        await call.answer()

    # -------------------------------------------------------------------
    # قیمت‌گذاری تمدید حجم/زمان سرویس‌ها (نرخ ثابت هر گیگ + نرخ ثابت هر روز)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_renewal_pricing")
    async def cb_admin_renewal_pricing(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(
            call,
            "💳 قیمت‌گذاری تمدید حجم/زمان سرویس\n\n"
            "این نرخ‌ها فقط برای «تمدید حجم» و «تمدید زمان» (از حساب کاربری) استفاده می‌شود؛ "
            "«تمدید کامل سرویس» همچنان بر اساس قیمت همان پلن انتخابی محاسبه می‌شود.\n"
            "اگر نرخی صفر باشد، آن دکمه‌ی تمدید برای کاربران قابل استفاده نخواهد بود.",
            reply_markup=kb.renewal_pricing_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_renewal_price_gb")
    async def cb_admin_renewal_price_gb(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalPricing.waiting_price_per_gb)
        await safe_edit(
            call,
            db.get_text('handlers_admin.auto_696f3227', 'نرخ هر گیگابایتِ «تمدید حجم» چند تومان باشد؟ (فقط عدد صحیح؛ صفر = غیرفعال):'),
            reply_markup=kb.admin_back_kb("adm_renewal_pricing"),
        )
        await call.answer()

    @router.message(AdminRenewalPricing.waiting_price_per_gb)
    async def process_renewal_price_gb(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_378acb93', 'لطفاً فقط عدد صحیح (بدون اعشار و منفی) ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "renewal_price_per_gb", text))
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "renewal_price_gb_set", f"مقدار جدید: {text}",
        ))
        await state.clear()
        await message.answer(
            tr(f"✅ نرخ هر گیگ تمدید حجم روی {int(text):,} تومان تنظیم شد."),
            reply_markup=kb.renewal_pricing_kb(db),
        )

    @router.callback_query(F.data == "adm_renewal_price_day")
    async def cb_admin_renewal_price_day(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalPricing.waiting_price_per_day)
        await safe_edit(
            call,
            db.get_text('handlers_admin.auto_def998ce', 'نرخ هر روزِ «تمدید زمان» چند تومان باشد؟ (فقط عدد صحیح؛ صفر = غیرفعال):'),
            reply_markup=kb.admin_back_kb("adm_renewal_pricing"),
        )
        await call.answer()

    @router.message(AdminRenewalPricing.waiting_price_per_day)
    async def process_renewal_price_day(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_378acb93', 'لطفاً فقط عدد صحیح (بدون اعشار و منفی) ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "renewal_price_per_day", text))
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "renewal_price_day_set", f"مقدار جدید: {text}",
        ))
        await state.clear()
        await message.answer(
            tr(f"✅ نرخ هر روز تمدید زمان روی {int(text):,} تومان تنظیم شد."),
            reply_markup=kb.renewal_pricing_kb(db),
        )

    async def deny_reseller_panel_access(call: CallbackQuery):
        await call.answer(db.get_text('handlers_admin.auto_211afb49', '⛔️ اتصال پنل VPN فقط از طریق بات اصلی مدیریت می\u200cشود.'), show_alert=True)

    @router.callback_query(F.data == "adm_panel_servers")
    async def cb_admin_panel_servers(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(call, "🖥 سرورهای پنل VPN متصل:", reply_markup=kb.panel_servers_list_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_panel_server_add")
    async def cb_admin_panel_server_add(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminAddPanelServer.waiting_name)
        await safe_edit(call, db.get_text('handlers_admin.auto_e34b9555', 'یک نام دلخواه برای این سرور بفرست (مثلاً «سرور آلمان»):'), reply_markup=kb.admin_back_kb("adm_panel_servers"))
        await call.answer()

    @router.message(AdminAddPanelServer.waiting_name)
    async def process_panel_server_name(message: Message, state: FSMContext):
        await state.update_data(name=message.text.strip())
        await state.set_state(AdminAddPanelServer.waiting_type)
        await message.answer(db.get_text('handlers_admin.auto_0f4a8567', 'نوع پنل را انتخاب کن:'), reply_markup=kb.panel_type_select_kb())

    @router.callback_query(F.data.startswith("adm_panel_type:"), AdminAddPanelServer.waiting_type)
    async def cb_panel_server_type_selected(call: CallbackQuery, state: FSMContext):
        panel_type = call.data.split(":")[1]
        await state.update_data(panel_type=panel_type)
        await state.set_state(AdminAddPanelServer.waiting_url)
        await call.answer()
        await call.message.answer(db.get_text('handlers_admin.auto_faf1fc9e', 'آدرس API پنل را بفرست (مثلاً https://panel.example.com یا با پورت/مسیر مخصوص):'))

    @router.message(AdminAddPanelServer.waiting_url)
    async def process_panel_server_url(message: Message, state: FSMContext):
        url = message.text.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            await message.answer(db.get_text('handlers_admin.auto_df2458e0', 'آدرس باید با http:// یا https:// شروع شود.'))
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
                db.get_text('handlers_admin.auto_a763a73c', 'API Token پنل را بفرست (نه پسورد ادمین!):\nاز داخل پنل 3X-UI برو به Settings ← Security ← API Token، یکی بساز و همان را اینجا بفرست.\n(نسخه\u200cهای جدید 3X-UI لاگین با یوزر/پس را برای بات\u200cها قبول نمی\u200cکنند و فقط با API Token کار می\u200cکنند.)')
            )
            return
        token_username = TOKEN_ONLY_PANEL_TYPES.get(data.get("panel_type"))
        if token_username:
            await state.update_data(username=token_username)
            await state.set_state(AdminAddPanelServer.waiting_password)
            await message.answer(SECRET_PROMPTS[data["panel_type"]])
            return
        await state.set_state(AdminAddPanelServer.waiting_username)
        if data.get("panel_type") == "hiddify":
            await message.answer(
                db.get_text('handlers_admin.auto_6e649819', 'هیدیفای یوزر/پس ندارد؛ این فیلد استفاده نمی\u200cشود - فقط هر متنی (مثلاً «hiddify») بفرست:')
            )
        else:
            await message.answer(db.get_text('handlers_admin.auto_b10629f3', 'نام کاربری ادمین پنل را بفرست:'))

    @router.message(AdminAddPanelServer.waiting_username)
    async def process_panel_server_username(message: Message, state: FSMContext):
        await state.update_data(username=message.text.strip())
        await state.set_state(AdminAddPanelServer.waiting_password)
        data = await state.get_data()
        if data.get("panel_type") == "hiddify":
            await message.answer(db.get_text('handlers_admin.auto_2b02e4fe', 'Hiddify-API-Key (همان UUID ادمین از داخل پنل: تنظیمات ← API) را بفرست:'))
        else:
            await message.answer(db.get_text('handlers_admin.auto_8dc2f972', 'رمز عبور ادمین پنل را بفرست:'))

    @router.message(AdminAddPanelServer.waiting_password)
    async def process_panel_server_password(message: Message, state: FSMContext):
        await state.update_data(password=message.text.strip())
        try:
            await message.delete()
        except Exception:
            pass
        data = await state.get_data()

        if data["panel_type"] in INBOUND_SELECT_PANEL_TYPES:
            await message.answer(db.get_text('handlers_admin.auto_8b1f39a5', '⏳ در حال دریافت لیست inbound از پنل...'))
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
                await message.answer(tr(f"⛔️ {e}\nسرور ذخیره نشد؛ دوباره از ابتدا تلاش کن."))
                return
            if not inbounds:
                (await asyncio.to_thread(db.delete_panel_server, server_id))
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_9bd7ece4', '⛔️ این پنل هیچ inbound ای ندارد. اول از داخل پنل یک inbound بساز.'))
                return
            await state.update_data(server_id=server_id, inbounds=inbounds, selected_inbound_ids=[])
            await state.set_state(AdminAddPanelServer.waiting_inbound_select)
            await message.answer(
                db.get_text('handlers_admin.auto_4d77a9ff', 'کدام inbound(ها) برای ساخت کاربرهای جدید استفاده شود؟ (می\u200cتوانی چند مورد را تیک بزنی)'),
                reply_markup=kb.inbound_select_kb(inbounds, []),
            )
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
                db.get_text('handlers_admin.auto_6381e83b', 'آدرس عمومی Subscription پنل را بفرست (چون معمولاً با آدرس API ادمین فرق دارد؛ همان دامنه/مسیری که پنل برای لینک اشتراک کاربر نشان می\u200cدهد - بدون / انتهایی):')
            )
            return

        # پنل‌های خانواده‌ی PasarGuard/Marzban/Marzneshin: قالب از کاربر نمونه
        await state.set_state(AdminAddPanelServer.waiting_template_user)
        await message.answer(
            TEMPLATE_PROMPTS.get(data["panel_type"])
            or "یک نام کاربری که از قبل روی این پنل وجود دارد بفرست.\n"
            "تنظیمات پروتکل/گروه (یا سرویس) همین کاربر به‌عنوان قالب پیش‌فرض برای همه‌ی "
            "کانفیگ‌های شخصی جدید استفاده می‌شود."
        )

    @router.callback_query(F.data.startswith("adm_xui_inbound_toggle:"), AdminAddPanelServer.waiting_inbound_select)
    async def cb_panel_server_inbound_toggle(call: CallbackQuery, state: FSMContext):
        inbound_id = int(call.data.split(":")[1])
        data = await state.get_data()
        selected = list(data.get("selected_inbound_ids") or [])
        if inbound_id in selected:
            selected.remove(inbound_id)
        else:
            selected.append(inbound_id)
        await state.update_data(selected_inbound_ids=selected)
        await call.answer()
        try:
            await call.message.edit_reply_markup(reply_markup=kb.inbound_select_kb(data.get("inbounds") or [], selected))
        except TelegramBadRequest:
            pass

    @router.callback_query(F.data == "adm_xui_inbound_confirm", AdminAddPanelServer.waiting_inbound_select)
    async def cb_panel_server_inbound_confirm(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        selected = data.get("selected_inbound_ids") or []
        if not selected:
            await call.answer(db.get_text('handlers_admin.auto_8b267fe4', 'حداقل یک inbound را تیک بزن.'), show_alert=True)
            return
        if data.get("panel_type") in SINGLE_INBOUND_PANEL_TYPES and len(selected) > 1:
            await call.answer(db.get_text('handlers_admin.auto_d262862a', 'برای این نوع پنل فقط یک inbound قابل انتخاب است.'), show_alert=True)
            return
        await state.update_data(inbound_ids=selected)
        await state.set_state(AdminAddPanelServer.waiting_sub_base_url)
        await call.answer()
        await call.message.answer(
            db.get_text('handlers_admin.auto_1e091184', 'آدرس پایه\u200cی Subscription پنل را بفرست (همان چیزی که پنل موقع ساخت کاربر دستی نشانت می\u200cدهد، مثلاً https://domain:2096/sub یا https://domain/sub - بدون / انتهایی):')
        )

    @router.message(AdminAddPanelServer.waiting_sub_base_url)
    async def process_xui_sub_base_url(message: Message, state: FSMContext):
        url = message.text.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            await message.answer(db.get_text('handlers_admin.auto_df2458e0', 'آدرس باید با http:// یا https:// شروع شود.'))
            return
        data = await state.get_data()
        if "inbound_ids" in data:
            import json as _json
            (await asyncio.to_thread(db.update_panel_server, data["server_id"], xui_inbound_ids=_json.dumps(data["inbound_ids"]), xui_sub_base_url=url))
        else:
            (await asyncio.to_thread(db.update_panel_server, data["server_id"], xui_sub_base_url=url))
        await state.clear()
        label = PANEL_TYPE_LABELS.get(data["panel_type"], data["panel_type"])
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_add", f"سرور «{data['name']}» ({label}, #{data['server_id']})"))
        await message.answer(
            f"{tr('✅ سرور')} «{data['name']}» ({label}) {tr('با موفقیت اضافه شد.')}",
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
        await message.answer(db.get_text('handlers_admin.auto_850d2134', '⏳ در حال دریافت قالب از پنل...'))
        try:
            provider = get_provider(server)
            template = await provider.fetch_template_from_user(message.text.strip())
        except PanelError as e:
            (await asyncio.to_thread(db.delete_panel_server, server_id))
            await state.clear()
            await message.answer(tr(f"⛔️ {e}\nسرور ذخیره نشد؛ دوباره از ابتدا تلاش کن."))
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
            f"{tr('✅ سرور')} «{data['name']}» ({label}) {tr('با قالب گرفته‌شده از')} «{message.text.strip()}» {tr('اضافه شد.')}",
            reply_markup=kb.panel_servers_list_kb(db),
        )

    @router.callback_query(F.data.startswith("adm_panel_server_view:"))
    async def cb_admin_panel_server_view(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_view")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        status = "🟢 فعال" if server["is_active"] else "🔴 غیرفعال"
        template_status = panel_server_readiness_text(server)
        cap = await asyncio.to_thread(db.get_panel_capacity_info, server_id)
        capacity_status = "♾️ ظرفیت: نامحدود" if not cap or cap['max_services'] is None else f"📊 ظرفیت: {cap['active_services']}/{cap['max_services']} ({cap['percent']:.0f}٪)" + (" ⚠️ نزدیک سقف" if cap['near_limit'] else "")
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
            f"{capacity_status}\n"
            f"انقضا از اولین اتصال: {'🟢 فعال' if server['start_on_first_use'] else '⚪️ خاموش'}\n"
            f"{template_status}"
        )
        health = (await asyncio.to_thread(db.list_panel_health)).get(server_id)
        if health and health["last_error"]:
            fails = int(health["fail_count"] or 0)
            state_label = "🔴 قطع" if health["status"] == "down" else f"🟡 {fails} بررسی ناموفق اخیر"
            text += f"\n\n🩺 پایش: {state_label}\nآخرین خطا: <code>{html.escape(health['last_error'])}</code>"
        rating_summary = await asyncio.to_thread(db.get_panel_rating_summary, server_id)
        if rating_summary["count"]:
            text += f"\n\n⭐ میانگین امتیاز کاربران: {rating_summary['avg']}/۵ ({rating_summary['count']:,} رأی)"
        await replace_admin_view(call, text, reply_markup=kb.panel_server_view_kb(server))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_panel_server_capacity:"))
    async def cb_admin_panel_server_capacity(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_capacity")
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        cap = await asyncio.to_thread(db.get_panel_capacity_info, server_id)
        current = "نامحدود" if not cap or cap['max_services'] is None else str(cap['max_services'])
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminSetPanelCapacity.waiting_limit)
        await safe_edit(call, f"سقف فعلی: {current}\n\nسقف جدید تعداد سرویس فعال این پنل را بفرست.\nعدد مثبت = سقف مشخص\n۰ = نامحدود", reply_markup=kb.admin_back_kb(f"adm_panel_server_view:{server_id}"))
        await call.answer()

    @router.message(AdminSetPanelCapacity.waiting_limit)
    async def process_panel_server_capacity(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_47791ccf', 'لطفاً فقط یک عدد صحیح نامنفی بفرست.'))
            return
        limit = int(text)
        data = await state.get_data()
        server_id = data.get("panel_server_id")
        cap = await asyncio.to_thread(db.get_panel_capacity_info, server_id)
        if cap and limit > 0 and limit < cap['active_services']:
            await message.answer(tr(f"⛔️ سقف نمی‌تواند کمتر از تعداد سرویس‌های فعال فعلی ({cap['active_services']}) باشد."))
            return
        await asyncio.to_thread(db.update_panel_server, server_id, max_services=(limit or None), capacity_alert_sent=0)
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_capacity_set", f"سرور #{server_id} ← {limit or 'unlimited'}")
        await state.clear()
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        await message.answer(db.get_text('handlers_admin.auto_e1789a23', '✅ سقف ظرفیت ذخیره شد.'), reply_markup=kb.panel_server_view_kb(server))

    async def _xui_server_or_deny(call: CallbackQuery, server_id: int):
        if not full_access_bot:
            await deny_reseller_panel_access(call)
            return None
        if not senior_admin_only(call.from_user.id):
            await deny_mid(call)
            return None
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server or server["panel_type"] != "3xui":
            await call.answer(db.get_text('handlers_admin.auto_c9fececa', 'این قابلیت فقط برای سرور 3X-UI است.'), show_alert=True)
            return None
        return server

    @router.callback_query(F.data.startswith("adm_panel_server_backup:"))
    async def cb_admin_panel_server_backup(call: CallbackQuery):
        server_id = callback_id(call.data, "adm_panel_server_backup")
        server = await _xui_server_or_deny(call, server_id)
        if not server:
            return
        await call.answer(db.get_text('handlers_admin.auto_9a8c4ab6', 'در حال دریافت بکاپ...'))
        try:
            data, _ = await get_provider(server).backup_panel()
        except PanelError as e:
            await call.message.answer(f"⛔️ {e}")
            return
        filename = f"3xui_panel_{server_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
        await call.message.answer_document(BufferedInputFile(data, filename=filename), caption=f"{tr('💾 بکاپ پنل')} «{server['name']}»")
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "panel_server_backup", f"سرور #{server_id}")

    @router.callback_query(F.data.startswith("adm_panel_server_restore:"))
    async def cb_admin_panel_server_restore_start(call: CallbackQuery, state: FSMContext):
        server_id = callback_id(call.data, "adm_panel_server_restore")
        server = await _xui_server_or_deny(call, server_id)
        if not server:
            return
        await state.clear()
        await state.update_data(xui_restore_server_id=server_id)
        await state.set_state(AdminXuiRestore.waiting_file)
        await safe_edit(
            call,
            f"♻️ فایل دیتابیس (x-ui.db) پنل «{server['name']}» را همین‌جا به‌صورت Document ارسال کن.\n\n"
            "⚠️ توجه: با تایید، دیتابیس فعلی پنل با این فایل جایگزین و سرویس Xray روی پنل ری‌استارت می‌شود.",
            reply_markup=kb.xui_restore_waiting_kb(server_id),
        )
        await call.answer()

    @router.callback_query(AdminXuiRestore.waiting_file, F.data.startswith("adm_xui_restore_cancel_wait:"))
    async def cb_admin_xui_restore_cancel_wait(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_xui_restore_cancel_wait")
        await state.clear()
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server:
            await call.answer()
            return
        await safe_edit(call, db.get_text('handlers_admin.auto_59009fb1', '❌ بازیابی کامل لغو شد.'), reply_markup=kb.panel_server_view_kb(server))
        await call.answer()

    @router.message(AdminXuiRestore.waiting_file, F.document)
    async def on_xui_restore_file(message: Message, state: FSMContext):
        data = await state.get_data()
        server_id = data.get("xui_restore_server_id")
        server = await asyncio.to_thread(db.get_panel_server, server_id) if server_id else None
        if not full_access_bot or not server or server["panel_type"] != "3xui" or not senior_admin_only(message.from_user.id):
            await state.clear()
            return
        doc = message.document
        if not doc.file_name.lower().endswith(".db"):
            await message.answer(tr("❌ فایل باید همان دیتابیس x-ui.db باشد (پسوند .db). دوباره ارسال کن."))
            return

        tmp_dir = tempfile.mkdtemp(prefix="xui_restore_")
        tmp_path = os.path.join(tmp_dir, "uploaded.db")
        file = await message.bot.get_file(doc.file_id)
        await message.bot.download_file(file.file_path, destination=tmp_path)

        if not is_valid_sqlite_db(tmp_path):
            try:
                os.remove(tmp_path)
                os.rmdir(tmp_dir)
            except OSError:
                pass
            await message.answer(tr("❌ این فایل یک دیتابیس sqlite معتبر نیست. عملیات لغو شد."))
            await state.clear()
            return

        await state.update_data(xui_restore_tmp_path=tmp_path)
        await state.set_state(AdminXuiRestore.waiting_confirm)
        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        await message.answer(
            tr(f"📦 فایل دریافت شد ({size_mb:.1f} مگابایت).\n\n"
            f"⚠️ با تایید، دیتابیس پنل «{server['name']}» با این فایل جایگزین و Xray روی پنل ری‌استارت می‌شود. مطمئنی؟"),
            reply_markup=kb.xui_restore_confirm_kb(server_id),
        )

    @router.message(AdminXuiRestore.waiting_file)
    async def on_xui_restore_file_wrong_type(message: Message):
        await message.answer(tr("❌ باید فایل دیتابیس x-ui.db را به‌صورت Document ارسال کنی، نه متن یا عکس."))

    @router.callback_query(AdminXuiRestore.waiting_confirm, F.data.startswith("adm_xui_restore_cancel:"))
    async def cb_admin_xui_restore_cancel(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_xui_restore_cancel")
        data = await state.get_data()
        tmp_path = data.get("xui_restore_tmp_path")
        await state.clear()
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server:
            await call.answer()
            return
        await safe_edit(call, "❌ بازیابی لغو شد.", reply_markup=kb.panel_server_view_kb(server))
        await call.answer()

    @router.callback_query(AdminXuiRestore.waiting_confirm, F.data.startswith("adm_xui_restore_confirm:"))
    async def cb_admin_xui_restore_confirm(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_xui_restore_confirm")
        data = await state.get_data()
        tmp_path = data.get("xui_restore_tmp_path")
        await state.clear()
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        if not tmp_path or not os.path.exists(tmp_path):
            await safe_edit(call, "❌ فایل موقت پیدا نشد، دوباره تلاش کن.", reply_markup=kb.panel_server_view_kb(server))
            return

        await safe_edit(call, "⏳ در حال بازیابی دیتابیس پنل...")
        try:
            with open(tmp_path, "rb") as f:
                file_bytes = f.read()
            await get_provider(server).restore_panel(file_bytes)
        except PanelError as e:
            await call.message.answer(tr(f"⛔️ بازیابی ناموفق بود: {e}"))
        else:
            await call.message.answer(f"{tr('✅ دیتابیس پنل')} «{server['name']}» {tr('بازیابی شد.')}" )
            await asyncio.to_thread(db.log_admin_action, call.from_user.id, "panel_server_restore", f"سرور #{server_id}")
        finally:
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass
        await call.message.answer(f"🖥 {server['name']}", reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_panel_server_stats:"))
    async def cb_admin_panel_server_stats(call: CallbackQuery):
        server_id = callback_id(call.data, "adm_panel_server_stats")
        server = await _xui_server_or_deny(call, server_id)
        if not server:
            return
        await call.answer(db.get_text('handlers_admin.auto_9a8c4ab6', 'در حال دریافت آمار...'))
        try:
            stats = await get_provider(server).get_panel_stats()
        except PanelError as e:
            await call.message.answer(f"⛔️ {e}")
            return
        text = (
            f"📊 آمار پنل «{server['name']}»\n\n"
            f"🔌 اینباندها: {stats['inbound_count']:,}\n"
            f"👥 کل کاربران: {stats['total_clients']:,}\n"
            f"🟢 آنلاین: {stats['online_clients']:,}\n"
            f"⌛️ منقضی‌شده: {stats['expired_clients']:,}\n"
            f"🔴 غیرفعال‌شده: {stats['disabled_clients']:,}"
        )
        await call.message.answer(text, reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_xui_inb_new:"))
    async def cb_admin_xui_inbound_new(call: CallbackQuery, state: FSMContext):
        server_id = callback_id(call.data, "adm_xui_inb_new")
        if not await _xui_server_or_deny(call, server_id):
            return
        await state.clear()
        await state.update_data(xui_server_id=server_id)
        await state.set_state(AdminXuiInbound.waiting_protocol)
        await safe_edit(call, db.get_text('handlers_admin.auto_bad5c3ac', 'پروتکل inbound جدید را انتخاب کن:'), reply_markup=kb.xui_inbound_protocol_kb(server_id))
        await call.answer()

    @router.callback_query(AdminXuiInbound.waiting_protocol, F.data.startswith("adm_xui_inb_proto:"))
    async def cb_admin_xui_inbound_proto(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await state.update_data(xui_protocol=call.data.split(":", 1)[1])
        await state.set_state(AdminXuiInbound.waiting_network)
        await safe_edit(call, db.get_text('handlers_admin.auto_56bbbdbe', 'نوع شبکه (transport) را انتخاب کن:'), reply_markup=kb.xui_inbound_network_kb(data["xui_server_id"]))
        await call.answer()

    @router.callback_query(AdminXuiInbound.waiting_network, F.data.startswith("adm_xui_inb_net:"))
    async def cb_admin_xui_inbound_net(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await state.update_data(xui_network=call.data.split(":", 1)[1])
        await state.set_state(AdminXuiInbound.waiting_tls)
        await safe_edit(call, db.get_text('handlers_admin.auto_70e0791d', 'امنیت لایه انتقال:'), reply_markup=kb.xui_inbound_tls_kb(data["xui_server_id"]))
        await call.answer()

    @router.callback_query(AdminXuiInbound.waiting_tls, F.data.startswith("adm_xui_inb_tls:"))
    async def cb_admin_xui_inbound_tls(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await state.update_data(xui_tls=call.data.split(":", 1)[1] == "1")
        await state.set_state(AdminXuiInbound.waiting_port)
        await safe_edit(
            call,
            db.get_text('handlers_admin.auto_9a193df1', 'شماره پورت را بفرست (۱ تا ۶۵۵۳۵).\n۰ = انتخاب تصادفی'),
            reply_markup=kb.admin_back_kb(f"adm_panel_server_view:{data['xui_server_id']}"),
        )
        await call.answer()

    @router.message(AdminXuiInbound.waiting_port)
    async def process_admin_xui_inbound_port(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) > 65535:
            await message.answer(db.get_text('handlers_admin.auto_0bfcdb13', '⚠️ یک عدد بین ۰ تا ۶۵۵۳۵ بفرست.'))
            return
        data = await state.get_data()
        server_id = data.get("xui_server_id")
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        await state.clear()
        if not server:
            await message.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'))
            return
        port = int(text) or None
        try:
            result = await get_provider(server).create_inbound(data.get("xui_protocol"), data.get("xui_network"), port, None, bool(data.get("xui_tls")))
        except PanelError as e:
            await message.answer(f"⛔️ {e}", reply_markup=kb.panel_server_view_kb(server))
            return
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "xui_inbound_create", f"سرور #{server_id} | {result['protocol']}/{result['network']} | پورت {result['port']}")
        await message.answer(
            tr(f"✅ Inbound ساخته شد.\nشناسه: {result['id']}\nنام: {result['remark']}\nپروتکل: {result['protocol']}\nشبکه: {result['network']}\nپورت: {result['port']}"),
            reply_markup=kb.panel_server_view_kb(server),
        )

    @router.callback_query(F.data.startswith("adm_panel_server_transfer:"))
    async def cb_admin_panel_server_transfer(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_transfer")
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminPanelServerTransfer.waiting_price)
        current = int(server["transfer_price"] or 0)
        await safe_edit(call,
            f"💰 هزینه انتقال به «{server['name']}»\n\n"
            f"مقدار فعلی: {current:,} تومان\n"
            "قیمت جدید را به تومان بفرست. ۰ یعنی رایگان.",
            reply_markup=kb.admin_back_kb(f"adm_panel_server_view:{server_id}"),
        )
        await call.answer()

    @router.message(AdminPanelServerTransfer.waiting_price)
    async def process_admin_panel_server_transfer_price(message: Message, state: FSMContext):
        text = (message.text or "").strip().replace(",", "")
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_a68e42e1', 'لطفاً فقط عدد نامنفی وارد کن.'))
            return
        price = int(text)
        if price > 10_000_000_000:
            await message.answer(db.get_text('handlers_admin.auto_e782078a', 'حداکثر مبلغ ۱۰ میلیارد تومان است.'))
            return
        data = await state.get_data()
        server_id = data.get("panel_server_id")
        await asyncio.to_thread(db.update_panel_server, server_id, transfer_price=price)
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_transfer_price", f"سرور #{server_id} ← {price}")
        await state.clear()
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        await message.answer(db.get_text('handlers_admin.auto_0ac5d13f', '✅ هزینه انتقال ذخیره شد.'), reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_panel_server_transfer_target:"))
    async def cb_admin_panel_server_transfer_target(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_transfer_target")
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        new_val = 0 if server["allow_transfer_target"] else 1
        await asyncio.to_thread(db.update_panel_server, server_id, allow_transfer_target=new_val)
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "panel_transfer_target_toggle", f"سرور #{server_id} ← {new_val}")
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        await safe_edit(call, f"🖥 {server['name']}\nتنظیمات انتقال لوکیشن به‌روزرسانی شد.", reply_markup=kb.panel_server_view_kb(server))
        await call.answer(db.get_text('handlers_admin.auto_d417a83d', 'تنظیم مقصد انتقال تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_panel_server_template:"))
    async def cb_admin_panel_server_template(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_template")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminSetPanelTemplate.waiting_username)
        await safe_edit(
            call,
            TEMPLATE_PROMPTS.get(server["panel_type"]) or "نام کاربری نمونه‌ی جدید (که روی پنل موجود است) را بفرست:",
            reply_markup=kb.admin_back_kb(f"adm_panel_server_view:{server_id}"),
        )
        await call.answer()

    @router.message(AdminSetPanelTemplate.waiting_username)
    async def process_panel_server_template_update(message: Message, state: FSMContext):
        data = await state.get_data()
        server = (await asyncio.to_thread(db.get_panel_server, data["panel_server_id"]))
        if not server:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'))
            return
        await message.answer(db.get_text('handlers_admin.auto_850d2134', '⏳ در حال دریافت قالب از پنل...'))
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
        await message.answer(db.get_text('handlers_admin.auto_eb591f9c', '✅ قالب جدید ذخیره شد.'), reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_panel_server_suburl:"))
    async def cb_admin_panel_server_suburl(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_suburl")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminSetPanelSubUrl.waiting_url)
        current = server["xui_sub_base_url"] or "—"
        await safe_edit(
            call,
            f"آدرس فعلی Subscription:\n{current}\n\n"
            "آدرس جدید Subscription پنل را بفرست (همان چیزی که پنل موقع ساخت کاربر دستی نشانت می‌دهد، "
            "مثلاً https://domain:2096/sub یا https://domain/sub - بدون / انتهایی):",
            reply_markup=kb.admin_back_kb(f"adm_panel_server_view:{server_id}"),
        )
        await call.answer()

    @router.message(AdminSetPanelSubUrl.waiting_url)
    async def process_panel_server_suburl_update(message: Message, state: FSMContext):
        url = message.text.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            await message.answer(db.get_text('handlers_admin.auto_df2458e0', 'آدرس باید با http:// یا https:// شروع شود.'))
            return
        data = await state.get_data()
        server = (await asyncio.to_thread(db.get_panel_server, data["panel_server_id"]))
        if not server:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'))
            return
        (await asyncio.to_thread(db.update_panel_server, server["id"], xui_sub_base_url=url))
        await state.clear()
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_suburl_update", f"سرور #{server['id']} ← {url}"))
        server = (await asyncio.to_thread(db.get_panel_server, server["id"]))
        await message.answer(db.get_text('handlers_admin.auto_f956be7e', '✅ آدرس Subscription جدید ذخیره شد.'), reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_panel_server_socks:"))
    async def cb_admin_panel_server_socks(call: CallbackQuery, state: FSMContext):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_socks")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        await state.update_data(panel_server_id=server_id)
        await state.set_state(AdminSetPanelSocksProxy.waiting_url)
        current = server["socks_proxy"] or "خاموش"
        await safe_edit(
            call,
            f"پروکسی ساکس فعلی این پنل:\n{current}\n\n"
            "اگر این پنل مستقیم از سرور بات قابل‌اتصال نیست (مثلاً پنل داخل ایران است)، "
            "آدرس پروکسی SOCKS5 را به این شکل بفرست:\n"
            "socks5://user:pass@host:port یا socks5://host:port (بدون یوزر/پس)\n\n"
            "برای خاموش کردن پروکسی و اتصال مستقیم، کلمه‌ی «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb(f"adm_panel_server_view:{server_id}"),
        )
        await call.answer()

    @router.message(AdminSetPanelSocksProxy.waiting_url)
    async def process_panel_server_socks_update(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        data = await state.get_data()
        server = (await asyncio.to_thread(db.get_panel_server, data["panel_server_id"]))
        if not server:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'))
            return
        if text in ("حذف", "-", "خاموش"):
            value = ""
            log_note = "خاموش شد"
        else:
            if not text.startswith("socks5://") and not text.startswith("socks4://"):
                await message.answer(db.get_text('handlers_admin.auto_fa438aa5', 'آدرس باید با socks5:// یا socks4:// شروع شود، یا کلمه\u200cی «حذف» را بفرست.'))
                return
            value = text
            log_note = text
        (await asyncio.to_thread(db.update_panel_server, server["id"], socks_proxy=value))
        await state.clear()
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "panel_server_socks_update", f"سرور #{server['id']} ← {log_note}"))
        server = (await asyncio.to_thread(db.get_panel_server, server["id"]))
        await message.answer(db.get_text('handlers_admin.auto_4d465db8', '✅ تنظیمات پروکسی ساکس ذخیره شد.'), reply_markup=kb.panel_server_view_kb(server))

    @router.callback_query(F.data.startswith("adm_panel_server_test:"))
    async def cb_admin_panel_server_test(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_test")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        await call.answer(db.get_text('handlers_admin.auto_e6010cfe', 'در حال تست اتصال...'))
        try:
            ok, error = await get_provider(server).check_connection()
        except PanelError as e:
            ok, error = False, str(e)
        if ok:
            await call.message.answer(db.get_text('handlers_admin.auto_87a33db4', '✅ اتصال به پنل موفق بود.'))
        else:
            await call.message.answer(tr(f"❌ اتصال به پنل ناموفق بود.\n\nعلت: <code>{html.escape(error)}</code>"))

    @router.callback_query(F.data.startswith("adm_panel_server_usage:"))
    async def cb_admin_panel_server_usage_toggle(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, kind, server_id_str = call.data.split(":")
        server_id = int(server_id_str)
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        field = {"custom": "used_for_custom_config", "test": "used_for_test_config", "reseller": "used_for_reseller"}.get(kind)
        if not field:
            await call.answer(db.get_text('handlers_admin.auto_87a93951', 'نوع نامعتبر.'), show_alert=True)
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
        await call.answer(db.get_text('handlers_admin.auto_1478966c', 'تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_panel_server_onhold:"))
    async def cb_admin_panel_server_onhold(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_onhold")
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server:
            return await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
        supported = {"marzban", "pasarguard", "rebecca", "marzneshin", "3xui", "threexui"}
        if server["panel_type"] not in supported:
            return await call.answer(db.get_text('handlers_admin.auto_5f22862a', 'این نوع پنل از On-hold پشتیبانی نمی\u200cکند.'), show_alert=True)
        new_val = 0 if server["start_on_first_use"] else 1
        await asyncio.to_thread(db.update_panel_server, server_id, start_on_first_use=new_val)
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "panel_server_onhold_toggle", f"سرور #{server_id} ← {new_val}")
        await safe_edit(call,
            f"🖥 {server['name']}\nنوع: {PANEL_TYPE_LABELS.get(server['panel_type'], server['panel_type'])}\n"
            f"انقضا از اولین اتصال: {'🟢 فعال' if server['start_on_first_use'] else '⚪️ خاموش'}\n"
            f"{panel_server_readiness_text(server)}",
            reply_markup=kb.panel_server_view_kb(server),
        )
        await call.answer(db.get_text('handlers_admin.auto_c38fa61b', 'تنظیم On-hold تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_panel_server_toggle:"))
    async def cb_admin_panel_server_toggle(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_toggle")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        (await asyncio.to_thread(db.update_panel_server, server_id, is_active=0 if server["is_active"] else 1))
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        await safe_edit(call,
            f"🖥 {server['name']}\nنوع: {PANEL_TYPE_LABELS.get(server['panel_type'], server['panel_type'])}\nآدرس: {server['api_url']}\n"
            f"وضعیت: {'🟢 فعال' if server['is_active'] else '🔴 غیرفعال'}",
            reply_markup=kb.panel_server_view_kb(server),
        )
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_panel_server_delete:"))
    async def cb_admin_panel_server_delete(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_delete")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
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
        await call.answer(db.get_text('handlers_admin.auto_c65370fc', 'سرور حذف شد.'))

    @router.callback_query(F.data.startswith("adm_panel_server_delete_force:"))
    async def cb_admin_panel_server_delete_force(call: CallbackQuery):
        if not full_access_bot:
            return await deny_reseller_panel_access(call)
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        server_id = callback_id(call.data, "adm_panel_server_delete_force")
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'سرور یافت نشد.'), show_alert=True)
            return
        removed = (await asyncio.to_thread(db.delete_panel_server, server_id, force=True))
        (await asyncio.to_thread(db.log_admin_action, 
            call.from_user.id, "panel_server_delete",
            f"سرور #{server_id} ({server['name']}) + {removed} کانفیگ شخصی مرتبط",
        ))
        await replace_admin_view(call, "🖥 سرورهای پنل VPN متصل:", reply_markup=kb.panel_servers_list_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_736eb2b9', 'سرور و کانفیگ\u200cهای مرتبط حذف شدند.'))

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
        await safe_edit(call, db.get_text('handlers_admin.auto_97dae02d', 'ابتدای این بازه چند گیگابایت باشد؟ (فقط عدد):'), reply_markup=kb.admin_back_kb("adm_pricing_tiers"))
        await call.answer()

    @router.message(AdminAddPricingTier.waiting_from_gb)
    async def process_pricing_tier_from(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        await state.update_data(from_gb=int(text))
        await state.set_state(AdminAddPricingTier.waiting_to_gb)
        await message.answer(
            db.get_text('handlers_admin.auto_4907c3db', 'انتهای این بازه چند گیگابایت باشد؟ (فقط عدد)\nاگر می\u200cخواهی این آخرین بازه باشد (بدون سقف/تا بی\u200cنهایت)، عدد 0 بفرست.')
        )

    @router.message(AdminAddPricingTier.waiting_to_gb)
    async def process_pricing_tier_to(message: Message, state: FSMContext):
        text = message.text.strip()
        data = await state.get_data()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_321920b0', 'لطفاً فقط عدد صحیح ارسال کن (یا 0 برای بی\u200cنهایت).'))
            return
        to_gb = None if int(text) == 0 else int(text)
        if to_gb is not None and to_gb <= data["from_gb"]:
            await message.answer(tr(f"انتهای بازه باید بزرگ‌تر از ابتدای آن ({data['from_gb']}) باشد."))
            return
        await state.update_data(to_gb=to_gb)
        await state.set_state(AdminAddPricingTier.waiting_price)
        await message.answer(db.get_text('handlers_admin.auto_5d369599', 'قیمت هر گیگابایت در این بازه چند تومان باشد؟ (فقط عدد):'))

    @router.message(AdminAddPricingTier.waiting_price)
    async def process_pricing_tier_price(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
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
            tr(f"✅ بازه‌ی قیمت اضافه شد: {data['from_gb']} تا {to_label} گیگ ← {int(text):,} تومان/گیگ"),
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
        await call.answer(db.get_text('handlers_admin.auto_a2f65e87', 'بازه حذف شد.'))

    @router.callback_query(F.data == "adm_reset_test_configs")
    async def cb_admin_reset_test_configs(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminResetTestConfig.waiting_message)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_89c55bae', 'پیامی که می\u200cخوای به کاربرانی که قبلاً کانفیگ تست گرفته\u200cاند ارسال بشه رو بفرست.\n(مثلاً: «🎉 کانفیگ تست دوباره برای شما فعال شد، از منوی اصلی دریافت کنید.»)\n\nبعد از این پیام، بازنشانی و ارسال شروع می\u200cشود.'),
            reply_markup=kb.admin_back_kb("adm_test_menu"),
        )
        await call.answer()

    @router.message(AdminResetTestConfig.waiting_message)
    async def process_reset_test_configs_message(message: Message, state: FSMContext, bot: Bot):
        text = message.text.strip()
        if not text:
            await message.answer(db.get_text('handlers_admin.auto_b4ec3e0f', 'لطفاً یک متن معتبر ارسال کنید.'))
            return
        await state.clear()
        user_ids = (await asyncio.to_thread(db.reset_all_test_usage))
        (await asyncio.to_thread(db.log_admin_action, 
            message.from_user.id, "reset_test_configs",
            f"بازنشانی کانفیگ تست برای {len(user_ids)} کاربر",
        ))
        status_msg = await message.answer(tr(f"⏳ در حال ارسال پیام به {len(user_ids)} کاربر..."))
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
            tr(f"✅ کانفیگ تست برای {len(user_ids)} کاربر بازنشانی شد و پیام به {sent} نفر ارسال شد."),
            reply_markup=kb.admin_test_menu_kb(db, is_main_bot),
        )

    @router.callback_query(F.data == "adm_renewal_toggle")
    async def cb_admin_renewal_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "renewal_reminder_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "renewal_reminder_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_c6c308df', '🔔 یادآوری تمدید سرویس:'), reply_markup=kb.renewal_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_renewal_edit_days")
    async def cb_admin_renewal_edit_days(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalSettings.waiting_days_before)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_ee771493', 'چند روز قبل از اتمام سرویس، یادآوری ارسال شود؟ (فقط عدد، مثلاً 5):'),
            reply_markup=kb.admin_back_kb("adm_renewal_settings"),
        )
        await call.answer()

    @router.message(AdminRenewalSettings.waiting_days_before)
    async def process_renewal_days(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "renewal_reminder_days_before", text))
        await state.clear()
        await message.answer(
            tr(f"✅ یادآوری روی {text} روز قبل از اتمام سرویس تنظیم شد."), reply_markup=kb.renewal_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_renewal_edit_percent")
    async def cb_admin_renewal_edit_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalSettings.waiting_percent)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_1beb28d3', 'درصد تخفیف کد تشویقی تمدید چقدر باشد؟ (عددی بین 1 تا 100، مثلاً 20):'),
            reply_markup=kb.admin_back_kb("adm_renewal_settings"),
        )
        await call.answer()

    @router.message(AdminRenewalSettings.waiting_percent)
    async def process_renewal_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 < int(text) <= 100):
            await message.answer(db.get_text('handlers_admin.auto_c1129902', 'لطفاً یک عدد بین 1 تا 100 ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "renewal_discount_percent", text))
        await state.clear()
        await message.answer(tr(f"✅ درصد تخفیف کد تشویقی روی {text}٪ تنظیم شد."), reply_markup=kb.renewal_settings_kb(db))

    @router.callback_query(F.data == "adm_renewal_edit_hours")
    async def cb_admin_renewal_edit_hours(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminRenewalSettings.waiting_expiry_hours)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_bf4246a2', 'کد تخفیف تشویقی چند ساعت اعتبار داشته باشد؟ (فقط عدد، مثلاً 24):'),
            reply_markup=kb.admin_back_kb("adm_renewal_settings"),
        )
        await call.answer()

    @router.message(AdminRenewalSettings.waiting_expiry_hours)
    async def process_renewal_hours(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "renewal_discount_expiry_hours", text))
        await state.clear()
        await message.answer(
            tr(f"✅ اعتبار کد تخفیف تشویقی روی {text} ساعت تنظیم شد."), reply_markup=kb.renewal_settings_kb(db)
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
        await safe_edit(call, db.get_text('handlers_admin.auto_59a7e810', '📉 یادآوری اتمام حجم:'), reply_markup=kb.volume_reminder_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_volume_toggle_mode")
    async def cb_admin_volume_toggle_mode(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "volume_reminder_mode", "percent"))
        (await asyncio.to_thread(db.set_setting, "volume_reminder_mode", "gb" if current == "percent" else "percent"))
        await safe_edit(call, db.get_text('handlers_admin.auto_59a7e810', '📉 یادآوری اتمام حجم:'), reply_markup=kb.volume_reminder_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_00efe1e6', 'مبنای آستانه تغییر کرد.'))

    @router.callback_query(F.data == "adm_volume_edit_percent")
    async def cb_admin_volume_edit_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_percent)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_72f42b59', 'وقتی چند درصد از حجم مصرف شد، یادآوری ارسال شود؟ (عددی بین 1 تا 99، مثلاً 80):'),
            reply_markup=kb.admin_back_kb("adm_volume_reminder_settings"),
        )
        await call.answer()

    @router.message(AdminVolumeReminderSettings.waiting_percent)
    async def process_volume_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 < int(text) < 100):
            await message.answer(db.get_text('handlers_admin.auto_4aae0428', 'لطفاً یک عدد بین 1 تا 99 ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "volume_reminder_percent", text))
        await state.clear()
        await message.answer(
            tr(f"✅ آستانه‌ی یادآوری حجم روی {text}٪ مصرف تنظیم شد."), reply_markup=kb.volume_reminder_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_volume_edit_gb")
    async def cb_admin_volume_edit_gb(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_gb_left)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_bee10d35', 'وقتی چند گیگابایت حجم باقی\u200cمانده شد، یادآوری ارسال شود؟ (عدد، مثلاً 2 یا 1.5):'),
            reply_markup=kb.admin_back_kb("adm_volume_reminder_settings"),
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
            await message.answer(db.get_text('handlers_admin.auto_821f89c8', 'لطفاً یک عدد مثبت ارسال کنید (مثلاً 2 یا 1.5).'))
            return
        (await asyncio.to_thread(db.set_setting, "volume_reminder_gb_left", str(value)))
        await state.clear()
        await message.answer(
            tr(f"✅ آستانه‌ی یادآوری حجم روی {value} گیگ باقی‌مانده تنظیم شد."), reply_markup=kb.volume_reminder_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_volume_edit_discount_percent")
    async def cb_admin_volume_edit_discount_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_discount_percent)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_ff139b89', 'درصد تخفیف کد تشویقی اتمام حجم چقدر باشد؟ (عددی بین 1 تا 100، مثلاً 20):'),
            reply_markup=kb.admin_back_kb("adm_volume_reminder_settings"),
        )
        await call.answer()

    @router.message(AdminVolumeReminderSettings.waiting_discount_percent)
    async def process_volume_discount_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 < int(text) <= 100):
            await message.answer(db.get_text('handlers_admin.auto_c1129902', 'لطفاً یک عدد بین 1 تا 100 ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "volume_discount_percent", text))
        await state.clear()
        await message.answer(tr(f"✅ درصد تخفیف کد تشویقی روی {text}٪ تنظیم شد."), reply_markup=kb.volume_reminder_settings_kb(db))

    @router.callback_query(F.data == "adm_volume_edit_discount_hours")
    async def cb_admin_volume_edit_discount_hours(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminVolumeReminderSettings.waiting_discount_hours)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_ccd56fa6', 'کد تخفیف تشویقی اتمام حجم چند ساعت اعتبار داشته باشد؟ (فقط عدد، مثلاً 24):'),
            reply_markup=kb.admin_back_kb("adm_volume_reminder_settings"),
        )
        await call.answer()

    @router.message(AdminVolumeReminderSettings.waiting_discount_hours)
    async def process_volume_discount_hours(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "volume_discount_expiry_hours", text))
        await state.clear()
        await message.answer(
            tr(f"✅ اعتبار کد تخفیف تشویقی روی {text} ساعت تنظیم شد."), reply_markup=kb.volume_reminder_settings_kb(db)
        )

    # -------------------------------------------------------------------
    # هشدار اتصال / عدم‌اتصال به کانفیگ
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_connect_alert_settings")
    async def cb_admin_connect_alert_settings(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(
            call, "🔌 هشدار اتصال/عدم‌اتصال به کانفیگ:", reply_markup=kb.connect_alert_settings_kb(db)
        )
        await call.answer()

    @router.callback_query(F.data == "adm_connect_toggle")
    async def cb_admin_connect_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "connect_alert_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "connect_alert_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_b89fec14', '🔌 هشدار اتصال/عدم\u200cاتصال به کانفیگ:'), reply_markup=kb.connect_alert_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_no_connect_toggle")
    async def cb_admin_no_connect_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "no_connect_alert_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "no_connect_alert_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_b89fec14', '🔌 هشدار اتصال/عدم\u200cاتصال به کانفیگ:'), reply_markup=kb.connect_alert_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_connect_edit_threshold")
    async def cb_admin_connect_edit_threshold(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminConnectAlertSettings.waiting_connect_threshold)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_0d1491bd', 'از چند مگابایت مصرف به بعد، کاربر «متصل» در نظر گرفته شود؟ (عدد، مثلاً 1):'),
            reply_markup=kb.admin_back_kb("adm_connect_alert_settings"),
        )
        await call.answer()

    @router.message(AdminConnectAlertSettings.waiting_connect_threshold)
    async def process_connect_threshold(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", ".")
        try:
            value = float(text)
            if value <= 0:
                raise ValueError
        except ValueError:
            await message.answer(db.get_text('handlers_admin.auto_96270c53', 'لطفاً یک عدد مثبت ارسال کنید (مثلاً 1 یا 0.5).'))
            return
        (await asyncio.to_thread(db.set_setting, "connect_alert_threshold_mb", str(value)))
        await state.clear()
        await message.answer(
            tr(f"✅ آستانه‌ی هشدار اتصال روی {value:g} مگابایت تنظیم شد."), reply_markup=kb.connect_alert_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_connect_edit_text")
    async def cb_admin_connect_edit_text(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminConnectAlertSettings.waiting_connect_text)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_aa129ae0', 'متن پیام هشدار اتصال را بفرستید.\nمی\u200cتوانید از {used_gb} (حجم مصرف\u200cشده به گیگابایت) استفاده کنید.\n\nمثال: «✅ سرویس شما فعال شد و تا الان {used_gb} گیگ مصرف کرده\u200cاید.»'),
            reply_markup=kb.admin_back_kb("adm_connect_alert_settings"),
        )
        await call.answer()

    @router.message(AdminConnectAlertSettings.waiting_connect_text)
    async def process_connect_text(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer(db.get_text('handlers_admin.auto_b4ec3e0f', 'لطفاً یک متن معتبر ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "connect_alert_text", text))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_5f9ee2de', '✅ متن هشدار اتصال ذخیره شد.'), reply_markup=kb.connect_alert_settings_kb(db))

    @router.callback_query(F.data == "adm_no_connect_edit_hours")
    async def cb_admin_no_connect_edit_hours(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminConnectAlertSettings.waiting_no_connect_hours)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_6fabb738', 'چند ساعت بعد از فعال\u200cسازی سرویس، اگر کاربر متصل نشده بود هشدار ارسال شود؟ (فقط عدد، مثلاً 24):'),
            reply_markup=kb.admin_back_kb("adm_connect_alert_settings"),
        )
        await call.answer()

    @router.message(AdminConnectAlertSettings.waiting_no_connect_hours)
    async def process_no_connect_hours(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "no_connect_alert_hours", text))
        await state.clear()
        await message.answer(
            tr(f"✅ مهلت هشدار عدم‌اتصال روی {text} ساعت تنظیم شد."), reply_markup=kb.connect_alert_settings_kb(db)
        )

    @router.callback_query(F.data == "adm_no_connect_edit_threshold")
    async def cb_admin_no_connect_edit_threshold(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminConnectAlertSettings.waiting_no_connect_threshold)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_a4fae6d6', 'زیر چند مگابایت مصرف، کاربر «متصل نشده» در نظر گرفته شود؟ (عدد، مثلاً 1):'),
            reply_markup=kb.admin_back_kb("adm_connect_alert_settings"),
        )
        await call.answer()

    @router.message(AdminConnectAlertSettings.waiting_no_connect_threshold)
    async def process_no_connect_threshold(message: Message, state: FSMContext):
        text = message.text.strip().replace(",", ".")
        try:
            value = float(text)
            if value <= 0:
                raise ValueError
        except ValueError:
            await message.answer(db.get_text('handlers_admin.auto_96270c53', 'لطفاً یک عدد مثبت ارسال کنید (مثلاً 1 یا 0.5).'))
            return
        (await asyncio.to_thread(db.set_setting, "no_connect_alert_threshold_mb", str(value)))
        await state.clear()
        await message.answer(
            tr(f"✅ آستانه‌ی هشدار عدم‌اتصال روی {value:g} مگابایت تنظیم شد."),
            reply_markup=kb.connect_alert_settings_kb(db),
        )

    @router.callback_query(F.data == "adm_no_connect_edit_text")
    async def cb_admin_no_connect_edit_text(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminConnectAlertSettings.waiting_no_connect_text)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_d72963a5', 'متن پیام هشدار عدم\u200cاتصال را بفرستید.\nمی\u200cتوانید از {used_gb} (حجم مصرف\u200cشده به گیگابایت) استفاده کنید.\n\nمثال: «⚠️ هنوز به سرویس\u200cتان متصل نشده\u200cاید، برای راهنما با پشتیبانی در تماس باشید.»'),
            reply_markup=kb.admin_back_kb("adm_connect_alert_settings"),
        )
        await call.answer()

    @router.message(AdminConnectAlertSettings.waiting_no_connect_text)
    async def process_no_connect_text(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer(db.get_text('handlers_admin.auto_b4ec3e0f', 'لطفاً یک متن معتبر ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "no_connect_alert_text", text))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_22021a3d', '✅ متن هشدار عدم\u200cاتصال ذخیره شد.'), reply_markup=kb.connect_alert_settings_kb(db))

    # -------------------------------------------------------------------
    # تخفیف تمدید کامل زودهنگام
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_early_renewal_discount")
    async def cb_admin_early_renewal_discount(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(
            call, "🎁 تخفیف تمدید کامل زودهنگام:", reply_markup=kb.early_renewal_discount_kb(db)
        )
        await call.answer()

    @router.callback_query(F.data == "adm_early_renewal_toggle")
    async def cb_admin_early_renewal_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        current = (await asyncio.to_thread(db.get_setting, "early_renewal_discount_enabled", "0"))
        (await asyncio.to_thread(db.set_setting, "early_renewal_discount_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_928db0ab', '🎁 تخفیف تمدید کامل زودهنگام:'), reply_markup=kb.early_renewal_discount_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_early_renewal_edit_days")
    async def cb_admin_early_renewal_edit_days(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminEarlyRenewalDiscount.waiting_days)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_716603fb', 'اگر تا انقضای سرویس حداکثر چند روز مانده باشد، تمدید کامل شامل تخفیف شود؟ (فقط عدد، مثلاً 5):'),
            reply_markup=kb.admin_back_kb("adm_early_renewal_discount"),
        )
        await call.answer()

    @router.message(AdminEarlyRenewalDiscount.waiting_days)
    async def process_early_renewal_days(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_da77c1e0', 'لطفاً یک عدد صحیح مثبت ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "early_renewal_discount_days", text))
        await state.clear()
        await message.answer(
            tr(f"✅ آستانه روی {text} روز قبل از انقضا تنظیم شد."), reply_markup=kb.early_renewal_discount_kb(db)
        )

    @router.callback_query(F.data == "adm_early_renewal_edit_percent")
    async def cb_admin_early_renewal_edit_percent(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminEarlyRenewalDiscount.waiting_percent)
        await safe_edit(call,
            db.get_text('handlers_admin.auto_2bb63ecb', 'چند درصد تخفیف روی قیمت تمدید کامل اعمال شود؟ (عددی بین 1 تا 100، مثلاً 10):'),
            reply_markup=kb.admin_back_kb("adm_early_renewal_discount"),
        )
        await call.answer()

    @router.message(AdminEarlyRenewalDiscount.waiting_percent)
    async def process_early_renewal_percent(message: Message, state: FSMContext):
        text = message.text.strip()
        if not text.isdigit() or not (0 < int(text) <= 100):
            await message.answer(db.get_text('handlers_admin.auto_c1129902', 'لطفاً یک عدد بین 1 تا 100 ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "early_renewal_discount_percent", text))
        await state.clear()
        await message.answer(
            tr(f"✅ درصد تخفیف روی {text}٪ تنظیم شد."), reply_markup=kb.early_renewal_discount_kb(db)
        )

    # -------------------------------------------------------------------
    # هزینه و انقضای عضویت نمایندگی (F13)
    # -------------------------------------------------------------------
    if is_main_bot:

        @router.callback_query(F.data == "adm_reseller_membership")
        async def cb_admin_reseller_membership(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            tiers = await asyncio.to_thread(db.list_reseller_tiers, False)
            await replace_admin_view(
                call,
                "⏳ <b>هزینه و انقضای نمایندگی</b>\n\n"
                "هزینه از کیف پول اعتباری کاربر در زمان تایید/تمدید کسر می‌شود. "
                "مدت ۰ یا خالی یعنی دائمی. سقف اعتبار پس‌پرداخت (تومان) سقف پیش‌فرض همه‌ی نماینده‌های این سطح است؛ ۰ یعنی بدون اعتبار.",
                reply_markup=kb.reseller_membership_tiers_kb(tiers),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("adm_rmem_edit:"))
        async def cb_admin_reseller_membership_edit(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            code = call.data.split(":", 1)[1]
            tier = await asyncio.to_thread(db.get_reseller_tier, code)
            if not tier:
                return await call.answer(db.get_text('handlers_admin.auto_79fc2c00', 'سطح یافت نشد.'), show_alert=True)
            await state.update_data(reseller_membership_tier=code)
            await state.set_state(AdminResellerMembership.waiting_fee_duration)
            fee = int(tier["membership_fee_toman"] or 0)
            days = tier["duration_days"] or 0
            cap = int(tier["credit_limit_toman"] or 0)
            await call.message.answer(
                tr(f"⚙️ {tier['icon']} {tier['title']}\n\n"
                f"مقدار فعلی: {fee:,} تومان / {days} روز / سقف اعتبار {cap:,} تومان\n\n"
                "فرمت جدید را بفرستید: <code>هزینه روز سقف_اعتبار</code>\n"
                "مثال: <code>250000 30 5000000</code>\n"
                "سقف اعتبار اختیاری است؛ اگر ننویسید تغییر نمی‌کند و ۰ یعنی بدون اعتبار پس‌پرداخت.\n"
                "برای عضویت دائمی: روز را <code>0</code> بزنید.")
            )
            await call.answer()

        @router.message(AdminResellerMembership.waiting_fee_duration)
        async def msg_admin_reseller_membership(message: Message, state: FSMContext):
            if not senior_admin_only(message.from_user.id):
                return
            parts = (message.text or "").replace(",", "").split()
            if len(parts) not in (2, 3):
                await message.answer(db.get_text('handlers_admin.auto_e23506a0', 'فرمت صحیح: <code>هزینه روز سقف_اعتبار</code>؛ مثال <code>250000 30 5000000</code>'))
                return
            try:
                fee, days = int(parts[0]), int(parts[1])
                cap = int(parts[2]) if len(parts) == 3 else None
                if fee < 0 or days < 0 or fee > 10_000_000_000 or days > 3650:
                    raise ValueError
                if cap is not None and not 0 <= cap <= 10_000_000_000:
                    raise ValueError
            except ValueError:
                await message.answer(db.get_text('handlers_admin.auto_53f45482', 'هزینه و سقف اعتبار باید ۰ تا ۱۰ میلیارد و مدت باید ۰ تا ۳۶۵۰ روز باشد.'))
                return
            data = await state.get_data()
            code = data.get("reseller_membership_tier")
            fields = {"membership_fee_toman": fee, "duration_days": (days or None)}
            if cap is not None:
                fields["credit_limit_toman"] = cap
            ok = await asyncio.to_thread(db.update_reseller_tier, code, **fields)
            await state.clear()
            if not ok:
                await message.answer(db.get_text('handlers_admin.auto_0e500602', '❌ سطح نمایندگی پیدا نشد.'))
                return
            tier = await asyncio.to_thread(db.get_reseller_tier, code)
            cap_now = int(tier["credit_limit_toman"] or 0)
            await asyncio.to_thread(db.log_admin_action, message.from_user.id, "reseller_membership_update", f"سطح {code} | هزینه {fee} | مدت {days} | سقف اعتبار {cap_now}")
            await message.answer(tr(f"✅ تنظیم شد: {tier['icon']} {tier['title']} — {fee:,} تومان / {'دائمی' if not days else f'{days} روز'} / سقف اعتبار {cap_now:,} تومان"))

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
                await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
                return
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
            if not reseller_bot:
                return await call.answer(db.get_text('handlers_admin.auto_edca6d43', 'یافت نشد.'), show_alert=True)

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
            await safe_edit(call, db.get_text('handlers_admin.auto_439eb43d', '🏪 مدیریت بات\u200cهای نمایندگی:'), reply_markup=kb.resellers_kb(bots))
            await call.answer(db.get_text('handlers_admin.auto_5706b1e3', 'وضعیت تغییر کرد و اعمال شد.'))

        @router.callback_query(F.data.startswith("adm_resbot_webpanel:"))
        async def cb_admin_resbot_webpanel(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_webpanel")
            if bot_id is None:
                await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
                return
            reseller_bot = (await asyncio.to_thread(db.get_reseller_bot, bot_id))
            if not reseller_bot:
                return await call.answer(db.get_text('handlers_admin.auto_edca6d43', 'یافت نشد.'), show_alert=True)

            # پنل وب برای نمایندگی نیز مجاز است؛ tenant پنل همان سطح
            # دسترسی محدود نماینده را اعمال می‌کند.
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
            await call.answer(db.get_text('handlers_admin.auto_a137ef33', 'پنل وب فعال شد.'))

            if not _get_admin_panel_url(db):
                await state.set_state(AdminSetPanelDomain.waiting_url)
                await state.update_data(pending_webpanel_bot_id=bot_id)
                await call.message.answer(
                    db.get_text('handlers_admin.auto_25bfa75f', '🌐 پنل وب این نماینده فعال شد، ولی هنوز آدرس پنل مدیریت وب رو بهم نگفتی.\n\nفقط همین یک\u200cبار، آدرس دامنه\u200cی پنل مدیریتت رو بفرست (با https://)، مثلاً:\nhttps://panel.example.com\n\nبعدش خودم لینک راه\u200cاندازی رو می\u200cسازم و مستقیم برای نماینده می\u200cفرستم؛ دیگه لازم نیست هیچ\u200cجا دستی چیزی تنظیم کنی.')
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
                return await call.answer(db.get_text('handlers_admin.auto_edca6d43', 'یافت نشد.'), show_alert=True)

            panel_url = _get_admin_panel_url(db)
            if not panel_url:
                return await call.answer(db.get_text('handlers_admin.auto_0137f0c0', 'هنوز آدرس پنل مدیریت وب تنظیم نشده.'), show_alert=True)

            b_value = reseller_bot["link_slug"] or str(bot_id)
            login_link = f"{panel_url}/?b={b_value}"

            await call.message.answer(
                tr("🔗 لینک ثابت ورود پنل وب این نماینده:\n\n"
                f"{login_link}\n\n"
                "این لینک (بر خلاف لینک راه‌اندازی) چندبارمصرف است؛ نماینده هر بار با همین لینک "
                "و یوزرنیم/پسوردی که خودش موقع راه‌اندازی ساخته وارد پنلش می‌شود. بهتر است "
                "نماینده این لینک را بوکمارک کند."),
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
                return await call.answer(db.get_text('handlers_admin.auto_edca6d43', 'یافت نشد.'), show_alert=True)

            (await asyncio.to_thread(db.regenerate_reseller_web_panel_token, bot_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "reseller_webpanel_regen", f"نماینده #{bot_id}"))
            await call.answer(db.get_text('handlers_admin.auto_20bdb71a', 'توکن جدید ساخته شد.'))

            if not _get_admin_panel_url(db):
                await state.set_state(AdminSetPanelDomain.waiting_url)
                await state.update_data(pending_webpanel_bot_id=bot_id)
                await call.message.answer(
                    db.get_text('handlers_admin.auto_ab3aa88f', '🔁 توکن راه\u200cاندازی جدید ساخته شد، ولی هنوز آدرس پنل مدیریت وب رو بهم نگفتی.\n\nآدرس دامنه\u200cی پنل مدیریتت رو بفرست (با https://)، بعدش خودم لینک رو می\u200cسازم و می\u200cفرستم:')
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
                return await call.answer(db.get_text('handlers_admin.auto_edca6d43', 'یافت نشد.'), show_alert=True)

            (await asyncio.to_thread(db.disable_reseller_web_panel, bot_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "reseller_webpanel_disable", f"نماینده #{bot_id}"))
            bots = (await asyncio.to_thread(db.list_reseller_bots))
            await safe_edit(call, db.get_text('handlers_admin.auto_b842641a', '⛔️ پنل وب این نماینده غیرفعال شد (نشست\u200cهای فعلی هم دیگر کار نمی\u200cکنند).\n\n🏪 مدیریت بات\u200cهای نمایندگی:'), reply_markup=kb.resellers_kb(bots))
            await call.answer(db.get_text('handlers_admin.auto_f2d4c165', 'غیرفعال شد.'))

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
                await message.answer(db.get_text('handlers_admin.auto_08f085e6', 'آدرس باید با http:// یا https:// شروع بشه. دوباره بفرست:'))
                return

            (await asyncio.to_thread(db.set_setting, "admin_panel_url", url))
            data = await state.get_data()
            pending_bot_id = data.get("pending_webpanel_bot_id")
            await state.clear()
            await message.answer(tr(f"✅ آدرس پنل مدیریت ذخیره شد: {url}\nهر وقت بخوای می‌تونی از همین‌جا («⚙️ آدرس پنل مدیریت») عوضش کنی."))

            if pending_bot_id:
                await _deliver_webpanel_link(db, message, message.from_user.id, pending_bot_id)

        @router.callback_query(F.data.startswith("adm_resbot_del:"))
        async def cb_admin_resbot_del(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            bot_id = callback_id(call.data, "adm_resbot_del")
            if bot_id is None:
                await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
                return
            await safe_edit(call,
                db.get_text('handlers_admin.auto_f1c95c1a', '⚠️ آیا از حذف این بات نمایندگی مطمئنی؟\n\nدیتابیس آن (شامل کاربران، کیف پول، کانفیگ\u200cها) پاک شود یا فقط برای احتیاط نگه داشته شود؟'),
                reply_markup=kb.resbot_del_confirm_kb(bot_id),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("adm_resbot_delc:"))
        async def cb_admin_resbot_del_confirm(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            parts = call.data.split(":")
            if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("0", "1"):
                await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_5e72f8ba', 'بات نمایندگی حذف شد.'))

        @router.callback_query(F.data == "adm_reseller_orphans")
        async def cb_admin_reseller_orphans(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            orphans = (await asyncio.to_thread(db.list_orphaned_reseller_users))
            if not orphans:
                await call.answer(db.get_text('handlers_admin.auto_207376b1', 'موردی پیدا نشد؛ هیچ داده\u200cی باقی\u200cمانده\u200cای وجود ندارد.'), show_alert=True)
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
                await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
                return
            (await asyncio.to_thread(db.purge_reseller_leftovers, target_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "reseller_orphan_purge", f"کاربر {target_id}"))
            orphans = (await asyncio.to_thread(db.list_orphaned_reseller_users))
            if orphans:
                await safe_edit(
                    call,
                    db.get_text('handlers_admin.auto_3fc7d26f', '🧹 داده\u200cهای باقی\u200cمانده\u200cی نمایندگی\n\n✅ کاربر پاکسازی شد.'),
                    reply_markup=kb.reseller_orphans_kb(orphans),
                )
            else:
                await safe_edit(
                    call,
                    db.get_text('handlers_admin.auto_c79f970a', '🧹 داده\u200cهای باقی\u200cمانده\u200cی نمایندگی\n\n✅ کاربر پاکسازی شد. دیگر موردی باقی نمانده.'),
                    reply_markup=kb.admin_back_kb("adm_resellers_menu"),
                )
            await call.answer(db.get_text('handlers_admin.auto_ce5f555e', 'پاکسازی شد.'))

        @router.callback_query(F.data == "adm_orphan_db_files")
        async def cb_admin_orphan_db_files(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            orphan_files = _find_orphan_reseller_db_files()
            if not orphan_files:
                await call.answer(db.get_text('handlers_admin.auto_0537964c', 'فایل دیتابیس یتیمی روی دیسک پیدا نشد.'), show_alert=True)
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
                await call.answer(db.get_text('handlers_admin.auto_e2845473', '❌ نام فایل نامعتبر است.'), show_alert=True)
                return

            target_path = os.path.join(RESELLER_DBS_DIR, fname)
            still_orphan = fname in _find_orphan_reseller_db_files()
            if not still_orphan or not os.path.exists(target_path):
                await call.answer(db.get_text('handlers_admin.auto_f49bcad6', 'این فایل دیگر یتیم نیست یا وجود ندارد.'), show_alert=True)
            else:
                try:
                    os.remove(target_path)
                    (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "orphan_db_file_delete", fname))
                except OSError:
                    logger.exception("پاک‌کردن فایل دیتابیس یتیم ناموفق بود: %s", target_path)
                    await call.answer(db.get_text('handlers_admin.auto_2441943f', '❌ حذف فایل با خطا مواجه شد.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_9f47ea77', 'فایل حذف شد.'))

        @router.callback_query(F.data == "adm_resbot_add")
        async def cb_admin_resbot_add(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            await state.set_state(AdminAddResellerBot.waiting_token)
            await safe_edit(call, 
                db.get_text('handlers_admin.auto_3608396c', 'توکن بات نماینده را ارسال کنید (همانی که از @BotFather گرفته):'),
                reply_markup=kb.admin_back_kb("adm_resellers_menu"),
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
                await message.answer(db.get_text('handlers_admin.auto_9cb8c716', '⛔️ این توکن قبلاً ثبت شده است.'))
                return

            await message.answer(db.get_text('handlers_admin.auto_869325bd', '⏳ در حال بررسی اعتبار توکن...'))
            temp_bot = Bot(token=token)
            try:
                me = await temp_bot.get_me()
            except Exception:
                await message.answer(db.get_text('handlers_admin.auto_02a005f3', '❌ این توکن معتبر نیست. دوباره بررسی و ارسال کنید:'))
                await temp_bot.session.close()
                return
            await temp_bot.session.close()

            await state.update_data(resbot_token=token, resbot_username=me.username)
            await state.set_state(AdminAddResellerBot.waiting_owner_id)
            await message.answer(
                tr(f"✅ توکن معتبر است: @{me.username}\n\n"
                f"حالا آیدی عددی نماینده (مالک این بات) را ارسال کنید:")
            )

        @router.message(AdminAddResellerBot.waiting_owner_id)
        async def process_resbot_owner_id(message: Message, state: FSMContext):
            if not message.text.strip().isdigit():
                await message.answer(db.get_text('handlers_admin.auto_0cd98de6', 'لطفاً فقط آیدی عددی ارسال کنید.'))
                return
            await state.update_data(resbot_owner_id=int(message.text.strip()))
            await state.set_state(AdminAddResellerBot.waiting_owner_name)
            await message.answer(db.get_text('handlers_admin.auto_141f56c6', 'یک نام برای این نماینده وارد کنید (فقط برای نمایش در پنل مدیریت):'))

        @router.message(AdminAddResellerBot.waiting_owner_name)
        async def process_resbot_owner_name(message: Message, state: FSMContext):
            await state.update_data(resbot_owner_name=message.text.strip())
            data = await state.get_data()
            token = data["resbot_token"]
            username = data["resbot_username"]
            owner_id = data["resbot_owner_id"]
            owner_name = data["resbot_owner_name"]

            os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
            db_path = os.path.join(RESELLER_DBS_DIR, f"{username}.db")
            # رفع باگ: این‌جا برخلاف _finalize_dedicated_bot_reseller (مسیر خودکارِ
            # تایید درخواست) فایل دیتابیسِ قدیمیِ باقی‌مانده روی همین مسیر (از یک
            # نماینده‌ی قبلی با همین یوزرنیمِ بات که با گزینه‌ی «پاک نشود» حذف شده
            # بود) پاک نمی‌شد؛ چون init_db از CREATE TABLE IF NOT EXISTS استفاده
            # می‌کند، کاربران/کیف‌پول/سفارش‌های نماینده‌ی قبلی عیناً به این نماینده‌ی
            # تازه هم دیده می‌شد. حالا مثل آن مسیر، قبل از ثبت‌نام پاک می‌شود.
            if os.path.exists(db_path):
                logger.warning(
                    "فایل دیتابیس قدیمی روی مسیر نماینده‌ی تازه پیدا شد و قبل از ثبت‌نام پاک می‌شود: %s", db_path,
                )
                try:
                    os.remove(db_path)
                except OSError:
                    logger.exception("پاک‌کردن فایل دیتابیس قدیمی نماینده ناموفق بود: %s", db_path)
                for suffix in (".fsm.sqlite3", ".fsm.sqlite3-wal", ".fsm.sqlite3-shm"):
                    stale_fsm = db_path + suffix
                    if os.path.exists(stale_fsm):
                        try:
                            os.remove(stale_fsm)
                        except OSError:
                            pass

            reseller_id = (await asyncio.to_thread(db.register_reseller_bot, token, username, owner_id, owner_name, db_path))

            started = False
            if bot_manager:
                started = await bot_manager.start_bot(token, db_path, owner_id, is_main_bot=False)

            # دیتابیس همین نماینده باید بداند شناسه‌ی خودش در جدول reseller_bots (بات اصلی) چیست
            # تا بتواند لینک مینی‌اپ اختصاصی خودش را بسازد (?b=<reseller_id>)، و سطح دسترسی‌اش چیست
            reseller_db = Database(db_path)
            (await asyncio.to_thread(reseller_db.init_db, owner_id=owner_id))
            (await asyncio.to_thread(reseller_db.set_setting, "miniapp_tenant_id", str(reseller_id)))
            # نمایندگی نباید هرگز حالت کانفیگ دستی/شخصی روشن داشته باشد
            (await asyncio.to_thread(reseller_db.set_setting, "custom_config_enabled", "0"))
            # رفع باگ اصلی: قبلاً هیچ‌کدام از این دو خط اینجا نبودند، پس فلگ
            # is_reseller مالک در دیتابیس *اصلی* هرگز True نمی‌شد و
            # reseller_auto_provision.provision_auto_config (که همین فلگ را
            # چک می‌کند) همیشه با «دسترسی اعتبار حجمی فعال نیست» شکست
            # می‌خورد - یعنی نمایندگی ساخته‌شده از این مسیر عملاً هرگز
            # نمی‌توانست چیزی بفروشد تا وقتی ادمین جداگانه و بدون هیچ راهنمایی‌ای
            # از صفحه‌ی «مدیریت نماینده‌ها» آن را دستی فعال می‌کرد. set_reseller_supply_model
            # هم صریحاً به «اعتبار حجمی/بدون محصول ثابت» ست می‌شود تا اگر همین
            # owner_id قبلاً (در یک نمایندگی حذف‌شده‌ی دیگر) مدل «محصول آماده»
            # داشته، آن باقیمانده نمایندگیِ تازه را خراب نکند.
            (await asyncio.to_thread(db.set_reseller_supply_model, owner_id, "volume_credit", None))
            (await asyncio.to_thread(db.set_reseller_status, owner_id, True))

            await state.clear()
            status_text = "✅ بات نمایندگی راه‌اندازی و همین الان روشن شد." if started else \
                "⚠️ بات ثبت شد ولی راه‌اندازی زنده انجام نشد؛ با ری‌استارت سرویس اصلی خودکار روشن می‌شود."
            extra_note = (
                "\n\n⚠️ نمایندگی فعال شد ولی اعتبار حجمی‌اش صفر است؛ از «مدیریت نماینده‌ها ← "
                "تنظیم اعتبار» برایش شارژ کنید، وگرنه خریدهای مشتری‌هایش شکست می‌خورد."
            )
            await message.answer(
                tr(f"{status_text}\n\n"
                f"🤖 بات: @{username}\n"
                f"👤 نماینده: {owner_name} ({owner_id})\n\n"
                f"این بات کاملاً مستقل است و تمام امکانات (کد تخفیف، زیرمجموعه‌گیری، کیف پول، کانفیگ تست) را "
                f"از صفر و جدا از بات اصلی دارد. نماینده باید با /start به بات خودش (@{username}) وارد شود."
                f"{extra_note}"),
                reply_markup=kb.resellers_kb((await asyncio.to_thread(db.list_reseller_bots))),
            )

        # ---------------------------------------------------------------
        # درخواست خودکار نمایندگی (بررسی، تعیین هزینه، تایید پرداخت)
        # ---------------------------------------------------------------

        @router.callback_query(F.data.startswith("resreq_approve:"))
        async def cb_resreq_approve(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or req["status"] != "pending_review":
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            # رفع باگ: قبلاً از اینجا تا ثبت قیمت، وضعیت درخواست همچنان pending_review
            # می‌ماند، پس اگر دو ادمین senior هم‌زمان روی همین درخواست کلیک می‌کردند،
            # هر دو می‌توانستند مسیر انتخاب پنل/قیمت را جداگانه طی کنند و آخری بی‌سروصدا
            # کار اولی را رونویسی می‌کرد. claim اتمیک این را می‌بندد.
            if not (await asyncio.to_thread(db.claim_reseller_request, request_id, call.from_user.id)):
                await call.answer(db.get_text('handlers_admin.auto_bc92c7f8', 'این درخواست همین الان توسط ادمین دیگری در حال بررسی است.'), show_alert=True)
                return
            panels = (await asyncio.to_thread(db.get_panel_servers, active_only=True))
            await call.message.answer(
                db.get_text('handlers_admin.auto_40db30b1', '🔗 این نماینده روی کدام پنل کانفیگ بسازد؟\n(نماینده هیچ\u200cوقت آدرس/مشخصات این پنل را نمی\u200cبیند.)'),
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
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            if req["claimed_by"] and req["claimed_by"] != call.from_user.id:
                await call.answer(db.get_text('handlers_admin.auto_627606a0', 'این درخواست توسط ادمین دیگری در حال بررسی است.'), show_alert=True)
                return
            await state.update_data(resreq_request_id=request_id, resreq_panel_id=panel_id or None)
            await state.set_state(AdminResellerRequestFlow.waiting_price)
            await call.message.answer(tr(f"💰 هزینه‌ی این نمایندگی (به تومان) چقدر باشد؟ فقط عدد ارسال کنید:"))
            await call.answer()

        @router.message(AdminResellerRequestFlow.waiting_price)
        async def process_resreq_price(message: Message, state: FSMContext, bot: Bot):
            text = (message.text or "").strip().replace(",", "")
            if not text.isdigit() or int(text) <= 0:
                await message.answer(db.get_text('handlers_admin.auto_fb9e0845', 'لطفاً یک عدد صحیح و مثبت ارسال کنید.'))
                return
            price = int(text)
            data = await state.get_data()
            request_id, panel_id = data.get("resreq_request_id"), data.get("resreq_panel_id")
            req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
            if not req or req["status"] != "pending_review":
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'))
                return
            if req["claimed_by"] and req["claimed_by"] != message.from_user.id:
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_627606a0', 'این درخواست توسط ادمین دیگری در حال بررسی است.'))
                return
            await state.update_data(resreq_price=price)
            tier = (await asyncio.to_thread(db.get_reseller_tier, req["tier_code"])) if req["tier_code"] else None
            if tier and tier["model"] == "commission":
                low = int(tier["commission_min"] or 1)
                high = int(tier["commission_max"] or 100)
                await state.update_data(resreq_percent_kind="commission", resreq_percent_low=low, resreq_percent_high=high)
                await state.set_state(AdminResellerRequestFlow.waiting_percent)
                proposed = req["proposed_percent"]
                accept_kb = kb.reseller_request_accept_percent_kb(proposed) if proposed is not None and low <= int(proposed) <= high else None
                hint = f"\n💡 پیشنهاد کاربر: {proposed}٪" if proposed is not None else ""
                await message.answer(tr(f"📈 درصد کمیسیون تاییدشده برای این نماینده برنزی را بفرستید (بین {low} تا {high}):{hint}"), reply_markup=accept_kb)
                return
            if tier and tier["model"] == "discount":
                await state.update_data(resreq_percent_kind="discount", resreq_percent_low=1, resreq_percent_high=100)
                await state.set_state(AdminResellerRequestFlow.waiting_percent)
                proposed = req["proposed_percent"]
                accept_kb = kb.reseller_request_accept_percent_kb(proposed) if proposed is not None and 1 <= int(proposed) <= 100 else None
                hint = f"\n💡 پیشنهاد کاربر: {proposed}٪" if proposed is not None else ""
                await message.answer(tr(f"🏷 درصد تخفیف دائمی تاییدشده برای این نماینده نقره‌ای را بفرستید (بین 1 تا 100):{hint}"), reply_markup=accept_kb)
                return
            await _resreq_show_payment_methods(message, state, req, price)

        async def _resreq_show_payment_methods(message: Message, state: FSMContext, req, price: int):
            catalog = [x for x in (await asyncio.to_thread(db.get_payment_methods_catalog, True)) if x["key"] != "wallet"]
            if not catalog:
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_f2dfe1b7', '⚠️ هیچ روش پرداخت فعالی وجود ندارد. ابتدا یک روش پرداخت را فعال کنید و دوباره تلاش کنید.'))
                return
            keys = [x["key"] for x in catalog]
            tier_default = await asyncio.to_thread(db.get_reseller_payment_methods, req["tier_code"] if req["tier_code"] else None)
            selected = [k for k in (tier_default or keys) if k in keys] or keys
            await state.update_data(resreq_pm_items=[[x["key"], x["label"]] for x in catalog], resreq_pm_selected=selected)
            await state.set_state(AdminResellerRequestFlow.waiting_payment_methods)
            await message.answer(
                tr(f"💳 روش‌های پرداخت مجاز برای این درخواست ({price:,} تومان) را انتخاب کنید:"),
                reply_markup=kb.reseller_request_payment_methods_kb([(x["key"], x["label"]) for x in catalog], selected),
            )

        async def _resreq_apply_percent(message: Message, state: FSMContext, admin_id: int, value: int):
            data = await state.get_data()
            request_id, price = data.get("resreq_request_id"), data.get("resreq_price")
            req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
            if not req or not price or req["status"] != "pending_review":
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'))
                return
            if req["claimed_by"] and req["claimed_by"] != admin_id:
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_627606a0', 'این درخواست توسط ادمین دیگری در حال بررسی است.'))
                return
            key = "resreq_commission_percent" if data.get("resreq_percent_kind") == "commission" else "resreq_discount_percent"
            await state.update_data(**{key: value})
            await _resreq_show_payment_methods(message, state, req, price)

        @router.message(AdminResellerRequestFlow.waiting_percent)
        async def process_resreq_percent(message: Message, state: FSMContext):
            text = (message.text or "").strip().replace("%", "").replace("٪", "")
            data = await state.get_data()
            low, high = int(data.get("resreq_percent_low") or 1), int(data.get("resreq_percent_high") or 100)
            if not text.isdigit() or not (low <= int(text) <= high):
                await message.answer(tr(f"لطفاً یک عدد صحیح بین {low} تا {high} ارسال کنید."))
                return
            await _resreq_apply_percent(message, state, message.from_user.id, int(text))

        @router.callback_query(AdminResellerRequestFlow.waiting_percent, F.data == "rrpct:accept")
        async def cb_resreq_accept_percent(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            data = await state.get_data()
            req = (await asyncio.to_thread(db.get_reseller_request, data.get("resreq_request_id"))) if data.get("resreq_request_id") else None
            proposed = req["proposed_percent"] if req else None
            low, high = int(data.get("resreq_percent_low") or 1), int(data.get("resreq_percent_high") or 100)
            if proposed is None or not (low <= int(proposed) <= high):
                await call.answer(db.get_text('handlers_admin.auto_9eb74877', 'پیشنهاد کاربر معتبر نیست؛ درصد را دستی بفرستید.'), show_alert=True)
                return
            await call.answer()
            await _resreq_apply_percent(call.message, state, call.from_user.id, int(proposed))

        @router.callback_query(AdminResellerRequestFlow.waiting_payment_methods, F.data.startswith("rrpm:"))
        async def cb_resreq_payment_methods(call: CallbackQuery, state: FSMContext, bot: Bot):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            parts = call.data.split(":")
            data = await state.get_data()
            items = [(k, label) for k, label in (data.get("resreq_pm_items") or [])]
            selected = list(data.get("resreq_pm_selected") or [])
            if parts[1] == "t" and len(parts) > 2 and parts[2].isdigit():
                idx = int(parts[2])
                if 0 <= idx < len(items):
                    key = items[idx][0]
                    selected = [k for k in selected if k != key] if key in selected else selected + [key]
                    await state.update_data(resreq_pm_selected=selected)
                    try:
                        await call.message.edit_reply_markup(reply_markup=kb.reseller_request_payment_methods_kb(items, selected))
                    except TelegramBadRequest:
                        pass
                await call.answer()
                return
            if parts[1] != "ok":
                await call.answer()
                return
            if not selected:
                await call.answer(db.get_text('handlers_admin.auto_89b52b68', 'حداقل یک روش پرداخت انتخاب کنید.'), show_alert=True)
                return
            price = data.get("resreq_price")
            request_id, panel_id = data.get("resreq_request_id"), data.get("resreq_panel_id")
            req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
            await state.clear()
            if not req or not price or req["status"] != "pending_review":
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            if req["claimed_by"] and req["claimed_by"] != call.from_user.id:
                await call.answer(db.get_text('handlers_admin.auto_627606a0', 'این درخواست توسط ادمین دیگری در حال بررسی است.'), show_alert=True)
                return

            commission_percent = data.get("resreq_commission_percent")
            discount_percent = data.get("resreq_discount_percent")
            (await asyncio.to_thread(db.quote_reseller_request, request_id, price, panel_id, call.from_user.id, commission_percent, discount_percent, selected))
            percent_log = f" | کمیسیون: {commission_percent}٪" if commission_percent is not None else (f" | تخفیف: {discount_percent}٪" if discount_percent is not None else "")
            (await asyncio.to_thread(db.log_admin_action,
                call.from_user.id, "reseller_request_quote",
                f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {price:,}{percent_log} | روش‌ها: {', '.join(selected)}",
            ))
            labels = {k: label for k, label in items}
            await safe_edit(call, f"✅ هزینه برای کاربر ارسال شد ({price:,} تومان).\n💳 روش‌های پرداخت: " + "، ".join(labels.get(k, k) for k in selected))
            await call.answer()
            volume_line = f"📦 حجم: {req['volume_gb']:,} گیگ\n" if req["volume_gb"] else ""
            approved_percent = commission_percent if commission_percent is not None else discount_percent
            proposed_percent = req["proposed_percent"] if "proposed_percent" in req.keys() else None
            percent_label = "📈 کمیسیون" if commission_percent is not None else "🏷 تخفیف نماینده"
            percent_line = f"{percent_label} تاییدشده: {approved_percent}٪\n" if approved_percent is not None else ""
            if approved_percent is not None and proposed_percent is not None and int(proposed_percent) != int(approved_percent):
                percent_line += f"💡 پیشنهاد شما: {proposed_percent}٪ (مدیر عدد بالا را تایید کرد)\n"
            try:
                await bot.send_message(
                    req["user_id"],
                    tr(f"🏪 درخواست نمایندگی #{request_id} شما تایید شد!\n\n"
                    f"💰 هزینه‌ی نمایندگی: {price:,} تومان\n"
                    f"{percent_line}{volume_line}\n"
                    f"در صورت موافقت روی «پرداخت می‌کنم» بزنید:"),
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
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            await state.update_data(resreq_reject_id=request_id, resreq_reject_status="rejected")
            await state.set_state(AdminResellerRequestFlow.waiting_reject_reason)
            await call.message.answer(db.get_text('handlers_admin.auto_57558377', 'دلیل رد درخواست را بنویسید (برای کاربر ارسال می\u200cشود):'))
            await call.answer()

        async def _decide_tier_request(call: CallbackQuery, bot: Bot, approve: bool):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_tier_request, request_id))
            if approve:
                result = await asyncio.to_thread(db.approve_tier_request, request_id, call.from_user.id) if req else {"ok": False, "reason": "invalid"}
                if not result.get("ok"):
                    if result.get("reason") == "insufficient_balance":
                        await call.answer(tr(f"موجودی کافی نیست. هزینه: {int(result.get('fee', 0)):,} تومان | موجودی: {int(result.get('balance', 0)):,}"), show_alert=True)
                    else:
                        await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                    return
            else:
                done = req is not None and (await asyncio.to_thread(db.reject_tier_request, request_id, call.from_user.id))
                if not done:
                    await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                    return
            tier = (await asyncio.to_thread(db.get_reseller_tier, req["tier_code"]))
            label = f"{tier['icon']} {tier['title']}" if tier else req["tier_code"]
            (await asyncio.to_thread(
                db.log_admin_action, call.from_user.id, "tier_request_approve" if approve else "tier_request_reject",
                f"درخواست #{request_id} | کاربر {req['user_id']} | سطح {req['tier_code']}",
            ))
            membership = await asyncio.to_thread(db.get_reseller_membership, req["user_id"]) if approve else {}
            expiry_line = ""
            if approve:
                fee = int(membership.get("membership_fee_toman") or 0)
                expires = membership.get("reseller_expires_at")
                expiry_line = f"\n💳 هزینه: {fee:,} تومان" + (f"\n⏳ انقضا: {expires}" if expires else "\n⏳ مدت: دائمی")
            text = (
                f"✅ درخواست شما برای سطح {label} تایید شد.{expiry_line}\n\n"
                "تخفیف‌ها هنگام «خرید کانفیگ» خودکار اعمال می‌شود."
                if approve else f"❌ متاسفانه درخواست شما برای سطح {label} رد شد."
            )
            try:
                await bot.send_message(req["user_id"], text)
            except Exception:
                pass
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await call.answer("تایید شد." if approve else "رد شد.")

        @router.callback_query(F.data.startswith("tierreq_ok:"))
        async def cb_tierreq_ok(call: CallbackQuery, bot: Bot):
            await _decide_tier_request(call, bot, True)

        @router.callback_query(F.data.startswith("tierreq_no:"))
        async def cb_tierreq_no(call: CallbackQuery, bot: Bot):
            await _decide_tier_request(call, bot, False)

        @router.callback_query(F.data.startswith("resreq_payreject:"))
        async def cb_resreq_payreject(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or req["status"] != "awaiting_payment_review":
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            await state.update_data(resreq_reject_id=request_id, resreq_reject_status="payment_rejected")
            await state.set_state(AdminResellerRequestFlow.waiting_reject_reason)
            await call.message.answer(db.get_text('handlers_admin.auto_3df8597c', 'دلیل رد پرداخت را بنویسید (برای کاربر ارسال می\u200cشود):'))
            await call.answer()

        @router.message(AdminResellerRequestFlow.waiting_reject_reason)
        async def process_resreq_reject_reason(message: Message, state: FSMContext, bot: Bot):
            reason = (message.text or "").strip()
            if not reason:
                await message.answer(db.get_text('handlers_admin.auto_7a2ca801', 'لطفاً دلیل را به\u200cصورت متن بنویسید.'))
                return
            data = await state.get_data()
            request_id = data.get("resreq_reject_id")
            status = data.get("resreq_reject_status", "rejected")
            req = (await asyncio.to_thread(db.get_reseller_request, request_id)) if request_id else None
            await state.clear()
            if not req:
                await message.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'))
                return

            (await asyncio.to_thread(db.reject_reseller_request, request_id, status, message.from_user.id, reason))
            (await asyncio.to_thread(db.log_admin_action, 
                message.from_user.id, "reseller_request_reject",
                f"درخواست #{request_id} | کاربر {req['user_id']} | وضعیت: {status} | دلیل: {reason}",
            ))
            await message.answer(db.get_text('handlers_admin.auto_3a17bf6f', '✅ ثبت شد و به کاربر اطلاع داده شد.'))
            label = "درخواست نمایندگی" if status == "rejected" else "پرداخت درخواست نمایندگی"
            try:
                await bot.send_message(
                    req["user_id"],
                    tr(f"❌ متاسفانه {label} شما (#{request_id}) رد شد.\n\nدلیل: {reason}"),
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
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return

            # رفع باگ ریس‌کاندیشن: approve_reseller_request_payment حالا خودش اتمیک
            # است (WHERE status='awaiting_payment_review'). اگر ادمین دیگری (یا
            # همین ادمین با دبل‌تپ) لحظه‌ای زودتر برنده‌ی همین انتقال شده باشد،
            # False برمی‌گردد و اینجا با یک پیام واضح متوقف می‌شویم - به‌جای اینکه
            # تخصیص اعتبار/ساخت بات نماینده دوباره (و دوبار) اجرا شود.
            if not (await asyncio.to_thread(db.approve_reseller_request_payment, request_id, call.from_user.id)):
                await call.answer(db.get_text('handlers_admin.auto_5aab6bcb', 'این درخواست همین الان توسط ادمین دیگری تایید شد.'), show_alert=True)
                return
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "reseller_request_payment_approve",
                f"درخواست #{request_id} | کاربر {req['user_id']} | هزینه: {req['price_toman']:,}",
            ))

            req = await asyncio.to_thread(db.get_reseller_request, request_id)
            if req and req["status"] == "completed":
                tier = await asyncio.to_thread(db.get_reseller_tier, req["tier_code"]) if req["tier_code"] else None
                label = f"{tier['icon']} {tier['title']}" if tier else "نمایندگی"
                try:
                    await bot.send_message(req["user_id"], tr(f"✅ پرداخت هزینه {label} تایید شد و نمایندگی شما فعال شد."))
                except Exception:
                    pass
                try:
                    await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ پرداخت تایید شد و نمایندگی فعال شد.")
                except Exception:
                    pass
                await call.answer(db.get_text('handlers_admin.auto_853b02dd', 'پرداخت تایید و نمایندگی فعال شد.'))
                return
            bot_choice = req["bot_choice"] if "bot_choice" in req.keys() else "dedicated"
            if bot_choice == "dedicated":
                user_state = FSMContext(
                    storage=dispatcher.storage,
                    key=StorageKey(bot_id=bot.id, chat_id=req["user_id"], user_id=req["user_id"]),
                )
                # رفع باگ: قبلاً بدون هیچ چکی روی state فعلیِ کاربر می‌نوشت. اگر آن
                # لحظه کاربر وسط یک جریان کاملاً بی‌ربط (مثلاً پرداخت یک سفارش عادی یا
                # شارژ کیف پول) بود، آن state بی‌سروصدا پاک/رونویسی می‌شد و کاربر بدون
                # هیچ توضیحی جریان قبلی‌اش را از دست می‌داد. الان state فعلی قبل از
                # رونویسی چک می‌شود تا حداقل با یک پیام صریح به کاربر اطلاع داده شود.
                previous_state = await user_state.get_state()
                await user_state.set_state(ResellerRequestFlow.waiting_bot_token)
                await user_state.update_data(resreq_request_id=request_id)
                interrupted_note = ""
                if previous_state and previous_state not in (
                    ResellerRequestFlow.waiting_bot_token.state,
                    ResellerRequestFlow.waiting_owner_id.state,
                    ResellerRequestFlow.waiting_owner_id_confirm.state,
                ):
                    interrupted_note = (
                        "\n\n⚠️ توجه: اگر همین الان در حال انجام کار دیگری (مثلاً خرید یا شارژ کیف پول) "
                        "بودید، آن جریان لغو شد؛ بعداً می‌توانید دوباره از منو شروعش کنید."
                    )
                try:
                    await bot.send_message(
                        req["user_id"],
                        "✅ پرداخت شما تایید شد!\n\n"
                        "حالا توکن بات نماینده‌ی خودتان را ارسال کنید (همانی که از @BotFather گرفته‌اید):"
                        + interrupted_note,
                    )
                except Exception:
                    pass
            else:
                # «لینک اختصاصی داخل بات اصلی» یا «بدون بات»: نیازی به توکن/آیدی مالک نیست،
                # نمایندگی همین‌جا تکمیل می‌شود.
                await _finalize_no_bot_reseller_request(req, bot)

            try:
                await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ پرداخت تایید شد.")
            except Exception:
                try:
                    await safe_edit(call, (call.message.text or "") + "\n\n✅ پرداخت تایید شد.")
                except Exception:
                    pass
            await call.answer(db.get_text('handlers_admin.auto_941ff861', 'پرداخت تایید شد.'))

        async def _finalize_no_bot_reseller_request(req, bot: Bot):
            """تکمیل درخواست نمایندگی برای انتخاب «لینک اختصاصی داخل بات اصلی» یا «بدون بات»
            (بخش ۳.۱ اسپک، گزینه‌ی الف): اگر پنل‌وب/مینی‌اپ خواسته شده، یک رکورد reseller_bots با
            has_live_bot=0 (بدون توکن واقعی، بدون bot_manager.start_bot) و دیتابیس جدا ساخته می‌شود.

            برای «لینک اختصاصی داخل بات اصلی»: نماینده inline_reseller_enabled می‌شود و لینک
            resref_<id> برایش ساخته می‌شود؛ کارمزد هر خرید مشتریانش (owner_reseller_id) از طریق
            db.reward_referrer_if_first_purchase → db._apply_inline_reseller_commission به کیف
            پولش واریز می‌شود (مستقل کامل از جدول reseller_bots، طبق درخواست خودِ اسپک).
            """
            owner_id = req["user_id"]
            reseller_bot_id = None
            if req["wants_web_panel"] or req["wants_miniapp"]:
                os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
                fake_slug = f"noBot_{req['id']}_{owner_id}"
                fake_token = f"no-bot:{req['id']}:{owner_id}"
                db_path = os.path.join(RESELLER_DBS_DIR, f"{fake_slug}.db")
                # رفع باگ: fake_slug شامل شناسه‌ی همین درخواست است پس برخورد آن با
                # فایل نماینده‌ی دیگری تقریباً غیرممکن است، اما برای اطمینان کامل و
                # هم‌خوانی با مسیر «بات اختصاصی» (که این ریسک را واقعاً دارد؛ نگاه کنید
                # به reseller_request_owner_id_confirmed در handlers_user.py)، همان
                # پاکسازی دفاعی این‌جا هم تکرار می‌شود.
                if os.path.exists(db_path):
                    logger.warning(
                        "فایل دیتابیس قدیمی روی مسیر نماینده‌ی تازه (بدون بات) پیدا شد و پاک می‌شود: %s", db_path,
                    )
                    try:
                        os.remove(db_path)
                    except OSError:
                        logger.exception("پاک‌کردن فایل دیتابیس قدیمی نماینده ناموفق بود: %s", db_path)
                # قبلاً اینجا req["request_text"] (متن آزادِ توضیحِ درخواست) به‌جای اسم
                # صاحب بات ذخیره می‌شد؛ get_reseller_owner_display_name اسم/یوزرنیم
                # واقعی کاربر را برمی‌گرداند.
                owner_name = (await asyncio.to_thread(db.get_reseller_owner_display_name, owner_id))
                reseller_bot_id = (await asyncio.to_thread(
                    db.register_reseller_bot, fake_token, fake_slug, owner_id,
                    owner_name, db_path, has_live_bot=0,
                ))
                if req["wants_web_panel"]:
                    (await asyncio.to_thread(db.enable_reseller_web_panel, reseller_bot_id))
                (await asyncio.to_thread(db.set_reseller_miniapp_enabled, reseller_bot_id, bool(req["wants_miniapp"])))
                reseller_db = Database(db_path)
                (await asyncio.to_thread(reseller_db.init_db, owner_id=owner_id))
                if req["wants_miniapp"]:
                    (await asyncio.to_thread(reseller_db.set_setting, "miniapp_tenant_id", str(reseller_bot_id)))
                wants_custom_config = "1" if req["wants_custom_config"] else "0"
                (await asyncio.to_thread(reseller_db.set_setting, "custom_config_enabled", wants_custom_config))

            (await asyncio.to_thread(db.set_reseller_status, owner_id, True))
            (await asyncio.to_thread(db.set_reseller_supply_model, owner_id, req["supply_model"], req["supply_product_id"]))
            if req["supply_model"] == "fixed_product" and req["supply_product_id"] and req["supply_qty"]:
                (await asyncio.to_thread(
                    db.set_reseller_product_credit, owner_id, req["supply_product_id"], req["supply_qty"],
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

            interface_bits = []
            if req["wants_web_panel"]:
                interface_bits.append("پنل وب")
            if req["wants_miniapp"]:
                interface_bits.append("مینی‌اپ")
            interface_label = " و ".join(interface_bits) if interface_bits else "بدون رابط (فقط اعتبار/موجودی)"
            note = ""
            if req["bot_choice"] == "inline_link":
                (await asyncio.to_thread(db.enable_inline_reseller, owner_id))
                me = await bot.get_me()
                ref_link = f"https://t.me/{me.username}?start=resref_{owner_id}"
                percent = (await asyncio.to_thread(db.get_setting, "reseller_inline_commission_percent", "10"))
                note = (
                    f"\n\n🔗 لینک اختصاصی فروش شما داخل همین بات:\n{ref_link}\n\n"
                    f"هر مشتری که با این لینک وارد شود و از شما خرید کند، {percent}٪ از مبلغ هر خرید "
                    f"به‌صورت اعتبار کیف پول به شما تعلق می‌گیرد. برای دیدن آمار، دستور /reseller_link را بفرستید."
                )
            # اگر پنل وب خواسته شده، لینک راه‌اندازی باید حتماً در همان پیام
            # تکمیل برای مالک ارسال شود. نماینده‌ی no-bot نمی‌تواند از بات
            # خودش پیام بگیرد، بنابراین بات اصلی ارسال‌کننده است.
            web_panel_note = ""
            if req["wants_web_panel"] and reseller_bot_id:
                try:
                    row = await asyncio.to_thread(db.get_reseller_bot, reseller_bot_id)
                    panel_url = _get_admin_panel_url(db)
                    if row and row["web_panel_setup_token"] and panel_url:
                        b_value = row["link_slug"] or str(reseller_bot_id)
                        setup_link = f"{panel_url}/setup?b={b_value}&t={row['web_panel_setup_token']}"
                        login_link = f"{panel_url}/?b={b_value}"
                        web_panel_note = (
                            f"\n\n🌐 لینک راه‌اندازی پنل وب نمایندگی:\n{setup_link}\n\n"
                            "این لینک یک‌بارمصرف است؛ با باز کردن آن، یوزرنیم و رمز پنل را خودت تعیین می‌کنی.\n"
                            f"🔗 لینک ورود بعدی: {login_link}"
                        )
                    elif req["wants_web_panel"]:
                        web_panel_note = "\n\n⚠️ پنل وب فعال شد ولی آدرس پنل مدیریت تنظیم نشده؛ پس از تنظیم دامنه، لینک راه‌اندازی را از مدیریت نماینده‌ها بساز."
                except Exception:
                    logger.exception("ساخت لینک پنل وب برای نماینده no-bot #%s ناموفق بود", reseller_bot_id)
            try:
                await bot.send_message(
                    owner_id,
                    tr(f"✅ نمایندگی شما تکمیل شد.\n🧩 رابط: {interface_label}{note}{web_panel_note}"),
                )
            except Exception:
                pass
            try:
                for a in (await asyncio.to_thread(db.list_admins_with_roles)):
                    if a["role"] in ("owner", "admin"):
                        await bot.send_message(
                            a["telegram_id"],
                            tr(f"✅ نمایندگی #{req['id']} (بدون بات مستقل) تکمیل شد.\n👤 مالک: {owner_id}"),
                        )
            except Exception:
                pass



        # ---------------------------------------------------------------
        # درخواست‌های نمایندگی (لیست کامل درخواست‌های باز + کنسل دستی)
        # ---------------------------------------------------------------

        @router.callback_query(F.data == "adm_reseller_requests_menu")
        async def cb_admin_reseller_requests_menu(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            requests = (await asyncio.to_thread(db.list_open_reseller_requests))
            if not requests:
                await call.answer(db.get_text('handlers_admin.auto_01717575', 'درخواست باز برای نمایندگی وجود ندارد.'), show_alert=True)
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
                await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
                return
            req = (await asyncio.to_thread(db.get_reseller_request, request_id))
            if not req or not (await asyncio.to_thread(db.is_reseller_request_open, req["status"])):
                await call.answer(db.get_text('handlers_admin.auto_01bb6976', 'این درخواست دیگر باز نیست.'), show_alert=True)
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
                    tr(f"⚪️ درخواست نمایندگی شما (#{request_id}) توسط مدیریت کنسل شد."),
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
                    reply_markup=kb.admin_back_kb("adm_cat:daily"),
                )
            await call.answer(db.get_text('handlers_admin.auto_353e9c9c', 'درخواست کنسل شد.'))

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
                db.get_text('handlers_admin.auto_63b89b3b', 'آیدی عددی کاربری که می\u200cخواهید نماینده\u200cاش کنید (یا مدیریت کنید) را ارسال کنید:'),
                reply_markup=kb.admin_back_kb("adm_credit_resellers_menu"),
            )
            await call.answer()

        async def _cres_limit_line(target_id: int) -> str:
            st = await asyncio.to_thread(db.get_wallet_status, target_id)
            return f"💳 سقف اعتبار پس‌پرداخت: {st['limit']:,} تومان | بدهی: {st['debt']:,} تومان"

        @router.message(AdminResellerCredit.waiting_user_id)
        async def process_cres_find(message: Message, state: FSMContext):
            raw = (message.text or "").strip()
            if not raw.isdigit():
                await message.answer(db.get_text('handlers_admin.auto_0cd98de6', 'لطفاً فقط آیدی عددی ارسال کنید.'))
                return
            target_id = int(raw)
            if not (await asyncio.to_thread(db.get_user, target_id)):
                await state.clear()
                await message.answer(
                    db.get_text('handlers_admin.auto_f974bdc2', 'این کاربر هنوز با بات /start نزده. اول باید کاربر یک\u200cبار بات را استارت کند.'),
                    reply_markup=kb.credit_resellers_menu_kb((await asyncio.to_thread(db.get_resellers))),
                )
                return
            await state.clear()
            credit = (await asyncio.to_thread(db.get_reseller_credit, target_id))
            is_res = (await asyncio.to_thread(db.is_reseller, target_id))
            await message.answer(
                f"👤 کاربر {target_id}\n"
                f"وضعیت نمایندگی: {'✅ فعال' if is_res else '◻️ غیرفعال'}\n"
                f"📦 اعتبار فعلی: {credit:,} گیگ\n"
                + (await _cres_limit_line(target_id)),
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )

        @router.callback_query(F.data.startswith("adm_cres_wlog:"))
        async def cb_admin_cres_wallet_log(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            rows = await asyncio.to_thread(db.get_wallet_transactions, target_id, 15)
            text = await asyncio.to_thread(db.wallet_transactions_text, rows)
            await replace_admin_view(
                call,
                f"📜 ۱۵ تراکنش آخر کیف پول کاربر {target_id}:\n\n" + text,
                reply_markup=kb.admin_back_kb(f"adm_cres_view:{target_id}"),
            )
            await call.answer()

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
                f"📦 اعتبار فعلی: {credit:,} گیگ\n"
                + (await _cres_limit_line(target_id)),
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
                f"📦 اعتبار فعلی: {credit:,} گیگ\n"
                + (await _cres_limit_line(target_id)),
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )
            await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

        @router.callback_query(F.data.startswith("adm_cres_credit:"))
        async def cb_admin_cres_credit(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            await state.update_data(cres_target_id=target_id)
            await state.set_state(AdminResellerCredit.waiting_delta)
            await safe_edit(
                call,
                db.get_text('handlers_admin.auto_26e1c12d', 'چند گیگ اضافه/کم شود؟ عدد مثبت برای شارژ، عدد منفی برای کسر (مثلاً 1000 یا 1000-):'),
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
                await message.answer(db.get_text('handlers_admin.auto_fa5ddc8c', 'لطفاً یک عدد صحیح غیرصفر ارسال کنید (مثلاً 1000 یا 1000-).'))
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
                f"📦 اعتبار فعلی: {credit:,} گیگ\n"
                + (await _cres_limit_line(target_id)),
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )

        @router.callback_query(F.data.startswith("adm_cres_limit:"))
        async def cb_admin_cres_limit(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            await state.update_data(cres_target_id=target_id)
            await state.set_state(AdminResellerCredit.waiting_limit)
            await safe_edit(
                call,
                "سقف اعتبار پس‌پرداخت را به تومان ارسال کنید. کیف پول نماینده تا این مبلغ می‌تواند منفی شود؛ 0 یعنی استفاده از سقف پیش‌فرض سطح نمایندگی او (در صورت تعریف):\n"
                + (await _cres_limit_line(target_id)),
                reply_markup=kb.admin_back_kb(f"adm_cres_view:{target_id}"),
            )
            await call.answer()

        @router.message(AdminResellerCredit.waiting_limit)
        async def process_cres_limit(message: Message, state: FSMContext):
            raw = (message.text or "").strip().replace(",", "").replace(" ", "")
            if not raw.isdigit():
                await message.answer(db.get_text('handlers_admin.auto_a66309b4', 'لطفاً یک عدد صحیح (تومان) ارسال کنید؛ 0 برای استفاده از سقف پیش\u200cفرض سطح.'))
                return
            data = await state.get_data()
            target_id = data.get("cres_target_id")
            await state.clear()
            if not (await asyncio.to_thread(db.set_credit_limit, target_id, int(raw))):
                await message.answer(db.get_text('handlers_admin.auto_b1786887', '⛔️ کاربر پیدا نشد.'))
                return
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "reseller_credit_limit", f"کاربر {target_id} | سقف {int(raw):,} تومان"))
            credit = (await asyncio.to_thread(db.get_reseller_credit, target_id))
            is_res = (await asyncio.to_thread(db.is_reseller, target_id))
            await message.answer(
                "✅ سقف اعتبار پس‌پرداخت تنظیم شد.\n\n"
                f"👤 کاربر {target_id}\n"
                f"📦 اعتبار فعلی: {credit:,} گیگ\n"
                + (await _cres_limit_line(target_id)),
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
                f"📦 اعتبار فعلی: {credit:,} گیگ\n"
                + (await _cres_limit_line(target_id)),
                reply_markup=kb.credit_reseller_view_kb(target_id, is_res),
            )
            await call.answer(db.get_text('handlers_admin.auto_582d5fbc', 'تنظیم شد.'))

        # ---------------------------------------------------------------
        # نمایندگی کمیسیونی (لینک اختصاصی داخل بات اصلی) - بدون حجم، بدون
        # محصول آماده؛ فقط درصد کمیسیون دائمی روی خریدهای مشتریان زیرمجموعه.
        # مستقل کامل از نمایندگی حجمی (بالا) و از reseller_requests.
        # ---------------------------------------------------------------

        @router.callback_query(F.data == "adm_commission_resellers_menu")
        async def cb_admin_commission_resellers_menu(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            pending = (await asyncio.to_thread(db.list_commission_reseller_requests, "pending"))
            await replace_admin_view(
                call,
                "💼 نمایندگی کمیسیونی\n\n"
                "بدون حجم و بدون محصول آماده؛ فقط یک لینک اختصاصی و درصد کمیسیون دائمی روی خریدهای "
                "مشتریانی که با آن لینک وارد شده‌اند - تا وقتی خودتان غیرفعالش کنید.",
                reply_markup=kb.commission_resellers_menu_kb(len(pending)),
            )
            await call.answer()

        @router.callback_query(F.data == "adm_comres_pending")
        async def cb_admin_comres_pending(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            pending = (await asyncio.to_thread(db.list_commission_reseller_requests, "pending"))
            if not pending:
                await replace_admin_view(
                    call, "📋 هیچ درخواست نمایندگی کمیسیونیِ در انتظاری وجود ندارد.",
                    reply_markup=kb.admin_back_kb("adm_commission_resellers_menu"),
                )
                await call.answer()
                return
            await replace_admin_view(
                call, f"📋 {len(pending)} درخواست در انتظار بررسی:",
                reply_markup=kb.commission_resellers_pending_kb(pending),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("comres_view:"))
        async def cb_admin_comres_view(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_commission_reseller_request, request_id))
            if not req or req["status"] != "pending":
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            user_row = (await asyncio.to_thread(db.get_user, req["user_id"]))
            first_name = (user_row["first_name"] if user_row else "") or ""
            username = (user_row["username"] if user_row else "") or "---"
            await replace_admin_view(
                call,
                f"💼 درخواست نمایندگی کمیسیونی #{request_id}\n"
                f"👤 کاربر: {first_name} (@{username})\n"
                f"🆔 آیدی عددی: {req['user_id']}\n"
                f"📊 درصد پیشنهادی: {req['proposed_percent']}٪",
                reply_markup=kb.commission_reseller_request_review_kb(request_id),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("comres_approve:"))
        async def cb_comres_approve(call: CallbackQuery, bot: Bot):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_commission_reseller_request, request_id))
            if not req or req["status"] != "pending":
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            # اتمیک: approve_commission_reseller_request خودش با WHERE status='pending'
            # چک می‌کند، پس اگر ادمین دیگری لحظه‌ای زودتر همین درخواست را تایید/رد کرده
            # باشد، None برمی‌گردد و اینجا با یک پیام واضح متوقف می‌شویم.
            approved = (await asyncio.to_thread(
                db.approve_commission_reseller_request, request_id, req["proposed_percent"], call.from_user.id,
            ))
            if not approved:
                await call.answer(db.get_text('handlers_admin.auto_8b9d2b13', 'این درخواست همین الان توسط ادمین دیگری بررسی شد.'), show_alert=True)
                return
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "commission_reseller_approve",
                f"درخواست #{request_id} | کاربر {req['user_id']} | {req['proposed_percent']}٪",
            ))
            me = await bot.get_me()
            link = f"https://t.me/{me.username}?start=resref_{req['user_id']}"
            try:
                await bot.send_message(
                    req["user_id"],
                    tr("✅ درخواست نمایندگی کمیسیونی شما تایید شد!\n\n"
                    f"🔗 لینک اختصاصی فروش شما:\n{link}\n\n"
                    f"روی هر خرید مشتریانی که با این لینک وارد شوند، {req['proposed_percent']}٪ کارمزد به کیف "
                    "پول شما اضافه می‌شود - تا وقتی ادمین نمایندگی‌تان را غیرفعال کند.\n"
                    "برای دیدن لینک و آمار، دستور /reseller_link را بفرستید."),
                )
                await _notify_user_inline_menu(bot, req["user_id"])
            except Exception:
                pass
            try:
                await call.message.edit_text((call.message.text or "") + "\n\n✅ تایید شد.")
            except Exception:
                pass
            await call.answer(db.get_text('handlers_admin.auto_d367e5e5', 'تایید شد.'))

        @router.callback_query(F.data.startswith("comres_reject:"))
        async def cb_comres_reject(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            request_id = int(call.data.split(":")[1])
            req = (await asyncio.to_thread(db.get_commission_reseller_request, request_id))
            if not req or req["status"] != "pending":
                await call.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'), show_alert=True)
                return
            await state.update_data(comres_reject_id=request_id)
            await state.set_state(AdminCommissionResellerFlow.waiting_reject_reason)
            await call.message.answer(db.get_text('handlers_admin.auto_57558377', 'دلیل رد درخواست را بنویسید (برای کاربر ارسال می\u200cشود):'))
            await call.answer()

        @router.message(AdminCommissionResellerFlow.waiting_reject_reason)
        async def process_comres_reject_reason(message: Message, state: FSMContext, bot: Bot):
            reason = (message.text or "").strip()
            data = await state.get_data()
            request_id = data.get("comres_reject_id")
            req = (await asyncio.to_thread(db.get_commission_reseller_request, request_id)) if request_id else None
            await state.clear()
            if not req or req["status"] != "pending":
                await message.answer(db.get_text('handlers_admin.auto_c22ab29a', 'این درخواست دیگر معتبر نیست.'))
                return
            rejected = (await asyncio.to_thread(
                db.reject_commission_reseller_request, request_id, reason, message.from_user.id,
            ))
            if not rejected:
                await message.answer(db.get_text('handlers_admin.auto_8b9d2b13', 'این درخواست همین الان توسط ادمین دیگری بررسی شد.'))
                return
            (await asyncio.to_thread(db.log_admin_action, 
                message.from_user.id, "commission_reseller_reject",
                f"درخواست #{request_id} | کاربر {req['user_id']} | دلیل: {reason}",
            ))
            await message.answer(db.get_text('handlers_admin.auto_3a17bf6f', '✅ ثبت شد و به کاربر اطلاع داده شد.'))
            try:
                await bot.send_message(
                    req["user_id"],
                    tr(f"❌ متاسفانه درخواست نمایندگی کمیسیونی شما (#{request_id}) رد شد.\n\nدلیل: {reason}"),
                )
                await _notify_user_inline_menu(bot, req["user_id"])
            except Exception:
                pass

        @router.callback_query(F.data == "adm_comres_active")
        async def cb_admin_comres_active(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            resellers = (await asyncio.to_thread(db.list_inline_resellers))
            if not resellers:
                await replace_admin_view(
                    call, "📊 هیچ نماینده‌ی کمیسیونیِ فعالی وجود ندارد.",
                    reply_markup=kb.admin_back_kb("adm_commission_resellers_menu"),
                )
                await call.answer()
                return
            await replace_admin_view(
                call, f"📊 {len(resellers)} نماینده‌ی کمیسیونیِ فعال:",
                reply_markup=kb.commission_reseller_active_kb(resellers),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("comres_view_active:"))
        async def cb_admin_comres_view_active(call: CallbackQuery):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            stats = (await asyncio.to_thread(db.get_inline_reseller_stats, target_id))
            await replace_admin_view(
                call,
                f"👤 نماینده‌ی کمیسیونی {target_id}\n\n"
                f"📊 درصد کمیسیون: {stats['percent']}٪\n"
                f"👥 تعداد مشتریان: {stats['customers']}\n"
                f"🧾 خریدهای تسویه‌شده: {stats['paid_orders']}\n"
                f"👛 مجموع کارمزد پرداختی: {stats['total_commission']:,} تومان",
                reply_markup=kb.commission_reseller_active_view_kb(target_id),
            )
            await call.answer()

        @router.callback_query(F.data.startswith("comres_disable:"))
        async def cb_admin_comres_disable(call: CallbackQuery, bot: Bot):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            (await asyncio.to_thread(db.disable_inline_reseller, target_id))
            (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "commission_reseller_disable", f"کاربر {target_id}"))
            try:
                await bot.send_message(target_id, tr("⛔️ نمایندگی کمیسیونی شما توسط ادمین غیرفعال شد."))
            except Exception:
                pass
            resellers = (await asyncio.to_thread(db.list_inline_resellers))
            await replace_admin_view(
                call, f"✅ نمایندگی این کاربر غیرفعال شد.\n\n📊 {len(resellers)} نماینده‌ی کمیسیونیِ فعال:",
                reply_markup=kb.commission_reseller_active_kb(resellers),
            )
            await call.answer(db.get_text('handlers_admin.auto_f2d4c165', 'غیرفعال شد.'))

        @router.callback_query(F.data.startswith("comres_edit:"))
        async def cb_admin_comres_edit(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            target_id = int(call.data.split(":")[1])
            await state.update_data(comres_edit_target=target_id)
            await state.set_state(AdminCommissionResellerFlow.waiting_edit_percent)
            await call.message.answer(db.get_text('handlers_admin.auto_46b898da', 'درصد کمیسیون جدید را ارسال کنید (عدد بین ۱ تا ۱۰۰):'))
            await call.answer()

        @router.message(AdminCommissionResellerFlow.waiting_edit_percent)
        async def process_comres_edit_percent(message: Message, state: FSMContext, bot: Bot):
            text = (message.text or "").strip()
            if not text.isdigit() or not (1 <= int(text) <= 100):
                await message.answer(db.get_text('handlers_admin.auto_15bcc016', 'لطفاً یک عدد صحیح بین ۱ تا ۱۰۰ ارسال کنید.'))
                return
            percent = int(text)
            data = await state.get_data()
            target_id = data.get("comres_edit_target")
            await state.clear()
            if not target_id:
                await message.answer(db.get_text('handlers_admin.auto_e12779c1', '⚠️ این عملیات منقضی شده؛ دوباره تلاش کنید.'))
                return
            (await asyncio.to_thread(db.set_inline_reseller_commission_percent, target_id, percent))
            (await asyncio.to_thread(db.log_admin_action, 
                message.from_user.id, "commission_reseller_edit_percent", f"کاربر {target_id} → {percent}٪",
            ))
            try:
                await bot.send_message(target_id, tr(f"📊 درصد کمیسیون نمایندگی شما به {percent}٪ تغییر کرد."))
            except Exception:
                pass
            await message.answer(
                tr(f"✅ درصد کمیسیون کاربر {target_id} به {percent}٪ تغییر کرد."),
                reply_markup=kb.commission_reseller_active_view_kb(target_id),
            )

        @router.callback_query(F.data == "adm_comres_direct_new")
        async def cb_admin_comres_direct_new(call: CallbackQuery, state: FSMContext):
            if not senior_admin_only(call.from_user.id):
                return await deny_mid(call)
            await state.set_state(AdminCommissionResellerFlow.waiting_direct_user_id)
            await safe_edit(
                call,
                db.get_text('handlers_admin.auto_a146b682', 'آیدی عددی کاربری که می\u200cخواهید مستقیماً نماینده\u200cی کمیسیونی کنید را ارسال کنید:'),
                reply_markup=kb.admin_back_kb("adm_commission_resellers_menu"),
            )
            await call.answer()

        @router.message(AdminCommissionResellerFlow.waiting_direct_user_id)
        async def process_comres_direct_user_id(message: Message, state: FSMContext):
            raw = (message.text or "").strip()
            if not raw.isdigit():
                await message.answer(db.get_text('handlers_admin.auto_0cd98de6', 'لطفاً فقط آیدی عددی ارسال کنید.'))
                return
            target_id = int(raw)
            if not (await asyncio.to_thread(db.get_user, target_id)):
                await message.answer(db.get_text('handlers_admin.auto_f974bdc2', 'این کاربر هنوز با بات /start نزده. اول باید کاربر یک\u200cبار بات را استارت کند.'))
                return
            if (await asyncio.to_thread(db.is_inline_reseller, target_id)):
                await state.clear()
                await message.answer(
                    db.get_text('handlers_admin.auto_685c8f76', 'این کاربر همین الان هم نماینده\u200cی کمیسیونی فعال است؛ از «لیست نماینده\u200cهای فعال» درصدش را ویرایش کنید.'),
                    reply_markup=kb.admin_back_kb("adm_commission_resellers_menu"),
                )
                return
            await state.update_data(comres_direct_target=target_id)
            await state.set_state(AdminCommissionResellerFlow.waiting_direct_percent)
            await message.answer(db.get_text('handlers_admin.auto_69017bc2', 'چند درصد کمیسیون برای این نماینده تعیین می\u200cکنید؟ عدد بین ۱ تا ۱۰۰ ارسال کنید:'))

        @router.message(AdminCommissionResellerFlow.waiting_direct_percent)
        async def process_comres_direct_percent(message: Message, state: FSMContext, bot: Bot):
            text = (message.text or "").strip()
            if not text.isdigit() or not (1 <= int(text) <= 100):
                await message.answer(db.get_text('handlers_admin.auto_15bcc016', 'لطفاً یک عدد صحیح بین ۱ تا ۱۰۰ ارسال کنید.'))
                return
            percent = int(text)
            data = await state.get_data()
            target_id = data.get("comres_direct_target")
            await state.clear()
            if not target_id:
                await message.answer(db.get_text('handlers_admin.auto_e12779c1', '⚠️ این عملیات منقضی شده؛ دوباره تلاش کنید.'))
                return
            (await asyncio.to_thread(db.enable_inline_reseller, target_id, percent))
            (await asyncio.to_thread(db.log_admin_action, 
                message.from_user.id, "commission_reseller_direct_create", f"کاربر {target_id} | {percent}٪",
            ))
            me = await bot.get_me()
            link = f"https://t.me/{me.username}?start=resref_{target_id}"
            try:
                await bot.send_message(
                    target_id,
                    tr("🎉 شما توسط ادمین به‌عنوان نماینده‌ی کمیسیونی تعیین شدید!\n\n"
                    f"🔗 لینک اختصاصی فروش شما:\n{link}\n\n"
                    f"روی هر خرید مشتریانی که با این لینک وارد شوند، {percent}٪ کارمزد به کیف پول شما اضافه "
                    "می‌شود - تا وقتی ادمین نمایندگی‌تان را غیرفعال کند.\n"
                    "برای دیدن لینک و آمار، دستور /reseller_link را بفرستید."),
                )
                await _notify_user_inline_menu(bot, target_id)
            except Exception:
                pass
            await message.answer(
                tr(f"✅ کاربر {target_id} با {percent}٪ کمیسیون، نماینده‌ی کمیسیونی شد."),
                reply_markup=kb.commission_reseller_active_view_kb(target_id),
            )

    # -------------------------------------------------------------------
    # ویرایش متن دکمه‌ها
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_edit_buttons")
    async def cb_admin_edit_buttons(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, "کدام دکمه ویرایش شود؟", reply_markup=kb.admin_edit_buttons_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_account_settings")
    async def cb_admin_account_settings(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(
            call,
            "🧾 تنظیمات حساب کاربری کاربران\n\nهر دکمه را برای فعال/غیرفعال‌کردن لمس کنید:",
            reply_markup=kb.account_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_acct_toggle:"))
    async def cb_admin_acct_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        key = call.data.split(":", 1)[1]
        valid_keys = {k for k, _label, _default in kb.ACCOUNT_TOGGLE_KEYS}
        if key not in valid_keys:
            await call.answer(db.get_text('handlers_admin.auto_e905b152', 'کلید نامعتبر.'), show_alert=True)
            return
        current = (await asyncio.to_thread(db.get_setting, key, "1"))
        (await asyncio.to_thread(db.set_setting, key, "0" if current == "1" else "1"))
        await safe_edit(
            call,
            db.get_text('handlers_admin.auto_3591a960', '🧾 تنظیمات حساب کاربری کاربران\n\nهر دکمه را برای فعال/غیرفعال\u200cکردن لمس کنید:'),
            reply_markup=kb.account_settings_kb(db),
        )
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data.startswith("adm_btn_edit:"))
    async def cb_admin_btn_edit(call: CallbackQuery, state: FSMContext):
        key = call.data.split(":")[1]
        await state.update_data(setting_key=key)
        await state.set_state(AdminEditButton.waiting_text)
        current = (await asyncio.to_thread(db.get_setting, key))
        await safe_edit(call, 
            f"متن فعلی: {current}\n\nمتن جدید را ارسال کنید (می‌توانید ایموجی هم اضافه کنید):",
            reply_markup=kb.admin_back_kb("adm_edit_buttons"),
        )
        await call.answer()

    @router.message(AdminEditButton.waiting_text)
    async def process_edit_button(message: Message, state: FSMContext):
        data = await state.get_data()
        key = data["setting_key"]
        (await asyncio.to_thread(db.set_setting, key, message.text.strip()))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_7eda6762', '✅ متن دکمه به\u200cروزرسانی شد.'), reply_markup=kb.admin_edit_buttons_kb(db))

    @router.callback_query(F.data.startswith("adm_btn_toggle:"))
    async def cb_admin_btn_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        key = call.data.split(":")[1]
        meta = MENU_BUTTON_META.get(key)
        if not meta or not meta["toggle_key"]:
            await call.answer(db.get_text('handlers_admin.auto_3afa6fa3', '❌ این دکمه قابل فعال/غیرفعال کردن نیست.'), show_alert=True)
            return
        toggle_key = meta["toggle_key"]
        current = (await asyncio.to_thread(db.get_setting, toggle_key, "1"))
        (await asyncio.to_thread(db.set_setting, toggle_key, "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_1c015d50', 'کدام دکمه ویرایش شود؟'), reply_markup=kb.admin_edit_buttons_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_8fd71e87', '✅ وضعیت دکمه به\u200cروزرسانی شد.'))

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
            await call.answer(db.get_text('handlers_admin.auto_cb537bc3', '⚠️ چون منوی شیشه\u200cای بالا غیرفعال است، منوی پایین را نمی\u200cتوان خاموش کرد.'), show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "main_menu_reply_enabled", "0" if current else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_1085e986', '🧩 تنظیمات منوی اصلی:'), reply_markup=kb.main_menu_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_236b18f2', '✅ اعمال شد.'))

    @router.callback_query(F.data == "adm_mm_toggle_inline")
    async def cb_admin_mm_toggle_inline(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "main_menu_inline_enabled", "0")) == "1"
        if current and (await asyncio.to_thread(db.get_setting, "main_menu_reply_enabled", "1")) != "1":
            await call.answer(db.get_text('handlers_admin.auto_85e83838', '⚠️ چون منوی پایین غیرفعال است، منوی شیشه\u200cای بالا را نمی\u200cتوان خاموش کرد.'), show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, "main_menu_inline_enabled", "0" if current else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_1085e986', '🧩 تنظیمات منوی اصلی:'), reply_markup=kb.main_menu_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_236b18f2', '✅ اعمال شد.'))

    @router.callback_query(F.data == "adm_mm_toggle_columns")
    async def cb_admin_mm_toggle_columns(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "main_menu_columns", "1"))
        new_val = "2" if current != "2" else "1"
        (await asyncio.to_thread(db.set_setting, "main_menu_columns", new_val))
        await safe_edit(call, db.get_text('handlers_admin.auto_1085e986', '🧩 تنظیمات منوی اصلی:'), reply_markup=kb.main_menu_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_236b18f2', '✅ اعمال شد.'))

    # کلیک روی دکمه‌ی «پنل مدیریت» وقتی از منوی شیشه‌ای بالا (نه منوی پایین) زده شود
    @router.callback_query(F.data == "mm:btn_admin_panel")
    async def cb_mm_admin_panel(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if not admin_only(call.from_user.id):
            return
        await state.clear()
        await call.message.answer(db.get_text('handlers_admin.auto_4741add8', '🔧 پنل مدیریت:'), reply_markup=kb.admin_panel_kb(db, is_main_bot))

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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        _, key, style = parts
        if not key or style not in {"primary", "success", "danger", "none"}:
            await call.answer(db.get_text('handlers_admin.auto_cfece57c', '❌ رنگ انتخاب\u200cشده نامعتبر است.'), show_alert=True)
            return
        (await asyncio.to_thread(db.set_setting, f"{key}_style", "" if style == "none" else style))
        if _is_panel_item_key(key):
            await safe_edit(call, db.get_text('handlers_admin.auto_7119a8d5', '🎨 رنگ\u200cآمیزی دکمه\u200cهای پنل مدیریت:'), reply_markup=kb.admin_panel_colors_kb(db, is_main_bot))
        elif _is_buyflow_key(key):
            await safe_edit(call, db.get_text('handlers_admin.auto_c916074c', '🎨 رنگ\u200cآمیزی دکمه\u200cهای خرید:'), reply_markup=kb.buy_flow_colors_kb(db))
        else:
            await safe_edit(call, db.get_text('handlers_admin.auto_1c015d50', 'کدام دکمه ویرایش شود؟'), reply_markup=kb.admin_edit_buttons_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_b39beef6', '✅ رنگ دکمه به\u200cروزرسانی شد.'))

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
    async def cb_admin_set_card(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, "💳 تنظیمات پرداخت کارت‌به‌کارت:", reply_markup=kb.card_settings_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_card_toggle")
    async def cb_admin_card_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "card_to_card_enabled", "1"))
        (await asyncio.to_thread(db.set_setting, "card_to_card_enabled", "0" if current == "1" else "1"))
        await safe_edit(call, db.get_text('handlers_admin.auto_1141f075', '💳 تنظیمات پرداخت کارت\u200cبه\u200cکارت:'), reply_markup=kb.card_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_set_card_edit")
    async def cb_admin_set_card_edit(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminSetCard.waiting_number)
        await safe_edit(call, db.get_text('handlers_admin.auto_890f2b8d', 'شماره کارت جدید را ارسال کنید:'), reply_markup=kb.admin_back_kb("adm_set_card"))
        await call.answer()

    @router.message(AdminSetCard.waiting_number)
    async def process_set_card_number(message: Message, state: FSMContext):
        await state.update_data(card_number=message.text.strip())
        await state.set_state(AdminSetCard.waiting_holder)
        await message.answer(db.get_text('handlers_admin.auto_3e9b3b19', 'نام صاحب حساب را ارسال کنید:'))

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
        await message.answer(db.get_text('handlers_admin.auto_9ebc4c96', '✅ اطلاعات کارت به\u200cروزرسانی شد.'), reply_markup=kb.card_settings_kb(db))

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
            db.get_text('handlers_admin.auto_51d8b3e7', '⏱ پیام\u200cهایی که شماره کارت داخلشونه (خرید، شارژ کیف پول، خرید نمایندگی و ...) بعد از مدت انتخابی، خودشون از چت حذف می\u200cشوند.\n\nمدت مورد نظر را انتخاب کن:'),
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
                call, db.get_text('handlers_admin.auto_ff8af74d', 'مدت دلخواه را به دقیقه ارسال کن (مثلاً 45):'),
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
            await message.answer(db.get_text('handlers_admin.auto_c2398e61', '⚠️ فقط یک عدد صحیح مثبت (به دقیقه) ارسال کن.'))
            return
        seconds = int(message.text.strip()) * 60
        await state.clear()
        (await asyncio.to_thread(db.set_setting, "card_msg_autodelete_seconds", str(seconds)))
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "card_autodelete_change",
            f"حذف خودکار پیام شماره کارت روی {seconds} ثانیه تنظیم شد.",
        ))
        await message.answer(
            tr(f"✅ پیام‌های شماره کارت از این پس {_duration_label_fa(seconds)} بعد از ارسال خودکار حذف می‌شوند."),
            reply_markup=kb.admin_category_kb(db, is_main_bot, "finance"),
        )

    # -------------------------------------------------------------------
    # تنظیم درگاه پرداخت کریپتو (Plisio)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_set_plisio")
    async def cb_admin_set_plisio(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        source = crypto_payment.resolve_plisio_key_source(db)
        source_note = {
            "db": "✅ از همین پنل بات خوانده می‌شود (بات و مینی‌اپ هر دو همین را می‌بینند، بدون نیاز به ری‌استارت).",
            "env": "⚠️ فقط از فایل .env این پروسه خوانده می‌شود. اگر بات و مینی‌اپ را جدا ری‌استارت نکرده باشی ممکن است این دو با هم ناهماهنگ باشند. پیشنهاد: همینجا دوباره ثبتش کن تا مطمئن بشی.",
            "none": "❌ هیچ کلیدی (نه در دیتابیس، نه در .env) تنظیم نشده.",
        }[source]
        await replace_admin_view(
            call,
            "🪙 تنظیم درگاه پرداخت کریپتو (Plisio)\n\n"
            f"منبع کلید: {source_note}\n\n"
            "بعد از تنظیم کلید، از مینی‌اپ → مدیریت → فروش → «پرداخت کریپتو» فعالش کن.",
            reply_markup=kb.plisio_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_plisio_set_key")
    async def cb_admin_plisio_set_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = (await asyncio.to_thread(db.get_setting, "plisio_api_key", ""))
        masked = f"...{current[-4:]}" if current else "❌ تنظیم نشده"
        await state.set_state(AdminSetPlisio.waiting_key)
        await safe_edit(
            call,
            f"🪙 API Key حساب Plisio را ارسال کن (از plisio.net → API Settings).\n"
            f"وضعیت فعلی: {masked}\n\n"
            f"برای غیرفعال‌کردن، عبارت «حذف» را بفرست.",
            reply_markup=kb.admin_back_kb("adm_set_plisio"),
        )
        await call.answer()

    @router.message(AdminSetPlisio.waiting_key)
    async def process_set_plisio_key(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            (await asyncio.to_thread(db.set_setting, "plisio_api_key", ""))
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "plisio_key_change", "API Key کریپتو حذف شد."))
            await message.answer(db.get_text('handlers_admin.auto_9f3b9669', '✅ API Key کریپتو حذف شد و درگاه غیرفعال شد.'), reply_markup=kb.plisio_settings_kb(db))
            return
        (await asyncio.to_thread(db.set_setting, "plisio_api_key", text))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "plisio_key_change", "API Key کریپتو تغییر کرد."))
        await message.answer(
            db.get_text('handlers_admin.auto_b99f09c2', '✅ API Key کریپتو ذخیره شد.\nالان از مینی\u200cاپ → مدیریت → فروش → «پرداخت کریپتو» فعالش کن.'),
            reply_markup=kb.plisio_settings_kb(db),
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
        await safe_edit(call, f"متن فعلی:\n{current}\n\nمتن جدید را ارسال کنید:", reply_markup=kb.admin_back_kb("adm_cat:appearance"))
        await call.answer()

    @router.message(AdminEditWelcome.waiting_text)
    async def process_edit_welcome(message: Message, state: FSMContext):
        # از html_text به‌جای text استفاده می‌شود تا فرمت‌بندی (بولد/ایتالیک) و
        # به‌خصوص ایموجی‌های پریمیوم/سفارشی‌ای که ادمین تایپ می‌کند حفظ شوند؛
        # چون parse_mode بات روی HTML است، همین رشته‌ی HTML مستقیماً ارسال می‌شود.
        (await asyncio.to_thread(db.set_setting, "welcome_text", message.html_text))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_f4186c64', '✅ پیام خوش\u200cآمد به\u200cروزرسانی شد.'), reply_markup=kb.admin_category_kb(db, is_main_bot, "appearance"))

    # -------------------------------------------------------------------
    # مدیریت آموزش‌ها: هر آموزش یک عنوان، چند مرحله‌ی متن/عکس/ویدیو و یک یا
    # چند «محل نمایش» (منوی آموزش، بعد از خرید، هر دکمه/بخش بات) دارد.
    # -------------------------------------------------------------------

    def _parse_tutorial_title(text: str):
        parts = text.split(" ", 1)
        if len(parts) == 2 and len(parts[0]) <= 4 and not parts[0].isalnum():
            return parts[0], parts[1].strip()
        return "📚", text

    async def _show_tutorial_devices(call: CallbackQuery):
        devices = await asyncio.to_thread(db.get_tutorial_devices)
        text = (
            "📚 مدیریت آموزش‌ها\n\n"
            "روی عنوان هر آموزش بزن تا مراحل و محل نمایشش را مدیریت کنی؛ روی 🟢/⚪️ بزن تا برای کاربر نشان داده شود یا نه.\n\n"
        )
        text += "هنوز آموزشی ثبت نشده." if not devices else "آموزش‌های ثبت‌شده:"
        await safe_edit(call, text, reply_markup=kb.tutorial_devices_admin_kb(devices))

    @router.callback_query(F.data == "adm_tutorial_devices")
    async def cb_admin_tutorial_devices(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await _show_tutorial_devices(call)
        await call.answer()

    @router.callback_query(F.data == "adm_tut_dev_add")
    async def cb_admin_tut_dev_add(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminTutorialDeviceAdd.waiting_name)
        await safe_edit(
            call,
            "عنوان آموزش جدید را بفرست (مثلاً: اتصال در اندروید، نحوه‌ی شارژ کیف پول).\n"
            "برای اموجی سفارشی، اموجی را ابتدای متن بگذار (مثلاً: 🤖 اتصال در اندروید)؛ وگرنه اموجی پیش‌فرض 📚 گذاشته می‌شود.",
            reply_markup=kb.admin_back_kb("adm_tutorial_devices"),
        )
        await call.answer()

    @router.message(AdminTutorialDeviceAdd.waiting_name)
    async def process_tut_dev_add(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer(tr("لطفاً عنوان آموزش را به‌صورت نوشتاری ارسال کن:"))
            return
        emoji, name = _parse_tutorial_title(text)
        if not name:
            await message.answer(tr("لطفاً یک عنوان معتبر برای آموزش بفرست."))
            return
        tutorial_id = await asyncio.to_thread(db.add_tutorial_device, name, emoji)
        await asyncio.to_thread(db.set_tutorial_target, tutorial_id, tutorial_hub.GENERAL, True)
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "tutorial_device_add", f"آموزش جدید: {emoji} {name}")
        await state.clear()
        view_text, markup = await _tutorial_manage_view(tutorial_id)
        await message.answer(
            "✅ آموزش اضافه شد و به‌صورت پیش‌فرض در منوی «آموزش» نمایش داده می‌شود. "
            "مرحله‌ها را اضافه کن و در صورت نیاز محل نمایشش را تغییر بده.\n\n" + view_text,
            reply_markup=markup,
        )

    @router.callback_query(F.data.startswith("adm_tut_dev_toggle:"))
    async def cb_admin_tut_dev_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        device_id = callback_id(call.data, "adm_tut_dev_toggle")
        if device_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        device = await asyncio.to_thread(db.get_tutorial_device, device_id)
        if not device:
            await call.answer(tr("این آموزش قبلاً حذف شده."), show_alert=True)
            await _show_tutorial_devices(call)
            return
        (await asyncio.to_thread(db.set_tutorial_device_active, device_id, not device["is_active"]))
        await _show_tutorial_devices(call)
        await call.answer(db.get_text('handlers_admin.auto_0479b78b', '✅ ذخیره شد'))

    @router.callback_query(F.data.startswith("adm_tut_dev_del:"))
    async def cb_admin_tut_dev_del(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        device_id = callback_id(call.data, "adm_tut_dev_del")
        if device_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        (await asyncio.to_thread(db.delete_tutorial_device, device_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "tutorial_device_delete", f"حذف آموزش #{device_id}"))
        await _show_tutorial_devices(call)
        await call.answer(db.get_text('handlers_admin.auto_d89f1ae4', '🗑 حذف شد.'))

    async def _tutorial_manage_view(device_id: int):
        """(متن، کیبورد) صفحه‌ی مدیریت یک آموزش؛ اگر آموزش وجود نداشته باشد (None, None)."""
        device = await asyncio.to_thread(db.get_tutorial_device, device_id)
        if not device:
            return None, None
        steps = await asyncio.to_thread(db.get_tutorial_steps, device_id)
        targets = await asyncio.to_thread(db.get_tutorial_targets, device_id)
        status = "🟢 فعال" if device["is_active"] else "⚪️ غیرفعال"
        text = f"{device['emoji']} {device['name']}\nوضعیت: {status}\n"
        text += "📍 محل نمایش: " + (tutorial_hub.describe_targets(targets) if targets else "هیچ‌جا (برای کاربر نمایش داده نمی‌شود)") + "\n\n"
        text += "مراحل آموزش (به‌ترتیب برای کاربر فرستاده می‌شوند):" if steps else "هنوز مرحله‌ای اضافه نشده."
        return text, kb.tutorial_device_steps_admin_kb(device_id, steps)

    async def _show_tutorial_steps(call: CallbackQuery, device_id: int):
        text, markup = await _tutorial_manage_view(device_id)
        if text is None:
            await call.answer(tr("این آموزش قبلاً حذف شده."), show_alert=True)
            await _show_tutorial_devices(call)
            return
        await safe_edit(call, text, reply_markup=markup)

    @router.callback_query(F.data.startswith("adm_tut_steps:"))
    async def cb_admin_tut_steps(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        device_id = callback_id(call.data, "adm_tut_steps")
        if device_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        await _show_tutorial_steps(call, device_id)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tut_rename:"))
    async def cb_admin_tut_rename(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        device_id = callback_id(call.data, "adm_tut_rename")
        if device_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        device = await asyncio.to_thread(db.get_tutorial_device, device_id)
        if not device:
            await call.answer(tr("این آموزش قبلاً حذف شده."), show_alert=True)
            await _show_tutorial_devices(call)
            return
        await state.set_state(AdminTutorialRename.waiting_title)
        await state.update_data(tut_device_id=device_id)
        await safe_edit(
            call,
            f"عنوان فعلی: {device['emoji']} {device['name']}\n\n"
            "عنوان جدید را بفرست. برای تغییر اموجی، آن را ابتدای متن بگذار؛ وگرنه اموجی فعلی حفظ می‌شود.",
            reply_markup=kb.admin_back_kb(f"adm_tut_steps:{device_id}"),
        )
        await call.answer()

    @router.message(AdminTutorialRename.waiting_title)
    async def process_tut_rename(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer(tr("لطفاً عنوان را به‌صورت نوشتاری ارسال کن:"))
            return
        data = await state.get_data()
        device_id = data.get("tut_device_id")
        if not device_id:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_0e29be08', '⚠️ خطایی رخ داد، دوباره تلاش کنید.'))
            return
        emoji, name = _parse_tutorial_title(text)
        if not name:
            await message.answer(tr("لطفاً یک عنوان معتبر بفرست."))
            return
        has_emoji = emoji != "📚" or text.startswith("📚")
        await asyncio.to_thread(db.rename_tutorial, device_id, name, emoji if has_emoji else None)
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "tutorial_rename", f"تغییر عنوان آموزش #{device_id}: {name}")
        await state.clear()
        view_text, markup = await _tutorial_manage_view(device_id)
        if view_text is None:
            await message.answer(tr("این آموزش قبلاً حذف شده."))
            return
        await message.answer("✅ عنوان ذخیره شد.\n\n" + view_text, reply_markup=markup)

    async def _show_tutorial_bind_main(call: CallbackQuery, device_id: int):
        device = await asyncio.to_thread(db.get_tutorial_device, device_id)
        if not device:
            await call.answer(tr("این آموزش قبلاً حذف شده."), show_alert=True)
            await _show_tutorial_devices(call)
            return
        selected = await asyncio.to_thread(db.get_tutorial_targets, device_id)
        text = (
            f"🔗 محل نمایش «{device['name']}»\n\n"
            "هر جایی که تیک بزنی، زیر همان صفحه دکمه‌ی «📚 آموزش» برای کاربر نشان داده می‌شود "
            "(وقتی کاربر آن دکمه/بخش را بزند). یک گروه را باز کن تا دکمه‌هایش را ببینی."
        )
        await safe_edit(call, text, reply_markup=kb.tutorial_bind_main_kb(device_id, selected))

    @router.callback_query(F.data.startswith("adm_tut_bind:"))
    async def cb_admin_tut_bind(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        device_id = callback_id(call.data, "adm_tut_bind")
        if device_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        await _show_tutorial_bind_main(call, device_id)
        await call.answer()

    async def _show_tutorial_bind_group(call: CallbackQuery, device_id: int, group_idx: int):
        device = await asyncio.to_thread(db.get_tutorial_device, device_id)
        if not device:
            await call.answer(tr("این آموزش قبلاً حذف شده."), show_alert=True)
            await _show_tutorial_devices(call)
            return
        selected = await asyncio.to_thread(db.get_tutorial_targets, device_id)
        title = tutorial_hub.GROUPS[group_idx][1]
        text = f"🔗 «{device['name']}» - {title}\n\nروی هر مورد بزن تا آموزش به آن وصل یا از آن جدا شود:"
        await safe_edit(call, text, reply_markup=kb.tutorial_bind_group_kb(device_id, group_idx, selected))

    @router.callback_query(F.data.startswith("adm_tut_bg:"))
    async def cb_admin_tut_bind_group(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        parts = call.data.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit() or int(parts[2]) >= len(tutorial_hub.GROUPS):
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        await _show_tutorial_bind_group(call, int(parts[1]), int(parts[2]))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tut_tg:"))
    async def cb_admin_tut_bind_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        parts = call.data.split(":")
        valid = (
            len(parts) == 4 and parts[1].isdigit() and parts[2].isdigit()
            and int(parts[2]) < len(tutorial_hub.FLAT_KEYS)
            and (parts[3] == "m" or (parts[3].isdigit() and int(parts[3]) < len(tutorial_hub.GROUPS)))
        )
        if not valid:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        device_id = int(parts[1])
        if not await asyncio.to_thread(db.get_tutorial_device, device_id):
            await call.answer(tr("این آموزش قبلاً حذف شده."), show_alert=True)
            await _show_tutorial_devices(call)
            return
        target_key = tutorial_hub.FLAT_KEYS[int(parts[2])]
        await asyncio.to_thread(db.toggle_tutorial_target, device_id, target_key)
        if parts[3] == "m":
            await _show_tutorial_bind_main(call, device_id)
        else:
            await _show_tutorial_bind_group(call, device_id, int(parts[3]))
        await call.answer(db.get_text('handlers_admin.auto_0479b78b', '✅ ذخیره شد'))

    @router.callback_query(F.data.startswith("adm_tut_step_add:"))
    async def cb_admin_tut_step_add(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        device_id = callback_id(call.data, "adm_tut_step_add")
        if device_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        await state.set_state(AdminTutorialStepAdd.waiting_content)
        await state.update_data(tut_device_id=device_id)
        await safe_edit(
            call,
            "متن، عکس (با کپشن دلخواه) یا ویدیو (با کپشن دلخواه) این مرحله را بفرست. "
            "مراحل به همان ترتیبی که اضافه می‌کنی برای کاربر فرستاده می‌شوند.",
            reply_markup=kb.admin_back_kb(f"adm_tut_steps:{device_id}"),
        )
        await call.answer()

    @router.message(AdminTutorialStepAdd.waiting_content)
    async def process_tut_step_add(message: Message, state: FSMContext):
        if message.media_group_id:
            await message.answer(db.get_text('handlers_admin.auto_97dadc39', '⚠️ ارسال آلبوم (چند عکس با هم) پشتیبانی نمی\u200cشود. فقط یک عکس یا متن تکی بفرست.'))
            return
        data = await state.get_data()
        device_id = data.get("tut_device_id")
        if not device_id:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_0e29be08', '⚠️ خطایی رخ داد، دوباره تلاش کنید.'))
            return
        text = message.html_text if (message.text or message.caption) else ""
        photo_file_id = message.photo[-1].file_id if message.photo else None
        video_file_id = message.video.file_id if message.video else None
        if not text and not photo_file_id and not video_file_id:
            await message.answer(tr("لطفاً متن، عکس یا ویدیو ارسال کنید."))
            return
        (await asyncio.to_thread(db.add_tutorial_step, device_id, text or None, photo_file_id, video_file_id))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "tutorial_step_add", f"مرحله‌ی جدید برای دستگاه #{device_id}"))
        await state.clear()
        steps = await asyncio.to_thread(db.get_tutorial_steps, device_id)
        await message.answer(
            tr("✅ مرحله اضافه شد."),
            reply_markup=kb.tutorial_device_steps_admin_kb(device_id, steps),
        )

    @router.callback_query(F.data.startswith("adm_tut_step_del:"))
    async def cb_admin_tut_step_del(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        parts = call.data.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        step_id, device_id = int(parts[1]), int(parts[2])
        (await asyncio.to_thread(db.delete_tutorial_step, step_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "tutorial_step_delete", f"حذف مرحله #{step_id}"))
        await _show_tutorial_steps(call, device_id)
        await call.answer(db.get_text('handlers_admin.auto_d89f1ae4', '🗑 حذف شد.'))

    # -------------------------------------------------------------------
    # مدیریت ادمین‌ها
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_admins_menu")
    async def cb_admin_admins_menu(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_c7320c54', '⛔️ مدیریت ادمین\u200cها فقط برای مالک اصلی در دسترس است.'), show_alert=True)
        try:
            await replace_admin_view(call, "👤 مدیریت ادمین‌ها:", kb.admin_admins_menu_kb())
            await call.answer()
        except Exception:
            await call.answer(db.get_text('handlers_admin.auto_cd56b196', '⚠️ باز کردن مدیریت ادمین\u200cها ناموفق بود.'), show_alert=True)

    @router.callback_query(F.data == "adm_admins_list")
    async def cb_admin_admins_list(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_9c355eab', '⛔️ فقط مالک اصلی می\u200cتواند لیست ادمین\u200cها را ببیند.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_88506e2b', '⚠️ دریافت لیست ادمین\u200cها ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data == "adm_admin_add")
    async def cb_admin_admin_add(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_51c82ee1', '⛔️ فقط مالک اصلی می\u200cتواند ادمین اضافه کند.'), show_alert=True)
        await state.set_state(AdminAddAdmin.waiting_id)
        await replace_admin_view(call, 
            "آیدی عددی کاربر جدید برای افزودن به ادمین‌ها را ارسال کنید:", reply_markup=kb.admin_back_kb("adm_admins_menu")
        )
        await call.answer()

    @router.message(AdminAddAdmin.waiting_id)
    async def process_add_admin(message: Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_0cd98de6', 'لطفاً فقط آیدی عددی ارسال کنید.'))
            return
        target_id = int(raw)
        if (await asyncio.to_thread(db.is_admin, target_id)):
            await state.clear()
            await message.answer(
                db.get_text('handlers_admin.auto_b679b402', 'این کاربر از قبل ادمین است. برای تغییر نقشش از «🔄 تغییر نقش ادمین» استفاده کن.'),
                reply_markup=kb.admin_admins_menu_kb(),
            )
            return
        await state.clear()
        await message.answer(
            tr(f"نقش کاربر {target_id} چه باشد?"),
            reply_markup=kb.admin_role_pick_kb(target_id, "add"),
        )

    @router.callback_query(F.data.startswith("adm_add_admin_role:"))
    async def cb_admin_add_admin_role(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_51c82ee1', '⛔️ فقط مالک اصلی می\u200cتواند ادمین اضافه کند.'), show_alert=True)
        try:
            parts = (call.data or "").split(":")
            if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("admin", "mid", "support"):
                return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
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
            await call.answer(db.get_text('handlers_admin.auto_bad0b475', 'ادمین اضافه شد.'))
        except Exception:
            await call.answer(db.get_text('handlers_admin.auto_d8911723', '⚠️ افزودن ادمین ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data == "adm_admin_role_change")
    async def cb_admin_role_change_start(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_f394eb63', '⛔️ فقط مالک اصلی می\u200cتواند نقش ادمین\u200cها را تغییر دهد.'), show_alert=True)
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
            await message.answer(db.get_text('handlers_admin.auto_0cd98de6', 'لطفاً فقط آیدی عددی ارسال کنید.'))
            return
        target_id = int(raw)
        await state.clear()
        role = (await asyncio.to_thread(db.get_admin_role, target_id))
        if role is None:
            await message.answer(db.get_text('handlers_admin.auto_896322da', 'این کاربر ادمین نیست.'), reply_markup=kb.admin_admins_menu_kb())
            return
        if role == "owner":
            await message.answer(db.get_text('handlers_admin.auto_4c3d6df1', 'نقش مالک اصلی قابل تغییر نیست.'), reply_markup=kb.admin_admins_menu_kb())
            return
        await message.answer(
            tr(f"نقش جدید کاربر {target_id} (نقش فعلی: {kb.ADMIN_ROLE_LABELS.get(role, role)}) چه باشد؟"),
            reply_markup=kb.admin_role_pick_kb(target_id, "setrole"),
        )

    @router.callback_query(F.data.startswith("adm_change_role_set:"))
    async def cb_admin_change_role_set(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_f394eb63', '⛔️ فقط مالک اصلی می\u200cتواند نقش ادمین\u200cها را تغییر دهد.'), show_alert=True)
        try:
            parts = (call.data or "").split(":")
            if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("admin", "mid", "support"):
                return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
            target_id, role = int(parts[1]), parts[2]
            ok = (await asyncio.to_thread(db.set_admin_role, target_id, role))
            if not ok:
                return await call.answer(db.get_text('handlers_admin.auto_1e83fac4', '⛔️ تغییر نقش ناموفق بود.'), show_alert=True)
            (await asyncio.to_thread(db.log_admin_action, 
                call.from_user.id, "admin_role_change",
                f"کاربر {target_id} | نقش جدید: {kb.ADMIN_ROLE_LABELS.get(role, role)}",
            ))
            await safe_edit(
                call,
                f"✅ نقش کاربر {target_id} به «{kb.ADMIN_ROLE_LABELS.get(role, role)}» تغییر کرد.",
                kb.admin_back_kb("adm_admins_menu"),
            )
            await call.answer(db.get_text('handlers_admin.auto_2fa8a416', 'نقش تغییر کرد.'))
        except Exception:
            await call.answer(db.get_text('handlers_admin.auto_c007bbc7', '⚠️ تغییر نقش ناموفق بود. دوباره تلاش کنید.'), show_alert=True)

    @router.callback_query(F.data == "adm_admin_remove")
    async def cb_admin_admin_remove(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_d42365c3', '⛔️ فقط مالک اصلی می\u200cتواند ادمین حذف کند.'), show_alert=True)
        await state.set_state(AdminRemoveAdmin.waiting_id)
        await replace_admin_view(call, 
            "آیدی عددی ادمینی که باید حذف شود را ارسال کنید:", reply_markup=kb.admin_back_kb("adm_admins_menu")
        )
        await call.answer()

    @router.message(AdminRemoveAdmin.waiting_id)
    async def process_remove_admin(message: Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_0cd98de6', 'لطفاً فقط آیدی عددی ارسال کنید.'))
            return
        target_id = int(raw)
        try:
            if not (await asyncio.to_thread(db.is_admin, target_id)):
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_c4408543', '⛔️ این کاربر ادمین نیست.'), reply_markup=kb.admin_admins_menu_kb())
                return
            if (await asyncio.to_thread(db.get_admin_role, target_id)) == "owner":
                await state.clear()
                await message.answer(db.get_text('handlers_admin.auto_799aee7f', '⛔️ مالک اصلی قابل حذف نیست.'), reply_markup=kb.admin_admins_menu_kb())
                return
            ok = (await asyncio.to_thread(db.remove_admin, target_id))
            await state.clear()
            if ok:
                (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "admin_remove", f"کاربر {target_id}"))
                await message.answer(db.get_text('handlers_admin.auto_9ad77844', '✅ ادمین حذف شد.'), reply_markup=kb.admin_admins_menu_kb())
            else:
                await message.answer(db.get_text('handlers_admin.auto_3ea61525', '⛔️ حذف ادمین ناموفق بود.'), reply_markup=kb.admin_admins_menu_kb())
        except Exception:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_16f87dd4', '⚠️ حذف ادمین ناموفق بود. دوباره تلاش کنید.'))

    # -------------------------------------------------------------------
    # پیام همگانی
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_broadcast_edit")
    async def cb_admin_broadcast_edit(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        target = data.get("broadcast_target", "all")
        target_server_id = data.get("broadcast_target_server_id")
        await state.update_data(broadcast_target=target, broadcast_target_server_id=target_server_id)
        await state.set_state(AdminBroadcast.waiting_message)
        if target == "server" and target_server_id:
            server = (await asyncio.to_thread(db.get_panel_server, target_server_id))
            server_name = server["name"] if server else target_server_id
            prompt = f"متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (فقط برای کاربران دارای سرویس فعال روی سرور «{server_name}» ارسال می‌شود):"
        elif target == "no_config":
            prompt = "متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (فقط برای کاربرانی که الان هیچ کانفیگی ندارند ارسال می‌شود):"
        else:
            prompt = "متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (برای همه کاربران ارسال می‌شود):"
        await replace_admin_view(call, prompt, reply_markup=kb.admin_back_kb("adm_cat:marketing"))
        await call.answer()

    @router.callback_query(F.data == "adm_broadcast")
    async def cb_admin_broadcast(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await replace_admin_view(call, "📢 پیام همگانی به چه کسانی ارسال شود؟", reply_markup=kb.admin_broadcast_target_kb())
        await call.answer()

    @router.callback_query(F.data.startswith("adm_broadcast_target:"))
    async def cb_admin_broadcast_target(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        choice = call.data.split(":", 1)[1]
        if choice == "server":
            await replace_admin_view(call, "🖥 سرور مورد نظر را انتخاب کن:", reply_markup=kb.admin_broadcast_server_select_kb(db))
            await call.answer()
            return
        if choice == "no_config":
            await state.update_data(broadcast_target="no_config", broadcast_target_server_id=None)
            await state.set_state(AdminBroadcast.waiting_message)
            await replace_admin_view(
                call,
                "متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (فقط برای کاربرانی که الان هیچ کانفیگی ندارند ارسال می‌شود):",
                reply_markup=kb.admin_back_kb("adm_cat:marketing"),
            )
            await call.answer()
            return
        if choice == "inactive_config":
            await state.update_data(broadcast_target="inactive_config", broadcast_target_server_id=None)
            await state.set_state(AdminBroadcast.waiting_message)
            await replace_admin_view(
                call,
                "متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (فقط برای کاربرانی که یک کانفیگ غیرفعال/منقضی‌شده دارند ارسال می‌شود):",
                reply_markup=kb.admin_back_kb("adm_cat:marketing"),
            )
            await call.answer()
            return
        if choice == "no_purchase":
            default_days = (await asyncio.to_thread(db.get_setting, "broadcast_inactive_purchase_days", "30")) or "30"
            await state.set_state(AdminBroadcast.waiting_no_purchase_days)
            await replace_admin_view(
                call,
                f"عدد روز را وارد کن (کاربرانی که حداقل یک خرید تاییدشده دارند ولی در این تعداد روز اخیر خرید تاییدشده‌ی جدیدی نداشته‌اند هدف قرار می‌گیرند). پیش‌فرض فعلی: {default_days}",
                reply_markup=kb.admin_back_kb("adm_broadcast"),
            )
            await call.answer()
            return
        if choice == "left_channel":
            fj_settings = (await asyncio.to_thread(db.get_force_join_settings))
            if not fj_settings["enabled"] or not fj_settings["channel"]:
                await call.answer(tr("⚠️ عضویت اجباری در کانال فعال نیست یا کانالی تنظیم نشده."), show_alert=True)
                return
            await state.update_data(broadcast_target="left_channel", broadcast_target_server_id=None)
            await state.set_state(AdminBroadcast.waiting_message)
            await replace_admin_view(
                call,
                "متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (فقط برای کاربرانی که الان عضو کانال اجباری نیستند ولی هنوز عضو ربات‌اند ارسال می‌شود؛ عضویت هنگام ارسال چک می‌شود پس ممکن است کمی طول بکشد):",
                reply_markup=kb.admin_back_kb("adm_cat:marketing"),
            )
            await call.answer()
            return
        await state.update_data(broadcast_target="all", broadcast_target_server_id=None)
        await state.set_state(AdminBroadcast.waiting_message)
        await replace_admin_view(call, "متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (برای همه کاربران ارسال می‌شود):", reply_markup=kb.admin_back_kb("adm_cat:marketing"))
        await call.answer()

    @router.message(AdminBroadcast.waiting_no_purchase_days)
    async def process_broadcast_no_purchase_days(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            return
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer(tr("⚠️ فقط یک عدد صحیح مثبت وارد کن (مثلاً 30)."))
            return
        days = int(text)
        (await asyncio.to_thread(db.set_setting, "broadcast_inactive_purchase_days", str(days)))
        await state.update_data(broadcast_target="no_purchase", broadcast_target_server_id=None, broadcast_no_purchase_days=days)
        await state.set_state(AdminBroadcast.waiting_message)
        await message.answer(
            tr(f"متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (فقط برای کاربرانی که در {days} روز اخیر خرید تاییدشده‌ی جدیدی نداشته‌اند ارسال می‌شود):"),
            reply_markup=kb.admin_back_kb("adm_cat:marketing"),
        )

    @router.callback_query(F.data.startswith("adm_broadcast_server:"))
    async def cb_admin_broadcast_server(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        server_id = int(call.data.split(":", 1)[1])
        server = (await asyncio.to_thread(db.get_panel_server, server_id))
        if not server:
            await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
            return
        await state.update_data(broadcast_target="server", broadcast_target_server_id=server_id)
        await state.set_state(AdminBroadcast.waiting_message)
        await replace_admin_view(
            call,
            f"متن یا عکس (با یا بدون کپشن) پیام همگانی را ارسال کنید (فقط برای کاربران دارای سرویس فعال روی سرور «{server['name']}» ارسال می‌شود):",
            reply_markup=kb.admin_back_kb("adm_cat:marketing"),
        )
        await call.answer()

    @router.message(AdminBroadcast.waiting_message)
    async def process_broadcast(message: Message, state: FSMContext, bot: Bot):
        # بند ۴۵ اسپک: ارسال تصویر در پیام همگانی. آلبوم (چند عکس با هم) رد می‌شود
        # چون تلگرام هر عکس آلبوم را به‌صورت یک پیام جدا به بات می‌دهد و اگر اجازه
        # بدهیم، همین‌جا چند بار پشت‌سرهم process_broadcast صدا زده می‌شود و state
        # قبل از رسیدن به مرحله‌ی تایید مدت، چند بار بازنویسی/رد می‌شود.
        if message.media_group_id:
            await message.answer(db.get_text('handlers_admin.auto_97dadc39', '⚠️ ارسال آلبوم (چند عکس با هم) پشتیبانی نمی\u200cشود. فقط یک عکس یا متن تکی بفرست.'))
            return
        await state.update_data(
            broadcast_chat_id=message.chat.id,
            broadcast_message_id=message.message_id,
            broadcast_text=message.text,
            broadcast_caption=message.caption,
        )
        await state.set_state(AdminBroadcast.waiting_duration)
        # نمونه‌ی دقیق پیام (بند ۴۴ اسپک): برای کاهش اشتباه در ارسال به کل
        # کاربران، همان پیام با همان تابع copy_message که در _finalize_broadcast
        # برای خودِ کاربران استفاده می‌شود، اینجا یک بار برای خودِ ادمین هم کپی
        # می‌شود - یعنی دقیقاً همان چیزی که کاربران می‌بینند (نه صرفاً متنی که
        # ادمین تایپ کرده)، پیش از این‌که ادمین مدت حذف خودکار/ارسال را تایید کند.
        await message.answer(db.get_text('handlers_admin.auto_53032292', '👁 نمونه\u200cی دقیق پیامی که برای همه\u200cی کاربران ارسال می\u200cشود:'))
        await bot.copy_message(message.chat.id, from_chat_id=message.chat.id, message_id=message.message_id)
        await message.answer(
            db.get_text('handlers_admin.auto_18038d8a', '☝️ اگر همین درست است، مدت حذف خودکار را انتخاب کن تا ارسال شود؛ برای اصلاح پیام «✏️ ویرایش متن/عکس» و برای انصراف کامل «❌ لغو ارسال» را بزن.'),
            reply_markup=kb.admin_broadcast_duration_kb(pin_after_send=False),
        )

    @router.callback_query(F.data == "adm_broadcast_toggle_pin")
    async def cb_broadcast_toggle_pin(call: CallbackQuery, state: FSMContext):
        """قابلیت ۸۸: روشن/خاموش کردن گزینه‌ی «پین بعد از ارسال» برای همین پیام
        همگانی (بی‌صدا - disable_notification=True - چون پیام همین الان با
        نوتیفیکیشن عادی ارسال شده و پین دوباره نباید کاربر را دوبار مطلع کند)."""
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        new_value = not bool(data.get("broadcast_pin"))
        await state.update_data(broadcast_pin=new_value)
        try:
            await call.message.edit_reply_markup(reply_markup=kb.admin_broadcast_duration_kb(pin_after_send=new_value))
        except Exception:
            pass
        await call.answer("📌 پین بعد از ارسال روشن شد." if new_value else "📌 پین بعد از ارسال خاموش شد.")

    async def _finalize_broadcast(state: FSMContext, bot: Bot, admin_id: int, seconds: int, answer_fn):
        data = await state.get_data()
        chat_id = data.get("broadcast_chat_id")
        message_id = data.get("broadcast_message_id")
        target = data.get("broadcast_target", "all")
        target_server_id = data.get("broadcast_target_server_id")
        pin_after_send = bool(data.get("broadcast_pin"))
        await state.clear()
        if not chat_id or not message_id:
            await answer_fn("⚠️ اطلاعات پیام همگانی ناقص بود؛ دوباره از اول شروع کن.")
            return
        if target == "server" and target_server_id:
            user_ids = (await asyncio.to_thread(db.get_user_ids_by_panel_server, target_server_id))
            server = (await asyncio.to_thread(db.get_panel_server, target_server_id))
            target_label = f"کاربران سرور «{server['name']}»" if server else f"کاربران سرور #{target_server_id}"
        elif target == "no_config":
            user_ids = (await asyncio.to_thread(db.get_user_ids_without_config))
            target_label = "کاربران بدون کانفیگ"
        elif target == "inactive_config":
            user_ids = (await asyncio.to_thread(db.get_user_ids_with_inactive_config))
            target_label = "کاربران دارای کانفیگ غیرفعال"
        elif target == "no_purchase":
            days = int(data.get("broadcast_no_purchase_days") or 30)
            user_ids = (await asyncio.to_thread(db.get_user_ids_without_recent_purchase, days))
            target_label = f"کاربران بدون خرید در {days} روز اخیر"
        elif target == "left_channel":
            fj_settings = (await asyncio.to_thread(db.get_force_join_settings))
            channel = fj_settings["channel"]
            all_ids = (await asyncio.to_thread(db.get_all_user_ids))
            user_ids = []
            if channel:
                for uid in all_ids:
                    if await asyncio.to_thread(db.is_admin, uid):
                        continue
                    if await asyncio.to_thread(db.is_force_join_exempt, uid):
                        continue
                    is_member = await is_channel_member(bot, channel, uid)
                    if not is_member:
                        user_ids.append(uid)
                    await asyncio.sleep(0.05)
            target_label = "کاربران خارج‌شده از کانال اجباری"
        else:
            user_ids = (await asyncio.to_thread(db.get_all_user_ids))
            target_label = "همه‌ی کاربران"
        success, failed, pinned = 0, 0, 0
        sent_targets = []
        for uid in user_ids:
            # قبلاً بدون sleep/retry بین ارسال‌ها بود: برای لیست‌های بزرگ خیلی سریع
            # به محدودیت flood تلگرام می‌خورد و از همان‌جا به بعد اکثر پیام‌ها با
            # TelegramRetryAfter رد می‌شدند (چون فقط except Exception بی‌قید-وشرط
            # می‌گرفت و شمرده می‌شد failed، بدون صبر/تلاش مجدد) - از دید ادمین این
            # دقیقاً همان «هنگ‌کردن/کرش پیام همگانی» بود، چون هم اکثر ارسال‌ها ناموفق
            # می‌ماندند و هم کل حلقه به‌خاطر همین خطاهای پشت‌سرهم به‌شدت کند می‌شد.
            for _attempt in range(3):
                try:
                    sent = await bot.copy_message(uid, from_chat_id=chat_id, message_id=message_id)
                    success += 1
                    if seconds > 0:
                        sent_targets.append((uid, sent.message_id))
                    if pin_after_send:
                        try:
                            await bot.pin_chat_message(uid, sent.message_id, disable_notification=True)
                            pinned += 1
                        except Exception:
                            pass
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    continue
                except Exception:
                    failed += 1
                    break
            await asyncio.sleep(0.05)
        for uid, mid in sent_targets:
            await schedule_message_autodelete(db, uid, mid, seconds)
        label = _duration_label_fa(seconds) if seconds > 0 else "بدون حذف خودکار"
        pin_note = f" | پین‌شده: {pinned}" if pin_after_send else ""
        (await asyncio.to_thread(db.log_admin_action, admin_id, "broadcast", f"ارسال به {target_label} ({len(user_ids)} نفر) | موفق: {success} | ناموفق: {failed} | حذف خودکار: {label}{pin_note}"))
        await answer_fn(
            f"📢 پیام همگانی به {target_label} ارسال شد.\n👥 مجموع: {len(user_ids)}\n✅ موفق: {success}\n❌ ناموفق: {failed}\n⏱ حذف خودکار: {label}"
            + (f"\n📌 پین‌شده: {pinned}" if pin_after_send else ""),
            reply_markup=kb.admin_category_kb(db, is_main_bot, "marketing"),
        )

    @router.callback_query(F.data == "adm_broadcast_cancel")
    async def cb_broadcast_cancel(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await replace_admin_view(call, "❌ ارسال پیام همگانی لغو شد.", reply_markup=kb.admin_category_kb(db, is_main_bot, "marketing"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_broadcast_dur:"))
    async def cb_broadcast_duration(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        value = call.data.split(":", 1)[1]
        if value == "custom":
            await state.set_state(AdminBroadcast.waiting_custom_minutes)
            await replace_admin_view(call, "مدت دلخواه را به دقیقه ارسال کن (مثلاً 45):", reply_markup=kb.admin_back_kb("adm_cat:marketing"))
            await call.answer()
            return
        await call.answer(db.get_text('handlers_admin.auto_aad6a683', 'در حال ارسال...'))
        await _finalize_broadcast(state, call.bot, call.from_user.id, int(value), call.message.answer)

    @router.callback_query(F.data == "adm_broadcast_schedule")
    async def cb_broadcast_schedule(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        if not (data.get("broadcast_text") or "").strip():
            await call.answer(db.get_text('handlers_admin.auto_8aaa4716', 'زمان\u200cبندی فقط برای پیام متنی ممکن است.'), show_alert=True)
            return
        await state.set_state(AdminBroadcast.waiting_schedule_time)
        await replace_admin_view(
            call,
            "زمان ارسال را به وقت تهران بفرست:\nYYYY-MM-DD HH:MM\nمثال: 2026-09-25 18:30",
            reply_markup=kb.admin_back_kb("adm_cat:marketing"),
        )
        await call.answer()

    @router.message(AdminBroadcast.waiting_schedule_time)
    async def process_broadcast_schedule_time(message: Message, state: FSMContext):
        from zoneinfo import ZoneInfo
        from datetime import timezone
        try:
            local = datetime.strptime((message.text or "").strip(), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Tehran"))
        except ValueError:
            await message.answer(db.get_text('handlers_admin.auto_8ae4986a', '⚠️ قالب نامعتبر است. مثال: 2026-09-25 18:30'))
            return
        when_utc = local.astimezone(timezone.utc).replace(tzinfo=None)
        if when_utc <= datetime.utcnow():
            await message.answer(db.get_text('handlers_admin.auto_9949b97e', '⚠️ زمان باید در آینده باشد.'))
            return
        data = await state.get_data()
        text = (data.get("broadcast_text") or "").strip()
        await state.clear()
        job_id = await asyncio.to_thread(db.create_scheduled_broadcast, message.from_user.id, text, when_utc.isoformat(timespec="seconds"))
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "broadcast_schedule", f"پیام همگانی زمان‌بندی‌شده #{job_id} برای {local.strftime('%Y-%m-%d %H:%M')} (تهران)")
        await message.answer(
            tr(f"⏰ پیام برای {local.strftime('%Y-%m-%d %H:%M')} (وقت تهران) زمان‌بندی شد. شناسه: {job_id}"),
            reply_markup=kb.admin_category_kb(db, is_main_bot, "marketing"),
        )

    @router.message(AdminBroadcast.waiting_custom_minutes)
    async def process_broadcast_custom_minutes(message: Message, state: FSMContext, bot: Bot):
        if not (message.text or "").strip().isdigit() or int(message.text.strip()) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_c2398e61', '⚠️ فقط یک عدد صحیح مثبت (به دقیقه) ارسال کن.'))
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
            await message.answer(db.get_text('handlers_admin.auto_a09d1671', '⚠️ آیدی نامعتبر است؛ فقط عدد ارسال کن.'))
            return
        await state.update_data(temp_target_id=int(message.text.strip()))
        await state.set_state(AdminTempMessage.waiting_text)
        await message.answer(db.get_text('handlers_admin.auto_d56bc0bb', 'متن پیام موقت را ارسال کن:'), reply_markup=kb.admin_back_kb("adm_temp_message"))

    @router.message(AdminTempMessage.waiting_text)
    async def process_tempmsg_text(message: Message, state: FSMContext):
        if not (message.text or "").strip():
            await message.answer(db.get_text('handlers_admin.auto_f4ea3470', '⚠️ فقط متن پشتیبانی می\u200cشود؛ یک پیام متنی ارسال کن.'))
            return
        await state.update_data(temp_text=message.html_text)
        await message.answer(db.get_text('handlers_admin.auto_2e9ac45d', '⏱ بعد از چه مدت خودش حذف شود؟'), reply_markup=kb.admin_temp_message_duration_kb())

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
        await call.answer(db.get_text('handlers_admin.auto_aad6a683', 'در حال ارسال...'))
        await _finalize_temp_message(state, call.bot, int(value), call.message.answer)

    @router.message(AdminTempMessage.waiting_custom_minutes)
    async def process_tempmsg_custom_minutes(message: Message, state: FSMContext, bot: Bot):
        if not (message.text or "").strip().isdigit() or int(message.text.strip()) <= 0:
            await message.answer(db.get_text('handlers_admin.auto_c2398e61', '⚠️ فقط یک عدد صحیح مثبت (به دقیقه) ارسال کن.'))
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
            f"🎯 <b>محصول خاص</b> — <code>{base}prod_&lt;آیدی محصول&gt;</code>\n"
            "باز شدن مستقیم صفحه‌ی همان محصول (مثل انتخاب از منو)\n\n"
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
            f"<code>{base}buy-disc_SUMMER10</code>\n"
            f"یا برای بازکردن یک محصول خاص با کد تخفیف مخصوص همان: <code>{base}prod_12-disc_SUMMER10</code>"
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
            call, db.get_text('handlers_admin.auto_fefe2ec5', 'چه نوع دیپ\u200cلینکی می\u200cخوای بسازی؟'),
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
                db.get_text('handlers_admin.auto_10cfc4a0', '❌ این یک پیامِ فوروارد شده از کانال نبود. لطفاً خودِ پست کانال را فوروارد کن.'),
                reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
            )
            return

        await state.update_data(channel_chat_id=chat_id, channel_message_id=msg_id)
        await state.set_state(AdminChannelButton.waiting_button_text)
        await message.answer(db.get_text('handlers_admin.auto_cc7fa751', 'متن دکمه رو بفرست (مثلاً: 🎁 خرید با ۳۰٪ تخفیف)'))

    @router.message(AdminChannelButton.waiting_button_text)
    async def process_channel_button_text(message: Message, state: FSMContext):
        button_text = (message.text or "").strip()
        if not button_text:
            await message.answer(db.get_text('handlers_admin.auto_a1b81989', 'متن دکمه نمی\u200cتواند خالی باشد. دوباره بفرست:'))
            return
        await state.update_data(channel_button_text=button_text)
        await message.answer(
            db.get_text('handlers_admin.auto_188d4133', 'چه نوع دیپ\u200cلینکی به این دکمه وصل بشه؟'),
            reply_markup=kb.deeplink_type_picker_kb("adm_deeplink_tools"),
        )

    @router.callback_query(F.data.startswith("adm_dlp_type:"))
    async def cb_dlp_type(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        dl_type = call.data.split(":", 1)[1]

        if dl_type == "disc":
            codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
            active_codes = [c for c in codes if c["is_active"]]
            if not active_codes:
                await safe_edit(
                    call, db.get_text('handlers_admin.auto_1bd64a9f', '❌ هیچ کد تخفیف فعالی نداری. اول از «کدهای تخفیف» یکی بساز.'),
                    reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
                )
                await call.answer()
                return
            await safe_edit(
                call, db.get_text('handlers_admin.auto_704e95a1', 'کدوم کد تخفیف؟'),
                reply_markup=kb.deeplink_discount_picker_kb(active_codes, "adm_dl_build"),
            )
            await call.answer()
            return

        if dl_type == "prod":
            categories = (await asyncio.to_thread(db.get_categories, active_only=True))
            if not categories:
                await safe_edit(
                    call, db.get_text('handlers_admin.auto_4beff07a', '❌ هیچ دسته\u200cبندی/محصولی وجود ندارد.'),
                    reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
                )
                await call.answer()
                return
            await safe_edit(
                call, db.get_text('handlers_admin.auto_d24ad63a', 'محصول موردنظر در کدام دسته\u200cبندی است؟'),
                reply_markup=kb.deeplink_product_categories_kb(categories, "adm_dl_build"),
            )
            await call.answer()
            return

        if dl_type == "custom":
            data = await state.get_data()
            in_channel_flow = bool(data.get("channel_chat_id"))
            await state.set_state(
                AdminChannelButton.waiting_custom_param if in_channel_flow else AdminDeepLinkTools.waiting_custom_param
            )
            await safe_edit(call, db.get_text('handlers_admin.auto_6e4a5a0f', 'پارامتر دلخواه رو بفرست (فقط حروف/عدد/زیرخط، بدون فاصله):'))
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
            await call.answer(db.get_text('handlers_admin.auto_a51e7b91', 'کد پیدا نشد.'), show_alert=True)
            return
        await _finalize_deeplink(call, state, f"disc_{code_row['code']}", call.bot)

    @router.callback_query(F.data.startswith("adm_dlp_prodcat:"))
    async def cb_dlp_prodcat(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cat_id = int(call.data.split(":", 1)[1])
        products = (await asyncio.to_thread(db.get_products, cat_id, active_only=True))
        if not products:
            await call.answer(db.get_text('handlers_admin.auto_f7277c1c', 'محصولی در این دسته\u200cبندی نیست.'), show_alert=True)
            return
        await safe_edit(
            call, db.get_text('handlers_admin.auto_aca04f3e', 'کدام محصول؟'),
            reply_markup=kb.deeplink_products_kb(products, "adm_dl_build"),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_dlp_prod:"))
    async def cb_dlp_prod(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_id = int(call.data.split(":", 1)[1])
        product_token = f"prod_{product_id}"
        codes = (await asyncio.to_thread(db.list_discount_codes, "bulk_admin"))
        active_codes = [c for c in codes if c["is_active"]]
        if not active_codes:
            await _finalize_deeplink(call, state, product_token, call.bot)
            return
        await safe_edit(
            call, db.get_text('handlers_admin.auto_035e1988', 'می\u200cخواهید یک کد تخفیف هم به این لینک محصول اضافه شود؟'),
            reply_markup=kb.deeplink_attach_discount_picker_kb(active_codes, product_token, "adm_dl_build"),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_dlp_prod_nodisc:"))
    async def cb_dlp_prod_nodisc(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        product_token = call.data.split(":", 1)[1]
        await _finalize_deeplink(call, state, product_token, call.bot)

    @router.callback_query(F.data.startswith("adm_dlp_prod_disc:"))
    async def cb_dlp_prod_disc(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, product_token, code_id = call.data.split(":")
        code_row = (await asyncio.to_thread(db.get_discount_code_by_id, int(code_id)))
        if not code_row:
            await call.answer(db.get_text('handlers_admin.auto_a51e7b91', 'کد پیدا نشد.'), show_alert=True)
            return
        combined_token = f"{product_token}-disc_{code_row['code']}"
        await _finalize_deeplink(call, state, combined_token, call.bot)

    @router.message(AdminDeepLinkTools.waiting_custom_param)
    async def process_dl_custom_param(message: Message, state: FSMContext, bot: Bot):
        token = re.sub(r"[^A-Za-z0-9_]", "", (message.text or "").strip())
        if not token:
            await message.answer(db.get_text('handlers_admin.auto_e91d67e9', 'پارامتر نامعتبر بود. فقط حروف/عدد/زیرخط بفرست:'))
            return
        await state.clear()
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={token}"
        await message.answer(
            tr(f"🔗 دیپ‌لینک ساخته شد:\n\n`{link}`"),
            parse_mode="Markdown",
            reply_markup=kb.admin_back_kb("adm_deeplink_tools"),
        )

    @router.message(AdminChannelButton.waiting_custom_param)
    async def process_channel_custom_param(message: Message, state: FSMContext, bot: Bot):
        token = re.sub(r"[^A-Za-z0-9_]", "", (message.text or "").strip())
        if not token:
            await message.answer(db.get_text('handlers_admin.auto_e91d67e9', 'پارامتر نامعتبر بود. فقط حروف/عدد/زیرخط بفرست:'))
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
            tr(f"🔗 دیپ‌لینک ساخته شد:\n\n`{link}`"),
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
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        conv = (await asyncio.to_thread(db.get_support_conversation, user_id))
        assigned_admin_id = conv["assigned_admin_id"] if conv else None
        if assigned_admin_id and assigned_admin_id != call.from_user.id and not owner_only(call.from_user.id):
            await call.answer(
                db.get_text('handlers_admin.auto_8d7fe2d4', '⛔️ این گفتگو در حال حاضر توسط ادمین دیگری پاسخ داده می\u200cشود.'), show_alert=True
            )
            return
        await state.update_data(reply_to_user=user_id)
        await state.set_state(AdminReplyFlow.waiting_reply)
        await call.message.answer(tr(f"متن پاسخ برای کاربر {user_id} را ارسال کنید:"))
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
                db.get_text('handlers_admin.auto_8d7fe2d4', '⛔️ این گفتگو در حال حاضر توسط ادمین دیگری پاسخ داده می\u200cشود.'),
                reply_markup=kb.admin_panel_kb(db, is_main_bot),
            )
            await state.clear()
            return
        try:
            # html_text به‌جای text تا فرمت‌بندی/ایموجی پریمیومِ خودِ ادمین در
            # پیامی که کاربر می‌بیند حفظ شود (parse_mode بات HTML است).
            reply_html = message.html_text if message.text else ""
            await bot.send_message(user_id, tr(f"📩 پاسخ پشتیبانی:\n\n{reply_html}"))
            if message.text:
                if not owner_only(message.from_user.id):
                    (await asyncio.to_thread(db.set_support_conversation_admin, user_id, message.from_user.id))
                (await asyncio.to_thread(db.add_support_message, user_id, "admin", message.text))
            await _notify_user_inline_menu(bot, user_id)
            await message.answer(db.get_text('handlers_admin.auto_85615d96', '✅ پاسخ ارسال شد.'), reply_markup=kb.admin_panel_kb(db, is_main_bot))
        except Exception:
            await message.answer(db.get_text('handlers_admin.auto_7a519898', '⛔️ ارسال پیام به کاربر با خطا مواجه شد.'), reply_markup=kb.admin_panel_kb(db, is_main_bot))
        await state.clear()

    # -------------------------------------------------------------------
    # مدیریت تیکت‌های پشتیبانی
    # -------------------------------------------------------------------

    async def _render_admin_ticket_thread(ticket_id: int, active_status: str):
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket:
            return None
        (await asyncio.to_thread(db.mark_ticket_read_by_admin, ticket_id))
        messages = (await asyncio.to_thread(db.get_ticket_messages, ticket_id))
        user = (await asyncio.to_thread(db.get_user, ticket["user_id"]))
        user_label = f"@{user['username']}" if user and user["username"] else str(ticket["user_id"])
        department = await asyncio.to_thread(db.get_ticket_department, ticket['department_id']) if ticket['department_id'] else None
        lines = [
            f"🎫 تیکت #{ticket['id']} — {kb.TICKET_STATUS_LABELS.get(ticket['status'], ticket['status'])}",
            f"👤 کاربر: {user_label} ({ticket['user_id']})",
            f"📌 موضوع: {ticket['subject']}",
            f"🧩 بخش: {department['name'] if department else 'عمومی'}",
            "",
        ]
        for m in messages:
            sender_label = "👤 کاربر" if m["sender"] == "user" else "🛠 پشتیبانی"
            lines.append(f"{sender_label}: {m['message']}")
        text = "\n".join(lines)
        markup = kb.admin_ticket_view_kb(ticket_id, ticket["status"], active_status)
        return text, markup

    @router.callback_query(F.data == "adm_tickets_menu")
    async def cb_admin_tickets_menu(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        tickets = (await asyncio.to_thread(db.get_all_tickets, "open"))
        await replace_admin_view(call, "🎫 تیکت‌های پشتیبانی:", reply_markup=kb.admin_tickets_list_kb(tickets, "open"))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_tickets_list:"))
    async def cb_admin_tickets_list(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        status = call.data.split(":", 1)[1]
        tickets = (await asyncio.to_thread(db.get_all_tickets, None if status == "all" else status))
        await safe_edit(call, db.get_text('handlers_admin.auto_17685214', '🎫 تیکت\u200cهای پشتیبانی:'), reply_markup=kb.admin_tickets_list_kb(tickets, status))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ticket_view:"))
    async def cb_admin_ticket_view(call: CallbackQuery):
        if not admin_only(call.from_user.id):
            return await call.answer()
        parts = call.data.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        ticket_id = int(parts[1])
        active_status = parts[2] if len(parts) > 2 else "open"
        rendered = await _render_admin_ticket_thread(ticket_id, active_status)
        if not rendered:
            await call.answer(db.get_text('handlers_admin.auto_01aac3cf', 'تیکت یافت نشد.'), show_alert=True)
            return
        text, markup = rendered
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ticket_reply:"))
    async def cb_admin_ticket_reply(call: CallbackQuery, state: FSMContext):
        if not admin_only(call.from_user.id):
            return await call.answer()
        ticket_id = callback_id(call.data, "adm_ticket_reply")
        if ticket_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket:
            await call.answer(db.get_text('handlers_admin.auto_01aac3cf', 'تیکت یافت نشد.'), show_alert=True)
            return
        if ticket["status"] == "closed":
            await call.answer(db.get_text('handlers_admin.auto_5a91e0a5', '⛔️ این تیکت بسته شده است.'), show_alert=True)
            return
        if ticket["claimed_by"] and ticket["claimed_by"] != call.from_user.id and not owner_only(call.from_user.id):
            await call.answer(db.get_text('handlers_admin.auto_51895a9a', '⛔️ این تیکت توسط ادمین دیگری در حال پاسخ است.'), show_alert=True)
            return
        await state.update_data(reply_ticket_id=ticket_id)
        await state.set_state(AdminTicketReplyFlow.waiting_reply)
        await call.message.answer(tr(f"متن پاسخ برای تیکت #{ticket_id} را ارسال کنید:"))
        await call.answer()

    @router.message(AdminTicketReplyFlow.waiting_reply)
    async def process_admin_ticket_reply(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        ticket_id = data.get("reply_ticket_id")
        if not ticket_id:
            await state.clear()
            return
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket:
            await message.answer(db.get_text('handlers_admin.auto_01aac3cf', 'تیکت یافت نشد.'), reply_markup=kb.admin_panel_kb(db, is_main_bot))
            await state.clear()
            return
        if ticket["claimed_by"] and ticket["claimed_by"] != message.from_user.id and not owner_only(message.from_user.id):
            await message.answer(
                db.get_text('handlers_admin.auto_51895a9a', '⛔️ این تیکت توسط ادمین دیگری در حال پاسخ است.'),
                reply_markup=kb.admin_panel_kb(db, is_main_bot),
            )
            await state.clear()
            return
        try:
            # html_text به‌جای text تا فرمت‌بندی/ایموجی پریمیومِ خودِ ادمین در
            # پاسخِ نمایش‌داده‌شده به کاربر حفظ شود (parse_mode بات HTML است).
            reply_html = message.html_text if message.text else ""
            await bot.send_message(
                ticket["user_id"],
                tr(f"🎫 پاسخ پشتیبانی به تیکت «{ticket['subject']}» (#{ticket_id}):\n\n{reply_html}"),
            )
            (await asyncio.to_thread(db.claim_ticket_if_open, ticket_id, message.from_user.id))
            (await asyncio.to_thread(db.add_ticket_message, ticket_id, "admin", message.text))
            await _notify_user_inline_menu(bot, ticket["user_id"])
            await message.answer(
                tr(f"✅ پاسخ به تیکت #{ticket_id} ارسال شد."), reply_markup=kb.admin_panel_kb(db, is_main_bot)
            )
        except Exception:
            await message.answer(db.get_text('handlers_admin.auto_8211dedc', '⛔️ ارسال پاسخ با خطا مواجه شد.'), reply_markup=kb.admin_panel_kb(db, is_main_bot))
        await state.clear()

    @router.callback_query(F.data.startswith("adm_ticket_close:"))
    async def cb_admin_ticket_close(call: CallbackQuery, bot: Bot):
        if not admin_only(call.from_user.id):
            return await call.answer()
        ticket_id = callback_id(call.data, "adm_ticket_close")
        if ticket_id is None:
            await call.answer(db.get_text('handlers_admin.auto_524e296b', '❌ درخواست نامعتبر است.'), show_alert=True)
            return
        ticket = (await asyncio.to_thread(db.get_ticket, ticket_id))
        if not ticket:
            await call.answer(db.get_text('handlers_admin.auto_01aac3cf', 'تیکت یافت نشد.'), show_alert=True)
            return
        (await asyncio.to_thread(db.close_ticket, ticket_id))
        try:
            await bot.send_message(
                ticket["user_id"], tr(f"🔒 تیکت «{ticket['subject']}» (#{ticket_id}) توسط پشتیبانی بسته شد.")
            )
        except Exception:
            pass
        await safe_edit(call, f"✅ تیکت #{ticket_id} بسته شد.", reply_markup=kb.admin_back_kb("adm_tickets_menu"))
        await call.answer()

    @router.callback_query(F.data == "adm_ticket_departments")
    async def cb_admin_ticket_departments(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_0cbf62fc', '⛔️ فقط مالک می\u200cتواند دپارتمان\u200cها را تنظیم کند.'), show_alert=True)
        departments = await asyncio.to_thread(db.list_ticket_departments, False)
        await replace_admin_view(call, "🧩 دپارتمان‌های پشتیبانی\n\nبرای تعیین ادمین‌های هر بخش، دپارتمان را انتخاب کنید:", reply_markup=kb.admin_ticket_departments_kb(departments))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ticket_dept:"))
    async def cb_admin_ticket_department(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_bf6b3d20', '⛔️ فقط مالک.'), show_alert=True)
        raw = call.data.split(":", 1)[1]
        if not raw.isdigit():
            return await call.answer(db.get_text('handlers_admin.auto_27bcb055', '❌ نامعتبر.'), show_alert=True)
        dep = await asyncio.to_thread(db.get_ticket_department, int(raw))
        if not dep:
            return await call.answer(db.get_text('handlers_admin.auto_a890896d', '❌ دپارتمان یافت نشد.'), show_alert=True)
        admins = await asyncio.to_thread(db.list_admins_with_roles)
        assigned = set(await asyncio.to_thread(db.list_ticket_department_admins, dep["id"]))
        await safe_edit(call, f"🧩 دپارتمان «{dep['name']}»\nادمین‌های مجاز برای دریافت تیکت:", reply_markup=kb.admin_ticket_department_admins_kb(dep, admins, assigned))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ticket_dept_admin:"))
    async def cb_admin_ticket_department_admin(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await call.answer(db.get_text('handlers_admin.auto_bf6b3d20', '⛔️ فقط مالک.'), show_alert=True)
        parts = call.data.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            return await call.answer(db.get_text('handlers_admin.auto_27bcb055', '❌ نامعتبر.'), show_alert=True)
        dep_id, admin_id = int(parts[1]), int(parts[2])
        await asyncio.to_thread(db.toggle_ticket_department_admin, dep_id, admin_id)
        dep = await asyncio.to_thread(db.get_ticket_department, dep_id)
        admins = await asyncio.to_thread(db.list_admins_with_roles)
        assigned = set(await asyncio.to_thread(db.list_ticket_department_admins, dep_id))
        await safe_edit(call, f"🧩 دپارتمان «{dep['name']}»\nادمین‌های مجاز برای دریافت تیکت:", reply_markup=kb.admin_ticket_department_admins_kb(dep, admins, assigned))
        await call.answer(db.get_text('handlers_admin.auto_c78aa882', 'ذخیره شد'))

    # -------------------------------------------------------------------
    # تنظیم آیدی مدیر برای چت مستقیم (بخش ارتباط با پشتیبانی)
    # -------------------------------------------------------------------

    SUPPORT_METHODS_HEADER = "📞 روش‌های ارتباط با پشتیبانی\n\nهر روش را برای فعال/غیرفعال‌کردن لمس کنید. دکمه‌ی چت مستقیم فقط وقتی نمایش داده می‌شود که آیدی مدیر تنظیم شده باشد:"

    @router.callback_query(F.data == "adm_set_support_contact")
    async def cb_admin_set_support_contact(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(
            call,
            SUPPORT_METHODS_HEADER,
            reply_markup=kb.support_contact_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_support_toggle:"))
    async def cb_admin_support_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        key = call.data.split(":", 1)[1]
        if key not in {k for k, _label in kb.SUPPORT_CONTACT_METHODS}:
            await call.answer(db.get_text('handlers_admin.auto_e905b152', 'کلید نامعتبر.'), show_alert=True)
            return
        new_value = "0" if kb.support_method_enabled(db, key) else "1"
        await asyncio.to_thread(db.set_setting, key, new_value)
        await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "support_contact_toggle", f"{key}={new_value}"
        )
        await safe_edit(call, SUPPORT_METHODS_HEADER, reply_markup=kb.support_contact_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_d5ebb39c', 'وضعیت تغییر کرد.'))

    @router.callback_query(F.data == "adm_set_support_contact_edit")
    async def cb_admin_set_support_contact_edit(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminSetSupportContact.waiting_id)
        await replace_admin_view(
            call,
            "آیدی عددی تلگرام مدیر را ارسال کنید (برای دریافت آیدی عددی می‌توانید از بات‌هایی مثل @userinfobot کمک بگیرید):",
            reply_markup=kb.admin_back_kb("adm_set_support_contact"),
        )
        await call.answer()

    @router.message(AdminSetSupportContact.waiting_id)
    async def process_set_support_contact(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.lstrip("-").isdigit():
            await message.answer(db.get_text('handlers_admin.auto_9f7281df', '❌ آیدی نامعتبر است. لطفاً فقط عدد آیدی عددی تلگرام را ارسال کنید.'))
            return
        (await asyncio.to_thread(db.set_setting, "support_admin_id", text))
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "support_contact_change", f"آیدی مدیر برای چت مستقیم: {text}"
        ))
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_5aeeed3a', '✅ آیدی مدیر ذخیره شد.'), reply_markup=kb.admin_panel_kb(db, is_main_bot))

    @router.callback_query(F.data == "adm_clear_support_contact")
    async def cb_admin_clear_support_contact(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        (await asyncio.to_thread(db.set_setting, "support_admin_id", ""))
        await safe_edit(call, SUPPORT_METHODS_HEADER, reply_markup=kb.support_contact_settings_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_f349f7a2', '✅ حذف شد.'))

    # -------------------------------------------------------------------
    # دستیار پشتیبانی هوش مصنوعی (سوالات متداول + روشن/خاموش)
    # -------------------------------------------------------------------

    async def _show_ai_faq_menu(call: CallbackQuery):
        items = await asyncio.to_thread(db.get_ai_faq_items)
        # این بخش عمداً در برابر تنظیمات ناقص/قدیمی DB مقاوم است؛ اگر یکی از
        # تنظیمات جدید در دیتابیس وجود نداشته باشد، باز شدن منوی مدیر نباید کرش کند.
        try:
            provider = ai_support.resolve_provider_mode(db)
        except Exception:
            provider = "auto"
        try:
            provider_label = ai_support.PROVIDER_LABELS.get(provider, ai_support.PROVIDER_LABELS.get("auto", "🤖 خودکار"))
        except Exception:
            provider_label = "🤖 خودکار"
        statuses = []
        for name, label in (("gemini", "Gemini"), ("groq", "Groq"), ("openrouter", "OpenRouter")):
            try:
                configured = bool(ai_support.resolve_provider_keys(db, name))
            except Exception:
                configured = False
            statuses.append(f"{'🟢' if configured else '⚪️'} {label}")
        try:
            gemini_model = ai_support.resolve_gemini_model(db)
        except Exception:
            gemini_model = "gemini-2.5-flash-lite"
        try:
            groq_model = ai_support.resolve_groq_model(db)
        except Exception:
            groq_model = "openai/gpt-oss-20b"
        try:
            openrouter_model = ai_support.resolve_openrouter_model(db)
        except Exception:
            openrouter_model = "openrouter/free"
        text = (
            "🤖 مدیریت دستیار هوشمند پشتیبانی\n\n"
            f"🔀 مسیر: {provider_label}\n"
            f"{' | '.join(statuses)}\n\n"
            f"🧠 Gemini: {gemini_model}\n"
            f"🚀 Groq: {groq_model}\n"
            f"🌐 OpenRouter: {openrouter_model}\n\n"
            "📖 راهنمای مدیر\n"
            "🔷 Gemini: https://aistudio.google.com/ — ورود و ساخت API Key\n"
            "🚀 Groq: https://console.groq.com/ — ورود و ساخت API Key\n"
            "🌐 OpenRouter: https://openrouter.ai/ — ورود و ساخت API Key\n\n"
            "💡 پیشنهاد: مسیر «خودکار» را بگذار تا در صورت خطای سهمیه/اختلال، Agent بعدی را امتحان کند.\n\n"
        )
        if items:
            text += "سوالات متداولی که به دستیار آموزش داده شده (برای حذف، روی 🗑 بزن):"
        else:
            text += "هنوز سوالی ثبت نشده. با «➕ افزودن سوال جدید» شروع کن."
        await replace_admin_view(call, text, reply_markup=kb.ai_faq_admin_kb(db, items))

    @router.callback_query(F.data == "adm_ai_support_settings")
    async def cb_admin_ai_support_settings(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await _show_ai_faq_menu(call)
        await call.answer()

    @router.callback_query(F.data == "adm_ai_toggle")
    async def cb_admin_ai_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current = db.get_setting("ai_support_enabled", "1")
        (await asyncio.to_thread(db.set_setting, "ai_support_enabled", "0" if current == "1" else "1"))
        await _show_ai_faq_menu(call)
        await call.answer()

    @router.callback_query(F.data == "adm_ai_set_provider")
    async def cb_admin_ai_set_provider(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, "🔀 مسیر انتخاب مدل\n\n«خودکار» بهترین حالت است: به‌ترتیب Gemini → Groq → OpenRouter را امتحان می‌کند و با خطای سهمیه/اختلال به بعدی می‌رود.", reply_markup=kb.ai_provider_choice_kb(db))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ai_provider_pick:"))
    async def cb_admin_ai_provider_pick(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        mode = call.data.split(":", 1)[1]
        if mode not in ai_support.PROVIDER_LABELS:
            return await call.answer(db.get_text('handlers_admin.auto_91c4bad2', '❌ مسیر نامعتبر'), show_alert=True)
        await asyncio.to_thread(db.set_setting, "ai_provider", mode)
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "ai_provider_change", f"مسیر Agent: {mode}")
        await _show_ai_faq_menu(call)
        await call.answer(db.get_text('handlers_admin.auto_0479b78b', '✅ ذخیره شد'))

    @router.callback_query(F.data == "adm_ai_set_model")
    async def cb_admin_ai_set_model(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(call, "🧠 انتخاب مدل\n\nبرای ۵۰۰ پیام روزانه، مدل‌های سریع را انتخاب کن. در حالت خودکار اگر Provider فعلی 429/5xx بدهد، Agent به Provider بعدی می‌رود. توضیح هر مدل کنار دکمه آمده است.", reply_markup=kb.ai_model_choice_kb(db))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ai_model_pick:"))
    async def cb_admin_ai_model_pick(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        parts = call.data.split(":", 2)
        if len(parts) != 3:
            return await call.answer(db.get_text('handlers_admin.auto_bc1a559a', '❌ مدل نامعتبر'), show_alert=True)
        provider, model = parts[1], parts[2]
        valid = {(p, m) for p, m, _ in ai_support.MODEL_CHOICES}
        if (provider, model) not in valid:
            return await call.answer(db.get_text('handlers_admin.auto_bc1a559a', '❌ مدل نامعتبر'), show_alert=True)
        key = {"gemini":"gemini_model", "groq":"groq_model", "openrouter":"openrouter_model"}[provider]
        await asyncio.to_thread(db.set_setting, key, model)
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "ai_model_change", f"{provider}: {model}")
        await replace_admin_view(call, f"✅ مدل {provider} روی «{model}» تنظیم شد.", reply_markup=kb.ai_model_choice_kb(db))
        await call.answer(db.get_text('handlers_admin.auto_0479b78b', '✅ ذخیره شد'))

    async def _show_ai_key_prompt(call, state, provider, state_cls, setting_key, title, source_env):
        current_keys = ai_support._split_keys(db.get_setting(setting_key, ""))
        masked = "\n".join(f"  {i+1}. ...{k[-4:]}" for i, k in enumerate(current_keys)) if current_keys else "❌ تنظیم نشده"
        await state.set_state(state_cls.waiting_key)
        links = {
            "GEMINI_API_KEY": "https://aistudio.google.com/",
            "GROQ_API_KEY": "https://console.groq.com/",
            "OPENROUTER_API_KEY": "https://openrouter.ai/",
        }
        link = links.get(source_env, "")
        guide = f"\n🔗 راهنما/ثبت‌نام: {link}" if link else ""
        await replace_admin_view(
            call,
            f"{title}\n\nکلید یا چند کلید را بفرست؛ هر کلید در یک خط. در صورت 429 کلید بعدی امتحان می‌شود."
            f"{guide}\n\nکلیدهای فعلی:\n{masked}\n\nبرای حذف: «حذف»\n\nENV جایگزین: {source_env}",
            reply_markup=kb.admin_back_kb("adm_ai_support_settings"),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_ai_set_key")
    async def cb_admin_ai_set_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id): return await deny_support(call)
        await _show_ai_key_prompt(call, state, "gemini", AdminSetGeminiKey, "gemini_api_key", "🔑 کلیدهای Gemini", "GEMINI_API_KEY")

    @router.callback_query(F.data == "adm_ai_set_groq_key")
    async def cb_admin_ai_set_groq_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id): return await deny_support(call)
        await _show_ai_key_prompt(call, state, "groq", AdminSetGroqKey, "groq_api_key", "🔑 کلیدهای Groq", "GROQ_API_KEY")

    @router.callback_query(F.data == "adm_ai_set_openrouter_key")
    async def cb_admin_ai_set_openrouter_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id): return await deny_support(call)
        await _show_ai_key_prompt(call, state, "openrouter", AdminSetOpenRouterKey, "openrouter_api_key", "🔑 کلیدهای OpenRouter", "OPENROUTER_API_KEY")

    @router.callback_query(F.data == "adm_translation_settings")
    async def cb_admin_translation_settings(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(
            call,
            "🌐 ترجمه خودکار\n\n"
            "ربات به‌صورت خودکار متن‌های فارسی رابط کاربری را برای زبان‌های فعال ترجمه می‌کند. "
            "برای بهترین کیفیت (ترجمه‌ای که context محصول/VPN را می‌فهمد)، یک کلید Gemini رایگان تنظیم کن؛ "
            "بدون کلید هم سیستم با ارائه‌دهنده‌های رایگان جایگزین کار می‌کند، فقط کیفیت پایین‌تر است.",
            reply_markup=kb.translation_settings_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_translation_langs")
    async def cb_admin_translation_langs(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await replace_admin_view(
            call,
            "🌍 مدیریت زبان‌ها\n\n"
            "روی وضعیت هر زبان بزن تا فعال/غیرفعال بشه. فعال‌کردن یک زبان جدید نیاز به تولید خودکار ترجمه‌هاش داره و ممکنه چند ثانیه طول بکشه. "
            "فارسی و انگلیسی همیشه فعال‌اند و قابل غیرفعال‌سازی نیستند.",
            reply_markup=kb.translation_languages_kb(db),
        )
        await call.answer()

    async def _bg_generate_language(bot, code: str, admin_id: int):
        """Keep retrying translation for `code` — combining every configured
        provider each pass — until fully complete, however long that takes,
        then flip it on and tell the admin who asked for it. No time limit:
        the admin explicitly asked for patience over giving up."""
        from translation_engine import sync_language
        from i18n import LANGUAGE_CATALOG
        delay = 30.0
        try:
            while True:
                try:
                    info = await asyncio.to_thread(sync_language, db, code, allow_network=True)
                except Exception:
                    logger.exception("زمینه‌ی تولید ترجمه‌ی زبان %s با خطا مواجه شد؛ تلاش مجدد.", code)
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.5, 300.0)
                    continue
                if info.get("status") == "busy":
                    await asyncio.sleep(delay)
                    continue
                if not info.get("missing_count"):
                    await asyncio.to_thread(db.enable_language, code, True)
                    await asyncio.to_thread(db.log_admin_action, admin_id, "language_enable", code)
                    name = LANGUAGE_CATALOG.get(code, {}).get("name", code)
                    try:
                        await bot.send_message(
                            admin_id,
                            tr(f"✅ ترجمه‌ی زبان {name} کامل شد و فعال گردید."),
                        )
                    except Exception:
                        pass
                    return
                # هنوز چیزی باقی مانده؛ کمی صبر کن و دوباره با همه‌ی ارائه‌دهنده‌های
                # پیکربندی‌شده (Gemini/OpenRouter/Google/MyMemory/LibreTranslate) تلاش کن
                await asyncio.sleep(delay)
                delay = min(delay * 1.3, 300.0)
        finally:
            _bg_lang_tasks.discard(code)

    @router.callback_query(F.data.startswith("adm_translation_lang_toggle:"))
    async def cb_admin_translation_lang_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        code = call.data.split(":", 1)[1].strip().lower()
        from i18n import LANGUAGE_CATALOG
        if code in {"fa", "en"} or code not in LANGUAGE_CATALOG:
            return await call.answer(tr("⚠️ این زبان قابل تغییر نیست."), show_alert=True)
        row = await asyncio.to_thread(db.get_language, code)
        currently_enabled = bool(row["enabled"]) if row else False
        if currently_enabled:
            await asyncio.to_thread(db.disable_language, code)
            await asyncio.to_thread(db.log_admin_action, call.from_user.id, "language_disable", code)
            await call.answer(tr("⚪️ زبان غیرفعال شد."))
        elif code in _bg_lang_tasks:
            await call.answer(tr("⏳ تولید ترجمه‌ی این زبان از قبل در حال انجام است؛ صبر کن."), show_alert=True)
            return
        else:
            _bg_lang_tasks.add(code)
            asyncio.create_task(_bg_generate_language(call.bot, code, call.from_user.id))
            await call.answer(
                tr("⏳ تولید ترجمه در پس‌زمینه شروع شد؛ هرچقدر طول بکشد (حتی چند ساعت) ادامه می‌یابد "
                   "و با ترکیب همه‌ی ارائه‌دهنده‌های فعال (از جمله LibreTranslate) تا اتمام کامل تلاش می‌کند. "
                   "بعد از تکمیل، پیام تأیید برایت ارسال می‌شود."),
                show_alert=True,
            )
        await replace_admin_view(
            call,
            "🌍 مدیریت زبان‌ها\n\n"
            "روی وضعیت هر زبان بزن تا فعال/غیرفعال بشه. فعال‌کردن یک زبان جدید نیاز به تولید خودکار ترجمه‌هاش داره و ممکنه چند ثانیه طول بکشه. "
            "فارسی و انگلیسی همیشه فعال‌اند و قابل غیرفعال‌سازی نیستند.",
            reply_markup=kb.translation_languages_kb(db),
        )

    @router.callback_query(F.data == "adm_translation_set_key")
    async def cb_admin_translation_set_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current_keys = ai_support._split_keys(db.get_setting("translation_gemini_api_key", ""))
        masked = "\n".join(f"  {i+1}. ...{k[-4:]}" for i, k in enumerate(current_keys)) if current_keys else "❌ تنظیم نشده (از .env استفاده می‌شود، اگر آنجا تنظیم شده باشد)"
        await state.set_state(AdminSetTranslationGeminiKey.waiting_key)
        await replace_admin_view(
            call,
            "🔑 کلید Gemini برای ترجمه خودکار\n\n"
            "این کلید فقط برای موتور ترجمه استفاده می‌شود و از کلید Gemini «دستیار هوشمند» کاملاً جداست؛ "
            "می‌توانی همان کلید را اینجا هم بفرستی یا کلید/quota جداگانه بسازی.\n\n"
            "🔗 ساخت کلید رایگان: https://aistudio.google.com/apikey\n\n"
            "کلید یا چند کلید را بفرست؛ هر کلید در یک خط (در صورت پر شدن سهمیه‌ی یکی، بعدی امتحان می‌شود).\n\n"
            f"کلیدهای فعلی:\n{masked}\n\n"
            "برای حذف (و بازگشت به .env یا ارائه‌دهنده‌های رایگان): «حذف»",
            reply_markup=kb.admin_back_kb("adm_translation_settings"),
        )
        await call.answer()

    @router.message(AdminSetTranslationGeminiKey.waiting_key)
    async def process_set_translation_gemini_key(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            await asyncio.to_thread(db.set_setting, "translation_gemini_api_key", "")
            await asyncio.to_thread(db.log_admin_action, message.from_user.id, "translation_gemini_key_change", "کلید حذف شد.")
            await message.answer(tr("✅ کلید حذف شد."), reply_markup=kb.translation_settings_kb(db))
            return
        keys = ai_support._split_keys(text)
        if not keys:
            await message.answer(tr("⚠️ متن نامعتبر است؛ کلید را دوباره ارسال کن یا «حذف» را بفرست."))
            await state.set_state(AdminSetTranslationGeminiKey.waiting_key)
            return
        await asyncio.to_thread(db.set_setting, "translation_gemini_api_key", "\n".join(keys))
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "translation_gemini_key_change", f"{len(keys)} کلید ذخیره شد.")
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(tr(f"✅ {len(keys)} کلید ذخیره شد. از همگام‌سازی بعدی، ترجمه‌ها با این کلید ساخته می‌شوند."), reply_markup=kb.translation_settings_kb(db))

    @router.callback_query(F.data == "adm_translation_set_openrouter_key")
    async def cb_admin_translation_set_openrouter_key(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        current_keys = ai_support._split_keys(db.get_setting("translation_openrouter_api_key", ""))
        masked = "\n".join(f"  {i+1}. ...{k[-4:]}" for i, k in enumerate(current_keys)) if current_keys else "❌ تنظیم نشده"
        await state.set_state(AdminSetTranslationOpenRouterKey.waiting_key)
        await replace_admin_view(
            call,
            "🔑 کلید OpenRouter برای ترجمه خودکار\n\n"
            "این کلید فقط برای موتور ترجمه استفاده می‌شود و از کلید OpenRouter «دستیار هوشمند» کاملاً جداست؛ "
            "می‌توانی همان کلید را اینجا هم بفرستی یا کلید جداگانه بسازی.\n\n"
            "نیازی به ساخت پروژه‌ی گوگل‌کلاود ندارد و ثبت‌نامش معمولاً بدون محدودیت منطقه‌ای انجام می‌شود.\n\n"
            "🔗 ساخت کلید رایگان: https://openrouter.ai/keys\n\n"
            "کلید یا چند کلید را بفرست؛ هر کلید در یک خط (در صورت پر شدن سهمیه‌ی یکی، بعدی امتحان می‌شود).\n\n"
            f"کلیدهای فعلی:\n{masked}\n\n"
            "برای حذف: «حذف»",
            reply_markup=kb.admin_back_kb("adm_translation_settings"),
        )
        await call.answer()

    @router.message(AdminSetTranslationOpenRouterKey.waiting_key)
    async def process_set_translation_openrouter_key(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            await asyncio.to_thread(db.set_setting, "translation_openrouter_api_key", "")
            await asyncio.to_thread(db.log_admin_action, message.from_user.id, "translation_openrouter_key_change", "کلید حذف شد.")
            await message.answer(tr("✅ کلید حذف شد."), reply_markup=kb.translation_settings_kb(db))
            return
        keys = ai_support._split_keys(text)
        if not keys:
            await message.answer(tr("⚠️ متن نامعتبر است؛ کلید را دوباره ارسال کن یا «حذف» را بفرست."))
            await state.set_state(AdminSetTranslationOpenRouterKey.waiting_key)
            return
        await asyncio.to_thread(db.set_setting, "translation_openrouter_api_key", "\n".join(keys))
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, "translation_openrouter_key_change", f"{len(keys)} کلید ذخیره شد.")
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(tr(f"✅ {len(keys)} کلید ذخیره شد. از همگام‌سازی بعدی، ترجمه‌ها با این کلید ساخته می‌شوند."), reply_markup=kb.translation_settings_kb(db))

    async def _save_ai_key(message: Message, state: FSMContext, setting_key: str, action: str):
        text = (message.text or "").strip()
        await state.clear()
        if text in ("حذف", "/حذف", "-"):
            await asyncio.to_thread(db.set_setting, setting_key, "")
            await asyncio.to_thread(db.log_admin_action, message.from_user.id, action, "کلیدها حذف شدند.")
            await message.answer(db.get_text('handlers_admin.auto_3f0ed323', '✅ کلیدها حذف شدند.'), reply_markup=kb.ai_faq_admin_kb(db, await asyncio.to_thread(db.get_ai_faq_items)))
            return
        keys = ai_support._split_keys(text)
        await asyncio.to_thread(db.set_setting, setting_key, "\n".join(keys))
        await asyncio.to_thread(db.log_admin_action, message.from_user.id, action, f"{len(keys)} کلید ذخیره شد.")
        try: await message.delete()
        except Exception: pass
        await message.answer(tr(f"✅ {len(keys)} کلید ذخیره شد."), reply_markup=kb.ai_faq_admin_kb(db, await asyncio.to_thread(db.get_ai_faq_items)))

    @router.message(AdminSetGeminiKey.waiting_key)
    async def process_set_gemini_key(message: Message, state: FSMContext):
        await _save_ai_key(message, state, "gemini_api_key", "gemini_key_change")

    @router.message(AdminSetGroqKey.waiting_key)
    async def process_set_groq_key(message: Message, state: FSMContext):
        await _save_ai_key(message, state, "groq_api_key", "groq_key_change")

    @router.message(AdminSetOpenRouterKey.waiting_key)
    async def process_set_openrouter_key(message: Message, state: FSMContext):
        await _save_ai_key(message, state, "openrouter_api_key", "openrouter_key_change")

    @router.callback_query(F.data == "adm_ai_faq_add")
    async def cb_admin_ai_faq_add(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminAIFaqAdd.waiting_question)
        await replace_admin_view(
            call,
            "❓ متن سوال را ارسال کن (همان چیزی که کاربر معمولاً می‌پرسد):",
            reply_markup=kb.admin_back_kb("adm_ai_support_settings"),
        )
        await call.answer()

    @router.message(AdminAIFaqAdd.waiting_question)
    async def process_ai_faq_question(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer(db.get_text('handlers_admin.auto_e10dd1ec', 'لطفاً متن سوال را به\u200cصورت نوشتاری ارسال کن:'))
            return
        await state.update_data(ai_faq_question=text)
        await state.set_state(AdminAIFaqAdd.waiting_answer)
        await message.answer(db.get_text('handlers_admin.auto_c4549581', '✅ حالا جواب این سوال را ارسال کن (همانی که دستیار باید بدهد):'))

    @router.message(AdminAIFaqAdd.waiting_answer)
    async def process_ai_faq_answer(message: Message, state: FSMContext):
        answer = (message.text or "").strip()
        if not answer:
            await message.answer(db.get_text('handlers_admin.auto_8656d7a9', 'لطفاً متن جواب را به\u200cصورت نوشتاری ارسال کن:'))
            return
        data = await state.get_data()
        question = data.get("ai_faq_question")
        if not question:
            await state.clear()
            await message.answer(db.get_text('handlers_admin.auto_0e29be08', '⚠️ خطایی رخ داد، دوباره تلاش کنید.'))
            return
        (await asyncio.to_thread(db.add_ai_faq_item, question, answer))
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "ai_faq_add", f"سوال جدید دستیار هوشمند: {question}"
        ))
        await state.clear()
        items = await asyncio.to_thread(db.get_ai_faq_items)
        await message.answer(
            db.get_text('handlers_admin.auto_b481fd98', '✅ سوال به دانش دستیار هوشمند اضافه شد.'),
            reply_markup=kb.ai_faq_admin_kb(db, items),
        )

    @router.callback_query(F.data.startswith("adm_ai_faq_del:"))
    async def cb_admin_ai_faq_del(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        item_id = callback_id(call.data, "adm_ai_faq_del")
        if item_id is None:
            return await call.answer(db.get_text('handlers_admin.auto_f25a5f7a', '⚠️ درخواست نامعتبر است.'), show_alert=True)
        if (await asyncio.to_thread(db.get_ai_faq_item, item_id)) is None:
            await call.answer(db.get_text('handlers_admin.auto_ebd7db09', 'این سوال قبلاً حذف شده.'), show_alert=True)
            await _show_ai_faq_menu(call)
            return
        (await asyncio.to_thread(db.delete_ai_faq_item, item_id))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "ai_faq_delete", f"حذف سوال #{item_id}"))
        await _show_ai_faq_menu(call)
        await call.answer(db.get_text('handlers_admin.auto_d89f1ae4', '🗑 حذف شد.'))

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
    # برترین خریداران (بر اساس مجموع خرید تاییدشده)
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_stats_top_buyers")
    async def cb_admin_stats_top_buyers(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        rows, _total = await asyncio.to_thread(db.search_users, "", "all", 10, 0, "purchase")
        rows = [r for r in rows if int(r["total_purchase"] or 0) > 0]
        if not rows:
            body = "هنوز هیچ خرید تاییدشده‌ای ثبت نشده."
        else:
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            lines = []
            for i, r in enumerate(rows, 1):
                label = f"@{r['username']}" if r["username"] else (r["first_name"] or str(r["telegram_id"]))
                lines.append(f"{medals.get(i, str(i) + '.')} {label} ({r['telegram_id']}) — {int(r['total_purchase']):,} تومان")
            body = "\n".join(lines)
        await replace_admin_view(
            call, f"🏆 برترین خریداران (۱۰ نفر برتر بر اساس مجموع خرید تاییدشده)\n\n{body}",
            reply_markup=kb.admin_back_kb("adm_stats"),
        )
        await call.answer()

    # -------------------------------------------------------------------
    # آمار دقیق کاربران ربات
    # -------------------------------------------------------------------

    def _fmt_user_stats_breakdown(stats: dict) -> str:
        return (
            "👥 آمار دقیق کاربران ربات\n\n"
            f"👤 کل کاربران: {stats['total']:,}\n"
            f"⚪️ غیرفعال (بدون خرید تاییدشده): {stats['inactive']:,}\n"
            f"🛒 خریدار: {stats['buyers']:,}\n"
            f"🚫 مسدود: {stats['blocked']:,}\n"
            f"🧪 تست‌کننده: {stats['testers']:,}\n"
            f"🤝 نماینده: {stats['resellers']:,}\n\n"
            "توجه: دسته‌ها مستقل‌اند و ممکن است هم‌پوشانی داشته باشند (مثلاً نماینده‌ای که خریدار هم هست)."
        )

    @router.callback_query(F.data == "adm_stats_users_breakdown")
    async def cb_admin_stats_users_breakdown(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        stats = await asyncio.to_thread(db.get_user_stats_breakdown)
        await replace_admin_view(call, _fmt_user_stats_breakdown(stats), reply_markup=kb.admin_back_kb("adm_stats"))
        await call.answer()

    # -------------------------------------------------------------------
    # آمار پیشرفته: روند فروش، درگاه‌های پرداخت، کمپین‌ها/نماینده‌ها، قیف تبدیل
    # -------------------------------------------------------------------

    def _fmt_advanced_stats_report(stats: dict) -> str:
        s, e = to_jalali_str(stats["start_date"]), to_jalali_str(stats["end_date"])
        lines = [f"📈 آمار پیشرفته ({s} تا {e})\n"]

        trend = stats["revenue_trend"]["points"]
        lines.append("📊 روند درآمد روزانه:")
        if trend:
            for p in trend[-10:]:
                bar = "▮" * min(20, max(1, p["revenue"] // max(1, max(t["revenue"] for t in trend) // 20 or 1)))
                lines.append(f"  {p['bucket']}: {p['revenue']:,} تومان ({p['orders']} سفارش) {bar}")
        else:
            lines.append("  داده‌ای در این بازه نیست.")

        lines.append("\n💳 تفکیک درگاه‌های پرداخت:")
        if stats["gateway_breakdown"]:
            for g in stats["gateway_breakdown"]:
                lines.append(
                    f"  • {g['gateway']}: {g['revenue']:,} تومان | {g['success']}/{g['attempts']} موفق "
                    f"({g['success_rate']}٪) | {g['failed']} ناموفق"
                )
        else:
            lines.append("  تراکنشی ثبت نشده.")

        lines.append("\n🎯 منابع ورودی کاربر (کمپین‌ها):")
        if stats["campaign_performance"]:
            for c in stats["campaign_performance"][:8]:
                lines.append(
                    f"  • {c['source']}: {c['new_users']:,} کاربر جدید → {c['buyers']:,} خریدار "
                    f"({c['conversion_rate']}٪) | {c['revenue']:,} تومان"
                )
        else:
            lines.append("  داده‌ای نیست.")

        if stats["reseller_performance"]:
            lines.append("\n🤝 عملکرد نمایندگان داخلی (لینک اختصاصی):")
            for r in stats["reseller_performance"][:8]:
                pct = f"{r['commission_percent']}٪" if r["commission_percent"] is not None else "—"
                lines.append(
                    f"  • {r['name']}: {r['orders']:,} فروش از {r['customers']:,} مشتری، "
                    f"{r['revenue']:,} تومان | کمیسیون {pct}: {r['commission_paid']:,} تومان"
                )

        f = stats["funnel"]
        lines.append("\n🔻 قیف تبدیل کاربران تازه‌وارد:")
        lines.append(f"  🆕 عضو شدند: {f['new_users']:,}")
        lines.append(f"  🛒 سفارش ثبت کردند: {f['attempted_purchase']:,} ({f['start_to_attempt_rate']}٪)")
        lines.append(f"  ✅ خرید موفق: {f['completed_purchase']:,} (از سفارش‌دهنده‌ها {f['attempt_to_purchase_rate']}٪)")
        lines.append(f"  📈 نرخ تبدیل کلی: {f['overall_conversion_rate']}٪")

        rt = stats["retention"]
        lines.append("\n🔁 وفاداری مشتری:")
        lines.append(f"  🔁 بازگشتی در این بازه: {rt['returning_customers']:,}")
        lines.append(f"  🆕 اولین خرید در این بازه: {rt['first_time_customers']:,}")
        lines.append(f"  ⚠️ ریزش‌کرده (بدون خرید در {rt['churn_window_days']} روز اخیر): {rt['churned_customers']:,}")

        heat = stats["hourly_heatmap"]
        day_names = ["شنبه", "یک‌شنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
        # sqlite %w: یکشنبه=۰..شنبه=۶ → نگاشت به ترتیب هفته‌ی ایرانی
        sqlite_to_fa = {0: "یک‌شنبه", 1: "دوشنبه", 2: "سه‌شنبه", 3: "چهارشنبه", 4: "پنج‌شنبه", 5: "جمعه", 6: "شنبه"}
        totals_by_day = [(sqlite_to_fa[i], sum(heat[i])) for i in range(7)]
        totals_by_hour = [sum(heat[d][h] for d in range(7)) for h in range(24)]
        if any(t for _, t in totals_by_day):
            best_day = max(totals_by_day, key=lambda x: x[1])
            best_hour = max(range(24), key=lambda h: totals_by_hour[h])
            lines.append("\n⏰ شلوغ‌ترین زمان‌ها (به وقت تهران):")
            lines.append(f"  📅 پرفروش‌ترین روز هفته: {best_day[0]} ({best_day[1]:,} سفارش)")
            lines.append(f"  🕐 پرفروش‌ترین ساعت: {best_hour:02d}:00 تا {best_hour+1:02d}:00 ({totals_by_hour[best_hour]:,} سفارش)")

        return "\n".join(lines)

    @router.callback_query(F.data.startswith("adm_stats_adv:"))
    async def cb_admin_stats_advanced(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        days = int(call.data.split(":", 1)[1])
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=days - 1)).isoformat()
        stats = await asyncio.to_thread(db.get_advanced_stats, start_date, end_date)
        await replace_admin_view(call, _fmt_advanced_stats_report(stats), reply_markup=kb.admin_advanced_stats_kb(days))
        await call.answer()

    # -------------------------------------------------------------------
    # آمار کامل یک کاربر خاص
    # -------------------------------------------------------------------

    def _fmt_user_full_stats_report(stats: dict) -> str:
        u = stats["user"]
        name = u["first_name"] or (f"@{u['username']}" if u["username"] else str(u["telegram_id"]))
        status_labels = {"blocked": "🚫 مسدود", "active": "🟢 دارای سرویس فعال", "expired": "🟡 سرویس‌های منقضی", "none": "⚪️ بدون سابقه‌ی سرویس"}
        lines = [
            f"🔍 آمار کامل کاربر {name}\n",
            f"🆔 آیدی عددی: {u['telegram_id']}",
            f"یوزرنیم: @{u['username']}" if u["username"] else "یوزرنیم: ندارد",
            f"تاریخ عضویت: {to_jalali_str(u['joined_at'])}",
            f"وضعیت: {status_labels.get(stats['status'], stats['status'])}",
            f"\n💰 موجودی کیف‌پول: {u['referral_credit']:,} تومان",
            f"🛒 سفارش‌های تاییدشده: {stats['approved_orders']:,} به مبلغ {stats['total_spent']:,} تومان",
            f"⏳ سفارش‌های در انتظار: {stats['pending_orders']:,}",
            f"❌ سفارش‌های ردشده: {stats['rejected_orders']:,}",
            f"💳 مجموع شارژ تاییدشده‌ی حساب: {stats['total_topup']:,} تومان",
            f"📡 تعداد کانفیگ فعال: {stats['active_configs']:,}",
            f"\n👥 تعداد زیرمجموعه (رفرال): {stats['referral_count']:,}",
        ]
        if stats["is_reseller"]:
            lines.append(f"🤝 نماینده است (سطح: {stats['agent_tier'] or '—'})")
        return "\n".join(lines)

    @router.callback_query(F.data == "adm_stats_user")
    async def cb_admin_stats_user(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminUserFullStats.waiting_identifier)
        await replace_admin_view(
            call,
            "آیدی عددی تلگرام یا یوزرنیم کاربر را بفرست.",
            reply_markup=kb.admin_back_kb("adm_stats"),
        )
        await call.answer()

    @router.message(AdminUserFullStats.waiting_identifier)
    async def process_admin_stats_user(message: Message, state: FSMContext):
        identifier = (message.text or "").strip()
        user = await asyncio.to_thread(db.find_user_by_identifier, identifier)
        if not user:
            await message.answer(db.get_text('handlers_admin.auto_60e70b77', 'کاربری با این مشخصات پیدا نشد. دوباره بفرست.'))
            return
        stats = await asyncio.to_thread(db.get_user_full_stats, user["telegram_id"])
        await state.clear()
        is_blocked = (user["is_blocked"] if "is_blocked" in user.keys() else 0) == 1
        await message.answer(_fmt_user_full_stats_report(stats), reply_markup=kb.user_full_stats_kb(user["telegram_id"], is_blocked))

    def _fmt_user_configs_report(tg_id: int, custom_configs: list, bank_configs: list) -> str:
        if not custom_configs and not bank_configs:
            return f"📦 کاربر {tg_id} هیچ کانفیگ خریداری‌شده‌ای ندارد.\n\n📡 تعداد کانفیگ فعال: ۰"
        now = datetime.utcnow()
        active_count = 0
        for cc in custom_configs:
            if cc["status"] == "active" and cc["source"] != "test":
                active_count += 1
        for c in bank_configs:
            used = bool(c["is_used"]) if "is_used" in c.keys() else False
            disabled = bool(c["is_disabled"]) if "is_disabled" in c.keys() else False
            expires_at = c["expires_at"] if "expires_at" in c.keys() else None
            if used and not disabled and (not expires_at or expires_at > now.isoformat()):
                active_count += 1
        lines = [f"📦 کل کانفیگ‌های خریداری‌شده‌ی کاربر {tg_id}", f"📡 تعداد کانفیگ فعال: {active_count:,}\n"]
        if custom_configs:
            lines.append(f"🛠 سرویس‌های مستقیم‌-پنل ({len(custom_configs)}):")
            for cc in custom_configs:
                name = cc["display_name"] or cc["username"]
                enabled = (cc["enabled"] if "enabled" in cc.keys() else 1) == 1
                auto_renew = (cc["auto_renew"] if "auto_renew" in cc.keys() else 0) == 1
                status = "🟢 فعال" if enabled else "🔴 غیرفعال"
                kind = "🧪 تست" if cc["source"] == "test" else "🛠 پنلی"
                lines.append(
                    f"  • «{name}» | {kind} | {cc['volume_gb']:g} گیگ / {cc['duration_days']:g} روز | "
                    f"{status} | تمدید خودکار: {'✅' if auto_renew else '◻️'} | "
                    f"انقضا: {to_jalali_str(cc['expires_at']) if cc['expires_at'] else '—'}"
                )
        if bank_configs:
            lines.append(f"\n🏦 کانفیگ‌های بانک محصول ({len(bank_configs)}):")
            for c in bank_configs:
                used = bool(c["is_used"]) if "is_used" in c.keys() else False
                disabled = bool(c["is_disabled"]) if "is_disabled" in c.keys() else False
                status = "🔴 غیرفعال" if disabled else ("⚪️ استفاده‌شده" if used else "🟢 فعال")
                lines.append(
                    f"  • {c['product_name'] or 'نامشخص'} | سفارش #{c['order_display_id'] or '—'} | "
                    f"{status} | اختصاص: {to_jalali_str(c['assigned_at']) if c['assigned_at'] else '—'} | "
                    f"انقضا: {to_jalali_str(c['expires_at']) if ('expires_at' in c.keys() and c['expires_at']) else '—'}"
                )
        return "\n".join(lines)

    @router.callback_query(F.data.startswith("adm_user_configs:"))
    async def cb_admin_user_configs(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_configs")
        if tg_id is None:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'کاربر یافت نشد.'), show_alert=True)
            return
        user = await asyncio.to_thread(db.get_user, tg_id)
        if not user:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'کاربر یافت نشد.'), show_alert=True)
            return
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        bank_configs = await asyncio.to_thread(db.get_bank_configs_for_user, tg_id)
        text = _fmt_user_configs_report(tg_id, custom_configs, bank_configs)
        for chunk_start in range(0, len(text), 3500):
            await call.message.answer(text[chunk_start:chunk_start + 3500])
        is_blocked = (user["is_blocked"] if "is_blocked" in user.keys() else 0) == 1
        await call.message.answer(tr(f"🔍 آمار کامل کاربر {tg_id}"), reply_markup=kb.user_full_stats_kb(tg_id, is_blocked))
        await call.answer()

    def _eligible_configs_for_bulk_toggle(custom_configs: list) -> list:
        # فقط سرویس‌های مستقیم‌-پنل (غیر تست) که به یک سرور پنل وصل‌اند، برای این عملیات دسته‌جمعی در نظر گرفته می‌شوند
        return [cc for cc in custom_configs if cc["source"] != "test" and cc["panel_server_id"]]

    @router.callback_query(F.data.startswith("adm_user_toggle_all:"))
    async def cb_admin_user_toggle_all_ask(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_toggle_all")
        if tg_id is None:
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'کاربر یافت نشد.'), show_alert=True)
            return
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        eligible = _eligible_configs_for_bulk_toggle(custom_configs)
        if not eligible:
            await call.answer(tr("این کاربر هیچ سرویس مستقیم‌-پنلی (غیر تست) ندارد که بشود دسته‌جمعی فعال/غیرفعال کرد."), show_alert=True)
            return
        enabled_count = sum(1 for cc in eligible if (cc["enabled"] if "enabled" in cc.keys() else 1) == 1)
        # اگر حتی یکی فعال باشد، عملیات یعنی «غیرفعال کردن همه»؛ وگرنه یعنی «فعال کردن همه»
        new_enabled = enabled_count == 0
        action_text = "فعال" if new_enabled else "غیرفعال"
        await call.message.answer(
            tr(f"⏻ {len(eligible)} سرویس مستقیم‌-پنل (غیر تست) برای کاربر {tg_id} پیدا شد "
            f"({enabled_count} فعال، {len(eligible) - enabled_count} غیرفعال).\n\n"
            f"با تایید، همه‌ی این {len(eligible)} سرویس روی پنل‌های مربوطه، «{action_text}» می‌شوند.\n"
            "⚠️ توجه: این کار روی خود پنل هم اعمال می‌شود."),
            reply_markup=kb.user_toggle_all_confirm_kb(tg_id, new_enabled),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_user_toggle_all_go:"))
    async def cb_admin_user_toggle_all_go(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, flag_s = call.data.split(":", 2)
            tg_id = int(tg_id_s)
            new_enabled = flag_s == "1"
        except (ValueError, IndexError):
            await call.answer(db.get_text('handlers_admin.auto_8ee026d7', 'کاربر یافت نشد.'), show_alert=True)
            return
        await call.answer(tr("در حال اعمال تغییرات..."))
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        eligible = _eligible_configs_for_bulk_toggle(custom_configs)
        ok_count = 0
        fail_names = []
        for cc in eligible:
            current_enabled = (cc["enabled"] if "enabled" in cc.keys() else 1) == 1
            if current_enabled == new_enabled:
                ok_count += 1
                continue
            name = cc["display_name"] or cc["username"]
            server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
            if not server or not server["is_active"]:
                fail_names.append(f"{name} (سرور پنل یافت نشد/غیرفعال)")
                continue
            try:
                provider = get_provider(server)
                await provider.set_enabled(cc["username"], new_enabled)
            except PanelError as e:
                fail_names.append(f"{name} ({e})")
                continue
            (await asyncio.to_thread(db.set_custom_config_enabled, cc["id"], tg_id, new_enabled))
            (await asyncio.to_thread(
                db.add_custom_config_history, cc["id"], "toggle",
                f"{'فعال شد' if new_enabled else 'غیرفعال شد'} (دسته‌جمعی توسط ادمین)",
            ))
            ok_count += 1
        (await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "user_bulk_toggle_configs",
            f"کاربر {tg_id} ← {'فعال' if new_enabled else 'غیرفعال'} ({ok_count}/{len(eligible)})",
        ))
        action_text = "فعال" if new_enabled else "غیرفعال"
        lines = [f"✅ عملیات دسته‌جمعی انجام شد: {ok_count} از {len(eligible)} سرویس کاربر {tg_id} «{action_text}» شدند."]
        if fail_names:
            lines.append("\n❌ موارد ناموفق:")
            lines.extend(f"  • {n}" for n in fail_names[:20])
        user = await asyncio.to_thread(db.get_user, tg_id)
        is_blocked = bool(user and (user["is_blocked"] if "is_blocked" in user.keys() else 0) == 1)
        await call.message.answer("\n".join(lines), reply_markup=kb.user_full_stats_kb(tg_id, is_blocked))

    # -------------------------------------------------------------------
    # مدیریت کامل کاربر: ارسال پیام مستقیم، کد تخفیف اختصاصی، بلاک/آنبلاک،
    # ویرایش موجودی کیف‌پول
    # -------------------------------------------------------------------

    async def _show_user_menu(message: Message, tg_id: int, note: str = None):
        user = await asyncio.to_thread(db.get_user, tg_id)
        if not user:
            await message.answer(tr("کاربر یافت نشد."))
            return
        stats = await asyncio.to_thread(db.get_user_full_stats, tg_id)
        is_blocked = (user["is_blocked"] if "is_blocked" in user.keys() else 0) == 1
        text = _fmt_user_full_stats_report(stats)
        if note:
            text = note + "\n\n" + text
        await message.answer(text, reply_markup=kb.user_full_stats_kb(tg_id, is_blocked))

    @router.callback_query(F.data.startswith("adm_user_view:"))
    async def cb_admin_user_view(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_view")
        if tg_id is None:
            await call.answer(tr("کاربر یافت نشد."), show_alert=True)
            return
        await state.clear()
        await _show_user_menu(call.message, tg_id)
        await call.answer()

    # ---- ارسال پیام مستقیم به کاربر ----

    @router.callback_query(F.data.startswith("adm_user_msg:"))
    async def cb_admin_user_msg_ask(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_msg")
        if tg_id is None:
            await call.answer(tr("کاربر یافت نشد."), show_alert=True)
            return
        await state.set_state(AdminUserManage.waiting_message_text)
        await state.update_data(target_user_id=tg_id)
        await call.message.answer(
            tr(f"✉️ متن پیام برای کاربر {tg_id} را ارسال کنید (فرمت‌بندی حفظ می‌شود):"),
            reply_markup=kb.admin_back_kb(f"adm_user_view:{tg_id}"),
        )
        await call.answer()

    @router.message(AdminUserManage.waiting_message_text)
    async def process_admin_user_msg(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        tg_id = data.get("target_user_id")
        await state.clear()
        if not tg_id:
            return
        html_text = message.html_text if message.text else ""
        try:
            await bot.send_message(tg_id, tr(f"📩 پیام از پشتیبانی:\n\n{html_text}"))
            await _notify_user_inline_menu(bot, tg_id)
            (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "user_direct_message", f"کاربر {tg_id}"))
            await _show_user_menu(message, tg_id, "✅ پیام ارسال شد.")
        except Exception:
            await _show_user_menu(message, tg_id, "⛔️ ارسال پیام ناموفق بود.")

    # ---- بلاک/آنبلاک کاربر ----

    @router.callback_query(F.data.startswith("adm_user_toggleblock:"))
    async def cb_admin_user_toggleblock(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_toggleblock")
        if tg_id is None:
            await call.answer(tr("کاربر یافت نشد."), show_alert=True)
            return
        user = await asyncio.to_thread(db.get_user, tg_id)
        if not user:
            await call.answer(tr("کاربر یافت نشد."), show_alert=True)
            return
        new_blocked = not ((user["is_blocked"] if "is_blocked" in user.keys() else 0) == 1)
        await asyncio.to_thread(db.set_user_blocked, tg_id, new_blocked)
        (await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "user_block_toggle",
            f"کاربر {tg_id} ← {'بلاک' if new_blocked else 'آنبلاک'}",
        ))
        note = "🚫 کاربر بلاک شد." if new_blocked else "✅ کاربر آنبلاک شد."
        await call.answer(tr(note))
        await _show_user_menu(call.message, tg_id, note)

    # ---- ویرایش موجودی کیف‌پول ----

    @router.callback_query(F.data.startswith("adm_user_wallet:"))
    async def cb_admin_user_wallet_ask(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_wallet")
        if tg_id is None:
            await call.answer(tr("کاربر یافت نشد."), show_alert=True)
            return
        await state.set_state(AdminUserManage.waiting_wallet_amount)
        await state.update_data(target_user_id=tg_id)
        await call.message.answer(
            tr(
                "💰 مبلغ تغییر موجودی کیف‌پول را به تومان ارسال کنید.\n"
                "برای افزایش عدد مثبت (مثلاً 50000) و برای کاهش عدد منفی (مثلاً -50000) بفرستید."
            ),
            reply_markup=kb.admin_back_kb(f"adm_user_view:{tg_id}"),
        )
        await call.answer()

    @router.message(AdminUserManage.waiting_wallet_amount)
    async def process_admin_user_wallet(message: Message, state: FSMContext):
        data = await state.get_data()
        tg_id = data.get("target_user_id")
        text = (message.text or "").strip().replace(",", "")
        try:
            amount = int(text)
        except ValueError:
            await message.answer(tr("⚠️ فقط یک عدد صحیح ارسال کنید (مثبت یا منفی)."))
            return
        if not tg_id:
            await state.clear()
            return
        if amount == 0:
            await message.answer(tr("⚠️ مبلغ نمی‌تواند صفر باشد."))
            return
        new_balance = await asyncio.to_thread(
            db.admin_adjust_wallet, tg_id, amount, f"تنظیم دستی توسط ادمین ({message.from_user.id})"
        )
        await state.clear()
        if new_balance is None:
            await message.answer(tr("❌ کاربر یافت نشد."))
            return
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "user_wallet_adjust",
            f"کاربر {tg_id} | تغییر: {amount:,} | موجودی جدید: {new_balance:,}",
        ))
        note = f"✅ موجودی کیف‌پول {'افزایش' if amount > 0 else 'کاهش'} یافت. موجودی جدید: {new_balance:,} تومان"
        await _show_user_menu(message, tg_id, note)

    # ---- کد تخفیف اختصاصی ----

    @router.callback_query(F.data.startswith("adm_user_disc:"))
    async def cb_admin_user_disc_ask(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_disc")
        if tg_id is None:
            await call.answer(tr("کاربر یافت نشد."), show_alert=True)
            return
        await state.set_state(AdminUserManage.waiting_discount_type_value)
        await state.update_data(target_user_id=tg_id)
        await call.message.answer(
            tr(
                "🎁 نوع و مقدار تخفیف اختصاصی این کاربر را ارسال کنید:\n\n"
                "برای تخفیف درصدی: `percent 20`\nبرای تخفیف مبلغ ثابت: `fixed 50000`"
            ),
            parse_mode="Markdown",
            reply_markup=kb.admin_back_kb(f"adm_user_view:{tg_id}"),
        )
        await call.answer()

    @router.message(AdminUserManage.waiting_discount_type_value)
    async def process_admin_user_disc_type_value(message: Message, state: FSMContext):
        parts = message.text.strip().split()
        if len(parts) != 2 or parts[0].lower() not in ("percent", "fixed") or not parts[1].isdigit():
            await message.answer(tr("فرمت اشتباه است. مثال درست: `percent 20` یا `fixed 50000`"), parse_mode="Markdown")
            return
        kind, value = parts[0].lower(), int(parts[1])
        if kind == "percent":
            await state.update_data(disc_percent=value, disc_fixed=None)
        else:
            await state.update_data(disc_percent=None, disc_fixed=value)
        await state.set_state(AdminUserManage.waiting_discount_expiry)
        await message.answer(tr("چند روز دیگر این کد منقضی شود؟ (برای بدون انقضا عدد 0 را بفرست)"))

    @router.message(AdminUserManage.waiting_discount_expiry)
    async def process_admin_user_disc_expiry(message: Message, state: FSMContext, bot: Bot):
        if not message.text.strip().isdigit():
            await message.answer(tr("لطفاً فقط عدد روز ارسال کنید (0 برای بدون انقضا)."))
            return
        days = int(message.text.strip())
        data = await state.get_data()
        tg_id = data.get("target_user_id")
        percent = data.get("disc_percent")
        fixed_amount = data.get("disc_fixed")
        await state.clear()
        if not tg_id:
            return
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat() if days > 0 else None
        pairs = await asyncio.to_thread(
            db.generate_bulk_discount_codes, [tg_id], percent, fixed_amount, expires_at
        )
        if not pairs:
            await message.answer(tr("⚠️ ساخت کد ناموفق بود؛ دوباره تلاش کن."))
            return
        _, code = pairs[0]
        value_txt = f"{percent}%" if percent else f"{fixed_amount:,} تومان"
        expiry_txt = f"تا {to_jalali_str(datetime.fromisoformat(expires_at))} معتبر است" if expires_at else "بدون تاریخ انقضا"
        text = (
            "🎁 یک کد تخفیف اختصاصی برای شما صادر شد!\n\n"
            f"🎟 کد: `{code}`\n💰 تخفیف: {value_txt}\n⏳ {expiry_txt}\n\n"
            "این کد فقط یک‌بار و فقط برای شما قابل استفاده است."
        )
        try:
            await send_telegram(bot, db, tg_id, text, parse_mode="Markdown")
            await _notify_user_inline_menu(bot, tg_id)
            sent_note = f"✅ کد «{code}» ساخته و برای کاربر ارسال شد."
        except Exception:
            sent_note = f"⚠️ کد «{code}» ساخته شد ولی ارسال آن به کاربر ناموفق بود."
        (await asyncio.to_thread(
            db.log_admin_action, message.from_user.id, "user_exclusive_discount",
            f"کاربر {tg_id} | کد «{code}» | تخفیف: {value_txt}",
        ))
        await _show_user_menu(message, tg_id, sent_note)

    # -------------------------------------------------------------------
    # مدیریت تک‌تک کانفیگ‌های یک کاربر (فعال/غیرفعال، تمدید خودکار، تغییر
    # نام، انتقال، تاریخچه) - مشابه چیزی که مشتری برای سرویس خودش دارد
    # -------------------------------------------------------------------

    def _admin_manageable_configs(custom_configs: list) -> list:
        # فقط سرویس‌های مستقیم‌-پنل (غیر تست) - مثل محدوده‌ی فعال/غیرفعال دسته‌جمعی
        return [cc for cc in custom_configs if cc["source"] != "test"]

    @router.callback_query(F.data.startswith("adm_user_cfglist:"))
    async def cb_admin_user_cfglist(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        tg_id = callback_id(call.data, "adm_user_cfglist")
        if tg_id is None:
            await call.answer(tr("کاربر یافت نشد."), show_alert=True)
            return
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        manageable = _admin_manageable_configs(custom_configs)
        if not manageable:
            await call.answer(tr("این کاربر هیچ سرویس مستقیم‌-پنلی (غیر تست) ندارد."), show_alert=True)
            return
        await call.message.answer(
            tr(f"🛠 مدیریت تک‌تک کانفیگ‌های کاربر {tg_id} — یکی را انتخاب کن:"),
            reply_markup=kb.admin_user_config_list_kb(tg_id, manageable),
        )
        await call.answer()

    async def _show_config_detail(message: Message, tg_id: int, cc_id: int, note: str = None):
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        cc = next((c for c in custom_configs if c["id"] == cc_id), None)
        if not cc:
            await message.answer(tr("این کانفیگ دیگر یافت نشد."))
            return
        enabled = (cc["enabled"] if "enabled" in cc.keys() else 1) == 1
        auto_renew = (cc["auto_renew"] if "auto_renew" in cc.keys() else 0) == 1
        can_auto_renew = (cc["duration_days"] or 0) > 0
        name = cc["display_name"] or cc["username"]
        lines = [
            f"🛠 کانفیگ «{name}» (کاربر {tg_id})",
            f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}",
            (f"تمدید خودکار: {'✅ فعال' if auto_renew else '◻️ غیرفعال'}" if can_auto_renew
             else "تمدید خودکار: نامحدود (نیازی نیست)"),
            f"حجم/مدت: {cc['volume_gb']:g} گیگ / {cc['duration_days']:g} روز",
            f"انقضا: {to_jalali_str(cc['expires_at']) if cc['expires_at'] else '—'}",
        ]
        text = "\n".join(lines)
        if note:
            text = note + "\n\n" + text
        await message.answer(
            text, reply_markup=kb.admin_config_detail_kb(tg_id, cc_id, enabled, auto_renew, can_auto_renew)
        )

    @router.callback_query(F.data.startswith("adm_cfg_view:"))
    async def cb_admin_cfg_view(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, cc_id_s = call.data.split(":", 2)
            tg_id, cc_id = int(tg_id_s), int(cc_id_s)
        except ValueError:
            await call.answer(tr("کانفیگ یافت نشد."), show_alert=True)
            return
        await state.clear()
        await _show_config_detail(call.message, tg_id, cc_id)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_cfg_toggle:"))
    async def cb_admin_cfg_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, cc_id_s = call.data.split(":", 2)
            tg_id, cc_id = int(tg_id_s), int(cc_id_s)
        except ValueError:
            await call.answer(tr("کانفیگ یافت نشد."), show_alert=True)
            return
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        cc = next((c for c in custom_configs if c["id"] == cc_id), None)
        if not cc:
            await call.answer(tr("این کانفیگ یافت نشد."), show_alert=True)
            return
        new_enabled = not ((cc["enabled"] if "enabled" in cc.keys() else 1) == 1)
        server = (await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])) if cc["panel_server_id"] else None
        if not server or not server["is_active"]:
            await call.answer(tr("سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است."), show_alert=True)
            return
        try:
            provider = get_provider(server)
            await provider.set_enabled(cc["username"], new_enabled)
        except PanelError as e:
            await call.answer(tr(f"⛔️ ناموفق بود: {e}"), show_alert=True)
            return
        (await asyncio.to_thread(db.set_custom_config_enabled, cc_id, tg_id, new_enabled))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc_id, "toggle",
            f"{'فعال شد' if new_enabled else 'غیرفعال شد'} (توسط ادمین {call.from_user.id})",
        ))
        await call.answer(tr("✅ وضعیت بروزرسانی شد."))
        await _show_config_detail(call.message, tg_id, cc_id)

    @router.callback_query(F.data.startswith("adm_cfg_autorenew:"))
    async def cb_admin_cfg_autorenew(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, cc_id_s = call.data.split(":", 2)
            tg_id, cc_id = int(tg_id_s), int(cc_id_s)
        except ValueError:
            await call.answer(tr("کانفیگ یافت نشد."), show_alert=True)
            return
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        cc = next((c for c in custom_configs if c["id"] == cc_id), None)
        if not cc:
            await call.answer(tr("این کانفیگ یافت نشد."), show_alert=True)
            return
        if (cc["duration_days"] or 0) <= 0:
            await call.answer(tr("این کانفیگ نامحدود است و نیازی به تمدید خودکار ندارد."), show_alert=True)
            return
        new_val = not ((cc["auto_renew"] if "auto_renew" in cc.keys() else 0) == 1)
        (await asyncio.to_thread(db.set_custom_config_auto_renew, cc_id, tg_id, new_val))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc_id, "auto_renew_toggle",
            f"{'فعال شد' if new_val else 'غیرفعال شد'} (توسط ادمین {call.from_user.id})",
        ))
        await call.answer(tr("✅ بروزرسانی شد."))
        await _show_config_detail(call.message, tg_id, cc_id)

    @router.callback_query(F.data.startswith("adm_cfg_rename:"))
    async def cb_admin_cfg_rename_ask(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, cc_id_s = call.data.split(":", 2)
            tg_id, cc_id = int(tg_id_s), int(cc_id_s)
        except ValueError:
            await call.answer(tr("کانفیگ یافت نشد."), show_alert=True)
            return
        await state.set_state(AdminConfigManage.waiting_rename)
        await state.update_data(target_user_id=tg_id, target_cc_id=cc_id)
        await call.message.answer(
            tr("✏️ نام جدید کانفیگ را ارسال کنید. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر."),
            reply_markup=kb.admin_back_kb(f"adm_cfg_view:{tg_id}:{cc_id}"),
        )
        await call.answer()

    @router.message(AdminConfigManage.waiting_rename)
    async def process_admin_cfg_rename(message: Message, state: FSMContext):
        data = await state.get_data()
        tg_id, cc_id = data.get("target_user_id"), data.get("target_cc_id")
        new_label = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", new_label):
            await message.answer(tr("❌ نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر."))
            return
        if not tg_id or not cc_id:
            await state.clear()
            return
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        cc = next((c for c in custom_configs if c["id"] == cc_id), None)
        if not cc:
            await state.clear()
            await message.answer(tr("این کانفیگ دیگر یافت نشد."))
            return
        current_label = cc["display_name"] or cc["username"]
        if new_label == current_label:
            await message.answer(tr("این نام همان نام فعلی است."))
            return
        if (await asyncio.to_thread(db.is_custom_username_taken, new_label)):
            await message.answer(tr("❌ این نام قبلاً استفاده شده. نام دیگری بفرست."))
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
        (await asyncio.to_thread(db.rename_custom_config, cc_id, tg_id, new_label, panel_username))
        (await asyncio.to_thread(
            db.add_custom_config_history, cc_id, "rename",
            f"{current_label} ← {new_label} {note} (توسط ادمین {message.from_user.id})",
        ))
        await state.clear()
        await _show_config_detail(message, tg_id, cc_id, f"✅ نام کانفیگ به «{new_label}» تغییر کرد. {note}")

    @router.callback_query(F.data.startswith("adm_cfg_transfer:"))
    async def cb_admin_cfg_transfer_ask(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, cc_id_s = call.data.split(":", 2)
            tg_id, cc_id = int(tg_id_s), int(cc_id_s)
        except ValueError:
            await call.answer(tr("کانفیگ یافت نشد."), show_alert=True)
            return
        await state.set_state(AdminConfigManage.waiting_transfer_target)
        await state.update_data(target_user_id=tg_id, target_cc_id=cc_id)
        await call.message.answer(
            tr("👤 آی‌دی عددی تلگرام کاربر مقصد را ارسال کنید (آن کاربر باید قبلاً بات را استارت کرده باشد)."),
            reply_markup=kb.admin_back_kb(f"adm_cfg_view:{tg_id}:{cc_id}"),
        )
        await call.answer()

    @router.message(AdminConfigManage.waiting_transfer_target)
    async def process_admin_cfg_transfer_target(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(tr("❌ فقط آی‌دی عددی تلگرام را ارسال کنید."))
            return
        target_id = int(text)
        data = await state.get_data()
        tg_id, cc_id = data.get("target_user_id"), data.get("target_cc_id")
        if not tg_id or not cc_id:
            await state.clear()
            return
        if target_id == tg_id:
            await message.answer(tr("این کانفیگ همین الان مال همین کاربر است."))
            return
        target_user = await asyncio.to_thread(db.get_user, target_id)
        if not target_user:
            await message.answer(tr("❌ این کاربر بات را استارت نکرده یا آی‌دی نادرست است."))
            return
        await state.clear()
        await message.answer(
            tr(f"⚠️ آیا مطمئن هستید که این کانفیگ از کاربر {tg_id} به کاربر {target_id} منتقل شود؟\n"
               "این عملیات **غیرقابل بازگشت** است."),
            parse_mode="Markdown",
            reply_markup=kb.admin_cfg_transfer_confirm_kb(tg_id, cc_id, target_id),
        )

    @router.callback_query(F.data.startswith("adm_cfg_transok:"))
    async def cb_admin_cfg_transfer_confirm(call: CallbackQuery, bot: Bot):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, cc_id_s, target_id_s = call.data.split(":", 3)
            tg_id, cc_id, target_id = int(tg_id_s), int(cc_id_s), int(target_id_s)
        except ValueError:
            await call.answer(tr("کانفیگ یافت نشد."), show_alert=True)
            return
        custom_configs = await asyncio.to_thread(db.get_custom_configs_for_user, tg_id)
        cc = next((c for c in custom_configs if c["id"] == cc_id), None)
        if not cc:
            await call.answer(tr("این کانفیگ یافت نشد (شاید قبلاً منتقل شده)."), show_alert=True)
            return
        ok = await asyncio.to_thread(db.transfer_custom_config, cc_id, tg_id, target_id)
        if not ok:
            await call.answer(tr("انتقال ناموفق بود."), show_alert=True)
            return
        (await asyncio.to_thread(
            db.add_custom_config_history, cc_id, "transfer",
            f"از {tg_id} به {target_id} (توسط ادمین {call.from_user.id})",
        ))
        (await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "admin_transfer_config",
            f"کانفیگ #{cc_id} از {tg_id} به {target_id}",
        ))
        await call.answer(tr("✅ کانفیگ منتقل شد."), show_alert=True)
        try:
            await bot.send_message(
                target_id,
                tr(f"📦 یک کانفیگ («{cc['display_name'] or cc['username']}») توسط پشتیبانی به حساب شما منتقل شد.\n"
                   "برای مشاهده، حساب کاربری ← سرویس‌ها و سفارش‌های من را ببینید."),
            )
        except Exception:
            pass
        await _show_user_menu(call.message, tg_id, "✅ کانفیگ به کاربر دیگر منتقل شد.")

    @router.callback_query(F.data.startswith("adm_cfg_history:"))
    async def cb_admin_cfg_history(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, tg_id_s, cc_id_s = call.data.split(":", 2)
            tg_id, cc_id = int(tg_id_s), int(cc_id_s)
        except ValueError:
            await call.answer(tr("کانفیگ یافت نشد."), show_alert=True)
            return
        rows = await asyncio.to_thread(db.get_custom_config_history, cc_id)
        if not rows:
            await call.answer(tr("تاریخچه‌ای ثبت نشده."), show_alert=True)
            return
        lines = [f"🕒 تاریخچه‌ی کانفیگ #{cc_id}:\n"]
        for r in rows:
            lines.append(f"• {to_jalali_str(r['created_at'], with_time=True)} — {r['event_type']}: {r['detail'] or ''}")
        text = "\n".join(lines)
        for chunk_start in range(0, len(text), 3500):
            await call.message.answer(text[chunk_start:chunk_start + 3500])
        await call.answer()

    # -------------------------------------------------------------------
    # گروه گزارش تاپیک‌دار
    # -------------------------------------------------------------------

    def _report_group_text() -> str:
        chat_id = report_router.get_chat_id(db)
        status = f"فعال (آیدی: {chat_id})" if chat_id is not None else "غیرفعال؛ گزارش‌ها به پیام خصوصی مدیران می‌روند"
        return (
            "📣 گروه گزارش تاپیک‌دار\n\n"
            f"وضعیت: {status}\n\n"
            "مراحل راه‌اندازی:\n"
            "1. یک سوپرگروه بساز و در تنظیمات گروه، حالت «Topics» را روشن کن.\n"
            "2. بات را به گروه اضافه کن، ادمین کن و دسترسی «Manage Topics» بده.\n"
            "3. آیدی عددی گروه را بگیر: ربات @myidbot را به گروه اضافه کن و داخل گروه دستور /getgroupid@myidbot را بفرست. عددی که برمی‌گرداند (مثل -100123456789) آیدی گروه است. بعد از گرفتن آیدی می‌توانی @myidbot را از گروه حذف کنی.\n"
            "4. دکمه‌ی «تنظیم یا تغییر گروه» را بزن و آن آیدی را با علامت منفی و بدون فاصله بفرست.\n\n"
            "⚠️ فقط مدیران را عضو گروه کن؛ رسیدهای پرداخت کارت‌به‌کارت همچنان به پیام خصوصی مدیران می‌روند."
        )

    @router.callback_query(F.data == "adm_report_group")
    async def cb_report_group_menu(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await replace_admin_view(
            call, _report_group_text(),
            reply_markup=kb.admin_report_group_kb(report_router.get_chat_id(db) is not None),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_report_set")
    async def cb_report_group_set(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminReportGroup.waiting_chat_id)
        await safe_edit(
            call,
            db.get_text('handlers_admin.auto_b2a1aa2d', 'آیدی عددی سوپرگروه فوروم را بفرست (مثل -100123456789).\n\nبرای گرفتن آیدی: ربات @myidbot را به گروه اضافه کن و داخل گروه دستور /getgroupid@myidbot را بفرست.'),
            reply_markup=kb.admin_back_kb("adm_report_group"),
        )
        await call.answer()

    async def _apply_report_group(bot: Bot, chat_id: int) -> str:
        try:
            created = await report_router.setup_group(bot, db, chat_id)
        except report_router.SetupError as e:
            return f"❌ {e}"
        return f"✅ گروه گزارش فعال شد ({created} تاپیک جدید ساخته شد)."

    @router.message(AdminReportGroup.waiting_chat_id)
    async def process_report_group_id(message: Message, state: FSMContext, bot: Bot):
        if not owner_only(message.from_user.id):
            return
        try:
            chat_id = int((message.text or "").strip())
        except ValueError:
            await message.answer(db.get_text('handlers_admin.auto_788d80fe', '❌ آیدی باید یک عدد صحیح باشد (گروه\u200cها منفی هستند، مثل -100123456789).'))
            return
        await state.clear()
        result = await _apply_report_group(bot, chat_id)
        if result.startswith("✅"):
            await asyncio.to_thread(db.log_admin_action, message.from_user.id, "report_group_set", f"گروه گزارش: {chat_id}")
        await message.answer(result, reply_markup=kb.admin_report_group_kb(report_router.get_chat_id(db) is not None))

    @router.callback_query(F.data == "adm_report_recheck")
    async def cb_report_group_recheck(call: CallbackQuery, bot: Bot):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        chat_id = report_router.get_chat_id(db)
        if chat_id is None:
            await call.answer(db.get_text('handlers_admin.auto_f3306533', 'گروه گزارشی تنظیم نشده است.'), show_alert=True)
            return
        result = await _apply_report_group(bot, chat_id)
        await safe_edit(
            call, result + "\n\n" + _report_group_text(),
            reply_markup=kb.admin_report_group_kb(report_router.get_chat_id(db) is not None),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_report_clear")
    async def cb_report_group_clear(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await report_router.clear_group(db)
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "report_group_clear", "حذف گروه گزارش")
        await safe_edit(
            call, db.get_text('handlers_admin.auto_5f006669', '🚫 گروه گزارش حذف شد؛ گزارش\u200cها دوباره به پیام خصوصی مدیران ارسال می\u200cشوند.'),
            reply_markup=kb.admin_report_group_kb(False),
        )
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
        show_full = is_main_bot and owner_only(call.from_user.id)
        extra_hint = (
            "\n• «دریافت بکاپ کامل» یک فایل zip شامل دیتابیس بات اصلی + دیتابیس تک‌تک "
            "نماینده‌ها می‌فرستد؛ برای جابجایی کامل به سرور دیگر از همین گزینه استفاده کن.\n"
            "• «بازیابی کامل» همان فایل zip را می‌گیرد و هم بات اصلی هم دیتابیس تک‌تک "
            "نماینده‌ها را با هم بازیابی می‌کند (برخلاف «بازیابی از فایل بکاپ» معمولی که فقط "
            "دیتابیس همین یک بات را عوض می‌کند و اطلاعات نماینده‌ها را برنمی‌گرداند)."
            if show_full else ""
        )
        await replace_admin_view(call, 
            "🗄 بکاپ و بازیابی دیتابیس\n\n"
            "• «دریافت بکاپ فوری» یک نسخه از دیتابیس فعلی را همین الان برایت می‌فرستد.\n"
            "• «بازیابی از فایل بکاپ» دیتابیس فعلی را با فایلی که آپلود می‌کنی جایگزین می‌کند "
            "(این کار قابل بازگشت نیست مگر با بکاپ دیگری)."
            + extra_hint,
            reply_markup=kb.admin_backup_menu_kb(show_full_backup=show_full),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_backup_now")
    async def cb_backup_now(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await call.answer(db.get_text('handlers_admin.auto_d6e0acf2', '⏳ در حال گرفتن بکاپ...'))
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(db.db_path)), "backups")
        try:
            backup_path = await asyncio.to_thread(create_backup, db.db_path, backup_dir, 14)
        except Exception:
            return await call.message.answer(db.get_text('handlers_admin.auto_02bed82c', '❌ گرفتن بکاپ ناموفق بود.'))
        if not backup_path:
            return await call.message.answer(db.get_text('handlers_admin.auto_cffcb4ca', '❌ فایل دیتابیس پیدا نشد.'))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "backup_create", "دریافت بکاپ فوری از طریق بات"))
        await call.message.answer_document(
            FSInputFile(backup_path), caption=tr("🗄 بکاپ فوری دیتابیس")
        )

    @router.callback_query(F.data == "adm_backup_full")
    async def cb_backup_full(call: CallbackQuery):
        # این گزینه عمداً روی هر بات نمایندگی مخفی است (کیبورد فقط وقتی
        # is_main_bot=True آن را نشان می‌دهد)، ولی این چک سمت سرور هم لازم
        # است چون callback_data را می‌شود دستی هم فرستاد؛ یک نماینده هرگز نباید
        # بتواند اطلاعات کل نماینده‌های دیگر را با این دکمه بگیرد.
        if not (is_main_bot and owner_only(call.from_user.id)):
            return await deny_support(call)
        await call.answer(db.get_text('handlers_admin.auto_62a833c4', '⏳ در حال ساخت بکاپ کامل (بات اصلی + همه\u200cی نماینده\u200cها)...'))
        output_dir = os.path.join(os.path.dirname(os.path.abspath(db.db_path)), "backups", "full")
        try:
            zip_path = await asyncio.to_thread(create_full_backup, db, db.db_path, output_dir, 5)
        except Exception:
            logger.exception("ساخت بکاپ کامل ناموفق بود.")
            return await call.message.answer(db.get_text('handlers_admin.auto_0531647f', '❌ ساخت بکاپ کامل ناموفق بود.'))
        if not zip_path:
            return await call.message.answer(db.get_text('handlers_admin.auto_d98083ed', '❌ فایل دیتابیس اصلی پیدا نشد.'))
        file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        (await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "backup_full_create",
            "دریافت بکاپ کامل (بات اصلی + همه‌ی نماینده‌ها) از طریق بات",
        ))
        caption = (
            "🗂 بکاپ کامل\n"
            "شامل: دیتابیس بات اصلی + دیتابیس تک‌تک نماینده‌ها\n"
            f"📦 حجم: {file_size_mb:.1f} مگابایت\n\n"
            "برای انتقال به سرور جدید: همین فایل zip را روی سرور جدید باز کن؛ "
            "«main_bot.db» همان دیتابیس بات اصلی است و فایل‌های «reseller_*.db» "
            "باید در مسیر دیتابیس همان نماینده جایگزین شوند (طبق manifest.txt داخل zip)."
        )
        if file_size_mb > 49:
            await call.message.answer(
                tr(f"⚠️ حجم فایل ({file_size_mb:.1f} مگابایت) ممکن است از سقف ارسال فایل تلگرام "
                "برای بات‌ها بیشتر باشد. اگر ارسال زیر با خطا مواجه شد، فایل را مستقیم از مسیر "
                f"زیر روی خود سرور بردار:\n{zip_path}")
            )
        try:
            await call.message.answer_document(FSInputFile(zip_path), caption=caption)
        except Exception:
            logger.exception("ارسال فایل بکاپ کامل ناموفق بود.")
            await call.message.answer(
                tr(f"❌ ارسال فایل از طریق تلگرام ناموفق بود. فایل روی خود سرور اینجاست:\n{zip_path}")
            )

    # -------------------------------------------------------------------
    # بازیابی کامل (از فایل zip ساخته‌شده توسط «دریافت بکاپ کامل»)
    # -------------------------------------------------------------------
    # این بخش دقیقاً معادل «بازیابی از فایل بکاپ» است، با این تفاوت که
    # به‌جای یک فایل .db تنها، یک zip شامل بات اصلی + همه‌ی نماینده‌ها را
    # می‌گیرد و هرکدام را در مسیر خودش جایگزین می‌کند - وگرنه (باگ قبلی)
    # «بازیابی از فایل بکاپ» فقط دیتابیس همان بات را عوض می‌کرد و چون
    # اطلاعات کاربرها/کانفیگ‌ها/کیف پول هر نماینده داخل دیتابیس مستقل خودش
    # است (نه دیتابیس بات اصلی)، آن‌ها هیچ‌وقت برنمی‌گشتند.

    @router.callback_query(F.data == "adm_restore_full_start")
    async def cb_restore_full_start(call: CallbackQuery, state: FSMContext):
        if not (is_main_bot and owner_only(call.from_user.id)):
            return await deny_support(call)
        await state.set_state(AdminRestoreFullBackup.waiting_file)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_240f0a67', '♻️ فایل zip «بکاپ کامل» (همان چیزی که از «دریافت بکاپ کامل» گرفتی) را همین\u200cجا به\u200cصورت Document ارسال کن.\n\n⚠️ توجه: بعد از تایید، هم دیتابیس بات اصلی و هم دیتابیس تک\u200cتک نماینده\u200cهایی که داخل این zip باشند، جایگزین می\u200cشوند. هر بات نماینده\u200cای که در همین لحظه در حال اجراست، برای چند ثانیه در زمان جایگزینی دیتابیسش متوقف و دوباره خودکار روشن می\u200cشود.'),
            reply_markup=kb.admin_restore_full_waiting_kb(),
        )
        await call.answer()

    @router.callback_query(AdminRestoreFullBackup.waiting_file, F.data == "adm_restore_full_cancel_wait")
    async def cb_restore_full_cancel_wait(call: CallbackQuery, state: FSMContext):
        if not (is_main_bot and owner_only(call.from_user.id)):
            return await deny_support(call)
        await state.clear()
        await safe_edit(call, db.get_text('handlers_admin.auto_59009fb1', '❌ بازیابی کامل لغو شد.'), reply_markup=kb.admin_back_kb("adm_backup_menu"))
        await call.answer()

    @router.message(AdminRestoreFullBackup.waiting_file, F.document)
    async def on_restore_full_file(message: Message, state: FSMContext):
        if not (is_main_bot and owner_only(message.from_user.id)):
            return
        doc = message.document
        if not doc.file_name.lower().endswith(".zip"):
            return await message.answer(db.get_text('handlers_admin.auto_acc2dcce', '❌ فایل باید همان zip «بکاپ کامل» باشد. دوباره ارسال کن.'))

        tmp_dir = tempfile.mkdtemp(prefix="restore_full_")
        tmp_path = os.path.join(tmp_dir, "uploaded.zip")
        file = await message.bot.get_file(doc.file_id)
        await message.bot.download_file(file.file_path, destination=tmp_path)

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                names = zf.namelist()
        except Exception:
            return await message.answer(db.get_text('handlers_admin.auto_ccdfc887', '❌ این فایل یک zip معتبر نیست. عملیات لغو شد.'))
        if "main_bot.db" not in names:
            return await message.answer(db.get_text('handlers_admin.auto_8e9241dc', '❌ این zip شامل main_bot.db نیست؛ فایل «بکاپ کامل» درستی به نظر نمی\u200cرسد.'))

        reseller_count = sum(1 for n in names if n.startswith("reseller_") and n.endswith(".db"))
        await state.update_data(restore_full_tmp_path=tmp_path)
        await state.set_state(AdminRestoreFullBackup.waiting_confirm)
        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        await message.answer(
            tr(f"📦 فایل دریافت شد ({size_mb:.1f} مگابایت) — شامل بات اصلی + {reseller_count} دیتابیس نماینده.\n\n"
            "⚠️ با تایید، دیتابیس بات اصلی و دیتابیس همین نماینده‌ها جایگزین می‌شود (از وضعیت فعلی هر "
            "کدام هم قبلش یک نسخه‌ی pre_restore ذخیره می‌شود). مطمئنی؟"),
            reply_markup=kb.admin_restore_full_confirm_kb(),
        )

    @router.message(AdminRestoreFullBackup.waiting_file)
    async def on_restore_full_file_wrong_type(message: Message):
        if not (is_main_bot and owner_only(message.from_user.id)):
            return
        await message.answer(db.get_text('handlers_admin.auto_10efade1', '❌ باید فایل zip بکاپ کامل را به\u200cصورت Document ارسال کنی، نه متن یا عکس.'))

    @router.callback_query(AdminRestoreFullBackup.waiting_confirm, F.data == "adm_restore_full_confirm")
    async def cb_restore_full_confirm(call: CallbackQuery, state: FSMContext):
        if not (is_main_bot and owner_only(call.from_user.id)):
            return await deny_support(call)
        data = await state.get_data()
        tmp_path = data.get("restore_full_tmp_path")
        await state.clear()
        if not tmp_path or not os.path.exists(tmp_path):
            return await safe_edit(call, db.get_text('handlers_admin.auto_a5da3ea3', '❌ فایل موقت پیدا نشد، دوباره تلاش کن.'))

        await safe_edit(call, db.get_text('handlers_admin.auto_7607b181', '⏳ در حال بازیابی کامل...'))

        # قبل از جایگزینی فایل هر نماینده، اگر بات همان نماینده همین الان در حال
        # اجراست باید متوقفش کنیم - وگرنه اتصال زنده‌اش ممکن است وسط جایگزینی
        # فایل نیمه‌نوشته را باز نگه دارد (همان باگی که در replace_file توضیح
        # داده شده). چون این کار قبل از دانستن لیست نماینده‌ها (که داخل خود
        # zip است) ممکن نیست، ابتدا zip را باز و لیست را می‌خوانیم، هر بات
        # مرتبط را متوقف می‌کنیم، بعد فایل‌ها را جایگزین می‌کنیم؛ حلقه‌ی
        # reconcile هر بات متوقف‌شده‌ای که هنوز فعال باشد را ظرف چند ثانیه
        # خودش دوباره روشن می‌کند.
        stopped_tokens = []
        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                names = zf.namelist()
            reseller_ids = []
            for n in names:
                if n.startswith("reseller_") and n.endswith(".db"):
                    try:
                        reseller_ids.append(int(n[len("reseller_"):-len(".db")].split("_level")[0]))
                    except (ValueError, IndexError):
                        pass
            if bot_manager is not None:
                for rid in reseller_ids:
                    row = await asyncio.to_thread(db.get_reseller_bot, rid)
                    if row and bot_manager.is_running(row["bot_token"]):
                        await bot_manager.stop_bot(row["bot_token"])
                        stopped_tokens.append(row["bot_token"])

            result = await asyncio.to_thread(restore_full_backup, db, db.db_path, tmp_path)
        except Exception as e:
            logger.exception("بازیابی کامل ناموفق بود.")
            return await safe_edit(call, f"❌ بازیابی کامل ناموفق بود: {e}")
        else:
            (await asyncio.to_thread(
                db.log_admin_action, call.from_user.id, "backup_full_restore",
                f"بازیابی کامل: {len(result['resellers_restored'])} نماینده بازیابی، "
                f"{len(result['resellers_skipped'])} رد شد.",
            ))
        finally:
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass

        lines = ["✅ دیتابیس بات اصلی بازیابی شد."]
        if result["resellers_restored"]:
            lines.append(f"✅ {len(result['resellers_restored'])} دیتابیس نماینده بازیابی شد:")
            for r in result["resellers_restored"]:
                lines.append(f"  • @{r['bot_username'] or r['id']}")
        if result["resellers_skipped"]:
            lines.append(f"⚠️ {len(result['resellers_skipped'])} مورد رد شد:")
            for s in result["resellers_skipped"]:
                lines.append(f"  • {s['file']}: {s['reason']}")
        if stopped_tokens:
            lines.append(
                f"\nℹ️ {len(stopped_tokens)} بات نماینده برای جایگزینی دیتابیس موقتاً متوقف شد و ظرف چند "
                "ثانیه‌ی آینده خودش دوباره روشن می‌شود."
            )
        await safe_edit(call, "\n".join(lines))
        await call.answer()

    @router.callback_query(AdminRestoreFullBackup.waiting_confirm, F.data == "adm_restore_full_cancel")
    async def cb_restore_full_cancel(call: CallbackQuery, state: FSMContext):
        if not (is_main_bot and owner_only(call.from_user.id)):
            return await deny_support(call)
        data = await state.get_data()
        tmp_path = data.get("restore_full_tmp_path")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except OSError:
                pass
        await state.clear()
        await safe_edit(call, db.get_text('handlers_admin.auto_59009fb1', '❌ بازیابی کامل لغو شد.'), reply_markup=kb.admin_back_kb("adm_backup_menu"))
        await call.answer()

    # -------------------------------------------------------------------
    # زمان‌بندی بکاپ خودکار + جابجایی بین دو سرور
    # -------------------------------------------------------------------

    @router.callback_query(F.data == "adm_backup_sync_menu")
    async def cb_backup_sync_menu(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_9a579f94', '🔁 زمان\u200cبندی و جابجایی بکاپ بین سرورها\n\n• فاصله\u200cی بکاپ خودکار را می\u200cتونی تغییر بدی.\n• برای نگه\u200cداشتن یک کپی جانبی روی سرور دیگر، دو راه هست:\n  ۱) ارسال خودکار فایل بکاپ به یک چت تلگرام روی سرور دوم (ساده، نیاز به SSH ندارد).\n  ۲) ارسال مستقیم فایل بکاپ به سرور دوم با SFTP (نیاز به آی\u200cپی/یوزر/پسورد یا کلید سرور دوم).\nهر دو را می\u200cتونی هم\u200cزمان فعال کنی.'),
            reply_markup=kb.admin_backup_sync_menu_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_backup_sync_test")
    async def cb_backup_sync_test(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await call.answer(db.get_text('handlers_admin.auto_03c64a84', '⏳ در حال گرفتن بکاپ و ارسال به همه\u200cی مقصدها...'))
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(db.db_path)), "backups")
        try:
            await backup_and_notify(call.bot, db, db.db_path, backup_dir, keep=14)
        except Exception as e:
            return await call.message.answer(tr(f"❌ تست ناموفق بود: {e}"))
        await call.message.answer(
            db.get_text('handlers_admin.auto_69f59b21', '✅ بکاپ گرفته و به همه\u200cی ادمین\u200cها + مقصدهای جانبیِ فعال (چت دوم / SFTP در صورت تنظیم) ارسال شد.\nاگر ارسال به یکی از مقصدهای جانبی ناموفق بوده، در لاگ سرور ثبت شده - می\u200cتونی چک کنی.')
        )

    # --- فاصله‌ی زمانی بکاپ خودکار ---

    @router.callback_query(F.data == "adm_backup_interval_menu")
    async def cb_backup_interval_menu(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        current = (db.get_setting("backup_interval_hours", "") or "24").strip() or "24"
        await safe_edit(call, 
            f"⏱ فاصله‌ی فعلی بکاپ خودکار: هر {current} ساعت\n\n"
            "یکی از گزینه‌های زیر رو انتخاب کن یا عدد دلخواه بفرست:",
            reply_markup=kb.admin_backup_interval_kb(),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_backup_interval_set:"))
    async def cb_backup_interval_set(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        hours = call.data.split(":")[1]
        (await asyncio.to_thread(db.set_setting, "backup_interval_hours", hours))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "backup_interval_set", f"فاصله بکاپ: {hours} ساعت"))
        await safe_edit(call, 
            f"✅ فاصله‌ی بکاپ خودکار روی هر {hours} ساعت تنظیم شد.\n"
            "این تغییر از چرخه‌ی بعدی بکاپ‌گیری اعمال می‌شود (نیازی به ری‌استارت بات نیست).",
            reply_markup=kb.admin_backup_sync_menu_kb(db),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_backup_interval_custom")
    async def cb_backup_interval_custom(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminBackupInterval.waiting_hours)
        await safe_edit(call, db.get_text('handlers_admin.auto_d6ce4d14', 'عدد فاصله\u200cی زمانی بکاپ خودکار را به «ساعت» بفرست (مثلاً 8):'), reply_markup=kb.admin_back_kb("adm_backup_sync_menu"))
        await call.answer()

    @router.message(AdminBackupInterval.waiting_hours)
    async def process_backup_interval_hours(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        try:
            hours = int(float(text))
        except ValueError:
            await message.answer(db.get_text('handlers_admin.auto_c8a8cd6a', '❌ لطفاً فقط عدد بفرست (مثلاً 8).'))
            return
        if hours < 1 or hours > 720:
            await message.answer(db.get_text('handlers_admin.auto_da2a4455', '❌ عدد باید بین 1 تا 720 ساعت باشد.'))
            return
        await state.clear()
        (await asyncio.to_thread(db.set_setting, "backup_interval_hours", str(hours)))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "backup_interval_set", f"فاصله بکاپ: {hours} ساعت"))
        await message.answer(
            tr(f"✅ فاصله‌ی بکاپ خودکار روی هر {hours} ساعت تنظیم شد."),
            reply_markup=kb.admin_backup_sync_menu_kb(db),
        )

    # --- چت دوم تلگرام ---

    @router.callback_query(F.data == "adm_backup_chat2_menu")
    async def cb_backup_chat2_menu(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        chat2 = (db.get_setting("backup_secondary_chat_id", "") or "").strip()
        status = f"فعال (آیدی: {chat2})" if chat2 else "غیرفعال"
        await safe_edit(call, 
            f"📨 چت دوم تلگرام برای دریافت کپی خودکار بکاپ\n\nوضعیت فعلی: {status}\n\n"
            "نکته: بات باید عضو آن چت باشد یا آیدی عددی یک کاربر (که استارت بات را زده) باشد.",
            reply_markup=kb.admin_backup_chat2_menu_kb(bool(chat2)),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_backup_chat2_set")
    async def cb_backup_chat2_set(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminBackupSecondaryChat.waiting_chat_id)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_79b70063', 'آیدی عددی چت مقصد را بفرست (مثلاً 123456789 برای یک کاربر، یا -100123456789 برای یک گروه/کانال):'),
            reply_markup=kb.admin_back_kb("adm_backup_sync_menu"),
        )
        await call.answer()

    @router.message(AdminBackupSecondaryChat.waiting_chat_id)
    async def process_backup_chat2_id(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        try:
            chat_id = int(text)
        except ValueError:
            await message.answer(db.get_text('handlers_admin.auto_20e500d2', '❌ آیدی باید یک عدد صحیح باشد (می\u200cتواند منفی هم باشد).'))
            return
        await state.clear()
        (await asyncio.to_thread(db.set_setting, "backup_secondary_chat_id", str(chat_id)))
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "backup_chat2_set", f"چت دوم بکاپ: {chat_id}"))
        await message.answer(
            tr(f"✅ چت دوم روی آیدی {chat_id} تنظیم شد. از بکاپ خودکار بعدی، یک کپی هم اینجا فرستاده می‌شود."),
            reply_markup=kb.admin_backup_sync_menu_kb(db),
        )

    @router.callback_query(F.data == "adm_backup_chat2_disable")
    async def cb_backup_chat2_disable(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        (await asyncio.to_thread(db.set_setting, "backup_secondary_chat_id", ""))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "backup_chat2_disable", "غیرفعال‌سازی چت دوم بکاپ"))
        await safe_edit(call, db.get_text('handlers_admin.auto_68bc83f5', '🚫 ارسال به چت دوم غیرفعال شد.'), reply_markup=kb.admin_backup_sync_menu_kb(db))
        await call.answer()

    # --- SFTP سرور دوم ---

    @router.callback_query(F.data == "adm_backup_sftp_menu")
    async def cb_backup_sftp_menu(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        host = (db.get_setting("backup_sftp_host", "") or "").strip()
        enabled = (db.get_setting("backup_sftp_enabled", "0") or "0") == "1"
        if host:
            port = db.get_setting("backup_sftp_port", "22") or "22"
            user = db.get_setting("backup_sftp_username", "") or "-"
            remote_dir = db.get_setting("backup_sftp_remote_dir", "/root/vpn_backups") or "/root/vpn_backups"
            status = (
                f"{'فعال' if enabled else 'غیرفعال (تنظیمات ذخیره شده ولی خاموش)'}\n"
                f"سرور: {user}@{host}:{port}\nمسیر مقصد: {remote_dir}"
            )
        else:
            status = "تنظیم نشده"
        await safe_edit(call, 
            f"🔐 اتصال SFTP به سرور دوم\n\nوضعیت فعلی: {status}",
            reply_markup=kb.admin_backup_sftp_menu_kb(bool(host), enabled),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_backup_sftp_start")
    async def cb_backup_sftp_start(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminBackupSftp.waiting_host)
        await safe_edit(call, db.get_text('handlers_admin.auto_91b7ee8b', 'آی\u200cپی یا دامنه\u200cی سرور دوم را بفرست:'), reply_markup=kb.admin_back_kb("adm_backup_sync_menu"))
        await call.answer()

    @router.message(AdminBackupSftp.waiting_host)
    async def process_backup_sftp_host(message: Message, state: FSMContext):
        host = (message.text or "").strip()
        if not host:
            await message.answer(db.get_text('handlers_admin.auto_648b7f58', '❌ آدرس نمی\u200cتواند خالی باشد.'))
            return
        await state.update_data(sftp_host=host)
        await state.set_state(AdminBackupSftp.waiting_port)
        await message.answer(db.get_text('handlers_admin.auto_2a90d9bf', 'پورت SSH را بفرست (برای پیش\u200cفرض، عدد 22 را بفرست):'))

    @router.message(AdminBackupSftp.waiting_port)
    async def process_backup_sftp_port(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(db.get_text('handlers_admin.auto_cb57ba7b', '❌ پورت باید یک عدد باشد (مثلاً 22).'))
            return
        await state.update_data(sftp_port=int(text))
        await state.set_state(AdminBackupSftp.waiting_username)
        await message.answer(db.get_text('handlers_admin.auto_4aed4c13', 'یوزرنیم SSH سرور دوم را بفرست (مثلاً root):'))

    @router.message(AdminBackupSftp.waiting_username)
    async def process_backup_sftp_username(message: Message, state: FSMContext):
        username = (message.text or "").strip()
        if not username:
            await message.answer(db.get_text('handlers_admin.auto_0546214b', '❌ یوزرنیم نمی\u200cتواند خالی باشد.'))
            return
        await state.update_data(sftp_username=username)
        await message.answer(db.get_text('handlers_admin.auto_ba217a7c', 'روش احراز هویت SSH را انتخاب کن:'), reply_markup=kb.admin_backup_sftp_auth_choice_kb())

    @router.callback_query(F.data.startswith("adm_backup_sftp_auth:"), AdminBackupSftp.waiting_username)
    async def cb_backup_sftp_auth_choice(call: CallbackQuery, state: FSMContext):
        method = call.data.split(":")[1]
        if method == "password":
            await state.set_state(AdminBackupSftp.waiting_password)
            await call.message.answer(db.get_text('handlers_admin.auto_2077d805', 'پسورد SSH سرور دوم را بفرست:'))
        else:
            await state.set_state(AdminBackupSftp.waiting_key_path)
            await call.message.answer(
                db.get_text('handlers_admin.auto_34b71c34', 'مسیر فایل کلید خصوصی SSH را بفرست.\n⚠️ توجه: این فایل باید از قبل روی همین سرور (جایی که خود بات اجرا می\u200cشود) موجود باشد، مثلاً /root/.ssh/id_rsa - و کلید عمومی متناظرش باید روی سرور دوم authorize شده باشد.')
            )
        await call.answer()

    @router.message(AdminBackupSftp.waiting_password)
    async def process_backup_sftp_password(message: Message, state: FSMContext):
        password = (message.text or "").strip()
        await state.update_data(sftp_password=password, sftp_key_path=None)
        try:
            await message.delete()
        except Exception:
            pass
        await state.set_state(AdminBackupSftp.waiting_remote_dir)
        await message.answer(db.get_text('handlers_admin.auto_cb06c7a4', 'پوشه\u200cی مقصد روی سرور دوم را بفرست (مثلاً /root/vpn_backups) - یا «-» برای پیش\u200cفرض:'))

    @router.message(AdminBackupSftp.waiting_key_path)
    async def process_backup_sftp_key_path(message: Message, state: FSMContext):
        key_path = (message.text or "").strip()
        if not os.path.exists(key_path):
            await message.answer(tr(f"❌ فایلی در مسیر «{key_path}» روی این سرور پیدا نشد. دوباره بفرست یا مسیر درست را وارد کن."))
            return
        await state.update_data(sftp_key_path=key_path, sftp_password=None)
        await state.set_state(AdminBackupSftp.waiting_remote_dir)
        await message.answer(db.get_text('handlers_admin.auto_cb06c7a4', 'پوشه\u200cی مقصد روی سرور دوم را بفرست (مثلاً /root/vpn_backups) - یا «-» برای پیش\u200cفرض:'))

    @router.message(AdminBackupSftp.waiting_remote_dir)
    async def process_backup_sftp_remote_dir(message: Message, state: FSMContext):
        remote_dir = (message.text or "").strip()
        if remote_dir == "-" or not remote_dir:
            remote_dir = "/root/vpn_backups"
        data = await state.get_data()
        await message.answer(db.get_text('handlers_admin.auto_766b5a86', '⏳ در حال تست اتصال به سرور دوم...'))
        try:
            await test_sftp_connection(
                host=data["sftp_host"], port=data.get("sftp_port", 22), username=data["sftp_username"],
                password=data.get("sftp_password"), key_path=data.get("sftp_key_path"),
            )
        except Exception as e:
            await message.answer(tr(f"❌ اتصال به سرور دوم ناموفق بود: {e}\nتنظیمات ذخیره نشد؛ از منوی بکاپ دوباره تلاش کن."))
            await state.clear()
            return

        (await asyncio.to_thread(db.set_setting, "backup_sftp_host", data["sftp_host"]))
        (await asyncio.to_thread(db.set_setting, "backup_sftp_port", str(data.get("sftp_port", 22))))
        (await asyncio.to_thread(db.set_setting, "backup_sftp_username", data["sftp_username"]))
        (await asyncio.to_thread(db.set_setting, "backup_sftp_password", data.get("sftp_password") or ""))
        (await asyncio.to_thread(db.set_setting, "backup_sftp_key_path", data.get("sftp_key_path") or ""))
        (await asyncio.to_thread(db.set_setting, "backup_sftp_remote_dir", remote_dir))
        (await asyncio.to_thread(db.set_setting, "backup_sftp_enabled", "1"))
        await state.clear()
        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "backup_sftp_set", f"اتصال SFTP سرور دوم: {data['sftp_username']}@{data['sftp_host']}"))
        await message.answer(
            db.get_text('handlers_admin.auto_0fb6ab9a', '✅ اتصال با موفقیت تست شد و تنظیمات SFTP ذخیره شد.\nاز بکاپ خودکار بعدی، فایل بکاپ مستقیماً روی سرور دوم هم ذخیره می\u200cشود.'),
            reply_markup=kb.admin_backup_sync_menu_kb(db),
        )

    @router.callback_query(F.data == "adm_backup_sftp_disable")
    async def cb_backup_sftp_disable(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        (await asyncio.to_thread(db.set_setting, "backup_sftp_enabled", "0"))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "backup_sftp_disable", "غیرفعال‌سازی موقت SFTP بکاپ"))
        await safe_edit(call, db.get_text('handlers_admin.auto_b57ff4ea', '🔌 SFTP موقتاً غیرفعال شد (تنظیمات حفظ شد).'), reply_markup=kb.admin_backup_sync_menu_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_backup_sftp_clear")
    async def cb_backup_sftp_clear(call: CallbackQuery):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        for key in ("backup_sftp_host", "backup_sftp_port", "backup_sftp_username",
                    "backup_sftp_password", "backup_sftp_key_path", "backup_sftp_remote_dir",
                    "backup_sftp_enabled"):
            (await asyncio.to_thread(db.set_setting, key, ""))
        (await asyncio.to_thread(db.log_admin_action, call.from_user.id, "backup_sftp_clear", "حذف کامل تنظیمات SFTP بکاپ"))
        await safe_edit(call, db.get_text('handlers_admin.auto_62abc057', '🗑 تنظیمات SFTP سرور دوم کامل حذف شد.'), reply_markup=kb.admin_backup_sync_menu_kb(db))
        await call.answer()

    @router.callback_query(F.data == "adm_restore_start")
    async def cb_restore_start(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminRestoreBackup.waiting_file)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_19634f25', '♻️ فایل بکاپ (.db) را همین\u200cجا به\u200cصورت Document ارسال کن.\n\n⚠️ توجه: بعد از تایید، کل دیتابیس فعلی با این فایل جایگزین می\u200cشود.'),
            reply_markup=kb.admin_restore_waiting_kb(),
        )
        await call.answer()

    @router.callback_query(AdminRestoreBackup.waiting_file, F.data == "adm_restore_cancel_wait")
    async def cb_restore_cancel_wait(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await safe_edit(call, db.get_text('handlers_admin.auto_eb791574', '❌ بازیابی لغو شد.'), reply_markup=kb.admin_back_kb("adm_backup_menu"))
        await call.answer()

    @router.message(AdminRestoreBackup.waiting_file, F.document)
    async def on_restore_file(message: Message, state: FSMContext):
        if not owner_only(message.from_user.id):
            return
        doc = message.document
        if not doc.file_name.lower().endswith((".db", ".sqlite", ".sqlite3")):
            return await message.answer(db.get_text('handlers_admin.auto_bf52faed', '❌ فایل باید پسوند .db یا .sqlite داشته باشد. دوباره ارسال کن.'))

        tmp_dir = tempfile.mkdtemp(prefix="restore_")
        tmp_path = os.path.join(tmp_dir, "uploaded.db")
        file = await message.bot.get_file(doc.file_id)
        await message.bot.download_file(file.file_path, destination=tmp_path)

        if not is_valid_sqlite_db(tmp_path):
            return await message.answer(db.get_text('handlers_admin.auto_5b59fd57', '❌ این فایل یک دیتابیس sqlite معتبر نیست. عملیات لغو شد.'))

        await state.update_data(restore_tmp_path=tmp_path)
        await state.set_state(AdminRestoreBackup.waiting_confirm)
        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        await message.answer(
            tr(f"📦 فایل دریافت شد ({size_mb:.1f} مگابایت).\n\n"
            "⚠️ با تایید، دیتابیس فعلی جایگزین می‌شود (یک نسخه از وضعیت فعلی هم قبلش ذخیره می‌شود). "
            "مطمئنی؟"),
            reply_markup=kb.admin_restore_confirm_kb(),
        )

    @router.message(AdminRestoreBackup.waiting_file)
    async def on_restore_file_wrong_type(message: Message):
        if not owner_only(message.from_user.id):
            return
        await message.answer(db.get_text('handlers_admin.auto_3f6df645', '❌ باید فایل بکاپ را به\u200cصورت Document ارسال کنی، نه متن یا عکس.'))

    @router.callback_query(AdminRestoreBackup.waiting_confirm, F.data == "adm_restore_confirm")
    async def cb_restore_confirm(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        tmp_path = data.get("restore_tmp_path")
        await state.clear()
        if not tmp_path or not os.path.exists(tmp_path):
            return await safe_edit(call, db.get_text('handlers_admin.auto_a5da3ea3', '❌ فایل موقت پیدا نشد، دوباره تلاش کن.'))

        await safe_edit(call, db.get_text('handlers_admin.auto_043af51a', '⏳ در حال بازیابی...'))
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
            db.get_text('handlers_admin.auto_76222e81', '✅ دیتابیس با موفقیت بازیابی شد.\nاز نسخه\u200cی قبلی هم یک بکاپ ایمن (pre_restore) کنار دیتابیس ذخیره شد.')
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
        await safe_edit(call, db.get_text('handlers_admin.auto_eb791574', '❌ بازیابی لغو شد.'), reply_markup=kb.admin_back_kb("adm_backup_menu"))
        await call.answer()

    # -------------------------------------------------------------------
    # بازگشت به حالت کارخانه (روز اول نصب)
    # -------------------------------------------------------------------
    # فقط owner همین بات (اصلی یا نمایندگی) دسترسی دارد؛ همه‌ی داده‌ی این بات
    # پاک می‌شود و فقط owner باقی می‌ماند. قبل از پاک‌سازی یک بکاپ ایمنی
    # خودکار گرفته می‌شود.

    @router.callback_query(F.data == "adm_factory_reset_start")
    async def cb_factory_reset_start(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_376006a4', '🏭 بازگشت به حالت کارخانه\n\nبا تایید، همه\u200cی داده\u200cی این بات (کاربرها، سفارش\u200cها، محصولات، کیف پول، تیکت\u200cها، تنظیمات و ...) پاک می\u200cشود؛ دقیقاً مثل روز اول نصب، هم در بات و مینی\u200cاپ هم در پنل وب. فقط حساب خودت به\u200cعنوان owner باقی می\u200cماند. نماینده\u200cهای زیرمجموعه\u200cی این بات (در صورت وجود) دست\u200cنخورده می\u200cمانند.\n\n⚠️ این کار قابل بازگشت نیست مگر با بکاپ (یک بکاپ ایمنی خودکار قبل از پاک\u200cسازی گرفته می\u200cشود). مطمئنی؟'),
            reply_markup=kb.admin_factory_reset_confirm_kb(),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_factory_reset_step2")
    async def cb_factory_reset_step2(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminFactoryReset.waiting_confirm_text)
        await safe_edit(call, 
            db.get_text('handlers_admin.auto_8dfa5e44', '⚠️ تایید نهایی: برای پاک\u200cسازی، عبارت RESET را دقیقاً همین\u200cجا تایپ و ارسال کن.'),
            reply_markup=kb.admin_factory_reset_waiting_kb(),
        )
        await call.answer()

    @router.message(AdminFactoryReset.waiting_confirm_text)
    async def on_factory_reset_confirm_text(message: Message, state: FSMContext):
        if not owner_only(message.from_user.id):
            return
        if (message.text or "").strip().upper() != "RESET":
            return await message.answer(db.get_text('handlers_admin.auto_a4f7a754', '❌ عبارت را دقیقاً RESET وارد کن، یا برای انصراف دکمه\u200cی زیر پیام قبلی را بزن.'))

        await state.clear()
        status_msg = await message.answer(db.get_text('handlers_admin.auto_8f5ff68a', '⏳ در حال گرفتن بکاپ ایمنی و پاک\u200cسازی...'))
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(db.db_path)), "backups")
        try:
            safety_backup = await asyncio.to_thread(create_backup, db.db_path, backup_dir, 14)
        except Exception:
            safety_backup = None
        try:
            await asyncio.to_thread(db.factory_reset)
        except Exception as e:
            return await status_msg.edit_text(tr(f"❌ بازگشت به حالت کارخانه ناموفق بود: {e}"))

        (await asyncio.to_thread(db.log_admin_action, message.from_user.id, "factory_reset",
            f"بازگشت کامل به حالت کارخانه از طریق بات؛ بکاپ ایمنی: "
            f"{os.path.basename(safety_backup) if safety_backup else 'ناموفق'}"))
        await status_msg.edit_text(
            tr("✅ بات به حالت کارخانه بازگشت؛ همه‌ی داده‌ها پاک شدند و فقط حساب owner باقی ماند.\n"
            f"بکاپ قبل از پاک‌سازی: {os.path.basename(safety_backup) if safety_backup else 'ناموفق'}")
        )
        await message.answer(db.get_text('handlers_admin.auto_4741add8', '🔧 پنل مدیریت:'), reply_markup=kb.admin_panel_kb(db, is_main_bot))

    @router.callback_query(F.data == "adm_factory_reset_cancel")
    async def cb_factory_reset_cancel(call: CallbackQuery, state: FSMContext):
        if not owner_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await safe_edit(call, db.get_text('handlers_admin.auto_768cdf99', '❌ بازگشت به حالت کارخانه لغو شد.'), reply_markup=kb.admin_back_kb("adm_backup_menu"))
        await call.answer()

    # -------------------------------------------------------------------
    # دستور متنی برای دسترسی سریع
    # -------------------------------------------------------------------

    @router.message(Command("token2"))
    async def cmd_token2(message: Message, state: FSMContext):
        """صدور PAT برای API مستند؛ توکن قبلی همان ادمین فوراً باطل می‌شود."""
        if not admin_only(message.from_user.id):
            return
        await state.clear()
        raw = "shp_" + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        prefix = raw[:12]
        await asyncio.to_thread(
            db.create_mobile_token,
            message.from_user.id,
            "API /token2",
            token_hash,
            prefix,
            "read,users,orders",
            True,
        )
        await message.answer(
            tr("🔐 توکن API ساخته شد.\n\n"
            f"<code>{raw}</code>\n\n"
            "⚠️ این توکن فقط یک‌بار نمایش داده می‌شود و با صدور توکن جدید، توکن قبلی باطل می‌شود.\n"
            "سطح دسترسی: read, users, orders\n\n"
            "📖 مستندات: /api/index.html"),
            parse_mode=ParseMode.HTML,
        )

    @router.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        if not admin_only(message.from_user.id):
            return
        await state.clear()
        await message.answer(db.get_text('handlers_admin.auto_4741add8', '🔧 پنل مدیریت:'), reply_markup=kb.admin_panel_kb(db, is_main_bot))

    admin_tools.register(
        router, db, is_main_bot, full_admin_only, senior_admin_only,
        deny_support, deny_mid, safe_edit, replace_admin_view,
    )

    extra_gateway_admin.register(
        router, db, is_main_bot, admin_only, full_admin_only, deny_support, replace_admin_view,
        safe_edit, callback_id,
    )

    return router
