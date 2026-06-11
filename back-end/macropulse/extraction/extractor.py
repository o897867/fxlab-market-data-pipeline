"""Claude API 调用层。

单篇路径用 client.messages.parse() + Pydantic（SDK 自动做 schema 约束与校验，
自动剥离不支持的数值约束并在客户端校验）。Batch 路径在 cli.py（结构化输出走
output_config.format + 手动 Pydantic 校验）。

成本可观测：每次调用累计 usage（input/output/cache token），CLI 结束时报告
实际花费，与计划估算对照。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import anthropic

from macropulse import config
from macropulse.extraction import prompts, schema
from macropulse.extraction.schema import StatementScores, MinutesScores

logger = logging.getLogger(__name__)

# Opus 4.8 价格（USD / MTok），用于花费报告
_PRICE_IN, _PRICE_OUT = 5.0, 25.0
_PRICE_CACHE_READ, _PRICE_CACHE_WRITE = 0.5, 6.25


@dataclass
class UsageTally:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    calls: int = 0

    def add(self, usage) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def cost_usd(self) -> float:
        m = 1_000_000
        return (self.input_tokens / m * _PRICE_IN
                + self.output_tokens / m * _PRICE_OUT
                + self.cache_read / m * _PRICE_CACHE_READ
                + self.cache_write / m * _PRICE_CACHE_WRITE)

    def report(self) -> str:
        return (f"{self.calls} 次调用 | in {self.input_tokens:,} / out {self.output_tokens:,} "
                f"/ cache_r {self.cache_read:,} / cache_w {self.cache_write:,} "
                f"| ≈ ${self.cost_usd():.3f}")


class Extractor:
    def __init__(self, anchors: list[dict], client=None, model: str = None):
        self.anchors = anchors
        self.client = client or anthropic.Anthropic()
        self.model = model or config.EXTRACT_MODEL
        self.usage = UsageTally()
        self.system_statement = prompts.build_system_prompt(anchors, "statement")
        self.system_minutes = prompts.build_system_prompt(anchors, "minutes")

    def _parse(self, system: str, user: str, output_format):
        resp = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            # 锚点块 >4k token，打缓存断点：回填/回归时后续调用读缓存 ~0.1x
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
        )
        self.usage.add(resp.usage)
        return resp.parsed_output

    def score_statement(self, doc: dict, diff_entries: list[dict]) -> dict:
        """打分一篇声明。diff_entries 来自 diff.py（非 unchanged 段落的 dict 列表）。"""
        scores: StatementScores = self._parse(
            self.system_statement,
            prompts.build_statement_user(doc, diff_entries),
            StatementScores,
        )
        return self._finalize(doc, scores,
                              schema.merge_diff_labels(diff_entries, scores.diff_labels))

    def score_minutes(self, doc: dict) -> dict:
        scores: MinutesScores = self._parse(
            self.system_minutes, prompts.build_minutes_user(doc), MinutesScores)
        return self._finalize(doc, scores, None)

    def _finalize(self, doc: dict, scores, diffs) -> dict:
        quote_bad = schema.validate_quotes(scores.dimensions, doc["text"])
        score_bad = schema.validate_scores(scores)
        if quote_bad:
            logger.warning("%s: key_quote 非原文子串: %s", doc["document_id"], quote_bad)
        if score_bad:
            logger.warning("%s: 分数越界: %s", doc["document_id"], score_bad)
        return schema.build_record(
            doc, scores, diffs_vs_previous=diffs, model=self.model,
            prompt_version=prompts.PROMPT_VERSION,
            quote_violations=quote_bad, score_violations=score_bad,
        )
