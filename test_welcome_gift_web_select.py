# -*- coding: utf-8 -*-
"""محصول هدیه‌ی کانفیگ عضویت در پنل وب/مینی‌اپ: لیست انتخابی به‌جای شناسه‌ی عددی.
اجرا: python -m unittest test_welcome_gift_web_select -v"""
import os
import tempfile
import time
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="wgift_select_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import extra_settings_schema as xs  # noqa: E402
from database import Database  # noqa: E402

KEY = "welcome_gift_product_id"


def make_db():
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    return db


def field(groups):
    g = [g for g in groups if g["id"] == "welcome_gift"][0]
    return [f for f in g["fields"] if f["key"] == KEY][0]


class WelcomeGiftSelectTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        cat = self.db.add_category("اشتراک‌ها")
        panel = self.db.add_panel_server("پنل ۱", "marzban", "http://x", "u", "p")
        self.linked = self.db.add_product(cat, "۳۰ روزه", 100000, provision_server_id=panel, is_auto_provision=True)
        self.unlinked = self.db.add_product(cat, "بدون پنل", 50000)

    def test_field_is_select_with_only_giftable_products(self):
        f = field(xs.groups_for("web", self.db))
        self.assertEqual(f["type"], "select")
        values = [o[0] for o in f["options"]]
        self.assertEqual(values[0], "0")
        self.assertIn(str(self.linked), values)
        self.assertNotIn(str(self.unlinked), values)
        label = dict(f["options"])[str(self.linked)]
        self.assertIn("اشتراک‌ها", label)
        self.assertIn("۳۰ روزه", label)

    def test_mini_surface_gets_same_options_and_no_db_is_safe(self):
        self.assertIn(str(self.linked), [o[0] for o in field(xs.groups_for("mini", self.db))["options"]])
        self.assertEqual(field(xs.groups_for("web"))["options"], [["0", "— انتخاب کنید —"]])

    def test_save_valid_product_sets_mode_existing(self):
        self.db.set_setting("welcome_gift_product_mode", "dedicated")
        changed = xs.save_values(self.db, "web", {KEY: str(self.linked), "welcome_gift_enabled": "1"})
        self.assertIn(KEY, changed)
        self.assertEqual(self.db.get_setting(KEY, "0"), str(self.linked))
        self.assertEqual(self.db.get_setting("welcome_gift_product_mode", ""), "existing")
        self.assertEqual(xs.load_values(self.db, "web")[KEY], str(self.linked))

    def test_rejects_bad_values(self):
        for bad in ("abc", "-1", "999", str(self.unlinked)):
            with self.assertRaises(xs.SettingsValidationError, msg=bad):
                xs.save_values(self.db, "web", {KEY: bad})
        with self.assertRaises(xs.SettingsValidationError):
            xs.save_values(self.db, "web", {"welcome_gift_enabled": "1"})  # فعال‌سازی بدون محصول

    def test_dedicated_hidden_product_stays_selectable_and_unchanged_mode(self):
        hidden = self.db.clone_product_as_hidden_gift(self.linked, "هدیه‌ی مخصوص")
        self.db.set_setting(KEY, str(hidden))
        self.db.set_setting("welcome_gift_product_mode", "dedicated")
        f = field(xs.groups_for("web", self.db))
        self.assertIn(str(hidden), [o[0] for o in f["options"]])
        self.assertIn("🎁", dict(f["options"])[str(hidden)])
        # ذخیره‌ی دوباره‌ی همان مقدار، حالت «dedicated» را خراب نمی‌کند
        xs.save_values(self.db, "web", {KEY: str(hidden)})
        self.assertEqual(self.db.get_setting("welcome_gift_product_mode", ""), "dedicated")


if __name__ == "__main__":
    unittest.main()
