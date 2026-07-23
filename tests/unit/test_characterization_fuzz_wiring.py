"""orchestrator._build_characterization_info's branch on characterization_fuzz_cases:
0 (default) keeps today's propose_tests path unchanged; a positive value
switches to propose_fuzz_seeds + expand_function_seeds instead. Both paths
are exercised directly against the private function (same level the
existing _process_file/_discover_test_pairs orchestrator tests reach into),
with StubProvider standing in for the LLM."""

from pathlib import Path

from shiftcode.agents.characterization import CharacterizationAgent
from shiftcode.models import (
    CharacterizationFuzzPlan,
    CharacterizationTestPlan,
    FileUnit,
    FunctionSeedPlan,
    ParamSeed,
    TestCase,
)
from shiftcode.pipeline.orchestrator import _build_characterization_info

from fakes import StubProvider

SOURCE = "def divide(a, b):\n    return a // b\n"


def _file_unit() -> FileUnit:
    return FileUnit(path=Path("mathutils.py"), original_source=SOURCE)


def test_zero_fuzz_cases_uses_propose_tests_path():
    plan = CharacterizationTestPlan(
        cases=[TestCase(function_name="divide", args_literal="(7, 2)", rationale="typical")]
    )
    agent = CharacterizationAgent(StubProvider([plan]))

    info = _build_characterization_info(
        _file_unit(), [], agent, characterization_fuzz_cases=0
    )

    assert info is not None
    assert info.cases == plan.cases


def test_positive_fuzz_cases_uses_propose_fuzz_seeds_and_expands():
    fuzz_plan = CharacterizationFuzzPlan(
        function_seed_plans=[
            FunctionSeedPlan(
                function_name="divide",
                param_seeds=[
                    ParamSeed(param_index=0, seed_values_literal=["1", "2", "3", "4"], rationale="dividend"),
                    ParamSeed(param_index=1, seed_values_literal=["1", "2"], rationale="divisor"),
                ],
            )
        ]
    )
    agent = CharacterizationAgent(StubProvider([fuzz_plan]))

    info = _build_characterization_info(
        _file_unit(), [], agent, characterization_fuzz_cases=6
    )

    assert info is not None
    assert len(info.cases) == 6  # respects the requested case budget
    assert all(c.function_name == "divide" for c in info.cases)
    assert "call_sites" not in info.evidence_source  # no call-site evidence given here


def test_fuzz_path_returns_none_when_no_functions_seeded():
    fuzz_plan = CharacterizationFuzzPlan(function_seed_plans=[])
    agent = CharacterizationAgent(StubProvider([fuzz_plan]))

    info = _build_characterization_info(
        _file_unit(), [], agent, characterization_fuzz_cases=10
    )

    assert info is None
