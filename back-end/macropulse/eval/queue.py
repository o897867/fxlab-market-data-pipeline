"""人工裁决队列。

从生产分数 + 归因结果里挑出"不放心"的样本进队列，供本人裁决；裁决结果存
committed adjudications.json，回流为校准依据，并把已裁决项移出队列。

入队理由：
  needs_human_review  —— 模型自标不确定
  low_confidence      —— confidence_overall 低于阈值
  quote_violation     —— key_quote 非原文逐字
  price_conflict      —— 与声明后 XAU 实际反应冲突（方向打脸 / 中性却大波动）
"""

from __future__ import annotations

import os
import json

LOW_CONFIDENCE = 0.6
PRICE_CONFLICT_RET = 1.0   # 非中性方向打脸且 |1d收益| 超此值（%）
NEUTRAL_BIG_MOVE = 2.0     # 中性分但 |1d收益| 超此值（%）

ADJUDICATIONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),  # back-end/
    "data", "eval", "adjudications.json")


def load_adjudications(path: str = ADJUDICATIONS_PATH) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {a["document_id"]: a for a in json.load(f)}


def _price_conflict(score: dict, attribution_event: dict | None) -> str | None:
    """与 1d XAU 反应是否冲突。返回理由串或 None。"""
    if not attribution_event:
        return None
    r = attribution_event["reactions"].get("1440")
    if not r:
        return None
    ret = r["return_pct"]
    s = score["overall_score"]
    if s == 0 and abs(ret) >= NEUTRAL_BIG_MOVE:
        return f"中性分(0)但1d XAU {ret:+.2f}%大波动"
    if s != 0 and r["hit"] is False and abs(ret) >= PRICE_CONFLICT_RET:
        return f"方向打脸：分{s:+d}预期{'跌' if s>0 else '涨'}，实际1d {ret:+.2f}%"
    return None


def build_queue(scores: list[dict], attribution: dict | None = None,
                adjudicated: dict[str, dict] = None) -> list[dict]:
    """拢出待裁决项（已裁决的排除）。"""
    adjudicated = adjudicated or {}
    attr_by_id = {}
    if attribution:
        attr_by_id = {e["document_id"]: e for e in attribution.get("events", [])}

    queue = []
    for sc in scores:
        did = sc["document_id"]
        if did in adjudicated:
            continue
        reasons = []
        if sc.get("needs_human_review"):
            reasons.append("needs_human_review")
        if sc.get("confidence_overall", 1.0) < LOW_CONFIDENCE:
            reasons.append(f"low_confidence({sc['confidence_overall']})")
        if sc.get("quote_violations"):
            reasons.append(f"quote_violation{sc['quote_violations']}")
        pc = _price_conflict(sc, attr_by_id.get(did))
        if pc:
            reasons.append(f"price_conflict({pc})")
        if reasons:
            queue.append({
                "document_id": did,
                "doc_type": sc["doc_type"],
                "meeting_date": sc["meeting_date"],
                "overall_score": sc["overall_score"],
                "confidence_overall": sc.get("confidence_overall"),
                "reasons": reasons,
            })
    return sorted(queue, key=lambda q: (q["doc_type"], q["meeting_date"]))
