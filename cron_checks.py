# -*- coding: utf-8 -*-
"""کرون ساعتی: بررسی همه‌ی سیستم‌های قابل‌چک و ذخیره‌ی وضعیت برای داشبورد پنل وب."""

import asyncio
import html
import json
import logging
import os
import socket
import ssl
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

STATE_KEY = "_job_cron_state"
REQUEST_KEY = "_job_cron_request"
INTERVAL_SECONDS = 3600
POLL_SECONDS = 10
STARTUP_DELAY_SECONDS = 90
CHECK_TIMEOUT = 90

OK, WARN, ERROR, SKIP = "ok", "warn", "error", "skip"
_SEVERITY = {SKIP: 0, OK: 0, WARN: 1, ERROR: 2}
_ICON = {OK: "🟢", WARN: "🟠", ERROR: "🔴", SKIP: "⚪"}


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(iso: str):
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - dt).total_seconds(), 0)
    except (TypeError, ValueError):
        return None


def _human_age(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)} دقیقه"
    if seconds < 172800:
        return f"{int(seconds // 3600)} ساعت"
    return f"{int(seconds // 86400)} روز"


def _short(items, limit=4) -> str:
    items = [str(i) for i in items]
    extra = len(items) - limit
    text = "، ".join(items[:limit])
    return text + (f" و {extra} مورد دیگر" if extra > 0 else "")


def _http_host_ok(status: int) -> bool:
    return status < 500


async def _http_probe(url: str, timeout: float = 10) -> int:
    client_timeout = aiohttp.ClientTimeout(total=timeout, connect=min(timeout, 8))
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        async with session.get(url, allow_redirects=False) as resp:
            return resp.status


async def check_panels(db, bot):
    import panel_health
    servers = await _db(db.get_panel_servers, True)
    if not servers:
        return SKIP, "پنل فعالی ثبت نشده است."
    sem = asyncio.Semaphore(panel_health.PROBE_CONCURRENCY)
    results = await asyncio.gather(*(panel_health._probe(s, sem) for s in servers))
    down = [(s, err) for s, (ok, err) in zip(servers, results) if not ok]
    if not down:
        return OK, f"هر {len(servers)} پنل در دسترس است."
    if not await panel_health._reference_reachable():
        return WARN, "اتصال خود سرور به اینترنت مشکل دارد؛ نتیجه‌ی پنل‌ها قابل اعتماد نیست."
    names = [f"{s['name']} ({(err or '')[:60]})" for s, err in down]
    status = ERROR if len(down) == len(servers) else WARN
    return status, f"{len(down)} از {len(servers)} پنل در دسترس نیست: {_short(names, 3)}"


async def check_capacity(db, bot):
    servers = await _db(db.get_panel_servers, True)
    full, near, limited = [], [], 0
    for s in servers:
        info = await _db(db.get_panel_capacity_info, s["id"])
        if not info or not info["max_services"]:
            continue
        limited += 1
        label = f"{s['name']} ({info['active_services']}/{info['max_services']})"
        if info["percent"] >= 100:
            full.append(label)
        elif info["near_limit"]:
            near.append(label)
    if not limited:
        return SKIP, "برای هیچ پنلی سقف ظرفیت تنظیم نشده است."
    if full:
        return ERROR, f"ظرفیت پر شده و فروش روی آن‌ها متوقف است: {_short(full)}"
    if near:
        return WARN, f"نزدیک پر شدن (بالای ۹۰٪): {_short(near)}"
    return OK, f"ظرفیت {limited} پنل مشکلی ندارد."


async def check_stock(db, bot):
    overview = await _db(db.get_low_stock_overview)
    if not overview:
        return SKIP, "محصول انبارداری‌شده‌ای وجود ندارد."
    low = [p for p in overview if p["low"]]
    if not low:
        return OK, f"موجودی {len(overview)} محصول کافی است."
    empty = [p["name"] for p in low if p["stock"] <= 0]
    parts = [f"{len(low)} محصول موجودی کم دارد: {_short([p['name'] + ' (' + str(p['stock']) + ')' for p in low])}"]
    if empty:
        parts.append(f"{len(empty)} محصول تمام شده است.")
    return WARN, " | ".join(parts)


def _resources_sync():
    import psutil
    cpu = psutil.cpu_percent(interval=0.5)
    cores = psutil.cpu_count(logical=True) or 1
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    try:
        load1 = os.getloadavg()[0]
    except (OSError, AttributeError):
        load1 = None
    return cpu, cores, mem, disk, load1


async def check_resources(db, bot):
    try:
        cpu, cores, mem, disk, load1 = await asyncio.to_thread(_resources_sync)
    except ImportError:
        return SKIP, "psutil نصب نیست."
    problems, status = [], OK

    def flag(level, text):
        nonlocal status
        problems.append(text)
        if _SEVERITY[level] > _SEVERITY[status]:
            status = level

    if disk >= 90:
        flag(ERROR, f"دیسک {disk:.0f}٪ پر است")
    elif disk >= 80:
        flag(WARN, f"دیسک {disk:.0f}٪ پر است")
    if mem >= 95:
        flag(ERROR, f"رم {mem:.0f}٪ مصرف شده")
    elif mem >= 90:
        flag(WARN, f"رم {mem:.0f}٪ مصرف شده")
    if load1 is not None and load1 / cores > 2:
        flag(WARN, f"لود سیستم {load1:.1f} روی {cores} هسته")
    summary = f"CPU {cpu:.0f}٪ | رم {mem:.0f}٪ | دیسک {disk:.0f}٪"
    return status, (f"{summary} | " + "، ".join(problems)) if problems else summary


def _backup_dir_for(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")


async def check_backup(db, bot):
    from config import DB_PATH
    backup_dir = _backup_dir_for(DB_PATH)
    files = []
    if os.path.isdir(backup_dir):
        for name in os.listdir(backup_dir):
            if name.endswith((".db", ".zip")) and not name.startswith("pre_restore_"):
                path = os.path.join(backup_dir, name)
                try:
                    files.append((os.path.getmtime(path), path))
                except OSError:
                    continue
    if not files:
        return ERROR, "هیچ فایل بکاپی پیدا نشد."
    mtime, path = max(files)
    age = time.time() - mtime
    try:
        interval_h = float((await _db(db.get_setting, "backup_interval_hours", "")) or 24)
    except ValueError:
        interval_h = 24.0
    interval_h = max(interval_h, 1.0)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    summary = f"آخرین بکاپ {_human_age(age)} پیش ({size_mb:.1f}MB، {len(files)} نسخه)"
    if size_mb <= 0:
        return ERROR, summary + " و فایل خالی است."
    if path.endswith(".db"):
        from backup import is_valid_sqlite_db
        if not await asyncio.to_thread(is_valid_sqlite_db, path):
            return ERROR, summary + " و فایل معتبر نیست."
    if age > interval_h * 3 * 3600:
        return ERROR, summary + "؛ بکاپ‌گیری خودکار متوقف شده است."
    if age > interval_h * 1.5 * 3600:
        return WARN, summary + "؛ از زمان‌بندی عقب است."
    return OK, summary


async def check_config_scan(db, bot):
    link = ((await _db(db.get_setting, "master_sub_link", "")) or "").strip()
    if not link:
        return SKIP, "لینک ساب مادر تنظیم نشده است."
    import geo_scan
    result = await geo_scan.scan_subscription(
        link, force_refresh=True, check_status=True, tcp_timeout=geo_scan.TCP_TIMEOUT_BACKGROUND,
    )
    if not result.get("ok"):
        return ERROR, str(result.get("error") or "خواندن لینک ساب ناموفق بود.")[:200]
    servers = result.get("servers") or []
    if not servers:
        return WARN, "لینک ساب خوانده شد ولی سروری در آن نبود."
    offline = [s for s in servers if s.get("status") == "offline"]
    if not offline:
        return OK, f"{len(servers)} سرور بررسی شد و همه آنلاین‌اند."
    names = [s.get("remark") or s.get("host") or s.get("ip") or "?" for s in offline]
    status = ERROR if len(offline) == len(servers) else WARN
    return status, f"{len(offline)} از {len(servers)} سرور آفلاین است: {_short(names)}"


async def check_exchange_rate(db, bot):
    import exchange_rate
    try:
        cache = await exchange_rate.refresh_rate(None)
    except Exception as exc:
        return ERROR, f"دریافت نرخ دلار از همه‌ی منابع ناموفق بود: {str(exc)[:120]}"
    if not cache.get("ts"):
        return ERROR, "منابع نرخ دلار پاسخ ندادند و فقط نرخ قدیمی کش در دسترس است."
    rate = cache.get("rate")
    source = cache.get("source")
    if source == "manual":
        return WARN, f"منابع آنلاین پاسخ ندادند؛ نرخ دستی پشتیبان استفاده می‌شود ({rate:,.0f})."
    return OK, f"نرخ دلار {rate:,.0f} تومان (منبع: {source})."


async def check_renewal_loop(db, bot):
    from renewal_reminders import STATUS_KEY_LAST_RUN
    last = (await _db(db.get_setting, STATUS_KEY_LAST_RUN, "")) or ""
    if not last:
        return WARN, "هنوز هیچ اجرای ثبت‌شده‌ای از یادآوری تمدید/حجم وجود ندارد."
    age = _age_seconds(last)
    if age is None:
        return WARN, "زمان آخرین اجرا نامعتبر است."
    if age > 3 * 3600:
        return ERROR, f"آخرین اجرای یادآوری تمدید {_human_age(age)} پیش بوده؛ حلقه متوقف به نظر می‌رسد."
    if age > 90 * 60:
        return WARN, f"آخرین اجرای یادآوری تمدید {_human_age(age)} پیش بوده."
    return OK, f"آخرین اجرای یادآوری تمدید {_human_age(age)} پیش بوده."


def _db_health_sync(db_path: str):
    size = os.path.getsize(db_path)
    wal = os.path.getsize(db_path + "-wal") if os.path.exists(db_path + "-wal") else 0
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        rows = conn.execute("PRAGMA quick_check").fetchall()
    finally:
        conn.close()
    verdict = "; ".join(str(r[0]) for r in rows[:3])
    return size, wal, verdict


async def check_database(db, bot):
    from config import DB_PATH
    if not os.path.exists(DB_PATH):
        return ERROR, "فایل دیتابیس اصلی پیدا نشد."
    try:
        size, wal, verdict = await asyncio.to_thread(_db_health_sync, DB_PATH)
    except sqlite3.Error as exc:
        return ERROR, f"بررسی دیتابیس ناموفق بود: {str(exc)[:150]}"
    summary = f"حجم دیتابیس {size / 1048576:.1f}MB، WAL {wal / 1048576:.1f}MB"
    if verdict != "ok":
        return ERROR, f"{summary} | quick_check: {verdict[:150]}"
    if wal > 256 * 1048576:
        return WARN, summary + " | فایل WAL بزرگ است."
    return OK, summary + " | یکپارچگی سالم است."


async def check_ssh_nodes(db, bot):
    from ssh_providers import get_ssh_provider
    from quota_reconciler import _env_secret_resolver
    nodes = [n for n in await _db(db.list_ssh_nodes, False) if n.get("status") in ("active", "degraded", "error")]
    if not nodes:
        return SKIP, "نود SSH/OpenVPN/WireGuard فعالی ثبت نشده است."

    async def probe(node):
        try:
            provider = get_ssh_provider(node, secret_resolver=_env_secret_resolver)
            ok = await asyncio.wait_for(provider.test_connection(), 20)
            return bool(ok), "" if ok else "پاسخ نامعتبر"
        except asyncio.TimeoutError:
            return False, "timeout"
        except Exception as exc:
            return False, (str(exc) or type(exc).__name__)[:80]

    results = await asyncio.gather(*(probe(n) for n in nodes))
    down = [f"{n.get('name') or n['id']} ({err})" for n, (ok, err) in zip(nodes, results) if not ok]
    if not down:
        return OK, f"هر {len(nodes)} نود در دسترس است."
    status = ERROR if len(down) == len(nodes) else WARN
    return status, f"{len(down)} از {len(nodes)} نود در دسترس نیست: {_short(down, 3)}"


_GATEWAY_HOSTS = {
    "noapay": "https://noapay.mirname.xyz",
    "abangateway": "https://api.abangateway.ir",
    "blupal": "https://www.blupal.net",
    "plisio": "https://api.plisio.net",
    "zarinpal": "https://payment.zarinpal.com",
    "aqayepardakht": "https://panel.aqayepardakht.ir",
    "tetra98": "https://tetra98.com",
    "cubepay": "https://cubevps.ir",
    "nowpayments": "https://api.nowpayments.io",
}


def _gateway_specs(db):
    import config
    import extra_gateway_registry as reg
    specs = [
        ("noapay", "نوا‌پی", "noapay_payment_enabled", [db.get_setting("noapay_api_key", "") or getattr(config, "NOAPAY_API_KEY", "")]),
        ("abangateway", "آبان‌گیت", "abangateway_payment_enabled", [db.get_setting("abangateway_api_key", "") or getattr(config, "ABANGATEWAY_API_KEY", "")]),
        ("blupal", "بلوپال", "blupal_payment_enabled", [db.get_setting("blupal_api_key", "") or getattr(config, "BLUPAL_API_KEY", "")]),
        ("plisio", "کریپتو (Plisio)", "crypto_payment_enabled", [db.get_setting("plisio_api_key", "") or getattr(config, "PLISIO_API_KEY", "")]),
    ]
    for key in reg.GATEWAY_ORDER:
        gw = reg.GATEWAYS.get(key) or {}
        required = [f["setting"] for f in gw.get("fields", []) if f.get("required")]
        specs.append((key, gw.get("title", key), reg.enable_setting(key), [db.get_setting(s, "") for s in required]))
    return specs


async def check_gateways(db, bot):
    specs = await _db(_gateway_specs, db)
    enabled = [s for s in specs if (db.get_setting(s[2], "0") == "1")]
    if not enabled:
        return SKIP, "هیچ درگاه آنلاینی فعال نیست."

    async def probe(spec):
        key, title, _, secrets_ = spec
        if not all((v or "").strip() for v in secrets_):
            return ERROR, f"{title}: فعال است ولی کلید/مشخصات ناقص است"
        host = _GATEWAY_HOSTS.get(key)
        if not host:
            return OK, ""
        try:
            code = await _http_probe(host)
        except Exception as exc:
            return ERROR, f"{title}: در دسترس نیست ({(str(exc) or type(exc).__name__)[:50]})"
        if not _http_host_ok(code):
            return WARN, f"{title}: خطای سرور {code}"
        return OK, ""

    results = await asyncio.gather(*(probe(s) for s in enabled))
    errors = [m for st, m in results if st == ERROR]
    warns = [m for st, m in results if st == WARN]
    if errors:
        return ERROR, f"{len(errors)} درگاه مشکل دارد: {_short(errors + warns, 3)}"
    if warns:
        return WARN, _short(warns, 3)
    return OK, f"هر {len(enabled)} درگاه فعال در دسترس است."


async def check_ai(db, bot):
    import ai_support
    import ai_text
    if not await _db(ai_support.is_configured, db):
        return SKIP, "هوش مصنوعی تنظیم نشده است."
    try:
        await asyncio.wait_for(
            ai_text.generate_json(db, 'Reply with only this JSON: {"ok": true}', "ping"), 60,
        )
    except asyncio.TimeoutError:
        return ERROR, "ارائه‌دهنده‌ی AI در زمان مقرر پاسخ نداد."
    except Exception as exc:
        return ERROR, f"درخواست آزمایشی AI ناموفق بود: {str(exc)[:150]}"
    return OK, "ارائه‌دهنده‌ی AI به درخواست آزمایشی پاسخ داد."


async def check_translation(db, bot):
    import translation_engine
    statuses = await _db(translation_engine.provider_status, db)
    libre = next((p for p in statuses if p.get("name") == "libretranslate" and p.get("configured")), None)
    if not libre:
        return SKIP, "LibreTranslate فعال/تنظیم نشده است."
    endpoint = os.getenv("SHOPVPN_LIBRETRANSLATE_URL", "http://127.0.0.1:5000").strip().rstrip("/")
    try:
        code = await _http_probe(endpoint + "/languages", timeout=10)
    except Exception as exc:
        return ERROR, f"LibreTranslate پاسخ نمی‌دهد ({(str(exc) or type(exc).__name__)[:60]})."
    if code >= 400:
        return ERROR, f"LibreTranslate کد خطا {code} برگرداند."
    return OK, "موتور ترجمه‌ی LibreTranslate در دسترس است."


async def check_sessions(db, bot):
    import userbot
    sessions = {
        "یوزربات": userbot.load_session(),
        "اسکنر نشت": userbot.load_session(userbot.SCANNER_SESSION_PATH),
    }
    present = [name for name, data in sessions.items() if data]
    if not present:
        return SKIP, "هیچ سشن یوزربات/اسکنری ثبت نشده است."
    problems = []
    if sessions["یوزربات"] and not userbot.STATE.get("connected"):
        err = (userbot.STATE.get("last_error") or "").strip()
        problems.append("یوزربات متصل نیست" + (f" ({err[:60]})" if err else ""))
    if problems:
        return WARN, "؛ ".join(problems)
    return OK, f"سشن‌های ثبت‌شده سالم‌اند: {_short(present)}."


def _smtp_sync():
    import smtplib
    import web_auth
    env = web_auth._smtp_env
    host = env("SHOPVPN_SMTP_HOST").strip()
    user = env("SHOPVPN_SMTP_USER").strip()
    password = env("SHOPVPN_SMTP_PASSWORD")
    port = int(env("SHOPVPN_SMTP_PORT", "587") or "587")
    use_ssl = env("SHOPVPN_SMTP_SSL", "0").lower() in {"1", "true", "yes"}
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
            smtp.login(user, password)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
    return host


async def check_smtp(db, bot):
    import web_auth
    if not web_auth.email_configured():
        return SKIP, "SMTP برای ورود با ایمیل تنظیم نشده است."
    try:
        host = await asyncio.to_thread(_smtp_sync)
    except Exception as exc:
        return ERROR, f"ورود به SMTP ناموفق بود: {(str(exc) or type(exc).__name__)[:120]}"
    return OK, f"اتصال و ورود به SMTP ({host}) موفق بود."


def _cert_days_left(host: str, port: int):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    return int((ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) // 86400)


def _ssl_hosts():
    import config
    hosts = {}
    for url in (getattr(config, "API_BASE_URL", ""), getattr(config, "MINIAPP_URL", "")):
        parsed = urlparse(url or "")
        if parsed.scheme == "https" and parsed.hostname:
            hosts[parsed.hostname] = parsed.port or 443
    return hosts


async def check_ssl(db, bot):
    hosts = await asyncio.to_thread(_ssl_hosts)
    if not hosts:
        return SKIP, "آدرس https برای دامنه‌ی پنل/مینی‌اپ تنظیم نشده است."
    errors, warns, oks = [], [], []
    for host, port in hosts.items():
        try:
            days = await asyncio.to_thread(_cert_days_left, host, port)
        except ssl.SSLCertVerificationError as exc:
            errors.append(f"{host}: گواهی نامعتبر ({(exc.verify_message or 'verify failed')[:50]})")
            continue
        except Exception as exc:
            errors.append(f"{host}: اتصال TLS ناموفق ({(str(exc) or type(exc).__name__)[:50]})")
            continue
        if days < 0:
            errors.append(f"{host}: گواهی منقضی شده است")
        elif days < 7:
            errors.append(f"{host}: {days} روز تا انقضا")
        elif days < 15:
            warns.append(f"{host}: {days} روز تا انقضا")
        else:
            oks.append(f"{host}: {days} روز")
    if errors:
        return ERROR, _short(errors + warns, 3)
    if warns:
        return WARN, _short(warns, 3)
    return OK, "گواهی‌ها معتبرند: " + _short(oks, 3)


async def check_telegram(db, bot):
    from config import BOT_TOKEN
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(base + "/getMe") as resp:
                me = await resp.json(content_type=None)
            async with session.get(base + "/getWebhookInfo") as resp:
                hook = await resp.json(content_type=None)
    except Exception as exc:
        return ERROR, f"اتصال به API تلگرام ناموفق بود: {(str(exc) or type(exc).__name__)[:100]}"
    if not me.get("ok"):
        return ERROR, f"توکن بات توسط تلگرام رد شد: {str(me.get('description'))[:80]}"
    info = hook.get("result") or {}
    username = (me.get("result") or {}).get("username", "")
    if info.get("url"):
        last_err = info.get("last_error_date") or 0
        if last_err and time.time() - last_err < 3600:
            return WARN, f"@{username} | وب‌هوک در یک ساعت اخیر خطا داشته: {str(info.get('last_error_message'))[:80]}"
        if (info.get("pending_update_count") or 0) > 100:
            return WARN, f"@{username} | {info['pending_update_count']} آپدیت در صف وب‌هوک مانده است."
    return OK, f"@{username} پاسخ می‌دهد."


async def check_push(db, bot):
    import fcm_client
    import config
    parts, status = [], OK
    configured = False
    if config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY:
        configured = True
        parts.append("کلیدهای VAPID تنظیم شده‌اند")
    if await _db(fcm_client.is_configured, db):
        configured = True
        try:
            sa = fcm_client._load_service_account(db)
            await asyncio.wait_for(fcm_client._get_access_token(sa), 20)
            parts.append("اعتبار سرویس‌اکانت FCM تایید شد")
        except Exception as exc:
            status = ERROR
            parts.append(f"دریافت توکن FCM ناموفق: {(str(exc) or type(exc).__name__)[:80]}")
    if not configured:
        return SKIP, "نه VAPID و نه FCM تنظیم شده است."
    return status, " | ".join(parts)


CHECKS = (
    ("panels", "پنل‌های VPN", check_panels),
    ("capacity", "ظرفیت پنل‌ها", check_capacity),
    ("stock", "موجودی محصولات", check_stock),
    ("resources", "منابع سرور", check_resources),
    ("backup", "بکاپ", check_backup),
    ("config_scan", "وضعیت کانفیگ‌ها (ساب مادر)", check_config_scan),
    ("exchange_rate", "نرخ دلار", check_exchange_rate),
    ("renewal_loop", "یادآوری تمدید", check_renewal_loop),
    ("database", "سلامت دیتابیس", check_database),
    ("ssh_nodes", "نودهای SSH/OpenVPN/WireGuard", check_ssh_nodes),
    ("gateways", "درگاه‌های پرداخت", check_gateways),
    ("ai", "هوش مصنوعی", check_ai),
    ("translation", "موتور ترجمه", check_translation),
    ("sessions", "یوزربات و اسکنر نشت", check_sessions),
    ("smtp", "ایمیل SMTP", check_smtp),
    ("ssl", "گواهی SSL دامنه", check_ssl),
    ("telegram", "API تلگرام", check_telegram),
    ("push", "اعلان پوش (VAPID/FCM)", check_push),
)


def load_state(db) -> dict:
    try:
        data = json.loads(db.get_setting(STATE_KEY, "") or "{}")
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("results", {})
    return data


def _save_state(db, state: dict) -> None:
    db.set_setting(STATE_KEY, json.dumps(state, ensure_ascii=False))


async def _run_one(key, title, fn, db, bot):
    started = time.monotonic()
    try:
        status, message = await asyncio.wait_for(fn(db, bot), CHECK_TIMEOUT)
    except asyncio.TimeoutError:
        status, message = ERROR, "بررسی در زمان مقرر تمام نشد."
    except Exception as exc:
        logger.exception("چک کرون %s ناموفق بود.", key)
        status, message = ERROR, f"خطای داخلی در بررسی: {(str(exc) or type(exc).__name__)[:150]}"
    return key, {
        "title": title,
        "status": status,
        "message": message,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


async def run_checks(db, bot=None) -> dict:
    """همه‌ی چک‌ها را هم‌زمان اجرا می‌کند، وضعیت را ذخیره و در صورت تغییر هشدار می‌دهد."""
    previous = await _db(load_state, db)
    prev_results = previous.get("results", {})
    pairs = await asyncio.gather(*(_run_one(k, t, f, db, bot) for k, t, f in CHECKS))
    now = _now_iso()
    results = {}
    for key, item in pairs:
        old = prev_results.get(key) or {}
        item["checked_at"] = now
        item["since"] = old.get("since") if old.get("status") == item["status"] and old.get("since") else now
        results[key] = item
    state = {
        "checked_at": now,
        "interval_seconds": INTERVAL_SECONDS,
        "handled_request": previous.get("handled_request", ""),
        "order": [k for k, _, _ in CHECKS],
        "results": results,
    }
    await _db(_save_state, db, state)
    if bot is not None:
        try:
            await _notify_changes(bot, db, prev_results, results)
        except Exception:
            logger.exception("ارسال هشدار کرون ناموفق بود.")
    return state


async def _notify_changes(bot, db, prev_results: dict, results: dict) -> None:
    import report_router
    new_problems, recovered = [], []
    for key, item in results.items():
        old_status = (prev_results.get(key) or {}).get("status", OK)
        new_status = item["status"]
        if _SEVERITY[new_status] > _SEVERITY.get(old_status, 0):
            new_problems.append(item)
        elif _SEVERITY[new_status] == 0 and _SEVERITY.get(old_status, 0) > 0 and new_status == OK:
            recovered.append(item)
    if not new_problems and not recovered:
        return
    lines = ["🕐 <b>گزارش کرون ساعتی</b>"]
    for item in sorted(new_problems, key=lambda i: -_SEVERITY[i["status"]]):
        lines.append(f"\n{_ICON[item['status']]} <b>{html.escape(item['title'])}</b>\n{html.escape(item['message'])}")
    for item in recovered:
        lines.append(f"\n🟢 <b>{html.escape(item['title'])}</b> به حالت عادی برگشت.")
    await report_router.report(bot, db, "service", "\n".join(lines), senior_only=True)


def request_run(db) -> str:
    """درخواست اجرای فوری از پنل وب؛ حلقه‌ی کرون داخل پردازش بات آن را برمی‌دارد."""
    token = str(time.time())
    db.set_setting(REQUEST_KEY, token)
    return token


async def cron_loop(bot, db) -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            state = await _db(load_state, db)
            request = (await _db(db.get_setting, REQUEST_KEY, "")) or ""
            age = _age_seconds(state.get("checked_at", ""))
            due = age is None or age >= INTERVAL_SECONDS - POLL_SECONDS
            requested = bool(request) and request != state.get("handled_request", "")
            if due or requested:
                new_state = await run_checks(db, bot)
                if requested:
                    new_state["handled_request"] = request
                    await _db(_save_state, db, new_state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("چرخه‌ی کرون ناموفق بود.")
        await asyncio.sleep(POLL_SECONDS)
