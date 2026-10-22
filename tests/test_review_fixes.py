"""Regression tests for the review fixes (apply queue, goal, config, targets, CLI)."""

import io
import json
import queue
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from ds_client import ap_apply
from ds_client.ap_catalog import ApCatalog, CatalogEntry
from ds_client.ap_client import ApRuntime
from ds_client.ap_config import load_config, parse_connect_target
from ds_client.ap_protocol import NetworkItem
from ds_client.ap_state import ApState
from ds_client.models import WatchTarget, load_targets
from ds_client.sinks import init_db, list_memory_map, sync_memory_map_from_targets


def _target(tid: str, label: str) -> WatchTarget:
    return WatchTarget(
        id=tid,
        event_type="MEMORY_STATE",
        module="darksiders1.exe",
        offsets=(0x10,),
        size=4,
        unpacker=struct.Struct("<I"),
        dtype="uint32",
        notes="",
        label=label,
        category="inventory",
    )


class ApplyQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = ApState(Path(tmp.name) / "ap.db")
        self.addCleanup(self.state.close)
        self.catalog = ApCatalog(
            locations={},
            items={
                "Beholder Key": CatalogEntry("Beholder Key", 59),
                "Heart of the Chosen": CatalogEntry("Heart of the Chosen", 60),
            },
        )

    def test_unmapped_item_does_not_block_later_items(self) -> None:
        # idx 0 has no mapped watch; idx 1 does. Both queued in that order.
        items = [NetworkItem(item=60, location=1, player=1), NetworkItem(item=59, location=2, player=1)]
        rows = self.state.ingest_received("s", 0, 1, 0, items)
        q: queue.SimpleQueue = queue.SimpleQueue()
        for row in rows:
            q.put(row)
        targets = [_target("key", "Beholder Key")]
        with mock.patch.multiple(
            ap_apply.win32,
            resolve_address=mock.Mock(return_value=0x1000),
            read_memory=mock.Mock(return_value=struct.pack("<I", 0)),
            write_memory=mock.Mock(return_value=True),
        ), redirect_stdout(io.StringIO()):
            ap_apply.drain_apply_queue(None, {"darksiders1.exe": 1}, targets, self.catalog, self.state, q)
        self.assertEqual([r.idx for r in self.state.pending_applies("s", 0, 1)], [0])
        self.assertTrue(q.empty())  # unmappable row left pending in the DB, not spinning in the queue


class GoalTests(unittest.TestCase):
    def test_goal_before_connect_is_kept_for_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ApState(Path(tmp) / "ap.db")
            try:
                runtime = ApRuntime(state, ApCatalog(locations={}, items={}))
                runtime.submit_goal()
                runtime.submit_location_checks([5])
                self.assertEqual(runtime.drain_outbox(), [])  # nothing before Connected
                self.assertEqual(runtime.take_pending(), ([5], True))
            finally:
                state.close()


class ConfigTests(unittest.TestCase):
    def test_connect_target_without_port_keeps_saved_port(self) -> None:
        self.assertEqual(parse_connect_target("archipelago.gg"), ("archipelago.gg", None, False))
        self.assertEqual(parse_connect_target("wss://a.gg:38282/x"), ("a.gg", 38282, True))

    def test_host_with_port_in_config_is_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ap_config.json"
            path.write_text(json.dumps({"host": "wss://h.gg:1234", "port": 1, "slot": "War", "uuid": "u"}))
            cfg = load_config(path)
            self.assertEqual(cfg.uri(), "wss://h.gg:1234")


class TargetsTests(unittest.TestCase):
    def test_templates_and_disabled_rows_are_not_watched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            path.write_text(json.dumps({"targets": [
                {"id": "real", "offsets": ["0x10"], "type": "uint8"},
                {"id": "tmpl", "offsets": ["0x0"], "type": "uint8"},
                {"id": "off", "enabled": False, "offsets": ["0x20"], "type": "uint8"},
            ]}))
            _, targets = load_targets(path)
            self.assertEqual([t.id for t in targets], ["real"])

    def test_missing_id_is_a_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            path.write_text(json.dumps({"targets": [{"offsets": ["0x10"]}]}))
            with self.assertRaisesRegex(ValueError, "needs an 'id'"):
                load_targets(path)

    def test_sync_removes_rows_for_deleted_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = init_db(Path(tmp) / "d.db")
            try:
                sync_memory_map_from_targets(conn, [_target("a", "A"), _target("b", "B")])
                sync_memory_map_from_targets(conn, [_target("a", "A")])
                self.assertEqual([r["target_id"] for r in list_memory_map(conn)], ["a"])
            finally:
                conn.close()


class CliTests(unittest.TestCase):
    def test_every_command_has_working_help(self) -> None:
        from tools.cli import COMMANDS, main

        for name in COMMANDS:
            with self.subTest(name), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main([name, "--help"])
                self.assertEqual(ctx.exception.code, 0)

    def test_unknown_command(self) -> None:
        from tools.cli import main

        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["snapshot"]), 2)


if __name__ == "__main__":
    unittest.main()
