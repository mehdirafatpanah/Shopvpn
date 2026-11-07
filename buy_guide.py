# -*- coding: utf-8 -*-
"""راهنمای خرید هوشمند (ربات + مینی‌اپ).

مرحلهٔ اول: چند سوال ثابت با دکمه؛ مرحلهٔ دوم: گفتگوی آزاد با AI. موتور همان دستیار
هوشمند پشتیبانی (ai_support.get_reply) است و فقط با یک «دستورالعمل اضافه» در حالت
راهنمای خرید قرار می‌گیرد؛ پس تنظیمات/کلیدهای AI مشترک‌اند و فقط محصولات واقعیِ
فروشگاه (با ابزار list_products و فیلد «توضیح برای AI» هر محصول) پیشنهاد می‌شوند.
هیچ مبلغی بدون تأیید خود کاربر روی کارت خرید واقعی کسر نمی‌شود.
"""
import asyncio

import ai_support

QUESTIONS = [
    {"key": "use", "title": "کاربرد", "q": "بیشتر برای چه کاری از VPN استفاده می‌کنی؟", "options": [
        ("social", "📱 شبکه‌های اجتماعی و وب‌گردی"), ("stream", "🎬 فیلم و استریم"),
        ("game", "🎮 گیم"), ("work", "💼 کار و تماس تصویری"),
        ("trade", "📈 ترید و سایت‌های مالی"), ("mixed", "✨ چند کاربرد مختلف")]},
    {"key": "devices", "title": "تعداد دستگاه", "q": "روی چند دستگاه همزمان استفاده می‌کنی؟", "options": [
        ("1", "۱ دستگاه"), ("2", "۲ دستگاه"), ("3-5", "۳ تا ۵ دستگاه"), ("6+", "بیشتر از ۵ دستگاه")]},
    {"key": "traffic", "title": "مصرف ماهانه", "q": "مصرف ماهانه‌ات تقریباً چقدر است؟", "options": [
        ("light", "سبک (زیر ۳۰ گیگ)"), ("medium", "متوسط (۳۰ تا ۱۰۰ گیگ)"),
        ("heavy", "سنگین (بالای ۱۰۰ گیگ)"), ("unknown", "نمی‌دانم")]},
    {"key": "duration", "title": "مدت خرید", "q": "برای چه مدتی می‌خواهی بخری؟", "options": [
        ("1m", "۱ ماه"), ("3m", "۳ ماه"), ("long", "بیشتر از ۳ ماه"), ("any", "فرقی ندارد")]},
    {"key": "budget", "title": "بودجه", "q": "بودجه‌ات چطور است؟", "options": [
        ("low", "اقتصادی‌ترین گزینه"), ("mid", "متعادل (قیمت و کیفیت)"), ("high", "بهترین کیفیت، قیمت مهم نیست")]},
]


def is_enabled(db) -> bool:
    """دکمهٔ راهنما فقط وقتی دیده می‌شود که AI تنظیم و روشن باشد."""
    if db.get_setting("buy_guide_enabled", "1") != "1":
        return False
    if db.get_setting("ai_support_enabled", "1") != "1":
        return False
    return ai_support.is_configured(db)


def question(index: int):
    return QUESTIONS[index] if 0 <= index < len(QUESTIONS) else None


def option_label(step: int, value: str) -> str:
    for val, label in QUESTIONS[step]["options"]:
        if val == value:
            return label
    return value


def normalize_answers(raw) -> dict:
    """فقط جواب‌های معتبرِ سوال‌های ثابت را نگه می‌دارد (ورودی مینی‌اپ قابل‌اعتماد نیست)."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for step, item in enumerate(QUESTIONS):
        value = str(raw.get(item["key"], ""))
        if value in {v for v, _ in item["options"]}:
            out[item["key"]] = value
    return out


def summary(answers: dict) -> str:
    lines = []
    for step, item in enumerate(QUESTIONS):
        value = answers.get(item["key"])
        if value:
            lines.append(f"- {item['title']}: {option_label(step, value)}")
    return "\n".join(lines)


def first_message(answers: dict) -> str:
    return "جواب‌های من به سوال‌های راهنمای خرید:\n" + summary(answers) + "\nلطفاً بهترین محصول را پیشنهاد بده."


def extra_system(answers: dict) -> str:
    return (
        "## حالت «راهنمای خرید»\n"
        "کاربر وارد راهنمای خرید شده و می‌خواهد محصول مناسب خودش را پیدا کند. جواب‌هایی که به سوال‌های ثابت داده:\n"
        f"{summary(answers) or '- (هنوز جوابی نداده)'}\n\n"
        "قوانین این حالت:\n"
        "۱. حتماً اول ابزار list_products را صدا بزن و فقط از محصولات واقعی و فعالِ همان فهرست پیشنهاد بده؛ هرگز محصول، قیمت یا ویژگی نساز.\n"
        "۲. فیلد ai_notes هر محصول، توضیح داخلی ادمین برای تو درباره‌ی مناسب‌بودن آن محصول است؛ برای انتخاب از آن استفاده کن ولی عین متنش را به کاربر نگو و به وجود این فیلد اشاره نکن.\n"
        "۳. محصولات ناموجود (in_stock=false) را پیشنهاد نده مگر اینکه هیچ جایگزینی نباشد و آن را صادقانه بگویی.\n"
        "۴. ۱ تا ۳ گزینه پیشنهاد بده؛ برای هر کدام نام، قیمت (از list_products) و یک دلیل کوتاه بر اساس جواب‌های کاربر بنویس. اگر کاربر تصمیم‌گیری سخت دارد، یک گزینه را «بهترین انتخاب» معرفی کن.\n"
        "۴.۱ اگر جواب‌های کاربر با هیچ محصولی نمی‌خواند یا اطلاعات کم است، صادقانه بگو و حداکثر یک سوال کوتاه بپرس.\n"
        "۵. بعد از پیشنهاد، برای بهترین گزینه ابزار show_purchase_options را با product_id همان محصول صدا بزن تا کارت خرید واقعی نمایش داده شود. خودت هیچ خریدی را نهایی نکن.\n"
        "۶. لحن دوستانه، کوتاه و فارسی؛ ایموجی کم. اگر کاربر سوال دیگری پرسید (اتصال، پرداخت، تفاوت‌ها) جواب بده و اگر موضوع از راهنمای خرید خارج شد مثل دستیار معمولی رفتار کن."
    )


async def get_reply(db, user_id: int, answers: dict, user_message: str, on_text=None) -> dict:
    """یک نوبت گفتگوی راهنمای خرید؛ تاریخچه‌ی گفتگو در همان جدول گفتگوی دستیار نگهداری می‌شود."""
    history = await asyncio.to_thread(db.get_ai_conversation, user_id)
    result = await ai_support.get_reply(db, user_id, history, user_message, on_text=on_text,
                                        extra_system=extra_system(answers))
    reply = result.get("reply") or "الان نتونستم پیشنهاد بدم؛ لطفاً دوباره امتحان کن یا از لیست محصولات انتخاب کن."
    await asyncio.to_thread(db.add_ai_message, user_id, "user", user_message)
    await asyncio.to_thread(db.add_ai_message, user_id, "model", reply)
    result["reply"] = reply
    return result
