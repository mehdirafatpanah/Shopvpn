# -*- coding: utf-8 -*-
"""LICENSE section 6 source offer. Run: python -m unittest test_source_offer -v"""
import os
import unittest

import source_offer


class SourceOfferTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("SHOPVPN_SOURCE_URL", None)

    def test_default_is_official_repo(self):
        os.environ.pop("SHOPVPN_SOURCE_URL", None)
        self.assertEqual(source_offer.source_url(), source_offer.OFFICIAL_REPO)

    def test_custom_url_and_bad_values(self):
        os.environ["SHOPVPN_SOURCE_URL"] = "https://github.com/me/fork"
        self.assertEqual(source_offer.source_url(), "https://github.com/me/fork")
        self.assertTrue(source_offer.license_url().endswith("/LICENSE"))
        os.environ["SHOPVPN_SOURCE_URL"] = "javascript:alert(1)"
        self.assertEqual(source_offer.source_url(), source_offer.OFFICIAL_REPO)

    def test_text_both_languages_and_escaping(self):
        os.environ["SHOPVPN_SOURCE_URL"] = 'https://x.io/a"b<c'
        for lang in ("fa", "en"):
            t = source_offer.build_text(lang)
            self.assertNotIn('"b<c', t)
            self.assertIn(source_offer.LICENSE_NAME, t)


if __name__ == "__main__":
    unittest.main()
