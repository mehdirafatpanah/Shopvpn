# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""نمایش قیمت تخفیف‌دار محصول (فقط نمایشی).

compare_price = قیمت قبل از تخفیف. اگر از قیمت فعلی بزرگ‌تر باشد، در ربات
قیمت قبلی با خط روی آن نوشته می‌شود و قیمت جدید کنارش می‌آید. محاسبه‌ی پرداخت
همچنان فقط از `price` انجام می‌شود.
"""

_LRE, _RLE, _PDF = "\u202a", "\u202b", "\u202c"
_STRIKE = "̶"  # Combining long stroke overlay: خط‌خوردگی در متن ساده‌ی تلگرام (دکمه‌ها هم)‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def _field(product, key, default=0):
    try:
        value = product[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def strike(text: str) -> str:
    return "".join(ch + _STRIKE for ch in str(text))
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def compare_price_for(product, unit_price: int = None) -> int:
    """قیمت قبل از تخفیف متناسب با unit_price (مثلاً با احتساب کاربر اضافه). 0 یعنی تخفیفی نیست."""
    compare = int(_field(product, "compare_price", 0) or 0)
    price = int(product["price"] or 0)
    if compare <= price or price <= 0:
        return 0
    if unit_price is None:
        return compare
    return compare + (int(unit_price) - price)


def _ltr(text: str) -> str:
    """عدد را در یک بلوک چپ‌به‌راست جدا می‌کند تا در متن راست‌به‌چپ ارقام و ویرگول‌ها جابه‌جا نشوند
    (مثلاً 70,000 به‌شکل 000,70 دیده نمی‌شد)."""
    return f"{_LRE}{text}{_PDF}"


def _rtl(text: str) -> str:
    """کل برچسب قیمت را راست‌به‌چپ می‌کند: قیمت قدیمی سمت راست، جدید سمت چپ، حتی اگر دکمه با نام لاتین شروع شود."""
    return f"{_RLE}{text}{_PDF}"


def _percent(old: int, new: int) -> int:
    return max(round((old - new) * 100 / old), 1) if old > 0 else 0


def price_range(old: int, new: int, suffix: str = "") -> str:
    """«قیمت قدیمی (خط‌خورده) ← قیمت جدید» با ترتیب درست در هر زمینه‌ی متنی (راست‌به‌چپ یا چپ‌به‌راست)."""
    tail = f" {suffix}" if suffix else ""
    return _rtl(f"{_ltr(strike(f'{int(old):,}'))} ← {_ltr(f'{int(new):,}')}{tail}")


def plain_range(old: int, new: int, suffix: str = "ت") -> str:
    """مثل price_range ولی بدون خط‌خوردگی (برای دکمه‌های ادمین و متن‌هایی که خط‌خورده لازم ندارند)."""
    return _rtl(f"{_ltr(f'{int(old):,}')} ← {_ltr(f'{int(new):,}')}{suffix}")


def price_label_plain(product, unit_price: int = None, suffix: str = "تومان") -> str:
    """برچسب قیمت برای متن ساده: «۱۰۰,۰۰۰ (خط‌خورده) ← ۸۰,۰۰۰ تومان»."""
    price = int(unit_price if unit_price is not None else product["price"])
    old = compare_price_for(product, price)
    if not old:
        return f"{_ltr(f'{price:,}')} {suffix}".rstrip()
    return price_range(old, price, suffix).rstrip()


# حداکثر طول (کاراکتر) نام + دو عدد برای نمایش کامل قیمت خط‌خورده روی دکمه؛ بیشتر از آن
# متن زیر لبه‌ی دکمه می‌رود، پس فرم کوتاه با درصد تخفیف نشان داده می‌شود.
_BUTTON_FULL_LIMIT = 26


def price_label_button(product, unit_price: int = None, name: str = "") -> str:
    """برچسب قیمت دکمه. اگر جا باشد قیمت قدیمی خط‌خورده + جدید، وگرنه قیمت جدید + درصد تخفیف."""
    price = int(unit_price if unit_price is not None else product["price"])
    old = compare_price_for(product, price)
    if not old:
        return f"{_ltr(f'{price:,}')} تومان"
    old_s, new_s = f"{old:,}", f"{price:,}"
    if len(str(name)) + len(old_s) + len(new_s) <= _BUTTON_FULL_LIMIT:
        return price_range(old, price, "ت")
    return _rtl(f"{_ltr(new_s)}ت ({_ltr(str(_percent(old, price)) + '٪')} تخفیف)")

#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
