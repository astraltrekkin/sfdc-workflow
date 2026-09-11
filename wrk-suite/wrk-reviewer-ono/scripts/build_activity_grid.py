#!/usr/bin/env python3
"""Build an inline-table GitHub-style contribution pixel grid for repo activity.

Reads JSON from stdin: {"YYYY-MM-DD": count, ...}
Writes HTML table fragment to stdout (52 weeks x 7 days, Sunday-first).

Usage:
  python3 scripts/build_activity_grid.py --repo REPO < day_counts.json
  python3 scripts/build_activity_grid.py --repo owner/repo < day_counts.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone


LEVEL_COLORS = {
    0: "#161b22",
    1: "#0e4429",
    2: "#006d32",
    3: "#26a641",
    4: "#39d353",
}


def level_for(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 10:
        return 3
    return 4


def cell(color: str) -> str:
    return (
        f'<td style="width:10px;height:10px;background:{color};'
        f'font-size:0;line-height:0;">&nbsp;</td>'
    )


def spacer_row() -> str:
    return '<tr><td style="height:2px;font-size:0;line-height:0;">&nbsp;</td></tr>'


def short_repo_name(repo: str) -> str:
    """Accept OWNER/REPO or bare REPO; caption uses the short name."""
    repo = repo.strip().strip("/")
    if "/" in repo:
        return repo.rsplit("/", 1)[-1]
    return repo or "repo"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default="repo",
        help="Target repo (OWNER/REPO or short name) for the caption",
    )
    args = parser.parse_args()
    label = short_repo_name(args.repo)

    raw = sys.stdin.read().strip() or "{}"
    counts = json.loads(raw)
    normalized: dict[date, int] = {}
    for key, value in counts.items():
        day = datetime.strptime(str(key)[:10], "%Y-%m-%d").date()
        normalized[day] = normalized.get(day, 0) + int(value)

    today = datetime.now(timezone.utc).date()
    # End on the Saturday of the current week; start 52 weeks of Sundays before that.
    days_since_sunday = (today.weekday() + 1) % 7  # Mon=0 … Sun=6 → Sun=0
    end = today + timedelta(days=(6 - days_since_sunday))  # Saturday
    start = end - timedelta(days=52 * 7 - 1)  # Sunday 52 weeks ago

    weeks: list[list[date]] = []
    cursor = start
    while cursor <= end:
        weeks.append([cursor + timedelta(days=i) for i in range(7)])
        cursor += timedelta(days=7)

    week_tds: list[str] = []
    for week in weeks:
        rows: list[str] = []
        for i, day in enumerate(week):
            color = LEVEL_COLORS[level_for(normalized.get(day, 0))]
            rows.append(f"<tr>{cell(color)}</tr>")
            if i < 6:
                rows.append(spacer_row())
        inner = "".join(rows)
        week_tds.append(
            '<td style="vertical-align:top;padding-right:2px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0">{inner}</table>'
            "</td>"
        )

    total_events = sum(normalized.values())
    html = (
        '<table role="presentation" cellpadding="0" cellspacing="0">'
        f"<tr>{''.join(week_tds)}</tr></table>"
    )
    # Caption helper on stderr for the agent
    print(
        f"{label} activity · last 12 months · {total_events} events observed",
        file=sys.stderr,
    )
    sys.stdout.write(html)


if __name__ == "__main__":
    main()
