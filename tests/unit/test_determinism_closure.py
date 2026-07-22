import subprocess
from dataclasses import dataclass
from pathlib import Path

from shiftcode.pipeline.dependencies import ClosureFile
from shiftcode.pipeline.verify.determinism import capture_py2_script_runs, capture_py3_script_runs


@dataclass
class _FakeRuntime:
    available: bool = True
    # Snapshot of every file under cwd at call time (relative path -> content) -
    # taken immediately, not deferred, since cwd is a TemporaryDirectory that
    # gets deleted once the caller's `with` block exits.
    captured_tree: dict[str, str] | None = None

    def run_script(self, cwd, script_rel_path, *, timeout=30):
        self.captured_tree = {str(p.relative_to(cwd)): p.read_text() for p in cwd.rglob("*") if p.is_file()}
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")


def test_capture_py3_script_runs_writes_module_and_closure_at_nested_paths():
    """A __main__-executable file with sibling imports hits the same
    ModuleNotFoundError-on-both-sides problem run_mode_b does - must get the
    same closure treatment (docs/bug-log.md #13's design note)."""
    runtime = _FakeRuntime()
    closure = [ClosureFile(rel_path=Path("mypkg/helpers.py"), source_py2="py2 helper\n", source_py3="py3 helper\n")]

    capture_py3_script_runs(
        "py3 cli\n",
        "cli.py",
        py3_runtime=runtime,
        n=1,
        dependency_closure=closure,
        module_rel_path=Path("mypkg/cli.py"),
    )

    assert runtime.captured_tree["mypkg/cli.py"] == "py3 cli\n"
    assert runtime.captured_tree["mypkg/helpers.py"] == "py3 helper\n"


def test_capture_py2_script_runs_writes_py2_side_of_closure():
    runtime = _FakeRuntime()
    closure = [ClosureFile(rel_path=Path("mypkg/helpers.py"), source_py2="py2 helper\n", source_py3="py3 helper\n")]

    capture_py2_script_runs(
        runtime,
        "py2 cli\n",
        "cli.py",
        n=1,
        dependency_closure=closure,
        module_rel_path=Path("mypkg/cli.py"),
    )

    assert runtime.captured_tree["mypkg/cli.py"] == "py2 cli\n"
    assert runtime.captured_tree["mypkg/helpers.py"] == "py2 helper\n"


def test_capture_py3_script_runs_empty_closure_is_flat_write():
    runtime = _FakeRuntime()

    capture_py3_script_runs("x = 1\n", "m.py", py3_runtime=runtime, n=1)

    assert runtime.captured_tree["m.py"] == "x = 1\n"
