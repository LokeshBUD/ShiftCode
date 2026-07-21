"""resolve_execution_runtimes' fallback policy: py2 unchanged (local -> docker ->
unavailable). py3 for Mode A/B prefers docker but falls back to local if Docker
is unavailable (today's proven availability). py3 for Mode C is docker-only,
no local fallback - never runs guessed inputs unsandboxed."""

from shiftcode.config import LLMConfig, ShiftConfig
from shiftcode.pipeline.verify.sandbox_runtime import resolve_execution_runtimes


def _config(**overrides) -> ShiftConfig:
    return ShiftConfig(llm=LLMConfig(), agent_overrides={}, **overrides)


def test_py3_for_ab_falls_back_to_local_when_docker_unavailable(monkeypatch):
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime._docker_daemon_reachable", lambda: False)
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime.shutil.which", lambda name: None)

    runtimes = resolve_execution_runtimes(_config())

    assert runtimes.py3_for_ab.available
    assert runtimes.py3_for_ab.kind == "local"


def test_py3_for_c_has_no_fallback_when_docker_unavailable(monkeypatch):
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime._docker_daemon_reachable", lambda: False)
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime.shutil.which", lambda name: None)

    runtimes = resolve_execution_runtimes(_config())

    assert not runtimes.py3_for_c.available
    assert runtimes.py3_for_c.kind == "unavailable"


def test_py3_for_ab_and_c_both_docker_when_available(monkeypatch):
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime._docker_daemon_reachable", lambda: True)

    runtimes = resolve_execution_runtimes(_config())

    assert runtimes.py3_for_ab.kind == "docker"
    assert runtimes.py3_for_c.kind == "docker"
    assert runtimes.py3_for_ab.available
    assert runtimes.py3_for_c.available


def test_py2_policy_unchanged_by_this_feature(monkeypatch):
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime._docker_daemon_reachable", lambda: False)
    monkeypatch.setattr("shiftcode.pipeline.verify.sandbox_runtime.shutil.which", lambda name: None)

    runtimes = resolve_execution_runtimes(_config())

    assert not runtimes.py2.available
    assert runtimes.py2.kind == "unavailable"
