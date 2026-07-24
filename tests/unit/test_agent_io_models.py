"""Real gap found while building Mode R (docs/verification.md's
recording_loader.py needed the same check for a genuinely new untrusted
input - a JSONL file - and surfaced that TestCase.function_name, which gets
spliced directly into driver-script SOURCE CODE
(characterization_gate.py's _build_driver_script), had never had one at
all, for the pre-existing LLM-facing path either."""

import pytest
from pydantic import ValidationError

from shiftcode.models import TestCase


def test_accepts_a_real_plain_identifier():
    case = TestCase(function_name="divide", args_literal="(7, 2)", rationale="typical")
    assert case.function_name == "divide"


def test_accepts_dunder_style_identifiers():
    case = TestCase(function_name="__init__", args_literal="()", rationale="x")
    assert case.function_name == "__init__"


@pytest.mark.parametrize(
    "malicious",
    [
        "x); __import__('os').system('echo pwned'); (",
        "os.system",
        "divide()",
        "divide; import os",
        "",
        "1invalid",
        "has space",
    ],
)
def test_rejects_anything_that_is_not_a_plain_identifier(malicious):
    with pytest.raises(ValidationError):
        TestCase(function_name=malicious, args_literal="()", rationale="x")


def test_class_name_defaults_to_none_for_plain_function_cases():
    case = TestCase(function_name="divide", args_literal="(7, 2)", rationale="typical")
    assert case.class_name is None
    assert case.constructor_args_literal is None


def test_accepts_a_real_class_name():
    case = TestCase(
        function_name="resize", args_literal="(4,)", class_name="Widget", constructor_args_literal="(10,)", rationale="x"
    )
    assert case.class_name == "Widget"
    assert case.constructor_args_literal == "(10,)"


@pytest.mark.parametrize(
    "malicious",
    [
        "x); __import__('os').system('echo pwned'); (",
        "os.system",
        "Widget()",
        "",
        "1Invalid",
    ],
)
def test_rejects_a_class_name_that_is_not_a_plain_identifier(malicious):
    with pytest.raises(ValidationError):
        TestCase(function_name="resize", args_literal="()", class_name=malicious, rationale="x")
