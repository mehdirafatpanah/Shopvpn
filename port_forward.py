# -*- coding: utf-8 -*-
"""قوانین socat و فوروارد پورت برای آدرس‌های عمومی (ساب مرکزی، ساب‌های اختصاصی، وب‌شاپ، پنل وب).

هر قانون روی همین سرور (local) یا روی یک سرور رله از طریق SSH اجرا می‌شود و با یک سرویس systemd ماندگار است.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import secrets
import shlex
import time

SETTING_KEY = "port_forward_rules"
SUB_CENTRAL = "sub_central"
METHODS = ("socat", "iptables")
PROTOS = ("tcp", "udp")
RUN_ON = ("local", "ssh")
ACTIONS = ("apply", "remove", "status", "delete")
FIELD_LIMIT = 120

_DNS_RE = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")
_USER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}")
_ID_RE = re.compile(r"[0-9a-f]{8}")
_LOOPBACK = {"127.0.0.1", "localhost", "0.0.0.0"}


class PortForwardError(Exception):
    pass


def _ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


def valid_host(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 253:
        raise PortForwardError("آدرس مقصد معتبر نیست.")
    if _ipv4(value):
        return value
    if ":" in value or not _DNS_RE.fullmatch(value):
        raise PortForwardError("آدرس باید IPv4 یا نام دامنه معتبر باشد (IPv6 پشتیبانی نمی‌شود).")
    return value.lower()


def valid_port(value, label: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise PortForwardError(f"{label} معتبر نیست.")
    if not 1 <= port <= 65535:
        raise PortForwardError(f"{label} باید بین ۱ تا ۶۵۵۳۵ باشد.")
    return port


def _load(db) -> list:
    try:
        data = json.loads(db.get_setting(SETTING_KEY, "[]") or "[]")
    except (ValueError, TypeError):
        return []
    return [r for r in data if isinstance(r, dict) and _ID_RE.fullmatch(str(r.get("id", "")))]


def _save(db, rules: list) -> None:
    db.set_setting(SETTING_KEY, json.dumps(rules, ensure_ascii=False))


def targets(db) -> list:
    import dedicated_sub as ds
    out = [{"key": SUB_CENTRAL, "label": "ساب مرکزی", "url": ds.base_url(db)}]
    for prof in ds.list_profiles(db):
        out.append({"key": f"sub:{prof['id']}", "label": f"ساب اختصاصی «{prof['name']}»", "url": prof["base_url"]})
    out.append({"key": "shop", "label": "وب‌شاپ", "url": db.get_setting("web_shop_base_url", "") or ""})
    out.append({"key": "panel", "label": "پنل وب ادمین", "url": db.get_setting("admin_panel_public_url", "") or ""})
    return out


def public(rule: dict) -> dict:
    out = {k: v for k, v in rule.items() if k != "ssh_pass_enc"}
    out["ssh_saved"] = bool(rule.get("ssh_pass_enc"))
    return out


def list_rules(db) -> list:
    return [public(r) for r in _load(db)]


def get_rule(db, rule_id: str) -> dict:
    for rule in _load(db):
        if rule["id"] == rule_id:
            return rule
    raise PortForwardError("قانون پیدا نشد.")


def _location(rule: dict) -> tuple:
    if rule["run_on"] == "ssh":
        return ("ssh", rule["ssh_host"], rule["ssh_port"])
    return ("local",)


_CRITICAL = ("method", "proto", "bind", "listen_port", "run_on", "ssh_host", "ssh_port")


def normalize(db, data: dict, existing: dict | None = None) -> dict:
    base = dict(existing or {})
    merged = {**base, **{k: v for k, v in data.items() if v is not None}}
    keys = {t["key"] for t in targets(db)}
    target = str(merged.get("target") or "")
    if target not in keys:
        raise PortForwardError("آدرس انتخاب‌شده وجود ندارد.")
    method = str(merged.get("method") or "socat").lower()
    proto = str(merged.get("proto") or "tcp").lower()
    run_on = str(merged.get("run_on") or "local").lower()
    if method not in METHODS or proto not in PROTOS or run_on not in RUN_ON:
        raise PortForwardError("روش، پروتکل یا محل اجرا نامعتبر است.")
    bind = str(merged.get("bind") or "0.0.0.0").strip()
    if not _ipv4(bind):
        raise PortForwardError("آدرس شنود باید IPv4 باشد (مثلاً 0.0.0.0).")
    rule = {
        "id": base.get("id") or secrets.token_hex(4),
        "target": target, "method": method, "proto": proto, "bind": bind,
        "listen_port": valid_port(merged.get("listen_port"), "پورت ورودی"),
        "dest_host": valid_host(merged.get("dest_host")),
        "dest_port": valid_port(merged.get("dest_port"), "پورت مقصد"),
        "run_on": run_on,
        "note": str(merged.get("note") or "").strip()[:FIELD_LIMIT],
        "enabled": bool(base.get("enabled", False)),
        "status": base.get("status") or "new",
        "last_error": base.get("last_error") or "",
        "applied_at": base.get("applied_at") or 0,
        "ssh_host": "", "ssh_port": 22, "ssh_user": "root",
    }
    if run_on == "ssh":
        rule["ssh_host"] = valid_host(merged.get("ssh_host"))
        rule["ssh_port"] = valid_port(merged.get("ssh_port") or 22, "پورت SSH")
        user = str(merged.get("ssh_user") or "root").strip()
        if not _USER_RE.fullmatch(user):
            raise PortForwardError("نام کاربری SSH معتبر نیست.")
        rule["ssh_user"] = user
        if rule["listen_port"] == rule["ssh_port"]:
            raise PortForwardError("پورت ورودی نباید با پورت SSH سرور رله یکی باشد.")
    if rule["dest_host"] in _LOOPBACK and rule["dest_port"] == rule["listen_port"] and run_on == "local" \
            and bind in ("0.0.0.0", "127.0.0.1"):
        raise PortForwardError("مقصد همان پورت ورودی است و حلقه می‌سازد.")
    secret_new = str(merged.get("ssh_password") or "")
    save_secret = bool(merged["ssh_save_secret"]) if "ssh_save_secret" in merged else bool(base.get("ssh_pass_enc"))
    enc = base.get("ssh_pass_enc") or ""
    if run_on != "ssh" or not save_secret:
        enc = ""
    elif secret_new:
        from ssh_credentials import encrypt_credential
        enc = encrypt_credential(secret_new)
    if enc:
        rule["ssh_pass_enc"] = enc
    for other in _load(db):
        if other["id"] == rule["id"]:
            continue
        if _location(other) == _location(rule) and other["listen_port"] == rule["listen_port"] \
                and other["proto"] == rule["proto"]:
            raise PortForwardError("برای همین سرور قانونی با همین پورت ورودی و پروتکل از قبل وجود دارد.")
    if existing and existing.get("enabled"):
        if any(existing.get(k) != rule.get(k) for k in _CRITICAL):
            raise PortForwardError("این قانون روی سرور فعال است؛ برای تغییر پورت ورودی، روش، پروتکل یا سرور اول «حذف از سرور» را بزن.")
    return rule


def create_rule(db, data: dict) -> dict:
    rule = normalize(db, data)
    rules = _load(db)
    rules.append(rule)
    _save(db, rules)
    return public(rule)


def update_rule(db, rule_id: str, data: dict) -> dict:
    rules = _load(db)
    for i, old in enumerate(rules):
        if old["id"] == rule_id:
            new = normalize(db, data, old)
            if old.get("enabled"):
                new["status"] = "pending"
            rules[i] = new
            _save(db, rules)
            return public(new)
    raise PortForwardError("قانون پیدا نشد.")


def _put(db, rule: dict) -> None:
    rules = _load(db)
    for i, old in enumerate(rules):
        if old["id"] == rule["id"]:
            rules[i] = rule
            _save(db, rules)
            return


def _drop(db, rule_id: str) -> None:
    _save(db, [r for r in _load(db) if r["id"] != rule_id])


def unit_name(rule: dict) -> str:
    return f"shopvpn-fwd-{rule['id']}"


_HEAD = r"""set -e
need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  if command -v apt-get >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$2" >/dev/null 2>&1 || true
  elif command -v dnf >/dev/null 2>&1; then dnf install -y -q "$2" >/dev/null 2>&1 || true
  elif command -v yum >/dev/null 2>&1; then yum install -y -q "$2" >/dev/null 2>&1 || true
  fi
  command -v "$1" >/dev/null 2>&1 || { echo "INSTALL_FAILED:$2"; exit 4; }
}
"""


def _vars(rule: dict) -> str:
    q = shlex.quote
    bind_arg = "" if rule["bind"] == "0.0.0.0" else f"-d {rule['bind']}"
    return (
        f"ID={q(rule['id'])}\nUNIT={q(unit_name(rule))}\nTAG={q(unit_name(rule))}\n"
        f"PROTO={q(rule['proto'])}\nBIND={q(rule['bind'])}\nBINDARG={q(bind_arg)}\n"
        f"LP={rule['listen_port']}\nDH={q(rule['dest_host'])}\nDP={rule['dest_port']}\n"
        f"LFLAG={'t' if rule['proto'] == 'tcp' else 'u'}\n"
        f"SCRIPT=/usr/local/sbin/{unit_name(rule)}.sh\nUNITFILE=/etc/systemd/system/{unit_name(rule)}.service\n"
    )


_IPT_FUNCS = r"""r() {
  t=$1; a=$2; shift 2
  case "$a" in
    add) "$IPT" -t "$t" -C "$@" 2>/dev/null || "$IPT" -t "$t" -A "$@" ;;
    del) while "$IPT" -t "$t" -C "$@" 2>/dev/null; do "$IPT" -t "$t" -D "$@"; done ;;
    chk) "$IPT" -t "$t" -C "$@" 2>/dev/null ;;
  esac
}
rules() {
  r nat "$1" PREROUTING $BINDARG -p "$PROTO" --dport "$LP" -m comment --comment "$TAG" -j DNAT --to-destination "$DH:$DP"
  r nat "$1" POSTROUTING -p "$PROTO" -d "$DH" --dport "$DP" -m comment --comment "$TAG" -j MASQUERADE
  r filter "$1" FORWARD -p "$PROTO" -d "$DH" --dport "$DP" -m comment --comment "$TAG" -j ACCEPT
}
rules_ok() {
  r nat chk PREROUTING $BINDARG -p "$PROTO" --dport "$LP" -m comment --comment "$TAG" -j DNAT --to-destination "$DH:$DP" \
  && r nat chk POSTROUTING -p "$PROTO" -d "$DH" --dport "$DP" -m comment --comment "$TAG" -j MASQUERADE \
  && r filter chk FORWARD -p "$PROTO" -d "$DH" --dport "$DP" -m comment --comment "$TAG" -j ACCEPT
}
"""


def _ipt_helper_script(rule: dict) -> str:
    return "#!/bin/bash\nset -e\n" + _vars(rule) + 'IPT=$(command -v iptables)\n' + _IPT_FUNCS + (
        'case "${1:-add}" in add) rules add ;; del) rules del ;; esac\n')


def build_apply(rule: dict) -> str:
    parts = [_HEAD, _vars(rule)]
    parts.append(_teardown(rule))
    parts.append(
        'if command -v ss >/dev/null 2>&1 && ss -H -ln"$LFLAG" "sport = :$LP" 2>/dev/null | grep -q .; then\n'
        '  echo "PORT_BUSY:$LP"; exit 3\nfi\n')
    if rule["method"] == "socat":
        proto = rule["proto"].upper()
        listen = f"{proto}-LISTEN:$LP,bind=$BIND,fork,reuseaddr"
        parts.append('need socat socat\nSOCAT=$(command -v socat)\n')
        parts.append(
            'cat > "$UNITFILE" <<EOF\n[Unit]\nDescription=ShopVPN socat forward ' + rule["id"] + '\n'
            'After=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\n'
            f'ExecStart=$SOCAT {listen} {proto}:$DH:$DP\n'
            'Restart=always\nRestartSec=3\n\n[Install]\nWantedBy=multi-user.target\nEOF\n')
    else:
        parts.append('need iptables iptables\n')
        parts.append("sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true\n"
                     "mkdir -p /etc/sysctl.d\necho 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-shopvpn-forward.conf\n")
        parts.append("cat > \"$SCRIPT\" <<'EOS'\n" + _ipt_helper_script(rule) + "EOS\nchmod 700 \"$SCRIPT\"\n")
        parts.append(
            'cat > "$UNITFILE" <<EOF\n[Unit]\nDescription=ShopVPN iptables forward ' + rule["id"] + '\n'
            'After=network-online.target\nWants=network-online.target\n\n[Service]\nType=oneshot\n'
            'RemainAfterExit=yes\nExecStart=$SCRIPT add\nExecStop=$SCRIPT del\n\n'
            '[Install]\nWantedBy=multi-user.target\nEOF\n')
    parts.append(f'systemctl daemon-reload\nsystemctl enable "$UNIT" >/dev/null 2>&1 || true\n'
                 f'systemctl restart "$UNIT"\nsleep 1\n')
    if rule["method"] == "socat":
        parts.append('systemctl is-active --quiet "$UNIT" || { echo "UNIT_FAILED"; journalctl -u "$UNIT" -n 5 --no-pager 2>/dev/null || true; exit 5; }\n')
    else:
        parts.append('IPT=$(command -v iptables)\n' + _IPT_FUNCS +
                     'rules_ok || { echo "RULES_MISSING"; exit 5; }\n')
    parts.append("echo OK\n")
    return "".join(parts)


def _teardown(rule: dict) -> str:
    return (
        'systemctl stop "$UNIT" >/dev/null 2>&1 || true\n'
        'systemctl disable "$UNIT" >/dev/null 2>&1 || true\n'
        'if [ -x "$SCRIPT" ]; then "$SCRIPT" del >/dev/null 2>&1 || true; fi\n'
        'if command -v iptables >/dev/null 2>&1; then\n  IPT=$(command -v iptables)\n' + _IPT_FUNCS +
        '  rules del >/dev/null 2>&1 || true\nfi\n'
    )


def build_remove(rule: dict, quiet: bool = False) -> str:
    return ("set -e\n" + _vars(rule) + _teardown(rule) +
            'rm -f "$UNITFILE" "$SCRIPT"\nsystemctl daemon-reload\n' + ("" if quiet else "echo OK\n"))


def build_status(rule: dict) -> str:
    body = "set +e\n" + _vars(rule)
    if rule["method"] == "socat":
        body += ('if systemctl is-active --quiet "$UNIT"; then echo ACTIVE=1; else echo ACTIVE=0; fi\n'
                 'if command -v ss >/dev/null 2>&1 && ss -H -ln"$LFLAG" "sport = :$LP" 2>/dev/null | grep -q .; '
                 'then echo LISTEN=1; else echo LISTEN=0; fi\n')
    else:
        body += ('IPT=$(command -v iptables)\n' + _IPT_FUNCS +
                 'if [ -n "$IPT" ] && rules_ok; then echo ACTIVE=1; else echo ACTIVE=0; fi\necho LISTEN=1\n')
    return body + "echo OK\n"


async def _run_local(script: str, timeout: int) -> tuple:
    argv = ["bash", "-c", script] if os.geteuid() == 0 else ["sudo", "-n", "bash", "-c", script]
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        raise PortForwardError("زمان اجرای دستور روی سرور تمام شد.")
    except FileNotFoundError:
        raise PortForwardError("bash یا sudo روی سرور پیدا نشد.")
    text = (out or b"").decode("utf-8", "replace")
    if proc.returncode != 0 and "password" in text.lower() and "sudo" in text.lower():
        raise PortForwardError("پنل وب با کاربر غیرروت اجرا می‌شود و sudo بدون رمز برایش فعال نیست.")
    return proc.returncode, text


async def _run_ssh(script: str, rule: dict, password: str | None, key: str | None, timeout: int) -> tuple:
    try:
        import asyncssh
    except ImportError as exc:
        raise PortForwardError("کتابخانه asyncssh نصب نیست.") from exc
    if not (password or key):
        raise PortForwardError("رمز یا کلید خصوصی SSH سرور رله را وارد کن.")
    kwargs = {"host": rule["ssh_host"], "port": rule["ssh_port"], "username": rule["ssh_user"],
              "known_hosts": None, "connect_timeout": 20}
    if key:
        try:
            kwargs["client_keys"] = [asyncssh.import_private_key(key)]
        except Exception as exc:
            raise PortForwardError("کلید خصوصی SSH معتبر نیست.") from exc
    else:
        kwargs["password"] = password
        kwargs["client_keys"] = None
    try:
        conn = await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=25)
    except asyncssh.PermissionDenied as exc:
        raise PortForwardError("ورود SSH ناموفق بود؛ نام کاربری یا رمز/کلید را بررسی کن.") from exc
    except Exception as exc:
        raise PortForwardError(f"اتصال SSH برقرار نشد ({type(exc).__name__}).") from exc
    async with conn:
        is_root = (await conn.run("id -u", check=False)).stdout.strip() == "0"
        use_sudo_pw = False
        if not is_root:
            probe = await conn.run("sudo -n true", check=False)
            if probe.exit_status != 0:
                if not password:
                    raise PortForwardError("کاربر SSH روت نیست و sudo بدون رمز ندارد.")
                probe = await conn.run("sudo -S -p '' -v", input=password + "\n", check=False)
                if probe.exit_status != 0:
                    raise PortForwardError("رمز sudo معتبر نیست.")
                use_sudo_pw = True
        if is_root:
            cmd = "bash -c " + shlex.quote(script)
        elif use_sudo_pw:
            cmd = "sudo -S -p '' bash -c " + shlex.quote(script)
        else:
            cmd = "sudo -n bash -c " + shlex.quote(script)
        try:
            res = await asyncio.wait_for(conn.run(cmd, check=False, input=(password + "\n") if use_sudo_pw else None), timeout)
        except asyncio.TimeoutError:
            raise PortForwardError("زمان اجرای دستور روی سرور تمام شد.")
        return res.exit_status, ((res.stdout or "") + (res.stderr or ""))


_ERRORS = {
    3: "این پورت روی سرور از قبل توسط برنامه‌ی دیگری استفاده می‌شود.",
    4: "نصب بسته‌ی موردنیاز روی سرور ناموفق بود.",
    5: "سرویس فوروارد بعد از اجرا فعال نشد.",
}


def _tail(text: str, limit: int = 600) -> str:
    return (text or "").strip()[-limit:]


async def run_script(rule: dict, script: str, password: str | None = None, key: str | None = None,
                     db_secret_enc: str | None = None, timeout: int = 240) -> tuple:
    if rule["run_on"] == "ssh":
        if not password and not key and db_secret_enc:
            from ssh_credentials import decrypt_credential
            password = decrypt_credential(db_secret_enc)
        return await _run_ssh(script, rule, password, key, timeout)
    return await _run_local(script, timeout)


async def act(db, rule_id: str, action: str, ssh_password: str | None = None, ssh_key: str | None = None,
              force: bool = False) -> dict:
    if action not in ACTIONS:
        raise PortForwardError("عملیات نامعتبر است.")
    rule = get_rule(db, rule_id)
    if action == "delete" and not rule.get("enabled"):
        _drop(db, rule_id)
        return {"deleted": True}
    script = {"apply": build_apply, "remove": build_remove, "delete": build_remove, "status": build_status}[action](rule)
    try:
        code, out = await run_script(rule, script, ssh_password, ssh_key, rule.get("ssh_pass_enc"))
    except PortForwardError as exc:
        if action == "delete" and force:
            _drop(db, rule_id)
            return {"deleted": True, "warning": str(exc)}
        if action != "status":
            rule["last_error"] = str(exc)
            if action == "apply":
                rule["status"] = "error"
            _put(db, rule)
        raise
    if code != 0 or "OK" not in out.splitlines()[-1:]:
        message = _ERRORS.get(code) or "اجرای دستور روی سرور ناموفق بود."
        detail = _tail(out)
        if action == "delete" and force:
            _drop(db, rule_id)
            return {"deleted": True, "warning": message}
        if action != "status":
            rule["last_error"] = f"{message} {detail}".strip()
            if action == "apply":
                rule["status"] = "error"
            _put(db, rule)
        raise PortForwardError(f"{message}\n{detail}" if detail else message)
    now = int(time.time())
    if action == "apply":
        rule.update(enabled=True, status="active", last_error="", applied_at=now)
    elif action in ("remove", "delete"):
        rule.update(enabled=False, status="removed", last_error="")
    else:
        fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if rule.get("enabled"):
            rule["status"] = "active" if fields.get("ACTIVE") == "1" and fields.get("LISTEN") == "1" else "stopped"
        rule["last_error"] = "" if rule["status"] == "active" else rule.get("last_error", "")
    if action == "delete":
        _drop(db, rule_id)
        return {"deleted": True}
    _put(db, rule)
    return {"rule": public(rule)}
