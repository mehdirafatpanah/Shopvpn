"""
اینترفیس پایه‌ی مشترک برای همه‌ی provider های پنل VPN (PasarGuard، و در آینده
Marzban، Marzneshin، X-UI و ...). هر provider جدید فقط باید این کلاس را
پیاده‌سازی کند و در panel_providers/__init__.py رجیستر شود؛ بقیه‌ی کد پروژه
(handlers_user.py, miniapp/server.py) فقط با همین اینترفیس کار می‌کند و از
جزئیات API هر پنل بی‌خبر است.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PanelUserResult:
    username: str
    subscription_url: str
    raw: dict = None


class PanelError(Exception):
    """خطای عمومی ارتباط با پنل (اتصال، احراز هویت، یا پاسخ نامعتبر)."""
    pass


class PanelUsernameTakenError(PanelError):
    """نام کاربری روی خود پنل هم از قبل وجود دارد."""
    pass


class BasePanelProvider(ABC):
    """server: ردیف جدول panel_servers (sqlite3.Row) شامل api_url/api_username/
    api_password/group_ids/proxy_settings/default_group"""

    def __init__(self, server):
        self.server = server

    @abstractmethod
    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
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
                           reset_usage: bool = False) -> PanelUserResult:
        """حجم/انقضای یک کاربر موجود روی پنل را برای «تمدید سرویس» افزایش می‌دهد.
        add_volume_gb/add_days روی مقدار فعلی جمع می‌شوند (نه جایگزین آن).
        اگر انقضای فعلی گذشته باشد، مبنای محاسبه‌ی انقضای جدید «اکنون» است، نه
        تاریخ گذشته. reset_usage=True یعنی مصرف قبلی صفر شود (تمدید کامل)."""
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

    async def set_enabled(self, username: str, enabled: bool) -> None:
        """کاربر را روی خودِ پنل فعال/غیرفعال می‌کند (بدون تغییر حجم/انقضا).
        پیاده‌سازی پیش‌فرض: پشتیبانی نمی‌شود؛ provider هایی که این قابلیت را
        دارند این متد را override می‌کنند."""
        raise PanelError("این نوع پنل از فعال/غیرفعال کردن مستقیم کاربر پشتیبانی نمی‌کند.")

    async def rename_user(self, username: str, new_username: str) -> None:
        """نام/برچسب کاربر را روی خودِ پنل عوض می‌کند. پیاده‌سازی پیش‌فرض:
        پشتیبانی نمی‌شود (بعضی پنل‌ها username را به‌عنوان شناسه‌ی ثابت/کلید
        ردیابی مصرف استفاده می‌کنند و تغییر آن API ندارد)."""
        raise PanelError("این نوع پنل از تغییر نام کاربر روی خودِ پنل پشتیبانی نمی‌کند.")
