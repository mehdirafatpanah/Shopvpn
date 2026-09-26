from i18n import tr
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

import asyncio
import os
from datetime import datetime
from io import BytesIO

import qrcode
from aiogram import Bot
from aiogram.types import BufferedInputFile

import config
from jalali import to_jalali_str
from sub_info import fetch_individual_links
from notification_i18n import localized, user_language

# -----------------------------------------------------------------------
# تصویر پس‌زمینه‌ی سفارشی برای کد QR کانفیگ (فعلاً فقط از داخل خودِ بات اصلی
# قابل تنظیم است - در handlers_admin.py، بخش «تنظیمات ارسال کانفیگ»).
# خودِ کد QR همیشه روی یک کادر کاملاً سفید قرار می‌گیرد تا قابل‌اسکن بودنش
# تضمین شود؛ تصویر انتخابی ادمین فقط به‌عنوان تزئین دور این کادر استفاده
# می‌شود. چون این تابع‌ها بدون وابستگی به aiogram نوشته شده‌اند، پنل وب
# مستقل (admin_panel/config_delivery_web.py) هم می‌تواند از همین منطق
# (و همین پس‌زمینه‌ی مشترکِ ذخیره‌شده در settings) استفاده کند.
QR_BACKGROUND_PATH = os.path.join(config.BASE_DIR, "qr_background.png")
QR_BACKGROUND_SETTING_KEY = "qr_background_enabled"

QR_CANVAS_SIZE = 1000       # اندازه‌ی نهایی تصویر مربعی خروجی (پیکسل)
QR_PANEL_RATIO = 0.62       # نسبت عرض کادر سفید حامل QR به کل تصویر
QR_PANEL_PADDING_RATIO = 0.09  # حاشیه‌ی سفید داخل کادر، دور خودِ QR
QR_PANEL_RADIUS_RATIO = 0.06   # شعاع گردی گوشه‌های کادر سفید


def has_qr_background() -> bool:
    """آیا ادمین تا الان تصویر پس‌زمینه‌ای برای QR آپلود کرده؟"""
    return os.path.isfile(QR_BACKGROUND_PATH)


def qr_background_enabled(db) -> bool:
    """آیا استفاده از پس‌زمینه فعال است؟ (هم باید فایلی آپلود شده باشد، هم سوییچ روشن باشد)."""
    if db is None or not has_qr_background():
        return False
    return db.get_setting(QR_BACKGROUND_SETTING_KEY, "1") != "0"


def save_qr_background(source_path: str) -> None:
    """تصویر آپلودشده توسط ادمین (هر فرمتی) را می‌خواند، به RGB تبدیل و به‌صورت
    یک PNG ثابت ذخیره می‌کند تا همیشه یک مسیر واحد و قابل‌پیش‌بینی داشته باشیم."""
    from PIL import Image
    with Image.open(source_path) as img:
        img = img.convert("RGB")
        img.save(QR_BACKGROUND_PATH, format="PNG")


def remove_qr_background() -> bool:
    """حذف تصویر پس‌زمینه‌ی فعلی (اگر وجود داشته باشد)."""
    if has_qr_background():
        os.remove(QR_BACKGROUND_PATH)
        return True
    return False


def _compose_qr_with_background(qr_img) -> "Image.Image":
    """کد QR (تصویر PIL سیاه/سفید ساخته‌شده توسط کتابخانه‌ی qrcode) را روی یک
    کادر کاملاً سفید در مرکز تصویر پس‌زمینه‌ی ادمین می‌چسباند. خودِ پیکسل‌های
    QR هیچ‌وقت روی پس‌زمینه قرار نمی‌گیرند - فقط دور کادر سفید تزئین می‌شود -
    تا اسکن‌پذیری کد در هر شرایطی (هر عکسی که ادمین انتخاب کند) تضمین بماند."""
    from PIL import Image, ImageDraw

    with Image.open(QR_BACKGROUND_PATH) as bg_raw:
        bg = bg_raw.convert("RGB")
        # برش مرکزی به مربع، سپس تغییر اندازه به بومِ نهایی
        w, h = bg.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        bg = bg.crop((left, top, left + side, top + side))
        bg = bg.resize((QR_CANVAS_SIZE, QR_CANVAS_SIZE), Image.LANCZOS)

    canvas = bg.convert("RGBA")

    # کادر سفید گردشده در مرکز، با سوپرسمپل برای لبه‌های صاف
    panel_size = int(QR_CANVAS_SIZE * QR_PANEL_RATIO)
    radius = int(panel_size * QR_PANEL_RADIUS_RATIO)
    scale = 4
    mask_big = Image.new("L", (panel_size * scale, panel_size * scale), 0)
    ImageDraw.Draw(mask_big).rounded_rectangle(
        (0, 0, panel_size * scale - 1, panel_size * scale - 1),
        radius=radius * scale,
        fill=255,
    )
    mask = mask_big.resize((panel_size, panel_size), Image.LANCZOS)

    panel = Image.new("RGBA", (panel_size, panel_size), (255, 255, 255, 255))
    panel_pos = ((QR_CANVAS_SIZE - panel_size) // 2, (QR_CANVAS_SIZE - panel_size) // 2)
    canvas.paste(panel, panel_pos, mask)

    # خودِ QR، با حاشیه‌ی سفید داخل کادر، دقیقاً وسط کادر
    padding = int(panel_size * QR_PANEL_PADDING_RATIO)
    qr_target = panel_size - 2 * padding
    qr_img = qr_img.convert("RGB").resize((qr_target, qr_target), Image.NEAREST)
    qr_pos = (panel_pos[0] + padding, panel_pos[1] + padding)
    canvas.paste(qr_img, qr_pos)

    return canvas.convert("RGB")


def build_qr_bytes(link: str, db=None) -> bytes:
    """ساخت بایت‌های تصویر PNG کد QR از روی لینک اشتراک (بدون وابستگی به aiogram).
    اگر ادمین پس‌زمینه‌ای برای QR تنظیم و فعال کرده باشد (db داده شده و
    qr_background_enabled(db) درست باشد)، همان تصویر دور کد QR چیده می‌شود؛
    در غیر این صورت همان کد QR ساده‌ی سیاه/سفید قبلی برگردانده می‌شود."""
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
    if qr_background_enabled(db):
        try:
            final_img = _compose_qr_with_background(img)
            final_img.save(buffer, format="PNG")
        except Exception:
            buffer = BytesIO()
            img.save(buffer, format="PNG")
    else:
        img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


def _build_qr_photo(link: str, filename: str = "config_qr.png", db=None) -> BufferedInputFile:
    """نگاشت بایت‌های QR به فرمت قابل ارسال aiogram."""
    return BufferedInputFile(build_qr_bytes(link, db=db), filename=filename)


def build_delivery_caption(
    product_name: str,
    idx: int,
    total: int,
    order_id: int = None,
    jalali_ready_date: str = None,
    category_name: str = None,
) -> str:
    """متن کامل کپشن تحویل کانفیگ (مشخصات سفارش + راهنمای اتصال + پیام تشکر)."""
    if jalali_ready_date is None:
        jalali_ready_date = to_jalali_str(datetime.now(), with_time=True)

    caption = "🎉 با تشکر از خرید شما!\n\n"
    caption += "✅ کانفیگ شما با موفقیت صادر و آماده استفاده است.\n\n"
    caption += "🧾 مشخصات سفارش\n"
    if order_id:
        caption += f"┣ 🆔 شماره سفارش: #{order_id}\n"
    if category_name:
        caption += f"┣ 📂 دسته: {category_name}\n"
    caption += f"┣ 📦 پلن: {product_name}\n"
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


async def send_individual_configs(bot: Bot, user_tg_id: int, links: list, db=None) -> None:
    """نسخه‌ی عمومی، برای استفاده از خارج این ماژول (مثلاً فلوی کانفیگ تست در handlers_user.py)."""
    await _send_individual_configs(bot, user_tg_id, links, db=db)


async def _send_individual_configs(bot: Bot, user_tg_id: int, links: list, db=None) -> None:
    """کانفیگ‌های تکی داخل یک اشتراک را در قالب یک یا چند پیام (با رعایت سقف
    ۴۰۹۶ کاراکتری تلگرام) ارسال می‌کند. خطای احتمالی (مثلاً پارس مارک‌داون)
    نباید مانع تحویل اصلی سفارش شود، پس کاملاً silent-fail است.
    """
    header = localized("📋 کانفیگ‌های تکی این اشتراک (اگه لینک اشتراک رو نتونستی مستقیم اضافه کنی، هرکدوم از این‌ها رو تکی وارد کن):\n\n", db, user_tg_id)
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
            await bot.send_message(user_tg_id, localized(part, db, user_tg_id), parse_mode="Markdown")
        except Exception:
            try:
                await bot.send_message(user_tg_id, localized(part, db, user_tg_id))
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


def get_post_delivery_text(db) -> str:
    """متن دلخواه ادمین که بعد از تحویل کامل کانفیگ (و خلاصه‌ی مبلغ) برای کاربر
    ارسال می‌شود؛ اگر db داده نشود یا چیزی تنظیم نشده باشد، رشته‌ی خالی برمی‌گردد."""
    if db is None:
        return ""
    return (db.get_setting("post_delivery_custom_text", "") or "").strip()


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

    # برای خرید پلن آماده، دسته‌بندی را مستقیماً از سفارش می‌خوانیم تا همه‌ی
    # مسیرهای پرداخت (درگاه‌ها، کارت‌به‌کارت و پرداخت کیف پول) خروجی یکسانی داشته
    # باشند. برای کانفیگ شخصی، دسته‌بندی وجود ندارد و همان خروجی قبلی حفظ می‌شود.
    category_name = None
    if db is not None and order_id:
        try:
            order = db.get_order(order_id)
            if order and not order["is_custom_config"] and order["product_id"]:
                product = db.get_product(order["product_id"])
                if product and product["category_id"]:
                    category = db.get_category(product["category_id"])
                    if category:
                        category_name = category["name"]
        except Exception:
            # اطلاعات تکمیلی نباید جلوی تحویل موفق کانفیگ را بگیرد.
            category_name = None

    for idx, link in enumerate(links, start=1):
        caption = localized(
            build_delivery_caption(product_name, idx, total, order_id, category_name=category_name),
            db, user_tg_id,
        )

        try:
            qr_photo = _build_qr_photo(link, db=db)
            await bot.send_photo(user_tg_id, qr_photo, caption=caption)
        except Exception:
            # اگر ساخت/ارسال QR به هر دلیلی ناموفق بود، حداقل متن اطلاعات برای کاربر ارسال شود
            await bot.send_message(user_tg_id, localized(caption, db, user_tg_id))

        if sub_link_on:
            await bot.send_message(
                user_tg_id,
                localized(f"🔗 لینک اشتراک شما (برای کپی):\n`{link}`", db, user_tg_id),
                parse_mode="Markdown",
            )
            alternates = await asyncio.to_thread(db.get_alternate_sub_urls, link) if db is not None else []
            if alternates:
                await bot.send_message(
                    user_tg_id,
                    localized("🔁 لینک‌های جایگزین (اگر لینک بالا باز نشد):\n", db, user_tg_id) + "\n".join(f"`{u}`" for u in alternates),
                    parse_mode="Markdown",
                )

        if individual_on and link.startswith(("http://", "https://")):
            try:
                individual_links = await fetch_individual_links(link)
            except Exception:
                individual_links = []
            if individual_links:
                await _send_individual_configs(bot, user_tg_id, individual_links, db=db)

    if final_price is not None:
        await bot.send_message(user_tg_id, localized(build_summary_text(final_price, total), db, user_tg_id))

    post_text = get_post_delivery_text(db)
    if post_text:
        try:
            await bot.send_message(user_tg_id, post_text)
        except Exception:
            pass

    if db is not None:
        try:
            import tutorial
            await tutorial.send_device_picker(bot, user_tg_id, db)
        except Exception:
            pass
