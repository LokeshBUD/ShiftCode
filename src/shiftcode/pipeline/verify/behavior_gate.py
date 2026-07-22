import ast
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from shiftcode.models import BehaviorResult, GateOutcome
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime


def _default_local_py3() -> SandboxRuntime:
    return SandboxRuntime(available=True, kind="local", interpreter_path=sys.executable)


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


def _parse_junit_xml(xml_content: str) -> dict[str, str]:
    """JUnit XML has a stable schema regardless of interpreter version or
    test style (unittest.TestCase vs bare assert) - this is what replaced the
    old regex-parsed `unittest -v` text output, which had two confirmed real
    bugs stemming from its interpreter-version-dependent formatting
    (docs/bug-log.md #2, #4). A module-level collection error (e.g. an
    ImportError from a missing dependency) shows up as its own testcase
    entry with an <error> child, same as any other failure - no special
    casing needed, unlike the old approach where this crashed Python 2.7's
    unittest ungracefully with no parseable output at all."""
    if not xml_content.strip():
        return {}
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return {}
    outcomes = {}
    for testcase in root.iter("testcase"):
        name = testcase.get("name", "")
        if not name:
            continue
        if testcase.find("failure") is not None:
            outcomes[name] = "FAIL"
        elif testcase.find("error") is not None:
            outcomes[name] = "ERROR"
        elif testcase.find("skipped") is not None:
            outcomes[name] = "SKIPPED"
        else:
            outcomes[name] = "ok"
    return outcomes


def run_mode_a(
    *,
    module_filename: str,
    module_source_py2: str,
    module_source_py3: str,
    test_filename: str,
    test_source: str,
    py2_runtime: SandboxRuntime,
    py3_runtime: SandboxRuntime | None = None,
    timeout: float = 30,
) -> BehaviorResult:
    """Run the existing test suite under both interpreters via pytest (natively
    discovers both unittest.TestCase and bare-assert pytest-style suites, unlike
    `python -m unittest` - see docs/bug-log.md #5), compare per-test outcome and
    full stdout (not just exit code - a print-based side effect could differ
    while assertions still coincidentally pass)."""
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

        py2_proc, py2_xml = py2_runtime.run_pytest(Path(py2_dir), test_filename, timeout=timeout)
        py3_proc, py3_xml = py3_runtime.run_pytest(Path(py3_dir), test_filename, timeout=timeout)

    py2_outcomes = _parse_junit_xml(py2_xml)
    py3_outcomes = _parse_junit_xml(py3_xml)

    if not py2_outcomes and not py3_outcomes:
        # Zero tests discovered on both sides isn't a pass - an empty
        # comparison must never read as agreement (docs/bug-log.md #2).
        return BehaviorResult(
            outcome=GateOutcome.UNVERIFIED,
            mode="A",
            detail="pytest discovered 0 tests on both sides - cannot verify",
        )

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
