---
name: wrk-rev-com
description: Validate reviewer/maintainer claims on a PR or issue before acting on them
---

**Do not change code yet.** Reviewer/maintainer feedback is a set of claims to verify — not instructions to obey blindly. Validate first, then decide what (if anything) to change.

Given the PR/issue review comments in context, answer in order:

1. **Are you on the right branch?** — before validating anything, confirm the local checkout matches the PR under review (branch name, remote tracking, HEAD commit vs the PR’s head). If not, switch/sync to the correct branch first and say what you did. Do not proceed on the wrong branch.
2. **What claims did they make?** — extract every distinct claim from the reviewer/maintainer comments (technical facts, expected behavior, style/convention rules, requested changes, “this is wrong because…”, suggested alternatives). Number them. Quote or paraphrase tightly; do not merge separate claims into one.
3. **What is each claim about?** — for every claim: name the file/symbol/behavior/docs it targets, and whether it is about correctness, design, convention, performance, security, API surface, or process.
4. **Validate each claim** — for every claim, check it against the actual codebase, tests, docs, prior discussion, and runnable behavior where needed. Mark each as **confirmed**, **partially true**, **incorrect**, or **unclear**. Give evidence (paths, lines, commands, outputs). Do not speculate past what you verified.
5. **What should we do about it?** — for each claim, recommend one action: **accept & change**, **push back (with evidence)**, **ask a clarifying question**, or **no-op**. Keep the recommendation grounded in the validation result and the project’s norms (CONTRIBUTING, existing patterns).
6. **Reply draft (optional)** — if useful, sketch a short, respectful reply covering push-backs and clarifying questions only. Do not apologize for verified disagreements; cite evidence.

Stop here. Do **not** change code in this skill. Implementing accepted items is a separate, user-chosen step — never auto-apply after this validation.
