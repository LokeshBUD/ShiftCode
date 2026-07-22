"""Regression: one file hitting an unexpected error (in the real incident, an
LLMTimeoutError escaping call_structured uncaught) crashed the entire
`run_migration` call - no report was produced at all, losing results for
every already-processed file. run_migration's per-file loop must isolate one
file's failure from the rest of the batch."""

from pathlib import Path

import pytest

from shiftcode.models import MigrationPlan, PlanStep, RefactorPatch, Status, SymbolBlock, TransformAudit
from shiftcode.pipeline import orchestrator as orchestrator_module
from shiftcode.pipeline.orchestrator import run_migration

from fakes import StubProvider

DIVISION_SOURCE = "def f(a, b):\n    return a / b\n"


class _RaisesOnceThenPlans(StubProvider):
    """First call: an unexpected, non-AgentOutputError exception (simulating
    any surprise failure, not just the specific LLMTimeoutError from the real
    incident). Subsequent calls: a real plan."""

    def __init__(self):
        super().__init__([])
        self._call_count = 0

    def generate_structured(self, prompt, *, schema, system=None, temperature=0.0):
        self._call_count += 1
        if self._call_count == 1:
            raise RuntimeError("simulated unexpected failure on the first file")
        return MigrationPlan(
            steps=[PlanStep(finding_ref="ambiguous_division@2:11", description="use //", rationale="preserve py2 semantics")]
        )


@pytest.fixture
def two_file_project(tmp_path):
    (tmp_path / "file_a.py").write_text(DIVISION_SOURCE)
    (tmp_path / "file_b.py").write_text(DIVISION_SOURCE)
    return tmp_path


def test_one_files_unexpected_failure_does_not_crash_the_whole_run(monkeypatch, two_file_project):
    planner_provider = _RaisesOnceThenPlans()
    providers_by_role = {
        "planner": planner_provider,
        "transform_auditor": StubProvider([TransformAudit(concerns=[]), TransformAudit(concerns=[])]),
        "refactorer": StubProvider(
            [RefactorPatch(blocks=[SymbolBlock(symbol="f", new_source="def f(a, b):\n    return a // b\n")])]
        ),
        "auditor": StubProvider([]),
        "characterization": StubProvider([]),
    }

    def fake_get_provider(config, *, name="openai-compatible"):
        return providers_by_role[name]

    monkeypatch.setattr(orchestrator_module, "get_provider", fake_get_provider)

    from shiftcode.config import LLMConfig, ShiftConfig

    config = ShiftConfig(llm=LLMConfig(), agent_overrides={})

    report = run_migration(two_file_project, config)

    assert len(report.files) == 2
    by_name = {f.path.name: f for f in report.files}

    # file_a hit the unexpected failure - degraded, not lost.
    assert by_name["file_a.py"].status == Status.NEEDS_REVIEW
    assert "unexpected error" in by_name["file_a.py"].reason

    # file_b was still fully processed despite file_a's failure - this is the
    # actual point of the fix. Its plan should reflect the real (second) call.
    assert by_name["file_b.py"].plan is not None
    assert len(by_name["file_b.py"].plan.steps) == 1
