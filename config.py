# -*- coding: utf-8 -*-
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
    """مسیرهای قدیمی که ممکن است نسبی داخل دیتابیس ذخیره شده باشند را هم
    به مسیر مطلق تبدیل می‌کند (سازگاری با رکوردهای نمایندگی قدیمی‌تر)."""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)

# حداکثر تعداد کانفیگ تست مجاز برای هر کاربر
MAX_TEST_PER_USER = 1

# آدرس مینی‌اپ (باید HTTPS با گواهی معتبر باشد؛ خالی یعنی دکمه مینی‌اپ نمایش داده نشود)
MINIAPP_URL = os.getenv("MINIAPP_URL", "")

# آدرس پایه‌ی API مینی‌اپ (همان دامنه‌ای که سرور FastAPI روی آن سرو می‌شود؛
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

# کلید API درگاه پرداخت کریپتو Plisio (فقط به‌عنوان فال‌بک سراسری؛ در عمل هر بات
# (اصلی یا نمایندگی) کلید خودش را از داخل پنل مدیریت بات تنظیم می‌کند)
PLISIO_API_KEY = os.getenv("PLISIO_API_KEY", "")

# کلید API درگاه پرداخت کارت‌به‌کارت خودکار آبان گیت وی (fallback سراسری؛ هر بات
# می‌تواند کلید خودش را از داخل پنل مدیریت بات تنظیم کند - دکمه‌ی «تنظیم درگاه آبان گیت وی»)
ABANGATEWAY_API_KEY = os.getenv("ABANGATEWAY_API_KEY", "")

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
