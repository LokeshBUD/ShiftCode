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
from shiftcode.pipeline.ingest import ingest
from shiftcode.pipeline.repair import BehaviorTestInfo, CharacterizationInfo, migrate_file
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
from shiftcode.pipeline.verify.sandbox_runtime import ExecutionRuntimes, resolve_execution_runtimes


def _emit(on_progress: Callable[[str], None] | None, file_unit: FileUnit, msg: str) -> None:
    if on_progress:
        on_progress(f"{file_unit.path.name}: {msg}")


def _discover_test_pairs(file_units: list[FileUnit]) -> dict[Path, BehaviorTestInfo]:
    pairs: dict[Path, BehaviorTestInfo] = {}
    for fu in file_units:
        if fu.path.stem.startswith("test_"):
            continue
        candidates = [
            fu.path.parent / f"test_{fu.path.name}",
            fu.path.parent / "tests" / f"test_{fu.path.name}",
        ]
        for candidate in candidates:
            if candidate.is_file():
                pairs[fu.path] = BehaviorTestInfo(
                    test_filename=candidate.name,
                    test_source=candidate.read_text(),
                )
                break
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
) -> CharacterizationInfo | None:
    """Runs once per file, before the repair loop (unlike Mode A's test_info,
    this requires LLM calls, so it's generated upfront and reused across
    repair attempts rather than regenerated per attempt)."""
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

    try:
        # One call for every function in this file, not one call per function
        # - see FunctionContext's docstring for why.
        plan = characterization_agent.propose_tests(functions=contexts)
    except AgentOutputError:
        return None  # this file just doesn't get characterization-tested

    if not plan.cases:
        return None
    return CharacterizationInfo(cases=plan.cases, evidence_source="+".join(sorted(tiers_used)))


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
    on_progress: Callable[[str], None] | None = None,
) -> None:
    _emit(on_progress, file_unit, "running deterministic transform")
    lib_findings = find_lib2to3_findings(file_unit.original_source)

    try:
        file_unit.deterministic_output = deterministic_transform(file_unit.original_source)
    except DeterministicTransformError as exc:
        file_unit.py2_findings = lib_findings
        file_unit.status = Status.NEEDS_REVIEW
        file_unit.reason = f"could not parse original source: {exc}"
        _emit(on_progress, file_unit, "NEEDS_REVIEW (source did not parse)")
        return

    sem_findings, dep_slices = find_semantic_findings(file_unit.deterministic_output)
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
            return
    else:
        file_unit.plan = MigrationPlan(steps=[])

    # Mode C (characterization testing) only matters when Mode A/B don't apply
    # and there's a py3 sandbox available to run guessed inputs in - generating
    # it costs real LLM calls, so skip that cost entirely when it can't be used.
    characterization_info = None
    is_test_file = file_unit.path.name.startswith("test_")
    if (
        test_info is None
        and not is_test_file
        and not has_main_block(file_unit.deterministic_output)
        and runtimes.py3_for_c.available
    ):
        _emit(on_progress, file_unit, "generating characterization tests")
        characterization_info = _build_characterization_info(
            file_unit, all_file_units, characterization_agent
        )
        if characterization_info is not None:
            file_unit.characterization_cases = characterization_info.cases

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
        on_progress=(lambda msg, fu=file_unit: _emit(on_progress, fu, msg)) if on_progress else None,
    )
    _emit(on_progress, file_unit, file_unit.status.value)


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

    file_units = ingest(root)
    test_pairs = _discover_test_pairs(file_units)
    total = len(file_units)

    try:
        for i, file_unit in enumerate(file_units, start=1):
            if file_unit.status == Status.NEEDS_REVIEW:
                continue  # already flagged at ingest (e.g. oversized file)
            if on_progress:
                on_progress(f"[{i}/{total}] {file_unit.path.name}")
            try:
                _process_file(
                    file_unit,
                    file_units,
                    planner=planner,
                    refactorer=refactorer,
                    auditor=auditor,
                    characterization_agent=characterization_agent,
                    transform_auditor=transform_auditor,
                    runtimes=runtimes,
                    max_attempts=config.max_repair_attempts,
                    determinism_runs=config.determinism_runs,
                    test_info=test_pairs.get(file_unit.path),
                    on_progress=on_progress,
                )
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
    finally:
        # Volumes are ephemeral scaffolding for this one run, not something
        # that should accumulate on the Docker host across migrations.
        cleanup_dependency_volume(runtimes.py2)
        cleanup_dependency_volume(runtimes.py3_for_ab)
        if runtimes.py3_for_c is not runtimes.py3_for_ab:
            cleanup_dependency_volume(runtimes.py3_for_c)

    return build_report(file_units, dependency_provisioning=dependency_provisioning_summary)
