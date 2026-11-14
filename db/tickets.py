# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
import time

from .constants import *
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

PRIORITIES = ("low", "medium", "high")


def normalize_priority(value) -> str:
    """اولویت تیکت/چت زنده: low (کم) | medium (متوسط) | high (زیاد)؛ مقدار نامعتبر = medium."""
    value = str(value or "").strip().lower()
    return value if value in PRIORITIES else "medium"


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def norm_search(text) -> str:
    """نرمال‌سازی متن برای جستجو: ارقام فارسی/عربی، ی/ک عربی، نیم‌فاصله و حروف بزرگ/کوچک."""
    s = str(text or "").translate(_FA_DIGITS)
    s = s.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ـ", "").replace("\u200c", " ")
    return " ".join(s.casefold().split())


def search_tokens(text) -> list:
    """کلمات جستجو؛ @ و # ابتدای هر کلمه حذف می‌شود تا «@user» و «#12» هم کار کنند."""
    return [t for t in (w.lstrip("@#") for w in norm_search(text).split()) if t]


class TicketsMixin:
    def add_support_message(self, user_id: int, sender: str, message: str) -> int:
        """sender باید 'user' یا 'admin' باشد."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO support_messages (user_id, sender, message, is_read_by_user, is_read_by_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, sender, message, 1 if sender == "user" else 0, 1 if sender == "admin" else 0),
            )
            if sender == "user":
                # پیام جدید کاربر روی چت بسته‌شده، آن را خودکار دوباره باز می‌کند.
                conn.execute(
                    "INSERT INTO support_conversations (user_id, updated_at, status) "
                    "VALUES (?, CURRENT_TIMESTAMP, 'open') "
                    "ON CONFLICT(user_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP, "
                    "status='open', closed_at=NULL",
                    (user_id,),
                )
            else:
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
                "SELECT user_id, MAX(id) AS last_id, MAX(created_at) AS last_at, COUNT(*) AS total, "
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
                    "SELECT assigned_admin_id, status, priority, ref_kind, ref_id, ref_label "
                    "FROM support_conversations WHERE user_id=?", (r["user_id"],)
                ).fetchone()
                result.append({
                    "user_id": r["user_id"],
                    "last_at": r["last_at"],
                    "unread": r["unread"] or 0,
                    "messages_count": r["total"] or 0,
                    "last_message": last_msg["message"] if last_msg else "",
                    "last_sender": last_msg["sender"] if last_msg else "",
                    "assigned_admin_id": conv["assigned_admin_id"] if conv else None,
                    "status": (conv["status"] if conv and conv["status"] else "open"),
                    "priority": normalize_priority(conv["priority"] if conv else None),
                    "ref_kind": conv["ref_kind"] if conv else None,
                    "ref_id": conv["ref_id"] if conv else None,
                    "ref_label": (conv["ref_label"] if conv else None) or "",
                })
            return result


    # --- وضعیت / اولویت / سرویس مرتبط / حذف چت زنده (فقط از پنل وب مدیریت می‌شود) ---

    def get_support_conversation_state(self, user_id: int) -> dict:
        """وضعیت فعلی چت زنده‌ی یک کاربر؛ اگر هنوز ردیفی نباشد مقادیر پیش‌فرض."""
        conv = self.get_support_conversation(user_id)
        return {
            "status": (conv["status"] if conv and conv["status"] else "open"),
            "priority": normalize_priority(conv["priority"] if conv else None),
            "ref_kind": conv["ref_kind"] if conv else None,
            "ref_id": conv["ref_id"] if conv else None,
            "ref_label": (conv["ref_label"] if conv else None) or "",
            "assigned_admin_id": conv["assigned_admin_id"] if conv else None,
        }

    def set_support_status(self, user_id: int, status: str) -> None:
        status = "closed" if status == "closed" else "open"
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO support_conversations (user_id, status, closed_at, updated_at) "
                "VALUES (?, ?, CASE WHEN ?='closed' THEN CURRENT_TIMESTAMP ELSE NULL END, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET status=excluded.status, closed_at=excluded.closed_at, "
                "updated_at=CURRENT_TIMESTAMP",
                (user_id, status, status),
            )

    def set_support_priority(self, user_id: int, priority: str) -> None:
        priority = normalize_priority(priority)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO support_conversations (user_id, priority, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET priority=excluded.priority",
                (user_id, priority),
            )

    def set_support_reference(self, user_id: int, ref_kind, ref_id, ref_label) -> None:
        """سرویس خریداری‌شده‌ای که کاربر در چت زنده به آن اشاره کرده (None = حذف اشاره)."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO support_conversations (user_id, ref_kind, ref_id, ref_label, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET ref_kind=excluded.ref_kind, ref_id=excluded.ref_id, "
                "ref_label=excluded.ref_label",
                (user_id, ref_kind, ref_id, ref_label),
            )

    def delete_support_conversation(self, user_id: int) -> int:
        """کل چت زنده‌ی کاربر (پیام‌ها + ردیف مکالمه) را حذف می‌کند؛ تعداد پیام‌های حذف‌شده را برمی‌گرداند."""
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM support_messages WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM support_conversations WHERE user_id=?", (user_id,))
            return cur.rowcount or 0

    def list_user_support_services(self, user_id: int, limit: int = 30) -> list:
        """سرویس‌های خریداری‌شده‌ی کاربر برای اشاره در تیکت/چت زنده.
        هر آیتم: {kind: 'custom'|'bank', id, label}. کانفیگ‌های تست/هدیه حذف می‌شوند."""
        items = []
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT cc.id AS id, COALESCE(NULLIF(cc.display_name,''), cc.username) AS name, "
                "cc.status AS status, p.name AS product_name "
                "FROM custom_configs cc LEFT JOIN orders o ON o.id=cc.order_id "
                "LEFT JOIN products p ON p.id=o.product_id "
                "WHERE cc.user_id=? AND COALESCE(cc.source,'') NOT IN ('test','welcome_gift','gift') "
                "ORDER BY cc.id DESC LIMIT ?",
                (int(user_id), int(limit)),
            ).fetchall()
            for r in rows:
                label = str(r["name"] or f"#{r['id']}")
                if r["product_name"]:
                    label += f" — {r['product_name']}"
                items.append({"kind": "custom", "id": int(r["id"]), "label": label[:120]})
            rows = conn.execute(
                "SELECT cf.id AS id, p.name AS product_name FROM configs cf "
                "LEFT JOIN products p ON p.id=cf.product_id "
                "WHERE cf.assigned_user_id=? ORDER BY cf.id DESC LIMIT ?",
                (int(user_id), int(limit)),
            ).fetchall()
            for r in rows:
                items.append({"kind": "bank", "id": int(r["id"]),
                              "label": f"{r['product_name'] or 'سرویس'} (#{r['id']})"[:120]})
        return items[: int(limit)]

    def resolve_support_service_ref(self, user_id: int, kind, ref_id):
        """اعتبارسنجی اشاره به سرویس: فقط سرویسی که واقعاً مال همین کاربر است پذیرفته می‌شود.
        خروجی (kind, id, label) یا (None, None, None)."""
        try:
            ref_id = int(ref_id)
        except (TypeError, ValueError):
            return None, None, None
        for item in self.list_user_support_services(user_id, limit=200):
            if item["kind"] == kind and item["id"] == ref_id:
                return item["kind"], item["id"], item["label"]
        return None, None, None

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
        # دسته‌بندی‌های پیش‌فرض فقط یک بار ساخته می‌شوند تا اگر مدیر یکی را از پنل وب
        # حذف کرد، با فراخوانی بعدی دوباره برنگردد.
        if self.get_setting("ticket_departments_seeded", "") == "1":
            return
        defaults = [("فروش", 10), ("فنی", 20), ("مالی", 30), ("عمومی", 40)]
        with self._get_conn() as conn:
            for name, order in defaults:
                conn.execute(
                    "INSERT OR IGNORE INTO ticket_departments(name, sort_order, is_active) VALUES (?, ?, 1)",
                    (name, order),
                )
        self.set_setting("ticket_departments_seeded", "1")

    def create_ticket_department(self, name: str, sort_order: int = None) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("نام دسته‌بندی نمی‌تواند خالی باشد.")
        self.ensure_ticket_departments()
        with self._get_conn() as conn:
            if conn.execute("SELECT 1 FROM ticket_departments WHERE name=?", (name,)).fetchone():
                raise ValueError("دسته‌بندی‌ای با این نام وجود دارد.")
            if sort_order is None:
                row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM ticket_departments").fetchone()
                sort_order = int(row["m"] or 0) + 10
            cur = conn.execute(
                "INSERT INTO ticket_departments(name, sort_order, is_active) VALUES (?, ?, 1)",
                (name, int(sort_order)),
            )
            return cur.lastrowid

    def update_ticket_department(self, department_id: int, name: str = None,
                                 is_active: bool = None, sort_order: int = None) -> bool:
        self.ensure_ticket_departments()
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM ticket_departments WHERE id=?", (department_id,)).fetchone()
            if not row:
                return False
            fields, params = [], []
            if name is not None:
                name = name.strip()
                if not name:
                    raise ValueError("نام دسته‌بندی نمی‌تواند خالی باشد.")
                dup = conn.execute(
                    "SELECT 1 FROM ticket_departments WHERE name=? AND id<>?", (name, department_id)
                ).fetchone()
                if dup:
                    raise ValueError("دسته‌بندی‌ای با این نام وجود دارد.")
                fields.append("name=?"); params.append(name)
            if is_active is not None:
                fields.append("is_active=?"); params.append(1 if is_active else 0)
            if sort_order is not None:
                fields.append("sort_order=?"); params.append(int(sort_order))
            if fields:
                params.append(department_id)
                conn.execute(f"UPDATE ticket_departments SET {', '.join(fields)} WHERE id=?", params)
            return True

    def count_tickets_in_department(self, department_id: int) -> int:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM tickets WHERE department_id=?", (department_id,)
            ).fetchone()[0]

    def delete_ticket_department(self, department_id: int) -> bool:
        """دسته‌بندی را حذف می‌کند؛ تیکت‌های قبلی آن بدون دسته‌بندی می‌مانند (حذف نمی‌شوند)."""
        self.ensure_ticket_departments()
        with self._get_conn() as conn:
            if not conn.execute("SELECT 1 FROM ticket_departments WHERE id=?", (department_id,)).fetchone():
                return False
            conn.execute("UPDATE tickets SET department_id=NULL WHERE department_id=?", (department_id,))
            conn.execute("DELETE FROM ticket_department_admins WHERE department_id=?", (department_id,))
            conn.execute("DELETE FROM ticket_departments WHERE id=?", (department_id,))
            return True


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


    def create_ticket(self, user_id: int, subject: str, first_message: str, department_id: int = None,
                      ref_kind: str = None, ref_id: int = None, ref_label: str = None,
                      priority: str = "medium") -> int:
        self.ensure_ticket_departments()
        if department_id is None:
            deps = self.list_ticket_departments()
            department_id = deps[0]["id"] if deps else None
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO tickets (user_id, subject, status, department_id, priority, ref_kind, ref_id, ref_label) "
                "VALUES (?, ?, 'open', ?, ?, ?, ?, ?)",
                (user_id, subject, department_id, normalize_priority(priority), ref_kind, ref_id, ref_label),
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


    def get_user_names(self, user_ids) -> dict:
        """نام‌کاربری و نام کاربران به‌صورت دسته‌ای: {telegram_id: {username, first_name}}."""
        ids = sorted({int(i) for i in user_ids if i is not None})
        out = {}
        with self._get_conn() as conn:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for r in conn.execute(
                    f"SELECT telegram_id, username, first_name FROM users WHERE telegram_id IN ({marks})", chunk
                ).fetchall():
                    out[r["telegram_id"]] = {"username": r["username"] or "", "first_name": r["first_name"] or ""}
        return out

    def get_ticket_message_stats(self) -> dict:
        """آمار پیام هر تیکت: {ticket_id: {total, unread, last_sender}} (unread = پیام‌های خوانده‌نشده‌ی کاربر برای ادمین)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT ticket_id, COUNT(*) AS total, "
                "SUM(CASE WHEN sender='user' AND is_read_by_admin=0 THEN 1 ELSE 0 END) AS unread "
                "FROM ticket_messages GROUP BY ticket_id"
            ).fetchall()
            stats = {r["ticket_id"]: {"total": r["total"] or 0, "unread": r["unread"] or 0, "last_sender": ""} for r in rows}
            last = conn.execute(
                "SELECT m.ticket_id, m.sender FROM ticket_messages m "
                "JOIN (SELECT MAX(id) AS mid FROM ticket_messages GROUP BY ticket_id) x ON m.id = x.mid"
            ).fetchall()
            for r in last:
                if r["ticket_id"] in stats:
                    stats[r["ticket_id"]]["last_sender"] = r["sender"]
        return stats

    def _ids_by_message_text(self, table: str, column: str, term: str, limit: int = 5000) -> set:
        raw = str(term or "").strip()
        if not raw:
            return set()
        variants = {raw, norm_search(raw), raw.replace("ی", "ي").replace("ک", "ك")}
        variants.discard("")
        esc = lambda v: v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clause = " OR ".join("message LIKE ? ESCAPE '\\'" for _ in variants)
        params = [f"%{esc(v)}%" for v in variants]
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {clause} LIMIT ?", params + [limit]
            ).fetchall()
        return {r[0] for r in rows}

    def find_ticket_ids_by_text(self, term: str, limit: int = 5000) -> set:
        """شناسه‌ی تیکت‌هایی که متن یکی از پیام‌هایشان شامل term است."""
        return self._ids_by_message_text("ticket_messages", "ticket_id", term, limit)

    def find_support_user_ids_by_text(self, term: str, limit: int = 5000) -> set:
        """شناسه‌ی کاربرانی که متن یکی از پیام‌های چت زنده‌شان شامل term است."""
        return self._ids_by_message_text("support_messages", "user_id", term, limit)


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


    def reopen_ticket(self, ticket_id: int) -> bool:
        """تیکت بسته را دوباره باز می‌کند (برای مدیر در پنل وب و برای خود کاربر)."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE tickets SET status='open', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='closed'",
                (ticket_id,),
            )
            return (cur.rowcount or 0) > 0

    def set_ticket_priority(self, ticket_id: int, priority: str) -> None:
        with self._get_conn() as conn:
            conn.execute("UPDATE tickets SET priority=? WHERE id=?", (normalize_priority(priority), ticket_id))

    def set_ticket_department(self, ticket_id: int, department_id) -> None:
        with self._get_conn() as conn:
            conn.execute("UPDATE tickets SET department_id=? WHERE id=?", (department_id, ticket_id))

    def delete_ticket(self, ticket_id: int) -> bool:
        """تیکت را همراه با همه‌ی پیام‌هایش برای همیشه حذف می‌کند."""
        with self._get_conn() as conn:
            if not conn.execute("SELECT 1 FROM tickets WHERE id=?", (ticket_id,)).fetchone():
                return False
            conn.execute("DELETE FROM ticket_messages WHERE ticket_id=?", (ticket_id,))
            self._ensure_ticket_group_table(conn)
            conn.execute("DELETE FROM ticket_group_messages WHERE ticket_id=?", (ticket_id,))
            conn.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))
            return True

    def delete_closed_tickets(self) -> int:
        """همه‌ی تیکت‌های بسته‌شده را حذف می‌کند و تعدادشان را برمی‌گرداند."""
        with self._get_conn() as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM tickets WHERE status='closed'").fetchall()]
            if not ids:
                return 0
            self._ensure_ticket_group_table(conn)
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM ticket_messages WHERE ticket_id IN ({marks})", chunk)
                conn.execute(f"DELETE FROM ticket_group_messages WHERE ticket_id IN ({marks})", chunk)
                conn.execute(f"DELETE FROM tickets WHERE id IN ({marks})", chunk)
            return len(ids)

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
