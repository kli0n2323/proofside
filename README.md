# Proofside

Proofside is intended to become a lightweight sidecar for mathematical research
code: a researcher will point it at a typed Python function, review an explicit
mathematical contract, and ask a formal verifier to check the implementation.
This repository currently contains only the Milestone 0 proof of concept; it has
no LLM code, and Nagini/Viper performs the actual verification.

## Run the demonstration

Prerequisites are a 64-bit Python 3.12--3.14 installation and a 64-bit Java 11+
runtime. Nagini normally discovers Java automatically; if it does not, set
`JAVA_HOME` to the Java installation root. From the repository root, create an
isolated environment and install the pinned verifier:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-verification.txt
```

Run the two cases with Nagini's default Silicon backend:

```bash
nagini --verifier silicon examples/shot_budget_good.py
nagini --verifier silicon examples/shot_budget_bad.py
```

The good function allocates a nonnegative remainder to a second bucket and proves
that the two nonnegative allocations sum to the declared nonnegative shot budget.
The bad function differs only by `+ 1`, so it over-allocates one shot. Nagini must
reject its budget-conservation postcondition; this failure is the expected result.

Formal verification establishes that an implementation satisfies a stated
specification under its assumptions. It does not establish that the specification
is scientifically meaningful or that a scientific model corresponds to reality.
This example also does not address integer bounds, runtime callers that violate the
preconditions, variable-length allocations, floating-point behavior, or any future
Proofside workflow.

## Third-party software

| Software | Version | License | Use here |
| --- | --- | --- | --- |
| [Nagini](https://github.com/marcoeilers/nagini) | 1.3.1 | MPL-2.0 | Direct verification dependency |
| [Viper/Silicon](https://github.com/viperproject/silicon) | Bundled by Nagini 1.3.1 | MPL-2.0 | Verification backend used through Nagini |
| [Z3](https://github.com/Z3Prover/z3) | 4.8.7.0, installed transitively | MIT | SMT solver used through Viper |

Proofside depends on these tools; it does not incorporate or adapt their source
code. Python and a Java runtime are execution prerequisites, with licenses supplied
by their respective distributions.

