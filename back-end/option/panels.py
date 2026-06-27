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
