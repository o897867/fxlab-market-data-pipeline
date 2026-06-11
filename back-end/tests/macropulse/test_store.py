"""S3 key 约定 + 幂等清单的单测（hermetic，不连 S3）。"""

import pytest

from macropulse.models import RawDocument, content_hash, FED, DOC_STATEMENT
from macropulse.s3_store import Manifest, raw_keys

pytestmark = pytest.mark.unit


def _doc(text="hello world") -> RawDocument:
    return RawDocument(
        document_id="fed_statement_2026-04-29",
        central_bank=FED,
        doc_type=DOC_STATEMENT,
        title="Federal Reserve issues FOMC statement",
        url="https://x/monetary20260429a.htm",
        meeting_date="2026-04-29",
        retrieved_at="2026-04-29T18:05:00+00:00",
        text=text,
        paragraphs=[text],
    )


def test_content_hash_deterministic():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")


def test_raw_keys_partitioning():
    json_key, html_key = raw_keys(_doc())
    assert json_key == "raw/macro/fed/statement/year=2026/fed_statement_2026-04-29.json"
    assert html_key.endswith("fed_statement_2026-04-29.html")


def test_manifest_dedup_unchanged():
    m = Manifest()
    doc = _doc()
    jk, hk = raw_keys(doc)
    assert not m.is_unchanged(doc.document_id, doc.content_hash)  # 初次不存在
    m.record(doc, jk, hk)
    assert m.is_unchanged(doc.document_id, doc.content_hash)      # 记录后命中


def test_manifest_detects_change():
    m = Manifest()
    doc = _doc("old text")
    jk, hk = raw_keys(doc)
    m.record(doc, jk, hk)
    changed = _doc("new text")
    assert not m.is_unchanged(changed.document_id, changed.content_hash)


def test_manifest_roundtrip():
    m = Manifest()
    doc = _doc()
    jk, hk = raw_keys(doc)
    m.record(doc, jk, hk)
    restored = Manifest(m.to_dict())
    assert restored.is_unchanged(doc.document_id, doc.content_hash)
