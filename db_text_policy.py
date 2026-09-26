# -*- coding: utf-8 -*-
"""Policy for text stored in the database.

Database text is intentionally split into two classes:

* ``system``: text owned by ShopVPN (UI/system messages, configurable system
  copy, notification templates). It may be localized at render time.
* ``custom``: text authored by an admin/user or received from an external
  service. It is data, not UI copy, and MUST be rendered verbatim.

The policy is descriptive and is also used by tests to prevent accidental
``tr(...)`` calls around user/admin content.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class TextStorageKind(str, Enum):
    SYSTEM = "system"
    CUSTOM = "custom"
    NEUTRAL = "neutral"


# Table -> columns whose values are user/admin/external content.
# Keep this list explicit: adding a new free-form DB field should force the
# developer to classify it here before it is rendered.
CUSTOM_TEXT_FIELDS = {
    "users": {"username", "first_name"},
    "categories": {"name"},
    "products": {"name", "description"},
    "test_config_plans": {"name", "name_prefix"},
    "scheduled_broadcasts": {"message_text"},
    "support_messages": {"message"},
    "ai_support_messages": {"message"},
    "ai_faq_items": {"question", "answer"},
    "tutorial_devices": {"name"},
    "tutorial_steps": {"title", "content"},
    "tickets": {"subject"},
    "ticket_messages": {"message"},
    "ticket_departments": {"name"},
    "panel_servers": {"name"},
    "custom_config_products": {"name", "description"},
    "custom_configs": {"username"},
    "custom_config_history": {"detail"},
    "reseller_tiers": {"code", "name", "summary", "description"},
    "reseller_requests": {"reject_reason"},
    "reseller_tier_requests": {"reject_reason"},
    "custom_gateways": {"name"},
    "card_to_card_cards": {"holder_name", "bank_name"},
    "wallet_tx_label": {"note"},
    "payment_webhook_logs": {"error", "raw_body"},
    "mobile_app_tokens": {"name"},
    "mobile_fcm_tokens": {"device_label"},
    "report_topics": {"name"},
}

# Explicitly system-owned text fields stored in DB.
SYSTEM_TEXT_FIELDS = {
    "bot_text_registry": {"default_text"},
}

# Settings are mixed. The ``msgtext__`` namespace is system copy; arbitrary
# settings are not translated because many are labels, secrets, URLs, or
# admin-authored/custom content.
SYSTEM_SETTING_PREFIXES = ("msgtext__",)


def classify_text_field(table: str, column: str, *, setting_key: Optional[str] = None) -> TextStorageKind:
    if setting_key is not None:
        if any(setting_key.startswith(prefix) for prefix in SYSTEM_SETTING_PREFIXES):
            return TextStorageKind.SYSTEM
        return TextStorageKind.NEUTRAL
    table = str(table or "").strip().lower()
    column = str(column or "").strip().lower()
    if column in CUSTOM_TEXT_FIELDS.get(table, set()):
        return TextStorageKind.CUSTOM
    if column in SYSTEM_TEXT_FIELDS.get(table, set()):
        return TextStorageKind.SYSTEM
    return TextStorageKind.NEUTRAL


def is_custom_text_field(table: str, column: str) -> bool:
    return classify_text_field(table, column) is TextStorageKind.CUSTOM


def localize_system_text(value: object, language: Optional[str] = None) -> str:
    """Localize a system-owned stored value; never use this for custom data."""
    from i18n import tr
    return tr(str(value or ""), language)


def render_db_text(table: str, column: str, value: object, language: Optional[str] = None) -> str:
    """Render a classified DB value safely.

    Custom and neutral fields are returned verbatim. Only fields explicitly
    classified as system text enter the translation layer.
    """
    if classify_text_field(table, column) is TextStorageKind.SYSTEM:
        return localize_system_text(value, language)
    return str(value or "")

# Frontend-facing stored content. These values are intentionally CUSTOM:
# the Admin Panel/Mini App may display them, but i18n must never rewrite them.
CUSTOM_SETTING_KEYS = {
    "store_name",
    "miniapp_banner_text",
    "miniapp_banners",
}

# JSON/object fields used by Mini App/Admin Panel banners. Keep this explicit so
# future renderers cannot accidentally pass them through tr().
CUSTOM_BANNER_FIELDS = {
    "icon", "title", "sub", "cta", "image", "image_url", "image_only",
    "bg", "enabled", "nav",
}


def classify_setting(key: str) -> TextStorageKind:
    """Classify a value stored in the generic settings table."""
    key = str(key or "").strip()
    if key in CUSTOM_SETTING_KEYS:
        return TextStorageKind.CUSTOM
    if any(key.startswith(prefix) for prefix in SYSTEM_SETTING_PREFIXES):
        return TextStorageKind.SYSTEM
    return TextStorageKind.NEUTRAL


def render_stored_setting(key: str, value: object, language: Optional[str] = None) -> str:
    """Render a settings value under the storage policy.

    Custom/neutral settings are returned verbatim. Only explicit system-copy
    settings can enter the translation layer.
    """
    if classify_setting(key) is TextStorageKind.SYSTEM:
        return localize_system_text(value, language)
    return str(value or "")


def render_custom_content(value: object) -> str:
    """Render admin/user-authored frontend content without localization."""
    return str(value or "")
