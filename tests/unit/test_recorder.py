"""shiftcode.record.recorder is stdlib-only and py2/py3-compatible by
design (see its own module docstring) - these tests run it directly under
whatever interpreter runs the suite, same as any other pure-Python unit
under test. Real py2 compatibility is separately confirmed live against
the real shiftcode-py2-sandbox Docker image (py_compile + a live decorated
call, run by hand during this feature's development)."""

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
    assert entry["args"] == [2, 3]
    assert entry["result"] == 5
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
    assert entry["result"] is None


def test_record_silently_skips_non_json_serializable_args_without_breaking_the_call(tmp_path):
    recorder._counts.clear()

    class NotSerializable:
        pass

    @recorder.record(out_dir=str(tmp_path))
    def f(obj):
        return "handled"

    # The real call must still happen and return normally...
    assert f(NotSerializable()) == "handled"
    # ...but nothing gets written, since the arg can't be JSON-serialized.
    assert not (tmp_path / "f.jsonl").exists()


def test_record_captures_kwargs_too(tmp_path):
    recorder._counts.clear()

    @recorder.record(out_dir=str(tmp_path))
    def greet(name, greeting="hello"):
        return f"{greeting}, {name}"

    greet("world", greeting="hi")

    entry = json.loads((tmp_path / "greet.jsonl").read_text().splitlines()[0])
    assert entry["kwargs"] == {"greeting": "hi"}
