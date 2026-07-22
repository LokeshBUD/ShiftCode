import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shiftcode.models import GateOutcome, TestCase
from shiftcode.pipeline.dependencies import ClosureFile
from shiftcode.pipeline.verify.characterization_gate import (
    UnsafeTestCaseError,
    _module_dotted_name,
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
    # Snapshot of every file under cwd at call time (relative path -> content) -
    # taken immediately, not deferred, since cwd is a TemporaryDirectory that
    # gets deleted once the caller's `with` block exits.
    captured_tree: dict[str, str] | None = None

    def run_script(self, cwd, script_rel_path, *, timeout=30):
        self.captured_tree = {str(p.relative_to(cwd)): p.read_text() for p in cwd.rglob("*") if p.is_file()}
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


def test_run_mode_c_ignores_dict_key_ordering_differences():
    """Regression from a real stress test (purl's parse(), docs/bug-log.md):
    Python 2 dicts have no ordering guarantee, Python 3.7+ guarantees
    insertion order - the exact same key/value pairs can legitimately repr()
    in a different order on each side. Comparing raw repr strings flagged
    this as a false mismatch; comparing the actual parsed values doesn't."""
    py2 = _ScriptedRuntime(outputs=["RESULT:{'a': 1, 'b': 2}\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:{'b': 2, 'a': 1}\n"])

    result = run_mode_c(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
    )

    assert result.outcome == GateOutcome.PASS


def test_run_mode_c_still_catches_a_real_value_difference_hidden_in_a_dict():
    py2 = _ScriptedRuntime(outputs=["RESULT:{'a': 1, 'b': 2}\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:{'b': 2, 'a': 99}\n"])

    result = run_mode_c(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
    )

    assert result.outcome == GateOutcome.FAIL


def test_run_mode_c_falls_back_to_string_comparison_for_non_literal_reprs():
    """A repr that isn't ast.literal_eval-parseable (e.g. a custom object's
    repr, or a float with genuinely different precision text) must not crash
    the comparison - falls back to the previous plain string behavior."""
    py2 = _ScriptedRuntime(outputs=["RESULT:<Point x=1 y=2>\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:<Point x=1 y=2>\n"])

    result = run_mode_c(
        module_filename="m.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
    )

    assert result.outcome == GateOutcome.PASS


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


def test_module_dotted_name_for_package_init():
    assert _module_dotted_name(Path("mypkg/__init__.py")) == "mypkg"


def test_module_dotted_name_for_nested_module():
    assert _module_dotted_name(Path("mypkg/core.py")) == "mypkg.core"


def test_module_dotted_name_for_flat_module():
    assert _module_dotted_name(Path("m.py")) == "m"


def test_run_mode_c_writes_closure_once_and_reuses_across_cases():
    """Closure written once per side (not per-case) - confirmed by inspecting
    the shared cwd after multiple cases run, and that the closure file is
    still present (not recreated/lost between cases)."""
    cases = [
        TestCase(function_name="divide", args_literal="(7, 2)", rationale="typical"),
        TestCase(function_name="divide", args_literal="(1, 1)", rationale="edge"),
    ]
    py2 = _ScriptedRuntime(outputs=["RESULT:3\n", "RESULT:1\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:3\n", "RESULT:1\n"])
    closure = [ClosureFile(rel_path=Path("mypkg/helpers.py"), source_py2="py2 helper\n", source_py3="py3 helper\n")]

    result = run_mode_c(
        module_filename="__init__.py",
        module_source_py2="py2 init\n",
        module_source_py3="py3 init\n",
        test_plan_cases=cases,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
        dependency_closure=closure,
        module_rel_path=Path("mypkg/__init__.py"),
    )

    assert result.outcome == GateOutcome.PASS
    assert py2.captured_tree["mypkg/__init__.py"] == "py2 init\n"
    assert py2.captured_tree["mypkg/helpers.py"] == "py2 helper\n"
    assert py3.captured_tree["mypkg/helpers.py"] == "py3 helper\n"
    assert py2.calls == 2 and py3.calls == 2
