"""Builds ShiftCode's two verification sandbox images (py2 + py3, each with
pytest pre-installed - see docker/*-sandbox.Dockerfile for why). Run this once
per machine; sandbox_runtime.py also calls the same build automatically the
first time an image is needed and isn't found locally, so running this by
hand is a convenience, not a required separate step.

Usage:
    python3 scripts/build_sandbox_images.py
    python3 scripts/build_sandbox_images.py --only py2
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

IMAGES = {
    "py2": ("shiftcode-py2-sandbox", REPO_ROOT / "docker" / "py2-sandbox.Dockerfile"),
    "py3": ("shiftcode-py3-sandbox", REPO_ROOT / "docker" / "py3-sandbox.Dockerfile"),
}


def image_exists(tag: str) -> bool:
    result = subprocess.run(["docker", "image", "inspect", tag], capture_output=True, timeout=10)
    return result.returncode == 0


def build_image(tag: str, dockerfile: Path, *, force: bool = False) -> bool:
    if not force and image_exists(tag):
        print(f"{tag}: already built (use --force to rebuild)")
        return True
    print(f"{tag}: building from {dockerfile.name}...")
    result = subprocess.run(
        ["docker", "build", "-t", tag, "-f", str(dockerfile), str(REPO_ROOT)],
        timeout=600,
    )
    if result.returncode != 0:
        print(f"{tag}: build failed", file=sys.stderr)
        return False
    print(f"{tag}: built")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["py2", "py3"], help="build just one image")
    parser.add_argument("--force", action="store_true", help="rebuild even if the image already exists")
    args = parser.parse_args()

    targets = [args.only] if args.only else list(IMAGES)
    ok = True
    for key in targets:
        tag, dockerfile = IMAGES[key]
        ok = build_image(tag, dockerfile, force=args.force) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
