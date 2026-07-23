import pytest

from shiftcode.models import FunctionSeedPlan, ParamSeed, TestCase
from shiftcode.pipeline.verify.fuzz_generation import (
    MAX_ANCHOR_CASES,
    UnsafeTestCaseError,
    _combinatorial_expand,
    _mutate_value,
    _neighbor_variants,
    _rng_for,
    expand_function_seeds,
    validate_args_literal,
    validate_seed_literal,
)


@pytest.mark.parametrize(
    "malicious",
    [
        '__import__("os").system("echo pwned")',
        'open("/etc/passwd").read()',
        "(a=5, b=0)",
        'os.system("rm -rf /")',
        "lambda: None",
        "some_name",
    ],
)
def test_validate_args_literal_rejects_non_literal_expressions(malicious):
    """The entire defense against a malicious/manipulated model response
    trying to smuggle code execution through this field. Must reject
    anything that isn't a pure literal tuple - no exceptions."""
    with pytest.raises(UnsafeTestCaseError):
        validate_args_literal(malicious)


def test_validate_args_literal_accepts_literal_tuples():
    assert validate_args_literal("(10, 4)") == (10, 4)
    assert validate_args_literal("()") == ()
    assert validate_args_literal("([1, 2], {'a': 1})") == ([1, 2], {"a": 1})


def test_validate_args_literal_rejects_non_tuple_literal():
    with pytest.raises(UnsafeTestCaseError):
        validate_args_literal("5")  # a literal, but not a tuple


@pytest.mark.parametrize(
    "malicious",
    ['__import__("os").system("x")', "open('/etc/passwd')", "lambda: None", "some_name", "a.b.c"],
)
def test_validate_seed_literal_rejects_non_literal_expressions(malicious):
    with pytest.raises(UnsafeTestCaseError):
        validate_seed_literal(malicious)


def test_validate_seed_literal_accepts_bare_values_not_just_tuples():
    assert validate_seed_literal("5") == 5
    assert validate_seed_literal('"hello"') == "hello"
    assert validate_seed_literal("[]") == []
    assert validate_seed_literal("None") is None
    assert validate_seed_literal("(1, 2)") == (1, 2)  # a tuple IS a legitimate single value here


def _seed(param_index: int, *literals: str) -> ParamSeed:
    return ParamSeed(param_index=param_index, seed_values_literal=list(literals), rationale="test")


def test_expand_function_seeds_respects_case_budget():
    plan = FunctionSeedPlan(
        function_name="f",
        param_seeds=[_seed(0, "1", "2", "3", "4", "5", "6", "7", "8")],
    )
    cases = expand_function_seeds(plan, case_budget=3)
    assert len(cases) <= 3


def test_expand_function_seeds_always_includes_anchors():
    anchor = TestCase(function_name="f", args_literal="(99, 99)", rationale="important call site")
    plan = FunctionSeedPlan(function_name="f", param_seeds=[], anchor_cases=[anchor])
    cases = expand_function_seeds(plan, case_budget=1)
    assert any("(99, 99)" == c.args_literal for c in cases)


def test_expand_function_seeds_caps_anchors_even_if_more_are_given():
    anchors = [TestCase(function_name="f", args_literal=f"({i},)", rationale="x") for i in range(10)]
    plan = FunctionSeedPlan(function_name="f", param_seeds=[], anchor_cases=anchors)
    cases = expand_function_seeds(plan, case_budget=100)
    anchor_cases_used = [c for c in cases if "[anchor]" in c.rationale]
    assert len(anchor_cases_used) <= MAX_ANCHOR_CASES


def test_expand_function_seeds_drops_invalid_seed_without_failing_whole_plan():
    plan = FunctionSeedPlan(
        function_name="f",
        param_seeds=[_seed(0, "1", "__import__('os')", "3")],  # one poisoned entry
    )
    cases = expand_function_seeds(plan, case_budget=10)
    assert len(cases) > 0
    for c in cases:
        args = validate_args_literal(c.args_literal)
        assert "__import__" not in repr(args)


def test_expand_function_seeds_is_deterministic():
    plan = FunctionSeedPlan(
        function_name="f",
        param_seeds=[_seed(0, "1", "2", "3"), _seed(1, "10", "20", "30")],
    )
    first = expand_function_seeds(plan, case_budget=20)
    second = expand_function_seeds(plan, case_budget=20)
    assert [c.args_literal for c in first] == [c.args_literal for c in second]


def test_expand_function_seeds_zero_param_function_produces_empty_tuple_case():
    plan = FunctionSeedPlan(function_name="f", param_seeds=[])
    cases = expand_function_seeds(plan, case_budget=5)
    assert any(c.args_literal == "()" for c in cases)


def test_expand_function_seeds_does_not_pad_budget_with_duplicate_mutations():
    """Real bug found via end-to-end validation: _mutate_value's list/dict
    mutations are deterministic (no rng), so a small seed pool cycled
    multiple times to fill a larger budget used to produce EXACT duplicate
    cases on every cycle after the first - e.g. a 5-combo pool asked to fill
    a budget of 20 produced only 5 distinct cases, tripled. Every returned
    case's args_literal must be distinct."""
    plan = FunctionSeedPlan(function_name="f", param_seeds=[_seed(0, "[1, 2]")])
    cases = expand_function_seeds(plan, case_budget=20)
    literals = [c.args_literal for c in cases]
    assert len(literals) == len(set(literals))


def test_expand_function_seeds_all_invalid_param_seeds_with_nonzero_anchor_skips_degenerate_mutations():
    """Second manifestation of the same real bug: a ParamSeed IS present
    (so param_pools isn't empty), but every one of its literals fails
    validation, leaving an empty pool - _combinatorial_expand correctly
    returns [] for that, but the old [()] fallback still synthesized
    degenerate zero-arg mutations from it."""
    anchor = TestCase(function_name="normalize", args_literal="({'a': 1},)", rationale="typical dict")
    plan = FunctionSeedPlan(
        function_name="normalize",
        param_seeds=[_seed(0, "__import__('os')")],  # every literal here is invalid
        anchor_cases=[anchor],
    )
    cases = expand_function_seeds(plan, case_budget=20)
    assert len(cases) == 1
    assert cases[0].args_literal == "({'a': 1},)"


def test_expand_function_seeds_no_param_seeds_but_nonzero_anchor_skips_degenerate_mutations():
    """Real bug found via end-to-end validation: when the LLM supplies
    anchor_cases but zero param_seeds for a function that actually takes
    arguments (e.g. normalize(items)), the code used to fall through to the
    zero-arg combinatorial/mutation path and fill the rest of the budget
    with meaningless `()` calls. An anchor proving nonzero arity must
    suppress that, leaving just the anchor(s) - not padded with garbage."""
    anchor = TestCase(function_name="normalize", args_literal="({'a': 1},)", rationale="typical dict")
    plan = FunctionSeedPlan(function_name="normalize", param_seeds=[], anchor_cases=[anchor])
    cases = expand_function_seeds(plan, case_budget=20)
    assert len(cases) == 1
    assert cases[0].args_literal == "({'a': 1},)"


def test_expand_function_seeds_never_exceeds_hard_cap_regardless_of_budget():
    plan = FunctionSeedPlan(function_name="f", param_seeds=[_seed(0, "1", "2")])
    cases = expand_function_seeds(plan, case_budget=10_000)
    assert len(cases) <= 500


def test_combinatorial_expand_covers_every_seed_value_at_least_once():
    pools = [[1, 2, 3], [10, 20, 30]]
    combos = _combinatorial_expand(pools, budget=20, rng=_rng_for("f"))
    seen_first = {c[0] for c in combos}
    seen_second = {c[1] for c in combos}
    assert seen_first == {1, 2, 3}
    assert seen_second == {10, 20, 30}


def test_combinatorial_expand_empty_pool_produces_nothing():
    assert _combinatorial_expand([[1, 2], []], budget=10, rng=_rng_for("f")) == []


def test_combinatorial_expand_no_params_produces_single_empty_tuple():
    assert _combinatorial_expand([], budget=10, rng=_rng_for("f")) == [()]


def test_combinatorial_expand_with_duplicate_pool_values_does_not_hang():
    """Real bug found via end-to-end validation: a pool with duplicate
    values (e.g. [[1, 2], [3, 4], [1, 2]]) has fewer DISTINCT combos than its
    raw length suggests - the exhaustion guard must compare against distinct
    achievable combos, not raw pool length, or the random-sampling loop
    spins forever re-picking already-seen combos once distinct space is
    exhausted but the requested budget still exceeds it."""
    pools = [[1, 1, 1], [2, 2, 2]]  # only one distinct combo possible: (1, 2)
    combos = _combinatorial_expand(pools, budget=50, rng=_rng_for("f"))
    assert combos == [(1, 2)]


def test_combinatorial_expand_handles_unhashable_seed_values():
    """Real bug found via end-to-end validation: a parameter seed pool can
    contain lists/dicts (e.g. a function taking a list of items), which are
    unhashable - deduping combos via a raw `set[tuple]` crashed outright.
    Dedup must work off a hashable key (repr), not the combo itself."""
    pools = [[[1, 2], [3, 4], [1, 2]], [{"a": 1}, {"b": 2}]]
    combos = _combinatorial_expand(pools, budget=10, rng=_rng_for("f"))
    assert combos  # must not raise, must produce something
    assert all(isinstance(c, tuple) for c in combos)


def test_mutate_value_type_dispatch_produces_different_values():
    """Some individual mutation choices can be a no-op for a specific input
    (e.g. .lower() on an already-lowercase string) - harmless in practice
    (worst case, one duplicate generated case), so this checks that AT LEAST
    ONE of several trials differs, not that every single call must."""
    rng = _rng_for("f")
    assert any(_mutate_value(5, rng) != 5 for _ in range(10))
    assert any(_mutate_value("hello", rng) != "hello" for _ in range(10))
    assert any(_mutate_value([1, 2], rng) != [1, 2] for _ in range(10))
    assert any(_mutate_value({"a": 1, "b": 2}, rng) != {"a": 1, "b": 2} for _ in range(10))


def test_mutate_value_never_raises_on_unhandled_type():
    rng = _rng_for("f")
    assert _mutate_value(None, rng) is None
    assert _mutate_value(True, rng) is True


def test_neighbor_variants_produces_fixed_count_all_literal_valid():
    variants = _neighbor_variants((5, "hello"), function_name="f", count=3)
    assert len(variants) == 3
    for v in variants:
        validate_args_literal(v.args_literal)  # must not raise
