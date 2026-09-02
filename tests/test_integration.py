import os
import unittest
from pathlib import Path

from proofside.cli import Status, check


@unittest.skipUnless(
    os.environ.get("PROOFSIDE_RUN_NAGINI") == "1",
    "set PROOFSIDE_RUN_NAGINI=1 to run Nagini integration tests",
)
class SidecarIntegrationTests(unittest.TestCase):
    contract_path = Path("examples/shot_budget_contract.json")

    def test_sidecar_good_verifies_without_modifying_source(self) -> None:
        path = Path("examples/shot_budget_plain.py")
        original_bytes = path.read_bytes()
        result = check(f"{path}::allocate_remaining", self.contract_path)
        self.assertEqual(result.status, Status.VERIFIED)
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_sidecar_bad_fails(self) -> None:
        result = check(
            "examples/shot_budget_plain_bad.py::allocate_remaining",
            self.contract_path,
        )
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("Postcondition", result.detail)

    def test_ops_shot_budget_verifies(self) -> None:
        result = check(
            "examples/ops_shot_budget.py::remaining_feature_shots",
            Path("examples/ops_shot_budget_contract.json"),
        )
        self.assertEqual(result.status, Status.VERIFIED)

    def test_broken_ops_shot_budget_fails_conservation(self) -> None:
        result = check(
            "examples/ops_shot_budget_bad.py::remaining_feature_shots",
            Path("examples/ops_shot_budget_contract.json"),
        )
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("Postcondition", result.detail)
        self.assertIn("total_shots", result.detail)


if __name__ == "__main__":
    unittest.main()
