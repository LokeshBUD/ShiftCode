import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.models import FileUnit, MigrationPlan, PlanStep, RefactorPatch, Status, SymbolBlock, TestCase
from shiftcode.pipeline.repair import CharacterizationInfo, migrate_file

from fakes import StubProvider


@dataclass
class _ScriptedRuntime:
    outputs: list[str]
    available: bool = True
    reason: str | None = None
    calls: int = field(default=0)

    def run_script(self, cwd, script_rel_path, *, timeout=30):
        stdout = self.outputs[self.calls]
        self.calls += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_migrate_file_reaches_verified_inferred_via_mode_c():
    """A library file with no test suite, no __main__, but a real Mode C pass
    should land on VERIFIED_INFERRED - real signal, but distinct from VERIFIED
    (a human never confirmed this behavior, ShiftCode inferred and checked it)."""
    good_patch = RefactorPatch(
        blocks=[SymbolBlock(symbol="divide", new_source="def divide(a, b):\n    return a // b\n")]
    )
    refactorer = RefactorerAgent(StubProvider([good_patch]))
    auditor = AuditorAgent(StubProvider([]))  # nothing fails, never consulted

    fu = FileUnit(
        path=Path("mathutils.py"),
        original_source="def divide(a, b):\n    return a / b\n",
        deterministic_output="def divide(a, b):\n    return a / b\n",
        plan=MigrationPlan(
            steps=[PlanStep(finding_ref="ambiguous_division@2:11", description="use //", rationale="preserve py2 semantics")]
        ),
    )

    py3_runtime_for_c = _ScriptedRuntime(outputs=["RESULT:3\n"])
    characterization_info = CharacterizationInfo(
        cases=[TestCase(function_name="divide", args_literal="(7, 2)", rationale="typical")],
        evidence_source="docstring",
    )

    # Mode A/B don't apply here (no test_info, no __main__), so py2_runtime is
    # only exercised by run_mode_c - scripted to match what it expects.
    py2_runtime = _ScriptedRuntime(outputs=["RESULT:3\n"])

    result = migrate_file(
        fu,
        refactorer=refactorer,
        auditor=auditor,
        py2_runtime=py2_runtime,
        py3_runtime_for_c=py3_runtime_for_c,
        characterization_info=characterization_info,
    )

    assert result.status == Status.VERIFIED_INFERRED
    assert result.verify_result.behavior.mode == "C"
    assert result.verify_result.behavior.evidence_source == "docstring"


def test_migrate_file_stays_needs_review_without_characterization_info():
    """No test suite, no __main__, and no characterization_info generated
    (e.g. no eligible public functions) - falls through to plain UNVERIFIED,
    same as before Mode C existed. No amount of Mode C infrastructure existing
    should ever fabricate a pass when nothing was actually generated/run."""
    fu = FileUnit(
        path=Path("mathutils.py"),
        original_source="def _private(a, b):\n    return a / b\n",
        deterministic_output="def _private(a, b):\n    return a / b\n",
        plan=MigrationPlan(steps=[]),
    )
    py2_runtime = _ScriptedRuntime(outputs=[])

    result = migrate_file(
        fu,
        refactorer=RefactorerAgent(StubProvider([])),
        auditor=AuditorAgent(StubProvider([])),
        py2_runtime=py2_runtime,
        characterization_info=None,
    )

    assert result.status == Status.NEEDS_REVIEW
    assert "no characterization tests available" in result.reason
