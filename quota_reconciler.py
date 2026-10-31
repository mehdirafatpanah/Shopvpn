# -*- coding: utf-8 -*-
"""Central poller/enforcer for shared VPN + SSH quota pools.

VPN counters are read through ShopVPN's existing panel providers. Linux SSH
counters are accepted only when the node agent says accounting_ready=true;
this module never converts an unreported counter into zero usage.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from panel_providers import get_provider
from ssh_providers import get_ssh_provider, SSHProviderError

logger = logging.getLogger(__name__)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _env_secret_resolver(reference: str):
    """Resolve only explicit env:NAME references; never treat a ref as a secret."""
    reference = str(reference or "")
    if reference.startswith("enc:"):
        # توکن رمزنگاری‌شده در دیتابیس (نودهای نصب‌شده با نصب خودکار)
        from ssh_credentials import decrypt_credential
        try:
            return decrypt_credential(reference[4:])
        except RuntimeError as exc:
            raise SSHProviderError(str(exc))
    if not reference.startswith("env:"):
        raise SSHProviderError("secret_ref پشتیبانی‌نشده است؛ از env:VARIABLE_NAME استفاده کنید")
    name = reference[4:].strip()
    if not name or not name.replace("_", "A").isalnum():
        raise SSHProviderError("نام متغیر محیطی در secret_ref نامعتبر است")
    value = os.getenv(name)
    if not value:
        raise SSHProviderError(f"متغیر محیطی {name} تنظیم نشده است")
    return value


class QuotaReconciler:
    """Reconcile snapshots and enforce quota/expiry on all members of each pool.

    max_snapshot_age_seconds prevents stale counters from being mistaken for
    current usage. Expired pools are disabled regardless of telemetry health.
    If telemetry is stale, the reconciler does not automatically re-enable any
    previously suspended service.
    """
    def __init__(self, db, interval_seconds: int = 60, max_snapshot_age_seconds: int = 300, stale_grace_seconds: int = 900,
                 vpn_provider_factory=None, ssh_provider_factory=None, secret_resolver=None):
        self.db = db
        self.interval_seconds = max(10, int(interval_seconds))
        self.max_snapshot_age_seconds = max(30, int(max_snapshot_age_seconds))
        self.stale_grace_seconds = max(0, int(stale_grace_seconds))
        self.vpn_provider_factory = vpn_provider_factory or get_provider
        self.ssh_provider_factory = ssh_provider_factory or get_ssh_provider
        self.secret_resolver = secret_resolver or _env_secret_resolver

    def _vpn_record(self, custom_config_id):
        with self.db._get_conn() as conn:
            cc = conn.execute("SELECT id,user_id,panel_server_id,username,status FROM custom_configs WHERE id=?",
                              (int(custom_config_id),)).fetchone()
            if not cc:
                return None, None
            server = conn.execute("SELECT * FROM panel_servers WHERE id=?", (int(cc["panel_server_id"]),)).fetchone()
            return (dict(cc), dict(server) if server else None)

    def _vpn_member(self, service_id):
        kind, _, raw = str(service_id).partition(":")
        if kind == "custom_config":
            return self._vpn_record(raw)
        if kind == "panel_link":
            with self.db._get_conn() as conn:
                link = conn.execute(
                    "SELECT id,panel_server_id,username FROM config_panel_links WHERE id=? AND status='active'",
                    (int(raw),)).fetchone()
                if not link:
                    return None, None
                server = conn.execute("SELECT * FROM panel_servers WHERE id=?",
                                      (int(link["panel_server_id"]),)).fetchone()
                return dict(link), (dict(server) if server else None)
        raise RuntimeError("شناسه سرویس VPN باید custom_config:<id> یا panel_link:<id> باشد")

    def _ssh_record(self, account_id):
        accounts = self.db.list_ssh_accounts()
        account = next((a for a in accounts if str(a.get("account_id")) == str(account_id)), None)
        if not account:
            return None, None
        nodes = self.db.list_ssh_nodes()
        node = next((n for n in nodes if int(n["id"]) == int(account["node_id"])), None)
        return account, node

    async def _poll_vpn(self, service_id):
        cc, server = self._vpn_member(service_id)
        if not cc or not server:
            raise RuntimeError("سرویس VPN یا پنل مربوطه پیدا نشد")
        provider = self.vpn_provider_factory(server)
        usage = await provider.get_user_usage(cc["username"])
        if not isinstance(usage, dict) or usage.get("used_bytes") is None:
            raise RuntimeError("Provider مقدار used_bytes معتبر برنگرداند")
        used = int(usage["used_bytes"])
        if used < 0:
            raise RuntimeError("Provider مصرف منفی گزارش کرد")
        stamp = usage.get("reported_at") or datetime.now(timezone.utc).isoformat()
        self.db.record_usage_snapshot("vpn", service_id, used,
            uploaded_bytes=usage.get("uploaded_bytes", 0),
            downloaded_bytes=usage.get("downloaded_bytes", 0),
            source=f"panel:{server.get('panel_type', 'unknown')}", reported_at=stamp)
        return {"ok": True, "used_bytes": used, "source": server.get("panel_type", "unknown"),
                "raw_used_bytes": used, "panel_limit_bytes": int(usage.get("data_limit_bytes") or 0),
                "panel_status": str(usage.get("status") or "")}

    async def _poll_ssh(self, service_id):
        account, node = self._ssh_record(service_id)
        if not account or not node:
            raise RuntimeError("حساب SSH یا نود آن پیدا نشد")
        provider = self.ssh_provider_factory(node, secret_resolver=self.secret_resolver)
        usage = await provider.get_usage(service_id)
        remote_status = usage.get("status")
        remote_reason = usage.get("disabled_reason")
        if remote_status in {"active", "disabled", "expired", "error"}:
            self.db.set_ssh_account_status_by_account_id(service_id, remote_status)
        if account.get("quota_pool_id") and remote_reason == "manual":
            self.db.set_quota_enforcement_state(int(account["quota_pool_id"]), "ssh", service_id,
                is_disabled=False, reason="manual_disabled", last_error=None)
        if not usage.get("accounting_ready"):
            # Explicitly refuse to treat the agent's initial zero as real traffic.
            raise RuntimeError("منبع شمارش ترافیک SSH هنوز آماده نیست")
        used = int(usage.get("used_bytes", -1))
        if used < 0:
            raise RuntimeError("شمارنده SSH نامعتبر است")
        stamp = usage.get("reported_at") or datetime.now(timezone.utc).isoformat()
        self.db.record_usage_snapshot("ssh", service_id, used,
            uploaded_bytes=usage.get("uploaded_bytes", 0),
            downloaded_bytes=usage.get("downloaded_bytes", 0),
            source=str(usage.get("source") or "ssh-agent"), reported_at=stamp)
        return {"ok": True, "used_bytes": used, "source": usage.get("source") or "ssh-agent",
                "remote_status": remote_status}

    async def _set_member_enabled(self, pool_id, member, enabled, reason):
        kind, service_id = member["service_kind"], member["service_id"]
        prior = self.db.get_quota_enforcement_state(pool_id, kind, service_id)
        # Avoid repeated API calls for a service already suspended by this worker.
        if not enabled and prior and prior.get("reason") == "manual_disabled" and not prior.get("is_disabled"):
            return {"service_kind": kind, "service_id": service_id, "ok": True, "skipped": True, "manual_disabled": True}
        if not enabled and prior and prior.get("is_disabled") and prior.get("reason") == reason and not prior.get("last_error"):
            return {"service_kind": kind, "service_id": service_id, "ok": True, "skipped": True}
        try:
            if kind == "vpn":
                cc, server = self._vpn_member(service_id)
                if not cc or not server:
                    raise RuntimeError("سرویس VPN یا پنل مربوطه پیدا نشد")
                provider = self.vpn_provider_factory(server)
                await provider.set_enabled(cc["username"], bool(enabled))
            elif kind == "ssh":
                account, node = self._ssh_record(service_id)
                if not account or not node:
                    raise RuntimeError("حساب SSH یا نود آن پیدا نشد")
                provider = self.ssh_provider_factory(node, secret_resolver=self.secret_resolver)
                if enabled:
                    # Shared pool owns the expiry and volume. Synchronize its expiry
                    # before enabling, otherwise the node's old local expiry can
                    # immediately disable the account again.
                    pool = self.db.get_quota_pool(pool_id)
                    await provider.update_account(service_id, limit_bytes=0,
                                                  expires_at=(pool or {}).get("expires_at"))
                await provider.set_account_enabled(service_id, bool(enabled),
                                                   reason=reason if not enabled else None)
                self.db.set_ssh_account_status_by_account_id(service_id, "active" if enabled else "disabled")
            else:
                raise RuntimeError(f"نوع سرویس ناشناخته: {kind}")
            self.db.set_quota_enforcement_state(pool_id, kind, service_id,
                is_disabled=not enabled, reason=reason if not enabled else None, last_error=None)
            return {"service_kind": kind, "service_id": service_id, "ok": True, "enabled": bool(enabled)}
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            # Preserve whether this worker had previously disabled the service.
            self.db.set_quota_enforcement_state(pool_id, kind, service_id,
                is_disabled=bool(prior and prior.get("is_disabled")),
                reason=(prior.get("reason") if prior else reason), last_error=error)
            logger.warning("Quota enforcement failed for pool=%s service=%s/%s: %s",
                           pool_id, kind, service_id, error)
            return {"service_kind": kind, "service_id": service_id, "ok": False, "error": error}

    async def _sync_vpn_panel_limits(self, pool, members, poll_results, usage):
        """مصرف SSH را روی پنل(های) VPN عضو همان استخر «اعمال» می‌کند.

        پنل‌های VPN هیچ راهی برای نوشتن مستقیم «مصرف» ندارند (و نوشتن آن هم باعث شمارش
        دوباره‌ی مصرف در poll بعدی می‌شد)، پس سقف حجم کاربر روی پنل برابر می‌شود با
        «مصرف خودِ پنل + باقی‌مانده‌ی استخر مشترک» = سقف استخر − مصرف SSH. نتیجه:
          * پنل همیشه باقی‌مانده‌ی واقعیِ مشترک را می‌بیند؛
          * وقتی حجم مشترک تمام شود، خودِ پنل VPN هم در همان لحظه (بدون انتظار برای
            دور بعدیِ reconciler) کاربر را قطع می‌کند.
        فقط وقتی اجرا می‌شود که استخر سقف مشخص دارد، حداقل یک عضو SSH دارد و همه‌ی
        شمارنده‌ها تازه‌اند. خطای یک پنل هیچ‌وقت enforcement را مختل نمی‌کند."""
        limit = int(pool.get("limit_bytes") or 0)
        if limit <= 0 or len(members) < 2:
            return []
        remaining = max(limit - int((usage or {}).get("used_bytes") or 0), 0)
        results = []
        for res in poll_results:
            if res.get("service_kind") != "vpn" or not res.get("ok") or res.get("raw_used_bytes") is None:
                continue
            service_id = res["service_id"]
            try:
                cc, server = self._vpn_member(service_id)
                if not cc or not server:
                    continue
                provider = self.vpn_provider_factory(server)
                if not getattr(provider, "supports_data_limit_sync", False):
                    results.append({"service_id": service_id, "ok": True, "skipped": "unsupported_panel"})
                    continue
                raw_used = int(res["raw_used_bytes"])
                current = int(res.get("panel_limit_bytes") or 0)
                # سقف مثبت: 0 در پنل‌ها یعنی «نامحدود» پس هرگز 0 نمی‌نویسیم.
                target = max(raw_used + remaining, 1)
                if current and abs(target - current) < 1024 * 1024:
                    continue
                reenable = bool(current and raw_used >= current and target > raw_used)
                await provider.set_data_limit_bytes(cc["username"], target, reenable=reenable)
                results.append({"service_id": service_id, "ok": True, "limit_bytes": target})
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                logger.warning("Panel limit sync failed for pool=%s service=%s: %s", pool.get("id"), service_id, error)
                results.append({"service_id": service_id, "ok": False, "error": error})
        return results

    async def push_pool_expiry(self, pool_id):
        """انقضای فعلی استخر را روی همه‌ی حساب‌های SSH عضو آن (روی نود) می‌نویسد.
        بعد از تمدید سرویس ترکیبی صدا زده می‌شود تا نود حساب را با تاریخ قدیمی قطع نکند.
        خروجی: [{"service_id", "ok", "error"?}] و هیچ‌وقت exception پرتاب نمی‌کند."""
        pool = self.db.get_quota_pool(int(pool_id))
        results = []
        if not pool:
            return results
        for member in self.db.get_quota_members(int(pool_id)):
            if member["service_kind"] != "ssh":
                continue
            sid = member["service_id"]
            try:
                account, node = self._ssh_record(sid)
                if not account or not node:
                    raise RuntimeError("حساب SSH یا نود آن پیدا نشد")
                provider = self.ssh_provider_factory(node, secret_resolver=self.secret_resolver)
                await provider.update_account(sid, limit_bytes=0, expires_at=pool.get("expires_at"))
                results.append({"service_id": sid, "ok": True})
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                logger.warning("push_pool_expiry failed for pool=%s account=%s: %s", pool_id, sid, error)
                results.append({"service_id": sid, "ok": False, "error": error})
        return results

    def _pool_is_expired(self, pool):
        raw = pool.get("expires_at")
        if not raw:
            return False
        expires = _parse_time(raw)
        # Invalid legacy expiry metadata fails closed rather than becoming unlimited.
        return True if expires is None else datetime.now(timezone.utc) >= expires

    def _snapshots_fresh(self, members):
        now = datetime.now(timezone.utc)
        if not members:
            return True
        for member in members:
            stamp = _parse_time(member.get("reported_at"))
            if not stamp:
                return False
            age = (now - stamp).total_seconds()
            if age > self.max_snapshot_age_seconds or age < -self.max_snapshot_age_seconds:
                return False
        return True

    def _oldest_snapshot_age(self, members):
        now = datetime.now(timezone.utc)
        ages = []
        for member in members:
            stamp = _parse_time(member.get("reported_at"))
            if not stamp:
                return float("inf")
            ages.append(abs((now - stamp).total_seconds()))
        return max(ages) if ages else 0.0

    async def reconcile_pool(self, pool):
        pool_id = int(pool["id"])
        members_before = self.db.get_quota_members(pool_id)
        poll_results = []
        for member in members_before:
            try:
                if member["service_kind"] == "vpn":
                    result = await self._poll_vpn(member["service_id"])
                else:
                    result = await self._poll_ssh(member["service_id"])
                poll_results.append({"service_kind": member["service_kind"],
                                     "service_id": member["service_id"], **result})
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                poll_results.append({"service_kind": member["service_kind"],
                                     "service_id": member["service_id"], "ok": False, "error": error})

        # Expiry is enforceable without usage data. For volume-limited pools, stale
        # accounting fails closed: suspend members until every counter is fresh again.
        expired = self._pool_is_expired(pool)
        members = self.db.get_quota_members(pool_id)
        usage = self.db.get_quota_usage(pool_id)
        fresh = self._snapshots_fresh(members)
        limit = int(pool.get("limit_bytes") or 0)
        exceeded = bool(limit and usage and int(usage["used_bytes"]) >= limit)
        actions = []
        panel_sync = []
        if expired:
            for member in members:
                actions.append(await self._set_member_enabled(pool_id, member, False, "expired"))
            self.db.set_quota_pool_status(pool_id, "expired")
            state = "expired"
        elif limit and not fresh and self._oldest_snapshot_age(members) <= self.max_snapshot_age_seconds + self.stale_grace_seconds:
            state = "stale_grace"
        elif limit and not fresh:
            for member in members:
                actions.append(await self._set_member_enabled(pool_id, member, False, "stale"))
            self.db.set_quota_pool_status(pool_id, "stale")
            state = "stale"
        elif exceeded:
            for member in members:
                actions.append(await self._set_member_enabled(pool_id, member, False, "quota_exceeded"))
            self.db.set_quota_pool_status(pool_id, "exceeded")
            state = "exceeded"
        elif fresh:
            # Only restore services this reconciler itself marked as suspended.
            for member in members:
                prior = self.db.get_quota_enforcement_state(pool_id, member["service_kind"], member["service_id"])
                if prior and prior.get("is_disabled") and prior.get("reason") in {"quota_exceeded", "expired", "stale"}:
                    actions.append(await self._set_member_enabled(pool_id, member, True, None))
            # اگر استخر تمدید شده ولی انقضای محلی نود SSH هنوز قدیمی است، نود خودش حساب را
            # expired کرده؛ انقضا را با استخر هم‌گام و حساب را فعال می‌کنیم.
            healed = {a.get("service_id") for a in actions if a.get("enabled")}
            for res in poll_results:
                if (res.get("service_kind") == "ssh" and res.get("ok") and res.get("remote_status") == "expired"
                        and res["service_id"] not in healed):
                    member = next((m for m in members if m["service_kind"] == "ssh" and m["service_id"] == res["service_id"]), None)
                    if member:
                        actions.append(await self._set_member_enabled(pool_id, member, True, None))
            self.db.set_quota_pool_status(pool_id, "active")
            state = "active"
            panel_sync = await self._sync_vpn_panel_limits(pool, members, poll_results, usage)
        else:
            self.db.set_quota_pool_status(pool_id, "stale")
            state = "stale"

        all_enforced = all(a.get("ok") for a in actions) if actions else True
        stale_fail_closed = state == "stale" and limit > 0 and len(actions) == len(members)
        return {"pool_id": pool_id, "state": state, "used_bytes": int((usage or {}).get("used_bytes") or 0),
                "limit_bytes": limit, "snapshots_fresh": fresh, "poll_results": poll_results,
                "actions": actions, "panel_sync": panel_sync, "enforcement_complete": bool(all_enforced and (state in {"active", "exceeded", "expired"} or stale_fail_closed))}

    async def poll_once(self):
        results = []
        for pool in self.db.list_quota_pools(active_only=True):
            try:
                results.append(await self.reconcile_pool(pool))
            except Exception:
                logger.exception("Quota pool reconciliation failed for pool=%s", pool.get("id"))
                results.append({"pool_id": pool.get("id"), "state": "error", "enforcement_complete": False})
        return results

    async def run_forever(self):
        logger.info("Shared quota reconciler started (interval=%ss)", self.interval_seconds)
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Quota reconciler cycle failed")
            await asyncio.sleep(self.interval_seconds)
