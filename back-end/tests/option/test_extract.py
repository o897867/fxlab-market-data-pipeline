"""OptionLens 抽取层单测（hermetic：monkeypatch HTTP，不触网）。"""

import pandas as pd
import pytest

from option import extract, config

pytestmark = pytest.mark.unit


@pytest.fixture
def _stub(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr(extract.config, "SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr(extract, "fetch_underlying", lambda c: {"code": c, "last_price": 100.0})
    monkeypatch.setattr(extract, "fetch_quotes", lambda *a, **k: ([
        {"code": "OPRA:MU260717C100.0", "type": "CALL", "strike_price": 100.0,
         "expiration": 20260717, "bid_price": 5.0, "ask_price": 5.4,
         "implied_volatility": 0.5, "bid_iv": 0.49, "ask_iv": 0.51, "delta": 0.52,
         "gamma": 0.03, "theta": -0.2, "vega": 0.1, "rho": 0.05, "theoretical_price": 5.2},
    ], 1_700_000_000_000))
    monkeypatch.setattr(extract, "fetch_contracts", lambda *a, **k: ([
        {"code": "OPRA:MU260717C100.0", "type": "CALL", "strike_price": 100.0,
         "expiration": "2026-07-17", "open_interest": "258", "open_interest_date": "2026-06-24",
         "close_price": "5.1", "multiplier": "100", "style": "american", "status": "active"},
    ], 1_700_000_000_000))
    return tmp_path


def test_snapshot_writes_three_parquet(_stub):
    summ = extract.snapshot("NASDAQ:MU", "2026-07-01", "2026-07-31", 20)
    assert summ["spot"] == 100.0
    assert summ["n_quotes"] == 1 and summ["n_contracts"] == 1
    assert summ["expirations"] == ["2026-07-17"]
    for kind in ("quotes", "contracts", "underlying"):
        df = pd.read_parquet(summ["paths"][kind])
        assert len(df) >= 1 and "snapshot_ts" in df.columns


def test_quotes_carry_spot_and_underlying(_stub):
    summ = extract.snapshot("NASDAQ:MU", "2026-07-01", "2026-07-31", 20)
    q = pd.read_parquet(summ["paths"]["quotes"])
    assert q.iloc[0]["spot"] == 100.0
    assert q.iloc[0]["underlying_code"] == "NASDAQ:MU"
    assert q.iloc[0]["code"] == "OPRA:MU260717C100.0"  # join 键
    assert q.iloc[0]["delta"] == 0.52


def test_snapshot_ts_from_last_update(_stub):
    summ = extract.snapshot("NASDAQ:MU", "2026-07-01", "2026-07-31", 20)
    # last_update 1_700_000_000_000 ms → 2023-11-14
    assert summ["snapshot_ts"].startswith("2023-11-14")
