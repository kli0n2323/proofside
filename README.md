# Proofside

**State the math. Review the contract. Verify the code.**

Proofside is a small formal-verification sidecar for typed mathematical Python.
Declare the math a function is supposed to implement, review an explicit
contract, then ask Nagini/Viper whether the implementation satisfies it.

Proofside annotations keep equations and plain-language intent beside the code
but separate from the implementation body. An optional model can translate that
declared specification into an untrusted candidate contract without seeing the
body by default. No model is required: contracts may also be authored manually,
and a model never determines whether a proof succeeds.

## Quick start

Proofside supports 64-bit Python 3.12–3.14 and requires a 64-bit Java 11+
runtime. From a checkout:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
```

Start with a reproducible model-free verification:

```bash
proofside check examples/sidecar/shot_budget_plain.py::allocate_remaining \
  --contract examples/sidecar/shot_budget_contract.json
```

The contract assumes nonnegative counts with `first_bucket <= total_shots` and
guarantees a nonnegative result that conserves the declared budget. The command
prints the contract, `VERIFIED`, and an explicit proof boundary.

Now check the nearly identical broken implementation:

```bash
proofside check examples/sidecar/shot_budget_plain_bad.py::allocate_remaining \
  --contract examples/sidecar/shot_budget_contract.json
```

Nagini reports `FAILED` because the extra `+ 1` prevents budget conservation.
Prefixing commands with `python -m proofside` is also supported.

## Examples

| Path | Purpose |
| --- | --- |
| `examples/sidecar/` | Model-free Proofside JSON contract workflow: good and bad implementations share one explicit contract. |
| `examples/nagini/` | Direct handwritten Nagini contracts. Proofside supports this path but does not parse Nagini annotations back into its IR. |
| `examples/annotated/shot_budget_annotated.py` | Smallest annotation-first specification and proposal example. |
| `examples/annotated/model_workflow_stress.py` | Eight-function model-assisted stress fixture with both matching and intentionally mismatched implementations. Its annotations are normative; bodies are withheld by default. |
| `examples/research/` | Research-derived bookkeeping example with careful, limited provenance. |
| `examples/unsupported/` | A source boundary that Proofside explicitly reports as unsupported. |

## Declare the intended math

Proofside recognizes two case-sensitive comments in the contiguous comment
block immediately above a supported function:

```python
# proofside equation: result = total_shots - first_bucket
# proofside intent: Return the unallocated portion of the declared budget.
def allocate_remaining(total_shots: int, first_bucket: int) -> int:
    return total_shots - first_bucket
```

Equation and intent text is opaque, user-authored specification material.
Proofside preserves it rather than interpreting, normalizing, or checking the
mathematics at annotation-extraction time. Multiple equation or intent lines
are allowed.

The specification says what the function is supposed to mean; the implementation
is the object later checked against the accepted contract. They have different
roles.

## From specification to proof

```text
       user-declared specification
      equation / intent / selected sources
                     ↓
          optional model translation
                     ↓
              candidate contract
               NOT VERIFIED
                     ↓
              human review/edit
                     ↓
              accepted contract ─────────┐
               NOT VERIFIED              │
                                         ├→ selected explicit contract
manually authored JSON contract ─────────┘
               NOT VERIFIED
                     +
       implementation under test
                     ↓
       deterministic Proofside lowering
                     ↓
            Nagini / Viper / Z3
                     ↓
     VERIFIED / FAILED / UNSUPPORTED / ERROR
```

Handwritten Nagini contracts provide a lower-level route directly to Nagini.
In every route, Nagini/Viper—not a model—decides whether proof obligations are
discharged.

To ask an explicitly selected model for a candidate:

```bash
proofside propose examples/annotated/shot_budget_annotated.py::allocate_remaining \
  --model-source api \
  --model MODEL_NAME
```

Without `--out`, this writes:

```text
examples/annotated/.proofside/shot_budget_annotated.allocate_remaining.candidate.json
```

The response must be exact JSON. Proofside strictly parses and structurally
validates it, but labels it `PROPOSED — NOT VERIFIED`. Review or edit that file,
then record the explicit choice to submit it for verification:

```bash
proofside accept examples/annotated/shot_budget_annotated.py::allocate_remaining
```

This retains the candidate and creates:

```text
examples/annotated/.proofside/shot_budget_annotated.allocate_remaining.contract.json
```

Acceptance means only “accepted for verification.” It neither asserts that the
contract is correct nor runs the verifier. Verification remains a separate
action:

```bash
proofside check examples/annotated/shot_budget_annotated.py::allocate_remaining \
  --contract examples/annotated/.proofside/shot_budget_annotated.allocate_remaining.contract.json
```

An explicit `--out custom.json` remains available for proposal, and
`accept --candidate custom.json` validates a reviewed custom candidate into the
deterministic accepted path. `accept --replace` is required to replace an
existing accepted contract, and validation completes before replacement.

No model is needed for either contract route. A manually authored JSON contract
may be checked directly with `check --contract`; it does not have to pass through
`accept`. Advanced users may instead keep handwritten Nagini annotations in the
function:

```bash
proofside check examples/nagini/shot_budget_good.py::allocate_remaining
```

Proofside does not parse handwritten Nagini annotations into its contract IR.

## Specification sources

`propose` and `propose-all` accept repeatable `--source` choices:

- `equation` — the function's `proofside equation` lines;
- `intent` — the function's `proofside intent` lines;
- `implementation` — the selected function body, only when explicitly chosen.

With no `--source`, Proofside uses every available annotation type in the fixed
order `equation`, then `intent`. It never silently falls back to the
implementation. An unannotated function therefore requires explicit
`--source implementation`; sources may also be combined.

The function name, parameter names and types, and return annotation remain
structural context. Unless `implementation` is selected, the model does not
receive the body, return expression, neighboring functions, imports, tests, or
other repository content.

## Candidate and accepted artifacts

For `path/module.py::function`, the source-adjacent convention is:

```text
path/.proofside/module.function.candidate.json
    proposed or supplied for review; unaccepted; NOT VERIFIED

path/.proofside/module.function.contract.json
    explicitly accepted for verification; still NOT VERIFIED
```

Both files contain ordinary Proofside contract JSON without approval metadata.
Proposal never overwrites an existing candidate, accepts it, or verifies it.
Acceptance validates before writing, never calls a model or verifier, and leaves
the candidate in place.

## Batch workflow

Batch commands are deterministic orchestration over independent single-function
operations. Only marked top-level functions participate; there is no batch
contract or multi-function proof.

```bash
proofside propose-all examples/annotated/ --model-source api --model MODEL_NAME
```

`propose-all` may make one sequential model request per marked function needing
a candidate. It uses each function's equation/intent annotations by default and
withholds each body unless `--source implementation` is selected. Candidates
are written independently; none is accepted or verified.

Review the candidate files and accept each chosen contract explicitly:

```bash
proofside accept research/budget.py::remaining
```

Then verify all marked functions with accepted source-adjacent contracts:

```bash
proofside check-all research/
```

One file or function failure does not stop later independent operations. Both
batch commands recursively inspect only the supplied files/directories, prune
hidden directories, deduplicate paths, and use deterministic ordering.

The conspicuous bypass below lets `check-all` fall back to a candidate only when
no accepted contract exists:

```bash
proofside check-all research/ --allow-unreviewed
```

Candidate-backed results are labeled `UNREVIEWED CONTRACT`, and the overall
exit remains nonzero even if every underlying proof verifies. An accepted
contract always wins over a candidate.

## What a result means

- `VERIFIED`: Nagini/Viper discharged the displayed proof obligations.
- `FAILED`: one or more obligations were not proved. This does not by itself
  mean that a concrete counterexample was produced.
- `UNSUPPORTED`: Proofside recognized input outside its deliberately narrow
  source or contract boundary.
- `ERROR`: malformed input, missing tooling, or another setup/runtime problem
  prevented meaningful verification.

`UNSUPPORTED` and `ERROR` do not imply that verification occurred.

A successful run establishes that the selected implementation satisfies the
displayed guarantees under the displayed assumptions, within the supported
Nagini/Viper semantics. Preconditions remain obligations on callers.

Formal verification does not establish that the contract captures the intended
mathematics, that a scientific model corresponds to reality, that an algorithm
is useful or optimal, or that an experiment is empirically valid. The researcher
remains responsible for the specification and its scientific meaning.

## Supported boundary

The closed contract language supports:

- arithmetic values: parameters, integer literals, the result in
  postconditions, addition, subtraction, negation, and multiplication by an
  integer constant;
- logical formulas: `==`, `!=`, `<`, `<=`, `>`, `>=`, `and`, `or`, `not`, and
  implication;
- lists of preconditions (`requires`) and postconditions (`ensures`).

This is intentionally close to quantifier-free propositional linear integer
arithmetic. It excludes arbitrary variable-by-variable multiplication,
division, powers, quantifiers, arrays, floating point, and arbitrary Python
expressions.

For example, piecewise intent can be preserved directly:

```text
value >= 0 -> result == value
value < 0  -> result == 0
```

That says more than weakening the function to global bounds such as
`result >= 0`.

It contains no raw Python or Nagini snippets.

Proofside currently selects top-level synchronous functions with complete
parameter and return annotations. Decorated, async, nested, ambiguous, or
untyped targets are rejected. Sidecar mode also rejects function docstrings and
one-line bodies.

The selected function must be self-contained. Sidecar source generation does
not preserve arbitrary imports, helpers, closures, comments, or module state.
Proofside does not provide verification semantics for arbitrary Python, NumPy,
SciPy, or research frameworks.

## Trust and model transport

Proofside strictly parses one closed contract representation, validates names
against the selected function, and lowers accepted JSON deterministically to a
temporary Nagini source. Nagini, Viper/Silicon, and Z3 perform formal
verification. Temporary verifier sources are removed after each run.

Model output and annotation payloads are untrusted input. A model receives only
the selected specification sources plus structural signature context:

- API mode sends that context remotely. The default OpenAI endpoint alone reads
  `OPENAI_API_KEY` implicitly.
- A custom API endpoint must use HTTPS and explicitly name its credential with
  `--api-key-env`; Proofside does not forward `OPENAI_API_KEY` automatically.
- Local mode defaults to `http://localhost:11434/v1` and is unauthenticated.
- Authenticated requests refuse every HTTP redirect so credentials cannot be
  forwarded to a redirect target.

Proofside makes one non-streaming request with a finite timeout and no automatic
retry, repair, or verifier-feedback loop.

## Research example

```bash
proofside check examples/research/research_shot_budget.py::remaining_feature_shots \
  --contract examples/research/research_shot_budget_contract.json
```

This synthetic bookkeeping kernel is inspired by two motifs in the author's
research workflow: finite-shot Pauli feature acquisition and train/test
separation. It is not copied from that implementation and does not represent a
canonical allocation policy. The private research repository is not needed to
understand or run this self-contained example.

The contract proves a nonnegative remainder and conservation of the declared
counts under its assumptions. It does not prove that the split is optimal, that
the acquisition choices are scientifically appropriate, that the method
improves a downstream task, or that a policy transfers to hardware.

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, tests, the code map, and
design constraints. If Nagini cannot find Java—especially on Windows—set
`JAVA_HOME` to the Java installation root.

See [`ROADMAP.md`](ROADMAP.md) for suggested contribution directions.

## Third-party software and license status

| Software | Version | License | Use here |
| --- | --- | --- | --- |
| [Nagini](https://github.com/marcoeilers/nagini) | 1.3.1 | MPL-2.0 | Direct pinned verification dependency |
| [Viper/Silicon](https://github.com/viperproject/silicon) | Bundled by Nagini 1.3.1 | MPL-2.0 | Verification backend used through Nagini |
| [Z3](https://github.com/Z3Prover/z3) | 4.8.7.0 on common x64 platforms | MIT | Solver installed transitively by Nagini |

Proofside depends on these projects but contains no copied or adapted
third-party source. Python and Java are execution prerequisites distributed
under their respective licenses.

Proofside is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).

