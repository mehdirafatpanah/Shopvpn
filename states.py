# -*- coding: utf-8 -*-
from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    waiting_receipt = State()


class DiscountEntry(StatesGroup):
    waiting_code = State()


class WalletTopup(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


class ContactFlow(StatesGroup):
    waiting_message = State()


class AdminReplyFlow(StatesGroup):
    waiting_reply = State()


class AdminAddCategory(StatesGroup):
    waiting_name = State()


class AdminAddProduct(StatesGroup):
    waiting_category = State()
    waiting_name = State()
    waiting_price = State()
    waiting_desc = State()
    waiting_duration = State()
    waiting_provision_choice = State()
    waiting_provision_server = State()
    waiting_auto_provision_volume = State()


class AdminAddConfigs(StatesGroup):
    waiting_product = State()
    waiting_links = State()


class AdminAddTestConfigs(StatesGroup):
    waiting_links = State()


class AdminTestConfigSettings(StatesGroup):
    waiting_volume = State()
    waiting_duration = State()


class AdminForceJoin(StatesGroup):
    waiting_channel = State()


class AdminEditButton(StatesGroup):
    waiting_text = State()


class AdminSetCard(StatesGroup):
    waiting_number = State()
    waiting_holder = State()
    waiting_autodelete_custom = State()


class AdminSetPlisio(StatesGroup):
    waiting_key = State()


class AdminSetAbanGateway(StatesGroup):
    waiting_key = State()


class AdminBroadcast(StatesGroup):
    waiting_message = State()


class AdminDeepLinkTools(StatesGroup):
    waiting_custom_param = State()


class AdminChannelButton(StatesGroup):
    waiting_forward = State()
    waiting_button_text = State()
    waiting_custom_param = State()


class AdminAddAdmin(StatesGroup):
    waiting_id = State()


class AdminRemoveAdmin(StatesGroup):
    waiting_id = State()


class AdminChangeRole(StatesGroup):
    waiting_id = State()


class AdminEditWelcome(StatesGroup):
    waiting_text = State()


class AdminCreateDiscount(StatesGroup):
    waiting_code = State()
    waiting_type_value = State()
    waiting_maxuses = State()


class AdminReferralPercent(StatesGroup):
    waiting_value = State()


class AdminReferralCommissionMax(StatesGroup):
    waiting_value = State()


class AdminReferralFreeConfigThreshold(StatesGroup):
    waiting_value = State()


class AdminReferralInviteBonusAmount(StatesGroup):
    waiting_value = State()


class AdminReferralInviteBonusMax(StatesGroup):
    waiting_value = State()


class AdminResellerCredit(StatesGroup):
    waiting_user_id = State()
    waiting_delta = State()


class AdminAddResellerBot(StatesGroup):
    waiting_token = State()
    waiting_owner_id = State()
    waiting_owner_name = State()
    waiting_level = State()


class AdminSetPanelDomain(StatesGroup):
    """آدرس دامنه‌ی پنل مدیریت وب مستقل (برای ساخت لینک راه‌اندازی پنل نماینده‌های
    کامل). فقط داخل دیتابیس ذخیره می‌شود، نیازی به دست‌زدن به .env نیست."""
    waiting_url = State()


class AdminWheelSettings(StatesGroup):
    waiting_win_percent = State()
    waiting_prizes = State()
    waiting_expiry = State()
    waiting_cooldown = State()


class AdminRenewalSettings(StatesGroup):
    waiting_days_before = State()
    waiting_percent = State()
    waiting_expiry_hours = State()


class AdminStockAlertSettings(StatesGroup):
    waiting_threshold = State()


class AdminVolumeReminderSettings(StatesGroup):
    waiting_percent = State()
    waiting_gb_left = State()
    waiting_discount_percent = State()
    waiting_discount_hours = State()


class AdminRestoreBackup(StatesGroup):
    waiting_file = State()
    waiting_confirm = State()


class AdminAddPanelServer(StatesGroup):
    waiting_name = State()
    waiting_type = State()
    waiting_url = State()
    waiting_username = State()
    waiting_password = State()
    waiting_template_user = State()
    waiting_inbound_select = State()
    waiting_sub_base_url = State()


class AdminSetPanelTemplate(StatesGroup):
    waiting_username = State()


class AdminSetPanelSubUrl(StatesGroup):
    waiting_url = State()


class AdminAddPricingTier(StatesGroup):
    waiting_from_gb = State()
    waiting_to_gb = State()
    waiting_price = State()


class AdminCustomConfigSettings(StatesGroup):
    waiting_min_gb = State()
    waiting_max_gb = State()


class AdminResetTestConfig(StatesGroup):
    waiting_message = State()


class CustomConfigFlow(StatesGroup):
    waiting_username = State()
    waiting_volume = State()
    waiting_receipt = State()


class ResellerFlow(StatesGroup):
    waiting_username = State()
    waiting_volume = State()


class ResellerRequestFlow(StatesGroup):
    waiting_volume = State()
    waiting_text = State()
    waiting_receipt = State()
    waiting_bot_token = State()
    waiting_owner_id = State()


class AdminResellerRequestFlow(StatesGroup):
    waiting_price = State()
    waiting_reject_reason = State()


class AdminTempMessage(StatesGroup):
    waiting_target_id = State()
    waiting_text = State()
    waiting_custom_minutes = State()
