"""归因回测编排（三标的：XAU / DXY / US2Y）。

把鹰鸽分数与声明后各标的的窗口收益对齐，逐事件标命中，按 (标的×窗口) 聚合，
并给一个跨标的 consensus（把三标的的方向观测汇到一起算命中率——一次真正的
鹰派意外应同时压金价、推美元、抬2Y收益率，三者一致才是强信号）。

命中只在非中性事件（score≠0）上计算。聚合纯函数可独立单测；S3/价格 I/O 在 run。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from macropulse import config
from macropulse.attribution import events
from macropulse.attribution.prices import InstrumentPrices

logger = logging.getLogger(__name__)

INSTRUMENTS = ("XAU", "DXY", "US2Y")


def build_event(score: dict, prices_by_inst: dict, windows: list[int] = None,
                t0_ms: int = None) -> dict:
    """单事件归因：分数 + 每标的各窗口收益 + 命中。

    t0_ms 显式给定时直接用（宏观事件 8:30 ET，时戳由源带来）；
    否则按 FOMC 约定从 meeting_date 推 14:00 ET。
    """
    windows = windows or config.ATTRIBUTION_WINDOWS_MIN
    date = score["meeting_date"]
    t0 = t0_ms if t0_ms is not None else events.release_ts_ms(date)
    release_iso = (__import__("datetime").datetime
                   .fromtimestamp(t0 / 1000, tz=__import__("datetime").timezone.utc).isoformat()
                   if t0_ms is not None else events.release_utc(date).isoformat())

    reactions = {}
    exp_signs = {}
    for inst, prices in prices_by_inst.items():
        exp = events.expected_return_sign(score["overall_score"], inst)
        exp_signs[inst] = exp
        rmap = {}
        for w in windows:
            r = prices.window_return(t0, w)
            if r is None:
                rmap[str(w)] = None
                continue
            ret_sign = (1 if r["return_pct"] > 0 else (-1 if r["return_pct"] < 0 else 0))
            hit = None if exp == 0 else (ret_sign == exp)
            rmap[str(w)] = {**r, "return_sign": ret_sign, "hit": hit}
        reactions[inst] = rmap

    rec = {
        "document_id": score["document_id"],
        "meeting_date": date,
        "release_utc": release_iso,
        "overall_score": score["overall_score"],
        "confidence_overall": score.get("confidence_overall"),
        "expected_signs": exp_signs,
        "reactions": reactions,
    }
    # 宏观事件透传额外字段（前端/审计用），FOMC 声明无这些键则不带。
    for k in ("event_type", "surprise", "surprise_source", "actual", "forecast"):
        if k in score:
            rec[k] = score[k]
    return rec


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return None if vx == 0 or vy == 0 else round(cov / (vx * vy), 4)


def _agg_window(pairs: list[tuple]) -> dict:
    """pairs: [(score, reaction_dict)]，已过滤掉 None。"""
    directional = [(s, r) for s, r in pairs if s != 0]
    hits = sum(1 for _, r in directional if r["hit"])
    n_dir = len(directional)
    scores = [s for s, _ in pairs]
    rets = [r["return_pct"] for _, r in pairs]
    return {
        "n_events": len(pairs),
        "n_directional": n_dir,
        "hits": hits,
        "hit_rate": round(hits / n_dir, 3) if n_dir else None,
        "pearson_score_vs_return": _pearson(scores, rets),
    }


def aggregate(event_records: list[dict], windows: list[int] = None,
              instruments: tuple = INSTRUMENTS) -> dict:
    """按 标的×窗口 聚合 + 每窗口 consensus（汇所有标的的命中观测）。"""
    windows = windows or config.ATTRIBUTION_WINDOWS_MIN
    out = {inst: {} for inst in instruments}
    out["consensus"] = {}
    for w in windows:
        key = str(w)
        consensus_pairs = []
        for inst in instruments:
            pairs = []
            for e in event_records:
                r = e["reactions"].get(inst, {}).get(key)
                if r is not None:
                    pairs.append((e["overall_score"], r))
            out[inst][key] = _agg_window(pairs)
            consensus_pairs += pairs
        out["consensus"][key] = _agg_window(consensus_pairs)
    return out


def run(store, windows: list[int] = None) -> dict:
    """读 S3 声明分数 + 本地三标的价格，产出完整三标的归因结果。"""
    windows = windows or config.ATTRIBUTION_WINDOWS_MIN

    stmt_keys = {}
    paginator = store.s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=store.bucket,
                                   Prefix=f"{config.SCORES_PREFIX}/statement/"):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                d = o["Key"].rsplit("_", 1)[-1].replace(".json", "")
                stmt_keys[d] = o["Key"]

    prices_by_inst = {inst: InstrumentPrices(table=events.INSTRUMENT_TABLE[inst])
                      for inst in INSTRUMENTS}
    try:
        # 各标的覆盖范围（取交集做跳过判断，用 XAU 为准——三者范围一致）
        lo, hi = prices_by_inst["XAU"].coverage()
        records, skipped = [], []
        for date in sorted(stmt_keys):
            score = store.load_json(stmt_keys[date])
            t0 = events.release_ts_ms(date)
            if lo is None or t0 < lo or t0 > hi:
                skipped.append(date)
                continue
            records.append(build_event(score, prices_by_inst, windows))
    finally:
        for p in prices_by_inst.values():
            p.close()

    logger.info("归因：%d 个声明有价格覆盖，%d 个超出范围跳过", len(records), len(skipped))
    return {
        "instruments": list(INSTRUMENTS),
        "directions": events.INSTRUMENT_DIR,
        "windows_min": windows,
        "n_scored_statements": len(stmt_keys),
        "n_attributed": len(records),
        "n_skipped_no_price": len(skipped),
        "skipped_dates": skipped,
        "events": records,
        "aggregate": aggregate(records, windows),
    }


def run_macro(conn: sqlite3.Connection = None, windows: list[int] = None,
              event_types: tuple = None) -> dict:
    """宏观数据事件（CPI/核心CPI/核心PCE/非农）归因——复用三标的机器。

    事件取自 macro_releases（surprise_z 当 overall_score），t0 由源带的精确发布时戳。
    按 event_type 分组聚合 + 一个 pooled 总聚合。
    """
    from macropulse.attribution import macro_events

    windows = windows or config.ATTRIBUTION_WINDOWS_MIN
    own = conn is None
    conn = conn or sqlite3.connect(config.PRICE_DB_PATH)
    prices_by_inst = {inst: InstrumentPrices(conn=conn, table=events.INSTRUMENT_TABLE[inst])
                      for inst in INSTRUMENTS}
    try:
        lo, hi = prices_by_inst["XAU"].coverage()
        evs = macro_events.load_events(conn)
        records, skipped = [], []
        for ev in evs:
            if event_types and ev["event_type"] not in event_types:
                continue
            t0 = ev["release_ts_ms"]
            if lo is None or t0 < lo or t0 > hi:
                skipped.append(ev["document_id"])
                continue
            records.append(build_event(ev, prices_by_inst, windows, t0_ms=t0))
    finally:
        if own:
            conn.close()

    by_type = {}
    for et in sorted({r["event_type"] for r in records}):
        subset = [r for r in records if r["event_type"] == et]
        by_type[et] = {"n_events": len(subset), "aggregate": aggregate(subset, windows)}

    logger.info("宏观归因：%d 个事件有价格覆盖，%d 个超范围跳过", len(records), len(skipped))
    return {
        "instruments": list(INSTRUMENTS),
        "directions": events.INSTRUMENT_DIR,
        "windows_min": windows,
        "n_events": len(records),
        "n_skipped_no_price": len(skipped),
        "surprise_note": ("历史段 surprise 用 FRED 'actual vs 近12期均值' 代理"
                          "(无 consensus)；前向段用 actual−forecast 真 consensus。"
                          "命中率按 surprise 符号判定，混合两段。"),
        "by_event_type": by_type,
        "aggregate_pooled": aggregate(records, windows),
        "events": records,
    }
