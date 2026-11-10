# -*- coding: utf-8 -*-
"""مدیریت نود، حساب و استخر SSH داخل بات ادمین (مشابه مدیریت پنل‌های VPN)."""
import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ssh_service
from i18n import tr
from ssh_service import SSHServiceError
from ssh_uri import build_ssh_uri
from states import AdminSSH

logger = logging.getLogger(__name__)

STATUS_FA = {"active": "فعال", "pending": "در انتظار", "error": "خطا", "degraded": "ناپایدار",
             "disabled": "غیرفعال", "stale": "داده قدیمی", "exceeded": "سهمیه تمام‌شده",
             "quota_exceeded": "سهمیه تمام‌شده", "expired": "منقضی", "deleted": "حذف‌شده"}
STATUS_ICON = {"active": "🟢", "pending": "🟡", "degraded": "🟠", "disabled": "⚪", "deleted": "⚫"}


def _st(s):
    return STATUS_FA.get(s, s or "نامشخص")


def _icon(s):
    return STATUS_ICON.get(s, "🔴")


def _fmt_bytes(n):
    n = float(n or 0)
    return f"{n / 1024 ** 2:.1f} MB" if n < 1024 ** 3 else f"{n / 1024 ** 3:.2f} GB"


def _btn(text, cb):
    return InlineKeyboardButton(text=tr(text), callback_data=cb)


def _kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def _cancel_kb(back="adm_ssh_menu"):
    return _kb([_btn("❌ انصراف", back)])


def register(router: Router, db, *, full_access_bot, senior_admin_only, deny_mid, safe_edit, replace_admin_view):
    async def _guard(call: CallbackQuery) -> bool:
        if not full_access_bot:
            await call.answer(tr("مدیریت SSH فقط در بات اصلی (یا نماینده با دسترسی کامل) فعال است."), show_alert=True)
            return False
        if not senior_admin_only(call.from_user.id):
            await deny_mid(call)
            return False
        return True

    def _msg_ok(message: Message) -> bool:
        return full_access_bot and senior_admin_only(message.from_user.id)

    def _log(uid, action, detail):
        try:
            db.log_admin_action(uid, action, detail, "ssh")
        except Exception:
            logger.exception("ssh admin log failed")

    # ------------------------------------------------------------------ منو
    def _menu_kb():
        ov = ssh_service.overview(db)
        accs = [a for a in ov["accounts"] if a.get("status") != "deleted"]
        return _kb(
            [_btn(f"🖥 نودها ({len(ov['nodes'])})", "adm_ssh_nodes")],
            [_btn(f"👤 حساب‌ها ({len(accs)})", "adm_ssh_accounts")],
            [_btn(f"📦 استخرها ({len(ov['pools'])})", "adm_ssh_pools")],
            [_btn("↩️ بازگشت", "adm_cat:products")],
        )

    @router.callback_query(F.data == "adm_ssh_menu")
    async def cb_ssh_menu(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.clear()
        await replace_admin_view(call, tr("🔐 مدیریت SSH و سهمیه مشترک:"), reply_markup=_menu_kb())
        await call.answer()

    # ------------------------------------------------------------------ نودها
    def _nodes_kb():
        nodes = ssh_service.overview(db)["nodes"]
        rows = [[_btn(f"{_icon(n['status'])} {n['name']} ({n['host']})", f"adm_ssh_node:{n['id']}")] for n in nodes]
        rows.append([_btn("➕ افزودن نود (نصب خودکار)", "adm_ssh_node_add")])
        rows.append([_btn("↩️ بازگشت", "adm_ssh_menu")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.callback_query(F.data == "adm_ssh_nodes")
    async def cb_ssh_nodes(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.clear()
        await replace_admin_view(call, tr("🖥 نودهای SSH:"), reply_markup=_nodes_kb())
        await call.answer()

    def _find_node(node_id):
        return next((n for n in ssh_service.overview(db)["nodes"] if int(n["id"]) == int(node_id)), None)

    async def _show_node(call: CallbackQuery, node_id: int):
        node = _find_node(node_id)
        if not node:
            await call.answer(tr("نود پیدا نشد."), show_alert=True)
            return
        text = (f"🖥 <b>{html.escape(str(node['name']))}</b>\n"
                f"آدرس: <code>{html.escape(str(node['host']))}:{int(node['port'])}</code>\n"
                f"وضعیت: {_icon(node['status'])} {_st(node['status'])}")
        if node.get("last_error"):
            text += f"\nخطا: {html.escape(str(node['last_error'])[:300])}"
        await replace_admin_view(call, text, parse_mode="HTML", reply_markup=_kb(
            [_btn("🔌 تست اتصال", f"adm_ssh_node_test:{node_id}")],
            [_btn("✏️ تغییر نام", f"adm_ssh_node_rename:{node_id}")],
            [_btn("🗑 حذف نود", f"adm_ssh_node_del:{node_id}")],
            [_btn("↩️ بازگشت", "adm_ssh_nodes")],
        ))

    @router.callback_query(F.data.startswith("adm_ssh_node:"))
    async def cb_ssh_node_view(call: CallbackQuery):
        if not await _guard(call):
            return
        await _show_node(call, int(call.data.split(":")[1]))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ssh_node_test:"))
    async def cb_ssh_node_test(call: CallbackQuery):
        if not await _guard(call):
            return
        node_id = int(call.data.split(":")[1])
        await call.answer(tr("در حال تست اتصال..."))
        try:
            ok = await ssh_service.test_node(db, node_id)
            _log(call.from_user.id, "ssh_node_test", f"SSH node #{node_id}: {'ok' if ok else 'failed'}")
            await call.message.answer(tr("✅ اتصال Agent موفق بود.") if ok else tr("❌ پاسخ Agent معتبر نیست."))
        except SSHServiceError as exc:
            await call.message.answer(tr("❌ ") + html.escape(str(exc)))
        await _show_node(call, node_id)

    @router.callback_query(F.data.startswith("adm_ssh_node_rename:"))
    async def cb_ssh_node_rename(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        node_id = int(call.data.split(":")[1])
        await state.set_state(AdminSSH.node_rename)
        await state.update_data(node_id=node_id)
        await safe_edit(call, tr("نام جدید نود را بفرست (همین نام روی کانفیگ SSH کاربر دیده می‌شود):"),
                        reply_markup=_cancel_kb(f"adm_ssh_node:{node_id}"))
        await call.answer()

    @router.message(AdminSSH.node_rename, ~F.text.startswith("/"))
    async def msg_ssh_node_rename(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        data = await state.get_data()
        node_id = int(data["node_id"])
        try:
            ssh_service.rename_node(db, node_id, message.text or "")
        except SSHServiceError as exc:
            return await message.answer(tr("❌ ") + html.escape(str(exc)))
        _log(message.from_user.id, "ssh_node_rename", f"SSH node #{node_id}: {(message.text or '').strip()}")
        await state.clear()
        await message.answer(tr("✅ نام نود تغییر کرد."), reply_markup=_nodes_kb())

    @router.callback_query(F.data.startswith("adm_ssh_node_del:"))
    async def cb_ssh_node_del(call: CallbackQuery):
        if not await _guard(call):
            return
        node_id = int(call.data.split(":")[1])
        await safe_edit(call, tr("⚠️ این نود حذف شود؟"), reply_markup=_kb(
            [_btn("✅ بله، حذف شود", f"adm_ssh_node_delc:{node_id}")],
            [_btn("❌ انصراف", f"adm_ssh_node:{node_id}")]))
        await call.answer()

    @router.callback_query(F.data.startswith(("adm_ssh_node_delc:", "adm_ssh_node_delf:")))
    async def cb_ssh_node_delc(call: CallbackQuery):
        if not await _guard(call):
            return
        node_id = int(call.data.split(":")[1])
        force = call.data.startswith("adm_ssh_node_delf:")
        try:
            ssh_service.delete_node(db, node_id, force=force)
        except SSHServiceError as exc:
            if "حساب SSH فعال" in str(exc) and not force:
                await safe_edit(call, tr("⚠️ ") + str(exc) + "\n\n" + tr("اگر سرور این نود حذف شده یا از دسترس خارج است، نود و همه‌ی حساب‌هایش فقط از پنل پاک می‌شوند (روی سرور تغییری داده نمی‌شود)."),
                                reply_markup=_kb([_btn("🗑 حذف اجباری نود و حساب‌ها", f"adm_ssh_node_delf:{node_id}")],
                                                 [_btn("❌ انصراف", f"adm_ssh_node:{node_id}")]))
                await call.answer()
                return
            await call.answer(str(exc)[:180], show_alert=True)
            return
        _log(call.from_user.id, "ssh_node_delete", f"SSH node #{node_id}" + (" (force)" if force else ""))
        await replace_admin_view(call, tr("🗑 نود حذف شد."), reply_markup=_nodes_kb())
        await call.answer()

    # --- افزودن نود با نصب خودکار
    @router.callback_query(F.data == "adm_ssh_node_add")
    async def cb_ssh_node_add(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.set_state(AdminSSH.node_name)
        await safe_edit(call, tr("نام نود را بفرست (مثلاً Germany-SSH-1):"), reply_markup=_cancel_kb("adm_ssh_nodes"))
        await call.answer()

    @router.message(AdminSSH.node_name, ~F.text.startswith("/"))
    async def msg_ssh_node_name(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        name = (message.text or "").strip()
        if not 1 <= len(name) <= 80:
            return await message.answer(tr("نام باید بین ۱ تا ۸۰ کاراکتر باشد."))
        await state.update_data(name=name)
        await state.set_state(AdminSSH.node_host)
        await message.answer(tr("آی‌پی یا دامنه سرور را بفرست (Ubuntu/Debian تازه):"), reply_markup=_cancel_kb("adm_ssh_nodes"))

    @router.message(AdminSSH.node_host, ~F.text.startswith("/"))
    async def msg_ssh_node_host(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        await state.update_data(host=(message.text or "").strip())
        await state.set_state(AdminSSH.node_port)
        await message.answer(tr("پورت SSH سرور را بفرست (پیش‌فرض 22):"), reply_markup=_cancel_kb("adm_ssh_nodes"))

    @router.message(AdminSSH.node_port, ~F.text.startswith("/"))
    async def msg_ssh_node_port(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        text = (message.text or "").strip()
        if not text.isdigit() or not 1 <= int(text) <= 65535:
            return await message.answer(tr("پورت نامعتبر است؛ عددی بین ۱ تا ۶۵۵۳۵ بفرست."))
        await state.update_data(port=int(text))
        await state.set_state(AdminSSH.node_pass)
        await message.answer(tr("رمز root سرور را بفرست. فقط برای همین نصب استفاده می‌شود، ذخیره نمی‌شود و پیامت بلافاصله پاک می‌شود."),
                             reply_markup=_cancel_kb("adm_ssh_nodes"))

    @router.message(AdminSSH.node_pass, ~F.text.startswith("/"))
    async def msg_ssh_node_pass(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        password = message.text or ""
        try:
            await message.delete()
        except Exception:
            pass
        data = await state.get_data()
        await state.clear()
        try:
            job_id = ssh_service.start_auto_install(db, name=data["name"], host=data["host"],
                                                    ssh_port=data["port"], password=password)
        except SSHServiceError as exc:
            return await message.answer(tr("❌ ") + html.escape(str(exc)), reply_markup=_nodes_kb())
        _log(message.from_user.id, "ssh_node_auto_install", f"SSH node auto-install started: {data['name']} ({data['host']})")
        progress = await message.answer(tr("⏳ نصب شروع شد؛ ممکن است چند دقیقه طول بکشد..."))

        async def _watch():
            last = ""
            for _ in range(450):
                await asyncio.sleep(4)
                job = ssh_service.get_install_job(job_id) or {}
                text = "\n".join(job.get("log") or [])[-3000:] or "..."
                if text != last:
                    last = text
                    try:
                        await progress.edit_text(f"⏳ {data['name']}\n<pre>{html.escape(text)}</pre>", parse_mode="HTML")
                    except Exception:
                        pass
                if job.get("status") == "done":
                    note = ("✅ نود نصب و فعال شد." + (f"\n⚠️ {job['warning']}" if job.get("warning") else ""))
                    await message.answer(note, reply_markup=_nodes_kb())
                    return
                if job.get("status") == "error":
                    await message.answer("❌ " + html.escape(str(job.get("error") or "نصب ناموفق بود.")), reply_markup=_nodes_kb())
                    return
            await message.answer(tr("نصب طولانی شد؛ بعداً وضعیت نودها را بررسی کن."), reply_markup=_nodes_kb())

        asyncio.create_task(_watch())

    # ------------------------------------------------------------------ حساب‌ها
    def _live_accounts():
        return [a for a in ssh_service.overview(db)["accounts"] if a.get("status") != "deleted"]

    def _accounts_kb():
        rows = [[_btn(f"{_icon(a['status'])} {a['username']} · کاربر {a['user_id']}", f"adm_ssh_acc:{a['id']}")]
                for a in _live_accounts()[-25:]]
        rows.append([_btn("➕ ساخت حساب", "adm_ssh_acc_add")])
        rows.append([_btn("↩️ بازگشت", "adm_ssh_menu")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.callback_query(F.data == "adm_ssh_accounts")
    async def cb_ssh_accounts(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.clear()
        total = len(_live_accounts())
        await replace_admin_view(call, tr(f"👤 حساب‌های SSH ({total}) — ۲۵ مورد آخر:"), reply_markup=_accounts_kb())
        await call.answer()

    def _find_account(row_id):
        return next((a for a in ssh_service.overview(db)["accounts"] if int(a["id"]) == int(row_id)), None)

    async def _show_account(call: CallbackQuery, row_id: int):
        a = _find_account(row_id)
        if not a:
            await call.answer(tr("حساب پیدا نشد."), show_alert=True)
            return
        text = (f"👤 <b>{html.escape(str(a['username']))}</b>\n"
                f"سرور: <code>{html.escape(str(a['host']))}:{int(a['port'])}</code>\n"
                f"کاربر: <code>{int(a['user_id'])}</code> · نود #{int(a['node_id'])}\n"
                f"استخر: {('#' + str(int(a['quota_pool_id']))) if a.get('quota_pool_id') else 'ندارد'}\n"
                f"وضعیت: {_icon(a['status'])} {_st(a['status'])}")
        await replace_admin_view(call, text, parse_mode="HTML", reply_markup=_kb(
            [_btn("✅ فعال", f"adm_ssh_accx:enable:{row_id}"), _btn("⏸ غیرفعال", f"adm_ssh_accx:disable:{row_id}")],
            [_btn("🗑 حذف حساب", f"adm_ssh_accx:delete:{row_id}")],
            [_btn("↩️ بازگشت", "adm_ssh_accounts")],
        ))

    @router.callback_query(F.data.startswith("adm_ssh_acc:"))
    async def cb_ssh_acc_view(call: CallbackQuery):
        if not await _guard(call):
            return
        await _show_account(call, int(call.data.split(":")[1]))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ssh_accx:"))
    async def cb_ssh_acc_action(call: CallbackQuery):
        if not await _guard(call):
            return
        _, action, row = call.data.split(":")
        row_id = int(row)
        a = _find_account(row_id)
        if not a:
            await call.answer(tr("حساب پیدا نشد."), show_alert=True)
            return
        if action == "delete":
            await safe_edit(call, tr("⚠️ حساب SSH حذف شود؟"), reply_markup=_kb(
                [_btn("✅ بله، حذف شود", f"adm_ssh_accxc:{row_id}")], [_btn("❌ انصراف", f"adm_ssh_acc:{row_id}")]))
            return await call.answer()
        await call.answer(tr("در حال انجام..."))
        try:
            await ssh_service.account_action(db, a["account_id"], action)
            _log(call.from_user.id, f"ssh_account_{action}", f"SSH account {a['account_id']}")
        except SSHServiceError as exc:
            await call.message.answer(tr("❌ ") + html.escape(str(exc)))
        await _show_account(call, row_id)

    @router.callback_query(F.data.startswith(("adm_ssh_accxc:", "adm_ssh_accxf:")))
    async def cb_ssh_acc_delete(call: CallbackQuery):
        if not await _guard(call):
            return
        row_id = int(call.data.split(":")[1])
        a = _find_account(row_id)
        if not a:
            await call.answer(tr("حساب پیدا نشد."), show_alert=True)
            return
        force = call.data.startswith("adm_ssh_accxf:")
        try:
            await ssh_service.account_action(db, a["account_id"], "delete", force=force)
            _log(call.from_user.id, "ssh_account_delete", f"SSH account {a['account_id']}" + (" (force)" if force else ""))
        except SSHServiceError as exc:
            if exc.status == ssh_service.AGENT_UNREACHABLE_STATUS:
                await safe_edit(call, tr("⚠️ ") + str(exc) + "\n\n" + tr("حذف اجباری فقط از پنل انجام شود؟ (روی سرور نود تغییری داده نمی‌شود)"),
                                reply_markup=_kb([_btn("🗑 حذف اجباری (فقط از پنل)", f"adm_ssh_accxf:{row_id}")],
                                                 [_btn("❌ انصراف", f"adm_ssh_acc:{row_id}")]))
                await call.answer()
                return
            await call.answer(str(exc)[:180], show_alert=True)
            return
        await replace_admin_view(call, tr("🗑 حساب حذف شد."), reply_markup=_accounts_kb())
        await call.answer()

    # --- ساخت حساب
    @router.callback_query(F.data == "adm_ssh_acc_add")
    async def cb_ssh_acc_add(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        nodes = [n for n in ssh_service.overview(db)["nodes"] if n.get("status") == "active"]
        if not nodes:
            await call.answer(tr("نود فعالی وجود ندارد؛ اول یک نود اضافه کن."), show_alert=True)
            return
        rows = [[_btn(f"🖥 {n['name']}", f"adm_ssh_acc_node:{n['id']}")] for n in nodes]
        rows.append([_btn("❌ انصراف", "adm_ssh_accounts")])
        await safe_edit(call, tr("نود حساب را انتخاب کن:"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ssh_acc_node:"))
    async def cb_ssh_acc_node(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.update_data(node_id=int(call.data.split(":")[1]))
        await state.set_state(AdminSSH.acc_user)
        await safe_edit(call, tr("شناسه عددی تلگرام کاربر را بفرست:"), reply_markup=_cancel_kb("adm_ssh_accounts"))
        await call.answer()

    @router.message(AdminSSH.acc_user, ~F.text.startswith("/"))
    async def msg_ssh_acc_user(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            return await message.answer(tr("شناسه باید عدد مثبت باشد."))
        if not db.get_user(int(text)):
            return await message.answer(tr("این کاربر در دیتابیس بات پیدا نشد."))
        await state.update_data(user_id=int(text))
        await state.set_state(AdminSSH.acc_username)
        await message.answer(tr("نام کاربری SSH را بفرست (حروف کوچک انگلیسی، عدد، _ و -):"), reply_markup=_cancel_kb("adm_ssh_accounts"))

    @router.message(AdminSSH.acc_username, ~F.text.startswith("/"))
    async def msg_ssh_acc_username(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        username = (message.text or "").strip().lower()
        if not username or len(username) > 32 or not all(c.isalnum() or c in "_-" for c in username) or not username.isascii():
            return await message.answer(tr("نام کاربری نامعتبر است (فقط حروف انگلیسی، عدد، _ و -، حداکثر ۳۲ کاراکتر)."))
        await state.update_data(username=username)
        data = await state.get_data()
        pools = [p for p in ssh_service.overview(db)["pools"]
                 if p.get("status") == "active" and int(p["user_id"]) == int(data["user_id"])]
        if pools:
            rows = [[_btn(f"📦 #{p['id']} · {p.get('label') or ''}", f"adm_ssh_acc_pool:{p['id']}")] for p in pools]
            rows.append([_btn("بدون استخر (حجم مستقل)", "adm_ssh_acc_pool:0")])
            rows.append([_btn("❌ انصراف", "adm_ssh_accounts")])
            return await message.answer(tr("این کاربر استخر فعال دارد؛ حساب به کدام وصل شود؟"),
                                        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await state.update_data(pool_id=None)
        await state.set_state(AdminSSH.acc_limit)
        await message.answer(tr("سقف حجم مستقل (GB) را بفرست؛ 0 یعنی بدون محدودیت حجم:"), reply_markup=_cancel_kb("adm_ssh_accounts"))

    @router.callback_query(F.data.startswith("adm_ssh_acc_pool:"))
    async def cb_ssh_acc_pool(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        pool_id = int(call.data.split(":")[1])
        if pool_id:
            await state.update_data(pool_id=pool_id, limit_gb=0, days=0)
            return await _finish_account(call.message, state, call.from_user.id)
        await state.update_data(pool_id=None)
        await state.set_state(AdminSSH.acc_limit)
        await safe_edit(call, tr("سقف حجم مستقل (GB) را بفرست؛ 0 یعنی بدون محدودیت حجم:"), reply_markup=_cancel_kb("adm_ssh_accounts"))
        await call.answer()

    @router.message(AdminSSH.acc_limit, ~F.text.startswith("/"))
    async def msg_ssh_acc_limit(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        try:
            limit = float((message.text or "").replace(",", ".").strip())
            if limit < 0:
                raise ValueError
        except ValueError:
            return await message.answer(tr("عدد معتبر (۰ یا بیشتر) بفرست."))
        await state.update_data(limit_gb=limit)
        await state.set_state(AdminSSH.acc_days)
        await message.answer(tr("مدت اعتبار (روز) را بفرست؛ 0 یعنی بدون انقضا:"), reply_markup=_cancel_kb("adm_ssh_accounts"))

    @router.message(AdminSSH.acc_days, ~F.text.startswith("/"))
    async def msg_ssh_acc_days(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        text = (message.text or "").strip()
        if not text.isdigit():
            return await message.answer(tr("عدد صحیح بفرست."))
        await state.update_data(days=int(text))
        await _finish_account(message, state, message.from_user.id)

    async def _finish_account(msg: Message, state: FSMContext, admin_id: int):
        data = await state.get_data()
        await state.clear()
        wait = await msg.answer(tr("⏳ در حال ساخت حساب روی نود..."))
        try:
            r = await ssh_service.create_account(db, node_id=data["node_id"], user_id=data["user_id"],
                username=data["username"], limit_gb=data.get("limit_gb") or 0, days=data.get("days") or 0,
                quota_pool_id=data.get("pool_id"))
        except SSHServiceError as exc:
            return await wait.edit_text("❌ " + html.escape(str(exc)), reply_markup=_accounts_kb())
        _log(admin_id, "ssh_account_create", f"SSH account #{r['id']} for user {data['user_id']}")
        try:
            link = build_ssh_uri(r["username"], r["password"], r["host"], int(r["port"]), f"{r.get('node_name') or 'SSH'} {r['username']}")
        except ValueError:
            link = ""
        text = (f"✅ حساب SSH ساخته شد\n\n"
                f"نام کاربری: <code>{html.escape(r['username'])}</code>\n"
                f"رمز: <code>{html.escape(str(r['password']))}</code>\n"
                f"سرور: <code>{html.escape(str(r['host']))}:{int(r['port'])}</code>\n")
        if link:
            text += f"\nلینک:\n<code>{html.escape(link)}</code>\n"
        text += "\n⚠️ رمز فقط همین یک بار نمایش داده می‌شود."
        if r.get("warning"):
            text += f"\n⚠️ {html.escape(r['warning'])}"
        await wait.edit_text(text, parse_mode="HTML", reply_markup=_accounts_kb())

    # ------------------------------------------------------------------ استخرها
    def _pools_kb():
        return _kb(
            [_btn("➕ ساخت استخر", "adm_ssh_pool_add")],
            [_btn("🔗 اتصال VPN به استخر", "adm_ssh_attach")],
            [_btn("🔄 پایش و اعمال سهمیه", "adm_ssh_reconcile")],
            [_btn("↩️ بازگشت", "adm_ssh_menu")],
        )

    @router.callback_query(F.data == "adm_ssh_pools")
    async def cb_ssh_pools(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.clear()
        pools = ssh_service.overview(db)["pools"]
        lines = []
        for p in pools[-15:]:
            u = p.get("usage") or {}
            limit = _fmt_bytes(p["limit_bytes"]) if int(p.get("limit_bytes") or 0) else "نامحدود"
            lines.append(f"#{p['id']} · {p.get('label') or ''}\n   کاربر {p['user_id']} · {_fmt_bytes(u.get('used_bytes'))} از {limit} · "
                         f"{_st(p.get('status'))} · اعضا: {len(p.get('members') or [])}")
        text = "📦 استخرهای سهمیه:\n\n" + ("\n\n".join(lines) if lines else "استخری وجود ندارد.")
        await replace_admin_view(call, text, reply_markup=_pools_kb())
        await call.answer()

    @router.callback_query(F.data == "adm_ssh_reconcile")
    async def cb_ssh_reconcile(call: CallbackQuery):
        if not await _guard(call):
            return
        await call.answer(tr("در حال پایش..."))
        try:
            results = await ssh_service.reconcile(db)
        except Exception as exc:
            logger.exception("ssh reconcile failed")
            return await call.message.answer("❌ " + html.escape(str(exc)[:300]))
        _log(call.from_user.id, "ssh_quota_reconcile", f"Manual reconcile ({len(results)} pools)")
        failed = len([x for x in results if not x.get("enforcement_complete")])
        stale = len([x for x in results if x.get("state") == "stale"])
        msg = (f"پایش انجام شد؛ {failed} استخر نیازمند بررسی است." if failed else
               (f"{stale} استخر به‌علت گزارش مصرف قدیمی در حالت امن ماند." if stale else "✅ پایش سهمیه انجام شد."))
        await call.message.answer(msg)

    @router.callback_query(F.data == "adm_ssh_pool_add")
    async def cb_ssh_pool_add(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.set_state(AdminSSH.pool_user)
        await safe_edit(call, tr("شناسه عددی تلگرام صاحب استخر را بفرست:"), reply_markup=_cancel_kb("adm_ssh_pools"))
        await call.answer()

    @router.message(AdminSSH.pool_user, ~F.text.startswith("/"))
    async def msg_ssh_pool_user(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            return await message.answer(tr("شناسه باید عدد مثبت باشد."))
        if not db.get_user(int(text)):
            return await message.answer(tr("این کاربر در دیتابیس بات پیدا نشد."))
        await state.update_data(user_id=int(text))
        await state.set_state(AdminSSH.pool_limit)
        await message.answer(tr("سقف کل حجم (GB) را بفرست؛ 0 یعنی نامحدود:"), reply_markup=_cancel_kb("adm_ssh_pools"))

    @router.message(AdminSSH.pool_limit, ~F.text.startswith("/"))
    async def msg_ssh_pool_limit(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        try:
            limit = float((message.text or "").replace(",", ".").strip())
            if limit < 0:
                raise ValueError
        except ValueError:
            return await message.answer(tr("عدد معتبر (۰ یا بیشتر) بفرست."))
        await state.update_data(limit_gb=limit)
        await state.set_state(AdminSSH.pool_days)
        await message.answer(tr("مدت اعتبار (روز) را بفرست؛ 0 یعنی بدون انقضا:"), reply_markup=_cancel_kb("adm_ssh_pools"))

    @router.message(AdminSSH.pool_days, ~F.text.startswith("/"))
    async def msg_ssh_pool_days(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        text = (message.text or "").strip()
        if not text.isdigit():
            return await message.answer(tr("عدد صحیح بفرست."))
        data = await state.get_data()
        expires_at = None
        if int(text):
            from datetime import datetime, timedelta, timezone
            expires_at = (datetime.now(timezone.utc) + timedelta(days=int(text))).isoformat()
        try:
            pool_id = ssh_service.create_pool(db, data["user_id"], data["limit_gb"], expires_at, "سهمیه مشترک VPN + SSH")
        except SSHServiceError as exc:
            return await message.answer("❌ " + html.escape(str(exc)))
        _log(message.from_user.id, "ssh_pool_create", f"Shared quota pool #{pool_id} for user {data['user_id']}")
        await state.clear()
        await message.answer(f"✅ استخر #{pool_id} ساخته شد.", reply_markup=_pools_kb())

    # --- اتصال VPN به استخر
    @router.callback_query(F.data == "adm_ssh_attach")
    async def cb_ssh_attach(call: CallbackQuery):
        if not await _guard(call):
            return
        pools = [p for p in ssh_service.overview(db)["pools"] if p.get("status") == "active"]
        if not pools:
            await call.answer(tr("استخر فعالی وجود ندارد."), show_alert=True)
            return
        rows = [[_btn(f"📦 #{p['id']} · کاربر {p['user_id']} · {p.get('label') or ''}", f"adm_ssh_attach_pool:{p['id']}")] for p in pools[-20:]]
        rows.append([_btn("❌ انصراف", "adm_ssh_pools")])
        await safe_edit(call, tr("استخر را انتخاب کن:"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_ssh_attach_pool:"))
    async def cb_ssh_attach_pool(call: CallbackQuery, state: FSMContext):
        if not await _guard(call):
            return
        await state.update_data(pool_id=int(call.data.split(":")[1]))
        await state.set_state(AdminSSH.attach_config)
        await safe_edit(call, tr("شناسه کانفیگ VPN (custom config) را بفرست:"), reply_markup=_cancel_kb("adm_ssh_pools"))
        await call.answer()

    @router.message(AdminSSH.attach_config, ~F.text.startswith("/"))
    async def msg_ssh_attach_config(message: Message, state: FSMContext):
        if not _msg_ok(message):
            return
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            return await message.answer(tr("شناسه باید عدد مثبت باشد."))
        data = await state.get_data()
        try:
            ssh_service.attach_vpn(db, data["pool_id"], int(text))
        except SSHServiceError as exc:
            return await message.answer("❌ " + html.escape(str(exc)))
        _log(message.from_user.id, "ssh_pool_attach_vpn", f"Pool #{data['pool_id']} <- custom_config:{text}")
        await state.clear()
        await message.answer(tr("✅ کانفیگ VPN به استخر متصل شد."), reply_markup=_pools_kb())
