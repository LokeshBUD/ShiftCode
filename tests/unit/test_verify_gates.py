import subprocess
from dataclasses import dataclass

from shiftcode.config import LLMConfig, ShiftConfig
from shiftcode.models import GateOutcome
from shiftcode.pipeline.verify.behavior_gate import has_main_block, run_mode_a, run_mode_b
from shiftcode.pipeline.verify.determinism import check_determinism
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime, resolve_py2_runtime


def _proc(stdout: str, stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


@dataclass
class _FakeAvailableRuntime:
    unittest_result: subprocess.CompletedProcess
    available: bool = True

    def run_unittest(self, cwd, test_module, *, timeout=30):
        return self.unittest_result


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
        test_module_name="test_m",
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


PY2_STYLE_ALL_OK = "test_add (m.T) ... ok\ntest_div (m.T) ... ok\n"
PY3_STYLE_ALL_OK = "test_add (m.T.test_add) ... ok\ntest_div (m.T.test_div) ... ok\n"
PY3_STYLE_DIV_FAILS = "test_add (m.T.test_add) ... ok\ntest_div (m.T.test_div) ... FAIL\n"


def test_run_mode_a_passes_when_test_outcomes_match_even_if_stdout_text_differs():
    """Regression: a behaviorally-correct migration was failing this gate purely
    because ZeroDivisionError's message text differs between Python 2 and 3
    ("integer division or modulo by zero" vs "division by zero") - interpreter
    wording, not something any migration controls. Test outcomes matching is
    the authoritative signal; a stdout text difference alone must not fail."""
    py2_runtime = _FakeAvailableRuntime(
        unittest_result=_proc(stdout="error: integer division or modulo by zero\n", stderr=PY2_STYLE_ALL_OK)
    )
    py3_runtime = _FakeAvailableRuntime(
        unittest_result=_proc(stdout="error: division by zero\n", stderr=PY3_STYLE_ALL_OK)
    )

    result = run_mode_a(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="test_m.py",
        test_source="",
        test_module_name="test_m",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.PASS
    assert "interpreter-internal wording" in result.detail


def test_run_mode_a_fails_when_test_outcomes_genuinely_differ():
    py2_runtime = _FakeAvailableRuntime(unittest_result=_proc(stdout="", stderr=PY2_STYLE_ALL_OK))
    py3_runtime = _FakeAvailableRuntime(unittest_result=_proc(stdout="", stderr=PY3_STYLE_DIV_FAILS))

    result = run_mode_a(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_filename="test_m.py",
        test_source="",
        test_module_name="test_m",
        py2_runtime=py2_runtime,
        py3_runtime=py3_runtime,
    )

    assert result.outcome == GateOutcome.FAIL
    assert "test_div" in result.failing_tests[0]
