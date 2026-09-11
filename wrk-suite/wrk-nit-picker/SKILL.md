---
name: wrk-nit-picker
description: >-
  Thorough, issue-grounded review of a complex PR, plus a separate final check
  that the PR adheres to repo contribution guidelines. Use when the user invokes
  wrk-nit-picker, asks for a nit-pick review, or wants findings split into
  must-apply vs out-of-scope nits. Not part of the wrk-e2e path/flow. Deliverable
  is an in-chat written report with a Need to apply Yes/No table and a
  contribution-guidelines section; when finished, ask if the user wants an HTML
  copy. Never push. Never open or comment on the PR unless the user separately
  asks.
argument-hint: "[PR url / owner/repo#N / issue+PR — optional]"
---

# WRK Nit Picker

You are doing a **deep review** of a complex PR. Reserved for hard cases — large
diffs, ambiguous scope, contested design, or when a normal `wrk-rev` pass is not
enough.

This skill is **not** part of the wrk-e2e path. Do **not** call
`ctl`, review gates, or gap-closer. Do **not** push, open a PR, or post review
comments on GitHub unless the user separately asks.

Be strict and honest. Ground every claim in the **issue requirements** and the
**actual diff**. Prefer surgical judgment over taste.

## Inputs

- Target: `$ARGUMENTS` (PR URL, `owner/repo#N`, or “PR for issue #N”).
- If empty: infer from open PR / current branch / ambient chat. Ask once only
  if still impossible.

Always resolve **both**:

1. The **issue** the PR claims to solve (body “Fixes/Closes”, linked issue, or
   user-stated issue).
2. The **PR diff** vs the PR base branch.

## Hard rules

- **Do not push.** Do not `gh pr create`, `gh pr review`, or comment on GitHub
  unless the user explicitly asks after the report.
- **Do not invent findings.** Every row needs a file/hunk or a quoted issue
  requirement (or an explicit “not found in diff”).
- **Scope is the issue.** “Nice for the codebase” is not “needed for this
  issue.” Style preference alone is never Need to apply = Yes.
- **No pipeline meta** in the report body (wrk-suite, remote, fork owner,
  agent branch names) unless the user asked for operator notes separately.
- Never print secrets / tokens / `.env` values.

## Workflow

Copy and track:

```
WRK Nit Picker
- [ ] 1. Resolve PR + linked issue + base branch
- [ ] 2. Load issue asks as a concrete checklist
- [ ] 3. Establish diff ground truth (stat + focused hunks)
- [ ] 4. Write the issue-grounded nit-pick review (prose)
- [ ] 5. Build the Need to apply table (every finding) — issue yardstick only
- [ ] 6. Final check: repo contribution guidelines (separate section)
- [ ] 7. Deliver in-chat report, then ask if they want HTML
```

### 1. Resolve targets

```bash
# Prefer gh. Example once PR is known:
gh pr view <PR> --json number,title,url,baseRefName,headRefName,body,files,commits,closingIssuesReferences
gh pr diff <PR>
gh issue view <ISSUE> --json number,title,body,labels,url
```

If GraphQL projects-classic errors block `gh`, use the REST API. Do not stall.

### 2. Issue checklist (ground truth of “needed”)

From the issue (and only what the PR is obligated to do), extract a short
checklist of **executable asks**: behavior to fix/add, API contract, tests,
docs the issue explicitly requires, and constraints the **issue** itself
imposes.

Mark each later as met / partial / missing in the review prose. That checklist
is the **only** yardstick for Need to apply = Yes.

### 3. Diff ground truth

- `gh pr diff` / `git diff <base>...HEAD` — file list + sizes.
- Open every non-trivial hunk that might be out of scope or incorrect.
- Note new files, renames, deleted tests, dependency bumps, generated churn.

If there is no diff, stop: “Nothing to review.”

### 4–5. Nit-pick review + Need to apply table

Do the deep, issue-grounded review and the findings table **first**. Contribution
guidelines are **not** the yardstick for Need to apply = Yes (except when the
issue itself cites a guideline ask). Do not dilute, shorten, or skip nit-pick
depth to make room for the guidelines check.

### 6. Final check — contribution guidelines (separate)

After the nit-pick review and findings table are complete, run a **separate**
pass against the repo’s contribution docs. This check is **not** part of the
nit-pick review and must **not** replace, merge into, or weaken it.

Read (when present): `CONTRIBUTING.md`, `CONTRIBUTING.*`, `.github/CONTRIBUTING*`,
PR template expectations, `AGENTS.md`, `CLAUDE.md`, and any linked style/test
docs those files point at.

Assess whether the PR is **up to par and adhering** to those guidelines for
this change set, for example:

- required tests / CI expectations called out in CONTRIBUTING
- commit / PR description conventions the repo enforces
- code style / lint / formatting rules that are documented as required
- CLA / DCO / license / docs update requirements
- “no unrelated changes” / process steps the docs mandate for contributors

Report this as its **own** report section (see structure below). Verdict options:

- **Up to par** — meets documented contribution requirements for this PR
- **Gaps** — list each gap with the quoted guideline + where the PR falls short
- **N/A / missing docs** — no contribution guide found; say so plainly

Do **not** fold guideline gaps into the Need to apply table unless the same
item is already a true issue-execution blocker (then it may appear in both
places with distinct Why text). Prefer keeping guideline findings only in the
contribution-guidelines section so the nit-pick table stays issue-pure.

## Deliverable: the report

Produce a **written report** (article-style Markdown) as the **agent reply** —
that in-chat message is the deliverable. Lead with the verdict, then support it.

Do **not** write a file by default (no mandatory `tmp/*.md` / HTML).

When the full in-chat report is finished (review + findings table + contribution
guidelines + bottom line), **ask the user** in one short question whether they
want an HTML version. Example: “Want an HTML copy of this report?”

- If **yes**: write `tmp/wrk-nit-picker-<owner>-<repo>-<pr>.html`, open it in the
  browser, and confirm the path.
- If **no** / no answer yet: stop. Do not build HTML unless they say yes.

### Required structure

1. **Title** — specific (`#`), not “Nit pick report”.
2. **Dek** — one or two italic lines: PR + issue + overall verdict.
3. **Lead** — what this PR is trying to do, how big the diff is, and whether it
   is ready / needs must-apply fixes / is overloaded with out-of-scope nits.
4. **Issue asks** — the checklist from step 2, each marked met / partial /
   missing with evidence (path or hunk).
5. **Review** — thorough prose sections as needed, for example:
   - Correctness vs the issue
   - Missing work the issue still requires
   - Risks (regressions, API breaks, flaky tests)
   - Scope creep and drive-bys
   - Tests / validation evidence actually present
   Do not dump an unstructured bullet salad; keep it readable.
6. **Findings table** — **required**. Every distinct finding is one row.
   Yardstick = issue execution only (see below).
7. **Contribution guidelines** — **required final check**, separate from the
   nit-pick review. Heading must be explicit (e.g. `## Contribution guidelines`).
   State **Up to par** / **Gaps** / **N/A**, then list adherence evidence or
   each gap with a quote from the guide. Do not bury this inside the findings
   table or skip it because the nit-pick table was long.
8. **Bottom line** — what to do next: apply the Yes rows only; ignore or defer
   No rows; then separately call out any contribution-guideline gaps that still
   need fixing before upstream would accept the PR.

### Findings table (required)

Use this exact column set:

| ID | Finding | Location | Need to apply | Why |
|---|---|---|---|---|
| F1 | … | `path` / hunk / “issue ask #n” | **Yes** or **No** | … |

Rules for **Need to apply**:

| Need to apply | When |
|---|---|
| **Yes** | Blocking or required for correct **execution of the work on the issue**: wrong/missing behavior the issue asked for, broken contract, missing test the issue explicitly requires, clear bug introduced by the PR, security/data-loss risk tied to the change. |
| **No** | Out-of-scope nit pick: preference, optional cleanup, unrelated refactor, naming taste, drive-by formatting, “while we’re here”, speculative future hardening, consistency with distant code the issue did not touch, or anything not needed to finish the issue’s asks. |

Contribution-guide process/style gaps belong in **Contribution guidelines**,
not as a way to inflate Need to apply = Yes.

For every **No** row, the **Why** cell must explain **why it is an out-of-scope
nit pick** — tie it back to the issue checklist (what the issue did *not*
require). For every **Yes** row, the **Why** cell must explain **why it is
needed for executing the issue work** — cite the ask or the failure mode.

Do not leave Why empty. Do not mark taste as Yes. Do not mark a real bug in
changed code as No just to be “surgical.”

Optional second summary counts above the table:

- Must apply (Yes): N
- Out-of-scope nits (No): N

### Empty findings

If the review finds nothing material, still ship the report with an empty table
stub and one row stating no actionable findings, Need to apply = No, Why =
“diff matches issue asks; no defects or scope violations found.”

## Voice

Direct, maintainer-grade, concrete. No flattery. No filler. Prefer paths and
issue quotes over adjectives.
