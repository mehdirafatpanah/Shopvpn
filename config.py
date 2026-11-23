# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
تنظیمات اصلی بات

نکته مهم: مقادیر حساس (توکن، آیدی ادمین) از فایل .env خوانده می‌شوند و
داخل این فایل هاردکد نیستند تا در صورت آپلود پروژه روی گیت‌هاب لو نروند.
اگر فایل .env وجود نداشته باشد، این فایل با خطا متوقف می‌شود تا از اجرای
تصادفی بدون تنظیمات درست جلوگیری شود.
"""

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID_RAW = os.getenv("OWNER_ID")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN تنظیم نشده است. یک فایل .env در کنار main.py بساز و مقدار "
        "BOT_TOKEN=توکن_بات_تو را داخلش قرار بده (نمونه در .env.example موجود است)."
    )

if not OWNER_ID_RAW or not OWNER_ID_RAW.strip().lstrip("-").isdigit():
    raise RuntimeError(
        "OWNER_ID تنظیم نشده یا عدد معتبر نیست. داخل فایل .env مقدار "
        "OWNER_ID=آیدی_عددی_تو را قرار بده."
    )

OWNER_ID = int(OWNER_ID_RAW)

# پوشه‌ی ریشه‌ی پروژه (مطلق) - برای اینکه مسیر دیتابیس‌ها به cwd پروسه‌ای که
# main.py یا uvicorn (مینی‌اپ) با آن اجرا می‌شوند وابسته نباشد و همیشه یکی باشد
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# مسیر فایل دیتابیس بات اصلی
DB_PATH = os.path.join(BASE_DIR, "bot_database.db")

# پوشه‌ای که دیتابیس هر بات نمایندگی داخلش ذخیره می‌شود
RESELLER_DBS_DIR = os.path.join(BASE_DIR, "reseller_dbs")


def resolve_db_path(path: str) -> str:
    """مسیر دیتابیس را به مسیر مطلق نسبت به پروژه تبدیل می‌کند."""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def resolve_reseller_db_path(path: str, *, relocate_missing: bool = True) -> str:
    """مسیر دیتابیس نماینده را پس از انتقال سرور به مسیر محلی استاندارد برساند.

    اگر مسیر مطلقِ سرور قبلی دیگر وجود نداشته باشد، نام فایل را در پوشه
    reseller_dbs همین نصب جست‌وجو/بازسازی می‌کند؛ مسیرهای موجود را دست نمی‌زند.
    """
    if not path:
        return path
    resolved = resolve_db_path(path)
    if os.path.exists(resolved) or not relocate_missing:
        return resolved
    filename = os.path.basename(os.path.normpath(path))
    if not filename or filename in ('.', '..'):
        return resolved
    local_path = os.path.join(RESELLER_DBS_DIR, filename)
    # مسیر نماینده همیشه باید به پوشه‌ی استاندارد این نصب اشاره کند؛ حتی اگر
    # فایل هنوز وجود نداشته باشد (در این حالت start_bot آن را ایجاد نمی‌کند).
    return local_path

# حالت دریافت آپدیت‌های تلگرام: "polling" (پیش‌فرض) یا "webhook"
# توجه: تلگرام این دو را هم‌زمان روی یک توکن قبول نمی‌کند (ست‌کردن وب‌هوک
# باعث خطا در getUpdates می‌شود و برعکس)، پس این یک انتخاب سراسری برای همه‌ی
# بات‌ها (اصلی + نماینده‌ها) است، نه اینکه هر دو با هم فعال باشند.
BOT_MODE = os.getenv("BOT_MODE", "polling").strip().lower()
if BOT_MODE not in ("polling", "webhook"):
    BOT_MODE = "polling"

# آدرس عمومی HTTPS (دامنه‌ای که nginx با SSL معتبر روی آن گوش می‌دهد) که
# تلگرام آپدیت‌ها را به آن پوش می‌کند - فقط در حالت webhook لازم است
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
# توکن مخفی اختیاری تلگرام (هدر X-Telegram-Bot-Api-Secret-Token) برای اطمینان
# از اینکه درخواست واقعاً از تلگرام آمده، نه یک درخواست جعلی به همان مسیر
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
# آدرس/پورت داخلی (لوکال) که سرور aiohttp وب‌هوک روی آن گوش می‌دهد؛ nginx
# روی دامنه‌ی بالا این پورت را proxy می‌کند
WEBHOOK_LISTEN_HOST = os.getenv("WEBHOOK_LISTEN_HOST", "127.0.0.1")
WEBHOOK_LISTEN_PORT = int(os.getenv("WEBHOOK_LISTEN_PORT", "8010"))

if BOT_MODE == "webhook" and not WEBHOOK_BASE_URL:
    raise RuntimeError(
        "BOT_MODE=webhook تنظیم شده ولی WEBHOOK_BASE_URL در .env خالی است. "
        "آدرس HTTPS دامنه‌ای که وب‌هوک باید به آن برسد را داخل .env قرار بده "
        "(یا از منوی manage.sh گزینه‌ی تنظیم حالت بات را دوباره اجرا کن)."
    )

# حداکثر تعداد کانفیگ تست مجاز برای هر کاربر
MAX_TEST_PER_USER = 1

# آدرس مینی‌اپ (باید HTTPS با گواهی معتبر باشد؛ خالی یعنی دکمه مینی‌اپ نمایش داده نشود)
MINIAPP_URL = os.getenv("MINIAPP_URL", "")
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

# آدرس پایه‌ی API مینی‌اپ (همان دامنه‌ای که سرور FastAPI روی آن سرو می‌شود؛‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# برای ساخت callback_url که Plisio بعد از پرداخت به آن درخواست می‌زند لازم است)
# اگر به‌صورت جداگانه در .env تنظیم نشده باشد، به‌صورت خودکار از روی MINIAPP_URL
# استخراج می‌شود (چون سرور FastAPI معمولاً همان دامنه‌ی مینی‌اپ است)؛
# بنابراین در حالت عادی نیازی به تنظیم دستی این متغیر نیست.
API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
if not API_BASE_URL and MINIAPP_URL:
    from urllib.parse import urlparse
    _parsed = urlparse(MINIAPP_URL)
    if _parsed.scheme and _parsed.netloc:
        API_BASE_URL = f"{_parsed.scheme}://{_parsed.netloc}"

# آدرس عمومی سرور «ساب اختصاصی» (مثلاً https://sub.example.com). با گزینه‌ی راه‌اندازی ساب اختصاصی در
# منوی manage.sh خودکار تنظیم می‌شود؛ روشن/خاموش و شخصی‌سازی آن از داخل ادمین بات انجام می‌شود.
DEDICATED_SUB_URL = os.getenv("DEDICATED_SUB_URL", "").rstrip("/")
DEDICATED_SUB_PORT = int(os.getenv("DEDICATED_SUB_PORT", "8004"))

# کلید API درگاه پرداخت کریپتو Plisio (فقط به‌عنوان فال‌بک سراسری؛ در عمل هر بات
# (اصلی یا نمایندگی) کلید خودش را از داخل پنل مدیریت بات تنظیم می‌کند)
PLISIO_API_KEY = os.getenv("PLISIO_API_KEY", "")

# کلید API درگاه پرداخت کارت‌به‌کارت خودکار آبان گیت وی (fallback سراسری؛ هر بات
# می‌تواند کلید خودش را از داخل پنل مدیریت بات تنظیم کند - دکمه‌ی «تنظیم درگاه آبان گیت وی»)
ABANGATEWAY_API_KEY = os.getenv("ABANGATEWAY_API_KEY", "")
BLUPAL_API_KEY = os.getenv("BLUPAL_API_KEY", "")

# کلید API و رمز وب‌هوک درگاه NoapayBot/StarBot
NOAPAY_API_KEY = os.getenv("NOAPAY_API_KEY", "")
NOAPAY_WEBHOOK_SECRET = os.getenv("NOAPAY_WEBHOOK_SECRET", "")

# کلید API دستیار پشتیبانی هوش مصنوعی (Google Gemini - رایگان، از aistudio.google.com
# بگیر). اگر خالی باشد، دکمه‌ی «دستیار هوشمند» در بخش ارتباط با پشتیبانی اصلاً
# نمایش داده نمی‌شود (نه خطا می‌دهد و نه بات را متوقف می‌کند).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
JARVIS_API_KEY = os.getenv("JARVIS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")


# نام مدل Gemini مورد استفاده برای دستیار پشتیبانی. اگر بعداً مدل جدیدتری آمد یا
# این مدل منسوخ شد، فقط همین مقدار را در .env تغییر بده، نیازی به تغییر کد نیست.
#
# gemini-2.5-flash دیگر برای اکانت‌های جدید در دسترس نیست (404 NOT_FOUND) و
# باعث می‌شد دستیار هوشمند مدام خطا بدهد. به‌جای پین‌کردن یک نسخه‌ی ثابت که
# دیر یا زود دوباره منسوخ می‌شود، از alias رسمی "gemini-flash-latest" استفاده‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# می‌کنیم که خودِ گوگل همیشه به آخرین نسخه‌ی خانواده‌ی Flash وصلش می‌کند
# (فعلاً یعنی Gemini 3.6/3.7/3.8 Flash، بسته به این‌که گوگل چه‌موقع سوییچ کند).
# اگر می‌خواهی نسخه‌ی مشخصی پین شود (برای پایداری رفتار مدل)، این مقدار را در
# .env با AI_SUPPORT_MODEL=gemini-3.6-flash (یا نسخه‌ی دلخواه) override کن.
AI_SUPPORT_MODEL = os.getenv("AI_SUPPORT_MODEL", "gemini-3.5-flash-lite")

# کلید امضای نشست (session) پنل مدیریت وب مستقل - فقط توسط admin_panel/server.py
# استفاده می‌شود. اگر ست نشود، هر ری‌استارت پروسه همه‌ی نشست‌های وب‌ادمین‌ها را
# باطل می‌کند (کاربران دوباره باید لاگین کنند) اما خطایی نمی‌دهد، چون بات اصلی
# به این مقدار وابسته نیست.
ADMIN_PANEL_SECRET = os.getenv("ADMIN_PANEL_SECRET", "")
if not ADMIN_PANEL_SECRET:
    import secrets as _secrets
    ADMIN_PANEL_SECRET = _secrets.token_hex(32)

# آدرس پنل مدیریت وب مستقل (همان دامنه‌ای که در گزینه‌ی «راه‌اندازی پنل ادمین»
# منوی manage.sh تنظیم می‌شود) - برای ساخت لینک راه‌اندازی پنل وب نماینده‌های
# کامل لازم است. اگر خالی باشد، دکمه‌ی فعال‌سازی پنل وب فقط اسلاگ/توکن را
# نشان می‌دهد و ادمین باید لینک را خودش کنار دامنه‌ی پنلش بچسباند.
ADMIN_PANEL_URL = os.getenv("ADMIN_PANEL_URL", "").rstrip("/")

# کلیدهای VAPID برای اعلان‌های Push پنل وب (کار می‌کنند حتی وقتی مرورگر ادمین
# کاملاً بسته باشد، چون از سرویس Push خودِ مرورگر عبور می‌کنند). با دستور زیر
# یک‌بار بساز و داخل .env بگذار: python -m admin_panel.generate_vapid_keys
# اگر خالی بمانند، فقط قابلیت اعلان Push غیرفعال می‌ماند؛ بقیه‌ی پنل وب طبق معمول کار می‌کند.
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "admin@example.com")
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
