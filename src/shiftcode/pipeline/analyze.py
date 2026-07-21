import ast

from shiftcode.models import DependencySlice, Py2Finding
from shiftcode.pipeline.transform.deterministic import make_refactoring_tool
from shiftcode.vendor.lib2to3 import pygram
from shiftcode.vendor.lib2to3.refactor import _detect_future_features


def _fixer_short_name(fixer) -> str:
    module = type(fixer).__module__
    return module.rsplit(".", 1)[-1]


def find_lib2to3_findings(source: str) -> list[Py2Finding]:
    """Dry-run match every lib2to3 fixer against the raw (possibly py2-only-syntax)
    source without applying anything: lib2to3's own grammar tolerates Python 2
    syntax, so unlike stdlib `ast` this is safe to run before any mechanical
    transform. This is the authoritative list of syntax-level py2 constructs
    lib2to3 knows how to fix mechanically (needs_llm=False).

    Note: this only calls each fixer's match(), not transform(). Some fixers
    (e.g. fix_tuple_params) match broadly and only decide in transform()
    whether a real change is needed, so this list can over-report candidates
    that turn out to be no-ops. That's fine here - it's informational context
    for the Planner, not what actually gets applied. The real mechanical fix
    in the deterministic transform stage uses refactor_string(), which is
    correctly gated on transform() producing an actual change."""
    rt = make_refactoring_tool()

    features = _detect_future_features(source)
    if "print_function" in features:
        rt.driver.grammar = pygram.python_grammar_no_print_statement
    try:
        tree = rt.driver.parse_string(source)
    finally:
        rt.driver.grammar = rt.grammar

    fixers = list(rt.pre_order) + list(rt.post_order)
    findings: list[Py2Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for node in tree.pre_order():
        for fixer in fixers:
            try:
                results = fixer.match(node)
            except (AttributeError, IndexError, TypeError):
                # Some fixers' match() assumes a specific node shape (e.g. a Leaf)
                # because in normal operation lib2to3's bottom-matcher only ever
                # calls them on pre-filtered node types. Brute-forcing every fixer
                # against every node here bypasses that filtering, so treat a
                # shape mismatch as "no match" rather than a hard failure - this
                # is a best-effort dry-run report, not the mechanical fix itself
                # (that goes through the real RefactoringTool machinery).
                continue
            if not results:
                continue
            lineno = node.get_lineno() or 0
            col = getattr(node, "column", 0) or 0
            name = _fixer_short_name(fixer)
            key = (name, lineno, col)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                Py2Finding(
                    construct_name=name,
                    line=lineno,
                    col=col,
                    fixer_name=name,
                    needs_llm=False,
                )
            )
    return findings


def find_semantic_findings(
    source: str,
) -> tuple[list[Py2Finding], list[DependencySlice]]:
    """Scan for py2/py3 behavior differences that lib2to3's syntax-level fixers
    can't resolve (needs LLM judgment). MVP covers ambiguous `/` division, since
    lib2to3 ships no division fixer at all. Must run on py3-parseable source
    (i.e. after the deterministic transform stage), since stdlib `ast` can't
    parse py2-only syntax like print statements."""
    tree = ast.parse(source)
    findings: list[Py2Finding] = []
    slices: list[DependencySlice] = []

    parent_of: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_of[child] = parent

    def enclosing_scope(node: ast.AST) -> ast.AST:
        current = parent_of.get(node)
        while current is not None and not isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)
        ):
            current = parent_of.get(current)
        return current if current is not None else tree

    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        findings.append(
            Py2Finding(
                construct_name="ambiguous_division",
                line=node.lineno,
                col=node.col_offset,
                fixer_name=None,
                needs_llm=True,
            )
        )
        slices.append(_build_dependency_slice(enclosing_scope(node), node))

    return findings, slices


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _build_dependency_slice(
    enclosing: ast.AST, division_node: ast.BinOp
) -> DependencySlice:
    involved_names = _names_in(division_node)
    related_lines: list[int] = []
    downstream_usage: list[str] = []

    for node in ast.walk(enclosing):
        if node is division_node:
            continue
        if isinstance(node, ast.Name) and node.id in involved_names:
            related_lines.append(node.lineno)
        if isinstance(node, ast.Call):
            call_name = node.func.id if isinstance(node.func, ast.Name) else None
            if call_name in {"round", "int", "float"} and any(
                isinstance(arg, ast.BinOp) and arg is division_node for arg in node.args
            ):
                downstream_usage.append(f"passed to {call_name}() on line {node.lineno}")
        if isinstance(node, ast.Assert) and any(
            isinstance(n, ast.BinOp) and n is division_node for n in ast.walk(node.test)
        ):
            downstream_usage.append(f"asserted on line {node.lineno}")

    enclosing_name = getattr(enclosing, "name", None)
    try:
        snippet = ast.unparse(enclosing)
    except Exception:
        snippet = ""

    return DependencySlice(
        finding_line=division_node.lineno,
        finding_col=division_node.col_offset,
        enclosing_function=enclosing_name,
        related_lines=sorted(set(related_lines)),
        snippet=snippet,
        downstream_usage=downstream_usage,
    )
