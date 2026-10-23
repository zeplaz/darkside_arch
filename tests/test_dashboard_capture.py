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


def _fake_snapshot(pid: int):
    def take(*, name: str, **_kw) -> Path:
        dest = Path("snapshots") / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "meta.json").write_text(json.dumps({"pid": pid}), encoding="utf-8")
        return dest

    return take


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
        patches = [
            mock.patch.object(dashboard, "take_snapshot", _fake_snapshot(1234)),
            mock.patch.object(dashboard.time, "sleep", lambda _s: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        dashboard.capture_reset()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _diff(self, deltas: list[Delta]) -> dict:
        with mock.patch.object(dashboard, "diff_snapshots", return_value=deltas):
            return dashboard.capture_after(self.slug, zero_to_one=True)["capture"]

    def test_diff_needs_baseline_for_same_location(self) -> None:
        with self.assertRaisesRegex(ValueError, "no baseline"):
            self._diff([])
        dashboard.capture_before(self.slug)
        other = dashboard._find_catalog_loc("Crossroads Currency Chest in Subway Station").slug
        with self.assertRaisesRegex(ValueError, "baseline belongs to"):
            dashboard.capture_after(other, zero_to_one=True)

    def test_game_restart_invalidates_baseline(self) -> None:
        dashboard.capture_before(self.slug)
        with mock.patch.object(dashboard, "take_snapshot", _fake_snapshot(999)):
            with self.assertRaisesRegex(ValueError, "restarted"):
                self._diff([])

    def test_multiple_candidates_need_a_pick(self) -> None:
        dashboard.capture_before(self.slug)
        cap = self._diff([Delta(".data", 0x10, 0, 1), Delta(".data", 0x20, 0, 1)])
        self.assertEqual((cap["stage"], cap["zero_to_one"]), ("diffed", 2))
        with self.assertRaisesRegex(ValueError, "2 candidates"):
            dashboard.capture_save(self.slug)
        with self.assertRaisesRegex(ValueError, "not one of"):
            dashboard.capture_save(self.slug, rva=0x30)
        out = dashboard.capture_save(self.slug, rva=0x20)
        self.assertEqual(out["entry"]["offsets"], ["0x20"])
        self.assertEqual(out["capture"]["stage"], "idle")

    def test_save_updates_template_row_instead_of_appending(self) -> None:
        dashboard.capture_before(self.slug)
        self._diff([Delta(".data", 0x1A40B20, 0, 1)])
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
        self._diff(
            [
                Delta(".data", 0x10, 0, 1),
                Delta(".data", 0x20, 0, 1),
                Delta(".data", 0x30, 0, 1),
            ]
        )
        cap = self._diff([Delta(".data", 0x20, 0, 1), Delta(".data", 0x40, 0, 1)])
        self.assertEqual(cap["zero_to_one"], 1)
        self.assertEqual(cap["deltas"][0]["rva"], 0x20)

    def test_object_pool_bytes_are_dropped(self) -> None:
        dashboard.capture_before(self.slug)
        pool = [Delta(".data", 0x1000 + i * 0x100 + 8, 0, 1) for i in range(6)]
        cap = self._diff(pool + [Delta(".data", 0xABCDEF, 0, 1)])
        self.assertEqual(cap["zero_to_one"], 1)
        self.assertEqual(cap["deltas"][0]["rva"], 0xABCDEF)
        self.assertEqual(cap["raw_zero_to_one"], 7)


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
