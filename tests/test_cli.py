import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofside.cli import (
    CheckResult,
    Status,
    check,
    classify_nagini,
    load_target,
    parse_selector,
    render_output,
)


class SelectorTests(unittest.TestCase):
    def test_parses_file_and_function(self) -> None:
        self.assertEqual(
            parse_selector("example.py::allocate"),
            (Path("example.py"), "allocate"),
        )

    def test_rejects_malformed_selector(self) -> None:
        with self.assertRaisesRegex(ValueError, "must have the form"):
            parse_selector("example.py")


class InspectionTests(unittest.TestCase):
    def inspect_source(self, source: str, name: str = "allocate"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "target.py")
            path.write_text(source, encoding="utf-8")
            return load_target(path, name)

    def test_accepts_typed_contracted_top_level_function(self) -> None:
        result = self.inspect_source(
            "def allocate(total: int) -> int:\n"
            "    Ensures(Result() == total)\n"
            "    return total\n"
        )
        self.assertIsInstance(result, tuple)

    def test_rejects_nested_function(self) -> None:
        result = self.inspect_source(
            "def outer(value: int) -> int:\n"
            "    def allocate(value: int) -> int:\n"
            "        return value\n"
            "    return allocate(value)\n"
        )
        self.assertEqual(result.status, Status.UNSUPPORTED)

    def test_rejects_missing_annotations(self) -> None:
        result = self.inspect_source(
            "def allocate(total):\n"
            "    Ensures(Result() == total)\n"
            "    return total\n"
        )
        self.assertEqual(result.status, Status.UNSUPPORTED)

    def test_reports_missing_function(self) -> None:
        result = self.inspect_source(
            "def another_function(total: int) -> int:\n"
            "    Ensures(Result() == total)\n"
            "    return total\n"
        )
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("not found", result.detail)

    def test_reports_syntax_error(self) -> None:
        result = self.inspect_source("def allocate(:\n")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("cannot parse", result.detail)


class ClassificationTests(unittest.TestCase):
    def test_classifies_success(self) -> None:
        result = classify_nagini(0, "Verification successful\n", "")
        self.assertEqual(result.status, Status.VERIFIED)

    def test_classifies_failed_obligation_and_keeps_diagnostic(self) -> None:
        result = classify_nagini(
            1,
            "Verification failed\nErrors:\nPostcondition might not hold.\nVerification took 1.00 seconds.\n",
            "",
        )
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.detail, "Postcondition might not hold.")

    def test_classifies_translation_failure_as_error(self) -> None:
        result = classify_nagini(1, "Translation failed\nNot supported: yield\n", "")
        self.assertEqual(result.status, Status.ERROR)

    def test_reports_missing_nagini_as_error(self) -> None:
        with patch("proofside.cli.shutil.which", return_value=None):
            result = check("examples/nagini/shot_budget_good.py::allocate_remaining")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("executable not found", result.detail)


class OutputTests(unittest.TestCase):
    contract_text = "Assumptions\n- value >= 0\n\nGuarantees\n- result >= 0"

    def test_verified_sidecar_explains_proof_boundary(self) -> None:
        output = render_output(CheckResult(Status.VERIFIED, "proved", self.contract_text))
        self.assertIn("Proof boundary", output)
        self.assertIn("satisfies the displayed guarantees", output)
        self.assertIn("does not establish scientific validity", output)

    def test_failed_sidecar_does_not_claim_counterexample(self) -> None:
        output = render_output(CheckResult(Status.FAILED, "Postcondition might not hold.", self.contract_text))
        self.assertIn("Proof boundary", output)
        self.assertIn("obligations were not established", output)
        self.assertIn("does not by itself mean that a concrete counterexample was produced", output)
        self.assertNotIn("satisfies the displayed guarantees", output)

    def test_unsupported_and_error_have_no_proof_boundary(self) -> None:
        for status in (Status.UNSUPPORTED, Status.ERROR):
            with self.subTest(status=status):
                output = render_output(CheckResult(status, "stopped", self.contract_text))
                self.assertNotIn("Proof boundary", output)


if __name__ == "__main__":
    unittest.main()
