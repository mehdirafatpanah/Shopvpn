# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
منطق مشترکِ اجرای واقعیِ «تمدید سرویس» از حساب کاربری، برای استفاده در همه‌ی
مسیرهای تایید پرداخت (تایید دستی کارت‌به‌کارت در پنل ادمین، تایید خودکار
کیف‌پول، و وب‌هوک/چک‌وضعیتِ کریپتو-آبان‌گیت‌وی-درگاه‌سفارشی که از طریق
abangateway_payment.finalize_paid_order صدا زده می‌شود).

سفارش تمدید مثل سفارش «کانفیگ شخصی» از همان جدول orders با product_id=0
استفاده می‌کند (is_renewal=1)، جزئیات لازم در ستون‌های renewal_* ذخیره شده.
"""

import logging
from datetime import datetime, timedelta, timezone

from panel_providers import get_provider, PanelError
from user_limit import provider_kwargs
import renewal_log

logger = logging.getLogger(__name__)
_GB = 1024 ** 3


async def _update_panel_links_user_limit(db, custom_config_id: int, user_limit: int):
    """Apply a user-limit change to every VPN panel belonging to a multi-panel service."""
    for link in db.panel_links_for_config(custom_config_id, active_only=True):
        link_server = db.get_panel_server(link["panel_server_id"])
        if not link_server:
            raise RenewalError("یکی از پنل‌های سرویس چندمقصدی دیگر در دسترس نیست.")
        link_provider = get_provider(link_server)
        if not getattr(link_provider, "supports_user_limit", False):
            raise RenewalError("یکی از پنل‌های سرویس چندمقصدی از محدودیت کاربر پشتیبانی نمی‌کند.")
        await link_provider.update_user(link["username"], **provider_kwargs(link_provider, user_limit))


def _report_failed_link_renewals(db, pool, failed_links, add_days):
    lines = []
    for link, exc in failed_links:
        try:
            db.add_custom_config_history(
                link["custom_config_id"], "extra_panel_renew_failed",
                f"تمدید {add_days} روزه پنل #{link['panel_server_id']} ({link['username']}) ناموفق بود: {str(exc)[:200]}",
            )
        except Exception:
            logger.exception("history write failed for link %s", link["id"])
        lines.append(f"سرویس #{link['custom_config_id']} | پنل #{link['panel_server_id']} | {link['username']}")
    text = ("⚠️ تمدید ناقص سرویس چندپنلی\n\n"
            f"پرداخت و پنل اصلی تمدید شد ولی تمدید {add_days} روزه این پنل‌ها شکست خورد "
            "و با تاریخ قبلی منقضی می‌شوند؛ دستی تمدید کنید:\n" + "\n".join(lines))
    try:
        renewal_log.alert(db, text)
    except Exception:
        logger.exception("failed-renewal alert could not be scheduled (pool=%s)", pool["id"])


def _renew_quota_pool(db, pool, mode, add_volume, add_days, fresh=False):
    """تمدید استخر سهمیه‌ی مشترک VPN+SSH. برای سرویس ترکیبی، حجم و انقضای واقعی در
    استخر نگهداری می‌شود (پنل VPN با سقف نامحدود ساخته شده و reconciler سقف آن را از
    استخر می‌سازد)، پس تمدید باید روی استخر اعمال شود نه فقط روی پنل؛ وگرنه استخر در
    تاریخ قدیمی منقضی و هر دو سرویس قطع می‌شد. مصرف هیچ‌وقت صفر نمی‌شود (شمارنده‌ی SSH
    تجمعی است)؛ بسته‌ی جدید روی سقف قبلی جمع می‌شود. برمی‌گرداند: سقف جدید (GB)."""
    pool_id = int(pool["id"])
    usage = db.get_quota_usage(pool_id) or {}
    old_limit = int(pool.get("limit_bytes") or 0)
    used = int(usage.get("used_bytes") or 0)
    if mode in ("full", "volume") and not add_volume:
        new_limit_gb = 0.0
    elif add_volume:
        # fresh=True (تمدید خودکار ماهانه): بسته‌ی تازه‌ی کامل از «اکنون»؛ وگرنه روی سقف قبلی جمع می‌شود.
        if fresh or old_limit <= 0:
            new_limit_gb = used / _GB + float(add_volume)
        else:
            new_limit_gb = old_limit / _GB + float(add_volume)
    else:
        new_limit_gb = old_limit / _GB
    expires_at = pool.get("expires_at")
    if add_days and expires_at:
        try:
            current = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
        except ValueError:
            current = datetime.now(timezone.utc)
        base = max(current, datetime.now(timezone.utc))
        expires_at = (base + timedelta(days=int(add_days))).isoformat()
    db.set_quota_pool_limit(pool_id, new_limit_gb, expires_at)
    return new_limit_gb


async def renew_pooled_service(db, provider, username, pool, mode, add_volume, add_days, user_kwargs=None,
                               fresh=False):
    """تمدید کامل یک سرویس ترکیبی VPN+SSH: زمان روی پنل VPN، حجم/انقضا روی استخر مشترک،
    انقضا روی نودهای SSH و یک دور reconcile (فعال‌سازی مجدد اعضای قطع‌شده + اعمال سقف روی پنل).
    خطای پنل VPN به‌صورت PanelError به فراخوان می‌رسد (قبل از هر تغییر روی استخر)."""
    await provider.update_user(
        username, add_volume_gb=0, add_days=add_days, reset_usage=False,
        preserve_remaining=False, unlimited_volume=False, **(user_kwargs or {}),
    )
    failed_links = []
    for link in db.panel_links_for_pool(pool["id"]):
        try:
            link_server = db.get_panel_server(link["panel_server_id"])
            link_provider = get_provider(link_server)
            await link_provider.update_user(
                link["username"], add_volume_gb=0, add_days=add_days, reset_usage=False,
                preserve_remaining=False, unlimited_volume=False,
                **(user_kwargs or {}),
            )
        except Exception as exc:
            logger.exception("multi-panel renewal: extra panel renew failed (pool=%s, link=%s)",
                             pool["id"], link["id"])
            failed_links.append((link, exc))
    if failed_links:
        _report_failed_link_renewals(db, pool, failed_links, add_days)
    new_limit_gb = _renew_quota_pool(db, pool, mode, add_volume, add_days, fresh=fresh)
    try:
        from quota_reconciler import QuotaReconciler
        reconciler = QuotaReconciler(db)
        await reconciler.push_pool_expiry(pool["id"])
        await reconciler.reconcile_pool(db.get_quota_pool(pool["id"]))
    except Exception:
        logger.exception("combined renewal: post-renew pool sync failed (pool=%s)", pool["id"])
    return new_limit_gb
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


class RenewalError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین در فرایند تمدید سرویس."""
    pass


def _carry_flags(order):
    """(carry_volume, carry_time) از snapshot سفارش؛ NULL یعنی رفتار قدیمی (انتقال)."""
    keys = order.keys() if hasattr(order, "keys") else ()
    def flag(name):
        value = order[name] if name in keys else None
        return True if value is None else bool(value)
    return flag("renewal_carry_volume"), flag("renewal_carry_time")


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
        # مقصد اختصاصیِ محصول در زمان ساخت سرویس روی خود رکورد سرویس snapshot شده؛
        # برای تمدید همان مقصد اعمال می‌شود. سرویس‌های قدیمی مقدار NULL دارند و
        # دقیقاً مثل قبل از تنظیمات سراسری پنل استفاده می‌کنند.
        try:
            from product_targets import apply_target_config
            server = apply_target_config(server, cc["panel_target_config"])
        except (KeyError, IndexError, TypeError):
            pass
        set_volume_gb = None
        renewal_users = order["renewal_user_limit"] if "renewal_user_limit" in order.keys() else None
        if mode == "users":
            if not renewal_users:
                raise RenewalError("تعداد کاربر درخواستی نامعتبر است.")
            try:
                provider = get_provider(server)
                if not getattr(provider, "supports_user_limit", False):
                    raise RenewalError("پنل این سرویس از محدودیت کاربر پشتیبانی نمی‌کند.")
                await provider.update_user(cc["username"], **provider_kwargs(provider, renewal_users))
                await _update_panel_links_user_limit(db, cc["id"], renewal_users)
            except PanelError as e:
                raise RenewalError(str(e)) from e
            db.set_custom_config_user_limit(cc["id"], renewal_users)
            renewal_log.notify(db, order, cc["display_name"] or cc["username"])
            return f"✅ تعداد کاربر همزمان سرویس شما به {renewal_users} افزایش یافت."
        try:
            provider = get_provider(server)
            before = await renewal_log.service_snapshot(db, cc, provider)
            # تمدید کامل: مصرف ریست نمی‌شود؛ حجم بسته‌ی جدید مستقیماً روی سقف قبلی جمع می‌شود
            # (در نتیجه حجم باقیمانده + بسته‌ی جدید)، دقیقاً مثل زمان که روی زمان باقیمانده جمع می‌شود.
            # فرمول قبلی (سقف = باقیمانده + بسته، سپس ریست مصرف) به موفق‌شدن مرحله‌ی ریست وابسته بود؛
            # اگر ریست اعمال نمی‌شد، باقیمانده‌ی نهایی می‌شد «دو برابرِ باقیمانده‌ی قبلی» و بسته‌ی جدید گم می‌شد.
            # فقط وقتی سقف فعلی مشخص و محدود نباشد (سرویس نامحدود/وضعیت نامعلوم)، رفتار قبلی حفظ می‌شود.
            reset_usage = (mode == "full")
            preserve_remaining = (mode == "full")
            # قوانین «تمدید کامل» محصول (snapshot روی سفارش)؛ NULL = رفتار قدیمی (انتقال هر دو).
            carry_volume, carry_time = _carry_flags(order)
            if mode == "full" and add_volume and before.get("total_bytes") and carry_volume:
                reset_usage = False
                preserve_remaining = False
            if mode == "full" and not carry_volume:
                # بدون انتقال حجم: مصرف صفر و سقف دقیقاً بسته‌ی جدید (حجم باقیمانده حذف می‌شود).
                reset_usage = True
                preserve_remaining = False
            panel_add_days = add_days
            time_reset_applied = False
            if mode == "full" and not carry_time and add_days:
                seconds_left = before.get("seconds_left")
                if seconds_left is not None and seconds_left > 0:
                    # پروایدرها روی زمان باقیمانده «جمع» می‌کنند؛ برای ریست زمان، مقدار باقیمانده
                    # از روزهای بسته‌ی جدید کم می‌شود تا انقضا ≈ اکنون + روزهای بسته‌ی جدید شود.
                    panel_add_days = int(round(add_days - seconds_left / 86400.0))
                    time_reset_applied = True
            # پلن با حجم ۰ یعنی «نامحدود»: در تمدید کامل/حجم باید سقف حجم سرویس هم نامحدود شود
            # (قبلاً add_volume=0 فقط «بدون تغییر حجم» تلقی می‌شد و فقط زمان اضافه می‌شد).
            unlimited_volume = mode in ("full", "volume") and not add_volume
            if unlimited_volume:
                preserve_remaining = False
            pool = db.quota_pool_for_custom_config(cc["id"])
            if pool:
                # سرویس ترکیبی VPN+SSH: سقف/انقضای واقعی در استخر مشترک است. روی پنل فقط زمان
                # تمدید می‌شود (حجم پنل را reconciler از استخر می‌سازد) و مصرف ریست نمی‌شود.
                new_pool_limit_gb = await renew_pooled_service(
                    db, provider, cc["username"], pool, mode, add_volume, add_days,
                    user_kwargs=provider_kwargs(provider, renewal_users),
                )
                set_volume_gb = new_pool_limit_gb
            else:
                await provider.update_user(
                    cc["username"], add_volume_gb=add_volume, add_days=panel_add_days, reset_usage=reset_usage,
                    preserve_remaining=preserve_remaining, unlimited_volume=unlimited_volume,
                    **provider_kwargs(provider, renewal_users),
                )
            if pool:
                pass
            elif unlimited_volume:
                set_volume_gb = 0
            elif mode == "full" and add_volume and not carry_volume:
                # بدون انتقال حجم: سقف جدید دقیقاً بسته‌ی محصول است.
                set_volume_gb = add_volume
            elif mode == "full" and add_volume:
                # سقف واقعیِ بعد از preserve_remaining را از خود پنل می‌خوانیم تا رکورد‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
                # محلی دقیقاً هم‌سو با پنل بماند (نه با محاسبه‌ی جداگانه و احتمالاً ناهم‌خوان).‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
                usage = await provider.get_user_usage(cc["username"])
                set_volume_gb = usage["data_limit_bytes"] / (1024 ** 3)
        except PanelError as e:
            raise RenewalError(str(e)) from e
        db.apply_custom_config_renewal(
            cc["id"], add_volume, add_days, full_reset=(mode == "full"), set_volume_gb=set_volume_gb,
            reset_time=(time_reset_applied and not pool),
        )
        if renewal_users and getattr(provider, "supports_user_limit", False):
            db.set_custom_config_user_limit(cc["id"], renewal_users)
        updated = db.get_custom_config_owned(cc["id"], order["user_id"]) or cc
        renewal_log.notify(db, order, cc["display_name"] or cc["username"], before, updated, provider)
        return "✅ سرویس شما با موفقیت تمدید شد."

    if kind == "config":
        new_expiry = db.extend_pool_config_expiry(target_id, order["user_id"], add_days)
        if not new_expiry:
            raise RenewalError("این سرویس دیگر یافت نشد (شاید قبلاً حذف شده).")
        renewal_log.notify(db, order, "کانفیگ بانک")
        return "✅ سرویس شما با موفقیت تمدید شد."

    raise RenewalError("نوع سرویس برای تمدید نامعتبر است.")
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
