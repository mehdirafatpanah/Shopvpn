# -*- coding: utf-8 -*-
"""ورود/خروج اکانت تلگرام یوزربات و اسکنر نشت از داخل بات (مخصوص نمایندگی کامل).

بات اصلی هنوز از منوی سرور (python userbot.py login) وارد می‌شود؛ اما نماینده‌ی کامل
به سرور دسترسی ندارد، پس سشن مستقل خودش را از همین‌جا می‌سازد.
مراحل: api_id → api_hash → شماره → کد (با فاصله بین رقم‌ها) → رمز دومرحله‌ای (در صورت نیاز).
"""

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import tenant_ctx
import userbot
from i18n import tr

logger = logging.getLogger(__name__)

KINDS = {"ub": "userbot", "leak": "scanner"}
_PENDING = {}   # (tenant key, admin id) -> {"client", "hash", "api_id", "api_hash", "phone", "kind"}


class UbLogin(StatesGroup):
    api_id = State()
    api_hash = State()
    phone = State()
    code = State()
    password = State()


def login_buttons(kind: str, logged_in: bool):
    """دکمه‌های ورود/خروج برای منوهای یوزربات و نشت؛ فقط برای نمایندگی کامل."""
    if tenant_ctx.current_key() is None:
        return []
    if logged_in:
        return [[InlineKeyboardButton(text=tr("🚪 خروج از اکانت تلگرام"), callback_data=f"ubl:out:{kind}")]]
    return [[InlineKeyboardButton(text=tr("🔑 ورود به اکانت تلگرام"), callback_data=f"ubl:start:{kind}")]]


def _path(kind: str) -> str:
    return userbot.session_path() if kind == "ub" else userbot.scanner_session_path()


def _back(kind: str) -> str:
    return "adm_userbot" if kind == "ub" else "adm_leak"


def _cancel_kb(kind: str):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("❌ انصراف"), callback_data=f"ubl:cancel:{kind}")]])


async def _drop(key):
    pending = _PENDING.pop(key, None)
    if pending and pending.get("client"):
        try:
            await pending["client"].disconnect()
        except Exception:
            pass


def create_login_router(db) -> Router:
    router = Router()
    router.message.outer_middleware(tenant_ctx.middleware(db))
    router.callback_query.outer_middleware(tenant_ctx.middleware(db))

    def _key(uid: int):
        return (tenant_ctx.current_key(), uid)

    def _allowed(uid: int) -> bool:
        return tenant_ctx.current_key() is not None and db.is_full_admin(uid)

    async def _wipe(message: Message):
        try:
            await message.delete()
        except Exception:
            pass

    @router.callback_query(F.data.startswith("ubl:start:"))
    async def cb_start(call: CallbackQuery, state: FSMContext):
        if not _allowed(call.from_user.id):
            return await call.answer(tr("⛔️ این بخش فقط برای مدیران کامل در دسترس است."), show_alert=True)
        kind = call.data.split(":")[2]
        if kind not in KINDS:
            return await call.answer()
        await _drop(_key(call.from_user.id))
        await state.clear()
        await state.update_data(kind=kind)
        await state.set_state(UbLogin.api_id)
        await call.message.answer(
            tr("🔑 ورود به اکانت تلگرام") + "\n\n"
            + tr("اول api_id و api_hash اکانت را از my.telegram.org بگیرید (بخش API development tools).") + "\n\n"
            + tr("api_id (فقط عدد) را بفرستید:"),
            reply_markup=_cancel_kb(kind),
        )
        await call.answer()

    @router.callback_query(F.data.startswith("ubl:cancel:"))
    async def cb_cancel(call: CallbackQuery, state: FSMContext):
        await _drop(_key(call.from_user.id))
        await state.clear()
        await call.message.answer(tr("انصراف داده شد."))
        await call.answer()

    @router.message(StateFilter(UbLogin.api_id))
    async def st_api_id(message: Message, state: FSMContext):
        if not _allowed(message.from_user.id):
            return
        raw = (message.text or "").strip()
        if not raw.isdigit():
            return await message.answer(tr("api_id باید فقط عدد باشد. دوباره بفرستید:"))
        await state.update_data(api_id=int(raw))
        await state.set_state(UbLogin.api_hash)
        await message.answer(tr("api_hash را بفرستید:"))

    @router.message(StateFilter(UbLogin.api_hash))
    async def st_api_hash(message: Message, state: FSMContext):
        if not _allowed(message.from_user.id):
            return
        raw = (message.text or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", raw):
            return await message.answer(tr("api_hash معتبر نیست (۳۲ کاراکتر). دوباره بفرستید:"))
        await _wipe(message)
        await state.update_data(api_hash=raw)
        await state.set_state(UbLogin.phone)
        await message.answer(tr("شماره‌ی اکانت را با کد کشور بفرستید (مثلاً +98912...):"))

    @router.message(StateFilter(UbLogin.phone))
    async def st_phone(message: Message, state: FSMContext):
        if not _allowed(message.from_user.id):
            return
        phone = re.sub(r"[\s\-()]", "", message.text or "")
        if not re.fullmatch(r"\+\d{8,15}", phone):
            return await message.answer(tr("شماره معتبر نیست؛ با + و کد کشور بفرستید:"))
        data = await state.get_data()
        try:
            from telethon import TelegramClient
            from telethon.errors import FloodWaitError, PhoneNumberInvalidError
            from telethon.sessions import StringSession
        except ImportError:
            await state.clear()
            return await message.answer(tr("telethon روی سرور نصب نیست."))
        client = TelegramClient(StringSession(), data["api_id"], data["api_hash"])
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            await client.disconnect()
            return await message.answer(tr("شماره نامعتبر است. دوباره بفرستید:"))
        except FloodWaitError as exc:
            await client.disconnect()
            await state.clear()
            return await message.answer(tr("تعداد تلاش زیاد است. بعد از") + f" {exc.seconds} " + tr("ثانیه دوباره امتحان کنید."))
        except Exception as exc:
            await client.disconnect()
            await state.clear()
            logger.warning("userbot web login failed: %s", exc)
            return await message.answer(tr("اتصال یا api_id/api_hash مشکل دارد؛ از ابتدا شروع کنید."))
        _PENDING[_key(message.from_user.id)] = {
            "client": client, "hash": sent.phone_code_hash, "phone": phone,
            "api_id": data["api_id"], "api_hash": data["api_hash"], "kind": data["kind"], "tries": 0,
        }
        await state.set_state(UbLogin.code)
        await message.answer(
            tr("کد ورود داخل تلگرام (یا پیامک) فرستاده شد.") + "\n"
            + tr("⚠️ رقم‌های کد را با فاصله یا خط‌تیره از هم جدا بفرستید (مثلاً 1 2 3 4 5)؛ اگر کد را یکجا بفرستید تلگرام آن را باطل می‌کند."),
            reply_markup=_cancel_kb(data["kind"]),
        )

    async def _finish(message: Message, state: FSMContext, pending: dict):
        client = pending["client"]
        try:
            me = await client.get_me()
            userbot.save_session(
                pending["api_id"], pending["api_hash"], client.session.save(),
                {"id": me.id, "first_name": me.first_name or "", "username": me.username or "", "phone": me.phone or pending["phone"]},
                _path(pending["kind"]),
            )
        finally:
            await client.disconnect()
            _PENDING.pop(_key(message.from_user.id), None)
            await state.clear()
        await message.answer(
            tr("✅ ورود انجام شد.") + f" {me.first_name or ''} (@{me.username or '-'})\n"
            + tr("بدون ری‌استارت فعال می‌شود."),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=_back(pending["kind"]))]]),
        )

    @router.message(StateFilter(UbLogin.code))
    async def st_code(message: Message, state: FSMContext):
        if not _allowed(message.from_user.id):
            return
        pending = _PENDING.get(_key(message.from_user.id))
        if not pending:
            await state.clear()
            return await message.answer(tr("نشست ورود منقضی شد؛ از ابتدا شروع کنید."))
        await _wipe(message)
        code = re.sub(r"\D", "", message.text or "")
        from telethon.errors import (
            PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError,
        )
        try:
            await pending["client"].sign_in(phone=pending["phone"], code=code, phone_code_hash=pending["hash"])
        except SessionPasswordNeededError:
            await state.set_state(UbLogin.password)
            return await message.answer(tr("رمز تأیید دومرحله‌ای را بفرستید:"))
        except PhoneCodeInvalidError:
            pending["tries"] += 1
            if pending["tries"] >= 3:
                await _drop(_key(message.from_user.id))
                await state.clear()
                return await message.answer(tr("کد چند بار اشتباه بود؛ از ابتدا شروع کنید."))
            return await message.answer(tr("کد اشتباه است. دوباره بفرستید (با فاصله بین رقم‌ها):"))
        except PhoneCodeExpiredError:
            await _drop(_key(message.from_user.id))
            await state.clear()
            return await message.answer(tr("کد منقضی شد؛ از ابتدا شروع کنید."))
        await _finish(message, state, pending)

    @router.message(StateFilter(UbLogin.password))
    async def st_password(message: Message, state: FSMContext):
        if not _allowed(message.from_user.id):
            return
        pending = _PENDING.get(_key(message.from_user.id))
        if not pending:
            await state.clear()
            return await message.answer(tr("نشست ورود منقضی شد؛ از ابتدا شروع کنید."))
        from telethon.errors import PasswordHashInvalidError
        password = message.text or ""
        await _wipe(message)
        try:
            await pending["client"].sign_in(password=password)
        except PasswordHashInvalidError:
            pending["tries"] += 1
            if pending["tries"] >= 3:
                await _drop(_key(message.from_user.id))
                await state.clear()
                return await message.answer(tr("رمز چند بار اشتباه بود؛ از ابتدا شروع کنید."))
            return await message.answer(tr("رمز اشتباه است. دوباره بفرستید:"))
        await _finish(message, state, pending)

    @router.callback_query(F.data.startswith("ubl:out:"))
    async def cb_logout(call: CallbackQuery):
        if not _allowed(call.from_user.id):
            return await call.answer(tr("⛔️ این بخش فقط برای مدیران کامل در دسترس است."), show_alert=True)
        kind = call.data.split(":")[2]
        if kind not in KINDS:
            return await call.answer()
        await userbot.logout(_path(kind))
        await call.message.answer(
            tr("از اکانت خارج شدید."),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=_back(kind))]]),
        )
        await call.answer()

    return router
