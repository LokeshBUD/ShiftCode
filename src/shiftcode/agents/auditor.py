import difflib

from shiftcode.agents.base import call_structured, load_prompt, render_prompt
from shiftcode.llm.base import LLMProvider
from shiftcode.models import MigrationPlan, RepairHint

_STATIC_PROMPT = load_prompt("auditor")


def _render_diff(before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="before (deterministic output)",
        tofile="after (Refactorer candidate)",
        lineterm="",
    )
    text = "\n".join(diff)
    return text if text else "(no textual difference)"


def _render_plan(plan: MigrationPlan) -> str:
    if not plan.steps:
        return "(empty plan)"
    return "\n".join(f"- [{s.finding_ref}] {s.description} (rationale: {s.rationale})" for s in plan.steps)


def _render_dynamic(
    deterministic_source: str, plan: MigrationPlan, candidate_source: str, failure_detail: str
) -> str:
    return "\n\n".join(
        [
            "## Migration plan\n" + _render_plan(plan),
            "## Diff (before -> Refactorer candidate)\n```diff\n"
            + _render_diff(deterministic_source, candidate_source)
            + "\n```",
            "## Gate failure\n" + failure_detail,
        ]
    )


class AuditorAgent:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1):
        self.provider = provider
        self.max_retries = max_retries

    def diagnose(
        self,
        *,
        deterministic_source: str,
        plan: MigrationPlan,
        candidate_source: str,
        failure_detail: str,
    ) -> RepairHint:
        prompt = render_prompt(
            _STATIC_PROMPT,
            _render_dynamic(deterministic_source, plan, candidate_source, failure_detail),
        )
        return call_structured(
            self.provider, prompt=prompt, schema=RepairHint, max_retries=self.max_retries
        )
