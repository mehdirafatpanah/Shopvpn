# -*- coding: utf-8 -*-
"""نصب خودکار نود (Linux Agent با SSH و/یا OpenVPN و/یا WireGuard) روی یک سرور Debian/Ubuntu فقط با IP و رمز root.
همچنین می‌تواند روی نود موجود پروتکل جدید (مثلاً OpenVPN یا WireGuard) اضافه کند.

پنل با asyncssh به سرور مقصد وصل می‌شود، فایل‌های Agent را آپلود و نصب می‌کند،
توکن و گواهی TLS (با pin کردن fingerprint) می‌سازد، دسترسی Agent را فقط به IP همین
سرور محدود می‌کند، نود را در دیتابیس ثبت و یک تست واقعی (ساخت/حذف حساب آزمایشی) انجام می‌دهد.
رمز root فقط در حافظه استفاده می‌شود و هیچ‌جا ذخیره یا لاگ نمی‌شود.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import time
import uuid

logger = logging.getLogger(__name__)

AGENT_PORT = 8765
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_FILES = (
    "ssh_node_agent.py",
    "deploy/install-shopvpn-ssh-agent.sh",
    "deploy/shopvpn-ssh-agent.service",
    "deploy/shopvpn-sshd@.service",
    "deploy/shopvpn-ovpn-disconnect.sh",
    "deploy/shopvpn-ovpn-nat.service",
    "deploy/shopvpn-wg-nat.service",
)
SUPPORTED_PROTOCOLS = ("ssh", "openvpn", "wireguard")
PROTOCOL_LABELS = {"ssh": "SSH", "openvpn": "OpenVPN", "wireguard": "WireGuard"}
_JOBS: dict = {}
_MAX_JOBS = 30


class InstallError(Exception):
    pass


def _new_job() -> dict:
    now = time.time()
    for key in [k for k, v in _JOBS.items() if now - v["created"] > 3600]:
        _JOBS.pop(key, None)
    while len(_JOBS) >= _MAX_JOBS:
        _JOBS.pop(next(iter(_JOBS)))
    job = {"id": uuid.uuid4().hex, "status": "running", "log": [], "created": now,
           "node_id": None, "warning": None, "error": None}
    _JOBS[job["id"]] = job
    return job


def get_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return None
    return {k: job[k] for k in ("id", "status", "log", "node_id", "warning", "error")}


def _log(job, text: str):
    job["log"].append(str(text)[:400])


def start_install(db, *, name, host, ssh_port, username, password=None, private_key=None,
                  protocols=None, node_id=None, ovpn_port=1194, ovpn_proto="udp", wg_port=51820) -> str:
    """Create a background job and return its id. Secrets live only inside the task closure."""
    wanted = [p for p in SUPPORTED_PROTOCOLS if p in (protocols or ["ssh"])]
    if not wanted:
        raise InstallError("حداقل یک پروتکل (SSH، OpenVPN یا WireGuard) انتخاب کنید.")
    if str(ovpn_proto) not in {"udp", "tcp"}:
        raise InstallError("پروتکل انتقال OpenVPN باید udp یا tcp باشد.")
    if not 1 <= int(ovpn_port) <= 65535 or int(ovpn_port) in {22, AGENT_PORT} or 20000 <= int(ovpn_port) <= 39999:
        raise InstallError("پورت OpenVPN نامعتبر است (22، 8765 و بازه 20000-39999 مجاز نیست).")
    if not 1 <= int(wg_port) <= 65535 or int(wg_port) in {22, AGENT_PORT} or 20000 <= int(wg_port) <= 39999:
        raise InstallError("پورت WireGuard نامعتبر است (22، 8765 و بازه 20000-39999 مجاز نیست).")
    if "openvpn" in wanted and "wireguard" in wanted and str(ovpn_proto) == "udp" and int(ovpn_port) == int(wg_port):
        raise InstallError("پورت OpenVPN (UDP) و WireGuard نمی‌توانند یکسان باشند.")
    job = _new_job()

    async def _runner():
        try:
            await _install(db, job, name, host, int(ssh_port), username, password, private_key,
                           wanted, node_id, int(ovpn_port), str(ovpn_proto), int(wg_port))
            job["status"] = "done"
        except InstallError as exc:
            job["status"] = "error"
            job["error"] = str(exc)
        except Exception as exc:  # never leak secrets: only the exception type and a short message
            logger.exception("SSH node auto-install failed")
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    task = asyncio.get_running_loop().create_task(_runner())
    job["_task"] = task  # keep a reference so it is not garbage collected
    return job["id"]


def _node_protocols(node) -> list:
    import json
    config = node.get("config_json") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except ValueError:
            config = {}
    listed = config.get("protocols") if isinstance(config, dict) else None
    found = [p for p in SUPPORTED_PROTOCOLS if p in (listed or [])]
    return found or ["ssh"]


async def _install(db, job, name, host, ssh_port, username, password, private_key,
                   protocols, node_id, ovpn_port, ovpn_proto, wg_port=51820):
    try:
        import asyncssh
    except ImportError as exc:
        raise InstallError("کتابخانه asyncssh نصب نیست (pip install asyncssh).") from exc
    from ssh_credentials import encrypt_credential
    from ssh_providers import get_ssh_provider
    from quota_reconciler import _env_secret_resolver

    if username != "root":
        raise InstallError("نصب خودکار فقط با کاربر root ممکن است.")
    if not (password or private_key):
        raise InstallError("رمز root یا کلید خصوصی لازم است.")
    encrypt_credential("preflight")  # fail early if the encryption key cannot be created

    existing_node = None
    existing_protocols = []
    if node_id is not None:
        existing_node = next((n for n in db.list_ssh_nodes() if int(n["id"]) == int(node_id)), None)
        if not existing_node or existing_node.get("node_type") != "linux":
            raise InstallError("نود Linux Agent موردنظر پیدا نشد.")
        existing_protocols = _node_protocols(existing_node)
    final_protocols = [p for p in SUPPORTED_PROTOCOLS if p in set(existing_protocols) | set(protocols)]
    labels = " + ".join(PROTOCOL_LABELS[p] for p in protocols)

    kwargs = dict(host=host, port=ssh_port, username=username, known_hosts=None, connect_timeout=20)
    if private_key:
        try:
            kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
        except Exception as exc:
            raise InstallError("کلید خصوصی نامعتبر است.") from exc
    else:
        kwargs["password"] = password
        kwargs["client_keys"] = None

    _log(job, f"نصب {labels}" + (" روی نود موجود" if existing_node else " روی نود جدید"))
    _log(job, "در حال اتصال به سرور...")
    try:
        conn = await asyncssh.connect(**kwargs)
    except asyncssh.PermissionDenied as exc:
        raise InstallError("احراز هویت SSH ناموفق بود (رمز یا کلید اشتباه است).") from exc
    except (OSError, asyncssh.Error, asyncio.TimeoutError) as exc:
        raise InstallError(f"اتصال SSH برقرار نشد: {type(exc).__name__}") from exc

    fp = ""
    token = ""
    client_ip = ""
    async with conn:
        async def run(cmd, timeout=600, check=True):
            try:
                res = await asyncio.wait_for(conn.run(cmd, check=False), timeout)
            except asyncio.TimeoutError as exc:
                raise InstallError("زمان اجرای دستور روی سرور تمام شد.") from exc
            if check and res.exit_status != 0:
                tail = ((res.stderr or "") + (res.stdout or "")).strip()[-300:]
                raise InstallError(f"دستور روی سرور شکست خورد: {tail}")
            return (res.stdout or "").strip()

        osr = (await run("cat /etc/os-release", check=False)).lower()
        if "debian" not in osr and "ubuntu" not in osr:
            raise InstallError("فقط Debian/Ubuntu پشتیبانی می‌شود.")
        client_ip = (await run("echo ${SSH_CLIENT%% *}", check=False)).strip()
        if not re.fullmatch(r"[0-9a-fA-F:.]{3,45}", client_ip or ""):
            client_ip = ""
        _log(job, f"IP این پنل از دید نود: {client_ip or 'نامشخص'}")

        _log(job, "آپلود فایل‌های Agent...")
        await run("rm -rf /tmp/shopvpn-install && mkdir -p /tmp/shopvpn-install/deploy")
        async with conn.start_sftp_client() as sftp:
            for rel in _FILES:
                local = os.path.join(_PROJECT_ROOT, rel)
                if not os.path.isfile(local):
                    raise InstallError(f"فایل نصب روی پنل پیدا نشد: {rel}")
                await sftp.put(local, f"/tmp/shopvpn-install/{rel}")

        _log(job, "نصب پیش‌نیازها (ممکن است چند دقیقه طول بکشد)...")
        await run("export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq openssl", timeout=900)

        if not existing_node:
            _log(job, "ساخت گواهی TLS و توکن...")
            await run("install -d -m 0755 /etc/shopvpn && "
                      "openssl req -x509 -newkey rsa:2048 -nodes -keyout /etc/shopvpn/agent.key "
                      "-out /etc/shopvpn/agent.crt -days 3650 -subj /CN=shopvpn-agent >/dev/null 2>&1 && "
                      "chmod 600 /etc/shopvpn/agent.key")
            fp_raw = await run("openssl x509 -in /etc/shopvpn/agent.crt -noout -fingerprint -sha256")
            fp = fp_raw.split("=", 1)[-1].replace(":", "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fp):
                raise InstallError("خواندن fingerprint گواهی ناموفق بود.")

            token = secrets.token_hex(32)
            env_lines = [
                f"SHOPVPN_AGENT_TOKEN={token}",
                "SHOPVPN_AGENT_HOST=0.0.0.0",
                f"SHOPVPN_AGENT_PORT={AGENT_PORT}",
                "SHOPVPN_AGENT_DB=/var/lib/shopvpn-ssh-agent/agent.db",
                f"SHOPVPN_NFT_ACCOUNTING={1 if 'ssh' in protocols else 0}",
                "SHOPVPN_AGENT_TLS_CERT=/etc/shopvpn/agent.crt",
                "SHOPVPN_AGENT_TLS_KEY=/etc/shopvpn/agent.key",
            ]
            if client_ip:
                env_lines.append(f"SHOPVPN_AGENT_ALLOWED_IPS={client_ip}")
            async with conn.start_sftp_client() as sftp:
                async with sftp.open("/tmp/shopvpn-install/agent.env", "wb") as fh:
                    await fh.write(("\n".join(env_lines) + "\n").encode())
            await run("install -m 0600 -o root -g root /tmp/shopvpn-install/agent.env /etc/shopvpn-ssh-agent.env")
        else:
            has_env = await run("test -f /etc/shopvpn-ssh-agent.env && echo yes", check=False)
            if has_env != "yes":
                raise InstallError("فایل /etc/shopvpn-ssh-agent.env روی نود پیدا نشد؛ این نود با نصب‌کننده ShopVPN ساخته نشده است.")

        _log(job, f"نصب و راه‌اندازی سرویس‌ها ({', '.join(PROTOCOL_LABELS[p] for p in final_protocols)})...")
        script_env = f"OVPN_PORT={int(ovpn_port)} OVPN_PROTO={ovpn_proto} WG_PORT={int(wg_port)}"
        if existing_node and "ssh" in protocols:
            script_env += " SHOPVPN_ENABLE_NFT=1"
        await run(f"cd /tmp/shopvpn-install && {script_env} bash deploy/install-shopvpn-ssh-agent.sh {','.join(final_protocols)}",
                  timeout=1200)
        if "ssh" in protocols:
            _log(job, "بررسی سرویس UDPGW و پورت داخلی 7300...")
            udpgw_check = await run(
                "systemctl is-active shopvpn-udpgw.service 2>/dev/null || true; "
                "ss -ltn 2>/dev/null | grep -E '127\\.0\\.0\\.1:7300([[:space:]]|$)' || true",
                check=False)
            udpgw_lines = [line.strip() for line in udpgw_check.splitlines() if line.strip()]
            if not udpgw_lines or udpgw_lines[0] != "active" or not any("127.0.0.1:7300" in line for line in udpgw_lines[1:]):
                detail = await run("journalctl -u shopvpn-udpgw.service -n 12 --no-pager -o cat", check=False)
                raise InstallError("UDPGW نصب شد اما سرویس یا پورت 127.0.0.1:7300 آماده نیست. "
                                   f"گزارش سرویس: {detail[-500:]}")
            _log(job, "UDPGW فعال است و روی 127.0.0.1:7300 گوش می‌دهد ✅")
        await run("systemctl restart shopvpn-ssh-agent; sleep 4", check=False)
        state = await run("systemctl is-active shopvpn-ssh-agent", check=False)
        if state != "active":
            tail = await run("journalctl -u shopvpn-ssh-agent -n 12 --no-pager -o cat", check=False)
            raise InstallError(f"سرویس Agent بالا نیامد ({state}). خروجی سرور:\n{tail[-600:]}")

        if "openvpn" in protocols:
            ovpn_state = ""
            for _ in range(8):
                ovpn_state = await run("systemctl is-active openvpn-server@shopvpn", check=False)
                if ovpn_state == "active":
                    break
                await asyncio.sleep(1.5)
            if ovpn_state != "active":
                tail = await run("journalctl -u openvpn-server@shopvpn -n 12 --no-pager -o cat", check=False)
                raise InstallError(f"سرویس OpenVPN بالا نیامد ({ovpn_state}). خروجی سرور:\n{tail[-600:]}")
            sock_ok = await run("test -S /run/openvpn-server/shopvpn.sock && echo yes", check=False)
            if sock_ok != "yes":
                raise InstallError("سوکت management سرویس OpenVPN ساخته نشد؛ حسابداری حجم ممکن نیست.")

        if "wireguard" in protocols:
            wg_state = ""
            for _ in range(8):
                wg_state = await run("systemctl is-active wg-quick@wg-shopvpn", check=False)
                if wg_state == "active":
                    break
                await asyncio.sleep(1.5)
            if wg_state != "active":
                tail = await run("journalctl -u wg-quick@wg-shopvpn -n 12 --no-pager -o cat", check=False)
                raise InstallError(f"سرویس WireGuard بالا نیامد ({wg_state}). خروجی سرور:\n{tail[-600:]}")
            wg_up = await run("wg show wg-shopvpn public-key >/dev/null 2>&1 && echo yes", check=False)
            if wg_up != "yes":
                raise InstallError("اینترفیس WireGuard ساخته نشد؛ حسابداری حجم ممکن نیست.")

        _log(job, "تنظیم فایروال...")
        rules = []
        if not existing_node:
            rules.append(f"ufw allow from {client_ip} to any port {AGENT_PORT} proto tcp" if client_ip
                         else f"ufw allow {AGENT_PORT}/tcp")
        if "ssh" in protocols:
            rules.append("ufw allow 20000:39999/tcp")
        if "openvpn" in protocols:
            rules.append(f"ufw allow {int(ovpn_port)}/{ovpn_proto}")
            rules.append("ufw route allow in on tun0")
        if "wireguard" in protocols:
            rules.append(f"ufw allow {int(wg_port)}/udp")
            rules.append("ufw route allow in on wg-shopvpn")
        if rules:
            await run("if command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'; then "
                      + " && ".join(rules) + "; fi", check=False)
        await run("rm -rf /tmp/shopvpn-install", check=False)

    node_config = {"protocols": final_protocols}
    if "openvpn" in final_protocols:
        node_config.update({"ovpn_port": ovpn_port, "ovpn_proto": ovpn_proto})
    if "wireguard" in protocols:
        node_config.update({"wg_port": wg_port})
    if existing_node:
        db.merge_ssh_node_config(int(node_id), node_config)
    else:
        secret_ref = "enc:" + encrypt_credential(token)
        node_id = db.create_ssh_node(
            name, "linux", host, ssh_port, auth_type="api_token", username="root", secret_ref=secret_ref,
            config_json={"agent_url": f"https://{host}:{AGENT_PORT}", "cert_sha256": fp,
                         "auto_installed": True, "agent_allowed_ip": client_ip, **node_config})
    job["node_id"] = node_id
    node = next(n for n in db.list_ssh_nodes() if int(n["id"]) == int(node_id))
    provider = get_ssh_provider(node, secret_resolver=_env_secret_resolver)
    _log(job, "تست اتصال به Agent...")
    ok = False
    for _ in range(5):
        try:
            ok = await provider.test_connection()
            if ok:
                break
        except Exception:
            await asyncio.sleep(2)
    if not ok:
        db.update_ssh_node_status(node_id, "error", "Agent connection failed after install")
        raise InstallError("Agent نصب شد ولی پنل نتوانست به آن وصل شود. فایروال/امنیت‌گروه سرویس‌دهنده پورت "
                           f"{AGENT_PORT} را بررسی کنید. نود با شناسه {node_id} ثبت شده و با «تست اتصال» دوباره امتحان می‌شود.")
    db.update_ssh_node_status(node_id, "active", None)

    warnings = []
    for proto in protocols:
        label = PROTOCOL_LABELS[proto]
        _log(job, f"تست حسابداری حجم {label} (ساخت و حذف حساب آزمایشی)...")
        try:
            res = await provider.create_account("svtest" + secrets.token_hex(3), 0, None, protocol=proto)
            try:
                usage = await provider.get_usage(res.account_id)
            finally:
                await provider.delete_account(res.account_id)
            if usage.get("accounting_ready"):
                _log(job, f"حسابداری حجم {label} فعال است ✅")
            else:
                warnings.append(f"شمارنده حجم {label} آماده نیست؛ فروش محصول حجمی {label} روی این نود تا رفع مشکل متوقف می‌ماند.")
        except Exception as exc:
            warnings.append(f"تست حساب آزمایشی {label} ناموفق بود: {type(exc).__name__}: {str(exc)[:160]}")
    job["warning"] = " | ".join(warnings) or None
    _log(job, "نود آماده است ✅")
