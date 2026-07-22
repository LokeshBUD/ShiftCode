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


def test_find_semantic_findings_detects_legacy_types_bare_import():
    """Regression from a real stress test (docs/bug-log.md #7): lib2to3's
    fix_types only rewrites `types.X` attribute access, never a bare name
    from `from types import X`, and never touches the import line either -
    left alone this raises ImportError under Python 3 with zero findings to
    prompt a fix."""
    source = "from types import UnicodeType\n\ndef f(x):\n    return type(x) == UnicodeType\n"
    findings, _ = find_semantic_findings(source)

    matches = [f for f in findings if f.construct_name == "legacy_types_import"]
    assert len(matches) == 1
    assert matches[0].needs_llm is True
    assert matches[0].line == 1
    assert "UnicodeType" in matches[0].detail
    assert "'str'" in matches[0].detail


def test_find_semantic_findings_ignores_unmapped_types_imports():
    source = "from types import ModuleType\n"
    findings, _ = find_semantic_findings(source)
    assert not any(f.construct_name == "legacy_types_import" for f in findings)


def test_find_semantic_findings_detects_normalize_encode_chain():
    """Regression from two independent real stress tests (docs/bug-log.md #8):
    python-slugify's slugify() and inflection's transliterate() both have
    unicodedata.normalize(...).encode('ascii', 'ignore') feeding into further
    str-only operations, which raises TypeError under Python 3 (bytes, not str)."""
    source = (
        "import unicodedata\n"
        "def transliterate(s):\n"
        "    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore')\n"
    )
    findings, _ = find_semantic_findings(source)

    matches = [f for f in findings if f.construct_name == "normalize_encode_bytes_result"]
    assert len(matches) == 1
    assert matches[0].needs_llm is True
    assert matches[0].line == 3
    assert "bytes" in matches[0].detail


def test_find_semantic_findings_ignores_unrelated_encode_calls():
    source = "def f(s):\n    return s.encode('utf-8')\n"
    findings, _ = find_semantic_findings(source)
    assert not any(f.construct_name == "normalize_encode_bytes_result" for f in findings)
