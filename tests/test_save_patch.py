import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.save_patch import (
    decoded_json_path,
    default_edited_path,
    find_war,
    is_steam_save_path,
    patch_sav_userid,
)


class SavePatchTests(unittest.TestCase):
    def test_decoded_json_sits_next_to_sav(self) -> None:
        self.assertEqual(decoded_json_path(Path("slot.sav")), Path("slot.json"))

    def test_edited_dest_is_local(self) -> None:
        self.assertEqual(default_edited_path(Path("foo.sav")), Path("saves") / "edited" / "foo.sav")

    def test_steam_path_gate(self) -> None:
        steam = Path("C:/Program Files (x86)/Steam/userdata/1/462780/remote/svd_fmt_0_0.sav")
        self.assertTrue(is_steam_save_path(steam))
        self.assertFalse(is_steam_save_path(Path("saves/edited/svd_fmt_0_0.sav")))

    def test_find_war_uses_explicit_binary(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        binary = Path(tmp.name) / "war-cli.exe"
        binary.write_bytes(b"x")
        self.assertEqual(find_war(binary), [str(binary.resolve())])

    def test_patch_calls_war_decode_then_encode(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        sav = root / "slot.sav"
        sav.write_bytes(b"SAV")
        dest = root / "out.sav"
        payload = {
            "properties": {
                "GameInfo": {
                    "properties": {"UserId": {"type": "int", "value": 111}}
                }
            }
        }

        def fake_run(cmd, check):
            if cmd[-2] == "decode":
                Path(cmd[-1]).with_suffix(".json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
            return None

        with patch("tools.save_patch.subprocess.run", side_effect=fake_run) as run:
            old = patch_sav_userid(sav, 222, dest, ["war-cli"])

        self.assertEqual(old, 111)
        self.assertTrue(dest.is_file())
        calls = [c.args[0] for c in run.call_args_list]
        self.assertEqual(calls[0][:3], ["war-cli", "sav", "decode"])
        self.assertEqual(calls[1][:3], ["war-cli", "sav", "encode"])
        self.assertEqual(calls[1][3], str(dest))


if __name__ == "__main__":
    unittest.main()
