"""抽取 schema v0.1 的 Pydantic 模型，对齐交接文档。

两层结构：
  - LLM 输出模型（StatementScores / MinutesScores）：只让模型产判断——分数、
    引用、置信度、diff 的方向标注。diff 的 old/new 文本不让模型转写，由代码
    从 diff 引擎的确定性结果合并（省 token 且不会转写出错）。
  - 落库模型（ExtractionRecord）：合并后的完整 schema v0.1 JSON。

注意：结构化输出不支持数值范围约束（minimum/maximum），分数范围在
`validate_scores` 里做代码侧校验，违规即 needs_human_review。
key_quote 必须是原文逐字子串（前端溯源），`validate_quotes` 校验。
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

DIRECTIONS = ("hawkish", "dovish", "neutral")


class DimensionScore(BaseModel):
    """单维度打分。key_quote 必须逐字摘自原文。"""
    score: int = Field(description="-5(极鸽)到+5(极鹰)的整数")
    key_quote: str = Field(description="支撑该分数的原文逐字引用（verbatim，不得改写）")
    confidence: float = Field(description="0到1的置信度")


class Dimensions(BaseModel):
    inflation: DimensionScore
    labor: DimensionScore
    balance_sheet_qt: DimensionScore
    forward_guidance: DimensionScore


class DiffLabel(BaseModel):
    """对 diff 引擎产出的一处变化做方向标注。old/new 文本由代码侧合并。"""
    diff_index: int = Field(description="对应输入 diffs 列表的下标")
    direction: Literal["hawkish", "dovish", "neutral"]
    magnitude: Literal[1, 2, 3] = Field(description="变化强度：1轻微 2明显 3重大")


class StatementScores(BaseModel):
    """LLM 对一篇 FOMC 声明的输出。"""
    overall_score: int = Field(description="-5(极鸽)到+5(极鹰)的整数总分")
    dimensions: Dimensions
    diff_labels: list[DiffLabel] = Field(description="对每处措辞变化的方向标注")
    confidence_overall: float
    needs_human_review: bool = Field(description="对判断不确定时置 true")


class MinutesScores(BaseModel):
    """LLM 对一篇 FOMC 纪要的输出（无 diff 部分，多一个分歧维度）。"""
    overall_score: int
    dimensions: Dimensions
    dissent_summary: str = Field(description="委员分歧的一句话概括，无分歧则说明一致")
    confidence_overall: float
    needs_human_review: bool


# ---------------------------------------------------------------- 代码侧校验


def validate_quotes(dimensions: Dimensions, source_text: str) -> list[str]:
    """key_quote 必须是原文子串。返回违规的维度名列表。"""
    bad = []
    for name in ("inflation", "labor", "balance_sheet_qt", "forward_guidance"):
        quote = getattr(dimensions, name).key_quote.strip()
        if quote and quote not in source_text:
            bad.append(name)
    return bad


def validate_scores(scores) -> list[str]:
    """分数/置信度范围校验（结构化输出不支持 min/max，代码侧兜底）。返回问题列表。"""
    problems = []
    if not -5 <= scores.overall_score <= 5:
        problems.append(f"overall_score={scores.overall_score} 越界")
    for name in ("inflation", "labor", "balance_sheet_qt", "forward_guidance"):
        d = getattr(scores.dimensions, name)
        if not -5 <= d.score <= 5:
            problems.append(f"{name}.score={d.score} 越界")
        if not 0.0 <= d.confidence <= 1.0:
            problems.append(f"{name}.confidence={d.confidence} 越界")
    if not 0.0 <= scores.confidence_overall <= 1.0:
        problems.append(f"confidence_overall={scores.confidence_overall} 越界")
    return problems


def build_record(
    doc: dict,
    scores,
    diffs_vs_previous: Optional[list[dict]] = None,
    model: str = "",
    prompt_version: str = "",
    quote_violations: Optional[list[str]] = None,
    score_violations: Optional[list[str]] = None,
) -> dict:
    """合并 LLM 输出与确定性 diff，产出落库的 schema v0.1 JSON。"""
    needs_review = scores.needs_human_review or bool(quote_violations) or bool(score_violations)
    record = {
        "document_id": doc["document_id"],
        "central_bank": doc["central_bank"],
        "doc_type": doc["doc_type"],
        "meeting_date": doc["meeting_date"],
        "overall_score": scores.overall_score,
        "dimensions": scores.dimensions.model_dump(),
        "diffs_vs_previous": diffs_vs_previous or [],
        "confidence_overall": scores.confidence_overall,
        "needs_human_review": needs_review,
        "quote_violations": quote_violations or [],
        "score_violations": score_violations or [],
        "model": model,
        "prompt_version": prompt_version,
    }
    if hasattr(scores, "dissent_summary"):
        record["dissent_summary"] = scores.dissent_summary
    return record


def merge_diff_labels(diff_paragraphs: list[dict], labels: list[DiffLabel]) -> list[dict]:
    """把 LLM 的方向标注合并进 diff 引擎的确定性变化列表。

    diff_paragraphs: diff.py 产出的非 unchanged 段落（dict 形式）。
    下标越界的标注丢弃（计为模型输出问题，但不中断）。
    """
    by_index = {lb.diff_index: lb for lb in labels}
    out = []
    for i, p in enumerate(diff_paragraphs):
        lb = by_index.get(i)
        out.append({
            "section": f"para_{p.get('old_index') if p.get('old_index') is not None else p.get('new_index')}",
            "status": p["status"],
            "old": p.get("old_text", ""),
            "new": p.get("new_text", ""),
            "direction": lb.direction if lb else "neutral",
            "magnitude": lb.magnitude if lb else 1,
        })
    return out
