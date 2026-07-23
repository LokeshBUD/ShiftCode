import json

from shiftcode.models import FileUnit, MigrationReport, VerifyResult


def build_report(files: list[FileUnit], *, dependency_provisioning: str | None = None) -> MigrationReport:
    return MigrationReport(files=files, dependency_provisioning=dependency_provisioning)


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
            "cases_run": v.behavior.cases_run,
            "cases_passed": v.behavior.cases_passed,
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
                "detail": x.detail,
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
    return json.dumps(
        {
            "dependency_provisioning": report.dependency_provisioning,
            "files": [_file_summary_dict(f) for f in report.files],
        },
        indent=2,
    )


_STATUS_COLOR = {
    "VERIFIED": "32",  # green
    "VERIFIED_RECORDED": "34",  # blue - real captured usage data, see Status docstring
    "VERIFIED_INFERRED": "36",  # cyan - real but weaker evidence, see Status docstring
    "NEEDS_REVIEW": "33",  # yellow
    "FAILED": "31",  # red
    "TRANSFORMED": "90",  # dim grey - intermediate, shouldn't normally be a terminal status
    "PENDING": "90",
}


def _colorize(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _cases_summary_line(f: FileUnit) -> str | None:
    """Real, exact evidence volume - generalizes what used to be a
    Mode-C-only line (keyed off characterization_cases) to any mode that
    tracks a real case count (behavior_gate.py's run_mode_a, run_mode_c) -
    e.g. `206/209 cases passed (Mode A)`. None when nothing meaningfully
    countable ran (Mode B, any UNVERIFIED outcome)."""
    behavior = f.verify_result.behavior if f.verify_result else None
    if behavior is None or behavior.cases_run is None:
        return None
    line = f"    {behavior.cases_passed}/{behavior.cases_run} cases passed (Mode {behavior.mode})"
    if behavior.evidence_source:
        line += f" (evidence: {behavior.evidence_source})"
    return line


def to_console(report: MigrationReport, *, color: bool = True) -> str:
    """Same information as to_text(), formatted for an interactive terminal:
    color-coded status badges and a per-status count header up top. Kept
    separate from to_text() (used for --report-format text and by anything
    parsing/grepping output) so adding color/formatting here never risks
    breaking a stable plain-text format something else might depend on."""
    counts: dict[str, int] = {}
    for f in report.files:
        counts[f.status.value] = counts.get(f.status.value, 0) + 1

    def badge(status: str) -> str:
        text = f"[{status}]"
        if not color:
            return text
        return _colorize(text, _STATUS_COLOR.get(status, "0"))

    lines = ["ShiftCode migration report", "=" * 40]
    for status, count in sorted(counts.items()):
        lines.append(f"{badge(status)} {count}")
    if report.dependency_provisioning:
        lines.append(f"dependencies: {report.dependency_provisioning}")
    lines.append("")
    for f in report.files:
        lines.append(f"{badge(f.status.value)} {f.path}")
        if f.reason:
            lines.append(f"    reason: {f.reason}")
        if f.repair_attempts:
            lines.append(f"    repair attempts: {len(f.repair_attempts)}")
        cases_line = _cases_summary_line(f)
        if cases_line:
            lines.append(cases_line)
    return "\n".join(lines)


def to_text(report: MigrationReport) -> str:
    counts: dict[str, int] = {}
    for f in report.files:
        counts[f.status.value] = counts.get(f.status.value, 0) + 1

    lines = ["ShiftCode migration report", "=" * 40]
    for status, count in sorted(counts.items()):
        lines.append(f"{status}: {count}")
    if report.dependency_provisioning:
        lines.append(f"dependencies: {report.dependency_provisioning}")
    lines.append("")
    for f in report.files:
        lines.append(f"- {f.path} [{f.status.value}]")
        if f.reason:
            lines.append(f"    reason: {f.reason}")
        if f.repair_attempts:
            lines.append(f"    repair attempts: {len(f.repair_attempts)}")
        cases_line = _cases_summary_line(f)
        if cases_line:
            lines.append(cases_line)
    return "\n".join(lines)
