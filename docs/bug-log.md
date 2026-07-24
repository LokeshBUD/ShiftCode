# Bug log

Real bugs found in ShiftCode itself, mostly via stress-testing against real
external code (not the bundled fixtures) — the whole point of stress testing
is to find the class of bug that a hand-built fixture won't surface. Each
entry: what was wrong, how it was found, the root cause, and what now catches
this class of bug going forward (a code fix, a new gate, or a new agent).

Index below, newest first — jump to `#N` for the full write-up (found via,
root cause, fix, status). Full entries follow in the same order.

| # | Bug | Status |
|---|---|---|
| [36](#36-mode-c-discarded-stderr-entirely-a-transitive-import-crash-on-one-side-was-indistinguishable-from-a-genuine-behavioral-difference) | Mode C discarded stderr entirely — a transitive import crash looked identical to a real behavioral difference | Fixed |
| [35](#35-a-file-with-zero-judgment-requiring-findings-got-exactly-one-verification-attempt-no-retry-even-on-a-genuinely-fixable-failure) | Zero-plan-step files got one verification attempt, no retry even on a fixable failure | Fixed |
| [34](#34-mode-bs-stdoutstderrexit-code-equality-check-false-failed-when-python-3-emitted-an-interpreter-level-warning-python-2-doesnt) | Mode B false-failed on a Python-3-only interpreter warning (SyntaxWarning noise) | Fixed |
| [33](#33-_values_equals-non-literal-fallback-compared-default-objectgenerator-reprs-verbatim-embedding-a-real-memory-address-that-can-never-match-across-two-separate-interpreter-processes) | `_values_equal` compared reprs with raw memory addresses baked in — can never match across processes | Fixed |
| [32](#32-mode-c-only-ever-characterized-top-level-functions-any-class-only-file-all-public-logic-in-methods-got-nothing-to-characterize-at-all) | Mode C only characterized top-level functions — class-only files got nothing tested at all | Fixed |
| [31](#31-the-dead-py22-truefalse-builtin-shim-bug-14-got-a-clear-diagnosis-but-was-never-actually-removed-html2textpy-stayed-needs_review-forever-on-this-construct-alone) | Dead py2.2 `True`/`False` shim (bug #14) got a diagnosis but was never actually removed | Fixed |
| [30](#30-dependency-closure-resolution-parsed-raw-possibly-py2-only-source-silently-losing-every-import-edge-for-any-importer-using-common-py2-only-syntax-like-a-bare-print-statement) | Dependency-closure resolution silently lost import edges for any importer using a bare `print` statement | Fixed |
| [29](#29-mode-rs-recording-wire-format-silently-coerced-non-string-dict-keys-and-collapsed-the-tuplelist-distinction) | Mode R's recording wire format silently coerced dict keys and collapsed tuple/list distinction | Fixed |
| [28](#28-testcasefunction_name-had-no-safety-validation-at-all-spliced-directly-into-driver-script-source-code) | `TestCase.function_name` had no safety validation — spliced directly into driver-script source | Fixed |
| [27](#27-import-pipes-produced-zero-findings-removed-in-python-313-with-no-fixer-anywhere-crashing-the-whole-modules-import) | `import pipes` produced zero findings — removed in Python 3.13, crashed the whole module | Fixed |
| [26](#26-non-package-modules-never-checked-a-sibling-test-singular-directory-only-tests-plural) | Non-package modules never checked a sibling `test/` (singular) directory, only `tests/` | Fixed |
| [25](#25-classes-defining-__cmp__-produced-zero-findings-python-3-silently-never-calls-it-more-dangerous-than-bare-cmp-calls) | Classes defining `__cmp__` produced zero findings — Python 3 silently never calls it | Fixed |
| [24](#24-non-package-modules-never-checked-a-sibling-top-level-tests-directory-or-a-private-modules-underscore-stripped-test-file-name) | Non-package modules never checked a sibling top-level `tests/` dir or underscore-stripped test names | Fixed |
| [23](#23-inspectgetargspec-produced-zero-findings-removed-in-python-311-with-no-fixer-anywhere-so-it-was-never-caught) | `inspect.getargspec(...)` produced zero findings — removed in Python 3.11, never caught | Fixed |
| [22](#22-mode-as-dependency-closure-never-included-the-paired-test-files-own-local-imports-only-the-modules) | Mode A's dependency closure never included the paired test file's own local imports | Fixed |
| [21](#21-dependency_closures-ancestor-__init__py-inclusion-bug-15-added-those-files-to-the-sandbox-but-never-traced-their-own-imports) | Ancestor `__init__.py` inclusion (bug #15) added files to the sandbox but never traced their own imports | Fixed |
| [20](#20-mode-as-sandbox-never-wrapped-__init__py-in-a-package-directory-when-the-migration-root-itself-is-the-package-test-imports-failed-identically-on-both-interpreters) | Mode A's sandbox never wrapped `__init__.py` when the migration root itself is the package | Fixed |
| [19](#19-bare-cmpa-b-builtin-calls-produced-zero-findings-removed-in-python-3-with-no-fixer-anywhere-so-it-was-never-caught) | Bare `cmp(a, b)` builtin calls produced zero findings — removed in Python 3, never caught | Fixed |
| [18](#18-find_lib2to3_findings-had-no-exception-handling-around-its-own-parse-call-a-raw-lib2to3-parseerror-crashed-past-deterministic_transforms-already-correct-handling) | `find_lib2to3_findings` had no exception handling — a raw `ParseError` crashed past existing handling | Fixed |
| [17](#17-_discover_test_pairs-doesnt-recognize-a-top-level-tests-directory-sibling-to-the-package-it-tests) | `_discover_test_pairs` didn't recognize a top-level `tests/` directory sibling to the package | Fixed |
| [16](#16-mode-c-compared-raw-repr-strings-which-is-sensitive-to-dictset-ordering-differences-that-arent-real-behavior-differences) | Mode C compared raw `repr()` strings — sensitive to dict/set ordering differences that aren't real | Fixed |
| [15](#15-a-leaf-modules-own-package-__init__py-wasnt-in-the-sandbox-when-nothing-in-the-module-itself-imports-it) | A leaf module's own package `__init__.py` wasn't in the sandbox when nothing imports it directly | Fixed |
| [14](#14-a-lib2to3-unfixable-construct-surviving-into-the-transformed-output-produced-a-confusing-raw-traceback-message-instead-of-a-clean-diagnosis) | A `lib2to3`-unfixable construct surviving into the output produced a confusing raw traceback | Fixed |
| [13](#13-__init__py-based-packages-cant-be-verified-when-the-test-suite-imports-them-by-package-name-from-purl-import-url) | `__init__.py`-based packages couldn't be verified when the test suite imports them by package name | Fixed |
| [12](#12-both-interpreters-failing-test-collection-in-the-exact-same-way-was-scored-as-a-pass) | Both interpreters failing test *collection* identically was scored as a PASS | Fixed |
| [11](#11-test-files-themselves-are-py2-source-too-but-mode-a-never-migrates-them-__metaclass__-silently-no-ops-on-python-3) | Test files are py2 source too, but Mode A never migrated them — `__metaclass__` silently no-ops on py3 | Fixed |
| [10](#10-a-test-file-with-a-name-that-doesnt-fit-test_namepy-gets-characterization-tested-as-if-it-were-library-code) | A test file with an unrecognized name got characterization-tested as if it were library code | Fixed |
| [9](#9-_discover_test_pairs-only-recognized-test_namepy-missing-the-equally-common-single-testspytestpy-convention) | `_discover_test_pairs` only recognized `test_<name>.py`, missing the `tests.py`/`test.py` convention | Fixed |
| [8](#8-unicodedatanormalizeencode-silently-becomes-bytes-in-python-3-breaking-every-later-string-operation) | `unicodedata.normalize(...).encode(...)` silently becomes `bytes` in Python 3 | Fixed |
| [7](#7-from-types-import-x-bare-legacy-type-name-has-no-python-3-equivalent-and-produces-zero-findings-so-its-never-fixed) | `from types import X` (legacy type name) has no py3 equivalent and produced zero findings | Fixed |
| [6](#6-files-with-zero-needs_llm-findings-get-zero-repair-attempts-even-on-a-real-verification-failure) | Files with zero `needs_llm` findings got zero repair attempts, even on a real fixable failure | Fixed — see #35 |
| [5](#5-sandbox-images-have-no-dependencies-installed-blocks-most-real-code) | Sandbox images had no dependencies installed — blocked most real code | Fixed |
| [4](#4-diagnostic-clarity-mode-a-cant-distinguish-outcomes-differ-from-one-side-never-produced-parseable-output-at-all) | Mode A couldn't distinguish "outcomes differ" from "one side never produced parseable output" | Subsumed by #5 |
| [3](#3-transient-networkapi-errors-crash-the-entire-run-not-just-one-file) | Transient network/API errors crashed the entire run, not just one file | Fixed |
| [2](#2-mode-a-vacuous-pass-on-zero-discovered-tests) | Mode A vacuous pass on zero discovered tests | Fixed |
| [1](#1-lib2to3s-fix_long-corrupts-identifiers-that-shadow-the-long-builtin) | `lib2to3`'s `fix_long` corrupts identifiers that shadow the `long` builtin | Fixed |

Format below: newest first, full write-up per entry.

---

## 36. Mode C discarded stderr entirely - a transitive import crash on one side was indistinguishable from a genuine behavioral difference

**Found via:** finally diagnosing `argcomplete/completers.py`'s `EnvironCompleter` "mismatch" - flagged as an open, undiagnosed lead across 3 separate stress-test rounds (entries 13, 15, 16 in `docs/stress-test-log.md`) without ever being root-caused. `py2` returned a real generator repr; `py3` returned a bare empty string, with no `RESULT:`/`EXCEPTION:` prefix at all - looked exactly like the function itself behaved differently.

**Root cause:** it wasn't a real difference at all. `argcomplete/completers.py` is a package submodule (`argcomplete.completers`), so importing it also imports `argcomplete/__init__.py` first - real Python import semantics. That `__init__.py`'s own final candidate still had the *unresolved* `import pipes` repair failure documented in `docs/bug-log.md` (a confirmed, reproducible model-capability ceiling, not fixable by raising `max_repair_attempts` - see entry 16 in `docs/stress-test-log.md`). On Python 3, importing `argcomplete.completers` transitively crashed at `argcomplete/__init__.py`'s own `import pipes` line, before `EnvironCompleter` was ever called - a real `ModuleNotFoundError`, with its traceback going to stderr. `_run_case_in` (`characterization_gate.py`), reused by Mode R too, only ever read `proc.stdout` - stderr was silently discarded, so the crash was invisible in the report; all that showed was an empty stdout that read exactly like "the function returns something different on py3."

**Fix:** `_run_case_in` now returns `(stdout, stderr)` instead of just `stdout`. `run_mode_c`'s mismatch message includes whichever side's stderr when that side's stdout was empty (the specific shape a crash-before-any-print produces) - narrow and additive, only fires in exactly that situation, never changes the actual PASS/FAIL comparison logic itself (still stdout-kind-based, unchanged). `recording_gate.py` (Mode R, which reuses the same helper) updated to match the new return shape.

**Status:** fixed, unit-tested (a scripted crash-shaped case - empty stdout, real stderr - confirmed to surface in the mismatch detail), confirmed live: reproduced the exact real failure by hand against the real `argcomplete` extraction, tracing it through `argcomplete/__init__.py`'s actual final candidate source to the real, unresolved `import pipes` line. `EnvironCompleter` itself has no real py2/py3 behavior difference - confirmed directly by running its driver script standalone, bypassing the broken import chain: identical generator-returning output on both interpreters (correctly normalized as equal by bug #33's fix). No further code changes needed for `completers.py` itself; the underlying `import pipes` repair failure remains a documented, accepted model-capability limit, not something this fix (or any further ShiftCode change) resolves.

---

## 35. A file with zero judgment-requiring findings got exactly one verification attempt, no retry even on a genuinely fixable failure

**Found via:** noted as a real, still-open gap ("Known limitations" in README.md, and this entry's own placeholder) since early in the project - closed now as part of a deliberate pass through every remaining open item once the 3 rule-based fixes (#30-#33) landed.

**Root cause:** `migrate_file`'s fast path for a file with an empty `plan.steps` (nothing the Planner flagged as needing judgment) verified the deterministic-only candidate once, then returned immediately on ANY failure - including a genuinely actionable one (a real behavior/determinism mismatch, or even a syntax problem in the deterministic output itself), never giving the Auditor a chance to diagnose it or the Refactorer a chance to fix it. "Nothing the Planner flagged" only means lib2to3's own fixers didn't know to flag anything - it doesn't mean nothing is actually wrong; a real behavior gate can still fail for reasons the deterministic layer had no way to see coming.

**Fix:** `migrate_file` (`pipeline/repair.py`) now runs one unified loop instead of two separate code paths - the free first check (no Refactorer call, zero LLM cost) still happens exactly as before, but only stops immediately when the result is `UNVERIFIED` (a structurally unverifiable environment - no py2 runtime, no test suite/entry point/characterization - where retrying genuinely cannot help) or already passing. A `RETRY`-classified result (syntax/behavior/determinism actually failed) now falls through into the exact same bounded Auditor↔Refactorer loop every other file gets, seeded with an Auditor diagnosis of that first failure. This wasn't new machinery to build - the Refactorer's own prompt already renders `"(no plan steps - nothing for you to change)"` for an empty plan and explicitly instructs treating Auditor hints as "authoritative corrections to your previous attempt"; that combination was already designed to make sense together, just never reachable.

**Status:** fixed, unit-tested (a deliberately-broken `deterministic_output` with an empty plan now correctly retries and recovers, and the untouched UNVERIFIED-immediate-stop case is confirmed to still record zero repair-attempt history, byte-for-byte the same as before), confirmed live: a real re-run against `toolz` shows `itertoolz/core.py` now genuinely exhausting 3 repair attempts on a real Mode A mismatch instead of giving up after the first free check, while files that hit a genuinely unverifiable environment (`test_core.py`, `test_recipes.py`, `test_curried.py` - no standalone entry point) correctly still stop immediately with no wasted attempts.

---

## 34. Mode B's stdout/stderr/exit-code equality check false-failed when Python 3 emitted an interpreter-level warning Python 2 doesn't

**Found via:** re-validating `html2text.py` after fixing bug #31 (the dead shim removal) - the file no longer hit that `SyntaxError`, but still failed Mode B, with identical stdout and exit code (0/0) on both sides.

**Root cause:** `run_mode_b` (`behavior_gate.py`) required `stdout`, `stderr`, and `returncode` to match exactly for a PASS. Python 3 emits interpreter-level warnings (here: a `SyntaxWarning` for an invalid string escape sequence, `'\s+'`) on stderr at import/compile time that Python 2 simply never emits - real, harmless interpreter noise, unrelated to whether the migrated code actually behaves the same. A behaviorally-identical migration could fail Mode B purely because Python 3 itself got chattier, not because anything about the migration was wrong.

**Fix:** new `_strip_interpreter_warning_noise` helper (`behavior_gate.py`) - regex-matches Python's own `warnings.formatwarning()` output shape (`"{file}:{line}: {Category}: {message}"` plus an optional 2-space-indented echo of the source line) for a fixed, narrow list of built-in warning categories (`SyntaxWarning`, `DeprecationWarning`, etc.), and strips only those blocks before the stderr equality check. Deliberately narrow - a real error message a program itself prints to stderr doesn't match this shape and still causes a real `FAIL`. The raw, unstripped stderr is still shown in full in the `FAIL` detail string for debugging - only the PASS/FAIL decision itself uses the normalized version.

**Status:** fixed, unit-tested against the exact real captured stderr text from the live run that found this (`test_run_mode_b_passes_when_only_stderr_differs_by_a_py3_warning`), confirmed a real difference hidden past the noise is still caught (`test_run_mode_b_still_fails_on_a_real_stderr_difference`). `html2text.py` itself doesn't yet reach a verified tier even with this fix - a live re-run surfaced a further, unrelated, genuine issue (the module needs `sgmllib3`, a Python 3 port of a removed stdlib module, which isn't provisioned into the sandbox) - a real dependency gap, not a comparison bug, and likely not fixable by ShiftCode itself (same category as the 9 "not fixable by either lever" files from the earlier breakdown).

---

## 33. `_values_equal`'s non-literal fallback compared default object/generator reprs verbatim, embedding a real memory address that can never match across two separate interpreter processes

**Found via:** the first real class-method characterization run against blinker's actual `Signal.receivers_for`/`signal()` (see #32) - every case mismatched, all with the exact same shape: `py2 returned '<... object at 0xAAA>', py3 returned '<... object at 0xBBB>'`, i.e. identical content, different addresses.

**Root cause:** `_values_equal` (`characterization_gate.py`) falls back to plain string comparison when a repr isn't `ast.literal_eval`-parseable (e.g. a custom object's default `__repr__`, or a generator). Default object repr embeds the object's real memory address - which was *never* going to match between the py2 sandbox process and the separate py3 sandbox process, regardless of whether the migration is correct. Separately, Python 3 added the generator's qualified name to its own repr (`<generator object Signal.receivers_for at 0x...>`) that Python 2's repr never had (`<generator object receivers_for at 0x...>`) - a real repr-*format* change between language versions, not a behavior difference. Both were pure false-mismatch noise, unrelated to whether the migrated code actually behaves the same. This almost certainly affected any earlier Mode C run characterizing a function/method that returns a plain object or a generator - it simply had no real-world trigger until a case shaped that way got run.

**Fix:** new `_normalize_nonliteral_repr` helper, applied on both sides before the string-equality fallback in `_values_equal` - collapses any `<generator object ... at 0x...>` to a single placeholder, and replaces every remaining hex address with a fixed placeholder. Only touches the non-literal fallback path; the literal-value comparison (the vast majority of real correctness signal) is untouched. Confirmed both that real noise (address-only, and generator-qualifier-only differences) is now ignored, and that a genuine difference hidden past the noise (e.g. a different literal payload after the address) is still caught.

**Status:** fixed, unit-tested, re-confirmed live: blinker/base.py went from 4/10 to 6/6 Mode C cases passing and `VERIFIED_INFERRED` once this landed.

---

## 32. Mode C only ever characterized top-level functions - any class-only file (all public logic in methods) got nothing to characterize at all

**Found via:** two real stress-test files landing on `NEEDS_REVIEW` purely because `top_level_function_defs` structurally excludes classes by design (`call_sites.py`'s own MVP-scope docstring) - `blinker/base.py` (`Signal.receivers_for` and friends) and `argcomplete/my_argparse.py`.

**Root cause:** characterizing a method requires two things a plain function doesn't: an instance to call it on (constructor args for `ClassName(...)`), and the method call itself (`instance.method_name(...)`) - genuinely more design surface than a direct `_mod.function_name(*args)` call, so it was explicitly deferred at MVP time.

**Fix:** `TestCase` gained two optional fields, `class_name`/`constructor_args_literal` (`None` for a plain function case - byte-for-byte the same behavior as before) - reused instead of a parallel model hierarchy, since a method case only needs 2 extra pieces of data over a function case. New `top_level_class_defs`/`class_init`/`public_methods` (`call_sites.py`) discover public classes, their `__init__` (if any), and their public methods (same "not underscore-prefixed" filter as functions - dunders, including `__call__`, excluded by the same rule). `_build_driver_script` (`characterization_gate.py`) gained a branch: when `class_name` is set, construct `_inst = _mod.ClassName(*ctor_args)` then call `_inst.method_name(*args)`, instead of calling the module-level function directly. The Characterization prompt now renders a method's class `__init__` alongside the method itself, and instructs the model to propose constructor args the same way it proposes any other arguments. `_neighbor_variants` (the differential-fuzzing shrinking analog) also had to carry `class_name`/`constructor_args_literal` through, or a method's boundary-nudged variants would have silently probed the wrong thing (calling the method name as if it were a top-level function).

Differential fuzzing (`propose_fuzz_seeds`/`FunctionSeedPlan`) deliberately stays function-only for now - methods always get the plain (non-fuzzed) `propose_tests` path regardless of `characterization_fuzz_cases`, a real scope cut, not an oversight.

**Status:** fixed, unit-tested, confirmed live: `blinker/base.py` went from `NEEDS_REVIEW` (nothing to characterize) to `VERIFIED_INFERRED` (6/6 cases, after #33's fix also landed). `argcomplete/my_argparse.py` remains `UNVERIFIED` - but now for an honest, correct reason: its one class (`IntrospectiveArgumentParser`) has exactly one method, `_parse_known_args`, which is genuinely private (an internal override of argparse's own API) and correctly excluded, not a gap in this fix. The underlying machinery is confirmed working on a second, independent real file too: `argcomplete/completers.py`'s `ChoicesCompleter` class is now discovered (though its only method, `__call__`, is a dunder and correctly excluded by the same filter).

---

## 31. The dead py2.2 `True`/`False` builtin shim (bug #14) got a clear diagnosis but was never actually removed - html2text.py stayed `NEEDS_REVIEW` forever on this construct alone

**Found via:** scoping out a real fix for the exact construct bug #14 diagnosed (`if not hasattr(__builtins__, 'True'): True, False = 1, 0`) instead of leaving it at "clear error message" permanently, per the plan to address every rule-based fix identified from the 14 open `NEEDS_REVIEW` files.

**Root cause:** the construct is unconditionally dead code on every real interpreter (py2.3+ and all of py3 always have `True`/`False`, so the guarded body never executes) - but it's a genuine Python 3 `SyntaxError` (`True`/`False` are reserved keywords, never valid assignment targets), and it survives `deterministic_transform` unchanged (lib2to3 has no fixer for it). That makes it structurally unlike every other detector in `analyze.py`: those all walk an AST that already parsed successfully; here there's no tree to walk until this exact line is gone, since `ast.parse()` itself fails first.

**Fix:** new `strip_dead_true_false_shim` (`analyze.py`) - a pre-parse *textual* strip (regex-matched, single-line-form only, tolerant of quote style), not an AST-based detector, following the one existing precedent for this shape of fix: `ingest.py`'s own trailing-newline normalization. Runs before `find_lib2to3_findings`/`deterministic_transform`, mutating `original_source` in place and emitting a `needs_llm=False` `Py2Finding` so the report stays honest about what happened. The matched line is replaced with a blank line (not deleted outright), so every other line number in the file stays correct.

**Status:** fixed, unit-tested, confirmed live: `html2text.py` no longer hits the `SyntaxError` backstop at all - it now proceeds into a real repair loop. It still doesn't fully verify, but for a completely different, unrelated reason (see the Mode B stderr-comparison gap noted in stress-test-log.md - flagged, not yet fixed, a separate design decision).

---

## 30. Dependency-closure resolution parsed raw (possibly py2-only) source, silently losing every import edge for any importer using common py2-only syntax like a bare `print` statement

**Found via:** re-validating `docopt/example.py` (originally attributed to "Mode B's single-file isolation," before any dependency-closure machinery existed at all - see stress-test-log.md). After bugs #13/#15/#21/#22 built real multi-file closures, `example.py` *still* failed with `ImportError: No module named docopt` even though `docopt.py` sits right next to it and `resolve_local_imports` should have found `from docopt import docopt`.

**Root cause:** `resolve_local_imports` (`dependencies.py`) called `ast.parse(file_unit.original_source)` - the raw, untouched py2 source - to find import statements. `example.py`'s original source has `print options` (a Python 2 print *statement*), which is a `SyntaxError` under Python 3's grammar. The function's own `except SyntaxError: return []` degraded this to *zero* import edges rather than crashing - safe, but silently wrong in scope: the `from docopt import docopt` line was never reached because parsing failed before that point. Any importer file containing print statements, `except E, e:`, or similar py2-only syntax would have this same silent gap, regardless of which library it belonged to.

**Fix:** `resolve_local_imports` now prefers `file_unit.deterministic_output` (the lib2to3-transformed, real py3-parseable candidate - already computed and available for every file by the time this runs, since Phase A completes for every file before Phase B's closure computation begins) over `original_source`, falling back to `original_source` only when `deterministic_output` is `None` (e.g. a synthetic `FileUnit` in a test). Confirmed live: `docopt/example.py`'s py2-side sandbox run went from a raw `ImportError` to real, correct output (`Options(count=False, ...)` etc.) once the sibling import actually resolved.

**Status:** fixed, confirmed live, zero unit-test regressions (275/275 unchanged before this fix, still 275/275 after). `example.py` itself still doesn't reach a verified tier - blocked by an unrelated, pre-existing issue (`docopt.py`'s own Refactorer repair corrupting indentation while reverting a `long`→`int` mechanical-fixer collision, reproducibly identical across repair attempts and across separate runs - a model-repair-quality gap, not a closure gap; candidate for the model-limit investigation, not this fix).

---

## 29. Mode R's recording wire format silently coerced non-string dict keys, and collapsed the tuple/list distinction

**Found via:** stress-testing Mode R for the first time against a real third-party library (`pytoolz/toolz`'s `dicttoolz.core.merge`), not the small hand-written example it shipped with. Recorded real calls like `merge({1: 'one'}, {2: 'two'})` under real Python 2 - the recording on disk came back as `{"1": "one", "2": "two"}`, a genuinely different dict (string keys, not int keys) than the real value that was actually returned.

**Root cause:** the original recorder (`recorder.py`) serialized args/kwargs/result with `json.dumps` on the raw Python values. JSON has no non-string object-key type - `json.dumps({1: 'one'})` silently stringifies the key with no error or warning. The same design also silently collapsed the tuple/list distinction (a function returning a real tuple would round-trip as a JSON array, indistinguishable from a list). Either would cause a **false mismatch** at replay time - the candidate could be perfectly correct and still get flagged as broken, purely because of the recording format's own lossy encoding, nothing to do with any real behavior difference.

**Fix:** both `recorder.py` and `recording_loader.py` now use `repr()` (validated by round-tripping through `ast.literal_eval`, the same check this codebase's existing `args_literal`/`args_repr` machinery already uses everywhere else) instead of raw JSON values for the args/kwargs/result fields - only the outer envelope (function name, module, timestamp) is plain JSON. `repr()`/`literal_eval` round-trips losslessly for anything in the literal-safe universe, so this can't lose key-type or tuple/list information the way JSON structurally can. Confirmed via a real regression test (recording an int-keyed dict, confirming the keys come back as real ints) and re-validated live against the real `toolz` recording: 5/5 real recorded `merge()` calls now correctly match toolz's real implementation, and 4/5 correctly fail against a deliberately broken candidate (the 5th - a single-dict merge - is correctly unaffected by the specific bug introduced, real per-case signal, not a blanket failure).

---

## 28. `TestCase.function_name` had no safety validation at all - spliced directly into driver-script source code

**Found via:** building Mode R's `recording_loader.py` (docs/verification.md), which needed to validate `function_name` for a genuinely new untrusted input (a recording `.jsonl` file, possibly produced on a different machine at an earlier time). Adding that check surfaced that the *pre-existing* LLM-facing path - `TestCase.function_name`, used by every Mode C case regardless of origin (`propose_tests`, `propose_fuzz_seeds`/`expand_function_seeds`) - had never had an equivalent check at all, since it had only ever been implicitly trusted as coming from an LLM response.

**Root cause:** `characterization_gate.py`'s `_build_driver_script` splices `case.function_name` directly into driver-script SOURCE CODE (`f"_mod.{case.function_name}(*_args)"`). `args_literal` is defended by `ast.literal_eval`'s structural inability to evaluate a function call or attribute access - but nothing equivalent ever existed for `function_name`. A manipulated or malicious model response (or a future untrusted input path along these same lines) putting something like `"x); __import__('os').system('...'); ("` in this field would have spliced straight into real, executable driver-script code.

**Fix:** a `field_validator` directly on `TestCase.function_name` (`models/agent_io.py`) - enforces a plain identifier (`^[A-Za-z_][A-Za-z0-9_]*$`), matching what a real top-level function's name always structurally is. Centralized at the model level rather than scattered per-gate checks, so it applies transitively to every `TestCase`, however it was constructed (LLM output, fuzz expansion, or the new recording-derived path) - can never reject a legitimate case, only an injection attempt. Confirmed via a real injection string (`"x); __import__('os').system('echo pwned'); ("`) correctly rejected at construction time.

---

## 27. `import pipes` produced zero findings - removed in Python 3.13 with no fixer anywhere, crashing the whole module's import

**Found via:** `kislyuk/argcomplete` @ `f6a7bf4`, same run as #26. Once #26's test-pairing fix routed `argcomplete/__init__.py` to real Mode A, it hit `ModuleNotFoundError: No module named 'pipes'` during test collection - the module imports `pipes` as part of a multi-name `import` statement, crashing the ENTIRE module's import (not just wherever `pipes` is used), the same "one missing symbol takes down everything" failure shape as bug #7's `types.UnicodeType`.

**Root cause:** `pipes` (shell-command utilities) was deprecated in Python 3.11 and removed entirely in 3.13 - a stdlib module removal, not a syntax difference, so `lib2to3` was never going to have a fixer for it (confirmed: no reference anywhere in the vendored fixer set), and this project's own scanner had no detection for it either.

**A real, separate finding while diagnosing this:** the only two real references to `pipes.quote(...)` in this specific file are both inside commented-out code - the import itself was genuinely dead weight here, not a case needing the `shlex.quote` replacement. The new detector's guidance covers both cases (replace `pipes.quote` with `shlex.quote` if actually used; just remove the import if not), since a detector can't assume which applies without a human/LLM reading the specific file.

**A real Auditor misdiagnosis observed during repair, left unfixed (LLM judgment limitation, not a code defect):** the Refactorer's first attempt correctly removed the dead `pipes` import per the new finding's guidance, surfacing a genuinely separate, real test failure. The Auditor then misread that failure and told the Refactorer to "restore the pipes import" - which re-introduced the exact `ModuleNotFoundError` this fix targets, and the repair loop exhausted its budget stuck on that mistaken hint. `NEEDS_REVIEW` is the correct, honest outcome here (same category as `docopt`'s documented LLM non-determinism, entry 1) - not something a code-level fix addresses; this is a diagnosis-quality question, not a ShiftCode gap.

**Fix:** new `_find_pipes_module_imports` in `analyze.py`, registered in `find_semantic_findings`. Same posture as #7/#23 - `needs_llm=True`, detection is deterministic and complete regardless of the repair loop's eventual success on any specific file.

---

## 26. Non-package modules never checked a sibling `test/` (singular) directory, only `tests/` (plural)

**Found via:** same `kislyuk/argcomplete` run as #27. `argcomplete/__init__.py` has a real, substantive 43-line test suite (`test/test.py`, testing the whole package via `from argcomplete import *`) that was never paired for Mode A at all - the directory is named `test` (singular), and every sibling-tests-directory candidate added by bug #24's fix only ever checked `tests` (plural).

**Root cause:** the directory-naming axis was never generalized - bug #9 already fixed the equivalent *filename* variance (`tests.py` vs `test.py`), but the *directory name* variance (`tests/` vs `test/`) was a separate, un-covered axis until this run surfaced a real case of it.

**Fix:** `_discover_test_pairs` (`orchestrator.py`) now tries both `tests` and `test` as the sibling-directory name everywhere a directory-based candidate is built (`_TEST_DIR_NAMES = ("tests", "test")`), for both the package (`__init__.py`) and non-package candidate paths. Confirmed live: `argcomplete/__init__.py` now correctly routes to Mode A (previously fell through to Mode C/nothing).

---

## 25. Classes defining `__cmp__` produced zero findings - Python 3 silently never calls it, more dangerous than bare `cmp()` calls

**Found via:** `jek/blinker` @ `c06a79a`, same run as #24. Once #24's test-pairing fix routed `_saferef.py` to real Mode A, it hit a genuine `FAIL`: `_saferef.py` defines `__cmp__` (Python 2's single-method comparison protocol). Confirmed via the real Refactorer/Auditor loop: the Auditor only diagnosed the full scope of the real fix (rewrite as `__eq__`/`__lt__`, not just fix the bare `cmp()` calls inside `__cmp__`'s own body) reactively, on the third and final attempt - and even then, the Refactorer exhausted all 3 attempts without a correct fix. `NEEDS_REVIEW` is the honest, correct outcome for a genuinely hard rewrite (must also preserve `__hash__`, since Python 3 sets it to `None` automatically on any class defining `__eq__` without it - confirmed real, `test_ShortCircuit` uses instances as dict keys) - not every `needs_llm=True` finding is expected to auto-resolve within the repair budget.

**Root cause:** a stdlib/language protocol removal with no exception raised at all (Python 3 doesn't error on a `__cmp__`-only class - comparisons just silently fall back to identity, or raise a generic `TypeError` depending what's attempted) - a real, more dangerous case than bare `cmp()` calls (#19), and no `lib2to3` fixer exists for it either.

**Fix:** new `_find_dunder_cmp_definitions` in `analyze.py`, registered in `find_semantic_findings` - flags `def __cmp__(...)` upfront with a complete finding (rich-comparison methods needed, plus the `__hash__` preservation trap), so the Planner gets the full scope from the start instead of the Auditor discovering it late, one wasted repair attempt at a time. Doesn't guarantee the fix succeeds (that's a real LLM-capability question, out of scope for a detector), but meaningfully improves the diagnostic signal quality regardless of outcome.

---

## 24. Non-package modules never checked a sibling top-level `tests/` directory, or a private module's underscore-stripped test-file name

**Found via:** same `jek/blinker` run as #25. `blinker/_saferef.py` and `blinker/_utilities.py` both have real, substantive test files (`tests/test_saferef.py`, 117 lines; `tests/test_utilities.py`) - but neither got paired for Mode A at all, silently falling back to Mode C (weaker evidence) or nothing.

**Root cause:** `_discover_test_pairs`'s non-`__init__.py` candidate list only ever checked inside the module's own directory (`test_<name>.py`, `tests/test_<name>.py`) - the sibling-top-level-`tests/`-directory candidate (already added for `__init__.py` files, bug #17) was never generalized to arbitrary modules. Separately, the candidate filename was always the module's literal basename - a private module's test file conventionally drops the leading underscore (`test_saferef.py`, not `test__saferef.py`, for `_saferef.py`), which the candidate list never tried.

**Fix:** `_discover_test_pairs` (`orchestrator.py`) now also checks `<module's parent's parent>/tests/test_<name>.py` for every module (not just packages), and tries both the module's exact basename and, for single-leading-underscore names, the stripped variant (`__dunder__`-style names are explicitly excluded from stripping). Confirmed live: `_saferef.py` and `_utilities.py` both now correctly route to Mode A; `_utilities.py` reached real `VERIFIED` (2/2) as a direct result, upgraded from its previous `VERIFIED_INFERRED`-via-fuzzing result.

---

## 23. `inspect.getargspec(...)` produced zero findings - removed in Python 3.11 with no fixer anywhere, so it was never caught

**Found via:** `pytoolz/toolz` @ `498fefa`, same run as #21/#22. Once those two dependency-closure fixes let `toolz/curried.py`'s real test suite actually run, it failed for a genuine, different reason: `curried.py` uses `inspect.getargspec(f).args` to inspect a function's arity, which raises `AttributeError: module 'inspect' has no attribute 'getargspec'` on this Python 3 (removed in 3.11) - confirmed via `grep` across the vendored fixer set that no `lib2to3` fixer references it, and this project's own semantic-findings scanner had no detection for it either, same shape as #7 and #19.

**Root cause:** a stdlib API removal, not a syntax difference - exactly the class of bug `lib2to3` structurally can't catch and nothing in `analyze.py` was watching for yet.

**Fix:** new `_find_inspect_getargspec_calls` in `analyze.py`, registered in `find_semantic_findings`. Same posture as #7/#8/#19 - `needs_llm=True`, detection is deterministic, the actual fix (`inspect.getargspec` → `inspect.getfullargspec`, same `.args` attribute) goes through the normal Planner/Refactorer/Auditor loop. Confirmed live: `toolz/curried.py` went from a Mode A collection crash to real `VERIFIED` (2/2) after this fix.

---

## 22. Mode A's dependency closure never included the paired TEST FILE's own local imports - only the module's

**Found via:** `pytoolz/toolz` @ `498fefa`, first library scouted specifically to stress differential fuzzing and the confidence-count fields on genuinely unseen real code. `toolz/dicttoolz/tests/test_core.py` does `from toolz.utils import raises`, but `toolz/dicttoolz/core.py` (the module actually under test) has zero import statements of its own - a real, correct, common shape (a leaf implementation module using only builtins). Reproduced directly: `run_mode_a`'s sandbox had the module's own closure (via bug #21's fix, correctly including `toolz/__init__.py`'s real re-exports) but never the test file's, so pytest failed collection with `ModuleNotFoundError: No module named 'toolz.utils'` - looked identical to a real behavior mismatch, or got masked entirely as `UNVERIFIED` by the vacuous-pass guard (#12).

**Root cause:** `dependency_closure()` is always computed starting from the module under test (`file_unit` in `orchestrator.py`'s Phase B loop) - the test file the sandbox also has to run was never used as a second BFS root, so its own real local-import needs were structurally invisible to the closure computation, regardless of #21's fix.

**A real bug caught by the test written for this fix, before it shipped:** the first version merged the test file's own closure in unconditionally - but a test file almost always imports the module under test itself, so its closure naturally resolves an edge right back to that module. Merging that edge in let `write_sandbox_tree`'s closure-write step (which runs *after* the module's own write) silently clobber the actual live candidate source being verified with the `FileUnit`'s stale `original_source`/`final_source` - verifying the wrong thing with no error at all. Caught immediately because the regression test asserted the merged closure's exact contents rather than just "doesn't crash."

**Fix:** new `_closure_including_test_file()` (`orchestrator.py`) - computes the module's closure as before, then (if a Mode A test pairing exists) computes a *second* closure rooted at the test file itself, merges the two (deduped by relative path), and explicitly excludes the module-under-test's own path from the test file's contribution. `BehaviorTestInfo` gained a `test_path: Path | None` field (previously only the matched test's basename/content were kept, not its real path - needed here to look up its own `FileUnit` for a real closure computation, especially since a bare filename like `test_core.py` is genuinely ambiguous in `toolz`'s own tree, which has three different `tests/test_core.py` files in three different subpackages). Confirmed live: `toolz/dicttoolz/core.py`, `toolz/functoolz/core.py`, `toolz/itertoolz/recipes.py`, `toolz/utils.py` all went from 0 files verified to real `VERIFIED` via genuine Mode A runs.

---

## 21. `dependency_closure`'s ancestor-`__init__.py` inclusion (bug #15) added those files to the sandbox but never traced THEIR OWN imports

**Found via:** same `pytoolz/toolz` run as #22 above. `toolz/dicttoolz/core.py` (zero import edges of its own) still failed real Mode A collection: `ModuleNotFoundError: No module named 'toolz.itertoolz'`. `toolz/__init__.py` (a real ancestor of the module under test, needed for Python 2's lack of namespace-package support - exactly what bug #15 added) itself does `from .itertoolz import (...)`, `from .functoolz import (...)`, `from .dicttoolz import (...)` - re-exporting from every subpackage, a real and common package-root shape.

**Root cause:** bug #15's ancestor-inclusion loop (`dependency_closure()`) appends each ancestor `__init__.py` directly to `closure`, but never adds it to the BFS `queue` - so the main traversal never resolves *its* own import edges. Fine for an ancestor `__init__.py` with no real imports of its own (the case #15 was built against), broken the moment a real ancestor `__init__.py` re-exports from siblings, which `toolz`'s top-level `__init__.py` genuinely does.

**Fix:** the ancestor-inclusion loop now also appends each discovered ancestor `__init__.py` to `queue` (moved to run before the main BFS loop, which now naturally expands whatever real imports those ancestors have, same dedup/cap logic as everything else). Confirmed via a new regression test (`test_dependencies.py`) reproducing `toolz`'s exact three-subpackage re-export shape, and live against the real repo.

---

## 20. Mode A's sandbox never wrapped `__init__.py` in a package directory when the migration root itself IS the package - test imports failed identically on both interpreters

**Found via:** a full regression re-run of every real library previously stress-tested this session (`docopt`, `python-slugify`, `inflection`, `jsonschema`, `purl`, `html2text`, `schedule`, `requests`), run fully unattended after this session's other changes (differential fuzzing, self-improving fixer library) to confirm nothing regressed. 6/8 matched documented results exactly; `docopt` hit already-known LLM output non-determinism (unrelated). `python-slugify` and `schedule` both newly landed on `NEEDS_REVIEW` where they'd previously reached `VERIFIED_INFERRED`.

**Root cause:** both libraries are migrated by pointing `shiftcode migrate` directly at the package directory (`schedule/`, `python-slugify/`) rather than a project root containing it. `module_rel_path = file_unit.path.relative_to(effective_root)` then collapses `__init__.py`'s path to a bare `Path("__init__.py")` - real on disk, but `write_sandbox_tree` writes it unwrapped at the sandbox root. Their real test files (`test_schedule.py`, `test.py`) do `import schedule` / `from slugify import slugify`, which fails identically on both interpreters (`ModuleNotFoundError`) - correctly caught as `UNVERIFIED` by the existing vacuous-pass guard (#12), not a false pass, but real lost coverage. Not caused by anything built this session directly - confirmed via `git diff` that `orchestrator.py`'s only change (repair-history capture) is gated off by default. The actual trigger: an earlier fix this session (#17, package-name test-matching) started correctly pairing these two libraries into Mode A for the first time; Mode A never got the same package-wrapping fix Mode C got for the analogous `purl` case (#13).

**A subtlety caught mid-fix:** the first fix attempt wrapped the module using the migration root's own directory name (`python-slugify`) - which fixed `schedule` (directory name happens to match its import name) but not `python-slugify` (a very common real-world mismatch: the PyPI/repo name differs from the actual importable module name - `python-slugify` ships a module literally called `slugify`). Fixed by inferring the real import name from the paired test file's own top-level imports instead of guessing from the directory name, with a small denylist for common test-tooling imports that can appear before the real one (`schedule`'s own test file does `import mock` before `import schedule`).

**Fix:** `_sandbox_root_prefix`/`_infer_package_import_name` in `orchestrator.py` - detects when the migration root itself is a package, infers the real import name from real evidence (the paired test's imports), and prefixes every sandbox-relative path (the module and its whole dependency closure) accordingly. Falls back to the directory name only when no test pairing exists. Confirmed on live re-runs: both `schedule/__init__.py` and `python-slugify/__init__.py` now reach real `VERIFIED` (stronger than their original `VERIFIED_INFERRED` - real Mode A test suites run now instead of falling back to Mode C). `purl` and `requests` (already-correct multi-directory layouts) re-confirmed unaffected.

---

## 19. Bare `cmp(a, b)` builtin calls produced zero findings - removed in Python 3 with no fixer anywhere, so it was never caught

**Found via:** the self-improving fixer library's first real graduation (`pipeline/repair_history.py` / `suggest-fixer-rules`), not external stress testing - a demonstration case, not a real third-party repo. `cmp()` was a Python 2 builtin (returns -1/0/1); Python 3 removed it entirely with no replacement, and confirmed by inspecting the vendored fixer set directly (`ls vendor/lib2to3/fixes/`) - there is no `fix_cmp`. A bare call raises `NameError` under Python 3 with zero findings to prompt a fix beforehand, same failure shape as #7's `UnicodeType` gap.

**Process exercised, end to end:** a confirmed repair (before/after + a diagnosed root-cause hint) was fed to `FixerRuleAgent`, running for real against `gemini-3.5-flash-lite`. It drafted a candidate `_find_*` detector matching the real style of `_find_legacy_types_from_imports`/`_find_normalize_encode_chains` almost exactly - correct AST shape, correctly narrow (only a bare `ast.Name` call with exactly 2 args, not method calls or other arities), parsed cleanly with no manual fixes needed to the logic. Reviewed by hand, given a proper docstring, two tests added (`test_analyze.py`), merged as `_find_builtin_cmp_calls`. Confirmed firing correctly through the real pipeline entry point (`deterministic_transform` -> `find_semantic_findings`), not just in isolation.

**Root cause:** a real, permanent gap in both lib2to3 and this project's own semantic-findings scanner - `cmp()` isn't a syntax construct lib2to3 fixers target, and nothing here detected it either until now.

**Fix:** new `_find_builtin_cmp_calls` in `analyze.py`, registered in `find_semantic_findings`. Same posture as #7/#8 - `needs_llm=True`, detection is deterministic, the actual code fix still goes through the normal Planner/Refactorer/Auditor loop.

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

**Status:** fixed - see #35 for the actual fix (the same gap described here,
closed as part of a deliberate pass through every remaining open item).

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

**Both parts are required, every time:**

1. **Index table row** (top of this file) — one-line bug description plus
   status, newest first. This is how anyone finds a specific entry without
   reading the whole file; a bug added without a row defeats the reason the
   index exists.
2. **Full entry** (`## N. Title`) — same as always: found via, root cause,
   fix, status.

If a bug's status ever changes after the fact (e.g. found-but-not-fixed
becomes fixed later, or one bug turns out to be subsumed by another), update
both the index row and the entry itself — don't let them drift apart.
