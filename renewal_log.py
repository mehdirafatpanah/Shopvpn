# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""هشدار وضعیت فعلی سرویس قبل از تمدید و ارسال لاگ تمدیدها به گروه گزارش مدیر."""

import asyncio
import logging
import os
from datetime import datetime, timezone

import report_router
from config import BOT_TOKEN, DB_PATH, resolve_db_path
from jalali import to_jalali_str
from panel_providers import get_provider

logger = logging.getLogger("renewal_log")

TOPIC_KEY = "renewal"
MODE_LABELS = {
    "full": "تمدید کامل سرویس",
    "volume": "تمدید حجم سرویس",
    "time": "تمدید زمان سرویس",
    "users": "افزایش کاربر سرویس",
}


def fmt_bytes(n: int) -> str:
    n = n or 0
    gb = n / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} گیگابایت"
    return f"{n / (1024 ** 2):.2f} مگابایت"
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def _parse_expiry(raw):
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_time_left(seconds) -> str:
    if seconds is None:
        return "نامشخص"
    if seconds <= 0:
        return "تمام‌شده"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    if days >= 1:
        return f"{days} روز" + (f" و {hours} ساعت" if hours else "")
    return f"{max(hours, 1)} ساعت"


async def service_snapshot(db, cc, provider=None) -> dict:
    """حجم و زمان باقی‌مانده‌ی یک سرویس شخصی؛ مقدار نامشخص None می‌ماند."""
    snap = {"remaining_bytes": None, "total_bytes": None, "unlimited": False, "seconds_left": None}
    exp = _parse_expiry(cc["expires_at"])
    if exp is not None:
        snap["seconds_left"] = (exp - datetime.now(timezone.utc)).total_seconds()
    try:
        if provider is None:
            server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
            if not server:
                return snap
            provider = get_provider(server)
        usage = await provider.get_user_usage(cc["username"])
        total = usage.get("data_limit_bytes") or 0
        used = usage.get("used_bytes") or 0
        if total > 0:
            snap["total_bytes"] = total
            snap["remaining_bytes"] = max(total - used, 0)
        else:
            snap["unlimited"] = True
    except Exception:
        logger.warning("دریافت وضعیت سرویس «%s» از پنل ناموفق بود.", cc["username"], exc_info=True)
    return snap


def _left_parts(snap) -> list:
    parts = []
    if snap.get("remaining_bytes"):
        parts.append(f"{fmt_bytes(snap['remaining_bytes'])} حجم")
    seconds = snap.get("seconds_left")
    if seconds is not None and seconds > 0:
        parts.append(fmt_time_left(seconds))
    return parts


def warning_text(snap) -> str:
    """متن هشدار صفحه‌ی تایید تمدید کامل؛ اگر چیزی از سرویس باقی نمانده خالی است."""
    parts = _left_parts(snap)
    if not parts:
        return ""
    return (
        f"⚠️ توجه: این سرویس هنوز {' و '.join(parts)} باقی‌مانده دارد.\n"
        "با تمدید کامل، بسته‌ی جدید روی حجم و زمان باقی‌مانده اضافه می‌شود.\n"
        "اگر هنوز نیازی به تمدید ندارید، انصراف دهید.\n"
    )


def _state_line(snap) -> str:
    if not snap:
        return "نامشخص"
    if snap.get("unlimited"):
        volume = "نامحدود"
    elif snap.get("remaining_bytes") is not None:
        volume = fmt_bytes(snap["remaining_bytes"])
    else:
        volume = "نامشخص"
    return f"حجم {volume} | زمان {fmt_time_left(snap.get('seconds_left'))}"


def _same_path(a, b) -> bool:
    return bool(a) and bool(b) and os.path.abspath(a) == os.path.abspath(b)


def resolve_token(db):
    token = getattr(db, "bot_token", None)
    if token:
        return token
    if _same_path(db.db_path, DB_PATH) or _same_path(db.db_path, resolve_db_path(DB_PATH)):
        return BOT_TOKEN
    try:
        from database import Database
        main_db = Database(DB_PATH)
        for row in main_db.list_reseller_bots():
            if _same_path(resolve_db_path(row["db_path"]), db.db_path):
                return row["bot_token"]
    except Exception:
        logger.warning("پیدا کردن توکن بات این دیتابیس ناموفق بود.", exc_info=True)
    return None


def _build_text(db, order, service_name, before, after) -> str:
    user = db.get_user(order["user_id"])
    name = (user["first_name"] if user and user["first_name"] else "") or "-"
    handle = f" (@{user['username']})" if user and user["username"] else ""
    lines = [
        f"🔄 {MODE_LABELS.get(order['renewal_mode'], 'تمدید سرویس')}",
        "",
        f"👤 {name}{handle}",
        f"🆔 {order['user_id']}",
        f"🎫 سرویس: {service_name} (#{order['renewal_target_id']})",
    ]
    added = []
    if order["renewal_add_volume_gb"]:
        added.append(f"+{order['renewal_add_volume_gb']} گیگ")
    if order["renewal_add_days"]:
        added.append(f"+{order['renewal_add_days']} روز")
    if order["renewal_user_limit"] and order["renewal_mode"] in ("users", "full"):
        added.append(f"{order['renewal_user_limit']} کاربر همزمان")
    if added:
        lines.append(f"📦 بسته: {' / '.join(added)}")
    if before is not None:
        lines.append(f"📉 قبل از تمدید: {_state_line(before)}")
    if after is not None:
        lines.append(f"📈 بعد از تمدید: {_state_line(after)}")
    lines.append(f"💰 مبلغ: {(order['base_price'] or 0):,} تومان")
    if order["discount_amount"]:
        lines.append(f"🎟 تخفیف کد: {order['discount_amount']:,} تومان")
    if order["wallet_used"]:
        lines.append(f"👛 از کیف پول: {order['wallet_used']:,} تومان")
    lines.append(f"💳 پرداخت مستقیم: {(order['final_price'] or 0):,} تومان")
    lines.append(f"🧾 سفارش #{order['id']}")
    lines.append(f"🕒 {to_jalali_str(datetime.now(timezone.utc), with_time=True)}")
    return "\n".join(lines)


_pending = set()


async def _send(db, order, service_name, before, after_cc, provider) -> None:
    try:
        token = await asyncio.to_thread(resolve_token, db)
        if not token:
            logger.warning("توکن بات برای ارسال لاگ تمدید سفارش #%s پیدا نشد.", order["id"])
            return
        after = await service_snapshot(db, after_cc, provider) if after_cc is not None else None
        text = await asyncio.to_thread(_build_text, db, order, service_name, before, after)
        await report_router.report_raw(token, db, TOPIC_KEY, text, senior_only=True)
    except Exception:
        logger.warning("ارسال لاگ تمدید سفارش #%s ناموفق بود.", order["id"], exc_info=True)


async def _send_alert(db, text) -> None:
    try:
        token = await asyncio.to_thread(resolve_token, db)
        if token:
            await report_router.report_raw(token, db, TOPIC_KEY, text, senior_only=True)
    except Exception:
        logger.warning("ارسال هشدار تمدید ناقص ناموفق بود.", exc_info=True)


def alert(db, text) -> None:
    """هشدار پس‌زمینه به مدیران ارشد (مثلاً تمدید ناقص پنل‌های اضافه)."""
    task = asyncio.get_running_loop().create_task(_send_alert(db, text))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def notify(db, order, service_name, before=None, after_cc=None, provider=None) -> None:
    """ارسال لاگ تمدید در پس‌زمینه (گروه گزارش، تاپیک «تمدید»؛ در غیاب گروه مدیران ارشد)."""
    task = asyncio.get_running_loop().create_task(_send(db, order, service_name, before, after_cc, provider))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
