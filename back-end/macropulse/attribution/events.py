"""事件时间与方向约定。

FOMC 声明固定在会议结束日 14:00 America/New_York 释放（声明页原文写
"For release at 2:00 p.m. EDT"）。用 zoneinfo 把 ET 转 UTC，自动处理夏令时
（夏 EDT=UTC-4 → 18:00 UTC；冬 EST=UTC-5 → 19:00 UTC）。

方向约定（XAU）：鹰派（更紧/加息预期↑→美元↑）→ 黄金跌；鸽派 → 黄金涨。
即 鹰鸽分数 与 XAU 收益 预期负相关。命中 = sign(收益) == -sign(分数)。
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
FOMC_RELEASE_LOCAL_HOUR = 14  # 2:00 p.m. ET


def release_utc(meeting_date: str) -> datetime:
    """会议日（YYYY-MM-DD）→ 声明释放时刻（UTC，tz-aware）。"""
    y, m, d = (int(x) for x in meeting_date.split("-"))
    local = datetime(y, m, d, FOMC_RELEASE_LOCAL_HOUR, 0, tzinfo=_ET)
    return local.astimezone(timezone.utc)


def release_ts_ms(meeting_date: str) -> int:
    """声明释放时刻的毫秒级 Unix 时间戳（对齐 xau_candles_1m.open_time）。"""
    return int(release_utc(meeting_date).timestamp() * 1000)


# 各标的对鹰派的预期价格方向（鹰派时该标的应往哪走）：
#   黄金 XAU：紧缩→实际利率↑→金价跌      → 与分数负相关 (-1)
#   美元 DXY：紧缩→美元走强→指数涨        → 与分数正相关 (+1)
#   2年期 US2Y：紧缩→加息预期↑→收益率涨   → 与分数正相关 (+1)
INSTRUMENT_DIR = {"XAU": -1, "DXY": +1, "US2Y": +1}
INSTRUMENT_TABLE = {"XAU": "xau_candles_1m", "DXY": "dxy_candles_1m", "US2Y": "us2y_candles_1m"}


def expected_return_sign(hawk_score: int, instrument: str = "XAU") -> int:
    """给定鹰鸽分数与标的，该标的收益的预期方向。中性分→0。"""
    s = (hawk_score > 0) - (hawk_score < 0)  # sign
    return s * INSTRUMENT_DIR.get(instrument, -1)
