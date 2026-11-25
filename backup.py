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
import hashlib
import json
import socket
import shutil
import tempfile
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


def _sqlite_safe_copy(src_path: str, dst_path: str) -> None:
    """Create a transactionally consistent SQLite snapshot."""
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sqlite_integrity(path: str) -> None:
    if not is_valid_sqlite_db(path):
        raise ValueError(f"فایل دیتابیس معتبر نیست: {os.path.basename(path)}")
    conn = sqlite3.connect(path)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise ValueError(f"سلامت دیتابیس تایید نشد: {os.path.basename(path)}")
    finally:
        conn.close()


def _machine_fingerprint() -> str:
    """Stable, non-reversible machine identifier used only to detect server changes."""
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(candidate, "r", encoding="utf-8") as stream:
                value = stream.read().strip()
            if value:
                return hashlib.sha256(value.encode("utf-8")).hexdigest()
        except OSError:
            pass
    return hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()


def _migration_environment_snapshot() -> dict:
    """Only public endpoints are included; credentials and tokens are never exported."""
    keys = ("MINIAPP_URL", "API_BASE_URL", "DEDICATED_SUB_URL", "ADMIN_PANEL_URL", "WEBHOOK_BASE_URL")
    return {key: os.getenv(key, "").strip() for key in keys}


def create_full_backup(main_db, main_db_path: str, output_dir: str, keep: int = 5) -> Optional[str]:
    """Create a portable, verifiable archive of the main DB and every reseller DB.

    Missing/invalid reseller databases are recorded as incomplete rather than being
    silently presented as a fully restorable archive. The archive carries relative
    identities and hashes, never source absolute paths or secrets.
    """
    if not os.path.isfile(main_db_path):
        return None
    from config import resolve_db_path

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(output_dir, f"full_backup_{timestamp}.zip")
    tmp_dir = tempfile.mkdtemp(prefix="_tmp_full_", dir=output_dir)
    entries = []
    errors = []
    try:
        main_copy = os.path.join(tmp_dir, "main_bot.db")
        _sqlite_safe_copy(main_db_path, main_copy)
        _validate_sqlite_integrity(main_copy)
        entries.append({"kind": "main", "file": "main_bot.db", "sha256": _sha256_file(main_copy),
                        "size": os.path.getsize(main_copy)})

        for row in main_db.list_reseller_bots(active_only=False):
            rid = int(row["id"])
            raw_path = row["db_path"]
            reseller_path = resolve_db_path(raw_path) if raw_path else ""
            filename = f"reseller_{rid}.db"
            if not reseller_path or not os.path.isfile(reseller_path):
                errors.append({"reseller_id": rid, "reason": "database_missing"})
                continue
            try:
                copy_path = os.path.join(tmp_dir, filename)
                _sqlite_safe_copy(reseller_path, copy_path)
                _validate_sqlite_integrity(copy_path)
                entries.append({"kind": "reseller", "reseller_id": rid, "file": filename,
                                "bot_username": row["bot_username"] or "", "active": bool(row["is_active"]),
                                "sha256": _sha256_file(copy_path), "size": os.path.getsize(copy_path)})
            except Exception as exc:
                logger.exception("Full backup failed for reseller id=%s", rid)
                errors.append({"reseller_id": rid, "reason": type(exc).__name__})

        manifest = {
            "format": "shopvpn-full-backup", "format_version": 2,
            "created_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source_host": socket.gethostname(),
            "source_machine_fingerprint": _machine_fingerprint(),
            "source_project": "ShopVPN",
            "environment": _migration_environment_snapshot(),
            "complete": not errors,
            "entries": entries,
            "errors": errors,
            "notes": ["Secrets, bot tokens and .env are intentionally excluded.",
                      "On a new server, configure public domains and server-specific settings again."],
        }
        with open(os.path.join(tmp_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(tmp_dir, "manifest.txt"), "w", encoding="utf-8") as f:
            f.write("ShopVPN full migration backup\n")
            f.write(f"Created: {manifest['created_at_utc']}\n")
            f.write(f"Complete: {'yes' if manifest['complete'] else 'NO - missing reseller databases'}\n")
            f.write(f"Reseller databases included: {sum(e['kind']=='reseller' for e in entries)}\n")
            if errors:
                f.write("\nMissing/failed reseller databases:\n")
                for item in errors:
                    f.write(f"- reseller {item['reseller_id']}: {item['reason']}\n")
        temp_zip = zip_path + ".tmp"
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for name in sorted(os.listdir(tmp_dir)):
                zf.write(os.path.join(tmp_dir, name), arcname=name)
        os.replace(temp_zip, zip_path)
    except Exception:
        try:
            if os.path.exists(zip_path + ".tmp"):
                os.remove(zip_path + ".tmp")
        except OSError:
            pass
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    existing = sorted(glob.glob(os.path.join(output_dir, "full_backup_*.zip")))
    for old_file in existing[:-max(1, int(keep))]:
        try:
            os.remove(old_file)
        except OSError:
            pass
    return zip_path


def _safe_read_full_archive(zip_path: str, extract_dir: str) -> dict:
    """Preflight and extract only flat, expected database files (no zip-slip)."""
    max_total = 10 * 1024 * 1024 * 1024
    max_files = 10000
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise ValueError("تعداد فایل‌های آرشیو غیرمجاز است.")
        total = sum(i.file_size for i in infos)
        if total > max_total:
            raise ValueError("حجم بازشده‌ی آرشیو بیش از حد مجاز است.")
        allowed = {"main_bot.db", "manifest.json", "manifest.txt"}
        for info in infos:
            name = info.filename
            if name not in allowed and not (name.startswith("reseller_") and name.endswith(".db")
                                             and name[9:-3].replace("_level", "").replace("_", "").isdigit()):
                raise ValueError(f"فایل غیرمنتظره در بکاپ: {name}")
            if "/" in name or "\\" in name or name.startswith("."):
                raise ValueError("مسیر نامعتبر داخل فایل بکاپ وجود دارد.")
        if "main_bot.db" not in zf.namelist():
            raise ValueError("فایل main_bot.db داخل بکاپ پیدا نشد.")
        os.makedirs(extract_dir, exist_ok=True)
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            target = os.path.join(extract_dir, name)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    main_path = os.path.join(extract_dir, "main_bot.db")
    _validate_sqlite_integrity(main_path)
    manifest_path = os.path.join(extract_dir, "manifest.json")
    manifest = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        if manifest.get("format") not in (None, "shopvpn-full-backup"):
            raise ValueError("فرمت manifest این بکاپ شناخته‌شده نیست.")
        for item in manifest.get("entries", []):
            name = item.get("file")
            allowed_manifest_files = {"main_bot.db"} | {
                entry for entry in os.listdir(extract_dir)
                if entry.startswith("reseller_") and entry.endswith(".db")
            }
            if name in allowed_manifest_files and os.path.isfile(os.path.join(extract_dir, name)):
                actual = _sha256_file(os.path.join(extract_dir, name))
                if item.get("sha256") and actual != item["sha256"]:
                    raise ValueError(f"تطبیق هش فایل {name} ناموفق بود؛ فایل آسیب دیده است.")
    return manifest


def restore_full_backup(main_db, main_db_path: str, zip_path: str) -> dict:
    """Restore main + reseller databases and relocate their paths to this install.

    All archive contents are validated before the first live database is touched.
    Current files are snapshotted first; each replacement is atomic on its target
    filesystem. Legacy archives without manifest.json remain supported.
    """
    from config import RESELLER_DBS_DIR
    result = {"main_restored": False, "main_pre_restore_path": None,
              "resellers_restored": [], "resellers_skipped": [],
              "manifest": {}, "source_host": None, "complete": True}
    tmp_dir = tempfile.mkdtemp(prefix="restore_full_")
    try:
        manifest = _safe_read_full_archive(zip_path, tmp_dir)
        result["manifest"] = manifest
        result["source_host"] = manifest.get("source_host")
        result["complete"] = bool(manifest.get("complete", True))
        main_path = os.path.join(tmp_dir, "main_bot.db")
        reseller_files = {}
        for name in os.listdir(tmp_dir):
            if name.startswith("reseller_") and name.endswith(".db"):
                try:
                    rid = int(name[len("reseller_"):-len(".db")].split("_level")[0])
                except ValueError:
                    result["resellers_skipped"].append({"file": name, "reason": "نام فایل نامعتبر است."})
                    continue
                _validate_sqlite_integrity(os.path.join(tmp_dir, name))
                reseller_files.setdefault(rid, os.path.join(tmp_dir, name))

        # Snapshot all current reseller DBs before replacing the main database.
        old_rows = list(main_db.list_reseller_bots(active_only=False))
        old_snapshots = {}
        for row in old_rows:
            path = row["db_path"]
            if path:
                from config import resolve_db_path
                resolved = resolve_db_path(path)
                if os.path.isfile(resolved):
                    snap = os.path.join(tmp_dir, f"pre_reseller_{int(row['id'])}.db")
                    _sqlite_safe_copy(resolved, snap)
                    old_snapshots[int(row["id"])] = (resolved, snap)

        result["main_pre_restore_path"] = main_db.replace_file(main_path)
        result["main_restored"] = True
        os.makedirs(RESELLER_DBS_DIR, exist_ok=True)
        restored_ids = set()
        for row in main_db.list_reseller_bots(active_only=False):
            rid = int(row["id"])
            target = os.path.join(RESELLER_DBS_DIR, f"reseller_{rid}.db")
            main_db.set_reseller_db_path(rid, target)
            source = reseller_files.get(rid)
            if not source:
                result["resellers_skipped"].append({"file": f"reseller_{rid}.db",
                    "reason": "دیتابیس این نماینده داخل آرشیو نبود؛ دیتابیس خالی ساخته نشد."})
                continue
            _raw_replace_db_file(source, target)
            restored_ids.add(rid)
            result["resellers_restored"].append({"id": rid,
                "bot_username": row["bot_username"], "db_path": target})
        # Files from the archive that have no matching reseller row are not attached
        # to a different tenant; they are reported rather than silently misassigned.
        known_ids = {int(r["id"]) for r in main_db.list_reseller_bots(active_only=False)}
        for rid in sorted(set(reseller_files) - known_ids):
            result["resellers_skipped"].append({"file": f"reseller_{rid}.db",
                "reason": "نماینده متناظر در دیتابیس اصلی بازیابی‌شده وجود ندارد."})
        try:
            from server_migration import create_pending_marker
            result["server_changed"] = create_pending_marker(manifest) if manifest else False
        except Exception:
            logger.exception("Could not create pending server-migration marker")
            result["server_changed"] = False
    except Exception:
        # Restore the main DB and reseller DBs to their pre-operation snapshots
        # where possible, so a failed multi-DB restore does not leave a half-state.
        try:
            pre_main = result.get("main_pre_restore_path")
            if pre_main and os.path.isfile(pre_main):
                main_db.replace_file(pre_main)
        except Exception:
            logger.exception("Rollback of main database after failed full restore failed")
        for rid, (target, snap) in locals().get("old_snapshots", {}).items():
            try:
                _raw_replace_db_file(snap, target)
            except Exception:
                logger.exception("Rollback of reseller database id=%s failed", rid)
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return result

def _raw_replace_db_file(src_path: str, target_path: str) -> str:
    """Safely replace a reseller DB after its bot process has been stopped."""
    _validate_sqlite_integrity(src_path)
    target_path = os.path.abspath(target_path)
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    backup_dir = os.path.join(target_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    pre_restore_path = os.path.join(backup_dir, f"pre_restore_{timestamp}.db")
    if os.path.isfile(target_path):
        _sqlite_safe_copy(target_path, pre_restore_path)
    fd, staged_path = tempfile.mkstemp(prefix=".shopvpn_restore_", suffix=".db", dir=target_dir)
    os.close(fd)
    try:
        shutil.copyfile(src_path, staged_path)
        _validate_sqlite_integrity(staged_path)
        with open(staged_path, "rb") as stream:
            os.fsync(stream.fileno())
        for suffix in ("-wal", "-shm"):
            stale = target_path + suffix
            if os.path.exists(stale):
                os.remove(stale)
        os.replace(staged_path, target_path)
    finally:
        try:
            if os.path.exists(staged_path):
                os.remove(staged_path)
        except OSError:
            pass
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
