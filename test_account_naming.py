import os
import tempfile
import unittest

import account_naming as an
from database import Database


class AccountNamingTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        self.db.init_db(owner_id=1)
        self.sid = self.db.add_panel_server("p1", "pasarguard", "http://x", "u", "p")

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def server(self, **fields):
        if fields:
            self.db.update_panel_server(self.sid, **fields)
        return self.db.get_panel_server(self.sid)

    def test_legacy_is_inactive(self):
        server = self.server()
        self.assertFalse(an.is_active(server))
        self.assertEqual(an.build_username(self.db, server, 1, "abc"), "")
        self.assertTrue(an.needs_user_name(server))

    def test_all_modes(self):
        tg = 123456789
        h = an.user_hash(tg)
        cases = {
            "user_name": "bob",
            "hash_user_name": f"{h}_bob",
            "prefix_user_name": "pre_bob",
            "user_name_suffix": "bob_suf",
            "counter_user_name": "001_bob",
            "prefix_counter": "pre_001",
            "counter_suffix": "001_suf",
            "tgid_counter": f"{tg}_001",
        }
        for mode, expected in cases.items():
            self.db.reset_panel_naming_counter(self.sid)
            server = self.server(naming_mode=mode, naming_prefix="pre", naming_suffix="suf")
            self.assertEqual(an.build_username(self.db, server, tg, "bob"), expected, mode)

    def test_counter_increments_per_panel(self):
        server = self.server(naming_mode="prefix_counter", naming_prefix="a")
        names = [an.build_username(self.db, server, 1) for _ in range(3)]
        self.assertEqual(names, ["a_001", "a_002", "a_003"])
        other = self.db.add_panel_server("p2", "pasarguard", "http://y", "u", "p")
        self.assertEqual(self.db.next_panel_naming_counter(other), 1)

    def test_quantity_suffix_and_length(self):
        server = self.server(naming_mode="user_name")
        self.assertEqual(an.build_username(self.db, server, 1, "bob", 1, 3), "bob_2")
        long = an.build_username(self.db, self.server(naming_mode="prefix_user_name", naming_prefix="p" * 12), 1, "n" * 30)
        self.assertLessEqual(len(long), an.USERNAME_MAX_LEN)

    def test_needs_user_name(self):
        for mode in ("prefix_counter", "counter_suffix", "tgid_counter"):
            self.assertFalse(an.needs_user_name(self.server(naming_mode=mode)))
        for mode in ("user_name", "hash_user_name", "counter_user_name"):
            self.assertTrue(an.needs_user_name(self.server(naming_mode=mode)))

    def test_affix_validation_and_missing(self):
        self.assertTrue(an.valid_affix("ab_1"))
        self.assertFalse(an.valid_affix("a-b"))
        self.assertFalse(an.valid_affix("x" * 13))
        server = self.server(naming_mode="prefix_user_name")
        self.assertEqual(an.missing_affix("prefix_user_name", server), "prefix")


if __name__ == "__main__":
    unittest.main()
