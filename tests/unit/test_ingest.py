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
