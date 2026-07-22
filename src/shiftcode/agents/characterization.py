from dataclasses import dataclass

from shiftcode.agents.base import call_structured, load_prompt, render_prompt
from shiftcode.llm.base import LLMProvider
from shiftcode.models import CallSiteEvidence, CharacterizationTestPlan

_STATIC_PROMPT = load_prompt("characterization")


@dataclass
class FunctionContext:
    name: str
    source: str
    docstring: str | None
    call_site_evidence: list[CallSiteEvidence]


def _render_call_site_evidence(evidence: list[CallSiteEvidence]) -> str:
    if not evidence:
        return "(none found)"
    return "\n".join(f"- called as {e.symbol}{e.args_repr} in {e.caller_file}:{e.context_line}" for e in evidence)


def _render_function(fn: FunctionContext) -> str:
    sections = [
        f"## Function: {fn.name}",
        "### Source\n```python\n" + fn.source + "\n```",
        "### Docstring\n" + (fn.docstring if fn.docstring else "(none)"),
        "### Call-site evidence\n" + _render_call_site_evidence(fn.call_site_evidence),
    ]
    return "\n\n".join(sections)


def _render_dynamic(functions: list[FunctionContext]) -> str:
    return "\n\n---\n\n".join(_render_function(fn) for fn in functions)


class CharacterizationAgent:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1):
        self.provider = provider
        self.max_retries = max_retries

    def propose_tests(self, *, functions: list[FunctionContext]) -> CharacterizationTestPlan:
        """One call for every function in a file (not one call per function) -
        each still gets its own full source/docstring/evidence section, but
        the static prompt prefix and the round-trip overhead are paid once
        per file instead of once per function."""
        prompt = render_prompt(_STATIC_PROMPT, _render_dynamic(functions))
        return call_structured(
            self.provider,
            prompt=prompt,
            schema=CharacterizationTestPlan,
            max_retries=self.max_retries,
        )
