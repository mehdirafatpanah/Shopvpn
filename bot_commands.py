# -*- coding: utf-8 -*-
"""فهرست مرکزی دستورهای «/» ربات.

- منوی «/» تلگرام (set_my_commands): کاربران عادی فقط دستورهای کاربری را می‌بینند؛ هر مدیر دستورهای
  کاربری + دستورهای مجاز خودش را (سطح «مدیر کامل» فقط برای مالک/مدیر کامل).
- لیست کامل برای مدیر: دستور /commands (در handlers_admin).
- هر دستور تازه‌ای که به ربات اضافه می‌شود را فقط همین‌جا به USER_COMMANDS / ADMIN_COMMANDS اضافه کنید.
"""
import asyncio
import html
import logging

from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

logger = logging.getLogger(__name__)

# (دستور، توضیح فارسی، توضیح انگلیسی، فقط ربات اصلی؟، داخل منوی «/»؟، راهنمای کاربرد)
USER_COMMANDS = (
    ("start", "شروع و منوی اصلی", "Start / main menu", False, True, ""),
    ("buy", "خرید سرویس", "Buy a service", False, True, ""),
    ("charge", "شارژ کیف پول", "Top up wallet", False, True, ""),
    ("help", "راهنما و آموزش", "Help and tutorials", False, True, ""),
    ("source", "سورس‌کد و لایسنس", "Source code and license", False, True, ""),
    ("language", "تغییر زبان", "Change language", False, True, ""),
    ("smartsub", "لینک اشتراک هوشمند", "Smart subscription link", False, True, "حداقل دو سرویس فعال لازم است"),
    ("myssh", "اطلاعات سرویس‌های SSH من", "My SSH accounts", False, True, "فقط در گفتگوی خصوصی"),
    ("payg", "پرداخت به‌ازای مصرف", "Pay as you go", True, True, ""),
    ("payg_history", "آخرین برداشت‌های پرداخت به‌ازای مصرف", "Pay-as-you-go history", True, False, ""),
    ("merge", "ادغام حساب فروشگاه وب با تلگرام", "Merge web store account", True, False, "/merge یا /merge کد"),
    ("transfer_wallet", "انتقال موجودی کیف پول", "Transfer wallet balance", False, False, "/transfer_wallet آیدی_عددی مبلغ"),
    ("reseller_link", "لینک نمایندگی (فقط نماینده‌ها)", "Reseller link (resellers only)", False, False, ""),
    ("wservices", "سرویس‌های من (ویجت)", "My services (widget)", False, False, "نیازمند فعال‌بودن ویجت‌ها"),
    ("wwallet", "کیف پول و دعوت (ویجت)", "Wallet and invites (widget)", False, False, "نیازمند فعال‌بودن ویجت‌ها"),
)

LEVEL_ADMIN = "admin"      # همه‌ی مدیران (از جمله پشتیبان)
LEVEL_SENIOR = "senior"    # فقط مالک و مدیر کامل

# (دستور، توضیح فارسی، توضیح انگلیسی، سطح، فقط ربات اصلی؟، داخل منوی «/»؟، راهنمای کاربرد)
ADMIN_COMMANDS = (
    ("admin", "پنل مدیریت", "Admin panel", LEVEL_ADMIN, False, True, ""),
    ("commands", "لیست همه‌ی دستورها", "List all commands", LEVEL_ADMIN, False, True, ""),
    ("ai", "دستیار هوشمند مدیر", "Admin AI assistant", LEVEL_SENIOR, False, True, "نیازمند تنظیم کلید AI"),
    ("update", "بررسی و نصب آپدیت", "Check for updates", LEVEL_SENIOR, False, True, ""),
    ("token2", "صدور توکن API", "Issue API token", LEVEL_ADMIN, False, True, "توکن قبلی همان ادمین باطل می‌شود"),
    ("giftadmin", "مدیریت کارت‌های هدیه", "Gift cards admin", LEVEL_ADMIN, False, True, ""),
    ("seasonadmin", "مدیریت فصل رقابتی و کوییز", "Season and quiz admin", LEVEL_ADMIN, False, True, ""),
    ("pin", "پین‌کردن پیام (ریپلای در گروه/کانال)", "Pin replied message", LEVEL_SENIOR, False, True, "فقط در گروه/کانال و با ریپلای"),
    ("unpin", "آن‌پین‌کردن پیام (ریپلای در گروه/کانال)", "Unpin replied message", LEVEL_SENIOR, False, True, "فقط در گروه/کانال و با ریپلای"),
    ("wstats", "ویجت آمار", "Stats widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("wfeatures", "ویجت مدیریت قابلیت‌ها", "Features widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("wqueue", "ویجت صف تایید", "Approval queue widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("whealth", "ویجت سلامت پنل‌ها", "Panel health widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("wusers", "ویجت مدیریت سریع کاربران", "Users widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("wpulse", "ویجت نبض زنده فروشگاه", "Live pulse widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("walerts", "ویجت مرکز هشدار", "Alerts widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("wtop", "ویجت برترین‌ها", "Top widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
    ("wanalysis", "ویجت تحلیل فروش", "Sales analysis widget", LEVEL_ADMIN, False, True, "نیازمند فعال‌بودن ویجت‌ها"),
)

_MENU_MAX = 100


# دستورهایی که به زیرساخت سراسری پلتفرم وصلند و حتی در نمایندگی کامل هم غیرفعال می‌مانند
# (سایت فروش وب / آپدیت پروژه).
_PLATFORM_ONLY = {"merge", "update"}


def _hidden_platform(cmd: str, real_main) -> bool:
    return cmd in _PLATFORM_ONLY and real_main is False


def _user_menu(is_main_bot: bool, lang: str, real_main=None):
    out = []
    real_main = is_main_bot if real_main is None else real_main
    for cmd, fa, en, main_only, in_menu, _hint in USER_COMMANDS:
        if _hidden_platform(cmd, real_main):
            continue
        if in_menu and (is_main_bot or not main_only):
            out.append(BotCommand(command=cmd, description=(en if lang == "en" else fa)[:256]))
    return out


def _admin_menu(is_main_bot: bool, is_senior: bool, lang: str, real_main=None):
    out = []
    real_main = is_main_bot if real_main is None else real_main
    for cmd, fa, en, level, main_only, in_menu, _hint in ADMIN_COMMANDS:
        if _hidden_platform(cmd, real_main):
            continue
        if not in_menu or (main_only and not is_main_bot):
            continue
        if level == LEVEL_SENIOR and not is_senior:
            continue
        out.append(BotCommand(command=cmd, description=(en if lang == "en" else fa)[:256]))
    return out


async def sync_admin_commands(bot, db, admin_id: int, is_main_bot: bool = True) -> bool:
    """منوی «/» یک مدیر را (کاربری + مدیریتی مجاز) ست می‌کند. اگر مدیر هنوز با بات چت نکرده باشد، بی‌صدا رد می‌شود."""
    try:
        senior = bool(await asyncio.to_thread(db.is_senior_admin, admin_id))
        scope = BotCommandScopeChat(chat_id=int(admin_id))
        full = bool(db.is_full_access_bot(is_main_bot))
        for lang in ("fa", "en"):
            cmds = (_user_menu(full, lang, is_main_bot) + _admin_menu(full, senior, lang, is_main_bot))[:_MENU_MAX]
            await bot.set_my_commands(cmds, scope=scope, language_code=("en" if lang == "en" else None))
        return True
    except Exception:
        logger.debug("ست‌کردن منوی دستورها برای مدیر %s ناموفق بود.", admin_id, exc_info=True)
        return False


async def sync_commands(bot, db, is_main_bot: bool = True) -> None:
    """منوی «/» پیش‌فرض (کاربران) + منوی اختصاصی هر مدیر. هیچ‌وقت exception نمی‌دهد."""
    try:
        full = bool(db.is_full_access_bot(is_main_bot))
        for lang in ("fa", "en"):
            await bot.set_my_commands(
                _user_menu(full, lang, is_main_bot), scope=BotCommandScopeDefault(),
                language_code=("en" if lang == "en" else None),
            )
    except Exception:
        logger.warning("ست‌کردن منوی دستورهای «/» ناموفق بود.", exc_info=True)
        return
    try:
        admin_ids = await asyncio.to_thread(db.list_admins)
    except Exception:
        logger.warning("خواندن لیست ادمین‌ها برای منوی دستورها ناموفق بود.", exc_info=True)
        return
    for admin_id in admin_ids:
        await sync_admin_commands(bot, db, admin_id, is_main_bot)
        await asyncio.sleep(0.2)


_bg_tasks: set = set()


def schedule_sync(bot, db, is_main_bot: bool = True) -> None:
    """هنگام استارت بات در پس‌زمینه اجرا می‌شود تا راه‌اندازی کند نشود."""
    task = asyncio.create_task(sync_commands(bot, db, is_main_bot))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def build_commands_text(is_main_bot: bool, is_senior: bool, real_main=None) -> str:
    """متن HTML لیست کامل دستورها برای مدیر (/commands)."""
    lines = ["📋 <b>لیست همه‌ی دستورهای ربات</b>", "", "👤 <b>دستورهای کاربران</b>"]
    real_main = is_main_bot if real_main is None else real_main
    for cmd, fa, _en, main_only, in_menu, hint in USER_COMMANDS:
        if (main_only and not is_main_bot) or _hidden_platform(cmd, real_main):
            continue
        extra = f" — <i>{html.escape(hint)}</i>" if hint else ""
        lines.append(f"/{cmd} — {html.escape(fa)}{extra}")
    lines += ["", "🛠 <b>دستورهای مدیران</b>"]
    hidden_senior = 0
    for cmd, fa, _en, level, main_only, in_menu, hint in ADMIN_COMMANDS:
        if (main_only and not is_main_bot) or _hidden_platform(cmd, real_main):
            continue
        if level == LEVEL_SENIOR and not is_senior:
            hidden_senior += 1
            continue
        tag = " 🔐" if level == LEVEL_SENIOR else ""
        extra = f" — <i>{html.escape(hint)}</i>" if hint else ""
        lines.append(f"/{cmd} — {html.escape(fa)}{tag}{extra}")
    lines += ["", "🔐 = فقط مالک و مدیر کامل"]
    if hidden_senior:
        lines.append(f"ℹ️ {hidden_senior} دستور سطح «مدیر کامل» برای نقش شما نمایش داده نشد.")
    return "\n".join(lines)
