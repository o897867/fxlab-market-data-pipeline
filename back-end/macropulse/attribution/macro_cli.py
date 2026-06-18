"""宏观数据事件 CLI。

  python -m macropulse.attribution.macro_cli backfill-fred [--start 2021-01-01]
  python -m macropulse.attribution.macro_cli poll-calendar [--weeks 1]
  python -m macropulse.attribution.macro_cli backtest [--type NFP] [--json]
  python -m macropulse.attribution.macro_cli show

backfill-fred  : FRED 历史 → macro_releases（代理 surprise，铺满 N）
poll-calendar  : InsightSentry 日历 → macro_releases（真 consensus，覆盖前向）
backtest       : 读 macro_releases + 三标的价格，跑命中率
show           : 看表里现有事件计数
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

from macropulse import config
from macropulse.attribution import macro_events, fred_source, calendar_source, backtest

_IS_TOKEN = ("eyJhbGciOiJIUzI1NiJ9.eyJ1dWlkIjoic3V5aW5nY2luQGdtYWlsLmNvbSIsInBsYW4i"
             "OiJ1bHRyYSIsIm5ld3NmZWVkX2VuYWJsZWQiOnRydWUsIndlYnNvY2tldF9zeW1ib2xzIjo1"
             "LCJ3ZWJzb2NrZXRfY29ubmVjdGlvbnMiOjF9.6aA_ND-9NmZI2-8mILRJeZDLt9Y6skrtsNbzP0FeQVI")


def _conn():
    return sqlite3.connect(config.PRICE_DB_PATH)


def cmd_backfill_fred(args):
    rows = fred_source.build_all_history(start=args.start)
    conn = _conn()
    try:
        n = macro_events.upsert(conn, rows)
    finally:
        conn.close()
    print(f"✅ FRED 历史回填 {n} 行（start={args.start}）")
    cmd_show(args)


def cmd_poll_calendar(args):
    token = os.getenv("INSIGHTSENTRY_TOKEN", _IS_TOKEN)
    raw = calendar_source.fetch_calendar(weeks=args.weeks, bearer_token=token)
    conn = _conn()
    try:
        rows = calendar_source.build_rows(conn, raw)
        n = macro_events.upsert(conn, rows)
    finally:
        conn.close()
    print(f"✅ 日历前向 {n} 行（拉取 {len(raw)} 条原始事件，weeks={args.weeks}）")
    for r in rows:
        print(f"   {r['event_type']:8} {r['ref_month']} act={r['actual']} "
              f"fc={r['forecast']} surprise={r['surprise']}")


def cmd_backtest(args):
    conn = _conn()
    try:
        types = (args.type,) if args.type else None
        result = backtest.run_macro(conn=conn, event_types=types)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"\n宏观归因  事件 N={result['n_events']}  跳过(无价){result['n_skipped_no_price']}")
    print(f"标的方向 {result['directions']}")
    print(f"⚠️  {result['surprise_note']}\n")
    for et, blk in result["by_event_type"].items():
        print(f"── {et}  (N={blk['n_events']}) ──")
        for w in result["windows_min"]:
            c = blk["aggregate"]["consensus"][str(w)]
            print(f"   {w:>4}m  consensus 命中 {c['hits']}/{c['n_directional']} "
                  f"= {c['hit_rate']}  pearson={c['pearson_score_vs_return']}")
    print(f"\n── POOLED（所有事件） ──")
    for w in result["windows_min"]:
        c = result["aggregate_pooled"]["consensus"][str(w)]
        print(f"   {w:>4}m  consensus 命中 {c['hits']}/{c['n_directional']} = {c['hit_rate']}")


def cmd_show(args):
    conn = _conn()
    try:
        macro_events.ensure_table(conn)
        rows = conn.execute(
            f"SELECT event_type, surprise_source, COUNT(*), MIN(ref_month), MAX(ref_month) "
            f"FROM {macro_events.TABLE} GROUP BY event_type, surprise_source "
            f"ORDER BY event_type, surprise_source").fetchall()
    finally:
        conn.close()
    print("\nmacro_releases 现有：")
    for et, src, n, lo, hi in rows:
        print(f"   {et:8} {src:11} {n:>3} 期  [{lo} → {hi}]")
    if not rows:
        print("   (空)")


def main():
    p = argparse.ArgumentParser(prog="macro_cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    bf = sub.add_parser("backfill-fred")
    bf.add_argument("--start", default="2021-01-01")
    bf.set_defaults(func=cmd_backfill_fred)

    pc = sub.add_parser("poll-calendar")
    pc.add_argument("--weeks", type=int, default=1)
    pc.set_defaults(func=cmd_poll_calendar)

    bt = sub.add_parser("backtest")
    bt.add_argument("--type", default=None, help="只看某事件类型，如 NFP")
    bt.add_argument("--json", action="store_true")
    bt.set_defaults(func=cmd_backtest)

    sh = sub.add_parser("show")
    sh.set_defaults(func=cmd_show)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
