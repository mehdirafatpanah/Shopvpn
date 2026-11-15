# -*- coding: utf-8 -*-
"""تست تیکت و چت زنده: اولویت، سرویس مرتبط، باز/بسته، حذف و دسته‌بندی‌ها.

اجرا: python -m unittest test_tickets_chat -v
"""
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")
try:
    import aiohttp  # noqa: F401
except ImportError:
    from unittest import mock
    sys.modules["aiohttp"] = mock.MagicMock()

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tickets_chat_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

from database import Database  # noqa: E402


def make_db():
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    return db


def add_user(db, uid):
    with db._get_conn() as c:
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?,?,?)",
                  (uid, f"u{uid}", f"n{uid}"))


def add_service(db, uid, name):
    psid = db.add_panel_server("P", "pasarguard", "https://p.example.com", "u", "p")
    with db._get_conn() as c:
        cur = c.execute("INSERT INTO custom_configs (user_id, panel_server_id, username, volume_gb, display_name) "
                        "VALUES (?,?,?,?,?)", (uid, psid, name, 10, name))
        return cur.lastrowid


class TicketsTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        add_user(self.db, 100)
        add_user(self.db, 200)

    def test_ticket_priority_ref_reopen_delete(self):
        db = self.db
        sid = add_service(db, 100, "myvpn")
        kind, rid, label = db.resolve_support_service_ref(100, "custom", sid)
        self.assertEqual((kind, rid), ("custom", sid))
        # سرویس کاربر دیگر پذیرفته نمی‌شود
        self.assertEqual(db.resolve_support_service_ref(200, "custom", sid), (None, None, None))
        tid = db.create_ticket(100, "s", "m", None, ref_kind=kind, ref_id=rid, ref_label=label)
        t = db.get_ticket(tid)
        self.assertEqual(t["priority"], "medium")
        self.assertEqual(t["ref_label"], label)
        db.set_ticket_priority(tid, "high")
        self.assertEqual(db.get_ticket(tid)["priority"], "high")
        db.set_ticket_priority(tid, "bogus")
        self.assertEqual(db.get_ticket(tid)["priority"], "medium")
        db.close_ticket(tid)
        self.assertEqual(db.get_ticket(tid)["status"], "closed")
        self.assertTrue(db.reopen_ticket(tid))
        self.assertEqual(db.get_ticket(tid)["status"], "open")
        self.assertFalse(db.reopen_ticket(tid))  # باز بود
        db.close_ticket(tid)
        self.assertEqual(db.delete_closed_tickets(), 1)
        self.assertIsNone(db.get_ticket(tid))
        t2 = db.create_ticket(100, "s2", "m2")
        self.assertTrue(db.delete_ticket(t2))
        self.assertFalse(db.delete_ticket(t2))
        self.assertEqual(db.get_ticket_messages(t2), [])

    def test_departments_crud_no_resurrection(self):
        db = self.db
        deps = db.list_ticket_departments(False)
        self.assertEqual(len(deps), 4)
        new_id = db.create_ticket_department("ویژه")
        with self.assertRaises(ValueError):
            db.create_ticket_department("ویژه")
        self.assertTrue(db.update_ticket_department(new_id, name="ویژه۲", is_active=False, sort_order=5))
        self.assertEqual(db.get_ticket_department(new_id)["name"], "ویژه۲")
        self.assertNotIn(new_id, [d["id"] for d in db.list_ticket_departments(True)])
        tid = db.create_ticket(100, "s", "m", deps[0]["id"])
        self.assertEqual(db.count_tickets_in_department(deps[0]["id"]), 1)
        self.assertTrue(db.delete_ticket_department(deps[0]["id"]))
        self.assertIsNone(db.get_ticket(tid)["department_id"])
        self.assertEqual(len(db.list_ticket_departments(False)), 4)  # 4-1+1، پیش‌فرض برنگشت

    def test_live_chat_state(self):
        db = self.db
        self.assertEqual(db.get_support_conversation_state(100)["status"], "open")
        db.add_support_message(100, "user", "سلام")
        db.set_support_priority(100, "high")
        sid = add_service(db, 100, "svc")
        db.set_support_reference(100, "custom", sid, "svc")
        db.set_support_status(100, "closed")
        st = db.get_support_conversation_state(100)
        self.assertEqual((st["status"], st["priority"], st["ref_label"]), ("closed", "high", "svc"))
        conv = db.list_support_conversations()[0]
        self.assertEqual((conv["status"], conv["priority"]), ("closed", "high"))
        # پیام ادمین وضعیت را عوض نمی‌کند
        db.add_support_message(100, "admin", "پاسخ")
        self.assertEqual(db.get_support_conversation_state(100)["status"], "closed")
        # پیام کاربر باز می‌کند و اولویت می‌ماند
        db.add_support_message(100, "user", "هنوز مشکل دارم")
        st = db.get_support_conversation_state(100)
        self.assertEqual((st["status"], st["priority"]), ("open", "high"))
        db.set_support_status(100, "open")
        self.assertEqual(db.delete_support_conversation(100), 3)
        self.assertEqual(db.list_support_conversations(), [])
        self.assertEqual(db.get_support_conversation_state(100)["priority"], "medium")


class SearchHelpersTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        add_user(self.db, 100)
        add_user(self.db, 200)

    def test_normalization_and_tokens(self):
        from db.tickets import norm_search, search_tokens
        self.assertEqual(norm_search("۱۲۳ كيك  ABC"), "123 کیک abc")
        self.assertEqual(search_tokens("@Alice #12 ۱۲"), ["alice", "12", "12"])
        self.assertEqual(search_tokens("  @ # "), [])

    def test_user_names_batch(self):
        names = self.db.get_user_names([100, 200, 999])
        self.assertEqual(names[100], {"username": "u100", "first_name": "n100"})
        self.assertNotIn(999, names)
        self.assertEqual(self.db.get_user_names([]), {})

    def test_ticket_message_stats(self):
        db = self.db
        t1 = db.create_ticket(100, "s", "first")
        t2 = db.create_ticket(200, "s2", "other")
        db.add_ticket_message(t1, "admin", "reply")
        stats = db.get_ticket_message_stats()
        self.assertEqual(stats[t1], {"total": 2, "unread": 1, "last_sender": "admin"})
        self.assertEqual(stats[t2]["last_sender"], "user")
        db.mark_ticket_read_by_admin(t2)
        self.assertEqual(db.get_ticket_message_stats()[t2]["unread"], 0)

    def test_message_text_search(self):
        db = self.db
        t1 = db.create_ticket(100, "s", "کانفیگ وصل نمیشه 100%_x")
        t2 = db.create_ticket(200, "s2", "renew please")
        db.add_support_message(100, "user", "سلام پشتیبانی")
        db.add_support_message(200, "user", "Hello there")
        self.assertEqual(db.find_ticket_ids_by_text("وصل"), {t1})
        self.assertEqual(db.find_ticket_ids_by_text("RENEW"), {t2})
        self.assertEqual(db.find_ticket_ids_by_text("100%_"), {t1})
        self.assertEqual(db.find_ticket_ids_by_text("%zzz"), set())
        self.assertEqual(db.find_ticket_ids_by_text(""), set())
        self.assertEqual(db.find_support_user_ids_by_text("hello"), {200})
        self.assertEqual(db.find_support_user_ids_by_text("پشتیبانی"), {100})

    def test_conversation_messages_count(self):
        db = self.db
        db.add_support_message(100, "user", "a")
        db.add_support_message(100, "admin", "b")
        db.add_support_message(200, "user", "c")
        counts = {c["user_id"]: c["messages_count"] for c in db.list_support_conversations()}
        self.assertEqual(counts, {100: 2, 200: 1})


if __name__ == "__main__":
    unittest.main()


class UserPriorityChoiceTest(unittest.TestCase):
    """کاربر موقع ساخت تیکت / در چت زنده خودش اولویت (زیاد/متوسط/کم) را انتخاب می‌کند."""

    def setUp(self):
        self.db = make_db()
        add_user(self.db, 100)

    def test_ticket_created_with_user_priority(self):
        db = self.db
        t_high = db.create_ticket(100, "s1", "m1", priority="high")
        t_low = db.create_ticket(100, "s2", "m2", priority="low")
        t_default = db.create_ticket(100, "s3", "m3")
        t_bad = db.create_ticket(100, "s4", "m4", priority="urgent!!")
        self.assertEqual(db.get_ticket(t_high)["priority"], "high")
        self.assertEqual(db.get_ticket(t_low)["priority"], "low")
        self.assertEqual(db.get_ticket(t_default)["priority"], "medium")
        self.assertEqual(db.get_ticket(t_bad)["priority"], "medium")

    def test_bot_keyboards(self):
        import keyboards as kb
        markup = kb.ticket_priority_kb("ticket_prio", "high", "ticket_cancel")
        first = markup.inline_keyboard[0]
        self.assertEqual([b.callback_data for b in first],
                         ["ticket_prio:high", "ticket_prio:medium", "ticket_prio:low"])
        self.assertTrue(first[0].text.startswith("✅"))
        self.assertFalse(first[1].text.startswith("✅"))
        self.assertEqual(markup.inline_keyboard[-1][0].callback_data, "ticket_cancel")
        services = [{"kind": "custom", "id": 5, "label": "myvpn"}]
        m2 = kb.ticket_services_kb(services, prefix="contact_svc", cancel_callback="cancel_flow",
                                   priority_prefix="contact_prio", priority_selected="low")
        datas = [b.callback_data for row in m2.inline_keyboard for b in row]
        self.assertIn("contact_svc:custom:5", datas)
        self.assertIn("contact_prio:low", datas)
        self.assertEqual(datas[-1], "cancel_flow")
        # لیست تیکت‌ها: اولویت زیاد با 🔴 مشخص می‌شود
        tid = self.db.create_ticket(100, "urgent", "x", priority="high")
        lst = kb.tickets_list_kb(self.db.get_user_tickets(100))
        self.assertTrue(any("🔴" in b.text and f"#{tid}" in b.text for row in lst.inline_keyboard for b in row))

    def test_miniapp_endpoints(self):
        try:
            from fastapi.testclient import TestClient
            import miniapp.server as ms
        except Exception as exc:  # pragma: no cover - وابستگی‌های محیط
            self.skipTest(f"miniapp.server قابل import نیست: {exc}")
        db = self.db

        class _Tenant:
            bot_token = "123:test"

        ms.app.dependency_overrides[ms.get_verified_user] = lambda: (100, db, _Tenant())
        sent = []

        class _Session:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *a):
                return False

            async def post(self_inner, url, json=None, **kw):
                sent.append(json)

        orig = ms.aiohttp.ClientSession
        ms.aiohttp.ClientSession = lambda *a, **k: _Session()
        try:
            client = TestClient(ms.app)
            r = client.post("/api/tickets", json={"subject": "s", "message": "m", "priority": "high"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["priority"], "high")
            self.assertTrue(any("🚦 اولویت: 🔴 زیاد" in (p or {}).get("text", "") for p in sent))
            r = client.post("/api/tickets", json={"subject": "s2", "message": "m2"})
            self.assertEqual(r.json()["priority"], "medium")
            r = client.post("/api/tickets", json={"subject": "s3", "message": "m3", "priority": "zzz"})
            self.assertEqual(r.json()["priority"], "medium")
            # چت زنده
            self.assertEqual(client.get("/api/support/state").json()["priority"], "medium")
            r = client.post("/api/support/messages", json={"message": "hello", "priority": "low"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(client.get("/api/support/state").json()["priority"], "low")
            # بدون ارسال priority اولویت فعلی حفظ می‌شود
            client.post("/api/support/messages", json={"message": "again"})
            self.assertEqual(client.get("/api/support/state").json()["priority"], "low")
            client.post("/api/support/messages", json={"message": "now urgent", "priority": "high"})
            self.assertEqual(db.get_support_conversation_state(100)["priority"], "high")
        finally:
            ms.aiohttp.ClientSession = orig
            ms.app.dependency_overrides.clear()
