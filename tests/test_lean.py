import ast
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofside.artifacts import accepted_contract_path
from proofside.cli import main
from proofside.contracts import parse_contract
from proofside.lean import run_lean
from proofside.targets import Status
from proofside.verification import check
from tests.test_integration import SidecarCases


def integer(value):
    return {"kind": "integer", "value": value}


def variable(name):
    return {"kind": "variable", "name": name}


def comparison(left, right, operator="=="):
    return {"kind": "compare", "operator": operator, "left": left, "right": right}


def returns(value, requires=()):
    return {
        "requires": list(requires),
        "ensures": [comparison({"kind": "result"}, value)],
    }


def check_source(source, contract, name="f", backend="lean"):
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory, "example.py")
        contract_path = Path(directory, "example.json")
        source_path.write_text(source, encoding="utf-8")
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return check(f"{source_path}::{name}", contract_path, backend)


class LeanBoundaryTests(unittest.TestCase):
    def test_unsupported_source_stops_before_verifier_process(self):
        for source in (
            "def f() -> str:\n    return 0\n",
            "def f(x: int = 1) -> int:\n    return x\n",
            "def f[T](x: int) -> int:\n    return x\n",
            "def f(x: int, x: int) -> int:\n    return x\n",
            "def f(x: int) -> int:\n    return x * x\n",
            "def f() -> int:\n    return False\n",
            "def f() -> int:\n    return int()\n",
            "def f() -> int:\n    while 1 == 1:\n        return 0\n",
            "def f(x: int) -> int:\n    if x > 0:\n        x = 1\n    return x\n",
            "def f(x: int) -> int:\n    if x > 0:\n        y = 1\n    else:\n        x = 1\n    return y\n",
            "def f(x: int) -> int:\n    if x > 0:\n        return 0\n    else:\n        x = 1\n",
        ):
            with self.subTest(source=source), patch("proofside.lean.subprocess.run") as execute:
                result = check_source(source, returns(integer(0)))
                self.assertEqual(result.status, Status.UNSUPPORTED, result.detail)
                execute.assert_not_called()

    def test_missing_tool_or_elan_proxy_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            bin_path = Path(directory, "bin")
            bin_path.mkdir()
            proxy = bin_path / "lean"
            proxy.touch()
            for executable in (None, str(proxy)):
                with (
                    self.subTest(executable=executable),
                    patch.dict(os.environ, {"PROOFSIDE_LEAN": ""}),
                    patch("proofside.lean.shutil.which", return_value=executable),
                    patch("proofside.lean.subprocess.run") as execute,
                ):
                    result = check_source("def f() -> int:\n    return 0\n", returns(integer(0)))
                    self.assertEqual(result.status, Status.ERROR)
                    self.assertIn("PROOFSIDE_LEAN", result.detail)
                    execute.assert_not_called()

    def test_branch_expansion_is_bounded_before_verifier_process(self):
        branch = "    if x == 0:\n        x = 1\n    else:\n        x = 2\n"
        source = "def f(x: int) -> int:\n" + branch * 15 + "    return x\n"
        with patch("proofside.lean.subprocess.run") as execute:
            result = check_source(source, returns(integer(0)))
        self.assertEqual(result.status, Status.UNSUPPORTED)
        self.assertIn("expansion limit", result.detail)
        execute.assert_not_called()

    def test_success_exit_requires_standard_axiom_report(self):
        function = ast.parse("def f() -> int:\n    return 0\n").body[0]
        contract = parse_contract(returns(integer(0)))
        for stdout in ("", "'proofsideContract' depends on axioms: [propext, sorryAx]\n"):
            with (
                self.subTest(stdout=stdout),
                patch("proofside.lean._lean_executable", return_value=Path("lean")),
                patch(
                    "proofside.lean.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, stdout, ""),
                ),
            ):
                self.assertEqual(run_lean(function, contract).status, Status.ERROR)

    def test_missing_nagini_never_falls_back_to_lean(self):
        with (
            patch("proofside.verification.shutil.which", return_value=None),
            patch("proofside.verification.run_lean") as lean,
        ):
            result = check_source("def f() -> int:\n    return 0\n", returns(integer(0)), backend="nagini")
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("Nagini executable not found", result.detail)
        lean.assert_not_called()

    def test_lean_rejects_handwritten_contract_mode(self):
        result = check("examples/nagini/shot_budget_good.py::allocate_remaining", backend="lean")
        self.assertEqual(result.status, Status.UNSUPPORTED)
        self.assertIn("JSON sidecar", result.detail)


@unittest.skipUnless(
    os.environ.get("PROOFSIDE_RUN_LEAN") == "1",
    "set PROOFSIDE_RUN_LEAN=1 to run Lean integration tests",
)
class LeanIntegrationTests(SidecarCases, unittest.TestCase):
    backend = "lean"
    failure_marker = "omega could not prove"
    conservation_parameter = "psArg0"

    def test_nullary_and_literal_arithmetic_use_signed_integers(self):
        difference = {"kind": "subtract", "left": integer(1), "right": integer(2)}
        contract = returns(integer(-1), [comparison(difference, integer(0), "<")])
        for expression, expected in (("1 - 2", Status.VERIFIED), ("0", Status.FAILED)):
            with self.subTest(expression=expression):
                result = check_source(f"def f() -> int:\n    return {expression}\n", contract)
                self.assertEqual(result.status, expected, result.detail)

    def test_reassignment_branch_scope_and_identifier_collisions(self):
        source = (
            "def sorry(sorry: int, h0: int, Int: int) -> int:\n"
            "    saved = sorry\n"
            "    sorry = sorry + 9\n"
            "    if h0 == Int and not (1 - 2 >= 0):\n"
            "        saved = saved - -1\n"
            "    else:\n"
            "        saved = sorry - 8\n"
            "    return saved\n"
        )
        expected = {"kind": "add", "left": variable("sorry"), "right": integer(1)}
        contract = returns(expected, [comparison(variable("h0"), integer(0), ">=")])
        for implementation, status in (
            (source, Status.VERIFIED),
            (source.replace("sorry - 8", "sorry - 7"), Status.FAILED),
        ):
            result = check_source(implementation, contract, name="sorry")
            self.assertEqual(result.status, status, result.detail)

    def test_cli_selects_lean_for_a_single_check_and_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "example.py")
            source.write_text("# proofside equation: result = 0\ndef f() -> int:\n    return 0\n", encoding="utf-8")
            contract = accepted_contract_path(source, "f")
            contract.parent.mkdir()
            contract.write_text(json.dumps(returns(integer(0))), encoding="utf-8")
            for args in (
                ["check", f"{source}::f", "--contract", str(contract)],
                ["check-all", str(source)],
            ):
                with self.subTest(command=args[0]), contextlib.redirect_stdout(io.StringIO()) as output:
                    status = main([*args, "--backend", "lean"])
                self.assertEqual(status, 0, output.getvalue())
                self.assertIn("Lean 4", output.getvalue())
                self.assertIn("VERIFIED", output.getvalue())
