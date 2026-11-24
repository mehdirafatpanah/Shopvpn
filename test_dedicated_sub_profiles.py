# -*- coding: utf-8 -*-
"""تست ساب مرکزی + ساب‌های اختصاصی (پروفایل‌ها): انتخاب دامنه‌ی لینک، تنظیمات مستقل، تشخیص از روی Host."""
import unittest

import dedicated_sub as ds
from test_dedicated_sub import CHROME, add_service, make_db

try:
    from starlette.testclient import TestClient
    HAVE_CLIENT = True
except Exception:  # pragma: no cover
    HAVE_CLIENT = False


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.db.set_setting("dsub_enabled", "1")
        self.db.set_setting("dsub_base_url", "https://central.example.com")
        self.db.set_setting("dsub_brand", "Central")
        self.cid = add_service(self.db)
        self.panel_id = self.db.get_custom_config(self.cid)["panel_server_id"] if hasattr(self.db, "get_custom_config") \
            else self.db.ds_get_config(self.cid)["panel_server_id"]
        self.pid = self.db.dsp_create("Iran", "https://iran.example.com", True)

    def link(self):
        return ds.link_for_config(self.db, self.cid)

    def test_default_is_central(self):
        self.assertTrue(self.link().startswith("https://central.example.com/s/"))

    def test_panel_profile_changes_domain(self):
        self.db.dsp_set_panels(self.pid, [self.panel_id])
        self.assertTrue(self.link().startswith("https://iran.example.com/s/"))

    def test_disabled_profile_falls_back_to_central(self):
        self.db.dsp_set_panels(self.pid, [self.panel_id])
        self.db.dsp_update(self.pid, enabled=False)
        self.assertTrue(self.link().startswith("https://central.example.com/s/"))

    def test_master_off_means_no_link(self):
        self.db.dsp_set_panels(self.pid, [self.panel_id])
        self.db.set_setting("dsub_enabled", "0")
        self.assertIsNone(self.link())

    def test_multi_panel_stays_central(self):
        self.db.dsp_set_panels(self.pid, [self.panel_id])
        self.db.add_config_panel_link(self.cid, 2, "u2", "https://p2.example.com/sub/x")
        self.assertTrue(self.link().startswith("https://central.example.com/s/"))

    def test_settings_are_independent(self):
        prof = self.db.dsp_get(self.pid)
        self.assertEqual(ds.all_settings(self.db, prof)["dsub_brand"], "Central")  # ارث از مرکزی
        self.db.dsp_set_settings(self.pid, {"dsub_brand": "IranBrand", "dsub_theme": "dark"})
        prof = self.db.dsp_get(self.pid)
        s = ds.all_settings(self.db, prof)
        self.assertEqual((s["dsub_brand"], s["dsub_theme"]), ("IranBrand", "dark"))
        self.assertEqual(s["dsub_base_url"], "https://iran.example.com")
        self.assertEqual(ds.all_settings(self.db)["dsub_brand"], "Central")  # مرکزی دست‌نخورده

    def test_host_lookup_and_upstream_for_link(self):
        self.assertEqual(self.db.dsp_get_by_host("IRAN.example.com:443")["id"], self.pid)
        self.assertIsNone(self.db.dsp_get_by_host("central.example.com"))
        self.db.dsp_set_panels(self.pid, [self.panel_id])
        self.assertEqual(ds.upstream_for_link(self.db, self.link()), self.db.ds_get_config(self.cid)["subscription_url"])

    def test_delete_profile_releases_panels(self):
        self.db.dsp_set_panels(self.pid, [self.panel_id])
        self.db.dsp_delete(self.pid)
        self.assertTrue(self.link().startswith("https://central.example.com/s/"))

    def test_profile_without_domain_has_no_link(self):
        p2 = self.db.dsp_create("Empty", "", True)
        self.assertFalse(ds.is_enabled(self.db, self.db.dsp_get(p2)))


@unittest.skipUnless(HAVE_CLIENT, "starlette TestClient/httpx not installed")
class ServerHostTests(unittest.TestCase):
    def test_page_settings_follow_host(self):
        from sub_server import server as s
        db = make_db()
        s.db = db
        s.limiter = s.RateLimiter()
        s.cache = s.UpstreamCache()
        db.set_setting("dsub_enabled", "1")
        db.set_setting("dsub_base_url", "https://central.example.com")
        db.set_setting("dsub_notice", "NOTICE-CENTRAL")
        pid = db.dsp_create("Iran", "https://iran.example.com", True)
        db.dsp_set_settings(pid, {"dsub_notice": "NOTICE-IRAN"})
        cid = add_service(db)
        token = db.ds_get_or_create_token(cid)

        async def fake(url, ua):
            return 200, {}, b""
        s._http_get = fake
        c = TestClient(s.app)
        hdr = dict(CHROME)
        r1 = c.get(f"/s/{token}", headers={**hdr, "host": "central.example.com"})
        r2 = c.get(f"/s/{token}", headers={**hdr, "host": "iran.example.com"})
        self.assertIn("NOTICE-CENTRAL", r1.text)
        self.assertNotIn("NOTICE-IRAN", r1.text)
        self.assertIn("NOTICE-IRAN", r2.text)


class MergeProfileSettingsTests(unittest.TestCase):
    def test_values_override_and_unknown_keys_ignored(self):
        out = ds.merge_profile_settings({"dsub_brand": "A"}, {"dsub_theme": "dark", "bogus": "x", "dsub_enabled": "1"})
        self.assertEqual(out, {"dsub_brand": "A", "dsub_theme": "dark"})

    def test_reset_returns_to_inheritance(self):
        out = ds.merge_profile_settings({"dsub_brand": "A", "dsub_theme": "dark"}, {}, ["dsub_brand", "nope"])
        self.assertEqual(out, {"dsub_theme": "dark"})

    def test_inherits_central_after_reset(self):
        db = make_db()
        db.set_setting("dsub_brand", "Central")
        pid = db.dsp_create("Iran", "https://iran.example.com", True)
        db.dsp_set_settings(pid, ds.merge_profile_settings({}, {"dsub_brand": "Iran"}))
        self.assertEqual(ds.all_settings(db, ds.get_profile(db, pid))["dsub_brand"], "Iran")
        prof = ds.get_profile(db, pid)
        db.dsp_set_settings(pid, ds.merge_profile_settings(prof["settings"], {}, ["dsub_brand"]))
        self.assertEqual(ds.all_settings(db, ds.get_profile(db, pid))["dsub_brand"], "Central")
        db.set_setting("dsub_brand", "Central2")
        self.assertEqual(ds.all_settings(db, ds.get_profile(db, pid))["dsub_brand"], "Central2")


if __name__ == "__main__":
    unittest.main()
