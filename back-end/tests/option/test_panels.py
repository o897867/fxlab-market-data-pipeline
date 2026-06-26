"""OptionLens 服务层单测：纯函数 + 临时 DuckDB（含 mart 表）跑三面板。"""

import datetime as dt

import duckdb
import pytest

from option import panels, config

pytestmark = pytest.mark.unit


# --------------------------------------------------------------- 纯函数

def test_interp_monotone():
    pts = [(100, 0.9), (110, 0.6), (120, 0.3)]
    assert panels._interp(90, pts) == 0.9      # 低于左端取端点
    assert panels._interp(130, pts) == 0.3     # 高于右端取端点
    assert panels._interp(105, pts) == pytest.approx(0.75)  # 线性插值


def test_mood_bands():
    assert panels._mood(0.7) == "挺有可能"
    assert panels._mood(0.4) == "机会一般"
    assert panels._mood(0.2) == "有点难"


def test_is_monthly():
    assert panels._is_monthly(dt.date(2026, 7, 17))   # 第三个周五
    assert not panels._is_monthly(dt.date(2026, 7, 10))
    assert not panels._is_monthly(dt.date(2026, 7, 24))


# --------------------------------------------------------------- 临时库三面板

@pytest.fixture
def _db(tmp_path, monkeypatch):
    path = str(tmp_path / "t.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE SCHEMA main_marts")
    con.execute("""CREATE TABLE main_marts.mart_expected_move AS SELECT
        'NASDAQ:MU' underlying_code, DATE '2026-07-17' expiration, 1213.6 spot,
        1.036 atm_iv, 301.6 expected_move_usd, 911.9 band_low, 1515.2 band_high,
        0.249 pct, 274.0 straddle_em_check""")
    con.execute("""CREATE TABLE main_marts.mart_probability_curve AS SELECT * FROM (VALUES
        ('NASDAQ:MU', DATE '2026-07-17', 1200.0, 1213.6, 0.06, 0.536, 0.536, 0.464),
        ('NASDAQ:MU', DATE '2026-07-17', 1300.0, 1213.6, 0.06, 0.410, 0.410, 0.590))
        t(underlying_code, expiration, strike, spot, t_years, call_delta, prob_above, prob_below)""")
    con.execute("""CREATE TABLE main_marts.mart_strike_distribution AS SELECT * FROM (VALUES
        ('NASDAQ:MU', DATE '2026-07-17', 1200.0, 1213.6, 7617, 1004, 8621, 1, true, 1050.0, 0.41),
        ('NASDAQ:MU', DATE '2026-07-17', 1000.0, 1213.6, 200, 9054, 9254, 2, true, 1050.0, 0.41))
        t(underlying_code, expiration, strike, spot, call_oi, put_oi, total_oi, oi_rank, is_wall, max_pain_strike, pc_ratio)""")
    con.close()
    monkeypatch.setattr(config, "DUCKDB_PATH", path)
    monkeypatch.setattr(panels.config, "DUCKDB_PATH", path)
    return path


def test_expected_move_panel(_db):
    r = panels.expected_move("NASDAQ:MU", expiry="2026-07-17")
    assert r["available"] and r["band_low"] == 911.9 and r["band_high"] == 1515.2
    assert "MU" in r["headline"] and "±25%" in r["headline"]


def test_probability_panel_interpolates(_db):
    r = panels.probability("NASDAQ:MU", 1250, expiry="2026-07-17")
    # 1250 在 1200(0.536) 与 1300(0.410) 之间 → 插值 ~0.473
    assert r["prob_above"] == pytest.approx(0.473, abs=0.01)
    assert "1250" in r["headline"]


def test_distribution_panel_walls(_db):
    r = panels.distribution("NASDAQ:MU", expiry="2026-07-17")
    assert r["max_pain"] == 1050.0 and r["pc_ratio"] == 0.41
    assert "1200" in r["headline"]  # 看涨墙
    sides = {s["strike"]: s["side"] for s in r["strikes"]}
    assert sides[1200.0] == "call" and sides[1000.0] == "put"


def test_unavailable_symbol(_db):
    assert panels.expected_move("NYSE:NONE", expiry="2026-07-17")["available"] is False
