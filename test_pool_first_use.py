# -*- coding: utf-8 -*-
"""شروع زمان از اولین اتصال برای محصول چندپنلی/نودی (استخر سهمیه مشترک).

اجرا: python -m unittest test_pool_first_use -v
"""
import asyncio
import json
import unittest
from datetime import datetime, timezone

import test_multi_target as tm
from test_multi_target import dpp, make_world, run, QuotaReconciler


class UsagePanel(tm.FakePanel):
    def __init__(self, name):
        super().__init__(name)
        self.used = 0

    async def get_user_usage(self, username):
        return {"used_bytes": self.used, "data_limit_bytes": 0, "status": "active"}


def world(first_use):
    db, ids, fakes, product = tm.make_world()
    for sid in ids:
        fakes[sid] = UsagePanel(f"p{sid}")
    dpp.get_provider = lambda server: fakes[int(server["id"])]
    db.set_product_extra_targets(product["id"], [ids[1]], [])
    db.edit_product(product["id"], start_on_first_use=first_use)
    return db, ids, fakes, db.get_product(product["id"])


class PoolFirstUseTests(unittest.TestCase):
    def test_purchase_mode_unchanged(self):
        db, ids, fakes, product = world(False)
        items = run(dpp.provision_direct(db, product, 1, user_id=100, order_id=None))
        pool = db.quota_pool_for_custom_config(items[0]["custom_config_id"])
        self.assertTrue(pool["expires_at"])
        self.assertFalse(db.quota_pool_first_use_pending(pool))

    def test_first_use_waits_then_starts_on_any_member(self):
        db, ids, fakes, product = world(True)
        items = run(dpp.provision_direct(db, product, 1, user_id=100, order_id=None))
        cc_id = items[0]["custom_config_id"]
        pool = db.quota_pool_for_custom_config(cc_id)
        self.assertIsNone(pool["expires_at"])
        self.assertTrue(db.quota_pool_first_use_pending(pool))
        self.assertEqual(json.loads(pool["metadata_json"])["first_use_days"], 30.0)
        cc = db.get_custom_config(cc_id) if hasattr(db, "get_custom_config") else None
        with db._get_conn() as conn:
            row = conn.execute("SELECT expires_at,start_on_first_use FROM custom_configs WHERE id=?", (cc_id,)).fetchone()
            self.assertIsNone(row["expires_at"]); self.assertEqual(row["start_on_first_use"], 1)
        # on-hold sync must not touch pool members
        self.assertEqual([r["config_id"] for r in db.get_custom_configs_due_for_onhold_sync()], [])

        rec = QuotaReconciler(db, vpn_provider_factory=lambda server: fakes[int(server["id"])])
        run(rec.reconcile_pool(db.get_quota_pool(pool["id"])))
        self.assertIsNone(db.get_quota_pool(pool["id"])["expires_at"])  # no usage yet

        fakes[ids[1]].used = 5 * 1024 * 1024  # first connection through the EXTRA panel
        run(rec.reconcile_pool(db.get_quota_pool(pool["id"])))
        after = db.get_quota_pool(pool["id"])
        self.assertTrue(after["expires_at"])
        days = (datetime.fromisoformat(after["expires_at"]) - datetime.now(timezone.utc)).total_seconds() / 86400
        self.assertTrue(29.9 < days <= 30.0, days)
        self.assertFalse(db.quota_pool_first_use_pending(after))
        with db._get_conn() as conn:
            row = conn.execute("SELECT expires_at FROM custom_configs WHERE id=?", (cc_id,)).fetchone()
        self.assertEqual(row["expires_at"], after["expires_at"])
        # idempotent
        self.assertIsNone(db.activate_quota_pool_first_use(pool["id"]))

    def test_renewal_before_start_extends_stored_duration(self):
        import renewal_engine
        db, ids, fakes, product = world(True)
        items = run(dpp.provision_direct(db, product, 1, user_id=100, order_id=None))
        pool = db.quota_pool_for_custom_config(items[0]["custom_config_id"])
        renewal_engine._renew_quota_pool(db, pool, "full", 0, 30)
        after = db.get_quota_pool(pool["id"])
        self.assertIsNone(after["expires_at"])
        self.assertEqual(json.loads(after["metadata_json"])["first_use_days"], 60.0)

    def test_unsupported_panel_type_disables_first_use(self):
        db, ids, fakes, product = world(True)
        sid = db.add_panel_server("H", "hiddify", "https://h.example.com", "u", "p")
        self.assertTrue(dpp.pool_first_use(db, product, ids[:2]))
        self.assertFalse(dpp.pool_first_use(db, product, ids[:2] + [sid]))
        self.assertTrue(dpp.pool_first_use(db, product, []))  # nodes only


if __name__ == "__main__":
    unittest.main()
