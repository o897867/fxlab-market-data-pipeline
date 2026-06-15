#!/usr/bin/env python3
"""
Analytics API Router
从 S3 读取预计算的分析结果 JSON 并提供给前端
"""

import json
import time
import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])
logger = logging.getLogger(__name__)

S3_BUCKET = "fxlab-data-lake"
S3_REGION = "ap-southeast-2"
ANALYSIS_PREFIX = "analysis"

# 简单内存缓存（TTL 5 分钟）
_cache: dict = {}
_CACHE_TTL = 300


def _get_s3():
    return boto3.client("s3", region_name=S3_REGION)


def _read_s3_json(key: str) -> dict:
    """从 S3 读取 JSON，带内存缓存"""
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
            raise HTTPException(404, f"Analysis not yet available: {key}")
        raise HTTPException(500, f"S3 error: {e}")


def _slice_series(data: dict, days: Optional[int]) -> dict:
    """按天数裁剪 series/results 数组"""
    if days is None:
        return data
    if "results" in data and isinstance(data["results"], list):
        data = {**data, "results": data["results"][-days:]}
    elif "results" in data and isinstance(data["results"], dict) and "series" in data["results"]:
        data = {**data, "results": {**data["results"], "series": data["results"]["series"][-days:]}}
    return data


# ========== XAU 端点 ==========

@router.get("/xau/daily-stats")
async def xau_daily_stats(days: Optional[int] = Query(None, le=365)):
    data = _read_s3_json(f"{ANALYSIS_PREFIX}/xau_daily_stats.json")
    return _slice_series(data, days)


@router.get("/xau/volatility")
async def xau_volatility(days: Optional[int] = Query(None, le=365)):
    data = _read_s3_json(f"{ANALYSIS_PREFIX}/xau_volatility.json")
    return _slice_series(data, days)


@router.get("/xau/sessions")
async def xau_sessions():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/xau_sessions.json")


@router.get("/xau/weekly")
async def xau_weekly():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/xau_weekly.json")


# ========== DXY（美元指数）端点 ==========

@router.get("/dxy/daily-stats")
async def dxy_daily_stats(days: Optional[int] = Query(None, le=2000)):
    return _slice_series(_read_s3_json(f"{ANALYSIS_PREFIX}/dxy_daily_stats.json"), days)


@router.get("/dxy/volatility")
async def dxy_volatility(days: Optional[int] = Query(None, le=2000)):
    return _slice_series(_read_s3_json(f"{ANALYSIS_PREFIX}/dxy_volatility.json"), days)


@router.get("/dxy/sessions")
async def dxy_sessions():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/dxy_sessions.json")


@router.get("/dxy/weekly")
async def dxy_weekly():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/dxy_weekly.json")


# ========== US2Y（2年期国债收益率）端点 ==========

@router.get("/us2y/daily-stats")
async def us2y_daily_stats(days: Optional[int] = Query(None, le=2000)):
    return _slice_series(_read_s3_json(f"{ANALYSIS_PREFIX}/us2y_daily_stats.json"), days)


@router.get("/us2y/volatility")
async def us2y_volatility(days: Optional[int] = Query(None, le=2000)):
    return _slice_series(_read_s3_json(f"{ANALYSIS_PREFIX}/us2y_volatility.json"), days)


@router.get("/us2y/sessions")
async def us2y_sessions():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/us2y_sessions.json")


@router.get("/us2y/weekly")
async def us2y_weekly():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/us2y_weekly.json")


# ========== News 端点 ==========

@router.get("/news/sentiment")
async def news_sentiment(days: Optional[int] = Query(None, le=365)):
    data = _read_s3_json(f"{ANALYSIS_PREFIX}/news_sentiment.json")
    return _slice_series(data, days)


@router.get("/news/categories")
async def news_categories():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/news_categories.json")


@router.get("/news/correlation")
async def news_correlation():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/news_correlation.json")


@router.get("/news/symbols")
async def news_symbols():
    return _read_s3_json(f"{ANALYSIS_PREFIX}/news_symbols.json")


# ========== 状态 ==========

@router.get("/status")
async def analytics_status():
    """返回各分析结果的最后更新时间"""
    s3 = _get_s3()
    files = [
        "xau_daily_stats", "xau_volatility", "xau_sessions", "xau_weekly",
        "dxy_daily_stats", "dxy_volatility", "dxy_sessions", "dxy_weekly",
        "us2y_daily_stats", "us2y_volatility", "us2y_sessions", "us2y_weekly",
        "news_sentiment", "news_categories", "news_correlation", "news_symbols",
    ]
    status = {}
    for f in files:
        key = f"{ANALYSIS_PREFIX}/{f}.json"
        try:
            meta = s3.head_object(Bucket=S3_BUCKET, Key=key)
            status[f] = {
                "last_modified": meta["LastModified"].isoformat(),
                "size_bytes": meta["ContentLength"],
            }
        except ClientError:
            status[f] = {"error": "not found"}

    return {"bucket": S3_BUCKET, "analyses": status}
