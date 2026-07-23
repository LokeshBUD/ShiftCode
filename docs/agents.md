# Agents

Six agents, each with one job, each wired through `agents/base.py`'s shared
`call_structured` helper: a structured-output call with a bounded retry on
parse failure, transient-network retry with backoff, and a regex/`ast`-based
fallback parser for providers without native structured-output support. Five
run inside a live migration; the sixth (Fixer-Rule) runs offline, standalone.

## Transform Auditor

**Where:** `agents/transform_auditor.py`. **Runs:** once per file,
immediately after the deterministic transform, before the Planner ever sees
the file.

**What it does:** reviews the mechanical `lib2to3` fixer output against the
original source for silent semantic drift, and produces `TransformConcern`s
that feed into the *same* `Py2Finding` list everything else reads from — not
a separate repair path.

**Why it exists:** the deterministic layer is pure pattern matching with no
scope/binding analysis. A real, confirmed stress test (`docopt`, see
`docs/bug-log.md` #1) found `lib2to3`'s `fix_long` fixer — whose real job is
rewriting *uses of the `long` builtin type* to `int` — blindly rewriting a
local parameter that happened to be named `long`, silently corrupting
`self.long = long` into `self.int = int`. No syntax error, no crash — the
corrupted code kept running, just wrong. That's what makes this class of bug
dangerous enough to warrant its own dedicated agent rather than trusting the
mechanical pass unaudited: it can produce silently-wrong code that still
looks structurally fine.

**Why its findings share the main finding list:** the fix for a real case
like this needs the same judgment-driven Planner→Refactorer path any other
`needs_llm=True` finding gets (revert the corruption, re-derive the correct
rewrite) — there's no reason to build a second, parallel repair mechanism
for what is, functionally, the same kind of finding.

## Planner

**Where:** `agents/planner.py`. **Runs:** once per file, only if there are
`needs_llm=True` findings.

**What it does:** reads the raw file, the full finding list, and a
dependency slice around each judgment-call finding. Writes **no code** —
only a step-by-step `MigrationPlan` (a list of `PlanStep`s, each tied to a
specific finding by reference) explaining what should change and why.

**Why it's separate from the Refactorer:** splitting "decide what should
change" from "write the actual patch" means the Refactorer's prompt can stay
narrowly focused on faithful code generation against an already-reasoned-out
plan, rather than doing analysis and code-writing in the same call. It also
means the plan itself is a real, inspectable artifact in the report — a
human reviewing a `NEEDS_REVIEW` file can see *what ShiftCode believed the
fix should be*, independent of whether the Refactorer actually landed it
correctly.

## Refactorer

**Where:** `agents/refactorer.py`. **Runs:** once per repair attempt (up to
`max_repair_attempts`, default 3).

**What it does:** takes the plan (or, on a retry, the plan plus the
Auditor's hint) and writes the actual patch as targeted `SymbolBlock`s —
spliced back into the original source via AST span matching
(`apply_symbol_blocks`, see `docs/architecture.md` for the full rationale on
why symbol-splice over full-file rewrite or line-diff). Falls back to
requesting a full-file replacement if a symbol can't be resolved.

## Auditor

**Where:** `agents/auditor.py`. **Runs:** only when a verification gate
fails, once per failed attempt.

**What it does:** reads the specific failure (`SyntaxError`, a behavior
mismatch, a determinism divergence) plus a diff of what the Refactorer
actually changed, and writes a targeted `RepairHint` (root cause + a
concrete hint) for the next attempt.

**Why it's reactive-only, never proactive:** diagnosing a failure needs the
*actual* failure signal (the real error, the real diff) to be useful —
there's nothing meaningful for it to review before a real attempt has
actually failed against a real gate. This also bounds its cost: it's the
one agent whose call count scales with how many attempts a file needs, so
keeping it strictly reactive means well-behaved files (that pass on the
first attempt) never pay for it at all.

**A real, observed limitation worth knowing about** (`docs/bug-log.md`
#27): the Auditor's diagnosis is still an LLM judgment call, not a
deterministic mechanism, and it can be wrong — a real run against
`kislyuk/argcomplete` saw it misread a genuinely separate test failure as
caused by a Refactorer change that had actually already fixed the real bug,
and told the Refactorer to *undo* the correct fix. This is an inherent LLM
diagnostic-quality limitation (same category as documented LLM
non-determinism elsewhere), not something a code-level fix addresses — worth
knowing if you're debugging why a repair loop exhausted its budget on a
file that looked like it should have succeeded.

## Characterization

**Where:** `agents/characterization.py`. **Runs:** once per file, only for
files with no existing test suite and no runnable entry point (i.e. only
when Mode C applies — see `docs/verification.md`).

**What it does:** proposes **inputs** to test with — either full example
argument tuples (`propose_tests`, the default path) or, if differential
fuzzing is enabled (`characterization_fuzz_cases > 0`), a per-parameter seed
pool (`propose_fuzz_seeds`) that `pipeline/verify/fuzz_generation.py` then
deterministically expands into many concrete cases, at zero further LLM
cost.

**Why it never invents expected outputs:** the actual expected behavior
always comes from running the real original Python 2 code with the proposed
inputs inside a sandbox — never from the model's guess at what the function
"should" return. If the model doesn't know what a function does, that's
fine: it just needs to propose *plausible* inputs and let real execution
reveal the real behavior. This is the single invariant that makes
`VERIFIED_INFERRED` honest rather than fabricated.

## Fixer-Rule

**Where:** `agents/fixer_rule.py`. **Runs:** offline, standalone from
`migrate` — via `shiftcode suggest-fixer-rules`, once per captured confirmed
repair.

**What it does:** generalizes one confirmed repair (a real before/after diff
plus the Auditor's diagnosed root cause) into a candidate permanent
detector — a precise trigger/fix/safety-conditions description plus a
starting-point `ast.walk` function body, in the style of `analyze.py`'s
existing hand-written detectors.

**Why its output is never auto-applied:** full detail in
`docs/self-improving-fixer-library.md`, but the short version — a live
feasibility test against the model actually in production use here found it
reliably good at *generalizing* a rule, but not reliably faithful at
*applying* one un-reviewed (it improvised an unauthorized "improvement"
instead of a literal substitution when tested). The draft it produces is
plain text a human reads, edits, and tests before it's ever real code — the
same posture `RefactorPatch`'s `new_source` has, except that one is verified
by the sandbox before being trusted and this one deliberately isn't, which
is exactly why this step stays a human gate instead of another automated
one.

## Working with any LLM provider

Not tied to Claude or any single vendor — the only requirement is an
OpenAI-compatible chat-completions endpoint (`llm/openai_compatible.py`),
which covers OpenAI itself, Google Gemini (via its OpenAI-compat endpoint),
Ollama, LM Studio, vLLM's OpenAI server, and most hosted providers.

Each of the six agent roles (`planner`, `refactorer`, `auditor`,
`characterization`, `transform_auditor`, `fixer_rule` —
`config.AGENT_ROLES`) can be routed to a *different* model/provider
independently, via `[tool.shiftcode.agents.<role>]` in `pyproject.toml`
(`ShiftConfig.llm_for(role)`, falling back to the shared default when no
override is configured). Practical use: a flagship model for Planner/Auditor's
reasoning-heavy work, a cheaper/faster model for the Refactorer's more
mechanical code-writing job.

Every provider call defaults to `temperature=0.0` — minimizes nondeterminism
at the source, on top of (not instead of) the determinism gate that catches
whatever variance remains downstream regardless.
