from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .contracts import (
    ContractError,
    build_annotated_source,
    load_contract,
    render_human,
    validate_contract,
)
from .targets import CheckResult, Status, function_arguments, load_target, parse_selector


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
        parameters = {argument.arg for argument in function_arguments(function)}
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
