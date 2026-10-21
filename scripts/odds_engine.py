#!/usr/bin/env python3
"""Rule engine for SKILL.md — mechanical, no eyeballing.

Reads the raw HTML snapshots captured from fenxi.zgzcw.com and computes the
quantities the SKILL rules are written against: 立博 dd/wd, 让方水位,
压价家数, and 四机构热度 (Δpp).

Two data sources are needed per match:
  {mid}/ypdb    亚洲盘表 — 立博 + 主流四家 (ＳＢ/*, 澳*, 易*, 36*) 的初/现盘口与水位
  {mid}/bjop    欧赔表 — 全域博彩公司的初/现胜平负 (压价家数 + 热度法)
  {mid}/zhishu  立博单家轨迹页 (optional but authoritative, see below)

⚠️ ypdb 滞后修正 (added 2026-10-10, backtesting.md 第 27 批 发现 4)
------------------------------------------------------------------
ypdb 表里立博那一行**滞后于立博自己的轨迹页**。实测：意大利-土耳其场
ypdb 的立博现值停在「赛前4时55分 0.95」，而轨迹页最新已是「赛前55分 1.10」;
法国-比利时场同样差一条。这会让「深盘高水」(让方 ≥1.05) 等阈值漏判。

SKILL 强制规则第 3 条本来就写明「只有同一公司或同一追踪源的初赔与当前价
才能计算降水」——立博轨迹页才是那个源。因此本引擎默认用轨迹页最新一条
**覆盖** ypdb 的立博现值，再计算 dd/wd。覆盖前的原值保留在 lb_ypdb 里备查。

Usage:
    from odds_engine import analyze, parse_zhishu
    snapshots = json.load(open("snapshots.json"))
    r = analyze("4518040", snapshots, "意大利 vs 土耳其")
"""
import re
import statistics as st

HCP = {"平手": 0.0, "平/半": 0.25, "半球": 0.5, "半/一": 0.75, "一球": 1.0,
       "一/球半": 1.25, "球半": 1.5, "球半/两": 1.75, "两球": 2.0, "两/两半": 2.25,
       "两半": 2.5, "两半/三": 2.75, "三球": 3.0, "三/三半": 3.25, "三半": 3.5,
       "三半/四": 3.75, "四球": 4.0}

# 主流对照公司 — 用于 dd (盘口档差) 与 wd (让方水位差)
MAIN = ["ＳＢ/*", "澳*", "易*", "36*"]
# 四机构热度法 — zgzcw 无 Bet365, 故用威*/立*/韦* 三家并标注 (SKILL 允许)
HEAT = ["威*", "立*", "韦*"]


def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip()


def _tab(html, tab):
    """Slice out one bf-tab-0N table from a fenxi page."""
    m = re.search(r'class="bf-tab-0%d"(.*?)(?=<table|</body>|$)' % tab, html, re.S)
    return m.group(1) if m else ""


def _cells(td_html):
    """Read a fenxi <td>: prefer the data attribute, fall back to the text."""
    da = re.search(r'\bdata="([^"]*)"', td_html)
    return (da.group(1) if da else None), strip_tags(td_html)


def ov(v):
    """Odds cell -> float, tolerating ↑/↓ movement markers."""
    t = re.sub(r'[↑↓]', '', str(v)).strip()
    try:
        return float(t)
    except ValueError:
        return None


def hcp_text(t):
    """Handicap text -> signed number. '受' prefix means the HOME side receives."""
    t = re.sub(r'[↑↓]', '', str(t)).strip()
    if not t:
        return None
    neg = '受' in t
    base = HCP.get(t.replace('受', '').strip())
    if base is None:
        return None
    return -base if neg else base


def hcpv(v, txt):
    """Handicap cell -> signed number, preferring the text over the data attr."""
    t = re.sub(r'[↑↓]', '', str(txt)).strip()
    h = hcp_text(t) if t else None
    if h is None:
        h = hcp_text(str(v))
    if h is None:
        try:
            h = float(v)
        except (TypeError, ValueError):
            return None
    return h


def parse_ypdb(html, tab=2):
    """亚洲盘表 -> {company: {'raw': [(data, text) x6], 'tds': [...]}}"""
    out = {}
    for row in re.finditer(r'<tr[^>]*>(.*?)</tr>', _tab(html, tab), re.S):
        r = row.group(1)
        tds = re.findall(r'<td[^>]*>.*?</td>', r, re.S)
        if len(tds) < 8:
            continue
        name = strip_tags(tds[1])
        if not name:
            continue
        out[name] = {"raw": [_cells(t) for t in tds[2:8]], "tds": tds}
    return out


def parse_odds(html, tab=2):
    """欧赔表 -> {company: dict(iw,id,il, cw,cd,cl)} (initial / current 胜平负)"""
    out = {}
    for row in re.finditer(r'<tr[^>]*>(.*?)</tr>', _tab(html, tab), re.S):
        r = row.group(1)
        tds = re.findall(r'<td[^>]*>.*?</td>', r, re.S)
        if len(tds) < 8:
            continue
        name = strip_tags(tds[1])
        if not name or name in out:
            continue
        nums = [ov(_cells(t)[0]) if _cells(t)[0] is not None else ov(_cells(t)[1])
                for t in tds[2:8]]
        out[name] = dict(iw=nums[0], id=nums[1], il=nums[2],
                         cw=nums[3], cd=nums[4], cl=nums[5])
    return out


def parse_zhishu(html):
    """立博轨迹页 -> list of snapshots, newest first."""
    out = []
    if not html:
        return out
    for row in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        tds = [strip_tags(x) for x in
               re.findall(r'<td[^>]*>.*?</td>', row.group(1), re.S)]
        if len(tds) >= 6 and re.match(r'^\d+$', tds[0].strip()):
            out.append(dict(seq=tds[0], time=tds[1], rel=tds[2],
                            hw=ov(tds[3]), hcp=tds[4], aw=ov(tds[5])))
    return out


def devig(w, d, l):
    """Odds -> (p_home, p_draw, p_away, payout) with the overround removed."""
    if None in (w, d, l) or w <= 1 or d <= 1 or l <= 1:
        return None
    s = 1 / w + 1 / d + 1 / l
    return (1 / w / s, 1 / d / s, 1 / l / s, 1 / s)


def _side(h):
    if h is None:
        return None
    return "home" if h > 0 else ("away" if h < 0 else "level")


def analyze(mid, htmls, label, use_trajectory=True):
    """Compute one match's rule inputs.

    use_trajectory=True (default) overrides 立博's current line with the latest
    entry from its own trajectory page — see the module docstring.
    """
    yp = parse_ypdb(htmls.get(f"{mid}/ypdb", ""))
    bo = parse_odds(htmls.get(f"{mid}/bjop", ""), 2)
    out = {"mid": mid, "label": label, "lb": None, "dd": None, "wd": None,
           "push": {}, "heat": None, "push_total": 0,
           "lb_from_trajectory": False}

    lb = None
    if "立*" in yp:
        v = yp["立*"]["raw"]
        lb = dict(iw=ov(v[0][0]), ih=hcpv(v[1][0], v[1][1]), il=ov(v[2][0]),
                  cw=ov(v[3][0]), ch=hcpv(v[4][0], v[4][1]), cl=ov(v[5][0]))
        out["lb_ypdb"] = dict(lb)

    if use_trajectory:
        traj = parse_zhishu(htmls.get(f"{mid}/zhishu", ""))
        if traj:
            latest, first = traj[0], traj[-1]
            th = hcp_text(latest.get("hcp"))
            got = (latest.get("hw") is not None and latest.get("aw") is not None
                   and th is not None)
            if lb is None:
                # 立博 has no ypdb row for this match — its own trajectory page
                # still carries the line, so fall back to it entirely.
                if got:
                    lb = dict(iw=first.get("hw"), ih=hcp_text(first.get("hcp")),
                              il=first.get("aw"),
                              cw=latest["hw"], ch=th, cl=latest["aw"])
                    out["lb_from_trajectory"] = True
                    out["lb_traj_only"] = True
                    out["lb_traj_rel"] = latest.get("rel")
            elif got:
                out["lb_traj_stale"] = (lb["cw"], lb["ch"], lb["cl"]) != \
                                       (latest["hw"], th, latest["aw"])
                out["lb_traj_rel"] = latest.get("rel")
                lb = dict(lb, cw=latest["hw"], ch=th, cl=latest["aw"])
                out["lb_from_trajectory"] = True

    out["lb"] = lb

    if lb is not None and lb.get("ch") is not None:
        mains = {n: yp[n] for n in MAIN if n in yp}
        if mains:
            mh = [hcpv(d["raw"][4][0], d["raw"][4][1]) for d in mains.values()]
            mh = [h for h in mh if h is not None]
            if mh:
                med = st.median(mh)
                out["main_hcp_med"] = med
                out["dd"] = round(abs(lb["ch"]) - abs(med), 3)
                s = _side(lb["ch"])
                out["lb_side"] = s
                if s in ("home", "away"):
                    w_lb = lb["cw"] if s == "home" else lb["cl"]
                    idx = 3 if s == "home" else 5
                    ws = [ov(d["raw"][idx][0]) for d in mains.values()]
                    ws = [w for w in ws if w is not None]
                    if ws and w_lb is not None:
                        out["wd"] = round(abs(w_lb - st.median(ws)), 3)
                        out["wd_signed"] = round(w_lb - st.median(ws), 3)
                        out["lb_water"] = w_lb
                        out["main_water_med"] = st.median(ws)

    pk = {"home": 0, "draw": 0, "away": 0}
    tot = 0
    for d in bo.values():
        if d["iw"] is None or d["cw"] is None:
            continue
        tot += 1
        if d["cw"] < d["iw"] - 0.005:
            pk["home"] += 1
        if d["cd"] < d["id"] - 0.005:
            pk["draw"] += 1
        if d["cl"] < d["il"] - 0.005:
            pk["away"] += 1
    out["push"] = pk
    out["push_total"] = tot

    acc_i, acc_c, n = [0.0] * 3, [0.0] * 3, 0
    for c in HEAT:
        if c not in bo:
            continue
        d = bo[c]
        a = devig(d["iw"], d["id"], d["il"])
        b = devig(d["cw"], d["cd"], d["cl"])
        if not a or not b:
            continue
        for i in range(3):
            acc_i[i] += a[i]
            acc_c[i] += b[i]
        n += 1
    if n:
        out["heat"] = {
            "n": n,
            "init": [round(x / n * 100, 1) for x in acc_i],
            "cur": [round(x / n * 100, 1) for x in acc_c],
            "dpp": [round((acc_c[i] - acc_i[i]) / n * 100, 1) for i in range(3)],
        }
    return out


def rules(r):
    """Apply the SKILL rule chain to one analyze() result -> list of tags."""
    tags = []
    lb, p = r.get("lb") or {}, r.get("push") or {}
    dd, wd, lw, side = r.get("dd"), r.get("wd"), r.get("lb_water"), r.get("lb_side")
    n = r.get("push_total") or 0

    def pct(k):
        return f"{p.get(k, 0)}/{n}={round(p.get(k, 0) / n * 100)}%" if n else "?"

    if dd is not None and lw is not None:
        if dd <= -0.25 and lw > 0.75:
            tags.append("浅盘避雷(主流盘不碰)")
        if dd <= -0.25 and lw <= 0.75 and (wd or 0) >= 0.205:
            tags.append(f"规则6->净胜命题(让方={side})")
        if abs(dd) < 1e-9 and 0.08 <= (wd or 0) <= 0.2:
            tags.append("宽平水->下盘不败")
        if abs(lb.get("ch") or 0) >= 1.0 and lw >= 1.05:
            tags.append("深盘高水->让球盘不碰")
        if dd >= 0.5 and lw <= 0.95 and (r.get("wd_signed") or 0) <= -0.08:
            tags.append("深盘低水->正路")
        ch = lb.get("ch")
        if ch is not None and side in ("home", "away"):
            uw = lb.get("cl") if side == "home" else lb["cw"]
            if uw is not None and uw <= 0.70:
                opp = "客队" if side == "home" else "主队"
                tags.append(f"受让方({opp})超低水{uw}->不败命题")
    if p.get("draw", 0) >= 30:
        tags.append(f"压平{pct('draw')}(已降级为环境项,不出单)")
    if p.get("home", 0) >= 25:
        tags.append(f"压主{pct('home')}")
    if p.get("away", 0) >= 25:
        tags.append(f"压客{pct('away')}")
    h = r.get("heat")
    if h:
        if max(h["dpp"]) >= 5:
            tags.append(f"热度升温+{max(h['dpp'])}pp")
        if min(h["dpp"]) <= -5:
            tags.append(f"热度消退{min(h['dpp'])}pp")
    return tags


# ---------------------------------------------------------------------------
# decide() — improved rule chain, 2026-10-20
#
# Why this exists alongside rules(): rules() only *labels* a match, so a
# 避雷 condition and an opposite bet signal can both fire on the same match
# (e.g. 浅盘避雷 + 宽平水→下盘不败). SKILL.md is explicit that 浅盘避雷 takes
# priority over everything else, but a tag list cannot express priority — the
# old consumer had to remember to check. That is exactly how the 10-15 欧联
# batch ended up using the since-deleted 立博让方水位方向 clause to override a
# 避雷 reading. decide() makes the veto structural: when it fires, no betting
# signal is emitted at all, and the suppressed candidates are returned in
# blocked[] so the avoidance can still be scored.
#
# Changes vs rules(), each tied to documented evidence in backtesting.md:
#   1. 浅盘避雷 is a hard veto, not a tag.                      (82%, 全场最高)
#   2. 宽平水 threshold tightened 0.08 -> 0.13.  wd 0.08-0.12 measured
#      1/5 = 20%, wd >=0.13 measured 3/3.  (weak-band MISSes)
#   3. 深盘高水 demoted to 不碰 only — never a direction.
#      56% and explicitly negative-value vs the 70% base rate.
#   4. 压平 >=30 stays an environment note only. 6/8 = 75%, formally 否决.
#   5. 压客 >=25 forces 不败 format (not 胜). 客队共识近 15 场错 6.
#   6. 主队共识 1.8-2.5 odds band forces 不败 format.  (FC东京/金泉/特鲁瓦)
#   7. 规则6 carries an explicit hard-downgrade flag for 让方防线/门将伤缺>=2;
#      the engine cannot see lineups, so the caller must supply it.
#      The downgrade now keeps the 不败 observation (SKILL wording), instead
#      of returning a blanket 不出.  Napoli 4:3 Bodo (10-20) hit 不败 while
#      the net proposition was suppressed.
#   8. Returns an explicit no_signal decision instead of forcing a pick.
#      Forcing a direction on a no-signal match is how accuracy gets inflated.
#   9. 规则6 + 压主 >=90% is a consensus-overheat trap: keep only the 不败
#      observation, never issue the net proposition.  0/3: Inter 3:4 (93%),
#      Fenerbahce 2:2 (96%), Porto 0:1 (100%).
#  10. A >=75% closing base probability overrides a contradictory price
#      consensus.  Man City 5:1 AEK: 86% base, 72% away push; the old engine
#      said 客队不败.  The push was an opening-price correction, not a signal.
#  11. 压客 >=40 + 立博让方水位未降/盘口未升 -> 不出 (hard veto, not a
#      half-tier downgrade).  Osasuna 2:0 (10-18), Stuttgart 1:1 (10-20).
#  12. 规则6 is mechanically equal-weighted (10-14); heat resonance is only a
#      warning, never a tier boost.
# ---------------------------------------------------------------------------

# Documented base rates, for the report only — never used to pick a side.
BASE_RATE = {
    "规则6->净胜命题": "全量 19/25=76% / 实战 14/18=78%; 现行无条件口径 6/8=75%; 压主>=90% 组 0/3 -> 降观察",
    "规则6+压主>=90%": "0/3 (国米 3:4, 费内 2:2, 波尔图 0:1) -> 只留不败观察",
    "基础概率>=75%覆盖反向共识": "曼城 5:1 AEK (86% base vs 72% away push) -> 主队胜",
    "压客>=40+亚盘不配合": "Osasuna 2:0, Stuttgart 1:1 -> 2/2 不出正确 (让球盘)",
    "宽平水->下盘不败": "实战 10/11=91% -> 全量 4/8=50% (wd>=0.13 分层 3/3)",
    "浅盘避雷": "累计 18/25=72%~82%, 全场价值最高单条",
    "深盘高水->不碰": "19/35=54%, 边际价值有限",
    "压主共识": "3/3=100% (样本少)",
    "压客共识": "近 15 场错 6 / 兑现 8 / 覆盖 1 -> 强制不败格式",
}

TIER_STRONG, TIER_NORMAL, TIER_HALF, TIER_OBSERVE = "⭐⭐", "⭐", "半档", "观察"


SIDE_CN = {"home": "主队", "away": "客队"}


def decide(r, *, fav_def_injuries=0):
    """Turn one analyze() result into ONE deterministic decision + audit trail.

    fav_def_injuries: number of injuries/suspensions to the favourite's
    defensive line or goalkeeper (SKILL hard-downgrade condition). The engine
    has no lineup data; the caller must pass it in, or the downgrade is skipped.
    """
    lb = r.get("lb") or {}
    p = r.get("push") or {}
    n = r.get("push_total") or 0
    dd, wd, lw, side = r.get("dd"), r.get("wd"), r.get("lb_water"), r.get("lb_side")
    heat = r.get("heat")
    dpp = heat.get("dpp") if heat else None
    out = {"label": r.get("label"), "mid": r.get("mid"),
           "decision": None, "tier": None, "rule": None,
           "blocked": [], "warnings": [], "inputs": {}}

    def block(rule, why):
        out["blocked"].append({"rule": rule, "reason": why})

    if n:
        out["inputs"] = {"dd": dd, "wd": wd, "lb_water": lw, "lb_side": side,
                         "push": {k: f"{p.get(k, 0)}/{n}={round(p.get(k,0)/n*100)}%"
                                  for k in ("home", "draw", "away")},
                         "heat_dpp": dpp}

    # --- priority 1: 浅盘避雷 is a VETO -------------------------------------
    if dd is not None and lw is not None and dd <= -0.25 and lw > 0.75:
        out["decision"] = "不出"
        out["rule"] = "浅盘避雷"
        out["tier"] = TIER_STRONG
        # Record what the veto suppressed, so avoidance stays measurable.
        # NOTE: dd <= -0.25 and 宽平水 (dd ~ 0) are mutually exclusive, so these
        # two can never co-fire in reality — they are listed anyway so the audit
        # trail is explicit and a future dd change cannot silently drop them.
        if 0.13 <= (wd or 0) <= 0.2:
            block("宽平水->下盘不败", "被浅盘避雷优先否决")
        if p.get("home", 0) >= 25:
            block("压主共识", "被浅盘避雷优先否决")
        if p.get("away", 0) >= 25:
            block("压客共识", "被浅盘避雷优先否决")
        if dpp and max(dpp) >= 5:
            out["warnings"].append(f"热度升温+{max(dpp)}pp 但避雷优先, 不翻案")
        return out

    # --- priority 2: 规则6 净胜命题 ----------------------------------------
    if (dd is not None and dd <= -0.25 and lw is not None and lw <= 0.75
            and (wd or 0) >= 0.205 and side in ("home", "away")):
        side_heat = dpp[0 if side == "home" else 2] if dpp else None
        # 10-14: rule 6 is mechanically equal-weighted. Heat resonance is
        # recorded as an observation, never as a tier boost.
        tier = TIER_NORMAL
        if side_heat is not None and side_heat >= 5:
            out["warnings"].append(
                f"热度共振 +{side_heat}pp (10-14 机械等权, 不加码)")
        # wd < 0.21 downgrades, it does NOT reject (SKILL: 降级为观察/轻仓)
        if (wd or 0) < 0.21:
            tier = TIER_HALF
            out["warnings"].append(f"wd {wd} < 0.21 (历史 0/2 全败) -> 降半档")
        if fav_def_injuries >= 2:
            block("规则6->净胜命题",
                  f"让方防线/门将伤缺 {fav_def_injuries} 人 -> 硬降级, 仅保留不败")
            out["decision"] = f"{SIDE_CN[side]}不败"
            out["rule"] = "规则6硬降级->不败观察"
            out["tier"] = TIER_OBSERVE
            return out
        # 10-20: rule 6 + 压主 >=90% is a consensus-overheat trap.
        # Fenerbahce 2:2 (96%), Porto 0:1 (100%), Inter 3:4 (93%) -> 0/3.
        # Keep only the 不败 observation; never issue the net proposition.
        if side == "home" and n and p.get("home", 0) / n >= 0.90:
            block("规则6->净胜命题",
                  f"压主 {p.get('home')}/{n} >=90% 极端共识 -> 降为观察")
            out["decision"] = "主队不败"
            out["rule"] = "规则6+压主>=90%->不败观察"
            out["tier"] = TIER_OBSERVE
            return out
        if p.get("draw", 0) >= 15:
            tier = TIER_HALF
            out["warnings"].append(f"压平 {p.get('draw')}/{n} >=15 -> 平局属性强, 降档")
        out["decision"] = f"{SIDE_CN[side]}净胜命题"
        out["rule"] = "规则6->净胜命题"
        out["tier"] = tier
        return out

    # --- priority 3: 宽平水 -> 下盘不败 (tightened wd >= 0.13) ---------------
    # NOTE: never write `dd or <default>` here — dd == 0.0 (真平手盘) is falsy
    # and would be silently replaced by the default.
    if dd is not None and abs(dd) < 1e-9 and 0.13 <= (wd or 0) <= 0.2:
        if lw is not None and lw >= 1.05:
            out["decision"] = "不出"
            out["rule"] = "宽平水降级(立博让方水>=1.05)"
            out["tier"] = TIER_OBSERVE
            out["warnings"].append("宽平水信号降级为观察项, 不单独出单")
            return out
        out["decision"] = "下盘不败"
        out["rule"] = "宽平水->下盘不败"
        out["tier"] = TIER_STRONG
        return out

    # --- priority 4: 深盘低水 -> 正路 (narrow, sample-poor) -----------------
    if (dd or 0) >= 0.5 and lw is not None and lw <= 0.95 \
            and (r.get("wd_signed") or 0) <= -0.08 and side in ("home", "away"):
        out["decision"] = f"{side}胜"
        out["rule"] = "深盘低水->正路"
        out["tier"] = TIER_OBSERVE
        out["warnings"].append("深盘低水样本 1/2, 仅观察")
        return out

    # --- priority 5: 共识 fallback -----------------------------------------
    # 10-20: a >=75% closing base probability is the anchor. If the price
    # consensus points to the opposite side, do not follow the consensus
    # (Man City 5:1 AEK: 86% base, 72% away push, engine wrongly said 客队不败).
    base = heat.get("cur") if heat else None
    if base:
        bi = max(range(3), key=lambda i: base[i])
        base_side = ("home", "draw", "away")[bi]
        cons_side = ("home" if p.get("home", 0) >= 25
                     else ("away" if p.get("away", 0) >= 25 else None))
        if base[bi] >= 75.0 and cons_side and cons_side != base_side:
            out["decision"] = ("主队胜" if base_side == "home"
                               else ("客队胜" if base_side == "away" else "平局"))
            out["rule"] = "基础概率>=75%覆盖反向共识"
            out["tier"] = TIER_NORMAL
            out["warnings"].append(
                f"基础概率 {base[bi]}% 指向 {base_side}, 压价共识指向 {cons_side} -> 不跟共识")
            return out

    if p.get("home", 0) >= 25:
        over = p["home"] >= 40
        t = TIER_HALF if over else TIER_NORMAL
        if over:
            out["warnings"].append(f"压主 {p['home']}/{n} >=40 共识过热 -> 降半档, 不因此加仓")
        out["decision"] = "主队不败"
        out["rule"] = "压主共识"
        out["tier"] = t
        return out
    if p.get("away", 0) >= 25:
        # 10-06: 压客 >=40 + 亚盘不配合 (立博让方水位未降 / 盘口未升)
        # is a HARD no-bet, not merely a half-tier downgrade.
        # Osasuna 2:0 (10-18), Stuttgart 1:1 (10-20) are the evidence.
        if p["away"] >= 40:
            lbw0 = lb.get("iw") if side == "home" else lb.get("il")
            lbw1 = lb.get("cw") if side == "home" else lb.get("cl")
            lbh0 = abs(lb["ih"]) if lb.get("ih") is not None else None
            lbh1 = abs(lb["ch"]) if lb.get("ch") is not None else None
            if None not in (lbw0, lbw1, lbh0, lbh1):
                if lbw1 >= lbw0 - 0.005 and lbh1 <= lbh0 + 0.001:
                    block("压客共识",
                          "压客>=40 但立博让方水位未降/盘口未升 -> 不出")
                    out["decision"] = "不出"
                    out["rule"] = "压客>=40+亚盘不配合"
                    out["tier"] = TIER_OBSERVE
                    return out
        over = p["away"] >= 40
        t = TIER_HALF if over else TIER_NORMAL
        if over:
            out["warnings"].append(f"压客 {p['away']}/{n} >=40 共识过热 -> 降半档")
        out["decision"] = "客队不败"          # 强制不败, 从不写客胜
        out["rule"] = "压客共识"
        out["tier"] = t
        return out

    # --- 深盘高水 / 压平: 不碰, 但绝不给方向 --------------------------------
    if abs(lb.get("ch") or 0) >= 1.0 and lw is not None and lw >= 1.05:
        out["decision"] = "不出"
        out["rule"] = "深盘高水->让球盘不碰"
        out["tier"] = TIER_OBSERVE
        out["warnings"].append("深盘高水既非正路也非下盘, 不给方向")
        return out
    if p.get("draw", 0) >= 30:
        out["warnings"].append(f"压平 {p['draw']}/{n} >=30 仅为环境项(6/8=75%, 已否决)")

    out["decision"] = "无信号"
    out["rule"] = "no_signal"
    out["tier"] = TIER_OBSERVE
    return out
