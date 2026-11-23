# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""گزارش روزانه‌ی فروش برای مدیران، در ساعت تنظیم‌شده به وقت تهران (پیش‌فرض ۲۳:۴۵)."""

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

import report_router
from jalali import to_jalali_str, to_jalali_month_day

try:
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:
    TEHRAN = timezone(timedelta(hours=3, minutes=30))

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
DEFAULT_TIME = (23, 45)
STATUS_KEY_LAST_DATE = "_job_daily_report_last_date"
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def parse_report_time(value: str) -> tuple:
    try:
        hour, minute = (int(part) for part in str(value).strip().split(":"))
    except ValueError:
        return DEFAULT_TIME
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return DEFAULT_TIME


def _fmt_change_pct(pct) -> str:
    if pct is None:
        return "🆕 دیروز فروشی نبود"
    if pct > 0:
        return f"📈 +{pct}٪"
    if pct < 0:
        return f"📉 {pct}٪"
    return "➖ ۰٪"


BAR_CHART_BLOCKS = "▁▂▃▄▅▆▇█"


def _build_week_bar_chart(daily_series: list) -> str:
    """نمودار میله‌ای متنی فروش ۷ روز اخیر (فاز ۵) - بدون نیاز به تصویر،
    فقط با کاراکترهای یونیکد؛ هر روز یک ستون، ارتفاع نسبت به بیشترین روز."""
    if not daily_series:
        return ""
    max_revenue = max((d["revenue"] for d in daily_series), default=0)
    lines = ["📊 نمودار فروش ۷ روز اخیر:"]
    for d in daily_series:
        if max_revenue <= 0:
            level = 0
        else:
            level = round(d["revenue"] / max_revenue * (len(BAR_CHART_BLOCKS) - 1))
        bar = BAR_CHART_BLOCKS[level] * 8
        label = to_jalali_month_day(d["date"])
        lines.append(f"{label} {bar} {d['revenue']:,} تومان ({d['orders']:,} سفارش)")
    return "\n".join(lines)


def _build_payment_breakdown(breakdown: dict) -> str:
    """تفکیک فروش امروز بر اساس روش پرداخت (فاز ۵)."""
    if not breakdown:
        return ""
    rows = sorted(breakdown.items(), key=lambda kv: kv[1]["revenue"], reverse=True)
    lines = ["💳 تفکیک پرداخت امروز:"]
    lines += [
        f"• {label}: {info['count']:,} سفارش، {info['revenue']:,} تومان"
        for label, info in rows
    ]
    return "\n".join(lines)


def build_report_text(db, now_tehran: datetime) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = db.get_sales_stats(day, day)
    extras = db.get_daily_report_extras(day)
    week_start = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d")
    week_stats = db.get_sales_stats(week_start, day)
    store = html.escape(db.get_setting("store_name", "") or "")
    lines = [
        f"📊 گزارش روزانه‌ی فروش{' - ' + store if store else ''}",
        f"📅 {WEEKDAYS_FA[now_tehran.weekday()]} {to_jalali_str(now_tehran)}",
        "",
        f"🛒 سفارش تاییدشده: {stats['approved']:,}",
        f"💰 درآمد: {stats['revenue']:,} تومان (فروش: {stats['orders_revenue']:,} + شارژ کیف پول: {stats['topup_revenue']:,})",
        f"🧾 میانگین سبد خرید: {stats['aov']:,} تومان",
        f"{_fmt_change_pct(stats['revenue_change_pct'])} نسبت به دیروز ({stats['prev_revenue']:,} تومان)",
        f"⏳ در انتظار: {stats['pending']:,} | ❌ ردشده: {stats['rejected']:,}",
        f"💳 شارژ کیف پول: {extras['topup_count']:,} مورد، {extras['topup_amount']:,} تومان",
        f"🧪 کانفیگ تست: {extras['test_count']:,}",
        f"👥 کاربر جدید: {stats['new_users']:,}",
        f"🎯 اولین خرید: {extras['first_purchase_count']:,} کاربر",
        f"🟢 کاربران فعال: {extras['active_users_count']:,} | ⚪️ غیرفعال: {extras['inactive_users_count']:,}",
        f"🤝 رفرال جدید امروز: {extras['referral_new_count']:,} نفر",
    ]
    conv = extras.get("signup_purchase_conversion_pct")
    if conv is not None:
        lines.append(f"🔁 نرخ تبدیل ثبت‌نام→خرید (همان روز): {conv}٪ (از {extras['signup_today_count']:,} ثبت‌نام)")
    if extras["best_hour"] is not None:
        lines.append(f"🕐 پرفروش‌ترین ساعت امروز: {extras['best_hour']:02d}:00 تا {extras['best_hour']+1:02d}:00 ({extras['best_hour_orders']:,} سفارش)")
    top = stats.get("top_products") or []
    if top:
        lines += ["", "🏆 پرفروش‌ترین‌ها:"]
        lines += [f"{i}. {html.escape(p['name'])}: {p['orders']:,} عدد" for i, p in enumerate(top[:3], 1)]
    payment_block = _build_payment_breakdown(extras.get("payment_breakdown") or {})
    if payment_block:
        lines += ["", payment_block]
    chart_block = _build_week_bar_chart(week_stats.get("daily_series") or [])
    if chart_block:
        lines += ["", chart_block]
    return "\n".join(lines)


async def check_and_send_daily_report(bot, db) -> bool:
    if db.get_setting("daily_report_enabled", "1") != "1":
        return False
    now = datetime.now(TEHRAN)
    today = now.strftime("%Y-%m-%d")
    hour, minute = parse_report_time(db.get_setting("daily_report_time", "23:45"))
    if (now.hour, now.minute) < (hour, minute):
        return False
    if db.get_setting(STATUS_KEY_LAST_DATE, "") == today:
        return False

    text = await _db(build_report_text, db, now)
    await report_router.report(bot, db, "nightly", text, senior_only=True)
    await _db(db.set_setting, STATUS_KEY_LAST_DATE, today)
    return True



async def check_and_send_payg_daily_report(bot, db) -> bool:
    """گزارش PayG مستقل از فعال/غیرفعال بودن گزارش فروش روزانه، در همان ساعت تنظیم‌شده."""
    now = datetime.now(TEHRAN)
    today = now.strftime("%Y-%m-%d")
    hour, minute = parse_report_time(db.get_setting("daily_report_time", "23:45"))
    if (now.hour, now.minute) < (hour, minute):
        return False
    key = "_job_payg_daily_report_last_date"
    if db.get_setting(key, "") == today:
        return False
    try:
        import payg
        await payg.send_payg_daily_report(bot, db, today)
        await _db(db.set_setting, key, today)
        return True
    except Exception:
        logger.exception("خطا در ارسال گزارش روزانه PayG")
        return False


async def daily_report_loop(bot, db, interval_seconds: int = CHECK_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await check_and_send_daily_report(bot, db)
            await check_and_send_payg_daily_report(bot, db)
        except Exception:
            logger.exception("خطا در چرخه‌ی گزارش روزانه‌ی فروش/PayG")
        await asyncio.sleep(interval_seconds)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
