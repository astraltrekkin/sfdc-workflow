#!/usr/bin/env python3
"""Gate tool calls during an active wrk-e2e run.

Cursor stdin: hooks JSON (tool_name / tool_input / command / file_path / ...)
Claude stdin: PreToolUse JSON (tool_name / tool_input)

Modes (argv[1]):
  cursor-pretool   — deny Write/StrReplace/Delete/... unless phase allows edits
  cursor-shell     — deny push / gh comment / pr create while active
  cursor-mcp       — deny GitHub comment/PR MCP tools while active
  claude-pretool   — Claude PreToolUse: edits + bash + MCP-ish via tool name

Resolves per-conversation state via conversation_id when present.
Denies (and allows of gated tool classes) are audited to
~/.cursor/wrk-e2e/audit.jsonl.

Exit 0 always after printing JSON decision (Cursor) or Claude deny JSON.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_store import load_state_for_hook  # noqa: E402
from telemetry import emit  # noqa: E402

EDIT_ALLOWED_PHASES = frozenset({"implement", "review"})
HOME = Path.home()
WRK_SUITE_ROOT = Path(__file__).resolve().parents[2]
ALWAYS_ALLOW_PATH_PREFIXES = (
    str(HOME / ".cursor" / "wrk-e2e"),
    str(HOME / ".cursor" / "skills"),
    str(HOME / ".cursor" / "commands"),
    str(HOME / ".cursor" / "hooks"),
    str(HOME / ".claude" / "skills"),
    str(HOME / ".claude" / "commands"),
    str(WRK_SUITE_ROOT),
)

EDIT_TOOLS = frozenset(
    {
        "Write",
        "StrReplace",
        "Delete",
        "EditNotebook",
        "Edit",
        "NotebookEdit",
        "create_or_update_file",
        "push_files",
        "write_file",
        "patch",
    }
)

# remote path may allow `git push` (branch only) via WRK_E2E_ALLOW_PUSH=1.
_BLOCKED_SHELL_CORE = r"""
      \bgh\s+pr\s+create\b
      | \bgh\s+pr\s+comment\b
      | \bgh\s+issue\s+comment\b
      | \bgh\s+api\s+.*\bcomments\b
      | \bgh\s+pr\s+review\b
"""
BLOCKED_SHELL_RE = re.compile(
    rf"""(?ix)
    (
      {_BLOCKED_SHELL_CORE}
      | \bgit\s+push\b
    )
    """
)
BLOCKED_SHELL_ALLOW_PUSH_RE = re.compile(
    rf"""(?ix)
    (
      {_BLOCKED_SHELL_CORE}
    )
    """
)

BLOCKED_MCP_TOOLS = frozenset(
    {
        "create_issue_comment",
        "add_issue_comment",
        "create_pull_request",
        "create_pull_request_review",
        "merge_pull_request",
        "update_issue",
        "push_files",
        "create_or_update_file",
    }
)

Denier = Callable[[str, str], None]


def path_allowed(path: str | None) -> bool:
    if not path:
        return False
    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError:
        resolved = str(Path(path).expanduser())
    return any(resolved.startswith(p) for p in ALWAYS_ALLOW_PATH_PREFIXES)


def cursor_allow(msg: str | None = None) -> None:
    out: dict[str, Any] = {"permission": "allow"}
    if msg:
        out["agent_message"] = msg
    print(json.dumps(out))


def cursor_deny(user: str, agent: str) -> None:
    print(
        json.dumps(
            {
                "permission": "deny",
                "user_message": user,
                "agent_message": agent,
            }
        )
    )


def claude_allow() -> None:
    print("{}")


def claude_deny(reason: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        "systemMessage": reason,
    }
    print(json.dumps(payload))
    sys.exit(2)


def extract_file_path(tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("path", "file_path", "target_notebook", "notebook_path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def extract_command(payload: dict[str, Any], tool_input: Any) -> str:
    if isinstance(payload.get("command"), str):
        return payload["command"]
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    return ""


def _audit_gate(
    state: dict[str, Any],
    *,
    kind: str,
    decision: str,
    tool: str | None = None,
    target: str | None = None,
    reason: str | None = None,
) -> None:
    emit(
        f"wrk_e2e.gate.{kind}",
        run_id=state.get("run_id"),
        decision=decision,
        phase=state.get("phase"),
        issue=state.get("issue"),
        path=state.get("path"),
        detail={"tool": tool, "target": target, "reason": reason},
        level="WARNING" if decision == "deny" else "DEFAULT",
    )


def gate_edits(state: dict[str, Any], file_path: str | None, denier: Denier, tool: str) -> bool:
    """Return True if denied (caller already emitted)."""
    if not state.get("active"):
        return False
    phase = state.get("phase")
    if phase in EDIT_ALLOWED_PHASES:
        return False
    if path_allowed(file_path):
        return False
    user = (
        f"wrk-e2e: edits blocked in phase '{phase}'. "
        f"Finish planning/repro, then advance to implement."
    )
    agent = (
        f"wrk-e2e hard gate: product edits are not allowed until phase is "
        f"implement or review (current: {phase}). "
        f"Complete the current phase with "
        f"`python3 <skill-root>/scripts/ctl.py gate {phase}` "
        f"(continuous) or HITL advance. Do not skip phases."
    )
    _audit_gate(
        state,
        kind="edit",
        decision="deny",
        tool=tool,
        target=file_path,
        reason=f"phase={phase}",
    )
    denier(user, agent)
    return True


def gate_shell(state: dict[str, Any], command: str, denier: Denier) -> bool:
    if not state.get("active"):
        return False
    allow_push = os.environ.get("WRK_E2E_ALLOW_PUSH", "").strip() in {"1", "true", "yes"}
    shell_re = BLOCKED_SHELL_ALLOW_PUSH_RE if allow_push else BLOCKED_SHELL_RE
    if not command or not shell_re.search(command):
        return False
    user = "wrk-e2e: push / GitHub comment / PR create blocked for this run."
    agent = (
        "wrk-e2e hard gate: do not open PRs or comment on GitHub"
        + ("" if allow_push else "; do not push")
        + ". Present the recap locally only. Clear state with ctl.py clear when done."
    )
    _audit_gate(
        state,
        kind="shell",
        decision="deny",
        tool="Shell",
        target=command[:500],
        reason="blocked_remote_write",
    )
    denier(user, agent)
    return True


def gate_mcp(state: dict[str, Any], tool_name: str, denier: Denier) -> bool:
    if not state.get("active"):
        return False
    bare = tool_name.split(":")[-1].rsplit("__", 1)[-1].strip() if tool_name else ""
    if bare not in BLOCKED_MCP_TOOLS and tool_name not in BLOCKED_MCP_TOOLS:
        return False
    user = "wrk-e2e: GitHub write/comment MCP blocked for this run."
    agent = (
        "wrk-e2e hard gate: no GitHub comments, PR creates, or remote file pushes "
        "during wrk-e2e. Recap locally only."
    )
    _audit_gate(
        state,
        kind="mcp",
        decision="deny",
        tool=tool_name,
        target=bare,
        reason="blocked_github_write",
    )
    denier(user, agent)
    return True


def handle_cursor_pretool(payload: dict[str, Any]) -> None:
    state = load_state_for_hook(payload)
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if tool_name in EDIT_TOOLS or tool_name.endswith("Write") or tool_name.endswith("StrReplace"):
        if gate_edits(state, extract_file_path(tool_input), cursor_deny, tool_name):
            return
    cursor_allow()


def handle_cursor_shell(payload: dict[str, Any]) -> None:
    state = load_state_for_hook(payload)
    tool_input = payload.get("tool_input") or {}
    command = extract_command(payload, tool_input)
    if gate_shell(state, command, cursor_deny):
        return
    cursor_allow()


def handle_cursor_mcp(payload: dict[str, Any]) -> None:
    state = load_state_for_hook(payload)
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    if gate_mcp(state, tool_name, cursor_deny):
        return
    cursor_allow()


def handle_claude_pretool(payload: dict[str, Any]) -> None:
    state = load_state_for_hook(payload)
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}

    def deny(user: str, agent: str) -> None:
        claude_deny(agent or user)

    if tool_name in ("Edit", "Write", "NotebookEdit"):
        if gate_edits(state, extract_file_path(tool_input), deny, tool_name):
            return
    if tool_name == "Bash":
        command = extract_command(payload, tool_input)
        if gate_shell(state, command, deny):
            return
    if "comment" in tool_name.lower() or tool_name.endswith("create_pull_request"):
        bare = tool_name.rsplit("__", 1)[-1]
        if gate_mcp(state, bare, deny):
            return
    claude_allow()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    handlers = {
        "cursor-pretool": handle_cursor_pretool,
        "cursor-shell": handle_cursor_shell,
        "cursor-mcp": handle_cursor_mcp,
        "claude-pretool": handle_claude_pretool,
    }
    handler = handlers.get(mode)
    if not handler:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        return 1
    try:
        handler(payload if isinstance(payload, dict) else {})
    except Exception:
        # Cursor failClosed: a traceback / empty stdout bricks Shell for the
        # whole chat (ctl never starts). Prefer allow over taking the session down.
        if mode.startswith("cursor-"):
            print(json.dumps({"permission": "allow"}))
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
