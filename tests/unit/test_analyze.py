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


def test_find_lib2to3_findings_degrades_gracefully_on_unparseable_source():
    """Regression from a real stress test (requests/__init__.py, no trailing
    newline): lib2to3's own parser raised a raw, uncaught ParseError here,
    crashing BEFORE deterministic_transform got a chance to hit the exact
    same failure through its own, already-correct DeterministicTransformError
    handling. Purely informational/best-effort (see docstring) - must degrade
    to an empty list, never crash, on anything lib2to3 can't parse."""
    unparseable = "import packages\nfrom .core import *"  # no trailing newline
    assert find_lib2to3_findings(unparseable) == []


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


def test_find_semantic_findings_detects_builtin_cmp_call():
    """First graduated detector from the self-improving fixer library
    (repair_history.py / suggest-fixer-rules): cmp() was a Python 2 builtin
    removed entirely in Python 3, no lib2to3 fixer exists for it, and a bare
    call raises NameError."""
    source = "def sort_key_compare(a, b):\n    return cmp(a.priority, b.priority)\n"
    findings, _ = find_semantic_findings(source)

    matches = [f for f in findings if f.construct_name == "builtin_cmp_call"]
    assert len(matches) == 1
    assert matches[0].needs_llm is True
    assert matches[0].line == 2
    assert "(a > b) - (a < b)" in matches[0].detail


def test_find_semantic_findings_ignores_unrelated_cmp_calls():
    source = "def f(cmp):\n    return cmp.compare(1, 2)\n\ndef g():\n    return cmp(1, 2, 3)\n"
    findings, _ = find_semantic_findings(source)
    assert not any(f.construct_name == "builtin_cmp_call" for f in findings)


def test_find_semantic_findings_detects_inspect_getargspec_call():
    """Regression from a real stress test (docs/bug-log.md #23): pytoolz/toolz's
    curried.py uses inspect.getargspec(f).args to inspect a function's arity -
    removed entirely in Python 3.11, no lib2to3 fixer exists for it."""
    source = "import inspect\n\ndef nargs(f):\n    return len(inspect.getargspec(f).args)\n"
    findings, _ = find_semantic_findings(source)

    matches = [f for f in findings if f.construct_name == "inspect_getargspec_call"]
    assert len(matches) == 1
    assert matches[0].needs_llm is True
    assert matches[0].line == 4
    assert "getfullargspec" in matches[0].detail


def test_find_semantic_findings_ignores_unrelated_getargspec_calls():
    source = "def f(x):\n    return x.getargspec()\n\ndef g():\n    return foo.getargspec(1)\n"
    findings, _ = find_semantic_findings(source)
    assert not any(f.construct_name == "inspect_getargspec_call" for f in findings)


def test_find_semantic_findings_detects_dunder_cmp_definition():
    """Regression from a real stress test (docs/bug-log.md #25): jek/blinker's
    _saferef.py defines __cmp__, which Python 3 silently never calls (no
    error) - a more dangerous case than bare cmp() calls."""
    source = "class Ref(object):\n    def __cmp__(self, other):\n        return cmp(self.key, other.key)\n"
    findings, _ = find_semantic_findings(source)

    matches = [f for f in findings if f.construct_name == "dunder_cmp_definition"]
    assert len(matches) == 1
    assert matches[0].needs_llm is True
    assert matches[0].line == 2
    assert "__eq__" in matches[0].detail
    assert "__hash__" in matches[0].detail


def test_find_semantic_findings_ignores_unrelated_method_definitions():
    source = "class Ref(object):\n    def __cmp2__(self, other):\n        return 0\n\n    def compare(self, other):\n        return 0\n"
    findings, _ = find_semantic_findings(source)
    assert not any(f.construct_name == "dunder_cmp_definition" for f in findings)


def test_find_semantic_findings_detects_pipes_module_import():
    """Regression from a real stress test (docs/bug-log.md #27):
    kislyuk/argcomplete's __init__.py imports 'pipes' as part of a
    multi-name import statement - removed in Python 3.13, no lib2to3
    fixer exists, and importing it crashes the whole module."""
    source = "import os, sys, pipes, shlex\n"
    findings, _ = find_semantic_findings(source)

    matches = [f for f in findings if f.construct_name == "pipes_module_import"]
    assert len(matches) == 1
    assert matches[0].needs_llm is True
    assert matches[0].line == 1
    assert "shlex.quote" in matches[0].detail


def test_find_semantic_findings_ignores_unrelated_imports():
    source = "import os, sys, shlex\nfrom pipes_utils import helper\n"
    findings, _ = find_semantic_findings(source)
    assert not any(f.construct_name == "pipes_module_import" for f in findings)
