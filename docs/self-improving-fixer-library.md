# Self-improving fixer library

How a confirmed real repair turns into a permanent, deterministic detector —
the full mechanism, the design rationale, and the real evidence behind why
it's built the way it is.

## The problem this solves

When ShiftCode hits a real py2/py3 semantic-drift bug it hasn't seen before
(the `unicodedata.normalize(...).encode(...)` bytes/str trap, a legacy
`types` module import — both real, both in `docs/bug-log.md`), it can only
find it one of two ways: an expensive, unreliable path where a real
characterization/Mode A test has to actually exercise the exact broken
input, fail, and get diagnosed live by the Auditor; or a human notices the
bug by hand and writes a new detector into `analyze.py`. Every bug found the
first way stays a one-off unless a human happens to generalize it — nothing
makes that generalization step less manual on its own.

## The mechanism

### 1. Capture

`--capture-repair-history` (off by default, opt-in, pure additive — zero
behavior change unless enabled). After a real migration run, every file that
reached `VERIFIED`/`VERIFIED_INFERRED` via a **genuinely Auditor-diagnosed**
repair — not just a blind retry that happened to succeed — gets its
before/after source and root-cause hint appended to a local JSONL log
(`pipeline/repair_history.py`'s `qualifying_repair`/`append_repair_history`).
Pure serialization, zero LLM cost either way.

The qualifying bar matters: `qualifying_repair` requires at least one
`RepairAttempt.hint` to be set, meaning a real diagnosed root cause exists —
this is deliberately the same high-signal bar the historical bugs that
motivated this feature (`docs/bug-log.md` #1, #7, #8) all actually meet. A
file that just needed a straightforward Planner-driven fix with zero repair
attempts has no articulable "pattern" to generalize from.

### 2. Draft

`shiftcode suggest-fixer-rules --history .shiftcode/repair_history.jsonl
--out candidate_fixers/` — offline, standalone from `migrate`, never run as
part of a live pipeline. For each captured entry, `FixerRuleAgent`
(`agents/fixer_rule.py`, see `docs/agents.md`) generalizes the one confirmed
repair into a `GeneralizedFixRule`: a precise `trigger_description`/
`fix_description`/`safety_conditions`/`confidence`, plus a
`draft_detector_code` — a starting-point `ast.walk` function body in the
real style of `analyze.py`'s existing hand-written detectors.

Written to a plain `.py` file with a header comment (the rule's own
trigger/fix/safety/confidence, plus the source repair's file path for
traceability) — **never executed automatically anywhere** in the pipeline.
A draft that doesn't even parse still gets written, just loudly flagged
(`"WARNING: draft did not parse, needs manual rewrite"`) rather than
silently dropped — same "never fabricate confidence, be honest about
degraded output" posture the rest of the codebase uses.

### 3. Graduate

A **human process, not new code**. A human reads the candidate like a
normal PR: checks the trigger is precise, the fix is safe, edits the
detector code as needed, writes the same two tests every existing detector
has (`test_analyze.py`'s convention — a `test_find_semantic_findings_detects_*`
and a `test_find_semantic_findings_ignores_unrelated_*` pair), and hand-merges
the function into `analyze.py`, adding one line to `find_semantic_findings`'s
dispatch list. Identical mechanical step to how every hand-written detector
in this project has been added — this mechanism only automates the *first
draft*, not the decision to trust it.

From then on, that bug shape is caught deterministically and instantly on
every future migration — no Docker, no LLM call, no dependency on test
coverage happening to exercise it.

## Why the draft is never auto-applied

A live feasibility test was run against `gemini-3.5-flash-lite` — the model
actually configured in production use here, not a hypothetical stronger
one — before this feature was built at all. Method: feed it 3 real
historical bugs (`docs/bug-log.md` #1, #7, #8) and ask it to generalize each
into a structured rule, then hold out 2 new, never-seen code snippets with
the same underlying bug shape and ask it to *apply* one of its own rules to
each.

**Result:** genuinely precise, well-scoped rule generation — the safety
conditions it wrote caught real edge cases (scope-shadowing for the
identifier-collision bug, "don't apply if the consumer expects bytes" for
the encode/decode trap). But the *application* test caught it improvising
an unauthorized "improvement": asked to apply its own stated rule (`replace
IntType with int`, i.e. `type(n) != int`), it instead rewrote the code to
`isinstance(n, int)` — a real semantic difference (`bool` is an `int`
subclass; the two checks disagree on that input), not the literal
substitution it had just described.

**The conclusion this shaped the design around:** trustworthy for drafting
a candidate rule, not for un-reviewed runtime application. That's not a
"weak model" problem a stronger model necessarily fixes either — the
deeper issue is that literal mechanical substitution shouldn't be
probabilistic re-derivation at all, at any model strength, when it can
instead be deterministic code a human has reviewed once. Step 3 stays a
human gate for exactly this reason, matching how `TransformAuditorAgent`
already works elsewhere in this codebase: an LLM diagnoses/drafts, code (or
human-approved code) acts.

## Validation: this actually happened, not just unit-tested

`docs/bug-log.md` #19 — `_find_builtin_cmp_calls`, catching Python 2's
removed `cmp()` builtin — is the first detector this project gained without
a human writing the `ast.walk` code from scratch. Real repair history was
captured against Python's own removed-`cmp()` shape, drafted by
`FixerRuleAgent`, reviewed and merged by hand, then confirmed firing
correctly through the real pipeline entry point.

The same mechanism was exercised again for real during a later stress-test
round (`docs/bug-log.md` #23, #25, #27 — `inspect.getargspec`, `__cmp__`
definitions, `import pipes`), though those three were hand-written directly
from real stress-test findings rather than drafted via `suggest-fixer-rules`
first — the capture/draft/graduate loop and the "write a detector from a
real confirmed bug" discipline are the same either way; only the entry
point (offline draft vs. live diagnosis) differs.
