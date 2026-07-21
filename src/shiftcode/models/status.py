from enum import Enum


class Status(str, Enum):
    PENDING = "PENDING"
    TRANSFORMED = "TRANSFORMED"
    VERIFIED = "VERIFIED"
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
