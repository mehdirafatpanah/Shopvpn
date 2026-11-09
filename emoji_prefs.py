"""Resolve configurable emojis for category, product and test-plan buttons."""

NONE_MARK = "-"

GLOBAL_KEYS = {
    "emoji_product_in_stock": ("✅", "ایموجی محصول موجود"),
    "emoji_product_out_of_stock": ("⛔️", "ایموجی محصول ناموجود"),
    "emoji_category": ("📁", "ایموجی دسته‌بندی"),
    "emoji_test_plan": ("🧪", "ایموجی پلن تست"),
}

RESET_WORDS = {"پیش‌فرض", "پیشفرض", "default", "reset", "0"}
REMOVE_WORDS = {NONE_MARK, "حذف", "none", "remove"}
MAX_LEN = 16


def _row_value(row, key):
    if row is None:
        return None
    try:
        return row[key] if key in row.keys() else None
    except (AttributeError, KeyError, IndexError):
        return None


def resolve(item_value, global_value: str) -> str:
    value = (item_value or "").strip()
    if not value:
        return global_value
    if value == NONE_MARK:
        return ""
    return value


def global_emoji(db, key: str) -> str:
    return (db.get_setting(key, GLOBAL_KEYS[key][0]) or "").strip()


def with_emoji(emoji: str, text: str) -> str:
    return f"{emoji} {text}" if emoji else text


def category_emoji(db, cat) -> str:
    return resolve(_row_value(cat, "emoji"), global_emoji(db, "emoji_category"))


def product_stock_emoji(db, cat, in_stock: bool) -> str:
    if not in_stock:
        return global_emoji(db, "emoji_product_out_of_stock")
    return resolve(_row_value(cat, "product_emoji"), global_emoji(db, "emoji_product_in_stock"))


def test_plan_emoji(db, plan) -> str:
    return resolve(_row_value(plan, "emoji"), global_emoji(db, "emoji_test_plan"))


def parse_input(text: str, allow_reset: bool = True):
    """Return (ok, value). value: '' reset to global, '-' hide, else the emoji text."""
    raw = (text or "").strip()
    if not raw:
        return False, None
    low = raw.lower()
    if allow_reset and low in RESET_WORDS:
        return True, ""
    if low in REMOVE_WORDS:
        return True, NONE_MARK
    if len(raw) > MAX_LEN:
        return False, None
    return True, raw


def describe(value) -> str:
    value = (value or "").strip()
    if not value:
        return "پیش‌فرض"
    if value == NONE_MARK:
        return "بدون ایموجی"
    return value
