#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
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
import html as html_lib
import logging
import math
import os
import re
import time
import urllib.parse
from datetime import datetime
from io import BytesIO

import qrcode

logger = logging.getLogger(__name__)

import dedicated_sub
from aiogram import Bot
from aiogram.types import BufferedInputFile

import config
from jalali import to_jalali_str
from sub_info import fetch_individual_links, fetch_sub_info, _CONFIG_SCHEMES
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
QR_PANEL_RATIO = 0.62       # نسبت عرض کادر سفید حامل QR به کل تصویر‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
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
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def save_qr_background(source_path: str) -> None:
    """تصویر آپلودشده توسط ادمین (هر فرمتی) را می‌خواند، به RGB تبدیل و به‌صورت
    یک PNG ثابت ذخیره می‌کند تا همیشه یک مسیر واحد و قابل‌پیش‌بینی داشته باشیم."""
    from PIL import Image
    with Image.open(source_path) as img:
        img = img.convert("RGB")
        img.save(QR_BACKGROUND_PATH, format="PNG")


QR_BACKGROUND_MAX_BYTES = 8 * 1024 * 1024
QR_BACKGROUND_MIN_SIDE = 300


def save_qr_background_bytes(data: bytes) -> None:
    """مثل مسیر آپلود داخل بات (handlers_admin.on_qr_background_photo)، ولی از روی بایت‌ها؛
    برای پنل وب و مینی‌اپ. در صورت مشکل ValueError با پیام فارسی می‌دهد."""
    import tempfile
    from io import BytesIO as _BytesIO
    from PIL import Image
    if not data:
        raise ValueError(tr("فایلی ارسال نشد."))
    if len(data) > QR_BACKGROUND_MAX_BYTES:
        raise ValueError(tr("حجم تصویر نباید بیشتر از ۸ مگابایت باشد."))
    try:
        with Image.open(_BytesIO(data)) as probe:
            probe.verify()
        with Image.open(_BytesIO(data)) as probe:
            width, height = probe.size
    except Exception:
        raise ValueError(tr("فایل تصویر سالم نیست؛ یک JPG یا PNG بفرستید."))
    if width < QR_BACKGROUND_MIN_SIDE or height < QR_BACKGROUND_MIN_SIDE:
        raise ValueError(tr("ابعاد تصویر خیلی کوچک است (حداقل ۳۰۰×۳۰۰؛ ۵۰۰×۵۰۰ یا بیشتر پیشنهاد می‌شود)."))
    with tempfile.TemporaryDirectory(prefix="qr_bg_") as tmp_dir:
        tmp_path = os.path.join(tmp_dir, "uploaded")
        with open(tmp_path, "wb") as f:
            f.write(data)
        save_qr_background(tmp_path)


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


def _post_delivery_media_for_prefix(db, prefix: str):
    """Return (source chat, ordered message ids); accepts legacy single-id settings."""
    import json
    chat_id = (db.get_setting(prefix + "_media_chat_id", "") or "").strip()
    raw_ids = (db.get_setting(prefix + "_media_message_ids", "") or "").strip()
    legacy_id = (db.get_setting(prefix + "_media_message_id", "") or "").strip()
    try:
        ids = json.loads(raw_ids) if raw_ids else ([int(legacy_id)] if legacy_id.isdigit() else [])
    except Exception:
        ids = [int(legacy_id)] if legacy_id.isdigit() else []
    ids = [int(x) for x in ids if str(x).lstrip("-").isdigit()]
    if chat_id and chat_id.lstrip("-").isdigit() and ids:
        return int(chat_id), ids
    return None


def get_post_delivery_media(db, is_test: bool = False):
    """پیام چندرسانه‌ای ذخیره‌شده؛ متن اختصاصی تست بر رسانه عمومی اولویت دارد."""
    if db is None:
        return None
    if is_test:
        test_media = _post_delivery_media_for_prefix(db, "test_post_delivery")
        if test_media:
            return test_media
        if (db.get_setting("test_post_delivery_text", "") or "").strip():
            return None
    return _post_delivery_media_for_prefix(db, "post_delivery_custom")


def get_post_delivery_text(db, is_test: bool = False) -> str:
    """متن دلخواه ادمین؛ رسانه‌ی تنظیم‌شده متن را از پیام اصلی کپی می‌کند."""
    if db is None:
        return ""
    if is_test:
        if _post_delivery_media_for_prefix(db, "test_post_delivery"):
            return ""
        test_text = (db.get_setting("test_post_delivery_text", "") or "").strip()
        if test_text:
            return test_text
    if _post_delivery_media_for_prefix(db, "post_delivery_custom"):
        return ""
    return (db.get_setting("post_delivery_custom_text", "") or "").strip()


# -----------------------------------------------------------------------
# قالب جدید پیام تحویل سفارش (یک پیام واحد: عکس QR + کپشن)
#
#   سفارش جدید شما 😍
#   ┃ اطلاعات سرویس: پروتکل / نام سرویس / حجم / مدت‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
#   ┃ لینک های اتصال: config / subscription
#   با لمس کردن هر یک از لینک ها، خودکار کپی میشود
#
# هر لینک داخل <code> است تا با یک لمس کپی شود. سقف کپشن تلگرام ۱۰۲۴ کاراکتر
# است؛ اگر لینک‌ها (مثلاً چند کانفیگ داخل یک اشتراک) جا نشدند، عکس QR فقط با
# بلوک «اطلاعات سرویس» ارسال می‌شود و بلوک «لینک های اتصال» بلافاصله به‌صورت
# پیام بعدی (با همان ظاهر) می‌آید. پارس‌مود همه‌جا HTML است.
# -----------------------------------------------------------------------
CAPTION_LIMIT = 1024
CHUNK_LIMIT = 3800


def _h(value) -> str:
    return html_lib.escape(str(value), quote=False)


def _visible_len(markup: str) -> int:
    """طول متنِ دیده‌شده (بعد از حذف تگ‌ها و decode شدن &amp; و...) - همان چیزی که تلگرام برای سقف کپشن می‌شمارد."""
    return len(html_lib.unescape(re.sub(r"<[^>]+>", "", markup)))


def strip_html(markup: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", markup))


def _format_volume(total_bytes):
    if not total_bytes or total_bytes <= 0:
        return "نامحدود"
    gb = total_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{round(gb, 2):g} گیگ"
    return f"{round(total_bytes / (1024 ** 2)):g} مگ"


def _format_duration(expire_ts):
    if not expire_ts:
        return "نامحدود"
    remaining = expire_ts - time.time()
    if remaining <= 0:
        return None
    return f"{max(1, math.ceil(remaining / 86400))} روز"


def _protocol_of(uri):
    if not uri or "://" not in uri:
        return None
    scheme = uri.split("://", 1)[0].lower()
    return {"hy2": "hysteria2"}.get(scheme, scheme)


def _remark_of(uri):
    if not uri or "#" not in uri:
        return None
    frag = urllib.parse.unquote(uri.rsplit("#", 1)[1]).strip()
    return frag or None


async def collect_service_info(link: str, product_name: str = "") -> dict:
    """مشخصات سرویس را مستقیماً از روی خودِ لینک اشتراک می‌خواند (مستقل از نوع پنل):
    پروتکل و نام از کانفیگ‌های داخل ساب، حجم و مدت از هدر subscription-userinfo.
    هر مقداری که پیدا نشود None می‌ماند و در پیام نمایش داده نمی‌شود (هیچ‌وقت عدد حدسی نشان نمی‌دهیم)."""
    is_sub = link.startswith(("http://", "https://"))
    configs, info = [], {}
    if is_sub:
        res = await asyncio.gather(
            fetch_individual_links(link), fetch_sub_info(link), return_exceptions=True,
        )
        configs = res[0] if isinstance(res[0], list) else []
        info = res[1] if isinstance(res[1], dict) and res[1].get("ok") else {}
    elif link.startswith(_CONFIG_SCHEMES):
        configs = [link]

    first = configs[0] if configs else None
    name = _remark_of(first) or (info.get("title") or "").strip() or (product_name or "").strip() or None
    return {
        "is_sub": is_sub,
        "sub_url": link if is_sub else None,
        "configs": configs,
        "protocol": _protocol_of(first),
        "name": name,
        "volume": _format_volume(info.get("total")) if info else None,
        "duration": _format_duration(info.get("expire")) if info else None,
    }


def build_delivery_message(svc: dict, idx: int, total: int, sub_link_on: bool,
                           individual_on: bool, alternates=None, L=None, header_text=None):
    """خروجی: (caption_html, [extra_html_messages]). L تابع ترجمه‌ی برچسب‌های ثابت است."""
    L = L or (lambda t: t)
    alternates = alternates or []

    header = _h(header_text) if header_text else f"{L('سفارش جدید شما')} 😍"
    if total > 1:
        header += f" ({idx}/{total})"

    rows = [
        ("📡", "پروتکل", svc.get("protocol")),
        ("🔮", "نام سرویس", svc.get("name")),
        ("🔋", "حجم سرویس", L(svc["volume"]) if svc.get("volume") else None),
        ("⏰", "مدت سرویس", L(svc["duration"]) if svc.get("duration") else None),
    ]
    info_lines = [f"{emoji} {L(label)}: {_h(value)}" for emoji, label, value in rows if value]
    info_block = f"<blockquote><b>{L('اطلاعات سرویس')}</b>\n" + "\n".join(info_lines) + "</blockquote>"

    link_lines = []
    if svc["is_sub"]:
        if individual_on:
            link_lines += [f"💝 config : <code>{_h(c)}</code>" for c in svc["configs"]]
        if sub_link_on:
            link_lines.append(f"🌐 subscription : <code>{_h(svc['sub_url'])}</code>")
            link_lines += [f"🔁 subscription : <code>{_h(u)}</code>" for u in alternates]
    elif sub_link_on or individual_on:
        for c in svc["configs"]:
            link_lines.append(f"💝 config : <code>{_h(c)}</code>")

    title = f"<b>{L('لینک های اتصال')}</b>"
    hint = L("با لمس کردن هر یک از لینک ها، خودکار کپی میشود")

    if not link_lines:
        return f"{header}\n\n{info_block}", []

    full = f"{header}\n\n{info_block}\n\n<blockquote>{title}\n\n" + "\n\n".join(link_lines) + f"</blockquote>\n\n{hint}"
    if _visible_len(full) <= CAPTION_LIMIT:
        return full, []

    # جا نشد: کپشنِ عکس فقط اطلاعات سرویس، و لینک‌ها در پیام(های) بعدی
    chunks, cur, cur_len = [], [], 0
    for line in link_lines:
        ln = _visible_len(line) + 2
        if cur and cur_len + ln > CHUNK_LIMIT:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += ln
    if cur:
        chunks.append(cur)
    extras = [f"<blockquote>{title}\n\n" + "\n\n".join(c) + "</blockquote>" for c in chunks]
    extras[-1] += f"\n\n{hint}"
    return f"{header}\n\n{info_block}", extras


async def prepare_delivery(link: str, product_name: str, idx: int, total: int,
                           db=None, user_tg_id: int = None, header_text=None, panel_type: str = ""):
    """مرحله‌ی مشترک بین بات (aiogram) و پنل وب: جمع‌آوری مشخصات و ساخت کپشن/پیام‌های اضافه."""
    sub_link_on, individual_on = _delivery_flags(db)
    if db is not None and user_tg_id is not None:
        L = lambda t: localized(t, db, user_tg_id)
    else:
        L = lambda t: t
    svc = await collect_service_info(link, product_name)
    alternates = []
    if db is not None and svc["is_sub"]:
        # ساب اختصاصی: به‌جای آدرس پنل، لینک روی دامنه‌ی خودِ فروشگاه نمایش داده می‌شود
        dedicated = await asyncio.to_thread(dedicated_sub.dedicated_link_for_upstream, db, link)
        if dedicated != link:
            svc["sub_url"] = dedicated
    if db is not None and sub_link_on and svc["is_sub"] and svc["sub_url"] == link:
        try:
            alternates = await asyncio.to_thread(db.get_alternate_sub_urls, link)
        except Exception:
            alternates = []
    # Per-provider custom delivery text. Empty template keeps the full legacy rich message.
    if db is not None:
        provider_key = re.sub(r"[^a-z0-9_]+", "_", str(panel_type or svc.get("protocol") or "default").lower()).strip("_") or "default"
        template = (await asyncio.to_thread(db.get_setting, f"delivery_message_template_{provider_key}", "") or "").strip()
        if not template:
            template = (await asyncio.to_thread(db.get_setting, "delivery_message_template_default", "") or "").strip()
        if template:
            safe_values = {
                "product_name": product_name or "", "protocol": svc.get("protocol") or "",
                "service_name": svc.get("name") or "", "volume": svc.get("volume") or "",
                "duration": svc.get("duration") or "", "index": idx, "total": total,
                "subscription_url": svc.get("sub_url") or "", "config_links": "\n".join(svc.get("configs") or []),
            }
            try:
                custom = template.format_map({k: html_lib.escape(str(v)) for k, v in safe_values.items()})
                if custom.strip():
                    return custom, []
            except (KeyError, ValueError, IndexError):
                logger.warning("قالب تحویل %s نامعتبر است؛ از قالب پیش‌فرض استفاده شد.", provider_key)
    return build_delivery_message(svc, idx, total, sub_link_on, individual_on, alternates, L, header_text)


async def _send_html(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception:
        try:
            await bot.send_message(chat_id, strip_html(text))
        except Exception:
            pass


async def notify_delivered_subscription(bot_token: str, db, user_tg_id: int, product_name: str,
                                         links, final_price=None, order_id=None) -> None:
    """ثبت تحویل در تاپیک اختصاصی؛ از مسیر بات و پنل وب مشترک استفاده می‌شود."""
    if db is None:
        return
    try:
        import report_router
        from report_router import build_delivered_subscription_event
        link = links[0] if isinstance(links, (list, tuple)) and links else (links or "")
        svc = await collect_service_info(link, product_name) if link else {}
        user = await asyncio.to_thread(db.get_user, int(user_tg_id))
        order = await asyncio.to_thread(db.get_order, int(order_id)) if order_id else None
        product = await asyncio.to_thread(db.get_product, int(order["product_id"])) if order else None
        server_id = product["provision_server_id"] if product and "provision_server_id" in product.keys() else None
        server = await asyncio.to_thread(db.get_panel_server, int(server_id)) if server_id else None
        panel_type = server["panel_type"] if server else ""
        panel_name = server["name"] if server else panel_type
        event = build_delivered_subscription_event(
            user_id=user_tg_id, username=(user["username"] if user else "") or "",
            account_name=(user["first_name"] if user else "") or "", product_name=product_name,
            panel_name=panel_name or svc.get("protocol") or "نامشخص",
            volume=svc.get("volume") or "", duration=svc.get("duration") or "",
            order_id=order_id, amount=final_price,
            subscription_details=svc.get("sub_url") or ", ".join(svc.get("configs") or []),
        )
        await report_router.notify_raw(bot_token, db, "delivered_stock", event, senior_only=False, parse_mode="HTML")
    except Exception:
        logger.exception("ثبت گزارش اشتراک تحویل‌شده ناموفق بود (user=%s, order=%s)", user_tg_id, order_id)


async def deliver_config_to_user(
    bot: Bot,
    user_tg_id: int,
    product_name: str,
    links,
    final_price: int = None,
    order_id: int = None,
    db=None,
    header_text=None,
    is_test: bool = False,
) -> None:
    """
    ارسال کانفیگ(های) خریداری‌شده به کاربر در قالب یک پیام: عکس QR + کپشن
    («سفارش جدید شما» / «اطلاعات سرویس» / «لینک های اتصال»)؛ جزئیات در بالای همین بخش.
    links می‌تواند یک لینک تکی (str) یا لیستی از لینک‌ها باشد (خرید با تعداد بیشتر از ۱)؛
    در حالت لیست، برای هر کانفیگ یک پیام جدا (با شماره‌ی خودش) ارسال می‌شود.

    تنظیمات deliver_sub_link_enabled / deliver_individual_configs_enabled همچنان کنترل
    می‌کنند که خطوط «subscription» و «config» در بلوک لینک‌ها بیایند یا نه.

    (نسخه‌ی aiogram - برای فراخوانی از داخل خودِ بات. برای پنل وب مستقل از
    admin_panel.config_delivery_web.deliver_config_to_user_web استفاده کن.)
    """
    if db is not None and order_id is not None:
        from gift_card_handlers import deliver_gift_order
        if await deliver_gift_order(bot, db, order_id):
            return
    if isinstance(links, str):
        links = [links]
    total = len(links)
    delivery_panel_type = ""
    delivery_panel_name = ""
    if db is not None and order_id:
        try:
            order_row = await asyncio.to_thread(db.get_order, int(order_id))
            product_row = await asyncio.to_thread(db.get_product, int(order_row["product_id"])) if order_row else None
            server_id = product_row["provision_server_id"] if product_row and "provision_server_id" in product_row.keys() else None
            server_row = await asyncio.to_thread(db.get_panel_server, int(server_id)) if server_id else None
            if server_row:
                delivery_panel_type = server_row["panel_type"] or ""
                delivery_panel_name = server_row["name"] or delivery_panel_type
        except Exception:
            logger.debug("تشخیص نوع پنل برای قالب تحویل ناموفق بود.", exc_info=True)

    for idx, link in enumerate(links, start=1):
        caption, extras = await prepare_delivery(link, product_name, idx, total, db=db, user_tg_id=user_tg_id, header_text=header_text, panel_type=delivery_panel_type)

        try:
            qr_link = await asyncio.to_thread(dedicated_sub.dedicated_link_for_upstream, db, link) if db is not None else link
            qr_photo = _build_qr_photo(qr_link, db=db)
            await bot.send_photo(user_tg_id, qr_photo, caption=caption, parse_mode="HTML")
        except Exception:
            # اگر ساخت/ارسال QR به هر دلیلی ناموفق بود، حداقل متن اطلاعات برای کاربر ارسال شود
            await _send_html(bot, user_tg_id, caption)

        for extra in extras:
            await _send_html(bot, user_tg_id, extra)

    if db is not None and not is_test:
        await notify_delivered_subscription(bot.token, db, user_tg_id, product_name, links, final_price, order_id)

    if final_price is not None:
        await bot.send_message(user_tg_id, localized(build_summary_text(final_price, total), db, user_tg_id))

    post_media = get_post_delivery_media(db, is_test=is_test)
    if post_media:
        try:
            from telegram_media import copy_messages as _copy_media_messages
            await _copy_media_messages(bot, user_tg_id, post_media[0], post_media[1])
        except Exception:
            logger.warning("کپی پیام چندرسانه‌ای بعد از تحویل ناموفق بود.", exc_info=True)
            post_text = get_post_delivery_text(db, is_test=is_test)
            if post_text:
                try: await bot.send_message(user_tg_id, post_text)
                except Exception: pass
    else:
        post_text = get_post_delivery_text(db, is_test=is_test)
        if post_text:
            try: await bot.send_message(user_tg_id, post_text)
            except Exception: pass

    if db is not None:
        try:
            import tutorial
            await tutorial.send_device_picker(bot, user_tg_id, db)
        except Exception:
            pass
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
