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


@router.get("/impact")
async def impact(symbol: str = Query(...), expiry: str | None = None):
    """面板④影响：期权怎么影响正股（事件预期/磁吸位/GEX，带可信度标签）。"""
    return _guard(panels.impact, symbol, expiry)


@router.get("/term-structure")
async def term_structure(symbol: str = Query(...)):
    """面板⑤期限结构：近月 vs 远月 ATM IV 曲线 + 形态。"""
    return _guard(panels.term_structure, symbol)


@router.get("/iv-rank")
async def iv_rank(symbol: str = Query(...)):
    """面板⑥ IV Rank：现在期权比过去(最多一年)贵还是便宜的客观统计（带冷启动标注）。"""
    return _guard(panels.iv_rank, symbol)


@router.get("/pc-trend")
async def pc_trend(symbol: str = Query(...)):
    """面板⑦ 情绪：看跌/看涨 OI 比 + 5 日趋势（防守升温/降温，客观统计）。"""
    return _guard(panels.pc_trend, symbol)


@router.get("/daily-report")
async def daily_report():
    """全 watchlist 概览：每票一张精简卡，临近财报置顶、其余按 IV Rank 降序。首页用。"""
    return _guard(panels.daily_report)


@router.get("/iv-board")
async def iv_board():
    """watchlist IV Rank 排行（降序）——哪些票现在定价最贵。"""
    return _guard(panels.iv_rank_board)


@router.get("/earnings-calendar")
async def earnings_calendar():
    """未来两周 watchlist 财报排期。"""
    return _guard(panels.earnings_calendar)


@router.get("/spark")
async def spark(symbol: str = Query(...)):
    """band chart 走势线：近期日线收盘 + 今日涨跌%（读 HV 缓存，不实时调 API）。"""
    return _guard(panels.spark, symbol)


@router.get("/expiries")
async def expiries(symbol: str = Query(...)):
    """该标的可选到期日列表 + 默认选择。"""
    return _guard(panels.expiries, symbol)
