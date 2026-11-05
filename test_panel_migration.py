# -*- coding: utf-8 -*-
"""تست مهاجرت کاربران بین پنل‌ها.

اجرا: python -m unittest test_panel_migration -v
"""

import asyncio
import os
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

try:
    import aiohttp  # noqa: F401
except ImportError:
    from unittest import mock
    sys.modules["aiohttp"] = mock.MagicMock()

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="panel_migration_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import panel_migration as pm  # noqa: E402
from database import Database  # noqa: E402
from panel_providers import PanelError, PanelUsernameTakenError  # noqa: E402

GB = 1024 ** 3


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakePanel:
    supports_user_limit = False
    supports_data_limit_sync = True

    def __init__(self, name, down=False, fail_create=False):
        self.name, self.down, self.fail_create = name, down, fail_create
        self.users = {}          # username → dict(volume_gb, days, enabled)
        self.usage = {}          # username → (used, limit)
        self.deleted, self.disabled, self.limit_sync = [], [], []

    async def create_user(self, username, volume_gb, duration_days, **kwargs):
        if self.fail_create:
            raise PanelError("template missing")
        if username in self.users:
            raise PanelUsernameTakenError("taken")
        self.users[username] = {"volume_gb": volume_gb, "days": duration_days, "kwargs": kwargs}
        return types.SimpleNamespace(username=username, subscription_url=f"https://{self.name}.example.com/sub/{username}")

    async def delete_user(self, username):
        self.deleted.append(username)
        self.users.pop(username, None)
        return True

    async def get_user_usage(self, username):
        if self.down:
            raise PanelError("panel down")
        used, limit = self.usage.get(username, (0, 0))
        return {"used_bytes": used, "data_limit_bytes": limit, "status": "active"}

    async def set_data_limit_bytes(self, username, limit_bytes, reenable=False):
        self.limit_sync.append((username, limit_bytes))

    async def set_enabled(self, username, enabled):
        if not enabled:
            self.disabled.append(username)

    async def check_connection(self):
        return (not self.down), ("" if not self.down else "down")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def make_world(dsub=True, types_=("3xui", "pasarguard")):
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    if dsub:
        db.set_setting("dsub_enabled", "1")
        db.set_setting("dsub_base_url", "https://sub.example.com")
    ids, fakes = [], {}
    for i, ptype in enumerate(types_):
        sid = db.add_panel_server(f"P{i + 1}", ptype, f"https://p{i + 1}.example.com", "u", "p")
        ids.append(sid)
        fakes[sid] = FakePanel(f"p{i + 1}")
    pm.get_provider = lambda server: fakes[int(server["id"])]
    return db, ids, fakes


def add_service(db, fakes, sid, user_id, username, volume_gb, used_gb, days_left, enabled=True):
    expires = (datetime.now(timezone.utc) + timedelta(days=days_left)).isoformat() if days_left is not None else None
    cc_id = db.add_custom_config(user_id, sid, username, volume_gb, 30, f"https://old.example.com/sub/{username}",
                                 expires_at=expires, source="direct_product")
    fakes[sid].users[username] = {"volume_gb": volume_gb}
    fakes[sid].usage[username] = (int(used_gb * GB), int(volume_gb * GB))
    if not enabled:
        with db._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET enabled=0 WHERE id=?", (cc_id,))
    return cc_id


class PanelMigrationTests(unittest.TestCase):
    def test_remaining_volume_and_time_are_carried_across_panel_types(self):
        db, ids, fakes = make_world()
        cc = add_service(db, fakes, ids[0], 11, "alice", volume_gb=10, used_gb=4, days_left=9.5)
        bot = FakeBot()
        report = run(pm.run_migration(db, ids[0], ids[1], pm.Options(), bot=bot, admin_id=1))
        self.assertTrue(report["ok"])
        self.assertEqual(report["migrated"], 1)
        row = db.get_custom_config_by_id(cc)
        self.assertEqual(row["panel_server_id"], ids[1])
        self.assertEqual(row["username"], "alice")
        self.assertIn("p2.example.com", row["subscription_url"])
        created = fakes[ids[1]].users["alice"]
        self.assertAlmostEqual(created["volume_gb"], 6.0, places=3)
        self.assertEqual(created["days"], 10)  # 9.5 روز → گردشده به بالا
        self.assertEqual(fakes[ids[1]].limit_sync[-1], ("alice", 6 * GB))
        # کاربر قدیمی دست‌نخورده است
        self.assertIn("alice", fakes[ids[0]].users)
        self.assertEqual(fakes[ids[0]].deleted, [])
        self.assertEqual(fakes[ids[0]].disabled, [])
        # پیام با لینک ساب (اختصاصی) به کاربر رفت
        self.assertEqual(len(bot.sent), 1)
        self.assertEqual(bot.sent[0][0], 11)
        self.assertIn("https://sub.example.com/s/", bot.sent[0][1])
        # تاریخچه
        events = [h["event_type"] for h in db.get_custom_config_history(cc)]
        self.assertIn("panel_migration", events)

    def test_without_dedicated_sub_user_gets_new_panel_link(self):
        db, ids, fakes = make_world(dsub=False)
        add_service(db, fakes, ids[0], 12, "bob", 5, 1, 20)
        bot = FakeBot()
        run(pm.run_migration(db, ids[0], ids[1], pm.Options(), bot=bot, admin_id=1))
        self.assertIn("https://p2.example.com/sub/bob", bot.sent[0][1])
        self.assertIn("دیگر کار نمی", bot.sent[0][1])

    def test_old_users_disabled_only_when_requested(self):
        db, ids, fakes = make_world()
        add_service(db, fakes, ids[0], 13, "carol", 5, 1, 20)
        run(pm.run_migration(db, ids[0], ids[1], pm.Options(disable_old=True, notify_users=False), admin_id=1))
        self.assertEqual(fakes[ids[0]].disabled, ["carol"])
        self.assertEqual(fakes[ids[0]].deleted, [])

    def test_expired_and_exhausted_are_skipped_and_stay_on_old_panel(self):
        db, ids, fakes = make_world()
        expired = add_service(db, fakes, ids[0], 14, "old", 5, 1, -2)
        full = add_service(db, fakes, ids[0], 15, "full", 5, 5, 10)
        ok = add_service(db, fakes, ids[0], 16, "fine", 5, 1, 10)
        report = run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        self.assertEqual((report["migrated"], report["skipped"], report["failed"]), (1, 2, 0))
        self.assertEqual(db.get_custom_config_by_id(expired)["panel_server_id"], ids[0])
        self.assertEqual(db.get_custom_config_by_id(full)["panel_server_id"], ids[0])
        self.assertEqual(db.get_custom_config_by_id(ok)["panel_server_id"], ids[1])

    def test_unreachable_source_uses_db_estimate_and_flags_it(self):
        db, ids, fakes = make_world()
        add_service(db, fakes, ids[0], 17, "dave", 8, 3, 15)
        fakes[ids[0]].down = True
        report = run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        self.assertEqual(report["migrated"], 1)
        self.assertEqual(report["estimated"], 1)
        self.assertAlmostEqual(fakes[ids[1]].users["dave"]["volume_gb"], 8.0, places=3)

    def test_unreachable_source_fails_when_estimate_not_allowed(self):
        db, ids, fakes = make_world()
        cc = add_service(db, fakes, ids[0], 18, "erin", 8, 3, 15)
        fakes[ids[0]].down = True
        report = run(pm.run_migration(db, ids[0], ids[1], pm.Options(allow_estimate=False, notify_users=False), admin_id=1))
        self.assertEqual(report["failed"], 1)
        self.assertEqual(db.get_custom_config_by_id(cc)["panel_server_id"], ids[0])

    def test_db_failure_rolls_back_user_on_destination(self):
        db, ids, fakes = make_world()
        cc = add_service(db, fakes, ids[0], 19, "frank", 5, 1, 10)

        def boom(*a, **k):
            raise RuntimeError("db locked")
        db.pm_switch_primary = boom
        report = run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        self.assertEqual(report["failed"], 1)
        self.assertEqual(fakes[ids[1]].deleted, ["frank"])
        self.assertNotIn("frank", fakes[ids[1]].users)
        self.assertEqual(db.get_custom_config_by_id(cc)["panel_server_id"], ids[0])

    def test_aborts_after_repeated_failures_without_touching_sales(self):
        db, ids, fakes = make_world()
        for i in range(6):
            add_service(db, fakes, ids[0], 30 + i, f"u{i}", 5, 1, 10)
        fakes[ids[1]].fail_create = True
        cat = db.add_category("C")
        pid = db.add_product(cat, "P", 1000, "", 30, True, 10, ids[0])
        report = run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        self.assertTrue(report["aborted"])
        self.assertEqual(report["migrated"], 0)
        self.assertLess(report["failed"] + report["skipped"], 6)
        self.assertEqual(db.get_product(pid)["provision_server_id"], ids[0])

    def test_sales_follow_the_migration(self):
        db, ids, fakes = make_world(types_=("3xui", "pasarguard", "marzban"))
        add_service(db, fakes, ids[0], 40, "gina", 5, 1, 10)
        cat = db.add_category("C")
        pid = db.add_product(cat, "P", 1000, "", 30, True, 10, ids[0])
        pid2 = db.add_product(cat, "Q", 1000, "", 30, True, 10, ids[2])
        db.set_product_extra_targets(pid2, [ids[0], ids[1]], [])
        report = run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        self.assertEqual(report["migrated"], 1)
        self.assertEqual(db.get_product(pid)["provision_server_id"], ids[1])
        # Q: مبدأ در extra بود و مقصد هم از قبل در extra بود → فقط یک بار می‌ماند
        extra = db.get_product_extra_targets(pid2)["panels"]
        self.assertEqual(extra, [ids[1]])

    def test_multi_panel_link_and_pool_usage_are_preserved(self):
        db, ids, fakes = make_world(types_=("3xui", "pasarguard", "marzban"))
        cc = add_service(db, fakes, ids[0], 50, "hank", 10, 0, 10)
        link_user = "hank_l"
        fakes[ids[1]].users[link_user] = {"volume_gb": 0}
        link_id = db.add_config_panel_link(cc, ids[1], link_user, "https://old2.example.com/sub/x")
        pool = db.create_quota_pool(50, 10, (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(), label="m")
        db.attach_custom_config_to_quota_pool(pool, cc)
        db.attach_quota_service(pool, "vpn", f"panel_link:{link_id}", node_id=ids[1])
        sid = f"panel_link:{link_id}"
        db.record_usage_snapshot("vpn", sid, 3 * GB, source="t")
        report = run(pm.run_migration(db, ids[1], ids[2], pm.Options(notify_users=False), admin_id=1))
        self.assertEqual(report["migrated"], 1)
        link = db.panel_links_for_config(cc)[0]
        self.assertEqual(link["panel_server_id"], ids[2])
        self.assertIn("p3.example.com", link["subscription_url"])
        # روی مقصد نامحدود ساخته می‌شود (سقف را استخر اعمال می‌کند)
        self.assertEqual(fakes[ids[2]].users[link_user]["volume_gb"], 0.0)
        # شمارنده‌ی مقصد از صفر شروع می‌شود ولی مصرف تجمعی قبلی حفظ می‌شود
        db.record_usage_snapshot("vpn", sid, 1 * GB, source="t")
        with db._get_conn() as conn:
            total = conn.execute("SELECT used_bytes FROM usage_snapshots WHERE service_id=?", (sid,)).fetchone()[0]
        self.assertEqual(total, 4 * GB)
        # پیام به صاحب سرویس هم رفت
        self.assertEqual(db.get_custom_config_by_id(cc)["panel_server_id"], ids[0])

    def test_plan_preview_counts_and_validation(self):
        db, ids, fakes = make_world()
        add_service(db, fakes, ids[0], 60, "ivy", 10, 1, 10)
        add_service(db, fakes, ids[0], 61, "jon", 5, 1, 10)
        add_service(db, fakes, ids[0], 61, "kim", 5, 1, -1)
        plan = run(pm.build_plan(db, ids[0], ids[1]))
        self.assertTrue(plan["ok"])
        self.assertEqual((plan["primary"], plan["users"], plan["expired"], plan["total_gb"]), (2, 2, 1, 15.0))
        self.assertFalse(plan["same_type"])
        self.assertFalse(run(pm.build_plan(db, ids[0], ids[0]))["ok"])
        fakes[ids[1]].down = True
        self.assertFalse(run(pm.build_plan(db, ids[0], ids[1]))["ok"])

    def test_rerun_only_picks_remaining_services(self):
        db, ids, fakes = make_world()
        add_service(db, fakes, ids[0], 70, "leo", 5, 1, 10)
        r1 = run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        r2 = run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        self.assertEqual(r1["migrated"], 1)
        self.assertFalse(r2["ok"])
        self.assertEqual(len(db.pm_recent_runs(5)), 1)

    def test_username_collision_on_destination_gets_suffix(self):
        db, ids, fakes = make_world()
        cc = add_service(db, fakes, ids[0], 80, "max", 5, 1, 10)
        fakes[ids[1]].users["max"] = {"volume_gb": 1}
        run(pm.run_migration(db, ids[0], ids[1], pm.Options(notify_users=False), admin_id=1))
        new_name = db.get_custom_config_by_id(cc)["username"]
        self.assertTrue(new_name.startswith("max_") and new_name != "max")
        self.assertIn(new_name, fakes[ids[1]].users)


if __name__ == "__main__":
    unittest.main()
