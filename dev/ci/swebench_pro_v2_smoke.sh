#!/usr/bin/env bash
# No GPU: unchanged Pro task, oracle/NOP capture/replay, locked mini-SWE tools.
set -euo pipefail
cd "$(dirname "$0")/../.."
SWE_WORK=${AIQ_SWE_WORK:-/tmp/aiq-harbor-roadmap}
HARBOR_ENV=${HARBOR_ENV:-$SWE_WORK/venv}
SWE_PRO_DIR=${SWE_PRO_DIR:-$SWE_WORK/swe-pro}
PRO_REV=66f92766bba642462d4bbe5479e83f91f9211862
if [ ! -d "$SWE_PRO_DIR/.git" ]; then
    git clone https://github.com/scaleapi/SWE-bench_Pro-os.git "$SWE_PRO_DIR"
    git -C "$SWE_PRO_DIR" checkout --detach "$PRO_REV"
fi
if [ "$(git -C "$SWE_PRO_DIR" rev-parse HEAD)" != "$PRO_REV" ] || \
   [ -n "$(git -C "$SWE_PRO_DIR" status --porcelain --untracked-files=no)" ]; then
    echo 'Pro V2 checkout differs from the candidate immutable source' >&2
    exit 1
fi
if [ ! -x "$HARBOR_ENV/bin/python" ]; then
    uv venv -q --python 3.12 "$HARBOR_ENV"
fi
uv pip install --python "$HARBOR_ENV/bin/python" \
    -c dev/environments/harbor-py312-constraints.txt -e '.[harbor,tests]'
"$HARBOR_ENV/bin/python" - <<'PY'
import json
import subprocess
from pathlib import Path
pin = json.loads(Path('dev/environments/swebench-pro-smoke.json').read_text())
subprocess.run(['docker', 'pull', pin['image']], check=True)
subprocess.run(['docker', 'tag', pin['image'], pin['image'].split('@')[0]], check=True)
PY
export SWE_PRO_DIR
export HARBOR_TELEMETRY=0
export PYTHONPATH="$SWE_PRO_DIR/v2/tooling${PYTHONPATH:+:$PYTHONPATH}"
if [ -z "${AIQ_PRO_CAPTURE_DIR:-}" ]; then
    mkdir -p "$SWE_WORK/pro-acceptance-captures"
    AIQ_PRO_CAPTURE_DIR=$(mktemp -d "$SWE_WORK/pro-acceptance-captures/run-XXXXXXXX")
fi
export AIQ_PRO_CAPTURE_DIR
"$HARBOR_ENV/bin/python" -m pytest -q tests/native/test_swebench_pro.py
echo "Native Pro captures: $AIQ_PRO_CAPTURE_DIR"
