"""End-to-end: a killed mid-run migration previously lost everything - no
state was ever persisted until the whole run finished (docs/bug-log.md).
config.checkpoint_dir makes a second run against the same directory skip any
file whose source hasn't changed and which already reached a terminal
status, with zero further LLM calls for it."""

from pathlib import Path

import pytest

from shiftcode.config import LLMConfig, ShiftConfig
from shiftcode.models import MigrationPlan, PlanStep, RefactorPatch, Status, SymbolBlock, TransformAudit
from shiftcode.pipeline import orchestrator as orchestrator_module
from shiftcode.pipeline.orchestrator import run_migration

from fakes import StubProvider

DIVISION_SOURCE = "def f(a, b):\n    return a / b\n"

_PLAN = MigrationPlan(
    steps=[PlanStep(finding_ref="ambiguous_division@2:11", description="use //", rationale="preserve py2 semantics")]
)
_PATCH = RefactorPatch(blocks=[SymbolBlock(symbol="f", new_source="def f(a, b):\n    return a // b\n")])


@pytest.fixture
def one_file_project(tmp_path):
    (tmp_path / "m.py").write_text(DIVISION_SOURCE)
    return tmp_path


def _install_providers(monkeypatch, *, planner, refactorer):
    providers_by_role = {
        "planner": planner,
        "transform_auditor": StubProvider([TransformAudit(concerns=[])]),
        "refactorer": refactorer,
        "auditor": StubProvider([]),
        "characterization": StubProvider([]),
    }

    def fake_get_provider(config, *, name="openai-compatible"):
        return providers_by_role[name]

    monkeypatch.setattr(orchestrator_module, "get_provider", fake_get_provider)


def test_second_run_with_checkpoint_skips_reprocessing_a_completed_file(monkeypatch, tmp_path, one_file_project):
    checkpoint_dir = tmp_path / "ckpt"
    config = ShiftConfig(llm=LLMConfig(), agent_overrides={}, checkpoint_dir=str(checkpoint_dir))

    _install_providers(monkeypatch, planner=StubProvider([_PLAN]), refactorer=StubProvider([_PATCH]))
    first_report = run_migration(one_file_project, config)
    assert first_report.files[0].status == Status.NEEDS_REVIEW  # no py2 runtime here - UNVERIFIED, correct and honest
    first_reason = first_report.files[0].reason

    # Providers that would raise AssertionError if actually called - proves
    # the second run genuinely skips re-processing rather than just
    # happening to produce the same result again.
    _install_providers(monkeypatch, planner=StubProvider([]), refactorer=StubProvider([]))
    second_report = run_migration(one_file_project, config)

    assert second_report.files[0].status == Status.NEEDS_REVIEW
    assert second_report.files[0].reason == first_reason
    assert second_report.files[0].plan is not None
    assert len(second_report.files[0].plan.steps) == 1


def test_changed_source_is_not_resumed_from_a_stale_checkpoint(monkeypatch, tmp_path, one_file_project):
    checkpoint_dir = tmp_path / "ckpt"
    config = ShiftConfig(llm=LLMConfig(), agent_overrides={}, checkpoint_dir=str(checkpoint_dir))

    _install_providers(monkeypatch, planner=StubProvider([_PLAN]), refactorer=StubProvider([_PATCH]))
    run_migration(one_file_project, config)

    (one_file_project / "m.py").write_text("def f(a, b):\n    return a - b\n")  # real content change, no findings now

    # A fresh planner/refactorer that would raise if called with the OLD
    # division-finding prompt shape - only the empty-plan fast path should
    # engage for the changed file, exactly as if there were no checkpoint.
    _install_providers(monkeypatch, planner=StubProvider([]), refactorer=StubProvider([]))
    second_report = run_migration(one_file_project, config)

    assert second_report.files[0].plan.steps == []  # real fresh analysis, not the stale division-finding plan
