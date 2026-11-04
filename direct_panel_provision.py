# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
تحویل خودکار محصولاتی که مستقیماً به یک پنل VPN مشخص (products.provision_server_id)
وصل هستند - بدون دخالت اعتبار حجمی نماینده.

برخلاف reseller_auto_provision.provision_auto_config (که مخصوص بات‌های نمایندگی
و اعتبار حجمی آن‌هاست)، این ماژول برای فروش عادی محصولات در بات اصلی/بانک‌کاربران
است: ادمین موقع ساخت محصول یک پنل مشخص می‌کند، و همان لحظه‌ی خرید یک کاربر واقعی
روی همان پنل ساخته می‌شود - از دید خریدار دقیقاً مثل خرید از بانک کانفیگ.
"""

import logging
import random
import string
import urllib.parse
from datetime import datetime, timedelta, timezone

from panel_providers import get_provider, PanelError, PanelUsernameTakenError
from user_limit import order_user_limit, provider_kwargs
from panel_capabilities import product_capabilities, USER_LIMIT
from ssh_uri import build_ssh_uri
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

logger = logging.getLogger(__name__)


class ProvisionError(Exception):
    pass


MULTI_TARGET_NEEDS_DSUB = ("محصول با چند پنل/نود یا ترکیب پنل و نود فقط با ساب اختصاصی فعال کار می‌کند؛ "
                           "ساب اختصاصی را فعال کنید.")


def _random_username(prefix: str = "") -> str:
    suffix = "d" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}-{suffix}" if prefix else suffix


def planned_usernames(base: str, quantity: int) -> list:
    return [base] if quantity == 1 else [f"{base}_{i}" for i in range(1, quantity + 1)]


def _order_config_name(order) -> str:
    """Read config_name from either sqlite3.Row or a mapping without assuming .get()."""
    if order is None:
        return ""
    try:
        value = order["config_name"]
    except (KeyError, IndexError, TypeError):
        value = ""
    return str(value or "")


async def provision_direct(db, product, quantity: int = 1, user_id: int = None, order_id: int = None) -> list:
    """محصول باید provision_server_id معتبر داشته باشد. برای هر واحد یک کاربر واقعی
    روی همان پنل ساخته می‌شود. برمی‌گرداند: لیستی از
    {"username": ..., "subscription_url": ..., "volume_gb": ..., "duration_days": ...}
    در صورت هر نوع خطا (حتی بعد از ساخت موفق چند واحد) ProvisionError پرتاب می‌شود
    و این تابع همه‌یا-هیچ است: واحدهایی که تا آن لحظه واقعاً روی پنل ساخته شده‌اند
    قبل از پرتاب خطا تلاش می‌شود پاک شوند تا اکانت یتیم روی پنل باقی نماند.

    اگر user_id داده شود، هر واحد ساخته‌شده در custom_configs (source='direct_product')
    هم ثبت می‌شود تا هشدار اتمام حجم/زمان و «سرویس‌های من» آن را ببینند."""
    ssh_node_id = None
    try:
        ssh_node_id = product["provision_ssh_node_id"]
    except (KeyError, IndexError):
        pass
    targets = db.product_target_counts(product)
    if len(targets["panels"]) + len(targets["ssh"]) > 1:
        import dedicated_sub
        if not dedicated_sub.is_enabled(db):
            raise ProvisionError(MULTI_TARGET_NEEDS_DSUB)
        if (len(targets["panels"]) == 1 and len(targets["ssh"]) == 1
                and len(_product_ssh_protocols(product)) == 1):
            return await _provision_combined(db, product, quantity=quantity, user_id=user_id, order_id=order_id)
        logger.info("provision_direct: product=%s -> multi path (panels=%s ssh=%s protocols=%s)",
                    product["id"], targets["panels"], targets["ssh"], _product_ssh_protocols(product))
        return await _provision_multi(db, product, targets, quantity=quantity, user_id=user_id, order_id=order_id)
    if ssh_node_id:
        return await provision_ssh_direct(db, product, quantity=quantity, user_id=user_id, order_id=order_id)
    return await _provision_vpn(db, product, quantity=quantity, user_id=user_id, order_id=order_id)


async def _provision_vpn(db, product, quantity: int = 1, user_id: int = None, order_id: int = None,
                         shared_pool: bool = False, server_id: int = None, register: bool = True, target_config_override=...) -> list:
    """ساخت کاربر روی پنل VPN. با shared_pool=True حجم روی خود پنل نامحدود ساخته می‌شود
    (سقف حجم را استخر مشترک VPN+SSH اعمال می‌کند) ولی حجم محصول در custom_configs ثبت می‌شود."""
    if not isinstance(quantity, int) or quantity < 1:
        raise ProvisionError("تعداد درخواستی نامعتبر است.")

    server_id = server_id or product["provision_server_id"]
    if not server_id:
        raise ProvisionError("این محصول به هیچ پنلی وصل نشده است.")

    server = db.get_panel_server(server_id)
    if not server or not server["is_active"]:
        raise ProvisionError("پنل متصل به این محصول یافت نشد یا غیرفعال است؛ با پشتیبانی تماس بگیرید.")
    # مقصد گروه/اینباند در سطح محصول ذخیره می‌شود؛ NULL برای محصولات قدیمی
    # عمداً یعنی ادامه‌ی استفاده از قالب قدیمی سرور (سازگاری کامل پس از آپدیت).
    from product_targets import apply_product_target
    effective_product = product
    if target_config_override is not ...:
        effective_product = dict(product)
        effective_product["provision_target_config"] = target_config_override
    server = apply_product_target(server, effective_product)

    if not db.panel_has_capacity(server_id, quantity):
        info = db.get_panel_capacity_info(server_id) or {}
        limit = info.get("max_services") or 0
        used = info.get("active_services", 0)
        raise ProvisionError(f"ظرفیت پنل تکمیل است ({used}/{limit} سرویس فعال).")

    volume_gb = product["auto_provision_volume_gb"]
    if volume_gb is None or volume_gb < 0:
        raise ProvisionError("حجم این محصول تنظیم نشده است.")
    # 0 یعنی نامحدود (هم برای حجم و هم برای مدت) - نباید با مقدار پیش‌فرض جایگزین شود
    duration_days = product["duration_days"] if product["duration_days"] is not None else 30

    configured_user_limit = any(int(product[key] or 0) > 0 for key in ("base_users", "extra_user_price", "max_users"))
    if configured_user_limit and not product_capabilities(db, product)[USER_LIMIT]:
        raise ProvisionError("این محصول محدودیت کاربر دارد اما یکی از پنل‌های مقصد دیگر از آن پشتیبانی نمی‌کند؛ تنظیمات محصول را اصلاح کنید.")

    provider = get_provider(server)
    prefix = db.get_custom_config_prefix()
    planned = []
    order = db.get_order(order_id) if order_id is not None else None
    if order and order["config_name"]:
        planned = planned_usernames(order["config_name"], quantity)
    extra_kwargs = provider_kwargs(provider, order_user_limit(order, product))
    built = []

    async def _rollback_built():
        # رفع باگ: برخلاف ادعای docstring («واحدهای ساخته‌شده گم نمی‌شوند»)، قبلاً
        # اگر واحد Nام از چند واحدِ یک خرید با خطا مواجه می‌شد، واحدهای ۱..N-۱ که
        # واقعاً روی پنل ساخته شده بودند نه پاک می‌شدند و نه در ProvisionError پرتاب‌شده
        # به‌جایی اشاره می‌شدند - یعنی اکانت‌های واقعی روی پنل مشتری برای همیشه یتیم‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
        # می‌ماندند (نه در custom_configs ثبت می‌شدند، نه قابل پیگیری بودند) درحالی‌که
        # خودِ خرید با خطا مواجه شده بود. دقیقاً مثل reseller_auto_provision._rollback_built،
        # الان قبل از پرتاب ProvisionError هر واحدِ تا این لحظه ساخته‌شده حذف می‌شود.
        for item in built:
            try:
                await provider.delete_user(item["username"])
            except Exception:
                pass

    try:
        for index in range(quantity):
            # بررسی دوم درست قبل از ساخت، برای کاهش احتمال عبور از سقف در خریدهای هم‌زمان.‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            if not db.panel_has_capacity(server_id, 1):
                await _rollback_built()
                raise ProvisionError("ظرفیت پنل در همین لحظه تکمیل شد؛ مبلغ سفارش به شما برگردانده می‌شود.")
            username = None
            result = None
            wanted = planned[index] if planned else None
            for attempt in range(5):
                if wanted and attempt == 0:
                    candidate = wanted
                elif wanted:
                    candidate = wanted + "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
                else:
                    candidate = _random_username(prefix)
                if db.is_custom_username_taken(candidate):
                    continue
                try:
                    result = await provider.create_user(candidate, 0 if shared_pool else volume_gb, duration_days, **extra_kwargs)
                    username = candidate
                    break
                except PanelUsernameTakenError:
                    continue
            if username is None:
                await _rollback_built()
                raise ProvisionError("ساخت نام کاربری یکتا روی پنل ناموفق بود؛ دوباره تلاش کنید.")
            built.append({
                "username": result.username,
                "panel_server_id": int(server_id),
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

    if user_id is not None and register:
        for item in built:
            try:
                item["custom_config_id"] = db.add_custom_config(
                    user_id, server["id"], item["username"], item["volume_gb"], item["duration_days"],
                    item["subscription_url"], order_id=order_id, source="direct_product",
                    user_limit=item.get("user_limit"),
                    panel_target_config=(effective_product["provision_target_config"] if "provision_target_config" in effective_product.keys() else None),
                )
            except Exception:
                # مسیر خودِ ساخت روی پنل قبلاً موفق شده (والا اصلاً به این بلوک
                # نمی‌رسیدیم)؛ اینجا فقط ثبت محلی سرویس است، پس raise نمی‌کنیم
                # تا مشتری از خریدی که واقعاً تحویل گرفته محروم نشود - ولی لاگ
                # می‌کنیم تا این‌جور شکست‌ها دیگر بی‌صدا گم نشوند.
                logger.exception(
                    "add_custom_config برای واحد direct-provision ناموفق بود "
                    "(user_id=%s, username=%s, order_id=%s) - این سرویس در «سرویس‌های من» دیده نخواهد شد.",
                    user_id, item.get("username"), order_id,
                )

    return built
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 


async def _provision_combined(db, product, quantity: int = 1, user_id: int = None, order_id: int = None) -> list:
    """محصول ترکیبی VPN+SSH با سهمیه مشترک: هر دو سرویس عضو یک quota pool هستند
    (حجم و انقضا مشترک؛ ‌quota_reconciler مصرف هر دو را جمع و در صورت اتمام هر دو را قطع می‌کند).
    همه‌یا‌هیچ: اگر هر مرحله‌ای شکست بخورد، آنچه تا آن لحظه ساخته شده پاک می‌شود."""
    if user_id is None:
        raise ProvisionError("شناسه کاربر برای ساخت محصول ترکیبی VPN+SSH الزامی است.")
    import dedicated_sub
    if not dedicated_sub.is_enabled(db):
        raise ProvisionError(MULTI_TARGET_NEEDS_DSUB)
    # ابتدا SSH (شکست‌پذیرتر: نیاز به شمارنده معتبر)، بعد VPN.
    ssh_items = await provision_ssh_direct(db, product, quantity=quantity, user_id=user_id, order_id=order_id,
                                           allow_openvpn=True)
    pool_id = ssh_items[0]["quota_pool_id"]

    async def _rollback_ssh():
        try:
            from ssh_providers import get_ssh_provider
            from quota_reconciler import _env_secret_resolver
            node = next((n for n in db.list_ssh_nodes() if int(n["id"]) == int(product["provision_ssh_node_id"])), None)
            provider = get_ssh_provider(node, secret_resolver=_env_secret_resolver)
            for item in ssh_items:
                try:
                    await provider.delete_account(item["account_id"])
                except Exception:
                    logger.exception("combined rollback: SSH delete failed for %s", item["account_id"])
        except Exception:
            logger.exception("combined rollback: SSH provider unavailable")
        db.delete_quota_pool(pool_id)

    try:
        vpn_items = await _provision_vpn(db, product, quantity=quantity, user_id=user_id,
                                         order_id=order_id, shared_pool=True)
    except Exception:
        await _rollback_ssh()
        raise

    try:
        for item in vpn_items:
            cc_id = item.get("custom_config_id")
            if not cc_id:
                raise ProvisionError("ثبت سرویس VPN برای اتصال به سهمیه مشترک ناموفق بود.")
            db.attach_custom_config_to_quota_pool(pool_id, cc_id)
        for vpn_item, ssh_item in zip(vpn_items, ssh_items):
            db.link_ssh_account_to_config(ssh_item["account_id"], vpn_item["custom_config_id"])
    except Exception as exc:
        provider = get_provider(db.get_panel_server(product["provision_server_id"]))
        for item in vpn_items:
            try:
                await provider.delete_user(item["username"])
            except Exception:
                logger.exception("combined rollback: VPN delete failed for %s", item["username"])
            if item.get("custom_config_id"):
                with db._get_conn() as conn:
                    conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?",
                                 (f"custom_config:{int(item['custom_config_id'])}",))
                    conn.execute("DELETE FROM custom_configs WHERE id=?", (int(item["custom_config_id"]),))
        await _rollback_ssh()
        if isinstance(exc, ProvisionError):
            raise
        raise ProvisionError(f"اتصال سرویس‌ها به سهمیه مشترک ناموفق بود: {exc}") from exc

    for item in vpn_items:
        item["quota_pool_id"] = int(pool_id)
    return vpn_items


async def _provision_multi(db, product, targets: dict, quantity: int = 1, user_id: int = None,
                           order_id: int = None) -> list:
    """محصول چندمقصدی: هر تعداد پنل VPN و نود SSH با حجم و زمان مشترک (یک استخر سهمیه برای هر واحد).
    پنل اول سرویس اصلی (custom_config) است و بقیه‌ی پنل‌ها با config_panel_links به آن وصل می‌شوند؛
    لینک ساب اختصاصی خروجی همه را یکجا می‌دهد. همه‌یا‌هیچ: با خطا هرچه ساخته شده پاک می‌شود."""
    if user_id is None or not isinstance(quantity, int) or quantity < 1:
        raise ProvisionError("شناسه کاربر یا تعداد برای ساخت محصول چندمقصدی نامعتبر است.")
    panel_ids, node_ids = list(targets["panels"]), list(targets["ssh"])
    configured_user_limit = any(int(product[key] or 0) > 0 for key in ("base_users", "extra_user_price", "max_users"))
    if configured_user_limit and not product_capabilities(db, product)[USER_LIMIT]:
        raise ProvisionError("محدودیت کاربر این محصول با یکی از پنل‌های مقصد سازگار نیست؛ تنظیمات محصول را اصلاح کنید.")
    if not panel_ids and any(p in FILE_PROTOCOLS for p in _product_ssh_protocols(product)):
        raise ProvisionError("تحویل فایل OpenVPN/WireGuard حداقل یک پنل VPN در محصول لازم دارد.")
    for sid in panel_ids:
        server = db.get_panel_server(sid)
        if not server or not server["is_active"]:
            raise ProvisionError(f"پنل #{sid} متصل به این محصول یافت نشد یا غیرفعال است؛ با پشتیبانی تماس بگیرید.")
    volume_gb = float(product["auto_provision_volume_gb"] or 0)
    duration_days = int(product["duration_days"] if product["duration_days"] is not None else 30)
    if volume_gb < 0 or duration_days < 0:
        raise ProvisionError("حجم یا مدت محصول نامعتبر است.")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=duration_days)).isoformat() if duration_days else None

    finished = []
    output = []
    try:
        for _ in range(quantity):
            unit_items, unit_rollback = await _provision_multi_unit(
                db, product, panel_ids, node_ids, user_id, order_id, volume_gb, expires_at)
            finished.append(unit_rollback)
            output.extend(unit_items)
    except Exception:
        for rollback in reversed(finished):
            await rollback()
        raise
    return output


async def _provision_multi_unit(db, product, panel_ids, node_ids, user_id, order_id, volume_gb, expires_at):
    pool_id = db.create_quota_pool(int(user_id), volume_gb, expires_at,
        label=f"{product['name']}" + (f" · order #{order_id}" if order_id else ""))
    ssh_items, vpn_items = [], []
    primary_cc_id = None

    async def rollback():
        for item in ssh_items:
            try:
                from ssh_providers import get_ssh_provider
                from quota_reconciler import _env_secret_resolver
                node = next((n for n in db.list_ssh_nodes() if int(n["id"]) == int(item["node_id"])), None)
                await get_ssh_provider(node, secret_resolver=_env_secret_resolver).delete_account(item["account_id"])
            except Exception:
                logger.exception("multi rollback: SSH delete failed for %s", item.get("account_id"))
        for item in vpn_items:
            try:
                await get_provider(db.get_panel_server(item["panel_server_id"])).delete_user(item["username"])
            except Exception:
                logger.exception("multi rollback: VPN delete failed for %s", item.get("username"))
        if primary_cc_id:
            db.delete_config_panel_links(primary_cc_id)
            with db._get_conn() as conn:
                conn.execute("DELETE FROM quota_pool_members WHERE service_kind='vpn' AND service_id=?",
                             (f"custom_config:{int(primary_cc_id)}",))
                conn.execute("DELETE FROM custom_configs WHERE id=?", (int(primary_cc_id),))
        db.delete_quota_pool(pool_id)

    try:
        extra_target_data = db.get_product_extra_targets(int(product["id"]))
        panel_target_configs = extra_target_data.get("panel_target_configs") or {}
        from ssh_service import node_protocols
        wanted_protocols = _product_ssh_protocols(product)
        nodes_by_id = {int(n["id"]): n for n in db.list_ssh_nodes(active_only=True)}
        for node_id in node_ids:
            node = nodes_by_id.get(int(node_id))
            supported = node_protocols(node) if node else []
            # هر نود فقط پروتکل‌هایی را می‌سازد که خودش دارد؛ نودِ بدون هیچ‌کدام خطا می‌دهد.
            node_picks = [p for p in wanted_protocols if p in supported]
            if not node_picks:
                raise ProvisionError(f"هیچ‌یک از پروتکل‌های انتخابی محصول روی نود #{node_id} نصب نیست.")
            logger.info("multi provision: product=%s order=%s node=%s wanted=%s supported=%s -> creating %s",
                        product["id"], order_id, node_id, wanted_protocols, supported, node_picks)
            for proto in node_picks:
                ssh_items.extend(await provision_ssh_direct(
                    db, product, quantity=1, user_id=user_id, order_id=order_id,
                    allow_openvpn=bool(panel_ids), node_id=node_id, pool_id=pool_id, protocol=proto))
        for index, server_id in enumerate(panel_ids):
            # هر پنل مقصد مستقل محصول را می‌گیرد؛ پنل اصلی از provision_target_config
            # و پنل‌های اضافه از product_extra_targets.target_config استفاده می‌کنند.
            per_panel_config = None
            if index > 0:
                per_panel_config = panel_target_configs.get(int(server_id))
            built = await _provision_vpn(
                db, product, quantity=1, user_id=user_id, order_id=order_id,
                shared_pool=True, server_id=server_id, register=(index == 0),
                target_config_override=(per_panel_config if index > 0 else ...),
            )
            vpn_items.extend(built)
            if index == 0:
                primary_cc_id = built[0].get("custom_config_id")
                if not primary_cc_id:
                    raise ProvisionError("ثبت سرویس اصلی برای اتصال به سهمیه مشترک ناموفق بود.")
                db.attach_custom_config_to_quota_pool(pool_id, primary_cc_id)
                for ssh_item in ssh_items:
                    db.link_ssh_account_to_config(ssh_item["account_id"], primary_cc_id)
            else:
                link_id = db.add_config_panel_link(
                    primary_cc_id, server_id, built[0]["username"], built[0]["subscription_url"],
                    target_config=panel_target_configs.get(int(server_id)),
                )
                db.attach_quota_service(pool_id, "vpn", f"panel_link:{link_id}", node_id=server_id)
    except Exception as exc:
        await rollback()
        if isinstance(exc, ProvisionError):
            raise
        raise ProvisionError(f"ساخت محصول چندمقصدی ناموفق بود: {exc}") from exc

    if not panel_ids:
        return ssh_items, rollback
    primary = dict(vpn_items[0])
    primary["quota_pool_id"] = int(pool_id)
    return [primary], rollback


FILE_PROTOCOLS = ("openvpn", "wireguard")


def _product_ssh_protocols(product) -> list:
    """لیست پروتکل‌های انتخاب‌شده‌ی محصول (ذخیره‌ی قدیمی تک‌مقداری هم پشتیبانی می‌شود)."""
    try:
        raw = str(product["provision_ssh_protocol"] or "ssh")
    except (KeyError, IndexError, TypeError):
        raw = "ssh"
    picked = {x.strip().lower() for x in raw.split(",")}
    return [p for p in ("ssh", "openvpn", "wireguard") if p in picked] or ["ssh"]


def _product_ssh_protocol(product) -> str:
    """پروتکل اصلی (اولین)؛ برای مسیرهای تک‌پروتکلی (SSH تنها / ترکیبی VPN+SSH)."""
    return _product_ssh_protocols(product)[0]


async def provision_ssh_direct(db, product, quantity: int = 1, user_id: int = None, order_id: int = None,
                               allow_openvpn: bool = False, node_id: int = None, pool_id: int = None,
                               protocol: str = None) -> list:
    """Provision a paid SSH product on a Linux Agent and create one shared quota pool.

    Commercial delivery fails closed unless the Agent reports a valid per-account
    counter. This prevents selling a quota-limited SSH product that cannot enforce
    its advertised volume.
    """
    if not isinstance(quantity, int) or quantity < 1 or user_id is None:
        raise ProvisionError("تعداد یا شناسه کاربر برای ساخت محصول SSH نامعتبر است.")
    node_id = node_id or product["provision_ssh_node_id"]
    node = next((n for n in db.list_ssh_nodes(active_only=True) if int(n["id"]) == int(node_id)), None)
    if not node or node.get("node_type") != "linux":
        raise ProvisionError("نود Linux Agent فعال پیدا نشد؛ پنل SSH هنوز آداپتور عملیاتی ندارد.")
    from ssh_service import node_protocols
    protocol = protocol or _product_ssh_protocol(product)
    if protocol in FILE_PROTOCOLS and not allow_openvpn:
        label = "WireGuard" if protocol == "wireguard" else "OpenVPN"
        raise ProvisionError(f"{label} فقط در محصول ترکیبی VPN + SSH پشتیبانی می‌شود (فایل آن داخل لینک ساب اختصاصی تحویل می‌شود).")
    if protocol not in node_protocols(node):
        raise ProvisionError(f"پروتکل {protocol} روی این نود نصب نشده است.")
    volume_gb = float(product["auto_provision_volume_gb"] or 0)
    duration_days = int(product["duration_days"] if product["duration_days"] is not None else 30)
    if volume_gb < 0 or duration_days < 0:
        raise ProvisionError("حجم یا مدت محصول SSH نامعتبر است.")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=duration_days)).isoformat() if duration_days else None

    from ssh_providers import get_ssh_provider, SSHProviderError
    from quota_reconciler import _env_secret_resolver
    from ssh_credentials import encrypt_credential
    try:
        encrypt_credential("preflight-check")
    except RuntimeError as exc:
        raise ProvisionError(str(exc))
    own_pool = False
    try:
        provider = get_ssh_provider(node, secret_resolver=_env_secret_resolver)
        if pool_id is None:
            pool_id = db.create_quota_pool(int(user_id), volume_gb, expires_at,
                label=f"{product['name']} SSH" + (f" · order #{order_id}" if order_id else ""))
            own_pool = True
    except Exception as exc:
        raise ProvisionError(f"آماده‌سازی محصول SSH ناموفق بود: {exc}") from exc
    built = []
    order = db.get_order(order_id) if order_id is not None else None
    # Keep the SSH login recognizable and tied to the name shown for the order.
    # SSH usernames are restricted to portable ASCII account-name characters.
    requested_base = _order_config_name(order).strip().lower()
    requested_base = "".join(ch for ch in requested_base if ch in string.ascii_lowercase + string.digits + "_-").strip("_-")
    requested_base = requested_base[:12]
    try:
        for item_index in range(quantity):
            result = None
            for attempt in range(5):
                suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=7))
                unit_base = requested_base if quantity == 1 else f"{requested_base[:9]}{item_index + 1}"
                username = f"{unit_base}_{suffix}" if unit_base else "sv" + suffix
                try:
                    # The shared pool is the sole volume authority. A duplicate
                    # per-account cap would prevent a renewed/increased pool from
                    # restoring accounts and would break shared usage semantics.
                    result = await provider.create_account(username, 0, expires_at, protocol=protocol)
                    break
                except SSHProviderError as exc:
                    if "already exists" in str(exc).lower() and attempt < 4:
                        continue
                    raise
            if result is None:
                raise ProvisionError("ساخت نام کاربری SSH یکتا ناموفق بود.")
            try:
                usage = await provider.get_usage(result.account_id)
                reliable_sources = {"nftables_port_counters", "external-counter", "ssh-traffic-accountant", "openvpn_accounting",
                                    "wireguard_accounting"}
                if volume_gb > 0 and (not usage.get("accounting_ready") or usage.get("source") not in reliable_sources):
                    raise ProvisionError("فروش محصول حجمی SSH متوقف شد: شمارنده‌ی دوطرفه‌ی معتبر آماده نیست. nftables را فعال کنید و مطمئن شوید منبع برابر nftables_port_counters یا یک external-counter معتبر است.")
                result.metadata["accounting_ready"] = bool(usage.get("accounting_ready"))
                secret = result.metadata.get("profile", "") if protocol in FILE_PROTOCOLS else result.metadata.get("password", "")
                credential_enc = encrypt_credential(secret)
                db.register_ssh_account(int(node_id), int(user_id), result.account_id, result.username,
                    result.host, result.port, int(pool_id), expires_at, credential_enc, protocol=protocol)
                if usage.get("accounting_ready"):
                    db.record_usage_snapshot("ssh", result.account_id, int(usage["used_bytes"]),
                        uploaded_bytes=usage.get("uploaded_bytes", 0), downloaded_bytes=usage.get("downloaded_bytes", 0),
                        source=str(usage.get("source") or "ssh-agent"), reported_at=usage.get("reported_at"))
                built.append(result)
            except Exception:
                try:
                    await provider.delete_account(result.account_id)
                except Exception:
                    logger.exception("SSH provisioning rollback failed for %s", result.account_id)
                raise
    except Exception as exc:
        for item in built:
            try:
                await provider.delete_account(item.account_id)
            except Exception:
                logger.exception("SSH provisioning rollback failed for %s", item.account_id)
        if own_pool:
            db.delete_quota_pool(pool_id)
        if isinstance(exc, ProvisionError):
            raise
        raise ProvisionError(f"ساخت محصول SSH ناموفق بود: {exc}") from exc

    import ssh_hosts
    output = []
    for item in built:
        password = str(item.metadata.get("password") or "")
        # آدرس/پورت نمایشی از «هاست»های نود می‌آید؛ بدون هاست همان آدرس واقعی نود است.
        eps = ssh_hosts.endpoints(node, protocol, str(item.host or ""), int(item.port))
        primary = eps[0]
        label = str(node.get("name") or "SSH")
        uri = "" if protocol in FILE_PROTOCOLS else build_ssh_uri(item.username, password, primary["address"], primary["port"],
                                                                    label + (f" {primary['remark']}" if primary["remark"] else ""))
        extra = [] if protocol in FILE_PROTOCOLS else [
            build_ssh_uri(item.username, password, ep["address"], ep["port"], label + (f" {ep['remark']}" if ep["remark"] else ""))
            for ep in eps[1:]]
        output.append({"username": item.username, "host": primary["address"], "port": int(primary["port"]),
            "password": password, "account_id": item.account_id, "quota_pool_id": int(pool_id), "node_id": int(node_id),
            "subscription_url": uri, "extra_uris": extra, "volume_gb": volume_gb, "duration_days": duration_days,
            "protocol": protocol, "accounting_ready": bool(item.metadata.get("accounting_ready"))})
    return output
