"""XAU 价格访问 + 窗口收益。

从 SQLite xau_candles_1m 读 1 分钟 K 线（open_time 毫秒、close 价）。
基准价 p0 = t0 当时（at-or-before）那根 K 线的 close；窗口价 p1 = t0+W 的
at-or-before close。收益 = (p1-p0)/p0 * 100（百分比）。

黄金近 24 小时交易但有周末缺口：若最近 K 线距目标时刻超过 max_lag_min，
判该窗口不可用（返回 None），避免拿隔了几小时的陈价算收益。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from macropulse import config


@dataclass
class Candle:
    open_time: int  # ms
    close: float


class InstrumentPrices:
    """轻封装：任意 *_candles_1m 表。可注入 sqlite3.Connection（测试用内存库）。"""

    def __init__(self, conn: sqlite3.Connection = None, table: str = "xau_candles_1m"):
        self._own = conn is None
        self.conn = conn or sqlite3.connect(config.PRICE_DB_PATH)
        self.table = table

    def close(self):
        if self._own:
            self.conn.close()

    def coverage(self) -> tuple[Optional[int], Optional[int]]:
        row = self.conn.execute(
            f"SELECT MIN(open_time), MAX(open_time) FROM {self.table}").fetchone()
        return (row[0], row[1]) if row else (None, None)

    def candle_at_or_before(self, ts_ms: int, max_lag_min: int = 180) -> Optional[Candle]:
        """t≤ts_ms 的最近一根 K 线；若滞后超过 max_lag_min 则视为不可用。"""
        row = self.conn.execute(
            f"SELECT open_time, close FROM {self.table} "
            f"WHERE open_time <= ? ORDER BY open_time DESC LIMIT 1",
            (ts_ms,)).fetchone()
        if not row:
            return None
        if (ts_ms - row[0]) > max_lag_min * 60_000:
            return None
        return Candle(open_time=row[0], close=float(row[1]))

    def window_return(self, t0_ms: int, window_min: int,
                      max_lag_min: int = 180) -> Optional[dict]:
        """t0 到 t0+window 的 XAU 收益（%）。任一端缺价返回 None。"""
        c0 = self.candle_at_or_before(t0_ms, max_lag_min)
        c1 = self.candle_at_or_before(t0_ms + window_min * 60_000, max_lag_min)
        if not c0 or not c1 or c0.close == 0:
            return None
        return {
            "window_min": window_min,
            "p0": round(c0.close, 4),
            "p1": round(c1.close, 4),
            "return_pct": round((c1.close - c0.close) / c0.close * 100, 4),
            "p1_lag_min": round((t0_ms + window_min * 60_000 - c1.open_time) / 60_000, 1),
        }


# 向后兼容旧名
XauPrices = InstrumentPrices
