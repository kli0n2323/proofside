# Proofside

Proofside is a small formal-verification sidecar for typed mathematical Python.
Write a compact explicit contract, then ask Nagini/Viper to check whether one
supported function satisfies it.

No LLM is required. Optional model support can propose an untrusted candidate
contract, but a model never decides whether a proof succeeds.

## Quick start

Proofside supports 64-bit Python 3.12–3.14 and requires a 64-bit Java 11+
runtime. From a checkout:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
```

Verify the good sidecar example:

```bash
proofside check examples/shot_budget_plain.py::allocate_remaining --contract examples/shot_budget_contract.json
```

The output displays the contract and its boundary:

```text
Assumptions
- total_shots >= 0
...

Guarantees
- first_bucket + result == total_shots

VERIFIED
Nagini/Viper discharged the declared proof obligations.

Proof boundary
- The selected implementation satisfies the displayed guarantees under the displayed assumptions, according to Nagini/Viper.
...
```

Now run the nearly identical broken implementation:

```bash
proofside check examples/shot_budget_plain_bad.py::allocate_remaining --contract examples/shot_budget_contract.json
```

Nagini reports `FAILED` because the extra `+ 1` prevents the declared budget
from being conserved. Prefixing these commands with `python -m proofside`
remains supported.

## What a result means

- `VERIFIED`: Nagini/Viper discharged the displayed proof obligations.
- `FAILED`: one or more obligations were not proved. This does not by itself
  mean that a concrete counterexample was produced.
- `UNSUPPORTED`: Proofside recognized input outside its deliberately narrow
  source or contract boundary.
- `ERROR`: malformed input, missing tooling, or another setup/runtime problem
  prevented meaningful verification.

`UNSUPPORTED` and `ERROR` do not imply that verification occurred.

## What the proof establishes

A successful run establishes that the selected implementation satisfies the
displayed guarantees under the displayed assumptions, within the supported
Nagini/Viper semantics.

It does not establish that the contract captures the intended scientific model,
that the model corresponds to reality, that an algorithm is useful or optimal,
or that an experiment is empirically valid. The researcher remains responsible
for the specification and for whether callers satisfy its preconditions.

## Using Proofside without a model

This is the primary workflow. Write a JSON sidecar such as
[`examples/shot_budget_contract.json`](examples/shot_budget_contract.json), then
select the function and contract explicitly:

```bash
proofside check path/to/code.py::function_name --contract path/to/contract.json
```

Proofside strictly parses and validates the sidecar, renders it for review,
lowers it deterministically to Nagini annotations in a temporary source file,
and removes that file after verification. It does not modify the target source.

Advanced users can continue to write Nagini contracts directly:

```bash
proofside check examples/shot_budget_good.py::allocate_remaining
```

Proofside does not parse handwritten Nagini annotations into its contract IR.

## Optional model proposal

`propose` sends user-selected specification context and the supported
contract-format instructions to an explicitly selected model. By default it
uses available annotations immediately above the function:

```python
# proofside equation: result = total_shots - first_bucket
# proofside intent: Return the unallocated portion of the declared budget.
def allocate_remaining(total_shots: int, first_bucket: int) -> int:
    return total_shots - first_bucket
```

The signature remains structural context, but the implementation body is not
sent unless `--source implementation` is explicitly selected. An unannotated
function therefore requires that option. A successful response is strictly
parsed, structurally validated, saved, and labeled `PROPOSED — NOT VERIFIED`.
Without `--out`, the candidate for `path/module.py::function` is written to
`path/.proofside/module.function.candidate.json`:

```bash
proofside propose examples/shot_budget_annotated.py::allocate_remaining \
  --model-source api --model MODEL_NAME
```

Review or edit the candidate, then explicitly accept it for verification. This
creates `path/.proofside/module.function.contract.json` while retaining the
candidate:

```bash
proofside accept examples/shot_budget_annotated.py::allocate_remaining
```

The candidate is unaccepted. Both files remain `NOT VERIFIED`; acceptance
records only the user's choice of specification. Verification remains a
separate command:

```bash
proofside check examples/shot_budget_annotated.py::allocate_remaining \
  --contract examples/.proofside/shot_budget_annotated.allocate_remaining.contract.json
```

An explicit `--out custom.json` remains available for proposal, and
`accept --candidate custom.json` accepts a reviewed custom candidate into the
deterministic `.contract.json` path. Arbitrary manually authored contracts may
still be passed directly to `check --contract`; `accept` is not required for
that workflow. Accepted artifacts are protected from overwrite unless the user
explicitly runs `accept --replace` after supplying a valid candidate. Proposal
and acceptance never invoke Nagini.

- API mode sends only the selected function context remotely. The default
  OpenAI endpoint reads `OPENAI_API_KEY`.
- A custom remote endpoint requires HTTPS and an explicitly named credential,
  for example `--base-url https://provider.example/v1 --api-key-env PROVIDER_API_KEY`.
- Local mode defaults to `http://localhost:11434/v1` and is unauthenticated.
- Authenticated requests do not follow redirects, so bearer credentials cannot
  be forwarded to another endpoint.

Model output remains arbitrary untrusted text until it passes the same strict
parser and validation used for a manually authored sidecar. Exact JSON is
required; Proofside does not repair or coerce a response. No model is needed for
verification.

## Supported contract language

The intentionally small closed language contains:

- parameter variables;
- integer literals;
- the function result in postconditions;
- addition;
- comparisons using `>=`, `<=`, and `==`;
- lists of preconditions (`requires`) and postconditions (`ensures`).

It contains no raw Python or Nagini snippets.

## Supported Python boundary

Proofside currently selects one top-level synchronous function with complete
parameter and return annotations. Decorated, async, nested, or ambiguous targets
are rejected. Sidecar mode also rejects function docstrings and one-line bodies.

The selected function must be self-contained. Sidecar source generation does
not preserve arbitrary imports, helper functions, closures, comments, or module
state. Proofside does not promise verification semantics for arbitrary Python,
NumPy, SciPy, or research frameworks.

## How it works

```text
human-authored contract ─────────────────────────────┐
                                                    │
optional model → untrusted candidate → human review ┤
                                                    ↓
Python function + selected explicit contract
                    ↓
           strict Proofside parser
                    ↓
            closed contract IR
                    ↓
      deterministic Nagini lowering
                    ↓
           Nagini / Viper / Z3
                    ↓
       result + explicit proof boundary
```

Proofside owns parsing, validation, and deterministic lowering. Nagini,
Viper/Silicon, and Z3 perform the formal verification. A model, when used, sits
outside the trusted proof engine.

## Research example

The Ops-inspired demonstration is:

```bash
proofside check examples/ops_shot_budget.py::remaining_feature_shots \
  --contract examples/ops_shot_budget_contract.json
```

`ops_shot_budget` is a synthetic bookkeeping example inspired by two motifs in
the author's Ops research workflow: finite-shot Pauli feature acquisition and
train/test separation. It is not copied from that implementation and does not
represent a canonical Ops allocation policy. The private research repository is
not needed to understand or run this self-contained example.

The contract proves nonnegative remainder and conservation of the declared
counts under its assumptions. It does not prove that the split is optimal, that
the acquisition choices are scientifically appropriate, that Ops improves a
downstream task, or that a policy transfers to hardware.

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development setup, test commands,
code map, and design constraints.

If Nagini cannot find Java—especially on Windows—set `JAVA_HOME` to the Java
installation root before running verification.

## Third-party software and license status

| Software | Version | License | Use here |
| --- | --- | --- | --- |
| [Nagini](https://github.com/marcoeilers/nagini) | 1.3.1 | MPL-2.0 | Direct pinned verification dependency |
| [Viper/Silicon](https://github.com/viperproject/silicon) | Bundled by Nagini 1.3.1 | MPL-2.0 | Verification backend used through Nagini |
| [Z3](https://github.com/Z3Prover/z3) | 4.8.7.0 on common x64 platforms | MIT | Solver installed transitively by Nagini |

Proofside depends on these projects but contains no copied or adapted
third-party source. Python and Java are execution prerequisites distributed
under their respective licenses.

The Proofside project license has deliberately not yet been selected. A license
will be applied before public release.
