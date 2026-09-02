import ast
import json
import tempfile
import unittest
from pathlib import Path

from proofside.contracts import (
    And,
    Comparison,
    ContractError,
    Implies,
    Negate,
    Not,
    Or,
    Scale,
    Subtract,
    build_annotated_source,
    load_contract,
    parse_contract,
    render_human,
    render_nagini,
    validate_contract,
)


CONTRACT_PATH = Path("examples/sidecar/shot_budget_contract.json")
RESEARCH_CONTRACT_PATH = Path("examples/research/research_shot_budget_contract.json")


def variable(name: str) -> dict[str, object]:
    return {"kind": "variable", "name": name}


def integer(value: int) -> dict[str, object]:
    return {"kind": "integer", "value": value}


def compare(operator: str, left: object, right: object) -> dict[str, object]:
    return {"kind": "compare", "operator": operator, "left": left, "right": right}


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
        data["ensures"][0]["operator"] = "=>"
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

    def test_research_contract_uses_existing_ir_and_matches_parameters(self) -> None:
        contract = load_contract(RESEARCH_CONTRACT_PATH)
        validate_contract(
            contract,
            {"total_shots", "training_feature_shots", "test_feature_shots"},
        )
        self.assertEqual(len(contract.requires), 4)
        self.assertEqual(len(contract.ensures), 2)
        self.assertIn(
            "training_feature_shots + test_feature_shots + result == total_shots",
            render_human(contract),
        )


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
        path = Path("examples/sidecar/shot_budget_plain.py")
        original_bytes = path.read_bytes()
        source = path.read_text(encoding="utf-8")
        function = ast.parse(source).body[0]

        generated = build_annotated_source(source, function, self.contract)

        self.assertIn("from nagini_contracts.contracts import", generated)
        self.assertIn("    Requires(total_shots >= 0)", generated)
        self.assertIn("    Ensures(first_bucket + Result() == total_shots)", generated)
        self.assertEqual(path.read_bytes(), original_bytes)


class ExpandedContractTests(unittest.TestCase):
    def test_parses_expanded_arithmetic_and_all_comparisons(self) -> None:
        data = {
            "requires": [
                compare("<", variable("x"), integer(10)),
                compare(">", variable("y"), integer(-10)),
                compare("!=", variable("x"), variable("y")),
            ],
            "ensures": [
                compare(
                    "==",
                    {"kind": "result"},
                    {
                        "kind": "subtract",
                        "left": {"kind": "scale", "factor": 2, "value": variable("x")},
                        "right": {"kind": "negate", "value": variable("y")},
                    },
                )
            ],
        }

        contract = parse_contract(data)
        value = contract.ensures[0].right

        self.assertIsInstance(value, Subtract)
        self.assertIsInstance(value.left, Scale)
        self.assertEqual(value.left.factor, 2)
        self.assertIsInstance(value.right, Negate)
        validate_contract(contract, {"x", "y"})

    def test_parses_nested_boolean_formulas(self) -> None:
        nonnegative = compare(">=", variable("x"), integer(0))
        equal = compare("==", {"kind": "result"}, variable("x"))
        data = {
            "requires": [],
            "ensures": [
                {
                    "kind": "implies",
                    "if": {"kind": "and", "items": [nonnegative, {"kind": "not", "item": compare("==", variable("x"), integer(-1))}]},
                    "then": {"kind": "or", "items": [equal, compare(">", {"kind": "result"}, variable("x"))]},
                }
            ],
        }

        formula = parse_contract(data).ensures[0]

        self.assertIsInstance(formula, Implies)
        self.assertIsInstance(formula.antecedent, And)
        self.assertIsInstance(formula.antecedent.items[1], Not)
        self.assertIsInstance(formula.consequent, Or)

    def test_scale_preserves_negative_zero_and_positive_factors(self) -> None:
        for factor in (-3, 0, 2):
            data = {
                "requires": [],
                "ensures": [compare("==", {"kind": "result"}, {"kind": "scale", "factor": factor, "value": variable("x")})],
            }
            value = parse_contract(data).ensures[0].right
            self.assertEqual(value.factor, factor)

    def test_rejects_invalid_scale_factors_including_boolean(self) -> None:
        for factor in (True, 2.0, "2"):
            data = {
                "requires": [],
                "ensures": [compare("==", {"kind": "result"}, {"kind": "scale", "factor": factor, "value": variable("x")})],
            }
            with self.subTest(factor=factor), self.assertRaisesRegex(ContractError, "factor must be an integer"):
                parse_contract(data)

    def test_rejects_extra_value_and_formula_fields(self) -> None:
        bad_scale = {"kind": "scale", "factor": 2, "value": variable("x"), "extra": 1}
        with self.assertRaisesRegex(ContractError, "exactly these fields"):
            parse_contract({"requires": [], "ensures": [compare("==", {"kind": "result"}, bad_scale)]})

        bad_not = {"kind": "not", "item": compare("==", variable("x"), integer(0)), "extra": 1}
        with self.assertRaisesRegex(ContractError, "exactly these fields"):
            parse_contract({"requires": [], "ensures": [bad_not]})

    def test_rejects_short_and_or_and_unknown_formula(self) -> None:
        one = compare("==", variable("x"), integer(0))
        for kind, items in (("and", []), ("or", [one])):
            with self.assertRaisesRegex(ContractError, "at least two formulas"):
                parse_contract({"requires": [], "ensures": [{"kind": kind, "items": items}]})
        with self.assertRaisesRegex(ContractError, "unknown operation"):
            parse_contract({"requires": [], "ensures": [{"kind": "xor", "items": [one, one]}]})

    def test_rejects_nested_unknown_parameter(self) -> None:
        formula = {
            "kind": "implies",
            "if": compare(">=", variable("x"), integer(0)),
            "then": {"kind": "not", "item": compare("==", variable("missing"), integer(0))},
        }
        contract = parse_contract({"requires": [], "ensures": [formula]})
        with self.assertRaisesRegex(ContractError, "nonexistent parameter: missing"):
            validate_contract(contract, {"x"})

    def test_rejects_deeply_nested_result_in_requires(self) -> None:
        formula = {
            "kind": "implies",
            "if": compare(">=", variable("x"), integer(0)),
            "then": {"kind": "not", "item": compare("!=", {"kind": "result"}, variable("x"))},
        }
        contract = parse_contract({"requires": [formula], "ensures": []})
        with self.assertRaisesRegex(ContractError, "only in postconditions"):
            validate_contract(contract, {"x"})

    def test_accepts_deeply_nested_result_in_ensures(self) -> None:
        formula = {
            "kind": "or",
            "items": [
                compare("==", {"kind": "result"}, variable("x")),
                {"kind": "not", "item": compare("!=", {"kind": "result"}, variable("x"))},
            ],
        }
        contract = parse_contract({"requires": [], "ensures": [formula]})
        validate_contract(contract, {"x"})

    def test_renders_expanded_contract_deterministically(self) -> None:
        contract = parse_contract(
            {
                "requires": [],
                "ensures": [
                    {
                        "kind": "implies",
                        "if": {"kind": "and", "items": [compare(">=", variable("x"), integer(0)), compare(">=", variable("y"), integer(0))]},
                        "then": compare(
                            "==",
                            {"kind": "result"},
                            {"kind": "subtract", "left": {"kind": "scale", "factor": 2, "value": variable("x")}, "right": variable("y")},
                        ),
                    },
                    {"kind": "or", "items": [compare("==", {"kind": "result"}, variable("x")), compare("==", {"kind": "result"}, variable("y"))]},
                    {"kind": "not", "item": compare("!=", {"kind": "result"}, {"kind": "negate", "value": {"kind": "add", "left": variable("x"), "right": variable("y")}})},
                ],
            }
        )

        self.assertEqual(
            render_human(contract),
            "Assumptions\n\nGuarantees\n"
            "- (x >= 0 and y >= 0) -> result == 2 * x - y\n"
            "- result == x or result == y\n"
            "- not (result != -(x + y))",
        )
        self.assertEqual(
            render_nagini(contract),
            "Ensures(Implies((x >= 0 and y >= 0), Result() == 2 * x - y))\n"
            "Ensures((Result() == x or Result() == y))\n"
            "Ensures(not (Result() != -(x + y)))",
        )

    def test_old_example_contracts_remain_valid(self) -> None:
        for path, parameters in (
            (CONTRACT_PATH, {"total_shots", "first_bucket"}),
            (RESEARCH_CONTRACT_PATH, {"total_shots", "training_feature_shots", "test_feature_shots"}),
        ):
            contract = load_contract(path)
            validate_contract(contract, parameters)
            self.assertTrue(all(isinstance(formula, Comparison) for formula in contract.requires + contract.ensures))


class HumanFormulaGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = compare(">=", variable("x"), integer(0))
        self.b = compare("==", {"kind": "result"}, variable("x"))
        self.c = compare("==", {"kind": "result"}, integer(0))

    def rendered(self, formula: object) -> str:
        contract = parse_contract({"requires": [], "ensures": [formula]})
        return render_human(contract).splitlines()[-1].removeprefix("- ")

    def test_simple_atomic_implication_stays_concise(self) -> None:
        formula = {"kind": "implies", "if": self.a, "then": self.b}
        self.assertEqual(self.rendered(formula), "x >= 0 -> result == x")

    def test_implication_inside_and_and_or_is_grouped(self) -> None:
        implication = {"kind": "implies", "if": self.a, "then": self.b}
        self.assertEqual(
            self.rendered({"kind": "and", "items": [implication, self.c]}),
            "(x >= 0 -> result == x) and result == 0",
        )
        self.assertEqual(
            self.rendered({"kind": "or", "items": [implication, self.c]}),
            "(x >= 0 -> result == x) or result == 0",
        )

    def test_composite_implication_operands_are_grouped(self) -> None:
        antecedent = {"kind": "and", "items": [self.a, compare(">=", variable("y"), integer(0))]}
        consequent = {"kind": "or", "items": [self.b, self.c]}
        self.assertEqual(
            self.rendered({"kind": "implies", "if": antecedent, "then": self.c}),
            "(x >= 0 and y >= 0) -> result == 0",
        )
        self.assertEqual(
            self.rendered({"kind": "implies", "if": self.a, "then": consequent}),
            "x >= 0 -> (result == x or result == 0)",
        )

    def test_nested_implication_association_is_explicit(self) -> None:
        inner = {"kind": "implies", "if": self.a, "then": self.b}
        self.assertEqual(
            self.rendered({"kind": "implies", "if": inner, "then": self.c}),
            "(x >= 0 -> result == x) -> result == 0",
        )
        self.assertEqual(
            self.rendered({"kind": "implies", "if": self.a, "then": {"kind": "implies", "if": self.b, "then": self.c}}),
            "x >= 0 -> (result == x -> result == 0)",
        )

    def test_mixed_and_or_and_not_preserve_structure(self) -> None:
        disjunction = {"kind": "or", "items": [self.b, self.c]}
        conjunction = {"kind": "and", "items": [self.b, self.c]}
        self.assertEqual(
            self.rendered({"kind": "and", "items": [self.a, disjunction]}),
            "x >= 0 and (result == x or result == 0)",
        )
        self.assertEqual(
            self.rendered({"kind": "or", "items": [self.a, conjunction]}),
            "x >= 0 or (result == x and result == 0)",
        )
        self.assertEqual(
            self.rendered({"kind": "not", "item": disjunction}),
            "not (result == x or result == 0)",
        )

    def test_nagini_nested_formula_rendering_is_unchanged(self) -> None:
        implication = {"kind": "implies", "if": self.a, "then": self.b}
        formula = {"kind": "and", "items": [implication, {"kind": "not", "item": self.c}]}
        contract = parse_contract({"requires": [], "ensures": [formula]})
        self.assertEqual(
            render_nagini(contract),
            "Ensures((Implies(x >= 0, Result() == x) and not (Result() == 0)))",
        )

    def test_arithmetic_grouping_is_unchanged(self) -> None:
        nested_subtract = {
            "kind": "subtract",
            "left": variable("x"),
            "right": {
                "kind": "subtract",
                "left": variable("y"),
                "right": variable("z"),
            },
        }
        self.assertEqual(
            self.rendered(compare("==", {"kind": "result"}, nested_subtract)),
            "result == x - (y - z)",
        )


if __name__ == "__main__":
    unittest.main()
