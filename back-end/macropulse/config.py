"""MacroPulse 配置。沿用 analytics/config.py 的 os.getenv + 默认值约定，
不引入 pydantic settings。所有 S3 资源默认复用 FXLab 数据湖。
"""

import os

from dotenv import load_dotenv

# 与 backend 主服务一致：就近加载 back-end/.env（ANTHROPIC_API_KEY、AWS 凭证等）。
# 从 back-end/ 运行 `python -m macropulse...` 时会找到该文件；未找到则静默跳过。
load_dotenv()

# S3 数据湖（与 analytics 复用同一 bucket / region）
S3_BUCKET = os.getenv("MACRO_S3_BUCKET", os.getenv("ANALYTICS_S3_BUCKET", "fxlab-data-lake"))
S3_REGION = os.getenv("MACRO_S3_REGION", os.getenv("ANALYTICS_S3_REGION", "ap-southeast-2"))

# S3 key 约定（对齐 raw/xau、raw/news）
RAW_MACRO_PREFIX = "raw/macro"
# 去重水位线 / 幂等清单：document_id -> {content_hash, keys, retrieved_at}
MANIFEST_KEY = "metadata/macro_ingest_manifest.json"

# 抓取礼貌设置：自报身份 + 限速，遵守各央行 robots.txt
USER_AGENT = os.getenv(
    "MACRO_USER_AGENT",
    "MacroPulse/0.1 (research project; +https://github.com/o897867/fxlab-market-data-pipeline)",
)
REQUEST_TIMEOUT = int(os.getenv("MACRO_REQUEST_TIMEOUT", "20"))
# 相邻请求最小间隔（秒），避免给央行官网压力
REQUEST_DELAY = float(os.getenv("MACRO_REQUEST_DELAY", "1.0"))

# 回填窗口（年）。第一期目标：近三年 FOMC 声明
BACKFILL_YEARS = int(os.getenv("MACRO_BACKFILL_YEARS", "3"))

# ---- LLM 抽取层（鹰鸽打分）。API key 走 ANTHROPIC_API_KEY 环境变量（SDK 自动读取），
# 不在此处持有。Max 订阅不覆盖 API 计费——需在 console 充 API 余额。
EXTRACT_MODEL = os.getenv("MACRO_EXTRACT_MODEL", "claude-opus-4-8")
SCORES_PREFIX = "analysis/macro/fed/scores"
EXTRACTION_MANIFEST_KEY = "metadata/macro_extraction_manifest.json"

# ---- 归因回测（鹰鸽分数 vs 声明后 XAU 实际反应）
# 价格源：复用 backend 的 SQLite（xau_candles_1m 是权威最新副本）。
# 仅 XAU 可用（无 DXY/US2Y）；XAU 1m 历史从 2025-10 起，只覆盖最近数次 FOMC。
PRICE_DB_PATH = os.getenv("MACRO_PRICE_DB",
                          os.path.join(os.path.dirname(os.path.dirname(__file__)), "shopback_data.db"))
ATTRIBUTION_PREFIX = "analysis/macro/fed/attribution"
# 事件窗口（分钟）。声明 14:00 ET 释放后的反应窗。
ATTRIBUTION_WINDOWS_MIN = [15, 60, 1440]
