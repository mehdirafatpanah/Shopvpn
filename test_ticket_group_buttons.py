# -*- coding: utf-8 -*-
"""تست دکمه‌های تیکت در تاپیک پشتیبانی گروه و حذف اعلان خصوصی وقتی گروه فعال است.

اجرا: python -m unittest test_ticket_group_buttons -v
"""
import asyncio
import os
import tempfile
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="ticket_group_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import report_router  # noqa: E402
from database import Database  # noqa: E402

GROUP = -1001234
THREAD = 77


def make_db():
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    return db


class FakeBot:
    def __init__(self):
        self.sent = []
        self._mid = 1000

    async def send_message(self, chat_id, text, **kw):
        self._mid += 1
        self.sent.append({"chat_id": chat_id, "text": text, "id": self._mid, **kw})
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=self._mid)


class FakeCall:
    def __init__(self, data, user_id, msg):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, first_name="Ali", username="ali")
        self.message = msg
        self.answers = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append((text, show_alert))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class GroupTicketTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db._get_conn() as c:
            c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (100,'u100','کاربر')")
        self.db.add_admin(2) if hasattr(self.db, "add_admin") else None
        self.tid = self.db.create_ticket(100, "موضوع <تست>", "سلام & پیام اول", None)
        self.bot = FakeBot()

    def _enable_group(self):
        self.db.set_setting(report_router.SETTING_CHAT_ID, str(GROUP))
        self.db.set_report_topic(GROUP, "support", THREAD)

    def test_group_inactive_means_no_group_and_fallback(self):
        self.assertFalse(report_router.group_active(self.db))
        ok = run(report_router.notify_ticket(self.bot, self.db, self.tid, "x"))
        self.assertFalse(ok)
        self.assertEqual(self.bot.sent, [])

    def test_notify_has_two_buttons_and_links_message(self):
        self._enable_group()
        self.assertTrue(report_router.group_active(self.db))
        ok = run(report_router.notify_ticket(self.bot, self.db, self.tid, "تیکت جدید"))
        self.assertTrue(ok)
        sent = self.bot.sent[0]
        self.assertEqual(sent["message_thread_id"], THREAD)
        row = sent["reply_markup"].inline_keyboard[0]
        self.assertEqual([b.callback_data for b in row],
                         [f"grp_tk_view:{self.tid}", f"grp_tk_reply:{self.tid}"])
        self.assertEqual(self.db.get_ticket_id_by_group_message(GROUP, sent["id"]), self.tid)

    def test_view_button_sends_full_thread_in_same_topic(self):
        self._enable_group()
        self.db.add_ticket_message(self.tid, "admin", "جواب <b>پشتیبانی</b>")
        msg = SimpleNamespace(chat=SimpleNamespace(id=GROUP), message_id=5, message_thread_id=THREAD)
        call = FakeCall(f"grp_tk_view:{self.tid}", 1, msg)  # 1 = owner
        self.assertTrue(run(report_router.handle_group_ticket_callback(self.bot, self.db, call)))
        out = self.bot.sent[-1]
        self.assertEqual(out["message_thread_id"], THREAD)
        self.assertEqual(out["reply_to_message_id"], 5)
        self.assertIn("&lt;تست&gt;", out["text"])          # موضوع escape شده
        self.assertIn("&lt;b&gt;پشتیبانی&lt;/b&gt;", out["text"])
        self.assertNotIn("<b>پشتیبانی</b>", out["text"])
        self.assertEqual(self.db.get_ticket_id_by_group_message(GROUP, out["id"]), self.tid)
        self.assertEqual(call.answers[-1], (None, False))

    def test_reply_button_prompts_and_reply_goes_to_user(self):
        self._enable_group()
        msg = SimpleNamespace(chat=SimpleNamespace(id=GROUP), message_id=5, message_thread_id=THREAD)
        call = FakeCall(f"grp_tk_reply:{self.tid}", 1, msg)
        self.assertTrue(run(report_router.handle_group_ticket_callback(self.bot, self.db, call)))
        prompt = self.bot.sent[-1]
        self.assertTrue(prompt["reply_markup"].selective)
        # ریپلای مدیر روی پیام راهنما => پاسخ به کاربر ارسال و ثبت می‌شود
        import notification_i18n
        delivered = []

        async def fake_send(bot, db, uid, text, **kw):
            delivered.append((uid, text))
        orig = notification_i18n.send_telegram
        notification_i18n.send_telegram = fake_send
        try:
            reply_msg = SimpleNamespace(
                chat=SimpleNamespace(id=GROUP), message_id=9, message_thread_id=THREAD,
                reply_to_message=SimpleNamespace(message_id=prompt["id"]),
                from_user=SimpleNamespace(id=1), text="سلام، حل شد", html_text="سلام، حل شد",
            )
            self.assertTrue(run(report_router.handle_group_ticket_reply(self.bot, self.db, reply_msg)))
        finally:
            notification_i18n.send_telegram = orig
        self.assertEqual(delivered[0][0], 100)
        self.assertIn("سلام، حل شد", delivered[0][1])
        msgs = self.db.get_ticket_messages(self.tid)
        self.assertEqual(msgs[-1]["sender"], "admin")

    def test_reply_blocked_when_closed_or_claimed_by_other(self):
        self._enable_group()
        msg = SimpleNamespace(chat=SimpleNamespace(id=GROUP), message_id=5, message_thread_id=THREAD)
        self.db.close_ticket(self.tid)
        call = FakeCall(f"grp_tk_reply:{self.tid}", 1, msg)
        run(report_router.handle_group_ticket_callback(self.bot, self.db, call))
        self.assertTrue(call.answers[-1][1])          # alert
        self.assertEqual(self.bot.sent, [])

    def test_non_admin_rejected(self):
        self._enable_group()
        msg = SimpleNamespace(chat=SimpleNamespace(id=GROUP), message_id=5, message_thread_id=THREAD)
        call = FakeCall(f"grp_tk_view:{self.tid}", 999, msg)
        run(report_router.handle_group_ticket_callback(self.bot, self.db, call))
        self.assertTrue(call.answers[-1][1])
        self.assertEqual(self.bot.sent, [])

    def test_long_thread_is_trimmed_under_telegram_limit(self):
        self._enable_group()
        for i in range(60):
            self.db.add_ticket_message(self.tid, "user", f"پیام شماره {i} " + "الف" * 200)
        ticket = self.db.get_ticket(self.tid)
        text = run(report_router.build_ticket_thread_html(self.db, ticket))
        self.assertLessEqual(len(text), 4096)
        self.assertIn("پیام شماره 59", text)

    def test_group_callbacks_whitelisted(self):
        self.assertIn("grp_tk_view:", report_router.GROUP_CALLBACK_PREFIXES)
        self.assertIn("grp_tk_reply:", report_router.GROUP_CALLBACK_PREFIXES)

    def test_admin_view_hides_reply_when_group_active(self):
        import keyboards as kb
        shown = kb.admin_ticket_view_kb(self.tid, "open", "open")
        hidden = kb.admin_ticket_view_kb(self.tid, "open", "open", show_reply=False)
        flat = lambda m: [b.callback_data for r in m.inline_keyboard for b in r]
        self.assertIn(f"adm_ticket_reply:{self.tid}", flat(shown))
        self.assertNotIn(f"adm_ticket_reply:{self.tid}", flat(hidden))
        self.assertIn(f"adm_ticket_close:{self.tid}", flat(hidden))


if __name__ == "__main__":
    unittest.main()
