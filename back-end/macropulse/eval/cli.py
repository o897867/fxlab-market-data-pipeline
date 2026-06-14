"""Eval CLI。

  python -m macropulse.eval.cli snapshot          # 刷新 golden（重打 prompt 后用，review diff 再 commit）
  python -m macropulse.eval.cli check              # 本地跑结构/校准回归（等同 CI Tier-1）
  python -m macropulse.eval.cli queue [--write]    # 生成人工裁决队列报告
"""

from __future__ import annotations

import json
import sys
import logging
import argparse

from dotenv import load_dotenv

load_dotenv()

from macropulse import config
from macropulse.s3_store import S3RawStore
from macropulse.eval import golden as goldenmod
from macropulse.eval import regression, queue as queuemod

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("macropulse.eval")

QUEUE_KEY = "analysis/macro/fed/eval/adjudication_queue.json"


def _all_scores(store: S3RawStore) -> list[dict]:
    recs = []
    pag = store.s3.get_paginator("list_objects_v2")
    for page in pag.paginate(Bucket=store.bucket, Prefix=config.SCORES_PREFIX + "/"):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                recs.append(store.load_json(o["Key"]))
    return recs


def cmd_snapshot():
    store = S3RawStore()
    recs = _all_scores(store)
    n = goldenmod.save_golden(recs)
    logger.info("golden 刷新 %d 条 -> %s", n, goldenmod.GOLDEN_PATH)
    g = goldenmod.load_golden()
    probs = regression.check_all(g)
    bands = regression.check_anchor_bands(g)
    print("结构问题:", probs or "无")
    print("锚点校准带:", bands or "✅ 全在带内")
    print("→ git diff 审查后再 commit golden_scores.json")


def cmd_check():
    g = goldenmod.load_golden()
    probs = regression.check_all(g)
    bands = regression.check_anchor_bands(g)
    print(f"golden {len(g)} 条")
    print("结构问题:", probs or "✅ 0")
    print("锚点校准带:", bands or "✅ 全在带内")
    sys.exit(1 if probs or bands else 0)


def cmd_queue(write: bool):
    store = S3RawStore()
    scores = _all_scores(store)
    try:
        attribution = store.load_json(f"{config.ATTRIBUTION_PREFIX}/backtest.json")
    except Exception:
        attribution = None
        logger.warning("无归因结果，price_conflict 维度跳过")
    adjudicated = queuemod.load_adjudications()
    q = queuemod.build_queue(scores, attribution, adjudicated)

    print("█" * 60)
    print(f"人工裁决队列：{len(q)} 项待裁决（生产 {len(scores)} 条，已裁决 {len(adjudicated)}）")
    print("█" * 60)
    for item in q:
        print(f"\n{item['meeting_date']} [{item['doc_type']}] overall={item['overall_score']:+d} "
              f"conf={item['confidence_overall']}")
        for r in item["reasons"]:
            print(f"    • {r}")
    if not q:
        print("\n✅ 队列为空，无待裁决项")

    if write:
        store.s3.put_object(
            Bucket=store.bucket, Key=QUEUE_KEY,
            Body=json.dumps(q, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8")
        logger.info("已写 s3://%s/%s", store.bucket, QUEUE_KEY)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="macropulse.eval.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", help="刷新 golden 快照")
    sub.add_parser("check", help="本地跑 Tier-1 回归")
    pq = sub.add_parser("queue", help="生成人工裁决队列")
    pq.add_argument("--write", action="store_true", help="同时写 S3")
    args = parser.parse_args(argv)
    {"snapshot": lambda: cmd_snapshot(),
     "check": lambda: cmd_check(),
     "queue": lambda: cmd_queue(args.write)}[args.cmd]()


if __name__ == "__main__":
    main(sys.argv[1:])
