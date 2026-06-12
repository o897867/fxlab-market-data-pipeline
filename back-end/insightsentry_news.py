#!/usr/bin/env python3
"""
InsightSentry Financial News WebSocket Client
连接到 InsightSentry 新闻推送服务并使用 ChatGPT 生成总结

WebSocket 端点: wss://realtime.insightsentry.com/newsfeed
文档: https://insightsentry.com/docs/ws
"""

import asyncio
import os
import websockets
import json
import sqlite3
import time
import logging
from datetime import datetime
from typing import Callable, Optional, Dict, List
from collections import deque
import aiohttp
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 新闻摘要 LLM 配置：默认 DeepSeek（OpenAI 兼容接口，高频路径成本优先）。
# 如需切回 OpenAI，整组覆盖三个环境变量即可：
#   NEWS_LLM_BASE_URL=https://api.openai.com/v1
#   NEWS_LLM_MODEL=gpt-4.1-mini
#   并让 fapi.py 注入 OPENAI_API_KEY
NEWS_LLM_BASE_URL = os.getenv("NEWS_LLM_BASE_URL", "https://api.deepseek.com/v1")
NEWS_LLM_MODEL = os.getenv("NEWS_LLM_MODEL", "deepseek-v4-flash")
# v4-flash 是推理模型：reasoning 也计入 completion tokens，上限必须给思考留足空间，
# 否则 finish_reason=length 且正文为空（切回 gpt-4.1-mini 时 250 就够）
NEWS_LLM_MAX_TOKENS = int(os.getenv("NEWS_LLM_MAX_TOKENS", "2048"))


class NewsWebSocketClient:
    """
    InsightSentry 新闻 WebSocket 客户端

    功能：
    - 连接到新闻推送服务
    - 自动接收最新 10 条新闻
    - 使用 ChatGPT 总结新闻内容
    - 存储到数据库
    - 实时推送给前端
    """

    WS_URL = "wss://realtime.insightsentry.com/newsfeed"

    def __init__(
        self,
        api_key: str,
        openai_api_key: str,
        db_path: str = "shopback_data.db",
        news_callback: Optional[Callable] = None
    ):
        self.api_key = api_key
        self.openai_api_key = openai_api_key
        self.db_path = db_path
        self.news_callback = news_callback  # 新闻到达时的回调函数

        self.is_running = False
        self.websocket = None
        self._task = None
        self._ping_task = None

        # 重连机制
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.base_reconnect_delay = 5

        # 心跳机制
        self.ping_interval = 25
        self._last_message_time = time.time()
        self._last_pong_time = time.time()

        # 速率限制（300条消息/5分钟）
        self.message_timestamps = deque(maxlen=300)
        # OpenAI 总结速率限制（防突发消耗）
        self.summary_timestamps = deque()
        self.summary_limit_per_minute = 20  # 可根据预算调整

        # 错误日志限制
        self.error_count = 0
        self.last_error_log_time = 0
        self.error_log_interval = 60
        self.consecutive_errors = 0

        # 新闻过滤配置：仅处理与以下主题相关的新闻，减少 OpenAI 调用
        # 收紧了通用货币/宽泛关键词，降低误触发概率
        self.symbol_filters = {
            # 股票
            "NVDA", "AMD", "RXRX", "GOOGL", "GOOG", "META", "TSM", "TSMC",
            # 指数
            "NASDAQ", "IXIC", "NDX", "DJI", "DJIA",
            # 贵金属
            "XAU", "GOLD", "GC",  # 黄金
            "XAG", "SILVER", "SI",  # 白银
            # 货币对（正向）
            "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD",
            "EURGBP", "EURJPY", "GBPJPY", "AUDNZD",
            # 货币对（反向）
            "USDEUR", "USDGBP", "JPYUSD", "CHFUSD", "USDAUD", "USDNZD",
            "GBPEUR", "JPYEUR", "JPYGBP", "NZDAUD",
            # 交易所
            "NYSE", "CME", "COMEX", "CBOT", "NYMEX"
        }
        # 关键词过滤（英文词做词边界，中文直接匹配）
        self.keyword_filters = [
            # === 股票公司 ===
            "nvidia", "nvda", "英伟达",
            "amd", "advanced micro devices",
            "recursion pharmaceuticals", "rxrx",
            # 谷歌
            "google", "googl", "goog", "alphabet", "谷歌",
            "sundar pichai", "pichai", "桑达尔·皮查伊",
            "gemini", "bard", "waymo",
            # Meta
            "meta", "meta platforms", "facebook", "instagram", "whatsapp",
            "mark zuckerberg", "zuckerberg", "扎克伯格",
            "metaverse", "元宇宙", "reality labs",
            # 台积电
            "tsm", "tsmc", "taiwan semiconductor", "台积电", "台湾积体电路",
            "morris chang", "张忠谋", "c.c. wei", "魏哲家",

            # === 指数 ===
            "nasdaq", "纳斯达克", "纳指",
            "dow jones", "djia", "道琼斯", "道指",

            # === 贵金属 ===
            "gold", "xau", "黄金",
            "silver", "xag", "白银",
            "precious metals", "贵金属",

            # === 债券 ===
            "treasury", "treasuries", "国债", "美债",
            "bond", "bonds", "债券",
            "yield", "收益率", "殖利率",
            "10-year", "10年期", "2-year", "2年期",
            "yield curve", "收益率曲线", "殖利率曲线",
            "government bond", "政府债券", "公债",

            # === 外汇/货币 ===
            "dollar index", "dxy", "美元指数",
            # 货币对（正向）
            "eurusd", "欧美", "gbpusd", "镑美",
            "usdjpy", "美日", "usdchf", "美瑞",
            "audusd", "澳美", "nzdusd", "纽美",
            "eurgbp", "欧镑", "eurjpy", "欧日",
            "gbpjpy", "镑日", "audnzd", "澳纽",
            # 货币对（反向）
            "usdeur", "美欧", "usdgbp", "美镑",
            "jpyusd", "日美", "chfusd", "瑞美",
            "usdaud", "美澳", "usdnzd", "美纽",
            "gbpeur", "镑欧", "jpyeur", "日欧",
            "jpygbp", "日镑", "nzdaud", "纽澳",
            "forex", "fx", "外汇", "汇率",

            # === 交易所 ===
            "nyse", "new york stock exchange", "纽约证券交易所", "纽交所",
            "cme", "chicago mercantile exchange", "芝加哥商品交易所", "芝商所",
            "comex", "commodity exchange", "商品交易所",
            "cbot", "chicago board of trade", "芝加哥期货交易所",
            "nymex", "new york mercantile exchange", "纽约商品交易所",

            # === 美国央行 ===
            "federal reserve", "fomc", "美联储", "美储",
            "jerome powell", "鲍威尔",
            "janet yellen", "耶伦",

            # === 中国央行 ===
            "pboc", "people's bank of china", "人民银行", "中国央行",
            "yi gang", "易纲",
            "pan gongsheng", "潘功胜",

            # === 日本央行 ===
            "boj", "bank of japan", "日银", "日本央行",
            "ueda kazuo", "植田和男",
            "kuroda haruhiko", "黑田东彦",

            # === 欧洲央行 ===
            "ecb", "european central bank", "欧洲央行", "欧央行",
            "christine lagarde", "拉加德",

            # === 英国央行 ===
            "boe", "bank of england", "英国央行", "英格兰银行",
            "andrew bailey",

            # === 瑞士央行 ===
            "snb", "swiss national bank", "瑞士央行", "瑞士国家银行",
            "thomas jordan",

            # === 澳洲央行 ===
            "rba", "reserve bank of australia", "澳洲联储", "澳洲央行", "澳储",
            "philip lowe", "michele bullock",

            # === 货币政策相关 ===
            "rate hike", "加息", "升息",
            "rate cut", "降息", "减息",
            "interest rate", "利率", "基准利率",
            "monetary policy", "货币政策",
            "quantitative easing", "qe", "量化宽松",
            "tapering", "缩减购债", "缩表"
        ]
        self.keyword_regexes = self._build_keyword_regexes(self.keyword_filters)
        # 货币相关：单独处理，要求有“币种 + 场景”上下文，减少噪音
        self.currency_keywords = [
            "usd", "美元", "eur", "欧元", "gbp", "英镑", "jpy", "日元", "chf", "瑞郎",
            "aud", "澳元", "cad", "加元", "nzd", "纽元", "cny", "人民币", "rmb"
        ]
        self.currency_context_keywords = [
            "汇率", "外汇", "fx", "forex", "走强", "走弱", "升值", "贬值", "升势", "跌幅",
            "加息", "降息", "利率", "货币政策", "美元指数", "dxy", "通胀", "通货膨胀", "cpi", "ppi"
        ]
        self.currency_kw_regexes = self._build_keyword_regexes(self.currency_keywords)
        self.currency_ctx_regexes = self._build_keyword_regexes(self.currency_context_keywords)

        # 初始化数据库
        self.init_database()

    def _has_chinese(self, text: str) -> bool:
        """检测字符串中是否包含中文字符"""
        if not text:
            return False
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def init_database(self):
        """初始化新闻数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS financial_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id TEXT UNIQUE,
                    title TEXT NOT NULL,
                    title_cn TEXT,
                    content TEXT,
                    summary TEXT,
                    summary_cn TEXT,
                    source TEXT,
                    url TEXT,
                    published_at TIMESTAMP,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    symbols TEXT,
                    sentiment TEXT,
                    impact_level TEXT,
                    category TEXT,
                    raw_data TEXT
                )
            """)

            # 迁移：为已有数据库添加 title_cn 列
            try:
                conn.execute("ALTER TABLE financial_news ADD COLUMN title_cn TEXT")
                logger.info("✅ Added title_cn column to financial_news table")
            except sqlite3.OperationalError:
                pass  # 列已存在

            # 创建索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_financial_news_published
                ON financial_news(published_at DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_financial_news_news_id
                ON financial_news(news_id)
            """)

            logger.info("✅ Financial news table initialized")

    def get_auth_message(self) -> dict:
        """构建认证消息（新闻端点不需要订阅）"""
        return {
            "api_key": self.api_key
        }

    def get_reconnect_delay(self) -> float:
        """计算重连延迟（指数退避，封顶300s；指数也封顶避免大整数运算）"""
        delay = min(self.base_reconnect_delay * (2 ** min(self.reconnect_attempts, 10)), 300)
        return delay

    def check_rate_limit(self) -> bool:
        """检查是否超过速率限制"""
        now = time.time()
        while self.message_timestamps and (now - self.message_timestamps[0]) > 300:
            self.message_timestamps.popleft()

        if len(self.message_timestamps) >= 300:
            return False

        self.message_timestamps.append(now)
        return True

    def _log_error(self, message: str, error_type: str = "general"):
        """限制错误日志频率"""
        now = time.time()
        self.consecutive_errors += 1

        if now - self.last_error_log_time > self.error_log_interval:
            if self.consecutive_errors > 1:
                logger.error(f"❌ {message} (occurred {self.consecutive_errors} times)")
            else:
                logger.error(f"❌ {message}")
            self.last_error_log_time = now
            self.consecutive_errors = 0
        elif self.consecutive_errors % 100 == 0:
            logger.warning(f"⚠️ {error_type}: {self.consecutive_errors} errors suppressed")

    async def send_ping(self, websocket):
        """定期发送 ping 保持连接"""
        try:
            while self.is_running:
                await asyncio.sleep(self.ping_interval)
                try:
                    if self.check_rate_limit():
                        await websocket.send("ping")
                        logger.debug("🏓 Sent ping to news WebSocket")
                except:
                    break
        except Exception as e:
            logger.debug(f"Ping task ended: {e}")

    def _infer_category(self, title: str, content: str, symbols: List[str]) -> str:
        """根据内容推断分类"""
        text = f"{title} {content}".lower()
        symbols_str = " ".join(symbols).lower() if symbols else ""

        # 科技股票
        if any(kw in text or kw in symbols_str for kw in ["nvda", "nvidia", "amd", "googl", "google", "meta", "facebook", "tsm", "tsmc", "taiwan semiconductor"]):
            return "tech_stocks"

        # 央行 - 使用更精确的匹配
        central_bank_keywords = [
            "federal reserve", "fed ", " fed", "fomc",
            "people's bank of china", "pboc",
            "bank of japan", "boj ",
            "european central bank", "ecb ",
            "bank of england", "boe ",
            "reserve bank of australia", "rba ",
            "swiss national bank", "snb "
        ]
        if any(kw in text for kw in central_bank_keywords):
            return "central_banks"

        # 货币政策
        if any(kw in text for kw in ["rate hike", "rate cut", "interest rate", "monetary policy", "quantitative", "tapering", "加息", "降息", "利率"]):
            return "monetary_policy"

        # 贵金属
        if any(kw in text or kw in symbols_str for kw in ["gold", "xau", "silver", "xag", "precious metal", "黄金", "白银"]):
            return "precious_metals"

        # 加密货币
        if any(kw in text or kw in symbols_str for kw in ["btc", "bitcoin", "eth", "ethereum", "crypto", "cryptocurrency", "sol", "bnb", "stablecoin", "usdt", "usdc", "加密", "比特币", "以太坊"]):
            return "crypto"

        # 外汇
        if any(kw in text or kw in symbols_str for kw in ["forex", "fx", "eurusd", "gbpusd", "usdjpy", "currency", "dollar index", "dxy", "外汇", "汇率"]):
            return "forex"

        # 债券
        if any(kw in text for kw in ["treasury", "bond", "yield", "government bond", "国债", "债券", "收益率"]):
            return "bonds"

        # 市场指数
        if any(kw in text or kw in symbols_str for kw in ["nasdaq", "dow jones", "s&p", "nyse", "cme", "index", "指数"]):
            return "market_indices"

        # 默认分类
        return "market_indices"

    def _build_keyword_regexes(self, keywords: List[str]) -> List[re.Pattern]:
        """预编译关键词正则，英文用词边界，中文直接匹配"""
        regexes = []
        for kw in keywords:
            kw_strip = kw.strip()
            if not kw_strip:
                continue
            # 中文或包含非字母的直接转义匹配
            if re.search(r"[\u4e00-\u9fff]", kw_strip) or not re.match(r"^[a-zA-Z0-9 ]+$", kw_strip):
                regexes.append(re.compile(re.escape(kw_strip), re.IGNORECASE))
            else:
                regexes.append(re.compile(rf"\b{re.escape(kw_strip)}\b", re.IGNORECASE))
        return regexes

    def _normalize_symbols(self, symbols) -> List[str]:
        """将 symbols/tickers 统一为大写列表"""
        if isinstance(symbols, list):
            normalized = []
            for s in symbols:
                if isinstance(s, dict) and 'symbol' in s:
                    normalized.append(str(s.get('symbol', '')).upper())
                else:
                    normalized.append(str(s).upper())
            return normalized
        if isinstance(symbols, str):
            parts = re.split(r"[\s,;|]+", symbols)
            return [p.upper() for p in parts if p]
        return []

    def can_summarize(self) -> bool:
        """检查 OpenAI 调用速率是否超限"""
        now = time.time()
        window = 60  # 秒
        while self.summary_timestamps and (now - self.summary_timestamps[0]) > window:
            self.summary_timestamps.popleft()
        if len(self.summary_timestamps) >= self.summary_limit_per_minute:
            return False
        self.summary_timestamps.append(now)
        return True

    def should_process(self, news_item: dict) -> bool:
        """
        判断新闻是否需要处理/总结，避免对不相关新闻调用 OpenAI
        规则：
        - symbols 包含关注的品类
        - 标题/内容包含关键字（中美日 + BTC/ETH/黄金/白银）
        - 货币类需同时出现币种和上下文（汇率/外汇/走强/走弱/加息/降息等）
        """
        try:
            # 符号匹配
            symbols = news_item.get('symbols') or news_item.get('tickers') or []
            symbol_list = self._normalize_symbols(symbols)
            if self.symbol_filters.intersection(set(symbol_list)):
                return True

            # 关键字匹配
            title = news_item.get('title', '') or news_item.get('headline', '')
            content = news_item.get('content', '') or news_item.get('description', '')
            text = f"{title}\n{content}"
            for regex in self.keyword_regexes:
                if regex.search(text):
                    return True
            if self._contains_currency_with_context(text):
                return True
        except Exception as e:
            logger.debug(f"Filter check failed: {e}")
        return False

    def _contains_currency_with_context(self, text: str) -> bool:
        """币种 + 上下文双命中才算，避免单独提到美元等导致噪音"""
        has_currency = any(regex.search(text) for regex in self.currency_kw_regexes)
        if not has_currency:
            return False
        return any(regex.search(text) for regex in self.currency_ctx_regexes)

    def _is_duplicate(self, conn: sqlite3.Connection, title: str, published_at: int) -> bool:
        """判重：同标题且发布时间在 10 分钟内视为重复"""
        try:
            if not title or not published_at:
                return False
            cursor = conn.execute(
                """
                SELECT 1 FROM financial_news
                WHERE LOWER(title) = ? AND ABS(published_at - ?) <= 600
                LIMIT 1
                """,
                (title.strip().lower(), int(published_at)),
            )
            return cursor.fetchone() is not None
        except Exception as e:
            logger.debug(f"Duplicate check failed: {e}")
            return False

    async def summarize_with_chatgpt(self, news_item: dict) -> Dict[str, object]:
        """
        使用 ChatGPT 总结新闻并抽取情绪/标的/影响级别
        如果没有返回中文摘要，会重试最多2次
        """
        try:
            title = news_item.get('title', '')
            content = news_item.get('content', news_item.get('description', ''))

            # 如果没有内容，使用标题
            text_to_summarize = content if content else title

            # 调用 LLM API（OpenAI 兼容协议，默认 DeepSeek，见模块顶部配置）
            url = f"{NEWS_LLM_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }

            max_retries = 3  # 最多尝试3次（初次 + 2次重试）
            for attempt in range(max_retries):
                # 如果是重试，加强中文摘要的要求
                system_content = (
                    "You are a financial markets analyst. Only process items that have clear financial/market relevance "
                    "(macroeconomics, monetary policy, FX/rates, commodities, crypto, equities, earnings, M&A, regulation, credit, funds). "
                    "Ignore travel/route/consumer lifestyle announcements unless they contain material financial impact. "
                    "Return a concise JSON object with keys: "
                    "is_financial (boolean, true only if the item is financially relevant), "
                    "title_cn (简洁的中文标题翻译 - REQUIRED, MUST BE IN CHINESE), "
                    "summary_en (concise professional English summary), "
                    "summary_cn (简洁的中文总结 - REQUIRED, MUST BE IN CHINESE), "
                    "sentiment (MUST be one of: positive/negative/neutral), "
                    "symbols (array of main tickers or commodities, e.g., BTC, ETH, XAU, XAG, currency pairs), "
                    "impact_level (MUST be one of: high/medium/low), "
                    "category (REQUIRED, MUST be EXACTLY one of these 8: tech_stocks/market_indices/precious_metals/bonds/forex/central_banks/monetary_policy/crypto). "
                    "Do not include any additional text."
                )

                if attempt > 0:
                    system_content += " IMPORTANT: You MUST provide title_cn and summary_cn in Chinese language (中文). This is mandatory."

                user_content = f"""Summarize this financial news in 2-3 sentences:

Title: {title}
Content: {text_to_summarize}

Provide analysis with:
1. Chinese title translation (简洁的中文标题) - THIS IS REQUIRED, MUST BE IN CHINESE LANGUAGE
2. English summary (concise, professional)
3. Chinese summary (简洁专业的中文总结) - THIS IS REQUIRED, MUST BE IN CHINESE LANGUAGE
4. Sentiment: positive/negative/neutral
5. Impact level: high/medium/low
6. Symbols: list of impacted tickers/commodities (e.g., BTC, ETH, XAU, XAG, EURUSD)
7. Category: MUST be EXACTLY one of these 8 categories (choose the most relevant):
   - tech_stocks (for NVDA, AMD, GOOGL, META, TSM, tech companies)
   - market_indices (for NASDAQ, DOW, NYSE, CME, stock indices)
   - precious_metals (for Gold, Silver, XAU, XAG)
   - bonds (for Treasury, Yields, Government Bonds)
   - forex (for Currency pairs, FX rates, dollar index)
   - central_banks (for Fed, PBOC, BOJ, ECB, BOE, SNB, RBA actions)
   - monetary_policy (for Rate decisions, QE, inflation, policy changes)
   - crypto (for BTC, ETH, altcoins, stablecoins, crypto markets)

Respond ONLY with JSON:
{{
  "is_financial": true|false,
  "title_cn": "必须是中文标题",
  "summary_en": "...",
  "summary_cn": "必须是中文摘要",
  "sentiment": "positive|negative|neutral",
  "symbols": ["..."],
  "impact_level": "high|medium|low",
  "category": "..."
}}"""

                if attempt > 0:
                    user_content += f"\n\nIMPORTANT: Previous attempt did not include Chinese content. You MUST provide title_cn and summary_cn in Chinese (中文). This is attempt {attempt + 1} of {max_retries}."

                payload = {
                    "model": NEWS_LLM_MODEL,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": system_content
                        },
                        {
                            "role": "user",
                            "content": user_content
                        }
                    ],
                    "temperature": 0.3,
                    "max_tokens": NEWS_LLM_MAX_TOKENS
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=payload, timeout=30) as response:
                        if response.status == 200:
                            data = await response.json()
                            summary_text = data['choices'][0]['message']['content'].strip()

                            def _parse_response(text: str) -> Dict[str, object]:
                                try:
                                    return json.loads(text)
                                except json.JSONDecodeError:
                                    # 尝试从混入文本中提取 JSON
                                    start = text.find("{")
                                    end = text.rfind("}")
                                    if start != -1 and end != -1 and end > start:
                                        try:
                                            return json.loads(text[start:end + 1])
                                        except json.JSONDecodeError:
                                            pass
                                    return {}

                            parsed = _parse_response(summary_text)

                            # 检查是否有中文摘要和中文标题，以及是否真的是中文
                            summary_cn = parsed.get("summary_cn", "")
                            title_cn = parsed.get("title_cn", "")
                            has_chinese_summary = bool(summary_cn) and any('\u4e00' <= char <= '\u9fff' for char in summary_cn)
                            has_chinese_title = bool(title_cn) and any('\u4e00' <= char <= '\u9fff' for char in title_cn)
                            has_chinese = has_chinese_summary and has_chinese_title

                            if not has_chinese and attempt < max_retries - 1:
                                logger.warning(f"⚠️ Attempt {attempt + 1}: No Chinese summary received for: {title[:50]}... Retrying...")
                                await asyncio.sleep(0.5)  # 短暂延迟避免过快重试
                                continue  # 重试

                            # 调试日志
                            if not parsed.get("summary_en") or not has_chinese_summary or not has_chinese_title:
                                logger.warning(f"⚠️ GPT returned incomplete summary/title for: {title[:50]}... (attempt {attempt + 1})")
                                logger.debug(f"GPT response: {summary_text[:500]}")

                            # 兜底保证字段存在
                            allowed_sentiments = {"positive", "negative", "neutral"}
                            allowed_impacts = {"high", "medium", "low"}

                            # 如果解析失败，使用标题作为默认摘要
                            default_summary = title

                            # 确保摘要是纯文本，不是JSON字符串
                            summary_en = parsed.get("summary_en") or default_summary
                            if not has_chinese_summary:
                                summary_cn = default_summary  # 最后的兜底：使用英文标题
                                logger.warning(f"⚠️ Using English title as Chinese summary fallback after {attempt + 1} attempts")
                            if not has_chinese_title:
                                title_cn = default_summary  # 兜底：使用英文标题
                                logger.warning(f"⚠️ Using English title as Chinese title fallback after {attempt + 1} attempts")

                            # 如果摘要仍然是JSON字符串，尝试提取内容
                            if summary_en and summary_en.startswith('{'):
                                summary_en = default_summary
                            if summary_cn and summary_cn.startswith('{'):
                                summary_cn = default_summary
                            if title_cn and title_cn.startswith('{'):
                                title_cn = default_summary

                            result = {
                                "is_financial": bool(parsed.get("is_financial", True)),
                                "title_cn": title_cn,
                                "summary_en": summary_en,
                                "summary_cn": summary_cn,
                                "sentiment": parsed.get("sentiment", "").lower(),
                                "symbols": parsed.get("symbols", []),
                                "impact_level": parsed.get("impact_level", "").lower(),
                                "category": parsed.get("category", "").lower()
                            }

                            # 验证分类
                            allowed_categories = {"tech_stocks", "market_indices", "precious_metals", "bonds", "forex", "central_banks", "monetary_policy", "crypto"}

                            if result["sentiment"] not in allowed_sentiments:
                                result["sentiment"] = ""
                            if result["impact_level"] not in allowed_impacts:
                                result["impact_level"] = ""
                            if result["category"] not in allowed_categories:
                                # 如果GPT没有返回有效分类，尝试根据内容推断
                                result["category"] = self._infer_category(title, text_to_summarize, result.get("symbols", []))
                            if not isinstance(result["symbols"], list):
                                result["symbols"] = []

                            logger.info(f"✅ Generated summary for: {title[:50]}... (attempt {attempt + 1})")
                            if summary_cn == default_summary or summary_en == default_summary:
                                # 调试日志：记录兜底回退，便于排查 GPT 返回不完整的情况
                                logger.debug(
                                    "GPT summary fallback used for title='%s' | parsed_keys=%s | raw=%s",
                                    title[:80],
                                    list(parsed.keys()),
                                    summary_text[:300]
                                )
                            return result
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ OpenAI API error {response.status}: {error_text}")
                            # API错误，不重试
                            return {
                                "title_cn": title,
                                "summary_en": title,
                                "summary_cn": title,
                                "sentiment": "",
                                "symbols": [],
                                "impact_level": "",
                                "category": ""
                            }

        except asyncio.TimeoutError:
            logger.error("❌ OpenAI API timeout")
            return {
                "is_financial": True,
                "title_cn": title,
                "summary_en": title,
                "summary_cn": title,
                "sentiment": "",
                "symbols": [],
                "impact_level": "",
                "category": ""
            }
        except Exception as e:
            logger.error(f"❌ Error generating summary: {e}")
            title_fallback = news_item.get('title', '')
            return {
                "is_financial": True,
                "title_cn": title_fallback,
                "summary_en": title_fallback,
                "summary_cn": title_fallback,
                "sentiment": "",
                "symbols": [],
                "impact_level": ""
            }

    async def save_news_to_db(self, news_item: dict):
        """保存新闻到数据库"""
        try:
            if not self.openai_api_key:
                logger.warning("⚠️ OPENAI_API_KEY missing, save title only to avoid empty summaries")
                await self.save_title_only(news_item)
                return

            if not self.can_summarize():
                logger.warning("⏸️ Summary rate limit reached, saving title only")
                await self.save_title_only(news_item)
                return

            llm_result = None
            summary_en = ""
            summary_cn = ""
            title_cn = ""

            # 最多尝试两次，避免因偶发返回不含中文导致落盘空中文
            for attempt in (1, 2):
                llm_result = await self.summarize_with_chatgpt(news_item)
                summary_en = llm_result.get("summary_en", "")
                summary_cn = llm_result.get("summary_cn", "")
                title_cn = llm_result.get("title_cn", "")

                if self._has_chinese(summary_cn) and self._has_chinese(title_cn):
                    break

                if attempt == 1:
                    logger.warning(f"⚠️ GPT returned no Chinese summary/title, retrying once: {news_item.get('title', '')[:60]}")
                    await asyncio.sleep(0.5)
                else:
                    # 第二次仍无中文，记录告警并用英文兜底，避免空字段
                    logger.warning(f"⚠️ GPT still missing Chinese content, fallback to English: {news_item.get('title', '')[:60]}")
                    if summary_en and not self._has_chinese(summary_cn):
                        summary_cn = summary_en
                    if not self._has_chinese(title_cn):
                        title_cn = news_item.get('title', '')
                    llm_result["summary_cn"] = summary_cn
                    llm_result["title_cn"] = title_cn

            if llm_result and llm_result.get("is_financial") is False:
                logger.info(f"🪙 Skipped non-financial item: {news_item.get('title', '')[:60]}...")
                return
            summary_en = summary_en or llm_result.get("summary_en", "")
            summary_cn = summary_cn or llm_result.get("summary_cn", "")
            title_cn = title_cn or llm_result.get("title_cn", "")

            # 提取字段
            news_id = news_item.get('id', news_item.get('news_id', str(int(time.time() * 1000))))
            title = news_item.get('title', 'Untitled')
            source = news_item.get('source', news_item.get('provider', 'InsightSentry'))

            # 时间戳处理
            published_at = news_item.get('published_at', news_item.get('timestamp', news_item.get('time')))
            if published_at:
                if isinstance(published_at, (int, float)):
                    if published_at < 10000000000:
                        published_at = int(published_at)
                    else:
                        published_at = int(published_at / 1000)
            else:
                published_at = int(time.time())

            # 提取相关产品代码
            symbols_raw = llm_result.get("symbols") or news_item.get('symbols', news_item.get('tickers', []))
            symbols_list = self._normalize_symbols(symbols_raw)
            symbols = json.dumps(symbols_list) if symbols_list else '[]'

            # 情绪、影响级别和分类
            sentiment = llm_result.get("sentiment") or news_item.get('sentiment', '')
            impact_level = llm_result.get("impact_level") or news_item.get('impact', news_item.get('importance', ''))
            category = llm_result.get("category", '')

            # 插入数据库
            with sqlite3.connect(self.db_path) as conn:
                if self._is_duplicate(conn, title, published_at):
                    logger.info(f"⏭️ Skip duplicate news: {title[:60]}...")
                    return
                conn.execute("""
                    INSERT OR REPLACE INTO financial_news
                    (news_id, title, title_cn, content, summary, summary_cn, source, url,
                     published_at, symbols, sentiment, impact_level, category, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    news_id, title, title_cn, '', summary_en, summary_cn, source, '',
                    published_at, symbols, sentiment, impact_level, category, ''
                ))

            logger.info(f"💾 Saved news: {title[:60]}...")

            # 调用回调函数（通知前端）
            if self.news_callback:
                news_with_summary = {
                    'id': news_id,
                    'title': title,
                    'title_cn': title_cn,
                    'content': '',
                    'summary': summary_en,
                    'summary_cn': summary_cn,
                    'source': source,
                    'url': '',
                    'published_at': published_at,
                    'symbols': json.loads(symbols) if symbols else [],
                    'sentiment': sentiment,
                    'impact_level': impact_level,
                    'category': category
                }
                await self.news_callback(news_with_summary)

        except Exception as e:
            logger.error(f"❌ Error saving news to DB: {e}")

    async def save_title_only(self, news_item: dict):
        """
        仅保存标题，不调用 OpenAI，供未触发关键词的新闻使用
        """
        try:
            news_id = news_item.get('id', news_item.get('news_id', str(int(time.time() * 1000))))
            title = news_item.get('title', news_item.get('headline', 'Untitled'))
            source = news_item.get('source', news_item.get('provider', 'InsightSentry'))

            published_at = news_item.get('published_at', news_item.get('timestamp', news_item.get('time')))
            if published_at:
                if isinstance(published_at, (int, float)):
                    if published_at < 10000000000:
                        published_at = int(published_at)
                    else:
                        published_at = int(published_at / 1000)
            else:
                published_at = int(time.time())

            symbols_raw = news_item.get('symbols', news_item.get('tickers', []))
            symbols_list = self._normalize_symbols(symbols_raw)
            symbols = json.dumps(symbols_list) if symbols_list else '[]'

            sentiment = news_item.get('sentiment', '')
            impact_level = news_item.get('impact', news_item.get('importance', ''))

            with sqlite3.connect(self.db_path) as conn:
                if self._is_duplicate(conn, title, published_at):
                    logger.info(f"⏭️ Skip duplicate title-only news: {title[:60]}...")
                    return
                conn.execute("""
                    INSERT OR IGNORE INTO financial_news
                    (news_id, title, content, summary, summary_cn, source, url,
                     published_at, symbols, sentiment, impact_level, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    news_id, title, '', '', '', source, '',
                    published_at, symbols, sentiment, impact_level, ''
                ))

            logger.info(f"📝 Saved title only: {title[:60]}...")
        except Exception as e:
            logger.error(f"❌ Error saving title-only news: {e}")

    async def handle_news_message(self, data: dict):
        """处理新闻消息"""
        try:
            # InsightSentry 可能发送单条新闻或数组
            if isinstance(data, list):
                for news_item in data:
                    if self.should_process(news_item):
                        await self.save_news_to_db(news_item)
                    else:
                        await self.save_title_only(news_item)
            elif isinstance(data, dict):
                # 检查是否是新闻项
                if 'title' in data or 'headline' in data:
                    if self.should_process(data):
                        await self.save_news_to_db(data)
                    else:
                        await self.save_title_only(data)
                # 或者是包含新闻数组的对象
                elif 'news' in data:
                    news_items = data.get('news', [])
                    for news_item in news_items:
                        if self.should_process(news_item):
                            await self.save_news_to_db(news_item)
                        else:
                            await self.save_title_only(news_item)
                elif 'items' in data:
                    news_items = data.get('items', [])
                    for news_item in news_items:
                        if self.should_process(news_item):
                            await self.save_news_to_db(news_item)
                        else:
                            await self.save_title_only(news_item)

        except Exception as e:
            logger.error(f"❌ Error handling news message: {e}")

    async def connect_and_listen(self):
        """连接到 WebSocket 并监听新闻"""
        while self.is_running:
            try:
                # 指数退避重连
                if self.reconnect_attempts > 0:
                    delay = self.get_reconnect_delay()
                    logger.info(f"⏳ News WS reconnecting in {delay}s (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
                    await asyncio.sleep(delay)

                logger.info(f"🔌 Connecting to InsightSentry News WebSocket...")

                async with websockets.connect(
                    self.WS_URL,
                    open_timeout=15,
                    close_timeout=10,
                    ping_interval=None,
                    ping_timeout=None
                ) as websocket:
                    self.websocket = websocket
                    logger.info(f"✅ Connected to {self.WS_URL}")
                    self.reconnect_attempts = 0
                    self.consecutive_errors = 0

                    # 发送认证消息
                    if self.check_rate_limit():
                        auth_msg = self.get_auth_message()
                        await websocket.send(json.dumps(auth_msg))
                        logger.info("📤 Authentication sent to news feed")

                    self._last_message_time = time.time()

                    # 启动 ping 任务
                    self._ping_task = asyncio.create_task(self.send_ping(websocket))

                    message_count = 0
                    last_log_time = time.time()
                    no_message_count = 0

                    logger.info("👂 Listening for news messages...")

                    while self.is_running:
                        try:
                            # 30秒超时等待消息
                            message = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                            no_message_count = 0
                            self.consecutive_errors = 0

                            # 处理 pong 响应
                            if message == "pong":
                                self._last_pong_time = time.time()
                                logger.debug("🏓 Received pong from news WebSocket")
                                continue

                            data = json.loads(message)
                            self._last_message_time = time.time()
                            message_count += 1

                            # 每60秒记录一次统计
                            if time.time() - last_log_time > 60:
                                logger.info(f"📊 News WS stats: {message_count} messages received")
                                last_log_time = time.time()

                            # 处理不同类型的消息
                            if isinstance(data, dict):
                                # 服务器心跳
                                if 'timestamp' in data and len(data) == 1:
                                    logger.debug(f"💓 Server heartbeat: {data['timestamp']}")
                                    continue

                                # 错误消息
                                if 'error' in data:
                                    logger.error(f"❌ Server error: {data}")
                                    if 'api_key' in str(data).lower():
                                        logger.error("API key error, stopping news client")
                                        self.is_running = False
                                        break
                                    continue

                                # 事件消息
                                if 'type' in data or 'event' in data:
                                    event_type = data.get('type', data.get('event'))
                                    if event_type in ['connected', 'authenticated', 'success']:
                                        logger.info(f"✅ News feed event: {data}")
                                        continue
                                    elif event_type == 'error':
                                        logger.error(f"❌ News feed error: {data}")
                                        continue

                                # 新闻数据
                                logger.info(f"📰 Received news update")
                                await self.handle_news_message(data)

                            elif isinstance(data, list):
                                # 新闻数组（初始连接时的 10 条最新新闻）
                                logger.info(f"📰 Received {len(data)} news items")
                                await self.handle_news_message(data)

                        except asyncio.TimeoutError:
                            # 30秒无消息
                            no_message_count += 1
                            if no_message_count == 2:  # 60秒无消息
                                logger.warning(f"⏱️ No news for 60s (news feed may be idle)")
                            elif no_message_count == 10:  # 5分钟无消息
                                logger.warning("⚠️ No news for 5 minutes, connection may be dead")
                                break
                            continue
                        except websockets.exceptions.ConnectionClosed as e:
                            # 连接被远端关闭，无需重复记录 suppressed 错误，直接跳出等待重连
                            logger.warning(f"⚠️ News WebSocket closed inside loop: code={e.code}, reason={e.reason}")
                            raise
                        except json.JSONDecodeError as e:
                            self._log_error(f"JSON decode error: {e}", "json_error")

                        except Exception as e:
                            self._log_error(f"Error processing message: {e}", "process_error")

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"⚠️ News WebSocket closed: code={e.code}, reason={e.reason}")
                self.reconnect_attempts += 1
            except websockets.exceptions.ConnectionClosedOK as e:
                # 显式处理正常关闭，保持重连逻辑一致
                logger.warning(f"⚠️ News WebSocket closed (OK): code={e.code}, reason={e.reason}")
                self.reconnect_attempts += 1
            except asyncio.TimeoutError:
                logger.warning("⚠️ News WebSocket timeout")
                self.reconnect_attempts += 1
            except Exception as e:
                logger.error(f"❌ News WebSocket error: {type(e).__name__}: {e}")
                self.reconnect_attempts += 1
            finally:
                # 清理 ping 任务
                if self._ping_task:
                    self._ping_task.cancel()
                    try:
                        await self._ping_task
                    except asyncio.CancelledError:
                        pass
                    self._ping_task = None

                if 'message_count' in locals() and message_count > 0:
                    logger.info(f"📊 Disconnect stats: {message_count} news messages received")

            # 检查是否超过最大重连次数
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                # 不放弃：上游（如 InsightSentry 502）长时间故障后自动恢复时，
                # 客户端必须还活着。按封顶退避（300s）无限重试，仅周期性告警。
                if self.reconnect_attempts % 10 == 0:
                    logger.warning(
                        f"⚠️ News WS 已连续失败 {self.reconnect_attempts} 次，"
                        f"继续按 {self.get_reconnect_delay():.0f}s 间隔重试")

            if not self.is_running:
                logger.info("🛑 News WebSocket stopping, not reconnecting")

    async def start(self):
        """启动新闻 WebSocket 客户端"""
        self.is_running = True
        self._task = asyncio.create_task(self.connect_and_listen())
        logger.info("✅ News WebSocket client started")

    async def stop(self):
        """停止新闻 WebSocket 客户端"""
        self.is_running = False

        if self.websocket:
            await self.websocket.close()

        if self._task:
            current = asyncio.current_task()
            self._task.cancel()

            # 避免在 connect_and_listen 内部自我等待导致 RuntimeError
            if self._task is not current:
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

        logger.info("🛑 News WebSocket client stopped")

    def get_latest_news(self, limit: int = 20) -> List[Dict]:
        """获取最新新闻"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT news_id, title, title_cn, content, summary, summary_cn, source, url,
                       published_at, symbols, sentiment, impact_level, category
                FROM financial_news
                ORDER BY
                    CASE WHEN summary IS NOT NULL AND summary != '' THEN 0 ELSE 1 END,
                    published_at DESC
                LIMIT ?
            """, (limit,))

            news_items = []
            for row in cursor.fetchall():
                news_items.append({
                    'id': row['news_id'],
                    'title': row['title'],
                    'title_cn': row['title_cn'],
                    'content': row['content'],
                    'summary': row['summary'],
                    'summary_cn': row['summary_cn'],
                    'source': row['source'],
                    'url': row['url'],
                    'published_at': row['published_at'],
                    'symbols': json.loads(row['symbols']) if row['symbols'] else [],
                    'sentiment': row['sentiment'],
                    'impact_level': row['impact_level'],
                    'category': row['category'],
                    'has_summary': bool(row['summary'])
                })

            return news_items

    def get_news_by_symbol(self, symbol: str, limit: int = 20) -> List[Dict]:
        """根据金融产品代码筛选新闻"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT news_id, title, title_cn, content, summary, summary_cn, source, url,
                       published_at, symbols, sentiment, impact_level
                FROM financial_news
                WHERE symbols LIKE ?
                ORDER BY
                    CASE WHEN summary IS NOT NULL AND summary != '' THEN 0 ELSE 1 END,
                    published_at DESC
                LIMIT ?
            """, (f'%{symbol}%', limit))

            news_items = []
            for row in cursor.fetchall():
                news_items.append({
                    'id': row['news_id'],
                    'title': row['title'],
                    'title_cn': row['title_cn'],
                    'content': row['content'],
                    'summary': row['summary'],
                    'summary_cn': row['summary_cn'],
                    'source': row['source'],
                    'url': row['url'],
                    'published_at': row['published_at'],
                    'symbols': json.loads(row['symbols']) if row['symbols'] else [],
                    'sentiment': row['sentiment'],
                    'impact_level': row['impact_level'],
                    'category': row['category'],
                    'has_summary': bool(row['summary'])
                })

            return news_items

    def get_split_news(
        self,
        important_limit: int = 20,
        others_limit: int = 20,
        search: Optional[str] = None,
        symbol: Optional[str] = None,
        category: Optional[str] = None,
        sentiment: Optional[str] = None,
        impact: Optional[str] = None,
    ) -> Dict[str, List[Dict]]:
        """分组获取新闻：重要（有摘要）和其他（仅标题），支持搜索与筛选"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            def row_to_dict(row, has_summary: bool) -> Dict:
                return {
                    'id': row['news_id'],
                    'title': row['title'],
                    'title_cn': row['title_cn'] if 'title_cn' in row.keys() else '',
                    'content': row['content'],
                    'summary': row['summary'],
                    'summary_cn': row['summary_cn'],
                    'source': row['source'],
                    'url': row['url'],
                    'published_at': row['published_at'],
                    'symbols': json.loads(row['symbols']) if row['symbols'] else [],
                    'sentiment': row['sentiment'],
                    'impact_level': row['impact_level'],
                    'category': row['category'] if 'category' in row.keys() else '',
                    'has_summary': has_summary
                }

            # 构建筛选条件
            filters = []
            params: List = []

            if search:
                keyword = f"%{search.strip()}%"
                filters.append("(title LIKE ? OR content LIKE ? OR summary LIKE ? OR summary_cn LIKE ?)")
                params.extend([keyword, keyword, keyword, keyword])

            if symbol:
                filters.append("symbols LIKE ?")
                params.append(f"%{symbol}%")

            if category:
                filters.append("LOWER(category) = ?")
                params.append(category.lower())

            if sentiment:
                filters.append("LOWER(sentiment) = ?")
                params.append(sentiment.lower())

            if impact:
                filters.append("LOWER(impact_level) = ?")
                params.append(impact.lower())

            filter_clause = " AND ".join(filters)

            def build_query(has_summary: bool) -> tuple[str, List]:
                summary_condition = "summary IS NOT NULL AND summary != ''" if has_summary else "(summary IS NULL OR summary = '')"
                where_parts = [summary_condition]
                if filter_clause:
                    where_parts.append(filter_clause)
                where_sql = " AND ".join(where_parts)
                return f"""
                    SELECT news_id, title, title_cn, content, summary, summary_cn, source, url,
                           published_at, symbols, sentiment, impact_level, category
                    FROM financial_news
                    WHERE {where_sql}
                    ORDER BY published_at DESC
                    LIMIT ?
                """, params + [important_limit if has_summary else others_limit]

            # 重要新闻：有摘要
            important_sql, important_params = build_query(True)
            cursor = conn.execute(important_sql, important_params)
            important = [row_to_dict(row, True) for row in cursor.fetchall()]

            # 其他新闻：无摘要
            others_sql, others_params = build_query(False)
            cursor = conn.execute(others_sql, others_params)
            others = [row_to_dict(row, False) for row in cursor.fetchall()]

            return {"important": important, "others": others}


# 测试代码
if __name__ == "__main__":
    async def test():
        # 测试用的 API keys
        insightsentry_key = "your_insightsentry_api_key"
        openai_key = "your_openai_api_key"

        async def on_news_update(news):
            print(f"\n📰 New news received:")
            print(f"   Title: {news['title']}")
            print(f"   Summary (EN): {news['summary']}")
            print(f"   Summary (CN): {news['summary_cn']}")

        client = NewsWebSocketClient(
            api_key=insightsentry_key,
            openai_api_key=openai_key,
            news_callback=on_news_update
        )

        await client.start()

        # 运行 5 分钟后停止
        await asyncio.sleep(300)

        # 获取最新新闻
        latest = client.get_latest_news(10)
        print(f"\n✅ Latest {len(latest)} news items:")
        for news in latest:
            print(f"  - {news['title']}")

        await client.stop()

    asyncio.run(test())
