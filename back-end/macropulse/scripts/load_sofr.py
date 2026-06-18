#!/usr/bin/env python3
"""一次性历史加载：3 个月 SOFR 期货 → sofr_candles_1m。

下载的是季度合约（CME:SR3{H/M/U/Z}{YYYY}）的月度 1m JSON，按月挑活跃合约
（行数最多者=当月前月、最流动）灌库，与黄金缺口同套路。

**存原始期货价格**（close=结算/收盘价），忠于源、与其他 *_candles_1m 表一致。
隐含政策利率 = 100 − price，在归因/展示层算（鹰派→预期利率↑→期货价↓，
故 INSTRUMENT_DIR['SOFR'] = -1，与黄金同号）。

time 秒 ×1000 → 毫秒，对齐 open_time。INSERT OR IGNORE 幂等。
2021 年 ZIRP 期 SOFR 钉在 ~0.05% 基本不动，对数据无反应——故只回填 2022→今。
"""

import os
import json
import glob
import sqlite3
import datetime as dt
from collections import defaultdict

HIST = "/root/shopback/ShopBack_PP/back-end/data/sofr_history"
DB = "/root/shopback/ShopBack_PP/back-end/shopback_data.db"
TABLE = "sofr_candles_1m"


def ensure_table(conn):
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        open_time INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL)""")


def rows_from_file(path):
    d = json.load(open(path))
    for s in d.get("series", []):
        if s.get("close") is None:
            continue
        yield (
            int(s["time"]) * 1000,
            s.get("open"), s.get("high"), s.get("low"), s["close"], s.get("volume", 0) or 0,
        )


def main():
    conn = sqlite3.connect(DB)
    ensure_table(conn)

    # month(YYYY-MM) -> {contract_file: bar_count}；跨合约挑活跃前月
    by_month = defaultdict(dict)
    for f in glob.glob(f"{HIST}/CME_SR3*/1m/*.json"):
        month = os.path.basename(f).replace(".json", "")
        d = json.load(open(f))
        by_month[month][f] = len(d.get("series", []))

    before = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    n = 0
    for month in sorted(by_month):
        active = max(by_month[month], key=by_month[month].get)
        rows = list(rows_from_file(active))
        conn.executemany(f"INSERT OR IGNORE INTO {TABLE} VALUES (?,?,?,?,?,?)", rows)
        n += len(rows)
        contract = active.split("/CME_")[1].split("/")[0]
        print(f"  {month}: 活跃 CME_{contract} ({by_month[month][active]} bars)")
    conn.commit()

    after, lo, hi = conn.execute(
        f"SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM {TABLE}").fetchone()
    f = lambda ms: dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    print(f"\n{TABLE}: 灌入 {n:,} 行 → 表内 {after:,}（新增 {after-before:,}）")
    print(f"  覆盖 {f(lo)} → {f(hi)}")
    # 隐含利率合理性抽样（首尾）
    p0 = conn.execute(f"SELECT close FROM {TABLE} ORDER BY open_time ASC LIMIT 1").fetchone()[0]
    p1 = conn.execute(f"SELECT close FROM {TABLE} ORDER BY open_time DESC LIMIT 1").fetchone()[0]
    print(f"  隐含利率：最早 {round(100-p0,3)}%  最新 {round(100-p1,3)}%")
    conn.close()


if __name__ == "__main__":
    main()
