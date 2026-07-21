from shiftcode.agents.base import call_structured, load_prompt, render_prompt
from shiftcode.llm.base import LLMProvider
from shiftcode.models import CallSiteEvidence, CharacterizationTestPlan

_STATIC_PROMPT = load_prompt("characterization")


def _render_call_site_evidence(evidence: list[CallSiteEvidence]) -> str:
    if not evidence:
        return "(none found)"
    return "\n".join(f"- called as {e.symbol}{e.args_repr} in {e.caller_file}:{e.context_line}" for e in evidence)


def _render_dynamic(function_source: str, docstring: str | None, call_site_evidence: list[CallSiteEvidence]) -> str:
    sections = [
        "## Function source\n```python\n" + function_source + "\n```",
        "## Docstring\n" + (docstring if docstring else "(none)"),
        "## Call-site evidence\n" + _render_call_site_evidence(call_site_evidence),
    ]
    return "\n\n".join(sections)


class CharacterizationAgent:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1):
        self.provider = provider
        self.max_retries = max_retries

    def propose_tests(
        self,
        *,
        function_source: str,
        docstring: str | None,
        call_site_evidence: list[CallSiteEvidence],
    ) -> CharacterizationTestPlan:
        prompt = render_prompt(
            _STATIC_PROMPT, _render_dynamic(function_source, docstring, call_site_evidence)
        )
        return call_structured(
            self.provider,
            prompt=prompt,
            schema=CharacterizationTestPlan,
            max_retries=self.max_retries,
        )
