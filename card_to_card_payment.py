# -*- coding: utf-8 -*-
"""
کارت‌به‌کارت با تایید خودکار: به هر فاکتور یک مبلغ یکتا (مبلغ اصلی + چند رقم
آخر تصادفی) اختصاص داده می‌شود؛ اپ اندروید BankSmsForwarder پیامک واریزی بانک
را می‌خواند و به وب‌هوک سرور می‌فرستد؛ با تطبیق دقیق همین مبلغ یکتا، فاکتور
بدون دخالت ادمین تایید می‌شود. حتی اگر هزاران نفر هم‌زمان پرداخت کنند، چون
مبلغ هرکدام یکتاست، امکان تداخل نیست.
"""

import logging
import random
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("card_to_card_payment")

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_MAX_ATTEMPTS = 40


class CardToCardError(Exception):
    """خطای قابل‌نمایش به کاربر (مثلاً هیچ کارتی تعریف نشده)."""
    pass


def normalize_amount(raw) -> Optional[int]:
    """رشته‌ی مبلغ (فارسی/عربی/انگلیسی، با یا بدون جداکننده‌ی هزارگان) را به
    عدد صحیح تبدیل می‌کند. اگر قابل‌تبدیل نبود None برمی‌گرداند."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    trans = {}
    for i, ch in enumerate(_PERSIAN_DIGITS):
        trans[ord(ch)] = str(i)
    for i, ch in enumerate(_ARABIC_DIGITS):
        trans[ord(ch)] = str(i)
    s = s.translate(trans)
    s = re.sub(r"[^\d]", "", s)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def rial_to_toman(amount: int, unit: str) -> int:
    """پیامک بانک معمولاً مبلغ را به ریال گزارش می‌کند؛ پروژه همه‌جا با تومان
    کار می‌کند، پس در آن حالت بر ۱۰ تقسیم می‌شود."""
    if (unit or "rial").lower() == "rial":
        return amount // 10
    return amount


def _random_offset(digits: int) -> int:
    lo = 10 ** (digits - 1)
    hi = (10 ** digits) - 1
    return random.randint(lo, hi)


def create_invoice(db, kind: str, ref_id: int, user_id: int, base_amount_toman: int) -> dict:
    """فاکتور کارت‌به‌کارت خودکار می‌سازد. اگر همین سفارش/شارژ از قبل یک فاکتور
    در انتظار دارد، همان را برمی‌گرداند تا با هربار باز شدن صفحه، مبلغ عوض
    نشود (و کاربر سردرگم نشود که کدام مبلغ را باید واریز کند)."""
    existing = db.get_pending_card_to_card_invoice_for_ref(kind, ref_id)
    if existing:
        card = db.get_card_to_card_card(existing["card_id"])
        return _invoice_dict(existing, card)

    card = db.pick_next_card_to_card_card()
    if not card:
        raise CardToCardError("هیچ شماره کارتی برای دریافت وجه تعریف نشده است.")

    digits = int(db.get_setting("card_to_card_auto_amount_digits", "3") or 3)
    timeout_minutes = int(db.get_setting("card_to_card_auto_timeout_minutes", "15") or 15)
    expires_at = (datetime.utcnow() + timedelta(minutes=timeout_minutes)).isoformat()

    last_err = None
    for attempt in range(_MAX_ATTEMPTS):
        # اگر رقم‌های عادی چند بار پشت‌سرهم تصادف رزرو‌شده درآمدند (بار همزمانی
        # خیلی بالا)، برای تلاش‌های آخر یک رقم بیشتر اضافه می‌کنیم تا فضای
        # مبلغ‌های ممکن بزرگ‌تر شود.
        d = digits if attempt < _MAX_ATTEMPTS - 10 else digits + 1
        amount_toman = base_amount_toman + _random_offset(d)
        try:
            invoice_id = db.create_card_to_card_invoice(
                card["id"], kind, ref_id, user_id, base_amount_toman, amount_toman, expires_at,
            )
        except sqlite3.IntegrityError as e:
            last_err = e
            continue
        db.touch_card_to_card_card(card["id"])
        invoice = db.get_card_to_card_invoice(invoice_id)
        return _invoice_dict(invoice, card)

    logger.error("card_to_card: reserving a unique amount failed after %s attempts", _MAX_ATTEMPTS)
    raise CardToCardError("امکان رزرو مبلغ یکتا وجود نداشت، لطفاً چند لحظه دیگر دوباره تلاش کنید.") from last_err


def _invoice_dict(invoice, card) -> dict:
    return {
        "invoice_id": invoice["id"],
        "amount_toman": invoice["amount_toman"],
        "base_amount_toman": invoice["base_amount_toman"],
        "card_number": card["card_number"] if card else None,
        "card_holder": card["holder_name"] if card else None,
        "bank_name": card["bank_name"] if card else None,
        "expires_at": invoice["expires_at"],
        "status": invoice["status"],
    }


def match_and_complete(db, amount_toman: int, sender: str = None, body: str = None, device_id: str = None):
    """فاکتور در انتظاری با همین مبلغ دقیق پیدا و 'completed' می‌کند. فاکتور
    (ردیف تازه‌خوانی‌شده) را برمی‌گرداند یا None اگر مطابقتی پیدا نشد."""
    db.expire_stale_card_to_card_invoices()
    invoice = db.get_pending_card_to_card_invoice_by_amount(amount_toman)
    if not invoice:
        return None
    db.complete_card_to_card_invoice(invoice["id"], sender=sender, body=body, device_id=device_id)
    return db.get_card_to_card_invoice(invoice["id"])
