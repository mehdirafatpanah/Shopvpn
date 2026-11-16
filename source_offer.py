# -*- coding: utf-8 -*-
"""Source-code offer required by the ShopVPN license (LICENSE, section 6).

If you modify ShopVPN and let people use your version through the bot, the mini app, the web
panel or the web store, you must offer them the source code of the version you run.
Set SHOPVPN_SOURCE_URL (in .env) to the public repository of YOUR version.
Unmodified installs can leave it empty: it points to the official repository.
"""
import html
import os

OFFICIAL_REPO = "https://github.com/mehdirafatpanah/Shopvpn"
LICENSE_NAME = "ShopVPN Source-Available Network Copyleft License 1.0"


def source_url() -> str:
    url = (os.getenv("SHOPVPN_SOURCE_URL") or "").strip()
    if not url.lower().startswith(("https://", "http://")):
        url = OFFICIAL_REPO
    return url


def license_url() -> str:
    base = source_url().rstrip("/")
    return f"{base}/blob/main/LICENSE" if "github.com" in base else base


def build_text(lang: str = "fa") -> str:
    """HTML text for the /source command (fa or en; other languages get English)."""
    src, lic = html.escape(source_url(), quote=True), html.escape(license_url(), quote=True)
    if lang == "fa":
        return (
            "📦 <b>سورس‌کد این ربات</b>\n\n"
            f"سورس‌کد کامل همین نسخه (ربات، مینی‌اپ و پنل وب) رایگان در دسترس است:\n{src}\n\n"
            f"📄 لایسنس: <a href=\"{lic}\">{LICENSE_NAME}</a>\n"
            "فروش کانفیگ و اشتراک VPN مجاز است؛ فروش یا اجاره‌ی خود نرم‌افزار بدون لایسنس تجاری مجاز نیست.\n\n"
            "ساخته‌شده با ShopVPN — Mehdi Rafatpanah (@celenor)"
        )
    return (
        "📦 <b>Source code</b>\n\n"
        f"The full source code of this version (bot, mini app and web panel) is available for free:\n{src}\n\n"
        f"📄 License: <a href=\"{lic}\">{LICENSE_NAME}</a>\n"
        "Selling VPN configurations and subscriptions is allowed; selling or renting the software itself "
        "needs a commercial license.\n\n"
        "Built with ShopVPN — Mehdi Rafatpanah (@celenor)"
    )
