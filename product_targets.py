# -*- coding: utf-8 -*-
"""Product-scoped panel destinations with legacy-safe fallback."""
from __future__ import annotations
import json

from panel_providers import get_provider, PanelError
from panel_providers.base import PanelPermissionError


def _json(value, fallback=None):
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _server_dict(server):
    try:
        return dict(server)
    except Exception:
        return {k: server[k] for k in server.keys()}


async def list_product_targets(server):
    """Return normalized selectable destinations through the common provider API."""
    provider = get_provider(server)
    permission_warning = ""
    try:
        info = await provider.list_product_targets()
    except PanelPermissionError as exc:
        # ادمین پنل اجازه‌ی خواندن فهرست زنده را ندارد (مثلاً ۴۰۳ groups.read در PasarGuard).
        # اگر قالب ذخیره‌شده‌ی پنل گروه دارد، با همان ادامه می‌دهیم و هشدار برمی‌گردانیم؛
        # وگرنه خطای واضح به ادمین نشان داده می‌شود.
        info = None
        permission_warning = str(exc)
    if info:
        info.setdefault("selected", [])
        return info

    # Legacy fallback: panels without a documented/live destination-list API keep
    # their existing template-based behavior. This is intentionally read-only.
    result = _legacy_targets(server)
    if permission_warning:
        if not result.get("choices"):
            raise PanelError(permission_warning)
        result["warning"] = permission_warning + " (فهرست از قالب ذخیره‌شده‌ی پنل نمایش داده شد.)"
    return result


def _legacy_targets(server):
    panel_type = str(server["panel_type"] or "").lower()
    raw = _json(server["group_ids"] if "group_ids" in server.keys() else None, [])
    if isinstance(raw, dict):
        choices = []
        for proto, items in raw.items():
            for item in items or []:
                value = f"{proto}::{item}"
                choices.append({"value": value, "label": f"{proto.upper()} · {item}"})
        selected = [f"{proto}::{item}" for proto, items in raw.items() for item in (items or [])]
        return {"field": "group_ids", "kind": "protocol_map", "selected": selected, "choices": choices}
    if isinstance(raw, list):
        return {"field": "group_ids", "kind": "list", "selected": [str(x) for x in raw], "choices": [
            {"value": str(x), "label": str(x)} for x in raw
        ]}
    if isinstance(raw, str) and raw:
        return {"field": "group_ids", "kind": "scalar", "selected": [raw], "choices": [{"value": raw, "label": raw}]}
    if panel_type in {"wgdashboard", "mikrotik", "ibsng"}:
        return {"field": "group_ids", "kind": "scalar", "selected": [], "choices": []}
    return {"field": "group_ids", "kind": "list", "selected": [], "choices": []}


def build_target_config(server, selected_values, target_info=None):
    """Validate UI values against the connected panel's currently available targets."""
    selected = list(dict.fromkeys(str(x) for x in (selected_values or [])))
    if not selected:
        raise ValueError("برای محصول حداقل یک گروه یا Inbound انتخاب کنید.")
    panel_type = str(server["panel_type"] or "").lower()
    target_info = target_info or {}
    live_choices = target_info.get("choices") or []
    live_allowed = {str(item.get("value")) for item in live_choices if isinstance(item, dict)}
    if live_allowed and any(x not in live_allowed for x in selected):
        raise ValueError("یکی از مقصدهای انتخاب‌شده دیگر در پنل وجود ندارد؛ فهرست را دوباره بارگذاری کنید.")

    if target_info.get("kind") == "scalar" and target_info.get("field") == "group_ids":
        if len(selected) != 1:
            raise ValueError("برای این پنل باید دقیقاً یک مقصد انتخاب کنید.")
        config = {"field": "group_ids", "value": selected[0]}
        if "id" in server.keys(): config["panel_server_id"] = int(server["id"])
        return config

    # Live Marzban API choices are protocol::inbound values and are authoritative,
    # even when the sample user's template contains only a subset of all inbounds.
    if target_info.get("kind") == "protocol_map" and target_info.get("field") == "group_ids":
        result = {}
        for value in selected:
            if "::" not in value:
                raise ValueError("شناسه Inbound پنل معتبر نیست.")
            proto, inbound = value.split("::", 1)
            result.setdefault(proto, []).append(inbound)
        config = {"field": "group_ids", "value": result}
        if "id" in server.keys(): config["panel_server_id"] = int(server["id"])
        return config

    if panel_type in {"3xui", "alireza"}:
        try:
            values = [int(x) for x in selected]
        except ValueError as exc:
            raise ValueError("شناسه Inbound نامعتبر است.") from exc
        if panel_type == "alireza" and len(values) != 1:
            raise ValueError("پنل Alireza فقط یک Inbound برای هر محصول می‌پذیرد.")
        result = {"field": "xui_inbound_ids", "value": values}
        if "id" in server.keys(): result["panel_server_id"] = int(server["id"])
        return result

    raw = _json(server["group_ids"] if "group_ids" in server.keys() else None, [])
    if isinstance(raw, dict):
        allowed = {f"{proto}::{item}" for proto, items in raw.items() for item in (items or [])}
        if any(x not in allowed for x in selected):
            raise ValueError("یکی از مقصدهای انتخاب‌شده در قالب فعلی پنل وجود ندارد.")
        result = {}
        for value in selected:
            proto, item = value.split("::", 1)
            result.setdefault(proto, []).append(item)
        config = {"field": "group_ids", "value": result}
        if "id" in server.keys(): config["panel_server_id"] = int(server["id"])
        return config
    if isinstance(raw, list):
        if panel_type == "rebecca" and len(selected) != 1:
            raise ValueError("پنل Rebecca فقط یک Service برای هر محصول می‌پذیرد.")
        allowed = {str(x) for x in raw}
        if not live_allowed and any(x not in allowed for x in selected):
            # PasarGuard uses a live groups API; the list of all groups may differ from sample user groups.
            if str(server["panel_type"]).lower() != "pasarguard":
                raise ValueError("یکی از گروه‌های انتخاب‌شده در قالب فعلی پنل وجود ندارد.")
        vals = []
        for x in selected:
            try: vals.append(int(x))
            except ValueError: vals.append(x)
        result = {"field": "group_ids", "value": vals}
        if "id" in server.keys(): result["panel_server_id"] = int(server["id"])
        return result
    if isinstance(raw, str):
        if len(selected) != 1:
            raise ValueError("این نوع پنل فقط یک مقصد برای هر محصول می‌پذیرد.")
        result = {"field": "group_ids", "value": selected[0]}
        if "id" in server.keys(): result["panel_server_id"] = int(server["id"])
        return result
    raise ValueError("این پنل هنوز قالب گروه/مقصد قابل انتخاب ندارد. ابتدا قالب پنل را تنظیم کنید.")


def _sync_choices_from_server(server, field):
    raw = _json(server[field] if field in server.keys() else None, None)
    if raw is None and field == "xui_inbound_ids":
        raw = _json(server["xui_inbound_ids"] if "xui_inbound_ids" in server.keys() else None, None)
        if not raw and "xui_inbound_id" in server.keys() and server["xui_inbound_id"]:
            raw = [server["xui_inbound_id"]]
    return [{"value": str(x)} for x in (raw if isinstance(raw, list) else [])]


def apply_target_config(server, raw):
    """Overlay a saved destination only for this provider instance. NULL means legacy."""
    cfg = _json(raw, None)
    if not isinstance(cfg, dict) or "field" not in cfg:
        return server
    if cfg.get("panel_server_id") is not None:
        try:
            if int(cfg["panel_server_id"]) != int(server["id"]):
                return server
        except (KeyError, TypeError, ValueError):
            return server
    data = _server_dict(server)
    field = cfg.get("field")
    value = cfg.get("value")
    if field == "group_ids":
        data["group_ids"] = json.dumps(value, ensure_ascii=False)
    elif field == "xui_inbound_ids":
        data["xui_inbound_ids"] = json.dumps(value)
        data["xui_inbound_id"] = None
    return data


def apply_product_target(server, product):
    """Overlay product destination only for this provider instance. NULL means legacy."""
    try:
        raw = product["provision_target_config"]
    except (KeyError, IndexError, TypeError):
        raw = None
    return apply_target_config(server, raw)
