from dataclasses import dataclass, field

from shiftcode.models.status import GateOutcome


@dataclass
class SyntaxResult:
    passed: bool
    error_message: str | None = None
    error_line: int | None = None
    error_offset: int | None = None


@dataclass
class BehaviorResult:
    outcome: GateOutcome
    mode: str | None = None  # "A" (test suite), "B" (golden-output), "C" (characterization), or None
    detail: str = ""
    failing_tests: list[str] = field(default_factory=list)
    # Mode C only: which evidence tier(s) produced the test plan - "docstring",
    # "call_sites", "llm_inference", or a "+"-joined combination across the
    # file's functions. None for modes A/B.
    evidence_source: str | None = None


@dataclass
class DeterminismResult:
    outcome: GateOutcome
    runs: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class VerifyResult:
    syntax: SyntaxResult | None = None
    behavior: BehaviorResult | None = None
    determinism: DeterminismResult | None = None
