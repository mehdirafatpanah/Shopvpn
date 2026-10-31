#!/usr/bin/env python3
import hashlib
import hmac
import os
import sys
from pathlib import Path

AUTH_FILE = Path(os.getenv("SHOPVPN_OVPN_AUTH_FILE", "/etc/openvpn/server/shopvpn/auth-users"))


def main() -> int:
    if len(sys.argv) != 2:
        return 1
    try:
        raw = Path(sys.argv[1]).read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError:
        return 1
    if len(raw) < 2:
        return 1
    username, password = raw[0].strip(), raw[1]
    if not username or not password or len(username) > 64 or len(password) > 256:
        return 1
    try:
        entries = AUTH_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 1
    stored = None
    for line in entries:
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0] == username:
            stored = parts[1].strip()
            break
    if not stored.startswith("scrypt$"):
        return 1
    try:
        _, n_s, r_s, p_s, salt_hex, digest_hex = stored.split("$", 5)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=int(n_s), r=int(r_s), p=int(p_s), dklen=len(bytes.fromhex(digest_hex)))
        return 0 if hmac.compare_digest(digest.hex(), digest_hex) else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
