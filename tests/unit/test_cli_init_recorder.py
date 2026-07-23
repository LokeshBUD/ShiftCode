import argparse
from pathlib import Path

from shiftcode.cli import _run_init_recorder


def test_init_recorder_writes_the_real_recorder_source(tmp_path):
    out = tmp_path / "shiftcode_record.py"
    args = argparse.Namespace(out=out)

    result = _run_init_recorder(args)

    assert result == 0
    content = out.read_text()
    assert "def record(" in content
    assert "import shiftcode" not in content  # must be standalone, zero shiftcode.* dependency
