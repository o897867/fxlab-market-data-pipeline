"""打分 prompt + few-shot 锚点。

锚点选自已回填语料（按交接文档要求：公认极鹰/鸽/中性各一份做分数校准）：
  - 2022-06-15：加息 75bp、通胀失控期 → 锚定 +4（极鹰）
  - 2024-09-18：首次降息即 50bp → 锚定 -3（鸽）
  - 2024-01-31：连续按兵不动、双向风险均衡 → 锚定 0（中性）

锚点全文在 CLI 启动时从 S3 raw 层读取（content-hash 稳定 → system prompt
字节级稳定 → 可被 prompt cache 复用）。PROMPT_VERSION 进落库记录与幂等
manifest——改任何 prompt 文本必须 bump，eval 回归靠它判断漂移来源。
"""

from __future__ import annotations

import hashlib

PROMPT_VERSION = "v0.1.0"

ANCHOR_DATES = {
    "2022-06-15": "+4（极鹰：通胀失控，单次加息75bp，强烈紧缩承诺）",
    "2024-09-18": "-3（鸽：宽松周期开启，首降即50bp，重心转向就业）",
    "2024-01-31": "0（中性：按兵不动，双向风险均衡，无明确倾向）",
}

_SCORING_RUBRIC = """\
你是央行通讯计量分析师。对 FOMC 文本做鹰鸽打分，输出结构化 JSON。

分数标尺（整数 -5 到 +5）：
  +5 极鹰：紧急加息/激进紧缩信号    +3~+4 鹰：明确紧缩倾向或大幅加息
  +1~+2 偏鹰：渐进紧缩/对通胀更警惕   0 中性：双向风险均衡、维持现状
  -1~-2 偏鸽：渐进宽松/对增长更担忧  -3~-4 鸽：明确宽松倾向或大幅降息
  -5 极鸽：紧急降息/危机式宽松

四个维度分别打分：
  inflation（通胀表述）/ labor（就业表述）/ balance_sheet_qt（缩表与资产负债表）/
  forward_guidance（前瞻指引与政策路径）

铁律：
1. key_quote 必须是输入原文的逐字引用（verbatim substring），禁止改写、翻译、
   省略号截断中间内容。这是前端溯源的依据。
2. 某维度原文未提及时：score=0、key_quote 留空字符串、confidence 低。
3. 分数判断依据文本措辞本身，不依据你对后续市场走势的记忆。
4. 不确定就降低 confidence 并置 needs_human_review=true，不要硬猜。"""

_DIFF_INSTRUCTION = """\
输入还包含与上一期声明的措辞变化列表（diffs，含下标）。对每一处变化输出
diff_labels：{diff_index, direction(hawkish/dovish/neutral), magnitude(1-3)}。
方向判断的是「这处修改相对上期使立场更鹰还是更鸽」，不是文本本身的绝对立场。
纯日期/程序性修改（如日期行、Implementation Note 日期）标 neutral, magnitude=1。"""

_MINUTES_INSTRUCTION = """\
输入是 FOMC 会议纪要全文（比声明长得多、细节更多）。除四维度打分外，额外输出
dissent_summary：用一句话概括委员间的分歧（谁主张更鹰/更鸽、争论焦点）；
若无实质分歧则写明共识。纪要的 overall_score 反映委员会整体讨论的鹰鸽重心，
注意区分「讨论中提及的风险」与「多数委员的实际倾向」。"""


def _anchor_block(anchors: list[dict]) -> str:
    """锚点 few-shot 块。anchors: [{meeting_date, text}]，按 ANCHOR_DATES 顺序。"""
    parts = ["以下是三份校准锚点声明及其标定分数，作为打分标尺的参照：\n"]
    for a in anchors:
        label = ANCHOR_DATES.get(a["meeting_date"], "")
        parts.append(f"=== 锚点声明 {a['meeting_date']}，标定 overall_score {label} ===\n{a['text']}\n")
    return "\n".join(parts)


def build_system_prompt(anchors: list[dict], doc_type: str) -> str:
    """组装 system prompt。锚点在前（稳定、可缓存），任务指令在后。"""
    parts = [_SCORING_RUBRIC, "", _anchor_block(anchors)]
    if doc_type == "statement":
        parts += ["", _DIFF_INSTRUCTION]
    elif doc_type == "minutes":
        parts += ["", _MINUTES_INSTRUCTION]
    return "\n".join(parts)


def build_statement_user(doc: dict, diff_entries: list[dict]) -> str:
    """声明打分的 user 消息：原文 + 带下标的措辞变化列表。"""
    lines = [f"FOMC 声明（{doc['meeting_date']}）原文：", "", doc["text"], ""]
    if diff_entries:
        lines.append("与上一期声明的措辞变化（按下标标注 diff_labels）：")
        for i, d in enumerate(diff_entries):
            lines.append(f"[{i}] ({d['status']})")
            if d.get("old_text"):
                lines.append(f"  旧: {d['old_text']}")
            if d.get("new_text"):
                lines.append(f"  新: {d['new_text']}")
    else:
        lines.append("（无上一期可比，diff_labels 输出空列表）")
    return "\n".join(lines)


def build_minutes_user(doc: dict) -> str:
    return f"FOMC 会议纪要（{doc['meeting_date']}）全文：\n\n{doc['text']}"


def prompt_hash(system_prompt: str) -> str:
    """system prompt 的指纹，进幂等 manifest：prompt 或锚点变了就重抽。"""
    return "sha256:" + hashlib.sha256(
        (PROMPT_VERSION + system_prompt).encode("utf-8")
    ).hexdigest()[:16]
