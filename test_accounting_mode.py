import json
import unittest

import accounting


class FakeDB:
    def __init__(self, panels, cfg=None):
        self.s = {"acct_panel_costs": json.dumps(panels), "acct_node_costs": "{}"}
        if cfg is not None:
            self.s["acct_formulas"] = json.dumps(cfg)

    def get_setting(self, key, default=""):
        return self.s.get(key, default)

    def set_setting(self, key, value):
        self.s[key] = value


PANELS = {"1": {"a": {"gb_rate": 100, "day_rate": 0, "user_rate": 0}, "b": {"gb_rate": 300, "day_rate": 0, "user_rate": 0}}}
CFG = {"constants": {"margin": 0, "fixed_fee": 0}, "round_to": 1,
       "formulas": {"panel": "gb*cost_gb"}}


class CalcModeTest(unittest.TestCase):
    def suggest(self, mode):
        db = FakeDB(PANELS, dict(CFG, calc_mode=mode))
        return accounting.suggest(db, "panel", [{"id": 1, "targets": []}], [], 1, 0, 1)

    def test_default_is_precise(self):
        self.assertEqual(accounting.get_config(FakeDB(PANELS))["calc_mode"], "precise")

    def test_precise_uses_max(self):
        self.assertEqual(self.suggest("precise")["price"], 300)

    def test_average_uses_mean(self):
        self.assertEqual(self.suggest("average")["price"], 200)

    def test_save_rejects_bad_mode(self):
        with self.assertRaises(ValueError):
            accounting.save_config(FakeDB(PANELS), {"constants": {"margin": 0, "fixed_fee": 0}, "calc_mode": "x"})

    def test_save_roundtrip(self):
        db = FakeDB(PANELS)
        accounting.save_config(db, {"constants": {"margin": 0, "fixed_fee": 0}, "calc_mode": "average"})
        self.assertEqual(accounting.get_config(db)["calc_mode"], "average")


if __name__ == "__main__":
    unittest.main()
