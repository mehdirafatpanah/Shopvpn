# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
هش کردن پسورد و ساخت/بررسی توکن نشست (session) پنل وب مستقل.
عمداً بدون هیچ وابستگی خارجی (فقط hashlib/hmac استاندارد پایتون) تا نیازی
به نصب پکیج اضافه روی سرور کاربر نباشد.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from urllib.parse import quote

PBKDF2_ITERATIONS = 260_000
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(dk.hex(), hash_hex)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(secret_key: str, admin_id: int, username: str, role: str, hours: int = 12,
                          tenant: str = "") -> str:
    now = int(time.time())
    payload = {
        "id": admin_id,
        "u": username,
        "r": role,
        "b": tenant,  # شناسه/اسلاگ تننت (نماینده)؛ خالی یعنی بات اصلی. منبع اعتبار تننت همین payload است نه پارامتر URL.‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
        "la": now,
        "exp": now + hours * 3600,
    }
    return _sign_payload(secret_key, payload)


def _sign_payload(secret_key: str, payload: dict) -> str:
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def refresh_session_token(secret_key: str, payload: dict, last_active: int = 0) -> str:
    """Re-sign a verified payload with a new last-activity stamp; the absolute exp is unchanged."""
    fresh = dict(payload)
    fresh["la"] = int(last_active or time.time())
    return _sign_payload(secret_key, fresh)


def session_idle_seconds(payload: dict) -> int:
    la = payload.get("la")
    if la is None:
        return 0
    return max(0, int(time.time()) - int(la))


def verify_session_token(secret_key: str, token: str):
    """توکن معتبر را به‌صورت dict برمی‌گرداند؛ در غیر این صورت None."""
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected_sig = hmac.new(secret_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig.encode("utf-8"), sig.encode("utf-8")):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


TOTP_STEP = 30
TOTP_DIGITS = 6
BACKUP_CODE_COUNT = 8


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** TOTP_DIGITS)
    return str(code).zfill(TOTP_DIGITS)


def verify_totp(secret: str, code: str, last_step: int = 0, window: int = 1):
    """Return the matched time step (int) or None. Steps <= last_step are rejected to block replay."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != TOTP_DIGITS or not secret:
        return None
    current = int(time.time()) // TOTP_STEP
    for step in range(current - window, current + window + 1):
        if step <= int(last_step or 0):
            continue
        try:
            expected = _hotp(secret, step)
        except Exception:
            return None
        if hmac.compare_digest(expected, code):
            return step
    return None


def totp_uri(secret: str, account: str, issuer: str = "ShopVPN") -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP}"


def generate_backup_codes(count: int = BACKUP_CODE_COUNT):
    """Return (plain_codes, hashed_codes)."""
    plain = []
    for _ in range(count):
        raw = secrets.token_hex(5)
        plain.append(f"{raw[:5]}-{raw[5:]}")
    return plain, [hash_backup_code(c) for c in plain]


def hash_backup_code(code: str) -> str:
    norm = "".join(ch for ch in str(code or "").lower() if ch.isalnum())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
