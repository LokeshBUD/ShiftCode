from enum import Enum


class Status(str, Enum):
    PENDING = "PENDING"
    TRANSFORMED = "TRANSFORMED"
    VERIFIED = "VERIFIED"
    # Passed against REAL captured usage data (Mode R) - real (args -> result)
    # pairs a user recorded from their own Python 2 code actually running,
    # not a guess. Stronger evidence than VERIFIED_INFERRED (an LLM guessed
    # or fuzzed the inputs), but still not VERIFIED: no human ever explicitly
    # asserted the recorded output was itself correct, so a pre-existing bug
    # in the original code could have been captured as "expected" along with
    # everything else. Kept as its own distinct tier for exactly that reason -
    # never blended with either neighbor.
    VERIFIED_RECORDED = "VERIFIED_RECORDED"
    # Passed only auto-generated characterization tests (Mode C) - no human
    # ever wrote or confirmed the expected behavior. Real signal, but weaker
    # evidence than VERIFIED (Mode A, a human-authored test suite), kept
    # distinct so the report never blends the two confidence levels.
    VERIFIED_INFERRED = "VERIFIED_INFERRED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class GateOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"
    SKIPPED = "SKIPPED"
    PRE_EXISTING_NONDETERMINISM = "PRE_EXISTING_NONDETERMINISM"
