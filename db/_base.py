# -*- coding: utf-8 -*-
from .constants import *

class DatabaseBase:
    _SETTINGS_CACHE_TTL = 8
    _ADMIN_CACHE_TTL = 5

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
            except Exception:  # intentional broad catch: top-level loop must not crash
                logger.exception("تازه‌سازی پس‌زمینه‌ی کش تنظیمات ناموفق بود (db_path=%s).", self.db_path)
            try:
                await asyncio.to_thread(self._load_admin_cache)
            except Exception:  # intentional broad catch: top-level loop must not crash
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
            except Exception:  # intentional broad catch: any DB error must rollback + re-raise
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
                except (sqlite3.Error, OSError):  # close may fail if connection already broken
                    pass
                self._conn = None
            self._settings_cache = None
            self._admin_cache = None


    def replace_file(self, uploaded_file_path: str) -> str:
        """فایل دیتابیس را با فایل بکاپ آپلودشده جایگزین می‌کند (برای «بازیابی از
        فایل بکاپ»). قبل از جایگزینی یک نسخه‌ی «قبل از بازیابی» گرفته می‌شود.

        نکته‌ی مهم (باگ قبلی): قبلاً این عملیات با یک `db.close()` جدا و بعد
        یک `shutil.copyfile` جدا انجام می‌شد، بدون این‌که لاک را بین این دو
        نگه دارد. در همین فاصله‌ی کوتاه، حلقه‌ی پس‌زمینه‌ی
        `cache_autorefresh_loop` (که هر ۲ ثانیه یک‌بار روی یک ترد جدا اجرا
        می‌شود) می‌توانست دقیقاً وسط جایگزینی فایل، یک اتصال sqlite تازه به
        فایلی که هنوز کامل نوشته نشده بود باز کند و آن را برای همیشه به‌عنوان
        `self._conn` نگه دارد - نتیجه‌اش این بود که بعد از بازیابی، همه‌ی
        دستورهای بعدی (حتی /start) تا ری‌استارت دستی پروسه با خطا مواجه
        می‌شدند، بدون این‌که خود عملیات بازیابی خطایی نشان بدهد.

        الان کل عملیات (بستن اتصال قدیمی + جایگزینی فایل) زیر یک لاک واحد
        انجام می‌شود، پس هیچ ترد دیگری نمی‌تواند در همین فاصله یک اتصال به
        فایل نیمه‌نوشته باز کند؛ اولین `_get_conn()` بعدی (که خودش هم منتظر
        همین لاک می‌ماند) یک اتصال تازه و سالم به فایل جدید باز خواهد کرد.
        """
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        pre_restore_path = os.path.join(backup_dir, f"pre_restore_{timestamp}.db")

        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._settings_cache = None
            self._admin_cache = None

            if os.path.exists(self.db_path):
                src = sqlite3.connect(self.db_path)
                try:
                    dst = sqlite3.connect(pre_restore_path)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                finally:
                    src.close()

            # پاک‌کردن فایل‌های کمکی WAL دیتابیس فعلی، وگرنه ممکن است داده‌ی
            # commit‌نشده‌ی قدیمی با دیتابیس جدید قاطی شود
            for suffix in ("-wal", "-shm"):
                stale = self.db_path + suffix
                if os.path.exists(stale):
                    os.remove(stale)

            shutil.copyfile(uploaded_file_path, self.db_path)
            # عمداً اتصال تازه اینجا باز نمی‌کنیم؛ self._conn همچنان None
            # می‌ماند تا اولین _get_conn() بعدی (زیر همین لاک) آن را بسازد.

        return pre_restore_path


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
                    referral_renewal_rewarded_count INTEGER DEFAULT 0,
                    referral_invite_bonus_given INTEGER DEFAULT 0,
                    referral_free_config_given INTEGER DEFAULT 0,
                    owner_reseller_id INTEGER,
                    inline_reseller_enabled INTEGER DEFAULT 0,
                    inline_reseller_commission_percent INTEGER,
                    reseller_discount_percent INTEGER,
                    reseller_supply_model TEXT DEFAULT 'volume_credit',
                    fixed_product_main_id INTEGER,
                    reseller_expires_at TEXT,
                    reseller_reminder_sent TEXT DEFAULT '',
                    score INTEGER DEFAULT 0,
                    phone_number TEXT,
                    phone_verified INTEGER DEFAULT 0,
                    referral_fraud_suspended INTEGER DEFAULT 0,
                    signup_gift_given INTEGER DEFAULT 0,
                    joined_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS admins (
                    telegram_id INTEGER PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS lottery_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lottery_date TEXT NOT NULL UNIQUE,
                    winners_json TEXT NOT NULL,
                    prize_type TEXT NOT NULL,
                    prizes_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                    cashback_paid INTEGER DEFAULT 0,
                    cashback_amount INTEGER DEFAULT 0,
                    cashback_type TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS smart_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    source_urls_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_smart_subscriptions_user ON smart_subscriptions(user_id);

                CREATE TABLE IF NOT EXISTS scheduled_broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    message_text TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    sent_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_scheduled_broadcasts_status_time ON scheduled_broadcasts(status, scheduled_at);

                CREATE TABLE IF NOT EXISTS wallet_transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    receiver_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS languages (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    native_name TEXT NOT NULL,
                    flag TEXT DEFAULT '',
                    rtl INTEGER DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    generated INTEGER NOT NULL DEFAULT 0,
                    translation_auto_quarantined INTEGER NOT NULL DEFAULT 0,
                    translation_retry_count INTEGER NOT NULL DEFAULT 0,
                    translation_last_failure TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS translations (
                    language_code TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'machine',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(language_code, source_text),
                    FOREIGN KEY(language_code) REFERENCES languages(code) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_translations_language ON translations(language_code);

                CREATE TABLE IF NOT EXISTS translation_manifests (
                    language_code TEXT PRIMARY KEY,
                    catalog_version TEXT NOT NULL DEFAULT '',
                    source_count INTEGER NOT NULL DEFAULT 0,
                    translated_count INTEGER NOT NULL DEFAULT 0,
                    missing_count INTEGER NOT NULL DEFAULT 0,
                    obsolete_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_sync_at TEXT,
                    last_error TEXT,
                    FOREIGN KEY(language_code) REFERENCES languages(code) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS translation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    language_code TEXT NOT NULL,
                    catalog_version TEXT NOT NULL,
                    source_count INTEGER NOT NULL,
                    translated_count INTEGER NOT NULL,
                    generated_count INTEGER NOT NULL DEFAULT 0,
                    obsolete_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(language_code) REFERENCES languages(code) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_translation_history_lang ON translation_history(language_code, id);

                -- قابلیت ۵۰: رجیستری متن‌های ربات، خودکار با اسکن کد (نگاه کن:
                -- text_scanner.py) در _sync_text_registry پر می‌شود. مقدار
                -- ویرایش‌شده (override) در همین جدول settings با پیشوند
                -- msgtext__ ذخیره می‌شود (نگاه کن: get_text/set_text/reset_text).
                CREATE TABLE IF NOT EXISTS bot_text_registry (
                    key TEXT PRIMARY KEY,
                    category TEXT,
                    default_text TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS discount_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    percent INTEGER,
                    fixed_amount INTEGER,
                    max_discount_amount INTEGER,
                    max_uses INTEGER DEFAULT 0,
                    used_count INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    product_ids TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS discount_redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    order_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_discount_redemptions_code_user ON discount_redemptions(code_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_discount_redemptions_order ON discount_redemptions(order_id);

                CREATE TABLE IF NOT EXISTS wallet_gift_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code_hash TEXT UNIQUE NOT NULL,
                    amount INTEGER NOT NULL,
                    max_uses INTEGER DEFAULT 1,
                    used_count INTEGER DEFAULT 0,
                    expires_at TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS wallet_gift_redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gift_code_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(gift_code_id, user_id),
                    FOREIGN KEY(gift_code_id) REFERENCES wallet_gift_codes(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_wallet_gift_redemptions_user ON wallet_gift_redemptions(user_id);

                CREATE TABLE IF NOT EXISTS panel_health (
                    server_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'up',
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    last_check TEXT,
                    last_change TEXT,
                    last_error TEXT,
                    last_alert TEXT
                );

                CREATE TABLE IF NOT EXISTS panel_health_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS report_topics (
                    chat_id INTEGER NOT NULL,
                    topic_key TEXT NOT NULL,
                    thread_id INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, topic_key)
                );

                CREATE TABLE IF NOT EXISTS wallet_topups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    cashback_paid INTEGER DEFAULT 0,
                    cashback_amount INTEGER DEFAULT 0,
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
                    has_live_bot INTEGER DEFAULT 1,
                    miniapp_enabled INTEGER DEFAULT 1,
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

                CREATE TABLE IF NOT EXISTS ai_support_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ai_faq_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tutorial_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    emoji TEXT DEFAULT '📱',
                    sort_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tutorial_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id INTEGER NOT NULL REFERENCES tutorial_devices(id) ON DELETE CASCADE,
                    step_order INTEGER DEFAULT 0,
                    text TEXT,
                    photo_file_id TEXT,
                    video_file_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tutorial_bindings (
                    tutorial_id INTEGER NOT NULL REFERENCES tutorial_devices(id) ON DELETE CASCADE,
                    target_key TEXT NOT NULL,
                    PRIMARY KEY (tutorial_id, target_key)
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

                CREATE TABLE IF NOT EXISTS ticket_departments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ticket_department_admins (
                    department_id INTEGER NOT NULL,
                    admin_id INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (department_id, admin_id),
                    FOREIGN KEY (department_id) REFERENCES ticket_departments(id) ON DELETE CASCADE
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

                CREATE TABLE IF NOT EXISTS config_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_id INTEGER NOT NULL,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_config_activity_config_id ON config_activity(config_id, created_at DESC);

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
                CREATE INDEX IF NOT EXISTS idx_ticket_department_admins_admin ON ticket_department_admins(admin_id);
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

                CREATE TABLE IF NOT EXISTS blupal_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id TEXT UNIQUE NOT NULL,  -- شناسه‌ی فاکتور در سمت بلوپال (invoice_id عددی)
                    kind TEXT NOT NULL,                -- 'order' یا 'wallet_topup'
                    ref_id INTEGER NOT NULL,           -- order_id یا topup_id
                    user_id INTEGER NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    amount_rial INTEGER NOT NULL,
                    final_amount_rial INTEGER,          -- مبلغ دقیقی که باید واریز شود (amount + عدد تصادفی ۳ رقمی)
                    payment_url TEXT,
                    status TEXT DEFAULT 'new',          -- new/pending/completed/expired/cancelled/error
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_blupal_invoices_invoice_id ON blupal_invoices(invoice_id);
                CREATE INDEX IF NOT EXISTS idx_blupal_invoices_ref ON blupal_invoices(kind, ref_id);

                CREATE TABLE IF NOT EXISTS noapay_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_token TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL,
                    ref_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    stars_count INTEGER NOT NULL,
                    quoted_total_toman INTEGER,
                    payment_url TEXT,
                    status TEXT DEFAULT 'new',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_noapay_invoices_token ON noapay_invoices(invoice_token);
                CREATE INDEX IF NOT EXISTS idx_noapay_invoices_ref ON noapay_invoices(kind, ref_id);

                CREATE TABLE IF NOT EXISTS extra_gateway_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gateway TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ref_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount_toman INTEGER NOT NULL,
                    payable_amount INTEGER,
                    remote_id TEXT,
                    order_number TEXT UNIQUE,
                    payment_url TEXT,
                    meta TEXT,
                    status TEXT DEFAULT 'new',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_extra_gw_invoices_remote ON extra_gateway_invoices(gateway, remote_id);
                CREATE INDEX IF NOT EXISTS idx_extra_gw_invoices_ref ON extra_gateway_invoices(kind, ref_id);


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
                    socks_proxy TEXT,
                    used_for_custom_config INTEGER DEFAULT 1,
                    used_for_test_config INTEGER DEFAULT 0,
                    start_on_first_use INTEGER DEFAULT 0,
                    max_services INTEGER,
                    capacity_alert_sent INTEGER DEFAULT 0,
                    transfer_price INTEGER DEFAULT 0,
                    allow_transfer_target INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
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
                    start_on_first_use INTEGER DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS service_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    custom_config_id INTEGER NOT NULL,
                    panel_server_id INTEGER,
                    rating INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT,
                    UNIQUE(user_id, custom_config_id)
                );
                CREATE INDEX IF NOT EXISTS idx_service_ratings_panel ON service_ratings(panel_server_id);

                CREATE TABLE IF NOT EXISTS location_change_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    custom_config_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    old_panel_server_id INTEGER NOT NULL,
                    new_panel_server_id INTEGER NOT NULL,
                    fee_toman INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    old_username TEXT,
                    new_username TEXT,
                    old_volume_gb INTEGER,
                    new_volume_gb INTEGER,
                    old_expires_at TEXT,
                    old_subscription_url TEXT,
                    new_expires_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_location_change_log_user ON location_change_log(user_id, created_at);

                CREATE TABLE IF NOT EXISTS bulk_gift_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    panel_server_id INTEGER,
                    params_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    total INTEGER NOT NULL DEFAULT 0,
                    done INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    note TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS bulk_gift_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES bulk_gift_jobs(id) ON DELETE CASCADE,
                    custom_config_id INTEGER NOT NULL,
                    panel_server_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    start_on_first_use INTEGER DEFAULT 0,
                    expires_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    claimed_at TEXT,
                    completed_at TEXT,
                    UNIQUE(job_id, custom_config_id)
                );
                CREATE TABLE IF NOT EXISTS price_change_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    undone_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_price_change_log_created ON price_change_log(created_at);

                CREATE INDEX IF NOT EXISTS idx_bulk_gift_items_job_status ON bulk_gift_items(job_id, status);
                CREATE INDEX IF NOT EXISTS idx_bulk_gift_jobs_status ON bulk_gift_jobs(status);

                CREATE TABLE IF NOT EXISTS reseller_credit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    delta_gb INTEGER NOT NULL,
                    reason TEXT,
                    admin_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reseller_credit_log_user ON reseller_credit_log(user_id);

                CREATE TABLE IF NOT EXISTS order_surveys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    panel_server_id INTEGER,
                    rating INTEGER,
                    sent_by INTEGER,
                    sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    answered_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_order_surveys_panel ON order_surveys(panel_server_id);

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
                    wants_custom_config INTEGER DEFAULT 0,
                    supply_model TEXT DEFAULT 'volume_credit',
                    supply_product_id INTEGER,
                    supply_qty INTEGER,
                    bot_choice TEXT DEFAULT 'dedicated',
                    wants_web_panel INTEGER DEFAULT 0,
                    wants_miniapp INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reseller_requests_user ON reseller_requests(user_id);
                CREATE INDEX IF NOT EXISTS idx_reseller_requests_status ON reseller_requests(status);

                CREATE TABLE IF NOT EXISTS reseller_product_credit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reseller_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    qty_remaining INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(reseller_id, product_id)
                );
                CREATE INDEX IF NOT EXISTS idx_reseller_product_credit_reseller ON reseller_product_credit(reseller_id);

                -- هشدار زیرمجموعه‌گیری فیک (بند ۴۳): هر رویداد تشخیص‌داده‌شده روی یک
                -- دعوت‌کننده‌ی مشکوک، تا زمانی که ادمین آن را بررسی/رفع کند، در این
                -- جدول باقی می‌ماند؛ برای جلوگیری از اسپم هشدار، به‌ازای هر دعوت‌کننده
                -- فقط یک ردیف باز (resolved=0) همزمان می‌تواند وجود داشته باشد.
                CREATE TABLE IF NOT EXISTS referral_fraud_flags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    invited_total INTEGER DEFAULT 0,
                    zero_purchase_count INTEGER DEFAULT 0,
                    burst_count INTEGER DEFAULT 0,
                    resolved INTEGER DEFAULT 0,
                    resolved_by INTEGER,
                    resolved_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_referral_fraud_flags_referrer ON referral_fraud_flags(referrer_id);
                CREATE INDEX IF NOT EXISTS idx_referral_fraud_flags_resolved ON referral_fraud_flags(resolved);

                -- نمایندگی کمیسیونی (لینک اختصاصی داخل بات اصلی) - مستقل کامل از
                -- reseller_requests (بدون حجم، بدون محصول آماده؛ فقط درصد کمیسیون
                -- روی همه‌ی خریدهای دائمی مشتریان زیرمجموعه، تا زمان غیرفعال‌سازی).
                CREATE TABLE IF NOT EXISTS commission_reseller_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    proposed_percent INTEGER NOT NULL,
                    request_text TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    approved_percent INTEGER,
                    reject_reason TEXT,
                    reviewed_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_commission_reseller_requests_user ON commission_reseller_requests(user_id);
                CREATE INDEX IF NOT EXISTS idx_commission_reseller_requests_status ON commission_reseller_requests(status);

                CREATE TABLE IF NOT EXISTS reseller_tiers (
                    code TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    icon TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    is_enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    commission_min INTEGER,
                    commission_max INTEGER,
                    permanent_discount_percent INTEGER,
                    min_qty INTEGER,
                    min_volume_gb INTEGER,
                    membership_fee_toman INTEGER NOT NULL DEFAULT 0,
                    duration_days INTEGER,
                    has_miniapp INTEGER NOT NULL DEFAULT 0,
                    has_web_panel INTEGER NOT NULL DEFAULT 0,
                    has_dedicated_bot INTEGER NOT NULL DEFAULT 0,
                    auto_approve INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS reseller_tier_qty_discounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tier_code TEXT NOT NULL,
                    min_qty INTEGER NOT NULL,
                    discount_percent INTEGER NOT NULL,
                    UNIQUE (tier_code, min_qty)
                );

                CREATE TABLE IF NOT EXISTS reseller_tier_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    tier_code TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewed_by INTEGER,
                    reject_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reseller_tier_requests_user ON reseller_tier_requests(user_id, status);

                CREATE TABLE IF NOT EXISTS reseller_inline_commission_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_reseller_id INTEGER NOT NULL,
                    buyer_id INTEGER NOT NULL,
                    paid_amount INTEGER NOT NULL,
                    commission_amount INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_reseller_inline_commission_owner ON reseller_inline_commission_log(owner_reseller_id);

                -- ===================== پنل مدیریت وب مستقل (خارج از تلگرام) =====================
                CREATE TABLE IF NOT EXISTS web_admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_login TEXT,
                    language_code TEXT DEFAULT 'fa'
                );
                CREATE INDEX IF NOT EXISTS idx_web_admins_username ON web_admins(username);

                CREATE TABLE IF NOT EXISTS payment_webhook_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gateway TEXT NOT NULL,        -- 'plisio' / 'abangateway' / 'blupal' / 'custom:<gateway_key>'
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

                -- ===================== اپ موبایل مدیریت (Personal Access Token + FCM) =====================
                CREATE TABLE IF NOT EXISTS mobile_app_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    token_prefix TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'read,users,orders',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_mobile_tokens_hash ON mobile_app_tokens(token_hash);
                CREATE INDEX IF NOT EXISTS idx_mobile_tokens_admin ON mobile_app_tokens(admin_id);

                CREATE TABLE IF NOT EXISTS mobile_fcm_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    mobile_token_id INTEGER,
                    fcm_token TEXT UNIQUE NOT NULL,
                    device_label TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_fcm_tokens_admin ON mobile_fcm_tokens(admin_id);

                CREATE TABLE IF NOT EXISTS temp_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    delete_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_temp_messages_delete_at ON temp_messages(delete_at);
                """
            )

            from i18n import LANGUAGE_CATALOG
            for _code, _meta in LANGUAGE_CATALOG.items():
                c.execute(
                    "INSERT OR IGNORE INTO languages (code,name,native_name,flag,rtl,enabled,generated) VALUES (?,?,?,?,?,?,?)",
                    (_code, _meta["name"], _meta["native_name"], _meta["flag"], int(_meta["rtl"]), 1 if _code in ("fa", "en") else 0, 1 if _code in ("fa", "en") else 0),
                )

            c.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (owner_id,))

            for k, v in DEFAULT_SETTINGS.items():
                c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

            self._migrate_columns(conn)

            # Keep a manifest row for every known language. The manifest is the
            # versioned source-of-truth for automatic translation synchronization.
            for _code in LANGUAGE_CATALOG:
                c.execute(
                    "INSERT OR IGNORE INTO translation_manifests(language_code) VALUES (?)",
                    (_code,),
                )

            # رفع باگ: این ایندکس قبلا داخل executescript بالا بود، اما روی
            # دیتابیس‌های قدیمی (قبل از اضافه‌شدن ستون owner_reseller_id) جدول
            # users از قبل وجود داشت، پس CREATE TABLE IF NOT EXISTS کاری نمی‌کرد
            # و ساخت این ایندکس با OperationalError: no such column می‌شکست -
            # قبل از این‌که _migrate_columns اصلا فرصت اضافه‌کردن ستون را پیدا کند.
            # حالا بعد از migrate_columns ساخته می‌شود که ستون تضمینا موجود است.
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_owner_reseller_id ON users(owner_reseller_id)")

            c.execute(
                "CREATE TABLE IF NOT EXISTS wallet_transactions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, delta INTEGER NOT NULL, "
                "balance_before INTEGER NOT NULL, balance_after INTEGER NOT NULL, kind TEXT, note TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_wallet_transactions_user ON wallet_transactions(user_id, id)")
            c.execute(
                "CREATE TABLE IF NOT EXISTS wallet_tx_label (user_id INTEGER PRIMARY KEY, kind TEXT, note TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS coin_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
                "amount INTEGER NOT NULL, remaining INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT)"
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_coin_batches_user ON coin_batches(user_id, remaining)")
            c.execute(
                "CREATE TABLE IF NOT EXISTS coin_wallet_credits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
                "amount INTEGER NOT NULL, remaining INTEGER NOT NULL, tx_id INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT)"
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_coin_wallet_credits_user ON coin_wallet_credits(user_id, remaining)")
            c.execute(
                "CREATE TRIGGER IF NOT EXISTS trg_wallet_transactions AFTER UPDATE OF referral_credit ON users "
                "WHEN COALESCE(OLD.referral_credit,0) <> COALESCE(NEW.referral_credit,0) BEGIN "
                "INSERT INTO wallet_transactions (user_id, delta, balance_before, balance_after, kind, note) "
                "VALUES (NEW.telegram_id, COALESCE(NEW.referral_credit,0) - COALESCE(OLD.referral_credit,0), "
                "COALESCE(OLD.referral_credit,0), COALESCE(NEW.referral_credit,0), "
                "(SELECT kind FROM wallet_tx_label WHERE user_id=NEW.telegram_id), "
                "(SELECT note FROM wallet_tx_label WHERE user_id=NEW.telegram_id)); END"
            )

            self._seed_default_custom_config_product(conn)
            self._seed_default_test_config_plan(conn)
            self._seed_default_reseller_tiers(conn)

            # رفع باگ: این فایل دیتابیس ممکن است از یک بات نمایندگیِ حذف‌شده‌ی قبلی
            # باقی مانده باشد (مثلاً ادمین موقع حذف نماینده گزینه‌ی «پاک نشود» را
            # زده، و یک نماینده‌ی تازه بعداً با همان یوزرنیم بات ثبت‌نام کرده - چون
            # مسیر فایل فقط از روی یوزرنیم بات ساخته می‌شود). قبلاً چون همه‌جا از
            # CREATE TABLE IF NOT EXISTS استفاده شده، owner قدیمی در admins دست‌نخورده
            # می‌ماند و INSERT OR IGNORE بالا owner جدید را فقط *اضافه* می‌کند - نتیجه
            # دو ردیف با role='owner' بود و get_owner_telegram_id() (که LIMIT 1 می‌زند)
            # می‌توانست owner قدیمی و غلط را برگرداند، یعنی کل اعتبار حجمی/تشخیص
            # مالکیت این بات نماینده به فرد اشتباه (نماینده‌ی حذف‌شده‌ی قبلی) می‌رفت.
            # این چک باید بعد از _migrate_columns باشد چون ستون role در نصب‌های
            # خیلی قدیمی/دیتابیس تازه‌ساز با ALTER TABLE همان‌جا اضافه می‌شود، نه در
            # CREATE TABLE بالا. اگر owner ثبت‌شده‌ی فعلی با owner_id تازه فرق دارد،
            # یعنی این قطعاً داده‌ی یک نصب/مالک دیگر است - جدول admins برای این
            # instance از صفر ساخته می‌شود تا مالکیت همیشه بدون ابهام مشخص باشد
            # (نگه‌داشتن کاربران/سفارش‌های قدیمی به‌عنوان «پشتیبان» به‌عهده‌ی خودِ
            # فایل دیتابیس است، نه این تابع).
            existing_owner = conn.execute(
                "SELECT telegram_id FROM admins WHERE role='owner' LIMIT 1"
            ).fetchone()
            if existing_owner and existing_owner["telegram_id"] != owner_id:
                logger.warning(
                    "init_db: owner قدیمی (%s) این دیتابیس با owner تازه (%s) فرق دارد؛ "
                    "احتمالاً فایل از یک نماینده‌ی حذف‌شده‌ی قبلی باقی مانده - جدول admins بازسازی می‌شود.",
                    existing_owner["telegram_id"], owner_id,
                )
                conn.execute("DELETE FROM admins")
                conn.execute("INSERT INTO admins (telegram_id) VALUES (?)", (owner_id,))

            # اطمینان از این‌که همیشه مالک اصلی (از env) نقش «owner» را داشته باشد،
            # چه در نصب تازه و چه در ارتقای نصب‌های قدیمی‌تر که این ستون را نداشتند.
            conn.execute("UPDATE admins SET role='owner' WHERE telegram_id=?", (owner_id,))

                # مهاجرت زبان کاربران برای نصب‌های قدیمی.
        try:
            conn.execute("ALTER TABLE users ADD COLUMN language_code TEXT DEFAULT 'fa'")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        conn.execute("UPDATE users SET language_code='fa' WHERE language_code IS NULL OR language_code=''")

# قابلیت ۵۰: هر بار این نمونه از بات بالا می‌آید، کد را برای فراخوانی‌های
        # get_text(...) اسکن می‌کند تا متن‌های جدید خودکار در پنل وب ظاهر شوند
        # (نگاه کن: text_scanner.py، _sync_text_registry).
        self._sync_text_registry()

        # صف هدیه باید بعد از هر ری‌استارت خودکار ادامه پیدا کند. worker خودش
        # فقط یک نمونه برای هر فایل DB اجرا می‌کند.
        try:
            from bulk_gifts import ensure_worker
            ensure_worker(self)
        except Exception:
            logger.exception("شروع worker هدیه‌ی گروهی ناموفق بود")

    # جدول‌هایی که «داده‌ی فروشگاه» این نمونه‌ی بات محسوب می‌شوند و در factory
    # reset کامل پاک می‌شوند. reseller_bots و pending_db_purges عمداً اینجا
    # نیستند: این‌ها ثبت بات‌های زیرمجموعه/صف حذف فایل هستند، نه داده‌ی خودِ
    # این بات، و factory reset یک بات نباید بات‌های نماینده‌ی دیگرش را قطع کند.
    FACTORY_RESET_TABLES = (
        "users", "categories", "products", "configs", "config_activity", "test_configs",
        "test_config_plans", "orders", "discount_codes", "discount_redemptions", "wallet_topups",
        "crypto_invoices", "support_messages", "support_conversations",
        "admin_presence", "tickets", "ticket_messages", "ticket_departments", "ticket_department_admins", "admin_logs",
        "abangateway_invoices", "blupal_invoices", "noapay_invoices", "extra_gateway_invoices", "custom_gateways", "custom_gateway_invoices",
        "card_to_card_cards", "card_to_card_invoices", "panel_servers", "panel_health", "panel_health_events", "report_topics",
        "custom_config_pricing_tiers", "custom_config_products",
        "custom_config_product_pricing_tiers", "custom_configs",
        "custom_config_history", "location_change_log", "bulk_gift_jobs", "bulk_gift_items", "price_change_log", "lottery_log", "reseller_credit_log", "wallet_transactions", "wallet_tx_label", "coin_batches", "coin_wallet_credits", "reseller_requests",
        "reseller_product_credit", "reseller_inline_commission_log", "reseller_tiers",
        "reseller_tier_qty_discounts", "reseller_tier_requests",
        "payment_webhook_logs", "web_push_subscriptions", "temp_messages", "order_surveys",
        "referral_fraud_flags",
        "settings",
    )


    def factory_reset(self, owner_id: int = None):
        """بازگشت این نمونه از دیتابیس (بات اصلی یا یک بات نمایندگی) به وضعیت
        روز اول نصب: تمام داده‌ی فروشگاه (کاربران، سفارش‌ها، محصولات، کیف پول،
        تیکت‌ها، تنظیمات و ...) پاک می‌شود. فقط خودِ صاحب این نمونه در جدول
        admins/web_admins نگه داشته می‌شود تا بعد از ریست قفل نشود؛ بقیه‌ی
        ادمین‌ها/کاربران پنل حذف می‌شوند چون در روز اول نصب وجود نداشتند.
        بات‌های نماینده‌ی این بات (در صورت وجود) دست‌نخورده باقی می‌مانند.
        اگر owner_id داده نشود، از همان ردیف role='owner' موجود در admins
        همین دیتابیس خوانده می‌شود (هر نمونه از قبل دقیقاً یک owner دارد)."""
        with self._get_conn() as conn:
            c = conn.cursor()
            if owner_id is None:
                row = c.execute("SELECT telegram_id FROM admins WHERE role='owner' LIMIT 1").fetchone()
                if not row:
                    raise ValueError("این دیتابیس هیچ owner ثبت‌شده‌ای ندارد؛ factory_reset ناممکن است.")
                owner_id = row["telegram_id"]
            c.execute("PRAGMA foreign_keys = OFF")
            for table in self.FACTORY_RESET_TABLES:
                if table not in self.FACTORY_RESET_TABLES:
                    raise ValueError(f"factory_reset: جدول نامعتبر {table!r}")
                c.execute(f"DELETE FROM {table}")  # table از FACTORY_RESET_TABLES (whitelist داخلی)
            c.execute("DELETE FROM admins WHERE telegram_id != ?", (owner_id,))
            c.execute("DELETE FROM web_admins WHERE role != 'owner'")
            c.execute("PRAGMA foreign_keys = ON")

            c.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (owner_id,))
            c.execute("UPDATE admins SET role='owner' WHERE telegram_id=?", (owner_id,))
            for k, v in DEFAULT_SETTINGS.items():
                c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

            self._seed_default_custom_config_product(conn)
            self._seed_default_test_config_plan(conn)
            self._seed_default_reseller_tiers(conn)

        self._settings_cache = None
        self._admin_cache = None


    def _column_exists(self, conn, table: str, column: str) -> bool:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return column in cols


    def _migrate_columns(self, conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS translation_manifests (
            language_code TEXT PRIMARY KEY, catalog_version TEXT NOT NULL DEFAULT '',
            source_count INTEGER NOT NULL DEFAULT 0, translated_count INTEGER NOT NULL DEFAULT 0,
            missing_count INTEGER NOT NULL DEFAULT 0, obsolete_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', last_sync_at TEXT, last_error TEXT,
            FOREIGN KEY(language_code) REFERENCES languages(code) ON DELETE CASCADE
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS translation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, language_code TEXT NOT NULL,
            catalog_version TEXT NOT NULL, source_count INTEGER NOT NULL, translated_count INTEGER NOT NULL,
            generated_count INTEGER NOT NULL DEFAULT 0, obsolete_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(language_code) REFERENCES languages(code) ON DELETE CASCADE
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_translation_history_lang ON translation_history(language_code, id)")
        # Translation health/recovery state. These columns are additive so
        # existing installations keep their language data untouched.
        for _col, _typ in [
            ("translation_auto_quarantined", "INTEGER NOT NULL DEFAULT 0"),
            ("translation_retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ("translation_last_failure", "TEXT"),
        ]:
            if not self._column_exists(conn, "languages", _col):
                conn.execute(f"ALTER TABLE languages ADD COLUMN {_col} {_typ}")

        migrations = [
            ("users", "referred_by", "INTEGER"),
            ("users", "owner_reseller_id", "INTEGER"),
            ("users", "inline_reseller_enabled", "INTEGER DEFAULT 0"),
            ("users", "inline_reseller_commission_percent", "INTEGER"),
            ("users", "reseller_discount_percent", "INTEGER"),
            ("users", "reseller_supply_model", "TEXT DEFAULT 'volume_credit'"),
            ("users", "fixed_product_main_id", "INTEGER"),
            ("users", "referral_credit", "INTEGER DEFAULT 0"),
            ("users", "credit_limit", "INTEGER DEFAULT 0"),
            ("users", "referral_first_purchase_rewarded", "INTEGER DEFAULT 0"),
            ("users", "referral_renewal_rewarded_count", "INTEGER DEFAULT 0"),
            ("users", "referral_invite_bonus_given", "INTEGER DEFAULT 0"),
            ("users", "referral_free_config_given", "INTEGER DEFAULT 0"),
            ("users", "referral_fraud_suspended", "INTEGER DEFAULT 0"),
            ("users", "signup_gift_given", "INTEGER DEFAULT 0"),
            ("users", "score", "INTEGER DEFAULT 0"),
            ("users", "coin_mode", "TEXT DEFAULT 'wallet'"),
            ("users", "coin_credit_synced_tx", "INTEGER DEFAULT 0"),
            ("panel_health", "last_alert", "TEXT"),
            ("orders", "status", "TEXT DEFAULT 'pending'"),
            ("orders", "base_price", "INTEGER"),
            ("orders", "wallet_used", "INTEGER DEFAULT 0"),
            ("orders", "discount_code_id", "INTEGER"),
            ("orders", "discount_amount", "INTEGER DEFAULT 0"),
            ("orders", "final_price", "INTEGER"),
            ("orders", "cashback_paid", "INTEGER DEFAULT 0"),
            ("orders", "cashback_amount", "INTEGER DEFAULT 0"),
            ("orders", "cashback_type", "TEXT"),
            ("orders", "receipt_type", "TEXT DEFAULT 'photo'"),
            ("wallet_topups", "receipt_type", "TEXT DEFAULT 'photo'"),
            ("wallet_topups", "cashback_paid", "INTEGER DEFAULT 0"),
            ("wallet_topups", "cashback_amount", "INTEGER DEFAULT 0"),
            ("users", "last_wheel_spin_at", "TEXT"),
            ("discount_codes", "expires_at", "TEXT"),
            ("discount_codes", "source", "TEXT"),
            ("discount_codes", "min_purchase", "INTEGER"),
            ("discount_codes", "max_purchase", "INTEGER"),
            ("discount_codes", "product_id", "INTEGER"),
            ("discount_codes", "category_id", "INTEGER"),
            ("discount_codes", "per_user_limit", "INTEGER"),
            ("discount_codes", "first_purchase_only", "INTEGER DEFAULT 0"),
            ("discount_codes", "audience", "TEXT DEFAULT 'all'"),
            ("discount_codes", "max_discount_amount", "INTEGER"),
            ("discount_codes", "product_ids", "TEXT"),
            ("products", "duration_days", "INTEGER DEFAULT 30"),
            ("configs", "expires_at", "TEXT"),
            ("configs", "renewal_reminder_sent", "INTEGER DEFAULT 0"),
            ("configs", "volume_reminder_sent", "INTEGER DEFAULT 0"),
            ("products", "low_stock_alert_sent", "INTEGER DEFAULT 0"),
            ("admins", "role", "TEXT DEFAULT 'admin'"),
            ("mobile_app_tokens", "scope", "TEXT NOT NULL DEFAULT 'read,users,orders'"),
            ("support_messages", "is_read_by_admin", "INTEGER DEFAULT 0"),
            ("tickets", "claimed_by", "INTEGER"),
            ("tickets", "department_id", "INTEGER"),
            ("orders", "quantity", "INTEGER DEFAULT 1"),
            ("orders", "config_name", "TEXT"),
            ("configs", "order_id", "INTEGER"),
            ("reseller_bots", "link_slug", "TEXT"),
            ("reseller_bots", "web_panel_enabled", "INTEGER DEFAULT 0"),
            ("reseller_bots", "web_panel_setup_token", "TEXT"),
            ("reseller_bots", "web_panel_setup_token_created_at", "TEXT"),
            ("reseller_bots", "has_live_bot", "INTEGER DEFAULT 1"),
            ("reseller_bots", "miniapp_enabled", "INTEGER DEFAULT 1"),
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
            ("panel_servers", "socks_proxy", "TEXT"),
            ("panel_servers", "used_for_custom_config", "INTEGER DEFAULT 1"),
            ("panel_servers", "used_for_test_config", "INTEGER DEFAULT 0"),
            ("panel_servers", "start_on_first_use", "INTEGER DEFAULT 0"),
            ("panel_servers", "max_services", "INTEGER"),
            ("panel_servers", "transfer_price", "INTEGER DEFAULT 0"),
            ("panel_servers", "allow_transfer_target", "INTEGER DEFAULT 0"),
            ("users", "location_change_count", "INTEGER DEFAULT 0"),
            ("location_change_log", "old_subscription_url", "TEXT"),
            ("panel_servers", "capacity_alert_sent", "INTEGER DEFAULT 0"),
            ("panel_servers", "used_for_reseller", "INTEGER DEFAULT 0"),
            ("panel_servers", "xui_inbound_id", "INTEGER"),
            ("panel_servers", "xui_sub_base_url", "TEXT"),
            ("panel_servers", "xui_sub_base_urls", "TEXT"),
            # چند-inbound برای 3X-UI: از این به بعد یک سرور می‌تواند همزمان چند
            # inbound برای ساخت کاربر جدید داشته باشد (JSON array از id ها، مثلاً
            # "[1,2,3]"). ستون قدیمی xui_inbound_id (تک‌مقداری) برای سازگاری با
            # نصب‌های قبلی حذف نشده و به‌عنوان fallback خوانده می‌شود.
            ("panel_servers", "xui_inbound_ids", "TEXT"),
            ("users", "phone_number", "TEXT"),
            ("users", "phone_verified", "INTEGER DEFAULT 0"),
            ("products", "is_auto_provision", "INTEGER DEFAULT 0"),
            ("products", "auto_provision_volume_gb", "INTEGER"),
            ("products", "provision_server_id", "INTEGER"),
            ("products", "extra_user_price", "INTEGER DEFAULT 0"),
            ("products", "max_users", "INTEGER DEFAULT 0"),
            ("products", "base_users", "INTEGER DEFAULT 0"),
            ("orders", "user_limit", "INTEGER"),
            ("orders", "renewal_user_limit", "INTEGER"),
            ("custom_configs", "user_limit", "INTEGER"),
            ("users", "is_reseller", "INTEGER DEFAULT 0"),
            ("users", "reseller_credit_gb", "INTEGER DEFAULT 0"),
            ("custom_configs", "renewal_reminder_sent", "INTEGER DEFAULT 0"),
            ("custom_configs", "volume_reminder_sent", "INTEGER DEFAULT 0"),
            ("custom_configs", "source", "TEXT DEFAULT 'custom_config'"),
            ("custom_configs", "reseller_product_id", "INTEGER"),
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
            ("reseller_requests", "tier_code", "TEXT"),
            ("users", "reseller_tier", "TEXT"),
            ("users", "reseller_expires_at", "TEXT"),
            ("users", "reseller_reminder_sent", "TEXT DEFAULT ''"),
            ("reseller_tiers", "membership_fee_toman", "INTEGER NOT NULL DEFAULT 0"),
            ("reseller_tiers", "duration_days", "INTEGER"),
            ("reseller_tiers", "credit_limit_toman", "INTEGER NOT NULL DEFAULT 0"),
            ("orders", "tier_discount_amount", "INTEGER DEFAULT 0"),
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
            ("reseller_requests", "wants_custom_config", "INTEGER DEFAULT 0"),
            ("reseller_requests", "supply_model", "TEXT DEFAULT 'volume_credit'"),
            ("reseller_requests", "supply_product_id", "INTEGER"),
            ("reseller_requests", "supply_qty", "INTEGER"),
            ("reseller_requests", "bot_choice", "TEXT DEFAULT 'dedicated'"),
            ("reseller_requests", "wants_web_panel", "INTEGER DEFAULT 0"),
            ("reseller_requests", "wants_miniapp", "INTEGER DEFAULT 0"),
            ("reseller_requests", "payment_method", "TEXT"),
            ("reseller_requests", "payment_methods", "TEXT"),
            ("reseller_requests", "proposed_percent", "INTEGER"),
            ("reseller_requests", "commission_percent", "INTEGER"),
            ("reseller_requests", "discount_percent", "INTEGER"),
            # دیتابیس‌های قدیمی جدول reseller_tier_requests را بدون متن درخواست ساخته‌اند؛
            # مهاجرت یکپارچه‌ی درخواست‌ها پایین‌تر r.request_text را می‌خواند، پس این ستون
            # باید قبل از اجرای seed/migration اضافه شود.
            ("reseller_tier_requests", "request_text", "TEXT"),
            # رفع باگ: قبلاً وضعیت pending_review در طول کل مراحل «انتخاب پنل» و
            # «تعیین قیمت» ثابت می‌ماند، پس اگر دو ادمین senior هم‌زمان روی یک
            # درخواست کار می‌کردند، هر دو می‌توانستند پنل انتخاب کنند و قیمت
            # بفرستند بدون این‌که از کار همدیگر خبردار شوند (آخری بی‌سروصدا
            # رونویسی می‌کرد). claimed_by یک قفل خوش‌بینانه‌ی ساده است: اولین
            # ادمینی که «تایید و تعیین هزینه» را می‌زند این درخواست را claim
            # می‌کند و تا وقتی قیمت را نهایی نکند یا خودش/ادمین دیگری آن را رد
            # نکند، ادمین دوم پیام «توسط ادمین دیگری در حال بررسی است» می‌بیند.
            ("reseller_requests", "claimed_by", "INTEGER"),
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
            # غیرفعال‌سازی اداری یک کانفیگ بانکی توسط ادمین (بدون حذف کامل)؛ وقتی
            # فعال باشد، لینک دیگر به کاربر (در بات/مینی‌اپ) نمایش داده نمی‌شود.
            ("configs", "is_disabled", "INTEGER DEFAULT 0"),
            # هشدار اتصال / عدم‌اتصال به کانفیگ: یک‌بار برای هر سرویس ارسال
            # می‌شوند (مثل renewal_reminder_sent/volume_reminder_sent).
            # activated_at مبنای شمارش «N ساعت از فعال‌سازی» برای هشدار
            # عدم‌اتصال است؛ برای configs از assigned_at موجود استفاده می‌شود،
            # برای custom_configs از created_at موجود - نیازی به ستون جدید نیست.
            ("configs", "connect_alert_sent", "INTEGER DEFAULT 0"),
            ("configs", "no_connect_alert_sent", "INTEGER DEFAULT 0"),
            ("custom_configs", "connect_alert_sent", "INTEGER DEFAULT 0"),
            ("custom_configs", "no_connect_alert_sent", "INTEGER DEFAULT 0"),
            ("custom_configs", "start_on_first_use", "INTEGER DEFAULT 0"),
            ("custom_configs", "cleanup_soft_disabled_at", "TEXT"),
            ("custom_configs", "cleanup_warning_sent_at", "TEXT"),
            ("custom_configs", "cleanup_deleted_at", "TEXT"),
            ("custom_configs", "service_alert_expired_sent_at", "TEXT"),
            # آینه‌ی محلیِ پنل اعتبار حجمی نمایندگی (رفع باگ): بات‌های نمایندگی هر
            # کدام دیتابیس sqlite جدای خودشان را دارند و panel_servers.id بین این
            # دو دیتابیس هیچ ارتباطی ندارد. reseller_auto_provision.py برای ساخت
            # کاربر واقعی از پنلِ ثبت‌شده در دیتابیس بات اصلی استفاده می‌کند، ولی
            # add_custom_config باید رکورد را در دیتابیس همین بات نمایندگی (که
            # FOREIGN KEY(panel_server_id) به panel_servers خودش دارد) ذخیره کند.
            # قبلاً همان id عددی بات اصلی مستقیم پاس داده می‌شد که تقریباً همیشه در
            # جدول panel_servers بات نمایندگی وجود نداشت (این بات‌ها معمولاً هیچ
            # پنلی از خودشان ندارند) و INSERT با FOREIGN KEY constraint failed شکست
            # می‌خورد - چون داخل try/except بی‌صدا بود، مشتری اکانتش را واقعاً
            # می‌گرفت ولی هیچ‌جای بات نمایندگی ثبت نمی‌شد (نه در «سرویس‌های من»، نه
            # در یادآورهای تمدید/اتمام حجم). get_or_create_mirror_panel_server یک
            # ردیف محلی معادل همان پنل می‌سازد/به‌روز می‌کند و mirror_source_id
            # ارتباط پایدار بین دو دیتابیس را نگه می‌دارد.
            ("panel_servers", "mirror_source_id", "INTEGER"),
            ("panel_servers", "is_mirror", "INTEGER DEFAULT 0"),
            ("panel_servers", "sort_order", "INTEGER DEFAULT 0"),
            # قابلیت #253: ترتیب نمایش محصولات داخل هر دسته (پیش از این فقط بر
            # اساس id/ترتیب ساخت مرتب می‌شدند).
            ("products", "sort_order", "INTEGER DEFAULT 0"),
        ]
        for table, col, coltype in migrations:
            if not self._column_exists(conn, table, col):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")

        # مهاجرت نقش‌های ثابت قدیمی (owner/admin/mid/support) به مجموعه
        # مجوزهای granular. فقط رکوردهایی که هنوز permissions ندارند پر می‌شوند
        # تا override دستی مالک روی حساب‌های موجود دست‌نخورده بماند.
        if not self._column_exists(conn, "web_admins", "language_code"):
            conn.execute("ALTER TABLE web_admins ADD COLUMN language_code TEXT DEFAULT 'fa'")
            conn.execute("UPDATE web_admins SET language_code='fa' WHERE language_code IS NULL OR language_code=''")

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

        if conn.execute(
            "SELECT 1 FROM settings WHERE key='_migrated_tutorial_bindings'"
        ).fetchone() is None:
            conn.execute(
                "INSERT OR IGNORE INTO tutorial_bindings (tutorial_id, target_key) "
                "SELECT d.id, t.k FROM tutorial_devices d "
                "JOIN (SELECT 'general' k UNION ALL SELECT 'post_purchase' UNION ALL SELECT 'svc_detail') t"
            )
            conn.execute(
                "UPDATE settings SET value=? WHERE key='btn_tutorial' AND value=?",
                ("📚 آموزش", "📚 آموزش اتصال"),
            )
            conn.execute(
                "UPDATE settings SET value=? WHERE key='acct_tutorial_text' AND value=?",
                ("📚 آموزش", "📚 آموزش اتصال"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('_migrated_tutorial_bindings', '1')"
            )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_department_id ON tickets(department_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_configs_order_id ON configs(order_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_logs_record ON admin_logs(record_type, record_id)"
        )


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

