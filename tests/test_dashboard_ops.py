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
        labels = {row["label"] for row in data["inventory"]}
        self.assertIn("Armageddon Blade Shards", labels)
        self.assertIn("Abaddon The Destroyer defeated", labels)
        self.assertTrue(all(not row["mapped"] for row in data["inventory"]))


if __name__ == "__main__":
    unittest.main()
