"""End-to-end smoke test through the real pipeline (ingest -> analyze ->
deterministic transform -> Planner -> Refactorer <-> Auditor repair loop ->
verify -> report) against the bundled sample_project_py2 fixture, with
StubProvider standing in for the LLM so this runs with no network/API key.

Uses explicitly-constructed unavailable runtimes (not resolve_execution_runtimes()
against real machine state) so this test's outcome doesn't depend on whether
whatever machine runs the suite happens to have Docker/python2 installed - the
UNVERIFIED degrade path is what's under test here, deliberately, regardless of
environment. sandbox_runtime.py's own resolution logic is covered separately in
test_verify_gates.py.
"""

from pathlib import Path

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.characterization import CharacterizationAgent
from shiftcode.agents.planner import PlannerAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.agents.transform_auditor import TransformAuditorAgent
from shiftcode.models import (
    MigrationPlan,
    MigrationReport,
    PlanStep,
    RefactorPatch,
    RepairHint,
    Status,
    SymbolBlock,
    TransformAudit,
)
from shiftcode.pipeline.ingest import ingest
from shiftcode.pipeline.orchestrator import _discover_test_pairs, _process_file
from shiftcode.pipeline.report import to_json, to_text
from shiftcode.pipeline.verify.sandbox_runtime import ExecutionRuntimes, SandboxRuntime

from fakes import StubProvider

UNAVAILABLE_RUNTIME = SandboxRuntime(available=False, kind="unavailable", reason="no py2 runtime in this test")
# py3 side realistically always has a local fallback (it's the interpreter running
# ShiftCode itself) - only py2 unavailability is what's under test here; run_mode_a/b
# short-circuit on py2 unavailability before ever touching py3_runtime anyway.
_LOCAL_PY3 = SandboxRuntime(available=True, kind="local", interpreter_path="python3")
UNAVAILABLE_RUNTIMES = ExecutionRuntimes(
    py2=UNAVAILABLE_RUNTIME, py3_for_ab=_LOCAL_PY3, py3_for_c=UNAVAILABLE_RUNTIME
)

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_project_py2"

BROKEN_THEN_FIXED_DIVIDE = [
    RefactorPatch(
        blocks=[
            SymbolBlock(
                symbol="divide",
                # missing colon - deliberately broken to prove the repair loop engages for real
                new_source="def divide(a, b)\n    result = a / b\n    return result\n",
            ),
            SymbolBlock(
                symbol="safe_divide",
                new_source=(
                    "def safe_divide(a, b):\n"
                    "    try:\n"
                    "        return a // b\n"
                    "    except ZeroDivisionError as e:\n"
                    "        print('error:', e)\n"
                    "        return None\n"
                ),
            ),
        ]
    ),
    RefactorPatch(
        blocks=[
            SymbolBlock(
                symbol="divide",
                new_source="def divide(a, b):\n    result = a // b\n    return result\n",
            ),
            SymbolBlock(
                symbol="safe_divide",
                new_source=(
                    "def safe_divide(a, b):\n"
                    "    try:\n"
                    "        return a // b\n"
                    "    except ZeroDivisionError as e:\n"
                    "        print('error:', e)\n"
                    "        return None\n"
                ),
            ),
        ]
    ),
]


def test_full_pipeline_smoke_on_fixture_with_stub_provider():
    units = ingest(FIXTURE_ROOT)
    calc = next(u for u in units if u.path.name == "calculator.py")
    test_pairs = _discover_test_pairs(units)
    assert calc.path in test_pairs  # Mode A test pairing discovered correctly

    planner_provider = StubProvider(
        [
            MigrationPlan(
                steps=[
                    PlanStep(
                        finding_ref="ambiguous_division@6:13",
                        description="use // to preserve py2 floor-division semantics for divide()",
                        rationale="no `from __future__ import division` in the original file, so py2's `/` on two ints floor-divides",
                    ),
                    PlanStep(
                        finding_ref="ambiguous_division@19:15",
                        description="use // to preserve py2 floor-division semantics for safe_divide()",
                        rationale="same reasoning applies inside the try/except branch",
                    ),
                ]
            )
        ]
    )
    refactorer_provider = StubProvider(list(BROKEN_THEN_FIXED_DIVIDE))
    auditor_provider = StubProvider(
        [RepairHint(root_cause="missing colon after divide's signature", hint="add ':' at the end of the def line")]
    )

    planner = PlannerAgent(planner_provider)
    refactorer = RefactorerAgent(refactorer_provider)
    auditor = AuditorAgent(auditor_provider)
    # calc has test_info (Mode A applies), so Mode C never triggers and this
    # agent is never actually called - StubProvider([]) would raise if it were.
    characterization_agent = CharacterizationAgent(StubProvider([]))
    # deterministic_transform doesn't corrupt anything in this fixture, so the
    # real audit would report no concerns - stub the same empty result.
    transform_auditor = TransformAuditorAgent(StubProvider([TransformAudit(concerns=[])]))

    _process_file(
        calc,
        units,
        planner=planner,
        refactorer=refactorer,
        auditor=auditor,
        characterization_agent=characterization_agent,
        transform_auditor=transform_auditor,
        runtimes=UNAVAILABLE_RUNTIMES,
        max_attempts=3,
        determinism_runs=3,
        test_info=test_pairs.get(calc.path),
    )

    # Planner was consulted with both division findings and produced a real plan
    assert calc.plan is not None
    assert len(calc.plan.steps) == 2
    assert {s.finding_ref for s in calc.plan.steps} == {
        "ambiguous_division@6:13",
        "ambiguous_division@19:15",
    }

    # Refactorer's first (broken) attempt triggered the Auditor, second attempt fixed it
    assert len(calc.repair_attempts) == 2
    assert "SYNTAX_ERROR" in calc.repair_attempts[0].failure_summary
    assert calc.repair_attempts[0].hint == "add ':' at the end of the def line"
    assert calc.final_source is not None
    assert "def divide(a, b):" in calc.final_source
    assert "a // b" in calc.final_source

    # Honest degrade: no py2 runtime available -> UNVERIFIED -> NEEDS_REVIEW,
    # never a fabricated VERIFIED
    assert calc.status == Status.NEEDS_REVIEW
    assert calc.verify_result.syntax.passed
    assert calc.verify_result.behavior.outcome.value == "UNVERIFIED"

    # Report renders without error and reflects the same outcome
    report = MigrationReport(files=[calc])
    text = to_text(report)
    json_text = to_json(report)
    assert "NEEDS_REVIEW" in text
    assert "ambiguous_division" in json_text
