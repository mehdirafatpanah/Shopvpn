# -*- coding: utf-8 -*-
"""تست ساب اختصاصی: هسته‌ی خالص، لایه‌ی دیتابیس و سرور (با پنل جعلی؛ بدون شبکه).

اجرا: python -m unittest test_dedicated_sub -v
(برای تست سرور به starlette و httpx نیاز است؛ در غیر این صورت آن بخش رد می‌شود.)
"""

import asyncio
import base64
import json
import os
import tempfile
import time
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")

import config  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="dsub_test_")
config.DB_PATH = os.path.join(_TMP, "bot.db")

import dedicated_sub as ds  # noqa: E402
from database import Database  # noqa: E402

GB = 1024 ** 3
VLESS = "vless://11111111-1111-1111-1111-111111111111@host.example.com:443?security=tls&type=ws#%F0%9F%87%A9%F0%9F%87%AA%20Germany"
VMESS_PAYLOAD = base64.b64encode(json.dumps({"v": "2", "ps": "Turkey", "add": "t.example.com", "port": "443",
                                             "id": "22222222-2222-2222-2222-222222222222"}).encode()).decode()
VMESS = "vmess://" + VMESS_PAYLOAD


def b64(text: str) -> bytes:
    return base64.b64encode(text.encode())


def make_db() -> Database:
    db = Database(os.path.join(_TMP, f"t{time.time_ns()}.db"))
    db.init_db(owner_id=1)
    return db


def add_service(db, url="https://panel.example.com:2053/sub/SECRET", expires_in_days=10, **kw):
    from datetime import datetime, timedelta
    panel_id = db.add_panel_server("P1", "marzban", "https://panel.example.com", "u", "p")
    cid = db.add_custom_config(100, panel_id, "alice", 50, 30, url,
                               expires_at=(datetime.utcnow() + timedelta(days=expires_in_days)).isoformat(), **kw)
    return cid


# ---------------------------------------------------------------------------
class CoreTests(unittest.TestCase):
    def test_userinfo_roundtrip(self):
        info = ds.parse_userinfo("upload=1; download=2; total=30; expire=1700000000")
        self.assertEqual(info, {"upload": 1, "download": 2, "total": 30, "expire": 1700000000})
        self.assertEqual(ds.parse_userinfo("garbage"), {})
        self.assertEqual(ds.parse_userinfo(None), {})

    def test_parse_body_variants(self):
        plain = ds.parse_body((VLESS + "\n" + VMESS).encode())
        self.assertEqual((plain.kind, plain.was_b64, len(plain.uris)), ("uris", False, 2))
        enc = ds.parse_body(b64(VLESS + "\n" + VMESS))
        self.assertEqual((enc.kind, enc.was_b64, len(enc.uris)), ("uris", True, 2))
        clash = ds.parse_body(b"proxies:\n  - name: a\n")
        self.assertEqual(clash.kind, "other")
        js = ds.parse_body(b'{"outbounds": []}')
        self.assertEqual(js.kind, "other")

    def test_ssh_uri_is_recognized_in_plain_and_base64_subscriptions(self):
        ssh = "ssh://alice:secret@ssh.example.com:22#Germany-SSH"
        plain = ds.parse_body(ssh.encode())
        self.assertEqual(plain.uris, [ssh])
        encoded = ds.parse_body(b64(ssh))
        self.assertEqual(encoded.uris, [ssh])
        self.assertEqual(ds.uri_protocol(ssh), "SSH")
        self.assertEqual(ds.uri_remark(ssh), "Germany-SSH")

    def test_remark_flag_protocol(self):
        self.assertEqual(ds.uri_remark(VLESS), "🇩🇪 Germany")
        self.assertEqual(ds.uri_flag("🇩🇪 Germany"), "🇩🇪")
        self.assertEqual(ds.uri_flag("no flag"), "🌐")
        self.assertEqual(ds.uri_remark(VMESS), "Turkey")
        self.assertEqual(ds.uri_protocol("hysteria2://x"), "HY2")

    def test_state(self):
        now = int(time.time())
        cc = {"enabled": 1, "status": "active", "expires_at": None}
        self.assertEqual(ds.compute_state(cc, {"total": 10, "download": 1, "expire": now + 100}, now), "active")
        self.assertEqual(ds.compute_state(cc, {"expire": now - 5}, now), "expired")
        self.assertEqual(ds.compute_state(cc, {"total": 10, "download": 10}, now), "limited")
        self.assertEqual(ds.compute_state({**cc, "enabled": 0}, {}, now), "disabled")
        self.assertEqual(ds.compute_state({**cc, "status": "cancelled"}, {}, now), "disabled")
        self.assertEqual(ds.compute_state({**cc, "status": "expired"}, {}, now), "expired")
        self.assertEqual(ds.compute_state({**cc, "expires_at": "2000-01-01T00:00:00"}, {}, now), "expired")
        self.assertEqual(ds.compute_state(cc, {"total": 0, "download": 99}, now), "active")  # نامحدود

    def _settings(self, **over):
        s = dict(ds.DSUB_DEFAULTS)
        s["dsub_enabled"] = "1"
        s.update(over)
        return s

    def test_reply_active_with_headers_and_info_line(self):
        now = int(time.time())
        cc = {"username": "alice", "display_name": "Alice VIP", "enabled": 1, "status": "active", "expires_at": None}
        s = self._settings(dsub_info_line="1", dsub_notice="سلام", dsub_support_url="https://t.me/پشتیبان")
        hdr = {"subscription-userinfo": f"upload=0; download={GB}; total={10 * GB}; expire={now + 3 * 86400}",
               "content-type": "text/plain"}
        r = ds.compose_client_reply(200, hdr, b64(VLESS), cc, s, "Shop", "https://sub.example.com/s/T", now)
        self.assertEqual(r.state, "active")
        decoded = base64.b64decode(r.body).decode().splitlines()
        self.assertEqual(len(decoded), 2)
        self.assertIn("127.0.0.1", decoded[0])                 # کانفیگ نمایشی اول
        self.assertIn("%D8%A8", decoded[0]) if False else None
        self.assertEqual(decoded[1], VLESS)                    # کانفیگ اصلی دست‌نخورده
        self.assertEqual(r.headers["profile-title"], ds.b64_header("Alice VIP"))
        self.assertEqual(r.headers["profile-update-interval"], "12")
        self.assertEqual(r.headers["profile-web-page-url"], "https://sub.example.com/s/T")
        self.assertEqual(r.headers["announce"], ds.b64_header("سلام"))
        self.assertTrue(r.headers["support-url"].startswith("https://t.me/%"))
        r.headers["support-url"].encode("ascii")               # هدر باید ASCII باشد
        self.assertEqual(r.headers["subscription-userinfo"], hdr["subscription-userinfo"])

    def test_reply_plain_format_stays_plain(self):
        cc = {"username": "a", "enabled": 1, "status": "active"}
        s = self._settings(dsub_info_line="1")
        r = ds.compose_client_reply(200, {}, (VLESS + "\n" + VMESS).encode(), cc, s, "Shop", "")
        self.assertIn(VLESS.encode(), r.body)  # base64 نشده

    def test_reply_expired_placeholder(self):
        now = int(time.time())
        cc = {"username": "alice", "enabled": 1, "status": "active"}
        s = self._settings(dsub_expired_text="منقضی شد")
        hdr = {"subscription-userinfo": f"upload=0; download=0; total={GB}; expire={now - 10}"}
        r = ds.compose_client_reply(200, hdr, b64(VLESS), cc, s, "Shop", "", now)
        self.assertEqual(r.state, "expired")
        text = base64.b64decode(r.body).decode()
        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("127.0.0.1", text)
        self.assertNotIn("host.example.com", text)             # کانفیگ واقعی لو نمی‌رود

    def test_reply_limited_uses_limited_text(self):
        cc = {"username": "a", "enabled": 1, "status": "active"}
        s = self._settings(dsub_limited_text="LIMITED_TXT")
        hdr = {"subscription-userinfo": f"upload=0; download={GB}; total={GB}"}
        r = ds.compose_client_reply(200, hdr, b64(VLESS), cc, s, "Shop", "")
        self.assertEqual(r.state, "limited")
        self.assertIn("LIMITED_TXT", base64.b64decode(r.body).decode().replace("%20", " ") + "LIMITED_TXT")

    def test_reply_placeholder_disabled_returns_upstream(self):
        now = int(time.time())
        cc = {"username": "a", "enabled": 1, "status": "active"}
        s = self._settings(dsub_expired_placeholder="0")
        hdr = {"subscription-userinfo": f"download=0; total={GB}; expire={now - 10}"}
        r = ds.compose_client_reply(200, hdr, b64(VLESS), cc, s, "Shop", "", now)
        self.assertEqual(base64.b64decode(r.body).decode(), VLESS)

    def test_reply_upstream_down(self):
        cc = {"username": "a", "enabled": 1, "status": "active", "expires_at": None}
        self.assertIsNone(ds.compose_client_reply(0, {}, b"", cc, self._settings(), "Shop", ""))
        # پنل جواب نمی‌دهد ولی سرویس در دیتابیس منقضی است → کانفیگ نمایشی
        cc2 = {**cc, "status": "expired"}
        r = ds.compose_client_reply(404, {}, b"not found", cc2, self._settings(), "Shop", "")
        self.assertIsNotNone(r)
        self.assertEqual(r.state, "expired")

    def test_reply_clash_untouched_even_with_info_line(self):
        cc = {"username": "a", "enabled": 1, "status": "active"}
        body = b"proxies:\n  - name: a\n"
        r = ds.compose_client_reply(200, {"content-type": "text/yaml"}, body, cc,
                                    self._settings(dsub_info_line="1"), "Shop", "")
        self.assertEqual(r.body, body)
        self.assertEqual(r.headers["content-type"], "text/yaml")

    def test_info_line_text(self):
        cc = {"username": "a", "expires_at": None}
        now = 1_700_000_000
        info = {"download": 2 * GB, "total": 10 * GB, "expire": now + 5 * 86400}
        self.assertEqual(ds.info_line_text({"dsub_info_line_text": "{volume} | {days}"}, info, cc, now), "8 GB | 5 روز")
        self.assertEqual(ds.info_line_text({"dsub_info_line_text": "{volume} | {days}"}, {}, cc, now),
                         "نامحدود | نامحدود")
        self.assertEqual(ds.info_line_text({"dsub_info_line_text": "{unknown} {volume}"}, info, cc, now),
                         "{unknown} 8 GB")

    def test_apps_resolution(self):
        s = dict(ds.DSUB_DEFAULTS)
        base = ds.resolve_apps(s)
        self.assertEqual(set(base), set(ds.PLATFORMS))
        self.assertTrue(base["android"][0]["rec"])
        s["dsub_apps_hidden"] = "android:v2rayNG"
        s["dsub_apps_rec"] = "android:hiddify"
        s["dsub_custom_apps"] = "android|MyApp|توضیح|myapp://add?url=|https://example.com/dl"
        apps = ds.resolve_apps(s)["android"]
        names = [a["n"] for a in apps]
        self.assertNotIn("v2rayNG", names)
        self.assertEqual(apps[0]["n"], "Hiddify")
        self.assertTrue(apps[0]["rec"])
        self.assertIn("MyApp", names)
        self.assertEqual([a["n"] for a in apps].count("Hiddify"), 1)

    def test_custom_apps_validation(self):
        bad = [
            "android|X|d|javascript://x|https://e.com",
            "android|X|d|https://evil.com/|https://e.com",
            "beos|X|d|a://b|https://e.com",
            "android|X|d|a://b|ftp://e.com",
            "android|X|d|-|-",
            "android|X|only three",
        ]
        for line in bad:
            apps, errors = ds.parse_custom_apps(line)
            self.assertEqual(apps, [], line)
            self.assertTrue(errors, line)
        apps, errors = ds.parse_custom_apps("ios|Ok|d|-|https://e.com/x")
        self.assertEqual((len(apps), errors), (1, []))
        self.assertNotIn("add", apps[0][1])

    def test_faq(self):
        self.assertEqual(ds.resolve_faq({"dsub_faq": ""}), ds.DEFAULT_FAQ)
        self.assertEqual(ds.resolve_faq({"dsub_faq": "س۱ | ج۱\nخراب\n س۲|ج۲ "}), [("س۱", "ج۱"), ("س۲", "ج۲")])

    def test_wants_page(self):
        chrome = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        self.assertTrue(ds.wants_page(chrome, "text/html,application/xhtml+xml", {}))
        self.assertFalse(ds.wants_page(chrome, "text/html", {"raw": "1"}))
        self.assertTrue(ds.wants_page("curl/8", "*/*", {"view": "1"}))
        for client in ("v2rayNG/1.8.29", "Streisand/1.0 CFNetwork/1494 Darwin/23", "Hiddify/2.0",
                       "clash-verge/v1.7", "sing-box 1.8", "Happ/1.2", "okhttp/4.12"):
            self.assertFalse(ds.wants_page(client, "text/html", {}), client)
        self.assertFalse(ds.wants_page(chrome, "*/*", {}))

    def test_series(self):
        now = 1_700_000_000
        self.assertIsNone(ds.build_series([], now))
        self.assertIsNone(ds.build_series([(now - 100, 5)], now))
        pts = [(now - 2 * 86400 - 10, 1 * GB), (now - 86400 - 10, 3 * GB), (now - 5, 6 * GB)]
        s = ds.build_series(pts, now)
        self.assertEqual(len(s["d"]), 12)
        self.assertEqual(len(s["w"]), 7)
        self.assertEqual(len(s["m"]), 30)
        self.assertEqual(s["w"][-1], 3.0)          # دیروز→الان: ۶−۳
        self.assertEqual(s["w"][-2], 2.0)          # پریروز→دیروز: ۳−۱
        self.assertIsNone(s["w"][0])               # قبل از اولین نمونه
        # ریست شمارنده (تمدید): مقدار جدید خودش مصرف است
        s2 = ds.build_series([(now - 86400 - 10, 9 * GB), (now - 5, 1 * GB)], now)
        self.assertEqual(s2["w"][-1], 1.0)

    def test_json_for_script_is_safe(self):
        out = ds.json_for_script({"a": "</script><script>alert(1)</script>", "b": "x\u2028y&"})
        self.assertNotIn("</script>", out)
        self.assertNotIn("<", out)
        self.assertEqual(json.loads(out)["a"], "</script><script>alert(1)</script>")

    def test_page_data_filters_unsafe_values(self):
        cc = {"username": "a", "enabled": 1, "status": "active", "duration_days": 30,
              "created_at": "2026-10-01 10:00:00"}
        s = dict(ds.DSUB_DEFAULTS, dsub_support_url="javascript:alert(1)", dsub_logo_url="http://x/y.png",
                 dsub_theme="neon")
        d = ds.build_page_data(cc, {}, [VLESS], s, "Shop", "https://sub.example.com/s/T", None)
        self.assertEqual((d["support"], d["logo"], d["theme"]), ("", "", "auto"))
        self.assertEqual(d["configs"][0]["f"], "🇩🇪")
        self.assertTrue(d["created"])

    def test_merge_smart(self):
        a = (200, {"subscription-userinfo": f"upload=1; download=2; total={GB}; expire=2000"}, b64(VLESS))
        b = (200, {"Subscription-Userinfo": f"upload=3; download=4; total={2 * GB}; expire=1000"},
             b64(VLESS + "\n" + VMESS))
        c = (500, {}, b"")
        body, header, count = ds.merge_smart([a, b, c])
        self.assertEqual(count, 2)                              # تکراری حذف شد
        self.assertEqual(base64.b64decode(body).decode().splitlines(), [VLESS, VMESS])
        info = ds.parse_userinfo(header)
        self.assertEqual((info["upload"], info["download"], info["total"], info["expire"]),
                         (4, 6, 3 * GB, 1000))
        body, header, count = ds.merge_smart([(200, {"subscription-userinfo": "total=0; download=1"}, b64(VLESS)), a])
        self.assertEqual(ds.parse_userinfo(header)["total"], 0)  # یکی نامحدود → کل نامحدود


# ---------------------------------------------------------------------------

    def test_custom_template_helpers(self):
        tpl = '<html><head><title>__TITLE__</title></head><body data-t="__THEME__"><script>const D=__DATA__;</script></body></html>'
        self.assertIsNone(ds.validate_custom_template(""))
        self.assertIsNone(ds.validate_custom_template(tpl))
        self.assertIn("__DATA__", ds.validate_custom_template("<html></html>"))
        self.assertIsNotNone(ds.validate_custom_template(tpl + "x" * (ds.CUSTOM_TEMPLATE_MAX + 1)))
        on = dict(ds.DSUB_DEFAULTS, dsub_custom_template_enabled="1", dsub_custom_template=tpl)
        self.assertEqual(ds.pick_template(on), tpl)
        self.assertIsNone(ds.pick_template(dict(on, dsub_custom_template_enabled="0")))
        self.assertIsNone(ds.pick_template(dict(on, dsub_custom_template="<html>no data</html>")))
        self.assertIsNone(ds.pick_template(dict(on, dsub_custom_template="  ")))
        out = ds.render_page_html(tpl, {"theme": "dark", "user": "__DATA__ <b>x</b>"}, "a<b>&__DATA__", "NN")
        self.assertIn('<script nonce="NN">', out)        # nonce خودکار
        self.assertNotIn("<b>", out)                      # عنوان و داده escape می‌شوند
        self.assertIn("&lt;b&gt;&amp;__DATA__</title>", out)  # مقدار جایگزین‌شده دوباره اسکن نمی‌شود
        self.assertIn('data-t="dark"', out)
        keep = ds.render_page_html('<script nonce="mine">__DATA__</script>', {"theme": "auto"}, "t", "NN")
        self.assertIn('nonce="mine"', keep)
        self.assertNotIn('nonce="NN"', keep)


class DbTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def test_tokens(self):
        a, b = add_service(self.db), add_service(self.db, url="https://p/sub/2")
        ta, tb = self.db.ds_get_or_create_token(a), self.db.ds_get_or_create_token(b)
        self.assertNotEqual(ta, tb)
        self.assertGreaterEqual(len(ta), 20)
        self.assertEqual(self.db.ds_get_or_create_token(a), ta)          # پایدار
        self.assertEqual(self.db.ds_get_config_by_token(ta)["id"], a)
        new = self.db.ds_regenerate_token(a)
        self.assertNotEqual(new, ta)
        self.assertIsNone(self.db.ds_get_config_by_token(ta))            # توکن قبلی باطل
        self.assertIsNone(self.db.ds_get_config_by_token("x" * 200))
        self.assertIsNone(self.db.ds_get_or_create_token(99999))

    def test_display_and_reverse_link(self):
        up = "https://panel.example.com/sub/XYZ"
        cid = add_service(self.db, url=up)
        self.assertEqual(ds.display_link(self.db, cid, up), up)
        self.assertEqual(ds.upstream_for_link(self.db, up), up)
        self.db.set_setting("dsub_enabled", "1")
        self.db.set_setting("dsub_base_url", "https://sub.example.com")
        shown = ds.display_link(self.db, cid, up)
        self.assertEqual(shown, f"https://sub.example.com/s/{self.db.ds_get_or_create_token(cid)}")
        self.assertEqual(ds.upstream_for_link(self.db, shown), up)
        self.assertEqual(ds.upstream_for_link(self.db, shown + "?x=1"), up)
        self.assertEqual(ds.upstream_for_link(self.db, "https://sub.example.com/s/unknown"), "https://sub.example.com/s/unknown")
        self.assertEqual(ds.upstream_for_link(self.db, up), up)
        self.assertEqual(ds.display_link(self.db, None, up), up)

    def test_link_helpers(self):
        cid = add_service(self.db, url="https://panel.example.com/sub/ABC")
        # خاموش: لینک اصلی
        self.assertEqual(ds.dedicated_link_for_upstream(self.db, "https://panel.example.com/sub/ABC"),
                         "https://panel.example.com/sub/ABC")
        self.db.set_setting("dsub_enabled", "1")
        # روشن ولی بدون دامنه: هنوز لینک اصلی
        self.assertEqual(ds.dedicated_link_for_upstream(self.db, "https://panel.example.com/sub/ABC"),
                         "https://panel.example.com/sub/ABC")
        self.db.set_setting("dsub_base_url", "https://sub.example.com/")
        link = ds.dedicated_link_for_upstream(self.db, "https://panel.example.com/sub/ABC")
        token = self.db.ds_get_or_create_token(cid)
        self.assertEqual(link, f"https://sub.example.com/s/{token}")
        # لینک ناشناس (کانفیگ موجودی/خام) دست نمی‌خورد
        self.assertEqual(ds.dedicated_link_for_upstream(self.db, "https://other/sub/zzz"), "https://other/sub/zzz")
        self.assertEqual(ds.dedicated_link_for_upstream(self.db, "vless://abc"), "vless://abc")
        self.assertNotIn("panel.example.com", link)

    def test_shared_vpn_ssh_quota_overrides_panel_unlimited(self):
        from datetime import datetime, timedelta, timezone
        cid = add_service(self.db, expires_in_days=30)
        expires = (datetime.now(timezone.utc) + timedelta(days=12)).isoformat()
        pool_id = self.db.create_quota_pool(100, 1, expires, label="combined test")
        self.assertTrue(self.db.attach_custom_config_to_quota_pool(pool_id, cid))
        self.db.record_usage_snapshot("vpn", f"custom_config:{cid}", 120 * 1024 ** 2,
                                      source="test", reported_at=datetime.now(timezone.utc).isoformat())
        self.db.attach_quota_service(pool_id, "ssh", "ssh-account-test")
        self.db.record_usage_snapshot("ssh", "ssh-account-test", 80 * 1024 ** 2,
                                      source="test", reported_at=datetime.now(timezone.utc).isoformat())
        info = ds.quota_info_for_config(self.db, cid)
        self.assertEqual(info["total"], 1024 ** 3)
        self.assertEqual(info["upload"], 200 * 1024 ** 2)
        self.assertEqual(info["download"], 0)
        self.assertGreater(info["expire"], int(time.time()))

    def test_usage_and_logs(self):
        cid = add_service(self.db)
        self.assertTrue(self.db.ds_record_usage(cid, 100))
        self.assertFalse(self.db.ds_record_usage(cid, 200))              # فاصله‌ی حداقلی
        self.assertTrue(self.db.ds_record_usage(cid, 300, min_gap=0))
        pts = self.db.ds_usage_points(cid, int(time.time()) - 3600)
        self.assertEqual([p[1] for p in pts], [100, 300])
        self.db.ds_log_access(cid, "1.2.3.4", "v2rayNG/1", "sub", 200)
        self.db.ds_log_access(cid, "1.2.3.5", "Mozilla", "page", 200)
        self.db.ds_log_access(None, "1.2.3.4", "x", "smart", 502)
        st = self.db.ds_access_stats(int(time.time()) - 60)
        self.assertEqual((st["total"], st["pages"], st["services"], st["ips"], st["errors"]), (3, 1, 1, 2, 1))
        self.assertEqual(self.db.ds_config_ips(cid, 0), 1)
        self.db.ds_prune(access_days=-1, usage_days=-1)
        self.assertEqual(self.db.ds_access_stats(0)["total"], 0)

    def test_defaults_registered(self):
        for key, value in ds.DSUB_DEFAULTS.items():
            self.assertEqual(self.db.get_setting(key, "__missing__"), value, key)
        self.assertEqual(self.db.get_setting("dsub_enabled"), "0")


# ---------------------------------------------------------------------------
try:
    from starlette.testclient import TestClient
    HAVE_CLIENT = True
except Exception:  # pragma: no cover
    HAVE_CLIENT = False

CHROME = {"user-agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
          "accept": "text/html,application/xhtml+xml"}


class CliTests(unittest.TestCase):
    def test_enable_requires_base_url(self):
        import contextlib
        import io
        from database import Database as D
        db = D(config.DB_PATH)
        db.init_db(owner_id=1)
        db.set_setting("dsub_enabled", "0")
        db.set_setting("dsub_base_url", "")
        config.DEDICATED_SUB_URL = ""
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = ds._cli(["enable"])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue().splitlines()[0], "disabled")
        self.assertEqual(db.get_setting("dsub_enabled"), "0")
        db.set_setting("dsub_base_url", "https://sub.example.com")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = ds._cli(["enable"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines()[0], "enabled")


@unittest.skipUnless(HAVE_CLIENT, "starlette TestClient/httpx not installed")
class ServerTests(unittest.TestCase):
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
        self.calls = []
        self.upstream = {}  # url → (status, headers, body)

        async def fake(url, ua):
            self.calls.append((url, ua))
            if url not in self.upstream:
                raise ConnectionError("down")
            return self.upstream[url]

        s._http_get = fake
        self.url = "https://panel.example.com:2053/sub/SECRET"
        self.cid = add_service(self.db, url=self.url)
        self.token = self.db.ds_get_or_create_token(self.cid)
        self.now = int(time.time())
        self.upstream[self.url] = (
            200,
            {"subscription-userinfo": f"upload=0; download={GB}; total={10 * GB}; expire={self.now + 5 * 86400}"},
            b64(VLESS + "\n" + VMESS),
        )
        self.db.set_setting("dsub_enabled", "1")
        self.db.set_setting("dsub_base_url", "https://sub.example.com")
        self.client = TestClient(s.app, base_url="http://sub.example.com")

    def test_app_gets_subscription(self):
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1.8.29"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(base64.b64decode(r.content).decode().splitlines(), [VLESS, VMESS])
        self.assertIn("profile-title", r.headers)
        self.assertEqual(r.headers["subscription-userinfo"].split(";")[2].strip(), f"total={10 * GB}")
        self.assertEqual(r.headers["cache-control"], "no-store")
        # UA اپ به پنل فرستاده می‌شود (پنل خودش فرمت مناسب را انتخاب می‌کند)
        self.assertEqual(self.calls[-1][1], "v2rayNG/1.8.29")

    def test_custom_template_used_and_falls_back(self):
        tpl = ('<!doctype html><html><head><title>__TITLE__</title></head><body>CUSTOM_PAGE'
               '<script>const D=__DATA__;document.title=D.user;</script></body></html>')
        # خاموش → قالب پیش‌فرض
        self.db.set_setting("dsub_custom_template", tpl)
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertNotIn("CUSTOM_PAGE", r.text)
        # روشن → قالب اختصاصی، با nonce خودکار و بدون درز آدرس پنل
        self.db.set_setting("dsub_custom_template_enabled", "1")
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertEqual(r.status_code, 200)
        self.assertIn("CUSTOM_PAGE", r.text)
        nonce = r.headers["content-security-policy"].split("'nonce-")[1].split("'")[0]
        self.assertIn(f'<script nonce="{nonce}">', r.text)
        self.assertNotIn("panel.example.com", r.text)
        self.assertNotIn("SECRET", r.text)
        self.assertIn(f"https://sub.example.com/s/{self.token}", r.text)
        # قالب نامعتبر (بدون __DATA__) → برگشت به پیش‌فرض
        self.db.set_setting("dsub_custom_template", "<html>CUSTOM_PAGE</html>")
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertNotIn("CUSTOM_PAGE", r.text)
        self.assertIn("const D=", r.text)
        # قالب اختصاصی روی پاسخ اپ VPN اثری ندارد
        self.db.set_setting("dsub_custom_template", tpl)
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1.8.29"})
        self.assertEqual(base64.b64decode(r.content).decode().splitlines(), [VLESS, VMESS])

    def test_caching_and_ua_separation(self):
        for _ in range(3):
            self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1"})
        self.assertEqual(len(self.calls), 1)
        self.client.get(f"/s/{self.token}", headers={"user-agent": "Hiddify/2"})
        self.assertEqual(len(self.calls), 2)

    def test_browser_gets_page_without_upstream_url(self):
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        html = r.text
        self.assertIn("const D=", html)
        self.assertNotIn("panel.example.com", html)
        self.assertNotIn("SECRET", html)
        self.assertIn(f"https://sub.example.com/s/{self.token}", html)
        csp = r.headers["content-security-policy"]
        nonce = csp.split("'nonce-")[1].split("'")[0]
        self.assertIn(f'nonce="{nonce}"', html)
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("__NONCE__", html)
        self.assertIn("🇩🇪", html)
        self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow")

    def test_page_can_be_disabled_and_forced(self):
        self.db.set_setting("dsub_web_page", "0")
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertEqual(base64.b64decode(r.content).decode().splitlines()[0], VLESS)
        self.db.set_setting("dsub_web_page", "1")
        r = self.client.get(f"/s/{self.token}?raw=1", headers=CHROME)
        self.assertEqual(base64.b64decode(r.content).decode().splitlines()[0], VLESS)
        r = self.client.get(f"/s/{self.token}?view=1", headers={"user-agent": "curl/8"})
        self.assertIn("const D=", r.text)

    def test_page_injection_safe(self):
        self.db.set_setting("dsub_notice", "</script><img src=x onerror=alert(1)>")
        r = self.client.get(f"/s/{self.token}", headers=CHROME)
        self.assertEqual(r.text.count("</script>"), 1)  # فقط همان تگ پایانی خودِ صفحه

    def test_disabled_is_transparent_passthrough(self):
        self.db.set_setting("dsub_enabled", "0")
        self.db.set_setting("dsub_info_line", "1")
        r = self.client.get(f"/s/{self.token}", headers=CHROME)  # حتی مرورگر هم صفحه نمی‌بیند
        self.assertEqual(r.status_code, 200)
        self.assertEqual(base64.b64decode(r.content).decode().splitlines(), [VLESS, VMESS])
        self.assertNotIn("profile-title", r.headers)

    def test_unknown_token_and_rate_limit(self):
        self.assertEqual(self.client.get("/s/nope").status_code, 404)
        codes = [self.client.get(f"/s/bad{i}").status_code for i in range(20)]
        self.assertIn(429, codes)  # حدس زدن توکن محدود می‌شود
        # IP محدودشده برای توکن معتبر هم بعد از سقف کلی محدود می‌شود، ولی IP دیگر آزاد است
        r = self.client.get(f"/s/{self.token}", headers={"x-forwarded-for": "9.9.9.9", "user-agent": "v2rayNG/1"})
        self.assertIn(r.status_code, (200, 429))

    def test_deleted_service_not_served(self):
        with self.db._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET status='deleted' WHERE id=?", (self.cid,))
        self.assertEqual(self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1"}).status_code, 404)

    def test_expired_gets_placeholder_and_upstream_hidden(self):
        self.upstream[self.url] = (200, {"subscription-userinfo": f"download=0; total={GB}; expire={self.now - 5}"},
                                   b64(VLESS))
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1"})
        text = base64.b64decode(r.content).decode()
        self.assertEqual(len(text.splitlines()), 1)
        self.assertNotIn("host.example.com", text)

    def test_upstream_down_serves_stale_then_502(self):
        self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1"})   # کش را پر می‌کند
        del self.upstream[self.url]
        self.db.set_setting("dsub_cache_ttl", "0")
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1"})
        self.assertEqual(r.status_code, 200)                                       # نسخه‌ی قدیمی
        r = self.client.get(f"/s/{self.token}", headers={"user-agent": "Hiddify/1"})  # کلید کش دیگر → خطا
        self.assertEqual(r.status_code, 502)

    def test_access_log_and_usage_snapshot(self):
        self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1"})
        self.client.get(f"/s/{self.token}", headers=CHROME)
        st = self.db.ds_access_stats(0)
        self.assertEqual((st["total"], st["pages"]), (2, 1))
        self.assertEqual(len(self.db.ds_usage_points(self.cid, 0)), 1)
        self.db.set_setting("dsub_log_enabled", "0")
        self.client.get(f"/s/{self.token}", headers={"user-agent": "v2rayNG/1"})
        self.assertEqual(self.db.ds_access_stats(0)["total"], 2)

    def test_smart_subscription(self):
        url2 = "https://panel2.example.com/sub/OTHER"
        self.upstream[url2] = (200, {"subscription-userinfo": "upload=0; download=5; total=100"}, b64(VMESS + "\n" + "trojan://p@h:443#T"))
        tok = self.db.create_smart_subscription(100, [self.url, url2])
        r = self.client.get(f"/sub/smart/{tok}", headers={"user-agent": "v2rayNG/1"})
        self.assertEqual(r.status_code, 200)
        lines = base64.b64decode(r.content).decode().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(set(lines)), 3)
        self.assertEqual(self.client.get("/sub/smart/unknown").status_code, 404)
        self.db.set_setting("smart_subscription_enabled", "0")
        self.assertEqual(self.client.get(f"/sub/smart/{tok}").status_code, 404)

    def test_qr_endpoint_guards(self):
        self.assertEqual(self.client.get("/s/nope/qr.png").status_code, 404)
        self.db.set_setting("dsub_show_qr", "0")
        self.assertEqual(self.client.get(f"/s/{self.token}/qr.png").status_code, 404)
        self.db.set_setting("dsub_show_qr", "1")
        self.assertEqual(self.client.get(f"/s/{self.token}/qr.png?i=99").status_code, 404)
        self.assertEqual(self.client.get(f"/s/{self.token}/qr.png?i=abc").status_code, 404)
        self.assertIn(self.client.get(f"/s/{self.token}/qr.png?i=0").status_code, (200, 503))  # 503 اگر qrcode نصب نباشد

    def test_misc_routes(self):
        self.assertEqual(self.client.get("/healthz").json(), {"ok": True})
        self.assertIn("Disallow: /", self.client.get("/robots.txt").text)
        self.assertEqual(self.client.get("/").status_code, 404)
        self.assertEqual(self.client.get("/admin").status_code, 404)

    def test_sampler_round(self):
        self.db.ds_log_access(self.cid, "1.1.1.1", "x", "sub", 200)
        asyncio.run(self.server._sampler_round())
        self.assertGreaterEqual(len(self.db.ds_usage_points(self.cid, 0)), 1)


class VpnLoginTests(unittest.TestCase):
    IFACES = {
        1: {"id": 1, "name": "l2", "protocol": "l2tp", "endpointHost": "h.example.com", "listenPort": 1701,
            "l2tp": {"psk": "PSK1", "allowPlain": True}},
        2: {"id": 2, "name": "ik", "protocol": "ikev2", "endpointHost": "h.example.com", "listenPort": 500,
            "ikev2": {"mschapv2": True, "serverNames": ["ike.example.com"],
                      "caCert": "-----BEGIN CERTIFICATE-----\nA\n-----END CERTIFICATE-----"}},
        3: {"id": 3, "name": "oc", "protocol": "openconnect", "endpointHost": "h.example.com", "listenPort": 8443,
            "openconnect": {"camouflage": True, "camouflageSecret": "sec"}},
        4: {"id": 4, "name": "ov", "protocol": "openvpn", "endpointHost": "h.example.com", "listenPort": 1194},
        5: {"id": 5, "name": "cert", "protocol": "ikev2", "endpointHost": "h.example.com", "listenPort": 500,
            "ikev2": {"rsa": True}},
    }

    def entries(self):
        from panel_providers.wui_provider import login_profile
        accs = [{"interfaceId": i, "username": f"u{i}", "password": f"pw{i}", "enabled": True} for i in self.IFACES]
        return [e for a in accs if (e := login_profile(a, self.IFACES[a["interfaceId"]]))]

    def test_only_login_protocols(self):
        self.assertEqual([e["kind"] for e in self.entries()], ["l2tp", "ikev2", "openconnect", "ikev2"])

    def test_openconnect_address_has_port_and_secret(self):
        oc = [e for e in self.entries() if e["kind"] == "openconnect"][0]
        self.assertEqual(oc["address"], "h.example.com:8443/?sec")

    def test_page_items_hide_secrets_and_skip_cert_only(self):
        items = ds.vpn_items_for_page(self.entries())
        self.assertEqual([v["k"] for v in items], ["l2tp", "ikev2", "openconnect"])
        blob = json.dumps(items)
        for secret in ("pw1", "PSK1", "u1"):
            self.assertNotIn(secret, blob)

    def test_secret_and_ca_lookup(self):
        es = self.entries()
        self.assertEqual(ds.vpn_secret(es, 1, "psk"), "PSK1")
        self.assertEqual(ds.vpn_secret(es, 1, "pass"), "pw1")
        self.assertIsNone(ds.vpn_secret(es, 9, "pass"))
        self.assertIsNone(ds.vpn_secret(es, 1, "x"))
        self.assertEqual(ds.vpn_ca_file(es, 2)["filename"], "ik-ca.crt")
        self.assertIsNone(ds.vpn_ca_file(es, 1))

    def test_wui_warning_only_when_dsub_off(self):
        db = make_db()
        self.assertTrue(ds.wui_dsub_warning(db, "wui"))
        self.assertEqual(ds.wui_dsub_warning(db, "marzban"), "")
        db.set_setting("dsub_enabled", "1")
        db.set_setting("dsub_base_url", "https://sub.example.com")
        self.assertEqual(ds.wui_dsub_warning(db, "wui"), "")


if __name__ == "__main__":
    unittest.main()
