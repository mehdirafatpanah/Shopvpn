# -*- coding: utf-8 -*-
"""Localized delivery helpers for background Telegram/Push notifications."""
from __future__ import annotations

from typing import Any

from i18n import tr, normalize_language, set_language, reset_language


def user_language(db, user_id: int) -> str:
    try:
        return normalize_language(db.get_user_language(user_id))
    except Exception:
        return "fa"


def admin_language(db, admin_id: int) -> str:
    try:
        if hasattr(db, "get_web_admin_language"):
            return normalize_language(db.get_web_admin_language(admin_id))
    except Exception:
        pass
    return user_language(db, admin_id)


def localized(text: str, db=None, user_id: int | None = None, language: str | None = None) -> str:
    if language is None and db is not None and user_id is not None:
        language = user_language(db, user_id)
    lang = language or "fa"
    catalog = db.translation_catalog(lang) if db is not None and lang not in {"fa", "en"} else None
    token = set_language(lang, catalog)
    try:
        return tr(text, lang)
    finally:
        reset_language(token)


async def send_telegram(bot: Any, db, chat_id: int, text: str, *, language: str | None = None, **kwargs):
    """Send a system notification in the recipient's persisted language."""
    return await bot.send_message(chat_id, localized(text, db, chat_id, language), **kwargs)


def localized_payload(db, admin_id: int, payload: dict) -> dict:
    """Translate a push payload for one admin without mutating the original."""
    lang = admin_language(db, admin_id)
    catalog = db.translation_catalog(lang) if lang not in {"fa", "en"} else None
    token = set_language(lang, catalog)
    try:
        out = dict(payload)
        if "title" in out:
            out["title"] = tr(str(out["title"]), lang)
        if "body" in out:
            out["body"] = tr(str(out["body"]), lang)
        return out
    finally:
        reset_language(token)
