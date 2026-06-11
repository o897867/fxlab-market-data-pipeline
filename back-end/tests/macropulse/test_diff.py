"""确定性 Diff 引擎单测（hermetic）。"""

import pytest

from macropulse import diff
from macropulse.diff import (
    diff_statements, word_changes, render_text,
    UNCHANGED, MODIFIED, ADDED, REMOVED,
)

pytestmark = pytest.mark.unit


def _stmt(date, paras):
    return {"document_id": f"fed_statement_{date}", "meeting_date": date, "paragraphs": paras}


def test_word_changes_replace():
    ch = word_changes("rate at 4 percent", "rate at 3 percent")
    assert len(ch) == 1 and ch[0].op == "replace"
    assert ch[0].old == "4" and ch[0].new == "3"


def test_word_changes_insert_delete():
    assert any(c.op == "insert" for c in word_changes("a b", "a x b"))
    assert any(c.op == "delete" for c in word_changes("a x b", "a b"))


def test_identical_all_unchanged():
    p = ["April 29, 2026", "Activity expanding at a solid pace.", "Voting for: Powell."]
    d = diff_statements(_stmt("2026-04-29", p), _stmt("2026-04-29", p))
    assert d.summary[UNCHANGED] == 3
    assert d.summary[MODIFIED] == d.summary[ADDED] == d.summary[REMOVED] == 0


def test_modified_paragraph_detected():
    old = _stmt("2026-03-18", [
        "March 18, 2026",
        "The Committee decided to maintain the target range at 4-1/4 to 4-1/2 percent.",
    ])
    new = _stmt("2026-04-29", [
        "April 29, 2026",
        "The Committee decided to maintain the target range at 3-1/2 to 3-3/4 percent.",
    ])
    d = diff_statements(old, new)
    # 利率段是长文本、措辞高度相似 → 应判 modified，并标出 4-1/4→3-1/2 的替换
    mods = [p for p in d.paragraphs if p.status == MODIFIED]
    rate = [p for p in mods if "target range" in p.new_text]
    assert len(rate) == 1
    assert any("3-1/2" in c.new for c in rate[0].word_changes)
    # 日期行只共享 "2026"，相似度低于对齐阈值 → 拆成删+增（而非 modified），符合预期
    assert d.summary[REMOVED] >= 1 and d.summary[ADDED] >= 1


def test_added_and_removed_paragraph():
    old = _stmt("2026-03-18", ["A unchanged para about the economy here.",
                               "Old paragraph that will be dropped entirely zzz."])
    new = _stmt("2026-04-29", ["A unchanged para about the economy here.",
                               "Totally fresh paragraph with new content qqq."])
    d = diff_statements(old, new)
    # 第一段未变；第二段措辞差异极大 → 删 + 增
    assert d.summary[UNCHANGED] == 1
    assert d.summary[REMOVED] >= 1 and d.summary[ADDED] >= 1


def test_alignment_handles_inserted_paragraph():
    old = _stmt("a", ["para one stable text", "para three stable text"])
    new = _stmt("b", ["para one stable text", "brand new middle insertion xyz", "para three stable text"])
    d = diff_statements(old, new)
    assert d.summary[UNCHANGED] == 2   # 首尾对齐不变
    assert d.summary[ADDED] == 1       # 中间新增


def test_render_contains_redline_markers():
    old = _stmt("2026-03-18", ["rate at 4 percent today"])
    new = _stmt("2026-04-29", ["rate at 3 percent today"])
    out = render_text(diff_statements(old, new))
    assert "[-4-]" in out and "{+3+}" in out


def test_to_dict_serializable():
    import json
    d = diff_statements(_stmt("a", ["x y z"]), _stmt("b", ["x q z"]))
    json.dumps(d.to_dict())  # 不抛即可
