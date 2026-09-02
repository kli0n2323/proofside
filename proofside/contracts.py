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


Value: TypeAlias = Variable | Integer | ResultValue | Add


class ComparisonOperator(str, Enum):
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    EQUAL = "=="


@dataclass(frozen=True)
class Comparison:
    operator: ComparisonOperator
    left: Value
    right: Value


@dataclass(frozen=True)
class Contract:
    requires: tuple[Comparison, ...]
    ensures: tuple[Comparison, ...]


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


def parse_contract(data: object) -> Contract:
    if not isinstance(data, dict):
        raise ContractError("contract must be an object")
    _require_keys(data, {"requires", "ensures"}, "contract")
    if not isinstance(data["requires"], list) or not isinstance(data["ensures"], list):
        raise ContractError("contract requires and ensures must be arrays")
    return Contract(
        tuple(_parse_comparison(item, f"requires[{index}]") for index, item in enumerate(data["requires"])),
        tuple(_parse_comparison(item, f"ensures[{index}]") for index, item in enumerate(data["ensures"])),
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
    elif isinstance(value, Add):
        _validate_value(value.left, parameters, allow_result)
        _validate_value(value.right, parameters, allow_result)
    else:
        raise ContractError(f"unsupported contract value: {type(value).__name__}")


def validate_contract(contract: Contract, parameters: set[str]) -> None:
    for comparison in contract.requires:
        _validate_value(comparison.left, parameters, False)
        _validate_value(comparison.right, parameters, False)
    for comparison in contract.ensures:
        _validate_value(comparison.left, parameters, True)
        _validate_value(comparison.right, parameters, True)


def _render_value(value: Value, result_text: str) -> str:
    if isinstance(value, Variable):
        return value.name
    if isinstance(value, Integer):
        return str(value.value)
    if isinstance(value, ResultValue):
        return result_text
    if isinstance(value, Add):
        return f"{_render_value(value.left, result_text)} + {_render_value(value.right, result_text)}"
    raise ContractError(f"unsupported contract value: {type(value).__name__}")


def _render_comparison(comparison: Comparison, result_text: str) -> str:
    left = _render_value(comparison.left, result_text)
    return f"{left} {comparison.operator.value} {_render_value(comparison.right, result_text)}"


def render_human(contract: Contract) -> str:
    lines = ["Assumptions"]
    lines.extend(f"- {_render_comparison(item, 'result')}" for item in contract.requires)
    lines.append("")
    lines.append("Guarantees")
    lines.extend(f"- {_render_comparison(item, 'result')}" for item in contract.ensures)
    return "\n".join(lines)


def render_nagini(contract: Contract) -> str:
    lines = [f"Requires({_render_comparison(item, 'Result()')})" for item in contract.requires]
    lines.extend(f"Ensures({_render_comparison(item, 'Result()')})" for item in contract.ensures)
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
    contract_import = "from nagini_contracts.contracts import Ensures, Requires, Result\n\n\n"
    return contract_import + "\n".join(function_lines) + "\n"
