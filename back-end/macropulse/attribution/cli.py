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
    print("█" * 64)
    print(f"FOMC 鹰鸽分数 → XAU 价格反应归因  (instrument={result['instrument']})")
    print(f"已打分声明 {result['n_scored_statements']} | 有价格覆盖 {result['n_attributed']} "
          f"| 超出 XAU 历史被跳过 {result['n_skipped_no_price']}")
    print("█" * 64)

    print("\n逐事件（鹰鸽分 vs 各窗口 XAU 收益%，✓=方向命中 ✗=未命中 ·=中性无预期）:")
    hdr = "  日期        分  " + "".join(f"{_WLABEL.get(str(w), str(w)):>12}" for w in result["windows_min"])
    print(hdr)
    for e in result["events"]:
        line = f"  {e['meeting_date']}  {e['overall_score']:+d}  "
        for w in result["windows_min"]:
            r = e["reactions"].get(str(w))
            if r is None:
                line += f"{'—':>12}"
            else:
                mark = "·" if r["hit"] is None else ("✓" if r["hit"] else "✗")
                line += f"{r['return_pct']:+8.2f}{mark:>2} "[:12].rjust(12)
        print(line)

    print("\n聚合（按窗口）:")
    for w in result["windows_min"]:
        a = result["aggregate"][str(w)]
        hr = f"{a['hit_rate']:.0%}" if a["hit_rate"] is not None else "n/a"
        r = a["pearson_score_vs_return"]
        rstr = f"{r:+.2f}" if r is not None else "n/a"
        print(f"  {_WLABEL.get(str(w), str(w)):>6}: 方向命中 {a['hits']}/{a['n_directional']} ({hr}) "
              f"| Pearson(分数,收益)={rstr} "
              f"| 鹰均收益={a['mean_return_hawkish']} 鸽均收益={a['mean_return_dovish']}")

    print("\n⚠️ 局限：仅 XAU 单标的，样本 N 极小（受 XAU 1m 历史起点限制），"
          "且未控制同日其他数据发布等混杂因素。结论仅作方法论演示，不构成统计显著性。")


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
