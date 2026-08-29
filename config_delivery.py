# -*- coding: utf-8 -*-
"""
تحویل حرفه‌ای کانفیگ به کاربر

این ماژول منطق مشترک تحویل کانفیگ را برای هر سه مسیر فراهم می‌کند:
  ۱) خرید از کیف پول/کد تخفیف که به‌صورت خودکار تایید می‌شود (handlers_user.py)
  ۲) خرید با رسید کارت‌به‌کارت که ادمین از داخل خودِ بات تایید می‌کند (handlers_admin.py)
  ۳) خرید/سفارش شخصی که ادمین از پنل وب مستقل تایید می‌کند (admin_panel/server.py)

خروجی شامل: عکس QR کد لینک اشتراک، مشخصات کامل سفارش، و پیام تشکر است.

ساخت QR و متن کپشن (build_qr_bytes / build_delivery_caption) عمداً بدون وابستگی
به aiogram نوشته شده‌اند تا پنل وب مستقل (که نمونه‌ای از Bot در اختیار ندارد و
مستقیم با Bot API خام کار می‌کند) هم بتواند از همین منطق برای ارسال همان پیام
«شیک» استفاده کند، نه فقط یک لینک خشک و ساده.
"""

from datetime import datetime
from io import BytesIO

import qrcode
from aiogram import Bot
from aiogram.types import BufferedInputFile

from jalali import to_jalali_str
from sub_info import fetch_individual_links


def build_qr_bytes(link: str) -> bytes:
    """ساخت بایت‌های تصویر PNG کد QR از روی لینک اشتراک (بدون وابستگی به aiogram)."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


def _build_qr_photo(link: str, filename: str = "config_qr.png") -> BufferedInputFile:
    """نگاشت بایت‌های QR به فرمت قابل ارسال aiogram."""
    return BufferedInputFile(build_qr_bytes(link), filename=filename)


def build_delivery_caption(
    product_name: str,
    idx: int,
    total: int,
    order_id: int = None,
    jalali_ready_date: str = None,
) -> str:
    """متن کامل کپشن تحویل کانفیگ (مشخصات سفارش + راهنمای اتصال + پیام تشکر)."""
    if jalali_ready_date is None:
        jalali_ready_date = to_jalali_str(datetime.now(), with_time=True)

    caption = "🎉 با تشکر از خرید شما!\n\n"
    caption += "✅ کانفیگ شما با موفقیت صادر و آماده استفاده است.\n\n"
    caption += "🧾 مشخصات سفارش\n"
    if order_id:
        caption += f"┣ 🆔 شماره سفارش: #{order_id}\n"
    caption += f"┣ 📦 محصول: {product_name}\n"
    if total > 1:
        caption += f"┣ 🔢 کانفیگ {idx} از {total}\n"
    caption += f"┗ 📅 تاریخ تحویل: {jalali_ready_date}\n\n"
    caption += (
        "📱 برای اتصال، کافیست تصویر QR بالا را با اپلیکیشن V2Ray خود اسکن کنید؛ "
        "یا لینک اشتراک را که در پیام بعدی برایتان ارسال می‌شود، کپی و در بخش "
        "«افزودن اشتراک/Subscription» اپلیکیشن وارد نمایید.\n\n"
        "🔒 این کانفیگ به‌صورت اختصاصی فقط برای شما صادر شده؛ لطفاً آن را با دیگران به اشتراک نگذارید "
        "تا کیفیت اتصال شما حفظ شود.\n\n"
        "📞 در صورت بروز هرگونه مشکل در اتصال، از بخش «ارتباط با پشتیبانی» با ما در تماس باشید.\n\n"
        "🙏 از اعتماد شما سپاسگزاریم و امیدواریم از سرویس‌مان راضی باشید."
    )
    return caption


def build_summary_text(final_price: int, total: int) -> str:
    summary = f"💰 مبلغ کل پرداخت‌شده: {final_price:,} تومان"
    if total > 1:
        summary += f" ({total} عدد کانفیگ)"
    return summary


async def send_individual_configs(bot: Bot, user_tg_id: int, links: list) -> None:
    """نسخه‌ی عمومی، برای استفاده از خارج این ماژول (مثلاً فلوی کانفیگ تست در handlers_user.py)."""
    await _send_individual_configs(bot, user_tg_id, links)


async def _send_individual_configs(bot: Bot, user_tg_id: int, links: list) -> None:
    """کانفیگ‌های تکی داخل یک اشتراک را در قالب یک یا چند پیام (با رعایت سقف
    ۴۰۹۶ کاراکتری تلگرام) ارسال می‌کند. خطای احتمالی (مثلاً پارس مارک‌داون)
    نباید مانع تحویل اصلی سفارش شود، پس کاملاً silent-fail است.
    """
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
            await bot.send_message(user_tg_id, part, parse_mode="Markdown")
        except Exception:
            try:
                await bot.send_message(user_tg_id, part)
            except Exception:
                pass


def _delivery_flags(db) -> tuple:
    """خروجی: (ارسال لینک اشتراک فعال است؟, ارسال کانفیگ‌های تکی فعال است؟).
    اگر db داده نشود (فراخوانی قدیمی بدون این پارامتر)، هر دو پیش‌فرض فعال‌اند."""
    if db is None:
        return True, True
    sub_link_on = db.get_setting("deliver_sub_link_enabled", "1") != "0"
    individual_on = db.get_setting("deliver_individual_configs_enabled", "1") != "0"
    return sub_link_on, individual_on


async def deliver_config_to_user(
    bot: Bot,
    user_tg_id: int,
    product_name: str,
    links,
    final_price: int = None,
    order_id: int = None,
    db=None,
) -> None:
    """
    ارسال حرفه‌ای کانفیگ(های) خریداری‌شده به کاربر: عکس QR کد لینک اشتراک + مشخصات
    کامل سفارش + پیام تشکر، و در پیام بعدی خودِ لینک به‌صورت متنی و قابل کپی.
    links می‌تواند یک لینک تکی (str) یا لیستی از لینک‌ها باشد (خرید با تعداد بیشتر از ۱)؛
    در حالت لیست، هر کانفیگ با شماره‌ی خودش (کانفیگ N از M) جداگانه ارسال می‌شود.

    ارسال متن لینک اشتراک و ارسال کانفیگ‌های تکی هرکدام جدا از طریق تنظیمات
    deliver_sub_link_enabled / deliver_individual_configs_enabled قابل فعال/غیرفعال‌سازی‌اند؛
    پارامتر db برای خواندن این دو تنظیم لازم است (اگر داده نشود، هر دو فعال فرض می‌شوند).

    (نسخه‌ی aiogram - برای فراخوانی از داخل خودِ بات. برای پنل وب مستقل از
    admin_panel.config_delivery_web.deliver_config_to_user_web استفاده کن.)
    """
    if isinstance(links, str):
        links = [links]
    total = len(links)
    sub_link_on, individual_on = _delivery_flags(db)

    for idx, link in enumerate(links, start=1):
        caption = build_delivery_caption(product_name, idx, total, order_id)

        try:
            qr_photo = _build_qr_photo(link)
            await bot.send_photo(user_tg_id, qr_photo, caption=caption)
        except Exception:
            # اگر ساخت/ارسال QR به هر دلیلی ناموفق بود، حداقل متن اطلاعات برای کاربر ارسال شود
            await bot.send_message(user_tg_id, caption)

        if sub_link_on:
            await bot.send_message(
                user_tg_id,
                f"🔗 لینک اشتراک شما (برای کپی):\n`{link}`",
                parse_mode="Markdown",
            )

        if individual_on and link.startswith(("http://", "https://")):
            try:
                individual_links = await fetch_individual_links(link)
            except Exception:
                individual_links = []
            if individual_links:
                await _send_individual_configs(bot, user_tg_id, individual_links)

    if final_price is not None:
        await bot.send_message(user_tg_id, build_summary_text(final_price, total))
