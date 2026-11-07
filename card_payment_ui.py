# -*- coding: utf-8 -*-
"""
ظاهر و دکمه‌های پیام پرداخت کارت‌به‌کارت (دستی و خودکار).

- متن «زیبا» (کارت اطلاعات واریز) یا «کلاسیک» (همان متن قبلی) بر اساس تنظیم c2c_message_style.
- دکمه‌های کپی (CopyTextButton تلگرام): شماره کارت، مبلغ تومان، مبلغ ریال، نام صاحب کارت.
- محافظت از پیام کارت (protect_content): جلوگیری از کپی متن، فوروارد و اسکرین‌شات؛
  دکمه‌های کپی با وجود محافظت کار می‌کنند.

این ماژول به aiogram وابسته نیست تا ساده تست شود؛ ساخت دکمه‌ها در handlers_user انجام می‌شود.
"""
import re

from md_utils import escape_md

_LINE = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
_VALID_STYLES = ("primary", "success", "danger")


def get_cfg(db) -> dict:
    """تنظیمات ظاهر/دکمه‌ها را یک‌جا می‌خواند."""
    def flag(key, default):
        return (db.get_setting(key, default) or default) == "1"

    style = (db.get_setting("c2c_copy_btn_style", "default") or "default").strip()
    return {
        "style": (db.get_setting("c2c_message_style", "pretty") or "pretty").strip(),
        "copy_buttons": flag("c2c_copy_buttons", "1"),
        "copy_card": flag("c2c_copy_card", "1"),
        "copy_toman": flag("c2c_copy_amount_toman", "1"),
        "copy_rial": flag("c2c_copy_amount_rial", "1"),
        "copy_holder": flag("c2c_copy_holder", "0"),
        "btn_style": style if style in _VALID_STYLES else "",
        "protect": flag("c2c_protect_card", "0"),
        "show_bank": flag("c2c_show_bank", "1"),
        "back_to_wallet": flag("c2c_back_to_wallet", "1"),
    }


def digits_only(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def format_card(value, grouped: bool = True) -> str:
    """۱۶ رقم را ۴تا۴تا گروه می‌کند؛ شبا/فرمت‌های دیگر دست‌نخورده می‌ماند."""
    raw = str(value or "").strip()
    d = digits_only(raw)
    if grouped and len(d) == 16 and not raw.upper().startswith("IR"):
        return " ".join(d[i:i + 4] for i in range(0, 16, 4))
    return raw


def copy_rows(cfg: dict, card_number, holder, amount_toman: int) -> list:
    """لیست ردیف‌های دکمه‌ی کپی: [[(برچسب، مقدار)]]. اگر قابلیت خاموش باشد خالی است."""
    if not cfg.get("copy_buttons"):
        return []
    rows = []
    raw_card = str(card_number or "").strip()
    copy_card_value = digits_only(raw_card) if len(digits_only(raw_card)) == 16 and not raw_card.upper().startswith("IR") else raw_card
    if cfg.get("copy_card") and copy_card_value:
        rows.append([("📋 کپی شماره کارت", copy_card_value)])
    amount_row = []
    if cfg.get("copy_toman") and amount_toman:
        amount_row.append(("📋 مبلغ (تومان)", str(int(amount_toman))))
    if cfg.get("copy_rial") and amount_toman:
        amount_row.append(("📋 مبلغ (ریال)", str(int(amount_toman) * 10)))
    if amount_row:
        rows.append(amount_row)
    if cfg.get("copy_holder") and holder:
        rows.append([("📋 کپی نام صاحب کارت", str(holder))])
    return rows


def build_text(cfg: dict, intro_lines, card_number, holder, bank, amount_toman: int,
               auto: bool = False, timeout_minutes: int = 15) -> str:
    """متن پیام پرداخت (Markdown لگاسی تلگرام)."""
    amount_toman = int(amount_toman)
    amount_rial = amount_toman * 10
    intro = "\n".join(intro_lines) + "\n\n" if intro_lines else ""
    holder_txt = escape_md(holder or "")
    bank_txt = escape_md(bank or "") if (bank and cfg.get("show_bank", True)) else ""

    if cfg.get("style") == "classic":
        text = ("\n".join(intro_lines) + "\n") if intro_lines else ""
        text += f"💳 شماره کارت: `{card_number}`\n"
        text += f"👤 به نام: {holder_txt}\n"
        if bank_txt:
            text += f"🏦 بانک: {bank_txt}\n"
        if auto:
            text += "\n⚠️ لطفاً دقیقاً یکی از این دو مبلغ رو (بسته به واحد اپ بانکت) واریز کن:\n"
            text += f"💰 تومان: `{amount_toman}` ({amount_toman:,} تومان)\n"
            text += f"💰 ریال: `{amount_rial}` ({amount_rial:,} ریال)\n\n"
            text += (
                "✅ به‌محض دریافت پیامک بانک، پرداخت به‌صورت خودکار تایید و تحویل داده "
                "می‌شود (بدون نیاز به ارسال رسید).\n"
                f"⏳ اعتبار این مبلغ فقط {timeout_minutes} دقیقه است؛ بعد از آن باید دوباره اقدام کنید."
            )
        else:
            text += f"💰 مبلغ (تومان): `{amount_toman}` ({amount_toman:,} تومان)\n"
            text += f"💰 مبلغ (ریال): `{amount_rial}` ({amount_rial:,} ریال)\n\n"
            text += "لطفاً عدد بالا رو لمس کن تا کپی بشه، مبلغ رو واریز کن و عکس رسید رو همینجا ارسال کن."
        return text

    # ---- سبک «زیبا» ----
    grouped = bool(cfg.get("copy_buttons"))  # با دکمه‌ی کپی، نمایش گروه‌بندی‌شده مشکلی ایجاد نمی‌کند
    text = intro
    text += "💳 *اطلاعات واریز*\n" + _LINE + "\n"
    if bank_txt:
        text += f"🏦 بانک: *{bank_txt}*\n"
    text += f"👤 به نام: *{holder_txt}*\n"
    text += f"💳 شماره کارت:\n`{format_card(card_number, grouped)}`\n"
    text += _LINE + "\n"
    if auto:
        text += "💰 *مبلغ دقیق واریز* (یکتا برای همین پرداخت)\n"
    else:
        text += "💰 *مبلغ قابل پرداخت*\n"
    text += f"▫️ تومان: `{amount_toman}`  ({amount_toman:,})\n"
    text += f"▫️ ریال: `{amount_rial}`  ({amount_rial:,})\n"
    text += _LINE + "\n"
    if auto:
        text += (
            "⚠️ دقیقاً همین مبلغ را (به واحد اپ بانکت) واریز کن.\n"
            "✅ بعد از دریافت پیامک بانک، پرداخت خودکار تایید و تحویل می‌شود؛ نیازی به رسید نیست.\n"
            f"⏳ اعتبار مبلغ: *{timeout_minutes} دقیقه*"
        )
    else:
        if cfg.get("copy_buttons"):
            text += "👇 با دکمه‌های زیر کپی کن، واریز کن و عکس رسید را همین‌جا بفرست."
        else:
            text += "👆 عدد بالا را لمس کن تا کپی شود، واریز کن و عکس رسید را همین‌جا بفرست."
    return text
