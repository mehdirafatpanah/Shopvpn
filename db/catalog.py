# -*- coding: utf-8 -*-
from .constants import *

class CatalogMixin:
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

    RESELLER_TIER_DEFAULTS = (
        {
            "code": "bronze", "title": "برنزی", "icon": "🥉", "model": "commission", "sort_order": 10,
            "membership_fee_toman": 0, "duration_days": 30,
            "summary": "کمیسیون از خرید مشتری‌ها",
            "description": "لینک اختصاصی می‌گیرید و از هر خرید مشتریانی که با لینک شما وارد شوند، درصدی کمیسیون به کیف پولتان اضافه می‌شود. بدون سرمایه اولیه.",
        },
        {
            "code": "silver", "title": "نقره‌ای", "icon": "🥈", "model": "discount", "sort_order": 20, "is_enabled": 1,
            "membership_fee_toman": 0, "duration_days": 30,
            "summary": "تخفیف دائمی و خرید عمده در بات اصلی",
            "description": "بدون لینک و بدون بات؛ از خود بات اصلی با قیمت تخفیفی می‌خرید و هرچه یک‌جا بیشتر بخرید، تخفیف بیشتر می‌شود.",
        },
        {
            "code": "gold", "title": "طلایی", "icon": "🥇", "model": "fixed_product", "sort_order": 30,
            "membership_fee_toman": 0, "duration_days": 30,
            "has_miniapp": 1, "has_web_panel": 1, "has_dedicated_bot": 1,
            "summary": "فروشگاه شخصی با خرید عمده‌ی محصولات ما",
            "description": "پنل وب، مینی‌اپ و بات مستقل اختصاصی دارید. محصولات فروشگاه را عمده و پیش‌پرداخت می‌خرید و همان‌ها را می‌فروشید.",
        },
        {
            "code": "vip", "title": "VIP", "icon": "👑", "model": "volume_credit", "sort_order": 40,
            "membership_fee_toman": 0, "duration_days": 30,
            "has_miniapp": 1, "has_web_panel": 1, "has_dedicated_bot": 1,
            "summary": "فروشگاه شخصی با اعتبار حجمی آزاد",
            "description": "پنل وب، مینی‌اپ و بات مستقل اختصاصی دارید. یک استخر حجم می‌خرید و هر محصولی را با هر قیمتی خودتان می‌سازید.",
        },
    )

    RESELLER_TIER_TEXT_FIELDS = ("title", "icon", "summary", "description")
    RESELLER_TIER_FLAG_FIELDS = ("is_enabled", "has_miniapp", "has_web_panel", "has_dedicated_bot", "auto_approve")
    RESELLER_TIER_INT_FIELDS = ("sort_order", "commission_min", "commission_max", "permanent_discount_percent", "min_qty", "min_volume_gb", "membership_fee_toman", "duration_days", "credit_limit_toman")
    RESELLER_TIER_NULLABLE_FIELDS = ("commission_min", "commission_max", "permanent_discount_percent", "min_qty", "min_volume_gb", "duration_days")
    RESELLER_TIER_PERCENT_FIELDS = ("commission_min", "commission_max", "permanent_discount_percent")


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


    def get_user_custom_configs(self, tg_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM custom_configs WHERE user_id=? ORDER BY id DESC", (tg_id,)).fetchall()


    def get_user_ids_without_config(self):
        """قابلیت ۸۸: آیدی کاربرانی که الان هیچ کانفیگی ندارند - نه از بانک
        کانفیگ‌های محصولات (configs.assigned_user_id؛ با حذف کانفیگ ردیفش کاملاً
        از این جدول پاک می‌شود، پس صرف وجود یعنی الان مالک آن است)، نه یک
        کانفیگ شخصی فعال (custom_configs.status='active'). برای پیام همگانی
        هدفمند به کاربرانی که هیچ‌وقت خرید نکرده‌اند یا سرویسشان دیگر فعال
        نیست - جهت ترغیب به خرید."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT u.telegram_id AS uid FROM users u "
                "WHERE u.is_blocked=0 "
                "AND NOT EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id) "
                "AND NOT EXISTS (SELECT 1 FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.status='active')"
            ).fetchall()
            return [r["uid"] for r in rows]


    def get_user_ids_with_inactive_config(self):
        """قابلیت ۸۹: آیدی کاربرانی که یک کانفیگ غیرفعال دارند - یعنی واقعاً یک
        کانفیگ (از بانک محصول یا سرویس شخصی) مال خودشان بوده و الان غیرفعال/
        منقضی/لغوشده است؛ برخلاف «بدون کانفیگ» که کسانی را هم شامل می‌شود که
        اصلاً هیچ‌وقت کانفیگی نداشته‌اند. برای پیام همگانی هدفمند جهت ترغیب به
        تمدید/تفعال مجدد."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT u.telegram_id AS uid FROM users u "
                "WHERE u.is_blocked=0 AND ("
                "EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_disabled=1) "
                "OR EXISTS (SELECT 1 FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.status IN ('expired','cancelled'))"
                ")"
            ).fetchall()
            return [r["uid"] for r in rows]


    def add_category(self, name: str) -> int:
        def op():
            with self._get_conn() as conn:
                cur = conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
                return cur.lastrowid
        return self._sqlite_retry(op)


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


    def preview_bulk_price_change(self, category_id=None, panel_server_id=None, mode="percent", value=0, rounding=0):
        """پیش‌نمایش و محاسبه‌ی قیمت‌های جدید. mode: percent یا fixed؛ value در percent می‌تواند منفی باشد."""
        params=[]; where=[]
        if category_id is not None:
            where.append("p.category_id=?"); params.append(category_id)
        if panel_server_id is not None:
            where.append("p.provision_server_id=?"); params.append(panel_server_id)
        sql="SELECT p.id,p.name,p.price,p.category_id,p.provision_server_id FROM products p"
        if where: sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.id"
        with self._get_conn() as conn:
            rows=conn.execute(sql, params).fetchall()
        out=[]
        for r in rows:
            old=int(r["price"] or 0)
            if mode == "percent":
                new=round(old * (100 + float(value)) / 100)
            else:
                new=old + int(value)
            if rounding:
                unit=abs(int(rounding)); new=int(round(new/unit)*unit)
            new=max(0,new)
            out.append({"id":r["id"],"name":r["name"],"old_price":old,"new_price":new,
                        "category_id":r["category_id"],"provision_server_id":r["provision_server_id"]})
        return out


    def apply_bulk_price_change(self, changes, scope="products"):
        """اعمال اتمیک تغییر قیمت و ثبت snapshot کامل برای undo."""
        if not changes: return None
        payload=json.dumps(changes, ensure_ascii=False)
        with self._get_conn() as conn:
            cur=conn.execute("INSERT INTO price_change_log(scope,payload_json) VALUES(?,?)", (scope,payload))
            log_id=cur.lastrowid
            for ch in changes:
                conn.execute("UPDATE products SET price=? WHERE id=?", (int(ch["new_price"]), int(ch["id"])))
            return log_id


    def list_price_change_logs(self, limit=10):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM price_change_log WHERE undone_at IS NULL ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()


    def undo_bulk_price_change(self, log_id):
        with self._get_conn() as conn:
            row=conn.execute("SELECT * FROM price_change_log WHERE id=? AND undone_at IS NULL", (log_id,)).fetchone()
            if not row: return False
            changes=json.loads(row["payload_json"] or "[]")
            for ch in changes:
                conn.execute("UPDATE products SET price=? WHERE id=?", (int(ch["old_price"]), int(ch["id"])))
            conn.execute("UPDATE price_change_log SET undone_at=CURRENT_TIMESTAMP WHERE id=?", (log_id,))
            return True


    def add_product(self, category_id: int, name: str, price: int, description: str = "", duration_days: int = 30,
                     is_auto_provision: bool = False, auto_provision_volume_gb: int = None,
                     provision_server_id: int = None, payment_methods=None,
                     base_users: int = 0, extra_user_price: int = 0, max_users: int = 0) -> int:
        """payment_methods: None/[] یعنی «همه‌ی روش‌های پرداخت مجازند» (پیش‌فرض)،
        در غیر این صورت لیستی از کلیدهای مجاز - همان قراردادِ set_product_payment_methods.

        base_users/extra_user_price/max_users: محدودیت کاربر همزمان (فقط محصولات خودکار).
        base_users=0 یعنی بدون محدودیت؛ ارتقا فقط وقتی فعال است که extra_user_price>0 و
        max_users>base_users باشد."""
        pm_value = json.dumps(payment_methods, ensure_ascii=False) if payment_methods else None
        base_users = max(int(base_users or 0), 0) if is_auto_provision else 0
        extra_user_price = max(int(extra_user_price or 0), 0)
        max_users = max(int(max_users or 0), 0)
        if not base_users or extra_user_price <= 0 or max_users <= base_users:
            extra_user_price, max_users = 0, 0
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO products (category_id, name, price, description, duration_days, "
                "is_auto_provision, auto_provision_volume_gb, provision_server_id, payment_methods, "
                "base_users, extra_user_price, max_users) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (category_id, name, price, description, duration_days,
                 1 if is_auto_provision else 0, auto_provision_volume_gb, provision_server_id, pm_value,
                 base_users, extra_user_price, max_users),
            )
            return cur.lastrowid


    def get_products(self, category_id: int, active_only=True):
        with self._get_conn() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM products WHERE category_id=? AND is_active=1 ORDER BY sort_order, id",
                    (category_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM products WHERE category_id=? ORDER BY sort_order, id", (category_id,)
                ).fetchall()
            return rows


    def get_all_products(self):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT p.*, c.name as category_name FROM products p "
                "JOIN categories c ON p.category_id=c.id ORDER BY c.sort_order, p.sort_order, p.id"
            ).fetchall()


    def reorder_products(self, category_id: int, product_ids: list):
        """قابلیت #253: ترتیب نمایش محصولات یک دسته را دقیقاً مطابق لیست شناسه‌ها ذخیره می‌کند."""
        ids = [int(x) for x in (product_ids or [])]
        if len(ids) != len(set(ids)):
            raise ValueError("شناسه‌های محصولات تکراری هستند.")
        with self._get_conn() as conn:
            rows = conn.execute("SELECT id FROM products WHERE category_id=?", (category_id,)).fetchall()
            existing = {int(r["id"]) for r in rows}
            if set(ids) != existing:
                raise ValueError("فهرست محصولات کامل نیست یا شامل محصول نامعتبر است.")
            for order, product_id in enumerate(ids):
                conn.execute("UPDATE products SET sort_order=? WHERE id=?", (order, product_id))


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
                      is_auto_provision=..., auto_provision_volume_gb=...,
                      provision_server_id=..., payment_methods=..., category_id: int = None):
        # نکته: is_auto_provision/auto_provision_volume_gb/provision_server_id از سنتینل
        # Ellipsis استفاده می‌کنند (مثل payment_methods) چون باید بتوان آن‌ها را عمداً
        # NULL/False کرد (مثلاً وقتی محصول از «اتصال مستقیم به پنل» به «بانک کانفیگ»
        # برمی‌گردد) و این با pattern قبلیِ «None یعنی بدون تغییر» فرق دارد.
        fields, values = [], []
        if category_id is not None:
            fields.append("category_id=?"); values.append(category_id)
        if name is not None:
            fields.append("name=?"); values.append(name)
        if price is not None:
            fields.append("price=?"); values.append(price)
        if description is not None:
            fields.append("description=?"); values.append(description)
        if duration_days is not None:
            fields.append("duration_days=?"); values.append(duration_days)
        if is_auto_provision is not ...:
            fields.append("is_auto_provision=?"); values.append(1 if is_auto_provision else 0)
        if auto_provision_volume_gb is not ...:
            fields.append("auto_provision_volume_gb=?"); values.append(auto_provision_volume_gb)
        if provision_server_id is not ...:
            fields.append("provision_server_id=?"); values.append(provision_server_id)
        if payment_methods is not ...:
            fields.append("payment_methods=?")
            values.append(json.dumps(payment_methods, ensure_ascii=False) if payment_methods else None)
        if not fields:
            return
        values.append(product_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE products SET {', '.join(fields)} WHERE id=?", values)


    def set_product_user_limit(self, product_id: int, extra_user_price: int, max_users: int,
                               base_users: int = None):
        """base_users=None: ستون base_users دست نمی‌خورد (رفتار قدیمی).
        base_users=0: محدودیت کاربر کاملاً غیرفعال. base_users>=1: تعداد ثابتِ گنجانده‌شده در قیمت پایه."""
        extra_user_price = max(int(extra_user_price or 0), 0)
        max_users = max(int(max_users or 0), 0)
        floor = 1
        if base_users is not None:
            base_users = max(int(base_users or 0), 0)
            floor = max(base_users, 1)
        if extra_user_price <= 0 or max_users < 2 or max_users <= floor:
            extra_user_price, max_users = 0, 0
        with self._get_conn() as conn:
            if base_users is None:
                conn.execute(
                    "UPDATE products SET extra_user_price=?, max_users=? WHERE id=?",
                    (extra_user_price, max_users, product_id),
                )
            else:
                conn.execute(
                    "UPDATE products SET extra_user_price=?, max_users=?, base_users=? WHERE id=?",
                    (extra_user_price, max_users, base_users, product_id),
                )


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


    def get_auto_provision_max_qty(self) -> int:
        try:
            return max(0, int(self.get_setting("auto_provision_max_qty", "0") or 0))
        except (TypeError, ValueError):
            return 0


    def count_available_configs(self, product_id: int) -> int:
        cap = self.get_auto_provision_max_qty()
        with self._get_conn() as conn:
            prod = conn.execute(
                "SELECT is_auto_provision FROM products WHERE id=?", (product_id,)
            ).fetchone()
            if prod and prod["is_auto_provision"]:
                return cap or AUTO_PROVISION_UNLIMITED_STOCK
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


    def get_orphan_config_stats(self):
        """F147: شمارش رکوردهای کانفیگ بدون مرجع معتبر.

        برای بانک کانفیگ و بانک تست، رکورد زمانی یتیم است که کاربر اختصاص‌یافته
        وجود نداشته باشد یا محصول مرجع حذف شده باشد. برای custom_configs فقط
        رکوردهای غیر فعالِ بدون کاربر، قابل حذف خودکار محسوب می‌شوند؛ سرویس فعال
        ممکن است هنوز روی پنل VPN وجود داشته باشد و نباید صرفاً با حذف DB جا بماند.
        """
        with self._get_conn() as conn:
            bank = conn.execute("""
                SELECT COUNT(*) c FROM configs c
                LEFT JOIN users u ON u.telegram_id = c.assigned_user_id
                LEFT JOIN products p ON p.id = c.product_id
                WHERE (c.assigned_user_id IS NOT NULL AND u.telegram_id IS NULL)
                   OR p.id IS NULL
            """).fetchone()["c"]
            test = conn.execute("""
                SELECT COUNT(*) c FROM test_configs c
                LEFT JOIN users u ON u.telegram_id = c.assigned_user_id
                WHERE c.assigned_user_id IS NOT NULL AND u.telegram_id IS NULL
            """).fetchone()["c"]
            custom_inactive = conn.execute("""
                SELECT COUNT(*) c FROM custom_configs c
                LEFT JOIN users u ON u.telegram_id = c.user_id
                WHERE u.telegram_id IS NULL AND COALESCE(c.status, '') <> 'active'
            """).fetchone()["c"]
            custom_active = conn.execute("""
                SELECT COUNT(*) c FROM custom_configs c
                LEFT JOIN users u ON u.telegram_id = c.user_id
                WHERE u.telegram_id IS NULL AND COALESCE(c.status, '') = 'active'
            """).fetchone()["c"]
        return {"configs": bank, "test_configs": test, "custom_inactive": custom_inactive, "custom_active_review": custom_active}


    def delete_orphan_configs(self):
        """F147: حذف یتیم‌های امن از بانک کانفیگ/تست و سرویس‌های custom غیرفعال."""
        with self._get_conn() as conn:
            bank = conn.execute("""
                DELETE FROM configs
                WHERE (assigned_user_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM users u WHERE u.telegram_id = configs.assigned_user_id
                ))
                   OR NOT EXISTS (SELECT 1 FROM products p WHERE p.id = configs.product_id)
            """).rowcount
            test = conn.execute("""
                DELETE FROM test_configs
                WHERE assigned_user_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM users u WHERE u.telegram_id = test_configs.assigned_user_id
                )
            """).rowcount
            custom = conn.execute("""
                DELETE FROM custom_configs
                WHERE COALESCE(status, '') <> 'active'
                  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.telegram_id = custom_configs.user_id)
            """).rowcount
        return {"configs": bank, "test_configs": test, "custom_configs": custom}


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


    def get_used_configs(self, product_id: int):
        """کانفیگ‌های تحویل‌شده (ناموجود/غیرقابل‌فروش) این محصول، برای نمایش و
        حذف دستی از همان صفحه‌ی «بانک کانفیگ» محصول (نه فقط از پروفایل کاربر)."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id, link, assigned_user_id, assigned_at FROM configs "
                "WHERE product_id=? AND is_used=1 ORDER BY assigned_at DESC, id DESC",
                (product_id,),
            ).fetchall()


    def delete_config(self, config_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM configs WHERE id=? AND is_used=0", (config_id,))

    # ------------------------------------------------------- admin: کانفیگ‌های بانکیِ یک کاربر --
    # مدیریت کانفیگ‌های «بانک محصول» (جدول configs) که به یک کاربر خاص اختصاص
    # یافته‌اند، از سمت ادمین (مینی‌اپ ← مدیریت کاربران): مشاهده‌ی لینک‌ها،
    # غیرفعال/فعال کردن نمایش لینک به کاربر، و حذف کامل - معادل قابلیت‌هایی که
    # پیش‌تر فقط برای «سرویس‌های مستقیم-پنل» (custom_configs) وجود داشت.


    def log_config_activity(self, config_id: int, action: str, details: str = "", user_id: int = None):
        """ثبت آخرین رخداد مهم مربوط به یک کانفیگ بانکی برای نمایش جزئیات فعالیت."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO config_activity (config_id, user_id, action, details) VALUES (?, ?, ?, ?)",
                (config_id, user_id, action, details or ""),
            )


    def get_config_activity(self, config_id: int, limit: int = 20):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id, config_id, user_id, action, details, created_at "
                "FROM config_activity WHERE config_id=? ORDER BY id DESC LIMIT ?",
                (config_id, max(1, min(int(limit or 20), 100))),
            ).fetchall()


    def get_last_config_activity(self, config_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id, config_id, user_id, action, details, created_at "
                "FROM config_activity WHERE config_id=? ORDER BY id DESC LIMIT 1",
                (config_id,),
            ).fetchone()


    def get_bank_configs_for_user(self, tg_id: int):
        """همه‌ی کانفیگ‌های بانکی که تا امروز به این کاربر اختصاص یافته (چه هنوز
        فعال باشند چه قبلاً توسط ادمین غیرفعال/از او گرفته نشده باشند)."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT cf.*, p.name AS product_name, o.id AS order_display_id "
                "FROM configs cf "
                "LEFT JOIN products p ON p.id = cf.product_id "
                "LEFT JOIN orders o ON o.id = cf.order_id "
                "WHERE cf.assigned_user_id = ? "
                "ORDER BY cf.assigned_at DESC, cf.id DESC",
                (tg_id,),
            ).fetchall()


    def set_config_disabled(self, config_id: int, disabled: bool):
        """غیرفعال/فعال کردن اداری یک کانفیگ بانکی توسط ادمین. این کار خودِ لینک
        را از کار نمی‌اندازد (کانفیگ‌های بانکی برخلاف سرویس‌های مستقیم-پنل به
        هیچ پنلی متصل نیستند که بشود رویش API زد)؛ فقط باعث می‌شود لینک دیگر در
        بات/مینی‌اپ به کاربر نمایش داده نشود."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE configs SET is_disabled=? WHERE id=?",
                (1 if disabled else 0, config_id),
            )
            row = conn.execute("SELECT assigned_user_id FROM configs WHERE id=?", (config_id,)).fetchone()
            conn.execute(
                "INSERT INTO config_activity (config_id, user_id, action, details) VALUES (?, ?, ?, ?)",
                (config_id, row["assigned_user_id"] if row else None, "disabled" if disabled else "enabled",
                 "غیرفعال شد" if disabled else "فعال شد"),
            )


    def admin_delete_bank_config(self, config_id: int):
        """حذف کامل و برگشت‌ناپذیر یک کانفیگ بانکی توسط ادمین (برخلاف
        delete_owned_config نیازی به تطابق مالکیت ندارد و برخلاف delete_config
        محدود به کانفیگ‌های استفاده‌نشده نیست). اگر سفارش مربوطه بعد از این
        حذف دیگر هیچ کانفیگی نداشته باشد، از لیست «سفارش‌های من» همان کاربر
        (نه گزارش‌های ادمین) مخفی می‌شود - دقیقاً مثل delete_owned_config."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM configs WHERE id=?", (config_id,)).fetchone()
            if not row:
                return None
            order_id = row["order_id"]
            assigned_user_id = row["assigned_user_id"]
            conn.execute("DELETE FROM configs WHERE id=?", (config_id,))
            if order_id and assigned_user_id:
                remaining = conn.execute(
                    "SELECT COUNT(*) c FROM configs WHERE order_id=?", (order_id,)
                ).fetchone()["c"]
                if remaining == 0:
                    conn.execute(
                        "UPDATE orders SET user_deleted=1 WHERE id=? AND user_id=?",
                        (order_id, assigned_user_id),
                    )
            return dict(row)


    def take_unused_config(self, product_id: int, user_tg_id: int):
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
            cur = conn.execute(
                "UPDATE configs SET is_used=1, assigned_user_id=?, assigned_at=?, expires_at=?, "
                "renewal_reminder_sent=0, volume_reminder_sent=0 WHERE id=? AND is_used=0",
                (user_tg_id, now.isoformat(), expires_at, row["id"]),
            )
            if cur.rowcount != 1:
                return None
            self.log_config_activity(
                row["id"], "assigned",
                f"اختصاص کانفیگ به کاربر {user_tg_id}؛ انقضا: {expires_at}", user_tg_id,
            )
            return {"id": row["id"], "link": row["link"], "expires_at": expires_at}


    def take_unused_configs(self, product_id: int, user_tg_id: int, quantity: int = 1):
        """مثل take_unused_config ولی چند کانفیگ را یکجا برمی‌دارد. اگر موجودی کافی
        نباشد، هیچ کانفیگی مصرف نمی‌شود و None برمی‌گردد."""
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
                cur = conn.execute(
                    "UPDATE configs SET is_used=1, assigned_user_id=?, assigned_at=?, expires_at=?, "
                    "renewal_reminder_sent=0, volume_reminder_sent=0 WHERE id=? AND is_used=0",
                    (user_tg_id, now.isoformat(), expires_at, row["id"]),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
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
        tier_discount_amount: int = 0,
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
                "custom_product_id, custom_duration_days, tier_discount_amount) "
                "VALUES (?, 0, 'pending', ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?)",
                (user_tg_id, base_price, wallet_used, final_price, volume_gb, username, panel_server_id,
                 custom_product_id, custom_duration_days, tier_discount_amount),
            )
            return cur.lastrowid


    def approve_custom_config_order(self, order_id: int) -> bool:
        """فقط اگر سفارش pending یا processing (بعد از claim_order) باشد اعمال می‌شود."""
        purchase_points = self.get_score_points("purchase")
        coin_days = self.get_coin_settings()["expiry_days"]
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='approved', updated_at=? WHERE id=? AND status IN ('pending','processing')",
                (datetime.utcnow().isoformat(), order_id),
            )
            if cur.rowcount:
                self._award_order_score(conn, order_id, purchase_points, coin_days)
            return cur.rowcount > 0


    def get_order_configs(self, order_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM configs WHERE order_id=? ORDER BY id", (order_id,)
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


    def delete_owned_custom_config(self, custom_config_id: int, user_tg_id: int, refund_amount: int = 0):
        """حذف کامل و برگشت‌ناپذیر یک کانفیگ شخصی متعلق به همین کاربر. فقط ردیف
        دیتابیس را حذف می‌کند؛ حذف واقعی کاربر از روی پنل VPN (در صورت وجود
        panel_server_id) باید قبل از فراخوانی این متد و جداگانه انجام شود.
        اگر با این حذف، سفارشی که این کانفیگ از آن بود دیگر هیچ کانفیگ شخصی
        دیگری نداشته باشد، آن سفارش هم از لیست «سفارش‌های من» کاربر (بات و
        مینی‌اپ) مخفی می‌شود - دقیقاً مثل delete_owned_config برای کانفیگ‌های
        بانکی (بدون این‌که از دیتابیس یا گزارش‌های ادمین حذف شود)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM custom_configs WHERE id=? AND user_id=?", (custom_config_id, user_tg_id)
            ).fetchone()
            if not row:
                return None
            order_id = row["order_id"]
            conn.execute("DELETE FROM custom_configs WHERE id=?", (custom_config_id,))
            if refund_amount and refund_amount > 0:
                with _wallet_tag(conn, user_tg_id, "service_refund", f"بازگشت وجه حذف سرویس {row['username']}"):
                    conn.execute(
                        "UPDATE users SET referral_credit = MAX(COALESCE(referral_credit,0) + ?, MIN(COALESCE(referral_credit,0), 0)) "
                        "WHERE telegram_id=?",
                        (int(refund_amount), user_tg_id),
                    )
            if order_id:
                remaining = conn.execute(
                    "SELECT COUNT(*) c FROM custom_configs WHERE order_id=?", (order_id,)
                ).fetchone()["c"]
                if remaining == 0:
                    conn.execute(
                        "UPDATE orders SET user_deleted=1 WHERE id=? AND user_id=?", (order_id, user_tg_id)
                    )
            return dict(row)

    # -----------------------------------------------------------------------
    # آمار
    # -----------------------------------------------------------------------


    def get_configs_due_for_renewal_reminder(self):
        """کانفیگ‌های فعال را همراه با پرچم sent (یادآوری قبلاً ارسال شده یا نه) برمی‌گرداند.

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
                "cf.renewal_reminder_sent as sent, "
                "p.id as product_id, p.name as product_name "
                "FROM configs cf JOIN products p ON cf.product_id = p.id "
                "WHERE cf.is_used=1 "
                "AND cf.link IS NOT NULL AND TRIM(cf.link) != ''"
            ).fetchall()


    def get_custom_configs_due_for_renewal_reminder(self):
        """معادل get_configs_due_for_renewal_reminder برای کانفیگ‌هایی که مستقیم
        از پنل VPN ساخته شده‌اند (خرید شخصی/نمایندگی/کانفیگ تست پنلی)."""
        settings = self.get_renewal_settings()
        if not settings["enabled"]:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id as config_id, subscription_url as link, user_id as assigned_user_id, "
                "renewal_reminder_sent as sent, username as product_name "
                "FROM custom_configs "
                "WHERE status='active' AND source != 'test' "
                "AND subscription_url IS NOT NULL AND TRIM(subscription_url) != ''"
            ).fetchall()


    def mark_custom_config_renewal_reminder_sent(self, config_id: int, sent: int = 1):
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET renewal_reminder_sent=? WHERE id=?", (int(sent), config_id))


    def get_configs_due_for_volume_reminder(self):
        """کانفیگ‌های فعال را همراه با پرچم sent (یادآوری حجم قبلاً ارسال شده یا نه) برمی‌گرداند.

        آستانه‌ی واقعی (درصد/گیگ) از روی مصرف زنده‌ی Subscription در
        renewal_reminders.py بررسی می‌شود؛ اینجا فقط کاندیدها فیلتر می‌شوند.
        """
        settings = self.get_volume_reminder_settings()
        if not settings["enabled"]:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT cf.id as config_id, cf.link, cf.assigned_user_id, "
                "cf.volume_reminder_sent as sent, "
                "p.id as product_id, p.name as product_name "
                "FROM configs cf JOIN products p ON cf.product_id = p.id "
                "WHERE cf.is_used=1 "
                "AND cf.link IS NOT NULL AND TRIM(cf.link) != ''"
            ).fetchall()


    def get_custom_configs_due_for_volume_reminder(self):
        """معادل get_configs_due_for_volume_reminder برای کانفیگ‌های ساخته‌شده
        مستقیم روی پنل VPN."""
        settings = self.get_volume_reminder_settings()
        if not settings["enabled"]:
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id as config_id, subscription_url as link, user_id as assigned_user_id, "
                "volume_reminder_sent as sent, username as product_name "
                "FROM custom_configs "
                "WHERE status='active' AND source != 'test' "
                "AND subscription_url IS NOT NULL AND TRIM(subscription_url) != ''"
            ).fetchall()


    def mark_custom_config_volume_reminder_sent(self, config_id: int, sent: int = 1):
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET volume_reminder_sent=? WHERE id=?", (int(sent), config_id))


    def get_configs_due_for_connect_check(self):
        """کانفیگ‌های فعال بدون هشدار اتصال/عدم‌اتصال ارسال‌شده (انبار کانفیگ ثابت)."""
        settings = self.get_connect_alert_settings()
        if not (settings["connect_enabled"] or settings["no_connect_enabled"]):
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT cf.id as config_id, cf.link, cf.assigned_user_id, cf.assigned_at, "
                "cf.connect_alert_sent, cf.no_connect_alert_sent, "
                "p.name as product_name "
                "FROM configs cf JOIN products p ON cf.product_id = p.id "
                "WHERE cf.is_used=1 AND cf.assigned_user_id IS NOT NULL "
                "AND (cf.connect_alert_sent=0 OR cf.no_connect_alert_sent=0) "
                "AND cf.link IS NOT NULL AND TRIM(cf.link) != ''"
            ).fetchall()


    def get_custom_configs_due_for_onhold_sync(self):
        """سرویس‌های On-hold که هنوز تاریخ انقضای واقعی‌شان از پنل ثبت نشده است."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id as config_id, username, panel_server_id "
                "FROM custom_configs WHERE status='active' AND start_on_first_use=1 "
                "AND expires_at IS NULL AND subscription_url IS NOT NULL "
                "AND TRIM(subscription_url) != ''"
            ).fetchall()


    def get_custom_configs_due_for_connect_check(self):
        """معادل بالا برای کانفیگ‌های ساخته‌شده مستقیم روی پنل VPN."""
        settings = self.get_connect_alert_settings()
        if not (settings["connect_enabled"] or settings["no_connect_enabled"]):
            return []
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT id as config_id, subscription_url as link, user_id as assigned_user_id, "
                "created_at as assigned_at, connect_alert_sent, no_connect_alert_sent, "
                "COALESCE(display_name, username) as product_name, username, panel_server_id, start_on_first_use "
                "FROM custom_configs "
                "WHERE status='active' AND source != 'test' "
                "AND (connect_alert_sent=0 OR no_connect_alert_sent=0) "
                "AND subscription_url IS NOT NULL AND TRIM(subscription_url) != ''"
            ).fetchall()


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
                           product_id: int = None, start_on_first_use: bool = None,
                           reseller_product_id: int = None, user_limit: int = None) -> int:
        """source: 'custom_config' (خرید شخصی)، 'test' (کانفیگ تست پنلی)، یا 'reseller'.
        duration_days=0 یعنی سرویس نامحدود/بدون انقضاست؛ در این حالت expires_at
        خالی (NULL) می‌ماند تا همه‌جا به‌صورت «نامحدود» نمایش داده شود. product_id
        به custom_config_products اشاره می‌کند (NULL برای مسیر سراسری قدیمی)."""
        if start_on_first_use is None:
            with self._get_conn() as conn:
                server_row = conn.execute(
                    "SELECT start_on_first_use FROM panel_servers WHERE id=?", (panel_server_id,)
                ).fetchone()
            start_on_first_use = bool(server_row and server_row["start_on_first_use"])
        if expires_at is None and duration_days and not start_on_first_use:
            expires_at = (datetime.utcnow() + timedelta(days=duration_days)).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO custom_configs (order_id, user_id, panel_server_id, username, volume_gb, "
                "duration_days, subscription_url, expires_at, source, product_id, start_on_first_use, reseller_product_id, "
                "user_limit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, user_id, panel_server_id, username, volume_gb, duration_days, subscription_url,
                 expires_at, source, product_id, int(bool(start_on_first_use)), reseller_product_id, user_limit),
            )
            new_id = cur.lastrowid
        self.add_custom_config_history(new_id, "purchase", f"{volume_gb} گیگ / {duration_days} روز")
        return new_id


    def sync_custom_config_expiry(self, custom_config_id: int, expires_at: str) -> bool:
        """پس از اولین مصرف، تاریخ انقضای واقعی برگشتی از پنل را در DB ثبت می‌کند."""
        if not expires_at:
            return False
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE custom_configs SET expires_at=? WHERE id=? AND status='active' AND start_on_first_use=1",
                (expires_at, custom_config_id),
            )
            return cur.rowcount > 0


    def get_inactive_custom_configs_for_scheduled_delete(self):
        """F138: کانفیگ‌های فعالِ ثبت‌شده که عمداً غیرفعال شده‌اند.

        سرویس‌هایی که توسط F14 به‌صورت soft-disable شده‌اند از این فهرست حذف می‌شوند
        تا مهلت حذف F14 دور زده نشود.
        """
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs "
                "WHERE status='active' AND COALESCE(enabled,1)=0 "
                "AND cleanup_soft_disabled_at IS NULL "
                "ORDER BY id ASC"
            ).fetchall()


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


    def get_custom_config_by_id(self, custom_config_id: int):
        """مثل get_custom_config_owned ولی بدون فیلتر مالکیت - فقط برای سمت
        ادمین (پنل وب) که باید بتواند سرویس هر کاربری را مدیریت کند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs WHERE id=?", (custom_config_id,)
            ).fetchone()


    def apply_custom_config_renewal(self, custom_config_id: int, add_volume_gb: int = 0, add_days: int = 0,
                                     full_reset: bool = False, set_volume_gb: float = None) -> dict:
        """بعد از موفقیت‌آمیز بودن به‌روزرسانی روی خودِ پنل (provider.update_user)،
        رکورد بوکینگ محلی (حجم/مدت/تاریخ انقضا) را هم‌سو با آن به‌روز می‌کند.
        set_volume_gb (اختیاری): اگر داده شود، همان مقدار دقیقاً به‌عنوان سقف جدید
        ثبت می‌شود - برای زمانی که فراخوان (renewal_engine) مقدار واقعیِ سقفِ
        محاسبه‌شده روی خود پنل را از قبل می‌داند (مثلاً حاصل از preserve_remaining
        در تمدید کامل) و نمی‌خواهیم اینجا دوباره و به‌شکلی متفاوت محاسبه شود.
        در غیر این صورت (set_volume_gb داده نشده): full_reset=True یعنی «تمدید
        کامل» بدون حفظ باقیمانده - حجم رکورد محلی هم با بستهٔ تازه جایگزین
        می‌شود، نه رویش جمع بزند."""
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
            if set_volume_gb is not None:
                new_volume = set_volume_gb
            elif add_volume_gb:
                new_volume = add_volume_gb if full_reset else (row["volume_gb"] or 0) + add_volume_gb
            else:
                new_volume = row["volume_gb"]
            new_duration = (row["duration_days"] or 0) + add_days if add_days else row["duration_days"]
            rearm_time = bool(add_days) or full_reset
            rearm_volume = bool(add_volume_gb) or set_volume_gb is not None or full_reset
            conn.execute(
                "UPDATE custom_configs SET volume_gb=?, duration_days=?, expires_at=?, "
                "renewal_reminder_sent=CASE WHEN ? THEN 0 ELSE renewal_reminder_sent END, "
                "volume_reminder_sent=CASE WHEN ? THEN 0 ELSE volume_reminder_sent END WHERE id=?",
                (new_volume, new_duration, new_expires_at, int(rearm_time), int(rearm_volume), custom_config_id),
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
            conn.execute(
                "UPDATE configs SET expires_at=?, renewal_reminder_sent=0 WHERE id=?",
                (new_expires_at, config_id),
            )
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
    # هدیه‌ی گروهی حجم/زمان
    # -----------------------------------------------------------------------


    def set_custom_config_user_limit(self, custom_config_id: int, users: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET user_limit=? WHERE id=?", (int(users), custom_config_id))
        self.add_custom_config_history(custom_config_id, "users", f"{int(users)} کاربر همزمان")


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
    # امتیازدهی به سرویس (سنجش کیفیت هر پنل/لوکیشن)
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
                "AND (start_on_first_use=0 OR expires_at IS NOT NULL) "
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

