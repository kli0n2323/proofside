from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tokenize

from .artifacts import accepted_contract_path, candidate_contract_path
from .cli import CheckResult, Status, check
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


def run_batch_checks(
    targets: tuple[Path, ...],
    allow_unreviewed: bool = False,
) -> tuple[tuple[BatchCheckResult, ...], tuple[tuple[Path, str], ...]]:
    files, discovery_errors = discover_python_files(targets)
    results = []
    errors = list(discovery_errors)
    for file_path in files:
        try:
            source = file_path.read_text(encoding="utf-8")
            functions = marked_functions_in_source(source)
        except (OSError, UnicodeError, SyntaxError, tokenize.TokenError) as error:
            errors.append((file_path, _discovery_error_detail(error)))
            continue

        for function in functions:
            selector = f"{file_path}::{function.name}"
            try:
                specification_annotations_for_function(source, function)
            except SpecificationAnnotationError as error:
                results.append(
                    BatchCheckResult(
                        selector,
                        issue="INVALID SPECIFICATION",
                        detail=str(error),
                    )
                )
                continue

            accepted_path = accepted_contract_path(file_path, function.name)
            candidate_path = candidate_contract_path(file_path, function.name)
            if accepted_path.is_file():
                contract_path = accepted_path
                unreviewed = False
            elif allow_unreviewed and candidate_path.is_file():
                contract_path = candidate_path
                unreviewed = True
            else:
                issue = "NO CONTRACT" if allow_unreviewed else "NO ACCEPTED CONTRACT"
                detail = str(candidate_path if allow_unreviewed else accepted_path)
                results.append(BatchCheckResult(selector, issue=issue, detail=detail))
                continue

            results.append(
                BatchCheckResult(
                    selector,
                    check(selector, contract_path),
                    contract_path,
                    unreviewed,
                )
            )
    return tuple(results), tuple(errors)


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
