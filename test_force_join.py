# -*- coding: utf-8 -*-
"""تست عضویت اجباری: تشخیص درست عضو/غیرعضو (از جمله restricted) و رفتار middleware."""
import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace

from aiogram.types import Chat, Message, User

import force_join as fj
from force_join_channels import is_not_member_error, membership_from_status


class FakeBot:
    def __init__(self, result):
        self.result, self.calls = result, 0

    async def get_chat_member(self, channel, user_id):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class StatusTests(unittest.TestCase):
    def test_statuses(self):
        for ok in ("member", "administrator", "creator"):
            self.assertTrue(membership_from_status(ok), ok)
        for bad in ("left", "kicked"):
            self.assertFalse(membership_from_status(bad), bad)

    def test_restricted_depends_on_is_member(self):
        self.assertTrue(membership_from_status("restricted", True))
        self.assertFalse(membership_from_status("restricted", False))

    def test_unknown_status_fails_open(self):
        self.assertTrue(membership_from_status("something_new"))

    def test_error_text(self):
        self.assertTrue(is_not_member_error("Bad Request: user not found"))
        self.assertFalse(is_not_member_error("Bad Request: chat not found"))


class IsMemberTests(unittest.TestCase):
    def run_(self, result):
        bot = FakeBot(result)
        return asyncio.run(fj.is_channel_member(bot, "@c", 5)), bot

    def test_restricted_not_member(self):
        r = SimpleNamespace(status="restricted", is_member=False)
        self.assertFalse(self.run_(r)[0])

    def test_member_and_left(self):
        self.assertTrue(self.run_(SimpleNamespace(status="member"))[0])
        self.assertFalse(self.run_(SimpleNamespace(status="left"))[0])

    def test_user_not_found_means_not_member(self):
        self.assertFalse(self.run_(Exception("Bad Request: user not found"))[0])

    def test_config_error_fails_open_without_retry(self):
        ok, bot = self.run_(Exception("Bad Request: chat not found"))
        self.assertTrue(ok)
        self.assertEqual(bot.calls, 1)


class FakeDb:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def get_force_join_settings(self):
        return {"enabled": self.enabled, "channels": ["@mychannel"], "channel": "@mychannel"}

    def is_admin(self, uid): return False
    def is_user_language_selected(self, uid): return True
    def is_force_join_exempt(self, uid): return False
    def get_terms_settings(self): return {"enabled": False, "text": ""}
    def is_terms_accepted(self, uid): return True


class MiddlewareTests(unittest.TestCase):
    def run_flow(self, member_result):
        sent, reached = [], []

        async def fake_answer(self, text, **kw):
            sent.append((text, kw.get("reply_markup")))

        orig = Message.answer
        Message.answer = fake_answer
        try:
            user = User(id=5, is_bot=False, first_name="u")
            msg = Message.model_construct(message_id=1, date=datetime.now(), chat=Chat(id=5, type="private"),
                                          from_user=user, text="سلام")

            async def handler(event, data):
                reached.append(1)

            mw = fj.ForceJoinMiddleware(FakeDb())
            asyncio.run(mw(handler, msg, {"event_from_user": user, "bot": FakeBot(member_result)}))
        finally:
            Message.answer = orig
        return sent, reached

    def test_non_member_gets_join_message_and_handler_blocked(self):
        sent, reached = self.run_flow(SimpleNamespace(status="left"))
        self.assertEqual(reached, [])
        self.assertEqual(len(sent), 1)
        self.assertIn("عضو", sent[0][0])
        self.assertTrue(any(b.callback_data == fj.CHECK_CALLBACK for row in sent[0][1].inline_keyboard for b in row))

    def test_restricted_non_member_blocked(self):
        sent, reached = self.run_flow(SimpleNamespace(status="restricted", is_member=False))
        self.assertEqual(reached, [])
        self.assertEqual(len(sent), 1)

    def test_member_passes_after_joining(self):
        sent, reached = self.run_flow(SimpleNamespace(status="member"))
        self.assertEqual(reached, [1])
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
