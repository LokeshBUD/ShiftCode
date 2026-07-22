from shiftcode.models import Status
from shiftcode.pipeline.ingest import ingest


def test_ingest_discovers_py_files_and_excludes_dirs(tmp_path):
    (tmp_path / "a.py").write_text("print 1\n")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "skip.py").write_text("skip me\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("print 2\n")

    units = ingest(tmp_path)
    names = sorted(str(u.path.relative_to(tmp_path)) for u in units)

    assert names == ["a.py", "sub/b.py"]


def test_ingest_flags_oversized_files_for_review(tmp_path):
    (tmp_path / "big.py").write_text("x = 1\n" * 1000)

    units = ingest(tmp_path, max_file_bytes=100)

    assert len(units) == 1
    assert units[0].status == Status.NEEDS_REVIEW
    assert "size ceiling" in units[0].reason


def test_ingest_normalizes_missing_trailing_newline(tmp_path):
    """Regression from a real stress test (requests/__init__.py, docs/bug-log.md
    #18): lib2to3's tokenizer can't parse source with no trailing newline at
    all - semantically inert (Python runs it identically either way), so
    normalized once here rather than patched around downstream."""
    path = tmp_path / "a.py"
    path.write_bytes(b"import os")  # deliberately no trailing newline

    units = ingest(tmp_path)

    assert units[0].original_source == "import os\n"


def test_ingest_does_not_double_up_existing_trailing_newline(tmp_path):
    (tmp_path / "a.py").write_text("import os\n")

    units = ingest(tmp_path)

    assert units[0].original_source == "import os\n"
