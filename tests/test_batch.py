from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from proofside.artifacts import accepted_contract_path, candidate_contract_path
from proofside.batch import (
    batch_succeeded,
    discover_python_files,
    render_batch_output,
    run_batch_checks,
)
from proofside.cli import CheckResult, Status, main


VERIFIED = CheckResult(Status.VERIFIED, "proved")


def write_source(path: Path, names: tuple[str, ...], unmarked: bool = False) -> None:
    sections = []
    for name in names:
        sections.append(
            f"# proofside equation: result = value\n"
            f"def {name}(value: int) -> int:\n"
            f"    return value\n"
        )
    if unmarked:
        sections.append("def ignored(value: int) -> int:\n    return value\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sections), encoding="utf-8")


def touch_contract(source_path: Path, function_name: str, candidate: bool = False) -> Path:
    helper = candidate_contract_path if candidate else accepted_contract_path
    path = helper(source_path, function_name)
    path.parent.mkdir(exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    return path


class BatchCheckTests(unittest.TestCase):
    def test_one_file_checks_each_marked_function_and_ignores_unmarked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "model.py")
            names = ("first", "second", "third")
            write_source(path, names, unmarked=True)
            contracts = [touch_contract(path, name) for name in names]

            with patch("proofside.batch.check", return_value=VERIFIED) as check:
                results, errors = run_batch_checks((path,))

            self.assertEqual(errors, ())
            self.assertEqual([item.selector.rsplit("::", 1)[1] for item in results], list(names))
            self.assertEqual(
                check.call_args_list,
                [call(f"{path}::{name}", contract) for name, contract in zip(names, contracts)],
            )

    def test_recursive_discovery_is_sorted_deduplicated_and_skips_hidden_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "research")
            visible_paths = [root / "a.py", root / "nested" / "b.py"]
            hidden_paths = [
                root / ".venv" / "ignored.py",
                root / ".hidden" / "ignored.py",
                root / ".proofside" / "ignored.py",
            ]
            for path in (*visible_paths, *hidden_paths):
                write_source(path, (path.stem,))
            for path in visible_paths:
                touch_contract(path, path.stem)

            files, errors = discover_python_files((root, visible_paths[0]))
            with patch("proofside.batch.check", return_value=VERIFIED) as check:
                results, batch_errors = run_batch_checks((root, visible_paths[0]))

            self.assertEqual(errors, ())
            self.assertEqual(files, tuple(visible_paths))
            self.assertEqual(batch_errors, ())
            self.assertEqual([item.selector for item in results], [f"{path}::{path.stem}" for path in visible_paths])
            self.assertEqual(check.call_count, 2)

    def test_contract_selection_and_unreviewed_exit_safety(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "model.py")
            write_source(source_path, ("selected",))
            selector = f"{source_path}::selected"

            with patch("proofside.batch.check") as check:
                results, errors = run_batch_checks((source_path,))
            self.assertEqual(results[0].issue, "NO ACCEPTED CONTRACT")
            self.assertIn(".contract.json", results[0].detail)
            self.assertFalse(batch_succeeded(results, errors))
            check.assert_not_called()

            candidate = touch_contract(source_path, "selected", candidate=True)
            with patch("proofside.batch.check", return_value=VERIFIED) as check:
                results, errors = run_batch_checks((source_path,), allow_unreviewed=True)
            check.assert_called_once_with(selector, candidate)
            self.assertTrue(results[0].unreviewed)
            self.assertIn("VERIFIED (UNREVIEWED CONTRACT)", render_batch_output(results, errors))
            self.assertFalse(batch_succeeded(results, errors))

            accepted = touch_contract(source_path, "selected")
            with patch("proofside.batch.check", return_value=VERIFIED) as check:
                results, errors = run_batch_checks((source_path,), allow_unreviewed=True)
            check.assert_called_once_with(selector, accepted)
            self.assertFalse(results[0].unreviewed)
            self.assertTrue(batch_succeeded(results, errors))

    def test_bypass_without_any_artifact_reports_no_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "model.py")
            write_source(source_path, ("selected",))
            with patch("proofside.batch.check") as check:
                results, errors = run_batch_checks((source_path,), allow_unreviewed=True)

            self.assertEqual(results[0].issue, "NO CONTRACT")
            self.assertFalse(batch_succeeded(results, errors))
            check.assert_not_called()

    def test_formal_statuses_are_aggregated_and_later_checks_continue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "model.py")
            names = ("failed", "unsupported", "errored")
            write_source(source_path, names)
            for name in names:
                touch_contract(source_path, name)
            outcomes = (
                CheckResult(Status.FAILED, "postcondition might not hold"),
                CheckResult(Status.UNSUPPORTED, "unsupported source"),
                CheckResult(Status.ERROR, "verifier unavailable"),
            )

            with patch("proofside.batch.check", side_effect=outcomes) as check:
                results, errors = run_batch_checks((source_path,))
            output = render_batch_output(results, errors)

            self.assertEqual(check.call_count, 3)
            self.assertIn("FAILED", output)
            self.assertIn("postcondition might not hold", output)
            self.assertIn("UNSUPPORTED", output)
            self.assertIn("ERROR", output)
            self.assertFalse(batch_succeeded(results, errors))

    def test_malformed_annotation_is_isolated_per_function(self) -> None:
        source = (
            "# proofside intent:\n"
            "def malformed(value: int) -> int:\n"
            "    return value\n\n"
            "# proofside equation: result = value\n"
            "def valid(value: int) -> int:\n"
            "    return value\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "model.py")
            source_path.write_text(source, encoding="utf-8")
            touch_contract(source_path, "malformed")
            valid_contract = touch_contract(source_path, "valid")

            with patch("proofside.batch.check", return_value=VERIFIED) as check:
                results, errors = run_batch_checks((source_path,))

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].issue, "INVALID SPECIFICATION")
            self.assertIn("empty proofside intent", results[0].detail)
            check.assert_called_once_with(f"{source_path}::valid", valid_contract)
            self.assertEqual(results[1].result.status, Status.VERIFIED)
            self.assertEqual(errors, ())

    def test_file_errors_are_isolated_from_valid_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bad_path = Path(directory, "bad.py")
            bad_path.write_text("def broken(:\n", encoding="utf-8")
            good_path = Path(directory, "good.py")
            write_source(good_path, ("valid",))
            valid_contract = touch_contract(good_path, "valid")
            missing_path = Path(directory, "missing.py")

            with patch("proofside.batch.check", return_value=VERIFIED) as check:
                results, errors = run_batch_checks((bad_path, good_path, missing_path))

            check.assert_called_once_with(f"{good_path}::valid", valid_contract)
            self.assertEqual(len(results), 1)
            self.assertEqual(len(errors), 2)
            output = render_batch_output(results, errors)
            self.assertIn("DISCOVERY ERROR", output)
            self.assertIn(str(bad_path), output)
            self.assertIn(str(missing_path), output)
            self.assertFalse(batch_succeeded(results, errors))

    def test_all_verified_and_no_marked_functions_have_safe_exit_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "model.py")
            write_source(source_path, ("first", "second"))
            for name in ("first", "second"):
                touch_contract(source_path, name)
            with patch("proofside.batch.check", return_value=VERIFIED):
                results, errors = run_batch_checks((source_path,))

            self.assertTrue(batch_succeeded(results, errors))
            self.assertIn("2/2 VERIFIED", render_batch_output(results, errors))

            empty_path = Path(directory, "empty.py")
            empty_path.write_text(
                "def unmarked(value: int) -> int:\n    return value\n",
                encoding="utf-8",
            )
            empty_results, empty_errors = run_batch_checks((empty_path,))
            self.assertFalse(batch_succeeded(empty_results, empty_errors))
            self.assertIn(
                "0 Proofside-marked functions found",
                render_batch_output(empty_results, empty_errors),
            )

    def test_cli_returns_zero_only_for_accepted_all_verified_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "model.py")
            write_source(source_path, ("selected",))
            touch_contract(source_path, "selected")
            with (
                patch("proofside.batch.check", return_value=VERIFIED),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                exit_code = main(["check-all", str(source_path)])

            self.assertEqual(exit_code, 0)
            self.assertIn("1/1 VERIFIED", stdout.getvalue())

            empty_path = Path(directory, "empty.py")
            empty_path.write_text("def unmarked() -> int:\n    return 1\n", encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main(["check-all", str(empty_path)]), 1)


if __name__ == "__main__":
    unittest.main()
