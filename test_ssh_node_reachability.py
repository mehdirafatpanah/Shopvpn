# -*- coding: utf-8 -*-
"""Regression tests: SSH node ports/ICMP must be opened (client shows «connected» but no ping otherwise)."""
import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
import types

try:
    import aiohttp  # noqa: F401
except ImportError:  # sandbox without aiohttp: the agent only needs `web` at import time
    _stub = types.ModuleType("aiohttp")
    _stub.web = types.ModuleType("aiohttp.web")
    sys.modules["aiohttp"], sys.modules["aiohttp.web"] = _stub, _stub.web

import ssh_node_agent
import ssh_service


def _agent(tmp):
    return ssh_node_agent.Agent("t" * 40, str(Path(tmp) / "agent.db"))


class _Res:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class FirewallTests(unittest.TestCase):
    def test_default_range_is_opened_in_ufw_iptables_and_nft(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            calls = []

            def fake_run(*args, **kw):
                calls.append(args)
                if args[:2] == ("ufw", "status"):
                    return _Res(0, "Status: active")
                if args[0] in ("iptables", "ip6tables") and args[1] == "-C":
                    return _Res(1)
                if args[:4] == ("nft", "list", "chain", "inet"):
                    return _Res(0, "chain input { policy drop; }")
                return _Res(0)

            with mock.patch.object(agent, "_run", side_effect=fake_run), \
                 mock.patch("ssh_node_agent.shutil.which", return_value="/usr/sbin/x"):
                agent._open_firewall_range(20000, 39999)
            flat = [" ".join(map(str, c)) for c in calls]
            self.assertTrue(any(c.startswith("iptables -I INPUT 1 -p tcp --dport 20000:39999") for c in flat), flat)
            self.assertTrue(any(c.startswith("ip6tables -I INPUT 1") for c in flat))
            self.assertIn("ufw allow 20000:39999/tcp", flat)
            self.assertTrue(any(c.startswith("nft insert rule inet filter input tcp dport 20000-39999 accept") for c in flat), flat)

    def test_agent_port_is_never_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            with mock.patch.object(agent, "_firewall_open_ranges") as opener:
                agent._open_firewall_range(1024, 40000)  # contains 22/8765 -> must be dropped
            opener.assert_called_once_with([])

    def test_account_ports_outside_default_range_are_listed_individually(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            with agent._conn() as db:
                db.execute("INSERT INTO accounts(account_id,username,ssh_port,status,created_at,updated_at) VALUES('a','usera',45000,'active','x','x')")
                db.execute("INSERT INTO accounts(account_id,username,ssh_port,status,created_at,updated_at) VALUES('b','userb',25000,'active','x','x')")
            ranges = agent._firewall_ranges()
            self.assertIn((20000, 39999), ranges)
            self.assertIn((45000, 45000), ranges)
            self.assertNotIn((25000, 25000), ranges)

    def test_icmp_adds_nft_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            seen = []
            with mock.patch.object(agent, "_nft_input_accept", side_effect=lambda t, r: seen.append((t, r))), \
                 mock.patch.object(agent, "_run", return_value=_Res(0)), \
                 mock.patch("ssh_node_agent.shutil.which", return_value=None), \
                 mock.patch.object(ssh_node_agent.Path, "write_text"):
                agent._ensure_icmp_ping()
            tags = {t for t, _ in seen}
            self.assertEqual(tags, {"shopvpn-icmp4", "shopvpn-icmp6"})

    def test_prefer_ipv4_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "gai.conf"
            conf.write_text("#precedence ::ffff:0:0/96  100\nlabel ::1/128 0\n", encoding="utf-8")
            with mock.patch.object(ssh_node_agent, "GAI_CONF", conf):
                ssh_node_agent.Agent._prefer_ipv4_resolution()
                first = conf.read_text(encoding="utf-8")
                ssh_node_agent.Agent._prefer_ipv4_resolution()
            self.assertIn("\nprecedence ::ffff:0:0/96  100", "\n" + first)
            self.assertNotIn("#precedence", first)
            self.assertEqual(first, conf.read_text(encoding="utf-8"))
            empty = Path(tmp) / "empty.conf"
            with mock.patch.object(ssh_node_agent, "GAI_CONF", empty):
                ssh_node_agent.Agent._prefer_ipv4_resolution()
            self.assertIn("precedence ::ffff:0:0/96  100", empty.read_text(encoding="utf-8"))

    def test_diagnose_runs_and_reports_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            with mock.patch.object(ssh_node_agent.Agent, "_tcp_probe", return_value=(False, "no network")), \
                 mock.patch("http.client.HTTPConnection", side_effect=OSError("offline")), \
                 mock.patch("ssh_node_agent.socket.getaddrinfo", side_effect=OSError("dns")):
                checks = agent.diagnose()
            names = {c["name"] for c in checks}
            self.assertTrue({"udpgw_7300", "icmp_sysctl", "firewall_ports", "dns_resolve", "egress_ipv4",
                             "http_generate_204", "sshd_listeners"} <= names)
            self.assertFalse(next(c for c in checks if c["name"] == "dns_resolve")["ok"])


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def _serve(self, banner):
        async def handle(reader, writer):
            writer.write(banner)
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return server, server.sockets[0].getsockname()[1]

    async def test_open_ssh_port(self):
        server, port = await self._serve(b"SSH-2.0-OpenSSH_9.6\r\n")
        async with server:
            self.assertTrue((await ssh_service.probe_ssh_endpoint("127.0.0.1", port))["ok"])

    async def test_non_ssh_banner(self):
        server, port = await self._serve(b"HTTP/1.1 400\r\n")
        async with server:
            result = await ssh_service.probe_ssh_endpoint("127.0.0.1", port)
        self.assertFalse(result["ok"])

    async def test_closed_port(self):
        server, port = await self._serve(b"SSH-2.0-x\r\n")
        server.close()
        await server.wait_closed()
        result = await ssh_service.probe_ssh_endpoint("127.0.0.1", port, timeout=2)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
