"""Federal Reserve 抓取源。

数据源：FOMC 日历页 fomccalendars.htm —— 单一可靠来源，同时列出：
  - 声明 press 链接： /newsevents/pressreleases/monetaryYYYYMMDDa.htm
  - 纪要正文链接：   /monetarypolicy/fomcminutesYYYYMMDD.htm   （完整正文，~4 万字）
两者 URL 里的 YYYYMMDD 都是 FOMC 会议（结束）日，天然按会议配对。

注意：声明的 press 页就是声明本身；但「已发布纪要」的 press release
（monetary...a.htm）只是一段公告，正文在 fomcminutes 页 —— 必须抓后者。
fomccalendars.htm 覆盖近 ~5 年，满足第一期「近三年」回填。更早历史需另接
fomchistorical 页（TODO）。
"""

from __future__ import annotations

import re
import time
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from macropulse import config
from macropulse.models import (
    RawDocument,
    FED,
    DOC_STATEMENT,
    DOC_MINUTES,
    DOC_OTHER,
)

logger = logging.getLogger(__name__)

BASE = "https://www.federalreserve.gov"
CALENDAR_URL = f"{BASE}/monetarypolicy/fomccalendars.htm"

# 声明 press 链接 / 纪要正文链接
_STMT_RE = re.compile(r"/newsevents/pressreleases/(monetary(\d{8})a)\.htm")
_MIN_RE = re.compile(r"/monetarypolicy/(fomcminutes(\d{8}))\.htm")

_last_request_ts = 0.0


def _get(url: str) -> requests.Response:
    """带 UA、超时、限速的 GET。"""
    global _last_request_ts
    wait = config.REQUEST_DELAY - (time.monotonic() - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(
        url,
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT,
    )
    _last_request_ts = time.monotonic()
    resp.raise_for_status()
    # Fed 页面 HTTP 头不声明 charset，requests 默认按 ISO-8859-1 解会把 UTF-8 的
    # en-dash（April 28–29）等字符变乱码。用 chardet 探测到的真实编码（UTF-8）。
    if resp.encoding and resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = resp.apparent_encoding
    return resp


def _ymd(ymd: str) -> str:
    """20260429 -> 2026-04-29"""
    return datetime.strptime(ymd, "%Y%m%d").date().isoformat()


def _doc_id(doc_type: str, meeting_date: str) -> str:
    return f"fed_{doc_type}_{meeting_date}"


def _classify(title: str) -> str:
    """按主标题判断文档类型（仅在列表未提供 doc_type 时兜底）。"""
    t = title.lower()
    if "fomc statement" in t or "issues fomc statement" in t:
        return DOC_STATEMENT
    if "minutes of the federal open market committee" in t:
        return DOC_MINUTES
    return DOC_OTHER


# ---------------------------------------------------------------- 列表


def list_meetings() -> list[dict]:
    """从 FOMC 日历页列出全部声明与纪要正文。

    返回 [{url, doc_type, meeting_date}]，按会议日期升序、(类型,日期) 去重。
    backfill 与 incremental 共用此源；incremental 靠 manifest 跳过已抓的。
    """
    resp = _get(CALENDAR_URL)
    items: dict[tuple, dict] = {}

    for full, ymd in _STMT_RE.findall(resp.text):
        d = _ymd(ymd)
        items[(DOC_STATEMENT, d)] = {
            "url": f"{BASE}/newsevents/pressreleases/{full}.htm",
            "doc_type": DOC_STATEMENT,
            "meeting_date": d,
        }
    for full, ymd in _MIN_RE.findall(resp.text):
        d = _ymd(ymd)
        items[(DOC_MINUTES, d)] = {
            "url": f"{BASE}/monetarypolicy/{full}.htm",
            "doc_type": DOC_MINUTES,
            "meeting_date": d,
        }

    return sorted(items.values(), key=lambda x: (x["meeting_date"], x["doc_type"]))


# ---------------------------------------------------------------- 解析


# 抓取页里需要剔除的样板段落
_BOILERPLATE_PREFIXES = ("For release at", "For immediate release", "Last Update:", "Share")


def parse(
    html: str,
    url: str,
    doc_type: str = None,
    meeting_date: str = None,
    published_at: str = None,
) -> RawDocument:
    """把一页声明 / 纪要正文 HTML 解析为 RawDocument。

    doc_type、meeting_date 若由列表阶段提供则直接采用；否则从 URL / 标题推断
    （供单测与 RSS 兜底）。两类页面正文均在 div#article 内。
    """
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", attrs={"property": "og:title"})
    title = (og["content"].strip() if og and og.get("content") else "")
    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    body = soup.find("div", id="article") or soup
    paragraphs = []
    for p in body.find_all("p"):
        txt = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
        if not txt:
            continue
        if any(txt.startswith(pre) for pre in _BOILERPLATE_PREFIXES):
            continue
        paragraphs.append(txt)
    text = "\n\n".join(paragraphs)

    if meeting_date is None:
        m = re.search(r"(\d{8})", url)
        meeting_date = _ymd(m.group(1)) if m else ""
    if doc_type is None:
        doc_type = _classify(title)

    return RawDocument(
        document_id=_doc_id(doc_type, meeting_date),
        central_bank=FED,
        doc_type=doc_type,
        title=title,
        url=url,
        meeting_date=meeting_date,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        text=text,
        paragraphs=paragraphs,
        published_at=published_at,
    )


def fetch(item: dict) -> tuple[RawDocument, str]:
    """抓取列表项（{url, doc_type, meeting_date}），返回 (RawDocument, 原始HTML)。"""
    resp = _get(item["url"])
    doc = parse(
        resp.text,
        item["url"],
        doc_type=item.get("doc_type"),
        meeting_date=item.get("meeting_date"),
        published_at=item.get("published_at"),
    )
    return doc, resp.text
