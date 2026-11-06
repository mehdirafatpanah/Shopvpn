# -*- coding: utf-8 -*-
"""منوی «مدیریت لینک‌ها» داخل پنل مدیریت بات (فقط مالک و مدیر کامل).

ادمین بدون ورود به سرور یا ویرایش .env می‌تواند:
• همه‌ی لینک‌های مهم (مینی‌اپ، فروشگاه وب، پنل مدیریت وب، سرور ساب اختصاصی، لینک پشتیبانی ساب) را یک‌جا ببیند و کپی کند،
• سالم‌بودن (در دسترس‌بودن) همه را با یک دکمه تست کند،
• آدرس‌هایی را که تنظیم داخل بات دارند ویرایش کند (آدرس سرور ساب، لینک پشتیبانی ساب، آدرس پنل وب)،
• لینک اشتراک (لینک پنل + لینک اختصاصی) یک سرویس را با نام کاربری یا خود لینک پیدا کند.

مینی‌اپ و فروشگاه وب فقط از .env / manage.sh خوانده می‌شوند (تغییرشان نیاز به راه‌اندازی مجدد سرویس دارد)،
پس اینجا فقط نمایش و تست می‌شوند.
"""

import asyncio
import html
import os
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import dedicated_sub as ds
from states import AdminLinksInput

# کلیدهای قابل ویرایش داخل بات: key → (عنوان، راهنما)
EDITABLE = {
    "dsub_base_url": ("🌐 آدرس سرور ساب", "فرمت: https://sub.example.com — خالی/«-» = همان دامنه‌ی manage.sh."),
    "dsub_support_url": ("🆘 لینک پشتیبانی صفحه‌ی ساب", "مثلاً https://t.me/username — «-» برای خالی‌کردن."),
    "admin_panel_url": ("🖥 آدرس پنل مدیریت وب", "فرمت: https://panel.example.com — «-» برای برگشت به مقدار .env."),
}


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _e(text) -> str:
    return html.escape(str(text or ""))


def _norm_url(raw: str) -> str:
    return (raw or "").strip().rstrip("/")


def collect_links(db) -> list:
    """فهرست لینک‌های مهم؛ هر مورد: dict(key, title, url, source, editable_key, probe_path)."""
    try:
        import config
        miniapp = _norm_url(getattr(config, "MINIAPP_URL", ""))
        panel_env = _norm_url(getattr(config, "ADMIN_PANEL_URL", ""))
    except Exception:
        miniapp = _norm_url(os.getenv("MINIAPP_URL", ""))
        panel_env = _norm_url(os.getenv("ADMIN_PANEL_URL", ""))
    store = _norm_url(os.getenv("SHOPVPN_SEO_SITE_URL", ""))
    panel_db = _norm_url(db.get_setting("admin_panel_url", ""))
    dsub_db = _norm_url(db.get_setting("dsub_base_url", ""))
    dsub_url = ds.base_url(db)
    support = (db.get_setting("dsub_support_url", "") or "").strip()
    dsub_on = ds.is_enabled(db)
    return [
        {"key": "miniapp", "title": "📱 مینی‌اپ فروشگاه", "url": miniapp, "source": ".env (MINIAPP_URL)",
         "editable": None, "probe": ""},
        {"key": "store", "title": "🛍 فروشگاه وب", "url": (store + "/") if store else "", "source": "manage.sh (گزینه‌ی فروشگاه وب)",
         "editable": None, "probe": ""},
        {"key": "panel", "title": "🖥 پنل مدیریت وب", "url": panel_db or panel_env,
         "source": "تنظیم داخل بات" if panel_db else ".env (ADMIN_PANEL_URL)",
         "editable": "admin_panel_url", "probe": ""},
        {"key": "dsub", "title": "🔗 سرور ساب اختصاصی" + ("" if dsub_on else " (خاموش)"), "url": dsub_url,
         "source": "تنظیم داخل بات" if (dsub_db.startswith(("http://", "https://"))) else ".env / manage.sh",
         "editable": "dsub_base_url", "probe": "/healthz"},
        {"key": "support", "title": "🆘 لینک پشتیبانی صفحه‌ی ساب", "url": support, "source": "تنظیم داخل بات",
         "editable": "dsub_support_url", "probe": None},  # None = تست نمی‌شود (مثلاً t.me)
    ]


async def probe_url(url: str, path: str = "") -> tuple:
    """(ok, detail, ms). هر پاسخ HTTP زیر ۵۰۰ یعنی سرور زنده است."""
    import aiohttp
    started = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url.rstrip("/") + path, allow_redirects=True) as resp:
                ok = resp.status < 500
                detail = f"HTTP {resp.status}"
    except Exception as exc:
        ok, detail = False, type(exc).__name__
    return ok, detail, int((time.monotonic() - started) * 1000)


def validate(key: str, raw: str):
    """(value, error). «-» یعنی خالی کردن (برگشت به مقدار پیش‌فرض/.env)."""
    raw = (raw or "").strip()
    if raw == "-":
        return "", None
    if " " in raw or "\n" in raw:
        return None, "لینک نباید فاصله یا چند خط داشته باشد."
    if len(raw) > 300:
        return None, "لینک بیش از حد طولانی است (حداکثر ۳۰۰ نویسه)."
    if key == "dsub_support_url":
        if not raw.lower().startswith(("https://", "http://", "tg://")):
            return None, "لینک باید با https:// یا tg:// شروع شود."
        return raw, None
    if not raw.lower().startswith("https://"):
        return None, "آدرس باید با https:// شروع شود."
    return raw.rstrip("/"), None


def find_services(db, query: str) -> list:
    """سرویس‌ها را با نام کاربری پنل یا لینک اشتراک پیدا می‌کند (حداکثر ۵ مورد)."""
    query = (query or "").strip()
    if not query:
        return []
    results = []
    seen = set()
    # ۱) اگر لینک اختصاصی داده شده، معادل پنل آن را بساز
    upstream = ""
    if query.startswith(("http://", "https://")):
        try:
            upstream = ds.upstream_for_link(db, query) or query
        except Exception:
            upstream = query
        try:
            row = db.ds_find_config_by_sub_url(upstream)
        except Exception:
            row = None
        if row is not None and row["id"] not in seen:
            seen.add(row["id"])
            results.append(row)
    # ۲) نام کاربری روی هر پنل
    if not query.startswith(("http://", "https://")):
        for server in db.get_panel_servers(include_mirrors=True):
            row = db.find_custom_config_by_panel_username(server["id"], query)
            if row is not None and row["id"] not in seen:
                seen.add(row["id"])
                results.append(row)
            if len(results) >= 5:
                break
    return results[:5]


def register(router: Router, db, senior_admin_only, deny_mid, replace_admin_view):

    async def _main_view(note: str = ""):
        links = await asyncio.to_thread(collect_links, db)
        lines = [note, ""] if note else []
        lines += ["🔗 مدیریت لینک‌ها", "",
                  "لینک‌های مهم فروشگاه (با یک لمس روی لینک کپی می‌شود):", ""]
        for item in links:
            url = item["url"]
            lines.append(f"{item['title']}")
            lines.append(f"  <code>{_e(url)}</code>" if url else "  ⚠️ تنظیم نشده")
            lines.append(f"  منبع: {_e(item['source'])}")
            lines.append("")
        lines.append("ℹ️ مینی‌اپ و فروشگاه وب از .env/manage.sh خوانده می‌شوند و فقط از آنجا قابل تغییرند. "
                     "بقیه را با دکمه‌های ✏️ همین‌جا عوض کن (بدون ری‌استارت اعمال می‌شود).")
        rows = [[_btn("🧪 بررسی سالم‌بودن همه‌ی لینک‌ها", "adm_links_probe")],
                [_btn("🔎 لینک اشتراک یک سرویس", "adm_links_svc")]]
        edit_row = []
        for key, (title, _hint) in EDITABLE.items():
            edit_row.append(_btn("✏️ " + title, f"adm_links_set:{key}"))
            if len(edit_row) == 2:
                rows.append(edit_row)
                edit_row = []
        if edit_row:
            rows.append(edit_row)
        rows.append([_btn("⬅️ بازگشت", "adm_cat:products")])
        return "\n".join(lines).strip(), _kb(rows)

    async def _show(call: CallbackQuery, note: str = ""):
        text, markup = await _main_view(note)
        await replace_admin_view(call, text, reply_markup=markup, parse_mode="HTML")

    @router.callback_query(F.data == "adm_links")
    async def cb_main(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await _show(call)
        await call.answer()

    # ------------------------------------------------------------------ تست سالم‌بودن
    @router.callback_query(F.data == "adm_links_probe")
    async def cb_probe(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await call.answer("در حال بررسی...")
        links = await asyncio.to_thread(collect_links, db)
        targets = [(i, i["url"], i["probe"]) for i in links if i["url"] and i["probe"] is not None]
        results = await asyncio.gather(*(probe_url(u, p) for _i, u, p in targets)) if targets else []
        by_key = {t[0]["key"]: r for t, r in zip(targets, results)}
        out = ["🧪 نتیجه‌ی بررسی لینک‌ها", ""]
        for item in links:
            if not item["url"]:
                out.append(f"⚠️ {item['title']}: تنظیم نشده")
            elif item["key"] not in by_key:
                out.append(f"➖ {item['title']}: بررسی نمی‌شود")
            else:
                ok, detail, ms = by_key[item["key"]]
                out.append(f"{'✅' if ok else '❌'} {item['title']}: {_e(detail)} ({ms} ms)")
        out += ["", "✅ یعنی سرور پاسخ داد؛ ❌ یعنی دامنه/SSL/سرویس مشکل دارد. "
                    "دقت کن این تست از خودِ سرور شما انجام می‌شود، نه از اینترنت کاربران (مثلاً ایرانسل)."]
        text, markup = await _main_view("\n".join(out))
        await replace_admin_view(call, text, reply_markup=markup, parse_mode="HTML")

    # ------------------------------------------------------------------ ویرایش
    @router.callback_query(F.data.startswith("adm_links_set:"))
    async def cb_set(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        key = call.data.split(":", 1)[1]
        if key not in EDITABLE:
            return await call.answer()
        title, hint = EDITABLE[key]
        current = await asyncio.to_thread(db.get_setting, key, "")
        await state.set_state(AdminLinksInput.waiting_value)
        await state.update_data(al_key=key)
        text = (f"✏️ {title}\n\nمقدار فعلی: <code>{_e(current) or '—'}</code>\n\n{_e(hint)}\n\n"
                "مقدار جدید را بفرست:")
        await replace_admin_view(call, text, reply_markup=_kb([[_btn("❌ انصراف", "adm_links")]]), parse_mode="HTML")
        await call.answer()

    @router.message(AdminLinksInput.waiting_value)
    async def msg_value(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        data = await state.get_data()
        key = data.get("al_key")
        if key not in EDITABLE:
            await state.clear()
            return
        if (message.text or "").startswith("/"):
            await state.clear()
            return await message.answer("لغو شد.", reply_markup=_kb([[_btn("🔗 مدیریت لینک‌ها", "adm_links")]]))
        value, err = validate(key, message.text or "")
        if err:
            return await message.answer(f"⚠️ {err}\nدوباره بفرست یا /admin را بزن.")
        await asyncio.to_thread(db.set_setting, key, value)
        await state.clear()
        text, markup = await _main_view(f"✅ «{EDITABLE[key][0]}» ذخیره شد.")
        await message.answer(text, reply_markup=markup, parse_mode="HTML")

    # ------------------------------------------------------------------ لینک اشتراک یک سرویس
    @router.callback_query(F.data == "adm_links_svc")
    async def cb_svc(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminLinksInput.waiting_service)
        text = ("🔎 لینک اشتراک یک سرویس\n\nنام کاربری سرویس روی پنل، یا خودِ لینک اشتراک "
                "(لینک پنل یا لینک اختصاصی) را بفرست:")
        await replace_admin_view(call, text, reply_markup=_kb([[_btn("❌ انصراف", "adm_links")]]))
        await call.answer()

    @router.message(AdminLinksInput.waiting_service)
    async def msg_service(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        if (message.text or "").startswith("/"):
            await state.clear()
            return await message.answer("لغو شد.", reply_markup=_kb([[_btn("🔗 مدیریت لینک‌ها", "adm_links")]]))
        rows = await asyncio.to_thread(find_services, db, message.text or "")
        if not rows:
            return await message.answer("⚠️ سرویسی پیدا نشد. نام کاربری یا لینک را دقیق بفرست یا /admin را بزن.")
        await state.clear()
        servers = {s["id"]: s for s in await asyncio.to_thread(db.get_panel_servers, include_mirrors=True)}
        out = ["🔎 نتیجه", ""]
        for row in rows:
            server = servers.get(row["panel_server_id"])
            panel_link = (row["subscription_url"] or "").strip()
            dedicated = await asyncio.to_thread(ds.display_link, db, row["id"], panel_link)
            out.append(f"👤 {_e(row['username'])} | کاربر بات: <code>{row['user_id']}</code> | "
                       f"پنل: {_e(server['name']) if server else row['panel_server_id']}")
            out.append(f"لینک پنل: <code>{_e(panel_link) or '—'}</code>")
            if dedicated and dedicated != panel_link:
                out.append(f"لینک اختصاصی: <code>{_e(dedicated)}</code>")
            out.append("")
        await message.answer("\n".join(out).strip(), parse_mode="HTML",
                             reply_markup=_kb([[_btn("🔎 جستجوی دیگر", "adm_links_svc")],
                                               [_btn("🔗 مدیریت لینک‌ها", "adm_links")]]))
