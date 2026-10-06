#!/usr/bin/env bash
# Generic Harbor worker acceptance; benchmark-specific VM gates remain separate.
set -euo pipefail
cd "$(dirname "$0")/../.."
HARBOR_ENV=${HARBOR_ENV:-${AIQ_HARBOR_WORK:-/tmp/aiq-harbor-roadmap}/venv}
if [ ! -x "$HARBOR_ENV/bin/python" ]; then
    uv venv -q --python 3.12 "$HARBOR_ENV"
fi
uv pip install --python "$HARBOR_ENV/bin/python" \
    -c dev/environments/harbor-py312-constraints.txt -e '.[harbor,tests]'
export HARBOR_TELEMETRY=0
"$HARBOR_ENV/bin/python" -m pytest -q tests/native/test_harbor_native.py \
    tests/native/test_conformance.py -k harbor
