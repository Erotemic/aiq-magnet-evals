#!/usr/bin/env bash
set -euo pipefail
exec "$(dirname "$0")/swebench_verified_acceptance.sh" "$@"
