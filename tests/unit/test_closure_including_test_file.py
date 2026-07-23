"""Regression from a real end-to-end run (`pytoolz/toolz` @ `498fefa`):
`_closure_including_test_file` merges the module-under-test's own
dependency closure with the paired test file's own closure - a test file
can have real local imports the module itself never references (real case:
`toolz/dicttoolz/tests/test_core.py` does `from toolz.utils import raises`,
but nothing in `dicttoolz/core.py` imports toolz.utils at all)."""

from pathlib import Path

from shiftcode.models import FileUnit
from shiftcode.pipeline.orchestrator import _closure_including_test_file
from shiftcode.pipeline.repair import BehaviorTestInfo


def _write(path: Path, source: str) -> FileUnit:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return FileUnit(path=path, original_source=source)


def test_merges_test_files_own_closure_with_the_modules(tmp_path):
    module = _write(tmp_path / "pkg" / "core.py", "def merge(*d):\n    return d\n")
    utils = _write(tmp_path / "pkg" / "utils.py", "def raises(exc, f):\n    pass\n")
    test_file = _write(
        tmp_path / "pkg" / "tests" / "test_core.py",
        "from pkg.utils import raises\nfrom pkg.core import merge\n",
    )
    all_units = [module, utils, test_file]
    test_info = BehaviorTestInfo(test_filename="test_core.py", test_source=test_file.original_source, test_path=test_file.path)

    closure = _closure_including_test_file(module, test_info, all_units, tmp_path, max_closure_files=20)

    assert {cf.rel_path for cf in closure} == {utils.path.relative_to(tmp_path)}


def test_excludes_the_module_under_test_itself_from_the_merged_closure(tmp_path):
    """Real bug caught while writing this test: a test file almost always
    imports the module it's testing, so the test file's own closure resolves
    an edge right back to it - merging that in would let write_sandbox_tree's
    closure-write step (which runs AFTER the module is written) silently
    overwrite the actual live candidate source being verified with the
    FileUnit's stale original/final source, verifying the wrong thing with
    no error at all."""
    module = _write(tmp_path / "pkg" / "core.py", "def merge(*d):\n    return d\n")
    test_file = _write(tmp_path / "pkg" / "tests" / "test_core.py", "from pkg.core import merge\n")
    all_units = [module, test_file]
    test_info = BehaviorTestInfo(test_filename="test_core.py", test_source=test_file.original_source, test_path=test_file.path)

    closure = _closure_including_test_file(module, test_info, all_units, tmp_path, max_closure_files=20)

    assert module.path.relative_to(tmp_path) not in {cf.rel_path for cf in closure}


def test_returns_just_the_modules_closure_when_no_test_info(tmp_path):
    module = _write(tmp_path / "pkg" / "core.py", "def merge(*d):\n    return d\n")

    closure = _closure_including_test_file(module, None, [module], tmp_path, max_closure_files=20)

    assert closure == []


def test_returns_just_the_modules_closure_when_test_path_unset(tmp_path):
    module = _write(tmp_path / "pkg" / "core.py", "def merge(*d):\n    return d\n")
    test_info = BehaviorTestInfo(test_filename="test_core.py", test_source="import unittest\n")

    closure = _closure_including_test_file(module, test_info, [module], tmp_path, max_closure_files=20)

    assert closure == []


def test_does_not_duplicate_a_file_both_closures_need(tmp_path):
    module = _write(tmp_path / "pkg" / "core.py", "import pkg.shared\n")
    shared = _write(tmp_path / "pkg" / "shared.py", "X = 1\n")
    test_file = _write(
        tmp_path / "pkg" / "tests" / "test_core.py",
        "import pkg.shared\nimport pkg.core\n",
    )
    all_units = [module, shared, test_file]
    test_info = BehaviorTestInfo(test_filename="test_core.py", test_source=test_file.original_source, test_path=test_file.path)

    closure = _closure_including_test_file(module, test_info, all_units, tmp_path, max_closure_files=20)

    rel_paths = [cf.rel_path for cf in closure]
    assert rel_paths.count(shared.path.relative_to(tmp_path)) == 1
