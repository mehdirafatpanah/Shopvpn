from i18n import tr
from notification_i18n import send_telegram
# -*- coding: utf-8 -*-
"""
یادآوری خودکار اتمام سرویس + کد تخفیف تشویقی تمدید

این ماژول به‌صورت دوره‌ای (برای هر بات، مستقل و روی دیتابیس خودش) بررسی می‌کند
که آیا زمان انقضای واقعی Subscription کانفیگ فروخته‌شده به بازه یادآوری رسیده یا نه
(طبق تنظیم «چند روز قبل» در پنل مدیریت → «🔔 یادآوری تمدید سرویس»). به هر کاربری که سرویسش رو به
اتمام است، دقیقاً یک‌بار پیام یادآوری همراه با یک کد تخفیف اختصاصی و محدود به
زمان ارسال می‌شود.
"""

import asyncio
import logging
from datetime import datetime, timezone

# کلیدهای settings برای نمایش فقط‌خواندنیِ وضعیت آخرین اجرا در پنل وب مدیریت
# (زمان‌بندی خودش هاردکد است و از پنل قابل تغییر نیست؛ فقط برای دیده‌شدن است)
STATUS_KEY_LAST_RUN = "_job_renewal_last_run"
STATUS_KEY_LAST_DATE_SENT = "_job_renewal_last_date_sent"
STATUS_KEY_LAST_VOLUME_SENT = "_job_renewal_last_volume_sent"

from sub_info import fetch_sub_info
from jalali import to_jalali_str
import report_router

logger = logging.getLogger(__name__)


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _live_info(link, cache):
    if link in cache:
        return cache[link]
    info = await fetch_sub_info(link)
    cache[link] = info
    return info


async def _prefetch_live_info(rows, cache, limit: int = 10) -> None:
    sem = asyncio.Semaphore(limit)

    async def one(link):
        async with sem:
            cache[link] = await fetch_sub_info(link)

    links = {r["link"] for r in rows if r["link"] and r["link"] not in cache}
    if links:
        await asyncio.gather(*(one(link) for link in links))


async def _send_single_reminder(bot, db, row, mark_fn, cache) -> bool:
    user_id = row["assigned_user_id"]
    if not user_id:
        return False

    settings = await _db(db.get_renewal_settings)

    # زمان انقضا فقط از Subscription واقعی خوانده می‌شود.
    # cf.expires_at دیتابیس نباید روی زمان ارسال یادآوری اثر بگذارد.
    info = await _live_info(row["link"], cache)
    if not info.get("ok"):
        logger.warning(
            "زمان انقضای واقعی Subscription برای config=%s قابل دریافت نیست؛ "
            "یادآوری ارسال نمی‌شود.",
            row["config_id"],
        )
        return False
    if not info.get("expire"):
        return False

    try:
        expire_ts = float(info["expire"])
    except (TypeError, ValueError):
        logger.warning(
            "expire نامعتبر برای config=%s؛ یادآوری ارسال نمی‌شود.",
            row["config_id"],
        )
        return False

    now = datetime.now(timezone.utc)
    exp_dt = datetime.fromtimestamp(expire_ts, tz=timezone.utc)
    seconds_left = expire_ts - now.timestamp()
    reminder_window = settings["days_before"] * 24 * 60 * 60

    # هنوز وارد بازه یادآوری نشده است (مثلاً تمدید شده)؛ پرچم قبلی آزاد می‌شود.
    if seconds_left > reminder_window:
        if row["sent"]:
            await _db(mark_fn, row["config_id"], 0)
        return False

    # کانفیگ منقضی شده است؛ یادآوری ارسال نکن.
    if seconds_left <= 0:
        return False

    if row["sent"]:
        return False

    # محاسبه فقط برای نمایش پیام است؛ شرط ارسال با ثانیه انجام می‌شود.
    real_days_left = int(seconds_left // (24 * 60 * 60))
    days_left = max(0, real_days_left)

    code, discount_expires_at, percent, expiry_hours = await _db(db.generate_renewal_discount_code, user_id)

    days_line = (
        f"⌛ حدود {days_left} روز از سرویس شما باقی مانده (انقضا: {to_jalali_str(exp_dt)}).\n\n"
        if days_left is not None else ""
    )

    text = (
        "⏰ یادآوری اتمام سرویس\n\n"
        f"📦 سرویس «{row['product_name']}» شما به‌زودی منقضی می‌شود.\n\n"
        f"{days_line}"
        f"🎁 برای اینکه دچار قطعی نشوید، یک کد تخفیف اختصاصی {percent}٪ برایتان صادر شد:\n"
        f"🎟 کد تخفیف: `{code}`\n"
        f"⏳ این کد فقط تا {expiry_hours} ساعت آینده معتبر است.\n\n"
        "✅ اگر همین امروز تمدید کنید، از این تخفیف بهره‌مند خواهید شد.\n"
        "برای تمدید، از منوی اصلی «🛒 خرید کانفیگ» را بزنید و هنگام خرید، دکمه‌ی "
        "«🎟 وارد کردن کد تخفیف» را زده و این کد را وارد کنید."
    )

    try:
        await send_telegram(bot, db, user_id, text, parse_mode="Markdown")
    except Exception:
        logger.warning("ارسال یادآوری تمدید به کاربر %s ناموفق بود.", user_id)

    # صرف‌نظر از موفقیت ارسال پیام، برای جلوگیری از تلاش‌های مکرر، به‌عنوان ارسال‌شده علامت می‌زنیم
    await _db(mark_fn, row["config_id"])
    return True


async def check_and_send_renewal_reminders(bot, db, cache=None) -> int:
    """یک بار کانفیگ‌ها را بررسی می‌کند و زمان‌بندی را فقط از Subscription واقعی می‌خواند.
    هم انبار کانفیگ ثابت و هم کانفیگ‌های ساخته‌شده مستقیم روی پنل VPN بررسی می‌شوند.
    تعداد یادآوری‌هایی که واقعاً ارسال شدند را برمی‌گرداند."""
    sent = 0
    cache = {} if cache is None else cache
    try:
        rows = await _db(db.get_configs_due_for_renewal_reminder)
    except Exception:
        logger.exception("خطا در دریافت لیست یادآوری‌های تمدید سرویس (انبار کانفیگ)")
        rows = []
    try:
        custom_rows = await _db(db.get_custom_configs_due_for_renewal_reminder)
    except Exception:
        logger.exception("خطا در دریافت لیست یادآوری‌های تمدید سرویس (کانفیگ‌های پنلی)")
        custom_rows = []
    await _prefetch_live_info(list(rows) + list(custom_rows), cache)

    for row in rows:
        if await _send_single_reminder(bot, db, row, db.mark_renewal_reminder_sent, cache):
            sent += 1
    for row in custom_rows:
        if await _send_single_reminder(bot, db, row, db.mark_custom_config_renewal_reminder_sent, cache):
            sent += 1

    return sent


async def _send_single_volume_reminder(bot, db, row, mark_fn, cache) -> bool:
    user_id = row["assigned_user_id"]
    if not user_id:
        return False

    settings = await _db(db.get_volume_reminder_settings)

    info = await _live_info(row["link"], cache)
    if not info.get("ok"):
        logger.warning(
            "اطلاعات مصرف Subscription برای config=%s قابل دریافت نیست؛ "
            "یادآوری حجم ارسال نمی‌شود.",
            row["config_id"],
        )
        return False

    total = info.get("total") or 0
    # کانفیگ‌های نامحدود مبنای حجمی ندارند؛ فقط یادآوری تاریخ انقضا برایشان معتبر است.
    if total <= 0:
        return False

    used = (info.get("upload") or 0) + (info.get("download") or 0)
    remaining_gb = max(0, total - used) / (1024 ** 3)
    percent_used = min(100, (used / total) * 100) if total else 0

    if settings["mode"] == "gb":
        due = remaining_gb <= settings["gb_left"]
    else:
        due = percent_used >= settings["percent"]

    if not due:
        if row["sent"]:
            await _db(mark_fn, row["config_id"], 0)
        return False

    if row["sent"]:
        return False

    code, discount_expires_at, percent, expiry_hours = await _db(db.generate_volume_discount_code, user_id)

    text = (
        "📉 یادآوری اتمام حجم\n\n"
        f"📦 حجم سرویس «{row['product_name']}» شما رو به اتمام است.\n\n"
        f"📊 حدود {remaining_gb:.2f} گیگابایت ({100 - round(percent_used)}٪) از حجم شما باقی مانده.\n\n"
        f"🎁 برای اینکه دچار قطعی نشوید، یک کد تخفیف اختصاصی {percent}٪ برایتان صادر شد:\n"
        f"🎟 کد تخفیف: `{code}`\n"
        f"⏳ این کد فقط تا {expiry_hours} ساعت آینده معتبر است.\n\n"
        "✅ اگر همین امروز تمدید کنید، از این تخفیف بهره‌مند خواهید شد.\n"
        "برای تمدید، از منوی اصلی «🛒 خرید کانفیگ» را بزنید و هنگام خرید، دکمه‌ی "
        "«🎟 وارد کردن کد تخفیف» را زده و این کد را وارد کنید."
    )

    try:
        await send_telegram(bot, db, user_id, text, parse_mode="Markdown")
    except Exception:
        logger.warning("ارسال یادآوری اتمام حجم به کاربر %s ناموفق بود.", user_id)

    await _db(mark_fn, row["config_id"])
    return True


async def check_and_send_volume_reminders(bot, db, cache=None) -> int:
    """یک بار کانفیگ‌ها را بررسی می‌کند و بر اساس مصرف زنده‌ی Subscription، یادآوری اتمام حجم می‌فرستد.
    هم انبار کانفیگ ثابت و هم کانفیگ‌های ساخته‌شده مستقیم روی پنل VPN بررسی می‌شوند.
    تعداد یادآوری‌هایی که واقعاً ارسال شدند را برمی‌گرداند."""
    sent = 0
    cache = {} if cache is None else cache
    try:
        rows = await _db(db.get_configs_due_for_volume_reminder)
    except Exception:
        logger.exception("خطا در دریافت لیست یادآوری‌های اتمام حجم (انبار کانفیگ)")
        rows = []
    try:
        custom_rows = await _db(db.get_custom_configs_due_for_volume_reminder)
    except Exception:
        logger.exception("خطا در دریافت لیست یادآوری‌های اتمام حجم (کانفیگ‌های پنلی)")
        custom_rows = []
    await _prefetch_live_info(list(rows) + list(custom_rows), cache)

    for row in rows:
        if await _send_single_volume_reminder(bot, db, row, db.mark_volume_reminder_sent, cache):
            sent += 1
    for row in custom_rows:
        if await _send_single_volume_reminder(bot, db, row, db.mark_custom_config_volume_reminder_sent, cache):
            sent += 1

    return sent


async def check_and_process_auto_renewals(bot, db) -> int:
    """کانفیگ‌های مستقیم-پنل که «تمدید خودکار» برایشان فعال است و نزدیک انقضا
    هستند را بررسی می‌کند: در صورت کافی‌بودن موجودی کیف پول، همان حجم/مدت
    فعلی‌شان را دوباره روی پنل و در دیتابیس تمدید می‌کند (و از کیف پول کسر
    می‌کند)؛ در غیر این صورت یک‌بار در روز به کاربر هشدار کمبود موجودی
    می‌فرستد. تعداد تمدیدهای موفق را برمی‌گرداند."""
    from panel_providers import get_provider, PanelError

    renewed = 0
    try:
        rows = await _db(db.get_custom_configs_due_for_auto_renew)
    except Exception:
        logger.exception("خطا در دریافت لیست تمدید خودکار کانفیگ‌های پنلی")
        rows = []

    price_per_gb = int(await _db(db.get_setting, "renewal_price_per_gb", "0") or "0")
    price_per_day = int(await _db(db.get_setting, "renewal_price_per_day", "0") or "0")
    today = datetime.now(timezone.utc).date().isoformat()

    for row in rows:
        user_id = row["user_id"]
        volume_gb = row["volume_gb"] or 0
        duration_days = row["duration_days"] or 0
        price = volume_gb * price_per_gb + duration_days * price_per_day
        label = row["display_name"] if ("display_name" in row.keys() and row["display_name"]) else row["username"]

        wallet_credit = await _db(db.get_wallet_credit, user_id)
        plan = await _db(db.plan_wallet_spend, user_id, price)
        if price <= 0 or plan["wallet_used"] < price:
            if row["auto_renew_alert_date"] != today:
                try:
                    await send_telegram(
                        bot, db, user_id,
                        tr(f"⚠️ تمدید خودکار کانفیگ «{label}» به‌دلیل کمبود موجودی کیف پول انجام نشد.\n"
                        f"مبلغ لازم: {price:,} تومان — موجودی فعلی: {wallet_credit:,} تومان.\n"
                        "لطفاً کیف پول خود را شارژ کنید یا تمدید خودکار را از صفحه‌ی سرویس خاموش کنید."),
                    )
                except Exception:
                    logger.warning("ارسال هشدار کمبود موجودی تمدید خودکار به کاربر %s ناموفق بود.", user_id)
                await _db(db.mark_custom_config_auto_renew_alert, row["id"], today)
            continue

        server = await _db(db.get_panel_server, row["panel_server_id"]) if row["panel_server_id"] else None
        if not server or not server["is_active"]:
            if row["auto_renew_alert_date"] != today:
                try:
                    await send_telegram(
                        bot, db, user_id,
                        tr(f"⚠️ تمدید خودکار کانفیگ «{label}» انجام نشد؛ سرور پنل این سرویس غیرفعال یا حذف شده است.\n"
                        "لطفاً با پشتیبانی تماس بگیرید."),
                    )
                except Exception:
                    logger.warning("ارسال هشدار تمدید خودکار (سرور غیرفعال) به کاربر %s ناموفق بود.", user_id)
                try:
                    await report_router.send_text(
                        bot, db, "service",
                        f"⚠️ تمدید خودکار کانفیگ «{label}» (کاربر {user_id}) انجام نشد: "
                        f"سرور پنل #{row['panel_server_id']} غیرفعال یا حذف شده است.",
                    )
                except Exception:
                    logger.warning("ارسال گزارش ادمین برای تمدید خودکار ناموفق (سرور غیرفعال) شکست خورد.")
                await _db(db.mark_custom_config_auto_renew_alert, row["id"], today)
            continue
        if not await _db(db.deduct_wallet_credit, user_id, price, True):
            continue
        try:
            provider = get_provider(server)
            await provider.update_user(row["username"], add_volume_gb=volume_gb, add_days=duration_days, reset_usage=True)
        except PanelError:
            logger.exception("تمدید خودکار روی پنل برای کانفیگ «%s» ناموفق بود.", row["username"])
            await _db(db.add_wallet_credit, user_id, price, "order_refund", "بازگشت وجه تمدید خودکار ناموفق")
            continue
        except Exception:
            await _db(db.add_wallet_credit, user_id, price, "order_refund", "بازگشت وجه تمدید خودکار ناموفق")
            raise

        await _db(db.apply_custom_config_renewal, row["id"], add_volume_gb=0, add_days=duration_days, full_reset=True)
        await _db(
            db.add_custom_config_history,
            row["id"], "auto_renew", f"{volume_gb} گیگ / {duration_days} روز — {price:,} تومان از کیف پول",
        )
        renewed += 1
        try:
            await send_telegram(
                bot, db, user_id,
                tr(f"🔄 کانفیگ «{label}» با موفقیت به‌صورت خودکار تمدید شد و {price:,} تومان از کیف پول شما کسر شد."),
            )
        except Exception:
            logger.warning("ارسال تاییدیه‌ی تمدید خودکار به کاربر %s ناموفق بود.", user_id)

    return renewed


async def renewal_reminder_loop(bot, db, interval_seconds: int = 3600) -> None:
    """در پس‌زمینه، به‌صورت دوره‌ای (پیش‌فرض هر ۱ ساعت) بررسی و یادآوری‌های تاریخ انقضا و اتمام حجم را ارسال می‌کند.
    برای نمایش فقط‌خواندنی در پنل وب، بعد از هر چرخه‌ی کامل، زمان و تعداد یادآوری‌های
    ارسال‌شده در settings ذخیره می‌شود (این مقدار کنترل زمان‌بندی نیست، فقط وضعیت است)."""
    while True:
        date_sent = 0
        volume_sent = 0
        cache = {}
        try:
            await check_and_process_auto_renewals(bot, db)
        except Exception:
            logger.exception("خطا در چرخه‌ی تمدید خودکار کانفیگ‌های پنلی")
        try:
            date_sent = await check_and_send_renewal_reminders(bot, db, cache)
        except Exception:
            logger.exception("خطا در چرخه‌ی یادآوری تمدید سرویس")
        try:
            volume_sent = await check_and_send_volume_reminders(bot, db, cache)
        except Exception:
            logger.exception("خطا در چرخه‌ی یادآوری اتمام حجم")
        try:
            await _db(db.set_setting, STATUS_KEY_LAST_RUN, datetime.now(timezone.utc).isoformat())
            await _db(db.set_setting, STATUS_KEY_LAST_DATE_SENT, str(date_sent))
            await _db(db.set_setting, STATUS_KEY_LAST_VOLUME_SENT, str(volume_sent))
        except Exception:
            logger.exception("خطا در ذخیره‌ی وضعیت آخرین اجرای یادآوری‌ها")
        await asyncio.sleep(interval_seconds)
