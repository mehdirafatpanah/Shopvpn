import os
import tempfile
import unittest

from database import Database

try:
    from web_store.routes import _web_catalog_payload
except ModuleNotFoundError:
    _web_catalog_payload = None


class WebCatalogTreeTest(unittest.TestCase):
    def setUp(self):
        if _web_catalog_payload is None:
            self.skipTest("web dependencies not installed")
        self.db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.db.init_db(owner_id=1)

    def _prod(self, cat, name):
        return self.db.add_product(cat, name, 1000, "", 30, is_auto_provision=True, auto_provision_volume_gb=10)

    def test_parent_with_only_children_is_listed_with_totals(self):
        root = self.db.add_category("Root")
        kid = self.db.add_category("Kid", parent_id=root)
        grand = self.db.add_category("Grand", parent_id=kid)
        empty = self.db.add_category("Empty")
        self._prod(kid, "a")
        self._prod(grand, "b")
        self._prod(grand, "c")
        out = {c["id"]: c for c in _web_catalog_payload(self.db)}
        self.assertNotIn(empty, out)
        self.assertEqual(out[root]["total"], 3)
        self.assertEqual(out[root]["products"], [])
        self.assertEqual(out[kid]["total"], 3)
        self.assertEqual(len(out[kid]["products"]), 1)
        self.assertEqual(out[grand]["parent_id"], kid)
        self.assertEqual(out[kid]["parent_id"], root)
        self.assertEqual(out[root]["parent_id"], 0)
        self.assertEqual(out[grand]["name"], "Grand")
        self.assertEqual(out[grand]["path"], "Root › Kid › Grand")


if __name__ == "__main__":
    unittest.main()
