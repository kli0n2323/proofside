from __future__ import annotations

import ast
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


class LeanTranslationError(ContractError):
    """The selected Python/contract fragment has no sound Lean lowering yet."""


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


def _render_python_expression(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return str(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"-({_render_python_expression(node.operand)})"
    if isinstance(node, ast.BinOp):
        operators = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}
        operator = operators.get(type(node.op))
        if operator is not None:
            return f"({_render_python_expression(node.left)} {operator} {_render_python_expression(node.right)})"
    raise LeanTranslationError(
        "Lean backend supports only straight-line integer return expressions using names, integers, +, -, and *"
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
    if len(function.body) != 1 or not isinstance(function.body[0], ast.Return) or function.body[0].value is None:
        raise LeanTranslationError("Lean backend supports only a function body containing one return expression")

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
    body = _render_python_expression(function.body[0].value)

    return (
        "import Lean.Elab.Tactic.Omega\n\n"
        f"def {function.name}{definition_arguments} : Int :=\n"
        f"  {body}\n\n"
        f"theorem {function.name}_proofside_contract\n"
        f"{theorem_arguments}"
        f"{''.join(requires)}"
        f"    : {guarantee} := by\n"
        f"  simp only [{function.name}]\n"
        "  omega\n"
    )
