import ast
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.base import AgentOutputError
from shiftcode.agents.characterization import CharacterizationAgent, FunctionContext
from shiftcode.agents.planner import PlannerAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.agents.transform_auditor import TransformAuditorAgent
from shiftcode.config import ShiftConfig
from shiftcode.llm import get_provider
from shiftcode.llm.errors import LLMAuthenticationError
from shiftcode.models import FileUnit, MigrationPlan, MigrationReport, Py2Finding, Status, TestCase
from shiftcode.pipeline.analyze import find_lib2to3_findings, find_semantic_findings, strip_dead_true_false_shim
from shiftcode.pipeline.checkpoint import (
    TERMINAL_STATUSES,
    load_checkpoint,
    restore_file_unit,
    serialize_file_unit,
    source_hash,
    write_checkpoint,
)
from shiftcode.pipeline.call_sites import (
    class_init,
    find_call_site_evidence,
    public_methods,
    top_level_class_defs,
    top_level_function_defs,
)
from shiftcode.pipeline.dependencies import (
    ClosureFile,
    build_import_graph,
    closure_files_for_sandbox,
    dependency_closure,
    topological_order,
)
from shiftcode.pipeline.ingest import ingest
from shiftcode.pipeline.repair import BehaviorTestInfo, CharacterizationInfo, is_test_filename, migrate_file
from shiftcode.pipeline.repair_history import append_repair_history, qualifying_repair
from shiftcode.pipeline.report import build_report
from shiftcode.pipeline.transform.deterministic import (
    DeterministicTransformError,
    deterministic_transform,
)
from shiftcode.pipeline.verify.behavior_gate import has_main_block
from shiftcode.pipeline.verify.dependency_provisioning import (
    cleanup_dependency_volume,
    find_requirements_file,
    provision_dependencies,
)
from shiftcode.pipeline.verify.fuzz_generation import expand_function_seeds
from shiftcode.pipeline.verify.recording_loader import RecordedCase, load_recordings
from shiftcode.pipeline.verify.sandbox_runtime import ExecutionRuntimes, resolve_execution_runtimes


def _emit(on_progress: Callable[[str], None] | None, file_unit: FileUnit, msg: str) -> None:
    if on_progress:
        on_progress(f"{file_unit.path.name}: {msg}")


# Files that commonly sit alongside a package's real module(s) but aren't
# themselves library code - excluded when deciding whether a directory has
# exactly one "real" module for the generic tests.py/test.py fallback below
# (conf.py: Sphinx docs config, seen verbatim in two real stress-test
# extractions so far - not a guess).
_NON_MODULE_FILENAMES = {"setup.py", "conf.py"}


# Both real, common directory-naming conventions for a project's test
# directory - "tests" (plural) and "test" (singular). Same axis of naming
# variance as bug #9's file-naming fix (tests.py vs test.py), just on the
# directory name instead - confirmed real via `kislyuk/argcomplete`'s
# `test/test.py` (singular), docs/bug-log.md #26.
_TEST_DIR_NAMES = ("tests", "test")


def _discover_test_pairs(file_units: list[FileUnit]) -> dict[Path, BehaviorTestInfo]:
    by_dir: dict[Path, list[FileUnit]] = {}
    for fu in file_units:
        by_dir.setdefault(fu.path.parent, []).append(fu)

    pairs: dict[Path, BehaviorTestInfo] = {}
    for fu in file_units:
        if is_test_filename(fu.path.name):
            continue
        # Real names to try for a non-package module: its own basename, and
        # (a real, common Python convention - a "private" module's test file
        # usually drops the leading underscore, e.g. blinker's own
        # `_saferef.py` is tested by `test_saferef.py`, not
        # `test__saferef.py`) the same basename with one leading underscore
        # stripped, if it has one.
        module_stem = fu.path.stem
        candidate_stems = [module_stem]
        if module_stem.startswith("_") and not module_stem.startswith("__"):
            candidate_stems.append(module_stem[1:])

        candidates = []
        for stem in candidate_stems:
            candidates.append(fu.path.parent / f"test_{stem}.py")
            for test_dir in _TEST_DIR_NAMES:
                candidates.append(fu.path.parent / test_dir / f"test_{stem}.py")
                # A sibling top-level tests/ (or test/) directory, one level
                # above the module's own directory - real shape, found via
                # blinker: `blinker/_saferef.py` tested by a project-root
                # `tests/test_saferef.py`, not nested inside `blinker/`
                # itself. Same principle as the __init__.py-specific case
                # below (docs/bug-log.md #17), generalized to any module.
                candidates.append(fu.path.parent.parent / test_dir / f"test_{stem}.py")
        if fu.path.name == "__init__.py":
            # A package's test file is very commonly named after the
            # PACKAGE (its directory name), not literally "__init__" - real
            # shapes confirmed on real libraries this session:
            # mypkg/tests/test_mypkg.py (test dir INSIDE the package) and
            # requests/../test_requests.py / requests/../tests/test_requests.py
            # (test file OUTSIDE/sibling to the package directory itself,
            # package-named - docs/bug-log.md #17). Distinct from the
            # schedule/bug-log.md #9 case, which was specifically an
            # artifact of this session's own flat single-directory
            # stress-test extraction, not a real gap.
            pkg_name = fu.path.parent.name
            candidates.append(fu.path.parent / f"test_{pkg_name}.py")
            candidates.append(fu.path.parent.parent / f"test_{pkg_name}.py")
            for test_dir in _TEST_DIR_NAMES:
                candidates.append(fu.path.parent / test_dir / f"test_{pkg_name}.py")
                candidates.append(fu.path.parent.parent / test_dir / f"test_{pkg_name}.py")
                # purl's exact real (un-flattened) shape: a sibling tests/
                # directory containing a GENERICALLY-named tests.py/test.py,
                # not package-named - docs/bug-log.md #17. argcomplete's real
                # shape is the singular-directory variant of the same thing:
                # test/test.py, testing the whole package via `from
                # argcomplete import *` - docs/bug-log.md #26.
                candidates.append(fu.path.parent.parent / test_dir / "tests.py")
                candidates.append(fu.path.parent.parent / test_dir / "test.py")
        matched = next((c for c in candidates if c.is_file()), None)

        if matched is None:
            # Common small-package convention: a single tests.py/test.py
            # tests the package's one real module directly (e.g. jsonschema,
            # purl - both real stress-test cases where the test_<name>.py
            # convention above doesn't apply at all). Deliberately restricted
            # to directories with exactly one real (non-test, non-setup/conf)
            # module, so a multi-file package's unrelated files don't each
            # get incorrectly paired with someone else's test suite.
            real_siblings = [
                other
                for other in by_dir[fu.path.parent]
                if other is not fu
                and not is_test_filename(other.path.name)
                and other.path.name not in _NON_MODULE_FILENAMES
            ]
            if not real_siblings:
                for name in ("tests.py", "test.py"):
                    candidate = fu.path.parent / name
                    if candidate.is_file():
                        matched = candidate
                        break

        if matched is not None:
            pairs[fu.path] = BehaviorTestInfo(
                test_filename=matched.name, test_source=matched.read_text(), test_path=matched
            )
    return pairs


# Third-party test-tooling packages common enough to reliably NOT be the
# package under test itself, when inferring the real import name below -
# real case that motivated this: schedule's own test_schedule.py does
# `import mock` BEFORE `import schedule`, so "first non-stdlib import" alone
# would have picked the wrong name.
_TEST_TOOLING_IMPORT_DENYLIST = {"mock", "pytest", "nose", "hypothesis", "six", "mox", "unittest2", "parameterized"}


def _infer_package_import_name(test_source: str, *, root_name_hint: str) -> str | None:
    """What name does this test file actually import the package under test
    by? The migration root's own directory name is NOT reliable for this -
    real case: `python-slugify` (the clone/repo directory name) ships a
    module actually imported as `slugify`, not `python-slugify` (not even a
    valid identifier). Scans the test source's own top-level imports for the
    real evidence instead, preferring one that resembles root_name_hint (a
    soft prior, not a guess used alone) and falling back to the first
    candidate that isn't stdlib or common test tooling."""
    try:
        tree = ast.parse(test_source)
    except SyntaxError:
        return None

    candidates: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            top = node.module.split(".")[0]
        elif isinstance(node, ast.Import):
            top = node.names[0].name.split(".")[0]
        else:
            continue
        if top in sys.stdlib_module_names or top in _TEST_TOOLING_IMPORT_DENYLIST:
            continue
        candidates.append(top)
    if not candidates:
        return None

    normalized_hint = root_name_hint.lower().replace("-", "").replace("_", "")
    for candidate in candidates:
        if candidate.lower() in normalized_hint:
            return candidate
    return candidates[0]


def _sandbox_root_prefix(
    effective_root: Path, file_units: list[FileUnit], test_pairs: dict[Path, BehaviorTestInfo]
) -> Path | None:
    """None (no wrapping - today's byte-for-byte unchanged behavior) unless
    the migration root itself is a package (its own __init__.py sits
    directly in it). When it is, infers the real importable package name
    from that file's paired test source if one was found, falling back to
    the root's own directory name only when no better evidence exists."""
    root_init = effective_root / "__init__.py"
    if not root_init.is_file():
        return None
    root_file_unit = next((fu for fu in file_units if fu.path == root_init), None)
    test_info = test_pairs.get(root_init) if root_file_unit else None
    if test_info is not None:
        inferred = _infer_package_import_name(test_info.test_source, root_name_hint=effective_root.name)
        if inferred is not None:
            return Path(inferred)
    return Path(effective_root.name)


def _closure_including_test_file(
    file_unit: FileUnit,
    test_info: BehaviorTestInfo | None,
    file_units: list[FileUnit],
    effective_root: Path,
    *,
    max_closure_files: int,
) -> list[ClosureFile]:
    """The module under test's dependency closure, merged with the paired
    test file's OWN closure. A Mode A test file can have real local imports
    independent of what the module itself imports (real case, found via a
    full end-to-end run against `pytoolz/toolz`: a test file does `from
    toolz.utils import raises`, but nothing in the module being verified
    imports toolz.utils at all - only the test file needs it). Without this,
    the sandbox has the module's closure but not the test file's, and pytest
    fails to even collect the test - looks identical to a real behavior
    mismatch (or gets masked as UNVERIFIED by the vacuous-pass guard) but is
    actually just a missing sandbox file. Deduped by rel_path so a file both
    sides need isn't written/considered twice."""
    closure_result = dependency_closure(file_unit, file_units, effective_root, max_closure_files=max_closure_files)
    closure = closure_files_for_sandbox(closure_result, effective_root)
    if test_info is None or test_info.test_path is None:
        return closure
    test_file_unit = next((fu for fu in file_units if fu.path == test_info.test_path), None)
    if test_file_unit is None:
        return closure
    test_closure_result = dependency_closure(
        test_file_unit, file_units, effective_root, max_closure_files=max_closure_files
    )
    test_closure = closure_files_for_sandbox(test_closure_result, effective_root)
    # The test file almost always imports the module under test itself -
    # that edge must NOT be merged in: write_sandbox_tree writes the module
    # separately, with the actual live candidate source being verified right
    # now (module_source_py2/py3), not the FileUnit's own possibly-stale
    # original_source/final_source a generic ClosureFile entry would carry.
    # Merging it in would let the closure-write step (which runs AFTER the
    # module write) silently clobber the real candidate with stale content -
    # verifying the wrong source without any error.
    module_rel_path = file_unit.path.relative_to(effective_root)
    existing_rel_paths = {cf.rel_path for cf in closure} | {module_rel_path}
    return closure + [cf for cf in test_closure if cf.rel_path not in existing_rel_paths]


def _audit_deterministic_transform(
    file_unit: FileUnit, transform_auditor: TransformAuditorAgent
) -> list[Py2Finding]:
    """Runs once per file, right after deterministic_transform, before the
    Planner. The deterministic layer is fast and reliable for the common
    case, but it's pure pattern matching with no scope/binding analysis - a
    real stress test found it silently corrupting a local variable/parameter
    named `long` (lib2to3's fix for the Python 2 `long` type has no way to
    tell "the builtin" from "a local name that happens to match"). Concerns
    become ordinary needs_llm findings feeding into the SAME Planner ->
    Refactorer <-> Auditor loop everything else goes through - no separate
    repair path, no special-casing downstream."""
    try:
        audit = transform_auditor.review(
            original_source=file_unit.original_source,
            deterministic_output=file_unit.deterministic_output,
        )
    except AgentOutputError:
        return []  # audit itself is best-effort; a parse failure here isn't fatal
    return [
        Py2Finding(
            construct_name=f"transform_audit:{c.identifier}",
            line=c.line,
            col=0,
            fixer_name=None,
            needs_llm=True,
            detail=c.concern,
        )
        for c in audit.concerns
    ]


def _build_characterization_info(
    file_unit: FileUnit,
    all_file_units: list[FileUnit],
    characterization_agent: CharacterizationAgent,
    *,
    characterization_fuzz_cases: int = 0,
) -> CharacterizationInfo | None:
    """Runs once per file, before the repair loop (unlike Mode A's test_info,
    this requires LLM calls, so it's generated upfront and reused across
    repair attempts rather than regenerated per attempt).

    characterization_fuzz_cases == 0 (default) keeps today's path unchanged:
    the LLM proposes 2-5 full example cases directly (propose_tests). A
    positive value switches to the differential-fuzzing path instead: the
    LLM proposes a per-parameter seed pool per function (propose_fuzz_seeds,
    one call total either way), and expand_function_seeds - pure, local,
    zero further LLM calls - deterministically expands that into up to
    characterization_fuzz_cases concrete TestCases per function."""
    functions = top_level_function_defs(file_unit.original_source)
    classes = top_level_class_defs(file_unit.original_source)
    if not functions and not classes:
        return None

    # class-only files (all public logic lives in methods, e.g. a real
    # blinker/base.py or argcomplete/my_argparse.py) previously had nothing
    # for Mode C to characterize at all - top_level_function_defs finds
    # functions only. method_defs pairs each public method with its class's
    # own __init__ (constructing an instance is a prerequisite for calling
    # any method on it).
    method_defs: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, ast.FunctionDef | ast.AsyncFunctionDef | None]] = []
    for cls in classes:
        init_def = class_init(cls)
        for method in public_methods(cls):
            method_defs.append((cls.name, method, init_def))

    symbol_names = {fn.name for fn in functions} | {method.name for _, method, _ in method_defs}
    other_files = [fu for fu in all_file_units if fu.path != file_unit.path]
    evidence_by_symbol = find_call_site_evidence(symbol_names, other_files)

    tiers_used: set[str] = set()

    def _context_for(name: str, node, *, class_name: str | None = None, init_source: str | None = None) -> FunctionContext:
        docstring = ast.get_docstring(node)
        evidence = evidence_by_symbol.get(name, [])
        source = ast.get_source_segment(file_unit.original_source, node) or ""
        if evidence:
            tiers_used.add("call_sites")
        elif docstring:
            tiers_used.add("docstring")
        else:
            tiers_used.add("llm_inference")
        return FunctionContext(
            name=name,
            source=source,
            docstring=docstring,
            call_site_evidence=evidence,
            class_name=class_name,
            init_source=init_source,
        )

    function_contexts = [_context_for(fn.name, fn) for fn in functions]
    method_contexts = [
        _context_for(
            method.name,
            method,
            class_name=class_name,
            init_source=ast.get_source_segment(file_unit.original_source, init_def) if init_def else None,
        )
        for class_name, method, init_def in method_defs
    ]

    evidence_source = "+".join(sorted(tiers_used))
    cases: list[TestCase] = []

    # Differential fuzzing (propose_fuzz_seeds/expand_function_seeds) stays
    # top-level-function-only for now - extending it to constructor+method
    # param combinations is real further scope, not needed to unblock
    # class-only files. Methods always go through the plain propose_tests
    # path below (a handful of examples, same as the non-fuzz default),
    # regardless of characterization_fuzz_cases.
    if characterization_fuzz_cases > 0 and function_contexts:
        try:
            fuzz_plan = characterization_agent.propose_fuzz_seeds(functions=function_contexts)
            cases.extend(
                case
                for seed_plan in fuzz_plan.function_seed_plans
                for case in expand_function_seeds(seed_plan, case_budget=characterization_fuzz_cases)
            )
        except AgentOutputError:
            pass  # functions just don't get fuzz-characterized this run
    elif function_contexts:
        try:
            # One call for every function in this file, not one call per
            # function - see FunctionContext's docstring for why.
            plan = characterization_agent.propose_tests(functions=function_contexts)
            cases.extend(plan.cases)
        except AgentOutputError:
            pass

    if method_contexts:
        try:
            method_plan = characterization_agent.propose_tests(functions=method_contexts)
            cases.extend(method_plan.cases)
        except AgentOutputError:
            pass

    if not cases:
        return None
    return CharacterizationInfo(cases=cases, evidence_source=evidence_source)


def _process_file_phase_a(
    file_unit: FileUnit,
    all_file_units: list[FileUnit],
    *,
    planner: PlannerAgent,
    characterization_agent: CharacterizationAgent,
    transform_auditor: TransformAuditorAgent,
    runtimes: ExecutionRuntimes,
    test_info: BehaviorTestInfo | None,
    characterization_fuzz_cases: int = 0,
    on_progress: Callable[[str], None] | None = None,
) -> CharacterizationInfo | None:
    """Deterministic transform, findings, transform-audit, Planner, Mode C
    case generation - everything that doesn't need THIS file's own repair
    loop. Run for every file before any file reaches Phase B, so every
    non-NEEDS_REVIEW file has a deterministic_output/plan available as a
    fallback source for whichever OTHER file's dependency closure needs it
    (see dependencies.py's closure_files_for_sandbox)."""
    # Known-dead constructs that would otherwise prevent ast.parse() itself
    # from succeeding (see strip_dead_true_false_shim's own docstring) get
    # stripped before any other analysis sees the source - same timing as
    # ingest.py's own trailing-newline normalization, one step further
    # upstream than the SyntaxError-catch below used to be the only defense.
    file_unit.original_source, shim_findings = strip_dead_true_false_shim(file_unit.original_source)

    _emit(on_progress, file_unit, "running deterministic transform")
    lib_findings = shim_findings + find_lib2to3_findings(file_unit.original_source)

    try:
        file_unit.deterministic_output = deterministic_transform(file_unit.original_source)
    except DeterministicTransformError as exc:
        file_unit.py2_findings = lib_findings
        file_unit.status = Status.NEEDS_REVIEW
        file_unit.reason = f"could not parse original source: {exc}"
        _emit(on_progress, file_unit, "NEEDS_REVIEW (source did not parse)")
        return None

    try:
        sem_findings, dep_slices = find_semantic_findings(file_unit.deterministic_output)
    except SyntaxError as exc:
        # lib2to3's tolerant grammar successfully parsed and mechanically
        # transformed the original source, but the RESULT still isn't valid
        # Python 3 - real, confirmed cases exist (docs/bug-log.md #14) where a
        # construct lib2to3 has no fixer for survives the transform
        # unchanged. strip_dead_true_false_shim above now pre-empts the one
        # specific known case; this remains the honest backstop for whatever
        # isn't (yet) a known case - NEEDS_REVIEW with a clear diagnosis
        # rather than a raw traceback fragment, never a crash or false
        # confidence (docs/bug-log.md #3).
        file_unit.py2_findings = lib_findings
        file_unit.status = Status.NEEDS_REVIEW
        file_unit.reason = f"deterministically-transformed source is not valid Python 3: {exc}"
        _emit(on_progress, file_unit, "NEEDS_REVIEW (transformed source did not parse)")
        return None

    _emit(on_progress, file_unit, "auditing deterministic transform for silent corruption")
    audit_findings = _audit_deterministic_transform(file_unit, transform_auditor)
    file_unit.py2_findings = lib_findings + sem_findings + audit_findings
    file_unit.dependency_slices = dep_slices
    file_unit.status = Status.TRANSFORMED

    needs_llm_findings = [f for f in file_unit.py2_findings if f.needs_llm]
    if needs_llm_findings:
        _emit(on_progress, file_unit, f"planning ({len(needs_llm_findings)} finding(s) need judgment)")
        try:
            file_unit.plan = planner.plan(
                original_source=file_unit.original_source,
                findings=file_unit.py2_findings,
                dependency_slices=dep_slices,
            )
        except AgentOutputError as exc:
            file_unit.status = Status.NEEDS_REVIEW
            file_unit.reason = f"planner call failed after retries: {exc}"
            _emit(on_progress, file_unit, "NEEDS_REVIEW (planner call failed)")
            return None
    else:
        file_unit.plan = MigrationPlan(steps=[])

    # Mode C (characterization testing) only matters when Mode A/B don't apply
    # and there's a py3 sandbox available to run guessed inputs in - generating
    # it costs real LLM calls, so skip that cost entirely when it can't be used.
    characterization_info = None
    is_test_file = is_test_filename(file_unit.path.name)
    if (
        test_info is None
        and not is_test_file
        and not has_main_block(file_unit.deterministic_output)
        and runtimes.py3_for_c.available
    ):
        _emit(on_progress, file_unit, "generating characterization tests")
        characterization_info = _build_characterization_info(
            file_unit,
            all_file_units,
            characterization_agent,
            characterization_fuzz_cases=characterization_fuzz_cases,
        )
        if characterization_info is not None:
            file_unit.characterization_cases = characterization_info.cases

    return characterization_info


def _process_file_phase_b(
    file_unit: FileUnit,
    *,
    refactorer: RefactorerAgent,
    auditor: AuditorAgent,
    runtimes: ExecutionRuntimes,
    max_attempts: int,
    determinism_runs: int,
    test_info: BehaviorTestInfo | None,
    characterization_info: CharacterizationInfo | None,
    dependency_closure: list[ClosureFile],
    module_rel_path: Path,
    recorded_cases: list[RecordedCase] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Refactorer<->Auditor<->verify repair loop, closure-aware (dependencies.py) -
    the module under test's real sibling-file imports resolve for real inside
    the sandbox instead of failing identically on both interpreters
    (docs/bug-log.md #12, #13)."""
    migrate_file(
        file_unit,
        refactorer=refactorer,
        auditor=auditor,
        py2_runtime=runtimes.py2,
        py3_runtime=runtimes.py3_for_ab,
        py3_runtime_for_c=runtimes.py3_for_c,
        max_attempts=max_attempts,
        determinism_runs=determinism_runs,
        test_info=test_info,
        characterization_info=characterization_info,
        recorded_cases=recorded_cases,
        dependency_closure=dependency_closure,
        module_rel_path=module_rel_path,
        on_progress=(lambda msg, fu=file_unit: _emit(on_progress, fu, msg)) if on_progress else None,
    )
    _emit(on_progress, file_unit, file_unit.status.value)


def _process_file(
    file_unit: FileUnit,
    all_file_units: list[FileUnit],
    *,
    planner: PlannerAgent,
    refactorer: RefactorerAgent,
    auditor: AuditorAgent,
    characterization_agent: CharacterizationAgent,
    transform_auditor: TransformAuditorAgent,
    runtimes: ExecutionRuntimes,
    max_attempts: int,
    determinism_runs: int,
    test_info: BehaviorTestInfo | None,
    characterization_fuzz_cases: int = 0,
    recorded_cases: list[RecordedCase] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Thin single-file convenience wrapper (Phase A then Phase B for one
    file, no dependency closure - there's only one file in play) for callers
    that process exactly one file in isolation rather than a whole project
    (existing tests, CLI single-file convenience)."""
    characterization_info = _process_file_phase_a(
        file_unit,
        all_file_units,
        planner=planner,
        characterization_agent=characterization_agent,
        transform_auditor=transform_auditor,
        runtimes=runtimes,
        test_info=test_info,
        characterization_fuzz_cases=characterization_fuzz_cases,
        on_progress=on_progress,
    )
    if file_unit.status == Status.NEEDS_REVIEW:
        return
    _process_file_phase_b(
        file_unit,
        refactorer=refactorer,
        auditor=auditor,
        runtimes=runtimes,
        max_attempts=max_attempts,
        determinism_runs=determinism_runs,
        test_info=test_info,
        characterization_info=characterization_info,
        recorded_cases=recorded_cases,
        dependency_closure=[],
        module_rel_path=Path(file_unit.path.name),
        on_progress=on_progress,
    )


def _provision_project_dependencies(root: Path, runtimes: ExecutionRuntimes) -> str | None:
    """Preflight, run once per migration (same timing as resolving the
    runtimes themselves): installs the project's own requirements.txt into
    py2 and py3 sandbox volumes before any verification runs, so a missing
    dependency doesn't masquerade as a migration bug (docs/bug-log.md #5).
    py3_for_ab and py3_for_c point at the same underlying Docker image when
    Docker is available (see resolve_execution_runtimes), so provisioning
    py3_for_ab's runtime and reusing its result for py3_for_c avoids running
    the same pip install twice."""
    requirements_file = find_requirements_file(root)
    if requirements_file is None:
        return None

    notes = []
    py2_result = provision_dependencies(runtimes.py2, requirements_file)
    runtimes.py2 = py2_result.runtime
    if py2_result.installed:
        notes.append(f"py2 sandbox: installed {', '.join(py2_result.packages)}")
    elif py2_result.warning:
        notes.append(f"py2 sandbox: {py2_result.warning}")

    py3_for_c_was_same = runtimes.py3_for_c is runtimes.py3_for_ab
    py3_result = provision_dependencies(runtimes.py3_for_ab, requirements_file)
    runtimes.py3_for_ab = py3_result.runtime
    if py3_for_c_was_same:
        runtimes.py3_for_c = py3_result.runtime
    if py3_result.installed:
        notes.append(f"py3 sandbox: installed {', '.join(py3_result.packages)}")
    elif py3_result.warning:
        notes.append(f"py3 sandbox: {py3_result.warning}")

    return "; ".join(notes) if notes else None


def run_migration(
    root: Path, config: ShiftConfig, *, on_progress: Callable[[str], None] | None = None
) -> MigrationReport:
    if on_progress:
        on_progress("resolving execution runtimes (py2/py3 interpreters, sandboxes)")
    runtimes = resolve_execution_runtimes(config)

    dependency_provisioning_summary = None
    if config.install_project_dependencies:
        if on_progress:
            on_progress("checking for project dependencies (requirements.txt)")
        dependency_provisioning_summary = _provision_project_dependencies(root, runtimes)
        if on_progress and dependency_provisioning_summary:
            on_progress(dependency_provisioning_summary)

    planner = PlannerAgent(get_provider(config.llm_for("planner"), name="planner"))
    refactorer = RefactorerAgent(get_provider(config.llm_for("refactorer"), name="refactorer"))
    auditor = AuditorAgent(get_provider(config.llm_for("auditor"), name="auditor"))
    characterization_agent = CharacterizationAgent(
        get_provider(config.llm_for("characterization"), name="characterization")
    )
    transform_auditor = TransformAuditorAgent(
        get_provider(config.llm_for("transform_auditor"), name="transform_auditor")
    )

    # A single-file `shiftcode migrate some_file.py` still needs a real
    # directory to compute relative paths / closures against - its own
    # parent, since the file itself obviously isn't a directory of files.
    effective_root = root if root.is_dir() else root.parent

    file_units = ingest(root)
    test_pairs = _discover_test_pairs(file_units)
    total = len(file_units)
    characterization_infos: dict[Path, CharacterizationInfo] = {}

    # Off by default (config.recordings_dir is None). Loaded once, keyed by
    # function name - matched to whichever file actually defines that
    # top-level function during Phase B, same discovery
    # (top_level_function_defs) Mode C already uses.
    recordings_by_function: dict[str, list[RecordedCase]] = (
        load_recordings(Path(config.recordings_dir)) if config.recordings_dir else {}
    )

    # When the migration root itself IS a package (its own __init__.py sits
    # directly in it, not inside a subdirectory - e.g. `shiftcode migrate
    # some_pkg/`), every path computed relative to effective_root collapses
    # package-name info that a real test importing it depends on:
    # `__init__.py`'s own module_rel_path becomes a bare `Path("__init__.py")`,
    # so write_sandbox_tree writes it unwrapped at the sandbox root - a real
    # test's import fails identically on both interpreters (real regression,
    # confirmed via re-running `schedule` and `python-slugify`: both
    # previously VERIFIED_INFERRED via Mode C, started failing once
    # test-pairing-by-package-name (bug-log.md #17) began correctly routing
    # them to Mode A - Mode A never got the same package-wrapping fix Mode C
    # got for the analogous `purl` case, #13). Prefixing every
    # sandbox-relative path with the correct package name reconstructs
    # exactly the layout a real import needs, without touching any of the
    # real on-disk resolution logic (dependency_closure/resolve_local_imports
    # still use the real effective_root unchanged) - purely a sandbox
    # presentation fix.
    sandbox_root_prefix = _sandbox_root_prefix(effective_root, file_units, test_pairs)

    # Off by default (config.checkpoint_dir is None), byte-for-byte unchanged
    # behavior from before this existed. When set: restore any file whose
    # source hasn't changed since a previous run's checkpoint and which
    # already reached a terminal status - skipped entirely in both phases
    # below, zero LLM/sandbox cost for it this run. A file only partially
    # through Phase A when a previous run was killed has no checkpoint entry
    # at all (only written once a file finishes) and gets fully redone -
    # an honest, deliberate scope limit, not an oversight (docs/bug-log.md).
    checkpoint_dir = Path(config.checkpoint_dir) if config.checkpoint_dir else None
    checkpoint_snapshot: dict[str, dict] = load_checkpoint(checkpoint_dir, root=root) if checkpoint_dir else {}
    resumed_paths: set[Path] = set()
    if checkpoint_dir:
        for file_unit in file_units:
            rel_key = str(file_unit.path.relative_to(effective_root))
            entry = checkpoint_snapshot.get(rel_key)
            if (
                entry is not None
                and entry.get("source_hash") == source_hash(file_unit.original_source)
                and entry.get("status") in {s.value for s in TERMINAL_STATUSES}
            ):
                restore_file_unit(file_unit, entry)
                resumed_paths.add(file_unit.path)
                if on_progress:
                    on_progress(f"{file_unit.path.name}: resumed from checkpoint ({entry['status']})")

    def _checkpoint(file_unit: FileUnit) -> None:
        if checkpoint_dir is None:
            return
        rel_key = str(file_unit.path.relative_to(effective_root))
        checkpoint_snapshot[rel_key] = serialize_file_unit(file_unit)
        write_checkpoint(checkpoint_dir, root=root, files_snapshot=checkpoint_snapshot)

    try:
        # Phase A: transform + findings + Planner + Mode C case generation
        # for every file, before ANY file reaches Phase B - guarantees every
        # non-NEEDS_REVIEW file has a deterministic_output/plan available as
        # a fallback source for whichever other file's dependency closure
        # needs it.
        for i, file_unit in enumerate(file_units, start=1):
            if file_unit.path in resumed_paths:
                continue  # restored from checkpoint - already terminal, skip entirely
            if file_unit.status == Status.NEEDS_REVIEW:
                continue  # already flagged at ingest (e.g. oversized file)
            if on_progress:
                on_progress(f"[{i}/{total}] {file_unit.path.name}")
            try:
                info = _process_file_phase_a(
                    file_unit,
                    file_units,
                    planner=planner,
                    characterization_agent=characterization_agent,
                    transform_auditor=transform_auditor,
                    runtimes=runtimes,
                    test_info=test_pairs.get(file_unit.path),
                    characterization_fuzz_cases=config.characterization_fuzz_cases,
                    on_progress=on_progress,
                )
                if info is not None:
                    characterization_infos[file_unit.path] = info
            except LLMAuthenticationError:
                # A bad API key/config fails identically on every remaining call -
                # grinding through the rest of the files would just repeat the same
                # failure. This is a setup problem, not a per-file one: stop now
                # with a clear top-level error instead of a slow, misleading string
                # of "NEEDS_REVIEW" results that all share the same real cause.
                raise
            except Exception as exc:
                # Genuinely unexpected failure processing this one file (agent
                # calls already degrade gracefully via AgentOutputError - this is
                # the backstop for anything else). One file's surprise shouldn't
                # cost every other file's results.
                file_unit.status = Status.NEEDS_REVIEW
                file_unit.reason = f"unexpected error while processing this file: {exc}"

            if file_unit.status == Status.NEEDS_REVIEW:
                # Phase A itself concluded this file is done (e.g. a
                # transform/parse failure) - it never reaches Phase B, so
                # this is the only chance to checkpoint it.
                _checkpoint(file_unit)

        # Phase B: repair loop, topological order by local-import dependencies
        # (files with no local deps first) - so a dependent gets its
        # dependencies' freshest available candidate wherever possible.
        edges = build_import_graph(file_units, effective_root)
        ordered_units = topological_order(file_units, edges)

        for file_unit in ordered_units:
            if file_unit.path in resumed_paths:
                continue  # restored from checkpoint - already terminal, skip entirely
            if file_unit.status == Status.NEEDS_REVIEW:
                continue  # Phase A failed for this file (or pre-flagged at ingest)
            test_info = test_pairs.get(file_unit.path)
            closure = _closure_including_test_file(
                file_unit,
                test_info,
                file_units,
                effective_root,
                max_closure_files=config.max_dependency_closure_files,
            )
            module_rel_path = file_unit.path.relative_to(effective_root)
            if sandbox_root_prefix is not None:
                module_rel_path = sandbox_root_prefix / module_rel_path
                closure = [replace(cf, rel_path=sandbox_root_prefix / cf.rel_path) for cf in closure]
            recorded_cases = None
            if recordings_by_function:
                own_function_names = {fn.name for fn in top_level_function_defs(file_unit.original_source)}
                matched = [
                    case
                    for name in own_function_names
                    for case in recordings_by_function.get(name, [])
                ]
                recorded_cases = matched or None
            try:
                _process_file_phase_b(
                    file_unit,
                    refactorer=refactorer,
                    auditor=auditor,
                    runtimes=runtimes,
                    max_attempts=config.max_repair_attempts,
                    determinism_runs=config.determinism_runs,
                    test_info=test_info,
                    characterization_info=characterization_infos.get(file_unit.path),
                    recorded_cases=recorded_cases,
                    dependency_closure=closure,
                    module_rel_path=module_rel_path,
                    on_progress=on_progress,
                )
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                file_unit.status = Status.NEEDS_REVIEW
                file_unit.reason = f"unexpected error while processing this file: {exc}"

            _checkpoint(file_unit)

        if config.capture_repair_history:
            history_entries = [e for fu in file_units if (e := qualifying_repair(fu)) is not None]
            append_repair_history(history_entries, Path(config.repair_history_path))
    finally:
        # Volumes are ephemeral scaffolding for this one run, not something
        # that should accumulate on the Docker host across migrations.
        cleanup_dependency_volume(runtimes.py2)
        cleanup_dependency_volume(runtimes.py3_for_ab)
        if runtimes.py3_for_c is not runtimes.py3_for_ab:
            cleanup_dependency_volume(runtimes.py3_for_c)

    return build_report(file_units, dependency_provisioning=dependency_provisioning_summary)
