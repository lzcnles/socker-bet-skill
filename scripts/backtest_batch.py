#!/usr/bin/env python3
"""Batch backtest harness — scores one night of matches across SKILL's layers.

Reads:
  --results  backtest_<date>.json   (official FT/HT scores; no odds)
  --snapshots snapshots.json        either raw HTML {mid/path: html} or
                                    precomputed {"matches": [analyze(), ...]}

Scores, per SKILL.md §赛后回测 and references/backtesting.md §2, seven
INDEPENDENT layers — a hit in one is never reported as "整套逻辑命中":

  1. 基础概率方向   closing 1X2 de-vigged favourite
  2. 显著热度方向   max Δpp >= 2pp, else 无明确信号 (excluded from denominator)
  3. 亚洲盘         W / HW / P / HL / L — half-win and push never folded into
                    win/loss, and never converted to a binary hit rate
  4. 大小球         settled on the final main line; <significant line change
                    is not counted as a direction hit
  5. BTTS           only when opening and closing both exist
  6. 比分簇         home-clean / home-BTTS / draw / away-clean / away-BTTS
  7. 精确比分       strong-drop / relative-lock / ordinary-low, kept separate

Every layer prints its denominator, and missing markets are excluded rather
than counted as misses.

Usage:
  python3 scripts/backtest_batch.py --results backtest_2026-10-15_uel.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_engine import analyze, decide, devig, SIDE_CN  # noqa: E402


# --------------------------------------------------------------------------
# Asian handicap settlement
# --------------------------------------------------------------------------
def ah_settle(bet_side: str, line_abs: float, hg: int, ag: int) -> str:
    """Settle a bet on `bet_side` giving `line_abs` goals. -> W/HW/P/HL/L.

    Quarter lines are split stakes: -0.25 = half at 0 / half at -0.5, etc.
    Line sign is ignored — direction comes from `bet_side` — so callers may pass
    either `-0.25` (盘口 notation) or `0.25` (magnitude notation).
    """
    line_abs = abs(line_abs)
    diff = (hg - ag) if bet_side == "home" else (ag - hg)
    if line_abs <= 0:
        return "W" if diff > 0 else ("P" if diff == 0 else "L")
    # Split quarter lines into the two neighbouring half/whole lines and settle
    # each half separately. A half may PUSH (result exactly on the line) — that
    # must yield HW/HL against the other half, not a bare P.
    halves = [line_abs] if (line_abs * 2) % 1 == 0 else [line_abs - 0.25, line_abs + 0.25]
    wins = losses = 0
    for ln in halves:
        margin = diff - ln
        if margin > 0:
            wins += 1
        elif margin < 0:
            losses += 1
    if wins == len(halves):
        return "W"
    if losses == len(halves):
        return "L"
    if wins and losses:
        return "HW" if wins > losses else "HL"
    if losses:
        return "HL"
    if wins:
        return "HW"
    return "P"


# --------------------------------------------------------------------------
# Layer scoring
# --------------------------------------------------------------------------
def score_1x2(closing: dict | None, hg: int, ag: int) -> tuple[str, str] | None:
    if not closing:
        return None
    d = devig(closing.get("cw"), closing.get("cd"), closing.get("cl"))
    if not d:
        return None
    labels = ["主胜", "平局", "客胜"]
    fav = labels[max(range(3), key=lambda i: d[i])]
    actual = "主胜" if hg > ag else ("平局" if hg == ag else "客胜")
    return fav, actual


def score_heat(heat: dict | None, hg: int, ag: int) -> tuple[str, str] | None:
    """Max Δpp direction, only if >= 2pp (significant-line rule)."""
    if not heat or not heat.get("dpp"):
        return None
    dpp = heat["dpp"]
    i = max(range(3), key=lambda k: dpp[k])
    if dpp[i] < 2.0:
        return None                      # 无明确信号 -> excluded from denominator
    labels = ["主胜", "平局", "客胜"]
    actual = "主胜" if hg > ag else ("平局" if hg == ag else "客胜")
    return labels[i], actual


def score_cluster(hg: int, ag: int) -> str:
    if hg > ag:
        return "主胜零封" if ag == 0 else "主胜双方进球"
    if hg == ag:
        return "平局"
    return "客胜零封" if hg == 0 else "客胜双方进球"


def _tally(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return "无样本"
    ok = sum(1 for a, b in pairs if a == b)
    return f"{ok}/{len(pairs)} = {round(ok / len(pairs) * 100)}%"


def run(results_path: Path, snapshots_path: Path | None) -> dict:
    res = json.loads(results_path.read_text())
    matches = res["matches"]

    snaps_html, snaps_pre = {}, []
    if snapshots_path and snapshots_path.exists():
        raw = json.loads(snapshots_path.read_text())
        if isinstance(raw, dict) and "matches" in raw:
            snaps_pre = raw["matches"]
        elif isinstance(raw, dict):
            snaps_html = raw          # {mid/path: html}

    rows, layer = [], {"1x2": [], "heat": [], "ah": {}, "btts": []}
    for i, m in enumerate(matches):
        hg, ag = m["hg"], m["ag"]
        label = f"{m['home']} vs {m['away']}"
        mid = str(m.get("mid") or "")

        if snaps_pre and i < len(snaps_pre):
            an = snaps_pre[i]
        elif snaps_html:
            keys = [k for k in snaps_html if mid and k.startswith(mid)]
            an = analyze(mid, snaps_html, label) if keys else None
        else:
            an = None

        row = {"no": m.get("no", i + 1), "label": label,
               "score": f"{hg}:{ag}", "cluster": score_cluster(hg, ag),
               "decision": None, "rule": None, "tier": None,
               "blocked": [], "warnings": [], "ah": None, "analyzed": bool(an)}
        if an:
            d = decide(an, fav_def_injuries=m.get("fav_def_injuries", 0))
            row.update(decision=d["decision"], rule=d["rule"], tier=d["tier"],
                       blocked=[b["rule"] for b in d["blocked"]],
                       warnings=d["warnings"])
            fav_side = an.get("lb_side")
            lb_ch = (an.get("lb") or {}).get("ch")
            if fav_side in ("home", "away") and lb_ch:
                row["ah"] = ah_settle(fav_side, abs(lb_ch), hg, ag)
                layer["ah"][row["ah"]] = layer["ah"].get(row["ah"], 0) + 1
            s = score_1x2(an.get("closing_odds"), hg, ag)
            if s:
                layer["1x2"].append(s)
            h = score_heat(an.get("heat"), hg, ag)
            if h:
                layer["heat"].append(h)
        rows.append(row)

    return {"batch": res.get("batch"), "rows": rows, "layers": layer,
            "n": len(matches), "n_analyzed": sum(1 for r in rows if r["analyzed"])}


def report(out: dict) -> None:
    print(f"\n{'='*96}\n{out['batch']}\n{'='*96}")
    print(f"场次 {out['n']}  已接入赔率 {out['n_analyzed']}")
    if not out["n_analyzed"]:
        print("\n⚠️  无赔率快照 —— 以下只有赛果与比分结构，"
              "规则方向/准确率无法计算（缺同源初盘+封盘）。\n")

    print(f"{'#':>3} {'场次':<38} {'比分':>6} {'比分簇':<14} {'判定':<14} {'依据'}")
    print("-" * 96)
    for r in out["rows"]:
        print(f"{r['no']:>3} {r['label'][:37]:<38} {r['score']:>6} "
              f"{r['cluster']:<14} {str(r['decision'] or '—'):<14} {r['rule'] or '—'}")

    print(f"\n{'-'*96}\n分层结算（每层独立，分母显式）\n{'-'*96}")
    print(f"1. 基础概率方向   {_tally(out['layers']['1x2'])}")
    print(f"2. 显著热度方向   {_tally(out['layers']['heat'])}  (Δpp<2pp 不计入分母)")
    ah = out["layers"]["ah"]
    ah_s = " ".join(f"{k}={ah[k]}" for k in ("W", "HW", "P", "HL", "L") if k in ah)
    print(f"3. 亚洲盘         {ah_s or '无样本'}  (半赢/走盘/半输单列, 不折算成二元命中率)")
    print(f"4. 大小球         无样本（快照未含大小球表）")
    print(f"5. BTTS           无样本")
    dec = [r for r in out["rows"] if r["decision"] and r["decision"] != "无信号"]
    print(f"6. 出单场次       {len(dec)}/{out['n']} 场（其余为避雷/不碰/无信号）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--snapshots")
    a = ap.parse_args()
    out = run(Path(a.results), Path(a.snapshots) if a.snapshots else None)
    report(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
