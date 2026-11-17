# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
بکاپ خودکار دیتابیس.

هر بات (اصلی یا نمایندگی)، به‌طور دوره‌ای از دیتابیس خودش یک بکاپ امن می‌گیرد
(با استفاده از SQLite Backup API، که برخلاف کپی‌کردن ساده‌ی فایل، حتی اگر
دیتابیس در حال استفاده باشد باعث خرابی نمی‌شود)، آن را در پوشه‌ی «backups» کنار
همان دیتابیس ذخیره می‌کند (و فقط چند نسخه‌ی آخر را نگه می‌دارد)، و آخرین بکاپ را
برای همه‌ی ادمین‌های همان بات به‌عنوان فایل تلگرامی می‌فرستد — تا حتی اگر خود
سرور/هارد از بین برود، یک نسخه‌ی جدا هم روی تلگرام موجود باشد.
"""

import os
import glob
import sqlite3
import asyncio
import logging
import zipfile
from datetime import datetime
from typing import Optional

import report_router

logger = logging.getLogger(__name__)


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def create_backup(db_path: str, backup_dir: str, keep: int = 14) -> Optional[str]:
    """یک بکاپ امن از دیتابیس می‌سازد و بکاپ‌های قدیمی‌تر از `keep` نسخه‌ی آخر را
    حذف می‌کند. مسیر فایل بکاپ ساخته‌شده را برمی‌گرداند، یا None اگر دیتابیس
    وجود نداشت."""
    if not os.path.exists(db_path):
        return None

    os.makedirs(backup_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(db_path))[0]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"{base_name}_{timestamp}.db")

    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    pattern = os.path.join(backup_dir, f"{base_name}_*.db")
    existing = sorted(glob.glob(pattern))
    for old_file in existing[:-keep]:
        try:
            os.remove(old_file)
        except OSError:
            pass

    return backup_path
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


def create_full_backup(main_db, main_db_path: str, output_dir: str, keep: int = 5) -> Optional[str]:
    """یک بکاپ «کامل» می‌سازد: دیتابیس بات اصلی + دیتابیس تک‌تک نماینده‌ها
    (چه سطح یک/کامل و چه سطح دو/ساده، فعال یا غیرفعال) را همه با هم در یک
    فایل zip واحد بسته‌بندی می‌کند.

    فقط برای بات اصلی معنا دارد (چون فقط دیتابیس بات اصلی جدول reseller_bots
    و مسیر دیتابیس نماینده‌ها را می‌شناسد). هدف این است که وقتی کل سرویس به یک
    سرور دیگر منتقل می‌شود، یک فایل تنها کافی باشد و اطلاعات نماینده‌ها جا
    نماند (که با بکاپ معمولی که فقط دیتابیس بات اصلی را می‌گیرد، ممکن است.)

    خروجی: مسیر فایل zip ساخته‌شده، یا None اگر حتی دیتابیس اصلی هم پیدا نشد.
    """
    if not os.path.exists(main_db_path):
        return None

    from config import resolve_db_path  # اینجا import می‌شود تا import چرخه‌ای پیش نیاید

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(output_dir, f"full_backup_{timestamp}.zip")

    # از هر دیتابیس (اصلی و هر نماینده) با SQLite Backup API یک نسخه‌ی امن و
    # سازگار می‌گیریم (نه کپی خام فایل) تا اگر همان لحظه در حال نوشتن باشد خراب نشود.
    tmp_dir = os.path.join(output_dir, f"_tmp_full_{timestamp}")
    os.makedirs(tmp_dir, exist_ok=True)
    manifest_lines = [
        "بکاپ کامل - شامل بات اصلی + همه‌ی بات‌های نمایندگی (سطح ۱ و سطح ۲)",
        f"تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    try:
        main_copy = os.path.join(tmp_dir, "main_bot.db")
        _sqlite_safe_copy(main_db_path, main_copy)
        manifest_lines.append(f"main_bot.db  <-  {main_db_path}")

        resellers = main_db.list_reseller_bots(active_only=False)
        for row in resellers:
            reseller_db_path = resolve_db_path(row["db_path"])
            active = "فعال" if row["is_active"] else "غیرفعال"
            safe_name = f"reseller_{row['id']}.db"
            if os.path.exists(reseller_db_path):
                try:
                    _sqlite_safe_copy(reseller_db_path, os.path.join(tmp_dir, safe_name))
                    manifest_lines.append(
                        f"{safe_name}  <-  {reseller_db_path}  "
                        f"(owner_id={row['owner_telegram_id']}, {active})"
                    )
                except Exception:
                    logger.exception("بکاپ‌گرفتن از دیتابیس نماینده %s ناموفق بود.", reseller_db_path)
                    manifest_lines.append(f"{safe_name}  <-  {reseller_db_path}  [ناموفق - رد شد]")
            else:
                manifest_lines.append(f"[فایل پیدا نشد - رد شد]  <-  {reseller_db_path}  (owner_id={row['owner_telegram_id']})")

        manifest_path = os.path.join(tmp_dir, "manifest.txt")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write("\n".join(manifest_lines))

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in os.listdir(tmp_dir):
                zf.write(os.path.join(tmp_dir, name), arcname=name)
    finally:
        for name in os.listdir(tmp_dir):
            try:
                os.remove(os.path.join(tmp_dir, name))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    pattern = os.path.join(output_dir, "full_backup_*.zip")
    existing = sorted(glob.glob(pattern))
    for old_file in existing[:-keep]:
        try:
            os.remove(old_file)
        except OSError:
            pass

    return zip_path


def _sqlite_safe_copy(src_path: str, dst_path: str) -> None:
    """یک کپی امن از یک فایل sqlite با Backup API می‌سازد (نه کپی خام فایل)."""
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def restore_full_backup(main_db, main_db_path: str, zip_path: str) -> dict:
    """یک فایل zip ساخته‌شده توسط `create_full_backup` را باز می‌کند:

    ۱) اول دیتابیس بات اصلی (main_bot.db داخل zip) را جایگزین دیتابیس فعلی
       می‌کند - از طریق خود `main_db.replace_file()` (همان مسیر امن/قفل‌دار
       بازیابی معمولی، تا اتصال persistent درست بسته و بازسازی شود).
    ۲) بعد، چون جدول reseller_bots حالا از روی همان دیتابیسِ تازه‌بازیابی‌شده
       خوانده می‌شود، فایل هر `reseller_<id>.db` (یا قالب قدیمی `reseller_<id>_level<N>.db`) داخل zip را با شناسه‌ی
       داخل نامش به یک ردیف واقعی از reseller_bots وصل می‌کند و مستقیماً در
       مسیر دیتابیس همان نماینده (`resolve_db_path`) جایگزین می‌کند.

    توجه: این تابع فقط فایل‌ها را جایگزین می‌کند و کاری به روشن/خاموش‌کردن
    پروسه‌ی بات‌های نمایندگی در حال اجرا ندارد - آن بخش (متوقف‌کردن قبل از
    جایگزینی و اجازه‌دادن به reconcile برای روشن‌کردن دوباره) باید قبل/بعد
    از این تابع، در کد async بالادستی (هندلر بات) انجام شود.

    خروجی: دیکشنری وضعیت شامل:
      - main_restored: bool
      - main_pre_restore_path: مسیر نسخه‌ی پیش از بازیابی دیتابیس اصلی
      - resellers_restored: [{"id", "bot_username", "db_path"}, ...]
      - resellers_skipped: [{"file", "reason"}, ...]
    """
    from config import resolve_db_path

    result = {
        "main_restored": False,
        "main_pre_restore_path": None,
        "resellers_restored": [],
        "resellers_skipped": [],
    }

    tmp_dir = zip_path + "_extract"
    if os.path.exists(tmp_dir):
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        main_extracted = os.path.join(tmp_dir, "main_bot.db")
        if not os.path.exists(main_extracted) or not is_valid_sqlite_db(main_extracted):
            raise ValueError("فایل main_bot.db داخل zip پیدا نشد یا دیتابیس sqlite معتبری نیست.")

        # ۱) بازیابی دیتابیس اصلی (همان مسیر امن replace_file خود کلاس Database)
        result["main_pre_restore_path"] = main_db.replace_file(main_extracted)
        result["main_restored"] = True

        # ۲) حالا reseller_bots را از روی دیتابیس *تازه* بخوان‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
        resellers_by_id = {row["id"]: row for row in main_db.list_reseller_bots(active_only=False)}

        for name in sorted(os.listdir(tmp_dir)):
            if not (name.startswith("reseller_") and name.endswith(".db")):
                continue
            # قالب نام: reseller_<id>.db یا (بکاپ‌های قدیمی) reseller_<id>_level<N>.db
            try:
                middle = name[len("reseller_"):-len(".db")]
                id_part = middle.split("_level")[0]
                reseller_id = int(id_part)
            except (ValueError, IndexError):
                result["resellers_skipped"].append({"file": name, "reason": "نام فایل نامعتبر است."})
                continue

            row = resellers_by_id.get(reseller_id)
            if row is None:
                result["resellers_skipped"].append(
                    {"file": name, "reason": f"نماینده‌ای با id={reseller_id} در دیتابیس اصلیِ بازیابی‌شده پیدا نشد."}
                )
                continue

            extracted_path = os.path.join(tmp_dir, name)
            if not is_valid_sqlite_db(extracted_path):
                result["resellers_skipped"].append({"file": name, "reason": "دیتابیس sqlite معتبر نیست."})
                continue

            target_path = resolve_db_path(row["db_path"])
            try:
                _raw_replace_db_file(extracted_path, target_path)
                result["resellers_restored"].append({
                    "id": reseller_id, "bot_username": row["bot_username"], "db_path": target_path,
                })
            except Exception:
                logger.exception("جایگزینی دیتابیس نماینده id=%s (%s) ناموفق بود.", reseller_id, target_path)
                result["resellers_skipped"].append({"file": name, "reason": "خطا هنگام جایگزینی فایل."})
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


def _raw_replace_db_file(src_path: str, target_path: str) -> str:
    """فایل دیتابیس در `target_path` را با `src_path` جایگزین می‌کند (برای
    نماینده‌ای که بات‌اش پروسه‌ی جدا دارد و اتصال persistent‌اش از اینجا در
    دسترس نیست). قبلش یک نسخه‌ی «پیش از بازیابی» می‌گیرد و فایل‌های WAL/SHM
    قدیمی را پاک می‌کند تا داده‌ی commit‌نشده‌ی قدیمی با فایل جدید قاطی نشود.

    نکته‌ی امنیتی: قبل از صدازدن این تابع باید مطمئن شد که هیچ پروسه‌ای
    (بات نماینده‌ی در حال اجرا) هم‌زمان به `target_path` وصل نیست - وگرنه
    همان باگ قدیمی «اتصال به فایل نیمه‌نوشته» ممکن است تکرار شود.
    """
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(target_path)), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    pre_restore_path = os.path.join(backup_dir, f"pre_restore_{timestamp}.db")

    if os.path.exists(target_path):
        _sqlite_safe_copy(target_path, pre_restore_path)

    for suffix in ("-wal", "-shm"):
        stale = target_path + suffix
        if os.path.exists(stale):
            os.remove(stale)

    import shutil as _shutil
    _shutil.copyfile(src_path, target_path)
    return pre_restore_path


async def backup_and_notify(bot, db, db_path: str, backup_dir: str, keep: int = 14) -> None:
    """یک بکاپ می‌گیرد و می‌فرستد: به تاپیک «بکاپ» گروه گزارش (در صورت تنظیم) یا PV ادمین‌های همین
    بات، و در صورت تنظیم‌بودن یک کپی هم به چت تلگرام دوم و/یا سرور دوم (از طریق SFTP)."""
    try:
        backup_path = await asyncio.to_thread(create_backup, db_path, backup_dir, keep)
    except Exception:
        logger.exception("بکاپ‌گیری از %s ناموفق بود.", db_path)
        return
    if not backup_path:
        return

    try:
        from aiogram.types import FSInputFile
    except ImportError:
        return

    file_size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    caption = (
        "🗄 بکاپ خودکار دیتابیس\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"📦 حجم: {file_size_mb:.1f} مگابایت"
    )

    # مقصد اصلی: تاپیک «بکاپ» گروه گزارش (اگر گروه گزارش تنظیم شده باشد). اگر ارسال به
    # تاپیک موفق شود و «عدم ارسال به چت خصوصی» روشن باشد (پیش‌فرض)، فایل به PV ربات/ادمین‌ها
    # فرستاده نمی‌شود. اگر گروه تنظیم نباشد یا ارسال شکست بخورد، برای اینکه بکاپ گم نشود
    # مثل قبل به PV ادمین‌ها می‌رود.
    sent_to_group = False
    if await _db(report_router.group_active, db):
        _key, silent = await _db(report_router.resolve_topic, db, "backup")
        sent = await report_router.send_to_group(
            bot, db, "backup",
            lambda chat_id, thread_id: bot.send_document(
                chat_id, FSInputFile(backup_path), caption=caption,
                message_thread_id=thread_id, disable_notification=silent,
            ),
        )
        sent_to_group = sent is not None
    skip_admin_dm = sent_to_group and (await _db(db.get_setting, "backup_skip_admin_dm", "1") or "1") == "1"

    if not skip_admin_dm:
        warn = "\n⚠️ ارسال به تاپیک بکاپ گروه گزارش ناموفق بود." if (not sent_to_group and await _db(report_router.group_active, db)) else ""
        admin_ids = await _db(db.list_admins)
        for admin_id in admin_ids:
            try:
                await bot.send_document(admin_id, FSInputFile(backup_path), caption=caption + warn)
            except Exception:
                logger.warning("ارسال بکاپ به ادمین %s ناموفق بود.", admin_id)
        await report_router.send_text(bot, db, "backup", caption + "\n📨 فایل برای مدیران ارسال شد.")

    # کپی جانبی: ارسال به یک چت تلگرام دوم (مثلاً ادمین/کانال روی سرور دوم)
    secondary_chat_id = (await _db(db.get_setting, "backup_secondary_chat_id", "") or "").strip()
    if secondary_chat_id:
        try:
            await bot.send_document(
                int(secondary_chat_id), FSInputFile(backup_path), caption=caption + "\n📡 (کپی جانبی)"
            )
        except Exception:
            logger.warning("ارسال بکاپ به چت دوم (%s) ناموفق بود.", secondary_chat_id)

    # کپی جانبی: ارسال مستقیم فایل به سرور دوم با SFTP
    if (await _db(db.get_setting, "backup_sftp_enabled", "0") or "0") == "1":
        try:
            await push_backup_sftp(
                backup_path,
                host=await _db(db.get_setting, "backup_sftp_host", ""),
                port=int(await _db(db.get_setting, "backup_sftp_port", "22") or "22"),
                username=await _db(db.get_setting, "backup_sftp_username", ""),
                password=(await _db(db.get_setting, "backup_sftp_password", "") or None),
                key_path=(await _db(db.get_setting, "backup_sftp_key_path", "") or None),
                remote_dir=await _db(db.get_setting, "backup_sftp_remote_dir", "/root/vpn_backups") or "/root/vpn_backups",
            )
        except Exception:
            logger.exception("ارسال بکاپ با SFTP به سرور دوم ناموفق بود.")


async def backup_loop(bot, db, db_path: str, interval_seconds: int = 86400, keep: int = 14) -> None:
    """به‌طور دوره‌ای یک بکاپ می‌گیرد و می‌فرستد.

    فاصله‌ی زمانی از تنظیم `backup_interval_hours` (قابل تغییر از پنل ادمین بدون
    نیاز به ری‌استارت بات) خوانده می‌شود؛ اگر تنظیم نشده باشد، از `interval_seconds`
    (پیش‌فرض: هر ۲۴ ساعت) استفاده می‌شود. چون فاصله در ابتدای هر چرخه دوباره خوانده
    می‌شود، تغییر آن از پنل ادمین از همان چرخه‌ی بعدی اعمال خواهد شد.
    """
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    # قبل از اولین چرخه کمی صبر می‌کنیم تا بات کاملاً بالا بیاید‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
    await asyncio.sleep(60)
    while True:
        try:
            await backup_and_notify(bot, db, db_path, backup_dir, keep=keep)
        except Exception:
            logger.exception("خطا در چرخه‌ی بکاپ‌گیری خودکار برای %s", db_path)

        sleep_seconds = interval_seconds
        raw_hours = (await _db(db.get_setting, "backup_interval_hours", "") or "").strip()
        if raw_hours:
            try:
                sleep_seconds = max(1, int(float(raw_hours) * 3600))
            except ValueError:
                pass
        await asyncio.sleep(sleep_seconds)


def is_valid_sqlite_db(file_path: str) -> bool:
    """بررسی سطحی که فایل آپلودشده واقعاً یک دیتابیس sqlite سالم است، نه یک
    فایل دلخواه/خراب. برای جلوگیری از این‌که یک فایل اشتباه جایگزین دیتابیس
    اصلی شود و کل بات را از کار بیندازد."""
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 100:
        return False
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
        if header != b"SQLite format 3\x00":
            return False
        conn = sqlite3.connect(file_path)
        try:
            # integrity_check کامل روی فایل‌های بزرگ کند است؛ همین که فایل
            # باز می‌شود و حداقل یک جدول قابل‌خواندن دارد کافی است.
            conn.execute("SELECT name FROM sqlite_master LIMIT 1")
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _build_sftp_connect_kwargs(host: str, port: int, username: str,
                                password: Optional[str] = None, key_path: Optional[str] = None) -> dict:
    if not host or not username:
        raise ValueError("آدرس سرور و یوزرنیم SSH نمی‌توانند خالی باشند.")
    if not password and not key_path:
        raise ValueError("باید یکی از پسورد یا مسیر کلید خصوصی SSH مشخص شود.")
    kwargs = {
        "host": host,
        "port": port or 22,
        "username": username,
        "known_hosts": None,  # سرور دوم معمولاً از قبل در known_hosts نیست؛ برای سادگی چک نمی‌شود
    }
    if key_path:
        if not os.path.exists(key_path):
            raise ValueError(f"فایل کلید خصوصی در مسیر «{key_path}» روی این سرور پیدا نشد.")
        kwargs["client_keys"] = [key_path]
    if password:
        kwargs["password"] = password
    return kwargs


async def test_sftp_connection(host: str, port: int, username: str,
                                password: Optional[str] = None, key_path: Optional[str] = None) -> None:
    """فقط تلاش می‌کند وصل شود؛ در صورت شکست، Exception با پیام مناسب raise می‌شود."""
    import asyncssh
    connect_kwargs = _build_sftp_connect_kwargs(host, port, username, password, key_path)
    async with asyncssh.connect(**connect_kwargs) as conn:
        async with conn.start_sftp_client():
            pass


async def push_backup_sftp(backup_path: str, host: str, port: int, username: str,
                            password: Optional[str] = None, key_path: Optional[str] = None,
                            remote_dir: str = "/root/vpn_backups") -> None:
    """فایل بکاپ را با SFTP به سرور دوم می‌فرستد (پوشه‌ی مقصد در صورت نبودن ساخته می‌شود)."""
    import asyncssh
    connect_kwargs = _build_sftp_connect_kwargs(host, port, username, password, key_path)
    remote_dir = (remote_dir or "/root/vpn_backups").rstrip("/") or "/"
    async with asyncssh.connect(**connect_kwargs) as conn:
        async with conn.start_sftp_client() as sftp:
            try:
                if not await sftp.exists(remote_dir):
                    await sftp.makedirs(remote_dir)
            except Exception:
                pass  # اگر ساخت پوشه شکست خورد (مثلاً از قبل هست)، همچنان تلاش برای آپلود می‌کنیم
            remote_path = f"{remote_dir}/{os.path.basename(backup_path)}"
            await sftp.put(backup_path, remote_path)


def restore_backup(db, db_path: str, uploaded_file_path: str) -> str:
    """دیتابیس فعلی را با فایل بکاپ آپلودشده جایگزین می‌کند.

    قبل از جایگزینی، از دیتابیس فعلی هم یک نسخه‌ی «قبل از بازیابی» گرفته
    می‌شود تا در صورت اشتباه قابل برگشت باشد. مسیر همان نسخه‌ی پیشین را
    برمی‌گرداند.

    نکته: بستن اتصال و جایگزینی فایل عمداً داخل `Database.replace_file()`
    و زیر یک لاک واحد انجام می‌شود (نه اینجا با db.close() جدا)، تا حلقه‌ی
    پس‌زمینه‌ی کش نتواند وسط جایگزینی یک اتصال نیمه‌کاره باز کند و بات را
    برای همیشه (تا ری‌استارت دستی) خراب نگه دارد. برای جزئیات به توضیح
    داخل `Database.replace_file` نگاه کن.
    """
    if not is_valid_sqlite_db(uploaded_file_path):
        raise ValueError("فایل ارسالی یک دیتابیس sqlite معتبر نیست.")

    return db.replace_file(uploaded_file_path)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
