#!/usr/bin/env bash
# No GPU: pinned Verified oracle/NOP, retained patches, fresh official regrade.
set -euo pipefail
cd "$(dirname "$0")/../.."
SWE_WORK=${AIQ_SWE_WORK:-/tmp/aiq-harbor-roadmap}
VERIFIED_ENV=${VERIFIED_ENV:-$SWE_WORK/verified-worker}
INSPECT_EVALS_DIR=${INSPECT_EVALS_DIR:-$SWE_WORK/inspect-evals}
INSPECT_EVALS_REV=9080b5e9f1647ed14e45de8cb01e3d43411c0163
if [ ! -d "$INSPECT_EVALS_DIR/.git" ]; then
    git clone https://github.com/UKGovernmentBEIS/inspect_evals.git "$INSPECT_EVALS_DIR"
    git -C "$INSPECT_EVALS_DIR" checkout --detach "$INSPECT_EVALS_REV"
fi
if [ "$(git -C "$INSPECT_EVALS_DIR" rev-parse HEAD)" != "$INSPECT_EVALS_REV" ]; then
    echo 'Inspect-Evals checkout does not match the candidate revision' >&2
    exit 1
fi
if [ -n "$(git -C "$INSPECT_EVALS_DIR" status --porcelain --untracked-files=no)" ]; then
    echo 'Inspect-Evals checkout has tracked source changes' >&2
    exit 1
fi
if [ ! -x "$VERIFIED_ENV/bin/python" ]; then
    uv venv -q --python 3.12 "$VERIFIED_ENV"
fi
uv pip install --python "$VERIFIED_ENV/bin/python" \
    -c dev/environments/swebench-verified-py312-constraints.txt \
    -e '.[inspect,tests]' "$INSPECT_EVALS_DIR[swe_bench]" 'swebench==3.0.15'
"$VERIFIED_ENV/bin/python" - <<'PY'
import json
import subprocess
from pathlib import Path
images = json.loads(Path('dev/environments/swebench-verified-images.json').read_text())
for instance, image in images.items():
    print(f'Preparing pinned Verified image: {instance}', flush=True)
    subprocess.run(['docker', 'pull', image], check=True)
PY
if [ -z "${AIQ_VERIFIED_CAPTURE_DIR:-}" ]; then
    mkdir -p "$SWE_WORK/verified-acceptance-captures"
    AIQ_VERIFIED_CAPTURE_DIR=$(mktemp -d "$SWE_WORK/verified-acceptance-captures/run-XXXXXXXX")
fi
export AIQ_VERIFIED_CAPTURE_DIR
"$VERIFIED_ENV/bin/python" -m pytest -q tests/native/test_swebench_verified.py
echo "Native Verified captures: $AIQ_VERIFIED_CAPTURE_DIR"
