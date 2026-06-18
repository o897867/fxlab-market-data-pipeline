"""模型 C（利率预期重定价）单测：纯函数，合成数据，不连 S3/价格库。"""

import pytest
from macropulse.attribution import rate_model

pytestmark = pytest.mark.unit


def test_directional_perfect_signal():
    # 信号与 Δrate 同号 → 100% 命中
    pairs = [(2.0, 5.0), (-1.0, -3.0), (1.5, 0.5), (-2.0, -1.0)]
    d = rate_model._directional(pairs)
    assert d["n"] == 4 and d["hits"] == 4 and d["hit_rate"] == 1.0


def test_directional_skips_none_and_zero():
    pairs = [(1.0, None), (0.0, 5.0), (2.0, 0.0), (1.0, 2.0)]
    d = rate_model._directional(pairs)
    assert d["n"] == 1 and d["hit_rate"] == 1.0  # 只剩 (1,2)


def test_ols_positive_slope():
    xs = [-2.0, -1.0, 0.0, 1.0, 2.0]
    ys = [-4.0, -2.0, 0.0, 2.0, 4.0]  # y=2x
    o = rate_model._ols(xs, ys)
    assert o["beta_bp"] == 2.0 and o["r2"] == 1.0 and o["n"] == 5


def test_ols_too_few():
    assert rate_model._ols([1.0, 2.0], [1.0, 2.0]) is None


def test_zscore_by_source_separates():
    rows = [
        {"source": "score", "signal": 5.0}, {"source": "score", "signal": -5.0},
        {"source": "fred_proxy", "signal": 2.0}, {"source": "fred_proxy", "signal": -2.0},
    ]
    z = rate_model._zscore_by_source(rows)
    # 每个 source 内部对称 → z 应为 ±1
    assert abs(z[id(rows[0])] - 1.0) < 1e-9
    assert abs(z[id(rows[2])] - 1.0) < 1e-9  # 不同尺度但标准化后同为 +1


def test_summarize_shape():
    rows = [
        {"date": "2024-01-01", "event_type": "FOMC", "source": "score",
         "signal": 3.0, "drate": {15: 4.0, 60: 5.0}},
        {"date": "2024-02-01", "event_type": "FOMC", "source": "score",
         "signal": -2.0, "drate": {15: -3.0, 60: None}},
        {"date": "2024-03-01", "event_type": "CPI", "source": "fred_proxy",
         "signal": 1.0, "drate": {15: 2.0, 60: 1.0}},
        {"date": "2024-04-01", "event_type": "CPI", "source": "fred_proxy",
         "signal": -1.0, "drate": {15: -1.0, 60: -2.0}},
        {"date": "2024-05-01", "event_type": "CPI", "source": "fred_proxy",
         "signal": 2.0, "drate": {15: 3.0, 60: 1.0}},
    ]
    s = rate_model.summarize(rows, [15, 60])
    assert s["n_events"] == 5
    assert s["by_window"]["15"]["directional_pooled"]["hit_rate"] == 1.0  # 全部同号
    assert s["by_window"]["60"]["n"] == 4  # 一个 None 被剔
    assert "FOMC" in s["by_window"]["15"]["by_event_type"]
