"""期权快照持久化 + 断档告警。

背景（doc §2「现在不做以后补不回来」）：InsightSentry 历史链不含已过期合约，
IV/OI 历史只能从每天落的一张当前快照往后攒。这些 Parquet 现在只在 EC2 本地、
且 data/ 已 gitignore——磁盘一挂，全部 IV 历史资产永久蒸发。

本模块干两件事，供 refresh.sh 每日 dbt run 之后调用：
  1. sync()  把本地 data/snapshots/{quotes,contracts,underlying}/*.parquet 幂等上传到
             s3://<bucket>/raw/options/{table}/{SYM}/{SYM}_{YYYYMMDD}.parquet
             （按日命名、写一次即不可变；已存在则跳过，故可反复跑）。
  2. check_freshness()  校验每只 watchlist 标的最新快照日是否够新，断档则 ⚠️ 并令进程非零退出，
             使 cron 日志可 grep（正式 alerting 是 v2 技术债，先保证不静默）。

复用 analytics 既有的 S3 桶与 boto3 实例凭证，不引入新配置。

  python -m option.sync_s3            # 同步 + freshness 检查
  python -m option.sync_s3 --force    # 强制重传（忽略 S3 已存在）
  python -m option.sync_s3 --check-only
"""

from __future__ import annotations

import os
import sys
import glob
import logging
import argparse
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from option import config
from analytics.config import S3_BUCKET, S3_REGION  # 复用同一个数据湖桶

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("option.sync_s3")

_TABLES = ("quotes", "contracts", "underlying")
S3_PREFIX = "raw/options"
# 允许的最大快照滞后天数：跨周末 + 一天缓冲。超过即视为断档。
FRESHNESS_MAX_LAG_DAYS = int(os.getenv("OPTION_FRESHNESS_LAG_DAYS", "4"))

_s3 = boto3.client("s3", region_name=S3_REGION)


def _s3_key(table: str, fname: str) -> str:
    # fname = "NVDA_20260706.parquet" -> raw/options/quotes/NVDA/NVDA_20260706.parquet
    sym = fname.split("_", 1)[0]
    return f"{S3_PREFIX}/{table}/{sym}/{fname}"


def _exists(key: str) -> bool:
    try:
        _s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def sync(force: bool = False) -> int:
    """把本地全部快照 Parquet 幂等上传到 S3。返回本次实际上传的文件数。"""
    uploaded = 0
    for table in _TABLES:
        local_dir = os.path.join(config.SNAPSHOT_DIR, table)
        for path in sorted(glob.glob(os.path.join(local_dir, "*.parquet"))):
            key = _s3_key(table, os.path.basename(path))
            if not force and _exists(key):
                continue
            with open(path, "rb") as f:
                _s3.put_object(Bucket=S3_BUCKET, Key=key, Body=f.read())
            uploaded += 1
            logger.info("  -> s3://%s/%s", S3_BUCKET, key)
    logger.info("快照同步完成：本次上传 %d 个文件（其余已存在，跳过）。", uploaded)
    return uploaded


def _latest_local_day(sym: str) -> str | None:
    """某标的本地最新快照日（YYYYMMDD），以 quotes 表为准；无则 None。"""
    files = glob.glob(os.path.join(config.SNAPSHOT_DIR, "quotes", f"{sym}_*.parquet"))
    days = [os.path.basename(p).rsplit("_", 1)[-1].replace(".parquet", "") for p in files]
    return max(days) if days else None


def check_freshness() -> list[str]:
    """校验每只 watchlist 标的最新快照是否够新。返回断档标的列表（空=健康）。"""
    today = datetime.now(timezone.utc).date()
    stale: list[str] = []
    for code in config.DEFAULT_SYMBOLS:
        sym = code.split(":")[-1]
        day = _latest_local_day(sym)
        if day is None:
            stale.append(f"{sym}(无任何快照)")
            continue
        d = datetime.strptime(day, "%Y%m%d").date()
        lag = (today - d).days
        if lag > FRESHNESS_MAX_LAG_DAYS:
            stale.append(f"{sym}(最新 {d}, 滞后 {lag}d)")
    if stale:
        logger.error("⚠️ 快照断档告警：%s ——IV 历史正在留永久空洞，检查 cron/extract！",
                     ", ".join(stale))
    else:
        logger.info("快照 freshness OK：%d 只标的均在 %d 天内。",
                    len(config.DEFAULT_SYMBOLS), FRESHNESS_MAX_LAG_DAYS)
    return stale


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="option.sync_s3")
    p.add_argument("--force", action="store_true", help="强制重传，忽略 S3 已存在")
    p.add_argument("--check-only", action="store_true", help="只跑 freshness 检查，不上传")
    args = p.parse_args(argv)

    if not args.check_only:
        sync(force=args.force)
    stale = check_freshness()
    # 断档 → 非零退出，让 refresh.sh 日志里留下可 grep 的失败信号。
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
