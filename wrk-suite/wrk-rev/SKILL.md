---
name: wrk-rev
description: Review an in-progress WRK contribution against its issue + the repo's contribution guidelines
argument-hint: "[issue/PR number or url — optional]"
---

You are reviewing the current work **before it is submitted**. Be a strict, honest reviewer — someone who will reject sloppy or out-of-scope PRs. Do not flatter. Ground every claim in the actual diff and the actual requirements; never assume work exists that you haven't verified.

**Do not push.** **Do not** `git push`, open a PR, or post on GitHub. Review is
local. Ready-to-submit does not mean publish.

## Inputs
- Target issue/PR: `$ARGUMENTS` (if empty, infer it from the branch name, recent commits, or ask the user once).

## Resolve paths (once per run)

```bash
WRK_ROOT="$(find . -path '*/.cursor/skills/wrk-e2e/scripts/ctl.py' 2>/dev/null | head -1 | xargs dirname | xargs dirname | xargs dirname | xargs dirname)"
SKILL_ROOT="$(find . -path '*/.cursor/skills/wrk-e2e/scripts/ctl.py' 2>/dev/null | head -1 | xargs dirname)"
if [ -z "$SKILL_ROOT" ] && [ -f "$HOME/.cursor/skills/wrk-e2e/scripts/ctl.py" ]; then
  SKILL_ROOT="$HOME/.cursor/skills/wrk-e2e"
fi
WRK_REV_GAP_CLOSER="${WRK_ROOT:-$HOME}/.cursor/skills/wrk-rev-gap-closer/SKILL.md"
REVIEW_GATE="python3 $SKILL_ROOT/scripts/review_gate.py"
CTL="python3 $SKILL_ROOT/scripts/ctl.py"
# Fall back to $HOME/.cursor/skills/wrk-rev-gap-closer/SKILL.md if missing
```

## Steps

1. **Establish ground truth of what changed.**
   - `git status --short` and `git diff --stat` against the base branch (find base via `git merge-base` with the default branch).
   - If the tree is clean and there are no commits ahead of base, STOP and report plainly: "No work has been done yet — nothing to review." Do not fabricate a review.

2. **Load the requirements.**
   - Fetch the issue/PR (`gh issue view` / `gh pr view`, or the REST API if GraphQL projects-classic errors block it). Extract the concrete asks as a checklist.
   - Read the repo's `CONTRIBUTING.md` (and `AGENTS.md` / `CLAUDE.md` if present).

3. **Answer these four questions, each with evidence (file:line, diff hunks, quoted guideline):**

   **A. Is the PR fully satisfied?**
   Map every requirement from the issue to where it's met in the diff. Mark each ✅ met / ⚠️ partial / ❌ missing. List anything the issue asked for that is not yet done.

   **A2. API key (from wrk-begin step 10 + issue/repo)**
   From begin’s credential assessment (or re-derive from the issue + repo docs if
   begin record is missing): was a real API key / credential required?

   **API key needed?**
   - [ ] Yes
   - [ ] No

   Mark exactly one.

   If **No**: say so and move on.

   If **Yes**:
   - List the env var **name(s)** that were required (never print values).
   - Then answer:

   **Was the API key used?**
   - [ ] Yes — used live for repro/validation (cite evidence: command, log line,
     provider call — no secrets)
   - [ ] No — required key was not used (mocks/fixtures/skipped only)

   Mark exactly one. If **No — not used** → **NEEDS WORK** (cannot READY).
   Missing/empty env when needed also → **NEEDS WORK**.

   **Discord Yes:** If begin had Special app Discord + credentials Yes, READY
   requires evidence of **live Discord** actions (and ctl `attest-live-use` when
   wrk-e2e ran). Mocks-only → **NEEDS WORK**.

   **A3. Specific model (from issue + begin/plan)**
   Did the issue (or begin/plan) require a **specific model** (exact id/name,
   e.g. a named catalog model, not “any LLM”)?

   **Specific model needed?**
   - [ ] Yes
   - [ ] No

   Mark exactly one.

   If **No**: say so and move on.

   If **Yes**:
   - Name the required model id/string from the issue/plan.
   - Then answer:

   **Was the specific model used?**
   - [ ] Yes — evidence shows that exact model was selected/exercised in
     repro/validation (cite config, CLI, log, or test — no secrets)
   - [ ] No — a different model was used, or model was never exercised

   Mark exactly one. If **No — not used** → **NEEDS WORK** (cannot READY).

   **B. Did we touch areas we didn't need to?**
   Flag any changed file/hunk not required by the issue: unrelated refactors, drive-by formatting, "cleanup" of nearby code, renamed symbols, churn in files outside scope. Quote the surgical-changes rule and call out each violation. Empty list = say so explicitly.

   **B2. New files**
   From ground truth (`git status --short` → `A`/`??`, untracked; and `git diff --diff-filter=A --name-only` vs base), answer with checkboxes — mark exactly one for each question:

   **Any new files added?**
   - [ ] Yes
   - [ ] No

   If **No**: say so and move on (do not invent files).

   If **Yes**: list every new path, then for **each** file answer:

   **Is it actually needed?**
   - [ ] Yes — needed
   - [ ] No — not needed

   Explain in a **grounded** way (evidence only):
   - What the issue/requirements actually demand that this file is supposed to cover.
   - What already exists in-repo that could cover the same need (existing test module, helper, openapi case, etc.) — cite path/symbol if you checked.
   - Whether the new file is load-bearing for the ask, or packaging/scaffolding (scratch, duplicate coverage, debug script, notes, backups, editor cruft, superseded copy after a move).
   - If **No — not needed**: say delete or merge-into-existing, and name the target.
   - If a file replaced an old one: confirm the old path was removed (no orphan).

   **C. Code review.**
   Correctness bugs, broken edge cases, behavioral regressions, and anything that contradicts how the surrounding code works. For refactors, verify behavior is preserved (and say how you verified — tests run, build run, eval compared; if you could NOT verify, say that). Note missing tests if the repo expects them.

   **D. Alignment with contribution guidelines.**
   Check the diff against CONTRIBUTING.md concretely: branch naming, commit-message convention, PR-focus rule, cross-platform rules, dependency/security policies, test requirements, and any project-specific "HARDLINE" standards. Cite the guideline line for each finding.

3b. **Machine-readable output (required).** After sections A–D, write `review.json` that matches those statuses:

```json
{
  "requirements": [
    {"id": "1", "summary": "…", "status": "met|partial|missing", "evidence": "…"}
  ],
  "issue_coverage": "complete|incomplete",
  "patch_readiness": "ready|needs_work",
  "verdict": "ready_to_submit|needs_work|not_started",
  "git_tree": "<git rev-parse HEAD^{tree} or write-tree id>",
  "closer_cycle": 0
}
```

Rules (enforced by Python — do not invent exceptions):

- Map ✅ → `met`, ⚠️ → `partial`, ❌ → `missing`.
- Any `partial`/`missing` → `issue_coverage: incomplete` and `verdict: needs_work`.
- `ready_to_submit` only when every requirement is `met` and `patch_readiness: ready`.
- Do not put softening language (`partial`, `scoped`, `incident patch`) in `verdict_note` / free-text fields.
- Set `closer_cycle` from the latest closer pass (0 on first review).

Then:

- `$REVIEW_GATE validate-review --file review.json` — **must exit 0**. If it fails, fix the JSON (and section A) until it passes. Never publish READY when validation fails.
- If wrk-e2e is active: `$CTL record-review --file review.json`.
- Human-readable sections A–D must match the JSON statuses.

4. **Verdict.** The headline must equal the JSON `verdict` with no extra qualifiers:

   - `ready_to_submit` → **READY TO SUBMIT**
   - `needs_work` → **NEEDS WORK** (ordered fix list)
   - `not_started` → **NOT STARTED**

   Forbidden: any “READY … partial/scoped/incident” phrasing. Python rejects those in `verdict_note`.

5. **After the verdict** (publish the full review + validated `review.json` first):

   - **READY TO SUBMIT** or **NOT STARTED**: stop. Do not invoke the closer.
   - **NEEDS WORK**:
     - If `closer_cycle` already equals `MAX_CLOSER_CYCLES` (4): stop. Report leftovers (failure — gaps should have been closed).
     - Else: immediately **Read and follow completely:** `$WRK_REV_GAP_CLOSER` with the same `$ARGUMENTS`.
     - The closer must close **every** open issue requirement (decide defaults, implement, run live). Only `blocked_env` (missing required secrets) may remain open. Push/PR/comments stay forbidden.
     - Do not ask the user. Do not type `/wrk-rev-gap-closer` (slash commands do not nest).
     - If this wrk-rev pass was invoked by the closer, still re-derive ground truth from git; do not assume prior gaps are fixed.

Keep it tight and evidence-led. No praise padding. If something is unverifiable in this environment (e.g. can't build), say so rather than guessing.
