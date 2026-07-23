from shiftcode.agents.base import call_structured, load_prompt, render_prompt
from shiftcode.llm.base import LLMProvider
from shiftcode.models import GeneralizedFixRule
from shiftcode.pipeline.repair_history import RepairHistoryEntry

_STATIC_PROMPT = load_prompt("fixer_rule")


def _render_entry(entry: RepairHistoryEntry) -> str:
    sections = [
        f"## Repair: {entry.file_path}",
        "### before_source\n```python\n" + entry.before_source + "\n```",
        "### after_source\n```python\n" + entry.after_source + "\n```",
        "### hints\n" + "\n".join(f"- {h}" for h in entry.hints),
        "### failure_summaries\n" + "\n".join(f"- {s}" for s in entry.failure_summaries),
    ]
    return "\n\n".join(sections)


class FixerRuleAgent:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1):
        self.provider = provider
        self.max_retries = max_retries

    def propose_rule(self, *, entry: RepairHistoryEntry) -> GeneralizedFixRule:
        """One call per confirmed repair - this runs offline (`suggest-fixer-rules`),
        never inside a live migration, so batching multiple entries into one
        call (like CharacterizationAgent.propose_tests does per-file) isn't
        needed here."""
        prompt = render_prompt(_STATIC_PROMPT, _render_entry(entry))
        return call_structured(
            self.provider,
            prompt=prompt,
            schema=GeneralizedFixRule,
            max_retries=self.max_retries,
        )
