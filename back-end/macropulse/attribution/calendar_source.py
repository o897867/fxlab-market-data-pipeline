"""前向轨：InsightSentry 经济日历 → 宏观事件（真 consensus）。

REST `/v3/calendar/events?c=US&w=N`（w 只能往未来）。每条带
actual / forecast / previous + 精确发布时戳（date，UTC，分钟级）。
故前向段 surprise = actual − forecast（真 consensus，surprise_source='consensus'），
且 release_ts_ms 直接取 date，不用补 8:30。

w 没有往回参数 → 历史靠 fred_source。本源只负责"从现在起累积"，
顺带是 Telegram 实时推送的素材源（数据一出即可算 surprise + 价格反应）。
"""

from __future__ import annotations

import asyncio
import sqlite3
import logging
from datetime import datetime, timezone

import requests

from macropulse.attribution.macro_events import EVENT_SPECS, TABLE

logger = logging.getLogger(__name__)

CAL_URL = "https://api.insightsentry.com/v3/calendar/events"
POLL_INTERVAL = 86400  # 每日；宏观数据月频，日轮询足以当天捕获 actual


def _iso_to_ms(s: str) -> int:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def _ref_month(reference_date: str | None, fallback_ms: int) -> str:
    if reference_date:
        return reference_date[:7] + "-01"
    dt = datetime.fromtimestamp(fallback_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-01")


def _match_spec(title: str):
    for spec in EVENT_SPECS.values():
        if any(t in title for t in spec.titles):
            return spec
    return None


def _actual_scale(conn: sqlite3.Connection, event_type: str) -> float:
    """用表里该事件已有 actual 的总体 std 作标准化尺度（与 actual−forecast 同单位）。"""
    vals = [r[0] for r in conn.execute(
        f"SELECT actual FROM {TABLE} WHERE event_type=? AND actual IS NOT NULL "
        f"ORDER BY release_ts_ms DESC LIMIT 24", (event_type,)) if r[0] is not None]
    if len(vals) < 4:
        return 0.0
    mean = sum(vals) / len(vals)
    return (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5


def fetch_calendar(weeks: int = 1, bearer_token: str = "", country: str = "US") -> list[dict]:
    """拉 w=1..weeks 各周窗口的 US 事件（合并去重）。"""
    headers = {"Authorization": f"Bearer {bearer_token}"}
    seen, out = set(), []
    for w in range(1, max(1, weeks) + 1):
        r = requests.get(CAL_URL, params={"c": country, "w": w},
                         headers=headers, timeout=30)
        r.raise_for_status()
        for ev in r.json().get("data", []):
            key = (ev.get("title"), ev.get("date"))
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
    return out


def build_rows(conn: sqlite3.Connection, raw_events: list[dict]) -> list[dict]:
    """过滤到目标事件 + 已出 actual + 有 forecast → 算 consensus surprise。"""
    rows = []
    for ev in raw_events:
        spec = _match_spec(ev.get("title") or "")
        if spec is None:
            continue
        actual, forecast, prev = ev.get("actual"), ev.get("forecast"), ev.get("previous")
        if actual is None or forecast is None:
            continue  # 未出数 or 无 consensus → 跳过（前向轨只收齐全的）
        ts_ms = _iso_to_ms(ev["date"])
        scale = _actual_scale(conn, spec.event_type)
        surprise = round(float(actual) - float(forecast), 4)
        sz = round(surprise / scale, 4) if scale > 0 else surprise
        rows.append({
            "event_type": spec.event_type,
            "ref_month": _ref_month(ev.get("reference_date"), ts_ms),
            "release_date": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
            "release_ts_ms": ts_ms,
            "actual": float(actual),
            "forecast": float(forecast),
            "previous": float(prev) if prev is not None else None,
            "surprise": surprise,
            "surprise_z": sz,
            "surprise_source": "consensus",
        })
    return rows


# ----------------------------------------------------------------- 后台轮询
# 与 realtime_poll 同机制：独立后台任务，纯 REST，不碰那条单 WS。


def poll_once(bearer_token: str, db_path: str, weeks: int = 2) -> int:
    """拉日历 → 落库一次。同步，供 to_thread 调用与 CLI 复用。返回写入条数。"""
    from macropulse.attribution import macro_events
    raw = fetch_calendar(weeks=weeks, bearer_token=bearer_token)
    conn = sqlite3.connect(db_path)
    try:
        rows = build_rows(conn, raw)
        return macro_events.upsert(conn, rows)
    finally:
        conn.close()


async def _poll_loop(bearer_token: str, db_path: str,
                     weeks: int = 2, interval: int = POLL_INTERVAL):
    while True:
        try:
            n = await asyncio.to_thread(poll_once, bearer_token, db_path, weeks)
            if n:
                logger.info("📅 宏观日历前向：写入/更新 %d 条 consensus 事件", n)
        except Exception as e:  # noqa: BLE001 — 单轮失败不中断
            logger.warning("宏观日历轮询失败: %r", e)
        await asyncio.sleep(interval)


def start_macro_poller(bearer_token: str, db_path: str) -> asyncio.Task:
    """起一个每日宏观日历轮询任务（前向 consensus 累积 + Telegram 素材源）。"""
    task = asyncio.create_task(_poll_loop(bearer_token, db_path))
    logger.info("✅ 宏观日历前向轮询已启动（REST，每日）")
    return task
