---
name: wrk-feat
description: Plan how to approach a feature before implementing it
---

**Do not implement yet.** This command is for scoping and prep only. Understand the feature, the repo’s constraints, and your readiness before writing code.

**Extension remote + feat:** if launch_source is `extension`, labels like
`needs-decision` / “awaiting maintainer decision” are **not** plan blockers and
must **not** become a later hard stop. In step 1, turn open questions into
**chosen defaults** for a scoped first milestone (document them). Do not stop
the chain waiting for maintainers.

## Spec gates (set FIRST — they bind the rest of the build)

This is a **build** in the `-feat` path, so lock these gates before any planning.
Carry forward the answers **wrk-begin** recorded (`$CTL set-provider` /
`$CTL set-required-env`); if wrk-feat is run standalone without begin, derive each
from the **issue + this repo’s docs/code** and answer it here. Mark **exactly one**
box per gate. These answers are binding: they dictate what the plan (steps 1–3),
the implementation, and the validation-after-implement must do — and they are what
**wrk-rev** enforces downstream ("Was the API key used?").

**Gate 1 — Provider involved?**
- [ ] Yes — name **which** provider(s) using the project’s own names (`openai`,
  `anthropic`, `discord`, …); one line each on how the feature touches it (API
  route, model, billing header, gateway adapter, …).
- [ ] No — no provider-specific path / label / API surface.

**Gate 2 — API key / credential required?**
- [ ] Yes — a real API key / third-party credential is required to validate the
  feature. Name **every** env var that must be present (from the issue + repo
  `.env.example` / config / CONTRIBUTING — do **not** pick from a canned provider
  list). For each: `env present?` Yes/No (never print values) + one line on what
  live call it is for. A named var missing/empty → **hard-stop** later.
- [ ] No — keyless / offline / local path is enough.

**Gate 3 — Live API call required?**
- [ ] Yes — validating this feature cannot be proven without an actual request to a
  live external API/service (the target behavior lives in the real call — response
  shape, status/error code, auth handshake, streaming, model output, webhook, …).
- [ ] No — no external API in play at all; behavior is purely local and is verified
  by exercising the real local code, not by standing in for any service.

**Mocking a live API is never acceptable.** A mock, stub, fixture, recorded
response, or skipped call never substitutes for a real call — it is not a fallback
of last resort, it is not an option. If an external API is anywhere in the path,
Gate 3 is **Yes** and the real call must be made.

**How the gates bind the build:**
- **Provider = Yes** → the plan (steps 1–2) must follow that provider’s real
  API/adapter conventions and existing code paths; validation exercises that
  provider’s real surface, not a generic stand-in.
- **API key = Yes** → the **No-mock-HTTP gate** below is in force; every live
  validation uses the named env; missing/empty required env is a **hard-stop**
  (never a licence to mock).
- **Live API call = Yes** → validation-after-implement **must** include at least
  one real live call, cited as evidence (command + observed response/outcome — no
  secrets). Mocks/stubs/fixtures/skipped calls do **not** satisfy a Yes under any
  circumstance.
- **All three No** → validate against the real **local** behavior. Do not fabricate
  a live call to look thorough, and do not reclassify a real API/provider surface as
  "No" to dodge the live call.

Incomplete spec-gate assessment means the feature is not ready to build.

**Cursor Desktop CU:** If wrk-begin recorded `cu_required: YES`, Desktop
validation during implement must drive the live desktop app — **no freestyle**.
Attestation is enforced at `$CTL gate implement`.

Given the feature issue (or description) in context, answer in order:

1. **What do we need to consider to work on this feature?** — list the constraints and decisions that matter before coding: intended behavior and non-goals, affected APIs/UX/surfaces, backwards compatibility, edge cases, existing patterns to follow or extend, tests/docs expected by the project, performance/security implications, and any open questions that would block a correct design. Ground this in the issue, linked discussion, and the codebase — not guesses.

   **Required credentials:** use the env var **names** locked in **Gate 2** above (or `none`). Live validation must use them when named; missing env → hard-stop.

   **No-mock-HTTP gate (hard, when a real API is required):** If any credential env is named above (i.e. a real API key is required), all live validation of this feature **must** hit the real API over a live HTTP layer using the named credential. It is **forbidden** to mock, stub, fake, intercept, or record/replay the HTTP layer or its routes — no `responses`/`requests-mock`/`httpretty`/`nock`/`msw`/`vcr`/cassettes, no monkeypatched client/transport, no fixture server standing in for the real endpoint. Validation built on any of these does **not** count as validated; escalate to the live call or declare the surface hard-blocked (missing/empty required env → hard-stop). State explicitly in the plan that the HTTP layer is live and unmocked.
2. **What will we use?** — name the concrete pieces we’ll rely on: existing modules/APIs/helpers, libraries already in the project, CLI/config surfaces, fixtures or test harnesses, docs/examples to mirror, and any tools required for local work. Prefer reuse over new abstractions; call out only what is actually needed for this feature. Include carried credential env **names** (never values).
3. **What will we check beforehand to make sure we have the grasp we need?** — define a short readiness checklist: read the relevant code paths and CONTRIBUTING/style norms, confirm how similar features were done, verify setup/build/test works locally, note version or platform assumptions, confirm each carried env is present (`env present?` Yes/No), and identify the smallest spike or mental model test that would prove we understand the surface. Stop when the checklist would catch a wrong approach early.
