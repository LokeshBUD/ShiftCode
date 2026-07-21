import pytest

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.base import AgentOutputError
from shiftcode.agents.planner import PlannerAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.llm.errors import LLMOutputError
from shiftcode.models import MigrationPlan, PlanStep, RefactorPatch, RepairHint, SymbolBlock

from fakes import StubProvider


def test_planner_agent_returns_scripted_plan():
    plan = MigrationPlan(
        steps=[PlanStep(finding_ref="division@2:13", description="use //", rationale="preserve py2 floor semantics")]
    )
    provider = StubProvider([plan])
    agent = PlannerAgent(provider)

    result = agent.plan(original_source="def f(a,b):\n    return a/b\n", findings=[], dependency_slices=[])

    assert result == plan
    assert len(provider.calls) == 1


def test_refactorer_agent_splices_scripted_patch():
    patch = RefactorPatch(
        blocks=[SymbolBlock(symbol="divide", new_source="def divide(a, b):\n    return a // b\n")]
    )
    provider = StubProvider([patch])
    agent = RefactorerAgent(provider)
    plan = MigrationPlan(steps=[PlanStep(finding_ref="x", description="y", rationale="z")])

    result = agent.refactor(
        deterministic_source="def divide(a, b):\n    return a / b\n", plan=plan
    )

    assert "return a // b" in result


def test_auditor_agent_returns_scripted_hint():
    hint = RepairHint(root_cause="wrong operator", hint="use // instead of /")
    provider = StubProvider([hint])
    agent = AuditorAgent(provider)
    plan = MigrationPlan(steps=[])

    result = agent.diagnose(
        deterministic_source="a / b",
        plan=plan,
        candidate_source="a / b",
        failure_detail="SYNTAX_ERROR: none, BEHAVIOR mismatch",
    )

    assert result == hint


def test_planner_agent_raises_agent_output_error_after_malformed_json_retries():
    provider = StubProvider([LLMOutputError("bad json"), LLMOutputError("still bad")])
    agent = PlannerAgent(provider, max_retries=1)

    with pytest.raises(AgentOutputError):
        agent.plan(original_source="x = 1\n", findings=[], dependency_slices=[])

    assert len(provider.calls) == 2
