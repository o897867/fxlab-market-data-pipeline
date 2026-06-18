"""模型 C：用 macro surprise + 鹰鸽分 解释/预测 SOFR 隐含利率的重定价。

定位（诚实）：**不预测联储决议**——那是陷阱，市场用期货早已定价、你赢不了。
本模型回答的是可做、可验、有用的问题：
  给定一次数据/沟通的"意外"，市场的利率预期会被重定价多少 bp、往哪个方向。

  目标 Y = SOFR 隐含政策利率在事件后窗口内的变动（bp，鹰派为正 = 期货价跌）
  信号 X = 该事件的标准化意外（宏观：surprise_z；FOMC：overall_score）

两个产出：
  1. 方向命中率 sign(信号)==sign(ΔSOFR)：无参数、天然样本外、不会过拟合 → 头条指标
  2. 敏感度 β（每 1 个标准差信号重定价多少 bp）+ 样本内 R²：描述性，标注 in-sample

诚实基线 = 随机游走（Δ=0，无信息）。方向命中以 50% 为硬币线。
"""

from __future__ import annotations

from macropulse.attribution import events
from macropulse.attribution.prices import InstrumentPrices
from macropulse.attribution.macro_events import load_events as load_macro

SOFR_TABLE = "sofr_candles_1m"

_sgn = lambda x: (x > 0) - (x < 0)


def drate_bp(sofr: InstrumentPrices, t0_ms: int, w: int) -> float | None:
    """SOFR 隐含利率在 [t0, t0+w] 的变动（bp）。鹰派重定价为正。"""
    r = sofr.window_return(t0_ms, w)
    if r is None:
        return None
    return round((r["p0"] - r["p1"]) * 100, 3)  # Δrate = −Δprice ×100


def build_dataset(conn, fomc_events: list[dict], windows: list[int]) -> list[dict]:
    """汇 FOMC（S3 分数）+ 宏观（SQLite）事件 → 每行带信号与各窗口 ΔSOFR(bp)。

    fomc_events: [{date, overall_score}]。宏观从 conn 的 macro_releases 读。
    """
    sofr = InstrumentPrices(conn=conn, table=SOFR_TABLE)
    rows = []
    for e in fomc_events:
        t0 = events.release_ts_ms(e["date"])
        rows.append({
            "date": e["date"], "event_type": "FOMC", "source": "score",
            "signal": float(e["overall_score"]),
            "drate": {w: drate_bp(sofr, t0, w) for w in windows},
        })
    for e in load_macro(conn):
        t0 = e["release_ts_ms"]
        rows.append({
            "date": e["meeting_date"], "event_type": e["event_type"],
            "source": e["surprise_source"], "signal": float(e["overall_score"]),
            "drate": {w: drate_bp(sofr, t0, w) for w in windows},
        })
    return rows


def _zscore_by_source(rows: list[dict]) -> dict:
    """按 source 把 signal 标准化到单位方差（FOMC 分数与 surprise_z 不同尺度）。
    返回 id(row)->signal_z。"""
    by_src: dict = {}
    for r in rows:
        by_src.setdefault(r["source"], []).append(r["signal"])
    stats = {}
    for src, vals in by_src.items():
        m = sum(vals) / len(vals)
        sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5
        stats[src] = (m, sd or 1.0)
    return {id(r): (r["signal"] - stats[r["source"]][0]) / stats[r["source"]][1] for r in rows}


def _ols(xs: list[float], ys: list[float]) -> dict | None:
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return None
    beta = sxy / sxx
    alpha = my - beta * mx
    sse = sum((y - (alpha + beta * x)) ** 2 for x, y in zip(xs, ys))
    sst = sum((y - my) ** 2 for y in ys)
    return {"beta_bp": round(beta, 2), "r2": round(1 - sse / sst, 3) if sst > 0 else None, "n": n}


def _directional(pairs: list[tuple]) -> dict:
    """pairs: [(signal, drate)]，剔除 None/中性。方向命中 = sign 一致。"""
    d = [(s, y) for s, y in pairs if y is not None and s != 0 and y != 0]
    if not d:
        return {"n": 0, "hits": 0, "hit_rate": None}
    hits = sum(1 for s, y in d if _sgn(s) == _sgn(y))
    return {"n": len(d), "hits": hits, "hit_rate": round(hits / len(d), 3)}


def summarize(rows: list[dict], windows: list[int]) -> dict:
    """每窗口：方向命中（pooled + 分事件类型）+ 样本内 OLS 敏感度。"""
    zmap = _zscore_by_source(rows)
    types = sorted({r["event_type"] for r in rows})
    out = {"n_events": len(rows), "windows_min": windows, "by_window": {}}
    for w in windows:
        valid = [r for r in rows if r["drate"][w] is not None]
        pooled_dir = _directional([(r["signal"], r["drate"][w]) for r in valid])
        ols = _ols([zmap[id(r)] for r in valid], [r["drate"][w] for r in valid])
        bytype = {}
        for et in types:
            sub = [r for r in valid if r["event_type"] == et]
            bytype[et] = {
                "directional": _directional([(r["signal"], r["drate"][w]) for r in sub]),
                "ols": _ols([zmap[id(r)] for r in sub], [r["drate"][w] for r in sub]),
            }
        out["by_window"][str(w)] = {
            "n": len(valid),
            "directional_pooled": pooled_dir,
            "ols_pooled": ols,
            "by_event_type": bytype,
        }
    out["note"] = ("方向命中无参数、天然样本外；β/R² 为样本内描述（每 1 SD 信号重定价 bp）。"
                   "基线=随机游走(Δ=0)。SOFR 信号仅 2022→今（2021 ZIRP 无反应）。"
                   "不预测联储决议——市场已定价；本模型量化'意外→利率预期重定价'。")
    return out
