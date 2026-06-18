"""宏观数据事件单测（hermetic：内存 sqlite + 纯函数，不连 FRED/InsightSentry）。"""

import sqlite3
import pytest

from macropulse.attribution import events, macro_events
from macropulse.attribution.backtest import build_event, run_macro

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- 时间/极性


def test_macro_release_local_time():
    # CPI/PCE/非农 8:30 ET → 夏令时 12:30 UTC，冬令时 13:30 UTC
    h, mi = events.MACRO_RELEASE_LOCAL
    assert (h, mi) == (8, 30)
    assert events.local_utc("2026-06-05", h, mi).isoformat() == "2026-06-05T12:30:00+00:00"
    assert events.local_utc("2026-01-09", h, mi).isoformat() == "2026-01-09T13:30:00+00:00"


def test_hot_print_is_hawkish_direction():
    # 正 surprise（热数据）→ 鹰派：金跌(-1) 美元涨(+1) 2Y涨(+1)
    assert events.expected_return_sign(2, "XAU") == -1
    assert events.expected_return_sign(2, "DXY") == 1
    assert events.expected_return_sign(2, "US2Y") == 1


# ---------------------------------------------------------------- zscore


def test_zscore_last_basic():
    vals = [1.0] * 12 + [2.0]  # 前12期均1、std0 → 末位偏离… std=0 返回 None
    assert macro_events.zscore_last(vals) is None
    vals = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 100.0]
    z = macro_events.zscore_last(vals)
    assert z is not None and z > 0  # 末位远高于前窗均值


def test_zscore_last_insufficient():
    assert macro_events.zscore_last([1.0, 2.0]) is None
    assert macro_events.zscore_last([]) is None


# ---------------------------------------------------------------- 表 CRUD


def _row(et="NFP", ref="2026-05-01", ts=1_700_000_000_000, sz=1.5, src="fred_proxy"):
    return {
        "event_type": et, "ref_month": ref, "release_date": "2026-06-05",
        "release_ts_ms": ts, "actual": 150.0, "forecast": None, "previous": 120.0,
        "surprise": 30.0, "surprise_z": sz, "surprise_source": src,
    }


def test_upsert_and_load_roundtrip():
    conn = sqlite3.connect(":memory:")
    macro_events.upsert(conn, [_row()])
    evs = macro_events.load_events(conn)
    assert len(evs) == 1
    e = evs[0]
    assert e["document_id"] == "NFP-2026-05-01"
    assert e["overall_score"] == 1.5  # = surprise_z
    assert e["meeting_date"] == "2026-06-05"
    assert e["surprise_source"] == "fred_proxy"


def test_consensus_overrides_proxy_on_conflict():
    conn = sqlite3.connect(":memory:")
    macro_events.upsert(conn, [_row(sz=1.5, src="fred_proxy")])
    macro_events.upsert(conn, [{**_row(sz=2.0, src="consensus"), "forecast": 100.0}])
    evs = macro_events.load_events(conn)
    assert len(evs) == 1  # 同 (event_type, ref_month) → 覆盖非新增
    assert evs[0]["surprise_source"] == "consensus"
    assert evs[0]["forecast"] == 100.0


def test_load_skips_null_surprise_z():
    conn = sqlite3.connect(":memory:")
    macro_events.upsert(conn, [_row(sz=None)])
    assert macro_events.load_events(conn) == []


# ---------------------------------------------------------------- build_event t0_ms


def test_build_event_honors_explicit_t0():
    t0 = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    for tbl in ("xau_candles_1m", "dxy_candles_1m", "us2y_candles_1m"):
        conn.execute(f"CREATE TABLE {tbl} (open_time INTEGER, close REAL)")
        conn.executemany(f"INSERT INTO {tbl} VALUES (?,?)",
                         [(t0, 100.0), (t0 + 15 * 60_000, 101.0)])
    conn.commit()
    from macropulse.attribution.prices import InstrumentPrices
    pbi = {i: InstrumentPrices(conn=conn, table=events.INSTRUMENT_TABLE[i])
           for i in ("XAU", "DXY", "US2Y")}
    score = {"document_id": "NFP-x", "meeting_date": "2026-06-05",
             "overall_score": 2.0, "event_type": "NFP", "surprise_source": "fred_proxy"}
    rec = build_event(score, pbi, windows=[15], t0_ms=t0)
    # 价格涨1%：DXY 鹰派预期涨(+1) → 命中；XAU 预期跌(-1) → 不命中
    assert rec["reactions"]["DXY"]["15"]["hit"] is True
    assert rec["reactions"]["XAU"]["15"]["hit"] is False
    assert rec["event_type"] == "NFP"  # 透传


def test_run_macro_end_to_end():
    t0 = 1_700_000_000_000
    conn = sqlite3.connect(":memory:")
    for tbl in ("xau_candles_1m", "dxy_candles_1m", "us2y_candles_1m"):
        conn.execute(f"CREATE TABLE {tbl} (open_time INTEGER, close REAL)")
        conn.executemany(f"INSERT INTO {tbl} VALUES (?,?)",
                         [(t0, 100.0), (t0 + 15 * 60_000, 101.0)])
    conn.commit()
    macro_events.upsert(conn, [_row(ts=t0, sz=2.0)])
    out = run_macro(conn=conn, windows=[15])
    assert out["n_events"] == 1
    assert "NFP" in out["by_event_type"]
    assert out["aggregate_pooled"]["consensus"]["15"]["n_directional"] == 3  # 三标的各一观测
