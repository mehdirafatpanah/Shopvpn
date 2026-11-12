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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db.constants import _wallet_tag

logger = logging.getLogger("payg")
GIB = 1024 ** 3
DEFAULT_RATES = [5000, 4500, 4000, 3500]


class PaygAdminStates(StatesGroup):
    waiting_rate = State()
    waiting_user_id = State()


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
    """Attach only services explicitly provisioned as PayG services."""
    attachments = []
    with db._get_conn() as conn:
        configs = conn.execute(
            "SELECT cc.id,cc.panel_server_id FROM custom_configs cc "
            "JOIN payg_provisioned_services p ON p.service_kind='vpn' "
            "AND p.service_id=('custom_config:' || cc.id) AND p.user_id=cc.user_id "
            "WHERE cc.user_id=? AND cc.status='active'",
            (int(user_id),),
        ).fetchall()
        for row in configs:
            sid = f"custom_config:{int(row['id'])}"
            snap = conn.execute(
                "SELECT used_bytes FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?",
                (sid,),
            ).fetchone()
            baseline = int(snap['used_bytes'] or 0) if snap else -1
            conn.execute(
                "INSERT OR IGNORE INTO payg_services(user_id,service_kind,service_id,last_billed_bytes,created_at) VALUES(?,?,?,?,?)",
                (int(user_id), "vpn", sid, baseline, _now()),
            )
            attachments.append(("vpn", sid, int(row["panel_server_id"]) if row["panel_server_id"] else None))
    attached = conflicts = 0
    for kind, sid, node_id in attachments:
        try:
            db.attach_quota_service(pool_id, kind, sid, node_id=node_id)
            attached += 1
        except ValueError as exc:
            conflicts += 1
            logger.warning("PAYG service could not be attached: %s/%s (%s)", kind, sid, exc)
            with db._get_conn() as conn:
                conn.execute(
                    "DELETE FROM payg_services WHERE user_id=? AND service_kind=? AND service_id=?",
                    (int(user_id), kind, sid),
                )
    return {"attached": attached, "conflicts": conflicts, "discovered": len(attachments)}


def activate_payg(db, user_id: int):
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
        limit_bytes = _affordable_limit_bytes(balance, active_rates, _billing_base_bytes(db, user_id), active_month_used)
        db.set_quota_pool_limit(int(existing['quota_pool_id']), limit_bytes / GIB)
        return {"ok": True, "existing": True, **sync}
    rates = get_rates(db)
    # Temporarily create a generous pool ceiling; after attaching services,
    # rebase it on settled usage and the wallet's exact tiered purchasing power.
    pool_id = db.create_quota_pool(user_id, 1_000_000_000,
                                   label="Pay As You Go", metadata={"payg": True})
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
    initial_limit = _affordable_limit_bytes(balance, rates, billed_base, 0)
    db.set_quota_pool_limit(pool_id, max(1, initial_limit) / GIB)
    return {"ok": True, "existing": False, "pool_id": pool_id, **sync}


def payg_status(db, user_id: int):
    with db._get_conn() as conn:
        row = conn.execute("SELECT * FROM payg_accounts WHERE user_id=?", (int(user_id),)).fetchone()
        services = conn.execute("SELECT COUNT(*) n FROM payg_services WHERE user_id=?", (int(user_id),)).fetchone()['n']
        tx = conn.execute("SELECT COALESCE(SUM(amount),0) total FROM payg_transactions WHERE user_id=? AND substr(cycle_key,1,7)=?",
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
    limit = _affordable_limit_bytes(balance, [int(x) for x in rates],
                                    _billing_base_bytes(db, user_id), month_used)
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
                pre_limit = _affordable_limit_bytes(current_balance, effective_rates,
                                                    _billing_base_bytes(self.db, uid), account_month_used)
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

                for service in services:
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
                        amount = max(0, _progressive_cost(before_bytes + delta, month_rates) - _progressive_cost(before_bytes, month_rates))
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
                                     json.dumps(month_rates), _now()))
                                conn.execute("UPDATE payg_services SET last_billed_bytes=? WHERE id=?",
                                             (current_bytes, service['id']))
                                conn.execute("UPDATE payg_accounts SET month_used_bytes=month_used_bytes+?,month_cost=month_cost+?,updated_at=? WHERE user_id=?",
                                             (delta, amount, _now(), uid))
                    if insufficient:
                        logger.warning("PAYG wallet insufficient; preserving unbilled usage for user=%s service=%s/%s",
                                       uid, service['service_kind'], service['service_id'])
                        break

                balance = int(self.db.get_wallet_credit(uid) or 0)
                with self.db._get_conn() as conn:
                    latest = conn.execute("SELECT month_used_bytes FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
                    latest_month_used = int(latest['month_used_bytes'] or 0) if latest else 0
                    conn.execute("UPDATE payg_accounts SET last_balance=?,updated_at=? WHERE user_id=?",
                                 (balance, _now(), uid))
                limit_bytes = _affordable_limit_bytes(balance, month_rates, _billing_base_bytes(self.db, uid), latest_month_used)
                self.db.set_quota_pool_limit(pool_id, limit_bytes / GIB)
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
        rate_text = ("تعرفه پلکانی هر گیگابایت:\n"
                     f"تا ۵۰ GB: {rates[0]:,} تومان | ۵۰ تا ۲۰۰ GB: {rates[1]:,} تومان\n"
                     f"۲۰۰ تا ۵۰۰ GB: {rates[2]:,} تومان | بیشتر از ۵۰۰ GB: {rates[3]:,} تومان\n")
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
                if not url:
                    continue
                safe_url = url.replace("&", "&amp;").replace('"', "&quot;")
                label = str(item["username"] or f"سرویس {item['id']}")
                panel_label = str(item["panel_name"] or f"پنل {item['panel_server_id']}")
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
            rows = conn.execute("SELECT service_kind,used_bytes,amount,created_at FROM payg_transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (call.from_user.id,)).fetchall()
        if not rows:
            await call.message.answer("هنوز تراکنشی برای Pay As You Go ثبت نشده است.")
            return
        lines = ["🧾 <b>آخرین برداشت‌های Pay As You Go</b>"]
        for row in rows:
            lines.append(f"• {row['service_kind'].upper()} | {int(row['used_bytes'])/GIB:.3f} GB | {int(row['amount']):,} تومان | {str(row['created_at'])[:16]}")
        await call.message.answer("\n".join(lines), parse_mode="HTML")

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
                "provision_target_config": None, "is_auto_provision": 1,
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

    def _admin_home_kb(enabled: bool):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=("🔴 توقف فروش جدید" if enabled else "🟢 فعال‌سازی فروش جدید"), callback_data="payg:admin_toggle")],
            [InlineKeyboardButton(text="💵 تنظیم تعرفه‌ها", callback_data="payg:admin_rates")],
            [InlineKeyboardButton(text="🖥 مدیریت چندپنل و توزیع سرویس", callback_data="payg:admin_servers")],
            [InlineKeyboardButton(text="👥 جستجوی کاربر PayG", callback_data="payg:admin_user_search")],
            [InlineKeyboardButton(text="📋 فهرست حساب‌های PayG", callback_data="payg:admin_users:0")],
            [InlineKeyboardButton(text="📈 گزارش مصرف و درآمد", callback_data="payg:admin_report")],
            [InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data="adm_payg")],
        ])

    async def _show_admin_home(target):
        rates = get_rates(db)
        enabled = db.get_setting("payg_enabled", "1") == "1"
        with db._get_conn() as conn:
            stats = conn.execute("SELECT COUNT(*) total, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) active, SUM(CASE WHEN status='suspended_admin' THEN 1 ELSE 0 END) suspended FROM payg_accounts").fetchone()
            revenue = conn.execute("SELECT COALESCE(SUM(amount),0) amount FROM payg_transactions WHERE substr(cycle_key,1,7)=?", (_month_key(),)).fetchone()["amount"]
            used = conn.execute("SELECT COALESCE(SUM(month_used_bytes),0) n FROM payg_accounts WHERE month_key=?", (_month_key(),)).fetchone()["n"]
        selected_ids = get_payg_panel_ids(db)
        selected_names = []
        for pid in selected_ids:
            panel = await asyncio.to_thread(db.get_panel_server, int(pid))
            if panel:
                selected_names.append(f"{panel['name']} (#{pid})")
        server_label = "، ".join(selected_names) if selected_names else "تنظیم نشده"
        text = ("⚙️ <b>مدیریت Pay As You Go</b>\n\n"
                f"فروش جدید: {'فعال' if enabled else 'غیرفعال'}\n"
                f"حساب‌ها: {int(stats['active'] or 0)} فعال | {int(stats['suspended'] or 0)} تعلیق مدیریتی | {int(stats['total'] or 0)} کل\n"
                f"مصرف این ماه: {int(used or 0)/GIB:.3f} GB\n"
                f"درآمد این ماه: {int(revenue or 0):,} تومان\n"
                f"پنل‌های ساخت سرویس: {server_label}\n"
                f"تعرفه‌ها (تومان/GB): {rates[0]:,} / {rates[1]:,} / {rates[2]:,} / {rates[3]:,}\n"
                f"چرخه تسویه: هر {max(60, int(db.get_setting('payg_cycle_seconds', '600') or 600))} ثانیه")
        await target.answer(text, reply_markup=_admin_home_kb(enabled), parse_mode="HTML")

    @router.callback_query(F.data == "adm_payg")
    async def payg_admin_panel(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id):
            return
        await _show_admin_home(call.message)

    @router.callback_query(F.data == "payg:admin_rates")
    async def payg_admin_rates(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id):
            return
        rates = get_rates(db)
        rows = []
        labels = ["تا ۵۰ گیگابایت", "۵۰ تا ۲۰۰ گیگابایت", "۲۰۰ تا ۵۰۰ گیگابایت", "بیشتر از ۵۰۰ گیگابایت"]
        for i, label in enumerate(labels):
            rows.append([InlineKeyboardButton(text=f"✏️ {label}: {rates[i]:,} تومان/GB", callback_data=f"payg:admin_rate:{i}")])
        rows.append([InlineKeyboardButton(text="↩️ بازگشت", callback_data="adm_payg")])
        await call.message.answer("💵 <b>تنظیم تعرفه‌های پلکانی</b>\nبرای تغییر هر بازه روی دکمه آن بزنید. نرخ جدید برای حساب‌های فعال از ابتدای ماه بعد اعمال می‌شود.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

    @router.callback_query(F.data.startswith("payg:admin_rate:"))
    async def payg_admin_rate_edit(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if not db.is_full_admin(call.from_user.id):
            return
        try:
            tier = int(call.data.rsplit(":", 1)[1])
            if tier not in range(4):
                raise ValueError
        except ValueError:
            await call.message.answer("بازه تعرفه نامعتبر است.")
            return
        await state.update_data(payg_rate_tier=tier)
        await state.set_state(PaygAdminStates.waiting_rate)
        await call.message.answer(f"قیمت جدید به تومان برای بازه {tier + 1} را به‌صورت عددی ارسال کنید.\nبرای لغو /cancel")

    @router.message(PaygAdminStates.waiting_rate)
    async def payg_admin_rate_save(message: Message, state: FSMContext):
        if not db.is_full_admin(message.from_user.id):
            await state.clear(); return
        if (message.text or "").strip() == "/cancel":
            await state.clear(); await message.answer("ویرایش تعرفه لغو شد."); return
        try:
            value = int((message.text or "").replace(",", "").strip())
            data = await state.get_data(); tier = int(data["payg_rate_tier"])
            rates = get_rates(db); rates[tier] = value
            if value <= 0 or rates != sorted(rates, reverse=True):
                raise ValueError
        except Exception:
            await message.answer("عدد نامعتبر است. همه تعرفه‌ها باید مثبت و به‌ترتیب نزولی باشند. دوباره ارسال کنید یا /cancel بزنید.")
            return
        db.set_setting("payg_rates", json.dumps(rates))
        await state.clear()
        await message.answer("✅ تعرفه ذخیره شد. نرخ جدید برای حساب‌های فعال از ابتدای ماه بعد اعمال می‌شود.")
        await _show_admin_home(message)

    @router.callback_query(F.data == "payg:admin_user_search")
    async def payg_admin_user_search(call: CallbackQuery, state: FSMContext):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        await state.set_state(PaygAdminStates.waiting_user_id)
        await call.message.answer("آیدی عددی تلگرام کاربر را ارسال کنید. برای لغو /cancel")

    @router.message(PaygAdminStates.waiting_user_id)
    async def payg_admin_user_search_receive(message: Message, state: FSMContext):
        if not db.is_full_admin(message.from_user.id): await state.clear(); return
        raw = (message.text or "").strip()
        if raw == "/cancel": await state.clear(); await message.answer("جستجو لغو شد."); return
        if not raw.isdigit(): await message.answer("آیدی باید عددی باشد."); return
        await state.clear()
        await _show_admin_user(message, int(raw))

    async def _show_admin_user(target, uid: int):
        with db._get_conn() as conn:
            row = conn.execute("SELECT * FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
            services = conn.execute("SELECT id,service_kind,service_id,last_billed_bytes FROM payg_services WHERE user_id=?", (uid,)).fetchall()
            tx = conn.execute("SELECT COUNT(*) n,COALESCE(SUM(amount),0) spent FROM payg_transactions WHERE user_id=?", (uid,)).fetchone()
        if not row:
            await target.answer("برای این کاربر حساب PayG ثبت نشده است."); return
        balance = int(db.get_wallet_credit(uid) or 0)
        pool = db.get_quota_usage(int(row['quota_pool_id'])) if row['quota_pool_id'] else None
        status_label = {"active":"فعال", "suspended_admin":"تعلیق‌شده توسط مدیریت", "inactive":"غیرفعال"}.get(row['status'], row['status'])
        lines = [f"👤 <b>حساب PayG کاربر {uid}</b>", f"وضعیت: {status_label}", f"کیف پول: {balance:,} تومان", f"مصرف ماه: {int(row['month_used_bytes'] or 0)/GIB:.3f} GB", f"هزینه ماه: {int(row['month_cost'] or 0):,} تومان", f"کل برداشت‌ها: {int(tx['spent'] or 0):,} تومان ({int(tx['n'] or 0)} تراکنش)", f"سرویس‌های متصل: {len(services)}"]
        if pool:
            lines.append(f"سقف استخر: {int(pool['limit_bytes'])/GIB:.3f} GB | مصرف ثبت‌شده استخر: {int(pool['used_bytes'])/GIB:.3f} GB")
        for item in services[:8]: lines.append(f"• {item['service_kind'].upper()} · {item['service_id']}")
        buttons = [[InlineKeyboardButton(text=f"🔍 جزئیات {item['service_kind'].upper()} · {item['service_id'][:18]}", callback_data=f"payg:admin_service:{uid}:{int(item['id'])}")] for item in services[:8]]
        if row['status'] == 'active': buttons.append([InlineKeyboardButton(text="⛔ تعلیق دستی حساب", callback_data=f"payg:admin_suspend:{uid}")])
        else: buttons.append([InlineKeyboardButton(text="🟢 فعال‌سازی مجدد حساب", callback_data=f"payg:admin_resume:{uid}")])
        buttons.extend([[InlineKeyboardButton(text="🧾 تراکنش‌های اخیر", callback_data=f"payg:admin_user_tx:{uid}")], [InlineKeyboardButton(text="↩️ بازگشت به فهرست", callback_data="payg:admin_users:0")]])
        await target.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

    @router.callback_query(F.data.startswith("payg:admin_suspend:"))
    async def payg_admin_suspend(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        uid = int(call.data.rsplit(":", 1)[1])
        with db._get_conn() as conn:
            row = conn.execute("SELECT quota_pool_id FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
            if row:
                conn.execute("UPDATE payg_accounts SET status='suspended_admin',updated_at=? WHERE user_id=?", (_now(), uid))
        if row and row['quota_pool_id']:
            usage = db.get_quota_usage(int(row['quota_pool_id']))
            used = int((usage or {}).get('used_bytes') or 0)
            db.set_quota_pool_limit(int(row['quota_pool_id']), max(1, used) / GIB)
        await call.message.answer("⛔ حساب PayG کاربر تعلیق شد.")
        await _show_admin_user(call.message, uid)

    @router.callback_query(F.data.startswith("payg:admin_resume:"))
    async def payg_admin_resume(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        uid = int(call.data.rsplit(":", 1)[1])
        with db._get_conn() as conn:
            row = conn.execute("SELECT * FROM payg_accounts WHERE user_id=?", (uid,)).fetchone()
        if not row:
            await call.message.answer("حساب پیدا نشد."); return
        balance = int(db.get_wallet_credit(uid) or 0)
        if balance <= 0:
            await call.message.answer("برای فعال‌سازی مجدد ابتدا کاربر باید کیف پولش را شارژ کند."); return
        with db._get_conn() as conn:
            conn.execute("UPDATE payg_accounts SET status='active',last_alert_level=0,updated_at=? WHERE user_id=?", (_now(), uid))
        rates = [int(x) for x in json.loads(row['month_rates'] or json.dumps(get_rates(db)))]
        limit = _affordable_limit_bytes(balance, rates, _billing_base_bytes(db, uid), int(row['month_used_bytes'] or 0))
        db.set_quota_pool_limit(int(row['quota_pool_id']), limit / GIB)
        await call.message.answer("✅ حساب PayG دوباره فعال شد.")
        await _show_admin_user(call.message, uid)

    @router.callback_query(F.data.startswith("payg:admin_users:"))
    async def payg_admin_users(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        offset = max(0, int(call.data.rsplit(":", 1)[1]))
        with db._get_conn() as conn:
            rows = conn.execute("SELECT user_id,status,month_used_bytes,month_cost FROM payg_accounts ORDER BY updated_at DESC LIMIT 10 OFFSET ?", (offset,)).fetchall()
            total = conn.execute("SELECT COUNT(*) n FROM payg_accounts").fetchone()['n']
        buttons = [[InlineKeyboardButton(text=f"{r['user_id']} · {r['status']} · {int(r['month_cost'] or 0):,} تومان", callback_data=f"payg:admin_user:{int(r['user_id'])}")] for r in rows]
        nav=[]
        if offset > 0: nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"payg:admin_users:{max(0,offset-10)}"))
        if offset + 10 < int(total): nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"payg:admin_users:{offset+10}"))
        if nav: buttons.append(nav)
        buttons.append([InlineKeyboardButton(text="🔎 جستجوی آیدی", callback_data="payg:admin_user_search"), InlineKeyboardButton(text="↩️ مدیریت PayG", callback_data="adm_payg")])
        await call.message.answer(f"👥 حساب‌های PayG ({offset+1} تا {min(offset+10,int(total))} از {int(total)})", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @router.callback_query(F.data.startswith("payg:admin_user:"))
    async def payg_admin_user_detail(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        await _show_admin_user(call.message, int(call.data.rsplit(":", 1)[1]))

    @router.callback_query(F.data.startswith("payg:admin_service:"))
    async def payg_admin_service_detail(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        try:
            _, _, uid_raw, service_pk_raw = call.data.split(":", 3)
            uid, service_pk = int(uid_raw), int(service_pk_raw)
        except Exception:
            await call.message.answer("شناسه سرویس نامعتبر است."); return
        with db._get_conn() as conn:
            row = conn.execute("SELECT ps.service_kind,ps.service_id,ps.last_billed_bytes,s.used_bytes,s.reported_at,s.source FROM payg_services ps LEFT JOIN usage_snapshots s ON s.service_kind=ps.service_kind AND s.service_id=ps.service_id WHERE ps.user_id=? AND ps.id=?", (uid, service_pk)).fetchone()
        if not row:
            await call.message.answer("سرویس پیدا نشد."); return
        used = int(row['used_bytes'] or 0)
        billed = int(row['last_billed_bytes'] or 0)
        kind, sid = row['service_kind'], row['service_id']
        await call.message.answer(f"🔍 <b>جزئیات سرویس</b>\nکاربر: {uid}\nنوع: {kind.upper()}\nشناسه: <code>{sid}</code>\nمصرف گزارش‌شده: {used/GIB:.3f} GB\nآخرین مصرف تسویه‌شده: {billed/GIB:.3f} GB\nمنبع آمار: {row['source'] or 'نامشخص'}\nآخرین گزارش: {row['reported_at'] or 'ندارد'}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ بازگشت به کاربر", callback_data=f"payg:admin_user:{uid}")]]))

    @router.callback_query(F.data.startswith("payg:admin_user_tx:"))
    async def payg_admin_user_transactions(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        uid = int(call.data.rsplit(":", 1)[1])
        with db._get_conn() as conn:
            rows = conn.execute("SELECT service_kind,service_id,used_bytes,amount,created_at FROM payg_transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
        lines=[f"🧾 <b>۲۰ برداشت آخر کاربر {uid}</b>"]
        for r in rows: lines.append(f"{r['service_kind']} · {r['service_id']} | {int(r['used_bytes'])/GIB:.3f} GB | {int(r['amount']):,} تومان | {str(r['created_at'])[:16]}")
        if not rows: lines.append("تراکنشی ثبت نشده است.")
        await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ بازگشت به کاربر", callback_data=f"payg:admin_user:{uid}")]]))

    @router.callback_query(F.data == "payg:admin_report")
    async def payg_admin_report(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id): return
        with db._get_conn() as conn:
            rows = conn.execute("SELECT service_kind,COUNT(*) tx,COALESCE(SUM(used_bytes),0) bytes,COALESCE(SUM(amount),0) amount FROM payg_transactions WHERE substr(cycle_key,1,7)=? GROUP BY service_kind", (_month_key(),)).fetchall()
            alerts = conn.execute("SELECT COUNT(*) n FROM payg_accounts WHERE status='active' AND last_balance<=0").fetchone()['n']
        lines=["📈 <b>گزارش ماه جاری PayG</b>", f"حساب‌های فعال با موجودی صفر: {int(alerts or 0)}"]
        for r in rows: lines.append(f"{r['service_kind'].upper()}: {int(r['tx'])} تراکنش | {int(r['bytes'])/GIB:.3f} GB | {int(r['amount']):,} تومان")
        if not rows: lines.append("هنوز تراکنشی ثبت نشده است.")
        await call.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ بازگشت", callback_data="adm_payg")]]), parse_mode="HTML")

    @router.callback_query(F.data == "payg:admin_servers")
    async def payg_admin_servers(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id):
            return
        servers = await asyncio.to_thread(db.get_panel_servers, True)
        selected = set(get_payg_panel_ids(db))
        rows = []
        for server in servers:
            sid = int(server["id"])
            mark = "✅" if sid in selected else "▫️"
            info = await asyncio.to_thread(db.get_panel_capacity_info, sid)
            load = ""
            if info:
                load = (f" · {int(info['active_services'])}/{info['max_services']} ظرفیت"
                        if info.get("max_services") else f" · {int(info['active_services'])} سرویس")
            rows.append([InlineKeyboardButton(
                text=f"{mark} {server['name']} · #{sid}{load}",
                callback_data=f"payg:admin_server_toggle:{sid}",
            )])
        rows.append([InlineKeyboardButton(text="🧹 پاک‌کردن همه انتخاب‌ها", callback_data="payg:admin_server_clear")])
        rows.append([InlineKeyboardButton(text="↩️ بازگشت", callback_data="adm_payg")])
        await call.message.answer(
            "🖥 <b>انتخاب چندپنل برای Pay As You Go</b>\n"
            "هر تعداد پنل فعال می‌خواهید انتخاب کنید. هنگام ساخت سرویس، سیستم به‌صورت خودکار پنل دارای ظرفیت و بار کمتر را انتخاب می‌کند.\n"
            "پنل‌های انتخاب‌شده فقط برای سرویس‌های جدید استفاده می‌شوند؛ سرویس‌های قبلی روی پنل خود باقی می‌مانند.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML",
        )

    @router.callback_query(F.data.startswith("payg:admin_server_toggle:"))
    async def payg_admin_set_server(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return
        try:
            server_id = int(call.data.rsplit(":", 1)[1])
        except Exception:
            await call.message.answer("شناسه پنل نامعتبر است.")
            return
        server = await asyncio.to_thread(db.get_panel_server, server_id)
        if not server or not server["is_active"]:
            await call.message.answer("پنل فعال پیدا نشد.")
            return
        selected = set(get_payg_panel_ids(db))
        if server_id in selected:
            selected.remove(server_id)
        else:
            selected.add(server_id)
        ordered = sorted(selected)
        db.set_setting("payg_panel_server_ids", json.dumps(ordered))
        db.set_setting("payg_panel_server_id", str(ordered[0]) if ordered else "")
        await payg_admin_servers(call)

    @router.callback_query(F.data == "payg:admin_server_clear")
    async def payg_admin_server_clear(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return
        db.set_setting("payg_panel_server_ids", "[]")
        db.set_setting("payg_panel_server_id", "")
        await payg_admin_servers(call)

    @router.callback_query(F.data == "payg:admin_toggle")
    async def payg_admin_toggle(call: CallbackQuery):
        await call.answer()
        if not db.is_full_admin(call.from_user.id):
            return
        new_value = "0" if db.get_setting("payg_enabled", "1") == "1" else "1"
        db.set_setting("payg_enabled", new_value)
        await _show_admin_home(call.message)

    @router.message(Command("payg_history"))
    async def payg_history(message: Message):
        with db._get_conn() as conn:
            rows = conn.execute("SELECT service_kind,used_bytes,amount,created_at FROM payg_transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (message.from_user.id,)).fetchall()
        if not rows:
            await message.answer("هنوز تراکنشی برای Pay As You Go ثبت نشده است.")
            return
        lines = ["🧾 <b>آخرین برداشت‌های Pay As You Go</b>"]
        for row in rows:
            lines.append(f"• {row['service_kind'].upper()} | {int(row['used_bytes'])/GIB:.3f} GB | {int(row['amount']):,} تومان | {str(row['created_at'])[:16]}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(Command("payg_admin"))
    async def payg_admin(message: Message):
        if not db.is_full_admin(message.from_user.id):
            return
        await _show_admin_home(message)

    @router.message(Command("payg_rate"))
    async def payg_rate(message: Message):
        if not db.is_full_admin(message.from_user.id):
            return
        parts = (message.text or "").split()
        try:
            rates = [int(x) for x in parts[1:]]
            if len(rates) != 4 or any(x <= 0 for x in rates) or rates != sorted(rates, reverse=True):
                raise ValueError
        except Exception:
            await message.answer("فرمت صحیح: /payg_rate 5000 4500 4000 3500\nقیمت‌ها باید مثبت و نزولی باشند.")
            return
        db.set_setting("payg_rates", json.dumps(rates))
        await message.answer("✅ تعرفه‌های Pay As You Go ذخیره شد. برای حساب‌های فعال، تعرفه‌ی دوره‌ی جاری ثابت می‌ماند و نرخ جدید از ابتدای ماه بعد اعمال می‌شود.")

    @router.message(Command("payg_cycle"))
    async def payg_cycle_set(message: Message):
        if not db.is_full_admin(message.from_user.id):
            return
        parts = (message.text or "").split()
        try:
            seconds = int(parts[1])
            if not 60 <= seconds <= 86400:
                raise ValueError
        except Exception:
            await message.answer("فرمت صحیح: /payg_cycle 600 (محدوده مجاز: ۶۰ تا ۸۶۴۰۰ ثانیه)")
            return
        db.set_setting("payg_cycle_seconds", str(seconds))
        await message.answer(f"✅ چرخه تسویه از چرخه بعدی روی {seconds} ثانیه تنظیم شد.")

    @router.message(Command("payg_max_services"))
    async def payg_max_services_set(message: Message):
        if not db.is_full_admin(message.from_user.id):
            return
        parts = (message.text or "").split()
        try:
            maximum = int(parts[1])
            if not 1 <= maximum <= 100:
                raise ValueError
        except Exception:
            await message.answer("فرمت صحیح: /payg_max_services 5 (محدوده مجاز: ۱ تا ۱۰۰)")
            return
        db.set_setting("payg_max_services_per_user", str(maximum))
        await message.answer(f"✅ حداکثر سرویس PayG برای هر کاربر روی {maximum} تنظیم شد.")

    @router.message(Command("payg_enable"))
    async def payg_enable(message: Message):
        if db.is_full_admin(message.from_user.id):
            db.set_setting("payg_enabled", "1")
            await message.answer("✅ فروش Pay As You Go فعال شد.")

    @router.message(Command("payg_disable"))
    async def payg_disable(message: Message):
        if db.is_full_admin(message.from_user.id):
            db.set_setting("payg_enabled", "0")
            await message.answer("⛔ فروش جدید Pay As You Go غیرفعال شد. حساب‌های فعال طبق تسویه ادامه می‌دهند.")

    return router
