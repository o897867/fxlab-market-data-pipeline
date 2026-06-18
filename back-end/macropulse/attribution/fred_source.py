"""历史轨：FRED → 宏观事件历史（2021→今），喂 macro_releases。

FRED 给得了 actual 实际值 + 精确发布日，但**没有 consensus**。所以历史段的
surprise 用"该期头条指标 vs 近 12 期均值"的标准化偏离作代理
（surprise_source='fred_proxy'）。这是有意的弱信号——writeup 里写清，
前向轨用真 consensus 覆盖。

头条指标按 kind：
  index（CPI/核心CPI/核心PCE）→ MoM%  =(idx_t/idx_{t-1}-1)*100
  level（非农 PAYEMS，单位千人）→ 环比变动量 = lvl_t - lvl_{t-1}

发布日只给日期，这三个统一 8:30 a.m. ET 释放 → local_utc 补时刻。
ref 月与发布日按"月末之后第一个发布日"对齐（稳健，免硬编码偏移）。
"""

from __future__ import annotations

import os
import logging
from datetime import date

import requests

from macropulse.attribution import events
from macropulse.attribution.macro_events import EVENT_SPECS, zscore_last

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"


def _api_key() -> str:
    k = os.getenv("FRED_API_KEY")
    if not k:
        raise RuntimeError("FRED_API_KEY 未设置（应在 back-end/.env）")
    return k


def _get(path: str, **params) -> dict:
    params.update(api_key=_api_key(), file_type="json")
    r = requests.get(f"{FRED_BASE}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_observations(series_id: str, start: str = "2020-01-01") -> list[tuple]:
    """[(ref_month 'YYYY-MM-01', value float)]，按月升序，跳过缺测('.')。"""
    d = _get("series/observations", series_id=series_id,
             observation_start=start, sort_order="asc")
    out = []
    for o in d.get("observations", []):
        v = o.get("value")
        if v in (None, ".", ""):
            continue
        out.append((o["date"], float(v)))
    return out


def fetch_release_dates(release_id: int, start: str = "2020-01-01") -> list[str]:
    """该 release 的历史发布日（升序 'YYYY-MM-DD'）。"""
    d = _get("release/dates", release_id=release_id,
             include_release_dates_with_no_data="false",
             sort_order="asc", limit=10000)
    return [x["date"] for x in d.get("release_dates", []) if x["date"] >= start]


def _month_end(ref_month: str) -> str:
    y, m, _ = (int(x) for x in ref_month.split("-"))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(ny, nm, 1).isoformat()  # 下月1日，作"月末之后"的下界


def _match_release(ref_month: str, release_dates: list[str]) -> str | None:
    """月末之后第一个发布日。"""
    floor = _month_end(ref_month)
    for rd in release_dates:
        if rd >= floor:
            return rd
    return None


def build_history(event_type: str, start: str = "2021-01-01") -> list[dict]:
    """产出某事件类型的历史 macro_releases 行（surprise_z 用代理）。"""
    spec = EVENT_SPECS[event_type]
    obs = fetch_observations(spec.fred_series, start="2020-01-01")  # 多取一年算 MoM/窗口
    rels = fetch_release_dates(spec.release_id, start="2020-06-01")
    if len(obs) < 14:
        logger.warning("%s: FRED 观测不足(%d)", event_type, len(obs))
        return []

    # 逐月头条指标
    metric = []  # [(ref_month, value, prev_value)]
    for i in range(1, len(obs)):
        ref_month, val = obs[i]
        _, prev = obs[i - 1]
        if spec.kind == "index":
            m = (val / prev - 1) * 100 if prev else None
        else:  # level
            m = val - prev
        if m is not None:
            metric.append((ref_month, round(m, 4), obs[i - 1]))

    rows = []
    series_vals = [m for _, m, _ in metric]
    for idx, (ref_month, m, _prev_obs) in enumerate(metric):
        if ref_month < start:
            continue
        rel = _match_release(ref_month, rels)
        if rel is None:
            continue
        h, mi = events.MACRO_RELEASE_LOCAL
        ts_ms = int(events.local_utc(rel, h, mi).timestamp() * 1000)
        z = zscore_last(series_vals[: idx + 1])
        prev_metric = metric[idx - 1][1] if idx > 0 else None
        rows.append({
            "event_type": event_type,
            "ref_month": ref_month,
            "release_date": rel,
            "release_ts_ms": ts_ms,
            "actual": m,
            "forecast": None,
            "previous": prev_metric,
            "surprise": round(m - prev_metric, 4) if prev_metric is not None else None,
            "surprise_z": z,
            "surprise_source": "fred_proxy",
        })
    return rows


def build_all_history(start: str = "2021-01-01") -> list[dict]:
    rows = []
    for et in EVENT_SPECS:
        r = build_history(et, start=start)
        logger.info("FRED 历史 %s: %d 行", et, len(r))
        rows += r
    return rows
