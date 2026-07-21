import ast
import py_compile
import tempfile
from pathlib import Path

from shiftcode.models import SyntaxResult


def check_syntax(source: str) -> SyntaxResult:
    """Hard gate: source must be valid Python 3. ast.parse catches SyntaxError
    cheaply; py_compile is a second, stricter pass (catches some things ast.parse
    alone doesn't, e.g. bytecode-compile-time issues)."""
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return SyntaxResult(
            passed=False,
            error_message=str(exc.msg),
            error_line=exc.lineno,
            error_offset=exc.offset,
        )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candidate.py"
        path.write_text(source)
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            error = exc.exc_value
            return SyntaxResult(
                passed=False,
                error_message=str(getattr(error, "msg", error)),
                error_line=getattr(error, "lineno", None),
                error_offset=getattr(error, "offset", None),
            )

    return SyntaxResult(passed=True)
