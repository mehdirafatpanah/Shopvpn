# -*- coding: utf-8 -*-
"""نصب خودکار نود Stealth VLESS روی سرور Debian/Ubuntu فقط با IP، رمز root و دامنه.

پنل با asyncssh وصل می‌شود، نصاب deploy/install-shopvpn-stealth.py را اجرا می‌کند،
node.json را می‌خواند و نود را به‌عنوان پنل از نوع stealth ثبت و تست می‌کند.
رمز root فقط در حافظه استفاده می‌شود و ذخیره یا لاگ نمی‌شود.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
import uuid

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_FILES = (
    "deploy/install-shopvpn-stealth.py",
    "deploy/shopvpn-stealth-agent.py",
)
ALL_TRANSPORTS = ("ws", "httpupgrade", "grpc", "xhttp")
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_EMAIL_RE = re.compile(r"^[^@\s'\"\\;|&$`<>]+@[^@\s'\"\\;|&$`<>]+\.[^@\s'\"\\;|&$`<>]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.:\-]{2,255}$")
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


def start_install(db, *, name, host, ssh_port, password=None, private_key=None, domain, decoy="movie",
                  proxy_url=None, cert="letsencrypt", email="", transports=None, port=443,
                  title="Stealth", site_name="CineVault") -> str:
    """Create a background job and return its id. Secrets live only inside the task closure."""
    if not (password or private_key):
        raise InstallError("رمز root یا کلید خصوصی لازم است.")
    if not _HOST_RE.match(host or ""):
        raise InstallError("آی‌پی یا آدرس سرور نامعتبر است.")
    if not 1 <= int(ssh_port) <= 65535:
        raise InstallError("پورت SSH نامعتبر است.")
    if not _DOMAIN_RE.match(domain or ""):
        raise InstallError("دامنه نامعتبر است.")
    if decoy not in ("movie", "proxy"):
        raise InstallError("نوع سایت جعلی نامعتبر است.")
    if decoy == "proxy" and not re.match(r"^https?://[A-Za-z0-9.\-]+(:\d+)?/?$", proxy_url or ""):
        raise InstallError("آدرس سایت واقعی برای آینه نامعتبر است (فقط https://domain).")
    if cert not in ("letsencrypt", "self"):
        raise InstallError("نوع گواهی نامعتبر است.")
    if cert == "letsencrypt" and not _EMAIL_RE.match(email or ""):
        raise InstallError("برای Let's Encrypt ایمیل معتبر لازم است.")
    wanted = [t for t in ALL_TRANSPORTS if t in (transports or [])]
    if not wanted:
        raise InstallError("حداقل یک ترنسپورت انتخاب کنید.")
    if not 1 <= int(port) <= 65535 or int(port) == int(ssh_port):
        raise InstallError("پورت عمومی نامعتبر است.")
    title = (title or "Stealth").strip()[:40]
    site_name = (site_name or "CineVault").strip()[:40]
    if not re.fullmatch(r"[A-Za-z0-9 _.\-]+", title) or not re.fullmatch(r"[A-Za-z0-9 _.\-]+", site_name):
        raise InstallError("عنوان یا نام سایت فقط می‌تواند حروف لاتین، عدد، فاصله و - _ . باشد.")
    job = _new_job()

    async def _runner():
        try:
            await _install(db, job, name, host, int(ssh_port), password, private_key, domain, decoy,
                           proxy_url, cert, email, wanted, int(port), title, site_name)
            job["status"] = "done"
        except InstallError as exc:
            job["status"] = "error"
            job["error"] = str(exc)
        except Exception as exc:
            logger.exception("Stealth node auto-install failed")
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    task = asyncio.get_running_loop().create_task(_runner())
    job["_task"] = task
    return job["id"]


async def _install(db, job, name, host, ssh_port, password, private_key, domain, decoy,
                   proxy_url, cert, email, transports, port, title, site_name):
    try:
        import asyncssh
    except ImportError as exc:
        raise InstallError("کتابخانه asyncssh نصب نیست (pip install asyncssh).") from exc
    from panel_providers import get_provider

    kwargs = dict(host=host, port=ssh_port, username="root", known_hosts=None, connect_timeout=20)
    if private_key:
        try:
            kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
        except Exception as exc:
            raise InstallError("کلید خصوصی نامعتبر است.") from exc
    else:
        kwargs["password"] = password
        kwargs["client_keys"] = None

    _log(job, "در حال اتصال به سرور...")
    try:
        conn = await asyncssh.connect(**kwargs)
    except asyncssh.PermissionDenied as exc:
        raise InstallError("احراز هویت SSH ناموفق بود (رمز یا کلید اشتباه است).") from exc
    except (OSError, asyncssh.Error, asyncio.TimeoutError) as exc:
        raise InstallError(f"اتصال SSH برقرار نشد: {type(exc).__name__}") from exc

    async with conn:
        async def run(cmd, timeout=600, check=True):
            try:
                res = await asyncio.wait_for(conn.run(cmd, check=False), timeout)
            except asyncio.TimeoutError as exc:
                raise InstallError("زمان اجرای دستور روی سرور تمام شد.") from exc
            if check and res.exit_status != 0:
                tail = ((res.stdout or "") + (res.stderr or "")).strip()[-600:]
                raise InstallError(f"دستور روی سرور شکست خورد: {tail}")
            return (res.stdout or "").strip()

        osr = (await run("cat /etc/os-release", check=False)).lower()
        if "debian" not in osr and "ubuntu" not in osr:
            raise InstallError("فقط Debian/Ubuntu پشتیبانی می‌شود.")

        _log(job, "آپلود فایل‌های نصاب...")
        await run("rm -rf /tmp/shopvpn-install && mkdir -p /tmp/shopvpn-install/deploy")
        async with conn.start_sftp_client() as sftp:
            for rel in _FILES:
                local = os.path.join(_PROJECT_ROOT, rel)
                if not os.path.isfile(local):
                    raise InstallError(f"فایل نصب روی پنل پیدا نشد: {rel}")
                await sftp.put(local, f"/tmp/shopvpn-install/{rel}")

        _log(job, "نصب پیش‌نیازها (ممکن است چند دقیقه طول بکشد)...")
        await run("export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && "
                  "apt-get install -y -qq python3 curl openssl ca-certificates", timeout=900)

        args = [
            "--domain", domain, "--port", str(port), "--transports", ",".join(transports),
            "--decoy", decoy, "--cert", cert, "--title", title, "--site-name", site_name,
        ]
        if decoy == "proxy":
            args += ["--proxy-url", proxy_url]
        if cert == "letsencrypt":
            args += ["--email", email]
        _log(job, "نصب xray، nginx، سایت جعلی و گواهی TLS (چند دقیقه)...")
        cmd = "cd /tmp/shopvpn-install && python3 deploy/install-shopvpn-stealth.py " \
              + " ".join(shlex.quote(a) for a in args) + " 2>&1 </dev/null"
        out = await run(cmd, timeout=1800, check=False)
        raw = await run("cat /etc/shopvpn-stealth/node.json", check=False)
        try:
            node = json.loads(raw)
        except ValueError:
            node = None
        marker = "نصب کامل شد"
        if not node or marker not in out:
            raise InstallError("نصب روی سرور کامل نشد. خروجی سرور:\n" + out[-700:])
        await run("rm -rf /tmp/shopvpn-install", check=False)

    api_path = str(node.get("api_path") or "").strip("/")
    api_token = str(node.get("api_token") or "")
    if not api_path or not api_token:
        raise InstallError("فایل node.json روی سرور ناقص است (api_path یا api_token).")
    api_url = f"https://{domain}{'' if port == 443 else ':%d' % port}/{api_path}"

    _log(job, "ثبت نود در پنل و تست اتصال...")
    server_id = db.add_panel_server(name, "stealth", api_url, "stealth", api_token, None)
    job["node_id"] = server_id
    ok, err = False, ""
    for _ in range(6):
        ok, err = await get_provider(db.get_panel_server(server_id)).check_connection()
        if ok:
            break
        await asyncio.sleep(5)
    if not ok:
        db.delete_panel_server(server_id)
        job["node_id"] = None
        raise InstallError(
            f"نصب روی سرور انجام شد ولی پنل به نود وصل نشد: {err}. DNS دامنه (و کلادفلر/پورت {port}) را بررسی کنید؛ "
            f"آدرس API و توکن در /etc/shopvpn-stealth/node.json روی سرور هست و می‌توانید نود را دستی در «پنل‌های VPN» اضافه کنید.")
    _log(job, "نود آماده است ✅")
