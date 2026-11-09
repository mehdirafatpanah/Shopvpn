"""تست نود Stealth: منطق ایجنت (با xray جعلی)، رندر nginx/decoy نصاب، و provider بات."""
import asyncio
import base64
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


installer = _load("stealth_installer", ROOT / "deploy" / "install-shopvpn-stealth.py")


class FakeRunner:
    def __init__(self):
        self.calls, self.stats = [], {}

    def run(self, args, stdin=None, timeout=15):
        self.calls.append(list(args))
        if "statsquery" in args:
            out = {"stat": [{"name": f"user>>>{n}>>>traffic>>>downlink", "value": str(v)} for n, v in self.stats.items()]}
            self.stats = {}
            return 0, json.dumps(out), ""
        if "statsonlineiplist" in args:
            return 0, json.dumps({"ips": {"1.2.3.4": 1}}), ""
        return 0, "", ""


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["STEALTH_CONF_DIR"] = self.tmp
        os.environ["XRAY_CONFIG"] = os.path.join(self.tmp, "xray.json")
        self.agent = _load("stealth_agent", ROOT / "deploy" / "shopvpn-stealth-agent.py")
        self.node = installer.build_node("cdn.example.com", 443, ["ws", "httpupgrade", "grpc", "xhttp"], "T")
        Path(self.tmp, "node.json").write_text(json.dumps(self.node))
        self.fake = FakeRunner()
        self.agent.runner = self.fake

    def test_create_links_and_xray_sync(self):
        r = self.agent.op_create({"username": "u1", "volume_gb": 1, "duration_days": 30})
        self.assertTrue(r["subscription_url"].startswith("https://cdn.example.com/"))
        self.assertNotIn(":443", r["subscription_url"])
        users = self.agent._load_users()
        links = self.agent.build_links(self.node, users["u1"], "u1")
        self.assertEqual(len(links), 4)
        self.assertTrue(all(l.startswith("vless://") and "security=tls" in l and "encryption=none" in l for l in links))
        self.assertIn("mode=stream-one", [l for l in links if "type=xhttp" in l][0])
        self.assertFalse(any("packet-up" in l for l in links))
        self.assertTrue(any("adu" in c for c in self.fake.calls))

    def test_quota_expiry_first_use(self):
        self.agent.op_create({"username": "u2", "volume_gb": 1, "duration_days": 10, "start_on_first_use": True})
        self.assertEqual(self.agent._load_users()["u2"]["expire_ts"], 0)
        self.fake.stats = {"u2": 100}
        self.agent.poll_usage_once()
        u = self.agent._load_users()["u2"]
        self.assertEqual(u["used_bytes"], 100)
        self.assertGreater(u["expire_ts"], time.time() + 9 * 86400)
        self.fake.stats = {"u2": 2 * 1024 ** 3}
        self.agent.poll_usage_once()
        self.assertEqual(self.agent.user_status(self.agent._load_users()["u2"]), "limited")
        self.assertTrue(any("rmu" in c for c in self.fake.calls))
        r = self.agent.op_update("u2", {"add_volume_gb": 5, "reset_usage": True})
        self.assertEqual(r["status"], "active")
        self.assertEqual(r["used_bytes"], 0)

    def test_revoke_rename_delete(self):
        a = self.agent.op_create({"username": "u3", "volume_gb": 0, "duration_days": 0})
        b = self.agent.op_revoke("u3")
        self.assertNotEqual(a["uuid"], b["uuid"])
        self.assertNotEqual(a["subscription_url"], b["subscription_url"])
        self.agent.op_rename("u3", "u4")
        self.assertIn("u4", self.agent._load_users())
        self.assertTrue(self.agent.op_delete("u4")["deleted"])
        self.assertFalse(self.agent.op_delete("u4")["deleted"])
        with self.assertRaises(self.agent.ApiError):
            self.agent.op_create({"username": "bad name!"})

    def test_xray_config_is_vless_only_with_dns_and_stats(self):
        self.agent.op_create({"username": "u5", "volume_gb": 1, "duration_days": 1})
        cfg = self.agent.render_xray_config(self.node, self.agent._load_users())
        protos = {i["protocol"] for i in cfg["inbounds"]}
        self.assertEqual(protos, {"dokodemo-door", "vless"})
        nets = {i["streamSettings"]["network"] for i in cfg["inbounds"] if i["protocol"] == "vless"}
        self.assertEqual(nets, {"ws", "httpupgrade", "grpc", "xhttp"})
        self.assertEqual([i for i in cfg["inbounds"] if i.get("tag") == "in-xhttp"][0]["streamSettings"]["xhttpSettings"]["mode"], "stream-one")
        self.assertIn("servers", cfg["dns"])
        self.assertTrue(cfg["policy"]["levels"]["0"]["statsUserDownlink"])
        self.assertNotIn("api", [o["tag"] for o in cfg["outbounds"]])

    def test_http_api_auth_sub_and_decoy_behaviour(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self.agent.Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        api = f"{base}/{self.node['api_path']}"
        tok = {"Authorization": "Bearer " + self.node["api_token"]}
        with self.assertRaises(HTTPError) as cm:
            urlopen(Request(api + "/health"))
        self.assertEqual(cm.exception.code, 404)  # بدون توکن مثل مسیر ناموجود
        self.assertEqual(json.load(urlopen(Request(api + "/health", headers=tok)))["ok"], True)
        req = Request(api + "/users", data=json.dumps({"username": "h1", "volume_gb": 2, "duration_days": 5}).encode(),
                      headers={**tok, "Content-Type": "application/json"}, method="POST")
        created = json.load(urlopen(req))
        sub_token = created["subscription_url"].rsplit("/", 1)[1]
        resp = urlopen(f"{base}/{self.node['sub_path']}/{sub_token}")
        lines = base64.b64decode(resp.read()).decode().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("subscription-userinfo", resp.headers)
        self.assertTrue(json.load(urlopen(Request(api + "/users/h1/online", headers=tok)))["online"])
        srv.shutdown()


class InstallerTest(unittest.TestCase):
    def test_nginx_render_movie_and_proxy(self):
        node = installer.build_node("cdn.example.com", 443, ["ws", "httpupgrade", "grpc", "xhttp"], "T")
        conf = installer.render_nginx(node, "movie", cert="/c.pem", key="/k.pem")
        for t in node["transports"]:
            self.assertIn(t.get("path") or "/" + t["service"] + "/", conf)
        self.assertIn("grpc_pass grpc://unix:/run/xray/grpc.sock", conf)
        self.assertIn('if ($http_upgrade != "websocket") { return 404; }', conf)
        self.assertIn("error_page 404 /404.html", conf)
        self.assertEqual(conf.count("{"), conf.count("}"))
        proxy = installer.render_nginx(node, "proxy", "https://www.example.org", "/c.pem", "/k.pem", http2_directive=False)
        self.assertIn("proxy_pass https://www.example.org", proxy)
        self.assertIn("listen 443 ssl http2;", proxy)
        self.assertEqual(proxy.count("{"), proxy.count("}"))

    def test_decoy_site_and_paths_unique(self):
        d = Path(tempfile.mkdtemp())
        installer.render_decoy(d, "CineVault")
        for f in ("index.html", "browse.html", "watch.html", "404.html", "style.css", "robots.txt"):
            self.assertTrue((d / f).exists(), f)
        a = installer.build_node("x.com", 443, ["ws"], "T")
        b = installer.build_node("x.com", 443, ["ws"], "T")
        self.assertNotEqual(a["api_token"], b["api_token"])
        self.assertNotEqual(a["transports"][0]["path"], b["transports"][0]["path"])


class ProviderTest(unittest.TestCase):
    def test_registered_and_flow(self):
        sys.path.insert(0, str(ROOT))
        try:
            import aiohttp  # noqa: F401
        except ImportError:  # محیط تست بدون وابستگی‌های بات
            from unittest.mock import MagicMock
            sys.modules["aiohttp"] = MagicMock()
        from panel_providers import PROVIDERS, TOKEN_ONLY_PANEL_TYPES, NO_SETUP_PANEL_TYPES, PANEL_TYPE_LABELS, get_provider
        from panel_providers.stealth_provider import StealthProvider
        self.assertIs(PROVIDERS["stealth"], StealthProvider)
        self.assertIn("stealth", TOKEN_ONLY_PANEL_TYPES)
        self.assertIn("stealth", NO_SETUP_PANEL_TYPES)
        self.assertEqual(PANEL_TYPE_LABELS["stealth"], "Stealth VLESS")

        calls = []

        async def fake_call(self, method, path, action, body=None, allow_404=False):
            calls.append((method, path, body))
            if method == "DELETE":
                return {"deleted": True}
            if path.endswith("/online"):
                return {"online": True}
            return {"username": "a b", "subscription_url": "https://x/sub/tok", "used_bytes": 5,
                    "data_limit_bytes": 10, "status": "active"}

        StealthProvider._call = fake_call
        p = get_provider({"panel_type": "stealth", "api_url": "https://x/api/", "api_password": "t"})
        r = asyncio.run(p.create_user("a b", 3, 30, True))
        self.assertEqual(r.subscription_url, "https://x/sub/tok")
        self.assertEqual(asyncio.run(p.get_user_usage("a b"))["used_bytes"], 5)
        self.assertTrue(asyncio.run(p.is_client_online("a b")))
        self.assertTrue(asyncio.run(p.delete_user("a b")))
        self.assertEqual(calls[3][1], "/users/a%20b")


if __name__ == "__main__":
    unittest.main()
