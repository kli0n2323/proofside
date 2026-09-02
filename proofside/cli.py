from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .contracts import (
    ContractError,
    build_annotated_source,
    load_contract,
    render_human,
    validate_contract,
)


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


def parse_selector(selector: str) -> tuple[Path, str]:
    if selector.count("::") != 1:
        raise ValueError("selector must have the form path/to/file.py::function_name")

    file_text, function_name = selector.split("::")
    if not file_text or Path(file_text).suffix != ".py":
        raise ValueError("selector must name a Python file ending in .py")
    if not function_name.isidentifier():
        raise ValueError("selector must end with one unqualified function name")
    return Path(file_text), function_name


def _function_arguments(function: ast.FunctionDef) -> list[ast.arg]:
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

    arguments = _function_arguments(function)
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


def run_nagini(file_path: Path, function_name: str) -> CheckResult:
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


def check(selector: str, contract_path: Path | None = None) -> CheckResult:
    try:
        file_path, function_name = parse_selector(selector)
    except ValueError as error:
        return CheckResult(Status.ERROR, str(error))

    target = load_target(file_path, function_name, require_inline_contract=contract_path is None)
    if isinstance(target, CheckResult):
        return target
    source, function = target

    if contract_path is None:
        return run_nagini(file_path, function_name)

    try:
        contract = load_contract(contract_path)
        parameters = {argument.arg for argument in _function_arguments(function)}
        validate_contract(contract, parameters)
        contract_text = render_human(contract)
        annotated_source = build_annotated_source(source, function, contract)
    except ContractError as error:
        return CheckResult(Status.ERROR, f"invalid contract: {error}")

    try:
        with tempfile.TemporaryDirectory(prefix="proofside-") as directory:
            verification_path = Path(directory, f"{file_path.stem}_verification.py")
            verification_path.write_text(annotated_source, encoding="utf-8")
            result = run_nagini(verification_path, function_name)
    except OSError as error:
        return CheckResult(Status.ERROR, f"could not create temporary verification source: {error}")

    return CheckResult(result.status, result.detail, contract_text)


def render_proof_boundary(result: CheckResult) -> str:
    if result.contract_text is None:
        return ""
    if result.status is Status.VERIFIED:
        lines = [
            "Proof boundary",
            "- The selected implementation satisfies the displayed guarantees under the displayed assumptions, according to Nagini/Viper.",
            "- Preconditions remain assumptions about valid callers and inputs.",
            "- The proof covers only the displayed contract and the supported verification semantics.",
            "- It does not establish scientific validity, empirical correspondence, usefulness, or optimality.",
        ]
        return "\n".join(lines)
    if result.status is Status.FAILED:
        lines = [
            "Proof boundary",
            "- One or more displayed proof obligations were not established.",
            "- FAILED does not by itself mean that a concrete counterexample was produced.",
            "- No conclusion about scientific validity follows from this failed proof attempt.",
        ]
        return "\n".join(lines)
    return ""


def render_output(result: CheckResult) -> str:
    sections = []
    if result.contract_text:
        sections.append(f"Contract\n\n{result.contract_text}")
    status = result.status.value
    if result.detail:
        status += f"\n{result.detail}"
    sections.append(status)
    boundary = render_proof_boundary(result)
    if boundary:
        sections.append(boundary)
    return "\n\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proofside")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check", help="verify one contracted top-level function")
    check_parser.add_argument("selector", help="path/to/file.py::function_name")
    check_parser.add_argument("--contract", type=Path, help="structured JSON sidecar contract")
    arguments = parser.parse_args(argv)

    result = check(arguments.selector, arguments.contract)
    print(render_output(result))
    return 0 if result.status is Status.VERIFIED else 1
