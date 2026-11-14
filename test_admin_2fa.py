import time
import unittest

from admin_panel import security as sec


class SessionTokenTests(unittest.TestCase):
    def test_last_activity_and_refresh_keep_exp(self):
        token = sec.create_session_token("k", 1, "u", "owner")
        payload = sec.verify_session_token("k", token)
        self.assertIn("la", payload)
        refreshed = sec.verify_session_token("k", sec.refresh_session_token("k", payload, payload["la"] + 40))
        self.assertEqual(refreshed["exp"], payload["exp"])
        self.assertEqual(refreshed["la"], payload["la"] + 40)

    def test_tampered_token_rejected(self):
        token = sec.create_session_token("k", 1, "u", "owner")
        self.assertIsNone(sec.verify_session_token("other", token))


class TotpTests(unittest.TestCase):
    def test_rfc6238_vector(self):
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(sec._hotp(secret, 59 // 30), "287082")

    def test_verify_and_replay(self):
        secret = sec.generate_totp_secret()
        step = int(time.time()) // sec.TOTP_STEP
        code = sec._hotp(secret, step)
        self.assertEqual(sec.verify_totp(secret, code), step)
        self.assertIsNone(sec.verify_totp(secret, code, last_step=step))
        self.assertIsNone(sec.verify_totp(secret, "000000" if code != "000000" else "111111"))

    def test_backup_codes(self):
        plain, hashed = sec.generate_backup_codes()
        self.assertEqual(len(plain), sec.BACKUP_CODE_COUNT)
        self.assertEqual(sec.hash_backup_code(plain[0].upper()), hashed[0])


if __name__ == "__main__":
    unittest.main()
