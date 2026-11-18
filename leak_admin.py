# -*- coding: utf-8 -*-
"""منوی ادمین «تشخیص نشت کانفیگ» و دکمه‌های هشدار نشت.

دکمه‌های lk:rot / lk:warn / lk:ign روی پیام هشدار (در تاپیک «🚨 نشت کانفیگ») کار می‌کنند؛
منوی اصلی از صفحه‌ی یوزربات (adm_userbot) باز می‌شود.
"""

import asyncio
import html
import logging
import os
import re
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import leak_discovery as ld
import tenant_ctx
import leak_index
import leak_scanner as ls
from userbot_login import login_buttons
import userbot
from i18n import tr

logger = logging.getLogger(__name__)

SCAN_MINUTES_CHOICES = [5, 15, 30, 60]
MAX_PER_MIN_CHOICES = [3, 6, 10, 20]
WARN_THRESHOLD_CHOICES = [1, 2, 3, 5]
DAILY_JOIN_CHOICES = [2, 5, 10, 20]
MAX_JOINED_CHOICES = [50, 100, 150, 250]
MIN_SCORE_CHOICES = [25, 35, 50, 65]
DISC_INTERVAL_CHOICES = [15, 30, 60, 120]
JOIN_MODE_LABELS = {"auto": "🤖 عضویت خودکار", "approve": "✋ با تأیید ادمین", "watch": "👁 فقط پایش (بدون عضویت)"}
CANDIDATE_LABELS = {
    "new": "🆕 در صف ارزیابی", "qualified": "✅ واجد شرایط", "pending": "✋ منتظر تأیید", "approved": "👍 تأییدشده",
    "joined": "📥 عضو شد", "watching": "👁 پایش", "skipped": "⏭ ردشده", "failed": "❌ ناموفق", "left": "🚪 ترک‌شده",
}
STATUS_LABELS = {"new": "🆕 جدید", "rotated": "🔄 چرخانده شد", "ignored": "🙈 نادیده", "warned": "⚠️ اخطار"}


_running_refreshes = set()


class LeakAdmin(StatesGroup):
    waiting_channel = State()
    waiting_keywords = State()
    waiting_disc_queries = State()


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _onoff(value: bool) -> str:
    return "🟢" if value else "🔴"


def _cycle(choices, current):
    for item in choices:
        if item > current:
            return item
    return choices[0]


def create_leak_router(db) -> Router:
    router = Router()
    # نمایندگی کامل: سشن/STATE اسکنر مخصوص همین بات
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

    async def _log(admin_id: int, action: str, detail: str):
        await asyncio.to_thread(db.log_admin_action, admin_id, action, detail)

    def _flag(key: str) -> bool:
        return ls.flag(db, key)

    def _int(key: str, default: int) -> int:
        return ls.int_setting(db, key, default)

    # ------------------------------------------------------------ main screen
    async def _main_text() -> str:
        stats = await asyncio.to_thread(db.get_credential_index_stats)
        by_status = await asyncio.to_thread(db.count_leak_events_by_status)
        channels = await asyncio.to_thread(db.list_leak_channels)
        active_channels = sum(1 for c in channels if c["active"])
        if ls.get_client():
            if os.path.exists(userbot.scanner_session_path()):
                creds = userbot.load_session(userbot.scanner_session_path()) or {}
                me = creds.get("user") or {}
                client_state = tr("🟢 متصل (اکانت اختصاصی اسکنر)")
            else:
                me = userbot.STATE.get("me") or {}
                client_state = tr("🟢 متصل")
            client_state += f" — @{html.escape(me['username'])}" if me.get("username") else ""
        else:
            client_state = tr("🔴 قطع (یوزربات متصل نیست)")
        events_line = " | ".join(
            f"{tr(label)}: {by_status.get(key, 0)}" for key, label in STATUS_LABELS.items()
        )
        return (
            f"{tr('🚨 تشخیص نشت کانفیگ')}\n\n"
            f"{tr('یوزربات')}: {client_state}\n"
            f"{tr('کانال‌های زیر نظر')}: {active_channels}/{len(channels)}\n"
            f"{tr('ایندکس')}: {stats['configs']} {tr('سرویس')} / {stats['hashes']} {tr('هش')}"
            + (f" — {tr('آخرین به‌روزرسانی')}: {html.escape(str(stats['last_update']))}" if stats["last_update"] else "")
            + "\n"
            f"{tr('رویدادها')}: {events_line}\n\n"
            f"{tr('اسکنر از اکانت یوزربات استفاده می‌کند. سقف درخواست دارد، هنگام FloodWait متوقف می‌شود و پاسخ به مشتری در اولویت است.')}"
        )

    async def _show_main(call: CallbackQuery):
        text = await _main_text()
        keywords = ls.keywords(db)
        rows = [
            [InlineKeyboardButton(text=f"{_onoff(_flag(ls.KEY_ENABLED))} {tr('اسکنر نشت')}", callback_data="adm_leak_t:" + ls.KEY_ENABLED)],
            [InlineKeyboardButton(text=f"{_onoff(_flag(ls.KEY_AUTO_REVOKE))} {tr('ابطال خودکار لینک (پیش‌فرض خاموش)')}", callback_data="adm_leak_t:" + ls.KEY_AUTO_REVOKE)],
            [InlineKeyboardButton(text=f"⏱ {tr('فاصله‌ی اسکن')}: {_int(ls.KEY_SCAN_MINUTES, 15)} {tr('دقیقه')}", callback_data="adm_leak_cycle:" + ls.KEY_SCAN_MINUTES)],
            [InlineKeyboardButton(text=f"🚦 {tr('سقف درخواست در دقیقه')}: {_int(ls.KEY_MAX_PER_MIN, 6)}", callback_data="adm_leak_cycle:" + ls.KEY_MAX_PER_MIN)],
            [InlineKeyboardButton(text=f"⚠️ {tr('سقف اخطار تا مسدودسازی')}: {_int(ls.KEY_WARN_THRESHOLD, 3)}", callback_data="adm_leak_cycle:" + ls.KEY_WARN_THRESHOLD)],
            [InlineKeyboardButton(text=f"🔑 {tr('کلیدواژه‌های جستجوی سراسری')} ({len(keywords)})", callback_data="adm_leak_kw")],
            [InlineKeyboardButton(text=tr("🧭 کشف و عضویت هوشمند"), callback_data="adm_leak_d")],
            [InlineKeyboardButton(text=tr("📢 کانال‌های زیر نظر"), callback_data="adm_leak_ch")],
            [InlineKeyboardButton(text=tr("🧾 آخرین رویدادها"), callback_data="adm_leak_ev")],
            [InlineKeyboardButton(text=tr("🔄 به‌روزرسانی فوری ایندکس"), callback_data="adm_leak_idx")],
            *login_buttons("leak", os.path.exists(userbot.scanner_session_path())),
            [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:access")],
        ]
        await _show(call, text, _kb(rows))

    @router.callback_query(F.data == "adm_leak")
    async def cb_main(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.clear()
        await _show_main(call)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_leak_t:"))
    async def cb_toggle(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        key = call.data.split(":", 1)[1]
        if key not in (ls.KEY_ENABLED, ls.KEY_AUTO_REVOKE):
            return await call.answer()
        new_value = "0" if _flag(key) else "1"
        await asyncio.to_thread(db.set_setting, key, new_value)
        await _log(call.from_user.id, "leak_toggle", f"{key}={new_value}")
        await _show_main(call)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_leak_cycle:"))
    async def cb_cycle(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        key = call.data.split(":", 1)[1]
        choices = {
            ls.KEY_SCAN_MINUTES: SCAN_MINUTES_CHOICES,
            ls.KEY_MAX_PER_MIN: MAX_PER_MIN_CHOICES,
            ls.KEY_WARN_THRESHOLD: WARN_THRESHOLD_CHOICES,
        }.get(key)
        if choices is None:
            return await call.answer()
        new_value = _cycle(choices, _int(key, choices[0]))
        await asyncio.to_thread(db.set_setting, key, str(new_value))
        await _log(call.from_user.id, "leak_setting", f"{key}={new_value}")
        await _show_main(call)
        await call.answer()

    @router.callback_query(F.data == "adm_leak_idx")
    async def cb_index(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        task = asyncio.create_task(leak_index.refresh_all(db))
        _running_refreshes.add(task)
        task.add_done_callback(_running_refreshes.discard)
        await _log(call.from_user.id, "leak_index_refresh", "manual")
        await call.answer(tr("به‌روزرسانی ایندکس شروع شد."), show_alert=True)

    # ------------------------------------------------------------ keywords
    @router.callback_query(F.data == "adm_leak_kw")
    async def cb_keywords(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.set_state(LeakAdmin.waiting_keywords)
        current = ", ".join(ls.keywords(db)) or tr("(خالی)")
        await _show(call, tr("کلیدواژه‌ها را با کاما جدا کنید (مثلاً: vless, vmess, trojan).") + f"\n{tr('فعلی')}: {html.escape(current)}\n\n" + tr("برای خالی‌کردن، «-» بفرستید."),
                    _kb([[InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data="adm_leak")]]))
        await call.answer()

    @router.message(StateFilter(LeakAdmin.waiting_keywords))
    async def msg_keywords(message: Message, state: FSMContext):
        if not db.is_full_admin(message.from_user.id):
            await state.clear()
            return
        raw = (message.text or "").strip()
        value = "" if raw in ("-", "") else ",".join(k.strip() for k in raw.split(",") if k.strip())[:500]
        await asyncio.to_thread(db.set_setting, ls.KEY_KEYWORDS, value)
        await _log(message.from_user.id, "leak_keywords", value)
        await state.clear()
        await message.answer(tr("✅ کلیدواژه‌ها ذخیره شد.") + "\n" + (html.escape(value) or tr("(خالی)")))

    # ------------------------------------------------------------ channels
    async def _show_channels(call: CallbackQuery):
        channels = await asyncio.to_thread(db.list_leak_channels)
        lines = [tr("📢 کانال‌های زیر نظر اسکنر"), ""]
        rows = []
        if not channels:
            lines.append(tr("هنوز کانالی اضافه نشده است."))
        for ch in channels:
            name = ch["title"] or str(ch["channel_id"])
            tag = "📥" if ch["joined"] else "👁"
            lines.append(f"{_onoff(ch['active'])} {tag} {html.escape(name)}")
            rows.append([
                InlineKeyboardButton(text=f"{_onoff(ch['active'])} {name[:30]}", callback_data=f"adm_leak_chT:{ch['channel_id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"adm_leak_chD:{ch['channel_id']}"),
            ])
        rows.append([InlineKeyboardButton(text=tr("➕ افزودن کانال"), callback_data="adm_leak_chA")])
        rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_leak")])
        await _show(call, "\n".join(lines), _kb(rows))

    @router.callback_query(F.data == "adm_leak_ch")
    async def cb_channels(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.clear()
        await _show_channels(call)
        await call.answer()

    @router.callback_query(F.data == "adm_leak_chA")
    async def cb_channel_add(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.set_state(LeakAdmin.waiting_channel)
        await _show(call, tr("@username یا لینک t.me یا شناسه‌ی عددی کانال را بفرستید.\nاکانت یوزربات باید عضو کانال باشد (یا کانال عمومی باشد)."),
                    _kb([[InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data="adm_leak_ch")]]))
        await call.answer()

    @router.message(StateFilter(LeakAdmin.waiting_channel))
    async def msg_channel(message: Message, state: FSMContext):
        if not db.is_full_admin(message.from_user.id):
            await state.clear()
            return
        client = ls.get_client()
        if client is None:
            await message.answer(tr("⛔️ یوزربات متصل نیست؛ ابتدا از منوی سرور وارد اکانت تلگرام شوید."))
            return
        try:
            title = await ls.add_channel(client, db, message.text or "")
        except ValueError as exc:
            await message.answer(tr("⛔️") + f" {exc}")
            return
        except Exception as exc:
            logger.warning("leak: add channel failed", exc_info=True)
            await message.answer(tr("⛔️ کانال پیدا نشد یا یوزربات دسترسی ندارد.") + f"\n{html.escape(str(exc)[:200])}")
            return
        await _log(message.from_user.id, "leak_channel_add", title)
        await state.clear()
        await message.answer(tr("✅ کانال اضافه شد:") + f" {html.escape(title)}")

    @router.callback_query(F.data.startswith("adm_leak_chT:"))
    async def cb_channel_toggle(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        channel_id = int(call.data.split(":", 1)[1])
        ch = await asyncio.to_thread(db.get_leak_channel, channel_id)
        if ch:
            await asyncio.to_thread(db.set_leak_channel_active, channel_id, not ch["active"])
        await _show_channels(call)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_leak_chD:"))
    async def cb_channel_delete(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        channel_id = int(call.data.split(":", 1)[1])
        await asyncio.to_thread(db.remove_leak_channel, channel_id)
        await _log(call.from_user.id, "leak_channel_remove", str(channel_id))
        await _show_channels(call)
        await call.answer(tr("حذف شد."))


    # ------------------------------------------------------------ discovery
    DISC_FLAGS = (ld.KEY_ENABLED, ld.KEY_CRAWL, ld.KEY_AUTO_LEAVE, ld.KEY_NOTIFY)
    DISC_CHOICES = {
        ld.KEY_DAILY_JOINS: DAILY_JOIN_CHOICES,
        ld.KEY_MAX_JOINED: MAX_JOINED_CHOICES,
        ld.KEY_MIN_SCORE: MIN_SCORE_CHOICES,
        ld.KEY_INTERVAL: DISC_INTERVAL_CHOICES,
    }

    def _dflag(key: str) -> bool:
        return ld.flag(db, key)

    def _dint(key: str, default: int) -> int:
        return ld.int_setting(db, key, default)

    def _back(target: str = "adm_leak_d"):
        return [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=target)]

    async def _disc_text() -> str:
        by_state = await asyncio.to_thread(db.count_leak_candidates_by_state)
        today = await asyncio.to_thread(db.count_leak_joins_since, 24)
        joined = await asyncio.to_thread(db.count_joined_leak_channels)
        queries = await asyncio.to_thread(db.list_leak_queries)
        paused = ld.DSTATE["join_paused_until"] - time.time()
        lines = [
            tr("🧭 کشف و عضویت هوشمند"),
            "",
            tr("اسکنر خودش در تلگرام کانال و گروه‌های مرتبط با کانفیگ را جستجو می‌کند، قبل از عضویت محتوا را امتیاز می‌دهد و فقط کانال‌های ارزشمند را زیر نظر می‌گیرد."),
            "",
            f"{tr('حالت عضویت')}: {tr(JOIN_MODE_LABELS[ld.join_mode(db)])}",
            f"{tr('عضویت امروز')}: {today}/{_dint(ld.KEY_DAILY_JOINS, 5)} | {tr('کل عضویت‌های خودکار')}: {joined}/{_dint(ld.KEY_MAX_JOINED, 100)}",
            f"{tr('کلیدواژه‌های جستجو')}: {len(queries)}",
            " | ".join(f"{tr(label)}: {by_state[key]}" for key, label in CANDIDATE_LABELS.items() if by_state.get(key)) or tr("هنوز کاندیدایی نیست."),
        ]
        if paused > 0:
            lines.append(f"⏸ {tr('عضویت به‌خاطر محدودیت تلگرام متوقف است')}: {int(paused // 60) + 1} {tr('دقیقه')}")
        if ld.DSTATE["last_cycle"]:
            ago = int((time.time() - ld.DSTATE["last_cycle"]) // 60)
            lines.append(f"🕒 {tr('آخرین چرخه')}: {ago} {tr('دقیقه پیش')} — {html.escape(ld.DSTATE['summary'] or '-')}")
        if not _flag(ls.KEY_ENABLED):
            lines += ["", tr("⚠️ کشف فقط وقتی کار می‌کند که «اسکنر نشت» روشن باشد.")]
        return "\n".join(lines)

    async def _show_disc(call: CallbackQuery):
        mode = ld.join_mode(db)
        rows = [
            [InlineKeyboardButton(text=f"{_onoff(_dflag(ld.KEY_ENABLED))} {tr('کشف خودکار')}", callback_data="adm_leak_dt:" + ld.KEY_ENABLED)],
            [InlineKeyboardButton(text=f"🚪 {tr('حالت')}: {tr(JOIN_MODE_LABELS[mode])}", callback_data="adm_leak_dm")],
            [InlineKeyboardButton(text=f"📆 {tr('سقف عضویت روزانه')}: {_dint(ld.KEY_DAILY_JOINS, 5)}", callback_data="adm_leak_dc:" + ld.KEY_DAILY_JOINS)],
            [InlineKeyboardButton(text=f"📦 {tr('سقف کل عضویت‌ها')}: {_dint(ld.KEY_MAX_JOINED, 100)}", callback_data="adm_leak_dc:" + ld.KEY_MAX_JOINED)],
            [InlineKeyboardButton(text=f"⭐ {tr('حداقل امتیاز عضویت')}: {_dint(ld.KEY_MIN_SCORE, 35)}", callback_data="adm_leak_dc:" + ld.KEY_MIN_SCORE)],
            [InlineKeyboardButton(text=f"⏱ {tr('فاصله‌ی چرخه‌ی کشف')}: {_dint(ld.KEY_INTERVAL, 30)} {tr('دقیقه')}", callback_data="adm_leak_dc:" + ld.KEY_INTERVAL)],
            [InlineKeyboardButton(text=f"{_onoff(_dflag(ld.KEY_CRAWL))} {tr('دنبال‌کردن لینک‌های داخل پست‌ها')}", callback_data="adm_leak_dt:" + ld.KEY_CRAWL)],
            [InlineKeyboardButton(text=f"{_onoff(_dflag(ld.KEY_AUTO_LEAVE))} {tr('ترک خودکار کانال‌های بی‌فایده')}", callback_data="adm_leak_dt:" + ld.KEY_AUTO_LEAVE)],
            [InlineKeyboardButton(text=f"{_onoff(_dflag(ld.KEY_NOTIFY))} {tr('اطلاع هر عضویت')}", callback_data="adm_leak_dt:" + ld.KEY_NOTIFY)],
            [
                InlineKeyboardButton(text=tr("📥 کاندیداها"), callback_data="adm_leak_dl"),
                InlineKeyboardButton(text=tr("📡 عضویت‌ها"), callback_data="adm_leak_dj"),
            ],
            [
                InlineKeyboardButton(text=tr("🔎 کلیدواژه‌ها"), callback_data="adm_leak_dq"),
                InlineKeyboardButton(text=tr("▶️ اجرای فوری"), callback_data="adm_leak_dgo"),
            ],
            _back("adm_leak"),
        ]
        await _show(call, await _disc_text(), _kb(rows))

    @router.callback_query(F.data == "adm_leak_d")
    async def cb_disc(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.clear()
        await _show_disc(call)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_leak_dt:"))
    async def cb_disc_toggle(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        key = call.data.split(":", 1)[1]
        if key not in DISC_FLAGS:
            return await call.answer()
        new_value = "0" if _dflag(key) else "1"
        await asyncio.to_thread(db.set_setting, key, new_value)
        await _log(call.from_user.id, "leak_disc_toggle", f"{key}={new_value}")
        await _show_disc(call)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_leak_dc:"))
    async def cb_disc_cycle(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        key = call.data.split(":", 1)[1]
        choices = DISC_CHOICES.get(key)
        if choices is None:
            return await call.answer()
        new_value = _cycle(choices, _dint(key, choices[0]))
        await asyncio.to_thread(db.set_setting, key, str(new_value))
        await _log(call.from_user.id, "leak_disc_setting", f"{key}={new_value}")
        await _show_disc(call)
        await call.answer()

    @router.callback_query(F.data == "adm_leak_dm")
    async def cb_disc_mode(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        modes = list(ld.JOIN_MODES)
        new_mode = modes[(modes.index(ld.join_mode(db)) + 1) % len(modes)]
        await asyncio.to_thread(db.set_setting, ld.KEY_JOIN_MODE, new_mode)
        await _log(call.from_user.id, "leak_disc_mode", new_mode)
        await _show_disc(call)
        await call.answer()

    @router.callback_query(F.data == "adm_leak_dgo")
    async def cb_disc_run(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        event = ld.DSTATE.get("wake")
        if event is None or ls.STATE.get("discovery") is None:
            return await call.answer(tr("⛔️ یوزربات متصل نیست."), show_alert=True)
        event.set()
        await _log(call.from_user.id, "leak_disc_run", "manual")
        await call.answer(tr("چرخه‌ی کشف شروع شد؛ نتیجه را چند دقیقه‌ی دیگر ببینید."), show_alert=True)

    # candidates ---------------------------------------------------------------
    async def _show_candidates(call: CallbackQuery):
        cands = await asyncio.to_thread(
            db.list_leak_candidates, ["pending", "approved", "qualified", "new"], 10, "score",
        )
        lines = [tr("📥 کاندیداهای عضویت"), ""]
        rows = []
        if not cands:
            lines.append(tr("کاندیدایی در صف نیست."))
        for c in cands:
            name = c["title"] or c["username"] or c["key"]
            lines.append(
                f"{tr(CANDIDATE_LABELS.get(c['state'], c['state']))} | ⭐ {c['score']:.0f} | 👥 {c['members'] or '-'} | "
                f"{html.escape(name[:40])}" + (f" (@{html.escape(c['username'])})" if c["username"] else "")
            )
            rows.append([
                InlineKeyboardButton(text=f"✅ {name[:22]}", callback_data=f"lkd:ok:{c['id']}"),
                InlineKeyboardButton(text="⏭", callback_data=f"lkd:no:{c['id']}"),
            ])
        rows.append(_back())
        await _show(call, "\n".join(lines), _kb(rows))

    @router.callback_query(F.data == "adm_leak_dl")
    async def cb_candidates(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await _show_candidates(call)
        await call.answer()

    @router.callback_query(F.data.startswith("lkd:ok:") | F.data.startswith("lkd:no:"))
    async def cb_candidate_decide(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        _, action, raw_id = call.data.split(":", 2)
        cand = await asyncio.to_thread(db.get_leak_candidate, int(raw_id)) if raw_id.isdigit() else None
        if not cand:
            return await call.answer(tr("کاندیدا پیدا نشد."), show_alert=True)
        if cand["state"] in ("joined", "watching", "left"):
            return await call.answer(tr("این مورد قبلاً رسیدگی شده است."), show_alert=True)
        if action == "ok":
            await asyncio.to_thread(db.update_leak_candidate, cand["id"], state="approved", reason=f"admin {call.from_user.id}")
            note = tr("✅ تأیید شد؛ در چرخه‌ی بعدی عضو می‌شود.")
            if ld.join_mode(db) == "watch":
                note += " " + tr("(حالت فعلی «فقط پایش» است؛ برای عضویت حالت را عوض کنید.)")
        else:
            await asyncio.to_thread(db.update_leak_candidate, cand["id"], state="skipped", reason=f"admin {call.from_user.id}")
            note = tr("⏭ رد شد.")
        await _log(call.from_user.id, "leak_candidate_" + action, str(cand["id"]))
        await call.answer(note, show_alert=True)
        if call.message and call.message.reply_markup and any(
            (b.callback_data or "").startswith("adm_leak_d") for r in call.message.reply_markup.inline_keyboard for b in r
        ):
            await _show_candidates(call)
        else:
            await _finish_alert(call, note)

    # joined channels ------------------------------------------------------------
    async def _show_joined(call: CallbackQuery):
        channels = [c for c in await asyncio.to_thread(db.list_leak_channels) if c["source"] == "discovery"]
        lines = [tr("📡 کانال‌های کشف‌شده‌ی زیر نظر"), ""]
        rows = []
        if not channels:
            lines.append(tr("هنوز کانالی با کشف خودکار اضافه نشده است."))
        for ch in channels[:25]:
            name = ch["title"] or str(ch["channel_id"])
            tag = "📥" if ch["joined"] else "👁"
            lines.append(f"{tag} {html.escape(name[:40])} | ⭐ {ch['score']:.0f} | 🧾 {ch['config_posts']} | 🚨 {ch['leak_hits']}")
            rows.append([InlineKeyboardButton(text=f"🚪 {tr('ترک/حذف')}: {name[:24]}", callback_data=f"lkd:lv:{ch['channel_id']}")])
        rows.append(_back())
        await _show(call, "\n".join(lines), _kb(rows))

    @router.callback_query(F.data == "adm_leak_dj")
    async def cb_joined(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await _show_joined(call)
        await call.answer()

    @router.callback_query(F.data.startswith("lkd:lv:"))
    async def cb_leave(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        disc = ls.STATE.get("discovery")
        if disc is None:
            return await call.answer(tr("⛔️ یوزربات متصل نیست."), show_alert=True)
        channel_id = int(call.data.split(":", 2)[2])
        ok, msg = await disc.leave_channel(channel_id, reason="admin")
        await _log(call.from_user.id, "leak_channel_leave", f"{channel_id} ok={ok}")
        await call.answer(tr(msg), show_alert=not ok)
        await _show_joined(call)

    # queries --------------------------------------------------------------------
    QUERY_PAGE = 8
    SOURCE_ICON = {"seed": "🌱", "admin": "✍️", "learned": "🧠"}

    async def _show_queries(call: CallbackQuery, page: int = 0):
        rows_db = await asyncio.to_thread(db.list_leak_queries)
        order = {"admin": 0, "learned": 1, "seed": 2}
        rows_db = sorted(rows_db, key=lambda r: (order.get(r["source"], 3), -(r["good_found"] or 0), r["query"]))
        pages = max(1, (len(rows_db) + QUERY_PAGE - 1) // QUERY_PAGE)
        page = max(0, min(page, pages - 1))
        chunk = rows_db[page * QUERY_PAGE:(page + 1) * QUERY_PAGE]
        active = sum(1 for r in rows_db if r["active"] is None or r["active"])
        lines = [
            tr("🔎 کلیدواژه‌های جستجوی تلگرام"), "",
            f"{tr('فعال')}: {active}/{len(rows_db)} | {tr('صفحه')} {page + 1}/{pages}",
            "✍️ " + tr("دستی") + " | 🧠 " + tr("یادگرفته‌شده") + " | 🌱 " + tr("پیش‌فرض"),
            tr("روی هر کلیدواژه بزنید تا فعال/غیرفعال شود. ارقام: خوب/جدید/اجرا"), "",
        ]
        rows = []
        for r in chunk:
            on = r["active"] is None or r["active"]
            lines.append(f"{_onoff(on)} {SOURCE_ICON.get(r['source'], '')} {html.escape(r['query'])} — {r['good_found']}/{r['new_found']}/{r['runs']}")
            row = [InlineKeyboardButton(text=f"{_onoff(on)} {r['query'][:26]}", callback_data=f"lkd:qt:{r['id']}:{page}")]
            if r["source"] != "seed":
                row.append(InlineKeyboardButton(text="🗑", callback_data=f"lkd:qd:{r['id']}:{page}"))
            rows.append(row)
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_leak_dq:{page - 1}"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_leak_dq:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton(text=tr("➕ افزودن کلیدواژه"), callback_data="adm_leak_dqa")])
        rows.append(_back())
        await _show(call, "\n".join(lines), _kb(rows))

    @router.callback_query(F.data.startswith("adm_leak_dq:") | (F.data == "adm_leak_dq"))
    async def cb_queries(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.clear()
        raw = call.data.split(":", 1)[1] if ":" in call.data else "0"
        await _show_queries(call, int(raw) if raw.isdigit() else 0)
        await call.answer()

    @router.callback_query(F.data.startswith("lkd:qt:") | F.data.startswith("lkd:qd:"))
    async def cb_query_edit(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        parts = call.data.split(":")
        action, qid, page = parts[1], int(parts[2]), int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        row = await asyncio.to_thread(db.get_leak_query, qid)
        if row is None:
            return await call.answer(tr("کلیدواژه پیدا نشد."), show_alert=True)
        if action == "qt":
            new_state = not (row["active"] is None or row["active"])
            await asyncio.to_thread(db.set_leak_query_active, qid, new_state)
            await _log(call.from_user.id, "leak_query_toggle", f"{row['query']}={int(new_state)}")
        else:
            await asyncio.to_thread(db.delete_leak_query, qid)
            await _log(call.from_user.id, "leak_query_delete", row["query"])
        await _show_queries(call, page)
        await call.answer()

    @router.callback_query(F.data == "adm_leak_dqa")
    async def cb_query_add(call: CallbackQuery, state: FSMContext):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        await state.set_state(LeakAdmin.waiting_disc_queries)
        await _show(
            call,
            tr("کلیدواژه‌ی جدید را بفرستید. چند کلیدواژه را با کاما یا خط جدید جدا کنید (حداکثر ۲۰ تا؛ هرکدام تا ۶۰ حرف).")
            + "\n" + tr("مثال: کانفیگ رایگان, v2ray reality, free nodes"),
            _kb([[InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data="adm_leak_dq")]]),
        )
        await call.answer()

    @router.message(StateFilter(LeakAdmin.waiting_disc_queries))
    async def msg_disc_queries(message: Message, state: FSMContext):
        if not db.is_full_admin(message.from_user.id):
            await state.clear()
            return
        items = [k.strip() for k in re.split(r"[,\n،]", message.text or "") if k.strip()][:20]
        added = 0
        for item in items:
            if await asyncio.to_thread(db.add_leak_query, item, "admin"):
                added += 1
        await _log(message.from_user.id, "leak_query_add", ", ".join(items)[:200])
        await state.clear()
        await message.answer(
            tr("✅ کلیدواژه‌ها ذخیره شد.") + f" ({added} {tr('جدید')} / {len(items) - added} {tr('از قبل بود و فعال شد')})\n"
            + tr("در چرخه‌ی بعدی کشف استفاده می‌شوند؛ برای فوری‌بودن «▶️ اجرای فوری» را بزنید.")
        )

    # ------------------------------------------------------------ events
    @router.callback_query(F.data == "adm_leak_ev")
    async def cb_events(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        events = await asyncio.to_thread(db.list_leak_events, 10)
        lines = [tr("🧾 آخرین رویدادهای نشت"), ""]
        if not events:
            lines.append(tr("تاکنون نشتی ثبت نشده است."))
        for ev in events:
            lines.append(
                f"#{ev['id']} | {STATUS_LABELS.get(ev['status'], ev['status'])} | "
                f"{tr('کاربر')} <code>{ev['user_id']}</code> | {html.escape(ev['channel_title'] or '-')}\n"
                f"{html.escape(ev['post_link'])}"
            )
        await _show(call, "\n".join(lines), _kb([[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_leak")]]))
        await call.answer()

    # ------------------------------------------------------------ alert buttons (lk:*)
    async def _finish_alert(call: CallbackQuery, status_line: str, keep_buttons: bool = False):
        """پیام هشدار را با نتیجه‌ی اقدام به‌روز می‌کند. مگر keep_buttons، دکمه‌ها برداشته می‌شوند."""
        if call.message is None:
            return
        try:
            base = call.message.html_text or ""
            markup = call.message.reply_markup if keep_buttons else None
            await call.message.edit_text(f"{base}\n\n{status_line}", parse_mode="HTML", reply_markup=markup)
        except Exception:
            logger.debug("could not update leak alert message", exc_info=True)

    async def _event_id(call: CallbackQuery):
        try:
            return int(call.data.split(":", 2)[2])
        except (IndexError, ValueError):
            return None

    @router.callback_query(F.data.startswith("lk:rot:"))
    async def cb_rotate(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        event_id = await _event_id(call)
        if event_id is None:
            return await call.answer()
        await call.answer(tr("در حال چرخاندن لینک..."))
        ok, msg = await ls.rotate_event(db, call.bot, event_id, actor=f"ادمین {call.from_user.id}")
        await _log(call.from_user.id, "leak_rotate", f"event={event_id} ok={ok}")
        mark = "✅" if ok else "⛔️"
        await _finish_alert(call, f"{mark} {html.escape(msg)}")

    @router.callback_query(F.data.startswith("lk:warn:"))
    async def cb_warn(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        event_id = await _event_id(call)
        if event_id is None:
            return await call.answer()
        ok, msg = await ls.warn_event(db, call.bot, event_id)
        await _log(call.from_user.id, "leak_warn", f"event={event_id} ok={ok}")
        await call.answer(tr(msg) if ok else msg, show_alert=not ok)
        if ok:
            await _finish_alert(call, f"⚠️ {html.escape(msg)}", keep_buttons=True)

    @router.callback_query(F.data.startswith("lk:ign:"))
    async def cb_ignore(call: CallbackQuery):
        if not db.is_full_admin(call.from_user.id):
            return await _deny(call)
        event_id = await _event_id(call)
        if event_id is None:
            return await call.answer()
        await asyncio.to_thread(db.set_leak_event_status, event_id, "ignored")
        await _log(call.from_user.id, "leak_ignore", f"event={event_id}")
        await call.answer(tr("نادیده گرفته شد."))
        await _finish_alert(call, tr("🙈 نادیده گرفته شد."))

    return router
