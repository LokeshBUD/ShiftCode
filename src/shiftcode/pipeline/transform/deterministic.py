from shiftcode.vendor.lib2to3.refactor import RefactoringTool, get_fixers_from_package

FIXER_NAMES = get_fixers_from_package("shiftcode.vendor.lib2to3.fixes")


def make_refactoring_tool() -> RefactoringTool:
    return RefactoringTool(FIXER_NAMES)


class DeterministicTransformError(Exception):
    """Raised when the vendored lib2to3 can't even parse the source (a real
    SyntaxError, not something a fixer can resolve)."""


def deterministic_transform(source: str) -> str:
    """Zero-LLM mechanical pass: run every lib2to3 fixer over the source. Handles
    the bulk of py2->py3 syntax rewrites (print statement, xrange, dict.iteritems,
    except E, e: etc). Anything lib2to3 has no fixer for (e.g. ambiguous division)
    passes through unchanged and becomes a needs_llm finding downstream."""
    rt = make_refactoring_tool()
    try:
        tree = rt.refactor_string(source, "<deterministic-transform>")
    except Exception as exc:
        # RefactoringTool.log_error's base implementation is just `raise` (it's
        # meant to be overridden by subclasses) - so a parse failure inside
        # refactor_string propagates here rather than returning None.
        raise DeterministicTransformError(f"lib2to3 could not parse source: {exc}") from exc
    if tree is None:
        raise DeterministicTransformError(f"lib2to3 could not parse source: {source[:200]!r}")
    return str(tree)
