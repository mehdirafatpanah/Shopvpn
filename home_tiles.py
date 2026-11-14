# -*- coding: utf-8 -*-
"""ترتیب کاشی‌های «دسترسی سریع» صفحه‌ی اصلی مینی‌اپ بر اساس چیدمان منوی اصلی ربات.

ترتیب منوی ربات (menu_order) تنها منبع است؛ هر کاشی به یک دکمه‌ی ربات نگاشت می‌شود
و دکمه‌های سفارشی (custom_menu:ID) همان جایگاهشان در ربات را در مینی‌اپ هم دارند.
تا وقتی ادمین ترتیب منو را تغییر نداده، چیدمان پیش‌فرض مینی‌اپ دست‌نخورده می‌ماند.
"""

# کلید دکمه‌ی ربات -> کاشی‌های مینی‌اپ (به‌ترتیب نمایش). «حساب کاربری» در ربات یک دکمه است
# ولی در مینی‌اپ سه کاشی دارد که کنار هم می‌مانند.
BOT_KEY_TO_TILES = {
    "btn_buy": ["store"],
    "btn_my_orders": ["services", "wallet", "profile"],
    "btn_test": ["test"],
    "btn_contact": ["support"],
    "btn_reseller_panel": ["reseller"],
}
DEFAULT_TILES = ["store", "services", "wallet", "profile", "test", "support", "reseller"]


def tile_order(menu_order: list, custom_button_ids: list, customized: bool) -> list:
    """لیست کلید کاشی‌ها (store, services, ..., cm:ID). customized=False یعنی ترتیب پیش‌فرض."""
    cm_keys = [f"cm:{int(i)}" for i in custom_button_ids]
    if not customized:
        return DEFAULT_TILES + cm_keys
    order, seen = [], set()

    def add(k):
        if k not in seen:
            seen.add(k)
            order.append(k)

    for key in menu_order or []:
        if key in BOT_KEY_TO_TILES:
            for t in BOT_KEY_TO_TILES[key]:
                add(t)
        elif isinstance(key, str) and key.startswith("custom_menu:"):
            tail = key.split(":", 1)[1]
            if tail.isdigit() and f"cm:{int(tail)}" in cm_keys:
                add(f"cm:{int(tail)}")
    for t in DEFAULT_TILES + cm_keys:
        add(t)
    return order


def tile_rows(menu_order: list, custom_button_ids: list, breaks) -> list:
    """چیدمان ردیفی مثل ربات: breaks همان main_menu_row_breaks است (کلیدهایی که ردیف جدید شروع می‌کنند).
    اگر breaks=None یعنی چیدمان ردیفی سفارشی نشده و None برمی‌گردد (مینی‌اپ چیدمان پیش‌فرضش را نگه می‌دارد).
    هر ردیف لیستی از کلید کاشی‌هاست؛ کلاینت بعد از حذف کاشی‌های نامربوط (مثلاً تست برای کاربری که
    قبلاً گرفته) ردیف‌ها را دوتا‌دوتا می‌چیند و کاشی تنها را تمام‌عرض می‌کند."""
    if breaks is None:
        return None
    cm_keys = {f"cm:{int(i)}" for i in custom_button_ids}
    break_set = set(breaks)
    rows, cur, seen = [], [], set()
    for key in menu_order or []:
        if key in BOT_KEY_TO_TILES:
            tiles = list(BOT_KEY_TO_TILES[key])
        elif isinstance(key, str) and key.startswith("custom_menu:") and key.split(":", 1)[1].isdigit() \
                and f"cm:{int(key.split(':', 1)[1])}" in cm_keys:
            tiles = [f"cm:{int(key.split(':', 1)[1])}"]
        else:
            continue
        if cur and key in break_set:
            rows.append(cur)
            cur = []
        cur += [t for t in tiles if t not in seen]
        seen.update(tiles)
    if cur:
        rows.append(cur)
    rest = [t for t in DEFAULT_TILES + sorted(cm_keys) if t not in seen]
    rows += [[t] for t in rest]
    return [r for r in rows if r]
