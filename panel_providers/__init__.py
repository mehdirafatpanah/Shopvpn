"""
نقطه‌ی ورود مشترک: get_provider(server) بر اساس server["panel_type"] نمونه‌ی
provider مناسب را برمی‌گرداند. برای اضافه‌کردن پنل جدید (X-UI فورک‌های دیگر،
Hiddify نسخه‌ی جدید و ...):
  ۱. یک فایل جدید مثل marzban_provider.py بساز که BasePanelProvider را پیاده کند
  ۲. اینجا در PROVIDERS رجیسترش کن
همین. بقیه‌ی کد پروژه بدون تغییر کار می‌کند.
"""
import json

from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError
from .pasarguard_provider import PasarguardProvider
from .threexui_provider import ThreeXUIProvider
from .marzban_provider import MarzbanProvider
from .marzneshin_provider import MarzneshinProvider
from .hiddify_provider import HiddifyProvider

PROVIDERS = {
    "pasarguard": PasarguardProvider,
    "3xui": ThreeXUIProvider,
    "marzban": MarzbanProvider,
    "marzneshin": MarzneshinProvider,
    "hiddify": HiddifyProvider,
}

PANEL_TYPE_LABELS = {
    "pasarguard": "PasarGuard",
    "3xui": "3X-UI",
    "marzban": "Marzban",
    "marzneshin": "Marzneshin",
    "hiddify": "Hiddify",
}

# پنل‌هایی که مثل PasarGuard با «کاربر نمونه» قالب می‌گیرند (group_ids/proxy_settings)
TEMPLATE_BASED_PANEL_TYPES = {"pasarguard", "marzban", "marzneshin"}
# پنل‌هایی که به یک «آدرس پایه‌ی Subscription» جدا از آدرس ادمین نیاز دارند
# (چون آدرس API ادمین و لینک عمومی اشتراک معمولاً دامنه/مسیر یکسانی ندارند).
# 3X-UI علاوه بر این، انتخاب inbound را هم لازم دارد؛ Hiddify نیازی به inbound ندارد.
SUB_BASE_URL_PANEL_TYPES = {"3xui", "hiddify"}
INBOUND_SELECT_PANEL_TYPES = {"3xui"}


def parse_xui_inbound_ids(server) -> list:
    """لیست id های inbound انتخاب‌شده روی یک سرور 3X-UI را برمی‌گرداند (برای
    نمایش/فرم‌ها در بات، مینی‌اپ و پنل وب - نه برای provider خودش که نسخه‌ی
    داخلی مشابه دارد). ستون جدید xui_inbound_ids (JSON array مثل "[1,2,3]")
    اولویت دارد؛ اگر خالی بود، برای سازگاری با نصب‌های قدیمی‌تر از ستون تک‌مقداری
    xui_inbound_id استفاده می‌شود."""
    keys = server.keys()
    raw = server["xui_inbound_ids"] if "xui_inbound_ids" in keys else None
    if raw:
        try:
            ids = json.loads(raw)
            if isinstance(ids, list) and ids:
                return [int(i) for i in ids]
        except (ValueError, TypeError):
            pass
    legacy = server["xui_inbound_id"] if "xui_inbound_id" in keys else None
    return [int(legacy)] if legacy else []


def get_provider(server) -> BasePanelProvider:
    panel_type = server["panel_type"]
    cls = PROVIDERS.get(panel_type)
    if cls is None:
        raise PanelError(f"نوع پنل «{panel_type}» پشتیبانی نمی‌شود")
    return cls(server)
