"""
Provider پنل PasarGuard.

روش احراز هویت: لاگین با یوزر/پس ادمین به /api/admin/token و گرفتن یک
access_token موقت (Bearer) - همان روش خانواده‌ی Marzban که PasarGuard هم از
آن مشتق شده (تایید‌شده با بررسی سورس یک بات معروف و پرکاربرد که به PasarGuard
وصل می‌شود).

نکته‌ی مهم درباره‌ی «اینباند/گروه»: به‌جای اینکه از ادمین بخواهیم دستی
JSON اینباند/پروکسی وارد کند، همان ترفندی که آن بات هم استفاده می‌کند را
پیاده کرده‌ایم: از ادمین یک «نام کاربری نمونه‌ی از قبل موجود روی پنل»
گرفته می‌شود، اطلاعات کاملش (group_ids + proxy_settings) از پنل خوانده و
به‌عنوان قالب پیش‌فرض برای همه‌ی کاربرهای جدید ذخیره می‌شود (بعد از پاک‌کردن
فیلدهای حساس مثل پسورد/کلید هر پروتکل).
"""
import time
import json
import aiohttp

from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError

_SECRET_FIELDS = {
    "shadowsocks": ["password"],
    "trojan": ["password"],
    "wireguard": ["private_key", "public_key", "peer_ips"],
}


class PasarguardProvider(BasePanelProvider):

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        try:
            async with session.post(
                f"{self._base_url()}/api/admin/token",
                data={"username": self.server["api_username"], "password": self.server["api_password"]},
                headers={"Content-Type": "application/x-www-form-urlencoded", "accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 401:
                    raise PanelError("نام کاربری یا رمز عبور ادمین پنل نادرست است.")
                if resp.status >= 400:
                    text = await resp.text()
                    raise PanelError(f"خطا در احراز هویت پنل (کد {resp.status}): {text[:300]}")
                data = await resp.json()
                token = data.get("access_token")
                if not token:
                    raise PanelError("پاسخ پنل شامل توکن نبود.")
                return token
        except aiohttp.ClientError as e:
            raise PanelError(f"خطا در اتصال به پنل: {e}") from e

    def _clean_proxy_settings(self, proxy_settings: dict) -> dict:
        cleaned = {}
        for proto, settings in (proxy_settings or {}).items():
            settings = dict(settings or {})
            for field in _SECRET_FIELDS.get(proto, ["id"]):
                settings.pop(field, None)
            settings.pop("id", None)
            cleaned[proto] = settings
        return cleaned

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        """اطلاعات یک کاربر نمونه‌ی موجود روی پنل را می‌خواند و group_ids/proxy_settings
        (پاک‌شده از مقادیر حساس) را برای ذخیره به‌عنوان قالب برمی‌گرداند."""
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/user/{sample_username}",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{sample_username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت کاربر نمونه (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        if "group_ids" not in data or "proxy_settings" not in data:
            raise PanelError("پاسخ پنل شامل group_ids/proxy_settings نبود؛ از یک کاربر دیگر امتحان کن.")

        return {
            "group_ids": data.get("group_ids") or [],
            "proxy_settings": self._clean_proxy_settings(data.get("proxy_settings")),
        }

    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
        group_ids = self.server["group_ids"]
        proxy_settings = self.server["proxy_settings"]
        if not group_ids or not proxy_settings:
            raise PanelError(
                "قالب گروه/پروکسی برای این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن."
            )
        payload = {
            "username": username,
            "proxy_settings": json.loads(proxy_settings) if isinstance(proxy_settings, str) else proxy_settings,
            "group_ids": json.loads(group_ids) if isinstance(group_ids, str) else group_ids,
            "data_limit": int(volume_gb * (1024 ** 3)),  # 0 = نامحدود
            "expire": (int(time.time()) + duration_days * 86400) if duration_days else 0,  # 0 = بدون انقضا
            "note": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
            "data_limit_reset_strategy": "no_reset",
        }
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            try:
                async with session.post(
                    f"{self._base_url()}/api/user",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 409:
                        raise PanelUsernameTakenError(f"نام کاربری «{username}» روی پنل تکراری است")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در ساخت کاربر روی پنل (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)

    async def delete_user(self, username: str) -> bool:
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            try:
                async with session.delete(
                    f"{self._base_url()}/api/user/{username}",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    return resp.status < 400
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

    async def get_user_usage(self, username: str) -> dict:
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/user/{username}",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت اطلاعات کاربر (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e
        return {
            "used_bytes": data.get("used_traffic", 0) or 0,
            "data_limit_bytes": data.get("data_limit", 0) or 0,
            "status": data.get("status", ""),
        }

    async def get_user(self, username: str) -> PanelUserResult:
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/user/{username}",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت اطلاعات کاربر (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e
        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)

    async def test_connection(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                await self._get_token(session)
            return True
        except PanelError:
            return False

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False) -> PanelUserResult:
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            try:
                async with session.get(
                    f"{self._base_url()}/api/user/{username}", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت اطلاعات کاربر (کد {resp.status}): {text[:300]}")
                    current = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

            now_ts = int(time.time())
            current_expire = current.get("expire")
            base_expire = current_expire if (current_expire and current_expire > now_ts) else now_ts
            new_expire = base_expire + add_days * 86400 if add_days else current_expire
            new_limit = int(current.get("data_limit") or 0) + int(add_volume_gb * (1024 ** 3)) if add_volume_gb else current.get("data_limit")

            payload = {"data_limit": new_limit, "expire": new_expire, "status": "active"}
            try:
                async with session.put(
                    f"{self._base_url()}/api/user/{username}", json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در بروزرسانی کاربر روی پنل (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

            if reset_usage:
                try:
                    async with session.post(
                        f"{self._base_url()}/api/user/{username}/reset", headers=headers,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ):
                        pass
                except aiohttp.ClientError:
                    pass

        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)
