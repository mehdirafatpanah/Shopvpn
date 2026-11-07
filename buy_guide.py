# -*- coding: utf-8 -*-
"""راهنمای خرید هوشمند (ربات + مینی‌اپ).

مرحلهٔ اول: چند سوال با دکمه؛ مرحلهٔ دوم: گفتگوی آزاد با AI. موتور همان دستیار
هوشمند پشتیبانی (ai_support.get_reply) است و فقط با یک «دستورالعمل اضافه» در حالت
راهنمای خرید قرار می‌گیرد؛ پس تنظیمات/کلیدهای AI مشترک‌اند و فقط محصولات واقعیِ
فروشگاه (با ابزار list_products و فیلد «توضیح برای AI» هر محصول) پیشنهاد می‌شوند.
هیچ مبلغی بدون تأیید خود کاربر روی کارت خرید واقعی کسر نمی‌شود.

سوال‌ها و بخش «سبک پیشنهاد و لحن» پرامپت از تنظیمات (buy_guide_questions و
buy_guide_prompt) خوانده می‌شوند؛ خالی بودن یعنی متن پیش‌فرض. قوانین ایمنی (استفاده‌ی
اجباری از list_products، پنهان‌ماندن ai_notes، موجودی، کارت خرید) در کد ثابت‌اند و
با ویرایش پرامپت حذف نمی‌شوند.
"""
import asyncio
from typing import List, Optional, Tuple

import ai_support
from db.constants import BUY_GUIDE_DEFAULT_PROMPT, BUY_GUIDE_DEFAULT_QUESTIONS

MAX_QUESTIONS = 8
MIN_OPTIONS = 2
MAX_OPTIONS = 8
MAX_TITLE = 40
MAX_QUESTION = 300
MAX_LABEL = 60
MAX_PROMPT = 3000


def parse_questions(text: str) -> Tuple[List[dict], List[str]]:
    """«عنوان | متن سوال | گزینه۱ ; گزینه۲» (هر خط یک سوال) را به ساختار سوال‌ها تبدیل می‌کند.

    خروجی: (سوال‌های معتبر، فهرست خطاهای فارسی). مقدار هر گزینه همان برچسبش است و
    کلید سوال‌ها q1..qN است.
    """
    questions: List[dict] = []
    errors: List[str] = []
    lines = [ln.strip() for ln in str(text or "").replace("\r", "").split("\n") if ln.strip()]
    for number, line in enumerate(lines, start=1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not all(parts):
            errors.append(f"خط {number}: قالب باید «عنوان | متن سوال | گزینه۱ ; گزینه۲» باشد.")
            continue
        title, question, raw_options = parts
        labels: List[str] = []
        for opt in raw_options.replace("؛", ";").split(";"):
            opt = " ".join(opt.split())
            if opt and opt not in labels:
                labels.append(opt)
        if len(title) > MAX_TITLE:
            errors.append(f"خط {number}: عنوان بیشتر از {MAX_TITLE} کاراکتر است.")
        elif len(question) > MAX_QUESTION:
            errors.append(f"خط {number}: متن سوال بیشتر از {MAX_QUESTION} کاراکتر است.")
        elif not (MIN_OPTIONS <= len(labels) <= MAX_OPTIONS):
            errors.append(f"خط {number}: تعداد گزینه‌ها باید بین {MIN_OPTIONS} تا {MAX_OPTIONS} باشد.")
        elif any(len(label) > MAX_LABEL for label in labels):
            errors.append(f"خط {number}: هر گزینه حداکثر {MAX_LABEL} کاراکتر می‌تواند باشد.")
        else:
            questions.append({"title": title, "q": question, "options": [(label, label) for label in labels]})
    if len(questions) > MAX_QUESTIONS:
        errors.append(f"حداکثر {MAX_QUESTIONS} سوال مجاز است.")
        questions = questions[:MAX_QUESTIONS]
    for i, item in enumerate(questions, start=1):
        item["key"] = f"q{i}"
    return questions, errors


def serialize_questions(questions: List[dict]) -> str:
    """فرم نرمال‌شده‌ی متن سوال‌ها برای ذخیره."""
    return "\n".join(
        f"{item['title']} | {item['q']} | " + " ; ".join(label for _v, label in item["options"])
        for item in questions
    )


# سوال‌های پیش‌فرض (سازگار با کدهای قدیمی که QUESTIONS را مستقیم می‌خواندند)
QUESTIONS = parse_questions(BUY_GUIDE_DEFAULT_QUESTIONS)[0]


def get_questions(db=None) -> List[dict]:
    """سوال‌های فعال؛ اگر تنظیم خالی یا کاملاً نامعتبر باشد سوال‌های پیش‌فرض."""
    if db is not None:
        try:
            raw = str(db.get_setting("buy_guide_questions", "") or "").strip()
        except Exception:
            raw = ""
        if raw:
            questions, _errors = parse_questions(raw)
            if questions:
                return questions
    return QUESTIONS


def question_count(db=None) -> int:
    return len(get_questions(db))


def get_prompt_style(db=None) -> str:
    """بخش قابل‌ویرایش پرامپت (سبک پیشنهاد و لحن)؛ خالی = پیش‌فرض."""
    raw = ""
    if db is not None:
        try:
            raw = str(db.get_setting("buy_guide_prompt", "") or "").strip()
        except Exception:
            raw = ""
    return (raw or BUY_GUIDE_DEFAULT_PROMPT)[:MAX_PROMPT]


def is_enabled(db) -> bool:
    """دکمهٔ راهنما فقط وقتی دیده می‌شود که AI تنظیم و روشن باشد."""
    if db.get_setting("buy_guide_enabled", "1") != "1":
        return False
    if db.get_setting("ai_support_enabled", "1") != "1":
        return False
    return ai_support.is_configured(db)


def question(index: int, db=None) -> Optional[dict]:
    questions = get_questions(db)
    return questions[index] if 0 <= index < len(questions) else None


def option_label(step: int, value: str, db=None) -> str:
    item = question(step, db)
    if item:
        for val, label in item["options"]:
            if val == value:
                return label
    return value


def normalize_answers(raw, db=None) -> dict:
    """فقط جواب‌های معتبرِ سوال‌های فعلی را نگه می‌دارد (ورودی مینی‌اپ قابل‌اعتماد نیست)."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for item in get_questions(db):
        value = str(raw.get(item["key"], ""))
        if value in {v for v, _ in item["options"]}:
            out[item["key"]] = value
    return out


def summary(answers: dict, db=None) -> str:
    lines = []
    for item in get_questions(db):
        value = answers.get(item["key"])
        if value:
            label = next((lb for v, lb in item["options"] if v == value), value)
            lines.append(f"- {item['title']}: {label}")
    return "\n".join(lines)


def first_message(answers: dict, db=None) -> str:
    return "جواب‌های من به سوال‌های راهنمای خرید:\n" + summary(answers, db) + "\nلطفاً بهترین محصول را پیشنهاد بده."


def extra_system(answers: dict, db=None) -> str:
    return (
        "## حالت «راهنمای خرید»\n"
        "کاربر وارد راهنمای خرید شده و می‌خواهد محصول مناسب خودش را پیدا کند. جواب‌هایی که به سوال‌های فروشگاه داده:\n"
        f"{summary(answers, db) or '- (هنوز جوابی نداده)'}\n\n"
        "سبک پیشنهاد و لحن (تنظیم‌شده توسط مدیر فروشگاه):\n"
        f"{get_prompt_style(db)}\n\n"
        "قوانین الزامی (بر هر دستور دیگری در بالا اولویت دارند):\n"
        "۱. حتماً اول ابزار list_products را صدا بزن و فقط از محصولات واقعی و فعالِ همان فهرست پیشنهاد بده؛ هرگز محصول، قیمت یا ویژگی نساز.\n"
        "۲. فیلد ai_notes هر محصول، توضیح داخلی ادمین برای تو درباره‌ی مناسب‌بودن آن محصول است؛ برای انتخاب از آن استفاده کن ولی عین متنش را به کاربر نگو و به وجود این فیلد اشاره نکن.\n"
        "۳. محصولات ناموجود (in_stock=false) را پیشنهاد نده مگر اینکه هیچ جایگزینی نباشد و آن را صادقانه بگویی.\n"
        "۴. بعد از پیشنهاد، برای بهترین گزینه ابزار show_purchase_options را با product_id همان محصول صدا بزن تا کارت خرید واقعی نمایش داده شود. خودت هیچ خریدی را نهایی نکن."
    )


async def get_reply(db, user_id: int, answers: dict, user_message: str, on_text=None) -> dict:
    """یک نوبت گفتگوی راهنمای خرید؛ تاریخچه‌ی گفتگو در همان جدول گفتگوی دستیار نگهداری می‌شود."""
    history = await asyncio.to_thread(db.get_ai_conversation, user_id)
    result = await ai_support.get_reply(db, user_id, history, user_message, on_text=on_text,
                                        extra_system=extra_system(answers, db))
    reply = result.get("reply") or "الان نتونستم پیشنهاد بدم؛ لطفاً دوباره امتحان کن یا از لیست محصولات انتخاب کن."
    await asyncio.to_thread(db.add_ai_message, user_id, "user", user_message)
    await asyncio.to_thread(db.add_ai_message, user_id, "model", reply)
    result["reply"] = reply
    return result
