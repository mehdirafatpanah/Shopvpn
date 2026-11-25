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


# ---------------------------------------------------------------------------
# تشخیص عضویت از روی پاسخ getChatMember (مشترک بین ربات، مینی‌اپ و فروشگاه وب)
# ---------------------------------------------------------------------------
_MEMBER_STATUSES = {"member", "administrator", "creator", "owner"}
_NOT_MEMBER_STATUSES = {"left", "kicked", "banned"}
# خطاهایی که یعنی «این کاربر در کانال نیست» (نه مشکل پیکربندی بات)؛ خطاهای دیگر fail-open می‌مانند.
_NOT_MEMBER_ERRORS = ("user not found", "participant_id_invalid", "user_not_participant", "participant not found")


def _status_text(status) -> str:
    """status می‌تواند رشته‌ی ساده (JSON خام API) یا Enum آیوگرم باشد؛ هر دو به متن کوچک تبدیل می‌شوند."""
    value = getattr(status, "value", status)
    return str(value or "").strip().lower()


def membership_from_status(status, is_member=None) -> bool:
    """True = عضو است.

    نکته‌ی مهم: کاربرِ «restricted» ممکن است از کانال خارج شده ولی محدودیتش مانده باشد؛ در این حالت
    تلگرام فیلد is_member=false می‌دهد و نباید عضو حساب شود (قبلاً هر restricted عضو حساب می‌شد).
    """
    st = _status_text(status)
    if st in _MEMBER_STATUSES:
        return True
    if st in _NOT_MEMBER_STATUSES:
        return False
    if st == "restricted":
        return True if is_member is None else bool(is_member)
    return True  # وضعیت ناشناخته (نسخه‌ی جدید API) = fail-open، نه قفل‌شدن همه


def is_not_member_error(message) -> bool:
    """پیام خطای getChatMember که یعنی کاربر عضو نیست (مثل «user not found»)."""
    text = str(message or "").lower()
    return any(marker in text for marker in _NOT_MEMBER_ERRORS)
