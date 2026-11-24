# -*- coding: utf-8 -*-
"""QR تحویل سفارش نباید به‌خاطر کپشن قالب تحویل (HTML نامعتبر) از دست برود."""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")
for _m in ("aiogram", "aiogram.types", "aiogram.exceptions", "aiogram.enums", "qrcode", "qrcode.constants",
           "aiohttp", "PIL", "PIL.Image", "PIL.ImageDraw"):
    try:
        __import__(_m)
    except Exception:  # pragma: no cover - فقط وقتی وابستگی نصب نیست
        sys.modules[_m] = MagicMock()

import config_delivery as cd  # noqa: E402


class _Bot:
    token = "t"

    def __init__(self):
        self.calls = []

    async def send_photo(self, chat, photo, caption=None, parse_mode=None):
        self.calls.append(("photo", caption, parse_mode))
        if caption and parse_mode == "HTML" and "<bad>" in caption:
            raise RuntimeError("can't parse entities")

    async def send_message(self, chat, text, parse_mode=None):
        self.calls.append(("msg", text, parse_mode))


class QrFallbackTests(unittest.TestCase):
    def setUp(self):
        self._saved = (cd.qr_bytes_with_fallback, cd.prepare_delivery, cd._send_vpn_files)

        async def fake_qr(link, db=None):
            return b"PNG"

        async def fake_files(*a, **k):
            return None

        cd.qr_bytes_with_fallback = fake_qr
        cd._send_vpn_files = fake_files

    def tearDown(self):
        cd.qr_bytes_with_fallback, cd.prepare_delivery, cd._send_vpn_files = self._saved

    def _deliver(self, caption):
        async def fake_prep(*a, **k):
            return caption, []

        cd.prepare_delivery = fake_prep
        bot = _Bot()
        asyncio.run(cd.deliver_config_to_user(bot, 1, "p", ["vless://x"], db=None))
        return bot.calls

    def test_valid_caption_single_photo(self):
        calls = self._deliver("hello")
        self.assertEqual(calls, [("photo", "hello", "HTML")])

    def test_rejected_caption_still_sends_qr_and_text(self):
        calls = self._deliver("hello <bad> tag")
        self.assertIn(("photo", None, None), calls)
        self.assertTrue(any(c[0] == "msg" and "hello" in c[1] for c in calls))


if __name__ == "__main__":
    unittest.main()
