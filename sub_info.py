# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
دریافت اطلاعات زنده‌ی اشتراک (حجم مصرف‌شده/باقی‌مانده و تاریخ انقضا) مستقیماً از روی
لینک ساب کاربر — دقیقاً مثل کاری که اپ‌هایی نظیر v2Box یا v2rayNG انجام می‌دهند.

این ماژول به هیچ پنل خاصی (Marzban/X-UI/Marzneshin/Hiddify/...) وابسته نیست، چون
همه‌ی آن‌ها از یک قرارداد نانوشته‌ی مشترک پیروی می‌کنند: در پاسخ به یک درخواست GET
روی لینک ساب، هدرهای زیر را برمی‌گردانند:

  subscription-userinfo: upload=...; download=...; total=...; expire=...
  profile-title: <base64 یا متن ساده>
  profile-update-interval: <ساعت>
"""

import base64
import binascii
import html as html_lib
import json
import logging
import re
import urllib.parse
from datetime import datetime, timezone

import aiohttp

from jalali import to_jalali_str

_log = logging.getLogger("sub_info")

_TIMEOUT = aiohttp.ClientTimeout(total=10)

_CONFIG_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "ssr://", "hysteria://", "hysteria2://", "hy2://", "tuic://", "ssh://")

# بعضی پنل‌ها به‌جای متن خامِ base64، یک صفحه‌ی HTML («Subscription Information»)
# برمی‌گردانند که لینک‌های کانفیگ وسط تگ‌ها هستند نه ابتدای خط؛ این regex (عیناً
# مثل geo_scan._CONFIG_URI_RE) برای استخراج از وسط چنین متنی استفاده می‌شود.
_CONFIG_URI_RE = re.compile(r"(?:vmess|vless|trojan|hysteria2|hy2|hysteria|tuic|ssr|ss)://[^\s\"'<>]+")
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


# ------------------------------------------------------- فرمت JSON کامل ---
# بعضی پنل‌ها (تایید شده از لاگ واقعی production: user.coloner.ir:2053) به‌جای
# لیست لینک‌های vmess://... یک کانفیگ *کامل* Xray-core به فرمت JSON برمی‌گردانند
# (شامل کلیدهای سطح‌بالای log/policy/inbounds/outbounds و...). این فرمت هیچ
# رشته‌ی vless://... در خودش ندارد، پس هیچ regex/base64-decode‌ای نمی‌تواند
# «کانفیگ تکی» ازش دربیاورد؛ باید از روی فیلدهای outbounds[] یک لینک استاندارد‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# (قابل کپی/وارد کردن در v2rayNG و مشابه) از نو ساخت.
def _net_params_from_stream(stream: dict, host: str) -> dict:
    stream = stream or {}
    security = (stream.get("security") or "none").lower()
    network = (stream.get("network") or "tcp").lower()
    ws_path, ws_host, header_type = "/", host, "none"
    if network in ("ws", "httpupgrade", "h2"):
        key = {"ws": "wsSettings", "httpupgrade": "httpupgradeSettings", "h2": "httpSettings"}[network]
        settings = stream.get(key) or {}
        ws_path = settings.get("path") or "/"
        headers = settings.get("headers") or {}
        ws_host = headers.get("Host") or settings.get("host") or host
    elif network == "grpc":
        grpc_settings = stream.get("grpcSettings") or {}
        ws_path = grpc_settings.get("serviceName") or ""
    elif network == "tcp":
        header = (stream.get("tcpSettings") or {}).get("header") or {}
        header_type = (header.get("type") or "none").lower()
        if header_type == "http":
            request = header.get("request") or {}
            host_hdr = (request.get("headers") or {}).get("Host")
            if isinstance(host_hdr, list) and host_hdr:
                ws_host = host_hdr[0]
            path_hdr = request.get("path")
            if isinstance(path_hdr, list) and path_hdr:
                ws_path = path_hdr[0]

    sni = ws_host or host
    reality = {}
    tls_fingerprint = "chrome"
    if security == "tls":
        tls_settings = stream.get("tlsSettings") or {}
        sni = tls_settings.get("serverName") or sni
        # Fingerprint is a client-side uTLS setting. Some panel/export formats
        # persist it under tlsSettings; when it is absent, chrome is the
        # compatible default used by Xray clients.
        tls_fingerprint = tls_settings.get("fingerprint") or "chrome"
    elif security == "reality":
        rs = stream.get("realitySettings") or {}
        sni = rs.get("serverName") or sni
        reality = {
            "pbk": rs.get("publicKey") or "", "sid": rs.get("shortId") or "",
            "fp": rs.get("fingerprint") or "chrome", "spx": rs.get("spiderX") or "",
        }
    return {
        "security": security, "network": network, "sni": sni,
        "ws_path": ws_path, "ws_host": ws_host, "header_type": header_type,
        "tls_fingerprint": tls_fingerprint, "reality": reality,
    }


def _vmess_uri(host, port, uuid_, remark, net: dict) -> str:
    payload = {
        "v": "2", "ps": remark or host, "add": host, "port": str(port),
        "id": uuid_, "aid": "0", "scy": "auto",
        "net": net["network"], "type": net.get("header_type", "none"),
        "host": net["ws_host"], "path": net["ws_path"],
        "tls": "tls" if net["security"] == "tls" else ("reality" if net["security"] == "reality" else ""),
        "sni": net["sni"],
    }
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"vmess://{encoded}"


def _vless_or_trojan_uri(scheme: str, host, port, auth, remark, net: dict) -> str:
    params = {"type": net["network"], "security": net["security"] or "none"}
    if scheme == "vless":
        params["encryption"] = "none"
    if net["security"] in ("tls", "reality"):
        params["sni"] = net["sni"]
        # Xray uTLS fingerprint applies to the client side of TLS too. Keep it
        # in the exported URI for VLESS/Trojan TLS configs, not only Reality.
        if net["security"] == "tls":
            params["fp"] = net.get("tls_fingerprint") or "chrome"
    if net["network"] in ("ws", "httpupgrade", "h2"):
        params["host"] = net["ws_host"]
        params["path"] = net["ws_path"]
    elif net["network"] == "grpc":
        params["serviceName"] = net["ws_path"]
    if net["security"] == "reality":
        r = net["reality"]
        params.update({"pbk": r["pbk"], "sid": r["sid"], "fp": r["fp"]})
        if r.get("spx"):
            params["spx"] = r["spx"]
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    frag = urllib.parse.quote(remark or host)
    return f"{scheme}://{urllib.parse.quote(str(auth), safe='')}@{host}:{port}?{query}#{frag}"


def _ss_uri(host, port, method, password, remark) -> str:
    creds = base64.b64encode(f"{method}:{password}".encode("utf-8")).decode("ascii").rstrip("=")
    frag = urllib.parse.quote(remark or host)
    return f"ss://{creds}@{host}:{port}#{frag}"


def _profile_remark(profile: dict):
    for key in ("remarks", "remark", "ps", "name", "title", "alias", "profile_title"):
        val = profile.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _xray_outbound_to_uri(ob: dict, profile_remark=None):
    protocol = (ob.get("protocol") or "").lower()
    settings = ob.get("settings") or {}
    tag = str(ob.get("tag") or "").strip()

    if protocol in ("vmess", "vless"):
        vnext = settings.get("vnext") or []
        if not vnext or not isinstance(vnext[0], dict):
            return None
        v = vnext[0]
        host = str(v.get("address") or "").strip()
        port = v.get("port")
        if not host or not port:
            return None
        users = v.get("users") or []
        user0 = users[0] if users and isinstance(users[0], dict) else {}
        uuid_ = user0.get("id")
        if not uuid_:
            return None
        email = user0.get("email") if isinstance(user0.get("email"), str) else None
        remark = (email or "").strip() or profile_remark or tag or host
        net = _net_params_from_stream(ob.get("streamSettings"), host)
        if protocol == "vmess":
            return _vmess_uri(host, port, uuid_, remark, net)
        return _vless_or_trojan_uri("vless", host, port, uuid_, remark, net)

    if protocol in ("trojan", "shadowsocks"):
        servers = settings.get("servers") or []
        if not servers or not isinstance(servers[0], dict):
            return None
        s = servers[0]
        host = str(s.get("address") or "").strip()
        port = s.get("port")
        if not host or not port:
            return None
        email = s.get("email") if isinstance(s.get("email"), str) else None
        remark = (email or "").strip() or profile_remark or tag or host
        if protocol == "trojan":
            password = s.get("password")
            if not password:
                return None
            net = _net_params_from_stream(ob.get("streamSettings"), host)
            return _vless_or_trojan_uri("trojan", host, port, password, remark, net)
        method = s.get("method")
        password = s.get("password")
        if not method or not password:
            return None
        return _ss_uri(host, port, method, password, remark)

    return None  # freedom/blackhole/dns و بقیه‌ی outboundهای غیر پروکسی


def _singbox_outbound_to_uri(ob: dict, profile_remark=None):
    otype = (ob.get("type") or "").lower()
    if otype not in ("vmess", "vless", "trojan", "shadowsocks"):
        return None
    host = str(ob.get("server") or "").strip()
    port = ob.get("server_port")
    if not host or not port:
        return None
    tag = str(ob.get("tag") or "").strip()
    remark = profile_remark or tag or host
    tls = ob.get("tls") or {}
    security = "tls" if tls.get("enabled") else ("reality" if (tls.get("reality") or {}).get("enabled") else "none")
    transport = ob.get("transport") or {}
    ttype = (transport.get("type") or "tcp").lower()
    net = {
        "security": security, "network": ttype,
        "sni": tls.get("server_name") or host,
        "ws_path": transport.get("path") or "/",
        "ws_host": (transport.get("headers") or {}).get("Host") or host,
        "header_type": "none", "reality": {},
    }
    if security == "reality":
        rs = tls.get("reality") or {}
        net["reality"] = {
            "pbk": rs.get("public_key") or "", "sid": rs.get("short_id") or "",
            "fp": (tls.get("utls") or {}).get("fingerprint") or "chrome", "spx": "",
        }
    if otype == "vmess":
        uuid_ = ob.get("uuid")
        if not uuid_:
            return None
        return _vmess_uri(host, port, uuid_, remark, net)
    if otype == "vless":
        uuid_ = ob.get("uuid")
        if not uuid_:
            return None
        return _vless_or_trojan_uri("vless", host, port, uuid_, remark, net)
    if otype == "trojan":
        password = ob.get("password")
        if not password:
            return None
        return _vless_or_trojan_uri("trojan", host, port, password, remark, net)
    if otype == "shadowsocks":
        method, password = ob.get("method"), ob.get("password")
        if not method or not password:
            return None
        return _ss_uri(host, port, method, password, remark)
    return None


def _full_json_configs_to_uris(text: str) -> list:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []

    if isinstance(data, dict):
        profiles = [data]
    elif isinstance(data, list):
        profiles = [p for p in data if isinstance(p, dict)]
    else:
        return []

    out = []
    for profile in profiles:
        outbounds = profile.get("outbounds")
        if not isinstance(outbounds, list):
            continue
        remark = _profile_remark(profile)
        for ob in outbounds:
            if not isinstance(ob, dict):
                continue
            uri = _xray_outbound_to_uri(ob, remark) if "protocol" in ob else _singbox_outbound_to_uri(ob, remark)
            if uri:
                out.append(uri)
    return out


def _session() -> aiohttp.ClientSession:
    """یک ClientSession با گواهی SSL غیرفعال می‌سازد.

    چرا لازم است: سرور Subscription پنل‌های 3X-UI تقریباً همیشه با گواهی
    self-signed یا روی http بالا می‌آید (دقیقاً همان دلیلی که در
    panel_providers/threexui_provider.py هم verify گواهی غیرفعال شده)؛ بدون
    این تنظیم، aiohttp با خطای SSL درخواست را رد می‌کند و fetch_individual_links/
    fetch_sub_info برای این پنل‌ها همیشه silent-fail می‌شوند (لیست خالی/ok=False)
    در حالی که خودِ لینک اشتراک در مرورگر یا اپ کاربر درست باز می‌شود. بقیه‌ی
    پنل‌ها (که معمولاً گواهی معتبر دارند) از این غیرفعال‌سازی آسیبی نمی‌بینند."""
    connector = aiohttp.TCPConnector(ssl=False)
    return aiohttp.ClientSession(connector=connector, timeout=_TIMEOUT)


def _b64_decode(value: str) -> str:
    """دیکد base64 برای متن اشتراک — دقیقاً هم‌منطق با geo_scan._b64_decode_text/
    parse_subscription_text: هم urlsafe base64 (-/_) رو پشتیبانی می‌کنه و هم اگر
    نتیجه‌ی دیکد شامل هیچ URI کانفیگی نبود (یعنی ورودی اصلاً base64 نبوده و
    b64decode با نادیده‌گرفتن کاراکترهای نامعتبر یه خروجی بی‌معنی ولی UTF-8-معتبر
    ساخته)، برمی‌گرده به متن خام به‌جای اینکه اون خروجی بی‌معنی رو قبول کنه."""
    try:
        padded = value.strip().replace("-", "+").replace("_", "/")
        padded += "=" * (-len(padded) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return value
    return decoded if decoded and "://" in decoded else value


async def fetch_individual_links(sub_url: str) -> list:
    """
    محتوای خودِ لینک اشتراک (subscription_url) را می‌گیرد و لیست کانفیگ‌های
    تکی داخلش (vless/vmess/trojan/ss/...) را برمی‌گرداند. مستقل از نوع پنل
    (Marzban/X-UI/Marzneshin/PasarGuard/Hiddify) کار می‌کند چون همه از یک
    فرمت مشترک (متن base64 شامل خطوط کانفیگ) پیروی می‌کنند.
    خروجی خالی یعنی یا چیزی پیدا نشد یا خطایی رخ داد؛ فراخوان باید silent
    fallback کند و فقط لینک اشتراک را نشان دهد.
    """
    try:
        async with _session() as session:
            async with session.get(sub_url, headers={"User-Agent": "v2rayNG/1.8.29"}) as resp:
                if resp.status != 200:
                    _log.warning("fetch_individual_links: HTTP %s برای %s", resp.status, sub_url)
                    return []
                raw = await resp.text()
    except Exception:
        _log.exception("fetch_individual_links: درخواست به %s ناموفق بود", sub_url)
        return []

    _log.info("fetch_individual_links: %d بایت خام دریافت شد از %s؛ نمونه: %r", len(raw), sub_url, raw[:200])

    # حالت ۱: خودِ متن خام، یک کانفیگ کامل Xray-core/sing-box به فرمت JSON است‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    # (نه لیست لینک) - این حالت اصلاً base64 نیست، پس باید قبل از تلاش برای
    # decode روی متن خام امتحان شود.
    json_uris = _full_json_configs_to_uris(raw.strip())
    if json_uris:
        return json_uris

    decoded = _b64_decode(raw.strip())

    # حالت ۲: خودِ محتوای base64-دیکدشده یک JSON کامل است (بعضی پنل‌ها حتی
    # این فرمت رو هم یه‌بار base64 می‌کنند).
    if decoded != raw.strip():
        json_uris = _full_json_configs_to_uris(decoded.strip())
        if json_uris:
            return json_uris

    lines = [ln.strip() for ln in decoded.splitlines() if ln.strip()]
    out = [ln for ln in lines if ln.startswith(_CONFIG_SCHEMES)]
    if out:
        return out

    # هیچ خطی مستقیماً با یکی از schemeها شروع نشد؛ احتمالاً پنل به‌جای متن
    # خام، یک صفحه‌ی HTML برگردانده که لینک‌ها وسط تگ‌ها هستند. با regex از
    # هر جای متن (حتی وسط HTML) استخراج می‌کنیم.
    out = [html_lib.unescape(m.group(0)) for m in _CONFIG_URI_RE.finditer(decoded)]
    if not out:
        _log.warning(
            "fetch_individual_links: هیچ کانفیگی از %s استخراج نشد؛ نمونه‌ی دیکدشده: %r",
            sub_url, decoded[:200],
        )
    return out


_pool_db = None


def _pool_override_sync(link: str):
    """اگر لینک ساب (آدرس پنل) متعلق به سرویس ترکیبی VPN+SSH باشد، مصرف/سقف/انقضای «استخر
    مشترک» را برمی‌گرداند (مصرف VPN+SSH روی هم، سقف اصلی بسته). پنل VPN فقط «باقی‌مانده‌ی
    مشترک» را به‌عنوان سقف می‌بیند (برای قطع لحظه‌ای)، و نباید آن عدد به کاربر نمایش داده شود.
    برای سرویس معمولی None برمی‌گردد."""
    global _pool_db
    try:
        import config
        import dedicated_sub
        from database import Database
        if _pool_db is None:
            _pool_db = Database(config.DB_PATH)
        base = str(link).split("#", 1)[0]
        with _pool_db._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM custom_configs WHERE subscription_url=? OR subscription_url=? ORDER BY id DESC LIMIT 1",
                (link, base.split("?", 1)[0]),
            ).fetchone()
        if not row:
            return None
        return dedicated_sub.quota_info_for_config(_pool_db, int(row["id"]), any_status=True)
    except Exception:
        _log.debug("pool override lookup failed", exc_info=True)
        return None


async def fetch_sub_info(link: str) -> dict:
    """فراخوانی اصلی؛ برای سرویس‌های ترکیبی VPN+SSH مصرف و سقف را از استخر مشترک می‌خواند."""
    import asyncio
    result = await _fetch_sub_info_raw(link)
    pool = await asyncio.to_thread(_pool_override_sync, link)
    if pool:
        base = result if result.get("ok") else {"ok": True, "title": None, "expire": None}
        result = dict(base)
        result.update({"ok": True, "upload": int(pool.get("upload") or 0), "download": int(pool.get("download") or 0),
                       "total": int(pool.get("total") or 0)})
        if pool.get("expire"):
            result["expire"] = int(pool["expire"])
    return result


async def _fetch_sub_info_raw(link: str) -> dict:
    """
    خروجی:
      {"ok": True, "upload": int, "download": int, "total": int,
       "expire": int|None, "title": str|None} در صورت موفقیت
      {"ok": False, "error": "..."} در صورت شکست
    """
    try:
        async with _session() as session:
            async with session.get(link, headers={"User-Agent": "v2rayNG/1.8.29"}) as resp:
                headers = resp.headers
                userinfo = headers.get("subscription-userinfo")
                if not userinfo:
                    return {"ok": False, "error": "no_userinfo_header"}

                data = dict(
                    p.strip().split("=", 1) for p in userinfo.split(";") if "=" in p
                )
                result = {
                    "ok": True,
                    "upload": int(data.get("upload", 0)),
                    "download": int(data.get("download", 0)),
                    "total": int(data.get("total", 0)),
                    "expire": int(data["expire"]) if data.get("expire") else None,
                    "title": None,
                }

                title = headers.get("profile-title")
                if title:
                    result["title"] = _b64_decode(title)

                return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def format_sub_info_fa(info: dict) -> str:
    """قالب‌بندی خروجی fetch_sub_info به یک متن فارسی کوتاه برای نمایش در بات."""
    if not info.get("ok"):
        return "⚠️ دریافت اطلاعات مصرف از سرور امکان‌پذیر نبود."

    used = int(info.get("upload") or 0) + int(info.get("download") or 0)
    total = int(info.get("total") or 0)

    def gb(n: int) -> str:
        return f"{n / (1024 ** 3):.2f}"

    lines = []
    if total > 0:
        remaining = max(0, total - used)
        percent = min(100, round(used / total * 100)) if total else 0
        lines.append(f"📊 مصرف: {gb(used)} از {gb(total)} گیگابایت ({percent}٪)")
        lines.append(f"📦 باقی‌مانده: {gb(remaining)} گیگابایت")
    else:
        lines.append(f"📊 مصرف: {gb(used)} گیگابایت (نامحدود)")

    if info.get("expire"):
        exp_dt = datetime.fromtimestamp(int(info["expire"]), tz=timezone.utc)
        days_left = (exp_dt - datetime.now(timezone.utc)).days
        lines.append(f"📅 انقضا: {to_jalali_str(exp_dt)} ({max(0, days_left)} روز مانده)")
    else:
        lines.append("📅 انقضا: نامحدود")

    return "\n".join(lines)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
