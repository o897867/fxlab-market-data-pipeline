"""导入手抓的 investing 历史经济日历 → macro_releases 的真 consensus。

investing 复制格式（每事件两行）：
    DD/MM/YYYY (Mon)\\tHH:MM\\tACTUAL\\tFORECAST
    PREVIOUS
日期是发布日，(Mon) 是数据参照月 = 发布月 − 1。取 actual + forecast（同一时点首发值），
surprise = actual − forecast（鹰派为正）。actual/forecast 同源，避免 FRED 修订口径污染。

用法：
    python -m macropulse.attribution.consensus_import CPI pct data/consensus_raw/cpi.txt
    python -m macropulse.attribution.consensus_import NFP k   data/consensus_raw/nfp.txt
event_type ∈ {CPI, CoreCPI, CorePCE, NFP}；unit ∈ {pct, k}。
"""

from __future__ import annotations

import re
import sys
import sqlite3
from datetime import date

from macropulse import config
from macropulse.attribution.macro_events import TABLE, ensure_table

_DATE_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})")          # 10/06/2026
_DATE_NAME = re.compile(r"^([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})")  # Jun 10, 2026
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _parse_date(line: str) -> date | None:
    m = _DATE_SLASH.match(line)
    if m:
        dd, mm, yyyy = m.groups()
        return date(int(yyyy), int(mm), int(dd))
    m = _DATE_NAME.match(line)
    if m:
        mon, dd, yyyy = m.groups()
        if mon in _MONTHS:
            return date(int(yyyy), _MONTHS[mon], int(dd))
    return None


def _num(tok: str, unit: str) -> float | None:
    tok = tok.strip().replace("%", "").replace(",", "").replace("K", "").replace("k", "")
    if tok in ("", "-", "—"):
        return None
    try:
        return float(tok)
    except ValueError:
        return None


_LABEL = re.compile(r"\(([A-Z][a-z]{2})\)")


def _ref_month(rel: date, line: str) -> str:
    """参照月：优先用行内 (Mon) 标签（停摆延迟发布时'发布月−1'会错），
    年份 = 该标签月 ≤ 发布月则同年、否则上一年。无标签则退回发布月−1。"""
    lm = _LABEL.search(line)
    if lm and lm.group(1) in _MONTHS:
        mon = _MONTHS[lm.group(1)]
        year = rel.year if mon <= rel.month else rel.year - 1
        return date(year, mon, 1).isoformat()
    y, m = (rel.year - 1, 12) if rel.month == 1 else (rel.year, rel.month - 1)
    return date(y, m, 1).isoformat()


def parse_investing(text: str, unit: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        rel = _parse_date(line.strip())
        if rel is None:
            continue  # previous 行 / 表头 / 空行
        parts = line.split("\t")
        actual = _num(parts[2], unit) if len(parts) > 2 else None
        forecast = _num(parts[3], unit) if len(parts) > 3 else None
        rows.append({"ref_month": _ref_month(rel, line), "release_date": rel.isoformat(),
                     "actual": actual, "forecast": forecast})
    return rows


def import_rows(conn: sqlite3.Connection, event_type: str, rows: list[dict]) -> dict:
    ensure_table(conn)
    matched = updated = skipped = 0
    for r in rows:
        if r["actual"] is None or r["forecast"] is None:
            skipped += 1
            continue
        exists = conn.execute(
            f"SELECT 1 FROM {TABLE} WHERE event_type=? AND ref_month=?",
            (event_type, r["ref_month"])).fetchone()
        if not exists:
            skipped += 1  # 该月不在我们的事件集（如 SOFR 覆盖外）
            continue
        matched += 1
        surprise = round(r["actual"] - r["forecast"], 4)
        conn.execute(
            f"""UPDATE {TABLE} SET actual=?, forecast=?, surprise=?, surprise_source='consensus'
                WHERE event_type=? AND ref_month=?""",
            (r["actual"], r["forecast"], surprise, event_type, r["ref_month"]))
        updated += 1
    conn.commit()
    _recompute_z(conn, event_type)
    return {"parsed": len(rows), "matched": matched, "updated": updated, "skipped": skipped}


def _recompute_z(conn: sqlite3.Connection, event_type: str):
    """按 event_type 把 consensus surprise 缩放进 surprise_z。

    **只除标准差、不减均值**：surprise=actual−forecast 的中性点是 0（如期），
    减样本均值会把零点挪走、令 sign 失真，且是样本内 lookahead。仅做尺度归一，
    保证 sign(surprise_z)==sign(surprise)。
    """
    vals = [r[0] for r in conn.execute(
        f"SELECT surprise FROM {TABLE} WHERE event_type=? AND surprise_source='consensus' "
        f"AND surprise IS NOT NULL", (event_type,))]
    if len(vals) < 4:
        return
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0  # 围绕均值的离散度作尺度
    conn.execute(
        f"""UPDATE {TABLE} SET surprise_z = ROUND(surprise / ?, 4)
            WHERE event_type=? AND surprise_source='consensus' AND surprise IS NOT NULL""",
        (sd, event_type))
    conn.commit()


def main(argv=None):
    argv = argv or sys.argv[1:]
    event_type, unit, path = argv[0], argv[1], argv[2]
    text = open(path, encoding="utf-8").read()
    rows = parse_investing(text, unit)
    conn = sqlite3.connect(config.PRICE_DB_PATH)
    try:
        stats = import_rows(conn, event_type, rows)
    finally:
        conn.close()
    print(f"{event_type}: 解析 {stats['parsed']} | 匹配入库 {stats['updated']} | "
          f"跳过(无值/不在集) {stats['skipped']}")


if __name__ == "__main__":
    main()
