"""Golden 基准快照管理。

把当前生产分数（S3）冻结成 committed JSON（macropulse/eval/golden_scores.json），
作为回归与漂移测试的参照。CI 跑不了 S3/API，所以必须 commit 这份快照。

只保留回归关心的数值字段（分数/置信度/标志），丢弃 key_quote 全文与 diff 数组
以保持文件紧凑。重打 prompt 后用 `cli.py snapshot` 刷新并 review diff。
"""

from __future__ import annotations

import os
import json

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden_scores.json")

# 校准锚点的期望分数带（与 prompts.ANCHOR_DATES 对应）：
# 重打后锚点分数若漂出带外，说明 prompt 改动动摇了标尺，回归应失败。
ANCHOR_BANDS = {
    "fed_statement_2022-06-15": (3, 5),    # 极鹰
    "fed_statement_2024-09-18": (-5, -2),  # 鸽
    "fed_statement_2024-01-31": (-1, 1),   # 中性
}


def _trim(record: dict) -> dict:
    """只留回归关心的字段。"""
    dims = {k: {"score": v["score"], "confidence": v["confidence"]}
            for k, v in record["dimensions"].items()}
    return {
        "document_id": record["document_id"],
        "doc_type": record["doc_type"],
        "meeting_date": record["meeting_date"],
        "overall_score": record["overall_score"],
        "dimensions": dims,
        "confidence_overall": record["confidence_overall"],
        "needs_human_review": record["needs_human_review"],
        "quote_violations": record.get("quote_violations", []),
        "score_violations": record.get("score_violations", []),
        "model": record.get("model", ""),
        "prompt_version": record.get("prompt_version", ""),
    }


def load_golden(path: str = GOLDEN_PATH) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {r["document_id"]: r for r in json.load(f)}


def save_golden(records: list[dict], path: str = GOLDEN_PATH) -> int:
    trimmed = sorted((_trim(r) for r in records), key=lambda r: (r["doc_type"], r["meeting_date"]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return len(trimmed)
