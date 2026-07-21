from shiftcode.agents.base import (
    MODULE_SENTINEL,
    SpliceError,
    apply_symbol_blocks,
    call_structured,
    load_prompt,
    render_prompt,
)
from shiftcode.llm.base import LLMProvider
from shiftcode.models import MigrationPlan, RefactorPatch, RepairHint

_STATIC_PROMPT = load_prompt("refactorer")


def _render_plan(plan: MigrationPlan) -> str:
    if not plan.steps:
        return "(no plan steps - nothing for you to change)"
    lines = []
    for step in plan.steps:
        lines.append(f"- [{step.finding_ref}] {step.description} (rationale: {step.rationale})")
    return "\n".join(lines)


def _render_hints(hints: list[RepairHint]) -> str:
    if not hints:
        return ""
    lines = [f"- root cause: {h.root_cause}\n  hint: {h.hint}" for h in hints]
    return "\n\n## Auditor hints from previous attempt(s)\n" + "\n".join(lines)


def _render_dynamic(source: str, plan: MigrationPlan, hints: list[RepairHint]) -> str:
    sections = [
        "## Current source\n```python\n" + source + "\n```",
        "## Migration plan\n" + _render_plan(plan),
    ]
    hint_section = _render_hints(hints)
    if hint_section:
        sections.append(hint_section)
    return "\n\n".join(sections)


class RefactorerAgent:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1):
        self.provider = provider
        self.max_retries = max_retries

    def refactor(
        self,
        *,
        deterministic_source: str,
        plan: MigrationPlan,
        hints: list[RepairHint] | None = None,
    ) -> str:
        hints = hints or []
        prompt = render_prompt(_STATIC_PROMPT, _render_dynamic(deterministic_source, plan, hints))
        patch = call_structured(
            self.provider, prompt=prompt, schema=RefactorPatch, max_retries=self.max_retries
        )
        try:
            return apply_symbol_blocks(deterministic_source, patch.blocks)
        except SpliceError:
            return self._request_full_file(deterministic_source, plan, hints)

    def _request_full_file(
        self, deterministic_source: str, plan: MigrationPlan, hints: list[RepairHint]
    ) -> str:
        dynamic = _render_dynamic(deterministic_source, plan, hints) + (
            "\n\nYour previous response's symbol block(s) could not be applied "
            "(symbol not found, or an ambiguous/overlapping edit). Return a "
            f'single block with symbol="{MODULE_SENTINEL}" containing the '
            "ENTIRE corrected file as new_source."
        )
        prompt = render_prompt(_STATIC_PROMPT, dynamic)
        patch = call_structured(
            self.provider, prompt=prompt, schema=RefactorPatch, max_retries=self.max_retries
        )
        return apply_symbol_blocks(deterministic_source, patch.blocks)
