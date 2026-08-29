# -*- coding: utf-8 -*-
"""
موتور عمومی درگاه پرداخت پویا (Generic Payment Gateway Engine).

هدف: ادمین هر فروشگاه بتواند بدون نوشتن حتی یک خط کد پایتون، هر درگاه
پرداختی (داخلی/خارجی، کریپتو، ریالی، هر چیزی که یک HTTP API دارد) را از
داخل پنل ادمین تعریف کند: آدرس API، هدرها، بدنه‌ی درخواست (با پلیس‌هولدر)،
و این‌که از پاسخ JSON کدام فیلدها باید خوانده شوند (با یک مسیر ساده شبیه
JSONPath، بدون نیاز به کتابخانه‌ی جانبی).

ساختار gateway_config (یک dict که از ستون JSON جدول custom_gateways خوانده
می‌شود؛ نمونه‌ی کامل در مستندات پنل ادمین آمده):

{
  "credential_fields": [{"name": "api_key", "label": "کلید API", "secret": true}, ...],
  "credentials": {"api_key": "xxxxx", ...},

  "create_request": {
      "method": "POST", "url": "https://example.com/api/invoice",
      "headers": {"Authorization": "Bearer {api_key}"},
      "body_type": "json",                        # json | form
      "body": {"amount": "{amount}", "callback": "{callback_url}", "order_id": "{order_id}"}
  },
  "create_response": {"invoice_url_path": "data.link", "txn_id_path": "data.id"},

  "verify_enabled": true,
  "verify_request": {
      "method": "POST", "url": "https://example.com/api/verify",
      "headers": {"Authorization": "Bearer {api_key}"}, "body_type": "json",
      "body": {"authority": "{query.Authority}", "amount": "{amount}"}
  },
  "verify_response": {"status_path": "data.code", "success_values": ["100", "101"]},

  "webhook_enabled": true,
  "webhook_auth": {"mode": "none|header_secret|query_secret|hmac_sha256",
                    "header_name": "X-Signature", "query_param": "secret",
                    "secret_field": "webhook_secret", "hmac_algo": "sha256"},
  "webhook_mapping": {"txn_id_path": "txn_id", "status_path": "status",
                       "success_values": ["completed", "paid"], "amount_path": "amount"}
}

متغیرهایی که همیشه در context templateها در دسترس‌اند: amount, amount_toman,
order_id, callback_url, currency, description, tenant_id، به‌علاوه‌ی هر چیزی
که در credentials تعریف شده، و در حالت verify/return هم query.* (پارامترهای
کوئری‌استرینگی که درگاه هنگام برگرداندن کاربر اضافه می‌کند، مثلاً Authority).
"""

import hashlib
import hmac
import json
import logging

import aiohttp

logger = logging.getLogger("payment_engine")


class PaymentEngineError(Exception):
    """خطای قابل‌نمایش به ادمین/کاربر در فلوی یک درگاه سفارشی."""
    pass


class _AttrDict(dict):
    """دیکشنری‌ای که هم با dict[key] و هم با dict.key قابل خواندن است (برای
    پشتیبانی از پلیس‌هولدرهای تودرتو مثل {query.Authority} در templateها).
    کلید نبود = رشته‌ی خالی (به‌جای خطا)، تا یک template ناقص کل درخواست را
    خراب نکند."""

    def __getattr__(self, item):
        try:
            val = self[item]
        except KeyError:
            return ""
        if isinstance(val, dict) and not isinstance(val, _AttrDict):
            val = _AttrDict(val)
            self[item] = val
        return val

    def __missing__(self, key):
        return ""


def _to_attr(obj):
    if isinstance(obj, dict):
        return _AttrDict({k: _to_attr(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_attr(v) for v in obj]
    return obj


def render(value, context: "_AttrDict"):
    """رندر بازگشتی یک str/dict/list با جایگزینی پلیس‌هولدرهای {..} از روی context."""
    if isinstance(value, str):
        try:
            return value.format_map(context)
        except Exception:
            logger.warning("رندر template ناموفق بود، مقدار خام برگردانده شد: %r", value)
            return value
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context) for v in value]
    return value


def extract_path(data, path: str):
    """یک مسیر ساده مثل 'data.result[0].id' یا 'status' را از یک dict/list
    استخراج می‌کند. مسیر نامعتبر یا پیدا‌نشدن => None (نه خطا)."""
    if not path:
        return None
    parts = []
    buf = ""
    i = 0
    n = len(path)
    while i < n:
        ch = path[i]
        if ch == ".":
            if buf:
                parts.append(buf)
                buf = ""
        elif ch == "[":
            if buf:
                parts.append(buf)
                buf = ""
            j = path.find("]", i)
            if j == -1:
                break
            parts.append(("idx", path[i + 1:j]))
            i = j
        else:
            buf += ch
        i += 1
    if buf:
        parts.append(buf)

    cur = data
    for p in parts:
        if cur is None:
            return None
        try:
            if isinstance(p, tuple):
                cur = cur[int(p[1])]
            elif isinstance(cur, dict):
                cur = cur.get(p)
            else:
                cur = cur[p]
        except Exception:
            return None
    return cur


async def _http_request(method: str, url: str, headers: dict, body_type: str, body: dict):
    method = (method or "POST").upper()
    try:
        async with aiohttp.ClientSession() as session:
            kw = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=25)}
            if method == "GET":
                kw["params"] = body
            elif body_type == "form":
                kw["data"] = body
            else:
                kw["json"] = body
            async with session.request(method, url, **kw) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                except Exception:
                    data = {"_raw_text": text}
                if resp.status >= 400:
                    raise PaymentEngineError(
                        f"درگاه با خطا پاسخ داد (HTTP {resp.status}): {text[:300]}"
                    )
                return data
    except aiohttp.ClientError as e:
        raise PaymentEngineError(f"اتصال به درگاه ناموفق بود: {e}")


class GenericGateway:
    """یک نمونه از موتور، ساخته‌شده روی config یک درگاه سفارشی مشخص
    (خروجی db.get_custom_gateway → json.loads(row['config_json']))."""

    def __init__(self, config: dict):
        self.config = config or {}

    def _context(self, **kwargs) -> _AttrDict:
        ctx = {}
        ctx.update(self.config.get("credentials") or {})
        ctx.update(kwargs)
        return _to_attr(ctx)

    # -- ساخت فاکتور ---------------------------------------------------

    async def create_invoice(self, **kwargs) -> dict:
        req = self.config.get("create_request") or {}
        url_tpl = req.get("url")
        if not url_tpl:
            raise PaymentEngineError("آدرس API «ساخت فاکتور» در تنظیمات این درگاه خالی است.")
        ctx = self._context(**kwargs)
        url = render(url_tpl, ctx)
        headers = render(req.get("headers") or {}, ctx)
        body = render(req.get("body") or {}, ctx)
        body_type = req.get("body_type") or "json"

        data = await _http_request(req.get("method", "POST"), url, headers, body_type, body)

        resp_map = self.config.get("create_response") or {}
        invoice_url = extract_path(data, resp_map.get("invoice_url_path") or "")
        txn_id = extract_path(data, resp_map.get("txn_id_path") or "")
        if not txn_id:
            raise PaymentEngineError(
                "درگاه پاسخ داد ولی شناسه‌ی تراکنش (txn_id) در پاسخ پیدا نشد؛ "
                "«مسیر txn_id» را در تنظیمات این درگاه بررسی کن."
            )
        return {
            "invoice_url": str(invoice_url) if invoice_url is not None else None,
            "txn_id": str(txn_id),
            "raw": data,
        }

    # -- استعلام دستی وضعیت (برای درگاه‌هایی که به‌جای/علاوه‌بر webhook با
    # verify API کار می‌کنند، مثلاً بعد از برگشت کاربر از صفحه‌ی پرداخت) ---

    async def verify(self, **kwargs) -> dict:
        if not self.config.get("verify_enabled"):
            return {"checked": False, "success": None}
        req = self.config.get("verify_request") or {}
        url_tpl = req.get("url")
        if not url_tpl:
            raise PaymentEngineError("آدرس API «استعلام پرداخت» در تنظیمات این درگاه خالی است.")
        ctx = self._context(**kwargs)
        url = render(url_tpl, ctx)
        headers = render(req.get("headers") or {}, ctx)
        body = render(req.get("body") or {}, ctx)
        body_type = req.get("body_type") or "json"

        data = await _http_request(req.get("method", "POST"), url, headers, body_type, body)

        resp_map = self.config.get("verify_response") or {}
        status_val = extract_path(data, resp_map.get("status_path") or "")
        success_values = [str(v) for v in (resp_map.get("success_values") or [])]
        success = (str(status_val) in success_values) if success_values else bool(status_val)
        return {"checked": True, "success": success, "raw": data, "status_value": status_val}

    # -- Webhook ---------------------------------------------------------

    def check_webhook_auth(self, headers: dict, query: dict, raw_body: bytes) -> bool:
        auth_cfg = self.config.get("webhook_auth") or {}
        mode = auth_cfg.get("mode") or "none"
        if mode == "none":
            return True
        creds = self.config.get("credentials") or {}
        secret = creds.get(auth_cfg.get("secret_field") or "") or ""
        headers_lower = {(k or "").lower(): v for k, v in (headers or {}).items()}

        if mode == "header_secret":
            hname = (auth_cfg.get("header_name") or "").lower()
            got = headers_lower.get(hname, "")
            return bool(secret) and got == secret

        if mode == "query_secret":
            qname = auth_cfg.get("query_param") or ""
            got = (query or {}).get(qname, "")
            return bool(secret) and got == secret

        if mode == "hmac_sha256" or mode == "hmac":
            hname = (auth_cfg.get("header_name") or "").lower()
            got_sig = headers_lower.get(hname, "")
            if not secret or not got_sig:
                return False
            algo = (auth_cfg.get("hmac_algo") or "sha256").lower()
            digestmod = getattr(hashlib, algo, hashlib.sha256)
            expected = hmac.new(secret.encode("utf-8"), raw_body or b"", digestmod).hexdigest()
            return hmac.compare_digest(expected, (got_sig or "").strip().lower())

        logger.warning("حالت webhook_auth ناشناخته: %s", mode)
        return False

    def parse_webhook(self, body: dict, query: dict) -> dict:
        mapping = self.config.get("webhook_mapping") or {}
        body = body or {}
        query = query or {}

        def get(path):
            if not path:
                return None
            if path.startswith("query."):
                return extract_path(query, path[len("query."):])
            if path.startswith("body."):
                return extract_path(body, path[len("body."):])
            return extract_path(body, path)

        txn_id = get(mapping.get("txn_id_path"))
        status_val = get(mapping.get("status_path"))
        amount_val = get(mapping.get("amount_path")) if mapping.get("amount_path") else None
        success_values = [str(v) for v in (mapping.get("success_values") or [])]
        success = (str(status_val) in success_values) if success_values else None

        return {
            "txn_id": str(txn_id) if txn_id is not None else None,
            "status_value": status_val,
            "success": success,
            "amount": amount_val,
        }
