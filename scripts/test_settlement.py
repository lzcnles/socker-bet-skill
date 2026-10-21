#!/usr/bin/env python3
"""Asian-handicap settlement verification.

The settlement function is the highest-risk piece of the backtest: if it is
wrong, every 让球 accuracy number downstream is wrong. Each expectation below
was derived by hand from split stakes, not copied from program output.

Key convention these cases pin down (I got this wrong twice while writing them):
a quarter line splits into the two neighbouring lines, where "neighbouring"
means half a step either side of the line AS QUOTED, not as its magnitude.
  away -0.25 (客让平半) = 半注 平手 / 半注 客让半球   -> halves [0.0, 0.5]
  home -1.25 (主让一球半) = 半注 主让一球 / 半注 主让球半 -> halves [1.0, 1.5]

Run:  python3 scripts/test_settlement.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_batch import ah_settle  # noqa: E402

# (bet_side, line, home_goals, away_goals, expected)
CASES = [
    # 平手盘
    ("home", 0.0, 1, 0, "W"), ("home", 0.0, 0, 0, "P"), ("home", 0.0, 0, 1, "L"),
    # 整数盘
    ("home", 1.0, 2, 0, "W"), ("home", 1.0, 1, 0, "P"), ("home", 1.0, 0, 1, "L"),
    # 半球盘
    ("home", 0.5, 1, 0, "W"), ("home", 0.5, 0, 0, "L"),
    # 平半盘: 半注平手 / 半注半球
    ("home", 0.25, 1, 0, "W"), ("home", 0.25, 0, 0, "HL"), ("home", 0.25, 0, 1, "L"),
    # 半一盘: 半注半球 / 半注一球
    ("home", 0.75, 1, 0, "HW"), ("home", 0.75, 2, 0, "W"), ("home", 0.75, 0, 0, "L"),
    # 球半盘
    ("home", 1.5, 2, 0, "W"), ("home", 1.5, 1, 0, "L"),
    # 一球半盘: 半注一球 / 半注球半
    ("home", 1.25, 2, 0, "W"), ("home", 1.25, 1, 0, "HL"), ("home", 1.25, 3, 0, "W"),
    # 客队让球
    ("away", 0.5, 0, 1, "W"), ("away", 0.5, 1, 1, "L"),
    ("away", 0.25, 0, 1, "W"), ("away", 0.25, 1, 1, "HL"), ("away", 0.25, 2, 1, "L"),
    ("away", 0.75, 1, 3, "W"), ("away", 0.75, 1, 2, "HW"), ("away", 0.75, 1, 1, "L"),
    ("away", 1.0, 0, 1, "P"), ("away", 1.0, 1, 1, "L"),
    ("away", 1.25, 1, 3, "W"), ("away", 1.25, 1, 2, "HL"),
    ("away", 1.5, 0, 2, "W"), ("away", 1.5, 0, 1, "L"),
    # 负号写法 (盘口记法) 必须与正号等价
    ("home", -0.25, 0, 0, "HL"), ("away", -0.25, 1, 1, "HL"), ("away", -1.25, 1, 2, "HL"),
]


def main() -> int:
    bad = 0
    for side, line, hg, ag, exp in CASES:
        got = ah_settle(side, line, hg, ag)
        if got != exp:
            bad += 1
            print(f"[FAIL] {side:<4} line={line:<6} {hg}:{ag} -> {got} (期望 {exp})")
    print(f"亚盘结算: {len(CASES) - bad}/{len(CASES)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
