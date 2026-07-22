from pathlib import Path

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.models import FileUnit, MigrationPlan, PlanStep, RefactorPatch, RepairHint, SymbolBlock
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


def test_migrate_file_emits_progress_for_plan_less_fast_path():
    fu = FileUnit(path=Path("m.py"), original_source="x = 1\n", deterministic_output="x = 1\n", plan=MigrationPlan(steps=[]))
    refactorer = RefactorerAgent(StubProvider([]))
    auditor = AuditorAgent(StubProvider([]))
    messages: list[str] = []

    migrate_file(
        fu, refactorer=refactorer, auditor=auditor, py2_runtime=UNAVAILABLE_RUNTIME, on_progress=messages.append
    )

    assert any("verifying" in m for m in messages)


def test_migrate_file_emits_progress_per_attempt():
    broken_patch = RefactorPatch(
        blocks=[SymbolBlock(symbol="divide", new_source="def divide(a, b)\n    result = a / b\n    return result\n")]
    )
    fixed_patch = RefactorPatch(
        blocks=[SymbolBlock(symbol="divide", new_source="def divide(a, b):\n    result = a / b\n    return result\n")]
    )
    hint = RepairHint(root_cause="missing colon", hint="add ':' after the function signature")
    refactorer = RefactorerAgent(StubProvider([broken_patch, fixed_patch]))
    auditor = AuditorAgent(StubProvider([hint]))
    messages: list[str] = []

    migrate_file(
        _file_unit(),
        refactorer=refactorer,
        auditor=auditor,
        py2_runtime=UNAVAILABLE_RUNTIME,
        on_progress=messages.append,
    )

    assert any("attempt 1/3: refactoring" in m for m in messages)
    assert any("attempt 1/3: RETRY" in m for m in messages)
    assert any("attempt 1/3: consulting Auditor" in m for m in messages)
    assert any("attempt 2/3: refactoring" in m for m in messages)


def test_migrate_file_with_no_progress_callback_does_not_crash():
    fu = FileUnit(path=Path("m.py"), original_source="x = 1\n", deterministic_output="x = 1\n", plan=MigrationPlan(steps=[]))
    refactorer = RefactorerAgent(StubProvider([]))
    auditor = AuditorAgent(StubProvider([]))

    result = migrate_file(fu, refactorer=refactorer, auditor=auditor, py2_runtime=UNAVAILABLE_RUNTIME)

    assert result.final_source == "x = 1\n"
