#!/usr/bin/env python3
"""
ShopBack CFD Trading Platform - 核心应用
专注于：实时行情、交易计算器、随机抽卦、周报思维导图、开户指南
"""

import logging
import uvicorn
import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# ETH Kalman filter imports
from eth_kalman_model import ETHKalmanModelManager
from binance_eth_data import BinanceDataManager

# XAU (Gold) data imports
from insightsentry_xau_data import XAUDataManager

# 导入配置
from config import (
    APP_NAME, VERSION, DEBUG, ALLOWED_ORIGINS,
    ENABLE_LEGACY_FEATURES, HOST, PORT, RELOAD, DATABASE_PATH
)

# 导入数据库初始化
from database import init_database, init_legacy_tables, check_database_health, get_db_connection

# 导入核心路由
from routers.calculator_router import router as calculator_router
from routers.fortune_router import router as fortune_router

# 配置日志
logging.basicConfig(level=logging.INFO if not DEBUG else logging.DEBUG)
logger = logging.getLogger(__name__)

# ============= ETH 数据与预测开关 =============
# 数据获取开启，预测计算关闭（仅拉取并存储行情）
ETH_DATA_ENABLED = True
ETH_PREDICTIONS_ENABLED = False
eth_model_manager: ETHKalmanModelManager = None
eth_data_manager: BinanceDataManager = None
eth_ws_clients: set = set()  # WebSocket clients for real-time updates

# ============= XAU (Gold) Data 全局变量 =============
XAU_DATA_ENABLED = True  # Enable XAU data fetching
xau_data_manager: XAUDataManager = None
xau_ws_clients: set = set()  # WebSocket clients for XAU updates

# ============= Financial News 全局变量 =============
NEWS_ENABLED = True  # Enable financial news feed
news_client = None  # NewsWebSocketClient instance

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global eth_model_manager, eth_data_manager, xau_data_manager, news_client

    # 启动时初始化
    logger.info("🚀 启动 ShopBack CFD Trading Platform")

    try:
        # 初始化核心数据库表
        init_database()
        logger.info("✅ 核心数据库初始化完成")

        # 可选：初始化Legacy功能表
        if ENABLE_LEGACY_FEATURES:
            init_legacy_tables()
            logger.info("✅ Legacy功能表初始化完成")
        else:
            logger.info("⏸️  Legacy功能已禁用")

        # 检查数据库健康状态
        health = check_database_health()
        logger.info(f"📊 数据库状态: {health}")

        # Initialize ETH data (without predictions)
        if ETH_DATA_ENABLED:
            try:
                logger.info("🔌 初始化 ETH 数据流 (Binance WS)...")
                eth_model_manager = ETHKalmanModelManager() if ETH_PREDICTIONS_ENABLED else None
                eth_data_manager = BinanceDataManager(model_manager=eth_model_manager)

                # Start ETH data manager in background
                asyncio.create_task(startup_eth_data())
                logger.info("✅ ETH 数据服务已启动")
            except Exception as e:
                logger.error(f"❌ ETH 数据服务初始化失败: {e}")

        # Initialize XAU data manager
        if XAU_DATA_ENABLED:
            try:
                logger.info("💰 初始化 XAU 数据服务 (InsightSentry)...")
                # InsightSentry Bearer Token
                bearer_token = "eyJhbGciOiJIUzI1NiJ9.eyJ1dWlkIjoic3V5aW5nY2luQGdtYWlsLmNvbSIsInBsYW4iOiJ1bHRyYSIsIm5ld3NmZWVkX2VuYWJsZWQiOnRydWUsIndlYnNvY2tldF9zeW1ib2xzIjo1LCJ3ZWJzb2NrZXRfY29ubmVjdGlvbnMiOjF9.6aA_ND-9NmZI2-8mILRJeZDLt9Y6skrtsNbzP0FeQVI"
                xau_data_manager = XAUDataManager(bearer_token=bearer_token)

                # Start XAU data polling in background
                asyncio.create_task(startup_xau_data())
                logger.info("✅ XAU 数据服务已启动 (InsightSentry)")

                # MacroPulse: DXY/US2Y 前向轮询（REST，独立后台任务，不碰 WS）
                from macropulse.realtime_poll import start_pollers
                start_pollers(bearer_token, DATABASE_PATH)

                # MacroPulse: 宏观数据日历前向轮询（CPI/PCE/非农 consensus，每日）
                from macropulse.attribution.calendar_source import start_macro_poller
                start_macro_poller(bearer_token, DATABASE_PATH)
            except Exception as e:
                logger.error(f"❌ XAU 数据服务初始化失败: {e}")

        # Initialize Financial News service
        if NEWS_ENABLED:
            try:
                from insightsentry_news import NewsWebSocketClient
                from routers.news_router import broadcast_news_to_clients
                import os

                # InsightSentry API Key (same as XAU)
                insightsentry_key = "eyJhbGciOiJIUzI1NiJ9.eyJ1dWlkIjoic3V5aW5nY2luQGdtYWlsLmNvbSIsInBsYW4iOiJ1bHRyYSIsIm5ld3NmZWVkX2VuYWJsZWQiOnRydWUsIndlYnNvY2tldF9zeW1ib2xzIjo1LCJ3ZWJzb2NrZXRfY29ubmVjdGlvbnMiOjF9.6aA_ND-9NmZI2-8mILRJeZDLt9Y6skrtsNbzP0FeQVI"
                # 新闻摘要已迁移至 DeepSeek（NEWS_LLM_KEY_ENV 可改回 OPENAI_API_KEY，
                # 需与 insightsentry_news.py 顶部的 NEWS_LLM_BASE_URL/MODEL 配套切换）
                llm_key_env = os.environ.get("NEWS_LLM_KEY_ENV", "DEEPSEEK_API_KEY")
                llm_key = os.environ.get(llm_key_env, "")
                if not llm_key:
                    logger.warning(f"⚠️  {llm_key_env} not set, news summarization will fail")

                news_client = NewsWebSocketClient(
                    api_key=insightsentry_key,
                    openai_api_key=llm_key,
                    db_path=DATABASE_PATH,
                    news_callback=broadcast_news_to_clients
                )

                # Start news client in background
                asyncio.create_task(news_client.start())
                logger.info("✅ 金融新闻服务已启动 (InsightSentry + DeepSeek)")
            except Exception as e:
                logger.error(f"❌ 金融新闻服务初始化失败: {e}")

    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}")
        raise

    yield

    # 关闭时清理
    logger.info("🛑 关闭 ShopBack CFD Trading Platform")

    # Cleanup ETH resources
    if ETH_DATA_ENABLED and eth_data_manager:
        try:
            await eth_data_manager.stop()
            logger.info("✅ ETH 数据服务已停止")
        except Exception as e:
            logger.error(f"❌ ETH 数据服务停止失败: {e}")

    # Cleanup XAU resources
    if XAU_DATA_ENABLED and xau_data_manager:
        try:
            await xau_data_manager.stop()
            logger.info("✅ XAU 数据服务已停止")
        except Exception as e:
            logger.error(f"❌ XAU 数据服务停止失败: {e}")

    # Cleanup News resources
    if NEWS_ENABLED and news_client:
        try:
            await news_client.stop()
            logger.info("✅ 金融新闻服务已停止")
        except Exception as e:
            logger.error(f"❌ 金融新闻服务停止失败: {e}")

# 创建FastAPI应用
app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description="专注于CFD经纪商对比和交易计算的一体化平台",
    lifespan=lifespan
)

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-User-Id"],
)

# 静态文件服务
static_dir = "/root/shopback/ShopBack_PP/back-end/static"
try:
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    logger.info(f"✅ 静态文件服务已配置: {static_dir}")
except Exception as e:
    logger.warning(f"⚠️  静态文件服务配置失败: {e}")

# ============= 核心功能路由 =============

# 交易计算器功能
app.include_router(
    calculator_router,
    prefix="/api/leverage",
    tags=["Trading Calculator"],
)

# 随机抽卦功能
app.include_router(
    fortune_router,
    tags=["Fortune - 随机抽卦"]
)

# 金融新闻功能
from routers.news_router import router as news_router
app.include_router(
    news_router,
    tags=["Financial News"],
)

# ============= Analytics 数据分析 =============
from routers.analytics_router import router as analytics_router
app.include_router(analytics_router, tags=["Analytics"])

# ============= MacroPulse 央行通讯解析 =============
from routers.macro_router import router as macro_router
app.include_router(macro_router, tags=["MacroPulse"])

# ============= Weekly Mindmap 模块 =============
from weekly.router import router as weekly_router
app.include_router(weekly_router)

# ============= Legacy功能路由 (可选) =============

if ENABLE_LEGACY_FEATURES:
    logger.info("🔄 启用Legacy功能")

    # 这里可以添加Legacy路由
    # from legacy.shopback_router import router as shopback_router
    # from legacy.eth_router import router as eth_router
    # app.include_router(shopback_router, prefix="/api/legacy/shopback", tags=["Legacy - ShopBack"])
    # app.include_router(eth_router, prefix="/api/legacy/eth", tags=["Legacy - ETH"])

# ============= 基础路由 =============

@app.get("/", summary="API根路径")
async def root():
    """API根路径，返回应用信息"""
    return {
        "app": APP_NAME,
        "version": VERSION,
        "status": "running",
        "core_features": [
            "Real-time Quotes (XAU/ETH)",
            "Trading Calculator",
            "Fortune Divination",
            "Weekly Mindmap",
            "Broker Guide"
        ],
        "endpoints": {
            "xau": "/api/xau/current-price",
            "eth": "/api/eth/current-price",
            "calculator": "/api/leverage/calculate",
            "fortune": "/api/fortune",
            "weekly": "/api/weekly/reports"
        }
    }

@app.get("/api/health", summary="系统健康检查")
async def health_check():
    """系统健康检查"""
    try:
        db_health = check_database_health()

        return {
            "status": "healthy",
            "app": APP_NAME,
            "version": VERSION,
            "database": db_health,
            "features": {
                "core_features": ["xau", "eth", "calculator", "fortune", "weekly"],
                "legacy_enabled": ENABLE_LEGACY_FEATURES
            }
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e)
            }
        )

@app.get("/api/info", summary="应用信息")
async def app_info():
    """获取应用详细信息"""
    return {
        "name": APP_NAME,
        "version": VERSION,
        "debug": DEBUG,
        "features": {
            "core": {
                "realtime_quotes": {
                    "description": "XAU/ETH 实时行情与 WebSocket 推送",
                    "endpoints": ["/api/xau/current-price", "/api/eth/current-price", "/ws/xau/price-updates"]
                },
                "trading_calculator": {
                    "description": "杠杆交易计算器和风险分析",
                    "endpoints": ["/api/leverage/calculate"]
                },
                "fortune": {
                    "description": "随机抽卦",
                    "endpoints": ["/api/fortune"]
                },
                "weekly_mindmap": {
                    "description": "周报思维导图",
                    "endpoints": ["/api/weekly/reports"]
                }
            }
        },
        "configuration": {
            "cors_origins": ALLOWED_ORIGINS,
            "debug_mode": DEBUG
        }
    }

# ============= ETH Kalman Filter 端点 =============

async def startup_xau_data():
    """Initialize XAU data with InsightSentry (REST + WebSocket)"""
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        logger.info("XAU data subsystem disabled; skipping startup")
        return
    try:
        # Start data manager (stores to database only, frontend polls via API)
        await xau_data_manager.start()
        logger.info("✅ Started XAU data service (InsightSentry WebSocket -> DB, frontend polls)")
    except Exception as e:
        logger.error(f"Failed to start XAU data manager: {e}")

async def startup_eth_data():
    """Initialize ETH data stream; optionally enable predictions"""
    if not ETH_DATA_ENABLED or eth_data_manager is None:
        logger.info("ETH data subsystem disabled; skipping startup")
        return
    try:
        # Optional predictions callback
        async def broadcast_candle_updates(candle: dict):
            if not ETH_PREDICTIONS_ENABLED or eth_model_manager is None:
                return None
            try:
                predictions = await eth_data_manager.on_new_candle(candle)
                if predictions and eth_ws_clients:
                    await broadcast_eth_update({
                        "type": "update",
                        "candle": candle,
                        "predictions": predictions,
                        "model_state": eth_model_manager.get_model_metrics()
                    })
                return predictions
            except Exception as e:
                logger.error(f"Error in broadcast_candle_updates: {e}")
                return None

        # Initialize data and start WS
        await eth_data_manager.initialize()
        await eth_data_manager.fetcher.start_websocket_stream(
            broadcast_candle_updates if ETH_PREDICTIONS_ENABLED else None
        )
        logger.info("Started ETH data manager with Binance WebSocket")
    except Exception as e:
        logger.error(f"Failed to start ETH data manager: {e}")

@app.get("/api/eth/current-price", summary="Get current ETH price and model state")
async def get_eth_current_price():
    """Get current ETH price with model state"""
    if not ETH_DATA_ENABLED or eth_data_manager is None:
        raise HTTPException(status_code=503, detail="ETH data service is temporarily disabled")
    try:
        current_price = eth_data_manager.fetcher.get_current_price()
        model_metrics = eth_model_manager.get_model_metrics() if ETH_PREDICTIONS_ENABLED and eth_model_manager else None

        return {
            "current_price": current_price,
            "model_state": model_metrics,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/eth/predictions", summary="Get ETH price predictions")
async def get_eth_predictions():
    """Get ETH price predictions for multiple horizons"""
    if not ETH_PREDICTIONS_ENABLED or eth_model_manager is None or eth_data_manager is None:
        raise HTTPException(status_code=503, detail="ETH prediction service is temporarily disabled")
    try:
        # Get latest candle
        candles = eth_data_manager.fetcher.get_recent_candles(2)
        if len(candles) < 2:
            return {"error": "Insufficient data for predictions"}

        # Generate predictions
        predictions = eth_model_manager.update_with_new_candle(candles[-1])

        return predictions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/eth/candles-3m", summary="Get historical 3-minute candles")
async def get_eth_candles(limit: int = Query(100, le=500)):
    """Get historical 3-minute ETH candles"""
    if not ETH_DATA_ENABLED or eth_data_manager is None:
        raise HTTPException(status_code=503, detail="ETH data service is temporarily disabled")
    try:
        candles = eth_data_manager.fetcher.get_recent_candles(limit)
        return {
            "candles": candles,
            "count": len(candles)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/eth/model/half-life", summary="Adjust Kalman filter half-life")
async def set_eth_half_life(half_life_candles: int = Query(..., ge=4, le=6)):
    """Adjust the half-life parameter (4-6 candles, i.e., 12-18 minutes)"""
    if not ETH_PREDICTIONS_ENABLED or eth_model_manager is None:
        raise HTTPException(status_code=503, detail="ETH prediction service is temporarily disabled")
    try:
        eth_model_manager.model.set_half_life(half_life_candles)
        eth_model_manager.save_state()

        return {
            "half_life_candles": half_life_candles,
            "half_life_minutes": half_life_candles * 3,
            "delta": eth_model_manager.model.delta
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/eth/model/metrics", summary="Get model performance metrics")
async def get_eth_model_metrics():
    """Get detailed model metrics and parameters"""
    if not ETH_PREDICTIONS_ENABLED or eth_model_manager is None:
        raise HTTPException(status_code=503, detail="ETH prediction service is temporarily disabled")
    try:
        metrics = eth_model_manager.get_model_metrics()
        state = eth_model_manager.model.get_state()

        return {
            "metrics": metrics,
            "state": state,
            "config": {
                "half_life_candles": eth_model_manager.model.half_life,
                "c_level": eth_model_manager.model.c_level,
                "c_trend": eth_model_manager.model.c_trend,
                "r0_mult": eth_model_manager.model.r0_mult
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/eth/kalman-updates")
async def eth_kalman_websocket(websocket: WebSocket):
    """WebSocket for real-time ETH Kalman model updates"""
    await websocket.accept()
    if not ETH_PREDICTIONS_ENABLED or eth_model_manager is None or eth_data_manager is None:
        await websocket.send_json({
            "type": "disabled",
            "message": "ETH prediction service is temporarily disabled"
        })
        await websocket.close()
        return

    eth_ws_clients.add(websocket)

    try:
        # Send initial state
        current_price = eth_data_manager.fetcher.get_current_price()
        initial_data = {
            "type": "initial",
            "current_price": current_price,
            "model_state": eth_model_manager.get_model_metrics()
        }
        await websocket.send_json(initial_data)
        logger.info(f"New WebSocket client connected. Total clients: {len(eth_ws_clients)}")

        # Keep connection alive with periodic ping
        ping_interval = 30  # Send ping every 30 seconds
        last_ping = time.time()

        while True:
            try:
                # Check if we should send a ping
                current_time = time.time()
                if current_time - last_ping > ping_interval:
                    await websocket.send_json({"type": "ping", "timestamp": current_time})
                    last_ping = current_time

                # Try to receive data with timeout
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # No data received, continue loop

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in WebSocket loop: {e}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected. Remaining clients: {len(eth_ws_clients) - 1}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in eth_ws_clients:
            eth_ws_clients.remove(websocket)
        try:
            await websocket.close()
        except:
            pass

async def broadcast_eth_update(update_data: dict):
    """Broadcast ETH model updates to all WebSocket clients"""
    if not ETH_PREDICTIONS_ENABLED:
        return
    disconnected = set()
    for ws in eth_ws_clients:
        try:
            await ws.send_json(update_data)
        except:
            disconnected.add(ws)

    # Remove disconnected clients
    for ws in disconnected:
        eth_ws_clients.remove(ws)

# ============= XAU (Gold) Price Data API =============

@app.get("/api/xau/current-price", summary="Get current XAU (gold) price")
async def get_xau_current_price():
    """Get current gold price"""
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        raise HTTPException(status_code=503, detail="XAU data service is temporarily disabled")
    try:
        current_price = xau_data_manager.get_current_price()
        candle_count = xau_data_manager.get_candle_count()
        latest_time = xau_data_manager.get_latest_candle_time()

        return {
            "current_price": current_price,
            "total_candles": candle_count,
            "latest_update": datetime.fromtimestamp(latest_time/1000).isoformat() if latest_time else None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/xau/quote", summary="Get top-of-book quote for XAU")
async def get_xau_quote():
    """获取 XAU 顶层盘口（最优买卖价）"""
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        raise HTTPException(status_code=503, detail="XAU data service is temporarily disabled")
    quote = xau_data_manager.get_latest_quote()
    if not quote:
        raise HTTPException(status_code=404, detail="No quote data available yet")
    return {
        "code": quote.get("code"),
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "bid_size": quote.get("bid_size"),
        "ask_size": quote.get("ask_size"),
        "timestamp": quote.get("timestamp"),
        "server_time": time.time()
    }

@app.get("/api/xau/quote/history", summary="Get recent top-of-book quote history for XAU")
async def get_xau_quote_history(limit: int = Query(100, le=300)):
    """获取最近的盘口顶层报价历史"""
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        raise HTTPException(status_code=503, detail="XAU data service is temporarily disabled")
    history = xau_data_manager.get_quote_history(limit=limit)
    if not history:
        raise HTTPException(status_code=404, detail="No quote history available")
    return {
        "count": len(history),
        "quotes": history
    }

@app.get("/api/xau/candles", summary="Get historical XAU candles")
async def get_xau_candles(
    limit: int = Query(100, le=1000),
    interval: str = Query("1m", regex="^(1m|3m|5m)$")
):
    """
    Get historical gold price candles

    Args:
        limit: Number of candles to fetch
        interval: Candle interval - "1m" for 1-minute, "3m" for 3-minute, or "5m" for 5-minute

    For 3m and 5m intervals, data is automatically aggregated from 1-minute candles
    using proper OHLC logic (first open, max high, min low, last close).
    """
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        raise HTTPException(status_code=503, detail="XAU data service is temporarily disabled")
    try:
        if interval == "5m":
            # Trigger aggregation and fetch 5m candles
            await xau_data_manager.aggregate_to_5m()
            candles = xau_data_manager.get_recent_candles_5m(limit)
        elif interval == "3m":
            # Trigger aggregation and fetch 3m candles
            await xau_data_manager.aggregate_to_3m()
            candles = xau_data_manager.get_recent_candles_3m(limit)
        else:  # 1m
            candles = xau_data_manager.get_recent_candles("1m", limit)

        return {
            "candles": candles,
            "count": len(candles),
            "symbol": "GC=F (Gold Futures)",
            "interval": interval
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/xau/stats", summary="Get XAU data statistics")
async def get_xau_stats():
    """Get XAU data collection statistics"""
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        raise HTTPException(status_code=503, detail="XAU data service is temporarily disabled")
    try:
        candle_count = xau_data_manager.get_candle_count()
        latest_time = xau_data_manager.get_latest_candle_time()
        current_price = xau_data_manager.get_current_price()

        return {
            "total_candles": candle_count,
            "current_price": current_price,
            "latest_candle_time": datetime.fromtimestamp(latest_time/1000).isoformat() if latest_time else None,
            "data_range_hours": (candle_count / 60) if candle_count > 0 else 0,
            "is_running": xau_data_manager.is_running
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/xau/indicators", summary="Get XAU technical indicators")
async def get_xau_indicators(
    limit: int = Query(500, le=1000),
    interval: str = Query("1m", regex="^(1m|3m|5m)$")
):
    """
    Calculate and return technical indicators for XAU data

    Args:
        limit: Number of candles to fetch
        interval: Candle interval - "1m" for 1-minute, "3m" for 3-minute, or "5m" for 5-minute

    Indicators included:
    - MACD (Moving Average Convergence Divergence)
    - RSI (Relative Strength Index)
    - SMA14 (Simple Moving Average 14)
    - EMA20 (Exponential Moving Average 20)
    """
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        raise HTTPException(status_code=503, detail="XAU data service is temporarily disabled")

    try:
        # Get candles based on interval
        if interval == "5m":
            await xau_data_manager.aggregate_to_5m()
            candles = xau_data_manager.get_recent_candles_5m(limit)
        elif interval == "3m":
            await xau_data_manager.aggregate_to_3m()
            candles = xau_data_manager.get_recent_candles_3m(limit)
        else:  # 1m
            candles = xau_data_manager.get_recent_candles(limit)

        if not candles:
            raise HTTPException(status_code=404, detail="No candle data available")

        # Extract price data
        import numpy as np
        prices = np.array([float(c['close']) for c in candles])

        # Calculate indicators using shared TechnicalIndicators class
        macd_result = TechnicalIndicators.calculate_macd(prices, fast_period=12, slow_period=26, signal_period=9)
        rsi_values = TechnicalIndicators.calculate_rsi(prices, period=14)
        sma14_values = TechnicalIndicators.calculate_sma(prices, period=14)
        ema20_values = TechnicalIndicators.calculate_ema(prices, period=20)

        # Convert numpy arrays to lists and handle NaN values
        def to_list_with_none(arr):
            return [None if np.isnan(v) else float(v) for v in arr]

        macd_list = to_list_with_none(macd_result['macd'])
        signal_list = to_list_with_none(macd_result['signal'])
        histogram_list = to_list_with_none(macd_result['histogram'])
        rsi_list = to_list_with_none(rsi_values)
        sma14_list = to_list_with_none(sma14_values)
        ema20_list = to_list_with_none(ema20_values)

        # Calculate metadata
        valid_rsi = [v for v in rsi_list if v is not None]
        valid_macd = [v for v in macd_list if v is not None]
        valid_sma14 = [v for v in sma14_list if v is not None]
        valid_ema20 = [v for v in ema20_list if v is not None]

        return {
            "candles": candles,
            "indicators": {
                "macd": {
                    "macd": macd_list,
                    "signal": signal_list,
                    "histogram": histogram_list
                },
                "rsi": rsi_list,
                "sma14": sma14_list,
                "ema20": ema20_list
            },
            "metadata": {
                "total_candles": len(candles),
                "rsi_values_count": len(valid_rsi),
                "macd_values_count": len(valid_macd),
                "sma14_values_count": len(valid_sma14),
                "ema20_values_count": len(valid_ema20),
                "rsi_current": valid_rsi[-1] if valid_rsi else None,
                "macd_current": valid_macd[-1] if valid_macd else None,
                "sma14_current": valid_sma14[-1] if valid_sma14 else None,
                "ema20_current": valid_ema20[-1] if valid_ema20 else None,
            },
            "symbol": "GC=F (Gold Futures)",
            "interval": interval
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating XAU indicators: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/xau/validity", summary="Analyze XAU indicator validity")
async def analyze_xau_validity(
    limit: int = Query(500, le=1000),
    interval: str = Query("1m", regex="^(1m|3m|5m)$"),
    minutes: int = Query(10080, le=43200),  # Default 7 days in minutes, max 30 days
    macd_win: int = Query(15),  # Longer window for XAU
    macd_thr: float = Query(0.0008),  # Lower threshold for XAU (0.08%)
    rsi_win: int = Query(15),  # Longer window for XAU
    rsi_thr: float = Query(0.0008),  # Lower threshold for XAU (0.08%)
    use_adaptive: bool = Query(True),
    atr_multiplier: float = Query(0.6)  # Lower multiplier for XAU
):
    """
    Analyze XAU indicator validity and generate trading signals

    Args:
        limit: Number of candles to fetch
        interval: Candle interval - "1m" for 1-minute, "3m" for 3-minute, or "5m" for 5-minute
        minutes: Time range in minutes to filter results (default 10080 = 7 days)
        macd_win: MACD follow-through window
        macd_thr: MACD threshold (or base threshold if adaptive)
        rsi_win: RSI reversal window
        rsi_thr: RSI threshold (or base threshold if adaptive)
        use_adaptive: Use ATR-based adaptive thresholds
        atr_multiplier: ATR multiplier for adaptive threshold calculation
    """
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        raise HTTPException(status_code=503, detail="XAU data service is temporarily disabled")

    try:
        # Get candles based on interval
        if interval == "5m":
            await xau_data_manager.aggregate_to_5m()
            candles = xau_data_manager.get_recent_candles_5m(limit)
        elif interval == "3m":
            await xau_data_manager.aggregate_to_3m()
            candles = xau_data_manager.get_recent_candles_3m(limit)
        else:  # 1m
            candles = xau_data_manager.get_recent_candles(limit)

        if not candles:
            raise HTTPException(status_code=404, detail="No candle data available")

        # Calculate all indicators for XAU
        indicators = calculate_all_indicators(candles)

        # Prepare parameters with adaptive threshold support
        # Optimized for XAU's lower volatility
        params = {
            'macd_win': macd_win,
            'macd_thr': macd_thr,
            'rsi_win': rsi_win,
            'rsi_thr': rsi_thr,
            'use_adaptive': use_adaptive,
            'atr_multiplier': atr_multiplier,
            'macd_hist': 3,
            'rsi_return_buffer': 3,
            # MA parameters optimized for XAU
            'ma_tol': 0.001,  # Tighter tolerance (0.1%) for XAU
            'ma_win': 10,  # Longer confirmation window
            'ma_thr': 0.002,  # Lower bounce threshold (0.2%)
            # RSI parameters for XAU
            'rsi_overbought': 75,  # Higher overbought level for XAU
            'rsi_oversold': 25  # Lower oversold level for XAU
        }

        # Analyze validity using same function as ETH
        validity_results = analyze_validity(candles, indicators, params)

        # Filter by period (convert minutes to days for existing filter function)
        days = minutes / 1440.0  # Convert minutes to days
        filtered_results = filter_validity_by_period(validity_results, candles, days)

        validity_summary = filtered_results

        return {
            'symbol': 'GC=F',
            'interval': interval,
            'time_range_minutes': minutes,
            'validity_summary': validity_summary,
            'parameters_used': params
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing XAU validity: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/xau/price-updates")
async def xau_price_websocket(websocket: WebSocket):
    """WebSocket for real-time XAU price updates"""
    await websocket.accept()
    if not XAU_DATA_ENABLED or xau_data_manager is None:
        await websocket.send_json({
            "type": "disabled",
            "message": "XAU data service is temporarily disabled"
        })
        await websocket.close()
        return

    xau_ws_clients.add(websocket)

    try:
        # Send initial state
        current_price = xau_data_manager.fetcher.get_current_price()
        recent_candles = xau_data_manager.fetcher.get_recent_candles(10)

        initial_data = {
            "type": "initial",
            "current_price": current_price,
            "recent_candles": recent_candles,
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send_json(initial_data)
        logger.info(f"New XAU WebSocket client connected. Total clients: {len(xau_ws_clients)}")

        # Keep connection alive with periodic ping
        ping_interval = 30  # Send ping every 30 seconds
        last_ping = time.time()

        while True:
            try:
                # Check if we should send a ping
                current_time = time.time()
                if current_time - last_ping > ping_interval:
                    await websocket.send_json({"type": "ping", "timestamp": current_time})
                    last_ping = current_time

                # Try to receive data with timeout
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # No data received, continue loop

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in XAU WebSocket loop: {e}")
                break

    except WebSocketDisconnect:
        logger.info(f"XAU WebSocket client disconnected. Remaining clients: {len(xau_ws_clients) - 1}")
    except Exception as e:
        logger.error(f"XAU WebSocket error: {e}")
    finally:
        if websocket in xau_ws_clients:
            xau_ws_clients.remove(websocket)
        try:
            await websocket.close()
        except:
            pass

async def broadcast_xau_update(update_data: dict):
    """Broadcast XAU price updates to all WebSocket clients"""
    if not XAU_DATA_ENABLED:
        return
    disconnected = set()
    for ws in xau_ws_clients:
        try:
            await ws.send_json(update_data)
        except:
            disconnected.add(ws)

    # Remove disconnected clients
    for ws in disconnected:
        xau_ws_clients.remove(ws)

# ============= 异常处理 =============

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """404错误处理"""
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": f"路径 {request.url.path} 不存在",
            "suggestion": "请查看 /api/info 获取可用的API端点"
        }
    )

@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """500错误处理"""
    logger.error(f"服务器错误: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "服务器内部错误，请稍后重试"
        }
    )

# ============= 应用启动 =============

if __name__ == "__main__":
    logger.info(f"🎯 启动模式: {'开发' if DEBUG else '生产'}")
    logger.info(f"🌐 CORS允许源: {ALLOWED_ORIGINS}")
    logger.info(f"🔧 Legacy功能: {'启用' if ENABLE_LEGACY_FEATURES else '禁用'}")

    uvicorn.run(
        "fapi:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
        log_level="debug" if DEBUG else "info"
    )
