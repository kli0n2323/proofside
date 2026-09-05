from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from proofside.acceptance import AcceptanceError, accept_contract
from proofside.artifacts import accepted_contract_path, candidate_contract_path
from proofside.cli import CheckResult, Status, check, main


VALID_CONTRACT = {
    "requires": [
        {
            "kind": "compare",
            "operator": ">=",
            "left": {"kind": "variable", "name": "value"},
            "right": {"kind": "integer", "value": 0},
        }
    ],
    "ensures": [
        {
            "kind": "compare",
            "operator": "==",
            "left": {"kind": "result"},
            "right": {"kind": "variable", "name": "value"},
        }
    ],
}


def write_target(directory: str) -> Path:
    source_path = Path(directory, "budget.py")
    source_path.write_text(
        "def remaining(value: int) -> int:\n"
        "    return value\n",
        encoding="utf-8",
    )
    return source_path


def write_candidate(path: Path, data: object = VALID_CONTRACT) -> bytes:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path.read_bytes()


class AcceptanceTests(unittest.TestCase):
    def test_default_candidate_is_accepted_without_model_or_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = write_target(directory)
            selector = f"{source_path}::remaining"
            candidate_path = candidate_contract_path(source_path, "remaining")
            original_candidate = write_candidate(candidate_path)
            accepted_path = accepted_contract_path(source_path, "remaining")
            with (
                patch("proofside.proposal.request_model") as request_model,
                patch("proofside.cli.run_nagini") as run_nagini,
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                exit_code = main(["accept", selector])

            self.assertEqual(exit_code, 0)
            request_model.assert_not_called()
            run_nagini.assert_not_called()
            self.assertEqual(candidate_path.read_bytes(), original_candidate)
            self.assertEqual(json.loads(accepted_path.read_text(encoding="utf-8")), VALID_CONTRACT)
            output = stdout.getvalue()
            self.assertIn("ACCEPTED FOR VERIFICATION", output)
            self.assertIn("NOT VERIFIED", output)
            self.assertIn("No verification was run", output)
            self.assertIn(str(candidate_path), output)
            self.assertIn(str(accepted_path), output)

    def test_custom_candidate_writes_deterministic_accepted_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = write_target(directory)
            custom_path = Path(directory, "reviewed.json")
            write_candidate(custom_path)
            output_path = accepted_contract_path(source_path, "remaining")

            with patch("sys.stdout", new_callable=io.StringIO):
                exit_code = main(
                    [
                        "accept",
                        f"{source_path}::remaining",
                        "--candidate",
                        str(custom_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(custom_path.exists())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), VALID_CONTRACT)

    def test_invalid_candidates_do_not_create_accepted_contract(self) -> None:
        unknown_operator = json.loads(json.dumps(VALID_CONTRACT))
        unknown_operator["ensures"][0]["operator"] = "=>"
        wrong_parameter = json.loads(json.dumps(VALID_CONTRACT))
        wrong_parameter["requires"][0]["left"]["name"] = "other"
        cases = {
            "missing": None,
            "malformed": "not json",
            "unknown_operator": json.dumps(unknown_operator),
            "wrong_parameter": json.dumps(wrong_parameter),
        }

        for name, candidate_text in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                source_path = write_target(directory)
                candidate_path = Path(directory, "candidate.json")
                if candidate_text is not None:
                    candidate_path.write_text(candidate_text, encoding="utf-8")
                output_path = accepted_contract_path(source_path, "remaining")

                with self.assertRaises(AcceptanceError):
                    accept_contract(
                        f"{source_path}::remaining",
                        candidate_path,
                    )

                self.assertFalse(output_path.exists())

    def test_existing_contract_requires_explicit_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = write_target(directory)
            candidate_path = candidate_contract_path(source_path, "remaining")
            write_candidate(candidate_path)
            output_path = accepted_contract_path(source_path, "remaining")
            original = b"existing accepted contract\n"
            output_path.write_bytes(original)

            with self.assertRaisesRegex(AcceptanceError, "use --replace"):
                accept_contract(f"{source_path}::remaining")

            self.assertEqual(output_path.read_bytes(), original)

    def test_replace_occurs_only_after_successful_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = write_target(directory)
            selector = f"{source_path}::remaining"
            candidate_path = candidate_contract_path(source_path, "remaining")
            write_candidate(candidate_path)
            output_path = accepted_contract_path(source_path, "remaining")
            output_path.write_bytes(b"old accepted contract\n")

            accept_contract(selector, replace=True)

            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), VALID_CONTRACT)

            previous = output_path.read_bytes()
            candidate_path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(AcceptanceError, "malformed candidate JSON"):
                accept_contract(selector, replace=True)
            self.assertEqual(output_path.read_bytes(), previous)

    def test_explicit_check_with_arbitrary_manual_contract_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = write_target(directory)
            contract_path = Path(directory, "manual.json")
            write_candidate(contract_path)
            verified = CheckResult(Status.VERIFIED, "proved")

            with patch("proofside.cli.run_nagini", return_value=verified):
                result = check(f"{source_path}::remaining", contract_path, backend="nagini")

            self.assertEqual(result.status, Status.VERIFIED)


if __name__ == "__main__":
    unittest.main()
