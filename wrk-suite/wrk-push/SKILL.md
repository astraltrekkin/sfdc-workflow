---
name: wrk-push
description: >-
  Create and push a PR. Use when the user says wrk-push / wrk push.
  Never invent a second PR.
---

# WRK Push

- Use the title/body from wrk-pr.
- Before `git push` / `gh pr create`, the branch must not be behind upstream:

```bash
python3 "$HOME/.cursor/skills/wrk-e2e/scripts/ctl.py" check-pr-base --issue ISSUE_URL
```

If that exits non-zero (`STATUS: hard_stop`), do not push or open the PR —
rebase onto the upstream base first. Override only with
`WRK_ALLOW_BEHIND_UPSTREAM=1` (discouraged).

Then `git push` and `gh pr create`. Print the full PR URL as soon as it exists.

If a PR already exists for this work and its author is the configured fork
owner, you may push more commits onto that same head. Do not open a second PR.
