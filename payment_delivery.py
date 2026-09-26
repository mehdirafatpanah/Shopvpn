from i18n import tr
# -*- coding: utf-8 -*-
"""
هلپر مشترک تحویل سفارش/شارژ پس از تایید پرداخت.

قبلاً هر فایل *_payment.py یک کپی کامل (~120 خط) از finalize_paid_order و
finalize_paid_topup داشت. تفاوت‌ها فقط در نام لاگر بود؛ منطق یکسان است.
این ماژول آن را یک‌بار پیاده می‌کند و فایل‌های پرداخت فقط یک wrapper نازک
با نام قدیمی export می‌کنند تا importهای موجود نشکند.
"""
import logging

from config_delivery import deliver_config_to_user
from panel_providers import get_provider
from reseller_auto_provision import provision_auto_config, ProvisionError
from direct_panel_provision import provision_direct, ProvisionError as DirectProvisionError
from stock_alerts import check_and_notify_low_stock
from renewal_engine import execute_renewal, RenewalError
from notification_i18n import send_telegram

logger = logging.getLogger("payment_delivery")


async def finalize_paid_order(db, bot, order_id: int, notify_admins_fn=None) -> str:
    order = db.get_order(order_id)
    if not order:
        return tr("⚠️ سفارش یافت نشد.")
    if order["status"] != "pending":
        return tr("✅ این سفارش قبلاً بررسی و تحویل داده شده است.")
    if not db.claim_order(order_id):
        return tr("✅ این سفارش قبلاً بررسی و تحویل داده شده است.")

    if order["is_renewal"]:
        try:
            result_text = await execute_renewal(db, order)
        except RenewalError as e:
            db.release_order_claim(order_id)
            return tr(f"⛔️ تمدید ناموفق بود: {e}\nبا پشتیبانی تماس بگیرید.")
        except Exception:
            logger.exception("خطای غیرمنتظره در execute_renewal برای سفارش تمدید #%s", order_id)
            db.release_order_claim(order_id)
            return tr("⛔️ خطای غیرمنتظره‌ای در تمدید رخ داد. سفارش برای بررسی دوباره آزاد شد؛ با پشتیبانی تماس بگیرید.")
        db.approve_renewal_order(order_id)
        renewal_reward_info = db.reward_referrer_on_renewal(order["user_id"], order["base_price"] or 0)
        if renewal_reward_info:
            renewal_reward_amount, renewal_referrer_id = renewal_reward_info
            try:
                await send_telegram(
                    bot, db, renewal_referrer_id,
                    tr(f"🤝 تبریک! یکی از زیرمجموعه‌های شما سرویسش را تمدید کرد.\n"
                    f"💰 {renewal_reward_amount:,} تومان پورسانت به کیف پول شما اضافه شد."),
                )
            except Exception:
                pass
        try:
            await send_telegram(bot, db, order["user_id"], result_text)
        except Exception:
            pass
        if notify_admins_fn:
            try:
                await notify_admins_fn(bot, order_id)
            except Exception:
                pass
        return result_text

    if order["is_custom_config"]:
        server = db.get_panel_server(order["custom_panel_server_id"])
        if not server:
            db.release_order_claim(order_id)
            return tr("⛔️ سرور مربوط به کانفیگ شخصی یافت نشد؛ با پشتیبانی تماس بگیرید.")
        duration_days = db.get_custom_config_settings()["duration_days"]
        try:
            provider = get_provider(server)
            result = await provider.create_user(order["custom_username"], order["custom_volume_gb"], duration_days)
        except Exception as e:
            db.release_order_claim(order_id)
            return tr(f"⛔️ خطا در ساخت کانفیگ روی پنل: {e}\nبا پشتیبانی تماس بگیرید.")
        db.add_custom_config(
            order["user_id"], server["id"], result.username, order["custom_volume_gb"],
            duration_days, result.subscription_url, order_id=order_id,
        )
        db.approve_custom_config_order(order_id)
        await deliver_config_to_user(
            bot, order["user_id"], "کانفیگ شخصی",
            [result.subscription_url], final_price=order["final_price"], order_id=order_id, db=db,
        )
    else:
        product = db.get_product(order["product_id"])
        quantity = order["quantity"] or 1
        if product and product["is_auto_provision"]:
            try:
                if product["provision_server_id"]:
                    prov_results = await provision_direct(db, product, quantity, user_id=order["user_id"], order_id=order_id)
                else:
                    prov_results = await provision_auto_config(db, product, quantity, user_id=order["user_id"], order_id=order_id)
            except (ProvisionError, DirectProvisionError) as e:
                db.release_order_claim(order_id)
                return tr(f"⚠️ پرداخت تایید شد ولی ساخت خودکار کانفیگ ناموفق بود: {e}\nبا پشتیبانی تماس بگیرید.")
            db.approve_order_auto(order_id)
            links = [r["subscription_url"] for r in prov_results]
        else:
            results = db.take_unused_configs(order["product_id"], order["user_id"], quantity)
            if not results:
                db.release_order_claim(order_id)
                return tr("⚠️ پرداخت تایید شد ولی موجودی هم‌زمان تمام شده؛ ادمین به‌زودی دستی رسیدگی می‌کند.")
            db.approve_order(order_id, [r["id"] for r in results])
            links = [r["link"] for r in results]
            await check_and_notify_low_stock(bot.send_message, db, order["product_id"], bot_token=bot.token)
        await deliver_config_to_user(
            bot, order["user_id"], product["name"] if product else "",
            links, final_price=order["final_price"], order_id=order_id, db=db,
        )

    reward_info = db.reward_referrer_if_first_purchase(order["user_id"], order["base_price"])
    if reward_info:
        reward_amount, referrer_id = reward_info
        try:
            await send_telegram(
                bot, db, referrer_id,
                tr(f"🤝 تبریک! یکی از زیرمجموعه‌های شما اولین خرید خود را انجام داد.\n"
                f"💰 {reward_amount:,} تومان به کیف پول شما اضافه شد."),
            )
        except Exception:
            pass
    if notify_admins_fn:
        try:
            await notify_admins_fn(bot, order_id)
        except Exception:
            pass
    return tr("✅ پرداخت تایید شد و کانفیگ تحویل داده شد.")


async def finalize_paid_topup(db, topup_id: int) -> str:
    topup = db.get_topup(topup_id)
    if not topup:
        return tr("⚠️ درخواست شارژ یافت نشد.")
    if not db.approve_topup(topup_id):
        return tr("✅ این درخواست شارژ قبلاً بررسی شده است.")
    return tr(f"✅ پرداخت تایید شد و {topup['amount']:,} تومان به کیف پول کاربر اضافه شد.")
