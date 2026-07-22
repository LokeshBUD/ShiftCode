# Bug log

Real bugs found in ShiftCode itself, mostly via stress-testing against real
external code (not the bundled fixtures) — the whole point of stress testing
is to find the class of bug that a hand-built fixture won't surface. Each
entry: what was wrong, how it was found, the root cause, and what now catches
this class of bug going forward (a code fix, a new gate, or a new agent).

Format: newest first.

---

## 18. `find_lib2to3_findings` had no exception handling around its own parse call - a raw lib2to3 `ParseError` crashed past `deterministic_transform`'s already-correct handling

**Found via:** `kennethreitz/requests` @ `a16278e8` (first real multi-file library stress-tested after multi-file sandboxing landed). `requests/__init__.py` and `requests/packages/__init__.py` both have no trailing newline - real, legitimate content, but something lib2to3's tokenizer/parser can't handle. Both landed on `NEEDS_REVIEW` with a confusing `"unexpected error while processing this file: bad input: type=0, value='', context=('\n', (5, 0))"` message instead of the clean `DeterministicTransformError` diagnosis that already exists for exactly this failure mode.

**Root cause:** `_process_file_phase_a` calls `find_lib2to3_findings(original_source)` *before* `deterministic_transform(original_source)` - both parse the same source with lib2to3. `find_lib2to3_findings`'s own parse call was wrapped in `try/finally` (not `try/except`) - the `finally` only restored the grammar attribute, never actually caught anything, so a real `ParseError` propagated straight through, uncaught, before `deterministic_transform`'s own try/except (which already correctly wraps this exact failure as `DeterministicTransformError`) ever got a chance to run. The crash bypassed the good handling entirely and was instead caught by `run_migration`'s generic per-file backstop, with a far less informative message.

**Fix:** two parts. (1) `find_lib2to3_findings` now catches any parse failure and returns an empty findings list - it's purely informational/best-effort by its own docstring ("informational context for the Planner, not what actually gets applied"), so degrading gracefully here is correct regardless of what caused the parse failure. (2) The actual trigger - a missing trailing newline - is semantically inert (Python runs a script identically either way) but genuinely unparseable by lib2to3's tokenizer, so `ingest()` now normalizes every file's `original_source` to end with `\n` once, up front, rather than working around the same gap in every downstream lib2to3 consumer.

**Status:** fully fixed, confirmed directly against both real files that found it - `requests/__init__.py` and `requests/packages/__init__.py` both now parse and migrate normally instead of landing on `NEEDS_REVIEW` at all. Unit-tested (`test_analyze.py` for the graceful-degradation fix, `test_ingest.py` for the newline normalization).

---

## 17. `_discover_test_pairs` doesn't recognize a top-level `tests/` directory sibling to the package it tests

**Found via:** real re-validation of `codeinthehole/purl` @ `1db2106` after fixing the extractor's flattening (see bug #13). The real repo's layout is `purl/__init__.py` + a *separate*, top-level `tests/tests.py` (not nested inside `purl/`) - a real, common convention (Django apps and many other real packages use exactly this shape), distinct from every convention `_discover_test_pairs` currently recognizes (`test_<name>.py` beside the module, `tests.py`/`test.py` beside the module, or - the fix added alongside this stress-test round - a package-named `test_<pkgname>.py` inside or beside the package directory). None of those match "a `tests/` directory as a sibling of the package directory, containing a generically-named `tests.py`."

**Symptom:** `purl/__init__.py` falls through to Mode C (characterization testing) instead of running its real, human-authored test suite via Mode A - not a false result (Mode C correctly reached genuine `VERIFIED_INFERRED`, see bug #13/#16), just a weaker confidence tier than the stronger evidence that was actually available.

**Status:** fixed. `_discover_test_pairs` now also checks a sibling `tests/` directory (one level up from the package) for both a package-named test file (`test_<pkgname>.py` - real shape confirmed on `requests`) and a generically-named one (`tests.py`/`test.py` - real shape confirmed on `purl` itself). Confirmed via direct re-run against the real `purl` extraction: `purl/__init__.py` now reaches genuine `VERIFIED` (not `VERIFIED_INFERRED`) via Mode A, running its real test suite for real - the strongest confidence tier, closing the loop this bug and bug #13 opened together. Unit-tested (`test_discover_test_pairs.py`).

---

## 16. Mode C compared raw `repr()` strings, which is sensitive to dict/set ordering differences that aren't real behavior differences

**Found via:** real re-validation of `codeinthehole/purl` (properly nested this time - see bug #13's fix below) after multi-file sandboxing landed. `purl.parse()` returned the exact same key/value pairs on both interpreters, but Mode C flagged a mismatch: Python 2 dicts have no ordering guarantee, Python 3.7+ guarantees insertion order, so the *same* dict can legitimately `repr()` differently on each side. The comparison (`py2_val != py3_val` on raw repr strings) treated that as a real behavioral difference.

**Root cause:** comparing string reprs instead of the actual values - a false positive, same shape as bug #8's "compares interpreter-formatted text, not meaning" class, but on Mode C's result-comparison path rather than a source-code construct.

**Fix:** `characterization_gate.py` gained `_values_equal`, which parses both reprs via `ast.literal_eval` (same safety posture as `args_literal` - never `eval()`) and compares the actual parsed values; falls back to the previous plain string comparison when the repr isn't literal-parseable (e.g. a custom object's repr), so nothing regresses for cases this can't safely improve on.

**Status:** fixed, confirmed via direct re-run against the real `purl` case that found it (`purl/__init__.py` now reaches genuine `VERIFIED_INFERRED` instead of a false mismatch), unit-tested (`test_characterization_gate.py` - including a real-difference-hidden-in-a-dict case that must still correctly fail).

---

## 15. A leaf module's own package `__init__.py` wasn't in the sandbox when nothing in the module itself imports it

**Found via:** real end-to-end run against the new `tests/fixtures/sample_multi_file_py2/` fixture (built to validate multi-file sandboxing - see bug #13's fix). `mypkg/helpers.py` has zero import statements of its own, so its dependency closure was correctly empty - but verifying it standalone still requires `import mypkg.helpers`, which needs `mypkg/__init__.py` to exist for Python 2 (no namespace-package support there; Python 3 tolerates the gap via implicit namespace packages, which is exactly why this only broke on the py2 side and looked like empty/silent output rather than an obvious error).

**Root cause:** `dependency_closure`'s BFS only follows import *edges* - a package's own `__init__.py` isn't an edge from a module that never imports it (the relationship runs the other way: `__init__.py` imports `helpers`, not vice versa), so it was never included even though it's structurally required for the module's own import path to resolve on py2.

**Fix:** `dependency_closure` now also walks the module's own ancestor directory chain (from its parent up to the sandbox root) and includes each real `__init__.py` found there - but only ones that genuinely exist in the ingested project; a true namespace package with no `__init__.py` anywhere stays exactly that, never synthesized.

**Status:** fixed, confirmed via direct re-run against the fixture that found it (`mypkg/helpers.py` now reaches genuine `VERIFIED_INFERRED`), unit-tested (`test_dependencies.py`, including a test that a genuine namespace package never gets an `__init__.py` invented for it).

---

## 14. A `lib2to3`-unfixable construct surviving into the transformed output produced a confusing raw-traceback message instead of a clean diagnosis

**Found via:** `aaronsw/html2text` @ `7a327b8` (expanded stress-test round, chosen specifically for having no test suite at all). `html2text.py` has an obscure Python 2.2-era compatibility shim - `if not hasattr(__builtins__, 'True'): True, False = 1, 0` - guarding against interpreters old enough to lack `True`/`False` as builtins. `lib2to3` has no fixer for this (a genuinely rare, ancient pattern), so it survives `deterministic_transform` completely unchanged. `find_semantic_findings`'s real `ast.parse()` then correctly rejects it - Python 3 made `True`/`False` reserved keywords, never valid assignment targets - but that raw `SyntaxError` propagated uncaught out of `find_semantic_findings`, through `_process_file`, and was only caught by `run_migration`'s generic per-file backstop (bug #3's crash-isolation fix), landing on `NEEDS_REVIEW` with a confusing bare exception string instead of a clear diagnosis.

**Root cause:** `deterministic_transform`'s own parse failures already have a clean, dedicated path (`DeterministicTransformError` → "could not parse original source: ..."), but there was no equivalent for the *output* of a successful transform still not being valid Python 3 - a real, distinct failure mode (lib2to3 successfully handled everything it *does* know about, but missed a construct that keeps the result syntactically invalid).

**Fix:** `_process_file` now catches `SyntaxError` around the `find_semantic_findings` call and reports `NEEDS_REVIEW` with a clear "deterministically-transformed source is not valid Python 3: ..." reason - same safe outcome as before (no crash, no false confidence - bug #3 already guaranteed that), just an honest, readable diagnosis instead of a raw traceback fragment.

**Status:** fixed, confirmed directly (reproduced the exact `SyntaxError` against the real extracted file before fixing), unit-tested (`test_transformed_source_syntax_error.py`). Not attempting to auto-fix this specific construct (e.g. via a new semantic-finding routing it to the Planner) - that's a real, separate, larger design task, not a quick diagnostic-clarity fix; noted as a possible future enhancement, not pursued now.

---

## 13. `__init__.py`-based packages can't be verified when the test suite imports them by package name - `from purl import URL`

**Found via:** `codeinthehole/purl` @ `1db2106` (part of the expanded stress-test round). `purl`'s whole implementation is a single `__init__.py`; its `tests.py` does `from purl import URL`, expecting `purl` to be a real importable package. Mode A's sandbox writes the module as a bare `__init__.py` sitting alone in a flat temp directory, with no `purl/` package directory wrapping it - so `from purl import URL` fails with `ModuleNotFoundError` on *both* interpreters, identically. (This is also what bug #12 was reproduced against - the identical failure this causes is the concrete case that motivated that fix.)

**Root cause:** Mode A/B/C's sandbox construction is file-at-a-time and package-name-unaware - it was designed for the common case of a plain `module.py` importable by its own filename, which doesn't hold for the equally common `package/__init__.py` layout where the package's *directory name* (not "`__init__`") is what real code imports.

**Important correction, found during the fix:** this exact repro turned out to be partly an artifact of `scripts/find_stress_test_candidates.py`'s own `extract()`, which flattened every file into one directory (`dest = out_dir / Path(f).name`) - the real `codeinthehole/purl` repo has genuine `purl/` and `tests/` subdirectories; `ingest()` itself never flattens anything. Fixed the extractor to preserve real relative paths before re-validating, so the "fixed" claim below is against the real nested structure, not a flattened stand-in.

**Fix:** built real multi-file dependency-aware sandboxing rather than a narrow `__init__.py` special case - `pipeline/dependencies.py` (AST-based local-import resolution, transitive closure, topological ordering for the repair phase), a shared `write_sandbox_tree` helper that writes a module and its closure at their real relative paths (preserving package structure) instead of flattening, and a two-phase orchestrator split (transform everything first, then repair in dependency order) so a dependent file can use its dependencies' freshest available candidate. Full design in the session's plan document; see bugs #15 and #16 for two further real bugs this surfaced and fixed along the way.

**Status:** fixed and confirmed via real re-extraction (fixed extractor) and re-run: `purl/__init__.py` now reaches genuine `VERIFIED_INFERRED` (real Mode C characterization tests, correctly resolving `from purl import URL`-style self-imports) instead of the original false `VERIFIED`. Not a Mode A pass specifically - `purl`'s real test suite lives in a top-level `tests/` directory sibling to the package (`tests/tests.py`), a distinct, real, still-open test-discovery convention gap (not what this bug was about) noted separately below as a known limitation, lower priority, same disposition as bug #6.

---

## 12. Both interpreters failing test collection in the exact same way was scored as a PASS

**Found via:** same `purl` run as bug #13, direct reproduction against the real sandbox container. `from purl import URL` (see #13) raised `ModuleNotFoundError` identically on both py2 and py3. pytest's `--junit-xml` represents a collection-level failure as one synthetic `<testcase>` entry (not zero, not per-real-test) - both sides produced the exact same single `ERROR` entry, which trivially "matched" under plain outcome comparison and reported `PASS` with a stdout-differs note, even though no real test assertion had run on either side.

**Root cause:** the existing zero-tests vacuous-pass guard (bug #2) only catches the *empty*-outcomes case. A collection-level error produces a *non-empty* outcome dict (one synthetic entry), so it slipped past that guard entirely - same underlying principle ("an empty or degenerate comparison must never read as agreement"), different mechanism than #2, so the existing check didn't generalize to it automatically.

**Fix:** `run_mode_a` now also checks whether *every* entry on both sides is `ERROR` - if so, treats it the same as the zero-tests case (`UNVERIFIED`, not `PASS`). Deliberately conservative: only triggers when literally everything on both sides is `ERROR`, so a real mix of genuine per-test outcomes plus an unrelated error entry is never swallowed by this guard.

**Status:** fixed, unit-tested (`test_verify_gates.py`) - both the vacuous-match case and a real-outcomes-mixed-with-an-error case that must NOT trigger the guard.

---

## 11. Test files themselves are py2 source too, but Mode A never migrates them - `__metaclass__` silently no-ops on Python 3

**Found via:** expanded stress-test round (`python-jsonschema/jsonschema` @ `f72f335`), the first library specifically chosen to exercise Mode A against real historical code again since bug #5's fix. `jsonschema.py` failed Mode A with `py3=?` for *every single test* - not a handful, all of them - which was itself the tell that something structural was wrong, not a real per-test behavior difference.

**Root cause, confirmed via direct reproduction (not guessed):** `run_mode_a` copies `test_source` completely unmodified to both the py2 and py3 sandboxes - only the *module under test* gets ShiftCode's migration applied, never the test file itself. `jsonschema`'s `tests.py` uses `__metaclass__ = ParametrizedTestCase` (Python 2's class-attribute metaclass syntax) to dynamically generate dozens of named test methods (`test_additionalItems_additional`, etc.) from a table of parameters. On Python 3, `__metaclass__ = X` is valid syntax but does *nothing at all* - it's just an inert class attribute; Python 3 needs `class Foo(Base, metaclass=X):` instead. No error, no crash - just an entirely different, disjoint set of test names collected on each side (py3 fell back to the 12 raw, unexpanded parametrized function names instead of the ~200 dynamically-generated ones). Confirmed directly: ran the real extracted `tests.py` against the real `shiftcode-py3-sandbox` container by hand - 12 tests collected, not the ~200 that ran on py2.

**Fix:** `behavior_gate.py`'s `run_mode_a` now runs the same zero-LLM `deterministic_transform` (mechanical `lib2to3` fixers only, exactly what already happens to the module under test) on `test_source` before writing it into the *py3* sandbox specifically - the py2 sandbox still gets the untouched original source, since that's the ground truth being compared against. `lib2to3`'s vendored `fix_metaclass` already handles this exact pattern mechanically and unambiguously; no LLM judgment needed.

**Status:** fixed and confirmed via direct reproduction against the real extracted `tests.py`: after the transform, `__metaclass__ = X` correctly becomes `class TestValidate(unittest.TestCase, metaclass=X):`, and the same real container now collects 209 tests (matching py2's universe) instead of 12 - surfacing 3 *genuine* remaining content differences (repr/ordering, not the metaclass artifact) instead of ~200 false mismatches. Unit-tested (`test_verify_gates.py`).

---

## 10. A test file with a name that doesn't fit `test_<name>.py` gets characterization-tested as if it were library code

**Found via:** same `jsonschema` run as bug #11 - `tests.py` (no underscore) doesn't match `is_test_file`'s `startswith("test_")` check anywhere in the pipeline, so it was treated as an ordinary library module: Mode C ran, guessing inputs for its own `test_xxx` methods as if they were real API, and it reached `VERIFIED_INFERRED` - a meaningless result for a file that's actually a test suite, not something anyone migrates "behavior" for in that sense.

**Root cause:** `is_test_file` was checked independently in two places (`pipeline/repair.py`'s `verify_candidate`, `pipeline/orchestrator.py`'s `_process_file`) with the same narrow `startswith("test_")` predicate - matching bug #7/#8's shape of "a real, common convention just wasn't in the recognized set."

**Fix:** one shared `is_test_filename()` predicate in `repair.py` (`test_<name>.py`, `tests.py`, `test.py` - the same three conventions `_discover_test_pairs` already recognizes for *pairing* a module with its tests, see below), used everywhere a file needs to be recognized as "this is a test file, not something to characterization-test."

**Status:** fixed, unit-tested (`test_is_test_filename.py`).

---

## 9. `_discover_test_pairs` only recognized `test_<name>.py`, missing the equally common single `tests.py`/`test.py` convention

**Found via:** same `jsonschema` run - `jsonschema.py` has a real, human-authored `tests.py`, but the `test_<name>.py` naming check (`test_jsonschema.py`) never matched, so Mode A never even ran for the module that most needed it (the whole point of picking this library was to exercise Mode A against real historical code again after bug #5's fix). Also affects `purl/__init__.py` + `tests.py` from the same stress-test round.

**Root cause:** `_discover_test_pairs` only ever checked for `test_<module-filename>.py`, missing the well-established convention (used by both `jsonschema` and `purl`, two independent real libraries) of a single `tests.py`/`test.py` testing a small package's one real module directly.

**Fix:** added a scoped fallback - when the primary `test_<name>.py` pattern doesn't match, check for a generic `tests.py`/`test.py` in the same directory, but *only* when this file is the sole real (non-test, non-`setup.py`/`conf.py`) module in that directory. Deliberately narrow: a multi-file package's unrelated files must never each get paired with someone else's test suite just because a shared `tests.py` happens to exist nearby.

**Status:** fixed, confirmed directly against the real extracted `jsonschema`/`purl` directories (both now pair correctly), unit-tested (`test_discover_test_pairs.py`).

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
