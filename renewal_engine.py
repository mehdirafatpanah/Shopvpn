# -*- coding: utf-8 -*-
"""
منطق مشترکِ اجرای واقعیِ «تمدید سرویس» از حساب کاربری، برای استفاده در همه‌ی
مسیرهای تایید پرداخت (تایید دستی کارت‌به‌کارت در پنل ادمین، تایید خودکار
کیف‌پول، و وب‌هوک/چک‌وضعیتِ کریپتو-آبان‌گیت‌وی-درگاه‌سفارشی که از طریق
abangateway_payment.finalize_paid_order صدا زده می‌شود).

سفارش تمدید مثل سفارش «کانفیگ شخصی» از همان جدول orders با product_id=0
استفاده می‌کند (is_renewal=1)، جزئیات لازم در ستون‌های renewal_* ذخیره شده.
"""

from panel_providers import get_provider, PanelError


class RenewalError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین در فرایند تمدید سرویس."""
    pass


async def execute_renewal(db, order) -> str:
    """تمدید واقعی را روی پنل/بوکینگ محلی اعمال می‌کند و متن نتیجه را برمی‌گرداند.
    در صورت شکست RenewalError صادر می‌شود (مبلغ را خودِ فراخوان باید مدیریت کند)."""
    kind = order["renewal_target_kind"]
    target_id = order["renewal_target_id"]
    mode = order["renewal_mode"]
    add_volume = order["renewal_add_volume_gb"] or 0
    add_days = order["renewal_add_days"] or 0

    if kind == "custom":
        cc = db.get_custom_config_owned(target_id, order["user_id"])
        if not cc:
            raise RenewalError("این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).")
        server = db.get_panel_server(cc["panel_server_id"])
        if not server or not server["is_active"]:
            raise RenewalError("سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است.")
        try:
            provider = get_provider(server)
            await provider.update_user(
                cc["username"], add_volume_gb=add_volume, add_days=add_days, reset_usage=(mode == "full"),
            )
        except PanelError as e:
            raise RenewalError(str(e)) from e
        db.apply_custom_config_renewal(cc["id"], add_volume, add_days)
        return "✅ سرویس شما با موفقیت تمدید شد."

    if kind == "config":
        new_expiry = db.extend_pool_config_expiry(target_id, order["user_id"], add_days)
        if not new_expiry:
            raise RenewalError("این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).")
        return "✅ سرویس شما با موفقیت تمدید شد."

    raise RenewalError("نوع سرویس برای تمدید نامعتبر است.")
