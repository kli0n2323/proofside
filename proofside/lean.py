from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen

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


class LeanTranslationError(ContractError):
    """The selected Python/contract fragment has no sound Lean lowering yet."""


LEAN_TOOLCHAIN = "leanprover/lean4:v4.33.1"


def lean_command() -> list[str] | None:
    """Return a command for the pinned Lean toolchain when one is available."""
    elan = shutil.which("elan") or str(Path.home() / ".elan" / "bin" / "elan")
    if Path(elan).is_file() or shutil.which("elan"):
        return [elan, "run", LEAN_TOOLCHAIN, "lean"]
    lean = shutil.which("lean")
    return [lean] if lean else None


def install_lean() -> None:
    """Install the pinned native Lean toolchain after explicit user approval."""
    elan = shutil.which("elan") or str(Path.home() / ".elan" / "bin" / "elan")
    if not (Path(elan).is_file() or shutil.which("elan")):
        with urlopen("https://elan.lean-lang.org/elan-init.sh") as response:
            script = response.read()
        with tempfile.NamedTemporaryFile(prefix="proofside-elan-", suffix=".sh", delete=False) as file:
            script_path = Path(file.name)
            file.write(script)
        try:
            completed = subprocess.run(
                ["sh", str(script_path), "-y", "--no-modify-path", "--default-toolchain", "none"],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            script_path.unlink(missing_ok=True)
        if completed.returncode:
            detail = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
            raise OSError(detail.strip() or "elan installer failed")
        elan = str(Path.home() / ".elan" / "bin" / "elan")
    completed = subprocess.run(
        [elan, "toolchain", "install", LEAN_TOOLCHAIN], capture_output=True, text=True, check=False
    )
    if completed.returncode:
        detail = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        raise OSError(detail.strip() or "Lean toolchain installation failed")


def _render_value(value: Value, result: str, parent_precedence: int = 0) -> str:
    if isinstance(value, Variable):
        return value.name
    if isinstance(value, Integer):
        return str(value.value)
    if isinstance(value, ResultValue):
        return result
    if isinstance(value, Add):
        text, precedence = (
            f"{_render_value(value.left, result, 10)} + {_render_value(value.right, result, 10)}",
            10,
        )
    elif isinstance(value, Subtract):
        text, precedence = (
            f"{_render_value(value.left, result, 10)} - {_render_value(value.right, result, 11)}",
            10,
        )
    elif isinstance(value, Scale):
        text, precedence = f"{value.factor} * {_render_value(value.value, result, 21)}", 20
    elif isinstance(value, Negate):
        text, precedence = f"-{_render_value(value.value, result, 31)}", 30
    else:  # pragma: no cover - Contract validation owns this boundary.
        raise LeanTranslationError(f"unsupported contract value: {type(value).__name__}")
    return f"({text})" if precedence < parent_precedence else text


def _render_formula(formula: Formula, result: str) -> str:
    if isinstance(formula, Comparison):
        operator = {
            ComparisonOperator.EQUAL: "=",
            ComparisonOperator.NOT_EQUAL: "≠",
            ComparisonOperator.LESS: "<",
            ComparisonOperator.LESS_EQUAL: "≤",
            ComparisonOperator.GREATER: ">",
            ComparisonOperator.GREATER_EQUAL: "≥",
        }[formula.operator]
        return f"{_render_value(formula.left, result)} {operator} {_render_value(formula.right, result)}"
    if isinstance(formula, And):
        return " ∧ ".join(f"({_render_formula(item, result)})" for item in formula.items)
    if isinstance(formula, Or):
        return " ∨ ".join(f"({_render_formula(item, result)})" for item in formula.items)
    if isinstance(formula, Not):
        return f"¬ ({_render_formula(formula.item, result)})"
    if isinstance(formula, Implies):
        return f"({_render_formula(formula.antecedent, result)}) → ({_render_formula(formula.consequent, result)})"
    raise LeanTranslationError(f"unsupported contract formula: {type(formula).__name__}")


def _render_python_expression(node: ast.expr, environment: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        try:
            return environment[node.id]
        except KeyError as error:
            raise LeanTranslationError(f"Lean backend found an unbound name: {node.id}") from error
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return str(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"-({_render_python_expression(node.operand, environment)})"
    if isinstance(node, ast.BinOp):
        operators = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}
        operator = operators.get(type(node.op))
        if operator is not None:
            return (
                f"({_render_python_expression(node.left, environment)} {operator} "
                f"{_render_python_expression(node.right, environment)})"
            )
    raise LeanTranslationError(
        "Lean backend supports only straight-line integer return expressions using names, integers, +, -, and *"
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


def _compile_block(statements: list[ast.stmt], environment: dict[str, str]) -> str:
    """Symbolically execute a side-effect-free Python block into one Lean expression."""
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
        next_environment = dict(environment)
        next_environment[statement.targets[0].id] = _render_python_expression(statement.value, environment)
        return _compile_block(remaining, next_environment)
    if isinstance(statement, ast.If):
        if not statement.orelse:
            raise LeanTranslationError("Lean backend requires an explicit else branch")
        condition = _render_python_condition(statement.test, environment)
        then_result = _compile_block([*statement.body, *remaining], dict(environment))
        else_result = _compile_block([*statement.orelse, *remaining], dict(environment))
        return f"(if {condition} then {then_result} else {else_result})"
    raise LeanTranslationError(
        "Lean backend supports assignments, if/else, and return; calls, loops, mutation, and exceptions are unsupported"
    )


def _arguments(function: ast.FunctionDef) -> list[str]:
    if function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
        raise LeanTranslationError("Lean backend does not support variadic or keyword-only parameters")
    arguments = [*function.args.posonlyargs, *function.args.args]
    if not arguments:
        return []
    for argument in arguments:
        if not isinstance(argument.annotation, ast.Name) or argument.annotation.id != "int":
            raise LeanTranslationError("Lean backend currently supports only parameters annotated int")
    if not isinstance(function.returns, ast.Name) or function.returns.id != "int":
        raise LeanTranslationError("Lean backend currently supports only functions returning int")
    return [argument.arg for argument in arguments]


def build_lean_source(function: ast.FunctionDef, contract: Contract) -> str:
    """Lower a deliberately small, semantics-preserving Python fragment to Lean."""
    arguments = _arguments(function)
    function_application = " ".join([function.name, *arguments])
    result = f"({function_application})" if arguments else function.name
    parameter_text = " ".join(arguments)
    definition_arguments = f" ({parameter_text} : Int)" if arguments else ""
    theorem_arguments = f"    ({parameter_text} : Int)\n" if arguments else ""
    requires = [f"    (h{index} : {_render_formula(formula, result)})\n" for index, formula in enumerate(contract.requires)]
    ensures = [_render_formula(formula, result) for formula in contract.ensures]
    if not ensures:
        raise LeanTranslationError("Lean backend requires at least one postcondition")
    guarantee = " ∧ ".join(f"({formula})" for formula in ensures)
    body = _compile_block(function.body, {argument: argument for argument in arguments})

    return (
        "import Lean.Elab.Tactic.Omega\n\n"
        f"def {function.name}{definition_arguments} : Int :=\n"
        f"  {body}\n\n"
        f"theorem {function.name}_proofside_contract\n"
        f"{theorem_arguments}"
        f"{''.join(requires)}"
        f"    : {guarantee} := by\n"
        f"  simp [{function.name}] <;> omega\n"
    )
