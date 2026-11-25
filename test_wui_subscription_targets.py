"""Regression tests for product-scoped W-UI subscription output."""
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

from sub_server import server as sub_server
from panel_providers.wui_provider import WUIProvider
from contextlib import asynccontextmanager


class WUISubscriptionTargetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sub_server._wui_cache.clear()

    async def test_product_snapshot_is_applied_and_client_resynced_before_zip(self):
        cc = {
            "id": 987654,
            "username": "product-user",
            "panel_target_config": '{"field":"group_ids","value":[22],"panel_server_id":5}',
        }
        base_server = {"id": 5, "panel_type": "wui", "group_ids": "[10,11]"}
        effective_server = {"id": 5, "panel_type": "wui", "group_ids": "[22]"}
        provider = type("FakeWUIProvider", (), {})()
        provider.resync_needs_snapshot = True
        provider.resync_user_template = AsyncMock(return_value=True)
        provider.get_config_files = AsyncMock(return_value=[{
            "kind": "wireguard", "filename": "product-user.conf", "text": "[Interface]\\nPrivateKey=x"
        }])
        provider.get_sub_info = AsyncMock(return_value={})
        provider.get_login_profiles = AsyncMock(return_value=[])

        with patch.object(sub_server, "_wui_server", new=AsyncMock(return_value=base_server)), \
             patch.object(sub_server.panel_resync, "_effective_server", return_value=effective_server) as apply_target, \
             patch.object(sub_server.panel_resync, "_snapshot_ok", return_value=True), \
             patch.object(sub_server, "get_provider", return_value=provider) as get_provider:
            result = await sub_server._wui_bundle(cc, ttl=0)

        apply_target.assert_called_once_with(base_server, cc)
        get_provider.assert_called_once_with(effective_server)
        provider.resync_user_template.assert_awaited_once_with("product-user")
        provider.get_config_files.assert_awaited_once_with("product-user")
        self.assertTrue(result["live"])
        self.assertEqual(len(result["wg"]), 1)

    async def test_create_user_repairs_panel_sample_interfaces(self):
        class FakeWUI(WUIProvider):
            def __init__(self):
                super().__init__({
                    "api_url": "https://wui.invalid", "api_password": "token",
                    "group_ids": "[22]", "start_on_first_use": 0,
                })
                self.actual_ids = [11]  # simulate W-UI applying the first sample client's interfaces
                self.calls = []

            @asynccontextmanager
            async def _session(self):
                yield object()

            async def _lookup(self, session, username):
                return None

            async def _api(self, session, method, path, action, **kwargs):
                self.calls.append((method, path, kwargs.get("json")))
                if method == "POST":
                    self.actual_ids = [11]
                    return {"id": 42}
                if method == "PATCH":
                    self.actual_ids = list(kwargs["json"]["interfaceIds"])
                    return {"id": 42}
                return {}

            async def _full(self, session, client_id):
                return {"id": client_id, "accounts": [{"interfaceId": i} for i in self.actual_ids]}

            async def _link(self, session, client_id):
                return "https://wui.invalid/sub/token"

        provider = FakeWUI()
        result = await provider.create_user("product-user", 5, 30)
        self.assertEqual(provider.actual_ids, [22])
        self.assertTrue(any(call[0] == "PATCH" and call[2] == {"interfaceIds": [22]} for call in provider.calls))
        self.assertEqual(result.subscription_url, "https://wui.invalid/sub/token")


if __name__ == "__main__":
    unittest.main()
