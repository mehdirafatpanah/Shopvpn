# -*- coding: utf-8 -*-
"""
بررسی هم‌خوانی تعریف تنظیمات بین بات، مینی‌اپ و پنل وب.

اجرا:  python3 check_settings_sync.py     (اگر مشکلی باشد کد خروج ۱ است)

python3 check_settings_sync.py --update-baseline   پس از رفع/پذیرفتن مغایرت‌ها، فهرست مبنا را بازنویسی می‌کند.

پنج بررسی:
 ۱) دو کپی settings_schema.py (ریشه و admin_panel/static) باید یکسان باشند.
 ۲) هر کلید فرم‌های ساده‌ی settings_schema باید تنظیم واقعی باشد (در DEFAULT_SETTINGS
    یا در یک get_setting/set_setting)؛ کلید مرده یعنی فرمی که چیزی را تغییر نمی‌دهد.
 ۳) در extra_settings_schema روی هر سطح (وب/مینی‌اپ) کلید تکراری نباشد.
 ۴) همه‌ی دکمه‌های ACCOUNT_TOGGLE_KEYS از مینی‌اپ قابل تنظیم باشند.
 ۶) گزینه‌های «مسیر انتخاب مدل» AI در extra_settings_schema با PROVIDER_LABELS در ai_support.py یکی باشد.
 ۵) تنظیمی که فقط در پنل وب یا فقط در مینی‌اپ قابل تغییر است و در
    settings_parity_baseline.json نیست، خطا می‌دهد (مغایرت جدید).
    «قابل تغییر» یعنی کلید در فرم/لیست فیلدها یا set_setting آن سطح باشد (نه فقط خوانده شود).
    بات عمداً در این مقایسه نیست: ادمین بات از لیست‌ها و helperهای عمومی استفاده می‌کند و
    با تحلیل ساده‌ی متن درست تشخیص داده نمی‌شود.
"""
import glob
import importlib.util
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
errors = []


def read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


# --- ۱) یکسان بودن دو کپی ---------------------------------------------------
a, b = "settings_schema.py", os.path.join("admin_panel", "static", "settings_schema.py")
if read(a) != read(b):
    errors.append(f"{a} و {b} با هم فرق دارند (یکی را روی دیگری کپی کن).")

# --- ۲) کلیدهای مرده --------------------------------------------------------
from db.constants import ACCOUNT_TOGGLE_KEYS, DEFAULT_SETTINGS  # noqa: E402

spec = importlib.util.spec_from_file_location("settings_schema_chk", a)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

used = set(DEFAULT_SETTINGS)
pat = re.compile(r"""(?:get_setting|set_setting)\s*(?:,|\()\s*['"]([A-Za-z0-9_]+)['"]""")
for f in glob.glob("**/*.py", recursive=True):
    if os.path.basename(f) in ("settings_schema.py", "check_settings_sync.py"):
        continue
    used.update(pat.findall(read(f)))
# کلیدهایی که در فرم‌های این پروژه با ساختار دیگری ذخیره می‌شوند.
used.update(k for k, _, _ in ACCOUNT_TOGGLE_KEYS)

for section in mod.SETTINGS_FORM_SECTIONS:
    for group in section.get("groups", []):
        if group.get("load_url"):  # فرم با endpoint اختصاصی؛ کلیدهایش نام مستعار دارند
            continue
        for field in group.get("fields", []):
            k = field.get("key")
            if k and k not in used:
                errors.append(f"کلید مرده در settings_schema: «{k}» (هیچ کدی آن را نمی‌خواند).")

# --- ۳) تکراری‌ها در extra_settings_schema ---------------------------------
import extra_settings_schema as E  # noqa: E402

for surface in ("web", "mini"):
    keys = [f["key"] for g in E.groups_for(surface) for f in g["fields"]]
    for k, n in Counter(keys).items():
        if n > 1:
            errors.append(f"کلید «{k}» در سطح {surface} {n} بار تعریف شده.")

# --- ۴) پوشش دکمه‌ها در مینی‌اپ --------------------------------------------
mini_keys = E.allowed_keys("mini")
for k, _, _ in ACCOUNT_TOGGLE_KEYS:
    if k not in mini_keys:
        errors.append(f"دکمه‌ی «{k}» در مینی‌اپ قابل تنظیم نیست.")

# --- ۶) هم‌خوانی ارائه‌دهنده‌های AI با ai_support.PROVIDER_LABELS ---------------
import ast  # noqa: E402

_labels = None
for _node in ast.walk(ast.parse(read("ai_support.py"))):
    if isinstance(_node, ast.Assign) and any(getattr(t_, "id", "") == "PROVIDER_LABELS" for t_ in _node.targets):
        _labels = ast.literal_eval(_node.value)
if _labels is None:
    errors.append("PROVIDER_LABELS در ai_support.py پیدا نشد.")
else:
    _schema_opts = {tuple(o) for o in E._AI_PROVIDER_OPTIONS}
    if _schema_opts != set(_labels.items()):
        errors.append("گزینه‌های ai_provider در extra_settings_schema با PROVIDER_LABELS در ai_support.py فرق دارد.")

# --- ۵) مغایرت وب ↔ مینی‌اپ نسبت به فهرست مبنا ------------------------------
import json  # noqa: E402

_get = re.compile(r"""get_setting\s*(?:,|\()\s*['"]([A-Za-z0-9_]+)['"]""")
_set = re.compile(r"""set_setting\s*(?:,|\()\s*['"]([A-Za-z0-9_]+)['"]""")
_key = re.compile(r"""['"]?\bkey['"]?\s*:\s*['"]([a-z][a-z0-9_]+)['"]""")

import extra_gateway_registry as _R  # noqa: E402

_real = set(DEFAULT_SETTINGS)
for _f in glob.glob("**/*.py", recursive=True):
    _real |= set(_get.findall(read(_f)))
_reg = set(_R.default_settings())


def _editable(files):
    out = set()
    for f in files:
        t = read(f)
        out |= set(_set.findall(t)) | set(_key.findall(t))
    return out


_web = (E.allowed_keys("web") | _reg | _editable([
    "admin_panel/server.py", "admin_panel/static/app.js", "admin_panel/static/settings_schema.py",
])) & _real
_mini = (E.allowed_keys("mini") | _reg | _editable(["miniapp/server.py", "miniapp/static/app.js"])) & _real

# تنظیماتی که طبق ماتریس انتشار باید در هر دو سطح وب و مینی‌اپ قابل ویرایش باشند.
_REQUIRED_WEB_MINI = {
    "usd_to_toman_rate", "crypto_payment_enabled", "crypto_allowed_currencies", "crypto_expire_min",
    "svc_refund_window_hours", "auto_provision_max_qty", "daily_report_enabled", "daily_report_time",
    "panel_health_enabled", "receipt_ai_reject_weight_threshold", "custom_config_duration_days",
    "test_config_panel_duration_days", "test_config_panel_volume_gb", "discount_order_expiry_minutes",
    "smart_subscription_base_url", "reseller_fixed_product_ids", "reseller_inline_commission_enabled",
}
for _surface_name, _surface_keys in (("پنل وب", _web), ("مینی‌اپ", _mini)):
    for _key_name in sorted(_REQUIRED_WEB_MINI - _surface_keys):
        errors.append(f"تنظیم «{_key_name}» طبق ماتریس باید در {_surface_name} قابل ویرایش باشد.")

# این سه تنظیم در پنل وب فرم اختصاصی دارند و باید علاوه بر آن در مینی‌اپ و بات نیز قابل ویرایش باشند.
for _surface_name, _surface_keys in (("مینی‌اپ", _mini), ("بات", E.allowed_keys("bot"))):
    for _key_name in ("report_chat_id", "server_check_interval_min", "server_offline_streak"):
        if _key_name not in _surface_keys:
            errors.append(f"تنظیم «{_key_name}» باید در {_surface_name} نیز قابل ویرایش باشد.")

current = {
    "web_only": sorted(k for k in _web - _mini if not k.startswith("_")),
    "mini_only": sorted(k for k in _mini - _web if not k.startswith("_")),
}
BASELINE = "settings_parity_baseline.json"

if "--update-baseline" in sys.argv:
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"✓ {BASELINE} بازنویسی شد (web_only={len(current['web_only'])}, mini_only={len(current['mini_only'])}).")
    sys.exit(0)

if not os.path.exists(BASELINE):
    errors.append(f"{BASELINE} وجود ندارد؛ یک بار با --update-baseline بساز.")
else:
    base = json.load(open(BASELINE, encoding="utf-8"))
    for side, where in (("web_only", "فقط در پنل وب"), ("mini_only", "فقط در مینی‌اپ")):
        for k in sorted(set(current[side]) - set(base.get(side, []))):
            errors.append(f"مغایرت جدید: «{k}» {where} قابل تغییر است (به سطح دیگر هم اضافه کن "
                          f"یا عمداً با --update-baseline بپذیر).")
        fixed = sorted(set(base.get(side, [])) - set(current[side]))
        if fixed:
            print(f"ℹ {len(fixed)} مورد از فهرست مبنا حل شده؛ با --update-baseline پاکشان کن: {', '.join(fixed)}")

if errors:
    print("\n".join("✗ " + e for e in errors))
    sys.exit(1)
print("✓ همه‌ی بررسی‌ها گذشت.")
