#!/usr/bin/env python3
"""wrk-e2e phase controller.

Per-run state: ~/.cursor/wrk-e2e/runs/<run_id>.json
Legacy mirror: ~/.cursor/wrk-e2e/state.json
Audit log:     ~/.cursor/wrk-e2e/audit.jsonl

Phases (order):
  begin → plan → reproduce → implement → review → recap → done
  (feature path skips reproduce)

Default: continuous (no HITL). Gate auto-advances to the next phase.

Usage:
  ctl.py start --issue URL [--path bug|feat] [--run-id ID] [--hitl]
  ctl.py status [--run-id ID]
  ctl.py list
  ctl.py gate <phase> [--run-id ID]
  ctl.py check-pr-base [--run-id ID]   # behind=0 vs upstream before wrk-pr/push
  ctl.py advance [--run-id ID]          # HITL only
  ctl.py set-path bug|feat [--run-id ID]
  ctl.py set-required-env --none | --require ENV_NAME … [--external-app discord]
  ctl.py set-provider --none | --provider NAME …
  ctl.py check-provider-wallet [--run-id ID]
  ctl.py set-work-host --remote yes|no [--local … --mac … --cwd …]
  ctl.py set-launch-source --source extension|local|other
  ctl.py attest-live-use --app discord --evidence "…"
  ctl.py attest-live-http --evidence "…"   # API = Yes, non-Discord
  ctl.py set-grok-desktop --grok-bot yes|no --bug yes|no --desktop yes|no --interface-ops yes|no
  ctl.py attest-mac-playbook --evidence "…"
  ctl.py set-cursor-desktop-cu --desktop yes|no --windows yes|no --local-cursor yes|no --interface-ops yes|no
  ctl.py attest-cursor-desktop-cu --evidence "…"
  ctl.py record-review --file review.json
  ctl.py record-closer --file closer.json
  ctl.py clear [--run-id ID]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Allow importing sibling modules when invoked as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from integrations_gate import (  # noqa: E402
    build_cursor_desktop_cu_attest,
    build_cursor_desktop_cu_record,
    build_grok_desktop_record,
    build_launch_source_record,
    build_live_http_attest,
    build_live_use_attest,
    build_mac_playbook_attest,
    build_provider_record,
    build_required_env_record,
    build_windows_surface_attest,
    build_work_host_record,
    cursor_desktop_cu_required,
    grok_desktop_playbook_required,
    missing_required_env,
    reject_remote_feat_unless_extension,
    require_credentials_for_gate,
    require_cursor_desktop_cu_for_gate,
    require_grok_desktop_for_gate,
    require_launch_source_for_gate,
    require_provider_for_gate,
    require_work_host_for_gate,
)
from fork_sync_gate import (  # noqa: E402
    ensure_pr_base_synced,
    require_fork_sync_for_gate,
)
from provider_wallet import (  # noqa: E402
    check_providers,
    require_provider_wallet_for_gate,
)
from review_gate import (  # noqa: E402
    MAX_CLOSER_CYCLES,
    require_review_for_gate,
    validate_closer,
    validate_review,
)
from state_store import (  # noqa: E402
    clear_run,
    empty_state,
    list_runs,
    load_run,
    resolve_run_id,
    save_run,
)
from telemetry import emit, emit_pillars  # noqa: E402

# Per-phase PILLAR registry: pillar suffix -> dataType. The agent passes
# `--pillar name=value`; dtype is looked up here so it never has to specify it.
PILLARS: dict[str, dict[str, str]] = {
    "plan": {
        "approach-soundness": "NUMERIC", "environment-fit": "NUMERIC",
        "assumption-surfacing": "NUMERIC", "reuse-awareness": "NUMERIC",
        "falsifiability": "BOOLEAN",
    },
    "reproduce": {
        "surface-fidelity": "CATEGORICAL", "environment-fidelity": "BOOLEAN",
        "credential-integrity": "BOOLEAN", "failure-match": "BOOLEAN",
        "control-validity": "BOOLEAN",
    },
    "implement": {
        "correctness": "NUMERIC", "scope-discipline": "NUMERIC",
        "convention-fit": "BOOLEAN", "test-coverage": "NUMERIC",
        "regression-safety": "BOOLEAN",
    },
    "review": {
        "requirement-coverage": "NUMERIC", "guideline-compliance": "NUMERIC",
        "self-catch-rate": "NUMERIC", "readiness-verdict": "CATEGORICAL",
    },
    "pr": {
        "template-adherence": "NUMERIC", "claim-accuracy": "BOOLEAN",
        "evidence": "BOOLEAN", "format-compliance": "BOOLEAN",
    },
}


def _coerce_pillar(dtype: str, raw: str):
    """Coerce a --pillar string value to the registry dtype."""
    if dtype == "NUMERIC":
        try:
            return float(raw)
        except ValueError:
            return None
    if dtype == "BOOLEAN":
        return 1 if str(raw).strip().lower() in ("1", "true", "yes", "ok", "y") else 0
    return str(raw)  # CATEGORICAL


def _pillars_from_args(phase: str, pillar_args: list[str] | None):
    """Parse repeatable `--pillar name=value` into emit_pillars tuples for the phase."""
    registry = PILLARS.get(phase, {})
    out: list[tuple] = []
    for item in pillar_args or []:
        if "=" not in item:
            continue
        name, _, val = item.partition("=")
        name, val = name.strip(), val.strip()
        dtype = registry.get(name)
        if not dtype:  # unknown pillar for this phase → ignore, never block gate
            continue
        coerced = _coerce_pillar(dtype, val)
        if coerced is None:
            continue
        out.append((name, coerced, dtype, None))
    return out


def derive_pillars(state: dict[str, Any], phase: str) -> tuple[list[tuple], str | None]:
    """Objectively-derived pillars for a phase, plus their provenance tier.

    Returns (emit_pillars tuples, provenance) — provenance None when nothing was
    derived. Block B derives reproduce pillars from run state; Block C derives
    implement pillars from git/CI.
    """
    if phase == "reproduce":
        return _derive_reproduce(state), "derived:state"
    if phase == "implement":
        derived = _derive_implement(state)
        return derived, ("derived:git" if derived else None)
    return [], None


def _changed_files() -> list[str]:
    """Best-effort list of files this contribution touched (working / staged / last commit)."""
    import subprocess

    for cmd in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            files = [x for x in r.stdout.splitlines() if x.strip()]
            if files:
                return files
        except Exception:
            continue
    return []


_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|spec|__tests__)/|(^|/)test_|_test\.|\.test\.|\.spec\.", re.I
)


def _derive_implement(state: dict[str, Any]) -> list[tuple]:
    """Implement pillars derived from the git diff (scope + test coverage)."""
    files = _changed_files()
    if not files:
        return []  # nothing to derive; agent may supply via --pillar
    n_tests = sum(1 for f in files if _TEST_PATH_RE.search(f))
    return [
        ("scope-discipline", float(len(files)), "NUMERIC", None),
        ("test-coverage", float(n_tests), "NUMERIC", None),
    ]


def _derive_reproduce(state: dict[str, Any]) -> list[tuple]:
    """Reproduce pillars read straight off the gated run state."""
    out: list[tuple] = []

    # surface-fidelity — from the windows-surface attestation reason.
    ws = state.get("windows_surface") or {}
    reason = ws.get("reason")
    sf = {"intrinsic": "intrinsic", "cheap-repro-failed": "escalated"}.get(
        reason, "cheap-faithful"
    )
    out.append(("surface-fidelity", sf, "CATEGORICAL", reason))

    # environment-fidelity — required env satisfied (the gate's own cred check).
    env_ok = 1 if require_credentials_for_gate(state, "reproduce") is None else 0
    out.append(("environment-fidelity", env_ok, "BOOLEAN", None))

    # credential-integrity — live creds attested, or none were required.
    integ = state.get("integrations") or {}
    live = state.get("live_use") or {}
    none_required = bool(integ.get("none")) or not integ.get("required_env")
    cred_ok = 1 if (live.get("app") or none_required) else 0
    out.append(("credential-integrity", cred_ok, "BOOLEAN", None))

    # failure-match — reaching the reproduce gate means the failure reproduced
    # (mirrors score_outcomes.repro_signal); the agent may override with
    # `--pillar failure-match=0` if what broke wasn't the reported failure.
    out.append(("failure-match", 1, "BOOLEAN", "gate-reached"))
    return out


def _emit_gate_pillars(state: dict[str, Any], phase: str, args: argparse.Namespace) -> None:
    """Best-effort: record this phase's pillar verdicts on the ledger + state."""
    try:
        pillars = _pillars_from_args(phase, getattr(args, "pillar", None))
        derived, derived_prov = derive_pillars(state, phase)  # objective pillars
        # agent-supplied override/augment derived (same suffix wins for agent)
        by_name = {p[0]: p for p in derived}
        for p in pillars:
            by_name[p[0]] = p
        merged = list(by_name.values())
        if not merged:
            return
        # provenance precedence: explicit flag > derived tier > self
        provenance = getattr(args, "provenance", None) or derived_prov or "self"
        state.setdefault("phases", {})[phase] = {
            "pillars": {p[0]: p[1] for p in merged}, "provenance": provenance,
        }
        emit_pillars(
            phase, run_id=state.get("run_id"), issue=state.get("issue"),
            path=state.get("path"), pillars=merged, provenance=provenance,
        )
    except Exception:
        pass  # telemetry must never block a gate

PHASE_ORDER_BUG = ["begin", "plan", "reproduce", "implement", "review", "recap", "done"]
PHASE_ORDER_FEAT = ["begin", "plan", "implement", "review", "recap", "done"]


def phase_order(path: str | None) -> list[str]:
    if path == "feat":
        return list(PHASE_ORDER_FEAT)
    return list(PHASE_ORDER_BUG)


def next_phase(state: dict[str, Any]) -> str | None:
    order = phase_order(state.get("path"))
    current = state.get("phase")
    if current not in order:
        return None
    idx = order.index(current)
    if idx + 1 >= len(order):
        return None
    return order[idx + 1]


def print_state(state: dict[str, Any]) -> None:
    import json

    print(json.dumps(state, indent=2))


def _run_id_from_args(args: argparse.Namespace, *, create: bool = False) -> str | None:
    rid = getattr(args, "run_id", None)
    return resolve_run_id(rid, create_if_missing=create)


def _emit_ctl(
    event_type: str,
    state: dict[str, Any],
    *,
    decision: str = "ok",
    detail: dict[str, Any] | None = None,
    level: str = "DEFAULT",
) -> None:
    emit(
        event_type,
        run_id=state.get("run_id"),
        decision=decision,
        phase=state.get("phase"),
        issue=state.get("issue"),
        path=state.get("path"),
        detail=detail or {},
        level=level,
    )


def cmd_start(args: argparse.Namespace) -> int:
    continuous = not bool(getattr(args, "hitl", False))
    if getattr(args, "continuous", False):
        continuous = True
    run_id = _run_id_from_args(args, create=True)
    assert run_id is not None
    state: dict[str, Any] = {
        "active": True,
        "run_id": run_id,
        "issue": args.issue,
        "path": args.path,
        "phase": "begin",
        "awaiting_continue": False,
        "continuous": continuous,
        "completed": [],
    }
    launch_src = getattr(args, "launch_source", None)
    if launch_src:
        try:
            state["launch_source"] = build_launch_source_record(source=launch_src)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    state = save_run(state, run_id)
    _emit_ctl(
        "wrk_e2e.ctl.start",
        state,
        detail={
            "continuous": continuous,
            "hitl": not continuous,
            "launch_source": (state.get("launch_source") or {}).get("source"),
        },
    )
    mode = "continuous (no HITL)" if continuous else "HITL (pause for continue)"
    print(f"Started wrk-e2e run — {mode}.")
    print(f"RUN_ID={run_id}")
    print("Export for this shell: export WRK_E2E_RUN_ID=" + run_id)
    if state.get("launch_source"):
        print(f"launch_source={state['launch_source']['source']}")
    print_state(state)
    print(
        "\nPHASE: begin — follow bundled .cursor/skills/wrk-begin/SKILL.md fully, "
        "then run: ctl.py gate begin"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = load_run(_run_id_from_args(args))
    print_state(state)
    if not state.get("active"):
        print("\nNo active wrk-e2e run.", file=sys.stderr)
        return 1
    if state.get("awaiting_continue") and not state.get("continuous"):
        print(
            f"\nPHASE {state.get('phase')} COMPLETE — awaiting user continue "
            f"(then: ctl.py advance)",
            file=sys.stderr,
        )
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    import json

    runs = list_runs()
    active = [r for r in runs if r.get("active")]
    print(json.dumps({"active_count": len(active), "runs": runs}, indent=2))
    return 0


def cmd_set_path(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl("wrk_e2e.ctl.set_path", state, decision="reject", detail={"reason": "inactive"}, level="WARNING")
        return 1
    state["path"] = args.path
    blocked = reject_remote_feat_unless_extension(state)
    if blocked:
        print(blocked, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_path",
            state,
            decision="reject",
            detail={"reason": "remote_feat_blocked", "error": blocked},
            level="WARNING",
        )
        return 1
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl("wrk_e2e.ctl.set_path", state, detail={"path": args.path})
    print_state(state)
    return 0


def cmd_set_launch_source(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_launch_source",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        record = build_launch_source_record(source=args.source)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    state["launch_source"] = record
    blocked = reject_remote_feat_unless_extension(state)
    if blocked:
        # Allow recording non-extension sources even if path=feat was set early;
        # the feat path itself stays blocked until source=extension.
        pass
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.set_launch_source",
        state,
        detail={"launch_source": record},
    )
    print("Launch source recorded:")
    print(f"  source={record['source']}")
    print(
        f"  remote_feat_allowed: "
        f"{'YES' if record['remote_feat_allowed'] else 'NO'}"
    )
    if blocked:
        print(f"  note: {blocked}", file=sys.stderr)
    print_state(state)
    return 0


def cmd_set_required_env(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_required_env",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        record = build_required_env_record(
            none=bool(args.none),
            require_env=list(args.require or []),
            external_app=getattr(args, "external_app", None),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_required_env",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1

    state["integrations"] = record
    # New credential record clears any prior live-use attestation.
    state.pop("live_use", None)
    state = save_run(state, state.get("run_id") or rid)
    missing = missing_required_env(record)
    _emit_ctl(
        "wrk_e2e.ctl.set_required_env",
        state,
        detail={"required_env": record, "missing": missing},
    )
    print("Required credentials recorded:")
    if record.get("none"):
        print("  none — no real API key / third-party credential required")
    else:
        print(f"  required_env: {', '.join(record.get('required_env') or [])}")
        if record.get("external_app"):
            print(f"  external_app: {record.get('external_app')}")
        if record.get("live_use_required"):
            print(
                "  live_use_required: YES — attest before gate reproduce/implement"
            )
        if missing:
            print("  env present: NO — missing: " + ", ".join(missing))
            print("  (reproduce/implement gates will hard-fail until these are set)")
        else:
            print("  env present: YES")
    print_state(state)
    return 0


def cmd_set_provider(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_provider",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        record = build_provider_record(
            none=bool(args.none),
            providers=list(args.provider or []),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_provider",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1

    state["providers"] = record
    if record.get("none"):
        state["provider_wallets"] = None
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.set_provider",
        state,
        detail={"providers": record},
    )
    print("Provider involvement recorded:")
    if record.get("none"):
        print("  none — issue is not provider-related")
    else:
        print(f"  providers: {', '.join(record.get('providers') or [])}")
        print("  Next: ctl.py check-provider-wallet (required before gate begin)")
    print_state(state)
    return 0


def cmd_check_provider_wallet(args: argparse.Namespace) -> int:
    """Live wallet/credits check for each Provider: Yes name. Fail closed."""
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.check_provider_wallet",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1

    providers = state.get("providers")
    if not isinstance(providers, dict) or "none" not in providers:
        print(
            "Provider involvement not recorded. Run set-provider first.",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.check_provider_wallet",
            state,
            decision="reject",
            detail={"reason": "providers_missing"},
            level="WARNING",
        )
        return 1

    if providers.get("none"):
        state["provider_wallets"] = {
            "checked": [],
            "all_funded": True,
            "blockers": [],
            "skipped": True,
        }
        state = save_run(state, state.get("run_id") or rid)
        print("Provider wallets: skipped (set-provider --none)")
        print_state(state)
        return 0

    names = list(providers.get("providers") or [])
    wallets = check_providers(names)
    state["provider_wallets"] = wallets
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.check_provider_wallet",
        state,
        decision="ok" if wallets.get("all_funded") else "reject",
        detail={
            "all_funded": wallets.get("all_funded"),
            "blockers": wallets.get("blockers"),
            # checked without remaining amounts that might be sensitive? remaining is fine
            "checked": [
                {
                    "provider": c.get("provider"),
                    "verdict": c.get("verdict"),
                    "reason": c.get("reason"),
                }
                for c in (wallets.get("checked") or [])
            ],
        },
        level="DEFAULT" if wallets.get("all_funded") else "WARNING",
    )
    print("Provider wallets:")
    for c in wallets.get("checked") or []:
        rem = c.get("remaining")
        rem_s = f" remaining={rem}" if rem is not None else ""
        print(f"  {c.get('provider')}: {c.get('verdict')} — {c.get('reason')}{rem_s}")
    if wallets.get("all_funded"):
        print("  all_funded: YES")
        print_state(state)
        return 0
    print("  all_funded: NO — HARD STOP (top-up or unknown). Do not gate begin.")
    print_state(state)
    return 1


def _load_json_file(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_record_review(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.record_review",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        data = _load_json_file(args.file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read review file: {exc}", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.record_review",
            state,
            decision="reject",
            detail={"reason": "read_error", "error": str(exc)},
            level="WARNING",
        )
        return 1
    errs = validate_review(data)
    if errs:
        print("record-review rejected — review_gate validation failed:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.record_review",
            state,
            decision="reject",
            detail={"reason": "invalid", "errors": errs},
            level="WARNING",
        )
        return 1
    history = list(state.get("review_history") or [])
    prev = state.get("review")
    if isinstance(prev, dict):
        history.append(prev)
    state["review_history"] = history
    state["review"] = data
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.record_review",
        state,
        detail={
            "verdict": data.get("verdict"),
            "issue_coverage": data.get("issue_coverage"),
            "closer_cycle": data.get("closer_cycle"),
        },
    )
    print("Review artifact recorded:")
    print(f"  verdict: {data.get('verdict')}")
    print(f"  issue_coverage: {data.get('issue_coverage')}")
    print(f"  closer_cycle: {data.get('closer_cycle')}")
    print_state(state)
    return 0


def cmd_record_closer(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.record_closer",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        data = _load_json_file(args.file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read closer file: {exc}", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.record_closer",
            state,
            decision="reject",
            detail={"reason": "read_error", "error": str(exc)},
            level="WARNING",
        )
        return 1
    prior_review = state.get("review") if isinstance(state.get("review"), dict) else None
    closer_history = list(state.get("closer_history") or [])
    prior_closer = closer_history[-1] if closer_history else None
    errs = validate_closer(
        data,
        prior_review=prior_review,
        prior_closer=prior_closer if isinstance(prior_closer, dict) else None,
    )
    if errs:
        print("record-closer rejected — review_gate validation failed:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.record_closer",
            state,
            decision="reject",
            detail={"reason": "invalid", "errors": errs},
            level="WARNING",
        )
        return 1
    if isinstance(state.get("closer"), dict):
        closer_history.append(state["closer"])
    state["closer_history"] = closer_history
    state["closer"] = data
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.record_closer",
        state,
        detail={
            "closer_cycle": data.get("closer_cycle"),
            "implement_count": data.get("implement_count"),
        },
    )
    print("Closer artifact recorded:")
    print(f"  closer_cycle: {data.get('closer_cycle')}")
    print(f"  implement_count: {data.get('implement_count')}")
    print_state(state)
    return 0


def cmd_set_work_host(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_work_host",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        record = build_work_host_record(
            remote=args.remote,
            local=args.local,
            mac=args.mac,
            cwd=args.cwd,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_work_host",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1
    state["work_host"] = record
    blocked = reject_remote_feat_unless_extension(state)
    if blocked:
        print(blocked, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_work_host",
            state,
            decision="reject",
            detail={"reason": "remote_feat_blocked", "error": blocked},
            level="WARNING",
        )
        return 1
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl("wrk_e2e.ctl.set_work_host", state, detail={"work_host": record})
    print("Work host recorded:")
    print(
        f"  remote={record['remote']}  local={record['local']}  "
        f"mac={record['mac']}"
    )
    if record.get("cwd"):
        print(f"  cwd: {record['cwd']}")
    print(f"  enforcement: {record.get('enforcement')}")
    print_state(state)
    return 0


def cmd_set_grok_desktop(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_grok_desktop",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        record = build_grok_desktop_record(
            grok_bot=args.grok_bot,
            bug=args.bug,
            desktop=args.desktop,
            interface_ops=args.interface_ops,
            interface_ops_why=getattr(args, "interface_ops_why", "") or "",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_grok_desktop",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1
    state["grok_desktop"] = record
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl("wrk_e2e.ctl.set_grok_desktop", state, detail={"grok_desktop": record})
    print("Grok desktop gates recorded:")
    print(
        f"  grok_bot={record['grok_bot']}  bug={record['bug']}  "
        f"desktop={record['desktop']}  interface_ops={record['interface_ops_needed']}"
    )
    if record.get("interface_ops_why"):
        print(f"  interface_ops_why: {record['interface_ops_why'][:200]}")
    print(f"  playbook_required: {'YES' if record['playbook_required'] else 'NO'}")
    print_state(state)
    return 0


def cmd_attest_mac_playbook(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        return 1
    if not grok_desktop_playbook_required(state):
        print(
            "Cannot attest-mac-playbook: playbook is off. Need "
            "interface-ops=yes + bug=yes + grok-bot=yes. Do not use the playbook.",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.attest_mac_playbook",
            state,
            decision="reject",
            detail={"reason": "playbook_off", "grok_desktop": state.get("grok_desktop")},
            level="WARNING",
        )
        return 1
    try:
        attest = build_mac_playbook_attest(evidence=args.evidence)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    state["mac_playbook"] = attest
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.attest_mac_playbook",
        state,
        detail={"evidence_len": len(attest["evidence"])},
    )
    print("Mac playbook attested (interface-ops need + bug + Grok Bot).")
    print(f"  evidence: {attest['evidence'][:200]}")
    print_state(state)
    return 0


def cmd_set_cursor_desktop_cu(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_cursor_desktop_cu",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        record = build_cursor_desktop_cu_record(
            desktop=args.desktop,
            windows=args.windows,
            local_cursor=args.local_cursor,
            interface_ops=args.interface_ops,
            interface_ops_why=getattr(args, "interface_ops_why", "") or "",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.set_cursor_desktop_cu",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1
    state["cursor_desktop_cu"] = record
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.set_cursor_desktop_cu",
        state,
        detail={"cursor_desktop_cu": record},
    )
    print("Cursor Desktop computer-use gates recorded:")
    print(
        f"  desktop={record['desktop']}  windows={record['windows']}  "
        f"local_cursor={record['local_cursor']}  "
        f"interface_ops={record['interface_ops_needed']}"
    )
    if record.get("interface_ops_why"):
        print(f"  interface_ops_why: {record['interface_ops_why'][:200]}")
    print(f"  cu_required: {'YES' if record['cu_required'] else 'NO'}")
    if record.get("bot_id"):
        print(f"  bot_id: {record['bot_id']}")
    print_state(state)
    return 0


def cmd_attest_cursor_desktop_cu(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        return 1
    if not cursor_desktop_cu_required(state):
        print(
            "Cannot attest-cursor-desktop-cu: path is off. Need "
            "interface-ops=yes, windows=no, local-cursor=yes. Do not freestyle "
            "computer-use.",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.attest_cursor_desktop_cu",
            state,
            decision="reject",
            detail={
                "reason": "cu_off",
                "cursor_desktop_cu": state.get("cursor_desktop_cu"),
            },
            level="WARNING",
        )
        return 1
    try:
        attest = build_cursor_desktop_cu_attest(evidence=args.evidence)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    state["cursor_desktop_cu_attest"] = attest
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.attest_cursor_desktop_cu",
        state,
        detail={"evidence_len": len(attest["evidence"]), "bot_id": attest.get("bot_id")},
    )
    print("Cursor Desktop computer-use attested (cu_required).")
    print(f"  bot_id: {attest.get('bot_id')}")
    print(f"  evidence: {attest['evidence'][:200]}")
    print_state(state)
    return 0


def cmd_attest_live_use(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.attest_live_use",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        attest = build_live_use_attest(app=args.app, evidence=args.evidence)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.attest_live_use",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1
    state["live_use"] = attest
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.attest_live_use",
        state,
        detail={"live_use": {"app": attest["app"], "evidence_len": len(attest["evidence"])}},
    )
    print(f"Live use attested: app={attest['app']}")
    print(f"  evidence: {attest['evidence'][:200]}")
    print_state(state)
    return 0


def cmd_attest_live_http(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.attest_live_http",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        attest = build_live_http_attest(evidence=args.evidence)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.attest_live_http",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1
    state["live_http"] = attest
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.attest_live_http",
        state,
        detail={"live_http": {"evidence_len": len(attest["evidence"])}},
    )
    print("Live HTTP attested (real endpoint, unmocked).")
    print(f"  evidence: {attest['evidence'][:200]}")
    print_state(state)
    return 0


def cmd_attest_windows_surface(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run. Start with: ctl.py start --issue URL", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.attest_windows_surface",
            state,
            decision="reject",
            detail={"reason": "inactive"},
            level="WARNING",
        )
        return 1
    try:
        attest = build_windows_surface_attest(
            reason=args.reason, evidence=args.evidence
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.attest_windows_surface",
            state,
            decision="reject",
            detail={"reason": "invalid", "error": str(exc)},
            level="WARNING",
        )
        return 1
    state["windows_surface"] = attest
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.attest_windows_surface",
        state,
        detail={
            "windows_surface": {
                "reason": attest["reason"],
                "evidence_len": len(attest["evidence"]),
            }
        },
    )
    print(f"Windows surface attested: reason={attest['reason']}")
    print(f"  evidence: {attest['evidence'][:200]}")
    print_state(state)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    """Emit pillar scores for a phase WITHOUT advancing (e.g. PR after recap)."""
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("run_id"):
        print("No run to score.", file=sys.stderr)
        return 1
    _emit_gate_pillars(state, args.phase, args)
    save_run(state, state.get("run_id") or rid)
    print(f"Scored {args.phase} pillars.")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run.", file=sys.stderr)
        _emit_ctl("wrk_e2e.ctl.gate", state, decision="reject", detail={"reason": "inactive", "wanted": args.phase}, level="WARNING")
        return 1
    phase = args.phase
    if state.get("phase") != phase:
        print(
            f"Cannot gate '{phase}': current phase is '{state.get('phase')}'.",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={"reason": "wrong_phase", "wanted": phase, "current": state.get("phase")},
            level="WARNING",
        )
        return 1
    if state.get("awaiting_continue") and not state.get("continuous"):
        print(
            f"Phase '{phase}' already gated; waiting for user continue / ctl.py advance.",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={"reason": "awaiting_continue", "wanted": phase},
            level="WARNING",
        )
        return 1
    if phase == "plan" and state.get("path") not in ("bug", "feat"):
        print(
            "Cannot gate plan: set path first with ctl.py set-path bug|feat",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={"reason": "path_unset", "wanted": phase},
            level="WARNING",
        )
        return 1

    cred_err = require_credentials_for_gate(state, phase)
    if cred_err:
        print(cred_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "required_env",
                "wanted": phase,
                "integrations": state.get("integrations"),
                "error": cred_err,
            },
            level="WARNING",
        )
        return 1

    provider_err = require_provider_for_gate(state, phase)
    if provider_err:
        print(provider_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "providers",
                "wanted": phase,
                "providers": state.get("providers"),
                "error": provider_err,
            },
            level="WARNING",
        )
        return 1

    wallet_err = require_provider_wallet_for_gate(state, phase)
    if wallet_err:
        print(wallet_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "provider_wallets",
                "wanted": phase,
                "providers": state.get("providers"),
                "provider_wallets": state.get("provider_wallets"),
                "error": wallet_err,
            },
            level="WARNING",
        )
        return 1

    work_host_err = require_work_host_for_gate(state, phase)
    if work_host_err:
        print(work_host_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "work_host",
                "wanted": phase,
                "work_host": state.get("work_host"),
                "error": work_host_err,
            },
            level="WARNING",
        )
        return 1

    launch_err = require_launch_source_for_gate(state, phase)
    if launch_err:
        print(launch_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "launch_source",
                "wanted": phase,
                "launch_source": state.get("launch_source"),
                "error": launch_err,
            },
            level="WARNING",
        )
        return 1

    fork_sync_err = require_fork_sync_for_gate(state, phase)
    if fork_sync_err:
        print(fork_sync_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "fork_sync",
                "wanted": phase,
                "error": fork_sync_err,
            },
            level="WARNING",
        )
        return 1

    grok_err = require_grok_desktop_for_gate(state, phase)
    if grok_err:
        print(grok_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "grok_desktop",
                "wanted": phase,
                "grok_desktop": state.get("grok_desktop"),
                "error": grok_err,
            },
            level="WARNING",
        )
        return 1

    cursor_cu_err = require_cursor_desktop_cu_for_gate(state, phase)
    if cursor_cu_err:
        print(cursor_cu_err, file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            decision="reject",
            detail={
                "reason": "cursor_desktop_cu",
                "wanted": phase,
                "cursor_desktop_cu": state.get("cursor_desktop_cu"),
                "error": cursor_cu_err,
            },
            level="WARNING",
        )
        return 1

    if phase == "review":
        review_err = require_review_for_gate(state)
        if review_err:
            print(review_err, file=sys.stderr)
            _emit_ctl(
                "wrk_e2e.ctl.gate",
                state,
                decision="reject",
                detail={
                    "reason": "review_artifact",
                    "wanted": phase,
                    "error": review_err,
                },
                level="WARNING",
            )
            return 1

    completed = list(state.get("completed") or [])
    if phase not in completed:
        completed.append(phase)
    state["completed"] = completed

    # Record this phase's pillar verdicts on the ledger (best-effort, never blocks).
    _emit_gate_pillars(state, phase, args)

    if state.get("continuous", True):
        nxt = next_phase(state)
        if nxt is None:
            state["phase"] = "done"
            state["awaiting_continue"] = False
            state["active"] = False
            state = save_run(state, state.get("run_id") or rid)
            _emit_ctl(
                "wrk_e2e.ctl.gate",
                state,
                detail={"gated": phase, "next": "done", "completed": completed},
            )
            print("Continuous run finished.")
            print_state(state)
            return 0
        state["phase"] = nxt
        state["awaiting_continue"] = False
        state = save_run(state, state.get("run_id") or rid)
        _emit_ctl(
            "wrk_e2e.ctl.gate",
            state,
            detail={"gated": phase, "next": nxt, "completed": completed},
        )
        print(f"PHASE {phase} COMPLETE — continuous advance → {nxt}")
        print_state(state)
        _print_phase_hint(state)
        return 0

    state["awaiting_continue"] = True
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl(
        "wrk_e2e.ctl.gate",
        state,
        detail={"gated": phase, "awaiting_continue": True, "completed": completed},
    )
    print(f"PHASE {phase} COMPLETE — reply continue to proceed.")
    print_state(state)
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    if not state.get("active"):
        print("No active run.", file=sys.stderr)
        return 1
    # Continuous mode auto-advances on gate; advance must not skip phases.
    if state.get("continuous", True):
        print(
            "advance is HITL-only. In continuous mode use: "
            f"ctl.py gate {state.get('phase')}",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.advance",
            state,
            decision="reject",
            detail={"reason": "continuous_mode"},
            level="WARNING",
        )
        return 1
    if not state.get("awaiting_continue"):
        print(
            "Not awaiting continue. Finish the current phase and run: "
            f"ctl.py gate {state.get('phase')}",
            file=sys.stderr,
        )
        _emit_ctl(
            "wrk_e2e.ctl.advance",
            state,
            decision="reject",
            detail={"reason": "not_awaiting"},
            level="WARNING",
        )
        return 1
    if state.get("phase") == "plan" and state.get("path") not in ("bug", "feat"):
        print("Set path before advancing past plan: ctl.py set-path bug|feat", file=sys.stderr)
        return 1

    nxt = next_phase(state)
    if nxt is None:
        state["phase"] = "done"
        state["awaiting_continue"] = False
        state["active"] = False
        state = save_run(state, state.get("run_id") or rid)
        _emit_ctl("wrk_e2e.ctl.advance", state, detail={"next": "done"})
        print("wrk-e2e complete.")
        print_state(state)
        return 0

    prev = state.get("phase")
    state["phase"] = nxt
    state["awaiting_continue"] = False
    state = save_run(state, state.get("run_id") or rid)
    _emit_ctl("wrk_e2e.ctl.advance", state, detail={"from": prev, "to": nxt})
    print(f"Advanced {prev} → {nxt}")
    print_state(state)
    _print_phase_hint(state)
    return 0


def _print_phase_hint(state: dict[str, Any]) -> None:
    phase = state.get("phase")
    path = state.get("path")
    hints = {
        "begin": (
            "Follow wrk-begin triage (skill). Record provider involvement: "
            "ctl.py set-provider --none   OR   "
            "ctl.py set-provider --provider NAME …. "
            "If Provider: Yes, run ctl.py check-provider-wallet "
            "(top-up/unknown hard-stops). "
            "Record required credential env names (required): "
            "ctl.py set-required-env --none   OR   "
            "ctl.py set-required-env --require SOME_API_KEY … "
            "Record work host: "
            "ctl.py set-work-host --remote yes   OR   "
            "ctl.py set-work-host --remote no --local yes|no --mac yes|no [--cwd PATH]. "
            "Record launch source: "
            "ctl.py set-launch-source --source extension|local|other "
            "(extension = only remote + feat bypass). "
            "Then record Grok gates (need + capability): "
            "ctl.py set-grok-desktop --grok-bot yes|no --bug yes|no --desktop yes|no "
            "--interface-ops yes|no [--interface-ops-why \"…\"]. "
            "Record Cursor Desktop CU locks: "
            "ctl.py set-cursor-desktop-cu --desktop yes|no --windows yes|no "
            "--local-cursor yes|no --interface-ops yes|no [--interface-ops-why \"…\"]. "
            "Then: ctl.py gate begin"
        ),
        "plan": (
            "Bug path: follow wrk-bug plan only. Then: ctl.py gate plan\n"
            "Feat path: follow wrk-feat plan only. Then: ctl.py gate plan"
            if path is None
            else (
                "Follow wrk-bug plan only. Then: ctl.py gate plan"
                if path == "bug"
                else "Follow wrk-feat plan only. Then: ctl.py gate plan"
            )
        ),
        "reproduce": (
            "Execute the wrk-bug repro plan; confirm failure with evidence. "
            "If cu_required: drive the live desktop app + "
            "ctl.py attest-cursor-desktop-cu --evidence \"…\". "
            "No fix yet. Then: ctl.py gate reproduce"
        ),
        "implement": (
            "Implement the change. Hooks now allow edits. "
            "If cu_required and not yet attested: "
            "drive the live desktop app + "
            "ctl.py attest-cursor-desktop-cu --evidence \"…\". "
            "Then: ctl.py gate implement"
        ),
        "review": (
            "Follow wrk-rev; write review.json; "
            "python3 review_gate.py validate-review --file review.json; "
            "ctl.py record-review --file review.json. "
            f"If needs_work: wrk-rev-gap-closer closes ALL open issue asks "
            f"(decide/implement/run_live; max {MAX_CLOSER_CYCLES} cycles; "
            "only blocked_env may stay open), then re-review. "
            "Gate only when ready_to_submit: ctl.py gate review"
        ),
        "recap": (
            "Present deliverables/recap. Gate recap re-checks upstream sync "
            "(behind=0). Then: ctl.py gate recap. Before wrk-pr/wrk-push: "
            "ctl.py check-pr-base"
        ),
        "done": "Run finished. ctl.py clear if needed.",
    }
    if phase in hints:
        print(f"\nNEXT: {hints[phase]}")


def cmd_check_pr_base(args: argparse.Namespace) -> int:
    """Hard-stop if current checkout is behind upstream PR base."""
    rid = _run_id_from_args(args)
    state = load_run(rid) if rid else {}
    issue = str(
        getattr(args, "issue", None)
        or (state.get("issue") if state else None)
        or ""
    ).strip()
    if not issue:
        print(
            "No issue ref. Pass --issue owner/repo#n or start a run first.",
            file=sys.stderr,
        )
        return 1
    emit_state = state if state.get("active") else {"issue": issue, "run_id": rid}
    try:
        info = ensure_pr_base_synced(issue=issue)
    except Exception as exc:
        print(f"check-pr-base FAILED: {exc}", file=sys.stderr)
        _emit_ctl(
            "wrk_e2e.ctl.check_pr_base",
            emit_state,
            decision="reject",
            detail={"error": str(exc)},
            level="WARNING",
        )
        return 1
    print(f"check-pr-base OK: {info.get('line')} upstream={info.get('upstream')}")
    if info.get("actions"):
        print(f"  actions: {', '.join(info['actions'])}")
    _emit_ctl(
        "wrk_e2e.ctl.check_pr_base",
        emit_state,
        detail={"line": info.get("line"), "actions": info.get("actions")},
    )
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    rid = _run_id_from_args(args)
    state = load_run(rid)
    _emit_ctl("wrk_e2e.ctl.clear", state, detail={"cleared_run_id": rid or state.get("run_id")})
    cleared = clear_run(rid or state.get("run_id"))
    print("Cleared wrk-e2e state.")
    print_state(cleared)
    return 0


def _add_run_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--run-id",
        default=None,
        help="Per-conversation run id (or set WRK_E2E_RUN_ID / CURSOR_CONVERSATION_ID)",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="wrk-e2e phase controller")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start a wrk-e2e run")
    p_start.add_argument("--issue", required=True, help="Issue URL or owner/repo#n")
    p_start.add_argument(
        "--path",
        choices=["bug", "feat"],
        default=None,
        help="Optional early classification; can set later with set-path",
    )
    p_start.add_argument(
        "--launch-source",
        choices=["extension", "local", "other"],
        default=None,
        help=(
            "Who started this run. extension = only source that allows "
            "remote + feat. Prefer this over a later set-launch-source."
        ),
    )
    p_start.add_argument(
        "--continuous",
        action="store_true",
        default=True,
        help="No HITL (default). Gate auto-advances; keep running phases in-session.",
    )
    p_start.add_argument(
        "--hitl",
        action="store_true",
        help="Pause after each gate and wait for user 'continue' before advancing",
    )
    _add_run_id(p_start)
    p_start.set_defaults(func=cmd_start)

    p_status = sub.add_parser("status", help="Show state")
    _add_run_id(p_status)
    p_status.set_defaults(func=cmd_status)

    p_list = sub.add_parser("list", help="List per-run state files")
    p_list.set_defaults(func=cmd_list)

    p_set = sub.add_parser("set-path", help="Set bug|feat classification")
    p_set.add_argument("path", choices=["bug", "feat"])
    _add_run_id(p_set)
    p_set.set_defaults(func=cmd_set_path)

    p_req = sub.add_parser(
        "set-required-env",
        help="Record required credential env names (required before gate begin)",
    )
    p_req.add_argument(
        "--none",
        action="store_true",
        help="No real API key / third-party credential required",
    )
    p_req.add_argument(
        "--require",
        action="append",
        default=[],
        help="Required env var name from issue/repo (repeatable)",
    )
    p_req.add_argument(
        "--external-app",
        default=None,
        help="Special/external app name when credentials are Yes (e.g. discord)",
    )
    _add_run_id(p_req)
    p_req.set_defaults(func=cmd_set_required_env)

    p_prov = sub.add_parser(
        "set-provider",
        help="Record whether the issue relates to any provider (required before gate begin)",
    )
    p_prov.add_argument(
        "--none",
        action="store_true",
        help="Issue is not provider-related",
    )
    p_prov.add_argument(
        "--provider",
        action="append",
        default=[],
        help="Provider name from issue/labels/docs (repeatable)",
    )
    _add_run_id(p_prov)
    p_prov.set_defaults(func=cmd_set_provider)

    p_wallet = sub.add_parser(
        "check-provider-wallet",
        help=(
            "Live wallet/credits check for each Provider: Yes name "
            "(required before gate begin; top-up/unknown hard-stops)"
        ),
    )
    _add_run_id(p_wallet)
    p_wallet.set_defaults(func=cmd_check_provider_wallet)

    p_wh = sub.add_parser(
        "set-work-host",
        help=(
            "Record remote / local / Mac work-host gates "
            "(required before gate begin)"
        ),
    )
    p_wh.add_argument(
        "--remote",
        required=True,
        choices=["yes", "no"],
        help="Operator is remote host",
    )
    p_wh.add_argument(
        "--local",
        choices=["yes", "no"],
        default=None,
        help="Operator is local (required when --remote no)",
    )
    p_wh.add_argument(
        "--mac",
        choices=["yes", "no"],
        default=None,
        help="Host is macOS (required when --remote no)",
    )
    p_wh.add_argument(
        "--cwd",
        default=None,
        help="Absolute work-tree path (required when local Mac)",
    )
    _add_run_id(p_wh)
    p_wh.set_defaults(func=cmd_set_work_host)

    p_ls = sub.add_parser(
        "set-launch-source",
        help=(
            "Record who started this run (required before gate begin). "
            "extension = only source that allows remote + feat"
        ),
    )
    p_ls.add_argument(
        "--source",
        required=True,
        choices=["extension", "local", "other"],
        help="extension | local | other",
    )
    _add_run_id(p_ls)
    p_ls.set_defaults(func=cmd_set_launch_source)

    p_attest = sub.add_parser(
        "attest-live-use",
        help="Attest live Discord (or other) actions before gate reproduce/implement",
    )
    p_attest.add_argument(
        "--app",
        required=True,
        help="External app that was used live (currently: discord)",
    )
    p_attest.add_argument(
        "--evidence",
        required=True,
        help="Short description of the live action + outcome (no secrets)",
    )
    _add_run_id(p_attest)
    p_attest.set_defaults(func=cmd_attest_live_use)

    p_http = sub.add_parser(
        "attest-live-http",
        help="Attest a real, UNMOCKED HTTP call to the API (required before "
        "gate reproduce/implement when API = Yes, non-Discord)",
    )
    p_http.add_argument(
        "--evidence",
        required=True,
        help="Real request (method+endpoint or client call) + status/response "
        "outcome — no secrets, no mocks/fixtures/cassettes",
    )
    _add_run_id(p_http)
    p_http.set_defaults(func=cmd_attest_live_http)


    p_mp = sub.add_parser(
        "attest-mac-playbook",
        help=(
            "Attest Mac computer-use playbook was used "
            "(only when playbook_required: interface-ops + bug + grok-bot)"
        ),
    )
    p_mp.add_argument(
        "--evidence",
        required=True,
        help="Live Mac desktop action + outcome (no secrets)",
    )
    _add_run_id(p_mp)
    p_mp.set_defaults(func=cmd_attest_mac_playbook)

    p_gd = sub.add_parser(
        "set-grok-desktop",
        help=(
            "Record Grok playbook need (interface-ops from issue) + capability "
            "locks (required before gate begin)"
        ),
    )
    p_gd.add_argument("--grok-bot", required=True, choices=["yes", "no"], help="Operated from Grok Bot (capability)")
    p_gd.add_argument("--bug", required=True, choices=["yes", "no"], help="Issue is a bug")
    p_gd.add_argument("--desktop", required=True, choices=["yes", "no"], help="Desktop app surface (step 2; not playbook need)")
    p_gd.add_argument(
        "--interface-ops",
        required=True,
        choices=["yes", "no"],
        help=(
            "Issue flow/repro requires operating/navigating an interface "
            "(not API/CLI/config/logs-only)"
        ),
    )
    p_gd.add_argument(
        "--interface-ops-why",
        default="",
        help="Short issue-grounded why for --interface-ops",
    )
    _add_run_id(p_gd)
    p_gd.set_defaults(func=cmd_set_grok_desktop)

    p_cdc = sub.add_parser(
        "set-cursor-desktop-cu",
        help=(
            "Record Cursor Desktop CU need (interface-ops) + capability "
            "(not-windows + local Cursor; bugs and features)"
        ),
    )
    p_cdc.add_argument(
        "--desktop",
        required=True,
        choices=["yes", "no"],
        help="Desktop app surface (wrk-begin step 2; not CU need alone)",
    )
    p_cdc.add_argument(
        "--windows",
        required=True,
        choices=["yes", "no"],
        help="Windows surface / Windows host required for this work",
    )
    p_cdc.add_argument(
        "--local-cursor",
        required=True,
        choices=["yes", "no"],
        help="Operator is local Cursor (not remote, not Grok Bot operator path)",
    )
    p_cdc.add_argument(
        "--interface-ops",
        required=True,
        choices=["yes", "no"],
        help=(
            "Issue flow/repro requires operating/navigating an interface "
            "(not API/CLI/config/logs-only)"
        ),
    )
    p_cdc.add_argument(
        "--interface-ops-why",
        default="",
        help="Short issue-grounded why for --interface-ops",
    )
    _add_run_id(p_cdc)
    p_cdc.set_defaults(func=cmd_set_cursor_desktop_cu)

    p_acdc = sub.add_parser(
        "attest-cursor-desktop-cu",
        help=(
            "Attest specialty Grok-bot computer-use was used "
            "(only when cu_required)"
        ),
    )
    p_acdc.add_argument(
        "--evidence",
        required=True,
        help="Live Desktop CU action via specialty Grok bot + outcome (no secrets)",
    )
    _add_run_id(p_acdc)
    p_acdc.set_defaults(func=cmd_attest_cursor_desktop_cu)

    p_win = sub.add_parser(
        "attest-windows-surface",
        help="Justify a Windows host before using one",
    )
    p_win.add_argument(
        "--reason",
        required=True,
        choices=["intrinsic", "cheap-repro-failed"],
        help=(
            "intrinsic = OS marker on the cited failing path; "
            "cheap-repro-failed = cheap faithful surface ran and could not reproduce"
        ),
    )
    p_win.add_argument(
        "--evidence",
        required=True,
        help=(
            "file:line + OS marker (intrinsic) or cheap surface run + why it failed "
            "(cheap-repro-failed). The reporter's env box is not evidence."
        ),
    )
    _add_run_id(p_win)
    p_win.set_defaults(func=cmd_attest_windows_surface)

    p_rr = sub.add_parser(
        "record-review",
        help="Record validated wrk-rev review.json (required before gate review)",
    )
    p_rr.add_argument("--file", required=True, help="Path to review.json")
    _add_run_id(p_rr)
    p_rr.set_defaults(func=cmd_record_review)

    p_rc = sub.add_parser(
        "record-closer",
        help="Record validated wrk-rev-gap-closer closer.json",
    )
    p_rc.add_argument("--file", required=True, help="Path to closer.json")
    _add_run_id(p_rc)
    p_rc.set_defaults(func=cmd_record_closer)

    p_gate = sub.add_parser("gate", help="Mark current phase complete")
    p_gate.add_argument("phase", choices=["begin", "plan", "reproduce", "implement", "review", "recap"])
    p_gate.add_argument("--pillar", action="append", metavar="NAME=VALUE",
                        help="Per-phase pillar verdict (repeatable); dtype from registry")
    p_gate.add_argument("--provenance", default=None,
                        help="Judging tier for this phase's pillars (self, derived:git, wrk-rev, …)")
    _add_run_id(p_gate)
    p_gate.set_defaults(func=cmd_gate)

    p_cpb = sub.add_parser(
        "check-pr-base",
        help="Hard-fail if checkout is behind upstream (run before wrk-pr / wrk-push)",
    )
    p_cpb.add_argument(
        "--issue",
        default=None,
        help="Issue URL or owner/repo#n (default: active run issue)",
    )
    _add_run_id(p_cpb)
    p_cpb.set_defaults(func=cmd_check_pr_base)

    p_score = sub.add_parser("score", help="Emit pillar scores for a phase without advancing (e.g. pr after recap)")
    p_score.add_argument("phase", choices=["plan", "reproduce", "implement", "review", "pr"])
    p_score.add_argument("--pillar", action="append", metavar="NAME=VALUE",
                         help="Per-phase pillar verdict (repeatable)")
    p_score.add_argument("--provenance", default=None, help="Judging tier")
    _add_run_id(p_score)
    p_score.set_defaults(func=cmd_score)

    p_adv = sub.add_parser("advance", help="Advance after user continue (HITL only)")
    _add_run_id(p_adv)
    p_adv.set_defaults(func=cmd_advance)

    p_clear = sub.add_parser("clear", help="Clear active run")
    _add_run_id(p_clear)
    p_clear.set_defaults(func=cmd_clear)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
