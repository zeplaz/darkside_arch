import unittest

from tools.dashboard import catalog_payload


class DashboardOpsTests(unittest.TestCase):
    def test_catalog_exposes_gate_ap_and_apply_facts(self) -> None:
        data = catalog_payload()
        self.assertIn("regions", data)
        self.assertEqual(data["gate"], "NO_OFFSETS")
        self.assertEqual(data["mapped"], 0)
        self.assertGreater(data["total"], 0)
        self.assertIn("uri", data["ap"])
        by_label = {row["label"]: row for row in data["inventory"]}
        self.assertIn("Armageddon Blade Shards", by_label)
        self.assertIn("Abaddon Destroyer defeated", by_label)
        chaos = by_label["Progressive Chaoseater"]
        self.assertEqual(chaos["write"], "level")
        self.assertEqual(chaos["cap"], 4)
        self.assertEqual(chaos["dtype"], "uint32")
        self.assertEqual(chaos["ap_id"], 100)
        self.assertIn("scan --item \"Progressive Chaoseater\"", chaos["scan"])
        self.assertEqual(by_label["Abaddon Destroyer defeated"]["write"], "goal")
        self.assertTrue(all(not row["mapped"] for row in data["inventory"]))


if __name__ == "__main__":
    unittest.main()
