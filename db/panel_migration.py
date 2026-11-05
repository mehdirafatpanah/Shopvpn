# -*- coding: utf-8 -*-
"""لایه‌ی دیتابیس «مهاجرت بین پنل‌ها».

جدول‌ها فقط برای ثبت تاریخچه‌ی مهاجرت‌ها هستند؛ منبع حقیقت همیشه خودِ ردیف سرویس است
(custom_configs / config_panel_links). بعد از جابه‌جایی هر سرویس، ستون panel_server_id آن
به پنل مقصد تغییر می‌کند؛ پس اجرای دوباره‌ی مهاجرت فقط سرویس‌های باقی‌مانده را برمی‌دارد.
"""

import json
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PanelMigrationMixin:
    # ----- جدول‌های تاریخچه ---------------------------------------------------
    def pm_ensure_tables(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS panel_migrations ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "source_panel_id INTEGER NOT NULL,"
                "dest_panel_id INTEGER NOT NULL,"
                "admin_id INTEGER,"
                "options_json TEXT,"
                "status TEXT NOT NULL DEFAULT 'running',"
                "total INTEGER NOT NULL DEFAULT 0,"
                "migrated INTEGER NOT NULL DEFAULT 0,"
                "failed INTEGER NOT NULL DEFAULT 0,"
                "skipped INTEGER NOT NULL DEFAULT 0,"
                "notified INTEGER NOT NULL DEFAULT 0,"
                "note TEXT,"
                "created_at TEXT NOT NULL,"
                "finished_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS panel_migration_items ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "migration_id INTEGER NOT NULL,"
                "kind TEXT NOT NULL,"
                "ref_id INTEGER NOT NULL,"
                "user_id INTEGER,"
                "old_username TEXT,"
                "new_username TEXT,"
                "old_url TEXT,"
                "new_url TEXT,"
                "status TEXT NOT NULL,"
                "estimated INTEGER NOT NULL DEFAULT 0,"
                "remaining_bytes INTEGER,"
                "error TEXT,"
                "created_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pm_items_mig ON panel_migration_items(migration_id)"
            )

    def pm_create_run(self, source_id: int, dest_id: int, admin_id, options: dict, total: int) -> int:
        self.pm_ensure_tables()
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO panel_migrations (source_panel_id,dest_panel_id,admin_id,options_json,total,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (int(source_id), int(dest_id), admin_id, json.dumps(options or {}, ensure_ascii=False),
                 int(total), _now()),
            )
            return int(cur.lastrowid)

    def pm_update_run(self, run_id: int, **fields) -> None:
        allowed = {"status", "migrated", "failed", "skipped", "notified", "note", "total"}
        sets, vals = [], []
        for key, value in fields.items():
            if key in allowed:
                sets.append(f"{key}=?")
                vals.append(value)
        if fields.get("status") in ("done", "aborted", "error"):
            sets.append("finished_at=?")
            vals.append(_now())
        if not sets:
            return
        with self._get_conn() as conn:
            conn.execute(f"UPDATE panel_migrations SET {', '.join(sets)} WHERE id=?", (*vals, int(run_id)))

    def pm_add_item(self, run_id: int, kind: str, ref_id: int, status: str, *, user_id=None, old_username=None,
                    new_username=None, old_url=None, new_url=None, estimated=False, remaining_bytes=None,
                    error=None) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO panel_migration_items (migration_id,kind,ref_id,user_id,old_username,new_username,"
                "old_url,new_url,status,estimated,remaining_bytes,error,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(run_id), kind, int(ref_id), user_id, old_username, new_username, old_url, new_url, status,
                 int(bool(estimated)), remaining_bytes, (str(error)[:500] if error else None), _now()),
            )

    def pm_recent_runs(self, limit: int = 5) -> list:
        self.pm_ensure_tables()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT m.*, s.name AS source_name, d.name AS dest_name FROM panel_migrations m "
                "LEFT JOIN panel_servers s ON s.id=m.source_panel_id "
                "LEFT JOIN panel_servers d ON d.id=m.dest_panel_id ORDER BY m.id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def pm_run_failures(self, run_id: int, limit: int = 20) -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT kind,ref_id,user_id,old_username,error FROM panel_migration_items "
                "WHERE migration_id=? AND status='failed' ORDER BY id LIMIT ?",
                (int(run_id), int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----- فهرست سرویس‌های قابل مهاجرت ----------------------------------------
    def pm_list_primary(self, source_id: int) -> list:
        """سرویس‌های فعالی که پنل اصلی‌شان همین پنل است."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_configs WHERE panel_server_id=? AND status='active' "
                "AND cleanup_deleted_at IS NULL ORDER BY id",
                (int(source_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def pm_list_links(self, source_id: int) -> list:
        """کاربران پنل‌های اضافه (چندپنلی) که روی این پنل هستند."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT l.*, cc.user_id AS user_id, cc.display_name AS display_name, "
                "cc.expires_at AS cc_expires_at, cc.duration_days AS cc_duration_days, "
                "cc.start_on_first_use AS cc_start_on_first_use FROM config_panel_links l "
                "JOIN custom_configs cc ON cc.id=l.custom_config_id "
                "WHERE l.panel_server_id=? AND l.status='active' AND cc.status='active' "
                "AND cc.cleanup_deleted_at IS NULL ORDER BY l.id",
                (int(source_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def pm_pool_for(self, service_id: str):
        """استخر سهمیه‌ی مشترکِ یک سرویس VPN (custom_config:<id> یا panel_link:<id>) یا None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT p.id AS pool_id, p.limit_bytes AS limit_bytes, p.expires_at AS expires_at "
                "FROM quota_pool_members m JOIN quota_pools p ON p.id=m.pool_id "
                "WHERE m.service_kind='vpn' AND m.service_id=? AND p.status='active'",
                (str(service_id),),
            ).fetchone()
        return dict(row) if row else None

    # ----- جابه‌جایی رکورد سرویس ----------------------------------------------
    def pm_rebase_snapshot(self, conn, service_id: str) -> None:
        """شمارنده‌ی پنل مقصد از صفر شروع می‌شود؛ مصرف تجمعی قبلی را در offset نگه می‌داریم
        تا استخر سهمیه (VPN+SSH / چندپنلی) مصرف قبلی کاربر را از دست ندهد."""
        conn.execute(
            "UPDATE usage_snapshots SET counter_offset_bytes=used_bytes, source_used_bytes=0 "
            "WHERE service_kind='vpn' AND service_id=?",
            (str(service_id),),
        )

    def pm_switch_primary(self, cc_id: int, dest_id: int, username: str, subscription_url: str,
                          history_detail: str = "") -> None:
        sid = f"custom_config:{int(cc_id)}"
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE custom_configs SET panel_server_id=?, username=?, subscription_url=?, "
                "panel_target_config=NULL WHERE id=?",
                (int(dest_id), username, subscription_url or "", int(cc_id)),
            )
            self.pm_rebase_snapshot(conn, sid)
            conn.execute("DELETE FROM credential_index WHERE config_id=?", (int(cc_id),))
            conn.execute(
                "INSERT INTO custom_config_history (custom_config_id, event_type, detail) VALUES (?,?,?)",
                (int(cc_id), "panel_migration", history_detail or None),
            )

    def pm_switch_link(self, link_id: int, cc_id: int, dest_id: int, username: str, subscription_url: str,
                       history_detail: str = "") -> None:
        sid = f"panel_link:{int(link_id)}"
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE config_panel_links SET panel_server_id=?, username=?, subscription_url=?, "
                "target_config=NULL WHERE id=?",
                (int(dest_id), username, subscription_url or "", int(link_id)),
            )
            self.pm_rebase_snapshot(conn, sid)
            conn.execute(
                "INSERT INTO custom_config_history (custom_config_id, event_type, detail) VALUES (?,?,?)",
                (int(cc_id), "panel_migration", history_detail or None),
            )

    # ----- انتقال فروش (محصولات جدید هم روی پنل مقصد ساخته شوند) ----------------
    def pm_retarget_sales(self, source_id: int, dest_id: int) -> dict:
        src, dst = int(source_id), int(dest_id)
        out = {"products": 0, "extra_targets": 0, "custom_products": 0, "test_plans": 0, "wheel_prizes": 0}
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE products SET provision_server_id=?, provision_target_config=NULL "
                "WHERE provision_server_id=?", (dst, src))
            out["products"] = cur.rowcount or 0
            # پنل‌های اضافه‌ی محصول: اگر مقصد قبلاً در همان محصول هست، ردیف قدیمی فقط حذف می‌شود.
            rows = conn.execute(
                "SELECT e.id, e.product_id FROM product_extra_targets e "
                "WHERE e.kind='panel' AND e.target_id=?", (src,)).fetchall()
            for r in rows:
                dup = conn.execute(
                    "SELECT 1 FROM product_extra_targets WHERE product_id=? AND kind='panel' AND target_id=?",
                    (r["product_id"], dst)).fetchone()
                prim = conn.execute(
                    "SELECT 1 FROM products WHERE id=? AND provision_server_id=?", (r["product_id"], dst)).fetchone()
                if dup or prim:
                    conn.execute("DELETE FROM product_extra_targets WHERE id=?", (r["id"],))
                else:
                    conn.execute(
                        "UPDATE product_extra_targets SET target_id=?, target_config=NULL WHERE id=?",
                        (dst, r["id"]))
                out["extra_targets"] += 1
            # محصولی که حالا پنل اصلی‌اش مقصد است و مقصد را در اضافه‌ها هم دارد.
            conn.execute(
                "DELETE FROM product_extra_targets WHERE kind='panel' AND target_id=? AND product_id IN "
                "(SELECT id FROM products WHERE provision_server_id=?)", (dst, dst))
            for table, key in (("custom_config_products", "custom_products"),
                               ("test_config_plans", "test_plans"),
                               ("wheel_prizes", "wheel_prizes")):
                try:
                    cur = conn.execute(f"UPDATE {table} SET panel_server_id=? WHERE panel_server_id=?", (dst, src))
                    out[key] = cur.rowcount or 0
                except Exception:
                    out[key] = 0
        return out
