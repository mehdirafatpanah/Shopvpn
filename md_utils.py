# -*- coding: utf-8 -*-
"""
ابزار کمکی برای Escape کردن متن قبل از قرار گرفتن در پیام‌هایی با
parse_mode="Markdown" (لگاسی تلگرام).

چرا لازم است؟
    هر مقداری که از کاربر می‌آید (username تلگرام، نام کاربری دلخواه
    کانفیگ، نام محصول و ...) ممکن است شامل کاراکترهای خاص مارک‌داون
    باشد: _ * ` [ . اگر این مقادیر بدون Escape داخل متنی قرار بگیرند که
    parse_mode="Markdown" دارد، تلگرام سعی می‌کند آن‌ها را به‌عنوان
    entity (ایتالیک/بولد/لینک/کد) تفسیر کند و چون معمولاً جفت باز/بسته
    کامل نیست، با خطای زیر رد می‌شود:
        Bad Request: can't parse entities: can't find end of the entity
        starting at byte offset N
    نتیجه‌اش این است که کل پیام اصلاً ارسال نمی‌شود.

استفاده:
    from md_utils import escape_md
    text = f"👤 نام کاربری: {escape_md(username)}"
"""

import html as _html

_MD_SPECIAL_CHARS = ("\\", "_", "*", "`", "[")


def escape_html(value) -> str:
    """مقدار را برای امن‌بودن داخل متن HTML (parse_mode="HTML") تلگرام
    Escape می‌کند. لازم است چون first_name/username تلگرام هر کاراکتری
    از جمله < > & می‌تواند داشته باشد و همین باعث خطای مشابه در حالت
    HTML می‌شود."""
    if value is None:
        return ""
    return _html.escape(str(value), quote=False)


def escape_md(value) -> str:
    """مقدار را برای امن‌بودن داخل متن Markdown (لگاسی) تلگرام Escape می‌کند.

    توجه: این تابع برای متنی است که *بیرون* از بلاک کد (backtick) قرار
    می‌گیرد. مقادیری که از قبل داخل ` ... ` گذاشته شده‌اند نیازی به این
    escape ندارند (تلگرام داخل بلاک کد چیزی را parse نمی‌کند).
    """
    if value is None:
        return ""
    text = str(value)
    for ch in _MD_SPECIAL_CHARS:
        text = text.replace(ch, "\\" + ch)
    return text
