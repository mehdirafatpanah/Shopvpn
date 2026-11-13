# -*- coding: utf-8 -*-
"""Pay As You Go billing for the main Telegram bot.

Only services with authoritative byte counters are billable. In this release
that means custom VPN configs explicitly provisioned by PayG and represented
in usage_snapshots. Existing purchased services are never enrolled implicitly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db.constants import _wallet_tag

logger = logging.getLogger("payg")
GIB = 1024 ** 3
DEFAULT_RATES = [5000, 4500, 4000, 3500]


def _now():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(db):
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
    return list(dict.fromkeys(x for x in ids if x > 0))


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


def payg_multi_plan(db):
    """(panel_ids, node_ids, protocols) اگر ساخت چندمقصدی لازم است؛ وگرنه None."""
    if get_payg_mode(db) != "all":
        return None
    panels = get_payg_panel_ids(db)
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
    balance = int(db.get_wallet_credit(user_id) or 0)
    if balance <= 0:
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
        limit_bytes = _affordable_payg_limit(db, user_id, balance, _billing_base_bytes(db, user_id), active_month_used, active_rates)
        db.set_quota_pool_limit(int(existing['quota_pool_id']), limit_bytes / GIB)
        return {"ok": True, "existing": True, **sync}
    rates = get_rates(db)
    # Temporarily create a generous pool ceiling; after attaching services,
    # rebase it on settled usage and the wallet's exact tiered purchasing power.
    pool_id = (int(existing_pool_id) if existing_pool_id else
               db.create_quota_pool(user_id, 1_000_000_000,
                                    label="Pay As You Go", metadata={"payg": True}))
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
    initial_limit = _affordable_payg_limit(db, user_id, balance, billed_base, 0, rates)
    db.set_quota_pool_limit(pool_id, initial_limit / GIB)
    return {"ok": True, "existing": False, "pool_id": pool_id, **sync}


def payg_status(db, user_id: int):
    with db._get_conn() as conn:
        row = conn.execute("SELECT * FROM payg_accounts WHERE user_id=?", (int(user_id),)).fetchone()
        services = conn.execute("SELECT COUNT(*) n FROM payg_services WHERE user_id=?", (int(user_id),)).fetchone()['n']
        tx = conn.execute("SELECT COALESCE(SUM(amount),0) total FROM payg_transactions WHERE user_id=? AND strftime('%Y-%m',created_at,'+3 hours','+30 minutes')=?",
                          (int(user_id), _month_key())).fetchone()
    if not row:
        return {"active": False, "services": 0, "spent": 0}
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


def _affordable_payg_limit(db, user_id: int, balance: int, base_bytes: int, month_used_bytes: int, legacy_rates: list[int]):
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
    limit = _affordable_payg_limit(db, user_id, balance, _billing_base_bytes(db, user_id), month_used, [int(x) for x in rates])
    db.set_quota_pool_limit(int(account["quota_pool_id"]), limit / GIB)
    with db._get_conn() as conn:
        if balance > int(account.get("last_balance") or 0):
            conn.execute("UPDATE payg_accounts SET last_balance=?,initial_balance=?,last_alert_level=0,updated_at=? WHERE user_id=?",
                         (balance, balance, _now(), int(user_id)))
    return True



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
                if billing_insufficient:
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
        level = 3 if balance <= 0 else 2 if balance <= initial * 0.10 else 1 if balance <= initial * 0.20 else 0
        previous = int(account.get('last_alert_level') or 0)
        if level <= previous:
            return None
        messages = {
            1: "⚠️ موجودی کیف پول شما به کمتر از ۲۰٪ موجودی شروع Pay As You Go رسیده است. برای جلوگیری از توقف سرویس، کیف پول را شارژ کنید.",
            2: "🚨 موجودی کیف پول شما به کمتر از ۱۰٪ موجودی شروع رسیده است. لطفاً هرچه زودتر کیف پول را شارژ کنید.",
            3: "⛔ موجودی کیف پول تمام شده و سرویس‌های Pay As You Go در حال تعلیق هستند. پس از شارژ کیف پول، سرویس به‌صورت خودکار دوباره فعال می‌شود.",
        }
        return {"user_id": uid, "level": level, "text": messages[level]}

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
    if account and account["status"] == "active" and account["quota_pool_id"]:
        pool_id = int(account["quota_pool_id"])
    else:
        pool_id = int(db.create_quota_pool(int(uid), 1_000_000_000, label="Pay As You Go", metadata={"payg": True}))
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
        if created_pool:
            db.delete_quota_pool(pool_id)

    try:
        ssh_product_base = {"name": "Pay As You Go", "auto_provision_volume_gb": 0, "duration_days": 0}
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
                "id": None, "name": "Pay As You Go", "auto_provision_volume_gb": 0, "duration_days": 0,
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


def _is_multi_service(db, custom_config_id: int) -> bool:
    with db._get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) n FROM config_panel_links WHERE custom_config_id=? AND status='active'",
                         (int(custom_config_id),)).fetchone()["n"]
        m = conn.execute("SELECT COUNT(*) n FROM ssh_accounts WHERE custom_config_id=? AND status='active'",
                         (int(custom_config_id),)).fetchone()["n"]
    return bool(n or m)


def create_payg_router(db, is_main_bot=True):
    router = Router(name="payg_router")
    if not is_main_bot:
        return router
    ensure_schema(db)

    def menu(active=False, configured=False):
        rows = [[InlineKeyboardButton(text="🚀 ساخت سرویس مصرفی جدید", callback_data="payg:provision")]]
        rows.extend([
            [InlineKeyboardButton(text="💰 شارژ کیف پول", callback_data="acct:wallet")],
            [InlineKeyboardButton(text="🧾 تاریخچه برداشت‌ها", callback_data="payg:history")],
            [InlineKeyboardButton(text="📊 وضعیت و جزئیات مصرف", callback_data="payg:status")],
            [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="back_categories")],
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show(message, user_id):
        status = payg_status(db, user_id)
        balance = int(db.get_wallet_credit(user_id) or 0)
        rates = status.get('rates') or get_rates(db)
        rate_text = ("تعرفه هر سرویس بر اساس پنل و گروه/اینباند محل ساخت محاسبه می‌شود؛ "
                     "هزینه ترافیک مصرفی، روزهای فعال و ظرفیت کاربران از کیف پول مشترک کسر خواهد شد.\n")
        supported_text = "سرویس‌های قابل صورتحساب فعلی: VPN و SSH با شمارنده مصرف معتبر.\n"
        panel_ids = get_payg_panel_ids(db)
        panel_names = []
        for pid in panel_ids:
            panel = await asyncio.to_thread(db.get_panel_server, int(pid))
            if panel and panel["is_active"]:
                panel_names.append(str(panel["name"] or f"پنل {pid}"))
        with db._get_conn() as conn:
            service_rows = conn.execute(
                "SELECT cc.id,cc.username,cc.subscription_url,cc.panel_server_id,ps.name AS panel_name "
                "FROM payg_provisioned_services p JOIN custom_configs cc "
                "ON p.service_kind='vpn' AND p.service_id=('custom_config:' || cc.id) "
                "LEFT JOIN panel_servers ps ON ps.id=cc.panel_server_id "
                "WHERE p.user_id=? AND cc.status='active' ORDER BY cc.id DESC",
                (int(user_id),),
            ).fetchall()
        if status['active']:
            text = ("💳 <b>Pay As You Go</b>\n\n"
                    f"وضعیت: فعال\nموجودی کیف پول: {balance:,} تومان\n"
                    f"هزینه این ماه: {status['spent']:,} تومان\n"
                    f"مصرف ثبت‌شده: {status['month_used_bytes']/GIB:.3f} GB\n"
                    f"سرویس‌های متصل: {status['services']}\n"
                    + rate_text + supported_text + "تسویه مصرف هر ۱۰ دقیقه انجام می‌شود.\n"
                    + (f"پنل‌های فعال ساخت سرویس: {', '.join(panel_names)}\n" if panel_names else "⚠️ پنل فعالی برای ساخت سرویس انتخاب نشده است.\n")
                    + "برای ساخت سرویس مصرفی جدید از دکمه زیر استفاده کنید.")
        else:
            text = ("💳 <b>Pay As You Go</b>\n\n"
                    f"موجودی کیف پول: {balance:,} تومان\n"
                    + rate_text + supported_text
                    + "با ساخت سرویس مصرفی، حجم و زمان ثابت نخواهید داشت و هزینه از کیف پول کسر می‌شود.\n"
                    "برای شروع، کیف پول باید موجودی مثبت داشته باشد.")
        if not panel_names:
            text += "\n\n⚠️ هنوز پنل فعال ساخت سرویس توسط مدیریت انتخاب نشده است."
        if service_rows:
            text += "\n\n🔗 <b>لینک‌های اشتراک اختصاصی فعال:</b>"
            for item in service_rows:
                url = str(item["subscription_url"] or "").strip()
                multi = await asyncio.to_thread(_is_multi_service, db, int(item["id"]))
                if multi:
                    import dedicated_sub
                    url = str(dedicated_sub.display_link(db, int(item["id"]), url) or url).strip()
                if not url:
                    continue
                safe_url = url.replace("&", "&amp;").replace('"', "&quot;")
                label = str(item["username"] or f"سرویس {item['id']}")
                panel_label = ("چندمقصدی" if multi else str(item["panel_name"] or f"پنل {item['panel_server_id']}"))
                text += f"\n• {label} · {panel_label}: <a href=\"{safe_url}\">باز کردن لینک</a>"
        with db._get_conn() as conn:
            configured = conn.execute("SELECT 1 FROM payg_accounts WHERE user_id=?", (int(user_id),)).fetchone() is not None
        await message.answer(text, reply_markup=menu(status['active'], configured), parse_mode="HTML")

    @router.message(Command("payg"))
    async def payg_command(message: Message):
        await show(message, message.from_user.id)

    @router.message(F.text.func(lambda t: t in (db.get_setting("btn_payg", "💳 پرداخت به‌ازای مصرف"), "💳 پرداخت به‌ازای مصرف")))
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
            await call.message.answer("هنوز تراکنشی برای Pay As You Go ثبت نشده است.")
            return
        lines = ["🧾 <b>آخرین برداشت‌های Pay As You Go</b>"]
        for row in rows:
            try: snap = json.loads(row["rate_snapshot"] or "{}")
            except Exception: snap = {}
            if snap.get("type") == "users": detail = f"ظرفیت {int(snap.get('capacity') or 0)} کاربر"
            elif snap.get("type") == "days": detail = f"{int(snap.get('days') or 0)} روز فعال"
            elif snap.get("type") == "traffic": detail = f"ترافیک {int(row['used_bytes'])/GIB:.3f} GB"
            else: detail = f"ترافیک {int(row['used_bytes'])/GIB:.3f} GB"
            lines.append(f"• {row['service_kind'].upper()} | {detail} | {int(row['amount']):,} تومان | {str(row['created_at'])[:16]}")
        await call.message.answer("\n".join(lines), parse_mode="HTML")

    async def _multi_provision_flow(call: CallbackQuery, uid: int, plan):
        panel_ids, node_ids, protocols = plan
        if not await asyncio.to_thread(_acquire_provision_lock, db, uid):
            await call.message.answer("⏳ درخواست ساخت سرویس شما در حال پردازش است؛ لطفاً چند لحظه صبر کنید.")
            return
        try:
            try:
                result = await _provision_payg_multi(db, uid, panel_ids, node_ids, protocols)
            except Exception as exc:
                logger.exception("PAYG multi-target provisioning failed for user=%s", uid)
                await call.message.answer(f"⛔️ ساخت سرویس Pay As You Go ناموفق بود: {str(exc)[:250]}\n"
                                          "هیچ هزینه مصرفی برای این سرویس ثبت نشده است.")
                return
            try:
                safe_url = str(result["subscription_url"]).replace("&", "&amp;").replace('"', "&quot;")
                await call.message.answer(
                    "✅ <b>سرویس Pay As You Go ساخته شد.</b>\n\n"
                    f"👤 نام کاربری: <code>{result['username']}</code>\n"
                    f"🧩 مقصدها: {result['panels']} پنل + {result['nodes']} نود\n"
                    "📦 حجم: پرداخت به‌ازای مصرف\n⏳ مدت: بدون انقضای ثابت\n"
                    "💳 هزینه از کیف پول تومانی شما کسر می‌شود.\n\n"
                    f"🔗 <a href=\"{safe_url}\">دریافت لینک اشتراک</a>\n\n"
                    "مصرف همه مقصدها با هم جمع و هر ۱۰ دقیقه تسویه می‌شود.",
                    parse_mode="HTML", disable_web_page_preview=True)
                await show(call.message, uid)
            except Exception:
                logger.exception("PAYG multi-target delivery message failed for user=%s", uid)
                try:
                    await call.message.answer("✅ سرویس Pay As You Go ساخته و فعال شده است. برای مشاهده لینک و وضعیت، دستور /payg را ارسال کنید.")
                except Exception:
                    pass
        finally:
            await asyncio.to_thread(_release_provision_lock, db, uid)

    @router.callback_query(F.data == "payg:provision")
    async def payg_provision_callback(call: CallbackQuery):
        uid = int(call.from_user.id)
        await call.answer("در حال آماده‌سازی سرویس مصرفی...")
        if db.get_setting("payg_enabled", "1") != "1":
            await call.message.answer("⛔️ فروش Pay As You Go در حال حاضر غیرفعال است.")
            return
        with db._get_conn() as conn:
            existing_account = conn.execute("SELECT status FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
        if existing_account and existing_account["status"] == "suspended_admin":
            await call.message.answer("⛔️ حساب Pay As You Go شما توسط مدیریت تعلیق شده است. برای پیگیری با پشتیبانی تماس بگیرید.")
            return
        if int(db.get_wallet_credit(uid) or 0) <= 0:
            await call.message.answer("برای ساخت سرویس مصرفی، ابتدا کیف پول تومانی خود را شارژ کنید.")
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
            await call.message.answer(f"⛔️ حداکثر {max_services} سرویس Pay As You Go برای هر کاربر مجاز است.")
            return
        panel_ids = get_payg_panel_ids(db)
        if not panel_ids:
            await call.message.answer("⛔️ هیچ پنل فعالی برای ساخت سرویس Pay As You Go توسط مدیریت انتخاب نشده است.")
            return
        plan = payg_multi_plan(db)
        if plan:
            await _multi_provision_flow(call, uid, plan)
            return
        server = await asyncio.to_thread(_choose_payg_panel, db, panel_ids)
        if not server:
            await call.message.answer("⛔️ هیچ‌یک از پنل‌های انتخاب‌شده فعال یا دارای ظرفیت کافی نیستند.")
            return
        server_id = int(server["id"])
        if not await asyncio.to_thread(_acquire_provision_lock, db, uid):
            await call.message.answer("⏳ درخواست ساخت سرویس شما در حال پردازش است؛ لطفاً چند لحظه صبر کنید.")
            return
        provisioned = None
        enrolled_ok = False
        try:
            from direct_panel_provision import provision_direct
            fake_product = {
                "id": None, "name": "Pay As You Go", "auto_provision_volume_gb": 0,
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
            safe_url = str(provisioned["subscription_url"]).replace("&", "&amp;").replace('"', "&quot;")
            await call.message.answer(
                "✅ <b>سرویس Pay As You Go ساخته شد.</b>\n\n"
                f"👤 نام کاربری: <code>{provisioned['username']}</code>\n"
                "📦 حجم: پرداخت به‌ازای مصرف\n⏳ مدت: بدون انقضای ثابت\n"
                "💳 هزینه از کیف پول تومانی شما کسر می‌شود.\n\n"
                f"🔗 <a href=\"{safe_url}\">دریافت لینک اشتراک</a>\n\n"
                "مصرف هر ۱۰ دقیقه محاسبه و تسویه می‌شود.", parse_mode="HTML", disable_web_page_preview=True)
            await show(call.message, uid)
        except Exception as exc:
            logger.exception("PAYG service provisioning/notification failed for user=%s", uid)
            if enrolled_ok:
                # Delivery/UI failure must never revoke a service that has already
                # been provisioned and enrolled successfully.
                try:
                    await call.message.answer("✅ سرویس Pay As You Go ساخته و فعال شده است. برای مشاهده لینک و وضعیت، دستور /payg را ارسال کنید.")
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
                await call.message.answer(f"⛔️ ساخت سرویس Pay As You Go ناموفق بود: {str(exc)[:250]}\nهیچ هزینه مصرفی برای این سرویس ثبت نشده است.")
        finally:
            await asyncio.to_thread(_release_provision_lock, db, uid)

    @router.callback_query(F.data == "payg:activate")
    async def payg_activate_callback(call: CallbackQuery):
        await call.answer()
        with db._get_conn() as conn:
            acc = conn.execute("SELECT status FROM payg_accounts WHERE user_id=?", (int(call.from_user.id),)).fetchone()
        if acc and acc["status"] == "suspended_admin":
            await call.message.answer("⛔️ حساب Pay As You Go شما توسط مدیریت تعلیق شده است. برای پیگیری با پشتیبانی تماس بگیرید.")
            return
        result = await asyncio.to_thread(activate_payg, db, call.from_user.id)
        if not result['ok']:
            if result['reason'] == 'disabled':
                reason = "این قابلیت در حال حاضر غیرفعال است."
            elif result['reason'] == 'suspended_admin':
                reason = "حساب Pay As You Go شما توسط مدیریت تعلیق شده است."
            elif result['reason'] == 'no_services':
                reason = ("⛔️ سرویس فعالی با آمار مصرف معتبر برای این حساب پیدا نشد.\n\n"
                          "ابتدا یک سرویس VPN یا SSH قابل‌اندازه‌گیری تهیه کنید. سرویس‌هایی که از قبل به استخر حجم دیگری متصل‌اند، بدون انتقال امن به این حساب اضافه نمی‌شوند.")
            else:
                reason = "برای فعال‌سازی ابتدا کیف پول را شارژ کنید."
            await call.message.answer(reason)
            return
        confirmation = "✅ Pay As You Go فعال شد. سرویس‌های دارای اندازه‌گیری مصرف معتبر متصل شدند.\nتسویه هر ۱۰ دقیقه انجام می‌شود."
        if result.get('conflicts'):
            confirmation += (f"\n\n⚠️ تعداد {result['conflicts']} سرویس به دلیل اتصال به استخر سهمیه‌ی دیگری وارد Pay As You Go نشد؛ "
                             "برای جلوگیری از تداخل سهمیه‌ها، انتقال آن‌ها خودکار انجام نشد.")
        await call.message.answer(confirmation)
        await show(call.message, call.from_user.id)

    @router.message(Command("payg_history"))
    async def payg_history(message: Message):
        with db._get_conn() as conn:
            rows = conn.execute("SELECT service_kind,used_bytes,amount,rate_snapshot,created_at FROM payg_transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (message.from_user.id,)).fetchall()
        if not rows:
            await message.answer("هنوز تراکنشی برای Pay As You Go ثبت نشده است.")
            return
        lines = ["🧾 <b>آخرین برداشت‌های Pay As You Go</b>"]
        for row in rows:
            try: snap = json.loads(row["rate_snapshot"] or "{}")
            except Exception: snap = {}
            if snap.get("type") == "users": detail = f"ظرفیت {int(snap.get('capacity') or 0)} کاربر"
            elif snap.get("type") == "days": detail = f"{int(snap.get('days') or 0)} روز فعال"
            elif snap.get("type") == "traffic": detail = f"ترافیک {int(row['used_bytes'])/GIB:.3f} GB"
            else: detail = f"ترافیک {int(row['used_bytes'])/GIB:.3f} GB"
            lines.append(f"• {row['service_kind'].upper()} | {detail} | {int(row['amount']):,} تومان | {str(row['created_at'])[:16]}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    return router
