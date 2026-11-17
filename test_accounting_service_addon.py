import json
import unittest

import accounting


class FakeDB:
    def __init__(self, links=None, quota_services=None):
        self.settings = {
            "acct_formulas": "{}",
            "acct_panel_costs": json.dumps({
                "1": {
                    "in-a": {"gb_rate": 100, "user_rate": 200},
                    "in-b": {"gb_rate": 300, "user_rate": 400},
                },
                "2": {"in-c": {"gb_rate": 500, "user_rate": 600}},
            }),
        }
        self.links = links or []
        self.quota_services = quota_services or []

    def get_setting(self, key, default=""):
        return self.settings.get(key, default)

    def get_panel_server(self, panel_id):
        return {"id": panel_id}

    def panel_links_for_config(self, config_id, active_only=True):
        return self.links

    def quota_pool_for_custom_config(self, config_id):
        return {"id": 9} if self.quota_services else None

    def get_quota_usage(self, pool_id):
        return {"services": self.quota_services}


class AccountingServiceAddonTests(unittest.TestCase):
    def test_single_panel_sums_selected_group_rates(self):
        db = FakeDB()
        cc = {
            "id": 7, "panel_server_id": 1,
            "panel_target_config": json.dumps({"field": "xui_inbound_ids", "value": ["in-a", "in-b"]}),
        }
        result = accounting.suggest_service_addon(db, cc, 2, "gb")
        self.assertEqual(result["unit_cost"], 400)
        self.assertEqual(result["raw"], 1040.0)
        self.assertEqual(result["panels"], 1)

    def test_multi_panel_uses_average_of_panel_totals(self):
        db = FakeDB(links=[{
            "panel_server_id": 2,
            "target_config": json.dumps({"field": "xui_inbound_ids", "value": ["in-c"]}),
        }])
        cc = {
            "id": 7, "panel_server_id": 1,
            "panel_target_config": json.dumps({"field": "xui_inbound_ids", "value": ["in-a", "in-b"]}),
        }
        result = accounting.suggest_service_addon(db, cc, 2, "gb")
        self.assertEqual(result["unit_cost"], 450)
        self.assertEqual(result["raw"], 1170.0)
        self.assertEqual(result["panels"], 2)

    def test_missing_selected_destination_tariff_is_not_silently_ignored(self):
        db = FakeDB()
        cc = {"id": 7, "panel_server_id": 1,
              "panel_target_config": json.dumps({"field": "xui_inbound_ids", "value": ["in-a", "not-configured"]})}
        with self.assertRaisesRegex(ValueError, "همه گروه‌ها"):
            accounting.suggest_service_addon(db, cc, 1, "gb")

    def test_custom_formula_receives_node_count_and_configured_rounding(self):
        db = FakeDB(quota_services=[{"node_id": 11}, {"node_id": 11}, {"node_id": 12}])
        db.settings["acct_node_costs"] = json.dumps({"11": {"gb_rate": 100}, "12": {"gb_rate": 300}})
        db.settings["acct_formulas"] = json.dumps({
            "constants": {"margin": 0, "fixed_fee": 0},
            "round_to": 100,
            "formulas": {"payg_gb": "cost_gb + nodes * 50"},
        })
        cc = {"id": 7, "panel_server_id": 1,
              "panel_target_config": json.dumps({"field": "xui_inbound_ids", "value": ["in-a"]})}
        result = accounting.suggest_service_addon(db, cc, 1, "gb")
        # Mean of panel tariff (100) and two distinct node tariffs (100, 300) rounds to 167;
        # formula sees two unique nodes and rounds the final amount up to 300.
        self.assertEqual(result["nodes"], 2)
        self.assertEqual(result["raw"], 267.0)
        self.assertEqual(result["price"], 300)

    def test_user_addon_multiplies_incremental_users(self):
        db = FakeDB()
        cc = {
            "id": 7, "panel_server_id": 1,
            "panel_target_config": json.dumps({"field": "xui_inbound_ids", "value": ["in-b"]}),
        }
        result = accounting.suggest_service_addon(db, cc, 3, "user")
        self.assertEqual(result["unit_cost"], 400)
        self.assertEqual(result["raw"], 1560.0)


if __name__ == "__main__":
    unittest.main()
