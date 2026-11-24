import unittest

try:
    import payg
except ModuleNotFoundError:
    payg = None


class _Db:
    def __init__(self, values):
        self.values = values

    def get_setting(self, key, default=""):
        return self.values.get(key, default)


class PaygEmojiTest(unittest.TestCase):
    def setUp(self):
        if payg is None:
            self.skipTest("bot dependencies not installed")

    def test_default_and_custom(self):
        self.assertEqual(payg.get_payg_emoji(_Db({})), "💳")
        self.assertEqual(payg.get_payg_emoji(_Db({"payg_emoji": " ⚡ "})), "⚡")

    def test_button_texts_cover_old_and_new(self):
        texts = payg.button_texts(_Db({"payg_emoji": "⚡"}))
        self.assertIn("⚡ پرداخت به‌ازای مصرف", texts)
        self.assertIn("💳 پرداخت به‌ازای مصرف", texts)
        self.assertEqual(len(texts), len(set(texts)))


if __name__ == "__main__":
    unittest.main()
