from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class SSHUDPGWInstallTests(unittest.TestCase):
    def test_installer_resolves_real_binary_and_never_writes_empty_execstart(self):
        script = (ROOT / "deploy/install-shopvpn-ssh-agent.sh").read_text(encoding="utf-8")
        self.assertIn('command -v badvpn-udpgw', script)
        self.assertIn('/usr/local/bin/badvpn-udpgw', script)
        self.assertIn('if [[ -z "${UDPGW_BIN}" || ! -x "${UDPGW_BIN}" ]]', script)
        self.assertIn('ExecStart=${UDPGW_BIN}', script)
        self.assertIn('systemctl is-active --quiet shopvpn-udpgw.service', script)
        self.assertIn("127\\.0\\.0\\.1:7300", script)
        self.assertIn('exit 1', script)

    def test_auto_installer_checks_udpgw_after_script(self):
        source = (ROOT / "ssh_auto_install.py").read_text(encoding="utf-8")
        self.assertIn('systemctl is-active shopvpn-udpgw.service', source)
        self.assertIn('127', source)
        self.assertIn('7300', source)
        self.assertIn('UDPGW نصب شد اما سرویس یا پورت', source)


if __name__ == "__main__":
    unittest.main()
