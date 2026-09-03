# -*- coding: utf-8 -*-
"""
ساخت کیبوردهای شیشه‌ای و معمولی بات

نکته مهم: چون هر بات (اصلی یا نمایندگی) دیتابیس مستقل خودش را دارد، تمام
توابعی که به تنظیمات/داده نیاز دارند، شیء db (نمونه‌ی Database همان بات) را
به‌عنوان پارامتر می‌گیرند - نه اینکه از یک ماژول سراسری import شود.
"""

from aiogram.types import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

from config import MINIAPP_URL
from panel_providers import PANEL_TYPE_LABELS
from database import MENU_BUTTON_META, ACCOUNT_TOGGLE_KEYS


# ---------------------------------------------------------------------------
# منوی اصلی (Reply Keyboard)
# ---------------------------------------------------------------------------

def _styled_button(text: str, style_value: str) -> KeyboardButton:
    """می‌سازد یک دکمه با رنگ دلخواه (ویژگی style در Bot API 9.4 به بعد).
    مقدار خالی یعنی رنگ پیش‌فرض (خاکستری)."""
    style = style_value if style_value in ("primary", "success", "danger") else None
    return KeyboardButton(text=text, style=style)


def _miniapp_url(db) -> str:
    """آدرس مینی‌اپ مخصوص همین بات (اصلی یا نمایندگی) را می‌سازد.
    برای بات‌های نمایندگی، شناسه‌ی تننت به‌صورت پارامتر ?b= اضافه می‌شود تا
    سرور مینی‌اپ (چندمستأجر) بداند دیتابیس و توکن کدام بات را استفاده کند."""
    if not MINIAPP_URL:
        return ""
    tenant_id = db.get_setting("miniapp_tenant_id", "")
    if tenant_id:
        sep = "&" if "?" in MINIAPP_URL else "?"
        return f"{MINIAPP_URL}{sep}b={tenant_id}"
    return MINIAPP_URL


MINIAPP_BTN_TEXT = "✨ مینی‌اپ فروشگاه"


def miniapp_inline_kb(miniapp_url: str) -> InlineKeyboardMarkup:
    """دکمه‌ی واقعی وب‌اپ به‌صورت inline (نه reply keyboard)، چون طبق تجربه‌ی عملی،
    initData وقتی از دکمه‌ی reply keyboard با web_app مستقیم باز شود، در برخی
    کلاینت‌های تلگرام همیشه خالی برمی‌گردد. راه اصلی و مطمئن، Menu Button
    (در bot_manager._sync_menu_button) است؛ این دکمه صرفاً یک مسیر جایگزین است."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MINIAPP_BTN_TEXT, web_app=WebAppInfo(url=miniapp_url))]
    ])


def _menu_items(db, is_admin: bool, is_reseller: bool, is_main_bot: bool, show_reseller_request: bool):
    """لیست مشترک آیتم‌های منوی اصلی را برمی‌گرداند: (key, text, style).
    این تابع پایه‌ی هر دو نوع منو (معمولی/پایین و شیشه‌ای/بالا) است تا منطق
    نمایش/عدم‌نمایش هر دکمه دقیقاً یک‌بار نوشته شده و همیشه هماهنگ بماند."""
    settings = db.get_all_settings()
    order = db.get_menu_order()
    miniapp_url = _miniapp_url(db)

    def item_miniapp():
        if settings.get("miniapp_enabled", "1") != "1":
            return None
        return (MINIAPP_BTN_TEXT, "") if miniapp_url else None

    def item_buy():
        return (settings.get("btn_buy", "🛒 خرید کانفیگ"), settings.get("btn_buy_style", ""))

    def item_test():
        if settings.get("test_enabled", "1") != "1":
            return None
        return (settings.get("btn_test", "🧪 کانفیگ تست رایگان"), settings.get("btn_test_style", ""))

    def item_my_orders():
        return (settings.get("btn_my_orders", "🧾 حساب کاربری من"), settings.get("btn_my_orders_style", ""))

    def item_referral():
        if settings.get("referral_button_enabled", "1") != "1":
            return None
        any_mode_enabled = (
            settings.get("referral_enabled", "1") == "1"
            or settings.get("referral_free_config_enabled", "0") == "1"
            or settings.get("referral_invite_bonus_enabled", "0") == "1"
        )
        if not any_mode_enabled:
            return None
        return (settings.get("btn_referral", "🤝 زیرمجموعه‌گیری من"), settings.get("btn_referral_style", ""))

    def item_wheel():
        if settings.get("wheel_enabled", "1") != "1":
            return None
        return (settings.get("btn_wheel", "🎡 گردونه شانس"), settings.get("btn_wheel_style", ""))

    def item_contact():
        return (settings.get("btn_contact", "📞 ارتباط با پشتیبانی"), settings.get("btn_contact_style", ""))

    def item_admin_panel():
        if not is_admin:
            return None
        return (settings.get("btn_admin_panel", "⚙️ پنل مدیریت"), settings.get("btn_admin_panel_style", ""))

    def item_reseller_panel():
        if not is_reseller:
            return None
        return (settings.get("btn_reseller_panel", "🧑‍💼 پنل نمایندگی"), settings.get("btn_reseller_panel_style", "primary"))

    def item_reseller_request():
        if not show_reseller_request:
            return None
        if settings.get("reseller_request_enabled", "1") != "1":
            return None
        return (settings.get("btn_reseller_request", "🏪 درخواست نمایندگی سطح ۲"), settings.get("btn_reseller_request_style", "primary"))

    builders = {
        "miniapp": item_miniapp,
        "btn_buy": item_buy,
        "btn_test": item_test,
        "btn_my_orders": item_my_orders,
        "btn_referral": item_referral,
        "btn_wheel": item_wheel,
        "btn_contact": item_contact,
        "btn_admin_panel": item_admin_panel,
        "btn_reseller_panel": item_reseller_panel,
        "btn_reseller_request": item_reseller_request,
    }

    items = []
    for key in order:
        builder = builders.get(key)
        if not builder:
            continue
        result = builder()
        if result:
            text, style = result
            items.append((key, text, style))
    return items


def _menu_columns(db) -> int:
    """تعداد دکمه در هر ردیف منوی اصلی (۱ یا ۲) بر اساس تنظیمات."""
    try:
        cols = int(db.get_setting("main_menu_columns", "1") or "1")
    except (TypeError, ValueError):
        cols = 1
    return 2 if cols == 2 else 1


def _chunk_row(buttons: list, columns: int) -> list:
    """لیست دکمه‌ها را به ردیف‌هایی با تعداد ستون مشخص تقسیم می‌کند - همان
    الگویی که در پنل مدیریت (admin_panel_kb) استفاده شده، فقط عمومی‌شده."""
    return [buttons[i:i + columns] for i in range(0, len(buttons), columns)]


def _menu_item_rows(db, items: list) -> list:
    """آیتم‌های منو (لیست تخت (key, text, style)) را بر اساس چیدمان دلخواه
    کاربر (main_menu_row_breaks) به ردیف‌ها تقسیم می‌کند: هر دکمه‌ای که کلیدش
    در لیست breaks باشد، یک ردیف تازه شروع می‌کند؛ بقیه به ردیف دکمه‌ی قبلی
    خودشان می‌چسبند. یعنی چیدمان دیگر به تعداد ستون ثابت محدود نیست - مثلاً
    می‌شود یک دکمه تمام‌عرض بالا، بعد چند دکمه کنار هم پایینش داشت.
    اگر کاربر هنوز چیدمان سفارشی نساخته باشد (breaks is None)، برای سازگاری
    با نصب‌های قدیمی از تنظیم main_menu_columns (۱ یا ۲ ستون ثابت) استفاده
    می‌شود."""
    breaks = db.get_menu_row_breaks()
    if breaks is None:
        columns = _menu_columns(db)
        return _chunk_row(items, columns)

    break_set = set(breaks)
    rows, current = [], []
    for item in items:
        key = item[0]
        if current and key in break_set:
            rows.append(current)
            current = []
        current.append(item)
    if current:
        rows.append(current)
    return rows


def main_menu_kb(db, is_admin: bool, is_reseller: bool = False, is_main_bot: bool = True,
                  show_reseller_request: bool = False):
    """منوی پایین (Reply Keyboard). اگر از تنظیمات غیرفعال شده باشد،
    ReplyKeyboardRemove برمی‌گردد تا کیبورد قبلی از پایین صفحه‌ی کاربر جمع شود."""
    if db.get_setting("main_menu_reply_enabled", "1") != "1":
        return ReplyKeyboardRemove()

    items = _menu_items(db, is_admin, is_reseller, is_main_bot, show_reseller_request)
    item_rows = _menu_item_rows(db, items)
    rows = [[_styled_button(text, style) for _key, text, style in row] for row in item_rows]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def main_menu_inline_kb(db, is_admin: bool, is_reseller: bool = False, is_main_bot: bool = True,
                         show_reseller_request: bool = False) -> InlineKeyboardMarkup:
    """منوی شیشه‌ای بالا (Inline Keyboard) - همان آیتم‌های منوی پایین، به شکل inline.
    روی کلیک هر دکمه، callback_data به‌صورت 'mm:<key>' ارسال می‌شود که در
    handlers_user.py / handlers_admin.py به همان هندلر متنی متناظرش وصل شده."""
    items = _menu_items(db, is_admin, is_reseller, is_main_bot, show_reseller_request)
    item_rows = _menu_item_rows(db, items)
    miniapp_url = _miniapp_url(db)

    def _build_button(key, text, style):
        if key == "miniapp" and miniapp_url:
            return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=miniapp_url))
        s = style if style in ("primary", "success", "danger") else None
        return InlineKeyboardButton(text=text, callback_data=f"mm:{key}", style=s)

    rows = [[_build_button(key, text, style) for key, text, style in row] for row in item_rows]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_for_user(db, user_tg_id: int, is_main_bot: bool = True):
    show_reseller_request = (
        is_main_bot
        and not db.is_reseller(user_tg_id)
        and not db.get_open_reseller_request(user_tg_id)
    )
    return main_menu_kb(db, db.is_admin(user_tg_id), db.is_reseller(user_tg_id), is_main_bot, show_reseller_request)


def inline_menu_for_user(db, user_tg_id: int, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    """معادل menu_for_user ولی نسخه‌ی شیشه‌ای (inline). اگر منوی شیشه‌ای از
    تنظیمات غیرفعال باشد None برمی‌گرداند تا فراخوان اصلاً پیامی نفرستد."""
    if db.get_setting("main_menu_inline_enabled", "0") != "1":
        return None
    show_reseller_request = (
        is_main_bot
        and not db.is_reseller(user_tg_id)
        and not db.get_open_reseller_request(user_tg_id)
    )
    return main_menu_inline_kb(db, db.is_admin(user_tg_id), db.is_reseller(user_tg_id), is_main_bot, show_reseller_request)


# ---------------------------------------------------------------------------
# دسته‌بندی‌ها / محصولات (کاربر)
# ---------------------------------------------------------------------------

def categories_kb(db, categories, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    rows = []
    custom_enabled = db.get_setting("custom_config_enabled", "0") == "1" or db.count_active_custom_config_products() > 0
    if db.is_full_access_bot(is_main_bot) and custom_enabled:
        rows.append([_styled_inline(db, "🛠 ساخت کانفیگ شخصی", "custom_config_start", "btn_custom_config_style")])
    for cat in categories:
        rows.append([_styled_inline(db, f"📁 {cat['name']}", f"cat:{cat['id']}", "btn_cat_select_style")])
    rows.append([_styled_inline(db, "⬅️ بازگشت", "back_main", "btn_buy_back_style")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_kb(db, products, category_id) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        stock = db.count_available_configs(p["id"])
        stock_tag = "✅" if stock > 0 else "⛔️"
        rows.append(
            [
                _styled_inline(
                    db,
                    f"{stock_tag} {p['name']} - {p['price']:,} تومان",
                    f"prod:{p['id']}",
                    "btn_product_select_style",
                )
            ]
        )
    rows.append([_styled_inline(db, "⬅️ بازگشت به دسته‌بندی‌ها", "back_categories", "btn_buy_back_style")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_confirm_kb(db, product_id, quantity: int = 1, max_qty: int = 1) -> InlineKeyboardMarkup:
    max_qty = max(max_qty, 1)
    quantity = max(1, min(quantity, max_qty))

    qty_row = []
    if quantity > 1:
        qty_row.append(InlineKeyboardButton(text="➖", callback_data=f"qty_dec:{product_id}:{quantity}"))
    qty_row.append(InlineKeyboardButton(text=f"🔢 تعداد: {quantity}", callback_data="noop"))
    if quantity < max_qty:
        qty_row.append(InlineKeyboardButton(text="➕", callback_data=f"qty_inc:{product_id}:{quantity}"))

    rows = [
        qty_row,
        [_styled_inline(db, "✅ ادامه و ارسال رسید", f"buy_start:{product_id}:{quantity}", "btn_buy_continue_style")],
        [_styled_inline(db, "🎟 وارد کردن کد تخفیف", f"enter_code:{product_id}:{quantity}", "btn_enter_code_style")],
        [_styled_inline(db, "⬅️ بازگشت", "back_categories", "btn_buy_back_style")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")]]
    )


def custom_config_username_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 نام کاربری خودکار", callback_data="custom_config_random_username")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")],
    ])


# ---------------------------------------------------------------------------
# سفارش‌های من (منوی کانفیگ‌ها با قابلیت حذف)
# ---------------------------------------------------------------------------

def my_orders_menu_kb(items) -> InlineKeyboardMarkup:
    """items: لیستی از دیکشنری‌های {cb_id, label} که هر کدام یک ردیف/دکمه‌ی جدا می‌شوند."""
    rows = [[InlineKeyboardButton(text=it["label"], callback_data=f"mo_v:{it['cb_id']}")] for it in items]
    rows.append([InlineKeyboardButton(text="⬅️ حساب کاربری", callback_data="acct:hub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_order_item_kb(cb_id: str, deletable: bool) -> InlineKeyboardMarkup:
    rows = []
    if deletable:
        rows.append([InlineKeyboardButton(text="🗑 حذف کامل این کانفیگ", callback_data=f"mo_del:{cb_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data="mo_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_order_error_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data="mo_back")]])


def service_detail_kb(db, cb_id: str, kind: str, deletable: bool, show_links: bool = False,
                       enabled: bool = True, auto_renew: bool = False, is_test: bool = False) -> InlineKeyboardMarkup:
    """دکمه‌های صفحه‌ی جزئیات یک سرویس.
    kind == 'custom' (کاربر واقعی روی پنل): هر سه نوع تمدید + قطع دسترسی +
    بروزرسانی + کیوآر + فعال/غیرفعال + تغییر نام + تمدید خودکار + انتقال +
    تاریخچه در دسترس است.
    is_test=True (کانفیگ تست، حتی اگر kind='custom' باشد): فقط بروزرسانی/کیوآر/
    حذف نمایش داده می‌شود؛ نباید قابلیت‌های کامل یک سرویس خریداری‌شده (تمدید،
    قطع دسترسی، تغییر نام، تمدید خودکار، انتقال، تاریخچه) را داشته باشد.
    kind == 'config' (لینک استخری بانک کانفیگ، بدون پنل/یوزرنیم واقعی):
    این نوع کنترلی روی خودِ حجم/زمان سرویس ندارد (نه تمدید، نه قطع دسترسی)
    ولی چون خودِ لینک/QR واقعی و قابل‌استفاده است، «بروزرسانی کانفیگ» و
    «کیوآر کانفیگ» هم برایش معنا دارد؛ در نهایت «حذف کامل سرویس» همیشه ته
    لیست است (اگر فعال باشد)."""
    def on(key: str) -> bool:
        return db.get_setting(key, "1") == "1"

    rows = []
    if kind == "custom" and not is_test:
        if on("svc_show_renew_full"):
            rows.append([InlineKeyboardButton(text="🛠 تمدید کامل سرویس", callback_data=f"svc_renew:full:{cb_id}")])
        row2 = []
        if on("svc_show_renew_volume"):
            row2.append(InlineKeyboardButton(text="🔋 تمدید حجم سرویس", callback_data=f"svc_renew:volume:{cb_id}"))
        if on("svc_show_renew_time"):
            row2.append(InlineKeyboardButton(text="⏱ تمدید زمان سرویس", callback_data=f"svc_renew:time:{cb_id}"))
        if row2:
            rows.append(row2)
        row3 = []
        if on("svc_show_cut_access"):
            row3.append(InlineKeyboardButton(text="🚫 قطع دسترسی و لینک جدید", callback_data=f"svc_cut:{cb_id}"))
        if row3:
            rows.append(row3)
        row5 = []
        if on("svc_show_toggle"):
            toggle_icon = "🔴 غیرفعال کردن کانفیگ" if enabled else "🟢 فعال کردن کانفیگ"
            row5.append(InlineKeyboardButton(text=toggle_icon, callback_data=f"svc_toggle:{cb_id}"))
        if on("svc_show_rename"):
            row5.append(InlineKeyboardButton(text="✏️ تغییر نام کانفیگ", callback_data=f"svc_rename:{cb_id}"))
        if row5:
            rows.append(row5)
        row6 = []
        if on("svc_show_auto_renew"):
            ar_icon = "🔄 تمدید خودکار: 🟢 فعال" if auto_renew else "🔄 تمدید خودکار: 🔴 غیرفعال"
            row6.append(InlineKeyboardButton(text=ar_icon, callback_data=f"svc_autorenew:{cb_id}"))
        if row6:
            rows.append(row6)
        row7 = []
        if on("svc_show_transfer"):
            row7.append(InlineKeyboardButton(text="👤 انتقال کانفیگ", callback_data=f"svc_transfer:{cb_id}"))
        if on("svc_show_history"):
            row7.append(InlineKeyboardButton(text="📜 تاریخچه سرویس", callback_data=f"svc_hist:{cb_id}"))
        if row7:
            rows.append(row7)
    if kind in ("custom", "config"):
        row4 = []
        if on("svc_show_update_config"):
            row4.append(InlineKeyboardButton(text="♻️ بروزرسانی کانفیگ", callback_data=f"mo_refresh:{cb_id}"))
        if on("svc_show_qr"):
            row4.append(InlineKeyboardButton(text="⬜ کیوآر کانفیگ", callback_data=f"svc_qr:{cb_id}"))
        if row4:
            rows.append(row4)
        if show_links:
            rows.append([InlineKeyboardButton(text="📋 کانفیگ‌های تکی", callback_data=f"mo_links:{cb_id}")])
    if deletable and on("svc_show_delete"):
        rows.append([InlineKeyboardButton(text="🗑 حذف کامل این سرویس", callback_data=f"mo_del:{cb_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data="mo_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# حساب کاربری (جایگزین دکمه‌ی «سفارش‌های من»؛ سفارش‌ها/زیرمجموعه‌گیری/کیف‌پول
# حالا همه یک ورودی واحد دارند)
# ---------------------------------------------------------------------------

def account_hub_kb(db) -> InlineKeyboardMarkup:
    rows = []
    if db.get_setting("acct_show_orders", "1") == "1":
        rows.append([InlineKeyboardButton(text="📦 سرویس‌ها و سفارش‌های من", callback_data="acct:orders")])
    if db.get_setting("acct_show_referral", "1") == "1":
        rows.append([InlineKeyboardButton(text="🤝 زیرمجموعه‌گیری من", callback_data="acct:referral")])
    if db.get_setting("acct_show_wallet", "1") == "1":
        rows.append([InlineKeyboardButton(text="👛 کیف پول من", callback_data="acct:wallet")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به منوی اصلی", callback_data="acct:main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def renewal_plans_kb(products, mode: str, cb_id: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{p['name']} - {p['auto_provision_volume_gb']} گیگ / {p['duration_days']} روز - {p['price']:,} تومان",
            callback_data=f"svc_renew_pick:{mode}:{cb_id}:{p['id']}",
        )]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text="⬅️ انصراف", callback_data=f"mo_v:{cb_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def renewal_pricing_kb(db) -> InlineKeyboardMarkup:
    """نرخ ثابتِ «هر گیگابایت» و «هر روز» برای تمدید فقط-حجم / فقط-زمان سرویس‌ها
    (مستقل از قیمت پلن‌ها که مخصوص تمدید کامل است)."""
    price_per_gb = int(db.get_setting("renewal_price_per_gb", "0") or "0")
    price_per_day = int(db.get_setting("renewal_price_per_day", "0") or "0")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔋 نرخ هر گیگ: {price_per_gb:,} تومان", callback_data="adm_renewal_price_gb")],
        [InlineKeyboardButton(text=f"⏱ نرخ هر روز: {price_per_day:,} تومان", callback_data="adm_renewal_price_day")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:finance")],
    ])


# ---------------------------------------------------------------------------
# تنظیمات ادمین: فعال/غیرفعال کردن دکمه‌های حساب کاربری/صفحه‌ی سرویس
# ---------------------------------------------------------------------------

def account_settings_kb(db) -> InlineKeyboardMarkup:
    rows = []
    for key, label, default in ACCOUNT_TOGGLE_KEYS:
        state_on = db.get_setting(key, default) == "1"
        icon = "🟢" if state_on else "🔴"
        rows.append([InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"adm_acct_toggle:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:appearance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_order_delete_confirm_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ بله، برای همیشه حذف شود", callback_data=f"mo_delok:{cb_id}")],
        [InlineKeyboardButton(text="↩️ انصراف", callback_data=f"mo_v:{cb_id}")],
    ])


def service_cut_confirm_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ بله، دسترسی قطع و لینک جدید صادر شود", callback_data=f"svc_cutok:{cb_id}")],
        [InlineKeyboardButton(text="↩️ انصراف", callback_data=f"mo_v:{cb_id}")],
    ])


def service_rename_cancel_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")],
    ])


def service_transfer_confirm_kb(cb_id: str, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ بله، منتقل شود", callback_data=f"svc_transok:{cb_id}:{target_id}")],
        [InlineKeyboardButton(text="↩️ انصراف", callback_data=f"mo_v:{cb_id}")],
    ])


def service_history_back_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"mo_v:{cb_id}")],
    ])


def my_orders_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data="mo_back")]]
    )


def reseller_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ساخت کانفیگ جدید", callback_data="reseller_new_config")],
    ])


def payment_choice_kb(crypto_enabled: bool, abangateway_enabled: bool = False,
                       custom_gateways: list = None, card_to_card_enabled: bool = True,
                       amount: int = None, db=None, allowed_methods=None,
                       card_auto_enabled: bool = False) -> InlineKeyboardMarkup:
    """کیبورد مرحله‌ی انتخاب روش پرداخت: کاربر ابتدا این لیست را می‌بیند و روش پرداخت را
    انتخاب می‌کند (به‌جای اینکه مستقیم شماره کارت نمایش داده شود). اگر درگاه کریپتو/آبان
    گیت وی/درگاه‌های سفارشی/کارت‌به‌کارت خودکار فعال باشند، دکمه‌ی مربوطه هم نمایش داده
    می‌شود. کارت‌به‌کارت دستی هم با تنظیم card_to_card_enabled قابل غیرفعال‌سازی است.
    custom_gateways لیستی از دیکشنری‌های {"id", "key", "name"} است (خروجی
    custom_gateway_payment.list_enabled_gateways).

    amount + db: در صورت ارسال، دکمه‌ی هر روشی که «حداقل مبلغ» تنظیم‌شده‌اش از amount
    بیشتر باشد حذف می‌شود. allowed_methods: در صورت ارسال (لیست کلیدها یا None برای
    «همه مجاز»)، فقط دکمه‌ی روش‌های مجاز برای محصول/آیتم جاری نمایش داده می‌شود."""

    def _ok(method_key: str) -> bool:
        if allowed_methods is not None and method_key not in allowed_methods:
            return False
        if db is not None and amount is not None:
            min_amt = db.get_payment_method_min_amount(method_key)
            if min_amt and amount < min_amt:
                return False
        return True

    rows = []
    if card_to_card_enabled and _ok("card"):
        rows.append([InlineKeyboardButton(text="💳 کارت‌به‌کارت (ارسال رسید)", callback_data="pay_card2card")])
    if card_auto_enabled and _ok("card_auto"):
        rows.append([InlineKeyboardButton(text="💳 کارت‌به‌کارت (تایید خودکار پیامکی)", callback_data="pay_card_auto")])
    if abangateway_enabled and _ok("abangateway"):
        rows.append([InlineKeyboardButton(text="💳 پرداخت خودکار کارت‌به‌کارت (تایید آنی)", callback_data="pay_abangateway")])
    if crypto_enabled and _ok("crypto"):
        rows.append([InlineKeyboardButton(text="🪙 پرداخت با ارز دیجیتال (تایید آنی)", callback_data="pay_crypto")])
    for gw in (custom_gateways or []):
        if _ok(f"custom:{gw['key']}"):
            rows.append([InlineKeyboardButton(text=f"💠 {gw['name']} (تایید آنی)", callback_data=f"pay_customgw:{gw['id']}")])
    rows.append([InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات پرداخت کارت‌به‌کارت (دستی): نمایش شماره کارت فعلی، وضعیت
    فعال/غیرفعال و دکمه‌های تغییر."""
    card_number = db.get_setting("card_number") or "-"
    card_holder = db.get_setting("card_holder") or "-"
    enabled = db.get_setting("card_to_card_enabled", "1") == "1"
    toggle_text = "🔴 غیرفعال کردن پرداخت کارت‌به‌کارت" if enabled else "🟢 فعال کردن پرداخت کارت‌به‌کارت"
    rows = [
        [InlineKeyboardButton(text=f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}", callback_data="noop")],
        [InlineKeyboardButton(text=f"💳 شماره کارت: {card_number}", callback_data="noop")],
        [InlineKeyboardButton(text=f"👤 به نام: {card_holder}", callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_card_toggle")],
        [InlineKeyboardButton(text="✏️ تغییر شماره کارت / صاحب حساب", callback_data="adm_set_card_edit")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_auto_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات کارت‌به‌کارت با تایید خودکار (پیامک بانک): وضعیت، مهلت،
    تعداد رقم یکتاساز، واحد مبلغ، لیست کارت‌ها و اتصال وب‌هوک."""
    enabled = db.get_setting("card_to_card_auto_enabled", "0") == "1"
    timeout = db.get_setting("card_to_card_auto_timeout_minutes", "15")
    digits = db.get_setting("card_to_card_auto_amount_digits", "3")
    unit = db.get_setting("card_to_card_sms_amount_unit", "rial")
    unit_label = "ریال" if unit == "rial" else "تومان"
    toggle_text = "🔴 غیرفعال کردن" if enabled else "🟢 فعال کردن"
    rows = [
        [InlineKeyboardButton(text=f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}", callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_card_auto_toggle")],
        [InlineKeyboardButton(text=f"⏱ مهلت هر مبلغ: {timeout} دقیقه", callback_data="adm_card_auto_timeout")],
        [InlineKeyboardButton(text=f"🔢 رقم یکتاساز مبلغ: {digits}", callback_data="adm_card_auto_digits")],
        [InlineKeyboardButton(text=f"💰 واحد مبلغ پیامک: {unit_label} (تغییر)", callback_data="adm_card_auto_unit_toggle")],
        [InlineKeyboardButton(text="💳 مدیریت کارت‌ها", callback_data="adm_card_auto_cards")],
        [InlineKeyboardButton(text="📡 اتصال اپ BankSmsForwarder", callback_data="adm_card_auto_webhook")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_auto_cards_kb(cards) -> InlineKeyboardMarkup:
    """لیست کارت‌های کارت‌به‌کارت خودکار با امکان ورود به جزئیات هرکدام."""
    rows = []
    for c in cards:
        icon = "🟢" if c["is_active"] else "🔴"
        last4 = (c["card_number"] or "")[-4:]
        holder = c["holder_name"] or "-"
        rows.append([InlineKeyboardButton(
            text=f"{icon} ...{last4} — {holder}", callback_data=f"adm_card_auto_card:{c['id']}",
        )])
    if not cards:
        rows.append([InlineKeyboardButton(text="هنوز کارتی اضافه نشده", callback_data="noop")])
    rows.append([InlineKeyboardButton(text="➕ افزودن کارت جدید", callback_data="adm_card_auto_card_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_card_auto")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_auto_card_detail_kb(card) -> InlineKeyboardMarkup:
    """عملیات یک کارت مشخص: فعال/غیرفعال، ویرایش، حذف."""
    toggle_text = "🔴 غیرفعال کردن" if card["is_active"] else "🟢 فعال کردن"
    rows = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_card_auto_card_toggle:{card['id']}")],
        [InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"adm_card_auto_card_edit:{card['id']}")],
        [InlineKeyboardButton(text="🗑 حذف", callback_data=f"adm_card_auto_card_del:{card['id']}")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_card_auto_cards")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# سفارش برای ادمین (تایید/رد)
# ---------------------------------------------------------------------------

def order_review_kb(order_id) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✅ تایید و ارسال کانفیگ", callback_data=f"order_approve:{order_id}"),
            InlineKeyboardButton(text="❌ رد کردن", callback_data=f"order_reject:{order_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contact_reply_kb(user_tg_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="↩️ پاسخ به کاربر", callback_data=f"reply_user:{user_tg_id}")]]
    )


# ---------------------------------------------------------------------------
# ارتباط با پشتیبانی (پیام مستقیم / تیکت / چت مستقیم با مدیر)
# ---------------------------------------------------------------------------

TICKET_STATUS_LABELS = {"open": "🟢 باز", "answered": "🟡 پاسخ داده‌شده", "closed": "🔴 بسته‌شده"}


def contact_menu_kb(db) -> InlineKeyboardMarkup:
    """منوی اصلی بخش «ارتباط با پشتیبانی»: پیام مستقیم، تیکت و در صورت تنظیم‌بودن
    آیدی مدیر، یک دکمه‌ی لینک برای باز شدن مستقیم پی‌وی او."""
    rows = [
        [InlineKeyboardButton(text="✉️ پیام مستقیم به پشتیبانی", callback_data="contact_direct")],
        [InlineKeyboardButton(text="🎫 ثبت تیکت جدید", callback_data="tickets_new")],
        [InlineKeyboardButton(text="📂 تیکت‌های من", callback_data="tickets_mine")],
    ]
    support_admin_id = (db.get_setting("support_admin_id") or "").strip()
    if support_admin_id.lstrip("-").isdigit():
        rows.append(
            [InlineKeyboardButton(text="👤 چت مستقیم با مدیر", url=f"tg://user?id={support_admin_id}")]
        )
    rows.append([InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tickets_list_kb(tickets) -> InlineKeyboardMarkup:
    """tickets: لیستی از ردیف‌های جدول tickets (هرکدام id, subject, status دارند)."""
    rows = []
    for t in tickets:
        status_icon = {"open": "🟢", "answered": "🟡", "closed": "🔴"}.get(t["status"], "⚪️")
        subject = (t["subject"] or "بدون موضوع").strip()
        if len(subject) > 30:
            subject = subject[:30] + "…"
        rows.append(
            [InlineKeyboardButton(text=f"{status_icon} #{t['id']} — {subject}", callback_data=f"ticket_view:{t['id']}")]
        )
    if not rows:
        rows.append([InlineKeyboardButton(text="هنوز تیکتی ثبت نکرده‌اید.", callback_data="noop")])
    rows.append([InlineKeyboardButton(text="🎫 ثبت تیکت جدید", callback_data="tickets_new")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="contact_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ticket_thread_kb(ticket_id: int, is_closed: bool, back_callback: str = "tickets_mine") -> InlineKeyboardMarkup:
    rows = []
    if not is_closed:
        rows.append([InlineKeyboardButton(text="✉️ ارسال پیام در این تیکت", callback_data=f"ticket_reply:{ticket_id}")])
        rows.append([InlineKeyboardButton(text="🔒 بستن تیکت", callback_data=f"ticket_close:{ticket_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به لیست تیکت‌ها", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ticket_admin_notify_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ پاسخ به تیکت", callback_data=f"adm_ticket_reply:{ticket_id}")],
        [InlineKeyboardButton(text="👁 مشاهده کامل تیکت", callback_data=f"adm_ticket_view:{ticket_id}")],
    ])


def admin_tickets_list_kb(tickets, active_status: str) -> InlineKeyboardMarkup:
    rows = []
    for t in tickets:
        status_icon = {"open": "🟢", "answered": "🟡", "closed": "🔴"}.get(t["status"], "⚪️")
        subject = (t["subject"] or "بدون موضوع").strip()
        if len(subject) > 30:
            subject = subject[:30] + "…"
        rows.append(
            [InlineKeyboardButton(
                text=f"{status_icon} #{t['id']} — {subject}",
                callback_data=f"adm_ticket_view:{t['id']}:{active_status}",
            )]
        )
    if not rows:
        rows.append([InlineKeyboardButton(text="موردی یافت نشد.", callback_data="noop")])
    tabs = [("open", "🟢 باز"), ("answered", "🟡 پاسخ‌داده‌شده"), ("closed", "🔴 بسته‌شده"), ("all", "📋 همه")]
    tab_row = [
        InlineKeyboardButton(text=("✅ " if key == active_status else "") + label, callback_data=f"adm_tickets_list:{key}")
        for key, label in tabs
    ]
    rows.append(tab_row[:2])
    rows.append(tab_row[2:])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به پنل مدیریت", callback_data="adm_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_view_kb(ticket_id: int, status: str, active_status: str) -> InlineKeyboardMarkup:
    rows = []
    if status != "closed":
        rows.append([InlineKeyboardButton(text="↩️ پاسخ به تیکت", callback_data=f"adm_ticket_reply:{ticket_id}")])
        rows.append([InlineKeyboardButton(text="🔒 بستن تیکت", callback_data=f"adm_ticket_close:{ticket_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data=f"adm_tickets_list:{active_status}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_contact_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی پنل مدیریت برای تنظیم آیدی عددی تلگرام مدیر که در بخش ارتباط با
    پشتیبانی، دکمه‌ی «چت مستقیم با مدیر» به پی‌وی همان آیدی باز می‌شود."""
    current_id = (db.get_setting("support_admin_id") or "").strip() or "-"
    rows = [
        [InlineKeyboardButton(text=f"🆔 آیدی فعلی: {current_id}", callback_data="noop")],
        [InlineKeyboardButton(text="✏️ تغییر آیدی مدیر", callback_data="adm_set_support_contact_edit")],
    ]
    if current_id != "-":
        rows.append([InlineKeyboardButton(text="🗑 حذف (غیرفعال کردن دکمه)", callback_data="adm_clear_support_contact")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:access")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# پنل مدیریت
# ---------------------------------------------------------------------------

# لیست دکمه‌های پنل مدیریت: (کلید تنظیمات رنگ, متن, callback_data)
ADMIN_PANEL_ITEMS = [
    ("adm_categories", "📂 مدیریت دسته‌بندی‌ها", "adm_categories"),
    ("adm_products", "📦 مدیریت محصولات", "adm_products"),
    ("adm_add_configs", "🔗 افزودن کانفیگ به محصول", "adm_add_configs"),
    ("adm_random_cfg", "🎲 دریافت کانفیگ رندوم", "adm_random_cfg"),
    ("adm_test_menu", "🧪 مدیریت کانفیگ تست", "adm_test_menu"),
    ("adm_forcejoin_menu", "📢 عضویت اجباری در کانال", "adm_forcejoin_menu"),
    ("adm_pending_orders", "🧾 سفارش‌های در انتظار", "adm_pending_orders"),
    ("adm_tickets_menu", "🎫 تیکت‌های پشتیبانی", "adm_tickets_menu"),
    ("adm_pending_topups", "👛 درخواست‌های شارژ کیف پول", "adm_pending_topups"),
    ("adm_crypto_payments", "🪙 پرداخت‌های کریپتو", "adm_crypto_payments"),
    ("adm_abangateway_payments", "💳 پرداخت‌های آبان گیت وی", "adm_abangateway_payments"),
    ("adm_discounts_menu", "🎟 مدیریت کدهای تخفیف", "adm_discounts_menu"),
    ("adm_wheel_settings", "🎡 مدیریت گردونه شانس", "adm_wheel_settings"),
    ("adm_renewal_settings", "🔔 یادآوری تمدید سرویس", "adm_renewal_settings"),
    ("adm_volume_reminder_settings", "📉 یادآوری اتمام حجم", "adm_volume_reminder_settings"),
    ("adm_stock_alert_settings", "📦 آستانه‌ی هشدار موجودی", "adm_stock_alert_settings"),
    ("adm_custom_config_settings", "🛠 ساخت کانفیگ شخصی (پنل‌های VPN)", "adm_custom_config_settings"),
    ("adm_renewal_pricing", "💳 قیمت‌گذاری تمدید حجم/زمان", "adm_renewal_pricing"),
    ("adm_delivery_settings", "📤 تنظیمات ارسال کانفیگ", "adm_delivery_settings"),
    ("adm_referral_settings", "🤝 تنظیمات زیرمجموعه‌گیری", "adm_referral_settings"),
    ("adm_resellers_menu", "🏪 مدیریت بات‌های نمایندگی", "adm_resellers_menu"),
    ("adm_credit_resellers_menu", "💳 نمایندگی حجمی (اعتبار)", "adm_credit_resellers_menu"),
    ("adm_reseller_requests_menu", "📋 درخواست‌های نمایندگی", "adm_reseller_requests_menu"),
    ("adm_edit_buttons", "✏️ ویرایش متن دکمه‌ها", "adm_edit_buttons"),
    ("adm_account_settings", "🧾 تنظیمات حساب کاربری کاربران", "adm_account_settings"),
    ("adm_main_menu_settings", "🧩 چیدمان/نمایش منوی اصلی", "adm_main_menu_settings"),
    ("adm_set_card", "💳 تنظیم شماره کارت", "adm_set_card"),
    ("adm_card_autodelete", "⏱ حذف خودکار پیام شماره کارت", "adm_card_autodelete"),
    ("adm_set_plisio", "🪙 تنظیم درگاه کریپتو (Plisio)", "adm_set_plisio"),
    ("adm_set_abangateway", "💳 تنظیم درگاه آبان گیت وی", "adm_set_abangateway"),
    ("adm_card_auto", "📶 کارت‌به‌کارت با تایید خودکار (پیامک بانک)", "adm_card_auto"),
    ("adm_custom_gateways", "💠 درگاه‌های پرداخت سفارشی (فعال/غیرفعال)", "adm_custom_gateways"),
    ("adm_min_amount_settings", "🧮 حداقل مبلغ پرداخت‌ها", "adm_min_amount_settings"),
    ("adm_edit_welcome", "📝 ویرایش پیام خوش‌آمد", "adm_edit_welcome"),
    ("adm_admins_menu", "👤 مدیریت ادمین‌ها", "adm_admins_menu"),
    ("adm_broadcast", "📢 پیام همگانی", "adm_broadcast"),
    ("adm_deeplink_tools", "🔗 دیپ‌لینک و پست کانال", "adm_deeplink_tools"),
    ("adm_stats", "📊 آمار فروش", "adm_stats"),
    ("adm_backup_menu", "🗄 بکاپ و بازیابی", "adm_backup_menu"),
    ("adm_temp_message", "⏳ پیام موقت (خودحذف‌شونده)", "adm_temp_message"),
    ("adm_set_support_contact", "🆔 آیدی مدیر برای چت مستقیم", "adm_set_support_contact"),
]


def _styled_inline(db, text: str, callback_data: str, style_key: str) -> InlineKeyboardButton:
    style_value = db.get_setting(style_key, "")
    style = style_value if style_value in ("primary", "success", "danger") else None
    return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)


# ---------------------------------------------------------------------------
# دسته‌بندی پنل مدیریت: هر دسته یک زیرمنوی مجزا می‌شود تا صفحه‌ی اصلی پنل
# شلوغ نباشد. ترتیب دسته‌ها بر اساس میزان استفاده‌ی روزمره‌ی ادمین چیده شده.
# ---------------------------------------------------------------------------
ADMIN_PANEL_CATEGORIES = [
    ("daily", "📋 کارهای روزانه", [
        "adm_pending_orders",
        "adm_tickets_menu",
        "adm_pending_topups",
        "adm_crypto_payments",
        "adm_abangateway_payments",
        "adm_reseller_requests_menu",
    ]),
    ("products", "📦 محصولات و کانفیگ", [
        "adm_categories",
        "adm_products",
        "adm_add_configs",
        "adm_random_cfg",
        "adm_test_menu",
        "adm_custom_config_settings",
        "adm_delivery_settings",
    ]),
    ("resellers", "🤝 نمایندگی‌ها", [
        "adm_resellers_menu",
        "adm_credit_resellers_menu",
    ]),
    ("marketing", "🎯 بازاریابی و تشویقی", [
        "adm_discounts_menu",
        "adm_wheel_settings",
        "adm_referral_settings",
        "adm_broadcast",
        "adm_deeplink_tools",
    ]),
    ("finance", "💰 مالی و پرداخت", [
        "adm_set_card",
        "adm_card_autodelete",
        "adm_set_plisio",
        "adm_set_abangateway",
        "adm_card_auto",
        "adm_custom_gateways",
        "adm_min_amount_settings",
        "adm_renewal_pricing",
    ]),
    ("alerts", "🔔 یادآوری‌ها و هشدارها", [
        "adm_renewal_settings",
        "adm_volume_reminder_settings",
        "adm_stock_alert_settings",
    ]),
    ("access", "🔐 دسترسی و امنیت", [
        "adm_forcejoin_menu",
        "adm_admins_menu",
        "adm_set_support_contact",
    ]),
    ("appearance", "🎨 ظاهر و رنگ‌بندی", [
        "adm_edit_buttons",
        "adm_account_settings",
        "adm_main_menu_settings",
        "adm_edit_welcome",
        "adm_panel_colors_menu",
        "adm_buyflow_colors_menu",
    ]),
    ("management", "👥 مدیریت و آمار", [
        "adm_stats",
        "adm_backup_menu",
        "adm_temp_message",
    ]),
]

# دو آیتم زیر واقعی نیستند (منوی رنگ‌بندی هستند نه اکشن مستقیم) اما برای اینکه
# در دسته‌ی «ظاهر» قابل نمایش باشند، برچسب/کال‌بک‌شان اینجا تعریف می‌شود.
_EXTRA_PANEL_ITEM_LABELS = {
    "adm_panel_colors_menu": "🎨 رنگ‌آمیزی دکمه‌های پنل مدیریت",
    "adm_buyflow_colors_menu": "🎨 رنگ‌آمیزی دکمه‌های مسیر خرید",
}


def _admin_item_label_and_cb(key: str):
    if key in _EXTRA_PANEL_ITEM_LABELS:
        return _EXTRA_PANEL_ITEM_LABELS[key], key
    for item_key, label, callback_data in ADMIN_PANEL_ITEMS:
        if item_key == key:
            return label, callback_data
    return key, key


def _is_item_visible(db, key: str, is_main_bot: bool) -> bool:
    if key in ("adm_resellers_menu", "adm_credit_resellers_menu", "adm_reseller_requests_menu") and not is_main_bot:
        # بات‌های نمایندگی خودشان اجازه‌ی ساخت زیرنماینده، فروش اعتبار یا مدیریت
        # درخواست‌های نمایندگی سطح ۲ (که فقط از بات اصلی قابل درخواست است) را ندارند
        return False
    if key == "adm_custom_config_settings" and not db.is_full_access_bot(is_main_bot):
        # ساخت کانفیگ شخصی به اتصال مستقیم پنل VPN نیاز دارد که فقط از بات اصلی یا نمایندگی کامل قابل مدیریت است
        return False
    if key == "adm_add_configs" and not db.is_full_access_bot(is_main_bot):
        # نماینده سطح ۲ بانک لینک دستی ندارد؛ محصولاتش همیشه خودکار از اعتبار حجمی تامین می‌شوند
        return False
    return True


def admin_panel_kb(db, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    """کیبورد سطح اول پنل مدیریت: فقط دسته‌ها نمایش داده می‌شوند، نه هر ۲۶ آیتم."""
    rows = []
    current_row = []
    for cat_key, cat_label, item_keys in ADMIN_PANEL_CATEGORIES:
        visible_items = [k for k in item_keys if _is_item_visible(db, k, is_main_bot)]
        if not visible_items:
            continue
        current_row.append(InlineKeyboardButton(text=cat_label, callback_data=f"adm_cat:{cat_key}"))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_exit_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_category_kb(db, is_main_bot: bool, cat_key: str) -> InlineKeyboardMarkup:
    """زیرمنوی یک دسته: آیتم‌های همان دسته با چیدمان دو ستونه + بازگشت."""
    item_keys = next((items for key, _, items in ADMIN_PANEL_CATEGORIES if key == cat_key), [])
    rows = []
    current_row = []
    for key in item_keys:
        if not _is_item_visible(db, key, is_main_bot):
            continue
        label, callback_data = _admin_item_label_and_cb(key)
        if key in _EXTRA_PANEL_ITEM_LABELS:
            current_row.append(InlineKeyboardButton(text=label, callback_data=callback_data))
        else:
            current_row.append(_styled_inline(db, label, callback_data, f"{key}_style"))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به پنل مدیریت", callback_data="adm_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_category_label(cat_key: str) -> str:
    for key, label, _ in ADMIN_PANEL_CATEGORIES:
        if key == cat_key:
            return label
    return "🔧 پنل مدیریت"


def admin_backup_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📥 دریافت بکاپ فوری", callback_data="adm_backup_now")],
        [InlineKeyboardButton(text="♻️ بازیابی از فایل بکاپ", callback_data="adm_restore_start")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:management")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_restore_confirm_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✅ بله، جایگزین کن", callback_data="adm_restore_confirm")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="adm_restore_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_restore_waiting_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="❌ انصراف", callback_data="adm_restore_cancel_wait")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_temp_message_target_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👤 به خودم", callback_data="adm_tempmsg_target:self")],
        [InlineKeyboardButton(text="🔢 آیدی عددی کاربر", callback_data="adm_tempmsg_target:custom")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:management")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_temp_message_duration_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="۱ ساعت", callback_data="adm_tempmsg_dur:3600"),
            InlineKeyboardButton(text="۶ ساعت", callback_data="adm_tempmsg_dur:21600"),
        ],
        [
            InlineKeyboardButton(text="۱ روز", callback_data="adm_tempmsg_dur:86400"),
            InlineKeyboardButton(text="۳ روز", callback_data="adm_tempmsg_dur:259200"),
        ],
        [InlineKeyboardButton(text="✏️ مدت دلخواه (دقیقه)", callback_data="adm_tempmsg_dur:custom")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="adm_temp_message")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_settings_kb(db) -> InlineKeyboardMarkup:
    """تنظیمات فعال/غیرفعال بودن ارسال لینک اشتراک و ارسال کانفیگ‌های تکی استخراج‌شده
    (برای هر سه مسیر تحویل: بانک کانفیگ، محصول متصل به پنل، ساخت کانفیگ شخصی، و کانفیگ تست)."""
    sub_link_on = db.get_setting("deliver_sub_link_enabled", "1") != "0"
    individual_on = db.get_setting("deliver_individual_configs_enabled", "1") != "0"
    sub_link_text = "✅ ارسال لینک اشتراک: فعال" if sub_link_on else "❌ ارسال لینک اشتراک: غیرفعال"
    individual_text = "✅ ارسال کانفیگ‌های تکی: فعال" if individual_on else "❌ ارسال کانفیگ‌های تکی: غیرفعال"
    rows = [
        [InlineKeyboardButton(text=sub_link_text, callback_data="adm_deliver_sublink_toggle")],
        [InlineKeyboardButton(text=individual_text, callback_data="adm_deliver_individual_toggle")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_duration_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🚫 بدون حذف خودکار", callback_data="adm_broadcast_dur:0")],
        [
            InlineKeyboardButton(text="۱ ساعت", callback_data="adm_broadcast_dur:3600"),
            InlineKeyboardButton(text="۶ ساعت", callback_data="adm_broadcast_dur:21600"),
        ],
        [
            InlineKeyboardButton(text="۱ روز", callback_data="adm_broadcast_dur:86400"),
            InlineKeyboardButton(text="۳ روز", callback_data="adm_broadcast_dur:259200"),
        ],
        [InlineKeyboardButton(text="✏️ مدت دلخواه (دقیقه)", callback_data="adm_broadcast_dur:custom")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="adm_broadcast")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_card_autodelete_kb(current_seconds: int) -> InlineKeyboardMarkup:
    """پیکر مدت حذف خودکار پیام‌های شماره کارت. تیک ✅ روی گزینه‌ی فعلی می‌آید."""
    def mark(seconds: int, label: str) -> str:
        return f"✅ {label}" if current_seconds == seconds else label

    rows = [
        [InlineKeyboardButton(text=mark(0, "🚫 خاموش (پیام برای همیشه می‌ماند)"), callback_data="adm_card_autodel:0")],
        [
            InlineKeyboardButton(text=mark(1800, "۳۰ دقیقه"), callback_data="adm_card_autodel:1800"),
            InlineKeyboardButton(text=mark(3600, "۱ ساعت"), callback_data="adm_card_autodel:3600"),
        ],
        [
            InlineKeyboardButton(text=mark(10800, "۳ ساعت"), callback_data="adm_card_autodel:10800"),
            InlineKeyboardButton(text=mark(86400, "۱ روز"), callback_data="adm_card_autodel:86400"),
        ],
        [InlineKeyboardButton(text="✏️ مدت دلخواه (دقیقه)", callback_data="adm_card_autodel:custom")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_colors_kb(db, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    """رنگ‌آمیزی دکمه‌های پنل مدیریت، گروه‌بندی‌شده بر اساس همان دسته‌های پنل
    تا پیدا کردن دکمه‌ی موردنظر برای تغییر رنگ ساده‌تر باشد."""
    rows = []
    for cat_key, cat_label, item_keys in ADMIN_PANEL_CATEGORIES:
        # آیتم‌های منوی رنگ (خودشان) در این لیست معنا ندارند
        real_items = [k for k in item_keys if k not in _EXTRA_PANEL_ITEM_LABELS]
        visible_items = [k for k in real_items if _is_item_visible(db, k, is_main_bot)]
        if not visible_items:
            continue
        rows.append([InlineKeyboardButton(text=f"── {cat_label} ──", callback_data="noop")])
        for key in visible_items:
            label, _ = _admin_item_label_and_cb(key)
            current_style = db.get_setting(f"{key}_style", "")
            style_icon = {"primary": "🔵", "success": "🟢", "danger": "🔴", "": "⚪️"}.get(current_style, "⚪️")
            rows.append(
                [
                    InlineKeyboardButton(text=f"{style_icon} {label}", callback_data="noop"),
                    InlineKeyboardButton(text="🎨 تغییر رنگ", callback_data=f"adm_btn_color_menu:{key}"),
                ]
            )
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:appearance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


BUY_FLOW_COLOR_ITEMS = [
    ("btn_cat_select", "📁 دکمه‌های انتخاب دسته‌بندی"),
    ("btn_product_select", "📦 دکمه‌های انتخاب محصول"),
    ("btn_buy_continue", "✅ دکمه «ادامه و ارسال رسید»"),
    ("btn_enter_code", "🎟 دکمه «وارد کردن کد تخفیف»"),
    ("btn_buy_back", "⬅️ دکمه‌های بازگشت در مسیر خرید"),
]


def buy_flow_colors_kb(db) -> InlineKeyboardMarkup:
    rows = []
    for key, label in BUY_FLOW_COLOR_ITEMS:
        current_style = db.get_setting(f"{key}_style", "")
        style_icon = {"primary": "🔵", "success": "🟢", "danger": "🔴", "": "⚪️"}.get(current_style, "⚪️")
        rows.append(
            [
                InlineKeyboardButton(text=f"{style_icon} {label}", callback_data="noop"),
                InlineKeyboardButton(text="🎨 تغییر رنگ", callback_data=f"adm_btn_color_menu:{key}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:appearance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_stats_period_kb(active_days: int = 7) -> InlineKeyboardMarkup:
    periods = [(1, "امروز"), (7, "۷ روز اخیر"), (30, "۳۰ روز اخیر"), (90, "۹۰ روز اخیر")]
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if d == active_days else "") + label,
                callback_data=f"adm_stats_p:{d}",
            )
            for d, label in periods[:2]
        ],
        [
            InlineKeyboardButton(
                text=("✅ " if d == active_days else "") + label,
                callback_data=f"adm_stats_p:{d}",
            )
            for d, label in periods[2:]
        ],
        [InlineKeyboardButton(text="⬅️ بازگشت به پنل مدیریت", callback_data="adm_back_panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_back_kb(callback_data="adm_back_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت به پنل مدیریت", callback_data=callback_data)]]
    )


def deeplink_tools_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 ساخت دیپ‌لینک تبلیغاتی", callback_data="adm_dl_build")],
        [InlineKeyboardButton(text="🖼 افزودن دکمه به پست کانال", callback_data="adm_dl_addbtn")],
        [InlineKeyboardButton(text="📋 پارامترهای اصلی منوی کاربر", callback_data="adm_dl_params_list")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:marketing")],
    ])


def deeplink_type_picker_kb(back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 خرید", callback_data="adm_dlp_type:buy")],
        [InlineKeyboardButton(text="🎟 کد تخفیف", callback_data="adm_dlp_type:disc")],
        [InlineKeyboardButton(text="🧪 کانفیگ تست", callback_data="adm_dlp_type:test")],
        [InlineKeyboardButton(text="🎡 گردونه شانس", callback_data="adm_dlp_type:wheel")],
        [InlineKeyboardButton(text="🏷 پارامتر دلخواه (فقط آمار منبع)", callback_data="adm_dlp_type:custom")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data=back_callback)],
    ])


def deeplink_discount_picker_kb(codes, back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🎟 {c['code']}", callback_data=f"adm_dlp_code:{c['id']}")]
        for c in codes if c["is_active"]
    ]
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_categories_kb(categories) -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        state_icon = "🟢" if cat["is_active"] else "🔴"
        rows.append(
            [
                InlineKeyboardButton(text=f"{state_icon} {cat['name']}", callback_data="noop"),
                InlineKeyboardButton(text="تغییر وضعیت", callback_data=f"adm_cat_toggle:{cat['id']}"),
                InlineKeyboardButton(text="🗑حذف", callback_data=f"adm_cat_del:{cat['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ افزودن دسته‌بندی جدید", callback_data="adm_cat_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_custom_gateways_kb(gateways) -> InlineKeyboardMarkup:
    """لیست درگاه‌های پرداخت سفارشی (تعریف‌شده از مینی‌اپ/پنل وب) با امکان فقط
    فعال/غیرفعال کردن و تنظیم حداقل مبلغ از داخل بات. ساخت/ویرایش/حذف همچنان
    مخصوص مینی‌اپ و پنل وب است."""
    rows = []
    for gw in gateways:
        state_icon = "🟢" if gw["enabled"] else "🔴"
        min_amt = int(gw["min_amount"] or 0) if "min_amount" in gw.keys() else 0
        rows.append(
            [InlineKeyboardButton(text=f"{state_icon} {gw['name']} (حداقل: {min_amt:,} ت)", callback_data="noop")]
        )
        rows.append(
            [
                InlineKeyboardButton(text="تغییر وضعیت", callback_data=f"adm_customgw_toggle:{gw['id']}"),
                InlineKeyboardButton(text="🧮 حداقل مبلغ", callback_data=f"adm_customgw_minamt:{gw['id']}"),
            ]
        )
    if not gateways:
        rows.append([InlineKeyboardButton(text="هیچ درگاه سفارشی‌ای تعریف نشده", callback_data="noop")])
    rows.append([InlineKeyboardButton(text="ℹ️ ساخت/ویرایش کامل درگاه فقط از مینی‌اپ ممکن است", callback_data="noop")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_products_categories_kb(categories, prefix="adm_prod_cat") -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        rows.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"{prefix}:{cat['id']}")])
    rows.append([InlineKeyboardButton(text="➕ افزودن محصول جدید", callback_data="adm_prod_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_products_list_kb(db, products) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        stock = db.count_available_configs(p["id"])
        state_icon = "🟢" if p["is_active"] else "🔴"
        dur = p["duration_days"]
        dur_label = "نامحدود" if (p["provision_server_id"] and dur == 0) else f"{dur if dur is not None else 30} روز"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{state_icon} {p['name']} | {p['price']:,}ت | موجودی: {stock} | مدت: {dur_label}",
                    callback_data="noop",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="تغییر وضعیت", callback_data=f"adm_prod_toggle:{p['id']}"),
                InlineKeyboardButton(text="🗑حذف", callback_data=f"adm_prod_del:{p['id']}"),
            ]
        )
        rows.append(
            [InlineKeyboardButton(text="💳 روش‌های پرداخت مجاز", callback_data=f"adm_prod_paymethods:{p['id']}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_new_product_payment_methods_kb(db, selected) -> InlineKeyboardMarkup:
    """صفحه‌ی چندانتخابی روش‌های پرداخت مجاز حین «ساخت» محصول جدید (قبل از این‌که
    محصول در دیتابیس ساخته شود). selected=None یعنی «همه مجاز» (پیش‌فرض)."""
    catalog = db.get_payment_methods_catalog()
    all_keys = {item["key"] for item in catalog}
    all_selected = selected is None or not selected or set(selected) >= all_keys

    rows = [[InlineKeyboardButton(
        text=f"{'✅' if all_selected else '⬜️'} همه‌ی روش‌ها فعال باشند",
        callback_data="newprodpm_all",
    )]]
    for item in catalog:
        checked = all_selected or (item["key"] in (selected or []))
        icon = "✅" if checked else "⬜️"
        suffix = "" if item["enabled"] else " (غیرفعال)"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {item['label']}{suffix}",
            callback_data=f"newprodpm_tgl:{item['key']}",
        )])
    rows.append([InlineKeyboardButton(text="✅ تایید و ساخت محصول", callback_data="newprodpm_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_product_payment_methods_kb(db, product_id: int) -> InlineKeyboardMarkup:
    """صفحه‌ی چندانتخابی روش‌های پرداخت مجاز برای یک محصول. لیست کامل روش‌ها
    (داخلی + هر درگاه سفارشی) پویا از db.get_payment_methods_catalog خوانده
    می‌شود، پس با اضافه‌شدن یک درگاه سفارشی جدید، خودش اینجا هم اضافه می‌شود.
    None/[] یعنی «همه مجاز» (پیش‌فرض)."""
    allowed = db.get_product_payment_methods(product_id)
    all_allowed = allowed is None
    catalog = db.get_payment_methods_catalog()
    product = db.get_product(product_id)
    back_cb = f"adm_prod_cat:{product['category_id']}" if product else "adm_products"

    rows = [[InlineKeyboardButton(
        text=f"{'✅' if all_allowed else '⬜️'} همه‌ی روش‌ها فعال باشند",
        callback_data=f"adm_prodpm_all:{product_id}",
    )]]
    for item in catalog:
        checked = all_allowed or (item["key"] in (allowed or []))
        icon = "✅" if checked else "⬜️"
        suffix = "" if item["enabled"] else " (غیرفعال)"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {item['label']}{suffix}",
            callback_data=f"adm_prodpm_tgl:{product_id}:{item['key']}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pick_category_kb(categories, prefix) -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        rows.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"{prefix}:{cat['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_new_product_source_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📦 بانک کانفیگ (لینک‌های آماده)", callback_data="adm_newprod_src:bank")],
        [InlineKeyboardButton(text="🔌 اتصال مستقیم به پنل", callback_data="adm_newprod_src:direct")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pick_provision_server_kb(servers) -> InlineKeyboardMarkup:
    rows = []
    for s in servers:
        rows.append([InlineKeyboardButton(text=f"🖥 {s['name']}", callback_data=f"adm_newprod_srv:{s['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_newprod_duration_mode_kb(limited_days: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"⏳ محدود ({limited_days} روز)", callback_data="adm_newprod_durmode:limited")],
        [InlineKeyboardButton(text="♾ نامحدود", callback_data="adm_newprod_durmode:unlimited")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pick_product_kb(products, prefix) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        rows.append([InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"{prefix}:{p['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_test_menu_kb(db, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    enabled = db.get_setting("test_enabled", "1") == "1"
    toggle_text = "🔴 غیرفعال کردن کانفیگ تست" if enabled else "🟢 فعال کردن کانفیگ تست"

    rows = [[InlineKeyboardButton(text=toggle_text, callback_data="adm_test_toggle")]]

    plans = db.get_test_config_plans()
    for p in plans:
        icon = "🟢" if p["is_active"] else "🔴"
        rows.append([InlineKeyboardButton(
            text=f"{icon} 🧪 {p['name']}", callback_data=f"adm_tp_view:{p['id']}",
        )])
    if db.is_full_access_bot(is_main_bot) or not plans:
        rows.append([InlineKeyboardButton(text="➕ افزودن پلن کانفیگ تست جدید", callback_data="adm_tp_add")])

    if db.is_full_access_bot(is_main_bot):
        remaining = db.count_available_test_configs()
        rows.append([InlineKeyboardButton(
            text=f"🗄 بانک لینک دستی (قدیمی) - موجودی: {remaining}", callback_data="adm_test_add",
        )])

    rows.append([InlineKeyboardButton(text="🔁 بازنشانی کانفیگ تست برای همه", callback_data="adm_reset_test_configs")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_plan_view_kb(db, plan) -> InlineKeyboardMarkup:
    pid = plan["id"]
    server = db.get_panel_server(plan["panel_server_id"])
    toggle_text = "🔴 غیرفعال‌سازی" if plan["is_active"] else "🟢 فعال‌سازی"
    vol_text = f"{plan['volume_mb']} مگابایت" if plan["volume_mb"] < 1024 else f"{plan['volume_mb'] / 1024:g} گیگ"
    dur_text = f"{plan['duration_hours']} ساعت" if plan["duration_hours"] < 24 else f"{plan['duration_hours'] / 24:g} روز"
    rows = [
        [InlineKeyboardButton(text=f"✏️ نام: {plan['name']}", callback_data=f"adm_tp_edit_name:{pid}")],
        [InlineKeyboardButton(text=f"✏️ پیشوند نام کاربری: {plan['name_prefix']}", callback_data=f"adm_tp_edit_prefix:{pid}")],
        [InlineKeyboardButton(
            text=f"🖥 پنل: {server['name'] if server else '—'}", callback_data=f"adm_tp_edit_panel:{pid}",
        )],
        [InlineKeyboardButton(text=f"📶 حجم: {vol_text}", callback_data=f"adm_tp_edit_volume:{pid}")],
        [InlineKeyboardButton(text=f"⏳ مدت: {dur_text}", callback_data=f"adm_tp_edit_duration:{pid}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_tp_toggle:{pid}")],
        [InlineKeyboardButton(text="🗑 حذف پلن", callback_data=f"adm_tp_delete:{pid}")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_test_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_plan_delete_confirm_kb(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ بله، این پلن حذف شود", callback_data=f"adm_tp_delete_force:{plan_id}")],
        [InlineKeyboardButton(text="⬅️ انصراف", callback_data=f"adm_tp_view:{plan_id}")],
    ])


def test_plan_panel_select_kb(db, plan_id) -> InlineKeyboardMarkup:
    servers = db.get_panel_servers(active_only=True)
    suffix = plan_id if plan_id is not None else "new"
    rows = [
        [InlineKeyboardButton(
            text=f"{s['name']} ({PANEL_TYPE_LABELS.get(s['panel_type'], s['panel_type'])})",
            callback_data=f"adm_tp_set_panel:{suffix}:{s['id']}",
        )]
        for s in servers
    ]
    rows.append([InlineKeyboardButton(text="➕ افزودن سرور جدید", callback_data="adm_panel_server_add")])
    back_cb = f"adm_tp_view:{plan_id}" if plan_id is not None else "adm_test_menu"
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_forcejoin_menu_kb(db) -> InlineKeyboardMarkup:
    settings = db.get_force_join_settings()
    toggle_text = "🔴 غیرفعال کردن عضویت اجباری" if settings["enabled"] else "🟢 فعال کردن عضویت اجباری"
    channel_text = f"کانال فعلی: {settings['channel']}" if settings["channel"] else "کانالی ثبت نشده است"
    rows = [
        [InlineKeyboardButton(text=channel_text, callback_data="noop")],
        [InlineKeyboardButton(text="✏️ تنظیم / تغییر کانال", callback_data="adm_forcejoin_set_channel")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_forcejoin_toggle")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


BUTTON_LABELS = {
    "btn_buy": "دکمه خرید کانفیگ",
    "btn_test": "دکمه کانفیگ تست",
    "btn_contact": "دکمه ارتباط با پشتیبانی",
    "btn_my_orders": "دکمه حساب کاربری",
    "btn_referral": "دکمه زیرمجموعه‌گیری",
    "btn_wallet": "دکمه کیف پول",
    "btn_wheel": "دکمه گردونه شانس",
    "btn_admin_panel": "دکمه پنل مدیریت",
    "btn_reseller_panel": "دکمه پنل نمایندگی",
    "btn_reseller_request": "دکمه درخواست نمایندگی سطح ۲",
}


def admin_edit_buttons_kb(db) -> InlineKeyboardMarkup:
    """این صفحه قبلاً همه‌چیز (متن/رنگ/فعال‌بودن) را در یک ردیف فشرده کنار هم
    می‌چید که با برچسب‌های فارسیِ بلند، متن‌ها روی هم می‌افتاد و معلوم نبود
    کدام دکمه‌ی رنگ/فعال مال کدام آیتم است. الان هر دکمه یک بلوکِ جدا دارد:
    یک ردیفِ عنوانِ تمام‌عرض (فقط نمایشی) و زیرش ردیفِ عملیات همان دکمه، با
    یک خط جداکننده بین بلوک‌ها."""
    style_icon = {"primary": "🔵", "success": "🟢", "danger": "🔴", "": "⚪️"}
    rows = []
    for i, (key, label) in enumerate(BUTTON_LABELS.items()):
        if i > 0:
            rows.append([InlineKeyboardButton(text="➖➖➖➖➖➖➖➖➖➖", callback_data="noop")])
        current_style = db.get_setting(f"{key}_style", "")
        icon = style_icon.get(current_style, "⚪️")
        toggle_key = MENU_BUTTON_META.get(key, {}).get("toggle_key")
        status_suffix = ""
        if toggle_key:
            enabled = db.get_setting(toggle_key, "1") == "1"
            status_suffix = " (فعال)" if enabled else " (غیرفعال)"
        rows.append([InlineKeyboardButton(text=f"{icon} {label}{status_suffix}", callback_data="noop")])
        action_row = [
            InlineKeyboardButton(text="✏️ ویرایش متن", callback_data=f"adm_btn_edit:{key}"),
            InlineKeyboardButton(text="🎨 تغییر رنگ", callback_data=f"adm_btn_color_menu:{key}"),
        ]
        if toggle_key:
            enabled = db.get_setting(toggle_key, "1") == "1"
            action_row.append(InlineKeyboardButton(
                text="🔴 غیرفعال‌سازی" if enabled else "🟢 فعال‌سازی",
                callback_data=f"adm_btn_toggle:{key}",
            ))
        rows.append(action_row)

    rows.append([InlineKeyboardButton(text="➖➖➖➖➖➖➖➖➖➖", callback_data="noop")])
    miniapp_enabled = db.get_setting("miniapp_enabled", "1") == "1"
    rows.append([InlineKeyboardButton(
        text=f"✨ دکمه مینی‌اپ فروشگاه{' (فعال)' if miniapp_enabled else ' (غیرفعال)'}", callback_data="noop",
    )])
    rows.append([InlineKeyboardButton(
        text="🔴 غیرفعال‌سازی" if miniapp_enabled else "🟢 فعال‌سازی",
        callback_data="adm_btn_toggle:miniapp",
    )])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:appearance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_settings_kb(db) -> InlineKeyboardMarkup:
    """تنظیمات نمایش منوی اصلی: فعال/غیرفعال کردن جداگانه‌ی منوی پایین (Reply)
    و منوی شیشه‌ای بالا (Inline)، و تعداد ستون هر دو منو (۱ یا ۲ دکمه در هر ردیف)."""
    reply_on = db.get_setting("main_menu_reply_enabled", "1") == "1"
    inline_on = db.get_setting("main_menu_inline_enabled", "0") == "1"
    columns = _menu_columns(db)

    reply_toggle = "🔴 غیرفعال کردن منوی پایین" if reply_on else "🟢 فعال کردن منوی پایین"
    inline_toggle = "🔴 غیرفعال کردن منوی شیشه‌ای بالا" if inline_on else "🟢 فعال کردن منوی شیشه‌ای بالا"
    col_toggle = "↔️ چیدمان: ۲ دکمه در هر ردیف" if columns == 1 else "↕️ چیدمان: ۱ دکمه در هر ردیف"

    rows = [
        [InlineKeyboardButton(text=f"منوی پایین (Reply): {'🟢 فعال' if reply_on else '🔴 غیرفعال'}", callback_data="noop")],
        [InlineKeyboardButton(text=reply_toggle, callback_data="adm_mm_toggle_reply")],
        [InlineKeyboardButton(text=f"منوی شیشه‌ای بالا (Inline): {'🟢 فعال' if inline_on else '🔴 غیرفعال'}", callback_data="noop")],
        [InlineKeyboardButton(text=inline_toggle, callback_data="adm_mm_toggle_inline")],
        [InlineKeyboardButton(text=f"چیدمان فعلی: {columns} دکمه در هر ردیف", callback_data="noop")],
        [InlineKeyboardButton(text=col_toggle, callback_data="adm_mm_toggle_columns")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:appearance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_color_picker_kb(key: str, back_callback: str = "adm_edit_buttons") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔵 آبی (Primary)", callback_data=f"adm_btn_color_set:{key}:primary")],
        [InlineKeyboardButton(text="🟢 سبز (Success)", callback_data=f"adm_btn_color_set:{key}:success")],
        [InlineKeyboardButton(text="🔴 قرمز (Danger)", callback_data=f"adm_btn_color_set:{key}:danger")],
        [InlineKeyboardButton(text="⚪️ پیش‌فرض (خاکستری)", callback_data=f"adm_btn_color_set:{key}:none")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data=back_callback)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_admins_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📃 لیست ادمین‌ها و نقش‌ها", callback_data="adm_admins_list")],
        [InlineKeyboardButton(text="➕ افزودن ادمین", callback_data="adm_admin_add")],
        [InlineKeyboardButton(text="🔄 تغییر نقش ادمین", callback_data="adm_admin_role_change")],
        [InlineKeyboardButton(text="➖ حذف ادمین", callback_data="adm_admin_remove")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:management")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


ADMIN_ROLE_LABELS = {"owner": "👑 مالک", "admin": "🛡 مدیر کامل", "mid": "🥈 ادمین میانی", "support": "🎧 پشتیبان"}


def admin_role_pick_kb(target_tg_id: int, action: str) -> InlineKeyboardMarkup:
    """action: 'add' یا 'setrole' - پیشوند callback_data برای تمایز دو مسیر."""
    prefix = "adm_add_admin_role" if action == "add" else "adm_change_role_set"
    rows = [
        [InlineKeyboardButton(text="🛡 مدیر کامل (دسترسی کامل)", callback_data=f"{prefix}:{target_tg_id}:admin")],
        [InlineKeyboardButton(text="🥈 ادمین میانی (بدون آمار/فروش/نمایندگی)", callback_data=f"{prefix}:{target_tg_id}:mid")],
        [InlineKeyboardButton(text="🎧 پشتیبان (فقط تیکت و سفارش)", callback_data=f"{prefix}:{target_tg_id}:support")],
        [InlineKeyboardButton(text="⬅️ انصراف", callback_data="adm_admins_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pending_orders_kb(orders) -> InlineKeyboardMarkup:
    rows = []
    for o in orders:
        rows.append(
            [InlineKeyboardButton(text=f"سفارش #{o['id']} - کاربر {o['user_id']}", callback_data=f"view_order:{o['id']}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)




def crypto_invoices_kb(invoices) -> InlineKeyboardMarkup:
    rows = []
    status_text = {
        "new": "🟡 جدید",
        "pending": "🟠 در انتظار تایید شبکه",
        "completed": "🟢 تکمیل‌شده",
        "expired": "🔴 منقضی‌شده",
        "cancelled": "⚪️ لغوشده",
        "error": "🔴 خطا",
        "mismatch": "🟣 مغایرت",
    }
    kind_text = {"order": "سفارش", "wallet_topup": "شارژ کیف پول"}
    for inv in invoices:
        st = status_text.get(inv["status"], inv["status"] or "---")
        kind = kind_text.get(inv["kind"], inv["kind"])
        row = [
            InlineKeyboardButton(
                text=f"{st} | {kind} #{inv['ref_id']} | {inv['amount_toman']:,} تومان",
                callback_data=f"view_crypto_invoice:{inv['id']}",
            )
        ]
        if inv["status"] in ("new", "pending"):
            row.append(InlineKeyboardButton(text="❌ لغو", callback_data=f"cancel_crypto_invoice:{inv['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="adm_crypto_payments")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def abangateway_invoices_kb(invoices) -> InlineKeyboardMarkup:
    rows = []
    status_text = {
        "new": "🟡 جدید",
        "pending": "🟠 در انتظار پرداخت",
        "completed": "🟢 تکمیل‌شده",
        "expired": "🔴 منقضی‌شده",
        "cancelled": "⚪️ لغوشده",
        "error": "🔴 خطا",
    }
    kind_text = {"order": "سفارش", "wallet_topup": "شارژ کیف پول"}
    for inv in invoices:
        st = status_text.get(inv["status"], inv["status"] or "---")
        kind = kind_text.get(inv["kind"], inv["kind"])
        row = [
            InlineKeyboardButton(
                text=f"{st} | {kind} #{inv['ref_id']} | {inv['amount_toman']:,} تومان",
                callback_data=f"view_abangateway_invoice:{inv['id']}",
            )
        ]
        if inv["status"] in ("new", "pending"):
            row.append(InlineKeyboardButton(text="🔄 بررسی", callback_data=f"check_abangateway_invoice:{inv['id']}"))
            row.append(InlineKeyboardButton(text="❌ لغو", callback_data=f"cancel_abangateway_invoice:{inv['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="adm_abangateway_payments")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pending_topups_kb(topups) -> InlineKeyboardMarkup:
    rows = []
    for t in topups:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"شارژ #{t['id']} - کاربر {t['user_id']} - {t['amount']:,} تومان",
                    callback_data=f"view_topup:{t['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# مدیریت کدهای تخفیف
# ---------------------------------------------------------------------------

def discount_codes_kb(codes) -> InlineKeyboardMarkup:
    rows = []
    for c in codes:
        state_icon = "🟢" if c["is_active"] else "🔴"
        if c["percent"]:
            value_txt = f"{c['percent']}%"
        else:
            value_txt = f"{c['fixed_amount']:,}ت"
        usage_txt = f"{c['used_count']}/{c['max_uses'] if c['max_uses'] else '∞'}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{state_icon} {c['code']} | {value_txt} | استفاده: {usage_txt}", callback_data="noop"
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="تغییر وضعیت", callback_data=f"adm_disc_toggle:{c['id']}"),
                InlineKeyboardButton(text="🗑حذف", callback_data=f"adm_disc_del:{c['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ ساخت کد تخفیف جدید", callback_data="adm_disc_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# تنظیمات زیرمجموعه‌گیری
# ---------------------------------------------------------------------------

def referral_settings_kb(db) -> InlineKeyboardMarkup:
    # --- حالت ۱: پورسانت درصدی از اولین خرید هر زیرمجموعه ---
    enabled = db.get_setting("referral_enabled", "1") == "1"
    toggle_text = "🔴 غیرفعال کردن پورسانت خرید" if enabled else "🟢 فعال کردن پورسانت خرید"
    percent = db.get_setting("referral_percent", "10")
    commission_max = int(db.get_setting("referral_commission_max_count", "0") or 0)
    commission_max_text = f"{commission_max} نفر" if commission_max > 0 else "نامحدود"

    # --- حالت ۲: محصول رایگان با رسیدن به تعداد دعوت مشخص ---
    fc_enabled = db.get_setting("referral_free_config_enabled", "0") == "1"
    fc_toggle_text = "🔴 غیرفعال کردن کانفیگ رایگان" if fc_enabled else "🟢 فعال کردن کانفیگ رایگان"
    fc_threshold = db.get_setting("referral_free_config_threshold", "10")
    fc_product_id = db.get_setting("referral_free_config_product_id", "") or ""
    fc_product_name = "تنظیم نشده"
    if fc_product_id:
        p = db.get_product(int(fc_product_id))
        fc_product_name = p["name"] if p else "محصول حذف‌شده - دوباره انتخاب کنید"

    # --- حالت ۳: شارژ ثابت کیف پول به‌ازای هر دعوت ---
    ib_enabled = db.get_setting("referral_invite_bonus_enabled", "0") == "1"
    ib_toggle_text = "🔴 غیرفعال کردن شارژ به‌ازای دعوت" if ib_enabled else "🟢 فعال کردن شارژ به‌ازای دعوت"
    ib_amount = db.get_setting("referral_invite_bonus_amount", "0")
    ib_max = int(db.get_setting("referral_invite_bonus_max_count", "0") or 0)
    ib_max_text = f"{ib_max} نفر" if ib_max > 0 else "نامحدود"

    rows = [
        [InlineKeyboardButton(text="① پورسانت درصدی از خرید زیرمجموعه", callback_data="noop")],
        [InlineKeyboardButton(text=f"درصد پورسانت: {percent}% | سقف: {commission_max_text}", callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_referral_toggle")],
        [InlineKeyboardButton(text="✏️ تغییر درصد پورسانت", callback_data="adm_referral_percent_edit")],
        [InlineKeyboardButton(text="✏️ تغییر سقف تعداد نفرات (۰=نامحدود)", callback_data="adm_referral_commission_max_edit")],

        [InlineKeyboardButton(text="② کانفیگ رایگان با تعداد دعوت مشخص", callback_data="noop")],
        [InlineKeyboardButton(text=f"آستانه: {fc_threshold} نفر | محصول: {fc_product_name}", callback_data="noop")],
        [InlineKeyboardButton(text=fc_toggle_text, callback_data="adm_referral_freeconfig_toggle")],
        [InlineKeyboardButton(text="✏️ تغییر تعداد دعوت لازم", callback_data="adm_referral_freeconfig_threshold_edit")],
        [InlineKeyboardButton(text="📦 انتخاب محصول جایزه", callback_data="adm_referral_freeconfig_product")],

        [InlineKeyboardButton(text="③ شارژ ثابت کیف پول به‌ازای هر دعوت", callback_data="noop")],
        [InlineKeyboardButton(text=f"مبلغ: {ib_amount} تومان | سقف: {ib_max_text}", callback_data="noop")],
        [InlineKeyboardButton(text=ib_toggle_text, callback_data="adm_referral_invitebonus_toggle")],
        [InlineKeyboardButton(text="✏️ تغییر مبلغ شارژ", callback_data="adm_referral_invitebonus_amount_edit")],
        [InlineKeyboardButton(text="✏️ تغییر سقف تعداد نفرات (۰=نامحدود)", callback_data="adm_referral_invitebonus_max_edit")],

        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:resellers")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_freeconfig_product_kb(db) -> InlineKeyboardMarkup:
    products = db.get_all_products()
    rows = []
    for p in products:
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} ({p['category_name']})", callback_data=f"adm_referral_freeconfig_setprod:{p['id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_referral_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# گردونه شانس
# ---------------------------------------------------------------------------

def wheel_settings_kb(db) -> InlineKeyboardMarkup:
    s = db.get_wheel_settings()
    toggle_text = "🔴 غیرفعال کردن گردونه" if s["enabled"] else "🟢 فعال کردن گردونه"
    prizes_txt = "، ".join(f"{p}%" for p in s["prizes"]) or "---"
    rows = [
        [InlineKeyboardButton(text=f"احتمال برد: {s['win_percent']}%", callback_data="noop")],
        [InlineKeyboardButton(text=f"جوایز ممکن: {prizes_txt}", callback_data="noop")],
        [InlineKeyboardButton(text=f"اعتبار کد جایزه: {s['expiry_hours']} ساعت", callback_data="noop")],
        [InlineKeyboardButton(text=f"فاصله بین دو چرخش: {s['cooldown_hours']} ساعت", callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_wheel_toggle")],
        [InlineKeyboardButton(text="✏️ تغییر درصد برد", callback_data="adm_wheel_edit_percent")],
        [InlineKeyboardButton(text="✏️ تغییر لیست جوایز", callback_data="adm_wheel_edit_prizes")],
        [InlineKeyboardButton(text="✏️ تغییر اعتبار کد", callback_data="adm_wheel_edit_expiry")],
        [InlineKeyboardButton(text="✏️ تغییر فاصله چرخش", callback_data="adm_wheel_edit_cooldown")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def renewal_settings_kb(db) -> InlineKeyboardMarkup:
    s = db.get_renewal_settings()
    toggle_text = "🔴 غیرفعال کردن یادآوری" if s["enabled"] else "🟢 فعال کردن یادآوری"
    rows = [
        [InlineKeyboardButton(text=f"وضعیت: {'🟢 فعال' if s['enabled'] else '🔴 غیرفعال'}", callback_data="noop")],
        [InlineKeyboardButton(text=f"📅 چند روز قبل از اتمام سرویس: {s['days_before']} روز", callback_data="noop")],
        [InlineKeyboardButton(text=f"🎟 درصد تخفیف کد تشویقی: {s['discount_percent']}٪", callback_data="noop")],
        [InlineKeyboardButton(text=f"⏳ اعتبار کد تشویقی: {s['discount_expiry_hours']} ساعت", callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_renewal_toggle")],
        [InlineKeyboardButton(text="✏️ تغییر تعداد روز یادآوری", callback_data="adm_renewal_edit_days")],
        [InlineKeyboardButton(text="✏️ تغییر درصد تخفیف", callback_data="adm_renewal_edit_percent")],
        [InlineKeyboardButton(text="✏️ تغییر اعتبار کد (ساعت)", callback_data="adm_renewal_edit_hours")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def volume_reminder_settings_kb(db) -> InlineKeyboardMarkup:
    s = db.get_volume_reminder_settings()
    toggle_text = "🔴 غیرفعال کردن یادآوری" if s["enabled"] else "🟢 فعال کردن یادآوری"
    mode_text = "📊 مبنا: درصد مصرف" if s["mode"] == "percent" else "📦 مبنا: حجم باقی‌مانده (گیگ)"
    rows = [
        [InlineKeyboardButton(text=f"وضعیت: {'🟢 فعال' if s['enabled'] else '🔴 غیرفعال'}", callback_data="noop")],
        [InlineKeyboardButton(text=mode_text, callback_data="adm_volume_toggle_mode")],
    ]
    if s["mode"] == "percent":
        rows.append([InlineKeyboardButton(
            text=f"📊 آستانه: وقتی {s['percent']}٪ مصرف شد", callback_data="noop")])
        rows.append([InlineKeyboardButton(
            text="✏️ تغییر درصد آستانه", callback_data="adm_volume_edit_percent")])
    else:
        rows.append([InlineKeyboardButton(
            text=f"📦 آستانه: وقتی {s['gb_left']} گیگ باقی ماند", callback_data="noop")])
        rows.append([InlineKeyboardButton(
            text="✏️ تغییر آستانه (گیگ)", callback_data="adm_volume_edit_gb")])
    rows += [
        [InlineKeyboardButton(text=f"🎟 درصد تخفیف کد تشویقی: {s['discount_percent']}٪", callback_data="noop")],
        [InlineKeyboardButton(text=f"⏳ اعتبار کد تشویقی: {s['discount_expiry_hours']} ساعت", callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_volume_toggle")],
        [InlineKeyboardButton(text="✏️ تغییر درصد تخفیف", callback_data="adm_volume_edit_discount_percent")],
        [InlineKeyboardButton(text="✏️ تغییر اعتبار کد (ساعت)", callback_data="adm_volume_edit_discount_hours")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_alert_settings_kb(db) -> InlineKeyboardMarkup:
    threshold = db.get_setting("low_stock_threshold", "3")
    rows = [
        [InlineKeyboardButton(text=f"📦 آستانه‌ی فعلی: {threshold} کانفیگ باقی‌مانده", callback_data="noop")],
        [InlineKeyboardButton(text="✏️ تغییر آستانه", callback_data="adm_stock_alert_edit")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# روش‌های داخلی که حداقل‌مبلغ‌شان از صفحه‌ی «حداقل مبلغ پرداخت‌ها» قابل تنظیم
# است. کیف پول جدا از بقیه است چون در واقع «حداقل مبلغ شارژ کیف پول» است، نه
# حداقل مبلغ یک درگاه.
MIN_AMOUNT_SETTINGS_ITEMS = [
    ("min_amount_wallet_topup", "👛 حداقل مبلغ شارژ کیف پول"),
    ("min_amount_card", "💳 حداقل مبلغ کارت‌به‌کارت (دستی)"),
    ("min_amount_abangateway", "💳 حداقل مبلغ آبان گیت وی"),
    ("min_amount_crypto", "🪙 حداقل مبلغ پرداخت کریپتو"),
]


def min_amount_settings_kb(db) -> InlineKeyboardMarkup:
    """صفحه‌ی تنظیم حداقل مبلغ برای شارژ کیف پول و هر روش پرداخت داخلی.
    حداقل مبلغ هر درگاه سفارشی از داخل همان درگاه (adm_custom_gateways) تنظیم
    می‌شود، نه از این صفحه."""
    rows = []
    for key, label in MIN_AMOUNT_SETTINGS_ITEMS:
        value = db.get_setting(key, "0")
        rows.append([InlineKeyboardButton(
            text=f"{label}: {int(value or 0):,} تومان",
            callback_data=f"adm_minamt_edit:{key}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# ساخت کانفیگ شخصی (پنل‌های VPN + قیمت‌گذاری)
# ---------------------------------------------------------------------------

def custom_config_menu_kb(db, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    settings = db.get_custom_config_settings()
    status = "🟢 فعال" if settings["enabled"] else "🔴 غیرفعال"
    prefix = db.get_custom_config_prefix()
    prefix_label = f"«{prefix}-»" if prefix else "خاموش (بدون پیش‌وند)"
    rows = [
        [InlineKeyboardButton(text=f"وضعیت: {status} (برای تغییر بزنید)", callback_data="adm_custom_config_toggle")],
        [InlineKeyboardButton(
            text=f"📶 حداقل/حداکثر حجم: {settings['min_gb']} تا {settings['max_gb']} گیگ",
            callback_data="adm_custom_config_edit_range",
        )],
        [InlineKeyboardButton(text=f"🏷 پیش‌وند نام کانفیگ: {prefix_label}", callback_data="adm_custom_config_prefix")],
    ]
    if db.is_full_access_bot(is_main_bot):
        # اتصال پنل VPN فقط توسط بات اصلی یا نمایندگی سطح کامل مدیریت می‌شود؛ نمایندگی سطح ۲
        # از استخر حجمی که ادمین بات اصلی تعیین می‌کند استفاده می‌کند، نه پنل خودش.
        rows.append([InlineKeyboardButton(text="🖥 مدیریت سرورهای پنل", callback_data="adm_panel_servers")])
    rows.append([InlineKeyboardButton(text="💰 مدیریت قیمت‌گذاری بر اساس بازه (تنظیم قدیمی/پیش‌فرض)", callback_data="adm_pricing_tiers")])
    rows.append([InlineKeyboardButton(text="🧩 محصولات کانفیگ‌ساز (چندمحصولی)", callback_data="adm_ccp_list")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# محصولات «ساخت کانفیگ شخصی» (چندمحصولی: هرکدوم پنل/اینباند، بازه‌ی حجم/مدت
# و قیمت‌گذاری خودشو داره)
# ---------------------------------------------------------------------------

def custom_config_products_list_kb(db) -> InlineKeyboardMarkup:
    products = db.get_custom_config_products()
    rows = []
    for p in products:
        icon = "🟢" if p["is_active"] else "🔴"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {p['icon'] or '🛠'} {p['name']}", callback_data=f"adm_ccp_view:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ افزودن محصول جدید", callback_data="adm_ccp_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_custom_config_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_config_product_view_kb(db, product) -> InlineKeyboardMarkup:
    pid = product["id"]
    server = db.get_panel_server(product["panel_server_id"])
    toggle_text = "🔴 غیرفعال‌سازی" if product["is_active"] else "🟢 فعال‌سازی"
    duration_label = (
        f"⏳ مدت: ثابت، {product['duration_days']} روز"
        if product["duration_mode"] == "fixed"
        else f"⏳ مدت: انتخاب کاربر، {product['min_days'] or 1} تا {product['max_days'] or 90} روز"
    )
    pricing_label = (
        f"💰 قیمت: {product['flat_price_per_gb']:,} تومان/گیگ (فلت)"
        if product["pricing_mode"] == "flat" and product["flat_price_per_gb"]
        else "💰 قیمت: پله‌ای (بر اساس بازه‌ی حجم)"
    )
    rows = [
        [InlineKeyboardButton(text=f"✏️ نام: {product['name']}", callback_data=f"adm_ccp_edit_name:{pid}")],
        [InlineKeyboardButton(text=f"✏️ توضیح: {product['description'] or '—'}", callback_data=f"adm_ccp_edit_desc:{pid}")],
        [InlineKeyboardButton(
            text=f"🖥 پنل: {server['name'] if server else '—'}", callback_data=f"adm_ccp_edit_panel:{pid}",
        )],
        [InlineKeyboardButton(
            text=f"📶 حجم: {product['min_gb']} تا {product['max_gb']} گیگ", callback_data=f"adm_ccp_edit_volume:{pid}",
        )],
        [InlineKeyboardButton(text=duration_label, callback_data=f"adm_ccp_duration_mode:{pid}")],
        [InlineKeyboardButton(text=pricing_label, callback_data=f"adm_ccp_pricing_mode:{pid}")],
    ]
    if product["pricing_mode"] == "tiered":
        rows.append([InlineKeyboardButton(text="💰 مدیریت تعرفه‌های پله‌ای این محصول", callback_data=f"adm_ccp_tiers:{pid}")])
    else:
        rows.append([InlineKeyboardButton(text="✏️ تغییر قیمت هر گیگ", callback_data=f"adm_ccp_edit_flat_price:{pid}")])
    rows += [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_ccp_toggle:{pid}")],
        [InlineKeyboardButton(text="🗑 حذف محصول", callback_data=f"adm_ccp_delete:{pid}")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_ccp_list")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_config_product_delete_confirm_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ بله، این محصول حذف شود", callback_data=f"adm_ccp_delete_force:{product_id}")],
        [InlineKeyboardButton(text="⬅️ انصراف", callback_data=f"adm_ccp_view:{product_id}")],
    ])


def custom_config_product_panel_select_kb(db, product_id: int) -> InlineKeyboardMarkup:
    servers = db.get_panel_servers(active_only=True)
    rows = [
        [InlineKeyboardButton(
            text=f"{s['name']} ({PANEL_TYPE_LABELS.get(s['panel_type'], s['panel_type'])})",
            callback_data=f"adm_ccp_set_panel:{product_id}:{s['id']}",
        )]
        for s in servers
    ]
    rows.append([InlineKeyboardButton(text="➕ افزودن سرور جدید", callback_data="adm_panel_server_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"adm_ccp_view:{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_plan_pick_kb(plans) -> InlineKeyboardMarkup:
    """برای کاربر نهایی: وقتی چند پلن کانفیگ تست فعال باشد، انتخاب یکی از آن‌ها."""
    from test_config_provision import format_plan_amount
    rows = [
        [InlineKeyboardButton(
            text=f"🧪 {p['name']} ({format_plan_amount(p)})", callback_data=f"user_test_plan:{p['id']}",
        )]
        for p in plans
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_config_product_duration_mode_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ مدت ثابت (ادمین تعیین می‌کند)", callback_data=f"adm_ccp_set_duration_mode:{product_id}:fixed")],
        [InlineKeyboardButton(text="🧑‍💻 مدت قابل‌انتخاب توسط مشتری", callback_data=f"adm_ccp_set_duration_mode:{product_id}:user_choice")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"adm_ccp_view:{product_id}")],
    ])


def custom_config_product_pricing_mode_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 قیمت فلت (یک نرخ ثابت هر گیگ)", callback_data=f"adm_ccp_set_pricing_mode:{product_id}:flat")],
        [InlineKeyboardButton(text="📊 قیمت پله‌ای (بر اساس بازه‌ی حجم)", callback_data=f"adm_ccp_set_pricing_mode:{product_id}:tiered")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"adm_ccp_view:{product_id}")],
    ])


def custom_config_product_tiers_kb(db, product_id: int) -> InlineKeyboardMarkup:
    tiers = db.get_custom_config_product_tiers(product_id)
    rows = []
    for t in tiers:
        to_label = f"{t['to_gb']}" if t["to_gb"] is not None else "∞"
        rows.append([InlineKeyboardButton(
            text=f"{t['from_gb']} تا {to_label} گیگ ← {t['price_per_gb']:,} تومان/گیگ  🗑",
            callback_data=f"adm_ccp_tier_delete:{product_id}:{t['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ افزودن بازه‌ی قیمت", callback_data=f"adm_ccp_tier_add:{product_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"adm_ccp_view:{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_config_product_select_kb(products) -> InlineKeyboardMarkup:
    """کیبورد انتخاب محصول برای کاربر، وقتی بیش از یک محصول فعال وجود دارد."""
    rows = [
        [InlineKeyboardButton(text=f"{p['icon'] or '🛠'} {p['name']}", callback_data=f"ccf_pick_product:{p['id']}")]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_type_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="PasarGuard", callback_data="adm_panel_type:pasarguard")],
        [InlineKeyboardButton(text="3X-UI", callback_data="adm_panel_type:3xui")],
        [InlineKeyboardButton(text="Marzban", callback_data="adm_panel_type:marzban")],
        [InlineKeyboardButton(text="Marzneshin", callback_data="adm_panel_type:marzneshin")],
        [InlineKeyboardButton(text="Hiddify", callback_data="adm_panel_type:hiddify")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")],
    ])


def inbound_select_kb(inbounds, selected_ids=None) -> InlineKeyboardMarkup:
    """کیبورد چند-انتخابی inbound ها: با هر تپ روی یک ردیف، تیک آن toggle می‌شود
    (بدون بستن پیام) و دکمه‌ی «تایید» در پایین وضعیت انتخاب فعلی را ادامه‌ی فلو
    می‌برد. selected_ids لیست id های تیک‌خورده‌ی فعلی است."""
    selected_ids = selected_ids or []
    rows = []
    for ib in inbounds:
        mark = "✅" if ib["id"] in selected_ids else "◻️"
        label = f"{mark} #{ib['id']} {ib['remark']} ({ib['protocol']}:{ib['port']})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm_xui_inbound_toggle:{ib['id']}")])
    confirm_label = f"✅ تایید ({len(selected_ids)} انتخاب‌شده)" if selected_ids else "✅ تایید انتخاب"
    rows.append([InlineKeyboardButton(text=confirm_label, callback_data="adm_xui_inbound_confirm")])
    rows.append([InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_servers_list_kb(db) -> InlineKeyboardMarkup:
    servers = db.get_panel_servers()
    rows = []
    for s in servers:
        icon = "🟢" if s["is_active"] else "🔴"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {s['name']} ({PANEL_TYPE_LABELS.get(s['panel_type'], s['panel_type'])})", callback_data=f"adm_panel_server_view:{s['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ افزودن سرور جدید", callback_data="adm_panel_server_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_custom_config_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_server_view_kb(server) -> InlineKeyboardMarkup:
    toggle_text = "🔴 غیرفعال‌سازی" if server["is_active"] else "🟢 فعال‌سازی"
    custom_text = "✅ برای خرید شخصی: فعال" if server["used_for_custom_config"] else "◻️ برای خرید شخصی: غیرفعال"
    test_text = "✅ برای کانفیگ تست: فعال" if server["used_for_test_config"] else "◻️ برای کانفیگ تست: غیرفعال"
    reseller_text = "✅ برای نمایندگی: فعال" if server["used_for_reseller"] else "◻️ برای نمایندگی: غیرفعال"
    rows = [
        [InlineKeyboardButton(text="🔌 تست اتصال", callback_data=f"adm_panel_server_test:{server['id']}")],
        [InlineKeyboardButton(text="🧩 تغییر کاربر نمونه (قالب)", callback_data=f"adm_panel_server_template:{server['id']}")],
    ]
    if server["panel_type"] == "3xui":
        rows.append([InlineKeyboardButton(
            text="🔗 تغییر لینک Subscription", callback_data=f"adm_panel_server_suburl:{server['id']}",
        )])
    rows += [
        [InlineKeyboardButton(text=custom_text, callback_data=f"adm_panel_server_usage:custom:{server['id']}")],
        [InlineKeyboardButton(text=test_text, callback_data=f"adm_panel_server_usage:test:{server['id']}")],
        [InlineKeyboardButton(text=reseller_text, callback_data=f"adm_panel_server_usage:reseller:{server['id']}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_panel_server_toggle:{server['id']}")],
        [InlineKeyboardButton(text="🗑 حذف سرور", callback_data=f"adm_panel_server_delete:{server['id']}")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_panel_servers")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_server_delete_confirm_kb(server_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ بله، همه چیز حذف شود", callback_data=f"adm_panel_server_delete_force:{server_id}")],
        [InlineKeyboardButton(text="⬅️ انصراف", callback_data=f"adm_panel_server_view:{server_id}")],
    ])


def pricing_tiers_kb(db) -> InlineKeyboardMarkup:
    tiers = db.get_pricing_tiers()
    rows = []
    for t in tiers:
        to_label = f"{t['to_gb']}" if t["to_gb"] is not None else "∞"
        rows.append([InlineKeyboardButton(
            text=f"{t['from_gb']} تا {to_label} گیگ ← {t['price_per_gb']:,} تومان/گیگ  🗑",
            callback_data=f"adm_pricing_tier_delete:{t['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ افزودن بازه‌ی قیمت", callback_data="adm_pricing_tier_add")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_custom_config_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# کیف پول
# ---------------------------------------------------------------------------

def wallet_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="➕ شارژ کیف پول", callback_data="start_topup")]]
    )


def topup_review_kb(topup_id) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✅ تایید و شارژ کیف پول", callback_data=f"topup_approve:{topup_id}"),
            InlineKeyboardButton(text="❌ رد کردن", callback_data=f"topup_reject:{topup_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# مدیریت بات‌های نمایندگی (فقط در بات اصلی)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# درخواست خودکار نمایندگی سطح ۲
# ---------------------------------------------------------------------------

def reseller_request_review_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید و تعیین هزینه", callback_data=f"resreq_approve:{request_id}")],
        [InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"resreq_reject:{request_id}")],
    ])


def reseller_request_panel_pick_kb(request_id, panels) -> InlineKeyboardMarkup:
    rows = []
    for p in panels:
        rows.append([InlineKeyboardButton(text=f"🖥 {p['name']}", callback_data=f"resreq_panel:{request_id}:{p['id']}")])
    rows.append([InlineKeyboardButton(text="↩️ خودکار (اولین پنل فعالِ نمایندگی)", callback_data=f"resreq_panel:{request_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_request_pay_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ پرداخت می‌کنم", callback_data=f"resreq_pay:{request_id}")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data=f"resreq_cancel:{request_id}")],
    ])


def reseller_request_payment_review_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید پرداخت", callback_data=f"resreq_payok:{request_id}")],
        [InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"resreq_payreject:{request_id}")],
    ])


def reseller_requests_open_kb(requests) -> InlineKeyboardMarkup:
    """لیست همه‌ی درخواست‌های باز نمایندگی با دکمه‌ی کنسل دستی برای هرکدام."""
    status_label = {
        "pending_review": "🟡 در انتظار بررسی",
        "awaiting_payment": "🟠 منتظر پرداخت",
        "awaiting_payment_review": "🟣 رسید ارسال‌شده",
        "awaiting_bot_info": "🔵 منتظر اطلاعات بات",
    }
    rows = []
    for r in requests:
        label = status_label.get(r["status"], r["status"])
        rows.append([
            InlineKeyboardButton(
                text=f"#{r['id']} | {label} | کاربر {r['user_id']} | {r['volume_gb']:,} گیگ",
                callback_data="noop",
            )
        ])
        rows.append([
            InlineKeyboardButton(text="🛑 کنسل دستی", callback_data=f"resreq_admin_cancel:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="adm_reseller_requests_menu")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def orphan_db_files_kb(filenames) -> InlineKeyboardMarkup:
    """لیست فایل‌های دیتابیس یتیم (بدون رکورد نماینده‌ی مرتبط) با دکمه‌ی حذف."""
    import urllib.parse
    rows = []
    for fname in filenames:
        rows.append([InlineKeyboardButton(text=f"🗃 {fname}", callback_data="noop")])
        rows.append([
            InlineKeyboardButton(
                text="🗑 حذف این فایل",
                callback_data=f"adm_orphan_db_del:{urllib.parse.quote(fname, safe='')}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_resellers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resbot_del_confirm_kb(bot_id) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🗑 فقط حذف (دیتابیس نگه داشته شود)", callback_data=f"adm_resbot_delc:{bot_id}:0")],
        [InlineKeyboardButton(text="🗑💥 حذف + پاک‌کردن دیتابیس", callback_data=f"adm_resbot_delc:{bot_id}:1")],
        [InlineKeyboardButton(text="انصراف", callback_data="adm_resellers_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resellers_kb(resellers) -> InlineKeyboardMarkup:
    rows = []
    for r in resellers:
        state_icon = "🟢" if r["is_active"] else "🔴"
        level = r["reseller_level"] if "reseller_level" in r.keys() else 2
        level_icon = "⭐️کامل" if level == 1 else "۲محدود"
        label = r["bot_username"] or r["bot_token"][:10] + "..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{state_icon} @{label} - {r['owner_name'] or r['owner_telegram_id']} ({level_icon})",
                    callback_data="noop",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="تغییر وضعیت", callback_data=f"adm_resbot_toggle:{r['id']}"),
                InlineKeyboardButton(text="🔁 تغییر سطح", callback_data=f"adm_resbot_level:{r['id']}"),
                InlineKeyboardButton(text="🗑حذف", callback_data=f"adm_resbot_del:{r['id']}"),
            ]
        )
        if level == 1:
            web_panel_enabled = bool(r["web_panel_enabled"]) if "web_panel_enabled" in r.keys() else False
            wp_label = "🌐 پنل وب: فعال (مدیریت)" if web_panel_enabled else "🌐 فعالسازی پنل وب"
            rows.append(
                [InlineKeyboardButton(text=wp_label, callback_data=f"adm_resbot_webpanel:{r['id']}")]
            )
    rows.append([InlineKeyboardButton(text="➕ افزودن بات نمایندگی جدید", callback_data="adm_resbot_add")])
    rows.append([InlineKeyboardButton(text="⚙️ آدرس پنل مدیریت وب", callback_data="adm_set_panel_domain")])
    rows.append([InlineKeyboardButton(text="🧹 پاکسازی داده‌های باقی‌مانده نمایندگی", callback_data="adm_reseller_orphans")])
    rows.append([InlineKeyboardButton(text="🗃 پاکسازی فایل‌های دیتابیس یتیم", callback_data="adm_orphan_db_files")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:resellers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resbot_webpanel_kb(bot_id) -> InlineKeyboardMarkup:
    """منوی مدیریت پنل وب یک نماینده‌ی کامل: بعد از فعال‌سازی نشان داده می‌شود."""
    rows = [
        [InlineKeyboardButton(text="🔗 لینک ورود پنل وب", callback_data=f"adm_resbot_webpanel_loginlink:{bot_id}")],
        [InlineKeyboardButton(text="🔁 ساخت لینک راه‌اندازی جدید", callback_data=f"adm_resbot_webpanel_regen:{bot_id}")],
        [InlineKeyboardButton(text="⛔️ غیرفعال‌سازی پنل وب", callback_data=f"adm_resbot_webpanel_off:{bot_id}")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_resellers_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_orphans_kb(rows_data) -> InlineKeyboardMarkup:
    rows = []
    for r in rows_data:
        name = r["first_name"] or r["username"] or str(r["telegram_id"])
        rows.append([InlineKeyboardButton(text=f"👤 {name} ({r['telegram_id']})", callback_data="noop")])
        rows.append([
            InlineKeyboardButton(
                text="🧹 پاکسازی کامل این کاربر",
                callback_data=f"adm_reseller_orphan_purge:{r['telegram_id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_resellers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_resellers_menu_kb(resellers) -> InlineKeyboardMarkup:
    rows = []
    for r in resellers:
        label = f"👤 {r['telegram_id']} - {r['reseller_credit_gb']:,} گیگ"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm_cres_view:{r['telegram_id']}")])
    rows.append([InlineKeyboardButton(text="➕ افزودن/جستجوی نماینده", callback_data="adm_cres_find")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_cat:resellers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_reseller_view_kb(user_tg_id: int, is_reseller: bool) -> InlineKeyboardMarkup:
    toggle_text = "⛔️ لغو نمایندگی" if is_reseller else "✅ تبدیل به نماینده"
    rows = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_cres_toggle:{user_tg_id}")],
        [InlineKeyboardButton(text="➕/➖ تغییر اعتبار (گیگ)", callback_data=f"adm_cres_credit:{user_tg_id}")],
        [InlineKeyboardButton(text="🔗 تعیین پنل اختصاصی", callback_data=f"adm_cres_panel:{user_tg_id}")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm_credit_resellers_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_reseller_panel_pick_kb(user_tg_id: int, panels) -> InlineKeyboardMarkup:
    rows = []
    for p in panels:
        rows.append([InlineKeyboardButton(text=f"🖥 {p['name']}", callback_data=f"adm_cres_panel_set:{user_tg_id}:{p['id']}")])
    rows.append([InlineKeyboardButton(text="↩️ خودکار (اولین پنل فعالِ نمایندگی)", callback_data=f"adm_cres_panel_set:{user_tg_id}:0")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"adm_cres_view:{user_tg_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
