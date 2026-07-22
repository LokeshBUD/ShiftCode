"""Regression: a real transient network timeout during a real stress-test run
propagated all the way up as an unhandled LLMTimeoutError and crashed the
entire `shiftcode migrate` process - not just the one file being processed.
call_structured only retried LLMOutputError (malformed responses); a
different exception class for network failures went entirely uncaught."""

from pydantic import BaseModel

from shiftcode.agents.base import AgentOutputError, call_structured
from shiftcode.llm.base import LLMProvider
from shiftcode.llm.errors import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMOutputError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class _Dummy(BaseModel):
    x: int


class _ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, prompt, **kw):
        raise NotImplementedError

    def generate_structured(self, prompt, *, schema, system=None, temperature=0.0):
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _no_sleep(seconds):
    pass  # tests shouldn't actually wait out backoff delays


def test_retries_transient_timeout_and_eventually_succeeds():
    provider = _ScriptedProvider([LLMTimeoutError("timed out"), _Dummy(x=1)])
    result = call_structured(provider, prompt="p", schema=_Dummy, sleep_fn=_no_sleep)
    assert result == _Dummy(x=1)
    assert provider.calls == 2


def test_retries_connection_and_rate_limit_errors_too():
    provider = _ScriptedProvider([LLMConnectionError("dropped"), LLMRateLimitError("429"), _Dummy(x=2)])
    result = call_structured(provider, prompt="p", schema=_Dummy, max_transient_retries=3, sleep_fn=_no_sleep)
    assert result == _Dummy(x=2)
    assert provider.calls == 3


def test_raises_agent_output_error_not_llm_error_after_exhausting_transient_retries():
    """The critical fix: this must surface as AgentOutputError (which every
    call site already catches and degrades gracefully), never as a raw
    LLMTimeoutError propagating uncaught and crashing the whole run."""
    provider = _ScriptedProvider(
        [LLMTimeoutError("1"), LLMTimeoutError("2"), LLMTimeoutError("3"), LLMTimeoutError("4")]
    )
    try:
        call_structured(provider, prompt="p", schema=_Dummy, max_transient_retries=3, sleep_fn=_no_sleep)
        assert False, "expected AgentOutputError"
    except AgentOutputError as exc:
        assert "transient-network" in str(exc)
    except LLMTimeoutError:
        assert False, "raw LLMTimeoutError escaped - this is the exact bug being fixed"


def test_backoff_increases_between_transient_retries():
    delays = []
    provider = _ScriptedProvider([LLMTimeoutError("1"), LLMTimeoutError("2"), _Dummy(x=3)])
    call_structured(
        provider, prompt="p", schema=_Dummy, max_transient_retries=3, backoff_seconds=2.0, sleep_fn=delays.append
    )
    assert delays == [2.0, 4.0]  # linear backoff: backoff_seconds * attempt_number


def test_authentication_error_is_not_retried_and_propagates_immediately():
    """A bad API key fails identically on every call - retrying wastes time
    and, at the run level, grinding through every remaining file with the
    same doomed call is worse than failing fast with one clear error."""
    provider = _ScriptedProvider([LLMAuthenticationError("bad key"), _Dummy(x=1)])
    try:
        call_structured(provider, prompt="p", schema=_Dummy, sleep_fn=_no_sleep)
        assert False, "expected LLMAuthenticationError to propagate"
    except LLMAuthenticationError:
        pass
    assert provider.calls == 1  # never retried


def test_output_and_transient_retries_have_independent_budgets():
    provider = _ScriptedProvider([LLMOutputError("bad json"), LLMTimeoutError("timeout"), _Dummy(x=9)])
    result = call_structured(
        provider, prompt="p", schema=_Dummy, max_retries=1, max_transient_retries=1, sleep_fn=_no_sleep
    )
    assert result == _Dummy(x=9)
    assert provider.calls == 3
