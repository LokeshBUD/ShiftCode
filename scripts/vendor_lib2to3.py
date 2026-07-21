"""Copy CPython's lib2to3 into shiftcode.vendor.lib2to3 and rewrite its internal
imports to be package-relative. lib2to3 was removed from the stdlib in Python 3.13
(deprecated since 3.9), so ShiftCode carries its own frozen copy rather than
depending on the interpreter it happens to run under.

Run once against a local Python install that still ships lib2to3 (3.9-3.12), e.g.:
    python3 scripts/vendor_lib2to3.py /path/to/lib2to3
"""

import re
import shutil
import sys
from pathlib import Path

DEST = Path(__file__).parent.parent / "src" / "shiftcode" / "vendor" / "lib2to3"

TOP_LEVEL_FILES = [
    "Grammar.txt",
    "PatternGrammar.txt",
    "btm_matcher.py",
    "btm_utils.py",
    "fixer_base.py",
    "fixer_util.py",
    "patcomp.py",
    "pygram.py",
    "pytree.py",
    "refactor.py",
]

IMPORT_RE = re.compile(r"^(\s*(?:from|import)\s+)lib2to3\b")

LICENSE_HEADER = '''"""Vendored from CPython's lib2to3 (PSF License, Python Software Foundation
Contributor Agreement). lib2to3 was removed from the stdlib in Python 3.13;
this is a frozen copy with internal imports rewritten to be package-relative.
Do not hand-edit; re-run scripts/vendor_lib2to3.py against a newer source if needed.
"""

'''


def rewrite_imports(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out = []
    for line in lines:
        out.append(IMPORT_RE.sub(r"\1shiftcode.vendor.lib2to3", line))
    return "".join(out)


def copy_and_rewrite(src_file: Path, dest_file: Path) -> None:
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    if src_file.suffix == ".py":
        text = src_file.read_text()
        text = rewrite_imports(text)
        dest_file.write_text(text)
    else:
        shutil.copy2(src_file, dest_file)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/lib2to3", file=sys.stderr)
        sys.exit(1)

    src = Path(sys.argv[1])
    if not src.is_dir():
        print(f"not a directory: {src}", file=sys.stderr)
        sys.exit(1)

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    (DEST / "__init__.py").write_text(LICENSE_HEADER)

    for name in TOP_LEVEL_FILES:
        copy_and_rewrite(src / name, DEST / name)

    for sub in ("fixes", "pgen2"):
        src_sub = src / sub
        dest_sub = DEST / sub
        for path in src_sub.rglob("*"):
            if path.is_dir():
                continue
            if path.suffix == ".pickle":
                continue
            rel = path.relative_to(src_sub)
            copy_and_rewrite(path, dest_sub / rel)

    print(f"vendored lib2to3 from {src} -> {DEST}")


if __name__ == "__main__":
    main()
