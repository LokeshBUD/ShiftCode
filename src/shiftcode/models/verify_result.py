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
    # Real, exact evidence volume - not a synthesized confidence score (see
    # README's "confidence is never blended" principle). Modes A/C only:
    # Mode A's real pytest-discovered test count, Mode C's total executed
    # characterization cases (including neighbor-variant probes). None
    # means "not meaningfully countable" - Mode B's single script
    # comparison, or any UNVERIFIED outcome where nothing real ran.
    cases_run: int | None = None
    cases_passed: int | None = None


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
