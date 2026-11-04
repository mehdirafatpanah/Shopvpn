# -*- coding: utf-8 -*-
"""Regression tests for per-product VPN panel destination selection."""
import json
import os
import tempfile
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("OWNER_ID", "1")
import config
from database import Database
from product_targets import apply_product_target, build_target_config


class ProductTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="product_targets_")
        config.DB_PATH = os.path.join(self.tmp, "db.sqlite")
        self.db = Database(config.DB_PATH)
        self.db.init_db(owner_id=1)
        self.category = self.db.add_category("VPN")
        self.server_id = self.db.add_panel_server("Panel", "pasarguard", "https://panel.invalid", "u", "p")

    def test_product_target_config_roundtrip_and_legacy_null(self):
        cfg = {"field": "group_ids", "value": [11, 12]}
        pid = self.db.add_product(self.category, "New", 1000, "", 30, True, 10,
                                  self.server_id, provision_target_config=cfg)
        product = self.db.get_product(pid)
        self.assertEqual(json.loads(product["provision_target_config"]), cfg)

        server = self.db.get_panel_server(self.server_id)
        # A product override is isolated from the shared panel record.
        with self.db._get_conn() as conn:
            conn.execute("UPDATE panel_servers SET group_ids=? WHERE id=?", ("[1,2]", self.server_id))
        server = self.db.get_panel_server(self.server_id)
        effective = apply_product_target(server, product)
        self.assertEqual(json.loads(effective["group_ids"]), [11, 12])
        self.assertEqual(json.loads(server["group_ids"]), [1, 2])

        legacy_id = self.db.add_product(self.category, "Legacy", 1000, "", 30, True, 10, self.server_id)
        legacy = self.db.get_product(legacy_id)
        self.assertIsNone(legacy["provision_target_config"])
        self.assertIs(apply_product_target(server, legacy), server)

    def test_target_config_is_carried_to_created_service_for_renewal(self):
        cfg = {"field": "group_ids", "value": [21], "panel_server_id": self.server_id}
        cc_id = self.db.add_custom_config(123, self.server_id, "u1", 5, 30, "https://sub.invalid/u1",
                                          source="direct_product", panel_target_config=cfg)
        with self.db._get_conn() as conn:
            row = conn.execute("SELECT panel_target_config FROM custom_configs WHERE id=?", (cc_id,)).fetchone()
        self.assertEqual(json.loads(row["panel_target_config"]), cfg)

    def test_target_override_does_not_leak_to_other_panels(self):
        cfg = {"field": "xui_inbound_ids", "value": [7], "panel_server_id": 10}
        server = {"id": 11, "panel_type": "3xui", "xui_inbound_ids": "[1]"}
        effective = apply_product_target(server, {"provision_target_config": json.dumps(cfg)})
        self.assertIs(effective, server)

    def test_inbound_selection_is_product_scoped(self):
        server = {"panel_type": "3xui", "xui_inbound_ids": "[1]", "xui_inbound_id": 1}
        cfg = build_target_config(server, ["7", "9"])
        self.assertEqual(cfg, {"field": "xui_inbound_ids", "value": [7, 9]})
        effective = apply_product_target(server, {"provision_target_config": json.dumps(cfg)})
        self.assertEqual(json.loads(effective["xui_inbound_ids"]), [7, 9])
        self.assertEqual(json.loads(server["xui_inbound_ids"]), [1])

    def test_marzban_protocol_map_selection(self):
        server = {"panel_type": "marzban", "group_ids": json.dumps({"vless": ["A", "B"], "vmess": ["C"]})}
        cfg = build_target_config(server, ["vless::B", "vmess::C"])
        self.assertEqual(cfg["value"], {"vless": ["B"], "vmess": ["C"]})

    def test_live_marzban_inbounds_can_exceed_sample_template(self):
        server = {"panel_type": "marzban", "group_ids": json.dumps({"vless": ["sample-only"]})}
        live = {"field": "group_ids", "kind": "protocol_map", "choices": [
            {"value": "vless::production", "label": "VLESS · production"},
            {"value": "trojan::edge", "label": "TROJAN · edge"},
        ]}
        cfg = build_target_config(server, ["vless::production", "trojan::edge"], live)
        self.assertEqual(cfg["value"], {"vless": ["production"], "trojan": ["edge"]})

    def test_live_marzneshin_services_can_exceed_sample_template(self):
        server = {"panel_type": "marzneshin", "group_ids": "[1]"}
        live = {"field": "group_ids", "kind": "list", "choices": [
            {"value": "1", "label": "Basic"}, {"value": "9", "label": "Premium"}
        ]}
        cfg = build_target_config(server, ["9"], live)
        self.assertEqual(cfg["value"], [9])

    def test_live_scalar_target_is_product_scoped(self):
        server = {"id": 4, "panel_type": "mikrotik", "group_ids": '"old-profile"'}
        live = {"field": "group_ids", "kind": "scalar", "choices": [
            {"value": "gold", "label": "gold"}, {"value": "silver", "label": "silver"}
        ]}
        cfg = build_target_config(server, ["gold"], live)
        self.assertEqual(cfg, {"field": "group_ids", "value": "gold", "panel_server_id": 4})
        effective = apply_product_target(server, {"provision_target_config": json.dumps(cfg)})
        self.assertEqual(json.loads(effective["group_ids"]), "gold")
        self.assertEqual(json.loads(server["group_ids"]), "old-profile")

    def test_live_destination_must_still_exist_in_snapshot(self):
        server = {"panel_type": "marzneshin", "group_ids": "[1]"}
        live = {"field": "group_ids", "kind": "list", "choices": [{"value": "1", "label": "Basic"}]}
        with self.assertRaisesRegex(ValueError, "دیگر در پنل وجود ندارد"):
            build_target_config(server, ["999"], live)


if __name__ == "__main__":
    unittest.main()
