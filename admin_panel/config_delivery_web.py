# -*- coding: utf-8 -*-
"""
معادل admin_panel-ی تابع deliver_config_to_user در config_delivery.py؛ همان
پیام «شیک» (عکس QR + مشخصات کامل سفارش + پیام تشکر) را برای کاربر می‌فرستد،
اما چون پنل وب مستقل نمونه‌ای از Bot در اختیار ندارد، مستقیم با Bot API خام
(از طریق admin_panel.telegram_notify) کار می‌کند.
"""

from config_delivery import build_qr_bytes, build_delivery_caption, build_summary_text, _delivery_flags
from admin_panel.telegram_notify import send_message as tg_send, send_photo as tg_send_photo
from config import BOT_TOKEN
from sub_info import fetch_individual_links


async def _send_individual_configs_web(user_tg_id: int, links: list, bot_token: str) -> None:
    """معادل پنل وب _send_individual_configs در config_delivery.py؛ کانفیگ‌های تکی
    استخراج‌شده از لینک اشتراک را (با رعایت سقف کاراکتری تلگرام) برای کاربر می‌فرستد.
    کاملاً silent-fail است تا مانع تحویل اصلی سفارش نشود."""
    header = "📋 کانفیگ‌های تکی این اشتراک (اگه لینک اشتراک رو نتونستی مستقیم اضافه کنی، هرکدوم از این‌ها رو تکی وارد کن):\n\n"
    chunk = header
    chunks = []
    for c in links:
        piece = f"`{c}`\n\n"
        if len(chunk) + len(piece) > 3800:
            chunks.append(chunk)
            chunk = ""
        chunk += piece
    if chunk.strip():
        chunks.append(chunk)

    for part in chunks:
        try:
            ok = await tg_send(bot_token, user_tg_id, part, parse_mode="Markdown")
            if not ok:
                await tg_send(bot_token, user_tg_id, part)
        except Exception:
            pass


async def deliver_config_to_user_web(
    user_tg_id: int,
    product_name: str,
    links,
    final_price: int = None,
    order_id: int = None,
    db=None,
    bot_token: str = None,
) -> None:
    """نسخه‌ی پنل وب مستقل از تحویل حرفه‌ای کانفیگ؛ همان خروجی‌ای که کاربر از خودِ بات می‌بیند.
    db برای خواندن تنظیمات deliver_sub_link_enabled / deliver_individual_configs_enabled لازم است
    (اگر داده نشود، هر دو فعال فرض می‌شوند). bot_token برای بات‌های نمایندگی (که توکن جدا دارند)
    باید صریحاً پاس داده شود؛ در غیر این صورت توکن بات اصلی استفاده می‌شود."""
    bot_token = bot_token or BOT_TOKEN
    if isinstance(links, str):
        links = [links]
    total = len(links)
    sub_link_on, individual_on = _delivery_flags(db)

    for idx, link in enumerate(links, start=1):
        caption = build_delivery_caption(product_name, idx, total, order_id)

        sent = False
        try:
            qr_bytes = build_qr_bytes(link)
            sent = await tg_send_photo(bot_token, user_tg_id, qr_bytes, "config_qr.png", caption)
        except Exception:
            sent = False
        if not sent:
            # اگر ساخت/ارسال QR به هر دلیلی ناموفق بود، حداقل متن اطلاعات برای کاربر ارسال شود
            await tg_send(bot_token, user_tg_id, caption)

        if sub_link_on:
            await tg_send(bot_token, user_tg_id, f"🔗 لینک اشتراک شما (برای کپی):\n`{link}`", parse_mode="Markdown")

        if individual_on and link.startswith(("http://", "https://")):
            try:
                individual_links = await fetch_individual_links(link)
            except Exception:
                individual_links = []
            if individual_links:
                await _send_individual_configs_web(user_tg_id, individual_links, bot_token)

    if final_price is not None:
        await tg_send(bot_token, user_tg_id, build_summary_text(final_price, total))
