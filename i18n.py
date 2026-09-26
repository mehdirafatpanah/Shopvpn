# -*- coding: utf-8 -*-
"""Bilingual UI support (Persian/English).

The active language is kept in a ContextVar so every Telegram update can use
its own language safely, including calls executed through asyncio.to_thread().
"""
from contextvars import ContextVar
from typing import Optional

SUPPORTED_LANGUAGES = ("fa", "en")
DEFAULT_LANGUAGE = "fa"
PARTIAL_MAX_RATIO = float(__import__("os").getenv("SHOPVPN_TRANSLATION_PARTIAL_RATIO", "0.05"))

# Built-in language metadata. Persian/English keep their existing behavior;
# additional languages are enabled per bot/tenant in the database and translated
# automatically on activation.
LANGUAGE_CATALOG = {
    "fa": {"name": "Persian", "native_name": "فارسی", "flag": "🇮🇷", "rtl": True},
    "en": {"name": "English", "native_name": "English", "flag": "🇬🇧", "rtl": False},
    "tr": {"name": "Turkish", "native_name": "Türkçe", "flag": "🇹🇷", "rtl": False},
    "ar": {"name": "Arabic", "native_name": "العربية", "flag": "🇸🇦", "rtl": True},
    "ru": {"name": "Russian", "native_name": "Русский", "flag": "🇷🇺", "rtl": False},
    "de": {"name": "German", "native_name": "Deutsch", "flag": "🇩🇪", "rtl": False},
    "fr": {"name": "French", "native_name": "Français", "flag": "🇫🇷", "rtl": False},
    "es": {"name": "Spanish", "native_name": "Español", "flag": "🇪🇸", "rtl": False},
    "it": {"name": "Italian", "native_name": "Italiano", "flag": "🇮🇹", "rtl": False},
    "pt": {"name": "Portuguese", "native_name": "Português", "flag": "🇵🇹", "rtl": False},
    "zh": {"name": "Chinese", "native_name": "中文", "flag": "🇨🇳", "rtl": False},
    "ja": {"name": "Japanese", "native_name": "日本語", "flag": "🇯🇵", "rtl": False},
    "ko": {"name": "Korean", "native_name": "한국어", "flag": "🇰🇷", "rtl": False},
    "nl": {"name": "Dutch", "native_name": "Nederlands", "flag": "🇳🇱", "rtl": False},
    "pl": {"name": "Polish", "native_name": "Polski", "flag": "🇵🇱", "rtl": False},
    "uk": {"name": "Ukrainian", "native_name": "Українська", "flag": "🇺🇦", "rtl": False},
}


_current_language = ContextVar("shopvpn_language", default=DEFAULT_LANGUAGE)
_current_catalog = ContextVar("shopvpn_language_catalog", default={})

# Per-update buffer of source (English) strings that tr() looked up but could
# not find in the active dynamic-language catalog. LanguageMiddleware starts a
# fresh buffer for every Telegram update whose language is dynamic; the bot
# layer (see bot_manager.TranslatingBot) drains it right before each outgoing
# request is actually sent, translates exactly those strings on the spot, and
# patches them into the request so no untranslated fallback is ever shown to
# the user. See translation_engine.translate_texts_now.
_missing_lookups: ContextVar[Optional[list]] = ContextVar("shopvpn_missing_lookups", default=None)


def start_missing_tracking():
    """Begin collecting untranslated lookups for the current context/update."""
    return _missing_lookups.set([])


def stop_missing_tracking(token) -> None:
    _missing_lookups.reset(token)


def note_missing(text: str) -> None:
    lookups = _missing_lookups.get()
    if lookups is not None and text and text not in lookups:
        lookups.append(text)


def pop_missing_lookups() -> list:
    """Return and clear whatever untranslated lookups were collected so far."""
    lookups = _missing_lookups.get()
    if not lookups:
        return []
    out = list(lookups)
    lookups.clear()
    return out


def merge_language_catalog(mapping: dict) -> None:
    """Fold freshly generated translations into the active per-context catalog
    so any further tr() calls in the same update see them immediately."""
    if not mapping:
        return
    catalog = dict(_current_catalog.get())
    catalog.update(mapping)
    _current_catalog.set(catalog)

# High-frequency UI phrases. Unknown/custom text intentionally falls back to the
# original text so existing installations keep working without data loss.
_TRANSLATIONS = {
    "fa": {},
    "en": {
        "🛒 خرید کانفیگ": "🛒 Buy configuration",
        "🧪 کانفیگ تست رایگان": "🧪 Free test configuration",
        "🧾 حساب کاربری من": "🧾 My account",
        "🤝 زیرمجموعه‌گیری من": "🤝 My referrals",
        "🎡 گردونه شانس": "🎡 Lucky wheel",
        "📚 آموزش": "📚 Tutorials",
        "📞 ارتباط با پشتیبانی": "📞 Contact support",
        "⚙️ پنل مدیریت": "⚙️ Admin panel",
        "🧑‍💼 پنل نمایندگی": "🧑‍💼 Reseller panel",
        "🤝 نمایندگی": "🤝 Reseller",
        "💰 کیف پول": "💰 Wallet",
        "✨ مینی‌اپ فروشگاه": "✨ Store mini app",
        "🌐 زبان / Language": "🌐 Language / زبان",
        "زبان": "Language",
        "فارسی": "Persian",
        "English": "English",
        "🇮🇷 فارسی": "🇮🇷 Persian",
        "🇬🇧 English": "🇬🇧 English",
        "زبان با موفقیت تغییر کرد.": "Language changed successfully.",
        "زبان انتخاب شد.": "Language selected.",
        "لطفاً زبان موردنظر را انتخاب کنید:": "Please choose your language:",
        "برای ورود به مینی‌اپ فروشگاه، روی دکمه‌ی زیر بزن:": "Tap the button below to open the store mini app.",
        "در حال حاضر امکان دریافت کانفیگ تست غیرفعال است.": "Free test configuration is currently disabled.",
        "فعلاً آموزشی ثبت نشده.": "No tutorials have been added yet.",
        "چطور می‌خواهید با پشتیبانی در ارتباط باشید؟": "How would you like to contact support?",
        "سرویس یافت نشد.": "Service not found.",
        "گزارش ثبت شد": "Report submitted.",
        "⛔️ محصول موردنظر یافت نشد یا دیگر فعال نیست.": "⛔️ The requested product was not found or is no longer active.",
        "⛔️ در حال حاضر موجودی این محصول تمام شده است.": "⛔️ This product is currently out of stock.",
        "⚠️ خطایی رخ داد، دوباره تلاش کنید.": "⚠️ Something went wrong. Please try again.",
        "در حال پردازش...": "Processing...",
        "لغو": "Cancel",
        "تایید": "Confirm",
        "بازگشت": "Back",
        "بله": "Yes",
        "خیر": "No",
        "بستن": "Close",
        "ذخیره": "Save",
        "حذف": "Delete",
        "ویرایش": "Edit",
        "جستجو": "Search",
        "صفحه بعد": "Next page",
        "صفحه قبل": "Previous page",
        "هیچ موردی یافت نشد.": "No items found.",
        "خطای ناشناخته": "Unknown error",
        "عملیات با موفقیت انجام شد.": "Operation completed successfully.",
        "لطفاً دوباره تلاش کنید.": "Please try again.",
        "کاربر": "User",
        "سفارش": "Order",
        "پرداخت": "Payment",
        "موجودی": "Balance",
        "پشتیبانی": "Support",
        "تنظیمات": "Settings",
        "مدیریت": "Administration",
        "داشبورد": "Dashboard",
    },
}

# General-purpose fallback catalog for legacy UI strings.  The project has a large
# amount of text assembled dynamically; keeping a lexical fallback here means
# older/newer handlers are bilingual even when their exact sentence is not in
# the hand-curated catalog above.

# Common complete UI phrases. These take precedence over the lexical fallback and
# keep the English copy natural for the most frequently displayed flows.
_PHRASE_TRANSLATIONS = {
    "در حال بررسی...": "Checking...",
    "در حال دریافت...": "Loading...",
    "در حال دریافت آمار...": "Loading statistics...",
    "در حال پردازش...": "Processing...",
    "در حال تست اتصال...": "Testing connection...",
    "در حال ارسال...": "Sending...",
    "در حال بازیابی...": "Restoring...",
    "در حال بازیابی کامل...": "Restoring everything...",
    "در حال گرفتن بکاپ...": "Creating backup...",
    "در حال ساخت بکاپ کامل...": "Creating full backup...",
    "نام دسته‌بندی جدید را ارسال کنید:": "Enter the new category name:",
    "نام محصول را ارسال کنید:": "Enter the product name:",
    "توضیحات محصول را وارد کنید (یا برای رد شدن بنویسید: -)": "Enter the product description (or send - to skip):",
    "قیمت محصول را به تومان و فقط عدد وارد کنید (مثال: 150000):": "Enter the product price in Toman using numbers only (e.g. 150000):",
    "مدت اعتبار این سرویس چند روز است؟ فقط عدد وارد کنید": "How many days should this service remain valid? Enter a number only:",
    "این محصول چند گیگابایت باشد؟ فقط عدد وارد کنید": "How many gigabytes should this product include? Enter a number only:",
    "این محصول به کدام پنل وصل شود؟": "Which panel should this product use?",
    "نوع پنل را انتخاب کن:": "Select the panel type:",
    "آدرس API پنل را بفرست": "Enter the panel API URL:",
    "آدرس پایه‌ی Subscription پنل را بفرست": "Enter the panel's base subscription URL:",
    "لطفاً زبان موردنظر را انتخاب کنید:": "Please choose your language:",
    "زبان با موفقیت تغییر کرد.": "Language changed successfully.",
    "این روش ارتباطی در حال حاضر غیرفعال است.": "This contact method is currently disabled.",
    "سرویس یافت نشد.": "Service not found.",
    "تیکت یافت نشد.": "Ticket not found.",
    "❌ درخواست نامعتبر است.": "❌ Invalid request.",
    "❌ ثبت تیکت لغو شد.": "❌ Ticket creation cancelled.",
    "لطفاً موضوع تیکت را به‌صورت متن ارسال کنید:": "Please send the ticket subject as text:",
    "متن کامل پیام خود را ارسال کنید:": "Please send the full message:",
    "لطفاً متن پیام را به‌صورت نوشتاری ارسال کنید:": "Please send the message as text:",
    "گزارش ثبت شد": "Report submitted.",
    "درخواست رد شد.": "Request rejected.",
    "ذخیره شد": "Saved.",
    "حذف شد.": "Deleted.",
    "تغییر کرد.": "Updated.",
    "به‌روزرسانی شد.": "Updated.",
    "عملیات با موفقیت انجام شد.": "Operation completed successfully.",
    "لطفاً دوباره تلاش کنید.": "Please try again.",
    "هیچ موردی یافت نشد.": "No items found.",
    "نامعتبر": "Invalid",
    "در دسترس نیست": "Unavailable",
    "فعال نیست": "Disabled",
    "غیرفعال است": "Disabled",
    "فعال است": "Enabled",
}

_PHRASE_TRANSLATIONS.update({
    "کانال حذف شد.": "Channel deleted.",
    "پاکسازی F147 انجام شد.": "F147 cleanup completed.",
    "حالت خرید کمتر از حداقل تغییر کرد.": "The below-minimum purchase mode was updated.",
    "منوی پس‌زمینه QR:": "QR background menu:",
    "✅ مرحله اضافه شد.": "✅ Step added.",
    "در حال اعمال تغییرات...": "Applying changes...",
    "❌ مبلغ بیش از حد مجاز است.": "❌ The amount exceeds the allowed limit.",
    "کاربری با این فیلترها پیدا نشد.": "No user matched these filters.",
    "❌ متن اعلان خالی است.": "❌ The announcement text cannot be empty.",
    "❌ آیدی کانال معتبر نیست.": "❌ The channel ID is invalid.",
    "هنوز تصویری آپلود نشده.": "No image has been uploaded yet.",
    "چیزی برای حذف وجود نداشت.": "There was nothing to delete.",
    "عملیات شروع شد.": "Operation started.",
    "حجم یا زمان هدیه را مشخص کن.": "Specify the gift volume or duration.",
    "یک پنل یا چند کاربر را انتخاب کن.": "Select one panel or multiple users.",
    "هیچ سرویس فعالی برای این هدف پیدا نشد.": "No active service was found for this target.",
    "شناسه نامعتبر": "Invalid ID",
    "❌ مقدار خالی است.": "❌ The value cannot be empty.",
    "فاکتور یافت نشد یا قبلاً حذف شده.": "The invoice was not found or has already been deleted.",
    "درخواست نامعتبر.": "Invalid request.",
    "داده نامعتبر.": "Invalid data.",
    "فاکتور یافت نشد.": "Invoice not found.",
    "درگاه نامعتبر.": "Invalid payment gateway.",
    "هنوز عضو کانال نشده‌اید.": "You have not joined the channel yet.",
    "دسترسی نداری.": "You do not have access.",
    "فعلاً آموزشی برای این بخش ثبت نشده.": "No tutorial has been added for this section yet.",
    "سیستم سکه در حال حاضر غیرفعال است.": "The coin system is currently disabled.",
    "در حال حاضر امکان تبدیل سکه وجود ندارد.": "Coin conversion is currently unavailable.",
    "📚 یک آموزش را انتخاب کنید:": "📚 Select a tutorial:",
    "⬜ کیوآر کانفیگ شما": "⬜ Your configuration QR code",
    "این روش پرداخت در حال حاضر در دسترس نیست.": "This payment method is currently unavailable.",
    "⏳ هنوز پرداختی برای این فاکتور تایید نشده.": "⏳ No payment has been confirmed for this invoice yet.",
    "✅ این پرداخت قبلاً تایید و تحویل داده شده است.": "✅ This payment has already been confirmed and delivered.",
    "❌ اعتبار این فاکتور تمام شده یا لغو شده است.": "❌ This invoice has expired or been cancelled.",
    "❌ اعتبار این فاکتور تمام شده یا لغو شده. لطفاً دوباره از منو اقدام کن.": "❌ This invoice has expired or been cancelled. Please start again from the menu.",
    "فاکتور لغو و حذف شد.": "Invoice cancelled and deleted.",
    "✅ فاکتور لغو و حذف شد.": "✅ Invoice cancelled and deleted.",
    "به‌روزرسانی شد.": "Updated.",
    "❌ یک عدد معتبر (بزرگ‌تر از صفر) بفرست.": "❌ Enter a valid number greater than zero.",
    "⚠️ MINIAPP_URL روی سرور تنظیم نشده است.": "⚠️ MINIAPP_URL is not configured on the server.",
    "❌ درخواست منقضی شد؛ دوباره از منو اقدام کن.": "❌ The request expired; please start again from the menu.",
    "🔧 پنل مدیریت:": "🔧 Admin panel:",
    "📋 منو:": "📋 Menu:",
    "🔄 کانفیگ با موفقیت به‌صورت خودکار تمدید شد.": "🔄 The configuration was automatically renewed successfully.",
    "عملیات با موفقیت انجام شد.": "Operation completed successfully.",
})

_PHRASE_TRANSLATIONS.update({
    "⚠️ سفارش یافت نشد.": "⚠️ Order not found.",
    "✅ این سفارش قبلاً بررسی و تحویل داده شده است.": "✅ This order has already been reviewed and delivered.",
    "⛔️ خطای غیرمنتظره‌ای در تمدید رخ داد. سفارش برای بررسی دوباره آزاد شد؛ با پشتیبانی تماس بگیرید.": "⛔️ An unexpected renewal error occurred. The order was released for review; please contact support.",
    "⛔️ سرور مربوط به کانفیگ شخصی یافت نشد؛ با پشتیبانی تماس بگیرید.": "⛔️ The panel server for the personal configuration was not found; please contact support.",
    "⚠️ پرداخت تایید شد ولی موجودی هم‌زمان تمام شده؛ ادمین به‌زودی دستی رسیدگی می‌کند.": "⚠️ Payment was confirmed, but the stock ran out at the same time; an admin will handle it manually soon.",
    "✅ پرداخت تایید شد و کانفیگ تحویل داده شد.": "✅ Payment confirmed and configuration delivered.",
    "⚠️ درخواست شارژ یافت نشد.": "⚠️ Top-up request not found.",
    "✅ این درخواست شارژ قبلاً بررسی شده است.": "✅ This top-up request has already been reviewed.",
    "ℹ️ در حال حاضر محاسبه‌ی مقدار برگشتی ممکن نیست (خطا در دریافت مصرف)؛ با حذف، چیزی برگردانده نمی‌شود.": "ℹ️ The refundable amount cannot currently be calculated (usage retrieval failed); nothing will be returned when the service is deleted.",
})
_WORD_TRANSLATIONS_EXTRA = {
    "مالک":"Owner", "مدیر":"Admin", "مدیران":"Admins", "کامل":"Full", "ربات":"Bot", "خاموش":"off", "روشن":"on",
    "تبریک":"Congratulations", "یکی":"one", "از":"from", "شما":"you", "سرویسش":"their service", "پورسانت":"commission",
    "اضافه":"added", "کافی":"enough", "نیست":"is not", "هزینه":"cost", "فقط":"only", "مثبت":"positive", "منفی":"negative",
    "بیشتر":"more", "کمتر":"less", "حد":"limit", "مجاز":"allowed", "اعلان":"announcement", "خالی":"empty", "عضویت":"membership",
    "اجباری":"required", "تشخیص":"detected", "فیش":"receipt", "فیک":"fake", "بلاک":"blocked", "رسید":"receipt", "ارسالی":"submitted",
    "تایید":"confirmed", "تأیید":"confirmed", "موضوع":"subject", "با":"with", "در":"in", "ارتباط":"contact", "تماس":"contact",
    "متاسفانه":"Unfortunately", "متأسفانه":"Unfortunately", "هنوز":"still", "قبلاً":"already", "تمام":"expired", "تمام شده":"expired",
    "لغو":"cancel", "لغو شد":"cancelled", "تصویر":"image", "عکس":"photo", "فایل":"file", "متن":"text", "ویدیو":"video",
    "ارسال":"send", "بفرست":"send", "بفرستید":"send", "کن":"do", "کنید":"do", "باید":"must", "همان":"the same",
    "پسوند":"extension", "دوباره":"again", "بررسی":"check", "مطمئن":"sure", "شوید":"make sure", "مرحله":"step", "پس‌زمینه":"background",
    "ساخت":"creation", "پیش‌نمایش":"preview", "ناموفق":"failed", "پردازش":"processing", "سالم":"valid", "ابعاد":"dimensions", "کوچک":"small",
    "بزرگ":"large", "پیشنهاد":"recommended", "ذخیره":"save", "فعال":"enabled", "غیرفعال":"disabled", "کاربر":"user", "کاربران":"users",
    "عادی":"regular", "دسترسی":"access", "عضو":"member", "کانال":"channel", "پاکسازی":"cleanup", "تغییر":"change", "حالت":"mode",
    "خرید":"purchase", "حداقل":"minimum", "بالاتر":"higher", "پایین‌تر":"lower", "دقیقاً":"exactly", "صحیح":"integer", "بین":"between",
    "مثلاً":"for example", "مثال":"example", "آیدی":"ID", "شناسه":"ID", "عدد":"number", "عددهای":"numbers", "شماره":"number",
    "نقش":"role", "عنوان":"title", "آموزش":"tutorial", "انتخاب":"select", "ثبت":"submit", "ثبت شده":"registered", "نشده":"not done",
    "موجود":"available", "موجودی":"balance", "روش":"method", "روش‌های":"methods", "پرداختی":"payment", "تحویل":"delivery", "داده":"given",
    "حساب":"account", "کیف":"wallet", "سیستم":"system", "امکان":"ability", "تبدیل":"conversion", "سکه":"coins", "توکن":"token",
    "جدید":"new", "مصرف":"used", "ثبت‌نام":"registration", "دیگر":"another", "مورد":"item", "مرتبط":"related", "دسته‌جمعی":"in bulk",
    "مستقیم":"direct", "پنلی":"panel-based", "غیر":"non", "تست":"test", "که":"that", "بشود":"can be", "کنند":"do", "دارد":"has",
    "ندارد":"does not have", "پیدا":"found", "یافت":"found", "شد":"was", "شود":"be", "باشد":"be", "است":"is", "هست":"is",
    "درحال":"in progress", "در حال":"in progress", "مانده":"remaining", "باقی":"remaining", "خودکار":"automatic", "دستی":"manual",
}
_WORD_TRANSLATIONS = {
    "لطفاً":"Please", "لطفا":"Please", "خواهید":"would you like", "می‌خواهید":"would you like",
    "انتخاب":"Select", "انتخاب کنید":"Select", "ارسال":"Send", "ارسال کنید":"Send",
    "وارد":"Enter", "وارد کنید":"Enter", "ثبت":"Submit", "ثبت شد":"Submitted",
    "ذخیره":"Save", "ذخیره شد":"Saved", "ویرایش":"Edit", "حذف":"Delete", "بازگشت":"Back",
    "انصراف":"Cancel", "تایید":"Confirm", "تأیید":"Confirm", "بله":"Yes", "خیر":"No",
    "بستن":"Close", "جستجو":"Search", "بروزرسانی":"Update", "بازنشانی":"Reset",
    "فعال":"Enabled", "غیرفعال":"Disabled", "فعال‌سازی":"Enable", "غیرفعال‌سازی":"Disable",
    "وضعیت":"Status", "نام":"Name", "کاربر":"User", "کاربران":"Users", "ادمین":"Admin",
    "مدیریت":"Management", "تنظیمات":"Settings", "سیستم":"System", "داشبورد":"Dashboard",
    "محصول":"Product", "محصولات":"Products", "دسته‌بندی":"Category", "دسته‌بندی‌ها":"Categories",
    "سفارش":"Order", "سفارش‌ها":"Orders", "پرداخت":"Payment", "پرداخت‌ها":"Payments",
    "فاکتور":"Invoice", "فاکتورها":"Invoices", "درگاه":"Gateway", "درگاه‌ها":"Gateways",
    "کیف پول":"Wallet", "موجودی":"Balance", "شارژ":"Top-up", "تومان":"Toman", "ریال":"Rial",
    "گیگ":"GB", "گیگابایت":"GB", "مگابایت":"MB", "روز":"days", "روزها":"days", "ساعت":"hours",
    "دقیقه":"minutes", "ثانیه":"seconds", "نفر":"people", "عدد":"items", "سکه":"coins",
    "پشتیبانی":"Support", "تیکت":"Ticket", "تیکت‌ها":"Tickets", "آموزش":"Tutorials",
    "نمایندگی":"Reseller", "نماینده":"Reseller", "زیرمجموعه":"Referral", "زیرمجموعه‌گیری":"Referrals",
    "گردونه":"Wheel", "شانس":"Lucky", "تخفیف":"Discount", "کد تخفیف":"Discount code",
    "کانفیگ":"Configuration", "کانفیگ‌ها":"Configurations", "سرویس":"Service", "سرویس‌ها":"Services",
    "سرور":"Server", "سرورها":"Servers", "پنل":"Panel", "لینک":"Link", "آدرس":"Address",
    "حجم":"Volume", "مدت":"Duration", "اعتبار":"Validity", "مصرف":"Usage", "مصرف‌شده":"Used",
    "باقی‌مانده":"Remaining", "نامحدود":"Unlimited", "بدون انقضا":"No expiration", "جدید":"New",
    "تکمیل‌شده":"Completed", "منقضی‌شده":"Expired", "در انتظار":"Pending", "لغوشده":"Cancelled",
    "ناموفق":"Failed", "موفق":"Successful", "خطا":"Error", "هشدار":"Warning", "درخواست":"Request",
    "یافت نشد":"Not found", "پیدا نشد":"Not found", "نامعتبر":"Invalid", "معتبر":"Valid",
    "در حال بررسی":"Checking", "در حال پردازش":"Processing", "در حال ساخت":"Creating", "در حال آماده‌سازی":"Preparing",
    "تغییر":"Change", "تغییر کرد":"Changed", "ساخته شد":"Created", "حذف شد":"Deleted",
    "اعمال شد":"Applied", "رد شد":"Rejected", "تایید شد":"Confirmed", "تأیید شد":"Confirmed",
    "لغو شد":"Cancelled", "غیرفعال است":"is disabled", "فعال است":"is enabled", "در دسترس نیست":"is unavailable",
    "دوباره تلاش کنید":"Please try again", "تماس بگیرید":"Please contact support", "با پشتیبانی":"with support",
    "همه":"All", "هیچ":"None", "نامشخص":"Unknown", "عمومی":"General", "اختیاری":"Optional",
    "اجباری":"Required", "خودکار":"Automatic", "دستی":"Manual", "رایگان":"Free", "ویژه":"Special",
    "تست":"Test", "فروش":"Sales", "بازاریابی":"Marketing", "شبکه":"Network", "همکاران":"Partners",
}

_WORD_TRANSLATIONS.update(_WORD_TRANSLATIONS_EXTRA)



# Dynamic UI sentence translations.  These rules handle f-strings whose runtime
# values make exact phrase lookup impossible.  Placeholders are represented as
# {x} in the catalog and matched non-greedily at runtime.

_FRAGMENT_TRANSLATIONS = {
    "حالا توکن بات نمایندگی خودتان را از @BotFather ارسال کنید تا فعال‌سازی ادامه پیدا کند:": "Now send your reseller bot token from @BotFather to continue activation:",
    "درگاه «": "Gateway “", "» به شماره موبایلت نیاز داره.": "” needs your mobile number.",
    "با زدن دکمه‌ی زیر شماره‌ات رو به اشتراک بذار:": "Tap the button below to share your number:",
    "روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن.": "Tap the button below and complete the payment.",
    "به‌محض تایید پرداخت توسط درگاه، ": "As soon as the gateway confirms the payment, ",
    "به‌صورت خودکار": "automatically", "به‌صورت automatic": "automatically",
    "ساخته می‌شود": "will be created", "ساخته شد": "was created", "ایجاد شد": "was created",
    "فقط عدد ارسال کنید": "send numbers only", "فقط عدد بفرست": "send a number only",
    "حداقل مبلغ شارژ": "Minimum top-up amount", "حداکثر مبلغ قابل شارژ فعلی": "Current maximum top-up amount",
    "چه مبلغی": "What amount", "می‌خواهید به کیف پول خود شارژ کنید": "would you like to add to your wallet",
    "مثال": "Example", "مثلاً": "for example", "حداقل": "Minimum", "حداکثر": "Maximum",
    "حالا حجم مورد نظر": "Now enter the requested volume", "حجم مورد نظر": "requested volume",
    "گیگابایت": "GB", "گیگ": "GB", "مگابایت": "MB", "روز": "days", "ساعت": "hours",
    "نام کاربری": "Username", "کاربری": "user", "کاربر": "user", "کاربران": "users",
    "محصول آماده": "prepared product", "کانفیگ محصول": "product configuration", "کانفیگ": "configuration", "کانفیگ‌ها": "configurations",
    "حجم": "Volume", "مدت": "Duration", "اعتبار باقی‌مانده": "Remaining quota", "موجودی باقی‌مانده": "Remaining stock", "موجودی فعلی": "Current balance",
    "موجودی": "Balance", "کیف پول": "wallet", "حساب کاربری": "user account", "سرویس‌ها": "services", "سفارش‌های من": "my orders",
    "در حال بررسی است": "is being reviewed", "در حال بررسی": "under review", "در حال": "in progress",
    "آیا مطمئن هستید": "Are you sure", "مطمئن هستید": "are you sure", "این عملیات": "This operation",
    "غیرقابل بازگشت": "irreversible", "غیرقابل‌بازگشت": "irreversible", "غیرقابل‌": "irreversible ",
    "منتقل می‌شود": "will be transferred", "منتقل شد": "was transferred", "منتقل شود": "should be transferred",
    "نمایندگی کمیسیونی": "commission reseller", "نمایندگی": "reseller", "نماینده": "reseller", "زیرمجموعه‌های شما": "your referrals", "زیرمجموعه": "referral",
    "لینک اختصاصی فروش شما": "Your dedicated sales link", "لینک فروش شما": "Your sales link", "لینک اختصاصی": "dedicated link",
    "خرید مشتریانی که با این لینک وارد شده‌اند": "purchases made by customers who joined through this link", "خرید مشتریانی که با این لینک وارد شوند": "purchases made by customers who join through this link",
    "کارمزد به کیف پول شما اضافه می‌شود": "commission will be added to your wallet", "کارمزد به کیف پول شما اضافه شد": "commission was added to your wallet",
    "تعداد مشتریان شما": "Your customer count", "تعداد خریدهای تسویه‌شده": "Settled purchases", "مجموع کارمزد دریافتی": "Total commission received",
    "درصد پیشنهادی": "proposed percentage", "منتظر بررسی ادمین بمانید": "wait for admin review", "تایید": "confirmation", "تأیید": "confirmation",
    "تایید شد": "was confirmed", "تأیید شد": "was confirmed", "رد شد": "was rejected", "لغو شد": "was cancelled",
    "فعال شد": "was activated", "فعال‌سازی": "activation", "راه‌اندازی": "setup", "تکمیل شد": "was completed", "تکمیل": "completion",
    "گزارش اختلال": "issue report", "بخش فنی": "technical team", "شماره تیکت": "ticket number", "تیکت": "ticket", "پاسخ داده می‌شود": "will be answered",
    "ممنون از بازخوردت": "Thanks for your feedback", "ممنون که وقت گذاشتی": "Thanks for your time",
    "درگاه لینک پرداخت برنگرداند": "the gateway did not return a payment link", "فاکتور پرداخت": "payment invoice", "فاکتور": "invoice",
    "پرداخت": "payment", "پرداخت را انتخاب کنید": "choose a payment method", "روش پرداخت": "payment method", "پرداختی": "payment",
    "نامعتبر است": "is invalid", "نامعتبر": "Invalid", "معتبر است": "is valid", "معتبر": "Valid", "ناموفق بود": "failed", "ناموفق": "Failed",
    "دوباره تلاش کنید": "Please try again", "دوباره تلاش کن": "Please try again", "انصراف بدهید": "cancel", "انصراف بده": "cancel",
    "فقط حروف انگلیسی، عدد و آندرلاین": "English letters, numbers, and underscores only", "کاراکتر": "characters",
    "پیش‌وند ثابت": "fixed prefix", "پیش‌وند": "prefix", "خط تیره": "hyphen", "نام تصادفی": "random name",
    "درخواست نمایندگی": "reseller request", "درخواست": "request", "نتیجه را اعلام می‌کند": "will announce the result", "نتیجه": "result",
    "مالکیت": "ownership", "مالک": "owner", "آیدی عددی": "numeric ID", "آیدی": "ID", "تلگرام": "Telegram",
    "صاحب": "owner", "اعتبار حجمی": "volume quota", "اعتبار": "quota", "بات نمایندگی": "reseller bot", "بات": "bot",
    "تخصیص‌یافته": "allocated", "برای شروع": "To get started", "وارد شوید": "enter", "وارد شو": "enter",
    "نپذیرفت": "did not accept", "خودشان تایید نکنند": "they confirm", "خودشان تأیید نکنند": "they confirm",
    "شارژ کیف پول": "wallet top-up", "شارژ": "top-up", "واریز": "deposit", "مبلغ دقیق": "exact amount", "کارت": "card", "به نام": "Account name",
    "بعد از واریز": "After the deposit", "به‌طور خودکار": "automatically", "بررسی می‌شود": "will be checked",
    "خطا در ساخت": "Error creating", "مبلغ به کیف پول بازگردانده شد": "The amount was refunded to your wallet",
    "بازیابی": "restore", "سرور": "server", "ذخیره نشد": "was not saved", "ذخیره شد": "was saved", "تنظیم شد": "was configured",
    "تنظیمات": "settings", "منوی بکاپ": "backup menu", "حالت کارخانه": "factory state", "بازگشت": "Back",
    "درصد کمیسیون": "commission percentage", "کمیسیون": "commission", "کاربر": "user", "تغییر کرد": "was changed", "تغییر": "change",
    "هزینه‌ی نمایندگی": "reseller fee", "هزینه": "fee", "روش‌های پرداخت مجاز": "allowed payment methods", "موافقت": "agreement",
    "پرداخت می‌کنم": "Pay", "دلیل": "Reason", "متاسفانه": "Unfortunately", "متأسفانه": "Unfortunately",
    "پاسخ پشتیبانی": "Support reply", "پشتیبانی": "Support", "توسط پشتیبانی بسته شد": "was closed by support", "ارسال شد": "was sent",
    "ارسال فایل": "file upload", "از طریق تلگرام": "through Telegram", "فایل روی خود سرور": "The file is on the server",
    "اتصال به سرور دوم": "connection to the second server", "بازگشت به حالت کارخانه": "factory reset", "تمدید": "renewal", "تمدید خودکار": "automatic renewal",
    "کمبود موجودی کیف پول": "insufficient wallet balance", "مبلغ لازم": "Required amount", "صفحه‌ی سرویس": "service page", "خاموش کنید": "disable",
    "ساخت فاکتور استارز": "creating the Stars invoice", "استارز": "Stars", "ناموفق بود": "failed",
    "یادآوری انقضای نمایندگی": "reseller expiration reminder", "پایان عضویت": "membership ends", "تاریخ انقضا": "Expiration date", "دوره‌ی بعدی": "next period",
    "نرخ": "rate", "درصد": "percentage", "سقف": "limit", "تعداد": "number", "افزایش": "increase", "کاهش": "decrease",
    "مقدار فعلی": "Current value", "فرمت جدید": "New format", "سقف اعتبار": "credit limit", "اختیاری": "optional", "عضویت دائمی": "permanent membership",
    "پیام": "message", "همگانی": "broadcast", "زمان‌بندی شد": "was scheduled", "شناسه": "ID", "کلید": "key", "آمار کامل": "full statistics",
    "فاصله": "interval", "بکاپ خودکار": "automatic backup", "چت دوم": "second chat", "نسخه": "copy", "جایگزین": "replaced", "مطمئنی": "Are you sure?",
    "توکن API": "API token", "ساخته شد": "was created", "سطح دسترسی": "Access level", "مستندات": "Documentation",

    "این": "this", "برای": "for", "را": "", "هر": "each", "به": "to", "تا": "until", "یک": "a", "یا": "or", "در": "in", "از": "from", "با": "with", "که": "that", "هم": "also", "خود": "yourself", "خودتان": "yourself", "خودش": "itself", "بدون": "without", "بعد": "after", "قبل": "before", "فعلی": "current", "نهایی": "final", "دکمه‌ی": "button", "انجام": "done", "شده": "done", "است": "is", "خواهد": "will", "بود": "was", "کند": "does", "می‌کند": "does", "می‌شود": "will be", "می‌شوند": "become", "می‌تونی": "you can", "می‌کنید": "do", "کنی": "do", "بگیر": "get", "بگیرید": "get", "ادامه": "continue", "شروع": "start", "ثابت": "fixed", "باز": "open", "استفاده": "use", "اعمال": "apply", "آیا": "Do", "ماند": "remained", "مبلغ": "amount", "کد": "code", "سطح": "level", "دیتابیس": "database", "زیر": "below", "تشویقی": "promotional", "آستانه‌ی": "threshold", "یادآوری": "reminder", "دعوت": "invite", "دریافت": "receive", "جایزه": "reward", "هدیه‌ی": "gift", "نفرات": "people", "قیمت": "price", "بازه‌ی": "range", "عدم‌اتصال": "disconnection", "توسط": "by", "مستقل": "independent", "وب": "web", "یوزرنیم": "username", "همین‌جا": "here", "نمایش": "display", "همیشه": "always", "قبلی": "previous", "اصلی": "main", "دیدن": "view", "آمار": "statistics", "دستور": "command", "به‌محض": "as soon as", "چه": "what", "وقت": "time", "بعدی": "next", "مورد": "item", "اطلاعات": "information", "مجاز": "allowed", "فقط": "only", "بیشتر": "more", "کمتر": "less", "دقیقاً": "exactly", "مثال": "example", "مثلاً": "for example", "صحیح": "integer", "عدد": "number", "شماره": "number", "شناسه": "ID", "آیدی": "ID", "آی‌دی": "ID", "نام": "name", "عنوان": "title", "موضوع": "subject", "متن": "text", "عکس": "photo", "تصویر": "image", "فایل": "file", "ویدیو": "video", "داده": "data", "تاریخ": "date", "زمان": "time", "پیام": "message", "کانال": "channel", "گروه": "group", "شماره‌ات": "your number", "شماره‌ی": "number", "موبایلت": "your mobile", "نیاز دارید": "do you need", "نیاز داره": "needs", "نیاز دارد": "needs", "داره": "has", "دارید": "have", "دارند": "have", "ندارد": "does not have", "ندارید": "do not have", "هست": "is", "هستید": "are", "مورد نظر": "requested", "موردنظر": "requested", "وارد": "enter", "وارد کنید": "enter", "وارد کن": "enter", "بفرست": "send", "بفرستید": "send", "بزن": "tap", "بزنید": "tap", "باقی‌مانده": "remaining", "قابل": "available", "توانید": "can", "می‌توانید": "you can", "می‌توانی": "you can", "خودت": "yourself", "خودم": "myself", "شما": "you", "تو": "you", "من": "I", "ما": "we", "خودشان": "themselves", "آن‌ها": "they", "آن": "that", "همین": "this", "چنین": "such", "بالا": "above", "داخل": "inside", "خارج": "outside", "از طریق": "through", "به‌خاطر": "because of", "به‌دلیل": "because of", "به‌صورت": "as", "به‌طور": "in a", "درحال": "in progress", "در حال": "in progress", "در دسترس": "available", "موجود نیست": "unavailable", "یافت نشد": "not found", "پیدا نشد": "not found", "پیدا": "found", "یافت": "found", "ثبت": "submit", "ثبت شد": "was submitted", "ثبت شده": "registered", "ارسال": "send", "ارسال شد": "was sent", "ارسال می‌شود": "will be sent", "دریافت شد": "was received", "آپلود": "upload", "آپلود شده": "uploaded", "دانلود": "download", "ذخیره": "save", "حذف": "delete", "ویرایش": "edit", "به‌روزرسانی": "update", "تغییر": "change", "تغییر کرد": "changed", "تنظیم": "setting", "تنظیم شد": "was configured", "ساخته شد": "was created", "ایجاد": "create", "عملیات": "operation", "خطا": "error", "علت": "reason", "باید": "must", "اختیاری": "optional", "اجباری": "required", "خودکار": "automatic", "دستی": "manual", "جدید": "new", "قدیمی": "old", "اولین": "first", "دوم": "second", "سوم": "third", "بعدی": "next", "فعلاً": "for now", "همین الان": "right now", "الان": "now", "فردا": "tomorrow", "امروز": "today", "آینده": "future", "پایان": "end", "مجموع": "total", "جمع": "total", "سقف": "limit", "حد": "limit", "حداقل": "minimum", "حداکثر": "maximum", "بین": "between", "بالاتر": "higher", "پایین‌تر": "lower", "درصد": "percent", "پورسانت": "commission", "تخفیف": "discount", "تعداد": "number", "نفر": "people", "دعوت": "invite", "برنده": "winner", "جایزه": "reward", "هدیه": "gift", "عضویت": "membership", "تمدید": "renewal", "تسویه‌شده": "settled", "ارسالی": "submitted", "رسید": "receipt", "فیش": "receipt", "فیک": "fake", "تشخیص": "detected", "بلاک": "blocked", "موجود": "available", "فعال": "enabled", "غیرفعال": "disabled", "عادی": "regular", "دسترسی": "access", "عضو": "member", "کانال": "channel", "پاکسازی": "cleanup", "حالت": "mode", "خرید": "purchase", "پیشنهاد": "proposal", "مستقیم": "direct", "پنلی": "panel-based", "تست": "test", "مورد": "item", "مرتبط": "related", "روش": "method", "پرداختی": "payment", "تحویل": "delivery", "حساب": "account", "سیستم": "system", "امکان": "ability", "تبدیل": "conversion", "سکه": "coins", "توکن": "token", "مصرف": "usage", "ثبت‌نام": "registration", "دیگر": "other", "دسته‌جمعی": "in bulk", "پنل": "panel", "سرور": "server", "سرویس": "service", "سرویس‌ها": "services", "کانفیگ": "configuration", "فاکتور": "invoice", "درگاه": "gateway", "لینک": "link", "آدرس": "address", "اعتبار": "quota", "موجودی": "balance", "کیف پول": "wallet", "پشتیبانی": "support", "تیکت": "ticket", "آموزش": "tutorial", "نمایندگی": "reseller", "نماینده": "reseller", "زیرمجموعه": "referral", "گردونه": "wheel", "شانس": "chance", "دسترسی": "access", "مدیریت": "administration", "ادمین": "admin", "مدیر": "admin", "مالک": "owner", "بات": "bot", "گزارش": "report", "فنی": "technical", "بررسی": "review", "نتیجه": "result", "اعلام": "announce", "ارسال": "send", "تایید": "confirm", "تأیید": "confirm", "رد": "reject", "لغو": "cancel", "کنسل": "cancel", "موفق": "successful", "ناموفق": "failed", "نامعتبر": "invalid", "معتبر": "valid", "مطمئن": "sure", "شما": "you", "خودتان": "yourself", "برای": "for", "را": "", "روی": "on", "به": "to", "تا": "until", "و": "and", "یا": "or", "از": "from", "در": "in", "با": "with", "که": "that", "هم": "also", "این": "this", "آن": "that", "ها": "s", "ی": "", "ِ": "", "٪": "%", "؟": "?", "،": ",", "؛": ";"

}

_FRAGMENT_TRANSLATIONS.update({
    "⚠️ سفارش یافت نشد.": "⚠️ Order not found.",
    "⛔️ تمدید ناموفق بود:": "⛔️ Renewal failed:",
    "با پشتیبانی تماس بگیرید.": "Please contact support.",
    "⛔️ خطا در ساخت کانفیگ روی پنل:": "⛔️ Failed to create the configuration on the panel:",
    "⚠️ پرداخت تایید شد ولی ساخت خودکار کانفیگ ناموفق بود:": "⚠️ Payment was confirmed, but automatic configuration creation failed:",
    "💰 مبلغ پرداختی:": "💰 Paid amount:",
    "♻️ مبلغ برگشتی به کیف پول:": "♻️ Refunded to wallet:",
    "♻️ موجودی برگشتی به محصول نمایندگی شما:": "♻️ Inventory returned to your reseller product:",
    "♻️ اعتبار برگشتی به نمایندگی شما:": "♻️ Credit returned to your reseller account:",
})


_DYNAMIC_PHRASES = [
    ("🤝 تبریک! یکی از زیرمجموعه‌های شما اولین خرید خود را انجام داد.\n💰 {x} تومان به کیف پول شما اضافه شد.", "🤝 Congratulations! One of your referrals made their first purchase.\n💰 {x} Toman was added to your wallet."),
    ("🤝 تبریک! یکی از زیرمجموعه‌های شما سرویسش را تمدید کرد.\n💰 {x} تومان پورسانت به کیف پول شما اضافه شد.", "🤝 Congratulations! One of your referrals renewed their service.\n💰 {x} Toman commission was added to your wallet."),
    ("🎁 هدیه‌ی عضویت شما فعال شد!\n{x} تومان به کیف پولت اضافه شد، همین حالا سرویس بگیر.", "🎁 Your signup gift is now active!\n{x} Toman was added to your wallet. Get your service now."),
    ("🔗 لینک اشتراک شما (برای کپی):\n`{x}`", "🔗 Your subscription link (copy it):\n`{x}`"),
    ("🔗 لینک اشتراک هوشمند شما:\n{x}/sub/smart/{x}", "🔗 Your smart subscription link:\n{x}/sub/smart/{x}"),
    ("📊 آمار کلی نمایندگی\n\n👥 کاربران: {x}\n🛒 خریداران: {x}\n🧪 اکانت تست: {x}\n📦 تعداد فروش: {x}\n💰 جمع فروش: {x} تومان", "📊 Reseller overview\n\n👥 Users: {x}\n🛒 Buyers: {x}\n🧪 Test accounts: {x}\n📦 Sales: {x}\n💰 Total sales: {x} Toman"),
    ("📦 محصول: {x}\nموجودی: {x} عدد\n\nیک نام کاربری برای کانفیگ وارد کن یا از دکمه نام تصادفی استفاده کن.", "📦 Product: {x}\nStock: {x}\n\nEnter a username for the configuration or use the random-name button."),
    ("❌ نام نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا {x} کاراکتر.", "❌ Invalid name. Use only English letters, numbers, and underscores, between 3 and {x} characters."),
    ("❌ مدت باید بین {x} تا {x} روز باشد.", "❌ Duration must be between {x} and {x} days."),
    ("⏳ مدت اعتبار را به روز وارد کن (بین {x} تا {x} روز):", "⏳ Enter the validity period in days (between {x} and {x} days):"),
    ("⛔️ ظرفیت پنل تکمیل است ({x}/{x} سرویس فعال).", "⛔️ The panel capacity is full ({x}/{x} active services)."),
    ("📦 یک کانفیگ («{x}») از طرف کاربر دیگری به حساب شما منتقل شد.\nبرای مشاهده، حساب کاربری ← سرویس‌ها و سفارش‌های من را ببینید.", "📦 A configuration (“{x}”) was transferred to your account by another user.\nTo view it, go to Account → My services and orders."),
    ("💸 {x} تومان از طرف یک کاربر به کیف پول شما منتقل شد.", "💸 {x} Toman was transferred to your wallet by a user."),
    ("لطفاً یک عدد معتبر و حداقل {x} تومان ارسال کنید.", "Please send a valid amount of at least {x} Toman."),
    ("لطفاً یک عدد صحیح بین {x} تا {x} ارسال کنید.", "Please send an integer between {x} and {x}."),
    ("لطفاً عددی بزرگ‌تر از حداقل ({x}) ارسال کنید.", "Please send a number greater than the minimum ({x})."),
    ("لطفاً عددی بزرگ‌تر از حداقل ({x}) ارسال کن.", "Please send a number greater than the minimum ({x})."),
    ("انتهای بازه باید بزرگ‌تر از ابتدای آن ({x}) باشد.", "The end of the range must be greater than its beginning ({x})."),
    ("⛔️ سقف نمی‌تواند کمتر از تعداد سرویس‌های فعال فعلی ({x}) باشد.", "⛔️ The limit cannot be lower than the current number of active services ({x})."),
    ("⏰ انقضای نمایندگی | کاربر {x} | سطح {x}", "⏰ Reseller membership expiration | User {x} | Level {x}"),
    ("⏳ یادآوری انقضای نمایندگی\n\nسطح: {x}\nفقط {x} روز تا پایان عضویت باقی مانده است.\nتاریخ انقضا: {x}\n\nبرای تمدید، هزینه‌ی دوره‌ی بعدی از کیف پول اعتباری کسر می‌شود.", "⏳ Reseller membership expiration reminder\n\nLevel: {x}\nOnly {x} days remain until the membership ends.\nExpiration date: {x}\n\nFor renewal, the next period’s fee will be deducted from the credit wallet."),
    ("🔄 کانفیگ «{x}» با موفقیت به‌صورت خودکار تمدید شد و {x} تومان از کیف پول شما کسر شد.", "🔄 Configuration “{x}” was automatically renewed successfully, and {x} Toman was deducted from your wallet."),
    ("⚠️ تمدید خودکار کانفیگ «{x}» به‌دلیل کمبود موجودی کیف پول انجام نشد.\nمبلغ لازم: {x} تومان — موجودی فعلی: {x} تومان.\nلطفاً کیف پول خود را شارژ کنید یا تمدید خودکار را از صفحه‌ی سرویس خاموش کنید.", "⚠️ Automatic renewal of configuration “{x}” failed because your wallet balance was insufficient.\nRequired amount: {x} Toman — Current balance: {x} Toman.\nPlease top up your wallet or disable automatic renewal from the service page."),
    ("⚠️ تمدید خودکار کانفیگ «{x}» انجام نشد؛ سرور پنل این سرویس غیرفعال یا حذف شده است.\nلطفاً با پشتیبانی تماس بگیرید.", "⚠️ Automatic renewal of configuration “{x}” failed because the panel server for this service is disabled or deleted.\nPlease contact support."),
    ("⚠️ ساخت فاکتور استارز ناموفق بود: {x}", "⚠️ Failed to create the Stars invoice: {x}"),
    ("❌ ارسال به کاربر ناموفق بود: {x}", "❌ Failed to send to the user: {x}"),
    ("⛔️ {x}\nسرور ذخیره نشد؛ دوباره از ابتدا تلاش کن.", "⛔️ {x}\nThe server was not saved; please start over."),
    ("⛔️ بازیابی ناموفق بود: {x}", "⛔️ Restore failed: {x}"),
    ("❌ اتصال به پنل ناموفق بود.\n\nعلت: <code>{x}</code>", "❌ Failed to connect to the panel.\n\nReason: <code>{x}</code>"),
    ("✅ دیتابیس پنل «{x}» بازیابی شد.", "✅ Panel database “{x}” was restored."),
    ("❌ دقیقاً سه عدد ({x}) بفرست؛ مثال: {x}", "❌ Send exactly three numbers ({x}); example: {x}"),
    ("❌ یک عدد صحیح بین {x} تا {x} بفرست.", "❌ Send an integer between {x} and {x}."),
    ("ایجاد عملیات ناموفق بود: {x}", "The operation could not be created: {x}"),
    ("⛔️ تمدید ناموفق بود: {x}", "⛔️ Renewal failed: {x}"),
    ("💰 مبلغ انتقال (تومان) را ارسال کنید.\nموجودی شما: {x} تومان", "💰 Enter the transfer amount (Toman).\nYour balance: {x} Toman"),
    ("✅ {x} تومان منتقل شد.\nموجودی فعلی: {x} تومان", "✅ {x} Toman was transferred.\nCurrent balance: {x} Toman"),
    ("✅ {x} تومان به کیف پول شما اضافه شد.\nموجودی فعلی: {x} تومان", "✅ {x} Toman was added to your wallet.\nCurrent balance: {x} Toman"),
    ("💳 <b>پرداخت هزینه {x}</b>\n\n💰 مبلغ: <b>{x} تومان</b>\n\nروش پرداخت را انتخاب کنید:", "💳 <b>Payment for {x}</b>\n\n💰 Amount: <b>{x} Toman</b>\n\nChoose a payment method:"),
    ("✅ توکن معتبر است: @{x}\n\nحالا آیدی عددی تلگرام خودتان (که مالک این بات خواهد بود) را ارسال کنید:", "✅ Token is valid: @{x}\n\nNow send your numeric Telegram ID (it will be the owner of this bot):"),
    ("✅ گزارش اختلال ثبت شد. شماره تیکت: #{x}\nبخش فنی در حال بررسی است.", "✅ Issue report submitted. Ticket number: #{x}\nThe technical team is reviewing it."),
    ("⭐ امتیاز {x}/۵ ثبت شد. ممنون از بازخوردت!", "⭐ Rating {x}/5 recorded. Thanks for your feedback!"),
    ("✅ تیکت شما با شماره #{x} ثبت شد. به زودی پاسخ داده می‌شود.", "✅ Your ticket #{x} was submitted. You will receive a response soon."),
    ("❌ حجم باید بین {x} تا {x} گیگابایت باشد.", "❌ Volume must be between {x} and {x} GB."),
    ("⛔️ سقف انتقال شما تکمیل شده است ({x}/{x}).", "⛔️ Your transfer limit has been reached ({x}/{x})."),
    ("❌ {x}\nدوباره تلاش کنید یا انصراف بدهید.", "❌ {x}\nPlease try again or cancel."),
    ("لطفاً فقط عدد صحیح و بزرگ‌تر از صفر وارد کنید{x}. مثال: 30", "Please enter a positive integer only{x}. Example: 30"),
    ("لطفاً متن پاسخ برای کاربر {x} را ارسال کنید:", "Please send the reply text for user {x}:"),
    ("متن پاسخ برای کاربر {x} را ارسال کنید:", "Send the reply text for user {x}:"),
    ("متن پاسخ برای تیکت #{x} را ارسال کنید:", "Send the reply text for ticket #{x}:"),
    ("📩 پاسخ پشتیبانی:\n\n{x}", "📩 Support reply:\n\n{x}"),
    ("🎫 پاسخ پشتیبانی به تیکت «{x}» (#{x}):\n\n{x}", "🎫 Support reply to ticket “{x}” (#{x}):\n\n{x}"),
    ("✅ پاسخ به تیکت #{x} ارسال شد.", "✅ Reply to ticket #{x} was sent."),
    ("🔒 تیکت «{x}» (#{x}) توسط پشتیبانی بسته شد.", "🔒 Ticket “{x}” (#{x}) was closed by support."),
    ("❌ فایلی در مسیر «{x}» روی این سرور پیدا نشد. دوباره بفرست یا مسیر درست را وارد کن.", "❌ No file was found at “{x}” on this server. Send it again or enter the correct path."),
    ("❌ ارسال فایل از طریق تلگرام ناموفق بود. فایل روی خود سرور اینجاست:\n{x}", "❌ Sending the file through Telegram failed. The file is available on the server here:\n{x}"),
    ("❌ تست ناموفق بود: {x}", "❌ Test failed: {x}"),
    ("❌ اتصال به سرور دوم ناموفق بود: {x}\nتنظیمات ذخیره نشد؛ از منوی بکاپ دوباره تلاش کن.", "❌ Connection to the second server failed: {x}\nSettings were not saved; try again from the backup menu."),
    ("❌ بازگشت به حالت کارخانه ناموفق بود: {x}", "❌ Factory reset failed: {x}"),
    ("📊 درصد کمیسیون نمایندگی شما به {x}٪ تغییر کرد.", "📊 Your reseller commission was changed to {x}%."),
    ("💰 هزینه‌ی این نمایندگی (به تومان) چقدر باشد؟ فقط عدد ارسال کنید:", "💰 What should the reseller fee be in Toman? Send numbers only:"),
    ("💳 روش‌های پرداخت مجاز برای این درخواست ({x} تومان) را انتخاب کنید:", "💳 Choose the allowed payment methods for this request ({x} Toman):"),
    ("✅ درصد کمیسیون کاربر {x} به {x}٪ تغییر کرد.", "✅ User {x}'s commission was changed to {x}% ."),
    ("❌ متاسفانه {x} شما (#{x}) رد شد.\n\nدلیل: {x}", "❌ Unfortunately, your {x} (#{x}) was rejected.\n\nReason: {x}"),
    ("🏪 درخواست نمایندگی #{x} شما تایید شد!\n\n💰 هزینه‌ی نمایندگی: {x} تومان\n{x}{x}\nدر صورت موافقت روی «پرداخت می‌کنم» بزنید:", "🏪 Your reseller request #{x} was approved!\n\n💰 Reseller fee: {x} Toman\n{x}{x}\nIf you agree, tap “Pay”."),
    ("✅ پرداخت هزینه {x} تایید شد و نمایندگی شما فعال شد.", "✅ Payment for {x} was confirmed and your reseller account was activated."),
    ("🧑‍💼 پنل نمایندگی\n\n📦 اعتبار باقی‌مانده: {x} گیگابایت\n\nمی‌تونی از این اعتبار مستقیم کانفیگ بسازی.", "🧑‍💼 Reseller panel\n\n📦 Remaining quota: {x} GB\n\nYou can create configurations directly from this quota."),
    ("📦 محصول: {x}\nموجودی: {x} عدد\n\nیک نام کاربری برای کانفیگ وارد کن یا از دکمه نام تصادفی استفاده کن.", "📦 Product: {x}\nStock: {x}\n\nEnter a username for the configuration or use the random-name button."),
    ("⏳ فردا دوباره امتحان کن! حدود {x} ساعت دیگر می‌توانی دوباره گردونه را بچرخانی.", "⏳ Try again tomorrow! You can spin the wheel again in about {x} hours."),
    ("💸 {x} تومان از طرف یک کاربر به کیف پول شما منتقل شد.", "💸 {x} Toman was transferred to your wallet by a user."),
    ("شما همین الان در سطح {x} {x} هستید.", "You are currently at {x} {x} level."),
    ("لطفاً یک عدد معتبر و حداقل {x} تومان ارسال کنید.", "Please send a valid amount of at least {x} Toman."),
    ("حداقل خرید سطح {x} برابر {x} گیگ است.", "The minimum purchase for level {x} is {x} GB."),
    ("حداقل خرید سطح {x} برابر {x} عدد است.", "The minimum purchase for level {x} is {x} items."),
    ("⛔️ ظرفیت پنل تکمیل است ({x}/{x}).", "⛔️ The panel capacity is full ({x}/{x})."),
]

_dynamic_cache = {"size": -1, "items": []}


def _compiled_dynamic():
    import re
    if _dynamic_cache["size"] != len(_DYNAMIC_PHRASES):
        items = []
        for fa_template, en_template in _DYNAMIC_PHRASES:
            parts = fa_template.split("{x}")
            pattern = re.escape(parts[0])
            for part in parts[1:]:
                pattern += r"([\s\S]*?)" + re.escape(part)
            items.append((re.compile(pattern), en_template))
        _dynamic_cache["items"] = items
        _dynamic_cache["size"] = len(_DYNAMIC_PHRASES)
    return _dynamic_cache["items"]


def numbered_template(en_template: str) -> str:
    """Return the English template with {x} placeholders numbered {x1}, {x2}, ..."""
    count = 0
    out = []
    for part in en_template.split("{x}"):
        if out:
            count += 1
            out.append("{x%d}" % count)
        out.append(part)
    return "".join(out)


def dynamic_match(text: str):
    """Return (numbered_english_template, captured_values) for a runtime-built Persian sentence."""
    for pattern, en_template in _compiled_dynamic():
        m = pattern.fullmatch(text)
        if m:
            return numbered_template(en_template), m.groups()
    return None


def fill_template(template: str, values) -> str:
    out = template
    for index, value in enumerate(values, 1):
        out = out.replace("{x%d}" % index, value)
    return out


def _lexical_translate(text: str) -> str:
    import re
    matched = dynamic_match(text)
    if matched:
        return fill_template(*matched)

    out = text
    # Translate longer UI fragments before individual words.
    for fa, en in sorted(_FRAGMENT_TRANSLATIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if not fa:
            continue
        # Use token boundaries for word-like Persian fragments so short entries
        # such as «تو» cannot corrupt «تومان» or other longer words.
        if all((c == " " or "\u0600" <= c <= "\u06ff" or c == "\u200c") for c in fa):
            pattern = r"(?<![\u0600-\u06ff])" + re.escape(fa) + r"(?![\u0600-\u06ff])"
            out = re.sub(pattern, en, out)
        else:
            out = out.replace(fa, en)
    # Only replace standalone Persian terms. The previous implementation used
    # raw substring replacement, which corrupted words such as «درگاه» and
    # «کاربر». This keeps the legacy fallback readable and safe.
    for fa, en in sorted(_WORD_TRANSLATIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if not fa:
            continue
        pattern = r'(?<![\u0600-\u06ff])' + re.escape(fa) + r'(?![\u0600-\u06ff])'
        out = re.sub(pattern, en, out)
    return out

def normalize_language(language: Optional[str]) -> str:
    value = (language or "").strip().lower().replace("_", "-")
    if value.startswith("fa") or value in {"prs", "per"}:
        return "fa"
    if value.startswith("en"):
        return "en"
    code = value.split("-", 1)[0]
    # Keep arbitrary ISO-style language codes so the per-tenant language
    # registry can enable them without changing application code. Unknown or
    # malformed values still preserve the historic Persian default.
    if 2 <= len(code) <= 3 and code.isalpha():
        return code
    return DEFAULT_LANGUAGE

def is_language_enabled(db, language: str) -> bool:
    code = normalize_language(language)
    try:
        row = db.get_language(code)
        if not row or not row["enabled"]:
            return False
        # Dynamic languages no longer need a (near-)complete catalog before
        # being selectable: whatever is still missing is translated on demand,
        # per string, the moment it is actually needed (see
        # bot_manager.TranslatingBot / translation_engine.translate_texts_now),
        # so admins can turn a language on immediately instead of waiting for a
        # full sync. The manifest/ratio machinery still exists for health
        # reporting in the admin panel, it just no longer gates availability.
        return True
    except Exception:
        return code in {"fa", "en"}


def set_language(language: str, catalog: Optional[dict] = None):
    lang = normalize_language(language)
    token = _current_language.set(lang)
    if catalog is not None:
        _current_catalog.set(dict(catalog or {}))
    elif lang in {"fa", "en"}:
        _current_catalog.set({})
    return token

def set_language_catalog(catalog: Optional[dict]):
    return _current_catalog.set(dict(catalog or {}))

def reset_language(token):
    _current_language.reset(token)

def get_language() -> str:
    return _current_language.get()

def tr(text: str, language: Optional[str] = None) -> str:
    if text is None:
        return text
    lang = normalize_language(language or get_language())
    if lang == "fa":
        return text
    catalog = _TRANSLATIONS.get(lang, {})
    if text in catalog:
        return catalog[text]
    if lang == "en":
        if text in _PHRASE_TRANSLATIONS:
            return _PHRASE_TRANSLATIONS[text]
        return _lexical_translate(text)
    catalog = _current_catalog.get()
    catalog_value = catalog.get(text)
    if catalog_value:
        return catalog_value
    english = _TRANSLATIONS.get("en", {}).get(text) or _PHRASE_TRANSLATIONS.get(text)
    if english:
        value = catalog.get(english)
        if value:
            return value
        note_missing(english)
        return english
    matched = dynamic_match(text)
    if matched:
        template, values = matched
        value = catalog.get(template)
        if not value:
            note_missing(template)
            value = template
        return fill_template(value, values)
    return text

def api_message(text: str, language: Optional[str] = None) -> str:
    """Translate a static API-facing message using the active/request language."""
    return tr(text, language)


def language_label(language: str) -> str:
    code = normalize_language(language)
    meta = LANGUAGE_CATALOG.get(code)
    if meta:
        return f"{meta['flag']} {meta['native_name']}"
    return code

def is_rtl(language: Optional[str] = None) -> bool:
    code = normalize_language(language or get_language())
    return bool(LANGUAGE_CATALOG.get(code, {}).get("rtl", False))

_PHRASE_TRANSLATIONS.update({
    "🗄 بکاپ فوری دیتابیس": "🗄 Instant database backup",
    "✅ تصویر پس‌زمینه ذخیره و فعال شد. این یک پیش‌نمایش با یک لینک نمونه است:": "✅ QR background image saved and enabled. This is a preview with a sample link:",
    "👁 پیش‌نمایش پس‌زمینه‌ی QR (با یک لینک نمونه)": "👁 QR background preview (with a sample link)",
    "این فاکتور دیگر معتبر نیست. لطفاً دوباره از منو اقدام کن.": "This invoice is no longer valid. Please start again from the menu.",
})
_PHRASE_TRANSLATIONS.update({
"✅ ساعت حذف کانفیگ‌های غیرفعال ذخیره شد.": "✅ Inactive configuration deletion time saved.",
"فیش فیک ثبت شد؛ کاربر بلاک و کانفیگ مرتبط حذف شد.": "Fake receipt recorded; the user was blocked and the related configuration was deleted.",
"✅ متن بعد از تحویل کانفیگ ذخیره شد.": "✅ Post-delivery configuration message saved.",
"📎 لطفاً یک تصویر (عکس یا فایل تصویری) بفرست، یا برای انصراف «لغو» را بفرست.": "📎 Please send an image (photo or image file), or send \"Cancel\" to abort.",
"❌ باید فایل دیتابیس x-ui.db را به‌صورت Document ارسال کنی، نه متن یا عکس.": "❌ Send the x-ui.db database as a document, not as text or a photo.",
"❌ مبلغ نامعتبر است؛ فقط عدد مثبت ارسال کنید.": "❌ Invalid amount; enter a positive number only.",
"🚫 فیش فیک تشخیص داده شد.\n\n⛔️ سفارش شما رد شد و حساب کاربری‌تان بلاک شد.\nدر صورت اشتباه، برای بررسی موضوع با پشتیبانی تماس بگیرید.": "🚫 A fake receipt was detected.\n\n⛔️ Your order was rejected and your account was blocked.\nIf this was a mistake, please contact support for review.",
"❌ متاسفانه رسید ارسالی شما تایید نشد. در صورت اشتباه لطفاً با پشتیبانی در ارتباط باشید.": "❌ Unfortunately, your submitted receipt was not approved. If this was a mistake, please contact support.",
"❌ متاسفانه درخواست شارژ کیف پول شما تایید نشد. در صورت اشتباه با پشتیبانی تماس بگیرید.": "❌ Unfortunately, your wallet top-up request was not approved. If this was a mistake, please contact support.",
"لطفاً یک عدد بین 0 تا 100 ارسال کنید.": "Please send a number between 0 and 100.",
"لطفاً یک عدد صحیح (0 یا بیشتر) ارسال کنید.": "Please send an integer (0 or greater).",
"✅ متن بعد از تحویل کانفیگ حذف شد.": "✅ Post-delivery configuration message deleted.",
"❌ فایل باید همان دیتابیس x-ui.db باشد (پسوند .db). دوباره ارسال کن.": "❌ The file must be the x-ui.db database (.db extension). Please send it again.",
"❌ این فایل یک دیتابیس sqlite معتبر نیست. عملیات لغو شد.": "❌ This file is not a valid SQLite database. Operation cancelled.",
"لطفاً عنوان آموزش را به‌صورت نوشتاری ارسال کن:": "Please send the tutorial title as text:",
"لطفاً یک عنوان معتبر برای آموزش بفرست.": "Please enter a valid tutorial title.",
"این آموزش قبلاً حذف شده.": "This tutorial has already been deleted.",
"لطفاً عنوان را به‌صورت نوشتاری ارسال کن:": "Please send the title as text:",
"لطفاً یک عنوان معتبر بفرست.": "Please enter a valid title.",
"لطفاً متن، عکس یا ویدیو ارسال کنید.": "Please send text, a photo, or a video.",
"⚠️ فقط یک عدد صحیح مثبت وارد کن (مثلاً 30).": "⚠️ Enter a positive integer only (for example, 30).",
"این کاربر هیچ سرویس مستقیم‌-پنلی (غیر تست) ندارد که بشود دسته‌جمعی فعال/غیرفعال کرد.": "This user has no direct panel services (excluding test services) that can be enabled or disabled in bulk.",
"❌ متن اعلان نباید بیشتر از ۱۰۰۰ کاراکتر باشد.": "❌ The announcement text must not exceed 1,000 characters.",
"❌ دسترسی به کانال ممکن نشد. آیدی را بررسی کنید و مطمئن شوید ربات ادمین کانال است.": "❌ Could not access the channel. Check the ID and make sure the bot is a channel admin.",
"❌ ساعت نامعتبر است. مثل 23:30 بفرستید یا ۰ برای خاموش‌کردن.": "❌ Invalid time. Use a format such as 23:30, or 0 to disable.",
"✅ کانفیگ شخصی شما ساخته شد!": "✅ Your personal configuration was created!",
"❌ فایل ارسالی تصویر نیست. یک عکس یا فایل تصویری (JPG/PNG) بفرست.": "❌ The uploaded file is not an image. Send a JPG/PNG photo or image file.",
"❌ ابعاد تصویر خیلی کوچک است (حداقل ۵۰۰×۵۰۰ پیشنهاد می‌شود). یک تصویر بزرگ‌تر بفرست، یا «لغو» را بفرست.": "❌ The image is too small (500×500 minimum recommended). Send a larger image, or send \"Cancel\".",
"❌ پردازش تصویر ناموفق بود. لطفاً یک فایل تصویری سالم (JPG/PNG) بفرست.": "❌ Image processing failed. Please send a valid JPG/PNG image file.",
"✅ تصویر پس‌زمینه ذخیره و فعال شد.": "✅ Background image saved and enabled.",
"ساخت پیش‌نمایش ناموفق بود.": "Preview generation failed.",
"⛔️ نمایندگی کمیسیونی شما توسط ادمین غیرفعال شد.": "⛔️ Your commission-based reseller account was disabled by an admin.",
"⚠️ عضویت اجباری در کانال فعال نیست یا کانالی تنظیم نشده.": "⚠️ Mandatory channel membership is disabled or no channel is configured.",
"⚠️ در پردازش پیام شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.": "⚠️ An error occurred while processing your message. Please try again or contact support.",
"❌ فقط آیدی‌های عددی را بفرست؛ مثال: 123456789 987654321": "❌ Send numeric IDs only; example: 123456789 987654321",
"❌ آیدی گروه باید عددی باشد؛ مثال: -1001234567890": "❌ The group ID must be numeric; example: -1001234567890",
"❌ یک عدد بین ۰ تا ۱۰۰۰۰۰ بفرست؛ مثال: 5 یا 2.5": "❌ Send a number between 0 and 100000; example: 5 or 2.5",
"❌ یک عدد صحیح بین ۰ تا ۳۶۵۰ بفرست.": "❌ Send an integer between 0 and 3650.",
"✅ به‌روزرسانی شد.": "✅ Updated.",
"⛔️ فقط مالک و مدیر کامل می‌توانند ربات را خاموش/روشن کنند.": "⛔️ Only the owner and full admins can turn the bot off or on.",
"🔴 ربات برای کاربران عادی خاموش شد.\nادمین‌ها همچنان دسترسی دارند. برای روشن کردن: /bot_on": "🔴 The bot is now off for regular users.\nAdmins still have access. To turn it on: /bot_on",
"⚠️ یک عدد صحیح مثبت ارسال کنید.": "⚠️ Please send a positive integer.",
"⛔️ این توکن همین الان توسط یک ثبت‌نام دیگر مصرف شد؛ لطفاً یک توکن جدید از @BotFather بگیرید و دوباره ارسال کنید.": "⛔️ This token was just used by another registration. Please get a new token from @BotFather and send it again.",
"⏳ هنوز پرداختی برای این فاکتور تایید نشده. کمی صبر کن و دوباره بررسی کن.": "⏳ No payment has been confirmed for this invoice yet. Wait a moment and check again.",
"⛔️ این دکمه‌ها فقط برای مدیران فعال است.": "⛔️ These buttons are available only to admins.",
"⚠️ عضویت نمایندگی شما منقضی شد. تنظیمات و دسترسی‌های نمایندگی غیرفعال شدند؛ سرویس‌های ساخته‌شده‌ی شما حذف نشده‌اند. برای ادامه، دوباره درخواست/تمدید نمایندگی ثبت کنید.": "⚠️ Your reseller membership has expired. Reseller settings and access were disabled; your existing services were not deleted. To continue, submit a new reseller request or renewal.",
})


# API/backend error catalog (same source of truth as Bot/Web/Mini App UI).
_PHRASE_TRANSLATIONS.update({
"توکن دسترسی نامعتبر یا باطل‌شده است.":"The access token is invalid or expired.",
"نشست منقضی شده یا نامعتبر است.":"The session has expired or is invalid.",
"پنل وب این نماینده دیگر فعال نیست.":"This reseller's web panel is no longer active.",
"حساب کاربری غیرفعال یا حذف شده است.":"The account is inactive or has been deleted.",
"این قابلیت برای نمایندگی در دسترس نیست.":"This feature is not available for reseller panels.",
"این بخش فقط در پنل بات اصلی در دسترس است.":"This section is only available in the main bot panel.",
"دسترسی کافی نیست.":"Insufficient permissions.",
"این بخش فقط برای مالک است.":"This section is available to the owner only.",
"این پنل در دسترس نیست.":"This panel is not available.",
"یوزرنیم یا پسورد اشتباه است.":"Incorrect username or password.",
"لینک راه‌اندازی نامعتبر یا منقضی‌شده است.":"The setup link is invalid or expired.",
"توکن پیدا نشد.":"Token not found.",
"توکن نامعتبر است.":"Invalid token.",
"یافت نشد.":"Not found.",
"سفارش یافت نشد.":"Order not found.",
"سفارش یافت نشد یا قبلاً بررسی شده.":"Order not found or already reviewed.",
"سفارش یافت نشد یا قبلاً بررسی شده است.":"Order not found or already reviewed.",
"رسیدی برای این سفارش ثبت نشده است.":"No receipt was registered for this order.",
"درخواست شارژ یافت نشد.":"Top-up request not found.",
"کاربر یافت نشد.":"User not found.",
"کاربری با این آیدی عددی پیدا نشد.":"No user was found with this numeric ID.",
"کانفیگ یافت نشد.":"Configuration not found.",
"محصول در دسترس نیست.":"Product is not available.",
"موجودی این محصول تمام شده است.":"This product is out of stock.",
"قبلاً بررسی شده است.":"Already reviewed.",
"یافت نشد یا قبلاً بررسی شده.":"Not found or already reviewed.",
"متن پیام نمی‌تواند خالی باشد.":"Message text cannot be empty.",
"متن پیام بیش از حد طولانی است.":"Message text is too long.",
"ارسال پیام به کاربر ناموفق بود (شاید بات را بلاک کرده).":"Failed to send the message to the user (they may have blocked the bot).",
"ارسال اعلان تست ناموفق بود.":"Failed to send the test notification.",
"ارسال نظرسنجی ممکن نیست.":"The survey cannot be sent.",
"اطلاعات subscription ناقص است.":"Subscription information is incomplete.",
"اعلان Push روی سرور تنظیم نشده است.":"Push notifications are not configured on the server.",
"هنوز روی این دستگاه اعلان را فعال نکرده‌ای.":"Notifications have not been enabled on this device yet.",
"دریافت رسید از تلگرام ناموفق بود.":"Failed to retrieve the receipt from Telegram.",
"ارسال رسید به ادمین ناموفق بود. دوباره تلاش کنید.":"Failed to send the receipt to the admin. Please try again.",
"ارسال فایل بکاپ به تلگرام ناموفق بود. دوباره تلاش کن.":"Failed to send the backup file to Telegram. Please try again.",
"ارتباط با تلگرام برقرار نشد. دوباره تلاش کن.":"Could not connect to Telegram. Please try again.",
"احراز هویت وب‌هوک نامعتبر است.":"Webhook authentication is invalid.",
"initData نامعتبر است.":"Invalid initData.",
"آدرس Subscription باید با http:// یا https:// شروع شود.":"The Subscription URL must start with http:// or https://.",
"لینک ساب باید با http:// یا https:// شروع شود.":"The subscription link must start with http:// or https://.",
"سوال و جواب نمی‌توانند خالی باشند.":"Question and answer cannot be empty.",
"مسیر انتخاب مدل نامعتبر است.":"The selected model path is invalid.",
"psutil نصب نیست. دستور: pip install psutil":"psutil is not installed. Command: pip install psutil",
"آستانه نمی‌تواند منفی باشد.":"The threshold cannot be negative.",
"آستانه‌ی مصرف باید بزرگ‌تر از صفر باشد.":"The usage threshold must be greater than zero.",
"آستانه‌ی گیگابایت باید بزرگ‌تر از صفر باشد.":"The gigabyte threshold must be greater than zero.",
"اعتبار کد تخفیف باید بزرگ‌تر از صفر باشد.":"Discount code credit must be greater than zero.",
"حجم نامعتبر است.":"Invalid volume.",
"نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.":"Invalid. Use only English letters, numbers, and underscores, 3 to 20 characters.",
"این نام همان نام فعلی است.":"This is already the current name.",
"این نام قبلاً استفاده شده. نام دیگری انتخاب کنید.":"This name is already in use. Choose another name.",
"این کاربر بات را استارت نکرده یا آی‌دی نادرست است.":"This user has not started the bot or the ID is incorrect.",
"انتقال ناموفق بود.":"Transfer failed.",
"این قابلیت برای کانفیگ تست در دسترس نیست.":"This feature is not available for test configurations.",
"این کانفیگ نامحدود است و نیازی به تمدید خودکار ندارد.":"This configuration is unlimited and does not need auto-renewal.",
"این کانفیگ همین الان مال همین کاربر است.":"This configuration already belongs to this user.",
"سرور پنل مربوط به این سرویس یافت نشد یا غیرفعال است.":"The panel server for this service was not found or is inactive.",
"نمایندگی معتبر نیست.":"The reseller is invalid.",
"نمایندگی غیرفعال است.":"The reseller is inactive.",
"این بخش فقط از پنل نمایندگی در دسترس است.":"This section is only available from the reseller panel.",
"هیچ پنل فعالی برای ساخت کانفیگ نمایندگی تنظیم نشده است.":"No active panel is configured for creating reseller configurations.",
"موجودی محصول هم‌زمان مصرف شد؛ دوباره تلاش کنید.":"The product inventory was consumed concurrently; please try again.",
"اعتبار حجمی هم‌زمان مصرف شد؛ دوباره تلاش کنید.":"The volume credit was consumed concurrently; please try again.",
"ثبت سرویس در پنل نماینده ناموفق بود؛ عملیات برگشت داده شد.":"Failed to register the service on the reseller panel; the operation was rolled back.",
"اتصال مستقیم به پنل فقط برای بات اصلی مجاز است.":"Direct panel connection is only allowed for the main bot.",
"امکان تغییر مجوزهای این حساب نیست.":"This account's permissions cannot be changed.",
"امکان تغییر نقش این حساب نیست.":"This account's role cannot be changed.",
"امکان تغییر وضعیت این حساب نیست.":"This account's status cannot be changed.",
"امکان حذف این حساب نیست.":"This account cannot be deleted.",
"granularity باید یکی از day/week/month باشد.":"granularity must be one of day/week/month.",
"فایل دیتابیس پیدا نشد.":"Database file not found.",
"این فایل یک دیتابیس sqlite معتبر نیست.":"This file is not a valid SQLite database.",
"فایل باید پسوند .db یا .sqlite داشته باشد.":"The file must have a .db or .sqlite extension.",
"برای تایید بازیابی، عبارت RESTORE را دقیقاً وارد کن.":"To confirm the restore, enter RESTORE exactly.",
"برای تایید بازگشت به حالت کارخانه، عبارت RESET را دقیقاً وارد کن.":"To confirm the factory reset, enter RESET exactly.",
})
_PHRASE_TRANSLATIONS.update({
    "📦 سرویس‌ها و سفارش‌های من": "📦 My services & orders",
    "👛 کیف پول من": "👛 My wallet",
    "⬅️ بازگشت به منوی اصلی": "⬅️ Back to main menu",
    "⬅️ حساب کاربری": "⬅️ My account",
})
_DYNAMIC_PHRASES.extend([
    ("🆔 شناسه کاربری: {x}", "🆔 User ID: {x}"),
    ("👤 نام کاربری: {x}", "👤 Username: {x}"),
    ("👛 موجودی کیف پول: {x} تومان", "👛 Wallet balance: {x} Toman"),
    ("💳 سقف اعتبار: {x} تومان | بدهی: {x} تومان", "💳 Credit limit: {x} Toman | Debt: {x} Toman"),
    ("📦 تعداد سفارش‌ها: {x}", "📦 Orders: {x}"),
])

from i18n_extra import EXTRA_PHRASES as _EXTRA_PHRASES, EXTRA_DYNAMIC_PHRASES as _EXTRA_DYNAMIC

for _key, _value in _EXTRA_PHRASES.items():
    _PHRASE_TRANSLATIONS.setdefault(_key, _value)
_known_dynamic = {fa for fa, _ in _DYNAMIC_PHRASES}
_DYNAMIC_PHRASES.extend(p for p in _EXTRA_DYNAMIC if p[0] not in _known_dynamic)
