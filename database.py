# -*- coding: utf-8 -*-
"""
لایه دیتابیس - SQLite

این فایل حالا یک کلاس Database است، نه مجموعه‌ای از توابع سطح بالا.
دلیلش معماری چندباتی است: بات اصلی و هر بات نمایندگی، هرکدام یک نمونه‌ی
کاملاً جداگانه از Database (با فایل دیتابیس خودشان) دارند، در نتیجه هرکدام
به‌طور خودکار و مستقل صاحب تمام امکانات هستند (کد تخفیف، زیرمجموعه‌گیری،
کیف پول، کانفیگ تست، ...) بدون این‌که غیرفعال‌کردن یک قابلیت در یک بات
روی بات‌های دیگر اثر بگذارد.
"""

import asyncio
import logging
import sqlite3
import secrets
import threading
import time
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# مجوزهای granular پنل وب مدیریت. هر ادمین (به‌جز owner که همیشه دسترسی کامل
# دارد) یک زیرمجموعه دلخواه از این کلیدها را می‌تواند داشته باشد.
WEB_ADMIN_PERMISSIONS = (
    "orders",      # تأیید/رد سفارش و شارژ کیف پول
    "users",       # بلاک/آنبلاک کاربر، تنظیم دستی موجودی کیف پول
    "catalog",     # دسته‌بندی‌ها، محصولات، بانک کانفیگ
    "discounts",   # کدهای تخفیف
    "tickets",     # پاسخ/بستن تیکت و چت زنده پشتیبانی
    "broadcast",   # ارسال پیام همگانی
    "resellers",   # مدیریت نمایندگی‌ها
    "panels",      # پنل‌های VPN و نرخ ارز
    "system",      # وضعیت جاب‌های سیستمی، وضعیت بکاپ، لاگ فعالیت ادمین‌ها
    "settings",    # تنظیمات و برندینگ
    "backup",      # ساخت بکاپ فوری دیتابیس (بازیابی همیشه فقط برای owner است)
)

# نگاشت نقش‌های ثابت قدیمی به مجوزهای معادل، فقط برای مهاجرت داده‌های قبلی.
ROLE_PERMISSION_PRESETS = {
    "owner": list(WEB_ADMIN_PERMISSIONS),
    "admin": ["orders", "users", "catalog", "discounts", "tickets", "broadcast",
              "resellers", "panels", "system", "settings"],
    "mid": ["orders", "users", "tickets", "broadcast"],
    "support": [],
}


# بنرهای پیش‌فرض کاروسل بالای صفحه‌ی خانه‌ی مینی‌اپ (قابل مدیریت از پنل ادمین
# > ظاهر > بنرها). ساختار هر بنر: آیکون (اموجی)، عنوان، توضیح کوتاه، متن دکمه،
# گرادیانِ پس‌زمینه و اینکه ضربه‌زدن روی بنر کاربر را به کدام تب مینی‌اپ ببرد.
DEFAULT_BANNERS = [
    {
        "id": "b_store",
        "icon": "🛒",
        "title": "خرید سرویس جدید!",
        "sub": "سرویس مورد نظرتو انتخاب کن و در چند ثانیه فعالش کن!",
        "cta": "شروع خرید",
        "nav": "store",
        "bg": "linear-gradient(120deg, #0d1a12, #123a20 55%, #17532c)",
        "image": "",
        "image_only": False,
        "enabled": True,
    },
    {
        "id": "b_support",
        "icon": "💬",
        "title": "پشتیبانی ۲۴ ساعته",
        "sub": "هر سوالی داشتی، همین‌جا از پشتیبانی بپرس.",
        "cta": "گفت‌وگو با پشتیبانی",
        "nav": "support",
        "bg": "linear-gradient(120deg, #150c22, #2a1440 55%, #431f66)",
        "image": "",
        "image_only": False,
        "enabled": True,
    },
]


DEFAULT_SETTINGS = {
    "welcome_text": "👋 به فروشگاه کانفیگ V2Ray خوش آمدید!\nاز منوی زیر یکی از گزینه‌ها را انتخاب کنید.",
    "btn_buy": "🛒 خرید کانفیگ",
    "btn_test": "🧪 کانفیگ تست رایگان",
    "btn_contact": "📞 ارتباط با پشتیبانی",
    "btn_my_orders": "🧾 حساب کاربری من",
    "btn_referral": "🤝 زیرمجموعه‌گیری من",
    "btn_wallet": "👛 کیف پول من",
    "btn_admin_panel": "⚙️ پنل مدیریت",
    "test_enabled": "1",
    "force_join_enabled": "0",
    "force_join_channel": "",  # مثلاً: @mychannel
    "card_number": "0000-0000-0000-0000",
    "card_holder": "نام صاحب حساب",
    # حذف خودکار پیام‌های حاوی شماره کارت بعد از این تعداد ثانیه از ارسال؛
    # صفر یعنی غیرفعال (پیام برای همیشه در چت باقی می‌ماند).
    "card_msg_autodelete_seconds": "0",
    # پرداخت دستی کارت‌به‌کارت (ارسال رسید) به‌عنوان یکی از روش‌های پرداخت؛
    # اگر ادمین این روش را غیرفعال کند، در لیست روش‌های پرداخت نمایش داده نمی‌شود.
    "card_to_card_enabled": "1",
    "contact_text": "پیام خود را بنویسید تا مستقیم برای پشتیبانی ارسال شود:",
    # آیدی عددی تلگرام مدیر برای دکمه‌ی «چت مستقیم با مدیر» در بخش ارتباط با
    # پشتیبانی (از طریق لینک tg://user?id=... بدون نیاز به یوزرنیم عمومی باز می‌شود).
    "support_admin_id": "",
    "ticket_intro_text": "لطفاً موضوع تیکت را در یک خط ارسال کنید:",
    "after_buy_text": "برای تکمیل خرید، مبلغ را به شماره کارت زیر واریز کرده و سپس عکس رسید را ارسال کنید:",
    # رنگ دکمه‌ها (ویژگی جدید Bot API 9.4 / فوریه 2026)
    # مقادیر مجاز: "" (پیش‌فرض/خاکستری), "primary" (آبی), "success" (سبز), "danger" (قرمز)
    "btn_buy_style": "primary",
    "btn_test_style": "success",
    "btn_contact_style": "",
    "btn_my_orders_style": "",
    "btn_referral_style": "",
    "btn_wallet_style": "success",
    "btn_admin_panel_style": "danger",
    # نمایش منوی اصلی: منوی پایین (Reply) و منوی شیشه‌ای بالا (Inline) هرکدام
    # جداگانه قابل فعال/غیرفعال هستند، و چیدمان (۱ یا ۲ دکمه در هر ردیف) مشترک است
    "main_menu_reply_enabled": "1",
    "main_menu_inline_enabled": "0",
    "main_menu_columns": "1",
    "store_name": "⚡ SHOP VPN",
    "miniapp_banner_text": "اتصال امن و پایدار برقرار است",
    # سیستم زیرمجموعه‌گیری
    # کلید مستر: مستقل از سه مدل زیر - غیرفعال کردنش کل سیستم رفرال (دکمه/تب و
    # هر سه مدل پاداش) را کاملاً خاموش می‌کند، صرف‌نظر از اینکه کدام مدل روشن باشد.
    "referral_button_enabled": "1",
    # حالت ۱: پورسانت درصدی از اولین خرید هر زیرمجموعه
    "referral_enabled": "1",
    "referral_percent": "10",  # درصدی که به دعوت‌کننده به‌عنوان اعتبار کیف پول تعلق می‌گیرد
    "referral_commission_max_count": "0",  # حداکثر تعداد نفراتی که پورسانت خریدشان تعلق می‌گیرد (0 = نامحدود)
    # حالت ۲: دریافت یک محصول/کانفیگ رایگان با رسیدن تعداد دعوت‌شده‌ها به یک آستانه (نیازی به خرید نیست)
    "referral_free_config_enabled": "0",
    "referral_free_config_threshold": "10",  # تعداد دعوت لازم
    "referral_free_config_product_id": "",  # آیدی محصولی که رایگان تحویل داده می‌شود
    # حالت ۳: شارژ ثابت کیف پول به‌ازای هر دعوت (بدون نیاز به خرید)، تا سقف مشخص
    "referral_invite_bonus_enabled": "0",
    "referral_invite_bonus_amount": "0",  # مبلغ ثابت شارژ کیف پول به‌ازای هر دعوت (تومان)
    "referral_invite_bonus_max_count": "10",  # حداکثر تعداد دعوت‌هایی که این پاداش برایشان تعلق می‌گیرد (0 = نامحدود)
    # رنگ دکمه‌های شیشه‌ای داخل پنل مدیریت
    "adm_categories_style": "",
    "adm_products_style": "",
    "adm_add_configs_style": "",
    "adm_test_menu_style": "",
    "adm_pending_orders_style": "primary",
    "adm_pending_topups_style": "primary",
    "adm_discounts_menu_style": "",
    "adm_referral_settings_style": "",
    "adm_resellers_menu_style": "success",
    "adm_edit_buttons_style": "",
    "adm_set_card_style": "",
    "adm_edit_welcome_style": "",
    "adm_admins_menu_style": "",
    "adm_broadcast_style": "",
    "adm_stats_style": "success",
    "adm_wheel_settings_style": "success",
    # رنگ دکمه‌های شیشه‌ای مسیر خرید (دسته‌بندی/محصول/تایید و ...)
    "btn_cat_select_style": "primary",
    "btn_product_select_style": "primary",
    "btn_buy_continue_style": "success",
    "btn_enter_code_style": "",
    "btn_buy_back_style": "",
    # گردونه شانس
    "wheel_enabled": "1",
    "wheel_win_percent": "10",  # درصد احتمال برد از هر چرخش
    "wheel_prizes": "10,20,30,50",  # درصدهای تخفیف ممکن؛ در صورت برد یکی تصادفی انتخاب می‌شود
    "wheel_code_expiry_hours": "24",  # اعتبار کد جایزه پس از برد (ساعت)
    "wheel_cooldown_hours": "24",  # فاصله مجاز بین دو چرخش هر کاربر
    "btn_wheel": "🎡 گردونه شانس",
    # پرداخت کریپتو (Plisio)
    "crypto_payment_enabled": "0",
    "plisio_api_key": "",  # کلید API درگاه Plisio؛ از داخل بات (دکمه‌ی «تنظیم درگاه کریپتو») قابل تنظیم است
    "usd_to_toman_rate": "0",  # نرخ تبدیل هر ۱ دلار به تومان؛ توسط ادمین دستی تنظیم می‌شود
    # پرداخت کارت‌به‌کارت خودکار (آبان گیت وی)
    "abangateway_payment_enabled": "0",
    "abangateway_api_key": "",  # کلید API آبان گیت وی؛ از داخل بات (دکمه‌ی «تنظیم درگاه آبان گیت وی») قابل تنظیم است
    "btn_wheel_style": "success",
    # یادآوری اتمام سرویس + کد تخفیف تشویقی تمدید
    "renewal_reminder_enabled": "1",
    "renewal_reminder_days_before": "5",  # چند روز قبل از اتمام سرویس یادآوری ارسال شود
    "low_stock_threshold": "3",  # وقتی موجودی یک محصول به این عدد یا کمتر برسد، به ادمین‌ها هشدار داده می‌شود
    "renewal_discount_percent": "20",  # درصد تخفیف کد تشویقی تمدید
    "renewal_discount_expiry_hours": "24",  # اعتبار کد تشویقی تمدید (ساعت)
    "adm_renewal_settings_style": "success",
    "adm_stock_alert_settings_style": "",
    # یادآوری اتمام حجم + کد تخفیف تشویقی تمدید (مستقل از یادآوری تاریخ انقضا)
    "volume_reminder_enabled": "1",
    "volume_reminder_mode": "percent",  # "percent" یا "gb" - مبنای آستانه‌ی هشدار
    "volume_reminder_percent": "80",  # وقتی درصد مصرف به این عدد رسید (mode=percent)
    "volume_reminder_gb_left": "2",  # وقتی حجم باقی‌مانده به این تعداد گیگ رسید (mode=gb)
    "volume_discount_percent": "20",  # درصد تخفیف کد تشویقی اتمام حجم
    "volume_discount_expiry_hours": "24",  # اعتبار کد تشویقی اتمام حجم (ساعت)
    "adm_volume_reminder_settings_style": "success",
    # ساخت کانفیگ شخصی (اتصال مستقیم به پنل VPN)
    "custom_config_enabled": "0",
    "custom_config_min_gb": "5",       # حداقل حجم مجاز (گیگ)
    "custom_config_max_gb": "1000",    # حداکثر حجم مجاز (گیگ)
    "custom_config_duration_days": "30",  # فعلاً ثابت؛ در آینده قابل انتخاب کاربر می‌شود
    "test_config_panel_volume_gb": "1",     # فقط وقتی یک سرور برای «کانفیگ تست» فعال باشد
    "test_config_panel_duration_days": "1",
    "btn_custom_config": "🛠 ساخت کانفیگ شخصی",
    "btn_custom_config_style": "primary",
    "adm_panel_servers_style": "",
    "adm_custom_config_settings_style": "",
    # چیدمان دکمه‌های منوی اصلی (ترتیب و نمایش) - آرایه JSON از کلیدها
    "menu_order": '["miniapp","btn_buy","btn_test","btn_my_orders","btn_referral","btn_wheel","btn_contact","btn_admin_panel"]',
    "miniapp_enabled": "1",
    "reseller_request_enabled": "1",
    # حداقل مبلغ مجاز برای هر روش پرداخت (تومان). 0 یعنی بدون محدودیت.
    "min_amount_wallet_topup": "1000",  # حداقل مبلغ شارژ کیف پول
    "min_amount_card": "0",             # حداقل مبلغ برای پرداخت کارت‌به‌کارت دستی
    "min_amount_abangateway": "0",      # حداقل مبلغ برای آبان گیت وی
    "min_amount_crypto": "0",           # حداقل مبلغ برای پرداخت کریپتو
    "min_amount_card_auto": "0",        # حداقل مبلغ برای کارت‌به‌کارت خودکار
    "card_to_card_auto_enabled": "0",
    "card_to_card_auto_timeout_minutes": "15",  # بعد این‌مدت اگر پیامک نرسد، به بررسی دستی می‌رود
    "card_to_card_auto_amount_digits": "3",     # چند رقم آخر مبلغ برای یکتاسازی تصادفی اضافه شود
    "card_to_card_sms_amount_unit": "rial",     # واحد مبلغ داخل پیامک بانک: rial یا toman
    "card_to_card_sms_webhook_token": "",       # توکن احراز هویت وب‌هوک اپ BankSmsForwarder
}

# روش‌های پرداخت «داخلی» (غیر از درگاه‌های سفارشی) که در همه‌جای پروژه
# (بات، پنل ادمین وب، مینی‌اپ) به همین شکل شناخته می‌شوند. کلید تنظیم حداقل
# مبلغ هر کدام هم از همین‌جا ساخته می‌شود (min_amount_<key>) تا یک‌جا مدیریت شود.
BUILTIN_PAYMENT_METHODS = [
    {"key": "wallet", "label": "👛 کیف پول", "enable_setting": None},
    {"key": "card", "label": "💳 کارت‌به‌کارت (ارسال رسید)", "enable_setting": "card_to_card_enabled"},
    {"key": "abangateway", "label": "💳 آبان گیت وی (تایید آنی)", "enable_setting": "abangateway_payment_enabled"},
    {"key": "crypto", "label": "🪙 ارز دیجیتال (تایید آنی)", "enable_setting": "crypto_payment_enabled"},
    {"key": "card_auto", "label": "💳 کارت‌به‌کارت (تایید خودکار پیامکی)", "enable_setting": "card_to_card_auto_enabled"},
]


# تعریف کامل دکمه‌های قابل‌مدیریت در منوی اصلی: کلید -> متادیتا
# toggle_key: نام تنظیمی که فعال/غیرفعال بودن دکمه را کنترل می‌کند (None یعنی همیشه نمایش داده می‌شود)
# admin_only: اگر True فقط برای ادمین‌ها نمایش داده می‌شود
MENU_BUTTON_META = {
    "miniapp": {"label": "دکمه مینی‌اپ فروشگاه", "toggle_key": "miniapp_enabled", "admin_only": False, "has_text": False, "has_style": False},
    "btn_buy": {"label": "دکمه خرید کانفیگ", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True},
    "btn_test": {"label": "دکمه کانفیگ تست", "toggle_key": "test_enabled", "admin_only": False, "has_text": True, "has_style": True},
    "btn_my_orders": {"label": "دکمه حساب کاربری من", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True},
    "btn_referral": {"label": "دکمه زیرمجموعه‌گیری", "toggle_key": "referral_button_enabled", "admin_only": False, "has_text": True, "has_style": True},
    "btn_wheel": {"label": "دکمه گردونه شانس", "toggle_key": "wheel_enabled", "admin_only": False, "has_text": True, "has_style": True},
    "btn_contact": {"label": "دکمه ارتباط با پشتیبانی", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True},
    "btn_admin_panel": {"label": "دکمه پنل مدیریت", "toggle_key": None, "admin_only": True, "has_text": True, "has_style": True},
    # btn_reseller_panel بر اساس وضعیت کاربر (نماینده بودن/نبودن) به‌صورت پویا نمایش
    # داده می‌شود، نه با یک toggle سراسری؛ به همین دلیل toggle_key ندارد ولی مثل
    # بقیه‌ی دکمه‌ها متن/رنگ قابل تنظیم و در چیدمان منو قابل جابجایی است.
    "btn_reseller_panel": {"label": "دکمه پنل نمایندگی", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True},
    "btn_reseller_request": {"label": "دکمه درخواست نمایندگی سطح ۲", "toggle_key": "reseller_request_enabled", "admin_only": False, "has_text": True, "has_style": True},
}
# دکمه‌های داخل «حساب کاربری» و صفحه‌ی جزئیات هر سرویس: هرکدام با یک تنظیم
# جدا فعال/غیرفعال می‌شوند (پیش‌فرض همه فعال). کلید -> (برچسب برای ادمین، مقدار پیش‌فرض)
ACCOUNT_TOGGLE_KEYS = [
    ("acct_show_orders", "📦 نمایش «سرویس‌ها و سفارش‌های من»", "1"),
    ("acct_show_referral", "🤝 نمایش «زیرمجموعه‌گیری من»", "1"),
    ("acct_show_wallet", "👛 نمایش «کیف پول من»", "1"),
    ("svc_show_renew_full", "🛠 دکمه «تمدید کامل سرویس»", "1"),
    ("svc_show_renew_volume", "🔋 دکمه «تمدید حجم سرویس»", "1"),
    ("svc_show_renew_time", "⏱ دکمه «تمدید زمان سرویس»", "1"),
    ("svc_show_cut_access", "🚫 دکمه «قطع دسترسی و لینک جدید»", "1"),
    ("svc_show_update_config", "♻️ دکمه «بروزرسانی کانفیگ»", "1"),
    ("svc_show_qr", "⬜ دکمه «کیوآر کانفیگ»", "1"),
    ("svc_show_delete", "🗑 دکمه «حذف کامل سرویس»", "1"),
    ("svc_show_toggle", "🟢 دکمه «فعال/غیرفعال کردن کانفیگ»", "1"),
    ("svc_show_rename", "✏️ دکمه «تغییر نام کانفیگ»", "1"),
    ("svc_show_auto_renew", "🔄 دکمه «تمدید خودکار»", "1"),
    ("svc_show_transfer", "👤 دکمه «انتقال کانفیگ»", "1"),
    ("svc_show_history", "📜 دکمه «تاریخچه سرویس»", "1"),
]
DEFAULT_SETTINGS.update({key: default for key, _label, default in ACCOUNT_TOGGLE_KEYS})

DEFAULT_MENU_ORDER = [
    "miniapp", "btn_reseller_panel", "btn_reseller_request", "btn_buy", "btn_test",
    "btn_my_orders", "btn_referral", "btn_wheel", "btn_contact", "btn_admin_panel",
]


class Database:
    _SETTINGS_CACHE_TTL = 8  # ثانیه؛ برای هماهنگی بین پردازش بات و Mini App
    _ADMIN_CACHE_TTL = 5  # ثانیه؛ کوتاه‌تر از تنظیمات چون نقش ادمین حساس‌تر است

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None
        self._settings_cache = None
        self._settings_cache_loaded_at = 0.0
        # is_admin()/get_admin_role() قبلاً به ازای *هر* پیام و *هر* کلیک هر
        # کاربر (چه ادمین چه غیرادمین) مستقیماً یک SELECT synchronous به
        # sqlite می‌زدند (در BlockedUserMiddleware، AdminPresenceMiddleware و
        # داخل خود هندلرها - گاهی چندبار برای یک کلیک). چون این کوئری‌ها روی
        # همان event loop تک‌رشته‌ای اجرا می‌شوند، هر برخورد با قفل نوشتن
        # (مثلاً هم‌زمان با Mini App) کل بات را فریز می‌کرد. جدول admins بسیار
        # کم‌تغییر است، پس مثل تنظیمات کش می‌شود؛ بعد از add/set_role/remove
        # فوراً invalidate می‌شود تا تغییرات همین پردازش بلافاصله اعمال شوند.
        self._admin_cache = None
        self._admin_cache_loaded_at = 0.0
        # مینی‌اپ (FastAPI) توابع sync را در threadpool اجرا می‌کند، یعنی
        # ممکن است چند ریکوئست هم‌زمان از تردهای مختلف به همین یک Database
        # (مثلاً main_db) دسترسی داشته باشند. بات‌های aiogram هم در یک
        # event loop تک‌رشته‌ای هستند، پس این لاک برای آن‌ها overhead
        # واقعی ندارد ولی برای مینی‌اپ لازم است.
        self._lock = threading.Lock()

    async def cache_autorefresh_loop(self, interval: float = 2.0):
        """فقط برای پردازش بات (aiogram) استفاده می‌شود، نه مینی‌اپ/پنل وب.

        is_admin()/get_setting() وقتی TTL کش تمام شده باشد، یک بار خودشان
        مستقیم (synchronous) کش را دوباره می‌خوانند - این خواندن چون روی
        همان event loop مشترک تمام بات‌ها اجرا می‌شود، اگر درست همان لحظه
        فایل دیتابیس توسط پردازش دیگری (مینی‌اپ/پنل وب) قفل باشد، کل بات را
        تا چند ثانیه (busy_timeout) برای همه‌ی کاربران فریز می‌کند - از دید
        ادمین دقیقاً شبیه «کرش‌کردن دکمه‌ها»ست، بدون این‌که هیچ Exception ای
        لاگ شود چون در نهایت با موفقیت (بعد از انتظار) تمام می‌شود.

        این تابع در پس‌زمینه، با فاصله‌ی کوتاه‌تر از TTL کش، خودش را با
        asyncio.to_thread (یعنی روی یک ترد جدا، نه event loop اصلی) تازه
        نگه می‌دارد؛ در نتیجه وقتی is_admin()/get_setting() صدا زده می‌شوند،
        کش تقریباً همیشه هنوز تازه است و آن‌ها هرگز مجبور به خواندن مستقیم و
        بلوکه‌کننده از sqlite روی event loop اصلی نمی‌شوند."""
        while True:
            try:
                await asyncio.to_thread(self._load_settings_cache)
            except Exception:
                logger.exception("تازه‌سازی پس‌زمینه‌ی کش تنظیمات ناموفق بود (db_path=%s).", self.db_path)
            try:
                await asyncio.to_thread(self._load_admin_cache)
            except Exception:
                logger.exception("تازه‌سازی پس‌زمینه‌ی کش ادمین‌ها ناموفق بود (db_path=%s).", self.db_path)
            await asyncio.sleep(interval)

    # -----------------------------------------------------------------------
    # اتصال
    # -----------------------------------------------------------------------
    # به‌جای باز و بسته‌کردن یک اتصال جدید sqlite در هر کوئری (که overhead
    # قابل توجهی داشت، مخصوصاً چون فیلترهای روتر aiogram به ازای هر پیام
    # ورودی صدا زده می‌شوند)، یک اتصال persistent نگه می‌داریم.
    # check_same_thread=False + لاک، چون همین نمونه ممکن است بین تردهای
    # threadpool مینی‌اپ مشترک باشد.

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL باعث می‌شود خواندن‌ها همزمان با نوشتن قفل نشوند (بات + مینی‌اپ + پنل ادمین)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        # بدون busy_timeout، وقتی بات و مینی‌اپ (دو پروسه‌ی جدا) هم‌زمان روی همین
        # فایل دیتابیس می‌نویسند، هر کوئری که با یک نوشتن هم‌زمان تداخل کند فوراً
        # با خطای «database is locked» شکست می‌خورد.
        #
        # نکته‌ی مهم: این PRAGMA باعث نمی‌شود انتظار async/غیربلوکه باشد؛
        # sqlite3.Connection.execute() یک تابع synchronous است و در طول این
        # انتظار، کل event loop تک‌رشته‌ای aiogram (که همه‌ی بات‌ها - اصلی و
        # نمایندگی‌ها - در bot_manager.py روی آن اجرا می‌شوند) بلوکه می‌ماند؛
        # یعنی هیچ کلیدی برای هیچ کاربری پردازش نمی‌شود تا این انتظار تمام شود.
        # قبلاً این مقدار ۳۰۰۰۰ (۳۰ ثانیه) بود که باعث می‌شد یک برخورد قفل ساده
        # (مثلاً هم‌زمانی با یک نوشتن از Mini App) کل بات را تا ۳۰ ثانیه برای
        # همه فریز کند - دقیقاً همان «همه‌چیز قفل می‌شود» که از دید کاربر شبیه
        # کرش‌کردن دکمه‌هاست. مقدار پایین‌تر این حداکثر زمان فریز را محدود
        # می‌کند؛ اگر قفل زودتر باز نشود، به‌جای فریز طولانی یک خطای
        # «database is locked» می‌دهد که توسط try/except هر هندلر یا هندلر
        # سراسری خطا (_global_error_handler) گرفته و به کاربر پیام کوتاه نشان
        # داده می‌شود - جایگزینی بسیار بهتر از فریز چندثانیه‌ای کل بات.
        conn.execute("PRAGMA busy_timeout = 4000")
        return conn

    @contextmanager
    def _get_conn(self):
        with self._lock:
            if self._conn is None:
                self._conn = self._connect()
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self):
        """اتصال persistent فعلی را می‌بندد و کش تنظیمات را پاک می‌کند. فراخوانی
        بعدی هر متدی خودش دوباره یک اتصال تازه باز می‌کند. لازم قبل از
        جایگزین‌کردن فایل دیتابیس (بازیابی بکاپ)."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._settings_cache = None
            self._admin_cache = None

    def init_db(self, owner_id: int):
        """owner_id: آیدی عددی کسی که مالک/ادمین اصلی همین یک نمونه از بات است
        (برای بات اصلی همان مالک بات، برای هر بات نمایندگی همان نماینده)."""
        with self._get_conn() as conn:
            c = conn.cursor()
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    is_blocked INTEGER DEFAULT 0,
                    test_used INTEGER DEFAULT 0,
                    referred_by INTEGER,
                    referral_credit INTEGER DEFAULT 0,
                    referral_first_purchase_rewarded INTEGER DEFAULT 0,
                    referral_invite_bonus_given INTEGER DEFAULT 0,
                    referral_free_config_given INTEGER DEFAULT 0,
                    joined_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS admins (
                    telegram_id INTEGER PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    description TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    payment_methods TEXT,
                    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    link TEXT NOT NULL,
                    is_used INTEGER DEFAULT 0,
                    assigned_user_id INTEGER,
                    assigned_at TEXT,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS test_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link TEXT NOT NULL,
                    is_used INTEGER DEFAULT 0,
                    assigned_user_id INTEGER,
                    assigned_at TEXT
                );

                -- «کانفیگ تست» چندمدلی: هر ردیف مثل یک محصول است (نام، پیشوند نام
                -- کاربری، پنل مقصد، حجم به مگابایت و مدت به ساعت - برای پشتیبانی از
                -- مقادیر زیر ۱ گیگ/۱ روز). قانون «هر کاربر فقط یک بار تست» سراسری است
                -- (users.test_used) و مستقل از تعداد پلن‌هاست.
                CREATE TABLE IF NOT EXISTS test_config_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    name_prefix TEXT NOT NULL DEFAULT 'test',
                    panel_server_id INTEGER NOT NULL REFERENCES panel_servers(id),
                    volume_mb INTEGER NOT NULL DEFAULT 1024,
                    duration_hours INTEGER NOT NULL DEFAULT 24,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_test_plans_active ON test_config_plans(is_active);

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    receipt_file_id TEXT,
                    receipt_type TEXT DEFAULT 'photo',
                    config_id INTEGER,
                    admin_chat_id INTEGER,
                    admin_message_id INTEGER,
                    base_price INTEGER,
                    wallet_used INTEGER DEFAULT 0,
                    discount_code_id INTEGER,
                    discount_amount INTEGER DEFAULT 0,
                    final_price INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS discount_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    percent INTEGER,
                    fixed_amount INTEGER,
                    max_uses INTEGER DEFAULT 0,
                    used_count INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS wallet_topups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    receipt_file_id TEXT,
                    receipt_type TEXT DEFAULT 'photo',
                    admin_chat_id INTEGER,
                    admin_message_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS crypto_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    txn_id TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL,              -- 'order' یا 'wallet_topup'
                    ref_id INTEGER NOT NULL,         -- order_id یا topup_id
                    user_id INTEGER NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    source_amount_usd REAL NOT NULL,
                    currency TEXT,                   -- ارز انتخابی کاربر (مثلاً BTC, USDT_TRX)
                    invoice_url TEXT,
                    status TEXT DEFAULT 'new',        -- new/pending/completed/expired/error/cancelled
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reseller_bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_token TEXT UNIQUE NOT NULL,
                    bot_username TEXT,
                    owner_telegram_id INTEGER NOT NULL,
                    owner_name TEXT,
                    db_path TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    link_slug TEXT UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS pending_db_purges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_token TEXT NOT NULL,
                    db_path TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS support_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_read_by_user INTEGER DEFAULT 0,
                    is_read_by_admin INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS support_conversations (
                    user_id INTEGER PRIMARY KEY,
                    assigned_admin_id INTEGER,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS admin_presence (
                    telegram_id INTEGER PRIMARY KEY,
                    last_seen TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    claimed_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ticket_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_read_by_user INTEGER DEFAULT 0,
                    is_read_by_admin INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
                CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by);
                CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id);
                CREATE INDEX IF NOT EXISTS idx_configs_product_id ON configs(product_id);
                CREATE INDEX IF NOT EXISTS idx_configs_product_unused ON configs(product_id, is_used);
                CREATE INDEX IF NOT EXISTS idx_configs_assigned_user_id ON configs(assigned_user_id);
                CREATE INDEX IF NOT EXISTS idx_test_configs_unused ON test_configs(is_used);
                CREATE INDEX IF NOT EXISTS idx_test_configs_assigned_user_id ON test_configs(assigned_user_id);
                CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
                CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders(product_id);
                CREATE INDEX IF NOT EXISTS idx_discount_codes_code ON discount_codes(code);
                CREATE INDEX IF NOT EXISTS idx_wallet_topups_user_id ON wallet_topups(user_id);
                CREATE INDEX IF NOT EXISTS idx_wallet_topups_status ON wallet_topups(status);
                CREATE INDEX IF NOT EXISTS idx_support_messages_user_id ON support_messages(user_id);
                CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
                CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
                CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id ON ticket_messages(ticket_id);
                CREATE INDEX IF NOT EXISTS idx_reseller_bots_active ON reseller_bots(is_active);
                CREATE INDEX IF NOT EXISTS idx_crypto_invoices_txn ON crypto_invoices(txn_id);
                CREATE INDEX IF NOT EXISTS idx_crypto_invoices_ref ON crypto_invoices(kind, ref_id);

                CREATE TABLE IF NOT EXISTS abangateway_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id TEXT UNIQUE NOT NULL,  -- شناسه‌ی فاکتور در سمت آبان گیت وی (مثل inv_xxx)
                    kind TEXT NOT NULL,                -- 'order' یا 'wallet_topup'
                    ref_id INTEGER NOT NULL,           -- order_id یا topup_id
                    user_id INTEGER NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    amount_rial INTEGER NOT NULL,
                    payable_rial INTEGER,              -- مبلغ دقیقی که باید واریز شود (کمی بیشتر از amount_rial)
                    payment_url TEXT,
                    status TEXT DEFAULT 'new',          -- new/pending/paid/completed/expired/cancelled/error
                    expires_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_abangateway_invoices_invoice_id ON abangateway_invoices(invoice_id);
                CREATE INDEX IF NOT EXISTS idx_abangateway_invoices_ref ON abangateway_invoices(kind, ref_id);

                -- ===================== ساخت کانفیگ شخصی (پنل‌های VPN) =====================
                -- ===== درگاه‌های پرداخت سفارشی/پویا (تعریف‌شده توسط ادمین، بدون کد) =====
                CREATE TABLE IF NOT EXISTS custom_gateways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gateway_key TEXT UNIQUE NOT NULL,   -- اسلاگ یکتا، مثلاً 'zarinpal' یا 'mygate'
                    name TEXT NOT NULL,                 -- نام نمایشی برای کاربر/ادمین
                    config_json TEXT NOT NULL,          -- کل تنظیمات (اعتبارنامه، create/verify/webhook)
                    enabled INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS custom_gateway_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gateway_id INTEGER NOT NULL,
                    txn_id TEXT NOT NULL,               -- شناسه‌ی داخلی ما (merchant ref) - از قبل مشخص
                    gateway_ref TEXT,                    -- شناسه‌ی فاکتور/تراکنش که خودِ درگاه برمی‌گرداند (اختیاری)
                    kind TEXT NOT NULL,                 -- 'order' یا 'wallet_topup'
                    ref_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    invoice_url TEXT,
                    status TEXT DEFAULT 'new',          -- new/pending/completed/failed/expired/cancelled
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_custom_gw_invoices_txn ON custom_gateway_invoices(gateway_id, txn_id);
                CREATE INDEX IF NOT EXISTS idx_custom_gw_invoices_ref ON custom_gateway_invoices(gateway_id, kind, ref_id);

                -- ===== کارت‌به‌کارت با تایید خودکار (پیامک بانک از اپ BankSmsForwarder) =====
                CREATE TABLE IF NOT EXISTS card_to_card_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_number TEXT NOT NULL,
                    holder_name TEXT,
                    bank_name TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    last_used_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS card_to_card_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,                 -- 'order' یا 'wallet_topup'
                    ref_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    base_amount_toman INTEGER NOT NULL, -- مبلغ واقعی فاکتور (بدون رقم یکتاساز)
                    amount_toman INTEGER NOT NULL,      -- مبلغی که باید کاربر دقیقاً واریز کند (یکتا)
                    status TEXT DEFAULT 'pending',      -- pending/completed/manual_review
                    matched_sender TEXT,
                    matched_body TEXT,
                    matched_device_id TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                -- مبلغ فقط در بین فاکتورهای «در انتظار» باید یکتا باشد (پیامک بانک فقط
                -- مبلغ را گزارش می‌دهد، نه این‌که برای کدام کارت ماست؛ پس یکتایی باید
                -- سراسری باشد، نه فقط به‌ازای هر کارت).
                CREATE UNIQUE INDEX IF NOT EXISTS idx_card_to_card_amount_pending
                    ON card_to_card_invoices(amount_toman) WHERE status = 'pending';
                CREATE INDEX IF NOT EXISTS idx_card_to_card_ref ON card_to_card_invoices(kind, ref_id);

                CREATE TABLE IF NOT EXISTS panel_servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    panel_type TEXT NOT NULL DEFAULT 'pasarguard',
                    api_url TEXT NOT NULL,
                    api_username TEXT,
                    api_password TEXT,
                    template_username TEXT,
                    group_ids TEXT,
                    proxy_settings TEXT,
                    default_group TEXT,
                    used_for_custom_config INTEGER DEFAULT 1,
                    used_for_test_config INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS custom_config_pricing_tiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_gb INTEGER NOT NULL,
                    to_gb INTEGER,
                    price_per_gb INTEGER NOT NULL,
                    sort_order INTEGER DEFAULT 0
                );

                -- چندمحصولی‌کردن «ساخت کانفیگ شخصی»: هر محصول پنل/اینباند، بازه‌ی
                -- حجم/مدت و قیمت‌گذاری خودش را دارد. تنظیمات سراسری و
                -- custom_config_pricing_tiers بالا برای سازگاری با نصب‌های قبلی
                -- حذف نشده‌اند و به‌عنوان منبع مهاجرت محصول پیش‌فرض استفاده می‌شوند.
                CREATE TABLE IF NOT EXISTS custom_config_products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    icon TEXT DEFAULT '🛠',
                    panel_server_id INTEGER NOT NULL REFERENCES panel_servers(id),
                    min_gb INTEGER NOT NULL DEFAULT 5,
                    max_gb INTEGER NOT NULL DEFAULT 1000,
                    duration_mode TEXT NOT NULL DEFAULT 'fixed',
                    duration_days INTEGER NOT NULL DEFAULT 30,
                    min_days INTEGER,
                    max_days INTEGER,
                    pricing_mode TEXT NOT NULL DEFAULT 'flat',
                    flat_price_per_gb INTEGER,
                    payment_methods TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS custom_config_product_pricing_tiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES custom_config_products(id) ON DELETE CASCADE,
                    from_gb INTEGER NOT NULL,
                    to_gb INTEGER,
                    price_per_gb INTEGER NOT NULL,
                    sort_order INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_ccp_active ON custom_config_products(is_active);
                CREATE INDEX IF NOT EXISTS idx_ccp_tiers_product ON custom_config_product_pricing_tiers(product_id);

                CREATE TABLE IF NOT EXISTS custom_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    user_id INTEGER NOT NULL,
                    panel_server_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    volume_gb INTEGER NOT NULL,
                    duration_days INTEGER NOT NULL DEFAULT 30,
                    subscription_url TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT,
                    FOREIGN KEY(panel_server_id) REFERENCES panel_servers(id)
                );

                CREATE INDEX IF NOT EXISTS idx_panel_servers_active ON panel_servers(is_active);
                CREATE INDEX IF NOT EXISTS idx_custom_configs_user_id ON custom_configs(user_id);
                CREATE INDEX IF NOT EXISTS idx_custom_configs_order_id ON custom_configs(order_id);

                CREATE TABLE IF NOT EXISTS custom_config_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    custom_config_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_custom_config_history_config_id ON custom_config_history(custom_config_id);

                CREATE TABLE IF NOT EXISTS reseller_credit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    delta_gb INTEGER NOT NULL,
                    reason TEXT,
                    admin_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reseller_credit_log_user ON reseller_credit_log(user_id);

                CREATE TABLE IF NOT EXISTS reseller_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    volume_gb INTEGER NOT NULL,
                    request_text TEXT,
                    status TEXT NOT NULL DEFAULT 'pending_review',
                    price_toman INTEGER,
                    panel_server_id INTEGER,
                    receipt_file_id TEXT,
                    receipt_type TEXT DEFAULT 'photo',
                    bot_token TEXT,
                    bot_username TEXT,
                    owner_telegram_id INTEGER,
                    reject_reason TEXT,
                    reviewed_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reseller_requests_user ON reseller_requests(user_id);
                CREATE INDEX IF NOT EXISTS idx_reseller_requests_status ON reseller_requests(status);

                -- ===================== پنل مدیریت وب مستقل (خارج از تلگرام) =====================
                CREATE TABLE IF NOT EXISTS web_admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_login TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_web_admins_username ON web_admins(username);

                CREATE TABLE IF NOT EXISTS payment_webhook_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gateway TEXT NOT NULL,        -- 'plisio' / 'abangateway' / 'custom:<gateway_key>'
                    txn_id TEXT,
                    verified INTEGER DEFAULT 0,   -- آیا امضا/اعتبارسنجی تایید شد؟
                    status TEXT,                  -- وضعیتی که کال‌بک اعلام کرده (completed/pending/...)
                    error TEXT,                   -- در صورت رد شدن یا خطا، دلیل
                    raw_body TEXT,                -- بدنه‌ی خام کال‌بک (برای دیباگ)
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_webhook_logs_created ON payment_webhook_logs(created_at);

                CREATE TABLE IF NOT EXISTS web_push_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    endpoint TEXT UNIQUE NOT NULL,
                    p256dh TEXT NOT NULL,
                    auth TEXT NOT NULL,
                    user_agent TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_push_subs_admin ON web_push_subscriptions(admin_id);

                CREATE TABLE IF NOT EXISTS temp_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    delete_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_temp_messages_delete_at ON temp_messages(delete_at);
                """
            )

            c.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (owner_id,))

            for k, v in DEFAULT_SETTINGS.items():
                c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

            self._migrate_columns(conn)
            self._seed_default_custom_config_product(conn)
            self._seed_default_test_config_plan(conn)
            # اطمینان از این‌که همیشه مالک اصلی (از env) نقش «owner» را داشته باشد،
            # چه در نصب تازه و چه در ارتقای نصب‌های قدیمی‌تر که این ستون را نداشتند.
            conn.execute("UPDATE admins SET role='owner' WHERE telegram_id=?", (owner_id,))

    def _column_exists(self, conn, table: str, column: str) -> bool:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return column in cols

    def _migrate_columns(self, conn):
        migrations = [
            ("users", "referred_by", "INTEGER"),
            ("users", "referral_credit", "INTEGER DEFAULT 0"),
            ("users", "referral_first_purchase_rewarded", "INTEGER DEFAULT 0"),
            ("users", "referral_invite_bonus_given", "INTEGER DEFAULT 0"),
            ("users", "referral_free_config_given", "INTEGER DEFAULT 0"),
            ("orders", "status", "TEXT DEFAULT 'pending'"),
            ("orders", "base_price", "INTEGER"),
            ("orders", "wallet_used", "INTEGER DEFAULT 0"),
            ("orders", "discount_code_id", "INTEGER"),
            ("orders", "discount_amount", "INTEGER DEFAULT 0"),
            ("orders", "final_price", "INTEGER"),
            ("orders", "receipt_type", "TEXT DEFAULT 'photo'"),
            ("wallet_topups", "receipt_type", "TEXT DEFAULT 'photo'"),
            ("users", "last_wheel_spin_at", "TEXT"),
            ("discount_codes", "expires_at", "TEXT"),
            ("discount_codes", "source", "TEXT"),
            ("products", "duration_days", "INTEGER DEFAULT 30"),
            ("configs", "expires_at", "TEXT"),
            ("configs", "renewal_reminder_sent", "INTEGER DEFAULT 0"),
            ("configs", "volume_reminder_sent", "INTEGER DEFAULT 0"),
            ("products", "low_stock_alert_sent", "INTEGER DEFAULT 0"),
            ("admins", "role", "TEXT DEFAULT 'admin'"),
            ("support_messages", "is_read_by_admin", "INTEGER DEFAULT 0"),
            ("tickets", "claimed_by", "INTEGER"),
            ("orders", "quantity", "INTEGER DEFAULT 1"),
            ("configs", "order_id", "INTEGER"),
            ("reseller_bots", "link_slug", "TEXT"),
            ("reseller_bots", "reseller_level", "INTEGER DEFAULT 2"),
            ("reseller_bots", "web_panel_enabled", "INTEGER DEFAULT 0"),
            ("reseller_bots", "web_panel_setup_token", "TEXT"),
            ("reseller_bots", "web_panel_setup_token_created_at", "TEXT"),
            ("crypto_invoices", "expires_at", "TEXT"),
            # ساخت کانفیگ شخصی: سفارش‌های این نوع از همان جدول orders رد می‌شوند
            # (تا کارت‌به‌کارت/کیف‌پول/کریپتو بدون تغییر کار کنند) و product_id
            # برایشان 0 (سنتینل، بدون FK) ذخیره می‌شود؛ جزئیات واقعی در ستون‌های زیر است.
            ("orders", "is_custom_config", "INTEGER DEFAULT 0"),
            ("orders", "custom_volume_gb", "INTEGER"),
            ("orders", "custom_username", "TEXT"),
            ("orders", "custom_panel_server_id", "INTEGER"),
            ("panel_servers", "api_key", "TEXT"),
            ("panel_servers", "api_username", "TEXT"),
            ("panel_servers", "api_password", "TEXT"),
            ("panel_servers", "template_username", "TEXT"),
            ("panel_servers", "group_ids", "TEXT"),
            ("panel_servers", "proxy_settings", "TEXT"),
            ("panel_servers", "used_for_custom_config", "INTEGER DEFAULT 1"),
            ("panel_servers", "used_for_test_config", "INTEGER DEFAULT 0"),
            ("panel_servers", "used_for_reseller", "INTEGER DEFAULT 0"),
            ("panel_servers", "xui_inbound_id", "INTEGER"),
            ("panel_servers", "xui_sub_base_url", "TEXT"),
            # چند-inbound برای 3X-UI: از این به بعد یک سرور می‌تواند همزمان چند
            # inbound برای ساخت کاربر جدید داشته باشد (JSON array از id ها، مثلاً
            # "[1,2,3]"). ستون قدیمی xui_inbound_id (تک‌مقداری) برای سازگاری با
            # نصب‌های قبلی حذف نشده و به‌عنوان fallback خوانده می‌شود.
            ("panel_servers", "xui_inbound_ids", "TEXT"),
            ("products", "is_auto_provision", "INTEGER DEFAULT 0"),
            ("products", "auto_provision_volume_gb", "INTEGER"),
            ("products", "provision_server_id", "INTEGER"),
            ("users", "is_reseller", "INTEGER DEFAULT 0"),
            ("users", "reseller_credit_gb", "INTEGER DEFAULT 0"),
            ("custom_configs", "renewal_reminder_sent", "INTEGER DEFAULT 0"),
            ("custom_configs", "volume_reminder_sent", "INTEGER DEFAULT 0"),
            ("custom_configs", "source", "TEXT DEFAULT 'custom_config'"),
            ("custom_configs", "enabled", "INTEGER DEFAULT 1"),
            ("custom_configs", "auto_renew", "INTEGER DEFAULT 0"),
            ("custom_configs", "auto_renew_alert_date", "TEXT"),
            ("custom_configs", "display_name", "TEXT"),
            ("users", "reseller_panel_id", "INTEGER"),
            # نصب‌های قدیمی‌تر ممکن است جدول reseller_requests را قبل از اضافه‌شدن
            # این ستون‌ها ساخته باشند (چون CREATE TABLE IF NOT EXISTS در آن حالت
            # هیچ ستونی اضافه نمی‌کند)؛ برای جلوگیری از خطای «no column named ...»
            # موقع ثبت درخواست نمایندگی، این ستون‌ها را هم مهاجرت می‌کنیم.
            ("reseller_requests", "volume_gb", "INTEGER DEFAULT 0"),
            ("reseller_requests", "request_text", "TEXT"),
            ("reseller_requests", "status", "TEXT DEFAULT 'pending_review'"),
            ("reseller_requests", "price_toman", "INTEGER"),
            ("reseller_requests", "panel_server_id", "INTEGER"),
            ("reseller_requests", "receipt_file_id", "TEXT"),
            ("reseller_requests", "receipt_type", "TEXT DEFAULT 'photo'"),
            ("reseller_requests", "bot_token", "TEXT"),
            ("reseller_requests", "bot_username", "TEXT"),
            ("reseller_requests", "owner_telegram_id", "INTEGER"),
            ("reseller_requests", "reject_reason", "TEXT"),
            ("reseller_requests", "reviewed_by", "INTEGER"),
            ("reseller_requests", "created_at", "TEXT"),
            ("reseller_requests", "updated_at", "TEXT"),
            ("web_admins", "permissions", "TEXT"),
            ("admin_logs", "record_type", "TEXT"),
            ("admin_logs", "record_id", "TEXT"),
            # حذف کانفیگ/سفارش توسط خود کاربر (از منوی «سفارش‌های من» در بات یا
            # مینی‌اپ)؛ سفارش‌هایی که همه‌ی کانفیگ‌هایشان حذف شده به این صورت از
            # لیست کاربر مخفی می‌شوند ولی برای گزارش‌های ادمین دست‌نخورده می‌مانند.
            ("orders", "user_deleted", "INTEGER DEFAULT 0"),
            ("users", "force_join_exempt", "INTEGER DEFAULT 0"),
            ("users", "acquisition_source", "TEXT"),
            # محدودسازی روش پرداخت مجاز به ازای هر محصول: JSON آرایه‌ای از
            # کلیدهای روش (مثلاً ["wallet","card"])؛ NULL/خالی یعنی همه‌ی
            # روش‌های پرداخت فعال، برای این محصول هم مجازند (رفتار پیش‌فرض/قدیم).
            ("products", "payment_methods", "TEXT"),
            # حداقل مبلغ واریزی مجاز برای هر درگاه سفارشی/پویا (به تومان).
            ("custom_gateways", "min_amount", "INTEGER DEFAULT 0"),
            # تمدید سرویس از حساب کاربری: مثل is_custom_config از همان جدول orders
            # با product_id=0 سنتینل استفاده می‌کند تا همه‌ی روش‌های پرداخت
            # (کارت/کیف‌پول/کریپتو/آبان‌گیت‌وی/درگاه سفارشی) بدون تغییر کار کنند.
            ("orders", "is_renewal", "INTEGER DEFAULT 0"),
            ("orders", "renewal_target_kind", "TEXT"),
            ("orders", "renewal_target_id", "INTEGER"),
            ("orders", "renewal_mode", "TEXT"),
            ("orders", "renewal_add_volume_gb", "INTEGER DEFAULT 0"),
            ("orders", "renewal_add_days", "INTEGER DEFAULT 0"),
            # چندمحصولی‌کردن «ساخت کانفیگ شخصی»: NULL یعنی سفارش/کانفیگ از
            # مسیر سراسری قدیمی ساخته شده (پیش از وجود جدول محصولات).
            ("orders", "custom_product_id", "INTEGER"),
            ("orders", "custom_duration_days", "INTEGER"),
            ("custom_configs", "product_id", "INTEGER"),
        ]
        for table, col, coltype in migrations:
            if not self._column_exists(conn, table, col):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")

        # مهاجرت نقش‌های ثابت قدیمی (owner/admin/mid/support) به مجموعه
        # مجوزهای granular. فقط رکوردهایی که هنوز permissions ندارند پر می‌شوند
        # تا override دستی مالک روی حساب‌های موجود دست‌نخورده بماند.
        if self._column_exists(conn, "web_admins", "permissions"):
            legacy_rows = conn.execute(
                "SELECT id, role FROM web_admins WHERE permissions IS NULL"
            ).fetchall()
            for row in legacy_rows:
                perms = ROLE_PERMISSION_PRESETS.get(row["role"], ROLE_PERMISSION_PRESETS["support"])
                conn.execute(
                    "UPDATE web_admins SET permissions=? WHERE id=?",
                    (json.dumps(perms), row["id"]),
                )

        # مهاجرت وضعیت درخواست‌های نمایندگی از نسخه‌های قدیمی.
        # در نسخه‌های قدیمی ممکن است درخواست جدید با status='pending' ذخیره شده
        # باشد، در حالی که منطق فعلی مدیر فقط 'pending_review' را معتبر می‌داند؛
        # در نتیجه با زدن «تأیید و تعیین هزینه» پیام «این درخواست دیگر معتبر نیست»
        # نمایش داده می‌شد. این تبدیل فقط روی جدول reseller_requests اعمال می‌شود
        # و وضعیت‌های معتبر نسخه فعلی را دست‌نخورده باقی می‌گذارد.
        if self._column_exists(conn, "reseller_requests", "status"):
            conn.execute(
                "UPDATE reseller_requests SET status='pending_review' "
                "WHERE status IN ('pending', '') OR status IS NULL"
            )

        # مهاجرت یک‌باره: تغییر نام دکمه‌ی «سفارش‌های من» به مقدار جدید پیش‌فرض
        # («🧾 حساب کاربری من»). چون تنظیمات با INSERT OR IGNORE ذخیره می‌شوند،
        # نصب‌های قدیمی‌تر که این مقدار را از قبل در دیتابیس داشتند با آپدیت کد
        # به‌تنهایی متنشان عوض نمی‌شد. این مهاجرت فقط یک‌بار (به ازای هر نصب)
        # اجرا می‌شود؛ اگر ادمین بعداً دستی متن دکمه را عوض کند، دیگر توسط
        # آپدیت‌های بعدی بازنویسی نخواهد شد.
        if conn.execute(
            "SELECT 1 FROM settings WHERE key='_migrated_btn_my_orders_rename'"
        ).fetchone() is None:
            conn.execute(
                "UPDATE settings SET value=? WHERE key='btn_my_orders'",
                (DEFAULT_SETTINGS["btn_my_orders"],),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('_migrated_btn_my_orders_rename', '1')"
            )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_configs_order_id ON configs(order_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_logs_record ON admin_logs(record_type, record_id)"
        )

    def _seed_default_custom_config_product(self, conn):
        """مهاجرت یک‌باره: اگر نصب قدیمی‌تر تنظیمات سراسری «ساخت کانفیگ شخصی»
        را فعال داشته و هنوز هیچ ردیفی در custom_config_products ندارد، یک
        محصول پیش‌فرض از روی همان تنظیمات/تعرفه‌ها/سرور ساخته می‌شود تا رفتار
        نصب‌های موجود بدون تغییر بماند (کاربر همچنان مستقیم می‌رود سراغ
        یوزرنیم/حجم، بدون مرحله‌ی اضافه‌ی «انتخاب محصول»)."""
        if conn.execute("SELECT 1 FROM custom_config_products LIMIT 1").fetchone() is not None:
            return
        enabled = conn.execute(
            "SELECT value FROM settings WHERE key='custom_config_enabled'"
        ).fetchone()
        if not enabled or enabled["value"] != "1":
            return
        server = conn.execute(
            "SELECT * FROM panel_servers WHERE is_active=1 AND used_for_custom_config=1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not server:
            return

        def _setting(key, default):
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row and row["value"] is not None else default

        min_gb = int(_setting("custom_config_min_gb", "5") or 5)
        max_gb = int(_setting("custom_config_max_gb", "1000") or 1000)
        duration_days = int(_setting("custom_config_duration_days", "30") or 30)

        cur = conn.execute(
            "INSERT INTO custom_config_products (name, description, panel_server_id, min_gb, max_gb, "
            "duration_mode, duration_days, pricing_mode, is_active, sort_order) "
            "VALUES (?, '', ?, ?, ?, 'fixed', ?, 'tiered', 1, 0)",
            ("کانفیگ شخصی", server["id"], min_gb, max_gb, duration_days),
        )
        product_id = cur.lastrowid

        tiers = conn.execute(
            "SELECT from_gb, to_gb, price_per_gb, sort_order FROM custom_config_pricing_tiers ORDER BY sort_order, from_gb"
        ).fetchall()
        for t in tiers:
            conn.execute(
                "INSERT INTO custom_config_product_pricing_tiers (product_id, from_gb, to_gb, price_per_gb, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (product_id, t["from_gb"], t["to_gb"], t["price_per_gb"], t["sort_order"]),
            )

    def _seed_default_test_config_plan(self, conn):
        """مهاجرت یک‌باره: اگر نصب قدیمی‌تر یک پنل برای «کانفیگ تست» فعال داشته
        و هنوز هیچ ردیفی در test_config_plans ندارد، یک پلن پیش‌فرض از روی همان
        تنظیمات سراسری قدیمی (test_config_panel_volume_gb/duration_days) ساخته
        می‌شود تا نصب‌های موجود بدون تغییر رفتار کنند."""
        if conn.execute("SELECT 1 FROM test_config_plans LIMIT 1").fetchone() is not None:
            return
        server = conn.execute(
            "SELECT * FROM panel_servers WHERE is_active=1 AND used_for_test_config=1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not server:
            return

        def _setting(key, default):
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row and row["value"] is not None else default

        volume_gb = float(_setting("test_config_panel_volume_gb", "1") or 1)
        duration_days = float(_setting("test_config_panel_duration_days", "1") or 1)
        conn.execute(
            "INSERT INTO test_config_plans (name, name_prefix, panel_server_id, volume_mb, duration_hours, "
            "is_active, sort_order) VALUES ('کانفیگ تست', 'test', ?, ?, ?, 1, 0)",
            (server["id"], int(round(volume_gb * 1024)), int(round(duration_days * 24))),
        )

    # -----------------------------------------------------------------------
    # تنظیمات (settings)
    # -----------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        # تنظیمات در حافظه کش می‌شوند چون به ازای هر پیام ورودی (فیلترهای
        # روتر در handlers_user.py) چندین بار خوانده می‌شوند؛ خواندن از dict
        # به‌جای query جدید sqlite تفاوت محسوسی در سرعت پاسخ‌گویی ایجاد می‌کند.
        # نکته: بات و Mini App دو پردازش جدا هستند، هرکدام کش خودشان را دارند؛
        # به همین دلیل این کش یک TTL کوتاه دارد تا تغییراتی که از پردازش دیگر
        # ذخیره می‌شوند (مثلاً چیدمان منو از Mini App) بعد از چند ثانیه در بات
        # هم اعمال شوند، بدون این‌که هر پیام مستقیم به sqlite بزند.
        self._maybe_reload_settings_cache()
        return self._settings_cache.get(key, default)

    def _maybe_reload_settings_cache(self):
        now = time.monotonic()
        if self._settings_cache is None or (now - self._settings_cache_loaded_at) > self._SETTINGS_CACHE_TTL:
            self._load_settings_cache()

    def _load_settings_cache(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            cache = {r["key"]: r["value"] for r in rows}
        with self._lock:
            self._settings_cache = cache
            self._settings_cache_loaded_at = time.monotonic()

    def set_setting(self, key: str, value: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        if self._settings_cache is not None:
            self._settings_cache[key] = value

    def get_all_settings(self) -> dict:
        self._maybe_reload_settings_cache()
        return dict(self._settings_cache)

    # -----------------------------------------------------------------------
    # چیدمان منوی اصلی (ترتیب دکمه‌ها)
    # -----------------------------------------------------------------------

    def get_menu_order(self) -> list:
        """ترتیب کلیدهای دکمه‌های منوی اصلی را برمی‌گرداند. کلیدهای جدیدی که در
        تنظیمات ذخیره‌شده نیستند (مثلاً بعد از آپدیت پروژه) به انتهای لیست اضافه می‌شوند
        تا هیچ دکمه‌ای گم نشود."""
        import json
        raw = self.get_setting("menu_order", "")
        order = []
        if raw:
            try:
                order = [k for k in json.loads(raw) if k in DEFAULT_MENU_ORDER]
            except (ValueError, TypeError):
                order = []
        if not order:
            order = list(DEFAULT_MENU_ORDER)
        for k in DEFAULT_MENU_ORDER:
            if k not in order:
                order.append(k)
        return order

    def set_menu_order(self, order: list):
        import json
        clean = [k for k in order if k in DEFAULT_MENU_ORDER]
        for k in DEFAULT_MENU_ORDER:
            if k not in clean:
                clean.append(k)
        self.set_setting("menu_order", json.dumps(clean, ensure_ascii=False))

    def get_menu_row_breaks(self):
        """کلیدهایی که باید *قبل* از آن‌ها یک ردیف جدید در منو شروع شود.
        این یعنی چیدمان منو دیگر محدود به «همه‌ی دکمه‌ها زیر هم» یا «۲تا-۲تا»
        نیست: هر دکمه‌ای که اینجا نباشد به ردیف دکمه‌ی قبلی‌اش می‌چسبد، پس با
        همین یک لیست می‌شود مثلاً «یک دکمه تمام‌عرض، بعد دو دکمه کنار هم»
        ساخت. مقدار None یعنی کاربر هنوز چیدمان سفارشی نساخته - در این حالت
        فراخوان باید برای سازگاری با نصب‌های قدیمی از main_menu_columns
        استفاده کند (رفتار قبلی)."""
        import json
        raw = self.get_setting("main_menu_row_breaks", "")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, list):
            return None
        return [k for k in data if isinstance(k, str) and k in DEFAULT_MENU_ORDER]

    def set_menu_row_breaks(self, keys: list):
        import json
        clean = [k for k in keys if k in DEFAULT_MENU_ORDER]
        self.set_setting("main_menu_row_breaks", json.dumps(clean, ensure_ascii=False))

    # -----------------------------------------------------------------------
    # بنرهای کاروسل بالای صفحه‌ی خانه‌ی مینی‌اپ
    # -----------------------------------------------------------------------

    def get_banners(self) -> list:
        """لیست بنرهای سفارشی کاروسل خانه را برمی‌گرداند. اولین بار که خوانده
        می‌شود، با بنرهای پیش‌فرض (خرید سرویس / پشتیبانی) مقداردهی می‌شود تا
        رفتار مینی‌اپ برای نصب‌های قبلی بدون تغییر بماند."""
        raw = self.get_setting("miniapp_banners", "")
        if not raw:
            self.set_banners(DEFAULT_BANNERS)
            return [dict(b) for b in DEFAULT_BANNERS]
        try:
            banners = json.loads(raw)
            if not isinstance(banners, list):
                raise ValueError
        except (ValueError, TypeError):
            return [dict(b) for b in DEFAULT_BANNERS]
        return banners

    def set_banners(self, banners: list):
        self.set_setting("miniapp_banners", json.dumps(banners, ensure_ascii=False))

    # -----------------------------------------------------------------------
    # کاربران
    # -----------------------------------------------------------------------

    def add_or_update_user(self, tg_id: int, username: str, first_name: str):
        with self._get_conn() as conn:
            row = conn.execute("SELECT id FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET username=?, first_name=? WHERE telegram_id=?",
                    (username, first_name, tg_id),
                )
            else:
                conn.execute(
                    "INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
                    (tg_id, username, first_name),
                )

    def get_user(self, tg_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()

    def set_user_blocked(self, tg_id: int, blocked: bool):
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET is_blocked=? WHERE telegram_id=?", (1 if blocked else 0, tg_id))

    def search_users(self, query: str = "", status_filter: str = "all", limit: int = 30, offset: int = 0):
        """جستجو/فیلتر کاربران برای پنل مدیریت.
        status_filter: 'all' | 'active' | 'expired' | 'blocked'
        خروجی: (rows, total_count)
        """
        now = datetime.utcnow().isoformat()
        conditions = []
        params = []

        if query:
            conditions.append("(CAST(u.telegram_id AS TEXT) LIKE ? OR u.username LIKE ? OR u.first_name LIKE ?)")
            like = f"%{query}%"
            params += [like, like, like]

        if status_filter == "blocked":
            conditions.append("u.is_blocked=1")
        elif status_filter == "active":
            conditions.append(
                "EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1 "
                "AND (c.expires_at IS NULL OR c.expires_at > ?))"
            )
            params.append(now)
        elif status_filter == "expired":
            conditions.append(
                "EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) "
                "AND NOT EXISTS (SELECT 1 FROM configs c2 WHERE c2.assigned_user_id=u.telegram_id AND c2.is_used=1 "
                "AND (c2.expires_at IS NULL OR c2.expires_at > ?))"
            )
            params.append(now)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) c FROM users u {where}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT u.* FROM users u {where} ORDER BY u.id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return rows, total

    def get_user_status(self, tg_id: int) -> str:
        """وضعیت خلاصه‌ی یک کاربر: 'blocked' | 'active' | 'expired' | 'none' (هیچ سرویسی نداشته)."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            u = conn.execute("SELECT is_blocked FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
            if u and u["is_blocked"]:
                return "blocked"
            has_active = conn.execute(
                "SELECT 1 FROM configs WHERE assigned_user_id=? AND is_used=1 "
                "AND (expires_at IS NULL OR expires_at > ?) LIMIT 1",
                (tg_id, now),
            ).fetchone()
            if has_active:
                return "active"
            has_any = conn.execute(
                "SELECT 1 FROM configs WHERE assigned_user_id=? AND is_used=1 LIMIT 1", (tg_id,)
            ).fetchone()
            return "expired" if has_any else "none"

    def get_user_full_history(self, tg_id: int):
        """تاریخچه‌ی کامل یک کاربر: سفارش‌ها (با نام محصول و لینک کانفیگ) + شارژهای کیف‌پول."""
        with self._get_conn() as conn:
            orders = conn.execute(
                "SELECT o.*, p.name as product_name, cf.link as config_link, cf.expires_at as config_expires_at "
                "FROM orders o "
                "LEFT JOIN products p ON o.product_id = p.id "
                "LEFT JOIN configs cf ON o.config_id = cf.id "
                "WHERE o.user_id=? ORDER BY o.id DESC",
                (tg_id,),
            ).fetchall()
            topups = conn.execute(
                "SELECT * FROM wallet_topups WHERE user_id=? ORDER BY id DESC", (tg_id,)
            ).fetchall()
            return {"orders": orders, "topups": topups}

    def get_expired_user_ids(self):
        """آیدی کاربرانی که سابقه‌ی سرویس دارند ولی الان هیچ سرویس فعالی ندارند و بلاک نیستند
        (برای ارسال پیام گروهی تشویق به تمدید)."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT u.telegram_id FROM users u "
                "WHERE u.is_blocked=0 "
                "AND EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) "
                "AND NOT EXISTS (SELECT 1 FROM configs c2 WHERE c2.assigned_user_id=u.telegram_id AND c2.is_used=1 "
                "AND (c2.expires_at IS NULL OR c2.expires_at > ?))",
                (now,),
            ).fetchall()
            return [r["telegram_id"] for r in rows]

    def mark_test_used(self, tg_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET test_used=test_used+1 WHERE telegram_id=?", (tg_id,))

    def reset_all_test_usage(self) -> list:
        """test_used همه‌ی کاربرانی که قبلاً کانفیگ تست گرفته‌اند را صفر می‌کند تا
        دوباره بتوانند تست بگیرند. لیست آیدی همان کاربران را برمی‌گرداند تا بشود
        بهشان پیام اطلاع‌رسانی فرستاد."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id FROM users WHERE test_used > 0").fetchall()
            user_ids = [r["telegram_id"] for r in rows]
            conn.execute("UPDATE users SET test_used=0 WHERE test_used > 0")
            return user_ids

    def get_all_user_ids(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id FROM users WHERE is_blocked=0").fetchall()
            return [r["telegram_id"] for r in rows]

    def count_users(self):
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    def _sqlite_retry(self, operation, attempts: int = 4, delay: float = 0.15):
        """اجرای عملیات SQLite با retry کوتاه برای برخوردهای موقت database is locked/busy."""
        last_error = None
        for attempt in range(attempts):
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                last_error = exc
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                if attempt == attempts - 1:
                    raise
                time.sleep(delay * (attempt + 1))
        raise last_error

    # -----------------------------------------------------------------------
    # ادمین‌ها
    # -----------------------------------------------------------------------

    def _maybe_reload_admin_cache(self):
        now = time.monotonic()
        if self._admin_cache is None or (now - self._admin_cache_loaded_at) > self._ADMIN_CACHE_TTL:
            self._load_admin_cache()

    def _load_admin_cache(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id, role FROM admins").fetchall()
            cache = {r["telegram_id"]: (r["role"] or "admin") for r in rows}
        with self._lock:
            self._admin_cache = cache
            self._admin_cache_loaded_at = time.monotonic()

    def _invalidate_admin_cache(self):
        with self._lock:
            self._admin_cache = None

    def is_admin(self, tg_id: int) -> bool:
        self._maybe_reload_admin_cache()
        return tg_id in self._admin_cache

    def get_owner_telegram_id(self):
        """آیدی تلگرام مالک این بات (نقش owner در جدول admins). برای بات نمایندگی
        همان کسی است که این بات را می‌گرداند - جهت اتصال به اعتبار حجمی‌اش در بات اصلی."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT telegram_id FROM admins WHERE role='owner' LIMIT 1").fetchone()
            return row["telegram_id"] if row else None

    def is_full_access_bot(self, is_main_bot: bool) -> bool:
        """بات اصلی و نماینده‌ی «سطح ۱ (کامل)» به همه‌ی امکانات (پنل VPN شخصی، ساخت
        کانفیگ دستی، بانک لینک برای محصولات) دسترسی دارند. نماینده‌ی «سطح ۲» فقط
        می‌تواند محصولات خودکار-از-اعتبار-حجمی بفروشد و به پنل/کانفیگ دستی دسترسی ندارد."""
        if is_main_bot:
            return True
        return self.get_setting("reseller_level", "2") == "1"

    def get_admin_role(self, tg_id: int):
        """نقش ادمین را برمی‌گرداند: 'owner' | 'admin' | 'mid' | 'support' | None (اگر ادمین نباشد)."""
        self._maybe_reload_admin_cache()
        return self._admin_cache.get(tg_id)

    def is_full_admin(self, tg_id: int) -> bool:
        """دسترسی کامل عملیاتی: مالک، مدیر یا ادمین میانی (برخلاف پشتیبان که دسترسی محدود دارد)."""
        role = self.get_admin_role(tg_id)
        return role in ("owner", "admin", "mid")

    def is_senior_admin(self, tg_id: int) -> bool:
        """فقط مالک یا مدیر کامل؛ برای بخش‌های حساس که حتی ادمین میانی هم به آن‌ها دسترسی ندارد
        (آمار فروش، چیدمان منو، تنظیمات کمپین‌ها/تخفیف، لاگ ادمین، نمایندگی‌ها،
        برندینگ فروشگاه، و مدیریت محصولات/دسته‌بندی‌ها/کانفیگ‌بانک)."""
        role = self.get_admin_role(tg_id)
        return role in ("owner", "admin")

    def is_owner(self, tg_id: int) -> bool:
        return self.get_admin_role(tg_id) == "owner"

    def add_admin(self, tg_id: int, role: str = "admin"):
        if role not in ("admin", "mid", "support"):
            role = "admin"
        def op():
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO admins (telegram_id, role) VALUES (?, ?) "
                    "ON CONFLICT(telegram_id) DO UPDATE SET role=excluded.role",
                    (tg_id, role),
                )
        result = self._sqlite_retry(op)
        self._invalidate_admin_cache()
        return result

    def set_admin_role(self, tg_id: int, role: str) -> bool:
        """تغییر نقش یک ادمین موجود. نقش «owner» هرگز از این مسیر قابل واگذاری نیست."""
        if role not in ("admin", "mid", "support"):
            return False
        def op():
            with self._get_conn() as conn:
                row = conn.execute("SELECT role FROM admins WHERE telegram_id=?", (tg_id,)).fetchone()
                if not row or row["role"] == "owner":
                    return False
                conn.execute("UPDATE admins SET role=? WHERE telegram_id=?", (role, tg_id))
            return True
        result = self._sqlite_retry(op)
        self._invalidate_admin_cache()
        return result

    def remove_admin(self, tg_id: int, protected_owner_id: int = None) -> bool:
        if protected_owner_id is not None and tg_id == protected_owner_id:
            return False
        def op():
            with self._get_conn() as conn:
                row = conn.execute("SELECT role FROM admins WHERE telegram_id=?", (tg_id,)).fetchone()
                if row and row["role"] == "owner":
                    return False
                conn.execute("DELETE FROM admins WHERE telegram_id=?", (tg_id,))
            return True
        result = self._sqlite_retry(op)
        self._invalidate_admin_cache()
        return result

    def list_admins(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id FROM admins").fetchall()
            return [r["telegram_id"] for r in rows]

    def list_admins_with_roles(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id, role FROM admins ORDER BY "
                                 "CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END, telegram_id").fetchall()
            return [{"telegram_id": r["telegram_id"], "role": r["role"] or "admin"} for r in rows]

    # -----------------------------------------------------------------------
    # پنل مدیریت وب مستقل (کاربران وب، جدا از ادمین‌های تلگرام)
    # -----------------------------------------------------------------------

    def create_web_admin(self, username: str, password_hash: str, role: str = "admin",
                          permissions=None) -> int:
        if role not in ("owner", "admin", "mid", "support"):
            role = "admin"
        if permissions is None:
            perms = ROLE_PERMISSION_PRESETS.get(role, [])
        else:
            perms = [p for p in permissions if p in WEB_ADMIN_PERMISSIONS]
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO web_admins (username, password_hash, role, permissions) VALUES (?, ?, ?, ?)",
                (username.strip().lower(), password_hash, role, json.dumps(perms)),
            )
            return cur.lastrowid

    def get_web_admin_by_username(self, username: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM web_admins WHERE username=?", (username.strip().lower(),)
            ).fetchone()

    def get_web_admin(self, admin_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM web_admins WHERE id=?", (admin_id,)).fetchone()

    def list_web_admins(self):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM web_admins ORDER BY "
                "CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END, id"
            ).fetchall()

    def count_web_admins(self) -> int:
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) c FROM web_admins").fetchone()["c"]

    def set_web_admin_password(self, admin_id: int, password_hash: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE web_admins SET password_hash=? WHERE id=?", (password_hash, admin_id))

    def set_web_admin_role(self, admin_id: int, role: str) -> bool:
        if role not in ("admin", "mid", "support"):
            return False
        with self._get_conn() as conn:
            row = conn.execute("SELECT role FROM web_admins WHERE id=?", (admin_id,)).fetchone()
            if not row or row["role"] == "owner":
                return False
            conn.execute(
                "UPDATE web_admins SET role=?, permissions=? WHERE id=?",
                (role, json.dumps(ROLE_PERMISSION_PRESETS.get(role, [])), admin_id),
            )
            return True

    def set_web_admin_permissions(self, admin_id: int, permissions) -> bool:
        perms = [p for p in permissions if p in WEB_ADMIN_PERMISSIONS]
        with self._get_conn() as conn:
            row = conn.execute("SELECT role FROM web_admins WHERE id=?", (admin_id,)).fetchone()
            if not row or row["role"] == "owner":
                return False
            conn.execute(
                "UPDATE web_admins SET permissions=? WHERE id=?", (json.dumps(perms), admin_id)
            )
            return True

    def get_web_admin_permissions(self, admin_row) -> list:
        if admin_row["role"] == "owner":
            return list(WEB_ADMIN_PERMISSIONS)
        try:
            perms = json.loads(admin_row["permissions"] or "[]")
        except (ValueError, TypeError):
            perms = []
        return [p for p in perms if p in WEB_ADMIN_PERMISSIONS]

    def has_web_admin_permission(self, admin_row, permission: str) -> bool:
        if admin_row["role"] == "owner":
            return True
        return permission in self.get_web_admin_permissions(admin_row)

    def set_web_admin_active(self, admin_id: int, active: bool) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT role FROM web_admins WHERE id=?", (admin_id,)).fetchone()
            if not row or row["role"] == "owner":
                return False
            conn.execute("UPDATE web_admins SET is_active=? WHERE id=?", (1 if active else 0, admin_id))
            return True

    def delete_web_admin(self, admin_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT role FROM web_admins WHERE id=?", (admin_id,)).fetchone()
            if not row or row["role"] == "owner":
                return False
            conn.execute("DELETE FROM web_admins WHERE id=?", (admin_id,))
            return True

    def touch_web_admin_login(self, admin_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE web_admins SET last_login=? WHERE id=?", (datetime.utcnow().isoformat(), admin_id)
            )

    def is_full_web_admin(self, role: str) -> bool:
        return role in ("owner", "admin", "mid")

    # ---------------------------------------------------- web push subs --

    def save_push_subscription(self, admin_id: int, endpoint: str, p256dh: str, auth: str, user_agent: str = None):
        """ذخیره یا به‌روزرسانی subscription پوش مرورگر یک ادمین (هر endpoint یکتاست؛
        اگر همان مرورگر قبلاً subscribe کرده بود، رکورد قبلی به‌روز می‌شود)."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO web_push_subscriptions (admin_id, endpoint, p256dh, auth, user_agent, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(endpoint) DO UPDATE SET "
                "admin_id=excluded.admin_id, p256dh=excluded.p256dh, auth=excluded.auth, user_agent=excluded.user_agent",
                (admin_id, endpoint, p256dh, auth, user_agent, datetime.utcnow().isoformat()),
            )

    def delete_push_subscription_by_endpoint(self, endpoint: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM web_push_subscriptions WHERE endpoint=?", (endpoint,))

    def delete_push_subscriptions_by_endpoints(self, endpoints):
        endpoints = list(endpoints or [])
        if not endpoints:
            return
        with self._get_conn() as conn:
            conn.executemany("DELETE FROM web_push_subscriptions WHERE endpoint=?", [(e,) for e in endpoints])

    def list_push_subscriptions_for_admin(self, admin_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM web_push_subscriptions WHERE admin_id=? ORDER BY id DESC", (admin_id,)
            ).fetchall()

    def list_push_subscriptions_for_permission(self, permission: str):
        """همه‌ی subscription های مرورگری ادمین‌های فعالی که مالک هستند یا مجوز
        داده‌شده را دارند؛ برای فرستادن پوش سراسری (سفارش/شارژ/تیکت جدید) استفاده می‌شود."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT s.*, a.role AS admin_role, a.permissions AS admin_permissions, a.is_active AS admin_active "
                "FROM web_push_subscriptions s JOIN web_admins a ON a.id = s.admin_id"
            ).fetchall()
        out = []
        for r in rows:
            if not r["admin_active"]:
                continue
            if r["admin_role"] == "owner":
                out.append(r)
                continue
            try:
                perms = json.loads(r["admin_permissions"] or "[]")
            except (ValueError, TypeError):
                perms = []
            if permission in perms:
                out.append(r)
        return out


    def is_senior_web_admin(self, role: str) -> bool:
        return role in ("owner", "admin")

    # -----------------------------------------------------------------------
    # لاگ فعالیت ادمین (audit log)
    # -----------------------------------------------------------------------

    def log_admin_action(self, admin_id: int, action: str, details: str = "",
                          record_type: str = None, record_id=None):
        """ثبت یک رخداد حساس (تغییر موجودی کیف‌پول، ویرایش قیمت و ...) در لاگ فعالیت ادمین.
        record_type/record_id اختیاری‌اند و امکان فیلتر «تاریخچه‌ی یک رکورد خاص» را می‌دهند
        (مثلاً همه‌ی رخدادهای سفارش #۱۲۳ یا کاربر ۱۲۳۴۵۶۷۸۹)."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO admin_logs (admin_id, action, details, record_type, record_id, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (admin_id, action, details, record_type,
                 str(record_id) if record_id is not None else None, datetime.utcnow().isoformat()),
            )

    def get_admin_logs(self, limit: int = 50, offset: int = 0, admin_id: int = None,
                        action: str = None, record_type: str = None, record_id=None):
        clauses, params = [], []
        if admin_id is not None:
            clauses.append("admin_id = ?")
            params.append(admin_id)
        if action:
            clauses.append("action = ?")
            params.append(action)
        if record_type:
            clauses.append("record_type = ?")
            params.append(record_type)
        if record_id is not None:
            clauses.append("record_id = ?")
            params.append(str(record_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) c FROM admin_logs {where}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM admin_logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return rows, total

    def list_admin_log_actions(self):
        """لیست یکتای انواع اکشن‌های ثبت‌شده، برای پر کردن فیلتر «نوع اکشن» در پنل."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT action FROM admin_logs ORDER BY action").fetchall()
            return [r["action"] for r in rows]

    # -----------------------------------------------------------------------
    # دسته‌بندی‌ها
    # -----------------------------------------------------------------------

    def add_category(self, name: str) -> int:
        def op():
            with self._get_conn() as conn:
                cur = conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
                return cur.lastrowid
        return self._sqlite_retry(op)

    def get_categories(self, active_only=True):
        with self._get_conn() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order, id"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, id").fetchall()
            return rows

    def get_category(self, cat_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()

    def toggle_category(self, cat_id: int):
        def op():
            with self._get_conn() as conn:
                row = conn.execute("SELECT is_active FROM categories WHERE id=?", (cat_id,)).fetchone()
                if row:
                    new_val = 0 if row["is_active"] else 1
                    conn.execute("UPDATE categories SET is_active=? WHERE id=?", (new_val, cat_id))
                    return True
                return False
        return self._sqlite_retry(op)

    def edit_category(self, cat_id: int, name: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))

    def delete_category(self, cat_id: int):
        def op():
            with self._get_conn() as conn:
                cur = conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
                return cur.rowcount > 0
        return self._sqlite_retry(op)

    # -----------------------------------------------------------------------
    # محصولات
    # -----------------------------------------------------------------------

    def add_product(self, category_id: int, name: str, price: int, description: str = "", duration_days: int = 30,
                     is_auto_provision: bool = False, auto_provision_volume_gb: int = None,
                     provision_server_id: int = None, payment_methods=None) -> int:
        """payment_methods: None/[] یعنی «همه‌ی روش‌های پرداخت مجازند» (پیش‌فرض)،
        در غیر این صورت لیستی از کلیدهای مجاز - همان قراردادِ set_product_payment_methods."""
        pm_value = json.dumps(payment_methods, ensure_ascii=False) if payment_methods else None
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO products (category_id, name, price, description, duration_days, "
                "is_auto_provision, auto_provision_volume_gb, provision_server_id, payment_methods) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (category_id, name, price, description, duration_days,
                 1 if is_auto_provision else 0, auto_provision_volume_gb, provision_server_id, pm_value),
            )
            return cur.lastrowid

    def get_products(self, category_id: int, active_only=True):
        with self._get_conn() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM products WHERE category_id=? AND is_active=1 ORDER BY id",
                    (category_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM products WHERE category_id=? ORDER BY id", (category_id,)
                ).fetchall()
            return rows

    def get_all_products(self):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT p.*, c.name as category_name FROM products p "
                "JOIN categories c ON p.category_id=c.id ORDER BY c.sort_order, p.id"
            ).fetchall()

    def get_product(self, product_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    def toggle_product(self, product_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_active FROM products WHERE id=?", (product_id,)).fetchone()
            if row:
                new_val = 0 if row["is_active"] else 1
                conn.execute("UPDATE products SET is_active=? WHERE id=?", (new_val, product_id))

    def edit_product(self, product_id: int, name: str = None, price: int = None,
                      description: str = None, duration_days: int = None,
                      is_auto_provision: bool = None, auto_provision_volume_gb: int = None,
                      provision_server_id: int = None, payment_methods=...):
        fields, values = [], []
        if name is not None:
            fields.append("name=?"); values.append(name)
        if price is not None:
            fields.append("price=?"); values.append(price)
        if description is not None:
            fields.append("description=?"); values.append(description)
        if duration_days is not None:
            fields.append("duration_days=?"); values.append(duration_days)
        if is_auto_provision is not None:
            fields.append("is_auto_provision=?"); values.append(1 if is_auto_provision else 0)
        if auto_provision_volume_gb is not None:
            fields.append("auto_provision_volume_gb=?"); values.append(auto_provision_volume_gb)
        if provision_server_id is not None:
            fields.append("provision_server_id=?"); values.append(provision_server_id)
        if payment_methods is not ...:
            fields.append("payment_methods=?")
            values.append(json.dumps(payment_methods, ensure_ascii=False) if payment_methods else None)
        if not fields:
            return
        values.append(product_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE products SET {', '.join(fields)} WHERE id=?", values)

    def delete_product(self, product_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM products WHERE id=?", (product_id,))

    # -----------------------------------------------------------------------
    # مخزن کانفیگ (بانک لینک)
    # -----------------------------------------------------------------------

    def add_configs(self, product_id: int, links: list):
        """افزودن لینک‌های بانک کانفیگ با حذف تکراری‌ها.

        تکراری بودن هم نسبت به کل بانک کانفیگ بررسی می‌شود و هم نسبت به
        لینک‌های تکراری داخل همان پیام. خروجی: (added_count, duplicate_count).
        """
        added = 0
        duplicates = 0
        with self._get_conn() as conn:
            # normalize فقط برای تشخیص است؛ مقدار ذخیره‌شده همان لینک تمیزشده است.
            existing = {
                (row["link"] or "").strip()
                for row in conn.execute("SELECT link FROM configs").fetchall()
                if (row["link"] or "").strip()
            }
            seen = set()
            for raw in links:
                link = (raw or "").strip()
                if not link:
                    continue
                if link in existing or link in seen:
                    duplicates += 1
                    continue
                conn.execute(
                    "INSERT INTO configs (product_id, link) VALUES (?, ?)",
                    (product_id, link),
                )
                seen.add(link)
                existing.add(link)
                added += 1
        return added, duplicates

    def count_available_configs(self, product_id: int) -> int:
        with self._get_conn() as conn:
            prod = conn.execute(
                "SELECT is_auto_provision FROM products WHERE id=?", (product_id,)
            ).fetchone()
            if prod and prod["is_auto_provision"]:
                # این محصولات لحظه‌ی خرید و به‌صورت خودکار از اعتبار حجمی نماینده ساخته می‌شوند؛
                # عدد ثابتی به‌عنوان سقفِ معقول تعداد قابل‌خرید در یک سفارش برمی‌گردد (نه موجودی واقعی)،
                # کفایت واقعی اعتبار همان لحظه‌ی خرید در provision_auto_config چک می‌شود.
                return 20
            row = conn.execute(
                "SELECT COUNT(*) c FROM configs WHERE product_id=? AND is_used=0", (product_id,)
            ).fetchone()
            return row["c"]

    def check_low_stock_alert_state(self, product_id: int, stock: int, threshold: int) -> bool:
        """مدیریت وضعیت هشدار موجودی کم برای یک محصول.
        فقط یک‌بار برای هر افت زیر آستانه هشدار می‌دهد (True برمی‌گرداند)، و وقتی موجودی
        دوباره از آستانه بیشتر شد، وضعیت را ریست می‌کند تا برای افت بعدی دوباره هشدار بدهد."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT low_stock_alert_sent FROM products WHERE id=?", (product_id,)
            ).fetchone()
            already_sent = bool(row["low_stock_alert_sent"]) if row else False
            if stock <= threshold and not already_sent:
                conn.execute("UPDATE products SET low_stock_alert_sent=1 WHERE id=?", (product_id,))
                return True
            if stock > threshold and already_sent:
                conn.execute("UPDATE products SET low_stock_alert_sent=0 WHERE id=?", (product_id,))
            return False

    def get_low_stock_overview(self):
        """وضعیت لحظه‌ای موجودی همه‌ی محصولات (غیرِ auto-provision) برای نمایش فقط‌خواندنی
        در پنل وب — بدون تغییر وضعیت هشدار (بر خلاف check_low_stock_alert_state)."""
        threshold = int(self.get_setting("low_stock_threshold", "3") or 3)
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.name, p.low_stock_alert_sent,
                       (SELECT COUNT(*) FROM configs c WHERE c.product_id = p.id AND c.is_used = 0) AS stock
                FROM products p
                WHERE p.is_auto_provision = 0
                ORDER BY p.name
                """
            ).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "name": r["name"],
                "stock": r["stock"],
                "threshold": threshold,
                "low": r["stock"] <= threshold,
                "alerted": bool(r["low_stock_alert_sent"]),
            })
        return out

    def get_config_stats(self, product_id: int) -> dict:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT SUM(CASE WHEN is_used=0 THEN 1 ELSE 0 END) unused, "
                "SUM(CASE WHEN is_used=1 THEN 1 ELSE 0 END) used FROM configs WHERE product_id=?",
                (product_id,),
            ).fetchone()
            return {"unused": row["unused"] or 0, "used": row["used"] or 0}

    def get_unused_configs(self, product_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id, link FROM configs WHERE product_id=? AND is_used=0 ORDER BY id", (product_id,)
            ).fetchall()

    def delete_config(self, config_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM configs WHERE id=? AND is_used=0", (config_id,))

    def take_unused_config(self, product_id: int, user_tg_id: int):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, link FROM configs WHERE product_id=? AND is_used=0 ORDER BY id LIMIT 1",
                (product_id,),
            ).fetchone()
            if not row:
                return None
            prod = conn.execute(
                "SELECT duration_days FROM products WHERE id=?", (product_id,)
            ).fetchone()
            duration_days = (prod["duration_days"] if prod and prod["duration_days"] else 30)
            now = datetime.utcnow()
            expires_at = (now + timedelta(days=duration_days)).isoformat()
            conn.execute(
                "UPDATE configs SET is_used=1, assigned_user_id=?, assigned_at=?, expires_at=?, "
                "renewal_reminder_sent=0, volume_reminder_sent=0 WHERE id=?",
                (user_tg_id, now.isoformat(), expires_at, row["id"]),
            )
            return {"id": row["id"], "link": row["link"], "expires_at": expires_at}

    def take_unused_configs(self, product_id: int, user_tg_id: int, quantity: int = 1):
        """مثل take_unused_config ولی چند کانفیگ را یکجا برمی‌دارد. اگر موجودی کافی
        نباشد، هیچ کانفیگی مصرف نمی‌شود و None برمی‌گردد."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, link FROM configs WHERE product_id=? AND is_used=0 ORDER BY id LIMIT ?",
                (product_id, quantity),
            ).fetchall()
            if len(rows) < quantity:
                return None
            prod = conn.execute(
                "SELECT duration_days FROM products WHERE id=?", (product_id,)
            ).fetchone()
            duration_days = (prod["duration_days"] if prod and prod["duration_days"] else 30)
            now = datetime.utcnow()
            expires_at = (now + timedelta(days=duration_days)).isoformat()
            results = []
            for row in rows:
                conn.execute(
                    "UPDATE configs SET is_used=1, assigned_user_id=?, assigned_at=?, expires_at=?, "
                    "renewal_reminder_sent=0, volume_reminder_sent=0 WHERE id=?",
                    (user_tg_id, now.isoformat(), expires_at, row["id"]),
                )
                results.append({"id": row["id"], "link": row["link"], "expires_at": expires_at})
            return results

    def admin_take_random_config(self, product_id: int, admin_tg_id: int):
        """برای دکمه‌ی «دریافت کانفیگ رندوم» در پنل ادمین: برخلاف take_unused_config
        (که برای فروش واقعی به‌ترتیب FIFO عمل می‌کند)، این یکی از کانفیگ‌های آزاد را
        کاملاً تصادفی برمی‌دارد و مصرف‌شده علامت می‌زند."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, link FROM configs WHERE product_id=? AND is_used=0 ORDER BY RANDOM() LIMIT 1",
                (product_id,),
            ).fetchone()
            if not row:
                return None
            prod = conn.execute(
                "SELECT duration_days FROM products WHERE id=?", (product_id,)
            ).fetchone()
            duration_days = (prod["duration_days"] if prod and prod["duration_days"] else 30)
            now = datetime.utcnow()
            expires_at = (now + timedelta(days=duration_days)).isoformat()
            conn.execute(
                "UPDATE configs SET is_used=1, assigned_user_id=?, assigned_at=?, expires_at=?, "
                "renewal_reminder_sent=0, volume_reminder_sent=0 WHERE id=?",
                (admin_tg_id, now.isoformat(), expires_at, row["id"]),
            )
            return {"id": row["id"], "link": row["link"], "expires_at": expires_at}

    def get_config_by_id(self, config_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()

    def release_config(self, config_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE configs SET is_used=0, assigned_user_id=NULL, assigned_at=NULL, "
                "expires_at=NULL, renewal_reminder_sent=0, volume_reminder_sent=0 WHERE id=?",
                (config_id,),
            )

    # -----------------------------------------------------------------------
    # کانفیگ تست (مخزن جدا)
    # -----------------------------------------------------------------------

    def add_test_configs(self, links: list):
        with self._get_conn() as conn:
            conn.executemany(
                "INSERT INTO test_configs (link) VALUES (?)",
                [(link.strip(),) for link in links if link.strip()],
            )

    def count_available_test_configs(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) c FROM test_configs WHERE is_used=0").fetchone()
            return row["c"]

    def take_unused_test_config(self, user_tg_id: int):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, link FROM test_configs WHERE is_used=0 ORDER BY id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE test_configs SET is_used=1, assigned_user_id=?, assigned_at=? WHERE id=?",
                (user_tg_id, datetime.utcnow().isoformat(), row["id"]),
            )
            return {"id": row["id"], "link": row["link"]}

    def get_assigned_test_config(self, user_tg_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id, link FROM test_configs WHERE assigned_user_id=? ORDER BY id DESC LIMIT 1",
                (user_tg_id,),
            ).fetchone()

    # -----------------------------------------------------------------------
    # پلن‌های کانفیگ تست (مثل محصولات: چند مدل، هرکدام با پنل/حجم/مدت خودشان)
    # -----------------------------------------------------------------------

    def get_test_config_plans(self, active_only: bool = False):
        q = "SELECT * FROM test_config_plans"
        if active_only:
            q += " WHERE is_active=1"
        q += " ORDER BY sort_order, id"
        with self._get_conn() as conn:
            return conn.execute(q).fetchall()

    def count_active_test_config_plans(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) c FROM test_config_plans WHERE is_active=1").fetchone()
            return row["c"]

    def get_test_config_plan(self, plan_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM test_config_plans WHERE id=?", (plan_id,)).fetchone()

    def create_test_config_plan(self, name: str, name_prefix: str, panel_server_id: int,
                                 volume_mb: int, duration_hours: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM test_config_plans").fetchone()
            cur = conn.execute(
                "INSERT INTO test_config_plans (name, name_prefix, panel_server_id, volume_mb, "
                "duration_hours, is_active, sort_order) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (name, name_prefix, panel_server_id, volume_mb, duration_hours, row["m"] + 1),
            )
            return cur.lastrowid

    def update_test_config_plan(self, plan_id: int, **fields) -> None:
        """fields می‌تواند شامل هرکدام از ستون‌های test_config_plans باشد،
        مثلاً update_test_config_plan(3, name=\"پلن یک‌ساعته\", is_active=0)."""
        if not fields:
            return
        allowed = {"name", "name_prefix", "panel_server_id", "volume_mb", "duration_hours",
                   "is_active", "sort_order"}
        sets, values = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k}=?")
                values.append(v)
        if not sets:
            return
        values.append(plan_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE test_config_plans SET {', '.join(sets)} WHERE id=?", values)

    def delete_test_config_plan(self, plan_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM test_config_plans WHERE id=?", (plan_id,))

    def toggle_test_config_plan(self, plan_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE test_config_plans SET is_active = 1 - is_active WHERE id=?", (plan_id,)
            )

    # -----------------------------------------------------------------------
    # سفارش‌ها
    # -----------------------------------------------------------------------

    def create_order(
        self,
        user_tg_id: int,
        product_id: int,
        base_price: int,
        wallet_used: int = 0,
        discount_code_id: int = None,
        discount_amount: int = 0,
        quantity: int = 1,
    ) -> int:
        final_price = max(base_price - wallet_used - discount_amount, 0)
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (user_id, product_id, status, base_price, wallet_used, "
                "discount_code_id, discount_amount, final_price, quantity) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
                (user_tg_id, product_id, base_price, wallet_used, discount_code_id, discount_amount, final_price, quantity),
            )
            return cur.lastrowid

    def create_custom_config_order(
        self,
        user_tg_id: int,
        volume_gb: int,
        username: str,
        panel_server_id: int,
        base_price: int,
        wallet_used: int = 0,
        custom_product_id: int = None,
        custom_duration_days: int = None,
    ) -> int:
        """سفارش «ساخت کانفیگ شخصی» - از همان جدول orders استفاده می‌کند (product_id=0
        سنتینل بدون FK) تا مسیر پرداخت کارت/کیف‌پول/کریپتوی فعلی بدون تغییر کار کند.
        custom_product_id به یک ردیف custom_config_products اشاره می‌کند؛ NULL یعنی
        سفارش از مسیر سراسری قدیمی (تک‌محصولی) ثبت شده است. custom_duration_days
        همان لحظه‌ی ثبت سفارش قفل می‌شود (چه از مدت ثابت محصول، چه از انتخاب
        کاربر) تا مسیرهای مختلف تایید سفارش (دستی/درگاه خودکار) مجبور نباشند
        دوباره تنظیمات/محصول را برای محاسبه‌ی مدت لوکاپ کنند."""
        final_price = max(base_price - wallet_used, 0)
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (user_id, product_id, status, base_price, wallet_used, final_price, "
                "quantity, is_custom_config, custom_volume_gb, custom_username, custom_panel_server_id, "
                "custom_product_id, custom_duration_days) VALUES (?, 0, 'pending', ?, ?, ?, 1, 1, ?, ?, ?, ?, ?)",
                (user_tg_id, base_price, wallet_used, final_price, volume_gb, username, panel_server_id,
                 custom_product_id, custom_duration_days),
            )
            return cur.lastrowid

    def approve_custom_config_order(self, order_id: int) -> bool:
        """فقط اگر سفارش pending یا processing (بعد از claim_order) باشد اعمال می‌شود."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='approved', updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (datetime.utcnow().isoformat(), order_id),
            )
            return cur.rowcount > 0

    def create_renewal_order(
        self,
        user_tg_id: int,
        target_kind: str,
        target_id: int,
        mode: str,
        add_volume_gb: int,
        add_days: int,
        base_price: int,
        wallet_used: int = 0,
    ) -> int:
        """سفارش «تمدید سرویس» از حساب کاربری - مثل is_custom_config از همان جدول
        orders با product_id=0 سنتینل استفاده می‌کند تا همه‌ی روش‌های پرداخت
        (کارت/کیف‌پول/کریپتو/آبان‌گیت‌وی/درگاه سفارشی) بدون تغییر کار کنند."""
        final_price = max(base_price - wallet_used, 0)
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (user_id, product_id, status, base_price, wallet_used, final_price, "
                "quantity, is_renewal, renewal_target_kind, renewal_target_id, renewal_mode, "
                "renewal_add_volume_gb, renewal_add_days) VALUES (?, 0, 'pending', ?, ?, ?, 1, 1, ?, ?, ?, ?, ?)",
                (user_tg_id, base_price, wallet_used, final_price, target_kind, target_id, mode, add_volume_gb, add_days),
            )
            return cur.lastrowid

    def approve_renewal_order(self, order_id: int) -> bool:
        """فقط اگر سفارش pending یا processing (بعد از claim_order) باشد تایید می‌کند."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='approved', updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (datetime.utcnow().isoformat(), order_id),
            )
            return cur.rowcount > 0

    def set_order_receipt(self, order_id: int, file_id: str, receipt_type: str = "photo"):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE orders SET receipt_file_id=?, receipt_type=? WHERE id=?",
                (file_id, receipt_type, order_id),
            )

    def set_order_admin_message(self, order_id: int, admin_chat_id: int, admin_message_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE orders SET admin_chat_id=?, admin_message_id=? WHERE id=?",
                (admin_chat_id, admin_message_id, order_id),
            )

    def get_order(self, order_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    def claim_order(self, order_id: int) -> bool:
        """قبل از اجرای عملیات جانبی (تمدید روی پنل، ساخت کانفیگ) صدا زده می‌شود تا از
        اجرای همزمان دو تایید برای یک سفارش (مثلاً کال‌بک تکراری درگاه) جلوگیری شود.
        اگر سفارش pending باشد آن را processing می‌کند و True برمی‌گرداند، وگرنه False."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='processing', updated_at=? WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), order_id),
            )
            return cur.rowcount > 0

    def release_order_claim(self, order_id: int):
        """در صورت شکست عملیات جانبی بعد از claim_order، سفارش را به pending برمی‌گرداند
        تا قابل تلاش مجدد (توسط ادمین یا وب‌هوک بعدی) باشد."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE orders SET status='pending', updated_at=? WHERE id=? AND status='processing'",
                (datetime.utcnow().isoformat(), order_id),
            )

    def approve_order(self, order_id: int, config_ids) -> bool:
        """config_ids می‌تواند یک id تکی یا لیستی از id ها باشد (برای سفارش با تعداد بیشتر از ۱).
        config_id ستون سفارش برای سازگاری با کدهای قدیمی، همیشه اولین کانفیگ را نگه می‌دارد؛
        برای گرفتن همه‌ی کانفیگ‌های یک سفارش از get_order_configs استفاده کن.
        فقط اگر سفارش pending یا processing (بعد از claim_order) باشد اعمال می‌شود."""
        if isinstance(config_ids, int):
            config_ids = [config_ids]
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='approved', config_id=?, updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (config_ids[0], datetime.utcnow().isoformat(), order_id),
            )
            if cur.rowcount == 0:
                return False
            conn.executemany(
                "UPDATE configs SET order_id=? WHERE id=?",
                [(order_id, cid) for cid in config_ids],
            )
            return True

    def approve_order_auto(self, order_id: int) -> bool:
        """تایید سفارش محصولات is_auto_provision که کانفیگشان لحظه‌ی خرید و بدون
        استفاده از بانک کانفیگ ساخته می‌شود (بدون config_id).
        فقط اگر سفارش pending یا processing (بعد از claim_order) باشد اعمال می‌شود."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='approved', updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (datetime.utcnow().isoformat(), order_id),
            )
            return cur.rowcount > 0

    def get_order_configs(self, order_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM configs WHERE order_id=? ORDER BY id", (order_id,)
            ).fetchall()

    def reject_order(self, order_id: int) -> bool:
        """فقط سفارش pending را رد می‌کند (نه processing/approved)، تا با یک تایید
        هم‌زمان (claim_order) تداخل نکند. در صورت رد شدن، مبلغ کیف پول را برمی‌گرداند."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='rejected', updated_at=? WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), order_id),
            )
            if cur.rowcount == 0:
                return False
        order = self.get_order(order_id)
        if order:
            if order["wallet_used"]:
                self.add_wallet_credit(order["user_id"], order["wallet_used"])
            if order["discount_code_id"]:
                self.decrement_discount_usage(order["discount_code_id"])
        return True

    def get_orders_by_status(self, status: str, limit: int = 200):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
            ).fetchall()

    def get_pending_orders(self):
        """سفارش‌های نیازمند بررسی دستی؛ سفارش‌هایی که برایشان فاکتور کریپتو ساخته شده‌اند اینجا نمی‌آیند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT o.* FROM orders o "
                "WHERE o.status='pending' "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='order' AND ci.ref_id=o.id) "
                "ORDER BY o.id"
            ).fetchall()

    def get_latest_pending_order_awaiting_receipt(self, user_tg_id: int):
        """آخرین سفارش (عادی یا کانفیگ شخصی) این کاربر که هنوز pending است و رسیدی
        برایش ثبت نشده - برای fallback بازیابی رسیدهایی که به‌خاطر گم‌شدن FSM state
        (مثلاً ری‌استارت بات) به هندلر state-دار اصلی نرسیده‌اند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE user_id=? AND status='pending' "
                "AND receipt_file_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='order' AND ci.ref_id=orders.id) "
                "ORDER BY id DESC LIMIT 1",
                (user_tg_id,),
            ).fetchone()

    def get_user_orders(self, user_tg_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE user_id=? AND (user_deleted IS NULL OR user_deleted=0) "
                "ORDER BY id DESC",
                (user_tg_id,),
            ).fetchall()

    def delete_owned_config(self, config_id: int, user_tg_id: int):
        """حذف کامل و برگشت‌ناپذیر یک کانفیگ متعلق به همین کاربر (از بانک محصولات).
        اگر کانفیگ متعلق به این کاربر نباشد، None برمی‌گرداند و کاری انجام نمی‌شود.
        اگر با این حذف، سفارشی که این کانفیگ از آن بود دیگر هیچ کانفیگی نداشته
        باشد، آن سفارش هم از لیست «سفارش‌های من» کاربر مخفی می‌شود (بدون این‌که
        از دیتابیس یا گزارش‌های ادمین حذف شود)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM configs WHERE id=? AND assigned_user_id=?", (config_id, user_tg_id)
            ).fetchone()
            if not row:
                return None
            order_id = row["order_id"]
            conn.execute("DELETE FROM configs WHERE id=?", (config_id,))
            if order_id:
                remaining = conn.execute(
                    "SELECT COUNT(*) c FROM configs WHERE order_id=?", (order_id,)
                ).fetchone()["c"]
                if remaining == 0:
                    conn.execute(
                        "UPDATE orders SET user_deleted=1 WHERE id=? AND user_id=?", (order_id, user_tg_id)
                    )
            return dict(row)

    def delete_owned_custom_config(self, custom_config_id: int, user_tg_id: int):
        """حذف کامل و برگشت‌ناپذیر یک کانفیگ شخصی متعلق به همین کاربر. فقط ردیف
        دیتابیس را حذف می‌کند؛ حذف واقعی کاربر از روی پنل VPN (در صورت وجود
        panel_server_id) باید قبل از فراخوانی این متد و جداگانه انجام شود."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM custom_configs WHERE id=? AND user_id=?", (custom_config_id, user_tg_id)
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM custom_configs WHERE id=?", (custom_config_id,))
            return dict(row)

    # -----------------------------------------------------------------------
    # آمار
    # -----------------------------------------------------------------------

    def get_stats(self):
        with self._get_conn() as conn:
            users_c = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            pending_c = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='pending'").fetchone()["c"]
            approved_c = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='approved'").fetchone()["c"]
            rejected_c = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='rejected'").fetchone()["c"]
            revenue = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(o.final_price, p.price)),0) s FROM orders o "
                "JOIN products p ON o.product_id=p.id WHERE o.status='approved'"
            ).fetchone()["s"]
            return {
                "users": users_c,
                "pending": pending_c,
                "approved": approved_c,
                "rejected": rejected_c,
                "revenue": revenue,
            }

    def get_sales_stats(self, start_date: str = None, end_date: str = None):
        """آمار فروش کامل برای یک بازه‌ی زمانی دلخواه.
        start_date/end_date به فرمت 'YYYY-MM-DD' (شامل خود آن روزها).
        اگر داده نشوند، پیش‌فرض ۱۴ روز اخیر است.
        شامل: کارت‌های خلاصه، مقایسه با بازه‌ی هم‌طول قبلی، نرخ تبدیل، میانگین سبد خرید،
        روند روزانه، تفکیک درآمد بر اساس دسته‌بندی، سهم رفرال در مقابل خرید مستقیم،
        و پرفروش‌ترین محصولات (همه محدود به همان بازه)."""
        with self._get_conn() as conn:
            if not end_date:
                end_date = conn.execute("SELECT date('now') d").fetchone()["d"]
            if not start_date:
                start_date = conn.execute("SELECT date(?, '-13 days') d", (end_date,)).fetchone()["d"]

            length_days = conn.execute(
                "SELECT CAST(julianday(?) - julianday(?) AS INTEGER) + 1 d", (end_date, start_date)
            ).fetchone()["d"]
            if length_days < 1:
                length_days = 1

            prev_end = conn.execute("SELECT date(?, '-1 day') d", (start_date,)).fetchone()["d"]
            prev_start = conn.execute(
                "SELECT date(?, ?) d", (prev_end, f"-{length_days - 1} days")
            ).fetchone()["d"]

            def _period_totals(s, e):
                row = conn.execute(
                    "SELECT "
                    "SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) approved_c, "
                    "SUM(CASE WHEN o.status='pending' THEN 1 ELSE 0 END) pending_c, "
                    "SUM(CASE WHEN o.status='rejected' THEN 1 ELSE 0 END) rejected_c, "
                    "COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue "
                    "FROM orders o JOIN products p ON o.product_id=p.id "
                    "WHERE date(o.created_at) BETWEEN ? AND ?",
                    (s, e),
                ).fetchone()
                approved = row["approved_c"] or 0
                pending = row["pending_c"] or 0
                rejected = row["rejected_c"] or 0
                revenue = row["revenue"] or 0
                decided = approved + rejected
                conversion = round(approved / decided * 100, 1) if decided else 0.0
                aov = round(revenue / approved) if approved else 0
                return {
                    "approved": approved, "pending": pending, "rejected": rejected,
                    "revenue": revenue, "conversion_rate": conversion, "aov": aov,
                }

            current = _period_totals(start_date, end_date)
            previous = _period_totals(prev_start, prev_end)

            def _pct_change(cur, prev):
                if prev == 0:
                    return None if cur == 0 else 100.0
                return round((cur - prev) / prev * 100, 1)

            current["revenue_change_pct"] = _pct_change(current["revenue"], previous["revenue"])
            current["orders_change_pct"] = _pct_change(current["approved"], previous["approved"])
            current["prev_revenue"] = previous["revenue"]
            current["prev_approved"] = previous["approved"]

            new_users = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE date(joined_at) BETWEEN ? AND ?", (start_date, end_date)
            ).fetchone()["c"]
            current["new_users"] = new_users

            daily_rows = conn.execute(
                "SELECT date(o.created_at) d, "
                "COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue, "
                "SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) orders "
                "FROM orders o JOIN products p ON o.product_id=p.id "
                "WHERE date(o.created_at) BETWEEN ? AND ? "
                "GROUP BY date(o.created_at)",
                (start_date, end_date),
            ).fetchall()
            daily_map = {r["d"]: {"revenue": r["revenue"], "orders": r["orders"]} for r in daily_rows}
            daily_series = []
            for i in range(length_days):
                d = conn.execute("SELECT date(?, ?) d", (start_date, f"+{i} days")).fetchone()["d"]
                entry = daily_map.get(d, {"revenue": 0, "orders": 0})
                daily_series.append({"date": d, "revenue": entry["revenue"], "orders": entry["orders"]})

            category_rows = conn.execute(
                "SELECT c.name name, COUNT(*) orders, COALESCE(SUM(COALESCE(o.final_price, p.price)),0) revenue "
                "FROM orders o JOIN products p ON o.product_id=p.id JOIN categories c ON p.category_id=c.id "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ? "
                "GROUP BY c.id ORDER BY revenue DESC",
                (start_date, end_date),
            ).fetchall()
            category_breakdown = [
                {"name": r["name"], "orders": r["orders"], "revenue": r["revenue"]} for r in category_rows
            ]

            referral_row = conn.execute(
                "SELECT "
                "COALESCE(SUM(CASE WHEN u.referred_by IS NOT NULL THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) referral_revenue, "
                "COALESCE(SUM(CASE WHEN u.referred_by IS NULL THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) direct_revenue "
                "FROM orders o JOIN products p ON o.product_id=p.id JOIN users u ON o.user_id=u.telegram_id "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()
            current["referral_revenue"] = referral_row["referral_revenue"] or 0
            current["direct_revenue"] = referral_row["direct_revenue"] or 0

            top_products = conn.execute(
                "SELECT p.name name, COUNT(*) c, COALESCE(SUM(COALESCE(o.final_price, p.price)),0) s "
                "FROM orders o JOIN products p ON o.product_id=p.id "
                "WHERE o.status='approved' AND date(o.created_at) BETWEEN ? AND ? "
                "GROUP BY p.id ORDER BY c DESC LIMIT 5",
                (start_date, end_date),
            ).fetchall()

            total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            active_configs_c = conn.execute("SELECT COUNT(*) c FROM configs WHERE is_used=1").fetchone()["c"]
            open_tickets_c = conn.execute(
                "SELECT COUNT(*) c FROM tickets WHERE status IN ('open','answered')"
            ).fetchone()["c"]
            wallet_total = conn.execute("SELECT COALESCE(SUM(referral_credit),0) s FROM users").fetchone()["s"]

            current.update({
                "start_date": start_date,
                "end_date": end_date,
                "total_users": total_users,
                "active_configs": active_configs_c,
                "open_tickets": open_tickets_c,
                "wallet_total": wallet_total,
                "daily_series": daily_series,
                "category_breakdown": category_breakdown,
                "top_products": [{"name": r["name"], "orders": r["c"], "revenue": r["s"]} for r in top_products],
            })
            return current

    def get_full_stats(self, start_date: str = None, end_date: str = None) -> dict:
        """آمار کامل: get_sales_stats به‌علاوه‌ی موجودی انبار، تیکت‌ها و مشتریان تکراری.
        منبع واحد برای بات، مینی‌اپ و پنل وب تا هر سه دقیقاً یک عدد نشان دهند."""
        stats = self.get_sales_stats(start_date, end_date)
        s, e = stats["start_date"], stats["end_date"]
        threshold = int(self.get_setting("low_stock_threshold", "3") or 3)
        with self._get_conn() as conn:
            inventory_rows = conn.execute(
                "SELECT p.id, p.name name, "
                "SUM(CASE WHEN c.is_used=0 THEN 1 ELSE 0 END) unused, "
                "SUM(CASE WHEN c.is_used=1 THEN 1 ELSE 0 END) used "
                "FROM products p LEFT JOIN configs c ON c.product_id=p.id "
                "WHERE p.is_active=1 GROUP BY p.id ORDER BY p.name"
            ).fetchall()
            inventory = [
                {
                    "product_id": r["id"], "name": r["name"],
                    "unused": r["unused"] or 0, "used": r["used"] or 0,
                    "low_stock": (r["unused"] or 0) <= threshold,
                }
                for r in inventory_rows
            ]
            low_stock_products = [i for i in inventory if i["low_stock"]]

            ticket_row = conn.execute(
                "SELECT COUNT(*) c, SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) open_c, "
                "SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) closed_c "
                "FROM tickets WHERE date(created_at) BETWEEN ? AND ?", (s, e),
            ).fetchone()
            first_response_rows = conn.execute(
                "SELECT t.created_at t_created, MIN(m.created_at) first_admin_reply "
                "FROM tickets t JOIN ticket_messages m ON m.ticket_id=t.id AND m.sender='admin' "
                "WHERE date(t.created_at) BETWEEN ? AND ? GROUP BY t.id", (s, e),
            ).fetchall()
            response_minutes = [
                (conn.execute("SELECT (julianday(?) - julianday(?)) * 1440 d",
                               (r["first_admin_reply"], r["t_created"])).fetchone()["d"])
                for r in first_response_rows
            ]
            avg_response_minutes = round(sum(response_minutes) / len(response_minutes), 1) if response_minutes else None

            repeat_customers = conn.execute(
                "SELECT COUNT(*) c FROM (SELECT user_id FROM orders WHERE status='approved' "
                "GROUP BY user_id HAVING COUNT(*) > 1)"
            ).fetchone()["c"]
            total_customers = conn.execute(
                "SELECT COUNT(DISTINCT user_id) c FROM orders WHERE status='approved'"
            ).fetchone()["c"]
            repeat_rate = round(repeat_customers / total_customers * 100, 1) if total_customers else 0.0

        stats.update({
            "inventory": inventory,
            "low_stock_products": low_stock_products,
            "tickets_created": ticket_row["c"] or 0,
            "tickets_open": ticket_row["open_c"] or 0,
            "tickets_closed": ticket_row["closed_c"] or 0,
            "avg_ticket_response_minutes": avg_response_minutes,
            "repeat_customers": repeat_customers,
            "total_customers": total_customers,
            "repeat_customer_rate": repeat_rate,
        })
        return stats

    def get_orders_for_export(self, start_date: str = None, end_date: str = None):
        """لیست خام سفارش‌ها برای خروجی CSV، در بازه‌ی زمانی داده‌شده."""
        with self._get_conn() as conn:
            if not end_date:
                end_date = conn.execute("SELECT date('now') d").fetchone()["d"]
            if not start_date:
                start_date = conn.execute("SELECT date(?, '-13 days') d", (end_date,)).fetchone()["d"]
            rows = conn.execute(
                "SELECT o.id, o.created_at, o.status, o.user_id, u.username, u.first_name, "
                "p.name as product_name, COALESCE(o.final_price, p.price) as amount, "
                "o.wallet_used, o.discount_amount, COALESCE(o.quantity, 1) as quantity "
                "FROM orders o "
                "JOIN products p ON o.product_id=p.id "
                "LEFT JOIN users u ON o.user_id=u.telegram_id "
                "WHERE date(o.created_at) BETWEEN ? AND ? "
                "ORDER BY o.id DESC",
                (start_date, end_date),
            ).fetchall()
            return rows

    # -----------------------------------------------------------------------
    # زیرمجموعه‌گیری (رفرال) و کیف پول اعتباری
    # -----------------------------------------------------------------------

    def set_referred_by(self, user_tg_id: int, referrer_tg_id: int):
        if user_tg_id == referrer_tg_id:
            return
        with self._get_conn() as conn:
            row = conn.execute("SELECT referred_by FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
            if row and row["referred_by"] is None:
                referrer_exists = conn.execute(
                    "SELECT 1 FROM users WHERE telegram_id=?", (referrer_tg_id,)
                ).fetchone()
                if referrer_exists:
                    conn.execute(
                        "UPDATE users SET referred_by=? WHERE telegram_id=?", (referrer_tg_id, user_tg_id)
                    )

    def get_referral_stats(self, user_tg_id: int) -> dict:
        with self._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE referred_by=?", (user_tg_id,)
            ).fetchone()["c"]
            row = conn.execute(
                "SELECT referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            credit = row["referral_credit"] if row else 0
            return {"count": count, "credit": credit}

    def get_wallet_credit(self, user_tg_id: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            return row["referral_credit"] if row else 0

    def add_wallet_credit(self, user_tg_id: int, delta: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET referral_credit = MAX(referral_credit + ?, 0) WHERE telegram_id=?",
                (delta, user_tg_id),
            )

    def reward_referrer_if_first_purchase(self, referred_user_tg_id: int, paid_amount: int):
        """حالت ۱ از سه مدل زیرمجموعه‌گیری: پورسانت درصدی، فقط برای اولین خرید هر
        زیرمجموعه، و در صورت تنظیم بودن سقف (referral_commission_max_count)، فقط برای
        همان تعداد اول از زیرمجموعه‌هایی که خرید کرده‌اند."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT referred_by, referral_first_purchase_rewarded FROM users WHERE telegram_id=?",
                (referred_user_tg_id,),
            ).fetchone()
            if not row or not row["referred_by"] or row["referral_first_purchase_rewarded"]:
                return None
            referrer_id = row["referred_by"]

            if self.get_setting("referral_button_enabled", "1") != "1":
                return None
            if self.get_setting("referral_enabled", "1") != "1":
                return None

            max_count = int(self.get_setting("referral_commission_max_count", "0") or 0)
            if max_count > 0:
                already = conn.execute(
                    "SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_first_purchase_rewarded=1",
                    (referrer_id,),
                ).fetchone()["c"]
                if already >= max_count:
                    # سقف پر شده؛ همچنان به‌عنوان «رویدادِ اولین خرید» علامت می‌زنیم تا دوباره بررسی نشود
                    conn.execute(
                        "UPDATE users SET referral_first_purchase_rewarded=1 WHERE telegram_id=?",
                        (referred_user_tg_id,),
                    )
                    return None

            conn.execute(
                "UPDATE users SET referral_first_purchase_rewarded=1 WHERE telegram_id=?",
                (referred_user_tg_id,),
            )

        percent = int(self.get_setting("referral_percent", "10") or 0)
        reward = (paid_amount * percent) // 100
        if reward > 0:
            self.add_wallet_credit(referrer_id, reward)
            return reward, referrer_id
        return None

    def apply_referral_invite_rewards(self, referred_user_tg_id: int, referrer_tg_id: int) -> dict:
        """بلافاصله بعد از ثبت یک دعوت جدید (بدون نیاز به خرید) صدا زده می‌شود و
        حالت‌های ۲ و ۳ مدل زیرمجموعه‌گیری را بررسی/اعمال می‌کند:
        - حالت ۳: شارژ ثابت کیف پول به‌ازای هر دعوت، تا سقف مشخص.
        - حالت ۲: دریافت یک محصول مشخص و رایگان با رسیدن تعداد دعوت‌ها به یک آستانه.
        خروجی: {"invite_bonus": مبلغ یا None, "free_config_product_id": آیدی محصول یا None}
        """
        result = {"invite_bonus": None, "free_config_product_id": None}
        if self.get_setting("referral_button_enabled", "1") != "1":
            return result
        with self._get_conn() as conn:
            referrer = conn.execute(
                "SELECT referral_free_config_given FROM users WHERE telegram_id=?", (referrer_tg_id,)
            ).fetchone()
            if not referrer:
                return result

            # --- حالت ۳: شارژ ثابت کیف پول برای هر دعوت، تا سقف مشخص ---
            if self.get_setting("referral_invite_bonus_enabled", "0") == "1":
                amount = int(self.get_setting("referral_invite_bonus_amount", "0") or 0)
                max_count = int(self.get_setting("referral_invite_bonus_max_count", "0") or 0)
                already = conn.execute(
                    "SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_invite_bonus_given=1",
                    (referrer_tg_id,),
                ).fetchone()["c"]
                if amount > 0 and (max_count == 0 or already < max_count):
                    conn.execute(
                        "UPDATE users SET referral_invite_bonus_given=1 WHERE telegram_id=?",
                        (referred_user_tg_id,),
                    )
                    conn.execute(
                        "UPDATE users SET referral_credit = MAX(referral_credit + ?, 0) WHERE telegram_id=?",
                        (amount, referrer_tg_id),
                    )
                    result["invite_bonus"] = amount

            # --- حالت ۲: محصول رایگان با رسیدن تعداد دعوت‌ها به یک آستانه (یک‌بار) ---
            if (
                self.get_setting("referral_free_config_enabled", "0") == "1"
                and not referrer["referral_free_config_given"]
            ):
                threshold = int(self.get_setting("referral_free_config_threshold", "0") or 0)
                product_id = self.get_setting("referral_free_config_product_id", "") or ""
                if threshold > 0 and product_id:
                    invited_count = conn.execute(
                        "SELECT COUNT(*) c FROM users WHERE referred_by=?", (referrer_tg_id,)
                    ).fetchone()["c"]
                    if invited_count >= threshold:
                        conn.execute(
                            "UPDATE users SET referral_free_config_given=1 WHERE telegram_id=?",
                            (referrer_tg_id,),
                        )
                        result["free_config_product_id"] = int(product_id)

        return result

    # -----------------------------------------------------------------------
    # کدهای تخفیف
    # -----------------------------------------------------------------------

    def create_discount_code(
        self, code: str, percent: int = None, fixed_amount: int = None, max_uses: int = 0,
        expires_at: str = None, source: str = "admin",
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO discount_codes (code, percent, fixed_amount, max_uses, expires_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (code.strip().upper(), percent, fixed_amount, max_uses, expires_at, source),
            )
            return cur.lastrowid

    def get_discount_code(self, code: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM discount_codes WHERE code=?", (code.strip().upper(),)
            ).fetchone()

    def get_discount_code_by_id(self, code_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM discount_codes WHERE id=?", (code_id,)).fetchone()

    def list_discount_codes(self):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM discount_codes ORDER BY id DESC").fetchall()

    def toggle_discount_code(self, code_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_active FROM discount_codes WHERE id=?", (code_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE discount_codes SET is_active=? WHERE id=?",
                    (0 if row["is_active"] else 1, code_id),
                )

    def delete_discount_code(self, code_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM discount_codes WHERE id=?", (code_id,))

    def increment_discount_usage(self, code_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE discount_codes SET used_count = used_count + 1 WHERE id=?", (code_id,))

    def decrement_discount_usage(self, code_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE discount_codes SET used_count = MAX(used_count - 1, 0) WHERE id=?", (code_id,)
            )

    def is_discount_code_valid(self, row) -> bool:
        if not row:
            return False
        if not row["is_active"]:
            return False
        if row["max_uses"] and row["used_count"] >= row["max_uses"]:
            return False
        expires_at = row["expires_at"] if "expires_at" in row.keys() else None
        if expires_at and datetime.utcnow().isoformat() > expires_at:
            return False
        return True

    def compute_discount_amount(self, row, price: int) -> int:
        if row["percent"]:
            return min((price * row["percent"]) // 100, price)
        if row["fixed_amount"]:
            return min(row["fixed_amount"], price)
        return 0

    # -----------------------------------------------------------------------
    # شارژ کیف پول
    # -----------------------------------------------------------------------

    def create_topup(self, user_tg_id: int, amount: int) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO wallet_topups (user_id, amount, status) VALUES (?, ?, 'pending')",
                (user_tg_id, amount),
            )
            return cur.lastrowid

    def set_topup_receipt(self, topup_id: int, file_id: str, receipt_type: str = "photo"):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE wallet_topups SET receipt_file_id=?, receipt_type=? WHERE id=?",
                (file_id, receipt_type, topup_id),
            )

    def set_topup_admin_message(self, topup_id: int, admin_chat_id: int, admin_message_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE wallet_topups SET admin_chat_id=?, admin_message_id=? WHERE id=?",
                (admin_chat_id, admin_message_id, topup_id),
            )

    def get_topup(self, topup_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM wallet_topups WHERE id=?", (topup_id,)).fetchone()

    def get_latest_pending_topup_awaiting_receipt(self, user_tg_id: int):
        """آخرین درخواست شارژ کیف‌پول این کاربر که هنوز pending است و رسیدی
        برایش ثبت نشده - برای fallback بازیابی رسیدهایی که FSM state‌شان گم شده."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM wallet_topups WHERE user_id=? AND status='pending' "
                "AND receipt_file_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='wallet_topup' AND ci.ref_id=wallet_topups.id) "
                "ORDER BY id DESC LIMIT 1",
                (user_tg_id,),
            ).fetchone()

    def approve_topup(self, topup_id: int) -> bool:
        """فقط اگر topup هنوز pending یا processing (بعد از claim_topup) باشد اعمال می‌شود."""
        topup = self.get_topup(topup_id)
        if not topup:
            return False
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE wallet_topups SET status='approved', updated_at=? WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), topup_id),
            )
            if cur.rowcount == 0:
                return False
        self.add_wallet_credit(topup["user_id"], topup["amount"])
        return True

    def reject_topup(self, topup_id: int) -> bool:
        """فقط topup pending را رد می‌کند (نه processing/approved)."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE wallet_topups SET status='rejected', updated_at=? WHERE id=? AND status='pending'",
                (datetime.utcnow().isoformat(), topup_id),
            )
            return cur.rowcount > 0

    def get_topups_by_status(self, status: str, limit: int = 200):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM wallet_topups WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
            ).fetchall()

    def get_pending_topups(self):
        """شارژهای نیازمند بررسی دستی؛ شارژهای دارای فاکتور کریپتو اینجا نمی‌آیند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT t.* FROM wallet_topups t "
                "WHERE t.status='pending' "
                "AND NOT EXISTS (SELECT 1 FROM crypto_invoices ci WHERE ci.kind='wallet_topup' AND ci.ref_id=t.id) "
                "ORDER BY t.id"
            ).fetchall()

    # -----------------------------------------------------------------------
    # ثبت‌نام بات‌های نمایندگی (فقط در دیتابیس بات اصلی معنا دارد)
    # -----------------------------------------------------------------------

    def register_reseller_bot(self, bot_token: str, bot_username: str, owner_telegram_id: int, owner_name: str,
                               db_path: str, reseller_level: int = 2) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO reseller_bots (bot_token, bot_username, owner_telegram_id, owner_name, db_path, reseller_level) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (bot_token, bot_username, owner_telegram_id, owner_name, db_path, reseller_level),
            )
            return cur.lastrowid

    def get_reseller_bot_by_token(self, bot_token: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_bots WHERE bot_token=?", (bot_token,)).fetchone()

    def list_reseller_bots(self, active_only: bool = False):
        with self._get_conn() as conn:
            if active_only:
                return conn.execute("SELECT * FROM reseller_bots WHERE is_active=1 ORDER BY id").fetchall()
            return conn.execute("SELECT * FROM reseller_bots ORDER BY id").fetchall()

    def get_bot_revenue_summary(self):
        """جمع فروش (سفارش‌های تاییدشده) روی همین دیتابیس - برای نمایش میزان فروش هر
        نماینده‌ی کامل (سطح ۱) که دیتابیس/باتِ مستقل خودش را دارد، از پنل وب اصلی."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN o.status='approved' THEN COALESCE(o.final_price, p.price) ELSE 0 END),0) revenue, "
                "COUNT(CASE WHEN o.status='approved' THEN 1 END) cnt "
                "FROM orders o LEFT JOIN products p ON p.id=o.product_id"
            ).fetchone()
        return {"revenue_toman": row["revenue"] or 0, "paid_orders": row["cnt"] or 0}

    def get_reseller_sales_map(self):
        """برای هر نماینده‌ی اعتباری (سطح ۲)، تعداد و مجموع حجم کانفیگ‌هایی که از اعتبار
        حجمی خودش برای مشتری‌هایش ساخته (source='reseller' در custom_configs)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, COUNT(*) cnt, COALESCE(SUM(volume_gb),0) gb "
                "FROM custom_configs WHERE source='reseller' GROUP BY user_id"
            ).fetchall()
        return {r["user_id"]: {"configs": r["cnt"], "volume_gb": r["gb"]} for r in rows}

    def get_reseller_bot(self, bot_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_bots WHERE id=?", (bot_id,)).fetchone()

    def set_reseller_level(self, bot_id: int, level: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE reseller_bots SET reseller_level=? WHERE id=?", (level, bot_id))

    def get_reseller_bot_by_slug(self, slug: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_bots WHERE link_slug=?", (slug,)).fetchone()

    def set_reseller_link_slug(self, bot_id: int, slug: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE reseller_bots SET link_slug=? WHERE id=?", (slug, bot_id))

    def toggle_reseller_bot(self, bot_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_active FROM reseller_bots WHERE id=?", (bot_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE reseller_bots SET is_active=? WHERE id=?", (0 if row["is_active"] else 1, bot_id)
                )

    def edit_reseller_bot(self, bot_id: int, owner_telegram_id: int = None, owner_name: str = None,
                           bot_token: str = None, bot_username: str = None):
        fields, values = [], []
        if owner_telegram_id is not None:
            fields.append("owner_telegram_id=?"); values.append(owner_telegram_id)
        if owner_name is not None:
            fields.append("owner_name=?"); values.append(owner_name)
        if bot_token is not None:
            fields.append("bot_token=?"); values.append(bot_token)
        if bot_username is not None:
            fields.append("bot_username=?"); values.append(bot_username)
        if not fields:
            return
        values.append(bot_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE reseller_bots SET {', '.join(fields)} WHERE id=?", values)

    def delete_reseller_bot(self, bot_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM reseller_bots WHERE id=?", (bot_id,))

    # ---------------------------------------------------- web panel (reseller) --

    def enable_reseller_web_panel(self, bot_id: int) -> str:
        """پنل وب این نماینده را فعال و یک توکن یک‌بارمصرف راه‌اندازی می‌سازد
        (برای اولین بار که نماینده یوزر/پس خودش را تنظیم می‌کند). توکن را برمی‌گرداند."""
        import secrets as _secrets
        token = _secrets.token_urlsafe(24)
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE reseller_bots SET web_panel_enabled=1, web_panel_setup_token=?, "
                "web_panel_setup_token_created_at=? WHERE id=?",
                (token, datetime.utcnow().isoformat(), bot_id),
            )
        return token

    def disable_reseller_web_panel(self, bot_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE reseller_bots SET web_panel_enabled=0, web_panel_setup_token=NULL, "
                "web_panel_setup_token_created_at=NULL WHERE id=?", (bot_id,)
            )

    def regenerate_reseller_web_panel_token(self, bot_id: int) -> str:
        """لینک راه‌اندازی جدید (مثلاً چون قبلی لو رفته یا نماینده گم کرده)."""
        import secrets as _secrets
        token = _secrets.token_urlsafe(24)
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE reseller_bots SET web_panel_setup_token=?, web_panel_setup_token_created_at=? WHERE id=?",
                (token, datetime.utcnow().isoformat(), bot_id),
            )
        return token

    def consume_reseller_web_panel_setup_token(self, bot_id: int):
        """بعد از اینکه نماینده اولین یوزر/پس را ست کرد، توکن راه‌اندازی باطل می‌شود."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE reseller_bots SET web_panel_setup_token=NULL, web_panel_setup_token_created_at=NULL "
                "WHERE id=?", (bot_id,)
            )

    # -------------------------------------------------------------------
    # پاکسازی داده‌های باقی‌مانده از نمایندگی‌های حذف‌شده
    # وقتی یک بات نمایندگی حذف می‌شود، پرچم/اعتبار/پنل نمایندگی روی رکورد
    # کاربر در دیتابیس اصلی ممکن است پاک نشده باقی بماند و باعث شود دکمه‌ی
    # «درخواست نمایندگی» برای او دیگر کار نکند (چون هنوز نماینده تلقی می‌شود).
    # -------------------------------------------------------------------

    def list_orphaned_reseller_users(self):
        """کاربرانی که پرچم/اعتبار/پنل نمایندگی روی رکوردشان مانده ولی هیچ
        بات نمایندگی‌ای (حتی غیرفعال) برایشان در reseller_bots ثبت نیست."""
        with self._get_conn() as conn:
            return conn.execute(
                """
                SELECT telegram_id, first_name, username, is_reseller,
                       reseller_credit_gb, reseller_panel_id
                FROM users
                WHERE (is_reseller = 1 OR reseller_credit_gb > 0 OR reseller_panel_id IS NOT NULL)
                  AND telegram_id NOT IN (SELECT owner_telegram_id FROM reseller_bots)
                ORDER BY telegram_id
                """
            ).fetchall()

    def purge_reseller_leftovers(self, user_tg_id: int):
        """پرچم نماینده‌بودن، اعتبار حجمی و پنل اختصاصی کاربر را در دیتابیس
        اصلی صفر/خالی می‌کند؛ برای پاکسازی کامل رد پای یک نمایندگی حذف‌شده."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET is_reseller=0, reseller_credit_gb=0, reseller_panel_id=NULL "
                "WHERE telegram_id=?",
                (user_tg_id,),
            )

    def queue_db_purge(self, bot_token: str, db_path: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO pending_db_purges (bot_token, db_path) VALUES (?, ?)",
                (bot_token, db_path),
            )

    def list_pending_db_purges(self):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM pending_db_purges").fetchall()

    def remove_pending_db_purge(self, purge_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM pending_db_purges WHERE id=?", (purge_id,))

    # -----------------------------------------------------------------------
    # فاکتورهای پرداخت کریپتو (Plisio)
    # -----------------------------------------------------------------------

    def create_crypto_invoice(self, txn_id: str, kind: str, ref_id: int, user_id: int,
                               amount_toman: int, source_amount_usd: float,
                               invoice_url: str = None, currency: str = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO crypto_invoices (txn_id, kind, ref_id, user_id, amount_toman, "
                "source_amount_usd, invoice_url, currency, status, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
                (txn_id, kind, ref_id, user_id, amount_toman, source_amount_usd, invoice_url, currency,
                 (datetime.utcnow() + timedelta(minutes=80)).isoformat()),
            )
            return cur.lastrowid

    def get_crypto_invoice_by_txn(self, txn_id: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM crypto_invoices WHERE txn_id=?", (txn_id,)).fetchone()

    def get_crypto_invoice(self, invoice_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM crypto_invoices WHERE id=?", (invoice_id,)).fetchone()

    def update_crypto_invoice_status(self, txn_id: str, status: str, currency: str = None):
        with self._get_conn() as conn:
            if currency is not None:
                conn.execute(
                    "UPDATE crypto_invoices SET status=?, currency=?, updated_at=? WHERE txn_id=?",
                    (status, currency, datetime.utcnow().isoformat(), txn_id),
                )
            else:
                conn.execute(
                    "UPDATE crypto_invoices SET status=?, updated_at=? WHERE txn_id=?",
                    (status, datetime.utcnow().isoformat(), txn_id),
                )

    def get_pending_crypto_invoice_for_ref(self, kind: str, ref_id: int):
        """آخرین فاکتور فعال (new/pending) ثبت‌شده برای یک سفارش یا شارژ کیف پول خاص را برمی‌گرداند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM crypto_invoices WHERE kind=? AND ref_id=? AND status IN ('new','pending') "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()

    def get_crypto_invoices(self, limit: int = 50):
        """فهرست پرداخت‌های کریپتو برای پنل مدیریت؛ شامل پرداخت‌های فعال و تاریخچه."""
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM crypto_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    # -----------------------------------------------------------------------
    # لاگ وبهوک درگاه‌های پرداخت (برای دیباگ مشکلاتی مثل رد شدن امضا)
    # -----------------------------------------------------------------------

    def log_webhook_event(self, gateway: str, txn_id: str = None, verified: bool = False,
                           status: str = None, error: str = None, raw_body: str = None):
        raw_body = (raw_body or "")[:4000]  # جلوگیری از رشد بی‌رویه‌ی دیتابیس
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO payment_webhook_logs (gateway, txn_id, verified, status, error, raw_body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gateway, txn_id, 1 if verified else 0, status, error, raw_body),
            )

    def get_recent_webhook_logs(self, limit: int = 50, gateway: str = None):
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            if gateway:
                return conn.execute(
                    "SELECT * FROM payment_webhook_logs WHERE gateway=? ORDER BY id DESC LIMIT ?",
                    (gateway, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM payment_webhook_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    def get_gateway_revenue_report(self):
        """جمع تومانی تراکنش‌های کامل‌شده به تفکیک درگاه (بر پایه‌ی جداول invoice هر درگاه).
        توجه: کارت‌به‌کارت دستی جدول invoice مجزا ندارد (تایید دستی روی سفارش انجام می‌شود)
        و در این گزارش لحاظ نشده."""
        with self._get_conn() as conn:
            crypto = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(amount_toman),0) s FROM crypto_invoices WHERE status='completed'"
            ).fetchone()
            aban = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(amount_toman),0) s FROM abangateway_invoices WHERE status IN ('paid','completed')"
            ).fetchone()
            custom_rows = conn.execute(
                "SELECT cg.name AS name, COUNT(*) c, COALESCE(SUM(cgi.amount_toman),0) s "
                "FROM custom_gateway_invoices cgi JOIN custom_gateways cg ON cg.id = cgi.gateway_id "
                "WHERE cgi.status='completed' GROUP BY cgi.gateway_id"
            ).fetchall()
        result = [
            {"gateway": "crypto", "label": "کریپتو (Plisio)", "count": crypto["c"], "amount_toman": crypto["s"]},
            {"gateway": "abangateway", "label": "آبان گیت‌وی", "count": aban["c"], "amount_toman": aban["s"]},
        ]
        for row in custom_rows:
            result.append({
                "gateway": f"custom:{row['name']}", "label": row["name"] or "درگاه سفارشی",
                "count": row["c"], "amount_toman": row["s"],
            })
        return result

    def expire_stale_crypto_invoices(self):
        """فاکتورهایی که هنوز 'new'/'pending' مانده‌اند ولی زمان اعتبارشان (expires_at)
        گذشته را 'expired' علامت می‌زند. این‌ها هیچ‌وقت خودشان به‌روزرسانی نمی‌شدند
        چون کاربر پرداخت نکرده و وبهوکی برایشان نمی‌آید."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE crypto_invoices SET status='expired', updated_at=? "
                "WHERE status IN ('new','pending') AND expires_at IS NOT NULL AND expires_at < ?",
                (now, now),
            )

    def cancel_and_delete_crypto_invoice(self, invoice_id: int):
        """لغو دستی توسط ادمین: فاکتور بلافاصله از دیتابیس حذف می‌شود (منتظر ۷ روز نمی‌ماند)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM crypto_invoices WHERE id=?", (invoice_id,))

    def purge_old_crypto_invoices(self, days: int = 7):
        """فاکتورهای کریپتوی نهایی‌شده (تکمیل/منقضی/لغو/خطا/مغایرت) که بیش از N روز از
        آخرین به‌روزرسانی‌شان گذشته را برای همیشه حذف می‌کند، تا لیست پنل مدیریت شلوغ نماند."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM crypto_invoices WHERE status IN "
                "('completed','expired','cancelled','error','mismatch') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # فاکتورهای پرداخت کارت‌به‌کارت خودکار (آبان گیت وی)
    # -----------------------------------------------------------------------

    def create_abangateway_invoice(self, invoice_id: str, kind: str, ref_id: int, user_id: int,
                                    amount_toman: int, amount_rial: int, payable_rial: int = None,
                                    payment_url: str = None, expiry_minutes: int = 60) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO abangateway_invoices (invoice_id, kind, ref_id, user_id, amount_toman, "
                "amount_rial, payable_rial, payment_url, status, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
                (invoice_id, kind, ref_id, user_id, amount_toman, amount_rial, payable_rial, payment_url,
                 (datetime.utcnow() + timedelta(minutes=expiry_minutes)).isoformat()),
            )
            return cur.lastrowid

    def get_abangateway_invoice_by_invoice_id(self, invoice_id: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM abangateway_invoices WHERE invoice_id=?", (invoice_id,)
            ).fetchone()

    def get_abangateway_invoice(self, id_: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM abangateway_invoices WHERE id=?", (id_,)).fetchone()

    def update_abangateway_invoice_status(self, invoice_id: str, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE abangateway_invoices SET status=?, updated_at=? WHERE invoice_id=?",
                (status, datetime.utcnow().isoformat(), invoice_id),
            )

    def get_pending_abangateway_invoice_for_ref(self, kind: str, ref_id: int):
        """آخرین فاکتور فعال (new/pending) ثبت‌شده برای یک سفارش یا شارژ کیف پول خاص را برمی‌گرداند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM abangateway_invoices WHERE kind=? AND ref_id=? AND status IN ('new','pending') "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()

    def get_abangateway_invoices(self, limit: int = 50):
        """فهرست پرداخت‌های آبان گیت وی برای پنل مدیریت؛ شامل پرداخت‌های فعال و تاریخچه."""
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM abangateway_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    def expire_stale_abangateway_invoices(self):
        """فاکتورهایی که هنوز 'new'/'pending' مانده‌اند ولی زمان اعتبارشان گذشته را 'expired' علامت می‌زند."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE abangateway_invoices SET status='expired', updated_at=? "
                "WHERE status IN ('new','pending') AND expires_at IS NOT NULL AND expires_at < ?",
                (now, now),
            )

    def cancel_and_delete_abangateway_invoice(self, id_: int):
        """لغو دستی توسط ادمین: فاکتور بلافاصله از دیتابیس حذف می‌شود."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM abangateway_invoices WHERE id=?", (id_,))

    def purge_old_abangateway_invoices(self, days: int = 7):
        """فاکتورهای نهایی‌شده‌ی آبان گیت وی که بیش از N روز از آخرین به‌روزرسانی‌شان گذشته را حذف می‌کند."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM abangateway_invoices WHERE status IN "
                "('completed','expired','cancelled','error') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # درگاه‌های پرداخت سفارشی/پویا (بدون کد، تعریف‌شده توسط ادمین)
    # -----------------------------------------------------------------------

    def create_custom_gateway(self, key: str, name: str, config: dict, enabled: bool = False,
                               min_amount: int = 0) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO custom_gateways (gateway_key, name, config_json, enabled, min_amount) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, name, json.dumps(config, ensure_ascii=False), 1 if enabled else 0, min_amount or 0),
            )
            return cur.lastrowid

    def update_custom_gateway(self, gateway_id: int, name: str = None, config: dict = None,
                               enabled: bool = None, min_amount: int = None):
        fields, values = [], []
        if name is not None:
            fields.append("name=?")
            values.append(name)
        if config is not None:
            fields.append("config_json=?")
            values.append(json.dumps(config, ensure_ascii=False))
        if enabled is not None:
            fields.append("enabled=?")
            values.append(1 if enabled else 0)
        if min_amount is not None:
            fields.append("min_amount=?")
            values.append(min_amount)
        if not fields:
            return
        fields.append("updated_at=?")
        values.append(datetime.utcnow().isoformat())
        values.append(gateway_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE custom_gateways SET {', '.join(fields)} WHERE id=?", values)

    def delete_custom_gateway(self, gateway_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM custom_gateways WHERE id=?", (gateway_id,))
            conn.execute("DELETE FROM custom_gateway_invoices WHERE gateway_id=?", (gateway_id,))

    def get_custom_gateway(self, gateway_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM custom_gateways WHERE id=?", (gateway_id,)).fetchone()

    def get_custom_gateway_by_key(self, key: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM custom_gateways WHERE gateway_key=?", (key,)).fetchone()

    def list_custom_gateways(self, only_enabled: bool = False):
        with self._get_conn() as conn:
            if only_enabled:
                return conn.execute(
                    "SELECT * FROM custom_gateways WHERE enabled=1 ORDER BY id"
                ).fetchall()
            return conn.execute("SELECT * FROM custom_gateways ORDER BY id").fetchall()

    # -----------------------------------------------------------------------
    # کاتالوگ روش‌های پرداخت (داخلی + درگاه‌های سفارشی) + حداقل مبلغ هرکدام
    # -----------------------------------------------------------------------
    # این تابع تنها منبع حقیقت برای «لیست همه‌ی روش‌های پرداخت موجود» است؛
    # همه‌جا (بات، پنل ادمین وب، مینی‌اپ) از همین‌جا خوانده می‌شود تا با
    # اضافه‌شدن یک درگاه سفارشی جدید، بدون هیچ تغییر دستی، خودش را در همه‌ی
    # لیست‌های انتخابِ محصول هم نشان دهد.

    def get_payment_methods_catalog(self, only_enabled: bool = False) -> list:
        """لیست کامل روش‌های پرداخت: آیتم‌های داخلی (کیف پول/کارت/آبان‌گیت‌وی/
        کریپتو) + همه‌ی درگاه‌های سفارشی تعریف‌شده. هر آیتم:
        {key, label, enabled, min_amount, is_custom}"""
        items = []
        for m in BUILTIN_PAYMENT_METHODS:
            enabled = True if not m["enable_setting"] else (self.get_setting(m["enable_setting"], "0") == "1")
            if only_enabled and not enabled:
                continue
            items.append({
                "key": m["key"],
                "label": m["label"],
                "enabled": enabled,
                "min_amount": int(self.get_setting(f"min_amount_{m['key']}", "0") or 0),
                "is_custom": False,
            })
        for gw in self.list_custom_gateways(only_enabled=only_enabled):
            items.append({
                "key": f"custom:{gw['gateway_key']}",
                "label": f"💠 {gw['name']}",
                "enabled": bool(gw["enabled"]),
                "min_amount": int(gw["min_amount"] or 0) if "min_amount" in gw.keys() else 0,
                "is_custom": True,
                "gateway_id": gw["id"],
            })
        return items

    def get_payment_method_min_amount(self, method_key: str) -> int:
        """حداقل مبلغ مجاز برای یک روش پرداخت (کلید داخلی یا 'custom:<key>')."""
        if method_key and method_key.startswith("custom:"):
            gw = self.get_custom_gateway_by_key(method_key.split(":", 1)[1])
            if gw and "min_amount" in gw.keys():
                return int(gw["min_amount"] or 0)
            return 0
        return int(self.get_setting(f"min_amount_{method_key}", "0") or 0)

    # -----------------------------------------------------------------------
    # محدودسازی روش پرداخت مجاز به ازای هر محصول
    # -----------------------------------------------------------------------

    def get_product_payment_methods(self, product_id: int):
        """None = همه‌ی روش‌ها برای این محصول مجازند (پیش‌فرض/بدون محدودیت).
        در غیر این صورت لیستی از کلیدهای مجاز (مثلاً ["wallet","card"])."""
        row = self.get_product(product_id)
        if not row:
            return None
        raw = row["payment_methods"] if "payment_methods" in row.keys() else None
        if not raw:
            return None
        try:
            methods = json.loads(raw)
        except Exception:
            return None
        if not methods:
            return None
        return methods

    def set_product_payment_methods(self, product_id: int, methods):
        """methods=None یا [] یعنی «همه‌ی روش‌ها مجاز» (حذف محدودیت)."""
        value = json.dumps(methods, ensure_ascii=False) if methods else None
        with self._get_conn() as conn:
            conn.execute("UPDATE products SET payment_methods=? WHERE id=?", (value, product_id))

    def product_allows_payment_method(self, product_id: int, method_key: str) -> bool:
        allowed = self.get_product_payment_methods(product_id)
        if allowed is None:
            return True
        return method_key in allowed

    def has_any_payable_method(self, amount: int, allowed_methods=None, exclude_wallet: bool = True) -> bool:
        """آیا برای «مبلغ» داده‌شده حداقل یک روش پرداخت فعال هست که هم توسط
        allowed_methods مجاز باشد (None = همه مجاز) و هم amount از حداقل‌مبلغش
        کمتر نباشد؟ کیف پول به‌طور پیش‌فرض از این بررسی کنار گذاشته می‌شود چون
        از قبل و جدا از این کیبورد به‌صورت خودکار در ابتدای خرید اعمال شده است."""
        for item in self.get_payment_methods_catalog(only_enabled=True):
            if exclude_wallet and item["key"] == "wallet":
                continue
            if allowed_methods is not None and item["key"] not in allowed_methods:
                continue
            if item["min_amount"] and amount < item["min_amount"]:
                continue
            return True
        return False

    def create_custom_gateway_invoice(self, gateway_id: int, txn_id: str, kind: str, ref_id: int,
                                       user_id: int, amount_toman: int, invoice_url: str = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO custom_gateway_invoices (gateway_id, txn_id, kind, ref_id, user_id, "
                "amount_toman, invoice_url, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'new')",
                (gateway_id, txn_id, kind, ref_id, user_id, amount_toman, invoice_url),
            )
            return cur.lastrowid

    def get_custom_gateway_invoice_by_txn(self, gateway_id: int, txn_id: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? AND txn_id=?",
                (gateway_id, txn_id),
            ).fetchone()

    def get_custom_gateway_invoice_by_gateway_ref(self, gateway_id: int, gateway_ref: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? AND gateway_ref=?",
                (gateway_id, gateway_ref),
            ).fetchone()

    def set_custom_gateway_invoice_gateway_ref(self, invoice_id: int, gateway_ref: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE custom_gateway_invoices SET gateway_ref=?, updated_at=? WHERE id=?",
                (gateway_ref, datetime.utcnow().isoformat(), invoice_id),
            )

    def get_custom_gateway_invoice(self, invoice_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE id=?", (invoice_id,)
            ).fetchone()

    def get_pending_custom_gateway_invoice_for_ref(self, gateway_id: int, kind: str, ref_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? AND kind=? AND ref_id=? "
                "AND status IN ('new','pending') ORDER BY id DESC LIMIT 1",
                (gateway_id, kind, ref_id),
            ).fetchone()

    def update_custom_gateway_invoice_status(self, invoice_id: int, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE custom_gateway_invoices SET status=?, updated_at=? WHERE id=?",
                (status, datetime.utcnow().isoformat(), invoice_id),
            )

    def list_custom_gateway_invoices(self, gateway_id: int = None, limit: int = 50):
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            if gateway_id:
                return conn.execute(
                    "SELECT * FROM custom_gateway_invoices WHERE gateway_id=? ORDER BY id DESC LIMIT ?",
                    (gateway_id, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM custom_gateway_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    def purge_old_custom_gateway_invoices(self, days: int = 7):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM custom_gateway_invoices WHERE status IN "
                "('completed','expired','cancelled','failed') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # کارت‌به‌کارت با تایید خودکار (پیامک بانک)
    # -----------------------------------------------------------------------

    def create_card_to_card_card(self, card_number: str, holder_name: str = "",
                                  bank_name: str = "", sort_order: int = 0) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO card_to_card_cards (card_number, holder_name, bank_name, sort_order) "
                "VALUES (?, ?, ?, ?)",
                (card_number, holder_name, bank_name, sort_order),
            )
            return cur.lastrowid

    def get_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM card_to_card_cards WHERE id=?", (card_id,)).fetchone()

    def list_card_to_card_cards(self, only_active: bool = False):
        with self._get_conn() as conn:
            if only_active:
                return conn.execute(
                    "SELECT * FROM card_to_card_cards WHERE is_active=1 ORDER BY sort_order, id"
                ).fetchall()
            return conn.execute("SELECT * FROM card_to_card_cards ORDER BY sort_order, id").fetchall()

    def update_card_to_card_card(self, card_id: int, **fields):
        allowed = {"card_number", "holder_name", "bank_name", "sort_order", "is_active"}
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return
        set_clause = ", ".join(f"{k}=?" for k in cols)
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE card_to_card_cards SET {set_clause} WHERE id=?",
                (*cols.values(), card_id),
            )

    def toggle_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_cards SET is_active = 1 - is_active WHERE id=?", (card_id,)
            )

    def delete_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM card_to_card_cards WHERE id=?", (card_id,))

    def pick_next_card_to_card_card(self):
        """کارت فعالِ کمترین‌استفاده‌شده (چرخشی) را برمی‌گرداند تا واریزی‌ها بین
        چند کارت پخش شوند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_cards WHERE is_active=1 "
                "ORDER BY (last_used_at IS NOT NULL), last_used_at, id LIMIT 1"
            ).fetchone()

    def touch_card_to_card_card(self, card_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_cards SET last_used_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), card_id),
            )

    def create_card_to_card_invoice(self, card_id: int, kind: str, ref_id: int, user_id: int,
                                     base_amount_toman: int, amount_toman: int, expires_at: str) -> int:
        """می‌تواند sqlite3.IntegrityError بزند اگر amount_toman با فاکتور در انتظار
        دیگری تداخل داشته باشد؛ فراخوان (card_to_card_payment) باید با مبلغ جدید
        دوباره تلاش کند."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO card_to_card_invoices (card_id, kind, ref_id, user_id, "
                "base_amount_toman, amount_toman, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (card_id, kind, ref_id, user_id, base_amount_toman, amount_toman, expires_at),
            )
            return cur.lastrowid

    def get_card_to_card_invoice(self, invoice_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_invoices WHERE id=?", (invoice_id,)
            ).fetchone()

    def get_pending_card_to_card_invoice_for_ref(self, kind: str, ref_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_invoices WHERE kind=? AND ref_id=? AND status='pending' "
                "ORDER BY id DESC LIMIT 1",
                (kind, ref_id),
            ).fetchone()

    def get_pending_card_to_card_invoice_by_amount(self, amount_toman: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM card_to_card_invoices WHERE amount_toman=? AND status='pending' "
                "ORDER BY created_at ASC LIMIT 1",
                (amount_toman,),
            ).fetchone()

    def complete_card_to_card_invoice(self, invoice_id: int, sender: str = None,
                                       body: str = None, device_id: str = None):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_invoices SET status='completed', matched_sender=?, "
                "matched_body=?, matched_device_id=?, updated_at=? WHERE id=?",
                (sender, (body or "")[:1000], device_id, datetime.utcnow().isoformat(), invoice_id),
            )

    def expire_stale_card_to_card_invoices(self):
        """فاکتورهای در انتظاری که مهلت‌شان گذشته را به 'manual_review' می‌برد تا هم
        مبلغ رزروشده آزاد شود و هم ادمین در لیست سفارش‌های در انتظار آن‌ها را ببیند."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE card_to_card_invoices SET status='manual_review', updated_at=? "
                "WHERE status='pending' AND expires_at < ?",
                (datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )

    def list_card_to_card_invoices(self, status: str = None, limit: int = 50):
        limit = max(1, min(int(limit or 50), 200))
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM card_to_card_invoices WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM card_to_card_invoices ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    def purge_old_card_to_card_invoices(self, days: int = 7):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM card_to_card_invoices WHERE status IN ('completed','manual_review') "
                "AND COALESCE(updated_at, created_at) < ?",
                (cutoff,),
            )

    # -----------------------------------------------------------------------
    # گردونه شانس
    # -----------------------------------------------------------------------

    def get_wheel_settings(self) -> dict:
        return {
            "enabled": self.get_setting("wheel_enabled", "1") == "1",
            "win_percent": int(self.get_setting("wheel_win_percent", "10") or 0),
            "prizes": [int(p) for p in self.get_setting("wheel_prizes", "10,20,30,50").split(",") if p.strip().isdigit()],
            "expiry_hours": int(self.get_setting("wheel_code_expiry_hours", "24") or 24),
            "cooldown_hours": int(self.get_setting("wheel_cooldown_hours", "24") or 24),
        }

    def set_wheel_prizes(self, prizes: list):
        self.set_setting("wheel_prizes", ",".join(str(p) for p in prizes))

    def can_spin_wheel(self, user_tg_id: int):
        """برمی‌گرداند (True, None) اگر مجاز به چرخش باشد، وگرنه (False, ساعات باقی‌مانده)."""
        cooldown_hours = int(self.get_setting("wheel_cooldown_hours", "24") or 24)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT last_wheel_spin_at FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
        if not row or not row["last_wheel_spin_at"]:
            return True, None
        last_spin = datetime.fromisoformat(row["last_wheel_spin_at"])
        elapsed = datetime.utcnow() - last_spin
        remaining = cooldown_hours - (elapsed.total_seconds() / 3600)
        if remaining <= 0:
            return True, None
        return False, remaining

    def record_wheel_spin(self, user_tg_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_wheel_spin_at=? WHERE telegram_id=?",
                (datetime.utcnow().isoformat(), user_tg_id),
            )

    def generate_wheel_prize_code(self, user_tg_id: int, percent: int) -> tuple:
        """یک کد تخفیف یکبارمصرف با تاریخ انقضا برای برنده‌ی گردونه می‌سازد و برمی‌گرداند (code, expires_at)."""
        settings = self.get_wheel_settings()
        expires_at = (datetime.utcnow() + timedelta(hours=settings["expiry_hours"])).isoformat()
        code = f"LUCKY{user_tg_id}{secrets.randbelow(9000) + 1000}"
        self.create_discount_code(
            code, percent=percent, max_uses=1, expires_at=expires_at, source="wheel"
        )
        return code, expires_at

    # -----------------------------------------------------------------------
    # یادآوری اتمام سرویس + کد تخفیف تشویقی تمدید
    # -----------------------------------------------------------------------

    def get_renewal_settings(self) -> dict:
        return {
            "enabled": self.get_setting("renewal_reminder_enabled", "1") == "1",
            "days_before": int(self.get_setting("renewal_reminder_days_before", "5") or 5),
            "discount_percent": int(self.get_setting("renewal_discount_percent", "20") or 20),
            "discount_expiry_hours": int(self.get_setting("renewal_discount_expiry_hours", "24") or 24),
        }

    def get_configs_due_for_renewal_reminder(self):
        """کانفیگ‌های فعال و بدون یادآوری را برمی‌گرداند.

        نکته مهم: زمان انقضای ذخیره‌شده در cf.expires_at عمداً در اینجا
        برای زمان‌بندی یادآوری استفاده نمی‌شود. زمان واقعی انقضا از لینک
        Subscription در renewal_reminders.py خوانده می‌شود.
        """
        settings = self.get_renewal_settings()
        if not settings["enabled"]:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT cf.id as config_id, cf.link, cf.assigned_user_id, cf.expires_at, "
                "p.id as product_id, p.name as product_name "
                "FROM configs cf JOIN products p ON cf.product_id = p.id "
                "WHERE cf.is_used=1 AND cf.renewal_reminder_sent=0 "
                "AND cf.link IS NOT NULL AND TRIM(cf.link) != ''"
            ).fetchall()

    def mark_renewal_reminder_sent(self, config_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE configs SET renewal_reminder_sent=1 WHERE id=?", (config_id,))

    def get_custom_configs_due_for_renewal_reminder(self):
        """معادل get_configs_due_for_renewal_reminder برای کانفیگ‌هایی که مستقیم
        از پنل VPN ساخته شده‌اند (خرید شخصی/نمایندگی/کانفیگ تست پنلی)."""
        settings = self.get_renewal_settings()
        if not settings["enabled"]:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id as config_id, subscription_url as link, user_id as assigned_user_id, "
                "username as product_name "
                "FROM custom_configs "
                "WHERE renewal_reminder_sent=0 AND status='active' AND source != 'test' "
                "AND subscription_url IS NOT NULL AND TRIM(subscription_url) != ''"
            ).fetchall()

    def mark_custom_config_renewal_reminder_sent(self, config_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET renewal_reminder_sent=1 WHERE id=?", (config_id,))

    def generate_renewal_discount_code(self, user_tg_id: int) -> tuple:
        """یک کد تخفیف یکبارمصرف و محدود به زمان برای یادآوری تمدید سرویس کاربر می‌سازد.
        خروجی: (code, expires_at, percent, expiry_hours)"""
        settings = self.get_renewal_settings()
        expires_at = (datetime.utcnow() + timedelta(hours=settings["discount_expiry_hours"])).isoformat()
        code = f"RENEW{user_tg_id}{secrets.randbelow(9000) + 1000}"
        self.create_discount_code(
            code, percent=settings["discount_percent"], max_uses=1, expires_at=expires_at, source="renewal_reminder"
        )
        return code, expires_at, settings["discount_percent"], settings["discount_expiry_hours"]

    # -----------------------------------------------------------------------
    # یادآوری اتمام حجم + کد تخفیف تشویقی تمدید (مستقل از یادآوری تاریخ انقضا)
    # -----------------------------------------------------------------------

    def get_volume_reminder_settings(self) -> dict:
        return {
            "enabled": self.get_setting("volume_reminder_enabled", "1") == "1",
            "mode": self.get_setting("volume_reminder_mode", "percent"),
            "percent": int(self.get_setting("volume_reminder_percent", "80") or 80),
            "gb_left": float(self.get_setting("volume_reminder_gb_left", "2") or 2),
            "discount_percent": int(self.get_setting("volume_discount_percent", "20") or 20),
            "discount_expiry_hours": int(self.get_setting("volume_discount_expiry_hours", "24") or 24),
        }

    def get_configs_due_for_volume_reminder(self):
        """کانفیگ‌های فعال و بدون یادآوری حجم را برمی‌گرداند.

        آستانه‌ی واقعی (درصد/گیگ) از روی مصرف زنده‌ی Subscription در
        renewal_reminders.py بررسی می‌شود؛ اینجا فقط کاندیدها فیلتر می‌شوند.
        """
        settings = self.get_volume_reminder_settings()
        if not settings["enabled"]:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT cf.id as config_id, cf.link, cf.assigned_user_id, "
                "p.id as product_id, p.name as product_name "
                "FROM configs cf JOIN products p ON cf.product_id = p.id "
                "WHERE cf.is_used=1 AND cf.volume_reminder_sent=0 "
                "AND cf.link IS NOT NULL AND TRIM(cf.link) != ''"
            ).fetchall()

    def mark_volume_reminder_sent(self, config_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE configs SET volume_reminder_sent=1 WHERE id=?", (config_id,))

    def get_custom_configs_due_for_volume_reminder(self):
        """معادل get_configs_due_for_volume_reminder برای کانفیگ‌های ساخته‌شده
        مستقیم روی پنل VPN."""
        settings = self.get_volume_reminder_settings()
        if not settings["enabled"]:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id as config_id, subscription_url as link, user_id as assigned_user_id, "
                "username as product_name "
                "FROM custom_configs "
                "WHERE volume_reminder_sent=0 AND status='active' AND source != 'test' "
                "AND subscription_url IS NOT NULL AND TRIM(subscription_url) != ''"
            ).fetchall()

    def mark_custom_config_volume_reminder_sent(self, config_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET volume_reminder_sent=1 WHERE id=?", (config_id,))

    def generate_volume_discount_code(self, user_tg_id: int) -> tuple:
        """یک کد تخفیف یکبارمصرف و محدود به زمان برای یادآوری اتمام حجم کاربر می‌سازد.
        خروجی: (code, expires_at, percent, expiry_hours)"""
        settings = self.get_volume_reminder_settings()
        expires_at = (datetime.utcnow() + timedelta(hours=settings["discount_expiry_hours"])).isoformat()
        code = f"VOLUME{user_tg_id}{secrets.randbelow(9000) + 1000}"
        self.create_discount_code(
            code, percent=settings["discount_percent"], max_uses=1, expires_at=expires_at, source="volume_reminder"
        )
        return code, expires_at, settings["discount_percent"], settings["discount_expiry_hours"]

    # -----------------------------------------------------------------------
    # چت پشتیبانی (مینی‌اپ + بات، یکپارچه)
    # -----------------------------------------------------------------------

    def add_support_message(self, user_id: int, sender: str, message: str) -> int:
        """sender باید 'user' یا 'admin' باشد."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO support_messages (user_id, sender, message, is_read_by_user, is_read_by_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, sender, message, 1 if sender == "user" else 0, 1 if sender == "admin" else 0),
            )
            conn.execute(
                "INSERT INTO support_conversations (user_id, updated_at) VALUES (?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP",
                (user_id,),
            )
            return cur.lastrowid

    def get_support_messages(self, user_id: int, since_id: int = 0, limit: int = 100):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_messages WHERE user_id=? AND id>? ORDER BY id LIMIT ?",
                (user_id, since_id, limit),
            ).fetchall()

    def mark_support_read_by_user(self, user_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE support_messages SET is_read_by_user=1 WHERE user_id=? AND is_read_by_user=0",
                (user_id,),
            )

    def mark_support_read_by_admin(self, user_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE support_messages SET is_read_by_admin=1 WHERE user_id=? AND is_read_by_admin=0",
                (user_id,),
            )

    # -----------------------------------------------------------------------
    # آنلاین‌بودن ادمین‌ها (برای مسیریابی چت زنده به اولین ادمین/مالک آنلاین)
    # -----------------------------------------------------------------------

    PRESENCE_ONLINE_SECONDS = 90

    def touch_admin_presence(self, tg_id: int):
        """باید در هر تعامل ادمین (پیام/کلیک در بات، یا درخواست API مینی‌اپ) صدا زده شود."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO admin_presence (telegram_id, last_seen) VALUES (?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(telegram_id) DO UPDATE SET last_seen=CURRENT_TIMESTAMP",
                (tg_id,),
            )

    def get_online_admin_ids(self, timeout_seconds: int = None) -> list:
        timeout_seconds = timeout_seconds or self.PRESENCE_ONLINE_SECONDS
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT telegram_id FROM admin_presence WHERE last_seen >= datetime('now', ?)",
                (f"-{timeout_seconds} seconds",),
            ).fetchall()
            return [r["telegram_id"] for r in rows]

    def is_admin_online(self, tg_id: int, timeout_seconds: int = None) -> bool:
        return tg_id in self.get_online_admin_ids(timeout_seconds)

    # -----------------------------------------------------------------------
    # پیام‌های موقت (خودحذف‌شونده بعد از مدت مشخص)
    # -----------------------------------------------------------------------

    def schedule_temp_message(self, chat_id: int, message_id: int, delete_at: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO temp_messages (chat_id, message_id, delete_at) VALUES (?, ?, ?)",
                (chat_id, message_id, delete_at),
            )

    def pop_due_temp_messages(self) -> list:
        """پیام‌های سررسیدشده را برمی‌گرداند و همزمان از جدول حذف می‌کند."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, chat_id, message_id FROM temp_messages WHERE delete_at <= ?", (now,)
            ).fetchall()
            if rows:
                conn.executemany(
                    "DELETE FROM temp_messages WHERE id=?", [(r["id"],) for r in rows]
                )
            return [{"chat_id": r["chat_id"], "message_id": r["message_id"]} for r in rows]

    # -----------------------------------------------------------------------
    # مسیریابی مکالمه‌ی چت زنده (به اولین ادمین/مالک آنلاین)
    # -----------------------------------------------------------------------

    def get_support_conversation(self, user_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_conversations WHERE user_id=?", (user_id,)
            ).fetchone()

    def set_support_conversation_admin(self, user_id: int, admin_id):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO support_conversations (user_id, assigned_admin_id, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET assigned_admin_id=excluded.assigned_admin_id, "
                "updated_at=CURRENT_TIMESTAMP",
                (user_id, admin_id),
            )

    def resolve_support_admin_for_message(self, user_id: int):
        """موقع رسیدن پیام جدید کاربر صدا زده می‌شود. اگر مکالمه قبلاً به ادمینی
        اختصاص یافته و آن ادمین همچنان آنلاین است، همان برگردانده می‌شود (یعنی پیام
        فقط برای همان یک نفر ارسال شود). در غیر این صورت اولین ادمین/مالک آنلاین
        انتخاب و مکالمه به او اختصاص داده می‌شود. اگر هیچ‌کس آنلاین نباشد None
        برمی‌گردد (یعنی طبق روال قدیم به همه‌ی ادمین‌ها اطلاع داده شود)."""
        conv = self.get_support_conversation(user_id)
        online_ids = set(self.get_online_admin_ids())
        current = conv["assigned_admin_id"] if conv else None
        if current and current in online_ids:
            return current
        if not online_ids:
            return None
        role_order = {"owner": 0, "admin": 1, "mid": 2, "support": 3}
        admins = self.list_admins_with_roles()
        candidates = [a for a in admins if a["telegram_id"] in online_ids]
        candidates.sort(key=lambda a: (role_order.get(a["role"], 9), a["telegram_id"]))
        chosen = candidates[0]["telegram_id"] if candidates else None
        if chosen:
            self.set_support_conversation_admin(user_id, chosen)
        return chosen

    def list_support_conversations(self):
        """لیست مکالمات چت زنده برای تب «پشتیبانی زنده» در پنل ادمین، جدیدترین اول."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, MAX(id) AS last_id, MAX(created_at) AS last_at, "
                "SUM(CASE WHEN sender='user' AND is_read_by_admin=0 THEN 1 ELSE 0 END) AS unread "
                "FROM support_messages GROUP BY user_id ORDER BY last_at DESC"
            ).fetchall()
            result = []
            for r in rows:
                last_msg = conn.execute(
                    "SELECT sender, message FROM support_messages WHERE user_id=? ORDER BY id DESC LIMIT 1",
                    (r["user_id"],),
                ).fetchone()
                conv = conn.execute(
                    "SELECT assigned_admin_id FROM support_conversations WHERE user_id=?", (r["user_id"],)
                ).fetchone()
                result.append({
                    "user_id": r["user_id"],
                    "last_at": r["last_at"],
                    "unread": r["unread"] or 0,
                    "last_message": last_msg["message"] if last_msg else "",
                    "last_sender": last_msg["sender"] if last_msg else "",
                    "assigned_admin_id": conv["assigned_admin_id"] if conv else None,
                })
            return result

    def count_unread_support_conversations(self) -> int:
        """تعداد مکالمات چت زنده‌ای که حداقل یک پیام خوانده‌نشده از کاربر دارند
        (برای بج زنده‌ی منو کنار «چت زنده»)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM support_messages "
                "WHERE sender='user' AND is_read_by_admin=0"
            ).fetchone()
            return row["c"] or 0

    def get_latest_user_support_message_id(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(id) AS m FROM support_messages WHERE sender='user'"
            ).fetchone()
            return row["m"] or 0

    def get_new_support_messages_since(self, since_id: int):
        """پیام‌های جدید کاربر (نه ادمین) بعد از since_id، برای حلقه‌ی پوش زنده‌ی پنل وب."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_messages WHERE sender='user' AND id>? ORDER BY id",
                (since_id,),
            ).fetchall()

    # -----------------------------------------------------------------------
    # سیستم تیکت (مستقل از چت مستقیم بالا - یک راه ارتباطی جداگانه و رسمی‌تر
    # با موضوع مشخص و وضعیت باز/پاسخ‌داده‌شده/بسته)
    # -----------------------------------------------------------------------

    def create_ticket(self, user_id: int, subject: str, first_message: str) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO tickets (user_id, subject, status) VALUES (?, ?, 'open')",
                (user_id, subject),
            )
            ticket_id = cur.lastrowid
            conn.execute(
                "INSERT INTO ticket_messages (ticket_id, sender, message, is_read_by_user, is_read_by_admin) "
                "VALUES (?, 'user', ?, 1, 0)",
                (ticket_id, first_message),
            )
            return ticket_id

    def get_user_tickets(self, user_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM tickets WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()

    def get_all_tickets(self, status: str = None):
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM tickets WHERE status=? ORDER BY updated_at DESC", (status,)
                ).fetchall()
            return conn.execute("SELECT * FROM tickets ORDER BY updated_at DESC").fetchall()

    def get_ticket(self, ticket_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()

    def claim_ticket_if_open(self, ticket_id: int, admin_id: int):
        """اولین ادمین یا مالکی که به تیکت پاسخ می‌دهد، مالک آن پاسخ‌گویی می‌شود؛
        تا وقتی claimed_by خالی است این تابع آن را قفل می‌کند و از این پس فقط
        همان ادمین (و همیشه مالک اصلی بات) اجازه‌ی پاسخ‌دادن به این تیکت را دارند."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tickets SET claimed_by=? WHERE id=? AND claimed_by IS NULL",
                (admin_id, ticket_id),
            )

    def add_ticket_message(self, ticket_id: int, sender: str, message: str) -> int:
        """sender باید 'user' یا 'admin' باشد. وضعیت تیکت را هم خودکار به‌روز می‌کند:
        پاسخ ادمین -> answered ، پیام جدید کاربر روی تیکت بسته/پاسخ‌داده‌شده -> open."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO ticket_messages (ticket_id, sender, message, is_read_by_user, is_read_by_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                (ticket_id, sender, message, 1 if sender == "user" else 0, 1 if sender == "admin" else 0),
            )
            new_status = "answered" if sender == "admin" else "open"
            conn.execute(
                "UPDATE tickets SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_status, ticket_id),
            )
            return cur.lastrowid

    def get_ticket_messages(self, ticket_id: int, since_id: int = 0, limit: int = 200):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM ticket_messages WHERE ticket_id=? AND id>? ORDER BY id LIMIT ?",
                (ticket_id, since_id, limit),
            ).fetchall()

    def close_ticket(self, ticket_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tickets SET status='closed', updated_at=CURRENT_TIMESTAMP WHERE id=?", (ticket_id,)
            )

    def mark_ticket_read_by_user(self, ticket_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ticket_messages SET is_read_by_user=1 WHERE ticket_id=? AND is_read_by_user=0",
                (ticket_id,),
            )

    def mark_ticket_read_by_admin(self, ticket_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ticket_messages SET is_read_by_admin=1 WHERE ticket_id=? AND is_read_by_admin=0",
                (ticket_id,),
            )

    def count_open_tickets(self) -> int:
        """تعداد تیکت‌هایی که منتظر پاسخ ادمین هستند (برای بج کنار دکمه‌ی پنل مدیریت)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM tickets WHERE status='open'"
            ).fetchone()
            return row["c"] or 0

    def get_expiring_configs_for_user(self, user_tg_id: int, days_before: int = None):
        """کانفیگ‌های فعال کاربر (خریداری‌شده از انبار + ساخته‌شده مستقیم روی پنل) که تا چند روز آینده منقضی می‌شوند."""
        if days_before is None:
            days_before = int(self.get_setting("renewal_reminder_days_before", "5") or 5)
        with self._get_conn() as conn:
            threshold = (datetime.utcnow() + timedelta(days=days_before)).isoformat()
            now = datetime.utcnow().isoformat()
            rows = conn.execute(
                "SELECT cf.id as config_id, cf.link, cf.expires_at, o.product_id "
                "FROM configs cf JOIN orders o ON (o.id = cf.order_id OR o.config_id = cf.id) "
                "WHERE cf.assigned_user_id=? AND cf.is_used=1 AND cf.expires_at IS NOT NULL "
                "AND cf.expires_at > ? AND cf.expires_at <= ? AND o.user_id=?",
                (user_tg_id, now, threshold, user_tg_id),
            ).fetchall()
            custom_rows = conn.execute(
                "SELECT id as config_id, subscription_url as link, expires_at, NULL as product_id, "
                "username as custom_username "
                "FROM custom_configs "
                "WHERE user_id=? AND status='active' AND source != 'test' AND expires_at IS NOT NULL "
                "AND expires_at > ? AND expires_at <= ?",
                (user_tg_id, now, threshold),
            ).fetchall()
            return list(rows) + list(custom_rows)

    # -----------------------------------------------------------------------
    # عضویت اجباری در کانال
    # -----------------------------------------------------------------------

    def get_force_join_settings(self) -> dict:
        return {
            "enabled": self.get_setting("force_join_enabled", "0") == "1",
            "channel": self.get_setting("force_join_channel", "").strip(),
        }

    def is_force_join_exempt(self, tg_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT force_join_exempt FROM users WHERE telegram_id=?", (tg_id,)
            ).fetchone()
            return bool(row and row["force_join_exempt"])

    def set_force_join_exempt(self, tg_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET force_join_exempt=1 WHERE telegram_id=?", (tg_id,)
            )

    def set_acquisition_source(self, tg_id: int, source: str):
        """اولین منبع ورودی کاربر را ثبت می‌کند (برای آمار کمپین‌های تبلیغاتی)؛
        اگر قبلاً ثبت شده باشد دوباره بازنویسی نمی‌شود."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET acquisition_source=? "
                "WHERE telegram_id=? AND (acquisition_source IS NULL OR acquisition_source='')",
                (source, tg_id),
            )

    # -----------------------------------------------------------------------
    # پنل‌های VPN (panel_servers) - برای ساخت کانفیگ شخصی
    # -----------------------------------------------------------------------

    def add_panel_server(self, name: str, panel_type: str, api_url: str,
                          api_username: str, api_password: str, default_group: str = None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO panel_servers (name, panel_type, api_url, api_username, api_password, default_group) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, panel_type, api_url.rstrip("/"), api_username, api_password, default_group),
            )
            return cur.lastrowid

    def update_panel_server(self, server_id: int, **fields):
        allowed = {"name", "panel_type", "api_url", "api_username", "api_password",
                   "default_group", "is_active", "template_username", "group_ids", "proxy_settings",
                   "used_for_custom_config", "used_for_test_config", "used_for_reseller",
                   "xui_inbound_id", "xui_inbound_ids", "xui_sub_base_url"}
        sets, values = [], []
        for k, v in fields.items():
            if k in allowed and v is not None:
                sets.append(f"{k}=?")
                values.append(v.rstrip("/") if k == "api_url" else v)
        if not sets:
            return
        values.append(server_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE panel_servers SET {', '.join(sets)} WHERE id=?", values)

    def count_custom_configs_by_panel(self, server_id: int) -> int:
        """چند کانفیگ شخصی (custom_configs) به این پنل وصل هستند. چون panel_server_id
        در custom_configs یک FOREIGN KEY (بدون CASCADE) است، حذف مستقیم پنل در صورت
        وجود چنین رکوردهایی با IntegrityError شکست می‌خورد."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM custom_configs WHERE panel_server_id=?", (server_id,)
            ).fetchone()
            return row["c"] if row else 0

    def delete_panel_server(self, server_id: int, force: bool = False) -> int:
        """پنل را حذف می‌کند. اگر کانفیگ شخصی مرتبط وجود داشته باشد و force=False
        باشد، به‌جای شکست خوردن با IntegrityError، ValueError با پیام قابل‌فهم می‌دهد.
        با force=True، رکوردهای custom_configs مرتبط هم حذف می‌شوند (غیرقابل بازگشت)
        و تعداد رکوردهای حذف‌شده برگردانده می‌شود."""
        dependent = self.count_custom_configs_by_panel(server_id)
        if dependent and not force:
            raise ValueError(
                f"این پنل {dependent} کانفیگ شخصی ثبت‌شده دارد و به همین دلیل قابل حذف نیست."
            )
        with self._get_conn() as conn:
            if dependent:
                conn.execute("DELETE FROM custom_configs WHERE panel_server_id=?", (server_id,))
            conn.execute("DELETE FROM panel_servers WHERE id=?", (server_id,))
        return dependent

    def get_panel_server(self, server_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM panel_servers WHERE id=?", (server_id,)).fetchone()

    def get_panel_servers(self, active_only: bool = False):
        with self._get_conn() as conn:
            q = "SELECT * FROM panel_servers"
            if active_only:
                q += " WHERE is_active=1"
            q += " ORDER BY id"
            return conn.execute(q).fetchall()

    def get_panel_server_for_usage(self, usage: str):
        """usage: 'custom_config' یا 'test_config' یا 'reseller'. اولین سرور فعالی
        که برای این مصرف علامت خورده را برمی‌گرداند (چند سرور می‌توانند به یک
        پنل با یوزر/پس متفاوت اشاره کنند، هرکدام برای یک مصرف)."""
        column = {
            "custom_config": "used_for_custom_config",
            "test_config": "used_for_test_config",
            "reseller": "used_for_reseller",
        }.get(usage, "used_for_custom_config")
        with self._get_conn() as conn:
            return conn.execute(
                f"SELECT * FROM panel_servers WHERE is_active=1 AND {column}=1 ORDER BY id LIMIT 1"
            ).fetchone()

    # -----------------------------------------------------------------------
    # قیمت‌گذاری پلکانی ساخت کانفیگ شخصی
    # -----------------------------------------------------------------------

    def get_pricing_tiers(self):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_config_pricing_tiers ORDER BY sort_order, from_gb"
            ).fetchall()

    def add_pricing_tier(self, from_gb: int, to_gb, price_per_gb: int) -> int:
        with self._get_conn() as conn:
            max_sort = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) AS m FROM custom_config_pricing_tiers"
            ).fetchone()["m"]
            cur = conn.execute(
                "INSERT INTO custom_config_pricing_tiers (from_gb, to_gb, price_per_gb, sort_order) VALUES (?, ?, ?, ?)",
                (from_gb, to_gb, price_per_gb, max_sort + 1),
            )
            return cur.lastrowid

    def update_pricing_tier(self, tier_id: int, from_gb: int = None, to_gb=None, price_per_gb: int = None):
        sets, values = [], []
        if from_gb is not None:
            sets.append("from_gb=?"); values.append(from_gb)
        if to_gb is not None or to_gb is None:  # اجازه‌ی ست‌کردن NULL برای «بی‌نهایت» را هم می‌دهیم
            sets.append("to_gb=?"); values.append(to_gb)
        if price_per_gb is not None:
            sets.append("price_per_gb=?"); values.append(price_per_gb)
        if not sets:
            return
        values.append(tier_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE custom_config_pricing_tiers SET {', '.join(sets)} WHERE id=?", values)

    def delete_pricing_tier(self, tier_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM custom_config_pricing_tiers WHERE id=?", (tier_id,))

    def calc_custom_config_price(self, volume_gb: int) -> int:
        """قیمت بر اساس نرخ همان بازه‌ای که حجم درخواستی داخلش قرار می‌گیرد
        محاسبه می‌شود (نه تصاعدی-پلکانی)؛ یعنی کل حجم با یک نرخ ثابت (نرخ آن
        بازه) ضرب می‌شود. اگر حجم از آخرین بازه هم بیشتر باشد، با نرخ آخرین
        بازه حساب می‌شود؛ اگر کمتر از اولین بازه باشد، با نرخ اولین بازه."""
        tiers = self.get_pricing_tiers()
        if not tiers:
            return 0
        for tier in tiers:
            frm, to = tier["from_gb"], tier["to_gb"]
            if volume_gb < frm:
                break
            if to is None or volume_gb <= to:
                return int(volume_gb * tier["price_per_gb"])
        # حجم از آخرین بازه هم بیشتر بوده یا کمتر از اولین بازه:
        if volume_gb < tiers[0]["from_gb"]:
            return int(volume_gb * tiers[0]["price_per_gb"])
        return int(volume_gb * tiers[-1]["price_per_gb"])

    # -----------------------------------------------------------------------
    # کانفیگ‌های شخصی ساخته‌شده توسط کاربر
    # -----------------------------------------------------------------------

    def add_custom_config(self, user_id: int, panel_server_id: int, username: str,
                           volume_gb: int, duration_days: int, subscription_url: str,
                           order_id: int = None, expires_at: str = None, source: str = "custom_config",
                           product_id: int = None) -> int:
        """source: 'custom_config' (خرید شخصی)، 'test' (کانفیگ تست پنلی)، یا 'reseller'.
        duration_days=0 یعنی سرویس نامحدود/بدون انقضاست؛ در این حالت expires_at
        خالی (NULL) می‌ماند تا همه‌جا به‌صورت «نامحدود» نمایش داده شود. product_id
        به custom_config_products اشاره می‌کند (NULL برای مسیر سراسری قدیمی)."""
        if expires_at is None and duration_days:
            expires_at = (datetime.utcnow() + timedelta(days=duration_days)).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO custom_configs (order_id, user_id, panel_server_id, username, volume_gb, "
                "duration_days, subscription_url, expires_at, source, product_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, user_id, panel_server_id, username, volume_gb, duration_days, subscription_url,
                 expires_at, source, product_id),
            )
            new_id = cur.lastrowid
        self.add_custom_config_history(new_id, "purchase", f"{volume_gb} گیگ / {duration_days} روز")
        return new_id

    def get_custom_configs_for_user(self, user_id: int, source: str = None):
        with self._get_conn() as conn:
            if source:
                return conn.execute(
                    "SELECT * FROM custom_configs WHERE user_id=? AND source=? ORDER BY id DESC", (user_id, source)
                ).fetchall()
            return conn.execute(
                "SELECT * FROM custom_configs WHERE user_id=? ORDER BY id DESC", (user_id,)
            ).fetchall()

    def update_custom_config_subscription_url(self, custom_config_id: int, subscription_url: str):
        """وقتی لینک اشتراک به‌صورت زنده از پنل دوباره خوانده می‌شود (مثلاً چون
        ادمین تنظیمات پنل را عوض کرده و لینک قدیمی دیگر معتبر نبود)، مقدار
        تازه اینجا در دیتابیس هم به‌روز می‌شود تا دفعه‌ی بعد از همان استفاده شود."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE custom_configs SET subscription_url=? WHERE id=?",
                (subscription_url, custom_config_id),
            )

    def get_test_custom_config_for_user(self, user_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs WHERE user_id=? AND source='test' ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

    def get_custom_config_owned(self, custom_config_id: int, user_tg_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs WHERE id=? AND user_id=?", (custom_config_id, user_tg_id)
            ).fetchone()

    def apply_custom_config_renewal(self, custom_config_id: int, add_volume_gb: int = 0, add_days: int = 0) -> dict:
        """بعد از موفقیت‌آمیز بودن به‌روزرسانی روی خودِ پنل (provider.update_user)،
        رکورد بوکینگ محلی (حجم/مدت/تاریخ انقضا) را هم‌سو با آن به‌روز می‌کند."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM custom_configs WHERE id=?", (custom_config_id,)).fetchone()
            if not row:
                return None
            now = datetime.utcnow()
            current_expires_at = row["expires_at"]
            base = now
            if current_expires_at:
                try:
                    current_dt = datetime.fromisoformat(current_expires_at)
                    if current_dt > now:
                        base = current_dt
                except ValueError:
                    pass
            new_expires_at = (base + timedelta(days=add_days)).isoformat() if add_days else current_expires_at
            new_volume = (row["volume_gb"] or 0) + add_volume_gb if add_volume_gb else row["volume_gb"]
            new_duration = (row["duration_days"] or 0) + add_days if add_days else row["duration_days"]
            conn.execute(
                "UPDATE custom_configs SET volume_gb=?, duration_days=?, expires_at=? WHERE id=?",
                (new_volume, new_duration, new_expires_at, custom_config_id),
            )
        self.add_custom_config_history(
            custom_config_id, "renewal",
            f"+{add_volume_gb} گیگ / +{add_days} روز" if (add_volume_gb or add_days) else "تمدید کامل",
        )
        return {"volume_gb": new_volume, "duration_days": new_duration, "expires_at": new_expires_at}

    def extend_pool_config_expiry(self, config_id: int, user_tg_id: int, add_days: int) -> str:
        """تمدید «زمانی» یک کانفیگ استخری قدیمی (جدول configs) که فقط لینک/تاریخ
        انقضا دارد و اطلاعات پنل/یوزرنیم برایش ذخیره نشده - فقط بوکینگ محلی
        (تاریخ انقضا) عوض می‌شود، بدون تماس با پنل."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM configs WHERE id=? AND assigned_user_id=?", (config_id, user_tg_id)
            ).fetchone()
            if not row:
                return None
            now = datetime.utcnow()
            base = now
            if row["expires_at"]:
                try:
                    current_dt = datetime.fromisoformat(row["expires_at"])
                    if current_dt > now:
                        base = current_dt
                except ValueError:
                    pass
            new_expires_at = (base + timedelta(days=add_days)).isoformat()
            conn.execute("UPDATE configs SET expires_at=? WHERE id=?", (new_expires_at, config_id))
            return new_expires_at

    def is_custom_username_taken(self, username: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM custom_configs WHERE username=? LIMIT 1", (username,)
            ).fetchone()
            return row is not None

    def get_custom_config_settings(self) -> dict:
        return {
            "enabled": self.get_setting("custom_config_enabled", "0") == "1",
            "min_gb": int(self.get_setting("custom_config_min_gb", "5") or 5),
            "max_gb": int(self.get_setting("custom_config_max_gb", "1000") or 1000),
            "duration_days": int(self.get_setting("custom_config_duration_days", "30") or 30),
        }

    def get_custom_config_prefix(self) -> str:
        """پیش‌وند ثابتی که ادمین برای نام کانفیگ‌های مستقیم-پنل تعیین می‌کند
        (مثلاً hunter -> hunter-<ادامه‌ی دلخواه کاربر>). خالی یعنی غیرفعال."""
        return (self.get_setting("custom_config_prefix", "") or "").strip()

    def set_custom_config_prefix(self, prefix: str):
        self.set_setting("custom_config_prefix", (prefix or "").strip())

    # -----------------------------------------------------------------------
    # تاریخچه‌ی سرویس (custom_config_history)
    # -----------------------------------------------------------------------

    def add_custom_config_history(self, custom_config_id: int, event_type: str, detail: str = None):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO custom_config_history (custom_config_id, event_type, detail) VALUES (?, ?, ?)",
                (custom_config_id, event_type, detail),
            )

    def get_custom_config_history(self, custom_config_id: int, limit: int = 30):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_config_history WHERE custom_config_id=? ORDER BY id DESC LIMIT ?",
                (custom_config_id, limit),
            ).fetchall()

    # -----------------------------------------------------------------------
    # فعال/غیرفعال، تمدید خودکار، تغییر نام و انتقال کانفیگ‌های مستقیم-پنل
    # -----------------------------------------------------------------------

    def set_custom_config_enabled(self, custom_config_id: int, user_tg_id: int, enabled: bool) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET enabled=? WHERE id=? AND user_id=?",
                (1 if enabled else 0, custom_config_id, user_tg_id),
            )
            return cur.rowcount > 0

    def set_custom_config_auto_renew(self, custom_config_id: int, user_tg_id: int, auto_renew: bool) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET auto_renew=? WHERE id=? AND user_id=?",
                (1 if auto_renew else 0, custom_config_id, user_tg_id),
            )
            return cur.rowcount > 0

    def rename_custom_config(self, custom_config_id: int, user_tg_id: int, display_name: str,
                              new_panel_username: str = None) -> bool:
        """display_name همیشه (فقط برای نمایش در بات) به‌روز می‌شود؛ ستون واقعی
        username (شناسه‌ی کاربر روی خودِ پنل که همه‌ی عملیات دیگر - تمدید/حذف/
        فعال‌سازی - با آن کار می‌کنند) فقط وقتی عوض می‌شود که rename روی خودِ
        پنل هم موفق بوده (new_panel_username داده شده باشد) تا هیچ‌وقت بین
        دیتابیس و پنل ناهماهنگی پیش نیاید."""
        with self._get_conn() as conn:
            if new_panel_username:
                cur = conn.execute(
                    "UPDATE custom_configs SET username=?, display_name=? WHERE id=? AND user_id=?",
                    (new_panel_username, display_name, custom_config_id, user_tg_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE custom_configs SET display_name=? WHERE id=? AND user_id=?",
                    (display_name, custom_config_id, user_tg_id),
                )
            return cur.rowcount > 0

    def transfer_custom_config(self, custom_config_id: int, from_user_tg_id: int, to_user_tg_id: int) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET user_id=? WHERE id=? AND user_id=?",
                (to_user_tg_id, custom_config_id, from_user_tg_id),
            )
            return cur.rowcount > 0

    def get_custom_configs_due_for_auto_renew(self, hours_before: int = 24):
        """کانفیگ‌های مستقیم-پنل که تمدید خودکار برایشان فعال است و انقضایشان
        در بازه‌ی hours_before ساعت آینده قرار دارد (duration_days=0 یعنی
        نامحدود و اصلاً وارد این لیست نمی‌شود)."""
        threshold = (datetime.utcnow() + timedelta(hours=hours_before)).isoformat()
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs WHERE auto_renew=1 AND enabled=1 AND duration_days>0 "
                "AND expires_at IS NOT NULL AND expires_at<=?",
                (threshold,),
            ).fetchall()

    def mark_custom_config_auto_renew_alert(self, custom_config_id: int, date_str: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE custom_configs SET auto_renew_alert_date=? WHERE id=?", (date_str, custom_config_id),
            )

    # -----------------------------------------------------------------------
    # محصولات «ساخت کانفیگ شخصی» (چندمحصولی)
    # -----------------------------------------------------------------------

    def get_custom_config_products(self, active_only: bool = False):
        q = "SELECT * FROM custom_config_products"
        if active_only:
            q += " WHERE is_active=1"
        q += " ORDER BY sort_order, id"
        with self._get_conn() as conn:
            return conn.execute(q).fetchall()

    def count_active_custom_config_products(self) -> int:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM custom_config_products WHERE is_active=1"
            ).fetchone()["c"]

    def get_custom_config_product(self, product_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_config_products WHERE id=?", (product_id,)
            ).fetchone()

    def create_custom_config_product(self, name: str, panel_server_id: int, min_gb: int = 5,
                                      max_gb: int = 1000, duration_mode: str = "fixed",
                                      duration_days: int = 30, min_days: int = None,
                                      max_days: int = None, pricing_mode: str = "flat",
                                      flat_price_per_gb: int = None, description: str = "",
                                      icon: str = "🛠") -> int:
        with self._get_conn() as conn:
            max_sort = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) AS m FROM custom_config_products"
            ).fetchone()["m"]
            cur = conn.execute(
                "INSERT INTO custom_config_products (name, description, icon, panel_server_id, min_gb, max_gb, "
                "duration_mode, duration_days, min_days, max_days, pricing_mode, flat_price_per_gb, "
                "is_active, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (name, description, icon, panel_server_id, min_gb, max_gb, duration_mode, duration_days,
                 min_days, max_days, pricing_mode, flat_price_per_gb, max_sort + 1),
            )
            return cur.lastrowid

    def update_custom_config_product(self, product_id: int, **fields) -> None:
        """fields می‌تواند شامل هرکدام از ستون‌های custom_config_products باشد،
        مثلاً update_custom_config_product(5, name="پلن آلمان", is_active=0)."""
        allowed = {
            "name", "description", "icon", "panel_server_id", "min_gb", "max_gb",
            "duration_mode", "duration_days", "min_days", "max_days", "pricing_mode",
            "flat_price_per_gb", "payment_methods", "is_active", "sort_order",
        }
        sets, values = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k}=?")
                values.append(v)
        if not sets:
            return
        values.append(product_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE custom_config_products SET {', '.join(sets)} WHERE id=?", values)

    def delete_custom_config_product(self, product_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM custom_config_products WHERE id=?", (product_id,))

    def get_custom_config_product_tiers(self, product_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_config_product_pricing_tiers WHERE product_id=? ORDER BY sort_order, from_gb",
                (product_id,),
            ).fetchall()

    def add_custom_config_product_tier(self, product_id: int, from_gb: int, to_gb, price_per_gb: int) -> int:
        with self._get_conn() as conn:
            max_sort = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) AS m FROM custom_config_product_pricing_tiers WHERE product_id=?",
                (product_id,),
            ).fetchone()["m"]
            cur = conn.execute(
                "INSERT INTO custom_config_product_pricing_tiers (product_id, from_gb, to_gb, price_per_gb, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (product_id, from_gb, to_gb, price_per_gb, max_sort + 1),
            )
            return cur.lastrowid

    def update_custom_config_product_tier(self, tier_id: int, from_gb: int = None, to_gb=None, price_per_gb: int = None):
        sets, values = [], []
        if from_gb is not None:
            sets.append("from_gb=?"); values.append(from_gb)
        if to_gb is not None or to_gb is None:
            sets.append("to_gb=?"); values.append(to_gb)
        if price_per_gb is not None:
            sets.append("price_per_gb=?"); values.append(price_per_gb)
        if not sets:
            return
        values.append(tier_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE custom_config_product_pricing_tiers SET {', '.join(sets)} WHERE id=?", values)

    def delete_custom_config_product_tier(self, tier_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM custom_config_product_pricing_tiers WHERE id=?", (tier_id,))

    def calc_custom_config_product_price(self, product_id: int, volume_gb: int) -> int:
        product = self.get_custom_config_product(product_id)
        if not product:
            return 0
        if product["pricing_mode"] == "flat":
            return int(volume_gb * (product["flat_price_per_gb"] or 0))
        tiers = self.get_custom_config_product_tiers(product_id)
        if not tiers:
            return 0
        for tier in tiers:
            frm, to = tier["from_gb"], tier["to_gb"]
            if volume_gb < frm:
                break
            if to is None or volume_gb <= to:
                return int(volume_gb * tier["price_per_gb"])
        if volume_gb < tiers[0]["from_gb"]:
            return int(volume_gb * tiers[0]["price_per_gb"])
        return int(volume_gb * tiers[-1]["price_per_gb"])

    # -----------------------------------------------------------------------
    # نمایندگی بر پایه‌ی استخر حجم (reseller credit)
    # -----------------------------------------------------------------------

    def is_reseller(self, user_tg_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT is_reseller FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            return bool(row and row["is_reseller"])

    def get_reseller_credit(self, user_tg_id: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT reseller_credit_gb FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            return row["reseller_credit_gb"] if row else 0

    def set_reseller_status(self, user_tg_id: int, enabled: bool):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET is_reseller=? WHERE telegram_id=?", (1 if enabled else 0, user_tg_id)
            )

    def adjust_reseller_credit(self, user_tg_id: int, delta_gb: int, admin_id: int = None, reason: str = None):
        """delta_gb مثبت (شارژ) یا منفی (کسر بابت ساخت کانفیگ) باشد."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET reseller_credit_gb = reseller_credit_gb + ? WHERE telegram_id=?",
                (delta_gb, user_tg_id),
            )
            conn.execute(
                "INSERT INTO reseller_credit_log (user_id, delta_gb, reason, admin_id) VALUES (?, ?, ?, ?)",
                (user_tg_id, delta_gb, reason, admin_id),
            )

    def get_reseller_credit_log(self, user_tg_id: int, limit: int = 20):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM reseller_credit_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_tg_id, limit),
            ).fetchall()

    def get_resellers(self):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE is_reseller=1 ORDER BY reseller_credit_gb DESC"
            ).fetchall()

    def get_reseller_cohort_churn(self, inactivity_days: int = 30, months: int = 6):
        """تحلیل کوهورت (cohort) و ریزش (churn) نمایندگی‌ها بر پایه‌ی لاگ اعتبار حجمی.

        کوهورت هر نماینده = ماه اولین رکورد او در reseller_credit_log (یعنی اولین
        شارژ/فعال‌سازی)؛ اگر نماینده‌ای هیچ لاگی نداشته باشد (مثلاً با ست دستی
        فلگ is_reseller)، ماه عضویتش (joined_at) به‌عنوان جایگزین در نظر گرفته می‌شود.
        «فعال بودن در ماه» یعنی حداقل یک رکورد لاگ (شارژ یا مصرف) در آن ماه.
        «ریزش» یعنی نماینده‌ای که is_reseller=1 است ولی طی inactivity_days روز
        اخیر هیچ رکورد لاگی نداشته (و بیش از همان مدت از عضویتش گذشته باشد).
        """
        with self._get_conn() as conn:
            first_activity = conn.execute(
                """
                SELECT u.telegram_id AS tg_id, u.username AS username, u.reseller_credit_gb AS credit_gb,
                       u.is_reseller AS is_reseller, u.joined_at AS joined_at,
                       COALESCE(MIN(l.created_at), u.joined_at) AS cohort_at,
                       MAX(l.created_at) AS last_activity
                FROM users u
                LEFT JOIN reseller_credit_log l ON l.user_id = u.telegram_id
                WHERE u.is_reseller = 1 OR EXISTS (
                    SELECT 1 FROM reseller_credit_log l2 WHERE l2.user_id = u.telegram_id
                )
                GROUP BY u.telegram_id
                """
            ).fetchall()

            monthly_activity = conn.execute(
                """
                SELECT user_id, strftime('%Y-%m', created_at) AS ym
                FROM reseller_credit_log
                GROUP BY user_id, ym
                """
            ).fetchall()

        active_months_by_user = {}
        for row in monthly_activity:
            active_months_by_user.setdefault(row["user_id"], set()).add(row["ym"])

        def month_key(dt_str):
            return (dt_str or "")[:7]

        def add_months(ym: str, n: int) -> str:
            y, m = int(ym[:4]), int(ym[5:7])
            total = (y * 12 + (m - 1)) + n
            return f"{total // 12:04d}-{total % 12 + 1:02d}"

        now = datetime.now()
        cur_ym = now.strftime("%Y-%m")
        cohort_months = []
        ym = cur_ym
        for _ in range(months):
            cohort_months.append(ym)
            ym = add_months(ym, -1)
        cohort_months.reverse()

        cohorts_map = {m: [] for m in cohort_months}
        for r in first_activity:
            cm = month_key(r["cohort_at"])
            if cm in cohorts_map:
                cohorts_map[cm].append(r["tg_id"])

        cohorts_out = []
        for cm in cohort_months:
            members = cohorts_map[cm]
            size = len(members)
            retention = []
            max_offset = add_months(cur_ym, 0)
            offset = 0
            probe = cm
            while probe <= cur_ym:
                active = sum(1 for uid in members if probe in active_months_by_user.get(uid, ()))
                retention.append({
                    "offset": offset,
                    "month": probe,
                    "active": active,
                    "pct": round(active * 100 / size, 1) if size else 0.0,
                })
                offset += 1
                probe = add_months(probe, 1)
            cohorts_out.append({"cohort_month": cm, "size": size, "retention": retention})

        churn_list = []
        active_count = 0
        cutoff = now.timestamp() - inactivity_days * 86400

        def to_ts(dt_str):
            if not dt_str:
                return None
            try:
                return datetime.fromisoformat(dt_str.replace("Z", "")).timestamp()
            except ValueError:
                return None

        current_resellers = [r for r in first_activity if r["is_reseller"]]
        for r in current_resellers:
            last_ts = to_ts(r["last_activity"])
            joined_ts = to_ts(r["joined_at"]) or 0
            is_new = joined_ts and joined_ts > cutoff
            if last_ts and last_ts >= cutoff:
                active_count += 1
                continue
            if not last_ts and is_new:
                active_count += 1
                continue
            days_inactive = int((now.timestamp() - (last_ts or joined_ts)) / 86400)
            churn_list.append({
                "telegram_id": r["tg_id"],
                "username": r["username"],
                "credit_gb": r["credit_gb"],
                "last_activity": r["last_activity"],
                "days_inactive": days_inactive,
            })

        total_resellers = len(current_resellers)
        churn_list.sort(key=lambda x: -x["days_inactive"])
        return {
            "cohorts": cohorts_out,
            "churn": {
                "total": total_resellers,
                "active": active_count,
                "churned": len(churn_list),
                "churn_rate": round(len(churn_list) * 100 / total_resellers, 1) if total_resellers else 0.0,
                "inactivity_days": inactivity_days,
                "list": churn_list,
            },
        }

    def set_reseller_panel(self, user_tg_id: int, panel_server_id):
        """پنل اختصاصی که ادمین برای این نماینده تعیین کرده (None = پیش‌فرض خودکار)."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET reseller_panel_id=? WHERE telegram_id=?", (panel_server_id, user_tg_id)
            )

    def get_reseller_panel(self, user_tg_id: int):
        """پنلی که این نماینده باید رویش کانفیگ بسازد: اول پنل اختصاصی‌اش، وگرنه
        اولین پنل فعالی که برای «نمایندگی» علامت خورده."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT reseller_panel_id FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            panel_id = row["reseller_panel_id"] if row else None
            if panel_id:
                server = conn.execute(
                    "SELECT * FROM panel_servers WHERE id=? AND is_active=1", (panel_id,)
                ).fetchone()
                if server:
                    return server
        return self.get_panel_server_for_usage("reseller")

    # -----------------------------------------------------------------------
    # درخواست خودکار نمایندگی سطح ۲ (ثبت، تایید هزینه، پرداخت، تحویل)
    # -----------------------------------------------------------------------

    _RESELLER_REQUEST_OPEN_STATUSES = (
        "pending_review", "awaiting_payment", "awaiting_payment_review", "awaiting_bot_info",
    )

    def create_reseller_request(self, user_id: int, volume_gb: int, request_text: str) -> int:
        with self._get_conn() as conn:
            # status را صراحتاً اینجا ست می‌کنیم و به مقدار پیش‌فرض ستون در schema
            # تکیه نمی‌کنیم. روی دیتابیس‌های قدیمی‌تر که ستون status از قبل (قبل از
            # اضافه‌شدن DEFAULT 'pending_review') با ALTER TABLE ساخته شده بود، تکیه
            # به دیفالت باعث می‌شد status درخواست‌های تازه NULL بماند و دکمه‌ی
            # «تایید و تعیین هزینه» همیشه با خطای «این درخواست دیگر معتبر نیست»
            # مواجه شود (چون NULL != 'pending_review'). ست‌کردن صریح این مشکل را
            # مستقل از تاریخچه‌ی دیتابیس برای همیشه حل می‌کند.
            known = {
                "user_id": user_id, "volume_gb": volume_gb, "request_text": request_text,
                "status": "pending_review",
            }
            fields = list(known.keys())
            values = list(known.values())
            # بعضی نصب‌های خیلی قدیمی ممکن است ستون‌های اضافی/الزامی (NOT NULL بدون
            # مقدار پیش‌فرض) در جدول reseller_requests داشته باشند که کد فعلی اصلاً
            # از آن‌ها استفاده نمی‌کند (مثلاً باقی‌مانده از نسخه‌های قدیمی‌تر پروژه).
            # به‌جای اینکه با هر نصب قدیمی دوباره به خطای «NOT NULL constraint
            # failed» بخوریم، این ستون‌های ناشناخته را این‌جا پویا شناسایی کرده
            # و برایشان یک مقدار بی‌ضرر بر اساس نوعشان می‌فرستیم.
            for row in conn.execute("PRAGMA table_info(reseller_requests)").fetchall():
                name = row["name"]
                if name in known or name in ("id", "created_at", "updated_at"):
                    continue
                if row["notnull"] and row["dflt_value"] is None:
                    col_type = (row["type"] or "").upper()
                    if "INT" in col_type:
                        fallback = 0
                    elif any(t in col_type for t in ("REAL", "FLOA", "DOUB")):
                        fallback = 0.0
                    else:
                        fallback = ""
                    fields.append(name)
                    values.append(fallback)
            placeholders = ", ".join("?" for _ in fields)
            cur = conn.execute(
                f"INSERT INTO reseller_requests ({', '.join(fields)}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def get_reseller_request(self, request_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM reseller_requests WHERE id=?", (request_id,)).fetchone()

    def get_open_reseller_request(self, user_id: int):
        placeholders = ",".join("?" * len(self._RESELLER_REQUEST_OPEN_STATUSES))
        with self._get_conn() as conn:
            return conn.execute(
                f"SELECT * FROM reseller_requests WHERE user_id=? AND status IN ({placeholders}) "
                f"ORDER BY id DESC LIMIT 1",
                (user_id, *self._RESELLER_REQUEST_OPEN_STATUSES),
            ).fetchone()

    def list_reseller_requests(self, status: str = None):
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM reseller_requests WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()
            return conn.execute("SELECT * FROM reseller_requests ORDER BY id DESC").fetchall()

    def list_open_reseller_requests(self):
        """درخواست‌های نمایندگی‌ای که هنوز باز هستند (رد/کنسل/تکمیل نشده‌اند)."""
        placeholders = ",".join("?" * len(self._RESELLER_REQUEST_OPEN_STATUSES))
        with self._get_conn() as conn:
            return conn.execute(
                f"SELECT * FROM reseller_requests WHERE status IN ({placeholders}) ORDER BY id DESC",
                self._RESELLER_REQUEST_OPEN_STATUSES,
            ).fetchall()

    def is_reseller_request_open(self, status: str) -> bool:
        return status in self._RESELLER_REQUEST_OPEN_STATUSES

    def admin_cancel_reseller_request(self, request_id: int, admin_id: int):
        """کنسل دستی یک درخواست نمایندگی توسط ادمین، در هر مرحله‌ای که باشد."""
        self.set_reseller_request_status(request_id, "cancelled", reviewed_by=admin_id)

    def set_reseller_request_status(self, request_id: int, status: str, **fields):
        cols, values = ["status=?", "updated_at=CURRENT_TIMESTAMP"], [status]
        for key, value in fields.items():
            cols.append(f"{key}=?")
            values.append(value)
        values.append(request_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE reseller_requests SET {', '.join(cols)} WHERE id=?", values)

    def quote_reseller_request(self, request_id: int, price_toman: int, panel_server_id: int, admin_id: int):
        self.set_reseller_request_status(
            request_id, "awaiting_payment",
            price_toman=price_toman, panel_server_id=panel_server_id, reviewed_by=admin_id,
        )

    def reject_reseller_request(self, request_id: int, status: str, admin_id: int, reason: str = None):
        self.set_reseller_request_status(request_id, status, reviewed_by=admin_id, reject_reason=reason)

    def set_reseller_request_receipt(self, request_id: int, file_id: str, receipt_type: str = "photo"):
        self.set_reseller_request_status(
            request_id, "awaiting_payment_review", receipt_file_id=file_id, receipt_type=receipt_type
        )

    def approve_reseller_request_payment(self, request_id: int, admin_id: int):
        self.set_reseller_request_status(request_id, "awaiting_bot_info", reviewed_by=admin_id)

    def set_reseller_request_bot(self, request_id: int, token: str, username: str):
        self.set_reseller_request_status(
            request_id, "awaiting_bot_info", bot_token=token, bot_username=username,
        )

    def complete_reseller_request(self, request_id: int, owner_telegram_id: int):
        self.set_reseller_request_status(
            request_id, "completed", owner_telegram_id=owner_telegram_id,
        )
