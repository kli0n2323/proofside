from __future__ import annotations

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import tokenize

from .artifacts import accepted_contract_path, candidate_contract_path
from .cli import CheckResult, Status, check
from .proposal import ProposalError, propose_contract
from .specification import (
    SpecificationAnnotationError,
    marked_functions_in_source,
    specification_annotations_for_function,
)


@dataclass(frozen=True)
class BatchCheckResult:
    selector: str
    result: CheckResult | None = None
    contract_path: Path | None = None
    unreviewed: bool = False
    issue: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class MarkedTarget:
    file_path: Path
    source: str
    function: ast.FunctionDef

    @property
    def selector(self) -> str:
        return f"{self.file_path}::{self.function.name}"


@dataclass(frozen=True)
class BatchProposalResult:
    selector: str
    candidate_path: Path
    sources: tuple[str, ...] = ()
    proposed: bool = False
    issue: str | None = None
    detail: str = ""


def discover_python_files(
    targets: tuple[Path, ...],
) -> tuple[tuple[Path, ...], tuple[tuple[Path, str], ...]]:
    files: dict[Path, Path] = {}
    errors = []
    for target in targets:
        if target.is_file():
            if target.suffix != ".py":
                errors.append((target, "target is not a Python file"))
            else:
                files.setdefault(target.resolve(), target)
            continue
        if not target.is_dir():
            errors.append((target, "target does not exist"))
            continue
        if target.name.startswith("."):
            continue

        walk_errors = []
        for directory, subdirectories, names in os.walk(
            target,
            onerror=walk_errors.append,
        ):
            subdirectories[:] = sorted(
                name for name in subdirectories if not name.startswith(".")
            )
            for name in sorted(names):
                if name.endswith(".py"):
                    path = Path(directory, name)
                    files.setdefault(path.resolve(), path)
        errors.extend((Path(error.filename or target), str(error)) for error in walk_errors)

    paths = tuple(sorted(files.values(), key=lambda path: path.as_posix()))
    return paths, tuple(errors)


def discover_marked_targets(
    targets: tuple[Path, ...],
) -> tuple[tuple[MarkedTarget, ...], tuple[tuple[Path, str], ...]]:
    files, discovery_errors = discover_python_files(targets)
    marked_targets = []
    errors = list(discovery_errors)
    for file_path in files:
        try:
            source = file_path.read_text(encoding="utf-8")
            functions = marked_functions_in_source(source)
        except (OSError, UnicodeError, SyntaxError, tokenize.TokenError) as error:
            errors.append((file_path, _discovery_error_detail(error)))
            continue
        marked_targets.extend(
            MarkedTarget(file_path, source, function) for function in functions
        )
    return tuple(marked_targets), tuple(errors)


def run_batch_checks(
    targets: tuple[Path, ...],
    allow_unreviewed: bool = False,
    backend: str = "nagini",
) -> tuple[tuple[BatchCheckResult, ...], tuple[tuple[Path, str], ...]]:
    marked_targets, discovery_errors = discover_marked_targets(targets)
    results = []

    for target in marked_targets:
        try:
            specification_annotations_for_function(target.source, target.function)
        except SpecificationAnnotationError as error:
            results.append(
                BatchCheckResult(
                    target.selector,
                    issue="INVALID SPECIFICATION",
                    detail=str(error),
                )
            )
            continue

        accepted_path = accepted_contract_path(target.file_path, target.function.name)
        candidate_path = candidate_contract_path(target.file_path, target.function.name)
        if accepted_path.is_file():
            contract_path = accepted_path
            unreviewed = False
        elif allow_unreviewed and candidate_path.is_file():
            contract_path = candidate_path
            unreviewed = True
        else:
            issue = "NO CONTRACT" if allow_unreviewed else "NO ACCEPTED CONTRACT"
            detail = str(candidate_path if allow_unreviewed else accepted_path)
            results.append(BatchCheckResult(target.selector, issue=issue, detail=detail))
            continue

        result = (
            check(target.selector, contract_path)
            if backend == "nagini"
            else check(target.selector, contract_path, backend)
        )
        results.append(
            BatchCheckResult(
                target.selector,
                result,
                contract_path,
                unreviewed,
            )
        )
    return tuple(results), discovery_errors


def run_batch_proposals(
    targets: tuple[Path, ...],
    model_source: str,
    model: str,
    base_url: str | None = None,
    api_key_env: str | None = None,
    sources: tuple[str, ...] | None = None,
) -> tuple[tuple[BatchProposalResult, ...], tuple[tuple[Path, str], ...]]:
    marked_targets, discovery_errors = discover_marked_targets(targets)
    results = []
    for target in marked_targets:
        output_path = candidate_contract_path(target.file_path, target.function.name)
        if output_path.exists():
            results.append(
                BatchProposalResult(
                    target.selector,
                    output_path,
                    issue="CANDIDATE EXISTS",
                    detail=str(output_path),
                )
            )
            continue
        try:
            _contract_text, used_sources = propose_contract(
                target.selector,
                model_source,
                model,
                None,
                base_url,
                api_key_env,
                sources,
            )
        except ProposalError as error:
            results.append(
                BatchProposalResult(
                    target.selector,
                    output_path,
                    issue="PROPOSAL REJECTED",
                    detail=str(error),
                )
            )
            continue
        results.append(
            BatchProposalResult(
                target.selector,
                output_path,
                used_sources,
                proposed=True,
            )
        )
    return tuple(results), discovery_errors


def _discovery_error_detail(error: BaseException) -> str:
    if isinstance(error, SyntaxError):
        location = f"line {error.lineno}" if error.lineno else "unknown line"
        return f"cannot parse ({location}): {error.msg}"
    return str(error)


def batch_succeeded(
    results: tuple[BatchCheckResult, ...],
    discovery_errors: tuple[tuple[Path, str], ...],
) -> bool:
    return bool(results) and not discovery_errors and all(
        item.result is not None
        and item.result.status is Status.VERIFIED
        and not item.unreviewed
        for item in results
    )


def batch_proposal_succeeded(
    results: tuple[BatchProposalResult, ...],
    discovery_errors: tuple[tuple[Path, str], ...],
) -> bool:
    return bool(results) and not discovery_errors and all(
        item.proposed for item in results
    )


def render_batch_output(
    results: tuple[BatchCheckResult, ...],
    discovery_errors: tuple[tuple[Path, str], ...],
) -> str:
    total = len(results)
    verified = sum(
        item.result is not None and item.result.status is Status.VERIFIED
        for item in results
    )
    lines = ["Proofside batch", ""]
    if not total:
        lines.append("0 Proofside-marked functions found")
    else:
        lines.extend((f"{total} Proofside-marked functions", f"{verified}/{total} VERIFIED"))

    groups: dict[str, list[tuple[str, str]]] = {}
    for item in results:
        if item.issue:
            category = item.issue
            detail = item.detail
        elif item.unreviewed:
            category = f"{item.result.status.value} (UNREVIEWED CONTRACT)"
            detail = str(item.contract_path)
        elif item.result.status is not Status.VERIFIED:
            category = item.result.status.value
            detail = item.result.detail
        else:
            continue
        groups.setdefault(category, []).append((item.selector, detail))
    if discovery_errors:
        groups["DISCOVERY ERROR"] = [
            (str(path), detail) for path, detail in discovery_errors
        ]

    for category, items in groups.items():
        lines.extend(("", category))
        for selector, detail in items:
            lines.append(f"- {selector}")
            if detail:
                lines.append(f"  {detail}")
    return "\n".join(lines)


def render_batch_proposal_output(
    results: tuple[BatchProposalResult, ...],
    discovery_errors: tuple[tuple[Path, str], ...],
) -> str:
    total = len(results)
    proposed = sum(item.proposed for item in results)
    lines = ["Proofside batch proposal", ""]
    if not total:
        lines.append("0 Proofside-marked functions found")
    else:
        lines.extend((f"{total} Proofside-marked functions", f"{proposed}/{total} PROPOSED"))

    groups: dict[str, list[tuple[str, str]]] = {}
    for item in results:
        if item.issue:
            groups.setdefault(item.issue, []).append((item.selector, item.detail))
    if discovery_errors:
        groups["DISCOVERY ERROR"] = [
            (str(path), detail) for path, detail in discovery_errors
        ]

    for category, items in groups.items():
        lines.extend(("", category))
        for selector, detail in items:
            lines.append(f"- {selector}")
            if detail:
                lines.append(f"  {detail}")
    if proposed:
        lines.extend(
            (
                "",
                "Candidates were saved under source-adjacent .proofside/ directories.",
                "Review or edit them, then accept explicitly before check-all.",
            )
        )
    return "\n".join(lines)
