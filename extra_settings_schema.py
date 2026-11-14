# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
اسکیمای مشترک «تنظیمات تکمیلی» برای پنل وب مدیر و بخش مدیریت مینی‌اپ.

تنظیماتی که بات از آن‌ها استفاده می‌کند ولی تا الان در پنل وب یا مینی‌اپ فرم
نداشتند اینجا تعریف شده‌اند. هر دو سرویس (admin_panel/server.py و
miniapp/server.py) از همین فایل می‌خوانند/می‌نویسند؛ پس برای افزودن تنظیم جدید
فقط کافی است همین‌جا یک فیلد اضافه شود.

ساختار هر فیلد:
  key      کلید در جدول settings (همان که بات می‌خواند)
  label    برچسب فارسی
  type     bool | number | text | textarea | password | select
  default  مقدار پیش‌فرض (دقیقاً همان که کد بات وقتی تنظیم نیست استفاده می‌کند)
  hint     توضیح کوتاه (اختیاری)
  min/max  برای number (اختیاری)
  options  برای select: [[value, label], ...]

هر گروه دو پرچم دارد: web / mini. اگر False باشد یعنی آن سطح از قبل فرم اختصاصی
دارد و تکراری نمی‌شود.

مقدار bool همیشه "1" / "0" ذخیره می‌شود (با تمام الگوهای `== "1"` و `!= "0"` در بات سازگار است).
"""

from typing import Any, Dict, List, Optional

SECRET_MASK = "••••••••"


def _b(key, label, default="0", hint=""):
    return {"key": key, "label": label, "type": "bool", "default": default, "hint": hint}


def _n(key, label, default="0", hint="", min=None, max=None):
    f = {"key": key, "label": label, "type": "number", "default": default, "hint": hint}
    if min is not None:
        f["min"] = min
    if max is not None:
        f["max"] = max
    return f


def _t(key, label, default="", hint=""):
    return {"key": key, "label": label, "type": "text", "default": default, "hint": hint}


def _ta(key, label, default="", hint=""):
    return {"key": key, "label": label, "type": "textarea", "default": default, "hint": hint}


def _pw(key, label, hint=""):
    return {"key": key, "label": label, "type": "password", "default": "", "hint": hint}


def _pwm(key, label, hint=""):
    """کلید(های) API: چند کلید با ویرگول یا خط جدید؛ مقدار ذخیره‌شده خط‌به‌خط است (مثل بات و ai_support._split_keys)."""
    return {"key": key, "label": label, "type": "password", "default": "", "hint": hint, "multikey": True}


def _sel(key, label, options, default="", hint=""):
    return {"key": key, "label": label, "type": "select", "default": default, "hint": hint, "options": options}


# ---------------------------------------------------------------------------
# فیلدهایی که از منبع حقیقیِ خودِ بات ساخته می‌شوند تا بین سه سطح از هم جدا نشوند.
# ---------------------------------------------------------------------------
# دو کلیدی که در گروه «دکمه‌های صفحه‌ی سرویس (تکمیلی)» برای هر دو سطح آمده‌اند.
_SVC_EXTRA_KEYS = ("svc_show_inquiry", "svc_show_location_transfer",
                   "wallet_show_transfer")  # آخری از قبل در گروه «کیف پول و کش‌بک» هست
# کلیدهای ACCOUNT_TOGGLE_KEYS که فرم فعلی پنل وب (تب برندینگ) ندارد.
_WEB_MISSING_TOGGLES = (
    "acct_show_tutorial", "acct_show_lootbox", "svc_show_rating",
)


def _toggle_fields(only=None, exclude=()):
    """از db.constants.ACCOUNT_TOGGLE_KEYS (همان لیستی که بات استفاده می‌کند) فیلد bool می‌سازد."""
    from db.constants import ACCOUNT_TOGGLE_KEYS
    out = []
    for key, label, default in ACCOUNT_TOGGLE_KEYS:
        if key in exclude or (only is not None and key not in only):
            continue
        out.append(_b(key, label, default))
    return out


def _default_setting(key: str, fallback: str = "") -> str:
    from db.constants import DEFAULT_SETTINGS
    return str(DEFAULT_SETTINGS.get(key, fallback))


_AI_PROVIDER_OPTIONS = [
    ["auto", "🤖 خودکار (همه ارائه‌دهنده‌های تنظیم‌شده)"],
    ["gemini", "🔷 فقط Gemini"],
    ["groq", "🚀 فقط Groq"],
    ["openrouter", "🌐 فقط OpenRouter"],
    ["openai", "🟢 فقط OpenAI"],
    ["anthropic", "🟠 فقط Claude (Anthropic)"],
    ["mistral", "🌬 فقط Mistral"],
    ["cohere", "🔶 فقط Cohere"],
    ["cloudflare", "☁️ فقط Cloudflare"],
    ["custom", "🔌 فقط ارائه‌دهنده‌های سفارشی"],
]
_AI_MODEL_KEYS = ("gemini_model", "groq_model", "openrouter_model", "openai_model", "anthropic_model", "cloudflare_model")
_AI_KEY_HINT = "چند کلید را با ویرگول یا خط جدید جدا کن (چرخشی استفاده می‌شوند). خالی = بدون تغییر؛ مقدار فعلی نمایش داده نمی‌شود."
_AI_MODEL_HINT = "خالی = مدل پیش‌فرض. بدون فاصله، حداکثر ۱۲۰ نویسه."


EXTRA_SETTINGS_GROUPS: List[Dict[str, Any]] = [
    {
        "id": "terms", "title": "📜 قوانین و شرایط استفاده", "web": True, "mini": True,
        "fields": [
            _b("terms_enabled", "نمایش قوانین به کاربر جدید (و کاربرانی که هنوز نپذیرفته‌اند)", "0",
               "با روشن شدن، تا قوانین را نپذیرد کاربر به بقیه‌ی بات/مینی‌اپ دسترسی ندارد. متن قوانین نباید خالی باشد."),
            {**_ta("terms_text", "متن قوانین (حداکثر ۳۵۰۰ کاراکتر)", ""), "maxlen": 3500},
        ],
    },
    {
        "id": "bot_profile", "title": "🪪 پروفایل ربات (توضیحات قبل از استارت)", "web": True, "mini": True, "bot": True,
        "fields": [
            {**_ta("bot_desc_fa", "توضیحات ربات - فارسی (حداکثر ۵۱۲ کاراکتر)", "",
                   "متنی که کاربر جدید قبل از زدن Start زیر «What can this bot do?» می‌بیند. بعد از ذخیره خودکار روی تلگرام اعمال می‌شود. "
                   "عکس/گیف بالای آن فقط از BotFather (Edit Description Picture) قابل تنظیم است."),
             "maxlen": 512, "plain": True},
            {**_ta("bot_desc_en", "توضیحات ربات - انگلیسی (حداکثر ۵۱۲ کاراکتر)", "",
                   "برای کاربرانی که زبان تلگرامشان انگلیسی است. خالی = از متن فارسی استفاده می‌شود."),
             "maxlen": 512, "plain": True},
            {**_t("bot_short_desc_fa", "توضیح کوتاه ربات - فارسی (حداکثر ۱۲۰ کاراکتر)", "",
                  "در صفحه‌ی پروفایل ربات و هنگام اشتراک‌گذاری نمایش داده می‌شود."),
             "maxlen": 120},
            {**_t("bot_short_desc_en", "توضیح کوتاه ربات - انگلیسی (حداکثر ۱۲۰ کاراکتر)", "",
                  "خالی = از متن فارسی استفاده می‌شود."),
             "maxlen": 120},
        ],
    },
    {
        "id": "signup_gift", "title": "🎁 هدیه‌ی ثبت‌نام (برای کاربرانی که خرید نکرده‌اند)", "web": True, "mini": True,
        "fields": [
            _b("signup_gift_enabled", "فعال بودن هدیه‌ی ثبت‌نام", "0", "مبلغ هدیه باید بزرگ‌تر از صفر باشد."),
            _n("signup_gift_amount", "مبلغ هدیه (تومان)", "0", min=0),
            _n("signup_gift_delay_days", "چند روز بعد از عضویت (بدون خرید) هدیه داده شود", "3", min=0),
        ],
    },
    {
        "id": "welcome_gift", "title": "🎁 هدیه‌ی کانفیگ عضویت (ارسال سرویس به کاربر تازه‌عضو)", "web": True, "mini": True,
        "fields": [
            _b("welcome_gift_enabled", "فعال بودن هدیه‌ی کانفیگ عضویت", "0", "فقط کاربرانی که بعد از فعال‌سازی عضو شوند هدیه می‌گیرند."),
            _n("welcome_gift_product_id", "شناسه‌ی محصول هدیه (متصل به پنل/نود)", "0", min=0),
            _t("welcome_gift_volume_gb", "حجم هدیه (گیگابایت)", "", "خالی = حجم پیش‌فرض محصول، 0 = نامحدود"),
            _t("welcome_gift_days", "مدت هدیه (روز)", "", "خالی = مدت پیش‌فرض محصول، 0 = نامحدود"),
            _n("welcome_gift_delay_minutes", "ارسال چند دقیقه بعد از عضویت", "0", "0 = بلافاصله (مثلاً 60 = یک ساعت، 1440 = یک روز)", min=0, max=525600),
        ],
    },
    {
        "id": "lottery", "title": "🎰 قرعه‌کشی و سکه", "web": True, "mini": True,
        "fields": [
            _b("score_enabled", "سیستم سکه", "1"),
            _b("lottery_enabled", "قرعه‌کشی", "1"),
            _b("lottery_agent_enabled", "قرعه‌کشی برای نماینده‌ها", "0"),
            _sel("lottery_prize_type", "نوع جایزه", [["wallet", "شارژ کیف پول (تومان)"], ["discount", "کد تخفیف (درصد)"]], "wallet"),
            _t("lottery_prizes", "جایزه‌ی رتبه‌ها (با ویرگول؛ تومان یا درصد)", "50000,30000,20000",
               "رتبه‌ی ۱ تا ۳ به ترتیب، مثلاً 50000,30000,20000"),
            _n("lottery_min_coins", "حداقل سکه برای ورود به قرعه‌کشی", "1", min=0),
            _n("lottery_discount_expiry_hours", "اعتبار کد تخفیف جایزه (ساعت)", "24", min=1),
            _t("lottery_report_chat_id", "آیدی گروه گزارش نتیجه (خالی = پیام خصوصی به ادمین‌ها)", ""),
        ],
    },
    {
        "id": "receipt_ai", "title": "🧾 بررسی هوشمند رسید (AI)", "web": True, "mini": True,
        "fields": [
            _b("receipt_ai_check_enabled", "بررسی رسید با هوش مصنوعی", "1"),
            _b("receipt_ai_auto_reject_enabled", "رد خودکار رسیدهای بسیار مشکوک", "1"),
            _b("receipt_ai_strict_mode", "حالت سخت‌گیرانه", "1"),
            _b("receipt_ai_multi_model_enabled", "بررسی چندمدلی (دقت بالاتر، هزینه‌ی بیشتر)", "1"),
            _n("receipt_ai_reject_weight_threshold", "آستانه‌ی وزنی رد خودکار", "1.5",
               "عدد کمتر = رد سریع‌تر؛ پیش‌فرض ۱.۵", min=0.1, max=10),
        ],
    },
    {
        "id": "backup", "title": "💾 بکاپ خودکار و SFTP", "web": True, "mini": True,
        "fields": [
            _n("backup_interval_hours", "فاصله‌ی بکاپ خودکار (ساعت)", "24", min=1, max=720),
            _t("backup_secondary_chat_id", "آیدی چت دوم برای ارسال نسخه‌ی بکاپ", ""),
            _b("backup_sftp_enabled", "ارسال بکاپ به سرور دوم با SFTP", "0"),
            _t("backup_sftp_host", "هاست SFTP", ""),
            _n("backup_sftp_port", "پورت SFTP", "22", min=1, max=65535),
            _t("backup_sftp_username", "یوزرنیم SFTP", ""),
            _pw("backup_sftp_password", "پسورد SFTP", "خالی = بدون تغییر. اگر از کلید استفاده می‌کنی خالی بگذار."),
            _t("backup_sftp_key_path", "مسیر کلید خصوصی روی سرور (اختیاری)", ""),
            _t("backup_sftp_remote_dir", "پوشه‌ی مقصد روی سرور دوم", "/root/vpn_backups"),
        ],
    },
    {
        "id": "smart_sub", "title": "🔗 اشتراک هوشمند (ادغام کانفیگ‌ها)", "web": True, "mini": True,
        "fields": [
            _b("smart_subscription_enabled", "فعال بودن لینک اشتراک هوشمند", "1"),
            _t("smart_subscription_base_url", "آدرس پایه‌ی لینک (خالی = آدرس API پیش‌فرض)", "",
               "مثلاً https://sub.example.com"),
        ],
    },
    {
        "id": "delivery", "title": "📦 نحوه‌ی تحویل کانفیگ", "web": True, "mini": True,
        "fields": [
            _b("deliver_sub_link_enabled", "ارسال لینک اشتراک (Subscription)", "1"),
            _b("deliver_individual_configs_enabled", "ارسال کانفیگ‌های تکی", "1"),
            _b("deliver_vpn_files_enabled", "ارسال فایل WireGuard/OpenVPN هنگام تحویل (نودها و پنل‌هایی مثل W-UI)", "1"),
            _ta("post_delivery_custom_text", "متن سفارشی بعد از تحویل سرویس (خالی = ندارد)", ""),
            _ta("test_post_delivery_text", "متن سفارشی بعد از تحویل کانفیگ تست (خالی = همان متن عمومی)", ""),
            _t("custom_config_prefix", "پیشوند نام کانفیگ‌های سفارشی", ""),
        ],
    },
    {
        "id": "location", "title": "📍 تغییر لوکیشن سرویس", "web": True, "mini": True,
        "fields": [
            _n("location_change_user_limit", "سقف تغییر لوکیشن برای هر کاربر (۰ = نامحدود)", "0", min=0),
            _n("location_change_free_quota", "تعداد تغییر رایگان (۰ = بدون سهمیه‌ی رایگان)", "0", min=0),
        ],
    },
    {
        "id": "wallet", "title": "👛 کیف پول و کش‌بک", "web": True, "mini": True,
        "fields": [
            _b("wallet_show_transfer", "دکمه‌ی «انتقال موجودی به کاربر دیگر»", "1"),
            _n("topup_cashback_percent", "کش‌بک شارژ کیف پول (٪)", "0", min=0, max=100),
            _n("renewal_cashback_percent", "کش‌بک تمدید سرویس (٪)", "0", min=0, max=100),
        ],
    },
    {
        "id": "alerts", "title": "🔔 هشدار موجودی و کانال سرویس", "web": True, "mini": True,
        "fields": [
            _n("low_stock_threshold", "هشدار موجودی کم — وقتی موجودی محصول به این عدد یا کمتر رسید", "3", min=0),
            _t("service_alert_channel", "کانال اعلان وضعیت سرویس‌ها (مثلاً @channel)", ""),
            _t("support_admin_id", "آیدی ادمین پشتیبان پیش‌فرض (خالی = همه‌ی ادمین‌ها)", ""),
        ],
    },
    {
        "id": "cleanup", "title": "🧹 پاکسازی خودکار سرویس‌ها", "web": True, "mini": True,
        "fields": [
            _n("expired_delete_days", "حذف سرویس منقضی‌شده بعد از N روز (۰ = غیرفعال)", "0", min=0),
            _n("test_delete_days", "حذف سرویس تست بعد از N روز (۰ = غیرفعال)", "0", min=0),
            _n("expired_cleanup_warning_days", "اخطار قبل از حذف (روز)", "3", min=0),
            _b("expired_cleanup_dry_run", "حالت آزمایشی (فقط گزارش می‌دهد، حذف نمی‌کند)", "1",
               "قبل از خاموش کردن، گزارش آزمایشی را بررسی کن."),
            _t("inactive_config_delete_time", "ساعت اجرای حذف کانفیگ‌های غیرفعال (HH:MM، خالی = غیرفعال)", ""),
        ],
    },
    {
        "id": "referral_adv", "title": "🤝 زیرمجموعه‌گیری پیشرفته", "web": True, "mini": True,
        "fields": [
            _b("referral_button_enabled", "نمایش دکمه‌ی زیرمجموعه‌گیری برای کاربران", "1"),
            _b("referral_multilevel_enabled", "پورسانت چندسطحی (سطح ۲ و ۳)", "0"),
            _n("referral_level2_percent", "درصد پورسانت سطح ۲", "3", min=0, max=100),
            _n("referral_level3_percent", "درصد پورسانت سطح ۳", "1", min=0, max=100),
            _n("referral_min_purchase_amount", "حداقل مبلغ خرید برای محاسبه‌ی پورسانت (تومان)", "0", min=0),
            _b("referral_min_purchase_strict", "سخت‌گیرانه (زیر حداقل مبلغ، هیچ پورسانتی ندهد)", "0"),
            _n("referral_renewal_percent", "درصد پورسانت تمدید", "0", min=0, max=100),
            _n("referral_renewal_max_count", "سقف دفعات پورسانت تمدید (۰ = نامحدود)", "0", min=0),
        ],
    },
    {
        "id": "renewal_adv", "title": "🔄 قیمت‌گذاری تمدید و پیشنهاد ریزش", "web": True, "mini": True,
        "fields": [
            _n("renewal_price_per_gb", "قیمت هر گیگ در تمدید حجمی (تومان)", "0", min=0),
            _n("renewal_price_per_day", "قیمت هر روز در تمدید زمانی (تومان)", "0", min=0),
            _n("churn_offer_default_cycle_days", "چرخه‌ی پیش‌فرض خرید برای تحلیل ریزش (روز، حداقل ۷)", "30", min=7),
        ],
    },
    {
        "id": "currency", "title": "💱 ارز، کریپتو و کارت‌به‌کارت", "web": True, "mini": True,
        "fields": [
            _b("card_to_card_enabled", "پرداخت کارت‌به‌کارت", "1"),
            _n("usd_to_toman_rate", "نرخ دستی هر دلار (تومان) — ۰ = نرخ زنده", "0", min=0),
            _n("crypto_expire_min", "مهلت پرداخت کریپتو (دقیقه)", "80", min=5, max=1440),
            _t("crypto_allowed_currencies", "ارزهای مجاز کریپتو (با ویرگول، خالی = همه)", "", "مثلاً USDT_TRX,BTC,TRX"),
        ],
    },
    {
        "id": "provisioning", "title": "🛠 تحویل خودکار، تست و بازگشت وجه", "web": True, "mini": True,
        "fields": [
            _n("auto_provision_max_qty", "سقف تعداد در هر سفارش تحویل خودکار (۰ = بدون سقف)", "0", min=0),
            _n("custom_config_duration_days", "مدت کانفیگ سفارشی (روز)", "30", min=1),
            _n("test_config_panel_volume_gb", "حجم کانفیگ تست پنل (گیگ)", "1", min=0),
            _n("test_config_panel_duration_days", "مدت کانفیگ تست پنل (روز)", "1", min=0),
            _n("svc_refund_window_hours", "مهلت بازگشت وجه هنگام حذف سرویس (ساعت، ۰ = غیرفعال)", "24", min=0),
            _b("reseller_inline_commission_enabled", "کمیسیون نمایندگی در حالت اینلاین", "1"),
            _n("reseller_inline_commission_percent", "درصد کمیسیون پیش‌فرض نماینده‌های قدیمی", "10", min=0, max=100),
            _t("reseller_fixed_product_ids", "شناسه‌ی محصولات ثابت نماینده (با ویرگول)", ""),
        ],
    },
    {
        "id": "system", "title": "⚙️ سیستم و گزارش‌ها", "web": True, "mini": True,
        "fields": [
            _b("daily_report_enabled", "گزارش روزانه برای ادمین", "1"),
            _t("daily_report_time", "ساعت گزارش روزانه (HH:MM)", "23:45"),
            _b("panel_health_enabled", "پایش سلامت پنل‌ها", "1"),
            _b("spam_guard_enabled", "ضداسپم", "1"),
            _t("admin_panel_url", "آدرس عمومی پنل وب (برای لینک‌های داخل بات)", ""),
        ],
    },
    {
        "id": "translation_keys", "title": "🌐 کلید ترجمه‌ی خودکار", "web": True, "mini": True,
        "fields": [
            _pw("translation_gemini_api_key", "کلید(های) Gemini برای ترجمه", "هر خط یا هر ویرگول یک کلید؛ خالی = بدون تغییر"),
            _pw("translation_openrouter_api_key", "کلید(های) OpenRouter برای ترجمه", "خالی = بدون تغییر"),
        ],
    },
    {
        "id": "engagement", "title": "🎮 صندوق شانس و استریک", "web": True, "mini": True,
        "fields": [
            _b("lootbox_enabled", "فعال بودن صندوق شانس", "0"),
            _n("lootbox_daily_limit", "سقف خرید صندوق در روز برای هر کاربر (۰ = نامحدود)", "10", min=0, max=1000),
            _n("lootbox_code_valid_days", "مدت اعتبار کد جایزه‌ی صندوق (روز)", "7", min=1, max=365),
            _b("streak_enabled", "فعال بودن استریک (روز متوالی استفاده)", "0"),
            _n("streak_code_valid_days", "مدت اعتبار کد تخفیف نقاط عطف (روز)", "14", min=1, max=365),
        ],
    },
    {
        "id": "season", "title": "🏆 فصل و رتبه‌بندی", "web": True, "mini": True,
        "fields": [
            _b("season_enabled", "فعال بودن فصل", "0",
               "با روشن شدن، اگر «شروع خودکار ماهانه» روشن باشد و فصل فعالی نباشد، یک فصل جدید شروع می‌شود."),
            _b("season_auto", "شروع خودکار ماهانه", "1"),
            _b("season_announce", "اعلان در کانال", "1"),
            _n("season_invite_points", "امتیاز هر دعوت جدید", "1", min=0, max=100),
            _n("season_purchase_points", "امتیاز اضافه وقتی دعوت‌شده خرید کند", "5", min=0, max=1000),
            _n("season_prize_wallet_1", "جایزه‌ی کیف پول رتبه ۱ (تومان)", "0", min=0, max=1000000000),
            _n("season_prize_wallet_2", "جایزه‌ی کیف پول رتبه ۲ (تومان)", "0", min=0, max=1000000000),
            _n("season_prize_wallet_3", "جایزه‌ی کیف پول رتبه ۳ (تومان)", "0", min=0, max=1000000000),
            _n("season_prize_discount_1", "کد تخفیف رتبه ۱ (درصد)", "0", min=0, max=100),
            _n("season_prize_discount_2", "کد تخفیف رتبه ۲ (درصد)", "0", min=0, max=100),
            _n("season_prize_discount_3", "کد تخفیف رتبه ۳ (درصد)", "0", min=0, max=100),
            _n("season_prize_product_1", "سرویس رایگان رتبه ۱ (شناسه‌ی محصول، ۰ = ندارد)", "0", min=0, max=1000000000),
            _n("season_prize_product_2", "سرویس رایگان رتبه ۲ (شناسه‌ی محصول، ۰ = ندارد)", "0", min=0, max=1000000000),
            _n("season_prize_product_3", "سرویس رایگان رتبه ۳ (شناسه‌ی محصول، ۰ = ندارد)", "0", min=0, max=1000000000),
            _n("season_prize_valid_days", "مدت اعتبار کد تخفیف جایزه (روز)", "30", min=1, max=365),
        ],
    },
    {
        "id": "daily_quiz", "title": "❓ کوییز روزانه", "web": True, "mini": True,
        "fields": [
            _b("quiz_enabled", "فعال بودن کوییز روزانه", "0"),
            _b("quiz_ai_fallback", "ساخت سؤال با AI وقتی بانک سؤال خالی است", "1"),
            _n("quiz_hour", "ساعت انتشار کوییز (به وقت تهران، ۰ تا ۲۳)", "20", min=0, max=23),
            _n("quiz_winner_limit", "تعداد برندگان (نفرات اول درست‌جواب)", "3", min=1, max=50),
            _n("quiz_discount_percent", "درصد کد تخفیف برندگان", "10", min=1, max=100),
            _n("quiz_code_valid_hours", "مدت اعتبار کد تخفیف (ساعت)", "48", min=1, max=720),
            _n("quiz_close_hours", "مدت باز بودن کوییز (ساعت)", "20", min=1, max=23),
        ],
    },
    {
        "id": "gift_cards", "title": "🎁 کارت هدیه", "web": True, "mini": True,
        "fields": [
            _b("gift_enabled", "کارت هدیه فعال باشد", "1"),
            _b("gift_allow_wallet", "هدیه‌ی مبلغ کیف پول", "1"),
            _b("gift_allow_config", "هدیه‌ی کانفیگ", "1"),
            _b("gift_allow_buy", "خرید کانفیگ جدید به‌عنوان هدیه", "1"),
            _n("gift_min_amount", "حداقل مبلغ (تومان)", "10000", min=0, max=1000000000),
            _n("gift_max_amount", "حداکثر مبلغ (تومان)", "5000000", min=0, max=1000000000),
            _n("gift_fee_percent", "کارمزد (درصد)", "0", min=0, max=100),
            _n("gift_expire_days", "مدت اعتبار (روز)", "30", min=1, max=3650),
            _n("gift_max_open", "سقف کارت باز هر کاربر (۰ = نامحدود)", "5", min=0, max=1000000),
        ],
    },
    {
        "id": "post_tools", "title": "🖼 پست‌ساز", "web": True, "mini": True,
        "fields": [
            _b("post_overlay_enabled", "افزودن لایه‌ی برند روی تصویر پست", "1"),
            _b("qr_background_enabled", "استفاده از تصویر پس‌زمینه برای QR", "1",
               "فقط وقتی تصویر آپلود شده باشد اثر دارد؛ تصویر را از همین بخش آپلود کن."),
            _sel("post_image_size", "اندازه‌ی پیش‌فرض تصویر پست",
                 [["post", "پست مربع"], ["portrait", "پست عمودی"], ["story", "استوری"]], "post"),
        ],
    },
    {
        "id": "card_to_card_ui", "title": "💳 ظاهر و دکمه‌های کارت‌به‌کارت", "web": True, "mini": True, "bot": True,
        "fields": [
            _sel("c2c_message_style", "ظاهر پیام اطلاعات واریز",
                 [["pretty", "✨ زیبا (کارت اطلاعات واریز)"], ["classic", "کلاسیک (متن ساده‌ی قبلی)"]], "pretty"),
            _b("c2c_copy_buttons", "نمایش دکمه‌های کپی زیر پیام کارت", "1",
               "با لمس هر دکمه، مقدار در کلیپ‌بورد کاربر کپی می‌شود (حتی وقتی محافظت از پیام روشن است). حذف خودکار پیام کارت از بخش «متفرقه» تنظیم می‌شود."),
            _b("c2c_copy_card", "دکمه‌ی «کپی شماره کارت»", "1"),
            _b("c2c_copy_amount_toman", "دکمه‌ی «کپی مبلغ (تومان)»", "1"),
            _b("c2c_copy_amount_rial", "دکمه‌ی «کپی مبلغ (ریال)»", "1"),
            _b("c2c_copy_holder", "دکمه‌ی «کپی نام صاحب کارت»", "0"),
            _sel("c2c_copy_btn_style", "رنگ دکمه‌های کپی",
                 [["default", "پیش‌فرض"], ["primary", "🔵 آبی"], ["success", "🟢 سبز"], ["danger", "🔴 قرمز"]], "default"),
            _b("c2c_protect_card", "محافظت از شماره کارت", "0",
               "پیام کارت قابل انتخاب/کپی متن، فوروارد و (روی موبایل) اسکرین‌شات نمی‌شود؛ کاربر فقط با دکمه‌های کپی می‌تواند کپی کند."),
            _b("c2c_show_bank", "نمایش نام بانک در پیام", "1"),
            _b("c2c_back_to_wallet", "دکمه‌ی «بازگشت به کیف پول» در پرداخت شارژ کیف پول", "1"),
        ],
    },
    {
        "id": "misc_admin", "title": "🧩 متفرقه", "web": True, "mini": True,
        "fields": [
            _n("card_msg_autodelete_seconds", "حذف خودکار پیام شماره کارت پس از (ثانیه، ۰ = غیرفعال)", "0", min=0, max=86400),
            _n("broadcast_inactive_purchase_days", "پیش‌فرض «بدون خرید در N روز» برای پیام همگانی", "30", min=1, max=3650),
            _t("promo_channel_id", "کانال تبلیغاتی/کمپین (@یوزرنیم یا آیدی عددی)", "",
               "مقصد پست‌های کمپین، کوییز و فصل"),
            _pwm("jarvis_api_key", "کلید(های) Jarvis برای ساخت محتوای کانال", _AI_KEY_HINT),
            _b("reseller_request_enabled", "امکان ثبت درخواست نمایندگی توسط کاربر", "1"),
            _n("discount_order_expiry_minutes", "مهلت لغو خودکار سفارش کارت‌به‌کارت با کد تخفیف اگر رسید نیاید (دقیقه، ۰ = غیرفعال)", "60", min=0, max=10080),
        ],
    },
    {
        "id": "service_buttons_extra", "title": "🔘 دکمه‌های صفحه‌ی سرویس (تکمیلی)", "web": True, "mini": True,
        "fields": [
            _b("svc_show_inquiry", "نمایش دکمه‌ی استعلام", "1"),
            _b("svc_show_location_transfer", "نمایش دکمه‌ی انتقال لوکیشن", "1"),
        ],
    },
    # ----- مرحله ۲: خلأهای مینی‌اپ (پنل وب این‌ها را در تب‌های خودش دارد) -----
    {
        "id": "acct_svc_buttons_mini", "title": "🧾 نمایش دکمه‌های حساب، سرویس و کیف پول", "web": False, "mini": True,
        "fields": _toggle_fields(exclude=_SVC_EXTRA_KEYS),
    },
    {
        "id": "acct_svc_buttons_web", "title": "🧾 دکمه‌های حساب/سرویس/کیف پول (تکمیلی)", "web": True, "mini": False,
        "fields": _toggle_fields(only=_WEB_MISSING_TOGGLES),
    },
    {
        "id": "main_menu", "title": "🧩 منوی اصلی بات", "web": False, "mini": True,
        "fields": [
            _b("main_menu_reply_enabled", "منوی پایین (کیبورد)", "1"),
            _b("main_menu_inline_enabled", "منوی شیشه‌ای بالای پیام", "0",
               "حداقل یکی از دو منو باید روشن بماند."),
            _sel("main_menu_columns", "تعداد ستون منو (فقط برای نصب‌های قدیمی بدون چیدمان آزاد)",
                 [["1", "۱ ستون"], ["2", "۲ ستون"]], "1"),
        ],
    },
    {
        "id": "welcome", "title": "👋 متن خوش‌آمدگویی", "web": False, "mini": True,
        "fields": [
            {**_ta("welcome_text", "متن خوش‌آمدگویی (شروع بات)", _default_setting("welcome_text"),
                   "از تگ‌های HTML تلگرام مثل <b> و <i> و <a href> پشتیبانی می‌شود."), "maxlen": 4000},
        ],
    },
    {
        "id": "spam_limits", "title": "🛡 محدودیت ضداسپم", "web": False, "mini": True,
        "fields": [
            _n("spam_limit", "حداکثر درخواست مجاز در هر بازه", "35", "تعداد پیام و دکمه‌ای که یک کاربر می‌تواند بفرستد.", min=5, max=500),
            _n("spam_window", "بازه‌ی زمانی (ثانیه)", "60", min=10, max=600),
        ],
    },
    {
        "id": "reminder_discount_codes", "title": "🎟 ارسال کد تخفیف در یادآوری‌ها", "web": False, "mini": True,
        "fields": [
            _b("renewal_send_discount_code", "ارسال کد تخفیف همراه یادآوری تمدید", "1"),
            _b("volume_send_discount_code", "ارسال کد تخفیف همراه یادآوری حجم", "1"),
        ],
    },
    {
        "id": "dsub_basic", "title": "🔗 اشتراک اختصاصی (صفحه‌ی لینک ساب)", "web": False, "mini": True,
        "fields": [
            _b("dsub_enabled", "فعال بودن اشتراک اختصاصی", "0"),
            _t("dsub_brand", "نام برند صفحه (خالی = نام فروشگاه)", ""),
            _t("dsub_logo_url", "لوگوی صفحه (آدرس https)", ""),
            _ta("dsub_notice", "اعلان بالای صفحه", ""),
            _t("dsub_support_url", "لینک پشتیبانی (t.me/... یا https://...)", ""),
            _t("dsub_footer_text", "متن پایین صفحه", ""),
            _sel("dsub_theme", "تم صفحه", [["auto", "خودکار"], ["light", "روشن"], ["dark", "تیره"]], "auto"),
            _b("dsub_show_configs", "نمایش کانفیگ‌ها", "1"),
            _b("dsub_show_chart", "نمایش نمودار مصرف", "1"),
            _b("dsub_show_qr", "نمایش QR", "1"),
            _b("dsub_show_apps", "نمایش برنامه‌ها", "1"),
            _b("dsub_show_faq", "نمایش بخش عیب‌یابی", "1"),
        ],
    },
    {
        "id": "dsub_apps", "title": "📱 اشتراک اختصاصی: برنامه‌ها و سوالات متداول", "web": True, "mini": True,
        "fields": [
            {**_ta("dsub_faq", "سوالات متداول (هر خط: «سوال | جواب»، حداکثر ۱۰ مورد؛ خالی = پیش‌فرض)", ""), "maxlen": 3000},
            {**_ta("dsub_custom_apps", "برنامه‌های سفارشی (هر خط: سیستم‌عامل|نام|توضیح|پیشوند افزودن|لینک دانلود)", "",
                   "سیستم‌عامل یکی از ios, android, windows, mac, linux است. برای نداشتن پیشوند یا لینک بنویس - . حداکثر ۴۰ خط."),
             "maxlen": 8000},
            _t("dsub_apps_hidden", "برنامه‌های مخفی‌شده (مثل ios:Streisand,android:v2rayNG)", ""),
            _t("dsub_apps_rec", "برنامه‌ی پیشنهادی هر سیستم‌عامل (مثل ios:Hiddify,android:v2rayNG)", ""),
        ],
    },
    # ----- مرحله ۵: تنظیمات دستیار هوش مصنوعی (قبلاً فقط ربات و فرم‌های اپ اندروید) -----
    {
        "id": "ai_general", "title": "🤖 دستیار هوش مصنوعی: عمومی", "web": True, "mini": True, "bot": True,
        "fields": [
            _b("ai_support_enabled", "فعال بودن دستیار هوشمند پشتیبانی", "1"),
            _b("ai_stream_enabled", "پاسخ تدریجی (stream) دستیار هوش مصنوعی", "1"),
            _sel("ai_provider", "مسیر انتخاب مدل", _AI_PROVIDER_OPTIONS, "auto"),
        ],
    },
    {
        "id": "ai_buy_guide", "title": "🛒 دستیار هوشمند خرید", "web": True, "mini": True, "bot": True,
        "bot_back": "adm_ai_agents", "bot_hidden_in_list": True,
        "fields": [
            _b("buy_guide_enabled", "فعال بودن دستیار هوشمند خرید (دکمه‌ی «راهنمای خرید» در مسیر خرید)", "1"),
            {**_ta("buy_guide_questions",
                   "سوال‌های راهنمای خرید (هر خط یک سوال: «عنوان | متن سوال | گزینه۱ ; گزینه۲ ; ...»)",
                   _default_setting("buy_guide_questions"),
                   "حداکثر ۸ سوال و هر سوال ۲ تا ۸ گزینه (جداشده با ;). عنوان در خلاصه‌ی جواب‌ها به AI داده می‌شود. "
                   "خالی = سوال‌های پیش‌فرض."),
             "maxlen": 3000, "plain": True},
            {**_ta("buy_guide_prompt",
                   "دستورالعمل AI در راهنمای خرید (سبک پیشنهاد و لحن)",
                   _default_setting("buy_guide_prompt"),
                   "قوانین ایمنی (فقط محصولات واقعی از list_products، پنهان‌ماندن توضیح داخلی محصول، موجودی، کارت خرید) "
                   "ثابت‌اند و با ویرایش این متن حذف نمی‌شوند. خالی = متن پیش‌فرض."),
             "maxlen": 3000, "plain": True},
        ],
    },
    {
        "id": "ai_providers", "title": "🔑 دستیار هوش مصنوعی: ارائه‌دهنده‌ها", "web": True, "mini": True,
        "fields": [
            _pwm("gemini_api_key", "کلید(های) Gemini", _AI_KEY_HINT),
            _t("gemini_model", "مدل Gemini", "", _AI_MODEL_HINT),
            _pwm("groq_api_key", "کلید(های) Groq", _AI_KEY_HINT),
            _t("groq_model", "مدل Groq", "", _AI_MODEL_HINT),
            _pwm("openrouter_api_key", "کلید(های) OpenRouter", _AI_KEY_HINT),
            _t("openrouter_model", "مدل OpenRouter", "", _AI_MODEL_HINT),
            _pwm("openai_api_key", "کلید(های) OpenAI", _AI_KEY_HINT),
            _t("openai_model", "مدل OpenAI", "", _AI_MODEL_HINT),
            _pwm("anthropic_api_key", "کلید(های) Claude (Anthropic)", _AI_KEY_HINT),
            _t("anthropic_model", "مدل Claude", "", _AI_MODEL_HINT),
        ],
    },
    {
        "id": "ai_extra_agents", "title": "🧾 دستیار هوش مصنوعی: ایجنت‌های اضافی تشخیص رسید", "web": True, "mini": True,
        "fields": [
            _pwm("mistral_api_key", "کلید(های) Mistral", _AI_KEY_HINT),
            _pwm("cohere_api_key", "کلید(های) Cohere", _AI_KEY_HINT),
            _pwm("cloudflare_api_token", "توکن Cloudflare Workers AI", _AI_KEY_HINT),
            _t("cloudflare_account_id", "Account ID کلودفلر", ""),
            _t("cloudflare_model", "مدل Workers AI (مثل @cf/...)", "", "باید با @cf/ یا @hf/ شروع شود."),
        ],
    },
    {
        "id": "dsub_enable_web", "title": "🔗 اشتراک اختصاصی: روشن/خاموش", "web": True, "mini": False,
        "fields": [
            _b("dsub_enabled", "فعال بودن اشتراک اختصاصی", "0",
               "برای محصول چندپنلی/چندنودی لازم است. تنظیم برند و ظاهر صفحه در تنظیمات برندینگ است."),
        ],
    },
    {
        "id": "ticket_list_web", "title": "🎫 جستجو و ترتیب لیست تیکت‌ها و چت زنده", "web": True, "mini": False,
        "fields": [
            _sel("tickets_default_sort", "ترتیب پیش‌فرض لیست تیکت‌ها", [
                ["updated_desc", "آخرین بروزرسانی (جدیدترین اول)"],
                ["updated_asc", "آخرین بروزرسانی (قدیمی‌ترین اول)"],
                ["created_desc", "تاریخ ایجاد (جدیدترین اول)"],
                ["created_asc", "تاریخ ایجاد (قدیمی‌ترین اول)"],
                ["priority_desc", "اولویت (زیاد به کم)"],
                ["priority_asc", "اولویت (کم به زیاد)"],
                ["unread_first", "خوانده‌نشده‌ها اول"],
                ["messages_desc", "بیشترین تعداد پیام"],
            ], "updated_desc", "فقط ترتیب نمایش در پنل وب؛ ادمین می‌تواند هر بار از نوار بالای لیست ترتیب دیگری انتخاب کند."),
            _sel("support_default_sort", "ترتیب پیش‌فرض لیست چت زنده", [
                ["last_desc", "آخرین پیام (جدیدترین اول)"],
                ["last_asc", "آخرین پیام (قدیمی‌ترین اول)"],
                ["unread_first", "خوانده‌نشده‌ها اول"],
                ["priority_desc", "اولویت (زیاد به کم)"],
                ["priority_asc", "اولویت (کم به زیاد)"],
                ["messages_desc", "بیشترین تعداد پیام"],
                ["name", "نام کاربر (الفبایی)"],
            ], "last_desc", "فقط ترتیب نمایش در پنل وب؛ ادمین می‌تواند هر بار از نوار بالای لیست ترتیب دیگری انتخاب کند."),
            _b("ticket_search_in_messages", "جستجو در متن پیام‌ها (تیکت و چت زنده)", "1",
               "روشن: علاوه بر نام‌کاربری، نام، آیدی، موضوع و سرویس، متن گفتگوها هم جستجو می‌شود. با تعداد زیاد پیام می‌توانید خاموشش کنید تا جستجو سریع‌تر شود."),
        ],
    },
    {
        "id": "free_test", "title": "🧪 کانفیگ تست رایگان", "web": False, "mini": True, "bot": True,
        "fields": [
            _b("test_enabled", "فعال بودن کانفیگ تست رایگان", "1",
               "پلن‌های تست از تب «پنل‌های VPN» مدیریت می‌شوند؛ این فقط کلید روشن/خاموش کل قابلیت است."),
            _n("test_max_per_user", "تعداد مجاز کانفیگ تست برای هر کاربر", "1", "سهمیه‌ی پیش‌فرض کاربران؛ برای کاربر خاص می‌توان مقدار جداگانه تعیین کرد.", min=0, max=1000),
        ],
    },
    # ----- مرحله ۴: تنظیماتی که فقط پنل وب داشت؛ حالا برای مینی‌اپ و ادمین بات هم (surface = bot) -----
    {
        "id": "support_texts", "title": "💬 متن‌های پشتیبانی و پرداخت", "web": False, "mini": True, "bot": True,
        "fields": [
            {**_ta("contact_text", "متن «ارتباط با پشتیبانی»", _default_setting("contact_text"),
                   "قبل از ارسال پیام کاربر به پشتیبانی نشان داده می‌شود."), "maxlen": 4000},
            {**_ta("after_buy_text", "متن راهنمای پرداخت کارت‌به‌کارت", _default_setting("after_buy_text"),
                   "بالای شماره کارت نشان داده می‌شود."), "maxlen": 4000},
        ],
    },
    {
        "id": "parity_extra", "title": "🧩 گزینه‌های تکمیلی", "web": False, "mini": True, "bot": True,
        "fields": [
            _b("bank_inquiry_auto_reject", "رد خودکار رسید وقتی مقصد طبق استعلام قطعاً اشتباه است (خاموش = فقط هشدار)", "0"),
            _n("manual_usd_rate_toman", "نرخ دلار دستی (فقط اگر منابع زنده شکست بخورند؛ ۰ = غیرفعال)", "0", min=0, max=100000000),
        ],
    },
    # فقط مینی‌اپ: در پنل وب این‌ها فرم اختصاصی دارند.
    {
        "id": "churn", "title": "📉 پیشنهاد هوشمند ضدریزش", "web": False, "mini": True,
        "fields": [
            _b("churn_offer_enabled", "فعال بودن", "0"),
            _b("churn_offer_ai_enabled", "تصمیم‌گیری با AI", "1"),
            _n("churn_offer_min_score", "حداقل امتیاز ریزش (۱ تا ۱۰۰)", "60", min=1, max=100),
            _n("churn_offer_discount_percent", "درصد تخفیف پایه", "15", min=0, max=100),
            _n("churn_offer_max_discount_percent", "سقف درصد تخفیف", "25", min=0, max=100),
            _n("churn_offer_expiry_hours", "اعتبار کد (ساعت)", "72", min=1),
            _n("churn_offer_cooldown_days", "فاصله بین دو پیشنهاد به یک کاربر (روز)", "30", min=1),
            _n("churn_offer_max_per_run", "سقف پیشنهاد در هر اجرا", "20", min=1),
        ],
    },
    {
        "id": "force_join", "title": "📢 عضویت اجباری در کانال", "web": False, "mini": True,
        "fields": [
            _b("force_join_enabled", "عضویت اجباری", "0"),
            _ta("force_join_channel", "آیدی کانال‌ها (هر کانال در یک خط، مثلاً @mychannel؛ تعداد نامحدود)", ""),
        ],
    },
    # تنظیمات پرداخت کریپتو در پنل وب فرم اختصاصی دارد؛ این فیلد فقط
    # برای تکمیل فرم مینی‌اپ اضافه شده و عمداً در منوی ادمین بات نیست.
    {
        "id": "crypto_payment_toggle_mini", "title": "🪙 پرداخت کریپتو", "web": False, "mini": True,
        "fields": [
            _b("crypto_payment_enabled", "فعال بودن پرداخت کریپتو", "0"),
        ],
    },
    # این دو تنظیم در پنل وب فرم اختصاصی دارند؛ مینی‌اپ و ادمین بات نیز
    # باید بتوانند همان مقادیر را از جدول settings مدیریت کنند.
    {
        "id": "report_and_server_monitoring", "title": "📡 گزارش‌ها و پایش سرورها",
        "web": False, "mini": True, "bot": True,
        "fields": [
            _t("report_chat_id", "آیدی عددی گروه گزارش (خالی = پیام خصوصی مدیران)", ""),
            _n("server_check_interval_min", "فاصله‌ی بررسی وضعیت سرورها (دقیقه)", "3",
               "محدوده‌ی مجاز: ۱ تا ۱۲۰ دقیقه.", min=1, max=120),
            _n("server_offline_streak", "تعداد بررسی متوالی برای اعلام قطعی", "2",
               "محدوده‌ی مجاز: ۱ تا ۱۰ بار.", min=1, max=10),
        ],
    },
    {
        "id": "referral_fraud", "title": "🕵️ تشخیص تقلب در زیرمجموعه‌گیری", "web": False, "mini": True,
        "fields": [
            _b("referral_fraud_detection_enabled", "تشخیص فعال", "1"),
            _n("referral_fraud_burst_count", "تعداد زیرمجموعه‌ی تازه که یعنی دعوت انبوه", "5", min=1),
            _n("referral_fraud_burst_minutes", "بازه‌ی بررسی (دقیقه)", "60", min=1),
            _n("referral_fraud_min_invites", "حداقل دعوت برای معیار نرخ بی‌خریدی", "5", min=1),
            _n("referral_fraud_zero_purchase_ratio", "درصد زیرمجموعه‌ی بی‌خرید مشکوک", "80", min=1, max=100),
            _b("referral_fraud_auto_suspend", "توقف خودکار پاداش در صورت مشکوک بودن", "1"),
        ],
    },
]
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

# ----------------------------------------------------------------------------‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

_FIELD_INDEX: Dict[str, Dict[str, Any]] = {
    f["key"]: f for g in EXTRA_SETTINGS_GROUPS for f in g["fields"]
}


def groups_for(surface: str) -> List[Dict[str, Any]]:
    """surface: 'web'، 'mini' یا 'bot' (ادمین بات؛ فقط گروه‌هایی که "bot": True دارند)"""
    return [g for g in EXTRA_SETTINGS_GROUPS if g.get(surface)]


def allowed_keys(surface: str) -> set:
    return {f["key"] for g in groups_for(surface) for f in g["fields"]}


def load_values(db, surface: str) -> Dict[str, Any]:
    """فرم‌ها را پر می‌کند. مقدار فیلد password هرگز برنمی‌گردد (فقط وضعیت set/unset)."""
    out: Dict[str, Any] = {}
    for g in groups_for(surface):
        for f in g["fields"]:
            raw = db.get_setting(f["key"], f["default"])
            raw = f["default"] if raw is None else str(raw)
            if f["type"] == "password":
                out[f["key"]] = SECRET_MASK if raw.strip() else ""
            elif f["type"] == "bool":
                out[f["key"]] = "1" if raw.strip() == "1" else "0"
            else:
                out[f["key"]] = raw
    return out


class SettingsValidationError(ValueError):
    pass


def _clean(field: Dict[str, Any], value: Any) -> Optional[str]:
    """مقدار را اعتبارسنجی/نرمال می‌کند. None یعنی «دست نزن» (برای password خالی)."""
    t = field["type"]
    if value is None:
        value = ""
    if isinstance(value, bool):
        value = "1" if value else "0"
    value = str(value)
    label = field["label"]
    if t == "password":
        value = value.strip()
        if value == "" or value == SECRET_MASK:
            return None
        if field.get("multikey"):
            keys, seen = [], set()
            for part in value.replace(",", "\n").splitlines():
                part = part.strip()
                if part and part not in seen:
                    seen.add(part)
                    keys.append(part)
            return "\n".join(keys) if keys else None
        return value
    if t == "bool":
        if value.strip() not in ("0", "1", "true", "false", "True", "False"):
            raise SettingsValidationError(f"مقدار «{label}» نامعتبر است.")
        return "1" if value.strip() in ("1", "true", "True") else "0"
    if t == "number":
        v = value.strip()
        if v == "":
            return str(field["default"])
        try:
            num = float(v.replace(",", ""))
        except ValueError:
            raise SettingsValidationError(f"«{label}» باید عدد باشد.")
        if num != num or num in (float("inf"), float("-inf")):
            raise SettingsValidationError(f"«{label}» نامعتبر است.")
        if "min" in field and num < field["min"]:
            raise SettingsValidationError(f"«{label}» نباید کمتر از {field['min']} باشد.")
        if "max" in field and num > field["max"]:
            raise SettingsValidationError(f"«{label}» نباید بیشتر از {field['max']} باشد.")
        return str(int(num)) if num == int(num) and "." not in str(field["default"]) else str(num)
    if t == "select":
        allowed = {o[0] for o in field.get("options", [])}
        if value not in allowed:
            raise SettingsValidationError(f"«{label}» نامعتبر است.")
        return value
    # text / textarea‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    value = value.strip() if t == "text" else value.strip("\r\n ")
    if len(value) > int(field.get("maxlen", 8000)):
        raise SettingsValidationError(f"«{label}» بیش از حد طولانی است (حداکثر {field.get('maxlen', 8000)} کاراکتر).")
    return value


def _cross_check(values: Dict[str, str], db) -> None:
    """قواعد بین‌فیلدی که بات هم همان‌ها را اعمال می‌کند."""
    def cur(key):
        if key in values:
            return values[key]
        f = _FIELD_INDEX[key]
        v = db.get_setting(key, f["default"])
        return f["default"] if v is None else str(v)

    if "terms_enabled" in values or "terms_text" in values:
        if cur("terms_enabled") == "1" and not cur("terms_text").strip():
            raise SettingsValidationError("برای فعال‌سازی قوانین، متن قوانین نمی‌تواند خالی باشد.")
    if "signup_gift_enabled" in values or "signup_gift_amount" in values:
        if cur("signup_gift_enabled") == "1" and float(cur("signup_gift_amount") or 0) <= 0:
            raise SettingsValidationError("برای فعال‌سازی هدیه‌ی ثبت‌نام، مبلغ باید بزرگ‌تر از صفر باشد.")
    if "welcome_gift_enabled" in values or "welcome_gift_product_id" in values:
        if cur("welcome_gift_enabled") == "1" and int(float(cur("welcome_gift_product_id") or 0)) <= 0:
            raise SettingsValidationError("برای فعال‌سازی هدیه‌ی کانفیگ عضویت، شناسه‌ی محصول را وارد کنید.")
    for _key in ("welcome_gift_volume_gb", "welcome_gift_days"):
        if _key in values:
            _val = str(values[_key]).strip()
            if _val:
                try:
                    if float(_val) < 0:
                        raise ValueError
                except ValueError:
                    raise SettingsValidationError("حجم و مدت هدیه باید عدد صفر یا بزرگ‌تر باشند (یا خالی).")
    if "deliver_sub_link_enabled" in values or "deliver_individual_configs_enabled" in values:
        if cur("deliver_sub_link_enabled") == "0" and cur("deliver_individual_configs_enabled") == "0":
            raise SettingsValidationError("حداقل یکی از «لینک اشتراک» یا «کانفیگ تکی» باید فعال بماند.")
    if "backup_sftp_enabled" in values or "backup_sftp_host" in values:
        if cur("backup_sftp_enabled") == "1" and not cur("backup_sftp_host").strip():
            raise SettingsValidationError("برای فعال‌سازی SFTP، هاست الزامی است.")
    if "force_join_enabled" in values or "force_join_channel" in values:
        if cur("force_join_enabled") == "1" and not cur("force_join_channel").strip():
            raise SettingsValidationError("برای فعال‌سازی عضویت اجباری، آیدی کانال الزامی است.")
    if "lottery_prizes" in values:
        parts = [p.strip() for p in values["lottery_prizes"].split(",") if p.strip()]
        if not parts or not all(p.isdigit() and int(p) > 0 for p in parts):
            raise SettingsValidationError("جایزه‌ی رتبه‌ها باید اعداد مثبتِ جداشده با ویرگول باشد.")
        values["lottery_prizes"] = ",".join(str(int(p)) for p in parts)
    if "lottery_prize_type" in values or "lottery_prizes" in values:
        if cur("lottery_prize_type") == "discount":
            if any(int(p) > 100 for p in cur("lottery_prizes").split(",") if p.strip().isdigit()):
                raise SettingsValidationError("در حالت «کد تخفیف» جایزه‌ها درصد هستند و نباید از ۱۰۰ بیشتر باشند.")
    if "churn_offer_discount_percent" in values or "churn_offer_max_discount_percent" in values:
        if float(cur("churn_offer_discount_percent")) > float(cur("churn_offer_max_discount_percent")):
            raise SettingsValidationError("درصد تخفیف پایه نمی‌تواند از سقف تخفیف بیشتر باشد.")
    if any(k in values for k in ("dsub_faq", "dsub_custom_apps", "dsub_apps_hidden", "dsub_apps_rec")):
        import dedicated_sub as _ds
        if values.get("dsub_faq", "").strip():
            items = _ds.parse_faq(values["dsub_faq"])
            if not items:
                raise SettingsValidationError("هر خط سوالات متداول باید به شکل «سوال | جواب» باشد.")
            if len(items) > 10:
                raise SettingsValidationError("حداکثر ۱۰ سوال متداول مجاز است.")
            values["dsub_faq"] = "\n".join(f"{q} | {a}" for q, a in items)
        if values.get("dsub_custom_apps", "").strip():
            apps, errors = _ds.parse_custom_apps(values["dsub_custom_apps"])
            if errors:
                raise SettingsValidationError("؛ ".join(errors[:3]))
            if len([ln for ln in values["dsub_custom_apps"].splitlines() if ln.strip()]) > 40:
                raise SettingsValidationError("حداکثر ۴۰ برنامه‌ی سفارشی مجاز است.")
        for k in ("dsub_apps_hidden", "dsub_apps_rec"):
            if k not in values or not values[k].strip():
                continue
            pairs = set()
            for part in values[k].replace("\n", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                plat, _, name = part.partition(":")
                plat, name = plat.strip().lower(), name.strip()
                if plat not in _ds.PLATFORMS or not name:
                    raise SettingsValidationError(
                        f"«{part}» نامعتبر است؛ قالب درست «سیستم‌عامل:نام برنامه» با سیستم‌عامل یکی از "
                        f"{', '.join(_ds.PLATFORMS)} است.")
                known = {n.lower() for n in _ds.all_app_names({"dsub_custom_apps": cur("dsub_custom_apps")}, plat)}
                if name.lower() not in known:
                    raise SettingsValidationError(f"برنامه‌ی «{name}» برای {plat} وجود ندارد.")
                pairs.add((plat, name.lower()))
            if k == "dsub_apps_rec":
                plats = [p for p, _ in pairs]
                if len(plats) != len(set(plats)):
                    raise SettingsValidationError("برای هر سیستم‌عامل فقط یک برنامه‌ی پیشنهادی مجاز است.")
            values[k] = ",".join(f"{p}:{n}" for p, n in sorted(pairs))
    for k in _AI_MODEL_KEYS:
        v = values.get(k, "")
        if not v:
            continue
        if len(v) > 120 or any(ch.isspace() for ch in v):
            raise SettingsValidationError("نام مدل نباید فاصله داشته باشد و باید حداکثر ۱۲۰ نویسه باشد.")
        if k == "cloudflare_model" and not v.startswith(("@cf/", "@hf/")):
            raise SettingsValidationError("نام مدل Workers AI نامعتبر است (باید با @cf/ یا @hf/ شروع شود).")
    if values.get("buy_guide_questions", "").strip():
        import buy_guide as _bg
        _qs, _qerrors = _bg.parse_questions(values["buy_guide_questions"])
        if _qerrors:
            raise SettingsValidationError("؛ ".join(_qerrors[:3]))
        values["buy_guide_questions"] = _bg.serialize_questions(_qs)
    if "main_menu_reply_enabled" in values or "main_menu_inline_enabled" in values:
        if cur("main_menu_reply_enabled") != "1" and cur("main_menu_inline_enabled") != "1":
            raise SettingsValidationError("حداقل یکی از «منوی پایین» یا «منوی شیشه‌ای» باید روشن بماند.")
    if "gift_min_amount" in values or "gift_max_amount" in values:
        lo, hi = int(float(cur("gift_min_amount") or 0)), int(float(cur("gift_max_amount") or 0))
        if hi and lo > hi:
            raise SettingsValidationError("حداقل مبلغ کارت هدیه نمی‌تواند از حداکثر بیشتر باشد.")
    for k in ("inactive_config_delete_time", "daily_report_time"):
        if k in values and values[k]:
            import re
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", values[k]):
                raise SettingsValidationError("ساعت باید با قالب HH:MM باشد (مثلاً 23:45).")
    if "reseller_fixed_product_ids" in values and values["reseller_fixed_product_ids"]:
        if not all(p.strip().isdigit() for p in values["reseller_fixed_product_ids"].split(",") if p.strip()):
            raise SettingsValidationError("شناسه‌ی محصولات باید عدد و با ویرگول جدا شده باشند.")
    if values.get("force_join_channel"):
        from force_join_channels import parse_channels, serialize_channels, invalid_entries
        if invalid_entries(values["force_join_channel"]):
            raise SettingsValidationError("آیدی کانال باید با @ شروع شود (یا آیدی عددی باشد).")
        _fj = parse_channels(values["force_join_channel"])
        values["force_join_channel"] = serialize_channels(_fj)
    for k in ("service_alert_channel", "promo_channel_id"):
        if k in values and values[k] and not (values[k].startswith("@") or values[k].lstrip("-").isdigit()
                                                or values[k].startswith("https://t.me/")):
            raise SettingsValidationError("آیدی کانال باید با @ شروع شود (یا آیدی عددی باشد).")
    for k in ("backup_secondary_chat_id", "lottery_report_chat_id", "support_admin_id", "report_chat_id"):
        if k in values and values[k] and not values[k].lstrip("-").isdigit():
            raise SettingsValidationError("این آیدی باید عددی باشد.")


def save_values(db, surface: str, payload: Dict[str, Any]) -> List[str]:
    """
    payload = {key: value}. فقط کلیدهای مجازِ همان سطح پذیرفته می‌شوند. همه‌چیز
    اول اعتبارسنجی می‌شود و بعد نوشته می‌شود (یا همه یا هیچ). لیست کلیدهای تغییرکرده را برمی‌گرداند.
    """
    allowed = allowed_keys(surface)
    cleaned: Dict[str, str] = {}
    for key, raw in (payload or {}).items():
        if key not in allowed:
            raise SettingsValidationError(f"کلید ناشناخته: {key}")
        v = _clean(_FIELD_INDEX[key], raw)
        if v is not None:
            cleaned[key] = v
    _cross_check(cleaned, db)
    changed = []
    for key, v in cleaned.items():
        old = db.get_setting(key, None)
        if old is None or str(old) != v:
            db.set_setting(key, v)
            changed.append(key)
    # همان اثر جانبی که ثبت متن قوانین از داخل بات دارد: زمان آخرین ویرایش (برای پذیرش مجدد)
    # همان اثر جانبی روشن‌کردن فصل از داخل بات: اگر شروع خودکار روشن است و فصل فعالی نیست، فصل جدید شروع شود
    if "season_enabled" in changed and cleaned.get("season_enabled") == "1":
        try:
            import seasons
            if seasons.auto_renew(db) and not db.season_get_active():
                seasons.start_season(db)
        except Exception:
            import logging
            logging.getLogger("extra_settings").exception("season auto start failed")
    if "terms_text" in changed:
        from datetime import datetime
        db.set_setting("terms_updated_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    return changed
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
