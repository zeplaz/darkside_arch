import tempfile
import unittest
from pathlib import Path

from ds_client.ap_protocol import NetworkItem
from ds_client.ap_state import ApState


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = ApState(Path(self.tmp.name) / "ap_state.db")

    def tearDown(self) -> None:
        self.state.close()
        self.tmp.cleanup()

    def test_replay_from_index_zero_does_not_requeue_applied(self) -> None:
        items = [
            NetworkItem(item=59, location=1, player=1, index=0),
            NetworkItem(item=87, location=2, player=1, index=1),
        ]
        pending = self.state.ingest_received("seed", 0, 1, 0, items)
        self.assertEqual([row.idx for row in pending], [0, 1])
        self.state.mark_applied("seed", 0, 1, 0)
        self.state.mark_applied("seed", 0, 1, 1)

        replay = self.state.ingest_received("seed", 0, 1, 0, items)
        self.assertEqual(replay, [])
        self.assertEqual(self.state.last_ingested_index("seed", 0, 1), 2)

    def test_unapplied_rows_return_on_replay(self) -> None:
        items = [NetworkItem(item=81, location=0, player=0, index=0)]
        self.state.ingest_received("seed", 0, 1, 0, items)
        again = self.state.ingest_received("seed", 0, 1, 0, items)
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0].item_id, 81)

    def test_checked_locations_dedup(self) -> None:
        first = self.state.add_checked_locations("seed", 0, 1, [10, 11])
        second = self.state.add_checked_locations("seed", 0, 1, [11, 12])
        self.assertEqual(first, [10, 11])
        self.assertEqual(second, [12])
        self.assertEqual(self.state.checked_locations("seed", 0, 1), [10, 11, 12])

    def test_item_count(self) -> None:
        shards = [NetworkItem(item=133, location=i, player=1) for i in range(7)]
        self.state.ingest_received("seed", 0, 1, 0, shards)
        self.assertEqual(self.state.item_count("seed", 0, 1, 133), 7)


if __name__ == "__main__":
    unittest.main()
