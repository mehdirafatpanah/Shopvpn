# -*- coding: utf-8 -*-
"""لایه‌ی دیتابیس «ساب اختصاصی»: توکن هر سرویس، لاگ دسترسی و تاریخچه‌ی مصرف.

توکن لینک اختصاصی (``custom_configs.sub_token``) تنها چیزی است که در URL عمومی
می‌آید؛ آدرس واقعی پنل (``subscription_url``) هرگز بیرون نمی‌رود.
"""

import json
import secrets
import time
from urllib.parse import urlparse


class DedicatedSubMixin:
    # ----- توکن ---------------------------------------------------------------
    def ds_get_or_create_token(self, config_id: int):
        """توکن لینک اختصاصیِ یک سرویس را برمی‌گرداند (اگر نبود می‌سازد)."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT sub_token FROM custom_configs WHERE id=?", (config_id,)).fetchone()
            if row is None:
                return None
            if row["sub_token"]:
                return row["sub_token"]
            for _ in range(5):
                token = secrets.token_urlsafe(18)
                try:
                    conn.execute("UPDATE custom_configs SET sub_token=? WHERE id=?", (token, config_id))
                    return token
                except Exception:  # برخورد بسیار نادر روی ایندکس یکتا
                    continue
        return None

    def ds_regenerate_token(self, config_id: int):
        """توکن قبلی را باطل و توکن تازه می‌سازد (مثلاً بعد از لو رفتن لینک)."""
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_configs SET sub_token=NULL WHERE id=?", (config_id,))
        return self.ds_get_or_create_token(config_id)

    def ds_get_config_by_token(self, token: str):
        if not token or len(token) > 80:
            return None
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM custom_configs WHERE sub_token=?", (token,)).fetchone()

    def ds_get_config(self, config_id: int):
        with self._get_conn() as conn:
            return conn.execute("SELECT * FROM custom_configs WHERE id=?", (config_id,)).fetchone()

    def ds_find_config_by_sub_url(self, url: str):
        """جدیدترین سرویسی که subscription_url آن همین لینک است."""
        if not url:
            return None
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM custom_configs WHERE subscription_url=? ORDER BY id DESC LIMIT 1", (url,)
            ).fetchone()

    def ds_panel_name(self, panel_server_id):
        if not panel_server_id:
            return ""
        with self._get_conn() as conn:
            row = conn.execute("SELECT name FROM panel_servers WHERE id=?", (panel_server_id,)).fetchone()
        return row["name"] if row else ""

    # ----- لاگ دسترسی ---------------------------------------------------------
    def ds_log_access(self, config_id, ip: str, ua: str, kind: str, status: int):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO sub_access_log (config_id, ts, ip, ua, kind, status) VALUES (?,?,?,?,?,?)",
                (config_id, int(time.time()), (ip or "")[:64], (ua or "")[:200], kind, int(status)),
            )

    def ds_access_stats(self, since_ts: int) -> dict:
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM sub_access_log WHERE ts>=?", (since_ts,)).fetchone()["c"]
            pages = conn.execute(
                "SELECT COUNT(*) c FROM sub_access_log WHERE ts>=? AND kind='page'", (since_ts,)
            ).fetchone()["c"]
            services = conn.execute(
                "SELECT COUNT(DISTINCT config_id) c FROM sub_access_log WHERE ts>=? AND config_id IS NOT NULL",
                (since_ts,),
            ).fetchone()["c"]
            ips = conn.execute(
                "SELECT COUNT(DISTINCT ip) c FROM sub_access_log WHERE ts>=?", (since_ts,)
            ).fetchone()["c"]
            errors = conn.execute(
                "SELECT COUNT(*) c FROM sub_access_log WHERE ts>=? AND status>=400", (since_ts,)
            ).fetchone()["c"]
            uas = conn.execute(
                "SELECT ua FROM sub_access_log WHERE ts>=? AND kind!='page' ORDER BY id DESC LIMIT 2000",
                (since_ts,),
            ).fetchall()
            recent = conn.execute(
                "SELECT l.ts, l.kind, l.status, l.ip, c.username FROM sub_access_log l "
                "LEFT JOIN custom_configs c ON c.id=l.config_id ORDER BY l.id DESC LIMIT 8"
            ).fetchall()
        return {
            "total": total, "pages": pages, "services": services, "ips": ips, "errors": errors,
            "uas": [r["ua"] for r in uas], "recent": [dict(r) for r in recent],
        }

    def ds_config_ips(self, config_id: int, since_ts: int) -> int:
        """تعداد IPهای یکتا که در بازه‌ی داده‌شده ساب این سرویس را گرفته‌اند."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(DISTINCT ip) c FROM sub_access_log WHERE config_id=? AND ts>=? AND kind='sub'",
                (config_id, since_ts),
            ).fetchone()["c"]

    def ds_recent_config_ids(self, since_ts: int, limit: int = 500):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT config_id FROM sub_access_log WHERE ts>=? AND config_id IS NOT NULL "
                "ORDER BY config_id DESC LIMIT ?", (since_ts, limit),
            ).fetchall()
        return [r["config_id"] for r in rows]

    def ds_prune(self, access_days: int = 30, usage_days: int = 45):
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute("DELETE FROM sub_access_log WHERE ts<?", (now - access_days * 86400,))
            conn.execute("DELETE FROM sub_usage_log WHERE ts<?", (now - usage_days * 86400,))

    # ----- تاریخچه‌ی مصرف (برای نمودار صفحه‌ی وب) ------------------------------
    def ds_record_usage(self, config_id: int, used_bytes: int, min_gap: int = 1200) -> bool:
        now = int(time.time())
        with self._get_conn() as conn:
            last = conn.execute(
                "SELECT ts, used FROM sub_usage_log WHERE config_id=? ORDER BY ts DESC LIMIT 1", (config_id,)
            ).fetchone()
            if last and now - last["ts"] < min_gap:
                return False
            conn.execute(
                "INSERT INTO sub_usage_log (config_id, ts, used) VALUES (?,?,?)",
                (config_id, now, int(used_bytes)),
            )
        return True

    def ds_usage_points(self, config_id: int, since_ts: int):
        """نقاط (ts, used) از «آخرین نمونه‌ی پیش از since_ts» تا امروز، به ترتیب زمان."""
        with self._get_conn() as conn:
            before = conn.execute(
                "SELECT ts, used FROM sub_usage_log WHERE config_id=? AND ts<? ORDER BY ts DESC LIMIT 1",
                (config_id, since_ts),
            ).fetchone()
            rows = conn.execute(
                "SELECT ts, used FROM sub_usage_log WHERE config_id=? AND ts>=? ORDER BY ts ASC",
                (config_id, since_ts),
            ).fetchall()
        pts = [(r["ts"], r["used"]) for r in rows]
        if before:
            pts.insert(0, (before["ts"], before["used"]))
        return pts

    # ----- جستجوی کانفیگ (ادمین) ----------------------------------------------
    @staticmethod
    def _like_escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _search_tokens(query: str):
        """از ورودی ادمین (لینک ساب پنل، لینک اختصاصی، توکن یا نام) کلیدهای جستجو را درمی‌آورد."""
        q = (query or "").strip().strip("<>\"'")
        token = None
        segment = None
        if "/s/" in q:
            token = q.split("/s/", 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
        if q.lower().startswith(("http://", "https://")):
            path = q.split("?", 1)[0].split("#", 1)[0].rstrip("/")
            segment = path.rsplit("/", 1)[-1]
        elif " " not in q and len(q) >= 8:
            segment = q
        if segment is not None and len(segment) < 8:
            segment = None
        return q, token, segment

    def search_custom_configs(self, query: str, limit: int = 10) -> list:
        """جستجوی سرویس‌های پنلی با: آیدی عددی کانفیگ، لینک ساب پنل، لینک/توکن ساب اختصاصی،
        یوزرنیم روی پنل یا نام نمایشی. خروجی: لیست ردیف‌ها (جدیدترین اول) بدون تکرار."""
        q, token, segment = self._search_tokens(query)
        if not q:
            return []
        conds, params = [], []
        if q.isdigit() and len(q) <= 12:
            conds.append("c.id=?")
            params.append(int(q))
        conds.append("c.subscription_url=?")
        params.append(q)
        if token:
            conds.append("c.sub_token=?")
            params.append(token)
        elif " " not in q and len(q) >= 10:
            conds.append("c.sub_token=?")
            params.append(q)
        if segment:
            conds.append("c.subscription_url LIKE ? ESCAPE '\\'")
            params.append(f"%{self._like_escape(segment)}%")
        conds.append("c.username=? COLLATE NOCASE")
        params.append(q)
        conds.append("c.display_name=? COLLATE NOCASE")
        params.append(q)
        if len(q) >= 3 and " " not in q and not q.lower().startswith(("http://", "https://")):
            like = f"%{self._like_escape(q)}%"
            conds.append("c.username LIKE ? ESCAPE '\\'")
            params.append(like)
            conds.append("c.display_name LIKE ? ESCAPE '\\'")
            params.append(like)
        sql = (
            "SELECT c.*, p.name AS panel_name FROM custom_configs c "
            "LEFT JOIN panel_servers p ON p.id=c.panel_server_id "
            f"WHERE {' OR '.join(conds)} ORDER BY c.id DESC LIMIT ?"
        )
        params.append(int(limit))
        with self._get_conn() as conn:
            return conn.execute(sql, params).fetchall()

    def search_bank_configs(self, query: str, limit: int = 10) -> list:
        """جستجوی کانفیگ‌های بانک محصول (جدول configs) با بخشی از لینک/کانفیگ."""
        q = (query or "").strip().strip("<>\"'")
        if len(q) < 8 or " " in q:
            return []
        like = f"%{self._like_escape(q)}%"
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT cf.*, p.name AS product_name FROM configs cf "
                "LEFT JOIN products p ON p.id=cf.product_id "
                "WHERE cf.link LIKE ? ESCAPE '\\' ORDER BY cf.id DESC LIMIT ?",
                (like, int(limit)),
            ).fetchall()

    # ----- پروفایل‌های ساب اختصاصی (چند دامنه) -------------------------------
    @staticmethod
    def _dsp_row(row):
        if row is None:
            return None
        try:
            settings = json.loads(row["settings"] or "{}")
            if not isinstance(settings, dict):
                settings = {}
        except (ValueError, TypeError):
            settings = {}
        return {"id": int(row["id"]), "name": row["name"] or "", "base_url": (row["base_url"] or "").rstrip("/"),
                "enabled": int(row["enabled"] or 0) == 1, "settings": settings,
                "ssl_status": row["ssl_status"] or ""}

    def dsp_list(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM dsub_profiles ORDER BY id").fetchall()
        return [self._dsp_row(r) for r in rows]

    def dsp_get(self, profile_id):
        try:
            pid = int(profile_id)
        except (TypeError, ValueError):
            return None
        with self._get_conn() as conn:
            return self._dsp_row(conn.execute("SELECT * FROM dsub_profiles WHERE id=?", (pid,)).fetchone())

    def dsp_get_by_host(self, host: str):
        """پروفایلی که دامنه‌اش با هدر Host برابر است (بدون پورت و بدون حساسیت به حروف)."""
        host = (host or "").split(":", 1)[0].strip().lower()
        if not host:
            return None
        for prof in self.dsp_list():
            if (urlparse(prof["base_url"]).hostname or "").lower() == host:
                return prof
        return None

    def dsp_create(self, name: str, base_url: str, enabled: bool = True) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("INSERT INTO dsub_profiles (name, base_url, enabled) VALUES (?,?,?)",
                               (name, (base_url or "").rstrip("/"), 1 if enabled else 0))
            return cur.lastrowid

    def dsp_update(self, profile_id: int, **fields):
        allowed = {"name", "base_url", "enabled", "ssl_status"}
        sets, values = [], []
        for k, v in fields.items():
            if k in allowed and v is not None:
                sets.append(f"{k}=?")
                values.append((v or "").rstrip("/") if k == "base_url" else (1 if v is True else 0 if v is False else v))
        if not sets:
            return
        values.append(int(profile_id))
        with self._get_conn() as conn:
            conn.execute(f"UPDATE dsub_profiles SET {', '.join(sets)} WHERE id=?", values)

    def dsp_set_settings(self, profile_id: int, settings: dict):
        with self._get_conn() as conn:
            conn.execute("UPDATE dsub_profiles SET settings=? WHERE id=?",
                         (json.dumps(settings or {}, ensure_ascii=False), int(profile_id)))

    def dsp_delete(self, profile_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE panel_servers SET dsub_profile_id=NULL WHERE dsub_profile_id=?", (int(profile_id),))
            conn.execute("DELETE FROM dsub_profiles WHERE id=?", (int(profile_id),))

    def dsp_panel_ids(self, profile_id: int):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT id FROM panel_servers WHERE dsub_profile_id=?", (int(profile_id),)).fetchall()
        return [int(r["id"]) for r in rows]

    def dsp_set_panels(self, profile_id: int, panel_ids):
        """پنل‌های این پروفایل را دقیقاً برابر لیست می‌گذارد (پنل‌های دیگرِ همین پروفایل آزاد می‌شوند)."""
        ids = [int(x) for x in dict.fromkeys(panel_ids or [])]
        with self._get_conn() as conn:
            conn.execute("UPDATE panel_servers SET dsub_profile_id=NULL WHERE dsub_profile_id=?", (int(profile_id),))
            for sid in ids:
                conn.execute("UPDATE panel_servers SET dsub_profile_id=? WHERE id=?", (int(profile_id), sid))

    def dsp_for_panel(self, server_id):
        try:
            sid = int(server_id)
        except (TypeError, ValueError):
            return None
        with self._get_conn() as conn:
            row = conn.execute("SELECT dsub_profile_id FROM panel_servers WHERE id=?", (sid,)).fetchone()
        if not row or not row["dsub_profile_id"]:
            return None
        return self.dsp_get(row["dsub_profile_id"])
