"""Diff 引擎 CLI —— 从 S3 拉相邻声明做红线对比。

  python -m macropulse.diff_cli --latest                # 最近两期
  python -m macropulse.diff_cli --pair 2026-03-18 2026-04-29
  python -m macropulse.diff_cli --all                   # 所有相邻对，逐对打印 summary
  python -m macropulse.diff_cli --latest --json         # 输出结构化 JSON 而非红线文本
"""

from __future__ import annotations

import json
import sys
import argparse

from macropulse.s3_store import S3RawStore
from macropulse.diff import diff_statements, render_text


def _index_by_date(store: S3RawStore) -> dict[str, str]:
    """meeting_date -> s3 key。"""
    out = {}
    for key in store.list_statements():
        # 文件名形如 fed_statement_2026-04-29.json
        date = key.rsplit("fed_statement_", 1)[-1].replace(".json", "")
        out[date] = key
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog="macropulse.diff_cli")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--latest", action="store_true", help="对比最近两期声明")
    g.add_argument("--pair", nargs=2, metavar=("FROM", "TO"), help="指定两期会议日")
    g.add_argument("--all", action="store_true", help="逐对打印所有相邻对的 summary")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    args = parser.parse_args(argv)

    store = S3RawStore()
    idx = _index_by_date(store)
    dates = sorted(idx)
    if len(dates) < 2:
        print("声明不足两期，无法 diff", file=sys.stderr)
        sys.exit(1)

    if args.all:
        for a, b in zip(dates, dates[1:]):
            d = diff_statements(store.load_json(idx[a]), store.load_json(idx[b]))
            s = d.summary
            print(f"{a} → {b} | 改 {s['modified']} 增 {s['added']} 删 {s['removed']} "
                  f"未变 {s['unchanged']}")
        return

    if args.latest:
        a, b = dates[-2], dates[-1]
    else:
        a, b = args.pair
        if a not in idx or b not in idx:
            print(f"找不到会议日：{a if a not in idx else b}（可选：{dates}）", file=sys.stderr)
            sys.exit(1)

    d = diff_statements(store.load_json(idx[a]), store.load_json(idx[b]))
    if args.json:
        print(json.dumps(d.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(d))


if __name__ == "__main__":
    main(sys.argv[1:])
