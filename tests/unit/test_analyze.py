from shiftcode.pipeline.analyze import find_lib2to3_findings, find_semantic_findings
from shiftcode.pipeline.transform.deterministic import deterministic_transform

PY2_SOURCE = '''def divide(a, b):
    result = a / b
    print "result:", result
    return result


def use_dict(d):
    for k, v in d.iteritems():
        print k, v


for i in xrange(3):
    print i
'''


def test_find_lib2to3_findings_detects_known_constructs():
    findings = find_lib2to3_findings(PY2_SOURCE)
    fixer_names = {f.fixer_name for f in findings}
    assert "fix_print" in fixer_names
    assert "fix_dict" in fixer_names
    assert "fix_xrange" in fixer_names
    assert all(not f.needs_llm for f in findings)


def test_find_semantic_findings_detects_ambiguous_division():
    deterministic_output = deterministic_transform(PY2_SOURCE)
    findings, slices = find_semantic_findings(deterministic_output)

    assert len(findings) == 1
    assert findings[0].construct_name == "ambiguous_division"
    assert findings[0].needs_llm is True

    assert len(slices) == 1
    assert slices[0].enclosing_function == "divide"


def test_find_semantic_findings_no_duplicates_for_nested_functions():
    source = "def outer():\n    def inner():\n        return 1 / 2\n    return inner()\n"
    findings, slices = find_semantic_findings(source)
    assert len(findings) == 1
    assert len(slices) == 1
    assert slices[0].enclosing_function == "inner"
