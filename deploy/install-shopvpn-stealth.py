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
    'Create a polished, responsive fictional streaming-catalog decoy site.'
    root.mkdir(parents=True, exist_ok=True)
    css = r'''/* CineVault — self-contained responsive decoy website */
:root{color-scheme:dark;--bg:#090d16;--panel:#111827;--panel2:#172235;--line:#263349;--muted:#9aa9bd;--text:#f4f7fb;--accent:#f2b84b;--accent2:#f28b50;--radius:18px;--max:1240px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.55}a{color:inherit;text-decoration:none}button,input{font:inherit}button{cursor:pointer}.shell{width:min(var(--max),calc(100% - 48px));margin:auto}.topline{height:3px;background:linear-gradient(90deg,#f2b84b,#f28b50,#8b79e8)}
header{position:sticky;top:0;z-index:20;background:rgba(9,13,22,.88);backdrop-filter:blur(18px);border-bottom:1px solid rgba(255,255,255,.07)}.nav{height:76px;display:flex;align-items:center;gap:34px}.brand{display:flex;align-items:center;gap:11px;font-size:21px;font-weight:850;letter-spacing:-.7px;white-space:nowrap}.brand-mark{width:36px;height:36px;border-radius:12px;background:linear-gradient(145deg,#f4c45d,#e87942);display:grid;place-items:center;color:#151923;box-shadow:0 7px 24px #e8794233}.brand-mark svg{width:19px}.navlinks{display:flex;align-items:center;gap:25px;color:#aeb9c9;font-size:14px}.navlinks a:hover,.navlinks a.active{color:#fff}.navright{margin-left:auto;display:flex;align-items:center;gap:12px}.searchbox{height:42px;width:210px;border:1px solid var(--line);border-radius:12px;display:flex;align-items:center;padding:0 12px;gap:8px;background:#101827}.searchbox input{min-width:0;width:100%;border:0;outline:0;background:transparent;color:#fff;font-size:13px}.iconbtn,.menu-btn{width:42px;height:42px;border:1px solid var(--line);border-radius:12px;background:#101827;color:#e8edf5;display:grid;place-items:center}.menu-btn{display:none}.mobile-links{display:none;padding:0 0 18px}.mobile-links.open{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.mobile-links a{padding:10px 12px;border-radius:10px;background:#111827;color:#c4cedc;font-size:14px}
.eyebrow{display:inline-flex;align-items:center;gap:8px;color:var(--accent);font-size:11px;font-weight:800;letter-spacing:1.8px;text-transform:uppercase}.eyebrow:before{content:"";width:20px;height:1px;background:currentColor}.hero{position:relative;overflow:hidden;min-height:500px;margin:28px auto 0;border:1px solid #35415a;border-radius:26px;background:radial-gradient(ellipse at 78% 48%,#79512f77,transparent 34%),radial-gradient(ellipse at 72% 80%,#403b7777,transparent 38%),linear-gradient(115deg,#17243a 0%,#182033 44%,#271f31 100%);display:flex;align-items:center}.hero:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,#111a2a 0%,#111a2aee 35%,transparent 75%),url("data:image/svg+xml,%3Csvg width='100' height='100' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.12'/%3E%3C/svg%3E");opacity:.8}.hero-art{position:absolute;right:7%;top:9%;width:37%;height:82%;border-radius:22px;background:linear-gradient(155deg,#e7a65a,#9c4c4b 43%,#252e59 44%,#121c31);box-shadow:0 35px 90px #0008;transform:rotate(3deg);overflow:hidden}.hero-art:before{content:"";position:absolute;inset:0;background:radial-gradient(ellipse at 50% 28%,#ffe0a6aa,transparent 28%),linear-gradient(0deg,#080c18 2%,transparent 72%)}.hero-art:after{content:"CINEVAULT";position:absolute;bottom:28px;left:25px;font-size:clamp(20px,3vw,40px);font-weight:950;letter-spacing:5px;color:#fff;text-shadow:0 4px 18px #000}.hero-copy{position:relative;z-index:1;max-width:590px;padding:66px 58px}.hero h1{font-size:clamp(38px,5.5vw,66px);line-height:1.02;letter-spacing:-2.6px;margin:17px 0 18px}.hero p{max-width:480px;color:#bdc7d6;font-size:15px}.meta{display:flex;flex-wrap:wrap;align-items:center;gap:12px;color:#c3ccda;font-size:12px;margin:22px 0}.meta span+span:before{content:"•";margin-right:12px;color:#75849a}.rating{color:#ffd06a}.actions{display:flex;flex-wrap:wrap;gap:11px;margin-top:27px}.btn{border:1px solid transparent;border-radius:12px;padding:12px 19px;display:inline-flex;align-items:center;justify-content:center;gap:9px;font-size:13px;font-weight:750;transition:.2s}.btn-primary{background:linear-gradient(135deg,#f4c45d,#e98b4d);color:#171923;box-shadow:0 8px 24px #e98b4d33}.btn-primary:hover{transform:translateY(-2px);filter:brightness(1.07)}.btn-ghost{background:#ffffff0d;border-color:#ffffff2b;color:#f5f7fb}.btn-ghost:hover{background:#ffffff19}
.section{padding:48px 0 8px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:20px}.section-head h2{font-size:24px;letter-spacing:-.7px;margin:0}.section-head p{margin:5px 0 0;color:var(--muted);font-size:13px}.textlink{color:var(--accent);font-size:13px;font-weight:700}.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:18px}.card{min-width:0;position:relative}.poster{position:relative;aspect-ratio:2/2.75;border-radius:15px;overflow:hidden;background:var(--poster,linear-gradient(145deg,#34445d,#171c2b));box-shadow:0 12px 32px #0003;transition:transform .25s,box-shadow .25s}.poster:before{content:"";position:absolute;inset:0;background:radial-gradient(ellipse at 50% 28%,#ffffff42,transparent 34%),linear-gradient(0deg,#080c18e8,transparent 58%)}.poster:after{content:attr(data-mark);position:absolute;left:12px;bottom:12px;font-size:clamp(20px,2.5vw,34px);font-weight:950;letter-spacing:-1.5px;color:#ffffffd9;text-shadow:0 2px 14px #0008}.card:hover .poster{transform:translateY(-5px);box-shadow:0 18px 40px #0008}.poster-tag{position:absolute;top:11px;left:11px;z-index:1;padding:5px 8px;border-radius:7px;background:#0a0e18b8;color:#f6d38a;font-size:10px;font-weight:800;letter-spacing:.6px}.fav{position:absolute;right:10px;top:10px;z-index:2;width:33px;height:33px;border:1px solid #ffffff44;border-radius:50%;background:#080c1880;color:white;display:grid;place-items:center}.fav.saved{color:#ff8e9b;background:#3b1724}.card-info{padding:11px 2px}.card-title{font-size:14px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.card-sub{display:flex;justify-content:space-between;gap:6px;color:var(--muted);font-size:11px;margin-top:4px}.card-sub .stars{color:#f5c96d}.filters{display:flex;flex-wrap:wrap;gap:9px;margin:24px 0}.chip{border:1px solid var(--line);border-radius:99px;padding:8px 15px;background:#101827;color:#aeb9c9;font-size:12px}.chip.active,.chip:hover{background:#f1bc55;color:#1a1b20;border-color:#f1bc55;font-weight:750}.catalog-tools{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}.sort{background:#101827;border:1px solid var(--line);border-radius:10px;padding:9px 12px;color:#dce3ed}.empty{grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--muted);background:#101827;border:1px dashed var(--line);border-radius:16px}
.promo{margin:55px 0 10px;padding:34px 38px;border:1px solid #39445a;border-radius:20px;background:linear-gradient(110deg,#192a40,#22233b 65%,#3a2940);display:flex;align-items:center;justify-content:space-between;gap:20px}.promo h2{font-size:24px;margin:0 0 6px}.promo p{margin:0;color:#b8c3d2;font-size:13px}.promo .btn{white-space:nowrap}.page-hero{padding:55px 0 22px}.page-hero h1{font-size:clamp(34px,5vw,52px);letter-spacing:-1.8px;margin:12px 0 8px}.page-hero p{color:var(--muted);max-width:650px;margin:0}.player-wrap{padding:30px 0 0}.video{position:relative;aspect-ratio:16/8.5;min-height:280px;border:1px solid #35415a;border-radius:20px;overflow:hidden;background:radial-gradient(ellipse at 50% 40%,#3a4964,#111827 58%,#080b12);display:grid;place-items:center}.video:before{content:"";position:absolute;inset:0;background:linear-gradient(0deg,#070a11aa,transparent 55%),repeating-linear-gradient(135deg,transparent 0 30px,#ffffff04 30px 31px)}.play{position:relative;z-index:1;width:76px;height:76px;border:1px solid #ffffff70;border-radius:50%;background:#f4c45ddd;color:#111827;font-size:26px;display:grid;place-items:center;box-shadow:0 0 0 12px #ffffff10}.video-label{position:absolute;bottom:18px;left:20px;color:#aeb9c9;font-size:12px}.video-controls{position:absolute;bottom:16px;right:18px;display:flex;gap:8px}.video-controls button{border:1px solid #ffffff33;border-radius:8px;padding:7px 10px;background:#090d16aa;color:#fff;font-size:11px}.watch-layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:32px;padding:25px 0}.watch-title{font-size:27px;margin:0}.muted{color:var(--muted)}.side-panel{padding:18px;border:1px solid var(--line);border-radius:16px;background:#101827;height:max-content}.side-panel h3{margin:0 0 13px;font-size:15px}.episode{padding:11px 0;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;font-size:12px;color:#c5cfdd}.episode span:last-child{color:var(--muted)}.about-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin:28px 0}.feature{padding:22px;border:1px solid var(--line);border-radius:16px;background:#101827}.feature b{display:block;margin:12px 0 5px}.feature p{font-size:13px;color:var(--muted);margin:0}.contact-card{max-width:680px;padding:28px;border:1px solid var(--line);border-radius:18px;background:#101827;margin:28px 0}.contact-row{padding:13px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:15px;font-size:13px}.contact-row:last-child{border:0}.footer{margin-top:70px;border-top:1px solid #202b3c;background:#0b111d;padding:34px 0 25px}.footer-top{display:flex;justify-content:space-between;gap:30px;flex-wrap:wrap}.footer-brand{max-width:330px}.footer-brand p,.footer-col a{font-size:12px;color:#8796aa}.footer-col{display:grid;gap:9px;align-content:start}.footer-col b{font-size:12px;margin-bottom:4px}.footer-bottom{border-top:1px solid #202b3c;margin-top:25px;padding-top:18px;color:#718198;font-size:11px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.toast{position:fixed;bottom:22px;left:50%;transform:translate(-50%,20px);opacity:0;pointer-events:none;background:#f3c45e;color:#161922;padding:11px 17px;border-radius:11px;font-size:12px;font-weight:750;z-index:60;transition:.25s}.toast.show{opacity:1;transform:translate(-50%,0)}
@media(max-width:1000px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}.hero-art{right:3%;width:40%}.hero-copy{padding:55px 40px;max-width:540px}.watch-layout{grid-template-columns:minmax(0,1fr) 260px}}
@media(max-width:760px){.shell{width:min(100% - 30px,var(--max))}.nav{height:66px;gap:14px}.navlinks{display:none}.menu-btn{display:grid}.searchbox{width:42px;padding:0 11px}.searchbox input{display:none}.navright{gap:8px}.hero{min-height:570px;margin-top:15px;align-items:end}.hero:before{background:linear-gradient(0deg,#111a2af7 0%,#111a2ac9 48%,transparent 100%)}.hero-art{width:58%;height:56%;top:5%;right:20%;opacity:.82}.hero-copy{padding:250px 25px 32px}.hero h1{font-size:43px}.hero p{font-size:13px}.section{padding-top:38px}.section-head h2{font-size:21px}.grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}.card-title{font-size:12px}.card-sub{font-size:10px}.promo{padding:25px;align-items:flex-start;flex-direction:column}.watch-layout{grid-template-columns:1fr}.about-grid{grid-template-columns:1fr}.video{min-height:220px}.footer-top{gap:25px}}
@media(max-width:460px){.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.hero h1{font-size:38px}.hero-art{width:68%;right:16%}.hero-copy{padding-top:240px}.meta{gap:8px}.meta span+span:before{margin-right:8px}.page-hero{padding-top:38px}.page-hero h1{font-size:36px}}
'''
    titles = [
        ("Midnight Harbor", "Thriller", "2024", "8.7", "#233b58,#b66b51", "MH", "A quiet coastal town hides a mystery that refuses to stay buried."),
        ("Paper Lanterns", "Drama", "2023", "8.2", "#633f38,#e1a36b", "PL", "Two strangers find an unexpected connection over one long summer."),
        ("The Last Orbit", "Sci-Fi", "2025", "9.1", "#102e49,#4f9eb5", "LO", "A lone pilot receives a signal from beyond the edge of known space."),
        ("Echoes of Summer", "Romance", "2022", "7.9", "#633b59,#e79c9e", "ES", "A forgotten photograph brings an old story back to life."),
        ("Iron Meridian", "Action", "2024", "8.4", "#382c35,#bd6251", "IM", "One decision puts an entire city on a collision course."),
        ("Quiet Valley", "Mystery", "2023", "8.5", "#21473c,#a5b78a", "QV", "A new arrival uncovers the secrets of a secluded valley."),
        ("Glass Kingdom", "Fantasy", "2025", "8.9", "#34305f,#78a6d7", "GK", "An ancient map leads to a kingdom thought to be a myth."),
        ("Neon Alley", "Crime", "2021", "8.1", "#2d1747,#d75d9b", "NA", "A detective follows a trail through the city's midnight streets."),
        ("Salt & Wind", "Adventure", "2024", "7.8", "#304a5a,#d6b46b", "SW", "A journey across the open sea becomes a test of courage."),
        ("Blue Hour", "Drama", "2022", "8.0", "#173b5b,#6e9ac0", "BH", "Three lives intersect during the final hour before dawn."),
        ("Hollow Crown", "Historical", "2023", "8.6", "#493522,#c19a63", "HC", "A young heir must choose between power and a fragile peace."),
        ("Starlight Diner", "Comedy", "2025", "7.7", "#512b50,#f1b95e", "SD", "The night shift at a small diner is never quite ordinary."),
        ("Northbound", "Adventure", "2024", "8.3", "#244d56,#b5c7a2", "NB", "A long road north brings a family closer to the truth."),
        ("The Silent Frame", "Thriller", "2025", "8.8", "#263044,#a1a9c7", "SF", "A photojournalist notices one detail nobody else can see."),
        ("Golden Lines", "Drama", "2021", "7.9", "#66452c,#e7b36b", "GL", "An architect returns home to restore a landmark theatre."),
    ]
    import json as _json
    data_json = _json.dumps([{"title":t,"genre":g,"year":y,"rating":r,"colors":c,"mark":m,"description":d} for t,g,y,r,c,m,d in titles], ensure_ascii=False)
    common_head = '''<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#090d16"><meta name="description" content="Discover stories, films and new releases on CineVault."><link rel="stylesheet" href="/style.css"><link rel="icon" href="/favicon.svg" type="image/svg+xml">'''
    def page(title, body, active=""):
        links = [("Home","/","home"),("Browse","/browse.html","browse"),("Collections","/browse.html#collections","collections"),("About","/about.html","about")]
        nav = "".join(f'<a class="{"active" if active==k else ""}" href="{u}">{n}</a>' for n,u,k in links)
        return f'''<!doctype html><html lang="en"><head>{common_head}<title>{title} · {site_name}</title></head><body><div class="topline"></div><header><div class="shell nav"><a class="brand" href="/"><span class="brand-mark"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.8c0-.8.9-1.3 1.6-.9l11 6.2a1 1 0 0 1 0 1.8l-11 6.2A1 1 0 0 1 7 17.2V4.8Z"/></svg></span>{site_name}</a><nav class="navlinks">{nav}</nav><div class="navright"><label class="searchbox"><span>⌕</span><input id="globalSearch" type="search" placeholder="Search titles…" aria-label="Search titles"></label><button class="iconbtn" id="watchlistBtn" aria-label="Watchlist">♡</button><button class="menu-btn" id="menuBtn" aria-label="Open menu">☰</button></div></div><div class="shell mobile-links" id="mobileLinks">{nav}<a href="/contact.html">Contact</a></div></header>{body}<footer class="footer"><div class="shell"><div class="footer-top"><div class="footer-brand"><a class="brand" href="/"><span class="brand-mark">▶</span>{site_name}</a><p>Thoughtful stories, memorable characters and fresh discoveries. Find your next favourite title.</p></div><div class="footer-col"><b>Explore</b><a href="/browse.html">All titles</a><a href="/browse.html#collections">Collections</a><a href="/watch.html">Featured title</a></div><div class="footer-col"><b>Company</b><a href="/about.html">About us</a><a href="/contact.html">Contact</a><a href="/about.html#faq">Help centre</a></div><div class="footer-col"><b>Information</b><a href="/about.html#terms">Terms of use</a><a href="/about.html#privacy">Privacy</a></div></div><div class="footer-bottom"><span>© 2025 {site_name}. All rights reserved.</span><span>Made for curious viewers · English edition</span></div></div></footer><div class="toast" id="toast" role="status"></div><script>window.CINE_TITLES={data_json};</script><script src="/app.js" defer></script></body></html>'''
    home = '''<main class="shell"><section class="hero"><div class="hero-art" aria-hidden="true"></div><div class="hero-copy"><span class="eyebrow">Editor's choice · Featured story</span><h1>Stories worth<br>staying up for.</h1><p>Discover remarkable films, hidden gems and fresh perspectives — all in one carefully curated collection.</p><div class="meta"><span>2025</span><span>Science Fiction</span><span>2h 08m</span><span class="rating">★ 9.1</span></div><div class="actions"><a class="btn btn-primary" href="/watch.html">▶ &nbsp;Explore featured title</a><a class="btn btn-ghost" href="/browse.html">Browse collection &nbsp;→</a></div></div></section><section class="section"><div class="section-head"><div><span class="eyebrow">Handpicked for you</span><h2>Trending this week</h2><p>The titles everyone is talking about.</p></div><a class="textlink" href="/browse.html">View all titles →</a></div><div class="grid" id="trendingGrid"></div></section><section class="section"><div class="section-head"><div><span class="eyebrow">Find your next favourite</span><h2>Explore by genre</h2><p>A good story comes in many forms.</p></div></div><div class="filters" id="homeGenres"><a class="chip" href="/browse.html?genre=Drama">Drama</a><a class="chip" href="/browse.html?genre=Thriller">Thriller</a><a class="chip" href="/browse.html?genre=Sci-Fi">Sci-Fi</a><a class="chip" href="/browse.html?genre=Adventure">Adventure</a><a class="chip" href="/browse.html?genre=Comedy">Comedy</a><a class="chip" href="/browse.html?genre=Mystery">Mystery</a></div></section><section class="promo"><div><span class="eyebrow">A world of stories</span><h2>There is always something new to discover.</h2><p>Explore the full collection and find a story that stays with you.</p></div><a class="btn btn-primary" href="/browse.html">Explore all titles →</a></section></main>'''
    browse = '''<main class="shell"><section class="page-hero"><span class="eyebrow">The CineVault collection</span><h1>Explore all titles.</h1><p>Browse the collection, discover new genres and find something worth watching tonight.</p></section><div class="catalog-tools"><div class="filters" id="genreFilters"><button class="chip active" data-genre="All">All titles</button><button class="chip" data-genre="Drama">Drama</button><button class="chip" data-genre="Thriller">Thriller</button><button class="chip" data-genre="Sci-Fi">Sci-Fi</button><button class="chip" data-genre="Action">Action</button><button class="chip" data-genre="Mystery">Mystery</button><button class="chip" data-genre="Adventure">Adventure</button><button class="chip" data-genre="Romance">Romance</button><button class="chip" data-genre="Comedy">Comedy</button></div><select class="sort" id="sortTitles" aria-label="Sort titles"><option value="featured">Featured</option><option value="rating">Top rated</option><option value="newest">Newest first</option><option value="az">A to Z</option></select></div><div class="section" style="padding-top:8px"><div class="section-head"><div><h2 id="catalogHeading">All titles</h2><p id="resultCount">15 titles in the collection</p></div></div><div class="grid" id="catalogGrid"></div></div></main>'''
    watch = '''<main class="shell"><section class="player-wrap"><div class="video" id="videoPlayer"><button class="play" id="playBtn" aria-label="Play preview">▶</button><span class="video-label">CineVault preview · Featured selection</span><div class="video-controls"><button id="captionsBtn">CC</button><button id="qualityBtn">HD ▾</button><button id="fullscreenBtn">⛶</button></div></div></section><div class="watch-layout"><section><span class="eyebrow">Featured selection</span><h1 class="watch-title">Midnight Harbor</h1><div class="meta"><span>2024</span><span>Thriller</span><span>2h 08m</span><span class="rating">★ 8.7</span></div><p class="muted">A quiet coastal town hides a mystery that refuses to stay buried. When a familiar face returns after many years, the secrets beneath the harbour begin to surface.</p><div class="actions"><button class="btn btn-primary" id="watchSave">♡ &nbsp;Add to watchlist</button><a class="btn btn-ghost" href="/browse.html">← Back to collection</a></div><section class="section"><h2>About this title</h2><p class="muted">A carefully crafted story about memory, belonging and the things we leave unsaid. Set against a dramatic coastal landscape, this selection blends atmospheric cinematography with an intimate mystery.</p></section></section><aside class="side-panel"><h3>More to discover</h3><div id="relatedTitles"></div></aside></div></main>'''
    about = '''<main class="shell"><section class="page-hero"><span class="eyebrow">Our story</span><h1>Stories bring us closer.</h1><p>CineVault is a curated destination for people who love thoughtful storytelling, distinctive worlds and films that leave a lasting impression.</p></section><div class="about-grid"><article class="feature"><span class="eyebrow">01 · Curated</span><b>Quality over quantity</b><p>We believe the best collections are thoughtfully selected, easy to explore and always evolving.</p></article><article class="feature"><span class="eyebrow">02 · Discover</span><b>Something unexpected</b><p>From familiar favourites to overlooked gems, there is always a new story around the corner.</p></article><article class="feature"><span class="eyebrow">03 · Enjoy</span><b>Made for everyone</b><p>A simple, welcoming place to find stories across genres, moods and generations.</p></article></div><section class="section" id="faq"><span class="eyebrow">Good to know</span><h2>Frequently asked questions</h2><div class="contact-card"><b>What can I find here?</b><p class="muted">A curated catalogue of fictional film and series titles across a range of genres.</p><hr style="border:0;border-top:1px solid var(--line)"><b>How often is the collection updated?</b><p class="muted">The collection is refreshed regularly with new selections and featured stories.</p></div></section></main>'''
    contact = '''<main class="shell"><section class="page-hero"><span class="eyebrow">Get in touch</span><h1>We would love to hear from you.</h1><p>Have a question, suggestion or feedback about the collection? Find the right contact below.</p></section><section class="contact-card"><h2 style="margin-top:0">Contact information</h2><div class="contact-row"><span class="muted">General enquiries</span><b>hello@example.com</b></div><div class="contact-row"><span class="muted">Support</span><b>support@example.com</b></div><div class="contact-row"><span class="muted">Response hours</span><b>Monday – Friday · 09:00–17:00</b></div><p class="muted" style="font-size:12px;margin-bottom:0">For general information, please include a short description of your enquiry.</p></section></main>'''
    notfound = '''<main class="shell"><section class="page-hero" style="padding:100px 0;text-align:center"><span class="eyebrow">Error 404</span><h1>Looks like this story ends here.</h1><p style="margin:0 auto">The page you are looking for could not be found. Let's get you back to something good.</p><div class="actions" style="justify-content:center"><a class="btn btn-primary" href="/">Return home</a><a class="btn btn-ghost" href="/browse.html">Browse titles</a></div></section></main>'''
    (root / "index.html").write_text(page("Discover", home, "home"), "utf-8")
    (root / "browse.html").write_text(page("Browse titles", browse, "browse"), "utf-8")
    (root / "watch.html").write_text(page("Featured title", watch, ""), "utf-8")
    (root / "about.html").write_text(page("About us", about, "about"), "utf-8")
    (root / "contact.html").write_text(page("Contact", contact, ""), "utf-8")
    (root / "404.html").write_text(page("Page not found", notfound, ""), "utf-8")
    (root / "style.css").write_text(css, "utf-8")
    js = r'''(()=>{
const titles=window.CINE_TITLES||[],$=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)],savedKey='cinevault-watchlist';
const saved=()=>{try{return JSON.parse(localStorage.getItem(savedKey)||'[]')}catch(e){return[]}},store=a=>localStorage.setItem(savedKey,JSON.stringify(a));
const toast=msg=>{const el=$('#toast');if(!el)return;el.textContent=msg;el.classList.add('show');clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>el.classList.remove('show'),2200)};
const poster=(t)=>`linear-gradient(145deg,${t.colors})`;
function card(t){const isSaved=saved().includes(t.title);return `<article class="card"><a href="/watch.html" aria-label="Explore ${t.title}"><div class="poster" style="--poster:${poster(t)}" data-mark="${t.mark}"><span class="poster-tag">${t.genre.toUpperCase()}</span></div></a><button class="fav ${isSaved?'saved':''}" data-fav="${t.title}" aria-label="${isSaved?'Remove from':'Add to'} watchlist">${isSaved?'♥':'♡'}</button><div class="card-info"><div class="card-title">${t.title}</div><div class="card-sub"><span>${t.year} · ${t.genre}</span><span class="stars">★ ${t.rating}</span></div></div></article>`}
function bindFav(){ $$('[data-fav]').forEach(b=>b.addEventListener('click',()=>{let a=saved(),n=b.dataset.fav;if(a.includes(n)){a=a.filter(x=>x!==n);toast('Removed from your watchlist')}else{a.push(n);toast('Added to your watchlist')}store(a);b.classList.toggle('saved',a.includes(n));b.textContent=a.includes(n)?'♥':'♡'})) }
const trending=$('#trendingGrid');if(trending){trending.innerHTML=titles.slice(0,5).map(card).join('');bindFav()}
const grid=$('#catalogGrid');if(grid){let genre=new URLSearchParams(location.search).get('genre')||'All',sort='featured';function render(){let list=titles.filter(t=>genre==='All'||t.genre===genre);if(sort==='rating')list.sort((a,b)=>+b.rating- +a.rating);if(sort==='newest')list.sort((a,b)=>+b.year- +a.year);if(sort==='az')list.sort((a,b)=>a.title.localeCompare(b.title));grid.innerHTML=list.length?list.map(card).join(''):'<div class="empty">No titles found in this category. Try another genre.</div>';$('#catalogHeading').textContent=genre==='All'?'All titles':genre;$('#resultCount').textContent=`${list.length} title${list.length===1?'':'s'} in the collection`;$$('[data-genre]').forEach(b=>b.classList.toggle('active',b.dataset.genre===genre));bindFav()}render();$$('[data-genre]').forEach(b=>b.addEventListener('click',()=>{genre=b.dataset.genre;render()}));$('#sortTitles')?.addEventListener('change',e=>{sort=e.target.value;render()})}
const related=$('#relatedTitles');if(related)related.innerHTML=titles.slice(1,5).map(t=>`<a class="episode" href="/watch.html"><span>${t.title}</span><span>★ ${t.rating}</span></a>`).join('');
const saveBtn=$('#watchSave');if(saveBtn){const update=()=>{saveBtn.innerHTML=saved().includes('Midnight Harbor')?'♥ &nbsp;In your watchlist':'♡ &nbsp;Add to watchlist'};update();saveBtn.addEventListener('click',()=>{let a=saved();a=a.includes('Midnight Harbor')?a.filter(x=>x!=='Midnight Harbor'):[...a,'Midnight Harbor'];store(a);update();toast(a.includes('Midnight Harbor')?'Added to your watchlist':'Removed from your watchlist')})}
$('#playBtn')?.addEventListener('click',e=>{e.currentTarget.textContent=e.currentTarget.textContent==='▶'?'Ⅱ':'▶';toast('Preview player')});$('#captionsBtn')?.addEventListener('click',()=>toast('No captions available for this preview'));$('#qualityBtn')?.addEventListener('click',()=>toast('Preview quality: HD'));$('#fullscreenBtn')?.addEventListener('click',()=>toast('Preview mode'));
$('#menuBtn')?.addEventListener('click',()=>$('#mobileLinks')?.classList.toggle('open'));$('#watchlistBtn')?.addEventListener('click',()=>{const a=saved();toast(a.length?`Your watchlist has ${a.length} title${a.length===1?'':'s'}`:'Your watchlist is empty')});
$('#globalSearch')?.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.value.trim())location.href='/browse.html?q='+encodeURIComponent(e.target.value.trim())});const q=new URLSearchParams(location.search).get('q');if(q&&grid){const inp=$('#globalSearch');if(inp)inp.value=q;const filtered=titles.filter(t=>(t.title+' '+t.genre).toLowerCase().includes(q.toLowerCase()));grid.innerHTML=filtered.length?filtered.map(card).join(''):'<div class="empty">No titles match your search.</div>';$('#catalogHeading').textContent='Search results';$('#resultCount').textContent=`${filtered.length} matching titles`;bindFav()}
})();'''
    (root / "app.js").write_text(js, "utf-8")
    (root / "robots.txt").write_text("User-agent: *\nAllow: /\n", "utf-8")
    (root / "favicon.svg").write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#f4c45d"/><stop offset="1" stop-color="#e87942"/></linearGradient></defs><rect width="64" height="64" rx="18" fill="url(#g)"/><path d="M24 17c-2 0-4 1.5-4 4v22c0 2.5 2 4 4 3l24-13c2-1 2-4 0-5L24 17Z" fill="#151923"/></svg>''', "utf-8")


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


def verify_agent(node):
    """بعد از نصب مطمئن می‌شود ایجنت واقعاً جواب می‌دهد؛ وگرنه علت را چاپ می‌کند و خارج می‌شود."""
    import time
    import urllib.request
    url = f"http://127.0.0.1:{node['agent_port']}/{node['api_path']}/health"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + node["api_token"]})
    for _ in range(20):
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1.5)
    print("❌ ایجنت ShopVPN بالا نیامد؛ لاگ سرویس:")
    subprocess.run("journalctl -u shopvpn-stealth-agent -n 25 --no-pager", shell=True)
    sys.exit("نصب ناقص ماند: ایجنت جواب نمی‌دهد (nginx خطای 502 می‌دهد).")


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
    ap.add_argument("--update-decoy-only", action="store_true", help="به‌روزرسانی سایت نمایشی بدون تغییر تنظیمات Xray، مسیرها یا کاربران")
    args = ap.parse_args()

    if args.update_decoy_only:
        if os.geteuid() != 0:
            sys.exit("برای به‌روزرسانی سایت باید با root اجرا شود.")
        if not WEB_ROOT.is_dir() or not NGINX_SITE.is_file():
            sys.exit("سایت نمایشی نصب‌شده پیدا نشد؛ ابتدا نصب نود را بررسی کنید.")
        if f"root {WEB_ROOT};" not in NGINX_SITE.read_text("utf-8", errors="ignore"):
            sys.exit("این نود از حالت سایت محلی استفاده نمی‌کند (احتمالاً decoy=proxy است)؛ تغییری اعمال نشد.")
        render_decoy(WEB_ROOT, args.site_name)
        sh("nginx -t && systemctl reload nginx")
        print("\n✅ سایت نمایشی CineVault به‌روزرسانی شد؛ تنظیمات Xray، مسیرها، کاربران و لینک‌های اشتراک دست‌نخورده ماندند.")
        return

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

    verify_agent(node)

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
