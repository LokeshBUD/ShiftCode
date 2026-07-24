# ShiftCode recorder - a standalone helper for capturing real function calls
# from your OWN Python 2 code, in your OWN environment, so ShiftCode can
# later replay those exact real inputs against a migrated candidate offline
# (Mode R / VERIFIED_RECORDED). This file is copied verbatim into your
# project by `shiftcode init-recorder` - it has ZERO dependency on the
# shiftcode package itself (stdlib only), so it works standing alone inside
# a Python 2 codebase that doesn't have shiftcode installed at all.
#
# Usage:
#     from shiftcode_record import record
#
#     @record
#     def some_function(a, b):
#         return a + b
#
#     @record(max_entries=50)
#     def another_function(x):
#         return x * 2
#
# Run your code normally (your own tests, your own manual usage, whatever
# already exercises these functions with real inputs). Recorded calls get
# appended to .shiftcode/recordings/<function_name>.jsonl - copy that
# directory to wherever you run `shiftcode migrate --recordings-dir ...`.
#
# Deliberately conservative: never lets recording break the function it
# wraps. The real call always happens and its real result/exception is
# always returned/raised, regardless of whether recording succeeds. Only
# calls whose args/kwargs/result round-trip losslessly through
# repr()/ast.literal_eval get captured - anything else (custom objects,
# file handles, etc.) is silently skipped, not an error.

import ast
import functools
import json
import os
import time

DEFAULT_OUT_DIR = os.environ.get("SHIFTCODE_RECORD_DIR", ".shiftcode/recordings")
DEFAULT_MAX_ENTRIES = 200

_counts = {}


def _safe_repr(value):
    """repr(), pre-validated by round-tripping through ast.literal_eval -
    the same check recording_loader.py does again at load time (a
    recording file is a separate, later-trusted-less artifact by the time
    it's loaded, so that check is never skipped just because this one
    passed). Using repr() rather than raw JSON values here is deliberate,
    found via a real stress test: json.dumps silently coerces ALL dict keys
    to strings (`{1: 'one'}` on the wire becomes `{"1": "one"}`) and
    collapses the tuple/list distinction - both would cause false
    mismatches at replay time that have nothing to do with any real
    behavior difference. repr()/literal_eval round-trips losslessly for
    anything in the literal-safe universe instead. Returns None (skip this
    value entirely) for anything that doesn't round-trip - a custom object,
    a file handle, etc.; also None for a genuinely broken __repr__."""
    try:
        text = repr(value)
        ast.literal_eval(text)
        return text
    except Exception:
        return None


def record(func=None, max_entries=DEFAULT_MAX_ENTRIES, out_dir=None):
    """Decorator. Usable bare (`@record`) or called (`@record(max_entries=50)`)."""

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                result = f(*args, **kwargs)
            except Exception as exc:
                _try_record(f, args, kwargs, max_entries, out_dir, exception=type(exc).__name__)
                raise
            _try_record(f, args, kwargs, max_entries, out_dir, result=result)
            return result

        return wrapper

    if func is not None:
        # bare @record form - func IS the function being decorated
        return decorator(func)
    return decorator


def _try_record(func, args, kwargs, max_entries, out_dir, result=None, exception=None):
    try:
        name = getattr(func, "__name__", "unknown")
        count = _counts.get(name, 0)
        if count >= max_entries:
            return

        args_repr = _safe_repr(tuple(args))
        if args_repr is None:
            return  # can't safely/losslessly represent this call at all

        kwargs_repr = _safe_repr(kwargs) if kwargs else None
        if kwargs and kwargs_repr is None:
            return

        result_repr = None
        if exception is None:
            result_repr = _safe_repr(result)
            if result_repr is None:
                return

        entry = {
            "function": name,
            "module": getattr(func, "__module__", None),
            "args_repr": args_repr,
            "kwargs_repr": kwargs_repr,
            "result_repr": result_repr,
            "exception": exception,
            "timestamp": time.time(),
        }
        # Every value above is already a plain string (repr() output) or
        # None/a string - json.dumps of the wrapping structure can't fail
        # at this point the way it could when raw objects were stored
        # directly (the reason this is still wrapped in try/except: a
        # pathological custom __repr__ could itself return a non-string,
        # or getattr(func, "__module__", None) could theoretically be
        # something odd - belt and suspenders, not the primary defense
        # anymore).
        line = json.dumps(entry)
    except Exception:
        return

    try:
        target_dir = out_dir or DEFAULT_OUT_DIR
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir)
        path = os.path.join(target_dir, name + ".jsonl")
        with open(path, "a") as fh:
            fh.write(line + "\n")
        _counts[name] = count + 1
    except Exception:
        # Never let a filesystem problem (permissions, disk full, read-only
        # deploy environment, ...) break the real function this wraps.
        return
