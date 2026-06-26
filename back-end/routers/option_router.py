"""OptionLens 服务层：三面板端点，返回「人话标题 + 原始数字」。

读 dbt-duckdb 的 mart_*（option.panels）。数据缺失（库未建/标的无快照）返回 available=false，
前端据此显示占位，不报 500。
"""

import logging

from fastapi import APIRouter, Query, HTTPException

from option import panels, config

router = APIRouter(prefix="/api/option", tags=["OptionLens"])
logger = logging.getLogger(__name__)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FileNotFoundError:
        raise HTTPException(503, "期权分析库尚未生成（先跑快照 + dbt run）")
    except Exception as e:  # noqa: BLE001
        logger.exception("option panel 失败")
        raise HTTPException(500, f"option panel failed: {e}")


@router.get("/symbols")
async def symbols():
    """v1 锁定的标的列表。"""
    return {"symbols": config.DEFAULT_SYMBOLS}


@router.get("/expected-move")
async def expected_move(symbol: str = Query(...), expiry: str | None = None):
    """面板①预期范围：到某到期日大概率落在的价格区间。"""
    return _guard(panels.expected_move, symbol, expiry)


@router.get("/probability")
async def probability(symbol: str = Query(...), price: float = Query(...),
                      expiry: str | None = None):
    """面板②问问市场：目标价的市场定价概率。"""
    return _guard(panels.probability, symbol, price, expiry)


@router.get("/distribution")
async def distribution(symbol: str = Query(...), expiry: str | None = None):
    """面板③押注分布：各价位 OI 墙 + max_pain + 看跌看涨比。"""
    return _guard(panels.distribution, symbol, expiry)
