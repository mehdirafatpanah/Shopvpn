# -*- coding: utf-8 -*-
"""
دریافت اطلاعات زنده‌ی اشتراک (حجم مصرف‌شده/باقی‌مانده و تاریخ انقضا) مستقیماً از روی
لینک ساب کاربر — دقیقاً مثل کاری که اپ‌هایی نظیر v2Box یا v2rayNG انجام می‌دهند.

این ماژول به هیچ پنل خاصی (Marzban/X-UI/Marzneshin/Hiddify/...) وابسته نیست، چون
همه‌ی آن‌ها از یک قرارداد نانوشته‌ی مشترک پیروی می‌کنند: در پاسخ به یک درخواست GET
روی لینک ساب، هدرهای زیر را برمی‌گردانند:

  subscription-userinfo: upload=...; download=...; total=...; expire=...
  profile-title: <base64 یا متن ساده>
  profile-update-interval: <ساعت>
"""

import base64
import binascii
from datetime import datetime, timezone

import aiohttp

from jalali import to_jalali_str

_TIMEOUT = aiohttp.ClientTimeout(total=10)

_CONFIG_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "ssr://", "hysteria://", "hysteria2://", "hy2://", "tuic://")


def _b64_decode(value: str) -> str:
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.b64decode(padded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return value


async def fetch_individual_links(sub_url: str) -> list:
    """
    محتوای خودِ لینک اشتراک (subscription_url) را می‌گیرد و لیست کانفیگ‌های
    تکی داخلش (vless/vmess/trojan/ss/...) را برمی‌گرداند. مستقل از نوع پنل
    (Marzban/X-UI/Marzneshin/PasarGuard/Hiddify) کار می‌کند چون همه از یک
    فرمت مشترک (متن base64 شامل خطوط کانفیگ) پیروی می‌کنند.
    خروجی خالی یعنی یا چیزی پیدا نشد یا خطایی رخ داد؛ فراخوان باید silent
    fallback کند و فقط لینک اشتراک را نشان دهد.
    """
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(sub_url, headers={"User-Agent": "v2rayNG/1.8.29"}) as resp:
                if resp.status != 200:
                    return []
                raw = await resp.text()
    except Exception:
        return []

    decoded = _b64_decode(raw.strip())
    lines = [ln.strip() for ln in decoded.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.startswith(_CONFIG_SCHEMES)]


async def fetch_sub_info(link: str) -> dict:
    """
    خروجی:
      {"ok": True, "upload": int, "download": int, "total": int,
       "expire": int|None, "title": str|None} در صورت موفقیت
      {"ok": False, "error": "..."} در صورت شکست
    """
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(link, headers={"User-Agent": "v2rayNG/1.8.29"}) as resp:
                headers = resp.headers
                userinfo = headers.get("subscription-userinfo")
                if not userinfo:
                    return {"ok": False, "error": "no_userinfo_header"}

                data = dict(
                    p.strip().split("=", 1) for p in userinfo.split(";") if "=" in p
                )
                result = {
                    "ok": True,
                    "upload": int(data.get("upload", 0)),
                    "download": int(data.get("download", 0)),
                    "total": int(data.get("total", 0)),
                    "expire": int(data["expire"]) if data.get("expire") else None,
                    "title": None,
                }

                title = headers.get("profile-title")
                if title:
                    result["title"] = _b64_decode(title)

                return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def format_sub_info_fa(info: dict) -> str:
    """قالب‌بندی خروجی fetch_sub_info به یک متن فارسی کوتاه برای نمایش در بات."""
    if not info.get("ok"):
        return "⚠️ دریافت اطلاعات مصرف از سرور امکان‌پذیر نبود."

    used = info["upload"] + info["download"]
    total = info["total"]

    def gb(n: int) -> str:
        return f"{n / (1024 ** 3):.2f}"

    lines = []
    if total > 0:
        remaining = max(0, total - used)
        percent = min(100, round(used / total * 100)) if total else 0
        lines.append(f"📊 مصرف: {gb(used)} از {gb(total)} گیگابایت ({percent}٪)")
        lines.append(f"📦 باقی‌مانده: {gb(remaining)} گیگابایت")
    else:
        lines.append(f"📊 مصرف: {gb(used)} گیگابایت (نامحدود)")

    if info["expire"]:
        exp_dt = datetime.fromtimestamp(info["expire"], tz=timezone.utc)
        days_left = (exp_dt - datetime.now(timezone.utc)).days
        lines.append(f"📅 انقضا: {to_jalali_str(exp_dt)} ({max(0, days_left)} روز مانده)")
    else:
        lines.append("📅 انقضا: نامحدود")

    return "\n".join(lines)
