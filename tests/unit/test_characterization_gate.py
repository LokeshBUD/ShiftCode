import subprocess
from dataclasses import dataclass, field

import pytest

from shiftcode.models import GateOutcome, TestCase
from shiftcode.pipeline.verify.characterization_gate import (
    UnsafeTestCaseError,
    _validate_args_literal,
    run_mode_c,
)


@pytest.mark.parametrize(
    "malicious",
    [
        '__import__("os").system("echo pwned")',
        'open("/etc/passwd").read()',
        "(a=5, b=0)",
        'os.system("rm -rf /")',
        "lambda: None",
        "some_name",
    ],
)
def test_validate_args_literal_rejects_non_literal_expressions(malicious):
    """The entire defense against a malicious/manipulated model response
    trying to smuggle code execution through this field. Must reject
    anything that isn't a pure literal tuple - no exceptions."""
    with pytest.raises(UnsafeTestCaseError):
        _validate_args_literal(malicious)


def test_validate_args_literal_accepts_literal_tuples():
    assert _validate_args_literal("(10, 4)") == (10, 4)
    assert _validate_args_literal("()") == ()
    assert _validate_args_literal("([1, 2], {'a': 1})") == ([1, 2], {"a": 1})


def test_validate_args_literal_rejects_non_tuple_literal():
    with pytest.raises(UnsafeTestCaseError):
        _validate_args_literal("5")  # a literal, but not a tuple


@dataclass
class _ScriptedRuntime:
    """Fake sandbox runtime: returns canned stdout per call_script invocation,
    in order. Used so these tests don't depend on Docker being installed."""

    outputs: list[str]
    available: bool = True
    reason: str | None = None
    calls: int = field(default=0)

    def run_script(self, script_path, *, timeout=30):
        stdout = self.outputs[self.calls]
        self.calls += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


CASES = [
    TestCase(function_name="divide", args_literal="(7, 2)", rationale="typical"),
]


def test_run_mode_c_passes_when_results_match():
    py2 = _ScriptedRuntime(outputs=["RESULT:3\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:3\n"])

    result = run_mode_c(
        module_filename="mathutils.py",
        module_source_py2="def divide(a, b):\n    return a // b\n",
        module_source_py3="def divide(a, b):\n    return a // b\n",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
    )

    assert result.outcome == GateOutcome.PASS
    assert result.mode == "C"
    assert result.evidence_source == "docstring"


def test_run_mode_c_fails_on_real_return_value_mismatch():
    py2 = _ScriptedRuntime(outputs=["RESULT:3\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:3.5\n"])

    result = run_mode_c(
        module_filename="mathutils.py",
        module_source_py2="def divide(a, b):\n    return a // b\n",
        module_source_py3="def divide(a, b):\n    return a / b\n",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="call_sites",
    )

    assert result.outcome == GateOutcome.FAIL
    assert "divide(7, 2)" in result.failing_tests[0]


def test_run_mode_c_matches_exceptions_by_type_not_message():
    """Same lesson as the Mode A fix this session: an exception's message
    wording can differ between py2/py3 for the same conceptual error. Type
    match is the meaningful signal, not message text."""
    py2 = _ScriptedRuntime(outputs=["EXCEPTION:ZeroDivisionError\n"])
    py3 = _ScriptedRuntime(outputs=["EXCEPTION:ZeroDivisionError\n"])

    result = run_mode_c(
        module_filename="mathutils.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="llm_inference",
    )

    assert result.outcome == GateOutcome.PASS


def test_run_mode_c_fails_when_one_side_raises_and_other_doesnt():
    py2 = _ScriptedRuntime(outputs=["EXCEPTION:ZeroDivisionError\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:0\n"])

    result = run_mode_c(
        module_filename="mathutils.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="llm_inference",
    )

    assert result.outcome == GateOutcome.FAIL


def test_run_mode_c_unverified_without_py2_runtime():
    py2 = _ScriptedRuntime(outputs=[], available=False, reason="no py2 here")
    py3 = _ScriptedRuntime(outputs=[])

    result = run_mode_c(
        module_filename="mathutils.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
    )

    assert result.outcome == GateOutcome.UNVERIFIED


def test_run_mode_c_unverified_without_py3_sandbox():
    py2 = _ScriptedRuntime(outputs=[])
    py3 = _ScriptedRuntime(outputs=[], available=False, reason="Docker unreachable")

    result = run_mode_c(
        module_filename="mathutils.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
    )

    assert result.outcome == GateOutcome.UNVERIFIED


def test_run_mode_c_unverified_when_all_cases_have_unsafe_args():
    unsafe_cases = [TestCase(function_name="f", args_literal='os.system("x")', rationale="malicious")]
    py2 = _ScriptedRuntime(outputs=[])
    py3 = _ScriptedRuntime(outputs=[])

    result = run_mode_c(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=unsafe_cases,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="llm_inference",
    )

    assert result.outcome == GateOutcome.UNVERIFIED
    assert py2.calls == 0  # never even attempted execution
    assert py3.calls == 0
