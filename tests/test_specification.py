from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap
import unittest

from proofside.specification import (
    SpecificationAnnotationError,
    extract_specification_annotations,
    find_annotated_functions,
)


def extract(source: str):
    return extract_specification_annotations(textwrap.dedent(source))


class SpecificationExtractionTests(unittest.TestCase):
    def test_extracts_basic_equation_and_intent(self) -> None:
        functions = extract(
            """
            # proofside equation: result = a + b
            # proofside intent: Return the sum.
            def add(a: int, b: int) -> int:
                return a + b
            """
        )

        self.assertEqual(len(functions), 1)
        self.assertEqual(functions[0].name, "add")
        self.assertEqual(functions[0].annotations.equations, ("result = a + b",))
        self.assertEqual(functions[0].annotations.intents, ("Return the sum.",))

    def test_preserves_repeated_intents_in_order(self) -> None:
        functions = extract(
            """
            # proofside intent: Return the unused allocation.
            # proofside intent: Inputs represent nonnegative counts.
            # proofside intent: Used allocations must not exceed the total.
            def remaining(total: int, used: int) -> int:
                return total - used
            """
        )

        self.assertEqual(
            functions[0].annotations.intents,
            (
                "Return the unused allocation.",
                "Inputs represent nonnegative counts.",
                "Used allocations must not exceed the total.",
            ),
        )

    def test_preserves_multiple_equations_in_order(self) -> None:
        functions = extract(
            """
            # proofside equation: remainder = total - used
            # proofside equation: used = train + test
            def remaining(total: int, train: int, test: int) -> int:
                return total - train - test
            """
        )

        self.assertEqual(
            functions[0].annotations.equations,
            ("remainder = total - used", "used = train + test"),
        )

    def test_equation_only_and_intent_only_are_valid(self) -> None:
        functions = extract(
            """
            # proofside equation: result = a + b
            def add(a: int, b: int) -> int:
                return a + b

            # proofside intent: Return the input unchanged.
            def identity(value: int) -> int:
                return value
            """
        )

        self.assertEqual([function.name for function in functions], ["add", "identity"])
        self.assertEqual(functions[0].annotations.intents, ())
        self.assertEqual(functions[1].annotations.equations, ())

    def test_ignores_normal_comments_in_leading_block(self) -> None:
        functions = extract(
            """
            # This function handles the budget remainder.
            # proofside equation: result = total - used
            # proofside intent: Return unused capacity.
            # Keep this implementation simple.
            def remaining(total: int, used: int) -> int:
                return total - used
            """
        )

        self.assertEqual(functions[0].annotations.equations, ("result = total - used",))
        self.assertEqual(functions[0].annotations.intents, ("Return unused capacity.",))

    def test_blank_line_and_statement_break_association(self) -> None:
        functions = extract(
            """
            # proofside equation: result = a

            def separated(a: int) -> int:
                return a

            # proofside equation: result = b
            SOME_CONSTANT = 3

            def interrupted(b: int) -> int:
                return b
            """
        )

        self.assertEqual(functions, ())

    def test_annotations_do_not_leak_to_next_function(self) -> None:
        functions = extract(
            """
            # proofside equation: result = a
            def first(a: int) -> int:
                return a

            def second(b: int) -> int:
                return b
            """
        )

        self.assertEqual([function.name for function in functions], ["first"])

    def test_several_functions_are_independent_and_in_source_order(self) -> None:
        functions = extract(
            """
            # proofside intent: First specification.
            def first(a: int) -> int:
                return a

            # proofside equation: result = b + 1
            def second(b: int) -> int:
                return b + 1

            # proofside intent: Third specification.
            def third(c: int) -> int:
                return c
            """
        )

        self.assertEqual([function.name for function in functions], ["first", "second", "third"])
        self.assertEqual(functions[0].annotations.intents, ("First specification.",))
        self.assertEqual(functions[1].annotations.equations, ("result = b + 1",))
        self.assertEqual(functions[2].annotations.intents, ("Third specification.",))

    def test_strings_and_function_body_comments_are_not_annotations(self) -> None:
        functions = extract(
            '''
            text = "# proofside equation: result = a + b"

            def f() -> str:
                # proofside intent: This is inside the function body.
                return "# proofside intent: also a string"
            '''
        )

        self.assertEqual(functions, ())

    def test_prefixes_are_case_sensitive(self) -> None:
        functions = extract(
            """
            # Proofside equation: result = value
            # PROOFSIDE INTENT: Return the value.
            def identity(value: int) -> int:
                return value
            """
        )

        self.assertEqual(functions, ())

    def test_nested_methods_and_async_functions_are_not_discovered(self) -> None:
        functions = extract(
            """
            def outer(value: int) -> int:
                # proofside equation: result = value
                def nested(value: int) -> int:
                    return value
                return nested(value)

            class Example:
                # proofside intent: Return the value.
                def method(self, value: int) -> int:
                    return value

            # proofside equation: result = value
            async def asynchronous(value: int) -> int:
                return value
            """
        )

        self.assertEqual(functions, ())

    def test_empty_equation_and_intent_fail_clearly(self) -> None:
        for tag in ("equation", "intent"):
            with self.subTest(tag=tag):
                with self.assertRaisesRegex(
                    SpecificationAnnotationError,
                    f"empty proofside {tag} annotation",
                ):
                    extract(
                        f"""
                        # proofside {tag}:
                        def identity(value: int) -> int:
                            return value
                        """
                    )

    def test_strips_surrounding_but_not_internal_whitespace(self) -> None:
        functions = extract(
            """
            # proofside equation:    result  =  a + b   
            def add(a: int, b: int) -> int:
                return a + b
            """
        )

        self.assertEqual(functions[0].annotations.equations, ("result  =  a + b",))

    def test_file_discovery_reads_utf8_source(self) -> None:
        source = textwrap.dedent(
            """
            # proofside intent: Return Δ unchanged.
            def identity(value: int) -> int:
                return value
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory, "annotated.py")
            file_path.write_text(source, encoding="utf-8")

            functions = find_annotated_functions(file_path)

        self.assertEqual(functions[0].annotations.intents, ("Return Δ unchanged.",))


if __name__ == "__main__":
    unittest.main()
