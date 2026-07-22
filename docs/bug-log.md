# Bug log

Real bugs found in ShiftCode itself, mostly via stress-testing against real
external code (not the bundled fixtures) — the whole point of stress testing
is to find the class of bug that a hand-built fixture won't surface. Each
entry: what was wrong, how it was found, the root cause, and what now catches
this class of bug going forward (a code fix, a new gate, or a new agent).

Format: newest first.

---

## 8. `unicodedata.normalize(...).encode(...)` silently becomes `bytes` in Python 3, breaking every later string operation

**Found via:** re-running `python-slugify` and `jpvanhal/inflection` after
bug #5's fix unblocked them - both landed on a genuine `TypeError` in Mode C
(`slugify.py`'s `slugify()`) and Mode A (`inflection.py`'s `transliterate()`,
via the test suite Mode A could finally actually run). Two independent real
libraries hitting the identical line shape (`unicodedata.normalize('NFKD',
text).encode('ascii', 'ignore')`) in the same session was a strong enough
signal to design a fix immediately rather than file it as a maybe.

**Root cause:** in Python 2, `.encode('ascii', 'ignore')` on a normalized
string returns `str`. In Python 3 it always returns `bytes`, regardless of
input type - a real, silent behavior change, not a syntax difference, so
lib2to3 has no fixer for it (correctly out of its scope) and ShiftCode's own
semantic-findings scanner had no detection for it either (MVP only covered
ambiguous division). The resulting bytes value then gets passed to `re.sub`
with a `str` pattern, or `.lower()`-chained into more string ops, and Python
3 raises `TypeError: cannot use a string pattern on a bytes-like object` (or
similar) the first time that happens - reproduced directly in both cases,
not guessed.

**Fix:** `analyze.py`'s `find_semantic_findings` gained
`_find_normalize_encode_chains`, matching the specific `X.normalize(...).encode(...)`
call shape (not every `.encode()` call in general - scoped to exactly what's
been confirmed to actually break, consistent with not fabricating confidence
about a broader pattern that hasn't been observed). Flags as a `needs_llm`
finding with a detail explaining the bytes/str split and the fix (decode
immediately after encoding), routing it into the normal Planner ->
Refactorer <-> Auditor loop like any other finding.

**Status:** fixed and confirmed live against both real libraries that found
it, after the LLM provider's quota reset. `python-slugify`'s `__init__.py`
now reaches `VERIFIED_INFERRED` - all 5 auto-generated characterization
tests pass on both interpreters (Mode C). `inflection.py` now reaches plain
`VERIFIED` - its real parametrized pytest suite passes on both interpreters
(Mode A). Both runs used `gemini-3.5-flash-lite` (switched from
`gemini-3.5-flash` for cost), confirming the fix isn't dependent on the
larger model. This closes the loop opened by bug #5's fix: `docopt` reaches
`VERIFIED`, `inflection` reaches `VERIFIED`, `python-slugify` reaches
`VERIFIED_INFERRED` - all three original stress-test libraries now fully
resolved with no open blockers.

---

## 7. `from types import X` (bare legacy type name) has no Python 3 equivalent and produces zero findings, so it's never fixed

**Found via:** re-running `python-slugify` after bug #5's fix unblocked it.
`__init__.py` had `from types import UnicodeType` and `type(text) !=
UnicodeType`; every characterization test call returned an empty result on
the Python 3 side, even trivial ones like `slugify("Hello World!")` -
reproduced directly against the real `shiftcode-py3-sandbox` container:
`ImportError: cannot import name 'UnicodeType' from 'types'`. The whole
module failed to import, so *every* test case looked like a mismatch, which
obscured the actual single-line cause.

**Root cause:** lib2to3's vendored `fix_types.py` (real upstream CPython
code) only matches the `types.X` attribute-access form
(`power< 'types' trailer< '.' name='UnicodeType' > >`) - it has no pattern
for a bare name introduced via `from types import UnicodeType`, and by its
own documented design it never touches the import statement either ("The
import statements are not modified"). ShiftCode's semantic-findings scanner
also had no check for this. Net effect: this construct produced *zero*
findings of any kind, which routed the file into the zero-`needs_llm`
fast path (`plan.steps = []`) - the exact scenario bug #6 already flagged as
getting no repair attempts at all, compounding the problem.

**Fix:** `analyze.py`'s `find_semantic_findings` gained
`_find_legacy_types_from_imports`, which reuses `fix_types.py`'s own
`_TYPE_MAPPING` dict (so "what's the Python 3 equivalent" stays defined in
exactly one place) to detect `from types import X` for any `X` in that
mapping, and emits a `needs_llm` finding naming the exact replacement.

**Status:** fixed and confirmed via live re-run against the same file that
found it - `__init__.py` no longer crashes on import; the Refactorer
correctly removed the `from types import UnicodeType` import and rewrote
`type(text) != UnicodeType` to `type(text) != str`. That specific bug is
gone; the file now surfaces a different, real, remaining issue (bug #8).

---

## 6. Files with zero `needs_llm` findings get zero repair attempts, even on a real verification failure

**Found via:** stress test against `jpvanhal/inflection` — `inflection.py`
had zero `needs_llm` findings (the Planner never ran, and `TransformAuditor`
found nothing suspicious either), so `migrate_file`'s "no plan steps" fast
path (`pipeline/repair.py`) ran verification exactly once and went straight
to `NEEDS_REVIEW` on failure - no Auditor diagnosis, no retry, regardless of
whether the failure was something a code change could have fixed.

**Root cause:** the fast path exists because a file with an empty plan has
nothing for the Refactorer to act on *initially* - but it doesn't account
for a *verification* failure discovered only after the fact (which the
Auditor might have been able to diagnose and hand back a concrete fix for,
same as it does for files that did have findings).

**Why this one didn't matter in practice (this time):** the actual failure
was bug #5 (missing sandbox dependency) - not fixable by any code change, so
extra retries wouldn't have helped here regardless. But the asymmetry is
real: a file with *some* findings gets up to 3 attempts and an Auditor
diagnosis on any failure type; a file with *zero* findings gets exactly one
shot, even for a failure category that might genuinely be fixable.

**Status:** found, not yet fixed - lower priority than #5 (which is the
actual blocker on 2 of 3 external stress tests so far). Worth revisiting
once #5 lands and this path gets exercised on files where the failure
*isn't* an unfixable environment issue.

---

## 5. Sandbox images have no dependencies installed - blocks most real code

**Found via:** stress test against `python-slugify` (missing `unidecode`) and
`jpvanhal/inflection` (missing `pytest` itself) — same root cause, confirmed
twice independently on two different real libraries via two different
missing packages.

**Symptom:** `slugify.py` does `from unidecode import unidecode` (a real
runtime dependency) — fails to import under both sandboxed interpreters,
since our bare `python:2.7`/`python:3-slim` images have nothing pip-installed
beyond the stdlib. `inflection`'s `test_inflection.py` does `import pytest`
(standard for any pytest-style test file) — same failure, reproduced directly
against the real sandbox: `ModuleNotFoundError: No module named 'pytest'`,
wrapped by Python 3's unittest loader as a graceful `_FailedTest ... ERROR`
(Python 2.7's loader crashes ungracefully instead - see the "known gap" note
on bug #2).

**Root cause, and why it's one fix, not two:** the sandbox images are bare
interpreters with nothing else installed. This blocks two things that looked
like separate gaps but are the same underlying problem: (a) a project's own
declared dependencies aren't available, so any file that imports one can
never be verified, and (b) `pytest` itself isn't available, so even
attempting to run pytest-style test suites (a very common real-world
convention - confirmed to matter on 2 of the first 3 external stress tests)
is blocked before it can even start. "Add pytest-style test support" and
"install project dependencies into the sandbox" turn out to require the same
infrastructure change.

**Status:** fixed and confirmed against both real cases that found it. Three
parts implemented: (1) custom `shiftcode-py2-sandbox`/`shiftcode-py3-sandbox`
Docker images (`docker/*.Dockerfile`) with `pytest` baked in at build time,
auto-built on first use; (2) `pipeline/verify/dependency_provisioning.py` — a
separate, constrained, network-enabled container that does nothing but `pip
install --target <volume> -r requirements.txt` against the project's own
declared packages, mounted read-only into every execution container
afterward with `--network none` fully intact (confirmed: `unidecode`
importable inside the sandbox, and that same container still has zero DNS
resolution); (3) Mode A switched from stdlib `unittest` to `pytest` with
JUnit XML output (`SandboxRuntime.run_pytest`, `_parse_junit_xml` in
`behavior_gate.py`), closing bug #2's remaining gap and bug #4's diagnostic-
clarity issue as a side effect, exactly as predicted below.
Re-ran both original blocking cases after rebuilding the images:
`python-slugify`'s `__init__.py` now shows `unidecode` actually installing
("py2 sandbox: installed Unidecode; py3 sandbox: installed Unidecode") and
importing correctly - the file now gets real characterization-test results
instead of an import crash. `inflection.py` now actually runs its real
pytest-style parametrized test suite inside the sandbox and reports genuine
per-test outcomes instead of failing before a single test could run.
`docopt.py` (bug #1's original test file, previously stuck at `NEEDS_REVIEW`
purely because Mode A couldn't discover its pytest-style tests) now reaches
real `VERIFIED` - Mode A discovered and matched all 3 tests on both
interpreters, confirming the pytest switch closes that specific,
previously-known gap.

---

## 4. Diagnostic clarity: Mode A can't distinguish "outcomes differ" from "one side never produced parseable output at all"

**Found via:** stress test against `python-slugify` and `jpvanhal/inflection`,
both showing a confusing `py2=? py3=ERROR`-shaped failure message.

**Symptom:** when Python 2.7's `unittest` crashes ungracefully on an import
error (raw traceback, not the `_FailedTest ... ERROR` format Python 3 uses),
`_parse_unittest_output` finds zero regex matches and that side's outcomes
dict ends up empty - correctly *not* triggering the bug-#2 vacuous-pass path
(since the other side is non-empty), but producing a `py2=?` in the mismatch
detail that doesn't explain *why* nothing was found. Not a false pass (the
gate correctly reports `FAIL`), just an unhelpful message.

**Root cause:** same regex-based, `unittest`-specific parsing this session
already found two real bugs in. It's suited to the "both sides produced
comparable output" case; it doesn't have a way to say "this side produced no
parseable output at all," so `?` is the most honest single-character summary
it can produce.

**Status:** found, not fixed as its own patch - subsumed by bug #5's design
(switching to `pytest` + structured JUnit XML output is expected to resolve
this as a side effect, not require its own separate fix).

---

## 3. Transient network/API errors crash the entire run, not just one file

**Found via:** stress test against `python-slugify` (real library, pre-py3-support
commit, see `docs/stress-test-log.md`).

**Symptom:** a genuine transient network timeout (`openai.APITimeoutError`)
during the Auditor's `call_structured` call propagated all the way up as an
unhandled `LLMTimeoutError` and killed the entire `shiftcode migrate`
process. Not "this file failed" — the whole run died, no report written, all
progress on every already-processed file lost.

**Root cause:** `call_structured` (`agents/base.py`) only retries on
`LLMOutputError` (malformed JSON after a successful response). Transient
network failures are a different exception class entirely
(`LLMTimeoutError`/`LLMConnectionError`/`LLMRateLimitError` in
`llm/errors.py`), and nothing catches them anywhere in the repair loop or
orchestrator. This isn't a contrived edge case — it's normal real-world
network behavior that will hit any long-enough real run eventually.

**Why it's more fundamental than #1/#2:** those were correctness bugs in
specific files. This one threatens the reliability of *every* run — a single
transient blip on file 3 of 50 currently loses the results for files 1 and 2
as well, not just file 3.

**Fix, two parts:**
1. `call_structured` (`agents/base.py`) now catches `LLMTimeoutError`,
   `LLMConnectionError`, and `LLMRateLimitError` as a separate transient-retry
   budget (default 3 attempts, linear backoff), independent of the existing
   malformed-output retry budget. `LLMAuthenticationError` is deliberately
   *not* retried — a bad API key fails identically on every call, so retrying
   just wastes time; it propagates immediately. After exhausting transient
   retries, raises the same `AgentOutputError` every call site already
   catches (message says which budget was exhausted), rather than letting the
   raw `LLMTimeoutError` escape uncaught.
2. `run_migration`'s per-file loop (`pipeline/orchestrator.py`) now wraps
   `_process_file` in its own try/except: `LLMAuthenticationError` still
   propagates and stops the whole run immediately (a config problem, not a
   per-file one — every remaining file would fail identically, so grinding
   through them is pointless); any other unexpected exception degrades that
   one file to `NEEDS_REVIEW` and the loop continues, so a single file's
   surprise never costs every other file's results. This is the backstop for
   *any* unforeseen failure, not just LLM-related ones — agent calls already
   degrade gracefully via `AgentOutputError` from part 1.

Also fixed the mislabeled error strings this touched (`"planner output
unparseable"`, `REFACTORER_OUTPUT_ERROR`, `AUDITOR_OUTPUT_ERROR`) — those
presumed the cause was always malformed output, which is no longer true now
that the same exception also covers exhausted network retries.

**Status:** fixed. Tests:
`tests/unit/test_call_structured_resilience.py` (retry/backoff behavior,
auth errors not retried),
`tests/unit/test_orchestrator_resilience.py` (one file's unexpected failure
doesn't take down the batch). Not yet re-run against the real
`python-slugify` stress test that found this — see `docs/stress-test-log.md`.

---

## 2. Mode A vacuous pass on zero discovered tests

**Found via:** stress test against `docopt` (real library, pre-py3-support
commit, see below).

**Symptom:** `run_mode_a` (`pipeline/verify/behavior_gate.py`) ran
`python -m unittest -v <test_module>` under both interpreters, parsed
per-test outcomes from stderr, and compared them. `test_docopt.py` uses bare
pytest-style `assert` functions, not `unittest.TestCase` subclasses —
`python -m unittest` silently discovers **zero tests** for a file like this.
Both `stdout` streams were empty (trivially equal), the outcome-mismatch set
was empty (nothing to disagree about) — the gate reported
`PASS: "all tests match, stdout identical"` despite literally nothing having
executed on either side.

**Why it matters:** this is exactly the gate that should have caught bug #1
below (`test_docopt.py`'s real assertions exercise the corrupted code path).
Because it silently no-op'd instead of failing loudly, a genuinely
broken migration reached `VERIFIED`.

**Root cause:** an empty comparison (`{} == {}`) is not the same claim as "we
verified these are equivalent" — the code conflated "nothing to disagree
about" with "confirmed to agree."

**Fix:** `run_mode_a` now checks for this case explicitly — if both
`py2_outcomes` and `py3_outcomes` are empty, return `UNVERIFIED` with a
message naming the likely cause (pytest-style test file, not
`unittest.TestCase`-discoverable), instead of falling through to the
stdout-comparison logic. Commit: fixes `behavior_gate.py::run_mode_a`. Test:
`tests/unit/test_verify_gates.py::test_run_mode_a_does_not_vacuously_pass_when_zero_tests_discovered`.

**Status:** fixed. **Known gap still open:** ShiftCode's Mode A only
discovers `unittest.TestCase`-style tests; it does not run pytest-style bare
`assert` test suites at all (a very common real-world convention — this
exact library uses it). A file whose only test suite is pytest-style now
correctly reports `UNVERIFIED` instead of a false `PASS`, but real pytest
support (bundling a py2-compatible pytest into the sandbox, or writing a
minimal bare-function test runner) is not built. Worth prioritizing given how
common the convention is in real code.

---

## 1. `lib2to3`'s `fix_long` corrupts identifiers that shadow the `long` builtin

**Found via:** stress test against `docopt` (real library — cloned from
`github.com/docopt/docopt`, taken at the commit immediately before its actual
"Support for Python 3.2" commit, so this is real, historically-accurate
Python 2 source with its real test suite, not a synthetic example).

**Symptom:** `docopt.py` has `class Option: def __init__(self, short=None,
long=None, ...)` — a parameter legitimately named `long`. After
`deterministic_transform`:
```python
# before:
long = long + '=' if long else None
self.long = long
# after:
long = int + '=' if int else None
self.long = int
```
`self.long` is now bound to the `int` type object itself, not the intended
value. Any call path that hits the `if not self.is_flag:` branch (e.g.
`Option(parse='-h TOPIC')`, which the real test suite exercises) raises
`TypeError: unsupported operand type(s) for +: 'type' and 'str'` at runtime.

**Root cause:** `lib2to3`'s `fix_long` fixer (`vendor/lib2to3/fixes/fix_long.py`)
renames every occurrence of the identifier `long` to `int` — it's a pure
pattern match with no scope/binding analysis. Its `is_probably_builtin()`
guard (`vendor/lib2to3/fixer_util.py`) only special-cases two syntactic
positions (an assignment target, a parameter declaration site) — it has no
way to recognize "this is a *read* of a local variable/parameter that
happens to be named `long`, not the builtin type." This is a genuine,
inherited limitation of the upstream CPython tool ShiftCode vendors, not
something introduced by ShiftCode's own code. No `needs_llm` finding was
generated for this — the fixer "succeeded" by its own logic, so nothing
flagged it to the Planner; `docopt.py` had 0 plan steps, 0 repair attempts
before the fix below — 100% deterministic-layer bug, zero LLM involvement.

**Fix — new agent, not a patch to the fixer.** Patching `fix_long` itself
only fixes this one identifier; the same class of bug (a mechanical rename
colliding with an unrelated local name) can happen with any of the other 51
fixers. Added `TransformAuditorAgent` (`agents/transform_auditor.py`,
`prompts/transform_auditor.md`): runs once per file, right after
`deterministic_transform`, comparing original source against the transform's
output and flagging cases where a mechanical change looks like it altered
*meaning*, not just syntax. Its findings become ordinary `needs_llm`
`Py2Finding`s (with the agent's specific reasoning carried through in a new
`detail` field so the Planner isn't told just "something's wrong at line
29") feeding into the exact same Planner → Refactorer ↔ Auditor loop
everything else goes through — no separate repair path, no special-casing
downstream. Verified for real (not just unit-tested): a live call against
the actual corrupted `docopt.py` correctly identified both corrupted
occurrences (lines 27 and 29) with accurate reasoning.

**Status:** fixed (new gate, not a narrow patch — should generalize to
other fixers' blind spots, to be confirmed by further stress testing).

---

## How to add an entry

When a stress test (or anything else) surfaces a real bug in ShiftCode
itself: symptom (what happened), root cause (why, precisely), fix (code
change and/or which agent/gate now catches this class of bug going forward,
not just this one instance), status. Prefer "which agent generalizes this"
over "which line got patched" where possible — the goal is a pipeline that
gets more trustworthy over time, not a growing list of one-off patches.
