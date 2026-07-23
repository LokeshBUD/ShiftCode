"""Real regression, found by re-running the whole real-library corpus after
this session's other changes: `schedule` and `python-slugify` both migrate
by pointing at the package directory itself. When that happens, every path
computed relative to effective_root collapses `__init__.py`'s own
module_rel_path to a bare `Path("__init__.py")`, so the sandbox writes it
unwrapped - a real test's `import schedule` / `from slugify import slugify`
fails identically on both interpreters. `_sandbox_root_prefix` fixes this by
wrapping in a directory matching the real importable name - inferred from
the paired test file's own imports (the migration root's directory name
alone is unreliable: `python-slugify` ships a module actually called
`slugify`)."""

from pathlib import Path

from shiftcode.models import FileUnit
from shiftcode.pipeline.orchestrator import _infer_package_import_name, _sandbox_root_prefix
from shiftcode.pipeline.repair import BehaviorTestInfo


def test_infer_package_import_name_finds_the_real_import_despite_directory_name_mismatch():
    test_source = "import unittest\nfrom slugify import slugify\n"
    assert _infer_package_import_name(test_source, root_name_hint="python-slugify") == "slugify"


def test_infer_package_import_name_skips_test_tooling_imported_before_the_real_package():
    test_source = "import unittest\nimport mock\nimport datetime\nimport schedule\n"
    assert _infer_package_import_name(test_source, root_name_hint="schedule") == "schedule"


def test_infer_package_import_name_returns_none_when_nothing_non_stdlib_found():
    assert _infer_package_import_name("import unittest\nimport os\n", root_name_hint="x") is None


def test_infer_package_import_name_returns_none_on_unparseable_source():
    assert _infer_package_import_name("def f(:\n", root_name_hint="x") is None


def test_sandbox_root_prefix_none_when_root_is_not_a_package(tmp_path):
    # No __init__.py directly in root - e.g. a project root containing a
    # nested package/ + tests/ (purl's real, un-flattened shape).
    file_units = [FileUnit(path=tmp_path / "pkg" / "__init__.py", original_source="x")]
    assert _sandbox_root_prefix(tmp_path, file_units, {}) is None


def test_sandbox_root_prefix_falls_back_to_directory_name_without_a_test_pairing(tmp_path):
    (tmp_path / "__init__.py").write_text("x")
    file_units = [FileUnit(path=tmp_path / "__init__.py", original_source="x")]
    assert _sandbox_root_prefix(tmp_path, file_units, {}) == Path(tmp_path.name)


def test_sandbox_root_prefix_prefers_the_test_files_real_import_name(tmp_path):
    (tmp_path / "__init__.py").write_text("x")
    init_path = tmp_path / "__init__.py"
    file_units = [FileUnit(path=init_path, original_source="x")]
    test_pairs = {
        init_path: BehaviorTestInfo(
            test_filename="test.py", test_source="import unittest\nfrom slugify import slugify\n"
        )
    }
    # tmp_path's own directory name is random (pytest tmp dir), never "slugify" -
    # so this only passes if the real import evidence is what's used, not the
    # directory name.
    assert _sandbox_root_prefix(tmp_path, file_units, test_pairs) == Path("slugify")
