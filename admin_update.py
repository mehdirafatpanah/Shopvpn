# -*- coding: utf-8 -*-
"""منوی «آپدیت پروژه» داخل پنل مدیریت بات (فقط مالک و مدیر کامل، فقط بات اصلی).

- نمایش نسخه‌ی نصب‌شده و آخرین نسخه‌ی GitHub، بررسی دستی، تغییرات نسخه
- آپدیت با یک دکمه (با تأیید) و برگشت به نسخه‌ی قبل
- روشن/خاموش کردن اعلان خودکار نسخه‌ی جدید

منطق اصلی در updater.py است؛ اعلان خودکار هم از همان‌جا (check_loop) ارسال می‌شود.
"""

import asyncio
import html
import os
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import updater


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _on(flag) -> str:
    return "🟢 روشن" if flag else "🔴 خاموش"


def _ago(ts: str) -> str:
    try:
        sec = max(0, int(time.time()) - int(ts))
    except (TypeError, ValueError):
        return "هنوز بررسی نشده"
    if sec < 90:
        return "همین الان"
    if sec < 5400:
        return f"{sec // 60} دقیقه پیش"
    if sec < 172800:
        return f"{sec // 3600} ساعت پیش"
    return f"{sec // 86400} روز پیش"


def register(router: Router, db, senior_admin_only, deny_mid, replace_admin_view):

    async def _present(target, text, markup):
        if isinstance(target, CallbackQuery):
            await replace_admin_view(target, text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)

    async def _main_view(info: dict, note: str = ""):
        notify = str(await asyncio.to_thread(db.get_setting, updater.K_NOTIFY, "1")) != "0"
        last_check = await asyncio.to_thread(db.get_setting, updater.K_LAST_CHECK, "")
        lines = [note, ""] if note else []
        lines += [
            "🔄 آپدیت پروژه",
            "",
            f"نسخه‌ی نصب‌شده: {html.escape(info['current'])}",
            f"آخرین نسخه‌ی منتشرشده: {html.escape(info['latest']) if info['latest'] else '—'}",
            f"آخرین بررسی: {_ago(last_check)}",
            f"اعلان خودکار نسخه‌ی جدید: {_on(notify)}",
        ]
        rows = []
        if info["available"]:
            lines += ["", f"🆕 نسخه‌ی {html.escape(info['latest'])} آماده‌ی نصب است."
                      + (" (آپدیت مهم)" if info["critical"] else "")]
            if info["notes"]:
                lines += ["", "تغییرات:", updater.format_notes(info["notes"])]
            if info.get("url"):
                lines += ["", f"🔗 جزئیات کامل: {html.escape(info['url'])}"]
            rows.append([_btn(f"⬇️ آپدیت به نسخه‌ی {info['latest']}", "adm_update_ask")])
        elif info["latest"]:
            lines += ["", "✅ ربات روی آخرین نسخه است."]
        rows.append([_btn("🔍 بررسی الان", "adm_update_check")])
        rows.append([_btn(f"🔔 اعلان خودکار: {'خاموش کن' if notify else 'روشن کن'}", "adm_update_toggle")])
        if updater.list_snapshots():
            rows.append([_btn("↩️ برگشت به نسخه‌ی قبل از آخرین آپدیت", "adm_update_rb_ask")])
        rows.append([_btn("⬅️ بازگشت", "adm_cat:management")])
        return "\n".join(lines), _kb(rows)

    async def _show(target, note: str = "", force: bool = False):
        info = await updater.check(db, force=force)
        if force and not info["checked"]:
            note = "⚠️ اتصال به GitHub برقرار نشد؛ اطلاعات آخرین بررسی نمایش داده می‌شود."
        text, markup = await _main_view(info, note)
        await _present(target, text, markup)

    @router.callback_query(F.data == "adm_update")
    async def cb_update_menu(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await _show(call)
        await call.answer()

    @router.message(Command("update"))
    async def cmd_update(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        await state.clear()
        await _show(message, force=True)

    @router.callback_query(F.data == "adm_update_check")
    async def cb_update_check(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await call.answer("⏳ در حال بررسی…")
        await _show(call, force=True)

    @router.callback_query(F.data == "adm_update_toggle")
    async def cb_update_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cur = str(await asyncio.to_thread(db.get_setting, updater.K_NOTIFY, "1")) != "0"
        await asyncio.to_thread(db.set_setting, updater.K_NOTIFY, "0" if cur else "1")
        await _show(call, note="🔕 اعلان خودکار خاموش شد." if cur else "🔔 اعلان خودکار روشن شد.")
        await call.answer()

    @router.callback_query(F.data == "adm_update_later")
    async def cb_update_later(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.answer("باشه؛ هر وقت خواستی از «پنل مدیریت ← گزارش و سیستم ← آپدیت پروژه» بزن.", show_alert=True)

    @router.callback_query(F.data == "adm_update_ask")
    async def cb_update_ask(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        info = await updater.check(db)
        if not info["available"]:
            await call.answer("✅ ربات روی آخرین نسخه است.", show_alert=True)
            return await _show(call)
        text = (
            f"⚠️ آپدیت از نسخه‌ی {html.escape(info['current'])} به {html.escape(info['latest'])}\n\n"
            "• قبل از شروع از دیتابیس و کد بکاپ گرفته می‌شود (پوشه‌ی backups).\n"
            "• ربات و سرویس‌های جانبی (مینی‌اپ، پنل وب، ساب اختصاصی) حدود ۳۰ ثانیه ری‌استارت می‌شوند.\n"
            "• اگر آپدیت ناموفق باشد خودکار به نسخه‌ی قبل برمی‌گردد و نتیجه همین‌جا اعلام می‌شود.\n"
            "• فایل‌های .env و دیتابیس‌ها دست نمی‌خورند؛ ولی تغییراتی که خودت دستی در فایل‌های کد داده‌ای ممکن است بازنویسی شود."
        )
        await replace_admin_view(call, text, reply_markup=_kb([
            [_btn("✅ تأیید و آپدیت", "adm_update_go")],
            [_btn("❌ انصراف", "adm_update")],
        ]))
        await call.answer()

    @router.callback_query(F.data == "adm_update_go")
    async def cb_update_go(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        info = await updater.check(db)
        if not info["available"]:
            await call.answer("✅ ربات روی آخرین نسخه است.", show_alert=True)
            return await _show(call)
        err = await updater.start("update", call.from_user.id, call.message.chat.id,
                                  call.message.message_id, info["latest"])
        if err:
            await call.answer()
            return await replace_admin_view(call, f"❌ {html.escape(err)}", reply_markup=_kb([[_btn("⬅️ بازگشت", "adm_update")]]))
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "project_update", f"{info['current']} -> {info['latest']}")
        await replace_admin_view(
            call, "⏳ آپدیت شروع شد. ربات تا حدود یک دقیقه آفلاین می‌شود و نتیجه همین‌جا برایت ارسال می‌شود.",
            reply_markup=None)
        await call.answer()

    @router.callback_query(F.data == "adm_update_rb_ask")
    async def cb_rollback_ask(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        snaps = updater.list_snapshots()
        if not snaps:
            await call.answer("نسخه‌ی پشتیبانی برای برگشت پیدا نشد.", show_alert=True)
            return await _show(call)
        text = (
            "↩️ برگشت به نسخه‌ی قبل\n\n"
            f"کد پروژه از آخرین بکاپ ({html.escape(os.path.basename(snaps[-1]))}) بازیابی می‌شود و سرویس‌ها ری‌استارت می‌شوند.\n"
            "دیتابیس برنمی‌گردد (سفارش‌ها و کاربران جدید حفظ می‌شوند)."
        )
        await replace_admin_view(call, text, reply_markup=_kb([
            [_btn("✅ بله، برگرد", "adm_update_rb_go")],
            [_btn("❌ انصراف", "adm_update")],
        ]))
        await call.answer()

    @router.callback_query(F.data == "adm_update_rb_go")
    async def cb_rollback_go(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        err = await updater.start("rollback", call.from_user.id, call.message.chat.id, call.message.message_id)
        if err:
            await call.answer()
            return await replace_admin_view(call, f"❌ {html.escape(err)}", reply_markup=_kb([[_btn("⬅️ بازگشت", "adm_update")]]))
        await asyncio.to_thread(db.log_admin_action, call.from_user.id, "project_rollback", "")
        await replace_admin_view(call, "⏳ برگشت شروع شد؛ نتیجه همین‌جا اعلام می‌شود.", reply_markup=None)
        await call.answer()
