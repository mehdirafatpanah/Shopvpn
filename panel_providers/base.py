#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
اینترفیس پایه‌ی مشترک برای همه‌ی provider های پنل VPN (PasarGuard، و در آینده
Marzban، Marzneshin، X-UI و ...). هر provider جدید فقط باید این کلاس را
پیاده‌سازی کند و در panel_providers/__init__.py رجیستر شود؛ بقیه‌ی کد پروژه
(handlers_user.py, miniapp/server.py) فقط با همین اینترفیس کار می‌کند و از
جزئیات API هر پنل بی‌خبر است.
"""
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

import aiohttp

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    ProxyConnector = None
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


@dataclass
class PanelUserResult:
    username: str
    subscription_url: str
    raw: dict = None


class PanelError(Exception):
    """خطای عمومی ارتباط با پنل (اتصال، احراز هویت، یا پاسخ نامعتبر)."""
    pass


class PanelPermissionError(PanelError):
    """ادمین/API Key پنل برای این عملیات دسترسی ندارد (۴۰۳)؛ مثلاً نبودنِ دسترسی groups.read در PasarGuard."""
    pass


class PanelUsernameTakenError(PanelError):
    """نام کاربری روی خود پنل هم از قبل وجود دارد."""
    pass


def subscription_token(url: str) -> str:
    """آخرین بخش مسیر یک لینک اشتراک (توکن)، بدون query و اسلش انتهایی."""
    from urllib.parse import urlsplit

    path = urlsplit(url or "").path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def build_connector(server, ssl: bool = False):
    """کانکتور aiohttp برای اتصال به پنل: اگر روی این پنل یک پروکسی SOCKS
    تنظیم شده باشد (ستون socks_proxy - برای پنل‌هایی که مستقیم از سرور بات
    قابل‌اتصال نیستند، مثلاً پنل ایرانی پشت سرور خارجی)، از طریق آن پروکسی
    وصل می‌شود؛ در غیر این صورت اتصال مستقیم معمولی."""
    proxy = None
    if server is not None:
        try:
            proxy = server["socks_proxy"]
        except (KeyError, IndexError, TypeError):
            proxy = None
    if proxy:
        if ProxyConnector is None:
            raise PanelError(
                "برای اتصال این پنل از طریق پروکسی SOCKS باید پکیج aiohttp_socks روی سرور نصب باشد."
            )
        return ProxyConnector.from_url(proxy, ssl=ssl)
    return aiohttp.TCPConnector(ssl=ssl)


class BasePanelProvider(ABC):
    """server: ردیف جدول panel_servers (sqlite3.Row) شامل api_url/api_username/
    api_password/group_ids/proxy_settings/default_group/socks_proxy"""

    supports_user_limit = False
    last_error = ""

    def __init__(self, server):
        self.server = server

    def _build_connector(self, ssl: bool = False):
        return build_connector(self.server, ssl=ssl)

    async def list_product_targets(self):
        """فهرست مقصدهای قابل انتخاب برای یک محصول را با قرارداد مشترک برمی‌گرداند.

        خروجی استاندارد: {field, kind, choices}. Providerهایی که API فهرست
        مقصد دارند می‌توانند این متد را override کنند. برای Providerهای قدیمی
        که list_groups/list_inbounds دارند، این adapter سازگاری را فراهم می‌کند.
        """
        list_groups = getattr(self, "list_groups", None)
        if callable(list_groups):
            rows = await list_groups()
            choices = [
                {"value": str(item["id"]), "label": str(item.get("name") or item["id"])}
                for item in (rows or []) if isinstance(item, dict) and item.get("id") is not None
            ]
            return {"field": "group_ids", "kind": "list", "choices": choices} if choices else None
        list_inbounds = getattr(self, "list_inbounds", None)
        if callable(list_inbounds):
            rows = await list_inbounds()
            choices = [
                {"value": str(item["id"]), "label": f'{item.get("remark") or item["id"]} · {item.get("protocol") or ""} · {item.get("port") or ""}'.strip(" ·")}
                for item in (rows or []) if isinstance(item, dict) and item.get("id") is not None
            ]
            return {"field": "xui_inbound_ids", "kind": "list", "choices": choices} if choices else None
        return None

    @abstractmethod
    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False) -> PanelUserResult:
        """کاربر جدید روی پنل می‌سازد و لینک اشتراک را برمی‌گرداند."""
        raise NotImplementedError

    @abstractmethod
    async def delete_user(self, username: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def get_user_usage(self, username: str) -> dict:
        """برمی‌گرداند: {"used_bytes": int, "data_limit_bytes": int, "status": str}"""
        raise NotImplementedError

    @abstractmethod
    async def get_user(self, username: str) -> PanelUserResult:
        """اطلاعات فعلیِ کاربر را مستقیماً از پنل می‌خواند (نه از دیتابیس خودمان)
        و شامل لینک اشتراک (subscription_url) به‌روز است. برای رفرش‌کردن لینکی
        که قبلاً ذخیره شده استفاده می‌شود - مثلاً وقتی ادمین تنظیمات پنل (دامنه‌ی
        Subscription، inbound و ...) را بعد از فروش عوض کرده و لینک قدیمی دیگر
        معتبر نیست. اگر کاربر روی پنل پیدا نشود PanelError پرتاب می‌شود."""
        raise NotImplementedError

    @abstractmethod
    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False) -> PanelUserResult:
        """حجم/انقضای یک کاربر موجود روی پنل را برای «تمدید سرویس» افزایش می‌دهد.
        add_volume_gb/add_days روی مقدار فعلی جمع می‌شوند (نه جایگزین آن).
        اگر انقضای فعلی گذشته باشد، مبنای محاسبه‌ی انقضای جدید «اکنون» است، نه
        تاریخ گذشته. reset_usage=True یعنی مصرف قبلی صفر شود (تمدید کامل).
        وقتی reset_usage=True است، preserve_remaining تعیین می‌کند سقف حجم جدید
        چطور محاسبه شود: False (پیش‌فرض) = جایگزینی با بستهٔ تازه (حجم باقیمانده
        از دست می‌رود)؛ True = حجم باقیمانده‌ی مصرف‌نشده حفظ و بستهٔ جدید رویش
        اضافه می‌شود."""
        raise NotImplementedError

    @abstractmethod
    async def revoke_credentials(self, username: str) -> PanelUserResult:
        """اعتبار/لینک فعلی کاربر را باطل می‌کند و یک لینک تازه صادر می‌کند،
        بدون این‌که حجم، انقضا یا مصرف قبلی‌اش تغییر کند (دقیقاً همان حجم/زمان
        باقی‌مانده‌ی قبلی حفظ می‌شود؛ فقط UUID/کلید کاربر روی پنل عوض می‌شود
        تا لینک قدیمی از کار بیفتد). برای دکمه‌ی «قطع دسترسی و لینک جدید»."""
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> bool:
        """برای دکمه‌ی «تست اتصال» در پنل ادمین؛ فقط احراز هویت را چک می‌کند."""
        raise NotImplementedError

    async def check_connection(self):
        """(ok, error): مثل test_connection ولی علت دقیق شکست را هم برمی‌گرداند."""
        self.last_error = ""
        try:
            ok = await self.test_connection()
        except asyncio.TimeoutError:
            return False, "پاسخی از سرور در زمان مقرر دریافت نشد (timeout)"
        except Exception as e:
            return False, (str(e) or type(e).__name__)[:300]
        if ok:
            return True, ""
        return False, self.last_error or "اتصال یا احراز هویت ناموفق"

    supports_data_limit_sync = False

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط «سقف حجم» کاربر روی خودِ پنل را به limit_bytes تغییر می‌دهد (0 = نامحدود)،
        بدون دست‌زدن به انقضا، مصرف یا وضعیت دستی فعال/غیرفعال. برای سرویس‌های ترکیبی
        VPN+SSH استفاده می‌شود: مصرف SSH از سقف مشترک کم می‌شود تا پنل VPN هم باقی‌مانده‌ی
        واقعی را ببیند و خودش در لحظه‌ی اتمام قطع کند. reenable=True یعنی پنل کاربر را چون
        به سقف قبلی رسیده بود خودش غیرفعال کرده و حالا باید دوباره فعال شود.
        provider هایی که این قابلیت را دارند این متد را override و supports_data_limit_sync را True می‌کنند."""
        raise PanelError("این نوع پنل از تغییر مستقل سقف حجم پشتیبانی نمی‌کند.")

    async def set_enabled(self, username: str, enabled: bool) -> None:
        """کاربر را روی خودِ پنل فعال/غیرفعال می‌کند (بدون تغییر حجم/انقضا).
        پیاده‌سازی پیش‌فرض: پشتیبانی نمی‌شود؛ provider هایی که این قابلیت را
        دارند این متد را override می‌کنند."""
        raise PanelError("این نوع پنل از فعال/غیرفعال کردن مستقیم کاربر پشتیبانی نمی‌کند.")

    @staticmethod
    def _norm_binding(value):
        """شکل قابل‌مقایسه‌ی لیست/دیکشنریِ inbound، گروه یا سرویس."""
        if isinstance(value, dict):
            return {str(k): sorted(str(x) for x in (v or [])) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return sorted(str(x) for x in value)
        return [] if value in (None, "") else [str(value)]

    async def _sync_binding(self, session, headers, path: str, field: str, target) -> bool:
        """کاربر را GET می‌کند و اگر فیلد field با target فرق داشت با PUT یکی می‌کند (Marzban/Marzneshin)."""
        url = f"{self._base_url()}{path}"
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 404:
                    raise PanelError("کاربر روی پنل پیدا نشد.")
                if resp.status >= 400:
                    raise PanelError(f"خطا در دریافت کاربر (کد {resp.status})")
                current = await resp.json()
            if self._norm_binding(current.get(field)) == self._norm_binding(target):
                return False
            async with session.put(url, json={field: target}, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise PanelError(f"خطا در هم‌گام‌سازی کاربر (کد {resp.status}): {text[:300]}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise PanelError(f"خطا در اتصال به پنل: {e or 'timeout'}") from e
        return True

    supports_template_resync = False

    async def resync_user_template(self, username: str) -> bool:
        """گروه/قالب کاربر را با قالب فعلی سرور هم‌گام می‌کند؛ True یعنی تغییری اعمال شد."""
        return False

    async def rename_user(self, username: str, new_username: str) -> str:
        """نام/شناسه‌ی کاربر را روی خودِ پنل عوض می‌کند. اگر تغییر نام باعث
        عوض‌شدن لینک اشتراک (subscription_url) هم بشود، لینک تازه را
        برمی‌گرداند (در غیر این صورت None، یعنی لینک قبلی هنوز معتبر است).
        پیاده‌سازی پیش‌فرض: پشتیبانی نمی‌شود."""
        raise PanelError("این نوع پنل از تغییر نام کاربر روی خودِ پنل پشتیبانی نمی‌کند.")

    supports_fingerprints = False

    async def get_fingerprints(self, username: str) -> list:
        """همه‌ی مقادیر محرمانه‌ای که این کاربر را روی پنل شناسایی می‌کنند
        (UUID و پسورد پروتکل‌ها و توکن اشتراک) را به‌صورت لیست رشته برمی‌گرداند.
        این مقادیر فقط برای ساخت ایندکس هشِ تشخیص نشت استفاده می‌شوند و
        هرگز ذخیره‌ی متنی نمی‌شوند. پیش‌فرض: پشتیبانی نمی‌شود."""
        raise PanelError("این نوع پنل از خواندن اثر انگشت کاربر پشتیبانی نمی‌کند.")

    supports_online_status = False

    async def is_client_online(self, username: str) -> bool:
        """آیا کاربر همین الان به سرور متصل است (وصل=True/قطع=False).
        پیاده‌سازی پیش‌فرض: پشتیبانی نمی‌شود؛ provider هایی که این قابلیت را
        دارند این متد را override و supports_online_status را True می‌کنند."""
        raise PanelError("این نوع پنل از استعلام وضعیت آنلاین لحظه‌ای پشتیبانی نمی‌کند.")
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
