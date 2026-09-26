# -*- coding: utf-8 -*-
"""محدودیت تعداد کاربر همزمان (limitIp) برای محصولات متصل به پنل.

هر محصول یک «تعداد کاربر پایه» (base_users) دارد که در قیمت پایه گنجانده شده است:
  - base_users = 0  → حالت قدیمی: محدودیتی روی پنل اعمال نمی‌شود (یا خریدار خودش از
                      انتخابگر ۱..max_users انتخاب می‌کند؛ قیمت پایه شامل ۱ کاربر است).
  - base_users >= 1 → مدیر تعداد ثابت را مشخص کرده؛ همهٔ خریدها با همین limitIp ساخته می‌شوند.
مشتری بعداً می‌تواند از «سرویس‌های من» تعداد را تا max_users افزایش دهد و فقط مابه‌التفاوت
(extra_user_price برای هر کاربر اضافه) را بپردازد.
"""

from panel_providers import PROVIDERS


def _field(row, key, default=0):
    if row is None:
        return default
    return row[key] if key in row.keys() and row[key] is not None else default


def product_base_users(product) -> int:
    """تعداد کاربر همزمانِ گنجانده‌شده در قیمت پایه؛ 0 یعنی مدیر عدد ثابتی تعیین نکرده."""
    try:
        return max(int(_field(product, "base_users")), 0)
    except (TypeError, ValueError):
        return 0


def _price_floor(product) -> int:
    return max(product_base_users(product), 1)


def configured_max_users(product) -> int:
    """سقف ارتقا (بالاترین تعداد کاربری که مشتری می‌تواند بخرد)؛ 0 یعنی ارتقا غیرفعال است."""
    extra = int(_field(product, "extra_user_price"))
    max_users = int(_field(product, "max_users"))
    if not _field(product, "is_auto_provision") or extra <= 0 or max_users <= _price_floor(product):
        return 0
    return max_users


def server_supports(server) -> bool:
    if not server:
        return False
    provider_cls = PROVIDERS.get(server["panel_type"])
    return bool(provider_cls and getattr(provider_cls, "supports_user_limit", False))


def resolve_server(db, product):
    server_id = _field(product, "provision_server_id", None)
    if server_id:
        return db.get_panel_server(server_id)
    try:
        from config import DB_PATH as MAIN_DB_PATH
        from database import Database

        owner_id = db.get_owner_telegram_id()
        if not owner_id:
            return None
        return Database(MAIN_DB_PATH).get_reseller_panel(owner_id)
    except Exception:
        return None


def included_users(db, product) -> int:
    """تعداد کاربر ثابتِ این محصول (base_users) در صورتی که روی پنل واقعاً قابل اعمال باشد؛ وگرنه 0."""
    base = product_base_users(product)
    if not base or not _field(product, "is_auto_provision"):
        return 0
    server = resolve_server(db, product)
    if not server or not _field(server, "is_active", 1) or not server_supports(server):
        return 0
    return base


def selectable_max_users(db, product) -> int:
    """سقف انتخابگرِ «هنگام خرید» (فقط برای محصولات قدیمی بدون base_users)."""
    if product_base_users(product) >= 1:
        return 0
    max_users = configured_max_users(product)
    if not max_users:
        return 0
    server = resolve_server(db, product)
    if not server or not _field(server, "is_active", 1) or not server_supports(server):
        return 0
    return max_users


def price_for_users(product, users: int) -> int:
    price = int(product["price"])
    floor = _price_floor(product)
    if users and users > floor:
        price += int(_field(product, "extra_user_price")) * (users - floor)
    return price


def order_user_limit(order, product=None) -> int:
    """limitIp برای ساخت سرویس: مقدار ثبت‌شده در سفارش، وگرنه base_users محصول.

    fallback به base_users باعث می‌شود خریدهای بدون انتخاب کاربر (مثلاً از مینی‌اپ یا API)
    هم با تعداد ثابتی که مدیر تعیین کرده ساخته شوند."""
    value = _field(order, "user_limit", None)
    if value:
        return int(value)
    if product is not None and _field(product, "is_auto_provision"):
        return product_base_users(product)
    return 0


def renewal_users(db, product, cc) -> int:
    """تعداد کاربری که تمدید کاملِ یک سرویس باید روی آن قیمت‌گذاری/اعمال شود (محصولات با base_users).

    اگر سرویس قبلاً ارتقا داده شده باشد همان تعداد فعلی حفظ می‌شود تا قیمت تمدید با
    تعداد واقعی کاربران هم‌خوان باشد."""
    base = product_base_users(product)
    if not base or not _field(product, "is_auto_provision"):
        return 0
    server = db.get_panel_server(cc["panel_server_id"]) if _field(cc, "panel_server_id", None) else None
    if not server or not server_supports(server):
        return 0
    return max(int(_field(cc, "user_limit", 0) or 0), base)


def provider_kwargs(provider, user_limit) -> dict:
    if user_limit and getattr(provider, "supports_user_limit", False):
        return {"user_limit": int(user_limit)}
    return {}


def upgrade_price(product, current: int, users: int) -> int:
    return int(_field(product, "extra_user_price")) * max(users - current, 0)


def service_upgrade_info(db, cc):
    current = int(_field(cc, "user_limit", 0))
    if current < 1 or _field(cc, "source", "") == "test" or not _field(cc, "enabled", 1):
        return None
    order_id = _field(cc, "order_id", None)
    order = db.get_order(order_id) if order_id else None
    product = db.get_product(order["product_id"]) if order and order["product_id"] else None
    max_users = configured_max_users(product) if product else 0
    server = db.get_panel_server(cc["panel_server_id"])
    if not max_users or current >= max_users:
        return None
    if not server or not _field(server, "is_active", 1) or not server_supports(server):
        return None
    return {"product": product, "current": current, "max_users": max_users}
