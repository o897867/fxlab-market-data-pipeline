"""已实现波动率（HV）—— IV Rank 冷启动期的"贵贱"参照系。

产品只翻译不预测：要说"期权现在贵不贵"，需要一把尺子。IV Rank 那把尺子是"这票自己过去
一年的 IV 区间"，得攒够历史才有意义。但**已实现波动（HV）这把尺子今天就现成**——从股价
历史直接算，无需等 IV 快照积累。对比"市场为未来定的波动(IV)"和"这票过去实际走的波动(HV)"
就是一句纯事实翻译，不是预测。这也是路线图风险登记簿写明的冷启动过渡方案。

逐票拉 InsightSentry 日线（复用 XAU 那套 /symbols/{code}/series 端点与同一把 token），
算年化 HV20 / HV252，缓存到 data/hv.json，供 panels 读。每日 cron 刷新（HV 变化慢，日更足够）。

  python -m option.realized_vol            # 刷新全 watchlist
"""

from __future__ import annotations

import os
import json
import math
import time
import logging
import urllib.parse

import requests

from option import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("option.realized_vol")

_HEADERS = {"Authorization": f"Bearer {config.IS_TOKEN}"}
CACHE_PATH = os.path.join(config.SNAPSHOT_DIR, "..", "hv.json")
TRADING_DAYS = 252


def fetch_closes(code: str, dp: int = 260) -> list[float]:
    """拉最近 dp 根日线收盘价（升序）。"""
    url = f"{config.IS_BASE_URL}/symbols/{urllib.parse.quote(code, safe='')}/series"
    params = {"bar_type": "day", "bar_interval": "1", "extended": "false",
              "dadj": "false", "badj": "true", "dp": str(dp), "long_poll": "false"}
    r = requests.get(url, params=params, headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    d = r.json()
    bars = d.get("series", d.get("bars", d if isinstance(d, list) else []))
    return [b["close"] for b in bars if b.get("close")]


def annualized_hv(closes: list[float], window: int) -> float | None:
    """年化已实现波动 = 日对数收益的样本标准差 × √252。窗口内点数不足则 None。"""
    cl = closes[-(window + 1):]
    if len(cl) < max(3, window // 2):   # 数据太少不硬算，交给下游标注
        return None
    rets = [math.log(cl[i] / cl[i - 1]) for i in range(1, len(cl)) if cl[i - 1] > 0]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


# 前端 band chart 走势线要的近期收盘根数（约一个月交易日）。
SPARK_TAIL = 24


def compute(code: str) -> dict | None:
    closes = fetch_closes(code)
    if not closes:
        return None
    tail = [round(float(c), 2) for c in closes[-SPARK_TAIL:]]
    # 今日涨跌% = 最新收盘 vs 前一根收盘
    chg = None
    if len(closes) >= 2 and closes[-2]:
        chg = round((closes[-1] / closes[-2] - 1) * 100, 2)
    return {"hv20": annualized_hv(closes, 20),
            "hv60": annualized_hv(closes, 60),
            "hv252": annualized_hv(closes, 252),
            "n_bars": len(closes),
            "closes_tail": tail,          # band chart 左侧真实走势
            "change_pct": chg}            # 头部/切股器的今日涨跌


def refresh(symbols=None, path: str = CACHE_PATH) -> dict:
    symbols = symbols or config.DEFAULT_SYMBOLS
    out = {}
    for i, s in enumerate(symbols):
        s = s.strip()
        try:
            out[s] = compute(s)
            logger.info("%s HV20=%s HV252=%s", s,
                        None if not out[s] else round(out[s]["hv20"] or 0, 3),
                        None if not out[s] else round(out[s]["hv252"] or 0, 3))
        except Exception as e:  # noqa: BLE001
            logger.error("%s HV 失败: %r", s, e)
            out[s] = None
        if i < len(symbols) - 1:
            time.sleep(config.EXTRACT_SLEEP_SEC)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=2)
    return out


def load(path: str = CACHE_PATH) -> dict:
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    print(json.dumps(refresh(), ensure_ascii=False, indent=2))
