"""Phase 0 抽取层：拉 InsightSentry 三端点 → 当前链快照落 Parquet。

三个源各落一份 Parquet（quotes / contracts / underlying），**故意不在这里 join**——
按 doc，两源(quotes⋈contracts on code)的 join 是 dbt int_option_chain 的活。

  python -m option.extract NASDAQ:MU --exp-from 2026-07-01 --exp-to 2026-07-31 --range 20
  python -m option.extract            # 用 config.DEFAULT_SYMBOLS，到期窗默认未来 ~6 周

输出：data/snapshots/{quotes,contracts,underlying}/{SYM}_{YYYYMMDD}.parquet
"""

from __future__ import annotations

import os
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd

from option import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("option.extract")

_HEADERS = {"Authorization": f"Bearer {config.IS_TOKEN}"}


def _get(path: str, params: dict) -> dict:
    r = requests.get(f"{config.IS_BASE_URL}/{path}", params=params,
                     headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _paginate(path: str, params: dict) -> tuple[list, int | None]:
    """翻 next_token 直到取完。返回 (全部 data 行, last_update)。"""
    rows, last_update, token = [], None, None
    while True:
        p = dict(params)
        if token:
            p["next_token"] = token
        d = _get(path, p)
        rows.extend(d.get("data", []))
        last_update = d.get("last_update", last_update)
        token = d.get("next_token")
        if not token:
            break
    return rows, last_update


def fetch_underlying(code: str) -> dict:
    d = _get("symbols/quotes", {"codes": code})
    arr = d.get("data", d) if isinstance(d, dict) else d
    row = arr[0] if isinstance(arr, list) and arr else (arr or {})
    return {"code": code, "last_price": row.get("last_price") or row.get("last")}


def fetch_quotes(code: str, exp_from: str, exp_to: str, range_pct: int) -> tuple[list, int | None]:
    return _paginate("options/quotes", {
        "code": code, "from": exp_from, "to": exp_to, "range": range_pct})


def fetch_contracts(code: str, exp_from: str, exp_to: str, range_pct: int) -> tuple[list, int | None]:
    return _paginate("options/contracts", {
        "code": code, "from": exp_from, "to": exp_to, "range": range_pct})


_QUOTE_COLS = ["code", "type", "strike_price", "expiration", "bid_price", "ask_price",
               "implied_volatility", "bid_iv", "ask_iv", "delta", "gamma", "theta",
               "vega", "rho", "theoretical_price"]
_CONTRACT_COLS = ["code", "type", "strike_price", "expiration", "open_interest",
                  "open_interest_date", "close_price", "multiplier", "style", "status"]


def _write(df: pd.DataFrame, table: str, sym_tag: str, day: str) -> str:
    out_dir = os.path.join(config.SNAPSHOT_DIR, table)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{sym_tag}_{day}.parquet")
    df.to_parquet(path, engine="pyarrow", index=False)
    return path


def snapshot(code: str, exp_from: str, exp_to: str, range_pct: int) -> dict:
    """拉一个标的的当前链快照，三源各落一份 Parquet。返回核对摘要。"""
    sym_tag = code.split(":")[-1]
    und = fetch_underlying(code)
    spot = und["last_price"]
    quotes, q_upd = fetch_quotes(code, exp_from, exp_to, range_pct)
    contracts, c_upd = fetch_contracts(code, exp_from, exp_to, range_pct)

    snap_ms = q_upd or c_upd or int(time.time() * 1000)
    snap_ts = datetime.fromtimestamp(snap_ms / 1000, tz=timezone.utc).isoformat()
    day = datetime.fromtimestamp(snap_ms / 1000, tz=timezone.utc).strftime("%Y%m%d")

    qdf = pd.DataFrame(quotes).reindex(columns=_QUOTE_COLS)
    qdf.insert(0, "underlying_code", code)
    qdf["spot"] = spot
    qdf["snapshot_ts"] = snap_ts

    cdf = pd.DataFrame(contracts).reindex(columns=_CONTRACT_COLS)
    cdf.insert(0, "underlying_code", code)
    cdf["snapshot_ts"] = snap_ts

    udf = pd.DataFrame([{"code": code, "last_price": spot, "snapshot_ts": snap_ts}])

    paths = {
        "quotes": _write(qdf, "quotes", sym_tag, day),
        "contracts": _write(cdf, "contracts", sym_tag, day),
        "underlying": _write(udf, "underlying", sym_tag, day),
    }
    return {"code": code, "spot": spot, "snapshot_ts": snap_ts,
            "n_quotes": len(qdf), "n_contracts": len(cdf),
            "expirations": sorted(cdf["expiration"].dropna().astype(str).unique().tolist()),
            "paths": paths}


def _verify(summ: dict):
    """字段核对：人工 sanity check。"""
    print(f"\n  ── {summ['code']}  spot={summ['spot']}  @ {summ['snapshot_ts']} ──")
    print(f"     quotes 行 {summ['n_quotes']} | contracts 行 {summ['n_contracts']}")
    print(f"     到期日 {len(summ['expirations'])} 个: {summ['expirations'][:6]}{'...' if len(summ['expirations'])>6 else ''}")
    for k, v in summ["paths"].items():
        print(f"     -> {os.path.relpath(v)}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="option.extract")
    p.add_argument("symbols", nargs="*", help="EXCHANGE:SYM（省略则用 config.DEFAULT_SYMBOLS）")
    p.add_argument("--exp-from", default=None, help="到期下界 YYYY-MM-DD（默认今天）")
    p.add_argument("--exp-to", default=None, help="到期上界 YYYY-MM-DD（默认 +45 天）")
    p.add_argument("--range", type=int, default=config.DEFAULT_RANGE_PCT, help="现价±range%% 行权价")
    args = p.parse_args(argv)

    today = datetime.now(timezone.utc).date()
    exp_from = args.exp_from or today.isoformat()
    exp_to = args.exp_to or (today + timedelta(days=45)).isoformat()
    symbols = args.symbols or config.DEFAULT_SYMBOLS

    logger.info("快照窗口 到期 %s → %s, range ±%d%%, %d 只标的", exp_from, exp_to, args.range, len(symbols))
    for i, code in enumerate(symbols):
        try:
            summ = snapshot(code.strip(), exp_from, exp_to, args.range)
            _verify(summ)
        except Exception as e:  # noqa: BLE001
            # 单只失败不阻塞整个 watchlist——继续攒其余票的历史。
            logger.error("%s 快照失败: %r", code, e)
        # 票间节流防 rate limit（末票后不必再睡）。
        if i < len(symbols) - 1:
            time.sleep(config.EXTRACT_SLEEP_SEC)


if __name__ == "__main__":
    main()
