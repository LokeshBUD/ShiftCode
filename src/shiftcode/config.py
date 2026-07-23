import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

AGENT_ROLES = ("planner", "refactorer", "auditor", "characterization", "transform_auditor", "fixer_rule")


@dataclass
class LLMConfig:
    base_url: str | None = None
    api_key: str = "not-needed"
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    timeout: float = 60.0
    max_retries: int = 2
    supports_structured_outputs: bool = True


@dataclass
class ShiftConfig:
    llm: LLMConfig
    agent_overrides: dict[str, LLMConfig]
    py2_interpreter: str | None = None
    # ShiftCode's own images (docker/*-sandbox.Dockerfile): bare python:2.7 /
    # python:3-slim plus pytest pre-installed, so Mode A can actually run
    # pytest-style test suites (see docs/bug-log.md #5) without needing
    # runtime network access - built once, offline, auto-built on first use
    # if not already present locally (sandbox_runtime.py).
    py2_docker_image: str = "shiftcode-py2-sandbox"
    py3_docker_image: str = "shiftcode-py3-sandbox"
    install_project_dependencies: bool = True
    sandbox_memory_limit: str = "256m"
    sandbox_cpu_limit: str = "1"
    max_repair_attempts: int = 3
    determinism_runs: int = 3
    # Cap on a file's transitive local-import dependency closure for
    # verification sandboxing (dependencies.py) - never silently truncated
    # beyond this; a file whose closure exceeds it degrades to UNVERIFIED
    # with a clear reason instead.
    max_dependency_closure_files: int = 20
    # Off by default (opt-in): 0 means Mode C keeps using today's LLM-picked
    # single-example CharacterizationTestPlan path unchanged. A positive
    # value switches to the differential-fuzzing seed-pool path instead
    # (propose_fuzz_seeds + expand_function_seeds), targeting roughly this
    # many executed cases per function - see fuzz_generation.py's own
    # MAX_GENERATED_CASES_HARD_CAP for the absolute ceiling regardless of
    # this value.
    characterization_fuzz_cases: int = 0
    # Off by default (opt-in): when True, run_migration appends every file
    # that reached VERIFIED/VERIFIED_INFERRED with a real Auditor-diagnosed
    # repair to repair_history_path (pipeline/repair_history.py) - the raw
    # material `suggest-fixer-rules` later drafts candidate permanent
    # detectors from. Pure serialization, zero LLM/Docker cost either way.
    capture_repair_history: bool = False
    repair_history_path: str = ".shiftcode/repair_history.jsonl"

    def llm_for(self, role: str) -> LLMConfig:
        return self.agent_overrides.get(role, self.llm)


def _llm_config_from_dict(base: LLMConfig, raw: dict) -> LLMConfig:
    fields = {}
    if "base_url" in raw:
        fields["base_url"] = raw["base_url"]
    if "api_key" in raw:
        fields["api_key"] = raw["api_key"]
    if "model" in raw:
        fields["model"] = raw["model"]
    if "temperature" in raw:
        fields["temperature"] = float(raw["temperature"])
    if "timeout" in raw:
        fields["timeout"] = float(raw["timeout"])
    if "max_retries" in raw:
        fields["max_retries"] = int(raw["max_retries"])
    if "supports_structured_outputs" in raw:
        fields["supports_structured_outputs"] = bool(raw["supports_structured_outputs"])
    return replace(base, **fields)


def _find_pyproject(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _load_pyproject_table(project_root: Path | None) -> dict:
    path = _find_pyproject(project_root or Path.cwd())
    if path is None:
        return {}
    data = tomllib.loads(path.read_text())
    return data.get("tool", {}).get("shiftcode", {})


def _apply_env(llm: LLMConfig) -> LLMConfig:
    env_map = {
        "SHIFTCODE_LLM_BASE_URL": "base_url",
        "SHIFTCODE_LLM_API_KEY": "api_key",
        "SHIFTCODE_LLM_MODEL": "model",
        "SHIFTCODE_LLM_TEMPERATURE": "temperature",
    }
    raw = {}
    for env_name, field_name in env_map.items():
        value = os.environ.get(env_name)
        if value is not None:
            raw[field_name] = value
    return _llm_config_from_dict(llm, raw)


def load_config(
    *,
    project_root: Path | None = None,
    cli_base_url: str | None = None,
    cli_model: str | None = None,
    cli_api_key: str | None = None,
    cli_py2_interpreter: str | None = None,
    cli_max_repair_attempts: int | None = None,
    cli_determinism_runs: int | None = None,
    cli_characterization_fuzz_cases: int | None = None,
    cli_capture_repair_history: bool | None = None,
) -> ShiftConfig:
    """Resolve config with precedence: CLI args > env vars > pyproject.toml [tool.shiftcode] > defaults."""
    table = _load_pyproject_table(project_root)

    llm = LLMConfig()
    llm = _llm_config_from_dict(llm, table.get("llm", {}))
    llm = _apply_env(llm)
    cli_overrides = {}
    if cli_base_url is not None:
        cli_overrides["base_url"] = cli_base_url
    if cli_model is not None:
        cli_overrides["model"] = cli_model
    if cli_api_key is not None:
        cli_overrides["api_key"] = cli_api_key
    llm = _llm_config_from_dict(llm, cli_overrides)

    agents_table = table.get("agents", {})
    agent_overrides: dict[str, LLMConfig] = {}
    for role in AGENT_ROLES:
        role_table = agents_table.get(role)
        if role_table:
            agent_overrides[role] = _llm_config_from_dict(llm, role_table)

    py2_interpreter = cli_py2_interpreter or os.environ.get("SHIFTCODE_PY2_INTERPRETER") or table.get("py2_interpreter")
    py2_docker_image = table.get("py2_docker_image", "shiftcode-py2-sandbox")
    py3_docker_image = table.get("py3_docker_image", "shiftcode-py3-sandbox")
    install_project_dependencies = table.get("install_project_dependencies", True)
    sandbox_memory_limit = table.get("sandbox_memory_limit", "256m")
    sandbox_cpu_limit = table.get("sandbox_cpu_limit", "1")
    max_repair_attempts = cli_max_repair_attempts or table.get("max_repair_attempts", 3)
    determinism_runs = cli_determinism_runs or table.get("determinism_runs", 3)
    max_dependency_closure_files = table.get("max_dependency_closure_files", 20)
    characterization_fuzz_cases = (
        cli_characterization_fuzz_cases
        if cli_characterization_fuzz_cases is not None
        else table.get("characterization_fuzz_cases", 0)
    )
    capture_repair_history = (
        cli_capture_repair_history
        if cli_capture_repair_history is not None
        else table.get("capture_repair_history", False)
    )
    repair_history_path = table.get("repair_history_path", ".shiftcode/repair_history.jsonl")

    return ShiftConfig(
        llm=llm,
        agent_overrides=agent_overrides,
        py2_interpreter=py2_interpreter,
        py2_docker_image=py2_docker_image,
        py3_docker_image=py3_docker_image,
        install_project_dependencies=install_project_dependencies,
        sandbox_memory_limit=sandbox_memory_limit,
        sandbox_cpu_limit=sandbox_cpu_limit,
        max_repair_attempts=max_repair_attempts,
        determinism_runs=determinism_runs,
        max_dependency_closure_files=max_dependency_closure_files,
        characterization_fuzz_cases=characterization_fuzz_cases,
        capture_repair_history=capture_repair_history,
        repair_history_path=repair_history_path,
    )
