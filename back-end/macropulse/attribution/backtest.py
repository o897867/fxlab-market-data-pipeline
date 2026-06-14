"""归因回测编排。

把鹰鸽分数（S3 scores）与声明后 XAU 窗口收益对齐，逐事件产出反应记录，
并按窗口聚合：方向命中率、Pearson 相关、鹰/鸽分组的平均收益。

命中只在非中性事件（score≠0）上计算（中性无方向预期）。聚合的纯统计函数
可独立单测；S3/价格 I/O 在 build_event / run。
"""

from __future__ import annotations

import logging
from typing import Optional

from macropulse import config
from macropulse.attribution import events
from macropulse.attribution.prices import XauPrices

logger = logging.getLogger(__name__)


def build_event(score: dict, prices: XauPrices,
                windows: list[int] = None) -> dict:
    """单个声明事件的归因记录：分数 + 各窗口 XAU 收益 + 命中标记。"""
    windows = windows or config.ATTRIBUTION_WINDOWS_MIN
    date = score["meeting_date"]
    t0 = events.release_ts_ms(date)
    exp_sign = events.expected_return_sign(score["overall_score"])

    reactions = {}
    for w in windows:
        r = prices.window_return(t0, w)
        if r is None:
            reactions[str(w)] = None
            continue
        ret_sign = (1 if r["return_pct"] > 0 else (-1 if r["return_pct"] < 0 else 0))
        hit = None if exp_sign == 0 else (ret_sign == exp_sign)
        reactions[str(w)] = {**r, "return_sign": ret_sign, "hit": hit}

    return {
        "document_id": score["document_id"],
        "meeting_date": date,
        "release_utc": events.release_utc(date).isoformat(),
        "overall_score": score["overall_score"],
        "confidence_overall": score.get("confidence_overall"),
        "expected_return_sign": exp_sign,
        "instrument": "XAU",
        "reactions": reactions,
    }


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    if vx == 0 or vy == 0:
        return None
    return round(cov / (vx * vy), 4)


def aggregate(event_records: list[dict], windows: list[int] = None) -> dict:
    """按窗口聚合命中率/相关性/分组均值。"""
    windows = windows or config.ATTRIBUTION_WINDOWS_MIN
    out = {}
    for w in windows:
        key = str(w)
        rows = [(e, e["reactions"].get(key)) for e in event_records]
        rows = [(e, r) for e, r in rows if r is not None]
        scores = [e["overall_score"] for e, _ in rows]
        rets = [r["return_pct"] for _, r in rows]

        directional = [(e, r) for e, r in rows if e["overall_score"] != 0]
        hits = sum(1 for _, r in directional if r["hit"])
        n_dir = len(directional)

        hawk_rets = [r["return_pct"] for e, r in rows if e["overall_score"] > 0]
        dove_rets = [r["return_pct"] for e, r in rows if e["overall_score"] < 0]

        out[key] = {
            "n_events": len(rows),
            "n_directional": n_dir,
            "hits": hits,
            "hit_rate": round(hits / n_dir, 3) if n_dir else None,
            "pearson_score_vs_return": _pearson(scores, rets),
            "mean_return_hawkish": round(sum(hawk_rets) / len(hawk_rets), 4) if hawk_rets else None,
            "mean_return_dovish": round(sum(dove_rets) / len(dove_rets), 4) if dove_rets else None,
        }
    return out


def run(store, windows: list[int] = None) -> dict:
    """读 S3 声明分数 + 本地 XAU 价格，产出完整归因结果（含覆盖范围注记）。"""
    from macropulse.extraction.cli import _index  # 复用声明索引
    windows = windows or config.ATTRIBUTION_WINDOWS_MIN

    stmt_keys = {}
    paginator = store.s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=store.bucket,
                                   Prefix=f"{config.SCORES_PREFIX}/statement/"):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                d = o["Key"].rsplit("_", 1)[-1].replace(".json", "")
                stmt_keys[d] = o["Key"]

    prices = XauPrices()
    try:
        lo, hi = prices.coverage()
        records, skipped = [], []
        for date in sorted(stmt_keys):
            score = store.load_json(stmt_keys[date])
            t0 = events.release_ts_ms(date)
            if lo is None or t0 < lo or t0 > hi:
                skipped.append(date)
                continue
            records.append(build_event(score, prices, windows))
    finally:
        prices.close()

    logger.info("归因：%d 个声明有 XAU 覆盖，%d 个超出价格范围被跳过",
                len(records), len(skipped))
    return {
        "instrument": "XAU",
        "windows_min": windows,
        "n_scored_statements": len(stmt_keys),
        "n_attributed": len(records),
        "n_skipped_no_price": len(skipped),
        "skipped_dates": skipped,
        "events": records,
        "aggregate": aggregate(records, windows),
    }
