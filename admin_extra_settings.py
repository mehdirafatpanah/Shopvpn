# -*- coding: utf-8 -*-
"""
ویرایش «تنظیمات تکمیلی» داخل ادمین بات.

گروه‌هایی از extra_settings_schema که "bot": True دارند اینجا به‌صورت منوی دکمه‌ای
نمایش داده می‌شوند (همان تعریف، همان اعتبارسنجی و همان پیش‌فرض‌هایی که وب و مینی‌اپ دارند).
فیلد جدید در آن گروه‌ها خودکار در بات هم ظاهر می‌شود.
"""

import asyncio
import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import bot_profile
import extra_settings_schema as xs
import keyboards as kb
from i18n import tr

SURFACE = "bot"
ENTRY_CB = "adm_xs"
_BTN_LIMIT = 44


class AdminExtraSetting(StatesGroup):
    waiting_value = State()


def _btn(text, cb):
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _short(text, n=_BTN_LIMIT):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _groups():
    return xs.groups_for(SURFACE)


def _group(gid):
    for g in _groups():
        if g["id"] == gid:
            return g
    return None


def _field(group, idx):
    try:
        return group["fields"][int(idx)]
    except (ValueError, IndexError, TypeError):
        return None


def _current(db, field):
    raw = db.get_setting(field["key"], field["default"])
    return field["default"] if raw is None else str(raw)


def _preview(db, field, limit=60):
    cur = _current(db, field)
    t = field["type"]
    if t == "password":
        return "••••" if cur.strip() else "—"
    if t == "bool":
        return "🟢 روشن" if cur.strip() == "1" else "🔴 خاموش"
    if t == "select":
        for value, label in field.get("options", []):
            if value == cur:
                return label
        return cur
    cur = " ".join(cur.split())
    if not cur:
        return "—"
    return cur if len(cur) <= limit else cur[: limit - 1] + "…"


def _bounds(field):
    if field["type"] != "number":
        return ""
    if "min" in field and "max" in field:
        return f" (بین {field['min']} تا {field['max']})"
    if "min" in field:
        return f" (حداقل {field['min']})"
    if "max" in field:
        return f" (حداکثر {field['max']})"
    return ""


def register(router: Router, db, senior_admin_only, deny_mid, replace_admin_view):

    def _groups_view():
        rows = [
            [_btn(tr(g["title"]), f"adm_xs_g:{g['id']}")]
            for g in _groups()
            if not g.get("bot_hidden_in_list") and g["id"] not in kb.ADMIN_XS_GROUP_ITEMS
        ]
        rows.append([_btn(tr("⬅️ بازگشت"), "adm_cat:management")])
        text = tr("🧩 تنظیمات تکمیلی\n\nیک گروه را انتخاب کن. همین گزینه‌ها در مینی‌اپ هم هستند.")
        return text, _kb(rows)

    def _group_view(group, note=""):
        lines = [note, ""] if note else []
        lines.append(tr(group["title"]))
        lines.append("")
        rows = []
        for i, f in enumerate(group["fields"]):
            lines.append(f"• {tr(f['label'])}: {html.escape(_preview(db, f))}")
            if f["type"] == "bool":
                on = _current(db, f).strip() == "1"
                rows.append([_btn(("✅ " if on else "⬜ ") + _short(tr(f["label"])), f"adm_xs_t:{group['id']}:{i}")])
            else:
                rows.append([_btn("✏️ " + _short(tr(f["label"])), f"adm_xs_e:{group['id']}:{i}")])
        mapped_item = kb.ADMIN_XS_GROUP_ITEMS.get(group["id"])
        hub = kb.admin_hub_of_item(db, mapped_item) if mapped_item else None
        back = group.get("bot_back") or (f"adm_cat:{hub}" if hub else ENTRY_CB)
        rows.append([_btn(tr("⬅️ بازگشت"), back)])
        return "\n".join(lines), _kb(rows)

    async def _log(user_id, key, detail):
        try:
            await asyncio.to_thread(db.log_admin_action, user_id, "setting_change", f"{key}: {detail} (بات)", "setting", key)
        except Exception:
            pass

    async def _save(user_id, key, value, detail, bot=None):
        changed = await asyncio.to_thread(xs.save_values, db, SURFACE, {key: value})
        await _log(user_id, key, detail)
        if bot is not None and bot_profile.has_profile_keys(changed):
            res = await bot_profile.apply_profile(bot.token, db)
            return res
        return None

    @router.callback_query(F.data == ENTRY_CB)
    async def cb_xs_menu(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        text, markup = _groups_view()
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_xs_g:"))
    async def cb_xs_group(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        group = _group(call.data.split(":", 1)[1])
        if not group:
            return await call.answer()
        await state.clear()
        text, markup = await asyncio.to_thread(_group_view, group)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_xs_t:"))
    async def cb_xs_toggle(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, gid, idx = call.data.split(":", 2)
        group = _group(gid)
        field = _field(group, idx) if group else None
        if not field or field["type"] != "bool":
            return await call.answer()
        new = "0" if _current(db, field).strip() == "1" else "1"
        try:
            await _save(call.from_user.id, field["key"], new, "روشن" if new == "1" else "خاموش")
        except xs.SettingsValidationError as e:
            return await call.answer(str(e), show_alert=True)
        text, markup = await asyncio.to_thread(_group_view, group)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    @router.callback_query(F.data.startswith("adm_xs_e:"))
    async def cb_xs_edit(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, gid, idx = call.data.split(":", 2)
        group = _group(gid)
        field = _field(group, idx) if group else None
        if not field or field["type"] == "bool":
            return await call.answer()
        back = f"adm_xs_g:{gid}"
        head = f"{tr(field['label'])}{_bounds(field)}"
        if field.get("hint"):
            head += f"\n{tr(field['hint'])}"
        if field["type"] == "select":
            rows = [[_btn(tr(label), f"adm_xs_s:{gid}:{idx}:{oi}")] for oi, (_, label) in enumerate(field["options"])]
            rows.append([_btn(tr("⬅️ بازگشت"), back)])
            await state.clear()
            await replace_admin_view(call, f"{head}\n\nمقدار فعلی: {html.escape(_preview(db, field))}", reply_markup=_kb(rows))
            return await call.answer()
        await state.set_state(AdminExtraSetting.waiting_value)
        await state.update_data(xs_gid=gid, xs_idx=idx)
        if field["type"] == "password":
            shown = "••••" if _current(db, field).strip() else "—"
            prompt = f"{head}\n\nمقدار فعلی: {shown}\nمقدار جدید را بفرستید (پیام شما بعد از ثبت حذف می‌شود):"
        else:
            cur = _current(db, field)
            cur = cur if len(cur) <= 800 else cur[:800] + "…"
            prompt = f"{head}\n\nمقدار فعلی:\n{html.escape(cur) or '—'}\n\nمقدار جدید را بفرستید:"
        rows = []
        if field["type"] != "password" and field.get("default", "") != "":
            rows.append([_btn(tr("↩️ بازگشت به پیش‌فرض"), f"adm_xs_d:{gid}:{idx}")])
        rows.append([_btn(tr("⬅️ بازگشت"), back)])
        await replace_admin_view(call, prompt, reply_markup=_kb(rows))
        await call.answer()

    @router.callback_query(F.data.startswith("adm_xs_s:"))
    async def cb_xs_select(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, gid, idx, oi = call.data.split(":", 3)
        group = _group(gid)
        field = _field(group, idx) if group else None
        if not field or field["type"] != "select":
            return await call.answer()
        try:
            value = field["options"][int(oi)][0]
            await _save(call.from_user.id, field["key"], value, value)
        except (ValueError, IndexError):
            return await call.answer()
        except xs.SettingsValidationError as e:
            return await call.answer(str(e), show_alert=True)
        text, markup = await asyncio.to_thread(_group_view, group)
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    @router.callback_query(F.data.startswith("adm_xs_d:"))
    async def cb_xs_default(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        _, gid, idx = call.data.split(":", 2)
        group = _group(gid)
        field = _field(group, idx) if group else None
        if not field:
            return await call.answer()
        try:
            await _save(call.from_user.id, field["key"], field["default"], "بازگشت به پیش‌فرض")
        except xs.SettingsValidationError as e:
            return await call.answer(str(e), show_alert=True)
        await state.clear()
        text, markup = await asyncio.to_thread(_group_view, group, tr("✅ به پیش‌فرض برگشت."))
        await replace_admin_view(call, text, reply_markup=markup)
        await call.answer(tr("ذخیره شد."))

    @router.message(AdminExtraSetting.waiting_value)
    async def process_xs_value(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            await state.clear()
            return
        data = await state.get_data()
        group = _group(data.get("xs_gid"))
        field = _field(group, data.get("xs_idx")) if group else None
        if not field:
            await state.clear()
            return await message.answer(tr("این گزینه دیگر وجود ندارد."))
        if field["type"] == "textarea" and not field.get("plain"):
            # html_text تا قالب‌بندی و ایموجی‌های پریمیوم حفظ شود (همان رفتار «ویرایش پیام خوش‌آمد»).
            value = message.html_text or ""
        else:
            value = (message.text or "").strip()
        secret = field["type"] == "password"
        try:
            prof = await _save(message.from_user.id, field["key"], value,
                               "••••" if secret else f"{len(value)} کاراکتر", bot=message.bot)
        except xs.SettingsValidationError as e:
            return await message.answer(str(e))
        if secret:
            try:
                await message.delete()
            except Exception:
                pass
        await state.clear()
        note = tr("✅ ذخیره شد.")
        if prof is not None:
            note += "\n" + (tr("✅ روی تلگرام اعمال شد.") if prof["ok"]
                            else tr("⚠️ ذخیره شد ولی اعمال روی تلگرام ناموفق بود:") + " " + html.escape("; ".join(prof["errors"].values())))
        text, markup = await asyncio.to_thread(_group_view, group, note)
        await message.answer(text, reply_markup=markup)
