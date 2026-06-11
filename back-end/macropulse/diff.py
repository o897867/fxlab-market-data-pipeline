"""确定性 Diff 引擎 —— 相邻两期 FOMC 声明的段落对齐 + 词级红线。

这是「AI 红线对比」的骨架，**不依赖 LLM**：纯文本对齐，结果可肉眼复核。
方向（hawkish/dovish）与强度（magnitude）标注是后续 LLM 抽取层的事，本引擎
只产出交接文档 `diffs_vs_previous` schema 里的 section / old / new 部分。

段落对齐用 Needleman-Wunsch（声明段落少、结构平行，DP 稳且开销可忽略）：
  - sim ≥ 0.98 → unchanged
  - 0.5 ≤ sim < 0.98 → modified（再做词级 diff）
  - sim < 0.5 的对角匹配 → 拆成 removed + added
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher

UNCHANGED, MODIFIED, ADDED, REMOVED = "unchanged", "modified", "added", "removed"

# 相似度阈值
_SAME = 0.98     # 视为未变
_ALIGN = 0.50    # 低于此则不认为是同一段（拆成删+增）


@dataclass
class WordChange:
    op: str          # replace | insert | delete
    old: str         # 被删 / 被替换掉的原词串（insert 时为空）
    new: str         # 新增 / 替换为的词串（delete 时为空）


@dataclass
class ParaDiff:
    status: str                  # unchanged | modified | added | removed
    old_index: int | None
    new_index: int | None
    old_text: str
    new_text: str
    similarity: float
    word_changes: list[WordChange] = field(default_factory=list)


@dataclass
class StatementDiff:
    from_id: str
    to_id: str
    from_date: str
    to_date: str
    paragraphs: list[ParaDiff]
    summary: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _ratio(a: str, b: str) -> float:
    """词级相似度（按空白切词，避免标点细节主导）。"""
    return SequenceMatcher(None, a.split(), b.split()).ratio()


def word_changes(old_text: str, new_text: str) -> list[WordChange]:
    """两段文本的词级增删替。"""
    a, b = old_text.split(), new_text.split()
    sm = SequenceMatcher(None, a, b)
    out: list[WordChange] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        out.append(WordChange(op=op, old=" ".join(a[i1:i2]), new=" ".join(b[j1:j2])))
    return out


def _align(old: list[str], new: list[str]) -> list[tuple]:
    """Needleman-Wunsch 段落对齐。返回操作序列 [(op, i, j)]，
    op ∈ {match, del, ins}，i/j 为段落下标（del 时 j=None，ins 时 i=None）。"""
    n, m = len(old), len(new)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0]
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + _ratio(old[i - 1], new[j - 1])
            dp[i][j] = max(diag, dp[i - 1][j], dp[i][j - 1])

    # 回溯
    ops: list[tuple] = []
    i, j = n, m
    while i > 0 and j > 0:
        diag = dp[i - 1][j - 1] + _ratio(old[i - 1], new[j - 1])
        if dp[i][j] == diag:
            ops.append(("match", i - 1, j - 1)); i -= 1; j -= 1
        elif dp[i][j] == dp[i - 1][j]:
            ops.append(("del", i - 1, None)); i -= 1
        else:
            ops.append(("ins", None, j - 1)); j -= 1
    while i > 0:
        ops.append(("del", i - 1, None)); i -= 1
    while j > 0:
        ops.append(("ins", None, j - 1)); j -= 1
    ops.reverse()
    return ops


def diff_statements(old: dict, new: dict) -> StatementDiff:
    """对比两期声明（dict 需含 paragraphs / document_id / meeting_date）。"""
    old_p, new_p = old["paragraphs"], new["paragraphs"]
    paras: list[ParaDiff] = []

    for op, i, j in _align(old_p, new_p):
        if op == "match":
            sim = _ratio(old_p[i], new_p[j])
            if sim >= _SAME:
                paras.append(ParaDiff(UNCHANGED, i, j, old_p[i], new_p[j], round(sim, 3)))
            elif sim >= _ALIGN:
                paras.append(ParaDiff(MODIFIED, i, j, old_p[i], new_p[j], round(sim, 3),
                                      word_changes(old_p[i], new_p[j])))
            else:
                # 对齐度太低：判为旧段删除 + 新段新增
                paras.append(ParaDiff(REMOVED, i, None, old_p[i], "", round(sim, 3)))
                paras.append(ParaDiff(ADDED, None, j, "", new_p[j], round(sim, 3)))
        elif op == "del":
            paras.append(ParaDiff(REMOVED, i, None, old_p[i], "", 0.0))
        else:
            paras.append(ParaDiff(ADDED, None, j, "", new_p[j], 0.0))

    summary = {s: sum(1 for p in paras if p.status == s)
               for s in (UNCHANGED, MODIFIED, ADDED, REMOVED)}
    return StatementDiff(
        from_id=old["document_id"], to_id=new["document_id"],
        from_date=old["meeting_date"], to_date=new["meeting_date"],
        paragraphs=paras, summary=summary,
    )


# ------------------------------------------------------------------ 渲染


def _inline_redline(old_text: str, new_text: str) -> str:
    """wdiff 风格内联红线：[-删-]{+增+}。"""
    a, b = old_text.split(), new_text.split()
    sm = SequenceMatcher(None, a, b)
    parts: list[str] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            parts.append(" ".join(a[i1:i2]))
        elif op == "delete":
            parts.append(f"[-{' '.join(a[i1:i2])}-]")
        elif op == "insert":
            parts.append(f"{{+{' '.join(b[j1:j2])}+}}")
        else:  # replace
            parts.append(f"[-{' '.join(a[i1:i2])}-]{{+{' '.join(b[j1:j2])}+}}")
    return " ".join(p for p in parts if p)


def render_text(d: StatementDiff) -> str:
    """人读红线视图（终端 / markdown 皆可）。"""
    L = []
    L.append(f"# 红线对比  {d.from_date}  →  {d.to_date}")
    L.append(f"  {d.from_id}  →  {d.to_id}")
    s = d.summary
    L.append(f"  段落: 未变 {s['unchanged']} | 修改 {s['modified']} | "
             f"新增 {s['added']} | 删除 {s['removed']}")
    L.append("=" * 72)
    for p in d.paragraphs:
        if p.status == UNCHANGED:
            L.append(f"\n= [{p.new_index}] (未变) {p.new_text[:70]}…")
        elif p.status == MODIFIED:
            L.append(f"\n~ [{p.old_index}→{p.new_index}] 修改 (sim={p.similarity}):")
            L.append("  " + _inline_redline(p.old_text, p.new_text))
        elif p.status == ADDED:
            L.append(f"\n+ [新 {p.new_index}] 新增:")
            L.append("  {+ " + p.new_text + " +}")
        else:  # removed
            L.append(f"\n- [旧 {p.old_index}] 删除:")
            L.append("  [- " + p.old_text + " -]")
    return "\n".join(L)
