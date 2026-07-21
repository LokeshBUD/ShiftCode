import ast
from pathlib import Path

from shiftcode.agents.auditor import AuditorAgent
from shiftcode.agents.base import AgentOutputError
from shiftcode.agents.characterization import CharacterizationAgent
from shiftcode.agents.planner import PlannerAgent
from shiftcode.agents.refactorer import RefactorerAgent
from shiftcode.config import ShiftConfig
from shiftcode.llm import get_provider
from shiftcode.models import FileUnit, MigrationPlan, MigrationReport, Status, TestCase
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
from shiftcode.pipeline.verify.sandbox_runtime import ExecutionRuntimes, resolve_execution_runtimes


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
                    test_module_name=f"test_{fu.path.stem}",
                )
                break
    return pairs


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

    all_cases: list[TestCase] = []
    tiers_used: set[str] = set()

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

        try:
            plan = characterization_agent.propose_tests(
                function_source=function_source,
                docstring=docstring,
                call_site_evidence=evidence,
            )
        except AgentOutputError:
            continue  # this one function just doesn't get characterization-tested
        all_cases.extend(plan.cases)

    if not all_cases:
        return None
    return CharacterizationInfo(cases=all_cases, evidence_source="+".join(sorted(tiers_used)))


def _process_file(
    file_unit: FileUnit,
    all_file_units: list[FileUnit],
    *,
    planner: PlannerAgent,
    refactorer: RefactorerAgent,
    auditor: AuditorAgent,
    characterization_agent: CharacterizationAgent,
    runtimes: ExecutionRuntimes,
    max_attempts: int,
    determinism_runs: int,
    test_info: BehaviorTestInfo | None,
) -> None:
    lib_findings = find_lib2to3_findings(file_unit.original_source)

    try:
        file_unit.deterministic_output = deterministic_transform(file_unit.original_source)
    except DeterministicTransformError as exc:
        file_unit.py2_findings = lib_findings
        file_unit.status = Status.NEEDS_REVIEW
        file_unit.reason = f"could not parse original source: {exc}"
        return

    sem_findings, dep_slices = find_semantic_findings(file_unit.deterministic_output)
    file_unit.py2_findings = lib_findings + sem_findings
    file_unit.dependency_slices = dep_slices
    file_unit.status = Status.TRANSFORMED

    needs_llm_findings = [f for f in file_unit.py2_findings if f.needs_llm]
    if needs_llm_findings:
        try:
            file_unit.plan = planner.plan(
                original_source=file_unit.original_source,
                findings=file_unit.py2_findings,
                dependency_slices=dep_slices,
            )
        except AgentOutputError as exc:
            file_unit.status = Status.NEEDS_REVIEW
            file_unit.reason = f"planner output unparseable: {exc}"
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
    )


def run_migration(root: Path, config: ShiftConfig) -> MigrationReport:
    runtimes = resolve_execution_runtimes(config)

    planner = PlannerAgent(get_provider(config.llm_for("planner"), name="planner"))
    refactorer = RefactorerAgent(get_provider(config.llm_for("refactorer"), name="refactorer"))
    auditor = AuditorAgent(get_provider(config.llm_for("auditor"), name="auditor"))
    characterization_agent = CharacterizationAgent(
        get_provider(config.llm_for("characterization"), name="characterization")
    )

    file_units = ingest(root)
    test_pairs = _discover_test_pairs(file_units)

    for file_unit in file_units:
        if file_unit.status == Status.NEEDS_REVIEW:
            continue  # already flagged at ingest (e.g. oversized file)
        _process_file(
            file_unit,
            file_units,
            planner=planner,
            refactorer=refactorer,
            auditor=auditor,
            characterization_agent=characterization_agent,
            runtimes=runtimes,
            max_attempts=config.max_repair_attempts,
            determinism_runs=config.determinism_runs,
            test_info=test_pairs.get(file_unit.path),
        )

    return build_report(file_units)
