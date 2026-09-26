# -*- coding: utf-8 -*-
from .constants import *

class SystemMixin:
    def wipe_agent_state(self, user_tg_id: int) -> dict:
        """حذف کامل هر چیزی که «نمایندگی قبلیِ» کاربر بود: بات و دیتابیس اختصاصی،
        اعتبار حجمی/محصولی، پنل، لینک و درصد کمیسیون، سطح، و برچسب مشتری‌های وصل‌شده.
        کیف پول و لاگ‌های مالی (سابقه‌ی حسابداری) عمداً دست‌نخورده می‌مانند."""
        try:
            from config import resolve_db_path
        except Exception:
            resolve_db_path = lambda p: p
        removed_bots = 0
        for bot_row in [b for b in self.list_reseller_bots() if b["owner_telegram_id"] == user_tg_id]:
            self.delete_reseller_bot(bot_row["id"])
            db_path = resolve_db_path(bot_row["db_path"])
            if not self._remove_reseller_db_files(db_path):
                self.queue_db_purge(bot_row["bot_token"], db_path)
            removed_bots += 1
        self.purge_reseller_leftovers(user_tg_id)
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET inline_reseller_commission_percent=NULL, reseller_discount_percent=NULL, reseller_tier=NULL, reseller_expires_at=NULL WHERE telegram_id=?",
                (user_tg_id,),
            )
            conn.execute("DELETE FROM reseller_product_credit WHERE reseller_id=?", (user_tg_id,))
            conn.execute("UPDATE users SET owner_reseller_id=NULL WHERE owner_reseller_id=?", (user_tg_id,))
        return {"bots_removed": removed_bots}


    def create_smart_subscription(self, user_id: int, source_urls: list) -> str:
        source_urls = [u.strip() for u in source_urls if isinstance(u, str) and u.strip()]
        if not source_urls:
            raise ValueError("هیچ لینک اشتراکی معتبری وجود ندارد")
        token = secrets.token_urlsafe(24)
        payload = json.dumps(source_urls, ensure_ascii=False)
        with self._get_conn() as conn:
            conn.execute("UPDATE smart_subscriptions SET is_active=0 WHERE user_id=?", (user_id,))
            conn.execute("INSERT INTO smart_subscriptions(user_id,token,source_urls_json) VALUES(?,?,?)", (user_id, token, payload))
        return token


    def get_smart_subscription(self, token: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM smart_subscriptions WHERE token=? AND is_active=1", (token,)).fetchone()


    def get_alternate_sub_urls(self, url: str) -> list:
        """لینک‌های اشتراک جایگزین (دامنه/IP های دیگر همان سرور) برای یک لینک اشتراک."""
        if not url:
            return []
        with self._get_conn() as conn:
            rows = conn.execute("SELECT xui_sub_base_urls FROM panel_servers WHERE xui_sub_base_urls IS NOT NULL AND xui_sub_base_urls != ''").fetchall()
        for row in rows:
            try:
                bases = [str(b).strip().rstrip("/") for b in json.loads(row[0]) if str(b).strip()]
            except Exception:
                continue
            if len(bases) > 1 and url.startswith(bases[0] + "/"):
                tail = url[len(bases[0]):]
                return [b + tail for b in bases[1:]]
        return []


    def create_scheduled_broadcast(self, admin_id: int, message_text: str, scheduled_at: str) -> int:
        with self._get_conn() as conn:
            cur=conn.execute("INSERT INTO scheduled_broadcasts(admin_id,message_text,scheduled_at) VALUES(?,?,?)", (admin_id,message_text,scheduled_at))
            return cur.lastrowid


    def get_due_scheduled_broadcasts(self, now_iso: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM scheduled_broadcasts WHERE status='pending' AND scheduled_at<=? ORDER BY id LIMIT 10", (now_iso,)).fetchall()


    def mark_scheduled_broadcast(self, job_id: int, status: str, sent_count: int = 0, failed_count: int = 0):
        with self._get_conn() as conn:
            conn.execute("UPDATE scheduled_broadcasts SET status=?,sent_count=?,failed_count=?,sent_at=CURRENT_TIMESTAMP WHERE id=?", (status,sent_count,failed_count,job_id))


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
    # قابلیت ۵۰: متن‌های ربات (تغییر همه‌ی متن‌ها از طریق سایت)
    # -----------------------------------------------------------------------
    # هر متن قابل‌ویرایش با یک کلید یکتا (مثلاً "handlers_user.welcome_extra")
    # در کد با db.get_text(key, default) خوانده می‌شود. مقدار override (اگر
    # ادمین از پنل وب چیزی ذخیره کرده باشد) در همان جدول settings موجود، با
    # پیشوند msgtext__، نگه داشته می‌شود - یعنی از همان کش/همان مکانیزم
    # get_setting/set_setting استفاده می‌کند و چیز جدیدی به لایه‌ی کش اضافه
    # نمی‌شود. متادیتای نمایش (دسته/متن پیش‌فرض) در bot_text_registry است که
    # با اسکن خودکار کد (text_scanner.py) در هر init_db به‌روز می‌شود.

    _TEXT_KEY_PREFIX = "msgtext__"


    def get_text(self, key: str, default: str = "") -> str:
        """Return the configured text in the active user language.

        Existing Persian overrides remain the source of truth for Persian.
        English uses the bilingual catalog first, then the configured/default
        Persian text as a safe fallback.
        """
        from i18n import get_language
        from db_text_policy import localize_system_text
        value = self.get_setting(f"{self._TEXT_KEY_PREFIX}{key}", default)
        return localize_system_text(value, get_language())


    def set_text(self, key: str, value: str):
        self.set_setting(f"{self._TEXT_KEY_PREFIX}{key}", value)


    def reset_text(self, key: str):
        """حذف override یک متن؛ بعد از این دوباره مقدار پیش‌فرض کد برمی‌گردد."""
        settings_key = f"{self._TEXT_KEY_PREFIX}{key}"
        with self._get_conn() as conn:
            conn.execute("DELETE FROM settings WHERE key=?", (settings_key,))
        if self._settings_cache is not None:
            self._settings_cache.pop(settings_key, None)


    def sync_text_registry(self, entries: list):
        """رجیستری bot_text_registry را با خروجی text_scanner.scan_bot_texts
        همگام می‌کند: کلیدهای تازه/تغییریافته را می‌نویسد و کلیدهایی که دیگر
        در کد نیستند را حذف می‌کند (override ذخیره‌شده‌ی آن‌ها در settings
        دست‌نخورده می‌ماند، اگر آن متن به کد برگردد دوباره کار می‌کند)."""
        with self._get_conn() as conn:
            for e in entries:
                conn.execute(
                    "INSERT INTO bot_text_registry (key, category, default_text, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET category=excluded.category, "
                    "default_text=excluded.default_text, updated_at=CURRENT_TIMESTAMP",
                    (e["key"], e.get("category", ""), e["default_text"]),
                )
            current_keys = [e["key"] for e in entries]
            if current_keys:
                placeholders = ",".join("?" * len(current_keys))
                conn.execute(
                    f"DELETE FROM bot_text_registry WHERE key NOT IN ({placeholders})",
                    current_keys,
                )
            else:
                conn.execute("DELETE FROM bot_text_registry")


    def _sync_text_registry(self):
        try:
            import text_scanner
            entries = text_scanner.scan_bot_texts()
            self.sync_text_registry(entries)
        except Exception:
            logger.exception("همگام‌سازی رجیستری متن‌های ربات (قابلیت ۵۰) ناموفق بود.")


    def list_text_registry(self, search: str = "") -> list:
        """برای تب «متن‌های ربات» در پنل وب: همه‌ی متن‌های شناخته‌شده به‌همراه
        مقدار فعلی (override یا پیش‌فرض) و این‌که آیا ویرایش شده‌اند یا نه."""
        self._maybe_reload_settings_cache()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, category, default_text FROM bot_text_registry ORDER BY category, key"
            ).fetchall()
        q = (search or "").strip().lower()
        out = []
        for r in rows:
            settings_key = f"{self._TEXT_KEY_PREFIX}{r['key']}"
            override = self._settings_cache.get(settings_key) if self._settings_cache else None
            current = override if override is not None else (r["default_text"] or "")
            if q and q not in r["key"].lower() and q not in current.lower() and q not in (r["category"] or "").lower():
                continue
            out.append({
                "key": r["key"],
                "category": r["category"] or "",
                "default_text": r["default_text"] or "",
                "current_text": current,
                "overridden": override is not None,
            })
        return out

    # -----------------------------------------------------------------------
    # چیدمان منوی اصلی (ترتیب دکمه‌ها)
    # -----------------------------------------------------------------------


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
    # ترتیب سفارشی عمومی برای هر «گروه» دکمه (رجیستری کاستوم‌سازی دکمه‌ها).
    # هر گروه با یک نام (مثلاً "payment_methods" یا "admin_items__daily") و
    # لیست کلیدهای معتبر همان گروه شناسایی می‌شود؛ خودِ ترتیب به‌صورت JSON در
    # همان جدول settings ذخیره می‌شود - کلیدهای نامعتبر/حذف‌شده فیلتر و
    # کلیدهای جدیدی که بعداً اضافه شده‌اند (valid_keys) به انتها اضافه می‌شوند.
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


    def mark_test_used(self, tg_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET test_used=test_used+1 WHERE telegram_id=?", (tg_id,))


    def try_reserve_test_slot(self, tg_id: int, max_allowed: int) -> bool:
        """رفع باگ ریس‌کاندیشن: قبلاً همه‌جا (بات، مینی‌اپ) الگو این بود که اول
        test_used در پایتون با یک SELECT جدا چک شود، بعد کانفیگ تست واقعاً روی
        پنل ساخته شود (این مرحله می‌تواند طول بکشد - تماس شبکه‌ای با پنل)، و فقط
        در انتها mark_test_used صدا زده شود. بین «چک» و «mark» هیچ قفلی نبود، پس
        چند درخواست همزمان از یک کاربر (دبل‌تپ روی دکمه، یا چند ریکوئست موازی به
        API مینی‌اپ) همگی از همان چک اولیه (test_used هنوز صفر) رد می‌شدند و هر
        کدام یک کانفیگ تست واقعی می‌ساختند - یعنی هم محدودیت «یک تست در هر
        کاربر» دور زده می‌شد و هم (در بات‌های نمایندگی) هر تلاش واقعاً از اعتبار
        حجمی نماینده کم می‌کرد.

        این تابع دقیقاً همان الگوی اتمیک consume_reseller_credit/mark_used_once
        را برای شمارنده‌ی test_used پیاده می‌کند: با یک UPDATE...WHERE اتمیک،
        سهمیه را *قبل* از تماس با پنل رزرو می‌کند. True یعنی این فراخوانی واقعاً
        برنده‌ی رزرو بوده (باید ادامه دهد)؛ False یعنی سهمیه از قبل توسط همین یا
        یک درخواست هم‌زمان دیگر مصرف شده (باید رد شود). اگر بعد از رزرو موفق،
        ساخت کانفیگ روی پنل شکست بخورد، صدازننده باید release_test_slot را صدا
        بزند تا این سهمیه به کاربر برگردد."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE users SET test_used=test_used+1 WHERE telegram_id=? AND test_used<?",
                (tg_id, max_allowed),
            )
            return cur.rowcount > 0


    def release_test_slot(self, tg_id: int):
        """جفتِ try_reserve_test_slot: وقتی رزرو شد ولی ساخت کانفیگ روی پنل بعداً
        شکست خورد (مثلاً اعتبار هم‌زمان توسط خرید دیگری مصرف شد یا خودِ پنل خطا
        داد)، سهمیه‌ی رزروشده باید برگردد تا کاربر واقعاً بتواند دوباره تلاش کند.
        WHERE test_used>0 جلوی منفی‌شدن را در حالت‌های لبه‌ای (مثل ریست دستی
        همزمانِ ادمین) می‌گیرد."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET test_used=test_used-1 WHERE telegram_id=? AND test_used>0", (tg_id,)
            )


    def reset_all_test_usage(self) -> list:
        """test_used همه‌ی کاربرانی که قبلاً کانفیگ تست گرفته‌اند را صفر می‌کند تا
        دوباره بتوانند تست بگیرند. لیست آیدی همان کاربران را برمی‌گرداند تا بشود
        بهشان پیام اطلاع‌رسانی فرستاد."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id FROM users WHERE test_used > 0").fetchall()
            user_ids = [r["telegram_id"] for r in rows]
            conn.execute("UPDATE users SET test_used=0 WHERE test_used > 0")
            return user_ids


    def create_mobile_token(self, admin_id: int, name: str, token_hash: str, token_prefix: str,
                            scope: str = "read,users,orders", revoke_previous: bool = True) -> int:
        """ایجاد PAT برای API عمومی. برای /token2 توکن قبلی همان ادمین باطل می‌شود."""
        scope = ",".join(dict.fromkeys(x.strip() for x in (scope or "read").split(",") if x.strip())) or "read"
        with self._get_conn() as conn:
            if revoke_previous:
                conn.execute(
                    "UPDATE mobile_app_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE admin_id=? AND revoked_at IS NULL",
                    (admin_id,),
                )
            cur = conn.execute(
                "INSERT INTO mobile_app_tokens (admin_id, name, token_hash, token_prefix, scope) VALUES (?, ?, ?, ?, ?)",
                (admin_id, name.strip()[:64] or "API Token", token_hash, token_prefix, scope),
            )
            return cur.lastrowid


    def get_mobile_token_by_hash(self, token_hash: str):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM mobile_app_tokens WHERE token_hash=? AND revoked_at IS NULL",
                (token_hash,),
            ).fetchone()


    def touch_mobile_token(self, token_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE mobile_app_tokens SET last_used_at=CURRENT_TIMESTAMP WHERE id=?", (token_id,)
            )


    def list_mobile_tokens(self, admin_id: int = None):
        with self._get_conn() as conn:
            if admin_id is not None:
                rows = conn.execute(
                    "SELECT id, admin_id, name, token_prefix, created_at, last_used_at, revoked_at "
                    "FROM mobile_app_tokens WHERE admin_id=? ORDER BY created_at DESC", (admin_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, admin_id, name, token_prefix, created_at, last_used_at, revoked_at "
                    "FROM mobile_app_tokens ORDER BY created_at DESC"
                ).fetchall()
            return rows


    def revoke_mobile_token(self, token_id: int, admin_id: int = None) -> bool:
        with self._get_conn() as conn:
            if admin_id is not None:
                cur = conn.execute(
                    "UPDATE mobile_app_tokens SET revoked_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND admin_id=? AND revoked_at IS NULL", (token_id, admin_id)
                )
            else:
                cur = conn.execute(
                    "UPDATE mobile_app_tokens SET revoked_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND revoked_at IS NULL", (token_id,)
                )
            return cur.rowcount > 0


    def delete_mobile_token(self, token_id: int, admin_id: int = None) -> bool:
        with self._get_conn() as conn:
            if admin_id is not None:
                cur = conn.execute(
                    "DELETE FROM mobile_app_tokens WHERE id=? AND admin_id=?", (token_id, admin_id)
                )
            else:
                cur = conn.execute("DELETE FROM mobile_app_tokens WHERE id=?", (token_id,))
            return cur.rowcount > 0

    # --------------------- اپ موبایل: توکن دستگاه برای Push (FCM) ---------------------


    def save_fcm_token(self, admin_id: int, mobile_token_id: int, fcm_token: str, device_label: str = ""):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO mobile_fcm_tokens (admin_id, mobile_token_id, fcm_token, device_label) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(fcm_token) DO UPDATE SET admin_id=excluded.admin_id, "
                "mobile_token_id=excluded.mobile_token_id, device_label=excluded.device_label, "
                "updated_at=CURRENT_TIMESTAMP",
                (admin_id, mobile_token_id, fcm_token, device_label[:128]),
            )


    def delete_fcm_token(self, fcm_token: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM mobile_fcm_tokens WHERE fcm_token=?", (fcm_token,))


    def list_fcm_tokens(self, admin_id: int = None):
        with self._get_conn() as conn:
            if admin_id is not None:
                rows = conn.execute(
                    "SELECT * FROM mobile_fcm_tokens WHERE admin_id=?", (admin_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM mobile_fcm_tokens").fetchall()
            return [r["fcm_token"] for r in rows]


    def list_fcm_tokens_with_admins(self, admin_id: int = None):
        """Return FCM token rows including admin_id so push text can be localized per recipient."""
        with self._get_conn() as conn:
            if admin_id is not None:
                return conn.execute(
                    "SELECT * FROM mobile_fcm_tokens WHERE admin_id=?", (admin_id,)
                ).fetchall()
            return conn.execute("SELECT * FROM mobile_fcm_tokens").fetchall()


    def get_translation_manifest(self, language: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM translation_manifests WHERE language_code=?", (language.lower(),)).fetchone()

    def upsert_translation_manifest(self, language: str, catalog_version: str, source_count: int,
                                    translated_count: int, missing_count: int, obsolete_count: int,
                                    status: str, last_error: str = None):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO translation_manifests(language_code,catalog_version,source_count,translated_count,missing_count,obsolete_count,status,last_sync_at,last_error) "
                "VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?) "
                "ON CONFLICT(language_code) DO UPDATE SET catalog_version=excluded.catalog_version,source_count=excluded.source_count,translated_count=excluded.translated_count,missing_count=excluded.missing_count,obsolete_count=excluded.obsolete_count,status=excluded.status,last_sync_at=excluded.last_sync_at,last_error=excluded.last_error",
                (language.lower(), catalog_version, int(source_count), int(translated_count), int(missing_count), int(obsolete_count), status, last_error),
            )

    def add_translation_history(self, language: str, catalog_version: str, source_count: int,
                                translated_count: int, generated_count: int, obsolete_count: int, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO translation_history(language_code,catalog_version,source_count,translated_count,generated_count,obsolete_count,status) VALUES(?,?,?,?,?,?,?)",
                (language.lower(), catalog_version, int(source_count), int(translated_count), int(generated_count), int(obsolete_count), status),
            )

    def list_translation_history(self, language: str, limit: int = 20):
        limit = max(1, min(int(limit), 100))
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM translation_history WHERE language_code=? ORDER BY id DESC LIMIT ?", (language.lower(), limit)).fetchall()

    def list_languages(self, enabled_only: bool = False):
        with self._get_conn() as conn:
            sql = "SELECT * FROM languages"
            if enabled_only:
                sql += " WHERE enabled=1"
            sql += " ORDER BY CASE code WHEN 'fa' THEN 0 WHEN 'en' THEN 1 ELSE 2 END, native_name"
            return conn.execute(sql).fetchall()

    def get_language(self, code: str):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM languages WHERE code=?", (code.lower(),)).fetchone()

    def enable_language(self, code: str, generated: bool = False, *, automatic: bool = False) -> bool:
        code = code.lower()
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE languages SET enabled=1, generated=?, translation_auto_quarantined=0, translation_last_failure=NULL, updated_at=CURRENT_TIMESTAMP WHERE code=?",
                (1 if generated else 0, code),
            )
        return cur.rowcount > 0

    def disable_language(self, code: str, *, automatic: bool = False, error: str = None) -> bool:
        code = code.lower()
        if code in {"fa", "en"}:
            return False
        with self._get_conn() as conn:
            if automatic:
                cur = conn.execute(
                    "UPDATE languages SET enabled=0, translation_auto_quarantined=1, translation_retry_count=COALESCE(translation_retry_count,0)+1, translation_last_failure=?, updated_at=CURRENT_TIMESTAMP WHERE code=?",
                    ((error or "Translation health check failed")[:500], code),
                )
            else:
                # A manual disable is an explicit admin choice; clear any
                # recovery marker so the health worker never re-enables it.
                cur = conn.execute(
                    "UPDATE languages SET enabled=0, translation_auto_quarantined=0, translation_last_failure=NULL, updated_at=CURRENT_TIMESTAMP WHERE code=?",
                    (code,),
                )
        return cur.rowcount > 0

    def list_translation_recovery_languages(self):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM languages WHERE code NOT IN ('fa','en') AND (enabled=1 OR translation_auto_quarantined=1) ORDER BY native_name"
            ).fetchall()

    def get_translations(self, language: str):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT source_text, translated_text FROM translations WHERE language_code=?", (language.lower(),)).fetchall()
        return {r["source_text"]: r["translated_text"] for r in rows}

    def upsert_translations(self, language: str, values: dict, source: str = "machine") -> int:
        if not values:
            return 0
        with self._get_conn() as conn:
            conn.executemany(
                "INSERT INTO translations(language_code,source_text,translated_text,source,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(language_code,source_text) DO UPDATE SET translated_text=excluded.translated_text, source=excluded.source, updated_at=CURRENT_TIMESTAMP",
                [(language.lower(), str(k), str(v), source) for k, v in values.items() if str(k).strip() and str(v).strip()],
            )
        return len(values)

    def translation_catalog(self, language: str):
        if language.lower() in {"fa", "en"}:
            return {}
        return self.get_translations(language)

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


    def get_web_admin_language(self, admin_id: int) -> str:
        with self._get_conn() as conn:
            row = conn.execute("SELECT language_code FROM web_admins WHERE id=?", (admin_id,)).fetchone()
        return (row["language_code"] if row and row["language_code"] else "fa")

    def set_web_admin_language(self, admin_id: int, language_code: str) -> bool:
        from i18n import normalize_language
        lang = normalize_language(language_code)
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE web_admins SET language_code=? WHERE id=?", (lang, admin_id))
        return cur.rowcount > 0

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


    def set_web_admin_username(self, admin_id: int, new_username: str) -> bool:
        """یوزرنیم یک حساب پنل را تغییر می‌دهد. اگر یوزرنیم جدید قبلاً توسط
        حساب دیگری استفاده شده باشد False برمی‌گردد و تغییری اعمال نمی‌شود."""
        new_username = new_username.strip().lower()
        with self._get_conn() as conn:
            clash = conn.execute(
                "SELECT id FROM web_admins WHERE username=? AND id!=?", (new_username, admin_id)
            ).fetchone()
            if clash:
                return False
            conn.execute("UPDATE web_admins SET username=? WHERE id=?", (new_username, admin_id))
            return True


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


    def get_categories(self, active_only=True):
        with self._get_conn() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order, id"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, id").fetchall()
            return rows


    def _refund_candidate(self, conn, custom_config_id: int, user_tg_id: int, source: str):
        """ردیف سرویسِ قابل بررسی برای ریفاند: متعلق به کاربر، از همین منبع، دارای حجم و دست‌نخورده (بدون تمدید/هدیه/انتقال/تغییر لوکیشن)."""
        cc = conn.execute(
            "SELECT * FROM custom_configs WHERE id=? AND user_id=?", (custom_config_id, user_tg_id)
        ).fetchone()
        if not cc or cc["source"] != source or int(cc["volume_gb"] or 0) <= 0:
            return None
        altered = conn.execute(
            "SELECT 1 FROM custom_config_history WHERE custom_config_id=? "
            "AND event_type IN ('renewal','gift','transfer') LIMIT 1", (custom_config_id,)
        ).fetchone() or conn.execute(
            "SELECT 1 FROM location_change_log WHERE custom_config_id=? LIMIT 1", (custom_config_id,)
        ).fetchone()
        return None if altered else cc


    @staticmethod
    def _refund_expired(cc, window_hours: int) -> bool:
        try:
            created = datetime.fromisoformat(str(cc["created_at"]).replace("Z", "+00:00"))
            if created.tzinfo:
                created = created.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            return True
        return datetime.utcnow() - created > timedelta(hours=window_hours)


    def get_service_refund_base(self, custom_config_id: int, user_tg_id: int) -> dict:
        """پایه‌ی ریفاند حذف سرویس شخصی خریداری‌شده: مبلغ پرداختی و رعایت مهلت؛ سهم مصرف جدا اعمال می‌شود."""
        window = max(int(self.get_setting("svc_refund_window_hours", "24") or 0), 0)
        none = {"eligible": False, "reason": "", "paid": 0, "window_hours": window}
        if window <= 0:
            return none
        with self._get_conn() as conn:
            cc = self._refund_candidate(conn, custom_config_id, user_tg_id, "custom_config")
            if not cc or not cc["order_id"]:
                return none
            order = conn.execute(
                "SELECT * FROM orders WHERE id=? AND user_id=? AND status='approved' AND is_custom_config=1",
                (cc["order_id"], user_tg_id),
            ).fetchone()
            if not order:
                return none
            paid = max(int(order["base_price"] or 0) - int(order["discount_amount"] or 0), 0)
        if paid <= 0:
            return none
        if self._refund_expired(cc, window):
            return {**none, "reason": "window", "paid": paid}
        return {"eligible": True, "reason": "", "paid": paid, "window_hours": window, "volume_gb": int(cc["volume_gb"])}


    def get_daily_report_extras(self, day: str) -> dict:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            topup = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(amount), 0) s FROM wallet_topups "
                "WHERE status='approved' AND date(created_at)=?", (day,),
            ).fetchone()
            tests = conn.execute(
                "SELECT (SELECT COUNT(*) FROM custom_configs WHERE source='test' AND date(created_at)=?) + "
                "(SELECT COUNT(*) FROM test_configs WHERE date(assigned_at)=?) c", (day, day),
            ).fetchone()
            first_purchase = conn.execute(
                "SELECT COUNT(*) c FROM ("
                "SELECT user_id, MIN(date(created_at)) first_day FROM orders "
                "WHERE status='approved' GROUP BY user_id"
                ") t WHERE t.first_day=?", (day,),
            ).fetchone()
            total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            active_users = conn.execute(
                "SELECT COUNT(*) c FROM users u WHERE EXISTS ("
                "SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1 "
                "AND (c.expires_at IS NULL OR c.expires_at > ?))",
                (now,),
            ).fetchone()["c"]
            best_hour_row = conn.execute(
                "SELECT CAST(strftime('%H', o.created_at, '+3 hours', '+30 minutes') AS INTEGER) hour, "
                "COUNT(*) c FROM orders o WHERE o.status='approved' AND date(o.created_at)=? "
                "GROUP BY hour ORDER BY c DESC LIMIT 1", (day,),
            ).fetchone()
        return {
            "topup_count": topup["c"], "topup_amount": topup["s"], "test_count": tests["c"],
            "first_purchase_count": first_purchase["c"],
            "active_users_count": active_users, "inactive_users_count": total_users - active_users,
            "best_hour": best_hour_row["hour"] if best_hour_row else None,
            "best_hour_orders": best_hour_row["c"] if best_hour_row else 0,
        }


    def get_credit_limit(self, user_tg_id: int) -> int:
        with self._get_conn() as conn:
            return self._wallet_balance_and_limit(conn, user_tg_id)[1]


    def set_credit_limit(self, user_tg_id: int, amount: int) -> bool:
        amount = max(int(amount), 0)
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE users SET credit_limit=? WHERE telegram_id=?", (amount, user_tg_id))
            return cur.rowcount > 0


    def reward_referrer_if_first_purchase(self, referred_user_tg_id: int, paid_amount: int):
        """حالت ۱ از سه مدل زیرمجموعه‌گیری: پورسانت درصدی، فقط برای اولین خرید هر
        زیرمجموعه، و در صورت تنظیم بودن سقف (referral_commission_max_count)، فقط برای
        همان تعداد اول از زیرمجموعه‌هایی که خرید کرده‌اند."""
        # کارمزد نماینده‌ی لینک‌محور (بند ۳.۱ اسپک) کاملاً مستقل از سیستم referred_by
        # است و روی هر خرید (نه فقط اولین) اعمال می‌شود؛ همین‌جا صدا زده می‌شود چون
        # این تابع از قبل در تمام نقاط تکمیل سفارش پروژه صدا زده می‌شود.
        self._apply_inline_reseller_commission(referred_user_tg_id, paid_amount)

        # رفع باگ: بات اصلی (main.py)، بک‌اند مینی‌اپ/وب‌هوک‌ها (miniapp/server.py) و
        # پنل ادمین (admin_panel/server.py) سه پروسه‌ی کاملاً جدا هستند که هرکدام
        # instance و قفل پایتونیِ self._lock مستقل خودشان را روی همین یک فایل
        # SQLite دارند - آن قفل فقط داخل همان یک پروسه اثر دارد. قبلاً اینجا ابتدا
        # با یک SELECT جدا خوانده می‌شد که آیا referral_first_purchase_rewarded
        # هنوز صفر است، و بعد یک UPDATE بدون قید روی مقدار قبلی آن را ۱ می‌کرد -
        # دقیقاً همان الگوی دومرحله‌ای بدون قفل که در consume_reseller_credit و
        # approve_topup و claim_order از قبل با UPDATE...WHERE اتمیک بسته شده بود،
        # فقط اینجا جا افتاده بود. اگر دو «اولین خرید» تقریباً هم‌زمان برای یک
        # زیرمجموعه در دو پروسه‌ی مختلف تکمیل می‌شد (مثلاً یکی با وب‌هوک درگاه در
        # مینی‌اپ و دیگری با تایید دستی رسید در پنل ادمین)، هر دو می‌توانستند فلگ
        # را هنوز صفر ببینند و هر دو UPDATE را بزنند - یعنی کارمزد ارجاع دوبار به
        # کیف‌پول معرف واریز می‌شد. الان مثل بقیه‌ی جاهای پروژه، خودِ UPDATE با
        # WHERE referral_first_purchase_rewarded=0 اتمیک است و ادامه‌ی کار
        # (بررسی سقف/واریز کارمزد) فقط وقتی انجام می‌شود که همین فراخوانی واقعاً
        # برنده‌ی این انتقال بوده - یعنی cur.rowcount>0.
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
            if self._is_referral_fraud_suspended(conn, referrer_id):
                return None

            min_amount = int(self.get_setting("referral_min_purchase_amount", "0") or 0)
            if min_amount > 0 and paid_amount < min_amount:
                if self.get_setting("referral_min_purchase_strict", "0") == "1":
                    # حالت سخت‌گیرانه: همین خرید کم‌مبلغ به‌عنوان «اولین خرید» مصرف می‌شود
                    # و دیگر هیچ‌وقت پورسانتی به این زیرمجموعه تعلق نمی‌گیرد.
                    conn.execute(
                        "UPDATE users SET referral_first_purchase_rewarded=1 "
                        "WHERE telegram_id=? AND referral_first_purchase_rewarded=0",
                        (referred_user_tg_id,),
                    )
                # حالت پیش‌فرض (غیرسخت‌گیرانه): فلگ علامت نمی‌خورد، منتظر خرید بعدی که
                # به حداقل برسد می‌مانیم تا همان به‌عنوان «اولین خرید واجد شرایط» حساب شود.
                return None

            max_count = int(self.get_setting("referral_commission_max_count", "0") or 0)
            if max_count > 0:
                already = conn.execute(
                    "SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_first_purchase_rewarded=1",
                    (referrer_id,),
                ).fetchone()["c"]
                if already >= max_count:
                    # سقف پر شده؛ همچنان به‌عنوان «رویدادِ اولین خرید» علامت می‌زنیم تا دوباره
                    # بررسی نشود - ولی چون این هم یک نوشتنِ یک‌باره روی همین فلگ است، همان
                    # قید اتمیک لازم است تا اگر هم‌زمان یک فراخوانی دیگر (پیش از رسیدن به این
                    # شرط) همین ردیف را رد کرده، این یکی رکورد رویداد را دوباره پردازش نکند.
                    cur = conn.execute(
                        "UPDATE users SET referral_first_purchase_rewarded=1 "
                        "WHERE telegram_id=? AND referral_first_purchase_rewarded=0",
                        (referred_user_tg_id,),
                    )
                    if cur.rowcount == 0:
                        return None
                    return None

            cur = conn.execute(
                "UPDATE users SET referral_first_purchase_rewarded=1 "
                "WHERE telegram_id=? AND referral_first_purchase_rewarded=0",
                (referred_user_tg_id,),
            )
            if cur.rowcount == 0:
                # فراخوانیِ هم‌زمانِ دیگری (در همین پروسه یا پروسه‌ی دیگر) همین لحظه برنده شد؛
                # برای جلوگیری از واریز دوبرابرِ کارمزد، اینجا صرف‌نظر می‌کنیم.
                return None

        percent = int(self.get_setting("referral_percent", "10") or 0)
        reward = (paid_amount * percent) // 100
        if reward > 0:
            self.add_wallet_credit(referrer_id, reward, "referral_reward", "پاداش اولین خرید زیرمجموعه")
            return reward, referrer_id
        return None


    def reward_referrer_on_renewal(self, referred_user_tg_id: int, paid_amount: int):
        """پورسانت زیرمجموعه‌گیری روی تمدید سرویس (قابلیت ۶۷): کاملاً مستقل از
        پاداش «اولین خرید» بالا و از فلگ referral_first_purchase_rewarded؛ روی
        هر تمدید سرویسِ زیرمجموعه، تا سقفِ تعداد تنظیم‌شده در
        referral_renewal_max_count (صفر = نامحدود)، درصدی از مبلغ تمدید
        (referral_renewal_percent، صفر = غیرفعال) به کیف‌پول معرف واریز
        می‌شود."""
        if paid_amount <= 0:
            return None
        if self.get_setting("referral_button_enabled", "1") != "1":
            return None
        if self.get_setting("referral_enabled", "1") != "1":
            return None
        percent = int(self.get_setting("referral_renewal_percent", "0") or 0)
        if percent <= 0:
            return None

        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT referred_by, referral_renewal_rewarded_count FROM users WHERE telegram_id=?",
                (referred_user_tg_id,),
            ).fetchone()
            if not row or not row["referred_by"]:
                return None
            referrer_id = row["referred_by"]
            if self._is_referral_fraud_suspended(conn, referrer_id):
                return None

            max_count = int(self.get_setting("referral_renewal_max_count", "0") or 0)
            if max_count > 0 and row["referral_renewal_rewarded_count"] >= max_count:
                return None
            # همان الگوی UPDATE...WHERE اتمیک بالا: جلوگیری از واریز دوبرابر در
            # صورت فراخوانی هم‌زمان از دو پروسه‌ی جدا (بات اصلی / وب‌هوک درگاه‌ها).
            cur = conn.execute(
                "UPDATE users SET referral_renewal_rewarded_count = referral_renewal_rewarded_count + 1 "
                "WHERE telegram_id=? AND (? = 0 OR referral_renewal_rewarded_count < ?)",
                (referred_user_tg_id, max_count, max_count),
            )
            if cur.rowcount == 0:
                return None

        reward = (paid_amount * percent) // 100
        if reward > 0:
            self.add_wallet_credit(referrer_id, reward, "referral_renewal_reward", "پورسانت تمدید سرویس زیرمجموعه")
            return reward, referrer_id
        return None


    def grant_pending_signup_gifts(self) -> list:
        """کاربران واجد شرایط (عضو از حداقل signup_gift_delay_days روز پیش،
        بدون سفارش تاییدشده، بدون هدیه‌ی قبلی) را پیدا و یک‌بار شارژ می‌کند.
        خروجی: [{"user_id":..., "amount":...}, ...] برای اطلاع‌رسانی به همان کاربران."""
        if self.get_setting("signup_gift_enabled", "0") != "1":
            return []
        amount = int(self.get_setting("signup_gift_amount", "0") or 0)
        delay_days = int(self.get_setting("signup_gift_delay_days", "0") or 0)
        if amount <= 0 or delay_days <= 0:
            return []
        cutoff = (datetime.utcnow() - timedelta(days=delay_days)).isoformat()
        granted = []
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT telegram_id FROM users "
                "WHERE COALESCE(signup_gift_given,0)=0 AND COALESCE(is_blocked,0)=0 "
                "AND joined_at IS NOT NULL AND joined_at<=? "
                "AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id=users.telegram_id AND o.status='approved')",
                (cutoff,),
            ).fetchall()
            for row in rows:
                uid = int(row["telegram_id"])
                conn.execute("UPDATE users SET signup_gift_given=1 WHERE telegram_id=?", (uid,))
                with _wallet_tag(conn, uid, "signup_gift", "هدیه‌ی عضویت"):
                    conn.execute(
                        "UPDATE users SET referral_credit=MAX(COALESCE(referral_credit,0)+?, MIN(COALESCE(referral_credit,0),0)) "
                        "WHERE telegram_id=?",
                        (amount, uid),
                    )
                granted.append({"user_id": uid, "amount": amount})
        return granted

    # -----------------------------------------------------------------------
    # هشدار زیرمجموعه‌گیری فیک (بند ۴۳ اسپک): چون تلگرام IP/دستگاه در اختیار
    # ما نمی‌گذارد، تشخیص صرفاً بر رفتار حساب‌ها تکیه دارد - دو معیار مستقل:
    #   ۱) دعوتِ انبوه در یک بازه‌ی زمانی کوتاه (burst)
    #   ۲) نسبت بالای زیرمجموعه‌هایی که هیچ‌وقت خرید نکرده‌اند (invite/free-config
    #      بدون خرید واقعی گرفته شده)
    # با تشخیص هر یک، یک ردیف در referral_fraud_flags ثبت و ادمین‌ها مطلع
    # می‌شوند؛ اگر referral_fraud_auto_suspend فعال باشد، هر سه مدل پاداش رفرال
    # همان دعوت‌کننده تا رفع دستی فلگ توسط ادمین متوقف می‌شود.
    # -----------------------------------------------------------------------


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


    def get_renewal_settings(self) -> dict:
        return {
            "enabled": self.get_setting("renewal_reminder_enabled", "1") == "1",
            "days_before": int(self.get_setting("renewal_reminder_days_before", "5") or 5),
            "discount_percent": int(self.get_setting("renewal_discount_percent", "20") or 20),
            "discount_expiry_hours": int(self.get_setting("renewal_discount_expiry_hours", "24") or 24),
            "cashback_percent": max(0, min(int(self.get_setting("renewal_cashback_percent", "0") or 0), 100)),
        }


    def mark_renewal_reminder_sent(self, config_id: int, sent: int = 1):
        with self._get_conn() as conn:
            conn.execute("UPDATE configs SET renewal_reminder_sent=? WHERE id=?", (int(sent), config_id))


    def get_volume_reminder_settings(self) -> dict:
        return {
            "enabled": self.get_setting("volume_reminder_enabled", "1") == "1",
            "mode": self.get_setting("volume_reminder_mode", "percent"),
            "percent": int(self.get_setting("volume_reminder_percent", "80") or 80),
            "gb_left": float(self.get_setting("volume_reminder_gb_left", "2") or 2),
            "discount_percent": int(self.get_setting("volume_discount_percent", "20") or 20),
            "discount_expiry_hours": int(self.get_setting("volume_discount_expiry_hours", "24") or 24),
        }


    def mark_volume_reminder_sent(self, config_id: int, sent: int = 1):
        with self._get_conn() as conn:
            conn.execute("UPDATE configs SET volume_reminder_sent=? WHERE id=?", (int(sent), config_id))


    def get_connect_alert_settings(self) -> dict:
        return {
            "connect_enabled": self.get_setting("connect_alert_enabled", "0") == "1",
            "connect_threshold_mb": float(self.get_setting("connect_alert_threshold_mb", "1") or 1),
            "connect_text": self.get_setting(
                "connect_alert_text",
                "✅ سرویس شما به کانفیگ متصل شد.",
            ),
            "no_connect_enabled": self.get_setting("no_connect_alert_enabled", "0") == "1",
            "no_connect_hours": int(self.get_setting("no_connect_alert_hours", "24") or 24),
            "no_connect_threshold_mb": float(self.get_setting("no_connect_alert_threshold_mb", "1") or 1),
            "no_connect_text": self.get_setting(
                "no_connect_alert_text",
                "⚠️ هنوز به سرویس خریداری‌شده‌تان متصل نشده‌اید. برای راهنمای اتصال با پشتیبانی در تماس باشید.",
            ),
        }


    def set_connect_alert_settings(self, **kwargs):
        """کلیدهای مجاز: connect_enabled, connect_threshold_mb, connect_text,
        no_connect_enabled, no_connect_hours, no_connect_threshold_mb, no_connect_text."""
        key_map = {
            "connect_enabled": ("connect_alert_enabled", lambda v: "1" if v else "0"),
            "connect_threshold_mb": ("connect_alert_threshold_mb", str),
            "connect_text": ("connect_alert_text", str),
            "no_connect_enabled": ("no_connect_alert_enabled", lambda v: "1" if v else "0"),
            "no_connect_hours": ("no_connect_alert_hours", lambda v: str(int(v))),
            "no_connect_threshold_mb": ("no_connect_alert_threshold_mb", str),
            "no_connect_text": ("no_connect_alert_text", str),
        }
        for field, value in kwargs.items():
            if field not in key_map or value is None:
                continue
            setting_key, caster = key_map[field]
            self.set_setting(setting_key, caster(value))


    def mark_connect_alert_sent(self, config_id: int, is_custom: bool):
        table = "custom_configs" if is_custom else "configs"
        with self._get_conn() as conn:
            conn.execute(f"UPDATE {table} SET connect_alert_sent=1 WHERE id=?", (config_id,))


    def mark_no_connect_alert_sent(self, config_id: int, is_custom: bool):
        table = "custom_configs" if is_custom else "configs"
        with self._get_conn() as conn:
            conn.execute(f"UPDATE {table} SET no_connect_alert_sent=1 WHERE id=?", (config_id,))

    # -----------------------------------------------------------------------
    # تخفیف تمدید کامل زودهنگام («حساب من» ← تمدید کامل سرویس)
    #
    # مستقل از تخفیف تشویقیِ یادآوری‌ها (renewal_discount_percent) است: این
    # یکی به‌صورت خودکار و بدون نیاز به کد، در لحظه‌ی محاسبه‌ی قیمت «تمدید
    # کامل» اعمال می‌شود، فقط اگر تا انقضای واقعی سرویس حداکثر N روز مانده باشد.
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


    def get_service_expiry_notification_candidates(self, now_iso: str):
        """سرویس‌های فعالی که به زمان انقضا رسیده‌اند و هنوز اعلان کانالی نگرفته‌اند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs WHERE status='active' AND duration_days>0 "
                "AND expires_at IS NOT NULL AND expires_at<=? "
                "AND (service_alert_expired_sent_at IS NULL OR service_alert_expired_sent_at='') "
                "ORDER BY expires_at ASC, id ASC",
                (now_iso,),
            ).fetchall()


    def mark_service_expiry_alert_sent(self, custom_config_id: int, at_iso: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET service_alert_expired_sent_at=? "
                "WHERE id=? AND status='active' AND (service_alert_expired_sent_at IS NULL OR service_alert_expired_sent_at='')",
                (at_iso, custom_config_id),
            )
            return cur.rowcount > 0


    def get_cleanup_candidates(self, now_iso: str, warning_since_iso: str = None):
        """سرویس‌های custom/test که برای پاکسازی خودکار بررسی می‌شوند.

        سرویس‌های نامحدود، On-hold (start_on_first_use بدون expires_at) و
        سرویس‌هایی که تمدید خودکارشان فعال است عمداً برگردانده نمی‌شوند.
        """
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs "
                "WHERE status='active' AND duration_days>0 AND expires_at IS NOT NULL "
                "AND expires_at<=? AND COALESCE(auto_renew,0)=0 "
                "AND NOT (COALESCE(start_on_first_use,0)=1 AND expires_at IS NULL) "
                "ORDER BY expires_at ASC, id ASC",
                (now_iso,),
            ).fetchall()


    def get_cleanup_warning_candidates(self, now_iso: str, warning_from_iso: str):
        """سرویس‌هایی که در آستانه حذف هستند و هنوز هشدار نگرفته‌اند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs "
                "WHERE status='active' AND duration_days>0 AND expires_at IS NOT NULL "
                "AND expires_at>? AND expires_at<=? AND COALESCE(auto_renew,0)=0 "
                "AND (cleanup_warning_sent_at IS NULL OR cleanup_warning_sent_at='') "
                "ORDER BY expires_at ASC, id ASC",
                (now_iso, warning_from_iso),
            ).fetchall()


    def mark_cleanup_soft_disabled(self, custom_config_id: int, at_iso: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET enabled=0, cleanup_soft_disabled_at=? "
                "WHERE id=? AND status='active'",
                (at_iso, custom_config_id),
            )
            return cur.rowcount > 0


    def mark_cleanup_warning_sent(self, custom_config_id: int, at_iso: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET cleanup_warning_sent_at=? "
                "WHERE id=? AND status='active'",
                (at_iso, custom_config_id),
            )
            return cur.rowcount > 0


    def mark_cleanup_deleted(self, custom_config_id: int, at_iso: str) -> bool:
        """ثبت حذف منطقی؛ رکورد DB عمداً باقی می‌ماند تا تاریخچه و گزارش حفظ شود."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET status='deleted', enabled=0, cleanup_deleted_at=? "
                "WHERE id=? AND status='active'",
                (at_iso, custom_config_id),
            )
            return cur.rowcount > 0


    def create_bulk_gift_job(self, admin_id, panel_server_id=None, user_ids=None, volume_gb=0, days=0, note=""):
        user_ids = [int(x) for x in (user_ids or [])]
        volume_gb = float(volume_gb or 0)
        days = int(days or 0)
        if volume_gb <= 0 and days <= 0:
            raise ValueError("مقدار هدیه باید حجم یا زمان داشته باشد")
        with self._get_conn() as conn:
            cond = ["cc.status='active'"]
            params = []
            # سرویس‌های تست، هدیه‌ی فروشگاهی نیستند.
            cond.append("COALESCE(cc.source, '') != 'test'")
            if panel_server_id:
                cond.append("cc.panel_server_id=?"); params.append(int(panel_server_id))
            if user_ids:
                marks = ','.join('?' for _ in user_ids)
                cond.append(f"cc.user_id IN ({marks})"); params.extend(user_ids)
            where = ' AND '.join(cond)
            rows = conn.execute(
                f"SELECT cc.id, cc.panel_server_id, cc.user_id, cc.username, cc.start_on_first_use, cc.expires_at "
                f"FROM custom_configs cc WHERE {where} ORDER BY cc.id", params
            ).fetchall()
            if not rows:
                raise ValueError("هیچ سرویس فعالی برای این هدف پیدا نشد")
            payload = json.dumps({"volume_gb": volume_gb, "days": days}, ensure_ascii=False)
            cur = conn.execute(
                "INSERT INTO bulk_gift_jobs(admin_id,panel_server_id,params_json,total,note) VALUES(?,?,?,?,?)",
                (admin_id, panel_server_id, payload, len(rows), note or ""),
            )
            job_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO bulk_gift_items(job_id,custom_config_id,panel_server_id,user_id,username,start_on_first_use,expires_at) VALUES(?,?,?,?,?,?,?)",
                [(job_id, r['id'], r['panel_server_id'], r['user_id'], r['username'], r['start_on_first_use'] or 0, r['expires_at']) for r in rows],
            )
            conn.execute("UPDATE bulk_gift_jobs SET status='running', started_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
            return {"id": job_id, "total": len(rows)}


    def count_bulk_gift_targets(self, panel_server_id=None, user_ids=None) -> int:
        cond = ["cc.status='active'", "COALESCE(cc.source, '') != 'test'"]
        params = []
        if panel_server_id:
            cond.append("cc.panel_server_id=?")
            params.append(int(panel_server_id))
        user_ids = [int(x) for x in (user_ids or [])]
        if user_ids:
            cond.append(f"cc.user_id IN ({','.join('?' for _ in user_ids)})")
            params.extend(user_ids)
        with self._get_conn() as conn:
            row = conn.execute(f"SELECT COUNT(*) c FROM custom_configs cc WHERE {' AND '.join(cond)}", params).fetchone()
        return int(row["c"]) if row else 0


    def get_bulk_gift_job(self, job_id):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM bulk_gift_jobs WHERE id=?", (job_id,)).fetchone()


    def claim_next_bulk_gift_item(self):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT i.* FROM bulk_gift_items i JOIN bulk_gift_jobs j ON j.id=i.job_id "
                "WHERE i.status='pending' AND j.status='running' ORDER BY i.id LIMIT 1"
            ).fetchone()
            if not row:
                # jobs بدون آیتم pending را finalize کن.
                jobs = conn.execute("SELECT id,total,done,failed FROM bulk_gift_jobs WHERE status='running'").fetchall()
                for j in jobs:
                    left = conn.execute("SELECT COUNT(*) c FROM bulk_gift_items WHERE job_id=? AND status='pending'", (j['id'],)).fetchone()['c']
                    if left == 0:
                        conn.execute("UPDATE bulk_gift_jobs SET status='done',finished_at=CURRENT_TIMESTAMP WHERE id=?", (j['id'],))
                return None
            conn.execute("UPDATE bulk_gift_items SET status='processing',claimed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (row['id'],))
            return conn.execute("SELECT * FROM bulk_gift_items WHERE id=?", (row['id'],)).fetchone()


    def apply_bulk_gift_success(self, item_id, custom_config_id, add_volume_gb, add_days, panel_expires_at=None):
        with self._get_conn() as conn:
            item = conn.execute("SELECT * FROM bulk_gift_items WHERE id=?", (item_id,)).fetchone()
            if not item or item['status'] != 'processing':
                return False
            cc = conn.execute("SELECT * FROM custom_configs WHERE id=?", (custom_config_id,)).fetchone()
            if not cc:
                conn.execute("UPDATE bulk_gift_items SET status='failed',error='سرویس دیگر وجود ندارد',completed_at=CURRENT_TIMESTAMP WHERE id=?", (item_id,))
                return False
            now = datetime.utcnow()
            new_exp = cc['expires_at']
            if add_days:
                base = now
                if cc['expires_at']:
                    try:
                        dt = datetime.fromisoformat(cc['expires_at'])
                        if dt > now: base = dt
                    except ValueError: pass
                new_exp = (base + timedelta(days=int(add_days))).isoformat()
            new_volume = (cc['volume_gb'] or 0) + float(add_volume_gb or 0)
            # اگر provider تاریخ معتبر برگرداند، همان مرجع اصلی است.
            if panel_expires_at:
                new_exp = panel_expires_at
            conn.execute(
                "UPDATE custom_configs SET volume_gb=?, expires_at=?, "
                "renewal_reminder_sent=CASE WHEN ? THEN 0 ELSE renewal_reminder_sent END, "
                "volume_reminder_sent=CASE WHEN ? THEN 0 ELSE volume_reminder_sent END WHERE id=?",
                (new_volume, new_exp, int(bool(add_days) or bool(panel_expires_at)), int(bool(add_volume_gb)), custom_config_id),
            )
            conn.execute("UPDATE bulk_gift_items SET status='done',completed_at=CURRENT_TIMESTAMP WHERE id=?", (item_id,))
            conn.execute("UPDATE bulk_gift_jobs SET done=done+1 WHERE id=?", (item['job_id'],))
        self.add_custom_config_history(custom_config_id, "gift", f"هدیه گروهی: +{add_volume_gb:g} گیگ / +{add_days} روز")
        return True


    def fail_bulk_gift_item(self, item_id, error):
        with self._get_conn() as conn:
            row = conn.execute("SELECT job_id,status FROM bulk_gift_items WHERE id=?", (item_id,)).fetchone()
            if not row or row['status'] in ('done','failed'):
                return False
            conn.execute("UPDATE bulk_gift_items SET status='failed',error=?,completed_at=CURRENT_TIMESTAMP WHERE id=?", (error[:500], item_id))
            conn.execute("UPDATE bulk_gift_jobs SET failed=failed+1 WHERE id=?", (row['job_id'],))
            return True


    def list_bulk_gift_jobs(self, limit=10):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM bulk_gift_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


    def cancel_bulk_gift_job(self, job_id):
        with self._get_conn() as conn:
            cur=conn.execute("UPDATE bulk_gift_jobs SET status='cancelled',finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'", (job_id,))
            if cur.rowcount:
                conn.execute("UPDATE bulk_gift_items SET status='failed',error='عملیات توسط ادمین لغو شد',completed_at=CURRENT_TIMESTAMP WHERE job_id=? AND status IN ('pending','processing')", (job_id,))
            return cur.rowcount > 0

    # -----------------------------------------------------------------------
    # تغییر لوکیشن سرویس
    # -----------------------------------------------------------------------


    def get_location_transfer_targets(self, current_panel_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM panel_servers WHERE is_active=1 AND allow_transfer_target=1 AND id<>? ORDER BY id",
                (current_panel_id,),
            ).fetchall()


    def get_location_transfer_policy(self, user_tg_id: int, target_panel_id: int) -> dict:
        limit = int(self.get_setting("location_change_user_limit", "0") or 0)
        free_quota = int(self.get_setting("location_change_free_quota", "0") or 0)
        with self._get_conn() as conn:
            user = conn.execute(
                "SELECT location_change_count, referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            panel = conn.execute("SELECT * FROM panel_servers WHERE id=?", (target_panel_id,)).fetchone()
            free_used = conn.execute(
                "SELECT COUNT(*) AS c FROM location_change_log WHERE status='completed' AND fee_toman=0"
            ).fetchone()["c"]
        if not user or not panel:
            return {"ok": False, "reason": "not_found"}
        count = int(user["location_change_count"] or 0)
        if limit > 0 and count >= limit:
            return {"ok": False, "reason": "user_limit", "limit": limit, "count": count}
        price = max(0, int(panel["transfer_price"] or 0))
        is_free = free_quota > 0 and free_used < free_quota
        if is_free:
            price = 0
        return {
            "ok": True, "price": price, "base_price": max(0, int(panel["transfer_price"] or 0)),
            "is_free": is_free, "free_used": free_used, "free_quota": free_quota,
            "count": count, "limit": limit, "balance": int(user["referral_credit"] or 0),
        }


    def reserve_location_transfer(self, custom_config_id: int, user_tg_id: int, old_panel_id: int,
                                  new_panel_id: int, base_price: int, old_username: str = None,
                                  old_volume_gb: int = None, old_expires_at: str = None, old_subscription_url: str = None) -> dict:
        """رزرو اتمیک انتقال: سهمیه/کیف پول و رکورد pending را همزمان قفل می‌کند."""
        limit = int(self.get_setting("location_change_user_limit", "0") or 0)
        free_quota = int(self.get_setting("location_change_free_quota", "0") or 0)
        with self._get_conn() as conn:
            user = conn.execute(
                "SELECT location_change_count, referral_credit FROM users WHERE telegram_id=?", (user_tg_id,)
            ).fetchone()
            if not user:
                return {"ok": False, "reason": "user_not_found"}
            count = int(user["location_change_count"] or 0)
            if limit > 0 and count >= limit:
                return {"ok": False, "reason": "user_limit", "limit": limit, "count": count}
            free_used = conn.execute(
                "SELECT COUNT(*) AS c FROM location_change_log WHERE status='completed' AND fee_toman=0"
            ).fetchone()["c"]
            fee = max(0, int(base_price or 0))
            if free_quota > 0 and free_used < free_quota:
                fee = 0
            if fee > 0:
                with _wallet_tag(conn, user_tg_id, "location_fee", "هزینه‌ی تغییر لوکیشن سرویس"):
                    cur = conn.execute(
                        "UPDATE users SET referral_credit=referral_credit-?, location_change_count=COALESCE(location_change_count,0)+1 "
                        "WHERE telegram_id=? AND referral_credit>=? AND COALESCE(location_change_count,0)<?",
                        (fee, user_tg_id, fee, limit if limit > 0 else 2147483647),
                    )
            else:
                cur = conn.execute(
                    "UPDATE users SET location_change_count=COALESCE(location_change_count,0)+1 WHERE telegram_id=? "
                    "AND COALESCE(location_change_count,0)<?",
                    (user_tg_id, limit if limit > 0 else 2147483647),
                )
            if cur.rowcount != 1:
                return {"ok": False, "reason": "insufficient_balance" if fee > 0 else "user_limit"}
            cur = conn.execute(
                "INSERT INTO location_change_log(custom_config_id,user_id,old_panel_server_id,new_panel_server_id,fee_toman,status,old_username,old_volume_gb,old_expires_at,old_subscription_url) "
                "VALUES(?,?,?,?,?,'pending',?,?,?,?)",
                (custom_config_id, user_tg_id, old_panel_id, new_panel_id, fee, old_username, old_volume_gb, old_expires_at, old_subscription_url),
            )
            return {"ok": True, "log_id": cur.lastrowid, "fee": fee, "is_free": fee == 0, "count": count + 1, "limit": limit}


    def update_location_transfer_local_pending(self, log_id: int, custom_config_id: int, new_username: str,
                                               subscription_url: str, new_volume_gb: int, new_expires_at: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM location_change_log WHERE id=? AND status='pending'", (log_id,)).fetchone()
            if not row:
                return False
            cur = conn.execute(
                "UPDATE custom_configs SET panel_server_id=?, username=?, subscription_url=?, volume_gb=?, expires_at=?, "
                "renewal_reminder_sent=0, volume_reminder_sent=0 "
                "WHERE id=? AND user_id=? AND status='active'",
                (row["new_panel_server_id"], new_username, subscription_url, int(new_volume_gb), new_expires_at, custom_config_id, row["user_id"]),
            )
            return cur.rowcount == 1


    def complete_location_transfer(self, log_id: int, custom_config_id: int, new_username: str,
                                   new_volume_gb: int, new_expires_at: str, detail: str = None,
                                   subscription_url: str = None) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM location_change_log WHERE id=? AND status='pending'", (log_id,)).fetchone()
            if not row:
                return False
            cur = conn.execute(
                "UPDATE custom_configs SET panel_server_id=?, username=?, subscription_url=?, volume_gb=?, expires_at=?, "
                "renewal_reminder_sent=0, volume_reminder_sent=0 "
                "WHERE id=? AND user_id=? AND status='active'",
                (row["new_panel_server_id"], new_username, subscription_url, int(new_volume_gb), new_expires_at, custom_config_id, row["user_id"]),
            )
            if cur.rowcount != 1:
                return False
            conn.execute(
                "UPDATE location_change_log SET status='completed',new_username=?,new_volume_gb=?,new_expires_at=?,completed_at=CURRENT_TIMESTAMP,detail=? WHERE id=?",
                (new_username, int(new_volume_gb), new_expires_at, detail, log_id),
            )
            return True


    def set_location_transfer_subscription(self, custom_config_id: int, log_id: int, subscription_url: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET subscription_url=? WHERE id=?", (subscription_url, custom_config_id))
            conn.execute("UPDATE location_change_log SET detail=COALESCE(detail,'') || ? WHERE id=?", (" | لینک مقصد ثبت شد", log_id))


    def rollback_location_transfer(self, log_id: int, reason: str = None) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM location_change_log WHERE id=? AND status IN ('pending','completed')", (log_id,)).fetchone()
            if not row:
                return False
            if row["fee_toman"] > 0:
                with _wallet_tag(conn, row["user_id"], "location_refund", "بازگشت هزینه‌ی تغییر لوکیشن"):
                    conn.execute("UPDATE users SET referral_credit=COALESCE(referral_credit,0)+? WHERE telegram_id=?", (row["fee_toman"], row["user_id"]))
            conn.execute("UPDATE users SET location_change_count=MAX(COALESCE(location_change_count,0)-1,0) WHERE telegram_id=?", (row["user_id"],))
            conn.execute(
                "UPDATE custom_configs SET panel_server_id=?, username=?, subscription_url=?, volume_gb=COALESCE(?,volume_gb), expires_at=? "
                "WHERE id=? AND user_id=?",
                (row["old_panel_server_id"], row["old_username"], row["old_subscription_url"], row["old_volume_gb"], row["old_expires_at"], row["custom_config_id"], row["user_id"]),
            )
            conn.execute("UPDATE location_change_log SET status='rolled_back',detail=? WHERE id=?", (reason or "rollback", log_id))
            return True


    def finalize_location_transfer_local(self, log_id: int, custom_config_id: int, new_username: str,
                                         subscription_url: str, new_volume_gb: int, new_expires_at: str,
                                         detail: str = None) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM location_change_log WHERE id=? AND status='pending'", (log_id,)).fetchone()
            if not row:
                return False
            cur = conn.execute(
                "UPDATE custom_configs SET panel_server_id=?, username=?, subscription_url=?, volume_gb=?, expires_at=?, "
                "renewal_reminder_sent=0, volume_reminder_sent=0 WHERE id=? AND user_id=? AND status='active'",
                (row["new_panel_server_id"], new_username, subscription_url, int(new_volume_gb), new_expires_at, custom_config_id, row["user_id"]),
            )
            if cur.rowcount != 1:
                return False
            conn.execute(
                "UPDATE location_change_log SET status='completed',new_username=?,new_volume_gb=?,new_expires_at=?,completed_at=CURRENT_TIMESTAMP,detail=? WHERE id=?",
                (new_username, int(new_volume_gb), new_expires_at, detail, log_id),
            )
            return True

    # -----------------------------------------------------------------------
    # تاریخچه‌ی سرویس (custom_config_history)
    # -----------------------------------------------------------------------


    def rate_service(self, user_tg_id: int, custom_config_id: int, panel_server_id, rating: int):
        """ثبت/به‌روزرسانی امتیاز ۱ تا ۵ کاربر برای یک سرویس (هر کاربر برای هر سرویس فقط یک امتیاز دارد)."""
        rating = max(1, min(5, int(rating)))
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO service_ratings (user_id, custom_config_id, panel_server_id, rating, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, custom_config_id) DO UPDATE SET "
                "rating=excluded.rating, panel_server_id=excluded.panel_server_id, updated_at=CURRENT_TIMESTAMP",
                (user_tg_id, custom_config_id, panel_server_id, rating),
            )


    def get_service_rating(self, user_tg_id: int, custom_config_id: int):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT rating FROM service_ratings WHERE user_id=? AND custom_config_id=?",
                (user_tg_id, custom_config_id),
            ).fetchone()
            return row["rating"] if row else None

