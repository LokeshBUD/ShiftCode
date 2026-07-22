import fnmatch
from pathlib import Path

from shiftcode.models import FileUnit, Status

DEFAULT_EXCLUDES = (
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "*.egg-info",
    "build",
    "dist",
)

DEFAULT_MAX_FILE_BYTES = 200_000


def _is_excluded(path: Path, root: Path, excludes: tuple[str, ...]) -> bool:
    rel_parts = path.relative_to(root).parts
    for part in rel_parts:
        for pattern in excludes:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def ingest(
    root: Path,
    *,
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[FileUnit]:
    """Walk `root`, collecting *.py files into FileUnits. Files over max_file_bytes
    are still returned but pre-flagged NEEDS_REVIEW rather than processed, so a
    single oversized file can't blow up repair-loop cost silently."""
    if root.is_file():
        candidates = [root] if root.suffix == ".py" else []
    else:
        candidates = sorted(
            p for p in root.rglob("*.py") if not _is_excluded(p, root, excludes)
        )

    units = []
    for path in candidates:
        size = path.stat().st_size
        source = path.read_text(errors="replace")
        if source and not source.endswith("\n"):
            # A missing trailing newline is semantically inert - Python runs
            # the script identically either way - but lib2to3's tokenizer
            # genuinely can't parse it at all (real, confirmed case:
            # `requests/__init__.py`, docs/bug-log.md #18's stress-test
            # discovery), raising a raw parse error before ANY findings,
            # transform, or verification can even start. Normalized once
            # here rather than patched around in every downstream consumer.
            source += "\n"
        unit = FileUnit(path=path, original_source=source)
        if size > max_file_bytes:
            unit.status = Status.NEEDS_REVIEW
            unit.reason = f"file exceeds {max_file_bytes}-byte MVP size ceiling ({size} bytes)"
        units.append(unit)
    return units
