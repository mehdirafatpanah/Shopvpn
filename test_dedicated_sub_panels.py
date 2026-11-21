# -*- coding: utf-8 -*-
"""تست لینک جدای هر پنل در ساب مرکزی: ترتیب مدیر، محدودکردن سرویس به یک پنل، داده‌ی صفحه."""
import base64
import unittest

import dedicated_sub as ds
from test_dedicated_sub import CHROME, VLESS, add_service, b64, make_db

try:
    from starlette.testclient import TestClient
    HAVE_CLIENT = True
except Exception:  # pragma: no cover
    HAVE_CLIENT = False

V2 = "vless://11111111-1111-1111-1111-111111111111@p2.example.com:443?type=ws#p2"


class PanelLinksTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.db.set_setting("dsub_enabled", "1")
        self.db.set_setting("dsub_base_url", "https://central.example.com")
        self.cid = add_service(self.db)
        cc = self.db.ds_get_config(self.cid)
        self.p1 = int(cc["panel_server_id"])
        self.p2 = self.db.add_panel_server("W", "wui", "https://w.example.com", "u", "p")
        self.p3 = self.db.add_panel_server("D", "doctordns", "https://d.example.com", "u", "p")
        self.db.add_config_panel_link(self.cid, self.p2, "u2", "https://w.example.com/c/x")
        self.db.add_config_panel_link(self.cid, self.p3, "u3", "https://d.example.com/?u=u3")
        self.token = self.db.ds_get_or_create_token(self.cid)

    def cc(self):
        return self.db.ds_get_config(self.cid)

    def test_entries_follow_admin_order(self):
        self.assertEqual([e["panel_id"] for e in ds.panel_entries(self.db, self.cc())], [self.p1, self.p2, self.p3])
        self.db.reorder_panel_servers([self.p3, self.p1, self.p2])
        self.assertEqual([e["panel_id"] for e in ds.panel_entries(self.db, self.cc())], [self.p3, self.p1, self.p2])

    def test_page_links_ordered_and_central(self):
        self.db.reorder_panel_servers([self.p2, self.p3, self.p1])
        links = ds.panel_page_links(self.db, self.cc(), self.token)
        self.assertEqual([l["id"] for l in links], [self.p2, self.p3, self.p1])
        self.assertEqual(links[0]["url"], f"https://central.example.com/s/{self.token}/p/{self.p2}")
        self.assertEqual([l["type"] for l in links], ["W-UI", "Doctor DNS", ""])

    def test_page_link_uses_panel_profile_domain(self):
        pid = self.db.dsp_create("Iran", "https://iran.example.com", True)
        self.db.dsp_set_panels(pid, [self.p2])
        links = {l["id"]: l["url"] for l in ds.panel_page_links(self.db, self.cc(), self.token)}
        self.assertEqual(links[self.p2], f"https://iran.example.com/s/{self.token}/p/{self.p2}")
        self.assertTrue(links[self.p1].startswith("https://central.example.com/s/"))

    def test_single_panel_service_has_no_panel_list(self):
        cid = add_service(self.db, url="https://solo.example.com/sub/S")
        self.assertEqual(ds.panel_page_links(self.db, self.db.ds_get_config(cid), "t"), [])

    def test_panel_with_dsub_off_is_hidden(self):
        self.db.update_panel_server(self.p3, dsub_enabled=0)
        self.assertEqual([l["id"] for l in ds.panel_page_links(self.db, self.cc(), self.token)], [self.p1, self.p2])

    def test_scoped_config_targets_one_panel(self):
        scoped = ds.scoped_config(self.db, self.cc(), self.p3)
        self.assertTrue(ds.is_scoped(scoped))
        self.assertEqual((scoped["panel_server_id"], scoped["username"], scoped["subscription_url"]),
                         (self.p3, "u3", "https://d.example.com/?u=u3"))
        self.assertEqual(scoped["id"], self.cid)
        self.assertIsNone(ds.scoped_config(self.db, self.cc(), 99999))
        self.assertEqual(ds.ssh_uris_for_config(self.db, self.cid, scoped), [])
        self.assertEqual(ds.wg_files_for_config(self.db, self.cid, scoped), [])
        self.assertEqual(ds.ovpn_files_for_config(self.db, self.cid, scoped), [])

    def test_scoped_page_keeps_full_panel_list(self):
        scoped = ds.scoped_config(self.db, self.cc(), self.p2)
        links = ds.panel_page_links(self.db, scoped, self.token)
        self.assertEqual([(l["id"], l["cur"]) for l in links], [(self.p1, False), (self.p2, True), (self.p3, False)])

    def test_build_page_data_panels(self):
        links = ds.panel_page_links(self.db, self.cc(), self.token)
        data = ds.build_page_data(self.cc(), {}, [], ds.all_settings(self.db), "B", "https://x/s/t", None, panels=links)
        self.assertTrue(data["show"]["panels"])
        self.assertEqual([p["n"] for p in data["panels"]], ["P1", "W", "D"])
        plain = ds.build_page_data(self.cc(), {}, [], ds.all_settings(self.db), "B", "https://x/s/t", None)
        self.assertFalse(plain["show"]["panels"])

    def test_payg_panel_ids_follow_admin_order(self):
        try:
            import payg
        except ImportError:
            self.skipTest("aiogram not installed")
        self.db.set_setting("payg_panel_server_ids", f"[{self.p1}, {self.p2}, {self.p3}]")
        self.db.reorder_panel_servers([self.p3, self.p2, self.p1])
        self.assertEqual(payg.get_payg_panel_ids(self.db), [self.p3, self.p2, self.p1])


@unittest.skipUnless(HAVE_CLIENT, "starlette TestClient/httpx not installed")
class PerPanelRouteTests(unittest.TestCase):
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
            return self.up[url]

        s._http_get = fake
        self.u1, self.u2 = "https://p1.example.com/sub/K1", "https://p2.example.com/sub/K2"
        self.cid = add_service(self.db, url=self.u1)
        self.p1 = int(self.db.ds_get_config(self.cid)["panel_server_id"])
        self.p2 = self.db.add_panel_server("P2", "marzban", "https://p2.example.com", "u", "p")
        self.token = self.db.ds_get_or_create_token(self.cid)
        self.up[self.u1] = (200, {}, b64(VLESS))
        self.up[self.u2] = (200, {}, b64(V2))
        self.db.add_config_panel_link(self.cid, self.p2, "u2", self.u2)
        self.db.set_setting("dsub_enabled", "1")
        self.db.set_setting("dsub_base_url", "https://sub.example.com")
        self.client = TestClient(s.app, base_url="http://sub.example.com")

    def test_central_link_merges_all_panels(self):
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1.8.29"})
        self.assertEqual(base64.b64decode(r.content).decode().splitlines(), [VLESS, V2])

    def test_panel_link_returns_only_that_panel(self):
        r = self.client.get(f"/s/{self.token}/p/{self.p2}", headers={"user-agent": "v2rayNG/1.8.29"})
        self.assertEqual(base64.b64decode(r.content).decode().splitlines(), [V2])

    def test_unknown_panel_is_404(self):
        r = self.client.get(f"/s/{self.token}/p/9999", headers={"user-agent": "v2rayNG/1.8.29"})
        self.assertEqual(r.status_code, 404)

    def test_browser_page_lists_panel_links(self):
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"/s/{self.token}/p/{self.p2}", r.text)


if __name__ == "__main__":
    unittest.main()
