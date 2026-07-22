from pathlib import Path

from shiftcode.models import FileUnit
from shiftcode.pipeline.dependencies import (
    build_import_graph,
    closure_files_for_sandbox,
    dependency_closure,
    resolve_local_imports,
    topological_order,
)


def _write(path: Path, source: str) -> FileUnit:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return FileUnit(path=path, original_source=source)


def test_resolves_flat_sibling_absolute_import(tmp_path):
    a = _write(tmp_path / "module_a.py", "import module_b\nmodule_b.helper()\n")
    b = _write(tmp_path / "module_b.py", "def helper():\n    pass\n")

    edges = resolve_local_imports(a, [a, b], tmp_path)

    assert len(edges) == 1
    assert edges[0].resolved == b.path
    assert edges[0].import_kind == "absolute"


def test_resolves_package_relative_bare_import(tmp_path):
    init = _write(tmp_path / "mypkg" / "__init__.py", "from . import helpers\nhelpers.normalize(1)\n")
    helpers = _write(tmp_path / "mypkg" / "helpers.py", "def normalize(x):\n    return x\n")

    edges = resolve_local_imports(init, [init, helpers], tmp_path)

    assert len(edges) == 1
    assert edges[0].resolved == helpers.path
    assert edges[0].import_kind == "relative"


def test_resolves_named_relative_import(tmp_path):
    init = _write(tmp_path / "mypkg" / "__init__.py", "from .helpers import normalize\nnormalize(1)\n")
    helpers = _write(tmp_path / "mypkg" / "helpers.py", "def normalize(x):\n    return x\n")

    edges = resolve_local_imports(init, [init, helpers], tmp_path)

    assert len(edges) == 1
    assert edges[0].resolved == helpers.path


def test_resolves_absolute_dotted_package_import(tmp_path):
    caller = _write(tmp_path / "caller.py", "from mypkg.core import thing\n")
    core = _write(tmp_path / "mypkg" / "core.py", "def thing():\n    pass\n")
    init = _write(tmp_path / "mypkg" / "__init__.py", "")

    edges = resolve_local_imports(caller, [caller, core, init], tmp_path)

    assert any(e.resolved == core.path for e in edges)


def test_non_local_import_produces_no_edge(tmp_path):
    a = _write(tmp_path / "module_a.py", "import os\nimport requests\n")

    edges = resolve_local_imports(a, [a], tmp_path)

    assert edges == []


def test_syntax_error_source_returns_no_edges_not_a_crash(tmp_path):
    a = _write(tmp_path / "module_a.py", "def f(:\n    pass\n")

    edges = resolve_local_imports(a, [a], tmp_path)

    assert edges == []


def test_dependency_closure_is_transitive(tmp_path):
    a = _write(tmp_path / "a.py", "import b\n")
    b = _write(tmp_path / "b.py", "import c\n")
    c = _write(tmp_path / "c.py", "x = 1\n")

    result = dependency_closure(a, [a, b, c], tmp_path)

    assert {fu.path for fu in result.files} == {b.path, c.path}
    assert not result.truncated


def test_dependency_closure_includes_own_package_init_even_with_no_import_edge_to_it(tmp_path):
    """Regression from a real end-to-end run (tests/fixtures/sample_multi_file_py2):
    Python 2 has no namespace-package support - `import mypkg.helpers` crashes
    there without a real mypkg/__init__.py in the sandbox, even when helpers.py
    itself has zero import edges (its own closure would otherwise be empty).
    Python 3 silently tolerates the missing __init__.py via implicit namespace
    packages, which is exactly why this only broke on the py2 side."""
    init = _write(tmp_path / "mypkg" / "__init__.py", "from .helpers import normalize\n")
    helpers = _write(tmp_path / "mypkg" / "helpers.py", "def normalize(x):\n    return x\n")

    result = dependency_closure(helpers, [init, helpers], tmp_path)

    assert {fu.path for fu in result.files} == {init.path}


def test_dependency_closure_never_synthesizes_a_missing_init(tmp_path):
    """A genuine namespace package (no __init__.py anywhere) must stay
    exactly that - never invent one that doesn't exist in the real project."""
    helpers = _write(tmp_path / "mypkg" / "helpers.py", "def normalize(x):\n    return x\n")

    result = dependency_closure(helpers, [helpers], tmp_path)

    assert result.files == []


def test_dependency_closure_handles_cycles_without_hanging(tmp_path):
    a = _write(tmp_path / "a.py", "import b\n")
    b = _write(tmp_path / "b.py", "import a\n")

    result = dependency_closure(a, [a, b], tmp_path)

    assert {fu.path for fu in result.files} == {b.path}
    assert not result.truncated


def test_dependency_closure_reports_truncation_honestly(tmp_path):
    a = _write(tmp_path / "a.py", "import b\nimport c\n")
    b = _write(tmp_path / "b.py", "x = 1\n")
    c = _write(tmp_path / "c.py", "x = 1\n")

    result = dependency_closure(a, [a, b, c], tmp_path, max_closure_files=1)

    assert result.truncated
    assert result.truncated_reason is not None
    assert len(result.files) == 1


def test_closure_files_for_sandbox_uses_source_fallback_chain(tmp_path):
    dep = _write(tmp_path / "dep.py", "x = 1\n")
    dep.deterministic_output = "x = 1  # transformed\n"
    a = _write(tmp_path / "a.py", "import dep\n")

    result = dependency_closure(a, [a, dep], tmp_path)
    closure_files = closure_files_for_sandbox(result, tmp_path)

    assert len(closure_files) == 1
    assert closure_files[0].rel_path == Path("dep.py")
    assert closure_files[0].source_py2 == "x = 1\n"
    assert closure_files[0].source_py3 == "x = 1  # transformed\n"  # deterministic_output preferred


def test_closure_files_for_sandbox_prefers_final_source_over_deterministic(tmp_path):
    dep = _write(tmp_path / "dep.py", "x = 1\n")
    dep.deterministic_output = "x = 1  # transformed\n"
    dep.final_source = "x = 1  # fully migrated\n"
    a = _write(tmp_path / "a.py", "import dep\n")

    result = dependency_closure(a, [a, dep], tmp_path)
    closure_files = closure_files_for_sandbox(result, tmp_path)

    assert closure_files[0].source_py3 == "x = 1  # fully migrated\n"


def test_topological_order_places_dependencies_first(tmp_path):
    a = _write(tmp_path / "a.py", "import b\n")
    b = _write(tmp_path / "b.py", "import c\n")
    c = _write(tmp_path / "c.py", "x = 1\n")
    units = [a, b, c]

    edges = build_import_graph(units, tmp_path)
    order = topological_order(units, edges)

    positions = {fu.path: i for i, fu in enumerate(order)}
    assert positions[c.path] < positions[b.path] < positions[a.path]


def test_topological_order_terminates_on_cycle(tmp_path):
    a = _write(tmp_path / "a.py", "import b\n")
    b = _write(tmp_path / "b.py", "import c\n")
    c = _write(tmp_path / "c.py", "import a\n")
    units = [a, b, c]

    edges = build_import_graph(units, tmp_path)
    order = topological_order(units, edges)

    assert {fu.path for fu in order} == {a.path, b.path, c.path}
    assert len(order) == 3


def test_topological_order_independent_files_keep_original_order(tmp_path):
    a = _write(tmp_path / "a.py", "x = 1\n")
    b = _write(tmp_path / "b.py", "x = 1\n")
    units = [a, b]

    edges = build_import_graph(units, tmp_path)
    order = topological_order(units, edges)

    assert order == [a, b]
