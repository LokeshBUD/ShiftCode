from shiftcode.pipeline.repair import is_test_filename


def test_matches_test_underscore_prefix():
    assert is_test_filename("test_calculator.py")


def test_matches_generic_tests_plural():
    """Regression: jsonschema's tests.py was wrongly treated as ordinary
    library code and characterization-tested (docs/bug-log.md #9)."""
    assert is_test_filename("tests.py")


def test_matches_generic_test_singular():
    assert is_test_filename("test.py")


def test_does_not_match_ordinary_module():
    assert not is_test_filename("calculator.py")


def test_does_not_match_unrelated_name_containing_test_substring():
    assert not is_test_filename("testing_utils.py")
