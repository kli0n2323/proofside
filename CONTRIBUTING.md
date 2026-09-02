# Contributing to Proofside

Proofside is intentionally small. A focused change should be understandable
without learning a framework or a large internal architecture.

## Development setup

Use 64-bit Python 3.12–3.14 and Java 11 or newer:

```bash
git clone https://github.com/kli0n2323/proofside.git
cd proofside
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
```

If Nagini cannot find Java, set `JAVA_HOME` to the Java installation root.

## Tests

Fast deterministic tests exercise Proofside-owned parsing, inspection,
rendering, classification, proposal, and security behavior. They require no API
credential or running model:

```bash
python -m unittest discover -s tests -v
```

The seven slow integration tests invoke Nagini/Viper. On Linux or macOS:

```bash
PROOFSIDE_RUN_NAGINI=1 python -m unittest tests.test_integration -v
```

On Windows PowerShell:

```powershell
$env:PROOFSIDE_RUN_NAGINI = "1"
python -m unittest tests.test_integration -v
```

Before submitting a change, run the fast suite and any integration test affected
by it. Live model calls are not part of the automated suite.

## Code map

- `proofside/cli.py` — selector/AST inspection, Nagini orchestration, result
  classification, console rendering, and argument parsing.
- `proofside/contracts.py` — the closed contract IR, strict parsing and
  validation, deterministic human/Nagini rendering, and sidecar source creation.
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
- `examples/` — workflow-organized sidecar, handwritten Nagini, annotated,
  research-inspired, and unsupported demonstrations.
- `tests/` — fast Proofside-owned boundaries and opt-in Nagini integrations.

## Design constraints

Please preserve these boundaries:

- Nagini/Viper gets the final word on proof success.
- Declared specification and implementation are distinct; a function body is
  model context only when the user explicitly selects it.
- Model proposal never verifies, accepts, or edits a contract automatically.
- Acceptance records selection for verification but never performs verification.
- Manual sidecars, handwritten Nagini contracts, and optional model proposals
  are all supported paths to the same verifier.
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

Proofside does not currently require a contributor license agreement. The
project license will be selected before public release.

