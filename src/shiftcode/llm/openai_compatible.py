from typing import TypeVar

import openai
from pydantic import BaseModel

from shiftcode.config import LLMConfig
from shiftcode.llm.base import LLMProvider, LLMResponse, parse_structured_fallback
from shiftcode.llm.errors import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)

T = TypeVar("T", bound=BaseModel)


def _wrap_sdk_error(exc: Exception) -> LLMError:
    if isinstance(exc, openai.AuthenticationError):
        return LLMAuthenticationError(str(exc))
    if isinstance(exc, openai.RateLimitError):
        return LLMRateLimitError(str(exc))
    if isinstance(exc, openai.APITimeoutError):
        return LLMTimeoutError(str(exc))
    if isinstance(exc, openai.APIConnectionError):
        return LLMConnectionError(str(exc))
    return LLMError(str(exc))


class OpenAICompatibleProvider(LLMProvider):
    """Talks to any OpenAI-compatible chat-completions endpoint: OpenAI itself, Ollama,
    LM Studio, vLLM's OpenAI server, etc. Provider-agnosticism is a config change
    (base_url/api_key/model), not a code change."""

    def __init__(self, config: LLMConfig, *, name: str = "openai-compatible"):
        self.config = config
        self.name = name
        self._client = openai.OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if stop is not None:
            kwargs["stop"] = stop

        try:
            resp = self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=temperature,
                **kwargs,
            )
        except openai.OpenAIError as exc:
            raise _wrap_sdk_error(exc) from exc

        choice = resp.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            raw=resp.model_dump(),
            model=resp.model,
            finish_reason=choice.finish_reason,
        )

    def generate_structured(
        self,
        prompt: str,
        *,
        schema: type[T],
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        if self.config.supports_structured_outputs:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            try:
                resp = self._client.chat.completions.parse(
                    model=self.config.model,
                    messages=messages,
                    temperature=temperature,
                    response_format=schema,
                )
            except openai.OpenAIError as exc:
                raise _wrap_sdk_error(exc) from exc
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMError(f"provider returned no parsed {schema.__name__} (refusal or empty response)")
            return parsed

        response = self.generate(prompt, system=system, temperature=temperature)
        return parse_structured_fallback(response.text, schema)
