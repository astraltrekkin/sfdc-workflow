---
name: wrk-ci
description: Investigate and fix a failing CI check on the issue's PR. Use when the user says wrk-ci, wrk ci, or asks to look at / fix the CI failure on a PR.
argument-hint: "[PR or issue number/url — optional]"
---

You are fixing **failing CI** on the pull request for the current WRK contribution. The PR has one or more red checks; your job is to find the real cause from the CI logs, reproduce it locally when feasible, and fix it in the working tree.

**Hard rules — do not violate:**
- **DON'T PUSH.** No `git push`, no `gh pr create`, no branch publish. The fix stays in the local working tree.
- **DON'T MAKE COMMENTS.** No `gh pr comment`, no `gh issue comment`, no review posts, no reactions — nothing written back to GitHub. Reading (`gh pr view`, `gh run view`, `gh api` GET) is fine; writing is not.

If the fix is only ready once verified, "verified" means you ran the same check CI runs and saw it pass (and saw it fail first — negative control). It does **not** mean publish.

## Inputs
- Target PR/issue: `$ARGUMENTS`. If empty, resolve it in this order:
  1. The PR for the current branch (`gh pr view --json number,headRefName,url,state`).
  2. If given an issue, find its linked PR (the issue's "linked pull requests", or `gh pr list --search "<issue-number> in:body"`, or the branch that references it).
  3. If still ambiguous, ask the user once for the PR number/URL.

## Steps

1. **Establish which checks are failing.**
   - `gh pr checks <PR> --watch=false` — list every check with its conclusion. Note which are `fail`/`failure`/`error`/`cancelled` vs `pass`/`skipped`.
   - If checks are still `pending`/`in_progress`, say so — don't diagnose a run that hasn't produced output yet. Offer to re-run the skill once it settles, or inspect the last completed run.
   - Record the failing check name(s) and their detail URLs.

2. **Pull the actual failure logs — never guess from the check name.**
   - Map the PR head to its run: `gh pr view <PR> --json headRefName` then `gh run list --branch <headRefName> --limit 5` to find the run id(s).
   - For each failing run: `gh run view <run-id> --log-failed` (falls back to `gh run view <run-id> --log` if `--log-failed` is empty). Read the failing job's output, not just the summary.
   - Identify the **exact failing step and command** (the line CI actually executed) and the **first** error in the log — not a downstream cascade. Quote the failing lines.

3. **Classify the failure.** State which one it is, with evidence from the log:
   - **Test failure** — an assertion/test the diff broke or that reveals a real bug.
   - **Lint / format / type check** — style, formatter, `ruff`/`eslint`/`mypy`/`tsc`, etc.
   - **Build / compile** error.
   - **Dependency / install / lockfile** mismatch.
   - **Config / workflow** issue (bad matrix, missing env, wrong version) — may not be your diff's fault.
   - **Flaky / infra / unrelated** — pre-existing failure on `main`, network, timeout, or a check unrelated to the change. If so, verify by checking whether the same check fails on the base branch (`gh run list --branch <default-branch>`), and say clearly it is not introduced by this PR.

4. **Reproduce locally (cheapest faithful path).**
   - Run the **same command CI ran**, from the failing step, in the local tree (e.g. the exact `pytest …`, `npm test`, `ruff check`, `tsc -p …`). Match the version where it matters.
   - Confirm you see the same failure locally = negative control. If it can't be reproduced locally (infra-only, OS-specific, secrets), say so explicitly and diagnose from the log alone rather than claiming a verified fix.

5. **Fix the root cause in the working tree.**
   - Surgical: touch only what the failure requires. Don't refactor unrelated code, don't reformat untouched files, don't "improve" nearby code. Keep the change scoped to making the red check green while preserving the PR's intended behavior.
   - If the correct fix would change the PR's intended behavior or is out of scope, stop and surface the tradeoff to the user instead of silently narrowing or bypassing the check (never delete/skip a test or loosen a lint rule to force green unless that is genuinely the right fix — and say so if you do).

6. **Verify.**
   - Re-run the same command locally and confirm it now passes.
   - Run any closely related checks the fix could affect (e.g. after a lint fix, re-run the test suite too) so you don't trade one red for another.
   - Report honestly what you ran, what passed, and what you could not verify in this environment.

7. **Report — no writes to GitHub.** Summarize:
   - Which check(s) were failing and the exact failing command.
   - Root cause (quote the log evidence).
   - The fix (files changed, why).
   - Verification: command run, before (fail) → after (pass), or what's unverifiable and why.
   - Leave the change in the working tree, uncommitted-or-committed per the repo's flow, but **not pushed** and with **no GitHub comment**. If the user wants it pushed or a PR updated, that's a separate, explicit step (e.g. wrk-push) — do not do it here.

Keep it tight and evidence-led. If CI is red for a reason outside this PR (flaky/infra/base-branch), say that plainly rather than inventing a fix.
