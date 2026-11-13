# -*- coding: utf-8 -*-
"""لایه‌ی دیتابیس «کلیدهای سفارشی منوی شیشه‌ای».

هر کلید دو حالت دارد:
  * ``url``     : با کلیک، لینک باز می‌شود (دکمه‌ی inline از نوع url).
  * ``content`` : با کلیک، یک یا چند پیام (متن/عکس/ویدیو/ویس/استیکر/...) برای کاربر ارسال می‌شود.
محتوای پیام‌ها به‌صورت لیست JSON در ستون ``parts`` ذخیره می‌شود.
"""

import json

MAX_TITLE_LEN = 40
MAX_PARTS = 10
MAX_BUTTONS = 30


class CustomMenuMixin:
    @staticmethod
    def _cm_row(row):
        if row is None:
            return None
        d = dict(row)
        try:
            d["parts"] = json.loads(d.get("parts") or "[]")
        except (ValueError, TypeError):
            d["parts"] = []
        return d

    def cm_list(self, only_active: bool = False):
        sql = "SELECT * FROM custom_menu_buttons"
        if only_active:
            sql += " WHERE is_active=1"
        sql += " ORDER BY sort_order, id"
        with self._get_conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._cm_row(r) for r in rows]

    def cm_get(self, button_id: int):
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM custom_menu_buttons WHERE id=?", (int(button_id),)).fetchone()
        return self._cm_row(row)

    def cm_count(self) -> int:
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) c FROM custom_menu_buttons").fetchone()["c"]

    def cm_create(self, title: str, kind: str, url: str = "", parts=None, style: str = "") -> int:
        if kind not in ("url", "content"):
            raise ValueError("kind")
        with self._get_conn() as conn:
            nxt = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 n FROM custom_menu_buttons").fetchone()["n"]
            cur = conn.execute(
                "INSERT INTO custom_menu_buttons (title, style, kind, url, parts, is_active, sort_order) "
                "VALUES (?,?,?,?,?,1,?)",
                ((title or "").strip()[:MAX_TITLE_LEN], style or "", kind, url or "",
                 json.dumps(parts or [], ensure_ascii=False), nxt),
            )
            return cur.lastrowid

    def cm_update(self, button_id: int, **fields) -> None:
        allowed = {"title", "style", "kind", "url", "parts", "is_active"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "parts":
                v = json.dumps(v or [], ensure_ascii=False)
            if k == "title":
                v = (v or "").strip()[:MAX_TITLE_LEN]
            sets.append(f"{k}=?")
            vals.append(v)
        if not sets:
            return
        vals.append(int(button_id))
        with self._get_conn() as conn:
            conn.execute(f"UPDATE custom_menu_buttons SET {', '.join(sets)} WHERE id=?", vals)

    def cm_delete(self, button_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM custom_menu_buttons WHERE id=?", (int(button_id),))

    def cm_move(self, button_id: int, direction: int) -> None:
        """direction=-1 یعنی بالا، +1 یعنی پایین (جابه‌جایی با کلید همسایه)."""
        items = self.cm_list()
        ids = [b["id"] for b in items]
        if int(button_id) not in ids:
            return
        i = ids.index(int(button_id))
        j = i + (-1 if direction < 0 else 1)
        if j < 0 or j >= len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        with self._get_conn() as conn:
            for order, bid in enumerate(ids, start=1):
                conn.execute("UPDATE custom_menu_buttons SET sort_order=? WHERE id=?", (order, bid))

    def cm_set_order(self, button_ids) -> None:
        """ذخیره‌ی ترتیب کامل کلیدهای سفارشی منو بر اساس شناسه‌ها."""
        try:
            requested = [int(x) for x in (button_ids or [])]
        except (TypeError, ValueError):
            raise ValueError("custom menu order")

        # فقط شناسه‌های موجود پذیرفته می‌شوند و موارد جاافتاده در انتها می‌آیند.
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM custom_menu_buttons ORDER BY sort_order, id"
            ).fetchall()
            existing = [int(row["id"]) for row in rows]
            ordered = []
            seen = set()
            for button_id in requested:
                if button_id in existing and button_id not in seen:
                    ordered.append(button_id)
                    seen.add(button_id)
            ordered.extend(button_id for button_id in existing if button_id not in seen)
            for sort_order, button_id in enumerate(ordered, start=1):
                conn.execute(
                    "UPDATE custom_menu_buttons SET sort_order=? WHERE id=?",
                    (sort_order, button_id),
                )

    def cm_add_click(self, button_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("UPDATE custom_menu_buttons SET clicks=clicks+1 WHERE id=?", (int(button_id),))
