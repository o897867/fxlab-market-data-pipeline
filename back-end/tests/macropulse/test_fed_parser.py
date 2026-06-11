"""Fed 解析、分类、列表的单测（hermetic，不联网）。"""

import pytest

from macropulse.sources import fed
from macropulse.models import DOC_STATEMENT, DOC_MINUTES, DOC_OTHER, FED

pytestmark = pytest.mark.unit

# 仿真一页 FOMC 声明，结构对齐真实页面：div#article + 样板段 + 正文段
STATEMENT_HTML = """
<html><head>
<meta property="og:title" content="Federal Reserve issues FOMC statement">
<title>Federal Reserve Board - Federal Reserve issues FOMC statement</title>
</head><body>
<div id="article">
  <p>April 29, 2026</p>
  <p>For release at 2:00 p.m. EDT Share</p>
  <p>Recent indicators suggest that economic activity has been expanding at a solid pace.</p>
  <p>The Committee decided to maintain the target range for the federal funds rate at 4-1/4 to 4-1/2 percent.</p>
  <p>  </p>
  <p>Implementation Note issued April 29, 2026</p>
</div>
</body></html>
"""

# 仿真纪要正文页（注意：URL 是 fomcminutes 形态，无 monetary slug）
MINUTES_HTML = """
<html><head>
<meta property="og:title" content="Minutes of the Federal Open Market Committee, March 17-18, 2026">
</head><body><div id="article">
  <p>A meeting of the Federal Open Market Committee was held in the offices of the Board.</p>
  <p>Developments in Financial Markets and Open Market Operations</p>
</div></body></html>
"""

STMT_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260429a.htm"
MIN_URL = "https://www.federalreserve.gov/monetarypolicy/fomcminutes20260318.htm"


def test_ymd():
    assert fed._ymd("20260429") == "2026-04-29"


@pytest.mark.parametrize("title,expected", [
    ("Federal Reserve issues FOMC statement", DOC_STATEMENT),
    ("Minutes of the Federal Open Market Committee, March 17-18, 2026", DOC_MINUTES),
    ("Minutes of the Board's discount rate meetings", DOC_OTHER),
])
def test_classify(title, expected):
    assert fed._classify(title) == expected


def test_parse_statement_basic():
    # 列表阶段提供 doc_type/meeting_date
    doc = fed.parse(STATEMENT_HTML, STMT_URL, doc_type=DOC_STATEMENT, meeting_date="2026-04-29")
    assert doc.central_bank == FED
    assert doc.doc_type == DOC_STATEMENT
    assert doc.document_id == "fed_statement_2026-04-29"
    assert doc.title == "Federal Reserve issues FOMC statement"
    assert doc.content_hash.startswith("sha256:")


def test_parse_infers_when_hints_absent():
    # 不给 doc_type/meeting_date 时，从 URL + 标题推断
    doc = fed.parse(STATEMENT_HTML, STMT_URL)
    assert doc.doc_type == DOC_STATEMENT
    assert doc.meeting_date == "2026-04-29"


def test_parse_filters_boilerplate():
    doc = fed.parse(STATEMENT_HTML, STMT_URL, doc_type=DOC_STATEMENT, meeting_date="2026-04-29")
    assert not any(p.startswith("For release") for p in doc.paragraphs)
    assert "" not in doc.paragraphs
    assert any("target range for the federal funds rate" in p for p in doc.paragraphs)
    assert doc.paragraphs[0] == "April 29, 2026"
    assert doc.paragraphs[-1].startswith("Implementation Note")


def test_parse_minutes_body():
    doc = fed.parse(MINUTES_HTML, MIN_URL, doc_type=DOC_MINUTES, meeting_date="2026-03-18")
    assert doc.doc_type == DOC_MINUTES
    assert doc.document_id == "fed_minutes_2026-03-18"
    assert "Federal Open Market Committee was held" in doc.text


def test_content_hash_changes_with_text():
    a = fed.parse(STATEMENT_HTML, STMT_URL, doc_type=DOC_STATEMENT, meeting_date="2026-04-29")
    b = fed.parse(STATEMENT_HTML.replace("solid pace", "modest pace"), STMT_URL,
                  doc_type=DOC_STATEMENT, meeting_date="2026-04-29")
    assert a.content_hash != b.content_hash


# 仿真日历页：含一对声明 + 纪要链接，验证 list_meetings 的正则与配对
CALENDAR_HTML = """
<html><body>
<a href="/newsevents/pressreleases/monetary20260318a.htm">Statement</a>
<a href="/monetarypolicy/fomcminutes20260318.htm">Minutes</a>
<a href="/newsevents/pressreleases/monetary20260429a.htm">Statement</a>
<a href="/newsevents/pressreleases/monetary20260318a.htm">dup</a>
</body></html>
"""


def test_get_fixes_mojibake_encoding(monkeypatch):
    """Fed 页头不声明 charset → requests 误判 ISO-8859-1，_get 须纠正为真实 UTF-8。"""
    import requests as _rq

    class FakeResp:
        def __init__(self):
            self.content = "April 28–29, 2026".encode("utf-8")  # 含 en-dash
            self.encoding = "ISO-8859-1"          # 模拟 requests 的错误默认
            self.apparent_encoding = "utf-8"       # chardet 的正确探测
        def raise_for_status(self):
            pass
        @property
        def text(self):
            return self.content.decode(self.encoding)

    monkeypatch.setattr(_rq, "get", lambda *a, **k: FakeResp())
    monkeypatch.setattr(fed, "_last_request_ts", 0.0)
    monkeypatch.setattr(fed.config, "REQUEST_DELAY", 0.0)
    resp = fed._get("https://x")
    assert resp.encoding == "utf-8"
    assert "28–29" in resp.text  # 正确 en-dash，而非 28â29


def test_list_meetings_parsing(monkeypatch):
    class FakeResp:
        text = CALENDAR_HTML
    monkeypatch.setattr(fed, "_get", lambda url: FakeResp())
    items = fed.list_meetings()
    # 去重后：2 声明 + 1 纪要 = 3
    assert len(items) == 3
    statements = [i for i in items if i["doc_type"] == DOC_STATEMENT]
    minutes = [i for i in items if i["doc_type"] == DOC_MINUTES]
    assert len(statements) == 2 and len(minutes) == 1
    assert minutes[0]["url"].endswith("/monetarypolicy/fomcminutes20260318.htm")
    assert items[0]["meeting_date"] == "2026-03-18"  # 升序
