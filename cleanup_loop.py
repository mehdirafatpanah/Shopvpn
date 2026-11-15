#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from i18n import tr
# -*- coding: utf-8 -*-
"""پاکسازی دوره‌ای سرویس‌های منقضی (F14).

طراحی عمدی:
- expired_delete_days و test_delete_days با مقدار ۰ خاموش هستند.
- قبل از حذف، سرویس روی پنل soft-disable می‌شود و رکورد DB باقی می‌ماند.
- On-hold، نامحدود و auto-renew هرگز وارد حذف نمی‌شوند.
- dry-run به‌صورت پیش‌فرض روشن است تا اولین انتشار فقط نامزدهای حذف را به ادمین نشان دهد.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from notification_i18n import send_telegram
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import report_router
from service_alerts import send_service_alert
from panel_providers import get_provider

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.utcnow()
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def _parse_iso(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _safe_int(db, key, default=0):
    try:
        return max(0, int(db.get_setting(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _safe_bool(db, key, default=True):
    raw = str(db.get_setting(key, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def _notify_user(bot: Bot, db, user_id: int, text: str, product_id=None):
    markup = None
    if product_id:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr("🛒 خرید سرویس جدید"), callback_data=f"prod:{int(product_id)}")
        ]])
    try:
        await send_telegram(bot, db, user_id, text, reply_markup=markup)
    except Exception as exc:
        logger.info("ارسال پیام پاکسازی به کاربر %s ناموفق بود: %s", user_id, exc)


async def _notify_admins(bot: Bot, db, text: str):
    try:
        admin_ids = await asyncio.to_thread(db.list_admins)
    except Exception:
        admin_ids = []
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


# --- اعلان یک‌پیامی پاکسازی در گروه تاپیک‌دار ---------------------------------
CLEANUP_REPORT_TOPIC = "service"   # تاپیک «🛠 سرویس» (رویدادهای پاکسازی خودکار)
REPORT_MAX_ITEMS = 15              # سقف ردیف‌های لیست داخل یک پیام (پیام همیشه کوتاه می‌ماند)
MAX_INTERVAL_HOURS = 720


def _interval_hours(db) -> int:
    """فاصله‌ی اجرای پاکسازی و اعلام (ساعت)؛ حداقل ۱ و حداکثر ۷۲۰."""
    return min(max(_safe_int(db, "expired_cleanup_interval_hours", 1), 1), MAX_INTERVAL_HOURS)


def _cleanup_due(db, now) -> bool:
    """True اگر از آخرین اجرای پاکسازی حداقل «فاصله‌ی تنظیم‌شده» گذشته باشد.
    ۲ دقیقه تلورانس برای جلوگیری از جاماندن یک دور به‌خاطر لغزش زمان حلقه."""
    last = _parse_iso(db.get_setting("expired_cleanup_last_run", "") or "")
    if last is None:
        return True
    return (now - last).total_seconds() >= _interval_hours(db) * 3600 - 120


async def _announce(bot: Bot, db, text: str) -> bool:
    """اعلام پاکسازی؛ همیشه فقط یک پیام، داخل تاپیک گروه گزارش
    (اگر گروه تنظیم نباشد یا خطا بدهد، مثل بقیه‌ی گزارش‌ها پیام خصوصی به مدیران)."""
    if not _safe_bool(db, "expired_cleanup_report_enabled", True):
        return False
    try:
        return await report_router.report(bot, db, CLEANUP_REPORT_TOPIC, text)
    except Exception:
        logger.warning("ارسال اعلان پاکسازی ناموفق بود.", exc_info=True)
        return False


def _item_line(row, is_test: bool) -> str:
    return f"{'🧪 تست' if is_test else '📦 سرویس'} #{row['id']} · کاربر {row['user_id']}"


def _compact_list(items) -> list:
    """items = [(row, is_test), ...] → حداکثر REPORT_MAX_ITEMS ردیف + یک خط «و N مورد دیگر»."""
    lines = [_item_line(r, t) for r, t in items[:REPORT_MAX_ITEMS]]
    if len(items) > REPORT_MAX_ITEMS:
        lines.append(f"… و {len(items) - REPORT_MAX_ITEMS} مورد دیگر")
    return lines


def _count_summary(items) -> str:
    tests = sum(1 for _r, t in items if t)
    return f"{len(items)} مورد (🧪 تست: {tests} | 📦 سرویس: {len(items) - tests})"


async def _primary_action(db, row, action):
    server = await asyncio.to_thread(db.get_panel_server, row["panel_server_id"])
    if not server or not server["is_active"]:
        return False, "پنل پیدا نشد یا غیرفعال است"
    try:
        provider = get_provider(server)
        if action == "disable":
            result = await provider.set_enabled(row["username"], False)
        else:
            result = await provider.delete_user(row["username"])
        return (result is not False), "ok"
    except Exception as exc:
        return False, str(exc)


async def _provider_action(db, row, action):
    """action = 'disable' | 'delete'. نتیجه False یعنی عملیات روی پنل قطعی نشده."""
    ok, reason = await _primary_action(db, row, action)
    try:
        import multi_target
        if action == "disable":
            linked_ok = await multi_target.set_linked_panel_users_enabled(db, row["id"], False)
            if not linked_ok and ok:
                ok, reason = False, "قطع پنل‌های اضافه ناموفق بود"
        else:
            await multi_target.delete_linked_panel_users(db, row["id"])
    except (KeyError, IndexError, TypeError):
        pass
    return ok, reason


def _tehran_now():
    return datetime.now(ZoneInfo("Asia/Tehran"))


def _valid_daily_time(value):
    try:
        raw = str(value or "").strip()
        if not raw:
            return None
        hour, minute = raw.split(":", 1)
        hour, minute = int(hour), int(minute)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour, minute
    except (TypeError, ValueError):
        return None


async def delete_inactive_configs_once(bot: Bot, db):
    """F138: در ساعت تنظیم‌شده، کانفیگ‌های عمداً غیرفعال‌شده را حذف می‌کند."""
    schedule = _valid_daily_time(db.get_setting("inactive_config_delete_time", ""))
    if schedule is None:
        return {"deleted": 0, "failed": 0, "disabled": True}

    now = _tehran_now()
    if (now.hour, now.minute) < schedule:
        return {"deleted": 0, "failed": 0, "disabled": False, "due": False}

    last_run = db.get_setting("inactive_config_delete_last_run", "") or ""
    today = now.date().isoformat()
    if last_run == today:
        return {"deleted": 0, "failed": 0, "disabled": False, "due": False, "already_run": True}
    db.set_setting("inactive_config_delete_last_run", today)

    rows = await asyncio.to_thread(db.get_inactive_custom_configs_for_scheduled_delete)
    deleted = failed = 0
    for row in rows:
        ok, reason = await _provider_action(db, row, "delete")
        if not ok:
            failed += 1
            logger.warning("F138: حذف کانفیگ #%s ناموفق: %s", row["id"], reason)
            continue
        if await asyncio.to_thread(db.mark_cleanup_deleted, row["id"], now.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat()):
            deleted += 1
            await asyncio.to_thread(
                db.add_custom_config_history, row["id"], "inactive_scheduled_delete",
                f"F138: حذف خودکار در ساعت {schedule[0]:02d}:{schedule[1]:02d} تهران",
            )
            try:
                await _notify_user(bot, db, row["user_id"], "🗑 کانفیگ غیرفعال شما طبق زمان‌بندی حذف خودکار از پنل حذف شد.")
            except Exception:
                pass

    if deleted or failed:
        await _announce(
            bot, db,
            f"🧹 F138 — حذف زمان‌بندی‌شده کانفیگ‌های غیرفعال\n\n"
            f"🗑 حذف‌شده: {deleted}\n❌ ناموفق: {failed}\n🕐 ساعت اجرا: {schedule[0]:02d}:{schedule[1]:02d} تهران",
        )
    return {"deleted": deleted, "failed": failed, "disabled": False, "due": True}


async def cleanup_once(bot: Bot, db, run_cleanup: bool = True):
    """یک دور پاکسازی را اجرا می‌کند. برای تست واحد نیز قابل فراخوانی است.

    run_cleanup=False یعنی فقط اعلان اتمام سرویس‌ها (که باید به‌موقع برود) انجام شود و
    مرحله‌ی پاکسازی/حذف رد شود؛ حلقه‌ی اصلی این مرحله را فقط هر «N ساعت تنظیم‌شده» اجرا می‌کند."""
    now = _utcnow()
    now_iso = now.isoformat()
    expired_days = _safe_int(db, "expired_delete_days", 0)
    test_days = _safe_int(db, "test_delete_days", 0)
    warning_days = _safe_int(db, "expired_cleanup_warning_days", 3)
    dry_run = _safe_bool(db, "expired_cleanup_dry_run", True)

    # اعلان اتمام مستقل از قابلیت پاکسازی است؛ حتی اگر حذف خودکار خاموش باشد،
    # رسیدن سرویس به expires_at فقط یک‌بار در کانال اعلام می‌شود.‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    expiry_rows = await asyncio.to_thread(db.get_service_expiry_notification_candidates, now_iso)
    expiry_notified = 0
    for row in expiry_rows:
        if await asyncio.to_thread(db.mark_service_expiry_alert_sent, row["id"], now_iso):
            expiry_notified += 1
            exp = _parse_iso(row["expires_at"])
            await send_service_alert(
                bot, db,
                f"⏰ اتمام کانفیگ\n\n👤 کاربر: {row['user_id']}\n🔗 سرویس #{row['id']}\n📌 نام کاربری پنل: {row['username']}\n📅 زمان انقضا: {exp.strftime('%Y-%m-%d %H:%M') if exp else row['expires_at']}"
            )

    if not run_cleanup or (expired_days == 0 and test_days == 0):
        return {"soft": 0, "deleted": 0, "warned": 0, "expiry_notified": expiry_notified, "dry_run": dry_run, "candidates": []}

    # dry-run: هیچ تغییر روی پنل/DB انجام نمی‌دهیم و فقط فهرست نامزدها را به ادمین می‌دهیم.
    rows = await asyncio.to_thread(db.get_cleanup_candidates, now_iso)
    candidates = []
    for row in rows:
        is_test = (row["source"] or "") == "test"
        grace_days = test_days if is_test else expired_days
        if grace_days <= 0:
            continue
        exp = _parse_iso(row["expires_at"])
        if not exp:
            continue
        candidates.append((row, is_test, grace_days, exp))

    if dry_run:
        # فقط وقتی فهرست نامزدها نسبت به دفعه‌ی قبل تغییر کرده اعلام می‌کنیم؛ دیگر هر دوره
        # همان پیام تکراری ارسال نمی‌شود. فهرست خالی شد → دفعه‌ی بعد که نامزد آمد دوباره اعلام می‌شود.
        sig = ",".join(str(r[0]["id"]) for r in sorted(candidates, key=lambda c: c[0]["id"]))
        last_sig = await asyncio.to_thread(db.get_setting, "expired_cleanup_dryrun_sig", "") or ""
        if candidates and sig != last_sig:
            items = [(c[0], c[1]) for c in candidates]
            grace_set = sorted({c[2] for c in candidates})
            lines = [
                "🧪 پاکسازی سرویس‌های منقضی — حالت آزمایشی (dry-run)",
                f"🔎 نامزد حذف: {_count_summary(items)}",
                f"⏱ مهلت حذف: {'، '.join(str(g) for g in grace_set)} روز بعد از انقضا",
                "",
            ]
            lines += _compact_list(items)
            lines += ["", f"🔁 بررسی بعدی: هر {_interval_hours(db)} ساعت (پیام فقط وقتی فهرست تغییر کند تکرار می‌شود)"]
            if await _announce(bot, db, "\n".join(lines)):
                await asyncio.to_thread(db.set_setting, "expired_cleanup_dryrun_sig", sig)
        elif not candidates and last_sig:
            await asyncio.to_thread(db.set_setting, "expired_cleanup_dryrun_sig", "")
        return {"soft": 0, "deleted": 0, "warned": 0, "dry_run": True, "candidates": [r[0]["id"] for r in candidates]}

    soft_count = deleted_count = warned_count = failed_count = 0
    soft_items, deleted_items = [], []

    # هشدار قبل از انقضا؛ هشدار صرفاً وقتی سرویس هنوز active است ارسال می‌شود.‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    warning_to = (now + timedelta(days=warning_days)).isoformat()
    warning_rows = await asyncio.to_thread(db.get_cleanup_warning_candidates, now_iso, warning_to)
    for row in warning_rows:
        is_test = (row["source"] or "") == "test"
        grace_days = test_days if is_test else expired_days
        if grace_days <= 0:
            continue
        if await asyncio.to_thread(db.mark_cleanup_warning_sent, row["id"], now_iso):
            warned_count += 1
            await _notify_user(
                bot,
                db,
                row["user_id"],
                "⚠️ سرویس شما به‌زودی منقضی می‌شود. لطفاً در صورت نیاز، قبل از پایان مهلت آن را تمدید یا سرویس جدید تهیه کنید.",
                row["product_id"] if "product_id" in row.keys() else None,
            )

    for row, is_test, grace_days, exp in candidates:
        # soft-disable در همان لحظه‌ی انقضا.
        if not row["cleanup_soft_disabled_at"]:
            ok, reason = await _provider_action(db, row, "disable")
            if not ok:
                logger.warning("F14: soft-disable سرویس #%s ناموفق: %s", row["id"], reason)
                failed_count += 1
                continue
            if await asyncio.to_thread(db.mark_cleanup_soft_disabled, row["id"], now_iso):
                soft_count += 1
                soft_items.append((row, is_test))
                await asyncio.to_thread(
                    db.add_custom_config_history,
                    row["id"], "cleanup_soft_disable",
                    f"F14: انقضا؛ مهلت حذف {grace_days} روز",
                )
            continue

        # حذف نهایی فقط پس از گذشت مهلت از زمان انقضا.
        delete_at = exp + timedelta(days=grace_days)
        if now < delete_at:
            continue
        ok, reason = await _provider_action(db, row, "delete")
        if not ok:
            logger.warning("F14: حذف سرویس #%s ناموفق: %s", row["id"], reason)
            failed_count += 1
            continue
        if await asyncio.to_thread(db.mark_cleanup_deleted, row["id"], now_iso):
            deleted_count += 1
            deleted_items.append((row, is_test))
            await asyncio.to_thread(
                db.add_custom_config_history,
                row["id"], "cleanup_delete",
                f"F14: حذف قطعی پس از {grace_days} روز مهلت",
            )
            if is_test:
                await _notify_user(
                    bot,
                    db,
                    row["user_id"],
                    "🧪 تست شما تمام شد و از پنل حذف شد. برای ادامه، می‌توانید یک سرویس خریداری کنید.",
                    row["product_id"] if "product_id" in row.keys() else None,
                )
            else:
                await _notify_user(
                    bot,
                    db,
                    row["user_id"],
                    "⛔ سرویس منقضی شما پس از پایان مهلت نگهداری از پنل حذف شد.",
                    row["product_id"] if "product_id" in row.keys() else None,
                )

    if soft_count or deleted_count:
        # یک پیام تجمیعی برای کل این دور (به‌جای چند پیام جدا)
        lines = ["📋 گزارش پاکسازی سرویس‌های منقضی", ""]
        if deleted_count:
            lines.append(f"🗑 حذف‌شده از پنل: {_count_summary(deleted_items)}")
        if soft_count:
            lines.append(f"🔕 غیرفعال‌شده (soft-disable): {_count_summary(soft_items)}")
        if warned_count:
            lines.append(f"⚠️ هشدار پیش از انقضا برای: {warned_count} سرویس")
        if failed_count:
            lines.append(f"❌ ناموفق: {failed_count} مورد (جزئیات در لاگ)")
        if deleted_items:
            lines += ["", "🗑 فهرست حذف‌شده‌ها:"] + _compact_list(deleted_items)
        if soft_items:
            lines += ["", "🔕 فهرست غیرفعال‌شده‌ها:"] + _compact_list(soft_items)
        lines += ["", f"🔁 اجرای بعدی: حدود {_interval_hours(db)} ساعت دیگر"]
        await _announce(bot, db, "\n".join(lines))

    return {
        "soft": soft_count,
        "deleted": deleted_count,
        "warned": warned_count,
        "expiry_notified": expiry_notified,
        "dry_run": False,
        "candidates": [r["id"] for r, *_ in candidates],
    }


async def expire_stale_discount_orders_once(bot: Bot, db):
    """قابلیت ۸۶: سفارش‌های pendingِ رهاشده (کارت‌به‌کارت انتخاب شده ولی رسیدی
    فرستاده نشده) که کد تخفیف دارند را بعد از مهلت تنظیم‌شده منقضی می‌کند تا
    کد تخفیف/کیف‌پول برای همیشه گیر نکند؛ ۰ یعنی این قابلیت غیرفعال است."""
    timeout_minutes = _safe_int(db, "discount_order_expiry_minutes", 60)
    if timeout_minutes <= 0:
        return {"expired": []}
    expired_ids = await asyncio.to_thread(db.expire_stale_discount_orders, timeout_minutes)
    for order_id in expired_ids:
        try:
            order = await asyncio.to_thread(db.get_order, order_id)
        except Exception:
            order = None
        if not order:
            continue
        await _notify_user(
            bot, db, order["user_id"],
            f"⌛ سفارش #{order_id} شما به دلیل ارسال‌نشدن رسید پرداخت تا مهلت تعیین‌شده، "
            f"به‌صورت خودکار لغو شد.\nکد تخفیف و مبلغ کیف پول (در صورت استفاده) به حالت "
            f"قبل بازگشت داده شد؛ در صورت تمایل می‌توانید دوباره سفارش دهید.",
        )
    if expired_ids:
        logger.info("قابلیت ۸۶: %s سفارش رهاشده با کد تخفیف منقضی شد: %s", len(expired_ids), expired_ids)
    return {"expired": expired_ids}


async def cleanup_loop(bot: Bot, db, interval: int = 3600):
    """حلقه‌ی بررسی (هر ساعت). اعلان اتمام سرویس هر دور انجام می‌شود، اما پاکسازی/حذف و اعلام
    آن فقط هر «expired_cleanup_interval_hours» ساعت؛ تنظیمات هر دور دوباره خوانده می‌شوند."""
    while True:
        try:
            import multi_target
            await multi_target.retry_pending_link_deletes(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در تلاش مجدد حذف کاربران پنل‌های اضافه")
        try:
            due = await asyncio.to_thread(_cleanup_due, db, _utcnow())
            await cleanup_once(bot, db, run_cleanup=due)
            if due:
                await asyncio.to_thread(db.set_setting, "expired_cleanup_last_run", _utcnow().isoformat())
            await delete_inactive_configs_once(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در حلقه F14 cleanup")
        try:
            await expire_stale_discount_orders_once(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در انقضای خودکار سفارش‌های رهاشده با کد تخفیف (قابلیت ۸۶)")
        await asyncio.sleep(max(300, int(interval)))
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
