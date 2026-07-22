import ast
from dataclasses import dataclass, field
from pathlib import Path

from shiftcode.models import FileUnit

DEFAULT_MAX_CLOSURE_FILES = 20


@dataclass
class ImportEdge:
    importer: Path
    resolved: Path
    import_kind: str  # "absolute" | "relative" - diagnostic only


@dataclass
class ClosureFile:
    rel_path: Path
    source_py2: str
    source_py3: str


@dataclass
class ClosureResult:
    files: list[FileUnit] = field(default_factory=list)
    truncated: bool = False
    truncated_reason: str | None = None
    # Paths with neither final_source nor deterministic_output - their own
    # Phase A step never completed, so the py3 side has nothing but raw py2
    # source to fall back on for them. Not fatal (callers degrade to
    # UNVERIFIED/FAIL for the dependent, never crash), but worth surfacing.
    degraded: list[Path] = field(default_factory=list)


def _candidate_module_paths(base: Path, dotted: str) -> list[Path]:
    sub = Path(*dotted.split("."))
    return [base / sub.with_suffix(".py"), base / sub / "__init__.py"]


def _resolve_absolute(dotted: str, importer_path: Path, root: Path, path_lookup: dict[Path, FileUnit]) -> Path | None:
    """Heuristic, same posture as call_sites.py: no real import-resolution
    graph or sys.path model - just try the ingest root first (the common
    case: a package living directly under the project root), then each
    ancestor directory up to the importer's own directory (covers nested/
    src-layout packages, and - since the importer's own directory is
    included - the very common flat convention of a bare `import
    sibling_module` with no relative-import dots at all)."""
    bases = [root]
    d = importer_path.parent
    while True:
        if d not in bases:
            bases.append(d)
        if d == root or d.parent == d:
            break
        d = d.parent
    for base in bases:
        for candidate in _candidate_module_paths(base, dotted):
            if candidate in path_lookup:
                return candidate
    return None


def _resolve_relative(
    module: str | None, level: int, names: list[str], importer_path: Path, path_lookup: dict[Path, FileUnit]
) -> list[Path]:
    base = importer_path.parent
    for _ in range(level - 1):
        base = base.parent
    resolved: list[Path] = []
    if module:
        # from .X import Y / from ..X import Y - resolve X itself
        for candidate in _candidate_module_paths(base, module):
            if candidate in path_lookup:
                resolved.append(candidate)
                break
    else:
        # from . import X, Y - each name resolved independently
        for name in names:
            for candidate in _candidate_module_paths(base, name):
                if candidate in path_lookup:
                    resolved.append(candidate)
                    break
    return resolved


def resolve_local_imports(
    file_unit: FileUnit,
    all_file_units: list[FileUnit],
    root: Path,
    *,
    path_lookup: dict[Path, FileUnit] | None = None,
) -> list[ImportEdge]:
    """AST-based, heuristic import resolution against other files in the same
    ingested project - same limits as call_sites.py's name-based call-site
    matching (no real sys.path model, no fully general re-export handling).
    Non-local imports (anything not matching another ingested FileUnit) are
    left alone entirely - those go through the existing pip-based
    dependency_provisioning.py mechanism, unchanged."""
    if path_lookup is None:
        path_lookup = {fu.path: fu for fu in all_file_units}

    try:
        tree = ast.parse(file_unit.original_source)
    except SyntaxError:
        return []

    edges: list[ImportEdge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_absolute(alias.name, file_unit.path, root, path_lookup)
                if resolved is not None:
                    edges.append(ImportEdge(importer=file_unit.path, resolved=resolved, import_kind="absolute"))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    resolved = _resolve_absolute(node.module, file_unit.path, root, path_lookup)
                    if resolved is not None:
                        edges.append(ImportEdge(importer=file_unit.path, resolved=resolved, import_kind="absolute"))
            else:
                names = [a.name for a in node.names]
                for resolved in _resolve_relative(node.module, node.level, names, file_unit.path, path_lookup):
                    edges.append(ImportEdge(importer=file_unit.path, resolved=resolved, import_kind="relative"))

    return edges


def dependency_closure(
    file_unit: FileUnit,
    all_file_units: list[FileUnit],
    root: Path,
    *,
    max_closure_files: int = DEFAULT_MAX_CLOSURE_FILES,
) -> ClosureResult:
    """Transitive closure of local-import edges reachable from file_unit
    (not including file_unit itself). Capped, never silently truncated - a
    cap violation is reported via `truncated`/`truncated_reason`, same
    philosophy as ingest.py's DEFAULT_MAX_FILE_BYTES ceiling."""
    path_lookup = {fu.path: fu for fu in all_file_units}
    visited = {file_unit.path}
    queue = [file_unit]
    closure: list[FileUnit] = []
    truncated = False

    while queue and not truncated:
        current = queue.pop(0)
        for edge in resolve_local_imports(current, all_file_units, root, path_lookup=path_lookup):
            dep = path_lookup.get(edge.resolved)
            if dep is None or dep.path in visited:
                continue
            visited.add(dep.path)
            if len(closure) >= max_closure_files:
                truncated = True
                break
            closure.append(dep)
            queue.append(dep)

    # Real package `__init__.py` files along file_unit's OWN directory chain
    # are needed for real package import semantics under Python 2 (no
    # namespace-package support, unlike Python 3's implicit namespace
    # packages) - confirmed real case: a leaf module verified on its own
    # (empty import-edge closure) still needs its own package's __init__.py
    # in the sandbox for `import mypkg.helpers` to work on py2 at all, even
    # though nothing in helpers.py itself imports __init__.py (the
    # dependency runs the other way). These are structural, not import-graph
    # edges, so the BFS above never finds them - added here explicitly, but
    # ONLY when the real project genuinely has that __init__.py file. Never
    # synthesized: a genuine namespace package with no __init__.py at all
    # stays exactly that, matching the real project's actual import
    # semantics rather than diverging from it.
    if not truncated:
        ancestor = file_unit.path.parent
        while ancestor != root and ancestor.parent != ancestor:
            init_unit = path_lookup.get(ancestor / "__init__.py")
            if init_unit is not None and init_unit.path not in visited:
                if len(closure) >= max_closure_files:
                    truncated = True
                    break
                visited.add(init_unit.path)
                closure.append(init_unit)
            ancestor = ancestor.parent

    degraded = [fu.path for fu in closure if fu.final_source is None and fu.deterministic_output is None]
    return ClosureResult(
        files=closure,
        truncated=truncated,
        truncated_reason=(f"dependency closure exceeded {max_closure_files}-file cap" if truncated else None),
        degraded=degraded,
    )


def closure_files_for_sandbox(closure: ClosureResult, root: Path) -> list[ClosureFile]:
    """Converts a ClosureResult into what the sandbox actually needs to
    write: each dependency's real path relative to the ingest root (so
    package structure/`__init__.py` layouts resolve exactly as they would in
    the real project), its untouched py2 source, and its best-available py3
    source - final_source if its own repair pass already completed, else
    deterministic_output (mechanical-only, always present once Phase A ran),
    else raw original_source as a last resort (will typically SyntaxError on
    py3, which correctly surfaces as a FAIL/UNVERIFIED for the dependent
    rather than a crash or a false pass)."""
    return [
        ClosureFile(
            rel_path=fu.path.relative_to(root),
            source_py2=fu.original_source,
            source_py3=fu.final_source or fu.deterministic_output or fu.original_source,
        )
        for fu in closure.files
    ]


def build_import_graph(all_file_units: list[FileUnit], root: Path) -> dict[Path, list[Path]]:
    """Every file's resolved local-import edges, for topological_order."""
    path_lookup = {fu.path: fu for fu in all_file_units}
    graph: dict[Path, list[Path]] = {}
    for fu in all_file_units:
        graph[fu.path] = [e.resolved for e in resolve_local_imports(fu, all_file_units, root, path_lookup=path_lookup)]
    return graph


def topological_order(file_units: list[FileUnit], edges: dict[Path, list[Path]]) -> list[FileUnit]:
    """Dependencies before dependents. Cycle-safe: a DFS back-edge (a
    dependency currently being visited higher up the same call stack) is
    simply skipped rather than followed - breaks the cycle without crashing
    or looping forever. Order within a cycle, and among files with no
    dependency relationship at all, falls back to file_units' original
    (ingest) order, since the outer loop visits them in that order."""
    path_to_unit = {fu.path: fu for fu in file_units}
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[Path, int] = {fu.path: WHITE for fu in file_units}
    order: list[Path] = []

    def visit(path: Path) -> None:
        if color.get(path) != WHITE:
            return
        color[path] = GREY
        for dep in edges.get(path, []):
            if dep not in color or color[dep] == GREY:
                continue  # not one of our files, or a back edge closing a cycle
            visit(dep)
        color[path] = BLACK
        order.append(path)

    for fu in file_units:
        visit(fu.path)

    return [path_to_unit[p] for p in order]
