# -*- coding: utf-8 -*-
"""
افزونه‌های تحویل سفارش (مستقل از aiogram؛ هم بات و هم پنل وب/مینی‌اپ از آن استفاده می‌کنند):

۱) متن و استیکر اختصاصی هر محصول  (products.delivery_text / products.delivery_sticker)
۲) فایل‌های WireGuard / AmneziaWG / OpenVPN سرویس تحویل‌شده
   - فایل حساب‌های نودهای SSH/Linux Agent  (dedicated_sub.wg_files_for_config / ovpn_files_for_config)
   - فایل‌های پنل‌هایی مثل W-UI           (provider.get_config_files)
   تا قبل از این فقط داخل صفحه‌ی ساب اختصاصی قابل دانلود بودند؛ حالا همان فایل‌ها هنگام
   تحویل داخل خودِ بات هم به‌صورت document برای کاربر ارسال می‌شوند.

هیچ‌کدام از توابع این ماژول استثنا بالا نمی‌دهند: تحویل اصلی سفارش نباید به‌خاطر این افزونه‌ها خراب شود.
"""
import asyncio
import logging
import re

import dedicated_sub

logger = logging.getLogger(__name__)

VPN_FILES_SETTING_KEY = "deliver_vpn_files_enabled"
# نوع‌هایی از فایل W-UI که فایل کانفیگ محسوب می‌شوند (بقیه مثل other ارسال نمی‌شوند)
_WUI_FILE_KINDS = {"wireguard": "WireGuard", "amneziawg": "AmneziaWG", "openvpn": "OpenVPN"}
MAX_FILES_PER_SERVICE = 20
MAX_FILE_BYTES = 200 * 1024  # فایل کانفیگ چند کیلوبایت است؛ سقف برای جلوگیری از ارسال محتوای غیرعادی


def vpn_files_enabled(db) -> bool:
    if db is None:
        return False
    try:
        return db.get_setting(VPN_FILES_SETTING_KEY, "1") != "0"
    except Exception:
        return True


def _row_get(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def get_product_delivery_extras(db, order_id) -> tuple:
    """(متن اختصاصی محصول, file_id استیکر محصول) برای سفارش؛ مقدار خالی یعنی تنظیم نشده."""
    if db is None or not order_id:
        return "", ""
    try:
        order = db.get_order(int(order_id))
        if not order:
            return "", ""
        product_id = _row_get(order, "product_id")
        product = db.get_product(int(product_id)) if product_id else None
        if not product:
            return "", ""
        text = str(_row_get(product, "delivery_text", "") or "").strip()
        sticker = str(_row_get(product, "delivery_sticker", "") or "").strip()
        return text, sticker
    except Exception:
        logger.debug("خواندن متن/استیکر تحویل محصول ناموفق بود.", exc_info=True)
        return "", ""


def render_product_text(text: str, product_name: str = "", order_id=None) -> str:
    """جایگزینی متغیرهای ساده‌ی {product_name} و {order_id}؛ هر آکولاد ناشناخته دست‌نخورده می‌ماند."""
    out = str(text or "")
    out = out.replace("{product_name}", str(product_name or ""))
    out = out.replace("{order_id}", str(order_id or ""))
    return out


def _safe_filename(name: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "")).strip("._") or fallback
    return name[:80]


async def collect_vpn_files(db, link: str) -> list:
    """فایل‌های WireGuard/OpenVPN سرویسی که این لینک اشتراک به آن تعلق دارد.
    خروجی: [{"filename", "content" (bytes), "label"}]؛ در هر خطا لیست خالی یا ناقص (هرگز استثنا)."""
    if db is None or not link or not vpn_files_enabled(db):
        return []
    try:
        upstream = await asyncio.to_thread(dedicated_sub.upstream_for_link, db, link)
        cc = await asyncio.to_thread(db.ds_find_config_by_sub_url, upstream)
    except Exception:
        logger.debug("پیدا کردن سرویس برای فایل‌های VPN ناموفق بود.", exc_info=True)
        return []
    if cc is None:
        return []

    found = []
    try:
        found += await asyncio.to_thread(dedicated_sub.wg_files_for_config, db, cc["id"], cc)
        found += await asyncio.to_thread(dedicated_sub.ovpn_files_for_config, db, cc["id"], cc)
    except Exception:
        logger.warning("جمع‌آوری فایل‌های WireGuard/OpenVPN نودها ناموفق بود.", exc_info=True)

    out = []
    for item in found:
        out.append({"filename": item["filename"], "content": str(item["profile"]).encode("utf-8"),
                    "label": item.get("remark") or item["filename"]})

    # پنل‌هایی مثل W-UI: فایل‌ها از خودِ پنل گرفته می‌شود
    try:
        server_id = _row_get(cc, "panel_server_id")
        server = await asyncio.to_thread(db.get_panel_server, int(server_id)) if server_id else None
        if server and str(_row_get(server, "panel_type", "") or "").lower() == "wui":
            from panel_providers import get_provider
            provider = get_provider(server)
            files = await provider.get_config_files(cc["username"])
            for f in files:
                label = _WUI_FILE_KINDS.get(f.get("kind"))
                if not label:
                    continue
                out.append({"filename": _safe_filename(f.get("filename"), "config"),
                            "content": str(f.get("text") or "").encode("utf-8"),
                            "label": f"{str(f.get('filename') or '').rsplit('.', 1)[0]} ({label})"})
    except Exception:
        logger.warning("دریافت فایل‌های کانفیگ از پنل W-UI ناموفق بود.", exc_info=True)

    # حذف فایل خالی/عجیب، یکتاسازی نام فایل، سقف تعداد
    final, seen = [], {}
    for f in out:
        if not f["content"].strip() or len(f["content"]) > MAX_FILE_BYTES:
            continue
        name = f["filename"]
        if name in seen:
            seen[name] += 1
            stem, dot, ext = name.rpartition(".")
            name = f"{stem}-{seen[name]}.{ext}" if dot else f"{name}-{seen[name]}"
        else:
            seen[name] = 1
        final.append(dict(f, filename=name))
        if len(final) >= MAX_FILES_PER_SERVICE:
            break
    return final
