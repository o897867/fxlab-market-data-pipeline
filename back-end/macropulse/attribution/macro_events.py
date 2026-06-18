"""宏观数据事件（CPI / 核心PCE / 非农）—— 喂同一套归因机器。

这三个不是 LLM 打鹰鸽分，而是数值意外（surprise）。但方向上同构：
一个 hot 数据（正向意外）= 鹰派 = 压金价、推美元、抬2Y收益率，正好落在
events.INSTRUMENT_DIR 的同一根轴上。所以只要把 surprise 映射成带符号的
"分数"（overall_score），后面的 build_event / window_return / aggregate / consensus
全部原样复用。

两个来源、两种 surprise，诚实分标：
  - 历史轨（FRED）：FRED 无 consensus，用"该期指标 vs 近 12 期均值"的标准化偏离
    作 surprise 代理（surprise_source='fred_proxy'）。
  - 前向轨（InsightSentry 日历）：有 forecast 真 consensus，
    surprise = actual − forecast（surprise_source='consensus'）。

落 SQLite（和价格同库，join 零摩擦，N 又小）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# 目标事件规格。polarity 一律"热=鹰派"（正 surprise → 正 overall_score），
# 故无需逐事件极性；surprise 的符号直接喂 expected_return_sign。
#   fred_series : FRED 系列 id
#   release_id  : FRED 发布日历 release id（取精确发布日）
#   kind        : 'index' → 月度指标按 MoM% 计；'level' → 月度指标按环比变动量计
#   titles      : InsightSentry 日历里的标题匹配子串（前向轨用）
@dataclass(frozen=True)
class EventSpec:
    event_type: str
    fred_series: str
    release_id: int
    kind: str
    titles: tuple


EVENT_SPECS = {
    "CPI": EventSpec("CPI", "CPIAUCSL", 10, "index",
                     ("Inflation Rate MoM", "CPI MoM", "Consumer Price Index MoM")),
    "CoreCPI": EventSpec("CoreCPI", "CPILFESL", 10, "index",
                         ("Core Inflation Rate MoM", "Core CPI MoM")),
    "CorePCE": EventSpec("CorePCE", "PCEPILFE", 54, "index",
                         ("Core PCE Price Index MoM", "Core PCE MoM")),
    "NFP": EventSpec("NFP", "PAYEMS", 50, "level",
                     ("Non Farm Payrolls", "Nonfarm Payrolls")),
}

TABLE = "macro_releases"


def ensure_table(conn: sqlite3.Connection):
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        event_type      TEXT NOT NULL,
        ref_month       TEXT NOT NULL,      -- 数据参照月 YYYY-MM-01
        release_date    TEXT NOT NULL,      -- 发布日 YYYY-MM-DD
        release_ts_ms   INTEGER NOT NULL,   -- 发布时刻毫秒 UTC（对齐 *_candles_1m.open_time）
        actual          REAL,               -- 市场反应的头条指标（MoM% 或环比变动量）
        forecast        REAL,               -- consensus（仅前向轨有）
        previous        REAL,
        surprise        REAL,               -- 原始意外（前向: actual−forecast）
        surprise_z      REAL,               -- 标准化意外，喂 overall_score
        surprise_source TEXT NOT NULL,      -- 'fred_proxy' | 'consensus'
        PRIMARY KEY (event_type, ref_month)
    )""")
    conn.commit()


def upsert(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    ensure_table(conn)
    # consensus 优于 fred_proxy：前向轨回来时覆盖历史代理值。
    conn.executemany(f"""INSERT INTO {TABLE}
        (event_type, ref_month, release_date, release_ts_ms,
         actual, forecast, previous, surprise, surprise_z, surprise_source)
        VALUES (:event_type, :ref_month, :release_date, :release_ts_ms,
                :actual, :forecast, :previous, :surprise, :surprise_z, :surprise_source)
        ON CONFLICT(event_type, ref_month) DO UPDATE SET
            release_date    = excluded.release_date,
            release_ts_ms   = excluded.release_ts_ms,
            actual          = excluded.actual,
            forecast        = COALESCE(excluded.forecast, {TABLE}.forecast),
            previous        = COALESCE(excluded.previous, {TABLE}.previous),
            surprise        = excluded.surprise,
            surprise_z      = excluded.surprise_z,
            surprise_source = excluded.surprise_source""", rows)
    conn.commit()
    return len(rows)


def zscore_last(values: list[float], window: int = 12) -> float | None:
    """末位值相对其前 window 期的标准化偏离。不足 4 期返回 None。"""
    if not values:
        return None
    hist = values[-(window + 1):-1]  # 不含当期
    if len(hist) < 4:
        return None
    mean = sum(hist) / len(hist)
    var = sum((v - mean) ** 2 for v in hist) / len(hist)
    sd = var ** 0.5
    if sd == 0:
        return None
    return round((values[-1] - mean) / sd, 4)


def load_events(conn: sqlite3.Connection, event_type: str | None = None) -> list[dict]:
    """读出事件，整形为 build_event 可吃的"分数 dict"（overall_score=surprise_z）。"""
    ensure_table(conn)
    sql = (f"SELECT event_type, ref_month, release_date, release_ts_ms, actual, "
           f"forecast, previous, surprise, surprise_z, surprise_source FROM {TABLE}")
    params: tuple = ()
    if event_type:
        sql += " WHERE event_type = ?"
        params = (event_type,)
    sql += " ORDER BY release_ts_ms ASC"
    out = []
    for r in conn.execute(sql, params):
        (etype, ref_month, rel_date, ts_ms, actual,
         forecast, previous, surprise, surprise_z, src) = r
        if surprise_z is None:
            continue  # 无意外信号的事件不进归因
        out.append({
            "event_type": etype,
            "document_id": f"{etype}-{ref_month}",
            "meeting_date": rel_date,
            "release_ts_ms": ts_ms,
            "overall_score": surprise_z,
            "confidence_overall": None,
            "actual": actual,
            "forecast": forecast,
            "previous": previous,
            "surprise": surprise,
            "surprise_source": src,
        })
    return out
