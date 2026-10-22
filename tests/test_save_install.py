import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.save_install import (
    is_late_game_save,
    patch_json_userid,
    patch_sav_userid,
    read_json_userid,
)


class SaveInstallTests(unittest.TestCase):
    def test_rejects_late_game_bag(self) -> None:
        reasons = is_late_game_save(
            {
                "spawn_world": "overworld",
                "spawn_region": "CI_02",
                "inventory_item_types": ["items/item_armageddonsword"],
                "chests_opened": 5,
            }
        )
        self.assertTrue(any("CI_02" in r for r in reasons))
        self.assertTrue(any("item_armageddonsword" in r for r in reasons))

    def test_accepts_crossroads_start(self) -> None:
        reasons = is_late_game_save(
            {
                "spawn_world": "overworld",
                "spawn_region": "CI_01",
                "inventory_item_types": ["items/item_warsword"],
                "chests_opened": 0,
            }
        )
        self.assertEqual(reasons, [])

    def test_patch_json_and_sav_userid(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        payload = {
            "type": "object",
            "classname": "PlayerSaveData",
            "properties": {
                "GameInfo": {
                    "type": "object",
                    "classname": "SaveGameInfo",
                    "properties": {
                        "UserId": {"type": "int", "value": 111}
                    },
                }
            },
        }
        json_path = root / "slot.json"
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        patch_json_userid(json_path, 222)
        self.assertEqual(read_json_userid(json_path), 222)

        sav = root / "slot.sav"
        sav.write_bytes(b"HDR" + struct.pack("<I", 111) + b"TAIL")
        n = patch_sav_userid(sav, 111, 222)
        self.assertEqual(n, 1)
        self.assertEqual(sav.read_bytes(), b"HDR" + struct.pack("<I", 222) + b"TAIL")


if __name__ == "__main__":
    unittest.main()
