# -*- coding: utf-8 -*-
"""زمینه‌ی «کدام بات/دیتابیس» برای ماژول‌هایی که قبلاً فقط یک وضعیت سراسری داشتند.

یوزربات و اسکنر نشت قبلاً فقط برای بات اصلی بودند (یک فایل سشن و یک STATE سراسری).
حالا هر نمایندگی کامل نسخه‌ی مستقل خودش را دارد: سشن جدا (کنار فایل دیتابیس خودش)،
STATE جدا و دیتابیس جدا. بات اصلی (CURRENT=None) دقیقاً مثل قبل کار می‌کند.
"""

import contextvars
import os
from collections.abc import MutableMapping

CURRENT = contextvars.ContextVar("shopvpn_tenant_db", default=None)


def key_for(db):
    """None برای بات اصلی؛ مسیر مطلق دیتابیس برای نمایندگی کامل."""
    try:
        from config import DB_PATH
        main = os.path.abspath(DB_PATH)
    except Exception:
        main = None
    path = os.path.abspath(getattr(db, "db_path", "") or "")
    if not path or path == main:
        return None
    return path


def use(db):
    """زمینه‌ی فعلی تسک/هندلر را روی این دیتابیس می‌گذارد و token را برمی‌گرداند."""
    return CURRENT.set(key_for(db))


def current_key():
    return CURRENT.get()


def session_file(kind: str, main_path: str) -> str:
    """مسیر فایل سشن؛ بات اصلی همان مسیر قدیمی، نماینده کنار دیتابیس خودش."""
    key = CURRENT.get()
    if key is None:
        return main_path
    return f"{key}.{kind}_session.json"


class PerTenant(MutableMapping):
    """دیکشنری‌ای که بسته به زمینه‌ی فعلی، نسخه‌ی مخصوص همان بات را برمی‌گرداند."""

    def __init__(self, factory):
        self._factory = factory
        self._data = {}

    def _cur(self):
        key = CURRENT.get()
        if key not in self._data:
            self._data[key] = self._factory()
        return self._data[key]

    def __getitem__(self, k):
        return self._cur()[k]

    def __setitem__(self, k, v):
        self._cur()[k] = v

    def __delitem__(self, k):
        del self._cur()[k]

    def __iter__(self):
        return iter(self._cur())

    def __len__(self):
        return len(self._cur())

    def __repr__(self):
        return repr(self._cur())


def middleware(db):
    """میدلویر aiogram: زمینه را برای هر آپدیتِ این روتر روی دیتابیس همین بات می‌گذارد."""
    async def _mw(handler, event, data):
        token = use(db)
        try:
            return await handler(event, data)
        finally:
            CURRENT.reset(token)
    return _mw
