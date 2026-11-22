# -*- coding: utf-8 -*-
"""اشتراک هدیه عضویت: سهمیه‌ی مشترک، گزینه‌های چندگانه، ریست همگانی و ارسال مجدد.
اجرا: python -m unittest test_welcome_gift_options -v"""
import os
import tempfile
import time
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="wgift_options_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import extra_settings_schema as xs  # noqa: E402
import welcome_gift as wg  # noqa: E402
from database import Database  # noqa: E402


def make_db():
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    return db


class WelcomeGiftOptionsTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        cat = self.db.add_category("اشتراک‌ها")
        panel = self.db.add_panel_server("پنل ۱", "marzban", "http://x", "u", "p")
        self.p1 = self.db.add_product(cat, "A", 100000, provision_server_id=panel, is_auto_provision=True)
        self.p2 = self.db.add_product(cat, "B", 100000, provision_server_id=panel, is_auto_provision=True)
        self.db.set_setting("welcome_gift_enabled", "1")

    def test_no_choices_until_option_or_legacy_product(self):
        self.assertEqual(self.db.get_welcome_gift_choices(), [])
        self.assertFalse(self.db.enqueue_welcome_gift(10, 0))
        self.db.set_setting("welcome_gift_product_id", str(self.p1))
        choices = self.db.get_welcome_gift_choices()
        self.assertEqual([c["id"] for c in choices], [0])
        self.assertTrue(self.db.enqueue_welcome_gift(10, 0))

    def test_options_replace_legacy_and_inactive_hidden(self):
        self.db.set_setting("welcome_gift_product_id", str(self.p1))
        a = self.db.add_welcome_gift_option("سرور آلمان", self.p1)
        b = self.db.add_welcome_gift_option("سرور هلند", self.p2, "5", "30")
        self.assertEqual([c["id"] for c in self.db.get_welcome_gift_choices()], [a, b])
        self.db.toggle_welcome_gift_option(a)
        self.assertEqual([c["id"] for c in self.db.get_welcome_gift_choices()], [b])
        self.db.toggle_welcome_gift_option(b)
        self.assertEqual([c["id"] for c in self.db.get_welcome_gift_choices()], [0])

    def test_quota_is_shared_and_consumed_only_after_delivery(self):
        a = self.db.add_welcome_gift_option("A", self.p1)
        b = self.db.add_welcome_gift_option("B", self.p2)
        self.assertEqual(self.db.welcome_gift_quota(7), "available")
        self.assertTrue(self.db.enqueue_welcome_gift(7, a))
        self.assertEqual(self.db.welcome_gift_quota(7), "pending")
        self.assertFalse(self.db.enqueue_welcome_gift(7, b))
        claimed = self.db.claim_due_welcome_gifts(5)
        self.assertEqual((claimed[0]["user_id"], claimed[0]["option_id"]), (7, a))
        self.db.finish_welcome_gift(7, "failed", "x")
        self.assertEqual(self.db.welcome_gift_quota(7), "available")
        self.assertTrue(self.db.enqueue_welcome_gift(7, b))
        self.db.claim_due_welcome_gifts(5)
        self.db.finish_welcome_gift(7, "done")
        self.assertEqual(self.db.welcome_gift_quota(7), "used")
        self.assertFalse(self.db.enqueue_welcome_gift(7, a))

    def test_later_keeps_quota_and_hides_offer(self):
        a = self.db.add_welcome_gift_option("A", self.p1)
        self.db.defer_welcome_gift(8)
        self.assertEqual(self.db.welcome_gift_quota(8), "available")
        self.assertIsNotNone(self.db.get_welcome_gift_status(8))
        self.assertEqual(self.db.claim_due_welcome_gifts(5), [])
        self.assertTrue(self.db.enqueue_welcome_gift(8, a))
        self.assertEqual(self.db.welcome_gift_quota(8), "pending")

    def test_reset_all_gives_everyone_a_new_share(self):
        a = self.db.add_welcome_gift_option("A", self.p1)
        for uid in (1, 2):
            self.db.enqueue_welcome_gift(uid, a)
        self.db.claim_due_welcome_gifts(5)
        self.db.finish_welcome_gift(1, "done")
        self.db.defer_welcome_gift(3)
        self.assertEqual(self.db.reset_all_welcome_gifts(), 1)
        self.assertEqual(self.db.welcome_gift_quota(1), "available")
        self.assertEqual(self.db.welcome_gift_quota(2), "pending")
        self.assertTrue(self.db.enqueue_welcome_gift(1, a))

    def test_resend_is_unlimited_and_independent_of_quota(self):
        a = self.db.add_welcome_gift_option("A", self.p1)
        self.db.enqueue_welcome_gift(5, a)
        self.db.claim_due_welcome_gifts(5)
        self.db.finish_welcome_gift(5, "done")
        first = self.db.enqueue_welcome_gift_resend(5, a, 99)
        second = self.db.enqueue_welcome_gift_resend(5, a, 99)
        jobs = self.db.claim_due_welcome_gift_resends(5)
        self.assertEqual({j["id"] for j in jobs}, {first, second})
        self.assertEqual(self.db.welcome_gift_quota(5), "used")
        self.db.finish_welcome_gift_resend(first, "done")
        self.assertEqual(self.db.retry_or_fail_welcome_gift_resend(second, "e", delivery_only=True), "provisioned")

    def test_gift_product_uses_option_then_global_then_product_defaults(self):
        product = dict(self.db.get_product(self.p1))
        self.db.set_setting("welcome_gift_volume_gb", "2")
        gift = wg.build_gift_product(self.db, product, {"volume_gb": "7", "days": ""})
        self.assertEqual(gift["auto_provision_volume_gb"], 7.0)
        self.assertNotEqual(gift.get("duration_days"), 0)
        gift = wg.build_gift_product(self.db, product, {"volume_gb": "", "days": "15"})
        self.assertEqual((gift["auto_provision_volume_gb"], gift["duration_days"]), (2.0, 15.0))
        self.assertEqual(gift["price"], 0)

    def test_enabling_via_settings_accepts_options_without_legacy_product(self):
        with self.assertRaises(xs.SettingsValidationError):
            xs.save_values(self.db, "web", {"welcome_gift_enabled": "1"})
        self.db.add_welcome_gift_option("A", self.p1)
        xs.save_values(self.db, "web", {"welcome_gift_enabled": "1"})


if __name__ == "__main__":
    unittest.main()
