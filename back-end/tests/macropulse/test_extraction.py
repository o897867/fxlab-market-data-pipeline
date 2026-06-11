"""LLM 抽取层单测（hermetic：mock client，不调 API / 不连 S3）。"""

import json
import pytest

from macropulse.extraction import prompts, schema
from macropulse.extraction.schema import (
    StatementScores, MinutesScores, DimensionScore, Dimensions, DiffLabel,
    validate_quotes, validate_scores, merge_diff_labels, build_record,
)
from macropulse.extraction.extractor import Extractor, UsageTally

pytestmark = pytest.mark.unit

ANCHORS = [
    {"meeting_date": d, "text": f"anchor text for {d}"}
    for d in ("2022-06-15", "2024-09-18", "2024-01-31")
]

DOC = {
    "document_id": "fed_statement_2026-04-29",
    "central_bank": "FED",
    "doc_type": "statement",
    "meeting_date": "2026-04-29",
    "text": "Inflation is elevated. Job gains have remained low. The Committee decided to maintain the target range.",
}


def _dim(quote="Inflation is elevated.", score=2, conf=0.9):
    return DimensionScore(score=score, key_quote=quote, confidence=conf)


def _scores(**kw):
    defaults = dict(
        overall_score=2,
        dimensions=Dimensions(
            inflation=_dim(),
            labor=_dim("Job gains have remained low.", -1),
            balance_sheet_qt=_dim("", 0, 0.2),
            forward_guidance=_dim("The Committee decided to maintain the target range.", 0),
        ),
        diff_labels=[DiffLabel(diff_index=0, direction="hawkish", magnitude=2)],
        confidence_overall=0.85,
        needs_human_review=False,
    )
    defaults.update(kw)
    return StatementScores(**defaults)


# ---------------------------------------------------------------- prompts


def test_system_prompt_contains_anchors_and_is_deterministic():
    a = prompts.build_system_prompt(ANCHORS, "statement")
    b = prompts.build_system_prompt(ANCHORS, "statement")
    assert a == b  # 字节级稳定 → 可缓存
    for d in prompts.ANCHOR_DATES:
        assert d in a
    assert "diff_labels" in a  # statement 变体含 diff 指令
    m = prompts.build_system_prompt(ANCHORS, "minutes")
    assert "dissent_summary" in m and "diff_labels" not in m


def test_prompt_hash_changes_with_version(monkeypatch):
    s = prompts.build_system_prompt(ANCHORS, "statement")
    h1 = prompts.prompt_hash(s)
    monkeypatch.setattr(prompts, "PROMPT_VERSION", "v9.9.9")
    assert prompts.prompt_hash(s) != h1


def test_statement_user_includes_indexed_diffs():
    diffs = [{"status": "modified", "old_text": "old words", "new_text": "new words"}]
    u = prompts.build_statement_user(DOC, diffs)
    assert "[0]" in u and "old words" in u and "new words" in u
    u2 = prompts.build_statement_user(DOC, [])
    assert "无上一期可比" in u2


# ---------------------------------------------------------------- schema 校验


def test_validate_quotes_catches_non_verbatim():
    dims = _scores().dimensions
    assert validate_quotes(dims, DOC["text"]) == []
    bad = _scores(dimensions=Dimensions(
        inflation=_dim("通胀压力上升（改写的）"), labor=_dim("Job gains have remained low.", -1),
        balance_sheet_qt=_dim("", 0), forward_guidance=_dim("", 0),
    )).dimensions
    assert validate_quotes(bad, DOC["text"]) == ["inflation"]


def test_validate_quotes_empty_quote_ok():
    dims = Dimensions(inflation=_dim(""), labor=_dim(""),
                      balance_sheet_qt=_dim(""), forward_guidance=_dim(""))
    assert validate_quotes(dims, DOC["text"]) == []


def test_validate_scores_out_of_range():
    assert validate_scores(_scores()) == []
    bad = _scores(overall_score=9)
    assert any("overall_score" in p for p in validate_scores(bad))
    bad2 = _scores(confidence_overall=1.5)
    assert any("confidence_overall" in p for p in validate_scores(bad2))


def test_merge_diff_labels():
    diffs = [
        {"status": "modified", "old_index": 1, "new_index": 1,
         "old_text": "a", "new_text": "b"},
        {"status": "added", "old_index": None, "new_index": 2,
         "old_text": "", "new_text": "c"},
    ]
    labels = [DiffLabel(diff_index=0, direction="hawkish", magnitude=3),
              DiffLabel(diff_index=99, direction="dovish", magnitude=1)]  # 越界丢弃
    merged = merge_diff_labels(diffs, labels)
    assert merged[0]["direction"] == "hawkish" and merged[0]["magnitude"] == 3
    assert merged[0]["old"] == "a" and merged[0]["new"] == "b"
    assert merged[1]["direction"] == "neutral"  # 未标注 → neutral 兜底
    assert merged[1]["section"] == "para_2"


def test_build_record_flags_review_on_violations():
    r = build_record(DOC, _scores(), quote_violations=["inflation"])
    assert r["needs_human_review"] is True
    r2 = build_record(DOC, _scores())
    assert r2["needs_human_review"] is False
    assert r2["document_id"] == DOC["document_id"]
    json.dumps(r2)  # 可序列化


# ---------------------------------------------------------------- extractor（mock client）


class _FakeUsage:
    input_tokens = 5000
    output_tokens = 800
    cache_read_input_tokens = 4000
    cache_creation_input_tokens = 0


class _FakeResp:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.usage = _FakeUsage()


class _FakeMessages:
    def __init__(self, parsed):
        self._parsed = parsed
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp(self._parsed)


class _FakeClient:
    def __init__(self, parsed):
        self.messages = _FakeMessages(parsed)


def test_extractor_statement_happy_path():
    ex = Extractor(ANCHORS, client=_FakeClient(_scores()), model="claude-opus-4-8")
    diffs = [{"status": "modified", "old_index": 1, "new_index": 1,
              "old_text": "x", "new_text": "y"}]
    record = ex.score_statement(DOC, diffs)
    assert record["overall_score"] == 2
    assert record["diffs_vs_previous"][0]["direction"] == "hawkish"
    assert record["needs_human_review"] is False
    assert record["model"] == "claude-opus-4-8"
    assert ex.usage.calls == 1 and ex.usage.input_tokens == 5000
    # 请求参数合规：缓存断点 + adaptive thinking
    kw = ex.client.messages.last_kwargs
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_extractor_flags_bad_quote():
    bad = _scores(dimensions=Dimensions(
        inflation=_dim("NOT IN SOURCE TEXT"), labor=_dim(""),
        balance_sheet_qt=_dim(""), forward_guidance=_dim(""),
    ))
    ex = Extractor(ANCHORS, client=_FakeClient(bad))
    record = ex.score_statement(DOC, [])
    assert record["needs_human_review"] is True
    assert record["quote_violations"] == ["inflation"]


def test_extractor_minutes_includes_dissent():
    parsed = MinutesScores(
        overall_score=-1, dimensions=_scores().dimensions,
        dissent_summary="两位委员主张更快降息", confidence_overall=0.8,
        needs_human_review=False,
    )
    ex = Extractor(ANCHORS, client=_FakeClient(parsed))
    record = ex.score_minutes({**DOC, "doc_type": "minutes",
                               "document_id": "fed_minutes_2026-04-29"})
    assert record["dissent_summary"] == "两位委员主张更快降息"
    assert record["diffs_vs_previous"] == []


def test_usage_tally_cost():
    t = UsageTally()
    t.add(_FakeUsage())
    assert t.calls == 1
    # 5000/1M*5 + 800/1M*25 + 4000/1M*0.5 = 0.025+0.02+0.002
    assert abs(t.cost_usd() - 0.047) < 1e-6
    assert "$" in t.report()
