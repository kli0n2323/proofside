from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
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


def parse_selector(selector: str) -> tuple[Path, str]:
    if selector.count("::") != 1:
        raise ValueError("selector must have the form path/to/file.py::function_name")

    file_text, function_name = selector.split("::")
    if not file_text or Path(file_text).suffix != ".py":
        raise ValueError("selector must name a Python file ending in .py")
    if not function_name.isidentifier():
        raise ValueError("selector must end with one unqualified function name")
    return Path(file_text), function_name


def inspect_target(file_path: Path, function_name: str) -> CheckResult | None:
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

    arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
    if function.args.vararg:
        arguments.append(function.args.vararg)
    if function.args.kwarg:
        arguments.append(function.args.kwarg)
    if function.returns is None or any(argument.annotation is None for argument in arguments):
        return CheckResult(Status.UNSUPPORTED, "the function must have complete parameter and return annotations")

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

    return None


def classify_nagini(return_code: int, stdout: str, stderr: str) -> CheckResult:
    if return_code == 0 and "Verification successful" in stdout:
        return CheckResult(Status.VERIFIED, "Nagini/Viper discharged the declared proof obligations.")

    if return_code != 0 and stdout.startswith("Verification failed"):
        diagnostic_lines = stdout.splitlines()[2:]
        if diagnostic_lines and diagnostic_lines[-1].startswith("Verification took "):
            diagnostic_lines.pop()
        return CheckResult(Status.FAILED, "\n".join(diagnostic_lines).strip())

    diagnostic = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
    return CheckResult(Status.ERROR, diagnostic or f"Nagini exited unexpectedly with status {return_code}")


def check(selector: str) -> CheckResult:
    try:
        file_path, function_name = parse_selector(selector)
    except ValueError as error:
        return CheckResult(Status.ERROR, str(error))

    eligibility_result = inspect_target(file_path, function_name)
    if eligibility_result:
        return eligibility_result

    nagini = shutil.which("nagini")
    if not nagini:
        return CheckResult(Status.ERROR, "Nagini executable not found; activate the verification environment")

    try:
        completed = subprocess.run(
            [
                nagini,
                "--verifier",
                "silicon",
                "--select",
                function_name,
                str(file_path.resolve()),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return CheckResult(Status.ERROR, f"could not start Nagini: {error}")

    return classify_nagini(completed.returncode, completed.stdout, completed.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proofside")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check", help="verify one contracted top-level function")
    check_parser.add_argument("selector", help="path/to/file.py::function_name")
    arguments = parser.parse_args(argv)

    result = check(arguments.selector)
    print(result.status.value)
    if result.detail:
        print(result.detail)
    return 0 if result.status is Status.VERIFIED else 1

