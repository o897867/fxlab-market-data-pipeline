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


def _report_deep(d: dict):
    print("█" * 68)
    print("模型 C 深化 · 主窗口方向命中(+Wilson CI) + walk-forward 样本外")
    print("█" * 68)
    wl = {15: "15min", 60: "1h", 1440: "1d"}
    for et, b in d["by_signal"].items():
        ins = b["in_sample_directional"]
        oos = b["oos"]
        ci = ins.get("ci95", (None, None))
        star = " ★真>50%" if ins.get("beats_coin") else ""
        print(f"\n── {et}  主窗口 {wl[b['primary_window']]} ──")
        print(f"  样本内方向命中 {ins['hits']}/{ins['n']} = "
              f"{ins['hit_rate']:.0%}  CI95[{ci[0]:.0%},{ci[1]:.0%}]{star}"
              if ins["hit_rate"] is not None else "  样本内: n/a")
        if oos["n"]:
            oci = oos["ci95"]
            print(f"  样本外(WF)     命中 {oos['dir_hit']:.0%} (N={oos['n']}) "
                  f"CI95[{oci[0]:.0%},{oci[1]:.0%}]  R²_vs随机游走={oos['r2_vs_zero']}")
        else:
            print("  样本外: 数据不足")
    po = d["pooled_oos"]
    if po["n"]:
        pci = po["ci95"]
        print(f"\n══ POOLED 样本外（全信号汇总）══")
        print(f"  方向命中 {po['dir_hit']:.0%} (N={po['n']}) CI95[{pci[0]:.0%},{pci[1]:.0%}]"
              f"  R²_vs随机游走={po['r2_vs_zero']}")
    print(f"\n⚠️  {d['note']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="macropulse.attribution.rate_cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("--json", action="store_true")
    pd_ = sub.add_parser("deep")
    pd_.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    store = S3RawStore()
    fomc = _load_fomc_scores(store)
    conn = sqlite3.connect(config.PRICE_DB_PATH)
    try:
        rows = rate_model.build_dataset(conn, fomc, WINDOWS)
    finally:
        conn.close()
    if args.cmd == "deep":
        result = rate_model.deepen(rows)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "", end="")
        if not args.json:
            _report_deep(result)
        return
    result = rate_model.summarize(rows, WINDOWS)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _report(result)


if __name__ == "__main__":
    main()
