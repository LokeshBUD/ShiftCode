import ast

from shiftcode.models import CallSiteEvidence, FileUnit


def _literal_repr(node: ast.expr) -> str | None:
    """Return a Python literal repr for the node if it's fully literal, else None."""
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return repr(value)


def _call_args_repr(call: ast.Call) -> str:
    parts = []
    for arg in call.args:
        literal = _literal_repr(arg)
        parts.append(literal if literal is not None else "<non-literal>")
    for kw in call.keywords:
        if kw.arg is None:
            parts.append("<non-literal:**kwargs>")
            continue
        literal = _literal_repr(kw.value)
        parts.append(f"{kw.arg}={literal if literal is not None else '<non-literal>'}")
    return "(" + ", ".join(parts) + ")"


def _call_func_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        # heuristic: match on the final attribute name (e.g. calculator.divide(...)
        # or obj.divide(...)) - no real import-resolution graph, same stated
        # limits as the existing DependencySlice approach in analyze.py.
        return func.attr
    return None


def top_level_symbol_names(source: str) -> set[str]:
    """Public (non-underscore-prefixed) top-level function/class names - the
    candidates for characterization testing and call-site matching."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
    return names


def top_level_function_defs(source: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Public (non-underscore) top-level functions - the candidates for
    characterization testing. See top_level_class_defs/public_methods for the
    class-method counterpart of this (a file with class-only public logic,
    like a real blinker/base.py or argcomplete/my_argparse.py, has none of
    these at all)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]


def top_level_class_defs(source: str) -> list[ast.ClassDef]:
    """Public (non-underscore) top-level classes - the class-method
    characterization-testing candidates top_level_function_defs (functions
    only) doesn't cover. See public_methods for extracting the actual
    per-instance testable surface off of one of these."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [node for node in tree.body if isinstance(node, ast.ClassDef) and not node.name.startswith("_")]


def class_init(class_def: ast.ClassDef) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The class's own __init__, if it defines one directly (not inherited -
    no MRO/base-class resolution here, same heuristic posture as everything
    else in this file). None means "no-arg construction", not "unknown"."""
    for node in class_def.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__init__":
            return node
    return None


def public_methods(class_def: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Public (non-underscore) methods directly in the class body - excludes
    __init__ and every other dunder too (same "not startswith _" filter as
    top_level_function_defs), since __init__ is the constructor, handled
    separately via class_init, not characterized as a case of its own."""
    return [
        node
        for node in class_def.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]


def find_call_site_evidence(
    target_symbols: set[str],
    other_files: list[FileUnit],
) -> dict[str, list[CallSiteEvidence]]:
    """Deterministic, no LLM: scan every OTHER ingested file for calls to any of
    target_symbols. Only reads other files for evidence - never transforms them
    as a side effect of migrating a different file (the one deliberate, scoped
    exception to file-at-a-time processing)."""
    evidence: dict[str, list[CallSiteEvidence]] = {name: [] for name in target_symbols}

    for fu in other_files:
        # Prefer deterministic_output (already py3-valid, if this file has been
        # processed already) over original_source, which may still have
        # py2-only syntax (print statement, `except E, e:`) that stdlib ast
        # (unlike the vendored lib2to3 parser used elsewhere) simply cannot
        # parse - silently skipping every such file would make call-site
        # evidence unreliable exactly when it's most useful (real py2 callers).
        source_to_scan = fu.deterministic_output if fu.deterministic_output is not None else fu.original_source
        try:
            tree = ast.parse(source_to_scan)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_func_name(node)
            if name not in target_symbols:
                continue
            evidence[name].append(
                CallSiteEvidence(
                    symbol=name,
                    caller_file=str(fu.path),
                    args_repr=_call_args_repr(node),
                    context_line=node.lineno,
                )
            )

    return evidence
