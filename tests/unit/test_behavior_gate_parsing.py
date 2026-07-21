"""Regression test for a real bug found running against a real py2 (Docker) and
real py3 side by side: Python 2's `unittest -v` verbose format is
`test_name (module.Class) ... ok`, but Python 3 (3.11+) changed this to
`test_name (module.Class.test_name) ... ok` - the method name is repeated
inside the parens. Keying comparisons by the full "(...)" qualname made every
single test look like a py2-vs-py3 mismatch, even ones that behaved identically.
"""

from shiftcode.pipeline.verify.behavior_gate import _parse_unittest_output

PY2_STYLE_STDERR = """\
test_add (test_calculator.CalculatorTest) ... ok
test_divide_preserves_py2_floor_semantics (test_calculator.CalculatorTest) ... ok
"""

PY3_STYLE_STDERR = """\
test_add (test_calculator.CalculatorTest.test_add) ... ok
test_divide_preserves_py2_floor_semantics (test_calculator.CalculatorTest.test_divide_preserves_py2_floor_semantics) ... FAIL
"""


def test_parses_py2_style_verbose_output():
    outcomes = _parse_unittest_output(PY2_STYLE_STDERR)
    assert outcomes == {"test_add": "ok", "test_divide_preserves_py2_floor_semantics": "ok"}


def test_parses_py3_style_verbose_output():
    outcomes = _parse_unittest_output(PY3_STYLE_STDERR)
    assert outcomes == {"test_add": "ok", "test_divide_preserves_py2_floor_semantics": "FAIL"}


def test_matching_test_names_compare_equal_across_py2_and_py3_formats():
    py2 = _parse_unittest_output(PY2_STYLE_STDERR)
    py3 = _parse_unittest_output(PY3_STYLE_STDERR)
    # test_add behaves identically and must NOT show up as a mismatch just
    # because the two interpreters format the test name differently.
    assert py2["test_add"] == py3["test_add"] == "ok"
    # the real divide bug must still be visible as a genuine mismatch.
    assert py2["test_divide_preserves_py2_floor_semantics"] != py3["test_divide_preserves_py2_floor_semantics"]
