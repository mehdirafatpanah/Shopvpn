#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
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
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
import asyncio
import logging
import aiohttp

from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError

logger = logging.getLogger(__name__)


class ThreeXUIProvider(BasePanelProvider):
    supports_user_limit = True
    supports_online_status = True

    def _base_url(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self) -> aiohttp.ClientSession:
        """یک ClientSession با هدر Bearer token می‌سازد (بدون کوکی/لاگین).

        نکته: پنل‌های 3X-UI تقریباً همیشه با گواهی self-signed یا روی http
        بالا می‌آیند (خودِ نصب‌کننده‌ی رسمی هم گزینه‌ی رد کردن SSL را می‌دهد؛
        مثل mirzabot که در CurlRequest همه‌جا CURLOPT_SSL_VERIFYPEER را
        false می‌گذارد)، پس اینجا هم verify گواهی را غیرفعال می‌کنیم."""
        token = self.server["api_password"]
        connector = self._build_connector()
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

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

    async def _live_inbounds(self, session: aiohttp.ClientSession) -> list:
        """لیست زنده‌ی inbound های پنل: [{id, remark, protocol, port}, ...].
        اگر خواندن لیست ممکن نباشد (خطای شبکه/احراز هویت)، None برمی‌گرداند تا
        فراخوان بتواند بدون اعتبارسنجی ادامه دهد و خطای واقعی پنل را نشان بدهد."""
        try:
            async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("success") is False:
            return None
        out = []
        for ib in (data.get("obj") or []):
            if isinstance(ib, dict) and ib.get("id") is not None:
                out.append({"id": int(ib["id"]), "remark": ib.get("remark", ""),
                            "protocol": ib.get("protocol", ""), "port": ib.get("port")})
        return out

    async def _resolve_inbound_ids(self, session: aiohttp.ClientSession, wanted: list) -> list:
        """رفع باگ «inbound N: record not found»: شناسه‌ی inbound ذخیره‌شده روی سرور/محصول
        ممکن است دیگر روی پنل وجود نداشته باشد (inbound حذف/دوباره ساخته شده یا دیتابیس پنل
        عوض شده)؛ آن‌وقت پنل کل ساخت کلاینت را رد می‌کرد. اینجا قبل از ساخت، شناسه‌ها با
        لیست زنده‌ی پنل تطبیق داده می‌شوند:
        - شناسه‌های ناموجود حذف می‌شوند و ساخت با بقیه ادامه پیدا می‌کند (لاگ هشدار)؛
        - اگر هیچ‌کدام وجود نداشت، خطای روشن به‌همراه inbound های موجود پنل داده می‌شود."""
        live = await self._live_inbounds(session)
        if live is None:
            return wanted
        live_ids = {ib["id"] for ib in live}
        valid = [i for i in wanted if i in live_ids]
        missing = [i for i in wanted if i not in live_ids]
        if missing and valid:
            logger.warning("3x-ui سرور #%s: inbound های %s روی پنل وجود ندارند و نادیده گرفته شدند؛ ساخت با %s ادامه یافت.",
                           self.server["id"] if "id" in self.server.keys() else "?", missing, valid)
        if not valid:
            available = "، ".join(
                f"#{ib['id']} ({ib['remark'] or ib['protocol']}:{ib['port']})" for ib in live
            ) or "هیچ inbound ای روی پنل نیست"
            raise PanelError(
                "inbound انتخاب‌شده (" + "، ".join(f"#{i}" for i in wanted) + ") دیگر روی پنل 3X-UI وجود ندارد "
                "(احتمالاً حذف یا دوباره ساخته شده). از تنظیمات سرور پنل یا محصول، inbound را دوباره انتخاب کن. "
                f"inbound های موجود: {available}"
            )
        return valid

    def _build_client(self, username: str, volume_gb: int, duration_days: int, user_limit: int = 0) -> tuple:
        """کلاینت را می‌سازد؛ خروجی: (client_dict, sub_id)

        نکته: چون این کلاینت ممکن است همزمان به چند inbound با پروتکل‌های
        متفاوت اضافه شود، هم "id" (لازم برای vless/vmess) و هم "password"
        (لازم برای trojan/shadowsocks) را می‌فرستیم؛ پنل هنگام پردازش هر
        inbound فقط فیلد مربوط به پروتکل خودش را می‌خواند و بقیه را نادیده
        می‌گیرد. همان uuid برای هر دو استفاده می‌شود تا برای عملیات‌های دیگر
        (مثلاً ساخت لینک کانفیگ دستی به‌جای subscription) هم قابل استفاده باشد."""
        sub_id = secrets.token_hex(8)
        client_uuid = str(uuid.uuid4())
        start_on_first_use = bool(self.server["start_on_first_use"]) if "start_on_first_use" in self.server.keys() else False
        expiry_ms = (-int(duration_days * 86400000)) if duration_days and start_on_first_use else (int((time.time() + duration_days * 86400) * 1000) if duration_days else 0)  # 0 = بدون انقضا
        data_limit_bytes = int(volume_gb * (1024 ** 3))  # 0 = نامحدود
        client = {
            "id": client_uuid,
            "password": client_uuid,
            "email": username,
            "enable": True,
            "expiryTime": expiry_ms,
            "totalGB": data_limit_bytes,
            "limitIp": int(user_limit or 0),
            "subId": sub_id,
            "tgId": 0,
        }
        return client, sub_id

    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False,
                           user_limit: int = 0) -> PanelUserResult:
        inbound_ids = self._inbound_ids()
        sub_base_url = self.server["xui_sub_base_url"]
        if not inbound_ids or not sub_base_url:
            raise PanelError("این سرور هنوز کامل تنظیم نشده (inbound یا آدرس Subscription خالی است).")

        async with self._session() as session:
            inbound_ids = await self._resolve_inbound_ids(session, inbound_ids)
            client, sub_id = self._build_client(username, volume_gb, duration_days, user_limit)
            payload = {"inboundIds": inbound_ids, "client": client}
            try:
                async with session.post(f"{self._base_url()}/panel/api/clients/add", json=payload) as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در ساخت کاربر (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
            if data.get("success") is False:
                msg = data.get("msg") or ""
                if "duplicate" in msg.lower() or "exist" in msg.lower() or "already in use" in msg.lower():
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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

        obj = data.get("obj") or {}
        used = (obj.get("up") or 0) + (obj.get("down") or 0)
        expiry = obj.get("expiryTime")
        try:
            expiry = int(expiry) if expiry is not None else 0
        except (TypeError, ValueError):
            expiry = 0
        return {
            "used_bytes": used,
            "data_limit_bytes": obj.get("total", 0) or 0,
            "status": "active" if obj.get("enable") else "disabled",
            "expires_at": (expiry / 1000.0) if expiry > 10000 else None,
        }

    async def is_client_online(self, username: str) -> bool:
        """وضعیت آنلاین/آفلاین همین لحظه‌ی کاربر را از /panel/api/inbounds/onlines
        می‌خواند (همان endpoint‌ای که در get_panel_stats برای شمارش کاربران آنلاین
        استفاده می‌شود). این یک وضعیت لحظه‌ای است، نه تاریخچه‌ی آخرین اتصال."""
        async with self._session() as session:
            try:
                async with session.post(f"{self._base_url()}/panel/api/inbounds/onlines") as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise PanelError(f"خطا در دریافت لیست آنلاین‌ها (کد {resp.status}): {text[:300]}")
                    data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
        if data.get("success") is False:
            raise PanelError(data.get("msg") or "دریافت لیست آنلاین‌ها ناموفق بود.")
        online_emails = set(data.get("obj") or [])
        return username in online_emails

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
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
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

    async def find_username_by_sub_id(self, sub_id: str):
        """email کلاینتی که subId آن برابر sub_id است (یا None)."""
        async with self._session() as session:
            try:
                async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                    if resp.status >= 400:
                        raise PanelError(f"خطا در دریافت لیست inbound (کد {resp.status}).")
                    data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PanelError(f"خطا در اتصال به پنل: {e or 'timeout'}") from e
        for ib in (data.get("obj") or []):
            raw = ib.get("settings")
            try:
                settings = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (ValueError, TypeError):
                continue
            for client in (settings.get("clients") or []):
                if client.get("subId") == sub_id and client.get("email"):
                    return client["email"]
        return None

    async def _find_client_all_inbounds(self, session: aiohttp.ClientSession, username: str) -> list:
        """همه‌ی نسخه‌های کلاینت با email==username را در تمام inbound هایی
        که کلاینت در آن‌ها ثبت شده برمی‌گرداند: [(client_dict, inbound_id), ...].

        نکته‌ی مهم (رفع باگ): چون از پنل می‌شود یک کانفیگ را همزمان روی چند
        inbound ساخت (به همان قابلیت «چند inbound» که در create_user هست)،
        نباید فقط به اولین match بسنده کرد؛ وگرنه در توابعی مثل
        revoke_credentials/update_user/set_enabled/rename_user فقط یکی از
        inbound ها به‌روزرسانی می‌شد و در بقیه، مقدار/UUID قدیمی همچنان معتبر
        می‌ماند (مثلاً «قطع دسترسی» واقعاً کامل انجام نمی‌شد)."""
        try:
            async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                if resp.status in (401, 403):
                    raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                if resp.status >= 400:
                    text = await resp.text()
                    raise PanelError(f"خطا در دریافت لیست inbound (کد {resp.status}): {text[:300]}")
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise PanelError(f"خطا در اتصال به پنل: {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e
        if data.get("success") is False:
            raise PanelError(data.get("msg") or "دریافت اطلاعات کاربر ناموفق بود.")
        matches = []
        for ib in (data.get("obj") or []):
            settings_raw = ib.get("settings")
            try:
                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else (settings_raw or {})
            except (ValueError, TypeError):
                continue
            for client in (settings.get("clients") or []):
                if client.get("email") == username:
                    matches.append((client, ib["id"]))
        if not matches:
            raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
        return matches

    async def _post_client_update(self, session: aiohttp.ClientSession, url_client_id: str,
                                   inbound_id, updated_client: dict, action_label: str) -> dict:
        """یک درخواست update به ازای یک (client, inbound) می‌فرستد؛ برای
        استفاده‌ی مشترک در حلقه‌ی روی چند inbound.

        نکته (رفع باگ): endpoint جدید /panel/api/clients/update/{email} بدنه‌ی
        flat خودِ فیلدهای کلاینت را می‌خواهد، نه {"id": inbound_id, "client": ...}.
        فرستادن inbound_id (عدد) داخل کلید "id" باعث خطای
        'cannot unmarshal number into Go struct field .id of type string' می‌شد،
        چون آن endpoint فیلد id را رشته (uuid کلاینت) فرض می‌کند. همچنین شناسه‌ی
        داخل URL باید ایمیل (username) باشد، نه client["id"]."""
        payload = updated_client
        try:
            async with session.post(
                f"{self._base_url()}/panel/api/clients/update/{url_client_id}", json=payload,
            ) as resp:
                if resp.status in (401, 403):
                    raise PanelError(f"خطا در احراز هویت (کد {resp.status}): API Token را بررسی کن.")
                if resp.status >= 400:
                    text = await resp.text()
                    raise PanelError(f"خطا در {action_label} (inbound {inbound_id}, کد {resp.status}): {text[:300]}")
                data = await resp.json()
                if data.get("success") is False:
                    raise PanelError(f"{action_label} ناموفق بود (inbound {inbound_id}): {data.get('msg') or ''}")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise PanelError(f"خطا در اتصال به پنل (inbound {inbound_id}): {e or 'پاسخی از سرور در زمان مقرر دریافت نشد (timeout)'}") from e

    supports_data_limit_sync = True

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط totalGB کلاینت را روی همه‌ی inbound ها عوض می‌کند (انقضا/مصرف دست‌نخورده).
        reenable=True یعنی پنل کلاینت را چون به سقف رسیده بود خودش غیرفعال کرده و حالا
        که سقف بالاتر رفته باید دوباره فعال شود."""
        async with self._session() as session:
            matches = await self._find_client_all_inbounds(session, username)
            for client, inbound_id in matches:
                updated = dict(client)
                updated["totalGB"] = int(limit_bytes)
                if reenable:
                    updated["enable"] = True
                await self._post_client_update(session, username, inbound_id, updated, "اعمال سقف حجم")

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False,
                           user_limit: int = None) -> PanelUserResult:
        sub_base_url = self.server["xui_sub_base_url"]
        used_bytes = 0
        if reset_usage and preserve_remaining and add_volume_gb:
            try:
                used_bytes = (await self.get_user_usage(username)).get("used_bytes", 0) or 0
            except PanelError:
                used_bytes = 0
        async with self._session() as session:
            matches = await self._find_client_all_inbounds(session, username)

            now_ms = int(time.time() * 1000)
            updated_client = None
            for client, inbound_id in matches:
                current_expiry = client.get("expiryTime") or 0
                try:
                    current_expiry = int(current_expiry)
                except (TypeError, ValueError):
                    current_expiry = 0
                is_on_hold = current_expiry < -10000
                if is_on_hold:
                    new_expiry = current_expiry - (add_days * 86400000) if add_days else current_expiry
                else:
                    base_ms = current_expiry if current_expiry > now_ms else now_ms
                    new_expiry = base_ms + add_days * 86400000 if add_days else current_expiry
                # تمدید «کامل» (reset_usage=True) دو حالت دارد: پیش‌فرض (preserve_remaining=False)
                # سقف حجم را با بستهٔ تازه جایگزین می‌کند، وگرنه حجم باقیمانده‌ی قبلی هم به
                # اشتباه به سقف جدید اضافه می‌شود. اگر preserve_remaining=True باشد (تمدید کامل
                # دستی)، حجم باقیمانده‌ی مصرف‌نشده (بر اساس مصرف واقعی خوانده‌شده از traffic‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
                # endpoint) حفظ و بستهٔ جدید رویش اضافه می‌شود. تمدید «افزایشی»
                # (reset_usage=False) همیشه روی سقف قبلی جمع می‌زند.
                if unlimited_volume:
                    new_total = 0  # 0 = نامحدود
                elif reset_usage and preserve_remaining:
                    remaining = max(int(client.get("totalGB") or 0) - int(used_bytes or 0), 0)
                    new_total = remaining + int(add_volume_gb * (1024 ** 3))
                elif add_volume_gb:
                    new_total = int(add_volume_gb * (1024 ** 3)) if reset_usage else int(client.get("totalGB") or 0) + int(add_volume_gb * (1024 ** 3))
                else:
                    new_total = client.get("totalGB")

                updated_client = dict(client)
                updated_client["expiryTime"] = new_expiry
                updated_client["totalGB"] = new_total
                updated_client["enable"] = True
                if user_limit is not None:
                    updated_client["limitIp"] = int(user_limit)

                await self._post_client_update(
                    session, username, inbound_id, updated_client, "بروزرسانی کاربر",
                )

                if reset_usage:
                    try:
                        await session.post(f"{self._base_url()}/panel/api/inbounds/{inbound_id}/resetClientTraffic/{username}")
                    except aiohttp.ClientError:
                        pass

        sub_id = updated_client.get("subId")
        sub_url = f"{sub_base_url.rstrip('/')}/{sub_id}" if (sub_id and sub_base_url) else ""
        return PanelUserResult(username=username, subscription_url=sub_url, raw=updated_client)

    supports_fingerprints = True

    async def get_fingerprints(self, username: str) -> list:
        """id، password و subId کلاینت را از همه‌ی inbound ها می‌خواند (برای ایندکس تشخیص نشت)."""
        async with self._session() as session:
            matches = await self._find_client_all_inbounds(session, username)
        values = []
        for client, _inbound_id in matches:
            for key in ("id", "password", "subId"):
                value = client.get(key)
                if value:
                    values.append(str(value))
        return list(dict.fromkeys(values))

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        """چون 3X-UI endpoint مستقلی برای «revoke» ندارد، همان کلاینت را با
        clients/update به‌روزرسانی می‌کنیم: فقط id/password/subId جدید (UUID
        تازه) می‌سازیم، ولی expiryTime/totalGB را دقیقاً دست‌نخورده نگه
        می‌داریم. مصرف (traffic) بر اساس «email» (همان username) شمرده
        می‌شود، نه UUID، پس با عوض‌شدن UUID مصرف قبلی هم از بین نمی‌رود."""
        sub_base_url = self.server["xui_sub_base_url"]
        async with self._session() as session:
            matches = await self._find_client_all_inbounds(session, username)

            # یک UUID/subId مشترک برای همه‌ی inbound ها می‌سازیم (نه جدا-جدا)،
            # چون subId پایه‌ی لینک subscription تجمیعی است و اگر هر inbound
            # subId متفاوتی می‌گرفت، یک لینک واحد دیگر همه‌ی کانفیگ‌ها را‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
            # پوشش نمی‌داد.
            new_uuid = str(uuid.uuid4())
            new_sub_id = secrets.token_hex(8)

            updated_client = None
            for client, inbound_id in matches:
                updated_client = dict(client)
                updated_client["id"] = new_uuid
                updated_client["password"] = new_uuid
                updated_client["subId"] = new_sub_id

                # مهم: باید روی *همه‌ی* inbound هایی که این کانفیگ در آن‌ها ثبت
                # شده UUID عوض شود، وگرنه در inbound های دیگر لینک/UUID قدیمی
                # همچنان معتبر می‌ماند و دسترسی واقعاً قطع نمی‌شود.
                await self._post_client_update(
                    session, username, inbound_id, updated_client, "قطع دسترسی/تولید لینک جدید",
                )

        sub_url = f"{sub_base_url.rstrip('/')}/{new_sub_id}" if sub_base_url else ""
        return PanelUserResult(username=username, subscription_url=sub_url, raw=updated_client)

    async def set_enabled(self, username: str, enabled: bool) -> None:
        async with self._session() as session:
            matches = await self._find_client_all_inbounds(session, username)
            for client, inbound_id in matches:
                updated_client = dict(client)
                updated_client["enable"] = bool(enabled)
                await self._post_client_update(
                    session, username, inbound_id, updated_client, "تغییر وضعیت کاربر",
                )

    async def rename_user(self, username: str, new_username: str) -> None:
        """چون traffic روی 3X-UI بر اساس فیلد email شمرده می‌شود، تغییر آن
        باعث می‌شود مصرف قبلی زیر email جدید دیده نشود (خودِ حجم/انقضای
        کلاینت دست‌نخورده می‌ماند، فقط شمارنده‌ی مصرف روی پنل صفر به‌نظر
        می‌رسد)."""
        async with self._session() as session:
            matches = await self._find_client_all_inbounds(session, username)
            for client, inbound_id in matches:
                updated_client = dict(client)
                updated_client["email"] = new_username
                await self._post_client_update(
                    session, username, inbound_id, updated_client, "تغییر نام کاربر",
                )

    async def test_connection(self) -> bool:
        try:
            async with self._session() as session:
                async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                    if resp.status in (401, 403):
                        self.last_error = f"احراز هویت پنل ناموفق بود (کد {resp.status})؛ نام کاربری و رمز را بررسی کنید."
                        return False
                    if resp.status >= 400:
                        self.last_error = f"پاسخ پنل با کد {resp.status}؛ آدرس یا مسیر پنل را بررسی کنید."
                        return False
                    data = await resp.json()
                    if not data.get("success", True):
                        self.last_error = "پنل پاسخ ناموفق (success=false) برگرداند."
                        return False
                    return True
        except aiohttp.ClientError as e:
            self.last_error = f"خطا در اتصال به پنل: {e}"
            return False
        except PanelError as e:
            self.last_error = str(e)
            return False

    async def backup_panel(self) -> tuple:
        """دیتابیس sqlite پنل (x-ui.db) را از /panel/api/server/getDb دانلود می‌کند.
        خروجی: (bytes دیتابیس, نام فایل پیشنهادی)."""
        try:
            async with self._session() as session:
                async with session.get(f"{self._base_url()}/panel/api/server/getDb") as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"احراز هویت پنل ناموفق بود (کد {resp.status}).")
                    if resp.status >= 400:
                        raise PanelError(f"دریافت بکاپ ناموفق بود (کد {resp.status}).")
                    data = await resp.read()
                    if not data:
                        raise PanelError("پنل فایل خالی برگرداند.")
                    return data, "x-ui.db"
        except aiohttp.ClientError as e:
            raise PanelError(f"خطا در اتصال به پنل: {e}")

    async def restore_panel(self, file_bytes: bytes) -> None:
        """دیتابیس sqlite داده‌شده را با /panel/api/server/importDB جایگزین دیتابیس فعلی پنل
        می‌کند (پنل بعد از این عملیات خودش Xray را ری‌استارت می‌کند).

        نکته: این درخواست باید بدون هدر ثابت Content-Type: application/json سشن معمولی
        ارسال شود (وگرنه aiohttp نمی‌تواند Content-Type چندبخشی/boundary خودش را
        جایگزین کند)، پس اینجا یک سشن جداگانه فقط با هدر Authorization ساخته می‌شود."""
        token = self.server["api_password"]
        connector = self._build_connector()
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as session:
                form = aiohttp.FormData()
                form.add_field("db", file_bytes, filename="x-ui.db", content_type="application/octet-stream")
                async with session.post(f"{self._base_url()}/panel/api/server/importDB", data=form) as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"احراز هویت پنل ناموفق بود (کد {resp.status}).")
                    if resp.status >= 400:
                        raise PanelError(f"بازیابی ناموفق بود (کد {resp.status}).")
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, ValueError):
                        return
                    if isinstance(data, dict) and not data.get("success", True):
                        raise PanelError(data.get("msg") or "پنل پاسخ ناموفق برگرداند.")
        except aiohttp.ClientError as e:
            raise PanelError(f"خطا در اتصال به پنل: {e}")

    async def get_panel_stats(self) -> dict:
        """آمار کلی پنل: تعداد inbound، کل کاربران، آنلاین‌ها، منقضی‌شده‌ها و غیرفعال‌شده‌ها.
        از /panel/api/inbounds/list (که clientStats هر inbound را هم برمی‌گرداند) و
        /panel/api/inbounds/onlines (لیست ایمیل کاربران آنلاین) خوانده می‌شود."""
        try:
            async with self._session() as session:
                async with session.get(f"{self._base_url()}/panel/api/inbounds/list") as resp:
                    if resp.status in (401, 403):
                        raise PanelError(f"احراز هویت پنل ناموفق بود (کد {resp.status}).")
                    if resp.status >= 400:
                        raise PanelError(f"دریافت اطلاعات پنل ناموفق بود (کد {resp.status}).")
                    data = await resp.json()
                if data.get("success") is False:
                    raise PanelError(data.get("msg") or "دریافت اطلاعات inbound ناموفق بود.")
                inbounds = data.get("obj") or []

                online_emails = set()
                try:
                    async with session.post(f"{self._base_url()}/panel/api/inbounds/onlines") as resp2:
                        if resp2.status < 400:
                            data2 = await resp2.json()
                            if data2.get("success", True):
                                online_emails = set(data2.get("obj") or [])
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
        except aiohttp.ClientError as e:
            raise PanelError(f"خطا در اتصال به پنل: {e}")

        now_ms = int(time.time() * 1000)
        seen_emails = set()
        total_clients = 0
        expired_clients = 0
        disabled_clients = 0
        online_count = 0
        for ib in inbounds:
            for c in (ib.get("clientStats") or []):
                email = c.get("email")
                if not email or email in seen_emails:
                    continue
                seen_emails.add(email)
                total_clients += 1
                if not c.get("enable", True):
                    disabled_clients += 1
                expiry = c.get("expiryTime") or 0
                if expiry and expiry < now_ms:
                    expired_clients += 1
                if email in online_emails:
                    online_count += 1

        return {
            "inbound_count": len(inbounds),
            "total_clients": total_clients,
            "online_clients": online_count,
            "expired_clients": expired_clients,
            "disabled_clients": disabled_clients,
        }
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
