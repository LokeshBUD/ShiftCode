# ShiftCode

Autonomous Legacy Code-Based Migration and Refactoring Engine.

ShiftCode takes a legacy codebase and migrates it to a modern equivalent using a
multi-agent LLM pipeline layered on top of deterministic tooling — with the
correctness of the migration treated as the actual product, not an
afterthought. It never marks a file "done" without passing a verification
gate, and it is explicit about *how confident* it is in that verification.

## Goal

Long-term: take an arbitrary legacy codebase (any source language/version) and
autonomously migrate it to a current equivalent, with behavior provably
preserved wherever it's possible to prove that, and an honest "needs human
review" flag wherever it isn't.

The hard requirement driving every design decision here: **never claim a
migration succeeded without actually verifying it.** A wrong migration that
looks confident is worse than no migration at all — so the pipeline is built
around real execution and real comparison, not an LLM's opinion of whether
code "looks right."

## Current state

MVP scope, working end to end against a real LLM (tested with Gemini via its
OpenAI-compatible endpoint) and a real Python 2 runtime (Docker):

- **One language pair**: Python 2 → Python 3. Not a general polyglot migrator
  yet — the architecture doesn't assume Python-to-Python, but only this pair
  is implemented.
- **File-at-a-time** migration, with one deliberate, scoped exception: Mode C
  (below) reads *other* ingested files to gather real call-site evidence, but
  never transforms them as a side effect of migrating a different file.
- Proven on a bundled fixture (`tests/fixtures/sample_project_py2/`) with a
  real API key and real Docker containers, including a genuine self-correction
  cycle: the Planner initially reasoned incorrectly about Python 2 division
  semantics, the verification gate caught the real behavioral mismatch (not a
  guess), the Auditor diagnosed it, and the Refactorer fixed it on retry.
- 75 unit tests, all passing, none of which require a real LLM or Docker (they
  run against a scripted stand-in provider/runtime).

## How it works

```
ingest → analyze → deterministic transform → Planner → Refactorer ⇄ Auditor → verify → report
```

1. **Ingest** (`pipeline/ingest.py`) — walks the target path, collects `.py`
   files, flags anything over a size ceiling for manual review outright.
2. **Analyze** (`pipeline/analyze.py`) — two passes: a dry-run match against
   every vendored `lib2to3` fixer (finds mechanically-fixable Python 2
   constructs — print statements, `xrange`, `dict.iteritems()`, old-style
   `except E, e:` syntax, etc.), and an `ast`-based scan for things no fixer
   exists for (currently: ambiguous `/` division, which had floor-division
   semantics on two ints in Python 2 but true-division semantics in Python 3 —
   `lib2to3` ships no fixer for this at all, so it always needs judgment).
3. **Deterministic transform** (`pipeline/transform/deterministic.py`) — runs
   the vendored `lib2to3` fixers with zero LLM involvement. Handles the bulk
   of every real migration mechanically and reliably; the LLM is reserved for
   the residue the deterministic tool can't resolve.
4. **Planner → Refactorer ⇄ Auditor** — see Agents below.
5. **Verify** — the candidate must pass a syntax gate, a behavior gate (Mode
   A/B/C, see below), and a determinism gate before anything is trusted.
6. **Report** (`pipeline/report.py`) — JSON + text output: per-file status,
   every finding, the full plan, every repair attempt with its diagnosis, and
   (for Mode C) exactly which test cases were generated and why.

## Agents

Five agents, each with one job, wired through `agents/base.py`'s shared
`call_structured` helper (structured-output call with a bounded retry, and a
regex/`ast`-based fallback parser for providers without native structured
output support):

- **Transform Auditor** (`agents/transform_auditor.py`) — runs once per file,
  right after the deterministic transform, before anything else. Reviews the
  mechanical fixer output against the original for silent semantic drift —
  the deterministic layer is pure pattern matching with no scope/binding
  analysis, and (found via real stress testing, see `docs/bug-log.md`) can
  rename an identifier that collides with an unrelated local variable of the
  same name. Its findings feed into the same finding list everything else
  reads from — no separate repair path.
- **Planner** (`agents/planner.py`) — reads the raw file, the full finding
  list, and a dependency slice around each judgment-call finding. Writes *no
  code* — only a step-by-step plan explaining what should change and why.
- **Refactorer** (`agents/refactorer.py`) — takes the plan and writes the
  actual patch, as targeted symbol-level blocks (not a full-file rewrite,
  and not a raw line-diff — line numbers are exactly the kind of thing a
  smaller/local model gets wrong) spliced back in via `ast` span matching.
  Falls back to requesting a full-file replacement if a symbol can't be
  resolved.
- **Auditor** (`agents/auditor.py`) — only invoked when a verification gate
  fails. Reads the specific failure (`SyntaxError`, a behavior mismatch, a
  determinism divergence) plus a diff of what the Refactorer actually
  changed, and writes a targeted hint for the next attempt — diagnosing the
  failure like a reviewer, not just saying "try again."
- **Characterization** (`agents/characterization.py`) — only invoked for
  files with no existing test suite and no runnable entry point (see Mode C).
  Proposes *inputs* to test with; it never invents expected outputs — those
  always come from actually running the real original code.

The repair loop (`pipeline/repair.py`) bounds Auditor↔Refactorer retries
(default 3 attempts) and never marks a file verified without a gate actually
passing — exhausting retries lands on `NEEDS_REVIEW` with the full attempt
history attached, not a silent guess.

## Works with any LLM provider

Not tied to Claude, or to any single vendor. The only requirement is an
OpenAI-compatible chat-completions endpoint (`llm/openai_compatible.py`),
which covers OpenAI itself, Google Gemini (via its OpenAI-compat endpoint),
Ollama, LM Studio, vLLM's OpenAI server, and most hosted providers.

Switching providers is a config change, not a code change:

```bash
# .env (gitignored, see .env.example)
SHIFTCODE_LLM_API_KEY=sk-...
SHIFTCODE_LLM_MODEL=gpt-4o
SHIFTCODE_LLM_BASE_URL=https://api.openai.com/v1        # or omit for the default

# or, for a fully local setup, no API key needed:
SHIFTCODE_LLM_BASE_URL=http://localhost:11434/v1          # Ollama
SHIFTCODE_LLM_MODEL=llama3
```

Each of the four agents can also be routed to a *different* model/provider
independently (`config.py`'s per-agent overrides, `[tool.shiftcode.agents.*]`
in `pyproject.toml`) — e.g. a flagship model for Planner/Auditor's reasoning,
a cheaper/faster model for the Refactorer's more mechanical job. Every
provider call defaults to `temperature=0.0` to minimize nondeterminism at the
source, on top of the determinism gate that catches it downstream regardless.

## How verification actually works

Three modes, tried in priority order per file, plus two supporting gates that
apply regardless of mode:

- **Syntax gate** — hard gate, always first: `ast.parse` + `py_compile`
  against the candidate. Any failure goes straight to the repair loop with
  the exact error and line.
- **Mode A — has a test suite.** Runs the *same* existing test suite against
  both the original Python 2 code and the migrated Python 3 candidate,
  compares per-test pass/fail outcomes (the authoritative signal — not raw
  `stdout` text, which can differ for reasons that have nothing to do with
  code correctness, like a builtin exception's message wording changing
  between interpreter versions).
- **Mode B — no test suite, but runnable.** For files with `if __name__ ==
  "__main__":`, runs the whole script under both interpreters and diffs
  stdout/stderr/exit code directly.
- **Mode C — no test suite, no entry point.** The common case for real-world
  legacy library code. Auto-generates characterization tests instead of
  requiring a human to have written them: for each public function, gathers
  evidence in priority order — a docstring, then real call-site usage
  elsewhere in the codebase (via static `ast` analysis, literal arguments
  only), then falls back to the LLM reading the function's own code. The
  Characterization agent proposes candidate inputs from that evidence; the
  actual expected behavior always comes from running the real original code
  with those inputs inside a sandbox, never from the LLM's guess.
- **Determinism gate** — runs the candidate multiple times (default 3),
  comparing outputs. New variance introduced only on the migrated side is a
  hard fail. Pre-existing flakiness already present in the legacy code (e.g.
  unordered dict iteration) is reported but doesn't block the migration —
  it's not something ShiftCode introduced.

**Confidence is never blended.** A file verified by Mode A (a human wrote and
presumably validated that test) is marked `VERIFIED`. A file verified only by
Mode C (ShiftCode inferred the spec itself) is marked `VERIFIED_INFERRED` — a
distinct status, kept separate on purpose so the report never implies a
stronger guarantee than what actually happened. `NEEDS_REVIEW` means exactly
that: a gate failed, or nothing could verify the file at all (no test suite,
no entry point, and Mode C had nothing to work with either) — flagged
honestly rather than silently skipped.

### Sandboxing

Both the original (py2) and candidate (py3) sides execute inside ephemeral
Docker containers (`pipeline/verify/sandbox_runtime.py`): `--rm` (nothing
persists), `--network none` (no legitimate reason a correctness check needs
network access — this is the main defense against a bad or malicious input
doing anything outside the sandbox), plus memory/CPU limits. This matters
most for Mode C, since it's the one mode calling functions with LLM-guessed
inputs rather than human-written ones. Mode A/B fall back to local execution
if Docker isn't available (lower marginal risk, human-authored inputs); Mode C
has no such fallback — if it can't run sandboxed, it doesn't run at all.

The one thing standing between "the LLM proposed an input" and arbitrary code
execution: Mode C's test-case arguments are parsed with `ast.literal_eval()`
only, never `eval()`/`exec()`. `literal_eval` structurally cannot evaluate a
function call, attribute access, or name lookup — a manipulated or malicious
model response trying to smuggle `__import__("os").system(...)` through this
field simply fails to parse and is discarded before any driver script is even
built.

## File structure

```
src/shiftcode/
├── cli.py                      # `shiftcode migrate <path>` entrypoint
├── config.py                   # provider config, precedence: CLI > env > pyproject.toml > defaults
├── llm/                        # provider abstraction (OpenAI-compatible client)
├── agents/                     # Transform Auditor, Planner, Refactorer, Auditor, Characterization
├── prompts/                    # static prompt templates for each agent
├── pipeline/
│   ├── ingest.py                # file discovery
│   ├── analyze.py               # lib2to3 dry-run + ast semantic scan
│   ├── call_sites.py            # AST call-site evidence extraction (Mode C)
│   ├── dependencies.py          # local-import resolution, dependency closure, topological order
│   ├── transform/deterministic.py  # the zero-LLM mechanical fixer pass
│   ├── verify/
│   │   ├── syntax_gate.py
│   │   ├── behavior_gate.py     # Mode A / Mode B
│   │   ├── characterization_gate.py  # Mode C
│   │   ├── determinism.py
│   │   └── sandbox_runtime.py   # containerized py2/py3 execution + fallback policy + closure-aware sandbox tree
│   ├── repair.py                # Auditor<->Refactorer loop, wires every gate
│   ├── orchestrator.py          # two-phase (transform, then dependency-ordered repair) per-project wiring
│   └── report.py                # JSON + text report rendering
├── models/                      # Pydantic (agent I/O) + dataclasses (internal state)
└── vendor/lib2to3/               # vendored stdlib lib2to3 (removed from Python 3.13+)

tests/
├── unit/                          # tests, all run against stubbed providers/runtimes
├── fixtures/sample_project_py2/   # real py2 fixture exercising every mode and evidence tier
└── fixtures/sample_multi_file_py2/  # real, executed multi-file imports (package + plain sibling-module)

scripts/
├── vendor_lib2to3.py             # re-vendor lib2to3 from a source Python install
└── find_stress_test_candidates.py  # dev-only: scouts real GitHub libraries for stress-test targets (zero LLM tokens)

docs/
├── bug-log.md                   # real bugs found (mostly via stress testing), root cause, fix
├── stress-test-log.md           # every real library run through the pipeline, outcome, status
└── stress-test-methodology.md   # the standing find/run/diagnose/design/confirm process
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in SHIFTCODE_LLM_API_KEY / MODEL / BASE_URL
```

A Python 2 runtime is required for real (non-`UNVERIFIED`) behavior
verification — either a `python2`/`python2.7` binary on `PATH`, or Docker with
the `python:2.7` image pulled. Without one, every behavior gate correctly
degrades to `UNVERIFIED` rather than fabricating a pass.

```bash
pytest                                          # 80 tests, no LLM/Docker required
shiftcode migrate <path> --dry-run              # list findings only, no LLM calls
shiftcode migrate <path> --output-dir ./out     # full run
```

## Validated against real code

`docs/stress-test-log.md` is a running, honest record of every real-world
library ShiftCode has actually been run against (not the bundled fixtures —
real code pulled from GitHub at its real pre-migration commit). A row there
means "we ran the real pipeline against this," not "this passed" — it tracks
crashed/blocked runs too, not just wins.

| # | Library | Pair | Outcome | Status |
|---|---------|------|---------|--------|
| 9 | [`requests`](https://github.com/kennethreitz/requests) | py2→py3 | first real multi-file library stress-tested; `requests/core.py` and a nested vendored submodule reach `VERIFIED_INFERRED`; `requests/__init__.py` reaches real Mode A (its own test suite correctly fails on live network calls, blocked by the sandbox's own `--network none` isolation — not a bug) | complete |
| 8 | [`purl`](https://github.com/codeinthehole/purl) (re-validated, real nested layout) | py2→py3 | `purl/__init__.py` reaches genuine real `VERIFIED` via Mode A — real multi-file dependency-aware sandboxing closes the original false-`VERIFIED` bug for good | complete |
| 7 | [`schedule`](https://github.com/dbader/schedule) | py2→py3 | `__init__.py` reaches genuine `VERIFIED_INFERRED` — 9 auto-generated characterization tests pass on both interpreters | complete — clean confirmation run, no new bugs |
| 6 | [`html2text`](https://github.com/aaronsw/html2text) | py2→py3 | no test suite (deliberately chosen); found and fixed a diagnostic-clarity bug on an obscure `lib2to3`-unfixable construct | complete |
| 5 | [`purl`](https://github.com/codeinthehole/purl) | py2→py3 | found and fixed a real, high-value bug — a false `VERIFIED` caused by both interpreters failing test collection identically | complete |
| 4 | [`jsonschema`](https://github.com/python-jsonschema/jsonschema) | py2→py3 | `jsonschema.py` runs its real 209-test suite via Mode A (was silently only 12); found and fixed 3 real bugs | complete |
| 3 | [`inflection`](https://github.com/jpvanhal/inflection) | py2→py3 | `inflection.py` reaches real `VERIFIED` — its real pytest suite passes on both interpreters | complete |
| 2 | [`python-slugify`](https://github.com/un33k/python-slugify) | py2→py3 | `__init__.py` reaches `VERIFIED_INFERRED` — all 5 auto-generated characterization tests pass on both interpreters | complete |
| 1 | [`docopt`](https://github.com/docopt/docopt) | py2→py3 | real corruption bug found *and correctly fixed*; `docopt.py` reaches real `VERIFIED` end-to-end | complete — first file to reach real `VERIFIED` on real historical code |

Nine runs, all fully resolved with no open blockers. `purl`'s original
false-`VERIFIED` finding (`docs/bug-log.md` #13) turned out to need real
multi-file dependency-aware sandboxing to close for good, not just a narrow
special case — built and confirmed via a purpose-built fixture
(`tests/fixtures/sample_multi_file_py2/`) before re-validating against
`purl` itself with its real nested directory structure preserved, and then
`requests` — the first genuinely popular, widely-depended-on real library
stress-tested this way. The original blocker the first three runs converged
on — bare sandbox images with no dependencies installed, not even `pytest`
itself — is fixed and confirmed (`docs/bug-log.md` #5). Each round of
stress testing has found further real bugs by unblocking deeper
verification on the same or new code, not by construction — see
`docs/stress-test-log.md` for exactly what each run found and why.

Full detail: `docs/stress-test-log.md`. The process every run follows:
`docs/stress-test-methodology.md`.

## Known limitations

- Python 2 → Python 3 only; no other language pair implemented.
- Migration itself (the Planner/Refactorer/Auditor loop) is still one file
  at a time — each file gets its own plan and its own repair loop, with no
  coordinated cross-file edit. Verification, however, is now real and
  multi-file-aware: `pipeline/dependencies.py` resolves a file's actual
  local imports (heuristic AST-based matching, same limits as call-site
  evidence below) and mounts the whole resulting closure into the sandbox
  at its real relative paths, so `from . import helpers`-style sibling and
  package imports resolve for real instead of failing identically on both
  interpreters.
- Mode C's call-site evidence and the local-import resolution above both use
  heuristic name matching, not a real import-resolution graph — either can
  occasionally match an unrelated symbol/module with the same name.
- No multi-repo/batch orchestration yet.
- The Refactorer's symbol-splice targets top-level functions, classes, and
  methods; module-level scattered edits fall back to full-file replacement.
- Files with zero `needs_llm` findings get exactly one verification attempt,
  no Auditor diagnosis or retry even on a genuinely fixable failure —
  see `docs/bug-log.md` #6.
- Semantic-findings detection (the set of py2/py3 behavior changes that get
  flagged for LLM judgment) is a growing, evidence-driven list, not
  exhaustive: ambiguous division, legacy `types` module imports, and the
  `unicodedata.normalize(...).encode(...)` bytes/str trap so far — each
  added after being confirmed on real code, not guessed in advance.

## Bug log

`docs/bug-log.md` tracks real bugs found in ShiftCode itself — mostly via
stress-testing against real external code, not the bundled fixtures — with
root cause and what now catches that class of bug going forward (a fix, a
new gate, or a new agent). 18 entries so far, all found via genuine stress
testing against real libraries: two vendored-fixer/gate bugs on `docopt`
(shadowed-identifier corruption, vacuous Mode A pass), a crash-isolation bug
and a diagnostic-clarity gap on `python-slugify`, a sandbox-dependency
blocker confirmed independently on two libraries (fixed), a repair-loop gap
still open (#6), two migration-correctness bugs found once the dependency
fix unblocked deeper verification (a legacy `types` import, a `.encode()`
bytes/str trap), three bugs found together on `jsonschema` (a missing
test-file-naming convention, a test file wrongly treated as library code,
and a test file that itself needed migrating before running on Python 3), a
high-value vacuous-pass variant found on `purl` (both interpreters failing
identically was scored as a match), a diagnostic-clarity fix found on
`html2text` (an obscure construct with no mechanical fixer produced a
confusing error instead of a clear one), a real multi-file dependency-aware
sandboxing feature built to close the `purl` finding for good (real, not
narrow — a shared local-import resolver, transitive closure, and
topological repair ordering), two further bugs that surfaced while
validating it (a leaf module missing its own package's `__init__.py`; Mode
C comparing raw `repr()` strings instead of actual values), a test-discovery
gap for a package's test suite living in a sibling `tests/` directory (found
and fixed, confirmed on both `purl` and `requests`), and a parse-crash
diagnostic-clarity bug found on `requests` (a missing trailing newline
crashed past an already-correct error handler; fixed at the root by
normalizing it once at ingest, since it's semantically inert).
