# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
import time

from .constants import *
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

class TicketsMixin:
    def add_support_message(self, user_id: int, sender: str, message: str) -> int:
        """sender باید 'user' یا 'admin' باشد."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO support_messages (user_id, sender, message, is_read_by_user, is_read_by_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, sender, message, 1 if sender == "user" else 0, 1 if sender == "admin" else 0),
            )
            conn.execute(
                "INSERT INTO support_conversations (user_id, updated_at) VALUES (?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP",
                (user_id,),
            )
            return cur.lastrowid


    def get_support_messages(self, user_id: int, since_id: int = 0, limit: int = 100):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_messages WHERE user_id=? AND id>? ORDER BY id LIMIT ?",
                (user_id, since_id, limit),
            ).fetchall()


    def mark_support_read_by_user(self, user_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE support_messages SET is_read_by_user=1 WHERE user_id=? AND is_read_by_user=0",
                (user_id,),
            )


    def mark_support_read_by_admin(self, user_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE support_messages SET is_read_by_admin=1 WHERE user_id=? AND is_read_by_admin=0",
                (user_id,),
            )

    # -----------------------------------------------------------------------
    # مکالمه‌ی دستیار پشتیبانی هوش مصنوعی (Gemini)
    # -----------------------------------------------------------------------


    def add_ai_message(self, user_id: int, role: str, message: str) -> int:
        """role باید 'user' یا 'model' باشد (مطابق نام‌گذاری Gemini)."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO ai_support_messages (user_id, role, message) VALUES (?, ?, ?)",
                (user_id, role, message),
            )
            return cur.lastrowid


    def get_ai_conversation(self, user_id: int, limit: int = 30):
        """آخرین `limit` پیام مکالمه‌ی AI را به ترتیب زمانی (قدیم به جدید)
        برمی‌گرداند - برای ارسال به‌عنوان تاریخچه به مدل."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_support_messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return list(reversed(rows))


    def clear_ai_conversation(self, user_id: int):
        """بعد از escalate به پشتیبانی انسانی یا با دستور صریح کاربر صدا زده
        می‌شود تا گفتگوی بعدی از صفر شروع شود."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM ai_support_messages WHERE user_id=?", (user_id,))

    # -----------------------------------------------------------------------
    # سوالات متداول دستیار هوش مصنوعی (قابل مدیریت از پنل ادمین)
    # -----------------------------------------------------------------------


    def add_ai_faq_item(self, question: str, answer: str) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) m FROM ai_faq_items").fetchone()
            next_order = (row["m"] or 0) + 1
            cur = conn.execute(
                "INSERT INTO ai_faq_items (question, answer, sort_order) VALUES (?, ?, ?)",
                (question, answer, next_order),
            )
            return cur.lastrowid


    def get_ai_faq_items(self):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM ai_faq_items ORDER BY sort_order, id").fetchall()


    def get_ai_faq_item(self, item_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM ai_faq_items WHERE id=?", (item_id,)).fetchone()


    def delete_ai_faq_item(self, item_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM ai_faq_items WHERE id=?", (item_id,))


    def build_ai_faq_text(self) -> str:
        """متن نهایی سوالات متداول برای تزریق به system prompt دستیار هوشمند."""
        items = self.get_ai_faq_items()
        if not items:
            return "(چیزی ثبت نشده)"
        return "\n\n".join(f"سوال: {it['question']}\nجواب: {it['answer']}" for it in items)

    # -----------------------------------------------------------------------
    # آموزش‌ها: هر آموزش (جدول tutorial_devices) یک عنوان و چند مرحله‌ی‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    # متن/عکس/ویدیو دارد و از طریق tutorial_bindings به هر تعداد بخش/دکمه
    # متصل می‌شود (کلیدهای مقصد در tutorial_hub.py تعریف شده‌اند).
    # -----------------------------------------------------------------------

    _TUT_TARGETS_TTL = 30.0

    def _tutorial_cache_clear(self) -> None:
        self._tut_targets_cache = None


    def add_tutorial_device(self, name: str, emoji: str = "📱") -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) m FROM tutorial_devices").fetchone()
            next_order = (row["m"] or 0) + 1
            cur = conn.execute(
                "INSERT INTO tutorial_devices (name, emoji, sort_order) VALUES (?, ?, ?)",
                (name, emoji, next_order),
            )
            new_id = cur.lastrowid
        self._tutorial_cache_clear()
        return new_id


    def rename_tutorial(self, tutorial_id: int, name: str, emoji: str = None) -> None:
        with self._get_conn() as conn:
            if emoji:
                conn.execute("UPDATE tutorial_devices SET name=?, emoji=? WHERE id=?", (name, emoji, tutorial_id))
            else:
                conn.execute("UPDATE tutorial_devices SET name=? WHERE id=?", (name, tutorial_id))


    def get_tutorial_devices(self, active_only: bool = False):
        query = "SELECT * FROM tutorial_devices"
        if active_only:
            query += " WHERE is_active=1"
        query += " ORDER BY sort_order, id"
        with self._get_conn() as conn:
            return conn.execute(query).fetchall()


    def get_tutorial_device(self, device_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM tutorial_devices WHERE id=?", (device_id,)).fetchone()


    def set_tutorial_device_active(self, device_id: int, active: bool) -> None:
        with self._get_conn() as conn:
            conn.execute("UPDATE tutorial_devices SET is_active=? WHERE id=?", (1 if active else 0, device_id))
        self._tutorial_cache_clear()


    def delete_tutorial_device(self, device_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM tutorial_bindings WHERE tutorial_id=?", (device_id,))
            conn.execute("DELETE FROM tutorial_steps WHERE device_id=?", (device_id,))
            conn.execute("DELETE FROM tutorial_devices WHERE id=?", (device_id,))
        self._tutorial_cache_clear()


    def add_tutorial_step(self, device_id: int, text: str = None, photo_file_id: str = None, video_file_id: str = None) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COALESCE(MAX(step_order), 0) m FROM tutorial_steps WHERE device_id=?", (device_id,)).fetchone()
            next_order = (row["m"] or 0) + 1
            cur = conn.execute(
                "INSERT INTO tutorial_steps (device_id, step_order, text, photo_file_id, video_file_id) VALUES (?, ?, ?, ?, ?)",
                (device_id, next_order, text, photo_file_id, video_file_id),
            )
            new_id = cur.lastrowid
        self._tutorial_cache_clear()
        return new_id


    def get_tutorial_steps(self, device_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM tutorial_steps WHERE device_id=? ORDER BY step_order, id", (device_id,),
            ).fetchall()


    def delete_tutorial_step(self, step_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM tutorial_steps WHERE id=?", (step_id,))
        self._tutorial_cache_clear()


    def get_tutorial_targets(self, tutorial_id: int) -> set:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT target_key FROM tutorial_bindings WHERE tutorial_id=?", (tutorial_id,),
            ).fetchall()
        return {r["target_key"] for r in rows}


    def set_tutorial_target(self, tutorial_id: int, target_key: str, enabled: bool) -> None:
        with self._get_conn() as conn:
            if enabled:
                conn.execute(
                    "INSERT OR IGNORE INTO tutorial_bindings (tutorial_id, target_key) VALUES (?, ?)",
                    (tutorial_id, target_key),
                )
            else:
                conn.execute(
                    "DELETE FROM tutorial_bindings WHERE tutorial_id=? AND target_key=?",
                    (tutorial_id, target_key),
                )
        self._tutorial_cache_clear()


    def toggle_tutorial_target(self, tutorial_id: int, target_key: str) -> bool:
        """وضعیت اتصال را برعکس می‌کند و وضعیت جدید (متصل=True) را برمی‌گرداند."""
        enabled = target_key not in self.get_tutorial_targets(tutorial_id)
        self.set_tutorial_target(tutorial_id, target_key, enabled)
        return enabled


    def get_tutorials_for_target(self, target_key: str):
        """آموزش‌های فعالِ دارای حداقل یک مرحله که به این مقصد متصل‌اند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT d.* FROM tutorial_devices d "
                "JOIN tutorial_bindings b ON b.tutorial_id = d.id "
                "WHERE b.target_key=? AND d.is_active=1 "
                "AND EXISTS (SELECT 1 FROM tutorial_steps s WHERE s.device_id = d.id) "
                "ORDER BY d.sort_order, d.id",
                (target_key,),
            ).fetchall()


    def get_tutorial_bound_targets(self) -> set:
        """مجموعه‌ی مقصدهایی که حداقل یک آموزش فعال (با مرحله) دارند؛ برای
        هر آپدیت ورودی خوانده می‌شود، پس چند ثانیه در حافظه کش می‌شود."""
        cache = getattr(self, "_tut_targets_cache", None)
        now = time.monotonic()
        if cache is not None and now - cache[0] < self._TUT_TARGETS_TTL:
            return cache[1]
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT b.target_key FROM tutorial_bindings b "
                "JOIN tutorial_devices d ON d.id = b.tutorial_id AND d.is_active=1 "
                "WHERE EXISTS (SELECT 1 FROM tutorial_steps s WHERE s.device_id = d.id)"
            ).fetchall()
        keys = {r["target_key"] for r in rows}
        self._tut_targets_cache = (now, keys)
        return keys

    # -----------------------------------------------------------------------
    # آنلاین‌بودن ادمین‌ها (برای مسیریابی چت زنده به اولین ادمین/مالک آنلاین)
    # -----------------------------------------------------------------------

    PRESENCE_ONLINE_SECONDS = 90


    def touch_admin_presence(self, tg_id: int):
        """باید در هر تعامل ادمین (پیام/کلیک در بات، یا درخواست API مینی‌اپ) صدا زده شود."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO admin_presence (telegram_id, last_seen) VALUES (?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(telegram_id) DO UPDATE SET last_seen=CURRENT_TIMESTAMP",
                (tg_id,),
            )


    def get_online_admin_ids(self, timeout_seconds: int = None) -> list:
        timeout_seconds = timeout_seconds or self.PRESENCE_ONLINE_SECONDS
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT telegram_id FROM admin_presence WHERE last_seen >= datetime('now', ?)",
                (f"-{timeout_seconds} seconds",),
            ).fetchall()
            return [r["telegram_id"] for r in rows]


    def schedule_temp_message(self, chat_id: int, message_id: int, delete_at: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO temp_messages (chat_id, message_id, delete_at) VALUES (?, ?, ?)",
                (chat_id, message_id, delete_at),
            )


    def add_broadcast_pin(self, batch: int, chat_id: int, message_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO broadcast_pins (batch, chat_id, message_id) VALUES (?, ?, ?)",
                (batch, chat_id, message_id),
            )


    def pop_latest_broadcast_pins(self) -> list:
        """پین‌های آخرین ارسال همگانی را برمی‌گرداند و از جدول حذف می‌کند."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT MAX(batch) AS b FROM broadcast_pins").fetchone()
            if not row or row["b"] is None:
                return []
            rows = conn.execute(
                "SELECT chat_id, message_id FROM broadcast_pins WHERE batch=?", (row["b"],)
            ).fetchall()
            conn.execute("DELETE FROM broadcast_pins WHERE batch=?", (row["b"],))
            return [{"chat_id": r["chat_id"], "message_id": r["message_id"]} for r in rows]


    def pop_due_temp_messages(self) -> list:
        """پیام‌های سررسیدشده را برمی‌گرداند و همزمان از جدول حذف می‌کند."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, chat_id, message_id FROM temp_messages WHERE delete_at <= ?", (now,)
            ).fetchall()
            if rows:
                conn.executemany(
                    "DELETE FROM temp_messages WHERE id=?", [(r["id"],) for r in rows]
                )
            return [{"chat_id": r["chat_id"], "message_id": r["message_id"]} for r in rows]

    # -----------------------------------------------------------------------‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    # مسیریابی مکالمه‌ی چت زنده (به اولین ادمین/مالک آنلاین)
    # -----------------------------------------------------------------------


    def get_support_conversation(self, user_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_conversations WHERE user_id=?", (user_id,)
            ).fetchone()


    def set_support_conversation_admin(self, user_id: int, admin_id):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO support_conversations (user_id, assigned_admin_id, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET assigned_admin_id=excluded.assigned_admin_id, "
                "updated_at=CURRENT_TIMESTAMP",
                (user_id, admin_id),
            )


    def list_support_conversations(self):
        """لیست مکالمات چت زنده برای تب «پشتیبانی زنده» در پنل ادمین، جدیدترین اول."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, MAX(id) AS last_id, MAX(created_at) AS last_at, "
                "SUM(CASE WHEN sender='user' AND is_read_by_admin=0 THEN 1 ELSE 0 END) AS unread "
                "FROM support_messages GROUP BY user_id ORDER BY last_at DESC"
            ).fetchall()
            result = []
            for r in rows:
                last_msg = conn.execute(
                    "SELECT sender, message FROM support_messages WHERE user_id=? ORDER BY id DESC LIMIT 1",
                    (r["user_id"],),
                ).fetchone()
                conv = conn.execute(
                    "SELECT assigned_admin_id FROM support_conversations WHERE user_id=?", (r["user_id"],)
                ).fetchone()
                result.append({
                    "user_id": r["user_id"],
                    "last_at": r["last_at"],
                    "unread": r["unread"] or 0,
                    "last_message": last_msg["message"] if last_msg else "",
                    "last_sender": last_msg["sender"] if last_msg else "",
                    "assigned_admin_id": conv["assigned_admin_id"] if conv else None,
                })
            return result


    def count_tickets_by_status(self, status: str) -> int:
        with self._get_read_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM tickets WHERE status=?", (status,)).fetchone()[0]


    def count_unread_support_conversations(self) -> int:
        """تعداد مکالمات چت زنده‌ای که حداقل یک پیام خوانده‌نشده از کاربر دارند
        (برای بج زنده‌ی منو کنار «چت زنده»)."""
        with self._get_read_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM support_messages "
                "WHERE sender='user' AND is_read_by_admin=0"
            ).fetchone()
            return row["c"] or 0


    def get_latest_user_support_message_id(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(id) AS m FROM support_messages WHERE sender='user'"
            ).fetchone()
            return row["m"] or 0


    def get_new_support_messages_since(self, since_id: int):
        """پیام‌های جدید کاربر (نه ادمین) بعد از since_id، برای حلقه‌ی پوش زنده‌ی پنل وب."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_messages WHERE sender='user' AND id>? ORDER BY id",
                (since_id,),
            ).fetchall()

    # -----------------------------------------------------------------------
    # سیستم تیکت (مستقل از چت مستقیم بالا - یک راه ارتباطی جداگانه و رسمی‌تر
    # با موضوع مشخص و وضعیت باز/پاسخ‌داده‌شده/بسته)
    # -----------------------------------------------------------------------


    def ensure_ticket_departments(self):
        defaults = [("فروش", 10), ("فنی", 20), ("مالی", 30), ("عمومی", 40)]
        with self._get_conn() as conn:
            for name, order in defaults:
                conn.execute(
                    "INSERT OR IGNORE INTO ticket_departments(name, sort_order, is_active) VALUES (?, ?, 1)",
                    (name, order),
                )


    def list_ticket_departments(self, active_only=True):
        self.ensure_ticket_departments()
        with self._get_conn() as conn:
            q = "SELECT * FROM ticket_departments" + (" WHERE is_active=1" if active_only else "") + " ORDER BY sort_order, id"
            return conn.execute(q).fetchall()


    def get_ticket_department(self, department_id):
        self.ensure_ticket_departments()
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM ticket_departments WHERE id=?", (department_id,)).fetchone()


    def toggle_ticket_department_admin(self, department_id: int, admin_id: int):
        self.ensure_ticket_departments()
        with self._get_conn() as conn:
            row = conn.execute("SELECT 1 FROM ticket_department_admins WHERE department_id=? AND admin_id=?", (department_id, admin_id)).fetchone()
            if row:
                conn.execute("DELETE FROM ticket_department_admins WHERE department_id=? AND admin_id=?", (department_id, admin_id))
                return False
            conn.execute("INSERT INTO ticket_department_admins(department_id, admin_id) VALUES (?, ?)", (department_id, admin_id))
            return True


    def list_ticket_department_admins(self, department_id: int):
        with self._get_conn() as conn:
            return [r["admin_id"] for r in conn.execute("SELECT admin_id FROM ticket_department_admins WHERE department_id=?", (department_id,)).fetchall()]


    def list_ticket_admin_ids_for_department(self, department_id: int):
        self.ensure_ticket_departments()
        assigned = self.list_ticket_department_admins(department_id)
        admins = self.list_admins()
        owner = None
        for a in self.list_admins_with_roles():
            if a["role"] == "owner":
                owner = a["telegram_id"]
                break
        if assigned:
            ids = set(assigned)
        else:
            # تا قبل از پیکربندی دپارتمان‌ها رفتار قبلی حفظ می‌شود.
            ids = set(admins)
        if owner:
            ids.add(owner)
        return sorted(ids)


    def create_ticket(self, user_id: int, subject: str, first_message: str, department_id: int = None) -> int:
        self.ensure_ticket_departments()
        if department_id is None:
            deps = self.list_ticket_departments()
            department_id = deps[0]["id"] if deps else None
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO tickets (user_id, subject, status, department_id) VALUES (?, ?, 'open', ?)",
                (user_id, subject, department_id),
            )
            ticket_id = cur.lastrowid
            conn.execute(
                "INSERT INTO ticket_messages (ticket_id, sender, message, is_read_by_user, is_read_by_admin) VALUES (?, 'user', ?, 1, 0)",
                (ticket_id, first_message),
            )
            return ticket_id


    def get_user_tickets(self, user_id: int):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM tickets WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()


    def get_all_tickets(self, status: str = None):
        with self._get_conn() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM tickets WHERE status=? ORDER BY updated_at DESC", (status,)
                ).fetchall()
            return conn.execute("SELECT * FROM tickets ORDER BY updated_at DESC").fetchall()


    def get_ticket(self, ticket_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()


    def _ensure_ticket_group_table(self, conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ticket_group_messages ("
            "chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (chat_id, message_id))"
        )


    def link_ticket_group_message(self, chat_id: int, message_id: int, ticket_id: int):
        with self._get_conn() as conn:
            self._ensure_ticket_group_table(conn)
            conn.execute(
                "INSERT OR REPLACE INTO ticket_group_messages (chat_id, message_id, ticket_id) VALUES (?, ?, ?)",
                (chat_id, message_id, ticket_id),
            )


    def get_ticket_id_by_group_message(self, chat_id: int, message_id: int):
        with self._get_conn() as conn:
            self._ensure_ticket_group_table(conn)
            row = conn.execute(
                "SELECT ticket_id FROM ticket_group_messages WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            ).fetchone()
            return row[0] if row else None


    def claim_ticket_if_open(self, ticket_id: int, admin_id: int):
        """اولین ادمین یا مالکی که به تیکت پاسخ می‌دهد، مالک آن پاسخ‌گویی می‌شود؛
        تا وقتی claimed_by خالی است این تابع آن را قفل می‌کند و از این پس فقط
        همان ادمین (و همیشه مالک اصلی بات) اجازه‌ی پاسخ‌دادن به این تیکت را دارند."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tickets SET claimed_by=? WHERE id=? AND claimed_by IS NULL",
                (admin_id, ticket_id),
            )


    def add_ticket_message(self, ticket_id: int, sender: str, message: str) -> int:
        """sender باید 'user' یا 'admin' باشد. وضعیت تیکت را هم خودکار به‌روز می‌کند:
        پاسخ ادمین -> answered ، پیام جدید کاربر روی تیکت بسته/پاسخ‌داده‌شده -> open."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO ticket_messages (ticket_id, sender, message, is_read_by_user, is_read_by_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                (ticket_id, sender, message, 1 if sender == "user" else 0, 1 if sender == "admin" else 0),
            )
            new_status = "answered" if sender == "admin" else "open"
            conn.execute(
                "UPDATE tickets SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_status, ticket_id),
            )
            return cur.lastrowid


    def get_ticket_messages(self, ticket_id: int, since_id: int = 0, limit: int = 200):
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM ticket_messages WHERE ticket_id=? AND id>? ORDER BY id LIMIT ?",
                (ticket_id, since_id, limit),
            ).fetchall()


    def close_ticket(self, ticket_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tickets SET status='closed', updated_at=CURRENT_TIMESTAMP WHERE id=?", (ticket_id,)
            )


    def mark_ticket_read_by_user(self, ticket_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ticket_messages SET is_read_by_user=1 WHERE ticket_id=? AND is_read_by_user=0",
                (ticket_id,),
            )


    def mark_ticket_read_by_admin(self, ticket_id: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ticket_messages SET is_read_by_admin=1 WHERE ticket_id=? AND is_read_by_admin=0",
                (ticket_id,),
            )


    def count_open_tickets(self) -> int:
        """تعداد تیکت‌هایی که منتظر پاسخ ادمین هستند (برای بج کنار دکمه‌ی پنل مدیریت)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM tickets WHERE status='open'"
            ).fetchone()
            return row["c"] or 0

#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
