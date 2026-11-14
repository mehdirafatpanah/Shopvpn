import unittest

import home_tiles as ht


class HomeTilesTest(unittest.TestCase):
    def test_default_when_not_customized(self):
        self.assertEqual(ht.tile_order(["btn_contact", "btn_buy"], [5], False),
                         ht.DEFAULT_TILES + ["cm:5"])

    def test_follows_bot_order(self):
        order = ht.tile_order(["btn_contact", "custom_menu:5", "btn_buy", "btn_my_orders"], [5], True)
        self.assertEqual(order[:6], ["support", "cm:5", "store", "services", "wallet", "profile"])

    def test_missing_tiles_appended_and_no_duplicates(self):
        order = ht.tile_order(["btn_buy"], [5, 6], True)
        self.assertEqual(order[0], "store")
        self.assertEqual(len(order), len(set(order)))
        self.assertEqual(set(order), set(ht.DEFAULT_TILES) | {"cm:5", "cm:6"})

    def test_unknown_or_inactive_custom_ignored(self):
        order = ht.tile_order(["custom_menu:9", "btn_tutorial", "bogus"], [5], True)
        self.assertNotIn("cm:9", order)
        self.assertIn("cm:5", order)


if __name__ == "__main__":
    unittest.main()


class HomeRowsTest(unittest.TestCase):
    ORDER = ["btn_buy", "btn_my_orders", "btn_test", "btn_contact", "btn_reseller_panel", "custom_menu:5"]

    def test_none_when_not_customized(self):
        self.assertIsNone(ht.tile_rows(self.ORDER, [5], None))

    def test_breaks_make_rows(self):
        rows = ht.tile_rows(self.ORDER, [5], ["btn_my_orders", "btn_test", "btn_reseller_panel"])
        self.assertEqual(rows, [["store"], ["services", "wallet", "profile"], ["test", "support"], ["reseller", "cm:5"]])

    def test_no_breaks_means_one_row(self):
        rows = ht.tile_rows(self.ORDER, [5], [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 7)

    def test_missing_tiles_appended(self):
        rows = ht.tile_rows(["btn_buy"], [5], [])
        flat = [t for r in rows for t in r]
        self.assertEqual(set(flat), set(ht.DEFAULT_TILES) | {"cm:5"})
        self.assertEqual(len(flat), len(set(flat)))
