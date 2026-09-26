from i18n import tr
# -*- coding: utf-8 -*-
"""صفحه‌های مدیریت داخل بات: سکه و قرعه‌کشی، کش‌بک، هدیه‌ی گروهی و ضداسپم."""

import asyncio
import html
import json
import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import bulk_gifts
import global_switch
import lottery_loop
from states import AdminBulkGift, AdminSettingInput

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

DEFAULT_LOTTERY_PRIZES = {"wallet": "50000,30000,20000", "discount": "30,20,10"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

NUM_FIELDS = {
    "lt_buy": {
        "key": "score_purchase_points", "title": "🪙 سکه‌ی هر خرید", "unit": "سکه",
        "lo": 0, "hi": 100, "presets": (0, 1, 2, 3, 5, 10), "default": 2, "card": "lottery",
        "hint": "این تعداد سکه بعد از تایید هر خرید به کاربر داده می‌شود. ۰ یعنی خرید سکه نمی‌دهد.",
    },
    "lt_ren": {
        "key": "score_renewal_points", "title": "🔄 سکه‌ی هر تمدید", "unit": "سکه",
        "lo": 0, "hi": 100, "presets": (0, 1, 2, 3, 5, 10), "default": 1, "card": "lottery",
        "hint": "این تعداد سکه بعد از تایید هر تمدید به کاربر داده می‌شود. ۰ یعنی تمدید سکه نمی‌دهد.",
    },
    "lt_ref": {
        "key": "score_referral_points", "title": "🤝 سکه‌ی هر زیرمجموعه", "unit": "سکه",
        "lo": 0, "hi": 100, "presets": (0, 1, 2, 3, 5, 10), "default": 1, "card": "lottery",
        "hint": "این تعداد سکه به‌محض عضویت هر زیرمجموعه (بدون نیاز به خرید) به دعوت‌کننده داده می‌شود. ۰ یعنی سکه نمی‌دهد.",
    },
    "lt_val": {
        "key": "coin_value_toman", "title": "💵 ارزش هر سکه", "unit": "تومان",
        "lo": 0, "hi": 10_000_000, "presets": (0, 100, 500, 1000, 2000, 5000), "default": 0, "card": "lottery",
        "hint": "هر سکه هنگام تبدیل به موجودی کیف پول چند تومان حساب شود. ۰ یعنی تبدیل سکه به موجودی غیرفعال است.",
    },
    "lt_cmin": {
        "key": "coin_convert_min", "title": "⬇️ حداقل سکه برای هر تبدیل", "unit": "سکه",
        "lo": 1, "hi": 1_000_000, "presets": (1, 5, 10, 20, 50, 100), "default": 1, "card": "lottery",
        "hint": "کاربر برای تبدیل به موجودی کیف پول حداقل این تعداد سکه را باید وارد کند.",
    },
    "lt_cmax": {
        "key": "coin_convert_max", "title": "⬆️ حداکثر سکه برای هر تبدیل", "unit": "سکه",
        "lo": 0, "hi": 10_000_000, "presets": (0, 50, 100, 200, 500, 1000), "default": 0, "card": "lottery",
        "hint": "کاربر در هر بار تبدیل حداکثر این تعداد سکه را می‌تواند وارد کند. ۰ یعنی بدون سقف.",
    },
    "lt_min": {
        "key": "lottery_min_coins", "title": "🎟 حداقل سکه برای ورود به قرعه‌کشی", "unit": "سکه",
        "lo": 1, "hi": 1_000_000, "presets": (1, 5, 10, 20, 50, 100), "default": 1, "card": "lottery",
        "hint": "فقط کاربرانی که حالت سکه‌شان «قرعه‌کشی» است و حداقل این تعداد سکه دارند وارد قرعه‌کشی می‌شوند.",
    },
    "lt_cexp": {
        "key": "coin_expiry_days", "title": "⏳ مهلت استفاده از سکه", "unit": "روز",
        "lo": 0, "hi": 3650, "presets": (0, 3, 7, 14, 30, 60), "default": 7, "card": "lottery",
        "hint": "هر سکه از لحظه‌ی دریافت این تعداد روز اعتبار دارد و بعد از آن سوخت می‌شود. ۰ یعنی بدون انقضا. فقط روی سکه‌های جدید اثر دارد.",
    },
    "lt_wexp": {
        "key": "coin_wallet_expiry_days", "title": "⏳ مهلت استفاده از موجودی حاصل از سکه", "unit": "روز",
        "lo": 0, "hi": 3650, "presets": (0, 3, 7, 14, 30, 60), "default": 7, "card": "lottery",
        "hint": "مبلغی که از تبدیل سکه به کیف پول اضافه می‌شود از لحظه‌ی تبدیل این تعداد روز اعتبار دارد و باقی‌مانده‌اش بعد از آن از کیف پول کم می‌شود. ۰ یعنی بدون انقضا. فقط روی تبدیل‌های جدید اثر دارد.",
    },
    "lt_exp": {
        "key": "lottery_discount_expiry_hours", "title": "⏳ اعتبار کد تخفیف جایزه", "unit": "ساعت",
        "lo": 1, "hi": 720, "presets": (6, 12, 24, 48, 72, 168), "default": 24, "card": "lottery",
        "hint": "فقط وقتی نوع جایزه «کد تخفیف» باشد اعمال می‌شود.",
    },
    "cb_ren": {
        "key": "renewal_cashback_percent", "title": "🔄 کش‌بک تمدید سرویس", "unit": "درصد",
        "lo": 0, "hi": 100, "presets": (0, 2, 5, 10, 15, 20), "default": 0, "card": "cashback",
        "hint": "بعد از تایید هر تمدید، این درصد از مبلغی که کاربر خارج از کیف پول پرداخته به کیف پولش برمی‌گردد. ۰ یعنی خاموش.",
    },
    "cb_top": {
        "key": "topup_cashback_percent", "title": "👛 کش‌بک شارژ کیف پول", "unit": "درصد",
        "lo": 0, "hi": 100, "presets": (0, 2, 5, 10, 15, 20), "default": 0, "card": "cashback",
        "hint": "بعد از تایید هر شارژ، این درصد از مبلغ شارژ به‌عنوان هدیه به کیف پول اضافه می‌شود. ۰ یعنی خاموش.",
    },
    "sp_lim": {
        "key": "spam_limit", "title": "🔢 حداکثر درخواست مجاز", "unit": "درخواست",
        "lo": 5, "hi": 500, "presets": (15, 25, 35, 50, 80, 120), "default": 35, "card": "spam",
        "hint": "تعداد پیام و دکمه‌ای که یک کاربر در بازه‌ی زمانی زیر می‌تواند بفرستد.",
    },
    "sp_win": {
        "key": "spam_window", "title": "⏱ بازه‌ی زمانی", "unit": "ثانیه",
        "lo": 10, "hi": 600, "presets": (30, 60, 120, 300), "default": 60, "card": "spam",
        "hint": "درخواست‌ها در این بازه شمرده می‌شوند.",
    },
}

CARD_BACK = {
    "lottery": "adm_lottery_settings",
    "cashback": "adm_cashback_settings",
    "spam": "adm_spam_settings",
}


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _num(text) -> str:
    return (text or "").strip().translate(_DIGITS).replace(",", "").replace("٬", "")


def _on(flag) -> str:
    return "🟢 روشن" if flag else "🔴 خاموش"


def _days(value) -> str:
    return f"{int(value)} روز" if int(value) > 0 else "بدون انقضا"


def _fmt_prize(value, prize_type: str) -> str:
    return f"{int(value)}٪ تخفیف" if prize_type == "discount" else f"{int(value):,} تومان"


def _who(row) -> str:
    username = row.get("username") if isinstance(row, dict) else None
    if username:
        return html.escape(f"@{username}")
    name = (row.get("first_name") if isinstance(row, dict) else None) or ""
    uid = row.get("user_id") or row.get("telegram_id") or ""
    return html.escape(name) if name else str(uid)


def register(router: Router, db, is_main_bot, full_admin_only, senior_admin_only,
             deny_support, deny_mid, safe_edit, replace_admin_view):

    card_renderers = {}

    async def _present(target, text: str, markup):
        if isinstance(target, CallbackQuery):
            await replace_admin_view(target, text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)

    # ------------------------------------------------------------------
    # ویرایشگر عددی مشترک (سکه، کش‌بک، ضداسپم)
    # ------------------------------------------------------------------

    @router.callback_query(F.data.startswith("adm_ns:"))
    async def cb_num_open(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        code = call.data.split(":", 1)[1]
        field = NUM_FIELDS.get(code)
        if not field:
            return await call.answer()
        current = await asyncio.to_thread(db.get_setting, field["key"], str(field["default"]))
        await state.set_state(AdminSettingInput.waiting_value)
        await state.update_data(ns_code=code)
        presets = [_btn(f"{v}", f"adm_nsv:{code}:{v}") for v in field["presets"]]
        rows = [presets[i:i + 3] for i in range(0, len(presets), 3)]
        rows.append([_btn("⬅️ بازگشت", CARD_BACK[field["card"]])])
        text = (
            f"{field['title']}\n\n"
            f"{field['hint']}\n\n"
            f"مقدار فعلی: {current} {field['unit']}\n\n"
            f"یکی از گزینه‌های سریع را بزن یا یک عدد بین {field['lo']} تا {field['hi']} بفرست."
        )
        await replace_admin_view(call, text, reply_markup=_kb(rows))
        await call.answer()

    async def _save_num(target, state: FSMContext, code: str, value: int):
        field = NUM_FIELDS[code]
        await asyncio.to_thread(db.set_setting, field["key"], str(value))
        await state.clear()
        text, markup = await card_renderers[field["card"]](f"✅ {field['title']} روی {value} {field['unit']} تنظیم شد.")
        await _present(target, text, markup)

    @router.callback_query(F.data.startswith("adm_nsv:"))
    async def cb_num_preset(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, code, raw = call.data.split(":", 2)
            value = int(raw)
        except ValueError:
            return await call.answer()
        field = NUM_FIELDS.get(code)
        if not field or not field["lo"] <= value <= field["hi"]:
            return await call.answer()
        await _save_num(call, state, code, value)
        await call.answer(tr("ذخیره شد."))

    @router.message(AdminSettingInput.waiting_value)
    async def msg_num_value(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        data = await state.get_data()
        code = data.get("ns_code")
        field = NUM_FIELDS.get(code)
        if not field:
            await state.clear()
            return
        try:
            value = int(_num(message.text))
            if not field["lo"] <= value <= field["hi"]:
                raise ValueError
        except ValueError:
            await message.answer(tr(f"❌ یک عدد صحیح بین {field['lo']} تا {field['hi']} بفرست."))
            return
        await _save_num(message, state, code, value)

    # ------------------------------------------------------------------
    # سکه و قرعه‌کشی شبانه
    # ------------------------------------------------------------------

    def _lottery_snapshot():
        s = db.get_lottery_settings()

        def points(key, default):
            try:
                return max(0, int(db.get_setting(key, str(default)) or 0))
            except (TypeError, ValueError):
                return default

        last = db.list_lottery_logs(1)
        return {
            "s": s,
            "buy": points("score_purchase_points", 2),
            "ren": points("score_renewal_points", 1),
            "ref": points("score_referral_points", 1),
            "participants": db.count_score_participants(s["agent_enabled"]),
            "coin": db.get_coin_settings(),
            "last": last[0] if last else None,
        }

    async def _lottery_view(note: str = ""):
        snap = await asyncio.to_thread(_lottery_snapshot)
        s = snap["s"]
        wallet = s["prize_type"] != "discount"
        ptype = "wallet" if wallet else "discount"
        prizes = " | ".join(f"{MEDALS[i + 1]} {_fmt_prize(v, ptype)}" for i, v in enumerate(s["prizes"]))
        report = f"گروه {s['report_chat_id']}" if s["report_chat_id"] else "پیام خصوصی ادمین‌ها"
        last = "هنوز انجام نشده"
        if snap["last"]:
            last = str(snap["last"]["lottery_date"])[:10]
        lines = []
        if note:
            lines += [note, ""]
        lines += [
            "🪙 سکه و قرعه‌کشی شبانه",
            "",
            "هر خرید، تمدید و زیرمجموعه‌ی جدید به کاربر سکه می‌دهد. کاربر انتخاب می‌کند سکه‌هایش برای قرعه‌کشی باشد یا به موجودی کیف پول تبدیل شود. "
            "هر شب ساعت ۰۰:۰۰ (به وقت سرور) سه نفر با بیشترین سکه بین شرکت‌کنندگان برنده می‌شوند و سکه‌ی همه‌ی شرکت‌کنندگان صفر می‌شود.",
            "",
            f"• سیستم سکه: {_on(s['score_enabled'])}",
            f"• قرعه‌کشی شبانه: {_on(s['enabled'])}",
            f"• شمول نماینده‌ها: {'✅ بله' if s['agent_enabled'] else '❌ خیر'}",
            f"• نوع جایزه: {'💰 شارژ کیف پول' if wallet else '🎟 کد تخفیف'}",
            f"• جایزه‌ها: {prizes}",
        ]
        if not wallet:
            lines.append(f"• اعتبار کد تخفیف: {s['discount_expiry_hours']} ساعت")
        lines += [
            f"• سکه‌ی هر خرید: {snap['buy']} | تمدید: {snap['ren']} | زیرمجموعه: {snap['ref']}",
            f"• ارزش هر سکه: {snap['coin']['value']:,} تومان" + ("" if snap["coin"]["value"] else " (تبدیل غیرفعال)"),
            f"• تبدیل به کیف پول: حداقل {snap['coin']['convert_min']:,} | حداکثر "
            + (f"{snap['coin']['convert_max']:,}" if snap["coin"]["convert_max"] else "بدون سقف") + " سکه",
            f"• حداقل سکه برای قرعه‌کشی: {snap['coin']['lottery_min']:,}",
            f"• مهلت استفاده از سکه: {_days(snap['coin']['expiry_days'])} | از موجودی حاصل از سکه: {_days(snap['coin']['wallet_expiry_days'])}",
            f"• گزارش برندگان: {report}",
            "",
            f"👥 شرکت‌کنندگان واجد شرایط قرعه‌کشی: {snap['participants']:,} نفر",
            f"🕘 آخرین قرعه‌کشی: {last}",
        ]
        if not (s["score_enabled"] and s["enabled"]):
            lines += ["", "⚠️ قرعه‌کشی فقط وقتی هم «سیستم سکه» و هم «قرعه‌کشی شبانه» روشن باشند اجرا می‌شود."]
        rows = [
            [_btn(f"سکه: {_on(s['score_enabled'])}", "adm_lt_toggle:score"),
             _btn(f"قرعه‌کشی: {_on(s['enabled'])}", "adm_lt_toggle:lottery")],
            [_btn(f"نماینده‌ها: {'✅ شامل' if s['agent_enabled'] else '❌ خارج'}", "adm_lt_toggle:agent")],
            [_btn(f"جایزه: {'💰 کیف پول' if wallet else '🎟 کد تخفیف'} (زدن = تغییر)", "adm_lt_toggle:prize")],
            [_btn("🥇🥈🥉 ویرایش مقدار جایزه‌ها", "adm_lt_prizes")],
        ]
        if not wallet:
            rows.append([_btn(f"⏳ اعتبار کد تخفیف: {s['discount_expiry_hours']} ساعت", "adm_ns:lt_exp")])
        rows += [
            [_btn(f"🪙 خرید: {snap['buy']}", "adm_ns:lt_buy"),
             _btn(f"🔄 تمدید: {snap['ren']}", "adm_ns:lt_ren"),
             _btn(f"🤝 زیرمجموعه: {snap['ref']}", "adm_ns:lt_ref")],
            [_btn(f"💵 ارزش هر سکه: {snap['coin']['value']:,} تومان", "adm_ns:lt_val")],
            [_btn(f"⬇️ حداقل تبدیل: {snap['coin']['convert_min']:,}", "adm_ns:lt_cmin"),
             _btn("⬆️ حداکثر تبدیل: " + (f"{snap['coin']['convert_max']:,}" if snap["coin"]["convert_max"] else "∞"), "adm_ns:lt_cmax")],
            [_btn(f"🎟 حداقل سکه قرعه‌کشی: {snap['coin']['lottery_min']:,}", "adm_ns:lt_min")],
            [_btn(f"⏳ مهلت سکه: {_days(snap['coin']['expiry_days'])}", "adm_ns:lt_cexp"),
             _btn(f"⏳ مهلت موجودی: {_days(snap['coin']['wallet_expiry_days'])}", "adm_ns:lt_wexp")],
            [_btn(f"📣 مقصد گزارش: {'گروه' if s['report_chat_id'] else 'ادمین‌ها'}", "adm_lt_report")],
            [_btn("🏆 جدول سکه‌ها", "adm_lt_top"), _btn("📜 نتایج قبلی", "adm_lt_history")],
            [_btn("▶️ اجرای قرعه‌کشی همین حالا", "adm_lt_run")],
            [_btn("⬅️ بازگشت", "adm_cat:marketing")],
        ]
        return "\n".join(lines), _kb(rows)

    @router.callback_query(F.data == "adm_lottery_settings")
    async def cb_lottery_menu(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        text, markup = await _lottery_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_lt_toggle:"))
    async def cb_lottery_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        what = call.data.split(":", 1)[1]
        simple = {
            "score": ("score_enabled", "1"),
            "lottery": ("lottery_enabled", "1"),
            "agent": ("lottery_agent_enabled", "0"),
        }
        note = ""
        if what == "prize":
            cur = await asyncio.to_thread(db.get_setting, "lottery_prize_type", "wallet")
            new = "discount" if cur != "discount" else "wallet"
            await asyncio.to_thread(db.set_setting, "lottery_prize_type", new)
            s = await asyncio.to_thread(db.get_lottery_settings)
            out_of_range = any(v > 100 for v in s["prizes"]) if new == "discount" else all(v <= 100 for v in s["prizes"])
            if out_of_range:
                await asyncio.to_thread(db.set_setting, "lottery_prizes", DEFAULT_LOTTERY_PRIZES[new])
                note = "ℹ️ چون واحد جایزه عوض شد، مقدار جایزه‌ها به پیش‌فرض برگشت. اگر می‌خواهی تغییرشان بده."
        elif what in simple:
            key, default = simple[what]
            cur = await asyncio.to_thread(db.get_setting, key, default)
            await asyncio.to_thread(db.set_setting, key, "0" if cur == "1" else "1")
        else:
            return await call.answer()
        text, markup = await _lottery_view(note)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    @router.callback_query(F.data == "adm_lt_prizes")
    async def cb_lottery_prizes(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        s = await asyncio.to_thread(db.get_lottery_settings)
        wallet = s["prize_type"] != "discount"
        ptype = "wallet" if wallet else "discount"
        current = " | ".join(f"{MEDALS[i + 1]} {_fmt_prize(v, ptype)}" for i, v in enumerate(s["prizes"]))
        if wallet:
            body = "سه مبلغ (به تومان) برای نفر اول، دوم و سوم بفرست؛ با کاما یا فاصله جدا کن.\nمثال: 50000,30000,20000"
        else:
            body = "سه درصد تخفیف (۱ تا ۱۰۰) برای نفر اول، دوم و سوم بفرست؛ با کاما یا فاصله جدا کن.\nمثال: 30,20,10"
        await state.set_state(AdminSettingInput.waiting_prizes)
        await replace_admin_view(
            call, f"🥇🥈🥉 مقدار جایزه‌ها\n\nمقدار فعلی: {current}\n\n{body}",
            reply_markup=_kb([[_btn("⬅️ بازگشت", "adm_lottery_settings")]]),
        )
        await call.answer()

    @router.message(AdminSettingInput.waiting_prizes)
    async def msg_lottery_prizes(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        parts = [p for p in re.split(r"[\s,،;]+", _num(message.text)) if p]
        prize_type = await asyncio.to_thread(db.get_setting, "lottery_prize_type", "wallet")
        limit = 100 if prize_type == "discount" else 1_000_000_000
        if len(parts) != 3 or not all(p.isdigit() and 0 < int(p) <= limit for p in parts):
            unit = "درصد بین ۱ تا ۱۰۰" if prize_type == "discount" else "مبلغ مثبت"
            example = DEFAULT_LOTTERY_PRIZES["discount" if prize_type == "discount" else "wallet"]
            await message.answer(tr(f"❌ دقیقاً سه عدد ({unit}) بفرست؛ مثال: {example}"))
            return
        await asyncio.to_thread(db.set_setting, "lottery_prizes", ",".join(str(int(p)) for p in parts))
        await state.clear()
        text, markup = await _lottery_view("✅ مقدار جایزه‌ها ذخیره شد.")
        await message.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_lt_report")
    async def cb_lottery_report(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        s = await asyncio.to_thread(db.get_lottery_settings)
        current = f"گروه {s['report_chat_id']}" if s["report_chat_id"] else "پیام خصوصی ادمین‌ها"
        await state.set_state(AdminSettingInput.waiting_report_chat)
        await replace_admin_view(
            call,
            "📣 مقصد گزارش قرعه‌کشی\n\n"
            f"مقدار فعلی: {current}\n\n"
            "آیدی عددی گروه را بفرست (مثل -1001234567890).\n"
            "برای گرفتن آیدی: ربات @myidbot را به گروه اضافه کن و داخل گروه /getgroupid@myidbot را بفرست.\n"
            "ربات خودت هم باید عضو گروه باشد.",
            reply_markup=_kb([
                [_btn("📥 ارسال برای ادمین‌ها (بدون گروه)", "adm_lt_report_clear")],
                [_btn("⬅️ بازگشت", "adm_lottery_settings")],
            ]),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_lt_report_clear")
    async def cb_lottery_report_clear(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await asyncio.to_thread(db.set_setting, "lottery_report_chat_id", "")
        await state.clear()
        text, markup = await _lottery_view("✅ گزارش قرعه‌کشی برای ادمین‌ها ارسال می‌شود.")
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    @router.message(AdminSettingInput.waiting_report_chat)
    async def msg_lottery_report(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        raw = _num(message.text)
        try:
            chat_id = int(raw)
        except ValueError:
            await message.answer(tr("❌ آیدی گروه باید عددی باشد؛ مثال: -1001234567890"))
            return
        await asyncio.to_thread(db.set_setting, "lottery_report_chat_id", "" if chat_id == 0 else str(chat_id))
        await state.clear()
        text, markup = await _lottery_view("✅ مقصد گزارش قرعه‌کشی ذخیره شد.")
        await message.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_lt_top")
    async def cb_lottery_top(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        s = await asyncio.to_thread(db.get_lottery_settings)
        rows = await asyncio.to_thread(db.get_score_leaderboard, 10, s["agent_enabled"])
        if not rows:
            body = "هنوز هیچ کاربر واجد شرایطی برای قرعه‌کشی وجود ندارد."
        else:
            lines = []
            for i, r in enumerate(rows, 1):
                info = {"username": r["username"], "first_name": r["first_name"], "user_id": r["telegram_id"]}
                lines.append(f"{MEDALS.get(i, str(i) + '.')} {_who(info)} ({r['telegram_id']}) — {r['score']} سکه")
            body = "\n".join(lines)
        await replace_admin_view(
            call, f"🏆 جدول سکه‌ها (۱۰ نفر برتر شرکت‌کنندگان)\n\n{body}",
            reply_markup=_kb([[_btn("⬅️ بازگشت", "adm_lottery_settings")]]),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_lt_history")
    async def cb_lottery_history(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        logs = await asyncio.to_thread(db.list_lottery_logs, 5)
        blocks = []
        for log in logs:
            try:
                winners = json.loads(log["winners_json"] or "[]")
            except (TypeError, ValueError):
                winners = []
            ptype = log["prize_type"] or "wallet"
            lines = [f"📅 {str(log['lottery_date'])[:10]}"]
            for w in winners:
                lines.append(f"{MEDALS.get(w.get('rank'), '🏅')} {_who(w)} — {w.get('score', 0)} سکه — {_fmt_prize(w.get('prize', 0), ptype)}")
            blocks.append("\n".join(lines))
        body = "\n\n".join(blocks) if blocks else "هنوز قرعه‌کشی‌ای انجام نشده."
        await replace_admin_view(
            call, f"📜 نتایج قرعه‌کشی‌های قبلی\n\n{body}",
            reply_markup=_kb([[_btn("⬅️ بازگشت", "adm_lottery_settings")]]),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_lt_run")
    async def cb_lottery_run(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await replace_admin_view(
            call,
            "▶️ اجرای قرعه‌کشی همین حالا\n\n"
            "سه نفر برتر همین الان انتخاب می‌شوند، جایزه‌ها داده می‌شود و سکه‌ی همه‌ی شرکت‌کنندگان صفر می‌شود. "
            "این کار قابل بازگشت نیست. مطمئنی؟",
            reply_markup=_kb([
                [_btn("✅ بله، اجرا کن", "adm_lt_run_ok")],
                [_btn("❌ انصراف", "adm_lottery_settings")],
            ]),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_lt_run_ok")
    async def cb_lottery_run_ok(call: CallbackQuery, bot: Bot):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        stamp = datetime.now().strftime("%Y-%m-%d-manual-%H%M%S")
        try:
            result = await lottery_loop.lottery_once(bot, db, stamp)
            status = result.get("status")
        except Exception as exc:
            status = "error"
            result = {"error": str(exc)}
        if status == "completed":
            note = "✅ قرعه‌کشی انجام شد. نتیجه برای برندگان و مقصد گزارش ارسال شد."
        elif status == "disabled":
            note = "⚠️ قرعه‌کشی انجام نشد چون «سیستم سکه» یا «قرعه‌کشی شبانه» خاموش است."
        elif status == "already_done":
            note = "⚠️ همین چند ثانیه پیش یک قرعه‌کشی اجرا شده است؛ کمی بعد دوباره تلاش کن."
        elif status == "no_winners":
            note = "⚠️ هیچ کاربر واجد شرایطی برای قرعه‌کشی پیدا نشد."
        else:
            note = f"❌ اجرای قرعه‌کشی ناموفق بود: {html.escape(str(result.get('error') or status))}"
        text, markup = await _lottery_view(note)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    # ------------------------------------------------------------------
    # کش‌بک
    # ------------------------------------------------------------------

    def _cashback_snapshot():
        def percent(key):
            try:
                return max(0, min(int(db.get_setting(key, "0") or 0), 100))
            except (TypeError, ValueError):
                return 0
        return percent("renewal_cashback_percent"), percent("topup_cashback_percent"), db.get_cashback_totals()

    async def _cashback_view(note: str = ""):
        renewal, topup, totals = await asyncio.to_thread(_cashback_snapshot)
        lines = []
        if note:
            lines += [note, ""]
        lines += [
            "💸 کش‌بک تمدید و شارژ",
            "",
            "بعد از تایید هر پرداخت، درصدی از مبلغ به‌صورت خودکار به کیف پول کاربر برمی‌گردد. ۰ یعنی خاموش.",
            "",
            f"🔄 کش‌بک تمدید سرویس: {renewal}٪" if renewal else "🔄 کش‌بک تمدید سرویس: 🔴 خاموش",
            f"👛 کش‌بک شارژ کیف پول: {topup}٪" if topup else "👛 کش‌بک شارژ کیف پول: 🔴 خاموش",
            "",
            "📊 مجموع کش‌بک پرداخت‌شده تا امروز:",
            f"• تمدید: {totals['renewal_count']:,} بار، {totals['renewal_total']:,} تومان",
            f"• شارژ کیف پول: {totals['topup_count']:,} بار، {totals['topup_total']:,} تومان",
        ]
        rows = [
            [_btn(f"🔄 کش‌بک تمدید: {renewal}٪", "adm_ns:cb_ren")],
            [_btn(f"👛 کش‌بک شارژ کیف پول: {topup}٪", "adm_ns:cb_top")],
            [_btn("⛔️ خاموش کردن هر دو", "adm_cb_off")],
            [_btn("⬅️ بازگشت", "adm_cat:marketing")],
        ]
        return "\n".join(lines), _kb(rows)

    @router.callback_query(F.data == "adm_cashback_settings")
    async def cb_cashback_menu(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        text, markup = await _cashback_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "adm_cb_off")
    async def cb_cashback_off(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await asyncio.to_thread(db.set_setting, "renewal_cashback_percent", "0")
        await asyncio.to_thread(db.set_setting, "topup_cashback_percent", "0")
        text, markup = await _cashback_view("✅ کش‌بک تمدید و شارژ خاموش شد.")
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    # ------------------------------------------------------------------
    # ضداسپم
    # ------------------------------------------------------------------

    def _spam_snapshot():
        def value(key, default):
            try:
                return max(1, int(db.get_setting(key, str(default)) or default))
            except (TypeError, ValueError):
                return default
        return db.get_setting("spam_guard_enabled", "1") == "1", value("spam_limit", 35), value("spam_window", 60)

    async def _spam_view(note: str = ""):
        enabled, limit, window = await asyncio.to_thread(_spam_snapshot)
        lines = []
        if note:
            lines += [note, ""]
        lines += [
            "🛡 ضداسپم کاربران",
            "",
            "اگر کاربری در بازه‌ی زمانی زیر بیش از حد مجاز پیام یا دکمه بفرستد، بار اول یک دقیقه نادیده گرفته می‌شود "
            "و همان‌جا به او هشدار داده می‌شود. اگر تکرار کند، خودکار مسدود می‌شود و به ادمین‌ها اطلاع می‌رسد. "
            "ادمین‌ها هرگز محدود نمی‌شوند.",
            "",
            f"وضعیت: {_on(enabled)}",
            f"حد مجاز: {limit} درخواست در {window} ثانیه",
            "",
            "برای رفع مسدودیت یک کاربر از پنل وب یا مینی‌اپ (بخش کاربران) اقدام کن.",
        ]
        rows = [
            [_btn(f"{'🔴 خاموش کردن' if enabled else '🟢 روشن کردن'} ضداسپم", "adm_spam_toggle")],
            [_btn(f"🔢 حد مجاز: {limit} درخواست", "adm_ns:sp_lim"),
             _btn(f"⏱ بازه: {window} ثانیه", "adm_ns:sp_win")],
            [_btn("♻️ بازگشت به پیش‌فرض (۳۵ درخواست در ۶۰ ثانیه)", "adm_spam_reset")],
            [_btn("⬅️ بازگشت", "adm_cat:management")],
        ]
        return "\n".join(lines), _kb(rows)

    @router.callback_query(F.data == "adm_spam_settings")
    async def cb_spam_menu(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        text, markup = await _spam_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "adm_spam_toggle")
    async def cb_spam_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cur = await asyncio.to_thread(db.get_setting, "spam_guard_enabled", "1")
        await asyncio.to_thread(db.set_setting, "spam_guard_enabled", "0" if cur == "1" else "1")
        text, markup = await _spam_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    @router.callback_query(F.data == "adm_spam_reset")
    async def cb_spam_reset(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await asyncio.to_thread(db.set_setting, "spam_limit", "35")
        await asyncio.to_thread(db.set_setting, "spam_window", "60")
        text, markup = await _spam_view("✅ تنظیمات ضداسپم به پیش‌فرض برگشت.")
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    # ------------------------------------------------------------------
    # سوئیچ سراسری ربات (خاموش/روشن کردن ربات برای کاربران عادی)
    # ------------------------------------------------------------------

    def _gswitch_snapshot():
        enabled = str(db.get_setting(global_switch.SETTING_KEY, "1")).strip() != "0"
        off_text = (db.get_setting(global_switch.TEXT_KEY, "") or "").strip() or global_switch.DEFAULT_OFF_TEXT
        return enabled, off_text

    async def _gswitch_view(note: str = ""):
        enabled, off_text = await asyncio.to_thread(_gswitch_snapshot)
        lines = []
        if note:
            lines += [note, ""]
        lines += [
            "🔌 سوئیچ سراسری ربات",
            "",
            "با خاموش کردن، ربات تلگرام برای همه‌ی کاربران عادی متوقف می‌شود و آن‌ها فقط پیام "
            "«ربات غیرفعال است» را می‌بینند. ادمین‌ها همچنان به ربات و همین پنل دسترسی دارند. "
            "مینی‌اپ و پنل وب تحت تأثیر این کلید نیستند.",
            "",
            f"وضعیت: {_on(enabled)}",
            f"پیام نمایش‌داده‌شده به کاربران در حالت خاموش:\n{html.escape(off_text)}",
        ]
        if enabled:
            rows = [[_btn("🔴 خاموش کردن ربات", "adm_gswitch_ask")]]
        else:
            rows = [[_btn("🟢 روشن کردن ربات", "adm_gswitch_on")]]
        rows.append([_btn("⬅️ بازگشت", "adm_cat:management")])
        return "\n".join(lines), _kb(rows)

    @router.callback_query(F.data == "adm_gswitch")
    async def cb_gswitch_menu(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        text, markup = await _gswitch_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "adm_gswitch_ask")
    async def cb_gswitch_ask(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        text = (
            "⚠️ مطمئنی می‌خواهی ربات را خاموش کنی؟\n\n"
            "از همین لحظه هیچ کاربر عادی نمی‌تواند خرید، تمدید یا هیچ کار دیگری در ربات انجام دهد. "
            "هر وقت خواستی از همین صفحه دوباره روشنش کن."
        )
        markup = _kb([
            [_btn("✅ بله، خاموش کن", "adm_gswitch_off")],
            [_btn("❌ انصراف", "adm_gswitch")],
        ])
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data.in_({"adm_gswitch_off", "adm_gswitch_on"}))
    async def cb_gswitch_set(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        turn_on = call.data == "adm_gswitch_on"
        await asyncio.to_thread(db.set_setting, global_switch.SETTING_KEY, "1" if turn_on else "0")
        note = "🟢 ربات دوباره روشن شد." if turn_on else "🔴 ربات برای کاربران عادی خاموش شد."
        text, markup = await _gswitch_view(note)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    card_renderers.update({"lottery": _lottery_view, "cashback": _cashback_view, "spam": _spam_view})

    # ------------------------------------------------------------------
    # هدیه‌ی گروهی حجم/زمان (ویزارد دکمه‌ای)
    # ------------------------------------------------------------------

    async def _bg_data(state: FSMContext) -> dict:
        d = await state.get_data()
        return {
            "panel": int(d.get("bg_panel") or 0),
            "users": [int(x) for x in (d.get("bg_users") or [])],
            "volume": float(d.get("bg_volume") or 0),
            "days": int(d.get("bg_days") or 0),
        }

    async def _bg_panel_name(panel_id: int) -> str:
        if not panel_id:
            return "همه‌ی پنل‌ها"
        server = await asyncio.to_thread(db.get_panel_server, panel_id)
        return server["name"] if server else f"#{panel_id}"

    def _bg_amounts(d: dict):
        volume = f"{d['volume']:g} گیگ" if d["volume"] > 0 else "بدون حجم"
        days = f"{d['days']} روز" if d["days"] > 0 else "بدون زمان"
        return volume, days

    async def _bg_view(state: FSMContext, note: str = ""):
        d = await _bg_data(state)
        panel_name = await _bg_panel_name(d["panel"])
        users_txt = f"{len(d['users'])} کاربر مشخص" if d["users"] else "همه‌ی کاربران"
        volume, days = _bg_amounts(d)
        count = await asyncio.to_thread(db.count_bulk_gift_targets, d["panel"] or None, d["users"])
        lines = []
        if note:
            lines += [note, ""]
        lines += [
            "🎁 هدیه‌ی گروهی",
            "",
            "به سرویس‌های فعال کاربران حجم یا زمان هدیه بده. سرویس‌های تست شامل نمی‌شوند.",
            "",
            f"🖥 پنل هدف: {html.escape(panel_name)}",
            f"👤 کاربران هدف: {users_txt}",
            f"📦 حجم هدیه: {volume}",
            f"⏳ زمان هدیه: {days}",
            "",
            f"🎯 تعداد سرویس مشمول: {count:,}",
        ]
        if not d["panel"] and not d["users"]:
            lines += ["", "⚠️ برای ادامه باید یک پنل یا چند کاربر را انتخاب کنی."]
        rows = [
            [_btn(f"🖥 پنل: {panel_name}", "adm_bg_panel"),
             _btn(f"👤 کاربران: {len(d['users']) or 'همه'}", "adm_bg_users")],
            [_btn(f"📦 حجم: {volume}", "adm_bg_vol"), _btn(f"⏳ زمان: {days}", "adm_bg_days")],
            [_btn("✅ بررسی و شروع", "adm_bg_review")],
            [_btn("📋 عملیات‌های اخیر", "adm_bg_jobs")],
            [_btn("⬅️ بازگشت", "adm_cat:marketing")],
        ]
        return "\n".join(lines), _kb(rows)

    @router.callback_query(F.data == "adm_bulk_gift")
    async def cb_bg_start(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.clear()
        text, markup = await _bg_view(state)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "adm_bg_view")
    async def cb_bg_view(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(None)
        text, markup = await _bg_view(state)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "adm_bg_panel")
    async def cb_bg_panel(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        servers = await asyncio.to_thread(db.get_panel_servers, True)
        rows = [[_btn("🌐 همه‌ی پنل‌ها", "adm_bg_panel_set:0")]]
        rows += [[_btn(f"🖥 {s['name']}", f"adm_bg_panel_set:{s['id']}")] for s in servers]
        rows.append([_btn("⬅️ بازگشت", "adm_bg_view")])
        await replace_admin_view(call, "🖥 پنل هدف هدیه را انتخاب کن:", reply_markup=_kb(rows))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_bg_panel_set:"))
    async def cb_bg_panel_set(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        try:
            panel_id = int(call.data.split(":", 1)[1])
        except ValueError:
            return await call.answer()
        await state.update_data(bg_panel=panel_id)
        text, markup = await _bg_view(state)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "adm_bg_users")
    async def cb_bg_users(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminBulkGift.waiting_users)
        await replace_admin_view(
            call,
            "👤 کاربران هدف\n\n"
            "آیدی عددی کاربران را بفرست. چند آیدی را با فاصله، کاما یا خط جدید جدا کن.\n"
            "فقط سرویس‌های همین کاربران هدیه می‌گیرند.",
            reply_markup=_kb([
                [_btn("🗑 حذف فیلتر کاربران (همه)", "adm_bg_users_clear")],
                [_btn("⬅️ بازگشت", "adm_bg_view")],
            ]),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_bg_users_clear")
    async def cb_bg_users_clear(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(None)
        await state.update_data(bg_users=[])
        text, markup = await _bg_view(state)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.message(AdminBulkGift.waiting_users)
    async def msg_bg_users(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            return
        tokens = [t for t in re.split(r"[\s,،;]+", _num(message.text)) if t]
        if not tokens or not all(t.isdigit() for t in tokens):
            await message.answer(tr("❌ فقط آیدی‌های عددی را بفرست؛ مثال: 123456789 987654321"))
            return
        users = sorted({int(t) for t in tokens})
        await state.set_state(None)
        await state.update_data(bg_users=users)
        text, markup = await _bg_view(state, f"✅ {len(users)} کاربر انتخاب شد.")
        await message.answer(text, reply_markup=markup)

    def _preset_rows(prefix: str, values, unit: str):
        buttons = [_btn(f"{v} {unit}", f"{prefix}:{v}") for v in values]
        return [buttons[i:i + 3] for i in range(0, len(buttons), 3)]

    @router.callback_query(F.data == "adm_bg_vol")
    async def cb_bg_vol(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminBulkGift.waiting_volume)
        rows = _preset_rows("adm_bg_vol_set", (1, 2, 5, 10, 20, 50), "گیگ")
        rows.append([_btn("بدون حجم (۰)", "adm_bg_vol_set:0")])
        rows.append([_btn("⬅️ بازگشت", "adm_bg_view")])
        await replace_admin_view(
            call,
            "📦 حجم هدیه به هر سرویس\n\nیکی از گزینه‌ها را بزن یا مقدار دلخواه را به گیگابایت بفرست (مثل 2.5).",
            reply_markup=_kb(rows),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_bg_vol_set:"))
    async def cb_bg_vol_set(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        try:
            volume = float(call.data.split(":", 1)[1])
        except ValueError:
            return await call.answer()
        await state.set_state(None)
        await state.update_data(bg_volume=max(0.0, volume))
        text, markup = await _bg_view(state)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.message(AdminBulkGift.waiting_volume)
    async def msg_bg_volume(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            return
        try:
            volume = float(_num(message.text).replace("٫", "."))
            if volume < 0 or volume > 100000:
                raise ValueError
        except ValueError:
            await message.answer(tr("❌ یک عدد بین ۰ تا ۱۰۰۰۰۰ بفرست؛ مثال: 5 یا 2.5"))
            return
        await state.set_state(None)
        await state.update_data(bg_volume=volume)
        text, markup = await _bg_view(state)
        await message.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_bg_days")
    async def cb_bg_days(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        await state.set_state(AdminBulkGift.waiting_days)
        rows = _preset_rows("adm_bg_days_set", (1, 3, 7, 15, 30, 60), "روز")
        rows.append([_btn("بدون زمان (۰)", "adm_bg_days_set:0")])
        rows.append([_btn("⬅️ بازگشت", "adm_bg_view")])
        await replace_admin_view(
            call,
            "⏳ زمان هدیه به هر سرویس\n\nیکی از گزینه‌ها را بزن یا تعداد روز دلخواه را بفرست.",
            reply_markup=_kb(rows),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("adm_bg_days_set:"))
    async def cb_bg_days_set(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        try:
            days = int(call.data.split(":", 1)[1])
        except ValueError:
            return await call.answer()
        await state.set_state(None)
        await state.update_data(bg_days=max(0, days))
        text, markup = await _bg_view(state)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.message(AdminBulkGift.waiting_days)
    async def msg_bg_days(message: Message, state: FSMContext):
        if not full_admin_only(message.from_user.id):
            return
        try:
            days = int(_num(message.text))
            if days < 0 or days > 3650:
                raise ValueError
        except ValueError:
            await message.answer(tr("❌ یک عدد صحیح بین ۰ تا ۳۶۵۰ بفرست."))
            return
        await state.set_state(None)
        await state.update_data(bg_days=days)
        text, markup = await _bg_view(state)
        await message.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_bg_review")
    async def cb_bg_review(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        d = await _bg_data(state)
        if d["volume"] <= 0 and d["days"] <= 0:
            return await call.answer(tr("حجم یا زمان هدیه را مشخص کن."), show_alert=True)
        if not d["panel"] and not d["users"]:
            return await call.answer(tr("یک پنل یا چند کاربر را انتخاب کن."), show_alert=True)
        count = await asyncio.to_thread(db.count_bulk_gift_targets, d["panel"] or None, d["users"])
        if count <= 0:
            return await call.answer(tr("هیچ سرویس فعالی برای این هدف پیدا نشد."), show_alert=True)
        volume, days = _bg_amounts(d)
        users_txt = f"{len(d['users'])} کاربر مشخص" if d["users"] else "همه‌ی کاربران"
        await replace_admin_view(
            call,
            "🎁 تایید هدیه‌ی گروهی\n\n"
            f"🖥 پنل: {html.escape(await _bg_panel_name(d['panel']))}\n"
            f"👤 کاربران: {users_txt}\n"
            f"📦 حجم: {volume}\n"
            f"⏳ زمان: {days}\n"
            f"🎯 تعداد سرویس: {count:,}\n\n"
            "بعد از شروع، هدیه‌ها در یک صف پایدار پردازش می‌شوند و با ری‌استارت بات هم ادامه پیدا می‌کنند. مطمئنی؟",
            reply_markup=_kb([
                [_btn("✅ بله، شروع کن", "adm_bg_go")],
                [_btn("✏️ ویرایش", "adm_bg_view")],
            ]),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_bg_go")
    async def cb_bg_go(call: CallbackQuery, state: FSMContext):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        d = await _bg_data(state)
        try:
            job = await asyncio.to_thread(
                bulk_gifts.start_job, db, admin_id=call.from_user.id,
                panel_server_id=d["panel"] or None, user_ids=d["users"],
                volume_gb=d["volume"], days=d["days"],
            )
        except Exception as exc:
            await call.answer(tr(f"ایجاد عملیات ناموفق بود: {exc}"), show_alert=True)
            return
        await state.clear()
        volume, days = _bg_amounts(d)
        await replace_admin_view(
            call,
            f"✅ عملیات هدیه‌ی گروهی #{job['id']} ساخته شد.\n\n"
            f"🎯 تعداد سرویس: {job['total']:,}\n"
            f"📦 حجم: {volume} | ⏳ زمان: {days}\n\n"
            "پیشرفت را از «عملیات‌های اخیر» ببین.",
            reply_markup=_kb([
                [_btn("📋 عملیات‌های اخیر", "adm_bg_jobs")],
                [_btn("⬅️ بازگشت", "adm_cat:marketing")],
            ]),
        )
        await call.answer(tr("عملیات شروع شد."))

    async def _bg_jobs_view():
        jobs = await asyncio.to_thread(db.list_bulk_gift_jobs, 8)
        status_map = {
            "running": "🟡 در حال اجرا", "done": "✅ تمام‌شده", "cancelled": "⛔️ لغوشده", "pending": "⚪️ در انتظار",
        }
        lines = ["📋 عملیات‌های اخیر هدیه‌ی گروهی", ""]
        rows = []
        if not jobs:
            lines.append("هنوز عملیاتی ثبت نشده است.")
        for job in jobs:
            try:
                params = json.loads(job["params_json"] or "{}")
            except (TypeError, ValueError):
                params = {}
            gift = f"{float(params.get('volume_gb') or 0):g} گیگ / {int(params.get('days') or 0)} روز"
            lines.append(
                f"#{job['id']} {status_map.get(job['status'], job['status'])}\n"
                f"   {job['done']}/{job['total']} موفق، {job['failed']} ناموفق | {gift}"
            )
            if job["status"] == "running":
                rows.append([_btn(f"🛑 لغو عملیات #{job['id']}", f"adm_bulk_gift_cancel:{job['id']}")])
        rows.append([_btn("🔄 بروزرسانی", "adm_bg_jobs")])
        rows.append([_btn("⬅️ بازگشت", "adm_bg_view")])
        return "\n".join(lines), _kb(rows)

    @router.callback_query(F.data == "adm_bg_jobs")
    async def cb_bg_jobs(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        text, markup = await _bg_jobs_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_bulk_gift_cancel:"))
    async def cb_bg_cancel(call: CallbackQuery):
        if not full_admin_only(call.from_user.id):
            return await deny_support(call)
        try:
            job_id = int(call.data.split(":", 1)[1])
        except ValueError:
            return await call.answer(tr("شناسه نامعتبر"), show_alert=True)
        ok = await asyncio.to_thread(db.cancel_bulk_gift_job, job_id)
        text, markup = await _bg_jobs_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer("عملیات لغو شد." if ok else "عملیات قابل لغو نیست.", show_alert=not ok)

