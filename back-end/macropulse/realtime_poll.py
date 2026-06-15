"""DXY / US2Y 前向数据轮询器（REST，与 XAU 同机制，不碰 WS）。

每 60s 拉 IS:DXY、IS:US02Y 的最近 1m bar，upsert 进 dxy/us2y_candles_1m。
纯 additive：独立后台任务，不触碰现有 XAUDataManager 与那条单 WS 连接，
零风险于线上黄金流。指数无 badj/settlement（futures-only），故省略。

由 fapi 在启动时调 start_pollers(api_key, db_path) 拉起。
"""

import asyncio
import sqlite3
import logging
from urllib.parse import quote

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.insightsentry.com/v3"
POLL_INTERVAL = 60

# symbol -> 落库表
INSTRUMENTS = {
    "IS:DXY": "dxy_candles_1m",
    "IS:US02Y": "us2y_candles_1m",
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


async def _poll_one(api_key: str, db_path: str, symbol: str, table: str):
    _ensure_table(db_path, table)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                candles = await _fetch(session, api_key, symbol)
                if candles:
                    _upsert(db_path, table, candles)
                    logger.debug("📈 %s 轮询 %d 条, 最新 close=%s", symbol, len(candles), candles[-1]["close"])
            except Exception as e:  # noqa: BLE001 — 单轮失败不中断
                logger.warning("%s 轮询失败: %r", symbol, e)
            await asyncio.sleep(POLL_INTERVAL)


def start_pollers(api_key: str, db_path: str) -> list:
    """为每个标的起一个轮询任务。返回 task 列表（供停止）。"""
    tasks = [asyncio.create_task(_poll_one(api_key, db_path, sym, tab))
             for sym, tab in INSTRUMENTS.items()]
    logger.info("✅ DXY/US2Y 前向轮询已启动（REST，%ds 间隔）", POLL_INTERVAL)
    return tasks
