# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
نقطه ورود - اجرا با: python main.py

این فایل بات اصلی را با توکن داخل .env راه‌اندازی می‌کند و سپس تمام
بات‌های نمایندگی که قبلاً از پنل مدیریت ثبت و فعال شده‌اند را هم به‌صورت
هم‌زمان (هرکدام با دیتابیس کاملاً مستقل خودشان) اجرا می‌کند.
"""

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from config import BOT_TOKEN, OWNER_ID, DB_PATH, BOT_MODE, resolve_db_path, resolve_reseller_db_path
from database import Database
from bot_manager import BotManager

os.makedirs("logs", exist_ok=True)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
_file_handler = RotatingFileHandler(
    "logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
)
logging.basicConfig(level=logging.INFO, handlers=[_file_handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)


async def _translation_health_loop(db):
    """Continuously recover languages quarantined by translation failures."""
    from translation_engine import sync_enabled_languages
    while True:
        try:
            await asyncio.to_thread(sync_enabled_languages, db, allow_network=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic translation health/recovery check failed.")
        await asyncio.sleep(900)


async def main():
    logger.info("حالت دریافت آپدیت: %s", BOT_MODE)
    manager = BotManager()

    # Automatic translation maintenance: enabled dynamic languages are synced
    # from the current English catalog before users can see them. If a provider
    # is unavailable or a translation is incomplete, that language is kept out
    # of user selection instead of producing mixed-language UI.
    try:
        main_translation_db = Database(DB_PATH)
        main_translation_db.init_db(owner_id=OWNER_ID)
    except Exception:
        logger.exception("Automatic language synchronization for the main bot failed.")

    # ۱. بات اصلی
    # قبلاً بدون try/except بود: اگر start_bot به هر دلیلی (مثلاً خطای موقت
    # تلگرام) exception می‌داد، کل main() می‌ترکید و چون سرویس با
    # Restart=always/RestartSec=5 اجرا می‌شود، این باعث یک چرخه‌ی کرش سریع‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    # می‌شد که می‌توانست چند دقیقه طول بکشد تا خودش تمام شود.
    try:
        await manager.start_bot(BOT_TOKEN, DB_PATH, OWNER_ID, is_main_bot=True)
        logger.info("بات اصلی راه‌اندازی شد.")
    except Exception:
        logger.exception("راه‌اندازی بات اصلی ناموفق بود.")

    # ۲. تمام بات‌های نمایندگیِ فعال (ثبت‌شده از پنل مدیریت بات اصلی)
    main_db = Database(DB_PATH)
    # سهمیه‌ی مشترک VPN/SSH برای دیتابیس اصلی و هر tenant جداگانه reconcile می‌شود.
    # اگر pool ای وجود نداشته باشد، worker هیچ تغییری روی سرویس‌ها اعمال نمی‌کند.
    from quota_reconciler import QuotaReconciler
    quota_tasks = [asyncio.create_task(QuotaReconciler(main_db).run_forever())]
    translation_health_tasks = []
    translation_health_tasks.append(asyncio.create_task(_translation_health_loop(main_translation_db)))
    reseller_bots = main_db.list_reseller_bots(active_only=True)
    # نماینده‌های «بدون بات واقعی» (has_live_bot=0 - فقط اعتبار/موجودی، بدون توکن
    # واقعی) نباید اینجا امتحان شوند؛ توکن‌شان قلابی است (مثل "no-bot:123:456") و
    # start_bot روی آن حتماً شکست می‌خورد. قبلاً این فیلتر نبود و فقط به‌خاطر
    # try/except دور هر آیتم (پایین‌تر) کرش نمی‌کرد، ولی بی‌فایده تلاش می‌شد.
    reseller_bots = [rb for rb in reseller_bots if (rb["has_live_bot"] if "has_live_bot" in rb.keys() else 1)]
    for rb in reseller_bots:
        resolved_path = resolve_reseller_db_path(rb["db_path"])
        if resolved_path != rb["db_path"]:
            main_db.set_reseller_db_path(rb["id"], resolved_path)
        if not os.path.isfile(resolved_path):
            logger.error(
                "نمایندگی @%s فعال است اما دیتابیس پیدا نشد؛ استارت رد شد تا دیتابیس خالی ساخته نشود: %s",
                rb["bot_username"], resolved_path,
            )
            continue
        # هماهنگ‌سازی شناسه‌ی تننت مینی‌اپ - باید قبل از start_bot باشد تا‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
        # لینک مینی‌اپ این نماینده از همون اول درست ساخته شود.
        try:
            reseller_db = Database(resolved_path)
            reseller_db.init_db(owner_id=rb["owner_telegram_id"])
            # از همان فرمول _reseller_miniapp_link در miniapp/server.py استفاده
            # می‌کنیم (اسلاگ در صورت وجود، وگرنه آیدی عددی) تا دکمه‌ی منوی بات
            # همیشه دقیقاً همان لینکی باشد که پنل مدیریت نشان می‌دهد/کپی می‌کند.
            reseller_db.set_setting("miniapp_tenant_id", rb["link_slug"] or str(rb["id"]))
            translation_health_tasks.append(asyncio.create_task(_translation_health_loop(reseller_db)))
            quota_tasks.append(asyncio.create_task(QuotaReconciler(reseller_db).run_forever()))
        except Exception:
            logger.exception("همگام‌سازی miniapp_tenant_id برای @%s ناموفق بود.", rb["bot_username"])

        try:
            started = await manager.start_bot(
                rb["bot_token"], resolved_path, rb["owner_telegram_id"], is_main_bot=False
            )
            if started:
                logger.info("بات نمایندگی @%s راه‌اندازی شد.", rb["bot_username"])
        except Exception:
            # قبلاً بدون try/except: خطای یک بات نماینده کل main() (و در نتیجه
            # بات اصلی و همه‌ی نماینده‌های دیگر) را هم با خودش می‌ترکاند.
            logger.exception("راه‌اندازی بات نمایندگی @%s ناموفق بود؛ رد شد.", rb["bot_username"])

    reconcile_task = asyncio.create_task(
        manager.reconcile_resellers_loop(main_db, BOT_TOKEN, interval=10)
    )
    import userbot
    userbot_task = asyncio.create_task(userbot.run(main_db, BOT_TOKEN))
    import leak_index
    leak_index_task = asyncio.create_task(leak_index.run(main_db))
    import leak_scanner
    leak_scanner_task = asyncio.create_task(leak_scanner.run_dedicated(main_db, BOT_TOKEN))

    try:
        await manager.wait_all()
    finally:
        for _task in quota_tasks:
            _task.cancel()
        for _task in quota_tasks:
            try:
                await _task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Quota reconciler shutdown failed.")
        for _task in translation_health_tasks:
            _task.cancel()
        for _task in translation_health_tasks:
            try:
                await _task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Translation health task shutdown failed.")
        reconcile_task.cancel()
        try:
            await reconcile_task
        except (Exception, asyncio.CancelledError):
            pass
        userbot_task.cancel()
        try:
            await userbot_task
        except (Exception, asyncio.CancelledError):
            pass
        leak_index_task.cancel()
        try:
            await leak_index_task
        except (Exception, asyncio.CancelledError):
            pass
        leak_scanner_task.cancel()
        try:
            await leak_scanner_task
        except (Exception, asyncio.CancelledError):
            pass
        await manager.stop_all()
        if manager.webhook_server:
            await manager.webhook_server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nبرنامه با Ctrl+C متوقف شد.")
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
