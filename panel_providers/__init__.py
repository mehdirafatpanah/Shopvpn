#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
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
from .alireza_provider import AlirezaProvider
from .rebecca_provider import RebeccaProvider
from .sui_provider import SUIProvider
from .wgdashboard_provider import WGDashboardProvider
from .mikrotik_provider import MikroTikProvider
from .ibsng_provider import IBSngProvider
from .wui_provider import WUIProvider
from .stealth_provider import StealthProvider
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

PROVIDERS = {
    "pasarguard": PasarguardProvider,
    "3xui": ThreeXUIProvider,
    "marzban": MarzbanProvider,
    "marzneshin": MarzneshinProvider,
    "hiddify": HiddifyProvider,
    "alireza": AlirezaProvider,
    "rebecca": RebeccaProvider,
    "sui": SUIProvider,
    "wgdashboard": WGDashboardProvider,
    "mikrotik": MikroTikProvider,
    "ibsng": IBSngProvider,
    "wui": WUIProvider,
    "stealth": StealthProvider,
}

PANEL_TYPE_LABELS = {
    "pasarguard": "PasarGuard",
    "3xui": "3X-UI",
    "marzban": "Marzban",
    "marzneshin": "Marzneshin",
    "hiddify": "Hiddify",
    "alireza": "Alireza X-UI",
    "rebecca": "Rebecca",
    "sui": "S-UI",
    "wgdashboard": "WGDashboard",
    "mikrotik": "MikroTik",
    "ibsng": "IBSng",
    "wui": "W-UI",
    "stealth": "Stealth VLESS",
}

# پنل‌هایی که مثل PasarGuard با «کاربر نمونه» قالب می‌گیرند (group_ids/proxy_settings)
TEMPLATE_BASED_PANEL_TYPES = {"pasarguard", "marzban", "marzneshin", "rebecca", "sui", "wgdashboard", "mikrotik", "ibsng", "wui"}
# پنل‌هایی که به یک «آدرس پایه‌ی Subscription» جدا از آدرس ادمین نیاز دارند‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# (چون آدرس API ادمین و لینک عمومی اشتراک معمولاً دامنه/مسیر یکسانی ندارند).‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 3X-UI علاوه بر این، انتخاب inbound را هم لازم دارد؛ Hiddify نیازی به inbound ندارد.
SUB_BASE_URL_PANEL_TYPES = {"3xui", "hiddify", "alireza"}
INBOUND_SELECT_PANEL_TYPES = {"3xui", "alireza"}
SINGLE_INBOUND_PANEL_TYPES = {"alireza"}

# پنل‌هایی که در مرحله‌ی «اتصال» هنوز به «کاربر نمونه» نیاز دارند، چون API فهرست زنده‌ی
# گروه/سرویس ندارند و محصول فقط از روی همان قالب می‌تواند مقصد را انتخاب کند.
# برای بقیه‌ی پنل‌ها در اتصال هیچ اینباند/گروه/کاربر نمونه‌ای پرسیده نمی‌شود؛
# مقصد (گروه یا اینباند) موقع ساخت محصول انتخاب می‌شود.
CONNECT_TEMPLATE_PANEL_TYPES = {"rebecca", "ibsng"}


def connect_needs_template(panel_type) -> bool:
    return panel_type in CONNECT_TEMPLATE_PANEL_TYPES


def connect_needs_inbound(panel_type) -> bool:
    """در اتصال دیگر انتخاب inbound وجود ندارد (در محصول انتخاب می‌شود)."""
    return False


def panel_server_is_ready(server) -> bool:
    """آیا سرور بعد از اتصال آماده‌ی استفاده است؟ (بدون نیاز به اینباند/گروه در سطح سرور)"""
    t = server["panel_type"]
    if t in SUB_BASE_URL_PANEL_TYPES:
        return bool(server["xui_sub_base_url"])
    if t in CONNECT_TEMPLATE_PANEL_TYPES:
        return bool(server["group_ids"])
    return True

TOKEN_ONLY_PANEL_TYPES = {"3xui": "3xui", "rebecca": "rebecca", "sui": "sui", "wgdashboard": "wgdashboard", "wui": "wui", "stealth": "stealth"}
# پنل‌هایی که بعد از آدرس و توکن هیچ تنظیم دیگری (قالب/inbound/ساب) نمی‌خواهند؛ فقط تست اتصال و ذخیره
NO_SETUP_PANEL_TYPES = {"stealth"}

SECRET_PROMPTS = {
    "rebecca": "توکن (Bearer token) ادمین پنل Rebecca را بفرست:",
    "sui": "API Token پنل S-UI را بفرست (از بخش Admin ← API Token داخل پنل):",
    "wgdashboard": "API Key پنل WGDashboard را بفرست (از Settings ← API Keys داخل پنل):",
    "stealth": "توکن API نود Stealth را بفرست (نصاب موقع پایان نصب چاپ می‌کند؛ آدرس API هم همان است که نصاب نشان داد):",
    "wui": "API Token پنل W-UI را بفرست (از Settings ← Authentication ← API Token داخل پنل؛ همان توکنی که نصب‌کننده نشان داد):",
}

TEMPLATE_PROMPTS = {
    "sui": "نام یک کاربر (client) که از قبل روی پنل S-UI وجود دارد را بفرست؛ inbound های همین کاربر برای کاربرهای جدید استفاده می‌شود.",
    "rebecca": "نام یک کاربر که از قبل روی پنل Rebecca وجود دارد را بفرست؛ سرویس (service) همین کاربر برای کاربرهای جدید استفاده می‌شود.",
    "wgdashboard": "نام configuration (اینترفیس WireGuard، مثلاً wg0) که کاربرها در آن ساخته شوند را بفرست:",
    "wui": "نام یک مشتری (customer) که از قبل روی پنل W-UI وجود دارد را بفرست؛ interface های همین مشتری برای کاربرهای جدید استفاده می‌شود.",
    "mikrotik": "نام profile در User Manager روتر را بفرست (حجم و مدت را همین profile تعیین می‌کند):",
    "ibsng": "نام گروه (Group) در IBSng را بفرست (حجم و مدت را همین گروه تعیین می‌کند):",
}
TEMPLATE_VALUE_LABELS = {"wgdashboard": "configuration", "mikrotik": "profile", "ibsng": "گروه"}


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
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 


def server_has_default_target(server) -> bool:
    """آیا خودِ سرور (بدون محصول) مقصد پیش‌فرض دارد؟ فقط برای مهاجرت کاربران لازم است،
    چون آن‌جا کاربر بدون محصول روی پنل مقصد ساخته می‌شود."""
    t = server["panel_type"]
    if t in ("hiddify", "stealth"):
        return True
    if t in INBOUND_SELECT_PANEL_TYPES:
        return bool(parse_xui_inbound_ids(server))
    return bool(server["group_ids"])


CUSTOM_CONFIG_NEEDS_TARGET_MSG = (
    "برای «خرید شخصی» (حجم دلخواه، بدون محصول) باید خودِ سرور یک مقصد پیش‌فرض داشته باشد؛ "
    "چون در اتصال پنل دیگر گروه/اینباند پرسیده نمی‌شود، اول از مدیریت همین سرور «کاربر نمونه/قالب پیش‌فرض» "
    "(یا «Inbound پیش‌فرض» برای 3X-UI/Alireza) را یک‌بار تنظیم کن."
)

