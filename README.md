# Proofside

Proofside is intended to become a lightweight sidecar for mathematical research
code: a researcher points it at a typed Python function, reviews an explicit
mathematical contract, and asks a formal verifier to check the implementation.
This repository currently contains only the Milestone 2 proof of concept.
Nagini/Viper performs the actual verification; no ML or contract generation has
been implemented.

## Install and run

Prerequisites are a 64-bit Python 3.12--3.14 installation and a 64-bit Java 11+
runtime. Create an isolated environment from the repository root:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-verification.txt
```

The sidecar example keeps the research functions free of Nagini annotations and
uses one manually written structured JSON contract for both implementations:

```bash
python -m proofside check examples/shot_budget_plain.py::allocate_remaining --contract examples/shot_budget_contract.json
python -m proofside check examples/shot_budget_plain_bad.py::allocate_remaining --contract examples/shot_budget_contract.json
```

Proofside validates the JSON against the selected function, renders the same
contract for the reader, and deterministically lowers it to Nagini `Requires` and
`Ensures` statements. It verifies a temporary file containing only the selected
function and generated annotations, then removes that file. The original source
is never modified.

The existing handwritten-Nagini mode remains available:

```bash
python -m proofside check examples/shot_budget_good.py::allocate_remaining
```

Proofside reports `VERIFIED` when Nagini/Viper discharges the obligations,
`FAILED` when a proof obligation is not established, `UNSUPPORTED` for a clear
preflight boundary, and `ERROR` for invalid contracts, malformed input,
translation failures, or setup/runtime problems. `FAILED` does not necessarily
mean Nagini produced a concrete counterexample.

## Current boundary

The JSON contract language is deliberately closed. It supports only parameter
references, integer literals, the function result, addition, and comparisons
using `>=`, `<=`, or `==`, collected into separate precondition and postcondition
lists. It contains logical structure, never raw Python or Nagini snippets.

Sidecar extraction currently accepts simple, self-contained, top-level synchronous
functions with complete annotations, no decorators, and no function docstring.
It does not preserve module imports, helpers, comments, closures, or module state.
Handwritten mode continues to require direct `Requires` or `Ensures` calls.

On Windows, set `JAVA_HOME` to the Java installation root if Nagini cannot find
the JVM even though `java` is on `PATH`. Run fast Proofside-owned tests with:

```bash
python -m unittest discover -s tests -v
```

The two slow Nagini integration tests are opt-in with
`PROOFSIDE_RUN_NAGINI=1`.

Formal verification establishes that an implementation satisfies a stated
specification under its assumptions. It does not establish that the specification
is scientifically meaningful or that a scientific model corresponds to reality.

## Third-party software

| Software | Version | License | Use here |
| --- | --- | --- | --- |
| [Nagini](https://github.com/marcoeilers/nagini) | 1.3.1 | MPL-2.0 | Direct verification dependency |
| [Viper/Silicon](https://github.com/viperproject/silicon) | Bundled by Nagini 1.3.1 | MPL-2.0 | Verification backend used through Nagini |
| [Z3](https://github.com/Z3Prover/z3) | 4.8.7.0, installed transitively | MIT | SMT solver used through Viper |

Proofside depends on these tools; it does not incorporate or adapt their source
code. Milestone 2 adds no third-party dependency. Python and a Java runtime are
execution prerequisites, with licenses supplied by their distributions.

