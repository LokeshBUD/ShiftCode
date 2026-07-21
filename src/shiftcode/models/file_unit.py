from dataclasses import dataclass, field
from pathlib import Path

from shiftcode.models.agent_io import MigrationPlan, TestCase
from shiftcode.models.status import Status
from shiftcode.models.verify_result import VerifyResult


@dataclass
class Py2Finding:
    construct_name: str
    line: int
    col: int
    fixer_name: str | None
    needs_llm: bool


@dataclass
class DependencySlice:
    finding_line: int
    finding_col: int
    enclosing_function: str | None
    related_lines: list[int]
    snippet: str
    downstream_usage: list[str] = field(default_factory=list)


@dataclass
class RepairAttempt:
    attempt_number: int
    candidate_source: str
    failure_summary: str
    hint: str | None = None


@dataclass
class CallSiteEvidence:
    symbol: str
    caller_file: str
    args_repr: str
    context_line: int


@dataclass
class FileUnit:
    path: Path
    original_source: str
    py2_findings: list[Py2Finding] = field(default_factory=list)
    dependency_slices: list[DependencySlice] = field(default_factory=list)
    deterministic_output: str | None = None
    plan: MigrationPlan | None = None
    final_source: str | None = None
    verify_result: VerifyResult | None = None
    repair_attempts: list[RepairAttempt] = field(default_factory=list)
    status: Status = Status.PENDING
    reason: str | None = None
    # Mode C only: the auto-generated test cases proposed for this file, so a
    # human reviewing a VERIFIED_INFERRED result can see exactly what was
    # tested and why, not just that "something" passed.
    characterization_cases: list[TestCase] = field(default_factory=list)
