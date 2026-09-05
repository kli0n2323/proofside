# Proofside roadmap and suggested contributions

Proofside is intentionally small. This roadmap describes useful directions,
not promises or a mandate to expand the tool. Concrete contributions should
normally begin with a GitHub issue so scope and proof/trust semantics can be
agreed before implementation.

## Good contribution directions

### Documentation and examples

Useful work includes clearer newcomer documentation, additional small and
self-contained mathematical or research examples, and platform-specific setup
findings. Examples should exercise the existing supported contract language
where possible and must not contain private or proprietary research code.

### Diagnostics and usability

Possible improvements include clearer verifier and setup diagnostics, small CLI
ergonomics changes grounded in actual user friction, and better links from
verifier diagnostics to user-visible contracts or source where this can be done
without misrepresenting Lean. The distinction among `VERIFIED`, `FAILED`,
`UNSUPPORTED`, and `ERROR` must remain explicit.

### Portability and testing

Useful work includes exercising supported Python, Lean, and platform
combinations; reproducing and documenting Lean environment issues;
focused regression and integration coverage; and packaging improvements that
do not enlarge the trusted core.

### Supported source boundary

Concrete use cases may justify careful support for currently unsupported source
forms, such as selected imports needed by a self-contained target or constrained
helper-function handling. Discuss these changes before implementation because
source preservation changes the verification boundary.

### Contract language extensions

The current deliberate boundary is roughly quantifier-free propositional linear
integer arithmetic. New contract constructs should be motivated by concrete
current use cases while preserving the closed structured IR, strict parsing,
deterministic human rendering, deterministic Lean lowering, and human
inspectability. This roadmap does not promise particular new syntax.

### Floating-point analysis

Rigorous floating-point and roundoff analysis is a significant post-0.1
exploratory direction. Systems such as FPTaylor or Daisy may be worth
investigating; they are not selected backends or dependencies. Work in this
area requires careful decisions about IEEE-754 semantics, input ranges,
NaN/infinity, overflow/underflow, supported expression subsets, and how
numerical-error results differ from functional verification. Substantial
implementation should start with an issue and design discussion.

### Performance

Repeated Lean verifier startup has a measurable cost. Contributors may help
measure it and investigate safe improvements. Proofside does not prescribe a
daemon, service, plugin layer, persistent Lean process, or other architecture without
evidence that it is needed.

## Maintainer-led areas

The maintainer currently intends to lead changes to model-assisted
specification-to-contract translation, including the translation strategy,
proposal-prompt semantics, specification-firewall behavior, model-context
selection, and any verifier-feedback or repair-loop design. Bug reports,
evaluations, adversarial examples, and design feedback are welcome; large
translator changes should not begin as unsolicited pull requests.

Changes to Proofside's fundamental trust or security architecture should also
start with an issue before implementation.

## Issues and claiming work

`ROADMAP.md` describes directions. GitHub Issues are the source of truth for
concrete, scoped work.

If you want to implement a roadmap item that does not yet have an issue, open
one first. This is especially important for changes to contract semantics,
source handling, model behavior, verifier integration, dependencies, or
security boundaries. Small documentation fixes and obvious test improvements
do not need extensive design discussion.

## Non-goals

Proofside is not currently trying to become a general Python verifier, a
framework or plugin ecosystem, a multi-backend abstraction layer, or a web
platform. Formal verification against an explicit contract must never be
presented as automatic evidence that code or its underlying model is
scientifically correct.
