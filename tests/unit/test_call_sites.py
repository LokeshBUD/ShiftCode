from pathlib import Path

from shiftcode.models import FileUnit
from shiftcode.pipeline.call_sites import find_call_site_evidence, top_level_function_defs


def test_top_level_function_defs_excludes_private_and_nested():
    source = (
        "def public_fn():\n    pass\n\n"
        "def _private_fn():\n    pass\n\n"
        "class C:\n    def method(self):\n        pass\n"
    )
    names = {fn.name for fn in top_level_function_defs(source)}
    assert names == {"public_fn"}


def test_find_call_site_evidence_captures_literal_args():
    caller = FileUnit(
        path=Path("caller.py"),
        original_source="import mathutils\nmathutils.clamp(5, 0, 10)\n",
    )
    evidence = find_call_site_evidence({"clamp"}, [caller])
    assert len(evidence["clamp"]) == 1
    assert evidence["clamp"][0].args_repr == "(5, 0, 10)"
    assert evidence["clamp"][0].caller_file == "caller.py"


def test_find_call_site_evidence_marks_non_literal_args_honestly():
    caller = FileUnit(
        path=Path("caller.py"),
        original_source="import mathutils\nx = get_input()\nmathutils.clamp(x, 0, 10)\n",
    )
    evidence = find_call_site_evidence({"clamp"}, [caller])
    assert evidence["clamp"][0].args_repr == "(<non-literal>, 0, 10)"


def test_find_call_site_evidence_prefers_deterministic_output_over_py2_only_source():
    """Regression: original_source may have py2-only syntax (print statement,
    except-comma) that stdlib ast can't parse at all, silently dropping every
    call site in that file. deterministic_output (already py3-valid, once the
    file has been processed) must be preferred when available."""
    py2_source = 'print "not valid py3"\nmathutils.clamp(5, 0, 10)\n'
    py3_output = 'print("valid py3 now")\nmathutils.clamp(5, 0, 10)\n'
    caller = FileUnit(path=Path("caller.py"), original_source=py2_source, deterministic_output=py3_output)

    evidence_without_fix = find_call_site_evidence({"clamp"}, [FileUnit(path=Path("c.py"), original_source=py2_source)])
    assert evidence_without_fix["clamp"] == []  # py2-only source can't be parsed, evidence lost

    evidence_with_output = find_call_site_evidence({"clamp"}, [caller])
    assert len(evidence_with_output["clamp"]) == 1


def test_find_call_site_evidence_no_match_for_unrelated_symbols():
    caller = FileUnit(path=Path("caller.py"), original_source="foo(1, 2)\n")
    evidence = find_call_site_evidence({"clamp"}, [caller])
    assert evidence["clamp"] == []
