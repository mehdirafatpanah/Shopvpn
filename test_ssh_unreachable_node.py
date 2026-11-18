"""حذف حساب/نود SSH وقتی Agent نود در دسترس نیست (مثلاً سرور حذف شده)."""
import asyncio
import json
import os
import unittest

import sys
import types

try:
    import aiohttp  # noqa: F401
    HAVE_AIOHTTP = True
except ImportError:  # محیط بدون وابستگی‌ها: فقط منطق service تست می‌شود
    HAVE_AIOHTTP = False
    _stub = types.ModuleType("aiohttp")
    _stub.ClientError = Exception
    _stub.__getattr__ = lambda name: type(name, (), {})  # هر attribute دیگر یک کلاس خالی
    sys.modules["aiohttp"] = _stub
    _qr = types.ModuleType("quota_reconciler")  # panel_providers به aiohttp واقعی نیاز دارد
    _qr._env_secret_resolver = lambda ref: "x"
    sys.modules["quota_reconciler"] = _qr

import ssh_service
from ssh_providers import LinuxAgentSSHProvider, SSHAgentUnreachable


class FakeDB:
    def __init__(self):
        self.node = {"id": 1, "name": "n1", "node_type": "linux", "host": "127.0.0.1", "port": 22,
                     "secret_ref": "env:TEST_AGENT_TOKEN", "status": "active",
                     "config_json": json.dumps({"agent_url": "http://127.0.0.1:1", "allow_insecure_http": True, "timeout": 3})}
        self.acc = {"id": 7, "node_id": 1, "account_id": "acc-1", "quota_pool_id": 5, "status": "active"}
        self.detached, self.deleted_nodes = [], []

    def list_ssh_accounts(self, user_id=None, node_id=None):
        return [dict(self.acc)]

    def list_ssh_nodes(self, active_only=False):
        return [dict(self.node)] if self.node else []

    def get_ssh_node(self, node_id):
        return dict(self.node) if self.node and int(node_id) == 1 else None

    def set_ssh_account_status(self, row_id, status):
        self.acc["status"] = status

    def detach_quota_service(self, pool_id, kind, sid):
        self.detached.append((pool_id, kind, sid))

    def delete_ssh_node(self, node_id):
        if self.acc["status"] != "deleted":
            raise ValueError("روی این نود هنوز حساب SSH فعال وجود دارد.")
        self.deleted_nodes.append(node_id)
        return True


class DeadProvider:
    """Agent مرده: هر تماس شبکه‌ای مثل سرور حذف‌شده شکست می‌خورد."""
    def __init__(self, *a, **k):
        pass

    async def _dead(self, *a, **k):
        raise SSHAgentUnreachable("ارتباط با Linux Agent برقرار نشد: ClientConnectorError")

    get_usage = set_account_enabled = delete_account = update_account = get_info = _dead


class UnreachableNodeTests(unittest.TestCase):
    def setUp(self):
        os.environ["TEST_AGENT_TOKEN"] = "x"
        import ssh_providers
        self._orig = ssh_providers.get_ssh_provider
        ssh_providers.get_ssh_provider = lambda node, secret_resolver=None: DeadProvider()

    def tearDown(self):
        import ssh_providers
        ssh_providers.get_ssh_provider = self._orig

    @unittest.skipUnless(HAVE_AIOHTTP, "aiohttp نصب نیست")
    def test_provider_raises_unreachable_not_generic(self):
        db = FakeDB()
        provider = LinuxAgentSSHProvider(db.node, secret_resolver=lambda ref: "x")
        with self.assertRaises(SSHAgentUnreachable):
            asyncio.run(provider.get_info())

    def test_delete_requires_force_when_unreachable(self):
        db = FakeDB()
        with self.assertRaises(ssh_service.SSHServiceError) as ctx:
            asyncio.run(ssh_service.account_action(db, "acc-1", "delete"))
        self.assertEqual(ctx.exception.status, ssh_service.AGENT_UNREACHABLE_STATUS)
        self.assertEqual(db.acc["status"], "active")

    def test_force_delete_works_offline(self):
        db = FakeDB()
        self.assertEqual(asyncio.run(ssh_service.account_action(db, "acc-1", "delete", force=True)), "deleted")
        self.assertEqual(db.acc["status"], "deleted")
        self.assertEqual(db.detached, [(5, "ssh", "acc-1")])

    def test_disable_unreachable_is_clear_error_not_local_change(self):
        db = FakeDB()
        with self.assertRaises(ssh_service.SSHServiceError) as ctx:
            asyncio.run(ssh_service.account_action(db, "acc-1", "disable"))
        self.assertEqual(ctx.exception.status, ssh_service.AGENT_UNREACHABLE_STATUS)
        self.assertEqual(db.acc["status"], "active")

    def test_force_delete_node_cleans_accounts(self):
        db = FakeDB()
        with self.assertRaises(ssh_service.SSHServiceError):
            asyncio.run(ssh_service.delete_node(db, 1))
        asyncio.run(ssh_service.delete_node(db, 1, force=True))
        self.assertEqual(db.deleted_nodes, [1])
        self.assertEqual(db.acc["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
