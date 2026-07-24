import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shiftcode.models import GateOutcome, TestCase
from shiftcode.pipeline.dependencies import ClosureFile
from shiftcode.pipeline.verify.characterization_gate import (
    MAX_REPORTED_MISMATCHES,
    _module_dotted_name,
    _values_equal,
    run_mode_c,
)

# UnsafeTestCaseError / validate_args_literal moved to fuzz_generation.py
# (shared by both the single-example and fuzz characterization paths now -
# see test_fuzz_generation.py for their tests).


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
    stderr_outputs: list[str] | None = None

    def run_script(self, cwd, script_rel_path, *, timeout=30):
        self.captured_tree = {str(p.relative_to(cwd)): p.read_text() for p in cwd.rglob("*") if p.is_file()}
        # Cycle rather than raise once outputs are exhausted - run_mode_c may
        # call this more times than a test anticipated (neighbor-variant
        # probing after the first mismatch), and tests not specifically
        # asserting on `calls` shouldn't need to hand-count exactly that many
        # scripted responses.
        stdout = self.outputs[self.calls % len(self.outputs)]
        stderr = self.stderr_outputs[self.calls % len(self.stderr_outputs)] if self.stderr_outputs else ""
        self.calls += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


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
    assert result.cases_run == 1
    assert result.cases_passed == 1


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
    # 1 original case + 3 neighbor-variant probes triggered by the first
    # mismatch (all also mismatch here, since the scripted outputs are fixed
    # regardless of args) - cases_run must reflect the TRUE total executed,
    # not just the originally-proposed case count.
    assert result.cases_run == 4
    assert result.cases_passed == 0


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


def test_run_mode_c_surfaces_stderr_when_one_side_crashes_before_printing_anything():
    """Real, confirmed case (argcomplete/completers.py): empty stdout with no
    RESULT:/EXCEPTION: prefix at all previously looked exactly like a real
    behavioral difference, when the actual cause was a transitive import
    crash elsewhere in the closure (a sibling __init__.py's own unrelated
    bug) - the real cause was only visible on stderr, which run_mode_c never
    surfaced at all until now."""
    py2 = _ScriptedRuntime(outputs=["RESULT:<generator object <genexpr> at 0x1>\n"])
    py3 = _ScriptedRuntime(
        outputs=[""],
        stderr_outputs=["ModuleNotFoundError: No module named 'pipes'\n"],
    )

    result = run_mode_c(
        module_filename="completers.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=CASES,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="llm_inference",
    )

    assert result.outcome == GateOutcome.FAIL
    assert "py3 stderr=" in result.detail
    assert "ModuleNotFoundError: No module named" in result.detail


def test_values_equal_ignores_memory_addresses_in_default_object_reprs():
    """Real, confirmed case (a class-method characterization run against
    blinker's actual code): two SEPARATE interpreter processes will never
    share a memory address, py2 vs py3 or not - comparing default object
    reprs verbatim was a pure false-mismatch source, unrelated to any real
    behavior difference."""
    py2_val = "<blinker.base.NamedSignal object at 0xffff93dc60d0; 'abc'>"
    py3_val = "<blinker.base.NamedSignal object at 0xffffb10186e0; 'abc'>"
    assert _values_equal(py2_val, py3_val) is True


def test_values_equal_still_catches_a_real_difference_hidden_past_the_address():
    py2_val = "<blinker.base.NamedSignal object at 0xffff93dc60d0; 'abc'>"
    py3_val = "<blinker.base.NamedSignal object at 0xffffb10186e0; 'xyz'>"
    assert _values_equal(py2_val, py3_val) is False


def test_values_equal_ignores_generator_repr_qualified_name_difference():
    """Real, confirmed case: Python 3 added the generator's qualified name to
    its own repr (`Signal.receivers_for`); Python 2's repr never had it
    (`receivers_for`) - a real repr-FORMAT change between versions, not a
    behavior difference."""
    py2_val = "<generator object receivers_for at 0xffffa38a44b0>"
    py3_val = "<generator object Signal.receivers_for at 0xffff8065a790>"
    assert _values_equal(py2_val, py3_val) is True


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
    assert result.cases_run is None
    assert result.cases_passed is None


def test_module_dotted_name_for_package_init():
    assert _module_dotted_name(Path("mypkg/__init__.py")) == "mypkg"


def test_module_dotted_name_for_nested_module():
    assert _module_dotted_name(Path("mypkg/core.py")) == "mypkg.core"


def test_module_dotted_name_for_flat_module():
    assert _module_dotted_name(Path("m.py")) == "m"


def test_run_mode_c_caps_reported_mismatches_but_keeps_full_failing_tests_list():
    """With characterization_fuzz_cases-scale case counts, a run with many
    mismatches must not produce an unreadable detail string - but
    failing_tests (structured, for programmatic consumption) must stay fully
    uncapped. Every case here mismatches (py2 always returns 1, py3 always
    returns 2), and the first mismatch triggers 3 neighbor-variant probes
    (also mismatching, since the scripted outputs cycle) - so failing_tests
    ends up longer than the case list itself."""
    cases = [TestCase(function_name="divide", args_literal=f"({i}, 1)", rationale="case") for i in range(15)]
    py2 = _ScriptedRuntime(outputs=["RESULT:1\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:2\n"])

    result = run_mode_c(
        module_filename="mathutils.py",
        module_source_py2="x",
        module_source_py3="x",
        test_plan_cases=cases,
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="docstring",
    )

    assert result.outcome == GateOutcome.FAIL
    assert len(result.failing_tests) == 18  # 15 cases + 3 neighbor variants of the first failure
    assert result.detail.count(";") + 1 == MAX_REPORTED_MISMATCHES
    assert "...and 8 more mismatch(es)" in result.detail
    # cases_run reflects the TRUE total executed (uncapped, same as
    # failing_tests) - not the capped detail-string count.
    assert result.cases_run == 18
    assert result.cases_passed == 0


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


def test_run_mode_c_class_method_case_constructs_then_calls():
    """Class-only files (all public logic in methods, no top-level functions
    - e.g. a real blinker/base.py or argcomplete/my_argparse.py) previously
    had nothing for Mode C to characterize at all. A class_name-bearing
    TestCase builds an instance first, then calls the method on it."""
    case = TestCase(
        function_name="resize",
        args_literal="(4,)",
        class_name="Widget",
        constructor_args_literal="(10,)",
        rationale="typical",
    )
    py2 = _ScriptedRuntime(outputs=["RESULT:14\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:14\n"])

    result = run_mode_c(
        module_filename="widgets.py",
        module_source_py2="class Widget:\n    def __init__(self, w):\n        self.w = w\n    def resize(self, d):\n        return self.w + d\n",
        module_source_py3="class Widget:\n    def __init__(self, w):\n        self.w = w\n    def resize(self, d):\n        return self.w + d\n",
        test_plan_cases=[case],
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="llm_inference",
    )

    assert result.outcome == GateOutcome.PASS
    driver = py2.captured_tree["_shiftcode_driver.py"]
    assert "_ctor_args = (10,)" in driver
    assert "_inst = _mod.Widget(*_ctor_args)" in driver
    assert "_inst.resize(*_args)" in driver


def test_run_mode_c_class_method_case_defaults_constructor_args_to_empty():
    case = TestCase(function_name="ping", args_literal="()", class_name="Server", rationale="typical")
    py2 = _ScriptedRuntime(outputs=["RESULT:'pong'\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:'pong'\n"])

    result = run_mode_c(
        module_filename="srv.py",
        module_source_py2="class Server:\n    def ping(self):\n        return 'pong'\n",
        module_source_py3="class Server:\n    def ping(self):\n        return 'pong'\n",
        test_plan_cases=[case],
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="llm_inference",
    )

    assert result.outcome == GateOutcome.PASS
    driver = py2.captured_tree["_shiftcode_driver.py"]
    assert "_ctor_args = ()" in driver
    assert "_inst = _mod.Server(*_ctor_args)" in driver


def test_run_mode_c_class_method_case_catches_a_real_mismatch():
    case = TestCase(
        function_name="resize", args_literal="(4,)", class_name="Widget", constructor_args_literal="(10,)", rationale="typical"
    )
    py2 = _ScriptedRuntime(outputs=["RESULT:14\n"])
    py3 = _ScriptedRuntime(outputs=["RESULT:99\n"])  # real behavior difference

    result = run_mode_c(
        module_filename="widgets.py",
        module_source_py2="class Widget: pass\n",
        module_source_py3="class Widget: pass\n",
        test_plan_cases=[case],
        py2_runtime=py2,
        py3_runtime=py3,
        evidence_source="llm_inference",
    )

    assert result.outcome == GateOutcome.FAIL
