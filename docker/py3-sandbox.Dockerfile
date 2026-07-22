# ShiftCode's py3 verification sandbox: bare python:3-slim plus pytest.
# Built once, offline - see py2-sandbox.Dockerfile for why this doesn't
# affect the --network none guarantee on actual verification runs.
#
# Build: docker build -t shiftcode-py3-sandbox -f docker/py3-sandbox.Dockerfile .
# Or use scripts/build_sandbox_images.py.
FROM python:3-slim

RUN pip install --no-cache-dir pytest
