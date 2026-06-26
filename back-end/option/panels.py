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
            "SELECT strike, call_oi, put_oi, total_oi, is_wall, max_pain_strike, pc_ratio, spot "
            "FROM main_marts.mart_strike_distribution WHERE underlying_code=? AND expiration=? "
            "ORDER BY total_oi DESC", [symbol, exp]).fetchall()
    finally:
        con.close()
    if not rows:
        return {"symbol": symbol, "available": False}
    strikes = [{"strike": float(r[0]), "call_oi": int(r[1]), "put_oi": int(r[2]),
                "total_oi": int(r[3]), "is_wall": bool(r[4]),
                "side": "call" if r[1] >= r[2] else "put"} for r in rows]
    max_pain = float(rows[0][5]) if rows[0][5] is not None else None
    pc_ratio = float(rows[0][6]) if rows[0][6] is not None else None
    # 文案：最大的看涨墙 + 最大的两个看跌墙
    call_walls = [s for s in strikes if s["side"] == "call"][:1]
    put_walls = [s for s in strikes if s["side"] == "put"][:2]
    name = _sym_short(symbol)
    ca = f"${call_walls[0]['strike']:.0f} 挤满赌涨" if call_walls else ""
    pa = "、".join(f"${s['strike']:.0f}" for s in put_walls)
    headline = f"{name} 押得最多的:{ca}" + (f",{pa} 堆着买保护" if pa else "")
    # 梯子展示：取 OI 最大的 top 个价位，再按价格降序排（高价在上，符合设计阶梯）
    ladder = sorted(strikes[:top], key=lambda s: s["strike"], reverse=True)
    return {
        "symbol": symbol, "available": True, "expiry": str(exp), "headline": headline,
        "spot": float(rows[0][7]),
        "strikes": ladder, "max_pain": max_pain, "pc_ratio": round(pc_ratio, 3) if pc_ratio else None,
        "sub": "未平仓量截至昨收;磁吸位（max pain）是临近到期股价容易被拉向的价位",
    }
