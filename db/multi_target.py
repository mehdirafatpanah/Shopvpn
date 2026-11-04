# -*- coding: utf-8 -*-
"""مقصدهای چندگانه‌ی محصول (چند پنل VPN و چند نود SSH) و لینک پنل‌های اضافه‌ی هر سرویس."""

import json


class MultiTargetMixin:
    def get_product_extra_targets(self, product_id: int) -> dict:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT kind,target_id,target_config FROM product_extra_targets WHERE product_id=? ORDER BY position,id",
                (int(product_id),),
            ).fetchall()
        panel_configs = {}
        for r in rows:
            if r["kind"] == "panel" and r["target_config"]:
                try:
                    panel_configs[int(r["target_id"])] = json.loads(r["target_config"])
                except (TypeError, ValueError):
                    continue
        return {
            "panels": [int(r["target_id"]) for r in rows if r["kind"] == "panel"],
            "ssh": [int(r["target_id"]) for r in rows if r["kind"] == "ssh"],
            "panel_target_configs": panel_configs,
        }

    def set_product_extra_targets(self, product_id: int, panel_ids=(), ssh_node_ids=(), panel_target_configs=None) -> None:
        pid = int(product_id)
        with self._get_conn() as conn:
            conn.execute("DELETE FROM product_extra_targets WHERE product_id=?", (pid,))
            position = 0
            for kind, ids in (("panel", panel_ids), ("ssh", ssh_node_ids)):
                seen = set()
                for raw in ids or ():
                    target = int(raw)
                    if target <= 0 or target in seen:
                        continue
                    seen.add(target)
                    target_config = None
                    if kind == "panel" and panel_target_configs:
                        target_config = panel_target_configs.get(target, panel_target_configs.get(str(target)))
                    conn.execute(
                        "INSERT INTO product_extra_targets (product_id,kind,target_id,position,target_config) VALUES (?,?,?,?,?)",
                        (pid, kind, target, position,
                         json.dumps(target_config, ensure_ascii=False) if target_config else None),
                    )
                    position += 1

    def clear_product_extra_targets(self, product_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM product_extra_targets WHERE product_id=?", (int(product_id),))

    def product_target_counts(self, product) -> dict:
        """تعداد پنل و نود واقعی یک محصول: هدف اصلی + هدف‌های اضافه."""
        def _val(key):
            try:
                return product[key]
            except (KeyError, IndexError, TypeError):
                return None
        extra = self.get_product_extra_targets(int(_val("id") or 0)) if _val("id") else {"panels": [], "ssh": []}
        panels = ([int(_val("provision_server_id"))] if _val("provision_server_id") else []) + extra["panels"]
        nodes = ([int(_val("provision_ssh_node_id"))] if _val("provision_ssh_node_id") else []) + extra["ssh"]
        return {"panels": list(dict.fromkeys(panels)), "ssh": list(dict.fromkeys(nodes))}

    def add_config_panel_link(self, custom_config_id: int, panel_server_id: int, username: str,
                              subscription_url: str, target_config=None) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO config_panel_links (custom_config_id,panel_server_id,username,subscription_url,target_config) "
                "VALUES (?,?,?,?,?)",
                (int(custom_config_id), int(panel_server_id), str(username), str(subscription_url or ""),
                 json.dumps(target_config, ensure_ascii=False) if target_config else None),
            )
            return int(cur.lastrowid)

    def panel_links_for_config(self, custom_config_id: int, active_only: bool = True) -> list:
        sql = ("SELECT l.id,l.custom_config_id,l.panel_server_id,l.username,l.subscription_url,l.target_config,l.status,"
               "s.name AS panel_name FROM config_panel_links l LEFT JOIN panel_servers s ON s.id=l.panel_server_id "
               "WHERE l.custom_config_id=?")
        if active_only:
            sql += " AND l.status='active'"
        with self._get_conn() as conn:
            rows = conn.execute(sql + " ORDER BY l.id", (int(custom_config_id),)).fetchall()
        return [dict(r) for r in rows]

    def panel_links_for_pool(self, pool_id: int) -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT l.id,l.custom_config_id,l.panel_server_id,l.username FROM quota_pool_members m "
                "JOIN config_panel_links l ON m.service_id='panel_link:'||l.id "
                "WHERE m.pool_id=? AND m.service_kind='vpn' AND l.status='active' ORDER BY l.id",
                (int(pool_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_config_panel_links(self, custom_config_id: int) -> list:
        """رکورد لینک‌ها و عضویتشان در استخر سهمیه را حذف می‌کند؛ لیست لینک‌های حذف‌شده را برمی‌گرداند."""
        links = self.panel_links_for_config(custom_config_id, active_only=False)
        with self._get_conn() as conn:
            for link in links:
                sid = f"panel_link:{int(link['id'])}"
                conn.execute("DELETE FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (sid,))
                conn.execute("DELETE FROM quota_enforcement_state WHERE service_kind='vpn' AND service_id=?", (sid,))
                conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?", (sid,))
                conn.execute("DELETE FROM config_panel_links WHERE id=?", (int(link["id"]),))
        return links

    def delete_config_panel_link(self, link_id: int) -> None:
        sid = f"panel_link:{int(link_id)}"
        with self._get_conn() as conn:
            conn.execute("DELETE FROM usage_snapshots WHERE service_kind='vpn' AND service_id=?", (sid,))
            conn.execute("DELETE FROM quota_enforcement_state WHERE service_kind='vpn' AND service_id=?", (sid,))
            conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?", (sid,))
            conn.execute("DELETE FROM config_panel_links WHERE id=?", (int(link_id),))

    def mark_config_panel_link_delete_pending(self, link_id: int) -> None:
        sid = f"panel_link:{int(link_id)}"
        with self._get_conn() as conn:
            conn.execute("UPDATE config_panel_links SET status='delete_pending' WHERE id=?", (int(link_id),))
            conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?", (sid,))

    def pending_delete_panel_links(self, limit: int = 200) -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id,custom_config_id,panel_server_id,username FROM config_panel_links "
                "WHERE status='delete_pending' ORDER BY id LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]
