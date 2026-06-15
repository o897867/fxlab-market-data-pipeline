"""归因回测 CLI。

  python -m macropulse.attribution.cli run [--dry-run]

run：计算全部有 XAU 覆盖的声明事件归因，打印报告，落 S3
     analysis/macro/fed/attribution/backtest.json（--dry-run 只打印不写）。
"""

from __future__ import annotations

import json
import sys
import logging
import argparse
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from macropulse import config
from macropulse.s3_store import S3RawStore
from macropulse.attribution import backtest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("macropulse.attribution")

_WLABEL = {"15": "15min", "60": "1h", "1440": "1d"}


def _report(result: dict) -> None:
    insts = result["instruments"]
    print("█" * 70)
    print(f"FOMC 鹰鸽分数 → 价格反应归因  标的={'/'.join(insts)}")
    print(f"已打分声明 {result['n_scored_statements']} | 有价格覆盖 {result['n_attributed']} "
          f"| 超出历史跳过 {result['n_skipped_no_price']}")
    print(f"方向约定（鹰派时）：" + "  ".join(
        f"{i}{'↑' if result['directions'][i] > 0 else '↓'}" for i in insts))
    print("█" * 70)

    print("\n聚合命中率（按 标的×窗口）：")
    hdr = "  标的     " + "".join(f"{_WLABEL.get(str(w), str(w)):>14}" for w in result["windows_min"])
    print(hdr)
    for inst in insts + ["consensus"]:
        cells = ""
        for w in result["windows_min"]:
            a = result["aggregate"][inst][str(w)]
            hr = f"{a['hit_rate']:.0%}" if a["hit_rate"] is not None else "n/a"
            r = a["pearson_score_vs_return"]
            cells += f"{a['hits']}/{a['n_directional']} {hr:>4} r{r if r is not None else '—'}".rjust(14)
        label = "一致性" if inst == "consensus" else inst
        print(f"  {label:<7}{cells}")

    print("\n逐事件 1d 收益%（✓命中 ✗未中 ·中性）：")
    for e in result["events"]:
        parts = []
        for inst in insts:
            r = e["reactions"][inst].get("1440")
            if r is None:
                parts.append(f"{inst} —")
            else:
                mark = "·" if r["hit"] is None else ("✓" if r["hit"] else "✗")
                parts.append(f"{inst} {r['return_pct']:+.2f}{mark}")
        print(f"  {e['meeting_date']} {e['overall_score']:+d} | " + " | ".join(parts))

    print("\n⚠️ 局限：样本仍小、仅三个标的、未控同日其他数据发布等混杂因素；"
          "consensus 的三标的观测彼此相关，非独立。结论作方法论演示，不构成统计显著性。")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="macropulse.attribution.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run", help="计算归因并落 S3")
    pr.add_argument("--dry-run", action="store_true", help="只打印不写 S3")
    args = parser.parse_args(argv)

    store = S3RawStore()
    result = backtest.run(store)
    result["computed_at"] = datetime.now(timezone.utc).isoformat()
    _report(result)

    if not args.cmd == "run" or args.dry_run:
        return
    key = f"{config.ATTRIBUTION_PREFIX}/backtest.json"
    store.s3.put_object(
        Bucket=store.bucket, Key=key,
        Body=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8")
    logger.info("已写 s3://%s/%s", store.bucket, key)


if __name__ == "__main__":
    main(sys.argv[1:])
