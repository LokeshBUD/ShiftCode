"""Regression: a test_*.py file was hitting Mode B (it has `if __name__ ==
"__main__": unittest.main()`), which runs it standalone in an isolated temp
dir - but test files always import their subject module, so this just crashed
on that import (differently-worded ImportError/ModuleNotFoundError between py2
and py3), reported as a confusing behavior FAIL instead of an honest
"can't verify this" UNVERIFIED."""

from shiftcode.models import GateOutcome
from shiftcode.pipeline.repair import verify_candidate
from shiftcode.pipeline.verify.py2_runtime import Py2Runtime

AVAILABLE_RUNTIME = Py2Runtime(available=True, kind="local", interpreter_path="/usr/bin/python2")

TEST_FILE_SOURCE = (
    "import unittest\nimport some_module\n\n\n"
    "class T(unittest.TestCase):\n    def test_x(self):\n        pass\n\n\n"
    'if __name__ == "__main__":\n    unittest.main()\n'
)


def test_test_named_file_skips_mode_b_and_reports_unverified():
    result = verify_candidate(
        TEST_FILE_SOURCE,
        TEST_FILE_SOURCE,
        "test_something.py",
        py2_runtime=AVAILABLE_RUNTIME,
    )

    assert result.behavior.outcome == GateOutcome.UNVERIFIED
    assert result.behavior.mode is None
    assert "no standalone entry point" in result.behavior.detail
    assert result.determinism is None
