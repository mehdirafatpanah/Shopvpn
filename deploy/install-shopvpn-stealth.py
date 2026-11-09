#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نصاب نود VLESS «استیلث» برای ShopVPN (Debian/Ubuntu، با root).

ساختار: کلاینت ──TLS──> (کلادفلر، اختیاری) ──> nginx:443 ──┬─ مسیر مخفی WS/HTTPUpgrade/gRPC/xhttp → xray (VLESS-only)
                                                          ├─ مسیر مخفی API/Sub                  → ایجنت ShopVPN
                                                          └─ هر چیز دیگر                       → سایت جعلی (فیلم یا reverse-proxy)

استفاده (نمونه):
  python3 install-shopvpn-stealth.py --domain cdn.example.com --decoy movie
  python3 install-shopvpn-stealth.py --domain cdn.example.com --decoy proxy --proxy-url https://www.example.org
  python3 install-shopvpn-stealth.py --domain cdn.example.com --cert file --cert-file fullchain.pem --key-file key.pem

بدون آرگومان (در ترمینال) سؤال‌های لازم را می‌پرسد.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF_DIR = Path("/etc/shopvpn-stealth")
AGENT_DST = Path("/opt/shopvpn-stealth/agent.py")
WEB_ROOT = Path("/var/www/shopvpn-decoy")
NGINX_SITE = Path("/etc/nginx/conf.d/shopvpn-stealth.conf")
CERT_DIR = Path("/etc/shopvpn-stealth/tls")
ALL_TRANSPORTS = ("ws", "httpupgrade", "grpc", "xhttp")
DEFAULT_TRANSPORTS = ("ws", "httpupgrade", "grpc")
CF_PORTS = {443, 2053, 2083, 2087, 2096, 8443}


def rnd(n=6):
    return secrets.token_hex(n)


# ───────────────────────── تولید داده/کانفیگ (قابل تست بدون root) ─────────────────────────

def build_node(domain, port, transports, title, dns_servers=None, fingerprint="chrome"):
    """node.json: همه‌ی مسیرهای مخفی تصادفی و واقع‌نما هستند (شبیه مسیر API یک سایت واقعی)."""
    seg = ["api", "v2", "v3", "media", "stream", "player", "assets", "cdn", "content", "live"]
    def realistic_path():
        return "/%s/%s/%s" % (secrets.choice(seg), secrets.choice(seg), rnd(5))
    node = {
        "domain": domain, "port": port, "title": title, "fingerprint": fingerprint,
        "agent_port": 10086,
        "api_path": "%s-%s" % (secrets.choice(["status", "health", "metrics", "internal"]), rnd(8)),
        "sub_path": "%s-%s" % (secrets.choice(["feed", "list", "playlist", "channel"]), rnd(6)),
        "api_token": secrets.token_urlsafe(32),
        "dns": {"servers": dns_servers} if dns_servers else {},
        "transports": [],
    }
    for t in transports:
        entry = {"name": t, "enabled": True, "socket": f"/run/xray/{t}.sock"}
        if t == "grpc":
            entry["service"] = "%s.%s" % (secrets.choice(["media", "stream", "sync", "feed"]), rnd(5))
        else:
            entry["path"] = realistic_path()
        node["transports"].append(entry)
    return node


def render_nginx(node, decoy_mode, proxy_url=None, cert=None, key=None, http2_directive=True):
    """config nginx با routing بر اساس مسیر. cert/key مسیر فایل‌های TLS هستند."""
    port = int(node["port"])
    d = node["domain"]
    loc = []
    for t in node["transports"]:
        if not t.get("enabled", True):
            continue
        sock = t["socket"]
        if t["name"] in ("ws", "httpupgrade"):
            loc.append(f"""
    location {t['path']} {{
        if ($http_upgrade != "websocket") {{ return 404; }}
        proxy_redirect off;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
        proxy_pass http://unix:{sock};
    }}""")
        elif t["name"] == "grpc":
            loc.append(f"""
    location /{t['service']}/ {{
        if ($content_type !~ "^application/grpc") {{ return 404; }}
        client_max_body_size 0;
        client_body_timeout 1h;
        grpc_read_timeout 1h;
        grpc_send_timeout 1h;
        grpc_socket_keepalive on;
        grpc_pass grpc://unix:{sock};
    }}""")
        elif t["name"] == "xhttp":
            loc.append(f"""
    location {t['path']} {{
        client_max_body_size 0;
        client_body_timeout 1h;
        grpc_read_timeout 1h;
        grpc_send_timeout 1h;
        grpc_set_header Host $host;
        grpc_pass grpc://unix:{sock};
    }}""")
    agent = f"http://127.0.0.1:{node['agent_port']}"
    loc.append(f"""
    location /{node['api_path']}/ {{
        proxy_pass {agent};
        proxy_set_header Host $host;
        proxy_read_timeout 60s;
    }}
    location /{node['sub_path']}/ {{
        proxy_pass {agent};
        proxy_set_header Host $host;
    }}""")

    if decoy_mode == "proxy":
        u = re.match(r"https?://([^/]+)", proxy_url).group(1)
        fallback = f"""
    location / {{
        proxy_pass {proxy_url.rstrip('/')};
        proxy_ssl_server_name on;
        proxy_set_header Host {u};
        proxy_set_header Accept-Encoding "";
        proxy_redirect ~^https?://{re.escape(u)}(.*)$ https://$host$1;
        proxy_connect_timeout 10s;
    }}"""
    else:
        fallback = f"""
    root {WEB_ROOT};
    index index.html;
    error_page 404 /404.html;
    location / {{
        try_files $uri $uri/ =404;
    }}"""
    h2 = "http2 on;" if http2_directive else ""
    listen_flag = "ssl" if http2_directive else "ssl http2"
    return f"""# ShopVPN Stealth — تولید خودکار؛ دستی ویرایش نکنید
server_tokens off;

server {{
    listen 80;
    listen [::]:80;
    server_name {d};
    location /.well-known/acme-challenge/ {{ root /var/www/html; }}
    location / {{ return 301 https://$host$request_uri; }}
}}

server {{
    listen {port} {listen_flag};
    listen [::]:{port} {listen_flag};
    {h2}
    server_name {d};

    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_prefer_server_ciphers off;

    access_log off;
    error_log /var/log/nginx/shopvpn-stealth.error.log crit;
    gzip on;
    gzip_types text/css application/javascript text/plain application/json;
{''.join(loc)}
{fallback}
}}
"""


MOVIES = [
    ("Midnight Harbor", "Thriller", "2024", "#1f2a44,#6a3d7c"), ("Paper Lanterns", "Drama", "2023", "#3d2c2c,#c9783b"),
    ("The Last Orbit", "Sci-Fi", "2025", "#0b2239,#2f7f9d"), ("Echoes of Summer", "Romance", "2022", "#4a2c4a,#e48a8a"),
    ("Iron Meridian", "Action", "2024", "#222,#8a2b2b"), ("Quiet Valley", "Mystery", "2023", "#1b3b2f,#7fa37a"),
    ("Glass Kingdom", "Fantasy", "2025", "#2d2a55,#5f8fd9"), ("Neon Alley", "Crime", "2021", "#150b2e,#d94f9a"),
    ("Salt & Wind", "Adventure", "2024", "#2a3b4a,#d9b45f"), ("Blue Hour", "Drama", "2022", "#10253d,#4d7ea8"),
    ("Hollow Crown", "Historical", "2023", "#38281c,#a77b4a"), ("Starlight Diner", "Comedy", "2025", "#3a1f4a,#f0b24a"),
]


def render_decoy(root: Path, site_name="CineVault"):
    """سایت جعلی «تماشای فیلم» چندصفحه‌ای — فقط محتوای ساختگی/اصیل؛ بدون پوستر یا نام واقعی."""
    root.mkdir(parents=True, exist_ok=True)
    css = """*{box-sizing:border-box}body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#0e0f13;color:#e8e8ee}
a{color:inherit;text-decoration:none}header{display:flex;align-items:center;gap:24px;padding:14px 28px;background:#14161c;position:sticky;top:0}
.logo{font-weight:800;font-size:20px;color:#ff5a5f}nav a{margin-right:18px;color:#b9bcc8}nav a:hover{color:#fff}
.hero{padding:56px 28px;background:linear-gradient(120deg,#1d2030,#2b1f3a)}.hero h1{margin:0 0 10px;font-size:38px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:18px;padding:28px}
.card .poster{aspect-ratio:2/3;border-radius:10px;display:flex;align-items:flex-end;padding:12px;font-weight:700}
.card small{display:block;color:#9aa0b0;margin-top:6px}h2{padding:0 28px;margin:24px 0 0}
.player{margin:28px;aspect-ratio:16/9;background:#000;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#777}
footer{padding:28px;color:#6d7284;border-top:1px solid #1d2028;margin-top:30px;font-size:13px}.btn{display:inline-block;background:#ff5a5f;color:#fff;padding:10px 18px;border-radius:8px;margin-top:12px}"""
    def page(title, body):
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · {site_name}</title><link rel="stylesheet" href="/style.css"></head><body>
<header><a class="logo" href="/">{site_name}</a><nav><a href="/">Home</a><a href="/browse.html">Browse</a><a href="/watch.html">Now playing</a><a href="/about.html">About</a></nav></header>
{body}<footer>© 2025 {site_name}. All titles shown are fictional placeholders. <a href="/about.html">About</a> · <a href="/contact.html">Contact</a></footer></body></html>"""
    cards = "".join(
        f'<a class="card" href="/watch.html"><div class="poster" style="background:linear-gradient(160deg,{c})">{t}</div><small>{g} · {y}</small></a>'
        for t, g, y, c in MOVIES)
    (root / "index.html").write_text(page("Home", f'<div class="hero"><h1>Stream stories you will love</h1><p>New releases every week.</p><a class="btn" href="/browse.html">Start watching</a></div><h2>Trending now</h2><div class="grid">{cards[:len(cards)//2]}</div><h2>Recently added</h2><div class="grid">{cards[len(cards)//2:]}</div>'), "utf-8")
    (root / "browse.html").write_text(page("Browse", f'<h2>All titles</h2><div class="grid">{cards}</div>'), "utf-8")
    (root / "watch.html").write_text(page("Now playing", '<div class="player">Loading player…</div><h2>Midnight Harbor</h2><p style="padding:0 28px;color:#9aa0b0">A retired detective returns to the harbor town where an old case was never closed.</p>'), "utf-8")
    (root / "about.html").write_text(page("About", '<div class="hero"><h1>About us</h1><p>We curate independent films and series for curious viewers.</p></div>'), "utf-8")
    (root / "contact.html").write_text(page("Contact", '<div class="hero"><h1>Contact</h1><p>support@example.com</p></div>'), "utf-8")
    (root / "404.html").write_text(page("Not found", '<div class="hero"><h1>404</h1><p>The page you are looking for does not exist.</p><a class="btn" href="/">Back home</a></div>'), "utf-8")
    (root / "style.css").write_text(css, "utf-8")
    (root / "robots.txt").write_text("User-agent: *\nAllow: /\n", "utf-8")


def xray_dropin() -> str:
    return "[Service]\nRuntimeDirectory=xray\nRuntimeDirectoryMode=0755\nRuntimeDirectoryPreserve=yes\n"


AGENT_UNIT = """[Unit]
Description=ShopVPN Stealth Agent
After=network-online.target xray.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/shopvpn-stealth/agent.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
"""


# ───────────────────────── اجرا روی سرور ─────────────────────────

def sh(cmd, check=True, **kw):
    print("+", cmd if isinstance(cmd, str) else " ".join(cmd), flush=True)
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=check, **kw)


def ask(prompt, default=None, choices=None):
    if not sys.stdin.isatty():
        return default
    hint = f" [{default}]" if default else ""
    while True:
        v = input(f"{prompt}{hint}: ").strip() or (default or "")
        if v and (not choices or v in choices):
            return v


def nginx_supports_http2_directive() -> bool:
    out = subprocess.run(["nginx", "-v"], capture_output=True, text=True)
    m = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", out.stderr + out.stdout)
    return bool(m) and tuple(map(int, m.groups())) >= (1, 25, 1)


def obtain_cert(args):
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert, key = CERT_DIR / "fullchain.pem", CERT_DIR / "privkey.pem"
    if args.cert == "file":
        shutil.copy(args.cert_file, cert)
        shutil.copy(args.key_file, key)
    elif args.cert == "self":
        sh(["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "3650", "-keyout", str(key),
            "-out", str(cert), "-subj", f"/CN={args.domain}", "-addext", f"subjectAltName=DNS:{args.domain}"])
        print("⚠️ گواهی خودامضا: در کلادفلر حالت SSL را روی Full (نه Strict) بگذارید.")
    else:
        sh("systemctl stop nginx", check=False)
        sh(["certbot", "certonly", "--standalone", "-d", args.domain, "-m", args.email, "--agree-tos", "-n"])
        live = Path("/etc/letsencrypt/live") / args.domain
        cert, key = live / "fullchain.pem", live / "privkey.pem"
        Path("/etc/letsencrypt/renewal-hooks/deploy").mkdir(parents=True, exist_ok=True)
        Path("/etc/letsencrypt/renewal-hooks/deploy/shopvpn-nginx.sh").write_text("#!/bin/sh\nsystemctl reload nginx\n")
        os.chmod("/etc/letsencrypt/renewal-hooks/deploy/shopvpn-nginx.sh", 0o755)
    key.chmod(0o600) if key.parent == CERT_DIR else None
    return str(cert), str(key)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--domain")
    ap.add_argument("--port", type=int, default=443, help="پورت عمومی (برای کلادفلر یکی از 443/2053/2083/2087/2096/8443)")
    ap.add_argument("--transports", default=",".join(DEFAULT_TRANSPORTS), help="ws,httpupgrade,grpc,xhttp (xhttp فقط stream-one)")
    ap.add_argument("--decoy", choices=("movie", "proxy"))
    ap.add_argument("--proxy-url", help="برای --decoy proxy: مثلاً https://www.example.org")
    ap.add_argument("--site-name", default="CineVault")
    ap.add_argument("--cert", choices=("letsencrypt", "file", "self"))
    ap.add_argument("--cert-file")
    ap.add_argument("--key-file")
    ap.add_argument("--email", default="")
    ap.add_argument("--title", default="Stealth")
    ap.add_argument("--dns", default="", help="سرورهای DNS داخلی xray با کاما (پیش‌فرض: DoH کلودفلر+گوگل)")
    ap.add_argument("--fingerprint", default="chrome")
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("باید با root اجرا شود.")
    args.domain = args.domain or ask("دامنه‌ی نود (باید رکورد DNS آن به این سرور/کلادفلر اشاره کند)")
    args.decoy = args.decoy or ask("سایت جعلی؟ movie (سایت فیلم ساختگی) یا proxy (آینه‌ی یک سایت واقعی)", "movie", ("movie", "proxy"))
    if args.decoy == "proxy":
        args.proxy_url = args.proxy_url or ask("آدرس سایت واقعی برای آینه (https://...)")
        if not args.proxy_url or not re.match(r"^https?://[^/\s]+", args.proxy_url):
            sys.exit("--proxy-url نامعتبر است.")
    args.cert = args.cert or ask("گواهی TLS؟ letsencrypt / file / self", "letsencrypt", ("letsencrypt", "file", "self"))
    if args.cert == "letsencrypt" and not args.email:
        args.email = ask("ایمیل برای Let's Encrypt")
    if args.cert == "file" and not (args.cert_file and args.key_file):
        sys.exit("--cert-file و --key-file لازم است.")
    transports = [t.strip() for t in args.transports.split(",") if t.strip()]
    if not args.domain or any(t not in ALL_TRANSPORTS for t in transports) or not transports:
        sys.exit("دامنه یا --transports نامعتبر است.")
    if args.port not in CF_PORTS:
        print(f"⚠️ پورت {args.port} را کلادفلر پروکسی نمی‌کند (فقط {sorted(CF_PORTS)}).")

    sh("apt-get update -y")
    sh("DEBIAN_FRONTEND=noninteractive apt-get install -y nginx python3 curl openssl ca-certificates"
       + (" certbot" if args.cert == "letsencrypt" else ""))
    if not Path("/usr/local/bin/xray").exists():
        sh('bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install')
    Path("/etc/systemd/system/xray.service.d").mkdir(parents=True, exist_ok=True)
    Path("/etc/systemd/system/xray.service.d/10-shopvpn.conf").write_text(xray_dropin())

    CONF_DIR.mkdir(parents=True, exist_ok=True)
    node = build_node(args.domain, args.port, transports, args.title,
                      [s.strip() for s in args.dns.split(",") if s.strip()] or None, args.fingerprint)
    (CONF_DIR / "node.json").write_text(json.dumps(node, indent=1))
    os.chmod(CONF_DIR / "node.json", 0o600)

    cert, key = obtain_cert(args)
    if args.decoy == "movie":
        render_decoy(WEB_ROOT, args.site_name)
    default_site = Path("/etc/nginx/sites-enabled/default")
    if default_site.exists():
        default_site.unlink()
    NGINX_SITE.write_text(render_nginx(node, args.decoy, args.proxy_url, cert, key, nginx_supports_http2_directive()))
    sh("nginx -t")

    AGENT_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "shopvpn-stealth-agent.py", AGENT_DST)
    Path("/etc/systemd/system/shopvpn-stealth-agent.service").write_text(AGENT_UNIT)
    sh("systemctl daemon-reload")
    sh("systemctl enable --now xray shopvpn-stealth-agent")
    sh("systemctl enable --now nginx")
    sh("systemctl restart xray shopvpn-stealth-agent nginx")
    if shutil.which("ufw") and "active" in subprocess.run(["ufw", "status"], capture_output=True, text=True).stdout:
        sh(f"ufw allow 80/tcp && ufw allow {args.port}/tcp", check=False)

    api_url = f"https://{args.domain}{'' if args.port == 443 else ':%d' % args.port}/{node['api_path']}"
    print("\n" + "=" * 60)
    print("✅ نصب کامل شد. در بات: پنل‌های VPN ← افزودن سرور ← نوع «Stealth VLESS»")
    print(f"   آدرس API : {api_url}")
    print(f"   توکن     : {node['api_token']}")
    print("ترنسپورت‌های فعال:", ", ".join(transports))
    print("""
کلادفلر: رکورد DNS دامنه را Proxied (ابر نارنجی) بگذارید؛ SSL/TLS = Full (strict اگر گواهی معتبر دارید)؛
WebSockets روشن؛ برای gRPC/xhttp در Network گزینه‌ی gRPC را روشن کنید.
نکته: xhttp فقط حالت stream-one (یک POST واحد) تولید می‌شود، نه packet-up.""")


if __name__ == "__main__":
    main()
