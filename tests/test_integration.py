import json
import os
import tempfile
import unittest
from pathlib import Path

from proofside.artifacts import accepted_contract_path
from proofside.batch import render_batch_output, run_batch_checks
from proofside.cli import Status, check


@unittest.skipUnless(
    os.environ.get("PROOFSIDE_RUN_LEAN") == "1",
    "set PROOFSIDE_RUN_LEAN=1 to run Lean integration tests",
)
class LeanIntegrationTests(unittest.TestCase):
    contract_path = Path("examples/sidecar/shot_budget_contract.json")

    def test_sidecar_good_verifies_without_modifying_source(self) -> None:
        path = Path("examples/sidecar/shot_budget_plain.py")
        original_bytes = path.read_bytes()
        result = check(f"{path}::allocate_remaining", self.contract_path)
        self.assertEqual(result.status, Status.VERIFIED)
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_sidecar_bad_fails(self) -> None:
        result = check(
            "examples/sidecar/shot_budget_plain_bad.py::allocate_remaining",
            self.contract_path,
        )
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("omega could not prove", result.detail)

    def test_research_shot_budget_verifies(self) -> None:
        result = check(
            "examples/research/research_shot_budget.py::remaining_feature_shots",
            Path("examples/research/research_shot_budget_contract.json"),
        )
        self.assertEqual(result.status, Status.VERIFIED)

    def test_broken_research_shot_budget_fails_conservation(self) -> None:
        result = check(
            "examples/research/research_shot_budget_bad.py::remaining_feature_shots",
            Path("examples/research/research_shot_budget_contract.json"),
        )
        self.assertEqual(result.status, Status.FAILED)
        self.assertIn("omega could not prove", result.detail)
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

    def test_piecewise_implications_verify_and_reject_wrong_negative_branch(self) -> None:
        good_source = (
            "def nonnegative_part(value: int) -> int:\n"
            "    if value >= 0:\n"
            "        result = value\n"
            "    else:\n"
            "        result = 0\n"
            "    return result\n"
        )
        bad_source = good_source.replace("        result = 0\n", "        result = -1\n")
        variable = {"kind": "variable", "name": "value"}
        zero = {"kind": "integer", "value": 0}
        contract = {
            "requires": [],
            "ensures": [
                {
                    "kind": "implies",
                    "if": {"kind": "compare", "operator": ">=", "left": variable, "right": zero},
                    "then": {"kind": "compare", "operator": "==", "left": {"kind": "result"}, "right": variable},
                },
                {
                    "kind": "implies",
                    "if": {"kind": "compare", "operator": "<", "left": variable, "right": zero},
                    "then": {"kind": "compare", "operator": "==", "left": {"kind": "result"}, "right": zero},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            contract_path = directory_path / "piecewise.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            good_path = directory_path / "piecewise_good.py"
            bad_path = directory_path / "piecewise_bad.py"
            good_path.write_text(good_source, encoding="utf-8")
            bad_path.write_text(bad_source, encoding="utf-8")

            good = check(f"{good_path}::nonnegative_part", contract_path)
            bad = check(f"{bad_path}::nonnegative_part", contract_path)

        self.assertEqual(good.status, Status.VERIFIED)
        self.assertEqual(bad.status, Status.FAILED)
        self.assertIn("omega could not prove", bad.detail)

    def test_linear_arithmetic_and_boolean_formulas_verify(self) -> None:
        source = (
            "def linear(x: int, y: int) -> int:\n"
            "    result = 2 * x - y\n"
            "    return result\n"
        )
        x = {"kind": "variable", "name": "x"}
        y = {"kind": "variable", "name": "y"}
        zero = {"kind": "integer", "value": 0}
        expected = {
            "kind": "subtract",
            "left": {"kind": "scale", "factor": 2, "value": x},
            "right": y,
        }
        equality = {"kind": "compare", "operator": "==", "left": {"kind": "result"}, "right": expected}
        contract = {
            "requires": [
                {
                    "kind": "and",
                    "items": [
                        {"kind": "compare", "operator": ">=", "left": x, "right": zero},
                        {"kind": "compare", "operator": ">=", "left": y, "right": zero},
                    ],
                }
            ],
            "ensures": [
                {
                    "kind": "or",
                    "items": [
                        equality,
                        {"kind": "compare", "operator": ">", "left": {"kind": "result"}, "right": expected},
                    ],
                },
                {"kind": "not", "item": {"kind": "compare", "operator": "!=", "left": {"kind": "result"}, "right": expected}},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "linear.py")
            contract_path = Path(directory, "linear.json")
            source_path.write_text(source, encoding="utf-8")
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            result = check(f"{source_path}::linear", contract_path)

        self.assertEqual(result.status, Status.VERIFIED)


if __name__ == "__main__":
    unittest.main()
