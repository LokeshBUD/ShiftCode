import json

from shiftcode.models import FileUnit, MigrationReport, VerifyResult


def build_report(files: list[FileUnit]) -> MigrationReport:
    return MigrationReport(files=files)


def _verify_summary(v: VerifyResult) -> dict:
    out = {}
    if v.syntax:
        out["syntax"] = {
            "passed": v.syntax.passed,
            "error": v.syntax.error_message,
            "line": v.syntax.error_line,
        }
    if v.behavior:
        out["behavior"] = {
            "outcome": v.behavior.outcome.value,
            "mode": v.behavior.mode,
            "detail": v.behavior.detail,
            "evidence_source": v.behavior.evidence_source,
        }
    if v.determinism:
        out["determinism"] = {"outcome": v.determinism.outcome.value, "detail": v.determinism.detail}
    return out


def _file_summary_dict(f: FileUnit) -> dict:
    return {
        "path": str(f.path),
        "status": f.status.value,
        "reason": f.reason,
        "findings": [
            {
                "construct": x.construct_name,
                "line": x.line,
                "col": x.col,
                "needs_llm": x.needs_llm,
            }
            for x in f.py2_findings
        ],
        "plan_steps": [s.model_dump() for s in f.plan.steps] if f.plan else [],
        "characterization_cases": [c.model_dump() for c in f.characterization_cases],
        "repair_attempts": [
            {
                "attempt": a.attempt_number,
                "failure": a.failure_summary,
                "hint": a.hint,
                "candidate_source": a.candidate_source,
            }
            for a in f.repair_attempts
        ],
        "verify": _verify_summary(f.verify_result) if f.verify_result else None,
        "final_source": f.final_source,
    }


def to_json(report: MigrationReport) -> str:
    return json.dumps({"files": [_file_summary_dict(f) for f in report.files]}, indent=2)


def to_text(report: MigrationReport) -> str:
    counts: dict[str, int] = {}
    for f in report.files:
        counts[f.status.value] = counts.get(f.status.value, 0) + 1

    lines = ["ShiftCode migration report", "=" * 40]
    for status, count in sorted(counts.items()):
        lines.append(f"{status}: {count}")
    lines.append("")
    for f in report.files:
        lines.append(f"- {f.path} [{f.status.value}]")
        if f.reason:
            lines.append(f"    reason: {f.reason}")
        if f.repair_attempts:
            lines.append(f"    repair attempts: {len(f.repair_attempts)}")
        if f.characterization_cases:
            evidence = f.verify_result.behavior.evidence_source if f.verify_result and f.verify_result.behavior else None
            lines.append(
                f"    characterization tests: {len(f.characterization_cases)} case(s)"
                + (f" (evidence: {evidence})" if evidence else "")
            )
    return "\n".join(lines)
