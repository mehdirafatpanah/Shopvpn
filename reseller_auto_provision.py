# -*- coding: utf-8 -*-
"""
تحویل خودکار محصولات «اعتبار حجمی» در بات‌های نمایندگی.

وقتی مشتریِ یک بات نمایندگی محصولی با is_auto_provision=1 می‌خرد، به‌جای
برداشتن یک لینک از بانک کانفیگ (که برای این محصولات اصلاً پر نمی‌شود)،
همین لحظه یک کاربر جدید روی همان پنلی که برای «نمایندگی» صاحب این بات در
بات اصلی تنظیم شده ساخته می‌شود و از اعتبار حجمی او کم می‌شود.

این ماژول عمداً کاملاً مستقل از هر Database instance خاصی است چون باید هم
به دیتابیس ایزوله‌ی بات نمایندگی (برای خواندن مالک/محصول) و هم به دیتابیس
بات اصلی (برای اعتبار و پنل) دسترسی داشته باشد؛ هر دو در همان پروسه اجرا
می‌شوند پس این کار فقط یک اتصال SQLite دوم است، نه فراخوانی شبکه‌ای.
"""

import logging
import random
import string

from config import DB_PATH as MAIN_DB_PATH
from database import Database
from panel_providers import get_provider, PanelError, PanelUsernameTakenError
from user_limit import order_user_limit, provider_kwargs

logger = logging.getLogger(__name__)


class ProvisionError(Exception):
    pass


def _random_username(prefix: str = "r") -> str:
    prefix = (prefix or "r").strip() or "r"
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


async def provision_auto_config(
    local_db: Database, product, quantity: int = 1,
    user_id: int = None, order_id: int = None, source: str = "direct_product",
    username_prefix: str = "r", product_id_for_config: int = None,
) -> list:
    """محصول باید is_auto_provision=1 داشته باشد. برای هر واحد یک کاربر واقعی روی پنل
    نمایندگی ساخته می‌شود. برمی‌گرداند: لیستی از
    {"username": ..., "subscription_url": ..., "volume_gb": ..., "duration_days": ...}
    در صورت هر نوع خطا (حتی بعد از ساخت موفق چند واحد) ProvisionError پرتاب می‌شود و
    هیچ اعتباری کم نمی‌شود - یعنی این تابع همه‌یا-هیچ است تا خرید ناقص تحویل داده نشود.

    اگر user_id داده شود، هر واحد در custom_configs بات نمایندگی (local_db) هم
    ثبت می‌شود (source پیش‌فرض 'direct_product'، برای کانفیگ تست 'test') تا هشدار
    اتمام حجم/زمان و «سرویس‌های من» آن را ببینند."""
    # اعتبارسنجی تعداد: بدون این چک، quantity<=0 باعث می‌شد range(quantity) هیچ
    # کانفیگی نسازد ولی total_volume_gb منفی/صفر پایین‌تر به consume_reseller_credit
    # یا consume_reseller_product_credit پاس داده شود؛ چک اتمیک آن‌ها فقط
    # "باقیمانده >= مقدار درخواستی" را رد می‌کند و با یک مقدار منفی این شرط
    # همیشه true است - یعنی به‌جای کسر، عملاً به اعتبار نماینده رایگان اضافه
    # می‌شد. همه‌ی نقاط فراخوانی فعلی خودشان quantity را به حداقل ۱ محدود
    # می‌کنند، ولی خودِ این تابع (به‌عنوان تنها نقطه‌ی مرکزی کسر اعتبار) نباید
    # به رعایت این قانون توسط هر فراخوانی فعلی/آینده متکی باشد.
    if not isinstance(quantity, int) or quantity < 1:
        raise ProvisionError("تعداد درخواستی نامعتبر است.")

    owner_id = local_db.get_owner_telegram_id()
    if not owner_id:
        raise ProvisionError("مالک این بات مشخص نیست؛ با پشتیبانی تماس بگیرید.")

    volume_gb = product["auto_provision_volume_gb"]
    if not volume_gb or volume_gb <= 0:
        raise ProvisionError("حجم این محصول تنظیم نشده است.")
    # نکته (باگ قبلی): `product["duration_days"] or 30` عدد ۰ را هم falsy
    # می‌دید، درحالی‌که duration_days=0 در کل پروژه یعنی «نامحدود/بدون انقضا»
    # (رجوع کنید به add_custom_config و گزینه‌ی «نامحدود» در ساخت محصول) - نه
    # «تنظیم نشده». نتیجه این بود که محصولات auto-provision با مدت «نامحدود»
    # وقتی از بات نمایندگی خریداری می‌شدند، هم روی پنل واقعی با انقضای ۳۰ روزه
    # ساخته می‌شدند و هم در «سرویس‌های من» به‌اشتباه ۳۰ روزه نشان داده می‌شدند.
    # فقط None (یعنی واقعاً تنظیم نشده) باید به ۳۰ پیش‌فرض بیفتد - دقیقاً مثل
    # direct_panel_provision.py که همین فیلد را درست مدیریت می‌کند.
    duration_days = product["duration_days"] if product["duration_days"] is not None else 30
    total_volume_gb = volume_gb * quantity

    main_db = Database(MAIN_DB_PATH)

    if not main_db.is_reseller(owner_id):
        raise ProvisionError("دسترسی اعتبار حجمی برای مالک این بات فعال نیست؛ با پشتیبانی تماس بگیرید.")

    supply = main_db.get_reseller_supply(owner_id)
    is_fixed_product = supply["model"] == "fixed_product"
    if is_fixed_product:
        # مدل «محصول آماده» (بند ۳.۳ اسپک): مصرف واحدی از reseller_product_credit،
        # نه از reseller_credit_gb. حجم/مدت محصول همچنان برای خودِ ساخت کانفیگ روی
        # پنل لازم است، ولی اعتبارسنجی/کسر بر اساس تعداد است نه گیگابایت.
        # در مدل چندمحصولی، محصول انتخاب‌شده از موجودی خودش منبع حقیقت است؛
        # fixed_product_main_id فقط برای سازگاری با نسخه‌های قدیمی نگه داشته شده.
        fixed_product_id = int(product.get("id") or 0)
        if not fixed_product_id:
            fixed_product_id = supply["product_id"]
        if not fixed_product_id:
            raise ProvisionError("محصول موجودیِ این نمایندگی مشخص نیست؛ با پشتیبانی تماس بگیرید.")
        remaining = main_db.get_reseller_product_credit(owner_id, fixed_product_id)
        if remaining < quantity:
            raise ProvisionError(f"موجودی محصول نماینده کافی نیست (نیاز: {quantity:,}، باقیمانده: {remaining:,}).")
    else:
        credit = main_db.get_reseller_credit(owner_id)
        if credit < total_volume_gb:
            raise ProvisionError(f"اعتبار حجمی نماینده کافی نیست (نیاز: {total_volume_gb:,} گیگ، باقیمانده: {credit:,} گیگ).")

    server = main_db.get_reseller_panel(owner_id)
    if not server or not server["is_active"]:
        product_server_id = product["provision_server_id"] if "provision_server_id" in product.keys() else None
        if product_server_id:
            candidate = main_db.get_panel_server(product_server_id)
            if candidate and candidate["is_active"]:
                server = candidate
    if not server or not server["is_active"]:
        raise ProvisionError("برای این محصول هیچ پنل فعالی برای ساخت کانفیگ نمایندگی پیدا نشد.")

    provider = get_provider(server)
    order = local_db.get_order(order_id) if order_id is not None else None
    extra_kwargs = provider_kwargs(provider, order_user_limit(order, product))
    built = []

    async def _rollback_built():
        # این تابع یتیم‌ماندن اکانت‌های واقعیِ روی پنل را حل می‌کند: قبلاً اگر
        # واحد N ام (از چند واحدِ یک خرید) با خطا مواجه می‌شد، واحدهای ۱..N-۱ که
        # قبلاً واقعاً روی پنل ساخته شده بودند هرگز پاک نمی‌شدند - چون کل خرید
        # لغو می‌شد نه از اعتبار نماینده کم می‌شد و نه رکوردی از آن‌ها ثبت
        # می‌شد، درحالی‌که خودِ اکانت روی پنل باقی می‌ماند و ظرفیت واقعی
        # نماینده را بی‌حساب مصرف می‌کرد. الان قبل از پرتاب ProvisionError، هر
        # واحدِ تا این لحظه ساخته‌شده تلاش می‌شود از روی پنل هم حذف شود.
        for item in built:
            try:
                await provider.delete_user(item["username"])
            except Exception:
                pass

    try:
        for _ in range(quantity):
            username = None
            result = None
            for _try in range(5):
                candidate = _random_username(username_prefix)
                try:
                    result = await provider.create_user(candidate, volume_gb, duration_days, **extra_kwargs)
                    username = candidate
                    break
                except PanelUsernameTakenError:
                    continue
            if username is None:
                await _rollback_built()
                raise ProvisionError("ساخت نام کاربری یکتا روی پنل ناموفق بود؛ دوباره تلاش کنید.")
            built.append({
                "username": result.username,
                "subscription_url": result.subscription_url,
                "volume_gb": volume_gb,
                "duration_days": duration_days,
                "user_limit": extra_kwargs.get("user_limit"),
            })
    except ProvisionError:
        raise
    except PanelError as e:
        await _rollback_built()
        raise ProvisionError(f"خطا در ساخت کانفیگ روی پنل: {e}")

    # فقط بعد از موفقیت واقعیِ ساخت همه‌ی واحدها روی پنل، از اعتبار کم می‌شود
    if is_fixed_product:
        if not main_db.consume_reseller_product_credit(owner_id, fixed_product_id, quantity):
            # این حالت خیلی نادر است (رقابت هم‌زمان دو خرید)؛ چون بالا اتمیک چک نشده
            # بود، اینجا با UPDATE...WHERE qty_remaining>=? واقعاً اتمیک تضمین می‌شود.
            # واحدها قبلاً واقعاً روی پنل ساخته شده‌اند، پس باید پاک شوند وگرنه یتیم
            # می‌مانند (قبلاً همین‌جا rollback فراموش شده بود).
            await _rollback_built()
            raise ProvisionError("موجودی محصول هم‌زمان توسط یک خرید دیگر مصرف شد؛ دوباره تلاش کنید.")
    else:
        # قبلاً اینجا adjust_reseller_credit با دلتای منفی صدا زده می‌شد که فقط یک
        # UPDATE بدون قید بود؛ چون چکِ «اعتبار کافی است؟» بالاتر (چند خط قبل) در
        # پایتون انجام شده بود و هیچ قفلی بین آن چک و این کسر نبود، دو خرید هم‌زمانِ
        # مشتریِ همین نماینده می‌توانستند هر دو از یک اعتبار مشترک رد شوند و اعتبار
        # نماینده منفی شود. consume_reseller_credit کسر را در همان یک کوئری اتمیک
        # (UPDATE ... WHERE reseller_credit_gb >= ?) انجام می‌دهد.
        if not main_db.consume_reseller_credit(
            owner_id, total_volume_gb,
            reason=f"خرید خودکار مشتری - محصول «{product['name']}» × {quantity}",
        ):
            await _rollback_built()
            raise ProvisionError("اعتبار حجمی هم‌زمان توسط یک خرید دیگر مصرف شد؛ دوباره تلاش کنید.")

    if user_id is not None:
        # مهم: server["id"] شناسه‌ی ردیف در دیتابیس بات *اصلی* است، درحالی‌که
        # add_custom_config روی local_db (دیتابیس همین بات نمایندگی) نوشته
        # می‌شود و custom_configs.panel_server_id یک FOREIGN KEY به
        # panel_servers *همان* دیتابیس محلی دارد - نه به بات اصلی. قبلاً همین
        # id خام بات اصلی مستقیم پاس داده می‌شد که تقریباً همیشه (بات‌های
        # نمایندگی معمولاً هیچ پنلی از خودشان ندارند) با FOREIGN KEY constraint
        # failed شکست می‌خورد و چون در try/except بی‌صدا بود، خرید ظاهراً موفق
        # می‌شد (اعتبار کم شده، اکانت واقعی روی پنل ساخته شده) ولی هیچ رکوردی
        # در دیتابیس بات نمایندگی ثبت نمی‌شد - یعنی نه در «سرویس‌های من»، نه در
        # یادآور تمدید/اتمام حجم قابل پیگیری بود. get_or_create_mirror_panel_server
        # یک ردیف محلی معادل می‌سازد/به‌روز می‌کند تا FK رعایت شود.
        try:
            local_panel_id = local_db.get_or_create_mirror_panel_server(server)
        except Exception:
            logger.exception(
                "ساخت/به‌روزرسانی آینه‌ی محلی پنل نمایندگی ناموفق بود (owner_id=%s, panel_id=%s)؛ "
                "ثبت سرویس در دیتابیس بات نمایندگی رد می‌شود.", owner_id, server["id"],
            )
            local_panel_id = None

        if local_panel_id is not None:
            for item in built:
                try:
                    local_db.add_custom_config(
                        user_id, local_panel_id, item["username"], item["volume_gb"], item["duration_days"],
                        item["subscription_url"], order_id=order_id, source=source,
                        product_id=product_id_for_config, user_limit=item.get("user_limit"),
                    )
                except Exception:
                    # این دیگر یک شکست ساختاری قابل‌پیش‌بینی (مثل FK قبلی) نیست -
                    # اگر همچنان رخ دهد (مثلاً دیتابیس قفل/خراب) حداقل لاگ می‌شود
                    # تا قابل پیگیری باشد؛ عمداً raise نمی‌شود چون این فقط ثبت
                    # محلی سرویس است، نه خودِ خرید که قبلاً واقعاً و با موفقیت
                    # از اعتبار نماینده کسر و روی پنل ساخته شده.
                    logger.exception(
                        "add_custom_config برای واحد auto-provision ناموفق بود "
                        "(user_id=%s, username=%s, order_id=%s) - این سرویس در «سرویس‌های من» دیده نخواهد شد.",
                        user_id, item.get("username"), order_id,
                    )

    return built


async def provision_test_config(local_db: Database, plan, user_id: int = None) -> dict:
    """کانفیگ تست برای نماینده: حجم/مدت/پیشوند نام از پلن انتخاب‌شده
    (test_config_plans محلی همان بات نمایندگی) خوانده می‌شود؛ پنل همیشه همان
    پنل اعتبار حجمی نماینده است (فیلد panel_server_id خود پلن نادیده گرفته
    می‌شود چون نماینده فقط به یک پنل اعتباری دسترسی دارد). این هم مثل بقیه‌ی
    محصولات auto-provision، مصرف واقعی روی پنل دارد و از اعتبار کم می‌شود."""
    volume_gb = plan["volume_mb"] / 1024.0
    duration_days = plan["duration_hours"] / 24.0
    fake_product = {"name": plan["name"], "auto_provision_volume_gb": volume_gb, "duration_days": duration_days}
    built = await provision_auto_config(
        local_db, fake_product, quantity=1, user_id=user_id, source="test",
        username_prefix=plan["name_prefix"], product_id_for_config=plan["id"],
    )
    return built[0]


async def provision_reseller_fixed_product(main_db: Database, owner_id: int, product_id: int,
                                           quantity: int = 1, username_prefix: str = "r", username: str = None) -> list:
    """ساخت مستقیم یک محصول آماده برای نماینده از بات اصلی.
    موجودی بر اساس تعداد محصول، نه گیگ، مصرف می‌شود."""
    if not isinstance(quantity, int) or quantity < 1:
        raise ProvisionError("تعداد درخواستی نامعتبر است.")
    if not main_db.is_reseller(owner_id):
        raise ProvisionError("این کاربر نماینده فعال نیست.")
    product = main_db.get_product(product_id)
    if not product or not product["is_active"] or not product["is_auto_provision"]:
        raise ProvisionError("محصول انتخاب‌شده برای ساخت خودکار آماده نیست.")
    if main_db.get_reseller_product_credit(owner_id, product_id) < quantity:
        raise ProvisionError("موجودی این محصول کافی نیست.")
    volume_gb = product["auto_provision_volume_gb"]
    if not volume_gb or volume_gb <= 0:
        raise ProvisionError("حجم محصول تنظیم نشده است.")
    duration_days = product["duration_days"] if product["duration_days"] is not None else 30
    # برای محصولات آماده، اول پنل اختصاصی نماینده را استفاده می‌کنیم؛
    # اگر ادمین پنل اختصاصی برای نماینده تعیین نکرده باشد، خودِ پنل
    # تعریف‌شده روی محصول (provision_server_id) باید به‌عنوان fallback
    # استفاده شود. در غیر این صورت داشتن یک محصول auto-provision عملاً
    # برای نماینده غیرقابل استفاده می‌شد و پیام «پنل نمایندگی تنظیم نشده»
    # نمایش داده می‌شد، حتی وقتی محصول خودش پنل معتبر داشت.
    server = main_db.get_reseller_panel(owner_id)
    if not server or not server["is_active"]:
        product_panel_id = product["provision_server_id"] if "provision_server_id" in product.keys() else None
        if product_panel_id:
            candidate = main_db.get_panel_server(product_panel_id)
            if candidate and candidate["is_active"]:
                server = candidate
    if not server or not server["is_active"]:
        raise ProvisionError("پنل فعال برای ساخت این محصول پیدا نشد؛ پنل نمایندگی یا پنل خود محصول را بررسی کنید.")
    provider = get_provider(server)
    built=[]
    try:
        for _ in range(quantity):
            result=None
            for _try in range(8):
                candidate=username if username and _try == 0 else _random_username(username_prefix)
                try:
                    result=await provider.create_user(candidate, volume_gb, duration_days)
                    break
                except PanelUsernameTakenError:
                    continue
            if result is None:
                raise ProvisionError("ساخت نام کاربری یکتا ناموفق بود؛ دوباره تلاش کنید.")
            built.append({"username": result.username, "subscription_url": result.subscription_url,
                          "volume_gb": volume_gb, "duration_days": duration_days, "product_id": product_id,
                          "product_name": product["name"]})
    except Exception as e:
        for item in built:
            try: await provider.delete_user(item["username"])
            except Exception: pass
        if isinstance(e, ProvisionError): raise
        raise ProvisionError(f"خطا در ساخت کانفیگ: {e}")
    if not main_db.consume_reseller_product_credit(owner_id, product_id, quantity):
        for item in built:
            try: await provider.delete_user(item["username"])
            except Exception: pass
        raise ProvisionError("موجودی محصول هم‌زمان توسط خرید دیگری مصرف شد؛ دوباره تلاش کنید.")
    return built
