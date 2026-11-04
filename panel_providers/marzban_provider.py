#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""
Provider پنل Marzban (Gozargah/Marzban) - همان پنل اصلی که PasarGuard از روی آن
فورک شده.

روش احراز هویت: دقیقاً مثل PasarGuard - لاگین با یوزر/پس ادمین به
/api/admin/token و گرفتن access_token موقت (Bearer). (تایید‌شده با بررسی
چند کتابخانه‌ی کلاینت رسمی/معروف Marzban.)

تفاوت اصلی با PasarGuard فقط در نام‌گذاری فیلدهای payload است - چیزی که
PasarGuard در فورک خودش عوض کرده:
  - Marzban: proxies (دیکشنری per-protocol) + inbounds (دیکشنری
    protocol -> لیست نام inbound)
  - PasarGuard: proxy_settings + group_ids (لیست عددی)

به همین دلیل «قالب» گرفته‌شده از کاربر نمونه اینجا هم در همان ستون‌های
عمومی group_ids/proxy_settings دیتابیس ذخیره می‌شود (فقط این‌جا معنایشان
inbounds/proxies است، نه group_ids/proxy_settings واقعی) - نیازی به تغییر
اسکیمای دیتابیس نیست.
"""
import time
import json
import asyncio
import aiohttp
from datetime import datetime
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

from . import auth_cache
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError

_SECRET_FIELDS = {
    "vmess": ["id"],
    "vless": ["id"],
    "trojan": ["password"],
    "shadowsocks": ["password"],
}


def _expire_to_epoch(value):
    """برخی فورک‌ها/نسخه‌های خانواده‌ی Marzban فیلد expire را رشته (عدد یا ISO)
    برمی‌گردانند، نه همیشه epoch خام. این تابع هر دو حالت را عددی می‌کند تا
    مقایسه‌ی زمانی توی update_user کرش نکند."""
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


class MarzbanProvider(BasePanelProvider):

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(connector=self._build_connector())

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        """توکن را از کش می‌خواند (اگر معتبر باشد) تا لاگین تکراری روی هر
        عملیات انجام نشود؛ فقط وقتی کش خالی/منقضی باشد واقعاً لاگین می‌کند."""
        key = auth_cache.cache_key("marzban", self.server)
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

    def _clean_proxies(self, proxies: dict) -> dict:
        cleaned = {}
        for proto, settings in (proxies or {}).items():
            settings = dict(settings or {})
            for field in _SECRET_FIELDS.get(proto, ["id"]):
                settings.pop(field, None)
            cleaned[proto] = settings
        return cleaned

    async def list_product_targets(self):
        """دریافت Inboundهای واقعی Marzban از API؛ مستقل از کاربر نمونه."""
        async with self._session() as session:
            token = await self._get_token(session)
            try:
                async with session.get(
                    f"{self._base_url()}/api/inbounds",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        raise PanelError(f"خطا در دریافت Inboundهای Marzban (کد {resp.status}): {body[:300]}")
                    payload = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise PanelError(f"خطا در اتصال برای دریافت Inboundهای Marzban: {exc or 'timeout'}") from exc

        # API استاندارد Marzban یک map از protocol به فهرست نام inbound می‌دهد.
        if isinstance(payload, dict):
            payload = payload.get("inbounds", payload.get("data", payload))
        if not isinstance(payload, dict):
            raise PanelError("ساختار پاسخ API Inboundهای Marzban قابل شناسایی نیست.")
        choices = []
        for protocol, entries in payload.items():
            if isinstance(entries, dict):
                entries = entries.get("inbounds") or entries.get("items") or entries.get("data") or []
            if not isinstance(entries, (list, tuple)):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    name = entry.get("tag") or entry.get("name") or entry.get("remark") or entry.get("id")
                else:
                    name = entry
                if name not in (None, ""):
                    value = f"{protocol}::{name}"
                    choices.append({"value": value, "label": f"{str(protocol).upper()} · {name}"})
        if not choices:
            raise PanelError("هیچ Inbound قابل انتخابی از Marzban دریافت نشد.")
        return {"field": "group_ids", "kind": "protocol_map", "choices": choices}

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        """اطلاعات یک کاربر نمونه‌ی موجود روی پنل را می‌خواند و inbounds/proxies
        (پاک‌شده از مقادیر حساس) را برای ذخیره به‌عنوان قالب برمی‌گرداند.
        خروجی در همان شکل PasarGuard (group_ids/proxy_settings) است تا با
        بقیه‌ی کد پروژه سازگار بماند؛ اینجا group_ids در واقع همان inbounds
        و proxy_settings همان proxies است."""
        async with self._session() as session:
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

        if "inbounds" not in data or "proxies" not in data:
            raise PanelError("پاسخ پنل شامل inbounds/proxies نبود؛ از یک کاربر دیگر امتحان کن.")

        return {
            "group_ids": data.get("inbounds") or {},
            "proxy_settings": self._clean_proxies(data.get("proxies")),
        }

    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False) -> PanelUserResult:
        inbounds = self.server["group_ids"]
        proxies = self.server["proxy_settings"]
        if not inbounds or not proxies:
            raise PanelError(
                "قالب inbounds/proxies برای این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن."
            )
        start_on_first_use = bool(self.server["start_on_first_use"]) if "start_on_first_use" in self.server.keys() else bool(start_on_first_use)
        payload = {
            "username": username,
            "proxies": json.loads(proxies) if isinstance(proxies, str) else proxies,
            "inbounds": json.loads(inbounds) if isinstance(inbounds, str) else inbounds,
            "data_limit": int(volume_gb * (1024 ** 3)),  # 0 = نامحدود (استاندارد Marzban)
            "expire": (int(time.time() + duration_days * 86400)) if duration_days and not start_on_first_use else 0,  # on-hold زمان را بعد از اولین اتصال شروع می‌کند
            "note": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
            "data_limit_reset_strategy": "no_reset",
            "status": "on_hold" if start_on_first_use and duration_days else "active",
        }
        if start_on_first_use and duration_days:
            payload["on_hold_expire_duration"] = int(duration_days * 86400)
        async with self._session() as session:
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
                    f"{self._base_url()}/api/user/{username}",
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
            "expires_at": _expire_to_epoch(data.get("expire")),
        }

    async def get_user(self, username: str) -> PanelUserResult:
        async with self._session() as session:
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
        sub_url = data.get("subscription_url") or ""
        if sub_url.startswith("/"):
            sub_url = self._base_url() + sub_url
        return PanelUserResult(username=data.get("username", username), subscription_url=sub_url, raw=data)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        """POST /api/user/{username}/revoke_sub: UUID/پسورد هر پروکسی کاربر را
        عوض می‌کند و لینک اشتراک تازه می‌سازد؛ data_limit/expire/مصرف فعلی
        دست‌نخورده می‌ماند (endpoint رسمی Marzban برای همین منظور)."""
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
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
        """همیشه واقعاً لاگین می‌کند (نه از کش) تا واقعاً یوزر/پس فعلی را تست کند."""
        try:
            async with self._session() as session:
                token = await self._login(session)
            auth_cache.set_token(auth_cache.cache_key("marzban", self.server), token)
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

    supports_template_resync = True

    async def resync_user_template(self, username: str) -> bool:
        """inbounds کاربر را با قالب فعلی پنل در ربات یکی می‌کند."""
        raw = self.server["group_ids"]
        target = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if not target:
            return False
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            return await self._sync_binding(session, headers, f"/api/user/{username}", "inbounds", target)

    supports_data_limit_sync = True

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط سقف حجم کاربر را عوض می‌کند (بدون دست‌زدن به انقضا/وضعیت/مصرف). 0 = نامحدود."""
        async with self._session() as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "Content-Type": "application/json"}
            try:
                async with session.put(
                    f"{self._base_url()}/api/user/{username}", json={"data_limit": int(limit_bytes)}, headers=headers,
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
            # سقف حجم را با بستهٔ تازه جایگزین می‌کند (نه رویش اضافه)، وگرنه حجم باقیمانده‌ی‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # قبلی هم به اشتباه به سقف جدید اضافه می‌شود. اگر preserve_remaining=True باشد
            # (تمدید کامل دستی)، حجم باقیمانده‌ی مصرف‌نشده حفظ و بستهٔ جدید رویش اضافه
            # می‌شود - چون زمان (expire) همیشه به همین شکل جمعی/حفظ‌شونده محاسبه می‌شود و‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # این ناهم‌خوانی بین حجم و زمان همان مشکل گزارش‌شده بود. تمدید «افزایشی»
            # (reset_usage=False) همیشه روی سقف قبلی جمع می‌زند.
            if unlimited_volume:
                new_limit = 0  # 0 = نامحدود
            elif reset_usage and preserve_remaining:
                remaining = max(int(current.get("data_limit") or 0) - int(current.get("used_traffic") or 0), 0)
                new_limit = remaining + int(add_volume_gb * (1024 ** 3))
            elif add_volume_gb:
                new_limit = int(add_volume_gb * (1024 ** 3)) if reset_usage else int(current.get("data_limit") or 0) + int(add_volume_gb * (1024 ** 3))
            else:
                new_limit = current.get("data_limit")

            if is_on_hold:
                payload = {
                    "data_limit": new_limit,
                    "expire": 0,
                    "status": "on_hold",
                    "on_hold_expire_duration": current_hold_duration + int(add_days * 86400),
                }
            else:
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
