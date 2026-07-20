"""DXY / US2Y 前向数据轮询器（REST，与 XAU 同机制，不碰 WS）。

默认每小时拉一次 IS:DXY、IS:US02Y、CME:SR31! 覆盖整小时的 1m bar，upsert 进对应表。
纯 additive：独立后台任务，不触碰现有 XAUDataManager 与那条单 WS 连接，
零风险于线上黄金流。指数无 badj/settlement（futures-only），故省略。

由 fapi 在启动时调 start_pollers(api_key, db_path) 拉起。
"""

import os
import asyncio
import sqlite3
import logging
from urllib.parse import quote

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.insightsentry.com/v3"
# 不需要实时：默认每小时拉一次，每次取覆盖整小时的 1m bar（dp = bar 数，不是小数位——
# 已实测 dp 只影响返回条数、不影响价格精度）。_upsert 按 open_time INSERT OR REPLACE 去重，
# 重叠 bar 自动合并，所以降频不丢任何一分钟数据。
#   60s×3 只 = 4320 次/天  →  3600s×3 只 = 72 次/天（÷60）。
POLL_INTERVAL = int(os.getenv("MACRO_POLL_INTERVAL", "3600"))
_DP = int(os.getenv("MACRO_POLL_DP", str(POLL_INTERVAL // 60 + 10)))  # 每请求 bar 数 = 间隔分钟 + 10 缓冲

# symbol -> 落库表
INSTRUMENTS = {
    "IS:DXY": "dxy_candles_1m",
    "IS:US02Y": "us2y_candles_1m",
    "CME:SR31!": "sofr_candles_1m",
}


def _ensure_table(db_path: str, table: str):
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            open_time INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL)""")


def _upsert(db_path: str, table: str, candles: list):
    if not candles:
        return
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} (open_time, open, high, low, close, volume) VALUES (?,?,?,?,?,?)",
            [(c["open_time"], c["open"], c["high"], c["low"], c["close"], c.get("volume", 0)) for c in candles])


_TIMEOUT = aiohttp.ClientTimeout(total=20)


async def _fetch(session, api_key: str, symbol: str, dp: int = 2) -> list:
    url = f"{BASE_URL}/symbols/{quote(symbol, safe='')}/series"
    params = {"bar_type": "minute", "bar_interval": "1", "dp": str(dp), "long_poll": "false"}
    headers = {"Authorization": f"Bearer {api_key}"}
    async with session.get(url, params=params, headers=headers, timeout=_TIMEOUT) as r:
        if r.status != 200:
            logger.warning("DXY/US2Y 轮询 %s -> HTTP %s", symbol, r.status)
            return []
        data = await r.json()
        out = []
        for bar in data.get("series", []):
            ts = bar.get("time", 0)
            ts_ms = ts * 1000 if ts < 10_000_000_000 else ts
            out.append({
                "open_time": (ts_ms // 60000) * 60000,
                "open": float(bar.get("open", bar.get("close", 0))),
                "high": float(bar.get("high", bar.get("close", 0))),
                "low": float(bar.get("low", bar.get("close", 0))),
                "close": float(bar.get("close", 0)),
                "volume": float(bar.get("volume", 0) or 0),
            })
        return out


async def _poll_one(api_key: str, db_path: str, symbol: str, table: str, dp: int = 2):
    _ensure_table(db_path, table)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                candles = await _fetch(session, api_key, symbol, dp=dp)
                if candles:
                    _upsert(db_path, table, candles)
                    logger.debug("📈 %s 轮询 %d 条, 最新 close=%s", symbol, len(candles), candles[-1]["close"])
            except Exception as e:  # noqa: BLE001 — 单轮失败不中断
                logger.warning("%s 轮询失败: %r", symbol, e)
            await asyncio.sleep(POLL_INTERVAL)


def start_pollers(api_key: str, db_path: str) -> list:
    """为每个标的起一个轮询任务。返回 task 列表（供停止）。"""
    tasks = [asyncio.create_task(_poll_one(api_key, db_path, sym, tab, _DP))
             for sym, tab in INSTRUMENTS.items()]
    logger.info("✅ DXY/US2Y/SOFR 前向轮询已启动（REST，%ds 间隔，dp=%d bar/请求 → %d 次/天）",
                POLL_INTERVAL, _DP, len(INSTRUMENTS) * 86400 // POLL_INTERVAL)
    return tasks
