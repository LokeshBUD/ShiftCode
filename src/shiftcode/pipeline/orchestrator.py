import ast
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
from shiftcode.models import FileUnit, MigrationPlan, MigrationReport, Py2Finding, Status
from shiftcode.pipeline.analyze import find_lib2to3_findings, find_semantic_findings
from shiftcode.pipeline.call_sites import find_call_site_evidence, top_level_function_defs
from shiftcode.pipeline.dependencies import (
    ClosureFile,
    build_import_graph,
    closure_files_for_sandbox,
    dependency_closure,
    topological_order,
)
from shiftcode.pipeline.ingest import ingest
from shiftcode.pipeline.repair import BehaviorTestInfo, CharacterizationInfo, is_test_filename, migrate_file
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


def _discover_test_pairs(file_units: list[FileUnit]) -> dict[Path, BehaviorTestInfo]:
    by_dir: dict[Path, list[FileUnit]] = {}
    for fu in file_units:
        by_dir.setdefault(fu.path.parent, []).append(fu)

    pairs: dict[Path, BehaviorTestInfo] = {}
    for fu in file_units:
        if is_test_filename(fu.path.name):
            continue
        candidates = [
            fu.path.parent / f"test_{fu.path.name}",
            fu.path.parent / "tests" / f"test_{fu.path.name}",
        ]
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
            candidates += [
                fu.path.parent / f"test_{pkg_name}.py",
                fu.path.parent / "tests" / f"test_{pkg_name}.py",
                fu.path.parent.parent / f"test_{pkg_name}.py",
                fu.path.parent.parent / "tests" / f"test_{pkg_name}.py",
                # purl's exact real (un-flattened) shape: a sibling tests/
                # directory containing a GENERICALLY-named tests.py/test.py,
                # not package-named - docs/bug-log.md #17.
                fu.path.parent.parent / "tests" / "tests.py",
                fu.path.parent.parent / "tests" / "test.py",
            ]
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
            pairs[fu.path] = BehaviorTestInfo(test_filename=matched.name, test_source=matched.read_text())
    return pairs


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
    if not functions:
        return None

    symbol_names = {fn.name for fn in functions}
    other_files = [fu for fu in all_file_units if fu.path != file_unit.path]
    evidence_by_symbol = find_call_site_evidence(symbol_names, other_files)

    tiers_used: set[str] = set()
    contexts: list[FunctionContext] = []
    for fn in functions:
        docstring = ast.get_docstring(fn)
        evidence = evidence_by_symbol.get(fn.name, [])
        function_source = ast.get_source_segment(file_unit.original_source, fn) or ""

        if evidence:
            tiers_used.add("call_sites")
        elif docstring:
            tiers_used.add("docstring")
        else:
            tiers_used.add("llm_inference")

        contexts.append(
            FunctionContext(
                name=fn.name, source=function_source, docstring=docstring, call_site_evidence=evidence
            )
        )

    evidence_source = "+".join(sorted(tiers_used))

    if characterization_fuzz_cases > 0:
        try:
            fuzz_plan = characterization_agent.propose_fuzz_seeds(functions=contexts)
        except AgentOutputError:
            return None  # this file just doesn't get characterization-tested
        cases = [
            case
            for seed_plan in fuzz_plan.function_seed_plans
            for case in expand_function_seeds(seed_plan, case_budget=characterization_fuzz_cases)
        ]
        if not cases:
            return None
        return CharacterizationInfo(cases=cases, evidence_source=evidence_source)

    try:
        # One call for every function in this file, not one call per function
        # - see FunctionContext's docstring for why.
        plan = characterization_agent.propose_tests(functions=contexts)
    except AgentOutputError:
        return None  # this file just doesn't get characterization-tested

    if not plan.cases:
        return None
    return CharacterizationInfo(cases=plan.cases, evidence_source=evidence_source)


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
    _emit(on_progress, file_unit, "running deterministic transform")
    lib_findings = find_lib2to3_findings(file_unit.original_source)

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
        # Python 3 - a real, confirmed case: an obscure Python 2.2-era
        # `if not hasattr(__builtins__, 'True'): True, False = 1, 0` shim,
        # which lib2to3 has no fixer for, survives the transform unchanged,
        # and Python 3's real ast.parse correctly rejects it (True/False are
        # reserved keywords there, never valid assignment targets). Without
        # this, the raw SyntaxError fell through to the generic per-file
        # backstop in run_migration with a confusing message instead of a
        # clear diagnosis - same NEEDS_REVIEW outcome either way (safe, no
        # crash - see docs/bug-log.md #3), just a much clearer reason.
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

    try:
        # Phase A: transform + findings + Planner + Mode C case generation
        # for every file, before ANY file reaches Phase B - guarantees every
        # non-NEEDS_REVIEW file has a deterministic_output/plan available as
        # a fallback source for whichever other file's dependency closure
        # needs it.
        for i, file_unit in enumerate(file_units, start=1):
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

        # Phase B: repair loop, topological order by local-import dependencies
        # (files with no local deps first) - so a dependent gets its
        # dependencies' freshest available candidate wherever possible.
        edges = build_import_graph(file_units, effective_root)
        ordered_units = topological_order(file_units, edges)

        for file_unit in ordered_units:
            if file_unit.status == Status.NEEDS_REVIEW:
                continue  # Phase A failed for this file (or pre-flagged at ingest)
            closure_result = dependency_closure(
                file_unit, file_units, effective_root, max_closure_files=config.max_dependency_closure_files
            )
            closure = closure_files_for_sandbox(closure_result, effective_root)
            module_rel_path = file_unit.path.relative_to(effective_root)
            try:
                _process_file_phase_b(
                    file_unit,
                    refactorer=refactorer,
                    auditor=auditor,
                    runtimes=runtimes,
                    max_attempts=config.max_repair_attempts,
                    determinism_runs=config.determinism_runs,
                    test_info=test_pairs.get(file_unit.path),
                    characterization_info=characterization_infos.get(file_unit.path),
                    dependency_closure=closure,
                    module_rel_path=module_rel_path,
                    on_progress=on_progress,
                )
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                file_unit.status = Status.NEEDS_REVIEW
                file_unit.reason = f"unexpected error while processing this file: {exc}"
    finally:
        # Volumes are ephemeral scaffolding for this one run, not something
        # that should accumulate on the Docker host across migrations.
        cleanup_dependency_volume(runtimes.py2)
        cleanup_dependency_volume(runtimes.py3_for_ab)
        if runtimes.py3_for_c is not runtimes.py3_for_ab:
            cleanup_dependency_volume(runtimes.py3_for_c)

    return build_report(file_units, dependency_provisioning=dependency_provisioning_summary)
