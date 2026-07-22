from pathlib import Path

from shiftcode.pipeline.dependencies import ClosureFile
from shiftcode.pipeline.verify.sandbox_runtime import write_sandbox_tree


def test_writes_module_at_its_real_relative_path(tmp_path):
    base = tmp_path / "sandbox"
    write_sandbox_tree(base, Path("mypkg/__init__.py"), "x = 1\n", [], side="py3")

    assert (base / "mypkg" / "__init__.py").read_text() == "x = 1\n"


def test_writes_closure_files_at_their_real_relative_paths_py2_side(tmp_path):
    base = tmp_path / "sandbox"
    closure = [ClosureFile(rel_path=Path("mypkg/helpers.py"), source_py2="py2 src\n", source_py3="py3 src\n")]

    write_sandbox_tree(base, Path("mypkg/__init__.py"), "init src\n", closure, side="py2")

    assert (base / "mypkg" / "helpers.py").read_text() == "py2 src\n"


def test_writes_closure_files_at_their_real_relative_paths_py3_side(tmp_path):
    base = tmp_path / "sandbox"
    closure = [ClosureFile(rel_path=Path("mypkg/helpers.py"), source_py2="py2 src\n", source_py3="py3 src\n")]

    write_sandbox_tree(base, Path("mypkg/__init__.py"), "init src\n", closure, side="py3")

    assert (base / "mypkg" / "helpers.py").read_text() == "py3 src\n"


def test_empty_closure_is_a_flat_single_file_write(tmp_path):
    base = tmp_path / "sandbox"
    write_sandbox_tree(base, Path("m.py"), "x = 1\n", [], side="py3")

    assert (base / "m.py").read_text() == "x = 1\n"
    assert list(base.iterdir()) == [base / "m.py"]
