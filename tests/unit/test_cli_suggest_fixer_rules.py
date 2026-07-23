import argparse
import json
from pathlib import Path

from shiftcode.cli import _run_suggest_fixer_rules
from shiftcode.models import GeneralizedFixRule

from fakes import StubProvider


def _write_history(path: Path, *entries: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _args(history: Path, out: Path) -> argparse.Namespace:
    return argparse.Namespace(history=history, out=out, model=None, base_url=None)


def test_suggest_fixer_rules_writes_draft_file_for_each_entry(tmp_path, monkeypatch):
    history_path = tmp_path / "history.jsonl"
    _write_history(
        history_path,
        {
            "file_path": "slugify/__init__.py",
            "before_source": "from types import UnicodeType\n",
            "after_source": "",
            "hints": ["remove import, replace UnicodeType with str"],
            "failure_summaries": ["ImportError"],
        },
    )
    out_dir = tmp_path / "candidate_fixers"

    rule = GeneralizedFixRule(
        pattern_name="legacy_types_bare_import",
        trigger_description="from types import <LegacyType>",
        fix_description="remove the import, replace bare uses with the py3 builtin",
        safety_conditions=["name must be a known legacy types.X entry"],
        confidence=0.9,
        draft_detector_code="def _find_legacy_types_bare_import(tree):\n    return []\n",
    )
    stub_provider = StubProvider([rule])
    monkeypatch.setattr("shiftcode.llm.get_provider", lambda *a, **k: stub_provider)

    result = _run_suggest_fixer_rules(_args(history_path, out_dir))

    assert result == 0
    target = out_dir / "legacy_types_bare_import.py"
    assert target.is_file()
    content = target.read_text()
    assert "REVIEW BEFORE USE" in content
    assert "remove the import, replace bare uses with the py3 builtin" in content
    assert "def _find_legacy_types_bare_import(tree):" in content
    assert "WARNING" not in content


def test_suggest_fixer_rules_flags_a_draft_that_does_not_parse(tmp_path, monkeypatch):
    history_path = tmp_path / "history.jsonl"
    _write_history(
        history_path,
        {"file_path": "m.py", "before_source": "b", "after_source": "a", "hints": ["h"], "failure_summaries": []},
    )
    out_dir = tmp_path / "candidate_fixers"

    rule = GeneralizedFixRule(
        pattern_name="broken_draft",
        trigger_description="x",
        fix_description="x",
        safety_conditions=[],
        confidence=0.5,
        draft_detector_code="def _find_broken(tree)\n    this is not valid python\n",
    )
    stub_provider = StubProvider([rule])
    monkeypatch.setattr("shiftcode.llm.get_provider", lambda *a, **k: stub_provider)

    _run_suggest_fixer_rules(_args(history_path, out_dir))

    content = (out_dir / "broken_draft.py").read_text()
    assert "WARNING: draft did not parse" in content


def test_suggest_fixer_rules_no_op_on_empty_history(tmp_path, capsys):
    history_path = tmp_path / "does_not_exist.jsonl"
    out_dir = tmp_path / "candidate_fixers"

    result = _run_suggest_fixer_rules(_args(history_path, out_dir))

    assert result == 0
    assert not out_dir.exists()
