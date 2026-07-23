import ast
import random

from shiftcode.models import FunctionSeedPlan, TestCase

# Sanity ceiling regardless of config - protects against a misconfigured
# characterization_fuzz_cases value (e.g. a fat-fingered 50000) from ever
# reaching run_mode_c uncapped. Mirrors dependencies.py's
# DEFAULT_MAX_CLOSURE_FILES pattern: a real ceiling, never silent beyond it.
MAX_GENERATED_CASES_HARD_CAP = 500

# Prompt-level guidance already caps anchor_cases at 3 (characterization_fuzz.md),
# but code-level enforcement doesn't rely on prompt compliance alone - same
# posture as UnsafeTestCaseError existing at all despite the prompt already
# saying literal-only.
MAX_ANCHOR_CASES = 3

_MUTATION_ORIGIN = "mutation:boundary"
_COMBINATION_ORIGIN = "combination"
_SEED_ORIGIN = "seed"
_ANCHOR_ORIGIN = "anchor"
_NEIGHBOR_ORIGIN = "neighbor-of-first-failure"


class UnsafeTestCaseError(Exception):
    """A literal-safety check failed - rejected before any driver script is
    ever built or executed. Not expected in normal operation (the prompts
    instruct literal-only output and the schemas are validated), but this is
    the actual enforcement point, not the prompt wording. Shared by both the
    single-example (TestCase.args_literal) and fuzz (ParamSeed.seed_values_literal)
    characterization paths - one safety mechanism, not two."""


def validate_args_literal(args_literal: str) -> tuple:
    """The only thing standing between 'the LLM proposed an input' and 'code
    executes' - ast.literal_eval structurally cannot evaluate a function call,
    attribute access, or name lookup. Anything that isn't a pure literal tuple
    is rejected here, full stop."""
    try:
        value = ast.literal_eval(args_literal)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
        raise UnsafeTestCaseError(f"args_literal {args_literal!r} rejected: {exc}") from exc
    if not isinstance(value, tuple):
        raise UnsafeTestCaseError(
            f"args_literal {args_literal!r} must be a tuple literal, got {type(value).__name__}"
        )
    return value


def validate_seed_literal(literal: str) -> object:
    """Same posture as validate_args_literal: ast.literal_eval ONLY. A seed
    is a single VALUE (e.g. "5", "'hello'", "[]"), not a tuple - unlike
    args_literal, a bare literal tuple here is treated as a legitimate
    tuple-typed parameter value, not rejected for being 'the wrong shape'
    (that distinction only applies to args_literal, which must always be a
    tuple representing an argument LIST)."""
    try:
        return ast.literal_eval(literal)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
        raise UnsafeTestCaseError(f"seed literal {literal!r} rejected: {exc}") from exc


def _rng_for(function_name: str) -> random.Random:
    """A local, function-name-seeded generator - never the global `random`
    module. expand_function_seeds must be a pure function of its inputs
    (same plan + budget -> byte-identical output every run), which matters
    for unit-testability, reproducibility of a specific run's failure
    report, and avoiding flakiness anywhere this gets exercised in a
    determinism-sensitive test. Seeding from the function name (not a fixed
    global constant) means different functions in the same file don't
    generate identical mutation sequences from identically-shaped pools."""
    return random.Random(hash(function_name))


def _mutate_value(value: object, rng: random.Random) -> object:
    """Boundary nudges, type-dispatched. Falls through to returning the
    value unchanged for types it doesn't recognize (None, bool, nested
    containers, custom objects) - unchanged is always safe, never a
    correctness bug, just a missed mutation opportunity."""
    if isinstance(value, bool):
        return value  # bool is a subclass of int - check before the int branch
    if isinstance(value, int):
        return rng.choice([value + 1, value - 1, -value, value * 1000, value // 2 if value else 0])
    if isinstance(value, float):
        return rng.choice([value + 1.0, value - 1.0, -value, value * 1000.0])
    if isinstance(value, str):
        if not value:
            return "x"
        return rng.choice([value.upper(), value.lower(), value * 2, value[: max(1, len(value) // 2)], value + "✓"])
    if isinstance(value, list):
        if not value:
            return [value]
        mutated = list(value)
        mutated.append(mutated[-1])
        return mutated
    if isinstance(value, dict):
        if not value:
            return dict(value)
        mutated = dict(value)
        mutated.pop(next(iter(mutated)))
        return mutated
    return value


def _combinatorial_expand(param_pools: list[list[object]], *, budget: int, rng: random.Random) -> list[tuple]:
    """Positional expansion capped at budget - deliberately NOT a full
    cartesian product (3 params x 8 seeds each = 512 combinations before any
    mutation is a real combinatorial-explosion risk). Strategy: first, a
    round-robin pass pairing each pool's values against the others so every
    seed value appears in at least one generated tuple (no seed silently
    ignored); then, if budget remains, additional tuples built by picking a
    random value from each pool independently."""
    if not param_pools:
        return [()]
    if any(not pool for pool in param_pools):
        return []  # a parameter with zero valid seeds can't be combined into a full tuple

    # Dedup key is repr(combo), not the combo tuple itself - a parameter's
    # seed value can be a list or dict (e.g. a function taking a list of
    # items), which is unhashable and would crash `set[tuple]` outright
    # (real case: module_b.double_all(values: list), mypkg.helpers.normalize
    # (items: dict), both hit this during real end-to-end validation).
    combos: list[tuple] = []
    seen: set[str] = set()
    max_pool_len = max(len(pool) for pool in param_pools)
    for i in range(max_pool_len):
        if len(combos) >= budget:
            break
        combo = tuple(pool[i % len(pool)] for pool in param_pools)
        key = repr(combo)
        if key not in seen:
            seen.add(key)
            combos.append(combo)

    while len(combos) < budget:
        combo = tuple(rng.choice(pool) for pool in param_pools)
        key = repr(combo)
        if key in seen:
            if len(seen) >= _pool_combination_space(param_pools):
                break  # exhausted every distinct combination - stop, don't loop forever
            continue
        seen.add(key)
        combos.append(combo)

    return combos[:budget]


def _pool_combination_space(param_pools: list[list[object]]) -> int:
    """Distinct achievable combos, not raw pool length - a pool can contain
    duplicate values (e.g. the LLM proposes the same seed twice, or two
    different literals that happen to be equal), and `seen` in
    _combinatorial_expand only ever grows to the number of DISTINCT combos.
    Using raw length here (an earlier version of this function did) counted
    duplicates as separate achievable combos, so the exhaustion guard's
    `len(seen) >= space` check could never trigger - the random-sampling
    loop spun forever re-picking already-seen combos (real bug, found via
    end-to-end validation with a duplicate-valued seed pool)."""
    space = 1
    for pool in param_pools:
        space *= len({repr(v) for v in pool})
    return space


def expand_function_seeds(plan: FunctionSeedPlan, *, case_budget: int) -> list[TestCase]:
    """Deterministic. Validates every seed_values_literal entry and every
    anchor_case's args_literal (invalid entries are dropped, not fatal -
    same posture as run_mode_c's existing per-case rejection loop). Combines
    per-parameter valid pools positionally via bounded combinatorial
    expansion, always includes every anchor_case verbatim (anchors count
    against the budget but are never dropped to make room for
    combinations/mutations), fills remaining budget with light mutation of
    the seed pool. Order: anchors first, then seed-pool combinations, then
    mutations - so if the budget truncates, the cases most directly endorsed
    by the LLM run first. Each returned TestCase's rationale is prefixed
    with its origin tag for later failure-report triage."""
    budget = max(0, min(case_budget, MAX_GENERATED_CASES_HARD_CAP))
    rng = _rng_for(plan.function_name)
    cases: list[TestCase] = []
    anchor_arity: int | None = None

    for anchor in plan.anchor_cases[:MAX_ANCHOR_CASES]:
        if len(cases) >= budget:
            return cases[:budget]
        try:
            parsed_anchor = validate_args_literal(anchor.args_literal)
        except UnsafeTestCaseError:
            continue
        anchor_arity = len(parsed_anchor)
        cases.append(
            TestCase(
                function_name=plan.function_name,
                args_literal=anchor.args_literal,
                rationale=f"[{_ANCHOR_ORIGIN}] {anchor.rationale}",
            )
        )

    if len(cases) >= budget:
        return cases[:budget]

    param_pools: list[list[object]] = []
    for seed in sorted(plan.param_seeds, key=lambda s: s.param_index):
        pool = []
        for literal in seed.seed_values_literal:
            try:
                pool.append(validate_seed_literal(literal))
            except UnsafeTestCaseError:
                continue
        param_pools.append(pool)

    if not param_pools and anchor_arity:
        # No usable per-parameter seeds were given at all, but a valid
        # anchor proves this function takes real (nonzero) arguments - don't
        # fall through to the empty-tuple combinatorial/mutation path below,
        # which would silently synthesize meaningless zero-arg calls instead
        # of real coverage (real bug, found via end-to-end validation: the
        # LLM gave anchor_cases but no param_seeds for a 1-arg function,
        # producing a budget's worth of degenerate `()` mutation cases).
        return cases[:budget]

    remaining = budget - len(cases)
    combos = _combinatorial_expand(param_pools, budget=remaining, rng=rng)
    for combo in combos:
        if len(cases) >= budget:
            return cases[:budget]
        cases.append(
            TestCase(
                function_name=plan.function_name,
                args_literal=repr(combo),
                rationale=f"[{_SEED_ORIGIN}/{_COMBINATION_ORIGIN}] generated from proposed parameter seeds",
            )
        )

    remaining = budget - len(cases)
    # Same "known-nonzero arity, no real seed data" guard as the earlier
    # not-param_pools check, for the other way it can happen: at least one
    # ParamSeed was given but every one of its literals failed validation,
    # so its pool ends up empty and _combinatorial_expand correctly returns
    # [] rather than [()] - but the [()] fallback below would still
    # synthesize degenerate zero-arg mutations if left ungated here too
    # (real bug, found via end-to-end validation: normalize(items) with one
    # all-invalid ParamSeed still produced 19 `()` mutation cases).
    mutation_source = combos if combos else ([] if anchor_arity else [()])
    # Mutated in place across cycles (not re-mutated fresh from the pristine
    # base each time) - _mutate_value's list/dict mutations are deterministic
    # (no rng involved), so cycling through the same small pool 3-4x to fill
    # budget used to produce EXACT duplicate cases every cycle (real bug,
    # found via end-to-end validation: a budget of 20 against a 5-value pool
    # produced only 5 distinct cases, each repeated 3x - no extra coverage
    # for 3/4 of the spent budget). Chaining mutations (mutate the already-
    # mutated value further next cycle) keeps each cycle's result distinct.
    current_bases = list(mutation_source)
    seen_literals = {c.args_literal for c in cases}
    mutation_count = 0
    mutation_attempts = 0
    while remaining > 0 and mutation_source and mutation_attempts <= budget * 4:
        idx = mutation_count % len(mutation_source)
        mutation_count += 1
        mutation_attempts += 1
        mutated = tuple(_mutate_value(v, rng) for v in current_bases[idx])
        current_bases[idx] = mutated
        literal = repr(mutated)
        if literal in seen_literals:
            continue  # exact duplicate (e.g. a numeric mutation looping back to a prior value) - skip, don't waste budget
        seen_literals.add(literal)
        cases.append(
            TestCase(
                function_name=plan.function_name,
                args_literal=repr(mutated),
                rationale=f"[{_MUTATION_ORIGIN}] boundary mutation of a generated case",
            )
        )
        remaining -= 1

    return cases[:budget]


def _neighbor_variants(failing_args: tuple, *, function_name: str, count: int = 3) -> list[TestCase]:
    """A small, fixed-size set of boundary-nudged variants of a known-failing
    case's args - a cheap, non-library analog of property-based-testing
    shrinking. Not a provably-minimal repro, but nudging a known-failing
    input toward simpler/boundary values and seeing which nudges still fail
    gets most of the practical debugging value (is this boundary-specific or
    broad?) at a fixed, small, predictable extra cost."""
    rng = _rng_for(function_name)
    variants = []
    for _ in range(count):
        mutated = tuple(_mutate_value(v, rng) for v in failing_args)
        variants.append(
            TestCase(
                function_name=function_name,
                args_literal=repr(mutated),
                rationale=f"[{_NEIGHBOR_ORIGIN}] boundary variant of the first failing case",
            )
        )
    return variants
