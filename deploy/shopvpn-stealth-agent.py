#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ShopVPN Stealth Agent — مدیریت کاربران یک نود VLESS «استیلث» (xray + nginx).

روی همان سرور نصب می‌شود (install-shopvpn-stealth.sh). فقط به stdlib نیاز دارد.
nginx این ایجنت را روی دو مسیر مخفی عمومی می‌کند (برای عبور از پروکسی کلادفلر):
  /<api_path>/...   API مدیریتی (فقط با Bearer token)  ← بات از این استفاده می‌کند
  /<sub_path>/<tok> لینک اشتراک کاربر (base64 از لینک‌های vless)

وظایف:
  - ساخت/حذف/تمدید/ابطال کاربر، سقف حجم و انقضا (با شروع از اولین مصرف)
  - اضافه/حذف کاربر روی xray بدون قطع بقیه (xray api adu/rmu)، و بازسازی کامل
    config فقط در صورت شکست API
  - شمارش مصرف با xray statsquery و قطع خودکار بعد از اتمام حجم/زمان
  - ساخت لینک vless برای هر ترنسپورت فعال (ws / httpupgrade / grpc / xhttp-stream-one)
"""
import base64
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid as uuidlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlsplit

VERSION = "1.1.0"
CONF_DIR = os.environ.get("STEALTH_CONF_DIR", "/etc/shopvpn-stealth")
NODE_FILE = os.path.join(CONF_DIR, "node.json")
USERS_FILE = os.path.join(CONF_DIR, "users.json")
XRAY_BIN = os.environ.get("XRAY_BIN", "/usr/local/bin/xray")
XRAY_CONFIG = os.environ.get("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
XRAY_API = os.environ.get("XRAY_API", "127.0.0.1:10085")
GB = 1024 ** 3
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

_lock = threading.RLock()


# ───────────────────────── ذخیره‌سازی ─────────────────────────

def load_node() -> dict:
    with open(NODE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_users() -> dict:
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_users(users: dict) -> None:
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, USERS_FILE)


# ───────────────────────── xray ─────────────────────────

class XrayRunner:
    """لایه‌ی نازک روی CLI xray؛ در تست‌ها جایگزین می‌شود."""

    def run(self, args, stdin=None, timeout=15):
        p = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr


runner = XrayRunner()


def active_transports(node: dict) -> list:
    return [t for t in node.get("transports", []) if t.get("enabled", True)]


def inbound_tag(transport: str) -> str:
    return f"in-{transport}"


def _client_obj(user: dict, name: str) -> dict:
    # بدون flow: xtls-rprx-vision با ws/grpc/httpupgrade سازگار نیست
    return {"id": user["uuid"], "email": name, "level": 0}


def xray_add_user(name: str, user: dict, node: dict) -> bool:
    """کاربر را روی همه‌ی inbound های فعال اضافه می‌کند. True = موفق."""
    for t in active_transports(node):
        # listen+port الزامی است: بدون آن xray خطای "Listen on AnyIP but no Port(s) set" می‌دهد،
        # ولی exit code را 0 برمی‌گرداند و می‌نویسد "Added 0 user(s)" (فقط برای ساخت config؛ inbound جدیدی ساخته نمی‌شود)
        cfg = {"inbounds": [{
            "tag": inbound_tag(t["name"]), "listen": "127.0.0.1", "port": 1, "protocol": "vless",
            "settings": {"clients": [_client_obj(user, name)], "decryption": "none"},
        }]}
        tmp = os.path.join(CONF_DIR, f".adu-{secrets.token_hex(4)}.json")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            rc, out, err = runner.run([XRAY_BIN, "api", "adu", f"--server={XRAY_API}", tmp])
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        # exit code قابل‌اعتماد نیست؛ باید واقعاً "Added N user(s)" با N>=1 دیده شود
        m = re.search(r"Added (\d+) user", (out or "") + "\n" + (err or ""))
        if rc != 0 or not m or int(m.group(1)) < 1:
            print(f"xray adu failed for {name} on {t['name']}: rc={rc} {(out or '')[-200:]} {(err or '')[-200:]}",
                  file=sys.stderr, flush=True)
            return False
    return True


def xray_remove_user(name: str, node: dict) -> bool:
    ok = True
    for t in active_transports(node):
        rc, out, err = runner.run([XRAY_BIN, "api", "rmu", f"--server={XRAY_API}", f"-tag={inbound_tag(t['name'])}", name])
        if rc != 0 and "not found" not in (out + err).lower():
            ok = False
    return ok


def render_xray_config(node: dict, users: dict) -> dict:
    """config کامل xray: VLESS-only روی unix socket، آمار، و DNS داخلی."""
    clients = [_client_obj(u, n) for n, u in users.items() if is_usable(u)]
    inbounds = [{
        "tag": "api-in", "listen": "127.0.0.1", "port": int(XRAY_API.rsplit(":", 1)[1]),
        "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"},
    }]
    for t in active_transports(node):
        name = t["name"]
        sock = t.get("socket") or f"/run/xray/{name}.sock"
        stream = {"network": "tcp", "security": "none"}
        if name == "ws":
            stream = {"network": "ws", "wsSettings": {"path": t["path"]}}
        elif name == "httpupgrade":
            stream = {"network": "httpupgrade", "httpupgradeSettings": {"path": t["path"]}}
        elif name == "grpc":
            stream = {"network": "grpc", "grpcSettings": {"serviceName": t["service"]}}
        elif name == "xhttp":
            stream = {"network": "xhttp", "xhttpSettings": {"path": t["path"], "mode": "stream-one"}}
        stream["security"] = "none"
        inbounds.append({
            "tag": inbound_tag(name), "listen": f"{sock},0666", "protocol": "vless",
            "settings": {"clients": clients, "decryption": "none"},
            "streamSettings": stream,
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True},
        })
    dns = node.get("dns") or {}
    servers = dns.get("servers") or ["https+local://1.1.1.1/dns-query", "https+local://8.8.8.8/dns-query", "localhost"]
    return {
        "log": {"loglevel": "warning", "access": "none"},
        "api": {"tag": "api", "services": ["HandlerService", "StatsService"]},
        "stats": {},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True, "handshake": 8,
                             "connIdle": 300, "uplinkOnly": 2, "downlinkOnly": 5}},
            "system": {"statsInboundUplink": False, "statsInboundDownlink": False},
        },
        # DNS داخلی: خروجی‌ها از resolver خودِ xray (DoH + کش) استفاده می‌کنند و به DNS سرور/ISP نشت نمی‌کنند
        "dns": {"servers": servers, "queryStrategy": "UseIPv4", "disableCache": False, "tag": "dns-int"},
        "inbounds": inbounds,
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4"}},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": [
            {"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"},
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "block"},
            {"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"},
        ]},
    }


_xray_stamp = {"v": None}


def xray_start_stamp():
    """زمان (monotonic) آخرین استارت xray؛ برای تشخیص ریستارت بیرونی (کرش/reboot/دستی).
    کاربرانی که با `api adu` اضافه شده‌اند فقط در حافظه‌ی xray هستند و با ریستارت از بین می‌روند."""
    try:
        rc, out, _ = runner.run(["systemctl", "show", "xray", "-p", "ActiveEnterTimestampMonotonic", "--value"])
    except Exception:  # noqa: BLE001
        return None
    out = (out or "").strip()
    return out if rc == 0 and out.isdigit() else None


def rewrite_xray(node: dict, users: dict) -> None:
    cfg = render_xray_config(node, users)
    # پسوند باید .json باشد وگرنه xray فرمت فایل را تشخیص نمی‌دهد (Failed to get format)
    base, ext = os.path.splitext(XRAY_CONFIG)
    tmp = base + ".new" + (ext or ".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    rc, out, err = runner.run([XRAY_BIN, "run", "-test", "-config", tmp])
    if rc != 0:
        os.remove(tmp)
        raise RuntimeError("xray config test failed: " + (err or out)[:300])
    os.replace(tmp, XRAY_CONFIG)
    runner.run(["systemctl", "restart", "xray"], timeout=30)
    # config کامل نوشته شد: همه‌ی کاربران قابل‌استفاده الان داخل xray هستند
    for u in users.values():
        u["_in_xray"] = is_usable(u)
    _xray_stamp["v"] = xray_start_stamp()


# ───────────────────────── منطق کاربر ─────────────────────────

def is_usable(u: dict) -> bool:
    if not u.get("enabled", True):
        return False
    limit = int(u.get("limit_bytes") or 0)
    if limit and int(u.get("used_bytes") or 0) >= limit:
        return False
    exp = int(u.get("expire_ts") or 0)
    if exp and exp < time.time():
        return False
    return True


def user_status(u: dict) -> str:
    limit = int(u.get("limit_bytes") or 0)
    exp = int(u.get("expire_ts") or 0)
    if limit and int(u.get("used_bytes") or 0) >= limit:
        return "limited"
    if exp and exp < time.time():
        return "expired"
    return "active" if u.get("enabled", True) else "disabled"


def build_links(node: dict, user: dict, name: str) -> list:
    domain = node["domain"]
    port = int(node.get("port", 443))
    fp = node.get("fingerprint", "chrome")
    sni = node.get("sni") or domain
    host = node.get("host") or domain
    links = []
    for t in active_transports(node):
        tn = t["name"]
        q = {"encryption": "none", "security": "tls", "sni": sni, "fp": fp}
        if tn == "ws":
            q.update({"type": "ws", "host": host, "path": t["path"], "alpn": "http/1.1"})
        elif tn == "httpupgrade":
            q.update({"type": "httpupgrade", "host": host, "path": t["path"], "alpn": "http/1.1"})
        elif tn == "grpc":
            q.update({"type": "grpc", "serviceName": t["service"], "mode": "gun", "authority": host, "alpn": "h2"})
        elif tn == "xhttp":
            # stream-one: یک درخواست POST واحد (نه packet-up)
            q.update({"type": "xhttp", "host": host, "path": t["path"], "mode": "stream-one", "alpn": "h2"})
        qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in q.items())
        tag = quote(f"{node.get('title', 'Stealth')}-{tn}-{name}", safe="")
        links.append(f"vless://{user['uuid']}@{domain}:{port}?{qs}#{tag}")
    return links


def sub_url(node: dict, user: dict) -> str:
    return f"https://{node['domain']}:{int(node.get('port', 443))}/{node['sub_path']}/{user['sub_token']}".replace(":443/", "/")


def _public(name: str, u: dict, node: dict) -> dict:
    return {
        "username": name, "uuid": u["uuid"], "subscription_url": sub_url(node, u),
        "used_bytes": int(u.get("used_bytes") or 0), "data_limit_bytes": int(u.get("limit_bytes") or 0),
        "expire_ts": int(u.get("expire_ts") or 0), "status": user_status(u),
    }


def _sync_user_to_xray(name: str, u: dict, node: dict, users: dict) -> bool:
    """بعد از تغییر وضعیت: کاربر را روی xray بساز یا بردار. اگر API نشد، config را کامل بازنویسی کن.

    نتیجه‌ی واقعی در u["_in_xray"] ذخیره می‌شود (روی دیسک هم). اگر کاربر قابل‌استفاده باشد ولی
    اضافه‌شدنش شکست بخورد، _in_xray=False می‌ماند و poller هر ۳۰ ثانیه دوباره تلاش می‌کند؛
    قبلاً این وضعیت ذخیره نمی‌شد و کاربر برای همیشه در users.json می‌ماند بدون اینکه روی xray باشد."""
    xray_remove_user(name, node)
    usable = is_usable(u)
    if not usable:
        u["_in_xray"] = False
        ok = True
    else:
        ok = xray_add_user(name, u, node)
        if not ok:
            try:
                rewrite_xray(node, users)  # در صورت موفقیت _in_xray همه True می‌شود
                ok = True
            except Exception as exc:  # noqa: BLE001
                print(f"xray sync failed for {name}: {exc}", file=sys.stderr, flush=True)
        u["_in_xray"] = bool(ok)
    _save_users(users)
    return ok


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def op_create(body: dict) -> dict:
    name = str(body.get("username") or "")
    if not USERNAME_RE.match(name):
        raise ApiError(400, "invalid username")
    node = load_node()
    with _lock:
        users = _load_users()
        if name in users:
            raise ApiError(409, "username exists")
        days = int(body.get("duration_days") or 0)
        first_use = bool(body.get("start_on_first_use")) and days > 0
        u = {
            "uuid": str(uuidlib.uuid4()), "sub_token": secrets.token_urlsafe(18),
            "limit_bytes": int(float(body.get("volume_gb") or 0) * GB), "used_bytes": 0,
            "expire_ts": 0 if (first_use or not days) else int(time.time()) + days * 86400,
            "pending_days": days if first_use else 0,
            "enabled": True, "created": int(time.time()),
        }
        users[name] = u
        _save_users(users)
        _sync_user_to_xray(name, u, node, users)
        return _public(name, u, node)


def _get(users: dict, name: str) -> dict:
    if name not in users:
        raise ApiError(404, "user not found")
    return users[name]


def op_update(name: str, body: dict) -> dict:
    node = load_node()
    with _lock:
        users = _load_users()
        u = _get(users, name)
        add_gb = float(body.get("add_volume_gb") or 0)
        add_days = int(body.get("add_days") or 0)
        reset = bool(body.get("reset_usage"))
        preserve = bool(body.get("preserve_remaining"))
        used = int(u.get("used_bytes") or 0)
        cur = int(u.get("limit_bytes") or 0)
        if body.get("unlimited_volume"):
            u["limit_bytes"] = 0
        elif reset and preserve:
            u["limit_bytes"] = max(cur - used, 0) + int(add_gb * GB)
        elif add_gb:
            u["limit_bytes"] = int(add_gb * GB) if reset else cur + int(add_gb * GB)
        if reset:
            u["used_bytes"] = 0
        if add_days:
            u["expire_ts"] = max(int(u.get("expire_ts") or 0), int(time.time())) + add_days * 86400
            u["pending_days"] = 0
        u["enabled"] = True
        _save_users(users)
        _sync_user_to_xray(name, u, node, users)
        return _public(name, u, node)


def op_delete(name: str) -> dict:
    node = load_node()
    with _lock:
        users = _load_users()
        if name not in users:
            return {"deleted": False}
        xray_remove_user(name, node)
        del users[name]
        _save_users(users)
        return {"deleted": True}


def op_revoke(name: str) -> dict:
    node = load_node()
    with _lock:
        users = _load_users()
        u = _get(users, name)
        xray_remove_user(name, node)  # با UUID قدیمی
        u["uuid"] = str(uuidlib.uuid4())
        u["sub_token"] = secrets.token_urlsafe(18)
        _save_users(users)
        _sync_user_to_xray(name, u, node, users)
        return _public(name, u, node)


def op_set_enabled(name: str, enabled: bool) -> dict:
    node = load_node()
    with _lock:
        users = _load_users()
        u = _get(users, name)
        u["enabled"] = bool(enabled)
        _save_users(users)
        _sync_user_to_xray(name, u, node, users)
        return _public(name, u, node)


def op_set_limit(name: str, limit_bytes: int, reenable: bool) -> dict:
    node = load_node()
    with _lock:
        users = _load_users()
        u = _get(users, name)
        u["limit_bytes"] = max(int(limit_bytes), 0)
        if reenable:
            u["enabled"] = True
        _save_users(users)
        _sync_user_to_xray(name, u, node, users)
        return _public(name, u, node)


def op_rename(name: str, new_name: str) -> dict:
    if not USERNAME_RE.match(new_name):
        raise ApiError(400, "invalid username")
    node = load_node()
    with _lock:
        users = _load_users()
        u = _get(users, name)
        if new_name in users:
            raise ApiError(409, "username exists")
        xray_remove_user(name, node)
        users[new_name] = users.pop(name)
        _save_users(users)
        _sync_user_to_xray(new_name, users[new_name], node, users)
        return _public(new_name, users[new_name], node)


def op_online(name: str) -> dict:
    with _lock:
        _get(_load_users(), name)
    rc, out, _ = runner.run([XRAY_BIN, "api", "statsonlineiplist", f"--server={XRAY_API}", f"-email={name}"])
    online = False
    if rc == 0:
        try:
            online = bool((json.loads(out or "{}").get("ips") or {}))
        except ValueError:
            online = False
    return {"online": online}


# ───────────────────────── شمارش مصرف ─────────────────────────

def poll_usage_once() -> None:
    """مصرف را از xray می‌خواند (با reset تا فقط دلتا بیاید) و به کاربران اضافه می‌کند؛
    سپس کاربرانی که حجم/زمانشان تمام شده را از xray برمی‌دارد."""
    node = load_node()
    cur = xray_start_stamp()
    if cur:
        if _xray_stamp["v"] and cur != _xray_stamp["v"]:
            # xray بیرون از ایجنت ریستارت شده: کاربرهای runtime از بین رفته‌اند، config را دوباره از users.json بساز
            try:
                with _lock:
                    users0 = _load_users()
                    rewrite_xray(node, users0)
                    _save_users(users0)
            except Exception as exc:  # noqa: BLE001
                print("resync after xray restart failed:", exc, file=sys.stderr, flush=True)
        elif not _xray_stamp["v"]:
            _xray_stamp["v"] = cur
    rc, out, _ = runner.run([XRAY_BIN, "api", "statsquery", f"--server={XRAY_API}", "-pattern", "user>>>", "-reset"])
    delta = {}
    if rc == 0 and out.strip():
        try:
            for st in json.loads(out).get("stat") or []:
                parts = (st.get("name") or "").split(">>>")
                if len(parts) == 4 and parts[0] == "user":
                    delta[parts[1]] = delta.get(parts[1], 0) + int(st.get("value") or 0)
        except ValueError:
            pass
    with _lock:
        users = _load_users()
        changed = False
        for name, u in users.items():
            d = delta.get(name, 0)
            if d:
                u["used_bytes"] = int(u.get("used_bytes") or 0) + d
                changed = True
                if u.get("pending_days"):  # شروع انقضا از اولین مصرف
                    u["expire_ts"] = int(time.time()) + int(u["pending_days"]) * 86400
                    u["pending_days"] = 0
            was_in = u.get("_in_xray", True)
            usable = is_usable(u)
            if was_in and not usable:
                xray_remove_user(name, node)
                u["_in_xray"] = False
                changed = True
            elif not was_in and usable:
                _sync_user_to_xray(name, u, node, users)  # _in_xray را خودش درست می‌کند؛ شکست = تلاش دوباره در دور بعد
                changed = True
        if changed:
            _save_users(users)


def poller_loop(interval=30):
    while True:
        try:
            poll_usage_once()
        except Exception as exc:  # noqa: BLE001
            print("poll error:", exc, file=sys.stderr, flush=True)
        time.sleep(interval)


# ───────────────────────── HTTP ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "nginx"
    sys_version = ""

    def log_message(self, *a):  # بدون لاگ دسترسی
        pass

    def _send(self, code, payload, ctype="application/json", extra=None):
        data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _auth(self, node) -> bool:
        got = self.headers.get("Authorization", "")
        return got.startswith("Bearer ") and hmac.compare_digest(got[7:].strip(), node["api_token"])

    def _route(self, method):
        node = load_node()
        path = urlsplit(self.path).path
        api_prefix = "/" + node["api_path"].strip("/") + "/"
        sub_prefix = "/" + node["sub_path"].strip("/") + "/"
        body = {}
        if method in ("POST", "PATCH", "PUT"):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                raise ApiError(413, "too large")
            if n:
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    raise ApiError(400, "bad json")

        if path.startswith(sub_prefix) and method == "GET":
            token = path[len(sub_prefix):].strip("/")
            with _lock:
                users = _load_users()
            for name, u in users.items():
                if hmac.compare_digest(u["sub_token"], token):
                    links = build_links(node, u, name) if is_usable(u) else []
                    exp = int(u.get("expire_ts") or 0)
                    info = f"upload=0; download={int(u.get('used_bytes') or 0)}; total={int(u.get('limit_bytes') or 0)}; expire={exp}"
                    return self._send(200, base64.b64encode("\n".join(links).encode()), "text/plain; charset=utf-8",
                                      {"subscription-userinfo": info, "profile-update-interval": "12",
                                       "profile-title": "base64:" + base64.b64encode(node.get("title", "Stealth").encode()).decode()})
            raise ApiError(404, "not found")

        if not path.startswith(api_prefix):
            raise ApiError(404, "not found")
        if not self._auth(node):
            raise ApiError(404, "not found")  # مثل مسیر ناموجود رفتار کن
        parts = [p for p in path[len(api_prefix):].split("/") if p]

        if parts == ["health"] and method == "GET":
            return self._send(200, {"ok": True, "version": VERSION,
                                    "transports": [t["name"] for t in active_transports(node)]})
        if parts == ["settings"] and method == "GET":
            return self._send(200, {
                "domain": node.get("domain", ""), "port": int(node.get("port", 443)),
                "title": node.get("title", "Stealth"), "fingerprint": node.get("fingerprint", "chrome"),
                "sni": node.get("sni") or node.get("domain", ""), "host": node.get("host") or node.get("domain", ""),
                "transports": [t["name"] for t in active_transports(node)],
            })
        if parts == ["settings"] and method == "PATCH":
            title = str(body.get("title", node.get("title", "Stealth"))).strip()[:40]
            fingerprint = str(body.get("fingerprint", node.get("fingerprint", "chrome"))).strip().lower()
            sni = str(body.get("sni", node.get("sni") or node.get("domain", ""))).strip()
            host = str(body.get("host", node.get("host") or node.get("domain", ""))).strip()
            if not re.fullmatch(r"[A-Za-z0-9 _.-]{1,40}", title):
                raise ApiError(400, "invalid title")
            if fingerprint not in {"chrome", "firefox", "safari", "random", "randomized"}:
                raise ApiError(400, "invalid fingerprint")
            if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", sni) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
                raise ApiError(400, "invalid host or SNI")
            with _lock:
                node["title"], node["fingerprint"], node["sni"], node["host"] = title, fingerprint, sni, host
                tmp = NODE_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(node, f, ensure_ascii=False, indent=1)
                os.chmod(tmp, 0o600)
                os.replace(tmp, NODE_FILE)
            return self._send(200, {"ok": True, "settings": {
                "title": title, "fingerprint": fingerprint, "sni": sni, "host": host,
                "domain": node.get("domain", ""), "port": int(node.get("port", 443)),
                "transports": [t["name"] for t in active_transports(node)],
            }})
        if parts == ["users"] and method == "POST":
            return self._send(200, op_create(body))
        if len(parts) >= 2 and parts[0] == "users":
            name = parts[1]
            rest = parts[2:]
            if not rest and method == "GET":
                with _lock:
                    return self._send(200, _public(name, _get(_load_users(), name), node))
            if not rest and method == "DELETE":
                return self._send(200, op_delete(name))
            if not rest and method == "PATCH":
                return self._send(200, op_update(name, body))
            if rest == ["revoke"] and method == "POST":
                return self._send(200, op_revoke(name))
            if rest == ["enabled"] and method == "POST":
                return self._send(200, op_set_enabled(name, bool(body.get("enabled"))))
            if rest == ["limit"] and method == "POST":
                return self._send(200, op_set_limit(name, int(body.get("limit_bytes") or 0), bool(body.get("reenable"))))
            if rest == ["rename"] and method == "POST":
                return self._send(200, op_rename(name, str(body.get("new_username") or "")))
            if rest == ["online"] and method == "GET":
                return self._send(200, op_online(name))
        raise ApiError(404, "not found")

    def _handle(self, method):
        try:
            self._route(method)
        except ApiError as e:
            self._send(e.code, {"error": e.msg})
        except Exception as exc:  # noqa: BLE001
            print("error:", exc, file=sys.stderr, flush=True)
            self._send(500, {"error": "internal"})

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PATCH(self): self._handle("PATCH")
    def do_DELETE(self): self._handle("DELETE")


def main():
    node = load_node()
    # در شروع، config xray را با کاربران فعلی هم‌گام کن
    # اگر هم‌گام‌سازی شکست بخورد، API نباید بمیرد (وگرنه nginx خطای 502 می‌دهد)
    try:
        with _lock:
            users0 = _load_users()
            try:
                rewrite_xray(node, users0)
            except Exception:
                for u in users0.values():  # poller دوباره تلاش می‌کند
                    u["_in_xray"] = False
                raise
            finally:
                _save_users(users0)
    except Exception as exc:  # noqa: BLE001
        print("startup xray sync failed:", exc, file=sys.stderr, flush=True)
    threading.Thread(target=poller_loop, daemon=True).start()
    port = int(node.get("agent_port", 10086))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
