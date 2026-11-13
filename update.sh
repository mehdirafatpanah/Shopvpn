#!/bin/bash
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# اسکریپت آپدیت بات (نسخه هماهنگ با سرویس systemd که install.sh می‌سازد)
# استفاده: ./update.sh "توضیح کوتاه تغییر"

set -e

cd "$(dirname "$0")"

COMMIT_MSG="${1:-آپدیت بدون توضیح}"
SERVICE_NAME="v2raybot"

echo "📦 ثبت تغییرات در گیت..."
git add .
git commit -m "$COMMIT_MSG" || echo "  (تغییری برای commit نبود)"
git push || echo "  ⚠️ push انجام نشد (شاید remote تنظیم نیست یا نیاز به توکن دارد)"

echo "🐍 آپدیت پکیج‌ها..."
source venv/bin/activate
pip install -r requirements.txt --quiet
deactivate

echo "🌍 موتور ترجمه محلی در آپدیت عادی اجرا نمی‌شود تا چند گیگابایت دانلود ناخواسته انجام نشود."
echo "   برای نصب/آپدیت اختیاری ترجمه از منوی مدیریت، گزینه 31 استفاده کنید."

echo "🎨 ساخت نسخه‌ی minify فایل‌های پنل وب..."
bash admin_panel/build_assets.sh --if-stale || echo "  ⚠️ build_assets ناموفق بود (پنل از فایل‌های سورس استفاده می‌کند)"

echo "🔄 ری‌استارت سرویس بات..."
sudo systemctl restart "$SERVICE_NAME"
if [ -f "/etc/systemd/system/${SERVICE_NAME}-sub.service" ]; then
    echo "🔗 ری‌استارت سرور ساب اختصاصی..."
    sudo systemctl restart "${SERVICE_NAME}-sub"
fi
sleep 2

echo "✅ انجام شد."
sudo systemctl status "$SERVICE_NAME" --no-pager -l | head -10

#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
