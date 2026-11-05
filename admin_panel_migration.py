# -*- coding: utf-8 -*-
"""منوی «مهاجرت کاربران به پنل دیگر» داخل مدیریت سرورهای پنل (فقط مالک/مدیر ارشد، فقط بات اصلی).

مسیر: سرورهای پنل ← یک سرور ← «🚚 مهاجرت کاربران» ← انتخاب پنل مقصد ← پیش‌نمایش و گزینه‌ها ← تأیید ← اجرا.
"""

import asyncio
import html
import logging
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import panel_migration as pm

try:
    from keyboards import PANEL_TYPE_LABELS
except Exception:  # pragma: no cover
    PANEL_TYPE_LABELS = {}

logger = logging.getLogger(__name__)

_STATE: dict = {}          # (admin_id, src, dst) → {"opts": Options, "plan": dict, "ts": float}
_STATE_TTL = 1800

OPTION_LABELS = {
    "n": ("notify_users", "📩 ارسال پیام و لینک جدید به کاربران"),
    "s": ("retarget_sales", "🛒 فروش جدید هم روی پنل مقصد باشد"),
    "d": ("disable_old", "⛔ غیرفعال‌کردن کاربران قدیمی روی پنل مبدأ"),
    "e": ("allow_estimate", "🧮 اگر پنل مبدأ در دسترس نبود، حجم را از دیتابیس تخمین بزن"),
}


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _e(value) -> str:
    return html.escape(str(value or ""))


def _type(server) -> str:
    return PANEL_TYPE_LABELS.get(server["panel_type"], server["panel_type"])


def _gc_state():
    now = time.time()
    for key in [k for k, v in _STATE.items() if now - v["ts"] > _STATE_TTL]:
        _STATE.pop(key, None)


def plan_text(plan: dict, opts: pm.Options) -> str:
    src, dst = plan["source"], plan["dest"]
    lines = [
        "🚚 مهاجرت کاربران بین پنل‌ها",
        f"از «{_e(src['name'])}» ({_e(_type(src))})  ←  به «{_e(dst['name'])}» ({_e(_type(dst))})",
        "",
        f"👥 کاربران: {plan['users']:,}",
        f"📦 سرویس‌های اصلی: {plan['primary']:,}",
    ]
    if plan["links"]:
        lines.append(f"🔗 کاربران پنل‌های اضافه (چندپنلی): {plan['links']:,}")
    if plan["pooled"]:
        lines.append(f"🔄 عضو سهمیه‌ی مشترک (حجمشان با استخر حساب می‌شود): {plan['pooled']:,}")
    lines.append(f"🧮 مجموع حجم خریداری‌شده‌ی سرویس‌های عادی: {plan['total_gb']:,} گیگ")
    if plan["expired"]:
        lines.append(f"⏳ منقضی‌شده (منتقل نمی‌شود): {plan['expired']:,}")
    lines.append("")
    if plan.get("dst_reachable") is True:
        lines.append("اتصال پنل مقصد: ✅ برقرار")
    if plan.get("src_reachable") is True:
        lines.append("اتصال پنل مبدأ: ✅ برقرار")
    elif plan.get("src_reachable") is False:
        lines.append("اتصال پنل مبدأ: ⚠️ برقرار نیست")
    for warn in plan.get("warnings", []):
        lines.append(f"⚠️ {_e(warn)}")
    lines += [
        "",
        "نکته‌ها:",
        "• حجم و زمان باقی‌مانده‌ی هر کاربر روی پنل مقصد حفظ می‌شود.",
        "• کاربران قدیمی روی پنل مبدأ حذف نمی‌شوند؛ پنل را خودت هر وقت خواستی حذف کن.",
        "• قبل از اجرا مطمئن شو در پنل مقصد «کاربر نمونه/گروه/اینباند» تنظیم شده است.",
    ]
    return "\n".join(lines)


def options_kb(src: int, dst: int, opts: pm.Options) -> InlineKeyboardMarkup:
    rows = []
    for key, (attr, label) in OPTION_LABELS.items():
        mark = "✅" if getattr(opts, attr) else "◻️"
        rows.append([_btn(f"{mark} {label}", f"adm_pmig_o:{src}:{dst}:{key}")])
    rows.append([_btn("🚀 شروع مهاجرت", f"adm_pmig_go:{src}:{dst}")])
    rows.append([_btn("⬅️ انتخاب پنل مقصد دیگر", f"adm_pmig:{src}")])
    return _kb(rows)


def register(router: Router, db, senior_admin_only, deny_mid, replace_admin_view):

    async def _guard(call: CallbackQuery) -> bool:
        if not senior_admin_only(call.from_user.id):
            await deny_mid(call)
            return False
        return True

    # ------------------------------------------------------------------ ۱) انتخاب پنل مقصد
    @router.callback_query(F.data.startswith("adm_pmig:"))
    async def cb_pmig_entry(call: CallbackQuery):
        if not await _guard(call):
            return
        src_id = int(call.data.split(":")[1])
        src = await asyncio.to_thread(db.get_panel_server, src_id)
        if not src:
            return await call.answer("پنل پیدا نشد.", show_alert=True)
        primaries = await asyncio.to_thread(db.pm_list_primary, src_id)
        links = await asyncio.to_thread(db.pm_list_links, src_id)
        servers = [s for s in await asyncio.to_thread(db.get_panel_servers, True) if int(s["id"]) != src_id]
        runs = await asyncio.to_thread(db.pm_recent_runs, 3)
        lines = [
            "🚚 مهاجرت کاربران به پنل دیگر",
            f"پنل مبدأ: «{_e(src['name'])}» ({_e(_type(src))})",
            f"سرویس‌های فعال: {len(primaries):,}" + (f" + {len(links):,} کاربر چندپنلی" if links else ""),
            "",
        ]
        if pm.is_running(src_id):
            lines.append("⏳ مهاجرت این پنل همین الان در حال اجراست.")
        if not primaries and not links:
            lines.append("سرویس فعالی روی این پنل نیست.")
        elif not servers:
            lines.append("اول یک پنل دیگر (فعال) اضافه کن، بعد برگرد.")
        else:
            lines.append("پنل مقصد را انتخاب کن (هر نوع پنلی می‌تواند باشد):")
        if runs:
            lines += ["", "آخرین مهاجرت‌ها:"]
            for r in runs:
                lines.append(f"• {_e(r.get('source_name'))} ← {_e(r.get('dest_name'))}: "
                             f"{r['migrated']:,} موفق / {r['failed']:,} خطا / {r['skipped']:,} ردشده")
        rows = []
        if (primaries or links) and not pm.is_running(src_id):
            for s in servers[:30]:
                rows.append([_btn(f"{s['name']} ({_type(s)})", f"adm_pmig_d:{src_id}:{s['id']}")])
        rows.append([_btn("⬅️ بازگشت", f"adm_panel_server_view:{src_id}")])
        await replace_admin_view(call, "\n".join(lines), reply_markup=_kb(rows))
        await call.answer()

    # ------------------------------------------------------------------ ۲) پیش‌نمایش
    @router.callback_query(F.data.startswith("adm_pmig_d:"))
    async def cb_pmig_preview(call: CallbackQuery):
        if not await _guard(call):
            return
        _, src_s, dst_s = call.data.split(":")
        src_id, dst_id = int(src_s), int(dst_s)
        await call.answer("در حال بررسی پنل‌ها…")
        plan = await pm.build_plan(db, src_id, dst_id)
        if not plan["ok"]:
            return await replace_admin_view(
                call, f"🚚 مهاجرت\n\n❌ {_e(plan['error'])}",
                reply_markup=_kb([[_btn("⬅️ بازگشت", f"adm_pmig:{src_id}")]]))
        _gc_state()
        key = (call.from_user.id, src_id, dst_id)
        _STATE[key] = {"opts": pm.Options(), "plan": plan, "ts": time.time()}
        await replace_admin_view(call, plan_text(plan, _STATE[key]["opts"]),
                                 reply_markup=options_kb(src_id, dst_id, _STATE[key]["opts"]))

    @router.callback_query(F.data.startswith("adm_pmig_o:"))
    async def cb_pmig_toggle(call: CallbackQuery):
        if not await _guard(call):
            return
        _, src_s, dst_s, opt = call.data.split(":")
        src_id, dst_id = int(src_s), int(dst_s)
        state = _STATE.get((call.from_user.id, src_id, dst_id))
        if not state or opt not in OPTION_LABELS:
            return await call.answer("نشست منقضی شد؛ دوباره پنل مقصد را انتخاب کن.", show_alert=True)
        attr = OPTION_LABELS[opt][0]
        setattr(state["opts"], attr, not getattr(state["opts"], attr))
        state["ts"] = time.time()
        await replace_admin_view(call, plan_text(state["plan"], state["opts"]),
                                 reply_markup=options_kb(src_id, dst_id, state["opts"]))
        await call.answer()

    # ------------------------------------------------------------------ ۳) تأیید نهایی
    @router.callback_query(F.data.startswith("adm_pmig_go:"))
    async def cb_pmig_confirm(call: CallbackQuery):
        if not await _guard(call):
            return
        _, src_s, dst_s = call.data.split(":")
        src_id, dst_id = int(src_s), int(dst_s)
        state = _STATE.get((call.from_user.id, src_id, dst_id))
        if not state:
            return await call.answer("نشست منقضی شد؛ دوباره پنل مقصد را انتخاب کن.", show_alert=True)
        plan, opts = state["plan"], state["opts"]
        text = (
            "⚠️ تأیید نهایی مهاجرت\n\n"
            f"«{_e(plan['source']['name'])}» ← «{_e(plan['dest']['name'])}»\n"
            f"{plan['need']:,} سرویس برای {plan['users']:,} کاربر منتقل می‌شود.\n"
            f"پیام به کاربران: {'✅ ارسال می‌شود' if opts.notify_users else '❌ ارسال نمی‌شود'}\n"
            f"کاربران قدیمی پنل مبدأ: {'⛔ غیرفعال می‌شوند' if opts.disable_old else 'دست‌نخورده می‌مانند'}\n\n"
            "مطمئنی؟"
        )
        await replace_admin_view(call, text, reply_markup=_kb([
            [_btn("✅ بله، شروع کن", f"adm_pmig_run:{src_id}:{dst_id}")],
            [_btn("⬅️ برگشت به گزینه‌ها", f"adm_pmig_d:{src_id}:{dst_id}")],
        ]))
        await call.answer()

    # ------------------------------------------------------------------ ۴) اجرا
    @router.callback_query(F.data.startswith("adm_pmig_run:"))
    async def cb_pmig_run(call: CallbackQuery):
        if not await _guard(call):
            return
        _, src_s, dst_s = call.data.split(":")
        src_id, dst_id = int(src_s), int(dst_s)
        state = _STATE.pop((call.from_user.id, src_id, dst_id), None)
        if not state:
            return await call.answer("نشست منقضی شد؛ دوباره پنل مقصد را انتخاب کن.", show_alert=True)
        if pm.is_running(src_id):
            return await call.answer("مهاجرت این پنل همین الان در حال اجراست.", show_alert=True)
        opts, bot = state["opts"], call.bot
        chat_id, message_id, admin_id = call.message.chat.id, call.message.message_id, call.from_user.id
        await call.answer("مهاجرت شروع شد…")
        await replace_admin_view(call, "🚚 مهاجرت شروع شد…\nمی‌توانی از منو بیرون بروی؛ گزارش پایانی برایت ارسال می‌شود.",
                                 reply_markup=None)
        last_edit = {"t": 0.0}

        async def progress(done, total, ok, bad, skipped):
            if time.time() - last_edit["t"] < 2.5 and done < total:
                return
            last_edit["t"] = time.time()
            try:
                await bot.edit_message_text(
                    f"🚚 در حال مهاجرت… {done:,}/{total:,}\n✅ موفق: {ok:,}   ❌ خطا: {bad:,}   ⏭ ردشده: {skipped:,}",
                    chat_id=chat_id, message_id=message_id)
            except Exception:
                pass

        async def _job():
            report = await pm.run_migration(db, src_id, dst_id, opts, bot=bot, admin_id=admin_id, progress=progress)
            try:
                await bot.send_message(chat_id, report_text(report), reply_markup=_kb(
                    [[_btn("🖥 سرورهای پنل", "adm_panel_servers")]]))
            except Exception:
                logger.exception("panel-migration: final report send failed")

        task = asyncio.create_task(_job())
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)


_TASKS: set = set()   # نگه‌داشتن ارجاع تا تسک وسط اجرا جمع‌آوری نشود


def report_text(report: dict) -> str:
    if not report.get("run_id") and not report.get("ok"):
        return f"❌ مهاجرت انجام نشد: {_e(report.get('error'))}"
    head = "⛔ مهاجرت متوقف شد" if report.get("aborted") else "✅ مهاجرت تمام شد"
    lines = [
        f"{head}: «{_e(report.get('source_name'))}» ← «{_e(report.get('dest_name'))}»",
        "",
        f"✅ منتقل‌شده: {report.get('migrated', 0):,} از {report.get('total', 0):,}",
        f"❌ خطا: {report.get('failed', 0):,}",
        f"⏭ ردشده (منقضی/حجم تمام‌شده): {report.get('skipped', 0):,}",
        f"📩 پیام ارسال‌شده به کاربران: {report.get('notified', 0):,}",
    ]
    if report.get("estimated"):
        lines.append(f"🧮 حجم تخمینی (پنل مبدأ در دسترس نبود): {report['estimated']:,} سرویس")
    rt = report.get("retarget") or {}
    if rt:
        lines.append(
            f"🛒 فروش منتقل شد: {rt.get('products', 0)} محصول، {rt.get('extra_targets', 0)} پنل اضافه، "
            f"{rt.get('custom_products', 0)} محصول کانفیگ شخصی، {rt.get('test_plans', 0)} پلن تست، "
            f"{rt.get('wheel_prizes', 0)} جایزه‌ی گردونه")
    if report.get("error"):
        lines += ["", f"⚠️ {_e(report['error'])}"]
    failures = report.get("failures") or []
    if failures:
        lines += ["", "نمونه‌ی خطاها:"]
        for f in failures[:10]:
            lines.append(f"• {_e(f.get('old_username'))}: {_e((f.get('error') or '')[:90])}")
        lines.append("برای سرویس‌های خطادار دوباره «مهاجرت» را اجرا کن؛ فقط باقی‌مانده‌ها برداشته می‌شوند.")
    lines += ["", "پنل قدیمی دست‌نخورده مانده؛ هر وقت مطمئن شدی از «حذف سرور» پاکش کن."]
    return "\n".join(lines)
