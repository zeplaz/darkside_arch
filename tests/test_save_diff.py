import unittest

from tools.save_diff import diff_saves, flatten_save


def _obj(world: str, rid: int, lid: int, oid: int, key: str, value: str) -> dict:
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
        "type": "object",
        "classname": "LayerData",
        "properties": {
            "LayerID": {"type": "int", "value": 6},
            "WorldObjects": {"type": "array", "items": list(objects)},
        },
    }
    region = {
        "type": "object",
        "classname": "RegionData",
        "properties": {
            "RegionID": {"type": "int", "value": 2},
            "Layers": {"type": "array", "items": [layer]},
        },
    }
    world = {
        "type": "object",
        "classname": "WorldData",
        "properties": {
            "World": {"type": "hstring", "value": "overworld"},
            "Regions": {"type": "array", "items": [region]},
        },
    }
    return {
        "classname": "PlayerSaveData",
        "properties": {
            "WorldData": {"type": "array", "items": [world]},
            "Stats": {
                "properties": {
                    "NumberOfChestsOpened": {"type": "int", "value": len(objects)}
                }
            },
        },
    }


class SaveDiffTests(unittest.TestCase):
    def test_chest_triggered_appears_as_object_record(self) -> None:
        before = _save()
        after = _save(_obj("overworld", 2, 6, 342, "Triggered", "true"))
        rows = diff_saves(before, after)
        fields = {(k[0], k[5], right) for k, _left, right in rows}
        self.assertIn(("object", "Triggered", "true"), fields)
        self.assertIn(("stat", "NumberOfChestsOpened", "1/int"), fields)

    def test_destroyed_breakable_is_same_table(self) -> None:
        data = _save(_obj("overworld", 2, 6, 10, "Destroyed", "true"))
        flat = flatten_save(data)
        self.assertEqual(
            flat[("object", "overworld", "2", "6", "10", "Destroyed")],
            "true",
        )


if __name__ == "__main__":
    unittest.main()
