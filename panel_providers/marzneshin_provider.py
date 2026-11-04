#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
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
import asyncio
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
import aiohttp

from . import auth_cache
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError


class MarzneshinProvider(BasePanelProvider):

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(connector=self._build_connector())

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        """توکن را از کش می‌خواند (اگر معتبر باشد) تا لاگین تکراری روی هر
        عملیات انجام نشود؛ فقط وقتی کش خالی/منقضی باشد واقعاً لاگین می‌کند."""
        key = auth_cache.cache_key("marzneshin", self.server)
        cached = auth_cache.get_token(key)
        if cached:
            return cached
        token = await self._login(session)
        auth_cache.set_token(key, token)
        return token

    async def _login(self, session: aiohttp.ClientSession) -> str:
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
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

    async def list_product_targets(self):
        """دریافت Serviceهای موجود Marzneshin؛ مستقل از سرویس کاربر نمونه."""
        async with self._session() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/services",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        raise PanelError(f"خطا در دریافت Serviceهای Marzneshin (کد {resp.status}): {body[:300]}")
                    payload = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise PanelError(f"خطا در اتصال برای دریافت Serviceهای Marzneshin: {exc or 'timeout'}") from exc

        if isinstance(payload, dict):
            items = payload.get("items") or payload.get("services") or payload.get("data") or payload.get("results") or []
            if isinstance(items, dict):
                items = items.get("items") or items.get("services") or items.get("results") or []
        else:
            items = payload
        if not isinstance(items, list):
            raise PanelError("ساختار پاسخ API سرویس‌های Marzneshin قابل شناسایی نیست.")
        choices = []
        for item in items:
            if not isinstance(item, dict):
                continue
            service_id = item.get("id") or item.get("service_id")
            if service_id is None:
                continue
            label = item.get("name") or item.get("title") or item.get("remark") or f"Service {service_id}"
            choices.append({"value": str(service_id), "label": f"{label} · ID {service_id}"})
        if not choices:
            raise PanelError("هیچ Service قابل انتخابی از Marzneshin دریافت نشد.")
        return {"field": "group_ids", "kind": "list", "choices": choices}

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        """service_ids کاربر نمونه‌ی موجود روی پنل را می‌خواند و به‌عنوان قالب
        برمی‌گرداند (در ستون group_ids ذخیره می‌شود؛ proxy_settings برای این
        پنل استفاده نمی‌شود)."""
        async with self._session() as session:
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

        service_ids = data.get("service_ids")
        if not service_ids:
            raise PanelError("پاسخ پنل شامل service_ids نبود؛ از یک کاربر دیگر امتحان کن.")

        return {"group_ids": service_ids, "proxy_settings": {}}

    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False) -> PanelUserResult:
        service_ids = self.server["group_ids"]
        if not service_ids:
            raise PanelError(
                "سرویس‌های این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن."
            )
        start_on_first_use = bool(self.server["start_on_first_use"]) if "start_on_first_use" in self.server.keys() else bool(start_on_first_use)
        payload = {
            "username": username,
            "service_ids": json.loads(service_ids) if isinstance(service_ids, str) else service_ids,
            "data_limit": int(volume_gb * (1024 ** 3)),  # 0 = نامحدود
            "data_limit_reset_strategy": "no_reset",
            "note": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
        }
        if duration_days and start_on_first_use:
            payload["expire_strategy"] = "start_on_first_use"
            payload["usage_duration"] = int(duration_days * 86400)
        elif duration_days:
            expire_dt = datetime.datetime.now() + datetime.timedelta(days=duration_days)
            payload["expire_strategy"] = "fixed_date"
            payload["expire_date"] = expire_dt.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            payload["expire_strategy"] = "never"  # بدون انقضا
        async with self._session() as session:
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)

    async def delete_user(self, username: str) -> bool:
        async with self._session() as session:
            token = await self._get_token(session)
            try:
                async with session.delete(
                    f"{self._base_url()}/api/users/{username}",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    return resp.status < 400
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

    async def get_user_usage(self, username: str) -> dict:
        async with self._session() as session:
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
        return {
            "used_bytes": data.get("used_traffic", 0) or 0,
            "data_limit_bytes": data.get("data_limit", 0) or 0,
            "status": data.get("status", ""),
            "expires_at": data.get("expire_date"),
        }

    async def get_user(self, username: str) -> PanelUserResult:
        async with self._session() as session:
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        """POST /api/users/{username}/revoke_sub: کلید کاربر را عوض می‌کند و
        لینک اشتراک تازه می‌سازد؛ data_limit/expire_date/مصرف فعلی دست‌نخورده
        می‌ماند.
        ⚠️ برخلاف pasarguard/marzban که این endpoint مستقیماً روی سورس آن‌ها
        دیده شده، اینجا فقط بر اساس الگوی یکسانِ بقیه‌ی مسیرهای این پنل
        (جمع‌بسته: /api/users/... به‌جای /api/user/...) قیاس شده و مستقیماً
        روی یک نصب واقعی Marzneshin تست نشده - قبل از استفاده‌ی جدی حتماً
        روی یک کاربر تستی امتحان شود."""
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
            try:
                async with session.post(
                    f"{self._base_url()}/api/users/{username}/revoke_sub", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در قطع دسترسی/تولید لینک جدید (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)

    async def test_connection(self) -> bool:
        """همیشه واقعاً لاگین می‌کند (نه از کش) تا واقعاً یوزر/پس فعلی را تست کند."""
        try:
            async with self._session() as session:
                token = await self._login(session)
            auth_cache.set_token(auth_cache.cache_key("marzneshin", self.server), token)
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False

    async def set_enabled(self, username: str, enabled: bool) -> None:
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            payload = {"status": "active" if enabled else "disabled"}
            try:
                async with session.put(
                    f"{self._base_url()}/api/users/{username}", json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در تغییر وضعیت کاربر (کد {resp.status}): {text[:300]}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

    supports_template_resync = True

    async def resync_user_template(self, username: str) -> bool:
        """service_ids کاربر را با قالب فعلی پنل در ربات یکی می‌کند."""
        raw = self.server["group_ids"]
        target = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if not target:
            return False
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            return await self._sync_binding(session, headers, f"/api/users/{username}", "service_ids", target)

    async def rename_user(self, username: str, new_username: str) -> str:
        """مرزنشین هم endpoint رسمی برای تغییر username ندارد؛ کاربر با
        همان service_ids/data_limit/expire ولی نام تازه ساخته می‌شود و کاربر
        قدیمی حذف می‌شود. لینک اشتراک تازه را برمی‌گرداند."""
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            try:
                async with session.get(
                    f"{self._base_url()}/api/users/{username}", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت اطلاعات کاربر (کد {resp.status}): {text[:300]}")
                    current = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

            create_payload = {
                "username": new_username,
                "service_ids": current.get("service_ids") or [],
                "data_limit": current.get("data_limit"),
                "data_limit_reset_strategy": current.get("data_limit_reset_strategy") or "no_reset",
                "note": current.get("note") or "",
            }
            if current.get("expire_date"):
                create_payload["expire_strategy"] = current.get("expire_strategy") or "fixed_date"
                create_payload["expire_date"] = current.get("expire_date")
            else:
                create_payload["expire_strategy"] = "never"
            try:
                async with session.post(
                    f"{self._base_url()}/api/users", json=create_payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 409:
                        raise PanelError(f"نام «{new_username}» از قبل روی پنل استفاده شده است.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در ساخت کاربر با نام جدید (کد {resp.status}): {text[:300]}")
                    new_data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

            try:
                async with session.delete(
                    f"{self._base_url()}/api/users/{username}", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ):
                    pass
            except aiohttp.ClientError:
                pass

        sub_url = new_data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return sub_url

    supports_data_limit_sync = True

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط سقف حجم کاربر را عوض می‌کند (بدون دست‌زدن به انقضا/وضعیت/مصرف). 0 = نامحدود."""
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            try:
                async with session.put(
                    f"{self._base_url()}/api/users/{username}", json={"data_limit": int(limit_bytes)}, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در اعمال سقف حجم روی پنل (کد {resp.status}): {text[:300]}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False) -> PanelUserResult:
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            try:
                async with session.get(
                    f"{self._base_url()}/api/users/{username}", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت اطلاعات کاربر (کد {resp.status}): {text[:300]}")
                    current = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

            now_dt = datetime.datetime.now()
            is_start_on_first_use = current.get("expire_strategy") == "start_on_first_use"
            current_usage_duration = int(current.get("usage_duration") or 0)
            current_expire_str = current.get("expire_date")
            current_expire_dt = None
            if current_expire_str:
                try:
                    current_expire_dt = datetime.datetime.strptime(current_expire_str[:19], "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    current_expire_dt = None
            base_dt = current_expire_dt if (current_expire_dt and current_expire_dt > now_dt) else now_dt
            new_expire_dt = (base_dt + datetime.timedelta(days=add_days)) if add_days else current_expire_dt
            # تمدید «کامل» (reset_usage=True) دو حالت دارد: پیش‌فرض (preserve_remaining=False)‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # سقف حجم را با بستهٔ تازه جایگزین می‌کند، وگرنه حجم باقیمانده‌ی قبلی هم به
            # اشتباه به سقف جدید اضافه می‌شود. اگر preserve_remaining=True باشد (تمدید کامل
            # دستی)، حجم باقیمانده‌ی مصرف‌نشده حفظ و بستهٔ جدید رویش اضافه می‌شود - چون زمان‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # همیشه به همین شکل حفظ‌شونده محاسبه می‌شود. تمدید «افزایشی» (reset_usage=False)
            # همیشه روی سقف قبلی جمع می‌زند.
            if unlimited_volume:
                new_limit = 0  # 0 = نامحدود
            elif reset_usage and preserve_remaining:
                remaining = max(int(current.get("data_limit") or 0) - int(current.get("used_traffic") or 0), 0)
                new_limit = remaining + int(add_volume_gb * (1024 ** 3))
            elif add_volume_gb:
                new_limit = int(add_volume_gb * (1024 ** 3)) if reset_usage else int(current.get("data_limit") or 0) + int(add_volume_gb * (1024 ** 3))
            else:
                new_limit = current.get("data_limit")

            if is_start_on_first_use:
                payload = {"data_limit": new_limit,
                           "expire_strategy": "start_on_first_use",
                           "usage_duration": current_usage_duration + int(add_days * 86400)}
            else:
                payload = {"data_limit": new_limit}
                if new_expire_dt:
                    payload["expire_strategy"] = "fixed_date"
                    payload["expire_date"] = new_expire_dt.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                async with session.put(
                    f"{self._base_url()}/api/users/{username}", json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در بروزرسانی کاربر روی پنل (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

            if reset_usage:
                try:
                    async with session.post(
                        f"{self._base_url()}/api/users/{username}/reset", headers=headers,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ):
                        pass
                except aiohttp.ClientError:
                    pass

        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
