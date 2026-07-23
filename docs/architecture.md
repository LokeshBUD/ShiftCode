# Architecture

How ShiftCode is actually put together, and why — for anyone extending or
debugging the pipeline itself. If you just want to know what the tool does
and what a report means, see the main `README.md` instead; this is the deep
reference.

## The pipeline, stage by stage

```
ingest → analyze → deterministic transform → Planner → Refactorer ⇄ Auditor → verify → report
```

1. **Ingest** (`pipeline/ingest.py`) — walks the target path, collects `.py`
   files, flags anything over a size ceiling for manual review outright
   (`DEFAULT_MAX_FILE_BYTES`, same "report the cap violation honestly, never
   silently truncate" philosophy the rest of the codebase uses for any
   bounded resource).

2. **Analyze** (`pipeline/analyze.py`) — two independent passes:
   - `find_lib2to3_findings`: a dry-run match (not apply) against every
     vendored `lib2to3` fixer, against the *raw* py2-syntax source. `ast`
     can't parse py2-only syntax (print statements, etc.), so this has to
     run before any transform, using `lib2to3`'s own tolerant grammar.
   - `find_semantic_findings`: an `ast`-based scan, run *after* the
     deterministic transform (needs py3-parseable source), for behavior
     differences no `lib2to3` fixer covers at all — ambiguous `/` division
     was the MVP case; a growing, evidence-driven list of detectors has
     been added since, each only after being confirmed on real code (see
     `docs/bug-log.md`), never guessed in advance. This is also where the
     self-improving fixer library's graduated detectors live once a human
     merges one in (`docs/self-improving-fixer-library.md`).

3. **Deterministic transform** (`pipeline/transform/deterministic.py`) —
   runs the vendored `lib2to3` fixers for real, zero LLM involvement. This
   does the bulk of every real migration mechanically and reliably; the LLM
   is reserved for whatever's left after this pass, which keeps the
   judgment-requiring surface area — and therefore cost and failure
   modes — as small as it can honestly be.

4. **Transform Auditor** runs immediately after the deterministic transform,
   before the Planner ever sees the file — see `docs/agents.md` for why it
   exists and why its findings feed into the *same* finding list as
   everything else rather than a separate repair path.

5. **Planner → Refactorer ⇄ Auditor** — the judgment loop. See
   `docs/agents.md` for each agent's role; the loop itself
   (`pipeline/repair.py`) bounds retries (default 3 attempts,
   `max_repair_attempts`) and never marks a file verified without a gate
   actually passing — exhausting retries lands on `NEEDS_REVIEW` with the
   full attempt history attached, not a silent guess.

6. **Verify** — syntax gate, behavior gate (Mode A/B/C), determinism gate.
   Full mechanics in `docs/verification.md`.

7. **Report** (`pipeline/report.py`) — JSON + text/console rendering: per-file
   status, every finding, the full plan, every repair attempt with its
   diagnosis, and (for Mode C) exactly which test cases were generated, why,
   and how many passed.

## Two-phase orchestration, and why

`pipeline/orchestrator.py`'s `run_migration` doesn't process files one at a
time start-to-finish. It runs **Phase A** (deterministic transform, findings,
Transform Audit, Planner, Mode C case generation) for *every* file first,
before *any* file enters **Phase B** (the Refactorer↔Auditor repair loop).

Why: Phase B needs a real dependency closure — a file's local imports may
need a *sibling* file's latest available source mounted into the sandbox
alongside it (`pipeline/dependencies.py`). If Phase A and B interleaved
per-file, a file processed early wouldn't have a fallback source for a
dependency that hasn't been through Phase A yet. Running Phase A to
completion for the whole project first guarantees every non-`NEEDS_REVIEW`
file has at least a `deterministic_output` (mechanical-only candidate)
available as a closure fallback, even before its own repair loop runs.

Phase B itself processes files in **topological order** by local-import
dependency (`topological_order`, files with no local deps first) — so a
dependent file gets its dependency's *freshest* available candidate
(`final_source` if repair already succeeded, else `deterministic_output`)
wherever possible, rather than always falling back to raw original source.

## Dependency closures, and the two real gaps found fixing them

`pipeline/dependencies.py`'s `dependency_closure` computes the transitive
set of local files a module needs in its sandbox to import correctly — a BFS
over `resolve_local_imports` edges (heuristic AST-based matching against
other ingested files, no real `sys.path`/import-resolution graph; same
posture as `call_sites.py`'s call-site matching).

Two real structural gaps were found and fixed here via actual stress
testing (`docs/bug-log.md` #15, #21, #22, both worth understanding since
they shaped the current design):

- **Python 2 has no implicit namespace packages.** A leaf module verified on
  its own can have an *empty* import-edge closure, yet still needs its own
  package's `__init__.py` present in the sandbox for `import mypkg.helpers`
  to resolve at all on py2 (Python 3 silently tolerates the gap via implicit
  namespace packages, which is exactly why this only broke on py2). Fixed by
  walking the file's own ancestor directory chain and including every real
  `__init__.py` found there — never synthesized; a genuine namespace package
  with no `__init__.py` anywhere stays exactly that.
- **An ancestor `__init__.py` can have real imports of its own.** The fix
  above used to just *append* each ancestor `__init__.py` to the closure —
  but if that `__init__.py` itself re-exports from sibling subpackages (a
  real, common package-root shape — confirmed via `pytoolz/toolz`'s
  top-level `__init__.py`, which does exactly this across three
  subpackages), those re-exported subpackages need to be in the closure
  too. Fixed by seeding ancestor `__init__.py` files into the BFS queue
  itself, not just the result list, so their own edges get resolved like
  any other file's.

A related, separate gap (`docs/bug-log.md` #22): the closure computed for
Mode A verification used to be scoped only to the *module under test* — but
the *paired test file* can have real local imports of its own the module
never references (a test importing a sibling utility module the code under
test doesn't happen to use). Fixed by computing a second closure rooted at
the test file and merging it in (`orchestrator.py`'s
`_closure_including_test_file`) — with one subtlety worth knowing if you
touch this again: the module under test's own path must be explicitly
excluded from the *test file's* contribution, since the test almost always
imports the module itself, and merging that edge in would let the
closure-write step (which runs after the module's own write) silently
clobber the live candidate source being verified with a stale copy.

## Why the Refactorer splices by symbol, not full-file or line-diff

`agents/base.py`'s `apply_symbol_blocks` locates each `SymbolBlock`'s real
AST span (`node.lineno`/`end_lineno`/`col_offset`) in the original source and
replaces exactly that byte range — not a full-file rewrite, and not a raw
line-number diff.

Two reasons, both about what a small/local model reliably gets wrong:
- **Line numbers are fragile.** A model computing "replace lines 40-52" has
  to keep a mental line count in sync with everything else it's writing —
  an easy, silent way to corrupt unrelated code. Symbol names (`function_name`
  or `Class.method`) are far more robust for a model to get right.
- **Full-file rewrites waste the model's attention and widen the blast
  radius.** Asking for a whole file back when only one function actually
  needs to change means the model has to faithfully reproduce everything
  else byte-for-byte, and any hallucination anywhere in that reproduction
  corrupts code that was never supposed to be touched.

Falls back to requesting a full-file replacement (the `__module__` sentinel)
only if a symbol can't be resolved or blocks overlap — `SpliceError`, caught
by the caller.

## File map

```
src/shiftcode/
├── cli.py                          # `shiftcode migrate` / `suggest-fixer-rules` entrypoints
├── config.py                       # provider config: CLI > env > pyproject.toml > defaults
├── llm/                             # provider abstraction (OpenAI-compatible client)
├── agents/                          # see docs/agents.md
├── prompts/                         # static prompt templates, one per agent
├── pipeline/
│   ├── ingest.py                     # file discovery, size-cap enforcement
│   ├── analyze.py                    # lib2to3 dry-run + ast semantic scan + graduated detectors
│   ├── call_sites.py                 # AST call-site evidence extraction (Mode C)
│   ├── dependencies.py               # local-import resolution, dependency closure, topological order
│   ├── repair_history.py             # captures confirmed repairs -> self-improving fixer library input
│   ├── transform/deterministic.py    # the zero-LLM mechanical fixer pass
│   ├── verify/                       # see docs/verification.md
│   │   ├── syntax_gate.py
│   │   ├── behavior_gate.py            # Mode A / Mode B
│   │   ├── characterization_gate.py    # Mode C
│   │   ├── fuzz_generation.py          # differential fuzzing: seed-pool expansion + mutation
│   │   ├── determinism.py
│   │   └── sandbox_runtime.py          # containerized py2/py3 execution + fallback policy
│   ├── repair.py                     # Auditor<->Refactorer loop, wires every gate
│   ├── orchestrator.py               # two-phase (transform, then dependency-ordered repair) wiring
│   └── report.py                     # JSON + text/console report rendering
├── models/                          # Pydantic (agent I/O) + dataclasses (internal state)
└── vendor/lib2to3/                   # vendored stdlib lib2to3 (removed from Python 3.13+)

tests/
├── unit/                             # tests, all run against stubbed providers/runtimes
├── fixtures/sample_project_py2/      # real py2 fixture exercising every mode and evidence tier
└── fixtures/sample_multi_file_py2/   # real, executed multi-file imports (package + sibling-module)

scripts/
├── vendor_lib2to3.py                 # re-vendor lib2to3 from a source Python install
└── find_stress_test_candidates.py    # dev-only: scouts real GitHub libraries, zero LLM tokens
```

## Known implementation limitations

- Mode C's call-site evidence and `dependencies.py`'s local-import resolution
  both use heuristic name matching, not a real import-resolution graph —
  either can occasionally match an unrelated symbol/module with the same
  name.
- The Refactorer's symbol-splice targets top-level functions, classes, and
  methods; module-level scattered edits fall back to full-file replacement.
- Files with zero `needs_llm` findings get exactly one verification attempt,
  no Auditor diagnosis or retry even on a genuinely fixable failure — a real,
  still-open gap (`docs/bug-log.md` #6).
- Migration itself is still one file at a time — each file gets its own plan
  and its own repair loop, no coordinated cross-file edit. Verification is
  multi-file-aware (the dependency closure work above); the repair loop
  itself isn't yet.
