import unittest

from ds_client.ap_catalog import load_catalog


class CatalogTests(unittest.TestCase):
    def test_labels_not_ids_in_targets_contract(self) -> None:
        catalog = load_catalog()
        self.assertEqual(catalog.location_id("Seraphim Hotel Life Chest 1"), 200)
        self.assertEqual(catalog.location_id("Seraphim Hotel Life Chest 2"), 201)
        self.assertEqual(
            catalog.location_id("Crossroads Currency Chest Down Back Alley Stairs"), 600
        )
        self.assertEqual(
            catalog.location_id("Crossroads Currency Chest South Crater"), 602
        )
        self.assertEqual(catalog.item_id("Armageddon Blade Shards"), 103)
        self.assertEqual(catalog.item_id("Armageddon Blade"), 102)
        self.assertEqual(catalog.item_id("Beholder Key"), 60)
        self.assertEqual(catalog.item_id("Heart of the Chosen"), 90)
        self.assertEqual(catalog.item_id("Progressive Gauntlet"), 113)
        self.assertTrue(catalog.is_goal_label("Abaddon Destroyer defeated"))
        self.assertIsNone(catalog.location_id("not a real location"))


if __name__ == "__main__":
    unittest.main()
