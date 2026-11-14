# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""ارسال پیام ساده به کاربر از طریق Bot API؛ برای اطلاع‌رسانی تایید/رد سفارش
و شارژ کیف پول وقتی این کارها از داخل پنل وب مستقل (نه خودِ بات) انجام می‌شوند."""

import os
import json
import logging

import aiohttp

logger = logging.getLogger("admin_panel.telegram_notify")


async def get_me(bot_token: str):
    """اطلاعات بات (از جمله username) از طریق Bot API خام؛ برای ساخت لینک
    resref_<id> نمایندگیِ لینک‌محور از داخل پنل وب مستقل (بدون aiogram)."""
    if not bot_token:
        return None
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("result")
    except Exception:
        logger.exception("getMe ناموفق بود")
        return None
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


async def copy_message(bot_token: str, chat_id: int, from_chat_id: int, message_id: int) -> bool:
    """کپی پیام ذخیره‌شده (متن، عکس، استیکر و سایر رسانه‌ها) بین گفت‌وگوها."""
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/copyMessage"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"chat_id": chat_id, "from_chat_id": from_chat_id,
                                               "message_id": message_id},
                                    timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json()
                return resp.status == 200 and bool(data.get("ok"))
    except Exception:
        logger.exception("کپی پیام تلگرام به %s ناموفق بود", chat_id)
        return False


async def send_message(bot_token: str, chat_id: int, text: str, parse_mode: str = None, reply_markup: dict = None) -> bool:
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                return resp.status == 200
    except Exception:
        logger.exception("ارسال پیام تلگرام به %s ناموفق بود", chat_id)
        return False


async def send_photo(
    bot_token: str,
    chat_id: int,
    photo_bytes: bytes,
    filename: str = "photo.png",
    caption: str = "",
    parse_mode: str = None,
    content_type: str = "image/png",
) -> bool:
    """ارسال عکس (مثلاً QR کد کانفیگ) به کاربر تلگرامی، بدون وابستگی به aiogram."""
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if caption:
            form.add_field("caption", caption)
            if parse_mode:
                form.add_field("parse_mode", parse_mode)
        form.add_field("photo", photo_bytes, filename=filename, content_type=content_type)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                return resp.status == 200
    except Exception:
        logger.exception("ارسال عکس تلگرام به %s ناموفق بود", chat_id)
        return False


async def upload_photo_get_file_id(
    bot_token: str,
    chat_id: int,
    photo_bytes: bytes,
    filename: str = "photo.jpg",
    content_type: str = "image/jpeg",
) -> str | None:
    """عکس را یک‌بار برای ادمین می‌فرستد تا file_id تلگرام آن گرفته شود، سپس همان پیام را
    پاک می‌کند. file_id مخصوص همین بات است و با پاک‌شدن پیام باطل نمی‌شود؛ ربات و مینی‌اپ
    عکس دسته‌بندی را با همین file_id نشان می‌دهند. خروجی None یعنی ناموفق."""
    if not bot_token or not chat_id:
        return None
    base = f"https://api.telegram.org/bot{bot_token}"
    try:
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        form.add_field("disable_notification", "true")
        form.add_field("photo", photo_bytes, filename=filename, content_type=content_type)
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{base}/sendPhoto", data=form, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json()
            if not data.get("ok"):
                logger.warning("آپلود عکس دسته‌بندی به تلگرام ناموفق بود: %s", data.get("description"))
                return None
            result = data["result"]
            file_id = result["photo"][-1]["file_id"]
            try:
                await session.post(f"{base}/deleteMessage", json={"chat_id": chat_id, "message_id": result["message_id"]},
                                   timeout=aiohttp.ClientTimeout(total=10))
            except Exception:
                pass
            return file_id
    except Exception:
        logger.exception("آپلود عکس دسته‌بندی به تلگرام ناموفق بود")
        return None


async def send_voice(
    bot_token: str,
    chat_id: int,
    voice_bytes: bytes,
    filename: str = "voice.ogg",
    caption: str = "",
) -> bool:
    """ارسال ویس از طریق Bot API."""
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendVoice"
    try:
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if caption:
            form.add_field("caption", caption)
        form.add_field("voice", voice_bytes, filename=filename, content_type="audio/ogg")
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                return resp.status == 200
    except Exception:
        logger.exception("ارسال ویس تلگرام به %s ناموفق بود", chat_id)
        return False


_RECEIPT_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif", "pdf": "application/pdf",
}


async def fetch_telegram_file(bot_token: str, file_id: str):
    """دریافت بایت‌های یک فایل تلگرامی (رسید پرداخت کارت‌به‌کارت) با file_id، برای
    نمایش داخل پنل وب مستقل (که خودش نمونه‌ی Bot در اختیار ندارد).
    خروجی: تاپل (bytes, content_type) یا None در صورت هر خطایی."""
    if not bot_token or not file_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.telegram.org/bot{bot_token}/getFile",
                params={"file_id": file_id},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
            if not data.get("ok"):
                return None
            file_path = data["result"]["file_path"]

            async with session.get(
                f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return None
                content = await resp.read()

        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        content_type = _RECEIPT_CONTENT_TYPES.get(ext, "application/octet-stream")
        return content, content_type
    except Exception:
        logger.exception("دریافت فایل رسید از تلگرام ناموفق بود (file_id=%s)", file_id)
        return None


async def send_document_bytes(bot_token: str, chat_id: int, data: bytes, filename: str, caption: str = "") -> bool:
    """ارسال فایل از روی بایت‌ها (مثلاً فایل .conf/.ovpn سرویس) بدون وابستگی به aiogram."""
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if caption:
            form.add_field("caption", caption)
        form.add_field("document", data, filename=filename, content_type="application/octet-stream")
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                return resp.status == 200
    except Exception:
        logger.exception("ارسال فایل تلگرام به %s ناموفق بود", chat_id)
        return False


async def send_sticker(bot_token: str, chat_id: int, sticker_file_id: str) -> bool:
    """ارسال استیکر با file_id (استیکر محصول)؛ file_id باید با همین توکن بات گرفته شده باشد."""
    if not bot_token or not sticker_file_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendSticker"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"chat_id": chat_id, "sticker": sticker_file_id},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                return resp.status == 200
    except Exception:
        logger.exception("ارسال استیکر تلگرام به %s ناموفق بود", chat_id)
        return False


async def send_document(bot_token: str, chat_id: int, file_path: str, caption: str = "") -> bool:
    """ارسال فایل (مثلاً بکاپ دیتابیس) به یک ادمین تلگرامی، بدون وابستگی به aiogram
    (پنل وب یک نمونه‌ی Bot در دسترس ندارد، پس مستقیم با Bot API خام کار می‌کند)."""
    if not bot_token:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if caption:
            form.add_field("caption", caption)
        form.add_field(
            "document", file_bytes,
            filename=os.path.basename(file_path), content_type="application/octet-stream",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                return resp.status == 200
    except Exception:
        logger.exception("ارسال فایل تلگرام به %s ناموفق بود", chat_id)
        return False
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
