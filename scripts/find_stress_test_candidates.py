"""Dev-only stress-test candidate scout. Finds real Python 2 libraries worth
running ShiftCode against, and (optionally) extracts the pre-py3-support
state into a working directory - automates the git archaeology that finding
`docopt` and `python-slugify` required by hand this session (clone, search
history for a "python 3 support" commit, check size/test-style/dependencies).

Deliberately NOT an LLM agent and NOT part of the shipped `shiftcode` package
(see docs/stress-test-log.md and the README's Option A/B split): this is
read-only git/filesystem work, zero tokens, so token budget stays on the
actual product agents being stress-tested, not on candidate discovery.
This does not edit ShiftCode's own source and never will - see the
discussion in docs/bug-log.md about why an autonomous self-fixing loop is a
deliberately unbuilt, separate, higher-risk idea.

Usage:
    python3 scripts/find_stress_test_candidates.py                 # scout the seed list
    python3 scripts/find_stress_test_candidates.py --repo OWNER/NAME  # scout one repo
    python3 scripts/find_stress_test_candidates.py --extract OWNER/NAME --out DIR
"""

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Small, curated starter list - not autonomous GitHub crawling (deliberately
# bounded cost/blast-radius, per the Option A/B discussion). Add to this list
# by hand as good candidates are found; the scout does the mechanical work of
# checking each one.
SEED_CANDIDATES = [
    "docopt/docopt",
    "un33k/python-slugify",
    "jpvanhal/inflection",
    "gruns/furl",
    "mitsuhiko/click",
    "kennethreitz/tablib",
    "benoitc/gunicorn",
    "aaronsw/html2text",
]

PY3_COMMIT_MESSAGE_RE = re.compile(
    r"\b(python\s*3|py3|2to3|support python3|python3 support)\b", re.IGNORECASE
)


@dataclass
class ScoutResult:
    repo: str
    py3_commit: str | None = None
    py2_commit: str | None = None  # the commit immediately before py3_commit
    py_files: list[str] = field(default_factory=list)
    total_lines: int = 0
    has_unittest_style_tests: bool = False
    has_pytest_style_tests: bool = False
    external_imports: list[str] = field(default_factory=list)
    verdict: str = ""
    suitable: bool = False


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    return result.stdout


def _clone(repo: str, dest: Path) -> bool:
    url = f"https://github.com/{repo}.git"
    result = subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)], capture_output=True, text=True, timeout=120
    )
    return result.returncode == 0


def _find_py3_commit(repo_dir: Path) -> str | None:
    log = _run(["git", "log", "--oneline", "--all"], cwd=repo_dir)
    candidates = [line for line in log.splitlines() if PY3_COMMIT_MESSAGE_RE.search(line)]
    if not candidates:
        return None
    # oldest matching commit (closest to the real py2->py3 transition), not
    # later maintenance commits mentioning "python 3" in passing (dropping
    # old versions, adding new version support, etc.)
    return candidates[-1].split()[0]


_STDLIB_HINTS = {
    "os", "sys", "re", "io", "json", "time", "math", "random", "itertools",
    "functools", "collections", "contextlib", "types", "copy", "abc",
    "unittest", "argparse", "subprocess", "tempfile", "shutil", "glob",
    "string", "textwrap", "warnings", "traceback", "inspect", "ast",
    "getopt", "unicodedata", "htmlentitydefs", "urllib", "urllib2",
}


def _analyze_py2_state(repo_dir: Path, py3_commit: str) -> ScoutResult | None:
    py2_commit_result = _run(["git", "log", "--oneline", "-1", f"{py3_commit}^"], cwd=repo_dir)
    if not py2_commit_result.strip():
        return None
    py2_commit = py2_commit_result.split()[0]

    files = _run(["git", "ls-tree", "-r", "--name-only", py2_commit], cwd=repo_dir).splitlines()
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        return None

    total_lines = 0
    has_unittest = False
    has_pytest = False
    external_imports: set[str] = set()

    for f in py_files:
        content = _run(["git", "show", f"{py2_commit}:{f}"], cwd=repo_dir)
        total_lines += len(content.splitlines())
        if "test" in Path(f).name.lower():
            if "unittest.TestCase" in content or "unittest2.TestCase" in content:
                has_unittest = True
            if re.search(r"^def test_\w+\(", content, re.MULTILINE) and "unittest" not in content:
                has_pytest = True
        for match in re.finditer(r"^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)", content, re.MULTILINE):
            root = match.group(1).split(".")[0]
            if root not in _STDLIB_HINTS and root not in {"", "__future__"}:
                external_imports.add(root)

    return ScoutResult(
        repo="",  # filled by caller
        py3_commit=py3_commit,
        py2_commit=py2_commit,
        py_files=py_files,
        total_lines=total_lines,
        has_unittest_style_tests=has_unittest,
        has_pytest_style_tests=has_pytest,
        external_imports=sorted(external_imports),
    )


def scout(repo: str, work_dir: Path) -> ScoutResult:
    repo_dir = work_dir / repo.replace("/", "_")
    if not repo_dir.exists():
        if not _clone(repo, repo_dir):
            return ScoutResult(repo=repo, verdict="clone failed (repo may not exist)")

    py3_commit = _find_py3_commit(repo_dir)
    if py3_commit is None:
        return ScoutResult(repo=repo, verdict="no python-3-support commit found in history")

    analysis = _analyze_py2_state(repo_dir, py3_commit)
    if analysis is None:
        return ScoutResult(repo=repo, py3_commit=py3_commit, verdict="could not read pre-py3 state")

    analysis.repo = repo

    # Suitability heuristic: small enough to review/stress-test cheaply, has
    # SOME test suite (either style - both are useful, they exercise
    # different Mode A paths), not enormous external dependency surface.
    reasons = []
    if analysis.total_lines > 1500:
        reasons.append(f"large ({analysis.total_lines} lines) - expensive to stress-test")
    if not (analysis.has_unittest_style_tests or analysis.has_pytest_style_tests):
        reasons.append("no discoverable test suite")
    if len(analysis.external_imports) > 3:
        reasons.append(f"many external deps ({', '.join(analysis.external_imports)}) - sandbox won't have them installed")

    analysis.suitable = not reasons
    analysis.verdict = "suitable" if analysis.suitable else "; ".join(reasons)
    return analysis


def extract(repo: str, work_dir: Path, out_dir: Path) -> None:
    result = scout(repo, work_dir)
    if result.py2_commit is None:
        print(f"cannot extract {repo}: {result.verdict}", file=sys.stderr)
        sys.exit(1)

    repo_dir = work_dir / repo.replace("/", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in result.py_files:
        content = _run(["git", "show", f"{result.py2_commit}:{f}"], cwd=repo_dir)
        dest = out_dir / Path(f).name  # flatten - stress tests are single-directory
        dest.write_text(content)
    print(f"extracted {len(result.py_files)} files from {repo} @ {result.py2_commit} -> {out_dir}")


def _print_result(r: ScoutResult) -> None:
    print(f"\n{r.repo}")
    if r.py3_commit is None or r.py2_commit is None:
        print(f"  {r.verdict}")
        return
    print(f"  py2 state: {r.py2_commit}  (parent of py3-support commit {r.py3_commit})")
    print(f"  {len(r.py_files)} .py files, {r.total_lines} lines")
    print(f"  tests: unittest={r.has_unittest_style_tests} pytest={r.has_pytest_style_tests}")
    print(f"  external deps: {r.external_imports or '(none - stdlib only)'}")
    print(f"  verdict: {r.verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="scout a single repo (owner/name) instead of the seed list")
    parser.add_argument("--extract", metavar="OWNER/NAME", help="extract a repo's pre-py3 state")
    parser.add_argument("--out", type=Path, help="output directory for --extract")
    parser.add_argument(
        "--work-dir", type=Path, default=Path(tempfile.gettempdir()) / "shiftcode_stress_scout",
        help="where repos get cloned (reused across runs)",
    )
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    if args.extract:
        if not args.out:
            parser.error("--extract requires --out")
        extract(args.extract, args.work_dir, args.out)
        return

    repos = [args.repo] if args.repo else SEED_CANDIDATES
    results = [scout(repo, args.work_dir) for repo in repos]
    for r in results:
        _print_result(r)

    suitable = [r for r in results if r.suitable]
    print(f"\n{len(suitable)}/{len(results)} suitable: {', '.join(r.repo for r in suitable) or '(none)'}")


if __name__ == "__main__":
    main()
