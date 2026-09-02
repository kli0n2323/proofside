from __future__ import annotations

import json
from pathlib import Path

from .artifacts import accepted_contract_path, candidate_contract_path
from .cli import CheckResult, _function_arguments, load_target, parse_selector
from .contracts import ContractError, parse_contract, render_human, validate_contract


class AcceptanceError(ValueError):
    pass


def accept_contract(
    selector: str,
    candidate_path: Path | None = None,
    replace: bool = False,
) -> tuple[str, Path, Path]:
    try:
        file_path, function_name = parse_selector(selector)
    except ValueError as error:
        raise AcceptanceError(str(error)) from error
    target = load_target(file_path, function_name, require_inline_contract=False)
    if isinstance(target, CheckResult):
        raise AcceptanceError(f"{target.status.value}: {target.detail}")
    _source, function = target

    candidate_path = candidate_path or candidate_contract_path(file_path, function_name)
    output_path = accepted_contract_path(file_path, function_name)
    if output_path.exists() and not replace:
        raise AcceptanceError(f"accepted contract already exists: {output_path}; use --replace")

    try:
        candidate_text = candidate_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise AcceptanceError(f"could not read candidate contract {candidate_path}: {error}") from error
    try:
        data = json.loads(candidate_text)
    except json.JSONDecodeError as error:
        raise AcceptanceError(
            f"malformed candidate JSON at line {error.lineno}: {error.msg}"
        ) from error
    try:
        contract = parse_contract(data)
        parameters = {argument.arg for argument in _function_arguments(function)}
        validate_contract(contract, parameters)
    except ContractError as error:
        raise AcceptanceError(f"invalid candidate contract: {error}") from error

    accepted_text = json.dumps(data, indent=2) + "\n"
    try:
        output_path.parent.mkdir(exist_ok=True)
        mode = "w" if replace else "x"
        with output_path.open(mode, encoding="utf-8") as output_file:
            output_file.write(accepted_text)
    except FileExistsError as error:
        raise AcceptanceError(f"accepted contract already exists: {output_path}; use --replace") from error
    except OSError as error:
        raise AcceptanceError(f"could not save accepted contract: {error}") from error

    return render_human(contract), candidate_path, output_path


def render_acceptance_output(
    contract_text: str,
    candidate_path: Path,
    accepted_path: Path,
) -> str:
    return (
        "ACCEPTED FOR VERIFICATION — NOT VERIFIED\n\n"
        f"Contract\n\n{contract_text}\n\n"
        f"Candidate:\n{candidate_path}\n\n"
        f"Accepted contract:\n{accepted_path}\n\n"
        "This records explicit user acceptance of the contract for verification.\n"
        "No verification was run."
    )
