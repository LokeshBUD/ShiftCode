import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from shiftcode.llm.errors import LLMOutputError

T = TypeVar("T", bound=BaseModel)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class LLMResponse:
    text: str
    raw: dict[str, Any]
    model: str
    finish_reason: str | None = None


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        *,
        schema: type[T],
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T: ...

    def describe(self) -> str:
        return self.name


def extract_json_object(text: str) -> str:
    """Pull a JSON object out of free-form model output: fenced code block first, else the
    first balanced-looking {...} span, else the raw text as a last resort."""
    fenced = _FENCED_JSON_RE.search(text)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_structured_fallback(text: str, schema: type[T]) -> T:
    """Best-effort parse of a schema instance out of plain generate() text output, for
    providers/endpoints that don't support native structured outputs."""
    candidate = extract_json_object(text)
    try:
        return schema.model_validate_json(candidate)
    except (ValueError, json.JSONDecodeError) as exc:
        raise LLMOutputError(f"could not parse {schema.__name__} from model output: {exc}") from exc
