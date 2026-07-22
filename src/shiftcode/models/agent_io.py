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


class TransformConcern(BaseModel):
    identifier: str
    line: int
    concern: str


class TransformAudit(BaseModel):
    concerns: list[TransformConcern]
