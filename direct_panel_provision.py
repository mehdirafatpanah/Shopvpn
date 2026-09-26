# -*- coding: utf-8 -*-
"""
تحویل خودکار محصولاتی که مستقیماً به یک پنل VPN مشخص (products.provision_server_id)
وصل هستند - بدون دخالت اعتبار حجمی نماینده.

برخلاف reseller_auto_provision.provision_auto_config (که مخصوص بات‌های نمایندگی
و اعتبار حجمی آن‌هاست)، این ماژول برای فروش عادی محصولات در بات اصلی/بانک‌کاربران
است: ادمین موقع ساخت محصول یک پنل مشخص می‌کند، و همان لحظه‌ی خرید یک کاربر واقعی
روی همان پنل ساخته می‌شود - از دید خریدار دقیقاً مثل خرید از بانک کانفیگ.
"""

import logging
import random
import string

from panel_providers import get_provider, PanelError, PanelUsernameTakenError
from user_limit import order_user_limit, provider_kwargs

logger = logging.getLogger(__name__)


class ProvisionError(Exception):
    pass


def _random_username(prefix: str = "") -> str:
    suffix = "d" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}-{suffix}" if prefix else suffix


def planned_usernames(base: str, quantity: int) -> list:
    return [base] if quantity == 1 else [f"{base}_{i}" for i in range(1, quantity + 1)]


async def provision_direct(db, product, quantity: int = 1, user_id: int = None, order_id: int = None) -> list:
    """محصول باید provision_server_id معتبر داشته باشد. برای هر واحد یک کاربر واقعی
    روی همان پنل ساخته می‌شود. برمی‌گرداند: لیستی از
    {"username": ..., "subscription_url": ..., "volume_gb": ..., "duration_days": ...}
    در صورت هر نوع خطا (حتی بعد از ساخت موفق چند واحد) ProvisionError پرتاب می‌شود
    و این تابع همه‌یا-هیچ است: واحدهایی که تا آن لحظه واقعاً روی پنل ساخته شده‌اند
    قبل از پرتاب خطا تلاش می‌شود پاک شوند تا اکانت یتیم روی پنل باقی نماند.

    اگر user_id داده شود، هر واحد ساخته‌شده در custom_configs (source='direct_product')
    هم ثبت می‌شود تا هشدار اتمام حجم/زمان و «سرویس‌های من» آن را ببینند."""
    if not isinstance(quantity, int) or quantity < 1:
        raise ProvisionError("تعداد درخواستی نامعتبر است.")

    server_id = product["provision_server_id"]
    if not server_id:
        raise ProvisionError("این محصول به هیچ پنلی وصل نشده است.")

    server = db.get_panel_server(server_id)
    if not server or not server["is_active"]:
        raise ProvisionError("پنل متصل به این محصول یافت نشد یا غیرفعال است؛ با پشتیبانی تماس بگیرید.")

    if not db.panel_has_capacity(server_id, quantity):
        info = db.get_panel_capacity_info(server_id) or {}
        limit = info.get("max_services") or 0
        used = info.get("active_services", 0)
        raise ProvisionError(f"ظرفیت پنل تکمیل است ({used}/{limit} سرویس فعال).")

    volume_gb = product["auto_provision_volume_gb"]
    if volume_gb is None or volume_gb < 0:
        raise ProvisionError("حجم این محصول تنظیم نشده است.")
    # 0 یعنی نامحدود (هم برای حجم و هم برای مدت) - نباید با مقدار پیش‌فرض جایگزین شود
    duration_days = product["duration_days"] if product["duration_days"] is not None else 30

    provider = get_provider(server)
    prefix = db.get_custom_config_prefix()
    planned = []
    order = db.get_order(order_id) if order_id is not None else None
    if order and order["config_name"]:
        planned = planned_usernames(order["config_name"], quantity)
    extra_kwargs = provider_kwargs(provider, order_user_limit(order, product))
    built = []

    async def _rollback_built():
        # رفع باگ: برخلاف ادعای docstring («واحدهای ساخته‌شده گم نمی‌شوند»)، قبلاً
        # اگر واحد Nام از چند واحدِ یک خرید با خطا مواجه می‌شد، واحدهای ۱..N-۱ که
        # واقعاً روی پنل ساخته شده بودند نه پاک می‌شدند و نه در ProvisionError پرتاب‌شده
        # به‌جایی اشاره می‌شدند - یعنی اکانت‌های واقعی روی پنل مشتری برای همیشه یتیم
        # می‌ماندند (نه در custom_configs ثبت می‌شدند، نه قابل پیگیری بودند) درحالی‌که
        # خودِ خرید با خطا مواجه شده بود. دقیقاً مثل reseller_auto_provision._rollback_built،
        # الان قبل از پرتاب ProvisionError هر واحدِ تا این لحظه ساخته‌شده حذف می‌شود.
        for item in built:
            try:
                await provider.delete_user(item["username"])
            except Exception:
                pass

    try:
        for index in range(quantity):
            # بررسی دوم درست قبل از ساخت، برای کاهش احتمال عبور از سقف در خریدهای هم‌زمان.
            if not db.panel_has_capacity(server_id, 1):
                await _rollback_built()
                raise ProvisionError("ظرفیت پنل در همین لحظه تکمیل شد؛ مبلغ سفارش به شما برگردانده می‌شود.")
            username = None
            result = None
            wanted = planned[index] if planned else None
            for attempt in range(5):
                if wanted and attempt == 0:
                    candidate = wanted
                elif wanted:
                    candidate = wanted + "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
                else:
                    candidate = _random_username(prefix)
                if db.is_custom_username_taken(candidate):
                    continue
                try:
                    result = await provider.create_user(candidate, volume_gb, duration_days, **extra_kwargs)
                    username = candidate
                    break
                except PanelUsernameTakenError:
                    continue
            if username is None:
                await _rollback_built()
                raise ProvisionError("ساخت نام کاربری یکتا روی پنل ناموفق بود؛ دوباره تلاش کنید.")
            built.append({
                "username": result.username,
                "subscription_url": result.subscription_url,
                "volume_gb": volume_gb,
                "duration_days": duration_days,
                "user_limit": extra_kwargs.get("user_limit"),
            })
    except ProvisionError:
        raise
    except PanelError as e:
        await _rollback_built()
        raise ProvisionError(f"خطا در ساخت کانفیگ روی پنل: {e}")

    if user_id is not None:
        for item in built:
            try:
                db.add_custom_config(
                    user_id, server["id"], item["username"], item["volume_gb"], item["duration_days"],
                    item["subscription_url"], order_id=order_id, source="direct_product",
                    user_limit=item.get("user_limit"),
                )
            except Exception:
                # مسیر خودِ ساخت روی پنل قبلاً موفق شده (والا اصلاً به این بلوک
                # نمی‌رسیدیم)؛ اینجا فقط ثبت محلی سرویس است، پس raise نمی‌کنیم
                # تا مشتری از خریدی که واقعاً تحویل گرفته محروم نشود - ولی لاگ
                # می‌کنیم تا این‌جور شکست‌ها دیگر بی‌صدا گم نشوند.
                logger.exception(
                    "add_custom_config برای واحد direct-provision ناموفق بود "
                    "(user_id=%s, username=%s, order_id=%s) - این سرویس در «سرویس‌های من» دیده نخواهد شد.",
                    user_id, item.get("username"), order_id,
                )

    return built
