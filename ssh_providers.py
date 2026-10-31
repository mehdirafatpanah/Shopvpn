# -*- coding: utf-8 -*-
"""قرارداد Provider برای ساخت SSH؛ پیاده‌سازی شبکه‌ای را آداپتورهای امن انجام می‌دهند.

عمداً اجرای shell خام و نگهداری رمز/کلید خصوصی در دیتابیس وجود ندارد. نود لینوکس
نیازمند Agent قابل‌اعتماد برای حسابداری per-user است؛ پنل SSH به API مستند نیاز دارد.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import asyncio
import json
import secrets
import string
import uuid

import aiohttp


class SSHProviderError(RuntimeError):
    http_status = None


class SSHAgentUnreachable(SSHProviderError):
    """Agent پاسخ نداد (سرور خاموش/حذف‌شده، فایروال، DNS، timeout یا خطای TLS)؛ با خطای HTTP خود Agent فرق دارد."""


@dataclass
class SSHAccountResult:
    account_id: str
    username: str
    host: str
    port: int
    subscription_uri: str = ""
    metadata: dict = field(default_factory=dict)


class BaseSSHProvider(ABC):
    """رابط پایه برای SSH Node Providerها."""
    node = None

    def __init__(self, node: dict, secret_resolver=None):
        self.node = dict(node)
        self.secret_resolver = secret_resolver

    def resolve_secret(self):
        ref = self.node.get("secret_ref")
        if not ref:
            return None
        if not self.secret_resolver:
            raise SSHProviderError("برای دریافت credential باید secret_resolver پیکربندی شود")
        return self.secret_resolver(ref)

    @abstractmethod
    async def test_connection(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def create_account(self, username: str, limit_bytes: int, expires_at: str = None,
                             protocol: str = "ssh") -> SSHAccountResult:
        raise NotImplementedError

    async def get_info(self) -> dict:
        return {}

    @abstractmethod
    async def get_usage(self, account_id: str) -> dict:
        """خروجی استاندارد: used_bytes، uploaded_bytes، downloaded_bytes، reported_at."""
        raise NotImplementedError

    @abstractmethod
    async def set_account_enabled(self, account_id: str, enabled: bool, reason: str = None) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def delete_account(self, account_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def update_account(self, account_id: str, limit_bytes: int = None, expires_at: str = None) -> bool:
        raise NotImplementedError


class LinuxAgentSSHProvider(BaseSSHProvider):
    """Client for the authenticated ShopVPN Linux-node agent.

    node.config_json must contain agent_url (prefer HTTPS) and optional timeout.
    The bearer token is resolved from secret_ref; it is never read from config_json.
    """
    def _settings(self):
        config = self.node.get("config_json") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                config = {}
        url = str(config.get("agent_url") or "").rstrip("/")
        if not url:
            host = str(self.node.get("host") or "").strip()
            port = int(config.get("agent_port") or 8765)
            scheme = "https" if config.get("https", True) else "http"
            url = f"{scheme}://{host}:{port}"
        if not url.startswith(("https://", "http://")):
            raise SSHProviderError("agent_url باید با http:// یا https:// شروع شود")
        if url.startswith("http://") and not config.get("allow_insecure_http", False):
            raise SSHProviderError("ارتباط HTTP ناامن است؛ از HTTPS یا شبکه خصوصی با allow_insecure_http صریح استفاده کنید")
        timeout = max(3, min(60, int(config.get("timeout", 12))))
        token = self.resolve_secret()
        if not token:
            raise SSHProviderError("توکن Agent از secret_ref دریافت نشد")
        self._pin = str(config.get("cert_sha256") or "").replace(":", "").strip().lower()
        return url, str(token), timeout

    async def _request(self, method, path, payload=None):
        url, token, timeout = self._settings()
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=client_timeout, headers=headers) as session:
                ssl_arg = aiohttp.Fingerprint(bytes.fromhex(self._pin)) if (getattr(self, "_pin", "") and url.startswith("https://")) else None
                async with session.request(method, url + path, json=payload, ssl=ssl_arg) as response:
                    raw = await response.text()
                    if response.status >= 400:
                        safe_detail = raw[:240].replace("\n", " ")
                        err = SSHProviderError(f"Linux Agent HTTP {response.status}: {safe_detail}")
                        err.http_status = response.status
                        raise err
                    try:
                        return json.loads(raw) if raw else {}
                    except ValueError as exc:
                        raise SSHProviderError("پاسخ Agent JSON معتبر نیست") from exc
        except SSHProviderError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise SSHAgentUnreachable(f"ارتباط با Linux Agent برقرار نشد: {type(exc).__name__}") from exc
        except OSError as exc:  # مثلاً ssl/socket خطاهایی که aiohttp بسته‌بندی نکرده
            raise SSHAgentUnreachable(f"ارتباط با Linux Agent برقرار نشد: {type(exc).__name__}") from exc

    async def test_connection(self) -> bool:
        data = await self._request("GET", "/v1/accounts")
        return isinstance(data.get("accounts"), list)

    async def get_info(self) -> dict:
        data = await self._request("GET", "/v1/info")
        return data if isinstance(data, dict) else {}

    async def create_account(self, username: str, limit_bytes: int, expires_at: str = None,
                             protocol: str = "ssh") -> SSHAccountResult:
        protocol = str(protocol or "ssh").strip().lower()
        if protocol == "openvpn":
            info = await self.get_info()
            if "openvpn_username_password" not in (info.get("features") or []):
                raise SSHProviderError("Linux Agent از OpenVPN با Username/Password پشتیبانی نمی‌کند؛ Agent را به‌روز کنید")
            alphabet = string.ascii_letters + string.digits + "-_"
            password = "".join(secrets.choice(alphabet) for _ in range(28))
            account_id = str(uuid.uuid4())
            data = await self._request("POST", "/v1/accounts", {
                "account_id": account_id, "username": username, "password": password, "protocol": "openvpn",
                "remote_host": str(self.node.get("host") or ""), "expires_at": expires_at,
                "limit_bytes": max(0, int(limit_bytes)),
            })
            profile = str(data.get("profile") or "")
            if "<ca>" not in profile:
                raise SSHProviderError("پاسخ Agent شامل پروفایل OpenVPN معتبر نیست")
            return SSHAccountResult(account_id=account_id, username=data.get("username", username),
                host=str(self.node.get("host") or ""), port=int(data.get("port") or 1194),
                metadata={"profile": profile, "password": password, "protocol": "openvpn", "transport": data.get("transport"),
                          "limit_bytes_requested": int(limit_bytes), "accounting_ready": False})
        if protocol == "wireguard":
            account_id = str(uuid.uuid4())
            data = await self._request("POST", "/v1/accounts", {
                "account_id": account_id, "username": username, "protocol": "wireguard",
                "remote_host": str(self.node.get("host") or ""), "expires_at": expires_at,
                "limit_bytes": max(0, int(limit_bytes)),
            })
            profile = str(data.get("profile") or "")
            if "[Interface]" not in profile or "PrivateKey" not in profile:
                raise SSHProviderError("پاسخ Agent شامل پروفایل WireGuard معتبر نیست")
            return SSHAccountResult(account_id=account_id, username=data.get("username", username),
                host=str(self.node.get("host") or ""), port=int(data.get("port") or 51820),
                metadata={"profile": profile, "protocol": "wireguard", "transport": data.get("transport"),
                          "limit_bytes_requested": int(limit_bytes), "accounting_ready": False})
        if protocol != "ssh":
            raise SSHProviderError(f"پروتکل پشتیبانی‌نشده: {protocol}")
        alphabet = string.ascii_letters + string.digits + "-_"
        password = "".join(secrets.choice(alphabet) for _ in range(28))
        account_id = str(uuid.uuid4())
        payload = {"account_id": account_id, "username": username, "password": password,
                   "expires_at": expires_at, "limit_bytes": max(0, int(limit_bytes))}
        from ssh_hosts import ssh_port_range, ssh_port_range_is_custom
        custom_range = ssh_port_range_is_custom(self.node)
        low, high = ssh_port_range(self.node)
        if custom_range:
            payload["port_min"], payload["port_max"] = low, high
        data = await self._request("POST", "/v1/accounts", payload)
        port = int(data.get("port") or self.node.get("port") or 22)
        if custom_range and not low <= port <= high:
            # Agent قدیمی بازه را نادیده گرفته؛ حساب را برنگردان تا پورت خارج از بازه به کاربر نرسد.
            try:
                await self._request("POST", f"/v1/accounts/{account_id}/delete")
            except Exception:
                pass
            raise SSHProviderError(
                f"Agent این نود بازه‌ی پورت SSH را اعمال نکرد (پورت {port}، بازه‌ی تنظیم‌شده {low}-{high}). "
                "فایل ssh_node_agent.py را روی نود به‌روز و سرویس shopvpn-ssh-agent را ری‌استارت کنید.")
        return SSHAccountResult(account_id=account_id, username=data.get("username", username),
            host=str(self.node.get("host") or ""), port=port,
            metadata={"password": password, "limit_bytes_requested": int(limit_bytes),
                      "accounting_ready": False, "warning": "وضعیت شمارنده پس از اولین گزارش مصرف بررسی می‌شود"})

    async def get_usage(self, account_id: str) -> dict:
        data = await self._request("GET", f"/v1/accounts/{account_id}/usage")
        return {"used_bytes": int(data.get("used_bytes", 0)),
                "uploaded_bytes": int(data.get("uploaded_bytes", 0)),
                "downloaded_bytes": int(data.get("downloaded_bytes", 0)),
                "reported_at": data.get("reported_at"), "source": data.get("source"),
                "status": data.get("status"), "disabled_reason": data.get("disabled_reason"),
                "accounting_ready": bool(data.get("accounting_ready", False))}

    async def set_account_enabled(self, account_id: str, enabled: bool, reason: str = None) -> bool:
        payload = None if enabled else {"reason": reason or "manual"}
        await self._request("POST", f"/v1/accounts/{account_id}/{'enable' if enabled else 'disable'}", payload)
        return True

    async def delete_account(self, account_id: str) -> bool:
        try:
            await self._request("POST", f"/v1/accounts/{account_id}/delete")
        except SSHProviderError as exc:
            if getattr(exc, "http_status", None) == 404:
                return True  # روی نود از قبل وجود ندارد؛ هدف (حذف) برقرار است.
            raise
        return True

    async def update_account(self, account_id: str, limit_bytes: int = None, expires_at: str = None) -> bool:
        payload = {"expires_at": expires_at}
        if limit_bytes is not None:
            payload["limit_bytes"] = max(0, int(limit_bytes))
        await self._request("PATCH", f"/v1/accounts/{account_id}", payload)
        return True


class SSHPanelAPIProvider(BaseSSHProvider):
    """قالب Provider برای پنل SSH. هر پنل باید آداپتور مستند و اختصاصی داشته باشد."""
    async def _not_configured(self):
        raise SSHProviderError(
            f"آداپتور API برای پنل SSH {self.node.get('panel_type') or '(نامشخص)'} پیاده‌سازی نشده است."
        )

    async def test_connection(self) -> bool:
        await self._not_configured()

    async def create_account(self, username: str, limit_bytes: int, expires_at: str = None,
                             protocol: str = "ssh") -> SSHAccountResult:
        await self._not_configured()

    async def get_usage(self, account_id: str) -> dict:
        await self._not_configured()

    async def set_account_enabled(self, account_id: str, enabled: bool, reason: str = None) -> bool:
        await self._not_configured()

    async def delete_account(self, account_id: str) -> bool:
        await self._not_configured()

    async def update_account(self, account_id: str, limit_bytes: int = None, expires_at: str = None) -> bool:
        await self._not_configured()


def get_ssh_provider(node: dict, secret_resolver=None) -> BaseSSHProvider:
    node_type = str(node.get("node_type") or "").lower()
    if node_type == "linux":
        return LinuxAgentSSHProvider(node, secret_resolver=secret_resolver)
    if node_type == "ssh_panel":
        return SSHPanelAPIProvider(node, secret_resolver=secret_resolver)
    raise SSHProviderError(f"نوع نود SSH ناشناخته است: {node_type}")
