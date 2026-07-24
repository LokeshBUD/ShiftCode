import subprocess
from dataclasses import dataclass
from pathlib import Path

from shiftcode.config import LLMConfig, ShiftConfig
from shiftcode.models import GateOutcome
from shiftcode.pipeline.verify.behavior_gate import (
    _strip_interpreter_warning_noise,
    has_main_block,
    run_mode_a,
    run_mode_b,
)
from shiftcode.pipeline.verify.determinism import check_determinism
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime, resolve_py2_runtime


def test_sandbox_runtime_mounts_deps_volume_and_sets_pythonpath_when_present():
    rt = SandboxRuntime(
        available=True, kind="docker", docker_image="shiftcode-py3-sandbox", deps_volume="shiftcode-deps-abc123"
    )
    cmd = rt._base_cmd(Path("/tmp/x"))
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"  # untouched by deps mounting
    assert "shiftcode-deps-abc123:/deps:ro" in cmd
    assert "PYTHONPATH=/deps" in cmd


def test_sandbox_runtime_no_deps_mount_when_absent():
    rt = SandboxRuntime(available=True, kind="docker", docker_image="shiftcode-py3-sandbox")
    cmd = rt._base_cmd(Path("/tmp/x"))
    assert not any("deps" in part for part in cmd)


def _proc(stdout: str, stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _junit_xml(outcomes: dict[str, str]) -> str:
    cases = []
    for name, outcome in outcomes.items():
        if outcome == "FAIL":
            cases.append(f'<testcase classname="m" name="{name}"><failure message="fail">x</failure></testcase>')
        elif outcome == "ERROR":
            cases.append(f'<testcase classname="m" name="{name}"><error message="error">x</error></testcase>')
        else:
            cases.append(f'<testcase classname="m" name="{name}" />')
    return f'<testsuites><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>'


@dataclass
class _FakeAvailableRuntime:
    pytest_result: subprocess.CompletedProcess
    pytest_xml: str = ""
    available: bool = True
    captured_test_source: str | None = None  # set by run_pytest, so a test can inspect what got written
    # Snapshot of every file under cwd at call time (relative path -> content) -
    # taken immediately, not deferred, since cwd is a TemporaryDirectory that
    # gets deleted once the caller's `with` block exits.
    captured_tree: dict[str, str] | None = None

    def _snapshot(self, cwd) -> dict[str, str]:
        return {str(p.relative_to(cwd)): p.read_text() for p in cwd.rglob("*") if p.is_file()}

    def run_pytest(self, cwd, test_filename, *, timeout=30):
        self.captured_tree = self._snapshot(cwd)
        self.captured_test_source = (cwd / test_filename).read_text()
        return self.pytest_result, self.pytest_xml

    def run_script(self, cwd, script_rel_path, *, timeout=30):
        self.captured_tree = self._snapshot(cwd)
        return self.pytest_result


def _config(**overrides) -> ShiftConfig:
    return ShiftConfig(llm=LLMConfig(), agent_overrides={}, **overrides)


def test_resolve_py2_runtime_uses_explicit_config_path(tmp_path):
    fake_interpreter = tmp_path / "python2"
    fake_interpreter.write_text("#!/bin/sh\n")
    cfg = _config(py2_interpreter=str(fake_interpreter))

    rt = resolve_py2_runtime(cfg)

    assert rt.available
    assert rt.kind == "local"
    assert rt.interpreter_path == str(fake_interpreter)


def test_resolve_py2_runtime_reports_unavailable_for_bad_config_path():
    cfg = _config(py2_interpreter="/definitely/does/not/exist/python2")

    rt = resolve_py2_runtime(cfg)

    assert not rt.available
    assert "does not exist" in rt.reason


def test_resolve_py2_runtime_finds_nothing_on_path_or_docker(monkeypatch):
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "shiftcode.pipeline.verify.sandbox_runtime._docker_daemon_reachable", lambda: False
    )
    cfg = _config()

    rt = resolve_py2_runtime(cfg)

    assert not rt.available
    assert rt.kind == "unavailable"


def test_behavior_gate_mode_a_degrades_to_unverified_without_py2_runtime():
    unavailable = SandboxRuntime(available=False, kind="unavailable", reason="no py2 here")

    result = run_mode_a(
        module_filename="m.py",
        module_source_py2="x = 1\n",
        module_source_py3="x = 1\n",
        test_filename="test_m.py",
        test_source="",
        py2_runtime=unavailable,
    )

    assert result.outcome == GateOutcome.UNVERIFIED
    assert result.mode == "A"


def test_behavior_gate_mode_b_degrades_to_unverified_without_py2_runtime():
    unavailable = SandboxRuntime(available=False, kind="unavailable", reason="no py2 here")

    result = run_mode_b(
        module_filename="m.py",
        module_source_py2="print(1)\n",
        module_source_py3="print(1)\n",
        py2_runtime=unavailable,
    )

    assert result.outcome == GateOutcome.UNVERIFIED
    assert result.mode == "B"


def test_has_main_block():
    assert has_main_block("if __name__ == '__main__':\n    pass\n")
    assert not has_main_block("x = 1\n")


def test_check_determinism_stable():
    result = check_determinism(py3_outputs=["a", "a", "a"])
    assert result.outcome == GateOutcome.PASS


def test_check_determinism_flags_introduced_nondeterminism():
    result = check_determinism(py3_outputs=["a", "b", "a"])
    assert result.outcome == GateOutcome.FAIL


def test_check_determinism_flags_pre_existing_py2_flakiness_without_blocking():
    result = check_determinism(py3_outputs=["a", "a"], py2_outputs=["x", "y"])
    assert result.outcome == GateOutcome.PRE_EXISTING_NONDETERMINISM


ALL_OK = _junit_xml({"test_add": "ok", "test_div": "ok"})
DIV_FAILS = _junit_xml({"test_add": "ok", "test_div": "FAIL"})


def test_run_mode_a_passes_when_test_outcomes_match_even_if_stdout_text_differs():
    """Regression: a behaviorally-correct migration was failing this gate purely
    because ZeroDivisionError's message text differs between Python 2 and 3
    ("integer division or modulo by zero" vs "division by zero") - interpreter
    wording, not something any migration controls. Test outcomes matching is
    the authoritative signal; a stdout text difference alone must not fail."""
    py2_runtime = _FakeAvailableRuntime(
        pytest_result=_proc(stdout="error: integer division or modulo by zero\n", stderr=""), pytest_xml=ALL_OK
    )
    py3_runtime = _FakeAvailableRuntime(
        pytest_result=_proc(stdout="error: division by zero\n", stderr=""), pytest_xml=ALL_OK
    )

    result = run_mode_a(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="test_m.py",
        test_source="",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.PASS
    assert "interpreter-internal wording" in result.detail
    assert result.cases_run == 2
    assert result.cases_passed == 2


def test_run_mode_a_fails_when_test_outcomes_genuinely_differ():
    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml=ALL_OK)
    py3_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml=DIV_FAILS)

    result = run_mode_a(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="test_m.py",
        test_source="",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.FAIL
    assert "test_div" in result.failing_tests[0]
    assert result.cases_run == 2
    assert result.cases_passed == 1  # test_add ok, test_div mismatched


def test_run_mode_a_does_not_vacuously_pass_when_zero_tests_discovered():
    """Regression from a real stress test: test_docopt.py uses bare pytest-style
    `assert` functions - an earlier `unittest`-based runner found zero tests on
    both sides. Empty stdout trivially matched empty stdout and the (empty)
    outcome-mismatch set was empty, so this used to report PASS ("all tests
    match") despite nothing having actually run - and a real, crash-inducing
    bug (lib2to3's fix_long corrupting a shadowed identifier) reached VERIFIED
    status undetected as a direct result."""
    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml="")
    py3_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml="")

    result = run_mode_a(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="test_m.py",
        test_source="",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.UNVERIFIED
    assert "0 tests" in result.detail
    assert result.cases_run is None
    assert result.cases_passed is None


_COLLECTION_ERROR_XML = (
    '<testsuites><testsuite name="pytest">'
    '<testcase classname="" name="tests"><error message="collection failure">ImportError</error></testcase>'
    "</testsuite></testsuites>"
)


def test_run_mode_a_does_not_vacuously_pass_when_both_sides_fail_collection_identically():
    """Regression from a real stress test (purl/__init__.py, docs/bug-log.md
    #12): `from purl import URL` fails on both interpreters with the same
    ImportError, since the sandbox's flat layout doesn't expose the module
    under its real package name. Both sides produce one matching synthetic
    'ERROR' testcase - a vacuous match, not a real behavior comparison. Same
    principle as the zero-tests guard above, different mechanism."""
    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml=_COLLECTION_ERROR_XML)
    py3_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml=_COLLECTION_ERROR_XML)

    result = run_mode_a(
        module_filename="__init__.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="tests.py",
        test_source="",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.UNVERIFIED
    assert "collection failed identically" in result.detail
    assert result.cases_run is None
    assert result.cases_passed is None


def test_run_mode_a_still_fails_when_one_side_errors_and_other_has_real_outcomes():
    """A mix of a real per-test outcome plus a collection-shaped ERROR entry
    must NOT be swallowed by the identical-collection-failure guard - only
    triggers when literally everything on both sides is ERROR."""
    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml=ALL_OK)
    py3_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml=_COLLECTION_ERROR_XML)

    result = run_mode_a(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="test_m.py",
        test_source="",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.FAIL


def test_run_mode_a_deterministically_transforms_test_source_for_py3_side_only():
    """Regression from a real stress test (jsonschema's tests.py, docs/bug-log.md
    #9): the test file is real py2 source too, but was being copied verbatim
    (unmigrated) to BOTH sandboxes. `__metaclass__ = X` is valid Python 3
    syntax but silently does nothing there (no error) instead of invoking the
    metaclass - it needs `class Foo(Base, metaclass=X):`. Every single test
    looked like a py2-vs-py3 mismatch as a result, since Python 3 collected a
    completely different, disjoint set of dynamically-generated test names."""
    py2_source_with_iteritems = "for k, v in d.iteritems():\n    pass\n"
    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml="")
    py3_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml="")

    run_mode_a(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="test_m.py",
        test_source=py2_source_with_iteritems,
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    # py2 side: untouched original (that's the ground truth being compared against)
    assert py2_runtime.captured_test_source == py2_source_with_iteritems
    # py3 side: mechanically transformed - the exact construct that broke silently
    assert "iteritems" not in py3_runtime.captured_test_source
    assert ".items()" in py3_runtime.captured_test_source


def test_run_mode_a_writes_module_and_closure_at_real_nested_paths():
    """A package's __init__.py (module_rel_path="mypkg/__init__.py") plus a
    sibling dependency (docs/bug-log.md #12/#13) must land at their real
    relative locations in the sandbox, not flattened - this is what makes
    `from . import helpers`-style imports resolve at all."""
    from shiftcode.pipeline.dependencies import ClosureFile

    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml="")
    py3_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="", stderr=""), pytest_xml="")
    closure = [ClosureFile(rel_path=Path("mypkg/helpers.py"), source_py2="py2 helper\n", source_py3="py3 helper\n")]

    run_mode_a(
        module_filename="__init__.py",
        module_source_py2="py2 init\n",
        module_source_py3="py3 init\n",
        test_filename="test_mypkg.py",
        test_source="",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
        dependency_closure=closure,
        module_rel_path=Path("mypkg/__init__.py"),
    )

    assert py2_runtime.captured_tree["mypkg/__init__.py"] == "py2 init\n"
    assert py2_runtime.captured_tree["mypkg/helpers.py"] == "py2 helper\n"
    assert py3_runtime.captured_tree["mypkg/__init__.py"] == "py3 init\n"
    assert py3_runtime.captured_tree["mypkg/helpers.py"] == "py3 helper\n"


def test_run_mode_b_writes_module_and_closure_at_real_nested_paths():
    from shiftcode.pipeline.dependencies import ClosureFile

    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="out", stderr=""))
    py3_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="out", stderr=""))
    closure = [ClosureFile(rel_path=Path("mypkg/helpers.py"), source_py2="py2 helper\n", source_py3="py3 helper\n")]

    run_mode_b(
        module_filename="cli.py",
        module_source_py2="py2 cli\n",
        module_source_py3="py3 cli\n",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
        dependency_closure=closure,
        module_rel_path=Path("mypkg/cli.py"),
    )

    assert py2_runtime.captured_tree["mypkg/cli.py"] == "py2 cli\n"
    assert py2_runtime.captured_tree["mypkg/helpers.py"] == "py2 helper\n"
    assert py3_runtime.captured_tree["mypkg/cli.py"] == "py3 cli\n"
    assert py3_runtime.captured_tree["mypkg/helpers.py"] == "py3 helper\n"


def test_strip_interpreter_warning_noise_removes_a_real_syntax_warning_block():
    """Real, confirmed case (a real stress test against aaronsw/html2text):
    Python 3 emits a SyntaxWarning at import time for an invalid escape
    sequence that Python 2 never emits, even though actual behavior is
    identical - pure interpreter noise."""
    stderr = (
        "/work/html2text.py:341: SyntaxWarning: \"\\s\" is an invalid escape sequence. "
        "Such sequences will not work in the future. Did you mean \"\\\\s\"? A raw string is also an option.\n"
        "  data = re.sub('\\s+', ' ', data)\n"
    )
    assert _strip_interpreter_warning_noise(stderr) == ""


def test_strip_interpreter_warning_noise_leaves_real_program_output_alone():
    stderr = "Traceback (most recent call last):\nValueError: something genuinely broke\n"
    assert _strip_interpreter_warning_noise(stderr) == stderr


def test_run_mode_b_passes_when_only_stderr_differs_by_a_py3_warning():
    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="hello\n", stderr=""))
    py3_runtime = _FakeAvailableRuntime(
        pytest_result=_proc(
            stdout="hello\n",
            stderr="/work/m.py:1: SyntaxWarning: invalid escape sequence\n  x = '\\s'\n",
        )
    )

    result = run_mode_b(
        module_filename="m.py",
        module_source_py2="print('hello')\n",
        module_source_py3="print('hello')\n",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.PASS


def test_run_mode_b_still_fails_on_a_real_stderr_difference():
    py2_runtime = _FakeAvailableRuntime(pytest_result=_proc(stdout="hello\n", stderr=""))
    py3_runtime = _FakeAvailableRuntime(
        pytest_result=_proc(stdout="hello\n", stderr="Traceback (most recent call last):\nValueError: real bug\n")
    )

    result = run_mode_b(
        module_filename="m.py",
        module_source_py2="print('hello')\n",
        module_source_py3="print('hello')\n",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.FAIL
