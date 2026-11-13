#!/usr/bin/env bash
# ساخت نسخه‌ی minify شده‌ی فایل‌های استاتیک پنل وب (app.js / i18n.js / style.css).
#
# این اسکریپت به‌صورت خودکار اجرا می‌شود:
#   - بعد از هر آپدیت (update_runner.sh و update.sh) و قبل از ری‌استارت سرویس‌ها
#   - هر بار که سرویس پنل وب بالا می‌آید (startup در admin_panel/server.py)
# پس بعد از هر آپدیت یا ری‌استارت لازم نیست دستی چیزی اجرا کنی.
#
# استفاده:
#   build_assets.sh              همیشه می‌سازد
#   build_assets.sh --if-stale   فقط وقتی سورس با build فعلی نمی‌خواند می‌سازد (سریع و بی‌خطر برای اجرای مکرر)
#
# اگر esbuild/npx/node نباشد یا شبکه نباشد، خطا نمی‌دهد: پنل وب خودش وقتی build با
# سورس نخواند، مستقیم فایل سورس را سرو می‌کند (فقط کمی حجیم‌تر).
set -uo pipefail
cd "$(dirname "$0")/static" || exit 0
mkdir -p built

IF_STALE=0
[ "${1:-}" = "--if-stale" ] && IF_STALE=1

digest() { sha1sum "$1" | cut -c1-10; }
log() { echo "[build_assets] $*"; }

APP_D="$(digest app.js)"; I18N_D="$(digest i18n.js)"; CSS_D="$(digest style.css)"

if [ "$IF_STALE" = "1" ] && [ -f built/manifest.json ] \
   && [ -f built/app.min.js ] && [ -f built/i18n.min.js ] && [ -f built/style.min.css ] \
   && grep -q "\"src\": \"$APP_D\"" built/manifest.json \
   && grep -q "\"src\": \"$I18N_D\"" built/manifest.json \
   && grep -q "\"src\": \"$CSS_D\"" built/manifest.json; then
    log "up to date"
    exit 0
fi

# جلوگیری از اجرای هم‌زمان (مثلاً چند سرویس هم‌زمان ری‌استارت شوند)
if command -v flock >/dev/null 2>&1; then
    exec 9>built/.build.lock
    flock -w 300 9 || { log "could not get lock"; exit 0; }
    # بعد از گرفتن قفل، ممکن است نفر قبلی کار را تمام کرده باشد
    if [ "$IF_STALE" = "1" ] && [ -f built/manifest.json ] \
       && grep -q "\"src\": \"$APP_D\"" built/manifest.json \
       && grep -q "\"src\": \"$I18N_D\"" built/manifest.json \
       && grep -q "\"src\": \"$CSS_D\"" built/manifest.json; then
        log "up to date"
        exit 0
    fi
fi

if command -v esbuild >/dev/null 2>&1; then
    ES=(esbuild)
elif command -v npx >/dev/null 2>&1; then
    ES=(npx --yes esbuild)
else
    log "esbuild/npx not found -> skipped (panel will serve the source files)"
    exit 0
fi

TMP="$(mktemp -d built/.tmp.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

build() {
    local src="$1" out="$2"; shift 2
    timeout 240 "${ES[@]}" "$src" --minify --charset=utf8 --legal-comments=none "$@" \
        --outfile="$TMP/$out" --log-level=error
}

if ! build app.js app.min.js --target=es2019 \
   || ! build i18n.js i18n.min.js --target=es2019 \
   || ! build style.css style.min.css; then
    log "build failed -> kept previous files (panel falls back to source when stale)"
    exit 1
fi

# فایل‌ها اتمیک جایگزین می‌شوند و manifest آخر نوشته می‌شود؛ پس سرور هرگز نیمه‌کاره نمی‌بیند
mv -f "$TMP/app.min.js" built/app.min.js
mv -f "$TMP/i18n.min.js" built/i18n.min.js
mv -f "$TMP/style.min.css" built/style.min.css
printf '{\n  "app.js": {"src": "%s", "out": "app.min.js"},\n  "i18n.js": {"src": "%s", "out": "i18n.min.js"},\n  "style.css": {"src": "%s", "out": "style.min.css"}\n}\n' \
  "$APP_D" "$I18N_D" "$CSS_D" > built/manifest.json.tmp && mv -f built/manifest.json.tmp built/manifest.json
log "built: app=$APP_D i18n=$I18N_D css=$CSS_D"
ls -l built | grep -v '^total' | grep -v '\.build\.lock'
