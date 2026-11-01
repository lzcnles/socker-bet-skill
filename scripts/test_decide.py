#!/usr/bin/env python3
"""Logic verification for odds_engine.decide().

NOT an accuracy measurement. These are synthetic analyze() results used to prove
the priority chain and the 浅盘避雷 veto behave as specified. Real accuracy can
only come from real odds snapshots — see backtest_batch.py.

Run:  python3 scripts/test_decide.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_engine import decide, SIDE_CN  # noqa: E402


def mk(dd=None, wd=None, lw=None, side="home", lb_ch=None, wd_signed=None,
       push=None, dpp=None, label="T", lb_full=None, heat_cur=None,
       main_hcp=None, mw_home=None, mw_away=None):
    total = sum((push or {}).values())
    heat = None
    if dpp is not None or heat_cur is not None:
        heat = {"dpp": dpp, "n": 3}
        if heat_cur is not None:
            heat["cur"] = heat_cur
    return {
        "mid": "test", "label": label, "dd": dd, "wd": wd, "lb_water": lw,
        "lb_side": side, "wd_signed": wd_signed,
        "lb": lb_full if lb_full is not None else {"ch": lb_ch},
        "push": push or {}, "push_total": total,
        "heat": heat,
        "main_hcp_med": main_hcp, "main_w_home_med": mw_home, "main_w_away_med": mw_away,
    }


CASES = []

def case(name, inputs, kwargs, expect_decision, expect_blocked=None):
    CASES.append((name, inputs, kwargs, expect_decision, expect_blocked))


# --- veto priority: the bug this refactor exists to fix -------------------
case("浅盘避雷 + 宽平水同场 -> 必须否决宽平水",
     mk(dd=-0.25, lw=0.83, wd=0.15, lb_ch=-0.5, push={"home": 30, "draw": 5, "away": 7}),
     {}, "不出", ["宽平水->下盘不败", "压主共识"])

case("浅盘避雷 + 热度升温 -> 不翻案, 仅警告",
     mk(dd=-0.5, lw=0.90, wd=0.20, lb_ch=-0.75, dpp=[9.9, -1.0, -8.9]),
     {}, "不出", None)

# --- 数据质量硬过滤 (priority 0) -------------------------------------------
case("立博缺失 -> 数据质量硬不出",
     mk(dd=-0.25, lw=0.60, wd=0.30, lb_ch=0.5, side="home",
        push={"home": 50, "draw": 3, "away": 2}),
     {"data_quality": "missing"}, "不出", None)

case("立博轨迹 >72h -> 数据质量硬不出",
     mk(dd=-0.25, lw=0.60, wd=0.30, lb_ch=0.5, side="home",
        push={"home": 50, "draw": 3, "away": 2}),
     {"data_quality": "stale"}, "不出", None)

# --- 规则6 ----------------------------------------------------------------
case("规则6 全条件 + 热度共振 -> 机械等权 ⭐, 不加码",
     mk(dd=-0.25, lw=0.70, wd=0.27, lb_ch=-0.5, dpp=[7.0, -2.0, -5.0],
        push={"home": 30, "draw": 4, "away": 7}),
     {}, "主队净胜命题", None)

case("规则6 + 让方防线伤缺 2 人 -> 硬降级, 只保留不败",
     mk(dd=-0.25, lw=0.70, wd=0.27, lb_ch=-0.5, push={"home": 30, "draw": 4, "away": 7}),
     {"fav_def_injuries": 2}, "主队不败", ["规则6->净胜命题"])

case("规则6 + 压主 >=90% -> 只保留不败观察, 不出净胜",
     mk(dd=-0.25, lw=0.60, wd=0.27, lb_ch=0.5, side="home",
        push={"home": 50, "draw": 3, "away": 2}),
     {}, "主队不败", ["规则6->净胜命题"])

case("压客>=40 + 立博让方(客队)水位未降/盘口未升 -> 不出",
     mk(dd=0.0, lw=1.05, wd=0.10, lb_ch=-0.5, side="away",
        push={"home": 2, "draw": 18, "away": 46},
        lb_full={"ch": -0.5, "ih": -0.5, "iw": 0.80, "cw": 0.80, "il": 1.05, "cl": 1.05}),
     {}, "不出", ["压客共识"])

# 11-01: veto scoped to 立博让方 = 客队. Real 10-31 inputs (23:15 / 23:25 snapshots).
case("布伦特福德-森林 2:0: 主让 + 压客 52, 热度主且主流主水 0.86 -> 以保护为准, 主队不败",
     mk(dd=0.25, lw=1.05, wd=0.19, lb_ch=0.5, side="home",
        push={"home": 2, "draw": 31, "away": 52}, dpp=[-2.5, 1.1, 1.4],
        heat_cur=[44.5, 26.5, 29.0], main_hcp=0.25, mw_home=0.86, mw_away=1.02,
        lb_full={"ch": 0.5, "ih": 0.5, "iw": 0.85, "cw": 1.05, "il": 0.83, "cl": 0.70}),
     {}, "主队不败", ["压客共识"])

case("维拉-富勒姆 1:1: 主让 + 压客 42, 热度主且主流主水 0.84 -> 以保护为准, 主队不败",
     mk(dd=0.25, lw=1.00, wd=0.16, lb_ch=0.5, side="home",
        push={"home": 3, "draw": 34, "away": 42}, dpp=[-4.0, 0.7, 3.3],
        heat_cur=[44.5, 26.9, 28.6], main_hcp=0.25, mw_home=0.84, mw_away=1.035,
        lb_full={"ch": 0.5, "ih": 0.5, "iw": 1.00, "cw": 1.00, "il": 0.73, "cl": 0.73}),
     {}, "主队不败", ["压客共识"])

# 封盘快照: 立博国米 1.00 -> 0.95 已降水, 否决不触发, 由保护线拦下.
case("AC米兰-国米 3:1: 压客 49, 热度客但主流客水 1.025 未保护 -> 不出",
     mk(dd=0.0, lw=0.95, wd=0.075, lb_ch=-0.5, side="away",
        push={"home": 1, "draw": 51, "away": 49}, dpp=[-6.8, 1.9, 4.9],
        heat_cur=[25.3, 27.4, 47.3], main_hcp=-0.5, mw_home=0.87, mw_away=1.025,
        lb_full={"ch": -0.5, "ih": -0.5, "iw": 0.73, "cw": 0.75, "il": 1.00, "cl": 0.95}),
     {}, "不出", ["压客共识"])

case("考文垂-桑德兰 3:1: 压客 49, 热度客但主流客水 1.025 未保护 -> 不出 (旧版: 客队不败)",
     mk(dd=0.25, lw=1.25, wd=0.225, lb_ch=-0.5, side="away",
        push={"home": 2, "draw": 27, "away": 49}, dpp=[-3.2, 0.2, 2.9],
        heat_cur=[31.6, 28.1, 40.3], main_hcp=-0.25, mw_home=0.865, mw_away=1.025,
        lb_full={"ch": -0.5, "ih": -0.5, "iw": 0.50, "cw": 0.57, "il": 1.45, "cl": 1.25}),
     {}, "不出", ["压客共识"])

case("基础概率>=75% + 反向压客共识 -> 主队胜",
     mk(dd=-0.125, lw=0.80, wd=0.145, lb_ch=2.5, side="home",
        push={"home": 9, "draw": 37, "away": 38},
        dpp=[-0.3, 0.2, 0.1], heat_cur=[85.8, 9.5, 4.7]),
     {}, "主队胜", None)

case("规则6 + 压平 >=15 -> 降半档",
     mk(dd=-0.25, lw=0.70, wd=0.27, lb_ch=-0.5, push={"home": 20, "draw": 22, "away": 4}),
     {}, "主队净胜命题", None)

case("规则6 + wd=0.21 -> 满足触发线, 降半档 (wd<0.21 历史 0/2)",
     mk(dd=-0.25, lw=0.70, wd=0.21, lb_ch=-0.5, push={"home": 30, "draw": 4, "away": 7}),
     {}, "主队净胜命题", None)

case("规则6 + wd=0.18 低于 0.205 触发线 -> 规则6 不触发, 走共识",
     mk(dd=-0.25, lw=0.70, wd=0.18, lb_ch=-0.5, push={"home": 30, "draw": 4, "away": 7}),
     {}, "主队不败", None)

# --- 宽平水阈值收紧 -------------------------------------------------------
case("宽平水 wd=0.10 (旧口径会出单) -> 不出",
     mk(dd=0.0, lw=0.92, wd=0.10, lb_ch=0.0, push={"home": 5, "draw": 3, "away": 4}),
     {}, "无信号", None)

case("宽平水 wd=0.15 -> 下盘不败",
     mk(dd=0.0, lw=0.92, wd=0.15, lb_ch=0.0, push={"home": 5, "draw": 3, "away": 4}),
     {}, "下盘不败", None)

case("宽平水 + 立博让方水>=1.05 -> 降级观察 (wd 需 >=0.13 才进入该分支)",
     mk(dd=0.0, lw=1.05, wd=0.15, lb_ch=0.0, push={"home": 5, "draw": 3, "away": 4}),
     {}, "不出", None)

case("宽平水 wd=0.10 且让方水 1.05 -> 阈值未达, 无信号",
     mk(dd=0.0, lw=1.05, wd=0.10, lb_ch=0.0, push={"home": 5, "draw": 3, "away": 4}),
     {}, "无信号", None)

# --- 共识 ----------------------------------------------------------------
case("压客 42 -> 强制不败格式(从不写客胜)",
     mk(dd=0.5, lw=0.90, wd=0.10, lb_ch=0.5, side="away",
        push={"home": 5, "draw": 6, "away": 42}),
     {}, "客队不败", None)

case("压主 30 -> 主队不败",
     mk(dd=0.5, lw=0.90, wd=0.10, lb_ch=0.5, side="home",
        push={"home": 30, "draw": 6, "away": 5}),
     {}, "主队不败", None)

# --- 不碰类绝不给方向 -----------------------------------------------------
case("深盘高水 -> 不出, 不给方向",
     mk(dd=0.0, lw=1.10, wd=0.05, lb_ch=-1.0, push={"home": 5, "draw": 3, "away": 4}),
     {}, "不出", None)

case("压平 42 孤独场 -> 无信号(压平是环境项)",
     mk(dd=0.0, lw=0.92, wd=0.05, lb_ch=0.0, push={"home": 8, "draw": 42, "away": 6}),
     {}, "无信号", None)


def main():
    fails = 0
    for name, inputs, kwargs, exp_dec, exp_blocked in CASES:
        got = decide(inputs, **kwargs)
        ok = got["decision"] == exp_dec
        if exp_blocked:
            blocked_rules = [b["rule"] for b in got["blocked"]]
            ok = ok and all(r in blocked_rules for r in exp_blocked)
        status = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{status}] {name}")
        print(f"        -> decision={got['decision']!r} tier={got['tier']} rule={got['rule']!r}")
        for b in got["blocked"]:
            print(f"           blocked: {b['rule']} ({b['reason']})")
        for w in got["warnings"]:
            print(f"           warn: {w}")
        if not ok:
            print(f"           EXPECTED decision={exp_dec!r} blocked>={exp_blocked}")
    print(f"\n{len(CASES) - fails}/{len(CASES)} logic cases passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
