# Proofside

Proofside is intended to become a lightweight sidecar for mathematical research
code: a researcher points it at a typed Python function, reviews an explicit
mathematical contract, and asks a formal verifier to check the implementation.
This repository currently contains only the Milestone 1 command-line proof of
concept. Contracts are still written manually, and Nagini/Viper performs the
actual verification; contract generation comes later.

## Install and run

Prerequisites are a 64-bit Python 3.12--3.14 installation and a 64-bit Java 11+
runtime. Create an isolated environment from the repository root:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-verification.txt
```

Run Proofside from the repository root:

```bash
python -m proofside check examples/shot_budget_good.py::allocate_remaining
python -m proofside check examples/shot_budget_bad.py::allocate_remaining
```

The good function returns the nonnegative remainder of a two-bucket shot budget
and proves that both allocations conserve the declared total. The bad function
differs only by `+ 1`, so Nagini rejects its conservation postcondition.

Proofside reports one of four states:

- `VERIFIED`: Nagini/Viper discharged the declared proof obligations.
- `FAILED`: Nagini ran, but at least one proof obligation was not established.
  This does not necessarily mean Nagini produced a concrete counterexample.
- `UNSUPPORTED`: the target is clearly outside this milestone's narrow workflow.
- `ERROR`: malformed input or a setup, translation, filesystem, or subprocess
  problem prevented a meaningful proof run.

The current selector accepts one top-level synchronous function with complete
parameter and return annotations, no decorators, and at least one direct
`Requires` or `Ensures` call. Proofside parses the file with the standard-library
AST without importing or executing it, then asks Nagini's Silicon backend to
verify only the named function. Deeper Python and contract compatibility remain
Nagini's responsibility.

On Windows, set `JAVA_HOME` to the Java installation root if Nagini cannot find
the JVM even though `java` is on `PATH`. Run the fast Proofside-owned tests with:

```bash
python -m unittest discover -s tests -v
```

Formal verification establishes that an implementation satisfies a stated
specification under its assumptions. It does not establish that the specification
is scientifically meaningful or that a scientific model corresponds to reality.
This milestone also does not address runtime callers that violate preconditions,
variable-length allocations, floating-point behavior, or contract generation.

## Third-party software

| Software | Version | License | Use here |
| --- | --- | --- | --- |
| [Nagini](https://github.com/marcoeilers/nagini) | 1.3.1 | MPL-2.0 | Direct verification dependency |
| [Viper/Silicon](https://github.com/viperproject/silicon) | Bundled by Nagini 1.3.1 | MPL-2.0 | Verification backend used through Nagini |
| [Z3](https://github.com/Z3Prover/z3) | 4.8.7.0, installed transitively | MIT | SMT solver used through Viper |

Proofside depends on these tools; it does not incorporate or adapt their source
code. The CLI and tests add no third-party dependency. Python and a Java runtime
are execution prerequisites, with licenses supplied by their distributions.

