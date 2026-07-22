# ShiftCode's py2 verification sandbox: bare python:2.7 plus pytest, pinned
# to the last release line that still supports Python 2.7 (pytest 5.0
# dropped py2 support). Built once, offline - network access happens here,
# at image-build time, never during an actual verification run (those
# containers run with --network none, unaffected by this).
#
# Build: docker build -t shiftcode-py2-sandbox -f docker/py2-sandbox.Dockerfile .
# Or use scripts/build_sandbox_images.py, which sandbox_runtime.py also calls
# automatically the first time this image is needed and isn't found locally.
FROM python:2.7

RUN pip install --no-cache-dir "pytest==4.6.11"
