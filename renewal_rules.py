# -*- coding: utf-8 -*-
"""
قوانین «تمدید کامل» هر محصول (قابل تنظیم در مرحله‌ی ساخت/ویرایش محصول).

ستون‌های محصول (همه INTEGER 0/1):
  renew_full_enabled   : آیا این محصول اصلاً در لیست تمدید کامل نمایش داده شود (پیش‌فرض 1)
  renew_same_type_only : فقط برای سرویس‌هایی که هم‌نوع این محصول‌اند (نامحدود/حجمی) نمایش داده شود (پیش‌فرض 1)
  renew_reset          : ریست کامل؛ حجم و زمان باقیمانده حذف و فقط بسته‌ی جدید اعمال می‌شود (پیش‌فرض 0)
  renew_carry_volume   : حجم باقیمانده‌ی سرویس به بسته‌ی جدید اضافه شود (پیش‌فرض 1)
  renew_carry_time     : زمان باقیمانده‌ی سرویس به بسته‌ی جدید اضافه شود (پیش‌فرض 1)

پیش‌فرض‌ها دقیقاً رفتار قبلی سیستم (جمع‌شدن حجم و زمان باقیمانده) را حفظ می‌کنند.
اگر renew_reset روشن باشد، دو گزینه‌ی انتقال خاموش حساب می‌شوند.
"""

RULE_KEYS = (
    "renew_full_enabled", "renew_same_type_only", "renew_reset",
    "renew_carry_volume", "renew_carry_time",
)
DEFAULTS = {
    "renew_full_enabled": 1, "renew_same_type_only": 1, "renew_reset": 0,
    "renew_carry_volume": 1, "renew_carry_time": 1,
}
RULE_LABELS = {
    "renew_full_enabled": "قابل تمدید کامل باشد",
    "renew_same_type_only": "فقط برای سرویس‌های هم‌نوع (نامحدود/حجمی)",
    "renew_reset": "ریست کامل بعد از تمدید",
    "renew_carry_volume": "انتقال حجم باقیمانده",
    "renew_carry_time": "انتقال زمان باقیمانده",
}


def _get(row, key):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = None
    return DEFAULTS[key] if value is None else value


def normalize(raw) -> dict:
    """ورودی خام (dict/Row) را به dict کامل 0/1 تبدیل و تناقض‌ها را رفع می‌کند."""
    rules = {k: 1 if _get(raw or {}, k) else 0 for k in RULE_KEYS}
    if rules["renew_reset"]:
        rules["renew_carry_volume"] = 0
        rules["renew_carry_time"] = 0
    return rules


def product_rules(product) -> dict:
    return normalize(product)


def is_unlimited_product(product) -> bool:
    return int(product["auto_provision_volume_gb"] or 0) == 0


def is_unlimited_service(cc) -> bool:
    try:
        return int(cc["volume_gb"] or 0) == 0
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def is_renewable_for(product, cc) -> bool:
    """آیا این محصول باید در لیست «تمدید کامل» این سرویس نمایش داده شود؟"""
    rules = product_rules(product)
    if not rules["renew_full_enabled"]:
        return False
    if rules["renew_same_type_only"] and is_unlimited_product(product) != is_unlimited_service(cc):
        return False
    return True


def filter_products(products, cc) -> list:
    return [p for p in products if is_renewable_for(p, cc)]


def order_flags(product):
    """(carry_volume, carry_time) برای ذخیره روی سفارش تمدید."""
    rules = product_rules(product)
    return rules["renew_carry_volume"], rules["renew_carry_time"]


# کلیدهای کوتاه برای callback_data ربات (محدودیت ۶۴ بایتی تلگرام)
SHORT_KEYS = {
    "enabled": "renew_full_enabled", "same": "renew_same_type_only", "reset": "renew_reset",
    "cv": "renew_carry_volume", "ct": "renew_carry_time",
}


def toggle(rules: dict, short: str):
    """یک قانون را برعکس می‌کند. برمی‌گرداند (rules جدید, پیام خطا یا None).
    وقتی «ریست کامل» روشن است دو گزینه‌ی انتقال قابل انتخاب نیستند."""
    key = SHORT_KEYS.get(short)
    if not key:
        return rules, "گزینه‌ی نامعتبر."
    rules = normalize(rules)
    if key in ("renew_carry_volume", "renew_carry_time") and rules["renew_reset"]:
        return rules, "ابتدا «ریست کامل» را خاموش کنید."
    rules[key] = 0 if rules[key] else 1
    return normalize(rules), None
