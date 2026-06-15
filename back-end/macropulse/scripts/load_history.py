#!/usr/bin/env python3
"""一次性历史加载：把 .tmp/hist 下载的月度 JSON 灌入 SQLite。

- IS:DXY  → dxy_candles_1m
- IS:US02Y → us2y_candles_1m（close = 收益率%）
- COMEX:GC1! → xau_candles_1m 的 2021→2025-10 缺口（按月取活跃前月合约）

下载文件 time 为秒，统一 ×1000 转毫秒，对齐现有 xau_candles_1m 的 open_time。
INSERT OR IGNORE 保证幂等、不覆盖既有数据。
"""

import os
import json
import glob
import sqlite3
from collections import defaultdict

HIST = "/root/shopback/ShopBack_PP/.tmp/hist"
DB = "/root/shopback/ShopBack_PP/back-end/shopback_data.db"


def ensure_table(conn, name):
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {name} (
        open_time INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL)""")


def rows_from_file(path):
    d = json.load(open(path))
    for s in d.get("series", []):
        yield (
            int(s["time"]) * 1000,
            s.get("open"), s.get("high"), s.get("low"), s["close"], s.get("volume", 0) or 0,
        )


def load_index(conn, sym_dir, table):
    ensure_table(conn, table)
    files = sorted(glob.glob(f"{HIST}/{sym_dir}/1m/*.json"))
    n = 0
    for f in files:
        rows = list(rows_from_file(f))
        conn.executemany(f"INSERT OR IGNORE INTO {table} VALUES (?,?,?,?,?,?)", rows)
        n += len(rows)
    conn.commit()
    cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"{table}: 灌入 {n:,} 行 → 表内 {cnt:,} 行（去重后）")


def load_gold_gap(conn):
    """按月挑活跃合约（行数最多者=前月），填 xau_candles_1m 的缺口。"""
    # month -> {contract_path: bar_count}
    by_month = defaultdict(dict)
    for f in glob.glob(f"{HIST}/COMEX_GC/*/1m/*.json"):
        month = os.path.basename(f).replace(".json", "")  # YYYY-MM
        d = json.load(open(f))
        by_month[month][f] = len(d.get("series", []))

    before = conn.execute("SELECT COUNT(*) FROM xau_candles_1m").fetchone()[0]
    n = 0
    for month in sorted(by_month):
        # 该月活跃合约 = 行数最多的那个
        active = max(by_month[month], key=by_month[month].get)
        rows = list(rows_from_file(active))
        conn.executemany("INSERT OR IGNORE INTO xau_candles_1m VALUES (?,?,?,?,?,?)", rows)
        n += len(rows)
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM xau_candles_1m").fetchone()[0]
    print(f"xau_candles_1m: 灌入 {n:,} 行 → 新增 {after-before:,}（{before:,} → {after:,}）")


def main():
    conn = sqlite3.connect(DB)
    load_index(conn, "IS_DXY", "dxy_candles_1m")
    load_index(conn, "IS_US02Y", "us2y_candles_1m")
    load_gold_gap(conn)
    # 覆盖范围报告
    import datetime as dt
    f = lambda ms: dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    for t in ("xau_candles_1m", "dxy_candles_1m", "us2y_candles_1m"):
        lo, hi, c = conn.execute(f"SELECT MIN(open_time),MAX(open_time),COUNT(*) FROM {t}").fetchone()
        print(f"  {t}: {c:,} 行, {f(lo)} → {f(hi)}")
    conn.close()


if __name__ == "__main__":
    main()
