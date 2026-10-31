# -*- coding: utf-8 -*-
"""ترمیم کاربران قدیمی پنل بعد از تغییر نود/هاست/گروه روی خود پنل."""
import asyncio
import logging
import time

from panel_providers import get_provider

logger = logging.getLogger(__name__)

HEAL_COOLDOWN = 600
_last_heal: dict = {}


def _server_for(db, cc):
    sid = cc["panel_server_id"] if "panel_server_id" in cc.keys() else None
    return db.get_panel_server(int(sid)) if sid else None


async def heal_config(db, cc) -> bool:
    """یک سرویس بدون کانفیگ را با قالب فعلی پنل هم‌گام می‌کند؛ True یعنی تغییری اعمال شد."""
    cid = int(cc["id"])
    now = time.monotonic()
    if now - _last_heal.get(cid, -HEAL_COOLDOWN) < HEAL_COOLDOWN:
        return False
    _last_heal[cid] = now
    try:
        server = await asyncio.to_thread(_server_for, db, cc)
        if not server:
            return False
        provider = get_provider(server)
        if not getattr(provider, "supports_template_resync", False):
            return False
        changed = await provider.resync_user_template(cc["username"])
        if changed:
            logger.warning("panel-resync: config=%s user=%s group_ids repaired", cid, cc["username"])
        return bool(changed)
    except Exception as exc:
        logger.warning("panel-resync failed config=%s: %s", cid, type(exc).__name__)
        return False


async def resync_server(db, server_id: int) -> dict:
    """همه‌ی سرویس‌های فعال یک پنل را با قالب فعلی هم‌گام می‌کند."""
    def _rows():
        with db._get_conn() as conn:
            return conn.execute(
                "SELECT id,username FROM custom_configs WHERE panel_server_id=? "
                "AND COALESCE(status,'active') NOT IN ('deleted','cancelled')", (int(server_id),)).fetchall()
    rows = await asyncio.to_thread(_rows)
    server = await asyncio.to_thread(db.get_panel_server, int(server_id))
    result = {"total": len(rows), "changed": 0, "failed": 0}
    if not server:
        return result
    provider = get_provider(server)
    if not getattr(provider, "supports_template_resync", False):
        return result
    for row in rows:
        try:
            if await provider.resync_user_template(row["username"]):
                result["changed"] += 1
        except Exception:
            result["failed"] += 1
    return result
