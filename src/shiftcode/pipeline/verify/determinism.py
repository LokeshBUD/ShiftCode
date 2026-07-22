import subprocess
import sys
import tempfile
from pathlib import Path

from shiftcode.models import DeterminismResult, GateOutcome
from shiftcode.pipeline.dependencies import ClosureFile
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime, write_sandbox_tree


def _normalize_run(proc: subprocess.CompletedProcess) -> str:
    return f"exit={proc.returncode}\n--stdout--\n{proc.stdout}\n--stderr--\n{proc.stderr}"


def capture_py3_script_runs(
    source: str,
    module_filename: str,
    *,
    py3_runtime: SandboxRuntime | None = None,
    n: int = 3,
    timeout: float = 30,
    dependency_closure: list[ClosureFile] | None = None,
    module_rel_path: Path | None = None,
) -> list[str]:
    """A __main__-executable file with sibling imports hits the same
    ModuleNotFoundError-on-both-sides problem run_mode_b does - this needs the
    identical closure treatment, called for the same file right alongside it
    in verify_candidate (docs/bug-log.md #13's design note)."""
    py3_runtime = py3_runtime or SandboxRuntime(available=True, kind="local", interpreter_path=sys.executable)
    closure = dependency_closure or []
    rel_path = module_rel_path or Path(module_filename)
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        write_sandbox_tree(Path(tmp), rel_path, source, closure, side="py3")
        for _ in range(n):
            proc = py3_runtime.run_script(Path(tmp), rel_path, timeout=timeout)
            runs.append(_normalize_run(proc))
    return runs


def capture_py2_script_runs(
    py2_runtime: SandboxRuntime,
    source: str,
    module_filename: str,
    *,
    n: int = 3,
    timeout: float = 30,
    dependency_closure: list[ClosureFile] | None = None,
    module_rel_path: Path | None = None,
) -> list[str] | None:
    if not py2_runtime.available:
        return None
    closure = dependency_closure or []
    rel_path = module_rel_path or Path(module_filename)
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        write_sandbox_tree(Path(tmp), rel_path, source, closure, side="py2")
        for _ in range(n):
            proc = py2_runtime.run_script(Path(tmp), rel_path, timeout=timeout)
            runs.append(_normalize_run(proc))
    return runs


def check_determinism(
    *,
    py3_outputs: list[str],
    py2_outputs: list[str] | None = None,
) -> DeterminismResult:
    """Pre-existing py2-side flakiness (e.g. unordered dict iteration in the
    legacy code) is reported but doesn't block migration - it's not something
    ShiftCode introduced. New variance only on the migrated py3 side is a hard
    fail: the migration must not make previously-stable behavior unstable."""
    py3_stable = len(set(py3_outputs)) <= 1

    if py2_outputs is not None and len(set(py2_outputs)) > 1:
        return DeterminismResult(
            outcome=GateOutcome.PRE_EXISTING_NONDETERMINISM,
            runs=py2_outputs,
            detail="py2 baseline itself varies run-to-run - pre-existing flakiness in the legacy code, not introduced by migration",
        )

    if not py3_stable:
        return DeterminismResult(
            outcome=GateOutcome.FAIL,
            runs=py3_outputs,
            detail=f"migrated (py3) output varies across {len(py3_outputs)} identical runs",
        )

    return DeterminismResult(
        outcome=GateOutcome.PASS,
        runs=py3_outputs,
        detail=f"stable across {len(py3_outputs)} runs",
    )
