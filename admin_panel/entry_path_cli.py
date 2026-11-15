# -*- coding: utf-8 -*-
"""نمایش، تنظیم یا خاموش‌کردن مسیر ورود مخفی پنل وب از روی سرور (برای وقتی که مسیر فراموش شده).

python3 -m admin_panel.entry_path_cli --show | --disable | --set <path>
"""

import argparse
import sqlite3
import sys

from config import DB_PATH
import web_entry_gate as gate


def _put(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--show", action="store_true")
    group.add_argument("--disable", action="store_true")
    group.add_argument("--set", metavar="PATH")
    args = ap.parse_args()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        if args.set is not None:
            slug = args.set.strip().strip("/")
            error = gate.validate_slug(slug)
            if error:
                print(error)
                return 1
            _put(conn, gate.KEY_PATH, slug)
            _put(conn, gate.KEY_ENABLED, "1")
            conn.commit()
        elif args.disable:
            _put(conn, gate.KEY_ENABLED, "0")
            conn.commit()
        rows = dict(conn.execute(
            "SELECT key, value FROM settings WHERE key IN (?, ?)", (gate.KEY_ENABLED, gate.KEY_PATH)
        ).fetchall())
    finally:
        conn.close()
    enabled = str(rows.get(gate.KEY_ENABLED) or "0") == "1"
    print("enabled" if enabled else "disabled")
    print("path: /" + (rows.get(gate.KEY_PATH) or ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
