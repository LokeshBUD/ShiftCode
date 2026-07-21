from shiftcode.agents.characterization import CharacterizationAgent
from shiftcode.models import CallSiteEvidence, CharacterizationTestPlan, TestCase

from fakes import StubProvider


def test_characterization_agent_returns_scripted_plan():
    plan = CharacterizationTestPlan(
        cases=[
            TestCase(function_name="clamp", args_literal="(5, 0, 10)", rationale="matches real call site"),
            TestCase(function_name="clamp", args_literal="(-1, 0, 10)", rationale="edge case: below range"),
        ]
    )
    provider = StubProvider([plan])
    agent = CharacterizationAgent(provider)

    result = agent.propose_tests(
        function_source="def clamp(value, low, high):\n    ...\n",
        docstring=None,
        call_site_evidence=[
            CallSiteEvidence(symbol="clamp", caller_file="calculator.py", args_repr="(5, 0, 10)", context_line=30)
        ],
    )

    assert result == plan
    assert "call-site" in provider.calls[0].lower() or "call site" in provider.calls[0].lower()


def test_characterization_agent_handles_no_evidence_or_docstring():
    plan = CharacterizationTestPlan(
        cases=[TestCase(function_name="is_even", args_literal="(4,)", rationale="typical even number")]
    )
    provider = StubProvider([plan])
    agent = CharacterizationAgent(provider)

    result = agent.propose_tests(
        function_source="def is_even(n):\n    return n % 2 == 0\n",
        docstring=None,
        call_site_evidence=[],
    )

    assert result == plan
    assert "(none found)" in provider.calls[0]
