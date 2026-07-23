# Verification

The mechanics behind every gate a candidate has to pass, and the sandbox
security model underneath all of it. For what the resulting status labels
mean as a *user*, see the "Outcome categories" section in `README.md` — this
is the deep reference for how those results actually get produced.

## Gate order

1. **Syntax gate** (`pipeline/verify/syntax_gate.py`) — hard gate, always
   first: `ast.parse` + `py_compile` against the candidate. Any failure goes
   straight to the repair loop with the exact error and line; nothing below
   this even runs on syntactically broken code.
2. **Behavior gate** — Mode A, B, or C, tried in that priority order per
   file (below).
3. **Determinism gate** (`pipeline/verify/determinism.py`) — runs the
   candidate multiple times (default 3, `determinism_runs`), comparing
   outputs. New variance introduced *only* on the migrated side is a hard
   fail. Pre-existing flakiness already present in the legacy code (e.g.
   unordered dict iteration under Python 2) is reported as
   `PRE_EXISTING_NONDETERMINISM` but doesn't block the migration — it's not
   something ShiftCode introduced, so it's not ShiftCode's job to fix.

## Mode A — has a test suite

`pipeline/verify/behavior_gate.py`'s `run_mode_a`. Runs the *same* existing
test suite via `pytest` (natively discovers both `unittest.TestCase` and
bare-assert pytest-style suites — an earlier `python -m unittest`-based
runner missed pytest-style suites entirely, see `docs/bug-log.md` #5)
against both the original Python 2 code and the migrated Python 3
candidate, and compares per-test outcome via JUnit XML — not raw `stdout`
text, which can differ for reasons that have nothing to do with code
correctness (a builtin exception's message wording changing between
interpreter versions is the confirmed real case that motivated this).

**Two vacuous-pass guards**, both found via real stress tests and both
worth understanding if you touch this function:
- **Zero tests discovered on both sides is not a pass.** An earlier version
  scored this as "outcomes trivially match" — a real, crash-inducing bug
  (the `fix_long` corruption above) reached `VERIFIED` completely undetected
  as a direct result (`docs/bug-log.md` #2).
- **Both interpreters failing test *collection* identically is not a pass
  either** — a different failure shape than zero tests discovered: pytest
  produces one synthetic `ERROR` testcase entry for a collection-level
  failure (e.g. an `ImportError` while loading the test module), which
  "matches" trivially under plain outcome comparison even though no real
  test assertion ever ran on either side. Confirmed real case: `purl`'s
  `from purl import URL` failing identically on both sides because the
  sandbox's layout didn't expose the module under its real package name —
  a sandboxing bug, not a real behavior difference, but it would have
  reported a false `VERIFIED` without this guard (`docs/bug-log.md` #12).

**Test-file migration:** the test file is real py2 source too — running it
unmigrated on the py3 side breaks any test file using a py2-only construct
that's syntactically legal but silently different on py3 (`__metaclass__ =
X` is valid Python 3 syntax but simply does nothing there, instead of
invoking the metaclass — confirmed real case, `docs/bug-log.md` #11). The
test file gets the same mechanical-only `deterministic_transform` the module
under test gets; the py2 side keeps the untouched original, since that's the
ground truth being compared against.

**Dependency closure:** both the module and its paired test file's own real
local imports get resolved and mounted into the sandbox — see
`docs/architecture.md`'s dependency-closure section for the two real gaps
found building this out.

## Mode B — no test suite, but runnable

`run_mode_b`. For files with `if __name__ == "__main__":`, runs the whole
script under both interpreters and diffs stdout/stderr/exit code directly.
No case-count concept here (unlike A/C) — it's a single script execution
compared as one unit, not many independent per-input comparisons.

## Mode C — no test suite, no entry point

`pipeline/verify/characterization_gate.py`'s `run_mode_c`. The common case
for real-world legacy library code with nothing to naturally verify against.
Auto-generates characterization tests instead of requiring a human to have
written them.

**Evidence priority order**, per function, for what inputs to propose:
1. Real call-site usage elsewhere in the ingested codebase (`call_sites.py`,
   static `ast` analysis, literal arguments only) — the strongest signal,
   since it's real observed usage.
2. A docstring, if the function has one.
3. The LLM reading the function's own code and inferring plausible inputs.

The Characterization agent (`docs/agents.md`) proposes candidate inputs from
whichever evidence tier applies; the actual expected behavior always comes
from running the real original code with those inputs — never the model's
guess. `BehaviorResult.evidence_source` records which tier(s) were used
(`"docstring"`, `"call_sites"`, `"llm_inference"`, or a `+`-joined
combination across a file's functions), so a human reviewing a
`VERIFIED_INFERRED` result can see exactly how strong the underlying
evidence was, not just that "something" passed.

### Differential fuzzing (optional)

Off by default (`characterization_fuzz_cases: int = 0` — additive, byte-for-byte
unchanged behavior unless opted into). When enabled, the Characterization
agent proposes a per-parameter **seed pool** (`propose_fuzz_seeds` —
representative literal *values*, not full argument tuples) instead of a
handful of complete examples, and `pipeline/verify/fuzz_generation.py` —
pure, deterministic, zero further LLM cost — expands that pool into up to
the configured budget of concrete cases:

1. A round-robin combinatorial pass over the seed pools (every proposed
   seed value gets used in at least one generated case — nothing silently
   ignored).
2. Type-dispatched boundary mutation to fill any remaining budget (numeric
   nudges, string case/length variants, list/dict empty-or-duplicate
   variants), chained progressively rather than re-mutating the same
   pristine base each cycle — an earlier version re-mutated fresh from the
   original seed every cycle, which for deterministic mutation types
   (list/dict) produced exact-duplicate cases once the budget exceeded the
   pool's natural variety, silently wasting most of a large budget on zero
   additional coverage.
3. All randomization uses a local `random.Random` seeded from the function
   name, never the global `random` module — the whole expansion is a pure
   function of its inputs (same plan + budget → byte-identical output every
   run), which matters for reproducibility of a specific run's failure
   report and for unit-testability.

Same one-LLM-call-per-file cost as the non-fuzzing path regardless of case
count — only sandbox execution time scales with the budget. Every generated
case still runs through the exact same `ast.literal_eval`-only safety gate
as a single hand-picked example (below) — the evidence *volume* changes,
the safety posture doesn't.

**Shrinking analog:** once a mismatch is found, a small fixed number
(`_NEIGHBOR_VARIANT_COUNT`, 3) of boundary-nudged variants of that *first*
failing case are generated and run too — a cheap, non-library analog of
property-based-testing shrinking. Not a provably-minimal repro, but enough
to show whether a failure is boundary-specific or broad. The full case
budget still runs even after a mismatch is found — stopping early would
hide exactly that signal, which the existing all-cases-run design already
preserves.

**Report-cap vs. execution-cap:** `BehaviorResult.failing_tests` (structured)
stays fully uncapped regardless of case count; only the free-text `detail`
string's formatting gets capped (`MAX_REPORTED_MISMATCHES = 10`, plus a
trailing "…and N more mismatch(es)" summary) — a 100-case run with many
failures would otherwise produce an unreadable detail string.

## Sandboxing

`pipeline/verify/sandbox_runtime.py`. Both the original (py2) and candidate
(py3) sides execute inside ephemeral Docker containers: `--rm` (nothing
persists), `--network none`, plus memory/CPU limits
(`sandbox_memory_limit`/`sandbox_cpu_limit`).

**Why `--network none`:** no legitimate reason a correctness check needs
network access — this is the main defense against a bad or malicious input
doing anything outside the sandbox. This matters most for Mode C, since
it's the one mode calling functions with LLM-*guessed* inputs rather than
human-written ones.

**Fallback policy is deliberately asymmetric.** Mode A/B fall back to local
(non-containerized) execution if Docker isn't available — lower marginal
risk, since the inputs there are human-authored (a real test suite, or a
`__main__` block someone wrote). Mode C has **no such fallback** — if it
can't run sandboxed, it doesn't run at all, correctly degrading to
`UNVERIFIED` rather than executing LLM-guessed inputs unsandboxed.

**`ast.literal_eval`-only, never `eval`/`exec`.** The single thing standing
between "the LLM proposed an input" and arbitrary code execution: every test
case's `args_literal` (and every fuzz seed value) is parsed with
`ast.literal_eval` only. This structurally *cannot* evaluate a function
call, attribute access, or name lookup — a manipulated or malicious model
response trying to smuggle `__import__("os").system(...)` through this
field simply fails to parse and is discarded before any driver script is
even built. This is the one invariant every part of Mode C (and its fuzzing
extension) is built around never weakening.

## Evidence-count semantics (`cases_run` / `cases_passed`)

`BehaviorResult` (`models/verify_result.py`) carries real, exact counts —
deliberately *not* a synthesized 0-100 confidence score, which would risk
implying a false precision/comparability across modes that don't actually
measure the same thing:

- **Mode A:** `cases_run` = the real `pytest`-discovered test count;
  `cases_passed` = that minus however many outcome mismatches were found.
  `None` on either vacuous-pass guard above — nothing real ran.
- **Mode C:** `cases_run` = the *true* total executed, including any
  neighbor-variant shrinking probes (not just the originally-proposed case
  count); `cases_passed` accordingly. `None` when there were no valid cases
  to run at all.
- **Mode B:** always `None` — a single script's stdout/stderr/exit-code
  comparison isn't a case count in the sense A/C's per-input comparisons
  are; reporting a fabricated "1/1" would misleadingly imply a countable-cases
  framing Mode B doesn't have.

Rendered in `to_text`/`to_console` as e.g. `206/209 cases passed (Mode A)`
whenever `cases_run` is set, and included in the JSON report's `behavior`
object either way.
