from pathlib import Path

from shiftcode.models import FileUnit, RepairAttempt, Status
from shiftcode.pipeline.repair_history import (
    RepairHistoryEntry,
    append_repair_history,
    load_repair_history,
    qualifying_repair,
)


def _file_unit(**overrides) -> FileUnit:
    fields = {
        "path": Path("m.py"),
        "original_source": "original",
        "status": Status.PENDING,
        "final_source": None,
        "repair_attempts": [],
    }
    fields.update(overrides)
    return FileUnit(**fields)


def test_qualifying_repair_none_for_needs_review():
    fu = _file_unit(status=Status.NEEDS_REVIEW)
    assert qualifying_repair(fu) is None


def test_qualifying_repair_none_for_verified_with_zero_repair_attempts():
    fu = _file_unit(status=Status.VERIFIED, final_source="fixed", repair_attempts=[])
    assert qualifying_repair(fu) is None


def test_qualifying_repair_none_when_no_attempt_has_a_hint():
    fu = _file_unit(
        status=Status.VERIFIED,
        final_source="fixed",
        repair_attempts=[RepairAttempt(attempt_number=1, candidate_source="x", failure_summary="SYNTAX_ERROR")],
    )
    assert qualifying_repair(fu) is None


def test_qualifying_repair_populated_when_a_real_hint_exists():
    fu = _file_unit(
        status=Status.VERIFIED_INFERRED,
        original_source="before",
        final_source="after",
        repair_attempts=[
            RepairAttempt(
                attempt_number=1,
                candidate_source="broken",
                failure_summary="TypeError: bytes vs str",
                hint="add .decode('ascii') after .encode(...)",
            )
        ],
    )
    entry = qualifying_repair(fu)
    assert entry is not None
    assert entry.before_source == "before"
    assert entry.after_source == "after"
    assert entry.hints == ["add .decode('ascii') after .encode(...)"]
    assert entry.failure_summaries == ["TypeError: bytes vs str"]


def test_append_repair_history_writes_valid_jsonl_and_appends_not_truncates(tmp_path):
    path = tmp_path / "history" / "repair_history.jsonl"
    first = RepairHistoryEntry(file_path="a.py", before_source="b1", after_source="a1", hints=["h1"])
    second = RepairHistoryEntry(file_path="b.py", before_source="b2", after_source="a2", hints=["h2"])

    append_repair_history([first], path)
    append_repair_history([second], path)

    loaded = load_repair_history(path)
    assert loaded == [first, second]


def test_append_repair_history_noop_on_empty_list(tmp_path):
    path = tmp_path / "repair_history.jsonl"
    append_repair_history([], path)
    assert not path.exists()


def test_load_repair_history_returns_empty_for_missing_file(tmp_path):
    assert load_repair_history(tmp_path / "does_not_exist.jsonl") == []
