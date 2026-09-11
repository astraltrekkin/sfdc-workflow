"""Hard-stop wrk-e2e when the checkout is behind upstream.

Used for local Cursor runs and remote VMs.

Phases:
  - ``begin``  — start of work (fresh tip / rebase work branch onto base)
  - ``recap``  — end of run before PR path (mergeability)

Also: ``ctl check-pr-base`` / ``ensure_pr_base_synced`` for wrk-pr / wrk-push.

Orchestrator syncs the GitHub fork via merge-upstream before launch; this
module is the in-checkout enforcement so neither path skips sync.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any, Optional

GITHUB_API = "https://api.github.com"

# Phases that must leave behind=0 (auto-sync attempted first).
SYNC_GATE_PHASES = frozenset({"begin", "recap"})

WORK_BRANCH_PREFIXES = ("cursor/", "claude/")


class ForkSyncError(RuntimeError):
    """Checkout / fork is behind upstream and could not be auto-synced."""


def _run(cmd: list[str], *, cwd: str) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def allow_behind_override() -> bool:
    """Operator escape hatch (default off)."""
    return (os.environ.get("WRK_ALLOW_BEHIND_UPSTREAM") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def recovery_commands(base: str, *, fork_hint: str = "OWNER/FORK") -> str:
    """Copy-pasteable recovery for conflict / still-behind hard-stops."""
    return (
        "STATUS: hard_stop — resolve sync, then retry.\n"
        "Recovery:\n"
        f"  1. GitHub UI: Sync fork on {fork_hint} (branch {base})\n"
        f"     or: gh api -X POST repos/{fork_hint}/merge-upstream -f branch={base}\n"
        f"  2. On base: git fetch upstream && git checkout {base} "
        f"&& git merge --ff-only upstream/{base}\n"
        f"  3. On work branch: git fetch upstream && git rebase upstream/{base}\n"
        "  4. Re-run: ctl gate begin|recap  or  ctl check-pr-base\n"
        "Override (discouraged): WRK_ALLOW_BEHIND_UPSTREAM=1"
    )


def parse_upstream_full_name(issue: str) -> Optional[str]:
    """Extract owner/repo from issue URL or owner/repo#n."""
    text = (issue or "").strip()
    if not text:
        return None
    m = re.search(
        r"github\.com[/:](?P<owner>[^/\s]+)/(?P<repo>[^/\s#]+)",
        text,
        re.I,
    )
    if m:
        return f"{m.group('owner')}/{m.group('repo').removesuffix('.git')}"
    m = re.match(
        r"(?P<owner>[^/\s]+)/(?P<repo>[^/\s#]+)#\d+",
        text,
    )
    if m:
        return f"{m.group('owner')}/{m.group('repo')}"
    return None


def _github_token() -> Optional[str]:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GH_PAT"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return None


def _remote_url(cwd: str, name: str) -> Optional[str]:
    code, out, _ = _run(["git", "remote", "get-url", name], cwd=cwd)
    if code != 0 or not out:
        return None
    return out


def _owner_repo_from_remote(url: str) -> Optional[str]:
    m = re.search(
        r"github\.com[/:](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)",
        url or "",
        re.I,
    )
    if not m:
        return None
    return f"{m.group('owner')}/{m.group('repo').removesuffix('.git')}"


def _ensure_upstream_remote(cwd: str, upstream_full_name: str) -> None:
    want = f"https://github.com/{upstream_full_name}.git"
    existing = _remote_url(cwd, "upstream")
    if existing:
        got = _owner_repo_from_remote(existing)
        if got and got.lower() == upstream_full_name.lower():
            return
        code, _, err = _run(
            ["git", "remote", "set-url", "upstream", want], cwd=cwd
        )
        if code != 0:
            raise ForkSyncError(f"Could not set upstream remote: {err or '?'}")
        return
    code, _, err = _run(["git", "remote", "add", "upstream", want], cwd=cwd)
    if code != 0:
        raise ForkSyncError(f"Could not add upstream remote: {err or '?'}")


def _resolve_base_branch(cwd: str) -> str:
    code, out, _ = _run(
        ["git", "symbolic-ref", "--quiet", "refs/remotes/upstream/HEAD"],
        cwd=cwd,
    )
    if code == 0 and out:
        return out.rsplit("/", 1)[-1]
    for candidate in ("main", "master", "dev", "develop"):
        code, _, _ = _run(
            ["git", "rev-parse", "--verify", f"upstream/{candidate}"],
            cwd=cwd,
        )
        if code == 0:
            return candidate
    raise ForkSyncError(
        "Could not resolve upstream default branch after fetch "
        "(tried upstream/HEAD, main, master, dev, develop)."
    )


def _behind_count(cwd: str, base: str) -> int:
    code, out, err = _run(
        ["git", "rev-list", "--count", f"HEAD..upstream/{base}"],
        cwd=cwd,
    )
    if code != 0:
        raise ForkSyncError(
            f"Could not measure behind vs upstream/{base}: {err or out or '?'}"
        )
    try:
        return int(out or "0")
    except ValueError as exc:
        raise ForkSyncError(f"Invalid behind count {out!r}") from exc


def _current_branch(cwd: str) -> str:
    code, out, _ = _run(["git", "branch", "--show-current"], cwd=cwd)
    return out if code == 0 else ""


def _is_work_branch(name: str) -> bool:
    return any((name or "").startswith(p) for p in WORK_BRANCH_PREFIXES)


def _merge_upstream_api(fork_full_name: str, branch: str, token: str) -> None:
    url = f"{GITHUB_API}/repos/{fork_full_name}/merge-upstream"
    body = json.dumps({"branch": branch}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 201):
                raise ForkSyncError(
                    f"merge-upstream HTTP {resp.status} for "
                    f"{fork_full_name}@{branch}\n"
                    + recovery_commands(branch, fork_hint=fork_full_name)
                )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code == 409:
            raise ForkSyncError(
                f"Fork sync conflict on {fork_full_name}@{branch}: {detail}\n"
                + recovery_commands(branch, fork_hint=fork_full_name)
            ) from exc
        raise ForkSyncError(
            f"merge-upstream failed ({exc.code}) for "
            f"{fork_full_name}@{branch}: {detail}\n"
            + recovery_commands(branch, fork_hint=fork_full_name)
        ) from exc


def ensure_checkout_synced_with_upstream(
    *,
    issue: str,
    cwd: Optional[str] = None,
    purpose: str = "begin",
) -> dict[str, Any]:
    """
    Fetch upstream, sync if behind, refuse if still behind.

    Prefers GitHub merge-upstream (when token + origin fork known), then
    refreshes the local checkout from origin/upstream.
    """
    if allow_behind_override():
        print(
            "  Fork sync: SKIPPED (WRK_ALLOW_BEHIND_UPSTREAM=1) — "
            "PR may be behind upstream"
        )
        return {
            "base": "?",
            "behind": -1,
            "upstream": parse_upstream_full_name(issue) or "?",
            "actions": ["override-skip"],
            "line": "base=? behind=? override=1",
        }

    root = cwd or os.getcwd()
    code, _, err = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root)
    if code != 0:
        raise ForkSyncError(
            f"Not a git checkout ({root}): {err or 'rev-parse failed'}"
        )

    upstream = parse_upstream_full_name(issue)
    if not upstream:
        raise ForkSyncError(
            "Cannot sync fork: issue ref missing owner/repo "
            f"(got {issue!r}). Use a GitHub issue URL or owner/repo#n."
        )

    _ensure_upstream_remote(root, upstream)
    code, _, err = _run(["git", "fetch", "upstream", "--prune"], cwd=root)
    if code != 0:
        raise ForkSyncError(f"git fetch upstream failed: {err or '?'}")

    base = _resolve_base_branch(root)
    behind = _behind_count(root, base)
    sync_actions: list[str] = []
    cur = _current_branch(root)
    fork_hint = "OWNER/FORK"
    origin_url = _remote_url(root, "origin")
    fork_name = _owner_repo_from_remote(origin_url or "") if origin_url else None
    if fork_name:
        fork_hint = fork_name

    if purpose == "begin" and _is_work_branch(cur) and behind > 0:
        sync_actions.append(
            f"note: on work branch {cur} behind upstream/{base} by {behind} "
            f"(prefer: checkout {base}, sync, then new branch)"
        )

    if behind > 0:
        token = _github_token()
        if fork_name and token:
            _merge_upstream_api(fork_name, base, token)
            sync_actions.append(f"merge-upstream {fork_name}@{base}")
            _run(["git", "fetch", "origin", "--prune"], cwd=root)
            if cur == base:
                code_m, _, err_m = _run(
                    ["git", "merge", "--ff-only", f"origin/{base}"],
                    cwd=root,
                )
                if code_m != 0:
                    code_m, _, err_m = _run(
                        ["git", "merge", "--ff-only", f"upstream/{base}"],
                        cwd=root,
                    )
                if code_m != 0:
                    raise ForkSyncError(
                        f"Synced GitHub fork but local {base} still stale: "
                        f"{err_m or '?'}\n"
                        + recovery_commands(base, fork_hint=fork_hint)
                    )
                sync_actions.append(f"ff-only onto {base}")
            else:
                code_r, _, err_r = _run(
                    ["git", "rebase", f"upstream/{base}"],
                    cwd=root,
                )
                if code_r != 0:
                    _run(["git", "rebase", "--abort"], cwd=root)
                    raise ForkSyncError(
                        f"Behind upstream/{base} by {behind} and rebase failed: "
                        f"{err_r or '?'}\n"
                        + recovery_commands(base, fork_hint=fork_hint)
                    )
                sync_actions.append(f"rebase onto upstream/{base}")
        else:
            if cur == base or not cur:
                code_m, _, err_m = _run(
                    ["git", "merge", "--ff-only", f"upstream/{base}"],
                    cwd=root,
                )
                if code_m != 0:
                    raise ForkSyncError(
                        f"Checkout is behind upstream/{base} by {behind} and "
                        f"auto-sync failed ({err_m or 'no ff-only'}). "
                        "Set GITHUB_TOKEN and Sync fork, or follow recovery.\n"
                        + recovery_commands(base, fork_hint=fork_hint)
                    )
                sync_actions.append(f"ff-only merge upstream/{base}")
            else:
                code_r, _, err_r = _run(
                    ["git", "rebase", f"upstream/{base}"],
                    cwd=root,
                )
                if code_r != 0:
                    _run(["git", "rebase", "--abort"], cwd=root)
                    raise ForkSyncError(
                        f"Behind upstream/{base} by {behind} and rebase failed "
                        f"(no token for Sync fork): {err_r or '?'}\n"
                        + recovery_commands(base, fork_hint=fork_hint)
                    )
                sync_actions.append(f"rebase onto upstream/{base}")

        behind = _behind_count(root, base)

    if behind > 0:
        raise ForkSyncError(
            f"Still behind upstream/{base} by {behind} after sync attempt.\n"
            + recovery_commands(base, fork_hint=fork_hint)
        )

    return {
        "base": base,
        "behind": behind,
        "upstream": upstream,
        "actions": sync_actions,
        "branch": cur,
        "line": f"base={base} behind={behind}",
    }


def ensure_pr_base_synced(
    *,
    issue: str,
    cwd: Optional[str] = None,
) -> dict[str, Any]:
    """Same sync for wrk-pr / wrk-push — must be behind=0 before open/push."""
    return ensure_checkout_synced_with_upstream(
        issue=issue, cwd=cwd, purpose="pr"
    )


def require_fork_sync_for_gate(
    state: dict[str, Any],
    phase: str,
    *,
    cwd: Optional[str] = None,
) -> Optional[str]:
    """Return error string if begin/recap cannot proceed; else None."""
    if phase not in SYNC_GATE_PHASES:
        return None
    label = "begin" if phase == "begin" else "recap"
    try:
        info = ensure_checkout_synced_with_upstream(
            issue=str(state.get("issue") or ""),
            cwd=cwd,
            purpose=phase,
        )
        print(
            f"  Fork sync OK ({label}): {info.get('line')} "
            f"upstream={info.get('upstream')} branch={info.get('branch') or '?'}"
        )
        if info.get("actions"):
            print(f"  Fork sync actions: {', '.join(info['actions'])}")
        return None
    except ForkSyncError as exc:
        return (
            f"Cannot gate {label}: fork/checkout not synced with upstream "
            f"(mergeability). {exc}"
        )
