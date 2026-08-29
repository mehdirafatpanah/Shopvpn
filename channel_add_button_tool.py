# -*- coding: utf-8 -*-
"""
ابزار افزودن دکمه‌ی دیپ‌لینک به یک پستِ از قبل منتشرشده در کانال
(یعنی خودت عکس/متن را دستی داخل تلگرام در کانال گذاشته‌ای، این فقط دکمه را
زیرش اضافه می‌کند - بدون نیاز به آپلود دوباره‌ی عکس).

پیش‌نیاز: بات باید در کانال ادمین باشد و دسترسی "ویرایش پیام‌های دیگران"
(can_edit_messages) را داشته باشد.

اجرا:
    python3 channel_add_button_tool.py
"""

import asyncio
import os
import re

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


def _parse_post_link(link: str):
    """از روی لینک پست (که با «کپی لینک» روی خود پست در تلگرام می‌گیری)
    chat_id و message_id را استخراج می‌کند."""
    link = link.strip()

    m = re.search(r"t\.me/c/(\d+)/(\d+)", link)
    if m:
        internal_id, message_id = m.groups()
        return f"-100{internal_id}", int(message_id)

    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", link)
    if m:
        username, message_id = m.groups()
        return f"@{username}", int(message_id)

    return None, None


def _build_start_param() -> str:
    print("\nنوع دیپ‌لینک دکمه را انتخاب کن:")
    print("  1) کد تخفیف (disc_CODE)")
    print("  2) کانفیگ تست (test)")
    print("  3) گردونه شانس (wheel)")
    print("  4) پارامتر دلخواه (فقط برای آمار منبع ورودی)")
    print("  0) بدون دیپ‌لینک (فقط باز شدن بات)")
    choice = input("انتخاب: ").strip()

    if choice == "1":
        code = input("کد تخفیف را وارد کن (باید از قبل در ادمین پنل ساخته شده باشد): ").strip()
        return f"disc_{code}" if code else ""
    if choice == "2":
        return "test"
    if choice == "3":
        return "wheel"
    if choice == "4":
        return input("نام کمپین/منبع را وارد کن (فقط حروف/عدد/زیرخط): ").strip()
    if choice != "0":
        print("گزینه نامعتبر بود؛ بدون دیپ‌لینک ادامه می‌دهم.")
    return ""


async def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN در .env تنظیم نشده است.")
        return

    bot = Bot(token=BOT_TOKEN)
    try:
        me = await bot.get_me()

        link = input("لینک پستی که خودت در کانال گذاشتی (روی پست بزن -> کپی لینک): ").strip()
        chat_id, message_id = _parse_post_link(link)
        if not chat_id:
            print("❌ نتونستم لینک رو تشخیص بدم. باید شبیه یکی از این دو باشه:\n"
                  "   https://t.me/channelusername/123\n"
                  "   https://t.me/c/1234567890/123")
            return

        button_text = input("متن دکمه (مثلاً 🎁 خرید با ۳۰٪ تخفیف): ").strip()
        if not button_text:
            print("❌ متن دکمه نمی‌تواند خالی باشد.")
            return

        start_param = _build_start_param()
        url = f"https://t.me/{me.username}?start={start_param}" if start_param else f"https://t.me/{me.username}"

        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=url)]])

        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)

        print("\n✅ دکمه به پست اضافه شد.")
        print(f"🔗 دیپ‌لینک دکمه: {url}")
    except Exception as e:
        print(f"❌ خطا: {e}\n(احتمالاً بات ادمین کانال نیست یا دسترسی ویرایش پیام‌های دیگران را ندارد)")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
