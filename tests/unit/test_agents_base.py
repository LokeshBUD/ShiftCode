import pytest
from pydantic import BaseModel

from shiftcode.agents.base import (
    AgentOutputError,
    SpliceError,
    apply_symbol_blocks,
    call_structured,
)
from shiftcode.llm.base import LLMProvider
from shiftcode.llm.errors import LLMOutputError
from shiftcode.models.agent_io import SymbolBlock

SOURCE = '''def foo(a, b):
    return a / b


class Calc(object):
    def divide(self, a, b):
        return a / b

    def multiply(self, a, b):
        return a * b
'''


def test_splice_replaces_top_level_function():
    out = apply_symbol_blocks(
        SOURCE, [SymbolBlock(symbol="foo", new_source="def foo(a, b):\n    return a // b\n")]
    )
    assert "return a // b" in out
    assert "def multiply" in out  # untouched sibling survives


def test_splice_replaces_method():
    out = apply_symbol_blocks(
        SOURCE,
        [SymbolBlock(symbol="Calc.divide", new_source="def divide(self, a, b):\n        return a // b\n")],
    )
    assert "return a // b" in out
    assert "def foo(a, b):\n    return a / b" in out  # untouched sibling survives


def test_splice_module_sentinel_replaces_whole_file():
    out = apply_symbol_blocks(SOURCE, [SymbolBlock(symbol="__module__", new_source="# replaced\n")])
    assert out == "# replaced\n"


def test_splice_raises_on_unresolved_symbol():
    with pytest.raises(SpliceError):
        apply_symbol_blocks(SOURCE, [SymbolBlock(symbol="does_not_exist", new_source="x")])


def test_splice_raises_on_overlapping_blocks():
    with pytest.raises(SpliceError):
        apply_symbol_blocks(
            SOURCE,
            [
                SymbolBlock(symbol="foo", new_source="def foo(a,b): pass\n"),
                SymbolBlock(symbol="foo", new_source="def foo(a,b): pass\n"),
            ],
        )


class _Dummy(BaseModel):
    x: int


class _FlakyOnceProvider(LLMProvider):
    name = "flaky"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, **kw):
        raise NotImplementedError

    def generate_structured(self, prompt, *, schema, system=None, temperature=0.0):
        self.calls += 1
        if self.calls == 1:
            raise LLMOutputError("bad json")
        return schema(x=42)


class _AlwaysBadProvider(LLMProvider):
    name = "always-bad"

    def generate(self, prompt, **kw):
        raise NotImplementedError

    def generate_structured(self, prompt, *, schema, system=None, temperature=0.0):
        raise LLMOutputError("still bad")


def test_call_structured_retries_once_and_succeeds():
    provider = _FlakyOnceProvider()
    result = call_structured(provider, prompt="give me json", schema=_Dummy, max_retries=1)
    assert result == _Dummy(x=42)
    assert provider.calls == 2


def test_call_structured_raises_agent_output_error_after_exhausting_retries():
    provider = _AlwaysBadProvider()
    with pytest.raises(AgentOutputError):
        call_structured(provider, prompt="give me json", schema=_Dummy, max_retries=1)
