"""Payload builders for the extra admin widgets: live pulse, alerts center, leaderboards, sales analysis.

All payloads stay small (< 1000 bytes JSON) because widget answers are limited to that size.
Day/hour bucketing uses Tehran time (UTC+03:30).
"""
import json
from typing import Optional

_TZ = "+210 minutes"
_PRICE = "COALESCE(o.final_price, p.price)"

# alerts payload index -> callback fed to the bot when the admin taps «باز کردن»
ALERT_TARGETS = {
    0: "adm_wqueue",
    1: "adm_wqueue",
    2: "adm_hub:support",
    3: "adm_whealth",
}

TOP_TABS = ("p", "b", "r")
TOP_PERIODS = ("7", "30", "0")
ANALYSIS_TABS = ("h", "c", "x")


def _dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _fit(payload: dict, list_key: Optional[str] = None) -> dict:
    """Trim the trailing rows of ``list_key`` until the JSON fits the 1000-byte answer limit."""
    while list_key and len(_dumps(payload).encode()) > 950 and payload.get(list_key):
        payload[list_key] = payload[list_key][:-1]
    return payload


def _name(row_name, row_username, tg_id) -> str:
    return str(row_name or row_username or tg_id)[:12]


def _count(db, method: str) -> int:
    try:
        return len(getattr(db, method)() or [])
    except Exception:
        return 0


def _panels_down(conn) -> int:
    try:
        return int(conn.execute(
            "SELECT COUNT(*) c FROM panel_health h JOIN panel_servers s ON s.id=h.server_id "
            "WHERE h.status='down' AND s.is_active=1"
        ).fetchone()["c"])
    except Exception:
        return 0


def _day_revenue(conn, day: str):
    row = conn.execute(
        f"SELECT COALESCE(SUM({_PRICE}),0) s, COUNT(*) c FROM orders o JOIN products p ON o.product_id=p.id "
        "WHERE o.status='approved' AND date(o.created_at, ?)=?",
        (_TZ, day),
    ).fetchone()
    topup = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM wallet_topups WHERE status='approved' AND date(created_at, ?)=?",
        (_TZ, day),
    ).fetchone()["s"]
    return int(row["s"] or 0) + int(topup or 0), int(row["c"] or 0)


def pulse_payload(db, back: int = 0) -> dict:
    back = 1 if back == 1 else 0
    with db._get_conn() as conn:
        day = conn.execute("SELECT date('now', ?, ?) d", (_TZ, f"-{back} days")).fetchone()["d"]
        prev_day = conn.execute("SELECT date(?, '-1 day') d", (day,)).fetchone()["d"]
        revenue, orders = _day_revenue(conn, day)
        prev_revenue, _ = _day_revenue(conn, prev_day)
        hours = [0] * 24
        for r in conn.execute(
            f"SELECT CAST(strftime('%H', o.created_at, ?) AS INTEGER) h, COALESCE(SUM({_PRICE}),0) s "
            "FROM orders o JOIN products p ON o.product_id=p.id "
            "WHERE o.status='approved' AND date(o.created_at, ?)=? GROUP BY h",
            (_TZ, _TZ, day),
        ).fetchall():
            hours[int(r["h"])] += int(r["s"] or 0)
        for r in conn.execute(
            "SELECT CAST(strftime('%H', created_at, ?) AS INTEGER) h, COALESCE(SUM(amount),0) s "
            "FROM wallet_topups WHERE status='approved' AND date(created_at, ?)=? GROUP BY h",
            (_TZ, _TZ, day),
        ).fetchall():
            hours[int(r["h"])] += int(r["s"] or 0)
        users = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE date(joined_at, ?)=?", (_TZ, day)
        ).fetchone()["c"]
        down = _panels_down(conn)
    try:
        tickets = int(db.count_open_tickets() or 0)
    except Exception:
        tickets = 0
    pending = _count(db, "get_pending_orders") + _count(db, "get_pending_topups")
    return {
        "b": back, "r": revenue, "p": prev_revenue, "o": orders, "u": int(users or 0),
        "h": [v // 1000 for v in hours], "q": pending, "t": tickets, "d": down,
    }


def alerts_payload(db) -> dict:
    orders = len([o for o in (db.get_pending_orders() or []) if not o["lootbox_type_id"]])
    topups = _count(db, "get_pending_topups")
    try:
        tickets = int(db.count_open_tickets() or 0)
    except Exception:
        tickets = 0
    with db._get_conn() as conn:
        down = _panels_down(conn)

        def expiring(days: int) -> int:
            try:
                return int(conn.execute(
                    "SELECT COUNT(*) c FROM custom_configs WHERE status='active' AND source != 'test' "
                    "AND expires_at IS NOT NULL AND datetime(expires_at) BETWEEN datetime('now') "
                    "AND datetime('now', ?)",
                    (f"+{days} days",),
                ).fetchone()["c"])
            except Exception:
                return 0

        exp1, exp3 = expiring(1), expiring(3)
    return {"a": [orders, topups, tickets, down, exp1, exp3]}


def _period_clause(period: str, column: str):
    if period == "0":
        return "", ()
    return f" AND date({column}) >= date('now', ?)", (f"-{int(period) - 1} days",)


def top_payload(db, tab: str = "p", period: str = "30") -> dict:
    tab = tab if tab in TOP_TABS else "p"
    period = period if period in TOP_PERIODS else "30"
    rows = []
    with db._get_conn() as conn:
        if tab == "p":
            clause, args = _period_clause(period, "o.created_at")
            for r in conn.execute(
                f"SELECT p.name n, COUNT(*) c, COALESCE(SUM({_PRICE}),0) s FROM orders o "
                "JOIN products p ON o.product_id=p.id WHERE o.status='approved'" + clause +
                " GROUP BY p.id ORDER BY c DESC, s DESC LIMIT 5", args,
            ).fetchall():
                rows.append([str(r["n"] or "؟")[:14], int(r["c"]), int(r["s"] or 0)])
        elif tab == "b":
            clause, args = _period_clause(period, "o.created_at")
            for r in conn.execute(
                f"SELECT u.telegram_id id, u.first_name fn, u.username un, COUNT(*) c, "
                f"COALESCE(SUM({_PRICE}),0) s FROM orders o JOIN products p ON o.product_id=p.id "
                "JOIN users u ON u.telegram_id=o.user_id WHERE o.status='approved'" + clause +
                " GROUP BY u.telegram_id ORDER BY s DESC LIMIT 5", args,
            ).fetchall():
                rows.append([_name(r["fn"], r["un"], r["id"]), int(r["c"]), int(r["s"] or 0)])
        else:
            clause, args = _period_clause(period, "u.joined_at")
            for r in conn.execute(
                "SELECT i.telegram_id id, i.first_name fn, i.username un, COUNT(*) c FROM users u "
                "JOIN users i ON i.telegram_id=u.referred_by WHERE u.referred_by IS NOT NULL" + clause +
                " GROUP BY i.telegram_id ORDER BY c DESC LIMIT 5", args,
            ).fetchall():
                rows.append([_name(r["fn"], r["un"], r["id"]), int(r["c"]), 0])
    return _fit({"t": tab, "e": period, "r": rows}, "r")


def analysis_payload(db, tab: str = "h") -> dict:
    tab = tab if tab in ANALYSIS_TABS else "h"
    with db._get_conn() as conn:
        if tab == "h":
            days = [r["d"] for r in conn.execute(
                "WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i+1 FROM n WHERE i<29) "
                "SELECT date('now', ?, '-' || (29-i) || ' days') d FROM n ORDER BY i", (_TZ,)
            ).fetchall()]
            totals = dict.fromkeys(days, 0)
            for r in conn.execute(
                f"SELECT date(o.created_at, ?) d, COALESCE(SUM({_PRICE}),0) s FROM orders o "
                "JOIN products p ON o.product_id=p.id WHERE o.status='approved' AND date(o.created_at, ?) >= ? "
                "GROUP BY d", (_TZ, _TZ, days[0]),
            ).fetchall():
                if r["d"] in totals:
                    totals[r["d"]] += int(r["s"] or 0)
            for r in conn.execute(
                "SELECT date(created_at, ?) d, COALESCE(SUM(amount),0) s FROM wallet_topups "
                "WHERE status='approved' AND date(created_at, ?) >= ? GROUP BY d", (_TZ, _TZ, days[0]),
            ).fetchall():
                if r["d"] in totals:
                    totals[r["d"]] += int(r["s"] or 0)
            return {"t": "h", "v": [totals[d] // 1000 for d in days]}
        if tab == "c":
            cats = conn.execute(
                f"SELECT c.name n, COUNT(*) c, COALESCE(SUM({_PRICE}),0) s FROM orders o "
                "JOIN products p ON o.product_id=p.id JOIN categories c ON p.category_id=c.id "
                "WHERE o.status='approved' AND date(o.created_at) >= date('now','-29 days') "
                "GROUP BY c.id ORDER BY s DESC LIMIT 5"
            ).fetchall()
            total = sum(int(r["s"] or 0) for r in cats) or 1
            ref = conn.execute(
                f"SELECT COALESCE(SUM(CASE WHEN u.referred_by IS NOT NULL THEN {_PRICE} ELSE 0 END),0) a, "
                f"COALESCE(SUM({_PRICE}),0) b FROM orders o JOIN products p ON o.product_id=p.id "
                "JOIN users u ON o.user_id=u.telegram_id WHERE o.status='approved' "
                "AND date(o.created_at) >= date('now','-29 days')"
            ).fetchone()
            ref_pct = round(int(ref["a"] or 0) / int(ref["b"]) * 100) if ref["b"] else 0
            rows = [[str(r["n"] or "؟")[:14], int(r["c"]), round(int(r["s"] or 0) / total * 100)] for r in cats]
            return _fit({"t": "c", "r": rows, "f": ref_pct}, "r")
        hours = [0] * 24
        for r in conn.execute(
            "SELECT CAST(strftime('%H', created_at, ?) AS INTEGER) h, COUNT(*) c FROM orders "
            "WHERE status='approved' AND date(created_at) >= date('now','-29 days') GROUP BY h", (_TZ,),
        ).fetchall():
            hours[int(r["h"])] += int(r["c"])
        return {"t": "x", "v": hours}
