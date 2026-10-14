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
