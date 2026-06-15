#!/usr/bin/env python3
"""
ETL: SQLite -> Parquet -> S3
从本地 SQLite 增量导出数据到 S3 数据湖
"""

import json
import logging
import sys
import io
from datetime import datetime, timezone

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# 允许作为模块运行 (python -m analytics.export_to_s3)
sys.path.insert(0, "/root/shopback/ShopBack_PP/back-end")
from database import get_db_connection
from analytics.config import S3_BUCKET, S3_REGION, RAW_XAU_PREFIX, RAW_NEWS_PREFIX, METADATA_KEY, LAMBDA_FUNCTION_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

s3 = boto3.client("s3", region_name=S3_REGION)


def get_watermark() -> dict:
    """从 S3 读取上次导出的水位线"""
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=METADATA_KEY)
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return {"xau_last_open_time": 0, "news_last_id": 0}
    except Exception:
        return {"xau_last_open_time": 0, "news_last_id": 0}


def save_watermark(wm: dict):
    """更新 S3 水位线"""
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=METADATA_KEY,
        Body=json.dumps(wm),
        ContentType="application/json",
    )


def upload_parquet(df: pd.DataFrame, s3_key: str):
    """将 DataFrame 写为 Parquet 并上传到 S3"""
    buf = io.BytesIO()
    df.to_parquet(buf, engine="pyarrow", index=False)
    buf.seek(0)
    s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=buf.getvalue())
    logger.info(f"  -> s3://{S3_BUCKET}/{s3_key} ({len(df)} rows, {buf.tell()} bytes)")


def export_xau(watermark: dict) -> int:
    """导出 XAU 1 分钟 K 线到 S3"""
    last = watermark.get("xau_last_open_time", 0)
    conn = get_db_connection()
    try:
        df = pd.read_sql_query(
            "SELECT open_time, open, high, low, close, volume FROM xau_candles_1m "
            "WHERE open_time > ? ORDER BY open_time",
            conn,
            params=(last,),
        )
    finally:
        conn.close()

    if df.empty:
        logger.info("XAU: 无新数据")
        return 0

    # open_time 是毫秒时间戳，转为 datetime 用于分区
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["year"] = df["dt"].dt.year
    df["month"] = df["dt"].dt.month

    total = 0
    for (year, month), group in df.groupby(["year", "month"]):
        part = group.drop(columns=["dt", "year", "month"])
        key = f"{RAW_XAU_PREFIX}/year={year}/month={month:02d}/xau_1m_{year}-{month:02d}.parquet"

        # 如果 S3 上已有该分区文件，合并去重
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            existing = pd.read_parquet(io.BytesIO(obj["Body"].read()))
            part = pd.concat([existing, part]).drop_duplicates(subset=["open_time"]).sort_values("open_time")
        except Exception:
            pass

        upload_parquet(part, key)
        total += len(group)

    watermark["xau_last_open_time"] = int(df["open_time"].max())
    logger.info(f"XAU: 导出 {total} 条新记录")
    return total


def export_news(watermark: dict) -> int:
    """导出新闻到 S3"""
    last_id = watermark.get("news_last_id", 0)
    conn = get_db_connection()
    try:
        df = pd.read_sql_query(
            "SELECT id, news_id, title, summary, summary_cn, source, "
            "published_at, received_at, symbols, sentiment, impact_level, category "
            "FROM financial_news WHERE id > ? ORDER BY id",
            conn,
            params=(last_id,),
        )
    finally:
        conn.close()

    if df.empty:
        logger.info("News: 无新数据")
        return 0

    # published_at 是秒级 Unix 时间戳
    df["pub_dt"] = pd.to_datetime(df["published_at"], unit="s", errors="coerce", utc=True)
    # 用 received_at 兜底（字符串格式）
    mask = df["pub_dt"].isna()
    if mask.any():
        df.loc[mask, "pub_dt"] = pd.to_datetime(df.loc[mask, "received_at"], errors="coerce", utc=True)
    df["pub_dt"] = df["pub_dt"].fillna(pd.Timestamp.now(tz="UTC"))

    df["year"] = df["pub_dt"].dt.year
    df["month"] = df["pub_dt"].dt.month

    total = 0
    for (year, month), group in df.groupby(["year", "month"]):
        part = group.drop(columns=["pub_dt", "year", "month"])
        key = f"{RAW_NEWS_PREFIX}/year={year}/month={month:02d}/news_{year}-{month:02d}.parquet"

        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            existing = pd.read_parquet(io.BytesIO(obj["Body"].read()))
            part = pd.concat([existing, part]).drop_duplicates(subset=["id"]).sort_values("id")
        except Exception:
            pass

        upload_parquet(part, key)
        total += len(group)

    watermark["news_last_id"] = int(df["id"].max())
    logger.info(f"News: 导出 {total} 条新记录")
    return total


def export_instrument(watermark: dict, inst: str, table: str) -> int:
    """通用：把 {inst}_candles_1m 增量导出到 raw/{inst}/candles_1m/。"""
    wm_key = f"{inst}_last_open_time"
    last = watermark.get(wm_key, 0)
    conn = get_db_connection()
    try:
        df = pd.read_sql_query(
            f"SELECT open_time, open, high, low, close, volume FROM {table} "
            "WHERE open_time > ? ORDER BY open_time", conn, params=(last,))
    finally:
        conn.close()
    if df.empty:
        logger.info("%s: 无新数据", inst.upper())
        return 0
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["year"] = df["dt"].dt.year
    df["month"] = df["dt"].dt.month
    total = 0
    for (year, month), group in df.groupby(["year", "month"]):
        part = group.drop(columns=["dt", "year", "month"])
        key = f"raw/{inst}/candles_1m/year={year}/month={month:02d}/{inst}_1m_{year}-{month:02d}.parquet"
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            existing = pd.read_parquet(io.BytesIO(obj["Body"].read()))
            part = pd.concat([existing, part]).drop_duplicates(subset=["open_time"]).sort_values("open_time")
        except Exception:
            pass
        upload_parquet(part, key)
        total += len(group)
    watermark[wm_key] = int(df["open_time"].max())
    logger.info("%s: 导出 %d 条新记录", inst.upper(), total)
    return total


def main():
    logger.info("=" * 50)
    logger.info("开始数据导出到 S3")
    watermark = get_watermark()
    logger.info(f"水位线: {watermark}")

    table = None
    if len(sys.argv) > 1 and sys.argv[1] == "--table":
        table = sys.argv[2] if len(sys.argv) > 2 else None

    if table is None or table == "xau":
        export_xau(watermark)
    if table is None or table == "dxy":
        export_instrument(watermark, "dxy", "dxy_candles_1m")
    if table is None or table == "us2y":
        export_instrument(watermark, "us2y", "us2y_candles_1m")
    if table is None or table == "news":
        export_news(watermark)

    save_watermark(watermark)
    logger.info("导出完成")

    # Export 成功后触发 Lambda 分析
    trigger_lambda()


def trigger_lambda():
    """导出完成后自动触发分析 Lambda"""
    try:
        client = boto3.client("lambda", region_name=S3_REGION)
        resp = client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="Event",  # 异步，不等结果
            Payload=json.dumps({"analysis": "all", "trigger": "export_to_s3"}),
        )
        logger.info(f"Lambda '{LAMBDA_FUNCTION_NAME}' triggered, status={resp['StatusCode']}")
    except Exception as e:
        logger.error(f"Lambda 触发失败: {e}")


if __name__ == "__main__":
    main()
