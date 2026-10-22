import unittest

from ds_client.ap_catalog import ApCatalog, CatalogEntry
from ds_client.ap_sink import ApLocationSink, is_checked_transition
from ds_client.models import Event


class FakeRuntime:
    def __init__(self) -> None:
        self.locations: list[list[int]] = []
        self.goals = 0

    def submit_location_checks(self, location_ids: list[int]) -> None:
        self.locations.append(list(location_ids))

    def submit_goal(self) -> None:
        self.goals += 1


class SinkTests(unittest.TestCase):
    def test_zero_to_one_and_stay_one(self) -> None:
        self.assertTrue(is_checked_transition("0", "1"))
        self.assertTrue(is_checked_transition("", "1"))
        self.assertFalse(is_checked_transition("", "0"))
        self.assertFalse(is_checked_transition("1", "1"))

    def test_location_and_goal_events(self) -> None:
        catalog = ApCatalog(
            locations={
                "Crossroads Currency Chest Down Stairs": CatalogEntry(
                    "Crossroads Currency Chest Down Stairs", 172, "chest", "Crossroads"
                )
            },
            items={},
        )
        runtime = FakeRuntime()
        sink = ApLocationSink(runtime, catalog)
        sink.emit(
            Event(
                session_id=1,
                event_type="LOCATION_CHECK",
                address_hex="0x1",
                value_raw="1",
                prev_value="0",
                notes="",
                label="Crossroads Currency Chest Down Stairs",
                category="location_flag",
            )
        )
        sink.emit(
            Event(
                session_id=1,
                event_type="GOAL",
                address_hex="0x2",
                value_raw="1",
                prev_value="0",
                notes="",
                label="Abaddon The Destroyer defeated",
                category="misc",
            )
        )
        self.assertEqual(runtime.locations, [[172]])
        self.assertEqual(runtime.goals, 1)


if __name__ == "__main__":
    unittest.main()
