"""Tier-1 结构/校准回归（CI 安全：纯跑 committed golden，无 API/S3/网络）。

每次提交都跑——prompt/schema 改动若动摇分数标尺或破坏 schema，这里失败。
重打 prompt 后用 `python -m macropulse.eval.cli snapshot` 刷新 golden 并 review diff。
"""

import pytest

from macropulse.eval.golden import load_golden, ANCHOR_BANDS
from macropulse.eval import regression

pytestmark = [pytest.mark.unit, pytest.mark.macro]


@pytest.fixture(scope="module")
def golden():
    return load_golden()


def test_golden_nonempty(golden):
    assert len(golden) >= 80  # 87 生产分数，留点余量


def test_all_records_structurally_valid(golden):
    problems = regression.check_all(golden)
    assert not problems, f"golden 结构问题: {problems}"


def test_anchor_calibration_bands_hold(golden):
    """锚点分数必须落在期望带内——这是分数标尺没被 prompt 改动带偏的证据。"""
    violations = regression.check_anchor_bands(golden)
    assert not violations, f"锚点漂出校准带: {violations}"


def test_anchors_present(golden):
    for did in ANCHOR_BANDS:
        assert did in golden, f"锚点 {did} 不在 golden"


def test_no_residual_score_violations(golden):
    """生产基准里不该有未处理的分数范围硬违规。"""
    bad = {did: r["score_violations"] for did, r in golden.items() if r.get("score_violations")}
    assert not bad, f"残留 score_violations: {bad}"


# ---- compare_drift 纯逻辑（不调 API，验证漂移判定本身正确）

def test_compare_drift_detects_large_shift():
    g = {"x": {"overall_score": 2}}
    assert regression.compare_drift(g, {"x": {"overall_score": 2}}) == []
    assert regression.compare_drift(g, {"x": {"overall_score": 3}}, threshold=1) == []  # 边界内
    assert regression.compare_drift(g, {"x": {"overall_score": 4}}, threshold=1)        # 超阈值


def test_compare_drift_detects_sign_flip():
    g = {"x": {"overall_score": 1}}
    flips = regression.compare_drift(g, {"x": {"overall_score": -1}}, threshold=5)
    assert any("方向翻转" in v for v in flips)
