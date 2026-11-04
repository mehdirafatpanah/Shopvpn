# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
تعریف فیلدهای تب «تنظیمات و برندینگ» به‌صورت داده‌محور (Schema)، برای اینکه
اپ موبایل Native بتواند بدون آپدیت، همان فرمی را بسازد که پنل وب دارد.

⚠️ نکته‌ی مهم برای توسعه‌ی بعدی:
پنل وب (static/app.js) همین گروه‌بندی را به‌صورت جدا در آرایه‌ی SETTINGS_GROUPS
دارد (چون جاوااسکریپت است و نمی‌تواند مستقیم از پایتون import کند). یعنی این
فایل «منبع حقیقت» برای اپ موبایل است، ولی هم‌زمان با SETTINGS_GROUPS در app.js
همگام نیست. وقتی فیلد تنظیمات جدیدی اضافه می‌کنی:
  ۱) به SETTINGS_GROUPS در admin_panel/static/app.js اضافه کن (برای پنل وب)
  ۲) دقیقاً همان فیلد را اینجا هم اضافه کن (برای اپ موبایل)
اگر در آینده خواستی این دو یکی شوند، می‌شود این JSON را از یک اندپوینت (مثلاً
GET /api/settings/schema) گرفت و هم در app.js و هم در اپ موبایل از همان
استفاده کرد — فعلاً برای کمِ‌ریسک نگه‌داشتن تغییرات پنل وب، جدا نگه داشته شده.

هر فیلد دقیقاً معادل نوع خودش در پنل وب است:
  text | textarea | password | number | bool | color | select
مقدار هر فیلد از/به GET و POST /api/settings (کلید-مقدار ساده) خوانده/نوشته می‌شود.
"""

import extra_gateway_registry

SETTINGS_FORM_SECTIONS = [
    {
        "title": "📝 محتوا و متن‌ها",
        "groups": [
            {
                "title": "متن‌های پایه",
                "fields": [
                    {"key": "store_name", "label": "نام فروشگاه", "type": "text"},
                    {"key": "welcome_text", "label": "متن خوش‌آمدگویی (شروع ربات)", "type": "textarea"},
                    {"key": "contact_text", "label": "متن ابتدای بخش ارتباط با پشتیبانی", "type": "textarea"},
                    {"key": "after_buy_text", "label": "متن راهنمای پرداخت (بعد از انتخاب محصول)", "type": "textarea"},
                ],
            },
        ],
    },
    {
        "title": "💳 پرداخت و مالی",
        "groups": [
            {
                "title": "کارت بانکی",
                "fields": [
                    {"key": "card_number", "label": "شماره کارت", "type": "text"},
                    {"key": "card_holder", "label": "نام صاحب کارت", "type": "text"},
                ],
            },
            {
                "title": "🔗 برندینگ صفحه لینک ساب",
                "fields": [
                    {"key": "dsub_brand", "label": "نام برند صفحه لینک ساب", "type": "text"},
                    {"key": "dsub_logo_url", "label": "لوگوی صفحه لینک ساب", "type": "text"},
                    {"key": "dsub_notice", "label": "اعلان بالای صفحه", "type": "textarea"},
                    {"key": "dsub_support_url", "label": "لینک پشتیبانی صفحه ساب", "type": "text"},
                    {"key": "dsub_footer_text", "label": "متن پایین صفحه", "type": "text"},
                    {"key": "dsub_theme", "label": "تم صفحه ساب", "type": "select", "options": [["auto", "خودکار"], ["light", "روشن"], ["dark", "تیره"]]},
                    {"key": "dsub_show_configs", "label": "نمایش کانفیگ‌ها", "type": "bool"},
                    {"key": "dsub_show_chart", "label": "نمایش نمودار مصرف", "type": "bool"},
                    {"key": "dsub_show_qr", "label": "نمایش QR", "type": "bool"},
                    {"key": "dsub_show_apps", "label": "نمایش برنامه‌ها", "type": "bool"},
                    {"key": "dsub_show_faq", "label": "نمایش بخش عیب‌یابی", "type": "bool"},
                ],
            },
            {
                "title": "قابلیت ۸۶: انقضای سفارش‌های رهاشده با کد تخفیف",
                "fields": [
                    {"key": "discount_order_expiry_minutes",
                     "label": "مهلت لغو خودکار سفارش (دقیقه) اگر رسید کارت‌به‌کارت فرستاده نشود؛ ۰ = غیرفعال",
                     "type": "number"},
                ],
            },
            {
                "title": "نرخ ارز پشتیبان (عمومی فروشگاه)",
                "fields": [
                    {"key": "manual_usd_rate_toman",
                     "label": "نرخ دلار دستی — فقط وقتی همه‌ی منابع زنده شکست بخورند استفاده می‌شود",
                     "type": "number"},
                ],
            },
            {
                "title": "🪙 پرداخت کریپتو (Plisio)",
                "fields": [
                    {"key": "crypto_payment_enabled", "label": "فعال بودن پرداخت کریپتو", "type": "bool"},
                    {"key": "plisio_api_key", "label": "کلید API درگاه Plisio", "type": "password"},
                ],
            },
            {
                "title": "💳 آبان گیت‌وی (کارت به کارت خودکار)",
                "fields": [
                    {"key": "abangateway_payment_enabled", "label": "فعال بودن درگاه آبان گیت‌وی", "type": "bool"},
                    {"key": "abangateway_api_key", "label": "کلید API آبان گیت‌وی", "type": "password"},
                    {"key": "abangateway_webhook_secret", "label": "کلید مخفی وب‌هوک آبان گیت‌وی", "type": "password"},
                ],
            },
            {
                "title": "💳 بلوپال (کارت به کارت خودکار)",
                "fields": [
                    {"key": "blupal_payment_enabled", "label": "فعال بودن درگاه بلوپال", "type": "bool"},
                    {"key": "blupal_api_key", "label": "کلید API بلوپال", "type": "password"},
                ],
            },
            {
                "title": "⭐ NoapayBot - استارز تلگرام (تایید آنی)",
                "fields": [
                    {"key": "noapay_payment_enabled", "label": "فعال بودن درگاه NoapayBot", "type": "bool"},
                    {"key": "noapay_api_key", "label": "کلید API NoapayBot", "type": "password"},
                    {"key": "noapay_webhook_secret", "label": "رمز HMAC وب‌هوک (X-Starbot-Signature)", "type": "password"},
                    {"key": "noapay_rate_toman_per_star", "label": "نرخ تومان به‌ازای هر استارز", "type": "number"},
                ],
            },
            *extra_gateway_registry.settings_groups(),
            {
                "title": "📡 کارت‌به‌کارت با تایید خودکار (پیامک بانک)",
                "fields": [
                    {"key": "card_to_card_auto_enabled",
                     "label": "فعال بودن (نیازمند حداقل یک کارت فعال)", "type": "bool"},
                    {"key": "card_to_card_auto_timeout_minutes",
                     "label": "مهلت هر مبلغ (دقیقه) - بعدش می‌رود صف بررسی دستی", "type": "number"},
                    {"key": "card_to_card_auto_amount_digits",
                     "label": "تعداد رقم آخر برای یکتاسازی مبلغ (پیشنهاد: ۳)", "type": "number"},
                    {"key": "card_to_card_sms_amount_unit", "label": "واحد مبلغ داخل پیامک بانک", "type": "select",
                     "options": [["rial", "ریال (اکثر بانک‌ها)"], ["toman", "تومان"]]},
                ],
            },
        ],
    },
    {
        "title": "⚙️ سرویس‌های ویژه",
        "groups": [
            {
                "title": "🛒 سقف تعداد خرید در هر سفارش",
                "fields": [
                    {"key": "auto_provision_max_qty", "label": "حداکثر تعداد محصولات خودکار در هر سفارش (۰=نامحدود)", "type": "number"},
                ],
            },
            {
                "title": "📊 گزارش روزانه‌ی فروش",
                "fields": [
                    {"key": "daily_report_enabled", "label": "ارسال گزارش روزانه‌ی فروش به مدیران", "type": "bool"},
                    {"key": "inactive_config_delete_time", "label": "ساعت حذف خودکار کانفیگ‌های غیرفعال (HH:MM به وقت تهران؛ خالی = خاموش)", "type": "text"},
                    {"key": "daily_report_time", "label": "ساعت ارسال به وقت تهران (مثل 23:45)", "type": "text"},
                ],
            },
            {
                "title": "📣 گروه گزارش تاپیک‌دار",
                "fields": [
                    {"key": "report_chat_id", "label": "آیدی عددی سوپرگروه فوروم (مثل -100123456789)؛ خالی یعنی ارسال به پیام خصوصی مدیران. برای گرفتن آیدی، @myidbot را به گروه اضافه کن و /getgroupid@myidbot را در گروه بفرست", "type": "text"},
                ],
            },
            {
                "title": "🩺 پایش سلامت پنل‌های VPN",
                "fields": [
                    {"key": "panel_health_enabled", "label": "هشدار قطعی و بازیابی پنل‌ها به مدیران (بررسی هر ۵ دقیقه)", "type": "bool"},
                ],
            },
            {
                "title": "🛡 ضداسپم کاربران",
                "fields": [
                    {"key": "spam_guard_enabled", "label": "فعال بودن ضداسپم (هشدار و سپس مسدودسازی خودکار)", "type": "bool"},
                    {"key": "spam_limit", "label": "حداکثر تعداد درخواست در بازه‌ی زمانی", "type": "number"},
                    {"key": "spam_window", "label": "بازه‌ی زمانی (ثانیه)", "type": "number"},
                ],
            },
            {
                "title": "کانفیگ شخصی/سفارشی",
                "fields": [
                    {"key": "custom_config_enabled", "label": "فعال بودن ساخت کانفیگ شخصی", "type": "bool"},
                    {"key": "custom_config_min_gb", "label": "حداقل حجم مجاز (گیگ)", "type": "number"},
                    {"key": "custom_config_max_gb", "label": "حداکثر حجم مجاز (گیگ)", "type": "number"},
                    {"key": "custom_config_duration_days", "label": "مدت اعتبار (روز)", "type": "number"},
                    {"key": "btn_custom_config", "label": "متن دکمه ساخت کانفیگ شخصی", "type": "text"},
                ],
            },
            {
                "title": "🗺 نقشه زنده شبکه (فروشگاه وب)",
                "fields": [
                    {"key": "netmap_locations", "label": "اصلاح دستی مکان سرورها (JSON: product_ids یا match + cc, city, city_fa, lat, lon)", "type": "textarea"},
                ],
            },
            {
                "title": "🧾 نمایش دکمه‌های حساب کاربری",
                "fields": [
                    {"key": "acct_show_orders", "label": "نمایش «سرویس‌ها و سفارش‌های من»", "type": "bool"},
                    {"key": "acct_show_referral", "label": "نمایش «زیرمجموعه‌گیری من»", "type": "bool"},
                    {"key": "acct_show_wallet", "label": "نمایش «کیف پول من»", "type": "bool"},
                ],
            },
            {
                "title": "🛠 نمایش دکمه‌های سرویس",
                "fields": [
                    {"key": "svc_show_renew_full", "label": "دکمه «تمدید کامل سرویس»", "type": "bool"},
                    {"key": "svc_show_renew_volume", "label": "دکمه «تمدید حجم سرویس»", "type": "bool"},
                    {"key": "svc_show_renew_time", "label": "دکمه «تمدید زمان سرویس»", "type": "bool"},
                    {"key": "svc_show_cut_access", "label": "دکمه «قطع دسترسی و لینک جدید»", "type": "bool"},
                    {"key": "svc_show_update_config", "label": "دکمه «بروزرسانی کانفیگ»", "type": "bool"},
                    {"key": "svc_show_qr", "label": "دکمه «کیوآر کانفیگ»", "type": "bool"},
                    {"key": "svc_show_delete", "label": "دکمه «حذف کامل سرویس»", "type": "bool"},
                    {"key": "svc_refund_window_hours", "label": "مهلت بازگشت وجه هنگام حذف سرویس (ساعت پس از خرید؛ ۰ = غیرفعال)", "type": "number"},
                    {"key": "svc_show_toggle", "label": "دکمه «فعال/غیرفعال کردن کانفیگ»", "type": "bool"},
                    {"key": "svc_show_rename", "label": "دکمه «تغییر نام کانفیگ»", "type": "bool"},
                    {"key": "svc_show_auto_renew", "label": "دکمه «تمدید خودکار»", "type": "bool"},
                    {"key": "svc_show_transfer", "label": "دکمه «انتقال کانفیگ»", "type": "bool"},
                    {"key": "svc_show_history", "label": "دکمه «تاریخچه سرویس»", "type": "bool"},
                ],
            },
        ],
    },
]
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


# ============================================================================
#  تب «تنظیمات فروش» — بر خلاف تب برندینگ که یک فروشگاه کلید-مقدار ساده
#  (/api/settings) دارد، این تب از چند اندپوینت REST جدا با بدنه‌ی JSON
#  تایپ‌شده تشکیل شده (هر «کارت» زیر معادل دقیق همان چیزی است که در
#  admin_panel/static/app.js تابع renderSalesSettings() می‌سازد). به همین‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
#  دلیل هر کارت load_url/submit_url مستقل خودش را دارد و روی ذخیره، کل آبجکت
#  (نه فقط فیلدهای تغییریافته) به همان اندپوینت پست می‌شود.
# ============================================================================

SALES_SETTINGS_STATIC_CARDS = [
    {
        "title": "🔗 رفرال — سه مدل مستقل زیرمجموعه‌گیری",
        "load_url": "/api/settings/referral", "submit_url": "/api/settings/referral",
        "fields": [
            {"key": "enabled", "label": "① پورسانت درصدی از خرید — فعال", "type": "bool"},
            {"key": "percent", "label": "درصد پورسانت", "type": "number"},
            {"key": "commission_max_count", "label": "سقف تعداد نفرات پورسانت‌دار (۰ = نامحدود)", "type": "number"},
            {"key": "free_config_enabled", "label": "② کانفیگ رایگان با تعداد دعوت مشخص — فعال", "type": "bool"},
            {"key": "free_config_threshold", "label": "تعداد دعوت لازم", "type": "number"},
            # options این فیلد در سرور (server.py) با لیست زنده‌ی محصولات جایگزین می‌شود‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            {"key": "free_config_product_id", "label": "محصول جایزه", "type": "select_int_nullable", "options": []},
            {"key": "invite_bonus_enabled", "label": "③ شارژ ثابت کیف‌پول به‌ازای هر دعوت — فعال", "type": "bool"},
            {"key": "invite_bonus_amount", "label": "مبلغ شارژ (تومان)", "type": "number"},
            {"key": "invite_bonus_max_count", "label": "سقف تعداد دعوت‌های مشمول (۰ = نامحدود)", "type": "number"},
        ],
    },
    {
        "title": "🚨 هشدار زیرمجموعه‌گیری فیک",
        "load_url": "/api/settings/referral-fraud", "submit_url": "/api/settings/referral-fraud",
        "fields": [
            {"key": "detection_enabled", "label": "فعال", "type": "bool"},
            {"key": "burst_count", "label": "تعداد دعوت که یعنی «انبوه»", "type": "number"},
            {"key": "burst_minutes", "label": "بازه‌ی زمانی دعوت انبوه (دقیقه)", "type": "number"},
            {"key": "min_invites", "label": "حداقل تعداد دعوت لازم برای بررسی نرخ بی‌خریدی", "type": "number"},
            {"key": "zero_purchase_ratio", "label": "درصد بی‌خریدی که یعنی مشکوک", "type": "number"},
            {"key": "auto_suspend", "label": "توقف خودکار پاداش رفرال کاربر مشکوک تا بررسی دستی", "type": "bool"},
        ],
    },
    {
        "title": "🎰 گردونه‌ی شانس",
        "load_url": "/api/settings/wheel", "submit_url": "/api/settings/wheel",
        "fields": [
            {"key": "enabled", "label": "فعال", "type": "bool"},
            {"key": "win_percent", "label": "درصد برد", "type": "number"},
            {"key": "prizes", "label": "جوایز (٪ تخفیف، با کاما جدا کن)", "type": "number_list"},
            {"key": "code_expiry_hours", "label": "اعتبار کد (ساعت)", "type": "number"},
            {"key": "cooldown_hours", "label": "فاصله‌ی بین دو چرخش (ساعت)", "type": "number"},
        ],
    },
    {
        "title": "⏳ یادآوری تمدید",
        "load_url": "/api/settings/renewal", "submit_url": "/api/settings/renewal",
        "fields": [
            {"key": "enabled", "label": "فعال", "type": "bool"},
            {"key": "days_before", "label": "چند روز قبل از انقضا", "type": "number"},
            {"key": "discount_percent", "label": "درصد تخفیف کد پیشنهادی", "type": "number"},
            {"key": "discount_expiry_hours", "label": "اعتبار کد (ساعت)", "type": "number"},
        ],
    },
    {
        "title": "📶 یادآوری بر اساس حجم مصرفی",
        "load_url": "/api/settings/volume-reminder", "submit_url": "/api/settings/volume-reminder",
        "fields": [
            {"key": "enabled", "label": "فعال", "type": "bool"},
            {"key": "mode", "label": "مبنای آستانه", "type": "select",
             "options": [["percent", "درصد باقی‌مانده"], ["gb", "گیگابایت باقی‌مانده"]]},
            {"key": "percent", "label": "درصد آستانه (وقتی مبنا درصد است)", "type": "number"},
            {"key": "gb_left", "label": "گیگ باقی‌مانده (وقتی مبنا گیگ است)", "type": "number"},
            {"key": "discount_percent", "label": "درصد تخفیف کد پیشنهادی", "type": "number"},
            {"key": "discount_expiry_hours", "label": "اعتبار کد (ساعت)", "type": "number"},
        ],
    },
    {
        "title": "🧪 کانفیگ تست",
        "load_url": "/api/settings/test-config", "submit_url": "/api/settings/test-config",
        "fields": [
            {"key": "bank_stock", "label": "موجودی بانک لینک دستی (قدیمی)", "type": "info"},
            {"key": "enabled", "label": "فعال", "type": "bool"},
        ],
        # این دکمه کل کانفیگ تست را برای همه‌ی کاربران بازنشانی می‌کند؛ چون
        # عملیات مخربی است، جدا از فرم بالا و با تاییدیه نشان داده می‌شود.
        # مدیریت لیست پلن‌های کانفیگ تست (افزودن/ویرایش/حذف) فعلاً فقط در
        # پنل وب موجود است.
        "danger_action": {
            "label": "بازنشانی کانفیگ تست برای همه‌ی کاربران",
            "endpoint": "/api/settings/test-config/reset-all", "method": "POST",
            "confirm_text": "کانفیگ تست همه‌ی کاربران بازنشانی شود؟ این عملیات قابل بازگشت نیست.",
        },
    },
    {
        "title": "📢 عضویت اجباری در کانال",
        "load_url": "/api/settings/force-join", "submit_url": "/api/settings/force-join",
        "fields": [
            {"key": "enabled", "label": "فعال", "type": "bool"},
            {"key": "channel", "label": "آیدی کانال (مثل @my_channel)", "type": "text"},
        ],
    },
    {
        "title": "📉 هشدار موجودی کم محصول",
        "load_url": "/api/settings/stock-alert", "submit_url": "/api/settings/stock-alert",
        "fields": [
            {"key": "threshold", "label": "آستانه (وقتی موجودی یک محصول به این عدد برسد، به ادمین‌ها اطلاع داده می‌شود)", "type": "number"},
        ],
    },
]


def sales_settings_cards(product_options):
    """کارت رفرال به یک select زنده از محصولات واجد شرایط جایزه نیاز دارد؛
    چون این لیست به داده‌ی لحظه‌ای دیتابیس بستگی دارد (نه یک مقدار ثابت مثل
    بقیه‌ی فیلدها)، اینجا در لحظه‌ی ساخت پیکربندی جایگزین می‌شود."""
    import copy
    cards = copy.deepcopy(SALES_SETTINGS_STATIC_CARDS)
    for field in cards[0]["fields"]:
        if field["key"] == "free_config_product_id":
            field["options"] = product_options
    return cards
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
