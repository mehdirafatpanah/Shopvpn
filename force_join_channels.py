# -*- coding: utf-8 -*-
"""توابع خالص برای فهرست کانال‌های عضویت اجباری (تعداد نامحدود).

فهرست در همان کلید قدیمی ``force_join_channel`` و با جداکنندهٔ خط جدید ذخیره می‌شود؛
بنابراین نصب‌های قدیمی (یک کانال) بدون مهاجرت کار می‌کنند.
"""
import re

_T_ME = re.compile(r"^(?:https?://)?(?:www\.)?t\.me/([A-Za-z0-9_]{3,})/?$", re.I)


def normalize_channel(raw) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    match = _T_ME.match(value)
    if match:
        return "@" + match.group(1)
    if not value.startswith("@") and not re.fullmatch(r"-\d+", value):
        value = "@" + value
    if re.fullmatch(r"@[A-Za-z0-9_]{3,}", value) or re.fullmatch(r"-\d+", value):
        return value
    return ""  # نامعتبر (مثلاً لینک دعوت خصوصی +xxxx)


def parse_channels(raw) -> list:
    """رشته (خط جدید / ویرگول / فاصله) یا لیست را به فهرست یکتا و مرتب کانال‌ها تبدیل می‌کند."""
    if isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[\n,;،\s]+", str(raw or ""))
    seen, result = set(), []
    for part in parts:
        channel = normalize_channel(part)
        key = channel.lower()
        if channel and key not in seen:
            seen.add(key)
            result.append(channel)
    return result


def invalid_entries(raw) -> list:
    """ورودی‌هایی که قابل تبدیل به آیدی کانال معتبر نیستند."""
    parts = [str(x) for x in raw] if isinstance(raw, (list, tuple)) else re.split(r"[\n,;،\s]+", str(raw or ""))
    return [p for p in parts if p.strip() and not normalize_channel(p)]


def serialize_channels(channels) -> str:
    return "\n".join(parse_channels(channels))


def join_link(channel: str):
    """لینک عضویت؛ برای آیدی عددی (کانال خصوصی) لینک عمومی وجود ندارد."""
    channel = str(channel or "")
    return "https://t.me/" + channel.lstrip("@") if channel.startswith("@") else None
