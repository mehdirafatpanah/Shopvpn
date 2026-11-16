import asyncio
import unittest


class _Db:
    def __init__(self, settings):
        self.settings = settings

    def get_setting(self, key, default=""):
        return self.settings.get(key, default)

    def get_user_language(self, user_id):
        return "fa"

    def _get_conn(self):
        raise RuntimeError("no connection")


class CycleTextTest(unittest.TestCase):
    def test_values(self):
        import payg
        cases = {"600": "۱۰ دقیقه", "60": "یک دقیقه", "3600": "یک ساعت", "7200": "۲ ساعت", "90": "۹۰ ثانیه", "": "۱۰ دقیقه", "x": "۱۰ دقیقه", "5": "یک دقیقه"}
        for raw, expected in cases.items():
            self.assertEqual(payg.cycle_text(_Db({"payg_cycle_seconds": raw})), expected)


class RenewMarkupTest(unittest.TestCase):
    def run_markup(self, db, kind, config_id):
        import renewal_reminders as rr
        return asyncio.run(rr._renew_markup(db, kind, config_id, 1))

    def test_custom_gets_full_renewal_button(self):
        markup, label = self.run_markup(_Db({}), "custom", 7)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "svc_renew:full:x7")
        self.assertIn("تمدید کامل", label)

    def test_stock_config_gets_time_renewal_button(self):
        markup, _ = self.run_markup(_Db({}), "config", 9)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "svc_renew:time:c9")

    def test_disabled_toggle_removes_button(self):
        markup, label = self.run_markup(_Db({"svc_show_renew_full": "0"}), "custom", 7)
        self.assertIsNone(markup)
        self.assertEqual(label, "")


if __name__ == "__main__":
    unittest.main()
