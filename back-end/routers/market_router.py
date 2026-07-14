"""全球市场指数快报 —— 首页 LIVE 面板 / 顶栏 ticker 用。

复用 InsightSentry 同一把 token（option.config），拉一组固定指数的实时报价。
轻量内存缓存（60s），避免每次首页加载都打 API。代码均已 get_quotes 验过。
"""

import time
import logging

import requests
from fastapi import APIRouter, HTTPException

from option import config

router = APIRouter(prefix="/api/market", tags=["Market"])
logger = logging.getLogger(__name__)

# (代码, 中文名, 短标) —— 顺序即展示顺序
INDICES = [
    ("SP:SPX", "标普500", "SPX"),
    ("NASDAQ:IXIC", "纳斯达克", "NDX"),
    ("BINANCE:BTCUSDT", "比特币", "BTC"),
    ("COMEX:GC1!", "黄金", "XAU"),
    ("ICEUS:DX1!", "美元指数", "DXY"),
]
_CACHE = {"at": 0.0, "data": None}
_TTL = 60


def _fetch() -> list[dict]:
    codes = ",".join(c for c, _, _ in INDICES)
    r = requests.get(f"{config.IS_BASE_URL}/symbols/quotes", params={"codes": codes},
                     headers={"Authorization": f"Bearer {config.IS_TOKEN}"},
                     timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    rows = r.json().get("data", [])
    by_code = {row.get("code"): row for row in rows}
    out = []
    for code, cn, short in INDICES:
        row = by_code.get(code) or {}
        last = row.get("last_price")
        out.append({
            "code": code, "name": cn, "short": short,
            "last": last,
            "change_pct": row.get("change_percent"),
        })
    return out


@router.get("/indices")
async def indices():
    """一组全球指数实时报价（60s 缓存）。"""
    now = time.time()
    if _CACHE["data"] and now - _CACHE["at"] < _TTL:
        return {"indices": _CACHE["data"], "cached": True}
    try:
        data = _fetch()
    except Exception as e:  # noqa: BLE001
        logger.warning("indices 拉取失败: %r", e)
        if _CACHE["data"]:
            return {"indices": _CACHE["data"], "stale": True}
        raise HTTPException(503, "指数报价暂不可用")
    _CACHE["at"], _CACHE["data"] = now, data
    return {"indices": data, "cached": False}
