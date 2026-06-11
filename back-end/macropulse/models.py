"""Raw 层文档模型。

注意：这是 **raw 层** 的结构，只承载抓取到的原始文本与元信息，
不含鹰鸽打分 / diff（那是第二、三周抽取引擎的事，见 CLAUDE 交接文档的
抽取 schema v0.1）。content_hash 用于去重与幂等。
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Optional

# 央行枚举
FED = "FED"
RBA = "RBA"
ECB = "ECB"

# 文档类型枚举（对齐抽取 schema 的 doc_type）
DOC_STATEMENT = "statement"
DOC_MINUTES = "minutes"
DOC_SPEECH = "speech"
DOC_OTHER = "other"  # 例如贴现率会议纪要，抓到但非核心


def content_hash(text: str) -> str:
    """对正文做 sha256，作为去重 / 变更检测的依据。"""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class RawDocument:
    document_id: str            # 如 fed_statement_2026-04-29
    central_bank: str           # FED | RBA | ECB
    doc_type: str               # statement | minutes | speech | other
    title: str
    url: str
    meeting_date: str           # YYYY-MM-DD（从 URL/页面解析）
    retrieved_at: str           # ISO8601 UTC
    text: str                   # 规范化后的全文
    paragraphs: list[str] = field(default_factory=list)
    published_at: Optional[str] = None   # RSS pubDate（若有）
    content_hash: str = ""
    raw_html_key: Optional[str] = None   # 原文 HTML 在 S3 的 key

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = content_hash(self.text)

    def to_dict(self) -> dict:
        return asdict(self)
