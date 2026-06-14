"""结构/校准回归检查（纯函数，CI 安全：无 API/S3/网络）。

对 golden 快照里每条记录做不变量校验 + 锚点校准带校验。任何破坏都说明
prompt/schema 改动引入了回归。
"""

from __future__ import annotations

from macropulse.eval.golden import ANCHOR_BANDS

DIMS = ("inflation", "labor", "balance_sheet_qt", "forward_guidance")
DOC_TYPES = ("statement", "minutes")


def check_record(r: dict) -> list[str]:
    """单条记录的不变量。返回问题列表（空=通过）。"""
    problems = []
    if r.get("doc_type") not in DOC_TYPES:
        problems.append(f"doc_type 非法: {r.get('doc_type')}")
    if not isinstance(r.get("overall_score"), int) or not -5 <= r["overall_score"] <= 5:
        problems.append(f"overall_score 越界: {r.get('overall_score')}")
    c = r.get("confidence_overall")
    if not isinstance(c, (int, float)) or not 0.0 <= c <= 1.0:
        problems.append(f"confidence_overall 越界: {c}")
    dims = r.get("dimensions", {})
    for d in DIMS:
        if d not in dims:
            problems.append(f"缺维度: {d}")
            continue
        s = dims[d].get("score")
        if not isinstance(s, int) or not -5 <= s <= 5:
            problems.append(f"{d}.score 越界: {s}")
        dc = dims[d].get("confidence")
        if not isinstance(dc, (int, float)) or not 0.0 <= dc <= 1.0:
            problems.append(f"{d}.confidence 越界: {dc}")
    # 生产基准里不该残留未裁决的硬违规（key_quote 逐字 / 分数范围）
    if r.get("score_violations"):
        problems.append(f"残留 score_violations: {r['score_violations']}")
    return problems


def check_all(golden: dict[str, dict]) -> dict[str, list[str]]:
    """全量记录校验。返回 {document_id: [问题…]}，只含有问题的。"""
    return {did: probs for did, r in golden.items()
            if (probs := check_record(r))}


def check_anchor_bands(golden: dict[str, dict]) -> list[str]:
    """锚点分数必须落在校准带内。返回违规说明列表。"""
    out = []
    for did, (lo, hi) in ANCHOR_BANDS.items():
        if did not in golden:
            out.append(f"{did} 不在 golden 中（锚点缺失）")
            continue
        s = golden[did]["overall_score"]
        if not lo <= s <= hi:
            out.append(f"{did} overall={s} 漂出校准带 [{lo},{hi}]")
    return out


def compare_drift(golden: dict[str, dict], fresh: dict[str, dict],
                  threshold: int = 1) -> list[str]:
    """漂移比对（供 Tier-2 用）：同 document_id 的 overall_score 偏移须 ≤ threshold，
    且方向（鹰/鸽/中性符号）不翻转。返回违规说明。"""
    out = []
    for did, fr in fresh.items():
        if did not in golden:
            continue
        g = golden[did]["overall_score"]
        f = fr["overall_score"]
        if abs(f - g) > threshold:
            out.append(f"{did}: overall {g}→{f} 漂移 {abs(f-g)} > {threshold}")
        if (g > 0) - (g < 0) != (f > 0) - (f < 0):
            out.append(f"{did}: 方向翻转 {g}→{f}")
    return out
