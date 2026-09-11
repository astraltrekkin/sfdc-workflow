---
name: wrk-begin
description: >-
  Triage an issue before any work begins. Use when the user
  mentions wrk-begin, wrk begin, or asks to triage/start a WRK issue.
argument-hint: "[issue number or url]"
---

**0. Rename this conversation first — before any other action.**
Do this immediately, even before fetching the issue, `$CTL start`, triage,
or any of the rules below.

- Extract the issue number from `$ARGUMENTS` / the issue URL / `#N` / bare
  digits. Title must be **digits only** (no `#`, no repo, no issue title).
  Example: `https://github.com/org/repo/issues/904320` → `904320`.
- Rename **this** conversation with the harness rename capability
  (`rename_chat`).
- If the title is already that issue number, skip. If it is already
  `{issue}/{pr}` (wrk-push form), **do not** smash it back to issue-only.
- If no number is available: ask once for the issue URL or number, rename,
  then proceed. Do not start triage until the title is the issue number.

**If this is a bug — you must reproduce it first.** No guessing. No speculative patches. Confirm the failure before any fix work. Reproduction must be on the surface(s) marked in step 2 — a backend-only / unit-path check does not replace a required Terminal, Desktop, Web, special-app, or VM repro when that surface is checked.

**If this is a feature / enhancement — you must detect every ask.** Go over the full issue (title, body, comments, and any linked design notes). Extract every distinct ask, requirement, acceptance criterion, and implied deliverable. Never defer an ask ("later", "out of scope for now", "nice to have we can skip") and never skip one. Every ask must be detected and explicitly marked for later work. Incomplete ask coverage means triage is not done.

**If this is a feature / enhancement — you must search the actual codebase** for whether the capability (or a close equivalent) already exists. Do not guess from memory or docs alone — grep/read the code. Then mark yes/no with an explanation. Incomplete existence check means triage is not done.

**Do not push** (`git push` to origin, fork, or upstream). **Do not** open a
PR or comment on GitHub. Triage is local. Finding no existing PR is not
permission to publish anything.

Triage an issue before any work begins. Answer, in order:

1. **What is this issue about?** — summarize the core ask in plain terms. State whether it is a **bug** or a **feature/enhancement**.
2. **Where does this show up?** — From the issue (title, body, comments, labels, screenshots), mark **every** surface where the problem is reported or must be verified. Check all that apply, then name the concrete product/host:

   - [ ] Terminal / CLI
   - [ ] Desktop app
   - [ ] Web / browser
   - [ ] Special app (name it below)
   - [ ] Virtual machine / remote environment (name it below)

   Then specify which (required — do not leave blank when a box is checked):

   - **Terminal / CLI:** e.g. the project's interactive CLI, a TUI, a specific subcommand
   - **Desktop app:** e.g. the project's desktop app
   - **Web / browser:** e.g. dashboard `/chat`, a docs site, a specific URL
   - **Special app:** e.g. Telegram / Discord / Slack gateway, VS Code / ACP, another named client
   - **Virtual machine / remote:** e.g. Docker, SSH backend, Modal, Daytona, a named VM host

   **Windows Desktop / Windows-only (wrk) — classify from the code, not the env box:**
   The issue's environment ("OS: Windows 10", "Measured on Windows") and kill-language
   ("Task Manager kill", "SIGKILL") only tell you where the reporter *was* — they are
   **not** evidence the bug is OS-bound and must **never** by themselves mark a Windows
   surface. Decide from the cited root-cause code:
   1. Locate the failing code the issue names (file:line/function), or grep the
      symptom/error string to find it.
   2. Grep that failing path for OS-binding markers: platform branches
      (`sys.platform=='win32'`, `os.name=='nt'`, `process.platform==='win32'`,
      `#ifdef _WIN32`); OS-only APIs/paths (`winreg`, `ctypes.windll`, `pywin32`,
      `msvcrt`, `.ps1`/`.bat`, `Scripts/` vs `bin/`, named pipes, Task Scheduler,
      `\\?\` long paths); OS-divergent behavior at the failure point (Windows
      file-locking, no `fork`, different signal semantics); or an OS-specific trace
      error (`WinError`).
   - **Marker on the failing path → intrinsic:** mark **Desktop app** and/or **Virtual
     machine / remote** and name the prepared GCP sandbox when available
     (`WRK_WINDOWS_GCP_INSTANCE`). Record it:
     `$CTL attest-windows-surface --reason intrinsic --evidence "<file:line + the OS
     marker found>"`. Do not claim Linux GUI repro satisfies Windows Desktop.
   - **Failing path is platform-neutral → incidental:** do **not** mark a Windows
     surface. Reproduce on the cheapest faithful surface (Terminal/CLI, backend,
     headless) on the Linux agent.
   - **Ambiguous / can't locate the code → cheap-repro-first:** attempt the cheapest
     faithful surface as a negative control. If it reproduces → incidental (done). If it
     demonstrably cannot → escalate, recording `$CTL attest-windows-surface --reason
     cheap-repro-failed --evidence "<what you ran + why it could not reproduce>"`.

   Windows work is **gated**: record `$CTL attest-windows-surface` before using a
   Windows host. Hard-stop if a required Windows env is missing.

   Rules:
   - Mark every surface the reporter used or that the bug/feature clearly targets. Multiple boxes may be checked.
   - If the issue does not say, infer from context (labels like `comp/desktop`, repro steps, screenshots) and state the inference. If still unclear, mark what you can and say what is unknown.
   - For **bugs**: later reproduce / fix work must exercise the checked surface(s). Skipping a checked surface (e.g. only hitting an API helper when Desktop is checked) means triage/repro is incomplete.
   - Incomplete surface identification means triage is not done.
3. **Feature asks (features only)** — If this is a feature/enhancement (not a bug), go over the issue and list **every** ask as an unchecked checklist item for later work. Rules:
   - Detect asks from the title, body, comments, and linked materials (acceptance criteria, "should / must / need", bullet lists, implied deliverables).
   - Mark each ask explicitly, e.g. `- [ ] Ask: <concrete deliverable>`.
   - Never defer any ask. Never skip any ask. Never collapse multiple asks into one vague line that drops detail.
   - If there are zero feature asks beyond the summary in step 1, say so explicitly (that should be rare).
   - Triage is incomplete until every ask is marked.
   - If this is a bug, write `N/A — bug; reproduce first` and continue.
4. **Does this capability already exist? (features only)** — If this is a feature/enhancement (not a bug), search the actual codebase (grep, file reads, related modules, config, docs in-repo) for the requested capability or a close equivalent. Answer with an explicit checkbox:

   - [ ] Yes — already exists (fully or substantially)
   - [ ] No — does not exist in the codebase

   Mark exactly one. Then explain:
   - What you searched (symbols, paths, commands, config keys).
   - What you found (or did not find), with concrete file/symbol references.
   - If **Yes**: whether it fully covers the asks from step 3, partially covers them (what is missing), or is a near-miss that should be extended instead of built from scratch.
   - If **No**: confirm you checked the obvious homes for this capability and found nothing.

   If this is a bug, write `N/A — bug; reproduce first` and continue. Incomplete codebase search means triage is not done.
5. **What parts of the product does it concern?** — name the affected components/subsystems/files.
6. **Were other PRs or issues mentioned?** — scan the issue body, comments, and pinned notes for any linked or mentioned issues/PRs (e.g. `#123`, "blocked by", "related to", "duplicate of", cross-repo links). Answer with an explicit checkbox:

   - [ ] Yes
   - [ ] No

   Mark exactly one. If **No**, say so and move on.

   If **Yes** — you MUST go through **each** mentioned issue/PR **entirely** before continuing triage. For every reference:
   - Fetch/open the full issue or PR (title, body, labels, status, and substantive comments — not a title-only skim).
   - Summarize what it is about and its current state (open/closed/merged, outcome).
   - Note the critical points of connectedness to the issue we want to work on — blocker, dependency, duplicate, shared surface area, prior attempt, or context that changes the approach.
   - Do not skip any reference. Incomplete coverage of mentioned issues/PRs means triage is not done.
7. **Does the issue contain any links?** — scan the issue body, comments, and attachments for URLs of any kind (docs, logs, screenshots, gists, Stack Overflow, blogs, CI runs, design notes, external repos, etc.). Every link must be opened/fetched and examined before triage is complete — use them for full understanding of the bug, expected behavior, repro steps, and prior discussion. Summarize what each link adds. If there are no links, say so explicitly.
8. **Is it assigned to anyone?** — check assignees, status, and comments for any indication someone is already on it.
9. **What labels are applied?** — list every label on the issue. For each one, explain what it means in this repo (check the repo's label descriptions, CONTRIBUTING, issue templates, or maintainer conventions — e.g. `bug` vs `enhancement`, priority, `good first issue`, area/component tags, status like `needs-repro` / `blocked`). Note how the labels should shape priority, scope, or approach. If none are applied, say so explicitly.

   **`needs-decision` (and cousins) on extension + feat:** soft product signal
   only — **not** a hard stop. When `$CTL` launch_source is `extension` and
   path is `feat`, do **not** refuse triage/implement because maintainers have
   not decided yet. Record the open questions, **choose a concrete default**,
   and continue with a scoped first milestone. Local/other remote bug
   path is unchanged.
10. **What env is needed?** — state the environment required to reproduce (bugs) or to validate/implement (features): OS, runtime/toolchain versions, install method, services, config, fixtures, and accounts. Justify against the issue (reporter’s env, CI matrix, docs, labels) and name which checked surface(s) from step 2 this env covers.

   **Desktop bug repro (mandatory when applicable):** If this is a **bug** and step 2 has **Desktop app** checked, the env MUST include launching the Desktop app and starting a real Desktop session. Reproduce only inside that session. A backend-only, unit-path, API-helper, or gateway-only check does **not** satisfy Desktop repro. Incomplete Desktop session repro means triage is not done.

   **Interface-ops → playbook/CU:** Complete step 13 (need from the issue path). Grok Bot / local Cursor only answer *who can run* computer-use — they do **not** decide that CU is needed. If `playbook_required` / `cu_required`, follow the live desktop app.

   Then answer **provider involvement** (near credentials — separate from the API-key checklist):

   **Is this issue relating to any provider?**
   - [ ] Yes
   - [ ] No

   Mark exactly one.

   If **Yes**:
   - Name **which** provider(s) from the issue (title/body/comments/labels such as
     `provider/*`, docs, code paths cited). Use the project’s own names
     (e.g. `openai`, `openai-codex`, `anthropic`, `discord`) — do **not** invent
     a canned provider menu.
   - One line each: how the issue touches that provider (API route, model,
     billing header, gateway adapter, etc.).
   - Incomplete provider naming means triage is not done.

   If **No**: say so explicitly (no provider-specific path / label / API surface).

   **Deterministic record (required before `$CTL gate begin`):**
   - `$CTL set-provider --none`   if **No**
   - `$CTL set-provider --provider NAME [--provider OTHER …]`   if **Yes**
     (repeat `--provider` for each named provider; names are opaque strings)
   - **If Yes — wallet check (hard-stop):** `$CTL check-provider-wallet`
     Live credits/balance for each named inference provider (OpenRouter + Nous
     have balance APIs; Anthropic uses a minimal Messages probe — no public USD
     balance endpoint; others fail closed as `unknown` until a checker exists).
     Messaging apps (`discord`, `slack`, …) are skipped — not wallets.
     - `funded` → continue
     - `top-up` or `unknown` → **hard-stop** (do not implement; do not call
       this `repro_failed`). Local: load missing keys from 1Password into env
       and re-run — never paste secrets in chat. Remote: keys come from injected
       `envVars` only (no 1Password on the VM).
   - `gate begin` / `gate plan` fail until provider involvement is recorded
     and (when Provider: Yes) wallets are checked and all funded.

   Then answer **live API call** — does proving this issue require a real call to a
   live external API/service?

   **Does this issue require a live API call?**
   - [ ] Yes — repro or validation cannot be proven without an actual request to a
     live external API/service, because the failing/target behavior lives in the
     real call (response shape, status/error code, rate limit, auth handshake,
     streaming, model output, webhook delivery, pagination, etc.)
   - [ ] No — there is **no external API in play at all**; the behavior is purely
     local (logic, parsing/formatting, config, types, CLI flags, docs) and is
     verified by exercising that real local code, not by standing in for any service

   Mark exactly one, and **explain** in one or two lines grounded in the issue:
   *which* call (endpoint / provider / operation) is involved — or, for **No**, why
   the behavior is entirely local with no external service anywhere in the path.

   **Mocking a live API is never acceptable.** A mock, stub, fixture, recorded
   response, or skipped call never substitutes for a real call. This is not a
   fallback of last resort — it is not an option. If an external API is anywhere in
   the path, this gate is **Yes** and the real call must be made.

   Consequences:
   - If **Yes**: repro (bugs) and validation-after-fix (bugs + feats) **must**
     include at least one real live call, cited as evidence (command + observed
     response/outcome — no secrets). Mocks/stubs/fixtures/skipped calls do **not**
     satisfy a Yes under any circumstance — it is a hard-stop later (this is what
     wrk-rev's "Was the API key used?" checks). If that live call needs a
     credential, the **required credentials** answer below must be **Yes** and name
     the env var(s); a missing credential is a hard-stop, not a licence to mock.
   - If **No**: verify against the real local behavior. Do not fabricate a live call
     to look thorough — and do not reclassify a real API surface as "No" to dodge
     the live call.

   Incomplete live-API assessment means triage is not done.

   Then answer **required credentials** (deterministic — not a provider menu):

   - [ ] Yes — a real API key / third-party credential is required for repro or validation
   - [ ] No — mocks, fixtures, offline, or keyless path is enough

   Mark exactly one. If **Yes**:
   - From the **issue + this repo’s docs/code** (env reference, provider config,
     `.env.example`, CONTRIBUTING), name every env var that must be present
     (e.g. whatever this project calls the key — do **not** pick from a canned
     provider list).
   - For each named var: `env present?` Yes/No (never print values) + one line
     what live call it is for.
   - If a named var is missing/empty → later work must hard-stop (mocks do not
     satisfy a required credential).
   - Ops note (only if those names appear): Discord bot/guild/channel ids may
     already be injected as `DISCORD_*` on remote runs.

   **Discord + credentials Yes (mandatory):** If step 2 has **Special app**
   checked and that app is **Discord**, **and** credentials above are **Yes**:
   - You **must** use the injected Discord env (`DISCORD_BOT_TOKEN` /
     `DISCORD_TOKEN`, `DISCORD_APPLICATION_ID`, `DISCORD_GUILD_ID`,
     `DISCORD_CHANNEL_ID`) to perform **live Discord actions** needed for this
     issue (send/read/react/join channel / exercise the failing path against
     the real bot+guild — whatever the issue requires).
   - Unit tests, mocks, fixtures, or `adapters=None` harnesses alone do **not**
     satisfy this. Live Discord is required for repro and for validation after
     the fix when the bug/feature is Discord-facing.
   - Record with:
     `$CTL set-required-env --require DISCORD_BOT_TOKEN --external-app discord`
     (ctl expands the canonical Discord env set). Before
     `$CTL gate reproduce` / `$CTL gate implement`, attest:
     `$CTL attest-live-use --app discord --evidence "…live action + outcome…"`
     (no secrets in evidence).

   **Deterministic record (required before `$CTL gate begin`):**
   - `$CTL set-required-env --none`   if **No**
   - `$CTL set-required-env --require ENV_NAME [--require OTHER …]`   if **Yes**
   - Add `--external-app discord` when Special app is Discord and credentials
     are Yes.
   - `gate begin` fails until this is recorded.
   - `gate reproduce` (bugs) and `gate implement` (bugs + feats) **fail** if any
     recorded env is missing/empty, or if Discord live-use was required but not
     attested.

   Incomplete credential assessment means triage is not done.
11. **Level of complexity** — estimate effort/risk (trivial / moderate / hard) with a one-line justification.
12. **How do you begin** — according to the project's CONTRIBUTING guidelines, lay out the first concrete steps (branch naming, tests, DCO/CLA, PR conventions, etc.). Note: a fork already exists in my own GitHub account, so skip fork creation — focus on cloning the fork, setting the `upstream` remote, syncing with upstream, and branching from there. **Local habit before work:** `git fetch upstream` → `git checkout <base>` → sync (`merge --ff-only upstream/<base>` or Sync fork) → then create the work branch. **`ctl gate begin` hard-requires** the checkout not behind upstream; **`ctl gate recap`** and **`ctl check-pr-base`** re-check before PR. Do not rely on prompt-only sync. For features, the first implementation work must cover the marked asks from step 3 — do not start by dropping any of them. If step 4 was **Yes**, begin by extending or wiring the existing capability rather than reimplementing it. For bugs, the first concrete step must include reproducing on every surface checked in step 2 **and** using every credential env named in step 10 (if Yes). Carry those env **names** into plan/repro.

13. **Interface-ops need + Grok Bot capability** — Decide **need** from the
   issue first, then record **capability** locks. Mark exactly one per question.

   **Need (from the issue — not from who is operating):**

   Does this issue’s described flow / repro path require **operating or
   navigating an interface**, rather than an API call / CLI / config / logs-only
   check?

   - [ ] Yes
   - [ ] No

   Mark exactly one. Then write one short **why** grounded in the issue text
   (quote the flow/repro/acceptance path). Rules:
   - Read the whole issue (title, body, comments, linked repro).
   - **Yes** = the path sounds like you must operate/navigate a UI to hit or
     prove it.
   - **No** = the path is API / CLI / config / code / logs — even if a Desktop
     product exists, and even if step 2 checked Desktop app.
   - Do **not** use a keyword bank. Do **not** answer Yes because the operator
     is Grok Bot.

   **Capability (host — does not create need):**

   **Operated from Grok Bot?**
   - [ ] Yes
   - [ ] No

   **Bug?** (must match step 1)
   - [ ] Yes
   - [ ] No

   **Desktop app surface?** (must match step 2 Desktop app — alignment only;
   not playbook need)
   - [ ] Yes
   - [ ] No

   Incomplete answers mean triage is not done.

   **Do not run the playbook in begin.** Begin only records need + locks.

   **`playbook_required` = interface-ops Yes + bug Yes + Grok Bot Yes.**

   Desktop Yes alone never turns the playbook on. Bot Yes alone never turns it on.

   **If `playbook_required` is No** — do **not** open Branch A of
   the live desktop app.

   **If `playbook_required` is Yes** — the **reproduce** phase MUST follow
   the live desktop app **Branch A** (Grok Bot +
   Peekaboo). Do not substitute a backend-only, unit-path, API-helper, or
   screenshot-only check.

   **Deterministic record (required before `$CTL gate begin`):**
   `$CTL set-grok-desktop --grok-bot yes|no --bug yes|no --desktop yes|no --interface-ops yes|no --interface-ops-why "…"`
   `gate begin` / `gate plan` fail until this is recorded.

   **Reproduce gate (only when `playbook_required`):**
   Follow the live desktop app Branch A, then
   `$CTL attest-mac-playbook --evidence "…live Mac desktop action + outcome…"`
   `gate reproduce` fails if the playbook was required and this attestation is missing.

15. **Cursor Desktop computer-use gates** — for **local Cursor** operators only.
   Answer all questions. Mark exactly one per Yes/No. Applies to **bugs and
   features**. Capability locks are host/surface; **need** is the same
   interface-ops judgment as step 13 (reuse that answer — do not invent a
   second story).

   **Interface-ops needed?** (must match step 13 need)
   - [ ] Yes
   - [ ] No

   **Desktop app surface?** (must match step 2 Desktop app — alignment only)
   - [ ] Yes
   - [ ] No

   **Windows?** (Windows surface or Windows host required for this work)
   - [ ] Yes
   - [ ] No

   **Local Cursor operator?** (this run is local Cursor — not remote, not
   the Grok Bot operator path in step 13)
   - [ ] Yes
   - [ ] No

   Incomplete answers mean triage is not done.

   **`cu_required` = interface-ops Yes + Windows No + Local Cursor Yes.**

   Desktop Yes alone never turns CU on.

   **Do not run computer-use in begin.** Begin only records the locks.

   **If `cu_required` is No** — do **not** open Branch B of
   the live desktop app.

   **If `cu_required` is Yes** — reproduce (bugs) and/or Desktop validation in
   implement (features) **MUST** follow
   the live desktop app **Branch B** (specialty
   Grok bot `f96438a3-f575-4ef2-86c8-4c6a8cf7a6e1`). **No freestyle** Desktop
   control (no substitute clicker / screenshot-only / backend-only proxy).

   **Deterministic record (required before `$CTL gate begin`):**
   `$CTL set-cursor-desktop-cu --desktop yes|no --windows yes|no --local-cursor yes|no --interface-ops yes|no --interface-ops-why "…"`
   `gate begin` / `gate plan` / `gate reproduce` / `gate implement` fail until
   this is recorded.

   **When `cu_required`:** follow the playbook, then
   `$CTL attest-cursor-desktop-cu --evidence "…live Desktop CU via specialty bot + outcome…"`
   `gate reproduce` and `gate implement` fail without that attestation.

16. **Work host** — answer in order. These are operator/host gates (where *this* run is executed), not issue labels.

   **remote?** (remote VM operator)
   - [ ] Yes
   - [ ] No

   If **Yes** — skip Local / Mac / folder checks. Record and continue.

   If **No** — continue:

   **Local?**
   - [ ] Yes
   - [ ] No

   **Mac?**
   - [ ] Yes
   - [ ] No

   **If Local + Mac:** report the current working directory (`pwd`). Work may run from **any** directory.

   **Deterministic record (required before `$CTL gate begin`):**
   - remote: `$CTL set-work-host --remote yes`
   - Otherwise: `$CTL set-work-host --remote no --local yes|no --mac yes|no`
     and when Local+Mac also `--cwd "$(pwd)"` (absolute path, optional).
   `gate begin` / `gate plan` fail until this is recorded.

