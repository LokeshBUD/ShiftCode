# Stress-test methodology

The standing process for testing ShiftCode against real code, not the
bundled fixtures. Every stress test follows this loop. Don't stray from it —
that consistency is what makes the bug log and stress-test log trustworthy
records instead of an ad-hoc pile of notes.

## The loop

**1. Find.** `scripts/find_stress_test_candidates.py` scouts real GitHub
libraries for a genuine pre-py3-support commit, checks size/test-style/
external-dependency-surface, and reports suitability — zero LLM tokens,
pure git/filesystem work, so token budget stays on the actual product agents
being tested, not on candidate discovery. Add promising repo names to
`SEED_CANDIDATES` as they come up; this is a small curated list, not
autonomous GitHub crawling (deliberate — see the Option A/B split in the
README's bug-log section on why unbounded autonomous discovery is a
different, higher-cost, higher-risk thing than this).

**2. Run.** `--extract` the pre-py3 state, run `shiftcode migrate` against
it for real — real LLM key, real Docker sandboxes. No shortcuts: a stress
test that doesn't use the real pipeline end-to-end doesn't tell us anything
a unit test wouldn't already.

**3. Diagnose — and this step is not optional or skippable.** For any
outcome that isn't a clean, expected `VERIFIED`/`NEEDS_REVIEW`-for-an-
already-known-reason: reproduce it directly before concluding anything.
"Directly" means the same interpreter, same sandbox, same candidate source
the pipeline actually used — not a guess, not a plausible-sounding theory.
Concretely, that's meant things like: running the exact failing
`docker run ... python:2.7 ...` invocation by hand to see the real
traceback (bug #3, bug #5), diffing `repair_attempts[].candidate_source`
across attempts to see what the Refactorer actually changed rather than
assuming (docopt, slugify write-ups), or locally re-running
`deterministic_transform` on the exact input to isolate whether a bug is in
the mechanical layer or the LLM layer (bug #1). A root-cause claim that
hasn't been confirmed this way is a hypothesis, not a finding — don't log it
as the latter.

**4. Design the fix — generalized, not narrow.** Prefer "which agent or gate
should catch this whole *class* of bug going forward" over "which specific
line gets patched." Bug #1 could have been a one-line patch to `fix_long`;
the actual fix was a new agent (`TransformAuditorAgent`) because the same
blind spot exists in the other 51 fixers too. If a fix is genuinely just a
one-off (e.g. a mislabeled error string), it's fine for it to be one-off —
but that should be a conclusion reached after asking the generalization
question, not by skipping it.

**5. Log both directions.** `docs/bug-log.md`: symptom, root cause (as
confirmed in step 3, not as first guessed), fix (or fix design, if not yet
implemented), status. `docs/stress-test-log.md`: which library, what
outcome, cross-linked to any bug numbers it surfaced. A crashed or blocked
run gets logged too — the record's value is honesty, not a highlight reel.

**6. Confirm, then confirm again on a *different* target.** After a fix
lands: re-run the exact stress test that found the bug, to confirm the fix
actually resolves it against the real original repro case. Then, before
considering the fix "done" rather than "probably done," run a *different*
stress test to check the fix generalizes rather than having been shaped
around the one example that found it (this is why docopt and python-slugify
were deliberately picked to be different in character - identifier
shadowing vs. import/encoding handling - rather than two similar cases).

## What this loop is not

Not an autonomous self-fixing agent that edits ShiftCode's own source
without review. That idea was discussed and deliberately not built this way
— see the reasoning in the session notes referenced from `bug-log.md`'s
introduction: a loop that edits its own verification logic to chase a
"more `VERIFIED` outcomes" metric is exactly the failure mode most dangerous
for a tool whose entire value is "never fabricate confidence." Diagnosis and
fix-*design* can and should be pushed as far as possible without waiting for
a check-in (that's this document); applying a change to ShiftCode's own
source is still a reviewed step, not an automatic one.
