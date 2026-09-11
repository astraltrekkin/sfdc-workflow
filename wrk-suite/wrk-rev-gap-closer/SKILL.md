---
name: wrk-rev-gap-closer
description: >-
  Close every open wrk-rev issue requirement (partial/missing). Decide defaults,
  implement code, run live evidence — leave nothing open except missing required
  secrets or publish actions (push/PR/comments). Keep all closer edits on the
  same existing contribution commit (amend / unified dirty tree — never new
  closer commits). Re-run wrk-rev until READY or hard-blocked. Use after wrk-rev
  NEEDS WORK, or when the user says wrk-rev-gap-closer / close review gaps.
argument-hint: "[issue/PR number or url — optional]"
---

Close **every** open issue requirement from the latest `review.json`. Goal:
next wrk-rev has all requirements `met` and `verdict: ready_to_submit`.

**Only carve-outs (never “skip this issue ask”):**

- Do **not** `git push`
- Do **not** open a PR (`gh pr create`)
- Do **not** post GitHub issue/PR comments

**Commit unity (hard rule — major violation if broken):**

Gap-closer edits are **the same contribution**, not a follow-up commit series.

- Do **not** create a new commit for closer work (`git commit` that adds a
  second/third SHA for “gap closer”, “address review”, “fix remaining”, etc.).
- Keep changes on the **same commit that already holds the issue work** up to
  this point:
  - If that work is already one local commit → **amend** that commit
    (`git commit --amend --no-edit` or update the message only if it must
    reflect the fuller fix). Do not invent a parallel commit.
  - If the work is still uncommitted → leave it uncommitted (or amend only
    after the user/pipeline already established a single commit). Still no
    extra commits.
- One logical contribution = one commit (or one dirty tree) through review ↔
  closer loops. Closer cycles must not multiply commits.

Everything else the issue asks for — including `needs-decision` defaults and
live validation — **must** be closed in this loop.

## Inputs

- Target issue/PR: `$ARGUMENTS` (if empty, infer from branch, recent commits, or the last wrk-rev write-up).
- Source gaps: every requirement with status `partial` or `missing` in the latest validated `review.json`.

## Resolve paths (once per run)

```bash
WRK_ROOT="$(find . -path '*/.cursor/skills/wrk-e2e/scripts/ctl.py' 2>/dev/null | head -1 | xargs dirname | xargs dirname | xargs dirname | xargs dirname)"
SKILL_ROOT="$(find . -path '*/.cursor/skills/wrk-e2e/scripts/ctl.py' 2>/dev/null | head -1 | xargs dirname)"
if [ -z "$SKILL_ROOT" ] && [ -f "$HOME/.cursor/skills/wrk-e2e/scripts/ctl.py" ]; then
  SKILL_ROOT="$HOME/.cursor/skills/wrk-e2e"
  WRK_ROOT="${WRK_ROOT:-$HOME}"
fi
WRK_REV="${WRK_ROOT:-$HOME}/.cursor/commands/wrk-rev.md"
REVIEW_GATE="python3 $SKILL_ROOT/scripts/review_gate.py"
CTL="python3 $SKILL_ROOT/scripts/ctl.py"
```

## Cycle guard

Track **closer cycle N**:

- First closer after a review with `closer_cycle: 0` → **N = 1**
- Else **N = prior closer_cycle + 1**
- If **N > MAX_CLOSER_CYCLES** (4): stop and report leftovers (hard fail — should be rare; prefer closing earlier)

Print `Closer cycle: N` at the top of your report.

## Tags (how you close — not excuses to leave open)

| Tag | Meaning | Required result |
|-----|---------|-----------------|
| **implement** | Code / tests / docs change | `closed` when diff proves it |
| **decide_and_implement** | Issue needs a product default (`needs-decision`, missing numbers, etc.) | **Pick a concrete default**, implement it, document the choice in `note` + evidence → `closed` |
| **run_live** | Needs live run / real API / real surface | **Do the live work**, cite evidence (no secrets) → `closed` |
| **blocked_env** | Required credential env is missing/empty (ctl would hard-fail) | `open` only — unique allowed open tag |

**Forbidden:**

- Leaving an issue ask open because it is “policy,” “out of scope,” “partial is fine,” or “maintainer later”
- Marking `closed` without the corresponding code change and/or live evidence
- Treating push/PR as an issue requirement (those are never gaps to close)
- Creating **new** commits for closer passes (must amend / stay on the existing work commit or dirty tree)

## Steps

1. **Ingest** — List every `partial` / `missing` requirement. Preserve order. This list is the job.

2. **Classify** — One tag per gap from the table above. Default to `implement` or `decide_and_implement` / `run_live` as appropriate. Use `blocked_env` only when a required env name is missing/empty.

3. **Close them all**
   - **implement / decide_and_implement:** edit code/tests/docs; for decisions, choose explicit values, ship them, record “chose X because Y” in `note`.
   - **run_live:** perform the live validation the issue needs; write evidence strings (commands/outcomes, no secrets).
   - **blocked_env:** stop that gap only; say which env names are missing.
   - **Commits:** after code edits, fold into the **existing** contribution commit
     (amend) or keep the unified dirty tree. **Never** `git commit` a separate
     closer-only SHA.

4. **Trees** — Record `git_tree_before` / `git_tree_after`. If any implement / decide_and_implement closed with a code change, trees **must** differ (`implement_count` = count of those closed code tags). Tree change does **not** authorize a new commit.

5. **Write `closer.json`** — Every ingested gap appears in `gaps[]` with `requirement_id`, `tag`, `result`, `note`.

6. **Validate + record**
   - `$REVIEW_GATE validate-closer --file closer.json --review-file review.json` — exit 0 required
   - If wrk-e2e active: `$CTL record-closer --file closer.json`

7. **Re-review** — **Read and follow completely:** `$WRK_REV` (same `$ARGUMENTS`). Pass this closer report. Do not type `/wrk-rev`.
   - If new review is still `needs_work` and N < MAX and not solely `blocked_env`: wrk-rev step 5 must invoke this skill again.
   - If all requirements `met`: stop (READY path).

8. **Stop early only if** prior verdict was `not_started`, or N > MAX, or every remaining open gap is `blocked_env`.
