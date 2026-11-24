from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class CheckResult:
    status: Status
    detail: str
    contract_text: str | None = None
    backend: str = "nagini"


def parse_selector(selector: str) -> tuple[Path, str]:
    if selector.count("::") != 1:
        raise ValueError("selector must have the form path/to/file.py::function_name")

    file_text, function_name = selector.split("::")
    if not file_text or Path(file_text).suffix != ".py":
        raise ValueError("selector must name a Python file ending in .py")
    if not function_name.isidentifier():
        raise ValueError("selector must end with one unqualified function name")
    return Path(file_text), function_name


def function_arguments(function: ast.FunctionDef) -> list[ast.arg]:
    arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
    if function.args.vararg:
        arguments.append(function.args.vararg)
    if function.args.kwarg:
        arguments.append(function.args.kwarg)
    return arguments


def load_target(
    file_path: Path,
    function_name: str,
    require_inline_contract: bool = True,
) -> tuple[str, ast.FunctionDef] | CheckResult:
    if not file_path.is_file():
        return CheckResult(Status.ERROR, f"file does not exist: {file_path}")

    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError as error:
        return CheckResult(Status.ERROR, f"could not read {file_path}: {error}")

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as error:
        location = f"line {error.lineno}" if error.lineno else "unknown line"
        return CheckResult(Status.ERROR, f"cannot parse {file_path} ({location}): {error.msg}")

    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    async_functions = [
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name
    ]

    if len(functions) + len(async_functions) > 1:
        return CheckResult(Status.UNSUPPORTED, f"multiple top-level functions are named {function_name}")
    if async_functions:
        return CheckResult(Status.UNSUPPORTED, "async functions are not supported")
    if not functions:
        nested_match = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
            for node in ast.walk(tree)
        )
        if nested_match:
            return CheckResult(
                Status.UNSUPPORTED,
                "the selected function is nested or is a method; only top-level functions are supported",
            )
        return CheckResult(Status.ERROR, f"top-level function not found: {function_name}")

    function = functions[0]
    if function.decorator_list:
        return CheckResult(Status.UNSUPPORTED, "decorated functions are not supported")

    arguments = function_arguments(function)
    if function.returns is None or any(argument.annotation is None for argument in arguments):
        return CheckResult(Status.UNSUPPORTED, "the function must have complete parameter and return annotations")

    if require_inline_contract:
        contract_names = {"Requires", "Ensures"}
        has_contract = any(
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id in contract_names
            for statement in function.body
        )
        if not has_contract:
            return CheckResult(Status.UNSUPPORTED, "no direct Requires or Ensures contract call was found")

    return source, function
