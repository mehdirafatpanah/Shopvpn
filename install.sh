#!/bin/bash
# اسکریپت نصب/آپدیت خودکار بات فروش کانفیگ V2Ray
#
# استفاده (بعد از اینکه این فایل را در مخزن گیت‌هاب خودت گذاشتی و REPO_URL را
# با آدرس ریپازیتوری خودت جایگزین کردی):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/USERNAME/v2ray-bot/main/install.sh)
#
# این اسکریپت هم برای نصب اولیه کار می‌کند و هم برای آپدیت‌های بعدی (idempotent است).

set -e

# جلوگیری از گیر کردن apt پشت پنجره‌های تعاملی (مثل پرسش needrestart برای ری‌استارت سرویس‌ها)
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

# جلوگیری از هنگ کردن git پشت پرامپت یوزرنیم/پسورد وقتی ریپو پرایوت یا آدرسش اشتباه است.
# به‌جای منتظر ماندن بی‌نهایت برای ورودی، فوراً با خطای واضح خارج می‌شود.
export GIT_TERMINAL_PROMPT=0

# ============================================================================
# تنظیمات - این خط را با آدرس مخزن گیت‌هاب خودت جایگزین کن
# ============================================================================
REPO_URL="https://github.com/mehdirafatpanah/Shopvpn.git"
INSTALL_DIR="$HOME/v2ray_bot"
SERVICE_NAME="v2raybot"

echo "🚀 شروع نصب/آپدیت بات فروش کانفیگ V2Ray"
echo "──────────────────────────────────────────"

# ----------------------------------------------------------------------------
# ۱. نصب پیش‌نیازهای سیستمی
# ----------------------------------------------------------------------------
echo "📦 بررسی و نصب پیش‌نیازها (git, python3, pip, venv)..."
sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq
timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get install -y -qq git python3 python3-pip python3-venv > /dev/null

# ----------------------------------------------------------------------------
# ۲. دریافت یا آپدیت کد از گیت‌هاب
# ----------------------------------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "🔄 مخزن از قبل موجود است، در حال دریافت آخرین تغییرات..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "📥 دریافت پروژه از گیت‌هاب..."
    if ! git clone "$REPO_URL" "$INSTALL_DIR"; then
        echo ""
        echo "❌ دریافت پروژه از گیت‌هاب شکست خورد."
        echo "   دلیل معمول: ریپو در آدرس زیر پابلیک نیست یا وجود ندارد:"
        echo "   $REPO_URL"
        echo "   اگر این ریپوی شماست، مطمئن شوید در گیت‌هاب روی Public تنظیم شده"
        echo "   و برنچ آن هم با آدرس بالا (معمولاً main) مطابقت دارد."
        exit 1
    fi
    cd "$INSTALL_DIR"
fi

# ----------------------------------------------------------------------------
# ۳. ساخت virtual environment و نصب پکیج‌ها
# ----------------------------------------------------------------------------
echo "🐍 آماده‌سازی محیط پایتون..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt --quiet
deactivate

# ----------------------------------------------------------------------------
# ۴. تنظیم فایل .env (فقط دفعه اول، چون این فایل هیچ‌وقت در گیت نیست)
# ----------------------------------------------------------------------------
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo ""
    echo "🔑 فایل .env پیدا نشد. اطلاعات زیر را وارد کن:"
    read -rp "توکن بات (از BotFather): " BOT_TOKEN_INPUT
    read -rp "آیدی عددی ادمین (مثلاً از @userinfobot): " OWNER_ID_INPUT
    cat > "$INSTALL_DIR/.env" <<EOF
BOT_TOKEN=$BOT_TOKEN_INPUT
OWNER_ID=$OWNER_ID_INPUT
EOF
    echo "✅ فایل .env ساخته شد."
else
    echo "✅ فایل .env از قبل موجود است، دست‌نخورده باقی می‌ماند."
fi

# ----------------------------------------------------------------------------
# ۵. ساخت systemd service برای اجرای دائمی و خودکار بعد از ری‌بوت سرور
# ----------------------------------------------------------------------------
echo "⚙️ تنظیم سرویس systemd برای اجرای همیشگی بات..."
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

echo ""
echo "──────────────────────────────────────────"
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ بات با موفقیت نصب/آپدیت شد و در حال اجراست."
else
    echo "⚠️ بات اجرا نشد. برای دیدن جزئیات خطا:"
    echo "   sudo journalctl -u $SERVICE_NAME -n 50 --no-pager"
fi
echo ""
echo "دستورات مفید:"
echo "  وضعیت بات:    sudo systemctl status $SERVICE_NAME"
echo "  لاگ زنده:      sudo journalctl -u $SERVICE_NAME -f"
echo "  ری‌استارت:     sudo systemctl restart $SERVICE_NAME"
echo "  متوقف کردن:    sudo systemctl stop $SERVICE_NAME"
echo "──────────────────────────────────────────"
