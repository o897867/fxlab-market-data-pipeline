"""抽取层 CLI。

  python -m macropulse.extraction.cli one --date 2026-04-29 [--type statement|minutes] [--dry-run]
  python -m macropulse.extraction.cli backfill [--statements-only] [--dry-run]

one      ：单篇即时打分（messages.parse），用于冒烟与人工核对。
backfill ：全量历史走 Batch API（5 折），结果写 S3 + 幂等 manifest。

幂等：manifest 记录 (content_hash, prompt_hash)。两者都未变则跳过；
改了 prompt（PROMPT_VERSION/锚点）或重抓了原文会自动重打。

Jackson Hole 等非常规声明（标题不含 "issues FOMC statement"）不参与 diff 链：
自身照常打分但不带 diff，也不作为下一篇的对比基准。
"""

from __future__ import annotations

import json
import sys
import time
import logging
import argparse
from dataclasses import asdict
from datetime import datetime, timezone

import anthropic

from macropulse import config
from macropulse.diff import diff_statements, UNCHANGED
from macropulse.s3_store import S3RawStore
from macropulse.extraction import prompts
from macropulse.extraction.extractor import Extractor, UsageTally
from macropulse.extraction.schema import (
    StatementScores, MinutesScores, build_record, merge_diff_labels,
    validate_quotes, validate_scores,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("macropulse.extraction")


# ---------------------------------------------------------------- 语料访问


def _index(store: S3RawStore, doc_type: str) -> dict[str, str]:
    """meeting_date -> s3 key。"""
    prefix = f"{config.RAW_MACRO_PREFIX}/fed/{doc_type}/"
    out = {}
    paginator = store.s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=store.bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                date = o["Key"].rsplit("_", 1)[-1].replace(".json", "")
                out[date] = o["Key"]
    return out


def _load_anchors(store: S3RawStore, stmt_idx: dict[str, str]) -> list[dict]:
    anchors = []
    for date in prompts.ANCHOR_DATES:
        if date not in stmt_idx:
            raise SystemExit(f"锚点声明 {date} 不在 S3 语料中，无法构建打分标尺")
        anchors.append(store.load_json(stmt_idx[date]))
    return anchors


def _is_regular(doc: dict) -> bool:
    return "issues fomc statement" in doc.get("title", "").lower()


def _diff_entries(prev_doc: dict | None, doc: dict) -> list[dict]:
    """非 unchanged 段落的 dict 列表（喂给 prompt 与 merge）。"""
    if prev_doc is None:
        return []
    d = diff_statements(prev_doc, doc)
    return [asdict(p) for p in d.paragraphs if p.status != UNCHANGED]


def _prev_regular(stmt_idx: dict[str, str], store: S3RawStore, date: str, cache: dict) -> dict | None:
    """date 之前最近的一篇常规声明（跳过 Jackson Hole 类）。"""
    for d in sorted(stmt_idx, reverse=True):
        if d >= date:
            continue
        doc = cache.setdefault(d, store.load_json(stmt_idx[d]))
        if _is_regular(doc):
            return doc
    return None


# ---------------------------------------------------------------- manifest / 落盘


def _load_manifest(store: S3RawStore) -> dict:
    try:
        obj = store.s3.get_object(Bucket=store.bucket, Key=config.EXTRACTION_MANIFEST_KEY)
        return json.loads(obj["Body"].read())
    except Exception:
        return {"documents": {}}


def _save_manifest(store: S3RawStore, manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.s3.put_object(
        Bucket=store.bucket, Key=config.EXTRACTION_MANIFEST_KEY,
        Body=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )


def _score_key(doc: dict) -> str:
    year = doc["meeting_date"][:4]
    return f"{config.SCORES_PREFIX}/{doc['doc_type']}/year={year}/fed_score_{doc['doc_type']}_{doc['meeting_date']}.json"


def _put_score(store: S3RawStore, doc: dict, record: dict) -> str:
    key = _score_key(doc)
    store.s3.put_object(
        Bucket=store.bucket, Key=key,
        Body=json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    logger.info("  -> s3://%s/%s", store.bucket, key)
    return key


# ---------------------------------------------------------------- one（即时单篇）


def run_one(date: str, doc_type: str, dry_run: bool) -> dict:
    store = S3RawStore()
    stmt_idx = _index(store, "statement")
    anchors = _load_anchors(store, stmt_idx)
    ex = Extractor(anchors)

    idx = stmt_idx if doc_type == "statement" else _index(store, doc_type)
    if date not in idx:
        raise SystemExit(f"{doc_type} {date} 不在 S3 语料中（可选：{sorted(idx)[-5:]}）")
    doc = store.load_json(idx[date])

    if doc_type == "statement":
        prev = _prev_regular(stmt_idx, store, date, {}) if _is_regular(doc) else None
        record = ex.score_statement(doc, _diff_entries(prev, doc))
    else:
        record = ex.score_minutes(doc)

    print(json.dumps(record, ensure_ascii=False, indent=2))
    logger.info("用量：%s", ex.usage.report())

    if not dry_run:
        manifest = _load_manifest(store)
        key = _put_score(store, doc, record)
        manifest["documents"][doc["document_id"]] = {
            "content_hash": doc["content_hash"],
            "prompt_hash": prompts.prompt_hash(ex.system_statement),
            "score_key": key,
        }
        _save_manifest(store, manifest)
    return record


# ---------------------------------------------------------------- backfill（Batch API）


def _strict_schema(model_cls) -> dict:
    """Pydantic schema → 结构化输出兼容（每个 object 加 additionalProperties:false）。"""
    s = model_cls.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(s)
    return s


def _batch_request(custom_id: str, system: str, user: str, model_cls, model: str) -> dict:
    return {
        "custom_id": custom_id,
        "params": {
            "model": model,
            "max_tokens": 16000,
            "thinking": {"type": "adaptive"},
            "system": [{"type": "text", "text": system,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": _strict_schema(model_cls)}},
        },
    }


def run_backfill(statements_only: bool, dry_run: bool) -> None:
    store = S3RawStore()
    stmt_idx = _index(store, "statement")
    min_idx = {} if statements_only else _index(store, "minutes")
    anchors = _load_anchors(store, stmt_idx)
    sys_stmt = prompts.build_system_prompt(anchors, "statement")
    sys_min = prompts.build_system_prompt(anchors, "minutes")
    p_hash = prompts.prompt_hash(sys_stmt)

    manifest = _load_manifest(store)
    done = manifest["documents"]

    # 组装待打分任务（跳过 manifest 中 content+prompt 都未变的）
    requests, meta = [], {}
    doc_cache: dict[str, dict] = {}

    for date in sorted(stmt_idx):
        doc = doc_cache.setdefault(date, store.load_json(stmt_idx[date]))
        rec = done.get(doc["document_id"])
        if rec and rec.get("content_hash") == doc["content_hash"] and rec.get("prompt_hash") == p_hash:
            continue
        prev = _prev_regular(stmt_idx, store, date, doc_cache) if _is_regular(doc) else None
        diffs = _diff_entries(prev, doc)
        cid = doc["document_id"]
        requests.append(_batch_request(cid, sys_stmt,
                                       prompts.build_statement_user(doc, diffs),
                                       StatementScores, config.EXTRACT_MODEL))
        meta[cid] = {"doc": doc, "diffs": diffs, "cls": StatementScores}

    for date in sorted(min_idx):
        doc = store.load_json(min_idx[date])
        rec = done.get(doc["document_id"])
        if rec and rec.get("content_hash") == doc["content_hash"] and rec.get("prompt_hash") == p_hash:
            continue
        cid = doc["document_id"]
        requests.append(_batch_request(cid, sys_min, prompts.build_minutes_user(doc),
                                       MinutesScores, config.EXTRACT_MODEL))
        meta[cid] = {"doc": doc, "diffs": None, "cls": MinutesScores}

    logger.info("待打分 %d 篇（声明 %d / 纪要 %d），跳过未变 %d 篇",
                len(requests),
                sum(1 for m in meta.values() if m["cls"] is StatementScores),
                sum(1 for m in meta.values() if m["cls"] is MinutesScores),
                len(stmt_idx) + len(min_idx) - len(requests))
    if dry_run or not requests:
        logger.info("[DRY-RUN] 不提交 Batch" if dry_run else "无新任务")
        return

    client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=requests)
    logger.info("Batch 已提交：%s（5 折计费），轮询中…", batch.id)

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        logger.info("  status=%s processing=%d", batch.processing_status,
                    batch.request_counts.processing)
        time.sleep(30)

    tally = UsageTally()
    ok = err = 0
    for result in client.messages.batches.results(batch.id):
        cid = result.custom_id
        if result.result.type != "succeeded":
            logger.error("%s: %s", cid, result.result.type)
            err += 1
            continue
        msg = result.result.message
        tally.add(msg.usage)
        text = next(b.text for b in msg.content if b.type == "text")
        m = meta[cid]
        scores = m["cls"].model_validate_json(text)
        doc = m["doc"]
        diffs = merge_diff_labels(m["diffs"], scores.diff_labels) if m["diffs"] is not None else None
        record = build_record(
            doc, scores, diffs_vs_previous=diffs, model=config.EXTRACT_MODEL,
            prompt_version=prompts.PROMPT_VERSION,
            quote_violations=validate_quotes(scores.dimensions, doc["text"]),
            score_violations=validate_scores(scores),
        )
        key = _put_score(store, doc, record)
        done[doc["document_id"]] = {
            "content_hash": doc["content_hash"], "prompt_hash": p_hash, "score_key": key,
        }
        ok += 1

    _save_manifest(store, manifest)
    logger.info("回填完成：成功 %d / 失败 %d", ok, err)
    logger.info("用量（Batch 5 折前的标价口径）：%s → 实际约 $%.3f",
                tally.report(), tally.cost_usd() / 2)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="macropulse.extraction.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("one", help="单篇即时打分")
    po.add_argument("--date", required=True)
    po.add_argument("--type", dest="doc_type", choices=["statement", "minutes"],
                    default="statement")
    po.add_argument("--dry-run", action="store_true", help="只打印不写 S3")

    pb = sub.add_parser("backfill", help="全量历史 Batch 打分")
    pb.add_argument("--statements-only", action="store_true")
    pb.add_argument("--dry-run", action="store_true", help="只统计任务不提交")

    args = parser.parse_args(argv)
    if args.cmd == "one":
        run_one(args.date, args.doc_type, args.dry_run)
    else:
        run_backfill(args.statements_only, args.dry_run)


if __name__ == "__main__":
    main(sys.argv[1:])
