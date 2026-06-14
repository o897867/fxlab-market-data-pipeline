"""归因回测单测（hermetic：内存 sqlite + 纯函数，不连 S3/不读价格库）。"""

import sqlite3
import pytest

from macropulse.attribution import events
from macropulse.attribution.prices import XauPrices
from macropulse.attribution.backtest import build_event, aggregate, _pearson

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- events


def test_release_utc_dst():
    # 夏令时：EDT=UTC-4 → 18:00 UTC
    assert events.release_utc("2026-04-29").isoformat() == "2026-04-29T18:00:00+00:00"
    # 冬令时：EST=UTC-5 → 19:00 UTC
    assert events.release_utc("2026-01-28").isoformat() == "2026-01-28T19:00:00+00:00"


def test_release_ts_ms_roundtrip():
    import datetime as dt
    ts = events.release_ts_ms("2026-04-29")
    back = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
    assert back.hour == 18 and back.minute == 0


@pytest.mark.parametrize("score,expected", [(3, -1), (-2, 1), (0, 0)])
def test_expected_return_sign(score, expected):
    assert events.expected_return_sign(score) == expected


# ---------------------------------------------------------------- prices


def _mem_prices(candles):
    """candles: [(open_time_ms, close)]"""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE xau_candles_1m (open_time INTEGER, close REAL)")
    conn.executemany("INSERT INTO xau_candles_1m VALUES (?,?)", candles)
    conn.commit()
    return XauPrices(conn=conn)


def test_window_return_basic():
    t0 = 1_000_000_000_000
    # t0 价 100；t0+15min 价 99（跌 1%）
    p = _mem_prices([(t0, 100.0), (t0 + 15 * 60_000, 99.0)])
    r = p.window_return(t0, 15)
    assert r["p0"] == 100.0 and r["p1"] == 99.0
    assert r["return_pct"] == -1.0


def test_window_return_at_or_before():
    t0 = 1_000_000_000_000
    # 目标时刻无精确K线，取之前最近的
    p = _mem_prices([(t0, 100.0), (t0 + 14 * 60_000, 101.0)])  # 15min窗内最近是+14min
    r = p.window_return(t0, 15)
    assert r["p1"] == 101.0 and r["p1_lag_min"] == 1.0


def test_window_return_none_when_gap_too_large():
    t0 = 1_000_000_000_000
    # t0+1d 目标，但最近K线在 t0（滞后 1440min > 180 容忍）→ 不可用
    p = _mem_prices([(t0, 100.0)])
    assert p.window_return(t0, 1440, max_lag_min=180) is None


def test_coverage():
    p = _mem_prices([(100, 1.0), (200, 2.0)])
    assert p.coverage() == (100, 200)


# ---------------------------------------------------------------- build_event


def _score(date, overall):
    return {"document_id": f"fed_statement_{date}", "meeting_date": date,
            "overall_score": overall, "confidence_overall": 0.8}


def test_build_event_hawkish_hit():
    # 鹰派(+2) → 预期黄金跌；实际跌 → 命中
    date = "2026-04-29"
    t0 = events.release_ts_ms(date)
    p = _mem_prices([(t0, 100.0), (t0 + 15 * 60_000, 98.0)])
    e = build_event(_score(date, 2), p, windows=[15])
    r = e["reactions"]["15"]
    assert e["expected_return_sign"] == -1
    assert r["return_sign"] == -1 and r["hit"] is True


def test_build_event_dovish_miss():
    # 鸽派(-2) → 预期黄金涨；实际跌 → 未命中
    date = "2026-04-29"
    t0 = events.release_ts_ms(date)
    p = _mem_prices([(t0, 100.0), (t0 + 15 * 60_000, 99.0)])
    e = build_event(_score(date, -2), p, windows=[15])
    assert e["reactions"]["15"]["hit"] is False


def test_build_event_neutral_no_prediction():
    date = "2026-04-29"
    t0 = events.release_ts_ms(date)
    p = _mem_prices([(t0, 100.0), (t0 + 15 * 60_000, 101.0)])
    e = build_event(_score(date, 0), p, windows=[15])
    assert e["expected_return_sign"] == 0
    assert e["reactions"]["15"]["hit"] is None


def test_build_event_missing_price_window():
    date = "2026-04-29"
    t0 = events.release_ts_ms(date)
    p = _mem_prices([(t0, 100.0)])  # 只有 t0 一根；1d 后无价且滞后超容忍
    e = build_event(_score(date, 1), p, windows=[1440])
    assert e["reactions"]["1440"] is None


# ---------------------------------------------------------------- aggregate


def _evt(date, score, ret, hit, window="15"):
    sign = 1 if ret > 0 else (-1 if ret < 0 else 0)
    return {"document_id": f"x_{date}", "meeting_date": date, "overall_score": score,
            "reactions": {window: {"window_min": 15, "p0": 100, "p1": 100 + ret,
                                   "return_pct": ret, "return_sign": sign, "hit": hit,
                                   "p1_lag_min": 0}}}


def test_aggregate_hit_rate_excludes_neutral():
    evts = [
        _evt("a", 2, -1.0, True),    # 鹰命中
        _evt("b", -2, 1.0, True),    # 鸽命中
        _evt("c", 1, 0.5, False),    # 鹰未命中
        _evt("d", 0, 0.3, None),     # 中性，不计命中
    ]
    agg = aggregate(evts, windows=[15])["15"]
    assert agg["n_events"] == 4
    assert agg["n_directional"] == 3  # 排除中性
    assert agg["hits"] == 2
    assert agg["hit_rate"] == round(2 / 3, 3)
    assert agg["mean_return_hawkish"] == round((-1.0 + 0.5) / 2, 4)
    assert agg["mean_return_dovish"] == 1.0


def test_aggregate_skips_missing_window():
    evts = [_evt("a", 2, -1.0, True)]
    evts.append({"document_id": "b", "meeting_date": "b", "overall_score": 1,
                 "reactions": {"15": None}})  # 缺价
    agg = aggregate(evts, windows=[15])["15"]
    assert agg["n_events"] == 1  # 缺价的被排除


def test_pearson_negative_relationship():
    # 鹰鸽分数与收益负相关（鹰高→收益低）
    r = _pearson([2, 1, -2], [-1.0, -0.5, 1.0])
    assert r is not None and r < -0.9


def test_pearson_too_few():
    assert _pearson([1], [1.0]) is None
