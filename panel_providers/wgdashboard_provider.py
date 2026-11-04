#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""Provider پنل WGDashboard (WireGuard): API Key در هدر wg-dashboard-apikey؛ نام configuration (اینترفیس) به‌جای «کاربر نمونه» گرفته می‌شود.

حجم و انقضا با Peer Schedule Job (محدودسازی خودکار) اعمال می‌شود و خروجی، متن فایل .conf است.
"""
import base64
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from ._http import new_session, request_json, http_error, load_json, gb_to_bytes, new_limit_bytes
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from .base import BasePanelProvider, PanelUserResult, PanelError, PanelUsernameTakenError

_JOB_TZ = timezone(timedelta(hours=3, minutes=30))
_JOB_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_RAW = serialization.Encoding.Raw


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _generate_keys() -> dict:
    secret = bytearray(secrets.token_bytes(32))
    secret[0] &= 248
    secret[31] = (secret[31] & 127) | 64
    private = X25519PrivateKey.from_private_bytes(bytes(secret))
    public = private.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
    return {
        "private_key": _b64(bytes(secret)),
        "public_key": _b64(public),
        "preshared_key": _b64(secrets.token_bytes(32)),
    }


def _job_value(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _job_epoch(value) -> int:
    try:
        return int(datetime.strptime(str(value), _JOB_DATE_FORMAT).replace(tzinfo=_JOB_TZ).timestamp())
    except ValueError:
        return 0


class WGDashboardProvider(BasePanelProvider):

    def _base(self) -> str:
        return self.server["api_url"].rstrip("/")

    def _session(self):
        return new_session(headers={"wg-dashboard-apikey": self.server["api_password"], "Accept": "application/json"}, server=self.server)

    async def list_product_targets(self):
        """فهرست interface/configurationهای WireGuard را از WGDashboard می‌خواند."""
        async with self._session() as session:
            data = await self._api(session, "GET", "getWireguardConfigurations", "دریافت فهرست configurationها")
        items = data.get("data") or data.get("configurations") or data.get("configs") or []
        if isinstance(items, dict):
            items = items.get("configurations") or items.get("configs") or items.get("items") or list(items.keys())
        choices = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                name = item.get("configurationName") or item.get("Name") or item.get("name") or item.get("config")
            else:
                name = item
            if name:
                choices.append({"value": str(name), "label": str(name)})
        if not choices:
            raise PanelError("هیچ configuration قابل انتخابی از WGDashboard دریافت نشد.")
        return {"field": "group_ids", "kind": "scalar", "choices": choices}

    def _config(self) -> str:
        name = load_json(self.server["group_ids"])
        if not isinstance(name, str) or not name:
            raise PanelError("نام configuration این سرور تنظیم نشده. اول از «تعیین کاربر نمونه» استفاده کن.")
        return name

    async def _api(self, session, method: str, path: str, action: str, **kwargs) -> dict:
        status, data, text = await request_json(session, method, f"{self._base()}/api/{path}", **kwargs)
        if status >= 400:
            raise http_error(action, status, text)
        if not isinstance(data, dict):
            raise PanelError(f"پاسخ نامعتبر از پنل در {action}.")
        if data.get("status") is False:
            raise PanelError(data.get("message") or data.get("msg") or f"{action} ناموفق بود.")
        return data

    async def _peers(self, session, config: str) -> tuple:
        data = await self._api(
            session, "GET", f"getWireguardConfigurationInfo?configurationName={quote(config)}", "دریافت لیست peer",
        )
        info = data.get("data") or {}
        return info.get("configurationPeers") or [], info.get("configurationRestrictedPeers") or []

    async def _find(self, session, config: str, username: str) -> tuple:
        """خروجی: (peer, is_restricted)."""
        peers, restricted = await self._peers(session, config)
        for peer in peers:
            if peer.get("name") == username:
                return peer, False
        for peer in restricted:
            if peer.get("name") == username:
                return peer, True
        raise PanelError(f"کاربری با نام «{username}» روی پنل پیدا نشد.")

    async def _save_job(self, session, config: str, peer_id: str, field: str, value) -> None:
        job = {
            "JobID": str(uuid.uuid4()),
            "Configuration": config,
            "Peer": peer_id,
            "Field": field,
            "Operator": "lgt",
            "Value": _job_value(value),
            "CreationDate": "",
            "ExpireDate": None,
            "Action": "restrict",
        }
        await self._api(session, "POST", "savePeerScheduleJob", "ثبت محدودیت", json={"Job": job})

    async def _delete_job(self, session, job: dict) -> None:
        await self._api(session, "POST", "deletePeerScheduleJob", "حذف محدودیت قبلی", json={"Job": job})

    async def _download(self, session, config: str, peer_id: str) -> str:
        data = await self._api(
            session, "GET", f"downloadPeer/{quote(config)}?id={quote(peer_id, safe='')}", "دریافت فایل کانفیگ",
        )
        return str((data.get("data") or {}).get("file") or "")

    @staticmethod
    def _jobs(peer: dict) -> tuple:
        limit_job = next((j for j in peer.get("jobs") or [] if j.get("Field") == "total_data"), None)
        date_job = next((j for j in peer.get("jobs") or [] if j.get("Field") == "date"), None)
        return limit_job, date_job

    async def fetch_template_from_user(self, sample_username: str) -> dict:
        config = sample_username.strip()
        async with self._session() as session:
            await self._peers(session, config)
        return {"group_ids": config, "proxy_settings": {}}

    async def create_user(self, username: str, volume_gb: int, duration_days: int) -> PanelUserResult:
        config = self._config()
        async with self._session() as session:
            peers, restricted = await self._peers(session, config)
            if any(p.get("name") == username for p in peers + restricted):
                raise PanelUsernameTakenError(f"نام کاربری «{username}» روی پنل تکراری است")
            ips = (await self._api(session, "GET", f"getAvailableIPs/{quote(config)}", "دریافت IP آزاد")).get("data") or {}
            free = next((v[0] for v in ips.values() if v), None)
            if not free:
                raise PanelError("IP آزادی روی این configuration باقی نمانده.")
            keys = _generate_keys()
            await self._api(
                session, "POST", f"addPeers/{quote(config)}", "ساخت کاربر",
                json={"name": username, "allowed_ips": [free], **keys},
            )
            try:
                if volume_gb:
                    await self._save_job(session, config, keys["public_key"], "total_data", volume_gb)
                if duration_days:
                    expire = datetime.fromtimestamp(time.time() + duration_days * 86400, _JOB_TZ)
                    await self._save_job(session, config, keys["public_key"], "date", expire.strftime(_JOB_DATE_FORMAT))
                file_text = await self._download(session, config, keys["public_key"])
            except PanelError:
                try:
                    await self._api(
                        session, "POST", f"deletePeers/{quote(config)}", "پاکسازی",
                        json={"peers": [keys["public_key"]]},
                    )
                except PanelError:
                    pass
                raise
        return PanelUserResult(username=username, subscription_url=file_text, raw={"public_key": keys["public_key"]})

    async def delete_user(self, username: str) -> bool:
        config = self._config()
        async with self._session() as session:
            try:
                peer, _ = await self._find(session, config, username)
            except PanelError as exc:
                if "پیدا نشد" in str(exc):
                    return False
                raise
            await self._api(
                session, "POST", f"allowAccessPeers/{quote(config)}", "فعال‌سازی peer", json={"peers": [peer["id"]]},
            )
            await self._api(
                session, "POST", f"deletePeers/{quote(config)}", "حذف کاربر", json={"peers": [peer["id"]]},
            )
        return True

    async def get_user_usage(self, username: str) -> dict:
        config = self._config()
        async with self._session() as session:
            peer, restricted = await self._find(session, config, username)
        used = gb_to_bytes(float(peer.get("total_data") or 0) + float(peer.get("cumu_data") or 0))
        limit_job, date_job = self._jobs(peer)
        limit = gb_to_bytes(limit_job["Value"]) if limit_job else 0
        expire = _job_epoch(date_job["Value"]) if date_job else 0
        status = "disabled" if restricted or (peer.get("configuration") or {}).get("Status") is False else "active"
        if expire and expire < time.time():
            status = "expired"
        if limit and limit < used:
            status = "limited"
        return {"used_bytes": used, "data_limit_bytes": limit, "status": status}

    async def get_user(self, username: str) -> PanelUserResult:
        config = self._config()
        async with self._session() as session:
            peer, _ = await self._find(session, config, username)
            file_text = await self._download(session, config, peer["id"])
        return PanelUserResult(username=username, subscription_url=file_text, raw=peer)

    supports_data_limit_sync = True

    async def set_data_limit_bytes(self, username: str, limit_bytes: int, reenable: bool = False) -> None:
        """فقط job محدودیت حجم peer را عوض می‌کند (انقضا/مصرف دست‌نخورده). 0 = نامحدود."""
        config = self._config()
        async with self._session() as session:
            peer, _ = await self._find(session, config, username)
            peer_id = peer["id"]
            limit_job, _date_job = self._jobs(peer)
            current_limit = gb_to_bytes(limit_job["Value"]) if limit_job else 0
            new_gb = round(int(limit_bytes) / (1024 ** 3), 2)
            if limit_bytes and new_gb * (1024 ** 3) < int(limit_bytes):
                new_gb = round(new_gb + 0.01, 2)  # گرد کردن رو به بالا؛ هرگز کمتر از سقف واقعی
            if int(limit_bytes) == current_limit or (limit_job and abs(float(limit_job["Value"]) - new_gb) < 0.005):
                return
            if limit_job:
                await self._delete_job(session, limit_job)
            if limit_bytes:
                await self._save_job(session, config, peer_id, "total_data", new_gb)
            if reenable:
                await self._api(
                    session, "POST", f"allowAccessPeers/{quote(config)}", "فعال‌سازی peer", json={"peers": [peer_id]},
                )

    async def update_user(self, username: str, add_volume_gb: float = 0, add_days: int = 0,
                           reset_usage: bool = False, preserve_remaining: bool = False,
                           unlimited_volume: bool = False) -> PanelUserResult:
        config = self._config()
        async with self._session() as session:
            peer, _ = await self._find(session, config, username)
            peer_id = peer["id"]
            limit_job, date_job = self._jobs(peer)
            used = gb_to_bytes(float(peer.get("total_data") or 0) + float(peer.get("cumu_data") or 0))
            current_limit = gb_to_bytes(limit_job["Value"]) if limit_job else 0
            new_limit = new_limit_bytes(current_limit, used, add_volume_gb, reset_usage, preserve_remaining,
                                         unlimited=unlimited_volume)
            if reset_usage:
                await self._api(
                    session, "POST", f"resetPeerData/{quote(config)}", "ریست مصرف",
                    json={"id": peer_id, "type": "total"},
                )
            await self._api(
                session, "POST", f"allowAccessPeers/{quote(config)}", "فعال‌سازی peer", json={"peers": [peer_id]},
            )
            if add_days:
                current = _job_epoch(date_job["Value"]) if date_job else 0
                new_expire = max(current, int(time.time())) + add_days * 86400
                if date_job:
                    await self._delete_job(session, date_job)
                await self._save_job(
                    session, config, peer_id, "date",
                    datetime.fromtimestamp(new_expire, _JOB_TZ).strftime(_JOB_DATE_FORMAT),
                )
            if new_limit != current_limit:
                if limit_job:
                    await self._delete_job(session, limit_job)
                if new_limit:
                    await self._save_job(session, config, peer_id, "total_data", round(new_limit / (1024 ** 3), 2))
            file_text = await self._download(session, config, peer_id)
        return PanelUserResult(username=username, subscription_url=file_text, raw=peer)

    async def revoke_credentials(self, username: str) -> PanelUserResult:
        raise PanelError("این نوع پنل از قطع دسترسی و صدور لینک جدید پشتیبانی نمی‌کند.")

    async def test_connection(self) -> bool:
        try:
            config = self._config()
            async with self._session() as session:
                await self._peers(session, config)
            return True
        except PanelError as e:
            self.last_error = str(e)
            return False
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
