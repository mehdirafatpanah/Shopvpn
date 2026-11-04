# -*- coding: utf-8 -*-
"""آپدیت پروژه از طریق خود بات تلگرام.

جریان کار:
  ۱. توسعه‌دهنده نسخه‌ی جدید را روی GitHub می‌گذارد و فایل ``VERSION`` را بالا می‌برد
     (اسکریپت ``release.sh`` همین کار را خودکار انجام می‌دهد؛ فایل اختیاری ``update.json``
     هم توضیح تغییرات را همراه دارد).
  ۲. بات هر چند ساعت (پیش‌فرض ۶) فایل ``VERSION`` مخزن را می‌خواند؛ اگر از نسخه‌ی نصب‌شده
     جدیدتر بود، به مالک و مدیران کامل پیام می‌دهد (با دکمه‌ی «آپدیت الان»).
  ۳. با تأیید مدیر، ``update_runner.sh`` جدا از پروسه‌ی بات (با systemd-run) اجرا می‌شود:
     بکاپ دیتابیس و کد ← دریافت کد جدید ← نصب پکیج‌ها ← بررسی نحو ← ری‌استارت سرویس‌ها
     ← بررسی سلامت. اگر هر مرحله خراب شود، خودکار به نسخه‌ی قبل برمی‌گردد.
  ۴. بات بعد از بالا آمدن نتیجه را به همان مدیر اعلام می‌کند.

هیچ داده‌ای به سمت توسعه‌دهنده ارسال نمی‌شود؛ فقط چند فایل متنی از GitHub خوانده می‌شود.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time

from config import BASE_DIR

logger = logging.getLogger(__name__)

REPO_OWNER = os.getenv("SHOPVPN_UPDATE_OWNER", "mehdirafatpanah")
REPO_NAME = os.getenv("SHOPVPN_UPDATE_REPO", "Shopvpn")
REPO_BRANCH = os.getenv("SHOPVPN_UPDATE_BRANCH", "main")

RAW_BASES = (
    f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}",
    # آینه‌ی جایگزین برای سرورهایی که دسترسی‌شان به raw.githubusercontent قطع است
    f"https://cdn.jsdelivr.net/gh/{REPO_OWNER}/{REPO_NAME}@{REPO_BRANCH}",
)

STATE_FILE = os.path.join(BASE_DIR, "update_state.json")
RESULT_FILE = os.path.join(BASE_DIR, "update_result.txt")
RUNNER = os.path.join(BASE_DIR, "update_runner.sh")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

# کلیدهای تنظیمات (جدول settings)
K_NOTIFY = "update_notify_enabled"          # "1"/"0" — اعلان خودکار نسخه‌ی جدید
K_NOTIFIED = "update_notified_version"      # آخرین نسخه‌ای که برایش اعلان رفته
K_NOTIFIED_AT = "update_notified_at"        # زمان آخرین اعلان (epoch)
K_LATEST = "update_latest_info"             # JSON آخرین اطلاعات دریافتی
K_LAST_CHECK = "update_last_check"          # epoch آخرین بررسی موفق
K_INTERVAL = "update_check_hours"           # فاصله‌ی بررسی (ساعت)

DEFAULT_INTERVAL_HOURS = 6
CRITICAL_REMIND_HOURS = 12

_RUN_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# نسخه
# ---------------------------------------------------------------------------
def current_version() -> str:
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def parse_version(value: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", str(value or ""))[:4]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


# ---------------------------------------------------------------------------
# دریافت اطلاعات نسخه‌ی جدید از GitHub
# ---------------------------------------------------------------------------
async def _http_get(session, url: str):
    import aiohttp
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15),
                               headers={"Cache-Control": "no-cache"}) as resp:
            if resp.status != 200:
                return None
            return await resp.text()
    except Exception:
        return None


def release_url(version: str) -> str:
    return f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/tag/v{version}"


async def fetch_latest():
    """{"version", "critical", "notes"} یا None اگر هیچ منبعی در دسترس نبود."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        for base in RAW_BASES:
            version_text = await _http_get(session, f"{base}/VERSION?t={int(time.time())}")
            if not version_text:
                continue
            version = version_text.strip().splitlines()[0].strip() if version_text.strip() else ""
            if not re.fullmatch(r"v?\d+(\.\d+){0,3}", version):
                continue
            info = {"version": version.lstrip("v"), "critical": False, "notes": [],
                    "url": release_url(version.lstrip("v"))}
            meta_text = await _http_get(session, f"{base}/update.json?t={int(time.time())}")
            if meta_text:
                try:
                    meta = json.loads(meta_text)
                    if parse_version(meta.get("version", "")) == parse_version(version):
                        info["critical"] = bool(meta.get("critical"))
                        notes = meta.get("notes") or {}
                        if isinstance(notes, dict):
                            notes = notes.get("fa") or notes.get("en") or []
                        if isinstance(notes, str):
                            notes = [notes]
                        info["notes"] = [str(n)[:300] for n in list(notes)[:15]]
                        url = str(meta.get("url") or "").strip()
                        if url.startswith("https://"):
                            info["url"] = url
                except (ValueError, AttributeError):
                    pass
            return info
    return None


def _load_cached(db) -> dict:
    try:
        return json.loads(db.get_setting(K_LATEST, "") or "{}")
    except ValueError:
        return {}


async def check(db, force: bool = False) -> dict:
    """بررسی نسخه؛ خروجی: current, latest, available, critical, notes, checked(bool)."""
    cur = current_version()
    cached = await asyncio.to_thread(_load_cached, db)
    checked = False
    if force or not cached:
        fetched = await fetch_latest()
        if fetched:
            cached = fetched
            checked = True
            await asyncio.to_thread(db.set_setting, K_LATEST, json.dumps(fetched, ensure_ascii=False))
            await asyncio.to_thread(db.set_setting, K_LAST_CHECK, str(int(time.time())))
    latest = cached.get("version", "") if cached else ""
    return {
        "current": cur,
        "latest": latest,
        "available": bool(latest) and is_newer(latest, cur),
        "critical": bool(cached.get("critical")) if cached else False,
        "notes": cached.get("notes", []) if cached else [],
        "url": (cached.get("url") or release_url(latest)) if latest else "",
        "checked": checked,
    }


# ---------------------------------------------------------------------------
# اعلان به مدیران
# ---------------------------------------------------------------------------
def senior_admin_ids(db) -> list:
    ids = []
    try:
        for row in db.list_admins_with_roles():
            if row["role"] in ("owner", "admin"):
                ids.append(int(row["telegram_id"]))
    except Exception:
        logger.exception("خواندن لیست ادمین‌ها برای اعلان آپدیت ناموفق بود.")
    return list(dict.fromkeys(ids))


def format_notes(notes: list) -> str:
    import html
    return "\n".join(f"• {html.escape(n)}" for n in notes) if notes else ""


def build_notice(info: dict) -> str:
    head = "🚨 آپدیت مهم" if info["critical"] else "🆕 نسخه‌ی جدید ربات منتشر شد"
    lines = [head, "", f"نسخه‌ی نصب‌شده: {info['current']}", f"نسخه‌ی جدید: {info['latest']}"]
    notes = format_notes(info["notes"])
    if notes:
        lines += ["", "تغییرات:", notes]
    if info.get("url"):
        lines += ["", f"🔗 جزئیات کامل: {info['url']}"]
    lines += ["", "قبل از آپدیت خودکار از دیتابیس و کد بکاپ گرفته می‌شود و اگر مشکلی پیش بیاید به نسخه‌ی قبل برمی‌گردد. "
                  "ربات حدود ۳۰ ثانیه آفلاین می‌شود."]
    return "\n".join(lines)


async def notify_admins(bot, db, info: dict) -> int:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    link_row = [[InlineKeyboardButton(text="📄 تغییرات نسخه", url=info["url"])]] if info.get("url") else []
    markup = InlineKeyboardMarkup(inline_keyboard=[
        *link_row,
        [InlineKeyboardButton(text="🔄 آپدیت الان", callback_data="adm_update_ask")],
        [InlineKeyboardButton(text="🔕 بعداً", callback_data="adm_update_later"),
         InlineKeyboardButton(text="⚙️ تنظیمات آپدیت", callback_data="adm_update")],
    ])
    sent = 0
    text = build_notice(info)
    for admin_id in senior_admin_ids(db):
        try:
            await bot.send_message(admin_id, text, reply_markup=markup)
            sent += 1
        except Exception:
            logger.debug("ارسال اعلان آپدیت به %s ناموفق بود.", admin_id, exc_info=True)
    return sent


async def check_loop(bot, db):
    """حلقه‌ی پس‌زمینه — فقط روی بات اصلی اجرا می‌شود."""
    await asyncio.sleep(120)
    while True:
        try:
            if str(await asyncio.to_thread(db.get_setting, K_NOTIFY, "1")) != "0":
                info = await check(db, force=True)
                if info["available"]:
                    notified = await asyncio.to_thread(db.get_setting, K_NOTIFIED, "")
                    last_at = float(await asyncio.to_thread(db.get_setting, K_NOTIFIED_AT, "0") or 0)
                    first_time = parse_version(notified) != parse_version(info["latest"])
                    remind = info["critical"] and time.time() - last_at >= CRITICAL_REMIND_HOURS * 3600
                    if first_time or remind:
                        if await notify_admins(bot, db, info):
                            await asyncio.to_thread(db.set_setting, K_NOTIFIED, info["latest"])
                            await asyncio.to_thread(db.set_setting, K_NOTIFIED_AT, str(int(time.time())))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("بررسی خودکار نسخه‌ی جدید ناموفق بود.")
        try:
            hours = max(1, min(168, int(await asyncio.to_thread(db.get_setting, K_INTERVAL, str(DEFAULT_INTERVAL_HOURS)) or DEFAULT_INTERVAL_HOURS)))
        except (TypeError, ValueError):
            hours = DEFAULT_INTERVAL_HOURS
        await asyncio.sleep(hours * 3600)


# ---------------------------------------------------------------------------
# اجرای آپدیت
# ---------------------------------------------------------------------------
def detect_service_name() -> str:
    """نام سرویس systemd که همین پروسه داخلش اجرا می‌شود (None اگر با systemd اجرا نشده)."""
    env = os.getenv("SHOPVPN_SERVICE_NAME", "").strip()
    if env:
        return env
    try:
        with open("/proc/self/cgroup", encoding="utf-8") as fh:
            for line in fh:
                m = re.search(r"/([A-Za-z0-9_.@-]+)\.service(?:/|$)", line.strip())
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def list_snapshots() -> list:
    try:
        names = sorted(n for n in os.listdir(BACKUP_DIR) if n.startswith("code_before_update_") and n.endswith(".tar.gz"))
    except OSError:
        return []
    return [os.path.join(BACKUP_DIR, n) for n in names]


def _can_run() -> str:
    """رشته‌ی خالی یعنی مشکلی نیست؛ وگرنه دلیل (فارسی)."""
    if os.name != "posix":
        return "آپدیت از داخل بات فقط روی سرور لینوکسی پشتیبانی می‌شود."
    if not os.path.isfile(RUNNER):
        return "فایل update_runner.sh کنار پروژه پیدا نشد."
    if not detect_service_name():
        return "بات با systemd اجرا نشده؛ آپدیت را از «bash manage.sh» انجام بده."
    if os.geteuid() != 0:
        if not shutil.which("sudo"):
            return "دسترسی sudo در دسترس نیست؛ آپدیت را از «bash manage.sh» انجام بده."
        try:
            ok = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=10).returncode == 0
        except Exception:
            ok = False
        if not ok:
            return "کاربر سرویس sudo بدون رمز ندارد؛ آپدیت را از «bash manage.sh» انجام بده."
    return ""


def _spawn_runner(mode: str) -> str:
    """runner را جدا از cgroup بات اجرا می‌کند؛ رشته‌ی خالی = موفق، وگرنه متن خطا."""
    service = detect_service_name()
    env = {
        "INSTALL_DIR": BASE_DIR, "SERVICE_NAME": service,
        "REPO_OWNER": REPO_OWNER, "REPO_NAME": REPO_NAME, "REPO_BRANCH": REPO_BRANCH,
    }
    import pwd
    me = pwd.getpwuid(os.getuid())
    unit = f"{service}-updater-{int(time.time())}"
    if shutil.which("systemd-run"):
        cmd = [] if os.geteuid() == 0 else ["sudo", "-n"]
        cmd += ["systemd-run", "--unit", unit, "--collect", "--quiet",
                "-p", f"WorkingDirectory={BASE_DIR}"]
        if os.geteuid() != 0:
            cmd += ["--uid", me.pw_name, "--gid", str(me.pw_gid)]
        for k, v in env.items():
            cmd += [f"--setenv={k}={v}"]
        cmd += ["--setenv=UPDATE_DETACHED=1", "bash", RUNNER, mode]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                return ""
            logger.warning("systemd-run ناموفق بود: %s", (res.stderr or res.stdout).strip()[:300])
        except Exception:
            logger.exception("اجرای systemd-run ناموفق بود.")
    # جایگزین: پروسه‌ی جداشده؛ ممکن است هنگام ری‌استارت سرویس کشته شود، ولی runner
    # سرویس بات را آخرین مرحله ری‌استارت می‌کند پس کار اصلی قبل از آن تمام شده است.
    try:
        subprocess.Popen(["setsid", "bash", RUNNER, mode], cwd=BASE_DIR, env={**os.environ, **env},
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return ""
    except Exception as exc:
        return f"اجرای آپدیت شروع نشد: {exc}"


async def start(mode: str, initiator_id: int, chat_id: int, message_id: int, target_version: str = "") -> str:
    """mode: update | rollback. رشته‌ی خالی = شروع شد؛ وگرنه دلیل خطا."""
    if _RUN_LOCK.locked():
        return "یک آپدیت هم‌اکنون در حال اجراست."
    async with _RUN_LOCK:
        problem = await asyncio.to_thread(_can_run)
        if problem:
            return problem
        if mode == "rollback" and not list_snapshots():
            return "نسخه‌ی پشتیبانی برای برگشت پیدا نشد."
        try:
            os.remove(RESULT_FILE)
        except OSError:
            pass
        state = {"mode": mode, "initiator": initiator_id, "chat_id": chat_id, "message_id": message_id,
                 "from": current_version(), "to": target_version, "started": int(time.time())}
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        err = await asyncio.to_thread(_spawn_runner, mode)
        if err:
            try:
                os.remove(STATE_FILE)
            except OSError:
                pass
        return err


def _read_result() -> dict:
    out = {}
    try:
        with open(RESULT_FILE, encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


async def announce_result(bot, db):
    """بعد از بالا آمدن بات: نتیجه‌ی آپدیت/برگشت قبلی را به مدیری که شروع کرده اعلام می‌کند."""
    await asyncio.sleep(6)
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    result = _read_result()
    # اگر runner هنوز کارش تمام نشده (نتیجه‌ای ننوشته) و کمتر از ۱۰ دقیقه گذشته، منتظر می‌مانیم
    for _ in range(60):
        if result.get("status"):
            break
        if time.time() - int(state.get("started", 0) or 0) > 600:
            break
        await asyncio.sleep(5)
        result = _read_result()
    status = result.get("status", "")
    now = current_version()
    if status == "ok":
        text = f"✅ آپدیت با موفقیت انجام شد.\nنسخه‌ی {state.get('from', '?')} ← {now}"
    elif status == "rollback_ok":
        text = f"↩️ برگشت به نسخه‌ی قبل انجام شد.\nنسخه‌ی فعلی: {now}"
    elif status == "rolled_back":
        text = ("⚠️ آپدیت ناموفق بود و خودکار به نسخه‌ی قبل برگشتیم؛ ربات روی نسخه‌ی "
                f"{now} سالم کار می‌کند.\nدلیل: {result.get('reason', 'نامشخص')}\n"
                "جزئیات: logs/update.log روی سرور.")
    elif status == "failed":
        text = f"❌ آپدیت ناموفق بود.\nدلیل: {result.get('reason', 'نامشخص')}\nجزئیات: logs/update.log روی سرور."
    else:
        text = "ℹ️ نتیجه‌ی آپدیت قبلی مشخص نشد. لطفاً logs/update.log را روی سرور بررسی کن."
    targets = [state.get("chat_id")] if state.get("chat_id") else []
    for admin_id in senior_admin_ids(db) if not targets else []:
        targets.append(admin_id)
    for chat in targets:
        try:
            await bot.send_message(chat, text)
        except Exception:
            logger.debug("اعلام نتیجه‌ی آپدیت ناموفق بود.", exc_info=True)
    for path in (STATE_FILE, RESULT_FILE):
        try:
            os.remove(path)
        except OSError:
            pass
