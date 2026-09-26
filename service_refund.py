import asyncio
import logging

from i18n import tr

from panel_providers import get_provider

GB = 1024 ** 3
UNUSED_TOLERANCE_BYTES = 1024 ** 2


async def _read_used_bytes(db, cc):
    server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
    if not server:
        return None
    try:
        usage = await get_provider(server).get_user_usage(cc["username"])
        return int(usage.get("used_bytes") or 0)
    except Exception:
        logging.getLogger("service_refund").exception("دریافت مصرف کاربر «%s» برای محاسبه‌ی ریفاند ناموفق بود.", cc["username"])
        return None


def _empty_quote(kind: str, cc, base: dict, paid: int = 0) -> dict:
    return {
        "eligible": False, "kind": kind, "amount": 0, "paid": paid, "used_gb": 0.0, "product_id": None,
        "volume_gb": int(cc["volume_gb"] or 0), "window_hours": base["window_hours"], "reason": base["reason"],
    }


async def quote_service_refund(db, cc, user_tg_id: int, credit_db=None) -> dict:
    """محاسبه‌ی ریفاند حذف سرویس: تومان به کیف پول (خرید مشتری) یا اعتبار نماینده (کانفیگ ساخته‌ی نماینده)، فقط داخل مهلت."""
    if cc["source"] == "reseller":
        return await _quote_reseller_refund(db, cc, user_tg_id, credit_db or db)
    base = await asyncio.to_thread(db.get_service_refund_base, cc["id"], user_tg_id)
    quote = _empty_quote("wallet", cc, base, base["paid"])
    if not base["eligible"]:
        return quote
    used = await _read_used_bytes(db, cc)
    if used is None:
        quote["reason"] = "usage"
        return quote
    ratio = max(0.0, 1 - used / (base["volume_gb"] * GB))
    quote.update(eligible=True, amount=int(base["paid"] * ratio), used_gb=used / GB, reason="")
    return quote


async def _quote_reseller_refund(db, cc, user_tg_id: int, credit_db) -> dict:
    base = await asyncio.to_thread(db.get_reseller_refund_base, cc["id"], user_tg_id)
    quote = _empty_quote("credit_gb", cc, base)
    if not base["eligible"]:
        return quote
    product_id = base["reseller_product_id"]
    if product_id:
        quote["kind"] = "credit_unit"
        quote["product_id"] = int(product_id)
    else:
        supply = await asyncio.to_thread(credit_db.get_reseller_supply, user_tg_id)
        if supply["model"] != "volume_credit":
            return quote
    used = await _read_used_bytes(db, cc)
    if used is None:
        quote["reason"] = "usage"
        return quote
    if product_id:
        amount = 1 if used <= UNUSED_TOLERANCE_BYTES else 0
    else:
        amount = max(0, int((base["volume_gb"] * GB - used) // GB))
    quote.update(eligible=True, amount=amount, used_gb=used / GB, reason="")
    return quote


def wallet_refund_amount(quote: dict, panel_deleted: bool) -> int:
    return quote["amount"] if quote["eligible"] and quote["kind"] == "wallet" and panel_deleted else 0


async def grant_service_refund_credit(credit_db, user_tg_id: int, quote: dict, panel_deleted: bool, username: str) -> int:
    """بعد از حذف موفق کانفیگ نماینده، اعتبار حجمی یا موجودی محصول را به او برمی‌گرداند؛ مقدار برگشتی را می‌دهد."""
    if not (quote["eligible"] and quote["kind"] != "wallet" and panel_deleted and quote["amount"] > 0):
        return 0
    reason = f"بازگشت اعتبار حذف کانفیگ «{username}»"
    if quote["kind"] == "credit_unit":
        await asyncio.to_thread(credit_db.grant_reseller_product_credit, user_tg_id, quote["product_id"], quote["amount"], reason=reason)
    else:
        await asyncio.to_thread(credit_db.adjust_reseller_credit, user_tg_id, quote["amount"], reason=reason)
    return quote["amount"]


def refund_result_text(quote: dict, refunded: int) -> str:
    if refunded <= 0:
        return ""
    if quote["kind"] == "wallet":
        return tr(f"{refunded:,} تومان به کیف پول شما برگشت.")
    if quote["kind"] == "credit_unit":
        return tr(f"{refunded} عدد به موجودی محصول نمایندگی شما برگشت.")
    return tr(f"{refunded:,} گیگ به اعتبار نمایندگی شما برگشت.")


def refund_quote_text(quote: dict) -> str:
    if quote["eligible"]:
        usage = f"(مصرف تا این لحظه: {quote['used_gb']:.2f} از {quote['volume_gb']} گیگ)"
        if quote["kind"] == "wallet":
            return tr(
                f"💰 مبلغ پرداختی: {quote['paid']:,} تومان\n"
                f"♻️ مبلغ برگشتی به کیف پول: {quote['amount']:,} تومان\n{usage}"
            )
        if quote["kind"] == "credit_unit":
            if quote["amount"] > 0:
                return tr(f"♻️ موجودی برگشتی به محصول نمایندگی شما: {quote['amount']} عدد\n{usage}")
            return tr(f"ℹ️ این کانفیگ مصرف داشته و موجودی محصول برنمی‌گردد.\n{usage}")
        return tr(f"♻️ اعتبار برگشتی به نمایندگی شما: {quote['amount']:,} گیگ\n{usage}")
    if quote["reason"] == "window":
        return tr(f"ℹ️ مهلت بازگشت وجه/اعتبار ({quote['window_hours']} ساعت پس از ساخت) گذشته است؛ با حذف، چیزی برگردانده نمی‌شود.")
    if quote["reason"] == "usage":
        return tr("ℹ️ در حال حاضر محاسبه‌ی مقدار برگشتی ممکن نیست (خطا در دریافت مصرف)؛ با حذف، چیزی برگردانده نمی‌شود.")
    return ""
