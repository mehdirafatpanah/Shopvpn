"""
Provider پنل Hiddify Manager - کاملاً متفاوت از خانواده‌ی Marzban/PasarGuard.

✅ تایید‌شده با بررسی سورس واقعی یک بات معروف و پرکاربرد فارسی که به
Hiddify وصل می‌شود؛ endpoint ها و نام فیلدهای create/delete/list همگی از
روی همان پیاده‌سازی واقعی گرفته شده‌اند.

- احراز هویت: نه یوزر/پس + توکن موقت، بلکه یک «Hiddify-API-Key» ثابت
  (همان UUID ادمین) که در هدر هر درخواست فرستاده می‌شود. از ستون موجود
  api_password برای نگه‌داشتن همین کلید استفاده می‌کنیم (api_username
  عملاً استفاده نمی‌شود)؛ نیازی به تغییر اسکیمای دیتابیس نیست.
- هویت کاربر روی پنل یک UUID است، نه یک username معمولی؛ فیلد «name» فقط
  یک برچسب نمایشی است. موقع ساخت یک UUID تازه تولید می‌کنیم و لینک
  اشتراک را از روی همان UUID می‌سازیم؛ برای عملیات‌های بعدی (حذف/دریافت
  مصرف) که فقط username پروژه را داریم، لیست کاربرهای پنل خوانده می‌شود
  و بر اساس «name» تطبیق‌شده با username پیدا می‌شود.
- بدون گروه/inbound/قالب: نیازی به «تعیین کاربر نمونه» نیست.
- ⚠️ نکته‌ی مهم: روی اکثر نصب‌های Hiddify، آدرس API ادمین (که معمولاً یک
  admin_proxy_path مخفی/تصادفی دارد) با آدرس عمومیِ لینک اشتراک (sub link)
  یکی نیست. به همین دلیل، درست مثل 3X-UI، یک «آدرس پایه‌ی Subscription»
  جدا از آدرس ادمین گرفته می‌شود و در همان ستون xui_sub_base_url ذخیره
  می‌شود (بازاستفاده از ستون موجود؛ نیازی به تغییر اسکیما نیست). اگر خالی
  بماند، به‌عنوان آخرین راه‌حل از همان آدرس API استفاده می‌شود.
"""
import uuid as uuid_lib
import aiohttp

from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError


class HiddifyProvider(BasePanelProvider):

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _sub_base_url(self) -> str:
        try:
            url = self.server["xui_sub_base_url"]
        except (KeyError, IndexError):
            url = None
        return (url or self.server["api_url"]).rstrip("/")

    def _headers(self) -> dict:
        return {
            "Hiddify-API-Key": self.server["api_password"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _find_by_name(self, session: aiohttp.ClientSession, username: str) -> dict:
        """چون شناسه‌ی واقعی کاربر روی هیدیفای UUID است نه username پروژه،
        برای پیدا کردن کاربر لیست کاربرهای پنل را می‌خوانیم و بر اساس فیلد
        «name» (که موقع ساخت، همان username پروژه در آن ذخیره شده) می‌گردیم."""
        try:
            async with session.get(
                f"{self._base_url()}/api/v2/admin/user/",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise PanelError(f"خطا در دریافت لیست کاربران (کد {resp.status}): {text[:300]}")
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        users = data if isinstance(data, list) else data.get("users", [])
        for u in users:
            if u.get("name") == username:
                return u
        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        raise PanelError(
            "پنل Hiddify نیازی به «کاربر نمونه»/قالب ندارد؛ این مرحله برای این نوع پنل لازم نیست."
        )

    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
        new_uuid = str(uuid_lib.uuid4())
        payload = {
            "uuid": new_uuid,
            "name": username,
            "added_by_uuid": self.server["api_password"],
            "current_usage_GB": 0,
            "usage_limit_GB": volume_gb,
            "package_days": duration_days,
            "comment": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self._base_url()}/api/v2/admin/user/",
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در ساخت کاربر روی پنل (کد {resp.status}): {text[:300]}")
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        sub_url = f"{self._sub_base_url()}/{new_uuid}/"
        return PanelUserResult(username=username, subscription_url=sub_url, raw=payload)

    async def delete_user(self, username: str) -> bool:
        async with aiohttp.ClientSession() as session:
            try:
                user = await self._find_by_name(session, username)
            except PanelError:
                return False
            try:
                async with session.delete(
                    f"{self._base_url()}/api/v2/admin/user/{user['uuid']}/",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    return resp.status < 400
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

    async def get_user_usage(self, username: str) -> dict:
        async with aiohttp.ClientSession() as session:
            user = await self._find_by_name(session, username)
        used_gb = user.get("current_usage_GB", 0) or 0
        limit_gb = user.get("usage_limit_GB", 0) or 0
        return {
            "used_bytes": int(float(used_gb) * (1024 ** 3)),
            "data_limit_bytes": int(float(limit_gb) * (1024 ** 3)),
            "status": "active",  # هیدیفای فیلد status جدا مثل Marzban ندارد
        }

    async def get_user(self, username: str) -> PanelUserResult:
        async with aiohttp.ClientSession() as session:
            user = await self._find_by_name(session, username)
        sub_url = f"{self._sub_base_url()}/{user.get('uuid')}/"
        return PanelUserResult(username=username, subscription_url=sub_url, raw=user)

    async def test_connection(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url()}/api/v2/admin/user/",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    return resp.status < 400
        except aiohttp.ClientError:
            return False

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False) -> PanelUserResult:
        async with aiohttp.ClientSession() as session:
            user = await self._find_by_name(session, username)
            new_limit = float(user.get("usage_limit_GB") or 0) + add_volume_gb if add_volume_gb else user.get("usage_limit_GB")
            new_days = int(user.get("package_days") or 0) + add_days if add_days else user.get("package_days")
            payload = dict(user)
            payload["usage_limit_GB"] = new_limit
            payload["package_days"] = new_days
            if reset_usage:
                payload["current_usage_GB"] = 0
            try:
                async with session.put(
                    f"{self._base_url()}/api/v2/admin/user/{user['uuid']}/",
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در بروزرسانی کاربر روی پنل (کد {resp.status}): {text[:300]}")
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        sub_url = f"{self._sub_base_url()}/{user['uuid']}/"
        return PanelUserResult(username=username, subscription_url=sub_url, raw=payload)

    async def set_enabled(self, username: str, enabled: bool) -> None:
        async with aiohttp.ClientSession() as session:
            user = await self._find_by_name(session, username)
            payload = dict(user)
            payload["enable"] = bool(enabled)
            try:
                async with session.put(
                    f"{self._base_url()}/api/v2/admin/user/{user['uuid']}/",
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در تغییر وضعیت کاربر (کد {resp.status}): {text[:300]}")
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

    async def rename_user(self, username: str, new_username: str) -> None:
        """روی هیدیفای «name» فقط یک برچسب نمایشی است (شناسه‌ی واقعی uuid
        است)، پس تغییر آن کاملاً بی‌خطر است و لینک/مصرف قبلی دست‌نخورده می‌ماند."""
        async with aiohttp.ClientSession() as session:
            user = await self._find_by_name(session, username)
            payload = dict(user)
            payload["name"] = new_username
            try:
                async with session.put(
                    f"{self._base_url()}/api/v2/admin/user/{user['uuid']}/",
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در تغییر نام کاربر (کد {resp.status}): {text[:300]}")
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        """روی هیدیفای خودِ UUID هم شناسه‌ی کاربر و هم لینک اشتراک است، پس
        «قطع دسترسی و لینک جدید» یعنی یک UUID تازه بسازیم و در همان PUT که
        update_user استفاده می‌کند جایگزین کنیم؛ usage_limit_GB/package_days/
        current_usage_GB بدون تغییر می‌مانند (لینک قدیمی دیگر کار نمی‌کند چون
        دیگر با هیچ کاربری روی پنل match نمی‌شود).
        ⚠️ این رفتار (تغییر uuid از طریق فیلد uuid در بدنه‌ی PUT) بر اساس
        همان الگوی به‌کاررفته در update_user این پروژه است؛ مستقیماً روی یک
        نصب واقعی Hiddify تست نشده - قبل از استفاده‌ی جدی حتماً امتحان شود."""
        async with aiohttp.ClientSession() as session:
            user = await self._find_by_name(session, username)
            new_uuid = str(uuid_lib.uuid4())
            payload = dict(user)
            payload["uuid"] = new_uuid
            try:
                async with session.put(
                    f"{self._base_url()}/api/v2/admin/user/{user['uuid']}/",
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در قطع دسترسی/تولید لینک جدید (کد {resp.status}): {text[:300]}")
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        sub_url = f"{self._sub_base_url()}/{new_uuid}/"
        return PanelUserResult(username=username, subscription_url=sub_url, raw=payload)
