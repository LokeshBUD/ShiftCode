import pytest

from shiftcode.pipeline.transform.deterministic import (
    DeterministicTransformError,
    deterministic_transform,
)
from shiftcode.pipeline.verify.syntax_gate import check_syntax


def test_deterministic_transform_fixes_mechanical_constructs():
    src = 'print "hi"\nfor i in xrange(3):\n    print i\n'
    out = deterministic_transform(src)
    assert "print(" in out
    assert "xrange" not in out
    assert "range(3)" in out


def test_deterministic_transform_leaves_division_untouched():
    src = "def f(a, b):\n    return a / b\n"
    out = deterministic_transform(src)
    assert "a / b" in out


def test_deterministic_transform_raises_on_unparseable_source():
    with pytest.raises(DeterministicTransformError):
        deterministic_transform("def f(:\n    pass\n")


def test_syntax_gate_passes_valid_source():
    result = check_syntax("def f():\n    return 1\n")
    assert result.passed
    assert result.error_message is None


def test_syntax_gate_reports_line_and_message_on_failure():
    result = check_syntax("def f(:\n    pass\n")
    assert not result.passed
    assert result.error_line == 1
    assert result.error_message
