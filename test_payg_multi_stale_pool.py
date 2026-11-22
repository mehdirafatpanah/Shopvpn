# -*- coding: utf-8 -*-
"""رفع باگ «ساخت سرویس Pay As You Go ناموفق بود: سرویس VPN یا استخر سهمیه پیدا نشد».

وقتی استخر حساب PayG موجود stale/exceeded/expired بود (یا پاک شده بود)، ساخت چندمقصدی بعد از ساخت روی پنل
هنگام اتصال به استخر شکست می‌خورد و همه‌چیز rollback می‌شد. حالا استخر دوباره فعال (یا بازسازی) می‌شود.

اجرا: python -m unittest test_payg_multi_stale_pool -v
"""
import asyncio
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="payg_stale_pool_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import payg  # noqa: E402
from database import Database  # noqa: E402

UID = 555


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeProvider:
    async def get_user_usage(self, username):
        return {"used_bytes": 0, "uploaded_bytes": 0, "downloaded_bytes": 0}

    async def delete_user(self, username):
        return True


class StalePoolTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
        self.db.init_db(owner_id=1)
        with self.db._get_conn() as c:
            c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?,?,?)", (UID, "u", "کاربر"))
        self.db.add_wallet_credit(UID, 500000, kind="test", note="t")
        self.sid = self.db.add_panel_server("P1", "marzban", "http://x", "u", "p")
        self.db.set_setting("payg_enabled", "1")

    def _account_with_pool(self, status):
        pool_id = self.db.create_quota_pool(UID, 1_000_000_000, label="Pay As You Go", metadata={"payg": True})
        self.db.set_quota_pool_status(pool_id, status)
        with self.db._get_conn() as c:
            c.execute(
                "INSERT INTO payg_accounts(user_id,status,quota_pool_id,initial_balance,last_balance,month_key,month_rates,"
                "month_used_bytes,month_cost,last_alert_level,created_at,updated_at) "
                "VALUES(?,'active',?,0,0,'x','[]',0,0,0,'now','now')", (UID, pool_id))
        return pool_id

    def _provision(self):
        db = self.db

        async def fake_provision_vpn(db_, product, quantity=1, user_id=None, order_id=None, shared_pool=False,
                                     server_id=None, register=True, target_config_override=...):
            cc = db_.add_custom_config(user_id, server_id, "pg_user", 0, 0, "http://sub", order_id=None, source="direct_product")
            return [{"username": "pg_user", "custom_config_id": cc, "subscription_url": "http://sub",
                     "panel_server_id": server_id}]

        with mock.patch("direct_panel_provision._provision_vpn", fake_provision_vpn), \
             mock.patch("panel_providers.get_provider", lambda server: FakeProvider()), \
             mock.patch("dedicated_sub.is_enabled", lambda d: True), \
             mock.patch("dedicated_sub.panels_dsub_off_message", lambda d, ids: ""), \
             mock.patch("dedicated_sub.link_for_config", lambda d, cid: "http://central"):
            return run(payg._provision_payg_multi(db, UID, [self.sid], [], ["ssh"]))

    def _pool_status(self, pool_id):
        return self.db.get_quota_pool(pool_id)["status"] if self.db.get_quota_pool(pool_id) else None

    def test_stale_pool_is_revived_instead_of_failing(self):
        for status in ("stale", "exceeded", "expired", "error"):
            with self.subTest(status=status):
                self.setUp()
                pool_id = self._account_with_pool(status)
                result = self._provision()
                self.assertEqual(result["panels"], 1)
                with self.db._get_conn() as c:
                    acc = c.execute("SELECT quota_pool_id FROM payg_accounts WHERE user_id=?", (UID,)).fetchone()
                self.assertEqual(int(acc["quota_pool_id"]), pool_id)

    def test_deleted_pool_is_recreated_and_account_repointed(self):
        pool_id = self._account_with_pool("active")
        self.db.delete_quota_pool(pool_id)
        result = self._provision()
        self.assertEqual(result["panels"], 1)
        with self.db._get_conn() as c:
            acc = c.execute("SELECT quota_pool_id FROM payg_accounts WHERE user_id=?", (UID,)).fetchone()
        new_pool = int(acc["quota_pool_id"])
        self.assertNotEqual(new_pool, pool_id)
        self.assertIsNotNone(self.db.get_quota_pool(new_pool))

    def test_failure_restores_previous_pool_status(self):
        pool_id = self._account_with_pool("stale")
        with mock.patch("dedicated_sub.link_for_config", lambda d, cid: None):
            with self.assertRaises(RuntimeError):
                self._provision_with_no_link()
        self.assertEqual(self._pool_status(pool_id), "stale")

    def _provision_with_no_link(self):
        db = self.db

        async def fake_provision_vpn(db_, product, quantity=1, user_id=None, order_id=None, shared_pool=False,
                                     server_id=None, register=True, target_config_override=...):
            cc = db_.add_custom_config(user_id, server_id, "pg_user2", 0, 0, "http://sub", order_id=None, source="direct_product")
            return [{"username": "pg_user2", "custom_config_id": cc, "subscription_url": "http://sub",
                     "panel_server_id": server_id}]

        with mock.patch("direct_panel_provision._provision_vpn", fake_provision_vpn), \
             mock.patch("panel_providers.get_provider", lambda server: FakeProvider()), \
             mock.patch("dedicated_sub.is_enabled", lambda d: True), \
             mock.patch("dedicated_sub.panels_dsub_off_message", lambda d, ids: ""), \
             mock.patch("dedicated_sub.link_for_config", lambda d, cid: None):
            return run(payg._provision_payg_multi(db, UID, [self.sid], [], ["ssh"]))


if __name__ == "__main__":
    unittest.main()
