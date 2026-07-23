import json
from pathlib import Path

from shiftcode.pipeline.verify.recording_loader import (
    MAX_RECORDED_CASES_PER_FUNCTION,
    load_recordings,
    RecordedCase,
)


def _write_jsonl(path: Path, *entries: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_loads_a_valid_result_entry(tmp_path):
    _write_jsonl(
        tmp_path / "add.jsonl",
        {"function": "add", "module": "m", "args": [2, 3], "kwargs": {}, "result": 5, "exception": None},
    )

    cases = load_recordings(tmp_path)

    assert cases["add"] == [
        RecordedCase(function_name="add", args_literal="(2, 3)", expected_result_literal="5", module="m")
    ]


def test_loads_a_valid_exception_entry(tmp_path):
    _write_jsonl(
        tmp_path / "boom.jsonl",
        {"function": "boom", "module": "m", "args": [], "kwargs": {}, "result": None, "exception": "ValueError"},
    )

    cases = load_recordings(tmp_path)

    assert cases["boom"][0].expected_exception == "ValueError"
    assert cases["boom"][0].expected_result_literal is None


def test_drops_entries_with_kwargs_without_failing_the_file(tmp_path):
    _write_jsonl(
        tmp_path / "f.jsonl",
        {"function": "f", "args": [1], "kwargs": {"x": 1}, "result": 1, "exception": None},
        {"function": "f", "args": [2], "kwargs": {}, "result": 2, "exception": None},
    )

    cases = load_recordings(tmp_path)

    assert len(cases["f"]) == 1
    assert cases["f"][0].args_literal == "(2,)"


def test_drops_entries_with_an_unsafe_function_name(tmp_path):
    _write_jsonl(
        tmp_path / "weird.jsonl",
        {"function": "os.system('x')", "args": [], "kwargs": {}, "result": 1, "exception": None},
    )

    cases = load_recordings(tmp_path)

    assert cases == {}


def test_drops_malformed_json_lines_without_crashing(tmp_path):
    path = tmp_path / "f.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"function": "f", "args": [1], "kwargs": {}, "result": 1}\nnot json at all\n')

    cases = load_recordings(tmp_path)

    assert len(cases["f"]) == 1


def test_caps_entries_per_function(tmp_path):
    entries = [
        {"function": "f", "args": [i], "kwargs": {}, "result": i, "exception": None}
        for i in range(MAX_RECORDED_CASES_PER_FUNCTION + 20)
    ]
    _write_jsonl(tmp_path / "f.jsonl", *entries)

    cases = load_recordings(tmp_path)

    assert len(cases["f"]) == MAX_RECORDED_CASES_PER_FUNCTION


def test_returns_empty_for_missing_directory(tmp_path):
    assert load_recordings(tmp_path / "does_not_exist") == {}
