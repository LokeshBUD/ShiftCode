import subprocess
from dataclasses import dataclass
from pathlib import Path

from shiftcode.config import LLMConfig, ShiftConfig
from shiftcode.models import GateOutcome
from shiftcode.pipeline.verify.behavior_gate import has_main_block, run_mode_a, run_mode_b
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

    def run_pytest(self, cwd, test_filename, *, timeout=30):
        return self.pytest_result, self.pytest_xml


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
