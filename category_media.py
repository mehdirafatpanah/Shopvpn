# -*- coding: utf-8 -*-
"""رسانه‌ی توضیحات دسته‌بندی/زیردسته (عکس، ویدیو، ویس، فایل، موزیک، گیف).

رسانه‌ها به‌صورت JSON در ستون categories.description_media ذخیره می‌شوند:
[{"type": "photo", "file_id": "..."}, ...]
file_id مخصوص همان بات است (بات اصلی یا بات نماینده)؛ چون دیتابیس هر بات جداست،
هر دسته همیشه با بات خودش ارسال می‌شود.
"""
import json
import logging

logger = logging.getLogger(__name__)

MAX_ITEMS = 10
CAPTION_LIMIT = 1024
# انواعی که تلگرام اجازه‌ی گروه‌کردن (آلبوم) آن‌ها را می‌دهد
_ALBUM_TYPES = ("photo", "video", "document", "audio")
# گروه‌های سازگار برای آلبوم: عکس/ویدیو با هم، سند و موزیک هرکدام جدا
_ALBUM_GROUP = {"photo": "visual", "video": "visual", "document": "document", "audio": "audio"}
TYPE_LABELS = {
    "photo": "🖼 عکس", "video": "🎬 ویدیو", "animation": "🎞 گیف", "voice": "🎙 ویس",
    "audio": "🎵 موزیک", "document": "📎 فایل", "video_note": "⏺ ویدیو‌مسیج",
}


def parse(raw) -> list:
    """رشته‌ی JSON ذخیره‌شده را به لیست آیتم‌های معتبر تبدیل می‌کند."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("type") in TYPE_LABELS and item.get("file_id"):
            out.append({"type": item["type"], "file_id": str(item["file_id"])})
    return out[:MAX_ITEMS]


def serialize(items) -> str:
    items = parse(items)
    return json.dumps(items, ensure_ascii=False) if items else ""


def item_from_message(message):
    """از یک پیام تلگرام، آیتم رسانه (یا None اگر رسانه ندارد) را درمی‌آورد."""
    if getattr(message, "photo", None):
        return {"type": "photo", "file_id": message.photo[-1].file_id}
    for kind in ("video", "animation", "voice", "audio", "video_note", "document"):
        obj = getattr(message, kind, None)
        if obj is not None:
            return {"type": kind, "file_id": obj.file_id}
    return None


def from_messages(messages):
    """لیست پیام‌ها (تک‌پیام یا آلبوم) → (آیتم‌های رسانه, متن/کپشن)."""
    items, caption = [], ""
    for m in messages:
        it = item_from_message(m)
        if it:
            items.append(it)
        text = (getattr(m, "caption", None) or getattr(m, "text", None) or "").strip()
        if text and not caption:
            caption = text
    return items[:MAX_ITEMS], caption


def summary(items) -> str:
    """مثلاً «۲ عکس، ۱ ویس» برای نمایش به ادمین."""
    items = parse(items)
    if not items:
        return ""
    counts = {}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    return "، ".join(f"{TYPE_LABELS[t]} ×{n}" for t, n in counts.items())


async def _send_one(bot, chat_id, item, caption, parse_mode_kw):
    kind, fid = item["type"], item["file_id"]
    cap = {"caption": caption, **parse_mode_kw} if caption else {}
    if kind == "photo":
        return await bot.send_photo(chat_id, fid, **cap)
    if kind == "video":
        return await bot.send_video(chat_id, fid, **cap)
    if kind == "animation":
        return await bot.send_animation(chat_id, fid, **cap)
    if kind == "voice":
        return await bot.send_voice(chat_id, fid, **cap)
    if kind == "audio":
        return await bot.send_audio(chat_id, fid, **cap)
    if kind == "video_note":
        return await bot.send_video_note(chat_id, fid)
    return await bot.send_document(chat_id, fid, **cap)


async def send_media(bot, chat_id: int, items, caption: str = "") -> tuple:
    """رسانه‌ها را می‌فرستد. caption فقط روی اولین پیام می‌رود.

    برمی‌گرداند: (message_id های ارسال‌شده, آیا کپشن واقعاً همراه رسانه رفت؟)
    اگر کپشن ارسال نشد (ویدیو‌مسیج یا خطا)، فراخواننده باید متن را جدا بفرستد.
    """
    items = parse(items)
    caption = caption if caption and len(caption) <= CAPTION_LIMIT else ""
    sent_ids, caption_sent = [], False
    if not items:
        return sent_ids, caption_sent

    from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

    async def attempt(fn, cap_text):
        try:
            return await fn({}, cap_text)
        except Exception:
            if cap_text:  # شاید خطای HTML کپشن بود؛ بدون پارس‌مود دوباره تلاش کن
                return await fn({"parse_mode": None}, cap_text)
            raise

    # گروه‌بندی آیتم‌های پشت‌سرهم که سازگار با آلبوم هستند
    i = 0
    first = True
    while i < len(items):
        it = items[i]
        group = [it]
        if it["type"] in _ALBUM_TYPES:
            j = i + 1
            while j < len(items) and items[j]["type"] in _ALBUM_TYPES and \
                    _ALBUM_GROUP[items[j]["type"]] == _ALBUM_GROUP[it["type"]]:
                group.append(items[j])
                j += 1
        cap_here = caption if first else ""
        try:
            if len(group) > 1:
                async def send_album(pm, cap_text, group=group):
                    media = []
                    for k, g in enumerate(group):
                        kw = {"caption": cap_text, **pm} if (k == 0 and cap_text) else {}
                        cls = {"photo": InputMediaPhoto, "video": InputMediaVideo,
                               "document": InputMediaDocument, "audio": InputMediaAudio}[g["type"]]
                        media.append(cls(media=g["file_id"], **kw))
                    return await bot.send_media_group(chat_id, media)
                msgs = await attempt(send_album, cap_here)
                sent_ids.extend(m.message_id for m in msgs)
            else:
                async def send_single(pm, cap_text, it=it):
                    return await _send_one(bot, chat_id, it, cap_text, pm)
                msg = await attempt(send_single, cap_here)
                sent_ids.append(msg.message_id)
            if first and cap_here and it["type"] != "video_note":
                caption_sent = True
        except Exception:
            logger.exception("ارسال رسانه‌ی توضیحات دسته ناموفق بود (type=%s)", it["type"])
            break
        first = False
        i += len(group)
    return sent_ids, caption_sent
