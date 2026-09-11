#!/usr/bin/env bash
set -euo pipefail
SELF="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${BASH_SOURCE[0]}")"
SUITE_ROOT="$(cd "$(dirname "$SELF")/../../.." && pwd)"
exec python3 "$SUITE_ROOT/wrk-e2e/scripts/hook_gate.py" claude-pretool
