"""下次财报日抓取：InsightSentry /v3/calendar/earnings（前向按周窗口）。

端点和经济日历一样只能往未来看，故逐票扫 w=1..MAX 直到该票出现，取其 earnings_release_date
（该周即将发布的那次）。结果缓存到 data/earnings.json，供 panels.impact 给"事件预期"
标注"财报在 X 日"。每日 cron 刷新（财报日变动慢，日更足够）。
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone

import requests

from option import config

logger = logging.getLogger("option.earnings")

EARN_URL = f"{config.IS_BASE_URL}/calendar/earnings"
_HEADERS = {"Authorization": f"Bearer {config.IS_TOKEN}"}
CACHE_PATH = os.path.join(config.SNAPSHOT_DIR, "..", "earnings.json")
# 逐周扫描上限：覆盖一个季度多即可；远期财报（>10 周）不必逐周探，省调用。
MAX_WEEKS = int(os.getenv("OPTION_EARNINGS_MAX_WEEKS", "10"))


def _to_iso(v) -> str | None:
    if not v:
        return None
    try:
        ts = int(v)
        ts = ts / 1000 if ts > 10_000_000_000 else ts
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(v)[:10] if isinstance(v, str) else None


def fetch_next_earnings(symbol: str, max_weeks: int = MAX_WEEKS) -> dict | None:
    """逐周扫描，返回该票最近一次即将发布的财报 {date, eps_forecast}。"""
    for w in range(1, max_weeks + 1):
        try:
            r = requests.get(EARN_URL, params={"code": symbol, "w": w},
                             headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
            r.raise_for_status()
            for row in r.json().get("data", []):
                # earnings_release_next_date = 下一次（即将）发布；release_date 是上一次
                if row.get("code") == symbol and row.get("earnings_release_next_date"):
                    return {"date": _to_iso(row["earnings_release_next_date"]),
                            "eps_forecast": row.get("earnings_per_share_forecast_next_fq")
                            or row.get("earnings_per_share_forecast_fq")}
        except Exception as e:  # noqa: BLE001
            logger.warning("%s earnings w=%d 失败: %r", symbol, w, e)
    return None


def refresh(symbols=None, path: str = CACHE_PATH) -> dict:
    symbols = symbols or config.DEFAULT_SYMBOLS
    out = {}
    for s in symbols:
        e = fetch_next_earnings(s.strip())
        out[s.strip()] = e
        logger.info("%s 下次财报: %s", s, e)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=2)
    return out


def load(path: str = CACHE_PATH) -> dict:
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print(json.dumps(refresh(), ensure_ascii=False, indent=2))
