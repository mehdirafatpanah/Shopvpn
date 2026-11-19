"""Provider پنل Doctor DNS: Bot API با کلید ادمین (dd_...)؛ پلن به‌جای گروه/inbound انتخاب می‌شود."""
import hashlib
from datetime import datetime
from urllib.parse import quote

from ._http import new_session, request_json, http_error, load_json, server_value
from .base import (
    BasePanelProvider, PanelUserResult, PanelError, PanelPermissionError, PanelUsernameTakenError,
)

SYNTHETIC_ID_BASE = 10 ** 15
MAX_DEVICES = 10  # سقف تعداد دستگاه (آی‌پی هم‌زمان) هر حساب روی پنل Doctor DNS

STATUS_MAP = {
    "active": "active",
    "pending": "disabled",
    "suspended": "disabled",
    "over_quota": "limited",
    "expired": "expired",
}


def telegram_id_for(username: str) -> int:
    """شناسه‌ی عددی ثابت برای هر نام کاربری؛ بالاتر از محدوده‌ی آیدی واقعی تلگرام."""
    digest = hashlib.sha256(str(username).encode("utf-8")).digest()
    return SYNTHETIC_ID_BASE + int.from_bytes(digest[:6], "big")


class DoctorDNSProvider(BasePanelProvider):
    # «تعداد کاربر» همان تعداد دستگاه (آی‌پی هم‌زمان، max_ips) حساب روی پنل است
    supports_user_limit = True

    def _base(self) -> str:
        url = self.server["api_url"].rstrip("/")
        return url if url.endswith("/api/v1") else f"{url}/api/v1"

    def _session(self):
        return new_session(
            headers={"Authorization": f"Bearer {self.server['api_password']}", "Accept": "application/json"},
            server=self.server,
        )

    async def _call(self, method: str, path: str, action: str, body=None) -> dict:
        async with self._session() as session:
            kwargs = {"json": body} if body is not None else {}
            status, data, text = await request_json(session, method, f"{self._base()}{path}", **kwargs)
        payload = data if isinstance(data, dict) else {}
        if status == 401:
            raise PanelError("کلید API پنل Doctor DNS معتبر نیست.")
        if status == 403 and payload.get("error") == "admin_only":
            raise PanelPermissionError("کلید API باید با تیک «دسترسی ادمین» ساخته شود.")
        if status == 403 and payload.get("error") == "ip_not_allowed":
            raise PanelPermissionError("آی‌پی سرور بات برای این کلید مجاز نشده است.")
        if status == 404 and payload.get("error") == "not_found" and path.endswith("/devices"):
            raise PanelError("مسیر /admin/users/{id}/devices روی پنل Doctor DNS نیست (احتمالاً Doctor DNS دوباره نصب/آپدیت شده و پچ پاک شده)؛ در پنل ادمین اتصال خودکار Doctor DNS را دوباره اجرا کنید.")
        if status >= 400 or not payload or payload.get("ok") is False:
            if payload.get("message"):
                raise PanelError(f"{action}: {payload['message']}")
            raise http_error(action, status, text)
        return payload

    def _plan_id(self, fallback=None) -> int:
        raw = load_json(server_value(self.server, "group_ids"))
        if isinstance(raw, list) and len(raw) == 1:
            raw = raw[0]
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
        if fallback:
            return int(fallback)
        raise PanelError("پلن این محصول روی پنل Doctor DNS انتخاب نشده است.")

    async def _apply_devices(self, panel_user_id, user_limit, current=None) -> None:
        """تعداد کل دستگاه‌های حساب را روی پنل تعیین می‌کند (۱ تا ۱۰)؛ اگر همان مقدار فعلی باشد کاری نمی‌کند."""
        total = int(user_limit or 0)
        if total < 1:
            return
        if total > MAX_DEVICES:
            raise PanelError(f"پنل Doctor DNS حداکثر {MAX_DEVICES} دستگاه را پشتیبانی می‌کند.")
        if current is not None and int(current or 0) == total:
            return
        await self._call("POST", f"/admin/users/{panel_user_id}/devices", "تنظیم تعداد کاربر", {"devices": total})

    async def list_product_targets(self):
        data = await self._call("GET", "/plans", "دریافت فهرست پلن‌ها")
        choices = []
        for plan in data.get("plans") or []:
            if not isinstance(plan, dict) or plan.get("id") is None:
                continue
            days = plan.get("days")
            label = f"{plan.get('name') or plan['id']} · {days} روز" if days else str(plan.get("name") or plan["id"])
            choices.append({"value": str(plan["id"]), "label": label})
        if not choices:
            raise PanelError("هیچ پلن در حال فروشی روی پنل Doctor DNS پیدا نشد.")
        return {"field": "group_ids", "kind": "scalar", "choices": choices}

    async def _account(self, username: str) -> dict:
        data = await self._call("GET", f"/users/{telegram_id_for(username)}", "دریافت کاربر")
        return data["user"]

    async def _result(self, username: str, user: dict) -> PanelUserResult:
        base = (user.get("panel_url") or "").rstrip("/")
        if not base:
            raise PanelError("آدرس پنل مشتری هنوز آماده نیست؛ سرور ایران همگام نشده است.")
        return PanelUserResult(username=username, subscription_url=f"{base}/?u={quote(username, safe='')}", raw=user)

    async def login_link(self, username: str) -> str:
        data = await self._call("POST", f"/users/{telegram_id_for(username)}/login-link", "ساخت لینک ورود")
        if not data.get("url"):
            raise PanelError("لینک ورود از پنل دریافت نشد.")
        return data["url"]

    async def get_dns_bundle(self, username: str) -> dict:
        """آدرس‌های DNS/DoH/DoT، آی‌پی‌های ثبت‌شده، فایل‌های وایرگارد و مصرف برای صفحه‌ی ساب اختصاصی."""
        tg = telegram_id_for(username)
        user = await self._account(username)
        servers = user.get("servers") or [{"ip": ip, "n": n} for n, ip in enumerate(user.get("dns") or [], 1)]
        try:
            configs = (await self._call("GET", f"/users/{tg}/wg/all", "دریافت کانفیگ‌های وایرگارد")).get("configs") or []
        except PanelError:
            configs = []
        files = []
        for item in configs:
            if not item.get("config"):
                continue
            label = " · ".join(x for x in (str(item.get("server") or ""), str(item.get("note") or "")) if x)
            files.append({"remark": label or "WireGuard", "filename": item.get("file") or "doctor-dns.conf",
                          "profile": item["config"]})
        expire = 0
        if user.get("expires_at"):
            try:
                expire = int(datetime.fromisoformat(user["expires_at"]).timestamp())
            except ValueError:
                expire = 0
        return {
            "servers": servers,
            "ips": user.get("ips") or [],
            "max_ips": int(user.get("max_ips") or 0),
            "status": user.get("status") or "",
            "wg": files,
            "info": {"upload": 0, "download": int(user.get("used_bytes") or 0),
                     "total": int(user.get("quota_bytes") or 0), "expire": expire},
        }

    async def create_user(self, username: str, volume_gb: int, duration_days: int,
                           start_on_first_use: bool = False, user_limit: int = 0) -> PanelUserResult:
        plan_id = self._plan_id()
        data = await self._call("POST", "/users", "ساخت کاربر",
                                {"telegram_id": telegram_id_for(username), "name": str(username)[:60]})
        user = data["user"]
        if not data.get("created") and user.get("status") != "pending":
            raise PanelUsernameTakenError("این کاربر روی پنل Doctor DNS از قبل وجود دارد")
        applied = await self._call("POST", f"/admin/users/{user['id']}/plan", "اعمال پلن", {"plan_id": plan_id})
        if user_limit:
            await self._apply_devices(user["id"], user_limit, (applied.get("user") or {}).get("max_ips"))
        try:
            await self._call("POST", f"/users/{telegram_id_for(username)}/wg", "ساخت کانفیگ وایرگارد")
        except PanelError:
            pass
        return await self.get_user(username)

    async def delete_user(self, username: str) -> bool:
        await self.set_enabled(username, False)
        return True

    async def get_user_usage(self, username: str) -> dict:
        user = await self._account(username)
        return {
            "used_bytes": int(user.get("used_bytes") or 0),
            "data_limit_bytes": int(user.get("quota_bytes") or 0),
            "status": STATUS_MAP.get(user.get("status"), user.get("status") or ""),
        }

    async def get_user(self, username: str) -> PanelUserResult:
        return await self._result(username, await self._account(username))

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False, user_limit: int = None) -> PanelUserResult:
        renew = bool(add_days or reset_usage)
        if not renew and user_limit is None:
            raise PanelError("پنل Doctor DNS حجم یا زمان جداگانه اضافه نمی‌کند؛ فقط تمدید با خرید دوباره‌ی پلن پشتیبانی می‌شود.")
        user = await self._account(username)
        current = user.get("max_ips")
        if renew:
            if user.get("status") == "suspended":
                await self._call("POST", f"/admin/users/{user['id']}/status", "فعال‌سازی کاربر", {"status": "active"})
            plan_id = self._plan_id(fallback=(user.get("plan") or {}).get("id"))
            applied = await self._call("POST", f"/admin/users/{user['id']}/plan", "تمدید پلن", {"plan_id": plan_id})
            # تمدید تعداد دستگاه را به مقدار پلن (+ اضافه‌های همان پلن) برمی‌گرداند؛ مقدار فعلی از پاسخ پنل خوانده می‌شود
            current = (applied.get("user") or {}).get("max_ips")
        if user_limit is not None:
            await self._apply_devices(user["id"], user_limit, current)
        return await self.get_user(username)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        data = await self._call("POST", f"/users/{telegram_id_for(username)}/doh-reset", "ابطال آدرس DoH")
        return await self._result(username, data.get("user") or await self._account(username))

    async def set_enabled(self, username: str, enabled: bool) -> None:
        user = await self._account(username)
        await self._call("POST", f"/admin/users/{user['id']}/status", "تغییر وضعیت کاربر",
                         {"status": "active" if enabled else "suspended"})

    async def test_connection(self) -> bool:
        try:
            await self._call("GET", "/", "بررسی اتصال")
            await self._call("GET", "/admin/stats", "بررسی دسترسی ادمین")
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False
