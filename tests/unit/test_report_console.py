import json
from pathlib import Path

from shiftcode.models import BehaviorResult, FileUnit, GateOutcome, MigrationReport, Status, VerifyResult
from shiftcode.pipeline.report import to_console, to_json, to_text


def _report() -> MigrationReport:
    return MigrationReport(
        files=[
            FileUnit(path=Path("a.py"), original_source="", status=Status.VERIFIED),
            FileUnit(path=Path("b.py"), original_source="", status=Status.NEEDS_REVIEW, reason="something failed"),
        ]
    )


def test_to_console_with_color_includes_ansi_codes():
    text = to_console(_report(), color=True)
    assert "\033[" in text
    assert "a.py" in text
    assert "b.py" in text
    assert "something failed" in text


def test_to_console_without_color_has_no_ansi_codes():
    text = to_console(_report(), color=False)
    assert "\033[" not in text
    assert "[VERIFIED]" in text
    assert "[NEEDS_REVIEW]" in text


def _file_with_behavior(behavior: BehaviorResult) -> FileUnit:
    return FileUnit(
        path=Path("m.py"),
        original_source="",
        status=Status.VERIFIED,
        verify_result=VerifyResult(behavior=behavior),
    )


def test_cases_summary_line_rendered_for_mode_a_and_mode_c():
    mode_a_file = _file_with_behavior(
        BehaviorResult(outcome=GateOutcome.FAIL, mode="A", cases_run=209, cases_passed=206)
    )
    mode_c_file = _file_with_behavior(
        BehaviorResult(outcome=GateOutcome.PASS, mode="C", cases_run=20, cases_passed=20, evidence_source="call_sites")
    )
    report = MigrationReport(files=[mode_a_file, mode_c_file])

    text = to_text(report)
    console = to_console(report, color=False)
    for rendered in (text, console):
        assert "206/209 cases passed (Mode A)" in rendered
        assert "20/20 cases passed (Mode C) (evidence: call_sites)" in rendered


def test_cases_summary_line_omitted_when_not_countable():
    mode_b_file = _file_with_behavior(BehaviorResult(outcome=GateOutcome.PASS, mode="B"))
    unverified_file = _file_with_behavior(BehaviorResult(outcome=GateOutcome.UNVERIFIED, mode="A"))
    report = MigrationReport(files=[mode_b_file, unverified_file])

    text = to_text(report)
    console = to_console(report, color=False)
    for rendered in (text, console):
        assert "cases passed" not in rendered


def test_json_report_includes_case_counts():
    report = MigrationReport(
        files=[_file_with_behavior(BehaviorResult(outcome=GateOutcome.PASS, mode="C", cases_run=5, cases_passed=5))]
    )
    data = json.loads(to_json(report))
    behavior = data["files"][0]["verify"]["behavior"]
    assert behavior["cases_run"] == 5
    assert behavior["cases_passed"] == 5
