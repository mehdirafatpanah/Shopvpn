# -*- coding: utf-8 -*-
"""مهاجرت کاربران بین پنل‌های VPN (حتی بین انواع مختلف پنل).

برای هر سرویس فعالِ روی پنل مبدأ:
  ۱. حجم و زمان باقی‌مانده خوانده می‌شود (از خود پنل؛ اگر پنل در دسترس نبود از دیتابیس — «تخمینی»).
  ۲. کاربر روی پنل مقصد با همان مقدار باقی‌مانده ساخته می‌شود.
  ۳. رکورد سرویس (پنل، نام کاربری، لینک ساب) به مقصد سوییچ می‌شود. اگر این مرحله شکست بخورد،
     کاربرِ تازه‌ساخته از پنل مقصد پاک می‌شود تا چیزی نیمه‌کاره نماند.
  ۴. کاربر قدیمی روی پنل مبدأ دست‌نخورده می‌ماند (ادمین خودش هر وقت خواست پنل را حذف می‌کند)؛
     فقط اگر ادمین گزینه‌ی «غیرفعال‌کردن کاربران قدیمی» را زده باشد، آن‌ها غیرفعال می‌شوند.
  ۵. به کاربر پیام «سرویس منتقل شد + لینک ساب جدید» ارسال می‌شود.

سرویس‌های عضو استخر سهمیه (چندپنلی / VPN+SSH): روی پنل مقصد نامحدود ساخته می‌شوند چون سقف حجم را خودِ
استخر اعمال می‌کند؛ مصرف قبلی در usage_snapshots حفظ می‌شود (offset).
"""

import asyncio
import html
import inspect
import logging
import math
import random
import string
from dataclasses import dataclass
from datetime import datetime, timezone

import dedicated_sub
from panel_providers import get_provider, PanelError, PanelUsernameTakenError
from user_limit import provider_kwargs

try:  # ترجمه‌ی پیام‌های کاربر؛ اگر ماژول در دسترس نبود همان فارسی می‌ماند
    from i18n import tr
except Exception:  # pragma: no cover
    def tr(text, language=None):
        return text

logger = logging.getLogger(__name__)

GB = 1024 ** 3
BATCH_SIZE = 3            # تعداد سرویس‌هایی که هم‌زمان منتقل می‌شوند
ABORT_AFTER_FAILS = 3     # اگر حتی یک موفقیت نبود و این‌قدر خطا آمد، اجرا متوقف می‌شود
PANEL_CALL_TIMEOUT = 40

_RUNNING: set = set()


def is_running(source_id: int) -> bool:
    return int(source_id) in _RUNNING


@dataclass
class Options:
    notify_users: bool = True      # ارسال پیام و لینک جدید به کاربر
    retarget_sales: bool = True    # محصولات/فروش جدید هم روی پنل مقصد ساخته شوند
    disable_old: bool = False      # کاربر قدیمی روی پنل مبدأ غیرفعال شود (حذف نمی‌شود)
    allow_estimate: bool = True    # اگر پنل مبدأ در دسترس نبود از اطلاعات دیتابیس تخمین بزن

    def as_dict(self) -> dict:
        return {"notify_users": self.notify_users, "retarget_sales": self.retarget_sales,
                "disable_old": self.disable_old, "allow_estimate": self.allow_estimate}


# ---------------------------------------------------------------------------
# کمکی‌ها
# ---------------------------------------------------------------------------
def _parse(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def time_plan(expires_at, duration_days, start_on_first_use, pool_expires_at=None):
    """(state, days, start_first): state=expired|ok؛ days=0 یعنی بدون انقضا."""
    exp = _parse(pool_expires_at) or _parse(expires_at)
    if exp:
        remaining = (exp - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return "expired", 0, False
        return "ok", max(1, math.ceil(remaining / 86400)), False
    if start_on_first_use and duration_days:
        return "ok", int(duration_days), True
    return "ok", 0, False


async def _call(coro):
    return await asyncio.wait_for(coro, timeout=PANEL_CALL_TIMEOUT)


async def _read_usage(provider, username: str, db_volume_gb, allow_estimate: bool):
    """(total_bytes, used_bytes, estimated)؛ total=0 یعنی نامحدود."""
    db_total = int(float(db_volume_gb or 0) * GB)
    try:
        usage = await _call(provider.get_user_usage(username))
        used = max(int(usage.get("used_bytes") or 0), 0)
        limit = max(int(usage.get("data_limit_bytes") or 0), 0)
        return (limit or db_total), used, False
    except Exception as exc:
        if not allow_estimate:
            raise
        logger.warning("panel-migration: usage unreadable for %s (%s) -> DB estimate", username, type(exc).__name__)
        return db_total, 0, True


async def _create_on_dest(provider, wanted: str, volume_gb: float, days: int, start_first: bool, kwargs: dict):
    """کاربر را روی پنل مقصد می‌سازد؛ اگر نام تکراری بود با پسوند کوتاه دوباره تلاش می‌کند."""
    last = None
    extra = dict(kwargs)
    try:  # همه‌ی پنل‌ها پارامتر start_on_first_use را ندارند (مثل Hiddify/S-UI/WGDashboard)
        if start_first and "start_on_first_use" in inspect.signature(provider.create_user).parameters:
            extra["start_on_first_use"] = True
    except (TypeError, ValueError):
        pass
    for attempt in range(5):
        candidate = wanted if attempt == 0 else wanted + "_" + "".join(
            random.choices(string.ascii_lowercase + string.digits, k=3))
        try:
            result = await _call(provider.create_user(candidate, volume_gb, days, **extra))
            return candidate, result
        except PanelUsernameTakenError as exc:
            last = exc
            continue
    raise PanelError(f"ساخت نام کاربری یکتا روی پنل مقصد ناموفق بود: {last}")


def _visible_link(db, cc_id: int, upstream_url: str) -> str:
    """لینکی که کاربر الان استفاده می‌کند: ساب اختصاصی اگر روشن است، وگرنه لینک خود پنل."""
    try:
        link = dedicated_sub.link_for_config(db, cc_id)
    except Exception:
        link = None
    return link or (upstream_url or "")


# ---------------------------------------------------------------------------
# پیش‌نمایش (بدون هیچ تغییری)
# ---------------------------------------------------------------------------
async def build_plan(db, source_id: int, dest_id: int, check_connections: bool = True) -> dict:
    await asyncio.to_thread(db.pm_ensure_tables)
    src = await asyncio.to_thread(db.get_panel_server, int(source_id))
    dst = await asyncio.to_thread(db.get_panel_server, int(dest_id))
    plan = {"ok": False, "error": "", "warnings": []}
    if not src or not dst:
        plan["error"] = "پنل مبدأ یا مقصد پیدا نشد."
        return plan
    if int(source_id) == int(dest_id):
        plan["error"] = "پنل مبدأ و مقصد نمی‌تواند یکی باشد."
        return plan
    if not dst["is_active"]:
        plan["error"] = "پنل مقصد غیرفعال است؛ اول فعالش کن."
        return plan

    primaries = await asyncio.to_thread(db.pm_list_primary, int(source_id))
    links = await asyncio.to_thread(db.pm_list_links, int(source_id))
    users, pooled, expired, total_gb = set(), 0, 0, 0.0
    live_primary = live_links = 0
    for cc in primaries:
        pool = await asyncio.to_thread(db.pm_pool_for, f"custom_config:{cc['id']}")
        state, _, _ = time_plan(cc.get("expires_at"), cc.get("duration_days"), cc.get("start_on_first_use"),
                                pool and pool.get("expires_at"))
        if state == "expired":
            expired += 1
            continue
        live_primary += 1
        users.add(cc["user_id"])
        if pool:
            pooled += 1
        else:
            total_gb += float(cc.get("volume_gb") or 0)
    for link in links:
        pool = await asyncio.to_thread(db.pm_pool_for, f"panel_link:{link['id']}")
        state, _, _ = time_plan(link.get("cc_expires_at"), link.get("cc_duration_days"),
                                link.get("cc_start_on_first_use"), pool and pool.get("expires_at"))
        if state == "expired":
            expired += 1
            continue
        live_links += 1
        users.add(link["user_id"])

    need = live_primary + live_links
    plan.update(
        ok=True, source=dict(src), dest=dict(dst), primary=live_primary, links=live_links, pooled=pooled,
        expired=expired, users=len(users), total_gb=round(total_gb, 1), need=need,
        same_type=str(src["panel_type"]) == str(dst["panel_type"]),
        capacity_ok=(need < 1 or await asyncio.to_thread(db.panel_has_capacity, int(dest_id), need)),
        dsub_enabled=bool(await asyncio.to_thread(dedicated_sub.is_enabled, db)),
        src_reachable=None, dst_reachable=None, dst_error="",
    )
    if need < 1:
        plan["ok"] = False
        plan["error"] = "هیچ سرویس فعالی روی پنل مبدأ پیدا نشد."
        return plan
    if not plan["capacity_ok"]:
        plan["warnings"].append("ظرفیت پنل مقصد (max_services) برای این تعداد سرویس کافی نیست.")
    if not plan["same_type"]:
        plan["warnings"].append("نوع دو پنل فرق دارد؛ UUID و کانفیگ‌ها عوض می‌شود و کاربر باید لینک جدید را بگیرد.")
    if not plan["dsub_enabled"]:
        plan["warnings"].append("ساب اختصاصی خاموش است؛ لینک کاربر عوض می‌شود و باید در برنامه‌اش جایگزین شود.")
    if check_connections:
        async def _check(server):
            try:
                ok, err = await asyncio.wait_for(get_provider(server).check_connection(), timeout=25)
                return bool(ok), err
            except Exception as exc:
                return False, (str(exc) or type(exc).__name__)[:200]
        (plan["src_reachable"], _), (plan["dst_reachable"], plan["dst_error"]) = await asyncio.gather(
            _check(src), _check(dst))
        if not plan["dst_reachable"]:
            plan["ok"] = False
            plan["error"] = f"اتصال به پنل مقصد برقرار نیست: {plan['dst_error']}"
        elif not plan["src_reachable"]:
            plan["warnings"].append("پنل مبدأ در دسترس نیست؛ حجم باقی‌مانده از دیتابیس «تخمین» زده می‌شود.")
    return plan


# ---------------------------------------------------------------------------
# منتقل‌کردن یک واحد
# ---------------------------------------------------------------------------
@dataclass
class _Ctx:
    db: object
    run_id: int
    src: object
    dst: object
    src_provider: object
    dst_provider: object
    opts: Options


def _res(status: str, **extra) -> dict:
    return {"status": status, **extra}


async def _record(ctx: _Ctx, kind: str, ref_id: int, result: dict, **fields):
    try:
        await asyncio.to_thread(
            ctx.db.pm_add_item, ctx.run_id, kind, ref_id, result["status"],
            estimated=result.get("estimated", False), remaining_bytes=result.get("remaining_bytes"),
            error=result.get("error"), new_username=result.get("new_username"),
            new_url=result.get("new_url"), **fields)
    except Exception:
        logger.exception("panel-migration: item log failed")


async def _finish_unit(ctx: _Ctx, *, kind: str, ref_id: int, row: dict, cc_id: int, pool, vol_gb: float,
                       remaining_bytes: int, days: int, start_first: bool, estimated: bool, enabled: bool,
                       user_limit, old_url: str, old_username: str, old_visible: str, apply_db) -> dict:
    """بخش مشترک: ساخت روی مقصد، همگام‌سازی سقف، سوییچ رکورد، بازگشت در صورت خطا."""
    kwargs = provider_kwargs(ctx.dst_provider, user_limit)
    try:
        new_user, result = await _create_on_dest(ctx.dst_provider, old_username, vol_gb, days, start_first, kwargs)
    except Exception as exc:
        return _res("failed", error=f"ساخت روی پنل مقصد ناموفق: {exc}")
    new_url = getattr(result, "subscription_url", "") or ""
    new_user = getattr(result, "username", None) or new_user

    if pool is None and vol_gb > 0 and getattr(ctx.dst_provider, "supports_data_limit_sync", False):
        try:  # سقف دقیقِ بایتی؛ ساخت با float ممکن است در بعضی پنل‌ها گرد شود
            await _call(ctx.dst_provider.set_data_limit_bytes(new_user, int(remaining_bytes)))
        except Exception:
            logger.warning("panel-migration: exact limit sync skipped for %s", new_user)
    if not enabled:
        try:
            await _call(ctx.dst_provider.set_enabled(new_user, False))
        except Exception:
            logger.warning("panel-migration: could not keep %s disabled on dest", new_user)

    detail = (f"مهاجرت از «{ctx.src['name']}» به «{ctx.dst['name']}»"
              + (f" · {remaining_bytes / GB:.2f} گیگ باقی‌مانده" if pool is None and vol_gb > 0 else "")
              + (" · تخمینی" if estimated else ""))
    try:
        await asyncio.to_thread(apply_db, new_user, new_url, detail)
    except Exception as exc:
        try:
            await _call(ctx.dst_provider.delete_user(new_user))
        except Exception:
            logger.exception("panel-migration: rollback delete failed for %s", new_user)
        return _res("failed", error=f"ثبت در دیتابیس ناموفق (بازگردانده شد): {exc}")

    if ctx.opts.disable_old:
        try:
            await _call(ctx.src_provider.set_enabled(old_username, False))
        except Exception:
            logger.warning("panel-migration: old user %s could not be disabled", old_username)

    return _res("done", new_username=new_user, new_url=new_url, estimated=estimated,
                remaining_bytes=int(remaining_bytes) if vol_gb > 0 else 0,
                cc_id=cc_id, user_id=row.get("user_id"), old_visible=old_visible)


async def _migrate_primary(ctx: _Ctx, cc: dict) -> dict:
    cid = int(cc["id"])
    try:
        pool = await asyncio.to_thread(ctx.db.pm_pool_for, f"custom_config:{cid}")
        state, days, start_first = time_plan(cc.get("expires_at"), cc.get("duration_days"),
                                             cc.get("start_on_first_use"), pool and pool.get("expires_at"))
        if state == "expired":
            result = _res("skipped", error="منقضی شده")
        else:
            vol_gb, remaining, estimated = 0.0, 0, False
            if pool is None:
                total, used, estimated = await _read_usage(ctx.src_provider, cc["username"],
                                                           cc.get("volume_gb"), ctx.opts.allow_estimate)
                if total > 0:
                    remaining = total - used
                    if remaining <= 0:
                        result = _res("skipped", error="حجم تمام شده")
                        await _record(ctx, "primary", cid, result, user_id=cc.get("user_id"),
                                      old_username=cc["username"], old_url=cc.get("subscription_url"))
                        return result
                    vol_gb = remaining / GB
            old_url = cc.get("subscription_url") or ""
            old_visible = await asyncio.to_thread(_visible_link, ctx.db, cid, old_url)
            result = await _finish_unit(
                ctx, kind="primary", ref_id=cid, row=cc, cc_id=cid, pool=pool, vol_gb=vol_gb,
                remaining_bytes=remaining, days=days, start_first=start_first, estimated=estimated,
                enabled=(cc.get("enabled") is None or bool(cc.get("enabled"))), user_limit=cc.get("user_limit"),
                old_url=old_url, old_username=cc["username"], old_visible=old_visible,
                apply_db=lambda u, url, d: ctx.db.pm_switch_primary(cid, ctx.dst["id"], u, url, d))
    except Exception as exc:
        logger.exception("panel-migration: primary %s failed", cid)
        result = _res("failed", error=str(exc) or type(exc).__name__)
    await _record(ctx, "primary", cid, result, user_id=cc.get("user_id"), old_username=cc.get("username"),
                  old_url=cc.get("subscription_url"))
    return result


async def _migrate_link(ctx: _Ctx, link: dict) -> dict:
    lid, cid = int(link["id"]), int(link["custom_config_id"])
    try:
        pool = await asyncio.to_thread(ctx.db.pm_pool_for, f"panel_link:{lid}")
        state, days, start_first = time_plan(link.get("cc_expires_at"), link.get("cc_duration_days"),
                                             link.get("cc_start_on_first_use"), pool and pool.get("expires_at"))
        if state == "expired":
            result = _res("skipped", error="منقضی شده")
        else:
            cc = await asyncio.to_thread(ctx.db.get_custom_config_by_id, cid)
            cc_user_limit = (cc["user_limit"] if cc and "user_limit" in cc.keys() else None)
            old_url = link.get("subscription_url") or ""
            old_visible = await asyncio.to_thread(_visible_link, ctx.db, cid, old_url)
            result = await _finish_unit(
                ctx, kind="link", ref_id=lid, row=link, cc_id=cid, pool=pool or {"pool_id": None}, vol_gb=0.0,
                remaining_bytes=0, days=days, start_first=start_first, estimated=False, enabled=True,
                user_limit=cc_user_limit, old_url=old_url, old_username=link["username"],
                old_visible=old_visible,
                apply_db=lambda u, url, d: ctx.db.pm_switch_link(lid, cid, ctx.dst["id"], u, url, d))
    except Exception as exc:
        logger.exception("panel-migration: link %s failed", lid)
        result = _res("failed", error=str(exc) or type(exc).__name__)
    await _record(ctx, "link", lid, result, user_id=link.get("user_id"), old_username=link.get("username"),
                  old_url=link.get("subscription_url"))
    return result


# ---------------------------------------------------------------------------
# اطلاع‌رسانی به کاربر
# ---------------------------------------------------------------------------
def build_user_message(name: str, link: str, link_changed: bool, dst_name: str = "") -> str:
    lines = [tr("🔄 سرویس شما به سرور جدید منتقل شد"), ""]
    if name:
        lines.append(tr("سرویس:") + f" <b>{html.escape(name)}</b>")
    lines.append(tr("✅ حجم و زمان باقی‌مانده‌ی شما بدون تغییر حفظ شده است."))
    lines += ["", tr("🔗 لینک اشتراک جدید شما:"), f"<code>{html.escape(link)}</code>", ""]
    if link_changed:
        lines.append(tr("لینک قبلی دیگر کار نمی‌کند. لطفاً در برنامه‌ی خود اشتراک قدیمی را حذف کنید و این لینک را "
                        "به‌جایش اضافه کنید."))
    else:
        lines.append(tr("لینک شما تغییری نکرده است؛ فقط کافی است داخل برنامه‌ات اشتراک را یک بار به‌روزرسانی "
                        "(Update) کنی تا کانفیگ‌های جدید دریافت شوند."))
    return "\n".join(lines)


async def _notify(db, bot, notes: dict) -> int:
    """notes: {cc_id: (user_id, old_visible)} → تعداد پیام‌های ارسال‌شده."""
    sent = 0
    for cc_id, (user_id, old_visible) in notes.items():
        try:
            cc = await asyncio.to_thread(db.get_custom_config_by_id, cc_id)
            if not cc or not user_id:
                continue
            new_link = await asyncio.to_thread(_visible_link, db, cc_id, cc["subscription_url"])
            if not new_link:
                continue
            name = (cc["display_name"] if "display_name" in cc.keys() and cc["display_name"] else cc["username"])
            text = build_user_message(name, new_link, link_changed=(new_link != old_visible))
            await bot.send_message(int(user_id), text, parse_mode="HTML", disable_web_page_preview=True)
            sent += 1
        except Exception as exc:
            logger.info("panel-migration: notify %s failed: %s", user_id, type(exc).__name__)
        await asyncio.sleep(0.06)
    return sent


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------
async def run_migration(db, source_id: int, dest_id: int, opts: Options, *, bot=None, admin_id=None,
                        progress=None) -> dict:
    """همه‌ی سرویس‌های فعال پنل مبدأ را به پنل مقصد منتقل می‌کند و گزارش برمی‌گرداند."""
    source_id, dest_id = int(source_id), int(dest_id)
    if source_id in _RUNNING:
        return {"ok": False, "error": "مهاجرت این پنل همین الان در حال اجراست."}
    _RUNNING.add(source_id)
    run_id = None
    try:
        await asyncio.to_thread(db.pm_ensure_tables)
        src = await asyncio.to_thread(db.get_panel_server, source_id)
        dst = await asyncio.to_thread(db.get_panel_server, dest_id)
        if not src or not dst or source_id == dest_id:
            return {"ok": False, "error": "پنل مبدأ/مقصد نامعتبر است."}
        if not dst["is_active"]:
            return {"ok": False, "error": "پنل مقصد غیرفعال است."}

        primaries = await asyncio.to_thread(db.pm_list_primary, source_id)
        links = await asyncio.to_thread(db.pm_list_links, source_id)
        units = [("primary", row) for row in primaries] + [("link", row) for row in links]
        if not units:
            return {"ok": False, "error": "سرویس فعالی روی پنل مبدأ نیست."}

        run_id = await asyncio.to_thread(db.pm_create_run, source_id, dest_id, admin_id, opts.as_dict(), len(units))
        ctx = _Ctx(db=db, run_id=run_id, src=src, dst=dst, src_provider=get_provider(src),
                   dst_provider=get_provider(dst), opts=opts)

        counts = {"migrated": 0, "failed": 0, "skipped": 0}
        notes: dict = {}
        estimated_n = 0
        aborted = False
        done = 0
        for start in range(0, len(units), BATCH_SIZE):
            batch = units[start:start + BATCH_SIZE]
            results = await asyncio.gather(*[
                (_migrate_primary(ctx, row) if kind == "primary" else _migrate_link(ctx, row))
                for kind, row in batch])
            for result in results:
                done += 1
                if result["status"] == "done":
                    counts["migrated"] += 1
                    estimated_n += 1 if result.get("estimated") else 0
                    notes.setdefault(result["cc_id"], (result.get("user_id"), result.get("old_visible", "")))
                elif result["status"] == "skipped":
                    counts["skipped"] += 1
                else:
                    counts["failed"] += 1
            await asyncio.to_thread(db.pm_update_run, run_id, **counts)
            if progress:
                try:
                    await progress(done, len(units), counts["migrated"], counts["failed"], counts["skipped"])
                except Exception:
                    pass
            if counts["migrated"] == 0 and counts["failed"] >= ABORT_AFTER_FAILS:
                aborted = True
                break

        retarget = {}
        if opts.retarget_sales and counts["migrated"] > 0 and not aborted:
            retarget = await asyncio.to_thread(db.pm_retarget_sales, source_id, dest_id)

        notified = 0
        if opts.notify_users and bot is not None and notes:
            notified = await _notify(db, bot, notes)

        status = "aborted" if aborted else "done"
        await asyncio.to_thread(db.pm_update_run, run_id, status=status, notified=notified, **counts)
        failures = await asyncio.to_thread(db.pm_run_failures, run_id, 15)
        return {"ok": not aborted, "aborted": aborted, "run_id": run_id, "total": len(units), **counts,
                "estimated": estimated_n, "notified": notified, "retarget": retarget, "failures": failures,
                "source_name": src["name"], "dest_name": dst["name"],
                "error": ("چند خطای پشت‌سرهم و هیچ موفقیتی؛ اجرا متوقف شد. تنظیمات پنل مقصد "
                          "(کاربر نمونه/گروه/اینباند) را چک کن.") if aborted else ""}
    except Exception as exc:
        logger.exception("panel-migration: run crashed")
        if run_id:
            await asyncio.to_thread(db.pm_update_run, run_id, status="error", note=str(exc)[:300])
        return {"ok": False, "error": f"خطای غیرمنتظره: {exc}", "run_id": run_id}
    finally:
        _RUNNING.discard(source_id)
