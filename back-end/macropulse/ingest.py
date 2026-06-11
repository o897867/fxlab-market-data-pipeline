"""Ingestion 编排。

可两种方式运行：
  - 本地回填： python -m macropulse.ingest backfill [--statements-only] [--dry-run]
  - 增量：     python -m macropulse.ingest incremental [--dry-run]
Lambda 入口（lambda/macropulse/handler.py）调用 run_incremental()。

数据源统一为 FOMC 日历页（见 sources/fed.py）。两条路径的区别只在去重策略：
  - backfill   ：抓取每篇、按 content_hash 与 manifest 比对（能捕捉勘误重抓）
  - incremental：document_id 已在 manifest 即跳过、不再抓取（声明/纪要发布后不变）

幂等：manifest 记录 document_id -> content_hash。--dry-run 只抓取+解析，不写 S3。
"""

from __future__ import annotations

import sys
import logging
import argparse

from macropulse import config
from macropulse.models import RawDocument, DOC_STATEMENT, DOC_OTHER
from macropulse.sources import fed
from macropulse.s3_store import S3RawStore, Manifest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("macropulse.ingest")


def _candidate_id(item: dict) -> str:
    return f"fed_{item['doc_type']}_{item['meeting_date']}"


def _wanted(doc_type: str, statements_only: bool) -> bool:
    """始终丢弃 other（贴现率纪要等）；statements_only 时进一步只留声明。"""
    if doc_type == DOC_OTHER:
        return False
    return doc_type == DOC_STATEMENT if statements_only else True


def _ingest_one(
    item: dict,
    store: S3RawStore | None,
    manifest: Manifest,
    statements_only: bool,
    dry_run: bool,
    skip_known: bool,
) -> str:
    """处理一个列表项。返回 written|filtered|unchanged|error。"""
    if not _wanted(item["doc_type"], statements_only):
        return "filtered"

    # incremental：document_id 已在清单则免抓直接跳过（发布后不变）
    if skip_known and item["doc_type"] != DOC_OTHER:
        cid = _candidate_id(item)
        if cid in manifest.documents:
            return "unchanged"

    try:
        doc, html = fed.fetch(item)
    except Exception as e:  # noqa: BLE001 — 单篇失败不中断整批
        logger.warning("抓取失败 %s: %s", item["url"], e)
        return "error"

    if manifest.is_unchanged(doc.document_id, doc.content_hash):
        logger.info("未变化，跳过 %s", doc.document_id)
        return "unchanged"

    logger.info("入库 %s (%s, %d 段, %d 字)",
                doc.document_id, doc.doc_type, len(doc.paragraphs), len(doc.text))
    if dry_run:
        _preview(doc)
        return "written"

    json_key, html_key = store.put_document(doc, html)
    manifest.record(doc, json_key, html_key)
    return "written"


def _preview(doc: RawDocument) -> None:
    head = doc.text[:220].replace("\n", " ")
    logger.info("    %s | %s | hash=%s", doc.title[:60], doc.meeting_date, doc.content_hash[:18])
    logger.info("    %s…", head)


def _run(items: list[dict], statements_only: bool, dry_run: bool, skip_known: bool) -> dict:
    store = None if dry_run else S3RawStore()
    manifest = store.load_manifest() if store else Manifest()

    stats = {"written": 0, "filtered": 0, "unchanged": 0, "error": 0}
    for item in items:
        status = _ingest_one(item, store, manifest, statements_only, dry_run, skip_known)
        stats[status] = stats.get(status, 0) + 1

    if store:
        store.save_manifest(manifest)
    return stats


def run_backfill(statements_only: bool = False, dry_run: bool = False) -> dict:
    """回填日历页上的全部 Fed 声明 + 纪要。"""
    logger.info("=" * 60)
    logger.info("Fed 回填%s%s",
                "（仅声明）" if statements_only else "（声明+纪要）",
                "  [DRY-RUN]" if dry_run else "")
    items = fed.list_meetings()
    logger.info("日历页共发现 %d 篇（声明+纪要）", len(items))
    stats = _run(items, statements_only, dry_run, skip_known=False)
    logger.info("回填完成：%s", stats)
    return stats


def run_incremental(statements_only: bool = False, dry_run: bool = False) -> dict:
    """增量：抓日历页上尚未入库的新声明 / 纪要。Lambda 调用此函数。"""
    logger.info("Fed 增量%s", "  [DRY-RUN]" if dry_run else "")
    items = fed.list_meetings()
    stats = _run(items, statements_only, dry_run, skip_known=True)
    logger.info("增量完成：%s", stats)
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(prog="macropulse.ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_ in [("backfill", "回填全部历史"), ("incremental", "只抓新增")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--statements-only", action="store_true", default=False,
                       help="只保留 FOMC 声明，跳过纪要")
        p.add_argument("--dry-run", action="store_true", default=False)

    args = parser.parse_args(argv)
    fn = run_backfill if args.cmd == "backfill" else run_incremental
    fn(statements_only=args.statements_only, dry_run=args.dry_run)


if __name__ == "__main__":
    main(sys.argv[1:])
