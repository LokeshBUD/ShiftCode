"""Regression: lib2to3's tolerant grammar can successfully parse and
mechanically transform py2 source that still isn't valid Python 3 afterward
(real case, docs/bug-log.md #14: an obscure `if not hasattr(__builtins__,
'True'): True, False = 1, 0` shim that lib2to3 has no fixer for). Before the
fix, find_semantic_findings's ast.parse raised a raw, uncaught SyntaxError
that fell through to run_migration's generic per-file backstop with a
confusing message instead of a clear diagnosis."""

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

# lib2to3 has no fixer for this obscure py2.2-era True/False builtin shim -
# it survives deterministic_transform unchanged, and is a real SyntaxError
# under Python 3's actual parser (True/False are reserved keywords there).
SOURCE_WITH_UNFIXABLE_SYNTAX = (
    "if not hasattr(__builtins__, 'True'): True, False = 1, 0\n"
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
