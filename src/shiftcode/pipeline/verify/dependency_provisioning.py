import subprocess
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from shiftcode.pipeline.verify.sandbox_runtime import SandboxRuntime

REQUIREMENTS_FILENAME = "requirements.txt"
DEFAULT_INSTALL_TIMEOUT = 180.0


@dataclass
class ProvisioningResult:
    runtime: SandboxRuntime
    installed: bool
    packages: list[str] = field(default_factory=list)
    warning: str | None = None


def find_requirements_file(project_root: Path) -> Path | None:
    """MVP scope: requirements.txt only (the most common manifest for a
    project old enough to still be on Python 2). setup.py install_requires /
    pyproject.toml are real gaps, not yet handled."""
    candidate = project_root / REQUIREMENTS_FILENAME
    return candidate if candidate.is_file() else None


def _read_package_names(requirements_file: Path) -> list[str]:
    """Just for the transparency report - the actual install uses the file
    directly via `pip install -r`, this doesn't drive install behavior."""
    names = []
    for line in requirements_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        name = stripped.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("[")[0].strip()
        if name:
            names.append(name)
    return names


def provision_dependencies(
    runtime: SandboxRuntime,
    requirements_file: Path,
    *,
    timeout: float = DEFAULT_INSTALL_TIMEOUT,
) -> ProvisioningResult:
    """Installs a project's own declared dependencies into a Docker volume,
    via one constrained, network-enabled container that runs nothing but
    `pip install` against the project's own requirements.txt - never
    arbitrary code, never anything derived from LLM output. Every execution
    container afterward mounts the resulting volume read-only and keeps
    --network none, exactly as before (see SandboxRuntime.deps_volume). Same
    trust level as a developer running `pip install -r requirements.txt` by
    hand on code they've already decided to migrate - meaningfully narrower
    than Mode C's "run guessed inputs" risk."""
    if runtime.kind != "docker":
        return ProvisioningResult(
            runtime=runtime, installed=False, warning="dependency provisioning requires a Docker sandbox"
        )

    packages = _read_package_names(requirements_file)
    if not packages:
        return ProvisioningResult(
            runtime=runtime, installed=False, warning="requirements.txt has no installable packages"
        )

    volume = f"shiftcode-deps-{uuid.uuid4().hex[:12]}"
    create = subprocess.run(["docker", "volume", "create", volume], capture_output=True, timeout=30)
    if create.returncode != 0:
        return ProvisioningResult(
            runtime=runtime,
            installed=False,
            warning=f"could not create Docker volume: {create.stderr.decode(errors='replace')}",
        )

    install = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{volume}:/deps",
            "-v", f"{requirements_file}:/proj/requirements.txt:ro",
            runtime.docker_image,
            "pip", "install", "--target", "/deps", "--no-cache-dir",
            "-r", "/proj/requirements.txt",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if install.returncode != 0:
        subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True, timeout=30)
        return ProvisioningResult(
            runtime=runtime,
            installed=False,
            warning=f"pip install failed (sandbox stays dependency-free for this run): {install.stderr[-500:]}",
        )

    provisioned = replace(runtime, deps_volume=volume)
    return ProvisioningResult(runtime=provisioned, installed=True, packages=packages)


def cleanup_dependency_volume(runtime: SandboxRuntime) -> None:
    if runtime.deps_volume:
        subprocess.run(["docker", "volume", "rm", "-f", runtime.deps_volume], capture_output=True, timeout=30)
