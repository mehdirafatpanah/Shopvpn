"""Provider نود «Stealth VLESS»: با ایجنت deploy/shopvpn-stealth-agent.py روی سرور صحبت می‌کند.

api_url      = https://<domain>[:port]/<api_path>   (همان که نصاب چاپ می‌کند؛ از پروکسی کلادفلر هم رد می‌شود)
api_password = توکن API نصاب
هیچ قالب/inbound/آدرس Subscription جداگانه‌ای لازم نیست؛ لینک اشتراک را خودِ ایجنت می‌سازد.
"""
from urllib.parse import quote

from ._http import new_session, request_json, http_error
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError


class StealthProvider(BasePanelProvider):
    supports_data_limit_sync = True
    supports_online_status = True

    def _base(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self):
        return new_session(headers={"Authorization": f"Bearer {self.server['api_password']}",
                                    "Accept": "application/json"}, server=self.server)

    async def _call(self, method: str, path: str, action: str, body=None, allow_404=False):
        async with self._session() as session:
            kwargs = {"json": body} if body is not None else {}
            status, data, text = await request_json(session, method, f"{self._base()}{path}", **kwargs)
        if status == 404 and allow_404:
            return None
        if status == 404:
            raise PanelError(f"{action}: کاربر پیدا نشد یا توکن/آدرس API اشتباه است.")
        if status == 409:
            raise PanelUsernameTakenError("نام کاربری روی نود تکراری است")
        if status >= 400:
            raise http_error(action, status, text)
        if not isinstance(data, dict):
            raise PanelError(f"پاسخ نامعتبر از نود در {action}.")
        return data

    @staticmethod
    def _result(username: str, data: dict) -> PanelUserResult:
        return PanelUserResult(username=data.get("username") or username,
                               subscription_url=data["subscription_url"], raw=data)

    @staticmethod
    def _path(username: str, suffix: str = "") -> str:
        return f"/users/{quote(username, safe='')}{suffix}"

    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False,
                           user_limit: int = 0) -> PanelUserResult:
        data = await self._call("POST", "/users", "ساخت کاربر", {
            "username": username, "volume_gb": volume_gb or 0, "duration_days": duration_days or 0,
            "start_on_first_use": bool(start_on_first_use),
        })
        return self._result(username, data)

    async def delete_user(self, username: str) -> bool:
        data = await self._call("DELETE", self._path(username), "حذف کاربر")
        return bool(data.get("deleted"))

    async def get_user_usage(self, username: str) -> dict:
        data = await self._call("GET", self._path(username), "دریافت مصرف")
        return {"used_bytes": int(data.get("used_bytes") or 0),
                "data_limit_bytes": int(data.get("data_limit_bytes") or 0),
                "status": data.get("status") or "active"}

    async def get_user(self, username: str) -> PanelUserResult:
        return self._result(username, await self._call("GET", self._path(username), "دریافت کاربر"))

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False) -> PanelUserResult:
        data = await self._call("PATCH", self._path(username), "تمدید کاربر", {
            "add_volume_gb": add_volume_gb, "add_days": add_days, "reset_usage": reset_usage,
            "preserve_remaining": preserve_remaining, "unlimited_volume": unlimited_volume,
        })
        return self._result(username, data)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        return self._result(username, await self._call("POST", self._path(username, "/revoke"), "ابطال لینک"))

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        await self._call("POST", self._path(username, "/limit"), "اعمال سقف حجم",
                         {"limit_bytes": int(limit_bytes), "reenable": bool(reenable)})

    async def set_enabled(self, username: str, enabled: bool) -> None:
        await self._call("POST", self._path(username, "/enabled"), "تغییر وضعیت کاربر", {"enabled": bool(enabled)})

    async def rename_user(self, username: str, new_username: str) -> str:
        data = await self._call("POST", self._path(username, "/rename"), "تغییر نام", {"new_username": new_username})
        return data.get("subscription_url")

    async def is_client_online(self, username: str) -> bool:
        data = await self._call("GET", self._path(username, "/online"), "وضعیت آنلاین")
        return bool(data.get("online"))

    async def test_connection(self) -> bool:
        try:
            await self._call("GET", "/health", "بررسی اتصال")
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False
