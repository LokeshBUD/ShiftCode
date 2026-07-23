from pathlib import Path

from shiftcode.models import FileUnit
from shiftcode.pipeline.orchestrator import _discover_test_pairs


def _fu(path: Path) -> FileUnit:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n")
    return FileUnit(path=path, original_source="x = 1\n")


def test_matches_test_prefixed_sibling(tmp_path):
    m = _fu(tmp_path / "m.py")
    _fu(tmp_path / "test_m.py")

    pairs = _discover_test_pairs([m, FileUnit(path=tmp_path / "test_m.py", original_source="")])

    assert m.path in pairs
    assert pairs[m.path].test_filename == "test_m.py"


def test_matches_test_prefixed_in_tests_subdir(tmp_path):
    m = _fu(tmp_path / "m.py")
    (tmp_path / "tests").mkdir()
    _fu(tmp_path / "tests" / "test_m.py")

    pairs = _discover_test_pairs([m])

    assert m.path in pairs


def test_generic_tests_py_pairs_with_sole_real_module(tmp_path):
    """Regression from real stress tests (jsonschema.py + tests.py,
    purl/__init__.py + tests.py): the test_<name>.py convention doesn't
    apply at all, but tests.py clearly tests the one real module present."""
    module = _fu(tmp_path / "jsonschema.py")
    setup = _fu(tmp_path / "setup.py")
    _fu(tmp_path / "tests.py")

    pairs = _discover_test_pairs([module, setup])

    assert module.path in pairs
    assert pairs[module.path].test_filename == "tests.py"
    assert setup.path not in pairs  # setup.py isn't the tested module


def test_generic_test_py_singular_also_matches(tmp_path):
    module = _fu(tmp_path / "__init__.py")
    _fu(tmp_path / "test.py")

    pairs = _discover_test_pairs([module])

    assert module.path in pairs


def test_conf_py_does_not_block_generic_fallback(tmp_path):
    """conf.py (Sphinx docs config) isn't library code - a real module sharing
    a directory with it should still be treated as the sole real module."""
    module = _fu(tmp_path / "__init__.py")
    conf = _fu(tmp_path / "conf.py")
    setup = _fu(tmp_path / "setup.py")
    _fu(tmp_path / "tests.py")

    pairs = _discover_test_pairs([module, conf, setup])

    assert module.path in pairs


def test_generic_fallback_skipped_when_multiple_real_modules_present(tmp_path):
    """Must not blindly pair a shared tests.py with every file in a
    multi-module directory - that would misleadingly run the same suite
    against unrelated modules."""
    a = _fu(tmp_path / "a.py")
    b = _fu(tmp_path / "b.py")
    _fu(tmp_path / "tests.py")

    pairs = _discover_test_pairs([a, b])

    assert pairs == {}


def test_no_match_when_nothing_present(tmp_path):
    m = _fu(tmp_path / "m.py")
    assert _discover_test_pairs([m]) == {}


def test_non_package_module_matches_test_in_sibling_tests_directory(tmp_path):
    """Real, common shape confirmed on `jek/blinker`: `blinker/_saferef.py`
    (a non-package module) is tested by a project-root `tests/test_saferef.py`
    - a sibling tests/ directory one level ABOVE the module's own directory,
    same principle as the __init__.py-specific sibling-tests-dir case below
    but generalized to any module, not just packages (docs/bug-log.md #24)."""
    module = _fu(tmp_path / "blinker" / "_saferef.py")
    (tmp_path / "tests").mkdir()
    _fu(tmp_path / "tests" / "test_saferef.py")

    pairs = _discover_test_pairs([module])

    assert module.path in pairs
    assert pairs[module.path].test_filename == "test_saferef.py"


def test_leading_underscore_module_also_matches_without_the_underscore_same_dir(tmp_path):
    module = _fu(tmp_path / "_utilities.py")
    _fu(tmp_path / "test_utilities.py")

    pairs = _discover_test_pairs([module])

    assert module.path in pairs
    assert pairs[module.path].test_filename == "test_utilities.py"


def test_dunder_module_does_not_get_underscore_stripped(tmp_path):
    """__main__.py-style dunder names must not have a single leading
    underscore stripped (that would garble the name, not simplify it) -
    only a real single-underscore "private module" convention qualifies."""
    module = _fu(tmp_path / "__main__.py")
    _fu(tmp_path / "test_main__.py")  # would only match if strip logic were wrong

    pairs = _discover_test_pairs([module])

    assert module.path not in pairs


def test_package_init_matches_generic_test_py_in_singular_test_directory(tmp_path):
    """Real shape confirmed on `kislyuk/argcomplete`: a project-root `test/`
    directory (SINGULAR, not "tests") containing a generically-named
    test.py that tests the whole package via `from argcomplete import *` -
    docs/bug-log.md #26. Same axis of naming variance as bug #9's
    tests.py/test.py filename fix, one level up on the directory name."""
    init = _fu(tmp_path / "argcomplete" / "__init__.py")
    (tmp_path / "test").mkdir()
    _fu(tmp_path / "test" / "test.py")

    pairs = _discover_test_pairs([init])

    assert init.path in pairs
    assert pairs[init.path].test_filename == "test.py"


def test_non_package_module_matches_test_in_singular_test_directory(tmp_path):
    module = _fu(tmp_path / "pkg" / "_utils.py")
    (tmp_path / "test").mkdir()
    _fu(tmp_path / "test" / "test_utils.py")

    pairs = _discover_test_pairs([module])

    assert module.path in pairs
    assert pairs[module.path].test_filename == "test_utils.py"


def test_package_init_matches_test_named_after_package_directory(tmp_path):
    """Real, common convention: mypkg/tests/test_mypkg.py for
    mypkg/__init__.py - named after the package (parent directory), not
    literally "__init__". Legitimate with real directory structure
    preserved, unlike the flattened-extraction-artifact case (bug-log.md #9)."""
    init = _fu(tmp_path / "mypkg" / "__init__.py")
    (tmp_path / "mypkg" / "tests").mkdir()
    _fu(tmp_path / "mypkg" / "tests" / "test_mypkg.py")

    pairs = _discover_test_pairs([init])

    assert init.path in pairs
    assert pairs[init.path].test_filename == "test_mypkg.py"


def test_package_init_matches_test_named_after_package_directory_same_dir(tmp_path):
    init = _fu(tmp_path / "mypkg" / "__init__.py")
    _fu(tmp_path / "mypkg" / "test_mypkg.py")

    pairs = _discover_test_pairs([init])

    assert init.path in pairs
    assert pairs[init.path].test_filename == "test_mypkg.py"


def test_package_init_matches_test_sibling_to_package_directory(tmp_path):
    """Real, common convention confirmed on two real libraries (purl,
    requests): the test file sits OUTSIDE the package, as a sibling to the
    package directory itself - e.g. repo_root/test_requests.py for
    repo_root/requests/__init__.py (docs/bug-log.md #17)."""
    init = _fu(tmp_path / "requests" / "__init__.py")
    _fu(tmp_path / "test_requests.py")

    pairs = _discover_test_pairs([init])

    assert init.path in pairs
    assert pairs[init.path].test_filename == "test_requests.py"


def test_package_init_matches_test_in_sibling_tests_directory(tmp_path):
    init = _fu(tmp_path / "requests" / "__init__.py")
    (tmp_path / "tests").mkdir()
    _fu(tmp_path / "tests" / "test_requests.py")

    pairs = _discover_test_pairs([init])

    assert init.path in pairs
    assert pairs[init.path].test_filename == "test_requests.py"


def test_package_init_matches_generic_tests_py_in_sibling_tests_directory(tmp_path):
    """purl's exact real (un-flattened) shape: a sibling tests/ directory
    containing a GENERICALLY-named tests.py, not package-named
    (docs/bug-log.md #17)."""
    init = _fu(tmp_path / "purl" / "__init__.py")
    (tmp_path / "tests").mkdir()
    _fu(tmp_path / "tests" / "tests.py")

    pairs = _discover_test_pairs([init])

    assert init.path in pairs
    assert pairs[init.path].test_filename == "tests.py"
