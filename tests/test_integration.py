import json
import os
import tempfile
import unittest
from pathlib import Path

from proofside.artifacts import accepted_contract_path
from proofside.batch import render_batch_output, run_batch_checks
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

    def test_batch_runs_independent_real_verifications(self) -> None:
        source = (
            "# proofside equation: result = value\n"
            "def correct(value: int) -> int:\n"
            "    return value\n\n"
            "# proofside equation: result = value\n"
            "def broken(value: int) -> int:\n"
            "    return value + 1\n"
        )
        contract = {
            "requires": [],
            "ensures": [
                {
                    "kind": "compare",
                    "operator": "==",
                    "left": {"kind": "result"},
                    "right": {"kind": "variable", "name": "value"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "batch_example.py")
            source_path.write_text(source, encoding="utf-8")
            for name in ("correct", "broken"):
                contract_path = accepted_contract_path(source_path, name)
                contract_path.parent.mkdir(exist_ok=True)
                contract_path.write_text(json.dumps(contract), encoding="utf-8")

            results, errors = run_batch_checks((source_path,))

        self.assertEqual(errors, ())
        self.assertEqual([item.result.status for item in results], [Status.VERIFIED, Status.FAILED])
        output = render_batch_output(results, errors)
        self.assertIn("1/2 VERIFIED", output)
        self.assertIn("batch_example.py::broken", output)
        self.assertIn("FAILED", output)


if __name__ == "__main__":
    unittest.main()
