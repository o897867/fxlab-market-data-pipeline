"""
Lambda 入口
从 S3 读取 Parquet 数据 → 运行分析 → 写结果 JSON 回 S3
"""

import json
import logging
import os

import boto3

from xau_analysis import run_all as run_xau
from news_analysis import run_all as run_news
from instrument_analysis import load_from_s3, analyze

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BUCKET = os.environ.get("S3_BUCKET", "fxlab-data-lake")
ANALYSIS_PREFIX = "analysis"


def upload_json(s3, key: str, data: dict):
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False),
        ContentType="application/json; charset=utf-8",
    )
    logger.info(f"Uploaded s3://{BUCKET}/{key}")


def lambda_handler(event, context):
    """
    event 可选字段:
      - analysis: "xau" | "news" | "all" (默认 "all")
    """
    s3 = boto3.client("s3")
    analysis = event.get("analysis", "all") if isinstance(event, dict) else "all"

    results = {}

    if analysis in ("xau", "all"):
        logger.info("Running XAU analysis...")
        xau_results = run_xau(s3, BUCKET)
        for name, data in xau_results.items():
            key = f"{ANALYSIS_PREFIX}/{name}.json"
            upload_json(s3, key, data)
            results[name] = f"s3://{BUCKET}/{key}"

    # DXY / US2Y（通用分析，从各自 raw 前缀读 Parquet）
    for inst in ("dxy", "us2y"):
        if analysis in (inst, "all"):
            logger.info("Running %s analysis...", inst.upper())
            df = load_from_s3(s3, BUCKET, f"raw/{inst}/candles_1m/")
            for name, data in analyze(df, inst).items():
                key = f"{ANALYSIS_PREFIX}/{name}.json"
                upload_json(s3, key, data)
                results[name] = f"s3://{BUCKET}/{key}"

    if analysis in ("news", "all"):
        logger.info("Running News analysis...")
        news_results = run_news(s3, BUCKET)
        for name, data in news_results.items():
            key = f"{ANALYSIS_PREFIX}/{name}.json"
            upload_json(s3, key, data)
            results[name] = f"s3://{BUCKET}/{key}"

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Analysis complete", "outputs": results}),
    }


# 支持本地测试
if __name__ == "__main__":
    result = lambda_handler({"analysis": "all"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
