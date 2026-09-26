# -*- coding: utf-8 -*-
"""
هشدار اتصال / عدم‌اتصال به کانفیگ

هیچ‌کدام از پنل‌های VPN پشتیبانی‌شده وضعیت آنلاین/آفلاین لحظه‌ای (handshake)
را گزارش نمی‌کنند؛ بنابراین «اتصال» از روی مصرفِ زنده‌ی Subscription تشخیص
داده می‌شود:

- هشدار اتصال: اولین باری که مصرف سرویس از آستانه‌ی تنظیم‌شده (پیش‌فرض ۱
  مگابایت، یعنی عملاً «هر مصرفی غیر از صفر») بیشتر شود، یک‌بار به کاربر
  پیام می‌رود.
- هشدار عدم‌اتصال: اگر از لحظه‌ی فعال‌سازی سرویس (assigned_at/created_at) به
  اندازه‌ی N ساعتِ تنظیم‌شده گذشته باشد و مصرف هنوز به آستانه نرسیده باشد،
  یک‌بار پیام هشدار برای کاربر ارسال می‌شود.

این ماژول دقیقاً از الگوی renewal_reminders.py پیروی می‌کند تا با همان چرخه‌ی
پس‌زمینه (renewal_reminder_loop در bot_manager.py) هماهنگ باشد.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sub_info import fetch_sub_info
from notification_i18n import send_telegram

logger = logging.getLogger(__name__)


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)

# کلیدهای settings برای نمایش فقط‌خواندنیِ وضعیت آخرین اجرا در پنل وب مدیریت
STATUS_KEY_LAST_RUN = "_job_connect_alerts_last_run"
STATUS_KEY_LAST_CONNECT_SENT = "_job_connect_alerts_last_connect_sent"
STATUS_KEY_LAST_NO_CONNECT_SENT = "_job_connect_alerts_last_no_connect_sent"


def _format_alert_text(template: str, used_gb: float, threshold_gb: float) -> str:
    try:
        return template.format(used_gb=f"{used_gb:.2f}", threshold_gb=f"{threshold_gb:.3f}")
    except Exception:
        # اگر ادمین placeholder نامعتبری در متن گذاشته باشد، متن خام ارسال شود
        # به‌جای کرش کردن کل چرخه.
        return template


async def _process_row(bot, db, row, is_custom: bool, settings: dict) -> tuple:
    """یک ردیف (کانفیگ ثابت یا پنلی) را بررسی می‌کند.
    خروجی: (connect_sent: bool, no_connect_sent: bool)"""
    user_id = row["assigned_user_id"]
    config_id = row["config_id"]
    if not user_id:
        return False, False

    need_connect_check = settings["connect_enabled"] and not row["connect_alert_sent"]
    need_no_connect_check = settings["no_connect_enabled"] and not row["no_connect_alert_sent"]
    if not (need_connect_check or need_no_connect_check):
        return False, False

    info = await fetch_sub_info(row["link"])
    if not info.get("ok"):
        logger.warning(
            "اطلاعات مصرف Subscription برای config=%s (custom=%s) قابل دریافت نیست؛ "
            "هشدار اتصال/عدم‌اتصال بررسی نمی‌شود.",
            config_id, is_custom,
        )
        return False, False

    used_bytes = (info.get("upload") or 0) + (info.get("download") or 0)
    used_gb = used_bytes / (1024 ** 3)

    if is_custom and row["start_on_first_use"] and used_bytes > 0:
        try:
            server = await _db(db.get_panel_server, row["panel_server_id"])
            if server:
                from panel_providers import get_provider
                provider = get_provider(server)
                panel_info = await provider.get_user_usage(row["username"])
                panel_expiry = panel_info.get("expires_at")
                if panel_expiry:
                    if isinstance(panel_expiry, (int, float)):
                        expiry_dt = datetime.fromtimestamp(float(panel_expiry), tz=timezone.utc).isoformat()
                    else:
                        expiry_dt = str(panel_expiry).replace("Z", "+00:00")
                    await _db(db.sync_custom_config_expiry, config_id, expiry_dt)
        except Exception:
            logger.debug("همگام‌سازی انقضای On-hold برای config=%s ناموفق بود.", config_id, exc_info=True)

    connect_sent = False
    no_connect_sent = False

    # --- هشدار اتصال ---
    if need_connect_check:
        threshold_bytes = settings["connect_threshold_mb"] * (1024 ** 2)
        if used_bytes >= threshold_bytes:
            text = _format_alert_text(
                settings["connect_text"], used_gb, settings["connect_threshold_mb"] / 1024,
            )
            try:
                await send_telegram(bot, db, user_id, text)
            except Exception:
                logger.warning("ارسال هشدار اتصال به کاربر %s ناموفق بود.", user_id)
            await _db(db.mark_connect_alert_sent, config_id, is_custom)
            connect_sent = True

    # --- هشدار عدم‌اتصال ---
    if need_no_connect_check and not connect_sent and used_bytes < settings["connect_threshold_mb"] * (1024 ** 2):
        assigned_at_raw = row["assigned_at"]
        if assigned_at_raw:
            try:
                assigned_dt = datetime.fromisoformat(assigned_at_raw.replace("Z", "+00:00"))
                if assigned_dt.tzinfo is None:
                    assigned_dt = assigned_dt.replace(tzinfo=timezone.utc)
                hours_passed = (datetime.now(timezone.utc) - assigned_dt).total_seconds() / 3600
                no_connect_threshold_bytes = settings["no_connect_threshold_mb"] * (1024 ** 2)
                if hours_passed >= settings["no_connect_hours"] and used_bytes < no_connect_threshold_bytes:
                    text = _format_alert_text(
                        settings["no_connect_text"], used_gb, settings["no_connect_threshold_mb"] / 1024,
                    )
                    try:
                        await send_telegram(bot, db, user_id, text)
                    except Exception:
                        logger.warning("ارسال هشدار عدم‌اتصال به کاربر %s ناموفق بود.", user_id)
                    await _db(db.mark_no_connect_alert_sent, config_id, is_custom)
                    no_connect_sent = True
            except (ValueError, TypeError):
                logger.warning("assigned_at نامعتبر برای config=%s (custom=%s)", config_id, is_custom)

    return connect_sent, no_connect_sent


async def sync_onhold_expiries(db) -> int:
    """حتی وقتی هشدار اتصال خاموش است، اولین مصرف را برای سرویس‌های On-hold
    پیدا می‌کند و تاریخ واقعی انقضا را از پنل در DB ذخیره می‌کند."""
    try:
        rows = await _db(db.get_custom_configs_due_for_onhold_sync)
    except Exception:
        logger.exception("دریافت سرویس‌های On-hold برای sync ناموفق بود")
        return 0
    synced = 0
    for row in rows:
        try:
            server = await _db(db.get_panel_server, row["panel_server_id"])
            if not server:
                continue
            from panel_providers import get_provider
            provider = get_provider(server)
            usage = await provider.get_user_usage(row["username"])
            if not ((usage.get("used_bytes") or 0) > 0):
                continue
            expiry = usage.get("expires_at")
            if not expiry:
                continue
            if isinstance(expiry, (int, float)):
                expiry = datetime.fromtimestamp(float(expiry), tz=timezone.utc).isoformat()
            else:
                expiry = str(expiry).replace("Z", "+00:00")
            if await _db(db.sync_custom_config_expiry, row["config_id"], expiry):
                synced += 1
        except Exception:
            logger.debug("sync On-hold برای config=%s ناموفق بود.", row["config_id"], exc_info=True)
    return synced


async def check_and_send_connect_alerts(bot, db) -> tuple:
    """یک بار همه‌ی سرویس‌های فعال (انبار کانفیگ + کانفیگ‌های پنلی) را بررسی
    می‌کند. خروجی: (تعداد هشدار اتصال ارسال‌شده, تعداد هشدار عدم‌اتصال ارسال‌شده)"""
    await sync_onhold_expiries(db)
    settings = await _db(db.get_connect_alert_settings)
    if not (settings["connect_enabled"] or settings["no_connect_enabled"]):
        return 0, 0

    connect_sent = 0
    no_connect_sent = 0

    try:
        rows = await _db(db.get_configs_due_for_connect_check)
    except Exception:
        logger.exception("خطا در دریافت لیست بررسی اتصال (انبار کانفیگ)")
        rows = []
    for row in rows:
        c, n = await _process_row(bot, db, row, is_custom=False, settings=settings)
        connect_sent += int(c)
        no_connect_sent += int(n)

    try:
        custom_rows = await _db(db.get_custom_configs_due_for_connect_check)
    except Exception:
        logger.exception("خطا در دریافت لیست بررسی اتصال (کانفیگ‌های پنلی)")
        custom_rows = []
    for row in custom_rows:
        c, n = await _process_row(bot, db, row, is_custom=True, settings=settings)
        connect_sent += int(c)
        no_connect_sent += int(n)

    return connect_sent, no_connect_sent


async def connect_alert_loop(bot, db, interval_seconds: int = 900) -> None:
    """در پس‌زمینه، به‌صورت دوره‌ای (پیش‌فرض هر ۱۵ دقیقه - بازه‌ی کوتاه‌تر از
    یادآوری تمدید، چون تشخیص «عدم‌اتصال بعد از N ساعت» به دقت زمانی بیشتری
    نیاز دارد) هشدارهای اتصال/عدم‌اتصال را بررسی و ارسال می‌کند."""
    while True:
        connect_sent = 0
        no_connect_sent = 0
        try:
            connect_sent, no_connect_sent = await check_and_send_connect_alerts(bot, db)
        except Exception:
            logger.exception("خطا در چرخه‌ی هشدار اتصال/عدم‌اتصال به کانفیگ")
        try:
            await _db(db.set_setting, STATUS_KEY_LAST_RUN, datetime.now(timezone.utc).isoformat())
            await _db(db.set_setting, STATUS_KEY_LAST_CONNECT_SENT, str(connect_sent))
            await _db(db.set_setting, STATUS_KEY_LAST_NO_CONNECT_SENT, str(no_connect_sent))
        except Exception:
            logger.exception("خطا در ذخیره‌ی وضعیت آخرین اجرای هشدار اتصال/عدم‌اتصال")
        await asyncio.sleep(interval_seconds)
