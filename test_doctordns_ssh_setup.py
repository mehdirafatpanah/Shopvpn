import os
import sqlite3
import tempfile
import unittest

import doctor_dns_ssh_setup as setup


class DoctorDNSSSHSetupTests(unittest.TestCase):
    def test_host_validation(self):
        self.assertEqual(setup._validate_host("203.0.113.10"), "203.0.113.10")
        self.assertEqual(setup._validate_host("dns.example.com"), "dns.example.com")
        self.assertEqual(setup._validate_host("2001:db8::1"), "2001:db8::1")
        for value in ("", "host/path", "https://host", "bad host"):
            with self.subTest(value=value), self.assertRaises(setup.DoctorDNSSetupError):
                setup._validate_host(value)

    def test_remote_bootstrap_creates_scoped_ip_limited_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "panel.db")
            con = sqlite3.connect(db_path)
            con.execute("CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, allow_ips TEXT, created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT, scope TEXT NOT NULL DEFAULT 'customer', admin_id INTEGER)")
            con.commit(); con.close()
            script = setup._remote_script("dd_secret", "a" * 64, "203.0.113.9", "ShopVPN-Test")
            script = script.replace("/var/lib/smart-dns/panel.db", db_path)
            exec(compile(script, "remote-bootstrap-test.py", "exec"), {})
            con = sqlite3.connect(db_path)
            row = con.execute("SELECT name, token_hash, allow_ips, scope, admin_id FROM api_tokens").fetchone()
            con.close()
            self.assertEqual(row, ("ShopVPN-Test", "a" * 64, "203.0.113.9", "admin", None))

    def test_remote_bootstrap_revokes_only_same_integration_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "panel.db")
            con = sqlite3.connect(db_path)
            con.execute("CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, allow_ips TEXT, created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT, scope TEXT NOT NULL DEFAULT 'customer', admin_id INTEGER)")
            con.execute("INSERT INTO api_tokens (name, token_hash, created_at, scope) VALUES ('ShopVPN-Test', 'old', '2025-01-01', 'admin')")
            con.execute("INSERT INTO api_tokens (name, token_hash, created_at, scope) VALUES ('Other-Key', 'other', '2025-01-01', 'admin')")
            con.commit(); con.close()
            script = setup._remote_script("dd_secret", "new", "203.0.113.9", "ShopVPN-Test")
            script = script.replace("/var/lib/smart-dns/panel.db", db_path)
            exec(compile(script, "remote-bootstrap-test.py", "exec"), {})
            con = sqlite3.connect(db_path)
            rows = con.execute("SELECT name, token_hash, revoked_at FROM api_tokens ORDER BY id").fetchall()
            con.close()
            self.assertEqual(rows[0][0:2], ("ShopVPN-Test", "old"))
            self.assertTrue(rows[0][2])
            self.assertEqual(rows[1], ("Other-Key", "other", None))
            self.assertEqual(rows[2][0:2], ("ShopVPN-Test", "new"))


if __name__ == "__main__":
    unittest.main()
