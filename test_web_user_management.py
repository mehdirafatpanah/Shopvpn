# -*- coding: utf-8 -*-
"""تست مدیریت کامل کاربر/اشتراک در وب: توابع دیتابیسی که اندپوینت‌های جدید استفاده می‌کنند
و وجود مسیرها/دکمه‌ها در سورس پنل.

اجرا: python -m unittest test_web_user_management -v
"""
import os
import re
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")
try:
    import aiohttp  # noqa: F401
except ImportError:
    from unittest import mock
    sys.modules["aiohttp"] = mock.MagicMock()

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="web_usermgmt_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

from database import Database  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def make_db():
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    return db


def add_user(db, uid):
    with db._get_conn() as c:
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?,?,?)",
                  (uid, f"u{uid}", f"n{uid}"))


def add_service(db, uid, name, volume=10, days=30):
    psid = db.add_panel_server("P", "pasarguard", "https://p.example.com", "u", "p")
    exp = (datetime.utcnow() + timedelta(days=days)).isoformat()
    with db._get_conn() as c:
        cur = c.execute(
            "INSERT INTO custom_configs (user_id, panel_server_id, username, volume_gb, duration_days, expires_at, display_name) "
            "VALUES (?,?,?,?,?,?,?)", (uid, psid, name, volume, days, exp, name))
        return cur.lastrowid


class WebUserMgmtDbTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        add_user(self.db, 100)

    def test_test_limit_override(self):
        db = self.db
        self.assertTrue(db.set_user_test_limit_override(100, 5))
        self.assertEqual(db.get_user(100)["test_limit_override"], 5)
        self.assertTrue(db.set_user_test_limit_override(100, None))
        self.assertIsNone(db.get_user(100)["test_limit_override"])
        self.assertFalse(db.set_user_test_limit_override(999, 1))

    def test_discount_code_for_single_user(self):
        pairs = self.db.generate_bulk_discount_codes([100], 20, None, None)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], 100)
        self.assertTrue(self.db.get_discount_code(pairs[0][1]))

    def test_extend_and_reduce_local_record(self):
        db = self.db
        cid = add_service(db, 100, "svc1", volume=10, days=30)
        db.apply_custom_config_renewal(cid, 5, 10)
        row = db.get_custom_config_by_id(cid)
        self.assertEqual(float(row["volume_gb"]), 15.0)
        self.assertEqual(int(row["duration_days"]), 40)
        db.apply_custom_config_reduction(cid, 3, 5)
        row = db.get_custom_config_by_id(cid)
        self.assertEqual(float(row["volume_gb"]), 12.0)
        self.assertEqual(int(row["duration_days"]), 35)
        # کاهش بیش از مقدار موجود هیچ‌وقت اعمال نمی‌شود
        self.assertIsNone(db.apply_custom_config_reduction(cid, 100, 0))
        self.assertEqual(float(db.get_custom_config_by_id(cid)["volume_gb"]), 12.0)

    def test_dsub_regenerate_token(self):
        db = self.db
        cid = add_service(db, 100, "svc2")
        t1 = db.ds_get_or_create_token(cid)
        t2 = db.ds_regenerate_token(cid)
        self.assertTrue(t1 and t2)
        self.assertNotEqual(t1, t2)

    def test_full_stats_and_invoice_items(self):
        stats = self.db.get_user_full_stats(100)
        for key in ("status", "approved_orders", "total_spent", "pending_orders", "rejected_orders",
                    "total_topup", "active_configs", "referral_count"):
            self.assertIn(key, stats)
        self.assertEqual(self.db.get_user_invoice_items(100), [])


class WebUserMgmtSourceTest(unittest.TestCase):
    def test_endpoints_exist_with_users_permission(self):
        src = open(os.path.join(HERE, "admin_panel", "server.py"), encoding="utf-8").read()
        for route in ("/api/users/{tg_id}/overview", "/api/users/{tg_id}/test-limit",
                      "/api/users/{tg_id}/configs-toggle-all", "/api/users/{tg_id}/discount-code",
                      "/api/users/{tg_id}/invoice-items", "/api/users/{tg_id}/invoice",
                      "/api/custom-configs/{custom_config_id}/detail",
                      "/api/custom-configs/{custom_config_id}/extend",
                      "/api/custom-configs/{custom_config_id}/reduce",
                      "/api/custom-configs/{custom_config_id}/dsub-regenerate"):
            self.assertIn(f'"{route}"', src, route)
        # مسیرهای تغییردهنده باید پشت مجوز users باشند
        for route in ("test-limit", "configs-toggle-all", "discount-code", '"/api/users/{tg_id}/invoice"',
                      "custom_config_id}/extend", "custom_config_id}/reduce", "dsub-regenerate"):
            m = re.search(r'@app\.(?:post|put)\("[^"]*' + re.escape(route.strip('"')) + r'[^"]*"\)\n(?:async )?def \w+\([^)]*\)', src)
            self.assertIsNotNone(m, route)
            self.assertIn('require_permission("users")', m.group(0), route)

    def test_frontend_wired(self):
        js = open(os.path.join(HERE, "admin_panel", "static", "app.js"), encoding="utf-8").read()
        for needle in ("openServiceManagerModal", "renderUserAdminOps", "wireUserAdminOps",
                       "/configs-toggle-all", "/discount-code", "/test-limit", "/dsub-regenerate",
                       "/custom-configs/${ccId}/${act}"):
            self.assertIn(needle, js, needle)


class WebCategoryDescImageTest(unittest.TestCase):
    def test_description_and_media_roundtrip(self):
        db = make_db()
        cid = db.add_category("Main")
        sub = db.add_category("Sub", parent_id=cid)
        db.set_category_description(sub, "توضیح زیردسته")
        self.assertEqual(db.get_category(sub)["description"], "توضیح زیردسته")
        db.set_category_description_media(sub, [{"type": "photo", "file_id": "AAA"}, {"type": "voice", "file_id": "BBB"}])
        media = db.get_category_description_media(sub)
        self.assertEqual([m["type"] for m in media], ["photo", "voice"])
        # حذف فقط عکس، ویس می‌ماند (همان منطق اندپوینت DELETE)
        db.set_category_description_media(sub, [m for m in media if m["type"] != "photo"])
        self.assertEqual([m["type"] for m in db.get_category_description_media(sub)], ["voice"])
        with self.assertRaises(ValueError):
            db.set_category_description(sub, "x" * 2001)

    def test_sources_wired(self):
        with open(os.path.join(HERE, "admin_panel", "server.py"), encoding="utf-8") as f:
            src = f.read()
        for needle in ('"/api/categories/{cat_id}/image"', "tg_upload_photo_get_file_id", "description: Optional[str]"):
            self.assertIn(needle, src)
        with open(os.path.join(HERE, "admin_panel", "static", "app.js"), encoding="utf-8") as f:
            js = f.read()
        for needle in ("catUploadImage", "cat-edit-desc", "cat-new-desc", "cat-edit-img-del"):
            self.assertIn(needle, js)


if __name__ == "__main__":
    unittest.main()
