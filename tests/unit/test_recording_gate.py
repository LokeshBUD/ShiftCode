import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from shiftcode.models import GateOutcome
from shiftcode.pipeline.verify.recording_gate import run_mode_r
from shiftcode.pipeline.verify.recording_loader import RecordedCase


@dataclass
class _ScriptedRuntime:
    """Fake sandbox runtime, same shape as characterization_gate.py's own
    tests use - canned stdout per call_script invocation, in order."""

    outputs: list[str]
    available: bool = True
    reason: str | None = None
    calls: int = field(default=0)

    def run_script(self, cwd, script_rel_path, *, timeout=30):
        stdout = self.outputs[self.calls % len(self.outputs)]
        self.calls += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_run_mode_r_passes_when_candidate_matches_the_recording():
    py3 = _ScriptedRuntime(outputs=["RESULT:5\n"])
    cases = [RecordedCase(function_name="add", args_literal="(2, 3)", expected_result_literal="5")]

    result = run_mode_r(
        module_filename="m.py",
        module_source_py3="def add(a, b):\n    return a + b\n",
        recorded_cases=cases,
        py3_runtime=py3,
    )

    assert result.outcome == GateOutcome.PASS
    assert result.mode == "R"
    assert result.cases_run == 1
    assert result.cases_passed == 1
    assert result.evidence_source == "recorded"


def test_run_mode_r_fails_on_a_real_mismatch():
    py3 = _ScriptedRuntime(outputs=["RESULT:6\n"])  # candidate returns 6, recording says 5
    cases = [RecordedCase(function_name="add", args_literal="(2, 3)", expected_result_literal="5")]

    result = run_mode_r(
        module_filename="m.py",
        module_source_py3="def add(a, b):\n    return a + b + 1\n",
        recorded_cases=cases,
        py3_runtime=py3,
    )

    assert result.outcome == GateOutcome.FAIL
    assert "add(2, 3)" in result.failing_tests[0]
    assert result.cases_run == 1
    assert result.cases_passed == 0


def test_run_mode_r_matches_a_recorded_exception():
    py3 = _ScriptedRuntime(outputs=["EXCEPTION:ZeroDivisionError\n"])
    cases = [RecordedCase(function_name="divide", args_literal="(1, 0)", expected_exception="ZeroDivisionError")]

    result = run_mode_r(
        module_filename="m.py",
        module_source_py3="x",
        recorded_cases=cases,
        py3_runtime=py3,
    )

    assert result.outcome == GateOutcome.PASS


def test_run_mode_r_needs_no_py2_runtime_argument_at_all():
    """The whole point of this mode: verification without a live py2
    interpreter, since the ground truth was already captured for real."""
    import inspect

    params = inspect.signature(run_mode_r).parameters
    assert "py2_runtime" not in params


def test_run_mode_r_unverified_without_py3_runtime():
    py3 = _ScriptedRuntime(outputs=[], available=False, reason="Docker unreachable")
    cases = [RecordedCase(function_name="add", args_literal="(2, 3)", expected_result_literal="5")]

    result = run_mode_r(
        module_filename="m.py",
        module_source_py3="x",
        recorded_cases=cases,
        py3_runtime=py3,
    )

    assert result.outcome == GateOutcome.UNVERIFIED


def test_run_mode_r_unverified_when_no_recorded_cases():
    py3 = _ScriptedRuntime(outputs=[])

    result = run_mode_r(
        module_filename="m.py",
        module_source_py3="x",
        recorded_cases=[],
        py3_runtime=py3,
    )

    assert result.outcome == GateOutcome.UNVERIFIED
    assert py3.calls == 0
