from pathlib import Path

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.models import FileUnit, MigrationPlan, PlanStep, RefactorPatch, RepairHint, Status, SymbolBlock
from shiftcode.pipeline.repair import migrate_file
from shiftcode.pipeline.verify.py2_runtime import Py2Runtime

from fakes import StubProvider

UNAVAILABLE_RUNTIME = Py2Runtime(available=False, kind="unavailable", reason="no python2/docker on this machine")

DETERMINISTIC_OUTPUT = "def divide(a, b):\n    result = a / b\n    return result\n"
PLAN = MigrationPlan(
    steps=[PlanStep(finding_ref="division@2:13", description="use true division", rationale="tests expect float")]
)


def _file_unit() -> FileUnit:
    return FileUnit(
        path=Path("calculator.py"),
        original_source="def divide(a, b):\n    return a / b\n",
        deterministic_output=DETERMINISTIC_OUTPUT,
        plan=PLAN,
    )


def test_migrate_file_skips_refactorer_when_plan_has_no_steps():
    fu = FileUnit(
        path=Path("m.py"),
        original_source="x = 1\n",
        deterministic_output="x = 1\n",
        plan=MigrationPlan(steps=[]),
    )
    refactorer = RefactorerAgent(StubProvider([]))  # would raise if called
    auditor = AuditorAgent(StubProvider([]))

    result = migrate_file(fu, refactorer=refactorer, auditor=auditor, py2_runtime=UNAVAILABLE_RUNTIME)

    assert result.final_source == "x = 1\n"
    assert result.status == Status.NEEDS_REVIEW  # unverifiable, no py2 runtime, no __main__ block


def test_migrate_file_needs_review_when_behavior_unverifiable():
    good_patch = RefactorPatch(
        blocks=[SymbolBlock(symbol="divide", new_source="def divide(a, b):\n    result = a / b\n    return result\n")]
    )
    refactorer = RefactorerAgent(StubProvider([good_patch]))
    auditor = AuditorAgent(StubProvider([]))  # should not be called - nothing failed

    result = migrate_file(_file_unit(), refactorer=refactorer, auditor=auditor, py2_runtime=UNAVAILABLE_RUNTIME)

    assert result.status == Status.NEEDS_REVIEW
    assert "UNVERIFIED" in result.reason
    assert len(result.repair_attempts) == 1


def test_migrate_file_repair_loop_engages_on_syntax_failure_and_recovers():
    broken_patch = RefactorPatch(
        blocks=[SymbolBlock(symbol="divide", new_source="def divide(a, b)\n    result = a / b\n    return result\n")]
    )  # missing colon
    fixed_patch = RefactorPatch(
        blocks=[SymbolBlock(symbol="divide", new_source="def divide(a, b):\n    result = a / b\n    return result\n")]
    )
    hint = RepairHint(root_cause="missing colon", hint="add ':' after the function signature")

    refactorer = RefactorerAgent(StubProvider([broken_patch, fixed_patch]))
    auditor = AuditorAgent(StubProvider([hint]))

    result = migrate_file(_file_unit(), refactorer=refactorer, auditor=auditor, py2_runtime=UNAVAILABLE_RUNTIME)

    assert len(result.repair_attempts) == 2
    assert "SYNTAX_ERROR" in result.repair_attempts[0].failure_summary
    assert result.repair_attempts[0].hint == "add ':' after the function signature"
    # second attempt has valid syntax but is still NEEDS_REVIEW (no py2 runtime here)
    assert result.status == Status.NEEDS_REVIEW
    assert "SYNTAX_ERROR" not in (result.reason or "")
