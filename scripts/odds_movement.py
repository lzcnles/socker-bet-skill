#!/usr/bin/env python3
"""Compare opening, previous, and latest decimal-odds snapshots.

Input JSON:
{
  "snapshots": [
    {"label": "opening", "timestamp": "...", "odds": {"0-1": 5.0}},
    {"label": "previous", "timestamp": "...", "odds": {"0-1": 5.8}},
    {"label": "latest", "timestamp": "...", "odds": {"0-1": 5.5}}
  ]
}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCORE_RE = re.compile(r"^(\d+)[-:]([0-9]+)$")


def pct(old: float, new: float) -> float:
    return (new / old - 1.0) * 100.0


def score_total(name: str) -> int | None:
    match = SCORE_RE.match(name.strip())
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2))


def classify(name: str, opening: float, latest: float) -> str:
    change = pct(opening, latest)
    total = score_total(name)
    tail = latest > 30 or (total is not None and total >= 5)

    if abs(change) < 0.5:
        return "锁价"
    if change > 0:
        return "升赔"
    if tail and change <= -20:
        return "尾部数字异常"
    if tail:
        return "尾部轻降"
    if change <= -15:
        return "强异常候选"
    if change <= -8:
        return "有意义降水"
    if change <= -5:
        return "轻度压价"
    return "普通波动"


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if not isinstance(snapshot.get("odds"), dict):
        raise ValueError("Each snapshot must contain an 'odds' object")
    for name, value in snapshot["odds"].items():
        if not isinstance(value, (int, float)) or value <= 1:
            raise ValueError(f"Invalid decimal odds for {name!r}: {value!r}")


def analyze(payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) < 2:
        raise ValueError("Provide at least two snapshots")
    for snapshot in snapshots:
        validate_snapshot(snapshot)

    opening = snapshots[0]
    previous = snapshots[-2]
    latest = snapshots[-1]
    outcomes = sorted(set(opening["odds"]) & set(latest["odds"]))
    rows: list[dict[str, Any]] = []

    for outcome in outcomes:
        open_price = float(opening["odds"][outcome])
        latest_price = float(latest["odds"][outcome])
        previous_price = previous["odds"].get(outcome)
        recent_change = None
        if isinstance(previous_price, (int, float)):
            recent_change = pct(float(previous_price), latest_price)
        rows.append(
            {
                "outcome": outcome,
                "opening": open_price,
                "previous": previous_price,
                "latest": latest_price,
                "opening_to_latest_pct": round(pct(open_price, latest_price), 1),
                "previous_to_latest_pct": (
                    round(recent_change, 1) if recent_change is not None else None
                ),
                "total_goals": score_total(outcome),
                "classification": classify(outcome, open_price, latest_price),
            }
        )
    return sorted(rows, key=lambda row: row["opening_to_latest_pct"])


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| 结果 | 初赔 | 上一快照 | 最新 | 初→临 | 上次→最新 | 分类 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        previous = "—" if row["previous"] is None else f'{row["previous"]:.2f}'
        recent = (
            "—"
            if row["previous_to_latest_pct"] is None
            else f'{row["previous_to_latest_pct"]:+.1f}%'
        )
        lines.append(
            f'| {row["outcome"]} | {row["opening"]:.2f} | {previous} | '
            f'{row["latest"]:.2f} | {row["opening_to_latest_pct"]:+.1f}% | '
            f'{recent} | {row["classification"]} |'
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file containing odds snapshots")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        rows = analyze(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
