from pathlib import Path

from shiftcode.cli import _write_migrated_files
from shiftcode.models import FileUnit, Status


def _file(path: str, status: Status, source: str | None = "print(1)\n") -> FileUnit:
    return FileUnit(path=Path(path), original_source="print 1\n", final_source=source, status=status)


def test_verified_written_to_output_dir_when_not_in_place(tmp_path):
    class _Report:
        files = [_file("m.py", Status.VERIFIED)]

    out = tmp_path / "out"
    written = _write_migrated_files(_Report(), out, in_place=False)

    assert (out / "m.py").read_text() == "print(1)\n"
    assert written == [out / "m.py"]


def test_verified_overwrites_in_place(tmp_path):
    original = tmp_path / "m.py"
    original.write_text("print 1\n")

    class _Report:
        files = [_file(str(original), Status.VERIFIED)]

    out = tmp_path / "out"
    _write_migrated_files(_Report(), out, in_place=True)

    assert original.read_text() == "print(1)\n"
    assert not (out / "m.py").exists()


def test_verified_inferred_never_overwrites_in_place(tmp_path):
    """VERIFIED_INFERRED is a lower-confidence tier (LLM-inferred tests, not
    human-authored ones) - must always land in output_dir, never silently
    replace the original file even when --in-place is requested."""
    original = tmp_path / "m.py"
    original.write_text("print 1\n")

    class _Report:
        files = [_file(str(original), Status.VERIFIED_INFERRED)]

    out = tmp_path / "out"
    written = _write_migrated_files(_Report(), out, in_place=True)

    assert original.read_text() == "print 1\n"  # untouched
    assert (out / "m.py").read_text() == "print(1)\n"
    assert written == [out / "m.py"]


def test_needs_review_and_failed_are_not_written(tmp_path):
    class _Report:
        files = [
            _file("a.py", Status.NEEDS_REVIEW),
            _file("b.py", Status.FAILED),
            _file("c.py", Status.PENDING),
        ]

    out = tmp_path / "out"
    written = _write_migrated_files(_Report(), out, in_place=False)

    assert written == []


def test_skips_files_with_no_final_source(tmp_path):
    class _Report:
        files = [_file("m.py", Status.VERIFIED, source=None)]

    out = tmp_path / "out"
    written = _write_migrated_files(_Report(), out, in_place=False)

    assert written == []
