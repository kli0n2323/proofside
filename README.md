# Proofside

Proofside is a small formal-verification tool for typed mathematical Python. A
researcher can write an explicit structured sidecar contract and ask Proofside to
check a selected function without using any model. Nagini/Viper performs the
actual verification; Proofside provides the strict contract boundary,
deterministic lowering, result classification, and console explanation.

Milestone 4 adds an optional command that asks an explicitly selected API or
local model to propose an untrusted candidate contract. It never verifies or
accepts the proposal automatically.

## Install and run

Prerequisites are a 64-bit Python 3.12--3.14 installation and a 64-bit Java 11+
runtime. From the repository root:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-verification.txt
```

Verify the original sidecar examples:

```bash
python -m proofside check examples/shot_budget_plain.py::allocate_remaining --contract examples/shot_budget_contract.json
python -m proofside check examples/shot_budget_plain_bad.py::allocate_remaining --contract examples/shot_budget_contract.json
```

Optionally propose a candidate using an API endpoint:

```bash
# Sends only the selected function and contract-format instructions remotely.
# OPENAI_API_KEY is read from the environment.
python -m proofside propose examples/shot_budget_plain.py::allocate_remaining --model-source api --model MODEL_NAME --out candidate_contract.json
```

Or use a local OpenAI-compatible endpoint, defaulting to Ollama at
`http://localhost:11434/v1`:

```bash
python -m proofside propose examples/shot_budget_plain.py::allocate_remaining --model-source local --model MODEL_NAME --out candidate_contract.json
```

Use `--base-url` to override either endpoint. `propose` sends only the selected
function source, its signature, and the supported contract-format instructions.
The model response is untrusted: it must pass the same strict parser and
structural validator as a manual sidecar. A successful proposal is labeled
`NOT VERIFIED`, saved only after validation, and never sent to Nagini. Review or
edit it, then run a separate explicit `proofside check ... --contract ...` if you
choose to submit it for verification. Existing files are not overwritten.

The advanced, low-level handwritten-Nagini path remains available:

```bash
python -m proofside check examples/shot_budget_good.py::allocate_remaining
```

Proofside reports `VERIFIED` when Nagini/Viper discharges the obligations,
`FAILED` when one or more obligations are not established, `UNSUPPORTED` for a
clear preflight boundary, and `ERROR` when verification could not meaningfully
run. `FAILED` does not by itself mean that a concrete counterexample was
produced. Structured-contract runs also print a concise proof boundary; errors
and unsupported inputs do not print language implying that verification
occurred.

## Trust model

```text
research Python + human-authored sidecar contract
                         |
                         v
                 strict Proofside parser
                         |
                         v
                  closed contract IR
                         |
                         v
             deterministic Nagini lowering
                         |
                         v
                 Nagini / Viper / Z3
                         |
                         v
          result + explicit proof boundary
```

Proofside parses and lowers the displayed contract deterministically. Nagini,
Viper/Silicon, and Z3 establish whether the supported implementation satisfies
that formal contract. The researcher remains responsible for deciding whether
the assumptions and guarantees express the intended mathematical or scientific
claim, and whether callers satisfy the assumptions.

The contract IR remains deliberately closed: parameter variables, integer
literals, the function result, addition, and comparisons using `>=`, `<=`, or
`==`, grouped into preconditions and postconditions. It contains no raw Python or
Nagini snippets.

## Ops finite-shot example

The research-derived demonstration is:

```bash
python -m proofside check examples/ops_shot_budget.py::remaining_feature_shots --contract examples/ops_shot_budget_contract.json
```

Its context is the private Ops research repository
`kli0n2323/qml-opsreps-toybox`, inspected at commit
`b239855fb976343dc4a200ed271cd75445d2778e`. In
`opsreps/core/dataset.py`, `estimate_pauli_expval_shots`,
`compute_pauli_expectations_shots`, and `featurize_dataset_shot_paulis` use a
finite number of shots to estimate Pauli features. `opsreps/core/splits.py` then
provides the workflow's train/test split.

Proofside's example is a deliberately reduced bookkeeping kernel modeled on
those finite-shot feature and train/test workflows. It is not copied from the
Ops repository, is not its canonical implementation, and does not reproduce its
acquisition policy. The contract assumes nonnegative total, training-feature,
and test-feature shot counts and that the two allocations fit within the total.
It proves that the returned remainder is nonnegative and that the two allocations
plus the remainder conserve the declared total.

That bookkeeping proof does not establish that the allocation is optimal, that
the Pauli features or acquisition choices are scientifically appropriate, that
Ops improves a downstream task, or that the policy transfers to hardware.

## Current boundary

Sidecar extraction accepts simple, self-contained, top-level synchronous
functions with complete annotations, no decorators, and no function docstring.
It does not preserve module imports, helpers, comments, closures, or module
state. Handwritten mode requires direct `Requires` or `Ensures` calls; Proofside
does not parse those annotations back into its IR.

On Windows, set `JAVA_HOME` to the Java installation root if Nagini cannot find
the JVM even though `java` is on `PATH`. Run fast Proofside-owned tests with:

```bash
python -m unittest discover -s tests -v
```

The four slow Nagini integration tests are opt-in with
`PROOFSIDE_RUN_NAGINI=1`.

Formal verification establishes that an implementation satisfies a stated
specification under its assumptions. It does not establish that the specification
is scientifically meaningful or that a scientific model corresponds to reality.

Model use is never required for verification. Model proposals do not change the
explicit, human-reviewable IR or the deterministic verifier path.

## Third-party software

| Software | Version | License | Use here |
| --- | --- | --- | --- |
| [Nagini](https://github.com/marcoeilers/nagini) | 1.3.1 | MPL-2.0 | Direct verification dependency |
| [Viper/Silicon](https://github.com/viperproject/silicon) | Bundled by Nagini 1.3.1 | MPL-2.0 | Verification backend used through Nagini |
| [Z3](https://github.com/Z3Prover/z3) | 4.8.7.0, installed transitively | MIT | SMT solver used through Viper |

Proofside depends on these tools; it does not incorporate or adapt their source
code. Milestone 3 adds no dependency. Python and a Java runtime are execution
prerequisites, with licenses supplied by their distributions. A Proofside project
license has not yet been selected.
