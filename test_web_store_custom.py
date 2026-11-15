import importlib.util
import os
import unittest

# customize.py عمداً بدون وابستگی سنگین است؛ مستقیم بارگذاری می‌شود (بدون FastAPI).
_spec = importlib.util.spec_from_file_location(
    "web_store_customize", os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_store", "customize.py"))
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)


def getter(values):
    return lambda key, default="": values.get(key, default)


class LinksTest(unittest.TestCase):
    def test_safe_link(self):
        self.assertEqual(wc.safe_link("@shop_support"), "https://t.me/shop_support")
        self.assertEqual(wc.safe_link("t.me/abc"), "https://t.me/abc")
        self.assertEqual(wc.safe_link("https://example.com/a?b=1"), "https://example.com/a?b=1")
        self.assertEqual(wc.safe_link("javascript:alert(1)"), "")
        self.assertEqual(wc.safe_link("https://a.com/ x"), "")
        self.assertEqual(wc.safe_link("@ab"), "")

    def test_https_only(self):
        self.assertEqual(wc.safe_https_url("https://cdn.x.com/i.png"), "https://cdn.x.com/i.png")
        self.assertEqual(wc.safe_https_url("http://cdn.x.com/i.png"), "")
        self.assertEqual(wc.safe_https_url('https://x.com/"onload=1'), "")
        self.assertEqual(wc.safe_https_url("data:image/png;base64,AAA"), "")

    def test_instagram_and_email(self):
        self.assertEqual(wc.safe_instagram("@my.shop"), "https://instagram.com/my.shop")
        self.assertEqual(wc.safe_instagram("instagram.com/my.shop"), "https://instagram.com/my.shop")
        self.assertEqual(wc.safe_instagram("https://evil.com/instagram.com/x"), "")
        self.assertEqual(wc.safe_email("help@shop.ir"), "help@shop.ir")
        self.assertEqual(wc.safe_email("not an email"), "")


class BlocksTest(unittest.TestCase):
    def test_faq_parse(self):
        text = "سؤال اول؟\nپاسخ اول\nادامه پاسخ\n\nفقط عنوان بدون پاسخ\n\nسؤال دوم؟\nپاسخ دوم"
        faq = wc.parse_faq(text)
        self.assertEqual(faq, [["سؤال اول؟", "پاسخ اول\nادامه پاسخ"], ["سؤال دوم؟", "پاسخ دوم"]])

    def test_terms_parse(self):
        terms = wc.parse_terms("قوانین\nمورد یک\nمورد دو\n\nتماس\nپشتیبانی ۲۴ ساعته")
        self.assertEqual(terms, [["قوانین", ["مورد یک", "مورد دو"]], ["تماس", ["پشتیبانی ۲۴ ساعته"]]])

    def test_limits(self):
        many = "\n\n".join("q%d\na%d" % (i, i) for i in range(100))
        self.assertEqual(len(wc.parse_faq(many)), wc.MAX_FAQ_ITEMS)
        long_q = "q" * 1000 + "\n" + "a" * 5000
        item = wc.parse_faq(long_q)[0]
        self.assertEqual(len(item[0]), wc.MAX_FAQ_Q)
        self.assertEqual(len(item[1]), wc.MAX_FAQ_A)

    def test_empty(self):
        self.assertEqual(wc.parse_faq(""), [])
        self.assertEqual(wc.parse_terms(None), [])


class PayloadTest(unittest.TestCase):
    def test_defaults_are_quiet(self):
        out = wc.build_custom_payload(getter({}))
        self.assertEqual(out, {"default_sort": "value"})

    def test_notice(self):
        out = wc.build_custom_payload(getter({
            "web_store_notice_enabled": "1", "web_store_notice_text": "  تخفیف ویژه  ",
            "web_store_notice_link": "@promo_chan", "web_store_notice_style": "success"}))
        self.assertEqual(out["notice"], {"text": "تخفیف ویژه", "link": "https://t.me/promo_chan", "style": "success"})

    def test_notice_needs_text_and_valid_style(self):
        self.assertNotIn("notice", wc.build_custom_payload(getter({"web_store_notice_enabled": "1"})))
        out = wc.build_custom_payload(getter({
            "web_store_notice_enabled": "1", "web_store_notice_text": "x", "web_store_notice_style": "<b>"}))
        self.assertEqual(out["notice"]["style"], "info")
        off = wc.build_custom_payload(getter({"web_store_notice_enabled": "0", "web_store_notice_text": "x"}))
        self.assertNotIn("notice", off)

    def test_maintenance(self):
        out = wc.build_custom_payload(getter({"web_store_maintenance": "1"}))
        self.assertEqual(out["maintenance"], {"text": ""})
        out = wc.build_custom_payload(getter({"web_store_maintenance": "1", "web_store_maintenance_text": "تا ساعت ۸"}))
        self.assertEqual(out["maintenance"], {"text": "تا ساعت ۸"})
        self.assertNotIn("maintenance", wc.build_custom_payload(getter({"web_store_maintenance": "0"})))

    def test_footer(self):
        out = wc.build_custom_payload(getter({
            "web_store_footer_text": "© شاپ", "web_store_channel_url": "t.me/ch",
            "web_store_instagram_url": "bad value", "web_store_email": "a@b.ir"}))
        self.assertEqual(out["footer"], {"text": "© شاپ", "channel": "https://t.me/ch", "instagram": "", "email": "a@b.ir"})

    def test_sort_validation(self):
        self.assertEqual(wc.build_custom_payload(getter({"web_store_default_sort": "low"}))["default_sort"], "low")
        self.assertEqual(wc.build_custom_payload(getter({"web_store_default_sort": "zzz"}))["default_sort"], "value")

    def test_hide_soldout_and_head(self):
        self.assertTrue(wc.hide_soldout(getter({"web_store_hide_soldout": "1"})))
        self.assertFalse(wc.hide_soldout(getter({})))
        head = wc.head_assets(getter({"web_store_favicon": "https://x.com/f.png", "web_store_og_image": "http://x.com/o.png"}))
        self.assertEqual(head, {"favicon": "https://x.com/f.png", "og_image": ""})


class MaintenanceGuardTest(unittest.TestCase):
    def test_blocked_paths(self):
        self.assertTrue(wc.is_blocked_in_maintenance("POST", "/api/orders"))
        self.assertTrue(wc.is_blocked_in_maintenance("POST", "/api/orders/12/crypto-invoice"))
        self.assertTrue(wc.is_blocked_in_maintenance("POST", "/api/orders/12/extra-invoice/zarinpal"))
        self.assertTrue(wc.is_blocked_in_maintenance("POST", "/api/orders/12/card-auto-invoice"))
        self.assertTrue(wc.is_blocked_in_maintenance("POST", "/api/custom-configs/3/renew-full"))

    def test_allowed_paths(self):
        self.assertFalse(wc.is_blocked_in_maintenance("GET", "/api/orders"))
        self.assertFalse(wc.is_blocked_in_maintenance("POST", "/api/orders/12/receipt"))
        self.assertFalse(wc.is_blocked_in_maintenance("POST", "/api/tickets"))
        self.assertFalse(wc.is_blocked_in_maintenance("POST", "/api/web/login/start"))
        self.assertFalse(wc.is_blocked_in_maintenance("GET", "/api/custom-configs/3/renewal-full-plans"))

    def test_message(self):
        self.assertEqual(wc.maintenance_message(getter({})), "")
        self.assertEqual(wc.maintenance_message(getter({"web_store_maintenance": "1"})), "__default__")
        self.assertEqual(wc.maintenance_message(getter({"web_store_maintenance": "1", "web_store_maintenance_text": "x"})), "x")


if __name__ == "__main__":
    unittest.main()
