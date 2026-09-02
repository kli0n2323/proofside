from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import tokenize


EQUATION_PREFIX = "# proofside equation:"
INTENT_PREFIX = "# proofside intent:"


class SpecificationAnnotationError(ValueError):
    pass


@dataclass(frozen=True)
class SpecificationAnnotations:
    equations: tuple[str, ...]
    intents: tuple[str, ...]


@dataclass(frozen=True)
class AnnotatedFunction:
    name: str
    function: ast.FunctionDef
    annotations: SpecificationAnnotations


def _comment_tokens(source: str) -> dict[int, tokenize.TokenInfo]:
    lines = source.splitlines()
    comment_tokens: dict[int, tokenize.TokenInfo] = {}
    for token in tokenize.generate_tokens(StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        line_number, column = token.start
        if lines[line_number - 1][:column].strip():
            continue
        comment_tokens[line_number] = token
    return comment_tokens


def _annotations_for_function(
    comment_tokens: dict[int, tokenize.TokenInfo],
    function: ast.FunctionDef,
) -> SpecificationAnnotations:
    leading_comments = []
    line_number = function.lineno - 1
    while line_number in comment_tokens:
        token = comment_tokens[line_number]
        if token.start[1] != function.col_offset:
            break
        leading_comments.append(token)
        line_number -= 1
    leading_comments.reverse()

    equations = []
    intents = []
    for token in leading_comments:
        for prefix, destination, label in (
            (EQUATION_PREFIX, equations, "equation"),
            (INTENT_PREFIX, intents, "intent"),
        ):
            if not token.string.startswith(prefix):
                continue
            text = token.string.removeprefix(prefix).strip()
            if not text:
                raise SpecificationAnnotationError(
                    f"empty proofside {label} annotation"
                )
            destination.append(text)
            break

    return SpecificationAnnotations(tuple(equations), tuple(intents))


def specification_annotations_for_function(
    source: str,
    function: ast.FunctionDef,
) -> SpecificationAnnotations:
    return _annotations_for_function(_comment_tokens(source), function)


def extract_specification_annotations(source: str) -> tuple[AnnotatedFunction, ...]:
    tree = ast.parse(source)
    comment_tokens = _comment_tokens(source)

    discovered = []
    for function in (
        node for node in tree.body if isinstance(node, ast.FunctionDef)
    ):
        annotations = _annotations_for_function(comment_tokens, function)
        if annotations.equations or annotations.intents:
            discovered.append(
                AnnotatedFunction(
                    function.name,
                    function,
                    annotations,
                )
            )
    return tuple(discovered)


def find_annotated_functions(file_path: Path) -> tuple[AnnotatedFunction, ...]:
    return extract_specification_annotations(file_path.read_text(encoding="utf-8"))
