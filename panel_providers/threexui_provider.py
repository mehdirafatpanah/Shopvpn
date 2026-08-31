"""
Provider پنل 3X-UI (MHSanaei/3x-ui).

روش احراز هویت: Bearer API Token (نه لاگین با یوزر/پس روی /login).

چرا این تغییر لازم بود:
- نسخه‌های جدید 3X-UI (v3.x به بعد) یک لایه‌ی CSRF hardening روی /login
  اضافه کرده‌اند که لاگین برنامه‌نویسی (بدون مرورگر/کوکی از قبل) را با
  خطای 403 رد می‌کند (باگ شناخته‌شده‌ی خودِ پروژه‌ی 3x-ui، مثلاً ایشوهای
  #4227 و #5622). یعنی روش قدیمی «لاگین با یوزر/پس و گرفتن کوکی سشن» روی
  پنل‌های امروزی اصلاً کار نمی‌کند.
- خودِ 3X-UI رسمی برای همین حالت یک روش جایگزین دارد: از داخل پنل
  Settings ← Security یک «API Token» بساز و آن را به‌جای پسورد به‌صورت
  هدر Authorization: Bearer بفرست. تمام مسیرهای /panel/api/* هر دو روش
  (کوکی سشن یا Bearer Token) را قبول می‌کنند.
- پروژه‌ی mirzabot (فایل x-ui_single.php) هم دقیقاً همین روش را استفاده
  می‌کند: هیچ‌وقت /login صدا زده نمی‌شود؛ همان مقدار پسورد مستقیم به‌عنوان
  Bearer token فرستاده می‌شود. این provider هم برای هماهنگی و برای این‌که
  واقعاً کار کند، از همین روش پیروی می‌کند.

نکته‌ی مهم برای ادمین: توی فیلد «رمز عبور ادمین پنل» موقع افزودن سرور،
باید API Token (از Settings ← Security پنل 3X-UI) وارد شود، نه پسورد
واقعی ادمین. فیلد «نام کاربری» برای این نوع پنل استفاده نمی‌شود (هر
مقداری قابل قبول است).

بقیه‌ی جزئیات مثل قبل:
- هر «کلاینت» باید داخل یک inbound مشخص اضافه شود (نه مستقل)؛ به همین دلیل
  روی هر سرور یک xui_inbound_id ذخیره می‌کنیم (ادمین موقع افزودن سرور از
  بین inbound های موجود روی پنل انتخاب می‌کند).
- خودِ API لینک اشتراک برنمی‌گرداند؛ لینک از xui_sub_base_url (که ادمین وارد
  می‌کند) + یک subId تصادفی که خودمان موقع ساخت کلاینت تولید می‌کنیم ساخته
  می‌شود.
- شناسه‌ی یکتای کاربر «email» است (اینجا از همان username پروژه استفاده
  می‌شود)؛ خود کلاینت هم یک UUID جدا دارد که برای عملیات حذف لازم است.

بروزرسانی (بعد از خطای «کد 404» روی addClient):
نسخه‌های جدیدتر 3X-UI یک API کاملاً جدا و client-محور دارند:
  /panel/api/clients/add ، /panel/api/clients/del/{username} ،
  /panel/api/clients/traffic/{username} و ...
که با API قدیمیِ inbound-محور (/panel/api/inbounds/addClient که کلاینت را
داخل settings یک inbound تزریق می‌کرد) فرق دارد. مسیرهای فقط-خواندنیِ
inbound (list / get) در هر دو نسخه هنوز کار می‌کنند، به همین دلیل آن دو
درخواست موفق می‌شدند ولی addClient با 404 رد می‌شد. پروژه‌ی mirzabot
(x-ui_single.php) برای پنل‌های 3X-UI دقیقاً از همین API جدید (clients/*)
استفاده می‌کند؛ این provider هم برای هماهنگی با آن بازنویسی شد.
لیست/جزئیات inbound همچنان از /panel/api/inbounds/* خوانده می‌شود (چون
هنوز برای انتخاب inbound موقع افزودن سرور لازم است)، ولی ساخت/حذف/مصرف
کاربر حالا از /panel/api/clients/* استفاده می‌کند.

چند-inbound (multi-inbound):
- روی هر سرور به‌جای یک inbound تکی، یک لیست از id ها ذخیره می‌شود (ستون
  xui_inbound_ids، JSON array). آدمین موقع افزودن سرور (در بات/مینی‌اپ/پنل
  وب) می‌تواند چند inbound را همزمان تیک بزند.
- خودِ API جدید 3X-UI (/panel/api/clients/add) از اول هم "inboundIds" را
  به‌صورت آرایه قبول می‌کند (یک کلاینت را همزمان به چند inbound اضافه
  می‌کند)؛ قبلاً این پروژه همیشه یک آرایه‌ی تک‌عضوی می‌فرستاد، الان لیست
  کامل انتخاب‌شده فرستاده می‌شود.
- چون یک "client" واحد به چند inbound (که ممکن است پروتکل‌شان فرق کند)
  اضافه می‌شود، دیگر برای ساخت کلاینت پروتکل یک inbound خاص را حدس
  نمی‌زنیم؛ هم "id" (برای vless/vmess) و هم "password" (برای
  trojan/shadowsocks) را همزمان می‌فرستیم - فیلد اضافه‌ی بی‌ربط به هر
  پروتکل توسط پنل نادیده گرفته می‌شود، پس این کار برای هر ترکیبی از
  inbound ها امن است.
"""
import json
import secrets
import time
import uuid
import aiohttp

from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError


class ThreeXUIProvider(BasePanelProvider):

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self) -> aiohttp.ClientSession:
        """یک ClientSession با هدر Bearer token می‌سازد (بدون کوکی/لاگین).

        نکته: پنل‌های 3X-UI تقریباً همیشه با گواهی self-signed یا روی http
        بالا می‌آیند (خودِ نصب‌کننده‌ی رسمی هم گزینه‌ی رد کردن SSL را می‌دهد؛
        مثل mirzabot که در CurlRequest همه‌جا CURLOPT_SSL_VERIFYPEER را
        false می‌گذارد)، پس اینجا هم verify گواهی را غیرفعال می‌کنیم."""
        token = self.server["api_password"]
        connector = aiohttp.TCPConnector(ssl=False)
        return aiohttp.ClientSession(
            connector=connector,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=20),
        )

    async def list_inbounds(self) -> list:
        """برای فلوی افزودن سرور: لیست inbound های پنل را برمی‌گرداند تا ادمین
        یکی را انتخاب کند. هر آیتم: {id, remark, protocol, port}."""
        async with self._session() as session:
            try:
                async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                    if resp.status in (401, 403):
                        raise PanelError(
                            f"خطا در احراز هویت (کد {resp.status}): API Token اشتباه است یا "
                            "هنوز از داخل پنل (Settings ← Security) API Token نساخته‌ای."
                        )
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت لیست inbound (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        if data.get("success") is False:
            raise PanelError(data.get("msg") or "دریافت لیست inbound ناموفق بود.")
        inbounds = data.get("obj") or []
        return [
            {"id": ib["id"], "remark": ib.get("remark", ""), "protocol": ib.get("protocol", ""), "port": ib.get("port")}
            for ib in inbounds
        ]

    def _inbound_ids(self) -> list:
        """لیست id های inbound انتخاب‌شده روی این سرور. ستون جدید
        xui_inbound_ids (JSON array) اولویت دارد؛ برای سازگاری با نصب‌های
        قدیمی‌تر که فقط یک inbound (ستون تک‌مقداری xui_inbound_id) داشتند،
        اگر ستون جدید خالی بود از همان مقدار تکی استفاده می‌شود."""
        raw = self.server["xui_inbound_ids"] if "xui_inbound_ids" in self.server.keys() else None
        if raw:
            try:
                ids = json.loads(raw)
                if isinstance(ids, list) and ids:
                    return [int(i) for i in ids]
            except (ValueError, TypeError):
                pass
        legacy = self.server["xui_inbound_id"] if "xui_inbound_id" in self.server.keys() else None
        return [int(legacy)] if legacy else []

    def _build_client(self, username: str, volume_gb: int, duration_days: int) -> tuple:
        """کلاینت را می‌سازد؛ خروجی: (client_dict, sub_id)

        نکته: چون این کلاینت ممکن است همزمان به چند inbound با پروتکل‌های
        متفاوت اضافه شود، هم "id" (لازم برای vless/vmess) و هم "password"
        (لازم برای trojan/shadowsocks) را می‌فرستیم؛ پنل هنگام پردازش هر
        inbound فقط فیلد مربوط به پروتکل خودش را می‌خواند و بقیه را نادیده
        می‌گیرد. همان uuid برای هر دو استفاده می‌شود تا برای عملیات‌های دیگر
        (مثلاً ساخت لینک کانفیگ دستی به‌جای subscription) هم قابل استفاده باشد."""
        sub_id = secrets.token_hex(8)
        client_uuid = str(uuid.uuid4())
        expiry_ms = int((time.time() + duration_days * 86400) * 1000) if duration_days else 0  # 0 = بدون انقضا
        data_limit_bytes = int(volume_gb * (1024 ** 3))  # 0 = نامحدود
        client = {
            "id": client_uuid,
            "password": client_uuid,
            "email": username,
            "enable": True,
            "expiryTime": expiry_ms,
            "totalGB": data_limit_bytes,
            "limitIp": 0,
            "subId": sub_id,
            "tgId": 0,
        }
        return client, sub_id

    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
        inbound_ids = self._inbound_ids()
        sub_base_url = self.server["xui_sub_base_url"]
        if not inbound_ids or not sub_base_url:
            raise PanelError("این سرور هنوز کامل تنظیم نشده (inbound یا آدرس Subscription خالی است).")

        async with self._session() as session:
            client, sub_id = self._build_client(username, volume_gb, duration_days)
            payload = {"inboundIds": inbound_ids, "client": client}
            try:
                async with session.post(f"{self._base_url()}/panel/api/clients/add", json=payload) as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در ساخت کاربر (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e
            if data.get("success") is False:
                msg = data.get("msg") or ""
                if "duplicate" in msg.lower() or "exist" in msg.lower():
                    raise PanelUsernameTakenError(f"نام کاربری «{username}» روی پنل تکراری است")
                raise PanelError(msg or "ساخت کاربر روی پنل ناموفق بود.")

        sub_url = f"{sub_base_url.rstrip('/')}/{sub_id}"
        return PanelUserResult(username=username, subscription_url=sub_url, raw=client)

    async def delete_user(self, username: str) -> bool:
        """با API جدید دیگر نیازی به خواندن inbound و پیدا کردن client_id
        نیست؛ همان username (email) مستقیماً به مسیر حذف فرستاده می‌شود."""
        async with self._session() as session:
            try:
                async with session.post(f"{self._base_url()}/panel/api/clients/del/{username}") as resp:
                    if resp.status == 404:
                        return False
                    return resp.status < 400
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

    async def get_user_usage(self, username: str) -> dict:
        async with self._session() as session:
            try:
                async with session.get(f"{self._base_url()}/panel/api/clients/traffic/{username}") as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت اطلاعات کاربر (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        obj = data.get("obj") or {}
        used = (obj.get("up") or 0) + (obj.get("down") or 0)
        return {
            "used_bytes": used,
            "data_limit_bytes": obj.get("total", 0) or 0,
            "status": "active" if obj.get("enable") else "disabled",
        }

    async def get_user(self, username: str) -> PanelUserResult:
        """API جدید clients/* یک GET تکی برای یک کلاینت ندارد؛ کلاینت داخل
        settings همان inbound که بهش اضافه شده نگه‌داری می‌شود، پس لیست
        inbound ها را می‌خوانیم و دنبال کلاینتی با email==username می‌گردیم
        تا subId فعلی‌اش (که ممکن است ادمین دستی روی پنل عوض کرده باشد) را
        پیدا کنیم و لینک اشتراک تازه را بسازیم."""
        sub_base_url = self.server["xui_sub_base_url"]
        async with self._session() as session:
            try:
                async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت لیست inbound (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e
        if data.get("success") is False:
            raise PanelError(data.get("msg") or "دریافت اطلاعات کاربر ناموفق بود.")
        for ib in (data.get("obj") or []):
            settings_raw = ib.get("settings")
            try:
                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else (settings_raw or {})
            except (ValueError, TypeError):
                continue
            for client in (settings.get("clients") or []):
                if client.get("email") == username:
                    sub_id = client.get("subId")
                    if not sub_id or not sub_base_url:
                        raise PanelError("لینک اشتراک این کاربر روی پنل یافت نشد.")
                    sub_url = f"{sub_base_url.rstrip('/')}/{sub_id}"
                    return PanelUserResult(username=username, subscription_url=sub_url, raw=client)
        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")

    async def _find_client_with_inbound(self, session: aiohttp.ClientSession, username: str) -> tuple:
        """کلاینت با email==username و id همان inbound که در آن قرار دارد را
        برمی‌گرداند: (client_dict, inbound_id)."""
        try:
            async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                if resp.status in (401, 403):
                    raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                if resp.status >= 400:
                    text = await resp.text()
                    raise PanelError(f"خطا در دریافت لیست inbound (کد {resp.status}): {text[:300]}")
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise PanelError(f"خطا در اتصال به پنل: {e}") from e
        if data.get("success") is False:
            raise PanelError(data.get("msg") or "دریافت اطلاعات کاربر ناموفق بود.")
        for ib in (data.get("obj") or []):
            settings_raw = ib.get("settings")
            try:
                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else (settings_raw or {})
            except (ValueError, TypeError):
                continue
            for client in (settings.get("clients") or []):
                if client.get("email") == username:
                    return client, ib["id"]
        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False) -> PanelUserResult:
        sub_base_url = self.server["xui_sub_base_url"]
        async with self._session() as session:
            client, inbound_id = await self._find_client_with_inbound(session, username)

            now_ms = int(time.time() * 1000)
            current_expiry = client.get("expiryTime") or 0
            base_ms = current_expiry if current_expiry > now_ms else now_ms
            new_expiry = base_ms + add_days * 86400000 if add_days else current_expiry
            new_total = int(client.get("totalGB") or 0) + int(add_volume_gb * (1024 ** 3)) if add_volume_gb else client.get("totalGB")

            updated_client = dict(client)
            updated_client["expiryTime"] = new_expiry
            updated_client["totalGB"] = new_total
            updated_client["enable"] = True

            payload = {"id": inbound_id, "client": updated_client}
            try:
                async with session.post(
                    f"{self._base_url()}/panel/api/clients/update/{updated_client['id']}", json=payload,
                ) as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در بروزرسانی کاربر (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
                    if data.get("success") is False:
                        raise PanelError(data.get("msg") or "بروزرسانی کاربر روی پنل ناموفق بود.")
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

            if reset_usage:
                try:
                    await session.post(f"{self._base_url()}/panel/api/inbounds/{inbound_id}/resetClientTraffic/{username}")
                except aiohttp.ClientError:
                    pass

        sub_id = updated_client.get("subId")
        sub_url = f"{sub_base_url.rstrip('/')}/{sub_id}" if (sub_id and sub_base_url) else ""
        return PanelUserResult(username=username, subscription_url=sub_url, raw=updated_client)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        """چون 3X-UI endpoint مستقلی برای «revoke» ندارد، همان کلاینت را با
        clients/update به‌روزرسانی می‌کنیم: فقط id/password/subId جدید (UUID
        تازه) می‌سازیم، ولی expiryTime/totalGB را دقیقاً دست‌نخورده نگه
        می‌داریم. مصرف (traffic) بر اساس «email» (همان username) شمرده
        می‌شود، نه UUID، پس با عوض‌شدن UUID مصرف قبلی هم از بین نمی‌رود."""
        sub_base_url = self.server["xui_sub_base_url"]
        async with self._session() as session:
            client, inbound_id = await self._find_client_with_inbound(session, username)

            new_uuid = str(uuid.uuid4())
            new_sub_id = secrets.token_hex(8)
            updated_client = dict(client)
            updated_client["id"] = new_uuid
            updated_client["password"] = new_uuid
            updated_client["subId"] = new_sub_id

            payload = {"id": inbound_id, "client": updated_client}
            try:
                async with session.post(
                    f"{self._base_url()}/panel/api/clients/update/{client['id']}", json=payload,
                ) as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در قطع دسترسی/تولید لینک جدید (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
                    if data.get("success") is False:
                        raise PanelError(data.get("msg") or "قطع دسترسی/تولید لینک جدید ناموفق بود.")
            except aiohttp.ClientError as e:
                raise PanelError(f"خطا در اتصال به پنل: {e}") from e

        sub_url = f"{sub_base_url.rstrip('/')}/{new_sub_id}" if sub_base_url else ""
        return PanelUserResult(username=username, subscription_url=sub_url, raw=updated_client)

    async def test_connection(self) -> bool:
        try:
            async with self._session() as session:
                async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                    if resp.status in (401, 403):
                        return False
                    if resp.status >= 400:
                        return False
                    data = await resp.json()
                    return bool(data.get("success", True))
        except (aiohttp.ClientError, PanelError):
            return False
