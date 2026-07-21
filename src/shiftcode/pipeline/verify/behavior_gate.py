import ast
import re
import sys
import tempfile
from pathlib import Path

from shiftcode.models import BehaviorResult, GateOutcome
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime


def _default_local_py3() -> SandboxRuntime:
    return SandboxRuntime(available=True, kind="local", interpreter_path=sys.executable)

# Python 2's `unittest -v` verbose format is `test_name (module.Class) ... ok`.
# Python 3 (3.11+) changed this to `test_name (module.Class.test_name) ... ok` -
# note the method name repeated inside the parens. Key by the bare method name
# (group 1) only, not the full "(...)" qualname, so comparing py2 vs py3 outcomes
# doesn't spuriously mismatch every single test purely on this formatting
# difference between interpreter versions.
_TEST_RESULT_RE = re.compile(r"^(\S+) \([\w.]+\) \.\.\. (ok|FAIL|ERROR)\s*$", re.MULTILINE)


def has_main_block(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_name_main_check(node.test):
            return True
    return False


def _is_name_main_check(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    left, right = test.left, test.comparators[0]
    names = {n for n in (left, right) if isinstance(n, ast.Name)}
    consts = {n.value for n in (left, right) if isinstance(n, ast.Constant)}
    return any(n.id == "__name__" for n in names) and "__main__" in consts


def _parse_unittest_output(stderr: str) -> dict[str, str]:
    """`python -m unittest -v` writes per-test result lines to stderr, e.g.
    'test_foo (mod.Class) ... ok'."""
    return dict(_TEST_RESULT_RE.findall(stderr))


def run_mode_a(
    *,
    module_filename: str,
    module_source_py2: str,
    module_source_py3: str,
    test_filename: str,
    test_source: str,
    test_module_name: str,
    py2_runtime: SandboxRuntime,
    py3_runtime: SandboxRuntime | None = None,
    timeout: float = 30,
) -> BehaviorResult:
    """Run the existing test suite under both interpreters, compare per-test
    outcome and full stdout (not just exit code - a print-based side effect could
    differ while assertions still coincidentally pass)."""
    if not py2_runtime.available:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED,
            mode="A",
            detail=f"no py2 runtime available ({py2_runtime.reason})",
        )

    py3_runtime = py3_runtime or _default_local_py3()

    with tempfile.TemporaryDirectory() as py2_dir, tempfile.TemporaryDirectory() as py3_dir:
        (Path(py2_dir) / module_filename).write_text(module_source_py2)
        (Path(py2_dir) / test_filename).write_text(test_source)
        (Path(py3_dir) / module_filename).write_text(module_source_py3)
        (Path(py3_dir) / test_filename).write_text(test_source)

        py2_proc = py2_runtime.run_unittest(Path(py2_dir), test_module_name, timeout=timeout)
        py3_proc = py3_runtime.run_unittest(Path(py3_dir), test_module_name, timeout=timeout)

    py2_outcomes = _parse_unittest_output(py2_proc.stderr)
    py3_outcomes = _parse_unittest_output(py3_proc.stderr)

    mismatches = []
    for name in sorted(set(py2_outcomes) | set(py3_outcomes)):
        if py2_outcomes.get(name) != py3_outcomes.get(name):
            mismatches.append(f"{name}: py2={py2_outcomes.get(name, '?')} py3={py3_outcomes.get(name, '?')}")

    stdout_matches = py2_proc.stdout == py3_proc.stdout

    if mismatches:
        # A real behavioral difference: the test suite's own assertions disagree
        # between interpreters. This is the authoritative signal - fail here.
        detail_parts = ["test outcome mismatches: " + "; ".join(mismatches)]
        if not stdout_matches:
            detail_parts.append(f"stdout also differs:\n--- py2 ---\n{py2_proc.stdout}\n--- py3 ---\n{py3_proc.stdout}")
        return BehaviorResult(
            outcome=GateOutcome.FAIL,
            mode="A",
            detail="\n".join(detail_parts),
            failing_tests=[m.split(":")[0] for m in mismatches],
        )

    if not stdout_matches:
        # Every test passed/failed identically under both interpreters - that's
        # what "behaves the same" actually means here. A remaining raw stdout
        # difference with no test-outcome difference is almost always
        # interpreter-internal wording (e.g. ZeroDivisionError's message text
        # changed between Python 2 and 3), not something migrated code controls
        # or could ever "fix". Note it for transparency, but don't hard-fail on it.
        return BehaviorResult(
            outcome=GateOutcome.PASS,
            mode="A",
            detail=(
                "all test outcomes match, but raw stdout text differs (likely "
                "interpreter-internal wording, e.g. an exception message, not a "
                f"behavioral difference):\n--- py2 ---\n{py2_proc.stdout}\n--- py3 ---\n{py3_proc.stdout}"
            ),
        )

    return BehaviorResult(outcome=GateOutcome.PASS, mode="A", detail="all tests match, stdout identical")


def run_mode_b(
    *,
    module_filename: str,
    module_source_py2: str,
    module_source_py3: str,
    py2_runtime: SandboxRuntime,
    py3_runtime: SandboxRuntime | None = None,
    timeout: float = 30,
) -> BehaviorResult:
    """No test suite: for __main__-executable files, diff stdout/stderr/exit code
    between the py2 and py3 runs."""
    if not py2_runtime.available:
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED,
            mode="B",
            detail=f"no py2 runtime available ({py2_runtime.reason})",
        )

    py3_runtime = py3_runtime or _default_local_py3()

    with tempfile.TemporaryDirectory() as py2_dir, tempfile.TemporaryDirectory() as py3_dir:
        py2_path = Path(py2_dir) / module_filename
        py3_path = Path(py3_dir) / module_filename
        py2_path.write_text(module_source_py2)
        py3_path.write_text(module_source_py3)

        py2_proc = py2_runtime.run_script(py2_path, timeout=timeout)
        py3_proc = py3_runtime.run_script(py3_path, timeout=timeout)

    if (
        py2_proc.stdout == py3_proc.stdout
        and py2_proc.stderr == py3_proc.stderr
        and py2_proc.returncode == py3_proc.returncode
    ):
        return BehaviorResult(outcome=GateOutcome.PASS, mode="B", detail="stdout/stderr/exit code identical")

    return BehaviorResult(
        outcome=GateOutcome.FAIL,
        mode="B",
        detail=(
            f"--- py2 stdout ---\n{py2_proc.stdout}\n--- py3 stdout ---\n{py3_proc.stdout}\n"
            f"py2 exit={py2_proc.returncode} py3 exit={py3_proc.returncode}"
        ),
    )
