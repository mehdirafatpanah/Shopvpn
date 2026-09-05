# -*- coding: utf-8 -*-
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
import shutil
import sqlite3
import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


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


async def backup_and_notify(bot, db, db_path: str, backup_dir: str, keep: int = 14) -> None:
    """یک بکاپ می‌گیرد، برای همه‌ی ادمین‌های همین بات ارسال می‌کند، و در صورت تنظیم‌بودن،
    یک کپی هم به چت تلگرام دوم و/یا سرور دوم (از طریق SFTP) می‌فرستد."""
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

    for admin_id in db.list_admins():
        try:
            await bot.send_document(admin_id, FSInputFile(backup_path), caption=caption)
        except Exception:
            logger.warning("ارسال بکاپ به ادمین %s ناموفق بود.", admin_id)

    # کپی جانبی: ارسال به یک چت تلگرام دوم (مثلاً ادمین/کانال روی سرور دوم)
    secondary_chat_id = (db.get_setting("backup_secondary_chat_id", "") or "").strip()
    if secondary_chat_id:
        try:
            await bot.send_document(
                int(secondary_chat_id), FSInputFile(backup_path), caption=caption + "\n📡 (کپی جانبی)"
            )
        except Exception:
            logger.warning("ارسال بکاپ به چت دوم (%s) ناموفق بود.", secondary_chat_id)

    # کپی جانبی: ارسال مستقیم فایل به سرور دوم با SFTP
    if (db.get_setting("backup_sftp_enabled", "0") or "0") == "1":
        try:
            await push_backup_sftp(
                backup_path,
                host=db.get_setting("backup_sftp_host", ""),
                port=int(db.get_setting("backup_sftp_port", "22") or "22"),
                username=db.get_setting("backup_sftp_username", ""),
                password=(db.get_setting("backup_sftp_password", "") or None),
                key_path=(db.get_setting("backup_sftp_key_path", "") or None),
                remote_dir=db.get_setting("backup_sftp_remote_dir", "/root/vpn_backups") or "/root/vpn_backups",
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
    # قبل از اولین چرخه کمی صبر می‌کنیم تا بات کاملاً بالا بیاید
    await asyncio.sleep(60)
    while True:
        try:
            await backup_and_notify(bot, db, db_path, backup_dir, keep=keep)
        except Exception:
            logger.exception("خطا در چرخه‌ی بکاپ‌گیری خودکار برای %s", db_path)

        sleep_seconds = interval_seconds
        raw_hours = (db.get_setting("backup_interval_hours", "") or "").strip()
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
    """
    if not is_valid_sqlite_db(uploaded_file_path):
        raise ValueError("فایل ارسالی یک دیتابیس sqlite معتبر نیست.")

    backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    pre_restore_path = os.path.join(backup_dir, f"pre_restore_{timestamp}.db")

    # اتصال persistent باز فعلی را می‌بندیم تا فایل دیتابیس قفل نباشد و
    # جایگزینی فایل با خطا مواجه نشود.
    db.close()

    if os.path.exists(db_path):
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(pre_restore_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

    # پاک‌کردن فایل‌های کمکی WAL دیتابیس فعلی، وگرنه ممکن است داده‌ی commit‌نشده
    # قدیمی با دیتابیس جدید قاطی شود
    for suffix in ("-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)

    shutil.copyfile(uploaded_file_path, db_path)

    # اتصال بعدی که db._get_conn() صدا زده شود، خودش یک اتصال تازه به فایل
    # جدید باز می‌کند (چون db.close() آن را None کرده).
    return pre_restore_path
