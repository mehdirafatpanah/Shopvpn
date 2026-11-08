# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
ساخت کانفیگ تست از روی یک ردیف test_config_plans (چندمدلی، مثل محصولات).

برخلاف مسیر قدیمی (تنظیم سراسری حجم/مدت + یک پنل ثابت)، هر پلن پنل/حجم/مدت/
پیشوند نام خودش را دارد. حجم و مدت به مگابایت و ساعت ذخیره می‌شوند تا مقادیر
زیر ۱ گیگ/۱ روز هم ممکن باشد؛ به provider همیشه به‌صورت GB/روز (float) داده
می‌شود، همان چیزی که create_user در همه‌ی پروایدرها می‌پذیرد.
"""

import random

from panel_providers import get_provider, PanelError, PanelUsernameTakenError
import direct_panel_provision


class ProvisionError(Exception):
    pass
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def _random_username(prefix: str) -> str:
    prefix = (prefix or "test").strip() or "test"
    suffix = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
    return f"{prefix}{suffix}"


def plan_to_product(plan) -> dict:
    """پلن تست را به همان شکل یک محصول متصل به پنل درمی‌آورد تا دقیقاً از مسیر
    تحویل محصولات (direct_panel_provision) ساخته شود: گروه/Inbound، محدودیت کاربر،
    نود SSH، چندپنلی و ظرفیت پنل. شناسه‌ی منفی کلید مقصدهای اضافه‌ی پلن در
    product_extra_targets است و با محصولات واقعی تداخل نمی‌کند."""
    def pick(key, default=None):
        return plan[key] if key in plan.keys() and plan[key] is not None else default
    return {
        "id": -int(plan["id"]),
        "name": plan["name"],
        "price": 0,
        "category_id": 0,
        "is_auto_provision": 1,
        "provision_server_id": pick("panel_server_id"),
        "provision_ssh_node_id": pick("provision_ssh_node_id"),
        "provision_ssh_protocol": pick("provision_ssh_protocol", "ssh"),
        "provision_target_config": pick("provision_target_config"),
        "auto_provision_volume_gb": plan["volume_mb"] / 1024.0,
        "duration_days": plan["duration_hours"] / 24.0,
        "base_users": pick("base_users", 0),
        "extra_user_price": pick("extra_user_price", 0),
        "max_users": pick("max_users", 0),
        "test_username_prefix": plan["name_prefix"],
    }


async def provision_test_plan(db, plan, user_id: int, override_server=None,
                              source: str = "test", track_product: bool = True) -> dict:
    if override_server is None and "base_users" in plan.keys():
        return await _provision_like_product(db, plan, user_id, source, track_product)
    return await _provision_legacy(db, plan, user_id, override_server, source, track_product)


async def _provision_like_product(db, plan, user_id: int, source: str, track_product: bool) -> dict:
    if not (plan["panel_server_id"] or plan["provision_ssh_node_id"]):
        raise ProvisionError("برای این پلن کانفیگ تست هیچ پنل یا نود SSH تنظیم نشده است؛ با پشتیبانی تماس بگیرید.")
    try:
        items = await direct_panel_provision.provision_direct(
            db, plan_to_product(plan), quantity=1, user_id=user_id)
    except direct_panel_provision.ProvisionError as e:
        raise ProvisionError(str(e))
    except Exception as e:
        raise ProvisionError(f"خطا در ساخت کانفیگ تست: {e}")
    for item in items:
        config_id = item.get("custom_config_id")
        if config_id:
            try:
                db.retag_custom_config(config_id, source, plan["id"] if track_product else None)
            except Exception:
                pass
    first = items[0]
    return {
        "subscription_url": first["subscription_url"],
        "username": first["username"],
        "volume_gb": first.get("volume_gb", plan["volume_mb"] / 1024.0),
        "duration_days": first.get("duration_days", plan["duration_hours"] / 24.0),
    }


async def _provision_legacy(db, plan, user_id: int, override_server=None,
                            source: str = "test", track_product: bool = True) -> dict:
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
            result.subscription_url, source=source,
            product_id=plan["id"] if track_product else None,
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
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
