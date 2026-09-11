#!/usr/bin/env bash
# beforeShellExecution entrypoint for wrk-e2e.
# Must always print one Cursor permission JSON and exit 0.
# A crash / bad JSON under failClosed bricks every later Shell in the chat
# (including ctl.py) — so this wrapper is fail-open on errors.
set +e
GATE=""
for c in \
  "$HOME/.cursor/skills/wrk-e2e/scripts/hook_gate.py" \
  "$HOME/.claude/skills/wrk-e2e/scripts/hook_gate.py"
do
  if [ -f "$c" ]; then
    GATE="$c"
    break
  fi
done
if [ -z "$GATE" ]; then
  echo '{"permission":"allow"}'
  exit 0
fi
out="$(python3 "$GATE" cursor-shell 2>/dev/null)"
status=$?
if [ "$status" -eq 0 ] && printf '%s' "$out" | python3 -c 'import sys,json; json.load(sys.stdin)' 2>/dev/null; then
  printf '%s\n' "$out"
  exit 0
fi
echo '{"permission":"allow"}'
exit 0
