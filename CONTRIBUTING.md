# Contributing to Proofside

Proofside is intentionally small. A focused change should be understandable
without learning a framework or a large internal architecture.

## Development setup

Use Python 3.9–3.14. On Python 3.12+, the default Nagini backend needs Java 11+
and its pinned Python dependencies; Lean 4 is the optional native fallback:

```bash
git clone https://github.com/kli0n2323/proofside.git
cd proofside
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
```

Install Lean through [elan](https://lean-lang.org/install/manual/) when working
on the fallback; the project pins its native Lean version in `lean-toolchain`.

## Tests

Fast deterministic tests exercise Proofside-owned parsing, inspection,
rendering, classification, proposal, and security behavior. They require no API
credential or running model:

```bash
python -m unittest discover -s tests -v
```

The Lean integration check is:

```bash
proofside check examples/sidecar/shot_budget_plain.py::allocate_remaining \
  --contract examples/sidecar/shot_budget_contract.json
```

Before submitting a change, run the fast suite and any integration test affected
by it. Live model calls are not part of the automated suite.

## Code map

- `proofside/cli.py` — selector/AST inspection, Lean orchestration, result
  classification, console rendering, and argument parsing.
- `proofside/contracts.py` — the closed contract IR, strict parsing and
  validation, deterministic human rendering, and verifier dispatch.
- `proofside/lean.py` — deliberately restricted Python-to-Lean lowering.
- `proofside/specification.py` — deterministic Proofside annotation extraction
  and marked-function discovery.
- `proofside/proposal.py` — optional specification-source selection, model
  prompting, secure HTTP transport, validation, and candidate creation.
- `proofside/artifacts.py` — deterministic source-adjacent candidate and accepted
  contract paths.
- `proofside/acceptance.py` — explicit candidate validation and acceptance for
  later verification.
- `proofside/batch.py` — shared marked-target discovery and thin independent
  `propose-all` / `check-all` orchestration.
- `examples/` — workflow-organized sidecar, annotated,
  research-inspired, and unsupported demonstrations.
- `tests/` — fast Proofside-owned boundaries and Lean-lowering coverage.

## Design constraints

Please preserve these boundaries:

- Lean gets the final word on proof success for the supported source subset.
- Declared specification and implementation are distinct; a function body is
  model context only when the user explicitly selects it.
- Model proposal never verifies, accepts, or edits a contract automatically.
- Acceptance records selection for verification but never performs verification.
- Manual sidecars and optional model proposals are supported inputs to Lean.
- Model output and sidecar JSON are untrusted until strictly parsed and validated.
- Batch commands orchestrate independent single-function pipelines; they do not
  create a batch contract or proof.
- New contract syntax needs a concrete current use case, not anticipated demand.
- Extract an abstraction only when current consumers justify it and readability
  improves.
- `UNSUPPORTED` is an honest and useful result, not a failure to hide.
- Credential and network behavior should fail closed.
- Keep the production codebase readable in one sitting.

## Pull requests

Keep changes small and focused, add tests for changed Proofside behavior, and
avoid unrelated refactoring. Describe any new third-party dependency, why the
standard library was insufficient, and its license implications.

See [`ROADMAP.md`](ROADMAP.md) for suggested contribution directions and which
larger changes should begin with an issue.

Proofside does not currently require a contributor license agreement.
Contributions are made under the project's Apache License 2.0.

