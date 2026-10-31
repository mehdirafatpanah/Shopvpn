#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""Provider پنل S-UI (alireza0/s-ui): REST API با هدر Token روی /apiv2؛ inboundها از روی کاربر نمونه گرفته می‌شوند."""
import json
import secrets
import string
import time
import uuid
from urllib.parse import urlparse
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍

from ._http import new_session, request_json, http_error, load_json, server_value, new_limit_bytes
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError

_ALPHABET = string.ascii_letters + string.digits


def _auth_str(length: int = 10) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _client_config(name: str) -> dict:
    ss_password = secrets.token_hex(16)
    return {
        "mixed": {"username": name, "password": _auth_str()},
        "socks": {"username": name, "password": _auth_str()},
        "http": {"username": name, "password": _auth_str()},
        "shadowsocks": {"name": name, "password": ss_password},
        "shadowsocks16": {"name": name, "password": ss_password},
        "shadowtls": {"name": name, "password": ss_password},
        "vmess": {"name": name, "uuid": str(uuid.uuid4()), "alterId": 0},
        "vless": {"name": name, "uuid": str(uuid.uuid4()), "flow": ""},
        "trojan": {"name": name, "password": _auth_str()},
        "naive": {"username": name, "password": _auth_str()},
        "hysteria": {"name": name, "auth_str": _auth_str()},
        "tuic": {"name": name, "uuid": str(uuid.uuid4()), "password": _auth_str()},
        "hysteria2": {"name": name, "password": _auth_str()},
    }


class SUIProvider(BasePanelProvider):

    def _base(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self):
        return new_session(headers={"Token": self.server["api_password"], "Accept": "application/json"}, server=self.server)

    async def _api(self, session, method: str, path: str, action: str, **kwargs) -> dict:
        status, data, text = await request_json(session, method, f"{self._base()}/apiv2/{path}", **kwargs)
        if status >= 400:
            raise http_error(action, status, text)
        if not isinstance(data, dict):
            raise PanelError(f"پاسخ نامعتبر از پنل در {action}.")
        if not data.get("success"):
            raise PanelError(data.get("msg") or f"{action} ناموفق بود.")
        return data

    async def _save(self, session, action_name: str, payload, label: str) -> dict:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        return await self._api(
            session, "POST", "save", label,
            data={"object": "clients", "action": action_name, "data": data},
        )

    async def _find(self, session, username: str) -> dict:
        listing = await self._api(session, "GET", "clients", "دریافت لیست کاربران")
        clients = (listing.get("obj") or {}).get("clients") or []
        entry = next((c for c in clients if c.get("name") == username), None)
        if entry is None:
            raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
        full = await self._api(session, "GET", "clients", "دریافت اطلاعات کاربر", params={"id": entry["id"]})
        found = (full.get("obj") or {}).get("clients") or []
        if not found:
            raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")
        return found[0]

    async def _sub_url(self, session, username: str) -> str:
        override = (server_value(self.server, "xui_sub_base_url", "") or "").rstrip("/")
        if override:
            return f"{override}/{username}"
        settings = (await self._api(session, "GET", "settings", "دریافت تنظیمات پنل")).get("obj") or {}
        parsed = urlparse(self._base())
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        path = settings.get("subPath") or "/sub/"
        if not path.endswith("/"):
            path += "/"
        port = settings.get("subPort")
        netloc = f"{host}:{port}" if port else host
        return f"{parsed.scheme}://{netloc}{path}{username}"

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        async with self._session() as session:
            client = await self._find(session, sample_username)
        inbounds = client.get("inbounds") or []
        if not inbounds:
            raise PanelError("کاربر نمونه هیچ inbound ای ندارد؛ از یک کاربر دیگر امتحان کن.")
        return {"group_ids": inbounds, "proxy_settings": {}}

    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
        inbounds = load_json(self.server["group_ids"])
        if not isinstance(inbounds, list) or not inbounds:
            raise PanelError("inbound های این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن.")
        client = {
            "enable": True,
            "name": username,
            "config": _client_config(username),
            "inbounds": inbounds,
            "links": [],
            "volume": int(volume_gb * (1024 ** 3)),
            "expiry": int(time.time() + duration_days * 86400) if duration_days else 0,
            "desc": "ساخته‌شده توسط ShopVPN (کانفیگ شخصی)",
        }
        async with self._session() as session:
            listing = await self._api(session, "GET", "clients", "دریافت لیست کاربران")
            if any(c.get("name") == username for c in (listing.get("obj") or {}).get("clients") or []):
                raise PanelUsernameTakenError(f"نام کاربری «{username}» روی پنل تکراری است")
            await self._save(session, "new", client, "ساخت کاربر")
            url = await self._sub_url(session, username)
        return PanelUserResult(username=username, subscription_url=url, raw=client)

    async def delete_user(self, username: str) -> bool:
        async with self._session() as session:
            try:
                client = await self._find(session, username)
            except PanelError as exc:
                if "پیدا نشد" in str(exc):
                    return False
                raise
            await self._save(session, "del", str(client["id"]), "حذف کاربر")
        return True

    async def get_user_usage(self, username: str) -> dict:
        async with self._session() as session:
            client = await self._find(session, username)
        used = int(client.get("up") or 0) + int(client.get("down") or 0)
        volume = int(client.get("volume") or 0)
        expiry = int(client.get("expiry") or 0)
        if volume and used >= volume:
            status = "limited"
        elif expiry and expiry < time.time():
            status = "expired"
        else:
            status = "active" if client.get("enable") else "disabled"
        return {"used_bytes": used, "data_limit_bytes": volume, "status": status}

    async def get_user(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            client = await self._find(session, username)
            url = await self._sub_url(session, username)
        return PanelUserResult(username=username, subscription_url=url, raw=client)

    supports_data_limit_sync = True

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط volume کلاینت را عوض می‌کند (انقضا/مصرف دست‌نخورده)."""
        async with self._session() as session:
            client = await self._find(session, username)
            updated = dict(client)
            updated["volume"] = int(limit_bytes)
            if reenable:
                updated["enable"] = True
            await self._save(session, "edit", updated, "اعمال سقف حجم")

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False) -> PanelUserResult:
        async with self._session() as session:
            client = await self._find(session, username)
            updated = dict(client)
            if add_days:
                current = int(client.get("expiry") or 0)
                updated["expiry"] = max(current, int(time.time())) + add_days * 86400
            used = int(client.get("up") or 0) + int(client.get("down") or 0)
            updated["volume"] = new_limit_bytes(client.get("volume"), used, add_volume_gb, reset_usage, preserve_remaining,
                                                     unlimited=unlimited_volume)
            if reset_usage:
                updated["up"] = 0
                updated["down"] = 0
            updated["enable"] = True
            await self._save(session, "edit", updated, "بروزرسانی کاربر")
            url = await self._sub_url(session, username)
        return PanelUserResult(username=username, subscription_url=url, raw=updated)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        async with self._session() as session:
            client = await self._find(session, username)
            updated = dict(client)
            updated["config"] = _client_config(username)
            updated["links"] = []
            await self._save(session, "edit", updated, "قطع دسترسی/تولید لینک جدید")
            url = await self._sub_url(session, username)
        return PanelUserResult(username=username, subscription_url=url, raw=updated)

    async def set_enabled(self, username: str, enabled: bool) -> None:
        async with self._session() as session:
            client = await self._find(session, username)
            updated = dict(client)
            updated["enable"] = bool(enabled)
            await self._save(session, "edit", updated, "تغییر وضعیت کاربر")

    supports_template_resync = True

    async def resync_user_template(self, username: str) -> bool:
        """inbound های کلاینت را با قالب فعلی پنل در ربات یکی می‌کند."""
        target = load_json(self.server["group_ids"])
        if not isinstance(target, list) or not target:
            return False
        async with self._session() as session:
            client = await self._find(session, username)
            if self._norm_binding(client.get("inbounds")) == self._norm_binding(target):
                return False
            updated = dict(client)
            updated["inbounds"] = target
            await self._save(session, "edit", updated, "هم‌گام‌سازی inbound کاربر")
        return True

    async def test_connection(self) -> bool:
        try:
            async with self._session() as session:
                await self._api(session, "GET", "settings", "بررسی اتصال")
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
