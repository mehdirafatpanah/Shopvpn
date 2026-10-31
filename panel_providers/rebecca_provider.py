#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""Provider پنل Rebecca (فورک Marzban): احراز هویت با Bearer token در فیلد رمز و سرویس (service_id) از روی کاربر نمونه."""
import time

from ._http import new_session, request_json, load_json, new_limit_bytes
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from .marzban_provider import _expire_to_epoch


class RebeccaProvider(BasePanelProvider):

    def _base(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self):
        return new_session(headers={
            "Authorization": f"Bearer {self.server['api_password']}",
            "Accept": "application/json",
        }, server=self.server)

    async def _call(self, session, method: str, path: str, action: str, not_found_ok: bool = False, **kwargs):
        status, data, text = await request_json(session, method, f"{self._base()}/api/{path}", **kwargs)
        detail = data.get("detail") if isinstance(data, dict) else None
        if status == 401:
            raise PanelError("توکن پنل نادرست یا منقضی است.")
        if status == 404 and not_found_ok:
            return status, data
        if status == 404:
            raise PanelError(f"کاربری روی پنل پیدا نشد ({action}).")
        if status >= 400:
            raise PanelError(f"خطا در {action} (کد {status}): {detail or (text or '')[:300]}")
        return status, data

    def _result(self, data: dict, username: str) -> PanelUserResult:
        sub_url = (data.get("subscription_url") or "") if isinstance(data, dict) else ""
        if sub_url.startswith("/"):
            sub_url = self._base() + sub_url
        return PanelUserResult(username=(data or {}).get("username", username), subscription_url=sub_url, raw=data)

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        async with self._session() as session:
            _, data = await self._call(session, "GET", f"user/{sample_username}", "دریافت کاربر نمونه")
        service_id = data.get("service_id") if isinstance(data, dict) else None
        if service_id is None:
            raise PanelError("کاربر نمونه service_id ندارد؛ از یک کاربر دیگر امتحان کن.")
        return {"group_ids": [service_id], "proxy_settings": {}}

    def _service_id(self):
        ids = load_json(self.server["group_ids"])
        if isinstance(ids, list):
            ids = ids[0] if ids else None
        if ids in (None, ""):
            raise PanelError("سرویس این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن.")
        return int(ids)

    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False) -> PanelUserResult:
        start_on_first_use = bool(self.server["start_on_first_use"]) if "start_on_first_use" in self.server.keys() else bool(start_on_first_use)
        payload = {
            "username": username,
            "service_id": self._service_id(),
            "data_limit": int(volume_gb * (1024 ** 3)),
            "expire": int(time.time() + duration_days * 86400) if duration_days and not start_on_first_use else 0,
            "note": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
            "data_limit_reset_strategy": "no_reset",
            "status": "on_hold" if start_on_first_use and duration_days else "active",
        }
        if start_on_first_use and duration_days:
            payload["on_hold_expire_duration"] = int(duration_days * 86400)
        async with self._session() as session:
            status, data, text = await request_json(session, "POST", f"{self._base()}/api/user", json=payload)
        detail = str(data.get("detail") if isinstance(data, dict) else "").lower()
        if status == 409 or (status >= 400 and ("exist" in detail or "already" in detail)):
            raise PanelUsernameTakenError(f"نام کاربری «{username}» روی پنل تکراری است")
        if status == 401:
            raise PanelError("توکن پنل نادرست یا منقضی است.")
        if status >= 400:
            raise PanelError(f"خطا در ساخت کاربر روی پنل (کد {status}): {detail or (text or '')[:300]}")
        return self._result(data, username)

    async def delete_user(self, username: str) -> bool:
        async with self._session() as session:
            status, _ = await self._call(session, "DELETE", f"user/{username}", "حذف کاربر", not_found_ok=True)
        return status < 400

    async def get_user_usage(self, username: str) -> dict:
        async with self._session() as session:
            _, data = await self._call(session, "GET", f"user/{username}", "دریافت اطلاعات کاربر")
        return {
            "used_bytes": data.get("used_traffic", 0) or 0,
            "data_limit_bytes": data.get("data_limit", 0) or 0,
            "status": data.get("status", ""),
            "expires_at": _expire_to_epoch(data.get("expire")),
        }

    async def get_user(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            _, data = await self._call(session, "GET", f"user/{username}", "دریافت اطلاعات کاربر")
        return self._result(data, username)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            _, data = await self._call(session, "POST", f"user/{username}/revoke_sub", "قطع دسترسی/تولید لینک جدید")
        return self._result(data, username)

    async def set_enabled(self, username: str, enabled: bool) -> None:
        async with self._session() as session:
            await self._call(
                session, "PUT", f"user/{username}", "تغییر وضعیت کاربر",
                json={"status": "active" if enabled else "disabled"},
            )

    supports_template_resync = True

    async def resync_user_template(self, username: str) -> bool:
        """service_id کاربر را با سرویس فعلی قالب یکی می‌کند."""
        target = self._service_id()
        async with self._session() as session:
            _, current = await self._call(session, "GET", f"user/{username}", "دریافت اطلاعات کاربر")
            if isinstance(current, dict) and str(current.get("service_id")) == str(target):
                return False
            await self._call(session, "PUT", f"user/{username}", "هم‌گام‌سازی سرویس کاربر", json={"service_id": target})
        return True

    supports_data_limit_sync = True

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط سقف حجم کاربر را عوض می‌کند (بدون دست‌زدن به انقضا/وضعیت/مصرف). 0 = نامحدود."""
        async with self._session() as session:
            await self._call(session, "PUT", f"user/{username}", "اعمال سقف حجم",
                             json={"data_limit": int(limit_bytes)})

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False) -> PanelUserResult:
        async with self._session() as session:
            _, current = await self._call(session, "GET", f"user/{username}", "دریافت اطلاعات کاربر")
            now_ts = int(time.time())
            is_on_hold = str(current.get("status", "")).lower() == "on_hold"
            current_hold_duration = int(current.get("on_hold_expire_duration") or 0)
            current_expire = _expire_to_epoch(current.get("expire"))
            base = current_expire if (current_expire and current_expire > now_ts) else now_ts
            new_expire = base + add_days * 86400 if add_days else current_expire
            new_limit = new_limit_bytes(
                current.get("data_limit"), current.get("used_traffic"), add_volume_gb, reset_usage, preserve_remaining,
                unlimited=unlimited_volume,
            )
            _, data = await self._call(
                session, "PUT", f"user/{username}", "بروزرسانی کاربر",
                json=(
                    {"data_limit": new_limit, "expire": 0, "status": "on_hold",
                     "on_hold_expire_duration": current_hold_duration + int(add_days * 86400)}
                    if is_on_hold else
                    {"data_limit": new_limit, "expire": new_expire, "status": "active"}
                ),
            )
            if reset_usage:
                try:
                    await self._call(session, "POST", f"user/{username}/reset", "ریست مصرف")
                except PanelError:
                    pass
        return self._result(data, username)

    async def test_connection(self) -> bool:
        try:
            async with self._session() as session:
                await self._call(session, "GET", "system", "بررسی اتصال")
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
