# -*- coding: utf-8 -*-
"""کلیدهای سفارشی منوی شیشه‌ای (فقط بات اصلی، فقط منوی Inline).

ادمین از داخل بات (تنظیمات منوی اصلی ← «کلیدهای سفارشی منوی شیشه‌ای») می‌تواند
کلید بسازد. هر کلید یکی از دو حالت را دارد:
  * لینک  : کلید مستقیماً یک آدرس را باز می‌کند.
  * پیام  : با کلیک، یک یا چند پیام ذخیره‌شده (متن، عکس، ویدیو، ویس، استیکر، گیف،
            فایل، موزیک، ویدیو‌مسیج) برای کاربر ارسال می‌شود.
نمایش کلیدها در keyboards.main_menu_inline_kb (custom_menu_rows) انجام می‌شود و
منوی پایین (Reply) هیچ‌وقت آن‌ها را نشان نمی‌دهد.
"""

import asyncio
import logging
import re
from typing import Optional

from aiogram import F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, MessageEntity,
)

from db.custom_menu import MAX_BUTTONS, MAX_PARTS, MAX_TITLE_LEN
from i18n import tr
from states import AdminCustomMenuButton as S

log = logging.getLogger("custom_menu_buttons")

_ALLOWED_SCHEMES = ("http://", "https://", "tg://")
_COLORS = (("", "⚪️ پیش‌فرض"), ("primary", "🔵 آبی"), ("success", "🟢 سبز"), ("danger", "🔴 قرمز"))
_COLOR_LABEL = {k: v for k, v in _COLORS}
_TYPE_LABEL = {"url": "🔗 لینک", "content": "💬 پیام"}


# ---------------------------------------------------------------------------
# ابزارهای خالص (بدون وابستگی به بات؛ قابل تست)
# ---------------------------------------------------------------------------
def normalize_url(raw: str) -> Optional[str]:
    """ورودی ادمین را به یک URL معتبر برای دکمه‌ی inline تبدیل می‌کند؛ نامعتبر → None."""
    value = (raw or "").strip()
    if not value or len(value) > 512 or re.search(r"\s", value):
        return None
    if value.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{4,32}", value):
        return "https://t.me/" + value[1:]
    low = value.lower()
    if low.startswith(_ALLOWED_SCHEMES):
        if low.startswith("tg://") and len(value) <= 5:
            return None
        if low.startswith(("http://", "https://")) and "." not in value.split("//", 1)[1].split("/", 1)[0]:
            return None
        return value
    if re.match(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(/.*)?$", value):
        return "https://" + value
    return None


def extract_part(message: Message) -> Optional[dict]:
    """یک پیام تلگرام را به «بخش» قابل ذخیره (JSON) تبدیل می‌کند؛ پشتیبانی‌نشده → None."""
    def ents(items):
        return [e.model_dump(exclude_none=True) for e in (items or [])]

    if message.text:
        return {"type": "text", "text": message.text, "entities": ents(message.entities)}
    caption = {"text": message.caption or "", "entities": ents(message.caption_entities)}
    if message.photo:
        return {"type": "photo", "file_id": message.photo[-1].file_id, **caption}
    if message.video:
        return {"type": "video", "file_id": message.video.file_id, **caption}
    if message.animation:
        return {"type": "animation", "file_id": message.animation.file_id, **caption}
    if message.voice:
        return {"type": "voice", "file_id": message.voice.file_id, **caption}
    if message.audio:
        return {"type": "audio", "file_id": message.audio.file_id, **caption}
    if message.document:
        return {"type": "document", "file_id": message.document.file_id, **caption}
    if message.sticker:
        return {"type": "sticker", "file_id": message.sticker.file_id, "text": "", "entities": []}
    if message.video_note:
        return {"type": "video_note", "file_id": message.video_note.file_id, "text": "", "entities": []}
    return None


def _entities(items):
    out = []
    for d in items or []:
        try:
            out.append(MessageEntity(**d))
        except Exception:  # entity خراب نباید ارسال کل پیام را خراب کند
            continue
    return out or None


async def send_parts(bot, chat_id: int, parts: list) -> int:
    """بخش‌های ذخیره‌شده را به ترتیب برای چت می‌فرستد؛ تعداد بخش‌های موفق را برمی‌گرداند."""
    sent = 0
    for p in parts or []:
        kind = p.get("type")
        fid = p.get("file_id")
        text = p.get("text") or None
        ents = _entities(p.get("entities"))
        try:
            if kind == "text":
                await bot.send_message(chat_id, p.get("text") or "…", entities=ents, parse_mode=None)
            elif kind == "photo":
                await bot.send_photo(chat_id, fid, caption=text, caption_entities=ents, parse_mode=None)
            elif kind == "video":
                await bot.send_video(chat_id, fid, caption=text, caption_entities=ents, parse_mode=None)
            elif kind == "animation":
                await bot.send_animation(chat_id, fid, caption=text, caption_entities=ents, parse_mode=None)
            elif kind == "voice":
                await bot.send_voice(chat_id, fid, caption=text, caption_entities=ents, parse_mode=None)
            elif kind == "audio":
                await bot.send_audio(chat_id, fid, caption=text, caption_entities=ents, parse_mode=None)
            elif kind == "document":
                await bot.send_document(chat_id, fid, caption=text, caption_entities=ents, parse_mode=None)
            elif kind == "sticker":
                await bot.send_sticker(chat_id, fid)
            elif kind == "video_note":
                await bot.send_video_note(chat_id, fid)
            else:
                continue
            sent += 1
        except TelegramForbiddenError:
            break
        except TelegramBadRequest as exc:
            log.warning("custom menu part failed (%s): %s", kind, exc)
        await asyncio.sleep(0.05)
    return sent


def _summary(btn: dict) -> str:
    if btn["kind"] == "url":
        return btn.get("url") or "—"
    counts = {}
    for p in btn.get("parts") or []:
        counts[p["type"]] = counts.get(p["type"], 0) + 1
    names = {"text": "متن", "photo": "عکس", "video": "ویدیو", "animation": "گیف", "voice": "ویس",
             "audio": "موزیک", "document": "فایل", "sticker": "استیکر", "video_note": "ویدیو‌مسیج"}
    return "، ".join(f"{names.get(k, k)} ×{n}" for k, n in counts.items()) or "—"


# ---------------------------------------------------------------------------
# کیبوردهای پنل ادمین
# ---------------------------------------------------------------------------
def _ib(text, data):
    return InlineKeyboardButton(text=tr(text), callback_data=data)


def list_kb(items: list) -> InlineKeyboardMarkup:
    rows = []
    for b in items:
        mark = "🟢" if b["is_active"] else "🔴"
        icon = "🔗" if b["kind"] == "url" else "💬"
        rows.append([InlineKeyboardButton(text=f"{mark} {icon} {b['title']}"[:64], callback_data=f"adm_cmb_v:{b['id']}")])
    rows.append([_ib("➕ ساخت کلید جدید", "adm_cmb_add")])
    rows.append([_ib("⬅️ بازگشت", "adm_main_menu_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def view_kb(btn: dict) -> InlineKeyboardMarkup:
    i = btn["id"]
    rows = [
        [_ib("🔴 غیرفعال کردن" if btn["is_active"] else "🟢 فعال کردن", f"adm_cmb_t:{i}")],
        [_ib("✏️ تغییر نام", f"adm_cmb_rn:{i}"), _ib("🎨 رنگ", f"adm_cmb_col:{i}")],
        [_ib("🔁 ویرایش لینک / پیام", f"adm_cmb_ec:{i}")],
    ]
    if btn["kind"] == "content":
        rows.append([_ib("👁 پیش‌نمایش پیام", f"adm_cmb_pv:{i}")])
    rows.append([_ib("🔼 بالاتر", f"adm_cmb_mv:{i}:u"), _ib("🔽 پایین‌تر", f"adm_cmb_mv:{i}:d")])
    rows.append([_ib("🗑 حذف", f"adm_cmb_del:{i}")])
    rows.append([_ib("⬅️ بازگشت", "adm_cmb")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kind_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_ib("🔗 باز کردن یک لینک", f"{prefix}:url")],
        [_ib("💬 ارسال پیام (متن/عکس/ویس/استیکر/...)", f"{prefix}:content")],
        [_ib("⬅️ انصراف", "adm_cmb_cancel")],
    ])


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_ib("⬅️ انصراف", "adm_cmb_cancel")]])


def done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_ib("✅ تمام، ذخیره کن", "adm_cmb_done")],
        [_ib("⬅️ انصراف", "adm_cmb_cancel")],
    ])


def color_kb(i: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tr(label), callback_data=f"adm_cmb_cs:{i}:{key or 'none'}")]
            for key, label in _COLORS]
    rows.append([_ib("⬅️ بازگشت", f"adm_cmb_v:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_kb(i: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_ib("✅ بله، حذف شود", f"adm_cmb_delok:{i}")],
        [_ib("⬅️ انصراف", f"adm_cmb_v:{i}")],
    ])


# ---------------------------------------------------------------------------
def register(router, db, is_main_bot: bool, full_admin_only, deny_support, replace_admin_view, safe_edit):
    if not is_main_bot:
        return

    def _list_text() -> str:
        inline_on = db.get_setting("main_menu_inline_enabled", "0") == "1"
        text = (
            "🔘 کلیدهای سفارشی منوی شیشه‌ای\n\n"
            "این کلیدها فقط در «منوی شیشه‌ای بالا» نمایش داده می‌شوند و در منوی پایین (Reply) دیده نمی‌شوند.\n"
            "هر کلید می‌تواند یک لینک را باز کند، یا یک یا چند پیام (متن، عکس، ویدیو، ویس، استیکر، فایل و...) را برای کاربر بفرستد."
        )
        if not inline_on:
            text += "\n\n⚠️ منوی شیشه‌ای فعلاً غیرفعال است؛ تا فعال نکنی این کلیدها به کاربران نشان داده نمی‌شوند."
        return text

    def _view_text(btn: dict) -> str:
        lines = [
            f"🔘 {btn['title']}",
            "",
            f"نوع: {_TYPE_LABEL.get(btn['kind'], btn['kind'])}",
            f"وضعیت: {'🟢 فعال' if btn['is_active'] else '🔴 غیرفعال'}",
            f"رنگ: {_COLOR_LABEL.get(btn.get('style') or '', '⚪️ پیش‌فرض')}",
            f"محتوا: {_summary(btn)}",
            f"تعداد کلیک: {btn.get('clicks') or 0}",
        ]
        return "\n".join(lines)

    async def _show_list(call: CallbackQuery):
        items = await asyncio.to_thread(db.cm_list)
        await replace_admin_view(call, _list_text(), reply_markup=list_kb(items))

    async def _show_view(call: CallbackQuery, btn_id: int) -> bool:
        btn = await asyncio.to_thread(db.cm_get, btn_id)
        if not btn:
            await call.answer(tr("این کلید دیگر وجود ندارد."), show_alert=True)
            await _show_list(call)
            return False
        await replace_admin_view(call, _view_text(btn), reply_markup=view_kb(btn))
        return True

    async def _msg_view(message: Message, btn_id: int):
        btn = await asyncio.to_thread(db.cm_get, btn_id)
        if btn:
            await message.answer(_view_text(btn), reply_markup=view_kb(btn))

    def _log(admin_id: int, action: str, detail: str):
        try:
            db.log_admin_action(admin_id, action, detail)
        except Exception:
            pass

    # ----- لیست / مشاهده -----------------------------------------------------
    @router.callback_query(F.data == "adm_cmb")
    async def cb_cmb_list(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        await _show_list(call)
        await call.answer()

    @router.callback_query(F.data == "adm_cmb_cancel")
    async def cb_cmb_cancel(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        await state.clear()
        edit_id = data.get("cm_edit_id")
        if edit_id:
            await _show_view(call, int(edit_id))
        else:
            await _show_list(call)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_cmb_v:"))
    async def cb_cmb_view(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        if await _show_view(call, int(call.data.split(":")[1])):
            await call.answer()

    # ----- ساخت کلید جدید ----------------------------------------------------
    @router.callback_query(F.data == "adm_cmb_add")
    async def cb_cmb_add(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        if await asyncio.to_thread(db.cm_count) >= MAX_BUTTONS:
            await call.answer(tr(f"حداکثر {MAX_BUTTONS} کلید سفارشی مجاز است."), show_alert=True)
            return
        await state.clear()
        await state.set_state(S.waiting_title)
        await safe_edit(call, tr(f"✏️ متن روی کلید را بفرست (حداکثر {MAX_TITLE_LEN} کاراکتر).\nمثلاً: 📢 کانال ما"),
                        reply_markup=cancel_kb())
        await call.answer()

    @router.message(S.waiting_title)
    async def msg_cmb_title(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            await state.clear()
            return
        title = (message.text or "").strip()
        if not title or len(title) > MAX_TITLE_LEN:
            await message.answer(tr(f"❌ متن باید بین ۱ تا {MAX_TITLE_LEN} کاراکتر باشد. دوباره بفرست."),
                                 reply_markup=cancel_kb())
            return
        await state.update_data(cm_title=title)
        await message.answer(tr("این کلید چه کاری انجام بدهد؟"), reply_markup=kind_kb("adm_cmb_kind"))

    @router.callback_query(F.data.startswith("adm_cmb_kind:"))
    async def cb_cmb_kind(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        if not data.get("cm_title"):
            await call.answer(tr("درخواست منقضی شد؛ دوباره شروع کن."), show_alert=True)
            return
        kind = call.data.split(":")[1]
        if kind == "url":
            await state.set_state(S.waiting_url)
            await safe_edit(call, tr("🔗 لینک را بفرست.\nمثلاً: https://t.me/yourchannel یا @yourchannel"),
                            reply_markup=cancel_kb())
        else:
            await state.set_state(S.waiting_content)
            await state.update_data(cm_parts=[])
            await safe_edit(call, _content_prompt(0), reply_markup=cancel_kb())
        await call.answer()

    def _content_prompt(n: int) -> str:
        return (
            f"💬 پیام‌هایی را که می‌خواهی با کلیک نمایش داده شود بفرست (حداکثر {MAX_PARTS} پیام).\n"
            "متن، عکس، ویدیو، گیف، ویس، موزیک، فایل، استیکر و ویدیو‌مسیج پشتیبانی می‌شود؛ "
            "هر پیام یک بخش جدا حساب می‌شود و به همین ترتیب ارسال خواهد شد.\n\n"
            f"دریافت‌شده تا اینجا: {n}\nوقتی همه را فرستادی «تمام» را بزن."
        )

    @router.message(S.waiting_url)
    async def msg_cmb_url(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            await state.clear()
            return
        url = normalize_url(message.text or "")
        if not url:
            await message.answer(tr("❌ لینک معتبر نیست. مثل https://example.com یا @username بفرست."),
                                 reply_markup=cancel_kb())
            return
        data = await state.get_data()
        title = data.get("cm_title")
        await state.clear()
        if not title:
            await message.answer(tr("❌ درخواست منقضی شد؛ دوباره از منو اقدام کن."))
            return
        new_id = await asyncio.to_thread(db.cm_create, title, "url", url)
        _log(message.from_user.id, "cmb_create", f"کلید لینک #{new_id}: {title}")
        await message.answer(tr("✅ کلید ساخته شد."))
        await _msg_view(message, new_id)

    async def _collect_part(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            await state.clear()
            return
        part = extract_part(message)
        if not part:
            await message.answer(tr("❌ این نوع پیام پشتیبانی نمی‌شود. متن، عکس، ویدیو، ویس، استیکر یا فایل بفرست."),
                                 reply_markup=done_kb())
            return
        data = await state.get_data()
        parts = list(data.get("cm_parts") or [])
        if len(parts) >= MAX_PARTS:
            await message.answer(tr(f"❌ حداکثر {MAX_PARTS} پیام مجاز است. «تمام» را بزن."), reply_markup=done_kb())
            return
        parts.append(part)
        await state.update_data(cm_parts=parts)
        await message.answer(tr(f"✅ پیام {len(parts)} دریافت شد. پیام بعدی را بفرست یا «تمام» را بزن."),
                             reply_markup=done_kb())

    @router.message(S.waiting_content)
    async def msg_cmb_content(message: Message, state: FSMContext):
        await _collect_part(message, state)

    @router.message(S.waiting_new_content)
    async def msg_cmb_new_content(message: Message, state: FSMContext):
        await _collect_part(message, state)

    @router.callback_query(F.data == "adm_cmb_done")
    async def cb_cmb_done(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        data = await state.get_data()
        parts = list(data.get("cm_parts") or [])
        if not parts:
            await call.answer(tr("هنوز هیچ پیامی نفرستادی."), show_alert=True)
            return
        edit_id = data.get("cm_edit_id")
        title = data.get("cm_title")
        await state.clear()
        if edit_id:
            await asyncio.to_thread(db.cm_update, int(edit_id), kind="content", parts=parts, url="")
            _log(call.from_user.id, "cmb_edit", f"محتوای کلید #{edit_id} تغییر کرد")
            btn_id = int(edit_id)
        elif title:
            btn_id = await asyncio.to_thread(db.cm_create, title, "content", "", parts)
            _log(call.from_user.id, "cmb_create", f"کلید پیام #{btn_id}: {title}")
        else:
            await call.answer(tr("درخواست منقضی شد؛ دوباره شروع کن."), show_alert=True)
            return
        await _show_view(call, btn_id)
        await call.answer(tr("✅ ذخیره شد."))

    # ----- ویرایش ------------------------------------------------------------
    @router.callback_query(F.data.startswith("adm_cmb_t:"))
    async def cb_cmb_toggle(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        btn_id = int(call.data.split(":")[1])
        btn = await asyncio.to_thread(db.cm_get, btn_id)
        if not btn:
            await call.answer(tr("این کلید دیگر وجود ندارد."), show_alert=True)
            return
        await asyncio.to_thread(db.cm_update, btn_id, is_active=0 if btn["is_active"] else 1)
        await _show_view(call, btn_id)
        await call.answer(tr("✅ اعمال شد."))

    @router.callback_query(F.data.startswith("adm_cmb_rn:"))
    async def cb_cmb_rename(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        btn_id = int(call.data.split(":")[1])
        await state.clear()
        await state.set_state(S.waiting_new_title)
        await state.update_data(cm_edit_id=btn_id)
        await safe_edit(call, tr(f"✏️ متن جدید کلید را بفرست (حداکثر {MAX_TITLE_LEN} کاراکتر)."), reply_markup=cancel_kb())
        await call.answer()

    @router.message(S.waiting_new_title)
    async def msg_cmb_new_title(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            await state.clear()
            return
        title = (message.text or "").strip()
        if not title or len(title) > MAX_TITLE_LEN:
            await message.answer(tr(f"❌ متن باید بین ۱ تا {MAX_TITLE_LEN} کاراکتر باشد. دوباره بفرست."),
                                 reply_markup=cancel_kb())
            return
        data = await state.get_data()
        await state.clear()
        btn_id = int(data.get("cm_edit_id") or 0)
        if not await asyncio.to_thread(db.cm_get, btn_id):
            await message.answer(tr("این کلید دیگر وجود ندارد."))
            return
        await asyncio.to_thread(db.cm_update, btn_id, title=title)
        await message.answer(tr("✅ متن کلید تغییر کرد."))
        await _msg_view(message, btn_id)

    @router.callback_query(F.data.startswith("adm_cmb_col:"))
    async def cb_cmb_color(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        btn_id = int(call.data.split(":")[1])
        await safe_edit(call, tr("🎨 رنگ کلید را انتخاب کن:"), reply_markup=color_kb(btn_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_cmb_cs:"))
    async def cb_cmb_color_set(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        _, btn_id, style = call.data.split(":")
        style = "" if style == "none" else style
        if style not in ("", "primary", "success", "danger"):
            await call.answer(tr("رنگ نامعتبر."), show_alert=True)
            return
        await asyncio.to_thread(db.cm_update, int(btn_id), style=style)
        await _show_view(call, int(btn_id))
        await call.answer(tr("✅ اعمال شد."))

    @router.callback_query(F.data.startswith("adm_cmb_ec:"))
    async def cb_cmb_edit_content(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        btn_id = int(call.data.split(":")[1])
        await state.clear()
        await state.update_data(cm_edit_id=btn_id)
        await safe_edit(call, tr("کلید بعد از ویرایش چه کاری انجام بدهد؟"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_ib("🔗 باز کردن یک لینک", f"adm_cmb_ek:{btn_id}:url")],
            [_ib("💬 ارسال پیام (متن/عکس/ویس/استیکر/...)", f"adm_cmb_ek:{btn_id}:content")],
            [_ib("⬅️ انصراف", f"adm_cmb_v:{btn_id}")],
        ]))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_cmb_ek:"))
    async def cb_cmb_edit_kind(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        _, btn_id, kind = call.data.split(":")
        if not await asyncio.to_thread(db.cm_get, int(btn_id)):
            await call.answer(tr("این کلید دیگر وجود ندارد."), show_alert=True)
            return
        await state.update_data(cm_edit_id=int(btn_id))
        if kind == "url":
            await state.set_state(S.waiting_new_url)
            await safe_edit(call, tr("🔗 لینک جدید را بفرست."), reply_markup=cancel_kb())
        else:
            await state.set_state(S.waiting_new_content)
            await state.update_data(cm_parts=[])
            await safe_edit(call, _content_prompt(0), reply_markup=cancel_kb())
        await call.answer()

    @router.message(S.waiting_new_url)
    async def msg_cmb_new_url(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            await state.clear()
            return
        url = normalize_url(message.text or "")
        if not url:
            await message.answer(tr("❌ لینک معتبر نیست. مثل https://example.com یا @username بفرست."),
                                 reply_markup=cancel_kb())
            return
        data = await state.get_data()
        await state.clear()
        btn_id = int(data.get("cm_edit_id") or 0)
        if not await asyncio.to_thread(db.cm_get, btn_id):
            await message.answer(tr("این کلید دیگر وجود ندارد."))
            return
        await asyncio.to_thread(db.cm_update, btn_id, kind="url", url=url, parts=[])
        _log(message.from_user.id, "cmb_edit", f"لینک کلید #{btn_id} تغییر کرد")
        await message.answer(tr("✅ لینک ذخیره شد."))
        await _msg_view(message, btn_id)

    @router.callback_query(F.data.startswith("adm_cmb_mv:"))
    async def cb_cmb_move(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        _, btn_id, d = call.data.split(":")
        await asyncio.to_thread(db.cm_move, int(btn_id), -1 if d == "u" else 1)
        await _show_view(call, int(btn_id))
        await call.answer(tr("✅ جابه‌جا شد."))

    @router.callback_query(F.data.startswith("adm_cmb_pv:"))
    async def cb_cmb_preview(call: CallbackQuery, bot):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        btn = await asyncio.to_thread(db.cm_get, int(call.data.split(":")[1]))
        if not btn or not btn["parts"]:
            await call.answer(tr("محتوایی برای پیش‌نمایش نیست."), show_alert=True)
            return
        await call.answer()
        await send_parts(bot, call.from_user.id, btn["parts"])

    @router.callback_query(F.data.startswith("adm_cmb_del:"))
    async def cb_cmb_delete(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        btn_id = int(call.data.split(":")[1])
        await safe_edit(call, tr("🗑 این کلید برای همیشه حذف شود؟"), reply_markup=delete_confirm_kb(btn_id))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_cmb_delok:"))
    async def cb_cmb_delete_ok(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        btn_id = int(call.data.split(":")[1])
        await asyncio.to_thread(db.cm_delete, btn_id)
        _log(call.from_user.id, "cmb_delete", f"کلید #{btn_id} حذف شد")
        await _show_list(call)
        await call.answer(tr("✅ حذف شد."))

    # ----- کلیک کاربر روی کلید پیام‌دار -------------------------------------
    @router.callback_query(F.data.startswith("cmb:"))
    async def cb_cmb_click(call: CallbackQuery, state: FSMContext, bot):
        try:
            btn_id = int(call.data.split(":", 1)[1])
        except ValueError:
            await call.answer()
            return
        btn = await asyncio.to_thread(db.cm_get, btn_id)
        if (not btn or not btn["is_active"] or btn["kind"] != "content" or not btn["parts"]
                or db.get_setting("main_menu_inline_enabled", "0") != "1"):
            await call.answer(tr("این گزینه دیگر در دسترس نیست."), show_alert=True)
            return
        await call.answer()
        # مثل بقیه‌ی دکمه‌های منو: کاربر از هر مرحله‌ی نیمه‌کاره بیرون می‌آید
        await state.clear()
        await asyncio.to_thread(db.cm_add_click, btn_id)
        await send_parts(bot, call.from_user.id, btn["parts"])
