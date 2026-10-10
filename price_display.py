# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""نمایش قیمت تخفیف‌دار محصول (فقط نمایشی).

compare_price = قیمت قبل از تخفیف. اگر از قیمت فعلی بزرگ‌تر باشد، در ربات
قیمت قبلی با خط روی آن نوشته می‌شود و قیمت جدید کنارش می‌آید. محاسبه‌ی پرداخت
همچنان فقط از `price` انجام می‌شود.
"""

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


def price_label_plain(product, unit_price: int = None, suffix: str = "تومان") -> str:
    """برچسب قیمت برای دکمه/متن ساده: «~~۱۰۰,۰۰۰~~ ۸۰,۰۰۰ تومان» (خط‌خورده با کاراکتر ترکیبی)."""
    price = int(unit_price if unit_price is not None else product["price"])
    old = compare_price_for(product, price)
    if not old:
        return f"{price:,} {suffix}".rstrip()
    return f"{strike(f'{old:,}')} ➜ {price:,} {suffix}".rstrip()
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
