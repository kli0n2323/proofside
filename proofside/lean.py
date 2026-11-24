from __future__ import annotations

import ast
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from .contracts import (
    Add,
    And,
    Comparison,
    ComparisonOperator,
    Contract,
    ContractError,
    Formula,
    Implies,
    Integer,
    Negate,
    Not,
    Or,
    ResultValue,
    Scale,
    Subtract,
    Value,
    Variable,
)
from .targets import CheckResult, Status


class LeanTranslationError(ContractError):
    """The selected Python/contract fragment has no sound Lean lowering yet."""


LEAN_VERSION = "4.33.1"


def _lean_executable() -> Path:
    # A PATH entry may be an Elan proxy. Require a native installation layout
    # before executing anything, even a version check.
    selected = os.environ.get("PROOFSIDE_LEAN") or shutil.which("lean")
    if selected:
        lean = Path(selected).resolve()
        if (
            lean.is_file()
            and lean.name in {"lean", "lean.exe"}
            and lean.parent.name == "bin"
            and (lean.parent.parent / "lib" / "lean" / "Init.olean").is_file()
        ):
            return lean
    raise FileNotFoundError(
        f"install Lean {LEAN_VERSION} separately and set PROOFSIDE_LEAN to its "
        "native bin/lean executable (an Elan proxy is not supported)"
    )


def _integer(value: int) -> str:
    return f"({value} : Int)"


def _render_value(value: Value, arguments: dict[str, str], result: str) -> str:
    if isinstance(value, Variable):
        return arguments[value.name]
    if isinstance(value, Integer):
        return _integer(value.value)
    if isinstance(value, ResultValue):
        return result
    if isinstance(value, (Add, Subtract)):
        operator = "+" if isinstance(value, Add) else "-"
        left = _render_value(value.left, arguments, result)
        right = _render_value(value.right, arguments, result)
        return f"({left} {operator} {right})"
    if isinstance(value, Scale):
        return f"({_integer(value.factor)} * {_render_value(value.value, arguments, result)})"
    if isinstance(value, Negate):
        return f"(-{_render_value(value.value, arguments, result)})"
    raise LeanTranslationError(f"unsupported contract value: {type(value).__name__}")


def _render_formula(formula: Formula, arguments: dict[str, str], result: str) -> str:
    if isinstance(formula, Comparison):
        operator = {
            ComparisonOperator.EQUAL: "=",
            ComparisonOperator.NOT_EQUAL: "≠",
            ComparisonOperator.LESS: "<",
            ComparisonOperator.LESS_EQUAL: "≤",
            ComparisonOperator.GREATER: ">",
            ComparisonOperator.GREATER_EQUAL: "≥",
        }[formula.operator]
        left = _render_value(formula.left, arguments, result)
        right = _render_value(formula.right, arguments, result)
        return f"({left} {operator} {right})"
    if isinstance(formula, (And, Or)):
        connector = " ∧ " if isinstance(formula, And) else " ∨ "
        return "(" + connector.join(_render_formula(item, arguments, result) for item in formula.items) + ")"
    if isinstance(formula, Not):
        return f"(¬ {_render_formula(formula.item, arguments, result)})"
    if isinstance(formula, Implies):
        antecedent = _render_formula(formula.antecedent, arguments, result)
        consequent = _render_formula(formula.consequent, arguments, result)
        return f"({antecedent} → {consequent})"
    raise LeanTranslationError(f"unsupported contract formula: {type(formula).__name__}")


def _is_integer_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        node = node.operand
    return isinstance(node, ast.Constant) and type(node.value) is int


def _render_python_expression(node: ast.expr, environment: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        try:
            return environment[node.id]
        except KeyError as error:
            raise LeanTranslationError(f"Lean backend found an unbound name: {node.id}") from error
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return _integer(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"(-{_render_python_expression(node.operand, environment)})"
    if isinstance(node, ast.BinOp):
        operators = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}
        operator = operators.get(type(node.op))
        if operator is not None:
            if operator == "*" and not (_is_integer_literal(node.left) or _is_integer_literal(node.right)):
                raise LeanTranslationError("Lean backend supports multiplication only by an integer literal")
            return (
                f"({_render_python_expression(node.left, environment)} {operator} "
                f"{_render_python_expression(node.right, environment)})"
            )
    raise LeanTranslationError(
        "Lean backend supports only integer expressions using names, literals, +, -, and literal scaling"
    )


def _render_python_condition(node: ast.expr, environment: dict[str, str]) -> str:
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
        operators = {
            ast.Eq: "=", ast.NotEq: "≠", ast.Lt: "<", ast.LtE: "≤", ast.Gt: ">", ast.GtE: "≥",
        }
        operator = operators.get(type(node.ops[0]))
        if operator is not None:
            return (
                f"{_render_python_expression(node.left, environment)} {operator} "
                f"{_render_python_expression(node.comparators[0], environment)}"
            )
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        connector = " ∧ " if isinstance(node.op, ast.And) else " ∨ "
        return connector.join(
            f"({_render_python_condition(value, environment)})" for value in node.values
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return f"¬ ({_render_python_condition(node.operand, environment)})"
    raise LeanTranslationError("Lean backend supports conditions made from integer comparisons, and, or, and not")


def _compile_block(statements: list[ast.stmt], environment: dict[str, str], budget: Iterator[int]) -> str:
    """Symbolically execute a side-effect-free Python block into one Lean expression."""
    # Branches duplicate the continuation. Bound expansion before invoking Lean.
    if next(budget, None) is None:
        raise LeanTranslationError("Lean backend reached its control-flow expansion limit")
    if not statements:
        raise LeanTranslationError("function can fall through without returning a value")
    statement, remaining = statements[0], statements[1:]
    if isinstance(statement, ast.Return):
        if statement.value is None:
            raise LeanTranslationError("Lean backend does not support bare return")
        if remaining:
            raise LeanTranslationError("statements after return are not supported")
        return _render_python_expression(statement.value, environment)
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        name = f"psLocal{statement.lineno}_{statement.col_offset}"
        value = _render_python_expression(statement.value, environment)
        next_environment = dict(environment)
        next_environment[statement.targets[0].id] = name
        continuation = _compile_block(remaining, next_environment, budget)
        return f"(let {name} : Int := {value}; {continuation})"
    if isinstance(statement, ast.If):
        if not statement.orelse:
            raise LeanTranslationError("Lean backend requires an explicit else branch")
        condition = _render_python_condition(statement.test, environment)
        then_result = _compile_block([*statement.body, *remaining], environment, budget)
        else_result = _compile_block([*statement.orelse, *remaining], environment, budget)
        return f"(if {condition} then {then_result} else {else_result})"
    raise LeanTranslationError(
        "Lean backend supports assignments, if/else, and return; calls, loops, mutation, and exceptions are unsupported"
    )


def _arguments(function: ast.FunctionDef) -> list[str]:
    if function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
        raise LeanTranslationError("Lean backend does not support variadic or keyword-only parameters")
    if function.args.defaults or function.type_params:
        raise LeanTranslationError("Lean backend does not support defaults or type parameters")
    arguments = [*function.args.posonlyargs, *function.args.args]
    for argument in arguments:
        if not isinstance(argument.annotation, ast.Name) or argument.annotation.id != "int":
            raise LeanTranslationError("Lean backend currently supports only parameters annotated int")
    if not isinstance(function.returns, ast.Name) or function.returns.id != "int":
        raise LeanTranslationError("Lean backend currently supports only functions returning int")
    return [argument.arg for argument in arguments]


def build_lean_source(function: ast.FunctionDef, contract: Contract) -> str:
    """Lower a deliberately small, semantics-preserving Python fragment to Lean."""
    # Never emit Python names into Lean, including names from the sidecar.
    arguments = {name: f"psArg{index}" for index, name in enumerate(_arguments(function))}
    result = "(" + " ".join(["proofsideImpl", *arguments.values()]) + ")"
    parameter_text = " ".join(arguments.values())
    definition_arguments = f" ({parameter_text} : Int)" if arguments else ""
    theorem_arguments = f"    ({parameter_text} : Int)\n" if arguments else ""
    requires = [
        f"    (psHyp{index} : {_render_formula(formula, arguments, result)})\n"
        for index, formula in enumerate(contract.requires)
    ]
    ensures = [_render_formula(formula, arguments, result) for formula in contract.ensures]
    if not ensures:
        raise LeanTranslationError("Lean backend requires at least one postcondition")
    guarantee = " ∧ ".join(ensures)
    body = _compile_block(function.body, arguments, iter(range(4096)))

    return (
        "import Lean.Elab.Tactic.Omega\n\n"
        "set_option autoImplicit false\n"
        "set_option linter.unusedVariables false\n\n"
        f"def proofsideImpl{definition_arguments} : Int :=\n"
        f"  {body}\n\n"
        "theorem proofsideContract\n"
        f"{theorem_arguments}"
        f"{''.join(requires)}"
        f"    : {guarantee} := by\n"
        "  (try unfold proofsideImpl) <;> (try dsimp) <;> omega\n\n"
        "#print axioms proofsideContract\n"
    )


def run_lean(function: ast.FunctionDef, contract: Contract) -> CheckResult:
    try:
        source = build_lean_source(function, contract)
    except (LeanTranslationError, RecursionError) as error:
        return CheckResult(Status.UNSUPPORTED, f"Lean 4: {error}")

    try:
        lean = _lean_executable()
        # Resolve imports from the native distribution, independent of the
        # project directory and user-supplied Lean module search paths.
        env = {name: value for name, value in os.environ.items() if not name.upper().startswith("LEAN_")}
        with tempfile.TemporaryDirectory(prefix="proofside-lean-") as directory:
            proof = Path(directory, "Proof.lean")
            proof.write_text(source, encoding="utf-8")
            completed = subprocess.run(
                [str(lean), "-DwarningAsError=true", proof.name],
                cwd=directory,
                env=env,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        return CheckResult(Status.ERROR, f"Lean 4: {error}")

    diagnostic = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if completed.returncode == 0:
        if diagnostic == "'proofsideContract' does not depend on any axioms":
            return CheckResult(Status.VERIFIED, "Lean 4 discharged the generated proof obligations.")
        prefix = "'proofsideContract' depends on axioms: ["
        if diagnostic.startswith(prefix) and diagnostic.endswith("]"):
            axioms = {name.strip() for name in diagnostic[len(prefix):-1].split(",")}
            if axioms <= {"propext", "Classical.choice", "Quot.sound"}:
                return CheckResult(Status.VERIFIED, "Lean 4 discharged the generated proof obligations.")
        return CheckResult(Status.ERROR, "Lean 4 did not report a proof using only standard axioms")
    errors = [line for line in diagnostic.splitlines() if "error:" in line]
    # Lean prints mathematical symbols even when stdout uses a legacy code page.
    diagnostic = diagnostic.translate(str.maketrans({
        "≥": ">=", "≤": "<=", "≠": "!=", "¬": "not ", "∧": " and ", "∨": " or ", "→": "->",
    })).encode("ascii", "backslashreplace").decode("ascii")
    if errors and all("omega could not prove" in line or "unsolved goals" in line for line in errors):
        return CheckResult(Status.FAILED, f"Lean 4:\n{diagnostic}")
    return CheckResult(
        Status.ERROR, f"Lean 4: {diagnostic or f'exited unexpectedly with status {completed.returncode}'}"
    )
