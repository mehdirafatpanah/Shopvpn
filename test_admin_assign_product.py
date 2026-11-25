# -*- coding: utf-8 -*-
"""اختصاص محصول به کاربر از پنل وب: توابع دیتابیس سفارش اختصاصی. اجرا: python -m unittest test_admin_assign_product -v"""
import os
import tempfile
import time
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="assign_product_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

from database import Database  # noqa: E402


class AssignProductDbTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
        self.db.init_db(owner_id=1)
        cat = self.db.add_category("cat")
        self.pid = self.db.add_product(cat, "stock-product", 100000)
        self.db.add_configs(self.pid, ["vless://a", "vless://b"])

    def test_grant_order_is_free_hidden_from_pending_and_marks_config(self):
        order_id = self.db.create_admin_grant_order(555, self.pid, 1)
        order = self.db.get_order(order_id)
        self.assertEqual((order["status"], order["final_price"], order["base_price"]), ("processing", 0, 0))
        rows = self.db.take_unused_configs(self.pid, 555, 1)
        self.assertTrue(self.db.finish_admin_grant_order(order_id, [rows[0]["id"]]))
        order = self.db.get_order(order_id)
        self.assertEqual(order["status"], "approved")
        self.assertEqual(order["config_id"], rows[0]["id"])
        self.assertIn(self.pid, self.db.get_user_approved_product_ids(555))
        self.assertFalse(self.db.finish_admin_grant_order(order_id, [rows[0]["id"]]))

    def test_discard_removes_only_unfinished_grant_order(self):
        failed = self.db.create_admin_grant_order(555, self.pid, 1)
        self.db.discard_admin_grant_order(failed)
        self.assertIsNone(self.db.get_order(failed))
        done = self.db.create_admin_grant_order(555, self.pid, 1)
        self.db.finish_admin_grant_order(done)
        self.db.discard_admin_grant_order(done)
        self.assertIsNotNone(self.db.get_order(done))

    def test_user_without_orders_owns_nothing(self):
        self.assertEqual(self.db.get_user_approved_product_ids(777), set())


if __name__ == "__main__":
    unittest.main()
