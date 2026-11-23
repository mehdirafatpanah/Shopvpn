# -*- coding: utf-8 -*-
import asyncio
import subprocess
import sys
import types
import unittest

import port_forward as pf


class FakeDb:
    def __init__(self):
        self.s = {"web_shop_base_url": "https://shop.example.com", "admin_panel_public_url": "https://admin.example.com"}

    def get_setting(self, key, default=""):
        return self.s.get(key, default)

    def set_setting(self, key, value):
        self.s[key] = value


def install_fake_dsub():
    mod = types.ModuleType("dedicated_sub")
    mod.base_url = lambda db, profile=None: "https://sub.example.com"
    mod.list_profiles = lambda db: [{"id": 7, "name": "ایران", "base_url": "https://sub2.example.com"}]
    sys.modules["dedicated_sub"] = mod


def data(**kw):
    base = {"target": "shop", "method": "socat", "proto": "tcp", "listen_port": 8443,
            "dest_host": "203.0.113.9", "dest_port": 443, "run_on": "local"}
    base.update(kw)
    return base


class PortForwardTest(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get("dedicated_sub")
        install_fake_dsub()
        self.db = FakeDb()

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop("dedicated_sub", None)
        else:
            sys.modules["dedicated_sub"] = self._saved

    def test_targets_cover_sub_profile_shop_panel(self):
        keys = [t["key"] for t in pf.targets(self.db)]
        self.assertEqual(keys, ["sub_central", "sub:7", "shop", "panel"])

    def test_rejects_bad_input(self):
        for bad in (data(target="x"), data(listen_port=0), data(dest_port=70000), data(dest_host="a b"),
                    data(dest_host="::1"), data(method="nc"), data(proto="icmp"), data(bind="999.1.1.1"),
                    data(run_on="ssh", ssh_host="1.2.3.4", ssh_port=2222, listen_port=2222),
                    data(dest_host="127.0.0.1", dest_port=8443)):
            with self.assertRaises(pf.PortForwardError, msg=str(bad)):
                pf.create_rule(self.db, bad)

    def test_duplicate_listen_port_same_server_rejected_but_other_server_allowed(self):
        pf.create_rule(self.db, data())
        with self.assertRaises(pf.PortForwardError):
            pf.create_rule(self.db, data(target="panel"))
        pf.create_rule(self.db, data(target="panel", proto="udp"))
        pf.create_rule(self.db, data(target="panel", run_on="ssh", ssh_host="198.51.100.4"))
        self.assertEqual(len(pf.list_rules(self.db)), 3)

    def test_secret_encrypted_and_never_public(self):
        import os, tempfile
        os.environ["SHOPVPN_SSH_CREDENTIAL_KEY"] = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
        rule = pf.create_rule(self.db, data(run_on="ssh", ssh_host="198.51.100.4", ssh_password="hunter2", ssh_save_secret=True))
        self.assertNotIn("hunter2", str(self.db.s))
        self.assertNotIn("ssh_pass_enc", rule)
        self.assertTrue(rule["ssh_saved"])
        again = pf.update_rule(self.db, rule["id"], {"dest_port": 8443})
        self.assertTrue(again["ssh_saved"])
        off = pf.update_rule(self.db, rule["id"], {"ssh_save_secret": False})
        self.assertFalse(off["ssh_saved"])

    def test_scripts_are_valid_bash_for_all_variants(self):
        for method in pf.METHODS:
            for proto in pf.PROTOS:
                rule = pf.normalize(self.db, data(method=method, proto=proto, bind="10.0.0.5"))
                for fn in (pf.build_apply, pf.build_remove, pf.build_status):
                    res = subprocess.run(["bash", "-n"], input=fn(rule), text=True, capture_output=True)
                    self.assertEqual(res.returncode, 0, res.stderr)
        socat = pf.build_apply(pf.normalize(self.db, data(proto="udp")))
        self.assertIn("UDP-LISTEN:$LP,bind=$BIND,fork,reuseaddr UDP:$DH:$DP", socat)

    def test_apply_marks_active_and_blocks_critical_edit_until_removed(self):
        rule = pf.create_rule(self.db, data())
        calls = []

        async def fake(rule_, script, password=None, key=None, db_secret_enc=None, timeout=240):
            calls.append(script)
            return 0, "OK\n"

        orig = pf.run_script
        pf.run_script = fake
        try:
            res = asyncio.run(pf.act(self.db, rule["id"], "apply"))
            self.assertEqual(res["rule"]["status"], "active")
            with self.assertRaises(pf.PortForwardError):
                pf.update_rule(self.db, rule["id"], {"listen_port": 9000})
            self.assertEqual(pf.update_rule(self.db, rule["id"], {"dest_port": 8080})["status"], "pending")
            asyncio.run(pf.act(self.db, rule["id"], "remove"))
            self.assertEqual(pf.update_rule(self.db, rule["id"], {"listen_port": 9000})["listen_port"], 9000)
            res = asyncio.run(pf.act(self.db, rule["id"], "delete"))
            self.assertTrue(res["deleted"])
            self.assertEqual(pf.list_rules(self.db), [])
        finally:
            pf.run_script = orig

    def test_failed_apply_records_error_and_busy_port_message(self):
        rule = pf.create_rule(self.db, data())

        async def fake(*a, **k):
            return 3, "PORT_BUSY:8443\n"

        orig = pf.run_script
        pf.run_script = fake
        try:
            with self.assertRaises(pf.PortForwardError) as ctx:
                asyncio.run(pf.act(self.db, rule["id"], "apply"))
            self.assertIn("از قبل", str(ctx.exception))
            stored = pf.list_rules(self.db)[0]
            self.assertEqual(stored["status"], "error")
            self.assertFalse(stored["enabled"])
            asyncio.run(pf.act(self.db, rule["id"], "delete"))
            self.assertEqual(pf.list_rules(self.db), [])
        finally:
            pf.run_script = orig

    def test_force_delete_when_remote_unreachable(self):
        rule = pf.create_rule(self.db, data(run_on="ssh", ssh_host="198.51.100.4"))
        self.db.s[pf.SETTING_KEY] = self.db.s[pf.SETTING_KEY].replace('"enabled": false', '"enabled": true')

        async def fake(*a, **k):
            raise pf.PortForwardError("اتصال SSH برقرار نشد")

        orig = pf.run_script
        pf.run_script = fake
        try:
            with self.assertRaises(pf.PortForwardError):
                asyncio.run(pf.act(self.db, rule["id"], "delete"))
            self.assertEqual(len(pf.list_rules(self.db)), 1)
            res = asyncio.run(pf.act(self.db, rule["id"], "delete", force=True))
            self.assertTrue(res["deleted"])
            self.assertEqual(pf.list_rules(self.db), [])
        finally:
            pf.run_script = orig


if __name__ == "__main__":
    unittest.main()
