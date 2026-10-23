import unittest

from tools.game_data import (
    HEALTH_CHEST_CLASS,
    chest_classnames,
    identity_fields,
    persist_flag,
)


class GameDataTests(unittest.TestCase):
    def test_identity_is_object_then_region_then_layer(self) -> None:
        self.assertEqual(identity_fields(), ("ObjectID", "RegionID", "LayerID"))

    def test_chest_scripts_write_triggered(self) -> None:
        self.assertEqual(persist_flag(), "Triggered")

    def test_health_chests_are_in_the_dump(self) -> None:
        names = chest_classnames()
        self.assertIn(HEALTH_CHEST_CLASS, names)
        self.assertTrue(names <= {"special_casket/chest_healthchest", "special_casket/chest_soulchest", "special_casket/chest_wrathchest"})


if __name__ == "__main__":
    unittest.main()
