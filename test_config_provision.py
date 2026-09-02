# -*- coding: utf-8 -*-
"""
ساخت کانفیگ تست از روی یک ردیف test_config_plans (چندمدلی، مثل محصولات).

برخلاف مسیر قدیمی (تنظیم سراسری حجم/مدت + یک پنل ثابت)، هر پلن پنل/حجم/مدت/
پیشوند نام خودش را دارد. حجم و مدت به مگابایت و ساعت ذخیره می‌شوند تا مقادیر
زیر ۱ گیگ/۱ روز هم ممکن باشد؛ به provider همیشه به‌صورت GB/روز (float) داده
می‌شود، همان چیزی که create_user در همه‌ی پروایدرها می‌پذیرد.
"""

import random

from panel_providers import get_provider, PanelError, PanelUsernameTakenError


class ProvisionError(Exception):
    pass


def _random_username(prefix: str) -> str:
    prefix = (prefix or "test").strip() or "test"
    suffix = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
    return f"{prefix}{suffix}"


async def provision_test_plan(db, plan, user_id: int, override_server=None) -> dict:
    """پلن را روی پنل خودش (یا override_server، برای نماینده سطح ۲ که همیشه از
    پنل اعتباری خودش استفاده می‌کند، نه پنل ثبت‌شده روی پلن) می‌سازد و در
    custom_configs با source='test' و product_id=plan['id'] ثبت می‌کند.
    برمی‌گرداند: {subscription_url, username, volume_gb, duration_days}."""
    server = override_server or db.get_panel_server(plan["panel_server_id"])
    if not server or not server["is_active"]:
        raise ProvisionError("پنل این پلن کانفیگ تست یافت نشد یا غیرفعال است؛ با پشتیبانی تماس بگیرید.")

    volume_gb = plan["volume_mb"] / 1024.0
    duration_days = plan["duration_hours"] / 24.0

    provider = get_provider(server)
    username = None
    result = None
    try:
        for _ in range(10):
            candidate = _random_username(plan["name_prefix"])
            try:
                result = await provider.create_user(candidate, volume_gb, duration_days)
                username = candidate
                break
            except PanelUsernameTakenError:
                continue
    except PanelError as e:
        raise ProvisionError(f"خطا در ساخت کانفیگ تست: {e}")

    if username is None:
        raise ProvisionError("ساخت نام کاربری یکتا روی پنل ناموفق بود؛ دوباره تلاش کنید.")

    try:
        db.add_custom_config(
            user_id, server["id"], username, volume_gb, duration_days,
            result.subscription_url, source="test", product_id=plan["id"],
        )
    except Exception:
        pass

    return {
        "subscription_url": result.subscription_url,
        "username": username,
        "volume_gb": volume_gb,
        "duration_days": duration_days,
    }


def format_plan_amount(plan) -> str:
    """نمایش خوانا از حجم/مدت پلن، حتی وقتی زیر ۱ گیگ یا ۱ روز باشد."""
    mb = plan["volume_mb"]
    vol_text = f"{mb / 1024:.2f}".rstrip("0").rstrip(".") + " گیگ" if mb >= 1024 else f"{mb} مگابایت"
    hours = plan["duration_hours"]
    dur_text = f"{hours / 24:.2f}".rstrip("0").rstrip(".") + " روز" if hours >= 24 and hours % 24 == 0 else f"{hours} ساعت"
    return f"{vol_text} / {dur_text}"
