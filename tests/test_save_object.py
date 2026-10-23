import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.save_diff import diff_saves
from tools.save_object import (
    identify_location,
    object_flag_deltas,
    parse_save_object,
    pick_flag_delta,
)
from tools.world_catalog import WorldLocation

REPO = Path(__file__).resolve().parent.parent


def _obj(oid: int, key: str, value: str) -> dict:
    return {
        "type": "object",
        "classname": "WorldObjectData",
        "properties": {
            "ObjectID": {"type": "int", "value": oid},
            "Data": {"type": "object", "classname": "None", "properties": {}},
            "Values": {
                "type": "array",
                "items": [
                    {
                        "type": "object",
                        "classname": "SaveValue",
                        "properties": {
                            "Key": {"type": "string", "value": key},
                            "Value": {"type": "string", "value": value},
                        },
                    }
                ],
            },
        },
    }


def _save(*objects: dict) -> dict:
    layer = {
        "properties": {
            "LayerID": {"type": "int", "value": 6},
            "WorldObjects": {"type": "array", "items": list(objects)},
        }
    }
    region = {
        "properties": {
            "RegionID": {"type": "int", "value": 2},
            "Layers": {"type": "array", "items": [layer]},
        }
    }
    world = {
        "properties": {
            "World": {"type": "hstring", "value": "overworld"},
            "Regions": {"type": "array", "items": [region]},
        }
    }
    return {"properties": {"WorldData": {"type": "array", "items": [world]}}}


class SaveObjectTests(unittest.TestCase):
    def test_pick_new_triggered_over_destroyed(self) -> None:
        before = _save(_obj(10, "Destroyed", "true"))
        after = _save(_obj(10, "Destroyed", "true"), _obj(342, "Triggered", "true"))
        flags = object_flag_deltas(diff_saves(before, after))
        pick = pick_flag_delta(flags)
        self.assertEqual(pick["object_id"], 342)
        self.assertEqual(pick["value_key"], "Triggered")

    def test_identify_writes_save_object_without_enabling(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, cwd)
        Path("docs").mkdir()
        shutil.copy(REPO / "docs" / "world_locations.json", "docs/world_locations.json")
        Path("targets.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "id": "chest_seraphim_hotel_life_1",
                            "enabled": False,
                            "label": "Seraphim Hotel Life Chest 1",
                            "offsets": ["0x0"],
                            "type": "uint8",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        loc = WorldLocation("Seraphim Hotel Life Chest 1", 1029, "Seraphim Hotel", "chest")
        action, entry = identify_location(
            loc,
            {
                "world": "overworld",
                "region_id": 2,
                "layer_id": 6,
                "object_id": 342,
                "value_key": "Triggered",
            },
        )
        self.assertEqual(action, "updated")
        self.assertFalse(entry["enabled"])
        self.assertEqual(entry["offsets"], ["0x0"])
        self.assertEqual(parse_save_object(entry["save_object"])["object_id"], 342)


if __name__ == "__main__":
    unittest.main()
