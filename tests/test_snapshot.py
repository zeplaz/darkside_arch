import unittest

from tools.snapshot import Delta, drop_pool_families, intersect_deltas


class SnapshotNarrowTests(unittest.TestCase):
    def test_intersect_keeps_shared_rvas_only(self) -> None:
        left = [Delta(".data", 0x10, 0, 1), Delta(".data", 0x20, 0, 1)]
        right = [Delta(".data", 0x20, 0, 1), Delta(".data", 0x30, 0, 1)]
        out = intersect_deltas(left, right)
        self.assertEqual([d.rva for d in out], [0x20])

    def test_drop_pool_families_keeps_unique_layout(self) -> None:
        pool = [Delta(".data", 0x1000 + i * 0x100 + 8, 0, 1) for i in range(6)]
        unique = Delta(".data", 0xABCDEF, 0, 1)
        out = drop_pool_families(pool + [unique])
        self.assertEqual([d.rva for d in out], [0xABCDEF])

    def test_drop_pool_families_does_not_empty_the_list(self) -> None:
        pool = [Delta(".data", 0x1000 + i * 0x100 + 8, 0, 1) for i in range(6)]
        out = drop_pool_families(pool)
        self.assertEqual(len(out), 6)


if __name__ == "__main__":
    unittest.main()
