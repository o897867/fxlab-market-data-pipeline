"""模型 C CLI：意外 → SOFR 利率预期重定价。

  python -m macropulse.attribution.rate_cli run [--json]

读 S3 的 FOMC 鹰鸽分数 + SQLite 的宏观 surprise，对齐 SOFR 隐含利率反应，
输出方向命中率（头条）+ 敏感度 β/R²（样本内）。
"""

from __future__ import annotations

import json
import sqlite3
import argparse

from dotenv import load_dotenv

load_dotenv()

from macropulse import config
from macropulse.s3_store import S3RawStore
from macropulse.attribution import rate_model

WINDOWS = [15, 60, 1440]


def _load_fomc_scores(store) -> list[dict]:
    out = []
    paginator = store.s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=store.bucket,
                                   Prefix=f"{config.SCORES_PREFIX}/statement/"):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                d = store.load_json(o["Key"])
                out.append({"date": d["meeting_date"], "overall_score": d["overall_score"]})
    return out


def _report(s: dict):
    wl = {"15": "15min", "60": "1h", "1440": "1d"}
    print("█" * 68)
    print(f"模型 C · 意外 → SOFR 利率预期重定价   事件 N={s['n_events']}")
    print("█" * 68)
    for w in s["windows_min"]:
        b = s["by_window"][str(w)]
        dp = b["directional_pooled"]
        ols = b["ols_pooled"] or {}
        print(f"\n── {wl[str(w)]}  (有SOFR价 N={b['n']}) ──")
        hr = f"{dp['hit_rate']:.0%}" if dp["hit_rate"] is not None else "n/a"
        print(f"  方向命中(pooled): {dp['hits']}/{dp['n']} = {hr}   "
              f"β={ols.get('beta_bp','—')}bp/SD  R²={ols.get('r2','—')}(样本内)")
        for et, blk in b["by_event_type"].items():
            d = blk["directional"]
            if d["n"] == 0:
                continue
            o = blk["ols"] or {}
            h = f"{d['hit_rate']:.0%}" if d["hit_rate"] is not None else "n/a"
            print(f"    {et:8} 命中 {d['hits']}/{d['n']}={h:>4}  β={o.get('beta_bp','—')}bp/SD")
    print(f"\n⚠️  {s['note']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="macropulse.attribution.rate_cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    store = S3RawStore()
    fomc = _load_fomc_scores(store)
    conn = sqlite3.connect(config.PRICE_DB_PATH)
    try:
        rows = rate_model.build_dataset(conn, fomc, WINDOWS)
    finally:
        conn.close()
    result = rate_model.summarize(rows, WINDOWS)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _report(result)


if __name__ == "__main__":
    main()
