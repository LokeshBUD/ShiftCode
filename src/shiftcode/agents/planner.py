from shiftcode.agents.base import call_structured, load_prompt, render_prompt
from shiftcode.llm.base import LLMProvider
from shiftcode.models import DependencySlice, MigrationPlan, Py2Finding

_STATIC_PROMPT = load_prompt("planner")


def _finding_ref(finding: Py2Finding) -> str:
    return f"{finding.construct_name}@{finding.line}:{finding.col}"


def _render_findings(findings: list[Py2Finding]) -> str:
    lines = []
    for f in findings:
        status = "needs your judgment" if f.needs_llm else "mechanically resolved"
        line = f"- {_finding_ref(f)}: {f.construct_name} ({status})"
        if f.detail:
            line += f"\n    {f.detail}"
        lines.append(line)
    return "\n".join(lines) if lines else "(no py2 constructs found)"


def _render_slice(s: DependencySlice) -> str:
    parts = [
        f"finding at line {s.finding_line}, col {s.finding_col}",
        f"enclosing function: {s.enclosing_function or '(module level)'}",
        f"related lines: {s.related_lines}",
        f"downstream usage: {s.downstream_usage or '(none detected)'}",
    ]
    if s.snippet:
        parts.append(f"snippet:\n{s.snippet}")
    return "\n".join(parts)


def _render_dynamic(
    original_source: str, findings: list[Py2Finding], dependency_slices: list[DependencySlice]
) -> str:
    sections = [
        "## Original source\n```python\n" + original_source + "\n```",
        "## Findings\n" + _render_findings(findings),
    ]
    if dependency_slices:
        slice_text = "\n\n".join(_render_slice(s) for s in dependency_slices)
        sections.append("## Dependency slices (for findings needing your judgment)\n" + slice_text)
    return "\n\n".join(sections)


class PlannerAgent:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1):
        self.provider = provider
        self.max_retries = max_retries

    def plan(
        self,
        *,
        original_source: str,
        findings: list[Py2Finding],
        dependency_slices: list[DependencySlice],
    ) -> MigrationPlan:
        prompt = render_prompt(
            _STATIC_PROMPT, _render_dynamic(original_source, findings, dependency_slices)
        )
        return call_structured(
            self.provider,
            prompt=prompt,
            schema=MigrationPlan,
            max_retries=self.max_retries,
        )
