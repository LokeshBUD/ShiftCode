import json
import re
from dataclasses import dataclass
from pathlib import Path

from shiftcode.pipeline.verify.fuzz_generation import (
    UnsafeTestCaseError,
    validate_args_literal,
    validate_seed_literal,
)

# Sanity ceiling regardless of what a recording file claims - same posture
# as MAX_GENERATED_CASES_HARD_CAP/DEFAULT_MAX_CLOSURE_FILES: a real ceiling,
# never silently truncated beyond it, protects against a misconfigured or
# runaway recording (e.g. max_entries left unset on a hot path for weeks).
MAX_RECORDED_CASES_PER_FUNCTION = 200

# A recording file is an external input (copied in from wherever the user's
# own py2 process ran, possibly a different machine entirely) - same
# zero-trust posture as LLM output applies to its `function` field too, not
# just the args/result literals. Splicing an unvalidated function name
# directly into a driver script as source code (characterization_gate.py's
# _build_driver_script) would otherwise be a real injection surface.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class RecordedCase:
    function_name: str
    args_literal: str
    expected_result_literal: str | None = None
    expected_exception: str | None = None
    module: str | None = None


def _entry_to_case(entry: dict) -> RecordedCase | None:
    function_name = entry.get("function")
    if not isinstance(function_name, str) or not _IDENTIFIER_RE.match(function_name):
        return None

    # v1 scope: positional-only, matching TestCase.args_literal's own
    # positional-only contract - no established literal representation for
    # keyword args exists anywhere else in this codebase yet. A recorded
    # call that used kwargs is dropped, not guessed at.
    if entry.get("kwargs_repr"):
        return None

    # args_repr/result_repr are already repr() output written by
    # recorder.py (real bug found via a real stress test against
    # `pytoolz/toolz`'s `merge()`: storing raw JSON values instead - as an
    # earlier version of both this loader and the recorder did - silently
    # corrupted non-string dict keys, since JSON coerces every dict key to
    # a string on the wire, and collapsed the tuple/list distinction. Using
    # repr() end to end avoids both losslessly). Still re-validated here,
    # not trusted just because the recorder already checked - a recording
    # file is a separate, later-trusted-less artifact by the time it's
    # loaded, same zero-trust posture as everywhere else in this codebase.
    args_literal = entry.get("args_repr")
    if not isinstance(args_literal, str):
        return None
    try:
        validate_args_literal(args_literal)
    except UnsafeTestCaseError:
        return None

    exception = entry.get("exception")
    if exception is not None:
        if not isinstance(exception, str):
            return None
        return RecordedCase(
            function_name=function_name,
            args_literal=args_literal,
            expected_exception=exception,
            module=entry.get("module"),
        )

    result_literal = entry.get("result_repr")
    if not isinstance(result_literal, str):
        return None
    try:
        validate_seed_literal(result_literal)
    except UnsafeTestCaseError:
        return None
    return RecordedCase(
        function_name=function_name,
        args_literal=args_literal,
        expected_result_literal=result_literal,
        module=entry.get("module"),
    )


def load_recordings(recordings_dir: Path) -> dict[str, list[RecordedCase]]:
    """Reads every *.jsonl file in recordings_dir (the shape `recorder.py`
    writes), keyed by function_name. A recording file is an external input,
    same zero-trust posture as any LLM output: malformed/unsafe entries are
    dropped individually (via `_entry_to_case` returning None), never
    failing the whole file. Bounded per function - never silently
    unbounded, same philosophy as every other resource cap in this
    codebase."""
    cases: dict[str, list[RecordedCase]] = {}
    if not recordings_dir.is_dir():
        return cases

    for path in sorted(recordings_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            case = _entry_to_case(entry)
            if case is None:
                continue
            bucket = cases.setdefault(case.function_name, [])
            if len(bucket) >= MAX_RECORDED_CASES_PER_FUNCTION:
                continue
            bucket.append(case)

    return cases
