from shiftcode.agents.characterization import CharacterizationAgent, FunctionContext
from shiftcode.models import (
    CallSiteEvidence,
    CharacterizationFuzzPlan,
    CharacterizationTestPlan,
    FunctionSeedPlan,
    ParamSeed,
    TestCase,
)

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
        functions=[
            FunctionContext(
                name="clamp",
                source="def clamp(value, low, high):\n    ...\n",
                docstring=None,
                call_site_evidence=[
                    CallSiteEvidence(
                        symbol="clamp", caller_file="calculator.py", args_repr="(5, 0, 10)", context_line=30
                    )
                ],
            )
        ]
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
        functions=[
            FunctionContext(
                name="is_even", source="def is_even(n):\n    return n % 2 == 0\n", docstring=None, call_site_evidence=[]
            )
        ]
    )

    assert result == plan
    assert "(none found)" in provider.calls[0]


def test_characterization_agent_batches_multiple_functions_into_one_call():
    plan = CharacterizationTestPlan(
        cases=[
            TestCase(function_name="a", args_literal="(1,)", rationale="typical"),
            TestCase(function_name="b", args_literal="(2,)", rationale="typical"),
        ]
    )
    provider = StubProvider([plan])
    agent = CharacterizationAgent(provider)

    result = agent.propose_tests(
        functions=[
            FunctionContext(name="a", source="def a(x):\n    return x\n", docstring=None, call_site_evidence=[]),
            FunctionContext(name="b", source="def b(x):\n    return x\n", docstring=None, call_site_evidence=[]),
        ]
    )

    assert result == plan
    assert len(provider.calls) == 1
    assert "## Function: a" in provider.calls[0]
    assert "## Function: b" in provider.calls[0]


def test_characterization_agent_propose_fuzz_seeds_returns_scripted_plan():
    plan = CharacterizationFuzzPlan(
        function_seed_plans=[
            FunctionSeedPlan(
                function_name="clamp",
                param_seeds=[
                    ParamSeed(param_index=0, seed_values_literal=["5", "-1", "0"], rationale="value to clamp"),
                    ParamSeed(param_index=1, seed_values_literal=["0"], rationale="low bound"),
                    ParamSeed(param_index=2, seed_values_literal=["10"], rationale="high bound"),
                ],
                anchor_cases=[TestCase(function_name="clamp", args_literal="(5, 0, 10)", rationale="real call site")],
            )
        ]
    )
    provider = StubProvider([plan])
    agent = CharacterizationAgent(provider)

    result = agent.propose_fuzz_seeds(
        functions=[
            FunctionContext(
                name="clamp",
                source="def clamp(value, low, high):\n    ...\n",
                docstring=None,
                call_site_evidence=[
                    CallSiteEvidence(
                        symbol="clamp", caller_file="calculator.py", args_repr="(5, 0, 10)", context_line=30
                    )
                ],
            )
        ]
    )

    assert result == plan
    assert "## Function: clamp" in provider.calls[0]
    assert "seed" in provider.calls[0].lower()
