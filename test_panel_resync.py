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
