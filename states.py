# -*- coding: utf-8 -*-
from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    waiting_config_name = State()
    waiting_receipt = State()
    waiting_customgw_phone = State()


class DiscountEntry(StatesGroup):
    waiting_code = State()


class RenewalDiscountEntry(StatesGroup):
    """قابلیت ۵۱: کد تخفیف در بخش «تمدید کامل سرویس» (نه تمدید حجم/زمان)."""
    waiting_code = State()


class WalletTopup(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()
    waiting_customgw_phone = State()


class WalletGiftCode(StatesGroup):
    waiting_code = State()


class CoinConvert(StatesGroup):
    waiting_amount = State()


class WalletTransfer(StatesGroup):
    waiting_receiver = State()
    waiting_amount = State()


class ContactFlow(StatesGroup):
    waiting_message = State()


class TicketFlow(StatesGroup):
    waiting_department = State()
    waiting_subject = State()
    waiting_message = State()


class AIChatFlow(StatesGroup):
    chatting = State()


class TicketReplyFlow(StatesGroup):
    waiting_message = State()


class AdminReplyFlow(StatesGroup):
    waiting_reply = State()


class AdminTicketReplyFlow(StatesGroup):
    waiting_reply = State()


class AdminSetSupportContact(StatesGroup):
    waiting_id = State()


class AdminAIFaqAdd(StatesGroup):
    waiting_question = State()
    waiting_answer = State()


class AdminTutorialDeviceAdd(StatesGroup):
    waiting_name = State()


class AdminTutorialStepAdd(StatesGroup):
    waiting_content = State()


class AdminTutorialRename(StatesGroup):
    waiting_title = State()


class AdminSetGeminiKey(StatesGroup):
    waiting_key = State()

class AdminSetGroqKey(StatesGroup):
    waiting_key = State()


class AdminSetOpenRouterKey(StatesGroup):
    waiting_key = State()


class AdminSetTranslationGeminiKey(StatesGroup):
    waiting_key = State()


class AdminSetTranslationOpenRouterKey(StatesGroup):
    waiting_key = State()


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
    waiting_provision_duration_mode = State()
    waiting_auto_provision_volume_mode = State()
    waiting_auto_provision_volume = State()
    waiting_base_users = State()
    waiting_user_extra_price = State()
    waiting_user_max = State()
    waiting_payment_methods = State()


class AdminAddConfigs(StatesGroup):
    waiting_product = State()
    waiting_links = State()


class AdminAddTestConfigs(StatesGroup):
    waiting_links = State()


class AdminAddTestPlan(StatesGroup):
    waiting_name = State()
    waiting_prefix = State()
    waiting_panel = State()
    waiting_volume_mb = State()
    waiting_duration_hours = State()


class AdminEditTestPlan(StatesGroup):
    waiting_name = State()
    waiting_prefix = State()
    waiting_panel = State()
    waiting_volume_mb = State()
    waiting_duration_hours = State()


class AdminCleanupSettings(StatesGroup):
    waiting_expired_days = State()
    waiting_test_days = State()
    waiting_warning_days = State()
    waiting_inactive_time = State()


class AdminForceJoin(StatesGroup):
    waiting_channel = State()


class AdminServiceAlertChannel(StatesGroup):
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


class AdminSetBlupal(StatesGroup):
    waiting_key = State()


class AdminSetNoapay(StatesGroup):
    waiting_key = State()
    waiting_secret = State()
    waiting_rate = State()


class AdminSetExtraGateway(StatesGroup):
    waiting_value = State()


class AdminC2CCard(StatesGroup):
    waiting_number = State()
    waiting_holder = State()
    waiting_bank = State()


class AdminC2CSettings(StatesGroup):
    waiting_timeout = State()
    waiting_digits = State()


class AdminBroadcast(StatesGroup):
    waiting_message = State()
    waiting_duration = State()
    waiting_custom_minutes = State()
    waiting_schedule_time = State()
    waiting_no_purchase_days = State()


class AdminBulkDiscount(StatesGroup):
    picking_filters = State()
    waiting_no_purchase_days = State()
    waiting_type_value = State()
    waiting_expiry = State()


class AdminXuiInbound(StatesGroup):
    waiting_protocol = State()
    waiting_network = State()
    waiting_tls = State()
    waiting_port = State()


class AdminXuiRestore(StatesGroup):
    waiting_file = State()
    waiting_confirm = State()


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


class AdminEditPostDeliveryText(StatesGroup):
    waiting_text = State()


class AdminSetQrBackground(StatesGroup):
    waiting_photo = State()


class AdminCreateWalletGift(StatesGroup):
    waiting_amount = State()
    waiting_maxuses = State()
    waiting_expiry = State()


class AdminCreateDiscount(StatesGroup):
    waiting_code = State()
    waiting_type_value = State()
    waiting_max_discount_amount = State()
    waiting_maxuses = State()
    waiting_min_purchase = State()
    waiting_max_purchase = State()
    waiting_scope = State()
    waiting_scope_category = State()
    waiting_scope_product = State()
    waiting_scope_products_multi = State()
    waiting_expiry = State()
    waiting_per_user = State()
    waiting_first_only = State()
    waiting_audience = State()


class AdminReferralPercent(StatesGroup):
    waiting_value = State()


class AdminReferralMultilevel(StatesGroup):
    waiting_value = State()

class AdminReferralCommissionMax(StatesGroup):
    waiting_value = State()

class AdminReferralRenewalPercent(StatesGroup):
    waiting_value = State()

class AdminReferralRenewalMax(StatesGroup):
    waiting_value = State()

class AdminReferralMinPurchase(StatesGroup):
    waiting_value = State()


class AdminReferralFreeConfigThreshold(StatesGroup):
    waiting_value = State()


class AdminReferralInviteBonusAmount(StatesGroup):
    waiting_value = State()


class AdminReferralInviteBonusMax(StatesGroup):
    waiting_value = State()


class AdminSignupGiftAmount(StatesGroup):
    waiting_value = State()


class AdminSignupGiftDelay(StatesGroup):
    waiting_value = State()


class AdminResellerCredit(StatesGroup):
    waiting_user_id = State()
    waiting_delta = State()
    waiting_limit = State()


class AdminResellerMembership(StatesGroup):
    waiting_fee_duration = State()


class AdminAddResellerBot(StatesGroup):
    waiting_token = State()
    waiting_owner_id = State()
    waiting_owner_name = State()


class AdminSetPanelDomain(StatesGroup):
    """آدرس دامنه‌ی پنل مدیریت وب مستقل (برای ساخت لینک راه‌اندازی پنل نماینده‌های
    کامل). فقط داخل دیتابیس ذخیره می‌شود، نیازی به دست‌زدن به .env نیست."""
    waiting_url = State()


class AdminSetPanelCapacity(StatesGroup):
    waiting_limit = State()


class AdminWheelSettings(StatesGroup):
    waiting_win_percent = State()
    waiting_lottery_prizes = State()
    waiting_lottery_report_chat = State()
    waiting_prizes = State()
    waiting_expiry = State()
    waiting_cooldown = State()


class AdminRenewalSettings(StatesGroup):
    waiting_days_before = State()
    waiting_percent = State()
    waiting_expiry_hours = State()


class AdminStockAlertSettings(StatesGroup):
    waiting_threshold = State()


class AdminMinAmountSettings(StatesGroup):
    """حداقل مبلغ مجاز برای هر روش پرداختِ داخلی (کارت/کریپتو/آبان‌گیت‌وی) +
    حداقل مبلغ شارژ کیف پول. کلید تنظیمی که در حال ویرایش است (مثلاً
    'min_amount_card') در state ذخیره می‌شود تا یک هندلر برای همه کافی باشد."""
    waiting_value = State()


class AdminCustomGatewayMinAmount(StatesGroup):
    waiting_value = State()


class AdminProductPaymentMethods(StatesGroup):
    """صفحه‌ی چندانتخابی «روش‌های پرداخت مجاز» برای یک محصول؛ خودِ صفحه از
    طریق callback toggle می‌شود و نیازی به state پیام‌محور ندارد، ولی برای
    یکدستی با بقیه‌ی صفحات ادمین یک state نگه‌دارنده‌ی product_id تعریف شده."""
    viewing = State()


class AdminVolumeReminderSettings(StatesGroup):
    waiting_percent = State()
    waiting_gb_left = State()
    waiting_discount_percent = State()
    waiting_discount_hours = State()


class AdminConnectAlertSettings(StatesGroup):
    """هشدار اتصال / عدم‌اتصال به کانفیگ."""
    waiting_connect_threshold = State()
    waiting_connect_text = State()
    waiting_no_connect_hours = State()
    waiting_no_connect_threshold = State()
    waiting_no_connect_text = State()


class AdminEarlyRenewalDiscount(StatesGroup):
    """تخفیف خودکار تمدید کامل زودهنگام (حساب من ← تمدید کامل سرویس)."""
    waiting_days = State()
    waiting_percent = State()


class AdminRestoreBackup(StatesGroup):
    waiting_file = State()
    waiting_confirm = State()


class AdminRestoreFullBackup(StatesGroup):
    waiting_file = State()
    waiting_confirm = State()


class AdminBackupInterval(StatesGroup):
    waiting_hours = State()


class AdminBackupSecondaryChat(StatesGroup):
    waiting_chat_id = State()


class AdminReportGroup(StatesGroup):
    waiting_chat_id = State()


class AdminBackupSftp(StatesGroup):
    waiting_host = State()
    waiting_port = State()
    waiting_username = State()
    waiting_password = State()
    waiting_key_path = State()
    waiting_remote_dir = State()


class AdminFactoryReset(StatesGroup):
    waiting_confirm_text = State()


class AdminAddPanelServer(StatesGroup):
    waiting_name = State()
    waiting_type = State()
    waiting_url = State()
    waiting_username = State()
    waiting_password = State()
    waiting_template_user = State()
    waiting_inbound_select = State()
    waiting_sub_base_url = State()


class AdminEditProduct(StatesGroup):
    waiting_volume = State()
    waiting_sub_base_url = State()
    waiting_user_base = State()
    waiting_user_extra_price = State()
    waiting_user_max = State()


class AdminBulkPrice(StatesGroup):
    waiting_category = State()
    waiting_panel = State()
    waiting_mode = State()
    waiting_value = State()
    waiting_rounding = State()
    waiting_confirm = State()


class AdminBulkWalletDeduct(StatesGroup):
    waiting_status = State()
    waiting_usertype = State()
    waiting_amount = State()
    waiting_confirm = State()


class AdminBulkWalletCredit(StatesGroup):
    waiting_status = State()
    waiting_usertype = State()
    waiting_amount = State()
    waiting_message = State()
    waiting_confirm = State()


class AdminPanelServerTransfer(StatesGroup):
    waiting_price = State()


class AdminLocationTransferSettings(StatesGroup):
    waiting_user_limit = State()
    waiting_free_quota = State()


class AdminUserFullStats(StatesGroup):
    waiting_identifier = State()


class AdminUserManage(StatesGroup):
    waiting_message_text = State()
    waiting_wallet_amount = State()
    waiting_discount_type_value = State()
    waiting_discount_expiry = State()


class AdminConfigManage(StatesGroup):
    waiting_rename = State()
    waiting_transfer_target = State()


class AdminSetPanelTemplate(StatesGroup):
    waiting_username = State()


class AdminSetPanelSubUrl(StatesGroup):
    waiting_url = State()


class AdminSetPanelSocksProxy(StatesGroup):
    waiting_url = State()


class AdminAddPricingTier(StatesGroup):
    waiting_from_gb = State()
    waiting_to_gb = State()
    waiting_price = State()


class AdminCustomConfigSettings(StatesGroup):
    waiting_min_gb = State()
    waiting_max_gb = State()
    waiting_prefix = State()


class AdminResetTestConfig(StatesGroup):
    waiting_message = State()


class CustomConfigFlow(StatesGroup):
    waiting_product_select = State()
    waiting_username = State()
    waiting_volume = State()
    waiting_duration = State()
    waiting_receipt = State()


class AdminCustomConfigProduct(StatesGroup):
    waiting_name = State()
    waiting_panel_pick = State()
    waiting_volume_min = State()
    waiting_volume_max = State()
    waiting_duration_mode_pick = State()
    waiting_duration_value = State()
    waiting_duration_min = State()
    waiting_duration_max = State()
    waiting_pricing_mode_pick = State()
    waiting_flat_price = State()
    waiting_description = State()


class AdminAddCustomConfigProductTier(StatesGroup):
    waiting_from_gb = State()
    waiting_to_gb = State()
    waiting_price = State()


class ServiceRenameFlow(StatesGroup):
    waiting_suffix = State()


class ServiceTransferFlow(StatesGroup):
    waiting_target_id = State()


class RenewalFlow(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()
    waiting_customgw_phone = State()


class AdminRenewalPricing(StatesGroup):
    waiting_price_per_gb = State()
    waiting_price_per_day = State()


class ResellerFlow(StatesGroup):
    waiting_username = State()
    waiting_volume = State()
    waiting_fixed_product_username = State()


class ResellerRequestFlow(StatesGroup):
    waiting_volume = State()
    waiting_percent = State()
    waiting_text = State()
    waiting_bot_choice = State()
    waiting_web_panel = State()
    waiting_miniapp = State()
    waiting_supply_model = State()
    waiting_supply_product = State()
    waiting_supply_qty = State()
    waiting_receipt = State()
    waiting_bot_token = State()
    waiting_payment_phone = State()
    waiting_owner_id = State()
    waiting_owner_id_confirm = State()


class AdminResellerRequestFlow(StatesGroup):
    waiting_price = State()
    waiting_percent = State()
    waiting_payment_methods = State()
    waiting_reject_reason = State()


class CommissionResellerRequestFlow(StatesGroup):
    """درخواست نمایندگی کمیسیونی توسط خودِ کاربر: بدون حجم، بدون محصول آماده،
    فقط یک درصد کمیسیون پیشنهادی که برای تایید/رد به ادمین ارسال می‌شود."""
    waiting_percent = State()


class AdminCommissionResellerFlow(StatesGroup):
    """اقدامات ادمین روی نمایندگی کمیسیونی: هم تایید/رد درخواست کاربر، هم
    ساخت مستقیم یک نماینده‌ی کمیسیونی جدید بدون درخواست قبلی."""
    waiting_approve_percent = State()
    waiting_reject_reason = State()
    waiting_direct_user_id = State()
    waiting_direct_percent = State()
    waiting_edit_percent = State()


class AdminTempMessage(StatesGroup):
    waiting_target_id = State()
    waiting_text = State()
    waiting_custom_minutes = State()


class AdminBulkGift(StatesGroup):
    waiting_users = State()
    waiting_volume = State()
    waiting_days = State()


class AdminSettingInput(StatesGroup):
    waiting_value = State()
    waiting_prizes = State()
    waiting_report_chat = State()
