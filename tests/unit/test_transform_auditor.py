from pathlib import Path

from shiftcode.agents.transform_auditor import TransformAuditorAgent
from shiftcode.models import FileUnit, TransformAudit, TransformConcern
from shiftcode.pipeline.orchestrator import _audit_deterministic_transform

from fakes import StubProvider


def test_transform_auditor_agent_returns_scripted_concerns():
    audit = TransformAudit(
        concerns=[
            TransformConcern(
                identifier="int",
                line=29,
                concern="fix_long renamed the `long` parameter, colliding with the int builtin",
            )
        ]
    )
    provider = StubProvider([audit])
    agent = TransformAuditorAgent(provider)

    result = agent.review(
        original_source="def f(long=None):\n    return long\n",
        deterministic_output="def f(long=None):\n    return int\n",
    )

    assert result == audit
    assert "fix_long" not in provider.calls[0]  # prompt doesn't presuppose the answer
    assert "long" in provider.calls[0]


def test_transform_auditor_agent_empty_concerns_is_the_common_case():
    audit = TransformAudit(concerns=[])
    provider = StubProvider([audit])
    agent = TransformAuditorAgent(provider)

    result = agent.review(original_source="def f():\n    pass\n", deterministic_output="def f():\n    pass\n")

    assert result.concerns == []


def test_audit_deterministic_transform_becomes_needs_llm_findings_with_detail():
    """Concerns become ordinary Py2Findings (needs_llm=True) carrying the
    agent's specific reasoning in `detail`, feeding into the same
    Planner -> Refactorer <-> Auditor loop everything else goes through."""
    audit = TransformAudit(
        concerns=[
            TransformConcern(identifier="int", line=29, concern="self.long now binds to the int type, not a value")
        ]
    )
    provider = StubProvider([audit])
    transform_auditor = TransformAuditorAgent(provider)
    fu = FileUnit(
        path=Path("docopt.py"),
        original_source="def f(long=None):\n    return long\n",
        deterministic_output="def f(long=None):\n    return int\n",
    )

    findings = _audit_deterministic_transform(fu, transform_auditor)

    assert len(findings) == 1
    assert findings[0].needs_llm is True
    assert findings[0].line == 29
    assert "int type" in findings[0].detail


def test_audit_deterministic_transform_empty_when_no_concerns():
    provider = StubProvider([TransformAudit(concerns=[])])
    transform_auditor = TransformAuditorAgent(provider)
    fu = FileUnit(path=Path("clean.py"), original_source="x = 1\n", deterministic_output="x = 1\n")

    findings = _audit_deterministic_transform(fu, transform_auditor)

    assert findings == []
