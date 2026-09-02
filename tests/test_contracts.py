import ast
import json
import tempfile
import unittest
from pathlib import Path

from proofside.contracts import (
    ContractError,
    build_annotated_source,
    load_contract,
    parse_contract,
    render_human,
    render_nagini,
    validate_contract,
)


CONTRACT_PATH = Path("examples/shot_budget_contract.json")


class ContractParsingTests(unittest.TestCase):
    def contract_data(self):
        return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_loads_valid_contract(self) -> None:
        contract = load_contract(CONTRACT_PATH)
        self.assertEqual(len(contract.requires), 3)
        self.assertEqual(len(contract.ensures), 2)

    def test_rejects_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "contract.json")
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "malformed contract JSON"):
                load_contract(path)

    def test_rejects_unknown_operator(self) -> None:
        data = self.contract_data()
        data["ensures"][0]["operator"] = ">"
        with self.assertRaisesRegex(ContractError, "unknown comparison operator"):
            parse_contract(data)

    def test_rejects_nonexistent_parameter(self) -> None:
        data = self.contract_data()
        data["requires"][0]["left"]["name"] = "missing_budget"
        contract = parse_contract(data)
        with self.assertRaisesRegex(ContractError, "nonexistent parameter"):
            validate_contract(contract, {"total_shots", "first_bucket"})

    def test_rejects_result_in_precondition(self) -> None:
        data = self.contract_data()
        data["requires"][0]["left"] = {"kind": "result"}
        contract = parse_contract(data)
        with self.assertRaisesRegex(ContractError, "only in postconditions"):
            validate_contract(contract, {"total_shots", "first_bucket"})


class ContractRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(CONTRACT_PATH)

    def test_renders_human_contract_deterministically(self) -> None:
        self.assertEqual(
            render_human(self.contract),
            "Assumptions\n"
            "- total_shots >= 0\n"
            "- first_bucket >= 0\n"
            "- first_bucket <= total_shots\n"
            "\n"
            "Guarantees\n"
            "- result >= 0\n"
            "- first_bucket + result == total_shots",
        )

    def test_renders_nagini_contract_deterministically(self) -> None:
        self.assertEqual(
            render_nagini(self.contract),
            "Requires(total_shots >= 0)\n"
            "Requires(first_bucket >= 0)\n"
            "Requires(first_bucket <= total_shots)\n"
            "Ensures(Result() >= 0)\n"
            "Ensures(first_bucket + Result() == total_shots)",
        )

    def test_builds_annotated_source_without_modifying_original(self) -> None:
        path = Path("examples/shot_budget_plain.py")
        original_bytes = path.read_bytes()
        source = path.read_text(encoding="utf-8")
        function = ast.parse(source).body[0]

        generated = build_annotated_source(source, function, self.contract)

        self.assertIn("from nagini_contracts.contracts import", generated)
        self.assertIn("    Requires(total_shots >= 0)", generated)
        self.assertIn("    Ensures(first_bucket + Result() == total_shots)", generated)
        self.assertEqual(path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()

