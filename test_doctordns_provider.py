import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    import aiohttp  # noqa: F401
except ImportError:
    sys.modules["aiohttp"] = MagicMock()

from panel_providers import PROVIDERS, PANEL_TYPE_LABELS, TOKEN_ONLY_PANEL_TYPES, get_provider
from panel_providers import doctordns_provider as mod
from panel_providers.base import PanelError, PanelUsernameTakenError
from panel_providers.doctordns_provider import DoctorDNSProvider, telegram_id_for


def refused(status, error, message):
    return status, {"ok": False, "error": error, "message": message}


class FakeDNS:
    def __init__(self):
        self.admin = True
        self.wg_admin_only = True
        self.users = {}
        self.calls = []
        self.next_id = 1

    def view(self, u):
        return {"id": u["id"], "telegram_id": u["tg"], "status": u["status"], "plan": u.get("plan"),
                "used_bytes": u.get("used", 0), "quota_bytes": u.get("quota", 0),
                "panel_url": "https://u.example.com:8443/", "ips": ["5.120.1.2"], "max_ips": 1,
                "expires_at": "2026-12-01T10:00:00+00:00",
                "servers": [{"ip": "203.0.113.4", "n": 1, "note": "تهران", "single": False,
                             "dot": "d1.example.com", "doh": "https://d1.example.com/dns-query/tok"}]}

    def handle(self, method, path, body, auth):
        self.calls.append((method, path, body))
        if auth != "Bearer dd_good":
            return refused(401, "unauthorized", "کلید API معتبر نیست")
        if path.startswith("/admin") and not self.admin:
            return refused(403, "admin_only", "این کلید دسترسی ادمین ندارد")
        if path == "/" or path == "/admin/stats":
            return 200, {"ok": True}
        if path == "/plans":
            return 200, {"ok": True, "plans": [{"id": 1, "name": "گیمینگ", "days": 30}, {"id": 2, "name": "کامل", "days": 30}]}
        if path == "/users" and method == "POST":
            tg = body["telegram_id"]
            created = tg not in self.users
            if created:
                self.users[tg] = {"id": self.next_id, "tg": tg, "status": "pending"}
                self.next_id += 1
            return (201 if created else 200), {"ok": True, "created": created, "user": self.view(self.users[tg])}
        parts = path.strip("/").split("/")
        if parts[0] == "users":
            u = self.users.get(int(parts[1]))
            if not u:
                return refused(404, "user_not_found", "کاربر پیدا نشد")
            if len(parts) == 2:
                return 200, {"ok": True, "user": self.view(u)}
            if parts[2] == "login-link":
                return 200, {"ok": True, "url": f"https://u.example.com:8443/l/{u['tg']}", "minutes": 10}
            if parts[2] == "wg" and method == "POST":
                if self.wg_admin_only:
                    return refused(403, "wg_admin_only", "کانفیگ را پشتیبانی می‌سازد")
                return 201, {"ok": True}
            if parts[2:] == ["wg", "all"]:
                return 200, {"ok": True, "configs": [{"id": 1, "config": "[Interface]\nPrivateKey = x", "file": "doctor-dns-1.conf",
                                                      "server": "سرور 1", "note": "تهران", "qr": ""}]}
            if parts[2] == "doh-reset":
                return 200, {"ok": True, "user": self.view(u)}
        if parts[0] == "admin" and parts[1] == "users":
            u = next(x for x in self.users.values() if x["id"] == int(parts[2]))
            if parts[3] == "plan":
                u.update(status="active", plan={"id": body["plan_id"], "name": "p"}, quota=100)
            if parts[3] == "status":
                u["status"] = body["status"]
            return 200, {"ok": True, "user": self.view(u)}
        return refused(404, "not_found", "نیست")


class FakeSession:
    def __init__(self, headers):
        self.auth = (headers or {}).get("Authorization")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def install(fake):
    mod.new_session = lambda headers=None, **kw: FakeSession(headers)

    async def fake_request_json(session, method, url, **kwargs):
        path = url.split("/api/v1", 1)[1] or "/"
        status, data = fake.handle(method, path, kwargs.get("json"), session.auth)
        return status, data, str(data)

    mod.request_json = fake_request_json


def row(key="dd_good", plan='"1"', url="https://dns.example.com:8445"):
    return {"panel_type": "doctordns", "api_url": url, "api_password": key, "group_ids": plan}


class RegistrationTest(unittest.TestCase):
    def test_registered(self):
        self.assertIs(PROVIDERS["doctordns"], DoctorDNSProvider)
        self.assertEqual(PANEL_TYPE_LABELS["doctordns"], "Doctor DNS")
        self.assertIn("doctordns", TOKEN_ONLY_PANEL_TYPES)

    def test_synthetic_id(self):
        a = telegram_id_for("svpn_1")
        self.assertEqual(a, telegram_id_for("svpn_1"))
        self.assertNotEqual(a, telegram_id_for("svpn_2"))
        self.assertTrue(10 ** 15 <= a < 10 ** 20)

    def test_base_url_normalisation(self):
        for url in ("https://d:8445", "https://d:8445/", "https://d:8445/api/v1", "https://d:8445/api/v1/"):
            self.assertEqual(get_provider(row(url=url))._base(), "https://d:8445/api/v1")


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDNS()
        install(self.fake)

    def run_(self, coro):
        return asyncio.run(coro)

    def test_connection(self):
        self.assertTrue(self.run_(get_provider(row()).test_connection()))
        ok, err = self.run_(get_provider(row(key="dd_bad")).check_connection())
        self.assertFalse(ok)
        self.assertIn("معتبر نیست", err)
        self.fake.admin = False
        ok, err = self.run_(get_provider(row()).check_connection())
        self.assertFalse(ok)
        self.assertIn("دسترسی ادمین", err)

    def test_targets(self):
        info = self.run_(get_provider(row()).list_product_targets())
        self.assertEqual((info["field"], info["kind"]), ("group_ids", "scalar"))
        self.assertEqual([c["value"] for c in info["choices"]], ["1", "2"])

    def test_lifecycle(self):
        p = get_provider(row())
        r = self.run_(p.create_user("svpn_1", 10, 30))
        self.assertEqual(r.subscription_url, "https://u.example.com:8443/?u=svpn_1")
        usage = self.run_(p.get_user_usage("svpn_1"))
        self.assertEqual((usage["status"], usage["data_limit_bytes"]), ("active", 100))
        with self.assertRaises(PanelUsernameTakenError):
            self.run_(p.create_user("svpn_1", 10, 30))
        self.run_(p.update_user("svpn_1", add_days=30))
        plans = [c[2]["plan_id"] for c in self.fake.calls if c[1].endswith("/plan")]
        self.assertEqual(plans, [1, 1])
        self.assertTrue(self.run_(p.delete_user("svpn_1")))
        self.assertEqual(self.run_(p.get_user_usage("svpn_1"))["status"], "disabled")
        self.run_(p.update_user("svpn_1", add_days=30))
        self.assertEqual(self.run_(p.get_user_usage("svpn_1"))["status"], "active")
        self.assertEqual(self.run_(p.revoke_credentials("svpn_1")).subscription_url, "https://u.example.com:8443/?u=svpn_1")

    def test_unique_link_per_user(self):
        p = get_provider(row())
        a = self.run_(p.create_user("svpn_a", 1, 1)).subscription_url
        b = self.run_(p.create_user("svpn_b", 1, 1)).subscription_url
        self.assertNotEqual(a, b)

    def test_login_link(self):
        p = get_provider(row())
        self.run_(p.create_user("svpn_6", 1, 1))
        self.assertTrue(self.run_(p.login_link("svpn_6")).startswith("https://u.example.com:8443/l/"))

    def test_wg_created_when_allowed(self):
        self.fake.wg_admin_only = False
        self.run_(get_provider(row()).create_user("svpn_7", 1, 1))
        self.assertTrue(any(c[0] == "POST" and c[1].endswith("/wg") for c in self.fake.calls))

    def test_dns_bundle(self):
        p = get_provider(row())
        self.run_(p.create_user("svpn_8", 1, 1))
        b = self.run_(p.get_dns_bundle("svpn_8"))
        self.assertEqual(b["servers"][0]["doh"], "https://d1.example.com/dns-query/tok")
        self.assertEqual((b["ips"], b["max_ips"]), (["5.120.1.2"], 1))
        self.assertEqual(b["wg"][0]["filename"], "doctor-dns-1.conf")
        self.assertIn("سرور 1", b["wg"][0]["remark"])
        self.assertEqual((b["info"]["total"], b["info"]["expire"] > 0), (100, True))

    def test_volume_only_update_rejected(self):
        p = get_provider(row())
        self.run_(p.create_user("svpn_2", 10, 30))
        with self.assertRaises(PanelError):
            self.run_(p.update_user("svpn_2", add_volume_gb=5))

    def test_retry_after_failed_plan_apply(self):
        p = get_provider(row())
        self.run_(p.create_user("svpn_3", 10, 30))
        self.fake.users[telegram_id_for("svpn_3")].update(status="pending", plan=None)
        self.assertTrue(self.run_(p.create_user("svpn_3", 10, 30)).subscription_url)

    def test_missing_plan(self):
        with self.assertRaises(PanelError):
            self.run_(get_provider(row(plan=None)).create_user("svpn_4", 1, 1))

    def test_renew_falls_back_to_current_plan(self):
        p = get_provider(row())
        self.run_(p.create_user("svpn_5", 1, 1))
        self.fake.users[telegram_id_for("svpn_5")]["plan"] = {"id": 2, "name": "x"}
        self.run_(get_provider(row(plan=None)).update_user("svpn_5", add_days=30))
        self.assertEqual([c[2]["plan_id"] for c in self.fake.calls if c[1].endswith("/plan")][-1], 2)


class PageDataTest(unittest.TestCase):
    def test_dns_section(self):
        import dedicated_sub as ds
        bundle = {"servers": [{"ip": "203.0.113.4", "n": 1, "note": "تهران", "dot": "d.example.com", "doh": "https://d.example.com/dns-query/t"}],
                  "ips": ["5.120.1.2"], "max_ips": 1}
        cc = {"username": "svpn_1", "status": "active", "expires_at": None, "duration_days": 30, "created_at": None}
        data = ds.build_page_data(cc, {"upload": 0, "download": 5, "total": 100, "expire": 0}, [], dict(ds.DSUB_DEFAULTS),
                                  "brand", "https://s/s/tok", None, dns=bundle)
        self.assertTrue(data["show"]["dns"])
        self.assertEqual(data["dns"]["servers"][0]["ip"], "203.0.113.4")
        self.assertEqual(data["dns"]["maxIps"], 1)
        plain = ds.build_page_data(cc, {}, [], dict(ds.DSUB_DEFAULTS), "brand", "https://s/s/tok", None)
        self.assertFalse(plain["show"]["dns"])
        self.assertIsNone(plain["dns"])


if __name__ == "__main__":
    unittest.main()
