"""归因回测单测（hermetic：内存 sqlite + 纯函数，不连 S3/不读价格库）。三标的。"""

import sqlite3
import pytest

from macropulse.attribution import events
from macropulse.attribution.prices import InstrumentPrices, XauPrices
from macropulse.attribution.backtest import build_event, aggregate, _pearson, INSTRUMENTS

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- events


def test_release_utc_dst():
    assert events.release_utc("2026-04-29").isoformat() == "2026-04-29T18:00:00+00:00"  # EDT
    assert events.release_utc("2026-01-28").isoformat() == "2026-01-28T19:00:00+00:00"  # EST


@pytest.mark.parametrize("score,inst,expected", [
    (3, "XAU", -1),    # 鹰→金跌
    (3, "DXY", 1),     # 鹰→美元涨
    (3, "US2Y", 1),    # 鹰→2Y收益率涨
    (-2, "XAU", 1),    # 鸽→金涨
    (-2, "DXY", -1),   # 鸽→美元跌
    (0, "XAU", 0),     # 中性无预期
])
def test_expected_return_sign(score, inst, expected):
    assert events.expected_return_sign(score, inst) == expected


def test_instrument_tables():
    assert events.INSTRUMENT_TABLE["DXY"] == "dxy_candles_1m"
    assert events.INSTRUMENT_TABLE["US2Y"] == "us2y_candles_1m"


# ---------------------------------------------------------------- prices


def _mem_prices(candles, table="xau_candles_1m"):
    conn = sqlite3.connect(":memory:")
    conn.execute(f"CREATE TABLE {table} (open_time INTEGER, close REAL)")
    conn.executemany(f"INSERT INTO {table} VALUES (?,?)", candles)
    conn.commit()
    return InstrumentPrices(conn=conn, table=table)


def test_window_return_basic():
    t0 = 1_000_000_000_000
    p = _mem_prices([(t0, 100.0), (t0 + 15 * 60_000, 99.0)])
    r = p.window_return(t0, 15)
    assert r["p0"] == 100.0 and r["p1"] == 99.0 and r["return_pct"] == -1.0


def test_window_return_none_when_gap_too_large():
    t0 = 1_000_000_000_000
    p = _mem_prices([(t0, 100.0)])
    assert p.window_return(t0, 1440, max_lag_min=180) is None


def test_xauprices_alias():
    assert XauPrices is InstrumentPrices


# ---------------------------------------------------------------- build_event（三标的）


def _score(date, overall):
    return {"document_id": f"fed_statement_{date}", "meeting_date": date,
            "overall_score": overall, "confidence_overall": 0.8}


def _three(date, xau, dxy, us2y):
    """造三标的内存价格：每个给 t0 与 t0+15min 两根。"""
    t0 = events.release_ts_ms(date)
    return {
        "XAU": _mem_prices([(t0, 100.0), (t0 + 15 * 60_000, xau)], "xau_candles_1m"),
        "DXY": _mem_prices([(t0, 100.0), (t0 + 15 * 60_000, dxy)], "dxy_candles_1m"),
        "US2Y": _mem_prices([(t0, 4.0), (t0 + 15 * 60_000, us2y)], "us2y_candles_1m"),
    }


def test_build_event_hawkish_all_hit():
    # 鹰派(+2)：金应跌、美元应涨、2Y应涨。给 金99(跌)、美元101(涨)、2Y4.1(涨) → 全命中
    date = "2026-04-29"
    e = build_event(_score(date, 2), _three(date, 99.0, 101.0, 4.1), windows=[15])
    assert e["expected_signs"] == {"XAU": -1, "DXY": 1, "US2Y": 1}
    assert e["reactions"]["XAU"]["15"]["hit"] is True
    assert e["reactions"]["DXY"]["15"]["hit"] is True
    assert e["reactions"]["US2Y"]["15"]["hit"] is True


def test_build_event_mixed():
    # 鹰派(+2)，但美元反而跌(99) → DXY 未命中；金跌→命中
    date = "2026-04-29"
    e = build_event(_score(date, 2), _three(date, 99.0, 99.0, 4.1), windows=[15])
    assert e["reactions"]["XAU"]["15"]["hit"] is True
    assert e["reactions"]["DXY"]["15"]["hit"] is False


def test_build_event_neutral_no_prediction():
    date = "2026-04-29"
    e = build_event(_score(date, 0), _three(date, 101.0, 101.0, 4.1), windows=[15])
    assert all(e["reactions"][i]["15"]["hit"] is None for i in INSTRUMENTS)


# ---------------------------------------------------------------- aggregate


def _evt(date, score, xau_ret, xau_hit, dxy_ret, dxy_hit):
    def rx(ret, hit):
        return {"15": {"return_pct": ret, "return_sign": (1 if ret > 0 else -1),
                       "hit": hit, "p0": 1, "p1": 1, "window_min": 15, "p1_lag_min": 0}}
    return {"document_id": f"x_{date}", "meeting_date": date, "overall_score": score,
            "reactions": {"XAU": rx(xau_ret, xau_hit), "DXY": rx(dxy_ret, dxy_hit),
                          "US2Y": {"15": None}}}


def test_aggregate_per_instrument_and_consensus():
    evts = [
        _evt("a", 2, -1.0, True, 1.0, True),    # 鹰：金跌命中、美元涨命中
        _evt("b", -2, 1.0, True, -1.0, True),   # 鸽：金涨命中、美元跌命中
        _evt("c", 1, 0.5, False, 0.5, False),   # 鹰：都未命中
        _evt("d", 0, 0.3, None, 0.3, None),     # 中性，不计
    ]
    agg = aggregate(evts, windows=[15])
    # XAU：3 个非中性，2 命中
    assert agg["XAU"]["15"]["n_directional"] == 3 and agg["XAU"]["15"]["hits"] == 2
    # consensus：XAU(3)+DXY(3)+US2Y(0,全None) = 6 观测，4 命中
    assert agg["consensus"]["15"]["n_directional"] == 6
    assert agg["consensus"]["15"]["hits"] == 4


def test_aggregate_skips_none_window():
    evts = [_evt("a", 2, -1.0, True, 1.0, True)]
    agg = aggregate(evts, windows=[15])
    assert agg["US2Y"]["15"]["n_events"] == 0  # US2Y 该窗 None


def test_pearson():
    assert _pearson([2, 1, -2], [-1.0, -0.5, 1.0]) < -0.9
    assert _pearson([1], [1.0]) is None
