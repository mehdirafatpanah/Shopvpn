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
BRAND_NAME="SHOP VPN"
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
MSG_EN[system_running]="Engine Ready ✅ (Bot is running)"
MSG_FA[system_running]="آماده به کار ✅ (بات در حال اجراست)"
MSG_EN[system_stopped]="Stopped ⛔️"
MSG_FA[system_stopped]="متوقف ⛔️"
MSG_EN[service_running]="Running ✅"
MSG_FA[service_running]="در حال اجراست ✅"
MSG_EN[service_stopped]="Stopped ⛔️"
MSG_FA[service_stopped]="متوقف ⛔️"
MSG_EN[pause_prompt]="Press Enter to return to the menu..."
MSG_FA[pause_prompt]="برای بازگشت به منو، Enter را بزن..."

# ensure_figlet
MSG_EN[preparing_font]="🔤 Preparing display font (first time only, a few seconds)..."
MSG_FA[preparing_font]="🔤 در حال آماده‌سازی فونت نمایش (فقط بار اول، چند ثانیه طول می‌کشد)..."
MSG_EN[figlet_failed]="⚠️ figlet installation failed, showing a simple banner instead."
MSG_FA[figlet_failed]="⚠️ نصب figlet انجام نشد، بنر ساده نمایش داده می‌شود."

# install_bot
MSG_EN[installing_prereqs]="📦 Checking and installing prerequisites (git, python3, pip, venv, figlet)..."
MSG_FA[installing_prereqs]="📦 بررسی و نصب پیش‌نیازها (git, python3, pip, venv, figlet)..."
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
MSG_EN[fetching_latest]="🔄 Fetching the latest changes from GitHub..."
MSG_FA[fetching_latest]="🔄 دریافت آخرین تغییرات از گیت‌هاب..."
MSG_EN[updating_packages]="🐍 Updating packages..."
MSG_FA[updating_packages]="🐍 آپدیت پکیج‌ها..."
MSG_EN[restarting_bot_service]="♻️ Restarting the bot service..."
MSG_FA[restarting_bot_service]="♻️ ری‌استارت سرویس بات..."
MSG_EN[update_done]="✅ Bot updated."
MSG_FA[update_done]="✅ آپدیت بات انجام شد."
MSG_EN[miniapp_not_installed]="⛔️ Mini App not installed yet. Run option 10 (setup Mini App) first."
MSG_FA[miniapp_not_installed]="⛔️ مینی‌اپ هنوز نصب نشده. اول گزینه ۱۰ (نصب/تنظیم مینی‌اپ) را بزن."
MSG_EN[restarting_miniapp_service]="♻️ Restarting the Mini App service..."
MSG_FA[restarting_miniapp_service]="♻️ ری‌استارت سرویس مینی‌اپ..."
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
MSG_EN[restarting_panel_service]="♻️ Restarting the admin panel service..."
MSG_FA[restarting_panel_service]="♻️ ری‌استارت سرویس پنل مدیریت..."
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
MSG_EN[menu_13]="Setup standalone admin panel (auto: domain + SSL + service)"
MSG_FA[menu_13]="نصب/تنظیم پنل مدیریت وب مستقل (خودکار: دامنه + SSL + سرویس)"
MSG_EN[menu_14]="Remove admin panel"
MSG_FA[menu_14]="حذف پنل مدیریت وب"
MSG_EN[menu_15]="Update admin panel"
MSG_FA[menu_15]="آپدیت پنل مدیریت وب"
MSG_EN[menu_16]="Auto-generate VAPID key (admin panel push notifications)"
MSG_FA[menu_16]="ساخت خودکار کلید VAPID (اعلان Push پنل مدیریت)"
MSG_EN[menu_17]="Add domain proxy for VPN panel (share port 443)"
MSG_FA[menu_17]="افزودن دامنه پروکسی برای پنل VPN (اشتراک پورت 443)"
MSG_EN[menu_18]="List panel/config domain proxies (info on existing ones)"
MSG_FA[menu_18]="نمایش لیست پروکسی‌های دامنه پنل/کانفیگ (اطلاعات کانفیگ‌های موجود)"
MSG_EN[menu_19]="Remove VPN panel domain proxy"
MSG_FA[menu_19]="حذف دامنه پروکسی پنل VPN"
MSG_EN[menu_20]="Mini App / Admin Panel domains (view + delete)"
MSG_FA[menu_20]="دامنه‌های مینی‌اپ / پنل مدیریت (نمایش + حذف)"
MSG_EN[menu_lang]="Language / زبان (English ⇄ فارسی)"
MSG_FA[menu_lang]="Language / زبان (English ⇄ فارسی)"
MSG_EN[menu_0]="Exit"
MSG_FA[menu_0]="خروج"
MSG_EN[enter_choice_prompt]="Enter choice [0-20, L]: "
MSG_FA[enter_choice_prompt]="یک گزینه انتخاب کن [0-20, L]: "
MSG_EN[invalid_choice]="Invalid option."
MSG_FA[invalid_choice]="گزینه نامعتبر است."
MSG_EN[goodbye]="Goodbye 👋"
MSG_FA[goodbye]="خدانگهدار 👋"

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
ensure_figlet() {
    if ! command -v figlet &> /dev/null; then
        echo -e "${CYAN}$(t preparing_font)${RESET}"
        sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
        timeout 60 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get install -y -qq figlet
        if ! command -v figlet &> /dev/null; then
            echo -e "${YELLOW}$(t figlet_failed)${RESET}"
            sleep 1
        fi
    fi
}

print_banner() {
    clear
    echo -e "${MAGENTA}╔══════════════════════════════════════════════════════════╗${RESET}"
    if command -v figlet &> /dev/null; then
        echo -e "${CYAN}${BOLD}$(figlet -f standard "$BRAND_NAME" 2>/dev/null)${RESET}"
    else
        echo -e "${CYAN}${BOLD}                     $BRAND_NAME${RESET}"
    fi
    echo -e "${YELLOW}                 B O T   M A N A G E M E N T   E N G I N E   $(get_version)${RESET}"
    echo -e "${MAGENTA}╚══════════════════════════════════════════════════════════╝${RESET}"
    echo ""
}

print_status_line() {
    if [ ! -d "$INSTALL_DIR" ]; then
        echo -e "System Status: ${YELLOW}$(t not_installed)${RESET}"
    elif systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo -e "System Status: ${GREEN}${BOLD}$(t system_running)${RESET}"
    else
        echo -e "System Status: ${RED}${BOLD}$(t system_stopped)${RESET}"
    fi

    MINIAPP_SERVICE="${SERVICE_NAME}-miniapp"
    if systemctl list-units --type=service --all 2>/dev/null | grep -q "${MINIAPP_SERVICE}.service"; then
        if systemctl is-active --quiet "$MINIAPP_SERVICE" 2>/dev/null; then
            echo -e "Mini App Status: ${GREEN}${BOLD}$(t service_running)${RESET}"
        else
            echo -e "Mini App Status: ${RED}${BOLD}$(t service_stopped)${RESET}"
        fi
    else
        echo -e "Mini App Status: ${YELLOW}$(t not_installed)${RESET}"
    fi

    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    if systemctl list-units --type=service --all 2>/dev/null | grep -q "${PANEL_SERVICE}.service"; then
        if systemctl is-active --quiet "$PANEL_SERVICE" 2>/dev/null; then
            echo -e "Admin Panel Status: ${GREEN}${BOLD}$(t service_running)${RESET}"
        else
            echo -e "Admin Panel Status: ${RED}${BOLD}$(t service_stopped)${RESET}"
        fi
    else
        echo -e "Admin Panel Status: ${YELLOW}$(t not_installed)${RESET}"
    fi

    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
}

pause() {
    echo ""
    read -rp "$(t pause_prompt)" _
}

# ---------------------------------------------------------------------------
# Action: full initial install / عملیات: نصب اولیه کامل
# ---------------------------------------------------------------------------
install_bot() {
    echo -e "${CYAN}$(t installing_prereqs)${RESET}"
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
    timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get install -y -qq git python3 python3-pip python3-venv figlet > /dev/null

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
    echo -e "${CYAN}$(t fetching_latest)${RESET}"
    fetch_project_code "$INSTALL_DIR"
    echo -e "${CYAN}$(t updating_packages)${RESET}"
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate
    echo -e "${CYAN}$(t restarting_bot_service)${RESET}"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2

    MINIAPP_SERVICE="${SERVICE_NAME}-miniapp"
    if systemctl list-units --full -all | grep -q "${MINIAPP_SERVICE}.service"; then
        echo -e "${CYAN}$(t restarting_miniapp_service)${RESET}"
        sudo systemctl restart "$MINIAPP_SERVICE"
        sleep 2
    fi

    PANEL_SERVICE="${SERVICE_NAME}-adminpanel"
    if systemctl list-units --full -all | grep -q "${PANEL_SERVICE}.service"; then
        echo -e "${CYAN}$(t restarting_panel_service)${RESET}"
        sudo systemctl restart "$PANEL_SERVICE"
        sleep 2
    fi

    echo -e "${GREEN}$(t update_done)${RESET}"
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
    echo -e "${CYAN}$(t fetching_latest)${RESET}"
    fetch_project_code "$INSTALL_DIR"
    echo -e "${CYAN}$(t updating_packages)${RESET}"
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate
    echo -e "${CYAN}$(t restarting_miniapp_service)${RESET}"
    sudo systemctl restart "$MINIAPP_SERVICE"
    sleep 2
    echo -e "${GREEN}$(t miniapp_update_done)${RESET}"
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
import database as db

lang = os.environ.get("SHOPVPN_STATS_LANG", "en")
s = db.get_stats()

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

    CUR_TOKEN=$(grep BOT_TOKEN "$INSTALL_DIR/.env" | cut -d '=' -f2)
    CUR_OWNER=$(grep OWNER_ID "$INSTALL_DIR/.env" | cut -d '=' -f2)

    [ -n "$NEW_TOKEN" ] && CUR_TOKEN="$NEW_TOKEN"
    [ -n "$NEW_OWNER" ] && CUR_OWNER="$NEW_OWNER"

    cat > "$INSTALL_DIR/.env" <<EOF
BOT_TOKEN=$CUR_TOKEN
OWNER_ID=$CUR_OWNER
EOF
    echo -e "${GREEN}$(t saved_restarting)${RESET}"
    sudo systemctl restart "$SERVICE_NAME"
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
    echo -e "${CYAN}$(t fetching_latest)${RESET}"
    fetch_project_code "$INSTALL_DIR"
    echo -e "${CYAN}$(t updating_packages)${RESET}"
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate
    echo -e "${CYAN}$(t restarting_panel_service)${RESET}"
    sudo systemctl restart "$PANEL_SERVICE"
    sleep 2
    echo -e "${GREEN}$(t panel_update_done)${RESET}"
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
# Main menu / منوی اصلی
# ---------------------------------------------------------------------------
ensure_figlet

while true; do
    print_banner
    print_status_line
    echo ""
    echo -e "${BLUE}[1]${RESET} » ${GREEN}$(t menu_1)${RESET}"
    echo -e "${BLUE}[2]${RESET} » ${GREEN}$(t menu_2)${RESET}"
    echo -e "${BLUE}[3]${RESET} » ${GREEN}$(t menu_3)${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${BLUE}[4]${RESET} » ${GREEN}$(t menu_4)${RESET}"
    echo -e "${BLUE}[5]${RESET} » ${GREEN}$(t menu_5)${RESET}"
    echo -e "${BLUE}[6]${RESET} » ${GREEN}$(t menu_6)${RESET}"
    echo -e "${BLUE}[7]${RESET} » ${GREEN}$(t menu_7)${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${YELLOW}[8]${RESET} » ${GREEN}$(t menu_8)${RESET}"
    echo -e "${YELLOW}[9]${RESET} » ${GREEN}$(t menu_9)${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${YELLOW}[10]${RESET} » ${GREEN}$(t menu_10)${RESET}"
    echo -e "${YELLOW}[11]${RESET} » ${GREEN}$(t menu_11)${RESET}"
    echo -e "${YELLOW}[12]${RESET} » ${GREEN}$(t menu_12)${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${YELLOW}[13]${RESET} » ${GREEN}$(t menu_13)${RESET}"
    echo -e "${YELLOW}[14]${RESET} » ${GREEN}$(t menu_14)${RESET}"
    echo -e "${YELLOW}[15]${RESET} » ${GREEN}$(t menu_15)${RESET}"
    echo -e "${YELLOW}[16]${RESET} » ${GREEN}$(t menu_16)${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${YELLOW}[17]${RESET} » ${GREEN}$(t menu_17)${RESET}"
    echo -e "${YELLOW}[18]${RESET} » ${GREEN}$(t menu_18)${RESET}"
    echo -e "${YELLOW}[19]${RESET} » ${GREEN}$(t menu_19)${RESET}"
    echo -e "${YELLOW}[20]${RESET} » ${GREEN}$(t menu_20)${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${MAGENTA}[L]${RESET} » ${GREEN}$(t menu_lang)${RESET}"
    echo -e "${RED}[0]${RESET} » ${GREEN}$(t menu_0)${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo ""
    read -rp "$(echo -e ${MAGENTA}${BOLD}"$(t enter_choice_prompt)"${RESET})" choice

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
        [Ll]) toggle_lang ;;
        0) echo -e "${CYAN}$(t goodbye)${RESET}"; exit 0 ;;
        *) echo -e "${RED}$(t invalid_choice)${RESET}"; sleep 1 ;;
    esac
done
