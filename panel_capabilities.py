# -*- coding: utf-8 -*-
"""Single source of truth for runtime capabilities.

UI, product validation and provisioning must not each maintain their own list of
which provider/node can do what.  This module keeps capability discovery small
and dependency-free so it can safely be used by the database, API and bot.
"""
from __future__ import annotations

from typing import Iterable

from panel_providers import PROVIDERS


USER_LIMIT = "user_limit"
OPENVPN_USERPASS = "openvpn_username_password"


def provider_capabilities(panel_type: str) -> dict:
    cls = PROVIDERS.get(str(panel_type or "").strip().lower())
    if not cls:
        return {USER_LIMIT: False}
    return {
        USER_LIMIT: bool(getattr(cls, "supports_user_limit", False)),
    }


def server_capabilities(server) -> dict:
    if not server:
        return {USER_LIMIT: False}
    return provider_capabilities(server["panel_type"])


def all_panels_support(panel_servers: Iterable, capability: str) -> bool:
    rows = list(panel_servers or [])
    if not rows:
        return False
    return all(bool(server_capabilities(row).get(capability, False)) for row in rows)


def product_panel_ids(db, product) -> list[int]:
    """VPN panel targets only; SSH nodes are intentionally excluded."""
    def value(key):
        try:
            return product[key]
        except (KeyError, IndexError, TypeError):
            return None

    ids = [int(value("provision_server_id"))] if value("provision_server_id") else []
    product_id = value("id")
    if product_id:
        extra = db.get_product_extra_targets(int(product_id))
        ids.extend(int(x) for x in extra.get("panels", []) if int(x) > 0)
    return list(dict.fromkeys(ids))


def product_panel_servers(db, product) -> list:
    return [db.get_panel_server(pid) for pid in product_panel_ids(db, product)]


def product_capabilities(db, product) -> dict:
    panels = product_panel_servers(db, product)
    return {
        USER_LIMIT: all_panels_support(panels, USER_LIMIT),
        "panel_count": len(panels),
        "panel_types": [str(p["panel_type"]) for p in panels if p],
    }


def product_supports_user_limit(db, product) -> bool:
    return bool(product_capabilities(db, product)[USER_LIMIT])


def normalize_user_limit(base_users=0, extra_user_price=0, max_users=0, *, supported=False) -> tuple[int, int, int]:
    """Return a safe (base, price, max) triple shared by every entry point."""
    base = max(int(base_users or 0), 0)
    extra = max(int(extra_user_price or 0), 0)
    maximum = max(int(max_users or 0), 0)
    if not supported:
        return 0, 0, 0
    if base > 20 or maximum > 20 or (maximum and maximum < base) or (extra and maximum <= max(base, 1)):
        raise ValueError("تنظیمات محدودیت کاربر نامعتبر است.")
    if extra <= 0 or maximum < 2 or maximum <= max(base, 1):
        extra, maximum = 0, 0
    return base, extra, maximum


def node_capabilities(node, protocols=None) -> dict:
    """Capabilities exposed by the current ShopVPN Linux Agent contract."""
    selected = set(protocols or [])
    try:
        listed = node.get("protocols")
    except AttributeError:
        listed = None
    selected.update(str(x).lower() for x in (listed or []))
    return {
        OPENVPN_USERPASS: "openvpn" in selected,
    }
