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

import extra_gateway_registry
import tutorial_hub
from config import MINIAPP_URL
from panel_providers import PANEL_TYPE_LABELS, INBOUND_SELECT_PANEL_TYPES
from database import MENU_BUTTON_META, ACCOUNT_TOGGLE_KEYS
from i18n import tr


# ---------------------------------------------------------------------------
# منوی اصلی (Reply Keyboard)
# ---------------------------------------------------------------------------

def _styled_button(text: str, style_value: str) -> KeyboardButton:
    """می‌سازد یک دکمه با رنگ دلخواه (ویژگی style در Bot API 9.4 به بعد).
    مقدار خالی یعنی رنگ پیش‌فرض (خاکستری)."""
    style = style_value if style_value in ("primary", "success", "danger") else None
    return KeyboardButton(text=text, style=style)


def _miniapp_url(db, language: str = "") -> str:
    """آدرس مینی‌اپ مخصوص همین بات (اصلی یا نمایندگی) را می‌سازد.
    برای بات‌های نمایندگی، شناسه‌ی تننت به‌صورت پارامتر ?b= اضافه می‌شود تا
    سرور مینی‌اپ (چندمستأجر) بداند دیتابیس و توکن کدام بات را استفاده کند."""
    if not MINIAPP_URL:
        return ""
    tenant_id = db.get_setting("miniapp_tenant_id", "")
    url = MINIAPP_URL
    if tenant_id:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}b={tenant_id}"
    if language:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}lang={language}"
    return url


MINIAPP_BTN_TEXT = "✨ مینی‌اپ فروشگاه"
LANGUAGE_BTN_TEXT = "🌐 زبان / Language"

def language_kb(db=None, back_callback: str = "") -> InlineKeyboardMarkup:
    if db is not None and hasattr(db, "list_languages"):
        languages = [dict(r) for r in db.list_languages(enabled_only=True)]
        rows = []
        row = []
        for item in languages:
            text = f"{item.get('flag', '')} {item.get('native_name') or item.get('name') or item.get('code')}".strip()
            row.append(InlineKeyboardButton(text=text, callback_data=f"language:{item['code']}"))
            if len(row) == 2:
                rows.append(row); row = []
        if row:
            rows.append(row)
    else:
        rows = [[InlineKeyboardButton(text=tr("🇮🇷 فارسی"), callback_data="language:fa"),
                 InlineKeyboardButton(text="🇬🇧 English", callback_data="language:en")]]
    if back_callback:
        rows.append([InlineKeyboardButton(text=tr("⬅️ حساب کاربری"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def miniapp_inline_kb(miniapp_url: str) -> InlineKeyboardMarkup:
    """دکمه‌ی واقعی وب‌اپ به‌صورت inline (نه reply keyboard)، چون طبق تجربه‌ی عملی،
    initData وقتی از دکمه‌ی reply keyboard با web_app مستقیم باز شود، در برخی
    کلاینت‌های تلگرام همیشه خالی برمی‌گردد. راه اصلی و مطمئن، Menu Button
    (در bot_manager._sync_menu_button) است؛ این دکمه صرفاً یک مسیر جایگزین است."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(MINIAPP_BTN_TEXT), web_app=WebAppInfo(url=miniapp_url))]
    ])


def _menu_items(db, is_admin: bool, is_reseller: bool, is_main_bot: bool, show_reseller_request: bool,
                 show_commission_reseller_request: bool = False):
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

    def item_tutorial():
        if settings.get("tutorial_menu_enabled", "1") != "1":
            return None
        if tutorial_hub.GENERAL not in db.get_tutorial_bound_targets():
            return None
        return (settings.get("btn_tutorial", "📚 آموزش"), settings.get("btn_tutorial_style", ""))

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

    tiers_menu_on = settings.get("reseller_tiers_menu_enabled", "1") == "1"

    def item_reseller_tiers():
        if not tiers_menu_on or not (show_reseller_request or show_commission_reseller_request):
            return None
        return (settings.get("btn_reseller_tiers", "🤝 نمایندگی"), settings.get("btn_reseller_tiers_style", "primary"))

    def item_reseller_request():
        if tiers_menu_on or not show_reseller_request:
            return None
        if settings.get("reseller_request_enabled", "1") != "1":
            return None
        return (settings.get("btn_reseller_request", "🏪 درخواست نمایندگی سطح ۲"), settings.get("btn_reseller_request_style", "primary"))

    def item_commission_reseller_request():
        if tiers_menu_on or not show_commission_reseller_request:
            return None
        if settings.get("commission_reseller_request_enabled", "1") != "1":
            return None
        return (
            settings.get("btn_commission_reseller_request", "💼 درخواست نمایندگی کمیسیونی"),
            settings.get("btn_commission_reseller_request_style", "primary"),
        )

    builders = {
        "miniapp": item_miniapp,
        "btn_buy": item_buy,
        "btn_test": item_test,
        "btn_my_orders": item_my_orders,
        "btn_tutorial": item_tutorial,
        "btn_referral": item_referral,
        "btn_wheel": item_wheel,
        "btn_contact": item_contact,
        "btn_admin_panel": item_admin_panel,
        "btn_reseller_panel": item_reseller_panel,
        "btn_reseller_tiers": item_reseller_tiers,
        "btn_reseller_request": item_reseller_request,
        "btn_commission_reseller_request": item_commission_reseller_request,
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
                  show_reseller_request: bool = False, show_commission_reseller_request: bool = False):
    """منوی پایین (Reply Keyboard). اگر از تنظیمات غیرفعال شده باشد،
    ReplyKeyboardRemove برمی‌گردد تا کیبورد قبلی از پایین صفحه‌ی کاربر جمع شود."""
    if db.get_setting("main_menu_reply_enabled", "1") != "1":
        return ReplyKeyboardRemove()

    items = _menu_items(db, is_admin, is_reseller, is_main_bot, show_reseller_request, show_commission_reseller_request)
    item_rows = _menu_item_rows(db, items)
    rows = [[_styled_button(tr(text), style) for _key, text, style in row] for row in item_rows]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def main_menu_inline_kb(db, is_admin: bool, is_reseller: bool = False, is_main_bot: bool = True,
                         show_reseller_request: bool = False,
                         show_commission_reseller_request: bool = False) -> InlineKeyboardMarkup:
    """منوی شیشه‌ای بالا (Inline Keyboard) - همان آیتم‌های منوی پایین، به شکل inline.
    روی کلیک هر دکمه، callback_data به‌صورت 'mm:<key>' ارسال می‌شود که در
    handlers_user.py / handlers_admin.py به همان هندلر متنی متناظرش وصل شده."""
    items = _menu_items(db, is_admin, is_reseller, is_main_bot, show_reseller_request, show_commission_reseller_request)
    item_rows = _menu_item_rows(db, items)
    miniapp_url = _miniapp_url(db, getattr(db, "_current_menu_language", ""))

    def _build_button(key, text, style):
        if key == "miniapp" and miniapp_url:
            return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=miniapp_url))
        s = style if style in ("primary", "success", "danger") else None
        return InlineKeyboardButton(text=text, callback_data=f"mm:{key}", style=s)

    rows = [[_build_button(key, tr(text), style) for key, text, style in row] for row in item_rows]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _show_commission_reseller_request(db, user_tg_id: int, is_main_bot: bool) -> bool:
    return (
        is_main_bot
        and not db.is_inline_reseller(user_tg_id)
        and not db.get_pending_commission_reseller_request_for_user(user_tg_id)
    )


def menu_for_user(db, user_tg_id: int, is_main_bot: bool = True):
    try:
        from i18n import normalize_language
        db._current_menu_language = normalize_language(db.get_user_language(user_tg_id))
    except Exception:
        db._current_menu_language = ""
    show_reseller_request = (
        is_main_bot
        and not db.is_reseller(user_tg_id)
        and not db.get_open_reseller_request(user_tg_id)
    )
    show_commission_reseller_request = _show_commission_reseller_request(db, user_tg_id, is_main_bot)
    return main_menu_kb(db, db.is_admin(user_tg_id), db.is_reseller(user_tg_id), is_main_bot,
                         show_reseller_request, show_commission_reseller_request)


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
    show_commission_reseller_request = _show_commission_reseller_request(db, user_tg_id, is_main_bot)
    return main_menu_inline_kb(db, db.is_admin(user_tg_id), db.is_reseller(user_tg_id), is_main_bot,
                                show_reseller_request, show_commission_reseller_request)


def tier_request_review_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ تایید"), callback_data=f"tierreq_ok:{request_id}", style="success")],
        [InlineKeyboardButton(text=tr("❌ رد"), callback_data=f"tierreq_no:{request_id}", style="danger")],
    ])


def reseller_tier_switch_confirm_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ بله، ادامه"), callback_data=f"rt:goc:{code}", style="danger")],
        [InlineKeyboardButton(text=tr("🔙 انصراف"), callback_data="rt:menu")],
    ])


def reseller_tiers_kb(tiers) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{t['icon']} {t['title']}", callback_data=f"rt:pick:{t['code']}")]
        for t in tiers
    ]
    rows.append([InlineKeyboardButton(text=tr("❌ بستن"), callback_data="rt:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_tier_detail_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ شروع درخواست"), callback_data=f"rt:go:{code}", style="success")],
        [InlineKeyboardButton(text=tr("🔙 بازگشت به سطح‌ها"), callback_data="rt:menu")],
    ])


# ---------------------------------------------------------------------------
# دسته‌بندی‌ها / محصولات (کاربر)
# ---------------------------------------------------------------------------

def categories_kb(db, categories, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    rows = []
    custom_enabled = db.get_setting("custom_config_enabled", "0") == "1" or db.count_active_custom_config_products() > 0
    if db.is_full_access_bot(is_main_bot) and custom_enabled:
        text = db.get_setting("btn_custom_config_text", "🛠 ساخت کانفیگ شخصی")
        rows.append([_styled_inline(db, text, "custom_config_start", "btn_custom_config_style")])
    for cat in categories:
        rows.append([_styled_inline(db, f"📁 {cat['name']}", f"cat:{cat['id']}", "btn_cat_select_style")])
    back_text = db.get_setting("btn_buy_back_text", "⬅️ بازگشت")
    rows.append([_styled_inline(db, back_text, "back_main", "btn_buy_back_style")])
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
    back_text = db.get_setting("btn_buy_back_text", "⬅️ بازگشت به دسته‌بندی‌ها")
    rows.append([_styled_inline(db, back_text, "back_categories", "btn_buy_back_style")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# دو دکمه‌ی «ادامه و ارسال رسید» و «وارد کردن کد تخفیف» با هم در یک صفحه
# ظاهر می‌شوند و ترتیبشان از تب «دکمه‌ها»ی پنل وب قابل جابجایی است؛ دکمه‌ی
# بازگشت همیشه ثابت و آخرین ردیف می‌ماند.
_PRODUCT_CONFIRM_BUILDERS = {
    "btn_buy_continue": lambda db, product_id, quantity: _styled_inline(
        db, db.get_setting("btn_buy_continue_text", "✅ ادامه و ارسال رسید"),
        f"buy_start:{product_id}:{quantity}", "btn_buy_continue_style",
    ),
    "btn_enter_code": lambda db, product_id, quantity: _styled_inline(
        db, db.get_setting("btn_enter_code_text", "🎟 وارد کردن کد تخفیف"),
        f"enter_code:{product_id}:{quantity}", "btn_enter_code_style",
    ),
}


def product_confirm_kb(db, product_id, quantity: int = 1, max_qty: int = 1, bulk_step: int = 0, users_change: bool = False) -> InlineKeyboardMarkup:
    max_qty = max(max_qty, 1)
    quantity = max(1, min(quantity, max_qty))

    qty_row = []
    if quantity > 1:
        qty_row.append(InlineKeyboardButton(text="➖", callback_data=f"qty_dec:{product_id}:{quantity}"))
    qty_row.append(InlineKeyboardButton(text=tr(f"🔢 تعداد: {quantity}"), callback_data="noop"))
    if quantity < max_qty:
        qty_row.append(InlineKeyboardButton(text="➕", callback_data=f"qty_inc:{product_id}:{quantity}"))

    order = db.get_custom_order("buyflow_confirm", list(_PRODUCT_CONFIRM_BUILDERS.keys()))
    back_text = db.get_setting("btn_buy_back_text", "⬅️ بازگشت")
    rows = [qty_row]
    if bulk_step > 1:
        bulk_row = []
        if quantity > 1:
            bulk_row.append(InlineKeyboardButton(text=f"➖{bulk_step}", callback_data=f"qty_dec:{product_id}:{quantity}:{bulk_step}"))
        if quantity < max_qty:
            bulk_row.append(InlineKeyboardButton(text=f"➕{bulk_step}", callback_data=f"qty_inc:{product_id}:{quantity}:{bulk_step}"))
        if bulk_row:
            rows.append(bulk_row)
    for key in order:
        rows.append([_PRODUCT_CONFIRM_BUILDERS[key](db, product_id, quantity)])
    if users_change:
        rows.append([InlineKeyboardButton(text=tr("👥 تغییر تعداد کاربر"), callback_data=f"buy_users_pick:{product_id}")])
    rows.append([_styled_inline(db, back_text, "back_categories", "btn_buy_back_style")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_count_picker_kb(product, max_users: int, callback_prefix: str, back_cb: str, current_users: int = 0) -> InlineKeyboardMarkup:
    from user_limit import price_for_users, upgrade_price
    if current_users:
        rows = [
            [InlineKeyboardButton(
                text=tr(f"👥 {n} کاربر (+{n - current_users}) - {upgrade_price(product, current_users, n):,} تومان"),
                callback_data=f"{callback_prefix}:{n}",
            )]
            for n in range(current_users + 1, max_users + 1)
        ]
    else:
        rows = [
            [InlineKeyboardButton(
                text=tr(f"👥 {n} کاربر - {price_for_users(product, n):,} تومان"),
                callback_data=f"{callback_prefix}:{n}",
            )]
            for n in range(1, max_users + 1)
        ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")]]
    )


def share_phone_kb() -> ReplyKeyboardMarkup:
    """کیبورد پایین (Reply) با یک دکمه‌ی «اشتراک‌گذاری شماره موبایل» (request_contact)
    برای درگاه‌های سفارشی که require_customer_phone در تنظیماتشان فعال است؛ چون
    کاربر باید خودش با زدن این دکمه شماره‌ی حساب تلگرامش را تایید/ارسال کند
    (تلگرام امکان تایپ دستی به‌جای این دکمه را جعل نمی‌کند)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=tr("📱 اشتراک‌گذاری شماره موبایل"), request_contact=True)],
            [KeyboardButton(text=tr("❌ انصراف"))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def custom_config_username_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("🎲 نام کاربری خودکار"), callback_data="custom_config_random_username")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")],
    ])


# ---------------------------------------------------------------------------
# سفارش‌های من (منوی کانفیگ‌ها با قابلیت حذف)
# ---------------------------------------------------------------------------

def my_orders_menu_kb(items) -> InlineKeyboardMarkup:
    """لیست سرویس‌های کاربر با نمایش بصری وضعیت فعال/منقضی.

    برای سازگاری با callerهای قدیمی، ``items`` همچنان حداقل به ``cb_id`` و
    ``label`` نیاز دارد؛ اگر اطلاعات وضعیت همراه آیتم باشد از آن برای رنگ‌بندی
    استفاده می‌کنیم. وضعیت فعال با 🟢 و منقضی با 🔴 نمایش داده می‌شود.
    """
    from datetime import datetime

    def _status_icon(item) -> str:
        # اگر caller مستقیماً وضعیت را داده باشد، همان مرجع است.
        status = str(item.get("status", "") or "").strip().lower()
        if status in {"expired", "inactive", "disabled", "deactivated", "ended"}:
            return "🔴"
        if status in {"active", "enabled", "valid"}:
            return "🟢"

        if "is_active" in item:
            return "🟢" if bool(item.get("is_active")) else "🔴"

        # برای سرویس‌هایی که وضعیت‌شان از تاریخ انقضا قابل تشخیص است.
        expires_at = item.get("expires_at") or item.get("config_expires_at")
        if expires_at:
            try:
                exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                now = datetime.now(exp.tzinfo) if exp.tzinfo else datetime.utcnow()
                return "🟢" if exp > now else "🔴"
            except (TypeError, ValueError):
                pass
        return ""

    rows = []
    for it in items:
        icon = _status_icon(it)
        label = str(it["label"])
        if icon and not label.startswith(("🟢", "🔴")):
            label = f"{icon} {label}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"mo_v:{it['cb_id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ حساب کاربری"), callback_data="acct:hub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_order_item_kb(cb_id: str, deletable: bool) -> InlineKeyboardMarkup:
    rows = []
    if deletable:
        rows.append([InlineKeyboardButton(text=tr("🗑 حذف کامل این کانفیگ"), callback_data=f"mo_del:{cb_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست"), callback_data="mo_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_order_error_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست"), callback_data="mo_back")]])


def service_inquiry_kb(cb_id: str) -> InlineKeyboardMarkup:
    """کیبورد صفحه‌ی «استعلام»: فقط یک دکمه‌ی بازگشت به صفحه‌ی جزئیات همان سرویس."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"mo_v:{cb_id}")]])


def service_inquiry_card_kb(cb_id: str, fields: list) -> InlineKeyboardMarkup:
    """کیبورد «کارتی» صفحه‌ی استعلام: هر آیتم از fields یک تاپل (برچسب، مقدار) است
    و به‌صورت یک ردیفِ دو-دکمه‌ای (برچسب راست، مقدار چپ) نمایش داده می‌شود. هر دو
    دکمه غیرفعال‌اند (callback_data='noop') و صرفاً برای نمایش شبکه‌ای اطلاعات
    به‌کار می‌روند (دقیقاً مثل کارت وضعیت سرویس که در پنل‌های مشابه دیده می‌شود)."""
    rows = [
        [
            InlineKeyboardButton(text=str(label), callback_data="noop"),
            InlineKeyboardButton(text=str(value), callback_data="noop"),
        ]
        for label, value in fields
    ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"mo_v:{cb_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_detail_kb(db, cb_id: str, kind: str, deletable: bool, show_links: bool = False,
                       enabled: bool = True, auto_renew: bool = False, is_test: bool = False,
                       can_add_users: bool = False) -> InlineKeyboardMarkup:
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
            rows.append([InlineKeyboardButton(text=tr("🛠 تمدید کامل سرویس"), callback_data=f"svc_renew:full:{cb_id}")])
        row2 = []
        if on("svc_show_renew_volume"):
            row2.append(InlineKeyboardButton(text=tr("🔋 تمدید حجم سرویس"), callback_data=f"svc_renew:volume:{cb_id}"))
        if on("svc_show_renew_time"):
            row2.append(InlineKeyboardButton(text=tr("⏱ تمدید زمان سرویس"), callback_data=f"svc_renew:time:{cb_id}"))
        if row2:
            rows.append(row2)
        if can_add_users:
            rows.append([InlineKeyboardButton(text=tr("👥 افزایش تعداد کاربر"), callback_data=f"svc_users:{cb_id}")])
        row3 = []
        if on("svc_show_cut_access"):
            row3.append(InlineKeyboardButton(text=tr("🚫 قطع دسترسی و لینک جدید"), callback_data=f"svc_cut:{cb_id}"))
        if row3:
            rows.append(row3)
        row5 = []
        if on("svc_show_toggle"):
            toggle_icon = "🔴 غیرفعال کردن کانفیگ" if enabled else "🟢 فعال کردن کانفیگ"
            row5.append(InlineKeyboardButton(text=toggle_icon, callback_data=f"svc_toggle:{cb_id}"))
        if on("svc_show_rename"):
            row5.append(InlineKeyboardButton(text=tr("✏️ تغییر نام کانفیگ"), callback_data=f"svc_rename:{cb_id}"))
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
            row7.append(InlineKeyboardButton(text=tr("👤 انتقال کانفیگ"), callback_data=f"svc_transfer:{cb_id}"))
        if on("svc_show_location_transfer"):
            row7.append(InlineKeyboardButton(text=tr("📍 تغییر لوکیشن"), callback_data=f"svc_location:{cb_id}"))
        if on("svc_show_history"):
            row7.append(InlineKeyboardButton(text=tr("📜 تاریخچه سرویس"), callback_data=f"svc_hist:{cb_id}"))
        row7.append(InlineKeyboardButton(text=tr("⚠️ گزارش اختلال"), callback_data=f"svc_disruption:{cb_id}"))
        if on("svc_show_rating"):
            row7.append(InlineKeyboardButton(text=tr("⭐ امتیاز به سرویس"), callback_data=f"svc_rate:{cb_id}"))
        if row7:
            rows.append(row7)
    if kind == "custom":
        row_inquiry = []
        if on("svc_show_inquiry"):
            row_inquiry.append(InlineKeyboardButton(text=tr("🔍 استعلام"), callback_data=f"svc_inquiry:{cb_id}"))
        if row_inquiry:
            rows.append(row_inquiry)
    if kind in ("custom", "config"):
        row4 = []
        if on("svc_show_update_config"):
            row4.append(InlineKeyboardButton(text=tr("♻️ بروزرسانی کانفیگ"), callback_data=f"mo_refresh:{cb_id}"))
        if on("svc_show_qr"):
            row4.append(InlineKeyboardButton(text=tr("⬜ کیوآر کانفیگ"), callback_data=f"svc_qr:{cb_id}"))
        if row4:
            rows.append(row4)
        if show_links:
            rows.append([InlineKeyboardButton(text=tr("📋 کانفیگ‌های تکی"), callback_data=f"mo_links:{cb_id}")])
    if deletable and on("svc_show_delete"):
        rows.append([InlineKeyboardButton(text=tr("🗑 حذف کامل این سرویس"), callback_data=f"mo_del:{cb_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست"), callback_data="mo_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# حساب کاربری (جایگزین دکمه‌ی «سفارش‌های من»؛ سفارش‌ها/زیرمجموعه‌گیری/کیف‌پول
# حالا همه یک ورودی واحد دارند)
# ---------------------------------------------------------------------------

_ACCOUNT_HUB_CALLBACKS = {
    "acct_orders": ("acct_show_orders", "acct:orders"),
    # دکمه‌ی «آموزش» داخل حساب کاربری از همان callback_data هندلر
    # svc_tutorial (handlers_user.py) استفاده می‌کند و منوی آموزش‌های کلی
    # را نشان می‌دهد - چون آن هندلر عمومی است و به سرویس خاصی وابسته نیست.
    "acct_tutorial": ("acct_show_tutorial", "svc_tutorial"),
    "acct_referral": ("acct_show_referral", "acct:referral"),
    "acct_wallet": ("acct_show_wallet", "acct:wallet"),
}


def account_hub_kb(db) -> InlineKeyboardMarkup:
    from database import ACCOUNT_HUB_META, DEFAULT_ACCOUNT_HUB_ORDER
    rows = []
    order = db.get_custom_order("account_hub", DEFAULT_ACCOUNT_HUB_ORDER)
    for key in order:
        toggle_key, callback_data = _ACCOUNT_HUB_CALLBACKS[key]
        if db.get_setting(toggle_key, "1") != "1":
            continue
        if key == "acct_tutorial" and tutorial_hub.GENERAL not in db.get_tutorial_bound_targets():
            continue
        text = tr(db.get_setting(f"{key}_text", ACCOUNT_HUB_META[key]["default_text"]))
        rows.append([_styled_inline(db, text, callback_data, f"{key}_style")])
    rows.append([InlineKeyboardButton(text=tr(LANGUAGE_BTN_TEXT), callback_data="acct:language")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به منوی اصلی"), callback_data="acct:main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def renewal_plans_kb(products, mode: str, cb_id: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=(f"{p['name']} - {p['auto_provision_volume_gb']} {tr('گیگ')} / {p['duration_days']} {tr('روز')} - {p['price']:,} {tr('تومان')}"),
            callback_data=f"svc_renew_pick:{mode}:{cb_id}:{p['id']}",
        )]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"mo_v:{cb_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# قابلیت ۵۱: صفحه‌ی تایید نهایی «تمدید کامل سرویس» - قبل از رفتن به انتخاب
# روش پرداخت، دکمه‌ی «وارد کردن کد تخفیف» را نشان می‌دهد (دقیقاً هم‌شکل با
# صفحه‌ی تایید خرید محصول - product_confirm_kb) تا برند/لحن یکسان بماند.
def renewal_full_confirm_kb(db, cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_styled_inline(
            db, db.get_setting("btn_enter_code_text", "🎟 وارد کردن کد تخفیف"),
            f"renew_enter_code:{cb_id}", "btn_enter_code_style",
        )],
        [_styled_inline(
            db, db.get_setting("btn_buy_continue_text", "✅ ادامه و انتخاب پرداخت"),
            f"renew_confirm_pay:{cb_id}", "btn_buy_continue_style",
        )],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"mo_v:{cb_id}")],
    ])


def renewal_pricing_kb(db) -> InlineKeyboardMarkup:
    """نرخ ثابتِ «هر گیگابایت» و «هر روز» برای تمدید فقط-حجم / فقط-زمان سرویس‌ها
    (مستقل از قیمت پلن‌ها که مخصوص تمدید کامل است)."""
    price_per_gb = int(db.get_setting("renewal_price_per_gb", "0") or "0")
    price_per_day = int(db.get_setting("renewal_price_per_day", "0") or "0")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(f"🔋 نرخ هر گیگ: {price_per_gb:,} تومان"), callback_data="adm_renewal_price_gb")],
        [InlineKeyboardButton(text=tr(f"⏱ نرخ هر روز: {price_per_day:,} تومان"), callback_data="adm_renewal_price_day")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")],
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
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:alerts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_order_delete_confirm_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، برای همیشه حذف شود"), callback_data=f"mo_delok:{cb_id}")],
        [InlineKeyboardButton(text=tr("↩️ انصراف"), callback_data=f"mo_v:{cb_id}")],
    ])


def service_cut_confirm_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، دسترسی قطع و لینک جدید صادر شود"), callback_data=f"svc_cutok:{cb_id}")],
        [InlineKeyboardButton(text=tr("↩️ انصراف"), callback_data=f"mo_v:{cb_id}")],
    ])


def service_rename_cancel_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")],
    ])


def service_transfer_confirm_kb(cb_id: str, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، منتقل شود"), callback_data=f"svc_transok:{cb_id}:{target_id}")],
        [InlineKeyboardButton(text=tr("↩️ انصراف"), callback_data=f"mo_v:{cb_id}")],
    ])


def service_location_targets_kb(cb_id: str, targets, policy_by_target=None) -> InlineKeyboardMarkup:
    rows = []
    policy_by_target = policy_by_target or {}
    for server in targets:
        policy = policy_by_target.get(server["id"], {})
        price = int(policy.get("price", server["transfer_price"] or 0))
        label = "رایگان" if price <= 0 else f"{price:,} تومان"
        rows.append([InlineKeyboardButton(
            text=f"📍 {server['name']} — {label}",
            callback_data=f"svc_location_pick:{cb_id}:{server['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"mo_v:{cb_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_location_confirm_kb(cb_id: str, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، انتقال انجام شود"), callback_data=f"svc_location_ok:{cb_id}:{target_id}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت به انتخاب لوکیشن"), callback_data=f"svc_location:{cb_id}")],
    ])


def service_rating_kb(cb_id: str, current: int = None) -> InlineKeyboardMarkup:
    stars_row = []
    for n in range(1, 6):
        text = f"✅{n}" if current == n else f"⭐{n}"
        stars_row.append(InlineKeyboardButton(text=text, callback_data=f"svc_rate_set:{cb_id}:{n}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        stars_row,
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"mo_v:{cb_id}")],
    ])


def service_history_back_kb(cb_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"mo_v:{cb_id}")],
    ])


def my_orders_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست"), callback_data="mo_back")]]
    )


def reseller_panel_kb(fixed_products=None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tr("➕ ساخت کانفیگ جدید"), callback_data="reseller_new_config")]]
    for p in (fixed_products or []):
        qty = int(p.get("qty_remaining", 0))
        rows.append([InlineKeyboardButton(text=(f"📦 {p.get('name','')} | {tr('موجودی')}: {qty}"), callback_data=f"reseller_fixed:{int(p['product_id'])}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_choice_kb(crypto_enabled: bool, abangateway_enabled: bool = False,
                       custom_gateways: list = None, card_to_card_enabled: bool = True,
                       amount: int = None, db=None, allowed_methods=None,
                       card_auto_enabled: bool = False, noapay_enabled: bool = False,
                       blupal_enabled: bool = False, extra_gateways: list = None) -> InlineKeyboardMarkup:
    """کیبورد مرحله‌ی انتخاب روش پرداخت: کاربر ابتدا این لیست را می‌بیند و روش پرداخت را
    انتخاب می‌کند (به‌جای اینکه مستقیم شماره کارت نمایش داده شود). اگر درگاه کریپتو/آبان
    گیت وی/درگاه‌های سفارشی/کارت‌به‌کارت خودکار فعال باشند، دکمه‌ی مربوطه هم نمایش داده
    می‌شود. کارت‌به‌کارت دستی هم با تنظیم card_to_card_enabled قابل غیرفعال‌سازی است.
    custom_gateways لیستی از دیکشنری‌های {"id", "key", "name"} است (خروجی
    custom_gateway_payment.list_enabled_gateways).

    amount + db: در صورت ارسال، دکمه‌ی هر روشی که «حداقل مبلغ» تنظیم‌شده‌اش از amount
    بیشتر باشد حذف می‌شود. allowed_methods: در صورت ارسال (لیست کلیدها یا None برای
    «همه مجاز»)، فقط دکمه‌ی روش‌های مجاز برای محصول/آیتم جاری نمایش داده می‌شود."""

    from database import PAYMENT_METHOD_META, DEFAULT_PAYMENT_METHOD_ORDER

    def _ok(method_key: str) -> bool:
        if allowed_methods is not None and method_key not in allowed_methods:
            return False
        if db is not None and amount is not None:
            min_amt = db.get_payment_method_min_amount(method_key)
            if min_amt and amount < min_amt:
                return False
        return True

    # هر روش استاتیک به شرط فعال بودنش (پارامترهای ورودی) در دسترس است؛
    # درگاه‌های سفارشی هم با کلید "customgw:<id>" وارد همان لیست ترتیب می‌شوند
    # تا ادمین بتواند جای همه‌ی روش‌های پرداخت را با هم، از تب «دکمه‌ها»ی پنل
    # وب، جابه‌جا کند.
    static_enabled = {
        "card": card_to_card_enabled, "card_auto": card_auto_enabled,
        "abangateway": abangateway_enabled, "blupal": blupal_enabled,
        "noapay": noapay_enabled, "crypto": crypto_enabled,
    }
    for _extra_key in (extra_gateways or []):
        static_enabled[_extra_key] = True
    gw_by_key = {f"customgw:{gw['id']}": gw for gw in (custom_gateways or [])}
    valid_keys = list(DEFAULT_PAYMENT_METHOD_ORDER) + list(gw_by_key.keys())
    order = db.get_custom_order("payment_methods", valid_keys) if db is not None else valid_keys

    def _btn(db, text, callback_data, style_key):
        return _styled_inline(db, text, callback_data, style_key) if db is not None else InlineKeyboardButton(text=text, callback_data=callback_data)

    rows = []
    static_cb = {"card": "pay_card2card", "card_auto": "pay_card_auto", "abangateway": "pay_abangateway",
                 "blupal": "pay_blupal", "noapay": "pay_noapay", "crypto": "pay_crypto"}
    for _extra_key in extra_gateway_registry.GATEWAY_ORDER:
        static_cb[_extra_key] = f"pay_{_extra_key}"
    for key in order:
        if key in PAYMENT_METHOD_META:
            if not static_enabled.get(key) or not _ok(key):
                continue
            default_text = PAYMENT_METHOD_META[key]["default_text"]
            text = db.get_setting(f"paymeth_{key}_text", default_text) if db is not None else default_text
            rows.append([_btn(db, text, static_cb[key], f"paymeth_{key}_style")])
        elif key in gw_by_key:
            gw = gw_by_key[key]
            if not _ok(f"custom:{gw['key']}"):
                continue
            default_text = f"💠 {gw['name']} (تایید آنی)"
            text = db.get_setting(f"paymeth_customgw_{gw['id']}_text", default_text) if db is not None else default_text
            rows.append([_btn(db, text, f"pay_customgw:{gw['id']}", f"paymeth_customgw_{gw['id']}_style")])
    rows.append([InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_payment_choice_kb(db, methods) -> InlineKeyboardMarkup:
    """انتخاب روش پرداخت هزینه نمایندگی؛ methods کلیدهای catalog هستند."""
    catalog = {x["key"]: x for x in db.get_payment_methods_catalog(only_enabled=True)}
    rows = []
    for key in methods:
        item = catalog.get(key)
        if not item:
            continue
        rows.append([InlineKeyboardButton(text=item["label"], callback_data=f"respay:{key}")])
    rows.append([InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="resreq_cancel_payment")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def card_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات پرداخت کارت‌به‌کارت (دستی): نمایش شماره کارت فعلی، وضعیت
    فعال/غیرفعال و دکمه‌های تغییر."""
    card_number = db.get_setting("card_number") or "-"
    card_holder = db.get_setting("card_holder") or "-"
    enabled = db.get_setting("card_to_card_enabled", "1") == "1"
    toggle_text = "🔴 غیرفعال کردن پرداخت کارت‌به‌کارت" if enabled else "🟢 فعال کردن پرداخت کارت‌به‌کارت"
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"💳 شماره کارت: {card_number}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"👤 به نام: {card_holder}"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_card_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر شماره کارت / صاحب حساب"), callback_data="adm_set_card_edit")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
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
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_card_auto_toggle")],
        [InlineKeyboardButton(text=tr(f"⏱ مهلت هر مبلغ: {timeout} دقیقه"), callback_data="adm_card_auto_timeout")],
        [InlineKeyboardButton(text=tr(f"🔢 رقم یکتاساز مبلغ: {digits}"), callback_data="adm_card_auto_digits")],
        [InlineKeyboardButton(text=tr(f"💰 واحد مبلغ پیامک: {unit_label} (تغییر)"), callback_data="adm_card_auto_unit_toggle")],
        [InlineKeyboardButton(text=tr("💳 مدیریت کارت‌ها"), callback_data="adm_card_auto_cards")],
        [InlineKeyboardButton(text=tr("📡 اتصال اپ BankSmsForwarder"), callback_data="adm_card_auto_webhook")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
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
        rows.append([InlineKeyboardButton(text=tr("هنوز کارتی اضافه نشده"), callback_data="noop")])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن کارت جدید"), callback_data="adm_card_auto_card_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_card_auto")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_auto_card_detail_kb(card) -> InlineKeyboardMarkup:
    """عملیات یک کارت مشخص: فعال/غیرفعال، ویرایش، حذف."""
    toggle_text = "🔴 غیرفعال کردن" if card["is_active"] else "🟢 فعال کردن"
    rows = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_card_auto_card_toggle:{card['id']}")],
        [InlineKeyboardButton(text=tr("✏️ ویرایش"), callback_data=f"adm_card_auto_card_edit:{card['id']}")],
        [InlineKeyboardButton(text=tr("🗑 حذف"), callback_data=f"adm_card_auto_card_del:{card['id']}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_card_auto_cards")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# سفارش برای ادمین (تایید/رد)
# ---------------------------------------------------------------------------

def order_review_kb(order_id) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=tr("✅ تایید و ارسال کانفیگ"), callback_data=f"order_approve:{order_id}"),
            InlineKeyboardButton(text=tr("❌ رد کردن"), callback_data=f"order_reject:{order_id}"),
        ],
        [
            InlineKeyboardButton(text=tr("🚫 فیش فیک + بلاک کاربر"), callback_data=f"order_fake_receipt:{order_id}"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contact_reply_kb(user_tg_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=tr("↩️ پاسخ به کاربر"), callback_data=f"reply_user:{user_tg_id}")]]
    )


# ---------------------------------------------------------------------------
# ارتباط با پشتیبانی (پیام مستقیم / تیکت / چت مستقیم با مدیر)
# ---------------------------------------------------------------------------

TICKET_STATUS_LABELS = {"open": "🟢 باز", "answered": "🟡 پاسخ داده‌شده", "closed": "🔴 بسته‌شده"}


SUPPORT_CONTACT_METHODS = [
    ("ai_support_enabled", "🤖 دستیار هوشمند"),
    ("support_direct_enabled", "✉️ پیام مستقیم"),
    ("support_ticket_new_enabled", "🎫 ثبت تیکت جدید"),
    ("support_ticket_mine_enabled", "📂 تیکت‌های من"),
    ("support_admin_chat_enabled", "👤 چت مستقیم با مدیر"),
]


def support_method_enabled(db, key: str) -> bool:
    return db.get_setting(key, "1") == "1"


def contact_menu_kb(db) -> InlineKeyboardMarkup:
    """منوی «ارتباط با پشتیبانی»؛ هر روش را ادمین جداگانه فعال/غیرفعال می‌کند."""
    rows = []
    if support_method_enabled(db, "ai_support_enabled"):
        import ai_support
        if ai_support.is_configured(db):
            rows.append([InlineKeyboardButton(text=tr("🤖 دستیار هوشمند (پاسخ آنی)"), callback_data="contact_ai")])
    if support_method_enabled(db, "support_direct_enabled"):
        rows.append([InlineKeyboardButton(text=tr("✉️ پیام مستقیم به پشتیبانی"), callback_data="contact_direct")])
    if support_method_enabled(db, "support_ticket_new_enabled"):
        rows.append([InlineKeyboardButton(text=tr("🎫 ثبت تیکت جدید"), callback_data="tickets_new")])
    if support_method_enabled(db, "support_ticket_mine_enabled"):
        rows.append([InlineKeyboardButton(text=tr("📂 تیکت‌های من"), callback_data="tickets_mine")])
    support_admin_id = (db.get_setting("support_admin_id") or "").strip()
    if support_method_enabled(db, "support_admin_chat_enabled") and support_admin_id.lstrip("-").isdigit():
        rows.append(
            [InlineKeyboardButton(text=tr("👤 چت مستقیم با مدیر"), url=f"tg://user?id={support_admin_id}")]
        )
    if not rows:
        rows.append([InlineKeyboardButton(text=tr("در حال حاضر هیچ روش ارتباطی فعال نیست."), callback_data="noop")])
    rows.append([InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_faq_admin_kb(db, items) -> InlineKeyboardMarkup:
    """پنل کامل Agent چند-Provider برای ادمین."""
    import ai_support
    ai_enabled = db.get_setting("ai_support_enabled", "1") == "1"
    provider = ai_support.resolve_provider_mode(db)
    rows = [
        [InlineKeyboardButton(text=tr(f"دستیار هوشمند: {'🟢 فعال' if ai_enabled else '🔴 غیرفعال'}"), callback_data="adm_ai_toggle")],
        [InlineKeyboardButton(text=tr(f"🔀 مسیر مدل: {ai_support.PROVIDER_LABELS[provider]}"), callback_data="adm_ai_set_provider")],
        [InlineKeyboardButton(text=tr("🔑 کلید Gemini"), callback_data="adm_ai_set_key")],
        [InlineKeyboardButton(text=tr("🔑 کلید Groq"), callback_data="adm_ai_set_groq_key")],
        [InlineKeyboardButton(text=tr("🔑 کلید OpenRouter"), callback_data="adm_ai_set_openrouter_key")],
        [InlineKeyboardButton(text=tr("🧠 انتخاب مدل"), callback_data="adm_ai_set_model")],
    ]
    for it in items:
        q = it["question"]
        short_q = q if len(q) <= 40 else q[:37] + "..."
        rows.append([InlineKeyboardButton(text=f"❓ {short_q}", callback_data="noop"), InlineKeyboardButton(text="🗑", callback_data=f"adm_ai_faq_del:{it['id']}")])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن سوال جدید"), callback_data="adm_ai_faq_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:access")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def translation_settings_kb(db) -> InlineKeyboardMarkup:
    """پنل مدیریت ترجمه خودکار: وضعیت کلید Gemini و ارائه‌دهنده‌های فعال."""
    import translation_engine as te
    source = te.gemini_key_source(db)
    source_label = {"panel": "🟢 از همین پنل", "env": "🟡 از فایل .env سرور", "none": "🔴 تنظیم نشده"}[source]
    providers = te.provider_status(db)
    providers_label = "، ".join(p["name"] for p in providers) if providers else "هیچ‌کدام"
    rows = [
        [InlineKeyboardButton(text=tr(f"🔑 کلید Gemini: {source_label}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"⚙️ ارائه‌دهنده‌های فعال: {providers_label}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("🌍 مدیریت زبان‌ها"), callback_data="adm_translation_langs")],
        [InlineKeyboardButton(text=tr("🔑 تنظیم/تغییر کلید Gemini"), callback_data="adm_translation_set_key")],
        [InlineKeyboardButton(text=tr("🔗 ساخت کلید رایگان از Google AI Studio"), url="https://aistudio.google.com/apikey")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:access")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def translation_languages_kb(db) -> InlineKeyboardMarkup:
    """لیست همه‌ی زبان‌های قابل‌پشتیبانی با وضعیت فعال/غیرفعال و دکمه‌ی تغییر وضعیت.

    فارسی/انگلیسی همیشه فعال‌اند و دکمه‌ی تغییر وضعیت ندارند."""
    from i18n import LANGUAGE_CATALOG
    known = {r["code"]: r for r in db.list_languages()}
    rows = []
    for code, meta in LANGUAGE_CATALOG.items():
        row = known.get(code)
        enabled = bool(row["enabled"]) if row else (code in {"fa", "en"})
        label = f"{meta['flag']} {meta['native_name']}"
        if code in {"fa", "en"}:
            rows.append([
                InlineKeyboardButton(text=label, callback_data="noop"),
                InlineKeyboardButton(text="🟢 همیشه فعال", callback_data="noop"),
            ])
        else:
            status = "🟢 فعال" if enabled else "⚪️ غیرفعال"
            rows.append([
                InlineKeyboardButton(text=label, callback_data="noop"),
                InlineKeyboardButton(text=status, callback_data=f"adm_translation_lang_toggle:{code}"),
            ])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_translation_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tutorial_devices_admin_kb(devices) -> InlineKeyboardMarkup:
    """لیست آموزش‌ها برای ادمین: هرکدام دکمه‌ی مدیریت (عنوان/مراحل/محل نمایش) +
    فعال/غیرفعال + حذف."""
    rows = []
    for d in devices:
        state_icon = "🟢" if d["is_active"] else "⚪️"
        rows.append([
            InlineKeyboardButton(text=f"{d['emoji']} {d['name']}", callback_data=f"adm_tut_steps:{d['id']}"),
            InlineKeyboardButton(text=state_icon, callback_data=f"adm_tut_dev_toggle:{d['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_tut_dev_del:{d['id']}"),
        ])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن آموزش جدید"), callback_data="adm_tut_dev_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:appearance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tutorial_device_steps_admin_kb(device_id: int, steps) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=tr("✏️ تغییر عنوان"), callback_data=f"adm_tut_rename:{device_id}"),
            InlineKeyboardButton(text=tr("🔗 محل نمایش"), callback_data=f"adm_tut_bind:{device_id}"),
        ],
    ]
    for i, s in enumerate(steps, start=1):
        kind = "🎬" if s["video_file_id"] else ("🖼" if s["photo_file_id"] else "📝")
        rows.append([
            InlineKeyboardButton(text=tr(f"{kind} مرحله {i}"), callback_data="noop"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_tut_step_del:{s['id']}:{device_id}"),
        ])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن مرحله جدید"), callback_data=f"adm_tut_step_add:{device_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست آموزش‌ها"), callback_data="adm_tutorial_devices")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tutorial_bind_main_kb(tutorial_id: int, selected: set) -> InlineKeyboardMarkup:
    """صفحه‌ی اصلی «محل نمایش آموزش»: دو مقصد ویژه + گروه‌های دکمه‌ها/بخش‌ها."""
    rows = []
    for key, label in tutorial_hub.SPECIAL_TARGETS:
        mark = "✅" if key in selected else "⬜️"
        idx = tutorial_hub.FLAT_KEYS.index(key)
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"adm_tut_tg:{tutorial_id}:{idx}:m")])
    for g_idx, (_gk, title, items) in enumerate(tutorial_hub.GROUPS):
        chosen = sum(1 for t in items if t["key"] in selected)
        rows.append([InlineKeyboardButton(
            text=f"{title} ({chosen}/{len(items)})", callback_data=f"adm_tut_bg:{tutorial_id}:{g_idx}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به آموزش"), callback_data=f"adm_tut_steps:{tutorial_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tutorial_bind_group_kb(tutorial_id: int, group_idx: int, selected: set) -> InlineKeyboardMarkup:
    """لیست دکمه‌ها/بخش‌های یک گروه با تیک انتخاب برای اتصال آموزش."""
    rows = []
    for t in tutorial_hub.GROUPS[group_idx][2]:
        mark = "✅" if t["key"] in selected else "⬜️"
        idx = tutorial_hub.FLAT_KEYS.index(t["key"])
        rows.append([InlineKeyboardButton(
            text=f"{mark} {t['label']}", callback_data=f"adm_tut_tg:{tutorial_id}:{idx}:{group_idx}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به گروه‌ها"), callback_data=f"adm_tut_bind:{tutorial_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tutorial_devices_user_kb(devices) -> InlineKeyboardMarkup:
    """کیبورد انتخاب آموزش برای کاربر (هر دکمه یک آموزش با عنوان خودش)."""
    rows = [[InlineKeyboardButton(text=f"{d['emoji']} {d['name']}", callback_data=f"tut_pick:{d['id']}")] for d in devices]
    return InlineKeyboardMarkup(inline_keyboard=rows)





def ai_provider_choice_kb(db) -> InlineKeyboardMarkup:
    import ai_support
    current = ai_support.resolve_provider_mode(db)
    rows = []
    for provider, label in ai_support.PROVIDER_LABELS.items():
        mark = "✅ " if provider == current else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"adm_ai_provider_pick:{provider}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_ai_support_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_model_choice_kb(db) -> InlineKeyboardMarkup:
    import ai_support
    current = {
        "gemini": ai_support.resolve_gemini_model(db),
        "groq": ai_support.resolve_groq_model(db),
        "openrouter": ai_support.resolve_openrouter_model(db),
    }
    rows = []
    last_provider = None
    for provider, model_id, label in ai_support.MODEL_CHOICES:
        if provider != last_provider:
            title = {"gemini":"🔷 Gemini", "groq":"🚀 Groq", "openrouter":"🌐 OpenRouter"}[provider]
            rows.append([InlineKeyboardButton(text=title, callback_data="noop")])
            last_provider = provider
        mark = "✅ " if model_id == current[provider] else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"adm_ai_model_pick:{provider}:{model_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_ai_support_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_chat_kb() -> InlineKeyboardMarkup:
    """کیبورد پایین گفتگو با دستیار هوشمند.

    عمداً از ابتدا دکمه‌ی «صحبت با پشتیبانی انسانی» را نشان نمی‌دهیم: دستیار
    باید اول تلاش کند خودش جواب بدهد و فقط وقتی واقعاً نتوانست (یا موضوع
    مالی/شکایت بود یا کاربر صریحاً خواست) خودش ارجاع را با ابزار
    escalate_to_human انجام می‌دهد (نگاه کن به ai_support.py و
    handlers_user.cb_ai_escalate/ai_chat_receive)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr("❌ پایان گفتگو"), callback_data="ai_end")],
        ]
    )


def ticket_departments_kb(departments) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🧩 {d['name']}", callback_data=f"ticket_dept:{d['id']}")] for d in departments]
    rows.append([InlineKeyboardButton(text=tr("❌ لغو"), callback_data="ticket_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_departments_kb(departments) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🧩 {d['name']}", callback_data=f"adm_ticket_dept:{d['id']}")] for d in departments]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:access")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_department_admins_kb(department, admins, assigned_ids) -> InlineKeyboardMarkup:
    rows = []
    for a in admins:
        aid = a['telegram_id']
        mark = "✅" if aid in assigned_ids else "⬜"
        rows.append([InlineKeyboardButton(text=f"{mark} {a.get('role','admin')} — {aid}", callback_data=f"adm_ticket_dept_admin:{department['id']}:{aid}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ دپارتمان‌ها"), callback_data="adm_ticket_departments")])
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
        rows.append([InlineKeyboardButton(text=tr("هنوز تیکتی ثبت نکرده‌اید."), callback_data="noop")])
    rows.append([InlineKeyboardButton(text=tr("🎫 ثبت تیکت جدید"), callback_data="tickets_new")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="contact_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ticket_thread_kb(ticket_id: int, is_closed: bool, back_callback: str = "tickets_mine") -> InlineKeyboardMarkup:
    rows = []
    if not is_closed:
        rows.append([InlineKeyboardButton(text=tr("✉️ ارسال پیام در این تیکت"), callback_data=f"ticket_reply:{ticket_id}")])
        rows.append([InlineKeyboardButton(text=tr("🔒 بستن تیکت"), callback_data=f"ticket_close:{ticket_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست تیکت‌ها"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ticket_admin_notify_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("↩️ پاسخ به تیکت"), callback_data=f"adm_ticket_reply:{ticket_id}")],
        [InlineKeyboardButton(text=tr("👁 مشاهده کامل تیکت"), callback_data=f"adm_ticket_view:{ticket_id}")],
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
        rows.append([InlineKeyboardButton(text=tr("موردی یافت نشد."), callback_data="noop")])
    tabs = [("open", "🟢 باز"), ("answered", "🟡 پاسخ‌داده‌شده"), ("closed", "🔴 بسته‌شده"), ("all", "📋 همه")]
    tab_row = [
        InlineKeyboardButton(text=("✅ " if key == active_status else "") + label, callback_data=f"adm_tickets_list:{key}")
        for key, label in tabs
    ]
    rows.append(tab_row[:2])
    rows.append(tab_row[2:])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_view_kb(ticket_id: int, status: str, active_status: str) -> InlineKeyboardMarkup:
    rows = []
    if status != "closed":
        rows.append([InlineKeyboardButton(text=tr("↩️ پاسخ به تیکت"), callback_data=f"adm_ticket_reply:{ticket_id}")])
        rows.append([InlineKeyboardButton(text=tr("🔒 بستن تیکت"), callback_data=f"adm_ticket_close:{ticket_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست"), callback_data=f"adm_tickets_list:{active_status}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_contact_settings_kb(db) -> InlineKeyboardMarkup:
    """فعال/غیرفعال‌کردن روش‌های ارتباط با پشتیبانی + تنظیم آیدی مدیر برای چت مستقیم."""
    current_id = (db.get_setting("support_admin_id") or "").strip() or "-"
    rows = []
    for key, label in SUPPORT_CONTACT_METHODS:
        icon = "🟢" if support_method_enabled(db, key) else "🔴"
        rows.append([InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"adm_support_toggle:{key}")])
    rows += [
        [InlineKeyboardButton(text=tr(f"🆔 آیدی فعلی: {current_id}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تغییر آیدی مدیر"), callback_data="adm_set_support_contact_edit")],
    ]
    if current_id != "-":
        rows.append([InlineKeyboardButton(text=tr("🗑 حذف آیدی مدیر"), callback_data="adm_clear_support_contact")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:access")])
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
    ("adm_cleanup_settings", "🧹 پاکسازی خودکار منقضی‌ها", "adm_cleanup_settings"),
    ("adm_forcejoin_menu", "📢 عضویت اجباری در کانال", "adm_forcejoin_menu"),
    ("adm_service_alert_channel", "📣 کانال اعلان حذف/اتمام کانفیگ", "adm_service_alert_channel"),
    ("adm_pending_orders", "🧾 سفارش‌های در انتظار", "adm_pending_orders"),
    ("adm_order_surveys", "🗳 نظرسنجی سفارش‌ها", "adm_order_surveys"),
    ("adm_tickets_menu", "🎫 تیکت‌های پشتیبانی", "adm_tickets_menu"),
    ("adm_ticket_departments", "🧩 دپارتمان‌های پشتیبانی", "adm_ticket_departments"),
    ("adm_pending_topups", "👛 درخواست‌های شارژ کیف پول", "adm_pending_topups"),
    ("adm_crypto_payments", "🪙 پرداخت‌های کریپتو", "adm_crypto_payments"),
    ("adm_abangateway_payments", "💳 پرداخت‌های آبان گیت وی", "adm_abangateway_payments"),
    ("adm_blupal_payments", "💳 پرداخت‌های بلوپال", "adm_blupal_payments"),
    ("adm_noapay_payments", "⭐ پرداخت‌های NoapayBot", "adm_noapay_payments"),
    ("adm_discounts_menu", "🎟 مدیریت کدهای تخفیف", "adm_discounts_menu"),
    ("adm_wheel_settings", "🎡 مدیریت گردونه شانس", "adm_wheel_settings"),
    ("adm_lottery_settings", "🪙 سکه و قرعه‌کشی شبانه", "adm_lottery_settings"),
    ("adm_cashback_settings", "💸 کش‌بک تمدید و شارژ", "adm_cashback_settings"),
    ("adm_renewal_settings", "🔔 یادآوری تمدید سرویس", "adm_renewal_settings"),
    ("adm_volume_reminder_settings", "📉 یادآوری اتمام حجم", "adm_volume_reminder_settings"),
    ("adm_connect_alert_settings", "🔌 هشدار اتصال/عدم‌اتصال کانفیگ", "adm_connect_alert_settings"),
    ("adm_early_renewal_discount", "🎁 تخفیف تمدید کامل زودهنگام", "adm_early_renewal_discount"),
    ("adm_stock_alert_settings", "📦 آستانه‌ی هشدار موجودی", "adm_stock_alert_settings"),
    ("adm_custom_config_settings", "🛠 ساخت کانفیگ شخصی (پنل‌های VPN)", "adm_custom_config_settings"),
    ("adm_renewal_pricing", "💳 قیمت‌گذاری تمدید حجم/زمان", "adm_renewal_pricing"),
    ("adm_delivery_settings", "📤 تنظیمات ارسال کانفیگ", "adm_delivery_settings"),
    ("adm_referral_settings", "🤝 تنظیمات زیرمجموعه‌گیری", "adm_referral_settings"),
    ("adm_signup_gift_settings", "🎁 هدیه‌ی عضویت", "adm_signup_gift_settings"),
    ("adm_resellers_menu", "🏪 مدیریت بات‌های نمایندگی", "adm_resellers_menu"),
    ("adm_credit_resellers_menu", "💳 نمایندگی حجمی (اعتبار)", "adm_credit_resellers_menu"),
    ("adm_commission_resellers_menu", "💼 نمایندگی کمیسیونی", "adm_commission_resellers_menu"),
    ("adm_reseller_membership", "⏳ هزینه و انقضای نمایندگی", "adm_reseller_membership"),
    ("adm_reseller_requests_menu", "📋 درخواست‌های نمایندگی", "adm_reseller_requests_menu"),
    ("adm_edit_buttons", "✏️ ویرایش متن دکمه‌ها", "adm_edit_buttons"),
    ("adm_account_settings", "🧾 تنظیمات حساب کاربری کاربران", "adm_account_settings"),
    ("adm_main_menu_settings", "🧩 چیدمان/نمایش منوی اصلی", "adm_main_menu_settings"),
    ("adm_set_card", "💳 تنظیم شماره کارت", "adm_set_card"),
    ("adm_card_autodelete", "⏱ حذف خودکار پیام شماره کارت", "adm_card_autodelete"),
    ("adm_set_plisio", "🪙 تنظیم درگاه کریپتو (Plisio)", "adm_set_plisio"),
    ("adm_set_abangateway", "💳 تنظیم درگاه آبان گیت وی", "adm_set_abangateway"),
    ("adm_set_blupal", "💳 تنظیم درگاه بلوپال", "adm_set_blupal"),
    ("adm_set_noapay", "⭐ تنظیم درگاه NoapayBot", "adm_set_noapay"),
    ("adm_card_auto", "📶 کارت‌به‌کارت با تایید خودکار (پیامک بانک)", "adm_card_auto"),
    ("adm_custom_gateways", "💠 درگاه‌های پرداخت سفارشی (فعال/غیرفعال)", "adm_custom_gateways"),
    ("adm_min_amount_settings", "🧮 حداقل مبلغ پرداخت‌ها", "adm_min_amount_settings"),
    ("adm_wallet_paymethods", "👛 روش‌های پرداخت شارژ کیف پول", "adm_wallet_paymethods"),
    ("adm_bulk_wallet_deduct", "➖ کاهش گروهی موجودی کیف پول", "adm_bulk_wallet_deduct"),
    ("adm_bulk_wallet_credit", "➕ افزایش گروهی موجودی و اعلان", "adm_bulk_wallet_credit"),
    ("adm_cc_paymethods", "🛠 روش‌های پرداخت کانفیگ شخصی", "adm_cc_paymethods"),
    ("adm_edit_welcome", "📝 ویرایش پیام خوش‌آمد", "adm_edit_welcome"),
    ("adm_tutorial_devices", "📚 مدیریت آموزش‌ها (عنوان، مراحل، محل نمایش)", "adm_tutorial_devices"),
    ("adm_admins_menu", "👤 مدیریت ادمین‌ها", "adm_admins_menu"),
    ("adm_broadcast", "📢 پیام همگانی", "adm_broadcast"),
    ("adm_deeplink_tools", "🔗 دیپ‌لینک و پست کانال", "adm_deeplink_tools"),
    ("adm_stats", "📊 آمار فروش", "adm_stats"),
    ("adm_user_search", "👥 مدیریت کاربران", "adm_stats_user"),
    ("adm_backup_menu", "🗄 بکاپ و بازیابی", "adm_backup_menu"),
    ("adm_report_group", "📣 گروه گزارش تاپیک‌دار", "adm_report_group"),
    ("adm_bulk_gift", "🎁 هدیه‌ی گروهی", "adm_bulk_gift"),
    ("adm_spam_settings", "🛡 ضداسپم کاربران", "adm_spam_settings"),
    ("adm_gswitch", "🔌 سوئیچ سراسری ربات (خاموش/روشن)", "adm_gswitch"),
    ("adm_temp_message", "⏳ پیام موقت (خودحذف‌شونده)", "adm_temp_message"),
    ("adm_set_support_contact", "📞 روش‌های ارتباط با پشتیبانی", "adm_set_support_contact"),
    ("adm_ai_support_settings", "🤖 دستیار هوشمند (سوالات متداول)", "adm_ai_support_settings"),
    ("adm_translation_settings", "🌐 ترجمه خودکار", "adm_translation_settings"),
]

ADMIN_PANEL_ITEMS += [
    (f"adm_xgw_pay_{_k}", f"{extra_gateway_registry.GATEWAYS[_k]['icon']} پرداخت‌های {extra_gateway_registry.GATEWAYS[_k]['title']}", f"adm_xgw_payments:{_k}")
    for _k in extra_gateway_registry.GATEWAY_ORDER
] + [
    (f"adm_set_xgw_{_k}", f"{extra_gateway_registry.GATEWAYS[_k]['icon']} تنظیم درگاه {extra_gateway_registry.GATEWAYS[_k]['title']}", f"adm_xgw:{_k}")
    for _k in extra_gateway_registry.GATEWAY_ORDER
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
        "adm_order_surveys",
        "adm_tickets_menu",
        "adm_pending_topups",
        "adm_crypto_payments",
        "adm_abangateway_payments",
        "adm_blupal_payments",
        "adm_noapay_payments",
        *[f"adm_xgw_pay_{_k}" for _k in extra_gateway_registry.GATEWAY_ORDER],
        "adm_reseller_requests_menu",
    ]),
    ("products", "📦 محصولات و کانفیگ", [
        "adm_categories",
        "adm_products",
        "adm_add_configs",
        "adm_random_cfg",
        "adm_test_menu",
        "adm_cleanup_settings",
        "adm_service_alert_channel",
        "adm_custom_config_settings",
        "adm_delivery_settings",
        "adm_renewal_pricing",
    ]),
    ("resellers", "🤝 نمایندگی‌ها", [
        "adm_resellers_menu",
        "adm_credit_resellers_menu",
        "adm_commission_resellers_menu",
        "adm_reseller_membership",
    ]),
    ("marketing", "🎯 بازاریابی و رشد", [
        "adm_discounts_menu",
        "adm_wheel_settings",
        "adm_lottery_settings",
        "adm_cashback_settings",
        "adm_bulk_gift",
        "adm_referral_settings",
        "adm_signup_gift_settings",
        "adm_broadcast",
        "adm_deeplink_tools",
        "adm_forcejoin_menu",
        "adm_temp_message",
    ]),
    ("finance", "💰 مالی و پرداخت", [
        "adm_set_card",
        "adm_card_autodelete",
        "adm_set_plisio",
        "adm_set_abangateway",
        "adm_set_blupal",
        "adm_set_noapay",
        *[f"adm_set_xgw_{_k}" for _k in extra_gateway_registry.GATEWAY_ORDER],
        "adm_card_auto",
        "adm_custom_gateways",
        "adm_min_amount_settings",
        "adm_wallet_paymethods",
        "adm_cc_paymethods",
        "adm_bulk_wallet_deduct",
        "adm_bulk_wallet_credit",
    ]),
    ("alerts", "🔔 یادآوری‌ها و هشدارها", [
        "adm_renewal_settings",
        "adm_volume_reminder_settings",
        "adm_connect_alert_settings",
        "adm_early_renewal_discount",
        "adm_stock_alert_settings",
        "adm_account_settings",
    ]),
    ("access", "👤 ادمین و دسترسی", [
        "adm_admins_menu",
        "adm_set_support_contact",
        "adm_ai_support_settings",
        "adm_translation_settings",
    ]),
    ("appearance", "🎨 ظاهر و رنگ‌بندی", [
        "adm_edit_buttons",
        "adm_main_menu_settings",
        "adm_edit_welcome",
        "adm_tutorial_devices",
        "adm_panel_colors_menu",
        "adm_buyflow_colors_menu",
    ]),
    ("management", "📊 گزارش و سیستم", [
        "adm_gswitch",
        "adm_stats",
        "adm_user_search",
        "adm_backup_menu",
        "adm_report_group",
        "adm_spam_settings",
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
    if key.startswith(("adm_set_xgw_", "adm_xgw_pay_")) and not is_main_bot:
        return False
    if key in ("adm_resellers_menu", "adm_credit_resellers_menu", "adm_reseller_requests_menu", "adm_commission_resellers_menu") and not is_main_bot:
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


def _ordered_admin_categories(db):
    """ترتیب دسته‌های پنل مدیریت را بر اساس چیدمان سفارشی (تب «دکمه‌ها» در
    پنل وب) برمی‌گرداند؛ اگر کاستوم‌سازی نشده باشد، ترتیب پیش‌فرض کد حفظ می‌شود."""
    by_key = {c[0]: c for c in ADMIN_PANEL_CATEGORIES}
    order = db.get_custom_order("admin_categories", list(by_key.keys()))
    return [by_key[k] for k in order if k in by_key]


def admin_panel_kb(db, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    """کیبورد سطح اول پنل مدیریت: فقط دسته‌ها نمایش داده می‌شوند، نه هر ۲۶ آیتم."""
    rows = []
    current_row = []
    for cat_key, cat_label, item_keys in _ordered_admin_categories(db):
        visible_items = [k for k in item_keys if _is_item_visible(db, k, is_main_bot)]
        if not visible_items:
            continue
        label = db.get_setting(f"catlbl_{cat_key}", cat_label)
        current_row.append(_styled_inline(db, label, f"adm_cat:{cat_key}", f"catlbl_{cat_key}_style"))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_exit_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_category_kb(db, is_main_bot: bool, cat_key: str) -> InlineKeyboardMarkup:
    """زیرمنوی یک دسته: آیتم‌های همان دسته با چیدمان دو ستونه + بازگشت.
    ترتیب آیتم‌ها و متن هرکدام از تب «دکمه‌ها»ی پنل وب قابل کاستوم‌سازی است."""
    default_item_keys = next((items for key, _, items in ADMIN_PANEL_CATEGORIES if key == cat_key), [])
    item_keys = db.get_custom_order(f"admin_items__{cat_key}", default_item_keys)
    rows = []
    current_row = []
    for key in item_keys:
        if key not in default_item_keys or not _is_item_visible(db, key, is_main_bot):
            continue
        label, callback_data = _admin_item_label_and_cb(key)
        if key in _EXTRA_PANEL_ITEM_LABELS:
            current_row.append(InlineKeyboardButton(text=label, callback_data=callback_data))
        else:
            label = db.get_setting(f"{key}_label", label)
            current_row.append(_styled_inline(db, label, callback_data, f"{key}_style"))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به پنل مدیریت"), callback_data="adm_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_category_label(cat_key: str) -> str:
    for key, label, _ in ADMIN_PANEL_CATEGORIES:
        if key == cat_key:
            return label
    return "🔧 پنل مدیریت"


def admin_backup_menu_kb(show_full_backup: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("📥 دریافت بکاپ فوری"), callback_data="adm_backup_now")],
    ]
    if show_full_backup:
        # فقط برای مالک اصلی روی بات اصلی نمایش داده می‌شود (نه هر بات نمایندگی):
        # این بکاپ، دیتابیس اصلی + دیتابیس تک‌تک نماینده‌ها (سطح ۱ و ۲) را با هم
        # در یک فایل واحد می‌فرستد؛ همان چیزی که برای جابجایی کامل بین دو سرور لازم است.
        rows.append([InlineKeyboardButton(
            text=tr("🗂 دریافت بکاپ کامل (بات اصلی + همه‌ی نماینده‌ها)"),
            callback_data="adm_backup_full",
        )])
    rows.append([InlineKeyboardButton(text=tr("♻️ بازیابی از فایل بکاپ"), callback_data="adm_restore_start")])
    if show_full_backup:
        rows.append([InlineKeyboardButton(
            text=tr("♻️ بازیابی کامل (از فایل zip بکاپ کامل)"),
            callback_data="adm_restore_full_start",
        )])
    rows.append([InlineKeyboardButton(text=tr("🔁 زمان‌بندی و جابجایی بین سرورها"), callback_data="adm_backup_sync_menu")])
    rows.append([InlineKeyboardButton(text=tr("🏭 بازگشت به حالت کارخانه"), callback_data="adm_factory_reset_start")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:management")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_backup_sync_menu_kb(db) -> InlineKeyboardMarkup:
    interval_hours = (db.get_setting("backup_interval_hours", "") or "24").strip() or "24"
    chat2 = (db.get_setting("backup_secondary_chat_id", "") or "").strip()
    sftp_on = (db.get_setting("backup_sftp_enabled", "0") or "0") == "1"
    sftp_host = (db.get_setting("backup_sftp_host", "") or "").strip()
    rows = [
        [InlineKeyboardButton(text=tr(f"⏱ فاصله‌ی بکاپ خودکار: هر {interval_hours} ساعت"), callback_data="adm_backup_interval_menu")],
        [InlineKeyboardButton(
            text=tr(f"📨 چت دوم تلگرام: {'فعال' if chat2 else 'غیرفعال'}"),
            callback_data="adm_backup_chat2_menu",
        )],
        [InlineKeyboardButton(
            text=tr(f"🔐 SFTP سرور دوم: {('فعال - ' + sftp_host) if sftp_on else 'غیرفعال'}"),
            callback_data="adm_backup_sftp_menu",
        )],
        [InlineKeyboardButton(text=tr("🧪 تست ارسال به مقصدهای جانبی"), callback_data="adm_backup_sync_test")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_backup_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_report_group_kb(configured: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tr("✏️ تنظیم یا تغییر گروه"), callback_data="adm_report_set")]]
    if configured:
        rows.append([InlineKeyboardButton(text=tr("🔁 بررسی و ساخت تاپیک‌های ناموجود"), callback_data="adm_report_recheck")])
        rows.append([InlineKeyboardButton(text=tr("🚫 حذف گروه گزارش"), callback_data="adm_report_clear")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:management")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_backup_interval_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=tr("۶ ساعت"), callback_data="adm_backup_interval_set:6"),
            InlineKeyboardButton(text=tr("۱۲ ساعت"), callback_data="adm_backup_interval_set:12"),
        ],
        [
            InlineKeyboardButton(text=tr("۲۴ ساعت"), callback_data="adm_backup_interval_set:24"),
            InlineKeyboardButton(text=tr("۴۸ ساعت"), callback_data="adm_backup_interval_set:48"),
        ],
        [InlineKeyboardButton(text=tr("✏️ عدد دلخواه (ساعت)"), callback_data="adm_backup_interval_custom")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_backup_sync_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_backup_chat2_menu_kb(configured: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tr("✏️ تنظیم / تغییر چت"), callback_data="adm_backup_chat2_set")]]
    if configured:
        rows.append([InlineKeyboardButton(text=tr("🚫 غیرفعال‌سازی"), callback_data="adm_backup_chat2_disable")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_backup_sync_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_backup_sftp_menu_kb(configured: bool, enabled: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tr("✏️ تنظیم / ویرایش اتصال"), callback_data="adm_backup_sftp_start")]]
    if configured and enabled:
        rows.append([InlineKeyboardButton(text=tr("🔌 غیرفعال‌سازی موقت"), callback_data="adm_backup_sftp_disable")])
    if configured:
        rows.append([InlineKeyboardButton(text=tr("🗑 حذف کامل تنظیمات"), callback_data="adm_backup_sftp_clear")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_backup_sync_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_backup_sftp_auth_choice_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("🔑 با پسورد"), callback_data="adm_backup_sftp_auth:password")],
        [InlineKeyboardButton(text=tr("📄 با فایل کلید خصوصی"), callback_data="adm_backup_sftp_auth:key")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_backup_sync_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_factory_reset_confirm_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("⚠️ بله، ادامه بده"), callback_data="adm_factory_reset_step2")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_factory_reset_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_factory_reset_waiting_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_factory_reset_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_restore_confirm_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("✅ بله، جایگزین کن"), callback_data="adm_restore_confirm")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_restore_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_restore_waiting_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_restore_cancel_wait")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_restore_full_confirm_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("✅ بله، همه‌چیز را جایگزین کن"), callback_data="adm_restore_full_confirm")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_restore_full_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_restore_full_waiting_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_restore_full_cancel_wait")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def xui_restore_waiting_kb(server_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data=f"adm_xui_restore_cancel_wait:{server_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def xui_restore_confirm_kb(server_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("✅ بله، دیتابیس پنل جایگزین شود"), callback_data=f"adm_xui_restore_confirm:{server_id}")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data=f"adm_xui_restore_cancel:{server_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_temp_message_target_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("👤 به خودم"), callback_data="adm_tempmsg_target:self")],
        [InlineKeyboardButton(text=tr("🔢 آیدی عددی کاربر"), callback_data="adm_tempmsg_target:custom")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_temp_message_duration_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=tr("۱ ساعت"), callback_data="adm_tempmsg_dur:3600"),
            InlineKeyboardButton(text=tr("۶ ساعت"), callback_data="adm_tempmsg_dur:21600"),
        ],
        [
            InlineKeyboardButton(text=tr("۱ روز"), callback_data="adm_tempmsg_dur:86400"),
            InlineKeyboardButton(text=tr("۳ روز"), callback_data="adm_tempmsg_dur:259200"),
        ],
        [InlineKeyboardButton(text=tr("✏️ مدت دلخواه (دقیقه)"), callback_data="adm_tempmsg_dur:custom")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_temp_message")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_settings_kb(db) -> InlineKeyboardMarkup:
    """تنظیمات فعال/غیرفعال بودن ارسال لینک اشتراک و ارسال کانفیگ‌های تکی استخراج‌شده
    (برای هر سه مسیر تحویل: بانک کانفیگ، محصول متصل به پنل، ساخت کانفیگ شخصی، و کانفیگ تست)."""
    sub_link_on = db.get_setting("deliver_sub_link_enabled", "1") != "0"
    individual_on = db.get_setting("deliver_individual_configs_enabled", "1") != "0"
    post_text_set = bool((db.get_setting("post_delivery_custom_text", "") or "").strip())
    sub_link_text = "✅ ارسال لینک اشتراک: فعال" if sub_link_on else "❌ ارسال لینک اشتراک: غیرفعال"
    individual_text = "✅ ارسال کانفیگ‌های تکی: فعال" if individual_on else "❌ ارسال کانفیگ‌های تکی: غیرفعال"
    post_text_label = "📝 متن دلخواه بعد از ارسال کانفیگ: تنظیم‌شده" if post_text_set else "📝 متن دلخواه بعد از ارسال کانفیگ: تنظیم‌نشده"
    import config_delivery as _cd
    if not _cd.has_qr_background():
        qr_bg_label = "🖼 پس‌زمینه QR: تنظیم‌نشده"
    elif _cd.qr_background_enabled(db):
        qr_bg_label = "🖼 پس‌زمینه QR: فعال"
    else:
        qr_bg_label = "🖼 پس‌زمینه QR: تنظیم‌شده (غیرفعال)"
    rows = [
        [InlineKeyboardButton(text=sub_link_text, callback_data="adm_deliver_sublink_toggle")],
        [InlineKeyboardButton(text=individual_text, callback_data="adm_deliver_individual_toggle")],
        [InlineKeyboardButton(text=post_text_label, callback_data="adm_edit_post_delivery_text")],
        [InlineKeyboardButton(text=qr_bg_label, callback_data="adm_qr_background_menu")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def qr_background_menu_kb(db) -> InlineKeyboardMarkup:
    """منوی مدیریت تصویر پس‌زمینه‌ی کد QR."""
    import config_delivery as _cd
    has_bg = _cd.has_qr_background()
    rows = [
        [InlineKeyboardButton(
            text=tr("🖼 آپلود/تعویض تصویر پس‌زمینه"),
            callback_data="adm_qr_background_upload",
        )],
    ]
    if has_bg:
        enabled = _cd.qr_background_enabled(db)
        toggle_text = "❌ غیرفعال‌کردن پس‌زمینه" if enabled else "✅ فعال‌کردن پس‌زمینه"
        rows.append([InlineKeyboardButton(text=toggle_text, callback_data="adm_qr_background_toggle")])
        rows.append([InlineKeyboardButton(text=tr("👁 پیش‌نمایش"), callback_data="adm_qr_background_preview")])
        rows.append([InlineKeyboardButton(text=tr("🗑 حذف تصویر پس‌زمینه"), callback_data="adm_qr_background_remove")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_delivery_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_target_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("👥 همه‌ی کاربران"), callback_data="adm_broadcast_target:all")],
        [InlineKeyboardButton(text=tr("🖥 کاربران یک سرور خاص"), callback_data="adm_broadcast_target:server")],
        [InlineKeyboardButton(text=tr("🚫 کاربران بدون کانفیگ"), callback_data="adm_broadcast_target:no_config")],
        [InlineKeyboardButton(text=tr("⛔️ کاربران دارای کانفیگ غیرفعال"), callback_data="adm_broadcast_target:inactive_config")],
        [InlineKeyboardButton(text=tr("📆 کاربران بدون خرید در N روز اخیر"), callback_data="adm_broadcast_target:no_purchase")],
        [InlineKeyboardButton(text=tr("🚪 خارج‌شده از کانال اجباری (ولی عضو ربات)"), callback_data="adm_broadcast_target:left_channel")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")],
    ])


def admin_broadcast_server_select_kb(db) -> InlineKeyboardMarkup:
    servers = db.get_panel_servers()
    rows = []
    for s in servers:
        icon = "🟢" if s["is_active"] else "🔴"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {s['name']}", callback_data=f"adm_broadcast_server:{s['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_broadcast")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_duration_kb(pin_after_send: bool = False) -> InlineKeyboardMarkup:
    pin_label = "📌 پین بعد از ارسال: روشن ✅" if pin_after_send else "📌 پین بعد از ارسال: خاموش"
    rows = [
        [InlineKeyboardButton(text=tr("🚫 بدون حذف خودکار"), callback_data="adm_broadcast_dur:0")],
        [
            InlineKeyboardButton(text=tr("۱ ساعت"), callback_data="adm_broadcast_dur:3600"),
            InlineKeyboardButton(text=tr("۶ ساعت"), callback_data="adm_broadcast_dur:21600"),
        ],
        [
            InlineKeyboardButton(text=tr("۱ روز"), callback_data="adm_broadcast_dur:86400"),
            InlineKeyboardButton(text=tr("۳ روز"), callback_data="adm_broadcast_dur:259200"),
        ],
        [InlineKeyboardButton(text=tr("✏️ مدت دلخواه (دقیقه)"), callback_data="adm_broadcast_dur:custom")],
        [InlineKeyboardButton(text=pin_label, callback_data="adm_broadcast_toggle_pin")],
        [InlineKeyboardButton(text=tr("⏰ زمان‌بندی ارسال (فقط متن)"), callback_data="adm_broadcast_schedule")],
        [InlineKeyboardButton(text=tr("✏️ ویرایش متن/عکس"), callback_data="adm_broadcast_edit")],
        [InlineKeyboardButton(text=tr("❌ لغو ارسال"), callback_data="adm_broadcast_cancel")],
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
        [InlineKeyboardButton(text=tr("✏️ مدت دلخواه (دقیقه)"), callback_data="adm_card_autodel:custom")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
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
                    InlineKeyboardButton(text=tr("🎨 تغییر رنگ"), callback_data=f"adm_btn_color_menu:{key}"),
                ]
            )
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:appearance")])
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
                InlineKeyboardButton(text=tr("🎨 تغییر رنگ"), callback_data=f"adm_btn_color_menu:{key}"),
            ]
        )
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:appearance")])
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
        [InlineKeyboardButton(text=tr("📈 آمار پیشرفته (روند، درگاه‌ها، نماینده‌ها، قیف تبدیل)"), callback_data="adm_stats_adv:7")],
        [InlineKeyboardButton(text=tr("👥 آمار دقیق کاربران ربات"), callback_data="adm_stats_users_breakdown")],
        [InlineKeyboardButton(text=tr("🏆 برترین خریداران"), callback_data="adm_stats_top_buyers")],
        [InlineKeyboardButton(text=tr("🔍 آمار کامل یک کاربر"), callback_data="adm_stats_user")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:management")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_advanced_stats_kb(active_days: int = 7) -> InlineKeyboardMarkup:
    periods = [(1, "امروز"), (7, "۷ روز اخیر"), (30, "۳۰ روز اخیر"), (90, "۹۰ روز اخیر")]
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if d == active_days else "") + label,
                callback_data=f"adm_stats_adv:{d}",
            )
            for d, label in periods[:2]
        ],
        [
            InlineKeyboardButton(
                text=("✅ " if d == active_days else "") + label,
                callback_data=f"adm_stats_adv:{d}",
            )
            for d, label in periods[2:]
        ],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت به آمار فروش"), callback_data="adm_stats")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_back_kb(callback_data="adm_back_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=tr("⬅️ بازگشت به پنل مدیریت"), callback_data=callback_data)]]
    )


def user_full_stats_kb(tg_id: int, is_blocked: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("📦 لیست کامل کانفیگ‌های این کاربر"), callback_data=f"adm_user_configs:{tg_id}")],
        [InlineKeyboardButton(text=tr("🛠 مدیریت تک‌تک کانفیگ‌ها"), callback_data=f"adm_user_cfglist:{tg_id}")],
        [InlineKeyboardButton(text=tr("⏻ فعال/غیرفعال کردن همه‌ی کانفیگ‌های این کاربر"), callback_data=f"adm_user_toggle_all:{tg_id}")],
        [InlineKeyboardButton(text=tr("✉️ ارسال پیام مستقیم"), callback_data=f"adm_user_msg:{tg_id}")],
        [InlineKeyboardButton(text=tr("🎁 ارسال کد تخفیف اختصاصی"), callback_data=f"adm_user_disc:{tg_id}")],
        [InlineKeyboardButton(text=tr("💰 ویرایش موجودی کیف‌پول"), callback_data=f"adm_user_wallet:{tg_id}")],
        [InlineKeyboardButton(
            text=tr("✅ آنبلاک کاربر") if is_blocked else tr("🚫 بلاک کاربر"),
            callback_data=f"adm_user_toggleblock:{tg_id}",
        )],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_stats")],
    ])


def user_toggle_all_confirm_kb(tg_id: int, new_enabled: bool) -> InlineKeyboardMarkup:
    flag = "1" if new_enabled else "0"
    label = "✅ بله، همه را فعال کن" if new_enabled else "⚠️ بله، همه را غیرفعال کن"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"adm_user_toggle_all_go:{tg_id}:{flag}")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data=f"adm_user_configs:{tg_id}")],
    ])


def admin_user_config_list_kb(tg_id: int, configs) -> InlineKeyboardMarkup:
    rows = []
    for cc in configs:
        name = cc["display_name"] or cc["username"]
        enabled = (cc["enabled"] if "enabled" in cc.keys() else 1) == 1
        icon = "🟢" if enabled else "🔴"
        rows.append([InlineKeyboardButton(text=f"{icon} {name}", callback_data=f"adm_cfg_view:{tg_id}:{cc['id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_user_view:{tg_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_config_detail_kb(tg_id: int, cc_id: int, enabled: bool, auto_renew: bool, can_auto_renew: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=tr("🔴 غیرفعال کردن") if enabled else tr("🟢 فعال کردن"),
            callback_data=f"adm_cfg_toggle:{tg_id}:{cc_id}",
        )],
    ]
    if can_auto_renew:
        rows.append([InlineKeyboardButton(
            text=tr("⏸ خاموش کردن تمدید خودکار") if auto_renew else tr("🔁 روشن کردن تمدید خودکار"),
            callback_data=f"adm_cfg_autorenew:{tg_id}:{cc_id}",
        )])
    rows.append([InlineKeyboardButton(text=tr("✏️ تغییر نام"), callback_data=f"adm_cfg_rename:{tg_id}:{cc_id}")])
    rows.append([InlineKeyboardButton(text=tr("👤 انتقال به کاربر دیگر"), callback_data=f"adm_cfg_transfer:{tg_id}:{cc_id}")])
    rows.append([InlineKeyboardButton(text=tr("🕒 تاریخچه"), callback_data=f"adm_cfg_history:{tg_id}:{cc_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت به لیست کانفیگ‌ها"), callback_data=f"adm_user_cfglist:{tg_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cfg_transfer_confirm_kb(tg_id: int, cc_id: int, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، منتقل شود"), callback_data=f"adm_cfg_transok:{tg_id}:{cc_id}:{target_id}")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data=f"adm_cfg_view:{tg_id}:{cc_id}")],
    ])


def deeplink_tools_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("🔗 ساخت دیپ‌لینک تبلیغاتی"), callback_data="adm_dl_build")],
        [InlineKeyboardButton(text=tr("🖼 افزودن دکمه به پست کانال"), callback_data="adm_dl_addbtn")],
        [InlineKeyboardButton(text=tr("📋 پارامترهای اصلی منوی کاربر"), callback_data="adm_dl_params_list")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")],
    ])


def deeplink_type_picker_kb(back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("🛒 خرید"), callback_data="adm_dlp_type:buy")],
        [InlineKeyboardButton(text=tr("🎯 محصول خاص"), callback_data="adm_dlp_type:prod")],
        [InlineKeyboardButton(text=tr("🎟 کد تخفیف"), callback_data="adm_dlp_type:disc")],
        [InlineKeyboardButton(text=tr("🧪 کانفیگ تست"), callback_data="adm_dlp_type:test")],
        [InlineKeyboardButton(text=tr("🎡 گردونه شانس"), callback_data="adm_dlp_type:wheel")],
        [InlineKeyboardButton(text=tr("🏷 پارامتر دلخواه (فقط آمار منبع)"), callback_data="adm_dlp_type:custom")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_callback)],
    ])


def deeplink_discount_picker_kb(codes, back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🎟 {c['code']}", callback_data=f"adm_dlp_code:{c['id']}")]
        for c in codes if c["is_active"]
    ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deeplink_product_categories_kb(categories, back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"adm_dlp_prodcat:{cat['id']}")]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deeplink_products_kb(products, back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📦 {p['name']} ({p['price']:,}{tr('تومان')})", callback_data=f"adm_dlp_prod:{p['id']}")]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deeplink_attach_discount_picker_kb(codes, product_token: str, back_callback: str) -> InlineKeyboardMarkup:
    """بعد از انتخاب محصول برای دیپ‌لینک، اختیاری یک کد تخفیف هم به آن اضافه
    می‌شود. product_token همان start_param محصول (مثلاً prod_12) است که در
    callback_data کدهای تخفیف قرار می‌گیرد تا در مرحله‌ی نهایی ترکیب شوند."""
    rows = [
        [InlineKeyboardButton(text=f"🎟 {c['code']}", callback_data=f"adm_dlp_prod_disc:{product_token}:{c['id']}")]
        for c in codes if c["is_active"]
    ]
    rows.append([InlineKeyboardButton(text=tr("بدون کد تخفیف"), callback_data=f"adm_dlp_prod_nodisc:{product_token}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_categories_kb(categories) -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        state_icon = "🟢" if cat["is_active"] else "🔴"
        rows.append(
            [
                InlineKeyboardButton(text=f"{state_icon} {cat['name']}", callback_data="noop"),
                InlineKeyboardButton(text=tr("تغییر وضعیت"), callback_data=f"adm_cat_toggle:{cat['id']}"),
                InlineKeyboardButton(text=tr("🗑حذف"), callback_data=f"adm_cat_del:{cat['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن دسته‌بندی جدید"), callback_data="adm_cat_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
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
            [InlineKeyboardButton(text=tr(f"{state_icon} {gw['name']} (حداقل: {min_amt:,} ت)"), callback_data="noop")]
        )
        rows.append(
            [
                InlineKeyboardButton(text=tr("تغییر وضعیت"), callback_data=f"adm_customgw_toggle:{gw['id']}"),
                InlineKeyboardButton(text=tr("🧮 حداقل مبلغ"), callback_data=f"adm_customgw_minamt:{gw['id']}"),
            ]
        )
    if not gateways:
        rows.append([InlineKeyboardButton(text=tr("هیچ درگاه سفارشی‌ای تعریف نشده"), callback_data="noop")])
    rows.append([InlineKeyboardButton(text=tr("ℹ️ ساخت/ویرایش کامل درگاه فقط از مینی‌اپ ممکن است"), callback_data="noop")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_bulk_price_scope_kb(categories, panels):
    rows=[[InlineKeyboardButton(text=tr("🌐 همه دسته‌ها"), callback_data="adm_bprice_cat:all")]]
    for c in categories:
        rows.append([InlineKeyboardButton(text=f"📁 {c['name']}", callback_data=f"adm_bprice_cat:{c['id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_bulk_price_panel_kb(panels):
    rows=[[InlineKeyboardButton(text=tr("🌐 همه پنل‌ها"), callback_data="adm_bprice_panel:all")]]
    for p in panels:
        rows.append([InlineKeyboardButton(text=f"🖥 {p['name']}", callback_data=f"adm_bprice_panel:{p['id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_bulk_price_mode_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("📈 درصدی"), callback_data="adm_bprice_mode:percent"),
         InlineKeyboardButton(text=tr("💰 مبلغ ثابت"), callback_data="adm_bprice_mode:fixed")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_products")],
    ])


def admin_bulk_price_rounding_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("بدون گرد کردن"), callback_data="adm_bprice_round:0")],
        [InlineKeyboardButton(text=tr("۱۰۰ تومان"), callback_data="adm_bprice_round:100"),
         InlineKeyboardButton(text=tr("۱٬۰۰۰ تومان"), callback_data="adm_bprice_round:1000")],
        [InlineKeyboardButton(text=tr("۱۰٬۰۰۰ تومان"), callback_data="adm_bprice_round:10000")],
    ])


def admin_bulk_price_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ اعمال تغییرات"), callback_data="adm_bprice_confirm"),
         InlineKeyboardButton(text=tr("❌ لغو"), callback_data="adm_bprice_cancel")],
    ])


def admin_bulk_price_undo_kb(logs):
    rows=[]
    for r in logs:
        rows.append([InlineKeyboardButton(text=tr(f"↩️ بازگردانی #{r['id']} — {r['created_at']}"), callback_data=f"adm_bprice_undo:{r['id']}")])
    if not rows: rows.append([InlineKeyboardButton(text=tr("تغییر قابل بازگردانی وجود ندارد"), callback_data="noop")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_bulk_wallet_status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("👥 همه‌ی کاربران"), callback_data="adm_bwd_status:all")],
        [InlineKeyboardButton(text=tr("🟢 دارای سرویس فعال"), callback_data="adm_bwd_status:active"),
         InlineKeyboardButton(text=tr("🔴 سرویس منقضی"), callback_data="adm_bwd_status:expired")],
        [InlineKeyboardButton(text=tr("⛔️ بلاک‌شده"), callback_data="adm_bwd_status:blocked")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
    ])


def admin_bulk_wallet_usertype_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("👥 همه"), callback_data="adm_bwd_utype:all")],
        [InlineKeyboardButton(text=tr("🏪 فقط نماینده‌ها"), callback_data="adm_bwd_utype:reseller"),
         InlineKeyboardButton(text=tr("🙍 فقط کاربران عادی"), callback_data="adm_bwd_utype:normal")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_bulk_wallet_deduct")],
    ])


def admin_bulk_wallet_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ اعمال کاهش"), callback_data="adm_bwd_confirm"),
         InlineKeyboardButton(text=tr("❌ لغو"), callback_data="adm_bwd_cancel")],
    ])


def admin_bulk_wallet_credit_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ افزایش موجودی و ارسال اعلان"), callback_data="adm_bwc_confirm"),
         InlineKeyboardButton(text=tr("❌ لغو"), callback_data="adm_bwc_cancel")],
    ])



def admin_products_categories_kb(categories, prefix="adm_prod_cat") -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        rows.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"{prefix}:{cat['id']}")])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن محصول جدید"), callback_data="adm_prod_add")])
    rows.append([InlineKeyboardButton(text=tr("💰 ویرایش گروهی قیمت"), callback_data="adm_bulk_price")])
    rows.append([InlineKeyboardButton(text=tr("↩️ Undo تغییرات قیمت"), callback_data="adm_bulk_price_undo")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_products_list_kb(db, products) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        stock = "∞" if p["is_auto_provision"] else db.count_available_configs(p["id"])
        state_icon = "🟢" if p["is_active"] else "🔴"
        dur = p["duration_days"]
        dur_label = "نامحدود" if (p["provision_server_id"] and dur == 0) else f"{dur if dur is not None else 30} روز"
        rows.append(
            [
                InlineKeyboardButton(
                    text=tr(f"{state_icon} {p['name']} | {p['price']:,}ت | موجودی: {stock} | مدت: {dur_label}"),
                    callback_data="noop",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text=tr("تغییر وضعیت"), callback_data=f"adm_prod_toggle:{p['id']}"),
                InlineKeyboardButton(text=tr("🗑حذف"), callback_data=f"adm_prod_del:{p['id']}"),
            ]
        )
        rows.append(
            [InlineKeyboardButton(text=tr("💳 روش‌های پرداخت مجاز"), callback_data=f"adm_prod_paymethods:{p['id']}")]
        )
        if p["is_auto_provision"]:
            edit_row = [InlineKeyboardButton(text=tr("📶 تغییر حجم"), callback_data=f"adm_prod_vol:{p['id']}")]
            if p["provision_server_id"]:
                edit_row.insert(0, InlineKeyboardButton(text=tr("🔌 تغییر پنل/اینباند"), callback_data=f"adm_prod_srv:{p['id']}"))
            rows.append(edit_row)
            extra = p["extra_user_price"] if "extra_user_price" in p.keys() else 0
            max_users = p["max_users"] if "max_users" in p.keys() else 0
            base_users = p["base_users"] if "base_users" in p.keys() and p["base_users"] else 0
            if base_users and extra and max_users > base_users:
                users_label = f"👥 {base_users} کاربر همزمان (ارتقا تا {max_users}، +{extra:,}ت)"
            elif base_users:
                users_label = f"👥 {base_users} کاربر همزمان (بدون ارتقا)"
            elif extra and max_users:
                users_label = f"👥 کاربر همزمان: تا {max_users} (+{extra:,}ت)"
            else:
                users_label = "👥 محدودیت کاربر: غیرفعال"
            rows.append([InlineKeyboardButton(text=users_label, callback_data=f"adm_prod_users:{p['id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_edit_product_provision_kb(db, product_id) -> InlineKeyboardMarkup:
    product = db.get_product(product_id)
    cat_id = product["category_id"] if product else None
    servers = db.get_panel_servers(active_only=True)
    rows = [
        [InlineKeyboardButton(
            text=f"🖥 {s['name']} ({PANEL_TYPE_LABELS.get(s['panel_type'], s['panel_type'])})",
            callback_data=f"adm_prod_set_srv:{product_id}:{s['id']}",
        )]
        for s in servers
    ]
    back_cb = f"adm_prod_cat:{cat_id}" if cat_id is not None else "adm_products"
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_new_product_payment_methods_kb(db, selected) -> InlineKeyboardMarkup:
    """صفحه‌ی چندانتخابی روش‌های پرداخت مجاز حین «ساخت» محصول جدید (قبل از این‌که
    محصول در دیتابیس ساخته شود). selected=None یعنی «همه مجاز» (پیش‌فرض)."""
    catalog = db.get_payment_methods_catalog()
    all_keys = {item["key"] for item in catalog}
    all_selected = selected is None or not selected or set(selected) >= all_keys

    rows = [[InlineKeyboardButton(
        text=tr(f"{'✅' if all_selected else '⬜️'} همه‌ی روش‌ها فعال باشند"),
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
    rows.append([InlineKeyboardButton(text=tr("✅ تایید و ساخت محصول"), callback_data="newprodpm_done")])
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
        text=tr(f"{'✅' if all_allowed else '⬜️'} همه‌ی روش‌ها فعال باشند"),
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
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_custom_config_product_payment_methods_kb(db, product_id: int) -> InlineKeyboardMarkup:
    """معادل admin_product_payment_methods_kb برای محصولات «ساخت کانفیگ شخصی»
    (چه قیمت‌گذاری فلت، چه پله‌ای/پلکانی). None/[] یعنی «همه مجاز» (پیش‌فرض)."""
    allowed = db.get_custom_config_product_payment_methods(product_id)
    all_allowed = allowed is None
    catalog = db.get_payment_methods_catalog()

    rows = [[InlineKeyboardButton(
        text=tr(f"{'✅' if all_allowed else '⬜️'} همه‌ی روش‌ها فعال باشند"),
        callback_data=f"adm_ccppm_all:{product_id}",
    )]]
    for item in catalog:
        checked = all_allowed or (item["key"] in (allowed or []))
        icon = "✅" if checked else "⬜️"
        suffix = "" if item["enabled"] else " (غیرفعال)"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {item['label']}{suffix}",
            callback_data=f"adm_ccppm_tgl:{product_id}:{item['key']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_ccp_view:{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_wallet_payment_methods_kb(db) -> InlineKeyboardMarkup:
    """صفحه‌ی چندانتخابی روش‌های پرداخت مجاز برای «شارژ کیف پول» - دقیقاً
    مشابه admin_product_payment_methods_kb اما مستقل از محصول (سراسری،
    فقط برای فرایند شارژ کیف پول کاربرد دارد)."""
    allowed = db.get_wallet_topup_payment_methods()
    all_allowed = allowed is None
    catalog = db.get_payment_methods_catalog()

    rows = [[InlineKeyboardButton(
        text=tr(f"{'✅' if all_allowed else '⬜️'} همه‌ی روش‌ها فعال باشند"),
        callback_data="adm_walletpm_all",
    )]]
    for item in catalog:
        checked = all_allowed or (item["key"] in (allowed or []))
        icon = "✅" if checked else "⬜️"
        suffix = "" if item["enabled"] else " (غیرفعال)"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {item['label']}{suffix}",
            callback_data=f"adm_walletpm_tgl:{item['key']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_custom_config_payment_methods_kb(db) -> InlineKeyboardMarkup:
    """چندانتخابی روش‌های پرداخت مجاز سراسری برای «ساخت کانفیگ شخصی»؛ پلنی که
    محدودیت خودش را دارد بر این تنظیم اولویت دارد."""
    allowed = db.get_custom_config_payment_methods()
    all_allowed = allowed is None
    catalog = db.get_payment_methods_catalog()

    rows = [[InlineKeyboardButton(
        text=tr(f"{'✅' if all_allowed else '⬜️'} همه‌ی روش‌ها فعال باشند"),
        callback_data="adm_ccpm_all",
    )]]
    for item in catalog:
        checked = all_allowed or (item["key"] in (allowed or []))
        icon = "✅" if checked else "⬜️"
        suffix = "" if item["enabled"] else " (غیرفعال)"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {item['label']}{suffix}",
            callback_data=f"adm_ccpm_tgl:{item['key']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pick_category_kb(categories, prefix) -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        rows.append([InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"{prefix}:{cat['id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_new_product_source_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("📦 بانک کانفیگ (لینک‌های آماده)"), callback_data="adm_newprod_src:bank")],
        [InlineKeyboardButton(text=tr("🔌 اتصال مستقیم به پنل"), callback_data="adm_newprod_src:direct")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pick_provision_server_kb(servers) -> InlineKeyboardMarkup:
    rows = []
    for s in servers:
        rows.append([InlineKeyboardButton(text=f"🖥 {s['name']}", callback_data=f"adm_newprod_srv:{s['id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_newprod_duration_mode_kb(limited_days: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(f"⏳ محدود ({limited_days} روز)"), callback_data="adm_newprod_durmode:limited")],
        [InlineKeyboardButton(text=tr("♾ نامحدود"), callback_data="adm_newprod_durmode:unlimited")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_newprod_volume_mode_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("🔢 مقدار مشخص"), callback_data="adm_newprod_volmode:limited")],
        [InlineKeyboardButton(text=tr("♾ نامحدود"), callback_data="adm_newprod_volmode:unlimited")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pick_product_kb(products, prefix) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        rows.append([InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"{prefix}:{p['id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
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
        rows.append([InlineKeyboardButton(text=tr("➕ افزودن پلن کانفیگ تست جدید"), callback_data="adm_tp_add")])

    if db.is_full_access_bot(is_main_bot):
        remaining = db.count_available_test_configs()
        rows.append([InlineKeyboardButton(
            text=tr(f"🗄 بانک لینک دستی (قدیمی) - موجودی: {remaining}"), callback_data="adm_test_add",
        )])

    rows.append([InlineKeyboardButton(text=tr("🔁 بازنشانی کانفیگ تست برای همه"), callback_data="adm_reset_test_configs")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cleanup_settings_kb(db) -> InlineKeyboardMarkup:
    expired = db.get_setting("expired_delete_days", "0")
    tests = db.get_setting("test_delete_days", "0")
    warning = db.get_setting("expired_cleanup_warning_days", "3")
    dry = db.get_setting("expired_cleanup_dry_run", "1") == "1"
    inactive_time = db.get_setting("inactive_config_delete_time", "") or "خاموش"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(f"📦 مهلت حذف سرویس: {expired} روز (۰=خاموش)"), callback_data="adm_cleanup_expired")],
        [InlineKeyboardButton(text=tr(f"🧪 مهلت حذف تست: {tests} روز (۰=خاموش)"), callback_data="adm_cleanup_test")],
        [InlineKeyboardButton(text=tr(f"⚠️ هشدار قبل از انقضا: {warning} روز"), callback_data="adm_cleanup_warning")],
        [InlineKeyboardButton(text=("🟢 dry-run روشن" if dry else "🔴 dry-run خاموش"), callback_data="adm_cleanup_dryrun")],
        [InlineKeyboardButton(text=tr(f"🕐 حذف کانفیگ‌های غیرفعال: {inactive_time}"), callback_data="adm_cleanup_inactive_time")],
        [InlineKeyboardButton(text=tr("🗑 پاکسازی کانفیگ‌های یتیم (F147)"), callback_data="adm_cleanup_orphans")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")],
    ])


def admin_service_alert_channel_kb(db) -> InlineKeyboardMarkup:
    channel = (db.get_setting("service_alert_channel", "") or "").strip() or "ثبت نشده"
    rows = [
        [InlineKeyboardButton(text=tr(f"📣 کانال فعلی: {channel}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تنظیم / تغییر کانال"), callback_data="adm_service_alert_set_channel")],
    ]
    if channel != "ثبت نشده":
        rows.append([InlineKeyboardButton(text=tr("🗑 حذف کانال (غیرفعال)"), callback_data="adm_service_alert_clear_channel")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_plan_view_kb(db, plan) -> InlineKeyboardMarkup:
    pid = plan["id"]
    server = db.get_panel_server(plan["panel_server_id"])
    toggle_text = "🔴 غیرفعال‌سازی" if plan["is_active"] else "🟢 فعال‌سازی"
    vol_text = f"{plan['volume_mb']} مگابایت" if plan["volume_mb"] < 1024 else f"{plan['volume_mb'] / 1024:g} گیگ"
    dur_text = f"{plan['duration_hours']} ساعت" if plan["duration_hours"] < 24 else f"{plan['duration_hours'] / 24:g} روز"
    rows = [
        [InlineKeyboardButton(text=tr(f"✏️ نام: {plan['name']}"), callback_data=f"adm_tp_edit_name:{pid}")],
        [InlineKeyboardButton(text=tr(f"✏️ پیشوند نام کاربری: {plan['name_prefix']}"), callback_data=f"adm_tp_edit_prefix:{pid}")],
        [InlineKeyboardButton(
            text=f"{tr('🖥 پنل:')} {server['name'] if server else '—'}", callback_data=f"adm_tp_edit_panel:{pid}",
        )],
        [InlineKeyboardButton(text=tr(f"📶 حجم: {vol_text}"), callback_data=f"adm_tp_edit_volume:{pid}")],
        [InlineKeyboardButton(text=tr(f"⏳ مدت: {dur_text}"), callback_data=f"adm_tp_edit_duration:{pid}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_tp_toggle:{pid}")],
        [InlineKeyboardButton(text=tr("🗑 حذف پلن"), callback_data=f"adm_tp_delete:{pid}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_test_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_plan_delete_confirm_kb(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، این پلن حذف شود"), callback_data=f"adm_tp_delete_force:{plan_id}")],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"adm_tp_view:{plan_id}")],
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
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن سرور جدید"), callback_data="adm_panel_server_add")])
    back_cb = f"adm_tp_view:{plan_id}" if plan_id is not None else "adm_test_menu"
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_forcejoin_menu_kb(db) -> InlineKeyboardMarkup:
    settings = db.get_force_join_settings()
    toggle_text = "🔴 غیرفعال کردن عضویت اجباری" if settings["enabled"] else "🟢 فعال کردن عضویت اجباری"
    channel_text = f"کانال فعلی: {settings['channel']}" if settings["channel"] else "کانالی ثبت نشده است"
    rows = [
        [InlineKeyboardButton(text=channel_text, callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تنظیم / تغییر کانال"), callback_data="adm_forcejoin_set_channel")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_forcejoin_toggle")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")],
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
    "btn_commission_reseller_request": "دکمه درخواست نمایندگی کمیسیونی",
    "btn_reseller_tiers": "دکمه انتخاب سطح نمایندگی",
    "btn_tutorial": "دکمه آموزش",
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
            InlineKeyboardButton(text=tr("✏️ ویرایش متن"), callback_data=f"adm_btn_edit:{key}"),
            InlineKeyboardButton(text=tr("🎨 تغییر رنگ"), callback_data=f"adm_btn_color_menu:{key}"),
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
        text=tr(f"✨ دکمه مینی‌اپ فروشگاه{' (فعال)' if miniapp_enabled else ' (غیرفعال)'}"), callback_data="noop",
    )])
    rows.append([InlineKeyboardButton(
        text="🔴 غیرفعال‌سازی" if miniapp_enabled else "🟢 فعال‌سازی",
        callback_data="adm_btn_toggle:miniapp",
    )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:appearance")])
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
        [InlineKeyboardButton(text=tr(f"منوی پایین (Reply): {'🟢 فعال' if reply_on else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(text=reply_toggle, callback_data="adm_mm_toggle_reply")],
        [InlineKeyboardButton(text=tr(f"منوی شیشه‌ای بالا (Inline): {'🟢 فعال' if inline_on else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(text=inline_toggle, callback_data="adm_mm_toggle_inline")],
        [InlineKeyboardButton(text=tr(f"چیدمان فعلی: {columns} دکمه در هر ردیف"), callback_data="noop")],
        [InlineKeyboardButton(text=col_toggle, callback_data="adm_mm_toggle_columns")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:appearance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_color_picker_kb(key: str, back_callback: str = "adm_edit_buttons") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("🔵 آبی (Primary)"), callback_data=f"adm_btn_color_set:{key}:primary")],
        [InlineKeyboardButton(text=tr("🟢 سبز (Success)"), callback_data=f"adm_btn_color_set:{key}:success")],
        [InlineKeyboardButton(text=tr("🔴 قرمز (Danger)"), callback_data=f"adm_btn_color_set:{key}:danger")],
        [InlineKeyboardButton(text=tr("⚪️ پیش‌فرض (خاکستری)"), callback_data=f"adm_btn_color_set:{key}:none")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=back_callback)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_admins_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("📃 لیست ادمین‌ها و نقش‌ها"), callback_data="adm_admins_list")],
        [InlineKeyboardButton(text=tr("➕ افزودن ادمین"), callback_data="adm_admin_add")],
        [InlineKeyboardButton(text=tr("🔄 تغییر نقش ادمین"), callback_data="adm_admin_role_change")],
        [InlineKeyboardButton(text=tr("➖ حذف ادمین"), callback_data="adm_admin_remove")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:access")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


ADMIN_ROLE_LABELS = {"owner": "👑 مالک", "admin": "🛡 مدیر کامل", "mid": "🥈 ادمین میانی", "support": "🎧 پشتیبان"}


def admin_role_pick_kb(target_tg_id: int, action: str) -> InlineKeyboardMarkup:
    """action: 'add' یا 'setrole' - پیشوند callback_data برای تمایز دو مسیر."""
    prefix = "adm_add_admin_role" if action == "add" else "adm_change_role_set"
    rows = [
        [InlineKeyboardButton(text=tr("🛡 مدیر کامل (دسترسی کامل)"), callback_data=f"{prefix}:{target_tg_id}:admin")],
        [InlineKeyboardButton(text=tr("🥈 ادمین میانی (بدون آمار/فروش/نمایندگی)"), callback_data=f"{prefix}:{target_tg_id}:mid")],
        [InlineKeyboardButton(text=tr("🎧 پشتیبان (فقط تیکت و سفارش)"), callback_data=f"{prefix}:{target_tg_id}:support")],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data="adm_admins_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pending_orders_kb(orders) -> InlineKeyboardMarkup:
    rows = []
    for o in orders:
        rows.append(
            [InlineKeyboardButton(text=tr(f"سفارش #{o['id']} - کاربر {o['user_id']}"), callback_data=f"view_order:{o['id']}")]
        )
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)




def order_survey_kb(survey_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{n}⭐", callback_data=f"svy:{survey_id}:{n}") for n in range(1, 6)
    ]])


def order_surveys_list_kb(orders, surveys) -> InlineKeyboardMarkup:
    rows = []
    for o in orders:
        s = surveys.get(o["id"])
        state = f"⭐{s['rating']}" if s and s["rating"] else ("✉️ ارسال‌شده" if s else "🗳 ارسال")
        rows.append([InlineKeyboardButton(
            text=tr(f"#{o['id']} · کاربر {o['user_id']} · {state}"), callback_data=f"adm_svy_send:{o['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("📊 نتایج به تفکیک پنل"), callback_data="adm_svy_results")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
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
                text=tr(f"{st} | {kind} #{inv['ref_id']} | {inv['amount_toman']:,} تومان"),
                callback_data=f"view_crypto_invoice:{inv['id']}",
            )
        ]
        if inv["status"] in ("new", "pending"):
            row.append(InlineKeyboardButton(text=tr("❌ لغو"), callback_data=f"cancel_crypto_invoice:{inv['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text=tr("🔄 بروزرسانی"), callback_data="adm_crypto_payments")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
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
                text=tr(f"{st} | {kind} #{inv['ref_id']} | {inv['amount_toman']:,} تومان"),
                callback_data=f"view_abangateway_invoice:{inv['id']}",
            )
        ]
        if inv["status"] in ("new", "pending"):
            row.append(InlineKeyboardButton(text=tr("🔄 بررسی"), callback_data=f"check_abangateway_invoice:{inv['id']}"))
            row.append(InlineKeyboardButton(text=tr("❌ لغو"), callback_data=f"cancel_abangateway_invoice:{inv['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text=tr("🔄 بروزرسانی"), callback_data="adm_abangateway_payments")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def blupal_invoices_kb(invoices) -> InlineKeyboardMarkup:
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
                text=tr(f"{st} | {kind} #{inv['ref_id']} | {inv['amount_toman']:,} تومان"),
                callback_data=f"view_blupal_invoice:{inv['id']}",
            )
        ]
        if inv["status"] in ("new", "pending"):
            row.append(InlineKeyboardButton(text=tr("🔄 بررسی"), callback_data=f"check_blupal_invoice:{inv['id']}"))
            row.append(InlineKeyboardButton(text=tr("❌ لغو"), callback_data=f"cancel_blupal_invoice:{inv['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text=tr("🔄 بروزرسانی"), callback_data="adm_blupal_payments")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def noapay_invoices_kb(invoices) -> InlineKeyboardMarkup:
    rows = []
    status_text = {
        "new": "🟡 جدید", "pending": "🟠 در انتظار", "opened": "🟠 باز شده",
        "paid": "🟠 رسید ارسال‌شده", "confirmed": "🟢 تاییدشده", "completed": "🟢 تکمیل‌شده",
        "expired": "🔴 منقضی‌شده", "rejected": "🔴 ردشده",
    }
    kind_text = {"order": "سفارش", "wallet_topup": "شارژ کیف پول"}
    for inv in invoices:
        st = status_text.get(inv["status"], inv["status"] or "---")
        kind = kind_text.get(inv["kind"], inv["kind"])
        row = [
            InlineKeyboardButton(
                text=tr(f"{st} | {kind} #{inv['ref_id']} | {inv['amount_toman']:,} تومان ({inv['stars_count']}⭐)"),
                callback_data=f"view_noapay_invoice:{inv['id']}",
            )
        ]
        if inv["status"] not in ("completed", "expired", "rejected"):
            row.append(InlineKeyboardButton(text=tr("🔄 بررسی"), callback_data=f"check_noapay_invoice:{inv['id']}"))
            row.append(InlineKeyboardButton(text=tr("❌ لغو"), callback_data=f"cancel_noapay_invoice:{inv['id']}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text=tr("🔄 بروزرسانی"), callback_data="adm_noapay_payments")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def blupal_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات درگاه بلوپال: وضعیت و کلید API (هم‌شکل با noapay_settings_kb)."""
    api_key = db.get_setting("blupal_api_key", "")
    enabled = db.get_setting("blupal_payment_enabled", "0") == "1" and bool(api_key)
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"💳 کلید API: {'✅ تنظیم شده' if api_key else '❌ تنظیم نشده'} (تغییر)"),
            callback_data="adm_blupal_set_key",
        )],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def blupal_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات درگاه بلوپال: وضعیت و کلید API (هم‌شکل با noapay_settings_kb)."""
    api_key = db.get_setting("blupal_api_key", "")
    enabled = db.get_setting("blupal_payment_enabled", "0") == "1" and bool(api_key)
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"💳 کلید API: {'✅ تنظیم شده' if api_key else '❌ تنظیم نشده'} (تغییر)"),
            callback_data="adm_blupal_set_key",
        )],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def abangateway_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات آبان گیت وی: وضعیت و کلید API (هم‌شکل با noapay_settings_kb)."""
    api_key = db.get_setting("abangateway_api_key", "")
    enabled = db.get_setting("abangateway_payment_enabled", "0") == "1" and bool(api_key)
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"💳 کلید API: {'✅ تنظیم شده' if api_key else '❌ تنظیم نشده'} (تغییر)"),
            callback_data="adm_abangateway_set_key",
        )],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plisio_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات Plisio: وضعیت و کلید API (هم‌شکل با noapay_settings_kb)."""
    api_key = db.get_setting("plisio_api_key", "")
    rows = [
        [InlineKeyboardButton(
            text=tr(f"🪙 کلید API: {'✅ تنظیم شده' if api_key else '❌ تنظیم نشده'} (تغییر)"),
            callback_data="adm_plisio_set_key",
        )],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def noapay_settings_kb(db) -> InlineKeyboardMarkup:
    """منوی تنظیمات درگاه NoapayBot: وضعیت، کلید API، رمز وب‌هوک، نرخ تبدیل."""
    enabled = db.get_setting("noapay_payment_enabled", "0") == "1"
    api_key = db.get_setting("noapay_api_key", "")
    secret = db.get_setting("noapay_webhook_secret", "")
    rate = db.get_setting("noapay_rate_toman_per_star", "0")
    toggle_text = "🔴 غیرفعال کردن" if enabled else "🟢 فعال کردن"
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_noapay_toggle")],
        [InlineKeyboardButton(
            text=tr(f"🔑 کلید API: {'✅ تنظیم شده' if api_key else '❌ تنظیم نشده'} (تغییر)"),
            callback_data="adm_noapay_set_key",
        )],
        [InlineKeyboardButton(
            text=tr(f"🔏 رمز وب‌هوک: {'✅ تنظیم شده' if secret else '❌ تنظیم نشده'} (تغییر)"),
            callback_data="adm_noapay_set_secret",
        )],
        [InlineKeyboardButton(
            text=tr(f"💱 نرخ هر استارز: {int(rate or 0):,} تومان (تغییر)"),
            callback_data="adm_noapay_set_rate",
        )],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pending_topups_kb(topups) -> InlineKeyboardMarkup:
    rows = []
    for t in topups:
        rows.append(
            [
                InlineKeyboardButton(
                    text=tr(f"شارژ #{t['id']} - کاربر {t['user_id']} - {t['amount']:,} تومان"),
                    callback_data=f"view_topup:{t['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# مدیریت کدهای تخفیف
# ---------------------------------------------------------------------------

def discount_code_constraints_line(c, db=None) -> str:
    """یک خط خلاصه از محدودیت‌های یک کد تخفیف (حداقل/حداکثر خرید، سقف مبلغ
    تخفیف، محصول/دسته‌ی اختصاصی یا چند محصول خاص، تاریخ انقضا) برای نمایش
    زیر اسم کد. db اختیاری است و فقط برای نمایش اسم محصولات (به‌جای شناسه)
    در حالت «چند محصول خاص» استفاده می‌شود."""
    parts = []
    min_purchase = c["min_purchase"] if "min_purchase" in c.keys() else None
    max_purchase = c["max_purchase"] if "max_purchase" in c.keys() else None
    max_discount_amount = c["max_discount_amount"] if "max_discount_amount" in c.keys() else None
    product_id = c["product_id"] if "product_id" in c.keys() else None
    category_id = c["category_id"] if "category_id" in c.keys() else None
    product_ids_raw = c["product_ids"] if "product_ids" in c.keys() else None
    expires_at = c["expires_at"] if "expires_at" in c.keys() else None
    if min_purchase:
        parts.append(f"حداقل خرید {min_purchase:,}ت")
    if max_purchase:
        parts.append(f"حداکثر خرید {max_purchase:,}ت")
    if max_discount_amount:
        parts.append(f"سقف تخفیف {max_discount_amount:,}ت")
    if product_ids_raw:
        names = db.get_discount_product_names(c) if db else []
        if names:
            parts.append(f"مخصوص محصولات: {'، '.join(names)}")
        else:
            parts.append("مخصوص چند محصول خاص")
    elif product_id:
        parts.append(f"مخصوص محصول #{product_id}")
    elif category_id:
        parts.append(f"مخصوص دسته #{category_id}")
    per_user_limit = c["per_user_limit"] if "per_user_limit" in c.keys() else None
    first_only = c["first_purchase_only"] if "first_purchase_only" in c.keys() else 0
    audience = c["audience"] if "audience" in c.keys() else "all"
    if per_user_limit:
        parts.append(f"هر کاربر {per_user_limit} بار")
    if first_only:
        parts.append("فقط خرید اول")
    if audience == "normal":
        parts.append("فقط کاربران عادی")
    elif audience == "reseller":
        parts.append("فقط نمایندگان")
    if expires_at:
        parts.append(f"انقضا: {str(expires_at)[:10]}")
    return " | ".join(parts)


def discount_codes_kb(codes, db=None) -> InlineKeyboardMarkup:
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
                    text=tr(f"{state_icon} {c['code']} | {value_txt} | استفاده: {usage_txt}"), callback_data="noop"
                )
            ]
        )
        constraints_txt = discount_code_constraints_line(c, db)
        if constraints_txt:
            rows.append([InlineKeyboardButton(text=f"ℹ️ {constraints_txt}", callback_data="noop")])
        rows.append(
            [
                InlineKeyboardButton(text=tr("تغییر وضعیت"), callback_data=f"adm_disc_toggle:{c['id']}"),
                InlineKeyboardButton(text=tr("🗑حذف"), callback_data=f"adm_disc_del:{c['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text=tr("➕ ساخت کد تخفیف جدید"), callback_data="adm_disc_add")])
    rows.append([InlineKeyboardButton(text=tr("🎯 کد تخفیف گروهی (بر اساس فیلتر)"), callback_data="adm_bulk_disc")])
    rows.append([InlineKeyboardButton(text=tr("🎁 گیفت‌کدهای شارژ کیف پول"), callback_data="adm_gift_menu")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


BULK_DISCOUNT_FILTER_OPTIONS = [
    ("no_config", "هیچ‌وقت خرید نکرده‌اند (بدون سرویس)"),
    ("inactive_config", "سرویسشان منقضی/غیرفعال شده و تمدید نکرده‌اند"),
    ("no_purchase", "در N روز اخیر خرید تاییدشده‌ی جدید نداشته‌اند"),
]


def bulk_discount_filters_kb(selected) -> InlineKeyboardMarkup:
    selected = selected or []
    rows = []
    for key, label in BULK_DISCOUNT_FILTER_OPTIONS:
        mark = "✅" if key in selected else "◻️"
        rows.append([InlineKeyboardButton(text=tr(f"{mark} {label}"), callback_data=f"adm_bulk_disc_filter:{key}")])
    rows.append([InlineKeyboardButton(text=tr("▶️ ادامه"), callback_data="adm_bulk_disc_next")])
    rows.append([InlineKeyboardButton(text=tr("❌ لغو"), callback_data="adm_bulk_disc_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bulk_discount_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ تایید و ارسال"), callback_data="adm_bulk_disc_confirm")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="adm_bulk_disc_cancel")],
    ])


def discount_first_purchase_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("🆕 فقط اولین خرید کاربر"), callback_data="adm_disc_first:1")],
        [InlineKeyboardButton(text=tr("🌐 همه‌ی خریدها"), callback_data="adm_disc_first:0")],
    ])


def discount_audience_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("👥 همه‌ی کاربران"), callback_data="adm_disc_aud:all")],
        [InlineKeyboardButton(text=tr("🙂 فقط کاربران عادی"), callback_data="adm_disc_aud:normal")],
        [InlineKeyboardButton(text=tr("🤝 فقط نمایندگان"), callback_data="adm_disc_aud:reseller")],
    ])


def discount_scope_picker_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("🌐 همه‌ی محصولات"), callback_data="adm_disc_scope:all")],
        [InlineKeyboardButton(text=tr("📁 فقط یک دسته‌بندی خاص"), callback_data="adm_disc_scope:cat")],
        [InlineKeyboardButton(text=tr("📦 فقط یک محصول خاص"), callback_data="adm_disc_scope:prod")],
        [InlineKeyboardButton(text=tr("🧩 چند محصول خاص"), callback_data="adm_disc_scope:mprod")],
    ])


def discount_scope_categories_kb(categories) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"adm_disc_scope_cat:{cat['id']}")]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_disc_scope_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def discount_scope_products_kb(products) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📦 {p['name']} ({p['price']:,}{tr('تومان')})", callback_data=f"adm_disc_scope_prod:{p['id']}")]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_disc_scope_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def discount_scope_products_multi_kb(products, selected_ids) -> InlineKeyboardMarkup:
    """کیبورد انتخاب چندگانه‌ی محصول برای کد تخفیف با حالت «چند محصول خاص»؛
    هر محصول با یک تیک قابل انتخاب/لغو است و در پایان با دکمه‌ی تایید ثبت می‌شود."""
    selected_ids = set(int(x) for x in (selected_ids or []))
    rows = []
    for p in products:
        mark = "✅" if p["id"] in selected_ids else "◻️"
        cat_name = f" ({p['category_name']})" if "category_name" in p.keys() and p["category_name"] else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark} {p['name']}{cat_name}",
            callback_data=f"adm_disc_scope_mprod_toggle:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr(f"✅ تایید ({len(selected_ids)} محصول)"), callback_data="adm_disc_scope_mprod_done")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_disc_scope_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# تنظیمات زیرمجموعه‌گیری
# ---------------------------------------------------------------------------

def referral_share_kb(link: str) -> InlineKeyboardMarkup:
    """دکمه اشتراک‌گذاری لینک رفرال از طریق پنجره Share خود تلگرام."""
    from urllib.parse import quote

    share_url = (
        "https://t.me/share/url?url="
        + quote(link, safe="")
        + "&text="
        + quote("🤝 برای عضویت در فروشگاه از لینک زیر استفاده کنید:", safe="")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("📤 اشتراک‌گذاری لینک"), url=share_url)]
    ])


def referral_settings_kb(db) -> InlineKeyboardMarkup:
    # --- حالت ۱: پورسانت درصدی از اولین خرید هر زیرمجموعه ---
    enabled = db.get_setting("referral_enabled", "1") == "1"
    toggle_text = "🔴 غیرفعال کردن پورسانت خرید" if enabled else "🟢 فعال کردن پورسانت خرید"
    percent = db.get_setting("referral_percent", "10")
    commission_max = int(db.get_setting("referral_commission_max_count", "0") or 0)
    commission_max_text = f"{commission_max} نفر" if commission_max > 0 else "نامحدود"
    min_purchase = int(db.get_setting("referral_min_purchase_amount", "0") or 0)
    min_purchase_text = f"{min_purchase:,} تومان" if min_purchase > 0 else "بدون حداقل"
    min_purchase_strict = db.get_setting("referral_min_purchase_strict", "0") == "1"
    min_purchase_strict_text = "🔴 حالت سخت‌گیرانه (خرید کم مصرف شود)" if min_purchase_strict else "🟢 حالت منتظر بمان (تا خرید بعدی)"

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

    # --- حالت ۴ (قابلیت ۶۷): پورسانت درصدی روی هر تمدید سرویس زیرمجموعه ---
    renewal_percent = db.get_setting("referral_renewal_percent", "0")
    renewal_max = int(db.get_setting("referral_renewal_max_count", "0") or 0)
    renewal_max_text = f"{renewal_max} تمدید" if renewal_max > 0 else "نامحدود"

    rows = [
        [InlineKeyboardButton(text=tr("① پورسانت درصدی از خرید زیرمجموعه"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"درصد پورسانت: {percent}% | سقف: {commission_max_text}"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_referral_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر درصد پورسانت"), callback_data="adm_referral_percent_edit")],
        [InlineKeyboardButton(text=tr("🔧 رفرال چندمرحله‌ای"), callback_data="adm_referral_multilevel_toggle")],
        [InlineKeyboardButton(text=tr("📊 درصد سطح ۲ و ۳"), callback_data="adm_referral_multilevel_info")],
        [InlineKeyboardButton(text=tr("✏️ تنظیم درصد سطح ۲ و ۳"), callback_data="adm_referral_multilevel_edit")],
        [InlineKeyboardButton(text=tr("✏️ تغییر سقف تعداد نفرات (۰=نامحدود)"), callback_data="adm_referral_commission_max_edit")],
        [InlineKeyboardButton(text=tr(f"حداقل مبلغ خرید برای پورسانت: {min_purchase_text}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تغییر حداقل مبلغ خرید (۰=بدون حداقل)"), callback_data="adm_referral_min_purchase_edit")],
        [InlineKeyboardButton(text=min_purchase_strict_text, callback_data="adm_referral_min_purchase_strict_toggle")],

        [InlineKeyboardButton(text=tr("② کانفیگ رایگان با تعداد دعوت مشخص"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"آستانه: {fc_threshold} نفر | محصول: {fc_product_name}"), callback_data="noop")],
        [InlineKeyboardButton(text=fc_toggle_text, callback_data="adm_referral_freeconfig_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر تعداد دعوت لازم"), callback_data="adm_referral_freeconfig_threshold_edit")],
        [InlineKeyboardButton(text=tr("📦 انتخاب محصول جایزه"), callback_data="adm_referral_freeconfig_product")],

        [InlineKeyboardButton(text=tr("③ شارژ ثابت کیف پول به‌ازای هر دعوت"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"مبلغ: {ib_amount} تومان | سقف: {ib_max_text}"), callback_data="noop")],
        [InlineKeyboardButton(text=ib_toggle_text, callback_data="adm_referral_invitebonus_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر مبلغ شارژ"), callback_data="adm_referral_invitebonus_amount_edit")],
        [InlineKeyboardButton(text=tr("✏️ تغییر سقف تعداد نفرات (۰=نامحدود)"), callback_data="adm_referral_invitebonus_max_edit")],

        [InlineKeyboardButton(text=tr("④ پورسانت درصدی روی تمدید سرویس زیرمجموعه"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"درصد پورسانت تمدید: {renewal_percent}% (۰=غیرفعال) | سقف: {renewal_max_text}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تغییر درصد پورسانت تمدید"), callback_data="adm_referral_renewal_percent_edit")],
        [InlineKeyboardButton(text=tr("✏️ تغییر سقف تعداد تمدیدها (۰=نامحدود)"), callback_data="adm_referral_renewal_max_edit")],

        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_freeconfig_product_kb(db) -> InlineKeyboardMarkup:
    products = db.get_all_products()
    rows = []
    for p in products:
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} ({p['category_name']})", callback_data=f"adm_referral_freeconfig_setprod:{p['id']}"
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_referral_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def signup_gift_settings_kb(db) -> InlineKeyboardMarkup:
    enabled = db.get_setting("signup_gift_enabled", "0") == "1"
    toggle_text = "🔴 غیرفعال کردن هدیه‌ی عضویت" if enabled else "🟢 فعال کردن هدیه‌ی عضویت"
    amount = db.get_setting("signup_gift_amount", "0")
    delay_days = db.get_setting("signup_gift_delay_days", "3")
    rows = [
        [InlineKeyboardButton(text=tr(f"مبلغ: {amount} تومان | بعد از {delay_days} روز بدون خرید"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_signup_gift_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر مبلغ هدیه"), callback_data="adm_signup_gift_amount_edit")],
        [InlineKeyboardButton(text=tr("✏️ تغییر مدت انتظار (روز)"), callback_data="adm_signup_gift_delay_edit")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# گردونه شانس
# ---------------------------------------------------------------------------

def wheel_settings_kb(db) -> InlineKeyboardMarkup:
    s = db.get_wheel_settings()
    toggle_text = "🔴 غیرفعال کردن گردونه" if s["enabled"] else "🟢 فعال کردن گردونه"
    prizes_txt = "، ".join(f"{p}%" for p in s["prizes"]) or "---"
    rows = [
        [InlineKeyboardButton(text=tr(f"احتمال برد: {s['win_percent']}%"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"جوایز ممکن: {prizes_txt}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"اعتبار کد جایزه: {s['expiry_hours']} ساعت"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"فاصله بین دو چرخش: {s['cooldown_hours']} ساعت"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_wheel_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر درصد برد"), callback_data="adm_wheel_edit_percent")],
        [InlineKeyboardButton(text=tr("✏️ تغییر لیست جوایز"), callback_data="adm_wheel_edit_prizes")],
        [InlineKeyboardButton(text=tr("✏️ تغییر اعتبار کد"), callback_data="adm_wheel_edit_expiry")],
        [InlineKeyboardButton(text=tr("✏️ تغییر فاصله چرخش"), callback_data="adm_wheel_edit_cooldown")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:marketing")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def renewal_settings_kb(db) -> InlineKeyboardMarkup:
    s = db.get_renewal_settings()
    toggle_text = "🔴 غیرفعال کردن یادآوری" if s["enabled"] else "🟢 فعال کردن یادآوری"
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if s['enabled'] else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"📅 چند روز قبل از اتمام سرویس: {s['days_before']} روز"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"🎟 درصد تخفیف کد تشویقی: {s['discount_percent']}٪"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"⏳ اعتبار کد تشویقی: {s['discount_expiry_hours']} ساعت"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_renewal_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر تعداد روز یادآوری"), callback_data="adm_renewal_edit_days")],
        [InlineKeyboardButton(text=tr("✏️ تغییر درصد تخفیف"), callback_data="adm_renewal_edit_percent")],
        [InlineKeyboardButton(text=tr("✏️ تغییر اعتبار کد (ساعت)"), callback_data="adm_renewal_edit_hours")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def volume_reminder_settings_kb(db) -> InlineKeyboardMarkup:
    s = db.get_volume_reminder_settings()
    toggle_text = "🔴 غیرفعال کردن یادآوری" if s["enabled"] else "🟢 فعال کردن یادآوری"
    mode_text = "📊 مبنا: درصد مصرف" if s["mode"] == "percent" else "📦 مبنا: حجم باقی‌مانده (گیگ)"
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if s['enabled'] else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(text=mode_text, callback_data="adm_volume_toggle_mode")],
    ]
    if s["mode"] == "percent":
        rows.append([InlineKeyboardButton(
            text=tr(f"📊 آستانه: وقتی {s['percent']}٪ مصرف شد"), callback_data="noop")])
        rows.append([InlineKeyboardButton(
            text=tr("✏️ تغییر درصد آستانه"), callback_data="adm_volume_edit_percent")])
    else:
        rows.append([InlineKeyboardButton(
            text=tr(f"📦 آستانه: وقتی {s['gb_left']} گیگ باقی ماند"), callback_data="noop")])
        rows.append([InlineKeyboardButton(
            text=tr("✏️ تغییر آستانه (گیگ)"), callback_data="adm_volume_edit_gb")])
    rows += [
        [InlineKeyboardButton(text=tr(f"🎟 درصد تخفیف کد تشویقی: {s['discount_percent']}٪"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"⏳ اعتبار کد تشویقی: {s['discount_expiry_hours']} ساعت"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_volume_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر درصد تخفیف"), callback_data="adm_volume_edit_discount_percent")],
        [InlineKeyboardButton(text=tr("✏️ تغییر اعتبار کد (ساعت)"), callback_data="adm_volume_edit_discount_hours")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def connect_alert_settings_kb(db) -> InlineKeyboardMarkup:
    s = db.get_connect_alert_settings()
    connect_toggle = "🔴 غیرفعال کردن هشدار اتصال" if s["connect_enabled"] else "🟢 فعال کردن هشدار اتصال"
    no_connect_toggle = "🔴 غیرفعال کردن هشدار عدم‌اتصال" if s["no_connect_enabled"] else "🟢 فعال کردن هشدار عدم‌اتصال"
    rows = [
        [InlineKeyboardButton(text=tr("✅ — هشدار اتصال به کانفیگ —"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"وضعیت: {'🟢 فعال' if s['connect_enabled'] else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"📊 آستانه‌ی مصرف: {s['connect_threshold_mb']:g} مگابایت"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تغییر آستانه"), callback_data="adm_connect_edit_threshold")],
        [InlineKeyboardButton(text=tr("✏️ تغییر متن پیام"), callback_data="adm_connect_edit_text")],
        [InlineKeyboardButton(text=connect_toggle, callback_data="adm_connect_toggle")],
        [InlineKeyboardButton(text=tr("⚠️ — هشدار عدم‌اتصال به کانفیگ —"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"وضعیت: {'🟢 فعال' if s['no_connect_enabled'] else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"⏱ مهلت بعد از فعال‌سازی: {s['no_connect_hours']} ساعت"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"📊 آستانه‌ی مصرف: {s['no_connect_threshold_mb']:g} مگابایت"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تغییر مهلت (ساعت)"), callback_data="adm_no_connect_edit_hours")],
        [InlineKeyboardButton(text=tr("✏️ تغییر آستانه"), callback_data="adm_no_connect_edit_threshold")],
        [InlineKeyboardButton(text=tr("✏️ تغییر متن پیام"), callback_data="adm_no_connect_edit_text")],
        [InlineKeyboardButton(text=no_connect_toggle, callback_data="adm_no_connect_toggle")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def early_renewal_discount_kb(db) -> InlineKeyboardMarkup:
    s = db.get_early_full_renewal_discount_settings()
    toggle_text = "🔴 غیرفعال کردن تخفیف" if s["enabled"] else "🟢 فعال کردن تخفیف"
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {'🟢 فعال' if s['enabled'] else '🔴 غیرفعال'}"), callback_data="noop")],
        [InlineKeyboardButton(
            text=tr(f"📅 حداکثر روز مانده به انقضا: {s['days_before']} روز"), callback_data="noop")],
        [InlineKeyboardButton(text=tr(f"🎁 درصد تخفیف: {s['percent']}٪"), callback_data="noop")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_early_renewal_toggle")],
        [InlineKeyboardButton(text=tr("✏️ تغییر تعداد روز"), callback_data="adm_early_renewal_edit_days")],
        [InlineKeyboardButton(text=tr("✏️ تغییر درصد تخفیف"), callback_data="adm_early_renewal_edit_percent")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_alert_settings_kb(db) -> InlineKeyboardMarkup:
    threshold = db.get_setting("low_stock_threshold", "3")
    rows = [
        [InlineKeyboardButton(text=tr(f"📦 آستانه‌ی فعلی: {threshold} کانفیگ باقی‌مانده"), callback_data="noop")],
        [InlineKeyboardButton(text=tr("✏️ تغییر آستانه"), callback_data="adm_stock_alert_edit")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:alerts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# روش‌های داخلی که حداقل‌مبلغ‌شان از صفحه‌ی «حداقل مبلغ پرداخت‌ها» قابل تنظیم
# است. کیف پول جدا از بقیه است چون در واقع «حداقل مبلغ شارژ کیف پول» است، نه
# حداقل مبلغ یک درگاه.
MIN_AMOUNT_SETTINGS_ITEMS = [
    ("min_amount_wallet_topup", "👛 حداقل مبلغ شارژ کیف پول"),
    ("max_wallet_balance", "🧢 سقف موجودی کیف پول"),
    ("min_amount_card", "💳 حداقل مبلغ کارت‌به‌کارت (دستی)"),
    ("min_amount_abangateway", "💳 حداقل مبلغ آبان گیت وی"),
    ("min_amount_blupal", "💳 حداقل مبلغ بلوپال"),
    ("min_amount_noapay", "⭐ حداقل مبلغ NoapayBot"),
    ("min_amount_crypto", "🪙 حداقل مبلغ پرداخت کریپتو"),
] + [
    (extra_gateway_registry.min_amount_setting(_k),
     f"{extra_gateway_registry.GATEWAYS[_k]['icon']} حداقل مبلغ {extra_gateway_registry.GATEWAYS[_k]['title']}")
    for _k in extra_gateway_registry.GATEWAY_ORDER
]


def min_amount_settings_kb(db) -> InlineKeyboardMarkup:
    """صفحه‌ی تنظیم حداقل مبلغ برای شارژ کیف پول و هر روش پرداخت داخلی.
    حداقل مبلغ هر درگاه سفارشی از داخل همان درگاه (adm_custom_gateways) تنظیم
    می‌شود، نه از این صفحه."""
    rows = []
    for key, label in MIN_AMOUNT_SETTINGS_ITEMS:
        value = db.get_setting(key, "0")
        rows.append([InlineKeyboardButton(
            text=tr(f"{label}: {int(value or 0):,} تومان"),
            callback_data=f"adm_minamt_edit:{key}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:finance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# ساخت کانفیگ شخصی (پنل‌های VPN + قیمت‌گذاری)
# ---------------------------------------------------------------------------

def location_transfer_settings_kb(db) -> InlineKeyboardMarkup:
    limit = db.get_setting("location_change_user_limit", "0")
    free = db.get_setting("location_change_free_quota", "0")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(f"👤 سقف هر کاربر: {'نامحدود' if limit == '0' else limit}"), callback_data="adm_location_transfer_user_limit")],
        [InlineKeyboardButton(text=tr(f"🎁 سهمیه رایگان کلی: {'خاموش' if free == '0' else free}"), callback_data="adm_location_transfer_free_quota")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_custom_config_settings")],
    ])


def custom_config_menu_kb(db, is_main_bot: bool = True) -> InlineKeyboardMarkup:
    settings = db.get_custom_config_settings()
    status = "🟢 فعال" if settings["enabled"] else "🔴 غیرفعال"
    prefix = db.get_custom_config_prefix()
    prefix_label = f"«{prefix}-»" if prefix else "خاموش (بدون پیش‌وند)"
    rows = [
        [InlineKeyboardButton(text=tr(f"وضعیت: {status} (برای تغییر بزنید)"), callback_data="adm_custom_config_toggle")],
        [InlineKeyboardButton(
            text=tr(f"📶 حداقل/حداکثر حجم: {settings['min_gb']} تا {settings['max_gb']} گیگ"),
            callback_data="adm_custom_config_edit_range",
        )],
        [InlineKeyboardButton(text=tr(f"🏷 پیش‌وند نام کانفیگ: {prefix_label}"), callback_data="adm_custom_config_prefix")],
        [InlineKeyboardButton(text=tr("📍 تنظیمات تغییر لوکیشن سرویس"), callback_data="adm_location_transfer_settings")],
    ]
    if db.is_full_access_bot(is_main_bot):
        # اتصال پنل VPN فقط توسط بات اصلی یا نمایندگی سطح کامل مدیریت می‌شود؛ نمایندگی سطح ۲
        # از استخر حجمی که ادمین بات اصلی تعیین می‌کند استفاده می‌کند، نه پنل خودش.
        rows.append([InlineKeyboardButton(text=tr("🖥 مدیریت سرورهای پنل"), callback_data="adm_panel_servers")])
    rows.append([InlineKeyboardButton(text=tr("💰 مدیریت قیمت‌گذاری بر اساس بازه (تنظیم قدیمی/پیش‌فرض)"), callback_data="adm_pricing_tiers")])
    rows.append([InlineKeyboardButton(text=tr("🧩 محصولات کانفیگ‌ساز (چندمحصولی)"), callback_data="adm_ccp_list")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:products")])
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
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن محصول جدید"), callback_data="adm_ccp_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_custom_config_settings")])
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
        [InlineKeyboardButton(text=f"{tr('✏️ نام:')} {product['name']}", callback_data=f"adm_ccp_edit_name:{pid}")],
        [InlineKeyboardButton(text=f"{tr('✏️ توضیح:')} {product['description'] or '—'}", callback_data=f"adm_ccp_edit_desc:{pid}")],
        [InlineKeyboardButton(
            text=f"{tr('🖥 پنل:')} {server['name'] if server else '—'}", callback_data=f"adm_ccp_edit_panel:{pid}",
        )],
        [InlineKeyboardButton(
            text=tr(f"📶 حجم: {product['min_gb']} تا {product['max_gb']} گیگ"), callback_data=f"adm_ccp_edit_volume:{pid}",
        )],
        [InlineKeyboardButton(text=duration_label, callback_data=f"adm_ccp_duration_mode:{pid}")],
        [InlineKeyboardButton(text=pricing_label, callback_data=f"adm_ccp_pricing_mode:{pid}")],
    ]
    if product["pricing_mode"] == "tiered":
        rows.append([InlineKeyboardButton(text=tr("💰 مدیریت تعرفه‌های پله‌ای این محصول"), callback_data=f"adm_ccp_tiers:{pid}")])
    else:
        rows.append([InlineKeyboardButton(text=tr("✏️ تغییر قیمت هر گیگ"), callback_data=f"adm_ccp_edit_flat_price:{pid}")])
    rows.append([InlineKeyboardButton(text=tr("💳 روش‌های پرداخت مجاز"), callback_data=f"adm_ccp_paymethods:{pid}")])
    rows += [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_ccp_toggle:{pid}")],
        [InlineKeyboardButton(text=tr("🗑 حذف محصول"), callback_data=f"adm_ccp_delete:{pid}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_ccp_list")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_config_product_delete_confirm_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، این محصول حذف شود"), callback_data=f"adm_ccp_delete_force:{product_id}")],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"adm_ccp_view:{product_id}")],
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
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن سرور جدید"), callback_data="adm_panel_server_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_ccp_view:{product_id}")])
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
        [InlineKeyboardButton(text=tr("⏳ مدت ثابت (ادمین تعیین می‌کند)"), callback_data=f"adm_ccp_set_duration_mode:{product_id}:fixed")],
        [InlineKeyboardButton(text=tr("🧑‍💻 مدت قابل‌انتخاب توسط مشتری"), callback_data=f"adm_ccp_set_duration_mode:{product_id}:user_choice")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_ccp_view:{product_id}")],
    ])


def custom_config_product_pricing_mode_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("💵 قیمت فلت (یک نرخ ثابت هر گیگ)"), callback_data=f"adm_ccp_set_pricing_mode:{product_id}:flat")],
        [InlineKeyboardButton(text=tr("📊 قیمت پله‌ای (بر اساس بازه‌ی حجم)"), callback_data=f"adm_ccp_set_pricing_mode:{product_id}:tiered")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_ccp_view:{product_id}")],
    ])


def custom_config_product_tiers_kb(db, product_id: int) -> InlineKeyboardMarkup:
    tiers = db.get_custom_config_product_tiers(product_id)
    rows = []
    for t in tiers:
        to_label = f"{t['to_gb']}" if t["to_gb"] is not None else "∞"
        rows.append([InlineKeyboardButton(
            text=tr(f"{t['from_gb']} تا {to_label} گیگ ← {t['price_per_gb']:,} تومان/گیگ  🗑"),
            callback_data=f"adm_ccp_tier_delete:{product_id}:{t['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن بازه‌ی قیمت"), callback_data=f"adm_ccp_tier_add:{product_id}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_ccp_view:{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_config_product_select_kb(products) -> InlineKeyboardMarkup:
    """کیبورد انتخاب محصول برای کاربر، وقتی بیش از یک محصول فعال وجود دارد."""
    rows = [
        [InlineKeyboardButton(text=f"{p['icon'] or '🛠'} {p['name']}", callback_data=f"ccf_pick_product:{p['id']}")]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_type_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="PasarGuard", callback_data="adm_panel_type:pasarguard")],
        [InlineKeyboardButton(text="3X-UI", callback_data="adm_panel_type:3xui")],
        [InlineKeyboardButton(text="Marzban", callback_data="adm_panel_type:marzban")],
        [InlineKeyboardButton(text="Marzneshin", callback_data="adm_panel_type:marzneshin")],
        [InlineKeyboardButton(text="Hiddify", callback_data="adm_panel_type:hiddify")],
        [InlineKeyboardButton(text="Alireza X-UI", callback_data="adm_panel_type:alireza")],
        [InlineKeyboardButton(text="Rebecca", callback_data="adm_panel_type:rebecca")],
        [InlineKeyboardButton(text="S-UI", callback_data="adm_panel_type:sui")],
        [InlineKeyboardButton(text="WGDashboard", callback_data="adm_panel_type:wgdashboard")],
        [InlineKeyboardButton(text="MikroTik", callback_data="adm_panel_type:mikrotik")],
        [InlineKeyboardButton(text="IBSng", callback_data="adm_panel_type:ibsng")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")],
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
    rows.append([InlineKeyboardButton(text=tr("❌ انصراف"), callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_servers_list_kb(db) -> InlineKeyboardMarkup:
    servers = db.get_panel_servers()
    rows = []
    for s in servers:
        icon = "🟢" if s["is_active"] else "🔴"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {s['name']} ({PANEL_TYPE_LABELS.get(s['panel_type'], s['panel_type'])})", callback_data=f"adm_panel_server_view:{s['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن سرور جدید"), callback_data="adm_panel_server_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_custom_config_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_server_view_kb(server) -> InlineKeyboardMarkup:
    toggle_text = "🔴 غیرفعال‌سازی" if server["is_active"] else "🟢 فعال‌سازی"
    custom_text = "✅ برای خرید شخصی: فعال" if server["used_for_custom_config"] else "◻️ برای خرید شخصی: غیرفعال"
    test_text = "✅ برای کانفیگ تست: فعال" if server["used_for_test_config"] else "◻️ برای کانفیگ تست: غیرفعال"
    reseller_text = "✅ برای نمایندگی: فعال" if server["used_for_reseller"] else "◻️ برای نمایندگی: غیرفعال"
    rows = [
        [InlineKeyboardButton(text=tr("🔌 تست اتصال"), callback_data=f"adm_panel_server_test:{server['id']}")],
        [InlineKeyboardButton(text=tr("🧩 تغییر کاربر نمونه (قالب)"), callback_data=f"adm_panel_server_template:{server['id']}")],
    ]
    if server["panel_type"] in INBOUND_SELECT_PANEL_TYPES:
        rows.append([InlineKeyboardButton(
            text=tr("🔗 تغییر لینک Subscription"), callback_data=f"adm_panel_server_suburl:{server['id']}",
        )])
    if server["panel_type"] == "3xui":
        rows += [
            [InlineKeyboardButton(text=tr("➕ ساخت Inbound جدید"), callback_data=f"adm_xui_inb_new:{server['id']}")],
            [InlineKeyboardButton(text=tr("💾 بکاپ پنل"), callback_data=f"adm_panel_server_backup:{server['id']}")],
            [InlineKeyboardButton(text=tr("♻️ بازیابی پنل از بکاپ"), callback_data=f"adm_panel_server_restore:{server['id']}")],
            [InlineKeyboardButton(text=tr("📊 آمار کامل پنل"), callback_data=f"adm_panel_server_stats:{server['id']}")],
        ]
    proxy_text = f"🧦 پروکسی ساکس: {'فعال' if server['socks_proxy'] else 'خاموش'}"
    rows += [
        [InlineKeyboardButton(text=proxy_text, callback_data=f"adm_panel_server_socks:{server['id']}")],
        [InlineKeyboardButton(text=custom_text, callback_data=f"adm_panel_server_usage:custom:{server['id']}")],
        [InlineKeyboardButton(text=test_text, callback_data=f"adm_panel_server_usage:test:{server['id']}")],
        [InlineKeyboardButton(text=reseller_text, callback_data=f"adm_panel_server_usage:reseller:{server['id']}")],
        [InlineKeyboardButton(text=tr(f"📍 مقصد انتقال: {'🟢 فعال' if server['allow_transfer_target'] else '🔴 خاموش'}"), callback_data=f"adm_panel_server_transfer_target:{server['id']}")],
        [InlineKeyboardButton(text=tr(f"💰 هزینه تغییر لوکیشن: {int(server['transfer_price'] or 0):,} تومان"), callback_data=f"adm_panel_server_transfer:{server['id']}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_panel_server_toggle:{server['id']}")],
        [InlineKeyboardButton(text=tr("🗑 حذف سرور"), callback_data=f"adm_panel_server_delete:{server['id']}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_panel_servers")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def xui_inbound_protocol_kb(server_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="VLESS", callback_data="adm_xui_inb_proto:vless"),
         InlineKeyboardButton(text="VMess", callback_data="adm_xui_inb_proto:vmess")],
        [InlineKeyboardButton(text="Trojan", callback_data="adm_xui_inb_proto:trojan"),
         InlineKeyboardButton(text="Shadowsocks", callback_data="adm_xui_inb_proto:shadowsocks")],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"adm_panel_server_view:{server_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def xui_inbound_network_kb(server_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="TCP", callback_data="adm_xui_inb_net:tcp"),
         InlineKeyboardButton(text="WebSocket", callback_data="adm_xui_inb_net:ws")],
        [InlineKeyboardButton(text="gRPC", callback_data="adm_xui_inb_net:grpc"),
         InlineKeyboardButton(text="HTTPUpgrade", callback_data="adm_xui_inb_net:httpupgrade")],
        [InlineKeyboardButton(text="H2", callback_data="adm_xui_inb_net:h2")],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"adm_panel_server_view:{server_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def xui_inbound_tls_kb(server_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔒 TLS", callback_data="adm_xui_inb_tls:1"),
         InlineKeyboardButton(text=tr("🔓 بدون TLS"), callback_data="adm_xui_inb_tls:0")],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"adm_panel_server_view:{server_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_server_delete_confirm_kb(server_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("⚠️ بله، همه چیز حذف شود"), callback_data=f"adm_panel_server_delete_force:{server_id}")],
        [InlineKeyboardButton(text=tr("⬅️ انصراف"), callback_data=f"adm_panel_server_view:{server_id}")],
    ])


def pricing_tiers_kb(db) -> InlineKeyboardMarkup:
    tiers = db.get_pricing_tiers()
    rows = []
    for t in tiers:
        to_label = f"{t['to_gb']}" if t["to_gb"] is not None else "∞"
        rows.append([InlineKeyboardButton(
            text=tr(f"{t['from_gb']} تا {to_label} گیگ ← {t['price_per_gb']:,} تومان/گیگ  🗑"),
            callback_data=f"adm_pricing_tier_delete:{t['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن بازه‌ی قیمت"), callback_data="adm_pricing_tier_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_custom_config_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# کیف پول
# ---------------------------------------------------------------------------

def wallet_menu_kb(db=None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("➕ شارژ کیف پول"), callback_data="start_topup")],
        [InlineKeyboardButton(text=tr("🎁 استفاده از گیفت‌کد"), callback_data="wallet_gift_code")],
    ]
    if db is None or db.get_setting("wallet_show_transfer", "1") == "1":
        rows.append([InlineKeyboardButton(text=tr("💸 انتقال موجودی به کاربر دیگر"), callback_data="wallet_transfer")])
    if db is None or db.get_setting("score_enabled", "1") == "1":
        rows.append([InlineKeyboardButton(text=tr("🪙 سکه‌های من"), callback_data="coins_menu")])
    rows.append([InlineKeyboardButton(text=tr("📜 تاریخچه تراکنش‌ها"), callback_data="wallet_history")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def coins_menu_kb(mode: str, can_convert: bool) -> InlineKeyboardMarkup:
    rows = []
    if mode == "lottery":
        rows.append([InlineKeyboardButton(text=tr("🔁 تغییر به: تبدیل به کیف پول"), callback_data="coins_mode:wallet")])
    else:
        rows.append([InlineKeyboardButton(text=tr("🔁 تغییر به: شرکت در قرعه‌کشی"), callback_data="coins_mode:lottery")])
        if can_convert:
            rows.append([InlineKeyboardButton(text=tr("💰 تبدیل سکه به موجودی"), callback_data="coins_convert")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="coins_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_gift_codes_kb(codes) -> InlineKeyboardMarkup:
    rows = []
    for c in codes:
        state_icon = "🟢" if c["is_active"] else "🔴"
        exp = str(c["expires_at"])[:16].replace("T", " ") if c["expires_at"] else "بدون انقضا"
        rows.append([InlineKeyboardButton(text=tr(f"{state_icon} #{c['id']} | {c['amount']:,}ت | {c['used_count']}/{c['max_uses']} | {exp}"), callback_data="noop")])
        rows.append([
            InlineKeyboardButton(text=tr("تغییر وضعیت"), callback_data=f"adm_gift_toggle:{c['id']}"),
            InlineKeyboardButton(text=tr("🗑 حذف"), callback_data=f"adm_gift_del:{c['id']}"),
        ])
    rows.append([InlineKeyboardButton(text=tr("➕ ساخت گیفت‌کد"), callback_data="adm_gift_add")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_discounts_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_review_kb(topup_id) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=tr("✅ تایید و شارژ کیف پول"), callback_data=f"topup_approve:{topup_id}"),
            InlineKeyboardButton(text=tr("❌ رد کردن"), callback_data=f"topup_reject:{topup_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# مدیریت بات‌های نمایندگی (فقط در بات اصلی)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# درخواست خودکار نمایندگی سطح ۲
# ---------------------------------------------------------------------------

def reseller_request_bot_choice_kb(options=None) -> InlineKeyboardMarkup:
    all_buttons = {
        "dedicated": InlineKeyboardButton(text=tr("🤖 بات مستقل با توکن خودم"), callback_data="resreq_bot:dedicated"),
        "inline_link": InlineKeyboardButton(text=tr("🔗 لینک اختصاصی داخل بات اصلی"), callback_data="resreq_bot:inline_link"),
        "none": InlineKeyboardButton(text=tr("🚫 ندارم"), callback_data="resreq_bot:none"),
    }
    options = options or list(all_buttons.keys())
    return InlineKeyboardMarkup(inline_keyboard=[[all_buttons[o]] for o in options if o in all_buttons])


def reseller_request_web_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ بله، پنل وب می‌خواهم"), callback_data="resreq_webpanel:1")],
        [InlineKeyboardButton(text=tr("❌ نه"), callback_data="resreq_webpanel:0")],
    ])


def reseller_request_miniapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ بله، مینی‌اپ می‌خواهم"), callback_data="resreq_miniapp:1")],
        [InlineKeyboardButton(text=tr("❌ نه"), callback_data="resreq_miniapp:0")],
    ])


def reseller_request_supply_model_kb(options=None) -> InlineKeyboardMarkup:
    all_buttons = {
        "volume_credit": InlineKeyboardButton(text=tr("📦 اعتبار حجمی (گیگابایت) برای ساخت آزاد"), callback_data="resreq_supply:volume_credit"),
        "fixed_product": InlineKeyboardButton(text=tr("🛒 محصول آماده با تعداد مشخص"), callback_data="resreq_supply:fixed_product"),
    }
    options = options or list(all_buttons.keys())
    return InlineKeyboardMarkup(inline_keyboard=[[all_buttons[o]] for o in options if o in all_buttons])


def reseller_request_supply_product_kb(products) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        rows.append([InlineKeyboardButton(text=f"🛒 {p['name']}", callback_data=f"resreq_supplyprod:{p['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_request_review_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ تایید و تعیین هزینه"), callback_data=f"resreq_approve:{request_id}")],
        [InlineKeyboardButton(text=tr("❌ رد درخواست"), callback_data=f"resreq_reject:{request_id}")],
    ])


def reseller_membership_tiers_kb(tiers) -> InlineKeyboardMarkup:
    rows = []
    for t in tiers:
        fee = int(t["membership_fee_toman"] or 0)
        days = t["duration_days"]
        duration = "دائمی" if days is None else f"{days} روز"
        cap = int(t["credit_limit_toman"] or 0)
        cap_text = f" | سقف اعتبار {cap:,}" if cap else ""
        rows.append([InlineKeyboardButton(
            text=tr(f"{t['icon']} {t['title']} | {fee:,} تومان | {duration}{cap_text}"),
            callback_data=f"adm_rmem_edit:{t['code']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:resellers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commission_resellers_menu_kb(pending_count: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=tr(f"📋 درخواست‌های در انتظار ({pending_count})"), callback_data="adm_comres_pending",
        )],
        [InlineKeyboardButton(text=tr("📊 لیست نماینده‌های فعال"), callback_data="adm_comres_active")],
        [InlineKeyboardButton(text=tr("➕ ساخت مستقیم نماینده جدید"), callback_data="adm_comres_direct_new")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:resellers")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commission_resellers_pending_kb(requests) -> InlineKeyboardMarkup:
    rows = []
    for r in requests:
        rows.append([InlineKeyboardButton(
            text=tr(f"#{r['id']} — کاربر {r['user_id']} — {r['proposed_percent']}٪"),
            callback_data=f"comres_view:{r['id']}",
        )])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_commission_resellers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commission_reseller_active_kb(resellers) -> InlineKeyboardMarkup:
    rows = []
    for r in resellers:
        label = f"👤 {r['telegram_id']} — {r['percent']}٪ — {r['customers']} مشتری"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"comres_view_active:{r['telegram_id']}")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_commission_resellers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commission_reseller_active_view_kb(user_tg_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("✏️ تغییر درصد کمیسیون"), callback_data=f"comres_edit:{user_tg_id}")],
        [InlineKeyboardButton(text=tr("⛔️ غیرفعال‌سازی نمایندگی"), callback_data=f"comres_disable:{user_tg_id}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_comres_active")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commission_reseller_request_review_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ تایید"), callback_data=f"comres_approve:{request_id}")],
        [InlineKeyboardButton(text=tr("❌ رد درخواست"), callback_data=f"comres_reject:{request_id}")],
    ])


def reseller_request_accept_percent_kb(percent) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(f"✅ قبول پیشنهاد کاربر ({percent}٪)"), callback_data="rrpct:accept")],
    ])


def reseller_request_payment_methods_kb(items, selected) -> InlineKeyboardMarkup:
    """انتخاب چندگانه‌ی روش‌های پرداخت هزینه نمایندگی توسط ادمین؛ items: [(key, label), ...]."""
    rows = []
    for i, (key, label) in enumerate(items):
        mark = "✅" if key in selected else "⬜️"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"rrpm:t:{i}")])
    rows.append([InlineKeyboardButton(text=tr("📨 تایید و ارسال به کاربر"), callback_data="rrpm:ok")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_request_panel_pick_kb(request_id, panels) -> InlineKeyboardMarkup:
    rows = []
    for p in panels:
        rows.append([InlineKeyboardButton(text=f"🖥 {p['name']}", callback_data=f"resreq_panel:{request_id}:{p['id']}")])
    rows.append([InlineKeyboardButton(text=tr("↩️ خودکار (اولین پنل فعالِ نمایندگی)"), callback_data=f"resreq_panel:{request_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_owner_id_confirm_kb() -> InlineKeyboardMarkup:
    """تایید آیدی عددی مالک قبل از ثبت نهایی بات نمایندگی (رفع باگ: قبلاً هر
    عددی که کاربر تایپ می‌کرد بدون هیچ تاییدی به‌عنوان مالک/گیرنده‌ی اعتبار
    نمایندگی ثبت می‌شد و یک اشتباه تایپی قابل جبران نبود)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ بله، همین آیدی درست است"), callback_data="resreq_ownerok")],
        [InlineKeyboardButton(text=tr("✏️ نه، دوباره وارد می‌کنم"), callback_data="resreq_ownerretry")],
    ])


def reseller_owner_external_confirm_kb(request_id) -> InlineKeyboardMarkup:
    """رفع باگ امنیتی: تاییدِ نهاییِ مالکیتِ نمایندگی وقتی آیدیِ وارد‌شده با
    درخواست‌دهنده فرق دارد، دیگر با کلیکِ خودِ درخواست‌دهنده انجام نمی‌شود؛ این دکمه
    مستقیماً در چتِ خودِ آیدیِ نامزدشده فرستاده می‌شود و فقط خودش می‌تواند بزندش."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ تایید می‌کنم، مالک این نمایندگی باشم"), callback_data=f"resreq_ownerx_ok:{request_id}")],
        [InlineKeyboardButton(text=tr("❌ نه، قبول نمی‌کنم"), callback_data=f"resreq_ownerx_no:{request_id}")],
    ])


def reseller_request_owner_wait_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("❌ انصراف از درخواست"), callback_data=f"resreq_cancel:{request_id}")],
    ])


def reseller_request_pay_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ پرداخت می‌کنم"), callback_data=f"resreq_pay:{request_id}")],
        [InlineKeyboardButton(text=tr("❌ انصراف"), callback_data=f"resreq_cancel:{request_id}")],
    ])


def reseller_request_payment_review_kb(request_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr("✅ تایید پرداخت"), callback_data=f"resreq_payok:{request_id}")],
        [InlineKeyboardButton(text=tr("❌ رد پرداخت"), callback_data=f"resreq_payreject:{request_id}")],
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
                text=tr(f"#{r['id']} | {label} | کاربر {r['user_id']} | {r['volume_gb']:,} گیگ"),
                callback_data="noop",
            )
        ])
        rows.append([
            InlineKeyboardButton(text=tr("🛑 کنسل دستی"), callback_data=f"resreq_admin_cancel:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton(text=tr("🔄 بروزرسانی"), callback_data="adm_reseller_requests_menu")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def orphan_db_files_kb(filenames) -> InlineKeyboardMarkup:
    """لیست فایل‌های دیتابیس یتیم (بدون رکورد نماینده‌ی مرتبط) با دکمه‌ی حذف."""
    import urllib.parse
    rows = []
    for fname in filenames:
        rows.append([InlineKeyboardButton(text=f"🗃 {fname}", callback_data="noop")])
        rows.append([
            InlineKeyboardButton(
                text=tr("🗑 حذف این فایل"),
                callback_data=f"adm_orphan_db_del:{urllib.parse.quote(fname, safe='')}",
            )
        ])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_resellers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resbot_del_confirm_kb(bot_id) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr("🗑 فقط حذف (دیتابیس نگه داشته شود)"), callback_data=f"adm_resbot_delc:{bot_id}:0")],
        [InlineKeyboardButton(text=tr("🗑💥 حذف + پاک‌کردن دیتابیس"), callback_data=f"adm_resbot_delc:{bot_id}:1")],
        [InlineKeyboardButton(text=tr("انصراف"), callback_data="adm_resellers_menu")],
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
                InlineKeyboardButton(text=tr("تغییر وضعیت"), callback_data=f"adm_resbot_toggle:{r['id']}"),
                InlineKeyboardButton(text=tr("🗑حذف"), callback_data=f"adm_resbot_del:{r['id']}"),
            ]
        )
        # پنل وب برای هر دو سطح قابل فعال‌سازی است؛ سطح ۲ هم ممکن است
        # پنل وب اختصاصی بخواهد (دسترسی‌ها در خود پنل با tenant/level محدود می‌شوند).
        web_panel_enabled = bool(r["web_panel_enabled"]) if "web_panel_enabled" in r.keys() else False
        wp_label = "🌐 پنل وب: فعال (مدیریت)" if web_panel_enabled else "🌐 فعالسازی پنل وب"
        rows.append(
            [InlineKeyboardButton(text=wp_label, callback_data=f"adm_resbot_webpanel:{r['id']}")]
        )
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن بات نمایندگی جدید"), callback_data="adm_resbot_add")])
    rows.append([InlineKeyboardButton(text=tr("⚙️ آدرس پنل مدیریت وب"), callback_data="adm_set_panel_domain")])
    rows.append([InlineKeyboardButton(text=tr("🧹 پاکسازی داده‌های باقی‌مانده نمایندگی"), callback_data="adm_reseller_orphans")])
    rows.append([InlineKeyboardButton(text=tr("🗃 پاکسازی فایل‌های دیتابیس یتیم"), callback_data="adm_orphan_db_files")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:resellers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resbot_webpanel_kb(bot_id) -> InlineKeyboardMarkup:
    """منوی مدیریت پنل وب یک نماینده‌ی کامل: بعد از فعال‌سازی نشان داده می‌شود."""
    rows = [
        [InlineKeyboardButton(text=tr("🔗 لینک ورود پنل وب"), callback_data=f"adm_resbot_webpanel_loginlink:{bot_id}")],
        [InlineKeyboardButton(text=tr("🔁 ساخت لینک راه‌اندازی جدید"), callback_data=f"adm_resbot_webpanel_regen:{bot_id}")],
        [InlineKeyboardButton(text=tr("⛔️ غیرفعال‌سازی پنل وب"), callback_data=f"adm_resbot_webpanel_off:{bot_id}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_resellers_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_orphans_kb(rows_data) -> InlineKeyboardMarkup:
    rows = []
    for r in rows_data:
        name = r["first_name"] or r["username"] or str(r["telegram_id"])
        rows.append([InlineKeyboardButton(text=f"👤 {name} ({r['telegram_id']})", callback_data="noop")])
        rows.append([
            InlineKeyboardButton(
                text=tr("🧹 پاکسازی کامل این کاربر"),
                callback_data=f"adm_reseller_orphan_purge:{r['telegram_id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_resellers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_resellers_menu_kb(resellers) -> InlineKeyboardMarkup:
    rows = []
    for r in resellers:
        label = f"👤 {r['telegram_id']} - {r['reseller_credit_gb']:,} گیگ"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm_cres_view:{r['telegram_id']}")])
    rows.append([InlineKeyboardButton(text=tr("➕ افزودن/جستجوی نماینده"), callback_data="adm_cres_find")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_cat:resellers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_reseller_view_kb(user_tg_id: int, is_reseller: bool) -> InlineKeyboardMarkup:
    toggle_text = "⛔️ لغو نمایندگی" if is_reseller else "✅ تبدیل به نماینده"
    rows = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm_cres_toggle:{user_tg_id}")],
        [InlineKeyboardButton(text=tr("➕/➖ تغییر اعتبار (گیگ)"), callback_data=f"adm_cres_credit:{user_tg_id}")],
        [InlineKeyboardButton(text=tr("💳 سقف اعتبار پس‌پرداخت (تومان)"), callback_data=f"adm_cres_limit:{user_tg_id}")],
        [InlineKeyboardButton(text=tr("📜 لاگ کیف پول"), callback_data=f"adm_cres_wlog:{user_tg_id}")],
        [InlineKeyboardButton(text=tr("🔗 تعیین پنل اختصاصی"), callback_data=f"adm_cres_panel:{user_tg_id}")],
        [InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data="adm_credit_resellers_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_reseller_panel_pick_kb(user_tg_id: int, panels) -> InlineKeyboardMarkup:
    rows = []
    for p in panels:
        rows.append([InlineKeyboardButton(text=f"🖥 {p['name']}", callback_data=f"adm_cres_panel_set:{user_tg_id}:{p['id']}")])
    rows.append([InlineKeyboardButton(text=tr("↩️ خودکار (اولین پنل فعالِ نمایندگی)"), callback_data=f"adm_cres_panel_set:{user_tg_id}:0")])
    rows.append([InlineKeyboardButton(text=tr("⬅️ بازگشت"), callback_data=f"adm_cres_view:{user_tg_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
