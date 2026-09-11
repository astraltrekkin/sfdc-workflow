#!/usr/bin/env python3
"""Local audit log for wrk-e2e gates (jsonl only)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(
    os.environ.get("WRK_E2E_STATE_DIR")
    or str(Path.home() / ".cursor" / "wrk-e2e")
).expanduser()
AUDIT_PATH = STATE_DIR / "audit.jsonl"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_audit(event: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", now())
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass


def emit(
    event_type: str,
    *,
    run_id: str | None = None,
    decision: str | None = None,
    phase: str | None = None,
    issue: str | None = None,
    path: str | None = None,
    detail: dict[str, Any] | None = None,
    level: str = "DEFAULT",
) -> None:
    append_audit(
        {
            "type": event_type,
            "run_id": run_id,
            "decision": decision,
            "phase": phase,
            "issue": issue,
            "path": path,
            "level": level,
            "detail": detail or {},
            "ts": now(),
        }
    )


def emit_pillars(
    phase: str,
    *,
    run_id: str | None,
    issue: str | None = None,
    path: str | None = None,
    pillars: list[tuple[str, Any, str, str | None]],
    provenance: str = "self",
) -> None:
    if not run_id or not pillars:
        return
    append_audit(
        {
            "type": "pillars",
            "phase": phase,
            "run_id": run_id,
            "issue": issue,
            "path": path,
            "provenance": provenance,
            "pillars": [p[0] for p in pillars],
            "ts": now(),
        }
    )
