"""MacroPulse Lambda 入口 —— 定时增量抓取 Fed 货币政策稿件。

部署约定与 analytics-pipeline 一致：EventBridge 定时触发，IAM role 提供 S3 权限，
不在代码内写凭证。event 可选字段：
  - mode: "incremental"（默认）| "backfill"
  - years: backfill 时回填年数
  - statements_only: bool

打包注意：Lambda 运行时自带 boto3，但 requests / beautifulsoup4 需随代码或 layer
一并打包；同时需把 back-end/macropulse 包加入部署 zip 的 import 路径。
"""

import json
import logging

# 让 `import macropulse.*` 在 Lambda 扁平部署包下可用
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from macropulse.ingest import run_incremental, run_backfill

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    mode = event.get("mode", "incremental")
    statements_only = event.get("statements_only", False)

    if mode == "backfill":
        stats = run_backfill(years=event.get("years"), statements_only=statements_only)
    else:
        stats = run_incremental(statements_only=statements_only)

    return {
        "statusCode": 200,
        "body": json.dumps({"mode": mode, "stats": stats}),
    }


if __name__ == "__main__":
    print(json.dumps(json.loads(lambda_handler({"mode": "incremental", "statements_only": True}, None)["body"]), indent=2))
