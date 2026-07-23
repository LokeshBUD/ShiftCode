from shiftcode.agents.fixer_rule import FixerRuleAgent
from shiftcode.models import GeneralizedFixRule
from shiftcode.pipeline.repair_history import RepairHistoryEntry

from fakes import StubProvider


def test_fixer_rule_agent_returns_scripted_rule():
    rule = GeneralizedFixRule(
        pattern_name="legacy_types_bare_import",
        trigger_description="from types import <LegacyType>",
        fix_description="remove the import, replace bare uses with the py3 builtin",
        safety_conditions=["name must be a known legacy types.X entry"],
        confidence=0.9,
        draft_detector_code="def _find_legacy_types_bare_import(tree):\n    return []\n",
    )
    provider = StubProvider([rule])
    agent = FixerRuleAgent(provider)

    entry = RepairHistoryEntry(
        file_path="slugify/__init__.py",
        before_source="from types import UnicodeType\n",
        after_source="",
        hints=["remove the import, replace UnicodeType with str"],
        failure_summaries=["ImportError: cannot import name 'UnicodeType' from 'types'"],
    )

    result = agent.propose_rule(entry=entry)

    assert result == rule
    assert "from types import UnicodeType" in provider.calls[0]
    assert "remove the import, replace UnicodeType with str" in provider.calls[0]


def test_fixer_rule_agent_includes_all_hints_and_failure_summaries():
    rule = GeneralizedFixRule(
        pattern_name="x",
        trigger_description="x",
        fix_description="x",
        safety_conditions=[],
        confidence=0.5,
        draft_detector_code="def _find_x(tree):\n    return []\n",
    )
    provider = StubProvider([rule])
    agent = FixerRuleAgent(provider)

    entry = RepairHistoryEntry(
        file_path="m.py",
        before_source="before",
        after_source="after",
        hints=["hint one", "hint two"],
        failure_summaries=["summary one", "summary two"],
    )

    agent.propose_rule(entry=entry)

    prompt = provider.calls[0]
    assert "hint one" in prompt
    assert "hint two" in prompt
    assert "summary one" in prompt
    assert "summary two" in prompt
