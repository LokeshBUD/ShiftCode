"""_provision_project_dependencies (orchestrator.py): the preflight that
installs a project's own requirements.txt into the py2/py3 sandbox volumes
before verification runs (docs/bug-log.md #5's fix). Exercised here with a
fake provision_dependencies so no real Docker/pip is needed - the real
end-to-end behavior is confirmed separately via the stress-test log."""

from dataclasses import replace

from shiftcode.pipeline.orchestrator import _provision_project_dependencies
from shiftcode.pipeline.verify.dependency_provisioning import ProvisioningResult
from shiftcode.pipeline.verify.sandbox_runtime import ExecutionRuntimes, SandboxRuntime


def _docker_runtime(image: str) -> SandboxRuntime:
    return SandboxRuntime(available=True, kind="docker", docker_image=image)


def test_no_requirements_file_is_a_silent_noop(tmp_path):
    runtimes = ExecutionRuntimes(
        py2=_docker_runtime("shiftcode-py2-sandbox"),
        py3_for_ab=_docker_runtime("shiftcode-py3-sandbox"),
        py3_for_c=_docker_runtime("shiftcode-py3-sandbox"),
    )

    summary = _provision_project_dependencies(tmp_path, runtimes)

    assert summary is None


def test_provisions_py2_and_py3_and_shares_result_with_py3_for_c(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("six==1.16.0\n")
    py3_shared = _docker_runtime("shiftcode-py3-sandbox")
    runtimes = ExecutionRuntimes(py2=_docker_runtime("shiftcode-py2-sandbox"), py3_for_ab=py3_shared, py3_for_c=py3_shared)

    def fake_provision(runtime, requirements_file, *, timeout=180.0):
        provisioned = replace(runtime, deps_volume=f"vol-{runtime.docker_image}")
        return ProvisioningResult(runtime=provisioned, installed=True, packages=["six"])

    monkeypatch.setattr("shiftcode.pipeline.orchestrator.provision_dependencies", fake_provision)

    summary = _provision_project_dependencies(tmp_path, runtimes)

    assert runtimes.py2.deps_volume == "vol-shiftcode-py2-sandbox"
    assert runtimes.py3_for_ab.deps_volume == "vol-shiftcode-py3-sandbox"
    assert runtimes.py3_for_c.deps_volume == "vol-shiftcode-py3-sandbox"
    assert "py2 sandbox: installed six" in summary
    assert "py3 sandbox: installed six" in summary


def test_does_not_provision_py3_for_c_separately_when_it_diverged_from_py3_for_ab(tmp_path, monkeypatch):
    """py3_for_c only shares identity with py3_for_ab when Docker was available
    at resolve time (see resolve_execution_runtimes). If py3_for_ab fell back
    to local execution, py3_for_c stays whatever it independently resolved to
    - must not be silently overwritten with the (irrelevant) py3_for_ab result."""
    local_py3 = SandboxRuntime(available=True, kind="local", interpreter_path="python3")
    unavailable_py3_for_c = SandboxRuntime(available=False, kind="unavailable", reason="no docker")
    runtimes = ExecutionRuntimes(py2=_docker_runtime("shiftcode-py2-sandbox"), py3_for_ab=local_py3, py3_for_c=unavailable_py3_for_c)
    (tmp_path / "requirements.txt").write_text("six==1.16.0\n")

    def fake_provision(runtime, requirements_file, *, timeout=180.0):
        if runtime.kind != "docker":
            return ProvisioningResult(runtime=runtime, installed=False, warning="dependency provisioning requires a Docker sandbox")
        return ProvisioningResult(runtime=replace(runtime, deps_volume="vol"), installed=True, packages=["six"])

    monkeypatch.setattr("shiftcode.pipeline.orchestrator.provision_dependencies", fake_provision)

    _provision_project_dependencies(tmp_path, runtimes)

    assert runtimes.py3_for_c is unavailable_py3_for_c
