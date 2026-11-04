#!/bin/bash
# انتشار نسخه‌ی جدید برای همه‌ی کسانی که پروژه را نصب کرده‌اند (فقط روی سیستم توسعه‌دهنده).
#
# استفاده:
#   ./release.sh 6.1.0 "رفع باگ پرداخت" "افزودن درگاه جدید"
#   CRITICAL=1 ./release.sh 6.1.1 "رفع باگ امنیتی مهم"
#
# کار این اسکریپت: بالا بردن VERSION، نوشتن update.json (توضیح تغییرات)، commit و push.
# ربات‌های نصب‌شده تا چند ساعت بعد نسخه‌ی جدید را می‌بینند و به مدیرشان اعلان می‌دهند.
set -e
cd "$(dirname "$0")"
VERSION="${1:-}"
[ -n "$VERSION" ] || { echo "استفاده: $0 <نسخه، مثل 6.1.0> [\"تغییر ۱\" \"تغییر ۲\" ...]"; exit 1; }
[[ "$VERSION" =~ ^[0-9]+(\.[0-9]+){1,3}$ ]] || { echo "نسخه باید مثل 6.1.0 باشد"; exit 1; }
shift

OLD="$(tr -d '[:space:]' < VERSION 2>/dev/null || echo 0)"
echo "$VERSION" > VERSION
python3 - "$VERSION" "${CRITICAL:-0}" "$@" <<'PY'
import json, sys
version, critical, *notes = sys.argv[1:]
json.dump({"version": version, "critical": critical == "1", "notes": {"fa": notes}},
          open("update.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
open("update.json", "a").write("\n")
PY

git add -A
git commit -m "release: v${VERSION}" || true
git push
git tag -f "v${VERSION}"
git push -f origin "v${VERSION}"
if command -v gh >/dev/null 2>&1; then
  NOTES_TEXT="$(printf '%s\n' "$@")"
  gh release create "v${VERSION}" --title "v${VERSION}" --notes "${NOTES_TEXT:-v${VERSION}}" 2>/dev/null \
    || gh release edit "v${VERSION}" --notes "${NOTES_TEXT:-v${VERSION}}" || true
fi
echo "✅ نسخه‌ی ${OLD} → ${VERSION} منتشر شد."
