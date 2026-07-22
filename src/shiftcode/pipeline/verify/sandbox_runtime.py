import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from shiftcode.config import ShiftConfig
from shiftcode.pipeline.dependencies import ClosureFile


@dataclass
class SandboxRuntime:
    """A resolved interpreter (py2 or py3) to execute migrated/legacy code
    against, for verification. Docker invocations run isolated: --rm (ephemeral,
    nothing persists), --network none (no legitimate reason a correctness check
    needs network access - this is the main defense against a guessed/malicious
    input doing something that reaches outside the sandbox), plus memory/CPU
    limits (guards against a hang or resource-exhaustion from a bad input).
    "local" kind runs directly on the host with no such isolation - only used
    where that's an accepted, bounded risk (see resolve_execution_runtimes)."""

    available: bool
    kind: str  # "local" | "docker" | "unavailable"
    interpreter_path: str | None = None
    docker_image: str | None = None
    memory_limit: str = "256m"
    cpu_limit: str = "1"
    reason: str | None = None
    # Set by dependency_provisioning.py when a project's requirements.txt was
    # installed into a Docker volume ahead of time - mounted read-only into
    # every execution container alongside PYTHONPATH, so --network none stays
    # intact on the containers that actually run migrated/legacy code (the
    # install itself happened earlier, in a separate, network-enabled,
    # constrained container - see dependency_provisioning.py).
    deps_volume: str | None = None
    deps_mount_path: str = "/deps"

    def _base_cmd(self, cwd: Path) -> list[str]:
        if self.kind == "local":
            return [self.interpreter_path]
        if self.kind == "docker":
            cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", self.memory_limit,
                "--cpus", self.cpu_limit,
                "-v", f"{cwd}:/work", "-w", "/work",
            ]
            if self.deps_volume:
                cmd += ["-v", f"{self.deps_volume}:{self.deps_mount_path}:ro", "-e", f"PYTHONPATH={self.deps_mount_path}"]
            cmd += [self.docker_image, "python"]
            return cmd
        raise RuntimeError("sandbox runtime not available")

    def run_pytest(
        self, cwd: Path, test_filename: str, *, timeout: float = 30
    ) -> tuple[subprocess.CompletedProcess, str]:
        """pytest natively discovers and runs both unittest.TestCase and bare
        `assert`-function test suites through one code path (see
        docs/bug-log.md #5) - unlike `python -m unittest`, which silently
        finds nothing for the latter. --junit-xml gives structured, stable
        per-test results instead of parsing interpreter-version-dependent
        verbose text (docs/bug-log.md #2, #4). Requires pytest to be
        installed in the sandbox - ShiftCode's own sandbox images bake it in
        (docker/*-sandbox.Dockerfile)."""
        xml_name = "_shiftcode_pytest_results.xml"
        cmd = [*self._base_cmd(cwd), "-m", "pytest", "-q", f"--junit-xml={xml_name}", test_filename]
        run_cwd = None if self.kind == "docker" else cwd
        proc = subprocess.run(cmd, cwd=run_cwd, capture_output=True, text=True, timeout=timeout)
        xml_path = cwd / xml_name
        xml_content = xml_path.read_text() if xml_path.is_file() else ""
        return proc, xml_content

    def run_script(self, cwd: Path, script_rel_path: Path, *, timeout: float = 30) -> subprocess.CompletedProcess:
        """`cwd` is the real sandbox root (mounted whole into Docker), `script_rel_path`
        is the script's path relative to it - NOT necessarily its immediate parent
        directory. Deriving cwd from the script's own parent (the old behavior)
        silently broke any sibling-import closure living outside that one
        subdirectory - mounting `cwd/mypkg` instead of all of `cwd` hides everything
        else in the closure from the container. Matches run_pytest's existing
        (already-correct) calling convention."""
        if self.kind == "docker":
            cmd = [*self._base_cmd(cwd), str(script_rel_path)]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        cmd = [*self._base_cmd(cwd), str(cwd / script_rel_path)]
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


@dataclass
class ExecutionRuntimes:
    """Bundles both interpreter sides with the resolution/fallback policy baked
    in: py2 is unchanged from the original design (local -> docker -> none).
    py3 differs by how the output will be used - Mode A/B run human-authored
    tests/scripts (lower marginal risk), so they fall back to local execution
    if Docker is unavailable, preserving today's availability. Mode C runs
    LLM-guessed inputs against arbitrary functions - meaningfully higher risk -
    so it gets no local fallback: unavailable Docker means Mode C is skipped
    entirely for the run rather than ever executing guessed inputs unsandboxed."""

    py2: SandboxRuntime
    py3_for_ab: SandboxRuntime
    py3_for_c: SandboxRuntime


def _docker_daemon_reachable() -> bool:
    docker_path = shutil.which("docker")
    if not docker_path:
        return False
    try:
        result = subprocess.run([docker_path, "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ShiftCode's own sandbox images (docker/*-sandbox.Dockerfile - bare
# python:2.7/python:3-slim plus pytest). Auto-built the first time one is
# needed and not already present locally, so this "just works" without a
# separate manual step; custom/user-configured image names are left alone -
# if missing, the later `docker run` fails with Docker's own clear error
# rather than something silently substituted.
_KNOWN_SANDBOX_DOCKERFILES = {
    "shiftcode-py2-sandbox": "py2-sandbox.Dockerfile",
    "shiftcode-py3-sandbox": "py3-sandbox.Dockerfile",
}


def _image_exists_locally(image: str) -> bool:
    try:
        result = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=10)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ensure_sandbox_image(image: str) -> None:
    if image not in _KNOWN_SANDBOX_DOCKERFILES or _image_exists_locally(image):
        return
    repo_root = Path(__file__).resolve().parents[4]
    dockerfile = repo_root / "docker" / _KNOWN_SANDBOX_DOCKERFILES[image]
    if not dockerfile.is_file():
        return  # not a dev checkout with docker/ present - let `docker run` fail normally
    subprocess.run(
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(repo_root)],
        capture_output=True,
        timeout=600,
    )


def resolve_py2_runtime(config: ShiftConfig) -> SandboxRuntime:
    """Preflight check, run once: config path -> PATH auto-detect -> Docker fallback."""
    if config.py2_interpreter:
        path = Path(config.py2_interpreter)
        if path.is_file():
            return SandboxRuntime(available=True, kind="local", interpreter_path=str(path))
        return SandboxRuntime(
            available=False,
            kind="unavailable",
            reason=f"configured py2_interpreter {config.py2_interpreter!r} does not exist",
        )

    for name in ("python2", "python2.7"):
        found = shutil.which(name)
        if found:
            return SandboxRuntime(available=True, kind="local", interpreter_path=found)

    if _docker_daemon_reachable():
        _ensure_sandbox_image(config.py2_docker_image)
        return SandboxRuntime(
            available=True,
            kind="docker",
            docker_image=config.py2_docker_image,
            memory_limit=config.sandbox_memory_limit,
            cpu_limit=config.sandbox_cpu_limit,
        )

    return SandboxRuntime(
        available=False,
        kind="unavailable",
        reason="no python2/python2.7 on PATH, no configured interpreter, and Docker daemon unreachable",
    )


def _local_py3_runtime() -> SandboxRuntime:
    return SandboxRuntime(available=True, kind="local", interpreter_path=sys.executable)


def resolve_py3_sandbox(config: ShiftConfig) -> SandboxRuntime:
    """Docker-only py3 resolution (no local fallback baked in here - callers
    decide whether to fall back, per resolve_execution_runtimes's policy)."""
    if _docker_daemon_reachable():
        _ensure_sandbox_image(config.py3_docker_image)
        return SandboxRuntime(
            available=True,
            kind="docker",
            docker_image=config.py3_docker_image,
            memory_limit=config.sandbox_memory_limit,
            cpu_limit=config.sandbox_cpu_limit,
        )
    return SandboxRuntime(
        available=False,
        kind="unavailable",
        reason="Docker daemon unreachable, no py3 sandbox available",
    )


def resolve_execution_runtimes(config: ShiftConfig) -> ExecutionRuntimes:
    """Single preflight resolving all three runtimes with the fallback policy
    applied. Call once at pipeline startup, same pattern as the original
    py2-only preflight."""
    py2 = resolve_py2_runtime(config)
    py3_sandbox = resolve_py3_sandbox(config)

    py3_for_ab = py3_sandbox if py3_sandbox.available else _local_py3_runtime()
    py3_for_c = py3_sandbox  # no local fallback - unavailable means Mode C is skipped

    return ExecutionRuntimes(py2=py2, py3_for_ab=py3_for_ab, py3_for_c=py3_for_c)


def write_sandbox_tree(
    base_dir: Path,
    module_rel_path: Path,
    module_source: str,
    closure: list[ClosureFile],
    *,
    side: str,
) -> None:
    """Writes the module under test at its REAL relative path (not just its
    basename) plus every dependency in its closure at ITS real relative
    path, preserving package structure - so `from mypkg import helpers`-
    style sibling/package imports resolve exactly as they would in the real
    project instead of failing identically on both interpreters (see
    docs/bug-log.md #12, #13). Shared by Mode A/B/C and determinism checks,
    all of which write into a Docker-mounted (or local) working directory -
    the mount is already recursive, no sandbox_runtime changes needed beyond
    this helper. `side` selects which of a ClosureFile's two sources to
    write: "py2" for the untouched original, "py3" for its best-available
    candidate. Files with an empty closure behave byte-for-byte identically
    to a flat single-file write - this is purely additive."""
    target = base_dir / module_rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source)
    for dep in closure:
        dep_target = base_dir / dep.rel_path
        dep_target.parent.mkdir(parents=True, exist_ok=True)
        dep_target.write_text(dep.source_py2 if side == "py2" else dep.source_py3)
