#!/usr/bin/env bash
# Engine-free CI: lint, the dependency-free suite, and proof that core imports
# and reads results with no evaluation engine installed.
# Usage: dev/ci/engine_free.sh [VENV_DIR]   (run from the repository root)
set -euo pipefail
VENV=${1:-${RUNNER_TEMP:-/tmp}/aiq-ci-core}
PY=${PYTHON_VERSION:-3.11}
uv venv -q --python "$PY" "$VENV"
uv pip install -q --python "$VENV/bin/python" -e '.[tests]' ruff
"$VENV/bin/python" - <<'PY'
import importlib.util
missing = [m for m in ('harbor', 'inspect_ai', 'olmo_eval', 'helm', 'magnet', 'kwdagger') if importlib.util.find_spec(m)]
assert not missing, f'engine-free environment has engines installed: {missing}'
import magnet_evals  # noqa: F401
PY
"$VENV/bin/ruff" check .
"$VENV/bin/python" -m pytest -q -m 'not native'
