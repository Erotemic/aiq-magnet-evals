#!/bin/bash
set -euo pipefail
cd /app
git apply /solution/model.patch
mkdir -p /logs/agent
git diff > /logs/agent/model.patch
