"""服务层：读 dbt-duckdb 的 mart_*，出三面板「人话标题 + 原始数字」。

翻译铁律（doc §5/§7）：默认句子零术语；颜色不背涨跌含义；每个数字落回
「对持有正股的你意味着什么」。诚实提醒：delta 是风险中性概率非预言、OI 截至昨收。
"""

from __future__ import annotations

import os
from datetime import date

import duckdb

from option import config


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(os.path.abspath(config.DUCKDB_PATH), read_only=True)


def _sym_short(symbol: str) -> str:
    return symbol.split(":")[-1]


def _is_monthly(e: date) -> bool:
    """标准月度到期 = 当月第三个周五（day 15–21 且周五）。"""
    return 15 <= e.day <= 21 and e.weekday() == 4


def _pick_expiry(con, table: str, symbol: str, expiry: str | None) -> str | None:
    """选到期日：显式优先；否则在剩余 ≥ MIN_DTE 的到期里优先最近的『月度』
    （月度 OI 厚、墙才真），无月度则取最近一个。"""
    if expiry:
        return expiry if isinstance(expiry, date) else date.fromisoformat(expiry)
    rows = con.execute(
        f"SELECT distinct expiration FROM main_marts.{table} WHERE underlying_code=? "
        f"ORDER BY expiration", [symbol]).fetchall()
    exps = [r[0] for r in rows]
    today = date.today()
    future = [e for e in exps if (e - today).days >= config.MIN_DTE]
    monthly = [e for e in future if _is_monthly(e)]
    return (monthly or future or exps or [None])[0]


def _exp_cn(e) -> str:
    return f"{e.month}/{e.day}" if e else "下次到期"


# ----------------------------------------------------------------- 面板①预期范围

def expected_move(symbol: str, expiry: str | None = None) -> dict:
    con = _con()
    try:
        exp = _pick_expiry(con, "mart_expected_move", symbol, expiry)
        row = con.execute(
            "SELECT spot, atm_iv, expected_move_usd, band_low, band_high, pct, straddle_em_check "
            "FROM main_marts.mart_expected_move WHERE underlying_code=? AND expiration=?",
            [symbol, exp]).fetchone()
    finally:
        con.close()
    if not row:
        return {"symbol": symbol, "available": False}
    spot, iv, em, lo, hi, pct, straddle = (float(x) for x in row)
    name = _sym_short(symbol)
    headline = f"到 {_exp_cn(exp)},{name} 大概率落在 ${lo:.0f}–${hi:.0f}(±{pct*100:.0f}%)"
    return {
        "symbol": symbol, "available": True, "expiry": str(exp), "headline": headline,
        "band_low": round(lo, 2), "band_high": round(hi, 2), "pct": round(pct, 4),
        "spot": round(spot, 2),
        "sub": f"这是市场押注的波动范围,你的目标位现不现实拿它当尺子",
        "raw": {"atm_iv": round(iv, 4), "expected_move_usd": round(em, 2),
                "straddle_check": round(straddle, 2)},
    }


# ----------------------------------------------------------------- 面板②问问市场

def _mood(p: float) -> str:
    if p >= 0.6:
        return "挺有可能"
    if p >= 0.35:
        return "机会一般"
    return "有点难"


def probability(symbol: str, price: float, expiry: str | None = None) -> dict:
    con = _con()
    try:
        exp = _pick_expiry(con, "mart_probability_curve", symbol, expiry)
        rows = con.execute(
            "SELECT strike, prob_above, spot FROM main_marts.mart_probability_curve "
            "WHERE underlying_code=? AND expiration=? ORDER BY strike", [symbol, exp]).fetchall()
    finally:
        con.close()
    if not rows:
        return {"symbol": symbol, "available": False}
    spot = float(rows[0][2])
    # 在相邻行权价间线性插值 prob_above
    p_above = float(_interp(price, [(float(r[0]), float(r[1])) for r in rows]))
    above = price >= spot
    shown_p = p_above if above else (1 - p_above)
    direction = "上方" if above else "下方"
    name = _sym_short(symbol)
    headline = (f"市场认为 {_exp_cn(exp)} {name} 收在 ${price:.0f} {direction}的概率约 "
                f"{shown_p*100:.0f}%（{_mood(shown_p)}）")
    return {
        "symbol": symbol, "available": True, "expiry": str(exp), "price": price,
        "headline": headline, "prob_above": round(p_above, 4),
        "prob_below": round(1 - p_above, 4), "direction": direction, "spot": round(spot, 2),
        "sub": "这是市场定价的概率,不是预言（用风险中性 delta 估算）",
    }


def _interp(x: float, pts: list[tuple]) -> float:
    """单调点列上对 x 线性插值（pts 按 strike 升序，value=prob_above 随 strike 降）。"""
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (k0, v0), (k1, v1) in zip(pts, pts[1:]):
        if k0 <= x <= k1:
            w = (x - k0) / (k1 - k0) if k1 != k0 else 0
            return v0 + w * (v1 - v0)
    return pts[-1][1]


# ----------------------------------------------------------------- 面板③押注分布

def distribution(symbol: str, expiry: str | None = None, top: int = 10) -> dict:
    con = _con()
    try:
        exp = _pick_expiry(con, "mart_strike_distribution", symbol, expiry)
        rows = con.execute(
            "SELECT strike, call_oi, put_oi, max_pain_strike, pc_ratio, spot "
            "FROM main_marts.mart_strike_distribution WHERE underlying_code=? AND expiration=? "
            "ORDER BY strike", [symbol, exp]).fetchall()
        emrow = con.execute(
            "SELECT pct FROM main_marts.mart_expected_move WHERE underlying_code=? AND expiration=?",
            [symbol, exp]).fetchone()
    finally:
        con.close()
    if not rows:
        return {"symbol": symbol, "available": False}
    spot = float(rows[0][5])
    max_pain = float(rows[0][3]) if rows[0][3] is not None else None
    pc_ratio = float(rows[0][4]) if rows[0][4] is not None else None
    pct = float(emrow[0]) if emrow and emrow[0] else 0.10

    # 价格网格：绕现价、按预期波动范围(±1.4σ)缩放，整数步长 → 均匀阶梯，无跳格。
    half = max(pct * 1.4, 0.05) * spot
    lo, hi = spot - half, spot + half
    step = _nice_step(2 * half / top)
    center = round(spot / step) * step
    grid = [center + i * step for i in range(-top, top + 1) if lo - step / 2 <= center + i * step <= hi + step / 2 and center + i * step > 0]

    buckets = []
    for g in grid:
        c = sum(int(r[1] or 0) for r in rows if abs(float(r[0]) - g) <= step / 2)
        p = sum(int(r[2] or 0) for r in rows if abs(float(r[0]) - g) <= step / 2)
        if c + p > 0:
            buckets.append({"strike": float(g), "call_oi": c, "put_oi": p,
                            "total_oi": c + p, "side": "call" if c >= p else "put"})
    if not buckets:
        return {"symbol": symbol, "available": False}
    # 墙 = 网格内 OI 最大的前 4 个
    wall_keys = {b["strike"] for b in sorted(buckets, key=lambda b: b["total_oi"], reverse=True)[:4]}
    for b in buckets:
        b["is_wall"] = b["strike"] in wall_keys
    ladder = sorted(buckets, key=lambda b: b["strike"], reverse=True)

    name = _sym_short(symbol)
    call_walls = sorted([b for b in buckets if b["side"] == "call" and b["is_wall"]],
                        key=lambda b: b["call_oi"], reverse=True)[:1]
    put_walls = sorted([b for b in buckets if b["side"] == "put" and b["is_wall"]],
                       key=lambda b: b["put_oi"], reverse=True)[:2]
    ca = f"${call_walls[0]['strike']:.0f} 挤满赌涨" if call_walls else ""
    pa = "、".join(f"${b['strike']:.0f}" for b in put_walls)
    headline = f"{name} 押得最多的:{ca}" + (f",{pa} 堆着买保护" if pa else "")
    return {
        "symbol": symbol, "available": True, "expiry": str(exp), "headline": headline,
        "spot": spot, "step": step,
        "strikes": ladder, "max_pain": max_pain, "pc_ratio": round(pc_ratio, 3) if pc_ratio else None,
        "sub": "未平仓量截至昨收;磁吸位（max pain）是临近到期股价容易被拉向的价位",
    }


import math


# ----------------------------------------------------------------- 面板⑤期限结构

_TS_HEAD = {
    "backwardation": "市场觉得未来几周的波动会比几个月后明显更大 → 通常意味着近期有大事(比如财报)。",
    "contango": "市场觉得越往后越不确定、近期没什么特别的事 —— 这是常态。",
    "flat": "近期和远期的波动预期差不多,市场没在为某个时点特别定价。",
}


def term_structure(symbol: str) -> dict:
    """近月 vs 远月 ATM IV 曲线 + 形态(backwardation 近期有事 / contango 常态)。"""
    con = _con()
    try:
        rows = con.execute(
            "SELECT dte, atm_iv, expiration, shape_flag FROM main_marts.mart_term_structure "
            "WHERE underlying_code=? ORDER BY dte", [symbol]).fetchall()
    finally:
        con.close()
    if not rows:
        return {"symbol": symbol, "available": False}
    shape = rows[0][3]
    curve = [{"dte": int(r[0]), "iv": round(float(r[1]), 4),
              "iv_pct": round(float(r[1]) * 100, 1), "expiry": str(r[2])} for r in rows]
    name = _sym_short(symbol)
    return {"symbol": symbol, "available": True, "shape": shape,
            "headline": f"{name}：" + _TS_HEAD.get(shape, ""),
            "curve": curve,
            "sub": "横轴=距到期天数,纵轴=市场对该期波动的定价(隐含波动率)。"}


# ----------------------------------------------------------------- 面板④影响

def impact(symbol: str, expiry: str | None = None) -> dict:
    """期权怎么影响正股。三子模块按可信度排序：事件预期(最可信) > 磁吸位 > GEX(估算)。
    可信度标签是产品诚信底线（doc §3.2）——把"定价事实"和"估算猜测"明明白白分开。"""
    con = _con()
    try:
        exp = _pick_expiry(con, "mart_impact", symbol, expiry)
        row = con.execute(
            "SELECT spot, dte, front_iv, baseline_iv, front_premium_pct, event_flag, "
            "max_pain_strike, magnet_strikes, net_gex, gex_regime "
            "FROM main_marts.mart_impact WHERE underlying_code=? AND expiration=?",
            [symbol, exp]).fetchone()
    finally:
        con.close()
    if not row:
        return {"symbol": symbol, "available": False}
    spot, dte, fiv, biv, prem, ev, mp, magnets, net_gex, regime = row
    spot = float(spot)
    name = _sym_short(symbol)
    em_pct = float(fiv) * math.sqrt(max(int(dte), 1) / 365) if fiv else 0

    # 财报日（来自 earnings.json 缓存）；所选到期是否覆盖它
    from option import earnings as _earn
    ed = (_earn.load().get(symbol) or {}).get("date")
    covers = bool(ed and ed <= str(exp))
    ed_cn = (ed[5:].replace("-", "/")) if ed else None

    items = []
    # B 事件预期 —— 最可信（定价事实）
    if covers:
        head = (f"📅 财报就在 {ed_cn},这个到期日覆盖它 —— 近月期权定价的 ±{em_pct*100:.0f}% "
                f"波动很可能就是为财报。")
    elif ev:
        head = (f"近月期权定价了 ±{em_pct*100:.0f}% 的波动,明显高于之后到期 → 市场把近期当大事。"
                + (f"(下次财报 {ed_cn},在所选到期之后)" if ed else ""))
    else:
        head = (f"近月与之后到期的期权定价的波动差不多({prem:+.0f}%),没在为近期特定事件额外定价。"
                + (f"下次财报 {ed_cn}。" if ed else ""))
    items.append({"key": "event", "title": "事件预期",
                  "tier": "定价事实 · 最可信", "tier_level": "high",
                  "headline": head, "earnings_date": ed, "earnings_in_window": covers,
                  "detail": f"近月隐含波动 ±{em_pct*100:.0f}% · 较远月基准 {prem:+.1f}%",
                  "value": f"±{em_pct*100:.0f}%"})

    # A 磁吸位 —— 倾向
    mlist = [float(x) for x in (magnets or [])]
    mstr = "、".join(f"${x:.0f}" for x in mlist[:3])
    items.append({"key": "magnet", "title": "磁吸位",
                  "tier": "倾向 · 只在临近到期明显", "tier_level": "mid",
                  "headline": f"到 {_exp_cn(exp)},${float(mp):.0f} 堆了最多筹码,临近到期股价容易被吸过去。" if mp else "暂无明显磁吸位。",
                  "detail": f"押注最重的价位:{mstr}",
                  "value": f"${float(mp):.0f}" if mp else "—"})

    # C 波动状态 GEX —— 估算（最不可信，标签务必显眼）
    if regime == "suppress":
        ghead = "当前结构倾向于压制波动,股价可能小幅黏着、大涨大跌的概率被结构性压低。"
    else:
        ghead = "当前结构倾向于放大波动,一旦动起来、利好利空都可能被放大。"
    items.append({"key": "gex", "title": "波动状态 · GEX",
                  "tier": "估算 · 基于「做市商空 gamma」假设,谨慎看", "tier_level": "low",
                  "headline": ghead,
                  "detail": "GEX 的正负取决于做市商持仓假设,不是观测到的事实——它可能是错的。",
                  "value": "压制波动" if regime == "suppress" else "放大波动"})

    return {"symbol": symbol, "available": True, "expiry": str(exp), "spot": spot,
            "dte": int(dte), "items": items,
            "sub": "按可信度从高到低排：事件预期是市场定价的事实,GEX 只是基于假设的估算。"}


def _nice_step(raw: float) -> float:
    """把原始步长收敛到一个好看的整数档（1/2/2.5/5/10/25/50/100/...）。"""
    for s in [1, 2, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500]:
        if s >= raw * 0.85:
            return s
    return 5000


# ----------------------------------------------------------------- 面板⑥ IV Rank（时序）

# 冷启动门槛：快照少于这么多天，IV Rank 的 min/max 区间还没走出来，参考价值有限。
IV_RANK_MIN_DAYS = 30


def _valuation(iv_current: float | None, hv20: float | None):
    """贵贱判断——今天就能出，用 IV vs 已实现波动(HV20)当尺子，不必等 IV 历史。
    返回 (级别文案, 级别码 hot/mid/calm, 比值) 或 None（缺数据）。纯事实对比，不预测。"""
    if not iv_current or not hv20 or hv20 <= 0:
        return None
    ratio = iv_current / hv20
    if ratio >= 1.20:
        return "偏贵", "hot", ratio
    if ratio <= 0.85:
        return "偏便宜", "calm", ratio
    return "中性", "mid", ratio


def iv_rank(symbol: str) -> dict:
    """期权现在贵不贵。两把尺子：
    ① vs 已实现波动(HV) —— 今天就能出（冷启动期的主判断）
    ② vs 自己过去一年(IV Rank) —— 需攒够快照，未满 30 天标注"积累中"
    翻译别越界：只陈述"市场当前如何定价 vs 这票实际走过的波动"，不预测、不给建议。"""
    con = _con()
    try:
        row = con.execute(
            "SELECT iv_current, iv_low, iv_high, iv_rank, iv_percentile, data_days, as_of "
            "FROM main_marts.mart_iv_rank WHERE underlying_code=?", [symbol]).fetchone()
    finally:
        con.close()
    if not row:
        return {"symbol": symbol, "available": False}
    iv_now, lo, hi, rank, pct, days, as_of = row
    iv_now = float(iv_now)
    name = _sym_short(symbol)
    maturing = days is None or days < IV_RANK_MIN_DAYS

    # ① HV 参照（今天可判）
    from option import realized_vol as _rv
    hv = (_rv.load().get(symbol) or {})
    hv20 = hv.get("hv20")
    hv252 = hv.get("hv252")
    val = _valuation(iv_now, hv20)

    if val:
        level, level_code, ratio = val
        gap = abs(ratio - 1) * 100
        if level == "偏贵":
            vdesc = (f"期权现在定价的年化波动约 ±{iv_now*100:.0f}%,比这票最近实际走的波动 "
                     f"(±{hv20*100:.0f}%) 高出约 {gap:.0f}% —— 相对偏贵。")
        elif level == "偏便宜":
            vdesc = (f"期权现在定价的年化波动约 ±{iv_now*100:.0f}%,低于这票最近实际走的波动 "
                     f"(±{hv20*100:.0f}%) 约 {gap:.0f}% —— 相对偏便宜。")
        else:
            vdesc = (f"期权定价的波动(±{iv_now*100:.0f}%)和这票最近实际走的波动"
                     f"(±{hv20*100:.0f}%)差不多 —— 定价不算贵也不算便宜。")
    else:
        level, level_code, vdesc = "暂无参照", "mature", "还拿不到这票的历史价格,暂时给不出贵贱参照。"

    headline = f"{name}:{level}"

    # ② IV Rank（积累中）—— 作为次要参照
    if rank is None or maturing:
        rank_note = f"另一把尺子「IV Rank」还在积累({days} 天),满 30 天后能看'比它自己过去一年贵还是便宜'。"
    else:
        rank_note = f"IV Rank {rank:.0f}/100 —— 当前 IV 在这票过去一年区间里的位置。"

    return {
        "symbol": symbol, "available": True, "as_of": str(as_of),
        "level": level, "level_code": level_code, "headline": headline, "description": vdesc,
        "iv_current": round(iv_now, 4),
        "hv20": round(float(hv20), 4) if hv20 else None,
        "hv252": round(float(hv252), 4) if hv252 else None,
        "iv_vs_hv": round(val[2], 3) if val else None,
        "iv_rank": round(float(rank), 1) if rank is not None else None,
        "iv_percentile": round(float(pct), 1) if pct is not None else None,
        "iv_low": round(float(lo), 4), "iv_high": round(float(hi), 4),
        "data_days": int(days), "maturing": maturing, "rank_note": rank_note,
        "sub": "贵贱用 IV vs 已实现波动(HV)判——市场为未来定的价 vs 这票过去实际走的,是事实对比不是预言。",
    }


# ----------------------------------------------------------------- 面板⑦ P/C 情绪趋势（时序）

def pc_trend(symbol: str) -> dict:
    """看跌/看涨未平仓量比 + 5 日趋势 —— 防守情绪升温还是降温。"""
    con = _con()
    try:
        row = con.execute(
            "SELECT pc_today, pc_prev, days_back, trend, as_of "
            "FROM main_marts.mart_pc_trend WHERE underlying_code=?", [symbol]).fetchone()
    finally:
        con.close()
    if not row:
        return {"symbol": symbol, "available": False}
    today, prev, days_back, trend, as_of = row
    name = _sym_short(symbol)
    today = float(today)

    stance = "偏防守" if today >= 1.1 else ("偏进攻" if today <= 0.9 else "中性")
    move = {"rising": "防守情绪在升温", "falling": "防守情绪在降温", "flat": "情绪大体平稳"}[trend]
    span = f"过去 {int(days_back)} 天" if days_back else "目前"
    headline = f"{name}:{stance}(P/C {today:.2f}),{span}{move}。"
    return {
        "symbol": symbol, "available": True, "as_of": str(as_of),
        "stance": stance, "trend": trend, "headline": headline,
        "pc_today": round(today, 3),
        "pc_prev": round(float(prev), 3) if prev is not None else None,
        "days_back": int(days_back) if days_back is not None else 0,
        "sub": "看跌/看涨未平仓量之比;比值越高说明买保护的越多。未平仓量截至昨收。",
    }


# ----------------------------------------------------------------- watchlist 日报聚合

def _pick_expiry_py(exps: list) -> "date | None":
    """从到期日列表里按 panels 一致的规则挑一个：剩余 ≥ MIN_DTE 里优先最近的月度，否则最近。"""
    if not exps:
        return None
    today = date.today()
    future = [e for e in exps if (e - today).days >= config.MIN_DTE]
    monthly = [e for e in future if _is_monthly(e)]
    return (monthly or future or exps)[0]


def daily_report() -> dict:
    """全 watchlist 概览：每票一张精简卡（IV Rank + 预期波动 + 情绪）。
    排序：有财报的置顶，其余按 IV Rank 降序（最"紧张"的在前）。首页用。"""
    symbols = config.DEFAULT_SYMBOLS
    from option import earnings as _earn
    from option import realized_vol as _rv
    earn = _earn.load()
    hvmap = _rv.load()

    con = _con()
    try:
        ivr = {r[0]: r for r in con.execute(
            "SELECT underlying_code, iv_current, iv_rank, data_days FROM main_marts.mart_iv_rank"
        ).fetchall()}
        pct = {r[0]: r for r in con.execute(
            "SELECT underlying_code, pc_today, trend FROM main_marts.mart_pc_trend"
        ).fetchall()}
        # 预期波动：一次拉全部，按票在 Python 里挑到期日
        em_rows = con.execute(
            "SELECT underlying_code, expiration, band_low, band_high, pct, spot "
            "FROM main_marts.mart_expected_move").fetchall()
    finally:
        con.close()

    em_by_sym: dict[str, dict] = {}
    for code, exp, lo, hi, p, spot in em_rows:
        em_by_sym.setdefault(code, {})[exp] = (lo, hi, p, spot)

    cards = []
    today = date.today()
    for code in symbols:
        name = _sym_short(code)
        ir = ivr.get(code)
        iv_now = float(ir[1]) if ir and ir[1] is not None else None
        rank = round(float(ir[2]), 1) if ir and ir[2] is not None else None
        days = int(ir[3]) if ir else 0
        maturing = ir is None or ir[3] is None or ir[3] < IV_RANK_MIN_DAYS

        # 贵贱：今天就能出（IV vs HV20），不必等 IV Rank 成熟
        hv20 = (hvmap.get(code) or {}).get("hv20")
        val = _valuation(iv_now, hv20)          # (级别, 码, 比值) 或 None
        valuation = val[0] if val else None
        valuation_code = val[1] if val else None

        em = em_by_sym.get(code, {})
        exp = _pick_expiry_py(sorted(em.keys())) if em else None
        band = em.get(exp)
        pc = pct.get(code)

        ed = (earn.get(code) or {}).get("date") if earn.get(code) else None
        days_to_earn = (date.fromisoformat(ed) - today).days if ed else None
        # 只有临近(≤14 天)的财报才置顶；远期财报仍展示日期但不抢排序
        earnings_soon = days_to_earn is not None and 0 <= days_to_earn <= 14

        cards.append({
            "symbol": code, "name": name,
            "valuation": valuation, "valuation_code": valuation_code,
            "iv_vs_hv": round(val[2], 3) if val else None,
            "iv_rank": rank, "iv_maturing": maturing, "data_days": days,
            "spot": round(float(band[3]), 2) if band else None,
            "band_low": round(float(band[0]), 2) if band else None,
            "band_high": round(float(band[1]), 2) if band else None,
            "em_pct": round(float(band[2]) * 100, 1) if band else None,
            "pc_today": round(float(pc[1]), 2) if pc else None,
            "pc_trend": pc[2] if pc else None,
            "earnings_date": ed, "days_to_earnings": days_to_earn,
            "earnings_soon": earnings_soon,
        })

    # 排序：临近财报(≤14天)置顶；其余按"贵"程度(IV/HV 比值)降序，无参照垫底
    cards.sort(key=lambda c: (
        not c["earnings_soon"],
        c["days_to_earnings"] if c["earnings_soon"] else 0,
        -(c["iv_vs_hv"] if c["iv_vs_hv"] is not None else -1),
    ))
    return {"as_of": str(today), "count": len(cards), "cards": cards,
            "disclaimer": "以上为期权市场当前定价的客观统计,不预测走势、不构成投资建议。"}


def iv_rank_board() -> dict:
    """watchlist IV Rank 排行（降序）。给"哪些票现在最紧张"的一眼榜。"""
    con = _con()
    try:
        rows = con.execute(
            "SELECT underlying_code, iv_current, iv_rank, iv_percentile, data_days "
            "FROM main_marts.mart_iv_rank ORDER BY iv_rank DESC NULLS LAST").fetchall()
    finally:
        con.close()
    board = [{
        "symbol": r[0], "name": _sym_short(r[0]),
        "iv_current": round(float(r[1]), 4),
        "iv_rank": round(float(r[2]), 1) if r[2] is not None else None,
        "iv_percentile": round(float(r[3]), 1) if r[3] is not None else None,
        "data_days": int(r[4]), "maturing": r[4] is None or r[4] < IV_RANK_MIN_DAYS,
    } for r in rows]
    return {"count": len(board), "board": board}


def earnings_calendar() -> dict:
    """未来两周 watchlist 财报排期（按日期升序）。"""
    from option import earnings as _earn
    earn = _earn.load()
    today = date.today()
    items = []
    for code in config.DEFAULT_SYMBOLS:
        e = earn.get(code)
        ed = (e or {}).get("date")
        if not ed:
            continue
        d = date.fromisoformat(ed)
        dd = (d - today).days
        if 0 <= dd <= 14:
            items.append({"symbol": code, "name": _sym_short(code), "date": ed,
                          "days_away": dd, "eps_forecast": (e or {}).get("eps_forecast")})
    items.sort(key=lambda x: x["days_away"])
    return {"as_of": str(today), "count": len(items), "events": items}
