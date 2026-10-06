#!/usr/bin/env bash
# Run only on a GPU host after a passing full VM report. No full benchmark.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${AIQ_GPU_ALIAS:?Set one managed infer-stack endpoint alias}"
: "${AIQ_VM_REPORT:?Set the passing full VM report.json path}"
SWE_WORK=${AIQ_SWE_WORK:-/tmp/aiq-harbor-roadmap}
INFER_STACK_BIN=${INFER_STACK_BIN:-infer-stack}
HARBOR_ENV=${HARBOR_ENV:-$SWE_WORK/venv}
VERIFIED_ENV=${VERIFIED_ENV:-$SWE_WORK/verified-worker}
SWE_PRO_DIR=${SWE_PRO_DIR:-$SWE_WORK/swe-pro}
INFER_STACK_DIR=${INFER_STACK_DIR:-$(dirname "$PWD")/infer_stack}
MAGNET_DIR=${MAGNET_DIR:-$(dirname "$PWD")/aiq-super-repo/submodules/aiq-magnet}
python3 - "$AIQ_VM_REPORT" "$PWD" "$INFER_STACK_DIR" "$MAGNET_DIR" <<'PY'
import json
import sys
from pathlib import Path
from dev.acceptance_support import source_digest
from dev.swebench_vm_checks import checks_pass
report = json.loads(Path(sys.argv[1]).read_text())
required = {'engine-free', 'harbor-phase0', 'harbor-conformance', 'verified',
            'pro-generation-replay', 'serving-provenance', 'magnet-fake-lease'}
assert report['status'] == 'PASS' and set(report['gates']) == required
assert all(value == 'PASS' for value in report['gates'].values())
assert checks_pass(report), 'required independent VM checks are missing or failed'
assert report['evals_source_sha256'] == source_digest(Path(sys.argv[2])), 'evaluation source changed since VM acceptance'
assert report['infer_stack_source_sha256'] == source_digest(Path(sys.argv[3]), ('infer_stack', 'tests/test_serving_provenance.py', 'pyproject.toml')), 'infer-stack source changed since VM acceptance'
assert report['magnet_source_sha256'] == source_digest(Path(sys.argv[4]), ('magnet', 'dev/ci', 'pyproject.toml')), 'MAGNET source changed since VM acceptance'
PY
mkdir -p "$SWE_WORK/gpu-acceptance"
GPU_WORK=$(mktemp -d "$SWE_WORK/gpu-acceptance/run-XXXXXXXX")
chmod 700 "$GPU_WORK"
CORE_ENV=${CORE_ENV:-$GPU_WORK/core}
if [ ! -x "$CORE_ENV/bin/python" ]; then
    uv venv -q --python 3.11 "$CORE_ENV"
    uv pip install -q --python "$CORE_ENV/bin/python" -e .
fi
catalog_args=()
if [ -n "${AIQ_INFER_CATALOG:-}" ]; then
    catalog_args=(--catalog "$AIQ_INFER_CATALOG")
fi
"$INFER_STACK_BIN" catalog endpoint provenance "$AIQ_GPU_ALIAS" "${catalog_args[@]}" >"$GPU_WORK/preflight.json"
python3 - "$GPU_WORK/preflight.json" <<'PY'
import json
import sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())['immutable'], 'pin model/image/configured serving inputs before GPU acceptance'
PY
LEASE_ENV="$GPU_WORK/lease.env"
released=0
release_owned() {
    if [ -f "$LEASE_ENV" ] && [ "$released" = 0 ]; then
        "$INFER_STACK_BIN" release --env-file "$LEASE_ENV" --yes --json >"$GPU_WORK/release.json"
        released=1
    fi
}
trap release_owned EXIT
"$INFER_STACK_BIN" acquire "$AIQ_GPU_ALIAS" "${catalog_args[@]}" \
    --env-file "$LEASE_ENV" --yes >"$GPU_WORK/acquire.log" 2>&1
source "$LEASE_ENV"
export PYTHONPATH="$SWE_PRO_DIR/v2/tooling${PYTHONPATH:+:$PYTHONPATH}"
export HARBOR_TELEMETRY=0
"$CORE_ENV/bin/python" dev/swebench_gpu_acceptance.py \
    --alias "$AIQ_GPU_ALIAS" --preflight "$GPU_WORK/preflight.json" \
    --descriptor "$INFER_STACK_ENDPOINT_DESCRIPTOR" --output "$GPU_WORK/evaluation" \
    --pro_root "$SWE_PRO_DIR" --harbor_python "$HARBOR_ENV/bin/python" \
    --verified_python "$VERIFIED_ENV/bin/python"
release_owned
"$INFER_STACK_BIN" leases --json >"$GPU_WORK/leases-after.json"
python3 - "$GPU_WORK" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
descriptor = json.loads((root / 'lease.env.json').read_text())
release = json.loads((root / 'release.json').read_text())
leases = json.loads((root / 'leases-after.json').read_text())
assert descriptor['lease_id'] in release['released'] and not release['publication_pending']
assert not any(row['id'] == descriptor['lease_id'] and row['state'] == 'active' for row in leases['leases'])
path = root / 'evaluation/result.json'
result = json.loads(path.read_text())
result['cleanup_verified'] = True
path.write_text(json.dumps(result, indent=2) + '\n')
PY
echo "GPU acceptance: PASS; $GPU_WORK/evaluation/result.json"
