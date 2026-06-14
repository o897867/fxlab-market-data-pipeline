"""裁决队列单测（hermetic）。"""

import pytest

from macropulse.eval import queue as q

pytestmark = [pytest.mark.unit, pytest.mark.macro]


def _score(did, overall=1, conf=0.8, needs=False, qv=None):
    return {"document_id": did, "doc_type": "statement", "meeting_date": "2026-04-29",
            "overall_score": overall, "confidence_overall": conf,
            "needs_human_review": needs, "quote_violations": qv or []}


def _attr(did, ret_1d, hit):
    return {"events": [{"document_id": did,
                        "reactions": {"1440": {"return_pct": ret_1d, "hit": hit}}}]}


def test_needs_review_enters_queue():
    out = q.build_queue([_score("a", needs=True)])
    assert len(out) == 1 and "needs_human_review" in out[0]["reasons"]


def test_low_confidence_enters_queue():
    out = q.build_queue([_score("a", conf=0.5)])
    assert any("low_confidence" in r for r in out[0]["reasons"])


def test_quote_violation_enters_queue():
    out = q.build_queue([_score("a", qv=["inflation"])])
    assert any("quote_violation" in r for r in out[0]["reasons"])


def test_clean_score_not_queued():
    assert q.build_queue([_score("a")]) == []


def test_adjudicated_excluded():
    out = q.build_queue([_score("a", needs=True)], adjudicated={"a": {"document_id": "a"}})
    assert out == []


def test_price_conflict_direction_miss():
    # 鹰派(+2)预期黄金跌，实际1d涨3% 且 hit=False → 打脸入队
    out = q.build_queue([_score("a", overall=2)], _attr("a", 3.0, False))
    assert any("price_conflict" in r for r in out[0]["reasons"])


def test_price_conflict_neutral_big_move():
    # 中性(0)但1d跌5.67%（即真实数据里的 2026-03-18 情形）
    out = q.build_queue([_score("a", overall=0)], _attr("a", -5.67, None))
    assert any("price_conflict" in r and "大波动" in r for r in out[0]["reasons"])


def test_price_conflict_small_move_ignored():
    # 方向打脸但波动很小 → 不入队（噪音）
    out = q.build_queue([_score("a", overall=2)], _attr("a", 0.3, False))
    assert out == []
