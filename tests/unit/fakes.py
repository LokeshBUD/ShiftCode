from pydantic import BaseModel

from shiftcode.llm.base import LLMProvider, LLMResponse


class StubProvider(LLMProvider):
    """Scripted per-agent responses, returned in sequence. Implements
    generate_structured directly (no real network/API-key dependency, and no
    dependence on real structured-output support), so tests exercise
    agent/orchestrator logic in isolation."""

    def __init__(self, responses: list[BaseModel | Exception]):
        self.name = "stub"
        self._responses = list(responses)
        self.calls: list[str] = []

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        raise NotImplementedError("StubProvider only implements generate_structured")

    def generate_structured(self, prompt: str, *, schema, system=None, temperature=0.0):
        self.calls.append(prompt)
        if not self._responses:
            raise AssertionError("StubProvider ran out of scripted responses")
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        assert isinstance(next_response, schema), (
            f"scripted response {type(next_response).__name__} doesn't match requested schema {schema.__name__}"
        )
        return next_response
