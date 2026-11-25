import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

try:
    import aiohttp  # noqa: F401
except ImportError:
    sys.modules["aiohttp"] = MagicMock()
    sys.modules["aiohttp_socks"] = MagicMock()

import panel_resync
from quota_reconciler import QuotaReconciler


class FakeProvider:
    supports_template_resync = True

    def __init__(self, changed):
        self.changed = changed
        self.calls = []

    async def resync_user_template(self, username):
        self.calls.append(username)
        return self.changed


class FakeDb:
    def get_panel_server(self, sid):
        return {"id": sid}


class HealTests(unittest.TestCase):
    def setUp(self):
        panel_resync._last_heal.clear()
        self.provider = FakeProvider(True)
        panel_resync.get_provider = lambda server: self.provider

    def test_heal_then_cooldown(self):
        cc = {"id": 7, "panel_server_id": 1, "username": "u"}
        self.assertTrue(asyncio.run(panel_resync.heal_config(FakeDb(), cc)))
        self.assertFalse(asyncio.run(panel_resync.heal_config(FakeDb(), cc)))
        self.assertEqual(self.provider.calls, ["u"])

    def test_no_panel_server(self):
        cc = {"id": 8, "username": "u"}
        self.assertFalse(asyncio.run(panel_resync.heal_config(FakeDb(), cc)))


class GraceTests(unittest.TestCase):
    def test_oldest_age(self):
        rec = QuotaReconciler(MagicMock())
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        age = rec._oldest_snapshot_age([{"reported_at": old}, {"reported_at": new}])
        self.assertTrue(390 < age < 420)
        self.assertEqual(rec._oldest_snapshot_age([{"reported_at": None}]), float("inf"))


if __name__ == "__main__":
    unittest.main()


class BindingTests(unittest.TestCase):
    def test_norm_binding(self):
        from panel_providers.base import BasePanelProvider as B
        self.assertEqual(B._norm_binding({"vless": ["b", "a"]}), B._norm_binding({"vless": ["a", "b"]}))
        self.assertEqual(B._norm_binding([2, 1]), B._norm_binding(["1", "2"]))
        self.assertNotEqual(B._norm_binding([1]), B._norm_binding([1, 2]))
        self.assertEqual(B._norm_binding(None), [])


class ProductTargetKeptTests(unittest.TestCase):
    """رگرسیون: همگام‌سازی نباید مقصد انتخاب‌شده‌ی محصول (مثلاً یک interface از W-UI) را با کل قالب سرور بنویسد."""

    def setUp(self):
        import json
        panel_resync._last_heal.clear()
        self.seen = []
        self.server = {"id": 1, "panel_type": "wui", "group_ids": json.dumps([1, 2, 3, 4])}

        class Db:
            def get_panel_server(_self, sid):
                return dict(self.server)

        self.db = Db()
        outer = self

        class Prov:
            supports_template_resync = True

            def __init__(self, server):
                self.group_ids = server["group_ids"]

            async def resync_user_template(self, username):
                outer.seen.append(self.group_ids)
                return False

        panel_resync.get_provider = lambda server: Prov(server)

    def test_product_target_applied(self):
        import json
        cfg = json.dumps({"field": "group_ids", "value": [2], "panel_server_id": 1})
        cc = {"id": 21, "panel_server_id": 1, "username": "u", "panel_target_config": cfg}
        asyncio.run(panel_resync.heal_config(self.db, cc))
        self.assertEqual(json.loads(self.seen[0]), [2])

    def test_legacy_config_uses_server_template(self):
        import json
        cc = {"id": 22, "panel_server_id": 1, "username": "u", "panel_target_config": None}
        asyncio.run(panel_resync.heal_config(self.db, cc))
        self.assertEqual(json.loads(self.seen[0]), [1, 2, 3, 4])


class WuiSnapshotGuardTests(unittest.TestCase):
    """رگرسیون: resync در W-UI مجموعه‌ی interface ها را جایگزین میکند؛ بدون مقصد ثبت‌شده‌ی سرویس نباید اجرا شود
    (وگرنه interface های انتخاب‌نشده اضافه و مثلاً OpenVPN انتخاب‌شده حذف میشد)."""

    class WuiLike(FakeProvider):
        resync_needs_snapshot = True

    def setUp(self):
        panel_resync._last_heal.clear()
        self.provider = self.WuiLike(True)
        panel_resync.get_provider = lambda server: self.provider

    def test_skipped_without_snapshot(self):
        cc = {"id": 21, "panel_server_id": 1, "username": "u", "panel_target_config": None}
        self.assertFalse(asyncio.run(panel_resync.heal_config(FakeDb(), cc)))
        self.assertEqual(self.provider.calls, [])

    def test_runs_with_snapshot(self):
        cc = {"id": 22, "panel_server_id": 1, "username": "u",
              "panel_target_config": '{"field": "group_ids", "value": [3], "panel_server_id": 1}'}
        self.assertTrue(asyncio.run(panel_resync.heal_config(FakeDb(), cc)))
        self.assertEqual(self.provider.calls, ["u"])
