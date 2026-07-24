import tempfile
from pathlib import Path

from shiftcode.models import BehaviorResult, GateOutcome, TestCase
from shiftcode.pipeline.dependencies import ClosureFile
from shiftcode.pipeline.verify.characterization_gate import (
    MAX_REPORTED_MISMATCHES,
    _module_dotted_name,
    _run_case_in,
    _values_equal,
)
from shiftcode.pipeline.verify.recording_loader import RecordedCase
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime, write_sandbox_tree


def run_mode_r(
    *,
    module_filename: str,
    module_source_py3: str,
    recorded_cases: list[RecordedCase],
    py3_runtime: SandboxRuntime,
    timeout: float = 30,
    dependency_closure: list[ClosureFile] | None = None,
    module_rel_path: Path | None = None,
) -> BehaviorResult:
    """Verification against REAL captured usage data - a user's own Python 2
    code, decorated with `shiftcode.record.recorder.record` in their own
    environment, produced these (args -> result/exception) pairs from real
    calls. The key difference from every other mode: no `py2_runtime` is
    needed at all here, since the expected output was already captured live,
    once, for real - this mode only ever executes the py3 CANDIDATE and
    compares it against that pre-recorded ground truth. Reuses
    characterization_gate.py's driver-script/comparison machinery directly
    (via a throwaway TestCase wrapper) rather than duplicating it - the
    execution/comparison mechanics are identical, only where the "expected"
    side comes from differs."""
    if not py3_runtime.available:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED, mode="R", detail=f"no py3 sandbox available ({py3_runtime.reason})"
        )
    if not recorded_cases:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED, mode="R", detail="no recorded cases available for this file"
        )

    closure = dependency_closure or []
    rel_path = module_rel_path or Path(module_filename)
    module_name = _module_dotted_name(rel_path)

    mismatches = []
    failing_cases = []
    with tempfile.TemporaryDirectory() as py3_dir:
        write_sandbox_tree(Path(py3_dir), rel_path, module_source_py3, closure, side="py3")

        for case in recorded_cases:
            driver_case = TestCase(
                function_name=case.function_name,
                args_literal=case.args_literal,
                rationale="[recorded] real captured call",
            )
            py3_out, _py3_err = _run_case_in(py3_runtime, Path(py3_dir), module_name, driver_case, timeout)
            py3_kind, _, py3_val = py3_out.partition(":")
            case_label = f"{case.function_name}{case.args_literal} [recorded]"

            is_mismatch = False
            if case.expected_exception is not None:
                if py3_kind != "EXCEPTION" or py3_val != case.expected_exception:
                    mismatches.append(
                        f"{case_label}: recorded raised {case.expected_exception}, candidate returned {py3_out!r}"
                    )
                    is_mismatch = True
            elif py3_kind != "RESULT" or not _values_equal(case.expected_result_literal, py3_val):
                mismatches.append(
                    f"{case_label}: recorded returned {case.expected_result_literal!r}, candidate returned {py3_out!r}"
                )
                is_mismatch = True

            if is_mismatch:
                failing_cases.append(case_label)

    if mismatches:
        reported = mismatches[:MAX_REPORTED_MISMATCHES]
        detail_parts = ["recorded-call mismatches: " + "; ".join(reported)]
        if len(mismatches) > MAX_REPORTED_MISMATCHES:
            detail_parts.append(f"...and {len(mismatches) - MAX_REPORTED_MISMATCHES} more mismatch(es)")
        return BehaviorResult(
            outcome=GateOutcome.FAIL,
            mode="R",
            detail=" ".join(detail_parts),
            failing_tests=failing_cases,
            evidence_source="recorded",
            cases_run=len(recorded_cases),
            cases_passed=len(recorded_cases) - len(failing_cases),
        )

    return BehaviorResult(
        outcome=GateOutcome.PASS,
        mode="R",
        detail=f"{len(recorded_cases)} recorded real call(s) matched candidate output",
        evidence_source="recorded",
        cases_run=len(recorded_cases),
        cases_passed=len(recorded_cases),
    )
