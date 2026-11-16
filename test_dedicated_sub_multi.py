# -*- coding: utf-8 -*-
"""تست ساب اختصاصی برای سرویس‌های چندپنلی: همه‌ی پنل‌ها باید در خروجی باشند (حتی با کلاینت Clash/JSON)."""
import base64
import unittest

from test_dedicated_sub import CHROME, VLESS, add_service, b64, make_db

try:
    from starlette.testclient import TestClient
    HAVE_CLIENT = True
except Exception:  # pragma: no cover
    HAVE_CLIENT = False

YAML = b"proxies:\n  - name: a\n    type: vless\n    server: x.example.com\n"
V2 = "vless://11111111-1111-1111-1111-111111111111@p2.example.com:443?type=ws#p2"
V3 = "vless://22222222-2222-2222-2222-222222222222@p3.example.com:443?type=ws#p3"


@unittest.skipUnless(HAVE_CLIENT, "starlette TestClient/httpx not installed")
class MultiPanelSubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sub_server import server
        cls.server = server

    def setUp(self):
        s = self.server
        self.db = make_db()
        s.db = self.db
        s.limiter = s.RateLimiter()
        s.cache = s.UpstreamCache()
        self.up = {}

        async def fake(url, ua):
            if url not in self.up:
                raise ConnectionError("down")
            entry = self.up[url]
            return entry["yaml"] if "clash" in ua.lower() and "yaml" in entry else entry["uris"]

        s._http_get = fake
        self.u1, self.u2, self.u3 = (f"https://p{i}.example.com/sub/K{i}" for i in (1, 2, 3))
        self.cid = add_service(self.db, url=self.u1)
        self.token = self.db.ds_get_or_create_token(self.cid)
        self.up[self.u1] = {"uris": (200, {}, b64(VLESS)), "yaml": (200, {}, YAML)}
        self.up[self.u2] = {"uris": (200, {}, b64(V2)), "yaml": (200, {}, YAML)}
        self.up[self.u3] = {"uris": (200, {}, b64(V3)), "yaml": (200, {}, YAML)}
        self.db.add_config_panel_link(self.cid, 2, "u2", self.u2)
        self.db.add_config_panel_link(self.cid, 3, "u3", self.u3)
        self.db.set_setting("dsub_enabled", "1")
        self.db.set_setting("dsub_base_url", "https://sub.example.com")
        self.client = TestClient(s.app, base_url="http://sub.example.com")

    def _uris(self, r):
        return base64.b64decode(r.content).decode().splitlines()

    def test_v2ray_client_gets_all_panels(self):
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1.8.29"})
        self.assertEqual(self._uris(r), [VLESS, V2, V3])

    def test_clash_client_gets_all_panels(self):
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "clash.meta"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._uris(r), [VLESS, V2, V3])

    def test_clash_client_with_dsub_off_gets_all_panels(self):
        self.db.set_setting("dsub_enabled", "0")
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "clash.meta"})
        self.assertEqual(self._uris(r), [VLESS, V2, V3])

    def test_web_page_lists_all_panels(self):
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertIn("p2.example.com", r.text)
        self.assertIn("p3.example.com", r.text)

    def test_doctordns_primary_page_lists_other_panels(self):
        s = self.server
        orig = s._dns_bundle

        async def fake_dns(cc, ttl=30):
            return {"servers": [{"ip": "1.2.3.4", "n": 1}], "ips": [], "max_ips": 0, "wg": [], "info": {}, "live": True}

        s._dns_bundle = fake_dns
        try:
            r = self.client.get(f"/s/{self.token}", headers=CHROME)
            self.assertIn("p2.example.com", r.text)
            self.assertIn("p3.example.com", r.text)
        finally:
            s._dns_bundle = orig


if __name__ == "__main__":
    unittest.main()
