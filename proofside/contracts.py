from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class Variable:
    name: str


@dataclass(frozen=True)
class Integer:
    value: int


@dataclass(frozen=True)
class ResultValue:
    pass


@dataclass(frozen=True)
class Add:
    left: Value
    right: Value


@dataclass(frozen=True)
class Subtract:
    left: Value
    right: Value


@dataclass(frozen=True)
class Negate:
    value: Value


@dataclass(frozen=True)
class Scale:
    factor: int
    value: Value


Value: TypeAlias = Variable | Integer | ResultValue | Add | Subtract | Negate | Scale


class ComparisonOperator(str, Enum):
    EQUAL = "=="
    NOT_EQUAL = "!="
    LESS = "<"
    LESS_EQUAL = "<="
    GREATER = ">"
    GREATER_EQUAL = ">="


@dataclass(frozen=True)
class Comparison:
    operator: ComparisonOperator
    left: Value
    right: Value


@dataclass(frozen=True)
class And:
    items: tuple[Formula, ...]


@dataclass(frozen=True)
class Or:
    items: tuple[Formula, ...]


@dataclass(frozen=True)
class Not:
    item: Formula


@dataclass(frozen=True)
class Implies:
    antecedent: Formula
    consequent: Formula


Formula: TypeAlias = Comparison | And | Or | Not | Implies


@dataclass(frozen=True)
class Contract:
    requires: tuple[Formula, ...]
    ensures: tuple[Formula, ...]


def _require_keys(data: dict[str, object], expected: set[str], location: str) -> None:
    if set(data) != expected:
        raise ContractError(f"{location} must contain exactly these fields: {', '.join(sorted(expected))}")


def _parse_value(data: object, location: str) -> Value:
    if not isinstance(data, dict):
        raise ContractError(f"{location} must be an object")

    kind = data.get("kind")
    if kind == "variable":
        _require_keys(data, {"kind", "name"}, location)
        name = data["name"]
        if not isinstance(name, str) or not name.isidentifier():
            raise ContractError(f"{location}.name must be a Python identifier")
        return Variable(name)
    if kind == "integer":
        _require_keys(data, {"kind", "value"}, location)
        value = data["value"]
        if type(value) is not int:
            raise ContractError(f"{location}.value must be an integer")
        return Integer(value)
    if kind == "result":
        _require_keys(data, {"kind"}, location)
        return ResultValue()
    if kind == "add":
        _require_keys(data, {"kind", "left", "right"}, location)
        left = _parse_value(data["left"], f"{location}.left")
        return Add(left, _parse_value(data["right"], f"{location}.right"))
    if kind == "subtract":
        _require_keys(data, {"kind", "left", "right"}, location)
        left = _parse_value(data["left"], f"{location}.left")
        return Subtract(left, _parse_value(data["right"], f"{location}.right"))
    if kind == "negate":
        _require_keys(data, {"kind", "value"}, location)
        return Negate(_parse_value(data["value"], f"{location}.value"))
    if kind == "scale":
        _require_keys(data, {"kind", "factor", "value"}, location)
        factor = data["factor"]
        if type(factor) is not int:
            raise ContractError(f"{location}.factor must be an integer")
        return Scale(factor, _parse_value(data["value"], f"{location}.value"))
    raise ContractError(f"{location} has unknown operation: {kind!r}")


def _parse_comparison(data: object, location: str) -> Comparison:
    if not isinstance(data, dict):
        raise ContractError(f"{location} must be an object")
    _require_keys(data, {"kind", "operator", "left", "right"}, location)
    if data["kind"] != "compare":
        raise ContractError(f"{location} has unknown operation: {data['kind']!r}")
    try:
        operator = ComparisonOperator(data["operator"])
    except (TypeError, ValueError):
        raise ContractError(f"{location} has unknown comparison operator: {data['operator']!r}") from None
    left = _parse_value(data["left"], f"{location}.left")
    return Comparison(operator, left, _parse_value(data["right"], f"{location}.right"))


def _parse_formula(data: object, location: str) -> Formula:
    if not isinstance(data, dict):
        raise ContractError(f"{location} must be an object")
    kind = data.get("kind")
    if kind == "compare":
        return _parse_comparison(data, location)
    if kind in {"and", "or"}:
        _require_keys(data, {"kind", "items"}, location)
        items = data["items"]
        if not isinstance(items, list) or len(items) < 2:
            raise ContractError(f"{location}.items must be an array with at least two formulas")
        parsed = tuple(
            _parse_formula(item, f"{location}.items[{index}]")
            for index, item in enumerate(items)
        )
        return And(parsed) if kind == "and" else Or(parsed)
    if kind == "not":
        _require_keys(data, {"kind", "item"}, location)
        return Not(_parse_formula(data["item"], f"{location}.item"))
    if kind == "implies":
        _require_keys(data, {"kind", "if", "then"}, location)
        antecedent = _parse_formula(data["if"], f"{location}.if")
        return Implies(antecedent, _parse_formula(data["then"], f"{location}.then"))
    raise ContractError(f"{location} has unknown operation: {kind!r}")


def parse_contract(data: object) -> Contract:
    if not isinstance(data, dict):
        raise ContractError("contract must be an object")
    _require_keys(data, {"requires", "ensures"}, "contract")
    if not isinstance(data["requires"], list) or not isinstance(data["ensures"], list):
        raise ContractError("contract requires and ensures must be arrays")
    return Contract(
        tuple(
            _parse_formula(item, f"requires[{index}]")
            for index, item in enumerate(data["requires"])
        ),
        tuple(
            _parse_formula(item, f"ensures[{index}]")
            for index, item in enumerate(data["ensures"])
        ),
    )


def load_contract(path: Path) -> Contract:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractError(f"could not read contract {path}: {error}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError(f"malformed contract JSON at line {error.lineno}: {error.msg}") from error
    return parse_contract(data)


def _validate_value(value: Value, parameters: set[str], allow_result: bool) -> None:
    if isinstance(value, Variable):
        if value.name not in parameters:
            raise ContractError(f"contract references nonexistent parameter: {value.name}")
    elif isinstance(value, Integer):
        return
    elif isinstance(value, ResultValue):
        if not allow_result:
            raise ContractError("result may appear only in postconditions")
    elif isinstance(value, (Add, Subtract)):
        _validate_value(value.left, parameters, allow_result)
        _validate_value(value.right, parameters, allow_result)
    elif isinstance(value, (Negate, Scale)):
        _validate_value(value.value, parameters, allow_result)
    else:
        raise ContractError(f"unsupported contract value: {type(value).__name__}")


def _validate_formula(formula: Formula, parameters: set[str], allow_result: bool) -> None:
    if isinstance(formula, Comparison):
        _validate_value(formula.left, parameters, allow_result)
        _validate_value(formula.right, parameters, allow_result)
    elif isinstance(formula, (And, Or)):
        for item in formula.items:
            _validate_formula(item, parameters, allow_result)
    elif isinstance(formula, Not):
        _validate_formula(formula.item, parameters, allow_result)
    elif isinstance(formula, Implies):
        _validate_formula(formula.antecedent, parameters, allow_result)
        _validate_formula(formula.consequent, parameters, allow_result)
    else:
        raise ContractError(f"unsupported contract formula: {type(formula).__name__}")


def validate_contract(contract: Contract, parameters: set[str]) -> None:
    for formula in contract.requires:
        _validate_formula(formula, parameters, False)
    for formula in contract.ensures:
        _validate_formula(formula, parameters, True)


def _render_value(value: Value, result_text: str, parent_precedence: int = 0) -> str:
    if isinstance(value, Variable):
        return value.name
    if isinstance(value, Integer):
        return str(value.value)
    if isinstance(value, ResultValue):
        return result_text
    if isinstance(value, Add):
        text = (
            f"{_render_value(value.left, result_text, 10)} + "
            f"{_render_value(value.right, result_text, 10)}"
        )
        precedence = 10
    elif isinstance(value, Subtract):
        text = (
            f"{_render_value(value.left, result_text, 10)} - "
            f"{_render_value(value.right, result_text, 11)}"
        )
        precedence = 10
    elif isinstance(value, Scale):
        text = f"{value.factor} * {_render_value(value.value, result_text, 21)}"
        precedence = 20
    elif isinstance(value, Negate):
        text = f"-{_render_value(value.value, result_text, 31)}"
        precedence = 30
    else:
        raise ContractError(f"unsupported contract value: {type(value).__name__}")
    return f"({text})" if precedence < parent_precedence else text


def _render_human_formula(formula: Formula, result_text: str) -> str:
    if isinstance(formula, Comparison):
        left = _render_value(formula.left, result_text)
        return f"{left} {formula.operator.value} {_render_value(formula.right, result_text)}"
    if isinstance(formula, (And, Or)):
        operator = " and " if isinstance(formula, And) else " or "
        return operator.join(
            _render_human_child(item, result_text) for item in formula.items
        )
    if isinstance(formula, Not):
        return f"not ({_render_human_formula(formula.item, result_text)})"
    if isinstance(formula, Implies):
        antecedent = _render_human_child(formula.antecedent, result_text)
        consequent = _render_human_child(formula.consequent, result_text)
        return f"{antecedent} -> {consequent}"
    raise ContractError(f"unsupported contract formula: {type(formula).__name__}")


def _render_human_child(formula: Formula, result_text: str) -> str:
    text = _render_human_formula(formula, result_text)
    return text if isinstance(formula, Comparison) else f"({text})"


def _render_nagini_formula(formula: Formula, result_text: str) -> str:
    if isinstance(formula, Comparison):
        left = _render_value(formula.left, result_text)
        return f"{left} {formula.operator.value} {_render_value(formula.right, result_text)}"
    if isinstance(formula, (And, Or)):
        operator = " and " if isinstance(formula, And) else " or "
        items = operator.join(
            _render_nagini_formula(item, result_text) for item in formula.items
        )
        return f"({items})"
    if isinstance(formula, Not):
        return f"not ({_render_nagini_formula(formula.item, result_text)})"
    if isinstance(formula, Implies):
        antecedent = _render_nagini_formula(formula.antecedent, result_text)
        consequent = _render_nagini_formula(formula.consequent, result_text)
        return f"Implies({antecedent}, {consequent})"
    raise ContractError(f"unsupported contract formula: {type(formula).__name__}")


def render_human(contract: Contract) -> str:
    lines = ["Assumptions"]
    lines.extend(f"- {_render_human_formula(item, 'result')}" for item in contract.requires)
    lines.append("")
    lines.append("Guarantees")
    lines.extend(f"- {_render_human_formula(item, 'result')}" for item in contract.ensures)
    return "\n".join(lines)


def render_nagini(contract: Contract) -> str:
    lines = [
        f"Requires({_render_nagini_formula(item, 'Result()')})"
        for item in contract.requires
    ]
    lines.extend(
        f"Ensures({_render_nagini_formula(item, 'Result()')})"
        for item in contract.ensures
    )
    return "\n".join(lines)


def validate_sidecar_source(function: ast.FunctionDef) -> None:
    if ast.get_docstring(function, clean=False) is not None:
        raise ContractError("sidecar mode does not support function docstrings")
    first_statement = function.body[0]
    if first_statement.lineno == function.lineno:
        raise ContractError("sidecar mode does not support one-line function bodies")


def build_annotated_source(source: str, function: ast.FunctionDef, contract: Contract) -> str:
    validate_sidecar_source(function)
    first_statement = function.body[0]
    source_lines = source.splitlines()
    function_lines = source_lines[function.lineno - 1:function.end_lineno]
    insertion_index = first_statement.lineno - function.lineno
    indent = source_lines[first_statement.lineno - 1][:first_statement.col_offset]
    contract_lines = [indent + line for line in render_nagini(contract).splitlines()]
    function_lines[insertion_index:insertion_index] = contract_lines + [""]
    contract_import = (
        "from nagini_contracts.contracts import "
        "Ensures, Implies, Requires, Result\n\n\n"
    )
    return contract_import + "\n".join(function_lines) + "\n"
