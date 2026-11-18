# -*- coding: utf-8 -*-
"""اسکنر تشخیص نشت روی سشن یوزربات (Telethon).

کار این ماژول:
  1. پارس لینک‌های vless / vmess / trojan / ss و لینک اشتراک داخل متن پست‌ها.
  2. هش کردن مقدارهای استخراج‌شده و تطبیق با credential_index (بدون ذخیره‌ی متن خام).
  3. اسکن کانال‌های فهرست‌شده برای پست‌های جدید + جستجوی سراسری با کلیدواژه‌ها.
  4. ثبت رویداد نشت و هشدار به ادمین؛ چرخاندن لینک، اخطار (با یا بدون ابطال خودکار).

اسکنر روی همان کلاینت و سشن یوزربات اجرا می‌شود (userbot.run آن را راه می‌اندازد).

محافظت از اکانت مشترک با یوزربات:
  * سقف درخواست در دقیقه (leak_max_requests_per_minute) و فاصله‌ی تصادفی بین درخواست‌ها.
  * توقف کامل هنگام FloodWait تلگرام.
  * اولویت با مشتری: تا چند ثانیه بعد از هر پیام ورودی مشتری، اسکنر درخواستی نمی‌فرستد.
  * کلید خاموش/روشن جدا از پاسخگوی هوش مصنوعی (leak_scanner_enabled).

نکته: این ماژول در زمان import به telethon و aiogram وابسته نیست؛ آن‌ها فقط داخل توابعی
که واقعاً نیاز دارند import می‌شوند تا تست‌های خالص بدون آن‌ها اجرا شوند.
"""

import asyncio
import base64
import binascii
import html
import json
import logging
import random
import re
import time
from collections import deque
from urllib.parse import unquote

import leak_discovery as ld
import tenant_ctx
import leak_index
from panel_providers import get_provider
from panel_providers.base import PanelError, subscription_token

logger = logging.getLogger(__name__)

KEY_ENABLED = "leak_scanner_enabled"
KEY_AUTO_REVOKE = "leak_auto_revoke"
KEY_WARN_THRESHOLD = "leak_warn_threshold"
KEY_MAX_PER_MIN = "leak_max_requests_per_minute"
KEY_SCAN_MINUTES = "leak_scan_interval_minutes"
KEY_KEYWORDS = "leak_keywords"

DEFAULTS = {
    KEY_ENABLED: "0",
    KEY_AUTO_REVOKE: "0",
    KEY_WARN_THRESHOLD: "3",
    KEY_MAX_PER_MIN: "6",
    KEY_SCAN_MINUTES: "15",
    KEY_KEYWORDS: "vless,vmess,trojan,shadowsocks",
}

CUSTOMER_QUIET_SECONDS = 15.0
MIN_GAP_SECONDS = 2.0
MAX_FLOOD_PAUSE_SECONDS = 1800
MIN_SECRET_LEN = leak_index.MIN_SECRET_LEN

# وضعیت مشترک بین حلقه‌ی اسکن و منوی ادمین
def _new_state() -> dict:
    return {
        "client": None, "paused_until": 0.0, "stamps": deque(), "last_flood": 0,
        "discovery": None, "realtime_handlers": [],
        # کش فهرست کانال‌های زیر نظر برای هندلر لحظه‌ای (بدون خواندن دیتابیس در هر پیام)
        "watched": {}, "watched_at": 0.0, "scanner_on": False,
    }


# هر بات (اصلی یا نمایندگی کامل) STATE مستقل خودش را دارد (انتخاب با tenant_ctx.CURRENT).
STATE = tenant_ctx.PerTenant(_new_state)
WATCH_CACHE_SECONDS = 60
MAX_CHANNELS_PER_CYCLE = 40
JOINED_CATCHUP_FACTOR = 4


# ---------------------------------------------------------------- settings helpers
def setting(db, key: str) -> str:
    return str(db.get_setting(key, DEFAULTS.get(key, "")) or "").strip()


def flag(db, key: str) -> bool:
    return setting(db, key) == "1"


def int_setting(db, key: str, default: int) -> int:
    try:
        return int(setting(db, key) or default)
    except (TypeError, ValueError):
        return default


def keywords(db) -> list:
    return [k.strip() for k in setting(db, KEY_KEYWORDS).split(",") if k.strip()]


_CUSTOMER_ACTIVITY = tenant_ctx.PerTenant(lambda: {"t": 0.0})


def note_customer_activity() -> None:
    """userbot وقتی پیام مشتری می‌رسد صدا می‌زند تا اسکنر کمی عقب بکشد."""
    _CUSTOMER_ACTIVITY["t"] = time.monotonic()


def get_client():
    """کلاینت Telethon زنده‌ی یوزربات (یا None اگر متصل نیست)."""
    client = STATE["client"]
    if client is None or not client.is_connected():
        return None
    return client


# ---------------------------------------------------------------- parsing
LINK_RE = re.compile(
    r"\b(?:vless|vmess|trojan|ss|hysteria2|hy2|tuic)://[^\s<>\"'`]+|\bhttps?://[^\s<>\"'`]+", re.IGNORECASE,
)


def _b64decode(text: str) -> str:
    cleaned = (text or "").strip().replace("-", "+").replace("_", "/")
    cleaned += "=" * (-len(cleaned) % 4)
    return base64.b64decode(cleaned, validate=True).decode("utf-8")


def _parse_link(link: str) -> list:
    scheme, _, rest = link.partition("://")
    scheme = scheme.lower()
    body = rest.split("#", 1)[0]

    if scheme in ("vless", "trojan"):
        if "@" not in body:
            return []
        userinfo = unquote(body.split("@", 1)[0]).strip()
        if not userinfo:
            return []
        return [("uuid" if scheme == "vless" else "password", userinfo)]

    if scheme == "vmess":
        data = json.loads(_b64decode(body))
        value = str(data.get("id") or "").strip()
        return [("uuid", value)] if value else []

    if scheme == "ss":
        core = body.split("?", 1)[0]
        if "@" in core:
            userinfo = core.rsplit("@", 1)[0]
            try:
                decoded = _b64decode(userinfo)          # SIP002: base64(method:password)@host
            except (binascii.Error, ValueError, UnicodeDecodeError):
                decoded = unquote(userinfo)             # method:password بدون base64
        else:
            decoded = _b64decode(core).rsplit("@", 1)[0]  # قالب قدیمی: base64(method:password@host:port)
        if ":" not in decoded:
            return []
        password = decoded.split(":", 1)[1]
        return [("password", password)] if password else []

    if scheme in ("hysteria2", "hy2"):
        if "@" not in body:
            return []
        auth = unquote(body.split("@", 1)[0]).strip()
        return [("password", auth)] if auth else []

    if scheme == "tuic":
        if "@" not in body:
            return []
        userinfo = unquote(body.split("@", 1)[0]).strip()
        uuid, _, password = userinfo.partition(":")
        return [pair for pair in (("uuid", uuid), ("password", password)) if pair[1]]

    if scheme in ("http", "https"):
        token = subscription_token(link)
        return [("token", token)] if token else []

    return []


def extract_secrets(text: str) -> list:
    """[(kind, value)] از همه‌ی لینک‌های یک متن. لینک‌های خراب بی‌صدا رد می‌شوند."""
    found = []
    for match in LINK_RE.finditer(text or ""):
        link = match.group(0).rstrip(".,;:!?)]}>")
        try:
            found.extend(_parse_link(link))
        except Exception:
            continue
    return [(kind, value) for kind, value in found if len(leak_index.normalize_secret(value)) >= MIN_SECRET_LEN]


def match_secrets(db, secrets) -> list:
    """تطبیق هش مقدارها با ایندکس. یک ردیف به ازای هر سرویس تطبیق‌خورده."""
    hashes = {}
    for kind, value in secrets:
        hashes.setdefault(leak_index.fingerprint_hash(value), kind)
    if not hashes:
        return []
    matches = {}
    for row in db.lookup_credential_hashes(list(hashes)):
        matches.setdefault(row["config_id"], {
            "config_id": row["config_id"],
            "user_id": row["user_id"],
            "panel_server_id": row["panel_server_id"],
            "username": row["username"],
            "kind": hashes.get(row["hash"], row["kind"]),
        })
    return list(matches.values())


def post_link(username: str, channel_id: int, post_id: int) -> str:
    if username:
        return f"https://t.me/{username}/{post_id}"
    return f"https://t.me/c/{channel_id}/{post_id}"


# ---------------------------------------------------------------- alerts & actions
KIND_LABELS = {"uuid": "UUID", "password": "پسورد پروتکل", "token": "توکن اشتراک"}


def _alert_text(db, event, status_line: str = "") -> str:
    from report_router import user_link

    lines = [
        "🚨 <b>نشت احتمالی کانفیگ</b>",
        f"👤 کاربر: {user_link(event['user_id'])}",
        f"🧾 سرویس: <code>{html.escape(str(event['config_username'] or '-'))}</code>",
        f"📢 کانال: {html.escape(event['channel_title'] or '-')}",
        f"🔗 پست: {html.escape(event['post_link'])}",
        f"🔎 تطبیق: {KIND_LABELS.get(event['matched_kind'], 'نامشخص')}",
    ]
    if status_line:
        lines += ["", status_line]
    return "\n".join(lines)


def _alert_markup(event_id: int, status: str):
    if status != "new" and status != "warned":
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 چرخاندن لینک", callback_data=f"lk:rot:{event_id}")],
        [
            InlineKeyboardButton(text="⚠️ اخطار", callback_data=f"lk:warn:{event_id}"),
            InlineKeyboardButton(text="🙈 نادیده", callback_data=f"lk:ign:{event_id}"),
        ],
    ])


def _event_with_service(db, event_id: int):
    """رویداد به‌همراه نام کاربری سرویس (برای متن هشدار)."""
    event = db.get_leak_event(event_id)
    if not event:
        return None
    cc = db.get_custom_config_by_id(event["config_id"])
    data = dict(event)
    data["config_username"] = cc["username"] if cc else ""
    return data


async def send_alert(db, bot, event_id: int, status_line: str = "") -> None:
    from report_router import report

    event = await asyncio.to_thread(_event_with_service, db, event_id)
    if not event:
        return
    text = _alert_text(db, event, status_line)
    try:
        await report(bot, db, "leak", text, reply_markup=_alert_markup(event_id, event["status"]))
    except Exception:
        logger.warning("leak alert %s could not be delivered", event_id, exc_info=True)


async def _notify_user_rotated(bot, db, user_id: int, url: str) -> None:
    from notification_i18n import localized, user_language

    template = (
        "🔐 به‌دلیل احتمال افشای لینک اشتراک شما، دسترسی قبلی قطع شد و لینک جدید صادر شد.\n"
        "لطفاً لینک جدید را در برنامه‌ی خود جایگزین کنید:"
    )
    try:
        text = localized(template, db, user_id, user_language(db, user_id))
        body = f"{html.escape(text)}\n<code>{html.escape(url)}</code>" if url else html.escape(text)
        await bot.send_message(user_id, body, parse_mode="HTML")
    except Exception:
        logger.warning("could not notify user %s about rotated link", user_id, exc_info=True)


async def rotate_event(db, bot, event_id: int, actor: str = "admin") -> tuple:
    """لینک سرویس مربوط به رویداد را باطل و لینک تازه صادر می‌کند. (ok, پیام برای ادمین)"""
    event = await asyncio.to_thread(db.get_leak_event, event_id)
    if not event:
        return False, "رویداد پیدا نشد."
    if event["status"] == "rotated":
        return False, "این لینک قبلاً چرخانده شده است."
    cc = await asyncio.to_thread(db.get_custom_config_by_id, event["config_id"])
    if not cc or cc["status"] != "active":
        return False, "این سرویس دیگر فعال نیست."
    server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
    if not server or not server["is_active"]:
        return False, "سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است."
    try:
        provider = get_provider(server)
        result = await provider.revoke_credentials(cc["username"])
    except PanelError as exc:
        return False, f"قطع دسترسی ناموفق بود: {exc}"
    if result.subscription_url:
        await asyncio.to_thread(db.update_custom_config_subscription_url, cc["id"], result.subscription_url)
    await asyncio.to_thread(
        db.add_custom_config_history, cc["id"], "leak_rotated", f"لینک به‌دلیل نشت باطل شد ({actor})",
    )
    await asyncio.to_thread(db.set_leak_event_status, event_id, "rotated")
    try:
        await leak_index.refresh_config(db, cc["id"])
    except Exception:
        logger.warning("leak index refresh after rotation failed", exc_info=True)
    await _notify_user_rotated(bot, db, event["user_id"], result.subscription_url or "")
    return True, "لینک جدید صادر و برای کاربر ارسال شد."


async def warn_event(db, bot, event_id: int) -> tuple:
    """اخطار به کاربر؛ بعد از رسیدن به سقف، کاربر مسدود می‌شود. (ok, پیام برای ادمین)"""
    from notification_i18n import localized, user_language

    event = await asyncio.to_thread(db.get_leak_event, event_id)
    if not event:
        return False, "رویداد پیدا نشد."
    if not await asyncio.to_thread(db.mark_leak_event_warned, event_id):
        return False, "برای این رویداد قبلاً اخطار ثبت شده است."
    count = await asyncio.to_thread(db.count_user_leak_warnings, event["user_id"])
    threshold = int_setting(db, KEY_WARN_THRESHOLD, 3)
    blocked = threshold > 0 and count >= threshold
    if blocked:
        await asyncio.to_thread(db.set_user_blocked, event["user_id"], True)
    try:
        template = (
            "⚠️ لینک اشتراک شما در یک کانال عمومی دیده شده است. "
            "لطفاً آن را محرمانه نگه دارید؛ تکرار این موضوع منجر به مسدود شدن حساب می‌شود."
        )
        await bot.send_message(
            event["user_id"],
            html.escape(localized(template, db, event["user_id"], user_language(db, event["user_id"]))),
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("could not send warning to user %s", event["user_id"], exc_info=True)
    msg = f"اخطار ثبت شد ({count}/{threshold})."
    if blocked:
        msg += " کاربر به‌دلیل رسیدن به سقف اخطار مسدود شد."
    return True, msg


# ---------------------------------------------------------------- scanner
async def _handle_post(db, bot, text: str, channel_id: int, channel_title: str, channel_username: str, post_id: int) -> int:
    matches = match_secrets(db, extract_secrets(text))
    created = 0
    for match in matches:
        link = post_link(channel_username, channel_id, post_id)
        event_id = await asyncio.to_thread(
            db.create_leak_event, match["user_id"], match["config_id"], channel_id,
            channel_title, link, match["kind"],
        )
        if event_id is None:
            continue
        created += 1
        status_line = ""
        if flag(db, KEY_AUTO_REVOKE):
            ok, msg = await rotate_event(db, bot, event_id, actor="خودکار")
            status_line = "🔄 لینک به‌صورت خودکار چرخانده شد." if ok else f"⚠️ چرخاندن خودکار ناموفق: {msg}"
        await send_alert(db, bot, event_id, status_line)
    await _learn_from_post(db, text, channel_id, channel_title, channel_username, created)
    return created


async def _learn_from_post(db, text: str, channel_id: int, title: str, username: str, created: int) -> None:
    """آمار کانال، دنبال‌کردن لینک‌ها و کاندیداکردن کانالی که نشت از آن آمده (بدون درخواست به تلگرام)."""
    try:
        has_config = 1 if ld.count_config_links(text) else 0
        await asyncio.to_thread(db.bump_leak_channel_stats, channel_id, has_config, created)
        if not ld.flag(db, ld.KEY_ENABLED):
            return
        await asyncio.to_thread(ld.collect_refs, db, text, f"crawl:{(username or title or channel_id)}")
        if has_config or created:
            key = f"u:{username.lower()}" if username else f"c:{channel_id}"
            await asyncio.to_thread(
                db.upsert_leak_candidate, key, channel_id, username or "", "", title or "", 0, "",
                "leak_hit" if created else "config_seen", "", 20 if created else 1,
            )
    except Exception:
        logger.debug("leak learn from post failed", exc_info=True)


class LeakScanner:
    def __init__(self, client, db, bot):
        self.client = client
        self.db = db
        self.bot = bot

    async def _acquire(self) -> None:
        """سهمیه‌ی دقیقه‌ای، اولویت مشتری و توقف FloodWait را رعایت می‌کند و بعد یک فاصله‌ی تصادفی می‌دهد."""
        while True:
            now = time.monotonic()
            if now < STATE["paused_until"]:
                await asyncio.sleep(min(STATE["paused_until"] - now, 60))
                continue
            quiet_for = now - _CUSTOMER_ACTIVITY["t"]
            if quiet_for < CUSTOMER_QUIET_SECONDS:
                await asyncio.sleep(CUSTOMER_QUIET_SECONDS - quiet_for)
                continue
            stamps = STATE["stamps"]
            while stamps and now - stamps[0] > 60:
                stamps.popleft()
            limit = max(int_setting(self.db, KEY_MAX_PER_MIN, 6), 1)
            if len(stamps) < limit:
                stamps.append(now)
                break
            await asyncio.sleep(60 - (now - stamps[0]) + 0.5)
        await asyncio.sleep(random.uniform(MIN_GAP_SECONDS, MIN_GAP_SECONDS * 2.5))

    async def _call(self, factory):
        """یک درخواست به تلگرام؛ اگر FloodWait بود، کل اسکن را تا پایان مهلت متوقف می‌کند."""
        from telethon.errors import FloodWaitError

        await self._acquire()
        try:
            return await factory()
        except FloodWaitError as exc:
            STATE["last_flood"] = int(exc.seconds or 60)
            pause = min(int(exc.seconds or 60), MAX_FLOOD_PAUSE_SECONDS)
            STATE["paused_until"] = time.monotonic() + pause
            logger.warning("leak scanner paused for %ss by FloodWait", pause)
            return None

    async def scan_channels(self) -> None:
        from telethon.tl.types import PeerChannel

        interval = max(int_setting(self.db, KEY_SCAN_MINUTES, 15), 1) * 60
        now = time.time()
        due = []
        for ch in await asyncio.to_thread(self.db.list_active_leak_channels):
            # کانال‌هایی که یوزربات عضوشان است لحظه‌ای پایش می‌شوند؛ پیمایش دوره‌ای فقط جبران خاموشی است.
            gap = interval * (JOINED_CATCHUP_FACTOR if ch["joined"] else 1)
            last = float(ch["last_scan_ts"] or 0)
            if now - last >= gap * 0.9:
                due.append((last, ch))
        due.sort(key=lambda item: item[0])

        for _, ch in due[:MAX_CHANNELS_PER_CYCLE]:
            try:
                entity = await self.client.get_entity(PeerChannel(ch["channel_id"]))
            except Exception:
                logger.info("leak scanner: channel %s could not be resolved", ch["channel_id"])
                await asyncio.to_thread(self.db.set_leak_channel_scanned, ch["channel_id"], time.time())
                continue
            title = getattr(entity, "title", "") or ch["title"]
            username = getattr(entity, "username", "") or ch["username"] or ""
            last_seen = ch["last_post_id"] or 0

            if not last_seen:
                # اولین بار: فقط نقطه‌ی شروع ثبت می‌شود؛ تاریخچه‌ی قدیمی اسکن نمی‌شود.
                latest = await self._call(lambda: self.client.get_messages(entity, limit=1))
                if latest:
                    await asyncio.to_thread(self.db.set_leak_channel_last_post, ch["channel_id"], latest[0].id)
                await asyncio.to_thread(self.db.set_leak_channel_scanned, ch["channel_id"], time.time())
                continue

            messages = await self._call(
                lambda: self.client.get_messages(entity, limit=100, min_id=last_seen)
            )
            await asyncio.to_thread(self.db.set_leak_channel_scanned, ch["channel_id"], time.time())
            if not messages:
                continue
            newest = last_seen
            for msg in sorted(messages, key=lambda m: m.id):
                newest = max(newest, msg.id)
                if not await asyncio.to_thread(self.db.mark_leak_post_seen, ch["channel_id"], msg.id):
                    continue
                await _handle_post(
                    self.db, self.bot, ld.message_text(msg),
                    ch["channel_id"], title, username, msg.id,
                )
            await asyncio.to_thread(self.db.set_leak_channel_last_post, ch["channel_id"], newest)

    async def global_search(self, keyword: str) -> None:
        from telethon.tl.functions.messages import SearchGlobalRequest
        from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty

        result = await self._call(lambda: self.client(SearchGlobalRequest(
            q=keyword, filter=InputMessagesFilterEmpty(), min_date=None, max_date=None,
            offset_rate=0, offset_peer=InputPeerEmpty(), offset_id=0, limit=50,
        )))
        if result is None:
            return
        chats = {c.id: c for c in getattr(result, "chats", [])}
        for msg in getattr(result, "messages", []) or []:
            channel_id = getattr(getattr(msg, "peer_id", None), "channel_id", None)
            if not channel_id:
                continue
            if not await asyncio.to_thread(self.db.mark_leak_post_seen, channel_id, msg.id):
                continue
            chat = chats.get(channel_id)
            await _handle_post(
                self.db, self.bot, ld.message_text(msg), channel_id,
                getattr(chat, "title", "") or "", getattr(chat, "username", "") or "", msg.id,
            )

    async def loop(self) -> None:
        while True:
            try:
                if not flag(self.db, KEY_ENABLED):
                    await asyncio.sleep(60)
                    continue
                if self.client.is_connected():
                    await self.scan_channels()
                    for word in keywords(self.db):
                        if not flag(self.db, KEY_ENABLED):
                            break
                        await self.global_search(word)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("leak scanner cycle failed", exc_info=True)
            minutes = max(int_setting(self.db, KEY_SCAN_MINUTES, 15), 1)
            await asyncio.sleep(minutes * 60 * random.uniform(0.9, 1.2))


async def _watch_cache(db) -> dict:
    """{channel_id: (title, username)} کانال‌های فعال + روشن‌بودن اسکنر؛ هر ۶۰ ثانیه از دیتابیس تازه می‌شود."""
    now = time.monotonic()
    if now - STATE["watched_at"] > WATCH_CACHE_SECONDS or STATE["watched_at"] == 0.0:
        rows = await asyncio.to_thread(db.list_active_leak_channels)
        STATE["watched"] = {r["channel_id"]: (r["title"], r["username"]) for r in rows}
        STATE["scanner_on"] = flag(db, KEY_ENABLED)
        STATE["watched_at"] = now
    return STATE["watched"] if STATE["scanner_on"] else {}


def install_realtime(client, db, bot) -> None:
    """پایش لحظه‌ای: پست تازه و ویرایش‌شده‌ی کانال‌های عضو‌شده بدون هیچ درخواست اضافه بررسی می‌شود."""
    from telethon import events

    async def _process(event, edited: bool) -> None:
        msg = event.message
        channel_id = getattr(getattr(msg, "peer_id", None), "channel_id", None)
        if not channel_id:
            return
        watched = await _watch_cache(db)
        if channel_id not in watched:
            return
        text = ld.message_text(msg)
        if not text or not any(mark in text for mark in ("://", "t.me/", "@")):
            return
        # پست ویرایش‌شده دوباره بررسی می‌شود (کانفیگ را گاهی بعداً ویرایش می‌کنند)؛ یکتایی رویداد جلوی تکرار را می‌گیرد.
        if not edited and not await asyncio.to_thread(db.mark_leak_post_seen, channel_id, msg.id):
            return
        title, username = watched[channel_id]
        await _handle_post(db, bot, text, channel_id, title or "", username or "", msg.id)

    async def on_new(event):
        try:
            await _process(event, edited=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("leak realtime handler failed", exc_info=True)

    async def on_edit(event):
        try:
            await _process(event, edited=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("leak realtime edit handler failed", exc_info=True)

    new_filter = events.NewMessage(incoming=True, func=lambda e: not e.is_private)
    edit_filter = events.MessageEdited(incoming=True, func=lambda e: not e.is_private)
    client.add_event_handler(on_new, new_filter)
    client.add_event_handler(on_edit, edit_filter)
    STATE["realtime_handlers"] = [(on_new, new_filter), (on_edit, edit_filter)]


def _remove_realtime(client) -> None:
    for handler, event_filter in STATE["realtime_handlers"]:
        try:
            client.remove_event_handler(handler, event_filter)
        except Exception:
            pass
    STATE["realtime_handlers"] = []


async def run(client, db, bot) -> None:
    """از userbot.run، بعد از اتصال موفق یوزربات صدا زده می‌شود و تا قطع شدن آن ادامه دارد."""
    STATE["client"] = client
    STATE["watched_at"] = 0.0
    scanner = LeakScanner(client, db, bot)
    discovery = ld.Discovery(client, db, bot, scanner._call, _handle_post, STATE)
    STATE["discovery"] = discovery
    tasks = []
    try:
        install_realtime(client, db, bot)
        tasks = [asyncio.create_task(scanner.loop()), asyncio.create_task(discovery.loop())]
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        _remove_realtime(client)
        STATE["client"] = None
        STATE["discovery"] = None


async def run_dedicated(db, bot_token: str) -> None:
    """اسکنر روی اکانت اختصاصی (leak_session.json)، مستقل از اکانت پاسخ‌گوی مشتری.

    بدون آن فایل هیچ کاری نمی‌کند (اسکنر در این حالت از userbot.run روی اکانت یوزربات اجرا می‌شود).
    با پیدا شدن فایل (بعد از login-scanner) خودکار شروع می‌شود؛ ری‌استارت لازم نیست.
    """
    import userbot

    tenant_ctx.use(db)  # نمایندگی کامل: سشن و STATE مستقل (داخل همین تسک)
    while userbot.load_session(userbot.scanner_session_path()) is None:
        await asyncio.sleep(30)
    creds = userbot.load_session(userbot.scanner_session_path())
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
    except ImportError:
        logger.warning("leak scanner account found but telethon/aiogram is not installed")
        return
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    client = TelegramClient(StringSession(creds["session"]), creds["api_id"], creds["api_hash"], flood_sleep_threshold=60)
    client.parse_mode = None
    try:
        while True:
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    logger.error("leak scanner account session is no longer valid; run: python userbot.py login-scanner")
                    return
                await run(client, db, bot)   # تا قطع شدن اتصال ادامه دارد
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("leak scanner account error; retrying", exc_info=True)
            await asyncio.sleep(30)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass


async def add_channel(client, db, ident: str) -> str:
    """کانال را با @username یا لینک t.me یا شناسه‌ی عددی اضافه می‌کند؛ عنوان آن را برمی‌گرداند."""
    from telethon.tl.types import PeerChannel

    ident = (ident or "").strip()
    ident = re.sub(r"^(?:https?://)?t\.me/(?:s/)?", "", ident).strip("/").split("/")[0]
    if not ident:
        raise ValueError("شناسه‌ی کانال خالی است.")
    if ident.lstrip("-").isdigit():
        entity = await client.get_entity(PeerChannel(abs(int(ident))))
    else:
        entity = await client.get_entity(ident if ident.startswith("@") else f"@{ident}")
    if not getattr(entity, "broadcast", False) and not getattr(entity, "megagroup", False):
        raise ValueError("این شناسه کانال یا گروه نیست.")
    latest = await client.get_messages(entity, limit=1)
    last_id = latest[0].id if latest else 0
    title = getattr(entity, "title", "") or str(entity.id)
    username = getattr(entity, "username", "") or ""
    await asyncio.to_thread(db.add_leak_channel, entity.id, title, username, last_id)
    STATE["watched_at"] = 0.0
    return title

