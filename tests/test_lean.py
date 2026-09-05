import ast
import unittest

from proofside.contracts import load_contract
from proofside.lean import LeanTranslationError, build_lean_source


class LeanLoweringTests(unittest.TestCase):
    def test_lowers_integer_sidecar_to_omega_theorem(self) -> None:
        function = ast.parse(
            "def allocate_remaining(total_shots: int, first_bucket: int) -> int:\n"
            "    return total_shots - first_bucket\n"
        ).body[0]
        contract = load_contract(__import__("pathlib").Path("examples/sidecar/shot_budget_contract.json"))

        source = build_lean_source(function, contract)

        self.assertIn("import Lean.Elab.Tactic.Omega", source)
        self.assertIn("def allocate_remaining (total_shots first_bucket : Int)", source)
        self.assertIn("theorem allocate_remaining_proofside_contract", source)
        self.assertIn("simp only [allocate_remaining]", source)
        self.assertIn("omega", source)

    def test_rejects_branching_body(self) -> None:
        function = ast.parse(
            "def choose(value: int) -> int:\n"
            "    if value >= 0:\n"
            "        return value\n"
            "    return -value\n"
        ).body[0]
        contract = load_contract(__import__("pathlib").Path("examples/sidecar/shot_budget_contract.json"))
        with self.assertRaisesRegex(LeanTranslationError, "one return expression"):
            build_lean_source(function, contract)


if __name__ == "__main__":
    unittest.main()
