"""_parse_junit_xml replaced the old regex-parsed `unittest -v` text parsing
(docs/bug-log.md #2, #4 - both stemmed from interpreter-version-dependent
verbose-text formatting). JUnit XML has a stable schema regardless of
interpreter version or test style, so that bug class no longer applies here;
these tests just confirm the XML parsing itself.
"""

from shiftcode.pipeline.verify.behavior_gate import _parse_junit_xml

PASSING_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2">
<testcase classname="test_calculator" name="test_add" time="0.001" />
<testcase classname="test_calculator" name="test_divide" time="0.001" />
</testsuite></testsuites>
"""

FAILING_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2">
<testcase classname="test_calculator" name="test_add" time="0.001" />
<testcase classname="test_calculator" name="test_divide" time="0.001">
<failure message="assert 1 == 2">AssertionError</failure>
</testcase>
</testsuite></testsuites>
"""


def test_parses_all_passing_junit_xml():
    outcomes = _parse_junit_xml(PASSING_XML)
    assert outcomes == {"test_add": "ok", "test_divide": "ok"}


def test_parses_failure_in_junit_xml():
    outcomes = _parse_junit_xml(FAILING_XML)
    assert outcomes == {"test_add": "ok", "test_divide": "FAIL"}


def test_empty_xml_yields_no_outcomes():
    assert _parse_junit_xml("") == {}


def test_malformed_xml_yields_no_outcomes():
    assert _parse_junit_xml("not xml at all") == {}
