import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofside.cli import main
from proofside.interpretation import (
    InterpretationError,
    interpret_contract,
)
from proofside.model import LOCAL_BASE_URL, ProposalError


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


def write_contract(directory: str, data: object = VALID_CONTRACT) -> Path:
    path = Path(directory, "contract.json")
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class InterpretationTests(unittest.TestCase):
    def test_model_prompt_contains_contract_but_no_source_or_specification(self) -> None:
        source = (
            "# proofside equation: ORIGINAL_EQUATION_SENTINEL\n"
            "# proofside intent: ORIGINAL_INTENT_SENTINEL\n"
            "def hidden(value: int) -> int:\n"
            "    return IMPLEMENTATION_SENTINEL\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "source.py").write_text(source, encoding="utf-8")
            contract_path = write_contract(directory)
            with patch(
                "proofside.interpretation.request_model",
                return_value="The result equals the nonnegative input.",
            ) as request_model:
                interpretation = interpret_contract(
                    contract_path,
                    "local",
                    "interpreter-model",
                )

        self.assertEqual(interpretation, "The result equals the nonnegative input.")
        endpoint, model, prompt, api_key = request_model.call_args.args
        self.assertEqual(endpoint, LOCAL_BASE_URL)
        self.assertEqual(model, "interpreter-model")
        self.assertIsNone(api_key)
        self.assertIn('"requires"', prompt)
        self.assertIn('"name": "value"', prompt)
        self.assertNotIn("ORIGINAL_EQUATION_SENTINEL", prompt)
        self.assertNotIn("ORIGINAL_INTENT_SENTINEL", prompt)
        self.assertNotIn("IMPLEMENTATION_SENTINEL", prompt)
        self.assertNotIn("def hidden", prompt)
        self.assertNotIn("source.py", prompt)

    def test_malformed_json_is_rejected_before_model_contact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "contract.json")
            path.write_text("{not json", encoding="utf-8")
            with patch("proofside.interpretation.request_model") as request_model:
                with self.assertRaisesRegex(InterpretationError, "malformed contract JSON"):
                    interpret_contract(path, "local", "model")
        request_model.assert_not_called()

    def test_unsupported_contract_ir_is_rejected_before_model_contact(self) -> None:
        invalid = {
            "requires": [],
            "ensures": [{"kind": "unsupported-operation"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_contract(directory, invalid)
            with patch("proofside.interpretation.request_model") as request_model:
                with self.assertRaisesRegex(InterpretationError, "unknown operation"):
                    interpret_contract(path, "local", "model")
        request_model.assert_not_called()

    def test_direct_result_in_requires_is_rejected_before_model_contact(self) -> None:
        invalid = {
            "requires": [
                {
                    "kind": "compare",
                    "operator": ">=",
                    "left": {"kind": "result"},
                    "right": {"kind": "integer", "value": 0},
                }
            ],
            "ensures": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_contract(directory, invalid)
            with patch("proofside.interpretation.request_model") as request_model:
                with self.assertRaisesRegex(InterpretationError, "postconditions"):
                    interpret_contract(path, "local", "model")
        request_model.assert_not_called()

    def test_deeply_nested_result_in_requires_is_rejected_before_model_contact(self) -> None:
        comparison = {
            "kind": "compare",
            "operator": "==",
            "left": {"kind": "result"},
            "right": {"kind": "integer", "value": 0},
        }
        invalid = {
            "requires": [
                {
                    "kind": "implies",
                    "if": {
                        "kind": "compare",
                        "operator": ">=",
                        "left": {"kind": "variable", "name": "value"},
                        "right": {"kind": "integer", "value": 0},
                    },
                    "then": {"kind": "not", "item": comparison},
                }
            ],
            "ensures": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_contract(directory, invalid)
            with patch("proofside.interpretation.request_model") as request_model:
                with self.assertRaisesRegex(InterpretationError, "postconditions"):
                    interpret_contract(path, "local", "model")
        request_model.assert_not_called()

    def test_variables_are_accepted_without_parameter_context(self) -> None:
        contract = {
            "requires": [
                {
                    "kind": "compare",
                    "operator": ">=",
                    "left": {"kind": "variable", "name": "unknown_to_interpreter"},
                    "right": {"kind": "integer", "value": 0},
                }
            ],
            "ensures": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_contract(directory, contract)
            with patch(
                "proofside.interpretation.request_model",
                return_value="The named input is assumed nonnegative.",
            ) as request_model:
                interpretation = interpret_contract(path, "local", "model")

        self.assertEqual(interpretation, "The named input is assumed nonnegative.")
        request_model.assert_called_once()

    def test_model_failure_is_a_clean_nonzero_cli_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_contract(directory)
            output = io.StringIO()
            with (
                patch(
                    "proofside.interpretation.request_model",
                    side_effect=ProposalError("could not reach model endpoint: offline"),
                ),
                contextlib.redirect_stdout(output),
            ):
                exit_code = main(
                    [
                        "interpret",
                        str(path),
                        "--model-source",
                        "local",
                        "--model",
                        "model",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("INTERPRETATION FAILED", output.getvalue())
        self.assertIn("could not reach model endpoint", output.getvalue())

    def test_success_output_has_deterministic_review_boundary_and_no_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_contract(directory)
            output = io.StringIO()
            with (
                patch(
                    "proofside.interpretation.request_model",
                    return_value="Assume value is nonnegative; return value unchanged.",
                ),
                patch("proofside.verification.run_nagini") as run_nagini,
                contextlib.redirect_stdout(output),
            ):
                exit_code = main(
                    [
                        "interpret",
                        str(path),
                        "--model-source",
                        "local",
                        "--model",
                        "model",
                    ]
                )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("BLIND MODEL INTERPRETATION — NOT A CORRECTNESS CHECK", rendered)
        self.assertIn("contract and generic Proofside IR semantics", rendered)
        self.assertIn("not the original specification or implementation", rendered)
        self.assertIn("does not prove the contract is correct or complete", rendered)
        self.assertIn("does not establish that the contract matches", rendered)
        run_nagini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
