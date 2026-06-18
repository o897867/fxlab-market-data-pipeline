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


def test_wilson_ci_brackets_half():
    lo, hi = rate_model.wilson_ci(50, 100)
    assert lo < 0.5 < hi and 0 < lo and hi < 1


def test_wilson_ci_lower_above_half_when_strong():
    lo, hi = rate_model.wilson_ci(90, 100)
    assert lo > 0.5  # 90/100 显著高于硬币


def test_ols_origin_through_zero():
    assert rate_model._ols_origin([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == 2.0
    assert rate_model._ols_origin([0.0], [5.0]) == 0.0  # sxx=0 → 0


def test_oos_metrics_perfect_direction():
    m = rate_model._oos_metrics([(1.0, 2.0), (-1.0, -3.0), (2.0, 1.0)])
    assert m["n"] == 3 and m["dir_hit"] == 1.0 and m["beats_coin"] is False  # N小CI宽


def test_walk_forward_basic():
    rows = [{"date": f"2024-{m:02d}-01", "event_type": "CPI", "source": "consensus",
             "signal": float(s), "drate": {15: float(s) * 2}}
            for m, s in enumerate([1, -1, 2, -2, 1, -1, 2, -2, 1, -1, 2, -2, 3, -3], 1)]
    preds = rate_model.walk_forward(rows, "CPI", 15, min_train=12)
    assert len(preds) == 2  # 14 事件 − 12 训练
    # y=2x，β应≈2，预测方向与实际一致
    assert all(rate_model._sgn(p) == rate_model._sgn(a) for p, a in preds)


def test_deepen_shape():
    rows = [{"date": f"2024-{m:02d}-01", "event_type": "CPI", "source": "consensus",
             "signal": float((-1) ** m), "drate": {15: None, 60: None, 1440: float((-1) ** m)}}
            for m in range(1, 16)]
    d = rate_model.deepen(rows, min_train=10)
    assert "CPI" in d["by_signal"]
    assert d["by_signal"]["CPI"]["primary_window"] == 1440
    assert d["pooled_oos"]["n"] >= 1


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
