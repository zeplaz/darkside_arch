import tempfile
import unittest
from pathlib import Path

from ds_client.ap_apply import (
    SYNTHETIC_BLADE_INDEX,
    desired_write_value,
    maybe_synthetic_blade,
)
from ds_client.ap_catalog import ApCatalog, CatalogEntry
from ds_client.ap_protocol import NetworkItem
from ds_client.ap_state import ApState
from ds_client.models import WatchTarget
import struct


def _target(dtype: str, bitmask: int | None = None) -> WatchTarget:
    size = {"bool": 1, "uint8": 1, "uint32": 4, "float": 4}[dtype]
    fmt = {"bool": "?", "uint8": "B", "uint32": "I", "float": "f"}[dtype]
    return WatchTarget(
        id="t",
        event_type="MEMORY_STATE",
        module="darksiders1.exe",
        offsets=(0x10,),
        size=size,
        unpacker=struct.Struct("<" + fmt),
        dtype=dtype,
        notes="",
        label="x",
        bitmask=bitmask,
    )


class ApplyRuleTests(unittest.TestCase):
    def test_flag_extras_are_noop(self) -> None:
        target = _target("uint8", bitmask=1)
        self.assertEqual(
            desired_write_value(
                item_name="Crossblade", received_count=1, current=0, target=target
            ),
            1,
        )
        self.assertIsNone(
            desired_write_value(
                item_name="Crossblade", received_count=4, current=1, target=target
            )
        )

    def test_count_sets_total(self) -> None:
        target = _target("uint32")
        self.assertEqual(
            desired_write_value(
                item_name="Beholder Key", received_count=3, current=1, target=target
            ),
            3,
        )

    def test_progressive_level_cap(self) -> None:
        target = _target("uint32")
        self.assertEqual(
            desired_write_value(
                item_name="Progressive Chaoseater",
                received_count=1,
                current=0,
                target=target,
            ),
            1,
        )
        self.assertEqual(
            desired_write_value(
                item_name="Progressive Chaoseater",
                received_count=9,
                current=1,
                target=target,
            ),
            4,
        )
        self.assertEqual(
            desired_write_value(
                item_name="Progressive Gauntlet",
                received_count=5,
                current=0,
                target=target,
            ),
            5,
        )

    def test_seventh_shard_queues_blade_once(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = ApState(Path(tmp.name) / "ap.db")
        self.addCleanup(state.close)
        catalog = ApCatalog(
            locations={},
            items={
                "Armageddon Blade Shards": CatalogEntry(
                    "Armageddon Blade Shards", 133, "primary_weapons"
                ),
                "Armageddon Blade": CatalogEntry(
                    "Armageddon Blade", 132, "primary_weapons"
                ),
            },
        )
        self.assertIsNone(maybe_synthetic_blade(state, catalog, "seed", 0, 1))
        shards = [NetworkItem(item=133, location=i, player=1) for i in range(7)]
        state.ingest_received("seed", 0, 1, 0, shards)
        blade = maybe_synthetic_blade(state, catalog, "seed", 0, 1)
        assert blade is not None
        self.assertEqual(blade.item_id, 132)
        self.assertEqual(blade.idx, SYNTHETIC_BLADE_INDEX)
        state.set_blade_granted("seed", 0, 1, True)
        self.assertIsNone(maybe_synthetic_blade(state, catalog, "seed", 0, 1))


if __name__ == "__main__":
    unittest.main()
