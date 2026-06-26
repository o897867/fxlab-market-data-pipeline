"""OptionLens 配置。沿用 FXLab 的 os.getenv + 默认值约定。"""

import os

from dotenv import load_dotenv

load_dotenv()

IS_BASE_URL = "https://api.insightsentry.com/v3"
# InsightSentry Bearer Token：优先环境变量，回退到仓库既用的 ultra key（与 XAU/news 同一把）。
IS_TOKEN = os.getenv("INSIGHTSENTRY_TOKEN", (
    "eyJhbGciOiJIUzI1NiJ9.eyJ1dWlkIjoic3V5aW5nY2luQGdtYWlsLmNvbSIsInBsYW4iOiJ1bHRyYS"
    "IsIm5ld3NmZWVkX2VuYWJsZWQiOnRydWUsIndlYnNvY2tldF9zeW1ib2xzIjo1LCJ3ZWJzb2NrZXRfY29"
    "ubmVjdGlvbnMiOjF9.6aA_ND-9NmZI2-8mILRJeZDLt9Y6skrtsNbzP0FeQVI"))

REQUEST_TIMEOUT = int(os.getenv("OPTION_REQUEST_TIMEOUT", "30"))

# 快照 Parquet 落地目录（本地；data/ 已 gitignore）。dbt 通过 read_parquet 读这里。
SNAPSHOT_DIR = os.getenv(
    "OPTION_SNAPSHOT_DIR",
    os.path.join(os.path.dirname(__file__), "data", "snapshots"))

# 现价 ±range% 的行权价（保证分布面板两侧虚值墙都拿得到）
DEFAULT_RANGE_PCT = int(os.getenv("OPTION_RANGE_PCT", "20"))

# v1 先锁流动性好的标的（doc：MU/SPY 这类）
DEFAULT_SYMBOLS = os.getenv(
    "OPTION_SYMBOLS", "NASDAQ:MU,AMEX:SPY,NYSE:ORCL,NASDAQ:GOOG").split(",")

# dbt-duckdb 产物库（mart_* 在 main_marts schema）。服务层只读它出三面板。
DUCKDB_PATH = os.getenv(
    "DBT_DUCKDB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "analytics", "dbt", "eventstudy.duckdb"))

# 选到期日时跳过的最小剩余天数（避开 0DTE/当周噪声）
MIN_DTE = int(os.getenv("OPTION_MIN_DTE", "7"))
