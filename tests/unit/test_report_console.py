from pathlib import Path

from shiftcode.models import FileUnit, MigrationReport, Status
from shiftcode.pipeline.report import to_console


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
