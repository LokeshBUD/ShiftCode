import ast
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


def _values_equal(py2_val: str, py3_val: str) -> bool:
    """Compares actual parsed values, not raw repr strings - dict/set repr
    ordering isn't guaranteed identical across interpreter versions even
    when the content is identical (confirmed real case: purl's `parse()`
    returning the exact same key/value pairs in a different dict order on
    py2 vs py3 - Python 2 dicts have no ordering guarantee, Python 3.7+
    guarantees insertion order - which a naive string comparison flagged as
    a false mismatch). ast.literal_eval-only, same safety posture as
    args_literal - never eval(). Falls back to plain string comparison if
    the repr isn't literal-parseable (e.g. a custom object's repr), matching
    the previous behavior exactly for anything this can't safely improve on."""
    try:
        return ast.literal_eval(py2_val) == ast.literal_eval(py3_val)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return py2_val == py3_val


def _build_driver_script(module_name: str, case: TestCase) -> str:
    """Valid under both py2 and py3 (print(x) as a single parenthesized arg
    works identically as a statement in py2 and a call in py3). args_literal
    has already passed validate_args_literal - its exact source text is
    proven to be nothing but a literal tuple, so splicing it directly into
    the driver as source code is exactly as safe as writing "(10, 4)" by
    hand; no eval() of any kind happens at driver runtime."""
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


def _run_case_in(runtime: SandboxRuntime, cwd: Path, module_name: str, case: TestCase, timeout: float) -> str:
    driver_rel = Path("_shiftcode_driver.py")
    (cwd / driver_rel).write_text(_build_driver_script(module_name, case))
    proc = runtime.run_script(cwd, driver_rel, timeout=timeout)
    return proc.stdout.strip()


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
            py2_out = _run_case_in(py2_runtime, Path(py2_dir), module_name, case, timeout)
            py3_out = _run_case_in(py3_runtime, Path(py3_dir), module_name, case, timeout)

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
                mismatches.append(f"{case_label}: py2={py2_out!r} py3={py3_out!r}")
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
                                first_failure_args, function_name=case.function_name, count=_NEIGHBOR_VARIANT_COUNT
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
        )

    return BehaviorResult(
        outcome=GateOutcome.PASS,
        mode="C",
        detail=f"{len(valid_cases)} auto-generated characterization test(s) passed (evidence: {evidence_source})",
        evidence_source=evidence_source,
    )
