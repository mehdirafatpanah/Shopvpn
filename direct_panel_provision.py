# -*- coding: utf-8 -*-
"""
تحویل خودکار محصولاتی که مستقیماً به یک پنل VPN مشخص (products.provision_server_id)
وصل هستند - بدون دخالت اعتبار حجمی نماینده.

برخلاف reseller_auto_provision.provision_auto_config (که مخصوص بات‌های نمایندگی
و اعتبار حجمی آن‌هاست)، این ماژول برای فروش عادی محصولات در بات اصلی/بانک‌کاربران
است: ادمین موقع ساخت محصول یک پنل مشخص می‌کند، و همان لحظه‌ی خرید یک کاربر واقعی
روی همان پنل ساخته می‌شود - از دید خریدار دقیقاً مثل خرید از بانک کانفیگ.
"""

import random
import string

from panel_providers import get_provider, PanelError, PanelUsernameTakenError


class ProvisionError(Exception):
    pass


def _random_username(prefix: str = "") -> str:
    suffix = "d" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}-{suffix}" if prefix else suffix


async def provision_direct(db, product, quantity: int = 1, user_id: int = None, order_id: int = None) -> list:
    """محصول باید provision_server_id معتبر داشته باشد. برای هر واحد یک کاربر واقعی
    روی همان پنل ساخته می‌شود. برمی‌گرداند: لیستی از
    {"username": ..., "subscription_url": ..., "volume_gb": ..., "duration_days": ...}
    در صورت بروز خطا ProvisionError پرتاب می‌شود؛ واحدهایی که تا آن لحظه با موفقیت
    روی پنل ساخته شده‌اند، در همان لیست خطا هم اشاره می‌شوند تا چیزی گم نشود.

    اگر user_id داده شود، هر واحد ساخته‌شده در custom_configs (source='direct_product')
    هم ثبت می‌شود تا هشدار اتمام حجم/زمان و «سرویس‌های من» آن را ببینند."""
    server_id = product["provision_server_id"]
    if not server_id:
        raise ProvisionError("این محصول به هیچ پنلی وصل نشده است.")

    server = db.get_panel_server(server_id)
    if not server or not server["is_active"]:
        raise ProvisionError("پنل متصل به این محصول یافت نشد یا غیرفعال است؛ با پشتیبانی تماس بگیرید.")

    volume_gb = product["auto_provision_volume_gb"]
    if volume_gb is None or volume_gb < 0:
        raise ProvisionError("حجم این محصول تنظیم نشده است.")
    # 0 یعنی نامحدود (هم برای حجم و هم برای مدت) - نباید با مقدار پیش‌فرض جایگزین شود
    duration_days = product["duration_days"] if product["duration_days"] is not None else 30

    provider = get_provider(server)
    prefix = db.get_custom_config_prefix()
    built = []
    try:
        for _ in range(quantity):
            username = None
            result = None
            for _try in range(5):
                candidate = _random_username(prefix)
                try:
                    result = await provider.create_user(candidate, volume_gb, duration_days)
                    username = candidate
                    break
                except PanelUsernameTakenError:
                    continue
            if username is None:
                raise ProvisionError("ساخت نام کاربری یکتا روی پنل ناموفق بود؛ دوباره تلاش کنید.")
            built.append({
                "username": result.username,
                "subscription_url": result.subscription_url,
                "volume_gb": volume_gb,
                "duration_days": duration_days,
            })
    except ProvisionError:
        raise
    except PanelError as e:
        raise ProvisionError(f"خطا در ساخت کانفیگ روی پنل: {e}")

    if user_id is not None:
        for item in built:
            try:
                db.add_custom_config(
                    user_id, server["id"], item["username"], item["volume_gb"], item["duration_days"],
                    item["subscription_url"], order_id=order_id, source="direct_product",
                )
            except Exception:
                pass

    return built
