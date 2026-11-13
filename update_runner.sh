#!/bin/bash
# اجراکننده‌ی آپدیت/برگشت — توسط بات (updater.py) جدا از پروسه‌ی بات اجرا می‌شود.
# استفاده: update_runner.sh update|rollback
# متغیرها: INSTALL_DIR SERVICE_NAME REPO_OWNER REPO_NAME REPO_BRANCH (و UPDATE_DETACHED=1)
set -u
MODE="${1:-update}"
INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "$0")" && pwd)}"
SERVICE_NAME="${SERVICE_NAME:-v2raybot}"
REPO_OWNER="${REPO_OWNER:-mehdirafatpanah}"
REPO_NAME="${REPO_NAME:-Shopvpn}"
REPO_BRANCH="${REPO_BRANCH:-main}"
export GIT_TERMINAL_PROMPT=0

cd "$INSTALL_DIR" || exit 1
mkdir -p logs backups
exec >>"logs/update.log" 2>&1
echo "=================== $(date '+%F %T') mode=$MODE ==================="

RESULT="$INSTALL_DIR/update_result.txt"
PY="$INSTALL_DIR/venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo -n"
TS="$(date +%Y%m%d_%H%M%S)"
FROM_VERSION="$(tr -d '[:space:]' < VERSION 2>/dev/null || echo '?')"
SNAP="$INSTALL_DIR/backups/code_before_update_${TS}.tar.gz"
OLD_HEAD=""
[ -d .git ] && OLD_HEAD="$(git rev-parse HEAD 2>/dev/null || true)"

log() { echo "[$(date '+%T')] $*"; }
write_result() { # status reason
    printf 'status=%s\nreason=%s\nfrom=%s\nto=%s\n' "$1" "${2:-}" "$FROM_VERSION" \
        "$(tr -d '[:space:]' < VERSION 2>/dev/null || echo '?')" > "$RESULT"
}

extra_services() {
    for suffix in miniapp adminpanel api sub store; do
        if systemctl cat "${SERVICE_NAME}-${suffix}.service" >/dev/null 2>&1; then
            echo "${SERVICE_NAME}-${suffix}"
        fi
    done
}

build_assets() { # ساخت خودکار نسخه‌ی minify پنل وب؛ شکست آن هیچ‌وقت آپدیت را خراب نمی‌کند
    [ -f admin_panel/build_assets.sh ] || return 0
    log "build admin panel assets"
    timeout 400 bash admin_panel/build_assets.sh --if-stale 2>&1 | tail -n 5 || log "WARN: build_assets failed (ignored)"
}

restart_all() {
    build_assets
    for svc in $(extra_services); do
        log "restart $svc"
        $SUDO systemctl restart "$svc" || log "WARN: restart $svc failed"
    done
    log "restart $SERVICE_NAME (last)"
    $SUDO systemctl restart "$SERVICE_NAME"
}

healthy() { # بعد از ری‌استارت: ۱۵ ثانیه صبر، سرویس باید فعال و بدون ری‌استارت خودکار باشد
    sleep 15
    $SUDO systemctl is-active --quiet "$SERVICE_NAME" || return 1
    local n
    n="$(systemctl show -p NRestarts --value "$SERVICE_NAME" 2>/dev/null || echo 0)"
    [ -z "$n" ] || [ "$n" = "0" ] || return 1
    return 0
}

restore_snapshot() { # $1 = مسیر فایل tar.gz
    log "restoring code from $1"
    tar -xzf "$1" -C "$INSTALL_DIR" || return 1
    if [ -n "$OLD_HEAD" ] && [ -d .git ]; then git reset -q --mixed "$OLD_HEAD" 2>/dev/null || true; fi
    return 0
}

prune_backups() {
    ls -1t backups/code_before_update_*.tar.gz 2>/dev/null | tail -n +4 | xargs -r rm -f
    ls -1t backups/db_before_update_*.db 2>/dev/null | tail -n +4 | xargs -r rm -f
}

do_rollback_after_failure() { # $1 reason
    log "ROLLBACK: $1"
    if restore_snapshot "$SNAP"; then
        "$PY" -m pip install -r requirements.txt --quiet 2>&1 | tail -n 3
        restart_all
        write_result rolled_back "$1"
    else
        write_result failed "$1 (و برگشت خودکار هم ناموفق بود؛ بکاپ: $SNAP)"
    fi
    exit 1
}

# ----------------------------------------------------------------------------
if [ "$MODE" = "rollback" ]; then
    LAST="$(ls -1t backups/code_before_update_*.tar.gz 2>/dev/null | head -n 1)"
    [ -n "$LAST" ] || { write_result failed "نسخه‌ی پشتیبان پیدا نشد"; exit 1; }
    restore_snapshot "$LAST" || { write_result failed "بازیابی بکاپ ناموفق بود"; exit 1; }
    "$PY" -m pip install -r requirements.txt --quiet 2>&1 | tail -n 3
    restart_all
    if healthy; then write_result rollback_ok ""; else write_result failed "بعد از برگشت سرویس بالا نیامد"; fi
    exit 0
fi

# ---------------------------- update ----------------------------------------
log "from version $FROM_VERSION"

log "backup: code snapshot"
tar -czf "$SNAP" --exclude=./venv --exclude=./.git --exclude=./backups --exclude=./logs \
    --exclude=./reseller_dbs --exclude='./*.db' --exclude='./*.db-*' --exclude=./.env \
    --exclude='__pycache__' -C "$INSTALL_DIR" . || { write_result failed "گرفتن بکاپ کد ناموفق بود"; exit 1; }

log "backup: database"
"$PY" - "$INSTALL_DIR" "$TS" <<'PYEOF' || log "WARN: db backup failed"
import os, sqlite3, sys
base, ts = sys.argv[1], sys.argv[2]
src = os.path.join(base, "bot_database.db")
if os.path.exists(src):
    dst = os.path.join(base, "backups", f"db_before_update_{ts}.db")
    a = sqlite3.connect(src); b = sqlite3.connect(dst)
    with b: a.backup(b)
    a.close(); b.close()
    print("db backup ->", dst)
PYEOF

log "fetch code"
fetched=0
if [ -d .git ]; then
    if git pull --ff-only --quiet origin "$REPO_BRANCH"; then fetched=1; else log "git pull failed -> archive fallback"; fi
fi
if [ "$fetched" = "0" ]; then
    tmp_tar="$(mktemp)"
    if ! curl -fsSL --max-time 180 \
        "https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${REPO_BRANCH}" -o "$tmp_tar"; then
        rm -f "$tmp_tar"; write_result failed "دانلود نسخه‌ی جدید از GitHub ناموفق بود"; exit 1
    fi
    if ! tar -xzf "$tmp_tar" -C "$INSTALL_DIR" --strip-components=1 \
        --exclude='.env' --exclude='*.db' --exclude='*.db-*' --exclude='venv' --exclude='.git' --exclude='backups'; then
        rm -f "$tmp_tar"; do_rollback_after_failure "بازکردن آرشیو نسخه‌ی جدید ناموفق بود"
    fi
    rm -f "$tmp_tar"
fi
NEW_VERSION="$(tr -d '[:space:]' < VERSION 2>/dev/null || echo '?')"
log "new version $NEW_VERSION"

log "pip install"
"$PY" -m pip install -r requirements.txt --quiet || do_rollback_after_failure "نصب پکیج‌های جدید ناموفق بود"

log "syntax check"
"$PY" -m compileall -q -f -x '(venv|backups|logs|reseller_dbs)' . >/dev/null \
    || do_rollback_after_failure "کد نسخه‌ی جدید خطای نحوی داشت"

prune_backups
restart_all
if healthy; then
    log "OK: $FROM_VERSION -> $NEW_VERSION"
    write_result ok ""
else
    do_rollback_after_failure "سرویس بعد از آپدیت پایدار بالا نیامد"
fi
