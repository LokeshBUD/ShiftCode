import ast

from shiftcode.models import DependencySlice, Py2Finding
from shiftcode.pipeline.transform.deterministic import make_refactoring_tool
from shiftcode.vendor.lib2to3 import pygram
from shiftcode.vendor.lib2to3.fixes.fix_types import _TYPE_MAPPING
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
    except Exception:
        # Real, confirmed case: a file with no trailing newline raised a raw,
        # uncaught lib2to3 ParseError here - propagating uncaught (the old
        # bare try/finally only restored the grammar, never actually caught
        # anything) meant this ran and crashed BEFORE deterministic_transform
        # got a chance to hit the exact same parse failure through its own,
        # already-correct DeterministicTransformError handling - landing on
        # a much less informative "unexpected error" instead of a clean
        # "could not parse original source" message. This function is purely
        # informational/best-effort (see docstring) - deterministic_transform
        # is what actually needs to succeed, and it already handles this.
        return []
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

    findings.extend(_find_legacy_types_from_imports(tree))
    findings.extend(_find_normalize_encode_chains(tree))
    findings.extend(_find_builtin_cmp_calls(tree))
    findings.extend(_find_inspect_getargspec_calls(tree))

    return findings, slices


def _find_normalize_encode_chains(tree: ast.Module) -> list[Py2Finding]:
    """`unicodedata.normalize(...).encode(encoding, errors)` is a common py2
    idiom for stripping accents/non-ASCII characters - it returned `str` in
    Python 2, but `.encode(...)` always returns `bytes` in Python 3, and
    lib2to3 has no fixer for this since it's a real behavior change, not a
    syntax one. Confirmed via two independent real stress tests (docs/bug-log.md
    #8 - python-slugify's `slugify()` and inflection's `transliterate()`, same
    exact line shape in both) that the resulting bytes value then gets passed
    to further str-only operations (re.sub, .lower(), string formatting) and
    raises TypeError at runtime. Narrowly scoped to this specific chain shape
    rather than every `.encode()` call in general, since that's exactly what's
    been confirmed to actually happen - not a guess at a broader pattern."""
    findings: list[Py2Finding] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "encode"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Attribute)
            and node.func.value.func.attr == "normalize"
        ):
            continue
        findings.append(
            Py2Finding(
                construct_name="normalize_encode_bytes_result",
                line=node.lineno,
                col=node.col_offset,
                fixer_name=None,
                needs_llm=True,
                detail=(
                    "'unicodedata.normalize(...).encode(...)' returns bytes in Python 3 "
                    "(it returned str in Python 2). If this value is used afterward in "
                    "string operations (re.sub, .lower(), string formatting, concatenation "
                    "with a str), that will raise TypeError. Check how the result is used "
                    "downstream in this function; if it feeds further string operations, "
                    "decode it back to str immediately (e.g. append '.decode(\"ascii\")' after "
                    "'.encode(...)')."
                ),
            )
        )
    return findings


def _find_legacy_types_from_imports(tree: ast.Module) -> list[Py2Finding]:
    """lib2to3's fix_types (vendored, real upstream CPython code) only
    rewrites the `types.X` attribute-access form - confirmed via a real
    stress test (docs/bug-log.md #7) that its PATTERN never matches a bare
    name from `from types import UnicodeType`, and by the fixer's own
    documented design it never touches the import statement either. Left
    alone, that import raises ImportError under Python 3 (`types.UnicodeType`
    etc. don't exist there), and since this construct produces zero findings
    on its own, the file gets zero LLM/repair engagement at all (whatever
    other findings exist may also be absent, routing it into the
    zero-plan-steps fast path). Reusing fix_types' own mapping keeps "what's
    the Python 3 equivalent" defined in exactly one place."""
    findings: list[Py2Finding] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module == "types"):
            continue
        for alias in node.names:
            replacement = _TYPE_MAPPING.get(alias.name)
            if replacement is None:
                continue
            findings.append(
                Py2Finding(
                    construct_name="legacy_types_import",
                    line=node.lineno,
                    col=node.col_offset,
                    fixer_name=None,
                    needs_llm=True,
                    detail=(
                        f"'from types import {alias.name}' has no Python 3 equivalent "
                        f"(types.{alias.name} was removed) - lib2to3 only rewrites the "
                        f"'types.{alias.name}' attribute form, never bare names imported "
                        f"this way, and never touches the import statement itself. Remove "
                        f"this import and replace every bare use of "
                        f"'{alias.asname or alias.name}' in this file with '{replacement}'."
                    ),
                )
            )
    return findings


def _find_builtin_cmp_calls(tree: ast.Module) -> list[Py2Finding]:
    """`cmp(a, b)` was a builtin in Python 2 (returns -1/0/1) - removed
    entirely in Python 3 with no replacement, and there's no lib2to3 fixer
    for it (confirmed: no fix_cmp in the vendored fixer set - `ls
    vendor/lib2to3/fixes/`). A bare call raises NameError under Python 3.
    First graduated detector from the self-improving fixer library
    (pipeline/repair_history.py / `suggest-fixer-rules`): drafted by
    FixerRuleAgent against a real confirmed repair, reviewed and merged by
    hand - see docs/bug-log.md for the graduation process this exercises.
    Narrowly matches exactly 2 positional args to a bare `cmp` name (not an
    attribute/method call) - a local function also named `cmp` with this
    same 2-arg shape would false-positive, but that's the same class of
    identifier-shadowing risk `_find_legacy_types_from_imports` above also
    doesn't guard against; TransformAuditorAgent's scope-aware review is
    what actually catches shadowing (see bug-log.md #1), not this detector."""
    findings: list[Py2Finding] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "cmp"
            and len(node.args) == 2
        ):
            continue
        findings.append(
            Py2Finding(
                construct_name="builtin_cmp_call",
                line=node.lineno,
                col=node.col_offset,
                fixer_name=None,
                needs_llm=True,
                detail=(
                    "'cmp(a, b)' was removed in Python 3 with no replacement - a bare "
                    "call raises NameError. Replace it with the idiomatic equivalent "
                    "'(a > b) - (a < b)', which preserves the same -1/0/1 semantics."
                ),
            )
        )
    return findings


def _find_inspect_getargspec_calls(tree: ast.Module) -> list[Py2Finding]:
    """`inspect.getargspec(f)` was deprecated across Python 3 and removed
    entirely in Python 3.11 (`AttributeError: module 'inspect' has no
    attribute 'getargspec'`) - lib2to3 has no fixer for it, since it's a
    stdlib API removal, not a syntax difference (confirmed: no reference to
    it anywhere in the vendored fixer set). Found via a real stress test
    (docs/bug-log.md #23): `pytoolz/toolz`'s curried.py uses it to inspect a
    function's arity. Narrowly matches the module-attribute call form
    (`inspect.getargspec(...)`) - the only form seen in practice; a bare
    `from inspect import getargspec` import would need its own detector,
    not guessed at here."""
    findings: list[Py2Finding] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getargspec"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "inspect"
        ):
            continue
        findings.append(
            Py2Finding(
                construct_name="inspect_getargspec_call",
                line=node.lineno,
                col=node.col_offset,
                fixer_name=None,
                needs_llm=True,
                detail=(
                    "'inspect.getargspec(...)' was removed in Python 3.11 - replace it "
                    "with 'inspect.getfullargspec(...)', which has the same '.args' "
                    "attribute and is available in every Python 3 version."
                ),
            )
        )
    return findings


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
