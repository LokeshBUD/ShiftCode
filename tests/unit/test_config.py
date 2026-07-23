from shiftcode.config import load_config


def test_defaults(tmp_path):
    cfg = load_config(project_root=tmp_path)
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.llm.base_url is None
    assert cfg.characterization_fuzz_cases == 0  # off by default - additive/opt-in feature
    assert cfg.capture_repair_history is False
    assert cfg.repair_history_path == ".shiftcode/repair_history.jsonl"
    assert cfg.recordings_dir is None


def test_env_overrides_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIFTCODE_LLM_MODEL", "llama3")
    monkeypatch.setenv("SHIFTCODE_LLM_BASE_URL", "http://localhost:11434/v1")
    cfg = load_config(project_root=tmp_path)
    assert cfg.llm.model == "llama3"
    assert cfg.llm.base_url == "http://localhost:11434/v1"


def test_cli_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIFTCODE_LLM_MODEL", "llama3")
    cfg = load_config(project_root=tmp_path, cli_model="gpt-4o")
    assert cfg.llm.model == "gpt-4o"


def test_pyproject_table_and_per_agent_overrides(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.shiftcode]
py2_interpreter = "/usr/bin/python2"
max_repair_attempts = 5

[tool.shiftcode.llm]
model = "shared-model"
base_url = "http://shared:8000/v1"

[tool.shiftcode.agents.planner]
model = "flagship-model"

[tool.shiftcode.agents.refactorer]
model = "cheap-model"
base_url = "http://cheap:8000/v1"
"""
    )

    cfg = load_config(project_root=tmp_path)

    assert cfg.llm.model == "shared-model"
    assert cfg.llm.base_url == "http://shared:8000/v1"
    assert cfg.llm_for("planner").model == "flagship-model"
    assert cfg.llm_for("planner").base_url == "http://shared:8000/v1"  # inherited
    assert cfg.llm_for("refactorer").model == "cheap-model"
    assert cfg.llm_for("refactorer").base_url == "http://cheap:8000/v1"
    assert cfg.llm_for("auditor") is cfg.llm  # no override configured, falls through
    assert cfg.py2_interpreter == "/usr/bin/python2"
    assert cfg.max_repair_attempts == 5


def test_characterization_fuzz_cases_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.shiftcode]
characterization_fuzz_cases = 50
"""
    )
    cfg = load_config(project_root=tmp_path)
    assert cfg.characterization_fuzz_cases == 50


def test_characterization_fuzz_cases_cli_overrides_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.shiftcode]
characterization_fuzz_cases = 50
"""
    )
    cfg = load_config(project_root=tmp_path, cli_characterization_fuzz_cases=0)
    assert cfg.characterization_fuzz_cases == 0  # explicit CLI 0 must not fall back to the pyproject value


def test_capture_repair_history_from_pyproject_and_cli_override(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.shiftcode]
capture_repair_history = true
repair_history_path = "custom/history.jsonl"
"""
    )
    cfg = load_config(project_root=tmp_path)
    assert cfg.capture_repair_history is True
    assert cfg.repair_history_path == "custom/history.jsonl"

    cfg_cli_off = load_config(project_root=tmp_path, cli_capture_repair_history=False)
    assert cfg_cli_off.capture_repair_history is False  # explicit CLI override wins over pyproject


def test_recordings_dir_from_pyproject_and_cli_override(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.shiftcode]
recordings_dir = "my_recordings"
"""
    )
    cfg = load_config(project_root=tmp_path)
    assert cfg.recordings_dir == "my_recordings"

    cfg_cli = load_config(project_root=tmp_path, cli_recordings_dir="other_recordings")
    assert cfg_cli.recordings_dir == "other_recordings"  # explicit CLI override wins over pyproject
