# Verification

The mechanics behind every gate a candidate has to pass, and the sandbox
security model underneath all of it. For what the resulting status labels
mean as a *user*, see the "Outcome categories" section in `README.md` — this
is the deep reference for how those results actually get produced.

## The four behavior-gate modes, at a glance

Tried in this priority order per file — the first one that applies wins.
Full mechanics for each below.

| Mode | Applies when | Needs a live py2 runtime? | Case-count semantics |
|---|---|---|---|
| A | A real test suite exists | Yes | `cases_run`/`cases_passed` = real pytest-discovered test count |
| R | Recorded `(args → result)` data exists for this file's functions (Mode R, opt-in) | No — expected output was already captured live | `cases_run`/`cases_passed` = real recorded calls replayed |
| B | No test suite, but has `if __name__ == "__main__":` | Yes | None — single script comparison, not a case count |
| C | No test suite, no entry point (the common case for legacy library code) | Yes | `cases_run`/`cases_passed` = true total executed, including shrinking probes |

## Gate order

1. **Syntax gate** (`pipeline/verify/syntax_gate.py`) — hard gate, always
   first: `ast.parse` + `py_compile` against the candidate. Any failure goes
   straight to the repair loop with the exact error and line; nothing below
   this even runs on syntactically broken code.
2. **Behavior gate** — Mode A, R, B, or C, tried in that priority order per
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

## Mode R — real captured usage data

`pipeline/verify/recording_gate.py`'s `run_mode_r`. A solo-developer-feasible
version of shadow testing: true live shadow mode (duplicate real production
traffic to old and new code paths, compare live) needs hosted infrastructure
sitting inside someone else's production traffic path — real ops burden,
real security/liability/privacy exposure, not feasible for a solo-maintained
tool. The record/replay version instead: the user adds `shiftcode.record`'s
`@record` decorator to their *own* Python 2 code in their *own* environment
(dev, staging, or production — their infrastructure, their call), capturing
real `(args → result)` pairs during normal use, then replays those exact
real inputs against the migrated candidate later, entirely offline.

**The key structural difference from every other mode: no `py2_runtime` is
needed at all.** Since the expected output was already captured live, once,
for real, this mode only ever executes the py3 *candidate* and compares it
against the pre-recorded ground truth — a genuinely new capability, since
every other mode requires a live py2 interpreter to be available.

Reuses `characterization_gate.py`'s driver-script/comparison machinery
directly (`_run_case_in`, `_values_equal`, `_module_dotted_name` — imported,
not duplicated) via a throwaway `TestCase` wrapper around each
`RecordedCase`; the execution/comparison mechanics are identical to Mode C,
only where the "expected" side comes from differs.

**The recorder itself** (`src/shiftcode/record/recorder.py`, copied
verbatim into a user's project via `shiftcode init-recorder`) is
deliberately stdlib-only and zero-dependency on the `shiftcode` package,
since it runs *inside the user's own Python 2 process* — confirmed to
actually compile and run under real Python 2 (not just written to look
compatible). Never lets recording break the function it wraps: the real
call always happens and its real result/exception is always
returned/raised regardless of whether recording succeeds; a
non-JSON-serializable arg/result is silently skipped, not an error. Bounded
per function (`max_entries`, default 200) — stops recording once the cap is
hit rather than growing forever in a long-running process.

**A real UX nuance found while validating this end-to-end:** applying
`@record` directly to a function *inside* the module being migrated means
the migrated candidate would carry a `from shiftcode_record import record`
import the verification sandbox doesn't have - a real `ImportError` at
verify time. The validated, recommended pattern instead wraps at the call
site from a separate recording harness (`add = record(calc.add)`), leaving
the module being migrated untouched:

```python
# record_harness.py - NOT part of the module being migrated
import calc
from shiftcode_record import record

add = record(calc.add)
add(2, 3)  # a real call, captured
```

**Loading + safety** (`pipeline/verify/recording_loader.py`'s
`load_recordings`): a recording file is an external input — possibly
produced on an entirely different machine, at an earlier time — so it gets
the exact same zero-trust posture as LLM output, not a lesser one. Every
`args`/`result` gets converted to a literal string and validated through
the same `ast.literal_eval`-only gate (`fuzz_generation.py`'s
`validate_args_literal`/`validate_seed_literal`, reused directly) everything
else in this codebase uses. `function_name` is additionally validated
against a plain identifier pattern before it's ever allowed near a driver
script — recordings are a new *class* of untrusted input this codebase
didn't have before (an LLM's response is at least schema-constrained by the
provider; a JSONL file on disk isn't), so this path doesn't inherit the
(undefended) assumption the existing `TestCase.function_name` path makes
that a function name is always safe by construction. Unsafe/malformed
entries are dropped individually, never failing the whole recording file.
v1 scope is positional-only, matching `TestCase.args_literal`'s own
contract — a recorded call that used keyword arguments is dropped, not
guessed at, since no established literal representation for kwargs exists
anywhere else in this codebase yet.

**Where Mode R sits in the priority chain:** Mode A → Mode R → Mode B →
Mode C. Real per-function recorded data, when available, is likely broader
evidence than a single `__main__` script's stdout diff (Mode B) or an
LLM-guessed/fuzzed characterization case (Mode C) — checked right after the
human test-suite tier.

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

### Class-method characterization

Originally MVP-scoped to top-level functions only — `top_level_function_defs`
structurally excludes classes, since characterizing a method needs an
instance to call it on, not just a call. `top_level_class_defs`/`class_init`/
`public_methods` (`pipeline/call_sites.py`) extend discovery to public
classes, their `__init__` (if any), and their public (non-underscore, so
dunders too — including `__call__` — are excluded by the same rule as
functions) methods. `TestCase` carries this as two additional optional
fields, `class_name`/`constructor_args_literal` (`None` for a plain function
case — byte-for-byte the same behavior as before this existed): when set,
`_build_driver_script` constructs `ClassName(*constructor_args)` first, then
calls the method on that instance, instead of calling a module-level
function directly. The same evidence-priority order and `ast.literal_eval`-only
safety gate apply to constructor args exactly as they do to any other
argument.

Differential fuzzing (below) stays function-only for now — methods always go
through the plain (non-fuzzed) example-proposal path regardless of
`characterization_fuzz_cases`, a deliberate scope cut, not an oversight.

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

| Mode | `cases_run` | `None` when |
|---|---|---|
| A | Real `pytest`-discovered test count; `cases_passed` = that minus however many outcome mismatches were found | Either vacuous-pass guard above fires — nothing real ran |
| R | Number of real recorded calls replayed; `cases_passed` accordingly | No recordings matched this file's functions at all |
| C | The *true* total executed, including any neighbor-variant shrinking probes (not just the originally-proposed case count); `cases_passed` accordingly | No valid cases to run at all |
| B | Always `None` | Always — a single script's stdout/stderr/exit-code comparison isn't a case count in the sense A/C's per-input comparisons are; a fabricated "1/1" would misleadingly imply a countable-cases framing Mode B doesn't have |

Rendered in `to_text`/`to_console` as e.g. `206/209 cases passed (Mode A)`
whenever `cases_run` is set, and included in the JSON report's `behavior`
object either way.
