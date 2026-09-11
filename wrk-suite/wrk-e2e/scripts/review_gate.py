"""Deterministic review / gap-closer artifact validation for wrk-e2e.

Skills write review.json / closer.json. This module validates consistency
(issue coverage vs statuses vs verdict) so READY cannot contradict open
requirements. Issue text and repo paths are opaque — only structure and
status consistency are enforced.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
MAX_CLOSER_CYCLES = 4

REQ_STATUSES = frozenset({"met", "partial", "missing"})
ISSUE_COVERAGE = frozenset({"complete", "incomplete"})
PATCH_READINESS = frozenset({"ready", "needs_work"})
VERDICTS = frozenset({"ready_to_submit", "needs_work", "not_started"})
CLOSER_TAGS = frozenset(
    {"implement", "decide_and_implement", "run_live", "blocked_env"}
)
CLOSER_RESULTS = frozenset({"closed", "open"})
# Tags that count as code-changing closes for implement_count / tree checks.
CODE_CLOSE_TAGS = frozenset({"implement", "decide_and_implement"})
# Only blocked_env may leave a gap open.
OPEN_ALLOWED_TAGS = frozenset({"blocked_env"})

# Softening language that must not appear next to a ready verdict / notes.
FORBIDDEN_SOFTENING: list[tuple[str, re.Pattern[str]]] = [
    ("partial", re.compile(r"\bpartial\b", re.I)),
    ("scoped", re.compile(r"\bscoped\b", re.I)),
    ("incident patch", re.compile(r"\bincident\s+patch\b", re.I)),
]


def artifact_dir(run_id: str, *, runs_dir: Optional[Path] = None) -> Path:
    """Per-run artifacts directory under the wrk-e2e runs store."""
    if runs_dir is not None:
        base = runs_dir
    else:
        import os

        base = Path(
            os.environ.get("WRK_E2E_STATE_DIR")
            or str(Path.home() / ".cursor" / "wrk-e2e")
        ).expanduser() / "runs"
    return base / run_id / "artifacts"


# --------------------------------------------------------------------------------------
# Review validation
# --------------------------------------------------------------------------------------
def _as_str(val: Any) -> str:
    return str(val).strip() if val is not None else ""


def _check_forbidden_softening(text: str, field: str) -> list[str]:
    errs: list[str] = []
    blob = text or ""
    for label, pat in FORBIDDEN_SOFTENING:
        if pat.search(blob):
            errs.append(f"{field}: forbidden softening language ({label})")
    return errs


def validate_review(data: Any) -> list[str]:
    """Return error messages if review artifact is inconsistent; empty = OK."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["review: must be a JSON object"]

    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        errs.append("review: requirements must be a list")
        requirements = []

    statuses: list[str] = []
    for i, row in enumerate(requirements):
        if not isinstance(row, dict):
            errs.append(f"review: requirements[{i}] must be an object")
            continue
        rid = _as_str(row.get("id"))
        if not rid:
            errs.append(f"review: requirements[{i}].id is required")
        status = _as_str(row.get("status"))
        if status not in REQ_STATUSES:
            errs.append(
                f"review: requirements[{i}].status must be one of "
                + ", ".join(sorted(REQ_STATUSES))
            )
        else:
            statuses.append(status)
        # summary / evidence are opaque strings — only presence for non-empty id rows
        if rid and "summary" not in row:
            errs.append(f"review: requirements[{i}].summary is required")
        if rid and "evidence" not in row:
            errs.append(f"review: requirements[{i}].evidence is required")

    issue_coverage = _as_str(data.get("issue_coverage"))
    if issue_coverage not in ISSUE_COVERAGE:
        errs.append(
            "review: issue_coverage must be one of "
            + ", ".join(sorted(ISSUE_COVERAGE))
        )

    patch_readiness = _as_str(data.get("patch_readiness"))
    if patch_readiness not in PATCH_READINESS:
        errs.append(
            "review: patch_readiness must be one of "
            + ", ".join(sorted(PATCH_READINESS))
        )

    verdict = _as_str(data.get("verdict"))
    if verdict not in VERDICTS:
        errs.append(
            "review: verdict must be one of " + ", ".join(sorted(VERDICTS))
        )

    git_tree = _as_str(data.get("git_tree"))
    if not git_tree and verdict != "not_started":
        errs.append("review: git_tree is required unless verdict is not_started")

    closer_cycle = data.get("closer_cycle")
    if not isinstance(closer_cycle, int) or isinstance(closer_cycle, bool):
        errs.append("review: closer_cycle must be an integer")
    elif closer_cycle < 0:
        errs.append("review: closer_cycle must be >= 0")
    elif closer_cycle > MAX_CLOSER_CYCLES:
        errs.append(
            f"review: closer_cycle {closer_cycle} exceeds MAX_CLOSER_CYCLES "
            f"({MAX_CLOSER_CYCLES})"
        )

    all_met = bool(statuses) and all(s == "met" for s in statuses)
    any_open = any(s != "met" for s in statuses)
    # Empty requirements: treat as incomplete unless explicitly not_started
    if not statuses and verdict not in ("not_started",):
        if issue_coverage == "complete":
            errs.append(
                "review: issue_coverage complete requires at least one met requirement"
            )

    if any_open and issue_coverage == "complete":
        errs.append(
            "review: issue_coverage must be incomplete when any requirement "
            "is partial or missing"
        )
    if any_open and verdict == "ready_to_submit":
        errs.append(
            "review: verdict cannot be ready_to_submit while any requirement "
            "is partial or missing"
        )
    if any_open and verdict == "not_started":
        errs.append(
            "review: verdict not_started is inconsistent with listed requirements"
        )

    if issue_coverage == "complete" and statuses and not all_met:
        errs.append(
            "review: issue_coverage complete requires every requirement status met"
        )

    if verdict == "ready_to_submit":
        if not all_met or not statuses:
            errs.append(
                "review: ready_to_submit requires every requirement status met"
            )
        if patch_readiness != "ready":
            errs.append(
                "review: ready_to_submit requires patch_readiness ready"
            )
        if issue_coverage != "complete":
            errs.append(
                "review: ready_to_submit requires issue_coverage complete"
            )

    # Softening language forbidden on verdict_note and free-text note fields
    for field in ("verdict_note", "note", "headline"):
        if field in data and data[field] is not None:
            errs.extend(_check_forbidden_softening(_as_str(data[field]), f"review.{field}"))

    if verdict == "ready_to_submit":
        # Also scan evidence strings for softening-as-excuse (optional but in plan)
        for i, row in enumerate(requirements):
            if isinstance(row, dict):
                ev = _as_str(row.get("evidence"))
                # only flag if evidence claims readiness via softening — skip empty
                if ev and FORBIDDEN_SOFTENING[0][1].search(ev):
                    # Do not fail on evidence mentioning "partial" from prior review notes
                    # Plan says: optional verdict_note / free-text fields — already covered
                    pass

    return errs


# --------------------------------------------------------------------------------------
# Closer validation
# --------------------------------------------------------------------------------------
def validate_closer(
    data: Any,
    *,
    prior_review: Optional[dict[str, Any]] = None,
    prior_closer: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Return error messages if closer artifact is inconsistent; empty = OK."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["closer: must be a JSON object"]

    closer_cycle = data.get("closer_cycle")
    if not isinstance(closer_cycle, int) or isinstance(closer_cycle, bool):
        errs.append("closer: closer_cycle must be an integer")
    elif closer_cycle < 1:
        errs.append("closer: closer_cycle must be >= 1")
    elif closer_cycle > MAX_CLOSER_CYCLES:
        errs.append(
            f"closer: closer_cycle {closer_cycle} exceeds MAX_CLOSER_CYCLES "
            f"({MAX_CLOSER_CYCLES})"
        )

    if prior_closer and isinstance(prior_closer, dict):
        prev = prior_closer.get("closer_cycle")
        if isinstance(prev, int) and isinstance(closer_cycle, int):
            if closer_cycle != prev + 1:
                errs.append(
                    f"closer: closer_cycle must be prior+1 (got {closer_cycle}, "
                    f"prior {prev})"
                )

    if prior_review and isinstance(prior_review, dict):
        prev_cycle = prior_review.get("closer_cycle")
        if (
            isinstance(prev_cycle, int)
            and isinstance(closer_cycle, int)
            and closer_cycle < 1
        ):
            pass

    gaps = data.get("gaps")
    if not isinstance(gaps, list):
        errs.append("closer: gaps must be a list")
        gaps = []

    implement_from_gaps = 0
    for i, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            errs.append(f"closer: gaps[{i}] must be an object")
            continue
        if not _as_str(gap.get("requirement_id")):
            errs.append(f"closer: gaps[{i}].requirement_id is required")
        tag = _as_str(gap.get("tag"))
        if tag not in CLOSER_TAGS:
            errs.append(
                f"closer: gaps[{i}].tag must be one of "
                + ", ".join(sorted(CLOSER_TAGS))
            )
        result = _as_str(gap.get("result"))
        if result not in CLOSER_RESULTS:
            errs.append(
                f"closer: gaps[{i}].result must be one of "
                + ", ".join(sorted(CLOSER_RESULTS))
            )
        if result == "open":
            if tag and tag not in OPEN_ALLOWED_TAGS:
                errs.append(
                    f"closer: gaps[{i}] result open is only allowed for tag "
                    f"blocked_env (got {tag!r}); issue asks must be closed"
                )
        if tag in CODE_CLOSE_TAGS and result == "closed":
            implement_from_gaps += 1

    # Prior review open requirements must each appear in gaps[]
    if prior_review and isinstance(prior_review, dict):
        prior_reqs = prior_review.get("requirements")
        if isinstance(prior_reqs, list):
            open_ids = {
                _as_str(r.get("id"))
                for r in prior_reqs
                if isinstance(r, dict)
                and _as_str(r.get("status")) in ("partial", "missing")
                and _as_str(r.get("id"))
            }
            covered = {
                _as_str(g.get("requirement_id"))
                for g in gaps
                if isinstance(g, dict)
            }
            missing_ids = sorted(open_ids - covered)
            if missing_ids:
                errs.append(
                    "closer: gaps[] must include every open prior requirement id; "
                    "missing: " + ", ".join(missing_ids)
                )

    implement_count = data.get("implement_count")
    if not isinstance(implement_count, int) or isinstance(implement_count, bool):
        errs.append("closer: implement_count must be an integer")
    elif implement_count < 0:
        errs.append("closer: implement_count must be >= 0")
    elif isinstance(implement_count, int) and implement_count != implement_from_gaps:
        if implement_count > 0 and implement_from_gaps == 0:
            errs.append(
                "closer: implement_count > 0 but no gaps with tag "
                "implement|decide_and_implement and result closed"
            )

    before = _as_str(data.get("git_tree_before"))
    after = _as_str(data.get("git_tree_after"))
    if not before:
        errs.append("closer: git_tree_before is required")
    if not after:
        errs.append("closer: git_tree_after is required")
    if (
        isinstance(implement_count, int)
        and implement_count > 0
        and before
        and after
        and before == after
    ):
        errs.append(
            "closer: implement_count > 0 requires git_tree_after != git_tree_before"
        )

    return errs


# --------------------------------------------------------------------------------------
# Gate helper for ctl
# --------------------------------------------------------------------------------------
def require_review_for_gate(state: dict[str, Any]) -> Optional[str]:
    """
    Return an error message if gate review must be blocked, else None.

    Requires a recorded review with verdict ready_to_submit that passes
    validate_review. If closer_history is non-empty, latest closer must
    also validate against the prior review when available.
    """
    review = state.get("review")
    if not isinstance(review, dict):
        return (
            "Cannot gate review: no review artifact recorded. "
            "After wrk-rev, run: ctl.py record-review --file review.json"
        )

    review_errs = validate_review(review)
    if review_errs:
        return (
            "Cannot gate review: recorded review failed validation:\n  - "
            + "\n  - ".join(review_errs)
        )

    verdict = _as_str(review.get("verdict"))
    if verdict != "ready_to_submit":
        return (
            "Cannot gate review: latest review verdict is "
            f"{verdict!r}; need ready_to_submit. "
            "If needs_work, run wrk-rev-gap-closer (max "
            f"{MAX_CLOSER_CYCLES} cycles) then re-record review."
        )

    closer_history = state.get("closer_history") or []
    closer = state.get("closer")
    if closer_history or closer:
        if not isinstance(closer, dict):
            return (
                "Cannot gate review: closer_history is non-empty but latest "
                "closer artifact is missing. Run: ctl.py record-closer --file closer.json"
            )
        # Prefer the review that preceded the latest closer when history exists
        prior = review
        review_history = state.get("review_history") or []
        if review_history and isinstance(review_history[-1], dict):
            # latest review is state.review; prior pass is last in history
            prior = review_history[-1]
        closer_errs = validate_closer(
            closer,
            prior_review=prior if isinstance(prior, dict) else None,
            prior_closer=(
                closer_history[-2]
                if len(closer_history) >= 2
                and isinstance(closer_history[-2], dict)
                else None
            ),
        )
        if closer_errs:
            return (
                "Cannot gate review: latest closer failed validation:\n  - "
                + "\n  - ".join(closer_errs)
            )

    return None


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Validate wrk-rev / wrk-rev-gap-closer artifacts"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_rev = sub.add_parser("validate-review", help="Validate review.json")
    p_rev.add_argument("--file", required=True, help="Path to review.json")

    p_cl = sub.add_parser("validate-closer", help="Validate closer.json")
    p_cl.add_argument("--file", required=True, help="Path to closer.json")
    p_cl.add_argument(
        "--review-file",
        default=None,
        help="Optional prior review.json for cross-checks",
    )

    args = p.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "validate-review":
        data = _load_json(args.file)
        errs = validate_review(data)
        if errs:
            print("review_gate validate-review FAILED:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print("review_gate validate-review OK")
        return 0

    if args.cmd == "validate-closer":
        data = _load_json(args.file)
        prior = None
        if args.review_file:
            prior = _load_json(args.review_file)
            if not isinstance(prior, dict):
                print("review_gate: --review-file must be a JSON object", file=sys.stderr)
                return 1
        errs = validate_closer(data, prior_review=prior)
        if errs:
            print("review_gate validate-closer FAILED:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print("review_gate validate-closer OK")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
