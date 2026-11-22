# -*- coding: utf-8 -*-
"""تست جداسازی تاپیک «چت زنده» و «تیکت‌ها» در گروه گزارش (آیتم ۳۳).

هر پیام فقط در تاپیک هم‌نوع خودش می‌نشیند؛ ریپلای مدیر روی هر دو نوع به مقصد درست می‌رسد.
اجرا: python -m unittest test_support_topics_split -v
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

_TMP = tempfile.mkdtemp(prefix="support_split_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import report_router  # noqa: E402
from database import Database  # noqa: E402

GROUP = -1001234
TICKET_THREAD = 77
LIVE_THREAD = 88


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


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


class SupportTopicsSplitTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        with self.db._get_conn() as c:
            c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (100,'u100','کاربر')")
        self.tid = self.db.create_ticket(100, "موضوع", "پیام اول", None)
        self.bot = FakeBot()
        self.db.set_setting(report_router.SETTING_CHAT_ID, str(GROUP))
        self.db.set_report_topic(GROUP, "support", TICKET_THREAD)
        self.db.set_report_topic(GROUP, "live_chat", LIVE_THREAD)

    def test_two_separate_topic_specs(self):
        self.assertIn("support", report_router.SPECS)
        self.assertIn("live_chat", report_router.SPECS)
        self.assertNotEqual(report_router.SPECS["support"].name, report_router.SPECS["live_chat"].name)

    def test_ticket_goes_only_to_ticket_topic(self):
        self.assertTrue(run(report_router.notify_ticket(self.bot, self.db, self.tid, "تیکت جدید")))
        self.assertEqual([m["message_thread_id"] for m in self.bot.sent], [TICKET_THREAD])

    def test_live_chat_goes_only_to_live_chat_topic(self):
        self.assertTrue(run(report_router.notify_live_chat(self.bot, self.db, 100, "پیام زنده")))
        self.assertEqual([m["message_thread_id"] for m in self.bot.sent], [LIVE_THREAD])
        sent = self.bot.sent[0]
        self.assertEqual(self.db.get_live_chat_user_by_group_message(GROUP, sent["id"]), 100)
        self.assertIsNone(self.db.get_ticket_id_by_group_message(GROUP, sent["id"]))

    def test_mixed_traffic_stays_separated(self):
        run(report_router.notify_live_chat(self.bot, self.db, 100, "a"))
        run(report_router.notify_ticket(self.bot, self.db, self.tid, "b"))
        run(report_router.notify_live_chat(self.bot, self.db, 100, "c"))
        got = {(m["text"], m["message_thread_id"]) for m in self.bot.sent}
        self.assertEqual(got, {("a", LIVE_THREAD), ("b", TICKET_THREAD), ("c", LIVE_THREAD)})

    def test_private_mode_sends_nothing_to_group(self):
        self.db.set_setting(report_router.SUPPORT_PRIVATE_KEY, "1")
        self.assertFalse(run(report_router.notify_live_chat(self.bot, self.db, 100, "x")))
        self.assertFalse(run(report_router.notify_ticket(self.bot, self.db, self.tid, "y")))
        self.assertEqual(self.bot.sent, [])

    def test_disabled_live_chat_topic_falls_back_to_other_not_tickets(self):
        self.db.set_report_topic(GROUP, "other", 99)
        report_router.set_pref(self.db, "live_chat", enabled=False)
        run(report_router.notify_live_chat(self.bot, self.db, 100, "x"))
        self.assertEqual([m["message_thread_id"] for m in self.bot.sent], [99])


if __name__ == "__main__":
    unittest.main()
