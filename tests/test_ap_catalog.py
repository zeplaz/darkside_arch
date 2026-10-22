import unittest

from ds_client.ap_catalog import load_catalog


class CatalogTests(unittest.TestCase):
    def test_labels_not_ids_in_targets_contract(self) -> None:
        catalog = load_catalog()
        self.assertEqual(
            catalog.location_id("Crossroads Currency Chest Down Stairs"), 128
        )
        self.assertEqual(catalog.item_id("Armageddon Blade Shards"), 133)
        self.assertEqual(catalog.item_id("Armageddon Blade"), 132)
        self.assertEqual(catalog.item_id("Beholder Key"), 59)
        self.assertEqual(catalog.item_id("Heart of the Chosen"), 87)
        self.assertEqual(catalog.item_id("Progressive Gauntlet"), 143)
        self.assertTrue(catalog.is_goal_label("Abaddon The Destroyer defeated"))
        self.assertIsNone(catalog.location_id("not a real location"))


if __name__ == "__main__":
    unittest.main()
