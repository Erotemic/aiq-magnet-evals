#!/usr/bin/env bash
# Full CPU/Docker gate. A missing required integration is FAIL, never SKIP/PASS.
set -euo pipefail
cd "$(dirname "$0")/../.."
EVAL_ROOT=$PWD
SWE_WORK=${AIQ_SWE_WORK:-/tmp/aiq-harbor-roadmap}
INFER_STACK_DIR=${INFER_STACK_DIR:-$(dirname "$EVAL_ROOT")/infer_stack}
MAGNET_DIR=${MAGNET_DIR:-$(dirname "$EVAL_ROOT")/aiq-super-repo/submodules/aiq-magnet}
export AIQ_HARBOR_WORK="$SWE_WORK"
mkdir -p "$SWE_WORK/vm-acceptance"
REPORT_DIR=$(mktemp -d "$SWE_WORK/vm-acceptance/run-XXXXXXXX")
failed=0
run_gate() {
    local label=$1
    shift
    echo "Running $label"
    local status=PASS
    if ! env PYTEST_ADDOPTS="--junitxml=$REPORT_DIR/$label.xml" "$@" >"$REPORT_DIR/$label.log" 2>&1; then
        status=FAIL
    elif [ -f "$REPORT_DIR/$label.xml" ]; then
        if ! python3 - "$REPORT_DIR/$label.xml" "$label" <<'PY'
import sys
import xml.etree.ElementTree as ET
cases = list(ET.parse(sys.argv[1]).iter('testcase'))
assert cases and any(c.find('skipped') is None for c in cases), 'required gate executed no tests'
assert not any(c.find('failure') is not None or c.find('error') is not None for c in cases)
if sys.argv[2] != 'engine-free':
    assert not any(c.find('skipped') is not None for c in cases), 'required native check was skipped'
PY
        then
            status=FAIL
        fi
    else
        echo 'Required integration produced no JUnit evidence' >>"$REPORT_DIR/$label.log"
        status=FAIL
    fi
    printf '%s\t%s\n' "$label" "$status" >>"$REPORT_DIR/status.tsv"
    echo "$label: $status"
    if [ "$status" = FAIL ]; then
        failed=1
        tail -15 "$REPORT_DIR/$label.log"
    fi
}
run_gate engine-free dev/ci/engine_free.sh "$REPORT_DIR/core"
run_gate harbor-phase0 dev/ci/harbor_phase0.sh
run_gate harbor-conformance dev/ci/native_harbor.sh
run_gate verified dev/ci/swebench_verified_acceptance.sh
run_gate pro-generation-replay dev/ci/swebench_pro_v2_smoke.sh
if [ -f "$INFER_STACK_DIR/tests/test_serving_provenance.py" ]; then
    INFER_ENV=${INFER_ENV:-$REPORT_DIR/infer-stack}
    uv venv -q --python 3.14 "$INFER_ENV"
    uv pip install -q --python "$INFER_ENV/bin/python" -e "$INFER_STACK_DIR[tests]"
    run_gate serving-provenance env -u NO_COLOR TERM=xterm "$INFER_ENV/bin/python" \
        -m pytest -q "$INFER_STACK_DIR/tests/test_serving_provenance.py"
else
    run_gate serving-provenance bash -c 'echo "infer-stack serving provenance tests are absent" >&2; exit 1'
fi
if [ -x "$MAGNET_DIR/dev/ci/swebench_vm_acceptance.sh" ]; then
    run_gate magnet-fake-lease "$MAGNET_DIR/dev/ci/swebench_vm_acceptance.sh"
else
    run_gate magnet-fake-lease bash -c 'echo "MAGNET EvaluationNode integration checkout and VM acceptance hook are unavailable; see the roadmap integration-branch requirement" >&2; exit 1'
fi
python3 - "$REPORT_DIR" "$EVAL_ROOT" "$failed" "$INFER_STACK_DIR" "$MAGNET_DIR" <<'PY'
import json
import subprocess
import sys
from pathlib import Path
from dev.acceptance_support import source_digest
root = Path(sys.argv[1])
statuses = dict(line.split('\t') for line in (root / 'status.tsv').read_text().splitlines())
(root / 'report.json').write_text(json.dumps({
    'schema': 'aiq-magnet-evals-swebench-vm-acceptance/1',
    'status': 'PASS' if sys.argv[3] == '0' else 'FAIL', 'gates': statuses,
    'evals_commit': subprocess.check_output(['git', '-C', sys.argv[2], 'rev-parse', 'HEAD'], text=True).strip(),
    'evals_source_sha256': source_digest(Path(sys.argv[2])),
    'infer_stack_source_sha256': source_digest(Path(sys.argv[4]), ('infer_stack', 'tests/test_serving_provenance.py', 'pyproject.toml')),
    'magnet_source_sha256': source_digest(Path(sys.argv[5]), ('magnet', 'dev/ci', 'pyproject.toml')),
}, indent=2) + '\n')
PY
echo "VM acceptance report: $REPORT_DIR/report.json"
exit "$failed"
