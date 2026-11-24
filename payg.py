# -*- coding: utf-8 -*-
"""Pay As You Go billing for the main Telegram bot.

Only services with authoritative byte counters are billable. In this release
that means custom VPN configs explicitly provisioned by PayG and represented
in usage_snapshots. Existing purchased services are never enrolled implicitly.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db.constants import _wallet_tag
from i18n import tr as _base_tr

logger = logging.getLogger("payg")
GIB = 1024 ** 3
DEFAULT_RATES = [5000, 4500, 4000, 3500]


_DEFAULT_NAME = "Pay As You Go"
PAYG_NAME_KEY = "payg_name"
PAYG_NAME_MAX = 40
PAYG_EMOJI_KEY = "payg_emoji"
PAYG_EMOJI_DEFAULT = "💳"
PAYG_EMOJI_MAX = 8
_LEGACY_BTN = "💳 پرداخت به‌ازای مصرف"
_BTN_TITLE = "پرداخت به‌ازای مصرف"
_name_state = {"db": None, "value": "", "at": 0.0}


def get_payg_name(db=None) -> str:
    """نام اشتراک پرداخت به‌ازای مصرف؛ تعیین‌شده توسط مدیر یا پیش‌فرض."""
    db = db or _name_state["db"]
    if db is None:
        return _DEFAULT_NAME
    now = time.monotonic()
    if db is not _name_state["db"] or now - _name_state["at"] > 5:
        try:
            value = str(db.get_setting(PAYG_NAME_KEY, "") or "").strip()[:PAYG_NAME_MAX]
        except Exception:
            value = ""
        _name_state.update(db=db, value=value, at=now)
    return _name_state["value"] or _DEFAULT_NAME


def get_payg_emoji(db=None) -> str:
    """ایموجی دکمه‌ی پرداخت به‌ازای مصرف؛ تعیین‌شده توسط مدیر یا پیش‌فرض."""
    db = db or _name_state["db"]
    if db is None:
        return PAYG_EMOJI_DEFAULT
    try:
        value = str(db.get_setting(PAYG_EMOJI_KEY, "") or "").strip()[:PAYG_EMOJI_MAX]
    except Exception:
        value = ""
    return value or PAYG_EMOJI_DEFAULT


def button_texts(db) -> list:
    """همه‌ی متن‌های ممکن دکمه‌ی منوی اصلی (برای تطبیق پیام کیبورد قدیمی و جدید)."""
    emoji, name = get_payg_emoji(db), get_payg_name(db)
    out = [db.get_setting("btn_payg", f"{emoji} {_BTN_TITLE}"), _LEGACY_BTN, f"💳 {name}",
           f"{emoji} {_BTN_TITLE}", f"{emoji} {name}"]
    return [t for i, t in enumerate(out) if t and t not in out[:i]]


def _n(text):
    """نام پیش‌فرض را با نام تعیین‌شده توسط مدیر جایگزین می‌کند (برای متن HTML امن‌شده)."""
    if not isinstance(text, str) or _DEFAULT_NAME not in text:
        return text
    name = get_payg_name()
    return text if name == _DEFAULT_NAME else text.replace(_DEFAULT_NAME, html.escape(name, quote=False))


def tr(text, language=None):
    return _n(_base_tr(text, language))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _tformat(template: str, **values) -> str:
    """Translate a Persian template before inserting dynamic values."""
    return _n(tr(template).format(**values))


def is_free_payg_user(db, user_id) -> bool:
    """مالک و مدیر کل بدون شارژ کیف پول و بدون کسر هزینه از PayG استفاده می‌کنند."""
    try:
        return bool(db.is_senior_admin(int(user_id)))
    except Exception:
        return False


def ensure_schema(db):
    _name_state.update(db=db, value=_name_state["value"] if _name_state["db"] is db else "", at=0.0)
    with db._get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS payg_accounts (
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'inactive',
            quota_pool_id INTEGER,
            initial_balance INTEGER NOT NULL DEFAULT 0,
            last_balance INTEGER NOT NULL DEFAULT 0,
            month_key TEXT NOT NULL DEFAULT '',
            month_rates TEXT NOT NULL DEFAULT '',
            month_used_bytes INTEGER NOT NULL DEFAULT 0,
            month_cost INTEGER NOT NULL DEFAULT 0,
            last_alert_level INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payg_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_kind TEXT NOT NULL,
            service_id TEXT NOT NULL,
            last_billed_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(service_kind, service_id)
        );
        CREATE INDEX IF NOT EXISTS idx_payg_services_user ON payg_services(user_id);
        CREATE TABLE IF NOT EXISTS payg_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            cycle_key TEXT NOT NULL,
            service_kind TEXT NOT NULL,
            service_id TEXT NOT NULL,
            used_bytes INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            rate_snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(cycle_key, service_kind, service_id)
        );
        CREATE INDEX IF NOT EXISTS idx_payg_transactions_user ON payg_transactions(user_id, id DESC);
        """)
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('payg_enabled','1')")
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('payg_rates',?)",
                     (json.dumps(DEFAULT_RATES),))
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('payg_cycle_seconds','600')")
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('payg_max_services_per_user','5')")
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('payg_panel_server_id','')")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS payg_provision_locks (
            user_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payg_provisioned_services (
            service_kind TEXT NOT NULL,
            service_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(service_kind, service_id)
        );
        """)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(payg_accounts)").fetchall()}
        if "last_balance" not in columns:
            conn.execute("ALTER TABLE payg_accounts ADD COLUMN last_balance INTEGER NOT NULL DEFAULT 0")
        if "cut_at" not in columns:
            conn.execute("ALTER TABLE payg_accounts ADD COLUMN cut_at TEXT NOT NULL DEFAULT ''")
        if "purged_at" not in columns:
            conn.execute("ALTER TABLE payg_accounts ADD COLUMN purged_at TEXT NOT NULL DEFAULT ''")
        if "month_rates" not in columns:
            conn.execute("ALTER TABLE payg_accounts ADD COLUMN month_rates TEXT NOT NULL DEFAULT ''")
        service_columns = {r[1] for r in conn.execute("PRAGMA table_info(payg_services)").fetchall()}
        for name, definition in (
            ("panel_server_id", "INTEGER"),
            ("target_key", "TEXT NOT NULL DEFAULT '*'"),
            ("user_capacity", "INTEGER NOT NULL DEFAULT 1"),
            ("charged_users", "INTEGER NOT NULL DEFAULT 0"),
            ("active_since", "TEXT NOT NULL DEFAULT ''"),
            ("day_billed_until", "REAL NOT NULL DEFAULT 0"),
            ("is_active", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if name not in service_columns:
                conn.execute(f"ALTER TABLE payg_services ADD COLUMN {name} {definition}")
        # Upgrade accounts created by the first PAYG preview without resetting usage.
        conn.execute("UPDATE payg_accounts SET last_balance=initial_balance WHERE last_balance=0 AND initial_balance>0")
        conn.execute("UPDATE payg_accounts SET month_rates=? WHERE month_rates=''", (json.dumps(DEFAULT_RATES),))
    _cleanup_unmarked_legacy_services(db)


def _cleanup_unmarked_legacy_services(db):
    """Fail safe on pre-marker rows: detach them so purchased services cannot be billed."""
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT ps.user_id,ps.service_kind,ps.service_id,pa.quota_pool_id "
            "FROM payg_services ps LEFT JOIN payg_provisioned_services p "
            "ON p.service_kind=ps.service_kind AND p.service_id=ps.service_id AND p.user_id=ps.user_id "
            "LEFT JOIN payg_accounts pa ON pa.user_id=ps.user_id "
            "WHERE p.service_id IS NULL"
        ).fetchall()
    for row in rows:
        pool_id = row["quota_pool_id"]
        if pool_id:
            try:
                db.detach_quota_service(int(pool_id), row["service_kind"], row["service_id"])
            except Exception:
                logger.exception("Could not detach legacy non-PayG service %s/%s",
                                 row["service_kind"], row["service_id"])
                continue
            # detach_quota_service preserves usage as a pool adjustment. This was
            # not PayG consumption, so remove that adjustment from the PayG pool.
            with db._get_conn() as conn:
                conn.execute(
                    "DELETE FROM quota_pool_adjustments WHERE pool_id=? AND service_kind=? AND service_id=?",
                    (int(pool_id), row["service_kind"], row["service_id"]),
                )
        with db._get_conn() as conn:
            conn.execute(
                "DELETE FROM payg_services WHERE user_id=? AND service_kind=? AND service_id=?",
                (int(row["user_id"]), row["service_kind"], row["service_id"]),
            )
            remaining = conn.execute("SELECT COUNT(*) n FROM payg_services WHERE user_id=?",
                                     (int(row["user_id"]),)).fetchone()["n"]
            if not remaining:
                conn.execute(
                    "UPDATE payg_accounts SET status='inactive',quota_pool_id=NULL,updated_at=? "
                    "WHERE user_id=? AND status='active'",
                    (_now(), int(row["user_id"])),
                )
                conn.execute("DELETE FROM payg_provision_locks WHERE user_id=?", (int(row["user_id"]),))
        if not remaining and pool_id:
            try:
                db.delete_quota_pool(int(pool_id))
            except Exception:
                logger.exception("Could not delete empty legacy PAYG pool %s", pool_id)


def get_payg_panel_ids(db):
    """پنل‌های فعال انتخاب‌شده برای ساخت سرویس؛ سازگار با تنظیم قدیمی تک‌پنلی."""
    raw = str(db.get_setting("payg_panel_server_ids", "") or "").strip()
    ids = []
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                ids = [int(x) for x in value if str(x).isdigit()]
        except Exception:
            ids = []
    if not ids:
        legacy = str(db.get_setting("payg_panel_server_id", "") or "").strip()
        if legacy.isdigit() and int(legacy) > 0:
            ids = [int(legacy)]
    ids = list(dict.fromkeys(x for x in ids if x > 0))
    try:
        import dedicated_sub
        return dedicated_sub.sort_panel_ids(db, ids)
    except Exception:
        return ids


def get_payg_targets(db):
    """اینباند/گروه انتخاب‌شده برای هر پنل PayG: {panel_id: target_config}."""
    raw = str(db.get_setting("payg_panel_targets", "") or "").strip()
    out = {}
    if not raw:
        return out
    try:
        data = json.loads(raw)
    except Exception:
        return out
    if isinstance(data, dict):
        for key, cfg in data.items():
            if str(key).isdigit() and isinstance(cfg, dict) and "field" in cfg:
                out[int(key)] = cfg
    return out


def _save_payg_targets(db, targets):
    db.set_setting("payg_panel_targets",
                   json.dumps({str(k): v for k, v in targets.items()}, ensure_ascii=False))


MULTI_NEEDS_DSUB = ("⛔️ حالت «همه مقصدها» در PayG فقط با ساب اختصاصی فعال کار می‌کند؛ "
                    "مدیریت باید ساب اختصاصی را روشن و آدرس پایه‌اش را تنظیم کند.")


def _json_list(db, key):
    try:
        value = json.loads(str(db.get_setting(key, "") or "") or "[]")
    except Exception:
        return []
    return value if isinstance(value, list) else []


def get_payg_ssh_nodes(db):
    """نودهای SSH انتخاب‌شده برای PayG (فقط در حالت «همه مقصدها» استفاده می‌شوند)."""
    ids = [int(x) for x in _json_list(db, "payg_ssh_node_ids") if str(x).isdigit()]
    return list(dict.fromkeys(x for x in ids if x > 0))


def get_payg_ssh_protocols(db):
    from ssh_service import SUPPORTED_PROTOCOLS
    chosen = {str(x).strip().lower() for x in _json_list(db, "payg_ssh_protocols")}
    picked = [p for p in SUPPORTED_PROTOCOLS if p in chosen]
    return picked or ["ssh"]


def get_payg_mode(db):
    """'balance' = هر سرویس روی یک پنل (کم‌بارترین)؛ 'all' = هر سرویس روی همه مقصدها با ساب اختصاصی."""
    return "all" if str(db.get_setting("payg_target_mode", "balance") or "") == "all" else "balance"


def get_min_balance(db) -> int:
    """حداقل موجودی کیف پول (تومان) برای ساخت سرویس مصرفی جدید؛ ۰ یعنی فقط موجودی مثبت لازم است."""
    try:
        return max(0, min(PAYG_MIN_BALANCE_MAX, int(db.get_setting(PAYG_MIN_BALANCE_KEY, "0") or 0)))
    except (TypeError, ValueError):
        return 0


PAYG_ALERT1_MODE_KEY = "payg_alert1_mode"
PAYG_ALERT1_VALUE_KEY = "payg_alert1_value"
PAYG_ALERT1_TEXT_KEY = "payg_alert1_text"
PAYG_ALERT2_MODE_KEY = "payg_alert2_mode"
PAYG_ALERT2_VALUE_KEY = "payg_alert2_value"
PAYG_ALERT2_TEXT_KEY = "payg_alert2_text"
PAYG_CUT_MODE_KEY = "payg_cut_mode"
PAYG_CUT_VALUE_KEY = "payg_cut_value"
PAYG_CUT_TEXT_KEY = "payg_cut_text"
PAYG_ALERT1_TEXT_MAX = 1000
PAYG_ALERT2_TEXT_MAX = 1000
PAYG_ALERT1_PLACEHOLDERS = ("percent", "threshold", "used", "balance", "initial", "retention_days")
PAYG_RETENTION_KEY = "payg_retention_days"
PAYG_RETENTION_MAX = 3650
_ALERT_KEYS = {1: (PAYG_ALERT1_MODE_KEY, PAYG_ALERT1_VALUE_KEY, PAYG_ALERT1_TEXT_KEY, "80", "⚠️"),
               2: (PAYG_ALERT2_MODE_KEY, PAYG_ALERT2_VALUE_KEY, PAYG_ALERT2_TEXT_KEY, "90", "🚨"),
               3: (PAYG_CUT_MODE_KEY, PAYG_CUT_VALUE_KEY, PAYG_CUT_TEXT_KEY, "100", "⛔")}


def get_retention_days(db) -> int:
    """مهلت نگهداری اکانت (روز) پس از قطع؛ ۰ یعنی هرگز حذف نشود."""
    try:
        return max(0, min(PAYG_RETENTION_MAX, int(db.get_setting(PAYG_RETENTION_KEY, "0") or 0)))
    except (TypeError, ValueError):
        return 0


def get_alert(db, n: int):
    """(mode, value) آستانه هشدار n؛ mode = percent|toman و value = 0 یعنی خاموش."""
    mode_key, value_key, _t, default, _e = _ALERT_KEYS[n]
    mode = str(db.get_setting(mode_key, "percent") or "percent").strip()
    if mode not in ("percent", "toman"):
        mode = "percent"
    try:
        value = int(db.get_setting(value_key, default) or 0)
    except (TypeError, ValueError):
        value = int(default)
    cap = 100 if mode == "percent" else PAYG_MIN_BALANCE_MAX
    return mode, max(0, min(cap, value))


def get_first_alert(db):
    return get_alert(db, 1)


def alert_reached(db, n: int, used: int, percent: float) -> bool:
    mode, value = get_alert(db, n)
    if value <= 0:
        return False
    return percent >= value if mode == "percent" else used >= value


def first_alert_reached(db, used: int, percent: float) -> bool:
    return alert_reached(db, 1, used, percent)


def default_alert_template(n: int, mode: str) -> str:
    emoji = _ALERT_KEYS[n][4]
    tail = {1: "برای جلوگیری از توقف سرویس، کیف پول را شارژ کنید.",
            2: "لطفاً هرچه زودتر کیف پول را شارژ کنید، در غیر این صورت سرویس قطع می‌شود.",
            3: "دسترسی شما به اشتراک قطع شد. پس از شارژ کیف پول، اشتراک به‌صورت خودکار دوباره فعال می‌شود."}[n]
    if mode == "toman":
        return f"{emoji} شما {{used}} تومان از اعتبار کیف پول خود را مصرف کرده‌اید. موجودی فعلی: {{balance}} تومان. {tail}"
    return f"{emoji} شما {{percent}} درصد از اعتبار کیف پول خود را مصرف کرده‌اید. موجودی فعلی: {{balance}} تومان. {tail}"


def default_first_alert_template(mode: str) -> str:
    return default_alert_template(1, mode)


def render_alert_text(db, n: int, used: int, initial: int, balance: int, percent: float) -> str:
    mode, value = get_alert(db, n)
    custom = str(db.get_setting(_ALERT_KEYS[n][2], "") or "").strip()
    values = {"percent": int(min(100, percent)), "threshold": value, "used": f"{int(used):,}",
              "balance": f"{int(balance):,}", "initial": f"{int(initial):,}",
              "retention_days": get_retention_days(db)}
    text = custom if custom else tr(default_alert_template(n, mode))
    for name in PAYG_ALERT1_PLACEHOLDERS:
        text = text.replace("{" + name + "}", str(values[name]))
    return text


def render_first_alert_text(db, used: int, initial: int, balance: int, percent: float) -> str:
    return render_alert_text(db, 1, used, initial, balance, percent)


def get_usable_payg_panel_ids(db):
    """پنل‌های PayG که ساب اختصاصی‌شان خاموش نشده است."""
    import dedicated_sub
    return [pid for pid in get_payg_panel_ids(db) if dedicated_sub.panel_enabled(db, pid)]


def payg_multi_plan(db):
    """(panel_ids, node_ids, protocols) اگر ساخت چندمقصدی لازم است؛ وگرنه None."""
    if get_payg_mode(db) != "all":
        return None
    panels = get_usable_payg_panel_ids(db)
    nodes = get_payg_ssh_nodes(db)
    if not panels or len(panels) + len(nodes) < 2:
        return None
    return panels, nodes, get_payg_ssh_protocols(db)


def _target_count(cfg):
    value = (cfg or {}).get("value")
    if isinstance(value, dict):
        return sum(len(v or []) for v in value.values())
    if isinstance(value, list):
        return len(value)
    return 1 if value not in (None, "") else 0


def _choose_payg_panel(db, panel_ids):
    """اختيار پنل فعال با ظرفیت و کمترین بار."""
    candidates = []
    for server_id in panel_ids:
        server = db.get_panel_server(int(server_id))
        if not server or not server["is_active"]:
            continue
        info = db.get_panel_capacity_info(int(server_id)) or {}
        if info.get("max_services") is not None and int(info.get("remaining") or 0) < 1:
            continue
        load = float(info.get("percent") or 0) if info.get("max_services") else int(info.get("active_services") or 0)
        candidates.append((load, int(server_id), server))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2] if candidates else None



def get_panel_costs(db):
    """Return configured cost rates keyed by panel and concrete inbound/group."""
    try:
        value = json.loads(str(db.get_setting("payg_panel_costs", "{}") or "{}"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}

def save_panel_costs(db, panel_id: int, entries: list):
    """Replace one panel's target-specific cost rates after strict validation."""
    all_costs = get_panel_costs(db)
    normalized = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        key = str(item.get("target_key", "")).strip()
        if not key or len(key) > 300:
            raise ValueError("شناسه مقصد نامعتبر است.")
        rates = {}
        for field in ("gb_rate", "day_rate", "user_rate"):
            raw = item.get(field, 0)
            try:
                amount = int(raw or 0)
            except (TypeError, ValueError):
                raise ValueError("تعرفه باید عدد صحیح باشد.")
            if amount < 0 or amount > 10**12:
                raise ValueError("تعرفه خارج از محدوده مجاز است.")
            rates[field] = amount
        normalized[key] = rates
    all_costs[str(int(panel_id))] = normalized
    db.set_setting("payg_panel_costs", json.dumps(all_costs, ensure_ascii=False, separators=(",", ":")))
    return normalized

def get_target_cost(db, panel_id: int, target_key: str):
    costs = get_panel_costs(db)
    panel = costs.get(str(int(panel_id)), {})
    return panel.get(str(target_key)) or panel.get("*") or {"gb_rate": 0, "day_rate": 0, "user_rate": 0}


def _target_keys_from_config(raw):
    if not raw:
        return ["*"]
    try:
        cfg = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return ["*"]
    value = cfg.get("value") if isinstance(cfg, dict) else None
    if value in (None, ""):
        return ["*"]
    if isinstance(value, dict):
        keys = [f"{proto}::{inbound}" for proto, items in value.items() for inbound in (items or [])]
        return keys or ["*"]
    if isinstance(value, list):
        return [str(x) for x in value] or ["*"]
    return [str(value)]


def get_service_target_cost(db, panel_id: int, raw_target_config):
    """For a multi-inbound account, use the highest selected target tariff so it cannot underbill."""
    keys = _target_keys_from_config(raw_target_config)
    values = [get_target_cost(db, panel_id, key) for key in keys]
    return {field: max((int(item.get(field, 0) or 0) for item in values), default=0)
            for field in ("gb_rate", "day_rate", "user_rate")}


def custom_plan_cost(db, panel_id: int, volume_gb: int, duration_days: int, user_capacity: int = 1, target_key: str = "*"):
    """Return None when no cost tariff is configured; otherwise calculate the custom-plan invoice."""
    panel = get_panel_costs(db).get(str(int(panel_id)), {})
    rates = panel.get(str(target_key))
    if rates is None or not any(int(rates.get(k, 0) or 0) for k in ("gb_rate", "day_rate", "user_rate")):
        default_rates = panel.get("*")
        if default_rates and any(int(default_rates.get(k, 0) or 0) for k in ("gb_rate", "day_rate", "user_rate")):
            rates = default_rates
        else:
            # The current personal-plan flow selects a panel but does not ask the customer
            # to pick an inbound/group. Use the highest configured target rate as a safe quote.
            configured_targets = [v for k, v in panel.items() if k != "*" and isinstance(v, dict)
                                  and any(int(v.get(field, 0) or 0) for field in ("gb_rate", "day_rate", "user_rate"))]
            if configured_targets:
                rates = {field: max(int(v.get(field, 0) or 0) for v in configured_targets)
                         for field in ("gb_rate", "day_rate", "user_rate")}
    if rates is None:
        return None
    volume = max(0, int(volume_gb or 0))
    days = max(0, int(duration_days or 0))
    users = max(1, int(user_capacity or 1))
    return (volume * int(rates.get("gb_rate", 0) or 0)
            + days * int(rates.get("day_rate", 0) or 0)
            + users * int(rates.get("user_rate", 0) or 0))

def _target_key_from_config(raw):
    """Normalize the exact group/inbound value used by product_targets choices."""
    if not raw:
        return "*"
    try:
        cfg = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return "*"
    value = cfg.get("value") if isinstance(cfg, dict) else None
    if value in (None, ""):
        return "*"
    if isinstance(value, (dict, list)):
        # protocol maps and multi-inbound selections are priced as a combined target.
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _epoch(value=None):
    if value in (None, ""):
        return time.time()
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return time.time()


def calculate_target_cost(used_bytes: int, active_days: int, user_capacity: int, rates: dict, charged_users: int = 0) -> dict:
    """Calculate PAYG variable usage, active-day and one-time capacity charges."""
    gb_rate = max(0, int((rates or {}).get("gb_rate", 0) or 0))
    day_rate = max(0, int((rates or {}).get("day_rate", 0) or 0))
    user_rate = max(0, int((rates or {}).get("user_rate", 0) or 0))
    used = max(0, int(used_bytes or 0))
    days = max(0, int(active_days or 0))
    capacity = max(0, int(user_capacity or 0))
    already_charged = max(0, int(charged_users or 0))
    # Charge traffic proportionally; cumulative byte counters prevent rounding loss across cycles.
    traffic_cost = (used * gb_rate) // GIB if gb_rate else 0
    day_cost = days * day_rate
    new_users = max(0, capacity - already_charged)
    user_cost = new_users * user_rate
    return {"traffic_cost": traffic_cost, "day_cost": day_cost, "user_cost": user_cost,
            "total": traffic_cost + day_cost + user_cost, "new_users": new_users}

def cycle_text(db) -> str:
    """Settlement interval from the admin setting as a Persian phrase (e.g. «۱۰ دقیقه»)."""
    try:
        seconds = int(db.get_setting("payg_cycle_seconds", "600") or 600)
    except (TypeError, ValueError):
        seconds = 600
    seconds = max(60, min(86400, seconds))
    if seconds % 3600 == 0:
        count, unit = seconds // 3600, "ساعت"
    elif seconds % 60 == 0:
        count, unit = seconds // 60, "دقیقه"
    else:
        count, unit = seconds, "ثانیه"
    digits = "یک" if count == 1 else str(count).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    return f"{digits} {unit}"


def get_rates(db):
    try:
        rates = json.loads(db.get_setting("payg_rates", json.dumps(DEFAULT_RATES)))
        if not isinstance(rates, list) or len(rates) != 4:
            raise ValueError
        rates = [max(1, int(x)) for x in rates]
        return rates
    except Exception:
        return list(DEFAULT_RATES)


def _progressive_cost(total_bytes: int, rates: list[int]) -> int:
    """Marginal monthly slabs: first 50GB, next 150GB, next 300GB, then rest."""
    remaining = max(0, int(total_bytes))
    slabs = [50 * GIB, 150 * GIB, 300 * GIB, None]
    cost = 0
    for cap, rate in zip(slabs, rates):
        amount = remaining if cap is None else min(remaining, cap)
        if amount > 0:
            cost += (amount * int(rate) + GIB - 1) // GIB
        remaining -= amount
        if remaining <= 0:
            break
    return int(cost)


def _month_key():
    return datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m")


def _sync_services(db, user_id: int, pool_id: int):
    """Sync explicitly provisioned PayG services and retain each panel's tariff key."""
    attachments = []
    targets = get_payg_targets(db)
    now = _now()
    with db._get_conn() as conn:
        pool_row = conn.execute("SELECT status FROM quota_pools WHERE id=?", (int(pool_id),)).fetchone()
        pool_active = bool(pool_row and str(pool_row["status"]) == "active")
    with db._get_conn() as conn:
        configs = conn.execute(
            "SELECT cc.id,cc.panel_server_id,cc.user_limit,cc.status,cc.created_at,cc.panel_target_config "
            "FROM custom_configs cc JOIN payg_provisioned_services p "
            "ON p.service_kind='vpn' AND p.service_id=('custom_config:' || cc.id) AND p.user_id=cc.user_id "
            "WHERE cc.user_id=?", (int(user_id),)
        ).fetchall()
        for row in configs:
            sid = f"custom_config:{int(row['id'])}"
            panel_id = int(row['panel_server_id']) if row['panel_server_id'] else None
            cfg = row["panel_target_config"] or (targets.get(panel_id, {}) if panel_id else {})
            target_key = json.dumps(_target_keys_from_config(cfg), ensure_ascii=False, separators=(",", ":"))
            capacity = max(1, int(row['user_limit'] or 1))
            snap = conn.execute("SELECT used_bytes FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (sid,)).fetchone()
            baseline = int(snap['used_bytes'] or 0) if snap else -1
            active = 1 if str(row['status']) == 'active' and pool_active else 0
            conn.execute(
                "INSERT OR IGNORE INTO payg_services(user_id,service_kind,service_id,last_billed_bytes,created_at,panel_server_id,target_key,user_capacity,active_since,day_billed_until,is_active) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (int(user_id), 'vpn', sid, baseline, now, panel_id, target_key, capacity, row['created_at'] or now, _epoch(row['created_at']), active)
            )
            prior = conn.execute("SELECT is_active FROM payg_services WHERE user_id=? AND service_kind='vpn' AND service_id=?", (int(user_id),sid)).fetchone()
            if prior and int(prior['is_active'] or 0) != active and active:
                # Resume starts a new active-day interval; downtime is never billed.
                conn.execute("UPDATE payg_services SET active_since=?,day_billed_until=? WHERE user_id=? AND service_kind='vpn' AND service_id=?", (now, time.time(), int(user_id), sid))
            conn.execute("UPDATE payg_services SET panel_server_id=?,target_key=?,user_capacity=?,is_active=? WHERE user_id=? AND service_kind='vpn' AND service_id=?",
                         (panel_id, target_key, capacity, active, int(user_id), sid))
            if active:
                attachments.append(("vpn", sid, panel_id))

        # Every secondary panel link is a separately metered service with its own target tariff.
        links = conn.execute(
            "SELECT l.id,l.panel_server_id,l.target_config,l.status,cc.status AS parent_status,l.created_at,cc.user_limit "
            "FROM config_panel_links l JOIN custom_configs cc ON cc.id=l.custom_config_id "
            "WHERE cc.user_id=? AND EXISTS (SELECT 1 FROM payg_provisioned_services p WHERE p.user_id=cc.user_id AND p.service_kind='vpn' AND p.service_id=('custom_config:' || cc.id))",
            (int(user_id),)
        ).fetchall()
        for row in links:
            sid = f"panel_link:{int(row['id'])}"
            panel_id = int(row['panel_server_id'])
            target_key = json.dumps(_target_keys_from_config(row['target_config']), ensure_ascii=False, separators=(",", ":"))
            capacity = max(1, int(row['user_limit'] or 1))
            snap = conn.execute("SELECT used_bytes FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (sid,)).fetchone()
            baseline = int(snap['used_bytes'] or 0) if snap else -1
            active = 1 if str(row['status']) == 'active' and str(row['parent_status']) == 'active' and pool_active else 0
            conn.execute(
                "INSERT OR IGNORE INTO payg_services(user_id,service_kind,service_id,last_billed_bytes,created_at,panel_server_id,target_key,user_capacity,active_since,day_billed_until,is_active) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (int(user_id), 'vpn', sid, baseline, now, panel_id, target_key, capacity, row['created_at'] or now, _epoch(row['created_at']), active)
            )
            prior = conn.execute("SELECT is_active FROM payg_services WHERE user_id=? AND service_kind='vpn' AND service_id=?", (int(user_id),sid)).fetchone()
            if prior and int(prior['is_active'] or 0) != active and active:
                conn.execute("UPDATE payg_services SET active_since=?,day_billed_until=? WHERE user_id=? AND service_kind='vpn' AND service_id=?", (now, time.time(), int(user_id), sid))
            conn.execute("UPDATE payg_services SET panel_server_id=?,target_key=?,user_capacity=?,is_active=? WHERE user_id=? AND service_kind='vpn' AND service_id=?",
                         (panel_id, target_key, capacity, active, int(user_id), sid))
            if active:
                attachments.append(("vpn", sid, panel_id))

        # SSH services remain on the legacy volume tariff until SSH target tariffs are configured.
        extra_members = conn.execute(
            "SELECT service_kind,service_id,node_id FROM quota_pool_members WHERE pool_id=? AND service_kind='ssh'",
            (int(pool_id),),
        ).fetchall()
        for member in extra_members:
            sid, kind = str(member['service_id']), str(member['service_kind'])
            snap = conn.execute("SELECT used_bytes FROM usage_snapshots WHERE service_kind=? AND service_id=?", (kind,sid)).fetchone()
            baseline = int(snap['used_bytes'] or 0) if snap else -1
            conn.execute("INSERT OR IGNORE INTO payg_services(user_id,service_kind,service_id,last_billed_bytes,created_at,is_active) VALUES(?,?,?,?,?,1)",
                         (int(user_id),kind,sid,baseline,now))
    attached = conflicts = 0
    for kind, sid, node_id in attachments:
        try:
            db.attach_quota_service(pool_id, kind, sid, node_id=node_id)
            attached += 1
        except ValueError as exc:
            conflicts += 1
            logger.warning("PAYG service could not be attached: %s/%s (%s)", kind, sid, exc)
            with db._get_conn() as conn:
                conn.execute("DELETE FROM payg_services WHERE user_id=? AND service_kind=? AND service_id=?", (int(user_id),kind,sid))
    return {"attached": attached, "conflicts": conflicts, "discovered": len(attachments)}


def _deduct_payg_amount(conn, uid: int, amount: int, reason: str) -> bool:
    amount = max(0, int(amount or 0))
    if amount <= 0:
        return True
    with _wallet_tag(conn, uid, 'payg_usage', reason):
        cur = conn.execute("UPDATE users SET referral_credit=referral_credit-? WHERE telegram_id=? AND referral_credit>=?", (amount, int(uid), amount))
    return cur.rowcount == 1


def _bill_panel_fixed_costs(db, uid: int, pool_id: int, service: dict) -> bool:
    """Bill one-time capacity and complete active 24h periods atomically."""
    panel_id = service.get('panel_server_id')
    if not panel_id:
        return True
    try:
        raw_keys = json.loads(str(service.get('target_key') or '"*"'))
    except Exception:
        raw_keys = [str(service.get('target_key') or '*')]
    if not isinstance(raw_keys, list): raw_keys = [str(raw_keys)]
    selected_rates = [get_target_cost(db, int(panel_id), str(key)) for key in raw_keys]
    rates = {field: max((int(item.get(field, 0) or 0) for item in selected_rates), default=0)
             for field in ("gb_rate", "day_rate", "user_rate")}
    now = time.time()
    capacity = max(1, int(service.get('user_capacity') or 1))
    charged = max(0, int(service.get('charged_users') or 0))
    new_users = max(0, capacity - charged)
    day_until = float(service.get('day_billed_until') or _epoch(service.get('active_since') or service.get('created_at')))
    active = bool(service.get('is_active', 1))
    elapsed_days = max(0, int((now - day_until) // 86400)) if active else 0
    user_rate = max(0, int(rates.get('user_rate', 0) or 0))
    day_rate = max(0, int(rates.get('day_rate', 0) or 0))
    user_amount, day_amount = new_users * user_rate, elapsed_days * day_rate
    total = user_amount + day_amount
    with db._get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        wallet = conn.execute("SELECT COALESCE(referral_credit,0) b FROM users WHERE telegram_id=?", (int(uid),)).fetchone()
        balance = int(wallet['b'] or 0) if wallet else 0
        if total > balance:
            return False
        if total and not _deduct_payg_amount(conn, uid, total,
                f"هزینه ظرفیت {new_users} کاربر و {elapsed_days} روز فعال · {service['service_id']}"):
            return False
        if new_users:
            if user_amount:
                cycle = f"fixed:users:{service['service_id']}:{capacity}"
                conn.execute("INSERT OR IGNORE INTO payg_transactions(user_id,cycle_key,service_kind,service_id,used_bytes,amount,rate_snapshot,created_at) VALUES(?,?,?,?,?,?,?,?)",
                             (int(uid),cycle,service['service_kind'],service['service_id'],0,user_amount,
                              json.dumps({"type":"users","capacity":capacity,"rate":user_rate,"panel_id":panel_id,"target_key":service.get('target_key')}),_now()))
            conn.execute("UPDATE payg_services SET charged_users=MAX(charged_users,?) WHERE id=?", (capacity,service['id']))
        if elapsed_days:
            new_until = day_until + elapsed_days * 86400
            if day_amount:
                cycle = f"fixed:days:{service['service_id']}:{int(new_until)}"
                conn.execute("INSERT OR IGNORE INTO payg_transactions(user_id,cycle_key,service_kind,service_id,used_bytes,amount,rate_snapshot,created_at) VALUES(?,?,?,?,?,?,?,?)",
                             (int(uid),cycle,service['service_kind'],service['service_id'],0,day_amount,
                              json.dumps({"type":"days","days":elapsed_days,"rate":day_rate,"panel_id":panel_id,"target_key":service.get('target_key')}),_now()))
            # Advance even when the configured rate is zero: later tariff edits must not bill history.
            conn.execute("UPDATE payg_services SET day_billed_until=? WHERE id=?", (new_until,service['id']))
        if total:
            month = _month_key()
            conn.execute("UPDATE payg_accounts SET month_cost=CASE WHEN month_key=? THEN month_cost+? ELSE ? END,updated_at=? WHERE user_id=?",
                         (month,total,total,_now(),int(uid)))
    return True


def activate_payg(db, user_id: int, existing_pool_id: int = None):
    if db.get_setting("payg_enabled", "1") != "1":
        return {"ok": False, "reason": "disabled"}
    free = is_free_payg_user(db, user_id)
    balance = int(db.get_wallet_credit(user_id) or 0)
    if balance <= 0 and not free:
        return {"ok": False, "reason": "balance"}
    with db._get_conn() as conn:
        existing = conn.execute("SELECT * FROM payg_accounts WHERE user_id=?", (int(user_id),)).fetchone()
    if existing and existing['status'] == 'suspended_admin':
        return {"ok": False, "reason": "suspended_admin"}
    if existing and existing['status'] == 'active':
        sync = _sync_services(db, user_id, int(existing['quota_pool_id']))
        try:
            active_rates = [int(x) for x in json.loads(existing['month_rates'] or '')]
            if len(active_rates) != 4:
                raise ValueError
        except Exception:
            active_rates = get_rates(db)
        active_month_used = int(existing['month_used_bytes'] or 0) if existing['month_key'] == _month_key() else 0
        limit_bytes = 0 if free else _affordable_payg_limit(db, user_id, balance, _billing_base_bytes(db, user_id), active_month_used, active_rates)
        db.set_quota_pool_limit(int(existing['quota_pool_id']), limit_bytes / GIB)
        return {"ok": True, "existing": True, **sync}
    rates = get_rates(db)
    # Temporarily create a generous pool ceiling; after attaching services,
    # rebase it on settled usage and the wallet's exact tiered purchasing power.
    pool_id = (int(existing_pool_id) if existing_pool_id else
               db.create_quota_pool(user_id, 1_000_000_000,
                                    label=get_payg_name(db), metadata={"payg": True}))
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO payg_accounts(user_id,status,quota_pool_id,initial_balance,last_balance,month_key,month_rates,month_used_bytes,month_cost,last_alert_level,created_at,updated_at) "
            "VALUES(?,'active',?,?,?,?,?,0,0,0,?,?) ON CONFLICT(user_id) DO UPDATE SET status='active',quota_pool_id=excluded.quota_pool_id,"
            "initial_balance=excluded.initial_balance,last_balance=excluded.last_balance,month_key=excluded.month_key,month_rates=excluded.month_rates,last_alert_level=0,updated_at=excluded.updated_at",
            (int(user_id), int(pool_id), balance, balance, _month_key(), json.dumps(rates), _now(), _now()),
        )
    sync = _sync_services(db, user_id, pool_id)
    if sync["attached"] <= 0:
        # Do not create an apparently active PAYG account with no enforceable,
        # authoritative usage counters. This also avoids orphan quota pools.
        with db._get_conn() as conn:
            conn.execute("DELETE FROM payg_accounts WHERE user_id=?", (int(user_id),))
        db.delete_quota_pool(pool_id)
        return {"ok": False, "reason": "no_services", **sync}
    billed_base = _billing_base_bytes(db, user_id)
    initial_limit = 0 if free else _affordable_payg_limit(db, user_id, balance, billed_base, 0, rates)
    db.set_quota_pool_limit(pool_id, initial_limit / GIB)
    return {"ok": True, "existing": False, "pool_id": pool_id, **sync}


def payg_status(db, user_id: int):
    with db._get_conn() as conn:
        row = conn.execute("SELECT * FROM payg_accounts WHERE user_id=?", (int(user_id),)).fetchone()
        services = conn.execute("SELECT COUNT(*) n FROM payg_services WHERE user_id=?", (int(user_id),)).fetchone()['n']
        tx = conn.execute("SELECT COALESCE(SUM(amount),0) total FROM payg_transactions WHERE user_id=? AND strftime('%Y-%m',created_at,'+3 hours','+30 minutes')=?",
                          (int(user_id), _month_key())).fetchone()
    if not row:
        return {"active": False, "services": 0, "spent": 0,
                "balance": int(db.get_wallet_credit(user_id) or 0),
                "month_used_bytes": 0, "rates": get_rates(db), "quota_pool_id": 0}
    try:
        account_rates = [int(x) for x in json.loads(row['month_rates'] or '')]
        if len(account_rates) != 4:
            raise ValueError
    except Exception:
        account_rates = get_rates(db)
    return {"active": row['status'] == 'active', "services": int(services), "spent": int(tx['total'] or 0),
            "balance": int(db.get_wallet_credit(user_id) or 0),
            "month_used_bytes": int(row['month_used_bytes'] or 0),
            "rates": account_rates,
            "quota_pool_id": int(row['quota_pool_id'] or 0)}



def build_payg_daily_report(db, day_key: str = None) -> str:
    """گزارش روزانه‌ی کامل PayG بر اساس روز تهران: مصرف، برداشت‌ها و وضعیت سرویس کاربران."""
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    day_key = day_key or _dt.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d")
    with db._get_conn() as conn:
        txs = [dict(r) for r in conn.execute(
            "SELECT user_id,service_kind,service_id,used_bytes,amount,rate_snapshot,created_at FROM payg_transactions "
            "WHERE date(created_at,'+3 hours','+30 minutes')=? ORDER BY user_id,id", (day_key,)).fetchall()]
        activated = [dict(r) for r in conn.execute(
            "SELECT user_id,status,initial_balance,last_balance,month_used_bytes,month_cost,created_at,updated_at "
            "FROM payg_accounts WHERE date(created_at,'+3 hours','+30 minutes')=? ORDER BY user_id", (day_key,)).fetchall()]
        active_accounts = [dict(r) for r in conn.execute(
            "SELECT user_id,status,last_balance,month_used_bytes,month_cost,created_at,updated_at FROM payg_accounts "
            "WHERE status='active' ORDER BY user_id").fetchall()]
        service_counts = {int(r['user_id']): int(r['n'] or 0) for r in conn.execute(
            "SELECT user_id,COUNT(*) n FROM payg_services GROUP BY user_id").fetchall()}
    if not txs and not activated:
        return f"📡 گزارش روزانه PayG — {day_key}\n\nامروز فعالیت یا فعال‌سازی جدیدی ثبت نشده است."
    by_user = {}
    for tx in txs:
        u = by_user.setdefault(int(tx['user_id']), {'bytes':0,'amount':0,'items':[]})
        u['bytes'] += max(0,int(tx['used_bytes'] or 0)); u['amount'] += max(0,int(tx['amount'] or 0)); u['items'].append(tx)
    lines = [f"📡 <b>گزارش روزانه خریدهای پرداخت به‌ازای مصرف</b>", f"📅 {day_key}", "",
             f"👥 کاربران دارای تراکنش: {len(by_user):,}", f"🧾 تعداد برداشت‌ها: {len(txs):,}",
             f"📥 مصرف ثبت‌شده: {sum(int(x['used_bytes'] or 0) for x in txs)/GIB:.3f} GB",
             f"💰 مجموع هزینه/برداشت: {sum(int(x['amount'] or 0) for x in txs):,} تومان",
             f"🆕 فعال‌سازی جدید: {len(activated):,}", f"🟢 حساب‌های فعال فعلی: {len(active_accounts):,}", "", "━━━━━━━━━━━━━━━━━━"]
    user_cache = {}
    for uid in sorted(set(by_user) | {int(x['user_id']) for x in activated}):
        info = by_user.get(uid, {'bytes':0,'amount':0,'items':[]})
        if uid not in user_cache:
            try:
                row = db.get_user(uid)
                user_cache[uid] = row
            except Exception:
                user_cache[uid] = None
        row = user_cache[uid]
        first = (row['first_name'] if row and 'first_name' in row.keys() else '') or ''
        username = (row['username'] if row and 'username' in row.keys() else '') or ''
        name = html.escape(first or 'کاربر')
        handle = f" (@{html.escape(username)})" if username else ''
        lines += [f"\n👤 <b>{name}{handle}</b> — <code>{uid}</code>",
                  f"📊 مصرف امروز: {info['bytes']/GIB:.3f} GB",
                  f"💳 برداشت امروز: {info['amount']:,} تومان",
                  f"🔢 تراکنش‌ها: {len(info['items']):,}"]
        for tx in info['items']:
            try: snap = json.loads(tx.get('rate_snapshot') or '{}')
            except Exception: snap = {}
            if snap.get('type') == 'users': detail = f"ظرفیت {int(snap.get('capacity') or 0)} کاربر"
            elif snap.get('type') == 'days': detail = f"{int(snap.get('days') or 0)} روز سرویس"
            else: detail = f"مصرف {int(tx['used_bytes'] or 0)/GIB:.3f} GB"
            service_label = str(tx['service_id'])
            try:
                sid = str(tx['service_id'])
                if sid.startswith('custom_config:'):
                    cid = int(sid.split(':',1)[1])
                    service = conn = None
                    with db._get_conn() as c:
                        service = c.execute("SELECT cc.username,ps.name panel_name FROM custom_configs cc LEFT JOIN panel_servers ps ON ps.id=cc.panel_server_id WHERE cc.id=?", (cid,)).fetchone()
                    if service: service_label = f"VPN {service['username']} · {service['panel_name'] or 'پنل نامشخص'}"
                elif sid.startswith('panel_link:'):
                    lid = int(sid.split(':',1)[1])
                    with db._get_conn() as c:
                        service = c.execute("SELECT l.username,ps.name panel_name,cc.username parent_username FROM config_panel_links l LEFT JOIN panel_servers ps ON ps.id=l.panel_server_id LEFT JOIN custom_configs cc ON cc.id=l.custom_config_id WHERE l.id=?", (lid,)).fetchone()
                    if service: service_label = f"لینک پنل {service['username']} · {service['panel_name'] or 'پنل'} (سرویس {service['parent_username']})"
            except Exception:
                pass
            lines.append(f"▫️ {html.escape(service_label)}: {detail} — {int(tx['amount'] or 0):,} تومان")
    lines += ["", "━━━━━━━━━━━━━━━━━━", "📌 خلاصه وضعیت حساب‌های فعال:"]
    for acc in active_accounts[:40]:
        uid=int(acc['user_id']); spent=int(acc['month_cost'] or 0); used=int(acc['month_used_bytes'] or 0)
        lines.append(f"• <code>{uid}</code> | سرویس‌ها: {service_counts.get(uid,0)} | ماه: {used/GIB:.2f} GB | هزینه ماه: {spent:,} تومان | موجودی: {int(acc['last_balance'] or 0):,} تومان")
    return "\n".join(lines)


async def send_payg_daily_report(bot, db, day_key: str = None) -> bool:
    text = await asyncio.to_thread(build_payg_daily_report, db, day_key)
    # تلگرام سقف طول پیام دارد؛ متن را در مرز خطوط به چند پیام مستقل تقسیم می‌کنیم.
    chunks, current = [], ""
    for line in text.splitlines():
        candidate = current + ("\n" if current else "") + line
        if len(candidate) > 3500 and current:
            chunks.append(current); current = line
        else:
            current = candidate
    if current: chunks.append(current)
    delivered = True
    for chunk in chunks:
        ok = await report_router.report(bot, db, "payg", chunk, senior_only=True)
        delivered = delivered and bool(ok)
    return delivered

def _billing_base_bytes(db, user_id: int) -> int:
    """Bytes already settled (or grandfathered at activation), excluding pending usage.

    The quota limit must be based on this value, not current usage: otherwise an
    unpaid delta would be added to the next wallet allowance and could overspend.
    """
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT ps.last_billed_bytes,s.used_bytes FROM payg_services ps "
            "LEFT JOIN usage_snapshots s ON s.service_kind=ps.service_kind AND s.service_id=ps.service_id "
            "WHERE ps.user_id=?", (int(user_id),)
        ).fetchall()
    total = 0
    for row in rows:
        billed = int(row['last_billed_bytes'] if row['last_billed_bytes'] is not None else -1)
        if billed < 0:
            continue
        current = int(row['used_bytes'] if row['used_bytes'] is not None else billed)
        total += min(billed, max(0, current))
    return max(0, total)


def _panel_traffic_rates(db, user_id: int):
    """Return (rates, has_panel_services); multi-target services use their highest target rate."""
    with db._get_conn() as conn:
        rows = conn.execute("SELECT panel_server_id,target_key FROM payg_services WHERE user_id=? AND panel_server_id IS NOT NULL", (int(user_id),)).fetchall()
    values = []
    for row in rows:
        try:
            keys = json.loads(str(row["target_key"] or '["*"]'))
        except Exception:
            keys = ["*"]
        if not isinstance(keys, list): keys = [str(keys)]
        selected = [get_target_cost(db, int(row["panel_server_id"]), str(key)) for key in keys]
        values.append(max((int(x.get("gb_rate", 0) or 0) for x in selected), default=0))
    positive = [x for x in values if x > 0]
    return ([min(positive)] * 4 if positive else [0, 0, 0, 0]), bool(rows)


def _pending_panel_fixed_cost(db, user_id: int) -> int:
    """Reserve one-time capacity and already-accrued active-day charges before granting quota."""
    with db._get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT panel_server_id,target_key,user_capacity,charged_users,day_billed_until,is_active "
            "FROM payg_services WHERE user_id=? AND panel_server_id IS NOT NULL", (int(user_id),)).fetchall()]
    reserve = 0
    now = time.time()
    for row in rows:
        try: keys = json.loads(str(row.get("target_key") or '["*"]'))
        except Exception: keys = ["*"]
        if not isinstance(keys, list): keys = [str(keys)]
        selected = [get_target_cost(db, int(row["panel_server_id"]), str(key)) for key in keys]
        rates = {field: max((int(x.get(field, 0) or 0) for x in selected), default=0)
                 for field in ("gb_rate", "day_rate", "user_rate")}
        seats = max(0, int(row.get("user_capacity") or 1) - int(row.get("charged_users") or 0))
        days = max(0, int((now - float(row.get("day_billed_until") or now)) // 86400)) if row.get("is_active") else 0
        reserve += seats * rates["user_rate"] + days * rates["day_rate"]
    return reserve


def _account_usage(db, user_id: int, balance: int):
    """(used, initial, percent) مصرف از اعتبار آخرین شارژ؛ شارژ ثبت‌نشده همین‌جا لحاظ می‌شود."""
    with db._get_conn() as conn:
        row = conn.execute("SELECT initial_balance,last_balance FROM payg_accounts WHERE user_id=?",
                           (int(user_id),)).fetchone()
    if not row:
        return 0, 1, 0.0
    initial = int(row["initial_balance"] or 0)
    if int(balance) > int(row["last_balance"] or 0):
        initial = int(balance)
    initial = max(1, initial)
    used = max(0, initial - int(balance))
    return used, initial, used * 100 / initial


def cutoff_reached(db, user_id: int, balance: int) -> bool:
    """آیا مصرف کاربر به آستانه‌ی قطع رسیده است؟ (۰ = خاموش)"""
    used, _initial, percent = _account_usage(db, user_id, balance)
    return alert_reached(db, 3, used, percent)


def _affordable_payg_limit(db, user_id: int, balance: int, base_bytes: int, month_used_bytes: int, legacy_rates: list[int]):
    if cutoff_reached(db, user_id, balance):
        return max(1, int(base_bytes))
    panel_rates, has_panel = _panel_traffic_rates(db, user_id)
    reserve = _pending_panel_fixed_cost(db, user_id) if has_panel else 0
    usable = max(0, int(balance) - reserve)
    if has_panel and not any(panel_rates):
        return 0 if usable > 0 or reserve == 0 else max(1, int(base_bytes))
    rates = panel_rates if has_panel else legacy_rates
    if has_panel and usable <= 0:
        return max(1, int(base_bytes))
    return _affordable_limit_bytes(usable, rates, base_bytes, month_used_bytes)


def _affordable_limit_bytes(balance: int, rates: list[int], billed_base_bytes: int,
                            month_used_bytes: int = 0) -> int:
    base = max(0, int(billed_base_bytes))
    if balance <= 0:
        # A positive limit equal to settled usage makes the quota reconciler
        # suspend members. Zero would mean unlimited in the existing quota API.
        return max(1, base)
    month_used = max(0, int(month_used_bytes))
    already_due = _progressive_cost(month_used, rates)
    # Find the largest additional byte allowance whose marginal bill is covered
    # by the wallet. This respects the lower marginal rates at higher tiers.
    low = 0
    high = max(1, ((int(balance) + 1) * GIB // max(1, min(rates))) + 1)
    while low < high:
        mid = (low + high + 1) // 2
        due = _progressive_cost(month_used + mid, rates) - already_due
        if due <= int(balance):
            low = mid
        else:
            high = mid - 1
    return max(base + 1, base + low)


def refresh_payg_quota(db, user_id: int):
    """Immediately rebase an active PAYG pool after a wallet top-up."""
    ensure_schema(db)
    with db._get_conn() as conn:
        account = conn.execute("SELECT * FROM payg_accounts WHERE user_id=? AND status='active'",
                               (int(user_id),)).fetchone()
        if not account or not account["quota_pool_id"]:
            return False
        account = dict(account)
    month = _month_key()
    rates = (json.loads(account.get("month_rates") or "[]")
             if account.get("month_key") == month else get_rates(db))
    if len(rates) != 4:
        rates = get_rates(db)
    balance = int(db.get_wallet_credit(user_id) or 0)
    month_used = int(account.get("month_used_bytes") or 0) if account.get("month_key") == month else 0
    if is_free_payg_user(db, user_id):
        db.set_quota_pool_limit(int(account["quota_pool_id"]), 0)
        return True
    limit = _affordable_payg_limit(db, user_id, balance, _billing_base_bytes(db, user_id), month_used, [int(x) for x in rates])
    db.set_quota_pool_limit(int(account["quota_pool_id"]), limit / GIB)
    with db._get_conn() as conn:
        if balance > int(account.get("last_balance") or 0):
            conn.execute("UPDATE payg_accounts SET last_balance=?,initial_balance=?,last_alert_level=0,updated_at=? WHERE user_id=?",
                         (balance, balance, _now(), int(user_id)))
    return True



def _settle_free_account(db, uid: int, pool_id: int, month: str) -> None:
    """ثبت مصرف مدیر/مالک با مبلغ صفر؛ شمارنده‌ها جلو می‌روند و سقف استخر نامحدود می‌ماند."""
    _sync_services(db, uid, pool_id)
    db.set_quota_pool_limit(pool_id, 0)
    now = time.time()
    with db._get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        acc = conn.execute("SELECT month_key FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
        if not acc:
            return
        if acc["month_key"] != month:
            conn.execute("UPDATE payg_accounts SET month_key=?,month_used_bytes=0,month_cost=0 WHERE user_id=?",
                         (month, uid))
        services = [dict(r) for r in conn.execute(
            "SELECT ps.*,s.used_bytes,s.reported_at FROM payg_services ps LEFT JOIN usage_snapshots s "
            "ON s.service_kind=ps.service_kind AND s.service_id=ps.service_id WHERE ps.user_id=? ORDER BY ps.id",
            (uid,)).fetchall()]
        total_delta = 0
        for service in services:
            if service.get("panel_server_id"):
                capacity = max(1, int(service.get("user_capacity") or 1))
                day_until = float(service.get("day_billed_until") or _epoch(service.get("active_since") or service.get("created_at")))
                elapsed = max(0, int((now - day_until) // 86400)) if service.get("is_active", 1) else 0
                conn.execute("UPDATE payg_services SET charged_users=MAX(charged_users,?),day_billed_until=? WHERE id=?",
                             (capacity, day_until + elapsed * 86400, service["id"]))
            if service["used_bytes"] is None:
                continue
            current_bytes = max(0, int(service["used_bytes"] or 0))
            previous = int(service["last_billed_bytes"] if service["last_billed_bytes"] is not None else -1)
            delta = current_bytes - previous if previous >= 0 and current_bytes >= previous else 0
            if current_bytes != previous:
                conn.execute("UPDATE payg_services SET last_billed_bytes=? WHERE id=?", (current_bytes, service["id"]))
            if delta > 0:
                total_delta += delta
                conn.execute(
                    "INSERT OR IGNORE INTO payg_transactions(user_id,cycle_key,service_kind,service_id,used_bytes,amount,rate_snapshot,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (uid, f"{month}:{service['service_kind']}:{service['service_id']}:{current_bytes}",
                     service["service_kind"], service["service_id"], delta, 0,
                     json.dumps({"type": "traffic", "free": "admin"}), _now()))
        if total_delta:
            conn.execute("UPDATE payg_accounts SET month_used_bytes=month_used_bytes+?,updated_at=? WHERE user_id=?",
                         (total_delta, _now(), uid))
        conn.execute("UPDATE payg_accounts SET last_alert_level=0,updated_at=? WHERE user_id=?", (_now(), uid))


class PaygEngine:
    def __init__(self, db, bot=None, interval_seconds=600):
        self.db = db
        self.bot = bot
        ensure_schema(db)
        try:
            configured_interval = int(db.get_setting("payg_cycle_seconds", str(interval_seconds)) or interval_seconds)
        except (TypeError, ValueError):
            configured_interval = int(interval_seconds)
        self.interval_seconds = max(60, min(86400, configured_interval))

    def _bill_once(self):
        current_rates = get_rates(self.db)
        with self.db._get_conn() as conn:
            accounts = [dict(r) for r in conn.execute("SELECT * FROM payg_accounts WHERE status='active'").fetchall()]
        alerts = []
        for account in accounts:
            uid, pool_id = int(account['user_id']), int(account['quota_pool_id'])
            try:
                if is_free_payg_user(self.db, uid):
                    _settle_free_account(self.db, uid, pool_id, _month_key())
                    continue
                current_balance = int(self.db.get_wallet_credit(uid) or 0)
                month = _month_key()
                try:
                    effective_rates = ([int(x) for x in json.loads(account.get('month_rates') or '')]
                                       if account.get('month_key') == month else list(current_rates))
                    if len(effective_rates) != 4 or any(x <= 0 for x in effective_rates):
                        raise ValueError
                except Exception:
                    effective_rates = list(current_rates)
                _sync_services(self.db, uid, pool_id)
                account_month_used = int(account.get('month_used_bytes') or 0) if account.get('month_key') == month else 0
                pre_limit = _affordable_payg_limit(self.db, uid, current_balance,
                                                   _billing_base_bytes(self.db, uid), account_month_used, effective_rates)
                self.db.set_quota_pool_limit(pool_id, pre_limit / GIB)

                with self.db._get_conn() as conn:
                    current = conn.execute("SELECT * FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
                    if not current:
                        continue
                    if current['month_key'] != month:
                        month_rates = list(current_rates)
                        conn.execute("UPDATE payg_accounts SET month_key=?,month_rates=?,month_used_bytes=0,month_cost=0 WHERE user_id=?",
                                     (month, json.dumps(month_rates), uid))
                    else:
                        try:
                            month_rates = [int(x) for x in json.loads(current['month_rates'] or '')]
                            if len(month_rates) != 4 or any(x <= 0 for x in month_rates):
                                raise ValueError
                        except Exception:
                            month_rates = list(current_rates)
                            conn.execute("UPDATE payg_accounts SET month_rates=? WHERE user_id=?", (json.dumps(month_rates), uid))
                    services = [dict(r) for r in conn.execute(
                        "SELECT ps.*,s.used_bytes,s.reported_at FROM payg_services ps LEFT JOIN usage_snapshots s "
                        "ON s.service_kind=ps.service_kind AND s.service_id=ps.service_id WHERE ps.user_id=? ORDER BY ps.id", (uid,)
                    ).fetchall()]

                # A top-up starts a fresh warning sequence. Never infer usage from stale/missing telemetry.
                if current_balance > int(account.get('last_balance') or 0):
                    with self.db._get_conn() as conn:
                        conn.execute("UPDATE payg_accounts SET last_alert_level=0,last_balance=?,initial_balance=? WHERE user_id=?",
                                     (current_balance, current_balance, uid))
                    account['last_alert_level'] = 0
                    account['last_balance'] = current_balance
                    account['initial_balance'] = current_balance

                fixed_insufficient = False
                billing_insufficient = False
                for service in services:
                    if service.get('panel_server_id'):
                        if not _bill_panel_fixed_costs(self.db, uid, pool_id, service):
                            fixed_insufficient = True
                            billing_insufficient = True
                            break
                    if service['used_bytes'] is None or not service['reported_at']:
                        continue
                    try:
                        stamp = datetime.fromisoformat(str(service['reported_at']).replace('Z', '+00:00'))
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=timezone.utc)
                        age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
                        if age < -60 or age > 900:
                            continue
                    except Exception:
                        continue

                    current_bytes = max(0, int(service['used_bytes'] or 0))
                    previous = int(service['last_billed_bytes'] if service['last_billed_bytes'] is not None else -1)
                    if previous < 0:
                        # First fresh sample is a baseline; historical usage is never charged.
                        with self.db._get_conn() as conn:
                            conn.execute("UPDATE payg_services SET last_billed_bytes=? WHERE id=? AND last_billed_bytes<0",
                                         (current_bytes, service['id']))
                        continue
                    if current_bytes < previous:
                        # Provider counter reset: establish a fresh baseline instead of
                        # waiting for the counter to climb back to its old value.
                        with self.db._get_conn() as conn:
                            conn.execute("UPDATE payg_services SET last_billed_bytes=? WHERE id=?",
                                         (current_bytes, service['id']))
                        continue
                    delta = current_bytes - previous
                    if delta <= 0:
                        continue

                    cycle_key = f"{month}:{service['service_kind']}:{service['service_id']}:{current_bytes}"
                    insufficient = False
                    with self.db._get_conn() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        duplicate = conn.execute("SELECT 1 FROM payg_transactions WHERE cycle_key=? AND service_kind=? AND service_id=?",
                                                  (cycle_key, service['service_kind'], service['service_id'])).fetchone()
                        if duplicate:
                            # The transaction and last_billed update are committed together;
                            # this branch only repairs a legacy partial write.
                            conn.execute("UPDATE payg_services SET last_billed_bytes=MAX(last_billed_bytes,?) WHERE id=?",
                                         (current_bytes, service['id']))
                            continue
                        acc = conn.execute("SELECT month_used_bytes,month_key FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
                        before_bytes = int(acc['month_used_bytes'] or 0) if acc and acc['month_key'] == month else 0
                        if service.get('panel_server_id'):
                            panel_rates = get_service_target_cost(self.db, int(service['panel_server_id']), {'value': _target_keys_from_config({'value': json.loads(service.get('target_key') or '["*"]')})})
                            gb_rate = max(0, int(panel_rates.get('gb_rate', 0) or 0))
                            amount = ((current_bytes * gb_rate) // GIB - (previous * gb_rate) // GIB) if gb_rate else 0
                            rate_snapshot = {"type":"traffic","gb_rate":gb_rate,"panel_id":service['panel_server_id'],"target_key":service.get('target_key')}
                        else:
                            amount = max(0, _progressive_cost(before_bytes + delta, month_rates) - _progressive_cost(before_bytes, month_rates))
                            rate_snapshot = month_rates
                        wallet = conn.execute("SELECT COALESCE(referral_credit,0) b FROM users WHERE telegram_id=?", (uid,)).fetchone()
                        balance = int(wallet['b'] or 0) if wallet else 0
                        if amount > balance:
                            # Do not partially charge or advance the counter. The full delta remains
                            # pending and will be billed after the user tops up.
                            insufficient = True
                        else:
                            if amount > 0:
                                with _wallet_tag(conn, uid, 'payg_usage',
                                                 f"مصرف Pay As You Go: {service['service_kind']} {service['service_id']}"):
                                    cur = conn.execute(
                                        "UPDATE users SET referral_credit=referral_credit-? WHERE telegram_id=? AND referral_credit>=?",
                                        (amount, uid, amount))
                                if cur.rowcount != 1:
                                    insufficient = True
                            if not insufficient:
                                conn.execute(
                                    "INSERT INTO payg_transactions(user_id,cycle_key,service_kind,service_id,used_bytes,amount,rate_snapshot,created_at) "
                                    "VALUES(?,?,?,?,?,?,?,?)",
                                    (uid, cycle_key, service['service_kind'], service['service_id'], delta, amount,
                                     json.dumps(rate_snapshot, ensure_ascii=False), _now()))
                                conn.execute("UPDATE payg_services SET last_billed_bytes=? WHERE id=?",
                                             (current_bytes, service['id']))
                                conn.execute("UPDATE payg_accounts SET month_used_bytes=month_used_bytes+?,month_cost=month_cost+?,updated_at=? WHERE user_id=?",
                                             (delta, amount, _now(), uid))
                    if insufficient:
                        billing_insufficient = True
                        logger.warning("PAYG wallet insufficient; preserving unbilled usage for user=%s service=%s/%s",
                                       uid, service['service_kind'], service['service_id'])
                        break

                balance = int(self.db.get_wallet_credit(uid) or 0)
                if fixed_insufficient:
                    # Positive limit equal to already-recorded usage makes the quota reconciler suspend all pool members.
                    self.db.set_quota_pool_limit(pool_id, max(1, _billing_base_bytes(self.db, uid)) / GIB)
                with self.db._get_conn() as conn:
                    latest = conn.execute("SELECT month_used_bytes FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
                    latest_month_used = int(latest['month_used_bytes'] or 0) if latest else 0
                    conn.execute("UPDATE payg_accounts SET last_balance=?,updated_at=? WHERE user_id=?",
                                 (balance, _now(), uid))
                if fixed_insufficient:
                    limit_bytes = max(1, _billing_base_bytes(self.db, uid))
                else:
                    # For mixed-panel pools use the cheapest configured per-GB rate as a conservative shared ceiling.
                    limit_bytes = _affordable_payg_limit(self.db, uid, balance,
                                                        _billing_base_bytes(self.db, uid), latest_month_used, month_rates)
                self.db.set_quota_pool_limit(pool_id, limit_bytes / GIB)
                cut = bool(cutoff_reached(self.db, uid, balance) or balance <= 0
                           or billing_insufficient or fixed_insufficient)
                with self.db._get_conn() as conn:
                    if cut:
                        conn.execute("UPDATE payg_accounts SET cut_at=? WHERE user_id=? AND cut_at=''", (_now(), uid))
                    else:
                        conn.execute("UPDATE payg_accounts SET cut_at='',purged_at='' WHERE user_id=? AND (cut_at<>'' OR purged_at<>'')", (uid,))
                if billing_insufficient or cut:
                    self.db.set_quota_pool_status(pool_id, "exceeded")
                alert = self._alert_payload(uid, account)
                if alert:
                    alerts.append(alert)
            except Exception:
                logger.exception("PAYG billing failed for user=%s", uid)
        return alerts

    def _alert_payload(self, uid, account):
        balance = int(self.db.get_wallet_credit(uid) or 0)
        initial = max(1, int(account.get('initial_balance') or 1))
        used = max(0, initial - balance)
        percent = used * 100 / initial
        if balance <= 0 or alert_reached(self.db, 3, used, percent):
            level = 3
        elif alert_reached(self.db, 2, used, percent):
            level = 2
        elif alert_reached(self.db, 1, used, percent):
            level = 1
        else:
            level = 0
        previous = int(account.get('last_alert_level') or 0)
        if level <= previous:
            return None
        return {"user_id": uid, "level": level,
                "text": render_alert_text(self.db, level, used, initial, balance, percent)}

    async def run_forever(self):
        logger.info("Pay As You Go billing worker started (interval=%ss)", self.interval_seconds)
        while True:
            try:
                alerts = await asyncio.to_thread(self._bill_once)
                if self.bot:
                    for alert in alerts or []:
                        # Persist the threshold before delivery to avoid retrying every cycle
                        # when the user has blocked the bot. A top-up resets the level.
                        with self.db._get_conn() as conn:
                            conn.execute("UPDATE payg_accounts SET last_alert_level=?,updated_at=? WHERE user_id=?",
                                         (alert["level"], _now(), alert["user_id"]))
                        try:
                            await self.bot.send_message(alert["user_id"], alert["text"])
                        except Exception:
                            logger.warning("PAYG alert delivery failed for user=%s; threshold will not be spammed", alert["user_id"])
                await retention_sweep(self.db, self.bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("PAYG worker cycle failed")
            try:
                self.interval_seconds = max(60, min(86400, int(
                    self.db.get_setting("payg_cycle_seconds", str(self.interval_seconds)) or self.interval_seconds
                )))
            except (TypeError, ValueError):
                pass
            await asyncio.sleep(self.interval_seconds)


async def _delete_payg_config(db, uid: int, cid: int) -> bool:
    """یک سرویس ساخته‌شده توسط PayG را از همه سرورها و دیتابیس حذف می‌کند؛ ناموفق بودن حذف از سرور = تلاش مجدد بعدی."""
    from multi_target import delete_linked_panel_users
    sid = f"custom_config:{int(cid)}"
    row = await asyncio.to_thread(db.get_custom_config_by_id, int(cid))
    if row is not None and int(row["user_id"]) == int(uid):
        with db._get_conn() as conn:
            accounts = [dict(r) for r in conn.execute(
                "SELECT account_id,node_id FROM ssh_accounts WHERE custom_config_id=?", (int(cid),)).fetchall()]
        for acc in accounts:
            try:
                from ssh_providers import get_ssh_provider
                from quota_reconciler import _env_secret_resolver
                node = await asyncio.to_thread(db.get_ssh_node, int(acc["node_id"]))
                if node:
                    await get_ssh_provider(node, secret_resolver=_env_secret_resolver).delete_account(acc["account_id"])
            except Exception:
                logger.exception("PAYG retention: SSH delete failed for %s", acc["account_id"])
                return False
        if row["panel_server_id"]:
            server = await asyncio.to_thread(db.get_panel_server, row["panel_server_id"])
            if server:
                try:
                    from panel_providers import get_provider
                    await get_provider(server).delete_user(row["username"])
                except Exception:
                    logger.exception("PAYG retention: panel delete failed for %s", row["username"])
                    return False
        link_ids = [int(l["id"]) for l in await asyncio.to_thread(db.panel_links_for_config, int(cid), False)]
        await delete_linked_panel_users(db, int(cid))
        with db._get_conn() as conn:
            for acc in accounts:
                conn.execute("DELETE FROM ssh_accounts WHERE account_id=?", (acc["account_id"],))
                for table in ("usage_snapshots", "quota_enforcement_state"):
                    conn.execute(f"DELETE FROM {table} WHERE service_kind='ssh' AND service_id=?", (acc["account_id"],))
                conn.execute("DELETE FROM quota_pool_members WHERE service_kind='ssh' AND service_id=?", (acc["account_id"],))
            for key in [sid] + [f"panel_link:{i}" for i in link_ids]:
                conn.execute("DELETE FROM payg_services WHERE user_id=? AND service_id=?", (int(uid), key))
                conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?", (key,))
                conn.execute("DELETE FROM quota_enforcement_state WHERE service_kind='vpn' AND service_id=?", (key,))
                conn.execute("DELETE FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (key,))
        await asyncio.to_thread(db.delete_owned_custom_config, int(cid), int(uid), 0)
    with db._get_conn() as conn:
        conn.execute("DELETE FROM payg_provisioned_services WHERE service_kind='vpn' AND service_id=? AND user_id=?", (sid, int(uid)))
    return True


async def purge_cut_account(db, uid: int) -> dict:
    """سرویس‌های ساخته‌شده توسط PayG برای یک کاربر قطع‌شده را حذف می‌کند (سرویس‌های قدیمیِ متصل‌شده دست‌نخورده می‌مانند)."""
    with db._get_conn() as conn:
        ids = [r["service_id"] for r in conn.execute(
            "SELECT service_id FROM payg_provisioned_services WHERE service_kind='vpn' AND user_id=?", (int(uid),)).fetchall()]
    deleted, ok = 0, True
    for sid in ids:
        try:
            cid = int(str(sid).split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if await _delete_payg_config(db, uid, cid):
            deleted += 1
        else:
            ok = False
    if ok:
        with db._get_conn() as conn:
            account = conn.execute("SELECT quota_pool_id FROM payg_accounts WHERE user_id=?", (int(uid),)).fetchone()
            remaining = conn.execute("SELECT COUNT(*) n FROM payg_services WHERE user_id=?", (int(uid),)).fetchone()["n"]
            if remaining == 0:
                conn.execute("DELETE FROM payg_accounts WHERE user_id=?", (int(uid),))
            else:
                conn.execute("UPDATE payg_accounts SET purged_at=? WHERE user_id=?", (_now(), int(uid)))
        if remaining == 0 and account and account["quota_pool_id"]:
            await asyncio.to_thread(db.delete_quota_pool, int(account["quota_pool_id"]))
    return {"ok": ok, "deleted": deleted}


async def retention_sweep(db, bot=None) -> int:
    """اکانت‌هایی که بیش از مهلت نگهداری قطع مانده‌اند را حذف می‌کند؛ تعداد حساب‌های پاک‌شده را برمی‌گرداند."""
    days = get_retention_days(db)
    if days <= 0:
        return 0
    with db._get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT user_id,cut_at,last_balance FROM payg_accounts "
            "WHERE status='active' AND cut_at<>'' AND purged_at=''").fetchall()]
    done = 0
    for row in rows:
        uid = int(row["user_id"])
        try:
            if is_free_payg_user(db, uid):
                continue
            stamp = datetime.fromisoformat(str(row["cut_at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - stamp).total_seconds() < days * 86400:
                continue
            if int(db.get_wallet_credit(uid) or 0) > int(row["last_balance"] or 0):
                continue
            result = await purge_cut_account(db, uid)
            if result["ok"] and result["deleted"]:
                done += 1
                logger.info("PAYG retention expired; deleted %s services for user=%s", result["deleted"], uid)
                if bot:
                    try:
                        await bot.send_message(uid, tr("🗑 مهلت نگهداری اشتراک شما به پایان رسید و چون کیف پول شارژ نشد، سرویس‌های آن از سرورها حذف شد."))
                    except Exception:
                        logger.warning("PAYG retention notice failed for user=%s", uid)
        except Exception:
            logger.exception("PAYG retention failed for user=%s", uid)
    return done


def _acquire_provision_lock(db, user_id: int) -> bool:
    now = _now()
    with db._get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM payg_provision_locks WHERE julianday(created_at) < julianday('now','-15 minutes')")
        cur = conn.execute("INSERT OR IGNORE INTO payg_provision_locks(user_id,created_at) VALUES(?,?)",
                           (int(user_id), now))
        return cur.rowcount == 1


def _release_provision_lock(db, user_id: int) -> None:
    with db._get_conn() as conn:
        conn.execute("DELETE FROM payg_provision_locks WHERE user_id=?", (int(user_id),))


async def _rollback_payg_vpn(db, server, provisioned: dict) -> None:
    """Best-effort rollback if a newly created PayG config cannot be enrolled."""
    username = str(provisioned.get("username") or "")
    custom_id = int(provisioned.get("custom_config_id") or 0)
    if username:
        try:
            from panel_providers import get_provider
            await get_provider(server).delete_user(username)
        except Exception:
            logger.exception("PAYG rollback could not delete remote user %s", username)
    if custom_id:
        sid = f"custom_config:{custom_id}"
        with db._get_conn() as conn:
            conn.execute("DELETE FROM payg_services WHERE service_kind='vpn' AND service_id=?", (sid,))
            conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?", (sid,))
            conn.execute("DELETE FROM quota_enforcement_state WHERE service_kind='vpn' AND service_id=?", (sid,))
            conn.execute("DELETE FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (sid,))
            conn.execute("DELETE FROM custom_configs WHERE id=?", (custom_id,))


async def _provision_payg_multi(db, uid: int, panel_ids, node_ids, protocols) -> dict:
    """ساخت یک سرویس PayG روی همه پنل‌ها (با اینباند انتخاب‌شده‌ی هرکدام) و نودهای SSH.

    پنل اول سرویس اصلی (custom_config) است، بقیه با config_panel_links وصل می‌شوند و
    ساب اختصاصی همه را یکجا می‌دهد. مصرف هر مقصد جدا خوانده و جمعش صورتحساب می‌شود.
    همه‌یا‌هیچ: با هر خطا هرچه ساخته شده پاک می‌شود. ثبت‌نام در حساب PayG هم داخل همین تابع است."""
    import dedicated_sub
    from direct_panel_provision import _provision_vpn, provision_ssh_direct
    from panel_providers import get_provider
    from ssh_service import node_protocols

    if not dedicated_sub.is_enabled(db):
        raise RuntimeError(MULTI_NEEDS_DSUB)
    off_message = dedicated_sub.panels_dsub_off_message(db, panel_ids)
    if off_message:
        raise RuntimeError(off_message)
    targets = get_payg_targets(db)
    for sid in panel_ids:
        server = db.get_panel_server(int(sid))
        if not server or not server["is_active"]:
            raise RuntimeError(f"پنل #{sid} فعال نیست؛ مدیریت باید انتخاب پنل‌های PayG را اصلاح کند.")
        if not db.panel_has_capacity(int(sid), 1):
            raise RuntimeError(f"ظرفیت پنل «{server['name']}» تکمیل است.")
    nodes_by_id = {int(n["id"]): n for n in db.list_ssh_nodes(active_only=True)}
    node_plan = []
    for nid in node_ids:
        node = nodes_by_id.get(int(nid))
        if not node or node.get("node_type") != "linux":
            raise RuntimeError(f"نود SSH #{nid} فعال نیست؛ مدیریت باید انتخاب نودهای PayG را اصلاح کند.")
        picks = [p for p in protocols if p in node_protocols(node)]
        if not picks:
            raise RuntimeError(f"هیچ‌یک از پروتکل‌های انتخابی PayG روی نود «{node.get('name') or nid}» نصب نیست.")
        node_plan.append((int(nid), picks))

    with db._get_conn() as conn:
        account = conn.execute("SELECT status,quota_pool_id FROM payg_accounts WHERE user_id=?", (int(uid),)).fetchone()
    created_pool = False
    # رفع باگ «سرویس VPN یا استخر سهمیه پیدا نشد»: attach_custom_config_to_quota_pool فقط به استخرِ
    # status='active' وصل می‌شود، ولی استخر حساب PayG موجود می‌تواند stale/exceeded/expired/error شده باشد
    # (مثلاً وقتی همه‌ی سرویس‌هایش حذف شده یا موجودی تمام شده بود) یا اصلاً پاک شده باشد. قبلاً در این
    # حالت ساخت سرویس جدید روی همه‌ی پنل‌ها انجام می‌شد و بعد با همین خطا کامل rollback می‌شد.
    pool_restore = {"status": None, "old_pool_id": None}
    if account and account["status"] == "active" and account["quota_pool_id"]:
        pool_id = int(account["quota_pool_id"])
        with db._get_conn() as conn:
            pool_row = conn.execute("SELECT user_id,status FROM quota_pools WHERE id=?", (pool_id,)).fetchone()
        if pool_row and int(pool_row["user_id"]) == int(uid):
            if str(pool_row["status"]) != "active":
                pool_restore["status"] = str(pool_row["status"])
                # تا چرخه‌ی بعدی quota_reconciler فعال می‌ماند؛ اگر هنوز سقف/موجودی تمام باشد همان‌جا دوباره تعلیق می‌شود.
                db.set_quota_pool_status(pool_id, "active")
        else:
            pool_restore["old_pool_id"] = pool_id
            pool_id = int(db.create_quota_pool(int(uid), 1_000_000_000, label=get_payg_name(db), metadata={"payg": True}))
            created_pool = True
            with db._get_conn() as conn:
                conn.execute("UPDATE payg_accounts SET quota_pool_id=? WHERE user_id=?", (pool_id, int(uid)))
    else:
        pool_id = int(db.create_quota_pool(int(uid), 1_000_000_000, label=get_payg_name(db), metadata={"payg": True}))
        created_pool = True

    ssh_items, panel_users, link_ids = [], [], []
    state = {"primary": None}

    async def rollback():
        for item in ssh_items:
            try:
                from ssh_providers import get_ssh_provider
                from quota_reconciler import _env_secret_resolver
                node = nodes_by_id.get(int(item["node_id"]))
                await get_ssh_provider(node, secret_resolver=_env_secret_resolver).delete_account(item["account_id"])
            except Exception:
                logger.exception("PAYG multi rollback: SSH delete failed for %s", item.get("account_id"))
            with db._get_conn() as conn:
                conn.execute("DELETE FROM ssh_accounts WHERE account_id=?", (item["account_id"],))
                for table in ("usage_snapshots", "quota_enforcement_state"):
                    conn.execute(f"DELETE FROM {table} WHERE service_kind='ssh' AND service_id=?", (item["account_id"],))
                conn.execute("DELETE FROM quota_pool_members WHERE service_kind='ssh' AND service_id=?", (item["account_id"],))
        for sid, username in panel_users:
            try:
                await get_provider(db.get_panel_server(int(sid))).delete_user(username)
            except Exception:
                logger.exception("PAYG multi rollback: panel user delete failed %s on %s", username, sid)
        primary = state["primary"]
        if primary:
            try:
                db.delete_config_panel_links(int(primary["custom_config_id"]))
            except Exception:
                logger.exception("PAYG multi rollback: link cleanup failed")
            sid_key = f"custom_config:{int(primary['custom_config_id'])}"
            with db._get_conn() as conn:
                conn.execute("DELETE FROM payg_provisioned_services WHERE service_kind='vpn' AND service_id=?", (sid_key,))
                conn.execute("DELETE FROM payg_services WHERE service_kind='vpn' AND service_id=?", (sid_key,))
                conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?", (sid_key,))
                conn.execute("DELETE FROM quota_enforcement_state WHERE service_kind='vpn' AND service_id=?", (sid_key,))
                conn.execute("DELETE FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (sid_key,))
                conn.execute("DELETE FROM custom_configs WHERE id=?", (int(primary["custom_config_id"]),))
        if pool_restore["old_pool_id"] is not None:
            with db._get_conn() as conn:
                conn.execute("UPDATE payg_accounts SET quota_pool_id=? WHERE user_id=?",
                             (pool_restore["old_pool_id"], int(uid)))
        if created_pool:
            db.delete_quota_pool(pool_id)
        elif pool_restore["status"]:
            try:
                db.set_quota_pool_status(pool_id, pool_restore["status"])
            except Exception:
                logger.exception("PAYG multi rollback: pool status restore failed")

    try:
        ssh_product_base = {"name": get_payg_name(db), "auto_provision_volume_gb": 0, "duration_days": 0}
        for nid, picks in node_plan:
            for proto in picks:
                prod = dict(ssh_product_base, provision_ssh_node_id=nid, provision_ssh_protocol=proto)
                built = await provision_ssh_direct(db, prod, quantity=1, user_id=int(uid), order_id=None,
                                                   allow_openvpn=True, node_id=nid, pool_id=pool_id, protocol=proto)
                ssh_items.extend(built)
                if any(not b.get("accounting_ready") for b in built):
                    raise RuntimeError(f"نود #{nid} شمارنده‌ی مصرف معتبر ندارد؛ این نود برای Pay As You Go قابل استفاده نیست.")

        primary_username = None
        for index, sid in enumerate(panel_ids):
            fake_product = {
                "id": None, "name": get_payg_name(db), "auto_provision_volume_gb": 0, "duration_days": 0,
                "provision_server_id": int(sid), "provision_ssh_node_id": None, "provision_ssh_protocol": "ssh",
                "is_auto_provision": 1, "base_users": 0, "extra_user_price": 0, "max_users": 0,
            }
            override = json.dumps(targets[int(sid)], ensure_ascii=False) if int(sid) in targets else None
            built = await _provision_vpn(db, fake_product, quantity=1, user_id=int(uid), order_id=None,
                                         shared_pool=True, server_id=int(sid), register=(index == 0),
                                         target_config_override=override)
            item = built[0]
            panel_users.append((int(sid), item["username"]))
            if index == 0:
                if not item.get("custom_config_id") or not item.get("subscription_url"):
                    raise RuntimeError("ساخت سرویس اصلی روی پنل کامل نشد.")
                state["primary"] = item
                primary_username = item["username"]
                with db._get_conn() as conn:
                    conn.execute("INSERT OR REPLACE INTO payg_provisioned_services(service_kind,service_id,user_id,created_at) "
                                 "VALUES('vpn',?,?,?)", (f"custom_config:{int(item['custom_config_id'])}", int(uid), _now()))
                db.attach_custom_config_to_quota_pool(pool_id, int(item["custom_config_id"]))
                for ssh_item in ssh_items:
                    db.link_ssh_account_to_config(ssh_item["account_id"], int(item["custom_config_id"]))
                snap_key = f"custom_config:{int(item['custom_config_id'])}"
            else:
                link_id = db.add_config_panel_link(int(state["primary"]["custom_config_id"]), int(sid), item["username"],
                                                   item["subscription_url"], target_config=targets.get(int(sid)))
                link_ids.append(link_id)
                db.attach_quota_service(pool_id, "vpn", f"panel_link:{link_id}", node_id=int(sid))
                snap_key = f"panel_link:{link_id}"
            # Authoritative usage baseline per panel; never bill a panel without byte counters.
            server = db.get_panel_server(int(sid))
            usage = await get_provider(server).get_user_usage(item["username"])
            if not isinstance(usage, dict) or usage.get("used_bytes") is None or int(usage["used_bytes"]) < 0:
                raise RuntimeError(f"پنل «{server['name']}» شمارنده مصرف معتبر ندارد؛ برای Pay As You Go قابل استفاده نیست.")
            db.record_usage_snapshot("vpn", snap_key, int(usage["used_bytes"]),
                                     uploaded_bytes=usage.get("uploaded_bytes", 0),
                                     downloaded_bytes=usage.get("downloaded_bytes", 0),
                                     source=f"panel:{server['panel_type']}", reported_at=usage.get("reported_at") or _now())

        primary = state["primary"]
        link = dedicated_sub.link_for_config(db, int(primary["custom_config_id"]))
        if not link:
            raise RuntimeError("ساخت لینک ساب اختصاصی ناموفق بود.")
        enrolled = await asyncio.to_thread(activate_payg, db, int(uid), pool_id if created_pool else None)
        sid_key = f"custom_config:{int(primary['custom_config_id'])}"
        with db._get_conn() as conn:
            member = conn.execute("SELECT 1 FROM payg_services WHERE user_id=? AND service_kind='vpn' AND service_id=?",
                                  (int(uid), sid_key)).fetchone()
        if not enrolled.get("ok") or not member:
            raise RuntimeError("اتصال سرویس ساخته‌شده به حساب مصرفی ناموفق بود.")
    except Exception:
        await rollback()
        raise
    return {"username": primary_username, "custom_config_id": int(primary["custom_config_id"]),
            "subscription_url": link, "panels": len(panel_ids), "nodes": len(node_plan),
            "ssh_accounts": len(ssh_items)}


def _central_link(db, custom_config_id, upstream_url) -> str:
    """لینک ساب مرکزی سرویس PayG (هر سرویس PayG همیشه ساب مرکزی می‌گیرد، چه تک‌پنلی چه چندمقصدی).
    اگر ساب مرکزی خاموش باشد یا خطایی رخ دهد همان لینک پنل برمی‌گردد."""
    url = str(upstream_url or "").strip()
    try:
        import dedicated_sub
        return str(dedicated_sub.display_link(db, int(custom_config_id), url) or url).strip()
    except Exception:
        return url


def _is_multi_service(db, custom_config_id: int) -> bool:
    with db._get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) n FROM config_panel_links WHERE custom_config_id=? AND status='active'",
                         (int(custom_config_id),)).fetchone()["n"]
        m = conn.execute("SELECT COUNT(*) n FROM ssh_accounts WHERE custom_config_id=? AND status='active'",
                         (int(custom_config_id),)).fetchone()["n"]
    return bool(n or m)


PAYG_MIN_BALANCE_KEY = "payg_min_balance"
PAYG_MIN_BALANCE_MAX = 10**10
PAYG_DELIVERY_TEXT_KEY = "payg_delivery_text"
PAYG_DELIVERY_PHOTO_KEY = "payg_delivery_photo"
PAYG_DELIVERY_TEXT_MAX = 3500
_CAPTION_LIMIT = 1024


def render_delivery_text(db, default_text: str, username: str, safe_url: str) -> str:
    """Return the admin-defined delivery text with placeholders filled, or the default text."""
    custom = str(db.get_setting(PAYG_DELIVERY_TEXT_KEY, "") or "").strip()
    if not custom:
        return default_text
    link = f'<a href="{safe_url}">دریافت لینک اشتراک</a>'
    text = (custom.replace("{username}", html.escape(str(username)))
            .replace("{cycle}", cycle_text(db))
            .replace("{link}", link)
            .replace("{url}", safe_url))
    if "{link}" not in custom and "{url}" not in custom:
        text += f"\n\n🔗 {link}"
    return text


PAYG_STATUS_TEXT_ACTIVE_KEY = "payg_status_text_active"
PAYG_STATUS_TEXT_INACTIVE_KEY = "payg_status_text_inactive"
PAYG_STATUS_TEXT_MAX = 3000
# متغیرهای قابل استفاده در متن صفحه‌ی «Pay As You Go» (پیام وضعیت و جزئیات مصرف)
PAYG_STATUS_PLACEHOLDERS = ("balance", "spent", "used_gb", "services", "cycle",
                            "min_balance", "panels", "free_note", "links")


_PAYG_RATE_LINE = ("تعرفه هر سرویس بر اساس پنل و گروه/اینباند محل ساخت محاسبه می‌شود؛ "
                   "هزینه ترافیک مصرفی، روزهای فعال و ظرفیت کاربران از کیف پول مشترک کسر خواهد شد.")
_PAYG_SUPPORTED_LINE = "سرویس‌های قابل صورتحساب فعلی: VPN و SSH با شمارنده مصرف معتبر."


def _default_status_template_raw(active: bool) -> str:
    """متن پیش‌فرض صفحه‌ی Pay As You Go به‌شکل قالب (با متغیرها)؛ معادل پیامی که ربات وقتی متن سفارشی
    ذخیره نشده نشان می‌دهد. پنل وب این را از ابتدا داخل فیلد می‌گذارد تا مدیر مستقیم ویرایشش کند.
    اگر متن ذخیره‌شده دقیقاً همین باشد به‌صورت «خالی» ذخیره می‌شود (= همان پیام پیش‌فرض و ترجمه‌ی خودکار)."""
    if active:
        return ("💳 <b>Pay As You Go</b>\n\n"
                "{free_note}\n"
                "وضعیت: فعال\n"
                "موجودی کیف پول: {balance} تومان\n"
                "هزینه این ماه: {spent} تومان\n"
                "مصرف ثبت‌شده: {used_gb} GB\n"
                "سرویس‌های متصل: {services}\n"
                f"{_PAYG_RATE_LINE}\n{_PAYG_SUPPORTED_LINE}\n"
                "حداقل موجودی کیف پول برای ساخت سرویس جدید: {min_balance} تومان\n"
                "تسویه مصرف هر {cycle} انجام می‌شود.\n"
                "پنل‌های فعال ساخت سرویس: {panels}\n"
                "برای ساخت سرویس مصرفی جدید از دکمه زیر استفاده کنید.")
    return ("💳 <b>Pay As You Go</b>\n\n"
            "موجودی کیف پول: {balance} تومان\n"
            f"{_PAYG_RATE_LINE}\n{_PAYG_SUPPORTED_LINE}\n"
            "حداقل موجودی کیف پول برای ساخت سرویس جدید: {min_balance} تومان\n"
            "با ساخت سرویس مصرفی، حجم و زمان ثابت نخواهید داشت و هزینه از کیف پول کسر می‌شود.\n"
            "{free_note}\n"
            "برای شروع، کیف پول باید موجودی مثبت داشته باشد.")


def default_status_template(active: bool) -> str:
    return _n(_default_status_template_raw(active))


def render_status_text(db, active: bool, values: dict):
    """Admin-defined PayG status text with placeholders filled; None means use the default text."""
    key = PAYG_STATUS_TEXT_ACTIVE_KEY if active else PAYG_STATUS_TEXT_INACTIVE_KEY
    custom = str(db.get_setting(key, "") or "").strip()
    if not custom:
        return None
    links = str(values.get("links", "") or "")
    for name in PAYG_STATUS_PLACEHOLDERS:
        if name == "links":
            continue
        custom = custom.replace("{" + name + "}", str(values.get(name, "")))
    if "{links}" in custom:
        return custom.replace("{links}", links)
    return custom + links


async def send_delivery_message(message, db, default_text: str, username: str, safe_url: str) -> None:
    """Send the PayG config message with the admin-defined text and photo, falling back to the default."""
    text = render_delivery_text(db, default_text, username, safe_url)
    photo = str(db.get_setting(PAYG_DELIVERY_PHOTO_KEY, "") or "").strip()
    try:
        if photo:
            if len(text) <= _CAPTION_LIMIT:
                await message.answer_photo(photo, caption=text, parse_mode="HTML")
                return
            await message.answer_photo(photo)
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        if text == default_text and not photo:
            raise
        logger.exception("PAYG custom delivery message failed; falling back to default")
        await message.answer(default_text, parse_mode="HTML", disable_web_page_preview=True)



async def _report_payg_event(bot, db, uid: int, title: str, details: dict = None):
    """ارسال رویداد فعال‌سازی/ساخت سرویس PayG به تاپیک گزارش خریدها."""
    try:
        import report_router
        row = await asyncio.to_thread(db.get_user, int(uid))
        first = (row['first_name'] if row and 'first_name' in row.keys() else '') or 'کاربر'
        username = (row['username'] if row and 'username' in row.keys() else '') or ''
        handle = f" (@{html.escape(username)})" if username else ''
        lines = [f"📡 <b>{html.escape(title)}</b>", "", f"👤 {html.escape(first)}{handle}", f"🆔 <code>{int(uid)}</code>"]
        details = details or {}
        for label, value in details.items():
            if value is not None and value != '':
                lines.append(f"▫️ {html.escape(str(label))}: {html.escape(str(value))}")
        lines.append(f"🕒 {_now()}")
        await report_router.report(bot, db, 'payg', '\n'.join(lines), senior_only=True)
    except Exception:
        logger.exception("PAYG event report failed for user=%s", uid)


def create_payg_router(db, is_main_bot=True):
    router = Router(name="payg_router")
    if not is_main_bot:
        return router
    ensure_schema(db)

    def menu(active=False, configured=False):
        rows = [[InlineKeyboardButton(text=tr("🚀 ساخت سرویس مصرفی جدید"), callback_data="payg:provision")]]
        rows.extend([
            [InlineKeyboardButton(text=tr("💰 شارژ کیف پول"), callback_data="acct:wallet")],
            [InlineKeyboardButton(text=tr("🧾 تاریخچه برداشت‌ها"), callback_data="payg:history")],
            [InlineKeyboardButton(text=tr("📊 وضعیت و جزئیات مصرف"), callback_data="payg:status")],
            [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="back_categories")],
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show(message, user_id):
        status = payg_status(db, user_id)
        balance = int(db.get_wallet_credit(user_id) or 0)
        min_balance = get_min_balance(db)
        panel_ids = get_usable_payg_panel_ids(db)
        panel_names = []
        for pid in panel_ids:
            panel = await asyncio.to_thread(db.get_panel_server, int(pid))
            if panel and panel["is_active"]:
                panel_names.append(str(panel["name"] or f"{tr('پنل')} {pid}"))

        with db._get_conn() as conn:
            service_rows = conn.execute(
                "SELECT cc.id,cc.username,cc.subscription_url,cc.panel_server_id,ps.name AS panel_name "
                "FROM payg_provisioned_services p JOIN custom_configs cc "
                "ON p.service_kind='vpn' AND p.service_id=('custom_config:' || cc.id) "
                "LEFT JOIN panel_servers ps ON ps.id=cc.panel_server_id "
                "WHERE p.user_id=? AND cc.status='active' ORDER BY cc.id DESC",
                (int(user_id),),
            ).fetchall()

        free = is_free_payg_user(db, user_id)
        rate_text = tr(
            "تعرفه هر سرویس بر اساس پنل و گروه/اینباند محل ساخت محاسبه می‌شود؛ "
            "هزینه ترافیک مصرفی، روزهای فعال و ظرفیت کاربران از کیف پول مشترک کسر خواهد شد."
        ) + "\n"
        supported_text = tr("سرویس‌های قابل صورتحساب فعلی: VPN و SSH با شمارنده مصرف معتبر.") + "\n"
        if min_balance:
            supported_text += _tformat(
                "حداقل موجودی کیف پول برای ساخت سرویس جدید: {amount} تومان",
                amount=f"{min_balance:,}",
            ) + "\n"

        if status["active"]:
            text = _n("💳 <b>Pay As You Go</b>\n\n")
            if free:
                text += tr("🎁 حالت رایگان مدیریت: بدون کسر از کیف پول و بدون سقف حجم") + "\n"
            text += _tformat(
                "وضعیت: فعال\nموجودی کیف پول: {balance} تومان\n",
                balance=f"{balance:,}",
            )
            text += _tformat("هزینه این ماه: {spent} تومان\n", spent=f"{status['spent']:,}")
            text += _tformat("مصرف ثبت‌شده: {used} GB\n", used=f"{int(status.get('month_used_bytes') or 0)/GIB:.3f}")
            text += _tformat("سرویس‌های متصل: {services}\n", services=status["services"])
            text += rate_text + supported_text
            text += _tformat("تسویه مصرف هر {cycle} انجام می‌شود.\n", cycle=cycle_text(db))
            if panel_names:
                text += _tformat("پنل‌های فعال ساخت سرویس: {panels}\n", panels=", ".join(panel_names))
            else:
                text += tr("⚠️ پنل فعالی برای ساخت سرویس انتخاب نشده است.") + "\n"
            text += tr("برای ساخت سرویس مصرفی جدید از دکمه زیر استفاده کنید.")
        else:
            text = _n("💳 <b>Pay As You Go</b>\n\n")
            text += _tformat("موجودی کیف پول: {balance} تومان\n", balance=f"{balance:,}")
            text += rate_text + supported_text
            text += tr("با ساخت سرویس مصرفی، حجم و زمان ثابت نخواهید داشت و هزینه از کیف پول کسر می‌شود.") + "\n"
            text += (
                tr("🎁 حساب شما مدیریتی است؛ بدون شارژ کیف پول و بدون هزینه می‌توانید سرویس بسازید.")
                if free else tr("برای شروع، کیف پول باید موجودی مثبت داشته باشد.")
            )

        if not panel_names:
            text += "\n\n" + tr("⚠️ هنوز پنل فعال ساخت سرویس توسط مدیریت انتخاب نشده است.")

        links_text = ""
        if service_rows:
            links_text += "\n\n" + tr("🔗 <b>لینک‌های اشتراک اختصاصی فعال:</b>")
            for item in service_rows:
                url = str(item["subscription_url"] or "").strip()
                multi = await asyncio.to_thread(_is_multi_service, db, int(item["id"]))
                url = await asyncio.to_thread(_central_link, db, int(item["id"]), url)
                if not url:
                    continue
                safe_url = url.replace("&", "&amp;").replace('"', "&quot;")
                label = str(item["username"] or f"{tr('سرویس')} {item['id']}")
                panel_label = (
                    tr("چندمقصدی") if multi
                    else str(item["panel_name"] or f"{tr('پنل')} {item['panel_server_id']}")
                )
                links_text += f"\n• {label} · {panel_label}: <a href=\"{safe_url}\">{tr('باز کردن لینک')}</a>"

        custom_text = render_status_text(db, bool(status["active"]), {
            "balance": f"{balance:,}",
            "spent": f"{int(status.get('spent') or 0):,}",
            "used_gb": f"{int(status.get('month_used_bytes') or 0)/GIB:.3f}",
            "services": status["services"],
            "cycle": cycle_text(db),
            "min_balance": f"{min_balance:,}" if min_balance else "0",
            "panels": html.escape(", ".join(panel_names)) if panel_names else tr("پنل فعالی انتخاب نشده است"),
            "free_note": tr("🎁 حالت رایگان مدیریت: بدون کسر از کیف پول و بدون سقف حجم") if free else "",
            "links": links_text,
        })
        with db._get_conn() as conn:
            configured = conn.execute(
                "SELECT 1 FROM payg_accounts WHERE user_id=?", (int(user_id),)
            ).fetchone() is not None
        markup = menu(status["active"], configured)
        if custom_text:
            try:
                await message.answer(custom_text, reply_markup=markup, parse_mode="HTML")
                return
            except Exception:
                logger.exception("PAYG custom status text failed; falling back to default")
        await message.answer(text + links_text, reply_markup=markup, parse_mode="HTML")

    @router.message(Command("payg"))
    async def payg_command(message: Message):
        await show(message, message.from_user.id)

    @router.message(F.text.func(lambda t: t in button_texts(db)))
    async def payg_menu_button(message: Message):
        await show(message, message.from_user.id)

    @router.callback_query(F.data == "mm:btn_payg")
    async def payg_inline_menu_button(call: CallbackQuery):
        await call.answer()
        await show(call.message, call.from_user.id)

    @router.callback_query(F.data == "payg:open")
    async def payg_open_from_buy(call: CallbackQuery):
        await call.answer()
        if db.get_setting("payg_enabled", "1") != "1":
            return
        try:
            await call.message.delete()
        except Exception:
            pass
        await show(call.message, call.from_user.id)

    @router.callback_query(F.data == "payg:status")
    async def payg_status_callback(call: CallbackQuery):
        await call.answer()
        await show(call.message, call.from_user.id)

    @router.callback_query(F.data == "payg:history")
    async def payg_history_callback(call: CallbackQuery):
        await call.answer()
        with db._get_conn() as conn:
            rows = conn.execute("SELECT service_kind,used_bytes,amount,rate_snapshot,created_at FROM payg_transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (call.from_user.id,)).fetchall()
        if not rows:
            await call.message.answer(tr("هنوز تراکنشی برای Pay As You Go ثبت نشده است."))
            return
        lines = [tr("🧾 <b>آخرین برداشت‌های Pay As You Go</b>")]
        for row in rows:
            try: snap = json.loads(row["rate_snapshot"] or "{}")
            except Exception: snap = {}
            if snap.get("type") == "users": detail = _tformat("ظرفیت {amount} کاربر", amount=int(snap.get('capacity') or 0))
            elif snap.get("type") == "days": detail = _tformat("{amount} روز فعال", amount=int(snap.get('days') or 0))
            else: detail = _tformat("ترافیک {amount} GB", amount=f"{int(row['used_bytes'])/GIB:.3f}")
            lines.append(f"• {row['service_kind'].upper()} | {detail} | {int(row['amount']):,} {tr('تومان')} | {str(row['created_at'])[:16]}")
        await call.message.answer("\n".join(lines), parse_mode="HTML")

    async def _multi_provision_flow(call: CallbackQuery, uid: int, plan):
        panel_ids, node_ids, protocols = plan
        if not await asyncio.to_thread(_acquire_provision_lock, db, uid):
            await call.message.answer(tr("⏳ درخواست ساخت سرویس شما در حال پردازش است؛ لطفاً چند لحظه صبر کنید."))
            return
        try:
            try:
                result = await _provision_payg_multi(db, uid, panel_ids, node_ids, protocols)
                await _report_payg_event(call.bot, db, uid, "سرویس PayG جدید ساخته شد", {
                    "نام کاربری": result.get("username"), "مقصدها": f"{result.get('panels',0)} پنل + {result.get('nodes',0)} نود",
                    "تعداد SSH": result.get("ssh_accounts", 0), "نوع سرویس": "پرداخت به‌ازای مصرف",
                    "وضعیت": "فعال",
                })
            except Exception as exc:
                logger.exception("PAYG multi-target provisioning failed for user=%s", uid)
                await call.message.answer(_tformat("⛔️ ساخت سرویس Pay As You Go ناموفق بود: {error}\nهیچ هزینه مصرفی برای این سرویس ثبت نشده است.", error=str(exc)[:250]))
                return
            try:
                safe_url = str(result["subscription_url"]).replace("&", "&amp;").replace('"', "&quot;")
                default_text = (
                    tr("✅ <b>سرویس Pay As You Go ساخته شد.</b>") + "\n\n"
                    + _tformat("👤 نام کاربری: <code>{username}</code>\n", username=result["username"])
                    + _tformat("🧩 مقصدها: {panels} پنل + {nodes} نود\n", panels=result["panels"], nodes=result["nodes"])
                    + tr("📦 حجم: پرداخت به‌ازای مصرف\n⏳ مدت: بدون انقضای ثابت\n")
                    + (tr("🎁 رایگان برای مدیریت؛ هزینه‌ای کسر نمی‌شود.\n\n") if is_free_payg_user(db, uid) else tr("💳 هزینه از کیف پول تومانی شما کسر می‌شود.\n\n"))
                    + _tformat("🔗 <a href=\"{url}\">دریافت لینک اشتراک</a>\n\n", url=safe_url)
                    + _tformat("مصرف همه مقصدها با هم جمع و هر {cycle} تسویه می‌شود.", cycle=cycle_text(db)))
                await send_delivery_message(call.message, db, default_text, result["username"], safe_url)
                await show(call.message, uid)
            except Exception:
                logger.exception("PAYG multi-target delivery message failed for user=%s", uid)
                try:
                    await call.message.answer(tr("✅ سرویس Pay As You Go ساخته و فعال شده است. برای مشاهده لینک و وضعیت، دستور /payg را ارسال کنید."))
                except Exception:
                    pass
        finally:
            await asyncio.to_thread(_release_provision_lock, db, uid)

    @router.callback_query(F.data == "payg:provision")
    async def payg_provision_callback(call: CallbackQuery):
        uid = int(call.from_user.id)
        await call.answer(tr("در حال آماده‌سازی سرویس مصرفی..."))
        if db.get_setting("payg_enabled", "1") != "1":
            await call.message.answer(tr("⛔️ فروش Pay As You Go در حال حاضر غیرفعال است."))
            return
        with db._get_conn() as conn:
            existing_account = conn.execute("SELECT status FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
        if existing_account and existing_account["status"] == "suspended_admin":
            await call.message.answer(tr("⛔️ حساب Pay As You Go شما توسط مدیریت تعلیق شده است. برای پیگیری با پشتیبانی تماس بگیرید."))
            return
        balance_now = int(db.get_wallet_credit(uid) or 0)
        if balance_now <= 0 and not is_free_payg_user(db, uid):
            await call.message.answer(tr("برای ساخت سرویس مصرفی، ابتدا کیف پول تومانی خود را شارژ کنید."))
            return
        min_balance = get_min_balance(db)
        if min_balance and balance_now < min_balance and not is_free_payg_user(db, uid):
            await call.message.answer(_tformat("⛔️ برای ساخت سرویس مصرفی، موجودی کیف پول باید حداقل {minimum} تومان باشد.\nموجودی فعلی شما: {current} تومان", minimum=f"{min_balance:,}", current=f"{balance_now:,}"))
            return
        try:
            max_services = max(1, min(100, int(db.get_setting("payg_max_services_per_user", "5") or 5)))
        except (TypeError, ValueError):
            max_services = 5
        with db._get_conn() as conn:
            service_count = conn.execute(
                "SELECT COUNT(*) n FROM payg_provisioned_services p "
                "JOIN custom_configs cc ON p.service_kind='vpn' AND p.service_id=('custom_config:' || cc.id) "
                "WHERE p.user_id=? AND cc.status='active'",
                (uid,),
            ).fetchone()["n"]
        if int(service_count or 0) >= max_services:
            await call.message.answer(_tformat("⛔️ حداکثر {count} سرویس Pay As You Go برای هر کاربر مجاز است.", count=max_services))
            return
        selected_ids = get_payg_panel_ids(db)
        if not selected_ids:
            await call.message.answer(tr("⛔️ هیچ پنل فعالی برای ساخت سرویس Pay As You Go توسط مدیریت انتخاب نشده است."))
            return
        panel_ids = get_usable_payg_panel_ids(db)
        if not panel_ids:
            await call.message.answer(tr("⛔️ ساب اختصاصی همه پنل‌های انتخاب‌شده برای Pay As You Go غیرفعال است؛ مدیریت باید آن را روشن کند."))
            return
        plan = payg_multi_plan(db)
        if plan:
            await _multi_provision_flow(call, uid, plan)
            return
        server = await asyncio.to_thread(_choose_payg_panel, db, panel_ids)
        if not server:
            await call.message.answer(tr("⛔️ هیچ‌یک از پنل‌های انتخاب‌شده فعال یا دارای ظرفیت کافی نیستند."))
            return
        server_id = int(server["id"])
        if not await asyncio.to_thread(_acquire_provision_lock, db, uid):
            await call.message.answer(tr("⏳ درخواست ساخت سرویس شما در حال پردازش است؛ لطفاً چند لحظه صبر کنید."))
            return
        provisioned = None
        enrolled_ok = False
        try:
            from direct_panel_provision import provision_direct
            fake_product = {
                "id": None, "name": get_payg_name(db), "auto_provision_volume_gb": 0,
                "duration_days": 0, "provision_server_id": server_id,
                "provision_ssh_node_id": None, "provision_ssh_protocol": "ssh",
                "provision_target_config": (
                    json.dumps(get_payg_targets(db)[server_id], ensure_ascii=False)
                    if server_id in get_payg_targets(db) else None),
                "is_auto_provision": 1,
                "base_users": 0, "extra_user_price": 0, "max_users": 0,
            }
            results = await provision_direct(db, fake_product, quantity=1, user_id=uid, order_id=None)
            provisioned = (results or [None])[0]
            if not provisioned or not provisioned.get("custom_config_id") or not provisioned.get("subscription_url"):
                raise RuntimeError("ساخت سرویس روی پنل کامل نشد.")
            # Establish an authoritative usage baseline immediately, before the
            # service is handed to the user. Do not sell metered service on a
            # panel whose provider cannot report actual byte counters.
            from panel_providers import get_provider
            provider = get_provider(server)
            usage = await provider.get_user_usage(provisioned["username"])
            if not isinstance(usage, dict) or usage.get("used_bytes") is None or int(usage["used_bytes"]) < 0:
                raise RuntimeError("پنل انتخاب‌شده شمارنده مصرف معتبر ندارد؛ این پنل برای Pay As You Go قابل استفاده نیست.")
            db.record_usage_snapshot(
                "vpn", f"custom_config:{int(provisioned['custom_config_id'])}", int(usage["used_bytes"]),
                uploaded_bytes=usage.get("uploaded_bytes", 0), downloaded_bytes=usage.get("downloaded_bytes", 0),
                source=f"panel:{server['panel_type']}", reported_at=usage.get("reported_at") or _now(),
            )
            sid = f"custom_config:{int(provisioned['custom_config_id'])}"
            with db._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO payg_provisioned_services(service_kind,service_id,user_id,created_at) VALUES('vpn',?,?,?)",
                    (sid, uid, _now()),
                )
            enrolled = await asyncio.to_thread(activate_payg, db, uid)
            sid = f"custom_config:{int(provisioned['custom_config_id'])}"
            with db._get_conn() as conn:
                member = conn.execute("SELECT 1 FROM payg_services WHERE user_id=? AND service_kind='vpn' AND service_id=?",
                                      (uid, sid)).fetchone()
            if not enrolled.get("ok") or not member:
                raise RuntimeError("اتصال سرویس ساخته‌شده به حساب مصرفی ناموفق بود.")
            enrolled_ok = True
            await _report_payg_event(call.bot, db, uid, "سرویس PayG جدید ساخته شد", {
                "نام کاربری": provisioned.get("username"), "پنل": server.get("name"),
                "شناسه سرویس": provisioned.get("custom_config_id"), "نوع سرویس": "پرداخت به‌ازای مصرف", "وضعیت": "فعال",
            })
            central_url = await asyncio.to_thread(_central_link, db, int(provisioned["custom_config_id"]),
                                                  provisioned["subscription_url"])
            safe_url = central_url.replace("&", "&amp;").replace('"', "&quot;")
            default_text = (
                tr("✅ <b>سرویس Pay As You Go ساخته شد.</b>") + "\n\n"
                + _tformat("👤 نام کاربری: <code>{username}</code>\n", username=provisioned["username"])
                + tr("📦 حجم: پرداخت به‌ازای مصرف\n⏳ مدت: بدون انقضای ثابت\n")
                + (tr("🎁 رایگان برای مدیریت؛ هزینه‌ای کسر نمی‌شود.\n\n") if is_free_payg_user(db, uid) else tr("💳 هزینه از کیف پول تومانی شما کسر می‌شود.\n\n"))
                + _tformat("🔗 <a href=\"{url}\">دریافت لینک اشتراک</a>\n\n", url=safe_url)
                + _tformat("مصرف هر {cycle} محاسبه و تسویه می‌شود.", cycle=cycle_text(db)))
            await send_delivery_message(call.message, db, default_text, provisioned["username"], safe_url)
            await show(call.message, uid)
        except Exception as exc:
            logger.exception("PAYG service provisioning/notification failed for user=%s", uid)
            if enrolled_ok:
                # Delivery/UI failure must never revoke a service that has already
                # been provisioned and enrolled successfully.
                try:
                    await call.message.answer(tr("✅ سرویس Pay As You Go ساخته و فعال شده است. برای مشاهده لینک و وضعیت، دستور /payg را ارسال کنید."))
                except Exception:
                    pass
            else:
                if provisioned:
                    try:
                        sid = f"custom_config:{int(provisioned.get('custom_config_id') or 0)}"
                        with db._get_conn() as conn:
                            conn.execute("DELETE FROM payg_provisioned_services WHERE service_kind='vpn' AND service_id=? AND user_id=?",
                                         (sid, uid))
                        await _rollback_payg_vpn(db, server, provisioned)
                    except Exception:
                        logger.exception("PAYG provisioning rollback/marker cleanup failed for user=%s", uid)
                await call.message.answer(_tformat("⛔️ ساخت سرویس Pay As You Go ناموفق بود: {error}\nهیچ هزینه مصرفی برای این سرویس ثبت نشده است.", error=str(exc)[:250]))
        finally:
            await asyncio.to_thread(_release_provision_lock, db, uid)

    @router.callback_query(F.data == "payg:activate")
    async def payg_activate_callback(call: CallbackQuery):
        await call.answer()
        with db._get_conn() as conn:
            acc = conn.execute("SELECT status FROM payg_accounts WHERE user_id=?", (int(call.from_user.id),)).fetchone()
        if acc and acc["status"] == "suspended_admin":
            await call.message.answer(tr("⛔️ حساب Pay As You Go شما توسط مدیریت تعلیق شده است. برای پیگیری با پشتیبانی تماس بگیرید."))
            return
        result = await asyncio.to_thread(activate_payg, db, call.from_user.id)
        if not result['ok']:
            if result['reason'] == 'disabled':
                reason = tr("این قابلیت در حال حاضر غیرفعال است.")
            elif result['reason'] == 'suspended_admin':
                reason = tr("حساب Pay As You Go شما توسط مدیریت تعلیق شده است.")
            elif result['reason'] == 'no_services':
                reason = tr("⛔️ سرویس فعالی با آمار مصرف معتبر برای این حساب پیدا نشد.") + "\n\n" + tr("ابتدا یک سرویس VPN یا SSH قابل‌اندازه‌گیری تهیه کنید. سرویس‌هایی که از قبل به استخر حجم دیگری متصل‌اند، بدون انتقال امن به این حساب اضافه نمی‌شوند.")
            else:
                reason = tr("برای فعال‌سازی ابتدا کیف پول را شارژ کنید.")
            await call.message.answer(reason)
            return
        if not result.get("existing"):
            await _report_payg_event(call.bot, db, call.from_user.id, "حساب PayG فعال شد", {
                "سرویس‌های متصل": result.get("attached", 0), "موجودی کیف پول": f"{int(db.get_wallet_credit(call.from_user.id) or 0):,} تومان",
                "تسویه": cycle_text(db), "وضعیت": "فعال",
            })
        confirmation = tr("✅ Pay As You Go فعال شد. سرویس‌های دارای اندازه‌گیری مصرف معتبر متصل شدند.") + "\n" + _tformat("تسویه مصرف هر {cycle} انجام می‌شود.\n", cycle=cycle_text(db))
        if result.get('conflicts'):
            confirmation += _n(f"\n\n⚠️ تعداد {result['conflicts']} سرویس به دلیل اتصال به استخر سهمیه‌ی دیگری وارد Pay As You Go نشد؛ "
                               "برای جلوگیری از تداخل سهمیه‌ها، انتقال آن‌ها خودکار انجام نشد.")
        await call.message.answer(confirmation)
        await show(call.message, call.from_user.id)

    @router.message(Command("payg_history"))
    async def payg_history(message: Message):
        with db._get_conn() as conn:
            rows = conn.execute("SELECT service_kind,used_bytes,amount,rate_snapshot,created_at FROM payg_transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (message.from_user.id,)).fetchall()
        if not rows:
            await message.answer(tr("هنوز تراکنشی برای Pay As You Go ثبت نشده است."))
            return
        lines = [tr("🧾 <b>آخرین برداشت‌های Pay As You Go</b>")]
        for row in rows:
            try: snap = json.loads(row["rate_snapshot"] or "{}")
            except Exception: snap = {}
            if snap.get("type") == "users": detail = _tformat("ظرفیت {amount} کاربر", amount=int(snap.get('capacity') or 0))
            elif snap.get("type") == "days": detail = _tformat("{amount} روز فعال", amount=int(snap.get('days') or 0))
            else: detail = _tformat("ترافیک {amount} GB", amount=f"{int(row['used_bytes'])/GIB:.3f}")
            lines.append(f"• {row['service_kind'].upper()} | {detail} | {int(row['amount']):,} {tr('تومان')} | {str(row['created_at'])[:16]}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    return router


# ---------------------------------------------------------------------------
# API مستقل از ربات (مینی‌اپ): همان قوانین و همان منطق ساخت سرویس مصرفی
# ---------------------------------------------------------------------------
class PaygProvisionError(Exception):
    """خطایی که متنش مستقیم به کاربر نمایش داده می‌شود."""


_schema_ready_dbs: set = set()


def _ensure_schema_once(db):
    key = id(db)
    if key not in _schema_ready_dbs:
        ensure_schema(db)
        _schema_ready_dbs.add(key)


def _max_services_per_user(db) -> int:
    try:
        return max(1, min(100, int(db.get_setting("payg_max_services_per_user", "5") or 5)))
    except (TypeError, ValueError):
        return 5


def _active_service_count(db, uid: int) -> int:
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) n FROM payg_provisioned_services p "
            "JOIN custom_configs cc ON p.service_kind='vpn' AND p.service_id=('custom_config:' || cc.id) "
            "WHERE p.user_id=? AND cc.status='active'",
            (int(uid),),
        ).fetchone()
    return int(row["n"] or 0)


def provision_blocker(db, uid: int):
    """اگر کاربر الان نمی‌تواند سرویس مصرفی بسازد متن دلیل (فارسی)، وگرنه None.

    دقیقاً همان چک‌های دکمه‌ی «ساخت سرویس مصرفی جدید» در ربات."""
    uid = int(uid)
    if db.get_setting("payg_enabled", "1") != "1":
        return tr("⛔️ فروش Pay As You Go در حال حاضر غیرفعال است.")
    with db._get_conn() as conn:
        acc = conn.execute("SELECT status FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
    if acc and acc["status"] == "suspended_admin":
        return tr("⛔️ حساب Pay As You Go شما توسط مدیریت تعلیق شده است. برای پیگیری با پشتیبانی تماس بگیرید.")
    free = is_free_payg_user(db, uid)
    balance = int(db.get_wallet_credit(uid) or 0)
    if balance <= 0 and not free:
        return tr("برای ساخت سرویس مصرفی، ابتدا کیف پول تومانی خود را شارژ کنید.")
    min_balance = get_min_balance(db)
    if min_balance and balance < min_balance and not free:
        return _tformat(
            "⛔️ برای ساخت سرویس مصرفی، موجودی کیف پول باید حداقل {minimum} تومان باشد.\nموجودی فعلی شما: {current} تومان",
            minimum=f"{min_balance:,}", current=f"{balance:,}",
        )
    max_services = _max_services_per_user(db)
    if _active_service_count(db, uid) >= max_services:
        return _tformat("⛔️ حداکثر {count} سرویس Pay As You Go برای هر کاربر مجاز است.", count=max_services)
    if not get_payg_panel_ids(db):
        return tr("⛔️ هیچ پنل فعالی برای ساخت سرویس Pay As You Go توسط مدیریت انتخاب نشده است.")
    if not get_usable_payg_panel_ids(db):
        return tr("⛔️ ساب اختصاصی همه پنل‌های انتخاب‌شده برای Pay As You Go غیرفعال است؛ مدیریت باید آن را روشن کند.")
    return None


async def provision_service_for_user(db, uid: int) -> dict:
    """ساخت یک سرویس مصرفی برای کاربر (بدون وابستگی به ربات/aiogram).

    خروجی: {username, subscription_url, custom_config_id, multi, panels, nodes}
    در هر شکست: PaygProvisionError با پیام قابل‌نمایش؛ هرچه ساخته شده پاک می‌شود."""
    uid = int(uid)
    await asyncio.to_thread(_ensure_schema_once, db)
    blocker = await asyncio.to_thread(provision_blocker, db, uid)
    if blocker:
        raise PaygProvisionError(blocker)
    plan = payg_multi_plan(db)
    server = None
    if not plan:
        server = await asyncio.to_thread(_choose_payg_panel, db, get_usable_payg_panel_ids(db))
        if not server:
            raise PaygProvisionError(tr("⛔️ هیچ‌یک از پنل‌های انتخاب‌شده فعال یا دارای ظرفیت کافی نیستند."))
    if not await asyncio.to_thread(_acquire_provision_lock, db, uid):
        raise PaygProvisionError(tr("⏳ درخواست ساخت سرویس شما در حال پردازش است؛ لطفاً چند لحظه صبر کنید."))
    try:
        if plan:
            panel_ids, node_ids, protocols = plan
            try:
                result = await _provision_payg_multi(db, uid, panel_ids, node_ids, protocols)
            except Exception as exc:
                logger.exception("PAYG multi-target provisioning (miniapp) failed for user=%s", uid)
                raise PaygProvisionError(_tformat(
                    "⛔️ ساخت سرویس Pay As You Go ناموفق بود: {error}\nهیچ هزینه مصرفی برای این سرویس ثبت نشده است.",
                    error=str(exc)[:250])) from exc
            return {"username": result["username"], "custom_config_id": int(result["custom_config_id"]),
                    "subscription_url": result["subscription_url"], "multi": True,
                    "panels": int(result["panels"]), "nodes": int(result["nodes"])}

        server_id = int(server["id"])
        provisioned = None
        enrolled_ok = False
        try:
            from direct_panel_provision import provision_direct
            from panel_providers import get_provider
            targets = get_payg_targets(db)
            fake_product = {
                "id": None, "name": get_payg_name(db), "auto_provision_volume_gb": 0,
                "duration_days": 0, "provision_server_id": server_id,
                "provision_ssh_node_id": None, "provision_ssh_protocol": "ssh",
                "provision_target_config": (
                    json.dumps(targets[server_id], ensure_ascii=False) if server_id in targets else None),
                "is_auto_provision": 1,
                "base_users": 0, "extra_user_price": 0, "max_users": 0,
            }
            results = await provision_direct(db, fake_product, quantity=1, user_id=uid, order_id=None)
            provisioned = (results or [None])[0]
            if not provisioned or not provisioned.get("custom_config_id") or not provisioned.get("subscription_url"):
                raise RuntimeError("ساخت سرویس روی پنل کامل نشد.")
            usage = await get_provider(server).get_user_usage(provisioned["username"])
            if not isinstance(usage, dict) or usage.get("used_bytes") is None or int(usage["used_bytes"]) < 0:
                raise RuntimeError("پنل انتخاب‌شده شمارنده مصرف معتبر ندارد؛ این پنل برای Pay As You Go قابل استفاده نیست.")
            sid = f"custom_config:{int(provisioned['custom_config_id'])}"
            db.record_usage_snapshot(
                "vpn", sid, int(usage["used_bytes"]),
                uploaded_bytes=usage.get("uploaded_bytes", 0), downloaded_bytes=usage.get("downloaded_bytes", 0),
                source=f"panel:{server['panel_type']}", reported_at=usage.get("reported_at") or _now(),
            )
            with db._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO payg_provisioned_services(service_kind,service_id,user_id,created_at) VALUES('vpn',?,?,?)",
                    (sid, uid, _now()),
                )
            enrolled = await asyncio.to_thread(activate_payg, db, uid)
            with db._get_conn() as conn:
                member = conn.execute(
                    "SELECT 1 FROM payg_services WHERE user_id=? AND service_kind='vpn' AND service_id=?",
                    (uid, sid)).fetchone()
            if not enrolled.get("ok") or not member:
                raise RuntimeError("اتصال سرویس ساخته‌شده به حساب مصرفی ناموفق بود.")
            enrolled_ok = True
        except Exception as exc:
            logger.exception("PAYG service provisioning (miniapp) failed for user=%s", uid)
            if provisioned and not enrolled_ok:
                try:
                    sid = f"custom_config:{int(provisioned.get('custom_config_id') or 0)}"
                    with db._get_conn() as conn:
                        conn.execute("DELETE FROM payg_provisioned_services WHERE service_kind='vpn' AND service_id=? AND user_id=?",
                                     (sid, uid))
                    await _rollback_payg_vpn(db, server, provisioned)
                except Exception:
                    logger.exception("PAYG provisioning rollback/marker cleanup failed for user=%s", uid)
            raise PaygProvisionError(_tformat(
                "⛔️ ساخت سرویس Pay As You Go ناموفق بود: {error}\nهیچ هزینه مصرفی برای این سرویس ثبت نشده است.",
                error=str(exc)[:250])) from exc
        return {"username": provisioned["username"], "custom_config_id": int(provisioned["custom_config_id"]),
                "subscription_url": _central_link(db, int(provisioned["custom_config_id"]), provisioned["subscription_url"]),
                "multi": False, "panels": 1, "nodes": 0}
    finally:
        await asyncio.to_thread(_release_provision_lock, db, uid)


def miniapp_overview(db, uid: int) -> dict:
    """همه‌ی داده‌ی لازم برای صفحه‌ی «پرداخت به‌ازای مصرف» در مینی‌اپ."""
    uid = int(uid)
    _ensure_schema_once(db)
    enabled = db.get_setting("payg_enabled", "1") == "1"
    status = payg_status(db, uid)
    free = is_free_payg_user(db, uid)
    blocker = provision_blocker(db, uid) if enabled else None
    with db._get_conn() as conn:
        service_rows = conn.execute(
            "SELECT cc.id,cc.username,cc.subscription_url,cc.panel_server_id,ps.name AS panel_name "
            "FROM payg_provisioned_services p JOIN custom_configs cc "
            "ON p.service_kind='vpn' AND p.service_id=('custom_config:' || cc.id) "
            "LEFT JOIN panel_servers ps ON ps.id=cc.panel_server_id "
            "WHERE p.user_id=? AND cc.status='active' ORDER BY cc.id DESC",
            (uid,),
        ).fetchall()
        tx_rows = conn.execute(
            "SELECT service_kind,used_bytes,amount,rate_snapshot,created_at FROM payg_transactions "
            "WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
    services = []
    for item in service_rows:
        url = str(item["subscription_url"] or "").strip()
        multi = _is_multi_service(db, int(item["id"]))
        try:
            import dedicated_sub
            url = str(dedicated_sub.display_link(db, int(item["id"]), url) or url).strip()
        except Exception:
            pass
        services.append({
            "id": int(item["id"]), "username": str(item["username"] or ""),
            "panel": tr("چندمقصدی") if multi else str(item["panel_name"] or ""), "link": url,
        })
    history = []
    for row in tx_rows:
        try:
            snap = json.loads(row["rate_snapshot"] or "{}")
        except Exception:
            snap = {}
        if snap.get("type") == "users":
            detail = _tformat("ظرفیت {amount} کاربر", amount=int(snap.get("capacity") or 0))
        elif snap.get("type") == "days":
            detail = _tformat("{amount} روز فعال", amount=int(snap.get("days") or 0))
        else:
            detail = _tformat("ترافیک {amount} GB", amount=f"{int(row['used_bytes'] or 0)/GIB:.3f}")
        history.append({"kind": str(row["service_kind"] or "").upper(), "detail": detail,
                        "amount": int(row["amount"] or 0), "at": str(row["created_at"] or "")[:16]})
    return {
        "enabled": enabled, "active": bool(status["active"]), "free": bool(free),
        "balance": int(status["balance"]), "spent": int(status["spent"]),
        "used_gb": round(int(status.get("month_used_bytes") or 0) / GIB, 3),
        "services_count": int(status["services"]), "max_services": _max_services_per_user(db),
        "min_balance": get_min_balance(db), "cycle": cycle_text(db),
        "can_provision": enabled and not blocker, "blocker": blocker,
        "services": services, "history": history,
        "emoji": get_payg_emoji(db),
    }
