"""DeepSeek 抽取器 —— 与 Opus 抽取器同 prompt/锚点/校验，用于横向对比。

DeepSeek API 兼容 OpenAI SDK（base_url https://api.deepseek.com）。与 Claude
路径的差异仅在结构化输出机制：DeepSeek 无原生 JSON Schema 约束，用
json_object 模式 + schema 嵌入指令 + Pydantic 客户端校验（失败重试一次）。
其余（打分标尺、锚点、diff 输入、key_quote/分数校验、落库 record 结构）
全部复用，保证对比的是模型能力而不是 prompt 差异。
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass

from openai import OpenAI
from pydantic import ValidationError

from macropulse.extraction import prompts, schema
from macropulse.extraction.schema import StatementScores, MinutesScores

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = os.getenv("MACRO_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("MACRO_DEEPSEEK_MODEL", "deepseek-v4-pro")

# 价格未内置（以 DeepSeek 官网为准），可通过环境变量提供以便报告花费（USD/MTok）
_PRICE_IN = float(os.getenv("MACRO_DEEPSEEK_PRICE_IN", "0"))
_PRICE_OUT = float(os.getenv("MACRO_DEEPSEEK_PRICE_OUT", "0"))


@dataclass
class DsUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    retries: int = 0

    def add(self, usage) -> None:
        self.calls += 1
        self.input_tokens += usage.prompt_tokens
        self.output_tokens += usage.completion_tokens

    def report(self) -> str:
        cost = ""
        if _PRICE_IN or _PRICE_OUT:
            usd = (self.input_tokens / 1e6 * _PRICE_IN
                   + self.output_tokens / 1e6 * _PRICE_OUT)
            cost = f" | ≈ ${usd:.3f}"
        return (f"{self.calls} 次调用（重试 {self.retries}）| "
                f"in {self.input_tokens:,} / out {self.output_tokens:,}{cost}")


def _format_instruction(model_cls) -> str:
    return (
        "\n\n输出要求：只输出一个 JSON 对象（不要 markdown 代码块、不要解释文字），"
        "且必须严格符合以下 JSON Schema：\n"
        + json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    )


class DeepSeekExtractor:
    """接口与 extractor.Extractor 对齐：score_statement / score_minutes。"""

    def __init__(self, anchors: list[dict], client=None, model: str = None):
        self.anchors = anchors
        self.client = client or OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"], base_url=DEEPSEEK_BASE_URL)
        self.model = model or DEEPSEEK_MODEL
        self.usage = DsUsage()
        self.system_statement = (prompts.build_system_prompt(anchors, "statement")
                                 + _format_instruction(StatementScores))
        self.system_minutes = (prompts.build_system_prompt(anchors, "minutes")
                               + _format_instruction(MinutesScores))

    def _call(self, system: str, messages: list[dict]):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}] + messages,
            response_format={"type": "json_object"},
            max_tokens=8000,
        )
        self.usage.add(resp.usage)
        return resp.choices[0].message.content

    def _parse(self, system: str, user: str, model_cls):
        text = self._call(system, [{"role": "user", "content": user}])
        try:
            return model_cls.model_validate_json(text)
        except ValidationError as e:
            # 一次纠错重试：把校验错误回喂
            self.usage.retries += 1
            logger.warning("DeepSeek 输出校验失败，重试一次: %s", str(e)[:200])
            text2 = self._call(system, [
                {"role": "user", "content": user},
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"你的 JSON 不符合 schema，错误：{e}\n请重新输出完整、合规的 JSON。"},
            ])
            return model_cls.model_validate_json(text2)

    def score_statement(self, doc: dict, diff_entries: list[dict]) -> dict:
        scores = self._parse(self.system_statement,
                             prompts.build_statement_user(doc, diff_entries),
                             StatementScores)
        return self._finalize(doc, scores,
                              schema.merge_diff_labels(diff_entries, scores.diff_labels))

    def score_minutes(self, doc: dict) -> dict:
        scores = self._parse(self.system_minutes,
                             prompts.build_minutes_user(doc), MinutesScores)
        return self._finalize(doc, scores, None)

    def _finalize(self, doc: dict, scores, diffs) -> dict:
        quote_bad = schema.validate_quotes(scores.dimensions, doc["text"])
        score_bad = schema.validate_scores(scores)
        return schema.build_record(
            doc, scores, diffs_vs_previous=diffs, model=self.model,
            prompt_version=prompts.PROMPT_VERSION,
            quote_violations=quote_bad, score_violations=score_bad,
        )
