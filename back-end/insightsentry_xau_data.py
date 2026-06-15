#!/usr/bin/env python3
"""
InsightSentry XAU/USD (Gold) Data Fetcher
使用 InsightSentry API 获取 COMEX:GC1! 黄金期货数据

数据流程：
1. 启动时：通过 REST API 获取历史数据并去重
2. 运行时：通过 WebSocket 接收实时数据流
"""

import asyncio
import aiohttp
import websockets
import json
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable
import logging
import time
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InsightSentryXAUDataFetcher:
    """
    XAU/USD 历史数据获取器（InsightSentry REST API）

    功能：
    - 获取历史K线数据
    - 数据去重
    - 数据库存储和管理
    """

    # API 配置
    BASE_URL = "https://api.insightsentry.com/v3"
    SYMBOL = "COMEX:GC1!"  # 黄金期货代码
    MAX_DP = 2000  # 单次请求最多 datapoints（用户侧要求：保持 2000）

    # 时间间隔（毫秒）
    INTERVAL_1M_MS = 60000
    INTERVAL_3M_MS = 180000
    INTERVAL_5M_MS = 300000

    def __init__(self, db_path: str = "shopback_data.db", bearer_token: Optional[str] = None):
        self.db_path = db_path
        self.bearer_token = bearer_token
        self.error_count = 0
        self.last_error_log_time = 0
        self.error_log_interval = 60  # 错误日志间隔（秒）

        if not self.bearer_token:
            raise ValueError("InsightSentry Bearer Token is required")

        self.session = None
        self.init_database()

    def init_database(self):
        """初始化数据库表（复用现有结构）"""
        with sqlite3.connect(self.db_path) as conn:
            # 1分钟K线表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS xau_candles_1m (
                    open_time INTEGER PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL
                )
            """)

            # 3分钟K线表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS xau_candles_3m (
                    open_time INTEGER PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL
                )
            """)

            # 5分钟K线表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS xau_candles_5m (
                    open_time INTEGER PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL
                )
            """)

            # 创建索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_xau_candles_1m_open_time
                ON xau_candles_1m(open_time DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_xau_candles_3m_open_time
                ON xau_candles_3m(open_time DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_xau_candles_5m_open_time
                ON xau_candles_5m(open_time DESC)
            """)

            logger.info("✅ XAU candles tables initialized (1m, 3m, 5m)")

    async def get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close_session(self):
        """关闭 aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()

    def floor_to_1m(self, timestamp_ms: int) -> int:
        """向下取整到1分钟"""
        return (timestamp_ms // self.INTERVAL_1M_MS) * self.INTERVAL_1M_MS

    def floor_to_3m(self, timestamp_ms: int) -> int:
        """向下取整到3分钟"""
        return (timestamp_ms // self.INTERVAL_3M_MS) * self.INTERVAL_3M_MS

    def floor_to_5m(self, timestamp_ms: int) -> int:
        """向下取整到5分钟"""
        return (timestamp_ms // self.INTERVAL_5M_MS) * self.INTERVAL_5M_MS

    def get_latest_candle_time(self, table: str = "xau_candles_1m") -> Optional[int]:
        """获取数据库中最新的K线时间"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"SELECT MAX(open_time) FROM {table}")
            result = cursor.fetchone()
            return result[0] if result and result[0] else None

    def get_candle_count(self, table: str = "xau_candles_1m") -> int:
        """获取K线总数"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            return cursor.fetchone()[0]

    def upsert_candles_batch(self, candles: List[Dict], table: str = "xau_candles_1m"):
        """批量存储K线数据（自动去重）"""
        if not candles:
            return

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(f"""
                INSERT OR REPLACE INTO {table}
                (open_time, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [(
                c['open_time'],
                c['open'],
                c['high'],
                c['low'],
                c['close'],
                c.get('volume', 0)
            ) for c in candles])

    async def fetch_recent_data(self, dp: int = 1000) -> List[Dict]:
        """
        使用 dp 限制的 REST API 获取最近的 K 线数据

        Args:
            dp: 需要的 datapoint 数量（最大 30000）
        """
        try:
            session = await self.get_session()
            dp = min(max(dp, 1), self.MAX_DP)

            url = f"{self.BASE_URL}/symbols/COMEX%3AGC1!/series"
            params = {
                "bar_type": "minute",
                "bar_interval": "1",
                "extended": "true",
                "dadj": "false",
                "badj": "true",
                "dp": str(dp),
                "long_poll": "false",
                "settlement": "true"
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.bearer_token}"
            }

            logger.info(f"📥 Fetching latest {dp} datapoints via InsightSentry series API...")

            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()

                    candles = []
                    bars = data.get('series', data.get('bars', data if isinstance(data, list) else []))

                    for bar in bars:
                        timestamp = bar.get('time', bar.get('timestamp', bar.get('t', 0)))
                        timestamp_ms = timestamp * 1000 if timestamp < 10000000000 else timestamp
                        open_time_floored = self.floor_to_1m(timestamp_ms)

                        candles.append({
                            "open_time": open_time_floored,
                            "timestamp": timestamp_ms // 1000,
                            "open": float(bar.get('open', bar.get('o', 0))),
                            "high": float(bar.get('high', bar.get('h', 0))),
                            "low": float(bar.get('low', bar.get('l', 0))),
                            "close": float(bar.get('close', bar.get('c', 0))),
                            "volume": float(bar.get('volume', bar.get('v', 0)))
                        })

                    logger.info(f"✅ Fetched {len(candles)} candles from InsightSentry")
                    return candles

                error_text = await response.text()
                logger.error(f"❌ API Error {response.status}: {error_text}")
                return []

        except Exception as e:
            logger.error(f"❌ Error fetching recent data: {e}")
            return []

    async def initialize_with_dp_backfill(self, max_dp: int = MAX_DP):
        """
        启动时根据数据库缺口计算需要回灌的 datapoints 数量，并进行去重存储
        """
        logger.info("🔄 Initializing XAU data with dp-limited backfill...")

        latest_db_time = self.get_latest_candle_time()
        existing_count = self.get_candle_count()

        if latest_db_time:
            latest_dt = datetime.fromtimestamp(latest_db_time / 1000)
            logger.info(f"📊 Database: {existing_count} records, latest: {latest_dt}")
        else:
            logger.info("📊 Database is empty - first initialization")

        # 计算缺口（按 1m bar 粒度，使用向上取整避免遗漏）
        now_ms = int(time.time() * 1000)
        if latest_db_time:
            import math
            gap_minutes = max(0, math.ceil((now_ms - latest_db_time) / self.INTERVAL_1M_MS))
        else:
            gap_minutes = max_dp  # 首次取满

        dp_needed = min(max_dp, max(1, gap_minutes + 5))  # 加 5 分钟冗余

        candles_from_api = await self.fetch_recent_data(dp=dp_needed)
        if not candles_from_api:
            logger.warning("⚠️  No data fetched during initialization")
            return

        existing_timestamps = set()
        if existing_count > 0:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT open_time FROM xau_candles_1m")
                existing_timestamps = {row[0] for row in cursor.fetchall()}

        new_candles = [
            candle for candle in candles_from_api
            if candle['open_time'] not in existing_timestamps
        ]

        duplicate_count = len(candles_from_api) - len(new_candles)
        if duplicate_count > 0:
            logger.info(f"🔍 Deduplication: skipped {duplicate_count} duplicate records")

        if new_candles:
            logger.info(f"💾 Storing {len(new_candles)} new candles...")
            self.upsert_candles_batch(new_candles, "xau_candles_1m")
            logger.info("✅ Data saved")
        else:
            logger.info("ℹ️  No new data to save")

        logger.info("🔄 Aggregating 3m and 5m candles...")
        await self.aggregate_1m_to_3m()
        await self.aggregate_1m_to_5m()

        final_count = self.get_candle_count()
        logger.info(f"✅ Initialization complete! Total: {final_count} records (+{final_count - existing_count} new)")

    async def aggregate_1m_to_3m(self):
        """聚合1分钟K线到3分钟"""
        with sqlite3.connect(self.db_path) as conn:
            # 只聚合最近 2 天：历史 3m/5m 已固定，回填后 1m 表达 188 万行，
            # 每分钟全表扫描会把整表 load 进内存 → OOM。
            cutoff = int(time.time() * 1000) - 2 * 86400000
            cursor = conn.execute("""
                SELECT open_time, open, high, low, close, volume
                FROM xau_candles_1m
                WHERE open_time > ?
                ORDER BY open_time ASC
            """, (cutoff,))

            rows = cursor.fetchall()
            if not rows:
                return

            # 按3分钟分组
            candles_3m = {}
            for row in rows:
                open_time_ms = row[0]
                open_time_3m = self.floor_to_3m(open_time_ms)

                if open_time_3m not in candles_3m:
                    candles_3m[open_time_3m] = {
                        'open_time': open_time_3m,
                        'open': row[1],
                        'high': row[2],
                        'low': row[3],
                        'close': row[4],
                        'volume': row[5]
                    }
                else:
                    candles_3m[open_time_3m]['high'] = max(candles_3m[open_time_3m]['high'], row[2])
                    candles_3m[open_time_3m]['low'] = min(candles_3m[open_time_3m]['low'], row[3])
                    candles_3m[open_time_3m]['close'] = row[4]
                    candles_3m[open_time_3m]['volume'] += row[5]

            if candles_3m:
                self.upsert_candles_batch(list(candles_3m.values()), "xau_candles_3m")
                logger.info(f"✅ Aggregated {len(candles_3m)} 3-minute candles")

    async def aggregate_1m_to_5m(self):
        """聚合1分钟K线到5分钟"""
        with sqlite3.connect(self.db_path) as conn:
            # 只聚合最近 2 天：历史 3m/5m 已固定，回填后 1m 表达 188 万行，
            # 每分钟全表扫描会把整表 load 进内存 → OOM。
            cutoff = int(time.time() * 1000) - 2 * 86400000
            cursor = conn.execute("""
                SELECT open_time, open, high, low, close, volume
                FROM xau_candles_1m
                WHERE open_time > ?
                ORDER BY open_time ASC
            """, (cutoff,))

            rows = cursor.fetchall()
            if not rows:
                return

            # 按5分钟分组
            candles_5m = {}
            for row in rows:
                open_time_ms = row[0]
                open_time_5m = self.floor_to_5m(open_time_ms)

                if open_time_5m not in candles_5m:
                    candles_5m[open_time_5m] = {
                        'open_time': open_time_5m,
                        'open': row[1],
                        'high': row[2],
                        'low': row[3],
                        'close': row[4],
                        'volume': row[5]
                    }
                else:
                    candles_5m[open_time_5m]['high'] = max(candles_5m[open_time_5m]['high'], row[2])
                    candles_5m[open_time_5m]['low'] = min(candles_5m[open_time_5m]['low'], row[3])
                    candles_5m[open_time_5m]['close'] = row[4]
                    candles_5m[open_time_5m]['volume'] += row[5]

            if candles_5m:
                self.upsert_candles_batch(list(candles_5m.values()), "xau_candles_5m")
                logger.info(f"✅ Aggregated {len(candles_5m)} 5-minute candles")

    def get_recent_candles(self, table: str = "xau_candles_1m", limit: int = 100) -> List[Dict]:
        """获取最近的K线数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"""
                SELECT open_time, open, high, low, close, volume
                FROM {table}
                ORDER BY open_time DESC
                LIMIT ?
            """, (limit,))

            candles = []
            for row in cursor.fetchall():
                candles.append({
                    "timestamp": row[0] // 1000,
                    "open_time": row[0],
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5]
                })

            return list(reversed(candles))  # 返回时间顺序

    def get_current_price(self) -> Optional[float]:
        """获取当前价格（最新K线的收盘价）"""
        candles = self.get_recent_candles("xau_candles_1m", 1)
        if candles:
            return candles[0]["close"]
        return None


class XAUWebSocketClient:
    """
    XAU/USD WebSocket 客户端（InsightSentry 实时数据）

    功能：
    - 连接到 WebSocket
    - 订阅实时数据流
    - 处理消息并回调
    - 断线自动重连（指数退避）
    - 心跳机制
    - 速率限制
    """

    WS_URL = "wss://realtime.insightsentry.com/live"

    def __init__(self, api_key: str, data_callback: Callable):
        self.api_key = api_key
        self.data_callback = data_callback  # 接收到新数据时的回调函数
        self.is_running = False
        self.websocket = None
        self._task = None

        # 重连机制
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.base_reconnect_delay = 5  # 基础重连延迟（秒）

        # 心跳机制
        self._ping_task = None
        self._last_pong_time = 0
        self._last_message_time = 0

        # 速率限制（300条消息/5分钟）
        self.message_timestamps = deque(maxlen=300)

        # 错误日志限制
        self.error_count = 0
        self.last_error_log_time = 0
        self.error_log_interval = 60  # 每分钟最多记录一次同类错误

    def get_subscription_message(self) -> dict:
        """构建订阅消息"""
        return {
            "api_key": self.api_key,
            "subscriptions": [
                {
                    "code": "COMEX:GC1!",
                    "type": "series",
                    "bar_type": "second",
                    "bar_interval": 1,
                    "extended": True,
                    "max_dp": 51,
                    "dadj": False,
                    "badj": True,
                    "settlement": True
                }
            ]
        }

    def get_reconnect_delay(self) -> float:
        """计算重连延迟（指数退避）"""
        delay = min(self.base_reconnect_delay * (2 ** self.reconnect_attempts), 300)  # 最大5分钟
        return delay

    def check_rate_limit(self) -> bool:
        """检查是否超过速率限制（300条消息/5分钟）"""
        now = time.time()
        # 清理5分钟前的时间戳
        while self.message_timestamps and (now - self.message_timestamps[0]) > 300:
            self.message_timestamps.popleft()

        # 检查是否达到限制
        if len(self.message_timestamps) >= 299:  # 留1个余地
            return False

        self.message_timestamps.append(now)
        return True

    async def send_ping(self, websocket):
        """定期发送ping保持连接活跃（每25秒）"""
        try:
            while self.is_running:
                await asyncio.sleep(25)  # 文档建议20-30秒，我们用25秒
                try:
                    if self.check_rate_limit():
                        await websocket.send("ping")
                        logger.debug("🏓 Sent ping")
                except:
                    # 连接已关闭，退出ping循环
                    break
        except Exception as e:
            logger.debug(f"Ping task ended: {e}")

    async def connect_and_listen(self):
        """连接到 WebSocket 并监听消息"""
        while self.is_running:
            try:
                # 计算重连延迟
                if self.reconnect_attempts > 0:
                    delay = self.get_reconnect_delay()
                    logger.info(f"⏳ Reconnecting in {delay}s (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
                    await asyncio.sleep(delay)

                # WebSocket超时设置为15秒（文档建议至少12秒）
                async with websockets.connect(
                    self.WS_URL,
                    open_timeout=15,
                    close_timeout=10,
                    ping_interval=None,  # 我们自己管理ping
                    ping_timeout=None
                ) as websocket:
                    self.websocket = websocket
                    logger.info("✅ WebSocket connected")
                    self.reconnect_attempts = 0  # 连接成功，重置计数器
                    self._last_message_time = time.time()

                    # 启动心跳任务
                    self._ping_task = asyncio.create_task(self.send_ping(websocket))

                    # 发送订阅消息
                    if self.check_rate_limit():
                        subscription = self.get_subscription_message()
                        await websocket.send(json.dumps(subscription))
                        logger.info(f"📤 Subscription sent for COMEX:GC1!")

                    # 持续接收消息
                    no_message_count = 0
                    async for message in websocket:
                        try:
                            self._last_message_time = time.time()
                            no_message_count = 0

                            # 处理pong响应
                            if message == "pong":
                                self._last_pong_time = time.time()
                                logger.debug("🏓 Received pong")
                                continue

                            data = json.loads(message)

                            # 处理不同类型的消息
                            if isinstance(data, dict):
                                # 时间戳消息（心跳）
                                if 'timestamp' in data and len(data) == 1:
                                    logger.debug(f"💓 Server heartbeat: {data['timestamp']}")
                                    continue

                                msg_type = data.get('type', data.get('event', 'unknown'))

                                if msg_type in ['subscribed', 'success']:
                                    logger.info(f"✅ Subscription confirmed: {data}")
                                elif msg_type == 'error':
                                    logger.error(f"❌ WebSocket error: {data}")
                                    # 根据错误类型决定是否重连
                                    if 'api_key' in str(data).lower():
                                        logger.error("API key error, stopping client")
                                        self.is_running = False
                                        break
                                elif 'bars' in data or 'bar' in data:
                                    # K线数据
                                    await self.handle_bar_data(data)
                                else:
                                    logger.debug(f"📨 Message: {data}")
                            elif isinstance(data, list):
                                # 可能是K线数组
                                for bar in data:
                                    await self.handle_bar_data(bar)

                        except json.JSONDecodeError as e:
                            self._log_error(f"JSON decode error: {e}", "json_error")
                        except websockets.exceptions.ConnectionClosed:
                            # WebSocket连接关闭，跳出消息循环进行重连
                            logger.warning("⚠️ Connection closed while processing message")
                            break
                        except Exception as e:
                            self._log_error(f"Error processing message: {e}", "process_error")
                            # 连接相关错误（含 1001 going away 驱逐）跳出循环走退避重连，
                            # 否则死循环烧 CPU/内存 → OOM
                            es = str(e).lower()
                            if any(k in es for k in ("close frame", "connection", "going away",
                                                     "1001", "1006", "1000", "code =")):
                                logger.warning("⚠️ Connection error detected, breaking loop")
                                break

                    # 检查是否因为长时间无消息而断开
                    if time.time() - self._last_message_time > 120:
                        logger.warning("⚠️ No messages for 2 minutes, reconnecting...")

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"⚠️ WebSocket connection closed: {e}")
                self.reconnect_attempts += 1
                # 限制重连次数，防止无限循环
                if self.reconnect_attempts > 10:
                    logger.error("❌ Too many reconnection attempts, stopping WebSocket client")
                    self.is_running = False
                    break
            except asyncio.TimeoutError:
                logger.warning("⚠️ WebSocket connection timeout")
                self.reconnect_attempts += 1
                if self.reconnect_attempts > 10:
                    logger.error("❌ Too many reconnection attempts, stopping WebSocket client")
                    self.is_running = False
                    break
            except Exception as e:
                logger.error(f"❌ WebSocket error: {e}")
                self.reconnect_attempts += 1
                if self.reconnect_attempts > 10:
                    logger.error("❌ Too many reconnection attempts, stopping WebSocket client")
                    self.is_running = False
                    break
            finally:
                # 清理ping任务
                if self._ping_task:
                    self._ping_task.cancel()
                    try:
                        await self._ping_task
                    except asyncio.CancelledError:
                        pass

            # 检查是否超过最大重连次数
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logger.error(f"❌ Max reconnection attempts reached ({self.max_reconnect_attempts})")
                self.is_running = False
                break

    def _log_error(self, message: str, error_type: str):
        """限制错误日志频率"""
        now = time.time()
        if now - self.last_error_log_time > self.error_log_interval:
            logger.error(f"❌ {message}")
            self.last_error_log_time = now
            self.error_count = 1
        else:
            self.error_count += 1
            if self.error_count % 100 == 0:  # 每100个错误记录一次统计
                logger.warning(f"⚠️ {error_type}: {self.error_count} errors in last {self.error_log_interval}s")

    async def handle_bar_data(self, data: dict):
        """处理K线数据"""
        try:
            # 提取K线数据（根据实际API响应调整字段名）
            bar = data.get('bar', data)

            timestamp = bar.get('time', bar.get('timestamp', bar.get('t', 0)))

            # 时间戳转换
            if timestamp < 10000000000:
                timestamp_ms = timestamp * 1000
            else:
                timestamp_ms = timestamp

            candle = {
                "open_time": (timestamp_ms // 60000) * 60000,  # Floor to 1m
                "timestamp": timestamp_ms // 1000,
                "open": float(bar.get('open', bar.get('o', 0))),
                "high": float(bar.get('high', bar.get('h', 0))),
                "low": float(bar.get('low', bar.get('l', 0))),
                "close": float(bar.get('close', bar.get('c', 0))),
                "volume": float(bar.get('volume', bar.get('v', 0)))
            }

            # 调用回调函数
            if self.data_callback:
                await self.data_callback(candle)

        except Exception as e:
            logger.error(f"❌ Error handling bar data: {e}")

    async def start(self):
        """启动 WebSocket 客户端"""
        self.is_running = True
        self._task = asyncio.create_task(self.connect_and_listen())

    async def stop(self):
        """停止 WebSocket 客户端"""
        self.is_running = False

        if self.websocket:
            await self.websocket.close()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 WebSocket client stopped")

class XAUQuoteWebSocketClient:
    """
    订阅顶层盘口（Level 1 Quote）的 WebSocket 客户端
    仅保存 bid/ask 与 size，用于盘口展示
    改进：
    - 错误日志限流
    - 指数退避重连
    - 正确的ping-pong机制
    - 速率限制保护
    """

    WS_URL = "wss://realtime.insightsentry.com/live"

    def __init__(self, api_key: str, code: str, data_callback: Callable):
        self.api_key = api_key
        self.code = code
        self.data_callback = data_callback
        self.is_running = False
        self.websocket = None
        self._task = None
        self._ping_task = None
        self.ping_interval = 25  # seconds, keep 20-30s per docs
        self._last_message_time = time.time()
        self._last_pong_time = time.time()

        # 重连机制
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.base_reconnect_delay = 5

        # 速率限制（300条消息/5分钟）
        self.message_timestamps = deque(maxlen=300)

        # 错误日志限制
        self.error_count = 0
        self.last_error_log_time = 0
        self.error_log_interval = 60  # 每分钟最多记录一次同类错误
        self.consecutive_errors = 0  # 连续错误计数

    def get_subscription_message(self) -> dict:
        return {
            "api_key": self.api_key,
            "subscriptions": [
                {
                    "code": self.code,
                    "type": "quote"
                }
            ]
        }

    def get_reconnect_delay(self) -> float:
        """计算重连延迟（指数退避）"""
        delay = min(self.base_reconnect_delay * (2 ** self.reconnect_attempts), 300)  # 最大5分钟
        return delay

    def check_rate_limit(self) -> bool:
        """检查是否超过速率限制（300条消息/5分钟）"""
        now = time.time()
        # 清理5分钟前的时间戳
        while self.message_timestamps and (now - self.message_timestamps[0]) > 300:
            self.message_timestamps.popleft()

        # 检查是否达到限制
        if len(self.message_timestamps) >= 299:
            return False

        self.message_timestamps.append(now)
        return True

    def _log_error(self, message: str, error_type: str = "general"):
        """限制错误日志频率，防止日志风暴"""
        now = time.time()
        self.consecutive_errors += 1

        # 如果是连续错误，只在特定间隔记录
        if now - self.last_error_log_time > self.error_log_interval:
            if self.consecutive_errors > 1:
                logger.error(f"❌ {message} (occurred {self.consecutive_errors} times)")
            else:
                logger.error(f"❌ {message}")
            self.last_error_log_time = now
            self.consecutive_errors = 0
        elif self.consecutive_errors % 1000 == 0:  # 每1000个错误记录一次
            logger.warning(f"⚠️ {error_type}: {self.consecutive_errors} errors suppressed")

    async def send_ping(self, websocket):
        """定期发送ping保持连接活跃"""
        try:
            while self.is_running:
                await asyncio.sleep(self.ping_interval)
                try:
                    if self.check_rate_limit():
                        await websocket.send("ping")
                        logger.debug("🏓 Sent ping to quote WebSocket")
                except:
                    # 连接已关闭，退出ping循环
                    break
        except Exception as e:
            logger.debug(f"Ping task ended: {e}")

    async def connect_and_listen(self):
        while self.is_running:
            try:
                # 指数退避重连
                if self.reconnect_attempts > 0:
                    delay = self.get_reconnect_delay()
                    logger.info(f"⏳ Quote WS reconnecting in {delay}s (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
                    await asyncio.sleep(delay)

                logger.info(f"🔌 Connecting to InsightSentry Quote WebSocket...")

                # 设置合理的超时（文档建议至少12秒）
                async with websockets.connect(
                    self.WS_URL,
                    open_timeout=15,
                    close_timeout=10,
                    ping_interval=None,  # 我们自己管理ping
                    ping_timeout=None
                ) as websocket:
                    self.websocket = websocket
                    logger.info(f"✅ Connected to {self.WS_URL}")
                    self.reconnect_attempts = 0  # 重置重连计数
                    self.consecutive_errors = 0  # 重置错误计数

                    # 发送订阅消息
                    if self.check_rate_limit():
                        subscription = self.get_subscription_message()
                        await websocket.send(json.dumps(subscription))
                        logger.info("📤 Quote subscription sent for COMEX:GC1!")

                    self._last_message_time = time.time()

                    # 启动ping任务
                    self._ping_task = asyncio.create_task(self.send_ping(websocket))

                    message_count = 0
                    last_log_time = time.time()
                    no_message_count = 0

                    logger.info("👂 Listening for quote messages...")

                    # 使用超时检测无消息状态
                    while self.is_running:
                        try:
                            # 10秒超时等待消息
                            message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                            no_message_count = 0  # 收到消息，重置计数器
                            self.consecutive_errors = 0  # 重置连续错误计数

                            # 处理pong响应
                            if message == "pong":
                                self._last_pong_time = time.time()
                                logger.debug("🏓 Received pong from quote WebSocket")
                                continue

                            data = json.loads(message)
                            self._last_message_time = time.time()
                            message_count += 1

                            # 每30秒记录一次统计
                            if time.time() - last_log_time > 30:
                                logger.info(f"📊 Quote WS stats: {message_count} messages, last at {time.strftime('%H:%M:%S')}")
                                last_log_time = time.time()

                            # 处理不同类型的消息
                            if isinstance(data, dict):
                                # 服务器心跳（时间戳）
                                if 'timestamp' in data and len(data) == 1:
                                    logger.debug(f"💓 Server heartbeat: {data['timestamp']}")
                                    continue

                                # 盘口数据
                                if "bid" in data or "ask" in data:
                                    bid = data.get('bid', 0)
                                    ask = data.get('ask', 0)
                                    spread = ask - bid if bid and ask else 0
                                    logger.debug(f"💹 Quote: bid={bid}, ask={ask}, spread={spread:.2f}")
                                    if self.data_callback:
                                        await self.data_callback(data)

                                # 错误消息
                                elif 'error' in data:
                                    logger.error(f"❌ Server error: {data}")
                                    if 'api_key' in str(data).lower():
                                        logger.error("API key error, stopping quote client")
                                        self.is_running = False
                                        break

                                # 事件消息
                                elif 'type' in data or 'event' in data:
                                    event_type = data.get('type', data.get('event'))
                                    if event_type in ['subscribed', 'success']:
                                        logger.info(f"✅ Subscription confirmed: {data}")
                                    else:
                                        logger.debug(f"📩 Event: {event_type}")

                        except asyncio.TimeoutError:
                            # 10秒无消息
                            no_message_count += 1
                            if no_message_count == 6:  # 1分钟无消息
                                logger.warning(f"⏱️ No messages for 60s")
                            elif no_message_count == 12:  # 2分钟无消息，考虑重连
                                logger.warning("⚠️ No messages for 2 minutes, connection may be dead")
                                break
                            continue

                        except json.JSONDecodeError as e:
                            self._log_error(f"JSON decode error: {e}", "json_error")

                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("⚠️ Quote 连接已关闭，退出消息循环重连")
                            break
                        except Exception as e:
                            self._log_error(f"Error processing message: {e}", "process_error")
                            # 连接被关闭/驱逐（1001 going away 等）必须退出循环走退避重连，
                            # 否则同一错误每次迭代重入 → 死循环烧 CPU/内存 → OOM
                            es = str(e).lower()
                            if any(k in es for k in ("close frame", "connection", "going away",
                                                     "1001", "1006", "1000", "code =")):
                                logger.warning("⚠️ Quote 连接错误，退出循环重连")
                                break

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"⚠️ Quote WebSocket closed: code={e.code}, reason={e.reason}")
                self.reconnect_attempts += 1
            except asyncio.TimeoutError:
                logger.warning("⚠️ Quote WebSocket timeout")
                self.reconnect_attempts += 1
            except Exception as e:
                logger.error(f"❌ Quote WebSocket error: {type(e).__name__}: {e}")
                self.reconnect_attempts += 1
            finally:
                # 清理资源
                if self._ping_task:
                    self._ping_task.cancel()
                    try:
                        await self._ping_task
                    except asyncio.CancelledError:
                        pass
                    self._ping_task = None

                # 记录断开统计
                if 'message_count' in locals() and message_count > 0:
                    logger.info(f"📊 Disconnect stats: {message_count} messages received")

            # 检查是否超过最大重连次数
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logger.error(f"❌ Max reconnection attempts reached ({self.max_reconnect_attempts})")
                self.is_running = False
                break

            if not self.is_running:
                logger.info("🛑 Quote WebSocket stopping, not reconnecting")

    async def OLD_watchdog(self, websocket):
        """监控连接活跃度，超过2分钟无消息则强制重连"""
        max_idle_seconds = 120  # 2分钟无消息视为连接僵死
        check_interval = 30  # 每30秒检查一次
        try:
            logger.info(f"🐕 Watchdog started, will check every {check_interval}s, max idle: {max_idle_seconds}s")
            while self.is_running and websocket and not websocket.closed:
                await asyncio.sleep(check_interval)
                if not self.is_running or websocket.closed:
                    logger.info("🐕 Watchdog: Connection closed or stopping, exiting")
                    break

                idle = time.time() - self._last_message_time
                # Use try-except to handle different websocket library versions
                try:
                    is_closed = websocket.closed if hasattr(websocket, 'closed') else websocket.state.name == 'CLOSED'
                except:
                    is_closed = False
                logger.info(f"🐕 Watchdog check: idle for {idle:.0f}s, connection state: {'closed' if is_closed else 'open'}")

                if idle > max_idle_seconds:
                    logger.warning(f"⚠️ Quote WebSocket idle for {idle:.0f}s (max: {max_idle_seconds}s), forcing reconnect...")
                    await websocket.close()
                    break
                elif idle > max_idle_seconds / 2:
                    logger.warning(f"⚠️ Quote WebSocket idle warning: {idle:.0f}s (will reconnect at {max_idle_seconds}s)")
        except asyncio.CancelledError:
            logger.info("🐕 Watchdog cancelled")
        except Exception as e:
            logger.error(f"❌ Watchdog error: {e}")

    async def OLD_ping_loop(self, websocket):
        """Send ping only when no message for ping_interval seconds (rate limit >15s)"""
        try:
            ping_count = 0
            logger.info(f"📡 Ping loop started, interval: {self.ping_interval}s")
            while self.is_running and websocket and not websocket.closed:
                await asyncio.sleep(self.ping_interval)
                if not self.is_running or websocket.closed:
                    logger.info("📡 Ping loop: Connection closed or stopping, exiting")
                    break

                idle = time.time() - self._last_message_time
                if idle >= self.ping_interval:
                    try:
                        ping_count += 1
                        await websocket.ping()
                        logger.info(f"📡 Ping #{ping_count} sent (idle: {idle:.0f}s)")
                    except Exception as e:
                        logger.error(f"❌ Ping #{ping_count} failed: {e}")
                        break
                else:
                    logger.debug(f"📡 Skip ping, recent activity {idle:.0f}s ago")
        except asyncio.CancelledError:
            logger.info("📡 Ping loop cancelled")
        except Exception as e:
            logger.error(f"❌ Ping loop error: {e}")

    async def start(self):
        self.is_running = True
        self._task = asyncio.create_task(self.connect_and_listen())

    async def stop(self):
        self.is_running = False
        if self.websocket:
            await self.websocket.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Quote WebSocket client stopped")


class XAUDataManager:
    """XAU 数据管理器（统一管理历史数据和实时数据）"""

    def __init__(self, bearer_token: str):
        self.fetcher = InsightSentryXAUDataFetcher(bearer_token=bearer_token)
        self.is_running = False
        self._poll_task: Optional[asyncio.Task] = None
        self.quote_ws_client: Optional[XAUQuoteWebSocketClient] = None
        self.latest_quote: Optional[Dict] = None
        self.quote_history: deque = deque(maxlen=300)  # 存最近 quote 更新

    async def initialize(self):
        """初始化：按缺口回灌有限 datapoints"""
        logger.info("🚀 Initializing XAU Data Manager with InsightSentry (dp-limited)...")
        await self.fetcher.initialize_with_dp_backfill()

        candles = self.fetcher.get_recent_candles(limit=100)
        logger.info(f"✅ Loaded {len(candles)} recent candles")
        return candles

    async def _poll_latest(self, interval_seconds: int = 60):
        """定时轮询最新 1m 数据点"""
        while self.is_running:
            try:
                candles = await self.fetcher.fetch_recent_data(dp=1)
                if candles:
                    self.fetcher.upsert_candles_batch(candles, "xau_candles_1m")
                    # 只聚合最新几条即可；异步保证开销可控
                    await self.fetcher.aggregate_1m_to_3m()
                    await self.fetcher.aggregate_1m_to_5m()
                    latest_close = candles[-1]["close"]
                    logger.info(f"💹 Polled latest XAU datapoint: ${latest_close:.2f}")
            except Exception as e:
                logger.error(f"❌ Error in polling latest datapoint: {e}")

            await asyncio.sleep(interval_seconds)

    async def on_quote_update(self, quote: dict):
        """处理盘口顶层报价更新"""
        try:
            ts = quote.get("time") or quote.get("timestamp") or time.time()
            # 标准化字段
            normalized = {
                "code": quote.get("code", "COMEX:GC1!"),
                "bid": float(quote.get("bid", 0)),
                "ask": float(quote.get("ask", 0)),
                "bid_size": float(quote.get("bid_size", 0)),
                "ask_size": float(quote.get("ask_size", 0)),
                "timestamp": ts
            }
            self.latest_quote = normalized

            # 记录历史供前端展示
            spread = normalized["ask"] - normalized["bid"] if normalized["ask"] and normalized["bid"] else None
            mid = (normalized["ask"] + normalized["bid"]) / 2 if normalized["ask"] and normalized["bid"] else None
            self.quote_history.append({
                **normalized,
                "mid": mid,
                "spread": spread
            })
        except Exception as e:
            logger.error(f"❌ Error handling quote update: {e}")

    async def start(self, update_callback: Optional[Callable] = None):
        """启动数据管理器：回灌 + 轮询"""
        self.is_running = True
        await self.initialize()

        # 开始 1 分钟轮询最新 datapoint
        self._poll_task = asyncio.create_task(self._poll_latest())

        # 启动盘口顶层报价订阅
        try:
            self.quote_ws_client = XAUQuoteWebSocketClient(
                api_key=self.fetcher.bearer_token,
                code="COMEX:GC1!",
                data_callback=self.on_quote_update
            )
            await self.quote_ws_client.start()
            logger.info("✅ XAU Quote WebSocket started")
        except Exception as e:
            logger.error(f"❌ Failed to start XAU Quote WebSocket: {e}")

        logger.info("✅ XAU Data Manager started (dp-limited REST polling)")

    async def stop(self):
        """停止数据管理器"""
        self.is_running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self.quote_ws_client:
            await self.quote_ws_client.stop()

        await self.fetcher.close_session()

        logger.info("🛑 XAU Data Manager stopped")

    def get_recent_candles(self, interval: str = "1m", limit: int = 100) -> List[Dict]:
        """获取最近的K线数据"""
        table_map = {
            "1m": "xau_candles_1m",
            "3m": "xau_candles_3m",
            "5m": "xau_candles_5m"
        }

        table = table_map.get(interval, "xau_candles_1m")
        return self.fetcher.get_recent_candles(table, limit)

    def get_current_price(self) -> Optional[float]:
        """获取当前价格"""
        return self.fetcher.get_current_price()

    # Compatibility methods for fapi.py
    async def aggregate_to_3m(self):
        """聚合1分钟K线到3分钟（兼容方法）"""
        await self.fetcher.aggregate_1m_to_3m()

    async def aggregate_to_5m(self):
        """聚合1分钟K线到5分钟（兼容方法）"""
        await self.fetcher.aggregate_1m_to_5m()

    def get_recent_candles_3m(self, limit: int = 100) -> List[Dict]:
        """获取最近的3分钟K线（兼容方法）"""
        return self.fetcher.get_recent_candles("xau_candles_3m", limit)

    def get_recent_candles_5m(self, limit: int = 100) -> List[Dict]:
        """获取最近的5分钟K线（兼容方法）"""
        return self.fetcher.get_recent_candles("xau_candles_5m", limit)

    def get_candle_count(self, table: str = "xau_candles_1m") -> int:
        """获取K线总数（兼容方法）"""
        return self.fetcher.get_candle_count(table)

    def get_latest_candle_time(self, table: str = "xau_candles_1m") -> Optional[int]:
        """获取最新K线时间（兼容方法）"""
        return self.fetcher.get_latest_candle_time(table)

    def get_latest_quote(self) -> Optional[Dict]:
        """获取最新盘口顶层报价"""
        return self.latest_quote

    def get_quote_history(self, limit: int = 100) -> List[Dict]:
        """获取最近的盘口报价历史"""
        items = list(self.quote_history)
        return items[-limit:] if limit and limit < len(items) else items


# 如果直接运行此文件，执行测试
if __name__ == "__main__":
    async def test():
        bearer_token = "eyJhbGciOiJIUzI1NiJ9.eyJ1dWlkIjoic3V5aW5nY2luQGdtYWlsLmNvbSIsInBsYW4iOiJ1bHRyYSIsIm5ld3NmZWVkX2VuYWJsZWQiOnRydWUsIndlYnNvY2tldF9zeW1ib2xzIjo1LCJ3ZWJzb2NrZXRfY29ubmVjdGlvbnMiOjF9.6aA_ND-9NmZI2-8mILRJeZDLt9Y6skrtsNbzP0FeQVI"

        fetcher = InsightSentryXAUDataFetcher(bearer_token=bearer_token)
        await fetcher.initialize_with_dp_backfill(max_dp=2000)

        print(f"\n✅ Test completed!")
        print(f"Total candles: {fetcher.get_candle_count()}")
        print(f"Current price: ${fetcher.get_current_price():.2f}")

        await fetcher.close_session()

    asyncio.run(test())
