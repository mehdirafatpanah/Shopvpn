"""
Provider پنل Marzneshin (فورک جدیدتر و مقیاس‌پذیرتر Marzban).

✅ تایید‌شده با بررسی سورس واقعی یک بات معروف و پرکاربرد فارسی که به
Marzneshin وصل می‌شود (endpoint ها، نام فیلدها و فرمت تاریخ همگی از روی
همان پیاده‌سازی واقعی گرفته شده‌اند، نه حدس).

تفاوت کلیدی با Marzban/PasarGuard:
- مرزنشین دسترسی کاربر به اینباند را از طریق «سرویس» (Service) مدیریت
  می‌کند، نه proxies/inbounds خام. هر سرویس یک شناسه‌ی عددی دارد.
- endpoint احراز هویت جمع بسته شده: /api/admins/token (نه admin مفرد).
- expire به‌صورت یک تاریخ کامل (expire_date با فرمت ISO شامل ساعت) +
  یک استراتژی (expire_strategy="fixed_date") است، نه timestamp خام مثل
  Marzban.

مثل PasarGuard/Marzban، «قالب» با خواندن یک کاربر نمونه‌ی موجود روی پنل
ساخته می‌شود؛ چون سرویس‌ها فقط یک لیست عدد هستند (نه دیکشنری پیچیده‌ی
proxy)، از همان ستون group_ids دیتابیس برای ذخیره‌ی service_ids استفاده
می‌شود و proxy_settings برای این پنل همیشه خالی می‌ماند - نیازی به تغییر
اسکیمای دیتابیس نیست.
"""
import time
import json
import datetime
import aiohttp

from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError


class MarzneshinProvider(BasePanelProvider):

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        try:
            async with session.post(
                f"{self._base_url()}/api/admins/token",
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

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        """service_ids کاربر نمونه‌ی موجود روی پنل را می‌خواند و به‌عنوان قالب
        برمی‌گرداند (در ستون group_ids ذخیره می‌شود؛ proxy_settings برای این
        پنل استفاده نمی‌شود)."""
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/users/{sample_username}",
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

        service_ids = data.get("service_ids")
        if not service_ids:
            raise PanelError("پاسخ پنل شامل service_ids نبود؛ از یک کاربر دیگر امتحان کن.")

        return {"group_ids": service_ids, "proxy_settings": {}}

    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
        service_ids = self.server["group_ids"]
        if not service_ids:
            raise PanelError(
                "سرویس‌های این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن."
            )
        expire_dt = datetime.datetime.now() + datetime.timedelta(days=duration_days)
        payload = {
            "username": username,
            "service_ids": json.loads(service_ids) if isinstance(service_ids, str) else service_ids,
            "data_limit": int(volume_gb * (1024 ** 3)),
            "data_limit_reset_strategy": "no_reset",
            "expire_strategy": "fixed_date",
            "expire_date": expire_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
        }
        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            try:
                async with session.post(
                    f"{self._base_url()}/api/users",
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
                    f"{self._base_url()}/api/users/{username}",
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
                    f"{self._base_url()}/api/users/{username}",
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
                    f"{self._base_url()}/api/users/{username}",
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
