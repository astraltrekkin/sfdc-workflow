#!/usr/bin/env python3
"""Per-run wrk-e2e state store.

Layout:
  ~/.cursor/wrk-e2e/state.json          — last-touched / legacy single-run mirror
  ~/.cursor/wrk-e2e/runs/<run_id>.json  — isolated per-conversation run
  ~/.cursor/wrk-e2e/last_run_id         — last ctl start/gate run id
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(
    os.environ.get("WRK_E2E_STATE_DIR")
    or str(Path.home() / ".cursor" / "wrk-e2e")
).expanduser()
STATE_PATH = STATE_DIR / "state.json"
RUNS_DIR = STATE_DIR / "runs"
LAST_RUN_PATH = STATE_DIR / "last_run_id"

_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9._-]+")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "active": False,
        "run_id": None,
        "issue": None,
        "path": None,
        "phase": None,
        "awaiting_continue": False,
        "continuous": True,
        "completed": [],
        # Per-phase pillar verdicts (set at each gate): {phase: {pillars, provenance}}
        "phases": {},
        # Live integrations from wrk-begin step 10 (set via ctl set-integrations)
        "integrations": None,
        # Provider involvement from wrk-begin step 10 (ctl set-provider)
        "providers": None,
        # Wallet / credits check (ctl check-provider-wallet) when Provider: Yes
        "provider_wallets": None,
        # Work host / local Mac root from wrk-begin (ctl set-work-host)
        "work_host": None,
        # wrk-rev / gap-closer machine-readable artifacts (ctl record-review / record-closer)
        "review": None,
        "review_history": [],
        "closer": None,
        "closer_history": [],
        "updated_at": now(),
    }


def sanitize_run_id(run_id: str) -> str:
    cleaned = _SAFE_RUN_ID.sub("-", run_id.strip())
    return cleaned[:180] or uuid.uuid4().hex


def resolve_run_id(
    explicit: str | None = None,
    *,
    create_if_missing: bool = False,
) -> str | None:
    if explicit:
        return sanitize_run_id(explicit)
    env = os.environ.get("WRK_E2E_RUN_ID") or os.environ.get("CURSOR_CONVERSATION_ID")
    if env:
        return sanitize_run_id(env)
    if LAST_RUN_PATH.exists():
        try:
            val = LAST_RUN_PATH.read_text().strip()
            if val:
                return sanitize_run_id(val)
        except OSError:
            pass
    if create_if_missing:
        return uuid.uuid4().hex
    return None


def run_path(run_id: str) -> Path:
    return RUNS_DIR / f"{sanitize_run_id(run_id)}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def load_run(run_id: str | None = None) -> dict[str, Any]:
    rid = resolve_run_id(run_id)
    if rid:
        data = _read_json(run_path(rid))
        if data is not None:
            base = empty_state()
            base.update(data)
            base["run_id"] = rid
            return base
    legacy = _read_json(STATE_PATH)
    if legacy is not None:
        base = empty_state()
        base.update(legacy)
        return base
    return empty_state()


def save_run(state: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rid = sanitize_run_id(run_id or state.get("run_id") or resolve_run_id(create_if_missing=True) or uuid.uuid4().hex)
    state = dict(state)
    state["run_id"] = rid
    state["updated_at"] = now()
    text = json.dumps(state, indent=2) + "\n"
    run_path(rid).write_text(text)
    # Mirror for legacy readers / single-chat convenience
    STATE_PATH.write_text(text)
    try:
        LAST_RUN_PATH.write_text(rid + "\n")
    except OSError:
        pass
    return state


def clear_run(run_id: str | None = None) -> dict[str, Any]:
    rid = resolve_run_id(run_id)
    cleared = empty_state()
    if rid:
        path = run_path(rid)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        # Only wipe legacy mirror if it pointed at this run
        legacy = _read_json(STATE_PATH) or {}
        if legacy.get("run_id") in (None, rid) or not legacy.get("active"):
            STATE_PATH.write_text(json.dumps(cleared, indent=2) + "\n")
        return cleared
    STATE_PATH.write_text(json.dumps(cleared, indent=2) + "\n")
    return cleared


def list_runs() -> list[dict[str, Any]]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.glob("*.json")):
        data = _read_json(path)
        if data:
            data.setdefault("run_id", path.stem)
            out.append(data)
    return out


def extract_conversation_id(payload: dict[str, Any]) -> str | None:
    for key in ("conversation_id", "conversationId", "session_id", "sessionId"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return sanitize_run_id(val)
    # Nested common shapes
    for nest_key in ("input", "metadata", "context"):
        nest = payload.get(nest_key)
        if isinstance(nest, dict):
            found = extract_conversation_id(nest)
            if found:
                return found
    env = os.environ.get("WRK_E2E_RUN_ID") or os.environ.get("CURSOR_CONVERSATION_ID")
    return sanitize_run_id(env) if env else None


def load_state_for_hook(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve the active run for this hook invocation.

    Prefer runs/<conversation_id>.json. If missing but legacy state.json is
    active and unbound (or already bound to this id), adopt it so a ctl start
    without --run-id still gates the chat that first hits a hook.
    """
    cid = extract_conversation_id(payload)
    if cid:
        existing = _read_json(run_path(cid))
        if existing is not None:
            base = empty_state()
            base.update(existing)
            base["run_id"] = cid
            return base

        legacy = _read_json(STATE_PATH) or {}
        if legacy.get("active"):
            legacy_rid = legacy.get("run_id")
            if legacy_rid in (None, "", cid):
                adopted = dict(legacy)
                adopted["run_id"] = cid
                save_run(adopted, cid)
                return adopted
        return {"active": False, "run_id": cid}

    return load_run(None)
