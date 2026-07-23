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
| 10 | full corpus regression re-run | py2→py3 | all 8 previously-tested libraries (`docopt`, `python-slugify`, `inflection`, `jsonschema`, `purl`-nested, `html2text`, `schedule`, `requests`), re-run fully unattended (no manual intervention) after this session's differential-fuzzing and self-improving-fixer-library work, to confirm nothing regressed. | 6/8 matched documented results exactly. `docopt` hit already-known LLM non-determinism (unrelated to any code change). `python-slugify` and `schedule` both regressed from `VERIFIED_INFERRED` to `NEEDS_REVIEW` - root-caused to an interaction between an earlier fix (#17) and a real, previously-unhit sandbox gap; fixed, and both now reach a *stronger* result than before (real `VERIFIED`, not just `VERIFIED_INFERRED`). | [#20](bug-log.md) (found and fixed this run) | complete |
| 9 | `requests` | py2→py3 | [kennethreitz/requests](https://github.com/kennethreitz/requests) @ `a16278e8` — first real multi-file library stress-tested after multi-file sandboxing landed. Scout wrongly flagged it as "many external deps"; all of them were requests' own vendored submodules (`requests/packages/poster/`), confirmed by inspecting the real extracted tree. | `requests/core.py`, `requests/packages/poster/encode.py`, `setup.py` reach genuine `VERIFIED_INFERRED`. `requests/__init__.py` now reaches real Mode A (previously blocked, then crashed on a missing-trailing-newline parse failure) — its own test suite does live network calls (`test_HTTP_200_OK_GET` etc.), correctly failing inside the sandbox's deliberate `--network none` isolation, not a ShiftCode bug. Full multi-level relative-import closure (`.packages.poster.encode`) and an implicit py2-only same-package `import packages` both resolved correctly. | [#18](bug-log.md) (found and fixed this run) | complete |
| 8 | `purl` (re-validated, nested) | py2→py3 | [codeinthehole/purl](https://github.com/codeinthehole/purl) @ `1db2106`, re-extracted with the real `purl/`/`tests/` directory structure preserved (see entry 5's update) | Built real multi-file dependency-aware sandboxing to close bug #13 for real (the original repro was itself an artifact of the extraction script's flattening). `purl/__init__.py` now reaches genuine `VERIFIED` via real Mode A (upgraded from an initial `VERIFIED_INFERRED` once bug #17 was fixed for real too) — the strongest confidence tier, running purl's actual test suite for real. New fixture (`sample_multi_file_py2`) confirmed both a package+sibling-module shape and a plain flat-sibling-imports shape end to end. | [#13](bug-log.md), [#15](bug-log.md), [#16](bug-log.md), [#17](bug-log.md) (all found and fixed this round) | complete |
| 7 | `schedule` | py2→py3 | [dbader/schedule](https://github.com/dbader/schedule) @ `fffe355` | `__init__.py` reaches genuine `VERIFIED_INFERRED` - 9 auto-generated characterization tests pass on both interpreters. `mock` dependency correctly provisioned. No new bugs - clean confirmation run. **Update (entry 10):** now reaches real `VERIFIED` - once bug #17 started routing it to Mode A, a real sandbox-wrapping gap (#20) blocked it, then got fixed; `__init__.py`'s actual test suite now runs and passes for real, stronger than the original result. | none (confirmation run); see #20 for the later update | complete |
| 6 | `html2text` | py2→py3 | [aaronsw/html2text](https://github.com/aaronsw/html2text) @ `7a327b8` | Chosen specifically for having *no test suite at all*. Hit an obscure `lib2to3`-unfixable py2.2-era `True`/`False` shim that produced a confusing raw-traceback `NEEDS_REVIEW` message instead of a clean one - fixed. | [#14](bug-log.md) (found and fixed this run) | complete |
| 5 | `purl` | py2→py3 | [codeinthehole/purl](https://github.com/codeinthehole/purl) @ `1db2106` | Scout misclassified this as "no test suite" (its own detection missed `from unittest import TestCase`); the `_discover_test_pairs` fix from this same round actually paired it correctly. Found a real vacuous-pass variant: both interpreters failing test collection identically (`from purl import URL`, package-name-unaware sandbox) was scored as a match. | [#12](bug-log.md) (found and fixed this run), [#13](bug-log.md) (found, fix designed, deferred - same disposition as #6) | complete |
| 4 | `jsonschema` | py2→py3 | [python-jsonschema/jsonschema](https://github.com/python-jsonschema/jsonschema) @ `f72f335` | `jsonschema.py` now runs its real 209-case test suite via Mode A (was 12, missing ~200 dynamically-generated tests, before the fix); 206/209 pass, 3 genuine remaining failures correctly left `NEEDS_REVIEW` (test oracle relies on `.message` and py2-specific repr formatting - not something ShiftCode should or does auto-fix). `tests.py` correctly stopped being characterization-tested as if it were library code. | [#9](bug-log.md), [#10](bug-log.md), [#11](bug-log.md) (all found and fixed this run) | complete |
| 3 | `inflection` | py2→py3 | [jpvanhal/inflection](https://github.com/jpvanhal/inflection) @ `58b0016` | `inflection.py` now reaches real `VERIFIED` - Mode A runs its real parametrized pytest suite on both interpreters, all outcomes match. Bugs #5 and #8 both confirmed fixed on this library. | [#5](bug-log.md) (confirmed fixed), [#6](bug-log.md) (still open, didn't block this run), [#8](bug-log.md) (confirmed fixed) | complete |
| 2 | `python-slugify` | py2→py3 | [un33k/python-slugify](https://github.com/un33k/python-slugify) @ `e951142` (re-extracted fresh; earlier `b3544c6^` no longer on disk) | `__init__.py` now reaches `VERIFIED_INFERRED` - all 5 auto-generated characterization tests pass on both interpreters (Mode C). Bugs #3, #5, #7, #8 all confirmed fixed on this library. **Update (entry 10):** now reaches real `VERIFIED` - a real sandbox-wrapping gap (#20) blocked Mode A once test-pairing correctly started matching `test.py`; fixed (also caught a real repo-name-vs-import-name mismatch: `python-slugify` ships a module actually imported as `slugify`). | [#3](bug-log.md), [#5](bug-log.md), [#7](bug-log.md), [#8](bug-log.md) (all confirmed fixed); see #20 for the later update | complete |
| 1 | `docopt` | py2→py3 | [docopt/docopt](https://github.com/docopt/docopt) @ `a5ec786` | `docopt.py` now reaches real `VERIFIED` (previously stuck at `NEEDS_REVIEW` purely because Mode A couldn't run its pytest-style tests) — Mode A discovered and matched all 3 tests on both interpreters. First run of this re-test hit a Refactorer indentation failure (3/3 attempts) that a same-config re-run did not reproduce - LLM output non-determinism, not a pipeline bug. | [#1](bug-log.md), [#2](bug-log.md) (both found and fixed previously); this run confirms bug #5's Mode A switch closes the last known gap from entry 1 below | complete — strongest result so far, real `VERIFIED` on real historical code |

## Entry detail

### 10. Full corpus regression re-run

- **Date:** 2026-07-23
- **Why this run:** after building differential fuzzing and the self-improving fixer library this session, re-ran every previously-tested real library fully unattended (no manual intervention) - not to test the new features again, but to confirm the existing, already-validated corpus hadn't regressed.
- **Outcome:** 6/8 matched documented results exactly (`inflection`, `jsonschema`, `purl`, `html2text`, and `requests`'s three files). `docopt` hit the same known LLM-output-nondeterminism failure mode already logged in entry 1 (indentation slip near a function def; unrelated to any code change). `python-slugify` and `schedule` both newly landed on `NEEDS_REVIEW` where they'd previously reached `VERIFIED_INFERRED`.
- **Diagnosis:** confirmed via `git diff` that neither differential fuzzing nor the fixer library touched anything relevant (`orchestrator.py`'s only change, repair-history capture, is gated off by default and never executed this run). Root-caused instead to bug #17 (package-name test-matching, added earlier this session) correctly routing these two libraries into Mode A for the first time - and Mode A never getting the same package-wrapping fix Mode C got for the analogous `purl` case (#13). See bug-log.md #20 for the full fix, including a real subtlety caught mid-fix (repo directory name isn't a reliable stand-in for the real importable package name - `python-slugify` ships a module called `slugify`).
- **Bugs found:** #20 (found and fixed this run).
- **Status:** complete - both libraries re-confirmed live after the fix, both now reach real `VERIFIED` (stronger than their original `VERIFIED_INFERRED`). `purl` and `requests` re-confirmed unaffected by the fix.

### 7. `schedule`

- **Date:** 2026-07-22
- **Source:** expanded stress-test round - `scripts/find_stress_test_candidates.py`'s `_STDLIB_HINTS` set was itself found to be badly incomplete during candidate discovery (missing dozens of real Python 2.7 stdlib modules - `distutils`, `pickle`, `hashlib`, `datetime`, etc. - all wrongly counted as "external deps," rejecting genuinely suitable candidates). Fixed the scout's stdlib list first, which is what surfaced `schedule` (and `jsonschema`, `toolz`, `blinker`, `argcomplete`) as suitable at all.
- **Why this target:** real py3-conversion history, real `unittest`+`mock`-based test suite, small (663 lines) - chosen as a clean confirmation case after bug #12's fix (also `__init__.py`-based, same shape as `purl`, but with a self-contained module that doesn't hit bug #13's package-import gap).
- **Outcome:** `__init__.py` reaches genuine `VERIFIED_INFERRED` - 9 real auto-generated characterization tests pass identically on both interpreters. `mock` (a real test-only dependency, not in the stdlib) correctly provisioned into both sandboxes. `test_schedule.py` - named after the *original* GitHub repo/directory, not any file our flat extraction produces - doesn't match any of `_discover_test_pairs`' three recognized conventions, so `__init__.py` fell to Mode C instead of Mode A; this is an artifact of this session's own flat single-directory extraction script, not a real ShiftCode gap (a real end user's actual nested project structure wouldn't lose that naming context the way flattening does).
- **Bugs found:** none - a clean confirmation run.
- **Status:** complete.

### 6. `html2text`

- **Date:** 2026-07-22
- **Source:** `aaronsw/html2text` @ `7a327b8`, deliberately chosen for having *no test suite at all* (confirmed by the scout, not guessed) - a genuine Mode C target, same intent as `purl` before it turned out to actually have one.
- **Outcome:** hit a real, obscure edge case before Mode C could even run: `if not hasattr(__builtins__, 'True'): True, False = 1, 0` (a Python 2.2-era compatibility shim) has no `lib2to3` fixer, survives `deterministic_transform` unchanged, and is a genuine `SyntaxError` under Python 3's real parser (`True`/`False` are reserved keywords there). The resulting `NEEDS_REVIEW` was always the *correct* outcome (no crash, no false confidence - bug #3's isolation already guaranteed that) - what was wrong was the diagnostic message, a confusing raw traceback fragment instead of a clear one.
- **Bugs found:** #14 (found and fixed this run - see bug-log.md for full detail).
- **Status:** complete; re-run after the fix confirms a clean, readable `NEEDS_REVIEW` reason.

### 5. `purl`

- **Date:** 2026-07-22
- **Source:** `codeinthehole/purl` @ `1db2106`. The scout's own test-suite detection missed this one (`from unittest import TestCase` + bare `TestCase` doesn't match its `"unittest.TestCase" in content` substring check), so it was picked as a "no test suite" Mode C candidate - the `_discover_test_pairs` fix from the same stress-test round (bug #9) actually paired `__init__.py` with `tests.py` correctly, turning this into an unplanned but valuable Mode A case instead.
- **Outcome:** first run: `__init__.py` reached a **false** `VERIFIED` - `tests.py` does `from purl import URL`, which fails identically on both interpreters (`ModuleNotFoundError`) because the sandbox writes the module as a bare `__init__.py`, not a real `purl/` package. That identical failure trivially "matched," reported as PASS. Confirmed directly against the real sandbox container before concluding anything. Re-run after the fix (bug #12): correctly reports `NEEDS_REVIEW`/`UNVERIFIED` with a clear reason instead.
- **Bugs found:** #12 (found and fixed this run - a real, high-value catch: without it, this library's migration would have shipped as silently, falsely "verified" with zero actual behavior validation), #13 (the deeper structural cause - found, root-caused, initially deferred, then fixed for real - see update below).
- **Status:** complete - #12 confirmed fixed via direct re-run; #13 later fixed for real (see update).

**Update (2026-07-22, multi-file dependency-aware sandboxing built to fix bug #13 for real):**
found that `scripts/find_stress_test_candidates.py`'s own `extract()` had been flattening every file into one directory the whole time - the real `codeinthehole/purl` repo has genuine `purl/__init__.py` and `tests/tests.py` (a top-level `tests/` directory, not nested inside `purl/`). Fixed the extractor to preserve real relative paths, re-extracted fresh, and confirmed via `gh api` against the exact extracted commit (`1db2106`) that this nested layout is real, not an assumption. Built real multi-file dependency-aware sandboxing (`pipeline/dependencies.py` - AST-based local-import resolution, transitive closure, topological repair ordering; a shared sandbox-tree writer that preserves real relative paths instead of flattening) rather than the narrower `__init__.py`-specific fix originally sketched. Validated first against a new purpose-built fixture (`tests/fixtures/sample_multi_file_py2/`, both a `package/__init__.py` + sibling-module shape and a plain flat-sibling-imports shape) - real end-to-end run, all 4 real modules reached `VERIFIED`/`VERIFIED_INFERRED`. That fixture run surfaced two further real bugs (#15: a leaf module's own package `__init__.py` wasn't in the sandbox when nothing in the module itself imports it - Python 2 has no namespace-package support, Python 3 silently tolerates the gap; #16: Mode C compared raw `repr()` strings, flagging identical dict content in a different key order as a false mismatch), both found, fixed, and confirmed. Re-ran `purl` with everything fixed: `purl/__init__.py` now reaches genuine `VERIFIED_INFERRED` (5 real characterization tests, correctly resolving `from purl import URL`) instead of the original false `VERIFIED` - bug #13 is closed for real. Not a Mode A pass specifically - `purl`'s real test suite sits in that top-level `tests/` directory, a distinct, real, still-open test-discovery convention gap (bug #17, lower priority, doesn't affect correctness).

### 4. `jsonschema`

- **Date:** 2026-07-22
- **Source:** `python-jsonschema/jsonschema` @ `f72f335` - the first library specifically re-picked to exercise Mode A against real historical code again after bug #5's fix, now that the scout's stdlib-hints fix made it discoverable as suitable.
- **Outcome:** `jsonschema.py` initially failed Mode A with `py3=?` for *every single test* (209 of them) - the uniform pattern was itself the tell that something structural was wrong, not a real per-test difference. Root cause: `tests.py` uses Python 2's `__metaclass__ = X` class-attribute syntax to dynamically generate ~200 named test methods; on Python 3 that syntax is valid but silently does nothing (no error), so only 12 raw, unexpanded methods got collected there instead - a completely disjoint set of test names from py2's ~200. Also found: `tests.py` (no underscore) wasn't recognized by any test-discovery or test-classification logic in the pipeline, so it was both missed by `_discover_test_pairs` *and*, once found via the fix, would have been wrongly characterization-tested as if it were library code.
- **Bugs found:** #9 (`_discover_test_pairs` missing the `tests.py`/`test.py` convention), #10 (a matched test file not being recognized as "don't characterization-test this"), #11 (test file itself never gets `deterministic_transform`'d before running on py3 - all found and fixed this run).
- **Status:** complete. Re-run after all three fixes: `jsonschema.py` now runs the real 209-test suite on both interpreters, 206 pass identically; the 3 remaining failures are genuine, correctly *not* auto-fixed (one needs `Exception.message`, removed in Python 3; the other asserts against Python 2's own `u'...'`-prefixed repr baked literally into the expected string content - a stale test oracle, not a migration bug, and editing test assertions is deliberately outside what the Refactorer is ever allowed to touch).

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
