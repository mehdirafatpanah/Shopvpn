# -*- coding: utf-8 -*-
from .constants import *

class UsersMixin:
    def get_user_language(self, tg_id: int) -> str:
        with self._get_conn() as conn:
            row = conn.execute("SELECT language_code FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
        code = (row["language_code"] if row and row["language_code"] else "fa")
        try:
            from i18n import is_language_enabled, normalize_language
            code = normalize_language(code)
            if not is_language_enabled(self, code):
                return "fa"
        except Exception:
            return "fa"
        return code

    def set_user_language(self, tg_id: int, language_code: str) -> bool:
        from i18n import normalize_language
        lang = normalize_language(language_code)
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE users SET language_code=? WHERE telegram_id=?",
                (lang, tg_id),
            )
        return cur.rowcount > 0

    def set_all_users_language(self, language_code: str) -> int:
        """زبان همه‌ی کاربران ربات را یک‌جا تغییر می‌دهد (نه فقط ادمین درخواست‌دهنده).
        برای استفاده‌ی مدیر از پنل مدیریت وقتی بخواهد زبان را برای همه‌ی
        کاربران عوض کند، نه فقط برای خودش. تعداد ردیف‌های تغییریافته را برمی‌گرداند."""
        from i18n import normalize_language
        lang = normalize_language(language_code)
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE users SET language_code=? WHERE language_code IS NULL OR language_code<>?",
                (lang, lang),
            )
        return cur.rowcount or 0

    def set_user_phone(self, tg_id: int, phone: str) -> bool:
        phone = (phone or "").strip()
        if len(phone) < 7:
            return False
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET phone_number=?, phone_verified=1 WHERE telegram_id=?", (phone, tg_id))
        return True


    def is_phone_verified(self, tg_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT phone_verified FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
        return bool(row and row["phone_verified"])


    def add_or_update_user(self, tg_id: int, username: str, first_name: str):
        # این تابع به‌ازای *هر* پیام/کلیک هر کاربری صدا زده می‌شود (از
        # BlockedUserMiddleware)، یعنی داغ‌ترین مسیر کل دیتابیس است. قبلاً یک
        # SELECT جدا برای تشخیص وجود کاربر + یک UPDATE/INSERT جدا (دو رفت‌وبرگشت
        # به دیسک) بود؛ با UPSERT تک‌کوئری، هم مدت باز نگه‌داشتن قفل نوشتن کم
        # می‌شود و هم به‌طور کلی سریع‌تر است - بدون تغییر در رفتار (فیلدهای
        # دیگر همچنان مقدار پیش‌فرض جدول را در حالت INSERT می‌گیرند).
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?) "
                "ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
                (tg_id, username, first_name),
            )


    def get_user(self, tg_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()


    def set_user_blocked(self, tg_id: int, blocked: bool):
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET is_blocked=? WHERE telegram_id=?", (1 if blocked else 0, tg_id))


    def search_users(self, query: str = "", status_filter: str = "all", limit: int = 30, offset: int = 0, sort: str = "newest"):
        """جستجو/فیلتر کاربران برای پنل مدیریت.
        status_filter: 'all' | 'active' | 'expired' | 'blocked'
        sort: 'newest' | 'balance' (بیشترین موجودی کیف پول) | 'purchase' (بیشترین میزان خرید تاییدشده)
              | 'active_services' (بیشترین تعداد سرویس فعال) | 'topup' (بیشترین میزان شارژ حساب تاییدشده)
        خروجی: (rows, total_count) — هر ردیف ستون‌های total_purchase، active_services و total_topup هم دارد.
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
        if sort == "balance":
            order_by = "COALESCE(u.referral_credit, 0) DESC, u.id DESC"
        elif sort == "purchase":
            order_by = "total_purchase DESC, u.id DESC"
        elif sort == "active_services":
            order_by = "active_services DESC, u.id DESC"
        elif sort == "topup":
            order_by = "total_topup DESC, u.id DESC"
        else:
            order_by = "u.id DESC"
        with self._get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) c FROM users u {where}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT u.*, "
                "(SELECT COALESCE(SUM(COALESCE(o.final_price, p.price)),0) FROM orders o "
                "JOIN products p ON o.product_id=p.id "
                "WHERE o.user_id=u.telegram_id AND o.status='approved') AS total_purchase, "
                "((SELECT COUNT(*) FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1 "
                "AND (c.expires_at IS NULL OR c.expires_at > ?)) + "
                "(SELECT COUNT(*) FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.status='active' "
                "AND cc.source != 'test')) AS active_services, "
                "(SELECT COALESCE(SUM(wt.amount),0) FROM wallet_topups wt "
                "WHERE wt.user_id=u.telegram_id AND wt.status='approved') AS total_topup "
                f"FROM users u {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
                [now] + params + [limit, offset],
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


    def find_user_by_identifier(self, identifier: str):
        """پیدا کردن کاربر با آیدی عددی تلگرام یا یوزرنیم (با یا بدون @)."""
        identifier = (identifier or "").strip().lstrip("@")
        if not identifier:
            return None
        with self._get_conn() as conn:
            if identifier.isdigit():
                row = conn.execute(
                    "SELECT * FROM users WHERE telegram_id=?", (int(identifier),)
                ).fetchone()
                if row:
                    return row
            return conn.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE", (identifier,)
            ).fetchone()


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


    def get_all_user_ids(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id FROM users WHERE is_blocked=0").fetchall()
            return [r["telegram_id"] for r in rows]


    def get_user_ids_without_recent_purchase(self, days: int):
        """قابلیت ۱۶۱: آیدی کاربرانی که حداقل یک سفارش تاییدشده دارند ولی در N
        روز اخیر هیچ سفارش تاییدشده‌ی جدیدی ثبت نکرده‌اند؛ برای پیام همگانی
        هدفمند جهت ترغیب کاربران قدیمیِ راکد به بازگشت (مشابه منطق churn در
        گزارش تحلیلی، اینجا برای هدف‌گیری پیام همگانی)."""
        days = max(1, int(days or 30))
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT o.user_id AS uid FROM orders o "
                "JOIN users u ON u.telegram_id = o.user_id "
                "WHERE o.status='approved' AND u.is_blocked=0 "
                "AND o.user_id NOT IN ("
                "  SELECT user_id FROM orders WHERE status='approved' AND datetime(created_at) >= datetime('now', ?)"
                ")",
                (f"-{days} days",),
            ).fetchall()
            return [r["uid"] for r in rows]


    def count_users(self):
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


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


    def is_full_access_bot(self, is_main_bot: bool = True) -> bool:
        """Whether this bot has the near-main feature set.

        The real main bot is always full-access.  A dedicated reseller bot is
        also full-access because it is a 99%-copy of the main bot with one
        intentional exception: it must never be able to create/manage another
        full reseller.  Older reseller databases are recognized by their
        ``miniapp_tenant_id`` marker; newer ones may also use ``bot_role``.
        """
        if is_main_bot:
            return True
        try:
            role = self.get_setting("bot_role", "")
            if role == "full_reseller":
                return True
            return bool(self.get_setting("miniapp_tenant_id", ""))
        except Exception:
            return False


    def update_user_profile(self, user_tg_id: int, first_name: str = None, username: str = None):
        fields=[]; values=[]
        if first_name is not None:
            fields.append("first_name=?"); values.append(first_name)
        if username is not None:
            fields.append("username=?"); values.append(username)
        if not fields: return
        values.append(user_tg_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE telegram_id=?", values)


    def get_owner_telegram_id(self):
        """آیدی تلگرام مالک این بات (نقش owner در جدول admins). برای بات نمایندگی
        همان کسی است که این بات را می‌گرداند - جهت اتصال به اعتبار حجمی‌اش در بات اصلی."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT telegram_id FROM admins WHERE role='owner' LIMIT 1").fetchone()
            return row["telegram_id"] if row else None


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

    # --------------------- اپ موبایل: توکن دسترسی طولانی‌مدت (PAT) ---------------------


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


    def set_referred_by(self, user_tg_id: int, referrer_tg_id: int):
        if user_tg_id == referrer_tg_id:
            return
        referral_points = self.get_score_points("referral")
        coin_days = self.get_coin_settings()["expiry_days"]
        with self._get_conn() as conn:
            row = conn.execute("SELECT referred_by FROM users WHERE telegram_id=?", (user_tg_id,)).fetchone()
            if row and row["referred_by"] is None:
                referrer_exists = conn.execute(
                    "SELECT 1 FROM users WHERE telegram_id=?", (referrer_tg_id,)
                ).fetchone()
                if referrer_exists:
                    cur = conn.execute(
                        "UPDATE users SET referred_by=? WHERE telegram_id=? AND referred_by IS NULL", (referrer_tg_id, user_tg_id)
                    )
                    if cur.rowcount:
                        self._grant_coins(conn, referrer_tg_id, referral_points, coin_days)

    # -------------------------------------------------------------------
    # نمایندگی با «لینک اختصاصی داخل بات اصلی» (بند ۳.۱ اسپک)
    # -------------------------------------------------------------------


    def reward_referral_uplines(self, referred_user_tg_id: int, paid_amount: int) -> list:
        """پرداخت پاداش رفرال سطح ۲ و ۳ برای اولین خرید زیرمجموعه."""
        if paid_amount <= 0 or self.get_setting("referral_button_enabled", "1") != "1" or self.get_setting("referral_multilevel_enabled", "0") != "1":
            return []
        percentages = {2: int(self.get_setting("referral_level2_percent", "0") or 0), 3: int(self.get_setting("referral_level3_percent", "0") or 0)}
        out = []
        with self._get_conn() as conn:
            row = conn.execute("SELECT referred_by FROM users WHERE telegram_id=?", (referred_user_tg_id,)).fetchone()
            current = row["referred_by"] if row else None
            conn.execute("""CREATE TABLE IF NOT EXISTS referral_multilevel_rewards (referred_user_id INTEGER NOT NULL, referrer_id INTEGER NOT NULL, level INTEGER NOT NULL, amount INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(referred_user_id, level))""")
            for level in (2, 3):
                if not current: break
                percent = max(0, min(100, percentages[level]))
                if percent > 0:
                    amount = (paid_amount * percent) // 100
                    if amount > 0:
                        cur = conn.execute("INSERT OR IGNORE INTO referral_multilevel_rewards(referred_user_id,referrer_id,level,amount) VALUES(?,?,?,?)", (referred_user_tg_id,current,level,amount))
                        if cur.rowcount:
                            with _wallet_tag(conn, current, "referral_reward", f"پاداش زیرمجموعه سطح {level}"):
                                conn.execute("UPDATE users SET referral_credit=MAX(referral_credit+?, MIN(referral_credit,0)) WHERE telegram_id=?", (amount,current))
                            out.append({"level":level,"referrer_id":current,"amount":amount})
                nxt = conn.execute("SELECT referred_by FROM users WHERE telegram_id=?", (current,)).fetchone()
                current = nxt["referred_by"] if nxt else None
        return out


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
            if self._is_referral_fraud_suspended(conn, referrer_tg_id):
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
                    with _wallet_tag(conn, referrer_tg_id, "referral_invite", "پاداش دعوت"):
                        conn.execute(
                            "UPDATE users SET referral_credit = MAX(referral_credit + ?, MIN(referral_credit, 0)) WHERE telegram_id=?",
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
    # هدیه‌ی عضویت (بند ۴۶ اسپک): جذب کاربر تازه‌وارد با یک شارژ یک‌باره‌ی کیف
    # پول، اگر بعد از X روز از عضویتش هنوز هیچ خریدی نکرده باشد. برخلاف پاداش‌
    # های رفرال، این مستقیماً به خودِ کاربر (نه دعوت‌کننده‌اش) تعلق می‌گیرد و
    # نیاز به هیچ دعوتی ندارد - فقط یک حلقه‌ی دوره‌ای (signup_gift.py) این تابع
    # را صدا می‌زند.
    # -----------------------------------------------------------------------


    @staticmethod
    def _is_referral_fraud_suspended(conn, referrer_id: int) -> bool:
        row = conn.execute(
            "SELECT referral_fraud_suspended FROM users WHERE telegram_id=?", (referrer_id,)
        ).fetchone()
        return bool(row and row["referral_fraud_suspended"])


    def is_referral_fraud_suspended(self, referrer_id: int) -> bool:
        with self._get_conn() as conn:
            return self._is_referral_fraud_suspended(conn, referrer_id)


    def get_referral_fraud_signals(self, referrer_id: int) -> dict:
        """محاسبه‌ی معیارهای تشخیص برای یک دعوت‌کننده، بدون هیچ نوشتنی."""
        burst_minutes = int(self.get_setting("referral_fraud_burst_minutes", "60") or 60)
        with self._get_conn() as conn:
            invited_total = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE referred_by=?", (referrer_id,)
            ).fetchone()["c"]
            burst_count = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE referred_by=? "
                "AND joined_at >= datetime('now', ?)",
                (referrer_id, f"-{burst_minutes} minutes"),
            ).fetchone()["c"]
            zero_purchase_count = conn.execute(
                "SELECT COUNT(*) c FROM users u WHERE u.referred_by=? "
                "AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved')",
                (referrer_id,),
            ).fetchone()["c"]
        zero_purchase_ratio = int(round((zero_purchase_count * 100) / invited_total)) if invited_total else 0
        return {
            "invited_total": invited_total,
            "burst_count": burst_count,
            "burst_minutes": burst_minutes,
            "zero_purchase_count": zero_purchase_count,
            "zero_purchase_ratio": zero_purchase_ratio,
        }


    def check_referral_fraud(self, referrer_id: int):
        """بعد از هر دعوت تازه صدا زده می‌شود. اگر الگوی مشکوک تازه‌ای تشخیص داده
        شود یک ردیف در referral_fraud_flags می‌سازد (و در صورت فعال بودن auto_suspend
        پاداش‌های این دعوت‌کننده را متوقف می‌کند) و دیکشنری فلگ را برمی‌گرداند؛
        در غیر این صورت None. تا وقتی یک فلگ باز (resolved=0) برای این دعوت‌کننده
        وجود دارد، دوباره هشدار تکراری ساخته نمی‌شود."""
        if self.get_setting("referral_fraud_detection_enabled", "1") != "1":
            return None
        with self._get_conn() as conn:
            already_open = conn.execute(
                "SELECT 1 FROM referral_fraud_flags WHERE referrer_id=? AND resolved=0", (referrer_id,)
            ).fetchone()
            if already_open:
                return None

        signals = self.get_referral_fraud_signals(referrer_id)
        burst_threshold = int(self.get_setting("referral_fraud_burst_count", "5") or 5)
        min_invites = int(self.get_setting("referral_fraud_min_invites", "5") or 5)
        ratio_threshold = int(self.get_setting("referral_fraud_zero_purchase_ratio", "80") or 80)

        reasons = []
        if signals["burst_count"] >= burst_threshold:
            reasons.append(
                f"دعوت انبوه: {signals['burst_count']} زیرمجموعه‌ی تازه در {signals['burst_minutes']} دقیقه‌ی اخیر"
            )
        if signals["invited_total"] >= min_invites and signals["zero_purchase_ratio"] >= ratio_threshold:
            reasons.append(
                f"نرخ بی‌خریدی بالا: {signals['zero_purchase_count']} از {signals['invited_total']} "
                f"زیرمجموعه ({signals['zero_purchase_ratio']}٪) هیچ خریدی نکرده‌اند"
            )
        if not reasons:
            return None

        auto_suspend = self.get_setting("referral_fraud_auto_suspend", "1") == "1"
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO referral_fraud_flags "
                "(referrer_id, reason, invited_total, zero_purchase_count, burst_count) "
                "VALUES (?,?,?,?,?)",
                (referrer_id, "؛ ".join(reasons), signals["invited_total"], signals["zero_purchase_count"], signals["burst_count"]),
            )
            flag_id = cur.lastrowid
            if auto_suspend:
                conn.execute(
                    "UPDATE users SET referral_fraud_suspended=1 WHERE telegram_id=?", (referrer_id,)
                )
        return {
            "id": flag_id,
            "referrer_id": referrer_id,
            "reason": "؛ ".join(reasons),
            "auto_suspended": auto_suspend,
            **signals,
        }


    def list_referral_fraud_flags(self, resolved: bool = False, limit: int = 100):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT f.*, u.username, u.first_name FROM referral_fraud_flags f "
                "LEFT JOIN users u ON u.telegram_id=f.referrer_id "
                "WHERE f.resolved=? ORDER BY f.id DESC LIMIT ?",
                (1 if resolved else 0, max(int(limit), 1)),
            ).fetchall()


    def resolve_referral_fraud_flag(self, flag_id: int, admin_id: int = None, unsuspend: bool = True):
        """اتمیک: فقط یک بار قابل رفع است. در صورت موفقیت، اگر unsuspend=True و
        دیگر فلگ باز دیگری برای همین دعوت‌کننده نمانده باشد، توقف پاداش او هم
        برداشته می‌شود؛ ردیف رفع‌شده برگردانده می‌شود، وگرنه None."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE referral_fraud_flags SET resolved=1, resolved_by=?, resolved_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND resolved=0",
                (admin_id, flag_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM referral_fraud_flags WHERE id=?", (flag_id,)).fetchone()
            if unsuspend and row:
                still_open = conn.execute(
                    "SELECT 1 FROM referral_fraud_flags WHERE referrer_id=? AND resolved=0",
                    (row["referrer_id"],),
                ).fetchone()
                if not still_open:
                    conn.execute(
                        "UPDATE users SET referral_fraud_suspended=0 WHERE telegram_id=?",
                        (row["referrer_id"],),
                    )
            return row

    # -----------------------------------------------------------------------
    # کدهای تخفیف
    # -----------------------------------------------------------------------


    def is_admin_online(self, tg_id: int, timeout_seconds: int = None) -> bool:
        return tg_id in self.get_online_admin_ids(timeout_seconds)

    # -----------------------------------------------------------------------
    # پیام‌های موقت (خودحذف‌شونده بعد از مدت مشخص)
    # -----------------------------------------------------------------------


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

