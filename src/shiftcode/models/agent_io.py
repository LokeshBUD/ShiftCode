from pydantic import BaseModel


class PlanStep(BaseModel):
    finding_ref: str
    description: str
    rationale: str


class MigrationPlan(BaseModel):
    steps: list[PlanStep]


class SymbolBlock(BaseModel):
    symbol: str
    new_source: str


class RefactorPatch(BaseModel):
    blocks: list[SymbolBlock]


class RepairHint(BaseModel):
    root_cause: str
    hint: str


class TestCase(BaseModel):
    __test__ = False  # tell pytest this isn't a test class despite the name

    function_name: str
    # A Python tuple-literal string of POSITIONAL args only, e.g. "(10, 4)" or
    # "()" for no args. Parsed with ast.literal_eval ONLY - never eval()/exec().
    # literal_eval accepts only genuine literal syntax (numbers/strings/lists/
    # dicts/tuples/booleans/None) - notably NOT keyword-argument syntax like
    # "(a=5)", which isn't valid outside an actual call site and would just
    # fail to parse. That parse-only constraint is the entire defense against
    # a manipulated/malicious response trying to smuggle code execution
    # through this field: it structurally cannot contain a function call or
    # attribute access, no matter what the model returns.
    args_literal: str
    rationale: str


class CharacterizationTestPlan(BaseModel):
    cases: list[TestCase]


class ParamSeed(BaseModel):
    # Position of this parameter (0-indexed) in the function's positional
    # argument list - ties the seed pool back to a specific slot so
    # fuzz_generation.py's combinatorial expansion knows which pool feeds
    # which position of a generated args_literal tuple.
    param_index: int
    # A Python literal-expression STRING per candidate value - same
    # literal-only contract as TestCase.args_literal, but each entry here is
    # a single VALUE, not a full argument tuple (e.g. for an int parameter:
    # ["0", "1", "-1", "1000000"]; for a string parameter: ['""', "'hello'",
    # "'a' * 1000"]). Parsed with ast.literal_eval ONLY, never eval()/exec() -
    # same defense as args_literal, applied per-value instead of per-tuple.
    seed_values_literal: list[str]
    rationale: str


class FunctionSeedPlan(BaseModel):
    function_name: str
    param_seeds: list[ParamSeed]
    # A small number of hand-picked FULL argument tuples (same args_literal
    # contract as TestCase) for specific correlated combinations worth
    # pinning verbatim - e.g. a real call-site-observed combination that
    # independent per-parameter expansion of param_seeds couldn't
    # reconstruct on its own. Capped at 3 by both the prompt and
    # fuzz_generation.py (code-level enforcement, not just prompt trust -
    # same posture as args_literal's own ast.literal_eval gate).
    anchor_cases: list[TestCase] = []


class CharacterizationFuzzPlan(BaseModel):
    function_seed_plans: list[FunctionSeedPlan]


class GeneralizedFixRule(BaseModel):
    """A candidate permanent detector, drafted from ONE confirmed real repair
    (see pipeline/repair_history.py). This is a DRAFT for human review, never
    executed automatically anywhere in the pipeline - draft_detector_code is
    plain text a human reads/edits/tests before it's ever real code, same
    posture RefactorPatch.blocks[].new_source has, except that one is
    verified by the sandbox before being trusted and this one deliberately
    isn't (see docs/bug-log.md and the flash-lite feasibility test this
    schema is based on: reliably good at generalizing a rule, not reliably
    faithful at applying one un-reviewed)."""

    pattern_name: str
    trigger_description: str
    fix_description: str
    # Conditions that must hold, or cases to explicitly exclude, before this
    # pattern is safe to detect broadly - e.g. "identifier must be a genuine
    # local binding, not the builtin usage" for a shadowing-style pattern.
    safety_conditions: list[str]
    # 0-1: the model's own confidence this generalizes safely to code it
    # hasn't seen - informational only, never used to auto-decide anything;
    # the human reviewer makes that call regardless of this number.
    confidence: float
    # A starting-point ast.walk detector function body, in the real style of
    # analyze.py's existing hand-written detectors (_find_normalize_encode_chains,
    # _find_legacy_types_from_imports) - a draft for a human to edit and test,
    # not something ever exec()'d by the pipeline.
    draft_detector_code: str


class TransformConcern(BaseModel):
    identifier: str
    line: int
    concern: str


class TransformAudit(BaseModel):
    concerns: list[TransformConcern]
