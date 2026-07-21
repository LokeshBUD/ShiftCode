from shiftcode.config import LLMConfig
from shiftcode.llm.base import LLMProvider, LLMResponse
from shiftcode.llm.openai_compatible import OpenAICompatibleProvider


def get_provider(config: LLMConfig, *, name: str = "openai-compatible") -> LLMProvider:
    """Single factory used for both the shared and per-agent providers. Only one
    implementation exists today (OpenAI-compatible), but call sites depend on this
    factory rather than the concrete class, so adding a second provider later is a
    config change, not a call-site rewrite."""
    return OpenAICompatibleProvider(config, name=name)


__all__ = ["LLMProvider", "LLMResponse", "OpenAICompatibleProvider", "get_provider"]
