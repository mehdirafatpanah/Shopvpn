# -*- coding: utf-8 -*-
"""منوی «ساب مرکزی» داخل پنل مدیریت بات (فقط مالک و مدیر کامل).

راه‌اندازی اولیه (دامنه، SSL، سرویس) از منوی manage.sh انجام می‌شود؛ همه‌ی بقیه‌ی تنظیمات از اینجا:
روشن/خاموش، ظاهر صفحه‌ی وب، خروجی ساب (هدرها/خط اول/کانفیگ نمایشی)، برنامه‌ها، سوالات متداول و آمار.
"""

import asyncio
import html
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import dedicated_sub as ds
from states import AdminDSubInput

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# کلیدهای متنی/عددی قابل ویرایش: key → (عنوان، راهنما، حداکثر طول، نوع)
# نوع: text | url | int:lo:hi | multiline
FIELDS = {
    "dsub_brand": ("🏷 نام برند صفحه", "نامی که بالای صفحه‌ی وب نشان داده می‌شود. خالی = نام فروشگاه.", 40, "text"),
    "dsub_logo_url": ("🖼 لوگوی صفحه", "آدرس تصویر لوگو (فقط https). تصویر مربعی بهتر دیده می‌شود.", 300, "https"),
    "dsub_notice": ("🔔 اطلاعیه", "بالای صفحه‌ی وب و داخل اپ‌هایی که هدر announce را پشتیبانی می‌کنند (Hiddify، Happ...) نشان داده می‌شود.", 200, "text"),
    "dsub_support_url": ("🆘 لینک پشتیبانی", "مثلاً https://t.me/username. دکمه‌ی «پشتیبانی» پایین صفحه و هدر support-url اپ‌ها.", 300, "link"),
    "dsub_footer_text": ("📝 متن پایین صفحه", "یک خط توضیح یا قانون کوتاه پایین صفحه.", 200, "text"),
    "dsub_profile_title": ("🏷 عنوان پروفایل داخل اپ", "نامی که اپ برای این اشتراک نشان می‌دهد. متغیرها: {name} نام سرویس، {user} نام کاربری، {brand} برند.", 80, "text"),
    "dsub_update_interval": ("🔄 بازه‌ی به‌روزرسانی اپ", "هر چند ساعت اپ ساب را دوباره بگیرد (۰ = تصمیم با پنل).", 3, "int:0:168"),
    "dsub_info_line_text": ("📊 متن خط اول ساب", "متغیرها: {volume} باقی‌مانده، {used} مصرف، {total} کل، {days} روز باقی‌مانده.", 100, "text"),
    "dsub_expired_text": ("⛔ متن کانفیگ نمایشی منقضی", "وقتی سرویس منقضی یا غیرفعال است، به‌جای کانفیگ این پیام داخل اپ نشان داده می‌شود.", 100, "text"),
    "dsub_limited_text": ("📶 متن کانفیگ نمایشی حجم تمام‌شده", "وقتی حجم سرویس تمام شده است.", 100, "text"),
    "dsub_cache_ttl": ("⏱ کش پاسخ پنل (ثانیه)", "برای کم کردن فشار روی پنل. ۰ = بدون کش. بیشینه ۶۰۰.", 3, "int:0:600"),
    "dsub_base_url": ("🌐 آدرس سرور ساب", "فقط اگر می‌خواهی آدرس را دستی عوض کنی (مثلاً پشت Cloudflare). فرمت: https://sub.example.com — خالی = همان دامنه‌ی manage.sh.", 200, "https"),
    "dsub_faq": ("❓ سوالات متداول", "هر خط یک مورد: «سوال | جواب». بیشینه ۱۰ مورد. با - به پیش‌فرض برمی‌گردد.", 3000, "faq"),
}

TOGGLES = {
    "dsub_web_page": "🌐 صفحه‌ی وب برای مرورگر",
    "dsub_show_configs": "📋 بخش کانفیگ‌ها",
    "dsub_show_chart": "📈 نمودار مصرف",
    "dsub_show_qr": "🔳 دکمه‌های QR",
    "dsub_show_apps": "📱 بخش برنامه‌ها",
    "dsub_show_faq": "❓ بخش «اگر وصل نشد»",
    "dsub_info_line": "📊 خط اول ساب (حجم و روز)",
    "dsub_expired_placeholder": "⛔ کانفیگ نمایشی برای منقضی/تمام‌شده",
    "dsub_usage_sampling": "🕒 نمونه‌برداری مصرف (برای نمودار)",
    "dsub_log_enabled": "🧾 لاگ دسترسی",
}


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _on(flag) -> str:
    return "🟢 روشن" if flag else "🔴 خاموش"


def _e(text) -> str:
    return html.escape(str(text or ""))


def _short(text: str, n: int = 60) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _ua_family(ua: str) -> str:
    low = (ua or "").lower()
    for key, name in (("v2rayng", "v2rayNG"), ("hiddify", "Hiddify"), ("streisand", "Streisand"), ("happ", "Happ"),
                      ("v2box", "V2Box"), ("sing-box", "sing-box"), ("singbox", "sing-box"), ("clash", "Clash"),
                      ("shadowrocket", "Shadowrocket"), ("karing", "Karing"), ("nekobox", "NekoBox"),
                      ("v2rayn", "v2rayN"), ("flclash", "FlClash"), ("okhttp", "okhttp")):
        if key in low:
            return name
    return "سایر"


def register(router: Router, db, senior_admin_only, deny_mid, replace_admin_view):

    async def _get(key):
        return await asyncio.to_thread(ds.get, db, key)

    async def _flag(key):
        return (await _get(key)).strip() == "1"

    async def _present(target, text, markup):
        if isinstance(target, CallbackQuery):
            await replace_admin_view(target, text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)

    # ------------------------------------------------------------------ صفحه‌ی اصلی
    async def _main_view(note: str = ""):
        enabled = await _flag("dsub_enabled")
        base = await asyncio.to_thread(ds.base_url, db)
        s = await asyncio.to_thread(ds.all_settings, db)
        lines = [note, ""] if note else []
        lines += [
            "🔗 ساب مرکزی",
            "",
            "لینک اشتراک سرویس‌ها از دامنه‌ی خودت صادر می‌شود (آدرس پنل دیده نمی‌شود) و کاربر با باز کردن لینک "
            "در مرورگر یک صفحه‌ی وب زیبا با مصرف، کانفیگ‌ها و دکمه‌ی «افزودن به برنامه» می‌بیند. "
            "اپ‌ها همان لینک را به‌صورت ساب معمولی دریافت می‌کنند.",
            "",
            f"وضعیت: {_on(enabled)}",
            f"سرور: {_e(base) if base else '⚠️ هنوز راه‌اندازی نشده'}",
        ]
        if not base:
            lines += ["", "راه‌اندازی اولیه (فقط یک بار) روی سرور: «bash manage.sh» ← گزینه‌ی ۲۷ (نصب/تنظیم سرور ساب مرکزی). "
                          "بعد از آن همین‌جا روشنش کن."]
        else:
            lines += [
                f"صفحه‌ی وب: {_on(s['dsub_web_page'] == '1')} | خط اول ساب: {_on(s['dsub_info_line'] == '1')}",
                f"کانفیگ نمایشی منقضی: {_on(s['dsub_expired_placeholder'] == '1')} | قالب: {_e(s['dsub_theme'])}",
            ]
        lines += ["", "ℹ️ با خاموش کردن، لینک‌هایی که قبلاً به کاربران داده شده کار می‌کنند (عبور ساده‌ی ساب پنل، بدون صفحه‌ی وب "
                      "و بدون تغییر)، ولی لینک‌های جدید دوباره آدرس خود پنل می‌شوند."]
        rows = [
            [_btn("🔴 خاموش کردن" if enabled else "🟢 روشن کردن", "adm_dsub_toggle")],
            [_btn("🎨 ظاهر صفحه‌ی وب", "adm_dsub_pg:look"), _btn("📡 خروجی ساب", "adm_dsub_pg:out")],
            [_btn("📱 برنامه‌ها", "adm_dsub_pg:apps"), _btn("❓ سوالات متداول", "adm_dsub_pg:faq")],
            [_btn("📊 آمار و لاگ", "adm_dsub_pg:stats"), _btn("🧪 تست سرور", "adm_dsub_test")],
            [_btn("📘 راهنمای راه‌اندازی", "adm_dsub_pg:guide")],
            [_btn("⬅️ بازگشت", "adm_cat:products")],
        ]
        return "\n".join(lines), _kb(rows)

    @router.callback_query(F.data == "adm_dsub")
    async def cb_main(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        text, markup = await _main_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data == "adm_dsub_toggle")
    async def cb_toggle_main(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        enabled = await _flag("dsub_enabled")
        if not enabled and not await asyncio.to_thread(ds.base_url, db):
            return await call.answer("اول باید سرور ساب را از manage.sh (گزینه‌ی ۲۹) راه‌اندازی کنی.", show_alert=True)
        await asyncio.to_thread(db.set_setting, "dsub_enabled", "0" if enabled else "1")
        text, markup = await _main_view("🟢 ساب مرکزی روشن شد." if not enabled else "🔴 ساب مرکزی خاموش شد.")
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer("ذخیره شد.")

    # ------------------------------------------------------------------ تست سرور
    @router.callback_query(F.data == "adm_dsub_test")
    async def cb_test(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        base = await asyncio.to_thread(ds.base_url, db)
        if not base:
            return await call.answer("سرور هنوز راه‌اندازی نشده است (manage.sh ← گزینه‌ی ۲۹).", show_alert=True)
        await call.answer("در حال تست...")
        import aiohttp
        started = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(base + "/healthz") as resp:
                    ok = resp.status == 200
                    detail = f"HTTP {resp.status}"
        except Exception as exc:
            ok, detail = False, type(exc).__name__
        ms = int((time.monotonic() - started) * 1000)
        note = (f"✅ سرور ساب پاسخ داد ({ms} میلی‌ثانیه)." if ok else
                f"❌ سرور ساب پاسخ نداد ({_e(detail)}). دامنه/SSL و سرویس v2raybot-sub را از manage.sh بررسی کن.")
        text, markup = await _main_view(note)
        await replace_admin_view(call, text, reply_markup=markup)

    # ------------------------------------------------------------------ صفحه‌های تنظیمات
    async def _toggle_row(key):
        return [_btn(f"{TOGGLES[key]}: {_on(await _flag(key))}", f"adm_dsub_t:{key}")]

    def _edit_btn(key, label=None):
        return _btn(f"✏️ {label or FIELDS[key][0]}", f"adm_dsub_set:{key}")

    async def _look_view(note=""):
        s = await asyncio.to_thread(ds.all_settings, db)
        lines = [note, ""] if note else []
        lines += [
            "🎨 ظاهر صفحه‌ی وب",
            "",
            "طرح صفحه ثابت است (سیاه‌وسفید با حالت تاریک/روشن)؛ از اینجا بخش‌ها، متن‌ها و برند را شخصی‌سازی می‌کنی.",
            "",
            f"برند: {_e(s['dsub_brand']) or '— (نام فروشگاه)'}",
            f"لوگو: {_e(_short(s['dsub_logo_url'])) or '—'}",
            f"اطلاعیه: {_e(_short(s['dsub_notice'])) or '—'}",
            f"پشتیبانی: {_e(_short(s['dsub_support_url'])) or '—'}",
            f"متن پایین: {_e(_short(s['dsub_footer_text'])) or '—'}",
            f"قالب پیش‌فرض: {_e(s['dsub_theme'])} (کاربر خودش هم می‌تواند عوض کند)",
        ]
        rows = [await _toggle_row(k) for k in ("dsub_web_page", "dsub_show_configs", "dsub_show_chart",
                                                "dsub_show_qr", "dsub_show_apps", "dsub_show_faq")]
        rows.append([_btn(f"🌓 قالب: {s['dsub_theme']}", "adm_dsub_theme")])
        rows += [[_edit_btn("dsub_brand"), _edit_btn("dsub_logo_url")],
                 [_edit_btn("dsub_notice"), _edit_btn("dsub_support_url")],
                 [_edit_btn("dsub_footer_text")],
                 [_btn("⬅️ بازگشت", "adm_dsub")]]
        return "\n".join(lines), _kb(rows)

    async def _out_view(note=""):
        s = await asyncio.to_thread(ds.all_settings, db)
        lines = [note, ""] if note else []
        lines += [
            "📡 خروجی ساب (چیزی که اپ‌ها می‌گیرند)",
            "",
            f"عنوان پروفایل: {_e(s['dsub_profile_title']) or '— (از پنل)'}",
            f"بازه‌ی به‌روزرسانی: {_e(s['dsub_update_interval'])} ساعت",
            f"خط اول ساب: {_on(s['dsub_info_line'] == '1')} — {_e(_short(s['dsub_info_line_text']))}",
            f"کانفیگ نمایشی منقضی: {_on(s['dsub_expired_placeholder'] == '1')}",
            f"  منقضی: {_e(_short(s['dsub_expired_text']))}",
            f"  حجم تمام‌شده: {_e(_short(s['dsub_limited_text']))}",
            f"کش پاسخ پنل: {_e(s['dsub_cache_ttl'])} ثانیه",
            f"آدرس سرور: {_e(s['dsub_base_url']) or '— (از manage.sh)'}",
            "",
            "«خط اول ساب» و «کانفیگ نمایشی» فقط روی ساب‌هایی کار می‌کنند که فرمت لینک (vless/vmess/...) دارند؛ "
            "ساب‌های Clash/JSON بدون دستکاری عبور می‌کنند. فرمت خروجی (Clash، sing-box، v2ray) را خود پنل بر اساس "
            "User-Agent اپ انتخاب می‌کند و سرور ساب همان User-Agent را به پنل می‌فرستد.",
        ]
        rows = [await _toggle_row(k) for k in ("dsub_info_line", "dsub_expired_placeholder",
                                                "dsub_usage_sampling", "dsub_log_enabled")]
        rows += [[_edit_btn("dsub_profile_title"), _edit_btn("dsub_update_interval")],
                 [_edit_btn("dsub_info_line_text")],
                 [_edit_btn("dsub_expired_text"), _edit_btn("dsub_limited_text")],
                 [_edit_btn("dsub_cache_ttl"), _edit_btn("dsub_base_url")],
                 [_btn("⬅️ بازگشت", "adm_dsub")]]
        return "\n".join(lines), _kb(rows)

    async def _faq_view(note=""):
        s = await asyncio.to_thread(ds.all_settings, db)
        custom = ds.parse_faq(s["dsub_faq"])
        items = ds.resolve_faq(s)
        lines = [note, ""] if note else []
        lines += ["❓ سوالات متداول صفحه‌ی وب", "", f"منبع: {'سفارشی' if custom else 'پیش‌فرض'} — {len(items)} مورد", ""]
        for i, (q, a) in enumerate(items, 1):
            lines.append(f"{i}. {_e(q)}\n   ↳ {_e(_short(a, 80))}")
        rows = [[_edit_btn("dsub_faq", "ویرایش سوالات")],
                [_btn("♻️ برگشت به پیش‌فرض", "adm_dsub_faq_reset")],
                [_btn("⬅️ بازگشت", "adm_dsub")]]
        return "\n".join(lines), _kb(rows)

    async def _apps_view(note=""):
        s = await asyncio.to_thread(ds.all_settings, db)
        apps = ds.resolve_apps(s)
        custom, errors = ds.parse_custom_apps(s["dsub_custom_apps"])
        lines = [note, ""] if note else []
        lines += ["📱 برنامه‌ها", "",
                  "فهرست برنامه‌ها برای iOS، اندروید، ویندوز، مک و لینوکس (با دکمه‌ی «افزودن» و «دانلود») در صفحه‌ی وب نشان داده می‌شود. "
                  "سیستم‌عامل را انتخاب کن تا برنامه‌ها را مخفی/نمایش بدهی یا برنامه‌ی پیشنهادی را عوض کنی.", ""]
        for plat in ds.PLATFORMS:
            lines.append(f"{ds.PLATFORM_LABELS[plat]}: {len(apps[plat])} برنامه")
        lines.append(f"برنامه‌های سفارشی: {len(custom)}")
        rows = [[_btn(ds.PLATFORM_LABELS[p], f"adm_dsub_pl:{p}") for p in ds.PLATFORMS[:3]],
                [_btn(ds.PLATFORM_LABELS[p], f"adm_dsub_pl:{p}") for p in ds.PLATFORMS[3:]],
                [_btn("➕ افزودن برنامه‌ی سفارشی", "adm_dsub_ca_add")]]
        if custom:
            rows.append([_btn("🗑 حذف همه‌ی برنامه‌های سفارشی", "adm_dsub_ca_clear")])
        rows.append([_btn("⬅️ بازگشت", "adm_dsub")])
        return "\n".join(lines), _kb(rows)

    async def _platform_view(plat, note=""):
        s = await asyncio.to_thread(ds.all_settings, db)
        hidden = ds._pairs(s["dsub_apps_hidden"])
        visible = {a["n"]: a for a in ds.resolve_apps(s)[plat]}
        names = ds.all_app_names(s, plat)
        lines = [note, ""] if note else []
        lines += [f"📱 برنامه‌های {ds.PLATFORM_LABELS[plat]}", "",
                  "✅ نمایش داده می‌شود | 🚫 مخفی است | ⭐ پیشنهادی (اولین کارت، دکمه‌ی بالای صفحه از برنامه‌ی پیشنهادی ساخته می‌شود)", ""]
        rows = []
        for i, name in enumerate(names):
            is_hidden = (plat, name.lower()) in hidden
            app = visible.get(name)
            mark = "🚫" if is_hidden else ("⭐" if app and app.get("rec") else "✅")
            lines.append(f"{mark} {_e(name)}")
            rows.append([_btn(f"{'نمایش' if is_hidden else 'مخفی'}: {name}", f"adm_dsub_ah:{plat}:{i}"),
                         _btn("⭐ پیشنهادی", f"adm_dsub_ar:{plat}:{i}")])
        rows.append([_btn("⬅️ بازگشت", "adm_dsub_pg:apps")])
        return "\n".join(lines), _kb(rows)

    async def _stats_view(note=""):
        now = int(time.time())
        day = await asyncio.to_thread(db.ds_access_stats, now - 86400)
        week = await asyncio.to_thread(db.ds_access_stats, now - 7 * 86400)
        fam = {}
        for ua in day["uas"]:
            fam[_ua_family(ua)] = fam.get(_ua_family(ua), 0) + 1
        top = "، ".join(f"{k} ({v})" for k, v in sorted(fam.items(), key=lambda x: -x[1])[:5]) or "—"
        lines = [note, ""] if note else []
        lines += [
            "📊 آمار و لاگ ساب مرکزی", "",
            f"۲۴ ساعت اخیر: {day['total']:,} درخواست | {day['services']:,} سرویس | {day['ips']:,} IP | {day['errors']:,} خطا | {day['pages']:,} بازدید صفحه",
            f"۷ روز اخیر: {week['total']:,} درخواست | {week['services']:,} سرویس | {week['ips']:,} IP",
            f"برنامه‌های پرکاربرد (۲۴ ساعت): {_e(top)}", "",
            "آخرین دسترسی‌ها:",
        ]
        for r in day["recent"] or week["recent"]:
            when = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
            lines.append(f"• {when} | {r['kind']} | {r['status']} | {_e(r['username'] or '—')} | {_e(r['ip'])}")
        if not (day["recent"] or week["recent"]):
            lines.append("• هنوز دسترسی ثبت نشده")
        lines += ["", "لاگ‌ها ۳۰ روز نگه داشته می‌شوند. بالا رفتن تعداد IP یک سرویس می‌تواند نشانه‌ی اشتراک‌گذاری باشد."]
        return "\n".join(lines), _kb([[_btn("🔄 بروزرسانی", "adm_dsub_pg:stats")], [_btn("⬅️ بازگشت", "adm_dsub")]])

    GUIDE = (
        "📘 راهنمای راه‌اندازی ساب مرکزی\n\n"
        "۱) یک دامنه یا ساب‌دامنه بگیر (مثلاً sub.example.com) و رکورد A آن را به IP همین سرور بزن.\n"
        "۲) روی سرور اجرا کن: bash manage.sh ← گزینه‌ی ۲۹ «نصب/تنظیم سرور ساب مرکزی». دامنه را وارد کن؛ "
        "nginx، SSL و سرویس خودکار ساخته می‌شود و آخرش می‌پرسد همان لحظه روشن شود یا نه.\n"
        "۳) همین‌جا (ادمین بات) روشن/خاموش و همه‌ی شخصی‌سازی‌ها را انجام بده.\n\n"
        "از آن لحظه، سرویس‌های جدیدی که تحویل داده می‌شوند لینک sub.example.com/s/… می‌گیرند؛ سرویس‌های قبلی هم در «سرویس‌های من» "
        "با لینک اختصاصی نشان داده می‌شوند. روشن/خاموش بدون ری‌استارت اعمال می‌شود (تا ۸ ثانیه).\n\n"
        "دستورهای manage.sh: ۲۹ نصب | ۳۰ روشن/خاموش | ۳۱ آپدیت | ۳۲ حذف.\n"
        "نکته: لینک‌های اشتراک هوشمند (/smartsub) هم از همین سرور ساخته می‌شوند."
    )

    PAGES = {"look": _look_view, "out": _out_view, "apps": _apps_view, "faq": _faq_view, "stats": _stats_view}

    @router.callback_query(F.data.startswith("adm_dsub_pg:"))
    async def cb_page(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        page = call.data.split(":", 1)[1]
        if page == "guide":
            await replace_admin_view(call, GUIDE, reply_markup=_kb([[_btn("⬅️ بازگشت", "adm_dsub")]]))
        elif page in PAGES:
            text, markup = await PAGES[page]()
            await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    async def _refresh(call, key_or_page_hint, note="ذخیره شد."):
        page = "out" if key_or_page_hint in ("dsub_info_line", "dsub_expired_placeholder", "dsub_usage_sampling",
                                              "dsub_log_enabled") else "look"
        text, markup = await PAGES[page]()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(note)

    @router.callback_query(F.data.startswith("adm_dsub_t:"))
    async def cb_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        key = call.data.split(":", 1)[1]
        if key not in TOGGLES:
            return await call.answer()
        cur = await _flag(key)
        await asyncio.to_thread(db.set_setting, key, "0" if cur else "1")
        await _refresh(call, key)

    @router.callback_query(F.data == "adm_dsub_theme")
    async def cb_theme(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        cur = await _get("dsub_theme")
        nxt = ds.THEMES[(ds.THEMES.index(cur) + 1) % len(ds.THEMES)] if cur in ds.THEMES else "auto"
        await asyncio.to_thread(db.set_setting, "dsub_theme", nxt)
        await _refresh(call, "dsub_theme")

    @router.callback_query(F.data == "adm_dsub_faq_reset")
    async def cb_faq_reset(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await asyncio.to_thread(db.set_setting, "dsub_faq", "")
        text, markup = await _faq_view("✅ سوالات به پیش‌فرض برگشت.")
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer("ذخیره شد.")

    # ------------------------------------------------------------------ برنامه‌ها
    @router.callback_query(F.data.startswith("adm_dsub_pl:"))
    async def cb_platform(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        plat = call.data.split(":", 1)[1]
        if plat not in ds.PLATFORMS:
            return await call.answer()
        text, markup = await _platform_view(plat)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    async def _app_name(plat, idx):
        s = await asyncio.to_thread(ds.all_settings, db)
        names = ds.all_app_names(s, plat)
        return (names[idx] if 0 <= idx < len(names) else None), s

    @router.callback_query(F.data.startswith("adm_dsub_ah:"))
    async def cb_app_hide(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, plat, raw = call.data.split(":")
            idx = int(raw)
        except ValueError:
            return await call.answer()
        if plat not in ds.PLATFORMS:
            return await call.answer()
        name, s = await _app_name(plat, idx)
        if not name:
            return await call.answer()
        pairs = ds._pairs(s["dsub_apps_hidden"])
        pair = (plat, name.lower())
        pairs.symmetric_difference_update({pair})
        await asyncio.to_thread(db.set_setting, "dsub_apps_hidden", ",".join(f"{p}:{n}" for p, n in sorted(pairs)))
        text, markup = await _platform_view(plat)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer("ذخیره شد.")

    @router.callback_query(F.data.startswith("adm_dsub_ar:"))
    async def cb_app_rec(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        try:
            _, plat, raw = call.data.split(":")
            idx = int(raw)
        except ValueError:
            return await call.answer()
        if plat not in ds.PLATFORMS:
            return await call.answer()
        name, s = await _app_name(plat, idx)
        if not name:
            return await call.answer()
        rec = {p: n for p, n in ds._pairs(s["dsub_apps_rec"])}
        hidden = ds._pairs(s["dsub_apps_hidden"])
        hidden.discard((plat, name.lower()))  # برنامه‌ی پیشنهادی نباید مخفی باشد
        rec[plat] = name.lower()
        await asyncio.to_thread(db.set_setting, "dsub_apps_hidden", ",".join(f"{p}:{n}" for p, n in sorted(hidden)))
        await asyncio.to_thread(db.set_setting, "dsub_apps_rec", ",".join(f"{p}:{n}" for p, n in sorted(rec.items())))
        text, markup = await _platform_view(plat, f"⭐ {_e(name)} برنامه‌ی پیشنهادی {ds.PLATFORM_LABELS[plat]} شد.")
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer("ذخیره شد.")

    @router.callback_query(F.data == "adm_dsub_ca_clear")
    async def cb_custom_clear(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await asyncio.to_thread(db.set_setting, "dsub_custom_apps", "")
        text, markup = await _apps_view("🗑 برنامه‌های سفارشی حذف شدند.")
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer("ذخیره شد.")

    # ------------------------------------------------------------------ ورودی متنی
    @router.callback_query(F.data.startswith("adm_dsub_set:"))
    async def cb_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        key = call.data.split(":", 1)[1]
        if key not in FIELDS:
            return await call.answer()
        title, hint, _max, kind = FIELDS[key]
        cur = await _get(key)
        await state.set_state(AdminDSubInput.waiting_value)
        await state.update_data(ds_key=key)
        text = (f"{title}\n\n{hint}\n\nمقدار فعلی:\n{_e(cur) or '— (خالی)'}\n\n"
                "مقدار جدید را بفرست. برای خالی کردن (یا برگشت به پیش‌فرض) فقط «-» بفرست.")
        await replace_admin_view(call, text, reply_markup=_kb([[_btn("❌ انصراف", "adm_dsub")]]))
        await call.answer()

    @router.callback_query(F.data == "adm_dsub_ca_add")
    async def cb_custom_add(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminDSubInput.waiting_app)
        text = (
            "➕ افزودن برنامه‌ی سفارشی\n\n"
            "هر برنامه یک خط، با ۵ بخش که با | جدا می‌شوند:\n"
            "سیستم‌عامل | نام | توضیح | پیشوند افزودن | لینک دانلود\n\n"
            "• سیستم‌عامل: ios, android, windows, mac, linux\n"
            "• پیشوند افزودن: deep-link برنامه (آدرس ساب به انتهایش اضافه می‌شود) مثل myapp://add?url= — اگر ندارد «-»\n"
            "• لینک دانلود: https://... — اگر ندارد «-» (یکی از این دو لازم است)\n\n"
            "مثال:\nandroid | MyVPN | کلاینت سبک | myvpn://add?url= | https://example.com/myvpn.apk"
        )
        await replace_admin_view(call, text, reply_markup=_kb([[_btn("❌ انصراف", "adm_dsub_pg:apps")]]))
        await call.answer()

    def _validate(key, raw: str):
        title, _hint, max_len, kind = FIELDS[key]
        raw = (raw or "").strip()
        if raw == "-":
            return "", None
        if len(raw) > max_len:
            return None, f"متن بیش از حد طولانی است (حداکثر {max_len} نویسنده)."
        if kind.startswith("int:"):
            _, lo, hi = kind.split(":")
            try:
                n = int(raw.translate(_DIGITS))
            except ValueError:
                return None, "یک عدد صحیح بفرست."
            if not int(lo) <= n <= int(hi):
                return None, f"عدد باید بین {lo} تا {hi} باشد."
            return str(n), None
        if kind == "https":
            if not raw.lower().startswith("https://") or " " in raw:
                return None, "آدرس باید با https:// شروع شود و فاصله نداشته باشد."
            return raw.rstrip("/") if key == "dsub_base_url" else raw, None
        if kind == "link":
            if not raw.lower().startswith(("https://", "http://", "tg://")) or " " in raw:
                return None, "لینک باید با https:// یا tg:// شروع شود و فاصله نداشته باشد."
            return raw, None
        if kind == "faq":
            items = ds.parse_faq(raw)
            if not items:
                return None, "هیچ موردی با قالب «سوال | جواب» پیدا نشد."
            if len(items) > 10:
                return None, "حداکثر ۱۰ مورد مجاز است."
            return "\n".join(f"{q} | {a}" for q, a in items), None
        return raw, None

    def _return_page(key):
        if key in ("dsub_profile_title", "dsub_update_interval", "dsub_info_line_text", "dsub_expired_text",
                   "dsub_limited_text", "dsub_cache_ttl", "dsub_base_url"):
            return _out_view
        if key == "dsub_faq":
            return _faq_view
        return _look_view

    @router.message(AdminDSubInput.waiting_value)
    async def msg_value(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        data = await state.get_data()
        key = data.get("ds_key")
        if key not in FIELDS:
            await state.clear()
            return
        if (message.text or "").startswith("/"):
            await state.clear()
            return await message.answer("لغو شد.")
        value, err = _validate(key, message.text or "")
        if err:
            return await message.answer(f"⚠️ {err}\nدوباره بفرست یا /admin را بزن.")
        await asyncio.to_thread(db.set_setting, key, value)
        await state.clear()
        text, markup = await _return_page(key)(f"✅ «{FIELDS[key][0]}» ذخیره شد.")
        await message.answer(text, reply_markup=markup)

    @router.message(AdminDSubInput.waiting_app)
    async def msg_app(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            return
        if (message.text or "").startswith("/"):
            await state.clear()
            return await message.answer("لغو شد.")
        raw = (message.text or "").strip()
        apps, errors = ds.parse_custom_apps(raw)
        if errors or not apps:
            return await message.answer("⚠️ " + "\n".join(errors or ["هیچ برنامه‌ی معتبری پیدا نشد."]) +
                                        "\nدوباره بفرست یا /admin را بزن.")
        existing = await _get("dsub_custom_apps")
        lines = [ln.strip() for ln in existing.splitlines() if ln.strip()]
        for ln in raw.splitlines():
            ln = ln.strip()
            if ln and ln not in lines:
                lines.append(ln)
        if len(lines) > 40:
            return await message.answer("⚠️ حداکثر ۴۰ برنامه‌ی سفارشی مجاز است.")
        await asyncio.to_thread(db.set_setting, "dsub_custom_apps", "\n".join(lines))
        await state.clear()
        text, markup = await _apps_view(f"✅ {len(apps)} برنامه اضافه شد.")
        await message.answer(text, reply_markup=markup)
