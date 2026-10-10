#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
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
import asyncio
import aiohttp
from datetime import datetime, timezone
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

from . import auth_cache
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError

API_KEY_PREFIX = "pg_key_"

_SECRET_FIELDS = {
    "shadowsocks": ["password"],
    "trojan": ["password"],
    "wireguard": ["private_key", "public_key", "peer_ips"],
}


def _expire_to_epoch(value):
    """پاسارگارد در GET، فیلد expire را گاهی به‌صورت رشته (عدد epoch رشته‌ای یا
    تاریخ ISO) برمی‌گرداند، نه همیشه عدد خام مثل مرزبان. این تابع هر دو حالت
    را به epoch عددی (ثانیه) تبدیل می‌کند؛ ورودی خالی/None => None (بدون انقضا)."""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            pass
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


class PasarguardProvider(BasePanelProvider):
    supports_user_limit = True
    supports_online_status = True
    online_window_seconds = 120


    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(connector=self._build_connector())

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _api_key_mode(self) -> bool:
        """اگر مقدار ذخیره‌شده به‌جای رمز، یک API Key پاسارگارد (pg_key_...) باشد."""
        return str(self.server["api_password"] or "").strip().startswith(API_KEY_PREFIX)

    def _auth(self, token: str) -> dict:
        if self._api_key_mode():
            return {"X-Api-Key": token}
        return {"Authorization": f"Bearer {token}"}

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        """در حالت API Key خودِ کلید را برمی‌گرداند؛ وگرنه توکن را از کش می‌خواند
        (اگر معتبر باشد) و فقط وقتی کش خالی/منقضی باشد واقعاً لاگین می‌کند."""
        if self._api_key_mode():
            return str(self.server["api_password"]).strip()
        key = auth_cache.cache_key("pasarguard", self.server)
        cached = auth_cache.get_token(key)
        if cached:
            return cached
        token = await self._login(session)
        auth_cache.set_token(key, token)
        return token

    async def _login(self, session: aiohttp.ClientSession) -> str:
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
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

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
        async with self._session() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/user/{sample_username}",
                    headers={**self._auth(token), "accept": "application/json"},
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

        if "group_ids" not in data or "proxy_settings" not in data:
            raise PanelError("پاسخ پنل شامل group_ids/proxy_settings نبود؛ از یک کاربر دیگر امتحان کن.")

        return {
            "group_ids": data.get("group_ids") or [],
            "proxy_settings": self._clean_proxy_settings(data.get("proxy_settings")),
        }

    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False,
                           user_limit: int = 0) -> PanelUserResult:
        group_ids = self.server["group_ids"]
        proxy_settings = self.server["proxy_settings"]
        if not group_ids or not proxy_settings:
            raise PanelError(
                "قالب گروه/پروکسی برای این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن."
            )
        start_on_first_use = bool(self.server["start_on_first_use"]) if "start_on_first_use" in self.server.keys() else bool(start_on_first_use)
        payload = {
            "username": username,
            "proxy_settings": json.loads(proxy_settings) if isinstance(proxy_settings, str) else proxy_settings,
            "group_ids": json.loads(group_ids) if isinstance(group_ids, str) else group_ids,
            "data_limit": int(volume_gb * (1024 ** 3)),  # 0 = نامحدود
            "expire": (int(time.time() + duration_days * 86400)) if duration_days and not start_on_first_use else 0,
            "note": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
            "data_limit_reset_strategy": "no_reset",
            "status": "on_hold" if start_on_first_use and duration_days else "active",
        }
        if start_on_first_use and duration_days:
            payload["on_hold_expire_duration"] = int(duration_days * 86400)
        if user_limit:
            payload["hwid_limit"] = int(user_limit)
        async with self._session() as session:
            token = await self._get_token(session)
            try:
                async with session.post(
                    f"{self._base_url()}/api/user",
                    json=payload,
                    headers={**self._auth(token), "accept": "application/json", "Content-Type": "application/json"},
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
                    f"{self._base_url()}/api/user/{username}",
                    headers={**self._auth(token), "accept": "application/json"},
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
                    f"{self._base_url()}/api/user/{username}",
                    headers={**self._auth(token), "accept": "application/json"},
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
            "expires_at": _expire_to_epoch(data.get("expire")),
        }

    async def get_user(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/user/{username}",
                    headers={**self._auth(token), "accept": "application/json"},
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
        """POST /api/user/{username}/revoke_sub: کلید/UUID پروتکل‌های کاربر را
        روی پنل عوض می‌کند و لینک اشتراک جدید می‌سازد؛ data_limit/expire/مصرف
        فعلی دست‌نخورده می‌ماند (خانواده‌ی Marzban/PasarGuard این را «revoke»
        می‌نامند)."""
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {**self._auth(token), "accept": "application/json"}
            try:
                async with session.post(
                    f"{self._base_url()}/api/user/{username}/revoke_sub", headers=headers,
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
        """همیشه واقعاً لاگین می‌کند (نه از کش) تا واقعاً یوزر/پس فعلی را تست کند.
        در حالت API Key، GET /api/admin را با کلید صدا می‌زند."""
        if self._api_key_mode():
            return await self._test_api_key()
        try:
            async with self._session() as session:
                token = await self._login(session)
            auth_cache.set_token(auth_cache.cache_key("pasarguard", self.server), token)
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False

    async def _get_json(self, path: str, error_label: str):
        async with self._session() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}{path}",
                    headers={**self._auth(token), "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"{error_label}: مورد پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"{error_label} (کد {resp.status}): {text[:300]}")
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

    async def is_client_online(self, username: str) -> bool:
        """پاسارگارد endpoint لحظه‌ای آنلاین ندارد؛ کاربر وقتی آنلاین حساب می‌شود که
        online_at او در ۲ دقیقه‌ی اخیر (همان پنجره‌ی خود پنل) باشد."""
        data = await self._get_json(f"/api/user/{username}", "خطا در دریافت اطلاعات کاربر")
        raw = data.get("online_at")
        if not raw:
            return False
        try:
            seen = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return False
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - seen).total_seconds() <= self.online_window_seconds

    async def get_panel_stats(self) -> dict:
        """آمار کلی پنل از /api/system/users و تعداد اینباندها از /api/inbounds."""
        users = await self._get_json("/api/system/users", "خطا در دریافت آمار پنل")
        try:
            inbounds = await self._get_json("/api/inbounds", "خطا در دریافت اینباندها")
        except PanelError:
            inbounds = []
        return {
            "inbound_count": len(inbounds) if isinstance(inbounds, list) else 0,
            "total_clients": int(users.get("total_user") or 0),
            "online_clients": int(users.get("online_users") or 0),
            "expired_clients": int(users.get("expired_users") or 0),
            "disabled_clients": int(users.get("disabled_users") or 0),
        }

    async def _test_api_key(self) -> bool:
        key = str(self.server["api_password"]).strip()
        try:
            async with self._session() as session:
                async with session.get(
                    f"{self._base_url()}/api/admin",
                    headers={"X-Api-Key": key, "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 401:
                        self.last_error = "API Key نامعتبر، منقضی یا غیرفعال است."
                        return False
                    if resp.status == 403:
                        self.last_error = "ادمینِ صاحب این API Key غیرفعال است یا دسترسی ندارد."
                        return False
                    if resp.status >= 400:
                        text = await resp.text()
                        self.last_error = f"خطا در احراز هویت پنل (کد {resp.status}): {text[:300]}"
                        return False
                    return True
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.last_error = f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}"
            return False

    async def set_enabled(self, username: str, enabled: bool) -> None:
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {**self._auth(token), "accept": "application/json", "Content-Type": "application/json"}
            payload = {"status": "active" if enabled else "disabled"}
            try:
                async with session.put(
                    f"{self._base_url()}/api/user/{username}", json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 404:
                        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در تغییر وضعیت کاربر (کد {resp.status}): {text[:300]}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           user_limit: int = None) -> PanelUserResult:
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {**self._auth(token), "accept": "application/json", "Content-Type": "application/json"}
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

            now_ts = int(time.time())
            is_on_hold = str(current.get("status", "")).lower() == "on_hold"
            current_hold_duration = int(current.get("on_hold_expire_duration") or 0)
            current_expire = _expire_to_epoch(current.get("expire"))
            base_expire = current_expire if (current_expire and current_expire > now_ts) else now_ts
            new_expire = base_expire + add_days * 86400 if add_days else current_expire
            # تمدید «کامل» (reset_usage=True) دو حالت دارد: پیش‌فرض (preserve_remaining=False)
            # سقف حجم را با بستهٔ تازه جایگزین می‌کند، وگرنه حجم باقیمانده‌ی قبلی هم به‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # اشتباه به سقف جدید اضافه می‌شود. اگر preserve_remaining=True باشد (تمدید کامل
            # دستی)، حجم باقیمانده‌ی مصرف‌نشده حفظ و بستهٔ جدید رویش اضافه می‌شود - چون زمان‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # همیشه به همین شکل حفظ‌شونده محاسبه می‌شود. تمدید «افزایشی» (reset_usage=False)
            # همیشه روی سقف قبلی جمع می‌زند.
            if reset_usage and preserve_remaining:
                remaining = max(int(current.get("data_limit") or 0) - int(current.get("used_traffic") or 0), 0)
                new_limit = remaining + int(add_volume_gb * (1024 ** 3))
            elif add_volume_gb:
                new_limit = int(add_volume_gb * (1024 ** 3)) if reset_usage else int(current.get("data_limit") or 0) + int(add_volume_gb * (1024 ** 3))
            else:
                new_limit = current.get("data_limit")

            if is_on_hold:
                payload = {"data_limit": new_limit, "expire": 0, "status": "on_hold",
                           "on_hold_expire_duration": current_hold_duration + int(add_days * 86400)}
            else:
                payload = {"data_limit": new_limit, "expire": new_expire, "status": "active"}
            if user_limit is not None:
                payload["hwid_limit"] = int(user_limit)
            try:
                async with session.put(
                    f"{self._base_url()}/api/user/{username}", json=payload, headers=headers,
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
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
