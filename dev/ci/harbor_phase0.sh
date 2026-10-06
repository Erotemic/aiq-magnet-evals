#!/usr/bin/env bash
# Native Phase 0 probes only; this is not the full SWE-bench VM acceptance gate.
set -euo pipefail
cd "$(dirname "$0")/../.."
PROBE_ROOT=${AIQ_HARBOR_WORK:-/tmp/aiq-harbor-roadmap}
HARBOR_ENV=${HARBOR_ENV:-$PROBE_ROOT/venv}
SWE_PRO_REPO=${SWE_PRO_REPO:-$PROBE_ROOT/swe-pro}
PRO_REV=66f92766bba642462d4bbe5479e83f91f9211862
mkdir -p "$PROBE_ROOT"
if [ ! -d "$SWE_PRO_REPO/.git" ]; then
    git clone https://github.com/scaleapi/SWE-bench_Pro-os.git "$SWE_PRO_REPO"
    git -C "$SWE_PRO_REPO" checkout --detach "$PRO_REV"
fi
test "$(git -C "$SWE_PRO_REPO" rev-parse HEAD)" = "$PRO_REV"
test -z "$(git -C "$SWE_PRO_REPO" status --porcelain -- v2)"
(cd "$SWE_PRO_REPO/v2" && sha256sum -c SHA256SUMS --quiet)
if [ ! -x "$HARBOR_ENV/bin/python" ]; then
    uv venv -q --python 3.12 "$HARBOR_ENV"
fi
uv pip install --python "$HARBOR_ENV/bin/python" \
    -c dev/environments/harbor-py312-constraints.txt harbor==0.23.0 pytest kwconf
docker info --format 'Docker {{.ServerVersion}}'
export HARBOR_TELEMETRY=0 SWE_PRO_REPO
export AIQ_HARBOR_PROBE_DIR=${AIQ_HARBOR_PROBE_DIR:-$PROBE_ROOT/phase0-artifacts}
"$HARBOR_ENV/bin/python" -m pytest -q -s tests/native/test_harbor_phase0.py
