# -*- coding: utf-8 -*-
"""
مدیریت چند بات هم‌زمان (بات اصلی + هر بات نمایندگی).

هر بات یک Bot و Dispatcher مستقل خودش را دارد و روی یک asyncio task جداگانه
در حال polling است؛ اضافه/حذف‌کردن یک بات نمایندگی نیازی به ری‌استارت کل
پروسه ندارد.
"""

import asyncio
import hashlib
import logging
import os
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from fsm_storage import SQLiteStorage
from aiogram.types import MenuButtonWebApp, MenuButtonDefault, WebAppInfo, ErrorEvent

from config import (
    BOT_MODE, WEBHOOK_BASE_URL, WEBHOOK_SECRET,
    WEBHOOK_LISTEN_HOST, WEBHOOK_LISTEN_PORT,
)
from database import Database
from handlers_user import create_user_router
from handlers_admin import create_admin_router
from renewal_reminders import renewal_reminder_loop
from connect_alerts import connect_alert_loop
from backup import backup_loop
from temp_messages import temp_message_cleanup_loop
import extra_gateway_payment
from force_join import ForceJoinMiddleware
from blocked_user import BlockedUserMiddleware
from spam_guard import ThrottleMiddleware
from panel_health import panel_health_loop
from daily_report import daily_report_loop
from cleanup_loop import cleanup_loop
from lottery_loop import lottery_loop
from signup_gift import signup_gift_loop
from report_router import ReportGroupGuardMiddleware
from global_switch import GlobalBotSwitchMiddleware
import keyboards as kb
import tutorial_hub
from i18n import (
    tr, set_language, reset_language, normalize_language, get_language,
    start_missing_tracking, stop_missing_tracking, pop_missing_lookups, merge_language_catalog,
)
from broadcast_i18n import send_scheduled_broadcast

logger = logging.getLogger(__name__)


async def scheduled_broadcast_loop(bot, db):
    from datetime import datetime
    while True:
        try:
            jobs=await asyncio.to_thread(db.get_due_scheduled_broadcasts, datetime.utcnow().isoformat())
            for job in jobs:
                user_ids=await asyncio.to_thread(db.get_all_user_ids)
                sent=failed=0
                for uid in user_ids:
                    try:
                        await send_scheduled_broadcast(bot, uid, job["message_text"])
                        sent+=1
                    except Exception:
                        failed+=1
                    await asyncio.sleep(0.05)
                await asyncio.to_thread(db.mark_scheduled_broadcast, job["id"], "sent", sent, failed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduled broadcast loop failed")
        await asyncio.sleep(20)


class LanguageMiddleware:
    """Loads the user's persisted language for every Telegram update."""
    def __init__(self, db):
        self.db = db

    async def __call__(self, handler, event, data: dict):
        user = data.get("event_from_user")
        token = None
        missing_token = None
        try:
            if user is not None:
                try:
                    row = await asyncio.to_thread(self.db.get_user, user.id)
                except Exception:
                    row = None
                language = (row["language_code"] if row and "language_code" in row.keys() else None)
                language = normalize_language(language or getattr(user, "language_code", None))
                catalog = await asyncio.to_thread(self.db.translation_catalog, language) if language not in {"fa", "en"} and await asyncio.to_thread(self.db.get_language, language) else None
                token = set_language(language, catalog)
                if language not in {"fa", "en"}:
                    # Collects any tr() misses for this update so TranslatingBot
                    # can translate them on demand right before sending.
                    missing_token = start_missing_tracking()
            return await handler(event, data)
        finally:
            if missing_token is not None:
                stop_missing_tracking(missing_token)
            if token is not None:
                reset_language(token)


def _patch_method_texts(method, generated: dict) -> None:
    """Replace already-built fallback strings with their fresh translation
    directly inside an outgoing aiogram request, in place, right before it is
    sent. Longer strings are replaced first so a short phrase can't clobber
    part of a longer string that happens to contain it."""
    replacements = sorted(generated.items(), key=lambda kv: len(kv[0]), reverse=True)

    def patch(value):
        if not isinstance(value, str) or not value:
            return value
        for src, dst in replacements:
            if src in value:
                value = value.replace(src, dst)
        return value

    for attr in ("text", "caption"):
        value = getattr(method, attr, None)
        if isinstance(value, str):
            try:
                setattr(method, attr, patch(value))
            except Exception:
                pass

    markup = getattr(method, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None)
    if rows:
        for row in rows:
            for button in row:
                text = getattr(button, "text", None)
                if isinstance(text, str):
                    try:
                        button.text = patch(text)
                    except Exception:
                        pass

    # Reply keyboards are the main menu in ShopVPN.  Previously only inline
    # keyboards were patched, so the translation was correctly generated and
    # saved in DB but the user still saw the original English fallback in the
    # bottom keyboard.  Patch every KeyboardButton in the regular keyboard as
    # well, using the same replacements.
    reply_rows = getattr(markup, "keyboard", None)
    if reply_rows:
        for row in reply_rows:
            for button in row:
                text = getattr(button, "text", None)
                if isinstance(text, str):
                    try:
                        button.text = patch(text)
                    except Exception:
                        pass


class TranslatingBot(Bot):
    """Bot subclass that fills in missing dynamic-language translations on demand.

    Every outgoing Telegram API call (send/edit message, callback answers, ...)
    passes through ``Bot.__call__``. If the current update's language is a
    dynamic one (not fa/en) and ``tr()`` hit strings missing from that
    language's catalog while building this request (see
    ``i18n.note_missing``/``LanguageMiddleware``), we translate exactly those
    strings here — once, synchronously, right before sending — persist them so
    every future lookup (by any user) is instant, and patch them into this
    outgoing request so the user never sees an untranslated fallback. Requests
    made outside a tracked update (background loops, broadcasts) are
    untouched, since there is nothing to drain for them.
    """

    def __init__(self, *args, translation_db=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._translation_db = translation_db

    async def __call__(self, method, request_timeout=None):
        db = self._translation_db
        if db is not None and get_language() not in ("fa", "en"):
            missing = pop_missing_lookups()
            if missing:
                lang = get_language()
                try:
                    from translation_engine import translate_texts_now
                    generated = await asyncio.to_thread(translate_texts_now, db, lang, missing)
                except Exception:
                    logger.warning("ترجمه‌ی لحظه‌ای برای زبان %s ناموفق بود.", lang, exc_info=True)
                    generated = {}
                if generated:
                    merge_language_catalog(generated)
                    _patch_method_texts(method, generated)
        return await super().__call__(method, request_timeout=request_timeout)


class AdminPresenceMiddleware:
    """با هر پیام/کلیک یک ادمین در بات، حضور آنلاین او را ثبت می‌کند تا پیام‌های
    جدید پشتیبانی زنده به اولین ادمین/مالک آنلاین مسیریابی شوند (نه به همه).

    برای این هدف نیازی نیست *هر* کلیک واقعاً روی دیتابیس نوشته شود (آستانه‌ی
    آنلاین‌بودن ۹۰ ثانیه است - PRESENCE_ONLINE_SECONDS در database.py). قبلاً
    هر کلیک/پیام ادمین یک نوشتن synchronous جدا به sqlite می‌زد؛ چون این کار
    روی همان event loop مشترک همه‌ی بات‌ها اجرا می‌شود، با هر برخورد به قفل
    (مثلاً هم‌زمانی با Mini App) کل بات برای همه فریز می‌شد - و چون ادمین‌ها
    (برخلاف کاربر عادی) هر کلیک پنل مدیریت هم از همین مسیر رد می‌شوند، این
    فریز بیشتر روی دکمه‌های پنل مدیریت حس می‌شد. با این throttle، هر ادمین
    حداکثر هر PRESENCE_WRITE_INTERVAL ثانیه یک‌بار واقعاً روی دیتابیس نوشته
    می‌شود؛ کلیک‌های بین این فاصله فقط از حافظه چک می‌شوند و اصلاً وارد sqlite
    نمی‌شوند."""

    PRESENCE_WRITE_INTERVAL = 20  # ثانیه

    def __init__(self, db):
        self.db = db
        self._last_write = {}  # tg_id -> time.monotonic() آخرین نوشتن واقعی

    async def __call__(self, handler, event, data: dict):
        user = data.get("event_from_user")
        if user is not None and self.db.is_admin(user.id):
            now = time.monotonic()
            last = self._last_write.get(user.id, 0.0)
            if now - last >= self.PRESENCE_WRITE_INTERVAL:
                self._last_write[user.id] = now
                try:
                    # throttle شده (هر ۲۰ ثانیه) ولی هنوز یک نوشتن sqlite
                    # synchronous است؛ با to_thread تا مطمئن شویم دقیقاً همین
                    # نوشتن نمی‌تواند کل بات را برای همه فریز کند.
                    await asyncio.to_thread(self.db.touch_admin_presence, user.id)
                except Exception:
                    pass
        return await handler(event, data)


async def _global_error_handler(event: ErrorEvent) -> bool:
    """هندلر سراسری خطا.

    بدون این، وقتی هندلر یک دکمه‌ی شیشه‌ای (callback_query) با یک خطای
    پیش‌بینی‌نشده مواجه می‌شود (مثلاً callback_data مربوط به یک محصول/سفارش/کد
    تخفیفی که دیگر وجود ندارد)، await call.answer() هرگز اجرا نمی‌شود و از
    دید کاربر دکمه فقط «لودینگ» می‌ماند و بعد بدون هیچ واکنشی متوقف می‌شود —
    یعنی دقیقاً همان «کلید کار نمی‌کند». این هندلر خطا را لاگ می‌کند و در صورت
    امکان همان callback را با یک پیام کوتاه answer می‌کند تا کاربر دست‌کم
    بفهمد خطایی رخ داده، نه اینکه بات فریز کرده.
    """
    logger.error("خطای پردازش‌نشده در آپدیت: %s", event.exception, exc_info=event.exception)
    cq = event.update.callback_query
    if cq is not None:
        try:
            await cq.answer(tr("⚠️ خطایی رخ داد، دوباره تلاش کنید."), show_alert=False)
        except Exception:
            pass
        return True
    # قبلاً برای آپدیت‌های message (مثل عکس رسید که هندلرش exception می‌دهد،
    # مثلاً به‌خاطر قفل موقت SQLite) این تابع فقط لاگ می‌کرد و برمی‌گشت -
    # یعنی کاربر و ادمین هیچ‌کدام هیچ پیامی نمی‌گرفتند و از دید هر دو انگار
    # آن پیام اصلاً نرسیده بود. حالا حداقل به خود کاربر اطلاع می‌دهیم که
    # چیزی خراب شده تا او بداند دوباره تلاش کند، نه اینکه فکر کند رسیدش
    # درست ثبت شده و منتظر تایید بماند.
    msg = event.update.message
    if msg is not None:
        try:
            await msg.answer(tr("⚠️ در پردازش پیام شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."))
        except Exception:
            pass
    return True


def _webhook_path_for_token(token: str) -> str:
    """مسیر وب‌هوک از روی هش توکن ساخته می‌شود تا خود توکن داخل URL/لاگ‌های
    nginx ظاهر نشود."""
    return hashlib.sha256(token.encode()).hexdigest()


class WebhookServer:
    """یک سرور aiohttp مشترک برای دریافت وب‌هوک همه‌ی بات‌ها (اصلی + هر تعداد
    بات نمایندگی). چون هر بات Dispatcher کاملاً مستقل خودش را دارد (middleware
    و روترهای بسته‌شده به دیتابیس خودش)، امکان استفاده از یک Dispatcher مشترک
    برای همه نیست؛ به‌جای ثبت یک مسیر ثابت برای هر بات هم (که چون روتر aiohttp
    بعد از بالا آمدن سرور فریز می‌شود، اضافه‌کردن مسیر جدید برای یک بات
    نمایندگی که بعداً اضافه می‌شود امکان‌پذیر نیست)، فقط یک مسیر پویا
    (/webhook/{token_hash}) یک‌بار در ابتدا ثبت می‌شود و نگاشت هر token_hash
    به هندلر مربوطه‌اش در یک دیکشنری معمولی نگه داشته می‌شود که در طول اجرا
    (افزودن/حذف نماینده) آزادانه قابل تغییر است."""

    def __init__(self):
        self._handlers = {}  # token_hash -> SimpleRequestHandler
        self._app = web.Application()
        self._app.router.add_post("/webhook/{token_hash}", self._dispatch)
        self._runner = None  # web.AppRunner | None
        self.started = False

    async def start(self, host: str, port: int) -> None:
        if self.started:
            return
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        self.started = True
        logger.info("سرور وب‌هوک روی %s:%s بالا آمد.", host, port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self.started = False

    def register(self, token: str, bot: Bot, dp: Dispatcher) -> None:
        self._handlers[_webhook_path_for_token(token)] = SimpleRequestHandler(dispatcher=dp, bot=bot)

    def unregister(self, token: str) -> None:
        self._handlers.pop(_webhook_path_for_token(token), None)

    async def _dispatch(self, request: web.Request) -> web.StreamResponse:
        if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            return web.Response(status=401)
        handler = self._handlers.get(request.match_info.get("token_hash", ""))
        if handler is None:
            return web.Response(status=404)
        return await handler.handle(request)


class BotManager:
    def __init__(self):
        self.instances = {}  # token -> {"bot": Bot, "dp": Dispatcher, "task": asyncio.Task, "db_path": str}
        self.webhook_server = WebhookServer() if BOT_MODE == "webhook" else None

    async def _sync_menu_button(self, bot: Bot, db) -> None:
        """دکمه‌ی منو (کنار باکس پیام) را روی مینی‌اپ همین بات ست می‌کند.
        چون از Menu Button باز می‌شود، initData واقعی و معتبر تولید می‌شود
        (برخلاف دکمه‌ی reply keyboard که initData همیشه خالی است).
        این کار کاملاً خودکار است؛ نماینده هیچ کاری (دامنه/BotFather) لازم ندارد."""
        miniapp_url = kb._miniapp_url(db)
        try:
            if miniapp_url:
                await bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(text=tr("فروشگاه"), web_app=WebAppInfo(url=miniapp_url))
                )
            else:
                await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
        except Exception:
            logger.warning("ست‌کردن Menu Button ناموفق بود.", exc_info=True)

    async def start_bot(self, token: str, db_path: str, owner_id: int, is_main_bot: bool = False) -> bool:
        """یک بات جدید (اصلی یا نمایندگی) را با دیتابیس مستقل خودش راه‌اندازی می‌کند.
        اگر توکن از قبل در حال اجرا باشد، کاری نمی‌کند و False برمی‌گرداند."""
        if token in self.instances:
            return False

        db = Database(db_path)
        db.init_db(owner_id=owner_id)
        # Dedicated reseller bots are intentionally a near-complete copy of the
        # main bot.  The only missing capability is the main-bot-only reseller
        # management section (create/approve/manage other full resellers).
        if not is_main_bot:
            db.set_setting("bot_role", "full_reseller")

        bot = TranslatingBot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML), translation_db=db)
        # قبلاً MemoryStorage (فقط RAM) بود که با هر ری‌استارت پروسه state‌های
        # در حال انتظار (از جمله «منتظر عکس رسید») را پاک می‌کرد و باعث گم‌شدن
        # رسیدهایی می‌شد که دقیقاً همان لحظه می‌رسیدند؛ حالا روی یک فایل SQLite
        # کنار دیتابیس همان بات ذخیره می‌شود تا بعد از ری‌استارت هم بماند.
        fsm_db_path = f"{db_path}.fsm.sqlite3"
        try:
            fsm_storage = SQLiteStorage(fsm_db_path)
        except Exception:
            logger.exception(
                "ساخت SQLiteStorage برای FSM با db_path=%s ناموفق بود؛ استفاده‌ی موقت از MemoryStorage.",
                fsm_db_path,
            )
            fsm_storage = MemoryStorage()
        dp = Dispatcher(storage=fsm_storage)
        dp.errors.register(_global_error_handler)
        language_mw = LanguageMiddleware(db)
        dp.message.outer_middleware(language_mw)
        dp.callback_query.outer_middleware(language_mw)


        report_guard_mw = ReportGroupGuardMiddleware(db)
        dp.message.outer_middleware(report_guard_mw)
        dp.callback_query.outer_middleware(report_guard_mw)

        blocked_mw = BlockedUserMiddleware(db)
        dp.message.outer_middleware(blocked_mw)
        dp.callback_query.outer_middleware(blocked_mw)

        global_switch_mw = GlobalBotSwitchMiddleware(db)
        dp.message.outer_middleware(global_switch_mw)
        dp.callback_query.outer_middleware(global_switch_mw)

        throttle_mw = ThrottleMiddleware(db)
        dp.message.outer_middleware(throttle_mw)
        dp.callback_query.outer_middleware(throttle_mw)

        presence_mw = AdminPresenceMiddleware(db)
        dp.message.outer_middleware(presence_mw)
        dp.callback_query.outer_middleware(presence_mw)

        force_join_mw = ForceJoinMiddleware(db)
        dp.message.outer_middleware(force_join_mw)
        dp.callback_query.outer_middleware(force_join_mw)

        tutorial_hub.install(bot, dp, db)

        dp.include_router(create_admin_router(db, is_main_bot=is_main_bot, bot_manager=self))
        dp.include_router(create_user_router(db, is_main_bot=is_main_bot, bot_manager=self))

        # قبلاً بدون try/except بود: اگر همین یک تماس (مثلاً به‌خاطر FloodWait یا
        # قطعی موقت شبکه‌ی تلگرام) خطا می‌داد، کل main() با exception می‌ترکید و
        # چون پروسه با systemd (Restart=always, RestartSec=5) اجرا می‌شود، هر ۵
        # ثانیه دوباره تلاش می‌کرد - و چون این تلاش خودش دوباره به همین API
        # می‌خورد، محدودیت تلگرام هر بار بزرگ‌تر می‌شد؛ از دید کاربر این حالت
        # دقیقاً شبیه «۱۵-۲۰ دقیقه کرش‌کردن پشت سر هم بعد از هر ری‌استارت» است.
        if BOT_MODE == "webhook":
            if self.webhook_server is None:
                self.webhook_server = WebhookServer()
            await self.webhook_server.start(WEBHOOK_LISTEN_HOST, WEBHOOK_LISTEN_PORT)
            webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{_webhook_path_for_token(token)}"
            try:
                await bot.set_webhook(
                    webhook_url,
                    secret_token=WEBHOOK_SECRET or None,
                    drop_pending_updates=True,
                )
            except Exception:
                logger.warning(
                    "set_webhook برای db_path=%s ناموفق بود؛ راه‌اندازی بات ادامه می‌یابد.",
                    db_path, exc_info=True,
                )
            self.webhook_server.register(token, bot, dp)
            # جایگزین polling task: چون در حالت webhook تسک polling وجود ندارد،
            # یک تسک بی‌پایان نگه می‌داریم تا wait_all/stop_bot با همان منطق
            # فعلی (که یک asyncio.Task برای هر بات انتظار دارد) کار کنند؛ این
            # تسک هیچ‌وقت خودش تمام/خطا نمی‌شود، فقط با cancel در stop_bot
            # متوقف می‌شود.
            task = asyncio.create_task(asyncio.Event().wait())
        else:
            try:
                await bot.delete_webhook(drop_pending_updates=True)
            except Exception:
                logger.warning(
                    "delete_webhook برای db_path=%s ناموفق بود؛ راه‌اندازی بات ادامه می‌یابد.",
                    db_path, exc_info=True,
                )
            task = asyncio.create_task(dp.start_polling(bot))
        await self._sync_menu_button(bot, db)
        reminder_task = asyncio.create_task(renewal_reminder_loop(bot, db))
        connect_alert_task = asyncio.create_task(connect_alert_loop(bot, db))
        backup_task = asyncio.create_task(backup_loop(bot, db, db_path))
        # جلوگیری از فریز کل بات هنگام انقضای کش تنظیمات/ادمین‌ها (رجوع کنید
        # به توضیح داخل Database.cache_autorefresh_loop)
        cache_refresh_task = asyncio.create_task(db.cache_autorefresh_loop())
        temp_msg_task = asyncio.create_task(temp_message_cleanup_loop(bot, db))
        extra_gateway_task = (
            asyncio.create_task(extra_gateway_payment.poll_loop(bot, db)) if is_main_bot else None
        )
        panel_health_task = asyncio.create_task(panel_health_loop(bot, db)) if is_main_bot else None
        daily_report_task = asyncio.create_task(daily_report_loop(bot, db))
        scheduled_broadcast_task = asyncio.create_task(scheduled_broadcast_loop(bot, db))
        cleanup_task = asyncio.create_task(cleanup_loop(bot, db))
        lottery_task = asyncio.create_task(lottery_loop(bot, db))
        reseller_expiry_task = asyncio.create_task(db.reseller_expiry_loop(bot))
        signup_gift_task = asyncio.create_task(signup_gift_loop(bot, db))

        self.instances[token] = {
            "bot": bot, "dp": dp, "task": task, "reminder_task": reminder_task,
            "connect_alert_task": connect_alert_task,
            "backup_task": backup_task, "cache_refresh_task": cache_refresh_task,
            "temp_msg_task": temp_msg_task, "extra_gateway_task": extra_gateway_task,
            "panel_health_task": panel_health_task, "daily_report_task": daily_report_task,
            "scheduled_broadcast_task": scheduled_broadcast_task,
            "cleanup_task": cleanup_task, "lottery_task": lottery_task,
            "reseller_expiry_task": reseller_expiry_task, "signup_gift_task": signup_gift_task,
            "db_path": db_path,
        }
        logger.info("بات با db_path=%s راه‌اندازی شد.", db_path)
        return True

    _STOP_TASK_KEYS = (
        "reminder_task", "connect_alert_task", "backup_task",
        "scheduled_broadcast_task", "cache_refresh_task", "temp_msg_task",
        "extra_gateway_task", "panel_health_task", "daily_report_task",
        "cleanup_task", "lottery_task", "reseller_expiry_task", "signup_gift_task",
    )

    async def stop_bot(self, token: str) -> bool:
        inst = self.instances.pop(token, None)
        if not inst:
            return False
        inst["task"].cancel()
        try:
            await inst["task"]
        except Exception:
            pass
        for key in self._STOP_TASK_KEYS:
            task = inst.get(key)
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except Exception:
                pass
        if BOT_MODE == "webhook" and self.webhook_server is not None:
            self.webhook_server.unregister(token)
            try:
                await inst["bot"].delete_webhook(drop_pending_updates=False)
            except Exception:
                pass
        try:
            await inst["bot"].session.close()
        except Exception:
            pass
        try:
            await inst["dp"].storage.close()
        except Exception:
            pass
        logger.info("بات با db_path=%s متوقف شد.", inst["db_path"])
        return True

    async def stop_all(self):
        for token in list(self.instances.keys()):
            await self.stop_bot(token)

    def is_running(self, token: str) -> bool:
        return token in self.instances

    async def wait_all(self):
        """تا وقتی حداقل یک بات در حال اجراست، برنامه را زنده نگه می‌دارد.

        قبلاً وقتی task یک بات (مثلاً به‌خاطر یک خطای غیرمنتظره یا حتی بدون
        خطا) تمام می‌شد، همچنان داخل self.instances می‌ماند؛ در نتیجه از آن به
        بعد asyncio.wait() در هر تکرار حلقه فوراً (چون آن task از قبل done
        بود) بدون هیچ sleep واقعی برمی‌گشت - یک busy loop که روی همان تک event
        loop مشترک تمام بات‌ها اجرا می‌شود و به‌شدت آن را اشغال می‌کند؛ از دید
        کاربر دقیقاً شبیه «هیچ کلیدی جواب نمی‌دهد» است، بدون اینکه لزوماً
        Exception ای هم لاگ شود (اگر آن task بدون خطا، فقط return شده باشد).
        حالا بات از کار افتاده کامل پاک/متوقف می‌شود (تا از حلقه‌ی بعدی حذف
        شود) و در هر تکرار یک sleep واقعی تضمین شده است."""
        while True:
            tasks = [inst["task"] for inst in self.instances.values()]
            if not tasks:
                await asyncio.sleep(1)
                continue
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for d in done:
                exc = d.exception() if not d.cancelled() else None
                token = next((t for t, inst in self.instances.items() if inst["task"] is d), None)
                if exc and not isinstance(exc, asyncio.CancelledError):
                    logger.error("یکی از بات‌ها با خطا متوقف شد: %s", exc)
                else:
                    logger.error("یکی از بات‌ها بدون خطای صریح polling را متوقف کرد (احتمالاً Conflict/قطع اتصال).")
                if token:
                    await self.stop_bot(token)
            await asyncio.sleep(1)

    async def reconcile_resellers_loop(self, main_db, main_bot_token: str, interval: int = 10):
        """هر چند ثانیه یک‌بار وضعیت بات‌های نمایندگی را با جدول reseller_bots
        (منبع حقیقت) مقایسه و همگام می‌کند. این باعث می‌شود تغییراتی که از طریق
        Mini App (که در یک پروسه‌ی جدا از این بات اجرا می‌شود و مستقیماً به
        BotManager دسترسی ندارد) روی دیتابیس اعمال می‌شوند - مثل افزودن،
        فعال/غیرفعال‌کردن یا حذف یک نماینده - با تأخیر کوتاهی خودکار اجرا شوند،
        بدون نیاز به ری‌استارت کل سرویس."""
        from config import resolve_db_path
        while True:
            await asyncio.sleep(interval)
            try:
                rows = main_db.list_reseller_bots()
                # نکته (باگ قبلی): نماینده‌های «بدون بات واقعی» (بات_choice=none/inline_link)
                # با has_live_bot=0 و یک توکن قلابی (مثل "no-bot:123:456") ثبت می‌شوند تا
                # فقط اعتبار/موجودی داشته باشند. این حلقه قبلاً این فلگ را چک نمی‌کرد و
                # سعی می‌کرد با همان توکن قلابی یک Bot() واقعی بسازد که بلافاصله با خطای
                # اعتبارسنجی فرمت توکن می‌ترکید؛ چون آن خطا داخل خودِ for گرفته نمی‌شد،
                # کل بقیه‌ی نماینده‌های همان دور (حتی نماینده‌های واقعی با بات زنده) اصلاً
                # پردازش نمی‌شدند. الان چنین ردیف‌هایی از همان ابتدا کنار گذاشته می‌شوند.
                active_tokens = {
                    r["bot_token"]: r for r in rows
                    if r["is_active"] and (r["has_live_bot"] if "has_live_bot" in r.keys() else 1)
                }
                all_tokens = {r["bot_token"] for r in rows}

                for token, row in active_tokens.items():
                    if token not in self.instances:
                        resolved_path = resolve_db_path(row["db_path"])
                        # قبل از استارت، شناسه‌ی تننت مینی‌اپ را sync کن - دقیقاً مثل
                        # حلقه‌ی استارتاپ در main.py - وگرنه اگر این تنظیم روی
                        # دیتابیس نماینده هنوز ست نشده باشد (مثلاً به‌خاطر تایمینگ
                        # ثبت از پنل یا ری‌استور بکاپ)، دکمه‌ی منوی بات با لینک
                        # مینی‌اپ بدون ?b= ساخته می‌شود و initData او با توکن بات
                        # اصلی چک می‌شود (نه توکن خودش) -> خطای «initData نامعتبر است».
                        try:
                            reseller_db = Database(resolved_path)
                            reseller_db.init_db(owner_id=row["owner_telegram_id"])
                            # فرمول یکسان با _reseller_miniapp_link (اسلاگ در
                            # صورت وجود، وگرنه آیدی عددی) - وگرنه لینکی که پنل
                            # مدیریت نشان می‌دهد با لینک واقعی دکمه‌ی منوی بات
                            # یکی نمی‌شود.
                            reseller_db.set_setting("miniapp_tenant_id", row["link_slug"] or str(row["id"]))
                        except Exception:
                            logger.exception(
                                "همگام‌سازی miniapp_tenant_id برای @%s (reconcile) ناموفق بود.",
                                row["bot_username"],
                            )
                        # این فراخوانی هم عمداً try/except جدا و مستقل از خودش دارد (نه فقط
                        # try/except دور کل تابع در انتهای فایل): اگر یک نماینده (به هر
                        # دلیلی، مثلاً توکن باطل‌شده توسط خودِ صاحبش در BotFather) در ساخت
                        # Bot()/start_bot خطا بدهد، نباید مانع پردازش بقیه‌ی نماینده‌های
                        # همان دور از حلقه بشود.
                        try:
                            started = await self.start_bot(
                                token, resolved_path, row["owner_telegram_id"], is_main_bot=False
                            )
                            if started:
                                logger.info("بات نمایندگی @%s توسط reconcile راه‌اندازی شد.", row["bot_username"])
                        except Exception:
                            logger.exception(
                                "راه‌اندازی بات نمایندگی @%s توسط reconcile ناموفق بود؛ رد شد.",
                                row["bot_username"],
                            )

                # ترمیم مداوم Menu Button بات‌های نمایندگی که از قبل در حال اجرا
                # بودند: هر چرخه (هر ۱۰ ثانیه) بررسی می‌شود که آیا
                # miniapp_tenant_id روی دیتابیس‌شان با «آخرین اسلاگ/آیدی» جدول
                # reseller_bots (منبع حقیقت، قابل تغییر با دکمه‌ی «تغییر لینک
                # مینی‌اپ» در پنل مدیریت که در یک پروسه‌ی جدا اجرا می‌شود) یکی
                # است یا نه؛ اگر نه، هم تنظیم داخلی و هم Menu Button واقعی بات
                # به‌روزرسانی می‌شود - بدون نیاز به ری‌استارت بات.
                #
                # نکته‌ی مهم (باگ قبلی): قبلاً این کار فقط *یک‌بار* در طول عمر
                # هر instance انجام می‌شد (پرچم menu_checked)، پس اگر ادمین بعداً
                # از دکمه‌ی «تغییر لینک مینی‌اپ» لینک را عوض می‌کرد، بات
                # نمایندگی‌ای که از قبل روشن بود هیچ‌وقت لینک جدید را نمی‌گرفت
                # و همچنان لینک قدیمی را در دکمه‌ی منویش نشان می‌داد - دقیقاً
                # همان چیزی که ادمین «هنوز لینک قدیمی را نشان می‌دهد» می‌دید.
                for token, row in active_tokens.items():
                    inst = self.instances.get(token)
                    if not inst:
                        continue
                    try:
                        resolved_path = resolve_db_path(row["db_path"])
                        reseller_db = Database(resolved_path)
                        expected = row["link_slug"] or str(row["id"])
                        current = reseller_db.get_setting("miniapp_tenant_id", "")
                        if current != expected:
                            reseller_db.set_setting("miniapp_tenant_id", expected)
                            logger.warning(
                                "miniapp_tenant_id برای @%s نادرست/قدیمی بود (%r) و به %r اصلاح شد.",
                                row["bot_username"], current, expected,
                            )
                            await self._sync_menu_button(inst["bot"], reseller_db)
                        elif not inst.get("menu_checked"):
                            # حتی وقتی مقدار درست است، حداقل یک‌بار در طول عمر
                            # instance مطمئن می‌شویم Menu Button واقعی هم واقعاً
                            # sync شده (مثلاً اگر تلاش قبلی موقع استارت‌آپ به‌خاطر
                            # قطعی موقت تلگرام شکست خورده باشد).
                            await self._sync_menu_button(inst["bot"], reseller_db)
                        inst["menu_checked"] = True
                    except Exception:
                        logger.exception("ترمیم Menu Button برای @%s ناموفق بود.", row["bot_username"])

                for token in list(self.instances.keys()):
                    if token == main_bot_token:
                        continue
                    if token not in active_tokens:
                        # یا غیرفعال شده یا کاملاً حذف شده (دیگر در all_tokens هم نیست)
                        await self.stop_bot(token)
                        logger.info(
                            "بات نمایندگی (token=...%s) توسط reconcile متوقف شد (غیرفعال/حذف‌شده).", token[-6:]
                        )

                # پاک‌کردن فایل دیتابیس نماینده‌های حذف‌شده فقط بعد از اطمینان از
                # اینکه بات‌شان کاملاً متوقف شده (تا با یک connection زنده روی
                # همان فایل رقابت نکند و باعث ساخته‌شدن دوباره‌ی یک دیتابیس خالی نشود).
                for purge_row in main_db.list_pending_db_purges():
                    if purge_row["bot_token"] in self.instances:
                        continue
                    try:
                        if os.path.exists(purge_row["db_path"]):
                            os.remove(purge_row["db_path"])
                        # فایل storage پایدار FSM (و فایل‌های کمکی WAL/SHM کنارش)
                        # هم مربوط به همین بات نماینده هستند و باید با خودش پاک شوند.
                        for suffix in (".fsm.sqlite3", ".fsm.sqlite3-wal", ".fsm.sqlite3-shm"):
                            fsm_file = purge_row["db_path"] + suffix
                            if os.path.exists(fsm_file):
                                os.remove(fsm_file)
                        main_db.remove_pending_db_purge(purge_row["id"])
                        logger.info("فایل دیتابیس نماینده‌ی حذف‌شده پاک شد: %s", purge_row["db_path"])
                    except OSError:
                        logger.exception("پاک‌کردن فایل دیتابیس نماینده ناموفق بود: %s", purge_row["db_path"])
            except Exception:
                logger.exception("خطا در حلقه‌ی reconcile نمایندگی‌ها.")
