# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from .constants import (
    DuplicateBotTokenError,
    WEB_ADMIN_PERMISSIONS,
    ROLE_PERMISSION_PRESETS,
    DEFAULT_BANNERS,
    DEFAULT_SETTINGS,
    BUILTIN_PAYMENT_METHODS,
    MENU_BUTTON_META,
    ACCOUNT_TOGGLE_KEYS,
    PAYMENT_METHOD_META,
    DEFAULT_PAYMENT_METHOD_ORDER,
    ACCOUNT_HUB_META,
    DEFAULT_ACCOUNT_HUB_ORDER,
    BUYFLOW_META,
    DEFAULT_BUYFLOW_CONFIRM_ORDER,
    BUYFLOW_STYLE_ONLY_META,
    DEFAULT_MENU_ORDER,
    AUTO_PROVISION_UNLIMITED_STOCK,
    _wallet_tag,
)
from ._base import DatabaseBase
from .users import UsersMixin
from .user_groups import UserGroupsMixin
from .subscriptions import SubscriptionsMixin
from .catalog import CatalogMixin
from .orders import OrdersMixin
from .payments import PaymentsMixin
from .panels import PanelsMixin
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from .tickets import TicketsMixin
from .resellers import ResellersMixin
from .system import SystemMixin
from .business import BusinessMixin
from .userbot_store import UserbotMixin
from .leak_store import LeakStoreMixin
from .gift_cards import GiftCardsMixin
from .seasons import SeasonsMixin
from .engagement import EngagementMixin
from .dedicated_sub import DedicatedSubMixin
from .usage import UsageMixin
from .multi_target import MultiTargetMixin
from .panel_migration import PanelMigrationMixin
from .custom_menu import CustomMenuMixin

class Database(
    DatabaseBase,
    UsersMixin,
    UserGroupsMixin,
    SubscriptionsMixin,
    CatalogMixin,
    OrdersMixin,
    PaymentsMixin,
    PanelsMixin,
    TicketsMixin,
    ResellersMixin,
    SystemMixin,
    BusinessMixin,
    UserbotMixin,
    LeakStoreMixin,
    GiftCardsMixin,
    SeasonsMixin,
    EngagementMixin,
    DedicatedSubMixin,
    UsageMixin,
    MultiTargetMixin,
    PanelMigrationMixin,
    CustomMenuMixin,
):
    pass

__all__ = [
    "Database",
    "DatabaseBase",
    "DuplicateBotTokenError",
    "WEB_ADMIN_PERMISSIONS",
    "ROLE_PERMISSION_PRESETS",
    "DEFAULT_BANNERS",
    "DEFAULT_SETTINGS",
    "BUILTIN_PAYMENT_METHODS",
    "MENU_BUTTON_META",
    "ACCOUNT_TOGGLE_KEYS",
    "PAYMENT_METHOD_META",
    "DEFAULT_PAYMENT_METHOD_ORDER",
    "ACCOUNT_HUB_META",
    "DEFAULT_ACCOUNT_HUB_ORDER",
    "BUYFLOW_META",
    "DEFAULT_BUYFLOW_CONFIRM_ORDER",
    "BUYFLOW_STYLE_ONLY_META",
    "DEFAULT_MENU_ORDER",
    "AUTO_PROVISION_UNLIMITED_STOCK",
    "_wallet_tag",
]
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
