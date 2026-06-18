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


def wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple:
    """方向命中率的 Wilson 95% 区间。小 N 下判断'是否真高于 50%'的诚实工具。"""
    if n == 0:
        return (None, None)
    p = hits / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (round((c - m) / d, 3), round((c + m) / d, 3))


def _directional(pairs: list[tuple]) -> dict:
    """pairs: [(signal, drate)]，剔除 None/中性。方向命中 = sign 一致 + Wilson CI。"""
    d = [(s, y) for s, y in pairs if y is not None and s != 0 and y != 0]
    if not d:
        return {"n": 0, "hits": 0, "hit_rate": None, "ci95": (None, None)}
    hits = sum(1 for s, y in d if _sgn(s) == _sgn(y))
    lo, hi = wilson_ci(hits, len(d))
    return {"n": len(d), "hits": hits, "hit_rate": round(hits / len(d), 3),
            "ci95": (lo, hi), "beats_coin": lo is not None and lo > 0.5}


def _ols_origin(xs: list[float], ys: list[float]) -> float:
    """过原点 OLS（surprise=0 → 重定价=0，中性点必须是 0）。返回 β。"""
    sxx = sum(x * x for x in xs)
    return sum(x * y for x, y in zip(xs, ys)) / sxx if sxx > 0 else 0.0


def walk_forward(rows: list[dict], event_type: str, window: int,
                 min_train: int = 12) -> list[tuple]:
    """扩张窗样本外：用过去事件拟合 β，预测下一个。返回 [(pred_bp, actual_bp)]。

    过原点拟合 → 用原始 surprise（同类型单位一致），OOS 预测以 bp 计、跨类型可汇。
    """
    seq = sorted((r["date"], r["signal"], r["drate"][window]) for r in rows
                 if r["event_type"] == event_type and r["drate"].get(window) is not None)
    preds = []
    for i in range(min_train, len(seq)):
        xs = [s for _, s, _ in seq[:i]]
        ys = [y for _, _, y in seq[:i]]
        b = _ols_origin(xs, ys)
        _, xi, yi = seq[i]
        preds.append((round(b * xi, 3), yi))
    return preds


def _oos_metrics(preds: list[tuple]) -> dict:
    """样本外 (pred,actual) → 方向命中(+CI) + R²_vs_零基线。"""
    p = [(pr, ac) for pr, ac in preds if ac != 0 and pr != 0]
    if not p:
        return {"n": 0, "dir_hit": None, "r2_vs_zero": None}
    hits = sum(1 for pr, ac in p if _sgn(pr) == _sgn(ac))
    sse = sum((ac - pr) ** 2 for pr, ac in p)
    sst = sum(ac * ac for _, ac in p)  # 基线=随机游走(预测0)
    lo, hi = wilson_ci(hits, len(p))
    return {"n": len(p), "dir_hit": round(hits / len(p), 3), "ci95": (lo, hi),
            "r2_vs_zero": round(1 - sse / sst, 3) if sst > 0 else None,
            "beats_coin": lo is not None and lo > 0.5}


# 主窗口按经济逻辑预设（非数据挖掘）：政策/劳动力即时反应，通胀数据隔夜消化。
PRIMARY_WINDOW = {"FOMC": 15, "NFP": 15, "CPI": 1440, "CoreCPI": 1440, "CorePCE": 1440}


def deepen(rows: list[dict], min_train: int = 12) -> dict:
    """深化：每信号在'预设主窗口'上的方向命中(+Wilson CI) + walk-forward 样本外。

    主窗口理论先验固定，避免挑窗 p-hacking。样本外把全类型 OOS 预测汇成
    一个 pooled R²/命中，回答'拿过去拟合的 β，对未来到底有没有用'。
    """
    types = [t for t in PRIMARY_WINDOW if any(r["event_type"] == t for r in rows)]
    per = {}
    pooled_oos = []
    for et in types:
        w = PRIMARY_WINDOW[et]
        insample = _directional([(r["signal"], r["drate"][w]) for r in rows
                                 if r["event_type"] == et and r["drate"].get(w) is not None])
        wf = walk_forward(rows, et, w, min_train)
        pooled_oos += wf
        per[et] = {"primary_window": w, "in_sample_directional": insample,
                   "oos": _oos_metrics(wf)}
    return {
        "primary_windows": PRIMARY_WINDOW,
        "by_signal": per,
        "pooled_oos": _oos_metrics(pooled_oos),
        "note": ("主窗口为理论先验固定（FOMC/非农即时、通胀隔夜），非挑窗。"
                 "方向命中带 Wilson 95% CI——CI 下界>0.5 才算真高于硬币。"
                 "OOS=扩张窗过原点拟合的样本外预测，R²基线=随机游走(预测0)。"),
    }


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
