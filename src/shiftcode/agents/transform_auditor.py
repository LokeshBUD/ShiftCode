import difflib

from shiftcode.agents.base import call_structured, load_prompt, render_prompt
from shiftcode.llm.base import LLMProvider
from shiftcode.models import TransformAudit

_STATIC_PROMPT = load_prompt("transform_auditor")


def _render_diff(before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="original (py2)",
        tofile="deterministic transform output",
        lineterm="",
    )
    text = "\n".join(diff)
    return text if text else "(no textual difference)"


def _render_dynamic(original_source: str, deterministic_output: str) -> str:
    return "\n\n".join(
        [
            "## Original source\n```python\n" + original_source + "\n```",
            "## Transformed output\n```python\n" + deterministic_output + "\n```",
            "## Diff\n```diff\n" + _render_diff(original_source, deterministic_output) + "\n```",
        ]
    )


class TransformAuditorAgent:
    """Reviews the deterministic (zero-LLM) transform's own output for silent
    semantic drift - the deterministic layer is fast and reliable for the
    common case, but it's pure pattern matching with no scope/binding
    analysis, so it can (and, found via a real stress test, does) corrupt an
    identifier that collides with an existing local name. Runs once per file,
    right after deterministic_transform, before the Planner. Its findings
    become ordinary needs_llm Py2Findings feeding into the SAME Planner ->
    Refactorer <-> Auditor loop everything else goes through - no separate
    repair path."""

    def __init__(self, provider: LLMProvider, *, max_retries: int = 1):
        self.provider = provider
        self.max_retries = max_retries

    def review(self, *, original_source: str, deterministic_output: str) -> TransformAudit:
        prompt = render_prompt(_STATIC_PROMPT, _render_dynamic(original_source, deterministic_output))
        return call_structured(
            self.provider,
            prompt=prompt,
            schema=TransformAudit,
            max_retries=self.max_retries,
        )
