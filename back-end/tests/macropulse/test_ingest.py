"""Ingest 编排逻辑单测：类型过滤 + 幂等跳过（hermetic，不联网/不连 S3）。"""

import pytest

from macropulse import ingest
from macropulse.models import RawDocument, FED, DOC_STATEMENT, DOC_MINUTES, DOC_OTHER
from macropulse.s3_store import Manifest, raw_keys
from macropulse.sources import fed

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("doc_type,statements_only,expected", [
    (DOC_STATEMENT, False, True),
    (DOC_MINUTES, False, True),
    (DOC_OTHER, False, False),     # other 永远丢弃
    (DOC_STATEMENT, True, True),
    (DOC_MINUTES, True, False),    # statements_only 时纪要也丢
    (DOC_OTHER, True, False),
])
def test_wanted(doc_type, statements_only, expected):
    assert ingest._wanted(doc_type, statements_only) is expected


def _doc(doc_type=DOC_STATEMENT, date="2026-04-29", text="body text"):
    return RawDocument(
        document_id=f"fed_{doc_type}_{date}", central_bank=FED, doc_type=doc_type,
        title="t", url="https://x/monetary20260429a.htm", meeting_date=date,
        retrieved_at="2026-04-29T18:00:00+00:00", text=text, paragraphs=[text],
    )


def test_filtered_item_not_fetched(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(fed, "fetch", lambda item: (_ for _ in ()).throw(AssertionError("不该抓")))
    item = {"url": "u", "doc_type": DOC_OTHER, "meeting_date": "2026-04-29"}
    status = ingest._ingest_one(item, None, Manifest(), False, dry_run=True, skip_known=True)
    assert status == "filtered"


def test_skip_known_avoids_fetch(monkeypatch):
    # manifest 已有该 document_id，incremental 应免抓跳过
    doc = _doc()
    jk, hk = raw_keys(doc)
    m = Manifest()
    m.record(doc, jk, hk)
    monkeypatch.setattr(fed, "fetch", lambda item: pytest.fail("skip_known 时不应抓取"))
    item = {"url": "u", "doc_type": DOC_STATEMENT, "meeting_date": "2026-04-29"}
    assert ingest._ingest_one(item, None, m, False, dry_run=True, skip_known=True) == "unchanged"


def test_new_item_written_in_dry_run(monkeypatch):
    doc = _doc()
    monkeypatch.setattr(fed, "fetch", lambda item: (doc, "<html/>"))
    item = {"url": "u", "doc_type": DOC_STATEMENT, "meeting_date": "2026-04-29"}
    status = ingest._ingest_one(item, None, Manifest(), False, dry_run=True, skip_known=False)
    assert status == "written"


def test_backfill_rehash_skips_unchanged(monkeypatch):
    # backfill（skip_known=False）会抓取，但 content_hash 未变则判 unchanged
    doc = _doc()
    jk, hk = raw_keys(doc)
    m = Manifest()
    m.record(doc, jk, hk)
    monkeypatch.setattr(fed, "fetch", lambda item: (doc, "<html/>"))
    item = {"url": "u", "doc_type": DOC_STATEMENT, "meeting_date": "2026-04-29"}
    assert ingest._ingest_one(item, None, m, False, dry_run=True, skip_known=False) == "unchanged"
