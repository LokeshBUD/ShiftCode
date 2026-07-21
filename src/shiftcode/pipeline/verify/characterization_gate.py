import ast
import tempfile
from pathlib import Path

from shiftcode.models import BehaviorResult, GateOutcome, TestCase
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime


class UnsafeTestCaseError(Exception):
    """args_literal failed the literal-only safety check - rejected before any
    driver script is ever built or executed. Not expected in normal operation
    (the prompt instructs literal-only output and the schema is validated),
    but this is the actual enforcement point, not the prompt wording."""


def _validate_args_literal(args_literal: str) -> tuple:
    """The only thing standing between 'the LLM proposed an input' and 'code
    executes' - ast.literal_eval structurally cannot evaluate a function call,
    attribute access, or name lookup. Anything that isn't a pure literal tuple
    is rejected here, full stop."""
    try:
        value = ast.literal_eval(args_literal)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
        raise UnsafeTestCaseError(f"args_literal {args_literal!r} rejected: {exc}") from exc
    if not isinstance(value, tuple):
        raise UnsafeTestCaseError(
            f"args_literal {args_literal!r} must be a tuple literal, got {type(value).__name__}"
        )
    return value


def _build_driver_script(module_name: str, case: TestCase) -> str:
    """Valid under both py2 and py3 (print(x) as a single parenthesized arg
    works identically as a statement in py2 and a call in py3). args_literal
    has already passed _validate_args_literal - its exact source text is
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


def _run_case(
    runtime: SandboxRuntime,
    module_filename: str,
    module_source: str,
    module_name: str,
    case: TestCase,
    timeout: float,
) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / module_filename).write_text(module_source)
        driver_path = tmp_path / "_shiftcode_driver.py"
        driver_path.write_text(_build_driver_script(module_name, case))
        proc = runtime.run_script(driver_path, timeout=timeout)
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
) -> BehaviorResult:
    """Auto-generated characterization testing: for files with no test suite
    and no __main__ entry point. Ground truth always comes from actually
    executing the real original py2 code with the proposed inputs - the LLM
    only ever proposes inputs, never expected outputs."""
    if not py2_runtime.available:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED, mode="C", detail=f"no py2 sandbox available ({py2_runtime.reason})"
        )
    if not py3_runtime.available:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED, mode="C", detail=f"no py3 sandbox available ({py3_runtime.reason})"
        )

    module_name = module_filename[:-3] if module_filename.endswith(".py") else module_filename

    valid_cases = []
    rejected = []
    for case in test_plan_cases:
        try:
            _validate_args_literal(case.args_literal)
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
    for case in valid_cases:
        py2_out = _run_case(py2_runtime, module_filename, module_source_py2, module_name, case, timeout)
        py3_out = _run_case(py3_runtime, module_filename, module_source_py3, module_name, case, timeout)

        py2_kind, _, py2_val = py2_out.partition(":")
        py3_kind, _, py3_val = py3_out.partition(":")
        case_label = f"{case.function_name}{case.args_literal}"

        # Same lesson as Mode A (behavior_gate.py): compare the meaningful
        # signal, not incidental interpreter text. Whether it raised, and
        # what type, or what value it returned, IS the signal. An exception's
        # message wording can differ between py2/py3 for the same conceptual
        # error (e.g. ZeroDivisionError) - that's not compared here.
        if py2_kind != py3_kind:
            mismatches.append(f"{case_label}: py2={py2_out!r} py3={py3_out!r}")
            failing_cases.append(case_label)
        elif py2_kind == "RESULT" and py2_val != py3_val:
            mismatches.append(f"{case_label}: py2 returned {py2_val!r}, py3 returned {py3_val!r}")
            failing_cases.append(case_label)
        elif py2_kind == "EXCEPTION" and py2_val != py3_val:
            mismatches.append(f"{case_label}: py2 raised {py2_val}, py3 raised {py3_val}")
            failing_cases.append(case_label)

    if mismatches:
        return BehaviorResult(
            outcome=GateOutcome.FAIL,
            mode="C",
            detail=f"characterization test mismatches (evidence: {evidence_source}): " + "; ".join(mismatches),
            failing_tests=failing_cases,
            evidence_source=evidence_source,
        )

    return BehaviorResult(
        outcome=GateOutcome.PASS,
        mode="C",
        detail=f"{len(valid_cases)} auto-generated characterization test(s) passed (evidence: {evidence_source})",
        evidence_source=evidence_source,
    )
