# -*- coding: utf-8 -*-
"""Admin panel (inside the Telegram bot) of the userbot: AI auto-reply in the owner's personal chats.

Independent from Telegram Business: own router, own callbacks (``adm_userbot*`` / ``ubr:``), own settings and tables.
"""

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import tenant_ctx
import userbot
from i18n import tr
from userbot_login import login_buttons
from states import AdminUserbot

logger = logging.getLogger(__name__)

MAX_FIRST_MESSAGE = 1000
MAX_PERSONA = 1200


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _onoff(value: bool) -> str:
    return "🟢" if value else "🔴"


def _cycle(choices, current):
    for item in choices:
        if item > current:
            return item
    return choices[0]


def create_userbot_router(db) -> Router:
    router = Router()
    # نمایندگی کامل: سشن/STATE یوزربات مخصوص همین بات
    router.message.outer_middleware(tenant_ctx.middleware(db))
    router.callback_query.outer_middleware(tenant_ctx.middleware(db))

    async def _deny(call: CallbackQuery):
        await call.answer(tr("⛔️ این بخش فقط برای مدیران کامل در دسترس است."), show_alert=True)

    async def _show(call: CallbackQuery, text: str, markup):
        if call.message is None:
            return
        try:
            await call.message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
        except Exception:
            pass
        try:
            await call.message.delete()
        except Exception:
            pass
        try:
            await call.message.answer(text, reply_markup=markup)
        except Exception:
            pass

    def _log(admin_id: int, action: str, detail: str):
        return asyncio.to_thread(db.log_admin_action, admin_id, action, detail)

    def _flag(key: str) -> bool:
        return userbot.flag(db, key)

    # ------------------------------------------------------------------ main screen
    def _status_line() -> str:
        creds = userbot.load_session()
        me = userbot.STATE.get("me") or (creds or {}).get("user") or {}
        who = ""
        if me:
            who = f" — {html.escape(me.get('first_name') or '')}" + (f" (@{html.escape(me['username'])})" if me.get("username") else "")
        if userbot.STATE["connected"]:
            return tr("🟢 متصل") + who
        if creds is None:
            return tr("⚪️ وارد نشده")
        if userbot.STATE.get("last_error"):
            return tr("🔴 قطع") + who + f"\n⚠️ {html.escape(userbot.STATE['last_error'])}"
        return tr("🔴 قطع") + who

    async def _show_main(call: CallbackQuery):
        stats = await asyncio.to_thread(db.get_userbot_stats, 1)
        humans = await asyncio.to_thread(db.count_userbot_human_chats)
        chats = await asyncio.to_thread(db.count_userbot_chats)
        away = userbot.get_away_minutes(db)
        creds = userbot.load_session()
        text = (
            f"{tr('🤖 یوزربات (پاسخ‌گوی هوش مصنوعی در پیوی مدیر)')}\n\n"
            f"{tr('وضعیت اتصال')}: {_status_line()}\n"
            f"{tr('مدیر الان فعال است')}: {'✅' if userbot.admin_active(db) else '❌'}\n"
            f"{tr('چت‌های ثبت‌شده')}: {chats} | {tr('در حالت انسانی')}: {humans}\n\n"
            f"{tr('امروز')}: {tr('پیام‌های دریافتی')} {stats.get('incoming', 0)} | "
            f"{tr('پاسخ‌ها')} {stats.get('replies', 0)} | {tr('تحویل به انسان')} {stats.get('handoffs', 0)} | "
            f"{tr('خطا')} {stats.get('errors', 0)}"
        )
        if creds is None and tenant_ctx.current_key() is not None:
            text += "\n\n" + tr("برای فعال‌سازی، از دکمه‌ی «ورود به اکانت تلگرام» پایین وارد شوید؛ نیازی به ریستارت نیست.")
        elif creds is None:
            text += "\n\n" + tr("ورود به اکانت از منوی سرور (گزینه «ورود به اکانت تلگرام») انجام می‌شود؛ بعد از ورود نیازی به ریستارت نیست.")
        else:
            text += "\n\n" + tr(
                "نکته: داخل هر چت می‌توانید بنویسید «.ai off» یا «.ai on» تا هوش مصنوعی فقط در همان چت خاموش/روشن شود "
                "(پیام دستور خودکار حذف می‌شود)."
            )
        sched_on = userbot.setting(db, userbot.KEY_SCHEDULE_MODE) == "off_hours"
        ttl = userbot.int_setting(db, userbot.KEY_HUMAN_TTL, 0)
        debounce = userbot.int_setting(db, userbot.KEY_DEBOUNCE, 3)
        scope_chat = userbot.setting(db, userbot.KEY_PAUSE_SCOPE) != "global"
        rows = [
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_ENABLED))} {tr('پاسخ‌دهی یوزربات')}", callback_data="adm_ub_t:" + userbot.KEY_ENABLED)],
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_PAUSE_WHEN_ACTIVE))} {tr('توقف وقتی مدیر فعال است')}", callback_data="adm_ub_t:" + userbot.KEY_PAUSE_WHEN_ACTIVE)],
            [InlineKeyboardButton(
                text=f"🎯 {tr('محدوده‌ی توقف')}: {tr('فقط همان چت') if scope_chat else tr('همه‌ی چت‌ها')}",
                callback_data="adm_ub_scope",
            )],
            [InlineKeyboardButton(text=f"⏱ {tr('مدت فعال‌ماندن مدیر')}: {away} {tr('دقیقه')}", callback_data="adm_ub_min")],
            [InlineKeyboardButton(text=f"⌛ {tr('تجمیع پیام‌های پشت‌سرهم')}: {debounce} {tr('ثانیه')}", callback_data="adm_ub_deb")],
            [InlineKeyboardButton(
                text=f"🕘 {tr('ساعات حضور مدیر')}: {_onoff(sched_on)}"
                + (f" {userbot.setting(db, userbot.KEY_HOURS_START)}–{userbot.setting(db, userbot.KEY_HOURS_END)}" if sched_on else ""),
                callback_data="adm_ub_sched",
            )],
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_MEDIA_UNDERSTAND))} {tr('فهم ویس و عکس مشتری')}", callback_data="adm_ub_t:" + userbot.KEY_MEDIA_UNDERSTAND)],
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_MEDIA_ACK))} {tr('تأیید دریافت فایل')}", callback_data="adm_ub_t:" + userbot.KEY_MEDIA_ACK)],
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_SALES_CARD))} {tr('ارسال مشخصات و لینک خرید')}", callback_data="adm_ub_t:" + userbot.KEY_SALES_CARD)],
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_SEND_CONFIGS))} {tr('ارسال کانفیگ مشتری داخل چت')}", callback_data="adm_ub_t:" + userbot.KEY_SEND_CONFIGS)],
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_SKIP_CONTACTS))} {tr('نادیده‌گرفتن مخاطب‌های ذخیره‌شده')}", callback_data="adm_ub_t:" + userbot.KEY_SKIP_CONTACTS)],
            [InlineKeyboardButton(text=f"{_onoff(_flag(userbot.KEY_MARK_READ))} {tr('علامت‌گذاری خوانده‌شده')}", callback_data="adm_ub_t:" + userbot.KEY_MARK_READ)],
            [InlineKeyboardButton(
                text=f"🔁 {tr('بازگشت خودکار چت انسانی')}: " + (f"{ttl} {tr('ساعت')}" if ttl else tr("خاموش")),
                callback_data="adm_ub_ttl",
            )],
            [InlineKeyboardButton(text=tr("✏️ پیام اول (خوش‌آمد)"), callback_data="adm_ub_fm")],
            [InlineKeyboardButton(text=tr("🎭 لحن و دستورالعمل پاسخ‌ها"), callback_data="adm_ub_persona")],
            [InlineKeyboardButton(text=f"{tr('🚫 لیست استثناها')} ({len(await asyncio.to_thread(db.list_userbot_exceptions))})", callback_data="adm_ub_ex")],
            [InlineKeyboardButton(text=f"{tr('🤝 چت‌های تحویل‌شده به انسان')} ({humans})", callback_data="adm_ub_humans")],
            *login_buttons("ub", creds is not None),
            [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:access")],
        ]
        await _show(call, text, _kb(rows))

    @router.callback_query(F.data == "adm_userbot")
    async def cb_main(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.clear()
        await _show_main(call)
        await call.answer()

    # ------------------------------------------------------------------ simple toggles / cycles
    @router.callback_query(F.data.startswith("adm_ub_t:"))
    async def cb_toggle(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        key = call.data.split(":", 1)[1]
        if key not in userbot.DEFAULTS:
            return await call.answer()
        new_value = "0" if _flag(key) else "1"
        await asyncio.to_thread(db.set_setting, key, new_value)
        await _log(call.from_user.id, "userbot_toggle", f"{key}={new_value}")
        await _show_main(call)
        await call.answer()

    async def _set_and_show(call: CallbackQuery, key: str, value: str):
        await asyncio.to_thread(db.set_setting, key, value)
        await _log(call.from_user.id, "userbot_setting", f"{key}={value}")
        await _show_main(call)
        await call.answer()

    @router.callback_query(F.data == "adm_ub_scope")
    async def cb_scope(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        new_value = "global" if userbot.setting(db, userbot.KEY_PAUSE_SCOPE) != "global" else "chat"
        await _set_and_show(call, userbot.KEY_PAUSE_SCOPE, new_value)

    @router.callback_query(F.data == "adm_ub_min")
    async def cb_min(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await _set_and_show(call, userbot.KEY_AWAY_MINUTES, str(_cycle(userbot.AWAY_CHOICES, userbot.get_away_minutes(db))))

    @router.callback_query(F.data == "adm_ub_deb")
    async def cb_debounce(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        current = userbot.int_setting(db, userbot.KEY_DEBOUNCE, 3)
        await _set_and_show(call, userbot.KEY_DEBOUNCE, str(_cycle(userbot.DEBOUNCE_CHOICES, current)))

    @router.callback_query(F.data == "adm_ub_ttl")
    async def cb_ttl(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        current = userbot.int_setting(db, userbot.KEY_HUMAN_TTL, 0)
        await _set_and_show(call, userbot.KEY_HUMAN_TTL, str(_cycle(userbot.TTL_CHOICES, current)))

    # ------------------------------------------------------------------ schedule
    async def _show_schedule(call: CallbackQuery):
        on = userbot.setting(db, userbot.KEY_SCHEDULE_MODE) == "off_hours"
        start = userbot.setting(db, userbot.KEY_HOURS_START)
        end = userbot.setting(db, userbot.KEY_HOURS_END)
        text = (
            f"{tr('🕘 ساعات حضور مدیر')}\n\n"
            + tr("اگر روشن باشد، در بازه‌ی حضور شما (به وقت ایران) هوش مصنوعی جواب نمی‌دهد تا خودتان پاسخ بدهید؛ بیرون از این بازه خودکار پاسخ می‌دهد.")
            + f"\n\n{tr('وضعیت')}: {_onoff(on)}\n{tr('بازه‌ی حضور')}: {start} – {end}"
        )
        rows = [
            [InlineKeyboardButton(text=f"{_onoff(on)} {tr('فعال')}", callback_data="adm_ub_sched_t")],
            [InlineKeyboardButton(text=f"✏️ {tr('تغییر بازه')}", callback_data="adm_ub_sched_e")],
            [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_userbot")],
        ]
        await _show(call, text, _kb(rows))

    @router.callback_query(F.data == "adm_ub_sched")
    async def cb_sched(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.clear()
        await _show_schedule(call)
        await call.answer()

    @router.callback_query(F.data == "adm_ub_sched_t")
    async def cb_sched_toggle(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        on = userbot.setting(db, userbot.KEY_SCHEDULE_MODE) == "off_hours"
        value = "always" if on else "off_hours"
        await asyncio.to_thread(db.set_setting, userbot.KEY_SCHEDULE_MODE, value)
        await _log(call.from_user.id, "userbot_schedule", f"mode={value}")
        await _show_schedule(call)
        await call.answer()

    @router.callback_query(F.data == "adm_ub_sched_e")
    async def cb_sched_edit(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.set_state(AdminUserbot.waiting_hours)
        await _show(
            call,
            tr("بازه‌ی حضور خودتان را به‌صورت «شروع-پایان» بفرستید، مثلاً 09:00-22:30 (به وقت ایران)."),
            _kb([[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_ub_sched")]]),
        )
        await call.answer()

    @router.message(StateFilter(AdminUserbot.waiting_hours))
    async def on_hours(message: Message, state: FSMContext):
        if not db.is_full_admin(message.from_user.id):
            return
        raw = (message.text or "").strip().replace("–", "-").replace("—", "-").replace(" ", "")
        parts = raw.split("-")
        start = userbot.normalize_hhmm(parts[0]) if len(parts) == 2 else None
        end = userbot.normalize_hhmm(parts[1]) if len(parts) == 2 else None
        if not start or not end or start == end:
            await message.answer(tr("فرمت نامعتبر است. مثال: 09:00-22:30"))
            return
        await state.clear()
        await asyncio.to_thread(db.set_setting, userbot.KEY_HOURS_START, start)
        await asyncio.to_thread(db.set_setting, userbot.KEY_HOURS_END, end)
        await _log(message.from_user.id, "userbot_hours", f"{start}-{end}")
        await message.answer(tr("✅ ذخیره شد."), reply_markup=_kb([[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_ub_sched")]]))

    # ------------------------------------------------------------------ free-text settings (first message, persona)
    def _text_setting(prefix: str, key: str, state_name, prompt: str, limit: int, log_action: str):
        @router.callback_query(F.data == f"adm_ub_{prefix}")
        async def _open(call: CallbackQuery, state: FSMContext):
            if not db.is_full_admin(call.from_user.id):
                return await _deny(call)
            await state.set_state(state_name)
            current = userbot.setting(db, key)
            shown = f"\n\n{tr('مقدار فعلی')}:\n{html.escape(current)}" if current else ""
            await _show(
                call,
                tr(prompt) + shown,
                _kb([[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_userbot")]]),
            )
            await call.answer()

        @router.message(StateFilter(state_name))
        async def _save(message: Message, state: FSMContext):
            if not db.is_full_admin(message.from_user.id):
                return
            text = (message.text or "").strip()
            if not text:
                await message.answer(tr("لطفاً متن بفرستید."))
                return
            if len(text) > limit:
                await message.answer(f"{tr('متن خیلی طولانی است. حداکثر')} {limit} {tr('حرف')}")
                return
            await state.clear()
            await asyncio.to_thread(db.set_setting, key, "" if text == "-" else text)
            await _log(message.from_user.id, log_action, f"{key} len={len(text)}")
            await message.answer(tr("✅ ذخیره شد."), reply_markup=_kb([[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_userbot")]]))

    _text_setting(
        "fm", userbot.KEY_FIRST_MESSAGE, AdminUserbot.waiting_first_message,
        "متن پیام اول را بفرستید. این پیام فقط یک‌بار در شروع هر چت جدید ارسال می‌شود. برای حذف، «-» بفرستید.",
        MAX_FIRST_MESSAGE, "userbot_first_message",
    )
    _text_setting(
        "persona", userbot.KEY_PERSONA, AdminUserbot.waiting_persona,
        (
            "لحن و دستورالعمل پاسخ‌ها را بنویسید؛ مثلاً: «محترمانه و خودمانی جواب بده، اسم فروشگاه «X» است، "
            "ساعت پاسخ‌گویی انسانی ۹ تا ۲۲ است.» این متن فقط روی لحن و اطلاعات برند اثر دارد و قوانین ایمنی را تغییر نمی‌دهد. "
            "برای حذف، «-» بفرستید."
        ),
        MAX_PERSONA, "userbot_persona",
    )

    # ------------------------------------------------------------------ exceptions
    async def _show_exceptions(call: CallbackQuery):
        exceptions = await asyncio.to_thread(db.list_userbot_exceptions)
        rows = []
        for e in exceptions[:40]:
            rows.append([
                InlineKeyboardButton(text=str(e["user_id"]), callback_data="noop"),
                InlineKeyboardButton(text="🗑", callback_data=f"adm_ub_exdel:{e['user_id']}"),
            ])
        rows.append([InlineKeyboardButton(text=tr("➕ افزودن آیدی عددی"), callback_data="adm_ub_exadd")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_userbot")])
        text = tr("🚫 مشتری‌هایی که یوزربات در چتشان پاسخ نمی‌دهد:") if exceptions else tr("لیست استثناها خالی است.")
        await _show(call, text, _kb(rows))

    @router.callback_query(F.data == "adm_ub_ex")
    async def cb_exceptions(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.clear()
        await _show_exceptions(call)
        await call.answer()

    @router.callback_query(F.data == "adm_ub_exadd")
    async def cb_exception_add(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.set_state(AdminUserbot.waiting_exception_id)
        await _show(
            call,
            tr("آیدی عددی تلگرام مشتری را بفرستید:"),
            _kb([[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_ub_ex")]]),
        )
        await call.answer()

    @router.message(StateFilter(AdminUserbot.waiting_exception_id))
    async def on_exception_id(message: Message, state: FSMContext):
        if not db.is_full_admin(message.from_user.id):
            return
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer(tr("آیدی عددی معتبر بفرستید."))
            return
        await state.clear()
        await asyncio.to_thread(db.add_userbot_exception, int(raw))
        await _log(message.from_user.id, "userbot_exception_add", f"user={raw}")
        await message.answer(tr("✅ اضافه شد."), reply_markup=_kb([[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_ub_ex")]]))

    @router.callback_query(F.data.startswith("adm_ub_exdel:"))
    async def cb_exception_del(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        try:
            user_id = int(call.data.split(":", 1)[1])
        except ValueError:
            return await call.answer()
        await asyncio.to_thread(db.remove_userbot_exception, user_id)
        await _log(call.from_user.id, "userbot_exception_del", f"user={user_id}")
        await _show_exceptions(call)
        await call.answer()

    # ------------------------------------------------------------------ human chats
    async def _show_humans(call: CallbackQuery):
        chats = await asyncio.to_thread(db.list_userbot_human_chats)
        rows = []
        for ch in chats:
            label = (ch["first_name"] or "").strip() or str(ch["chat_id"])
            rows.append([InlineKeyboardButton(text=f"▶️ {label}", callback_data=f"adm_ub_res:{ch['chat_id']}")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_userbot")])
        text = tr("برای برگرداندن چت به حالت خودکار، روی نام مشتری بزنید:") if chats else tr("چتی در حالت انسانی نیست.")
        await _show(call, text, _kb(rows))

    @router.callback_query(F.data == "adm_ub_humans")
    async def cb_humans(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await _show_humans(call)
        await call.answer()

    async def _resume(chat_id: int):
        await asyncio.to_thread(db.set_userbot_chat_mode, chat_id, "auto")
        await asyncio.to_thread(db.clear_userbot_ai_conversation, chat_id)
        userbot.STATE["chat_active"].pop(chat_id, None)

    @router.callback_query(F.data.startswith("adm_ub_res:"))
    async def cb_humans_resume(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        try:
            chat_id = int(call.data.split(":", 1)[1])
        except ValueError:
            return await call.answer()
        await _resume(chat_id)
        await _log(call.from_user.id, "userbot_resume", f"chat={chat_id}")
        await call.answer(tr("✅ چت به حالت خودکار برگشت."))
        await _show_humans(call)

    # the "resume" button inside the hand-off notification sent by the userbot
    @router.callback_query(F.data.startswith("ubr:"))
    async def cb_notice_resume(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        try:
            chat_id = int(call.data.split(":", 1)[1])
        except ValueError:
            return await call.answer()
        await _resume(chat_id)
        await _log(call.from_user.id, "userbot_resume", f"chat={chat_id}")
        await call.answer(tr("✅ چت به حالت خودکار برگشت."))
        if call.message is not None:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

    return router
