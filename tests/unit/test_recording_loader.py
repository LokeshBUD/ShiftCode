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


def _entry(args_repr, result_repr=None, exception=None, kwargs_repr=None, module="m", function="f"):
    return {
        "function": function,
        "module": module,
        "args_repr": args_repr,
        "kwargs_repr": kwargs_repr,
        "result_repr": result_repr,
        "exception": exception,
    }


def test_loads_a_valid_result_entry(tmp_path):
    _write_jsonl(tmp_path / "add.jsonl", _entry(function="add", args_repr="(2, 3)", result_repr="5"))

    cases = load_recordings(tmp_path)

    assert cases["add"] == [
        RecordedCase(function_name="add", args_literal="(2, 3)", expected_result_literal="5", module="m")
    ]


def test_loads_a_valid_exception_entry(tmp_path):
    _write_jsonl(tmp_path / "boom.jsonl", _entry(function="boom", args_repr="()", exception="ValueError"))

    cases = load_recordings(tmp_path)

    assert cases["boom"][0].expected_exception == "ValueError"
    assert cases["boom"][0].expected_result_literal is None


def test_preserves_real_int_dict_keys_not_coerced_to_strings(tmp_path):
    """Real bug found via a real stress test against pytoolz/toolz's
    merge(): the repr()-based wire format (recorder.py) preserves real
    dict key types - confirming the loader reads that back correctly too,
    not just that the recorder writes it correctly."""
    _write_jsonl(
        tmp_path / "merge.jsonl",
        _entry(function="merge", args_repr="({1: 'one', 2: 'two'},)", result_repr="{1: 'one', 2: 'two'}"),
    )

    cases = load_recordings(tmp_path)

    import ast

    result = ast.literal_eval(cases["merge"][0].expected_result_literal)
    assert set(result.keys()) == {1, 2}


def test_drops_entries_with_kwargs_without_failing_the_file(tmp_path):
    _write_jsonl(
        tmp_path / "f.jsonl",
        _entry(args_repr="(1,)", result_repr="1", kwargs_repr="{'x': 1}"),
        _entry(args_repr="(2,)", result_repr="2"),
    )

    cases = load_recordings(tmp_path)

    assert len(cases["f"]) == 1
    assert cases["f"][0].args_literal == "(2,)"


def test_drops_entries_with_an_unsafe_function_name(tmp_path):
    _write_jsonl(tmp_path / "weird.jsonl", _entry(function="os.system('x')", args_repr="()", result_repr="1"))

    cases = load_recordings(tmp_path)

    assert cases == {}


def test_drops_entries_with_a_non_literal_args_repr(tmp_path):
    """A recording file is an external, untrusted input - args_repr must
    still round-trip through ast.literal_eval even though the recorder
    already checked this once, since the file could have been tampered
    with or corrupted between recording and loading."""
    _write_jsonl(
        tmp_path / "f.jsonl", _entry(args_repr="__import__('os').system('x')", result_repr="1")
    )

    cases = load_recordings(tmp_path)

    assert cases == {}


def test_drops_malformed_json_lines_without_crashing(tmp_path):
    path = tmp_path / "f.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_entry(args_repr="(1,)", result_repr="1")) + "\nnot json at all\n")

    cases = load_recordings(tmp_path)

    assert len(cases["f"]) == 1


def test_caps_entries_per_function(tmp_path):
    entries = [_entry(args_repr=f"({i},)", result_repr=str(i)) for i in range(MAX_RECORDED_CASES_PER_FUNCTION + 20)]
    _write_jsonl(tmp_path / "f.jsonl", *entries)

    cases = load_recordings(tmp_path)

    assert len(cases["f"]) == MAX_RECORDED_CASES_PER_FUNCTION


def test_returns_empty_for_missing_directory(tmp_path):
    assert load_recordings(tmp_path / "does_not_exist") == {}
