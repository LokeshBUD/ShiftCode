from pathlib import Path

from shiftcode.models import (
    BehaviorResult,
    FileUnit,
    GateOutcome,
    MigrationPlan,
    Py2Finding,
    PlanStep,
    RepairAttempt,
    Status,
    SyntaxResult,
    TestCase,
    VerifyResult,
)
from shiftcode.pipeline.checkpoint import (
    load_checkpoint,
    restore_file_unit,
    serialize_file_unit,
    source_hash,
    write_checkpoint,
)


def _verified_file_unit() -> FileUnit:
    fu = FileUnit(path=Path("m.py"), original_source="def f(x):\n    return x\n")
    fu.status = Status.VERIFIED
    fu.final_source = "def f(x):\n    return x\n"
    fu.plan = MigrationPlan(steps=[PlanStep(finding_ref="x@1:1", description="d", rationale="r")])
    fu.py2_findings = [Py2Finding(construct_name="c", line=1, col=0, fixer_name="fix_x", needs_llm=True, detail="d")]
    fu.characterization_cases = [TestCase(function_name="f", args_literal="(1,)", rationale="typical")]
    fu.repair_attempts = [RepairAttempt(attempt_number=1, candidate_source="x", failure_summary="", hint=None)]
    fu.verify_result = VerifyResult(
        syntax=SyntaxResult(passed=True),
        behavior=BehaviorResult(outcome=GateOutcome.PASS, mode="A", detail="ok", cases_run=1, cases_passed=1),
    )
    return fu


def test_source_hash_is_stable_and_content_sensitive():
    assert source_hash("x = 1\n") == source_hash("x = 1\n")
    assert source_hash("x = 1\n") != source_hash("x = 2\n")


def test_serialize_then_restore_round_trips_everything_needed():
    original = _verified_file_unit()
    snapshot = serialize_file_unit(original)

    restored = FileUnit(path=original.path, original_source=original.original_source)
    restore_file_unit(restored, snapshot)

    assert restored.status == Status.VERIFIED
    assert restored.final_source == original.final_source
    assert restored.plan.steps[0].description == "d"
    assert restored.py2_findings[0].construct_name == "c"
    assert restored.characterization_cases[0].function_name == "f"
    assert restored.repair_attempts[0].attempt_number == 1
    assert restored.verify_result.behavior.outcome == GateOutcome.PASS
    assert restored.verify_result.behavior.cases_passed == 1


def test_write_then_load_checkpoint_round_trips(tmp_path):
    root = tmp_path / "proj"
    checkpoint_dir = tmp_path / "ckpt"
    snapshot = {"m.py": serialize_file_unit(_verified_file_unit())}

    write_checkpoint(checkpoint_dir, root=root, files_snapshot=snapshot)
    loaded = load_checkpoint(checkpoint_dir, root=root)

    assert loaded == snapshot


def test_load_checkpoint_returns_empty_for_missing_directory(tmp_path):
    assert load_checkpoint(tmp_path / "does_not_exist", root=tmp_path / "proj") == {}


def test_load_checkpoint_returns_empty_when_root_does_not_match(tmp_path):
    checkpoint_dir = tmp_path / "ckpt"
    write_checkpoint(checkpoint_dir, root=tmp_path / "proj_a", files_snapshot={"m.py": {}})

    assert load_checkpoint(checkpoint_dir, root=tmp_path / "proj_b") == {}


def test_load_checkpoint_returns_empty_for_corrupt_json(tmp_path):
    checkpoint_dir = tmp_path / "ckpt"
    checkpoint_dir.mkdir()
    (checkpoint_dir / ".shiftcode_checkpoint.json").write_text("not json at all {")

    assert load_checkpoint(checkpoint_dir, root=tmp_path / "proj") == {}


def test_write_checkpoint_is_atomic_no_leftover_tmp_file(tmp_path):
    checkpoint_dir = tmp_path / "ckpt"
    write_checkpoint(checkpoint_dir, root=tmp_path / "proj", files_snapshot={"m.py": {}})

    files = list(checkpoint_dir.iterdir())
    assert [f.name for f in files] == [".shiftcode_checkpoint.json"]
