# -*- coding: utf-8 -*-
"""همگام‌سازی پنل‌های اضافه‌ی یک سرویس چندپنلی با عملیات روی سرویس اصلی (حذف/قطع)."""

import asyncio
import logging

from panel_providers import get_provider

logger = logging.getLogger(__name__)


async def _delete_link(db, link, final_attempt: bool) -> bool:
    try:
        server = await asyncio.to_thread(db.get_panel_server, link["panel_server_id"])
        if server:
            result = await get_provider(server).delete_user(link["username"])
            if result is False and not final_attempt:
                raise RuntimeError("panel refused delete")
    except Exception:
        logger.exception("extra panel user delete failed (link=%s)", link["id"])
        return False
    await asyncio.to_thread(db.delete_config_panel_link, link["id"])
    return True


async def delete_linked_panel_users(db, custom_config_id) -> bool:
    """کاربران پنل‌های اضافه را از پنل پاک می‌کند؛ لینکِ ناموفق برای تلاش مجدد باقی می‌ماند."""
    try:
        links = await asyncio.to_thread(db.panel_links_for_config, int(custom_config_id), False)
    except Exception:
        logger.exception("panel links lookup failed for config %s", custom_config_id)
        return False
    all_ok = True
    for link in links:
        if not await _delete_link(db, link, final_attempt=link.get("status") == "delete_pending"):
            await asyncio.to_thread(db.mark_config_panel_link_delete_pending, link["id"])
            all_ok = False
    return all_ok


async def retry_pending_link_deletes(db) -> int:
    """لینک‌های در انتظار حذف را دوباره تلاش می‌کند و تعداد موفق‌ها را برمی‌گرداند."""
    try:
        links = await asyncio.to_thread(db.pending_delete_panel_links)
    except Exception:
        logger.exception("pending panel link lookup failed")
        return 0
    done = 0
    for link in links:
        if await _delete_link(db, link, final_attempt=True):
            done += 1
    return done


async def set_linked_panel_users_enabled(db, custom_config_id, enabled: bool) -> bool:
    """وضعیت کاربران پنل‌های اضافه را تغییر می‌دهد؛ فقط وقتی همه موفق باشند True برمی‌گرداند."""
    try:
        links = await asyncio.to_thread(db.panel_links_for_config, int(custom_config_id))
    except Exception:
        logger.exception("panel links lookup failed for config %s", custom_config_id)
        return False
    all_ok = True
    for link in links:
        try:
            server = await asyncio.to_thread(db.get_panel_server, link["panel_server_id"])
            if server:
                await get_provider(server).set_enabled(link["username"], bool(enabled))
        except Exception:
            logger.exception("extra panel user toggle failed (config=%s, link=%s)", custom_config_id, link["id"])
            all_ok = False
    return all_ok
