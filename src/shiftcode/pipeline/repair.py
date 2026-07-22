from dataclasses import dataclass, field
from typing import Callable

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.base import AgentOutputError
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.models import (
    BehaviorResult,
    FileUnit,
    GateOutcome,
    RepairAttempt,
    RepairHint,
    Status,
    TestCase,
    VerifyResult,
)
from shiftcode.pipeline.verify.behavior_gate import has_main_block, run_mode_a, run_mode_b
from shiftcode.pipeline.verify.characterization_gate import run_mode_c
from shiftcode.pipeline.verify.determinism import (
    capture_py2_script_runs,
    capture_py3_script_runs,
    check_determinism,
)
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime
from shiftcode.pipeline.verify.syntax_gate import check_syntax


@dataclass
class BehaviorTestInfo:
    """Present -> Mode A (run the existing test suite). Absent -> Mode B
    (__main__ golden-output diff) if the file has an entry point, else
    Mode C (auto-generated characterization tests) if any were produced,
    else behavior is simply unverifiable."""

    test_filename: str
    test_source: str


@dataclass
class CharacterizationInfo:
    """Generated once per file, before the repair loop starts (unlike Mode A's
    test_info, which already exists; this requires an LLM call, so it's
    produced upfront by the orchestrator and reused across repair attempts,
    not regenerated per attempt)."""

    cases: list[TestCase] = field(default_factory=list)
    evidence_source: str = "llm_inference"


def _emit(on_progress: Callable[[str], None] | None, msg: str) -> None:
    if on_progress:
        on_progress(msg)


def verify_candidate(
    original_source_py2: str,
    candidate_source_py3: str,
    module_filename: str,
    *,
    py2_runtime: SandboxRuntime,
    py3_runtime: SandboxRuntime | None = None,
    py3_runtime_for_c: SandboxRuntime | None = None,
    determinism_runs: int = 3,
    test_info: BehaviorTestInfo | None = None,
    characterization_info: CharacterizationInfo | None = None,
) -> VerifyResult:
    syntax = check_syntax(candidate_source_py3)
    if not syntax.passed:
        return VerifyResult(syntax=syntax)

    is_test_file = module_filename.startswith("test_")

    if test_info is not None:
        behavior = run_mode_a(
            module_filename=module_filename,
            module_source_py2=original_source_py2,
            module_source_py3=candidate_source_py3,
            test_filename=test_info.test_filename,
            test_source=test_info.test_source,
            py2_runtime=py2_runtime,
            py3_runtime=py3_runtime,
        )
    elif is_test_file:
        # A test_*.py file always imports the module(s) it tests, so it can
        # never run standalone in Mode B's single-file isolation - it would
        # just crash on that import (identically-but-differently-worded on
        # py2 vs py3), which looks like a behavior mismatch but isn't one.
        behavior = BehaviorResult(
            outcome=GateOutcome.UNVERIFIED,
            mode=None,
            detail="test file has no standalone entry point (imports its subject module - not Mode B eligible)",
        )
    elif has_main_block(candidate_source_py3):
        behavior = run_mode_b(
            module_filename=module_filename,
            module_source_py2=original_source_py2,
            module_source_py3=candidate_source_py3,
            py2_runtime=py2_runtime,
            py3_runtime=py3_runtime,
        )
    elif characterization_info is not None and characterization_info.cases and py3_runtime_for_c is not None:
        behavior = run_mode_c(
            module_filename=module_filename,
            module_source_py2=original_source_py2,
            module_source_py3=candidate_source_py3,
            test_plan_cases=characterization_info.cases,
            py2_runtime=py2_runtime,
            py3_runtime=py3_runtime_for_c,
            evidence_source=characterization_info.evidence_source,
        )
    else:
        behavior = BehaviorResult(
            outcome=GateOutcome.UNVERIFIED,
            mode=None,
            detail="cannot verify behavior (no test suite, no executable entry point, no characterization tests available)",
        )

    if behavior.outcome == GateOutcome.FAIL:
        return VerifyResult(syntax=syntax, behavior=behavior)

    # Determinism check is Mode-B-shaped (repeated script execution) - only
    # meaningful for __main__-executable files that can actually run standalone.
    # Mode A / library-only files / test files skip it in this MVP rather than
    # faking coverage; see plan deferrals.
    if is_test_file or not has_main_block(candidate_source_py3):
        determinism = None
    else:
        py3_runs = capture_py3_script_runs(
            candidate_source_py3, module_filename, py3_runtime=py3_runtime, n=determinism_runs
        )
        py2_runs = capture_py2_script_runs(
            py2_runtime, original_source_py2, module_filename, n=determinism_runs
        )
        determinism = check_determinism(py3_outputs=py3_runs, py2_outputs=py2_runs)

    return VerifyResult(syntax=syntax, behavior=behavior, determinism=determinism)


def _classify(result: VerifyResult) -> str:
    """RETRY (worth another Refactorer/Auditor pass), NEEDS_REVIEW (no amount of
    retrying fixes an unverifiable environment), VERIFIED_INFERRED (passed only
    auto-generated Mode C characterization tests - real signal, weaker
    confidence than a human-authored test), or VERIFIED."""
    if result.syntax and not result.syntax.passed:
        return "RETRY"
    if result.behavior and result.behavior.outcome == GateOutcome.FAIL:
        return "RETRY"
    if result.determinism and result.determinism.outcome == GateOutcome.FAIL:
        return "RETRY"
    if result.behavior and result.behavior.outcome == GateOutcome.UNVERIFIED:
        return "NEEDS_REVIEW"
    if result.behavior and result.behavior.mode == "C":
        return "VERIFIED_INFERRED"
    return "VERIFIED"


def _describe_failure(result: VerifyResult) -> str:
    parts = []
    if result.syntax and not result.syntax.passed:
        parts.append(f"SYNTAX_ERROR: {result.syntax.error_message} (line {result.syntax.error_line})")
    if result.behavior:
        parts.append(f"BEHAVIOR[{result.behavior.mode}]={result.behavior.outcome.value}: {result.behavior.detail}")
    if result.determinism:
        parts.append(f"DETERMINISM={result.determinism.outcome.value}: {result.determinism.detail}")
    return " | ".join(parts) if parts else "(no gate details)"


_STATUS_FOR_CLASSIFICATION = {
    "VERIFIED": Status.VERIFIED,
    "VERIFIED_INFERRED": Status.VERIFIED_INFERRED,
}


def _status_for_classification(classification: str) -> Status:
    return _STATUS_FOR_CLASSIFICATION.get(classification, Status.NEEDS_REVIEW)


def migrate_file(
    file_unit: FileUnit,
    *,
    refactorer: RefactorerAgent,
    auditor: AuditorAgent,
    py2_runtime: SandboxRuntime,
    py3_runtime: SandboxRuntime | None = None,
    py3_runtime_for_c: SandboxRuntime | None = None,
    max_attempts: int = 3,
    determinism_runs: int = 3,
    test_info: BehaviorTestInfo | None = None,
    characterization_info: CharacterizationInfo | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> FileUnit:
    """Bounded Auditor<->Refactorer loop, wired to every verify gate. Mutates and
    returns file_unit with final_source, verify_result, status, and full
    repair_attempts history. Never marks VERIFIED without passing the gates."""
    assert file_unit.deterministic_output is not None
    assert file_unit.plan is not None

    if not file_unit.plan.steps:
        _emit(on_progress, "verifying (no plan changes needed)")
        candidate = file_unit.deterministic_output
        result = verify_candidate(
            file_unit.original_source,
            candidate,
            file_unit.path.name,
            py2_runtime=py2_runtime,
            py3_runtime=py3_runtime,
            py3_runtime_for_c=py3_runtime_for_c,
            determinism_runs=determinism_runs,
            test_info=test_info,
            characterization_info=characterization_info,
        )
        classification = _classify(result)
        file_unit.final_source = candidate
        file_unit.verify_result = result
        file_unit.status = _status_for_classification(classification)
        if file_unit.status == Status.NEEDS_REVIEW:
            file_unit.reason = _describe_failure(result)
        return file_unit

    hints: list[RepairHint] = []
    candidate = file_unit.deterministic_output
    result = None
    classification = "RETRY"

    for attempt in range(1, max_attempts + 1):
        _emit(on_progress, f"attempt {attempt}/{max_attempts}: refactoring")
        try:
            candidate = refactorer.refactor(
                deterministic_source=file_unit.deterministic_output,
                plan=file_unit.plan,
                hints=hints,
            )
        except AgentOutputError as exc:
            classification = "RETRY"
            failure_detail = f"REFACTORER_CALL_ERROR: {exc}"
            _emit(on_progress, f"attempt {attempt}/{max_attempts}: Refactorer call failed, retrying")
            file_unit.repair_attempts.append(
                RepairAttempt(
                    attempt_number=attempt,
                    candidate_source="",
                    failure_summary=failure_detail,
                    hint=None,
                )
            )
            # No candidate to verify or diff for the Auditor - just retry the
            # Refactorer directly on the next attempt.
            continue

        _emit(on_progress, f"attempt {attempt}/{max_attempts}: verifying")
        result = verify_candidate(
            file_unit.original_source,
            candidate,
            file_unit.path.name,
            py2_runtime=py2_runtime,
            py3_runtime=py3_runtime,
            py3_runtime_for_c=py3_runtime_for_c,
            determinism_runs=determinism_runs,
            test_info=test_info,
            characterization_info=characterization_info,
        )
        classification = _classify(result)
        failure_detail = _describe_failure(result) if classification == "RETRY" else None
        _emit(on_progress, f"attempt {attempt}/{max_attempts}: {classification}")

        attempt_hint_text = None
        if classification == "RETRY" and attempt < max_attempts:
            _emit(on_progress, f"attempt {attempt}/{max_attempts}: consulting Auditor")
            try:
                hint = auditor.diagnose(
                    deterministic_source=file_unit.deterministic_output,
                    plan=file_unit.plan,
                    candidate_source=candidate,
                    failure_detail=failure_detail,
                )
                hints.append(hint)
                attempt_hint_text = hint.hint
            except AgentOutputError as exc:
                failure_detail = f"{failure_detail} | AUDITOR_CALL_ERROR: {exc}"

        file_unit.repair_attempts.append(
            RepairAttempt(
                attempt_number=attempt,
                candidate_source=candidate,
                failure_summary=failure_detail or "",
                hint=attempt_hint_text,
            )
        )

        if classification != "RETRY":
            break

    file_unit.final_source = candidate
    file_unit.verify_result = result
    file_unit.status = _status_for_classification(classification)
    if file_unit.status == Status.NEEDS_REVIEW:
        last_attempt_summary = file_unit.repair_attempts[-1].failure_summary if file_unit.repair_attempts else "(no attempts recorded)"
        if result is None:
            file_unit.reason = f"repair attempts exhausted ({max_attempts}): {last_attempt_summary}"
        elif classification == "RETRY":
            file_unit.reason = f"repair attempts exhausted ({max_attempts}): {_describe_failure(result)}"
        else:
            file_unit.reason = _describe_failure(result)
    return file_unit
