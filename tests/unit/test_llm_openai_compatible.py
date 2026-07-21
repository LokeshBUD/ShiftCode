from unittest.mock import MagicMock

from pydantic import BaseModel

from shiftcode.config import LLMConfig
from shiftcode.llm.openai_compatible import OpenAICompatibleProvider


class _Dummy(BaseModel):
    x: int
    y: str


def _make_provider(**overrides) -> OpenAICompatibleProvider:
    cfg = LLMConfig(model="test-model", **overrides)
    return OpenAICompatibleProvider(cfg)


def test_generate_returns_text_and_metadata():
    provider = _make_provider()
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="hello world"), finish_reason="stop")]
    fake_resp.model = "test-model"
    fake_resp.model_dump.return_value = {"ok": True}
    provider._client.chat.completions.create = MagicMock(return_value=fake_resp)

    result = provider.generate("hi")

    assert result.text == "hello world"
    assert result.model == "test-model"
    assert result.finish_reason == "stop"


def test_generate_structured_uses_parse_when_supported():
    provider = _make_provider(supports_structured_outputs=True)
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(parsed=_Dummy(x=1, y="a")))]
    provider._client.chat.completions.parse = MagicMock(return_value=fake_resp)

    result = provider.generate_structured("give me json", schema=_Dummy)

    assert result == _Dummy(x=1, y="a")
    provider._client.chat.completions.parse.assert_called_once()


def test_generate_structured_falls_back_to_text_parsing_when_unsupported():
    provider = _make_provider(supports_structured_outputs=False)
    fake_resp = MagicMock()
    fake_resp.choices = [
        MagicMock(
            message=MagicMock(content='sure, here: ```json\n{"x": 5, "y": "z"}\n```'),
            finish_reason="stop",
        )
    ]
    fake_resp.model = "test-model"
    fake_resp.model_dump.return_value = {}
    provider._client.chat.completions.create = MagicMock(return_value=fake_resp)

    result = provider.generate_structured("give me json", schema=_Dummy)

    assert result == _Dummy(x=5, y="z")
