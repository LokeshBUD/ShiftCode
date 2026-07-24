import ast
import re
import tempfile
from pathlib import Path

from shiftcode.models import BehaviorResult, GateOutcome, TestCase
from shiftcode.pipeline.dependencies import ClosureFile
from shiftcode.pipeline.verify.fuzz_generation import (
    UnsafeTestCaseError,
    _neighbor_variants,
    validate_args_literal,
)
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime, write_sandbox_tree

# Free-text detail formatting cap - failing_tests (structured, for
# programmatic consumption) stays fully uncapped regardless; this only
# bounds the human-readable summary string, which becomes unreadable once
# case counts grow past a handful (a real concern once characterization_fuzz_cases
# raises typical case counts from single digits into the dozens/hundreds).
MAX_REPORTED_MISMATCHES = 10
_NEIGHBOR_VARIANT_COUNT = 3


_HEX_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")
_GENERATOR_REPR_RE = re.compile(r"^<generator object [^ ]+ at 0x[0-9a-fA-F]+>$")


def _normalize_nonliteral_repr(value: str) -> str:
    """Real, confirmed case (a class-method characterization case against
    blinker's actual Signal.receivers_for): default object/generator reprs
    embed a real memory address, which always differs across two SEPARATE
    interpreter PROCESSES - py2 vs py3 or not, that address was never going
    to match - a pure comparison artifact, not a behavior difference.
    Python 3 also added the generator's qualified name to its own repr
    (`<generator object Class.method at 0x...>` vs py2's unqualified
    `<generator object method at 0x...>`) - a real repr-FORMAT change
    between versions, not a behavior difference either. Both collapse to one
    comparable placeholder; only affects the non-literal fallback path
    below, never the literal-value comparison itself."""
    if _GENERATOR_REPR_RE.match(value):
        return "<generator object>"
    return _HEX_ADDR_RE.sub("0xADDR", value)


def _values_equal(py2_val: str, py3_val: str) -> bool:
    """Compares actual parsed values, not raw repr strings - dict/set repr
    ordering isn't guaranteed identical across interpreter versions even
    when the content is identical (confirmed real case: purl's `parse()`
    returning the exact same key/value pairs in a different dict order on
    py2 vs py3 - Python 2 dicts have no ordering guarantee, Python 3.7+
    guarantees insertion order - which a naive string comparison flagged as
    a false mismatch). ast.literal_eval-only, same safety posture as
    args_literal - never eval(). Falls back to a noise-normalized string
    comparison if the repr isn't literal-parseable (e.g. a custom object's
    repr) - see _normalize_nonliteral_repr for what that strips and why."""
    try:
        return ast.literal_eval(py2_val) == ast.literal_eval(py3_val)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _normalize_nonliteral_repr(py2_val) == _normalize_nonliteral_repr(py3_val)


def _build_driver_script(module_name: str, case: TestCase) -> str:
    """Valid under both py2 and py3 (print(x) as a single parenthesized arg
    works identically as a statement in py2 and a call in py3). args_literal
    (and, for a class-method case, constructor_args_literal) has already
    passed validate_args_literal - its exact source text is proven to be
    nothing but a literal tuple, so splicing it directly into the driver as
    source code is exactly as safe as writing "(10, 4)" by hand; no eval() of
    any kind happens at driver runtime."""
    if case.class_name is not None:
        ctor_args = case.constructor_args_literal if case.constructor_args_literal is not None else "()"
        return (
            f"import {module_name} as _mod\n"
            f"_ctor_args = {ctor_args}\n"
            f"_args = {case.args_literal}\n"
            "try:\n"
            f"    _inst = _mod.{case.class_name}(*_ctor_args)\n"
            f"    _result = _inst.{case.function_name}(*_args)\n"
            "    print('RESULT:' + repr(_result))\n"
            "except Exception as _e:\n"
            "    print('EXCEPTION:' + _e.__class__.__name__)\n"
        )
    return (
        f"import {module_name} as _mod\n"
        f"_args = {case.args_literal}\n"
        "try:\n"
        f"    _result = _mod.{case.function_name}(*_args)\n"
        "    print('RESULT:' + repr(_result))\n"
        "except Exception as _e:\n"
        "    print('EXCEPTION:' + _e.__class__.__name__)\n"
    )


def _module_dotted_name(rel_path: Path) -> str:
    """`mypkg/__init__.py` -> "mypkg" (import the package itself, not a
    nonsensical "__init__" name); `mypkg/core.py` -> "mypkg.core"; flat
    `m.py` -> "m", same as the old `module_filename[:-3]` behavior."""
    parts = rel_path.parent.parts if rel_path.name == "__init__.py" else rel_path.with_suffix("").parts
    return ".".join(parts)


def _run_case_in(runtime: SandboxRuntime, cwd: Path, module_name: str, case: TestCase, timeout: float) -> tuple[str, str]:
    driver_rel = Path("_shiftcode_driver.py")
    (cwd / driver_rel).write_text(_build_driver_script(module_name, case))
    proc = runtime.run_script(cwd, driver_rel, timeout=timeout)
    return proc.stdout.strip(), proc.stderr.strip()


def run_mode_c(
    *,
    module_filename: str,
    module_source_py2: str,
    module_source_py3: str,
    test_plan_cases: list[TestCase],
    py2_runtime: SandboxRuntime,
    py3_runtime: SandboxRuntime,
    evidence_source: str,
    timeout: float = 30,
    dependency_closure: list[ClosureFile] | None = None,
    module_rel_path: Path | None = None,
) -> BehaviorResult:
    """Auto-generated characterization testing: for files with no test suite
    and no __main__ entry point. Ground truth always comes from actually
    executing the real original py2 code with the proposed inputs - the LLM
    only ever proposes inputs, never expected outputs.

    The module + its dependency closure are written into each side's sandbox
    ONCE, reused across every test case (only the tiny driver script changes
    per case) - with a real closure this is meaningfully cheaper than the old
    fresh-temp-dir-per-case approach, and matters even more once
    characterization_fuzz_cases raises typical case counts well past single
    digits. Trade-off worth naming explicitly: this reintroduces a small
    cross-case isolation risk (a case with a real filesystem side effect
    could in principle leak into the next case's shared directory) -
    acceptable given Mode C is already scoped to top-level functions with
    literal-only arguments (see top_level_function_defs's own docstring),
    not arbitrary stateful objects."""
    if not py2_runtime.available:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED, mode="C", detail=f"no py2 sandbox available ({py2_runtime.reason})"
        )
    if not py3_runtime.available:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED, mode="C", detail=f"no py3 sandbox available ({py3_runtime.reason})"
        )

    closure = dependency_closure or []
    rel_path = module_rel_path or Path(module_filename)
    module_name = _module_dotted_name(rel_path)

    valid_cases = []
    rejected = []
    for case in test_plan_cases:
        try:
            validate_args_literal(case.args_literal)
            if case.constructor_args_literal is not None:
                validate_args_literal(case.constructor_args_literal)
            valid_cases.append(case)
        except UnsafeTestCaseError as exc:
            rejected.append(f"{case.function_name}{case.args_literal}: {exc}")

    if not valid_cases:
        detail = "no valid characterization test cases (all rejected by literal-safety check)"
        if rejected:
            detail += ": " + "; ".join(rejected)
        return BehaviorResult(outcome=GateOutcome.UNVERIFIED, mode="C", detail=detail)

    mismatches = []
    failing_cases = []
    first_failure_args: tuple | None = None
    with tempfile.TemporaryDirectory() as py2_dir, tempfile.TemporaryDirectory() as py3_dir:
        write_sandbox_tree(Path(py2_dir), rel_path, module_source_py2, closure, side="py2")
        write_sandbox_tree(Path(py3_dir), rel_path, module_source_py3, closure, side="py3")

        cases_to_run = list(valid_cases)
        i = 0
        while i < len(cases_to_run):
            case = cases_to_run[i]
            i += 1
            py2_out, py2_err = _run_case_in(py2_runtime, Path(py2_dir), module_name, case, timeout)
            py3_out, py3_err = _run_case_in(py3_runtime, Path(py3_dir), module_name, case, timeout)

            py2_kind, _, py2_val = py2_out.partition(":")
            py3_kind, _, py3_val = py3_out.partition(":")
            case_label = f"{case.function_name}{case.args_literal} {case.rationale}"

            is_mismatch = False
            # Same lesson as Mode A (behavior_gate.py): compare the meaningful
            # signal, not incidental interpreter text. Whether it raised, and
            # what type, or what value it returned, IS the signal. An exception's
            # message wording can differ between py2/py3 for the same conceptual
            # error (e.g. ZeroDivisionError) - that's not compared here.
            if py2_kind != py3_kind:
                detail = f"{case_label}: py2={py2_out!r} py3={py3_out!r}"
                # Real, confirmed case (argcomplete/completers.py): empty
                # stdout with no RESULT:/EXCEPTION: prefix at all means the
                # driver crashed before its own try/except could even run -
                # e.g. a transitive import failure elsewhere in the closure
                # (a sibling __init__.py's own unrelated bug), not anything
                # about the function under test. That looked exactly like a
                # real behavioral difference until stderr was inspected by
                # hand - surfaced here so it doesn't have to be diagnosed
                # that way again.
                if not py2_out and py2_err:
                    detail += f" | py2 stderr={py2_err!r}"
                if not py3_out and py3_err:
                    detail += f" | py3 stderr={py3_err!r}"
                mismatches.append(detail)
                is_mismatch = True
            elif py2_kind == "RESULT" and not _values_equal(py2_val, py3_val):
                mismatches.append(f"{case_label}: py2 returned {py2_val!r}, py3 returned {py3_val!r}")
                is_mismatch = True
            elif py2_kind == "EXCEPTION" and py2_val != py3_val:
                mismatches.append(f"{case_label}: py2 raised {py2_val}, py3 raised {py3_val}")
                is_mismatch = True

            if is_mismatch:
                failing_cases.append(case_label)
                # Cheap, non-library shrinking analog: once the FIRST failure
                # for this whole run is found, probe a small, fixed number of
                # boundary-nudged neighbors of it (does the failure narrow to
                # a boundary, or hold broadly?) - scoped to exactly one origin
                # case, not every failure, to keep the added cost bounded and
                # predictable (+_NEIGHBOR_VARIANT_COUNT total, not per-failure).
                # Deliberately NOT stopping the main loop on failure - running
                # the full case budget even after a mismatch preserves real
                # diagnostic signal (boundary-specific vs pervasive) the
                # all-cases-run design already gives.
                if first_failure_args is None:
                    try:
                        first_failure_args = validate_args_literal(case.args_literal)
                        cases_to_run.extend(
                            _neighbor_variants(
                                first_failure_args,
                                function_name=case.function_name,
                                count=_NEIGHBOR_VARIANT_COUNT,
                                class_name=case.class_name,
                                constructor_args_literal=case.constructor_args_literal,
                            )
                        )
                    except UnsafeTestCaseError:
                        pass

    if mismatches:
        reported = mismatches[:MAX_REPORTED_MISMATCHES]
        detail_parts = [f"characterization test mismatches (evidence: {evidence_source}): " + "; ".join(reported)]
        if len(mismatches) > MAX_REPORTED_MISMATCHES:
            detail_parts.append(f"...and {len(mismatches) - MAX_REPORTED_MISMATCHES} more mismatch(es)")
        return BehaviorResult(
            outcome=GateOutcome.FAIL,
            mode="C",
            detail=" ".join(detail_parts),
            failing_tests=failing_cases,
            evidence_source=evidence_source,
            cases_run=len(cases_to_run),
            cases_passed=len(cases_to_run) - len(failing_cases),
        )

    return BehaviorResult(
        outcome=GateOutcome.PASS,
        mode="C",
        detail=f"{len(valid_cases)} auto-generated characterization test(s) passed (evidence: {evidence_source})",
        evidence_source=evidence_source,
        cases_run=len(valid_cases),
        cases_passed=len(valid_cases),
    )
