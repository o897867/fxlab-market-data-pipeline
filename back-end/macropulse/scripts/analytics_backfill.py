#!/usr/bin/env python3
"""一次性：把 DXY / US2Y 做到与 XAU 同级的 Analytics。

对每个标的：
  1. 从 SQLite 读 *_candles_1m → 导出 Parquet 到 S3 raw/{inst}/candles_1m/（年月分区）
  2. 跑四类分析（instrument_analysis.analyze）→ 上传 analysis/{inst}_*.json
后续每日增量由 export_to_s3 + Lambda 接管（见 export_to_s3 的 INSTRUMENTS）。
"""

import io
import sys
import json
import sqlite3

import boto3
import pandas as pd

sys.path.insert(0, "/root/shopback/ShopBack_PP/back-end")
sys.path.insert(0, "/root/shopback/ShopBack_PP/back-end/lambda/analytics")
from instrument_analysis import analyze  # noqa: E402

DB = "/root/shopback/ShopBack_PP/back-end/shopback_data.db"
BUCKET = "fxlab-data-lake"
REGION = "ap-southeast-2"
INSTRUMENTS = {"dxy": "dxy_candles_1m", "us2y": "us2y_candles_1m"}

s3 = boto3.client("s3", region_name=REGION)


def export_parquet(df: pd.DataFrame, inst: str) -> int:
    """按年月分区写 Parquet 到 raw/{inst}/candles_1m/。"""
    df = df.copy()
    df["year"] = df["dt"].dt.year
    df["month"] = df["dt"].dt.month
    n = 0
    for (y, m), g in df.groupby(["year", "month"]):
        part = g.drop(columns=["dt", "year", "month"])
        key = f"raw/{inst}/candles_1m/year={y}/month={m:02d}/{inst}_1m_{y}-{m:02d}.parquet"
        buf = io.BytesIO()
        part.to_parquet(buf, engine="pyarrow", index=False)
        buf.seek(0)
        s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
        n += len(part)
    return n


def main():
    conn = sqlite3.connect(DB)
    for inst, table in INSTRUMENTS.items():
        df = pd.read_sql_query(
            f"SELECT open_time, open, high, low, close, volume FROM {table} ORDER BY open_time", conn)
        df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        print(f"[{inst}] {len(df):,} 行 {df['dt'].min().date()} → {df['dt'].max().date()}")

        n = export_parquet(df, inst)
        print(f"  Parquet → s3://{BUCKET}/raw/{inst}/candles_1m/  ({n:,} 行)")

        results = analyze(df, inst)
        for name, data in results.items():
            key = f"analysis/{name}.json"
            s3.put_object(Bucket=BUCKET, Key=key,
                          Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                          ContentType="application/json; charset=utf-8")
            print(f"  analysis/{name}.json")
    conn.close()
    print("完成")


if __name__ == "__main__":
    main()
