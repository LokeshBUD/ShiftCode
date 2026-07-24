import hashlib
import json
from pathlib import Path

from shiftcode.models import (
    BehaviorResult,
    DeterminismResult,
    FileUnit,
    GateOutcome,
    MigrationPlan,
    Py2Finding,
    RepairAttempt,
    Status,
    SyntaxResult,
    TestCase,
    VerifyResult,
)

CHECKPOINT_FILENAME = ".shiftcode_checkpoint.json"

# A file only counts as safe to skip on resume once it reached one of these -
# anything else (PENDING, TRANSFORMED) means the previous run was killed
# mid-file, and there's no guarantee the file's own final_source/reason ever
# got set to something real. Redo it rather than trust a half-finished state.
TERMINAL_STATUSES = {Status.VERIFIED, Status.VERIFIED_RECORDED, Status.VERIFIED_INFERRED, Status.NEEDS_REVIEW}


def source_hash(source: str) -> str:
    """sha256 of the file's own original_source - the resume check's only
    correctness guard. A file that changed on disk since the checkpoint was
    written must never be silently skipped as if it were still the same
    file; this is what catches that, not the path alone."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def checkpoint_path(checkpoint_dir: Path) -> Path:
    return checkpoint_dir / CHECKPOINT_FILENAME


def load_checkpoint(checkpoint_dir: Path, *, root: Path) -> dict[str, dict]:
    """Never raises - a missing, corrupt, or different-root checkpoint is
    always treated the same as "no checkpoint at all," which just means
    starting fresh. A checkpoint should only ever help, never block a run."""
    path = checkpoint_path(checkpoint_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict) or data.get("root") != str(root):
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def write_checkpoint(checkpoint_dir: Path, *, root: Path, files_snapshot: dict[str, dict]) -> None:
    """Atomic write (temp file + os.replace): a kill mid-write must never
    leave a corrupt/partial checkpoint on disk - that's precisely the
    scenario this whole feature exists to survive, so the write path itself
    has to be safe against it too."""
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = checkpoint_path(checkpoint_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"root": str(root), "files": files_snapshot}, indent=2))
    tmp.replace(path)


def _serialize_verify_result(v: VerifyResult) -> dict:
    out = {}
    if v.syntax:
        out["syntax"] = {
            "passed": v.syntax.passed,
            "error_message": v.syntax.error_message,
            "error_line": v.syntax.error_line,
            "error_offset": v.syntax.error_offset,
        }
    if v.behavior:
        out["behavior"] = {
            "outcome": v.behavior.outcome.value,
            "mode": v.behavior.mode,
            "detail": v.behavior.detail,
            "failing_tests": v.behavior.failing_tests,
            "evidence_source": v.behavior.evidence_source,
            "cases_run": v.behavior.cases_run,
            "cases_passed": v.behavior.cases_passed,
        }
    if v.determinism:
        out["determinism"] = {
            "outcome": v.determinism.outcome.value,
            "runs": v.determinism.runs,
            "detail": v.determinism.detail,
        }
    return out


def _deserialize_verify_result(d: dict) -> VerifyResult:
    syntax = SyntaxResult(**d["syntax"]) if "syntax" in d else None
    behavior = None
    if "behavior" in d:
        b = dict(d["behavior"])
        b["outcome"] = GateOutcome(b["outcome"])
        behavior = BehaviorResult(**b)
    determinism = None
    if "determinism" in d:
        de = dict(d["determinism"])
        de["outcome"] = GateOutcome(de["outcome"])
        determinism = DeterminismResult(**de)
    return VerifyResult(syntax=syntax, behavior=behavior, determinism=determinism)


def serialize_file_unit(f: FileUnit) -> dict:
    """Enough to skip re-processing this file next run and redisplay it
    faithfully in the final report - not a byte-perfect FileUnit clone.
    fixer_name is deliberately dropped from findings (informational only,
    unused by report rendering or resume validation) to keep this simple."""
    return {
        "source_hash": source_hash(f.original_source),
        "status": f.status.value,
        "reason": f.reason,
        "final_source": f.final_source,
        "plan": f.plan.model_dump() if f.plan else None,
        "py2_findings": [
            {
                "construct_name": x.construct_name,
                "line": x.line,
                "col": x.col,
                "fixer_name": x.fixer_name,
                "needs_llm": x.needs_llm,
                "detail": x.detail,
            }
            for x in f.py2_findings
        ],
        "characterization_cases": [c.model_dump() for c in f.characterization_cases],
        "repair_attempts": [
            {
                "attempt_number": a.attempt_number,
                "candidate_source": a.candidate_source,
                "failure_summary": a.failure_summary,
                "hint": a.hint,
            }
            for a in f.repair_attempts
        ],
        "verify_result": _serialize_verify_result(f.verify_result) if f.verify_result else None,
    }


def restore_file_unit(file_unit: FileUnit, snapshot: dict) -> None:
    """Mutates file_unit in place with a previous run's result, so callers
    can splice a restored result into an already-ingested FileUnit without
    replacing it in any list that indexes by object identity. path and
    original_source are left untouched - they're already the real, current
    values from THIS run's own ingest()."""
    file_unit.status = Status(snapshot["status"])
    file_unit.reason = snapshot.get("reason")
    file_unit.final_source = snapshot.get("final_source")
    plan_snapshot = snapshot.get("plan")
    file_unit.plan = MigrationPlan.model_validate(plan_snapshot) if plan_snapshot else None
    file_unit.py2_findings = [Py2Finding(**x) for x in snapshot.get("py2_findings", [])]
    file_unit.characterization_cases = [TestCase.model_validate(c) for c in snapshot.get("characterization_cases", [])]
    file_unit.repair_attempts = [RepairAttempt(**a) for a in snapshot.get("repair_attempts", [])]
    verify_snapshot = snapshot.get("verify_result")
    file_unit.verify_result = _deserialize_verify_result(verify_snapshot) if verify_snapshot else None
