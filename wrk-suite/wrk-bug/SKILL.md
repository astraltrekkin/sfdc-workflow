---
name: wrk-bug
description: Plan how to reproduce a bug before fixing it
---

**Do not fix anything yet.** This command is for reproduction planning only. Confirm the failure exists before any patch work.

Given the bug issue (or description) in context, answer in order:

1. **What would be your approach reproducing this bug?** — lay out a concrete, ordered repro plan: setup, minimal steps to trigger the failure, what “broken” looks like (error, wrong output, UI state), and how you’ll know you’ve reproduced it. Prefer the smallest path that matches the reporter’s steps; call out anything missing from the issue that you’d need to fill in.

   The plan **must** exercise every surface checked in wrk-begin step 2 (**Where does this show up?** — Terminal / CLI, Desktop app, Web / browser, Special app, Virtual machine / remote). A backend-only or unit-path probe may support diagnosis, but it does **not** replace a required surface repro. If Desktop is checked, the plan must include the Desktop UI steps (or state why that surface is blocked).

   **Cheapest faithful surface first (cost-ordered):** reproduce on the cheapest surface that genuinely exercises the cited failure path before standing up an expensive one (GCP Windows VM, desktop GUI, browser, remote host). This does **not** override the rule above: when wrk-begin **correctly** marked a surface intrinsic to the bug, that surface is required and a cheaper proxy does not substitute. Cost-ordering only applies where the surface is *incidental or ambiguous* — there, attempt the cheap surface as a negative control; only its demonstrated failure to reproduce justifies escalating (and the GCP VM additionally requires `$CTL attest-windows-surface`).

   **Required credentials (carry forward):** Restate the env var **names** from wrk-begin step 10 (or `none`). The repro plan must use them live when named. If a required env is missing/empty → plan says hard-stop (no mocks for a required credential).

   **Discord Yes:** If Special app is Discord and credentials are Yes, the plan
   **must** include concrete live Discord steps using `DISCORD_*` env (not
   unit/mocks alone), then `$CTL attest-live-use --app discord` before gating repro.

   **Desktop CU:** If wrk-begin recorded `playbook_required` or `cu_required`, the
   **reproduce** phase must drive the live desktop app, then attest. **No freestyle.**
2. **What environment would you do it on and why?** — pick OS, runtime/language version, dependency versions, install method (source vs release), and any services/tools required. Justify each choice against the issue (reporter’s env, CI matrix, docs, labels). Note closest-match vs intentional differences. Explicitly name which checked surface(s) from wrk-begin step 2 this environment covers. Re-state required env names + `env present?` Yes/No. Then answer:

   - [ ] Yes — a real API key is required
   - [ ] No — a real API key is not required

   Mark exactly one. Must match wrk-begin step 10. Incomplete credential assessment means repro planning is not done.

   **No-mock-HTTP gate (hard, when API = Yes):** If the box above is **Yes**, the repro **must** hit the real API over a live HTTP layer using the named credential. It is **forbidden** to mock, stub, fake, intercept, or record/replay the HTTP layer or its routes — no `responses`/`requests-mock`/`httpretty`/`nock`/`msw`/`vcr`/cassettes, no monkeypatched client/transport, no fixture server standing in for the real endpoint. A repro built on any of these does **not** count as reproduced; escalate to the live call or declare the surface hard-blocked (missing/empty required env → hard-stop, per step 1). State explicitly in the plan that the HTTP layer is live and unmocked.
3. **What assumptions would you test?** — list the hidden assumptions in the report or your plan (defaults, config, data shape, timing, permissions, feature flags, platform-only behavior, version skew). For each, say how you’d verify or falsify it, and what a failed assumption would change about the repro.
