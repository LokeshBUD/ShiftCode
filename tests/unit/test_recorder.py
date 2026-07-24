"""shiftcode.record.recorder is stdlib-only and py2/py3-compatible by
design (see its own module docstring) - these tests run it directly under
whatever interpreter runs the suite, same as any other pure-Python unit
under test. Real py2 compatibility is separately confirmed live against
the real shiftcode-py2-sandbox Docker image (py_compile + a live decorated
call, run by hand during this feature's development)."""

import ast
import json

from shiftcode.record import recorder


def test_record_bare_decorator_captures_a_real_call(tmp_path):
    recorder._counts.clear()

    @recorder.record(out_dir=str(tmp_path))
    def add(a, b):
        return a + b

    assert add(2, 3) == 5  # the real call still happens and returns normally

    entries = (tmp_path / "add.jsonl").read_text().splitlines()
    assert len(entries) == 1
    entry = json.loads(entries[0])
    assert entry["function"] == "add"
    assert ast.literal_eval(entry["args_repr"]) == (2, 3)
    assert ast.literal_eval(entry["result_repr"]) == 5
    assert entry["exception"] is None


def test_record_called_form_with_max_entries(tmp_path):
    recorder._counts.clear()

    @recorder.record(max_entries=3, out_dir=str(tmp_path))
    def inc(x):
        return x + 1

    for i in range(10):
        inc(i)

    entries = (tmp_path / "inc.jsonl").read_text().splitlines()
    assert len(entries) == 3  # capped, not silently unbounded


def test_record_captures_exceptions_and_still_raises(tmp_path):
    recorder._counts.clear()

    @recorder.record(out_dir=str(tmp_path))
    def boom():
        raise ValueError("real failure")

    try:
        boom()
        assert False, "should have raised"
    except ValueError:
        pass

    entries = (tmp_path / "boom.jsonl").read_text().splitlines()
    entry = json.loads(entries[0])
    assert entry["exception"] == "ValueError"
    assert entry["result_repr"] is None


def test_record_silently_skips_unrepresentable_args_without_breaking_the_call(tmp_path):
    recorder._counts.clear()

    class NotRepresentable:
        def __repr__(self):
            return "<NotRepresentable object>"  # not literal-safe

    @recorder.record(out_dir=str(tmp_path))
    def f(obj):
        return "handled"

    # The real call must still happen and return normally...
    assert f(NotRepresentable()) == "handled"
    # ...but nothing gets written, since the arg doesn't round-trip through
    # repr()/ast.literal_eval.
    assert not (tmp_path / "f.jsonl").exists()


def test_record_captures_int_dict_keys_correctly_not_coerced_to_strings(tmp_path):
    """Real bug found via a real stress test against pytoolz/toolz's
    merge(): the earlier json.dumps(raw_value)-based design silently
    coerced dict keys to strings ({1: 'one'} -> {"1": "one"} on the wire),
    which would have caused false mismatches at replay time for any
    non-string-keyed dict - nothing to do with any real behavior
    difference. repr()-based recording preserves the real key type."""
    recorder._counts.clear()

    @recorder.record(out_dir=str(tmp_path))
    def merge(d):
        return dict(d)

    merge({1: "one", 2: "two"})

    entry = json.loads((tmp_path / "merge.jsonl").read_text().splitlines()[0])
    result = ast.literal_eval(entry["result_repr"])
    assert result == {1: "one", 2: "two"}
    assert set(result.keys()) == {1, 2}  # real int keys, not "1"/"2" strings


def test_record_captures_kwargs_too(tmp_path):
    """The recorder itself records kwargs faithfully - it's
    recording_loader.py's v1 scope decision to drop kwargs-using entries at
    LOAD time (see test_recording_loader.py), not something the recorder
    itself needs to know or decide about."""
    recorder._counts.clear()

    @recorder.record(out_dir=str(tmp_path))
    def greet(name, greeting="hello"):
        return f"{greeting}, {name}"

    greet("world", greeting="hi")

    entry = json.loads((tmp_path / "greet.jsonl").read_text().splitlines()[0])
    assert ast.literal_eval(entry["kwargs_repr"]) == {"greeting": "hi"}
