"""Regression: lib2to3's tolerant grammar can successfully parse and
mechanically transform py2 source that still isn't valid Python 3 afterward.
Originally found via a real, obscure `if not hasattr(__builtins__, 'True'):
True, False = 1, 0` shim (docs/bug-log.md #14) that lib2to3 has no fixer for
- that exact construct now gets pre-empted by strip_dead_true_false_shim
before it can ever reach this path (see test_analyze.py), so this test uses
an analogous but distinct construct (assigning to `None`, the other Python 3
reserved-keyword-that-was-a-plain-builtin-in-py2) to keep exercising the
generic backstop this code path provides for whatever ISN'T (yet) a known,
specifically-handled case. Before the original fix, find_semantic_findings's
ast.parse raised a raw, uncaught SyntaxError that fell through to
run_migration's generic per-file backstop with a confusing message instead of
a clear diagnosis."""

from pathlib import Path

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.characterization import CharacterizationAgent
from shiftcode.agents.planner import PlannerAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.agents.transform_auditor import TransformAuditorAgent
from shiftcode.models import FileUnit, Status
from shiftcode.pipeline.orchestrator import _process_file
from shiftcode.pipeline.verify.sandbox_runtime import ExecutionRuntimes, SandboxRuntime

from fakes import StubProvider

UNAVAILABLE = SandboxRuntime(available=False, kind="unavailable", reason="not needed for this test")
RUNTIMES = ExecutionRuntimes(py2=UNAVAILABLE, py3_for_ab=UNAVAILABLE, py3_for_c=UNAVAILABLE)

# lib2to3 has no fixer for this construct - it survives deterministic_transform
# unchanged, and is a real SyntaxError under Python 3's actual parser (None
# is a reserved keyword there, never a valid assignment target - same
# category as the True/False shim this test file used to exercise directly).
SOURCE_WITH_UNFIXABLE_SYNTAX = (
    "if not hasattr(__builtins__, 'None'): None = 0\n"
    "def f(x):\n"
    "    return x\n"
)


def test_syntax_error_in_transformed_source_gives_clear_needs_review_reason():
    fu = FileUnit(path=Path("m.py"), original_source=SOURCE_WITH_UNFIXABLE_SYNTAX)

    _process_file(
        fu,
        [fu],
        planner=PlannerAgent(StubProvider([])),
        refactorer=RefactorerAgent(StubProvider([])),
        auditor=AuditorAgent(StubProvider([])),
        characterization_agent=CharacterizationAgent(StubProvider([])),
        transform_auditor=TransformAuditorAgent(StubProvider([])),
        runtimes=RUNTIMES,
        max_attempts=3,
        determinism_runs=3,
        test_info=None,
    )

    assert fu.status == Status.NEEDS_REVIEW
    assert "not valid Python 3" in fu.reason
    assert "unexpected error" not in fu.reason
