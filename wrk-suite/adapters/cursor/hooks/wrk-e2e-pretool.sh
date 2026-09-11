#!/usr/bin/env bash
# preToolUse entrypoint for wrk-e2e — fail-open on crash (see wrk-e2e-shell.sh).
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
out="$(python3 "$GATE" cursor-pretool 2>/dev/null)"
status=$?
if [ "$status" -eq 0 ] && printf '%s' "$out" | python3 -c 'import sys,json; json.load(sys.stdin)' 2>/dev/null; then
  printf '%s\n' "$out"
  exit 0
fi
echo '{"permission":"allow"}'
exit 0
