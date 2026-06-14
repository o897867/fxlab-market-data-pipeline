"""Tier-2 漂移测试（gated：真实调 Claude API，默认跳过）。

只在 MACRO_RUN_LLM_EVAL=1 时运行。重打校准锚点，与 golden 比对 overall_score
漂移须 ≤ 阈值且方向不翻转——这是「改 prompt 后历史分数漂移在阈值内」的回归。

  MACRO_RUN_LLM_EVAL=1 pytest tests/macropulse/test_eval_drift.py -m llm

CI 默认不跑（无 key、有成本）；可在定时 workflow 或本地改 prompt 后手动跑。
"""

import os
import pytest

pytestmark = [pytest.mark.llm, pytest.mark.macro]

_GATE = os.getenv("MACRO_RUN_LLM_EVAL") == "1"
pytestmark.append(
    pytest.mark.skipif(not _GATE, reason="设 MACRO_RUN_LLM_EVAL=1 才跑真实 LLM 漂移测试"))


def test_anchor_drift_within_threshold():
    from dotenv import load_dotenv
    load_dotenv()
    from macropulse.s3_store import S3RawStore
    from macropulse.extraction.cli import _index, _load_anchors, _diff_entries, _prev_regular, _is_regular
    from macropulse.extraction.extractor import Extractor
    from macropulse.eval.golden import load_golden, ANCHOR_BANDS
    from macropulse.eval import regression

    golden = load_golden()
    store = S3RawStore()
    stmt_idx = _index(store, "statement")
    anchors = _load_anchors(store, stmt_idx)
    ex = Extractor(anchors)

    fresh = {}
    for date in (d.replace("fed_statement_", "") for d in ANCHOR_BANDS):
        doc = store.load_json(stmt_idx[date])
        prev = _prev_regular(stmt_idx, store, date, {}) if _is_regular(doc) else None
        rec = ex.score_statement(doc, _diff_entries(prev, doc))
        fresh[rec["document_id"]] = rec

    drift = regression.compare_drift(golden, fresh, threshold=1)
    bands = regression.check_anchor_bands(fresh)
    assert not drift, f"锚点漂移超阈值: {drift}"
    assert not bands, f"重打后锚点漂出校准带: {bands}"
