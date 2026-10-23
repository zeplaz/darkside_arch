import struct
import unittest
from contextlib import contextmanager
from unittest import mock

import numpy as np

from tools import snapshot
from tools.snapshot import Delta, Region, find_anchors, intersect_deltas


def _buf(dwords: dict[int, int], size: int = 0x200) -> np.ndarray:
    raw = bytearray(size)
    for off, value in dwords.items():
        struct.pack_into("<I", raw, off, value)
    return np.frombuffer(bytes(raw), dtype=np.uint8)


class AnchorTests(unittest.TestCase):
    def test_object_id_needs_region_and_layer_nearby(self) -> None:
        buf = _buf({0x40: 342, 0x48: 2, 0x4C: 6, 0x100: 342, 0x180: 342, 0x184: 2})
        self.assertEqual(find_anchors(buf, 342, (2, 6)), [0x40])
        self.assertEqual(find_anchors(buf, 342, ()), [0x40, 0x100, 0x180])

    def test_unaligned_object_id_is_ignored(self) -> None:
        raw = bytearray(0x100)
        struct.pack_into("<I", raw, 0x41, 342)
        self.assertEqual(find_anchors(np.frombuffer(bytes(raw), dtype=np.uint8), 342, ()), [])

    def test_windows_are_clipped_and_merged(self) -> None:
        heaps = [(0x10000, 0x1000)]
        out = snapshot._windows([0x10010, 0x10100], heaps)
        self.assertEqual([(r.address, r.size) for r in out], [(0x10000, 0x100 + snapshot.WINDOW)])


class IntersectTests(unittest.TestCase):
    def test_intersect_keeps_shared_addresses_only(self) -> None:
        left = [Delta("heap", 0x10, 0, 1), Delta("heap", 0x20, 0, 1)]
        right = [Delta("heap", 0x20, 0, 1), Delta("heap", 0x30, 0, 1)]
        self.assertEqual([d.address for d in intersect_deltas(left, right)], [0x20])


class FilterTests(unittest.TestCase):
    """0 in every baseline sample and 1 in every after sample, nothing else."""

    def test_only_steady_zero_then_steady_one_survives(self) -> None:
        region = Region(label="heap", address=0x5000, size=8)
        # byte 0: ticks during the baseline           -> dropped
        # byte 1: 0 then 1 in every after sample      -> kept
        # byte 2: 0 then 1 in only one after sample   -> dropped (popup / animation)
        # byte 3: already 1                           -> dropped
        baseline = [[0, 0, 0, 1, 0, 0, 0, 0], [5, 0, 0, 1, 0, 0, 0, 0]] + [[0, 0, 0, 1, 0, 0, 0, 0]] * 3
        after = [[0, 1, 1, 1, 0, 0, 0, 0], [0, 1, 0, 1, 0, 0, 0, 0], [0, 1, 0, 1, 0, 0, 0, 0]]
        reads = iter(np.array(s, dtype=np.uint8) for s in baseline + after)

        @contextmanager
        def fake_game(pid=None):
            yield 7, None

        with mock.patch.object(snapshot, "_open_game", fake_game), \
             mock.patch.object(snapshot, "heap_anchor_regions", return_value=([region], {"scope": "heap"})), \
             mock.patch.object(snapshot, "_read_region", side_effect=lambda h, r: next(reads)), \
             mock.patch.object(snapshot.RamCapture, "_save_debug"):
            cap = snapshot.start_capture({"object_id": 342, "region_id": 2, "layer_id": 6}, sleep=lambda s: None)
            deltas = cap.after(sleep=lambda s: None)
        self.assertEqual([(d.address, d.rva) for d in deltas], [(0x5001, None)])

    def test_module_byte_saves_its_rva_heap_byte_needs_a_chain(self) -> None:
        self.assertEqual(snapshot.offsets_for(Delta(".data", 0x7FF0_0123, 0, 1, rva=0x123), pid=1), [0x123])
        with mock.patch("tools.scanner.pointer_chain", return_value=[0x3B40000, 0x18, 0x41]):
            self.assertEqual(snapshot.offsets_for(Delta("heap", 0x2000_0041, 0, 1), pid=1), [0x3B40000, 0x18, 0x41])
        with mock.patch("tools.scanner.pointer_chain", return_value=None):
            with self.assertRaisesRegex(ValueError, "no static pointer path"):
                snapshot.offsets_for(Delta("heap", 0x2000_0041, 0, 1), pid=1)


if __name__ == "__main__":
    unittest.main()
