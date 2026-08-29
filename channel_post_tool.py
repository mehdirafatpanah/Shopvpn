# -*- coding: utf-8 -*-
"""
ابزار ارسال پست تبلیغاتی (عکس + کپشن + دکمه‌ی دیپ‌لینک) به کانال.

اجرا از داخل ترموکس، کنار بقیه فایل‌های پروژه:
    python3 channel_post_tool.py

توکن از همون .env پروژه خونده می‌شه (BOT_TOKEN). آیدی کانال یک بار پرسیده
و در .env ذخیره می‌شه تا دفعات بعد نپرسه.
"""

import asyncio
import os

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from dotenv import load_dotenv, set_key

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _build_start_param() -> str:
    print("\nنوع دیپ‌لینک دکمه را انتخاب کن:")
    print("  1) کد تخفیف (disc_CODE)")
    print("  2) کانفیگ تست (test)")
    print("  3) گردونه شانس (wheel)")
    print("  4) معافیت از عضویت اجباری (nofj)")
    print("  5) پارامتر دلخواه (فقط برای آمار منبع ورودی)")
    print("  0) بدون دیپ‌لینک (فقط باز شدن بات)")
    choice = input("انتخاب: ").strip()

    tokens = []
    if choice == "1":
        code = input("کد تخفیف را وارد کن (باید از قبل در ادمین پنل ساخته شده باشد): ").strip()
        if code:
            tokens.append(f"disc_{code}")
    elif choice == "2":
        tokens.append("test")
    elif choice == "3":
        tokens.append("wheel")
    elif choice == "4":
        tokens.append("nofj")
    elif choice == "5":
        custom = input("نام کمپین/منبع را وارد کن (فقط حروف/عدد/زیرخط): ").strip()
        if custom:
            tokens.append(custom)
    elif choice != "0":
        print("گزینه نامعتبر بود؛ بدون دیپ‌لینک ادامه می‌دهم.")

    if tokens and "nofj" not in tokens:
        ans = input("معافیت از عضویت اجباری (nofj) هم به همین دکمه اضافه شود؟ (y/n): ").strip().lower()
        if ans == "y":
            tokens.append("nofj")

    return "-".join(tokens)


async def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN در .env تنظیم نشده است.")
        return

    bot = Bot(token=BOT_TOKEN)
    try:
        me = await bot.get_me()

        channel_id = os.getenv("PROMO_CHANNEL_ID")
        if not channel_id:
            channel_id = input("آیدی عددی کانال را وارد کن (مثلاً -1001234567890): ").strip()
            if input("ذخیره شود تا دفعه‌ی بعد پرسیده نشود؟ (y/n): ").strip().lower() == "y":
                set_key(ENV_PATH, "PROMO_CHANNEL_ID", channel_id)

        photo_path = input("مسیر فایل عکس روی گوشی: ").strip().strip('"')
        if not os.path.isfile(photo_path):
            print(f"❌ فایلی در مسیر «{photo_path}» پیدا نشد.")
            return

        print("\nمتن کپشن را وارد کن (برای پایان، یک خط خالی بزن):")
        lines = []
        while True:
            line = input()
            if line == "":
                break
            lines.append(line)
        caption = "\n".join(lines) or None

        button_text = input("متن دکمه (مثلاً 🎁 خرید با ۳۰٪ تخفیف): ").strip()
        start_param = _build_start_param()
        url = f"https://t.me/{me.username}?start={start_param}" if start_param else f"https://t.me/{me.username}"

        markup = None
        if button_text:
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=url)]])

        photo = FSInputFile(photo_path)
        await bot.send_photo(chat_id=channel_id, photo=photo, caption=caption, reply_markup=markup)

        print("\n✅ پست با موفقیت در کانال ارسال شد.")
        print(f"🔗 دیپ‌لینک دکمه: {url}")
    except Exception as e:
        print(f"❌ خطا در ارسال: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
