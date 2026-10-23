import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import dashboard
from tools.snapshot import Delta

REPO = Path(__file__).resolve().parent.parent
LABEL = "Crossroads Currency Chest South Crater"


class FakeRam:
    """Stands in for snapshot.RamCapture: after() returns whatever the test queued."""

    def __init__(self, save_object=None) -> None:
        self.pid = 1234
        self.save_object = save_object
        self.stats = {"scope": "module", "scanned_mb": 32}
        self.next: list[Delta] = []
        self.error: str = ""

    def after(self) -> list[Delta]:
        if self.error:
            raise ValueError(self.error)
        return self.next


def _mod(rva: int) -> Delta:
    return Delta(".data", 0x7FF0_0000_0000 + rva, 0, 1, rva=rva)


class DashboardCaptureTests(unittest.TestCase):
    """Capture session rules, run in a temp cwd with fake dumps (no game needed)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        Path("docs").mkdir()
        shutil.copy(REPO / "docs" / "world_locations.json", "docs/world_locations.json")
        template = {
            "id": "chest_crossroads_currency_south_crater",
            "enabled": False,
            "event_type": "LOCATION_CHECK",
            "category": "location_flag",
            "label": LABEL,
            "region": "Crossroads",
            "offsets": ["0x0"],
            "type": "uint8",
            "bitmask": "0x01",
        }
        Path("targets.json").write_text(
            json.dumps({"observe_interval_ms": 250, "targets": [template]}), encoding="utf-8"
        )
        dashboard.capture_reset()
        self.slug = dashboard._find_catalog_loc(LABEL).slug
        self.rams: list[FakeRam] = []

        def start(save_object=None):
            self.rams.append(FakeRam(save_object))
            return self.rams[-1]

        patches = [mock.patch.object(dashboard, "start_capture", side_effect=start)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        dashboard.capture_reset()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _diff(self, deltas: list[Delta]) -> dict:
        self.rams[-1].next = deltas
        return dashboard.capture_after(self.slug)["capture"]

    def test_diff_needs_baseline_for_same_location(self) -> None:
        with self.assertRaisesRegex(ValueError, "no baseline"):
            dashboard.capture_after(self.slug)
        dashboard.capture_before(self.slug)
        other = dashboard._find_catalog_loc("Crossroads Currency Chest in Subway Station").slug
        with self.assertRaisesRegex(ValueError, "baseline belongs to"):
            dashboard.capture_after(other)

    def test_game_restart_invalidates_baseline(self) -> None:
        dashboard.capture_before(self.slug)
        self.rams[-1].error = "game restarted since the baseline; start over"
        with self.assertRaisesRegex(ValueError, "restarted"):
            self._diff([])

    def test_multiple_candidates_need_a_pick(self) -> None:
        dashboard.capture_before(self.slug)
        cap = self._diff([_mod(0x10), _mod(0x20)])
        self.assertEqual((cap["stage"], cap["zero_to_one"]), ("diffed", 2))
        with self.assertRaisesRegex(ValueError, "2 candidates"):
            dashboard.capture_save(self.slug)
        with self.assertRaisesRegex(ValueError, "not one of"):
            dashboard.capture_save(self.slug, address=_mod(0x30).address)
        out = dashboard.capture_save(self.slug, address=_mod(0x20).address)
        self.assertEqual(out["entry"]["offsets"], ["0x20"])
        self.assertEqual(out["capture"]["stage"], "idle")

    def test_save_updates_template_row_instead_of_appending(self) -> None:
        dashboard.capture_before(self.slug)
        self._diff([_mod(0x1A40B20)])
        out = dashboard.capture_save(self.slug)
        self.assertEqual(out["action"], "updated")
        rows = json.loads(Path("targets.json").read_text(encoding="utf-8"))["targets"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "chest_crossroads_currency_south_crater")
        self.assertEqual(rows[0]["offsets"], ["0x1A40B20"])
        self.assertTrue(rows[0]["enabled"])
        self.assertEqual(rows[0]["bitmask"], "0x01")

    def test_arm_waits_instead_of_dumping(self) -> None:
        out = dashboard.capture_arm(self.slug, "baseline")["capture"]
        self.assertEqual(out["wait"], "baseline")
        self.assertEqual(out["stage"], "idle")
        self.assertGreaterEqual(out["hold_s"], 7)
        with self.assertRaisesRegex(ValueError, "no baseline"):
            dashboard.capture_arm(self.slug, "diff")

    def test_select_sets_slug_while_idle(self) -> None:
        out = dashboard.capture_select(self.slug)["capture"]
        self.assertEqual(out["id"], self.slug)
        self.assertEqual(out["stage"], "idle")

    def test_dump_refuses_when_game_not_in_front(self) -> None:
        with mock.patch.object(dashboard, "game_is_foreground", return_value=False):
            with self.assertRaisesRegex(ValueError, "not in front"):
                dashboard.capture_before(self.slug, require_foreground=True)

    def test_second_diff_intersects_previous_candidates(self) -> None:
        dashboard.capture_before(self.slug)
        self._diff([_mod(0x10), _mod(0x20), _mod(0x30)])
        cap = self._diff([_mod(0x20), _mod(0x40)])
        self.assertEqual(cap["zero_to_one"], 1)
        self.assertEqual(cap["deltas"][0]["rva"], 0x20)

    def test_identified_row_captures_on_the_heap_and_saves_a_pointer_chain(self) -> None:
        so = {"world": "overworld", "region_id": 2, "layer_id": 6, "object_id": 342, "value_key": "Triggered"}
        rows = json.loads(Path("targets.json").read_text(encoding="utf-8"))
        rows["targets"][0]["save_object"] = so
        Path("targets.json").write_text(json.dumps(rows), encoding="utf-8")
        dashboard.capture_before(self.slug)
        self.assertEqual(self.rams[-1].save_object, so)
        cap = self._diff([Delta("heap", 0x2000_0041, 0, 1)])
        self.assertIsNone(cap["deltas"][0]["rva"])
        with mock.patch("tools.scanner.pointer_chain", return_value=[0x3B40000, 0x18, 0x41]):
            out = dashboard.capture_save(self.slug)
        self.assertEqual(out["entry"]["offsets"], ["0x3B40000", "0x18", "0x41"])


class GameMonitorTests(unittest.TestCase):
    def test_detached_monitor_reports_targets_without_live_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            path.write_text(
                json.dumps(
                    {
                        "targets": [
                            {"id": "a", "label": "A", "offsets": ["0x10"], "type": "uint8"},
                            {"id": "t", "label": "T", "offsets": ["0x0"], "type": "uint8"},
                            {"id": "off", "enabled": False, "offsets": ["0x20"], "type": "uint8"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            mon = dashboard.GameMonitor(path)
            mon._reload_targets()
            self.assertEqual([w["id"] for w in mon.watches()], ["a"])
            self.assertIsNone(mon.watches()[0]["value"])
            self.assertFalse(mon.status()["attached"])


if __name__ == "__main__":
    unittest.main()
