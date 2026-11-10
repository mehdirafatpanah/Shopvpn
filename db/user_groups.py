# -*- coding: utf-8 -*-
"""Saved, admin-defined dynamic user groups."""

import json
from datetime import datetime


class UserGroupsMixin:
    _GROUP_ANY_SERVICE = (
        "(EXISTS (SELECT 1 FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test') "
        "OR EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) "
        "OR EXISTS (SELECT 1 FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id))"
    )
    _GROUP_ACTIVE_SERVICE = (
        "(EXISTS (SELECT 1 FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test' "
        "AND cc.status='active' AND (cc.expires_at IS NULL OR cc.expires_at=' ' OR cc.expires_at>?)) "
        "OR EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) "
        "OR EXISTS (SELECT 1 FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id AND sa.status='active' "
        "AND (sa.expires_at IS NULL OR sa.expires_at>?)))"
    )

    _GROUP_FIELD_SQL = {
        "telegram_id": "u.telegram_id",
        "username": "COALESCE(u.username,'')",
        "first_name": "COALESCE(u.first_name,'')",
        "joined_at": "u.joined_at",
        "is_blocked": "COALESCE(u.is_blocked,0)",
        "phone_verified": "COALESCE(u.phone_verified,0)",
        "wallet_balance": "COALESCE(u.referral_credit,0)",
        "purchase_count": "(SELECT COUNT(*) FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved')",
        "total_purchase": "(SELECT COALESCE(SUM(COALESCE(o.final_price,p.price)),0) FROM orders o JOIN products p ON p.id=o.product_id WHERE o.user_id=u.telegram_id AND o.status='approved')",
        "last_purchase_at": "(SELECT MAX(o.created_at) FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved')",
        "topup_total": "(SELECT COALESCE(SUM(wt.amount),0) FROM wallet_topups wt WHERE wt.user_id=u.telegram_id AND wt.status='approved')",
        "active_services": "((SELECT COUNT(*) FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test' AND cc.status='active' AND (cc.expires_at IS NULL OR cc.expires_at>?)) + (SELECT COUNT(*) FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) + (SELECT COUNT(*) FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id AND sa.status='active' AND (sa.expires_at IS NULL OR sa.expires_at>?)))",
        "last_service_at": "(SELECT MAX(x.created_at) FROM (SELECT cc.created_at FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test' UNION ALL SELECT sa.created_at FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id UNION ALL SELECT c.assigned_at AS created_at FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) x)",
        "service_expiry_at": "(SELECT MAX(x.expires_at) FROM (SELECT cc.expires_at FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test' UNION ALL SELECT sa.expires_at FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id) x)",
        "referrals_count": "(SELECT COUNT(*) FROM users ru WHERE ru.referred_by=u.telegram_id)",
    }

    _GROUP_SEARCH_SQL = (
        "(CAST(u.telegram_id AS TEXT) LIKE ? OR COALESCE(u.username,'') LIKE ? OR COALESCE(u.first_name,'') LIKE ? "
        "OR EXISTS (SELECT 1 FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND "
        "(COALESCE(cc.subscription_url,'') LIKE ? OR COALESCE(cc.username,'') LIKE ? OR CAST(cc.id AS TEXT) LIKE ?)) "
        "OR EXISTS (SELECT 1 FROM config_panel_links cpl JOIN custom_configs cc2 ON cc2.id=cpl.custom_config_id "
        "WHERE cc2.user_id=u.telegram_id AND (COALESCE(cpl.subscription_url,'') LIKE ? OR COALESCE(cpl.username,'') LIKE ?)) "
        "OR EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND "
        "(COALESCE(c.link,'') LIKE ? OR CAST(c.id AS TEXT) LIKE ?)) "
        "OR EXISTS (SELECT 1 FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id AND "
        "(COALESCE(sa.username,'') LIKE ? OR COALESCE(sa.account_id,'') LIKE ? OR CAST(sa.id AS TEXT) LIKE ?)))"
    )

    def _normalize_group_rules(self, rules):
        if not isinstance(rules, dict):
            raise ValueError("ساختار شرط‌های گروه نامعتبر است.")
        match = "any" if str(rules.get("match", "all")).lower() == "any" else "all"
        allowed_fields = set(self._GROUP_FIELD_SQL) | {"service_type", "service_status", "purchase_date"}
        allowed_ops = {"eq", "is", "ne", "neq", "is_not", "contains", "starts", "gt", "after", "gte", "on_or_after", "lt", "before", "lte", "on_or_before", "between", "empty", "not_empty"}
        raw_conditions = rules.get("conditions", [])
        if not isinstance(raw_conditions, list) or len(raw_conditions) > 20:
            raise ValueError("حداکثر ۲۰ شرط برای هر گروه مجاز است.")
        conditions = []
        for item in raw_conditions:
            if not isinstance(item, dict):
                raise ValueError("یکی از شرط‌های گروه نامعتبر است.")
            field = str(item.get("field", "")).strip()
            op = str(item.get("op", "eq")).strip().lower()
            if field not in allowed_fields or op not in allowed_ops:
                raise ValueError("نوع فیلد یا عملگر یکی از شرط‌ها پشتیبانی نمی‌شود.")
            text_fields = {"username", "first_name"}
            date_fields = {"joined_at", "last_purchase_at", "last_service_at", "service_expiry_at", "purchase_date"}
            numeric_fields = {"telegram_id", "wallet_balance", "purchase_count", "total_purchase", "topup_total", "active_services", "referrals_count"}
            bool_fields = {"is_blocked", "phone_verified"}
            field_ops = (
                {"eq", "is", "ne", "neq", "is_not", "contains", "starts", "empty", "not_empty"} if field in text_fields else
                {"eq", "is", "ne", "neq", "is_not", "gt", "after", "gte", "on_or_after", "lt", "before", "lte", "on_or_before", "between", "empty", "not_empty"} if field in date_fields else
                {"eq", "is", "ne", "neq", "is_not", "gt", "after", "gte", "on_or_after", "lt", "before", "lte", "on_or_before", "between"} if field in numeric_fields else
                {"eq", "is", "ne", "neq", "is_not"}
            )
            if op not in field_ops:
                raise ValueError("این عملگر برای فیلد انتخاب‌شده پشتیبانی نمی‌شود.")
            value = item.get("value", "")
            value2 = item.get("value2", "")
            if isinstance(value, (dict, list)) or isinstance(value2, (dict, list)):
                raise ValueError("مقدار شرط نامعتبر است.")
            conditions.append({"field": field, "op": op, "value": str(value)[:256], "value2": str(value2)[:256]})
        return {"match": match, "conditions": conditions}

    def _user_group_condition_sql(self, rules, now):
        rules = self._normalize_group_rules(rules)
        clauses, params = [], []
        for rule in rules["conditions"]:
            field, op = rule["field"], rule["op"]
            value, value2 = rule.get("value", ""), rule.get("value2", "")
            numeric_fields = {"telegram_id", "is_blocked", "phone_verified", "wallet_balance", "purchase_count", "total_purchase", "topup_total", "active_services", "referrals_count"}
            if field in numeric_fields:
                try:
                    value = int(float(value))
                    if op == "between":
                        value2 = int(float(value2))
                except (TypeError, ValueError, OverflowError):
                    continue

            if field == "purchase_date":
                if op == "empty":
                    clauses.append("NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved')")
                elif op == "not_empty":
                    clauses.append("EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved')")
                else:
                    date_ops = {"eq": "=", "is": "=", "gt": ">", "after": ">", "gte": ">=", "on_or_after": ">=", "lt": "<", "before": "<", "lte": "<=", "on_or_before": "<="}
                    if op in ("ne", "neq", "is_not"):
                        clauses.append("NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved' AND date(o.created_at)=date(?))")
                        params.append(value)
                    elif op == "between":
                        clauses.append("EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved' AND date(o.created_at)>=date(?) AND date(o.created_at)<=date(?))")
                        params.extend([value, value2])
                    elif op in date_ops:
                        clauses.append(f"EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved' AND date(o.created_at){date_ops[op]}date(?))")
                        params.append(value)
                continue

            if field == "service_type":
                v = str(value or "").strip().lower()
                type_sql = {
                    "custom": "EXISTS (SELECT 1 FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test')",
                    "bank": "EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1)",
                    "ssh": "EXISTS (SELECT 1 FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id)",
                    "vpn": "(EXISTS (SELECT 1 FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test') OR EXISTS (SELECT 1 FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1))",
                    "any": self._GROUP_ANY_SERVICE,
                    "none": "NOT " + self._GROUP_ANY_SERVICE,
                }.get(v)
                if not type_sql:
                    continue
                clauses.append(f"({type_sql})" if op not in ("ne", "not", "neq") else f"(NOT ({type_sql}))")
                continue

            if field == "service_status":
                active = self._GROUP_ACTIVE_SERVICE
                any_service = self._GROUP_ANY_SERVICE
                v = str(value or "").strip().lower()
                status_sql = None
                if v == "active":
                    status_sql = active
                    params.extend([now, now])
                elif v == "expired":
                    status_sql = f"({any_service} AND NOT {active})"
                    params.extend([now, now])
                elif v in ("none", "no_service"):
                    status_sql = f"NOT {any_service}"
                elif v == "any":
                    status_sql = any_service
                if status_sql:
                    if op in ("ne", "not", "neq"):
                        status_sql = f"NOT ({status_sql})"
                    clauses.append(status_sql)
                continue

            expr = self._GROUP_FIELD_SQL.get(field)
            if not expr:
                continue
            # The active_services expression contains two expiry placeholders.
            if field == "active_services":
                params.extend([now, now])
            is_date = field in ("joined_at", "last_purchase_at", "last_service_at", "service_expiry_at")
            compare_expr = f"date({expr})" if is_date else expr
            compare_value = f"date(?)" if is_date else "?"
            if op in ("eq", "is"):
                clauses.append(f"({compare_expr} = {compare_value})")
                params.append(value)
            elif op in ("ne", "neq", "is_not"):
                clauses.append(f"({compare_expr} != {compare_value})")
                params.append(value)
            elif op == "contains" and field in ("username", "first_name"):
                clauses.append(f"({expr} LIKE ? ESCAPE '\\')")
                params.append("%" + str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
            elif op == "starts" and field in ("username", "first_name"):
                clauses.append(f"({expr} LIKE ? ESCAPE '\\')")
                params.append(str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
            elif op in ("gt", "after"):
                clauses.append(f"({compare_expr} > {compare_value})")
                params.append(value)
            elif op in ("gte", "on_or_after"):
                clauses.append(f"({compare_expr} >= {compare_value})")
                params.append(value)
            elif op in ("lt", "before"):
                clauses.append(f"({compare_expr} < {compare_value})")
                params.append(value)
            elif op in ("lte", "on_or_before"):
                clauses.append(f"({compare_expr} <= {compare_value})")
                params.append(value)
            elif op == "between":
                clauses.append(f"({compare_expr} >= {compare_value} AND {compare_expr} <= {compare_value})")
                params.extend([value, value2])
            elif op == "empty":
                clauses.append(f"({expr} IS NULL OR CAST({expr} AS TEXT)='')")
            elif op == "not_empty":
                clauses.append(f"({expr} IS NOT NULL AND CAST({expr} AS TEXT)!='')")

        if not clauses:
            return "", []
        glue = " OR " if rules["match"] == "any" else " AND "
        return "(" + glue.join(clauses) + ")", params

    def _user_group_where(self, rules, query=""):
        now = datetime.utcnow().isoformat()
        group_sql, params = self._user_group_condition_sql(rules, now)
        clauses = [group_sql] if group_sql else []
        if query and str(query).strip():
            cleaned_query = str(query).strip()
            if cleaned_query.startswith("@"):
                cleaned_query = cleaned_query[1:]
            like = "%" + cleaned_query + "%"
            clauses.append(self._GROUP_SEARCH_SQL)
            params.extend([like] * 13)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def ensure_user_groups_schema(self):
        with self._get_conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS user_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                rules_json TEXT NOT NULL DEFAULT '{\"match\":\"all\",\"conditions\":[]}',
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_groups_updated ON user_groups(updated_at DESC)")

    def list_user_groups(self):
        self.ensure_user_groups_schema()
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM user_groups ORDER BY updated_at DESC,id DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["rules"] = self._normalize_group_rules(json.loads(item.get("rules_json") or "{}"))
            except (TypeError, ValueError):
                item["rules"] = {"match": "all", "conditions": []}
            where, params = self._user_group_where(item["rules"])
            with self._get_conn() as conn:
                item["member_count"] = conn.execute(f"SELECT COUNT(*) c FROM users u {where}", params).fetchone()["c"]
            result.append(item)
        return result

    def get_user_group(self, group_id: int):
        self.ensure_user_groups_schema()
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM user_groups WHERE id=?", (int(group_id),)).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["rules"] = self._normalize_group_rules(json.loads(item.get("rules_json") or "{}"))
        except (TypeError, ValueError):
            item["rules"] = {"match": "all", "conditions": []}
        return item

    def create_user_group(self, name: str, description: str, rules: dict, created_by: int = None):
        self.ensure_user_groups_schema()
        name = (name or "").strip()
        if not name or len(name) > 80:
            raise ValueError("نام گروه باید بین ۱ تا ۸۰ کاراکتر باشد.")
        clean_rules = self._normalize_group_rules(rules)
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO user_groups(name,description,rules_json,created_by,created_at,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                (name, (description or "").strip()[:500], json.dumps(clean_rules, ensure_ascii=False), created_by),
            )
            return int(cur.lastrowid)

    def update_user_group(self, group_id: int, name: str, description: str, rules: dict):
        name = (name or "").strip()
        if not name or len(name) > 80:
            raise ValueError("نام گروه باید بین ۱ تا ۸۰ کاراکتر باشد.")
        clean_rules = self._normalize_group_rules(rules)
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE user_groups SET name=?,description=?,rules_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, (description or "").strip()[:500], json.dumps(clean_rules, ensure_ascii=False), int(group_id)),
            )
            return cur.rowcount > 0

    def delete_user_group(self, group_id: int):
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM user_groups WHERE id=?", (int(group_id),))
            return cur.rowcount > 0

    def search_user_group_members(self, group_id: int, query: str = "", limit: int = 25, offset: int = 0):
        group = self.get_user_group(group_id)
        if not group:
            return None, 0
        where, params = self._user_group_where(group["rules"], query)
        now = datetime.utcnow().isoformat()
        sql = (
            "SELECT u.*, "
            "(SELECT COUNT(*) FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved') AS purchase_count, "
            "(SELECT COALESCE(SUM(COALESCE(o.final_price,p.price)),0) FROM orders o JOIN products p ON p.id=o.product_id WHERE o.user_id=u.telegram_id AND o.status='approved') AS total_purchase, "
            "(SELECT MAX(o.created_at) FROM orders o WHERE o.user_id=u.telegram_id AND o.status='approved') AS last_purchase_at, "
            "(SELECT COALESCE(SUM(wt.amount),0) FROM wallet_topups wt WHERE wt.user_id=u.telegram_id AND wt.status='approved') AS topup_total, "
            "((SELECT COUNT(*) FROM custom_configs cc WHERE cc.user_id=u.telegram_id AND cc.source!='test' AND cc.status='active' AND (cc.expires_at IS NULL OR cc.expires_at>?)) + "
            "(SELECT COUNT(*) FROM configs c WHERE c.assigned_user_id=u.telegram_id AND c.is_used=1) + "
            "(SELECT COUNT(*) FROM ssh_accounts sa WHERE sa.user_id=u.telegram_id AND sa.status='active' AND (sa.expires_at IS NULL OR sa.expires_at>?))) AS active_services "
            f"FROM users u {where} ORDER BY u.id DESC LIMIT ? OFFSET ?"
        )
        with self._get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) c FROM users u {where}", params).fetchone()["c"]
            rows = conn.execute(sql, [now, now] + params + [max(1, min(int(limit), 100)), max(0, int(offset))]).fetchall()
        return rows, total

    def get_user_group_member_ids(self, group_id: int, limit: int = 1000):
        group = self.get_user_group(group_id)
        if not group:
            return None
        where, params = self._user_group_where(group["rules"])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT u.telegram_id FROM users u {where} ORDER BY u.id DESC LIMIT ?",
                params + [max(1, min(int(limit), 10000))],
            ).fetchall()
        return [int(r["telegram_id"]) for r in rows]

    def filter_user_group_member_ids(self, group_id: int, user_ids):
        ids = list(dict.fromkeys(int(x) for x in user_ids if int(x) > 0))
        if not ids:
            return []
        group = self.get_user_group(group_id)
        if not group:
            return None
        where, params = self._user_group_where(group["rules"])
        in_sql = ",".join("?" for _ in ids)
        condition = (where + " AND " if where else "WHERE ") + f"u.telegram_id IN ({in_sql})"
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT u.telegram_id FROM users u {condition}", params + ids
            ).fetchall()
        return [int(r["telegram_id"]) for r in rows]
