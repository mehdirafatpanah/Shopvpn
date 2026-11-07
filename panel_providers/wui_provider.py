"""Provider پنل W-UI (WireGuard/AmneziaWG/OpenVPN و ورود با نام‌کاربری: OpenConnect/L2TP/PPTP/IKEv2): API Token با هدر Bearer؛ interfaceها از روی کاربر نمونه یا انتخاب محصول تعیین میشوند."""
import asyncio
import io
import re
import time
import zipfile
from datetime import datetime, timezone

import aiohttp

from ._http import new_session, request_json, http_error, load_json, gb_to_bytes, new_limit_bytes
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError

_PER_PAGE = 200
_MAX_PAGES = 25
_STATUS = {"active": "active", "disabled": "disabled", "expired": "expired", "exhausted": "limited"}
_FRACTION = re.compile(r"\.(\d+)")
_AWG_MARK = re.compile(r"^\s*Jc\s*=", re.M)
_ZIP_MAX_BYTES = 4 * 1024 * 1024
_ZIP_MAX_FILES = 60


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(value) -> int:
    if not value:
        return 0
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), str(value)).replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return 0


def classify_profile(filename: str, text: str) -> str:
    """نوع فایل کانفیگ W-UI: wireguard / amneziawg / openvpn / other."""
    if filename.lower().endswith(".ovpn") or ("<ca>" in text and "remote " in text):
        return "openvpn"
    if "[Interface]" in text and "PrivateKey" in text:
        return "amneziawg" if _AWG_MARK.search(text) else "wireguard"
    return "other"


# پروتکل‌هایی که فایل کانفیگ ندارند و کاربر نام‌کاربری/رمز (و گاهی PSK) را داخل دستگاه تایپ می‌کند.
LOGIN_PROTOCOLS = ("openconnect", "l2tp", "pptp", "ikev2")
_LOGIN_ORDER = {name: pos for pos, name in enumerate(LOGIN_PROTOCOLS)}
_STD_PORT = {"l2tp": 1701, "pptp": 1723, "ikev2": 500}


def _oc_url(host: str, port: int, camouflage: bool, secret: str) -> str:
    """همان آدرسی که دستگاه می‌زند (مثل occonf.URL پنل): هاست، پورت اگر 443 نبود، و «/?راز» برای camouflage."""
    h = host
    if ":" in h and not h.startswith("["):
        h = f"[{h}]"
    out = h
    if int(port or 443) != 443:
        out += f":{int(port)}"
    if camouflage and secret:
        out += f"/?{secret}"
    return out


def login_profile(account: dict, iface: dict) -> dict:
    """یک ردیف ورودیِ نام‌کاربری/رمز را از حساب و interface پنل W-UI می‌سازد؛ برای پروتکل‌های دیگر None."""
    protocol = str(iface.get("protocol") or "").lower()
    if protocol not in LOGIN_PROTOCOLS or account.get("enabled") is False:
        return None
    host = str(iface.get("endpointHost") or "").strip()
    port = int(iface.get("listenPort") or 0)
    item = {
        "kind": protocol,
        "tunnel": str(iface.get("name") or ""),
        "device": str(account.get("deviceName") or ""),
        "server": host,
        "username": str(account.get("username") or ""),
        "password": str(account.get("password") or ""),
        "own_port": port if protocol in _STD_PORT and port and port != _STD_PORT[protocol] else 0,
    }
    if protocol == "l2tp":
        params = iface.get("l2tp") or {}
        item["psk"] = str(params.get("psk") or "")
        item["allow_plain"] = bool(params.get("allowPlain"))
    elif protocol == "ikev2":
        params = iface.get("ikev2") or {}
        names = [n for n in params.get("serverNames") or [] if n]
        item["modes"] = [m for m, on in (("mschapv2", params.get("mschapv2")), ("psk", params.get("psk")),
                                         ("rsa", params.get("rsa")), ("eap-tls", params.get("eapTls"))) if on]
        item["server_id"] = names[0] if names else host
        item["ca_cert"] = str(params.get("caCert") or "")
    elif protocol == "openconnect":
        params = iface.get("openconnect") or {}
        item["address"] = _oc_url(host, port, bool(params.get("camouflage")), str(params.get("camouflageSecret") or ""))
        item["dtls"] = bool(params.get("dtls"))
    if not item["username"] or not item["password"]:
        return None
    return item


class WUIProvider(BasePanelProvider):

    def _base(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self):
        headers = {"Authorization": f"Bearer {self.server['api_password']}", "Accept": "application/json"}
        return new_session(headers=headers, server=self.server)

    async def _api(self, session, method: str, path: str, action: str, **kwargs):
        status, data, text = await request_json(session, method, f"{self._base()}/api/{path}", **kwargs)
        if status >= 400:
            detail = data.get("error") if isinstance(data, dict) else None
            if detail:
                raise PanelError(f"خطا در {action} (کد {status}): {str(detail)[:300]}")
            raise http_error(action, status, text)
        return data

    def _interface_ids(self) -> list:
        ids = load_json(self.server["group_ids"])
        if not isinstance(ids, list) or not ids:
            raise PanelError("interface های این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن.")
        return [int(i) for i in ids]

    async def _lookup(self, session, username: str):
        for page in range(1, _MAX_PAGES + 1):
            data = await self._api(
                session, "GET", "clients", "دریافت لیست کاربران",
                params={"search": username, "page": page, "perPage": _PER_PAGE},
            )
            data = data if isinstance(data, dict) else {}
            for item in data.get("items") or []:
                if item.get("name") == username:
                    return item
            if page * _PER_PAGE >= int(data.get("total") or 0):
                break
        return None

    async def _find(self, session, username: str) -> dict:
        client = await self._lookup(session, username)
        if client is None:
            raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
        return client

    async def _full(self, session, client_id) -> dict:
        data = await self._api(session, "GET", f"clients/{client_id}", "دریافت اطلاعات کاربر")
        if not isinstance(data, dict):
            raise PanelError("پاسخ نامعتبر از پنل در دریافت اطلاعات کاربر.")
        return data

    async def _link(self, session, client_id) -> str:
        data = await self._api(session, "GET", f"clients/{client_id}/subscription", "دریافت لینک اشتراک")
        link = data.get("link") if isinstance(data, dict) else ""
        if not link:
            raise PanelError("لینک اشتراک از W-UI دریافت نشد؛ سرویس Subscription را در پنل فعال کن.")
        return link

    @staticmethod
    def _account_interfaces(client: dict) -> list:
        return sorted({int(a["interfaceId"]) for a in client.get("accounts") or [] if a.get("interfaceId")})

    async def list_product_targets(self):
        """فهرست interface های W-UI (WireGuard/AmneziaWG/OpenVPN) را از API میخواند."""
        async with self._session() as session:
            data = await self._api(session, "GET", "interfaces", "دریافت فهرست interfaceها")
        items = data.get("items") if isinstance(data, dict) else data
        choices = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("id") is not None:
                label = f'{item.get("name") or item["id"]} · {item.get("protocol") or ""}'.strip(" ·")
                choices.append({"value": str(item["id"]), "label": label})
        if not choices:
            raise PanelError("هیچ interface قابل انتخابی از W-UI دریافت نشد.")
        return {"field": "group_ids", "kind": "list", "choices": choices}

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        async with self._session() as session:
            client = await self._full(session, (await self._find(session, sample_username))["id"])
        ids = self._account_interfaces(client)
        if not ids:
            raise PanelError("کاربر نمونه هیچ interface ای ندارد؛ از یک کاربر دیگر امتحان کن.")
        return {"group_ids": ids, "proxy_settings": {}}

    supports_user_limit = True

    async def create_user(self, username: str, volume_gb: int, duration_days: int, start_on_first_use: bool = False,
                           user_limit: int = 0) -> PanelUserResult:
        interface_ids = self._interface_ids()
        first_use = bool(self.server["start_on_first_use"]) if "start_on_first_use" in self.server.keys() else bool(start_on_first_use)
        body = {
            "name": username,
            "note": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
            "interfaceIds": interface_ids,
            "quotaBytes": gb_to_bytes(volume_gb) if volume_gb else 0,
            "deviceLimit": int(user_limit) if user_limit and int(user_limit) > 0 else 1,
        }
        if duration_days and first_use:
            body["startOnFirstUse"] = True
            body["durationDays"] = int(duration_days)
        elif duration_days:
            body["expiresAt"] = _iso(time.time() + int(duration_days) * 86400)
        async with self._session() as session:
            if await self._lookup(session, username) is not None:
                raise PanelUsernameTakenError(f"نام کاربری «{username}» روی پنل تکراری است")
            created = await self._api(session, "POST", "clients", "ساخت کاربر", json=body)
            if not isinstance(created, dict) or not created.get("id"):
                raise PanelError("پاسخ نامعتبر از پنل در ساخت کاربر.")
            try:
                link = await self._link(session, created["id"])
            except PanelError:
                try:
                    await self._api(session, "DELETE", f"clients/{created['id']}", "پاکسازی")
                except PanelError:
                    pass
                raise
        return PanelUserResult(username=username, subscription_url=link, raw=created)

    async def delete_user(self, username: str) -> bool:
        async with self._session() as session:
            client = await self._lookup(session, username)
            if client is None:
                return False
            await self._api(session, "DELETE", f"clients/{client['id']}", "حذف کاربر")
        return True

    async def get_user_usage(self, username: str) -> dict:
        async with self._session() as session:
            client = await self._find(session, username)
        return {
            "used_bytes": int(client.get("usedBytes") or 0),
            "data_limit_bytes": int(client.get("quotaBytes") or 0),
            "status": _STATUS.get(str(client.get("status")), "active"),
        }

    async def get_user(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            client = await self._find(session, username)
            link = await self._link(session, client["id"])
        return PanelUserResult(username=username, subscription_url=link, raw=client)

    supports_data_limit_sync = True

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط سقف حجم (quotaBytes) مشتری را عوض میکند؛ 0 = نامحدود."""
        async with self._session() as session:
            client = await self._find(session, username)
            patch = {"quotaBytes": int(limit_bytes)}
            if reenable:
                patch["status"] = "active"
            await self._api(session, "PATCH", f"clients/{client['id']}", "اعمال سقف حجم", json=patch)

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False, user_limit: int = None) -> PanelUserResult:
        async with self._session() as session:
            client = await self._find(session, username)
            client_id = client["id"]
            used = int(client.get("usedBytes") or 0)
            current = int(client.get("quotaBytes") or 0)
            new_limit = new_limit_bytes(current, used, add_volume_gb, reset_usage, preserve_remaining,
                                         unlimited=unlimited_volume)
            patch = {"status": "active"}
            if new_limit != current:
                patch["quotaBytes"] = new_limit
            if user_limit is not None and int(user_limit) > 0:
                patch["deviceLimit"] = int(user_limit)
            if add_days:
                expires = _epoch(client.get("expiresAt"))
                if client.get("startOnFirstUse") and not expires:
                    patch["durationDays"] = int(client.get("durationDays") or 0) + int(add_days)
                else:
                    patch["expiresAt"] = _iso(max(expires, int(time.time())) + int(add_days) * 86400)
            if reset_usage:
                await self._api(session, "POST", f"clients/{client_id}/reset", "ریست مصرف")
            await self._api(session, "PATCH", f"clients/{client_id}", "بروزرسانی کاربر", json=patch)
            link = await self._link(session, client_id)
        return PanelUserResult(username=username, subscription_url=link, raw=client)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            client = await self._find(session, username)
            data = await self._api(
                session, "POST", f"clients/{client['id']}/rotate-keys", "قطع دسترسی/تولید لینک جدید",
                json={"subToken": True},
            )
            link = data.get("link") if isinstance(data, dict) else ""
            if not link:
                link = await self._link(session, client["id"])
        return PanelUserResult(username=username, subscription_url=link, raw=client)

    async def set_enabled(self, username: str, enabled: bool) -> None:
        async with self._session() as session:
            client = await self._find(session, username)
            await self._api(
                session, "PATCH", f"clients/{client['id']}", "تغییر وضعیت کاربر",
                json={"status": "active" if enabled else "disabled"},
            )

    async def rename_user(self, username: str, new_username: str) -> str:
        async with self._session() as session:
            client = await self._find(session, username)
            if await self._lookup(session, new_username) is not None:
                raise PanelUsernameTakenError(f"نام کاربری «{new_username}» روی پنل تکراری است")
            await self._api(session, "PATCH", f"clients/{client['id']}", "تغییر نام کاربر", json={"name": new_username})
        return None

    supports_online_status = True

    async def is_client_online(self, username: str) -> bool:
        async with self._session() as session:
            client = await self._find(session, username)
        return int(client.get("onlineNow") or 0) > 0

    supports_template_resync = True

    async def resync_user_template(self, username: str) -> bool:
        """interface های مشتری را با قالب فعلی سرور در ربات یکی میکند."""
        target = sorted(self._interface_ids())
        async with self._session() as session:
            client = await self._full(session, (await self._find(session, username))["id"])
            if self._account_interfaces(client) == target:
                return False
            await self._api(
                session, "PATCH", f"clients/{client['id']}", "همگام‌سازی interface کاربر",
                json={"interfaceIds": target},
            )
        return True

    async def get_config_files(self, username: str) -> list:
        """همه‌ی فایل‌های کانفیگ مشتری (هر دستگاه × هر host) از زیپ W-UI: [{filename, text, kind}]."""
        async with self._session() as session:
            client = await self._find(session, username)
            url = f"{self._base()}/api/clients/{client['id']}/configs"
            try:
                async with session.request("GET", url, params={"format": "zip"}) as resp:
                    raw = await resp.read()
                    status = resp.status
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise PanelError(f"خطا در اتصال به پنل: {exc or 'timeout'}") from exc
        if status >= 400:
            raise http_error("دریافت فایل‌های کانفیگ", status, raw[:300].decode("utf-8", errors="replace"))
        if len(raw) > _ZIP_MAX_BYTES:
            raise PanelError("زیپ کانفیگ‌های W-UI بیش از حد بزرگ است.")
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise PanelError("پاسخ W-UI زیپ معتبر نبود.") from exc
        files = []
        with archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename)[:_ZIP_MAX_FILES]:
                if info.is_dir() or info.file_size > _ZIP_MAX_BYTES:
                    continue
                name = re.sub(r"[^A-Za-z0-9_.-]", "_", info.filename.rsplit("/", 1)[-1]) or "config"
                text = archive.read(info).decode("utf-8", errors="replace")
                files.append({"filename": name, "text": text, "kind": classify_profile(name, text)})
        return files

    async def get_login_profiles(self, username: str) -> list:
        """ورودی‌های OpenConnect/L2TP/PPTP/IKEv2 مشتری (نام‌کاربری، رمز، PSK، آدرس...) از API پنل؛ هر مورد یک dict (login_profile)."""
        async with self._session() as session:
            client = await self._full(session, (await self._find(session, username))["id"])
            accounts = [a for a in client.get("accounts") or [] if a.get("username")]
            if not accounts:
                return []
            data = await self._api(session, "GET", "interfaces", "دریافت فهرست interfaceها")
        items = data.get("items") if isinstance(data, dict) else data
        by_id = {int(i["id"]): i for i in items if isinstance(i, dict) and i.get("id") is not None} if isinstance(items, list) else {}
        out = []
        for acc in accounts:
            iface = by_id.get(int(acc.get("interfaceId") or 0))
            item = login_profile(acc, iface) if iface else None
            if item:
                out.append(item)
        out.sort(key=lambda it: (_LOGIN_ORDER.get(it["kind"], 99), it["tunnel"], it["username"]))
        return out

    async def get_sub_info(self, username: str) -> dict:
        """مصرف/سقف/انقضا با کلیدهای هدر subscription-userinfo (upload/download/total/expire)."""
        async with self._session() as session:
            client = await self._find(session, username)
        up = int(client.get("upBytes") or 0)
        down = int(client.get("downBytes") or 0)
        used = int(client.get("usedBytes") or 0)
        if up + down < used:
            down = used - up
        return {
            "upload": up, "download": down,
            "total": int(client.get("quotaBytes") or 0),
            "expire": _epoch(client.get("expiresAt")),
        }

    async def test_connection(self) -> bool:
        try:
            async with self._session() as session:
                await self._api(session, "GET", "clients", "بررسی اتصال", params={"perPage": 1})
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False
