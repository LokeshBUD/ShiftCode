# Stress-test log

Tracks every real-world codebase ShiftCode has actually been run against —
not the bundled fixtures, real libraries pulled from GitHub at their actual
pre-migration commit. Purpose: show, honestly, what's been validated and
what hasn't. A row here means "we ran the real pipeline against this," not
"this passed" — outcome and status columns say what actually happened,
including when it didn't work. See `docs/bug-log.md` for the bugs these runs
found in ShiftCode itself.

Currently Python 2 → Python 3 only; this table is structured to extend to
other language pairs later (`Pair` column) without restructuring.

Every run here follows `docs/stress-test-methodology.md` — find, run,
diagnose (reproduce directly, don't guess), design the generalized fix, log
both directions, confirm on the original case and then a different one. Not
optional per-run; that consistency is what makes this log trustworthy.

## Summary

| # | Library | Pair | Source | Outcome | Bugs found | Status |
|---|---------|------|--------|---------|------------|--------|
| 3 | `inflection` | py2→py3 | [jpvanhal/inflection](https://github.com/jpvanhal/inflection) @ `58b0016` | `inflection.py` now reaches real `VERIFIED` - Mode A runs its real parametrized pytest suite on both interpreters, all outcomes match. Bugs #5 and #8 both confirmed fixed on this library. | [#5](bug-log.md) (confirmed fixed), [#6](bug-log.md) (still open, didn't block this run), [#8](bug-log.md) (confirmed fixed) | complete |
| 2 | `python-slugify` | py2→py3 | [un33k/python-slugify](https://github.com/un33k/python-slugify) @ `e951142` (re-extracted fresh; earlier `b3544c6^` no longer on disk) | `__init__.py` now reaches `VERIFIED_INFERRED` - all 5 auto-generated characterization tests pass on both interpreters (Mode C). Bugs #3, #5, #7, #8 all confirmed fixed on this library. | [#3](bug-log.md), [#5](bug-log.md), [#7](bug-log.md), [#8](bug-log.md) (all confirmed fixed) | complete |
| 1 | `docopt` | py2→py3 | [docopt/docopt](https://github.com/docopt/docopt) @ `a5ec786` | `docopt.py` now reaches real `VERIFIED` (previously stuck at `NEEDS_REVIEW` purely because Mode A couldn't run its pytest-style tests) — Mode A discovered and matched all 3 tests on both interpreters. First run of this re-test hit a Refactorer indentation failure (3/3 attempts) that a same-config re-run did not reproduce - LLM output non-determinism, not a pipeline bug. | [#1](bug-log.md), [#2](bug-log.md) (both found and fixed previously); this run confirms bug #5's Mode A switch closes the last known gap from entry 1 below | complete — strongest result so far, real `VERIFIED` on real historical code |

## Entry detail

### 3. `inflection`

- **Date:** 2026-07-22
- **Source:** found via `scripts/find_stress_test_candidates.py` (the first
  library found through the scout tool rather than by hand) — real library,
  pre-py3-support commit `58b0016`. Notably, manually inspecting this repo's
  `HEAD` earlier in the session had wrongly ruled it out (modern pytest +
  `typing` code, looked unsuitable) — the scout's proper git-history search
  found the actual, genuinely-suitable pre-py3 state that manual inspection
  of `HEAD` alone had missed.
- **Outcome:** all 4 files `NEEDS_REVIEW`. `inflection.py` (the real module,
  404 lines) failed Mode A with a confusing `py2=? py3=ERROR` signature;
  reproduced directly against the
  real `python:3-slim` sandbox and found the actual cause: `test_inflection.py`
  does `import pytest`, and `pytest` isn't installed in the sandbox image at
  all. `conf.py`/`setup.py` correctly `UNVERIFIED` (no test suite, no entry
  point - `conf.py` is Sphinx docs config, not really library code, an
  artifact of extracting the whole repo rather than just the package).
  `test_inflection.py` itself correctly recognized as not Mode-B-eligible.
- **Bugs found:** #5 (sandbox has no dependencies installed - this is the
  *second* confirmation of this exact root cause, first found via
  `python-slugify`'s missing `unidecode`), #6 (files with zero findings get
  zero repair attempts, didn't matter here since the blocker isn't
  code-fixable anyway).
- **Status:** blocked on #5, same as `python-slugify`. Two independent real
  libraries now converging on the same root blocker is a strong signal for
  where to focus next.

**Update (2026-07-22, after bug #5's fix, sandbox images rebuilt):**
re-extracted fresh at the same commit (`58b0016`) since the earlier working
copy was in a temp dir that no longer existed. `pytest` now genuinely
installs and runs inside the sandbox - `inflection.py` actually executes its
real parametrized test suite on both interpreters instead of failing before
a single test could run, confirming bug #5's second root cause (missing
`pytest` itself) is fixed. This unblocked a real `FAIL` on genuine
`test_parameterize`/`test_parameterize_and_normalize` outcome mismatches -
diagnosed directly against `inflection.py`'s `transliterate()`:
`unicodedata.normalize('NFKD', string).encode('ascii', 'ignore')` returns
`bytes` in Python 3, then feeds into `re.sub` with a `str` pattern in
`parameterize()`, raising `TypeError`. This is bug #8 - the exact same line
shape independently found in `python-slugify`'s `slugify()` in this same
session. Fix designed and implemented (`analyze.py`'s
`_find_normalize_encode_chains`); live re-confirmation against this file
specifically was not yet completed, blocked by the LLM provider's monthly
spending cap being hit while confirming the same fix against
`python-slugify` first. `conf.py`/`setup.py`/`test_inflection.py` unchanged
from the first run - correctly `UNVERIFIED`/not-Mode-B-eligible for the same
already-understood reasons, `dependency_provisioning: None` since this repo
has no `requirements.txt` (matches - `inflection` has zero runtime deps;
only `pytest`, now baked into the image itself, was ever missing).

**Update (2026-07-22, after LLM provider quota reset, model switched to
`gemini-3.5-flash-lite`):** re-ran the same file. `inflection.py` now reaches
real `VERIFIED` - Mode A's pytest run shows all outcomes matching on both
interpreters, only raw stdout warning text differs (correctly not treated as
a failure). Confirms bug #8's fix (`_find_normalize_encode_chains`) resolves
the `transliterate()` bytes/str `TypeError` end-to-end, and confirms the
smaller/cheaper `flash-lite` model handles this repair correctly too - the
fix isn't dependent on a larger model.

### 2. `python-slugify`

- **Date:** 2026-07-22
- **Source:** real library, taken at the commit immediately before its
  actual "Support python3" commit — real historical Python 2 source with its
  real `unittest.TestCase`-based test suite (chosen specifically to exercise
  the Mode A "tests actually run" path, complementing `docopt`'s case where
  they structurally couldn't).
- **Why this target:** genuinely different Python 2 constructs than
  `docopt` — `from htmlentitydefs import name2codepoint` (py2-only stdlib
  module), `from types import UnicodeType` (no py3 equivalent — py3 has no
  separate unicode type), bare `unicode(text, 'utf-8', 'ignore')` calls,
  `unichr(...)`, and a genuinely subtle trap: `.encode('ascii', 'ignore')`
  on a normalized string produces `bytes` in Python 3 (it produced `str` in
  Python 2), which would silently break every subsequent string operation on
  that value — a real semantic-drift case our current `needs_llm` detection
  (division-ambiguity only) doesn't even look for. Never got far enough to
  see how the pipeline handles this - that's the next thing to check once
  bug #3 is fixed and this run is resumed.
- **First run:** pipeline crashed partway through (bug #3) — a transient
  network timeout during an Auditor call propagated as an unhandled
  `LLMTimeoutError` and killed the whole process before a report was
  produced.
- **Fix applied:** #3 (`call_structured` retries transient network errors
  with backoff; `run_migration`'s per-file loop isolates one file's
  unexpected failure from the rest of the batch).
- **Second run** (after fix): no crash — confirms #3's fix works for real.
  `TransformAuditorAgent` generalized correctly to a *second*, genuinely
  different bug pattern (not identifier-shadowing this time): mechanical
  `unicode(...)` → `str(...)` translation left a call that raises `TypeError`
  in Python 3, since `unidecode()` already returns `str` there. The
  Refactorer made real, correct progress across attempts 1→2 — fixed both
  that issue *and* a subtler one (`.encode('ascii', 'ignore')` producing
  `bytes` instead of `str` in Python 3, silently breaking every later string
  op) without either being explicitly spelled out in the plan. Ultimately
  still `NEEDS_REVIEW`: `unidecode` (a real runtime dependency) isn't
  installed in the bare sandbox images, so neither interpreter can import
  the module at all — confirmed by running the actual Docker container by
  hand. This is bug #5, and applies regardless of how correct the code fix
  is.
- **Status:** crash-fix (#3) confirmed working. Blocked on #5 (same as
  `inflection`) for anything past that.

**Update (2026-07-22, after bug #5's fix, sandbox images rebuilt):**
re-extracted fresh (landed on commit `e951142`, a different-but-equally-valid
pre-py3 commit than the original `b3544c6^` since this was a fresh scout run
against the live repo, not the same working copy) and added a hand-written
`requirements.txt` (`Unidecode>=0.04.9`, taken from the real `setup.py`'s
`install_requires`, since the extraction script only pulls `.py` files).
Confirmed: `dependency_provisioning: "py2 sandbox: installed Unidecode; py3
sandbox: installed Unidecode"` - `unidecode` now genuinely installs and
imports on both sides, closing bug #5's first root cause. Unblocked,
`__init__.py` surfaced a *new* real bug: `from types import UnicodeType` has
no Python 3 equivalent, and lib2to3's `fix_types` fixer only handles the
`types.X` attribute form, not this bare-import form - the whole module
failed to import (`ImportError`), which made every characterization test
case look like a mismatch and obscured the real single-line cause. Reproduced
directly against the real sandbox container. This is bug #7 - designed and
implemented a fix (`analyze.py`'s `_find_legacy_types_from_imports`, reusing
`fix_types`'s own type-name mapping), then **re-ran this exact file again**:
confirmed fixed - the import is gone, `type(text) != UnicodeType` correctly
became `type(text) != str`. That re-run then surfaced bug #8 (the same
`unicodedata.normalize(...).encode(...)` bytes/str trap independently found
in `inflection`, see entry 3's update) - fix implemented but a third
re-confirmation run hit the LLM provider's `429 monthly spending cap
exceeded` before finishing, so bug #8's fix is implemented and unit-tested
but not yet confirmed live against this file. `setup.py` and `test.py`
outcomes unchanged from before - correctly `UNVERIFIED`/Mode-B-ineligible
for the same already-understood reasons.

**Update (2026-07-22, after LLM provider quota reset, model switched to
`gemini-3.5-flash-lite`):** re-ran `__init__.py`. Now reaches
`VERIFIED_INFERRED` - all 5 auto-generated characterization test cases pass
identically on both interpreters (Mode C). Confirms bug #8's fix resolves
`slugify()`'s bytes/str `TypeError` end-to-end. `setup.py`/`test.py`
unchanged - correctly `UNVERIFIED`/Mode-B-ineligible for the same reasons as
every prior run. Every bug this library surfaced (#3, #5, #7, #8) is now
confirmed fixed - no open blocker left on this library.

### 1. `docopt`

- **Date:** 2026-07-22
- **Source:** real library, taken at the commit immediately before its
  actual "Support for Python 3.2" commit — real historical Python 2 source
  (96-line `docopt.py`) with its real (pytest-style) test suite and a real
  human-authored reference migration one commit later, for comparison.
- **First run** (before bug #1/#2 fixes existed): `docopt.py` incorrectly
  reached `VERIFIED` — a severe bug (`lib2to3`'s `fix_long` corrupting a
  parameter legitimately named `long`, `self.long` silently bound to the
  `int` type instead of a value) was present in the "verified" output. Root
  cause was bug #2 (Mode A vacuously reported "all tests match" when zero
  tests were actually discoverable via `unittest`, since the real test suite
  is pytest-style).
- **Fixes applied:** #2 (vacuous-pass fix in `behavior_gate.py`), #1 (new
  `TransformAuditorAgent`, reviews the deterministic transform's own diff
  for exactly this class of silent corruption).
- **Second run** (after fixes): `TransformAuditorAgent` correctly flagged
  both corrupted lines with accurate reasoning. Planner correctly wrote plan
  steps to revert the corruption. Refactorer hit syntax errors on attempts
  1-2, self-corrected via Auditor hints, succeeded on attempt 3 — confirmed
  the real corruption is gone from `final_source`. Final status:
  `NEEDS_REVIEW`, not `VERIFIED` — correct and honest, since Mode A still
  structurally can't run this file's pytest-style tests (that gap is real
  and not yet fixed; see `bug-log.md` #2's "known gap still open" note).
  `example.py` and `test_docopt.py` (the other two files in the repo) landed
  on `NEEDS_REVIEW` for already-understood, correctly-identified reasons
  (Mode B's single-file isolation breaking on a sibling import; a test file
  correctly recognized as having no standalone entry point).
- **Status:** complete. Real bug found, real bug fixed, confirmed by a
  second real run — the strongest validation so far, even though no file in
  this run reached plain `VERIFIED`.

**Update (2026-07-22, after bug #5's fix, sandbox images rebuilt):**
re-extracted fresh at the same commit (`a5ec786`). Mode A now runs `pytest`
(not stdlib `unittest`) against `test_docopt.py`'s real pytest-style suite -
the exact gap called out as "real and not yet fixed" in this entry's second
run above. First attempt: `docopt.py` exhausted all 3 repair attempts on a
Refactorer indentation mistake unrelated to anything this session touched
(`SYNTAX_ERROR: expected an indented block ... on line 10`, an `__init__`
body indentation slip); a same-config re-run of the same file did **not**
reproduce this - real LLM output non-determinism, not a pipeline bug (ruled
out by direct re-run, not assumed). That second run reached real `VERIFIED`:
Mode A discovered and ran all 3 tests via pytest in both the
`shiftcode-py2-sandbox` and `shiftcode-py3-sandbox` containers, matched all
outcomes, only raw stdout warning text differed (correctly not treated as a
failure). This is the first file in any stress test this session to reach
plain `VERIFIED` end-to-end on real historical code. `example.py` and
`test_docopt.py` outcomes unchanged from the original run - correctly
`NEEDS_REVIEW` for the same already-understood, correctly-identified reasons.

## How to add an entry

Follow `docs/stress-test-methodology.md` — that's the canonical process
(find, run, diagnose, design, log both directions, confirm twice). Short
version for this file specifically: bump the summary table (newest first,
don't renumber old entries), add a detail section with date, source commit,
why this target was chosen, outcome, and status. A blocked/crashed run is
still worth a row — the point is an honest record, not a highlight reel.
