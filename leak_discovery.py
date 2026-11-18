# -*- coding: utf-8 -*-
"""کشف و عضویت هوشمند برای اسکنر تشخیص نشت.

اسکنر قبلاً فقط کانال‌هایی را می‌خواند که ادمین دستی اضافه می‌کرد. این ماژول خودش دنبال
کانال و گروه‌های تازه می‌گردد:

  1. جستجو در تلگرام (contacts.Search) با کلیدواژه‌های فارسی/انگلیسی/روسی/چینی. کلیدواژه‌ها
     یاد می‌گیرند: هر کلیدواژه که کاندیدای خوب بیاورد زودتر دوباره اجرا می‌شود و از عنوان
     کانال‌های خوب کلیدواژه‌ی تازه ساخته می‌شود.
  2. دنبال‌کردن لینک‌ها (snowball): لینک t.me / @username / لینک دعوت داخل پست‌ها و
     توضیح کانال‌ها و نتایج جستجوی سراسری به‌عنوان کاندیدا ثبت می‌شود.
  3. ارزیابی قبل از عضویت: آخرین پست‌ها بدون عضویت خوانده می‌شود (کانال عمومی)، تراکم
     کانفیگ، تازگی، نرخ پست، ارتباط عنوان و تعداد عضو امتیاز می‌گیرد. همان پست‌ها هم برای
     نشت اسکن می‌شوند.
  4. عضویت محتاطانه: سقف روزانه و سقف کل، فاصله‌ی تصادفی، توقف کامل هنگام FloodWait،
     و حالت «تأیید ادمین» یا «فقط پایش بدون عضویت».
  5. پاک‌سازی: کانالی که خود اسکنر عضو شده و بعد از چند روز هیچ کانفیگ/نشتی نداشته، ترک می‌شود.
     هرگز کانالی که از قبل عضو آن بوده‌اید (و اسکنر عضوش نکرده) ترک نمی‌شود.

این ماژول در زمان import به telethon/aiogram وابسته نیست؛ بخش‌های تلگرامی فقط داخل
متدها import می‌کنند، و منطق تصمیم‌گیری (امتیاز، انتخاب کلیدواژه، سقف عضویت، استخراج لینک)
تابع‌های خالص است که جداگانه تست می‌شود.
"""

import asyncio
import html
import logging
import math
import random
import re
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCANNER_ENABLED_KEY = "leak_scanner_enabled"
KEY_ENABLED = "leak_discovery_enabled"
KEY_JOIN_MODE = "leak_join_mode"            # auto | approve | watch
KEY_DAILY_JOINS = "leak_daily_join_cap"
KEY_MAX_JOINED = "leak_max_joined"
KEY_MIN_SCORE = "leak_min_score"
KEY_CRAWL = "leak_crawl_links"
KEY_AUTO_LEAVE = "leak_auto_leave"
KEY_NOTIFY = "leak_notify_joins"
KEY_INTERVAL = "leak_discovery_interval_minutes"

JOIN_MODES = ("auto", "approve", "watch")

DEFAULTS = {
    KEY_ENABLED: "0",
    KEY_JOIN_MODE: "auto",
    KEY_DAILY_JOINS: "5",
    KEY_MAX_JOINED: "100",
    KEY_MIN_SCORE: "35",
    KEY_CRAWL: "1",
    KEY_AUTO_LEAVE: "1",
    KEY_NOTIFY: "1",
    KEY_INTERVAL: "30",
}

QUERIES_PER_CYCLE = 3
EVALUATE_PER_CYCLE = 5
JOINS_PER_CYCLE = 2
LEAVES_PER_CYCLE = 2
SAMPLE_SIZE = 40
MIN_SAMPLE_FOR_VERDICT = 5
SEARCH_LIMIT = 40
MAX_REFS_PER_POST = 15
MAX_LEARNED_QUERIES = 80
PRUNE_AFTER_DAYS = 14
PRUNE_MIN_CONFIG_POSTS = 5
JOIN_DELAY = (45.0, 120.0)
QUERY_BASE_GAP_HOURS = 6.0
QUERY_MAX_GAP_HOURS = 24.0 * 7
DEFAULT_JOIN_PAUSE = 3600
CHANNELS_FULL_PAUSE = 86400

SEED_QUERIES = [
    # فارسی
    "کانفیگ", "کانفیگ رایگان", "کانفیگ v2ray", "کانال کانفیگ", "گروه کانفیگ", "فیلترشکن", "فیلتر شکن",
    "فیلترشکن رایگان", "پروکسی", "پروکسی رایگان", "پروکسی تلگرام", "اینترنت رایگان", "نت رایگان",
    "اشتراک رایگان", "ساب لینک", "وی پی ان", "وی‌پی‌ان رایگان", "دانلود کانفیگ",
    # انگلیسی
    "v2ray", "v2rayng", "vless", "vmess", "trojan", "shadowsocks", "xray", "reality", "hiddify",
    "sing-box", "clash", "free v2ray", "free vpn", "free vpn config", "free proxy", "mtproto",
    "subscription link", "sub link", "vpn config", "configs", "proxy",
    # روسی
    "бесплатный vpn", "vless конфиг", "прокси", "ключи vpn",
    # چینی
    "翻墙", "节点", "机场", "免费节点", "代理",
]

RELEVANT_WORDS = (
    "v2ray", "vless", "vmess", "trojan", "shadowsocks", "xray", "sing-box", "singbox", "hiddify", "clash",
    "reality", "proxy", "vpn", "config", "configs", "sub", "mtproto", "v2rayng", "nekobox", "hysteria",
    "کانفیگ", "کانفینگ", "فیلتر", "فیلترشکن", "پروکسی", "وی پی ان", "وی‌پی‌ان", "ساب", "اشتراک",
    "翻墙", "节点", "机场", "代理", "впн", "прокси", "конфиг", "ключи",
)

# ---------------------------------------------------------------- settings helpers
import tenant_ctx

DSTATE = tenant_ctx.PerTenant(lambda: {
    "last_cycle": 0.0,
    "summary": "",
    "join_paused_until": 0.0,
    "wake": None,
    "flood_warned_at": 0.0,
})


def setting(db, key: str) -> str:
    return str(db.get_setting(key, DEFAULTS.get(key, "")) or "").strip()


def flag(db, key: str) -> bool:
    return setting(db, key) == "1"


def int_setting(db, key: str, default: int) -> int:
    try:
        return int(setting(db, key) or default)
    except (TypeError, ValueError):
        return default


def join_mode(db) -> str:
    mode = setting(db, KEY_JOIN_MODE)
    return mode if mode in JOIN_MODES else "auto"


# ---------------------------------------------------------------- text helpers
CONFIG_LINK_RE = re.compile(
    r"\b(?:vless|vmess|trojan|ss|ssr|hysteria2|hysteria|hy2|tuic)://[^\s<>\"'`]{8,}", re.IGNORECASE,
)
SUB_URL_RE = re.compile(
    r"https?://[^\s<>\"'`]+/(?:sub|subscribe|subscription|sub-link|api/v1/client/subscribe)/[^\s<>\"'`]{6,}"
    r"|https?://[^\s<>\"'`]+[?&](?:token|sub)=[^\s<>\"'`&]{8,}",
    re.IGNORECASE,
)


def count_config_links(text: str) -> int:
    if not text:
        return 0
    return len(CONFIG_LINK_RE.findall(text)) + len(SUB_URL_RE.findall(text))


def message_text(msg) -> str:
    """متن پست + لینک‌های پنهان (هایپرلینک و دکمه‌ی شیشه‌ای) که در msg.message نیستند."""
    parts = [getattr(msg, "message", "") or ""]
    for ent in getattr(msg, "entities", None) or []:
        url = getattr(ent, "url", None)
        if url:
            parts.append(url)
    markup = getattr(msg, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        for button in getattr(row, "buttons", None) or []:
            url = getattr(button, "url", None)
            if url:
                parts.append(url)
    return "\n".join(p for p in parts if p)


_USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
_TME_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/([A-Za-z0-9_+\-]+)(?:/([^\s<>\"'`]*))?", re.IGNORECASE,
)
_MENTION_RE = re.compile(r"(?<![\w/.@])@([A-Za-z][A-Za-z0-9_]{4,31})\b")
_TG_RESOLVE_RE = re.compile(r"tg://resolve\?domain=([A-Za-z][A-Za-z0-9_]{4,31})", re.IGNORECASE)
_TG_JOIN_RE = re.compile(r"tg://join\?invite=([A-Za-z0-9_\-]{16,})", re.IGNORECASE)
_RESERVED_PATHS = {
    "s", "c", "addlist", "proxy", "socks", "share", "iv", "login", "addstickers", "addemoji", "setlanguage",
    "bg", "m", "boost", "invoice", "giftcode", "addtheme", "confirmphone", "contact", "msg", "joinchat",
    "telegram", "botfather", "durov", "username", "stickers", "premium", "gifts",
}


def _valid_username(name: str) -> bool:
    return bool(_USERNAME_RE.fullmatch(name or "")) and not name.lower().endswith("bot") \
        and name.lower() not in _RESERVED_PATHS


def extract_refs(text: str) -> list:
    """[('user', name) | ('invite', hash)] از همه‌ی ارجاع‌های تلگرامی یک متن، بدون تکرار."""
    found, seen = [], set()

    def add(kind, value):
        key = (kind, value.lower() if kind == "user" else value)
        if key not in seen:
            seen.add(key)
            found.append((kind, value))

    text = text or ""
    for m in _TME_RE.finditer(text):
        first, rest = m.group(1), m.group(2) or ""
        if first.startswith("+"):
            if len(first) > 16:
                add("invite", first[1:])
        elif first.lower() == "joinchat":
            code = re.split(r"[/?#]", rest)[0]
            if len(code) >= 16:
                add("invite", code)
        elif first.lower() not in _RESERVED_PATHS and _valid_username(first):
            add("user", first)
    for m in _TG_RESOLVE_RE.finditer(text):
        if _valid_username(m.group(1)):
            add("user", m.group(1))
    for m in _TG_JOIN_RE.finditer(text):
        add("invite", m.group(1))
    for m in _MENTION_RE.finditer(text):
        if _valid_username(m.group(1)):
            add("user", m.group(1))
    return found


def candidate_key(kind: str, value: str) -> str:
    return f"i:{value}" if kind == "invite" else f"u:{value.lower()}"


def collect_refs(db, text: str, source: str = "crawl") -> int:
    """لینک‌های تلگرامی متن را کاندیدا می‌کند (فقط دیتابیس، بدون درخواست به تلگرام)."""
    if not text or not flag(db, KEY_ENABLED) or not flag(db, KEY_CRAWL):
        return 0
    created = 0
    for kind, value in extract_refs(text)[:MAX_REFS_PER_POST]:
        if db.upsert_leak_candidate(
            candidate_key(kind, value),
            username=value if kind == "user" else "",
            invite_hash=value if kind == "invite" else "",
            source=source,
        ):
            created += 1
    return created


# ---------------------------------------------------------------- scoring
def title_relevance(title: str, username: str = "") -> float:
    """۰ تا ۱: چند کلمه‌ی مرتبط با کانفیگ/VPN در عنوان و نام کاربری هست."""
    blob = f"{title or ''} {(username or '').replace('_', ' ')}".lower()
    tokens = set(re.findall(r"[\w\-]+", blob))
    hits = 0
    for word in RELEVANT_WORDS:
        if word.isascii() and len(word) < 5:
            hit = word in tokens
        else:
            hit = word in blob
        hits += 1 if hit else 0
    return min(1.0, hits / 2)


def _freshness(newest_ts, now: float) -> float:
    if not newest_ts:
        return 0.5
    age_days = max(0.0, (now - newest_ts) / 86400)
    if age_days <= 3:
        return 1.0
    if age_days <= 10:
        return 0.7
    if age_days <= 30:
        return 0.35
    if age_days <= 90:
        return 0.1
    return 0.0


def score_channel(sample, title: str = "", username: str = "", members: int = 0, now: float = None) -> dict:
    """امتیاز ۰ تا ۱۰۰ برای یک کانال/گروه.

    sample: فهرست (متن، زمان‌پست یا None) از آخرین پست‌ها؛ فهرست خالی یعنی پیش‌نمایش ممکن نبود.
    """
    now = now if now is not None else time.time()
    n = len(sample)
    title_part = title_relevance(title, username)
    members_part = min(1.0, math.log10(max(int(members or 0), 0) + 1) / 5)
    if n == 0:
        score = (title_part * 0.7 + members_part * 0.3) * 70
        return {"score": round(score, 1), "density": 0.0, "config_posts": 0, "config_links": 0,
                "samples": 0, "preview": False}

    counts = [count_config_links(text) for text, _ in sample]
    cfg_msgs = sum(1 for c in counts if c)
    density = cfg_msgs / n
    density_part = min(1.0, density / 0.35)
    if n < MIN_SAMPLE_FOR_VERDICT:
        density_part *= n / MIN_SAMPLE_FOR_VERDICT

    stamps = [ts for _, ts in sample if ts]
    fresh = _freshness(max(stamps) if stamps else None, now)
    rate_part = 0.5
    if len(stamps) >= 2:
        span_days = max((max(stamps) - min(stamps)) / 86400, 0.5)
        rate_part = min(1.0, (n / span_days) / 3)

    score = 100 * (0.45 * density_part + 0.20 * fresh + 0.15 * title_part + 0.10 * members_part + 0.10 * rate_part)
    if n >= 10 and cfg_msgs == 0 and title_part < 0.5:
        score = min(score, 20.0)
    if fresh == 0.0 and stamps:
        score = min(score, 25.0)
    return {"score": round(score, 1), "density": round(density, 3), "config_posts": cfg_msgs,
            "config_links": sum(counts), "samples": n, "preview": True}


# ---------------------------------------------------------------- queries
def _query_active(row) -> bool:
    try:
        value = row["active"]
    except (KeyError, IndexError):
        return True
    return value is None or int(value) != 0


def pick_queries(rows, now: float, n: int = QUERIES_PER_CYCLE, rng=random) -> list:
    """کلیدواژه‌هایی که الان نوبتشان است؛ بازدهی بالاتر = اولویت بالاتر. هرگز اجرا نشده‌ها اول."""
    due = []
    for row in rows:
        if not _query_active(row):
            continue
        runs = int(row["runs"] or 0)
        gap_h = min(QUERY_BASE_GAP_HOURS * (1 + runs // 5), QUERY_MAX_GAP_HOURS)
        last = float(row["last_run_at"] or 0)
        if now - last < gap_h * 3600:
            continue
        yield_rate = (int(row["good_found"] or 0) + 1) / (runs + 2)
        priority = (10.0 if runs == 0 else 0.0) + yield_rate + rng.random() * 0.25
        due.append((priority, row["query"]))
    due.sort(reverse=True)
    return [q for _, q in due[:n]]


_STOP_TOKENS = {
    "free", "channel", "group", "official", "telegram", "the", "and", "for", "best", "new", "from",
    "کانال", "گروه", "رایگان", "جدید", "بهترین", "تلگرام", "رسمی",
}


def learn_queries(titles, existing, limit: int = 3) -> list:
    """از عنوان/نام کاربری کانال‌های خوب کلیدواژه‌ی تازه می‌سازد (توکن‌های منحصربه‌فرد، نه عمومی)."""
    known = {q.lower() for q in existing}
    counts = {}
    for title in titles:
        for tok in re.findall(r"[\w\-]+", (title or "").replace("_", " ").lower()):
            if len(tok) < 4 or tok.isdigit() or tok in _STOP_TOKENS or tok in known:
                continue
            counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [tok for tok, _ in ranked[:limit]]


def join_budget(joined_today: int, daily_cap: int, joined_total: int, max_joined: int) -> int:
    """چند عضویت دیگر مجاز است (کمینه‌ی سقف روزانه و سقف کل)."""
    return max(0, min(daily_cap - joined_today, max_joined - joined_total))


# ---------------------------------------------------------------- telegram side
GONE_ERRORS = {
    "UsernameNotOccupiedError", "UsernameInvalidError", "ChannelInvalidError", "InviteHashExpiredError",
    "InviteHashInvalidError", "ChannelPrivateError", "ChannelBannedError", "UserBannedInChannelError",
    "ValueError", "InviteRequestSentError",
}


def _entity_info(chat) -> dict:
    """اطلاعات یک Channel تلگرام؛ None برای چیزهایی که کانال/گروه سالم نیستند."""
    if type(chat).__name__ != "Channel":
        return None
    broadcast, mega = bool(getattr(chat, "broadcast", False)), bool(getattr(chat, "megagroup", False))
    if not (broadcast or mega) or getattr(chat, "scam", False) or getattr(chat, "fake", False):
        return None
    return {
        "channel_id": chat.id,
        "username": getattr(chat, "username", "") or "",
        "title": getattr(chat, "title", "") or "",
        "members": int(getattr(chat, "participants_count", 0) or 0),
        "kind": "broadcast" if broadcast else "group",
    }


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Discovery:
    def __init__(self, client, db, bot, call, handle_post, state):
        self.client = client
        self.db = db
        self.bot = bot
        self.call = call                # درخواست با سقف نرخ و مدیریت FloodWait (از اسکنر)
        self.handle_post = handle_post  # تطبیق پست با ایندکس (از اسکنر)
        self.state = state              # STATE اسکنر
        DSTATE["wake"] = asyncio.Event()

    # ---- helpers
    async def _db(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _invalidate_watch_cache(self):
        self.state["watched_at"] = 0.0

    async def notify(self, text: str, markup=None):
        try:
            from report_router import report
            await report(self.bot, self.db, "leak", text, reply_markup=markup)
        except Exception:
            logger.warning("leak discovery: notify failed", exc_info=True)

    @staticmethod
    def _approval_markup(cand_id: int):
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ عضویت", callback_data=f"lkd:ok:{cand_id}"),
            InlineKeyboardButton(text="⏭ رد", callback_data=f"lkd:no:{cand_id}"),
        ]])

    def _describe(self, cand, info: dict) -> str:
        name = html.escape(cand["title"] or cand["username"] or cand["key"])
        ref = f"@{html.escape(cand['username'])}" if cand["username"] else "🔒 invite"
        return (
            f"{name} ({ref})\n"
            f"👥 {cand['members'] or '-'} | ⭐ {info['score']} | 🧾 {info['config_posts']}/{info['samples']}"
        )

    # ---- cycle
    async def loop(self):
        await asyncio.sleep(random.uniform(20, 60))
        while True:
            try:
                if flag(self.db, KEY_ENABLED) and setting(self.db, SCANNER_ENABLED_KEY) == "1" \
                        and self.client.is_connected():
                    await self.cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("leak discovery cycle failed", exc_info=True)
            minutes = max(int_setting(self.db, KEY_INTERVAL, 30), 5)
            try:
                await asyncio.wait_for(DSTATE["wake"].wait(), timeout=minutes * 60 * random.uniform(0.8, 1.3))
            except asyncio.TimeoutError:
                pass
            DSTATE["wake"].clear()

    async def cycle(self) -> str:
        summary = []
        for name, step in (
            ("search", self.run_searches), ("evaluate", self.evaluate_pending),
            ("join", self.join_ready), ("prune", self.prune), ("learn", self.learn),
        ):
            try:
                done = await step()
                if done:
                    summary.append(f"{name}:{done}")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("leak discovery step %s failed", name, exc_info=True)
        await self._db(self.db.trim_leak_candidates, 3000)
        DSTATE["last_cycle"] = time.time()
        DSTATE["summary"] = " ".join(summary)
        return DSTATE["summary"]

    # ---- 1) search
    async def run_searches(self) -> int:
        from telethon.tl.functions.contacts import SearchRequest

        await self._db(self.db.ensure_leak_queries, SEED_QUERIES, "seed")
        rows = await self._db(self.db.list_leak_queries)
        found_total = 0
        for query in pick_queries(rows, time.time()):
            result = await self.call(lambda q=query: self.client(SearchRequest(q=q, limit=SEARCH_LIMIT)))
            if result is None:
                break
            new = 0
            for chat in getattr(result, "chats", []) or []:
                info = _entity_info(chat)
                if not info:
                    continue
                key = f"u:{info['username'].lower()}" if info["username"] else f"c:{info['channel_id']}"
                if await self._db(
                    self.db.upsert_leak_candidate, key, info["channel_id"], info["username"], "",
                    info["title"], info["members"], info["kind"], "search", f"q:{query}",
                ):
                    new += 1
            await self._db(self.db.record_leak_query_run, query, new, time.time())
            found_total += new
        return found_total

    # ---- 2) evaluate
    async def evaluate_pending(self) -> int:
        cands = await self._db(self.db.list_leak_candidates, ["new"], EVALUATE_PER_CYCLE, "seen")
        done = 0
        for cand in cands:
            try:
                if await self.evaluate(cand):
                    done += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("leak discovery: evaluate %s failed", cand["key"], exc_info=True)
                await self._db(self.db.update_leak_candidate, cand["id"], state="failed", reason="error")
        return done

    async def _fail(self, cand, reason: str, state: str = "failed"):
        await self._db(self.db.update_leak_candidate, cand["id"], state=state, reason=reason)

    async def evaluate(self, cand) -> bool:
        """True اگر ارزیابی تمام شد (حتی با رد)؛ False اگر به‌خاطر FloodWait باید بعداً تکرار شود."""
        thr = float(int_setting(self.db, KEY_MIN_SCORE, 35))
        title, members, username = cand["title"], int(cand["members"] or 0), cand["username"]
        entity, sample, msgs, channel_id, kind = None, [], [], int(cand["channel_id"] or 0), cand["kind"]

        if username:
            try:
                entity = await self.call(lambda: self.client.get_entity(username))
            except Exception as exc:
                await self._fail(cand, "gone" if type(exc).__name__ in GONE_ERRORS else type(exc).__name__)
                return True
            if entity is None:
                return False
            info = _entity_info(entity)
            if not info:
                await self._fail(cand, "not_channel", "skipped")
                return True
            channel_id, kind = info["channel_id"], info["kind"]
            title, members = info["title"] or title, max(members, info["members"])
            try:
                msgs = await self.call(lambda: self.client.get_messages(entity, limit=SAMPLE_SIZE))
            except Exception as exc:
                logger.info("leak discovery: no preview for %s (%s)", username, type(exc).__name__)
                msgs = []
            if msgs is None:
                return False
            msgs = list(msgs or [])
            for msg in msgs:
                text = message_text(msg)
                stamp = msg.date.timestamp() if getattr(msg, "date", None) else None
                sample.append((text, stamp))
                if text and await self._db(self.db.mark_leak_post_seen, channel_id, msg.id):
                    await self.handle_post(self.db, self.bot, text, channel_id, title, username, msg.id)
        elif cand["invite_hash"]:
            from telethon.tl.functions.messages import CheckChatInviteRequest
            try:
                invite = await self.call(lambda: self.client(CheckChatInviteRequest(cand["invite_hash"])))
            except Exception as exc:
                await self._fail(cand, "gone" if type(exc).__name__ in GONE_ERRORS else type(exc).__name__)
                return True
            if invite is None:
                return False
            chat = getattr(invite, "chat", None)         # ChatInviteAlready
            info = _entity_info(chat) if chat is not None else None
            if info:
                channel_id, kind = info["channel_id"], info["kind"]
                title, members = info["title"], max(members, info["members"])
                username = info["username"] or username
            else:
                title = getattr(invite, "title", "") or title
                members = max(members, int(getattr(invite, "participants_count", 0) or 0))
                kind = "broadcast" if getattr(invite, "broadcast", False) else "group"
                if getattr(invite, "request_needed", False):
                    await self._fail(cand, "request_needed", "skipped")
                    return True
        else:
            await self._fail(cand, "no_ref", "skipped")
            return True

        result = score_channel(sample, title, username, members)
        # توضیح کانال: لینک‌های دیگر + شمار اعضای دقیق (فقط برای کاندیدای امیدوارکننده)
        if entity is not None and result["score"] >= thr - 10:
            members, result = await self._enrich(cand, entity, sample, title, username, members, result)

        await self._db(
            self.db.update_leak_candidate, cand["id"], channel_id=channel_id, title=title, members=members,
            kind=kind, score=result["score"], config_posts=result["config_posts"], username=username,
        )
        await self._triage(cand, result, entity, msgs, title, username, channel_id, members)
        return True

    async def _enrich(self, cand, entity, sample, title, username, members, result):
        from telethon.tl.functions.channels import GetFullChannelRequest
        try:
            full = await self.call(lambda: self.client(GetFullChannelRequest(entity)))
        except Exception:
            return members, result
        if full is None:
            return members, result
        chat_full = getattr(full, "full_chat", None)
        count = int(getattr(chat_full, "participants_count", 0) or 0)
        about = getattr(chat_full, "about", "") or ""
        if about:
            await self._db(collect_refs, self.db, about, f"about:{username or title}")
        members = max(members, count)
        return members, score_channel(sample, title, username, members)

    async def _triage(self, cand, result, entity, msgs, title, username, channel_id, members):
        thr = float(int_setting(self.db, KEY_MIN_SCORE, 35))
        score = result["score"]
        if score < thr:
            await self._db(
                self.db.update_leak_candidate, cand["id"], state="skipped",
                reason=f"score {score}<{thr:g}",
            )
            return
        mode = join_mode(self.db)
        is_invite = not username and bool(cand["invite_hash"])
        if mode == "watch":
            if is_invite or entity is None:
                await self._fail(cand, "needs_join", "skipped")
                return
            last_id = max((m.id for m in msgs), default=0)
            await self._db(
                self.db.add_leak_channel, channel_id, title, username, last_id, "discovery", False, False,
                score, members,
            )
            self._invalidate_watch_cache()
            await self._db(self.db.update_leak_candidate, cand["id"], state="watching", reason="preview-only")
        elif mode == "approve":
            await self._db(self.db.update_leak_candidate, cand["id"], state="pending", reason="awaiting admin")
            fresh = await self._db(self.db.get_leak_candidate, cand["id"])
            await self.notify(
                "🧭 <b>کانال تازه برای عضویت</b>\n" + self._describe(fresh, result),
                self._approval_markup(cand["id"]),
            )
        else:
            await self._db(self.db.update_leak_candidate, cand["id"], state="qualified", reason="ready")
        if cand["source_query"].startswith("q:"):
            await self._db(self.db.bump_leak_query_good, cand["source_query"][2:])

    # ---- 3) join
    def _pause_joins(self, seconds: int):
        DSTATE["join_paused_until"] = time.time() + max(int(seconds), 60)

    async def join_ready(self) -> int:
        if join_mode(self.db) == "watch" or time.time() < DSTATE["join_paused_until"]:
            return 0
        total = await self._db(self.db.count_joined_leak_channels)
        today = await self._db(self.db.count_leak_joins_since, 24)
        max_joined = int_setting(self.db, KEY_MAX_JOINED, 100)
        daily = int_setting(self.db, KEY_DAILY_JOINS, 5)
        room_total = max_joined - total
        daily_left = join_budget(today, daily, total, max_joined)
        approved = await self._db(self.db.list_leak_candidates, ["approved"], JOINS_PER_CYCLE, "score")
        qualified = []
        if join_mode(self.db) == "auto" and daily_left > 0:
            qualified = await self._db(self.db.list_leak_candidates, ["qualified"], daily_left, "score")
        queue = [c for c in approved][:max(room_total, 0)] + list(qualified)
        joined = 0
        for cand in queue[:JOINS_PER_CYCLE]:
            if time.time() < DSTATE["join_paused_until"]:
                break
            if await self.join(cand):
                joined += 1
                await asyncio.sleep(random.uniform(*JOIN_DELAY))
        return joined

    async def join(self, cand) -> bool:
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest

        username, invite = cand["username"], cand["invite_hash"]
        already = False
        try:
            if invite and not username:
                result = await self.call(lambda: self.client(ImportChatInviteRequest(invite)))
                chat = next(iter(getattr(result, "chats", []) or []), None) if result is not None else None
            else:
                entity = await self.call(lambda: self.client.get_entity(username))
                result = None if entity is None else await self.call(lambda: self.client(JoinChannelRequest(entity)))
                chat = entity
            if result is None:
                seconds = max(int(self.state.get("last_flood", 0) or 0), DEFAULT_JOIN_PAUSE)
                self._pause_joins(seconds)
                await self._warn_flood(seconds)
                return False
        except Exception as exc:
            name = type(exc).__name__
            if name == "UserAlreadyParticipantError":
                already, chat = True, None
            elif name == "ChannelsTooMuchError":
                self._pause_joins(CHANNELS_FULL_PAUSE)
                await self.notify("⚠️ اکانت یوزربات به سقف تعداد کانال/گروه تلگرام رسید؛ عضویت خودکار ۲۴ ساعت متوقف شد.")
                return False
            elif name in GONE_ERRORS:
                await self._fail(cand, "request_sent" if name == "InviteRequestSentError" else "gone")
                return False
            else:
                logger.warning("leak discovery: join %s failed", cand["key"], exc_info=True)
                await self._fail(cand, name)
                return False

        info = _entity_info(chat) if chat is not None else None
        channel_id = info["channel_id"] if info else int(cand["channel_id"] or 0)
        if not channel_id:
            await self._fail(cand, "no_id")
            return False
        title = (info or {}).get("title") or cand["title"]
        last_id = 0
        try:
            latest = await self.call(lambda: self.client.get_messages(chat or username, limit=1))
            last_id = latest[0].id if latest else 0
        except Exception:
            pass
        await self._db(
            self.db.add_leak_channel, channel_id, title, (info or {}).get("username") or username, last_id,
            "discovery", True, not already, float(cand["score"] or 0), int(cand["members"] or 0),
        )
        await self._db(self.db.update_leak_candidate, cand["id"], state="joined", reason="", joined_at=_iso_now())
        self._invalidate_watch_cache()
        if flag(self.db, KEY_NOTIFY):
            await self.notify(f"➕ <b>عضو شد (کشف خودکار)</b>\n{html.escape(title or '-')} | ⭐ {cand['score']}")
        return True

    async def _warn_flood(self, seconds: int):
        now = time.time()
        if now - DSTATE["flood_warned_at"] < 3600:
            return
        DSTATE["flood_warned_at"] = now
        await self.notify(
            f"⚠️ تلگرام عضویت را محدود کرد (FloodWait). عضویت خودکار حدود {max(seconds // 60, 1)} دقیقه متوقف شد."
        )

    # ---- 4) prune
    async def prune(self) -> int:
        if not flag(self.db, KEY_AUTO_LEAVE):
            return 0
        rows = await self._db(self.db.list_prunable_leak_channels, PRUNE_AFTER_DAYS, PRUNE_MIN_CONFIG_POSTS)
        left = 0
        for ch in rows[:LEAVES_PER_CYCLE]:
            ok, _ = await self.leave_channel(ch["channel_id"], reason="useless")
            left += 1 if ok else 0
        return left

    async def leave_channel(self, channel_id: int, reason: str = "manual"):
        """ترک کانال و حذف از فهرست پایش. فقط کانال‌هایی که اسکنر خودش عضوشان شده."""
        from telethon.tl.functions.channels import LeaveChannelRequest
        from telethon.tl.types import PeerChannel

        ch = await self._db(self.db.get_leak_channel, channel_id)
        if not ch:
            return False, "کانال پیدا نشد."
        if ch["joined"] and ch["auto_joined"]:
            try:
                entity = await self.client.get_input_entity(PeerChannel(channel_id))
                result = await self.call(lambda: self.client(LeaveChannelRequest(entity)))
                if result is None:
                    return False, "تلگرام محدودیت موقت گذاشته؛ بعداً تلاش کنید."
            except Exception as exc:
                logger.warning("leak discovery: leave %s failed", channel_id, exc_info=True)
                return False, f"ترک کانال ناموفق بود: {type(exc).__name__}"
        await self._db(self.db.remove_leak_channel, channel_id)
        self._invalidate_watch_cache()
        for cand in await self._db(self.db.list_leak_candidates, ["joined", "watching"], 500, "recent"):
            if int(cand["channel_id"] or 0) == int(channel_id):
                await self._db(self.db.update_leak_candidate, cand["id"], state="left", reason=reason)
        return True, "انجام شد."

    # ---- 5) learn
    async def learn(self) -> int:
        if await self._db(self.db.count_learned_leak_queries) >= MAX_LEARNED_QUERIES:
            return 0
        good = await self._db(self.db.list_leak_candidates, ["joined", "watching", "qualified"], 30, "score")
        titles = [f"{c['title']} {c['username']}" for c in good if (c["score"] or 0) >= 60]
        existing = [r["query"] for r in await self._db(self.db.list_leak_queries)]
        fresh = learn_queries(titles, existing)
        if fresh:
            await self._db(self.db.ensure_leak_queries, fresh, "learned")
        return len(fresh)
