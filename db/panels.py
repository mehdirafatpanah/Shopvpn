# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from .constants import *

class PanelsMixin:
    def get_user_ids_by_panel_server(self, panel_server_id: int):
        """آیدی کاربرانی که سرویس فعال (custom_configs) روی یک سرور پنل خاص دارند؛
        برای پیام همگانی هدفمند به کاربران یک سرور خاص."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT cc.user_id AS uid FROM custom_configs cc "
                "JOIN users u ON u.telegram_id = cc.user_id "
                "WHERE cc.panel_server_id=? AND cc.status='active' AND u.is_blocked=0",
                (int(panel_server_id),),
            ).fetchall()
            return [r["uid"] for r in rows]


    def _order_panel_server_id(self, conn, order):
        """پنلی که سرویس این سفارش روی آن ساخته یا تمدید شده؛ برای بانک کانفیگ None."""
        row = conn.execute(
            "SELECT panel_server_id FROM custom_configs WHERE order_id=? ORDER BY id LIMIT 1", (order["id"],)
        ).fetchone()
        if row:
            return row["panel_server_id"]
        if order["custom_panel_server_id"]:
            return order["custom_panel_server_id"]
        if order["is_renewal"] and order["renewal_target_kind"] == "custom":
            row = conn.execute(
                "SELECT panel_server_id FROM custom_configs WHERE id=?", (order["renewal_target_id"],)
            ).fetchone()
            return row["panel_server_id"] if row else None
        if order["product_id"]:
            row = conn.execute("SELECT provision_server_id FROM products WHERE id=?", (order["product_id"],)).fetchone()
            return row["provision_server_id"] if row else None
        return None


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


    def add_panel_server(self, name: str, panel_type: str, api_url: str,
                          api_username: str, api_password: str, default_group: str = None,
                          panel_category_id: int = None) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM panel_servers WHERE is_mirror=0 OR is_mirror IS NULL").fetchone()
            sort_order = int(row["m"] or -1) + 1
            cur = conn.execute(
                "INSERT INTO panel_servers (name, panel_type, api_url, api_username, api_password, default_group, sort_order, panel_category_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, panel_type, api_url.rstrip("/"), api_username, api_password, default_group, sort_order,
                 int(panel_category_id) if panel_category_id else None),
            )
            return cur.lastrowid


    def update_panel_server(self, server_id: int, **fields):
        allowed = {"name", "panel_type", "api_url", "api_username", "api_password",
                   "default_group", "is_active", "template_username", "group_ids", "proxy_settings",
                   "socks_proxy",
                   "used_for_custom_config", "used_for_test_config", "used_for_reseller", "start_on_first_use",
                   "max_services", "capacity_alert_sent", "transfer_price", "allow_transfer_target",
                   "xui_inbound_id", "xui_inbound_ids", "xui_sub_base_url", "xui_sub_base_urls", "sort_order",
                   "geo_cc", "geo_city", "geo_city_fa", "geo_lat", "geo_lon", "geo_manual", "panel_category_id",
                   "naming_mode", "naming_prefix", "naming_suffix"}
        sets, values = [], []
        for k, v in fields.items():
            if k == "panel_category_id" and v in ("", 0, "0"):
                v = None
                sets.append("panel_category_id=NULL")
                continue
            if k in allowed and (v is not None or k == "max_services"):
                sets.append(f"{k}=?")
                values.append(v.rstrip("/") if k == "api_url" else v)
        if not sets:
            return
        values.append(server_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE panel_servers SET {', '.join(sets)} WHERE id=?", values)


    def next_panel_naming_counter(self, server_id: int) -> int:
        with self._get_conn() as conn:
            conn.execute("UPDATE panel_servers SET naming_counter=COALESCE(naming_counter, 0)+1 WHERE id=?", (server_id,))
            row = conn.execute("SELECT naming_counter FROM panel_servers WHERE id=?", (server_id,)).fetchone()
            return int(row["naming_counter"] or 1) if row else 1

    def reset_panel_naming_counter(self, server_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE panel_servers SET naming_counter=0 WHERE id=?", (server_id,))

    # --------------------------- دسته‌بندی پنل‌ها ---------------------------

    def get_panel_categories(self):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM panel_categories ORDER BY sort_order, id").fetchall()

    def get_panel_category(self, cat_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM panel_categories WHERE id=?", (cat_id,)).fetchone()

    def add_panel_category(self, name: str) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM panel_categories").fetchone()
            order = int(row["m"] if row["m"] is not None else -1) + 1
            return conn.execute("INSERT INTO panel_categories (name, sort_order) VALUES (?, ?)", (name, order)).lastrowid

    def edit_panel_category(self, cat_id: int, name: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE panel_categories SET name=? WHERE id=?", (name, cat_id))

    def delete_panel_category(self, cat_id: int) -> bool:
        with self._get_conn() as conn:
            conn.execute("UPDATE panel_servers SET panel_category_id=NULL WHERE panel_category_id=?", (cat_id,))
            return conn.execute("DELETE FROM panel_categories WHERE id=?", (cat_id,)).rowcount > 0

    def move_panel_category(self, cat_id: int, direction: str) -> bool:
        with self._get_conn() as conn:
            ids = [int(r["id"]) for r in conn.execute("SELECT id FROM panel_categories ORDER BY sort_order, id").fetchall()]
            if int(cat_id) not in ids:
                return False
            i = ids.index(int(cat_id))
            j = i - 1 if direction == "up" else i + 1
            if j < 0 or j >= len(ids):
                return False
            ids[i], ids[j] = ids[j], ids[i]
            for order, cid in enumerate(ids):
                conn.execute("UPDATE panel_categories SET sort_order=? WHERE id=?", (order, cid))
            return True

    def reorder_panel_servers(self, server_ids):
        """ترتیب نمایش سرورهای واقعی را دقیقاً مطابق لیست شناسه‌ها ذخیره می‌کند."""
        ids = [int(x) for x in (server_ids or [])]
        if len(ids) != len(set(ids)):
            raise ValueError("شناسه‌های سرورها تکراری هستند.")
        with self._get_conn() as conn:
            rows = conn.execute("SELECT id FROM panel_servers WHERE (is_mirror IS NULL OR is_mirror=0)").fetchall()
            existing = {int(r["id"]) for r in rows}
            if set(ids) != existing:
                raise ValueError("فهرست سرورها کامل نیست یا شامل سرور نامعتبر است.")
            for order, server_id in enumerate(ids):
                conn.execute("UPDATE panel_servers SET sort_order=? WHERE id=?", (order, server_id))


    def get_panel_capacity_info(self, server_id: int):
        """وضعیت ظرفیت پنل را بر اساس کانفیگ‌های فعال محاسبه می‌کند.
        max_services تهی/صفر یعنی نامحدود.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT max_services, capacity_alert_sent FROM panel_servers WHERE id=?", (server_id,)
            ).fetchone()
            if not row:
                return None
            active = conn.execute(
                "SELECT COUNT(*) AS c FROM custom_configs WHERE panel_server_id=? AND status='active'",
                (server_id,),
            ).fetchone()["c"]
            active += conn.execute(
                "SELECT COUNT(*) AS c FROM config_panel_links l JOIN custom_configs c ON c.id=l.custom_config_id "
                "WHERE l.panel_server_id=? AND l.status='active' AND c.status='active'",
                (server_id,),
            ).fetchone()["c"]
        limit = int(row["max_services"] or 0)
        remaining = None if limit <= 0 else max(0, limit - active)
        percent = 0.0 if limit <= 0 else (active / limit) * 100.0
        return {
            "max_services": limit or None,
            "active_services": active,
            "remaining": remaining,
            "percent": percent,
            "near_limit": bool(limit > 0 and percent >= 90.0),
            "capacity_alert_sent": bool(row["capacity_alert_sent"]),
        }


    def panel_has_capacity(self, server_id: int, additional: int = 1) -> bool:
        if not isinstance(additional, int) or additional < 1:
            return False
        info = self.get_panel_capacity_info(server_id)
        return bool(info and (info["max_services"] is None or info["active_services"] + additional <= info["max_services"]))


    def maybe_mark_panel_capacity_alert(self, server_id: int) -> bool:
        """اگر ظرفیت به ۹۰٪ رسیده باشد، فقط بار اول True می‌دهد؛
        وقتی مصرف دوباره زیر ۹۰٪ رفت، فلگ آزاد می‌شود."""
        info = self.get_panel_capacity_info(server_id)
        if not info or info["max_services"] is None:
            return False
        with self._get_conn() as conn:
            if info["percent"] >= 90.0:
                if info["capacity_alert_sent"]:
                    return False
                conn.execute("UPDATE panel_servers SET capacity_alert_sent=1 WHERE id=?", (server_id,))
                return True
            if info["capacity_alert_sent"]:
                conn.execute("UPDATE panel_servers SET capacity_alert_sent=0 WHERE id=?", (server_id,))
        return False


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
            for link in conn.execute(
                "SELECT id FROM config_panel_links WHERE panel_server_id=? OR custom_config_id IN "
                "(SELECT id FROM custom_configs WHERE panel_server_id=?)", (server_id, server_id)
            ).fetchall():
                sid = f"panel_link:{int(link['id'])}"
                conn.execute("DELETE FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (sid,))
                conn.execute("DELETE FROM quota_enforcement_state WHERE service_kind='vpn' AND service_id=?", (sid,))
                conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?", (sid,))
                conn.execute("DELETE FROM config_panel_links WHERE id=?", (int(link["id"]),))
            if dependent:
                conn.execute("DELETE FROM custom_configs WHERE panel_server_id=?", (server_id,))
            # test_config_plans و custom_config_products هم FK به panel_servers دارند‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # (بدون CASCADE)؛ بدون پاک‌کردن این‌ها، DELETE پایین با IntegrityError
            # شکست می‌خورد چون PRAGMA foreign_keys=ON فعال است.
            conn.execute("DELETE FROM test_config_plans WHERE panel_server_id=?", (server_id,))
            conn.execute("DELETE FROM wheel_prizes WHERE panel_server_id=?", (server_id,))
            conn.execute("DELETE FROM custom_config_products WHERE panel_server_id=?", (server_id,))
            conn.execute("DELETE FROM product_extra_targets WHERE kind='panel' AND target_id=?", (server_id,))
            conn.execute("DELETE FROM panel_servers WHERE id=?", (server_id,))
        return dependent


    def set_panel_health_alert(self, server_id: int, last_alert) -> None:
        """زمان آخرین هشدار/یادآوری قطعی این پنل را ثبت می‌کند؛ last_alert=None یعنی
        پاک‌کردن (وقتی پنل دوباره بالا می‌آید و برای قطعی بعدی باید از نو حساب شود)."""
        with self._get_conn() as conn:
            conn.execute("UPDATE panel_health SET last_alert=? WHERE server_id=?", (last_alert, server_id))


    def list_panel_health(self) -> dict:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM panel_health").fetchall()
        return {r["server_id"]: r for r in rows}


    def save_panel_health(
        self, server_id: int, status: str, fail_count: int, last_check: str, last_change: str, last_error: str,
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO panel_health (server_id, status, fail_count, last_check, last_change, last_error) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(server_id) DO UPDATE SET status=excluded.status, "
                "fail_count=excluded.fail_count, last_check=excluded.last_check, "
                "last_change=excluded.last_change, last_error=excluded.last_error",
                (server_id, status, fail_count, last_check, last_change, last_error),
            )


    def add_panel_health_event(self, server_id: int, kind: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO panel_health_events (server_id, kind, created_at) VALUES (?, ?, ?)",
                (server_id, kind, datetime.utcnow().isoformat()),
            )
            conn.execute(
                "DELETE FROM panel_health_events WHERE created_at < ?",
                ((datetime.utcnow() - timedelta(days=30)).isoformat(),),
            )


    def get_report_topics(self, chat_id: int) -> dict:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT topic_key, thread_id FROM report_topics WHERE chat_id=?", (chat_id,),
            ).fetchall()
        return {r["topic_key"]: r["thread_id"] for r in rows}


    def set_report_topic(self, chat_id: int, topic_key: str, thread_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO report_topics (chat_id, topic_key, thread_id) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id, topic_key) DO UPDATE SET thread_id=excluded.thread_id",
                (chat_id, topic_key, thread_id),
            )


    def clear_report_topics(self) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM report_topics")


    def get_report_topic_labels(self, chat_id: int) -> dict:
        """نام‌های سفارشی تاپیک‌ها (فاز ۱ گسترش گروه گزارش) که مدیر روی نام
        پیش‌فرض هر تاپیک override کرده - جدا از thread_id واقعی تلگرام تا حتی
        قبل از ساخته‌شدن خودِ تاپیک هم قابل تنظیم باشد."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT topic_key, custom_name FROM report_topic_labels WHERE chat_id=?", (chat_id,),
            ).fetchall()
        return {r["topic_key"]: r["custom_name"] for r in rows}


    def set_report_topic_label(self, chat_id: int, topic_key: str, custom_name: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO report_topic_labels (chat_id, topic_key, custom_name, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(chat_id, topic_key) DO UPDATE SET custom_name=excluded.custom_name, updated_at=excluded.updated_at",
                (chat_id, topic_key, custom_name, datetime.utcnow().isoformat()),
            )


    def clear_report_topic_label(self, chat_id: int, topic_key: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM report_topic_labels WHERE chat_id=? AND topic_key=?", (chat_id, topic_key),
            )


    def bump_report_topic_stat(self, chat_id: int, topic_key: str) -> None:
        """شمارنده‌ی روزانه‌ی پیام‌های ارسال‌شده به هر تاپیک (برای صفحه‌ی آمار مدیریت تاپیک‌ها)."""
        now = datetime.utcnow()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO report_topic_stats (chat_id, topic_key, day, count, last_at) VALUES (?, ?, ?, 1, ?) "
                "ON CONFLICT(chat_id, topic_key, day) DO UPDATE SET count=count+1, last_at=excluded.last_at",
                (chat_id, topic_key, now.strftime("%Y-%m-%d"), now.isoformat()),
            )
            if now.minute == 0 and now.second < 5:
                conn.execute(
                    "DELETE FROM report_topic_stats WHERE day < ?",
                    ((now - timedelta(days=90)).strftime("%Y-%m-%d"),),
                )

    def get_report_topic_stats(self, chat_id: int, days: int = 7) -> dict:
        """{topic_key: {"count": تعداد در بازه, "today": امروز, "last_at": آخرین ارسال}}"""
        now = datetime.utcnow()
        since = (now - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT topic_key, day, count, last_at FROM report_topic_stats WHERE chat_id=? AND day>=?",
                (chat_id, since),
            ).fetchall()
        out = {}
        for r in rows:
            e = out.setdefault(r["topic_key"], {"count": 0, "today": 0, "last_at": None})
            e["count"] += r["count"]
            if r["day"] == today:
                e["today"] += r["count"]
            if r["last_at"] and (e["last_at"] is None or r["last_at"] > e["last_at"]):
                e["last_at"] = r["last_at"]
        return out


    def get_latest_panel_health_event_id(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT MAX(id) m FROM panel_health_events").fetchone()
            return row["m"] or 0


    def get_panel_health_events_since(self, event_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT e.*, s.name AS server_name FROM panel_health_events e "
                "LEFT JOIN panel_servers s ON s.id = e.server_id WHERE e.id > ? ORDER BY e.id",
                (event_id,),
            ).fetchall()


    def get_panel_server(self, server_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM panel_servers WHERE id=?", (server_id,)).fetchone()


    def get_panel_servers(self, active_only: bool = False, include_mirrors: bool = False):
        """include_mirrors=False (پیش‌فرض) ردیف‌های آینه‌ای که
        get_or_create_mirror_panel_server برای بات‌های نمایندگی می‌سازد را از
        لیست «مدیریت پنل‌ها»ی ادمین کنار می‌گذارد - آن‌ها فقط یک کپی داخلی برای
        رعایت FOREIGN KEY جدول custom_configs هستند و نباید در فرم‌های
        ادمین/انتخاب پنل به چشم بیایند یا قابل ویرایش/حذف دستی باشند."""
        with self._get_conn() as conn:
            conds = []
            if active_only:
                conds.append("is_active=1")
            if not include_mirrors:
                conds.append("(is_mirror IS NULL OR is_mirror=0)")
            q = "SELECT * FROM panel_servers"
            if conds:
                q += " WHERE " + " AND ".join(conds)
            q += " ORDER BY sort_order, id"
            return conn.execute(q).fetchall()


    def get_or_create_mirror_panel_server(self, source_server) -> int:
        """برای reseller_auto_provision.py: از روی یک ردیف panel_servers که در
        دیتابیس *دیگری* (بات اصلی) خوانده شده، یک ردیف معادل در دیتابیس همین
        instance (بات نمایندگی) پیدا یا می‌سازد و id محلی را برمی‌گرداند - چون
        custom_configs.panel_server_id با FOREIGN KEY فقط به panel_servers
        *همین* دیتابیس اشاره می‌کند، نه دیتابیسی که source_server از آن آمده.
        اگر قبلاً برای همین پنل (بر اساس mirror_source_id) یک آینه ساخته شده،
        همان به‌روزرسانی می‌شود (مثلاً اگر ادمین بعداً آدرس/کلید پنل را عوض
        کرده) و id قبلی‌اش برمی‌گردد؛ در غیر این صورت یک ردیف تازه ساخته
        می‌شود. is_mirror=1 باعث می‌شود این ردیف در get_panel_servers()
        (لیست مدیریت پنل‌های ادمین) دیده نشود، ولی get_panel_server(id) برای
        عملیات واقعی (تمدید/مصرف/حذف سرویس) کاملاً عادی کار می‌کند."""
        fields = (
            "name", "panel_type", "api_url", "api_username", "api_password",
            "api_key", "template_username", "group_ids", "proxy_settings", "socks_proxy",
            "default_group", "xui_inbound_id", "xui_inbound_ids", "xui_sub_base_url", "start_on_first_use", "max_services",
        )
        keys = source_server.keys()
        values = {f: (source_server[f] if f in keys else None) for f in fields}
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM panel_servers WHERE mirror_source_id=?", (source_server["id"],)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE panel_servers SET name=?, panel_type=?, api_url=?, api_username=?, "
                    "api_password=?, api_key=?, template_username=?, group_ids=?, proxy_settings=?, socks_proxy=?, "
                    "default_group=?, xui_inbound_id=?, xui_inbound_ids=?, xui_sub_base_url=?, "
                    "start_on_first_use=?, max_services=?, is_active=1 WHERE id=?",
                    (values["name"], values["panel_type"], values["api_url"], values["api_username"],
                     values["api_password"], values["api_key"], values["template_username"],
                     values["group_ids"], values["proxy_settings"], values["socks_proxy"], values["default_group"],
                     values["xui_inbound_id"], values["xui_inbound_ids"], values["xui_sub_base_url"],
                     values["start_on_first_use"], values["max_services"], existing["id"]),
                )
                return existing["id"]
            cur = conn.execute(
                "INSERT INTO panel_servers (name, panel_type, api_url, api_username, api_password, "
                "api_key, template_username, group_ids, proxy_settings, socks_proxy, default_group, xui_inbound_id, "
                "xui_inbound_ids, xui_sub_base_url, start_on_first_use, max_services, is_active, used_for_custom_config, used_for_test_config, "
                "used_for_reseller, mirror_source_id, is_mirror) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0, 0, ?, 1)",
                (values["name"], values["panel_type"], values["api_url"], values["api_username"],
                 values["api_password"], values["api_key"], values["template_username"],
                 values["group_ids"], values["proxy_settings"], values["socks_proxy"], values["default_group"],
                 values["xui_inbound_id"], values["xui_inbound_ids"], values["xui_sub_base_url"], values["start_on_first_use"], values["max_services"],
                 source_server["id"]),
            )
            return cur.lastrowid


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
            # column فقط از whitelist dict بالا میاد (بدون ورودی کاربر)
            return conn.execute(
                f"SELECT * FROM panel_servers WHERE is_active=1 AND {column}=1 ORDER BY id LIMIT 1"
            ).fetchone()

    # -----------------------------------------------------------------------
    # قیمت‌گذاری پلکانی ساخت کانفیگ شخصی
    # -----------------------------------------------------------------------‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


    def get_panel_rating_summary(self, panel_server_id: int) -> dict:
        """میانگین امتیاز و تعداد رأی یک پنل/لوکیشن — برای شناسایی سرویس‌های ضعیف."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT AVG(rating) avg_rating, COUNT(*) c FROM service_ratings WHERE panel_server_id=?",
                (panel_server_id,),
            ).fetchone()
            return {"avg": round(row["avg_rating"], 1) if row["avg_rating"] is not None else None, "count": row["c"] or 0}

    # -----------------------------------------------------------------------
    # فعال/غیرفعال، تمدید خودکار، تغییر نام و انتقال کانفیگ‌های مستقیم-پنل
    # -----------------------------------------------------------------------


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
    # درخواست خودکار نمایندگی (ثبت، تایید هزینه، پرداخت، تحویل)
    # -----------------------------------------------------------------------

    _RESELLER_REQUEST_OPEN_STATUSES = (
        "pending_review", "awaiting_payment", "awaiting_payment_review", "awaiting_bot_info",
    )

#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
