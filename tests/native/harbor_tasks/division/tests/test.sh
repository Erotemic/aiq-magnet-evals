#!/bin/bash
set -uo pipefail
cd /app
mkdir -p /logs/verifier
if [ -f /tmp/network-probe.py ]; then
    python /tmp/network-probe.py > /logs/verifier/network.json
fi
if python -m pytest -q test_calc.py > /logs/verifier/pytest.txt 2>&1; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
