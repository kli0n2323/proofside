from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from proofside.artifacts import accepted_contract_path, candidate_contract_path
from proofside.batch import (
    batch_proposal_succeeded,
    discover_marked_targets,
    render_batch_proposal_output,
    run_batch_proposals,
)
from proofside.cli import main


VALID_CONTRACT = {
    "requires": [],
    "ensures": [
        {
            "kind": "compare",
            "operator": "==",
            "left": {"kind": "result"},
            "right": {"kind": "variable", "name": "value"},
        }
    ],
}


def marked_function(name: str, annotation: str | None = None) -> str:
    annotation = annotation or "# proofside equation: result = value"
    return (
        f"{annotation}\n"
        f"def {name}(value: int) -> int:\n"
        f"    return value\n"
    )


def write_source(path: Path, sections: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sections), encoding="utf-8")


class BatchProposalTests(unittest.TestCase):
    def test_shared_discovery_is_recursive_sorted_hidden_safe_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "research")
            first = root / "a.py"
            second = root / "nested" / "b.py"
            write_source(first, (marked_function("first"),))
            write_source(second, (marked_function("second"),))
            for hidden in (".venv", ".hidden", ".proofside"):
                write_source(root / hidden / "ignored.py", (marked_function("ignored"),))

            targets, errors = discover_marked_targets((root, first))

            self.assertEqual(errors, ())
            self.assertEqual(
                [target.selector for target in targets],
                [f"{first}::first", f"{second}::second"],
            )

    def test_multiple_marked_functions_forward_exact_configuration_and_ignore_unmarked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "model.py")
            write_source(
                path,
                (
                    marked_function("first"),
                    "def ignored(value: int) -> int:\n    return value\n",
                    marked_function("second"),
                    marked_function("third"),
                ),
            )
            sources = ("equation", "implementation")
            with patch(
                "proofside.batch.propose_contract",
                return_value=("rendered", sources),
            ) as propose:
                results, errors = run_batch_proposals(
                    (path,),
                    "local",
                    "model",
                    "http://127.0.0.1:9000/v1",
                    None,
                    sources,
                )

            self.assertEqual(errors, ())
            self.assertEqual([item.selector.rsplit("::", 1)[1] for item in results], ["first", "second", "third"])
            self.assertEqual(
                propose.call_args_list,
                [
                    call(
                        f"{path}::{name}",
                        "local",
                        "model",
                        None,
                        "http://127.0.0.1:9000/v1",
                        None,
                        sources,
                    )
                    for name in ("first", "second", "third")
                ],
            )

    def test_existing_candidate_is_skipped_but_accepted_contract_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "model.py")
            write_source(path, (marked_function("existing"), marked_function("fresh")))
            existing_candidate = candidate_contract_path(path, "existing")
            existing_candidate.parent.mkdir()
            existing_candidate.write_text("keep", encoding="utf-8")
            accepted_contract_path(path, "fresh").write_text("accepted", encoding="utf-8")

            with (
                patch(
                    "proofside.batch.propose_contract",
                    return_value=("rendered", ("equation",)),
                ) as propose,
                patch("proofside.proposal.request_model") as request_model,
            ):
                results, errors = run_batch_proposals((path,), "local", "model")

            self.assertEqual(errors, ())
            self.assertEqual(results[0].issue, "CANDIDATE EXISTS")
            self.assertEqual(existing_candidate.read_text(encoding="utf-8"), "keep")
            propose.assert_called_once_with(
                f"{path}::fresh", "local", "model", None, None, None, None
            )
            request_model.assert_not_called()
            self.assertTrue(results[1].proposed)
            self.assertFalse(batch_proposal_succeeded(results, errors))

    def test_real_proposal_path_creates_candidates_with_default_body_privacy(self) -> None:
        source = (
            "# proofside equation: result = value\n"
            "# proofside intent: Return value unchanged.\n"
            "def first(value: int) -> int:\n"
            "    first_body_secret = value + 101\n"
            "    return first_body_secret\n\n"
            "# proofside equation: result = value\n"
            "# proofside intent: Preserve the input.\n"
            "def second(value: int) -> int:\n"
            "    second_body_secret = value + 202\n"
            "    return second_body_secret\n"
        )
        prompts = []

        def respond(_url, _model, prompt, _key):
            prompts.append(prompt)
            return json.dumps(VALID_CONTRACT)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "model.py")
            path.write_text(source, encoding="utf-8")
            with (
                patch("proofside.proposal.request_model", side_effect=respond) as request_model,
                patch("proofside.batch.check") as check,
                patch("proofside.cli.run_nagini") as run_nagini,
                patch("proofside.acceptance.accept_contract") as accept,
            ):
                results, errors = run_batch_proposals((path,), "local", "model")

            self.assertEqual(errors, ())
            self.assertEqual(request_model.call_count, 2)
            self.assertTrue(all(item.proposed for item in results))
            self.assertEqual([item.sources for item in results], [("equation", "intent")] * 2)
            for name in ("first", "second"):
                self.assertTrue(candidate_contract_path(path, name).is_file())
                self.assertFalse(accepted_contract_path(path, name).exists())
            self.assertTrue(all("[EQUATION]" in prompt and "[INTENT]" in prompt for prompt in prompts))
            self.assertTrue(all("body_secret" not in prompt for prompt in prompts))
            check.assert_not_called()
            run_nagini.assert_not_called()
            accept.assert_not_called()

    def test_malformed_and_missing_requested_sources_are_isolated(self) -> None:
        cases = {
            "malformed": (
                marked_function("rejected", "# proofside intent:"),
                marked_function("eligible", "# proofside intent: Return value."),
                None,
                "empty proofside intent annotation",
            ),
            "missing_intent": (
                marked_function("rejected"),
                marked_function("eligible", "# proofside intent: Return value."),
                ("intent",),
                "requested specification source 'intent' is not available",
            ),
        }
        for name, (rejected, eligible, sources, expected_error) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory, "model.py")
                write_source(path, (rejected, eligible))
                with patch(
                    "proofside.proposal.request_model",
                    return_value=json.dumps(VALID_CONTRACT),
                ) as request_model:
                    results, errors = run_batch_proposals(
                        (path,), "local", "model", sources=sources
                    )

                self.assertEqual(errors, ())
                self.assertEqual(results[0].issue, "PROPOSAL REJECTED")
                self.assertIn(expected_error, results[0].detail)
                self.assertTrue(results[1].proposed)
                self.assertEqual(request_model.call_count, 1)

    def test_invalid_model_json_does_not_stop_later_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "model.py")
            write_source(path, (marked_function("first"), marked_function("second")))
            with patch(
                "proofside.proposal.request_model",
                side_effect=("not json", json.dumps(VALID_CONTRACT)),
            ) as request_model:
                results, errors = run_batch_proposals((path,), "local", "model")

            self.assertEqual(errors, ())
            self.assertEqual(request_model.call_count, 2)
            self.assertEqual(results[0].issue, "PROPOSAL REJECTED")
            self.assertFalse(candidate_contract_path(path, "first").exists())
            self.assertTrue(results[1].proposed)
            self.assertTrue(candidate_contract_path(path, "second").is_file())

    def test_discovery_error_does_not_stop_valid_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bad_path = Path(directory, "bad.py")
            bad_path.write_text("def broken(:\n", encoding="utf-8")
            good_path = Path(directory, "good.py")
            write_source(good_path, (marked_function("eligible"),))
            with patch(
                "proofside.batch.propose_contract",
                return_value=("rendered", ("equation",)),
            ) as propose:
                results, errors = run_batch_proposals(
                    (bad_path, good_path), "local", "model"
                )

            self.assertEqual(len(errors), 1)
            self.assertIn("cannot parse", errors[0][1])
            propose.assert_called_once()
            self.assertTrue(results[0].proposed)
            self.assertIn("DISCOVERY ERROR", render_batch_proposal_output(results, errors))

    def test_cli_exit_and_summary_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "model.py")
            write_source(path, (marked_function("first"), marked_function("second")))
            with (
                patch(
                    "proofside.batch.propose_contract",
                    return_value=("rendered", ("equation",)),
                ),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                exit_code = main(
                    [
                        "propose-all",
                        str(path),
                        "--model-source",
                        "local",
                        "--model",
                        "model",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("2/2 PROPOSED", stdout.getvalue())

            candidate = candidate_contract_path(path, "first")
            candidate.parent.mkdir(exist_ok=True)
            candidate.write_text("existing", encoding="utf-8")
            with (
                patch(
                    "proofside.batch.propose_contract",
                    return_value=("rendered", ("equation",)),
                ),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                exit_code = main(
                    [
                        "propose-all",
                        str(path),
                        "--model-source",
                        "local",
                        "--model",
                        "model",
                    ]
                )
            self.assertEqual(exit_code, 1)
            self.assertIn("1/2 PROPOSED", stdout.getvalue())
            self.assertIn("CANDIDATE EXISTS", stdout.getvalue())

            empty = Path(directory, "empty.py")
            empty.write_text("def unmarked() -> int:\n    return 1\n", encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = main(
                    [
                        "propose-all",
                        str(empty),
                        "--model-source",
                        "local",
                        "--model",
                        "model",
                    ]
                )
            self.assertEqual(exit_code, 1)
            self.assertIn("0 Proofside-marked functions found", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
