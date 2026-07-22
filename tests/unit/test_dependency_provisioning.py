from pathlib import Path

from shiftcode.pipeline.verify.dependency_provisioning import (
    find_requirements_file,
    provision_dependencies,
    _read_package_names,
)
from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime


def test_find_requirements_file_present(tmp_path):
    (tmp_path / "requirements.txt").write_text("six==1.16.0\n")
    assert find_requirements_file(tmp_path) == tmp_path / "requirements.txt"


def test_find_requirements_file_absent(tmp_path):
    assert find_requirements_file(tmp_path) is None


def test_read_package_names_strips_versions_and_comments(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# a comment\n"
        "six==1.16.0\n"
        "unidecode>=1.0,<2.0\n"
        "requests[security]>=2.0\n"
        "\n"
        "-e git+https://example.com/foo.git\n"
    )
    names = _read_package_names(req)
    assert names == ["six", "unidecode", "requests"]


def test_provision_dependencies_noop_for_non_docker_runtime(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("six==1.16.0\n")
    local_runtime = SandboxRuntime(available=True, kind="local", interpreter_path="python3")

    result = provision_dependencies(local_runtime, req)

    assert not result.installed
    assert "Docker" in result.warning
    assert result.runtime is local_runtime  # unchanged, no volume attached


def test_provision_dependencies_warns_on_empty_requirements(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("# nothing installable here\n\n-e git+https://example.com/foo.git\n")
    docker_runtime = SandboxRuntime(available=True, kind="docker", docker_image="shiftcode-py3-sandbox")

    result = provision_dependencies(docker_runtime, req)

    assert not result.installed
    assert result.runtime.deps_volume is None
