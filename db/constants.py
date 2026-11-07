# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
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
import os
import shutil
import sqlite3
import secrets
import threading
import time
import json
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

import extra_gateway_registry


logger = logging.getLogger(__name__)


class DuplicateBotTokenError(Exception):
    """توکن بات قبلاً برای یک بات نمایندگی دیگر ثبت شده (قید UNIQUE ستون bot_token).

    رفع باگ: register_reseller_bot قبلاً این IntegrityError احتمالی (رقابت دو ثبت‌نام
    هم‌زمان با دقیقاً یک توکن یکسان) را مدیریت نمی‌کرد و به‌صورت خام بالا می‌رفت؛
    الان به یک خطای مشخص تبدیل می‌شود تا صدازننده پیام قابل‌فهم به کاربر نشان دهد."""

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
    "btn_tutorial": "📚 آموزش",
    "tutorial_menu_enabled": "1",
    "test_enabled": "1",
    # F14: پاکسازی خودکار سرویس‌های منقضی. صفر یعنی خاموش.
    "expired_delete_days": "0",
    "test_delete_days": "0",
    "expired_cleanup_warning_days": "3",
    "expired_cleanup_dry_run": "1",
    # F138: ساعت روزانه حذف کانفیگ‌هایی که کاربر/ادمین غیرفعال کرده است؛ خالی یعنی خاموش.
    "inactive_config_delete_time": "",
    "force_join_enabled": "0",
    "service_alert_channel": "",  # کانال اعلان اتمام/حذف کانفیگ
    "force_join_channel": "",  # مثلاً: @mychannel
    "card_number": "0000-0000-0000-0000",
    "card_holder": "نام صاحب حساب",
    # حذف خودکار پیام‌های حاوی شماره کارت بعد از این تعداد ثانیه از ارسال؛
    # صفر یعنی غیرفعال (پیام برای همیشه در چت باقی می‌ماند).
    "card_msg_autodelete_seconds": "0",
    # ظاهر و دکمه‌های پیام کارت‌به‌کارت (card_payment_ui.py)
    "c2c_message_style": "pretty",
    "c2c_copy_buttons": "1",
    "c2c_copy_card": "1",
    "c2c_copy_amount_toman": "1",
    "c2c_copy_amount_rial": "1",
    "c2c_copy_holder": "0",
    "c2c_copy_btn_style": "default",
    "c2c_protect_card": "0",
    "c2c_show_bank": "1",
    "c2c_back_to_wallet": "1",
    # پرداخت دستی کارت‌به‌کارت (ارسال رسید) به‌عنوان یکی از روش‌های پرداخت؛
    # اگر ادمین این روش را غیرفعال کند، در لیست روش‌های پرداخت نمایش داده نمی‌شود.
    "card_to_card_enabled": "1",
    "contact_text": "پیام خود را بنویسید تا مستقیم برای پشتیبانی ارسال شود:",
    # آیدی عددی تلگرام مدیر برای دکمه‌ی «چت مستقیم با مدیر» در بخش ارتباط با
    # پشتیبانی (از طریق لینک tg://user?id=... بدون نیاز به یوزرنیم عمومی باز می‌شود).
    "support_admin_id": "",
    "support_direct_enabled": "1",
    "support_ticket_new_enabled": "1",
    "support_ticket_mine_enabled": "1",
    "support_admin_chat_enabled": "1",
    "ticket_intro_text": "لطفاً موضوع تیکت را در یک خط ارسال کنید:",
    # دستیار پشتیبانی هوش مصنوعی (Gemini) - در صورت خالی بودن GEMINI_API_KEY
    # در .env، این بخش حتی اگر "1" باشد غیرفعال می‌ماند.
    "ai_support_enabled": "1",
    "buy_guide_enabled": "1",
    "business_enabled": "0",
    "business_mark_read": "0",
    "business_notify_changes": "1",
    "ai_support_intro_text": (
        "🤖 دستیار هوشمند پشتیبانی\n"
        "سوالت رو بپرس؛ سعی می‌کنم با بررسی وضعیت واقعی حسابت و پلن‌ها سریع "
        "جوابت رو بدم یا حتی خودم مسیر خرید رو برات باز کنم.\n"
        "اگه نتونستم جوابت رو بدم، متصلت می‌کنم به پشتیبانی انسانی."
    ),
    # دانش پایه‌ای که به دستیار هوشمند داده می‌شود (به‌صورت لیست سوال/جواب،
    # از پنل مدیریت → «ادمین و دسترسی» → «دستیار هوشمند (سوالات متداول)»
    # قابل افزودن/حذف است - جدول ai_faq_items).
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
    "miniapp_theme": "clean-light",
    # سیستم زیرمجموعه‌گیری
    # کلید مستر: مستقل از سه مدل زیر - غیرفعال کردنش کل سیستم رفرال (دکمه/تب و
    # هر سه مدل پاداش) را کاملاً خاموش می‌کند، صرف‌نظر از اینکه کدام مدل روشن باشد.
    "referral_button_enabled": "1",
    # حالت ۱: پورسانت درصدی از اولین خرید هر زیرمجموعه
    "referral_enabled": "1",
    "referral_percent": "10",  # درصدی که به دعوت‌کننده به‌عنوان اعتبار کیف پول تعلق می‌گیرد
    "referral_multilevel_enabled": "0",
    "referral_level2_percent": "3",
    "referral_level3_percent": "1",
    "referral_commission_max_count": "0",  # حداکثر تعداد نفراتی که پورسانت خریدشان تعلق می‌گیرد (0 = نامحدود)
    "referral_min_purchase_amount": "0",  # حداقل مبلغ خرید (تومان) برای تعلق پورسانت اولین خرید؛ 0 = بدون حداقل
    # اگر مبلغ اولین خرید کمتر از حداقل باشد: "0"=منتظر بمان تا خرید بعدی به حداقل برسد (فلگ اولین خرید علامت نمی‌خورد)
    # "1"=همان خرید کم‌مبلغ به‌عنوان اولین خرید مصرف شود و دیگر هیچ‌وقت پورسانتی به آن زیرمجموعه تعلق نگیرد
    "referral_min_purchase_strict": "0",
    # پورسانت زیرمجموعه‌گیری روی تمدید سرویس (قابلیت ۶۷): مستقل از حالت «اولین
    # خرید» بالا - روی هر تمدیدِ سرویسِ زیرمجموعه (تا سقف تعداد مشخص) پورسانت
    # درصدی جداگانه به معرف تعلق می‌گیرد.
    "referral_renewal_percent": "0",  # 0 = غیرفعال
    "referral_renewal_max_count": "0",  # حداکثر تعداد تمدیدهای هر زیرمجموعه که پورسانت می‌دهد (0 = نامحدود)
    # کارمزد نماینده‌ی «لینک اختصاصی داخل بات اصلی» (بند ۳.۱ اسپک): روی هر خرید
    # (نه فقط اولین خرید) مشتریانی که با لینک این نماینده وارد شده‌اند، این درصد
    # به کیف پول خودِ نماینده تعلق می‌گیرد.
    "reseller_inline_commission_enabled": "1",
    "reseller_inline_commission_percent": "10",  # فقط fallback برای نماینده‌های قدیمی بدون درصد اختصاصی
    # حالت ۲: دریافت یک محصول/کانفیگ رایگان با رسیدن تعداد دعوت‌شده‌ها به یک آستانه (نیازی به خرید نیست)
    "referral_free_config_enabled": "0",
    "referral_free_config_threshold": "10",  # تعداد دعوت لازم‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    "referral_free_config_product_id": "",  # آیدی محصولی که رایگان تحویل داده می‌شود
    # حالت ۳: شارژ ثابت کیف پول به‌ازای هر دعوت (بدون نیاز به خرید)، تا سقف مشخص
    "referral_invite_bonus_enabled": "0",
    "referral_invite_bonus_amount": "0",  # مبلغ ثابت شارژ کیف پول به‌ازای هر دعوت (تومان)
    "referral_invite_bonus_max_count": "10",  # حداکثر تعداد دعوت‌هایی که این پاداش برایشان تعلق می‌گیرد (0 = نامحدود)
    # هشدار زیرمجموعه‌گیری فیک: چون تلگرام IP/دستگاه نمی‌دهد، تشخیص صرفاً بر اساس
    # رفتار حساب‌ها (سرعت دعوت + نرخ بی‌خریدی زیرمجموعه‌ها) است.
    "referral_fraud_detection_enabled": "1",
    "referral_fraud_burst_count": "5",  # این تعداد زیرمجموعه‌ی تازه در بازه‌ی زیر یعنی هشدار
    "referral_fraud_burst_minutes": "60",  # بازه‌ی زمانی بررسی دعوت انبوه (دقیقه)
    "referral_fraud_min_invites": "5",  # حداقل تعداد دعوت لازم برای معتبر بودن معیار نرخ بی‌خریدی
    "referral_fraud_zero_purchase_ratio": "80",  # درصد زیرمجموعه‌های بی‌خرید که یعنی مشکوک
    "referral_fraud_auto_suspend": "1",  # با تشخیص مشکوک، پاداش‌های رفرال این کاربر تا بررسی ادمین متوقف شود
    # هدیه‌ی عضویت (بند ۴۶ اسپک): به کاربرانی که از X روز قبل عضو شده‌اند و تا
    # الان هیچ خریدی (سفارش تاییدشده) نداشته‌اند، یک‌بار مبلغ ثابتی به کیف پول
    # اضافه می‌شود تا برای اولین خرید تشویق شوند.
    "signup_gift_enabled": "0",
    "signup_gift_amount": "0",  # مبلغ هدیه (تومان)
    "signup_gift_delay_days": "3",  # چند روز بعد از عضویت بدون خرید
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
    # امتیاز و قرعه‌کشی شبانه F18
    "score_enabled": "1",
    "lottery_enabled": "1",
    "lottery_agent_enabled": "0",
    "lottery_prize_type": "wallet",  # wallet | discount
    "lottery_prizes": "50000,30000,20000",  # رتبه‌های ۱ تا ۳؛ تومان یا درصد تخفیف
    "lottery_discount_expiry_hours": "24",
    "lottery_report_chat_id": "",  # آیدی گروه گزارش؛ خالی = ارسال برای ادمین‌ها
    "score_purchase_points": "2",  # امتیاز هر خرید تاییدشده
    "score_renewal_points": "1",  # امتیاز هر تمدید تاییدشده
    "score_referral_points": "1",  # امتیاز هر دعوت موفق
    "coin_value_toman": "0",
    "coin_convert_min": "1",
    "coin_convert_max": "0",
    "lottery_min_coins": "1",
    "coin_expiry_days": "7",
    "coin_wallet_expiry_days": "7",
    "btn_wheel": "🎡 گردونه شانس",
    # پرداخت کریپتو (Plisio)
    "crypto_payment_enabled": "0",
    "plisio_api_key": "",  # کلید API درگاه Plisio؛ از داخل بات (دکمه‌ی «تنظیم درگاه کریپتو») قابل تنظیم است
    "gemini_api_key": "",  # کلید API دستیار هوشمند (Gemini)؛ از داخل بات (دستیار هوشمند → تنظیم کلید API) قابل تنظیم است
    "groq_api_key": "",
    "openrouter_api_key": "",
    "mistral_api_key": "",
    "cohere_api_key": "",
    "cloudflare_api_token": "",
    "cloudflare_account_id": "",
    "cloudflare_model": "",  # خالی = مدل پیش‌فرض (Llama 4 Scout)؛ مدل بینایی‌دار Workers AI برای تشخیص رسید
    "openai_api_key": "",
    "anthropic_api_key": "",
    "openai_model": "",
    "anthropic_model": "",
    "ai_custom_providers": "[]",
    "ai_provider": "auto",
    "gemini_model": "gemini-3.5-flash-lite",
    "groq_model": "openai/gpt-oss-20b",
    "openrouter_model": "openrouter/free",
    "usd_to_toman_rate": "0",  # نرخ تبدیل هر ۱ دلار به تومان؛ توسط ادمین دستی تنظیم می‌شود
    # پرداخت کارت‌به‌کارت خودکار (آبان گیت وی)
    "abangateway_payment_enabled": "0",
    "abangateway_api_key": "",  # کلید API آبان گیت وی؛ از داخل بات (دکمه‌ی «تنظیم درگاه آبان گیت وی») قابل تنظیم است
    "abangateway_webhook_secret": "",
    # پرداخت کارت‌به‌کارت خودکار (بلوپال)
    "blupal_payment_enabled": "0",
    "blupal_api_key": "",  # کلید API بلوپال؛ از داخل بات (دکمه‌ی «تنظیم درگاه بلوپال») قابل تنظیم است
    # پرداخت با خرید استارز تلگرام (NoapayBot/StarBot)
    "noapay_payment_enabled": "0",
    "noapay_api_key": "",            # کلید API NoapayBot؛ از داخل بات (دکمه‌ی «تنظیم درگاه NoapayBot») قابل تنظیم است
    "noapay_webhook_secret": "",     # رمز HMAC وب‌هوک NoapayBot (X-Starbot-Signature)
    "noapay_rate_toman_per_star": "0",  # نرخ تقریبی تومان به‌ازای هر استارز؛ ۰ یعنی هنوز تنظیم نشده
    "btn_wheel_style": "success",
    # یادآوری اتمام سرویس + کد تخفیف تشویقی تمدید
    "renewal_reminder_enabled": "1",
    "renewal_reminder_days_before": "5",  # چند روز قبل از اتمام سرویس یادآوری ارسال شود
    "auto_provision_max_qty": "0",
    "daily_report_enabled": "1",
    "daily_report_time": "23:45",
    "panel_health_enabled": "1",
    "spam_guard_enabled": "1",
    "spam_limit": "35",
    "spam_window": "60",
    "report_chat_id": "",
    "low_stock_threshold": "3",  # وقتی موجودی یک محصول به این عدد یا کمتر برسد، به ادمین‌ها هشدار داده می‌شود
    "broadcast_inactive_purchase_days": "30",  # پیش‌فرض تعداد روزِ «بدون خرید» برای هدف پیام همگانی؛ هربار قابل تغییر است
    "renewal_discount_percent": "20",  # درصد تخفیف کد تشویقی تمدید
    "renewal_discount_expiry_hours": "24",  # اعتبار کد تشویقی تمدید (ساعت)
    "renewal_cashback_percent": "0",  # درصد کش‌بک تمدید؛ فقط از مبلغ پرداخت‌شده خارج از کیف پول
    "topup_cashback_percent": "0",  # درصد کش‌بک شارژ کیف پول
    "svc_refund_window_hours": "24",  # مهلت (ساعت پس از خرید) برای بازگشت وجه هنگام حذف سرویس؛ ۰ یعنی غیرفعال
    "adm_renewal_settings_style": "success",
    "adm_stock_alert_settings_style": "",
    # یادآوری اتمام حجم + کد تخفیف تشویقی تمدید (مستقل از یادآوری تاریخ انقضا)
    "volume_reminder_enabled": "1",
    "volume_reminder_mode": "percent",  # "percent" یا "gb" - مبنای آستانه‌ی هشدار
    "volume_reminder_percent": "80",  # وقتی درصد مصرف به این عدد رسید (mode=percent)
    "volume_reminder_gb_left": "2",  # وقتی حجم باقی‌مانده به این تعداد گیگ رسید (mode=gb)‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    "volume_discount_percent": "20",  # درصد تخفیف کد تشویقی اتمام حجم
    "volume_discount_expiry_hours": "24",  # اعتبار کد تشویقی اتمام حجم (ساعت)
    "adm_volume_reminder_settings_style": "success",
    # هشدار اتصال / عدم‌اتصال به کانفیگ
    "connect_alert_enabled": "0",
    "connect_alert_threshold_mb": "1",
    "no_connect_alert_enabled": "0",
    "no_connect_alert_hours": "24",
    "no_connect_alert_threshold_mb": "1",
    "adm_connect_alert_settings_style": "success",
    # تخفیف تمدید کامل زودهنگام
    "early_renewal_discount_enabled": "0",
    "early_renewal_discount_days": "5",
    "early_renewal_discount_percent": "10",
    "adm_early_renewal_discount_style": "success",
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
    "adm_ssh_menu_style": "",
    "adm_custom_config_settings_style": "",
    # چیدمان دکمه‌های منوی اصلی (ترتیب و نمایش) - آرایه JSON از کلیدها
    "menu_order": '["miniapp","btn_buy","btn_test","btn_my_orders","btn_referral","btn_wheel","btn_contact","btn_admin_panel"]',
    "miniapp_enabled": "1",
    "reseller_request_enabled": "1",
    # منوی یکپارچه انتخاب سطح نمایندگی برای کاربران عادی
    "reseller_tiers_menu_enabled": "1",
    # روشن/خاموش سراسری هرکدام از ۵ محور فرم درخواست نمایندگی (بند ۶ اسپک).
    # اگر مالک بخواهد یک محور را کلاً از فرم درخواست حذف کند (نه فقط رد کردنش توسط
    # کاربر)، همین کلیدها را از پنل ادمین (API) به "0" تغییر می‌دهد.
    "reseller_axis_bot_dedicated_enabled": "1",
    "reseller_axis_bot_inline_link_enabled": "1",
    "reseller_axis_bot_none_enabled": "1",
    "reseller_axis_webpanel_enabled": "1",
    "reseller_axis_miniapp_enabled": "1",
    "reseller_axis_supply_volume_enabled": "1",
    "reseller_axis_supply_fixed_product_enabled": "1",
    # لیست id محصولات مجاز برای مدل تامین «محصول آماده»، جدا با کاما؛ خالی یعنی همه‌ی محصولات مجازند.
    "reseller_fixed_product_ids": "",
    # حداقل مبلغ مجاز برای هر روش پرداخت (تومان). 0 یعنی بدون محدودیت.
    "min_amount_wallet_topup": "1000",  # حداقل مبلغ شارژ کیف پول
    "max_wallet_balance": "0",  # سقف موجودی کیف پول؛ 0 یعنی بدون محدودیت
    "card_gate_min_purchases": "0",  # حداقل تعداد خرید موفق برای نمایش شماره کارت؛ 0 = بدون شرط
    "card_gate_min_days": "0",  # حداقل تعداد روز از استارت بات برای نمایش شماره کارت؛ 0 = بدون شرط
    "location_change_user_limit": "0",  # 0 = نامحدود
    "location_change_free_quota": "0",  # 0 = بدون سهمیه رایگان
    "min_amount_card": "0",             # حداقل مبلغ برای پرداخت کارت‌به‌کارت دستی
    "min_amount_abangateway": "0",      # حداقل مبلغ برای آبان گیت وی
    "min_amount_blupal": "0",           # حداقل مبلغ برای بلوپال
    "min_amount_noapay": "0",           # حداقل مبلغ برای NoapayBot
    "min_amount_crypto": "0",           # حداقل مبلغ برای پرداخت کریپتو
    "min_amount_card_auto": "0",        # حداقل مبلغ برای کارت‌به‌کارت خودکار
    "card_to_card_auto_enabled": "0",
    "card_to_card_auto_timeout_minutes": "15",  # بعد این‌مدت اگر پیامک نرسد، به بررسی دستی می‌رود
    "card_to_card_auto_amount_digits": "3",     # چند رقم آخر مبلغ برای یکتاسازی تصادفی اضافه شود
    "card_to_card_sms_amount_unit": "rial",     # واحد مبلغ داخل پیامک بانک: rial یا toman
    "card_to_card_sms_webhook_token": "",       # توکن احراز هویت وب‌هوک اپ BankSmsForwarder
    "discount_order_expiry_minutes": "60",      # قابلیت ۸۶: بعد این‌مدت بدون رسید، سفارشِ دارای کد تخفیف خودکار لغو و کد آزاد می‌شود؛ ۰=غیرفعال
    # قابلیت‌های افزوده
    "global_bot_enabled": "1",
    "phone_auth_enabled": "1",
    "phone_auth_allow_international": "1",
    "smart_subscription_enabled": "1",
    "smart_subscription_base_url": "",
}
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
DEFAULT_SETTINGS.update(extra_gateway_registry.default_settings())

# ساب اختصاصی (کلیدهای dsub_*؛ تعریف مرجع در dedicated_sub.py)
from dedicated_sub import DSUB_DEFAULTS as _DSUB_DEFAULTS
DEFAULT_SETTINGS.update(_DSUB_DEFAULTS)

# روش‌های پرداخت «داخلی» (غیر از درگاه‌های سفارشی) که در همه‌جای پروژه
# (بات، پنل ادمین وب، مینی‌اپ) به همین شکل شناخته می‌شوند. کلید تنظیم حداقل
# مبلغ هر کدام هم از همین‌جا ساخته می‌شود (min_amount_<key>) تا یک‌جا مدیریت شود.
BUILTIN_PAYMENT_METHODS = [
    {"key": "wallet", "label": "👛 کیف پول", "enable_setting": None},
    {"key": "card", "label": "💳 کارت‌به‌کارت (ارسال رسید)", "enable_setting": "card_to_card_enabled"},
    {"key": "abangateway", "label": "💳 آبان گیت وی (تایید آنی)", "enable_setting": "abangateway_payment_enabled"},
    {"key": "blupal", "label": "💳 بلوپال (تایید آنی)", "enable_setting": "blupal_payment_enabled"},
    {"key": "noapay", "label": "⭐ NoapayBot - استارز تلگرام (تایید آنی)", "enable_setting": "noapay_payment_enabled"},
    {"key": "crypto", "label": "🪙 ارز دیجیتال (تایید آنی)", "enable_setting": "crypto_payment_enabled"},
    {"key": "card_auto", "label": "💳 کارت‌به‌کارت (تایید خودکار پیامکی)", "enable_setting": "card_to_card_auto_enabled"},
]
for _gw_key in extra_gateway_registry.GATEWAY_ORDER:
    _gw = extra_gateway_registry.GATEWAYS[_gw_key]
    BUILTIN_PAYMENT_METHODS.append({
        "key": _gw_key,
        "label": f"{_gw['icon']} {_gw['title']} (تایید آنی)",
        "enable_setting": extra_gateway_registry.enable_setting(_gw_key),
    })


# تعریف کامل دکمه‌های قابل‌مدیریت در منوی اصلی: کلید -> متادیتا
# toggle_key: نام تنظیمی که فعال/غیرفعال بودن دکمه را کنترل می‌کند (None یعنی همیشه نمایش داده می‌شود)
# admin_only: اگر True فقط برای ادمین‌ها نمایش داده می‌شود
MENU_BUTTON_META = {
    "miniapp": {"label": "دکمه مینی‌اپ فروشگاه", "toggle_key": "miniapp_enabled", "admin_only": False, "has_text": False, "has_style": False, "default_text": None},
    "btn_buy": {"label": "دکمه خرید کانفیگ", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True, "default_text": "🛒 خرید کانفیگ"},
    "btn_test": {"label": "دکمه کانفیگ تست", "toggle_key": "test_enabled", "admin_only": False, "has_text": True, "has_style": True, "default_text": "🧪 کانفیگ تست رایگان"},
    "btn_my_orders": {"label": "دکمه حساب کاربری من", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True, "default_text": "🧾 حساب کاربری من"},
    "btn_referral": {"label": "دکمه زیرمجموعه‌گیری", "toggle_key": "referral_button_enabled", "admin_only": False, "has_text": True, "has_style": True, "default_text": "🤝 زیرمجموعه‌گیری من"},
    "btn_wheel": {"label": "دکمه گردونه شانس", "toggle_key": "wheel_enabled", "admin_only": False, "has_text": True, "has_style": True, "default_text": "🎡 گردونه شانس"},
    "btn_contact": {"label": "دکمه ارتباط با پشتیبانی", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True, "default_text": "📞 ارتباط با پشتیبانی"},
    "btn_admin_panel": {"label": "دکمه پنل مدیریت", "toggle_key": None, "admin_only": True, "has_text": True, "has_style": True, "default_text": "⚙️ پنل مدیریت"},
    # btn_reseller_panel بر اساس وضعیت کاربر (نماینده بودن/نبودن) به‌صورت پویا نمایش
    # داده می‌شود، نه با یک toggle سراسری؛ به همین دلیل toggle_key ندارد ولی مثل
    # بقیه‌ی دکمه‌ها متن/رنگ قابل تنظیم و در چیدمان منو قابل جابجایی است.
    "btn_reseller_panel": {"label": "دکمه پنل نمایندگی", "toggle_key": None, "admin_only": False, "has_text": True, "has_style": True, "default_text": "🧑‍💼 پنل نمایندگی"},
    "btn_reseller_tiers": {"label": "دکمه درخواست نمایندگی", "toggle_key": "reseller_request_enabled", "admin_only": False, "has_text": True, "has_style": True, "default_text": "🤝 نمایندگی"},
    "btn_tutorial": {"label": "دکمه آموزش", "toggle_key": "tutorial_menu_enabled", "admin_only": False, "has_text": True, "has_style": True, "default_text": "📚 آموزش"},
}
# دکمه‌های داخل «حساب کاربری» و صفحه‌ی جزئیات هر سرویس: هرکدام با یک تنظیم
# جدا فعال/غیرفعال می‌شوند (پیش‌فرض همه فعال). کلید -> (برچسب برای ادمین، مقدار پیش‌فرض)
ACCOUNT_TOGGLE_KEYS = [
    ("acct_show_orders", "📦 نمایش «سرویس‌ها و سفارش‌های من»", "1"),
    ("acct_show_tutorial", "📚 نمایش «آموزش»", "1"),
    ("acct_show_referral", "🤝 نمایش «زیرمجموعه‌گیری من»", "1"),
    ("acct_show_wallet", "👛 نمایش «کیف پول من»", "1"),
    ("acct_show_lootbox", "🎁 نمایش «صندوق شانس» (فقط وقتی صندوق شانس روشن باشد)", "1"),
    ("acct_show_add_service", "➕ نمایش «افزودن حساب (اتصال کانفیگ قبلی)»", "1"),
    ("acct_show_merge", "🔗 نمایش «ادغام با حساب ایمیلی»", "1"),
    ("acct_add_service_by_username", "🔑 افزودن حساب با نام کاربری کانفیگ (علاوه بر لینک ساب)", "1"),
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
    ("svc_show_location_transfer", "📍 دکمه «تغییر لوکیشن سرویس»", "1"),
    ("svc_show_history", "📜 دکمه «تاریخچه سرویس»", "1"),
    ("svc_show_inquiry", "🔍 دکمه «استعلام»", "1"),
    ("svc_show_rating", "⭐ دکمه «امتیازدهی به سرویس»", "1"),
    ("wallet_show_transfer", "💸 دکمه «انتقال موجودی به کاربر دیگر»", "1"),
]

# ---------------------------------------------------------------------------
# رجیستری سراسری «کاستوم‌سازی دکمه‌ها» (پنل وب، تب مستقل «دکمه‌ها»)
# هر گروه یعنی یک نقطه از بات که چند دکمه‌ی کنار هم دارد؛ داخل هر گروه:
# متن (اگر has_text)، رنگ (اگر has_style) و ترتیب هر آیتم قابل ذخیره‌سازی است.
# افزودن یک دکمه‌ی جدید به بات یعنی فقط یک ورودی به این دیکشنری‌ها اضافه شود؛
# تب پنل وب و APIهای آن بدون تغییر، آیتم جدید را خودکار نشان می‌دهند.
# ---------------------------------------------------------------------------

PAYMENT_METHOD_META = {
    "card": {"label": "کارت‌به‌کارت (ارسال رسید)", "default_text": "💳 کارت‌به‌کارت (ارسال رسید)"},
    "card_auto": {"label": "کارت‌به‌کارت خودکار (تاییدپیامکی)", "default_text": "💳 کارت‌به‌کارت (تایید خودکار پیامکی)"},
    "abangateway": {"label": "آبان‌گیت‌وی", "default_text": "💳 پرداخت خودکار کارت‌به‌کارت (تایید آنی)"},
    "blupal": {"label": "بلوپال", "default_text": "💳 پرداخت خودکار کارت‌به‌کارت (تایید آنی)"},
    "noapay": {"label": "NoapayBot (استارز تلگرام)", "default_text": "⭐ NoapayBot - استارز تلگرام (تایید آنی)"},
    "crypto": {"label": "ارز دیجیتال (Plisio)", "default_text": "🪙 پرداخت با ارز دیجیتال (تایید آنی)"},
}
for _gw_key in extra_gateway_registry.GATEWAY_ORDER:
    _gw = extra_gateway_registry.GATEWAYS[_gw_key]
    PAYMENT_METHOD_META[_gw_key] = {"label": _gw["title"], "default_text": _gw["default_text"]}
DEFAULT_PAYMENT_METHOD_ORDER = ["card", "card_auto", "abangateway", "blupal", "noapay", "crypto"] + list(extra_gateway_registry.GATEWAY_ORDER)

ACCOUNT_HUB_META = {
    "acct_orders": {"label": "سرویس‌ها و سفارش‌های من", "default_text": "📦 سرویس‌ها و سفارش‌های من"},
    "acct_tutorial": {"label": "آموزش", "default_text": "📚 آموزش"},
    "acct_referral": {"label": "زیرمجموعه‌گیری من", "default_text": "🤝 زیرمجموعه‌گیری من"},
    "acct_wallet": {"label": "کیف پول من", "default_text": "👛 کیف پول من"},
    "acct_lootbox": {"label": "صندوق شانس", "default_text": "🎁 صندوق شانس"},
    "acct_add_service": {"label": "افزودن حساب", "default_text": "➕ افزودن حساب (اتصال کانفیگ قبلی)"},
    "acct_merge": {"label": "ادغام با حساب ایمیلی", "default_text": "🔗 ادغام با حساب ایمیلی"},
}
DEFAULT_ACCOUNT_HUB_ORDER = ["acct_orders", "acct_tutorial", "acct_referral", "acct_wallet", "acct_lootbox", "acct_add_service", "acct_merge"]

BUYFLOW_META = {
    "btn_custom_config": {"label": "ساخت کانفیگ شخصی", "default_text": "🛠 ساخت کانفیگ شخصی"},
    "btn_buy_continue": {"label": "ادامه و ارسال رسید", "default_text": "✅ ادامه و ارسال رسید"},
    "btn_enter_code": {"label": "وارد کردن کد تخفیف", "default_text": "🎟 وارد کردن کد تخفیف"},
    "btn_buy_back": {"label": "بازگشت (مسیر خرید)", "default_text": "⬅️ بازگشت"},
}
DEFAULT_BUYFLOW_CONFIRM_ORDER = ["btn_buy_continue", "btn_enter_code"]

# دکمه‌های مسیر خرید که متنشان پویا/داینامیک است (نام دسته یا محصول از دیتابیس)
# و بنابراین متن ثابتی برای ویرایش ندارند - فقط رنگشان از تب «دکمه‌های ربات»
# قابل تغییر است (قبلاً در تب «تنظیمات و برندینگ» بودند، اینجا یکپارچه شدند).
BUYFLOW_STYLE_ONLY_META = {
    "btn_cat_select": {"label": "انتخاب دسته‌بندی"},
    "btn_product_select": {"label": "انتخاب محصول"},
}
DEFAULT_SETTINGS.update({key: default for key, _label, default in ACCOUNT_TOGGLE_KEYS})

DEFAULT_MENU_ORDER = [
    "miniapp", "btn_reseller_panel", "btn_reseller_tiers", "btn_buy", "btn_test",
    "btn_my_orders", "btn_tutorial", "btn_referral", "btn_wheel", "btn_contact", "btn_admin_panel",
]


AUTO_PROVISION_UNLIMITED_STOCK = 10 ** 9


@contextmanager
def _wallet_tag(conn, user_id, kind, note=None):
    """برچسب نوع/توضیح تراکنش کیف پول را فقط برای همین اتصال و آپدیت داخل بلوک می‌گذارد."""
    conn.execute(
        "INSERT OR REPLACE INTO wallet_tx_label (user_id, kind, note) VALUES (?, ?, ?)", (user_id, kind, note)
    )
    try:
        yield
    finally:
        conn.execute("DELETE FROM wallet_tx_label WHERE user_id=?", (user_id,))


#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
