"""Deterministic required-credential recording + env presence for wrk-e2e.

Provider menus are not the source of truth. During begin the agent names the
env var(s) the issue/repo actually needs, records them with
``ctl.py set-required-env``, and gates refuse reproduce/implement when those
vars are missing/empty.

When credentials are **Yes** and the external/special app is **Discord**, the
agent must also:
  - require Discord env names (bot/guild/channel),
  - perform live Discord actions for repro/validation (not mocks),
  - ``ctl.py attest-live-use --app discord --evidence …`` before
    ``gate reproduce`` / ``gate implement``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Optional

# --------------------------------------------------------------------------------------
# Discord — canonical env when external app is Discord + credentials Yes
# --------------------------------------------------------------------------------------
DISCORD_EXTERNAL_APP = "discord"

# Prefer DISCORD_BOT_TOKEN; DISCORD_TOKEN is an accepted alias for presence checks.
DISCORD_TOKEN_ALIASES: tuple[str, ...] = ("DISCORD_BOT_TOKEN", "DISCORD_TOKEN")

DISCORD_CANONICAL_ENV: tuple[str, ...] = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_APPLICATION_ID",
    "DISCORD_GUILD_ID",
    "DISCORD_CHANNEL_ID",
)

# Any of these in required_env implies Discord live-use rules apply.
_DISCORD_ENV_MARKERS: frozenset[str] = frozenset(
    {
        *DISCORD_CANONICAL_ENV,
        "DISCORD_TOKEN",
        "DISCORD_INVITE_URL",
    }
)


def env_present(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def discord_token_present() -> bool:
    return any(env_present(n) for n in DISCORD_TOKEN_ALIASES)


def normalize_external_app(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = str(name).strip().lower()
    if not n:
        return None
    if n in ("discord", "discord.py", "discord-bot", "discord_bot"):
        return DISCORD_EXTERNAL_APP
    return n


def expand_discord_required_env(require_env: Iterable[str]) -> list[str]:
    """Ensure Discord Yes runs record the canonical Discord env names."""
    required: list[str] = []
    for name in require_env:
        n = (name or "").strip()
        if n and n not in required:
            required.append(n)
    for n in DISCORD_CANONICAL_ENV:
        if n not in required:
            required.append(n)
    # Drop redundant DISCORD_TOKEN if BOT_TOKEN is listed (alias handled at check).
    if "DISCORD_BOT_TOKEN" in required and "DISCORD_TOKEN" in required:
        required = [n for n in required if n != "DISCORD_TOKEN"]
    return required


def build_required_env_record(
    *,
    none: bool = False,
    require_env: Optional[Iterable[str]] = None,
    external_app: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build state.integrations payload (legacy key name kept for compatibility).

    ``none=True`` → no live credentials required (external_app must be empty).
    Otherwise ``require_env`` must list one or more env var names.
    When ``external_app`` is Discord (or any DISCORD_* is required), expand to
    the canonical Discord env set and set ``live_use_required``.
    """
    app = normalize_external_app(external_app)

    if none:
        if app:
            raise ValueError(
                "set-required-env --none cannot be combined with --external-app. "
                "If Special app is Discord and credentials are Yes, use "
                "--require … --external-app discord."
            )
        return {
            "none": True,
            "required_env": [],
            "external_app": None,
            "live_use_required": False,
        }

    required: list[str] = []
    for name in require_env or []:
        n = (name or "").strip()
        if n and n not in required:
            required.append(n)

    discordish = app == DISCORD_EXTERNAL_APP or any(
        n in _DISCORD_ENV_MARKERS for n in required
    )
    if discordish:
        app = DISCORD_EXTERNAL_APP
        required = expand_discord_required_env(required)

    if not required:
        raise ValueError(
            "set-required-env needs --none or at least one --require ENV_NAME. "
            "Name env vars from the issue/repo (do not invent a provider menu)."
        )

    return {
        "none": False,
        "required_env": required,
        "external_app": app,
        "live_use_required": bool(discordish),
    }


def missing_required_env(integrations: dict[str, Any]) -> list[str]:
    if not integrations or integrations.get("none"):
        return []
    missing: list[str] = []
    for name in integrations.get("required_env") or []:
        n = str(name).strip()
        if not n:
            continue
        if n in DISCORD_TOKEN_ALIASES:
            if not discord_token_present() and "DISCORD_BOT_TOKEN" not in missing:
                # Report the canonical name once.
                missing.append("DISCORD_BOT_TOKEN")
            continue
        if not env_present(n):
            missing.append(n)
    return missing


def credentials_recorded(state: dict[str, Any]) -> bool:
    integ = state.get("integrations")
    return isinstance(integ, dict) and ("none" in integ)


# --------------------------------------------------------------------------------------
# Provider involvement (wrk-begin step 10 — near credentials)
# --------------------------------------------------------------------------------------
def build_provider_record(
    *,
    none: bool = False,
    providers: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """
    Build state.providers payload.

    ``none=True`` → issue is not provider-related.
    Otherwise ``providers`` must list one or more opaque provider name strings
    taken from the issue/repo (not a canned menu).
    """
    if none:
        if providers:
            raise ValueError(
                "set-provider --none cannot be combined with --provider. "
                "If the issue relates to a provider, use --provider NAME …"
            )
        return {"none": True, "providers": []}

    names: list[str] = []
    for raw in providers or []:
        n = (raw or "").strip().lower()
        if not n:
            continue
        if n not in names:
            names.append(n)
    if not names:
        raise ValueError(
            "set-provider needs --none or at least one --provider NAME "
            "(from the issue/labels/docs — project’s own provider names)."
        )
    return {"none": False, "providers": names}


def providers_recorded(state: dict[str, Any]) -> bool:
    rec = state.get("providers")
    return isinstance(rec, dict) and ("none" in rec)


def require_provider_for_gate(
    state: dict[str, Any],
    phase: str,
) -> Optional[str]:
    """
    begin/plan: provider involvement must be recorded via set-provider.
    """
    if phase not in ("begin", "plan"):
        return None
    if not providers_recorded(state):
        return (
            f"Cannot gate {phase}: provider involvement not recorded. "
            "After wrk-begin provider Yes/No (+ which), run: "
            "ctl.py set-provider --none   OR   "
            "ctl.py set-provider --provider NAME "
            "(repeat --provider for each named provider from the issue)."
        )
    return None


def discord_live_use_required(integrations: dict[str, Any]) -> bool:
    if not integrations or integrations.get("none"):
        return False
    if integrations.get("live_use_required"):
        return True
    app = normalize_external_app(integrations.get("external_app"))
    if app == DISCORD_EXTERNAL_APP:
        return True
    required = integrations.get("required_env") or []
    return any(str(n).strip() in _DISCORD_ENV_MARKERS for n in required)


def live_use_attested(state: dict[str, Any], *, app: str) -> bool:
    attest = state.get("live_use")
    if not isinstance(attest, dict):
        return False
    want = normalize_external_app(app)
    got = normalize_external_app(attest.get("app"))
    evidence = (attest.get("evidence") or "").strip()
    return bool(got == want and evidence)


def api_key_required(integrations: dict[str, Any]) -> bool:
    """True when the run recorded a real API credential requirement (API = Yes)."""
    if not integrations or integrations.get("none"):
        return False
    return bool(integrations.get("required_env"))


# Mock-tooling / recorded-replay markers that disqualify live-HTTP evidence.
# Kept as distinctive tokens so positive phrasings ("unmocked", "no mock,
# real endpoint") do not trip the filter.
_HTTP_MOCK_MARKERS: tuple[str, ...] = (
    "mock only",
    "mocks only",
    "mock-only",
    "mocked the http",
    "mocked http layer",
    "fixture only",
    "fixtures only",
    "stubbed",
    "stub the http",
    "intercepted the http",
    "responses.add",
    "responses.get",
    "responses.post",
    "@responses",
    "requests_mock",
    "requests-mock",
    "requestsmock",
    "httpretty",
    "cassette",
    "vcrpy",
    "vcr.use",
    " nock",
    "nock(",
    "mock service worker",
    " msw",
    "monkeypatch",
    "record/replay",
    "recorded response",
    "replayed the",
    "no real request",
    "no live call",
    "no network call",
    "did not hit the api",
    "didn't hit the api",
    "did not hit the real",
)


def build_live_http_attest(*, evidence: str) -> dict[str, Any]:
    """
    Record that repro / feature validation hit the real API over a LIVE,
    UNMOCKED HTTP layer using the named credential — required before
    ``gate reproduce`` / ``gate implement`` whenever API = Yes.

    Evidence must describe the real request + outcome (method/endpoint or
    client call, status/response shape — no secrets). Any mock/stub/
    record-replay marker is rejected: a mocked HTTP layer or its routes is
    forbidden when a real API key is required.
    """
    ev = (evidence or "").strip()
    if len(ev) < 12:
        raise ValueError(
            "attest-live-http needs --evidence describing the real API call over "
            "a live HTTP layer (method + endpoint or client call, status/response "
            "outcome — no secrets). Mocks/fixtures/cassettes are not evidence."
        )
    low = ev.lower()
    hit = next((m for m in _HTTP_MOCK_MARKERS if m in low), None)
    if hit is not None:
        raise ValueError(
            "attest-live-http rejected: evidence names a mocked/stubbed/"
            f"recorded HTTP layer ({hit.strip()!r}). When API = Yes the repro / "
            "validation MUST hit the real endpoint over a live HTTP layer — no "
            "responses/requests-mock/httpretty/nock/msw/vcr/cassettes, no "
            "monkeypatched transport, no fixture server. Make the real call, or "
            "hard-stop on missing credentials."
        )
    return {"evidence": ev}


def live_http_attested(state: dict[str, Any]) -> bool:
    attest = (state or {}).get("live_http")
    if not isinstance(attest, dict):
        return False
    return bool((attest.get("evidence") or "").strip())


def build_live_use_attest(
    *,
    app: str,
    evidence: str,
) -> dict[str, Any]:
    normalized = normalize_external_app(app)
    if normalized != DISCORD_EXTERNAL_APP:
        raise ValueError(
            "attest-live-use currently supports --app discord only "
            f"(got {app!r})."
        )
    ev = (evidence or "").strip()
    if len(ev) < 12:
        raise ValueError(
            "attest-live-use needs --evidence describing the live Discord "
            "action (command/API call + outcome — no secrets). "
            "Mocks/fixtures alone are not evidence."
        )
    low = ev.lower()
    if any(
        bad in low
        for bad in (
            "mock only",
            "mocks only",
            "fixture only",
            "unit test only",
            "did not use discord",
            "skipped discord",
        )
    ):
        raise ValueError(
            "attest-live-use rejected: evidence must describe a live Discord "
            "action using injected DISCORD_* env (not mocks-only)."
        )
    return {
        "app": DISCORD_EXTERNAL_APP,
        "evidence": ev,
    }


# --------------------------------------------------------------------------------------
# Windows surface — gate before using a Windows host
# --------------------------------------------------------------------------------------
WINDOWS_SURFACE_REASONS: tuple[str, ...] = ("intrinsic", "cheap-repro-failed")


def build_windows_surface_attest(*, reason: str, evidence: str) -> dict[str, Any]:
    """
    Record why a Windows host is justified.

    reason ∈ {intrinsic, cheap-repro-failed}:
      - intrinsic: an OS-binding marker was found on the cited failing path
        (platform branch, winreg/pywin32/.ps1, Scripts/ vs bin/, WinError, …).
      - cheap-repro-failed: the cheapest faithful surface was attempted as a
        negative control and demonstrably could not reproduce the bug.
    The issue's env box ("OS: Windows 10") alone is never a valid justification.
    """
    r = (reason or "").strip().lower()
    if r not in WINDOWS_SURFACE_REASONS:
        raise ValueError(
            "attest-windows-surface needs --reason intrinsic|cheap-repro-failed "
            f"(got {reason!r}). Classify from the cited code, not the env box."
        )
    ev = (evidence or "").strip()
    if len(ev) < 12:
        raise ValueError(
            "attest-windows-surface needs --evidence: for intrinsic, the file:line "
            "+ the OS marker found; for cheap-repro-failed, what cheap surface you "
            'ran and why it could not reproduce. The env box ("OS: Windows 10") is '
            "not evidence."
        )
    low = ev.lower()
    if any(
        bad in low
        for bad in (
            "os: windows",
            "measured on windows",
            "reporter is on windows",
            "reporter env",
            "env box",
            "task manager kill",
        )
    ):
        raise ValueError(
            "attest-windows-surface rejected: evidence restates the reporter's "
            "environment, which is not proof the bug is OS-bound. Cite the OS marker "
            "on the failing code path, or the failed cheap repro."
        )
    return {"reason": r, "evidence": ev}


def windows_surface_attested(state: dict[str, Any]) -> bool:
    attest = (state or {}).get("windows_surface")
    if not isinstance(attest, dict):
        return False
    reason = (attest.get("reason") or "").strip().lower()
    evidence = (attest.get("evidence") or "").strip()
    return bool(reason in WINDOWS_SURFACE_REASONS and evidence)


def require_credentials_for_gate(
    state: dict[str, Any],
    phase: str,
) -> Optional[str]:
    """
    Return an error message if this gate must be blocked, else None.

    - begin: must record credentials (--none or --require …) before leaving begin
    - plan: must already be recorded
    - reproduce (bug) / implement (feat+bug): recorded + all required env present
      + Discord live-use attestation when Discord credentials were required
    """
    if phase == "begin":
        if not credentials_recorded(state):
            return (
                "Cannot gate begin: required credentials not recorded. "
                "After wrk-begin env/API-key assessment, run: "
                "ctl.py set-required-env --none   OR   "
                "ctl.py set-required-env --require SOME_API_KEY "
                "(repeat --require for each named env var from the issue/repo). "
                "If Special app is Discord and credentials are Yes: "
                "ctl.py set-required-env --require DISCORD_BOT_TOKEN "
                "--external-app discord …"
            )
        return None

    if phase in ("plan", "reproduce", "implement"):
        if not credentials_recorded(state):
            return (
                f"Cannot gate {phase}: required credentials not recorded in begin. "
                "Re-run begin + ctl.py set-required-env …"
            )
        if phase in ("reproduce", "implement"):
            integ = state.get("integrations") or {}
            missing = missing_required_env(integ)
            if missing:
                return (
                    f"Cannot gate {phase}: required credential env missing/empty: "
                    + ", ".join(missing)
                    + ". STATUS: hard_stop until secrets are injected "
                    "(wrk GH secrets → remote envVars)."
                )
            if discord_live_use_required(integ):
                # Discord's live-use attestation already proves a live, unmocked
                # gateway/HTTP interaction — it stands in for the live-HTTP gate.
                if not live_use_attested(state, app=DISCORD_EXTERNAL_APP):
                    return (
                        f"Cannot gate {phase}: Discord credentials required, but "
                        "live Discord use was not attested. Perform the issue's "
                        "needed Discord actions with injected DISCORD_* env "
                        "(send/read/react/etc. — not mocks), then: "
                        "ctl.py attest-live-use --app discord "
                        '--evidence "…live action + outcome…"'
                    )
            elif api_key_required(integ) and not live_http_attested(state):
                # API = Yes and non-Discord: the repro / validation must hit the
                # real endpoint over a live HTTP layer. Mocked HTTP is forbidden.
                return (
                    f"Cannot gate {phase}: a real API key is required "
                    "(API = Yes), but a live, UNMOCKED HTTP call was not "
                    "attested. The repro / validation must hit the real "
                    "endpoint with the named credential — no mock/stub/"
                    "record-replay of the HTTP layer or its routes "
                    "(responses/requests-mock/httpretty/nock/msw/vcr/"
                    "cassettes/monkeypatched transport/fixture server). Then: "
                    "ctl.py attest-live-http "
                    '--evidence "…real request (method+endpoint/client call) '
                    '+ status/response outcome, no secrets…"'
                )
        return None

    return None


# --------------------------------------------------------------------------------------
# Shared yes/no
# --------------------------------------------------------------------------------------
YES_NO = frozenset({"yes", "no"})


def _yes_no(val: str, flag: str) -> str:
    v = (val or "").strip().lower()
    if v not in YES_NO:
        raise ValueError(f"{flag} must be yes or no")
    return v


# --------------------------------------------------------------------------------------
# Work host (wrk-begin) — remote vs local/Mac; no work-root restriction
# --------------------------------------------------------------------------------------


def build_work_host_record(
    *,
    remote: str,
    local: str | None = None,
    mac: str | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Record operator host. Local Mac work may run from any directory."""
    is_remote = _yes_no(remote, "--remote")
    if is_remote == "yes":
        return {
            "remote": "yes",
            "local": "n/a",
            "mac": "n/a",
            "cwd": None,
            "root_ok": True,
            "enforcement": "skipped_remote",
        }
    if local is None or mac is None:
        raise ValueError(
            "when --remote no, pass --local yes|no and --mac yes|no"
        )
    loc = _yes_no(local, "--local")
    m = _yes_no(mac, "--mac")
    cwd_s = str(Path(cwd.strip()).expanduser().resolve()) if (cwd or "").strip() else None
    return {
        "remote": "no",
        "local": loc,
        "mac": m,
        "cwd": cwd_s,
        "root_ok": True,
        "enforcement": "no_work_root",
    }


def work_host_recorded(state: dict[str, Any]) -> bool:
    rec = (state or {}).get("work_host")
    if not isinstance(rec, dict):
        return False
    if rec.get("remote") == "yes":
        return rec.get("root_ok") is True
    if rec.get("remote") != "no":
        return False
    if rec.get("local") not in YES_NO or rec.get("mac") not in YES_NO:
        return False
    return rec.get("root_ok") is True


def require_work_host_for_gate(state: dict[str, Any], phase: str) -> str | None:
    """begin/plan: work host / local Mac root must be recorded via set-work-host."""
    if phase not in ("begin", "plan"):
        return None
    if not work_host_recorded(state):
        return (
            f"Cannot gate {phase}: work host not recorded. "
            "After wrk-begin work-host gates, run: "
            "ctl.py set-work-host --remote yes   OR   "
            "ctl.py set-work-host --remote no --local yes|no --mac yes|no "
            "[--cwd PATH]."
        )
    return None


# --------------------------------------------------------------------------------------
# Grok Bot playbook (need = interface ops from issue; capability = host locks)
# --------------------------------------------------------------------------------------


def build_grok_desktop_record(
    *,
    grok_bot: str,
    bug: str,
    desktop: str,
    interface_ops: str,
    interface_ops_why: str = "",
) -> dict[str, Any]:
    """playbook_required = issue needs interface ops AND bug AND Grok Bot host.

    ``desktop`` is recorded for step-2 alignment only — it does not turn the
    playbook on. ``interface_ops`` is the semantic need from the issue's
    flow/repro (operate/navigate an interface vs API/CLI/config/logs).
    """
    g = _yes_no(grok_bot, "--grok-bot")
    b = _yes_no(bug, "--bug")
    d = _yes_no(desktop, "--desktop")
    ops = _yes_no(interface_ops, "--interface-ops")
    why = (interface_ops_why or "").strip()
    return {
        "grok_bot": g,
        "bug": b,
        "desktop": d,
        "interface_ops_needed": ops,
        "interface_ops_why": why,
        "playbook_required": ops == "yes" and b == "yes" and g == "yes",
    }


def grok_desktop_recorded(state: dict[str, Any]) -> bool:
    rec = (state or {}).get("grok_desktop")
    if not isinstance(rec, dict):
        return False
    return all(
        rec.get(k) in YES_NO
        for k in ("grok_bot", "bug", "desktop", "interface_ops_needed")
    )


def grok_desktop_playbook_required(state: dict[str, Any]) -> bool:
    rec = (state or {}).get("grok_desktop") or {}
    return bool(isinstance(rec, dict) and rec.get("playbook_required"))


def build_mac_playbook_attest(*, evidence: str) -> dict[str, Any]:
    ev = (evidence or "").strip()
    if len(ev) < 12:
        raise ValueError(
            "attest-mac-playbook needs --evidence describing the live Mac "
            "desktop action + outcome (no secrets)"
        )
    low = ev.lower()
    banned = ("mock", "unit test only", "skipped playbook", "screenshot only")
    if any(b in low for b in banned) and "live" not in low:
        raise ValueError(
            "attest-mac-playbook rejected: evidence must describe live Mac "
            "desktop playbook use, not a mock/skip"
        )
    return {"evidence": ev}


def mac_playbook_attested(state: dict[str, Any]) -> bool:
    attest = (state or {}).get("mac_playbook")
    if not isinstance(attest, dict):
        return False
    return bool((attest.get("evidence") or "").strip())


def require_grok_desktop_for_gate(
    state: dict[str, Any],
    phase: str,
) -> Optional[str]:
    """Begin/plan need need+capability locks recorded. Reproduce also needs
    playbook attestation when playbook_required (interface ops + bug + Bot)."""
    if phase in ("begin", "plan", "reproduce"):
        if not grok_desktop_recorded(state):
            return (
                f"Cannot gate {phase}: Grok desktop gates not recorded. "
                "After wrk-begin, run: "
                "ctl.py set-grok-desktop --grok-bot yes|no --bug yes|no "
                "--desktop yes|no --interface-ops yes|no "
                '[--interface-ops-why "…issue-grounded…"]'
            )
    if phase == "reproduce" and grok_desktop_playbook_required(state):
        if not mac_playbook_attested(state):
            return (
                "Cannot gate reproduce: interface-ops need + bug + Grok Bot "
                "capability → Mac computer-use playbook required. Follow "
                "drive the live desktop app, then: "
                "ctl.py attest-mac-playbook --evidence "
                '"…live Mac desktop action + outcome…"'
            )
    return None


# --------------------------------------------------------------------------------------
# Cursor local Desktop computer-use (need = interface ops; capability = host)
# --------------------------------------------------------------------------------------

# Specialty Grok bot on the local Grok app — computer-use only for this path.
CURSOR_DESKTOP_CU_BOT_ID = "f96438a3-f575-4ef2-86c8-4c6a8cf7a6e1"


def build_cursor_desktop_cu_record(
    *,
    desktop: str,
    windows: str,
    local_cursor: str,
    interface_ops: str,
    interface_ops_why: str = "",
) -> dict[str, Any]:
    """cu_required when the issue needs interface ops, host is not Windows,
    and the operator is local Cursor. ``desktop`` is step-2 alignment only."""
    d = _yes_no(desktop, "--desktop")
    w = _yes_no(windows, "--windows")
    lc = _yes_no(local_cursor, "--local-cursor")
    ops = _yes_no(interface_ops, "--interface-ops")
    why = (interface_ops_why or "").strip()
    required = ops == "yes" and w == "no" and lc == "yes"
    return {
        "desktop": d,
        "windows": w,
        "local_cursor": lc,
        "interface_ops_needed": ops,
        "interface_ops_why": why,
        "cu_required": required,
        "bot_id": CURSOR_DESKTOP_CU_BOT_ID if required else None,
    }


def cursor_desktop_cu_recorded(state: dict[str, Any]) -> bool:
    rec = (state or {}).get("cursor_desktop_cu")
    if not isinstance(rec, dict):
        return False
    return all(
        rec.get(k) in YES_NO
        for k in ("desktop", "windows", "local_cursor", "interface_ops_needed")
    )


def cursor_desktop_cu_required(state: dict[str, Any]) -> bool:
    rec = (state or {}).get("cursor_desktop_cu") or {}
    return bool(isinstance(rec, dict) and rec.get("cu_required"))


def build_cursor_desktop_cu_attest(*, evidence: str) -> dict[str, Any]:
    ev = (evidence or "").strip()
    if len(ev) < 12:
        raise ValueError(
            "attest-cursor-desktop-cu needs --evidence describing the live "
            "Desktop computer-use action via the specialty Grok bot + outcome "
            "(no secrets)"
        )
    low = ev.lower()
    banned = ("mock", "unit test only", "skipped playbook", "screenshot only", "freestyle")
    if any(b in low for b in banned) and "live" not in low:
        raise ValueError(
            "attest-cursor-desktop-cu rejected: evidence must describe live "
            "Desktop computer-use via the specialty Grok bot, not a mock/skip"
        )
    return {"evidence": ev, "bot_id": CURSOR_DESKTOP_CU_BOT_ID}


def cursor_desktop_cu_attested(state: dict[str, Any]) -> bool:
    attest = (state or {}).get("cursor_desktop_cu_attest")
    if not isinstance(attest, dict):
        return False
    return bool((attest.get("evidence") or "").strip())


def require_cursor_desktop_cu_for_gate(
    state: dict[str, Any],
    phase: str,
) -> Optional[str]:
    """Begin/plan need the locks recorded. Reproduce + implement need the
    specialty-bot computer-use attestation when cu_required (bugs and features)."""
    if phase in ("begin", "plan", "reproduce", "implement"):
        if not cursor_desktop_cu_recorded(state):
            return (
                f"Cannot gate {phase}: Cursor Desktop computer-use gates not recorded. "
                "After wrk-begin Cursor Desktop CU step, run: "
                "ctl.py set-cursor-desktop-cu --desktop yes|no --windows yes|no "
                "--local-cursor yes|no --interface-ops yes|no "
                '[--interface-ops-why "…issue-grounded…"]'
            )
    if phase in ("reproduce", "implement") and cursor_desktop_cu_required(state):
        if not cursor_desktop_cu_attested(state):
            return (
                f"Cannot gate {phase}: interface-ops need + Windows=no + local "
                "Cursor=yes — computer-use via the specialty Grok bot is mandatory "
                f"(bot {CURSOR_DESKTOP_CU_BOT_ID}). Follow "
                "drive the live desktop app; do not freestyle. Then: "
                "ctl.py attest-cursor-desktop-cu --evidence "
                '"…live Desktop CU action via specialty bot + outcome…"'
            )
    return None


# --------------------------------------------------------------------------------------
# Launch source — extension is the only remote + feat bypass
# --------------------------------------------------------------------------------------

LAUNCH_SOURCES = frozenset({"extension", "local", "other"})


def build_launch_source_record(*, source: str) -> dict[str, Any]:
    s = (source or "").strip().lower()
    if s not in LAUNCH_SOURCES:
        raise ValueError(
            "--source must be one of: " + ", ".join(sorted(LAUNCH_SOURCES))
        )
    return {
        "source": s,
        # Only extension-invoked remote runs may take the feat path.
        "remote_feat_allowed": s == "extension",
    }


def launch_source_recorded(state: dict[str, Any]) -> bool:
    rec = (state or {}).get("launch_source")
    if not isinstance(rec, dict):
        return False
    return rec.get("source") in LAUNCH_SOURCES


def remote_feat_allowed(state: dict[str, Any]) -> bool:
    rec = (state or {}).get("launch_source") or {}
    return bool(isinstance(rec, dict) and rec.get("source") == "extension")


def _is_remote_run(state: dict[str, Any]) -> bool:
    wh = (state or {}).get("work_host") or {}
    return isinstance(wh, dict) and wh.get("remote") == "yes"


def reject_remote_feat_unless_extension(state: dict[str, Any]) -> Optional[str]:
    """remote + path=feat is allowed only when launch_source=extension."""
    if (state or {}).get("path") != "feat":
        return None
    if not _is_remote_run(state):
        return None
    if remote_feat_allowed(state):
        return None
    src = ((state or {}).get("launch_source") or {}).get("source") or "unset"
    return (
        "remote + feat is blocked unless launch_source=extension "
        f"(got launch_source={src!r}). Local/other remote runs "
        "are bug-only. Extension launches must record: "
        "ctl.py set-launch-source --source extension"
    )


def require_launch_source_for_gate(
    state: dict[str, Any],
    phase: str,
) -> Optional[str]:
    if phase in ("begin", "plan"):
        if not launch_source_recorded(state):
            return (
                f"Cannot gate {phase}: launch source not recorded. "
                "Run: ctl.py set-launch-source --source extension|local|other "
                "(extension = only bypass that allows remote + feat)"
            )
    if phase in ("begin", "plan", "reproduce", "implement"):
        return reject_remote_feat_unless_extension(state)
    return None

