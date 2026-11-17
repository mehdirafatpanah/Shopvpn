# -*- coding: utf-8 -*-
"""One-time SSH bootstrap for an already-installed Doctor DNS panel.

SSH credentials are used only in memory for this operation.  Only the
restricted Doctor DNS admin API key is persisted in ShopVPN afterwards.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit


class DoctorDNSSetupError(Exception):
    pass


def _validate_host(host: str) -> str:
    host = str(host or "").strip()
    if not host or len(host) > 253 or any(c in host for c in " /\\\r\n\t"):
        raise DoctorDNSSetupError("آدرس سرور معتبر نیست.")
    # Accept IPv4, IPv6, or a DNS name. Brackets are stripped for IPv6.
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*", candidate):
            raise DoctorDNSSetupError("IP یا دامنه سرور معتبر نیست.")
    return candidate


def _remote_script(token: str, token_hash: str, allow_ip: str, name: str) -> str:
    # Values are JSON literals, not shell-interpolated SQL.
    values = json.dumps({"token_hash": token_hash, "allow_ip": allow_ip,
                         "name": name, "created_at": datetime.now(timezone.utc).isoformat()},
                        ensure_ascii=True)
    return r'''import json, os, sqlite3, sys, subprocess, tempfile, time
# The Bot API defaults to 8445. If an explicit override disabled or moved it,
# normalize it to the documented port and restart only the Doctor DNS panel service.
config = "/etc/smart-dns/panel.env"
if os.path.isfile(config):
    with open(config, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    found = False
    changed = False
    out = []
    for line in lines:
        if line.lstrip().startswith("BOT_API_PORT="):
            found = True
            if line.split("=", 1)[1].strip().strip("\"'") != "8445":
                line = "BOT_API_PORT=8445\n"
                changed = True
        out.append(line)
    if changed:
        fd, tmp = tempfile.mkstemp(prefix=".panel.env.", dir=os.path.dirname(config))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.writelines(out)
            os.chmod(tmp, 0o600)
            os.replace(tmp, config)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        subprocess.run(["systemctl", "restart", "smartdns-panel.service"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        time.sleep(2)
p = "/var/lib/smart-dns/panel.db"
if not os.path.isfile(p):
    raise SystemExit("Doctor DNS database not found")
con = sqlite3.connect(p, timeout=15)
con.row_factory = sqlite3.Row
cols = {r[1] for r in con.execute("PRAGMA table_info(api_tokens)")}
required = {"name", "token_hash", "allow_ips", "created_at", "revoked_at", "scope", "admin_id"}
if not required.issubset(cols):
    raise SystemExit("Doctor DNS API schema is outdated; update Doctor DNS first")
v = json.loads(''' + repr(values) + r''')
# Replace only the prior key created by this integration, never other API keys.
con.execute("UPDATE api_tokens SET revoked_at=? WHERE name=? AND revoked_at IS NULL", (v["created_at"], v["name"]))
con.execute("INSERT INTO api_tokens (name, token_hash, allow_ips, created_at, scope, admin_id) VALUES (?, ?, ?, ?, 'admin', NULL)",
            (v["name"], v["token_hash"], v["allow_ip"], v["created_at"]))
con.commit()
print("DOCTOR_DNS_API_KEY_CREATED")
'''


async def setup_existing_panel(*, host: str, ssh_port: int = 22, username: str = "root",
                               password: str | None = None, private_key: str | None = None,
                               panel_name: str = "ShopVPN") -> dict:
    """Connect to an existing Doctor DNS install, create an IP-restricted admin key,
    verify the devices endpoint, and return the API URL + key. No SSH secret is saved.
    """
    try:
        import asyncssh
    except ImportError as exc:
        raise DoctorDNSSetupError("کتابخانه asyncssh نصب نیست.") from exc

    host = _validate_host(host)
    if not 1 <= int(ssh_port) <= 65535:
        raise DoctorDNSSetupError("پورت SSH نامعتبر است.")
    if username != "root":
        raise DoctorDNSSetupError("برای راه‌اندازی خودکار، نام کاربری SSH باید root باشد.")
    if not (password or private_key):
        raise DoctorDNSSetupError("رمز عبور یا کلید خصوصی SSH الزامی است.")

    kwargs = {"host": host, "port": int(ssh_port), "username": username,
              "known_hosts": None, "connect_timeout": 20}
    if private_key:
        try:
            kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
        except Exception as exc:
            raise DoctorDNSSetupError("کلید خصوصی SSH معتبر نیست.") from exc
    else:
        kwargs["password"] = password
        kwargs["client_keys"] = None

    try:
        conn = await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=25)
    except asyncssh.PermissionDenied as exc:
        raise DoctorDNSSetupError("ورود SSH ناموفق بود؛ نام کاربری یا رمز/کلید را بررسی کنید.") from exc
    except Exception as exc:
        raise DoctorDNSSetupError(f"اتصال SSH برقرار نشد ({type(exc).__name__}).") from exc

    token = "dd_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    api_key_name = ("ShopVPN-" + re.sub(r"[^A-Za-z0-9_.-]", "", panel_name)[:40])[:60]
    key_created = False
    async with conn:
        async def run(cmd: str, timeout=25, check=True):
            try:
                result = await asyncio.wait_for(conn.run(cmd, check=False), timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise DoctorDNSSetupError("زمان اجرای دستور روی سرور تمام شد.") from exc
            if check and result.exit_status != 0:
                detail = ((result.stderr or result.stdout or "").strip())[-240:]
                raise DoctorDNSSetupError("بررسی سرور ناموفق بود: " + (detail or "خطای نامشخص"))
            return (result.stdout or "").strip()

        os_release = (await run("cat /etc/os-release", check=False)).lower()
        if not os_release or not ("debian" in os_release or "ubuntu" in os_release):
            raise DoctorDNSSetupError("سیستم‌عامل سرور شناسایی نشد یا Debian/Ubuntu نیست.")
        probe = await run(
            "if test -x /usr/local/bin/smartdns-panel && test -f /etc/smart-dns/panel.env "
            "&& test -f /var/lib/smart-dns/panel.db && systemctl is-active --quiet smartdns-panel.service; "
            "then echo DOCTOR_DNS_READY; else echo DOCTOR_DNS_NOT_READY; fi", check=False)
        if "DOCTOR_DNS_READY" not in probe:
            raise DoctorDNSSetupError("Doctor DNS نصب/فعال نیست یا مسیرهای استاندارد آن پیدا نشدند. ابتدا نصب موجود را بررسی کنید.")

        # SSH_CLIENT's first field is the source address seen by the Doctor DNS host;
        # restricting the key to it avoids leaving a globally usable admin credential.
        source = await run("printf '%s' \"${SSH_CLIENT%% *}\"", check=False)
        try:
            source_ip = str(ipaddress.ip_address(source.strip()))
        except ValueError:
            source_ip = ""
        if not source_ip:
            raise DoctorDNSSetupError("IP خروجی ShopVPN از دید سرور Doctor DNS تشخیص داده نشد؛ امکان محدودسازی کلید API وجود ندارد.")

        script = _remote_script(token, token_hash, source_ip, api_key_name)
        import base64
        encoded = base64.b64encode(script.encode()).decode()
        await run("python3 -c 'import base64; exec(compile(base64.b64decode(%s), \"<shopvpn-bootstrap>\", \"exec\"))'" % json.dumps(encoded))
        key_created = True

    async def revoke_bootstrap_key():
        """Best-effort cleanup if the API cannot be verified or the panel cannot be saved."""
        try:
            cleanup_conn = await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=15)
            async with cleanup_conn:
                cleanup = (
                    "python3 -c 'import sqlite3,datetime; "
                    "c=sqlite3.connect(\"/var/lib/smart-dns/panel.db\"); "
                    "c.execute(\"UPDATE api_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL\", "
                    "(datetime.datetime.now(datetime.timezone.utc).isoformat(), \"" + token_hash + "\")); c.commit()'"
                )
                await asyncio.wait_for(cleanup_conn.run(cleanup, check=False), timeout=15)
        except Exception:
            pass

    # Test over the real public API before returning anything to ShopVPN.
    import aiohttp
    if ":" in host and not host.startswith("["):
        url_host = f"[{host}]"
    else:
        url_host = host
    api_url = f"https://{url_host}:8445"
    timeout = aiohttp.ClientTimeout(total=18)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            async with session.get(api_url + "/api/v1/admin/stats", headers=headers, ssl=False) as resp:
                stats_text = await resp.text()
                if resp.status != 200:
                    raise DoctorDNSSetupError(f"API ادمین Doctor DNS پاسخ مناسب نداد (HTTP {resp.status}).")
            # A zero-id probe verifies route registration without modifying a real account.
            async with session.post(api_url + "/api/v1/admin/users/0/devices", headers=headers,
                                    json={"devices": 1}, ssl=False) as resp:
                body = await resp.json(content_type=None)
                if resp.status == 404 and isinstance(body, dict) and body.get("error") == "user_not_found":
                    pass  # route exists and auth is admin; target 0 intentionally does not exist
                elif resp.status == 404 and isinstance(body, dict) and body.get("error") == "not_found":
                    raise DoctorDNSSetupError("نسخه نصب‌شده Doctor DNS مسیر تنظیم دستگاه‌ها را ندارد؛ باید Doctor DNS به‌روزرسانی شود.")
                elif resp.status == 400 and isinstance(body, dict) and body.get("error") == "bad_devices":
                    raise DoctorDNSSetupError("مسیر API وجود دارد اما نسخه/اعتبارسنجی آن با ShopVPN سازگار نیست.")
                else:
                    raise DoctorDNSSetupError("بررسی مسیر تنظیم تعداد دستگاه‌ها ناموفق بود.")
    except DoctorDNSSetupError:
        await revoke_bootstrap_key()
        raise
    except Exception as exc:
        await revoke_bootstrap_key()
        raise DoctorDNSSetupError(f"API از ShopVPN قابل دسترسی نیست ({type(exc).__name__}). پورت 8445، فایروال و گواهی را بررسی کنید.") from exc

    return {"api_url": api_url, "api_password": token, "api_username": "doctordns",
            "api_verified": True, "ssh_source_ip": source_ip}
