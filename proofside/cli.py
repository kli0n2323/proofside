from __future__ import annotations

import argparse
from pathlib import Path

from .acceptance import AcceptanceError, accept_contract, render_acceptance_output
from .artifacts import candidate_contract_path
from .batch import (
    batch_proposal_succeeded,
    batch_succeeded,
    render_batch_output,
    render_batch_proposal_output,
    run_batch_checks,
    run_batch_proposals,
)
from .interpretation import (
    InterpretationError,
    interpret_contract,
    render_interpretation_output,
)
from .proposal import ProposalError, propose_contract, render_proposal_output
from .targets import CheckResult, Status, load_target, parse_selector
from .verification import check, classify_nagini, run_nagini


def render_proof_boundary(result: CheckResult) -> str:
    if result.contract_text is None:
        return ""
    if result.status is Status.VERIFIED:
        verifier = "Lean 4" if result.backend == "lean" else "Nagini/Viper"
        lines = [
            "Proof boundary",
            f"- The selected implementation satisfies the displayed guarantees under the displayed assumptions, according to {verifier}.",
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
    parser = argparse.ArgumentParser(
        prog="proofside",
        description="State the math, review the contract, and verify typed Python.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser(
        "check",
        help="verify one contracted top-level function",
        description=(
            "Verify one typed top-level function with a JSON sidecar contract, "
            "or with handwritten Nagini contracts when --contract is omitted."
        ),
    )
    check_parser.add_argument("selector", help="path/to/file.py::function_name")
    check_parser.add_argument(
        "--contract",
        type=Path,
        help="structured JSON sidecar; omit for handwritten Nagini contracts",
    )
    check_parser.add_argument(
        "--backend", choices=("nagini", "lean"), default="nagini",
        help="formal verifier (default: nagini); lean requires a JSON sidecar",
    )
    check_all_parser = subparsers.add_parser(
        "check-all",
        help="verify Proofside-marked functions using source-adjacent contracts",
        description=(
            "Independently verify marked functions with accepted source-adjacent "
            "contracts. This command does not propose or accept contracts."
        ),
    )
    check_all_parser.add_argument("targets", nargs="+", type=Path, help="Python files or directories")
    check_all_parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="fall back to candidate contracts; still returns a nonzero exit status",
    )
    check_all_parser.add_argument(
        "--backend", choices=("nagini", "lean"), default="nagini",
        help="formal verifier for every selected function (default: nagini)",
    )
    propose_parser = subparsers.add_parser(
        "propose",
        help="ask an explicitly selected model for an unverified candidate contract",
        description=(
            "Ask an explicitly selected model for one unverified candidate. "
            "This command never accepts the candidate or runs verification."
        ),
    )
    propose_parser.add_argument("selector", help="path/to/file.py::function_name")
    propose_parser.add_argument(
        "--model-source",
        choices=("api", "local"),
        required=True,
        help="api sends selected context remotely; local sends it to the chosen local endpoint",
    )
    propose_parser.add_argument("--model", required=True, help="explicit model name")
    propose_parser.add_argument(
        "--out",
        type=Path,
        help="new candidate JSON path; defaults beside the source in .proofside/",
    )
    propose_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible base URL; API is remote and local defaults to localhost",
    )
    propose_parser.add_argument(
        "--api-key-env",
        help="credential environment-variable name required for a custom API base URL",
    )
    propose_parser.add_argument(
        "--source",
        action="append",
        choices=("equation", "intent", "implementation"),
        help="repeatable specification source; defaults to available equation/intent annotations",
    )
    propose_all_parser = subparsers.add_parser(
        "propose-all",
        help="propose candidates with up to one model request per marked function",
        description=(
            "Independently propose unverified candidates for marked functions, "
            "using deterministic source-adjacent paths. Nothing is accepted or verified."
        ),
    )
    propose_all_parser.add_argument("targets", nargs="+", type=Path, help="Python files or directories")
    propose_all_parser.add_argument(
        "--model-source",
        choices=("api", "local"),
        required=True,
        help="api sends selected context remotely; local sends it to the chosen local endpoint",
    )
    propose_all_parser.add_argument("--model", required=True, help="explicit model name")
    propose_all_parser.add_argument("--base-url", help="OpenAI-compatible base URL")
    propose_all_parser.add_argument(
        "--api-key-env",
        help="credential environment-variable name required for a custom API base URL",
    )
    propose_all_parser.add_argument(
        "--source",
        action="append",
        choices=("equation", "intent", "implementation"),
        help="repeatable specification source; defaults per function to equation/intent annotations",
    )
    interpret_parser = subparsers.add_parser(
        "interpret",
        help="ask a model to explain one contract without source context",
        description=(
            "Ask an explicitly selected model for a blind, contract-only explanation. "
            "This is not a correctness check and never runs verification."
        ),
    )
    interpret_parser.add_argument("contract", type=Path, help="Proofside contract JSON path")
    interpret_parser.add_argument(
        "--model-source",
        choices=("api", "local"),
        required=True,
        help="api sends the contract remotely; local sends it to the chosen local endpoint",
    )
    interpret_parser.add_argument("--model", required=True, help="explicit model name")
    interpret_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible base URL; API is remote and local defaults to localhost",
    )
    interpret_parser.add_argument(
        "--api-key-env",
        help="credential environment-variable name required for a custom API base URL",
    )
    accept_parser = subparsers.add_parser(
        "accept",
        help="explicitly accept a candidate contract for later verification",
        description=(
            "Validate a candidate and record it as accepted for verification. "
            "Acceptance does not assert correctness or run verification."
        ),
    )
    accept_parser.add_argument("selector", help="path/to/file.py::function_name")
    accept_parser.add_argument(
        "--candidate",
        type=Path,
        help="candidate JSON path; defaults beside the source in .proofside/",
    )
    accept_parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing accepted contract after successful validation",
    )
    arguments = parser.parse_args(argv)

    if arguments.command == "check":
        result = check(arguments.selector, arguments.contract, arguments.backend)
        print(render_output(result))
        return 0 if result.status is Status.VERIFIED else 1

    if arguments.command == "check-all":
        results, discovery_errors = run_batch_checks(
            tuple(arguments.targets),
            arguments.allow_unreviewed,
            arguments.backend,
        )
        verifier = "Lean 4" if arguments.backend == "lean" else "Nagini/Viper"
        print(f"Selected backend: {verifier}")
        print(render_batch_output(results, discovery_errors))
        return 0 if batch_succeeded(results, discovery_errors) else 1

    if arguments.command == "propose-all":
        results, discovery_errors = run_batch_proposals(
            tuple(arguments.targets),
            arguments.model_source,
            arguments.model,
            arguments.base_url,
            arguments.api_key_env,
            tuple(arguments.source) if arguments.source else None,
        )
        print(render_batch_proposal_output(results, discovery_errors))
        return 0 if batch_proposal_succeeded(results, discovery_errors) else 1

    if arguments.command == "accept":
        try:
            contract_text, candidate_path, accepted_path = accept_contract(
                arguments.selector,
                arguments.candidate,
                arguments.replace,
            )
        except AcceptanceError as error:
            print("ACCEPTANCE REJECTED")
            print(error)
            return 1
        print(render_acceptance_output(contract_text, candidate_path, accepted_path))
        return 0

    if arguments.command == "interpret":
        try:
            interpretation = interpret_contract(
                arguments.contract,
                arguments.model_source,
                arguments.model,
                arguments.base_url,
                arguments.api_key_env,
            )
        except InterpretationError as error:
            print("INTERPRETATION FAILED")
            print(error)
            return 1
        print(render_interpretation_output(interpretation))
        return 0

    try:
        contract_text, sources = propose_contract(
            arguments.selector,
            arguments.model_source,
            arguments.model,
            arguments.out,
            arguments.base_url,
            arguments.api_key_env,
            tuple(arguments.source) if arguments.source else None,
        )
    except ProposalError as error:
        print("PROPOSAL REJECTED")
        print(error)
        return 1
    output_path = arguments.out
    if output_path is None:
        file_path, function_name = parse_selector(arguments.selector)
        output_path = candidate_contract_path(file_path, function_name)
    print(render_proposal_output(arguments.selector, output_path, contract_text, sources))
    return 0

