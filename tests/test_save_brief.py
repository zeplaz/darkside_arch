import unittest

from tools.save_brief import brief_from_data


def _node(value, typ="int"):
    return {"type": typ, "value": value}


class SaveBriefTests(unittest.TestCase):
    def test_counts_triggered_and_spawn(self) -> None:
        data = {
            "classname": "PlayerSaveData",
            "properties": {
                "SpawnWorld": _node("overworld", "hstring"),
                "SpawnRegion": _node("CI_02", "hstring"),
                "SpawnPoint": _node("Start_04", "hstring"),
                "Health": _node(81),
                "GameInfo": {
                    "type": "object",
                    "properties": {
                        "UserId": _node(8457083),
                        "GameTime": _node(977),
                        "HealthLevel": _node(0),
                    },
                },
                "Stats": {
                    "type": "object",
                    "properties": {"NumberOfChestsOpened": _node(0)},
                },
                "WorldData": {
                    "type": "array",
                    "items": [
                        {
                            "classname": "SaveValue",
                            "properties": {
                                "Key": _node("Triggered", "string"),
                                "Value": _node("true", "string"),
                            },
                        },
                        {
                            "classname": "SaveValue",
                            "properties": {
                                "Key": _node("Destroyed", "string"),
                                "Value": _node("true", "string"),
                            },
                        },
                    ],
                },
            },
        }
        info = brief_from_data(data, file="x.sav", slot=1)
        self.assertEqual(info["slot"], 1)
        self.assertEqual(info["userid"], 8457083)
        self.assertEqual(info["chests_opened"], 0)
        self.assertEqual(info["triggered"], 1)
        self.assertEqual(info["destroyed"], 1)
        self.assertEqual(info["open"], 0)
        self.assertEqual(info["spawn_region"], "CI_02")


if __name__ == "__main__":
    unittest.main()
