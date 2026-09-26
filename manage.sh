#!/bin/bash
# ============================================================================
# Text management panel for the V2Ray config sales bot
# پنل مدیریت متنی بات فروش کانفیگ V2Ray
#
# Run directly (no prior install):
#   bash <(curl -fsSL https://raw.githubusercontent.com/USERNAME/v2ray-bot/main/manage.sh)
#
# Run after install:
#   bash ~/v2ray_bot/manage.sh
# ============================================================================

# ---------------------------------------------------------------------------
# Customizable settings / تنظیمات قابل شخصی‌سازی
# ---------------------------------------------------------------------------
REPO_URL="https://github.com/mehdirafatpanah/Shopvpn.git"
INSTALL_DIR="$HOME/v2ray_bot"
SERVICE_NAME="v2raybot"
GITHUB_OWNER="mehdirafatpanah"
GITHUB_REPO="Shopvpn"
GITHUB_BRANCH="main"
export GIT_TERMINAL_PROMPT=0

# ---------------------------------------------------------------------------
# Fetch/update project code without ever hanging on a git username/password
# prompt. Some server IPs (common on cheap VPS providers) get blocked or
# rate-limited by GitHub for the git-over-https protocol, even for public
# repos, and git falls back to an interactive credential prompt that just
# hangs a headless install. We try git first (fast, incremental); if it
# fails for any reason we fall back to downloading the plain tarball, which
# uses a different endpoint (codeload.github.com) and is not subject to
# that block.
# دریافت/آپدیت کد پروژه بدون گیر کردن روی پرامپت یوزرنیم/پسورد گیت.
# ---------------------------------------------------------------------------
fetch_project_code() {
    local target_dir="$1"
    local ok=0

    if [ -d "$target_dir/.git" ]; then
        if git -C "$target_dir" pull --quiet 2>/dev/null; then ok=1; fi
    elif [ ! -f "$target_dir/main.py" ]; then
        if git clone --quiet "$REPO_URL" "$target_dir" 2>/dev/null; then ok=1; fi
    fi

    if [ "$ok" = "1" ]; then
        return 0
    fi

    echo -e "${YELLOW}⚠️  دسترسی git مسدود شد، در حال دریافت از طریق آرشیو مستقیم...${RESET}"
    local tmp_tar tmp_dir
    tmp_tar=$(mktemp)
    tmp_dir=$(mktemp -d)
    if ! curl -fsSL "https://codeload.github.com/${GITHUB_OWNER}/${GITHUB_REPO}/tar.gz/refs/heads/${GITHUB_BRANCH}" -o "$tmp_tar"; then
        echo -e "${RED}❌ دانلود آرشیو پروژه هم ناموفق بود. اتصال اینترنت سرور را بررسی کن.${RESET}"
        rm -f "$tmp_tar"; rm -rf "$tmp_dir"
        return 1
    fi
    tar -xzf "$tmp_tar" -C "$tmp_dir" --strip-components=1
    rm -f "$tmp_tar"
    mkdir -p "$target_dir"
    if ! command -v rsync > /dev/null 2>&1; then
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync > /dev/null
    fi
    rsync -a --exclude='.env' --exclude='*.db' --exclude='*.db-journal' \
        --exclude='*.sqlite3' --exclude='venv' --exclude='.git' --exclude='backups' \
        "$tmp_dir"/ "$target_dir"/
    rm -rf "$target_dir/.git" 2>/dev/null
    rm -rf "$tmp_dir"
    return 0
}

# Version is computed automatically from git (commit count + short hash)
# so that every update (git pull) shows the correct running version.
# It's read from the VERSION file (bumped only for real, notable changes,
# not for every raw commit). The short git hash is shown next to it for
# exact build identification. If VERSION is missing, falls back to the
# old commit-count method so the banner is never empty.
get_version() {
    local base hash
    if [ -f "$INSTALL_DIR/VERSION" ]; then
        base="v$(cat "$INSTALL_DIR/VERSION" 2>/dev/null | tr -d '[:space:]')"
    elif [ -d "$INSTALL_DIR/.git" ]; then
        base="v$(git -C "$INSTALL_DIR" rev-list --count HEAD 2>/dev/null)"
    else
        base="v1.0"
    fi
    if [ -d "$INSTALL_DIR/.git" ]; then
        hash=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null)
        [ -n "$hash" ] && base="${base} (${hash})"
    fi
    echo "$base"
}

# Avoid apt getting stuck behind interactive prompts (e.g. needrestart)
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

# ---------------------------------------------------------------------------
# Colors / رنگ‌ها
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'
UI_WIDTH=60

# ---------------------------------------------------------------------------
# Language / زبان
# Default language is English. It can be switched to Persian from the menu
# ([L]) and the choice is remembered for next time.
# ---------------------------------------------------------------------------
LANG_FILE="$HOME/.shopvpn_manage_lang"
APP_LANG="en"
if [ -f "$LANG_FILE" ]; then
    _saved_lang=$(tr -d '[:space:]' < "$LANG_FILE" 2>/dev/null)
    [ "$_saved_lang" = "fa" ] && APP_LANG="fa"
fi

toggle_lang() {
    if [ "$APP_LANG" = "en" ]; then
        APP_LANG="fa"
    else
        APP_LANG="en"
    fi
    echo "$APP_LANG" > "$LANG_FILE" 2>/dev/null
}

declare -A MSG_EN
declare -A MSG_FA

# Status / وضعیت
MSG_EN[not_installed]="Not installed"
MSG_FA[not_installed]="نصب نشده"
MSG_EN[service_running]="Running"
MSG_FA[service_running]="در حال اجرا"
MSG_EN[service_stopped]="Stopped"
MSG_FA[service_stopped]="متوقف"
MSG_EN[lbl_bot]="Bot"
MSG_FA[lbl_bot]="بات"
MSG_EN[lbl_miniapp]="Mini App"
MSG_FA[lbl_miniapp]="مینی‌اپ"
MSG_EN[lbl_panel]="Admin Panel"
MSG_FA[lbl_panel]="پنل مدیریت"
MSG_EN[lbl_api]="Integration API"
MSG_FA[lbl_api]="API یکپارچه‌سازی"
MSG_EN[subtitle]="BOT MANAGEMENT ENGINE"
MSG_FA[subtitle]="موتور مدیریت بات"

MSG_EN[sec_setup]="BOT SETUP"
MSG_FA[sec_setup]="نصب و به‌روزرسانی"
MSG_EN[sec_service]="SERVICE CONTROL"
MSG_FA[sec_service]="کنترل سرویس"
MSG_EN[sec_store]="STORE & CONFIG"
MSG_FA[sec_store]="فروشگاه و تنظیمات"
MSG_EN[sec_miniapp]="MINI APP"
MSG_FA[sec_miniapp]="مینی‌اپ"
MSG_EN[sec_panel]="ADMIN PANEL"
MSG_FA[sec_panel]="پنل مدیریت وب"
MSG_EN[sec_domains]="DOMAINS & PROXY"
MSG_FA[sec_domains]="دامنه و پروکسی"
MSG_EN[sec_api]="INTEGRATION API"
MSG_FA[sec_api]="API یکپارچه‌سازی"
MSG_EN[sec_advanced]="ADVANCED"
MSG_FA[sec_advanced]="پیشرفته"
MSG_EN[sec_translation]="AUTO-TRANSLATION"
MSG_FA[sec_translation]="ترجمه خودکار"
MSG_EN[pause_prompt]="Press Enter to return to the menu..."
MSG_FA[pause_prompt]="برای بازگشت به منو، Enter را بزن..."

# install_bot
MSG_EN[installing_prereqs]="📦 Checking and installing prerequisites (git, python3, pip, venv)..."
MSG_FA[installing_prereqs]="📦 بررسی و نصب پیش‌نیازها (git, python3, pip, venv)..."
MSG_EN[already_installed_pulling]="⚠️ Project is already installed. Fetching the latest version..."
MSG_FA[already_installed_pulling]="⚠️ پروژه از قبل نصب شده است. در حال دریافت آخرین نسخه..."
MSG_EN[cloning_project]="📥 Cloning the project from GitHub..."
MSG_FA[cloning_project]="📥 دریافت پروژه از گیت‌هاب..."
MSG_EN[preparing_python]="🐍 Preparing the Python environment..."
MSG_FA[preparing_python]="🐍 آماده‌سازی محیط پایتون..."
MSG_EN[enter_bot_info]="🔑 Enter the bot info:"
MSG_FA[enter_bot_info]="🔑 اطلاعات بات را وارد کن:"
MSG_EN[prompt_bot_token]="Bot token (from BotFather): "
MSG_FA[prompt_bot_token]="توکن بات (از BotFather): "
MSG_EN[prompt_owner_id]="Admin numeric ID: "
MSG_FA[prompt_owner_id]="آیدی عددی ادمین: "
MSG_EN[env_created]="✅ .env file created."
MSG_FA[env_created]="✅ فایل .env ساخته شد."
MSG_EN[env_exists]="✅ .env file already exists, left unchanged."
MSG_FA[env_exists]="✅ فایل .env از قبل موجود است، دست‌نخورده باقی می‌ماند."
MSG_EN[creating_service]="⚙️ Creating the systemd service..."
MSG_FA[creating_service]="⚙️ ساخت سرویس systemd..."
MSG_EN[install_done]="✅ Installation complete, the bot is running."
MSG_FA[install_done]="✅ نصب کامل شد و بات در حال اجراست."
MSG_EN[install_failed]="⚠️ Bot did not start. To check the error: sudo journalctl -u %s -n 50 --no-pager"
MSG_FA[install_failed]="⚠️ بات اجرا نشد. برای بررسی خطا: sudo journalctl -u %s -n 50 --no-pager"

# update_bot / update_miniapp
MSG_EN[bot_not_installed]="⛔️ Bot not installed yet. Run option 1 (install) first."
MSG_FA[bot_not_installed]="⛔️ بات هنوز نصب نشده. اول گزینه ۱ (نصب) را بزن."
MSG_EN[fetching_latest]="🔄 Fetching latest changes from GitHub"
MSG_FA[fetching_latest]="🔄 دریافت آخرین تغییرات از گیت‌هاب"
MSG_EN[updating_packages]="🐍 Updating Python packages"
MSG_FA[updating_packages]="🐍 آپدیت پکیج‌های پایتون"
MSG_EN[restarting_bot_service]="♻️ Restarting bot service"
MSG_FA[restarting_bot_service]="♻️ ری‌استارت سرویس بات"
MSG_EN[update_bot_header]="Updating Bot"
MSG_FA[update_bot_header]="آپدیت بات"
MSG_EN[update_done]="✅ Bot updated."
MSG_FA[update_done]="✅ آپدیت بات انجام شد."
MSG_EN[miniapp_not_installed]="⛔️ Mini App not installed yet. Run option 10 (setup Mini App) first."
MSG_FA[miniapp_not_installed]="⛔️ مینی‌اپ هنوز نصب نشده. اول گزینه ۱۰ (نصب/تنظیم مینی‌اپ) را بزن."
MSG_EN[restarting_miniapp_service]="♻️ Restarting Mini App service"
MSG_FA[restarting_miniapp_service]="♻️ ری‌استارت سرویس مینی‌اپ"
MSG_EN[update_miniapp_header]="Updating Mini App"
MSG_FA[update_miniapp_header]="آپدیت مینی‌اپ"
MSG_EN[miniapp_update_done]="✅ Mini App updated."
MSG_FA[miniapp_update_done]="✅ آپدیت مینی‌اپ انجام شد."

# uninstall_bot
MSG_EN[uninstall_warning]="⚠️ This will completely remove the bot service."
MSG_FA[uninstall_warning]="⚠️ این کار سرویس بات را کاملاً حذف می‌کند."
MSG_EN[confirm_prompt]="Are you sure? (type yes to confirm): "
MSG_FA[confirm_prompt]="آیا مطمئن هستی؟ (yes برای تایید): "
MSG_EN[cancelled]="Cancelled."
MSG_FA[cancelled]="لغو شد."
MSG_EN[service_removed]="✅ Service removed."
MSG_FA[service_removed]="✅ سرویس حذف شد."
MSG_EN[confirm_delete_files]="Also delete the project files (including the customer database)? (type yes to confirm): "
MSG_FA[confirm_delete_files]="آیا فایل‌های پروژه (شامل دیتابیس مشتری‌ها) هم پاک شود؟ (yes برای تایید): "
MSG_EN[files_removed]="✅ Project files removed too."
MSG_FA[files_removed]="✅ فایل‌های پروژه هم حذف شدند."
MSG_EN[files_kept]="Project files kept at %s."
MSG_FA[files_kept]="فایل‌های پروژه در %s باقی ماندند."

# view_logs / restart / stop
MSG_EN[logs_exit_hint]="To exit live log view: Ctrl+C"
MSG_FA[logs_exit_hint]="برای خروج از حالت لاگ زنده: Ctrl+C"
MSG_EN[bot_restarted]="✅ Bot restarted."
MSG_FA[bot_restarted]="✅ بات ری‌استارت شد."
MSG_EN[bot_stopped]="⛔️ Bot stopped."
MSG_FA[bot_stopped]="⛔️ بات متوقف شد."

# show_stats
MSG_EN[no_database]="No database found."
MSG_FA[no_database]="دیتابیسی پیدا نشد."

# edit_env
MSG_EN[prompt_new_token]="New bot token (press Enter to keep current): "
MSG_FA[prompt_new_token]="توکن جدید بات (اگر تغییری نیست Enter بزن): "
MSG_EN[prompt_new_owner]="New admin numeric ID (press Enter to keep current): "
MSG_FA[prompt_new_owner]="آیدی عددی جدید ادمین (اگر تغییری نیست Enter بزن): "
MSG_EN[saved_restarting]="✅ Saved. Restarting..."
MSG_FA[saved_restarting]="✅ ذخیره شد. در حال ری‌استارت..."

# restore_backup_cli (new-server migration wizard)
MSG_EN[prompt_backup_path]="Full path of the backup .db file already placed on this server (e.g. /root/bot_database.db): "
MSG_FA[prompt_backup_path]="مسیر کامل فایل بکاپ .db که از قبل روی همین سرور گذاشتی (مثلاً /root/bot_database.db): "
MSG_EN[backup_file_missing]="⛔️ File not found at this path."
MSG_FA[backup_file_missing]="⛔️ فایلی در این مسیر پیدا نشد."
MSG_EN[validating_backup]="🔎 Validating the backup file..."
MSG_FA[validating_backup]="🔎 بررسی صحت فایل بکاپ..."
MSG_EN[venv_missing]="⛔️ Python venv not found. Install the bot first (option 1)."
MSG_FA[venv_missing]="⛔️ محیط مجازی پایتون پیدا نشد. اول بات را نصب کن (گزینه ۱)."
MSG_EN[backup_invalid]="⛔️ This file is not a valid SQLite database. Cancelled."
MSG_FA[backup_invalid]="⛔️ این فایل یک دیتابیس SQLite معتبر نیست. لغو شد."
MSG_EN[restore_warning]="⚠️ This will completely replace the current database with the uploaded backup (a safety copy of the current one is kept)."
MSG_FA[restore_warning]="⚠️ این کار دیتابیس فعلی را کاملاً با فایل بکاپ جایگزین می‌کند (یک نسخه‌ی امن از وضعیت فعلی هم نگه داشته می‌شود)."
MSG_EN[stopping_services_for_restore]="⏸ Stopping services to safely replace the database..."
MSG_FA[stopping_services_for_restore]="⏸ توقف سرویس‌ها برای جایگزینی امن دیتابیس..."
MSG_EN[restoring_backup]="♻️ Restoring the database..."
MSG_FA[restoring_backup]="♻️ در حال بازیابی دیتابیس..."
MSG_EN[restore_failed]="⛔️ Restore failed: %s\nServices have been started back up unchanged."
MSG_FA[restore_failed]="⛔️ بازیابی ناموفق بود: %s\nسرویس‌ها بدون تغییر دوباره روشن شدند."
MSG_EN[restore_done]="✅ Database restored. A safety copy of the previous one was saved as: %s"
MSG_FA[restore_done]="✅ دیتابیس بازیابی شد. یک نسخه‌ی امن از دیتابیس قبلی با نام «%s» ذخیره شد."
MSG_EN[prompt_had_miniapp]="Was the Mini App enabled on the old server? Set up a new domain for it now on this server? (y/n): "
MSG_FA[prompt_had_miniapp]="آیا مینی‌اپ روی سرور قبلی فعال بود؟ الان یک دامنه‌ی جدید برایش روی این سرور تنظیم شود؟ (y/n): "
MSG_EN[prompt_had_panel]="Was the standalone Admin Panel enabled on the old server? Set up a new domain for it now on this server? (y/n): "
MSG_FA[prompt_had_panel]="آیا پنل مدیریت وب مستقل روی سرور قبلی فعال بود؟ الان یک دامنه‌ی جدید برایش روی این سرور تنظیم شود؟ (y/n): "
MSG_EN[restore_flow_done]="🎉 Migration to the new server finished."
MSG_FA[restore_flow_done]="🎉 انتقال به سرور جدید تمام شد."

# setup_miniapp / setup_admin_panel (shared)
MSG_EN[miniapp_dir_missing]="⛔️ miniapp folder not found. Update the project code first (git pull/update)."
MSG_FA[miniapp_dir_missing]="⛔️ پوشه miniapp پیدا نشد. اول باید کد مینی‌اپ را داخل پروژه بیاوری (git pull/آپدیت)."
MSG_EN[panel_dir_missing]="⛔️ admin_panel folder not found. Update the project code first (option 2)."
MSG_FA[panel_dir_missing]="⛔️ پوشه admin_panel پیدا نشد. اول باید کد پروژه را آپدیت کنی (گزینه ۲)."
MSG_EN[prompt_domain_miniapp]="Enter the domain pointing to this server's IP (e.g. shop.example.com): "
MSG_FA[prompt_domain_miniapp]="دامنه‌ای که به IP همین سرور اشاره می‌کند را وارد کن (مثلاً shop.example.com): "
MSG_EN[prompt_domain_panel]="Enter the domain pointing to this server's IP (e.g. panel.example.com): "
MSG_FA[prompt_domain_panel]="دامنه‌ای که به IP همین سرور اشاره می‌کند را وارد کن (مثلاً panel.example.com): "
MSG_EN[domain_empty]="Domain is empty, cancelled."
MSG_FA[domain_empty]="دامنه خالی است، لغو شد."
MSG_EN[checking_dns]="🔎 Checking domain DNS..."
MSG_FA[checking_dns]="🔎 بررسی DNS دامنه..."
MSG_EN[dns_mismatch_warn]="⚠️ Warning: the domain does not point to this server's IP (%s) (currently %s)."
MSG_FA[dns_mismatch_warn]="⚠️ هشدار: دامنه به IP این سرور (%s) اشاره نمی‌کند (الان %s است)."
MSG_EN[continue_prompt]="Continue anyway? (type yes to continue): "
MSG_FA[continue_prompt]="همچنان ادامه بدهم؟ (yes برای ادامه): "
MSG_EN[installing_nginx]="📦 Installing nginx and certbot..."
MSG_FA[installing_nginx]="📦 نصب nginx و certbot..."
MSG_EN[installing_miniapp_pkgs]="🐍 Installing Mini App packages (fastapi, uvicorn)..."
MSG_FA[installing_miniapp_pkgs]="🐍 نصب پکیج‌های مینی‌اپ (fastapi, uvicorn)..."
MSG_EN[installing_panel_pkgs]="🐍 Installing admin panel packages (fastapi, uvicorn)..."
MSG_FA[installing_panel_pkgs]="🐍 نصب پکیج‌های پنل (fastapi, uvicorn)..."
MSG_EN[creating_miniapp_service]="⚙️ Creating the systemd service for the Mini App backend..."
MSG_FA[creating_miniapp_service]="⚙️ ساخت سرویس systemd برای بک‌اند مینی‌اپ..."
MSG_EN[creating_panel_service]="⚙️ Creating the systemd service for the admin panel..."
MSG_FA[creating_panel_service]="⚙️ ساخت سرویس systemd برای پنل مدیریت وب..."
MSG_EN[configuring_nginx]="🌐 Configuring nginx for %s..."
MSG_FA[configuring_nginx]="🌐 تنظیم nginx برای %s..."
MSG_EN[nginx_error]="⛔️ nginx config has an error. Details: %s"
MSG_FA[nginx_error]="⛔️ کانفیگ nginx خطا دارد. جزئیات: %s"
MSG_EN[getting_ssl]="🔐 Obtaining a free SSL certificate (Let's Encrypt)..."
MSG_FA[getting_ssl]="🔐 دریافت گواهی SSL رایگان (Let's Encrypt)..."
MSG_EN[ssl_failed]="⛔️ Getting the SSL certificate failed. Make sure the domain correctly points to this server and ports 80/443 are open."
MSG_FA[ssl_failed]="⛔️ دریافت SSL ناموفق بود. مطمئن شو دامنه درست به این سرور اشاره می‌کند و پورت 80/443 باز است."
MSG_EN[saving_miniapp_url]="📝 Saving the Mini App URL in .env..."
MSG_FA[saving_miniapp_url]="📝 ثبت آدرس مینی‌اپ در .env..."
MSG_EN[miniapp_ready]="✅ Mini App is ready: %s"
MSG_FA[miniapp_ready]="✅ مینی‌اپ آماده است: %s"
MSG_EN[miniapp_button_hint]="The «✨ Store Mini App» button will now appear in the bot menu."
MSG_FA[miniapp_button_hint]="دکمه «✨ مینی‌اپ فروشگاه» از الان در منوی بات دیده می‌شود."
MSG_EN[panel_ready]="✅ Admin panel is ready: %s"
MSG_FA[panel_ready]="✅ پنل مدیریت آماده است: %s"
MSG_EN[panel_login_hint]="Log in with the username/password you created."
MSG_FA[panel_login_hint]="با یوزرنیم/پسوردی که ساختی وارد شو."
MSG_EN[restarting_bot_for_panel_url]="🔁 Restarting the main bot so it picks up the panel address (ADMIN_PANEL_URL)..."
MSG_FA[restarting_bot_for_panel_url]="🔁 ری‌استارت بات اصلی تا آدرس پنل (ADMIN_PANEL_URL) را بشناسد..."
MSG_EN[enter_owner_account]="🔑 Create the panel owner account:"
MSG_FA[enter_owner_account]="🔑 حساب مالک (owner) پنل را بساز:"
MSG_EN[prompt_username]="Username: "
MSG_FA[prompt_username]="یوزرنیم: "
MSG_EN[prompt_password]="Password (min 8 characters): "
MSG_FA[prompt_password]="پسورد (حداقل ۸ کاراکتر): "

# change_admin_panel_credentials
MSG_EN[no_panel_admins_found]="⛔️ No admin panel accounts found yet. Run option 13 (setup admin panel) first."
MSG_FA[no_panel_admins_found]="⛔️ هنوز هیچ حساب پنلی ساخته نشده. اول گزینه ۱۳ (نصب/تنظیم پنل مدیریت) را بزن."
MSG_EN[existing_admins_header]="👤 Existing panel accounts:"
MSG_FA[existing_admins_header]="👤 حساب‌های موجود پنل:"
MSG_EN[prompt_current_username]="Current username: "
MSG_FA[prompt_current_username]="یوزرنیم فعلی: "
MSG_EN[prompt_new_username]="New username (leave empty to keep it unchanged): "
MSG_FA[prompt_new_username]="یوزرنیم جدید (خالی بگذار تا همان قبلی بماند): "
MSG_EN[prompt_new_password]="New password (min 8 characters): "
MSG_FA[prompt_new_password]="پسورد جدید (حداقل ۸ کاراکتر): "
MSG_EN[change_admin_creds_cancelled]="Current username or new password is empty, cancelled."
MSG_FA[change_admin_creds_cancelled]="یوزرنیم فعلی یا پسورد جدید خالی است، لغو شد."

# remove_miniapp
MSG_EN[remove_miniapp_warn]="⚠️ This will remove the Mini App service and its nginx config (the SSL certificate is kept)."
MSG_FA[remove_miniapp_warn]="⚠️ این کار سرویس و کانفیگ nginx مینی‌اپ را حذف می‌کند (گواهی SSL نگه داشته می‌شود)."
MSG_EN[prompt_domain_used_miniapp]="What domain did you use for the Mini App? (to remove its nginx config): "
MSG_FA[prompt_domain_used_miniapp]="دامنه‌ای که برای مینی‌اپ استفاده کرده بودی چه بود؟ (برای حذف کانفیگ nginx): "
MSG_EN[miniapp_removed]="✅ Mini App removed."
MSG_FA[miniapp_removed]="✅ مینی‌اپ حذف شد."

# update_admin_panel / remove_admin_panel
MSG_EN[panel_not_installed_yet]="⛔️ Admin panel not installed yet. Run option 13 (setup admin panel) first."
MSG_FA[panel_not_installed_yet]="⛔️ پنل مدیریت هنوز نصب نشده. اول گزینه ۱۳ (نصب/تنظیم پنل مدیریت) را بزن."
MSG_EN[restarting_panel_service]="♻️ Restarting admin panel service"
MSG_FA[restarting_panel_service]="♻️ ری‌استارت سرویس پنل مدیریت"
MSG_EN[update_panel_header]="Updating Admin Panel"
MSG_FA[update_panel_header]="آپدیت پنل مدیریت"
MSG_EN[panel_update_done]="✅ Admin panel updated."
MSG_FA[panel_update_done]="✅ آپدیت پنل مدیریت انجام شد."
MSG_EN[remove_panel_warn]="⚠️ This will remove the admin panel service and its nginx config (SSL certificate is kept; panel accounts in the database are untouched)."
MSG_FA[remove_panel_warn]="⚠️ این کار سرویس و کانفیگ nginx پنل مدیریت را حذف می‌کند (گواهی SSL نگه داشته می‌شود؛ حساب‌های پنل در دیتابیس دست‌نخورده می‌مانند)."
MSG_EN[prompt_domain_used_panel]="What domain did you use for the admin panel? (to remove its nginx config): "
MSG_FA[prompt_domain_used_panel]="دامنه‌ای که برای پنل مدیریت استفاده کرده بودی چه بود؟ (برای حذف کانفیگ nginx): "
MSG_EN[panel_removed]="✅ Admin panel removed."
MSG_FA[panel_removed]="✅ پنل مدیریت حذف شد."

# setup_vapid_keys
MSG_EN[admin_panel_folder_missing]="⛔️ admin_panel folder not found. Update the project code first (option 2)."
MSG_FA[admin_panel_folder_missing]="⛔️ پوشه admin_panel پیدا نشد. اول باید کد پروژه را آپدیت کنی (گزینه ۲)."
MSG_EN[vapid_already_set_warn1]="⚠️ VAPID keys are already set."
MSG_FA[vapid_already_set_warn1]="⚠️ کلیدهای VAPID از قبل تنظیم شده‌اند."
MSG_EN[vapid_already_set_warn2]="If you regenerate them, every device that already enabled notifications will stop working and will need to re-enable them."
MSG_FA[vapid_already_set_warn2]="اگر دوباره بسازی، تمام دستگاه‌هایی که قبلاً اعلان را فعال کرده‌اند از کار می‌افتند و باید دوباره فعال‌سازی کنند."
MSG_EN[confirm_regenerate]="Generate and replace with new keys anyway? (type yes to confirm): "
MSG_FA[confirm_regenerate]="همچنان کلید جدید بسازم و جایگزین کنم؟ (yes برای تایید): "
MSG_EN[prompt_vapid_email]="Contact email for VAPID (optional, press Enter for admin@example.com): "
MSG_FA[prompt_vapid_email]="ایمیل تماس برای VAPID (اختیاری، Enter بزن برای پیش‌فرض admin@example.com): "
MSG_EN[generating_vapid]="🔑 Generating VAPID keys..."
MSG_FA[generating_vapid]="🔑 در حال ساخت کلیدهای VAPID..."
MSG_EN[vapid_generation_failed]="⛔️ Key generation failed."
MSG_FA[vapid_generation_failed]="⛔️ ساخت کلیدها ناموفق بود."
MSG_EN[vapid_saved]="✅ VAPID keys generated and saved to .env."
MSG_FA[vapid_saved]="✅ کلیدهای VAPID ساخته و در .env ذخیره شدند."
MSG_EN[panel_restarted_hint]="✅ Service restarted. Now log into the panel and click \"Enable\" notifications."
MSG_FA[panel_restarted_hint]="✅ سرویس ری‌استارت شد. حالا وارد پنل شو و روی «فعال‌سازی» اعلان بزن."
MSG_EN[panel_not_installed_vapid_hint]="Admin panel not installed yet. These keys will be used automatically once installed (option 13)."
MSG_FA[panel_not_installed_vapid_hint]="پنل مدیریت هنوز نصب نشده. بعد از نصب (گزینه ۱۳) این کلیدها خودکار استفاده می‌شوند."

# setup_api / update_api / remove_api
MSG_EN[api_dir_missing]="⛔️ api folder not found. Update the project code first (option 2)."
MSG_FA[api_dir_missing]="⛔️ پوشه api پیدا نشد. اول باید کد پروژه را آپدیت کنی (گزینه ۲)."
MSG_EN[prompt_domain_api]="Enter a dedicated domain pointing to this server's IP (e.g. api.example.com): "
MSG_FA[prompt_domain_api]="یک دامنه‌ی جدا که به IP همین سرور اشاره می‌کند را وارد کن (مثلاً api.example.com): "
MSG_EN[creating_api_service]="⚙️ Creating the systemd service for the integration API..."
MSG_FA[creating_api_service]="⚙️ ساخت سرویس systemd برای API یکپارچه‌سازی..."
MSG_EN[api_ready]="✅ Integration API is ready: %s"
MSG_FA[api_ready]="✅ API یکپارچه‌سازی آماده است: %s"
MSG_EN[api_token_hint]="Create a token by sending /token2 to the admin bot. Docs: /api/index.html and /api/docs. Access log: logs/api_access.log"
MSG_FA[api_token_hint]="برای ساخت توکن در بات ادمین دستور /token2 را بفرست. مستندات: /api/index.html و /api/docs. لاگ دسترسی: logs/api_access.log"
MSG_EN[api_not_installed]="⛔️ Integration API not installed yet. Run option 24 (setup integration API) first."
MSG_FA[api_not_installed]="⛔️ API یکپارچه‌سازی هنوز نصب نشده. اول گزینه ۲۴ (نصب/تنظیم API یکپارچه‌سازی) را بزن."
MSG_EN[restarting_api_service]="♻️ Restarting integration API service"
MSG_FA[restarting_api_service]="♻️ ری‌استارت سرویس API یکپارچه‌سازی"
MSG_EN[update_api_header]="Updating Integration API"
MSG_FA[update_api_header]="آپدیت API یکپارچه‌سازی"
MSG_EN[api_update_done]="✅ Integration API updated."
MSG_FA[api_update_done]="✅ آپدیت API یکپارچه‌سازی انجام شد."
MSG_EN[remove_api_warn]="⚠️ This will remove the integration API service and its nginx config (the SSL certificate is kept; API tokens in the database are untouched)."
MSG_FA[remove_api_warn]="⚠️ این کار سرویس و کانفیگ nginx API یکپارچه‌سازی را حذف می‌کند (گواهی SSL نگه داشته می‌شود؛ توکن‌ها در دیتابیس دست‌نخورده می‌مانند)."
MSG_EN[prompt_domain_used_api]="What domain did you use for the integration API? (to remove its nginx config): "
MSG_FA[prompt_domain_used_api]="دامنه‌ای که برای API یکپارچه‌سازی استفاده کرده بودی چه بود؟ (برای حذف کانفیگ nginx): "
MSG_EN[api_removed]="✅ Integration API removed."
MSG_FA[api_removed]="✅ API یکپارچه‌سازی حذف شد."

# setup_panel_proxy / remove_panel_proxy
MSG_EN[prompt_domain_panel_proxy]="Domain for the VPN panel (e.g. panel.example.com): "
MSG_FA[prompt_domain_panel_proxy]="دامنه‌ای که برای پنل VPN می‌خواهی (مثلا panel.example.com): "
MSG_EN[prompt_backend_address]="Local address:port the VPN panel is listening on (e.g. 127.0.0.1:8000): "
MSG_FA[prompt_backend_address]="آدرس:پورت داخلی که پنل VPN رویش گوش می‌دهد (مثلا 127.0.0.1:8000): "
MSG_EN[backend_address_empty]="⛔️ Address:port cannot be empty."
MSG_FA[backend_address_empty]="⛔️ آدرس:پورت نمی‌تواند خالی باشد."
MSG_EN[prompt_backend_https]="Does the panel serve HTTPS itself on that port (usually with a self-signed certificate)? (yes/no): "
MSG_FA[prompt_backend_https]="آیا خود پنل روی همان پورت HTTPS (معمولا با گواهی خودامضا) سرو می‌کند؟ (yes/no): "
MSG_EN[prompt_backend_path]="URL path to proxy on this domain (press Enter for / , e.g. /dashboard or /a1b2c3): "
MSG_FA[prompt_backend_path]="مسیر (path) روی این دامنه که پروکسی شود (برای / فقط Enter بزن، مثلا /dashboard یا /a1b2c3): "
MSG_EN[panel_proxy_note]="⚠️ Make sure the VPN panel's own installer is NOT bound to ports 80/443 anymore (disable its own nginx/haproxy, or set it to listen only on the address:port you entered), otherwise it will still conflict with this server's nginx."
MSG_FA[panel_proxy_note]="⚠️ مطمئن شو نصب‌کننده خود پنل VPN دیگر روی پورت 80/443 گوش نمی‌دهد (nginx/haproxy داخلی خودش را غیرفعال کن یا فقط روی همان آدرس:پورتی که وارد کردی محدودش کن)، وگرنه باز هم با nginx این سرور تصادم می‌کند."
MSG_EN[panel_proxy_ready]="✅ Reverse-proxy is ready. The VPN panel is now reachable at: %s"
MSG_FA[panel_proxy_ready]="✅ پروکسی آماده است. پنل VPN از این آدرس در دسترس است: %s"
MSG_EN[remove_panel_proxy_warn]="⚠️ This will remove the nginx config for this VPN panel proxy (the SSL certificate is kept)."
MSG_FA[remove_panel_proxy_warn]="⚠️ این کار کانفیگ nginx این پروکسی پنل VPN را حذف می‌کند (گواهی SSL نگه داشته می‌شود)."
MSG_EN[prompt_domain_used_panel_proxy]="Which domain did you use for this VPN panel proxy? (to remove its nginx config): "
MSG_FA[prompt_domain_used_panel_proxy]="برای این پروکسی پنل VPN چه دامنه‌ای استفاده کرده بودی؟ (برای حذف کانفیگ nginx): "
MSG_EN[panel_proxy_removed]="✅ VPN panel proxy removed."
MSG_FA[panel_proxy_removed]="✅ پروکسی پنل VPN حذف شد."
MSG_EN[panel_proxy_list_header]="📋 Panel/config proxies set up with this menu:"
MSG_FA[panel_proxy_list_header]="📋 پروکسی‌های پنل/کانفیگی که با این منو ساخته شده‌اند:"
MSG_EN[panel_proxy_list_empty]="No panel proxy has been set up with option 17 yet."
MSG_FA[panel_proxy_list_empty]="هنوز هیچ پروکسی پنلی با گزینه ۱۷ ساخته نشده."
MSG_EN[panel_proxy_list_enabled]="enabled"
MSG_FA[panel_proxy_list_enabled]="فعال"
MSG_EN[panel_proxy_list_disabled]="disabled"
MSG_FA[panel_proxy_list_disabled]="غیرفعال"
MSG_EN[panel_proxy_list_ssl_ok]="valid until %s"
MSG_FA[panel_proxy_list_ssl_ok]="معتبر تا %s"
MSG_EN[panel_proxy_list_ssl_missing]="no certificate found"
MSG_FA[panel_proxy_list_ssl_missing]="گواهی SSL پیدا نشد"
MSG_EN[panel_proxy_domain_conflict]="⚠️ This domain (%s) already has an nginx config that was NOT created by this menu (likely your Mini App or Admin Panel domain). Using it here would overwrite that config and break the Mini App / Admin Panel. Pick a different domain/subdomain for the panel proxy, or remove the existing config yourself first if you are sure."
MSG_FA[panel_proxy_domain_conflict]="⚠️ این دامنه (%s) از قبل یک کانفیگ nginx دارد که با این منو ساخته نشده (احتمالاً دامنه مینی‌اپ یا پنل مدیریت توست). اگر همین‌جا ادامه بدهی، آن کانفیگ overwrite می‌شود و مینی‌اپ/پنل مدیریت از دسترس خارج می‌شوند. یک دامنه یا ساب‌دامنه دیگر برای پروکسی پنل انتخاب کن، یا اگر مطمئنی، اول خودت کانفیگ فعلی را حذف کن."

MSG_EN[service_domains_header]="🌐 Domains registered for the Mini App / Admin Panel"
MSG_FA[service_domains_header]="🌐 دامنه‌های ثبت‌شده برای مینی‌اپ / پنل مدیریت"
MSG_EN[service_domains_empty]="No domain is registered yet for the Mini App or Admin Panel."
MSG_FA[service_domains_empty]="هنوز هیچ دامنه‌ای برای مینی‌اپ یا پنل مدیریت ثبت نشده."
MSG_EN[service_domains_miniapp_label]="Mini App"
MSG_FA[service_domains_miniapp_label]="مینی‌اپ"
MSG_EN[service_domains_panel_label]="Admin Panel"
MSG_FA[service_domains_panel_label]="پنل مدیریت"
MSG_EN[service_domains_delete_prompt]="Enter the number to delete that domain (removes nginx+SSL only, service stays up), or press Enter to cancel: "
MSG_FA[service_domains_delete_prompt]="شماره مورد نظر برای حذف آن دامنه را وارد کن (فقط nginx و SSL حذف می‌شود، سرویس خاموش نمی‌شود)، برای لغو فقط Enter بزن: "
MSG_EN[service_domains_delete_warn]="⚠️ This removes the nginx/SSL config for the %s domain (%s). It will stop working until you set a new one."
MSG_FA[service_domains_delete_warn]="⚠️ این کار تنظیمات nginx/SSL دامنه %s (%s) را حذف می‌کند. تا دامنه جدید تنظیم نکنی، از کار می‌افتد."
MSG_EN[service_domains_deleted]="✅ Domain config removed."
MSG_FA[service_domains_deleted]="✅ تنظیمات دامنه حذف شد."
MSG_EN[current_bot_mode]="Current mode: %s"
MSG_FA[current_bot_mode]="حالت فعلی: %s"
MSG_EN[choose_bot_mode]="Choose [1/2]: "
MSG_FA[choose_bot_mode]="انتخاب [1/2]: "
MSG_EN[prompt_domain_webhook]="Domain to use for the bot webhook (DNS must point to this server): "
MSG_FA[prompt_domain_webhook]="دامنه‌ای که برای وب‌هوک بات استفاده می‌کنی (DNS باید روی این سرور باشد): "
MSG_EN[bot_mode_set_polling]="✅ Mode set to Polling and the bot was restarted."
MSG_FA[bot_mode_set_polling]="✅ حالت روی Polling تنظیم شد و بات ری‌استارت شد."
MSG_EN[bot_mode_set_webhook]="✅ Webhook mode is ready: %s"
MSG_FA[bot_mode_set_webhook]="✅ حالت Webhook آماده شد: %s"

# Main menu / منوی اصلی
MSG_EN[menu_1]="Full bot install (first time)"
MSG_FA[menu_1]="نصب کامل بات (اولین بار)"
MSG_EN[menu_2]="Update bot"
MSG_FA[menu_2]="آپدیت بات"
MSG_EN[menu_3]="Completely remove bot from server"
MSG_FA[menu_3]="حذف کامل بات از سرور"
MSG_EN[menu_4]="View bot status"
MSG_FA[menu_4]="مشاهده وضعیت بات"
MSG_EN[menu_5]="View live logs"
MSG_FA[menu_5]="مشاهده لاگ زنده"
MSG_EN[menu_6]="Restart bot"
MSG_FA[menu_6]="ری‌استارت بات"
MSG_EN[menu_7]="Stop bot"
MSG_FA[menu_7]="توقف بات"
MSG_EN[menu_8]="View sales stats"
MSG_FA[menu_8]="مشاهده آمار فروش"
MSG_EN[menu_9]="Change admin token or ID"
MSG_FA[menu_9]="تغییر توکن یا آیدی ادمین"
MSG_EN[menu_10]="Setup Mini App (auto: domain + SSL + service)"
MSG_FA[menu_10]="نصب/تنظیم مینی‌اپ (خودکار: دامنه + SSL + سرویس)"
MSG_EN[menu_11]="Remove Mini App"
MSG_FA[menu_11]="حذف مینی‌اپ"
MSG_EN[menu_12]="Update Mini App"
MSG_FA[menu_12]="آپدیت مینی‌اپ"
MSG_EN[menu_13]="Setup admin panel (domain + SSL + service)"
MSG_FA[menu_13]="نصب/تنظیم پنل مدیریت وب (دامنه + SSL + سرویس)"
MSG_EN[menu_14]="Remove admin panel"
MSG_FA[menu_14]="حذف پنل مدیریت وب"
MSG_EN[menu_15]="Update admin panel"
MSG_FA[menu_15]="آپدیت پنل مدیریت وب"
MSG_EN[menu_16]="Generate VAPID keys (admin panel push)"
MSG_FA[menu_16]="ساخت کلید VAPID (اعلان Push پنل)"
MSG_EN[menu_17]="Add domain proxy for VPN panel (share port 443)"
MSG_FA[menu_17]="افزودن دامنه پروکسی برای پنل VPN (اشتراک پورت 443)"
MSG_EN[menu_18]="List panel/config domain proxies"
MSG_FA[menu_18]="نمایش لیست پروکسی‌های دامنه پنل/کانفیگ"
MSG_EN[menu_19]="Remove VPN panel domain proxy"
MSG_FA[menu_19]="حذف دامنه پروکسی پنل VPN"
MSG_EN[menu_20]="Mini App / Admin Panel domains (view + delete)"
MSG_FA[menu_20]="دامنه‌های مینی‌اپ / پنل مدیریت (نمایش + حذف)"
MSG_EN[menu_21]="Restore backup (new server migration wizard)"
MSG_FA[menu_21]="بازیابی بکاپ (ویزارد انتقال به سرور جدید)"
MSG_EN[menu_22]="Bot update mode (Polling / Webhook)"
MSG_FA[menu_22]="حالت دریافت آپدیت بات (Polling / Webhook)"
MSG_EN[menu_24]="Setup integration API (domain + SSL + service)"
MSG_FA[menu_24]="نصب/تنظیم API یکپارچه‌سازی (دامنه + SSL + سرویس)"
MSG_EN[menu_25]="Remove integration API"
MSG_FA[menu_25]="حذف API یکپارچه‌سازی"
MSG_EN[menu_26]="Update integration API"
MSG_FA[menu_26]="آپدیت API یکپارچه‌سازی"
MSG_EN[menu_23]="Change admin panel username/password"
MSG_FA[menu_23]="تغییر نام کاربری و رمز عبور پنل مدیریت وب"
MSG_EN[menu_27]="Repair / install local translation runtime (automatic)"
MSG_FA[menu_27]="نصب/آپدیت خودکار موتور ترجمه محلی"
MSG_EN[menu_28]="Remove LibreTranslate"
MSG_FA[menu_28]="حذف LibreTranslate"
MSG_EN[menu_lang]="Language / زبان (English ⇄ فارسی)"
MSG_FA[menu_lang]="Language / زبان (English ⇄ فارسی)"
MSG_EN[menu_0]="Exit"
MSG_FA[menu_0]="خروج"
MSG_EN[enter_choice_prompt]="Enter choice [0-28, L]: "
MSG_FA[enter_choice_prompt]="یک گزینه انتخاب کن [0-28, L]: "
MSG_EN[invalid_choice]="Invalid option."
MSG_FA[invalid_choice]="گزینه نامعتبر است."
MSG_EN[goodbye]="Goodbye 👋"
MSG_FA[goodbye]="خدانگهدار 👋"

# LibreTranslate self-hosted install / لغات نصب LibreTranslate اختصاصی
MSG_EN[lt_header]="Self-hosted LibreTranslate"
MSG_FA[lt_header]="LibreTranslate اختصاصی (self-hosted)"
MSG_EN[lt_installing_deps]="📦 Making sure Python/venv are installed..."
MSG_FA[lt_installing_deps]="📦 اطمینان از نصب بودن Python/venv..."
MSG_EN[lt_venv_failed]="✗ Failed to create the virtual environment."
MSG_FA[lt_venv_failed]="✗ ساخت virtual environment ناموفق بود."
MSG_EN[lt_installing_pip]="⬇️ Installing LibreTranslate via pip (downloads translation models, may take several minutes and needs a few GB of free disk)..."
MSG_FA[lt_installing_pip]="⬇️ در حال نصب LibreTranslate با pip (مدل‌های ترجمه دانلود می‌شود، ممکن است چند دقیقه طول بکشد و چند گیگابایت فضای دیسک لازم دارد)..."
MSG_EN[lt_pip_failed]="✗ pip install failed. Last lines of the log:"
MSG_FA[lt_pip_failed]="✗ نصب با pip ناموفق بود. آخرین خطوط لاگ:"
MSG_EN[lt_writing_service]="⚙️ Creating the systemd service..."
MSG_FA[lt_writing_service]="⚙️ در حال ساخت سرویس systemd..."
MSG_EN[lt_already_installed]="⚠️ A LibreTranslate service already exists on this server."
MSG_FA[lt_already_installed]="⚠️ یک سرویس LibreTranslate از قبل روی این سرور وجود دارد."
MSG_EN[lt_confirm_reinstall]="Remove it and reinstall fresh? (type yes to confirm): "
MSG_FA[lt_confirm_reinstall]="حذف و نصب دوباره از صفر؟ (برای تأیید yes بنویس): "
MSG_EN[lt_waiting_ready]="⏳ Waiting for language models to load (first run only, can take a few minutes)"
MSG_FA[lt_waiting_ready]="⏳ در انتظار بارگذاری مدل‌های زبان (فقط بار اول، ممکن است چند دقیقه طول بکشد)"
MSG_EN[lt_ready]="✅ LibreTranslate is up and answering requests."
MSG_FA[lt_ready]="✅ LibreTranslate بالا آمد و به درخواست‌ها پاسخ می‌دهد."
MSG_EN[lt_not_ready_yet]="⚠️ Still not answering after a few minutes; it may still be downloading language models in the background. Check again shortly with: sudo journalctl -u %s -n 50 --no-pager"
MSG_FA[lt_not_ready_yet]="⚠️ بعد از چند دقیقه هنوز پاسخ نمی‌دهد؛ ممکن است هنوز در حال دانلود مدل‌های زبان در پس‌زمینه باشد. کمی بعد با این دستور بررسی کن: sudo journalctl -u %s -n 50 --no-pager"
MSG_EN[lt_env_saved]="✅ Saved the LibreTranslate address in .env (SHOPVPN_LIBRETRANSLATE_URL)."
MSG_FA[lt_env_saved]="✅ آدرس LibreTranslate در .env ذخیره شد (SHOPVPN_LIBRETRANSLATE_URL)."
MSG_EN[lt_done]="🎉 Done. LibreTranslate now runs automatically as a free, unlimited translation fallback — no API key needed."
MSG_FA[lt_done]="🎉 تمام شد. از این به بعد LibreTranslate به‌صورت خودکار به‌عنوان جایگزین رایگان و بدون محدودیت ترجمه استفاده می‌شود — بدون نیاز به هیچ کلید API."
MSG_EN[lt_remove_warn]="⚠️ This removes the local LibreTranslate fallback. Argos local models remain available for translation."
MSG_FA[lt_remove_warn]="⚠️ این کار LibreTranslate محلی را حذف می‌کند. مدل‌های محلی Argos همچنان برای ترجمه در دسترس می‌مانند."
MSG_EN[lt_removed]="✅ LibreTranslate removed."
MSG_FA[lt_removed]="✅ LibreTranslate حذف شد."
MSG_EN[lt_not_installed]="ℹ️ LibreTranslate is not installed on this server."
MSG_FA[lt_not_installed]="ℹ️ LibreTranslate روی این سرور نصب نیست."

# t <key> [args...] -> prints the localized, formatted string for the
# current APP_LANG (falls back to English if a key is somehow missing).
t() {
    local key="$1"; shift
    local fmt
    if [ "$APP_LANG" = "fa" ]; then
        fmt="${MSG_FA[$key]:-${MSG_EN[$key]}}"
    else
        fmt="${MSG_EN[$key]}"
    fi
    if [ "$#" -gt 0 ]; then
        printf -- "$fmt" "$@"
    else
        printf '%s' "$fmt"
    fi
}

# ---------------------------------------------------------------------------
# Title bar / banner / نوار عنوان / بنر
# ---------------------------------------------------------------------------
draw_rule() {
    local pad
    printf -v pad '%*s' "$UI_WIDTH" ''
    echo -e "  ${DIM}${pad// /─}${RESET}"
}

print_logo() {
    local -a rows=(
        '███████╗██╗  ██╗ ██████╗ ██████╗ ██╗   ██╗██████╗ ███╗   ██╗'
        '██╔════╝██║  ██║██╔═══██╗██╔══██╗██║   ██║██╔══██╗████╗  ██║'
        '███████╗███████║██║   ██║██████╔╝██║   ██║██████╔╝██╔██╗ ██║'
        '╚════██║██╔══██║██║   ██║██╔═══╝ ╚██╗ ██╔╝██╔═══╝ ██║╚██╗██║'
        '███████║██║  ██║╚██████╔╝██║      ╚████╔╝ ██║     ██║ ╚████║'
        '╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝       ╚═══╝  ╚═╝     ╚═╝  ╚═══╝'
    )
    local -a shades=(51 45 39 33 63 99)
    local i
    for i in "${!rows[@]}"; do
        printf '  \033[1;38;5;%sm%s\033[0m\n' "${shades[$i]}" "${rows[$i]}"
    done
}

print_banner() {
    local sub pad
    clear
    echo ""
    print_logo
    draw_rule
    sub="$(t subtitle)  ·  $(get_version)"
    printf -v pad '%*s' $(( (UI_WIDTH - ${#sub}) / 2 + 2 )) ''
    echo -e "${pad}${YELLOW}${BOLD}${sub}${RESET}"
    draw_rule
}

status_row() {
    local label dot color text pad
    label="$(t "$1")"
    case "$2" in
        running) dot="●"; color="${GREEN}${BOLD}"; text="$(t service_running)" ;;
        stopped) dot="●"; color="${RED}${BOLD}"; text="$(t service_stopped)" ;;
        *)       dot="○"; color="${YELLOW}"; text="$(t not_installed)" ;;
    esac
    printf -v pad '%*s' $(( ${#label} < 14 ? 14 - ${#label} : 0 )) ''
    printf '  %b%s%s%b %b%s %s%b\n' "$DIM" "$label" "$pad" "$RESET" "$color" "$dot" "$text" "$RESET"
}

service_state() {
    if systemctl is-active --quiet "$1" 2>/dev/null; then
        echo running
    else
        echo stopped
    fi
}

unit_state() {
    if systemctl list-units --type=service --all 2>/dev/null | grep -q "$1.service"; then
        service_state "$1"
    else
        echo missing
    fi
}

print_status_line() {
    local bot_state="missing"
    [ -d "$INSTALL_DIR" ] && bot_state="$(service_state "$SERVICE_NAME")"
    echo ""
    status_row lbl_bot "$bot_state"
    status_row lbl_miniapp "$(unit_state "${SERVICE_NAME}-miniapp")"
    status_row lbl_panel "$(unit_state "${SERVICE_NAME}-adminpanel")"
    status_row lbl_api "$(unit_state "${SERVICE_NAME}-api")"
    echo ""
}

menu_section() {
    local title fill pad
    title="$(t "$1")"
    fill=$(( UI_WIDTH - ${#title} - 3 ))
    [ "$fill" -lt 0 ] && fill=0
    printf -v pad '%*s' "$fill" ''
    echo -e "  ${YELLOW}${BOLD}▌ ${title}${RESET} ${DIM}${pad// /─}${RESET}"
}

menu_item() {
    local num="$1" key="$2" color="${3:-$RESET}"
    printf '   %b[%2s]%b  %b%s%b\n' "${CYAN}${BOLD}" "$num" "$RESET" "$color" "$(t "$key")" "$RESET"
}

pause() {
    echo ""
    read -rp "$(t pause_prompt)" _
}

# ---------------------------------------------------------------------------
# Step-progress UI for multi-step flows (update, etc.)
# رابط نمایش مرحله‌ای برای عملیات چندمرحله‌ای (آپدیت و ...)
# ---------------------------------------------------------------------------
section_header() {
    local title="$1" fill pad
    fill=$(( UI_WIDTH - ${#title} - 3 ))
    [ "$fill" -lt 0 ] && fill=0
    printf -v pad '%*s' "$fill" ''
    echo ""
    echo -e "  ${YELLOW}${BOLD}▌ ${title}${RESET} ${DIM}${pad// /─}${RESET}"
    echo ""
}

# run_step <index> <total> <label> <command...>
# Runs <command...>, then prints a single aligned result line:
#   [i/N] ✓ label   (green, on success)
#   [i/N] ✗ label   (red, plus last lines of output, on failure)
run_step() {
    local idx="$1" total="$2" label="$3" out status
    shift 3
    out="$("$@" 2>&1)"
    status=$?
    if [ "$status" -eq 0 ]; then
        printf '  %b[%s/%s]%b %b✓%b %s\n' "${CYAN}${BOLD}" "$idx" "$total" "$RESET" "${GREEN}${BOLD}" "$RESET" "$label"
    else
        printf '  %b[%s/%s]%b %b✗%b %s\n' "${CYAN}${BOLD}" "$idx" "$total" "$RESET" "${RED}${BOLD}" "$RESET" "$label"
        if [ -n "$out" ]; then
            echo "$out" | tail -5 | sed "s/^/        ${DIM}/" | sed "s/\$/${RESET}/"
        fi
    fi
    return "$status"
}

# ---------------------------------------------------------------------------
# Action: full initial install / عملیات: نصب اولیه کامل
# ---------------------------------------------------------------------------
install_bot() {
    echo -e "${CYAN}$(t installing_prereqs)${RESET}"
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
    timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get install -y -qq git python3 python3-pip python3-venv > /dev/null

    if [ -f "$INSTALL_DIR/main.py" ]; then
        echo -e "${YELLOW}$(t already_installed_pulling)${RESET}"
    else
        echo -e "${CYAN}$(t cloning_project)${RESET}"
    fi
    fetch_project_code "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    echo -e "${CYAN}$(t preparing_python)${RESET}"
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate

    if [ ! -f "$INSTALL_DIR/.env" ]; then
        echo ""
        echo -e "${YELLOW}${BOLD}$(t enter_bot_info)${RESET}"
        read -rp "$(t prompt_bot_token)" BOT_TOKEN_INPUT
        read -rp "$(t prompt_owner_id)" OWNER_ID_INPUT
        cat > "$INSTALL_DIR/.env" <<EOF
BOT_TOKEN=$BOT_TOKEN_INPUT
OWNER_ID=$OWNER_ID_INPUT
EOF
        echo -e "${GREEN}$(t env_created)${RESET}"
    else
        echo -e "${GREEN}$(t env_exists)${RESET}"
    fi

    echo -e "${CYAN}🌍 نصب خودکار موتور ترجمه محلی و مدل‌های زبان...${RESET}"
    if ! bash "$INSTALL_DIR/setup_local_translation.sh"; then
        echo -e "${YELLOW}⚠️ نصب موتور ترجمه کامل نشد؛ بات ادامه می‌دهد و در آپدیت بعدی دوباره تلاش می‌کند.${RESET}"
    fi

    echo -e "${CYAN}$(t creating_service)${RESET}"
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=V2Ray Telegram Sales Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/main.py
Restart=always
RestartSec=5
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME" > /dev/null 2>&1
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}${BOLD}$(t install_done)${RESET}"
    else
        echo -e "${RED}$(t install_failed "$SERVICE_NAME")${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Action: update / عملیات: آپدیت
# ---------------------------------------------------------------------------
update_bot() {
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        echo -e "${RED}$(t bot_not_installed)${RESET}"
        return
    fi
    cd "$INSTALL_DIR"

    MINIAPP_SERVICE="${SERVICE_NAME}-miniapp"
    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    API_SERVICE="${SERVICE_NAME}-api"
    local has_miniapp=0 has_panel=0 has_api=0
    systemctl list-units --full -all | grep -q "${MINIAPP_SERVICE}.service" && has_miniapp=1
    systemctl list-units --full -all | grep -q "${PANEL_SERVICE}.service" && has_panel=1
    systemctl list-units --full -all | grep -q "${API_SERVICE}.service" && has_api=1

    local total=4
    [ "$has_miniapp" = "1" ] && total=$((total+1))
    [ "$has_panel" = "1" ] && total=$((total+1))
    [ "$has_api" = "1" ] && total=$((total+1))
    local step=0 failed=0

    section_header "$(t update_bot_header)"

    step=$((step+1))
    run_step "$step" "$total" "$(t fetching_latest)" fetch_project_code "$INSTALL_DIR" || failed=1

    step=$((step+1))
    run_step "$step" "$total" "$(t updating_packages)" bash -c "source '$INSTALL_DIR/venv/bin/activate' && pip install -r requirements.txt --quiet && deactivate" || failed=1

    step=$((step+1))
    run_step "$step" "$total" "🌍 Updating local translation runtime/models" bash -c "bash '$INSTALL_DIR/setup_local_translation.sh'" || failed=1

    step=$((step+1))
    run_step "$step" "$total" "$(t restarting_bot_service)" bash -c "sudo systemctl restart '$SERVICE_NAME' && sleep 2" || failed=1

    if [ "$has_miniapp" = "1" ]; then
        step=$((step+1))
        run_step "$step" "$total" "$(t restarting_miniapp_service)" bash -c "sudo systemctl restart '$MINIAPP_SERVICE' && sleep 2" || failed=1
    fi

    if [ "$has_panel" = "1" ]; then
        step=$((step+1))
        run_step "$step" "$total" "$(t restarting_panel_service)" bash -c "sudo systemctl restart '$PANEL_SERVICE' && sleep 2" || failed=1
    fi

    if [ "$has_api" = "1" ]; then
        step=$((step+1))
        run_step "$step" "$total" "$(t restarting_api_service)" bash -c "sudo systemctl restart '$API_SERVICE' && sleep 2" || failed=1
    fi

    draw_rule
    if [ "$failed" = "0" ] && systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "  ${GREEN}${BOLD}$(t update_done)${RESET}"
    else
        echo -e "  ${RED}$(t install_failed "$SERVICE_NAME")${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Action: update Mini App / عملیات: آپدیت مینی‌اپ
# ---------------------------------------------------------------------------
update_miniapp() {
    MINIAPP_SERVICE="${SERVICE_NAME}-miniapp"
    if ! systemctl list-units --full -all | grep -q "${MINIAPP_SERVICE}.service"; then
        echo -e "${RED}$(t miniapp_not_installed)${RESET}"
        return
    fi
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        echo -e "${RED}$(t bot_not_installed)${RESET}"
        return
    fi
    cd "$INSTALL_DIR"

    local failed=0
    section_header "$(t update_miniapp_header)"
    run_step 1 3 "$(t fetching_latest)" fetch_project_code "$INSTALL_DIR" || failed=1
    run_step 2 3 "$(t updating_packages)" bash -c "source '$INSTALL_DIR/venv/bin/activate' && pip install -r requirements.txt --quiet && deactivate" || failed=1
    run_step 3 3 "$(t restarting_miniapp_service)" bash -c "sudo systemctl restart '$MINIAPP_SERVICE' && sleep 2" || failed=1

    draw_rule
    if [ "$failed" = "0" ] && systemctl is-active --quiet "$MINIAPP_SERVICE"; then
        echo -e "  ${GREEN}${BOLD}$(t miniapp_update_done)${RESET}"
    else
        echo -e "  ${RED}$(t install_failed "$MINIAPP_SERVICE")${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Action: full removal / عملیات: حذف کامل
# ---------------------------------------------------------------------------
uninstall_bot() {
    echo -e "${RED}${BOLD}$(t uninstall_warning)${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo -e "${YELLOW}$(t cancelled)${RESET}"
        return
    fi
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo systemctl daemon-reload
    echo -e "${GREEN}$(t service_removed)${RESET}"

    read -rp "$(t confirm_delete_files)" CONFIRM2
    if [ "$CONFIRM2" == "yes" ]; then
        rm -rf "$INSTALL_DIR"
        echo -e "${GREEN}$(t files_removed)${RESET}"
    else
        echo -e "${CYAN}$(t files_kept "$INSTALL_DIR")${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Action: status / logs / restart / stop
# عملیات: وضعیت / لاگ / ری‌استارت / توقف
# ---------------------------------------------------------------------------
view_status() {
    sudo systemctl status "$SERVICE_NAME" --no-pager -l || true
}

view_logs() {
    echo -e "${CYAN}$(t logs_exit_hint)${RESET}"
    sleep 1
    sudo journalctl -u "$SERVICE_NAME" -f
}

restart_bot() {
    sudo systemctl restart "$SERVICE_NAME"
    sleep 1
    echo -e "${GREEN}$(t bot_restarted)${RESET}"
}

stop_bot() {
    sudo systemctl stop "$SERVICE_NAME"
    echo -e "${YELLOW}$(t bot_stopped)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: quick sales stats (direct from DB, bot doesn't need to be running)
# عملیات: آمار فروش سریع (مستقیم از دیتابیس، بدون نیاز به روشن بودن بات)
# ---------------------------------------------------------------------------
show_stats() {
    if [ ! -f "$INSTALL_DIR/bot_database.db" ]; then
        echo -e "${RED}$(t no_database)${RESET}"
        return
    fi
    cd "$INSTALL_DIR"
    source venv/bin/activate
    SHOPVPN_STATS_LANG="$APP_LANG" python3 - <<'PYEOF'
import os
from database import Database

lang = os.environ.get("SHOPVPN_STATS_LANG", "en")
s = Database("bot_database.db").get_stats()

if lang == "fa":
    print(f"\n👥 تعداد کاربران: {s['users']}")
    print(f"⏳ سفارش‌های در انتظار: {s['pending']}")
    print(f"✅ سفارش‌های تایید شده: {s['approved']}")
    print(f"❌ سفارش‌های رد شده: {s['rejected']}")
    print(f"💰 مجموع فروش: {s['revenue']:,} تومان\n")
else:
    print(f"\n👥 Users: {s['users']}")
    print(f"⏳ Pending orders: {s['pending']}")
    print(f"✅ Approved orders: {s['approved']}")
    print(f"❌ Rejected orders: {s['rejected']}")
    print(f"💰 Total revenue: {s['revenue']:,} Toman\n")
PYEOF
    deactivate
}

# ---------------------------------------------------------------------------
# Action: change admin token or ID / عملیات: تغییر توکن یا آیدی ادمین
# ---------------------------------------------------------------------------
edit_env() {
    read -rp "$(t prompt_new_token)" NEW_TOKEN
    read -rp "$(t prompt_new_owner)" NEW_OWNER

    # قبلاً این تابع کل .env را با فقط BOT_TOKEN/OWNER_ID بازنویسی می‌کرد و در
    # نتیجه هر کلید دیگری (MINIAPP_URL، ADMIN_PANEL_URL، BOT_MODE/WEBHOOK_*،
    # کلیدهای درگاه پرداخت و ...) را پاک می‌کرد؛ حالا فقط همین دو کلید در جای
    # خودشان به‌روزرسانی می‌شوند و بقیه‌ی فایل دست‌نخورده می‌ماند.
    if [ -n "$NEW_TOKEN" ]; then
        if grep -q "^BOT_TOKEN=" "$INSTALL_DIR/.env" 2>/dev/null; then
            sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$NEW_TOKEN|" "$INSTALL_DIR/.env"
        else
            echo "BOT_TOKEN=$NEW_TOKEN" >> "$INSTALL_DIR/.env"
        fi
    fi
    if [ -n "$NEW_OWNER" ]; then
        if grep -q "^OWNER_ID=" "$INSTALL_DIR/.env" 2>/dev/null; then
            sed -i "s|^OWNER_ID=.*|OWNER_ID=$NEW_OWNER|" "$INSTALL_DIR/.env"
        else
            echo "OWNER_ID=$NEW_OWNER" >> "$INSTALL_DIR/.env"
        fi
    fi

    echo -e "${GREEN}$(t saved_restarting)${RESET}"
    sudo systemctl restart "$SERVICE_NAME"
}

# ---------------------------------------------------------------------------
# Tune nginx for real production traffic. VPN config domains on this box can
# see thousands of concurrent connections; Ubuntu's stock nginx.conf ships
# with worker_connections=768, which is nowhere near enough. That limit is
# shared across ALL vhosts on the same nginx process, so once it's hit,
# EVERY domain on the box - including the Mini App / Admin Panel domains -
# starts failing (TLS handshake errors like Cloudflare 525, refused
# connections, etc), not just the busy one. Idempotent: safe to call every
# time nginx is installed/updated.
# تنظیم nginx برای ترافیک واقعی. دامنه‌های کانفیگ VPN روی این سرور می‌تونن
# هزاران کانکشن همزمان داشته باشن؛ nginx پیش‌فرض اوبونتو با
# worker_connections=768 میاد که اصلاً کافی نیست. چون این سقف بین همه‌ی
# دامنه‌های همون nginx مشترکه، وقتی پر بشه همه‌ی دامنه‌ها -از جمله دامنه‌های
# مینی‌اپ/پنل مدیریت- شروع به خطا دادن می‌کنن (مثل خطای 525 در Cloudflare یا
# رد اتصال)، نه فقط اون دامنه‌ی پرترافیک. idempotent است؛ هر بار nginx نصب/
# آپدیت بشه بی‌خطر صدا زده می‌شود.
# ---------------------------------------------------------------------------
tune_nginx_for_scale() {
    [ -f /etc/nginx/nginx.conf ] || return

    if grep -q '^worker_processes' /etc/nginx/nginx.conf; then
        sudo sed -i 's/^worker_processes.*/worker_processes auto;/' /etc/nginx/nginx.conf
    else
        sudo sed -i '1i worker_processes auto;' /etc/nginx/nginx.conf
    fi

    if grep -q '^worker_rlimit_nofile' /etc/nginx/nginx.conf; then
        sudo sed -i 's/^worker_rlimit_nofile.*/worker_rlimit_nofile 65535;/' /etc/nginx/nginx.conf
    else
        sudo sed -i '/^worker_processes/a worker_rlimit_nofile 65535;' /etc/nginx/nginx.conf
    fi

    if grep -q 'worker_connections' /etc/nginx/nginx.conf; then
        sudo sed -i 's/worker_connections[[:space:]]*[0-9]*;/worker_connections 8192;/' /etc/nginx/nginx.conf
    fi

    # Raise the systemd-level open-file limit too (worker_rlimit_nofile above
    # is capped by this), so the higher nginx.conf value actually takes effect.
    sudo mkdir -p /etc/systemd/system/nginx.service.d
    sudo bash -c 'cat > /etc/systemd/system/nginx.service.d/override.conf' <<'NGINXOVERRIDE'
[Service]
LimitNOFILE=65535
NGINXOVERRIDE

    sudo systemctl daemon-reload
    if sudo nginx -t > /dev/null 2>&1; then
        sudo systemctl reload nginx 2>/dev/null || sudo systemctl restart nginx 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# Action: switch the bot between Polling and Webhook mode
# عملیات: تغییر حالت دریافت آپدیت بات بین Polling و Webhook
# ---------------------------------------------------------------------------
setup_bot_mode() {
    CUR_MODE=$(grep "^BOT_MODE=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d '=' -f2)
    CUR_MODE="${CUR_MODE:-polling}"
    echo -e "${CYAN}$(t current_bot_mode "$CUR_MODE")${RESET}"
    echo ""
    echo "  1) Polling"
    echo "  2) Webhook"
    read -rp "$(t choose_bot_mode)" MODE_CHOICE

    if [ "$MODE_CHOICE" = "1" ]; then
        if grep -q "^BOT_MODE=" "$INSTALL_DIR/.env" 2>/dev/null; then
            sed -i "s|^BOT_MODE=.*|BOT_MODE=polling|" "$INSTALL_DIR/.env"
        else
            echo "BOT_MODE=polling" >> "$INSTALL_DIR/.env"
        fi
        sudo systemctl restart "$SERVICE_NAME"
        echo -e "${GREEN}$(t bot_mode_set_polling)${RESET}"
        return
    elif [ "$MODE_CHOICE" != "2" ]; then
        echo -e "${RED}$(t invalid_choice)${RESET}"
        return
    fi

    read -rp "$(t prompt_domain_webhook)" DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}$(t domain_empty)${RESET}"
        return
    fi

    echo -e "${CYAN}$(t checking_dns)${RESET}"
    SERVER_IP=$(curl -fsSL ifconfig.me || echo "")
    DOMAIN_IP=$(getent ahosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
        echo -e "${YELLOW}$(t dns_mismatch_warn "$SERVER_IP" "$DOMAIN_IP")${RESET}"
        read -rp "$(t continue_prompt)" CONT
        [ "$CONT" != "yes" ] && return
    fi

    echo -e "${CYAN}$(t installing_nginx)${RESET}"
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
    timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 \
        apt-get install -y -qq nginx certbot python3-certbot-nginx > /dev/null
    tune_nginx_for_scale

    WEBHOOK_PORT=$(grep "^WEBHOOK_LISTEN_PORT=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d '=' -f2)
    WEBHOOK_PORT="${WEBHOOK_PORT:-8010}"

    echo -e "${CYAN}$(t configuring_nginx "$DOMAIN")${RESET}"
    sudo bash -c "cat > /etc/nginx/sites-available/${DOMAIN}.conf" <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$WEBHOOK_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
    if ! sudo nginx -t > /dev/null 2>&1; then
        echo -e "${RED}$(t nginx_error "$(sudo nginx -t 2>&1)")${RESET}"
        return
    fi
    sudo systemctl reload nginx

    echo -e "${CYAN}$(t getting_ssl)${RESET}"
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email --redirect
    if [ $? -ne 0 ]; then
        echo -e "${RED}$(t ssl_failed)${RESET}"
        return
    fi

    WEBHOOK_SECRET_VAL=$(grep "^WEBHOOK_SECRET=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d '=' -f2)
    [ -z "$WEBHOOK_SECRET_VAL" ] && WEBHOOK_SECRET_VAL=$(python3 -c "import secrets; print(secrets.token_hex(24))")

    for KV in "BOT_MODE=webhook" "WEBHOOK_BASE_URL=https://$DOMAIN" "WEBHOOK_SECRET=$WEBHOOK_SECRET_VAL" \
              "WEBHOOK_LISTEN_HOST=127.0.0.1" "WEBHOOK_LISTEN_PORT=$WEBHOOK_PORT"; do
        KEY="${KV%%=*}"
        if grep -q "^${KEY}=" "$INSTALL_DIR/.env" 2>/dev/null; then
            sed -i "s|^${KEY}=.*|${KV}|" "$INSTALL_DIR/.env"
        else
            echo "$KV" >> "$INSTALL_DIR/.env"
        fi
    done

    sudo systemctl restart "$SERVICE_NAME"
    echo -e "${GREEN}${BOLD}$(t bot_mode_set_webhook "https://$DOMAIN")${RESET}"
}

# ---------------------------------------------------------------------------
# Action: full Mini App setup (domain + SSL + nginx + service, all automatic)
# عملیات: نصب/تنظیم کامل مینی‌اپ (دامنه + SSL + nginx + سرویس، همه خودکار)
# ---------------------------------------------------------------------------
setup_miniapp() {
    if [ ! -d "$INSTALL_DIR/miniapp" ]; then
        echo -e "${RED}$(t miniapp_dir_missing)${RESET}"
        return
    fi

    read -rp "$(t prompt_domain_miniapp)" DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}$(t domain_empty)${RESET}"
        return
    fi

    echo -e "${CYAN}$(t checking_dns)${RESET}"
    SERVER_IP=$(curl -fsSL ifconfig.me || echo "")
    DOMAIN_IP=$(getent ahosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
        echo -e "${YELLOW}$(t dns_mismatch_warn "$SERVER_IP" "$DOMAIN_IP")${RESET}"
        read -rp "$(t continue_prompt)" CONT
        [ "$CONT" != "yes" ] && return
    fi

    echo -e "${CYAN}$(t installing_nginx)${RESET}"
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
    timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 \
        apt-get install -y -qq nginx certbot python3-certbot-nginx > /dev/null
    tune_nginx_for_scale

    echo -e "${CYAN}$(t installing_miniapp_pkgs)${RESET}"
    cd "$INSTALL_DIR"
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate

    echo -e "${CYAN}$(t creating_miniapp_service)${RESET}"
    MINIAPP_SERVICE="${SERVICE_NAME}-miniapp"
    sudo bash -c "cat > /etc/systemd/system/${MINIAPP_SERVICE}.service" <<EOF
[Unit]
Description=V2Ray Mini App Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/uvicorn miniapp.server:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable "$MINIAPP_SERVICE" > /dev/null 2>&1
    sudo systemctl restart "$MINIAPP_SERVICE"

    echo -e "${CYAN}$(t configuring_nginx "$DOMAIN")${RESET}"
    sudo bash -c "cat > /etc/nginx/sites-available/${DOMAIN}.conf" <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
    if ! sudo nginx -t > /dev/null 2>&1; then
        echo -e "${RED}$(t nginx_error "$(sudo nginx -t 2>&1)")${RESET}"
        return
    fi
    sudo systemctl reload nginx

    echo -e "${CYAN}$(t getting_ssl)${RESET}"
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email --redirect
    if [ $? -ne 0 ]; then
        echo -e "${RED}$(t ssl_failed)${RESET}"
        return
    fi

    echo -e "${CYAN}$(t saving_miniapp_url)${RESET}"
    if grep -q "^MINIAPP_URL=" "$INSTALL_DIR/.env" 2>/dev/null; then
        sed -i "s|^MINIAPP_URL=.*|MINIAPP_URL=https://$DOMAIN|" "$INSTALL_DIR/.env"
    else
        echo "MINIAPP_URL=https://$DOMAIN" >> "$INSTALL_DIR/.env"
    fi

    sudo systemctl restart "$SERVICE_NAME"

    echo -e "${GREEN}${BOLD}$(t miniapp_ready "https://$DOMAIN")${RESET}"
    echo -e "${GREEN}$(t miniapp_button_hint)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: full Mini App removal / عملیات: حذف کامل مینی‌اپ
# ---------------------------------------------------------------------------
remove_miniapp() {
    echo -e "${RED}${BOLD}$(t remove_miniapp_warn)${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }

    MINIAPP_SERVICE="${SERVICE_NAME}-miniapp"
    sudo systemctl stop "$MINIAPP_SERVICE" 2>/dev/null || true
    sudo systemctl disable "$MINIAPP_SERVICE" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${MINIAPP_SERVICE}.service"
    sudo systemctl daemon-reload

    read -rp "$(t prompt_domain_used_miniapp)" DOMAIN
    if [ -n "$DOMAIN" ]; then
        sudo rm -f "/etc/nginx/sites-enabled/${DOMAIN}.conf" "/etc/nginx/sites-available/${DOMAIN}.conf"
        sudo systemctl reload nginx 2>/dev/null || true
    fi

    if grep -q "^MINIAPP_URL=" "$INSTALL_DIR/.env" 2>/dev/null; then
        sed -i "/^MINIAPP_URL=/d" "$INSTALL_DIR/.env"
    fi
    sudo systemctl restart "$SERVICE_NAME" 2>/dev/null || true
    echo -e "${GREEN}$(t miniapp_removed)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: full standalone admin panel setup (domain + SSL + nginx + service)
# عملیات: نصب/تنظیم کامل پنل مدیریت وب مستقل (دامنه + SSL + nginx + سرویس)
# ---------------------------------------------------------------------------
setup_admin_panel() {
    if [ ! -d "$INSTALL_DIR/admin_panel" ]; then
        echo -e "${RED}$(t panel_dir_missing)${RESET}"
        return
    fi

    read -rp "$(t prompt_domain_panel)" DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}$(t domain_empty)${RESET}"
        return
    fi

    echo -e "${CYAN}$(t checking_dns)${RESET}"
    SERVER_IP=$(curl -fsSL ifconfig.me || echo "")
    DOMAIN_IP=$(getent ahosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
        echo -e "${YELLOW}$(t dns_mismatch_warn "$SERVER_IP" "$DOMAIN_IP")${RESET}"
        read -rp "$(t continue_prompt)" CONT
        [ "$CONT" != "yes" ] && return
    fi

    echo -e "${CYAN}$(t installing_nginx)${RESET}"
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
    timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 \
        apt-get install -y -qq nginx certbot python3-certbot-nginx > /dev/null
    tune_nginx_for_scale

    echo -e "${CYAN}$(t installing_panel_pkgs)${RESET}"
    cd "$INSTALL_DIR"
    source venv/bin/activate
    pip install -r requirements.txt --quiet

    if ! grep -q "^ADMIN_PANEL_SECRET=" "$INSTALL_DIR/.env" 2>/dev/null; then
        echo "ADMIN_PANEL_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> "$INSTALL_DIR/.env"
    fi

    # Save the final panel address (over https, once SSL is on) in .env so
    # the main bot can build activation links for full reseller web panels,
    # and so that re-running this on the same domain cleanly replaces the
    # previous value.
    if grep -q "^ADMIN_PANEL_URL=" "$INSTALL_DIR/.env" 2>/dev/null; then
        sudo sed -i "s#^ADMIN_PANEL_URL=.*#ADMIN_PANEL_URL=https://$DOMAIN#" "$INSTALL_DIR/.env"
    else
        echo "ADMIN_PANEL_URL=https://$DOMAIN" >> "$INSTALL_DIR/.env"
    fi

    echo ""
    echo -e "${YELLOW}${BOLD}$(t enter_owner_account)${RESET}"
    read -rp "$(t prompt_username)" PANEL_USER
    read -rsp "$(t prompt_password)" PANEL_PASS
    echo ""
    python3 -m admin_panel.create_admin "$PANEL_USER" "$PANEL_PASS"
    deactivate

    echo -e "${CYAN}$(t creating_panel_service)${RESET}"
    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    sudo bash -c "cat > /etc/systemd/system/${PANEL_SERVICE}.service" <<EOF
[Unit]
Description=ShopVPN Standalone Admin Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/uvicorn admin_panel.server:app --host 127.0.0.1 --port 8002
Restart=always
RestartSec=5
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable "$PANEL_SERVICE" > /dev/null 2>&1
    sudo systemctl restart "$PANEL_SERVICE"

    echo -e "${CYAN}$(t configuring_nginx "$DOMAIN")${RESET}"
    sudo bash -c "cat > /etc/nginx/sites-available/${DOMAIN}.conf" <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
    if ! sudo nginx -t > /dev/null 2>&1; then
        echo -e "${RED}$(t nginx_error "$(sudo nginx -t 2>&1)")${RESET}"
        return
    fi
    sudo systemctl reload nginx

    echo -e "${CYAN}$(t getting_ssl)${RESET}"
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email --redirect
    if [ $? -ne 0 ]; then
        echo -e "${RED}$(t ssl_failed)${RESET}"
        return
    fi

    echo -e "${GREEN}${BOLD}$(t panel_ready "https://$DOMAIN")${RESET}"
    echo -e "${GREEN}$(t panel_login_hint)${RESET}"

    echo -e "${CYAN}$(t restarting_bot_for_panel_url)${RESET}"
    sudo systemctl restart "$SERVICE_NAME" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Action: update standalone admin panel / عملیات: آپدیت پنل مدیریت وب مستقل
# ---------------------------------------------------------------------------
update_admin_panel() {
    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    if ! systemctl list-units --full -all | grep -q "${PANEL_SERVICE}.service"; then
        echo -e "${RED}$(t panel_not_installed_yet)${RESET}"
        return
    fi
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        echo -e "${RED}$(t bot_not_installed)${RESET}"
        return
    fi
    cd "$INSTALL_DIR"

    local failed=0
    section_header "$(t update_panel_header)"
    run_step 1 3 "$(t fetching_latest)" fetch_project_code "$INSTALL_DIR" || failed=1
    run_step 2 3 "$(t updating_packages)" bash -c "source '$INSTALL_DIR/venv/bin/activate' && pip install -r requirements.txt --quiet && deactivate" || failed=1
    run_step 3 3 "$(t restarting_panel_service)" bash -c "sudo systemctl restart '$PANEL_SERVICE' && sleep 2" || failed=1

    draw_rule
    if [ "$failed" = "0" ] && systemctl is-active --quiet "$PANEL_SERVICE"; then
        echo -e "  ${GREEN}${BOLD}$(t panel_update_done)${RESET}"
    else
        echo -e "  ${RED}$(t install_failed "$PANEL_SERVICE")${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Action: change an existing admin panel account's username/password
# عملیات: تغییر یوزرنیم/پسورد یکی از حساب‌های موجود پنل مدیریت وب
# ---------------------------------------------------------------------------
change_admin_panel_credentials() {
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        echo -e "${RED}$(t bot_not_installed)${RESET}"
        return
    fi
    if [ ! -d "$INSTALL_DIR/admin_panel" ]; then
        echo -e "${RED}$(t panel_dir_missing)${RESET}"
        return
    fi

    cd "$INSTALL_DIR"
    source venv/bin/activate

    local EXISTING_ADMINS
    EXISTING_ADMINS=$(python3 -c "
from config import DB_PATH
from database import Database
db = Database(DB_PATH)
for r in db.list_web_admins():
    print(f\"  - {r['username']} ({r['role']})\")
" 2>/dev/null)

    if [ -z "$EXISTING_ADMINS" ]; then
        echo -e "${RED}$(t no_panel_admins_found)${RESET}"
        deactivate
        return
    fi

    echo -e "${CYAN}$(t existing_admins_header)${RESET}"
    echo "$EXISTING_ADMINS"
    echo ""

    read -rp "$(t prompt_current_username)" CUR_USER
    read -rp "$(t prompt_new_username)" NEW_USER
    [ -z "$NEW_USER" ] && NEW_USER="$CUR_USER"
    read -rsp "$(t prompt_new_password)" NEW_PASS
    echo ""

    if [ -z "$CUR_USER" ] || [ -z "$NEW_PASS" ]; then
        echo -e "${RED}$(t change_admin_creds_cancelled)${RESET}"
        deactivate
        return
    fi

    python3 -m change_admin "$CUR_USER" "$NEW_USER" "$NEW_PASS"
    deactivate
}

# ---------------------------------------------------------------------------
# Action: full standalone admin panel removal
# عملیات: حذف کامل پنل مدیریت وب مستقل
# ---------------------------------------------------------------------------
remove_admin_panel() {
    echo -e "${RED}${BOLD}$(t remove_panel_warn)${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }

    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    sudo systemctl stop "$PANEL_SERVICE" 2>/dev/null || true
    sudo systemctl disable "$PANEL_SERVICE" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${PANEL_SERVICE}.service"
    sudo systemctl daemon-reload

    read -rp "$(t prompt_domain_used_panel)" DOMAIN
    if [ -n "$DOMAIN" ]; then
        sudo rm -f "/etc/nginx/sites-enabled/${DOMAIN}.conf" "/etc/nginx/sites-available/${DOMAIN}.conf"
        sudo systemctl reload nginx 2>/dev/null || true
    fi
    echo -e "${GREEN}$(t panel_removed)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: reverse-proxy a domain (with SSL) to any locally/remotely running
# VPN panel (Hiddify, Marzban, Marzneshin, 3X-UI, PasarGuard, ...), so it can
# share port 443 with the mini-app / admin panel via nginx SNI vhosts.
# عملیات: پروکسی یک دامنه (با SSL) به هر پنل VPN (Hiddify, Marzban,
# Marzneshin, 3X-UI, PasarGuard و ...) تا پورت 443 را با مینی‌اپ/پنل مدیریت
# از طریق vhost‌های nginx به اشتراک بگذارد.
# ---------------------------------------------------------------------------
setup_panel_proxy() {
    read -rp "$(t prompt_domain_panel_proxy)" DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}$(t domain_empty)${RESET}"
        return
    fi

    read -rp "$(t prompt_backend_address)" BACKEND
    if [ -z "$BACKEND" ]; then
        echo -e "${RED}$(t backend_address_empty)${RESET}"
        return
    fi

    read -rp "$(t prompt_backend_https)" BACKEND_HTTPS
    if [[ "$BACKEND_HTTPS" == "yes" ]]; then
        BACKEND_SCHEME="https"
    else
        BACKEND_SCHEME="http"
    fi

    read -rp "$(t prompt_backend_path)" BACKEND_PATH
    if [ -z "$BACKEND_PATH" ]; then
        BACKEND_PATH="/"
    fi
    # normalize: must start with / and must NOT end with / (unless it's root "/")
    [[ "$BACKEND_PATH" != /* ]] && BACKEND_PATH="/$BACKEND_PATH"
    if [ "$BACKEND_PATH" != "/" ]; then
        BACKEND_PATH="${BACKEND_PATH%/}"
    fi

    echo -e "${CYAN}$(t checking_dns)${RESET}"
    SERVER_IP=$(curl -fsSL ifconfig.me || echo "")
    DOMAIN_IP=$(getent ahosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
        echo -e "${YELLOW}$(t dns_mismatch_warn "$SERVER_IP" "$DOMAIN_IP")${RESET}"
        read -rp "$(t continue_prompt)" CONT
        [ "$CONT" != "yes" ] && return
    fi

    echo -e "${CYAN}$(t installing_nginx)${RESET}"
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
    timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 \
        apt-get install -y -qq nginx certbot python3-certbot-nginx > /dev/null
    tune_nginx_for_scale

    # Guard: never silently overwrite an nginx config that this menu did not
    # create itself (e.g. the Mini App / Admin Panel domain config), which
    # would otherwise take down those services.
    # گارد: هیچ‌وقت کانفیگی که خودِ این منو نساخته (مثلاً کانفیگ دامنه
    # مینی‌اپ/پنل مدیریت) را بی‌سروصدا overwrite نکن، چون باعث از دسترس خارج
    # شدن آن سرویس‌ها می‌شود.
    EXISTING_CONF="/etc/nginx/sites-available/${DOMAIN}.conf"
    if sudo test -f "$EXISTING_CONF" && ! sudo grep -q "^# managed-by-shopvpn-panel-proxy$" "$EXISTING_CONF" 2>/dev/null; then
        echo -e "${RED}$(t panel_proxy_domain_conflict "$DOMAIN")${RESET}"
        return
    fi

    echo -e "${CYAN}$(t configuring_nginx "$DOMAIN")${RESET}"
    if [ "$BACKEND_SCHEME" == "https" ]; then
        SSL_PROXY_LINES="        proxy_ssl_verify off;
        proxy_ssl_server_name on;"
    else
        SSL_PROXY_LINES=""
    fi
    sudo bash -c "cat > /etc/nginx/sites-available/${DOMAIN}.conf" <<EOF
# managed-by-shopvpn-panel-proxy
# backend: ${BACKEND_SCHEME}://${BACKEND}${BACKEND_PATH}
server {
    listen 80;
    server_name $DOMAIN;

    location ${BACKEND_PATH} {
        proxy_pass ${BACKEND_SCHEME}://${BACKEND};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
${SSL_PROXY_LINES}
    }
}
EOF
    sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
    if ! sudo nginx -t > /dev/null 2>&1; then
        echo -e "${RED}$(t nginx_error "$(sudo nginx -t 2>&1)")${RESET}"
        return
    fi
    sudo systemctl reload nginx

    echo -e "${CYAN}$(t getting_ssl)${RESET}"
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email --redirect
    if [ $? -ne 0 ]; then
        echo -e "${RED}$(t ssl_failed)${RESET}"
        return
    fi

    echo -e "${YELLOW}$(t panel_proxy_note)${RESET}"
    echo -e "${GREEN}${BOLD}$(t panel_proxy_ready "https://${DOMAIN}${BACKEND_PATH}")${RESET}"
}

# ---------------------------------------------------------------------------
# Action: remove a VPN panel domain proxy
# عملیات: حذف دامنه پروکسی پنل VPN
# ---------------------------------------------------------------------------
remove_panel_proxy() {
    echo -e "${RED}${BOLD}$(t remove_panel_proxy_warn)${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }

    read -rp "$(t prompt_domain_used_panel_proxy)" DOMAIN
    if [ -n "$DOMAIN" ]; then
        sudo rm -f "/etc/nginx/sites-enabled/${DOMAIN}.conf" "/etc/nginx/sites-available/${DOMAIN}.conf"
        sudo systemctl reload nginx 2>/dev/null || true
    fi
    echo -e "${GREEN}$(t panel_proxy_removed)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: list all panel/config domain proxies set up via option 17
# عملیات: نمایش لیست پروکسی‌های دامنه‌ای که با گزینه ۱۷ ساخته شده‌اند
# ---------------------------------------------------------------------------
list_panel_proxies() {
    local found=0

    echo -e "${CYAN}${BOLD}$(t panel_proxy_list_header)${RESET}"
    echo ""

    for conf in /etc/nginx/sites-available/*.conf; do
        [ -e "$conf" ] || continue
        grep -q "^# managed-by-shopvpn-panel-proxy$" "$conf" 2>/dev/null || continue
        found=1

        local domain backend path enabled_state ssl_state cert_file expiry
        domain=$(basename "$conf" .conf)
        backend=$(grep -m1 "^# backend:" "$conf" | sed 's/^# backend: *//')
        path=$(grep -m1 "location " "$conf" | awk '{print $2}')

        if [ -L "/etc/nginx/sites-enabled/$(basename "$conf")" ]; then
            enabled_state="$(t panel_proxy_list_enabled)"
        else
            enabled_state="$(t panel_proxy_list_disabled)"
        fi

        cert_file="/etc/letsencrypt/live/${domain}/fullchain.pem"
        if [ -f "$cert_file" ]; then
            expiry=$(sudo openssl x509 -enddate -noout -in "$cert_file" 2>/dev/null | cut -d= -f2)
            ssl_state="$(t panel_proxy_list_ssl_ok "$expiry")"
        else
            ssl_state="$(t panel_proxy_list_ssl_missing)"
        fi

        echo -e "  ${GREEN}${BOLD}${domain}${RESET}"
        echo -e "    → backend: ${backend:-?}"
        echo -e "    → path:    ${path:-/}"
        echo -e "    → nginx:   ${enabled_state}"
        echo -e "    → SSL:     ${ssl_state}"
        echo ""
    done

    if [ "$found" -eq 0 ]; then
        echo -e "${YELLOW}$(t panel_proxy_list_empty)${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Action: list domains currently registered for the Mini App and for the
# standalone Admin Panel (read from MINIAPP_URL / ADMIN_PANEL_URL in .env),
# and let the user pick one to delete (removes only its nginx site + SSL
# cert; the underlying systemd service is left running).
# عملیات: نمایش دامنه‌های فعلی مینی‌اپ و پنل مدیریت وب (از .env) و امکان
# حذف یکی از آن‌ها (فقط nginx و SSL، بدون خاموش کردن سرویس).
# ---------------------------------------------------------------------------
list_service_domains() {
    local ENV_FILE="$INSTALL_DIR/.env"
    local miniapp_domain="" admin_domain=""

    if [ -f "$ENV_FILE" ]; then
        miniapp_domain=$(grep -m1 "^MINIAPP_URL=" "$ENV_FILE" | cut -d= -f2- | sed -E 's#^https?://##; s#/+$##')
        admin_domain=$(grep -m1 "^ADMIN_PANEL_URL=" "$ENV_FILE" | cut -d= -f2- | sed -E 's#^https?://##; s#/+$##')
    fi

    if [ -z "$miniapp_domain" ] && [ -z "$admin_domain" ]; then
        echo -e "${YELLOW}$(t service_domains_empty)${RESET}"
        return
    fi

    echo -e "${CYAN}${BOLD}$(t service_domains_header)${RESET}"
    echo ""

    local -a ENTRY_LABEL ENTRY_DOMAIN ENTRY_ENVKEY
    local idx=0
    if [ -n "$miniapp_domain" ]; then
        idx=$((idx + 1))
        ENTRY_LABEL[$idx]="$(t service_domains_miniapp_label)"
        ENTRY_DOMAIN[$idx]="$miniapp_domain"
        ENTRY_ENVKEY[$idx]="MINIAPP_URL"
    fi
    if [ -n "$admin_domain" ]; then
        idx=$((idx + 1))
        ENTRY_LABEL[$idx]="$(t service_domains_panel_label)"
        ENTRY_DOMAIN[$idx]="$admin_domain"
        ENTRY_ENVKEY[$idx]="ADMIN_PANEL_URL"
    fi

    local i
    for ((i = 1; i <= idx; i++)); do
        local domain="${ENTRY_DOMAIN[$i]}" enabled_state ssl_state cert_file expiry
        if [ -L "/etc/nginx/sites-enabled/${domain}.conf" ]; then
            enabled_state="$(t panel_proxy_list_enabled)"
        else
            enabled_state="$(t panel_proxy_list_disabled)"
        fi

        cert_file="/etc/letsencrypt/live/${domain}/fullchain.pem"
        if [ -f "$cert_file" ]; then
            expiry=$(sudo openssl x509 -enddate -noout -in "$cert_file" 2>/dev/null | cut -d= -f2)
            ssl_state="$(t panel_proxy_list_ssl_ok "$expiry")"
        else
            ssl_state="$(t panel_proxy_list_ssl_missing)"
        fi

        echo -e "  ${YELLOW}[$i]${RESET} ${GREEN}${BOLD}${ENTRY_LABEL[$i]}${RESET}: ${domain}"
        echo -e "      → nginx: ${enabled_state}"
        echo -e "      → SSL:   ${ssl_state}"
        echo ""
    done

    read -rp "$(t service_domains_delete_prompt)" CHOICE
    [ -z "$CHOICE" ] && return
    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]] || [ "$CHOICE" -lt 1 ] || [ "$CHOICE" -gt "$idx" ]; then
        echo -e "${RED}$(t invalid_choice)${RESET}"
        return
    fi

    local sel_domain="${ENTRY_DOMAIN[$CHOICE]}" sel_envkey="${ENTRY_ENVKEY[$CHOICE]}" sel_label="${ENTRY_LABEL[$CHOICE]}"
    echo -e "${RED}${BOLD}$(t service_domains_delete_warn "$sel_label" "$sel_domain")${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }

    sudo rm -f "/etc/nginx/sites-enabled/${sel_domain}.conf" "/etc/nginx/sites-available/${sel_domain}.conf"
    sudo systemctl reload nginx 2>/dev/null || true

    if [ -f "$ENV_FILE" ] && grep -q "^${sel_envkey}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "/^${sel_envkey}=/d" "$ENV_FILE"
    fi
    sudo systemctl restart "$SERVICE_NAME" 2>/dev/null || true

    echo -e "${GREEN}$(t service_domains_deleted)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: auto-generate VAPID keys for admin panel push notifications
# عملیات: ساخت خودکار کلیدهای VAPID برای اعلان Push پنل مدیریت وب
# ---------------------------------------------------------------------------
setup_vapid_keys() {
    if [ ! -d "$INSTALL_DIR/admin_panel" ]; then
        echo -e "${RED}$(t admin_panel_folder_missing)${RESET}"
        return
    fi

    ENV_FILE="$INSTALL_DIR/.env"
    touch "$ENV_FILE"

    if grep -q "^VAPID_PUBLIC_KEY=" "$ENV_FILE" 2>/dev/null && [ -n "$(grep '^VAPID_PUBLIC_KEY=' "$ENV_FILE" | cut -d= -f2-)" ]; then
        echo -e "${YELLOW}$(t vapid_already_set_warn1)${RESET}"
        echo -e "${YELLOW}$(t vapid_already_set_warn2)${RESET}"
        read -rp "$(t confirm_regenerate)" CONFIRM
        [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }
    fi

    echo ""
    read -rp "$(t prompt_vapid_email)" CLAIM_EMAIL
    CLAIM_EMAIL=${CLAIM_EMAIL:-admin@example.com}

    echo -e "${CYAN}$(t generating_vapid)${RESET}"
    cd "$INSTALL_DIR"
    source venv/bin/activate
    KEYS_OUTPUT=$(python3 -m admin_panel.generate_vapid_keys 2>/dev/null | grep -E "^VAPID_(PUBLIC|PRIVATE)_KEY=")
    deactivate

    VAPID_PUB=$(echo "$KEYS_OUTPUT" | grep "^VAPID_PUBLIC_KEY=" | cut -d= -f2-)
    VAPID_PRIV=$(echo "$KEYS_OUTPUT" | grep "^VAPID_PRIVATE_KEY=" | cut -d= -f2-)

    if [ -z "$VAPID_PUB" ] || [ -z "$VAPID_PRIV" ]; then
        echo -e "${RED}$(t vapid_generation_failed)${RESET}"
        return
    fi

    # Remove any previous values and append the new ones to .env
    sed -i '/^VAPID_PUBLIC_KEY=/d; /^VAPID_PRIVATE_KEY=/d; /^VAPID_CLAIM_EMAIL=/d' "$ENV_FILE"
    {
        echo "VAPID_PUBLIC_KEY=$VAPID_PUB"
        echo "VAPID_PRIVATE_KEY=$VAPID_PRIV"
        echo "VAPID_CLAIM_EMAIL=$CLAIM_EMAIL"
    } >> "$ENV_FILE"

    echo -e "${GREEN}$(t vapid_saved)${RESET}"

    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    if systemctl list-units --full -all | grep -q "${PANEL_SERVICE}.service"; then
        echo -e "${CYAN}$(t restarting_panel_service)${RESET}"
        sudo systemctl restart "$PANEL_SERVICE"
        echo -e "${GREEN}$(t panel_restarted_hint)${RESET}"
    else
        echo -e "${YELLOW}$(t panel_not_installed_vapid_hint)${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Action: restore a database backup that was already copied onto this server
# (e.g. via scp), meant for migrating an existing bot to a brand-new server.
# After the database swap, optionally walks through Mini App / Admin Panel
# domain setup again (their domain/SSL/systemd config lives in .env and
# nginx on the OLD server, NOT inside the database backup, so a fresh server
# needs it redone with a new domain).
# عملیات: بازیابی یک فایل بکاپ دیتابیس که از قبل (مثلاً با scp) روی همین
# سرور کپی شده - برای انتقال یک بات موجود به یک سرور کاملاً جدید. بعد از
# جایگزینی دیتابیس، در صورت نیاز مینی‌اپ/پنل مدیریت را هم با دامنه‌ی جدید
# دوباره راه‌اندازی می‌کند (چون تنظیمات دامنه/SSL/سرویس آن‌ها داخل .env و
# nginx سرور قبلی است، نه داخل خود فایل بکاپ، و روی سرور جدید باید با یک
# دامنه‌ی جدید از نو انجام شود).
# ---------------------------------------------------------------------------
restore_backup_cli() {
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        echo -e "${RED}$(t bot_not_installed)${RESET}"
        return
    fi
    if [ ! -x "$INSTALL_DIR/venv/bin/python3" ]; then
        echo -e "${RED}$(t venv_missing)${RESET}"
        return
    fi

    read -rp "$(t prompt_backup_path)" BACKUP_FILE
    if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
        echo -e "${RED}$(t backup_file_missing)${RESET}"
        return
    fi
    BACKUP_FILE="$(readlink -f "$BACKUP_FILE")"

    echo -e "${CYAN}$(t validating_backup)${RESET}"
    cd "$INSTALL_DIR"
    if ! venv/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from backup import is_valid_sqlite_db
sys.exit(0 if is_valid_sqlite_db(sys.argv[1]) else 1)
" "$BACKUP_FILE"; then
        echo -e "${RED}$(t backup_invalid)${RESET}"
        return
    fi

    echo -e "${YELLOW}${BOLD}$(t restore_warning)${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }

    MINIAPP_SERVICE="${SERVICE_NAME}-miniapp"
    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    MINIAPP_WAS_ACTIVE=false
    PANEL_WAS_ACTIVE=false
    systemctl is-active --quiet "$MINIAPP_SERVICE" 2>/dev/null && MINIAPP_WAS_ACTIVE=true
    systemctl is-active --quiet "$PANEL_SERVICE" 2>/dev/null && PANEL_WAS_ACTIVE=true

    echo -e "${CYAN}$(t stopping_services_for_restore)${RESET}"
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    [ "$MINIAPP_WAS_ACTIVE" = true ] && sudo systemctl stop "$MINIAPP_SERVICE" 2>/dev/null || true
    [ "$PANEL_WAS_ACTIVE" = true ] && sudo systemctl stop "$PANEL_SERVICE" 2>/dev/null || true

    echo -e "${CYAN}$(t restoring_backup)${RESET}"
    RESTORE_OUT=$(venv/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from database import Database
from backup import restore_backup
db = Database('bot_database.db')
try:
    pre = restore_backup(db, 'bot_database.db', sys.argv[1])
    print('OK:' + pre)
except Exception as e:
    print('ERR:' + str(e))
    sys.exit(1)
" "$BACKUP_FILE" 2>&1)

    if [[ "$RESTORE_OUT" != OK:* ]]; then
        echo -e "${RED}$(t restore_failed "$RESTORE_OUT")${RESET}"
        sudo systemctl start "$SERVICE_NAME" 2>/dev/null || true
        [ "$MINIAPP_WAS_ACTIVE" = true ] && sudo systemctl start "$MINIAPP_SERVICE" 2>/dev/null || true
        [ "$PANEL_WAS_ACTIVE" = true ] && sudo systemctl start "$PANEL_SERVICE" 2>/dev/null || true
        return
    fi

    echo -e "${GREEN}$(t restore_done "$(basename "${RESTORE_OUT#OK:}")")${RESET}"

    echo -e "${CYAN}$(t restarting_bot_service)${RESET}"
    sudo systemctl start "$SERVICE_NAME"
    sleep 2

    echo ""
    read -rp "$(t prompt_had_miniapp)" HAD_MINIAPP
    if [[ "$HAD_MINIAPP" =~ ^[yY]$ ]]; then
        setup_miniapp
    elif [ "$MINIAPP_WAS_ACTIVE" = true ]; then
        sudo systemctl start "$MINIAPP_SERVICE" 2>/dev/null || true
    fi

    read -rp "$(t prompt_had_panel)" HAD_PANEL
    if [[ "$HAD_PANEL" =~ ^[yY]$ ]]; then
        setup_admin_panel
    elif [ "$PANEL_WAS_ACTIVE" = true ]; then
        sudo systemctl start "$PANEL_SERVICE" 2>/dev/null || true
    fi

    echo -e "${GREEN}${BOLD}$(t restore_flow_done)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: integration API setup / update / removal (own domain + SSL + service)
# عملیات: نصب / آپدیت / حذف API یکپارچه‌سازی (دامنه‌ی جدا + SSL + سرویس)
# ---------------------------------------------------------------------------
setup_api() {
    if [ ! -d "$INSTALL_DIR/api" ]; then
        echo -e "${RED}$(t api_dir_missing)${RESET}"
        return
    fi

    read -rp "$(t prompt_domain_api)" DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}$(t domain_empty)${RESET}"
        return
    fi

    echo -e "${CYAN}$(t checking_dns)${RESET}"
    SERVER_IP=$(curl -fsSL ifconfig.me || echo "")
    DOMAIN_IP=$(getent ahosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
        echo -e "${YELLOW}$(t dns_mismatch_warn "$SERVER_IP" "$DOMAIN_IP")${RESET}"
        read -rp "$(t continue_prompt)" CONT
        [ "$CONT" != "yes" ] && return
    fi

    echo -e "${CYAN}$(t installing_nginx)${RESET}"
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
    timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 \
        apt-get install -y -qq nginx certbot python3-certbot-nginx > /dev/null
    tune_nginx_for_scale

    echo -e "${CYAN}$(t installing_miniapp_pkgs)${RESET}"
    cd "$INSTALL_DIR"
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate

    echo -e "${CYAN}$(t creating_api_service)${RESET}"
    API_SERVICE="${SERVICE_NAME}-api"
    sudo bash -c "cat > /etc/systemd/system/${API_SERVICE}.service" <<EOF
[Unit]
Description=ShopVPN Integration API
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8003 --workers 1
Restart=always
RestartSec=5
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable "$API_SERVICE" > /dev/null 2>&1
    sudo systemctl restart "$API_SERVICE"

    echo -e "${CYAN}$(t configuring_nginx "$DOMAIN")${RESET}"
    sudo bash -c "cat > /etc/nginx/sites-available/${DOMAIN}.conf" <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8003;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
    if ! sudo nginx -t > /dev/null 2>&1; then
        echo -e "${RED}$(t nginx_error "$(sudo nginx -t 2>&1)")${RESET}"
        return
    fi
    sudo systemctl reload nginx

    echo -e "${CYAN}$(t getting_ssl)${RESET}"
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email --redirect
    if [ $? -ne 0 ]; then
        echo -e "${RED}$(t ssl_failed)${RESET}"
        return
    fi

    echo -e "${GREEN}${BOLD}$(t api_ready "https://$DOMAIN")${RESET}"
    echo -e "${GREEN}$(t api_token_hint)${RESET}"
}

update_api() {
    API_SERVICE="${SERVICE_NAME}-api"
    if ! systemctl list-units --full -all | grep -q "${API_SERVICE}.service"; then
        echo -e "${RED}$(t api_not_installed)${RESET}"
        return
    fi
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        echo -e "${RED}$(t bot_not_installed)${RESET}"
        return
    fi
    cd "$INSTALL_DIR"

    local failed=0
    section_header "$(t update_api_header)"
    run_step 1 3 "$(t fetching_latest)" fetch_project_code "$INSTALL_DIR" || failed=1
    run_step 2 3 "$(t updating_packages)" bash -c "source '$INSTALL_DIR/venv/bin/activate' && pip install -r requirements.txt --quiet && deactivate" || failed=1
    run_step 3 3 "$(t restarting_api_service)" bash -c "sudo systemctl restart '$API_SERVICE' && sleep 2" || failed=1

    draw_rule
    if [ "$failed" = "0" ] && systemctl is-active --quiet "$API_SERVICE"; then
        echo -e "  ${GREEN}${BOLD}$(t api_update_done)${RESET}"
    else
        echo -e "  ${RED}$(t install_failed "$API_SERVICE")${RESET}"
    fi
}

remove_api() {
    echo -e "${RED}${BOLD}$(t remove_api_warn)${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }

    API_SERVICE="${SERVICE_NAME}-api"
    sudo systemctl stop "$API_SERVICE" 2>/dev/null || true
    sudo systemctl disable "$API_SERVICE" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${API_SERVICE}.service"
    sudo systemctl daemon-reload

    read -rp "$(t prompt_domain_used_api)" DOMAIN
    if [ -n "$DOMAIN" ]; then
        sudo rm -f "/etc/nginx/sites-enabled/${DOMAIN}.conf" "/etc/nginx/sites-available/${DOMAIN}.conf"
        sudo systemctl reload nginx 2>/dev/null || true
    fi
    echo -e "${GREEN}$(t api_removed)${RESET}"
}

# ---------------------------------------------------------------------------
# Action: install/manage the project-owned local translation runtime.
# Everything is automated: Argos models + isolated LibreTranslate fallback.
# ---------------------------------------------------------------------------
LIBRETRANSLATE_SERVICE="shopvpn-libretranslate"

setup_libretranslate() {
    section_header "$(t lt_header)"
    if [ ! -f "$INSTALL_DIR/setup_local_translation.sh" ]; then
        echo -e "${RED}$(t bot_not_installed)${RESET}"
        return
    fi

    echo -e "${CYAN}🌍 Installing/repairing Argos models and the local LibreTranslate runtime...${RESET}"
    if bash "$INSTALL_DIR/setup_local_translation.sh"; then
        echo -e "${GREEN}${BOLD}$(t lt_done)${RESET}"
    else
        echo -e "${RED}$(t lt_pip_failed)${RESET}"
        return
    fi

    if [ -d "$INSTALL_DIR" ] && systemctl list-units --full -all 2>/dev/null | grep -q "${SERVICE_NAME}.service"; then
        sudo systemctl restart "$SERVICE_NAME"
    fi
}

remove_libretranslate() {
    if ! systemctl list-units --full -all 2>/dev/null | grep -q "${LIBRETRANSLATE_SERVICE}.service"; then
        echo -e "${YELLOW}$(t lt_not_installed)${RESET}"
        return
    fi

    echo -e "${RED}${BOLD}$(t lt_remove_warn)${RESET}"
    read -rp "$(t confirm_prompt)" CONFIRM
    [ "$CONFIRM" != "yes" ] && { echo -e "${YELLOW}$(t cancelled)${RESET}"; return; }

    sudo systemctl stop "$LIBRETRANSLATE_SERVICE" >/dev/null 2>&1 || true
    sudo systemctl disable "$LIBRETRANSLATE_SERVICE" >/dev/null 2>&1 || true
    sudo rm -f "/etc/systemd/system/${LIBRETRANSLATE_SERVICE}.service"
    sudo systemctl daemon-reload
    rm -rf "$INSTALL_DIR/translation-venv"

    local ENV_FILE="$INSTALL_DIR/.env"
    [ -f "$ENV_FILE" ] && sed -i '/^SHOPVPN_LIBRETRANSLATE_URL=/d' "$ENV_FILE"

    if [ -d "$INSTALL_DIR" ] && systemctl list-units --full -all 2>/dev/null | grep -q "${SERVICE_NAME}.service"; then
        sudo systemctl restart "$SERVICE_NAME"
    fi

    echo -e "${GREEN}$(t lt_removed)${RESET}"
}

# ---------------------------------------------------------------------------
# Main menu / منوی اصلی
# ---------------------------------------------------------------------------
while true; do
    print_banner
    print_status_line
    menu_section sec_setup
    menu_item 1 menu_1
    menu_item 2 menu_2
    menu_item 3 menu_3 "$RED"
    menu_section sec_service
    menu_item 4 menu_4
    menu_item 5 menu_5
    menu_item 6 menu_6
    menu_item 7 menu_7
    menu_section sec_store
    menu_item 8 menu_8
    menu_item 9 menu_9
    menu_section sec_miniapp
    menu_item 10 menu_10
    menu_item 11 menu_11 "$RED"
    menu_item 12 menu_12
    menu_section sec_panel
    menu_item 13 menu_13
    menu_item 14 menu_14 "$RED"
    menu_item 15 menu_15
    menu_item 16 menu_16
    menu_section sec_domains
    menu_item 17 menu_17
    menu_item 18 menu_18
    menu_item 19 menu_19 "$RED"
    menu_item 20 menu_20
    menu_section sec_api
    menu_item 24 menu_24
    menu_item 25 menu_25 "$RED"
    menu_item 26 menu_26
    menu_section sec_translation
    menu_item 27 menu_27
    menu_item 28 menu_28 "$RED"
    menu_section sec_advanced
    menu_item 21 menu_21
    menu_item 22 menu_22
    menu_item 23 menu_23
    draw_rule
    menu_item L menu_lang "$MAGENTA"
    menu_item 0 menu_0 "$DIM"
    draw_rule
    echo ""
    read -rp "$(echo -e ${MAGENTA}${BOLD}"  $(t enter_choice_prompt)"${RESET})" choice

    case $choice in
        1) install_bot; pause ;;
        2) update_bot; pause ;;
        12) update_miniapp; pause ;;
        3) uninstall_bot; pause ;;
        4) view_status; pause ;;
        5) view_logs ;;
        6) restart_bot; pause ;;
        7) stop_bot; pause ;;
        8) show_stats; pause ;;
        9) edit_env; pause ;;
        10) setup_miniapp; pause ;;
        11) remove_miniapp; pause ;;
        13) setup_admin_panel; pause ;;
        14) remove_admin_panel; pause ;;
        15) update_admin_panel; pause ;;
        16) setup_vapid_keys; pause ;;
        17) setup_panel_proxy; pause ;;
        18) list_panel_proxies; pause ;;
        19) remove_panel_proxy; pause ;;
        20) list_service_domains; pause ;;
        21) restore_backup_cli; pause ;;
        22) setup_bot_mode; pause ;;
        23) change_admin_panel_credentials; pause ;;
        24) setup_api; pause ;;
        25) remove_api; pause ;;
        26) update_api; pause ;;
        27) setup_libretranslate; pause ;;
        28) remove_libretranslate; pause ;;
        [Ll]) toggle_lang ;;
        0) echo -e "${CYAN}$(t goodbye)${RESET}"; exit 0 ;;
        *) echo -e "${RED}$(t invalid_choice)${RESET}"; sleep 1 ;;
    esac
done
