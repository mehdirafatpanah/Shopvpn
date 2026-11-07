# -*- coding: utf-8 -*-
"""Per-panel account naming modes for auto-provisioned configs."""

import hashlib
import random
import re
import string

MODE_LEGACY = ""

MODES = {
    "user_name": ("نام دلخواه کاربر", True, False, False),
    "hash_user_name": ("هش آیدی عددی + نام دلخواه کاربر", True, False, False),
    "prefix_user_name": ("پیشوند + نام دلخواه کاربر", True, True, False),
    "user_name_suffix": ("نام دلخواه کاربر + پسوند", True, False, True),
    "counter_user_name": ("شمارنده + نام دلخواه کاربر", True, False, False),
    "prefix_counter": ("پیشوند + شمارنده", False, True, False),
    "counter_suffix": ("شمارنده + پسوند", False, False, True),
    "tgid_counter": ("آیدی عددی تلگرام + شمارنده", False, False, False),
}

MODE_ORDER = tuple(MODES)
AFFIX_MAX_LEN = 12
USERNAME_MAX_LEN = 32
COUNTER_WIDTH = 3
JOINER = "_"
_AFFIX_RE = re.compile(r"[A-Za-z0-9_]{1,%d}" % AFFIX_MAX_LEN)


def mode_label(mode: str) -> str:
    if mode in MODES:
        return MODES[mode][0]
    return "پیش‌فرض (روش قبلی)"


def server_mode(server) -> str:
    if server is None:
        return MODE_LEGACY
    try:
        mode = (server["naming_mode"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return MODE_LEGACY
    return mode if mode in MODES else MODE_LEGACY


def server_affix(server, kind: str) -> str:
    try:
        return (server["naming_" + kind] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


def is_active(server) -> bool:
    return server_mode(server) != MODE_LEGACY


def needs_user_name(server) -> bool:
    mode = server_mode(server)
    if mode == MODE_LEGACY:
        return True
    return MODES[mode][1]


def needs_counter(server) -> bool:
    return server_mode(server) in ("counter_user_name", "prefix_counter", "counter_suffix", "tgid_counter")


def needs_prefix(mode: str) -> bool:
    return mode in MODES and MODES[mode][2]


def needs_suffix(mode: str) -> bool:
    return mode in MODES and MODES[mode][3]


def valid_affix(text: str) -> bool:
    return bool(_AFFIX_RE.fullmatch(text or ""))


def missing_affix(mode: str, server) -> str:
    if needs_prefix(mode) and not server_affix(server, "prefix"):
        return "prefix"
    if needs_suffix(mode) and not server_affix(server, "suffix"):
        return "suffix"
    return ""


def user_hash(tg_id) -> str:
    return hashlib.sha256(str(int(tg_id or 0)).encode()).hexdigest()[:6]


def _clean(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", text or "")


def _random_tail(length: int = 4) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _join(*parts) -> str:
    return JOINER.join(p for p in parts if p)


def _fit(name: str, reserve: int = 0) -> str:
    return name[: max(USERNAME_MAX_LEN - reserve, 3)]


def build_username(db, server, tg_id, user_name: str = "", unit_index: int = 0, quantity: int = 1) -> str:
    """Compose one panel username from the server's naming mode. Returns '' for the legacy mode."""
    mode = server_mode(server)
    if mode == MODE_LEGACY:
        return ""
    prefix = _clean(server_affix(server, "prefix"))
    suffix = _clean(server_affix(server, "suffix"))
    name = _clean(user_name)
    if quantity and quantity > 1 and name:
        name = f"{name}{JOINER}{unit_index + 1}"
    needs_name = MODES[mode][1]
    if needs_name and not name:
        name = "u" + _random_tail(8)

    def counter() -> str:
        return str(db.next_panel_naming_counter(int(server["id"]))).zfill(COUNTER_WIDTH)

    if mode == "user_name":
        result = name
    elif mode == "hash_user_name":
        result = _join(user_hash(tg_id), name)
    elif mode == "prefix_user_name":
        result = _join(prefix, name)
    elif mode == "user_name_suffix":
        result = _join(name, suffix)
    elif mode == "counter_user_name":
        result = _join(counter(), name)
    elif mode == "prefix_counter":
        result = _join(prefix, counter())
    elif mode == "counter_suffix":
        result = _join(counter(), suffix)
    else:
        result = _join(str(int(tg_id or 0)), counter())
    return _fit(result)


def collision_variant(name: str) -> str:
    return _fit(name, reserve=4) + JOINER + _random_tail(3)


def preview(server, mode: str, user_name: str = "myname", tg_id: int = 123456789) -> str:
    prefix = _clean(server_affix(server, "prefix")) or "pre"
    suffix = _clean(server_affix(server, "suffix")) or "suf"
    counter = "1".zfill(COUNTER_WIDTH)
    samples = {
        "user_name": user_name,
        "hash_user_name": _join(user_hash(tg_id), user_name),
        "prefix_user_name": _join(prefix, user_name),
        "user_name_suffix": _join(user_name, suffix),
        "counter_user_name": _join(counter, user_name),
        "prefix_counter": _join(prefix, counter),
        "counter_suffix": _join(counter, suffix),
        "tgid_counter": _join(str(tg_id), counter),
    }
    return samples.get(mode, "")
