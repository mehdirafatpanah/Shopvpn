# -*- coding: utf-8 -*-
"""Unified, searchable view over every subscription a user owns.

Three kinds of services live in three different tables:
  * custom - direct-panel services (custom_configs), including free tests
  * bank   - pre-made links assigned from the config bank (configs)
  * ssh    - SSH accounts (ssh_accounts)

The admin web panel's "Active subscriptions" page needs one list across all of
them, searchable by service name, numeric Telegram id or Telegram username.
"""


class SubscriptionsMixin:
    _SUBS_UNION = (
        "SELECT 'custom' AS kind, cc.id AS rid, CAST(cc.id AS TEXT) AS sid, cc.user_id AS user_id, "
        "COALESCE(NULLIF(cc.display_name,''), cc.username) AS name, cc.username AS raw_name, "
        "cc.volume_gb AS volume_gb, cc.duration_days AS duration_days, cc.subscription_url AS link, "
        "cc.created_at AS created_at, cc.expires_at AS expires_at, "
        "CASE WHEN COALESCE(cc.enabled,1)=0 OR COALESCE(cc.status,'active')='cancelled' THEN 1 ELSE 0 END AS is_disabled, "
        "CASE WHEN COALESCE(cc.status,'active')='expired' THEN 1 ELSE 0 END AS is_expired_flag, "
        "COALESCE(cc.auto_renew,0) AS auto_renew, "
        "CASE WHEN cc.source='test' THEN 1 ELSE 0 END AS is_test, '' AS extra "
        "FROM custom_configs cc "
        "UNION ALL "
        "SELECT 'bank', cf.id, CAST(cf.id AS TEXT), cf.assigned_user_id, "
        "COALESCE(NULLIF(p.name,''),'کانفیگ بانک') || ' #' || cf.id, COALESCE(p.name,''), "
        "NULL, NULL, cf.link, cf.assigned_at, cf.expires_at, "
        "COALESCE(cf.is_disabled,0), 0, 0, 0, COALESCE(p.name,'') "
        "FROM configs cf LEFT JOIN products p ON p.id=cf.product_id "
        "WHERE cf.is_used=1 AND cf.assigned_user_id IS NOT NULL "
        "UNION ALL "
        "SELECT 'ssh', sa.id, sa.account_id, sa.user_id, sa.username, sa.username, "
        "NULL, NULL, NULL, sa.created_at, sa.expires_at, "
        "CASE WHEN sa.status IN ('disabled','suspended') THEN 1 ELSE 0 END, "
        "CASE WHEN sa.status='expired' THEN 1 ELSE 0 END, 0, 0, "
        "COALESCE(n.name,'') || ' / ' || COALESCE(sa.protocol,'ssh') "
        "FROM ssh_accounts sa LEFT JOIN ssh_nodes n ON n.id=sa.node_id "
        "WHERE COALESCE(sa.status,'') NOT IN ('deleted','pending')"
    )

    _SUBS_EXPIRED_SQL = (
        "(x.is_expired_flag=1 OR (TRIM(COALESCE(x.expires_at,''))!='' "
        "AND datetime(x.expires_at) IS NOT NULL AND datetime(x.expires_at) <= datetime('now')))"
    )

    _SUBS_SORTS = {
        "newest": "s.created_at DESC, s.rid DESC",
        "oldest": "s.created_at ASC, s.rid ASC",
        "expiry_asc": "(s.expires_at IS NULL OR TRIM(s.expires_at)='') ASC, datetime(s.expires_at) ASC, s.rid DESC",
        "expiry_desc": "(s.expires_at IS NULL OR TRIM(s.expires_at)='') ASC, datetime(s.expires_at) DESC, s.rid DESC",
        "name": "LOWER(s.name) ASC, s.rid DESC",
    }

    @staticmethod
    def _subs_like(value: str) -> str:
        escaped = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return "%" + escaped + "%"

    def _subs_base_sql(self) -> str:
        return (
            "SELECT x.*, u.username AS user_username, u.first_name AS user_first_name, "
            "COALESCE(u.is_blocked,0) AS user_blocked, COALESCE(u.referral_credit,0) AS user_wallet, "
            "CASE WHEN x.is_disabled=1 THEN 'disabled' "
            f"WHEN {self._SUBS_EXPIRED_SQL} THEN 'expired' ELSE 'active' END AS state "
            "FROM (" + self._SUBS_UNION + ") x LEFT JOIN users u ON u.telegram_id=x.user_id"
        )

    def _subs_where(self, query: str, kind: str):
        clauses, params = [], []
        kind = (kind or "all").strip().lower()
        if kind == "test":
            clauses.append("(s.kind='custom' AND s.is_test=1)")
        elif kind == "custom":
            clauses.append("(s.kind='custom' AND s.is_test=0)")
        elif kind in ("bank", "ssh"):
            clauses.append("s.kind=?")
            params.append(kind)
        q = (query or "").strip()
        if q.startswith("@"):
            q = q[1:]
        if q:
            like = self._subs_like(q)
            clauses.append(
                "(CAST(s.user_id AS TEXT) LIKE ? ESCAPE '\\' OR COALESCE(s.user_username,'') LIKE ? ESCAPE '\\' "
                "OR COALESCE(s.user_first_name,'') LIKE ? ESCAPE '\\' OR COALESCE(s.name,'') LIKE ? ESCAPE '\\' "
                "OR COALESCE(s.raw_name,'') LIKE ? ESCAPE '\\' OR COALESCE(s.link,'') LIKE ? ESCAPE '\\' "
                "OR s.sid LIKE ? ESCAPE '\\' "
                "OR (s.kind='custom' AND EXISTS (SELECT 1 FROM config_panel_links cpl WHERE cpl.custom_config_id=s.rid "
                "AND (COALESCE(cpl.username,'') LIKE ? ESCAPE '\\' OR COALESCE(cpl.subscription_url,'') LIKE ? ESCAPE '\\'))))"
            )
            params.extend([like] * 9)
        return clauses, params

    def search_subscriptions(self, query: str = "", kind: str = "all", status: str = "active",
                             sort: str = "newest", limit: int = 25, offset: int = 0):
        """Returns (rows, total, counts). counts = {active, expired, disabled} for the current
        search/kind filter, regardless of the selected status, so the UI can show chip badges."""
        clauses, params = self._subs_where(query, kind)
        base = self._subs_base_sql()
        where_no_status = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        status = (status or "active").strip().lower()
        row_clauses, row_params = list(clauses), list(params)
        if status in ("active", "expired", "disabled"):
            row_clauses.append("s.state=?")
            row_params.append(status)
        where = ("WHERE " + " AND ".join(row_clauses)) if row_clauses else ""
        order = self._SUBS_SORTS.get(sort, self._SUBS_SORTS["newest"])
        with self._get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM ({base}) s {where}", row_params).fetchone()[0]
            rows = conn.execute(
                f"SELECT s.* FROM ({base}) s {where} ORDER BY {order} LIMIT ? OFFSET ?",
                row_params + [int(limit), int(offset)],
            ).fetchall()
            count_rows = conn.execute(
                f"SELECT s.state AS state, COUNT(*) AS n FROM ({base}) s {where_no_status} GROUP BY s.state",
                params,
            ).fetchall()
        counts = {"active": 0, "expired": 0, "disabled": 0}
        for r in count_rows:
            counts[r["state"]] = r["n"]
        return rows, total, counts
