# -*- coding: utf-8 -*-
"""هدیه‌ی کانفیگ عضویت: بعد از ثبت‌نام (با تأخیر دلخواه) یک سرویس از محصول انتخابی با حجم/مدت دلخواه ساخته و ارسال می‌شود."""

import asyncio
import html
import logging
import json
import re

import direct_panel_provision
import report_router
from config_delivery import deliver_config_to_user

logger = logging.getLogger(__name__)

_UNITS = {
    "m": 1, "min": 1, "دقیقه": 1, "دقيقه": 1,
    "h": 60, "hr": 60, "ساعت": 60,
    "d": 1440, "day": 1440, "روز": 1440,
}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def parse_delay_minutes(text: str):
    """«30» یا «30m» دقیقه، «2h» ساعت، «3d» روز (فارسی هم پذیرفته می‌شود). نامعتبر → None."""
    raw = (text or "").strip().lower().translate(_DIGITS).replace("٫", ".")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-zا-ی]*)", raw)
    if not match:
        return None
    unit = match.group(2) or "m"
    if unit not in _UNITS:
        return None
    minutes = int(round(float(match.group(1)) * _UNITS[unit]))
    return minutes if 0 <= minutes <= 60 * 24 * 365 else None


def format_delay(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes <= 0:
        return "بلافاصله بعد از عضویت"
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if mins:
        parts.append(f"{mins} دقیقه")
    return " و ".join(parts) + " بعد از عضویت"


def parse_amount(text: str):
    """عدد اعشاری نامنفی؛ «-» یا خالی = پیش‌فرض محصول (رشته‌ی خالی). نامعتبر → None."""
    raw = (text or "").strip().translate(_DIGITS).replace("٫", ".").replace(",", ".")
    if raw in ("", "-"):
        return ""
    try:
        value = float(raw)
    except ValueError:
        return None
    if value < 0 or value > 100000:
        return None
    return str(int(value)) if value == int(value) else str(value)


def format_amount(value: str, unit: str) -> str:
    if value is None or str(value).strip() == "":
        return "پیش‌فرض محصول"
    if float(value) == 0:
        return "نامحدود"
    return f"{value} {unit}"


def product_is_giftable(db, product) -> bool:
    if not product:
        return False
    targets = db.product_target_counts(product)
    return bool(targets["panels"] or targets["ssh"])


def build_gift_product(db, product) -> dict:
    gift = dict(product)
    volume = (db.get_setting("welcome_gift_volume_gb", "") or "").strip()
    days = (db.get_setting("welcome_gift_days", "") or "").strip()
    if volume != "":
        gift["auto_provision_volume_gb"] = float(volume)
    if days != "":
        gift["duration_days"] = float(days)
    gift["price"] = 0
    gift["is_auto_provision"] = 1
    return gift


async def _provision(db, user_id: int) -> dict:
    product_id = int(await asyncio.to_thread(db.get_setting, "welcome_gift_product_id", "0") or 0)
    product = await asyncio.to_thread(db.get_product, product_id) if product_id > 0 else None
    if not product:
        raise direct_panel_provision.ProvisionError("محصول هدیه‌ی عضویت پیدا نشد.")
    gift = await asyncio.to_thread(build_gift_product, db, product)
    items = await direct_panel_provision.provision_direct(db, gift, quantity=1, user_id=user_id)
    for item in items:
        if item.get("custom_config_id"):
            try:
                await asyncio.to_thread(db.retag_custom_config, item["custom_config_id"], "welcome_gift", product_id)
            except Exception:
                pass
    first = items[0]
    return {
        "name": product["name"],
        "username": first.get("username") or "",
        "subscription_url": first["subscription_url"],
        "volume_gb": first.get("volume_gb"),
        "duration_days": first.get("duration_days"),
    }


async def _deliver(bot, db, user_id: int, result: dict) -> bool:
    try:
        await deliver_config_to_user(
            bot, user_id, result["name"], result["subscription_url"], db=db,
            header_text="🎁 هدیه‌ی عضویت شما",
        )
        return True
    except Exception as exc:
        logger.info("ارسال هدیه‌ی کانفیگ عضویت به کاربر %s ناموفق بود: %s", user_id, exc)
        return False


async def _report(bot, db, user_id: int, result: dict) -> None:
    vol = "نامحدود" if not result.get("volume_gb") else f"{result['volume_gb']:g} گیگ"
    dur = "نامحدود" if not result.get("duration_days") else f"{result['duration_days']:g} روز"
    text = (
        "🎁 هدیه‌ی کانفیگ عضویت ارسال شد\n\n"
        f'👤 <a href="tg://user?id={user_id}">{user_id}</a>\n'
        f"📦 {html.escape(result['name'])} - {vol} / {dur}\n"
        f"🔑 <code>{html.escape(result['username'])}</code>"
    )
    try:
        await report_router.send_text(bot, db, "prize", text)
    except Exception as exc:
        logger.info("گزارش هدیه‌ی کانفیگ عضویت ارسال نشد: %s", exc)


async def welcome_gift_once(bot, db) -> int:
    if await asyncio.to_thread(db.get_setting, "welcome_gift_enabled", "0") != "1":
        return 0
    queue_items = await asyncio.to_thread(db.claim_due_welcome_gifts, 5)
    sent = 0
    for queue_item in queue_items:
        user_id = int(queue_item["user_id"])
        user = await asyncio.to_thread(db.get_user, user_id)
        if not user or user["is_blocked"]:
            await asyncio.to_thread(db.finish_welcome_gift, user_id, "skipped", "blocked or missing user")
            continue
        try:
            if queue_item.get("result_json"):
                # اگر ساخت روی پنل موفق بوده اما ارسال تلگرام شکست خورده باشد،
                # فقط همان لینک ذخیره‌شده دوباره ارسال می‌شود؛ حساب جدید نمی‌سازیم.
                result = json.loads(queue_item["result_json"])
            else:
                result = await _provision(db, user_id)
                await asyncio.to_thread(db.save_welcome_gift_result, user_id, result)
        except Exception as exc:
            state = await asyncio.to_thread(db.retry_or_fail_welcome_gift, user_id, str(exc))
            logger.warning("هدیه‌ی عضویت برای %s ناموفق (%s): %s", user_id, state, exc)
            await asyncio.sleep(2.0)
            continue

        delivered = await _deliver(bot, db, user_id, result)
        if not delivered:
            await asyncio.to_thread(db.retry_welcome_gift_delivery, user_id, "ارسال تلگرام ناموفق بود.")
            await asyncio.sleep(2.0)
            continue

        await asyncio.to_thread(db.finish_welcome_gift, user_id, "done")
        await _report(bot, db, user_id, result)
        sent += 1
        # ایجاد حساب روی پنل‌ها به‌صورت کنترل‌شده انجام می‌شود تا هجوم درخواست‌ها
        # باعث فشار ناگهانی روی پنل یا محدودیت تلگرام نشود.
        await asyncio.sleep(2.0)
    return sent


async def welcome_gift_loop(bot, db, interval: int = 5):
    while True:
        try:
            await welcome_gift_once(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در حلقه‌ی هدیه‌ی کانفیگ عضویت")
        await asyncio.sleep(max(5, int(interval)))
