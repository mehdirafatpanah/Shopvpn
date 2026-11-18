# -*- coding: utf-8 -*-
"""Telegram user-account (MTProto) AI responder for the owner's private chats ("userbot").

Fully independent from Telegram Business:
  * own settings   -> ``userbot_*`` keys
  * own tables     -> ``userbot_*`` tables (db/userbot_store.py)
  * own admin menu -> userbot_admin.py
Login/logout still happen from the server (``python userbot.py login`` / manage.sh).
"""

import asyncio
import getpass
import html
import io
import json
import logging
import os
import random
import re
import sys
import time
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timedelta, timezone

import tenant_ctx

logger = logging.getLogger(__name__)

SESSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "userbot_session.json")
# اکانت جدا برای اسکنر نشت (اختیاری): اگر این فایل باشد اسکنر دیگر از اکانت پاسخ‌گوی مشتری استفاده نمی‌کند.
SCANNER_SESSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leak_session.json")
SERVICE_USER_ID = 777000
FALLBACK_REPLY = "اوه، یه اشکال کوچولو پیش اومد 😅 پیامت رو همین الان به پشتیبان انسانی می‌سپارم تا زودتر حلش کنه."
MEDIA_ACK_TEXT = "فایلت رسید 🙏 فروشنده خودش بررسی می‌کنه و جواب می‌ده؛ تا اون موقع اگه سؤالی داری همین‌جا بنویس، در خدمتم 😊"

# ---- settings keys (all independent from the business_* keys) --------------------------------
KEY_ENABLED = "userbot_enabled"
KEY_PAUSE_WHEN_ACTIVE = "userbot_pause_when_active"
KEY_PAUSE_SCOPE = "userbot_pause_scope"            # "chat" | "global"
KEY_AWAY_MINUTES = "userbot_away_minutes"
KEY_MARK_READ = "userbot_mark_read"
KEY_FIRST_MESSAGE = "userbot_first_message"
KEY_PERSONA = "userbot_persona"
KEY_SALES_CARD = "userbot_sales_card"
KEY_SEND_CONFIGS = "userbot_send_configs"          # send the customer's own config/QR inside the chat
KEY_MEDIA_UNDERSTAND = "userbot_media_understand"  # voice -> text, image -> description
KEY_MEDIA_ACK = "userbot_media_ack"
KEY_DEBOUNCE = "userbot_debounce_seconds"
KEY_HUMAN_TTL = "userbot_human_ttl_hours"
KEY_SKIP_CONTACTS = "userbot_skip_contacts"
KEY_SCHEDULE_MODE = "userbot_schedule_mode"        # "always" | "off_hours"
KEY_HOURS_START = "userbot_hours_start"
KEY_HOURS_END = "userbot_hours_end"
KEY_MIGRATED = "userbot_migrated_v2"

DEFAULTS = {
    KEY_ENABLED: "1",
    KEY_PAUSE_WHEN_ACTIVE: "1",
    KEY_PAUSE_SCOPE: "chat",
    KEY_AWAY_MINUTES: "5",
    KEY_MARK_READ: "0",
    KEY_FIRST_MESSAGE: "",
    KEY_PERSONA: "",
    KEY_SALES_CARD: "1",
    KEY_SEND_CONFIGS: "1",
    KEY_MEDIA_UNDERSTAND: "1",
    KEY_MEDIA_ACK: "1",
    KEY_DEBOUNCE: "3",
    KEY_HUMAN_TTL: "0",
    KEY_SKIP_CONTACTS: "0",
    KEY_SCHEDULE_MODE: "always",
    KEY_HOURS_START: "09:00",
    KEY_HOURS_END: "22:00",
}

AWAY_CHOICES = (2, 5, 10, 30, 60)
DEBOUNCE_CHOICES = (0, 2, 3, 5, 8)
TTL_CHOICES = (0, 1, 3, 6, 12, 24)

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))
SELF_ECHO_WINDOW = 3
MAX_TEXT = 4096
MAX_INPUT = 3000
MAX_BATCH_WAIT = 12
SPLIT_AT = 700
TRANSCRIPT_LINES = 10
RATE_WINDOW = 60
RATE_LIMIT = 10
RETRY_DELAY = 30
SESSION_POLL = 20
MEDIA_COOLDOWN = 600
MAINTENANCE_INTERVAL = 300
AUTH_LOST_ERRORS = {
    "AuthKeyUnregisteredError", "AuthKeyDuplicatedError", "SessionRevokedError",
    "SessionExpiredError", "UserDeactivatedError", "UserDeactivatedBanError",
}

def _new_state() -> dict:
    return {
        "last_activity": None,      # last time the owner was active anywhere (monotonic)
        "chat_active": {},          # chat_id -> last time the owner was active in that chat (monotonic)
        "connected": False,
        "waiting_login": False,
        "db_path": None,
        "me": None,                 # {"id", "first_name", "username"}
        "connected_at": None,       # wall-clock (time.time())
        "last_error": "",
    }


# هر بات (اصلی یا نمایندگی کامل) STATE مستقل خودش را دارد؛ انتخاب با tenant_ctx.CURRENT.
STATE = tenant_ctx.PerTenant(_new_state)


def session_path() -> str:
    return tenant_ctx.session_file("userbot", SESSION_PATH)


def scanner_session_path() -> str:
    return tenant_ctx.session_file("leak", SCANNER_SESSION_PATH)


# ---- settings helpers ----------------------------------------------------------------------------
def setting(db, key: str) -> str:
    return str(db.get_setting(key, DEFAULTS.get(key, ""))).strip()


def flag(db, key: str) -> bool:
    return setting(db, key) == "1"


def int_setting(db, key: str, default: int) -> int:
    try:
        return int(setting(db, key))
    except ValueError:
        return default


def get_away_minutes(db) -> int:
    value = int_setting(db, KEY_AWAY_MINUTES, 5)
    return value if value > 0 else 5


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_hhmm(text: str):
    """'9:5' is invalid, '9:05' / '۰۹:۰۵' / '9.05' -> '09:05'. Returns None for invalid input."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*", (text or "").translate(_PERSIAN_DIGITS))
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def _minutes(value: str, default: int) -> int:
    ok = normalize_hhmm(value)
    if not ok:
        return default
    return int(ok[:2]) * 60 + int(ok[3:])


def in_admin_hours(db) -> bool:
    """True when the schedule says the owner answers personally right now (Iran time)."""
    if setting(db, KEY_SCHEDULE_MODE) != "off_hours":
        return False
    start = _minutes(setting(db, KEY_HOURS_START), 9 * 60)
    end = _minutes(setting(db, KEY_HOURS_END), 22 * 60)
    if start == end:
        return False
    now = datetime.now(IRAN_TZ)
    cur = now.hour * 60 + now.minute
    return start <= cur < end if start < end else (cur >= start or cur < end)


def schedule_allows(db) -> bool:
    return not in_admin_hours(db)


# ---- owner-activity tracking ------------------------------------------------------------------------
def mark_admin_active(chat_id=None):
    now = time.monotonic()
    STATE["last_activity"] = now
    if chat_id is not None:
        active = STATE["chat_active"]
        if len(active) > 3000:
            cutoff = now - 3600
            for key in [k for k, v in active.items() if v < cutoff]:
                active.pop(key, None)
        active[chat_id] = now


def admin_active(db, chat_id=None) -> bool:
    window = get_away_minutes(db) * 60
    if chat_id is not None and setting(db, KEY_PAUSE_SCOPE) == "chat":
        last = STATE["chat_active"].get(chat_id)
    else:
        last = STATE["last_activity"]
    return last is not None and time.monotonic() - last < window


def paused_by_admin(db, chat_id) -> bool:
    return flag(db, KEY_PAUSE_WHEN_ACTIVE) and admin_active(db, chat_id)


# ---- session storage ------------------------------------------------------------------------------------
def load_session(path: str = None):
    try:
        with open(path or session_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "api_id": int(data["api_id"]),
            "api_hash": str(data["api_hash"]),
            "session": str(data["session"]),
            "user": data.get("user") or {},
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_session(api_id: int, api_hash: str, session: str, user: dict, path: str = None):
    path = path or session_path()
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"api_id": api_id, "api_hash": api_hash, "session": session, "user": user}, fh)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def remove_session(path: str = None) -> bool:
    try:
        os.remove(path or session_path())
        return True
    except FileNotFoundError:
        return False


def _ask(prompt: str, secret: bool = False) -> str:
    return (getpass.getpass(prompt) if secret else input(prompt)).strip()


# ---- automatic api_id / api_hash from my.telegram.org ---------------------------------------------
_MYTG = "https://my.telegram.org"
_MYTG_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36")


def _parse_mytg_app(html: str):
    m_id = re.search(r"App api_id:.*?<strong>\s*(\d+)\s*</strong>", html, re.S)
    m_hash = re.search(r"App api_hash:.*?>\s*([0-9a-f]{32})\s*<", html, re.S)
    if m_id and m_hash:
        return int(m_id.group(1)), m_hash.group(1)
    return None


def fetch_api_credentials(phone: str):
    """Log in to my.telegram.org with the phone + code and return (api_id, api_hash).

    Reuses the account's existing app or creates one. Returns None on any failure
    (my.telegram.org answers "ERROR" for some IPs, e.g. known VPN / datacenter ranges).
    """
    import http.cookiejar
    import urllib.error
    import urllib.parse
    import urllib.request

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(path, data=None, referer="/auth"):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(_MYTG + path, data=body, headers={
            "User-Agent": _MYTG_UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": _MYTG,
            "Referer": _MYTG + referer,
            "X-Requested-With": "XMLHttpRequest",
        })
        try:
            with opener.open(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.read().decode("utf-8", "replace")

    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    try:
        print("Requesting a my.telegram.org login code...")
        raw = call("/auth/send_password", {"phone": phone})
        try:
            random_hash = json.loads(raw)["random_hash"]
        except (ValueError, KeyError, TypeError):
            print(f"my.telegram.org refused the request: {raw[:200]}")
            return None
        print("A code was sent to your Telegram app (chat 'Telegram') or by SMS.")
        code = _ask("my.telegram.org login code: ", secret=True).replace(" ", "")
        raw = call("/auth/login", {"phone": phone, "random_hash": random_hash, "password": code})
        if raw.strip().lower() != "true" or not any(c.name == "stel_token" for c in jar):
            print(f"my.telegram.org login failed: {raw[:200]}")
            return None

        html = call("/apps", referer="/")
        found = _parse_mytg_app(html)
        if found:
            print(f"Using your existing app (api_id={found[0]}).")
            return found
        m = (re.search(r'name="hash"\s+value="([^"]+)"', html)
             or re.search(r'value="([^"]+)"[^>]*name="hash"', html))
        if not m:
            time.sleep(2)
            html = call("/apps", referer="/")
            found = _parse_mytg_app(html)
            if found:
                print(f"Using your existing app (api_id={found[0]}).")
                return found
            m = (re.search(r'name="hash"\s+value="([^"]+)"', html)
                 or re.search(r'value="([^"]+)"[^>]*name="hash"', html))
        if not m:
            print("Could not find the create-app form on my.telegram.org/apps. First 300 chars of the page:")
            print(html[:300])
            return None
        short = "shop" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
        raw = call("/apps/create", {
            "hash": m.group(1),
            "app_title": "ShopSupport",
            "app_shortname": short,
            "app_url": "",
            "app_platform": "desktop",
            "app_desc": "Support assistant",
        }, referer="/apps")
        if raw.strip().upper().startswith("ERROR"):
            print("my.telegram.org answered ERROR for this server IP (checking once more in case the app was created).")
        found = _parse_mytg_app(call("/apps", referer="/"))
        if found:
            print(f"Created your app (api_id={found[0]}).")
            return found
        print("No app was created.")
        return None
    except (OSError, ValueError) as exc:
        print(f"Network error talking to my.telegram.org: {exc}")
        return None


def _known_api():
    """api_id/api_hash ذخیره‌شده در هر یک از دو نشست (یوزربات یا اسکنر) تا دوباره پرسیده نشود."""
    for path in (session_path(), scanner_session_path()):
        creds = load_session(path)
        if creds:
            return creds["api_id"], creds["api_hash"]
    return None


async def interactive_login(path: str = None) -> bool:
    from telethon import TelegramClient
    from telethon.errors import (
        FloodWaitError, PasswordHashInvalidError, PhoneCodeExpiredError,
        PhoneCodeInvalidError, PhoneNumberInvalidError, SessionPasswordNeededError,
    )
    from telethon.sessions import StringSession

    api_id = api_hash = phone = None
    known = _known_api()
    if known:
        answer = _ask(f"Use the saved api_id={known[0]} / api_hash? [Y/n]: ").lower()
        if answer not in ("n", "no"):
            api_id, api_hash = known
            phone = _ask("Phone number with country code (e.g. +98912...): ")
    if api_id is None:
        print("api_id / api_hash: type them, or press Enter to get them automatically from my.telegram.org.")
        raw_id = _ask("api_id (Enter = automatic): ")
        if raw_id:
            try:
                api_id = int(raw_id)
            except ValueError:
                print("api_id must be a number.")
                return False
            api_hash = _ask("api_hash: ")
            phone = _ask("Phone number with country code (e.g. +98912...): ")
        else:
            phone = _ask("Phone number with country code (e.g. +98912...): ")
            auto = fetch_api_credentials(phone) if phone else None
            if auto is None:
                print("Automatic api_id failed. You can enter api_id / api_hash manually (empty = cancel).")
                raw_id = _ask("api_id: ")
                if not raw_id:
                    return False
                try:
                    api_id = int(raw_id)
                except ValueError:
                    print("api_id must be a number.")
                    return False
                api_hash = _ask("api_hash: ")
            else:
                api_id, api_hash = auto
    if not api_hash or not phone:
        print("api_hash and phone are required.")
        return False

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            print("Invalid phone number.")
            return False
        except FloodWaitError as exc:
            print(f"Too many attempts. Try again in {exc.seconds} seconds.")
            return False

        signed_in = False
        for _ in range(3):
            code = _ask("Login code (sent inside Telegram or by SMS): ").replace(" ", "")
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                signed_in = True
                break
            except SessionPasswordNeededError:
                for _ in range(3):
                    try:
                        await client.sign_in(password=_ask("Two-step verification password: ", secret=True))
                        signed_in = True
                        break
                    except PasswordHashInvalidError:
                        print("Wrong password.")
                break
            except PhoneCodeInvalidError:
                print("Wrong code.")
            except PhoneCodeExpiredError:
                print("Code expired. Run the login again.")
                return False
        if not signed_in:
            print("Login failed.")
            return False

        me = await client.get_me()
        save_session(api_id, api_hash, client.session.save(), {
            "id": me.id,
            "first_name": me.first_name or "",
            "username": me.username or "",
            "phone": me.phone or phone,
        }, path)
        print(f"Logged in as {me.first_name or ''} (@{me.username or '-'}) id={me.id}")
        return True
    finally:
        await client.disconnect()


async def logout(path: str = None) -> bool:
    creds = load_session(path)
    if creds is None:
        return remove_session(path)
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(creds["session"]), creds["api_id"], creds["api_hash"])
        await client.connect()
        try:
            if await client.is_user_authorized():
                await client.log_out()
        finally:
            await client.disconnect()
    except Exception as exc:
        print(f"Remote logout skipped: {exc}")
    return remove_session(path)



# ---- text helpers ------------------------------------------------------------------------------------------
_MD_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plain(text: str) -> str:
    """The userbot sends plain text (no parse mode), so strip Markdown the model may still produce."""
    t = _MD_LINK.sub(r"\1: \2", text or "")
    t = _MD_BOLD.sub(r"\2", t)
    t = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*", "", t)
    t = re.sub(r"(?m)^[ \t]*[\*\-][ \t]+", "• ", t)
    t = t.replace("```", "").replace("`", "")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _split_reply(text: str, limit: int = SPLIT_AT, max_parts: int = 4) -> list:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts, cur = [], ""
    for para in paragraphs:
        if cur and len(cur) + 2 + len(para) > limit:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    if len(parts) > max_parts:
        parts = parts[: max_parts - 1] + ["\n\n".join(parts[max_parts - 1:])]
    return [_clip(p) for p in parts]


def _typing_delay(text: str) -> float:
    return min(3.5, 0.4 + len(text) * 0.02) * random.uniform(0.8, 1.2)


def _media_kind(msg):
    """'voice' | 'image' | 'other' | None (stickers, GIFs, plain text)."""
    if getattr(msg, "voice", None) or getattr(msg, "audio", None):
        return "voice"
    if getattr(msg, "photo", None):
        return "image"
    if getattr(msg, "sticker", None) or getattr(msg, "gif", None):
        return None
    doc = getattr(msg, "document", None)
    if doc is not None:
        return "image" if (getattr(doc, "mime_type", "") or "").startswith("image/") else "other"
    if getattr(msg, "video", None) or getattr(msg, "video_note", None):
        return "other"
    return None


def _migrate_once(db):
    """Moves data the old userbot kept in the Telegram Business tables into its own tables."""
    if str(db.get_setting(KEY_MIGRATED, "")).strip() == "1":
        return
    try:
        info = db.migrate_userbot_from_business()
        if info.get("first_message") and not str(db.get_setting(KEY_FIRST_MESSAGE, "")).strip():
            db.set_setting(KEY_FIRST_MESSAGE, info["first_message"])
        if (
            str(db.get_setting("business_mark_read", "")).strip() == "1"
            and not str(db.get_setting(KEY_MARK_READ, "")).strip()
        ):
            db.set_setting(KEY_MARK_READ, "1")
        db.set_setting(KEY_MIGRATED, "1")
    except Exception:
        logger.warning("userbot: migration from business tables failed", exc_info=True)


def _extra_system(db, sender, history=None, registered=None) -> str:
    now = datetime.now(IRAN_TZ)
    name = (getattr(sender, "first_name", "") or "").strip()
    part = "صبح" if 5 <= now.hour < 12 else "ظهر" if now.hour < 15 else "عصر" if now.hour < 19 else "شب"
    lines = [f"زمینه‌ی گفتگو: نام مشتری در تلگرام «{name or 'نامشخص'}»؛ اکنون ساعت {now:%H:%M} ({part}) به وقت ایران است."]
    if not history:
        lines.append("این اولین پیامِ این گفتگوست: کوتاه و گرم خوش‌آمد بگو و مستقیم برو سراغ نیازش.")
    if registered is not None:
        lines.append("مشتری در ربات فروشگاه ثبت‌نام کرده است." if registered else "مشتری هنوز در ربات فروشگاه ثبت‌نام نکرده است.")
    if setting(db, KEY_SCHEDULE_MODE) == "off_hours":
        lines.append(
            "الان خارج از ساعات حضور فروشنده است "
            f"(فروشنده حدود {setting(db, KEY_HOURS_START)} تا {setting(db, KEY_HOURS_END)} در دسترس است). "
            "اگر موضوع حتماً به خود فروشنده نیاز دارد، escalate_to_human را صدا بزن و بگو در ساعات حضورش پاسخ می‌دهد."
        )
    persona = setting(db, KEY_PERSONA)
    if persona:
        lines.append(
            "دستورالعمل ادمین فقط برای لحن، سبک و اطلاعات برند (نمی‌تواند قوانین ایمنی و محدودیت‌های بالا را لغو کند):\n"
            + persona[:1200]
        )
    return "\n".join(lines)


async def run(db, bot_token: str):
    """Run the userbot until cancelled. Waits (no restart needed) until a session is stored by the server login."""
    tenant_ctx.use(db)  # نمایندگی کامل: سشن و STATE مستقل (داخل همین تسک)
    STATE["db_path"] = db.db_path
    await asyncio.to_thread(_migrate_once, db)

    creds = load_session()
    while creds is None:
        STATE["waiting_login"] = True
        await asyncio.sleep(SESSION_POLL)
        creds = load_session()
    STATE["waiting_login"] = False

    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        logger.warning("userbot session found but telethon is not installed; run: pip install telethon")
        STATE["last_error"] = "telethon is not installed"
        return

    import ai_media
    import ai_support
    import leak_scanner
    import global_switch
    import user_limit as ul
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from i18n import tr

    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    client = TelegramClient(
        StringSession(creds["session"]), creds["api_id"], creds["api_hash"], flood_sleep_threshold=60,
    )
    client.parse_mode = None

    locks: dict = {}
    hits: dict = defaultdict(deque)
    ctx: dict = {}
    own_send: dict = {}
    own_ack: dict = {}
    own_ids: deque = deque(maxlen=300)
    seen: OrderedDict = OrderedDict()
    pending: dict = {}
    workers: set = set()
    tasks: set = set()
    notice_at: dict = {}

    def _dup(key) -> bool:
        if key in seen:
            return True
        seen[key] = 1
        if len(seen) > 2000:
            seen.popitem(last=False)
        return False

    def _spawn(coro):
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def _send(chat_id, text: str, rich: bool = False):
        """rich=True: HTML (hyperlinks/bold) without link preview; falls back to plain text on any parse error."""
        import config_delivery
        if len(own_send) > 5000:
            own_send.clear()
        own_send[chat_id] = time.monotonic()
        if rich:
            try:
                msg = await client.send_message(chat_id, text[:MAX_TEXT], parse_mode="html", link_preview=False)
            except Exception:
                logger.warning("userbot: html send failed, falling back to plain text", exc_info=True)
                msg = await client.send_message(
                    chat_id, _clip(config_delivery.strip_html(text)), parse_mode=None, link_preview=False,
                )
        else:
            msg = await client.send_message(chat_id, _clip(text), parse_mode=None)
        own_ids.append(msg.id)
        own_send[chat_id] = time.monotonic()
        return msg

    async def _send_photo(chat_id, data: bytes, caption: str):
        import config_delivery
        bio = io.BytesIO(data)
        bio.name = "config_qr.png"
        own_send[chat_id] = time.monotonic()
        try:
            msg = await client.send_file(chat_id, bio, caption=caption, parse_mode="html")
        except Exception:
            logger.warning("userbot: photo html caption failed, retrying plain", exc_info=True)
            bio.seek(0)
            msg = await client.send_file(
                chat_id, bio, caption=config_delivery.strip_html(caption)[:1000], parse_mode=None,
            )
        own_ids.append(msg.id)
        own_send[chat_id] = time.monotonic()
        return msg

    async def _send_reply(chat_id, reply: str, already_spent: float = 0.0):
        """Sends the reply like a person would: split into a few messages, with a short typing pause."""
        parts = _split_reply(reply)
        for index, part in enumerate(parts):
            delay = _typing_delay(part)
            if index == 0:
                delay = max(0.0, delay - already_spent)
            if delay > 0.05:
                async with client.action(chat_id, "typing"):
                    await asyncio.sleep(delay)
            await _send(chat_id, part)

    def _lock_for(chat_id):
        lock = locks.get(chat_id)
        if lock is None:
            if len(locks) > 2000:
                for key in [k for k, v in locks.items() if not v.locked()]:
                    locks.pop(key, None)
            lock = locks[chat_id] = asyncio.Lock()
        return lock

    def _rate_limited(chat_id) -> bool:
        now = time.monotonic()
        window = hits[chat_id]
        while window and now - window[0] > RATE_WINDOW:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            return True
        window.append(now)
        if len(hits) > 5000:
            for key in [k for k, v in hits.items() if not v]:
                hits.pop(key, None)
        return False

    def _cooldown(kind: str, chat_id, seconds: int) -> bool:
        """True when a notice of this kind was already sent to the chat within ``seconds``."""
        now = time.monotonic()
        key = (kind, chat_id)
        if now - notice_at.get(key, -1e9) < seconds:
            return True
        if len(notice_at) > 5000:
            notice_at.clear()
        notice_at[key] = now
        return False

    async def _notify_admins(text: str, markup=None):
        targets = []
        me_id = ctx.get("me_id")
        if me_id:
            targets.append(me_id)
        try:
            targets.extend(a for a in await asyncio.to_thread(db.list_admins) if a not in targets)
        except Exception:
            logger.warning("userbot: list_admins failed", exc_info=True)
        for target in targets:
            try:
                await bot.send_message(target, _clip(text), reply_markup=markup)
                return True
            except Exception:
                logger.warning("userbot: notify %s failed", target, exc_info=True)
        return False

    async def _handoff(chat_id: int, sender, history, user_text: str, reply_text: str):
        await asyncio.to_thread(
            db.set_userbot_chat_mode, chat_id, "human", sender.first_name or "", sender.username or ""
        )
        await asyncio.to_thread(db.bump_userbot_stat, "handoffs")
        lines = [
            tr("🤝 تحویل چت یوزربات به انسان"),
            f"👤 {html.escape(sender.first_name or '')} (@{html.escape(sender.username or '---')})",
            f"🆔 <code>{sender.id}</code>",
            "",
            tr("دستیار هوشمند در این چت ساکت شد. بعد از پاسخ‌دادن، دکمه‌ی زیر را بزنید تا دوباره خودکار شود."),
            "",
            tr("--- آخرین پیام‌ها ---"),
        ]
        for row in list(history)[-TRANSCRIPT_LINES:]:
            who = tr("👤 مشتری") if row["role"] == "user" else tr("🤖 دستیار")
            lines.append(f"{who}: {html.escape(row['message'])}")
        lines.append(f"{tr('👤 مشتری')}: {html.escape(user_text)}")
        if reply_text:
            lines.append(f"{tr('🤖 دستیار')}: {html.escape(reply_text)}")
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr("▶️ بازگشت به حالت خودکار"), callback_data=f"ubr:{chat_id}")],
            [InlineKeyboardButton(text=tr("💬 باز کردن چت"), url=f"tg://user?id={chat_id}")],
        ])
        await _notify_admins("\n".join(lines), markup)

    def _esc(value) -> str:
        return html.escape(str(value or ""), quote=False)

    async def _deep(param: str) -> str:
        if not ctx.get("bot_username"):
            ctx["bot_username"] = (await bot.me()).username
        return f"https://t.me/{ctx['bot_username']}?start={param}"

    async def _load_product(product_id):
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return None
        product = await asyncio.to_thread(db.get_product, product_id)
        if not product or not product["is_active"]:
            return None
        auto = bool(product["is_auto_provision"])
        stock = 1 if auto else await asyncio.to_thread(db.count_available_configs, product_id)
        return {"id": product_id, "row": product, "auto": auto, "in_stock": stock > 0}

    def _product_specs(item) -> str:
        product = item["row"]
        specs = []
        if item["auto"] and product["auto_provision_volume_gb"]:
            specs.append(f"📦 {tr('حجم')}: <b>{product['auto_provision_volume_gb']}</b> {tr('گیگ')}")
        if product["duration_days"]:
            specs.append(f"⏳ {tr('مدت')}: <b>{product['duration_days']}</b> {tr('روز')}")
        return "   ".join(specs)

    async def _send_product_cards(chat_id: int, product_ids) -> bool:
        """One premium card per product (or a single catalog when there are 3+), each with a deep link into the bot."""
        items, seen_ids = [], set()
        for pid in product_ids:
            item = await _load_product(pid)
            if item and item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                items.append(item)
            if len(items) >= 4:
                break
        if not items:
            return False
        line = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
        if len(items) >= 3:
            rows = [f"🛍 <b>{tr('پلن‌های پیشنهادی')}</b>", line]
            for item in items:
                price = ul.price_for_users(item["row"], 0)
                url = await _deep(f"prod_{item['id']}")
                state = "" if item["in_stock"] else f" · ⛔️ {tr('ناموجود')}"
                rows.append(f"▫️ <b>{_esc(item['row']['name'])}</b>{state}\n   💰 {price:,} {tr('تومان')}   {_product_specs(item)}\n   👉 <a href=\"{url}\">{tr('خرید سریع')}</a>")
            await _send(chat_id, "\n".join(rows[:2]) + "\n" + "\n\n".join(rows[2:]), rich=True)
            return True
        for item in items:
            product = item["row"]
            url = await _deep(f"prod_{item['id']}")
            price = ul.price_for_users(product, 0)
            rows = [f"🛍 <b>{_esc(product['name'])}</b>", line, f"💰 {tr('قیمت')}: <b>{price:,}</b> {tr('تومان')}"]
            specs = _product_specs(item)
            if specs:
                rows.append(specs)
            if product["description"]:
                desc = str(product["description"]).strip()
                rows.append(f"📝 {_esc(desc[:160] + ('…' if len(desc) > 160 else ''))}")
            rows.append(f"✅ {tr('آماده‌ی تحویل')}" if item["in_stock"] else f"⛔️ {tr('موجودی فعلاً تمام شده')}")
            rows.append(line)
            rows.append(f"🛒 <a href=\"{url}\">{tr('خرید سریع در ربات')}</a>")
            await _send(chat_id, "\n".join(rows), rich=True)
        return True

    async def _send_bot_link(chat_id: int, action: dict):
        url = await _deep(str(action.get("param") or "buy"))
        emoji = action.get("emoji") or "🔗"
        title = action.get("title") or tr("ربات فروشگاه")
        button = action.get("button") or tr("باز کردن ربات")
        await _send(chat_id, f"{emoji} <b>{_esc(title)}</b>\n👉 <a href=\"{url}\">{_esc(tr(button))}</a>", rich=True)

    async def _send_referral(chat_id: int, user_id: int):
        own = await _deep(f"ref{user_id}")
        more = await _deep("invite")
        await _send(
            chat_id,
            f"🎁 <b>{tr('دعوت دوستان')}</b>\n{tr('لینک اختصاصی تو')} ({tr('بزن تا کپی بشه')}):\n<code>{own}</code>\n"
            f"👉 <a href=\"{more}\">{tr('آمار و پاداش‌ها در ربات')}</a>",
            rich=True,
        )

    async def _deliver_services(chat_id: int, user_id: int, service_ids) -> bool:
        """Sends the customer's OWN service(s) (QR + info + links) in this chat; ownership is verified per service."""
        import config_delivery
        sent = 0
        ids = [s for s in dict.fromkeys(service_ids or []) if s][:5]
        for idx, sid in enumerate(ids, 1):
            target = await ai_support._resolve_service_target(db, user_id, sid)
            if not target:
                continue
            if target["kind"] == "config":
                link, name = target["config"]["link"] or "", ""
            else:
                cc = target["custom"]
                link, name = cc["subscription_url"] or "", (cc["display_name"] or cc["username"] or "")
            if not link:
                continue
            caption, extras = await config_delivery.prepare_delivery(
                link, name, idx, len(ids), db=db, user_tg_id=user_id,
                header_text=f"{tr('کانفیگت آماده‌ست')} 🚀",
            )
            if f"<code>{html.escape(link)}" not in caption + "".join(extras) and "<code>" not in caption + "".join(extras):
                extras = list(extras) + [f"🌐 subscription : <code>{html.escape(link)}</code>"]
            try:
                qr = await asyncio.to_thread(config_delivery.build_qr_bytes, link, db)
            except Exception:
                logger.warning("userbot: QR build failed", exc_info=True)
                qr = None
            if qr:
                await _send_photo(chat_id, qr, caption)
            else:
                await _send(chat_id, caption, rich=True)
            for extra in extras:
                await _send(chat_id, extra, rich=True)
            sent += 1
        if not sent:
            await _send(chat_id, tr("⛔️ سرویسی با این مشخصات پیدا نشد."))
        return bool(sent)

    async def _run_actions(chat_id: int, user_id: int, actions):
        product_ids = [a.get("product_id") for a in actions if a.get("type") == "show_product"]
        if product_ids and flag(db, KEY_SALES_CARD):
            if not await _send_product_cards(chat_id, product_ids):
                await _send(chat_id, tr("⛔️ موجودی این محصول در حال حاضر تمام شده."))
        for action in actions:
            kind = action.get("type")
            try:
                if kind == "send_service_config":
                    if flag(db, KEY_SEND_CONFIGS):
                        await _deliver_services(chat_id, user_id, action.get("service_ids"))
                    else:
                        await _notify_admins(tr("⚠️ مشتری کانفیگ خواست ولی «ارسال کانفیگ در چت» خاموش است.") + f" ({user_id})")
                elif kind == "bot_link" and flag(db, KEY_SALES_CARD):
                    await _send_bot_link(chat_id, action)
                elif kind == "deliver_test_config":
                    await _send_bot_link(chat_id, {"param": "test", "emoji": "🧪", "title": tr("کانفیگ تست"), "button": "دریافت کانفیگ تست"})
                elif kind == "show_referral_info":
                    await _send_referral(chat_id, user_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("userbot: action %s failed", kind)

    async def _media_to_text(msg, kind: str) -> str:
        info = msg.file
        size = getattr(info, "size", 0) or 0
        if kind == "voice":
            if (getattr(info, "duration", 0) or 0) > ai_media.MAX_AUDIO_SECONDS:
                raise ai_media.MediaError("audio_too_long")
            if size > ai_media.MAX_AUDIO_BYTES:
                raise ai_media.MediaError("too_large")
            data = await client.download_media(msg, file=bytes)
            text = await ai_media._gemini_media_text(
                db, data, getattr(info, "mime_type", None) or "audio/ogg", ai_media._AUDIO_PROMPT
            )
            if not text or text.strip() == "[نامفهوم]":
                raise ai_media.MediaError("unintelligible")
            return f"[پیام صوتی - متن خودکار]: {text}"
        if size > ai_media.MAX_IMAGE_BYTES:
            raise ai_media.MediaError("too_large")
        data = await client.download_media(msg, file=bytes)
        desc = await ai_media._image_text(
            db, data, getattr(info, "mime_type", None) or "image/jpeg", ai_media._IMAGE_PROMPT
        )
        if not desc:
            raise ai_media.MediaError("unreadable")
        return f"[تصویر ارسالی کاربر - توضیح خودکار]: {desc}"

    # ------------------------------------------------------------------ answering --------------------
    async def _answer(chat_id: int, entry: dict):
        sender = entry["sender"]
        sender_id = sender.id
        text = _clip("\n".join(entry["parts"]), MAX_INPUT)
        chat = await asyncio.to_thread(db.get_userbot_chat, chat_id)
        if chat is None or chat["mode"] == "human":
            return
        if not flag(db, KEY_ENABLED) or not schedule_allows(db) or paused_by_admin(db, chat_id):
            return

        async with _lock_for(chat_id):
            first = setting(db, KEY_FIRST_MESSAGE)
            if first and not chat["greeted"]:
                await asyncio.to_thread(db.mark_userbot_chat_greeted, chat_id)
                await _send(chat_id, first)
            history = await asyncio.to_thread(db.get_userbot_ai_conversation, chat_id)
            registered = bool(await asyncio.to_thread(db.get_user, sender_id))
            mode = ai_support.BUSINESS_USERBOT if flag(db, KEY_SALES_CARD) else ai_support.BUSINESS_USERBOT_PLAIN
            started = time.monotonic()
            try:
                async with client.action(chat_id, "typing"):
                    result = await ai_support.get_reply(
                        db, sender_id, history, text, business_mode=mode, extra_system=_extra_system(db, sender, history, registered),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("userbot AI reply failed for user %s", sender_id)
                await asyncio.to_thread(db.bump_userbot_stat, "errors")
                result = {"reply": FALLBACK_REPLY, "escalate": True}
            spent = time.monotonic() - started
            reply = _plain((result.get("reply") or "").strip())

            # The owner may have taken the chat over while the model was thinking: stay silent then.
            latest = await asyncio.to_thread(db.get_userbot_chat, chat_id)
            if latest is None or latest["mode"] == "human" or paused_by_admin(db, chat_id):
                return

            if reply:
                await _send_reply(chat_id, reply, spent)
                await asyncio.to_thread(db.add_userbot_ai_message, chat_id, "user", text)
                await asyncio.to_thread(db.add_userbot_ai_message, chat_id, "model", reply)
                await asyncio.to_thread(db.bump_userbot_chat_ai, chat_id)
                await asyncio.to_thread(db.bump_userbot_stat, "replies")
            if flag(db, KEY_MARK_READ):
                try:
                    own_ack[chat_id] = time.monotonic()
                    await client.send_read_acknowledge(chat_id, entry["msg"])
                except Exception:
                    logger.warning("userbot: read ack failed", exc_info=True)
            if result.get("escalate"):
                await _handoff(chat_id, sender, history, text, reply)
                return
            actions = result.get("ui_actions") or ([result["ui_action"]] if result.get("ui_action") else [])
            if actions:
                await _run_actions(chat_id, sender_id, actions)

    async def _drain(chat_id: int):
        """Waits until the customer stopped typing (debounce), then answers all buffered messages at once."""
        try:
            while True:
                entry = pending.get(chat_id)
                if entry is None:
                    return
                wait = entry["deadline"] - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                    continue
                pending.pop(chat_id, None)
                try:
                    await _answer(chat_id, entry)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("userbot answer failed (chat %s)", chat_id)
                    await asyncio.to_thread(db.bump_userbot_stat, "errors")
                if chat_id not in pending:
                    return
        finally:
            workers.discard(chat_id)

    def _enqueue(chat_id: int, sender, msg, text: str):
        now = time.monotonic()
        delay = max(0, int_setting(db, KEY_DEBOUNCE, 3))
        entry = pending.get(chat_id)
        if entry is None:
            entry = pending[chat_id] = {"parts": [], "first": now, "deadline": now}
        if len(entry["parts"]) < 10:
            entry["parts"].append(text)
        entry["sender"] = sender
        entry["msg"] = msg
        entry["deadline"] = min(now + delay, entry["first"] + MAX_BATCH_WAIT)
        if chat_id not in workers:
            workers.add(chat_id)
            _spawn(_drain(chat_id))

    async def _on_message(event):
        msg = event.message
        chat_id = event.chat_id
        sender_id = event.sender_id
        if not sender_id or sender_id == SERVICE_USER_ID or sender_id == ctx.get("me_id"):
            return
        leak_scanner.note_customer_activity()
        if _dup((chat_id, msg.id)):
            return
        if not flag(db, KEY_ENABLED):
            return
        if str(db.get_setting(global_switch.SETTING_KEY, "1")).strip() == "0":
            return
        text = (event.raw_text or "").strip()
        kind = _media_kind(msg)
        if not text and kind is None:
            return
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return
        if flag(db, KEY_SKIP_CONTACTS) and getattr(sender, "contact", False):
            return
        if db.is_admin(sender_id):
            return
        db_user = await asyncio.to_thread(db.get_user, sender_id)
        if db_user and db_user["is_blocked"]:
            return
        if await asyncio.to_thread(db.is_userbot_exception, sender_id):
            return

        chat = await asyncio.to_thread(
            db.touch_userbot_chat, chat_id, sender.first_name or "", sender.username or ""
        )
        if chat["mode"] == "human":
            return
        if not ai_support.is_configured(db) or not schedule_allows(db) or paused_by_admin(db, chat_id):
            return
        if _rate_limited(chat_id):
            return

        if kind in ("voice", "image") and flag(db, KEY_MEDIA_UNDERSTAND):
            try:
                media_text = await _media_to_text(msg, kind)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("userbot: media understanding failed: %s", exc)
                if not _cooldown("media_err", chat_id, 120):
                    await _send(chat_id, ai_media.error_text(exc))
                return
            await asyncio.to_thread(db.bump_userbot_stat, kind)
            text = f"{media_text}\n[متن همراه]: {text}" if text else media_text
        elif kind is not None and not text:
            if flag(db, KEY_MEDIA_ACK) and not _cooldown("media_ack", chat_id, MEDIA_COOLDOWN):
                await _send(chat_id, MEDIA_ACK_TEXT)
            return
        if not text:
            return
        await asyncio.to_thread(db.bump_userbot_stat, "incoming")
        _enqueue(chat_id, sender, msg, text)

    async def _owner_command(event, text: str):
        """`.ai off` / `.ai on` typed by the owner inside a customer chat. The command message is deleted."""
        chat_id = event.chat_id
        if chat_id == ctx.get("me_id"):
            return
        turn_on = text == ".ai on"
        try:
            chat = await event.get_chat()
        except Exception:
            chat = None
        first_name = (getattr(chat, "first_name", "") or "") if chat else ""
        username = (getattr(chat, "username", "") or "") if chat else ""
        pending.pop(chat_id, None)
        if turn_on:
            STATE["chat_active"].pop(chat_id, None)
            await asyncio.to_thread(db.set_userbot_chat_mode, chat_id, "auto", first_name, username)
            await asyncio.to_thread(db.clear_userbot_ai_conversation, chat_id)
        else:
            await asyncio.to_thread(db.set_userbot_chat_mode, chat_id, "human", first_name, username)
        try:
            await event.delete()
        except Exception:
            logger.warning("userbot: could not delete the command message", exc_info=True)
        label = f"{first_name} (@{username})" if username else (first_name or str(chat_id))
        await _notify_admins(
            (tr("✅ هوش مصنوعی در این چت روشن شد") if turn_on else tr("🔇 هوش مصنوعی در این چت خاموش شد"))
            + f": {html.escape(label)}"
        )

    async def _on_outgoing(event):
        if not event.is_private:
            return
        if event.message.id in own_ids:
            return
        text = (event.raw_text or "").strip().lower()
        if text in (".ai on", ".ai off"):
            await _owner_command(event, text)
            return
        last = own_send.get(event.chat_id)
        if last is None or time.monotonic() - last >= SELF_ECHO_WINDOW:
            mark_admin_active(event.chat_id)

    async def _on_read(event):
        chat_id = getattr(event, "chat_id", None)
        last = own_ack.get(chat_id)
        if last is None or time.monotonic() - last >= SELF_ECHO_WINDOW:
            mark_admin_active(chat_id)

    def _safe(fn):
        async def wrapper(event):
            try:
                await fn(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                STATE["last_error"] = f"{fn.__name__} failed"
                logger.exception("userbot handler %s failed (chat %s)", fn.__name__, getattr(event, "chat_id", None))
        return wrapper

    async def _maintenance():
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            try:
                hours = int_setting(db, KEY_HUMAN_TTL, 0)
                if hours > 0:
                    await asyncio.to_thread(db.expire_userbot_human_chats, hours)
            except Exception:
                logger.warning("userbot: maintenance failed", exc_info=True)

    client.add_event_handler(_safe(_on_message), events.NewMessage(incoming=True, func=lambda e: e.is_private))
    client.add_event_handler(_safe(_on_outgoing), events.NewMessage(outgoing=True))
    client.add_event_handler(_safe(_on_read), events.MessageRead(inbox=True))
    maintenance_task = asyncio.create_task(_maintenance())
    leak_started = False

    try:
        while True:
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError("AuthKeyUnregisteredError")
                me = await client.get_me()
                ctx["me_id"] = me.id
                if not leak_started and not os.path.exists(scanner_session_path()):
                    # اسکنر تشخیص نشت روی همین کلاینت و همین سشن یوزربات کار می‌کند
                    leak_started = True
                    _spawn(leak_scanner.run(client, db, bot))
                STATE["me"] = {"id": me.id, "first_name": me.first_name or "", "username": me.username or ""}
                STATE["connected"] = True
                STATE["connected_at"] = time.time()
                STATE["last_error"] = ""
                logger.info("userbot connected as %s (@%s)", me.id, me.username)
                await client.run_until_disconnected()
                STATE["connected"] = False
                logger.warning("userbot disconnected; reconnecting in %ss", RETRY_DELAY)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                STATE["connected"] = False
                STATE["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
                if type(exc).__name__ in AUTH_LOST_ERRORS or "AuthKeyUnregisteredError" in str(exc):
                    logger.error("userbot session is no longer valid: %s", exc)
                    await _notify_admins(
                        "⚠️ Telegram userbot session is no longer valid. "
                        "Log in again from the server menu (Telegram userbot login)."
                    )
                    return
                logger.warning("userbot error: %s; retrying in %ss", exc, RETRY_DELAY, exc_info=True)
            await asyncio.sleep(RETRY_DELAY)
    finally:
        STATE["connected"] = False
        maintenance_task.cancel()
        for task in list(tasks):
            task.cancel()
        try:
            await client.disconnect()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass


def _cli(argv) -> int:
    argv = list(argv)
    if "--db" in argv:
        # سشن مخصوص یک نمایندگی کامل: python userbot.py login --db <مسیر دیتابیس نماینده>
        idx = argv.index("--db")
        try:
            db_arg = argv[idx + 1]
        except IndexError:
            print("usage: --db <path to the reseller database file>")
            return 2
        del argv[idx:idx + 2]

        class _P:
            db_path = db_arg
        tenant_ctx.use(_P())
    cmd = argv[0] if argv else ""
    if cmd == "login":
        return 0 if asyncio.run(interactive_login()) else 1
    if cmd == "logout":
        asyncio.run(logout())
        print("Userbot session removed.")
        return 0
    if cmd == "status":
        creds = load_session()
        if creds is None:
            print("not logged in")
            return 1
        user = creds["user"]
        print(f"logged in: {user.get('first_name', '')} (@{user.get('username') or '-'}) id={user.get('id')}")
        return 0
    if cmd == "login-scanner":
        return 0 if asyncio.run(interactive_login(scanner_session_path())) else 1
    if cmd == "logout-scanner":
        asyncio.run(logout(scanner_session_path()))
        print("Scanner session removed (the scanner falls back to the userbot account).")
        return 0
    if cmd == "status-scanner":
        creds = load_session(scanner_session_path())
        if creds is None:
            print("no dedicated scanner account (the scanner uses the userbot account)")
            return 1
        user = creds["user"]
        print(f"scanner account: {user.get('first_name', '')} (@{user.get('username') or '-'}) id={user.get('id')}")
        return 0
    print("usage: userbot.py login|logout|status|login-scanner|logout-scanner|status-scanner")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
