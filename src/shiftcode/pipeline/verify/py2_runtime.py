"""Backward-compatible re-export: the Docker-execution logic here was
generalized into sandbox_runtime.py to be shared by both interpreter sides
(py2 and py3). Py2Runtime is now just an alias for the shared SandboxRuntime
class; existing imports of Py2Runtime/resolve_py2_runtime keep working
unchanged."""

from shiftcode.pipeline.verify.sandbox_runtime import (
    SandboxRuntime as Py2Runtime,
)
from shiftcode.pipeline.verify.sandbox_runtime import resolve_py2_runtime

__all__ = ["Py2Runtime", "resolve_py2_runtime"]
