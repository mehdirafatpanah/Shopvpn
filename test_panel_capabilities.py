import unittest

from panel_capabilities import (
    USER_LIMIT,
    all_panels_support,
    normalize_user_limit,
    product_capabilities,
    provider_capabilities,
)


class _DB:
    def __init__(self, servers, extras=None):
        self.servers = servers
        self.extras = extras or []

    def get_panel_server(self, sid):
        return self.servers.get(int(sid))

    def get_product_extra_targets(self, product_id):
        return {"panels": list(self.extras), "ssh": []}


class PanelCapabilityTests(unittest.TestCase):
    def test_known_provider_capabilities(self):
        self.assertTrue(provider_capabilities("pasarguard")[USER_LIMIT])
        self.assertTrue(provider_capabilities("3xui")[USER_LIMIT])
        self.assertTrue(provider_capabilities("alireza")[USER_LIMIT])
        self.assertFalse(provider_capabilities("marzban")[USER_LIMIT])

    def test_all_selected_vpn_panels_are_required(self):
        supported = {1: {"id": 1, "panel_type": "pasarguard", "is_active": 1},
                     2: {"id": 2, "panel_type": "3xui", "is_active": 1}}
        mixed = {**supported, 3: {"id": 3, "panel_type": "marzban", "is_active": 1}}
        db = _DB(mixed, extras=[2])
        self.assertTrue(product_capabilities(db, {"id": 10, "provision_server_id": 1})[USER_LIMIT])
        db.extras = [3]
        self.assertFalse(product_capabilities(db, {"id": 10, "provision_server_id": 1})[USER_LIMIT])

    def test_ssh_does_not_disqualify_vpn_capability(self):
        panels = [{"id": 1, "panel_type": "pasarguard"}]
        self.assertTrue(all_panels_support(panels, USER_LIMIT))

    def test_legacy_selectable_limit_is_preserved(self):
        self.assertEqual(normalize_user_limit(0, 100, 5, supported=True), (0, 100, 5))
        self.assertEqual(normalize_user_limit(0, 100, 5, supported=False), (0, 0, 0))

    def test_invalid_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_user_limit(6, 100, 5, supported=True)
        with self.assertRaises(ValueError):
            normalize_user_limit(1, 100, 21, supported=True)


if __name__ == "__main__":
    unittest.main()
