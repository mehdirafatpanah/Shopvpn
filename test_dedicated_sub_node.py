# -*- coding: utf-8 -*-
"""Dedicated subscriptions for SSH/OpenVPN/WireGuard-only node products."""
import base64
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")
import config
from database import Database
from ssh_credentials import encrypt_credential

try:
    from starlette.testclient import TestClient
    from sub_server import server
    HAVE_CLIENT = True
except Exception:
    HAVE_CLIENT = False


@unittest.skipUnless(HAVE_CLIENT, "starlette TestClient/httpx not installed")
class NodeOnlyDedicatedSubTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(prefix="node_dsub_", suffix=".db")
        self.db = Database(self.path)
        os.environ["SHOPVPN_SSH_CREDENTIAL_KEY"] = Fernet.generate_key().decode("ascii")
        self.db.init_db(owner_id=1)
        self.db.add_or_update_user(100, "buyer", "Buyer")
        self.node = self.db.create_ssh_node("Node-A", "linux", "node.example.test", 22,
                                            config_json={"protocols": ["ssh", "openvpn", "wireguard"]})
        self.pool = self.db.create_quota_pool(100, 8, None, "Node-only product")
        self.sub_id = self.db.create_node_subscription(100, order_id=10, product_id=20,
            quota_pool_id=self.pool, display_name="Node bundle", volume_gb=8, duration_days=30)
        self._add_account("ssh", "ssh-account", "ssh-user", "ssh-password")
        self._add_account("openvpn", "ovpn-account", "ovpn-user", "client\n<ca>CA</ca>\n<key>KEY</key>")
        self._add_account("wireguard", "wg-account", "wg-user", "[Interface]\nPrivateKey = PRIVATE\n[Peer]\nPublicKey = PUBLIC\nEndpoint = old.example:51820")
        self.db.set_setting("dsub_enabled", "1")
        self.db.set_setting("dsub_base_url", "https://sub.example.test")
        self.token = self.db.ds_node_sub_get_or_create_token(self.sub_id)
        server.db = self.db
        server.limiter = server.RateLimiter()
        server.cache = server.UpstreamCache()
        self.client = TestClient(server.app, base_url="http://sub.example.test")

    def _add_account(self, protocol, account_id, username, secret):
        self.db.register_ssh_account(self.node, 100, account_id, username, "node.example.test", 22,
                                     self.pool, None, encrypt_credential(secret), protocol=protocol)
        self.assertTrue(self.db.link_ssh_account_to_node_subscription(account_id, self.sub_id))

    def test_node_bundle_gets_dedicated_link_and_merged_ssh_uri(self):
        link = __import__("dedicated_sub").link_for_node_subscription(self.db, self.sub_id)
        self.assertEqual(link, f"https://sub.example.test/s/{self.token}")
        response = self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1.8.29"})
        self.assertEqual(response.status_code, 200)
        body = base64.b64decode(response.content).decode("utf-8")
        self.assertIn("ssh://", body)
        self.assertIn(base64.b64encode(b"ssh-user:ssh-password").decode(), body)

    def test_openvpn_and_wireguard_profiles_download_from_same_link(self):
        ovpn = self.client.get(f"/s/{self.token}/ovpn/1")
        wg = self.client.get(f"/s/{self.token}/wg/1")
        self.assertEqual(ovpn.status_code, 200)
        self.assertIn(b"<ca>", ovpn.content)
        self.assertEqual(wg.status_code, 200)
        self.assertIn(b"PrivateKey", wg.content)

    def test_browser_page_and_qr_work_without_panel_upstream(self):
        page = self.client.get(f"/s/{self.token}?view=1", headers={"user-agent": "Mozilla/5.0"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("Node bundle", page.text)
        qr = self.client.get(f"/s/{self.token}/qr.png?i=0")
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.headers.get("content-type"), "image/png")

    def test_node_subscription_volume_and_time_renewal_uses_shared_pool(self):
        import asyncio
        import sys, types
        sys.modules.setdefault("renewal_log", types.SimpleNamespace())
        import renewal_engine
        class FakeReconciler:
            def __init__(self, db): self.db = db
            async def push_pool_expiry(self, pool_id): return True
            async def reconcile_pool(self, pool): return []
        order = {"renewal_target_kind": "node", "renewal_target_id": self.sub_id, "renewal_mode": "volume",
                 "renewal_add_volume_gb": 2, "renewal_add_days": 0, "user_id": 100}
        with patch("quota_reconciler.QuotaReconciler", FakeReconciler):
            result = asyncio.run(renewal_engine.execute_renewal(self.db, order))
        self.assertIn("موفقیت", result)
        pool = self.db.get_quota_pool(self.pool)
        self.assertEqual(pool["limit_bytes"], 10 * (1024 ** 3))
        self.assertEqual(self.db.get_node_subscription(self.sub_id)["volume_gb"], 10)
        time_order = {"renewal_target_kind": "node", "renewal_target_id": self.sub_id, "renewal_mode": "time",
                      "renewal_add_volume_gb": 0, "renewal_add_days": 7, "user_id": 100}
        with patch("quota_reconciler.QuotaReconciler", FakeReconciler):
            result = asyncio.run(renewal_engine.execute_renewal(self.db, time_order))
        self.assertIn("موفقیت", result)
        self.assertTrue(self.db.get_node_subscription(self.sub_id)["expires_at"])

    def test_node_link_does_not_confuse_overlapping_custom_config_ids(self):
        panel = self.db.add_panel_server("Panel-A", "marzban", "https://panel.example.test", "u", "p")
        cid = self.db.add_custom_config(100, panel, "panel-user", 5, 30, "https://panel.example.test/sub/panel-token")
        self.assertEqual(cid, self.sub_id)  # both tables start their own integer sequence
        node_link = __import__("dedicated_sub").link_for_node_subscription(self.db, self.sub_id)
        custom_link = __import__("dedicated_sub").link_for_config(self.db, cid)
        self.assertIn(self.token, node_link)
        self.assertNotIn(self.token, custom_link)

    def test_token_lookup_resolves_node_subscription(self):
        row = self.db.ds_get_config_by_token(self.token)
        self.assertTrue(row["is_node_subscription"])
        self.assertEqual(row["node_subscription_id"], self.sub_id)


class DirectNodeProductProvisionTests(unittest.TestCase):
    def test_single_node_products_get_subscription_links_for_all_linux_protocols(self):
        import asyncio
        import direct_panel_provision
        from ssh_providers import SSHAccountResult

        class FakeProvider:
            async def create_account(self, username, limit_bytes, expires_at=None, protocol="ssh"):
                metadata = {"password": "node-secret"} if protocol == "ssh" else {
                    "profile": "client\n<ca>CA</ca>\n<key>KEY</key>" if protocol == "openvpn" else
                               "[Interface]\nPrivateKey = PRIVATE\n[Peer]\nPublicKey = PUBLIC\nEndpoint = node.example.test:51820"
                }
                return SSHAccountResult("account-" + protocol, username, "node.example.test", 22, metadata=metadata)
            async def get_usage(self, account_id):
                return {"used_bytes": 0, "uploaded_bytes": 0, "downloaded_bytes": 0,
                        "source": "nftables_port_counters", "accounting_ready": True}
            async def delete_account(self, account_id): return True

        for protocol in ("ssh", "openvpn", "wireguard"):
            with self.subTest(protocol=protocol):
                self.path = tempfile.mktemp(prefix="node_product_", suffix=".db")
                db = Database(self.path); db.init_db(owner_id=1); db.add_or_update_user(100, "buyer", "Buyer")
                node_id = db.create_ssh_node("Node-A", "linux", "node.example.test", 22,
                    config_json={"protocols": ["ssh", "openvpn", "wireguard"]})
                db.update_ssh_node_status(node_id, "active", None)
                db.set_setting("dsub_enabled", "1"); db.set_setting("dsub_base_url", "https://sub.example.test")
                product = {"id": 50, "name": "Node product", "provision_ssh_node_id": node_id,
                           "provision_server_id": None, "provision_ssh_protocol": protocol,
                           "auto_provision_volume_gb": 5, "duration_days": 30, "start_on_first_use": 0}
                os.environ["SHOPVPN_SSH_CREDENTIAL_KEY"] = Fernet.generate_key().decode("ascii")
                with patch("ssh_providers.get_ssh_provider", return_value=FakeProvider()):
                    result = asyncio.run(direct_panel_provision.provision_ssh_direct(
                        db, product, quantity=1, user_id=100, protocol=protocol))
                self.assertEqual(len(result), 1)
                self.assertIn("/s/", result[0]["subscription_url"])
                self.assertTrue(result[0].get("node_subscription_id"))
                account = db.list_ssh_accounts(100)[0]
                self.assertEqual(account["protocol"], protocol)
                self.assertEqual(account["node_subscription_id"], result[0]["node_subscription_id"])

    def test_multi_node_product_uses_one_shared_subscription_link(self):
        import asyncio
        import direct_panel_provision
        from ssh_providers import SSHAccountResult

        class FakeProvider:
            def __init__(self): self.counter = 0
            async def create_account(self, username, limit_bytes, expires_at=None, protocol="ssh"):
                self.counter += 1
                return SSHAccountResult(f"multi-{self.counter}", username, "node.example.test", 22,
                                        metadata={"password": "multi-secret"})
            async def get_usage(self, account_id):
                return {"used_bytes": 0, "uploaded_bytes": 0, "downloaded_bytes": 0,
                        "source": "nftables_port_counters", "accounting_ready": True}
            async def delete_account(self, account_id): return True

        db = Database(tempfile.mktemp(prefix="multi_node_product_", suffix=".db"))
        db.init_db(owner_id=1); db.add_or_update_user(100, "buyer", "Buyer")
        n1 = db.create_ssh_node("Node-1", "linux", "n1.example.test", 22, config_json={"protocols": ["ssh"]})
        n2 = db.create_ssh_node("Node-2", "linux", "n2.example.test", 22, config_json={"protocols": ["ssh"]})
        db.update_ssh_node_status(n1, "active", None); db.update_ssh_node_status(n2, "active", None)
        db.set_setting("dsub_enabled", "1"); db.set_setting("dsub_base_url", "https://sub.example.test")
        os.environ["SHOPVPN_SSH_CREDENTIAL_KEY"] = Fernet.generate_key().decode("ascii")
        product = {"id": 60, "name": "Multi-node", "provision_ssh_node_id": n1,
                   "provision_ssh_protocol": "ssh", "auto_provision_volume_gb": 5, "duration_days": 30}
        with patch("ssh_providers.get_ssh_provider", return_value=FakeProvider()):
            items, rollback = asyncio.run(direct_panel_provision._provision_multi_unit(
                db, product, [], [n1, n2], 100, 77, 5, None, first_use=False, duration_days=30))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["subscription_url"], items[1]["subscription_url"])
        self.assertIn("/s/", items[0]["subscription_url"])
        self.assertEqual(items[0]["node_subscription_id"], items[1]["node_subscription_id"])


if __name__ == "__main__":
    unittest.main()
