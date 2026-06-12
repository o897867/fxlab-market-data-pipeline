"""Opus vs DeepSeek 对比 CLI。

  python -m macropulse.extraction.compare_cli probe                 # 单篇探测（验证模型ID/key）
  python -m macropulse.extraction.compare_cli run [--statements-only] [--workers 6] [--force]
  python -m macropulse.extraction.compare_cli report

run    ：用与 Opus 回填完全相同的输入（同 diff、同锚点、同 prompt）跑 DeepSeek，
         结果落 S3 analysis/macro/fed/scores_deepseek/...（默认跳过已存在的，--force 重打）。
report ：逐篇对齐两边结果，输出一致率/相关性/分歧样本。
"""

from __future__ import annotations

import json
import sys
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()

from macropulse import config
from macropulse.s3_store import S3RawStore
from macropulse.extraction import prompts
from macropulse.extraction.cli import (
    _index, _load_anchors, _is_regular, _diff_entries, _prev_regular,
)
from macropulse.extraction.deepseek import DeepSeekExtractor, DEEPSEEK_MODEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("macropulse.compare")

DS_PREFIX = "analysis/macro/fed/scores_deepseek"
DIMS = ("inflation", "labor", "balance_sheet_qt", "forward_guidance")


def _ds_key(doc: dict) -> str:
    year = doc["meeting_date"][:4]
    return f"{DS_PREFIX}/{doc['doc_type']}/year={year}/fed_score_{doc['doc_type']}_{doc['meeting_date']}.json"


def _exists(store: S3RawStore, key: str) -> bool:
    try:
        store.s3.head_object(Bucket=store.bucket, Key=key)
        return True
    except Exception:
        return False


def _collect_tasks(store: S3RawStore, statements_only: bool) -> list[dict]:
    stmt_idx = _index(store, "statement")
    tasks, doc_cache = [], {}
    for date in sorted(stmt_idx):
        doc = doc_cache.setdefault(date, store.load_json(stmt_idx[date]))
        prev = _prev_regular(stmt_idx, store, date, doc_cache) if _is_regular(doc) else None
        tasks.append({"doc": doc, "diffs": _diff_entries(prev, doc)})
    if not statements_only:
        for date in sorted(_index(store, "minutes")):
            tasks.append({"doc": store.load_json(_index(store, "minutes")[date]), "diffs": None})
    return tasks


# ---------------------------------------------------------------- probe / run


def run_probe() -> None:
    store = S3RawStore()
    stmt_idx = _index(store, "statement")
    anchors = _load_anchors(store, stmt_idx)
    ex = DeepSeekExtractor(anchors)
    logger.info("探测模型：%s @ %s", ex.model, "deepseek api")
    date = sorted(stmt_idx)[-1]
    doc = store.load_json(stmt_idx[date])
    prev = _prev_regular(stmt_idx, store, date, {})
    record = ex.score_statement(doc, _diff_entries(prev, doc))
    print(json.dumps({k: record[k] for k in
                      ("document_id", "overall_score", "confidence_overall",
                       "needs_human_review", "quote_violations", "model")},
                     ensure_ascii=False, indent=2))
    logger.info("用量：%s", ex.usage.report())


def run_full(statements_only: bool, workers: int, force: bool) -> None:
    store = S3RawStore()
    stmt_idx = _index(store, "statement")
    anchors = _load_anchors(store, stmt_idx)
    tasks = _collect_tasks(store, statements_only)
    if not force:
        tasks = [t for t in tasks if not _exists(store, _ds_key(t["doc"]))]
    logger.info("DeepSeek(%s) 待打分 %d 篇，并发 %d", DEEPSEEK_MODEL, len(tasks), workers)
    if not tasks:
        return

    ex = DeepSeekExtractor(anchors)

    def work(t):
        doc = t["doc"]
        record = (ex.score_statement(doc, t["diffs"]) if t["diffs"] is not None
                  else ex.score_minutes(doc))
        store.s3.put_object(
            Bucket=store.bucket, Key=_ds_key(doc),
            Body=json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8")
        return doc["document_id"], record["overall_score"]

    ok = err = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, t): t for t in tasks}
        for f in as_completed(futures):
            try:
                did, score = f.result()
                ok += 1
                logger.info("[%d/%d] %s -> %+d", ok + err, len(tasks), did, score)
            except Exception as e:  # noqa: BLE001 — 单篇失败不中断
                err += 1
                logger.error("[%d/%d] %s 失败: %s", ok + err, len(tasks),
                             futures[f]["doc"]["document_id"], str(e)[:200])
    logger.info("完成：成功 %d / 失败 %d", ok, err)
    logger.info("DeepSeek 用量：%s", ex.usage.report())


# ---------------------------------------------------------------- report


def _load_all(store: S3RawStore, prefix: str) -> dict[str, dict]:
    # 注意：S3 Prefix 是纯字符串前缀，"…/scores" 会同时命中 "…/scores_deepseek"。
    # 必须带尾斜杠区分两个目录。
    prefix = prefix.rstrip("/") + "/"
    out = {}
    paginator = store.s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=store.bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                d = store.load_json(o["Key"])
                out[d["document_id"]] = d
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


def run_report() -> None:
    store = S3RawStore()
    opus = _load_all(store, config.SCORES_PREFIX)
    ds = _load_all(store, DS_PREFIX)
    # 断言两边确实来自不同模型（防止前缀混淆这类静默错误）
    o_models = {d["model"] for d in opus.values()}
    d_models = {d["model"] for d in ds.values()}
    print(f"Opus 侧模型: {o_models} | DeepSeek 侧模型: {d_models}")
    if o_models & d_models:
        raise SystemExit("两侧记录的 model 字段有交集——数据装载有误，终止对比")
    common = sorted(set(opus) & set(ds))
    print(f"对齐样本：{len(common)} 篇（Opus {len(opus)} / DeepSeek {len(ds)}）\n")

    for doc_type in ("statement", "minutes"):
        ids = [i for i in common if opus[i]["doc_type"] == doc_type]
        if not ids:
            continue
        o = [opus[i]["overall_score"] for i in ids]
        d = [ds[i]["overall_score"] for i in ids]
        deltas = [abs(a - b) for a, b in zip(o, d)]
        print(f"== {doc_type}（{len(ids)} 篇）overall_score ==")
        print(f"  完全一致: {sum(x == 0 for x in deltas)}/{len(ids)}"
              f" ({sum(x == 0 for x in deltas)/len(ids):.0%})"
              f" | |Δ|≤1: {sum(x <= 1 for x in deltas)/len(ids):.0%}"
              f" | 平均|Δ|: {sum(deltas)/len(ids):.2f}"
              f" | Pearson r: {_pearson(o, d):.3f}")
        for dim in DIMS:
            od = [opus[i]["dimensions"][dim]["score"] for i in ids]
            dd = [ds[i]["dimensions"][dim]["score"] for i in ids]
            dl = [abs(a - b) for a, b in zip(od, dd)]
            print(f"  {dim:<18} |Δ|≤1: {sum(x <= 1 for x in dl)/len(ids):>4.0%}"
                  f"  平均|Δ|: {sum(dl)/len(ids):.2f}  r: {_pearson(od, dd):.3f}")

        # diff 方向一致率（仅声明；两边标注的是同一套引擎 diff，按位对齐）
        if doc_type == "statement":
            agree = total = 0
            for i in ids:
                for po, pd in zip(opus[i]["diffs_vs_previous"], ds[i]["diffs_vs_previous"]):
                    total += 1
                    agree += po["direction"] == pd["direction"]
            if total:
                print(f"  diff direction 一致率: {agree}/{total} ({agree/total:.0%})")

        qv_o = sum(1 for i in ids if opus[i]["quote_violations"])
        qv_d = sum(1 for i in ids if ds[i]["quote_violations"])
        hr_o = sum(1 for i in ids if opus[i]["needs_human_review"])
        hr_d = sum(1 for i in ids if ds[i]["needs_human_review"])
        print(f"  quote_violations: Opus {qv_o} / DeepSeek {qv_d}"
              f"  |  needs_human_review: Opus {hr_o} / DeepSeek {hr_d}\n")

    print("== 最大分歧（|Δ overall|≥3）==")
    rows = sorted(((abs(opus[i]['overall_score'] - ds[i]['overall_score']), i) for i in common),
                  reverse=True)
    shown = 0
    for delta, i in rows:
        if delta < 3 or shown >= 10:
            break
        print(f"  {i}: Opus {opus[i]['overall_score']:+d} vs DS {ds[i]['overall_score']:+d}")
        shown += 1
    if not shown:
        print("  （无）")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="macropulse.extraction.compare_cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="单篇探测：验证模型 ID 与 key")
    pr = sub.add_parser("run", help="DeepSeek 全量打分")
    pr.add_argument("--statements-only", action="store_true")
    pr.add_argument("--workers", type=int, default=6)
    pr.add_argument("--force", action="store_true", help="重打已存在的")
    sub.add_parser("report", help="输出对比报告")

    args = parser.parse_args(argv)
    if args.cmd == "probe":
        run_probe()
    elif args.cmd == "run":
        run_full(args.statements_only, args.workers, args.force)
    else:
        run_report()


if __name__ == "__main__":
    main(sys.argv[1:])
