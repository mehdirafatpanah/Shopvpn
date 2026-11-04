#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""Provider MikroTik User Manager (RouterOS REST API): احراز هویت Basic با یوزر/پس ادمین روتر.

حجم و مدت را profile تعیین می‌کند (نام profile به‌جای «کاربر نمونه» گرفته می‌شود)؛ مقدار حجم/مدت ورودی create_user اعمال نمی‌شود.
خروجی به‌جای لینک اشتراک، متن نام کاربری و رمز است.
"""
import secrets

import aiohttp

from ._http import new_session, request_json, load_json
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

_UNSUPPORTED = "این نوع پنل از این عملیات پشتیبانی نمی‌کند."


def credentials_text(username: str, password: str) -> str:
    return f"Username: {username}\nPassword: {password}"


class MikroTikProvider(BasePanelProvider):

    def _base(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self):
        return new_session(
            headers={"Content-Type": "application/json"},
            auth=aiohttp.BasicAuth(self.server["api_username"], self.server["api_password"]),
            server=self.server,
        )

    async def _api(self, session, method: str, path: str, action: str, **kwargs):
        status, data, text = await request_json(session, method, f"{self._base()}/rest/{path}", **kwargs)
        if status == 401:
            raise PanelError("نام کاربری یا رمز عبور روتر نادرست است.")
        if status >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise PanelError(f"خطا در {action} (کد {status}): {detail or (text or '')[:300]}")
        return data

    async def list_product_targets(self):
        """فهرست User Manager Profileها را از RouterOS REST API می‌خواند."""
        async with self._session() as session:
            data = await self._api(session, "GET", "user-manager/profile", "دریافت فهرست profileها")
        if not isinstance(data, list):
            raise PanelError("ساختار پاسخ فهرست profileهای MikroTik قابل شناسایی نیست.")
        choices = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name:
                choices.append({"value": str(name), "label": str(name)})
        if not choices:
            raise PanelError("هیچ User Manager Profile قابل انتخابی در MikroTik پیدا نشد.")
        return {"field": "group_ids", "kind": "scalar", "choices": choices}

    def _profile(self) -> str:
        name = load_json(self.server["group_ids"])
        if not isinstance(name, str) or not name:
            raise PanelError("profile این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن.")
        return name

    async def _find(self, session, username: str) -> dict:
        data = await self._api(session, "GET", "user-manager/user", "دریافت اطلاعات کاربر", params={"name": username})
        if not isinstance(data, list) or not data:
            raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
        return data[0]

    async def _remove(self, session, user_id: str) -> None:
        await self._api(session, "POST", "user-manager/user/remove", "حذف کاربر", json={".id": user_id})

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        profile = sample_username.strip()
        async with self._session() as session:
            data = await self._api(session, "GET", "user-manager/profile", "دریافت profile", params={"name": profile})
        if not isinstance(data, list) or not data:
            raise PanelError(f"profile با نام «{profile}» روی روتر پیدا نشد.")
        return {"group_ids": profile, "proxy_settings": {}}

    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
        profile = self._profile()
        password = secrets.token_hex(6)
        async with self._session() as session:
            try:
                await self._api(
                    session, "POST", "user-manager/user/add", "ساخت کاربر",
                    json={"name": username, "password": password},
                )
            except PanelError as exc:
                if "already" in str(exc).lower():
                    raise PanelUsernameTakenError(f"نام کاربری «{username}» روی پنل تکراری است") from exc
                raise
            try:
                await self._api(
                    session, "POST", "user-manager/user-profile/add", "تخصیص profile",
                    json={"user": username, "profile": profile},
                )
            except PanelError:
                try:
                    await self._remove(session, (await self._find(session, username))[".id"])
                except PanelError:
                    pass
                raise
        return PanelUserResult(username=username, subscription_url=credentials_text(username, password), raw={})

    async def delete_user(self, username: str) -> bool:
        async with self._session() as session:
            try:
                user = await self._find(session, username)
            except PanelError as exc:
                if "پیدا نشد" in str(exc):
                    return False
                raise
            await self._remove(session, user[".id"])
        return True

    async def get_user_usage(self, username: str) -> dict:
        async with self._session() as session:
            user = await self._find(session, username)
            data = await self._api(
                session, "POST", "user-manager/user/monitor", "دریافت مصرف",
                json={"once": True, ".id": user[".id"]},
            )
        entry = data[0] if isinstance(data, list) and data else {}
        used = int(entry.get("total-upload") or 0) + int(entry.get("total-download") or 0)
        disabled = str(user.get("disabled", "false")).lower() in ("true", "yes")
        return {"used_bytes": used, "data_limit_bytes": 0, "status": "disabled" if disabled else "active"}

    async def get_user(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            user = await self._find(session, username)
        return PanelUserResult(
            username=username, subscription_url=credentials_text(username, user.get("password", "")), raw=user,
        )

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False) -> PanelUserResult:
        raise PanelError(_UNSUPPORTED)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        raise PanelError(_UNSUPPORTED)

    async def test_connection(self) -> bool:
        try:
            async with self._session() as session:
                await self._api(session, "GET", "system/resource", "بررسی اتصال")
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
