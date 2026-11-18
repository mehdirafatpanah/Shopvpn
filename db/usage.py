# -*- coding: utf-8 -*-
"""زیرساخت مصرف یکپارچه برای سرویس‌های VPN و SSH.

مصرف در usage_snapshots به‌صورت شمارنده‌ی تجمعی (absolute bytes) ذخیره می‌شود؛
بنابراین اجرای مجدد poll یک پنل باعث دوباره‌شماری نمی‌شود. این لایه فقط آمار را
تجمیع می‌کند و عمداً بدون آداپتور معتبر، مصرف SSH را به API پنل VPN تزریق نمی‌کند.
"""
from datetime import datetime, timedelta, timezone
import json


def _normalize_timestamp(value: str) -> str:
    """Normalize ISO timestamps to UTC so lexical stale-checks are reliable."""
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        raise ValueError("زمان گزارش مصرف باید ISO-8601 معتبر باشد")


class UsageMixin:
    def create_quota_pool(self, user_id: int, limit_gb: float, expires_at: str = None,
                          label: str = "", metadata: dict = None) -> int:
        if int(user_id) <= 0 or float(limit_gb) < 0:
            raise ValueError("شناسه کاربر یا سقف حجم نامعتبر است")
        limit_bytes = int(float(limit_gb) * (1024 ** 3))
        if expires_at:
            expires_at = _normalize_timestamp(expires_at)
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO quota_pools (user_id,label,limit_bytes,expires_at,metadata_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (int(user_id), str(label or ""), limit_bytes, expires_at,
                 json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            return int(cur.lastrowid)

    # ------------------------------------------------------------------
    # شروع زمان از اولین اتصال برای استخرهای چندپنلی/نودی (VPN + SSH/OpenVPN/WireGuard)
    # ------------------------------------------------------------------
    @staticmethod
    def _pool_meta(raw) -> dict:
        try:
            meta = json.loads(raw or "{}")
            return meta if isinstance(meta, dict) else {}
        except (TypeError, ValueError):
            return {}

    def quota_pool_first_use_pending(self, pool) -> bool:
        """True اگر استخر «از اولین اتصال» است و هنوز هیچ اتصالی ثبت نشده (انقضا خالی)."""
        if not pool or pool.get("expires_at"):
            return False
        meta = self._pool_meta(pool.get("metadata_json"))
        return bool(meta.get("first_use_pending")) and float(meta.get("first_use_days") or 0) > 0

    def activate_quota_pool_first_use(self, pool_id: int, now: datetime = None):
        """با اولین مصرف، انقضای استخر را now+مدت می‌گذارد و همان را روی سرویس اصلی و
        حساب‌های SSH محلی هم ثبت می‌کند. اگر استخر در انتظار نباشد None برمی‌گرداند."""
        now = now or datetime.now(timezone.utc)
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM quota_pools WHERE id=?", (int(pool_id),)).fetchone()
            if not row:
                return None
            pool = dict(row)
            if not self.quota_pool_first_use_pending(pool):
                return None
            meta = self._pool_meta(pool.get("metadata_json"))
            expires_at = (now + timedelta(days=float(meta["first_use_days"]))).isoformat()
            meta["first_use_pending"] = False
            meta["activated_at"] = now.isoformat()
            conn.execute("UPDATE quota_pools SET expires_at=?, metadata_json=?, updated_at=? WHERE id=? AND expires_at IS NULL",
                         (expires_at, json.dumps(meta, ensure_ascii=False), now.isoformat(), int(pool_id)))
            conn.execute(
                "UPDATE custom_configs SET expires_at=? WHERE status='active' AND start_on_first_use=1 AND expires_at IS NULL "
                "AND ('custom_config:' || id) IN (SELECT service_id FROM quota_pool_members WHERE pool_id=? AND service_kind='vpn')",
                (expires_at, int(pool_id)))
            conn.execute("UPDATE ssh_accounts SET expires_at=?, updated_at=? WHERE quota_pool_id=? AND expires_at IS NULL",
                         (expires_at, now.isoformat(), int(pool_id)))
            return expires_at

    def add_quota_pool_first_use_days(self, pool_id: int, add_days: float) -> bool:
        """تمدید زمانیِ استخری که هنوز شروع نشده: روز جدید به مدت ذخیره‌شده اضافه می‌شود."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM quota_pools WHERE id=?", (int(pool_id),)).fetchone()
            if not row or not self.quota_pool_first_use_pending(dict(row)):
                return False
            meta = self._pool_meta(row["metadata_json"])
            meta["first_use_days"] = float(meta.get("first_use_days") or 0) + float(add_days)
            conn.execute("UPDATE quota_pools SET metadata_json=?, updated_at=? WHERE id=?",
                         (json.dumps(meta, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), int(pool_id)))
            return True

    def delete_quota_pool(self, pool_id: int) -> bool:
        """Delete a pool and its SSH records/snapshots; intended for provisioning rollback."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT id FROM quota_pools WHERE id=?", (int(pool_id),)).fetchone()
            if not row:
                return False
            members = conn.execute("SELECT service_kind,service_id FROM quota_pool_members WHERE pool_id=?", (int(pool_id),)).fetchall()
            adjustments = conn.execute("SELECT service_kind,service_id FROM quota_pool_adjustments WHERE pool_id=?", (int(pool_id),)).fetchall()
            for member in list(members) + list(adjustments):
                conn.execute("DELETE FROM usage_snapshots WHERE service_kind=? AND service_id=?",
                             (member["service_kind"], member["service_id"]))
            conn.execute("DELETE FROM ssh_accounts WHERE quota_pool_id=?", (int(pool_id),))
            conn.execute("DELETE FROM quota_pools WHERE id=?", (int(pool_id),))
            return True

    def get_quota_pool(self, pool_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM quota_pools WHERE id=?", (int(pool_id),)).fetchone()
            return dict(row) if row else None

    def attach_quota_service(self, pool_id: int, service_kind: str, service_id: str,
                             node_id: int = None) -> bool:
        """سرویس را به استخر متصل می‌کند؛ service_id باید در همان نوع یکتا باشد."""
        kind = str(service_kind or "").strip().lower()
        sid = str(service_id or "").strip()
        if kind not in {"vpn", "ssh"} or not sid:
            raise ValueError("نوع سرویس باید vpn یا ssh و شناسه سرویس الزامی است")
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            pool = conn.execute("SELECT id FROM quota_pools WHERE id=? AND status='active'", (int(pool_id),)).fetchone()
            if not pool:
                raise ValueError("استخر سهمیه فعال پیدا نشد")
            existing = conn.execute("SELECT pool_id FROM quota_pool_members WHERE service_kind=? AND service_id=?", (kind, sid)).fetchone()
            if existing:
                if int(existing["pool_id"]) != int(pool_id):
                    raise ValueError("این سرویس از قبل به استخر سهمیه دیگری متصل است؛ انتقال خودکار مجاز نیست")
                return True
            adjustment = conn.execute("SELECT pool_id FROM quota_pool_adjustments WHERE service_kind=? AND service_id=?", (kind, sid)).fetchone()
            if adjustment and int(adjustment["pool_id"]) != int(pool_id):
                raise ValueError("مصرف تاریخی این سرویس متعلق به استخر دیگری است")
            conn.execute("DELETE FROM quota_pool_adjustments WHERE pool_id=? AND service_kind=? AND service_id=?", (int(pool_id), kind, sid))
            conn.execute(
                "INSERT INTO quota_pool_members (pool_id,service_kind,service_id,node_id,created_at) VALUES (?,?,?,?,?)",
                (int(pool_id), kind, sid, node_id, now),
            )
            return True

    def attach_custom_config_to_quota_pool(self, pool_id: int, custom_config_id: int) -> bool:
        """سرویس VPN موجود را با شناسه پایدار custom_config:<id> به استخر وصل می‌کند."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT cc.id,cc.user_id,cc.panel_server_id FROM custom_configs cc WHERE cc.id=?",
                (int(custom_config_id),),
            ).fetchone()
            pool = conn.execute("SELECT user_id FROM quota_pools WHERE id=? AND status='active'", (int(pool_id),)).fetchone()
        if not row or not pool:
            raise ValueError("سرویس VPN یا استخر سهمیه پیدا نشد")
        if int(row["user_id"]) != int(pool["user_id"]):
            raise ValueError("سرویس و استخر سهمیه متعلق به یک کاربر نیستند")
        return self.attach_quota_service(pool_id, "vpn", f"custom_config:{int(custom_config_id)}",
                                         node_id=int(row["panel_server_id"]) if row["panel_server_id"] else None)

    def register_ssh_account(self, node_id: int, user_id: int, account_id: str, username: str,
                              host: str, port: int = 22, quota_pool_id: int = None,
                              expires_at: str = None, credential_enc: str = None,
                              protocol: str = "ssh") -> int:
        """ذخیره حساب SSH پس از موفقیت ساخت واقعی روی Provider."""
        if int(user_id) <= 0 or not str(account_id or "").strip() or not str(username or "").strip():
            raise ValueError("اطلاعات حساب SSH ناقص است")
        protocol = str(protocol or "ssh").strip().lower()
        if protocol not in {"ssh", "openvpn", "wireguard"}:
            raise ValueError("پروتکل حساب نامعتبر است")
        if expires_at:
            expires_at = _normalize_timestamp(expires_at)
        with self._get_conn() as conn:
            node = conn.execute("SELECT id,status FROM ssh_nodes WHERE id=?", (int(node_id),)).fetchone()
            if not node:
                raise ValueError("نود SSH پیدا نشد")
            if quota_pool_id is not None:
                pool = conn.execute("SELECT user_id,status FROM quota_pools WHERE id=?", (int(quota_pool_id),)).fetchone()
                if not pool or int(pool["user_id"]) != int(user_id) or pool["status"] != "active":
                    raise ValueError("استخر سهمیه متعلق به کاربر نیست یا فعال نیست")
            now = datetime.now(timezone.utc).isoformat()
            cur = conn.execute(
                "INSERT INTO ssh_accounts (node_id,user_id,quota_pool_id,account_id,username,host,port,status,expires_at,credential_enc,protocol,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,'active',?,?,?,?,?)",
                (int(node_id), int(user_id), int(quota_pool_id) if quota_pool_id is not None else None,
                 str(account_id).strip(), str(username).strip(), str(host).strip(), int(port), expires_at, credential_enc, protocol, now, now),
            )
            account_row_id = int(cur.lastrowid)
            if quota_pool_id is not None:
                existing = conn.execute("SELECT pool_id FROM quota_pool_members WHERE service_kind='ssh' AND service_id=?", (str(account_id),)).fetchone()
                if existing and int(existing["pool_id"]) != int(quota_pool_id):
                    raise ValueError("این حساب SSH از قبل به استخر دیگری متصل است")
                conn.execute("INSERT OR IGNORE INTO quota_pool_members (pool_id,service_kind,service_id,node_id,created_at) VALUES (?,'ssh',?,?,?)",
                             (int(quota_pool_id), str(account_id), int(node_id), now))
        return account_row_id

    def list_ssh_accounts(self, user_id: int = None, node_id: int = None) -> list:
        clauses, params = [], []
        if user_id is not None:
            clauses.append("a.user_id=?"); params.append(int(user_id))
        if node_id is not None:
            clauses.append("a.node_id=?"); params.append(int(node_id))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT a.id,a.node_id,a.user_id,a.quota_pool_id,a.account_id,a.username,a.host,a.port,a.protocol,a.status,a.expires_at,a.created_at,a.updated_at,n.name AS node_name,n.node_type FROM ssh_accounts a "
                "JOIN ssh_nodes n ON n.id=a.node_id" + where + " ORDER BY a.id DESC", params
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_ssh_account_record(self, account_row_id: int) -> bool:
        """Remove a local SSH record and its snapshot after a failed provisioning transaction."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT account_id,quota_pool_id FROM ssh_accounts WHERE id=?", (int(account_row_id),)).fetchone()
            if not row:
                return False
            account_id, pool_id = str(row["account_id"]), row["quota_pool_id"]
            conn.execute("DELETE FROM usage_snapshots WHERE service_kind='ssh' AND service_id=?", (account_id,))
            conn.execute("DELETE FROM quota_pool_members WHERE service_kind='ssh' AND service_id=?", (account_id,))
            if pool_id:
                conn.execute("DELETE FROM quota_enforcement_state WHERE pool_id=? AND service_kind='ssh' AND service_id=?",
                             (int(pool_id), account_id))
            conn.execute("DELETE FROM ssh_accounts WHERE id=?", (int(account_row_id),))
            return True

    def link_ssh_account_to_config(self, account_id: str, custom_config_id: int) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE ssh_accounts SET custom_config_id=? WHERE account_id=?",
                               (int(custom_config_id), str(account_id)))
            return bool(cur.rowcount)

    def ssh_accounts_for_config(self, custom_config_id: int, protocol: str = "ssh") -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT a.account_id,a.username,a.host,a.port,a.credential_enc,n.name AS node_name,n.config_json AS node_config_json FROM ssh_accounts a "
                "JOIN ssh_nodes n ON n.id=a.node_id WHERE a.custom_config_id=? AND a.status='active' AND a.protocol=? ORDER BY a.id",
                (int(custom_config_id), str(protocol))
            ).fetchall()
            return [dict(r) for r in rows]

    def get_ssh_account_credential(self, account_id: str, user_id: int = None):
        """Return encrypted credential only for the exact account owner when requested."""
        sql = "SELECT credential_enc FROM ssh_accounts WHERE account_id=?"
        params = [str(account_id)]
        if user_id is not None:
            sql += " AND user_id=?"
            params.append(int(user_id))
        with self._get_conn() as conn:
            row = conn.execute(sql, params).fetchone()
            return row["credential_enc"] if row else None

    def set_ssh_account_status_by_account_id(self, account_id: str, status: str) -> bool:
        if status not in {"pending", "active", "disabled", "expired", "error", "deleted"}:
            raise ValueError("وضعیت حساب SSH نامعتبر است")
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE ssh_accounts SET status=?,updated_at=? WHERE account_id=?",
                               (status, datetime.now(timezone.utc).isoformat(), str(account_id)))
            return bool(cur.rowcount)

    def set_ssh_account_status(self, account_row_id: int, status: str) -> bool:
        if status not in {"pending", "active", "disabled", "expired", "error", "deleted"}:
            raise ValueError("وضعیت حساب SSH نامعتبر است")
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE ssh_accounts SET status=?,updated_at=? WHERE id=?",
                               (status, now, int(account_row_id)))
            return bool(cur.rowcount)

    def record_usage_snapshot(self, service_kind: str, service_id: str, used_bytes: int,
                              uploaded_bytes: int = None, downloaded_bytes: int = None,
                              source: str = "unknown", reported_at: str = None,
                              event_id: str = None) -> bool:
        """ثبت شمارنده تجمعی. گزارش قدیمی‌تر جایگزین گزارش جدید نمی‌شود.

        event_id اختیاری است؛ برای Agentهایی که گزارش افزایشی ارسال می‌کنند باید
        اول در لایه آداپتور به شمارنده تجمعی تبدیل شود، یا event ledger جداگانه استفاده شود.
        """
        kind = str(service_kind or "").strip().lower()
        sid = str(service_id or "").strip()
        total = int(used_bytes)
        if kind not in {"vpn", "ssh"} or not sid or total < 0:
            raise ValueError("گزارش مصرف نامعتبر است")
        up = max(0, int(uploaded_bytes if uploaded_bytes is not None else 0))
        down = max(0, int(downloaded_bytes if downloaded_bytes is not None else 0))
        # total authoritative remains used_bytes; directional counters are optional diagnostics.
        stamp = _normalize_timestamp(reported_at)
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            current = conn.execute(
                "SELECT reported_at,used_bytes,source_used_bytes,counter_offset_bytes FROM usage_snapshots "
                "WHERE service_kind=? AND service_id=?", (kind, sid),
            ).fetchone()
            if current and current["reported_at"] and stamp < current["reported_at"]:
                return False
            offset = int(current["counter_offset_bytes"] or 0) if current else 0
            normalized_total = total
            if current:
                old_raw = int(current["source_used_bytes"] if current["source_used_bytes"] is not None else current["used_bytes"] or 0)
                old_total = int(current["used_bytes"] or 0)
                # A newer but lower source counter means the panel reset its usage counter.
                # Preserve the accumulated total by moving the prior total into the offset.
                if total < old_raw:
                    offset = old_total
                normalized_total = offset + total
            conn.execute(
                "INSERT INTO usage_snapshots (service_kind,service_id,used_bytes,source_used_bytes,counter_offset_bytes,"
                "uploaded_bytes,downloaded_bytes,source,reported_at,event_id,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(service_kind,service_id) DO UPDATE SET "
                "used_bytes=excluded.used_bytes,source_used_bytes=excluded.source_used_bytes,"
                "counter_offset_bytes=excluded.counter_offset_bytes,uploaded_bytes=excluded.uploaded_bytes,downloaded_bytes=excluded.downloaded_bytes,"
                "source=excluded.source,reported_at=excluded.reported_at,event_id=excluded.event_id,updated_at=excluded.updated_at",
                (kind, sid, normalized_total, total, offset, up, down, str(source or "unknown"), stamp, event_id, now),
            )
            return True

    def detach_quota_service(self, pool_id: int, service_kind: str, service_id: str) -> bool:
        """Detach a service while preserving its final cumulative usage in the pool."""
        kind, sid = str(service_kind or "").strip().lower(), str(service_id or "").strip()
        if kind not in {"vpn", "ssh"} or not sid:
            raise ValueError("نوع یا شناسه سرویس نامعتبر است")
        with self._get_conn() as conn:
            member = conn.execute("SELECT 1 FROM quota_pool_members WHERE pool_id=? AND service_kind=? AND service_id=?",
                                  (int(pool_id), kind, sid)).fetchone()
            if not member:
                return False
            snap = conn.execute("SELECT used_bytes FROM usage_snapshots WHERE service_kind=? AND service_id=?", (kind, sid)).fetchone()
            used = int(snap["used_bytes"] or 0) if snap else 0
            conn.execute("INSERT INTO quota_pool_adjustments(pool_id,service_kind,service_id,used_bytes,created_at) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(pool_id,service_kind,service_id) DO UPDATE SET used_bytes=excluded.used_bytes",
                         (int(pool_id), kind, sid, used, datetime.now(timezone.utc).isoformat()))
            conn.execute("DELETE FROM quota_pool_members WHERE pool_id=? AND service_kind=? AND service_id=?",
                         (int(pool_id), kind, sid))
            conn.execute("DELETE FROM quota_enforcement_state WHERE pool_id=? AND service_kind=? AND service_id=?",
                         (int(pool_id), kind, sid))
            return True

    def quota_pool_for_custom_config(self, custom_config_id: int):
        """Return the active quota pool linked to a VPN config, if any.

        Combined VPN+SSH products link the VPN service through the stable member ID
        ``custom_config:<id>``. The subscription UI uses this pool as the commercial
        source of truth instead of trusting a panel header that may say unlimited.
        """
        service_id = f"custom_config:{int(custom_config_id)}"
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT p.* FROM quota_pool_members m JOIN quota_pools p ON p.id=m.pool_id "
                "WHERE m.service_kind='vpn' AND m.service_id=? ORDER BY p.id DESC LIMIT 1",
                (service_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_quota_usage(self, pool_id: int) -> dict:
        """گزارش مصرف جمع‌شده از آخرین snapshot هر سرویس متصل به pool."""
        with self._get_conn() as conn:
            pool = conn.execute("SELECT * FROM quota_pools WHERE id=?", (int(pool_id),)).fetchone()
            if not pool:
                return None
            rows = conn.execute(
                "SELECT m.service_kind,m.service_id,m.node_id,COALESCE(s.used_bytes,0) used_bytes,"
                "s.uploaded_bytes,s.downloaded_bytes,s.source,s.reported_at "
                "FROM quota_pool_members m LEFT JOIN usage_snapshots s "
                "ON s.service_kind=m.service_kind AND s.service_id=m.service_id WHERE m.pool_id=?",
                (int(pool_id),),
            ).fetchall()
        used = sum(int(r["used_bytes"] or 0) for r in rows)
        with self._get_conn() as conn:
            adjustments = conn.execute("SELECT service_kind,service_id,used_bytes FROM quota_pool_adjustments WHERE pool_id=?", (int(pool_id),)).fetchall()
        used += sum(int(r["used_bytes"] or 0) for r in adjustments)
        limit = int(pool["limit_bytes"] or 0)
        # سقف صفر در این API به معنی نامحدود است.
        return {
            "pool_id": int(pool_id), "user_id": int(pool["user_id"]),
            "limit_bytes": limit, "used_bytes": used,
            "remaining_bytes": None if limit == 0 else max(0, limit - used),
            "unlimited": limit == 0, "exceeded": bool(limit and used >= limit),
            "status": pool["status"], "services": [dict(r) for r in rows],
            "detached_services": [dict(r) for r in adjustments],
        }

    def set_quota_pool_limit(self, pool_id: int, limit_gb: float, expires_at: str = None,
                             reset_usage: bool = False) -> bool:
        """تغییر سقف. مصرف به‌صورت پیش‌فرض حفظ می‌شود؛ reset_usage صرفاً snapshotها را صفر می‌کند."""
        if float(limit_gb) < 0:
            raise ValueError("سقف حجم نمی‌تواند منفی باشد")
        if expires_at:
            expires_at = _normalize_timestamp(expires_at)
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE quota_pools SET limit_bytes=?,expires_at=?,status='active',updated_at=? WHERE id=?",
                (int(float(limit_gb) * (1024 ** 3)), expires_at, now, int(pool_id)),
            )
            if not cur.rowcount:
                return False
            if reset_usage:
                conn.execute(
                    "UPDATE usage_snapshots SET used_bytes=0,source_used_bytes=0,counter_offset_bytes=0,uploaded_bytes=0,downloaded_bytes=0,updated_at=? "
                    "WHERE (service_kind,service_id) IN (SELECT service_kind,service_id FROM quota_pool_members WHERE pool_id=?)",
                    (now, int(pool_id)),
                )
            return True

    def create_ssh_node(self, name: str, node_type: str, host: str, port: int = 22,
                        auth_type: str = "ssh_key", username: str = "root",
                        panel_type: str = None, panel_url: str = None,
                        secret_ref: str = None, config_json: dict = None) -> int:
        """ثبت metadata نود؛ secret_ref باید به secret manager/env اشاره کند، نه خود رمز خصوصی."""
        typ = str(node_type or "").lower()
        auth = str(auth_type or "").lower()
        if typ not in {"linux", "ssh_panel"}:
            raise ValueError("نوع نود باید linux یا ssh_panel باشد")
        if not str(name or "").strip() or not str(host or "").strip():
            raise ValueError("نام و آدرس نود الزامی است")
        if not 1 <= int(port) <= 65535:
            raise ValueError("پورت نامعتبر است")
        if auth not in {"ssh_key", "password", "api_token", "api_password"}:
            raise ValueError("روش احراز هویت پشتیبانی نمی‌شود")
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO ssh_nodes (name,node_type,host,port,auth_type,username,panel_type,panel_url,secret_ref,config_json,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?)",
                (name.strip(), typ, host.strip(), int(port), auth, username.strip() or "root",
                 panel_type, panel_url, secret_ref, json.dumps(config_json or {}, ensure_ascii=False), now, now),
            )
            return int(cur.lastrowid)

    def list_ssh_nodes(self, active_only: bool = False) -> list:
        with self._get_conn() as conn:
            sql = "SELECT * FROM ssh_nodes" + (" WHERE status='active'" if active_only else "") + " ORDER BY id DESC"
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def get_ssh_node(self, node_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM ssh_nodes WHERE id=?", (int(node_id),)).fetchone()
            return dict(row) if row else None

    def replace_ssh_node_config_keys(self, node_id: int, updates: dict, remove: tuple = ()) -> bool:
        """مثل merge_ssh_node_config ولی کلیدهای remove هم از config_json پاک می‌شوند."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT config_json FROM ssh_nodes WHERE id=?", (int(node_id),)).fetchone()
            if not row:
                return False
            try:
                config = json.loads(row["config_json"] or "{}")
            except (TypeError, ValueError):
                config = {}
            for key in remove:
                config.pop(key, None)
            config.update(updates or {})
            cur = conn.execute("UPDATE ssh_nodes SET config_json=?,updated_at=? WHERE id=?",
                               (json.dumps(config, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), int(node_id)))
            return bool(cur.rowcount)

    def update_ssh_node_name(self, node_id: int, name: str) -> bool:
        name = str(name or "").strip()
        if not name or len(name) > 80:
            raise ValueError("نام نود باید بین ۱ تا ۸۰ کاراکتر باشد")
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE ssh_nodes SET name=?,updated_at=? WHERE id=?",
                               (name, datetime.now(timezone.utc).isoformat(), int(node_id)))
            return cur.rowcount > 0

    def delete_ssh_node(self, node_id: int) -> bool:
        """حذف نود؛ فقط وقتی هیچ حساب غیرحذف‌شده‌ای روی آن نیست و هیچ محصولی به آن وصل نیست."""
        with self._get_conn() as conn:
            if conn.execute("SELECT 1 FROM ssh_accounts WHERE node_id=? AND status!='deleted' LIMIT 1", (int(node_id),)).fetchone():
                raise ValueError("روی این نود هنوز حساب SSH فعال وجود دارد.")
            if conn.execute("SELECT 1 FROM products WHERE provision_ssh_node_id=? LIMIT 1", (int(node_id),)).fetchone():
                raise ValueError("یک محصول به این نود وصل است؛ ابتدا محصول را تغییر دهید.")
            conn.execute("DELETE FROM ssh_accounts WHERE node_id=?", (int(node_id),))
            cur = conn.execute("DELETE FROM ssh_nodes WHERE id=?", (int(node_id),))
            return cur.rowcount > 0

    def merge_ssh_node_config(self, node_id: int, updates: dict) -> bool:
        """به‌روزرسانی بخشی از config_json نود بدون پاک شدن کلیدهای دیگر."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT config_json FROM ssh_nodes WHERE id=?", (int(node_id),)).fetchone()
            if not row:
                return False
            try:
                config = json.loads(row["config_json"] or "{}")
            except (TypeError, ValueError):
                config = {}
            config.update(updates or {})
            cur = conn.execute("UPDATE ssh_nodes SET config_json=?,updated_at=? WHERE id=?",
                               (json.dumps(config, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), int(node_id)))
            return bool(cur.rowcount)

    def update_ssh_node_status(self, node_id: int, status: str, last_error: str = None) -> bool:
        if status not in {"pending", "active", "degraded", "disabled", "error"}:
            raise ValueError("وضعیت نود نامعتبر است")
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE ssh_nodes SET status=?,last_error=?,updated_at=? WHERE id=?",
                               (status, (last_error or "")[:500] or None, now, int(node_id)))
            return bool(cur.rowcount)


    def list_quota_pools(self, active_only: bool = True) -> list:
        with self._get_conn() as conn:
            sql = "SELECT * FROM quota_pools" + (" WHERE status IN ('active','stale','exceeded')" if active_only else "") + " ORDER BY id"
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def get_quota_members(self, pool_id: int) -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT m.pool_id,m.service_kind,m.service_id,m.node_id,s.used_bytes,s.uploaded_bytes,"
                "s.downloaded_bytes,s.source,s.reported_at,s.updated_at AS snapshot_updated_at "
                "FROM quota_pool_members m LEFT JOIN usage_snapshots s "
                "ON s.service_kind=m.service_kind AND s.service_id=m.service_id WHERE m.pool_id=? ORDER BY m.id",
                (int(pool_id),),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_quota_pool_status(self, pool_id: int, status: str) -> bool:
        if status not in {"active", "stale", "exceeded", "expired", "error"}:
            raise ValueError("وضعیت استخر سهمیه نامعتبر است")
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE quota_pools SET status=?,updated_at=? WHERE id=?",
                               (status, datetime.now(timezone.utc).isoformat(), int(pool_id)))
            return bool(cur.rowcount)

    def get_quota_enforcement_state(self, pool_id: int, service_kind: str, service_id: str):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM quota_enforcement_state WHERE pool_id=? AND service_kind=? AND service_id=?",
                (int(pool_id), str(service_kind), str(service_id)),
            ).fetchone()
            return dict(row) if row else None

    def set_quota_enforcement_state(self, pool_id: int, service_kind: str, service_id: str,
                                    is_disabled: bool, reason: str = None, last_error: str = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO quota_enforcement_state(pool_id,service_kind,service_id,is_disabled,reason,last_error,updated_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(pool_id,service_kind,service_id) DO UPDATE SET "
                "is_disabled=excluded.is_disabled,reason=excluded.reason,last_error=excluded.last_error,updated_at=excluded.updated_at",
                (int(pool_id), str(service_kind), str(service_id), int(bool(is_disabled)), reason,
                 (str(last_error)[:500] if last_error else None), now),
            )
