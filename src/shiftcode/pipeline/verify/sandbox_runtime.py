import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from shiftcode.config import ShiftConfig


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

    def _base_cmd(self, cwd: Path) -> list[str]:
        if self.kind == "local":
            return [self.interpreter_path]
        if self.kind == "docker":
            return [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", self.memory_limit,
                "--cpus", self.cpu_limit,
                "-v", f"{cwd}:/work", "-w", "/work",
                self.docker_image, "python",
            ]
        raise RuntimeError("sandbox runtime not available")

    def run_unittest(
        self, cwd: Path, test_module: str, *, timeout: float = 30
    ) -> subprocess.CompletedProcess:
        cmd = [*self._base_cmd(cwd), "-m", "unittest", "-v", test_module]
        run_cwd = None if self.kind == "docker" else cwd
        return subprocess.run(cmd, cwd=run_cwd, capture_output=True, text=True, timeout=timeout)

    def run_script(self, script_path: Path, *, timeout: float = 30) -> subprocess.CompletedProcess:
        cwd = script_path.parent
        if self.kind == "docker":
            cmd = [*self._base_cmd(cwd), script_path.name]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        cmd = [*self._base_cmd(cwd), str(script_path)]
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
