#!/usr/bin/env python3
"""
MacroPulse API Router
从 S3 读取央行通讯的鹰鸽分数 / 红线 diff / 归因回测 / 裁决队列，供前端展示。
只读，全部走 analysis/macro 与 raw/macro 前缀；diff 复用 macropulse.diff 引擎。
"""

import json
import time
import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/macro", tags=["MacroPulse"])
logger = logging.getLogger(__name__)

S3_BUCKET = "fxlab-data-lake"
S3_REGION = "ap-southeast-2"
SCORES_PREFIX = "analysis/macro/fed/scores"
ATTRIBUTION_KEY = "analysis/macro/fed/attribution/backtest.json"
QUEUE_KEY = "analysis/macro/fed/eval/adjudication_queue.json"
RAW_STMT_PREFIX = "raw/macro/fed/statement"

_cache: dict = {}
_CACHE_TTL = 300


def _get_s3():
    return boto3.client("s3", region_name=S3_REGION)


def _read_json(key: str, optional: bool = False):
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < _CACHE_TTL:
        return _cache[key]["data"]
    try:
        obj = _get_s3().get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(obj["Body"].read())
        _cache[key] = {"data": data, "ts": now}
        return data
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            if optional:
                return None
            raise HTTPException(404, f"Not yet available: {key}")
        raise HTTPException(500, f"S3 error: {e}")


def _list_keys(prefix: str) -> list[str]:
    s3 = _get_s3()
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix + "/"):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                keys.append(o["Key"])
    return keys


def _all_scores() -> list[dict]:
    """列出并读取全部分数（带聚合缓存）。"""
    ckey = "__all_scores__"
    now = time.time()
    if ckey in _cache and now - _cache[ckey]["ts"] < _CACHE_TTL:
        return _cache[ckey]["data"]
    s3 = _get_s3()
    out = []
    for key in _list_keys(SCORES_PREFIX):
        out.append(json.loads(s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()))
    out.sort(key=lambda r: (r["doc_type"], r["meeting_date"]))
    _cache[ckey] = {"data": out, "ts": now}
    return out


def _summary(r: dict) -> dict:
    """时间线用的精简视图。"""
    return {
        "document_id": r["document_id"],
        "doc_type": r["doc_type"],
        "meeting_date": r["meeting_date"],
        "overall_score": r["overall_score"],
        "confidence_overall": r.get("confidence_overall"),
        "needs_human_review": r.get("needs_human_review", False),
        "dimension_scores": {k: v["score"] for k, v in r.get("dimensions", {}).items()},
    }


# ========== 分数 ==========

@router.get("/scores")
async def list_scores(doc_type: Optional[str] = Query(None, pattern="^(statement|minutes)$")):
    """鹰鸽分数时间线（精简）。可按 doc_type 过滤。"""
    rows = _all_scores()
    if doc_type:
        rows = [r for r in rows if r["doc_type"] == doc_type]
    return {"count": len(rows), "scores": [_summary(r) for r in rows]}


@router.get("/scores/{document_id}")
async def score_detail(document_id: str):
    """单篇完整分数（含各维度 key_quote 与 diff 方向标注）。"""
    for r in _all_scores():
        if r["document_id"] == document_id:
            return r
    raise HTTPException(404, f"No score for {document_id}")


# ========== 红线 diff ==========

def _statement_index() -> dict:
    """meeting_date -> raw statement json key。"""
    idx = {}
    for key in _list_keys(RAW_STMT_PREFIX):
        date = key.rsplit("_", 1)[-1].replace(".json", "")
        idx[date] = key
    return idx


@router.get("/diff")
async def statement_diff(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """两期声明红线对比；不传则取最近两期。"""
    from macropulse.diff import diff_statements, render_text  # 局部 import，避免启动期依赖

    idx = _statement_index()
    dates = sorted(idx)
    if len(dates) < 2:
        raise HTTPException(404, "Need at least two statements")
    if from_date and to_date:
        if from_date not in idx or to_date not in idx:
            raise HTTPException(404, "Unknown statement date")
        a, b = from_date, to_date
    else:
        a, b = dates[-2], dates[-1]

    s3 = _get_s3()
    old = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=idx[a])["Body"].read())
    new = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=idx[b])["Body"].read())
    d = diff_statements(old, new)
    out = d.to_dict()
    out["redline_text"] = render_text(d)
    out["available_dates"] = dates
    return out


# ========== 归因 / 队列 / 状态 ==========

@router.get("/attribution")
async def attribution():
    """鹰鸽分数 vs XAU 价格反应的归因回测结果。"""
    return _read_json(ATTRIBUTION_KEY)


@router.get("/adjudication-queue")
async def adjudication_queue():
    """人工裁决队列（低置信/needs_review/逐字违规/价格冲突）。"""
    data = _read_json(QUEUE_KEY, optional=True)
    return {"count": len(data or []), "queue": data or []}


@router.get("/status")
async def status():
    """各数据集的最后更新时间，供前端显示新鲜度。"""
    s3 = _get_s3()
    scores = _all_scores()
    out = {
        "bucket": S3_BUCKET,
        "n_scores": len(scores),
        "n_statements": sum(1 for r in scores if r["doc_type"] == "statement"),
        "n_minutes": sum(1 for r in scores if r["doc_type"] == "minutes"),
        "datasets": {},
    }
    for name, key in (("attribution", ATTRIBUTION_KEY), ("adjudication_queue", QUEUE_KEY)):
        try:
            meta = s3.head_object(Bucket=S3_BUCKET, Key=key)
            out["datasets"][name] = {"last_modified": meta["LastModified"].isoformat(),
                                     "size_bytes": meta["ContentLength"]}
        except ClientError:
            out["datasets"][name] = {"error": "not found"}
    return out
